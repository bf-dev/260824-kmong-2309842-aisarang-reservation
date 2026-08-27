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
        여유           ARRIVAL_SAFETY_MS = 250ms
        목표 도착      434.6 + 250 = 684.6ms  (정각 뒤)
    """
    got = _measured(869.2).safe_arrival_after(config.ARRIVAL_SAFETY_MS / 1000.0)
    assert abs(got * 1000.0 - 684.6) < 0.5, got * 1000.0

    # 그날 네 번의 측정 전부. 어느 것도 -296ms 근처로 돌아가지 않는다.
    for u in (868.1, 843.0, 847.3, 869.2):
        ms = _measured(u).safe_arrival_after() * 1000.0
        assert 660.0 < ms < 690.0, (u, ms)


def test_a_tighter_clock_aims_closer_to_the_hour():
    """오차가 줄면 조준도 정각 쪽으로 당겨진다. 상수가 아니라 측정값이다."""
    loose = _measured(869.2).safe_arrival_after()
    mid = _measured(500.0).safe_arrival_after()
    assert mid < loose
    assert abs(mid * 1000.0 - (250.0 + config.ARRIVAL_SAFETY_MS)) < 0.5

    # CI 러너처럼 아주 잘 맞은 시계(uncertainty 133.2ms)면 66.6 + 250 = 316.6ms
    # 인데, 바닥값이 그것보다 크므로 바닥값으로 간다. 늦는 쪽이 안전한 방향이다.
    tight = _measured(133.2).safe_arrival_after()
    assert tight * 1000.0 == config.ARRIVAL_MIN_AFTER_MS
    assert tight < mid


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
    assert data["arrival_after_ms"] == 0          # 0 = 측정값으로 자동
    assert data["use_hours"] == 9                 # 나머지 설정은 그대로 산다


def test_the_runner_turns_the_measurement_into_an_aim():
    """Runner._arrival_aim: 기본은 자동, 고객이 고정값을 넣으면 그 값(범위 안)."""
    from aisarang.runner import Runner

    r = Runner()
    r.clock = _measured(869.2)
    auto = r._arrival_aim(dict(config.DEFAULT_SETTINGS))
    assert abs(auto * 1000.0 - 684.6) < 0.5

    assert r._arrival_aim({"arrival_after_ms": 900}) == 0.9
    # 범위 밖 값은 잘린다. 사용자가 실수로 -300 을 넣어도 정각 앞으로 못 간다.
    assert r._arrival_aim({"arrival_after_ms": -300}) == auto
    assert r._arrival_aim({"arrival_after_ms": 99999}) \
        == config.ARRIVAL_MAX_AFTER_MS / 1000.0
