# -*- coding: utf-8 -*-
"""맞춰야 하는 것은 '발사 시각'이 아니라 '도착 시각'이다.

고객이 손으로 성공시킬 때 누른 시각은 08:59:59.xxx 였다. 즉 요청이 서버에
닿는 순간이 정각 언저리여야 한다. 로컬에서 정각에 쏘면 편도지연만큼 늦게
도착한다. 그래서 편도지연을 빼고 쏜다.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import clock as clockmod


def _clock(offset=0.0, rtt=0.040):
    c = clockmod.ClockSync()
    c.offset = offset
    c.rtt_best = rtt
    c.lo, c.hi = offset - 0.01, offset + 0.01
    c.samples = 8
    c.synced = True
    return c


def test_one_way_is_half_the_best_rtt():
    assert _clock(rtt=0.040).one_way == 0.020


def test_unmeasured_rtt_does_not_shift_anything():
    c = clockmod.ClockSync()
    assert c.one_way == 0.0


def test_fire_is_earlier_than_the_wanted_arrival_by_one_way():
    c = _clock(offset=0.0, rtt=0.040)
    arrival = 1_800_000_000.0
    assert abs(c.local_fire_for_arrival(arrival) - (arrival - 0.020)) < 1e-9


def test_server_offset_and_one_way_both_apply():
    c = _clock(offset=1.5, rtt=0.100)          # 서버가 로컬보다 1.5초 빠름
    arrival = 1_800_000_000.0
    # 로컬시각 = 서버시각 - offset, 거기서 편도(50ms)만큼 더 앞당긴다
    assert abs(c.local_fire_for_arrival(arrival) - (arrival - 1.5 - 0.050)) < 1e-9


def test_arrival_is_the_inverse_of_fire():
    c = _clock(offset=-0.3, rtt=0.080)
    arrival = 1_800_000_000.0
    fire = c.local_fire_for_arrival(arrival)
    assert abs(c.arrival_for_local_fire(fire) - arrival) < 1e-9


def test_firing_at_the_open_instant_would_arrive_late():
    """예전 방식(로컬에서 정각에 발사)은 편도지연만큼 늦게 도착한다."""
    c = _clock(offset=0.0, rtt=0.060)
    open_epoch = 1_800_000_000.0
    late = c.arrival_for_local_fire(c.local_time_for(open_epoch)) - open_epoch
    assert abs(late - 0.030) < 1e-6      # float64 로 epoch 를 다루는 만큼의 오차


def test_sleep_until_local_is_accurate():
    target = time.time() + 0.25
    clockmod.sleep_until_local(target)
    assert 0 <= time.time() - target < 0.02


def test_sleep_until_arrival_wakes_one_way_early():
    c = _clock(offset=0.0, rtt=0.200)          # 편도 100ms
    arrival = time.time() + 0.35
    clockmod.sleep_until_arrival(c, arrival)
    fired = time.time()
    assert -0.02 < (arrival - fired) - 0.100 < 0.02


def test_describe_reports_the_one_way_estimate():
    assert "편도 추정 20ms" in _clock(rtt=0.040).describe()


# ------------------------------- 조준점이 정각 '앞' 에서 '뒤' 로 옮겨졌다 (v1.0.9)
#
# 2026-08-27 09:00:00, 인계 모드의 첫 실전 발사가 v1.0.8 의 조준값 때문에
# 확정 실패했다 (고객 PC 진단 ZIP `…-20260827-090021.zip`):
#
#   [확인] 1발째 · 도착 추정 정각 -296ms
#          · 서버: 알림 아직 예약 가능한 시간이 아닙니다. 확인 [too_early]
#
# 서버는 자기 시계로 09:00:00.000 전에 닿은 요청을 그냥 버린다. 그러니
# -300ms 조준은 어떤 날에도 실패한다. 조준점은 정각 뒤여야 한다.

from aisarang import config                                       # noqa: E402


def _measured(uncertainty_ms: float, rtt_ms: float = 739.6):
    """2026-08-27 고객 PC 에서 실제로 나온 모양의 측정값."""
    c = clockmod.ClockSync()
    c.offset = -1.3193
    c.rtt_best = rtt_ms / 1000.0
    c.lo = c.offset - uncertainty_ms / 2000.0
    c.hi = c.offset + uncertainty_ms / 2000.0
    c.samples = 12
    c.synced = True
    return c


def test_the_aim_is_after_the_hour_never_before():
    """어떤 측정값에서도 목표 도착은 정각 뒤다. 이 한 줄이 v1.0.9 의 전부다."""
    for u in (0.0, 50.0, 133.2, 843.0, 869.2, 5000.0):
        assert _measured(u).safe_arrival_after() > 0


def test_the_aim_is_computed_from_the_measured_uncertainty():
    """2026-08-27 의 실측값으로 산수를 그대로 확인한다.

        마지막 재측정  uncertaintyMs = 869.2  → 한쪽 오차 434.6ms
        여유           ARRIVAL_SAFETY_MS = 140ms (v1.0.17, was 175)
        목표 도착      434.6 + 140 = 574.6ms  (정각 뒤)
    """
    got = _measured(869.2).safe_arrival_after(config.ARRIVAL_SAFETY_MS / 1000.0)
    assert abs(got * 1000.0 - 574.6) < 0.5, got * 1000.0

    # 그날 네 번의 측정 전부. 어느 것도 -296ms 근처로 돌아가지 않는다.
    for u in (868.1, 843.0, 847.3, 869.2):
        ms = _measured(u).safe_arrival_after() * 1000.0
        assert 550.0 < ms < 580.0, (u, ms)


def test_a_tighter_clock_aims_closer_to_the_hour():
    """오차가 줄면 조준도 정각 쪽으로 당겨진다. 상수가 아니라 측정값이다."""
    loose = _measured(869.2).safe_arrival_after()
    mid = _measured(500.0).safe_arrival_after()
    assert mid < loose
    assert abs(mid * 1000.0 - (250.0 + config.ARRIVAL_SAFETY_MS)) < 0.5

    # uncertainty 133.2ms → 66.6 + 140 = 206.6ms. 하한(140)보다 크므로
    # 계산값이 그대로 쓰인다.
    tight = _measured(133.2).safe_arrival_after()
    assert abs(tight * 1000.0 - 206.6) < 0.5, tight * 1000.0
    assert tight < mid
    assert tight * 1000.0 >= config.ARRIVAL_MIN_AFTER_MS


def test_the_customers_measured_clock_now_drives_the_aim_not_the_floor():
    """조준점을 정하는 것은 하한이 아니라 실측이어야 한다.

    v1.0.12 에서 하한을 350 → 250 으로 내려 이 성질을 만들었고, v1.0.15 는
    여유와 하한을 함께 175 로, v1.0.17 은 140 으로 내렸다. 하한이 여유보다
    크면 하한이 조준점을 혼자 정해버리므로 둘은 항상 같이 움직인다.

    고객 PC 실측(로그 원문):
      09-03  "시각 오차 ±27ms"   → 27 + 140 = 167ms
      09-04  "시각 오차 ±24ms"   → 24 + 140 = 164ms
      09-22  "시각 오차 ±28ms"   → 28 + 140 = 168ms  (그날은 203 이었다)
    """
    assert config.ARRIVAL_SAFETY_MS == 140.0
    assert config.ARRIVAL_MIN_AFTER_MS == 140.0     # 여유와 같이 내려야 한다
    assert config.ARRIVAL_MAX_AFTER_MS == 1200.0

    for half_ms, want in ((27.0, 167.0), (24.0, 164.0), (28.0, 168.0)):
        got = _measured(half_ms * 2).safe_arrival_after() * 1000.0
        assert abs(got - want) < 0.5, (half_ms, got)
        # 그래도 정각 뒤다. 최악(한쪽 오차만큼 이른 쪽)이어도 정각을 넘는다.
        assert got - half_ms >= config.ARRIVAL_SAFETY_MS - 0.5, (half_ms, got)


def test_the_0917_aim_actually_moved_earlier():
    """09-17 의 그 조건에서 조준이 250 → 175 → 140 으로 당겨졌는지 못박는다.

    고객 로그 원문(09-17): "조준 확정: 도착 목표 정각 +275ms (시각 오차 ±25ms
    + 여유 250ms)". 같은 측정값으로 v1.0.15 는 +200ms, v1.0.17 은 +165ms.
    """
    got = _measured(50.0).safe_arrival_after() * 1000.0     # ±25ms
    assert abs(got - 165.0) < 0.5, got
    assert got < 200.0, "조준이 당겨지지 않았다"
    assert abs((200.0 - got) - 35.0) < 0.5, got              # 이번 걸음 = 35ms


def test_the_0922_aim_moves_to_168ms():
    """이번 판의 요청 그 자체. 09-22 실전과 같은 조건에서 +168ms 여야 한다.

    고객 로그 원문(09-22 09:00): "조준 확정: 도착 목표 정각 +203ms (시각 오차
    ±28ms + 여유 175ms)". 여유만 140 으로 내렸으니 같은 아침에 +168ms.
    """
    got = _measured(56.0).safe_arrival_after() * 1000.0     # ±28ms
    assert abs(got - 168.0) < 0.5, got
    assert abs((203.0 - got) - 35.0) < 0.5, got


def test_a_worse_morning_pushes_the_aim_back_up_by_itself():
    """여유를 내려도 이른 쪽 위험이 늘지 않는 이유.

    앞쪽 항(uncertainty/2)이 살아 있어서, 시각이 덜 맞은 아침에는 조준점이
    자동으로 다시 뒤로 간다. 하한은 측정이 아주 좋게 나왔을 때의 바닥일 뿐이다.
    """
    pairs = [(24.0, 164.0), (100.0, 240.0), (200.0, 340.0), (435.0, 575.0)]
    last = 0.0
    for half_ms, want in pairs:
        got = _measured(half_ms * 2).safe_arrival_after() * 1000.0
        assert abs(got - want) < 0.5, (half_ms, got)
        assert got > last
        last = got


def test_the_aim_is_clamped_at_both_ends():
    assert _measured(0.0).safe_arrival_after(0.0) * 1000.0 \
        == config.ARRIVAL_MIN_AFTER_MS
    assert _measured(5000.0).safe_arrival_after() * 1000.0 \
        == config.ARRIVAL_MAX_AFTER_MS


def test_an_unmeasured_clock_aims_as_late_as_allowed():
    """시각을 못 쟀으면 모르는 것이다. 모를수록 늦게 쏜다."""
    assert clockmod.ClockSync().safe_arrival_after() * 1000.0 \
        == config.ARRIVAL_MAX_AFTER_MS


def test_the_dead_setting_cannot_come_back_from_an_old_settings_file(tmp_path,
                                                                    monkeypatch):
    """고객 PC 의 settings.json 에는 아직 arrival_lead_ms=300 이 들어 있다.

    그 값이 되살아나면 2026-08-27 이 그대로 반복된다. 죽은 키로 못박아 둔다.
    """
    import json

    monkeypatch.setattr(config, "settings_path",
                        lambda: tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(
        json.dumps({"arrival_lead_ms": 300, "prefire_ms": 300,
                    "use_hours": 9}, ensure_ascii=False), encoding="utf-8")
    data = config.load_settings()
    assert "arrival_lead_ms" not in data
    assert "prefire_ms" not in data
    assert "arrival_after_ms" not in data         # v1.0.18: 죽은 키
    assert data["use_hours"] == 9                 # 나머지 설정은 그대로 산다


def test_the_saved_safety_margin_can_no_longer_shadow_the_constant(tmp_path,
                                                                   monkeypatch):
    """**이번 판에서 제일 조용한 함정.** 상수만 내리면 고객 PC 는 안 바뀐다.

    고객 PC 의 settings.json 에는 v1.0.14 가 쓴 `arrival_safety_ms: 250` 이
    그대로 있다(save_settings 가 DEFAULT_SETTINGS 의 모든 키를 쓰기 때문이고,
    고객이 화면에서 이 값을 바꾼 적은 한 번도 없다). 예전 runner 는
    settings.get("arrival_safety_ms", 상수) 로 읽었으므로 파일의 250 이
    이겨서 조준이 275ms 에 그대로 머물렀을 것이다.

    v1.0.17: 파일에 남아 있을 수 있는 옛 값이 250 하나가 아니다. v1.0.15/16
    을 한 번이라도 돌린 PC 라면 175 가 들어 있다. 둘 다 못박는다.

    v1.0.18: `arrival_after_ms` 도 같은 죽은 키다. 2026-09-17 에 이 키 하나가
    새 조준을 그림자처럼 덮어써서 250ms 로 머문 사건이 있었다. 이번 판의
    -500ms 하루 실험도 같은 방식으로 무너질 수 있으므로 함께 못박는다.
    """
    import json

    from aisarang.runner import Runner

    monkeypatch.setattr(config, "settings_path",
                        lambda: tmp_path / "settings.json")

    for old in (250, 175):
        (tmp_path / "settings.json").write_text(
            json.dumps({"arrival_safety_ms": old, "arrival_after_ms": 250,
                        "reopen_max": 2,
                        "reopen_seconds": 15, "use_hours": 9},
                       ensure_ascii=False), encoding="utf-8")
        data = config.load_settings()
        for dead in ("arrival_safety_ms", "arrival_after_ms",
                     "reopen_max", "reopen_seconds"):
            assert dead not in data, (old, dead)
        assert data["use_hours"] == 9             # 진짜 고객 설정은 그대로 산다

        # 조준은 파일이 아니라 상수(정각 -500ms) 를 따른다. 측정값도 무관하다.
        r = Runner()
        r.clock = _measured(50.0)
        assert abs(r._arrival_aim(data) * 1000.0
                   - config.CONFIRM_PREHOUR_LEAD_MS) < 1e-9, old

        # 파일의 값을 억지로 다시 끼워 넣어도 이제 무시된다.
        stale = dict(data)
        stale["arrival_after_ms"] = old
        stale["arrival_safety_ms"] = old
        assert abs(r._arrival_aim(stale) * 1000.0
                   - config.CONFIRM_PREHOUR_LEAD_MS) < 1e-9, old

        # 그리고 읽고 나면 죽은 키는 디스크에서도 지워진다(v1.0.17).
        on_disk = json.loads((tmp_path / "settings.json").read_text(
            encoding="utf-8"))
        for dead in ("arrival_safety_ms", "arrival_after_ms",
                     "reopen_max", "reopen_seconds"):
            assert dead not in on_disk, (old, dead)
        assert on_disk["use_hours"] == 9


def test_the_default_settings_do_not_carry_a_dead_aim_key():
    """v1.0.18: DEFAULT_SETTINGS 에 arrival_after_ms 가 없어야 한다.

    save_settings 는 DEFAULT_SETTINGS 의 모든 키를 파일로 쓴다. 여기 남아
    있으면 다음 실행의 load_settings 가 다시 그림자 키를 만들어 낸다.
    """
    assert "arrival_after_ms" not in config.DEFAULT_SETTINGS
    assert "arrival_after_ms" in config._OBSOLETE
    assert "arrival_safety_ms" in config._OBSOLETE


def test_the_prehour_experiment_aim_is_minus_500ms():
    """이번 판의 요청 그 자체(2026-09-23 고객 요구 하루 실험).

    첫 발 [확인] 은 정각 500ms 전에 도착시킨다. 고객 3대 실험에서 정각 전
    클릭이 이겼고, 모바일 앱도 정각 직전 발사로 대기화면 없이 성공했다.
    서버가 '아직 예약 가능한 시간이 아닙니다' 로 거절하면 회복 발사가
    표준 조준(정각 +140ms)으로 다시 누른다.
    """
    from aisarang.runner import Runner

    assert config.CONFIRM_PREHOUR_LEAD_MS == -500.0
    assert config.ARRIVAL_SAFETY_MS == 140.0

    r = Runner()
    for u in (0.0, 50.0, 133.2, 869.2, 5000.0):
        # 측정값이 아무리 나빠도 조준은 상수다. 산술이 조준을 다시 정하지 않는다.
        r.clock = _measured(u)
        assert r._arrival_aim({}) * 1000.0 == -500.0, u
        assert r._arrival_aim(dict(config.DEFAULT_SETTINGS)) * 1000.0 == -500.0

    # 음수 조준이어도 발사 시각 변환은 정상(정각보다 이른 로컬 발사)이다.
    c = _clock(offset=0.0, rtt=0.040)
    open_epoch = 1_800_000_000.0
    fire = c.local_fire_for_arrival(open_epoch - 0.5)
    assert abs(fire - (open_epoch - 0.520)) < 1e-9
    assert abs(c.arrival_for_local_fire(fire) - (open_epoch - 0.5)) < 1e-9


def test_the_recovery_aim_stays_after_the_hour():
    """회복 발사의 조준은 정각 뒤(+140ms) 여야 한다. 정각 전 재발사를 못박는다."""
    assert config.ARRIVAL_SAFETY_MS == 140.0
    c = _clock(offset=0.0, rtt=0.040)
    open_epoch = 1_800_000_000.0
    recovery = c.local_fire_for_arrival(
        open_epoch + config.ARRIVAL_SAFETY_MS / 1000.0)
    assert c.arrival_for_local_fire(recovery) > open_epoch


def test_the_runner_ignores_any_setting_when_it_aims():
    """Runner._arrival_aim 은 settings 를 아예 읽지 않는다(상수 전용)."""
    from aisarang.runner import Runner

    r = Runner()
    r.clock = _measured(869.2)
    for junk in ({"arrival_after_ms": 900},
                 {"arrival_after_ms": -300},
                 {"arrival_after_ms": 99999},
                 {"arrival_safety_ms": 250},
                 {"arrival_lead_ms": 300, "prefire_ms": 300}):
        assert r._arrival_aim(junk) == config.CONFIRM_PREHOUR_LEAD_MS / 1000.0
    assert r._arrival_aim(None) == config.CONFIRM_PREHOUR_LEAD_MS / 1000.0
