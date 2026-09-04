# -*- coding: utf-8 -*-
"""서버 시각 동기화 로직 검증.

핵심 주장: Date 헤더는 초 단위인데도 구간 교집합으로 초 이하까지 좁혀진다.
가짜 서버(진짜 offset 을 알고 있는)를 세워 실제로 좁혀지는지 확인한다.
"""
import datetime as dt
import email.utils
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import clock as clockmod, config


class FakeResponse:
    def __init__(self, date_header):
        self.headers = {"Date": date_header}


class FakeSession:
    """서버 시각 = 로컬 + true_offset, 왕복 rtt 인 가짜 서버."""

    def __init__(self, true_offset, rtt=0.02):
        self.true_offset = true_offset
        self.rtt = rtt

    def head(self, url, **kw):
        time.sleep(self.rtt)
        server_now = time.time() + self.true_offset
        whole = int(server_now)  # 서버는 초 단위로만 알려준다
        stamp = email.utils.formatdate(whole, usegmt=True)
        return FakeResponse(stamp)


def test_sync_converges_within_rtt():
    true_offset = 0.734
    s = FakeSession(true_offset, rtt=0.02)
    out = clockmod.sync(session=s, samples=14, log=lambda *_: None)
    assert out.synced
    # 좁혀진 구간 안에 진짜 offset 이 들어 있어야 한다
    assert out.lo <= true_offset <= out.hi
    # 초 단위 헤더인데도 100ms 안쪽으로 좁혀져야 한다
    assert out.uncertainty < 0.2, out.uncertainty
    assert abs(out.offset - true_offset) < 0.12


def test_sync_handles_negative_offset():
    true_offset = -1.45
    s = FakeSession(true_offset, rtt=0.03)
    out = clockmod.sync(session=s, samples=14, log=lambda *_: None)
    assert out.lo <= true_offset <= out.hi
    assert abs(out.offset - true_offset) < 0.15


def test_high_rtt_widens_but_still_brackets():
    true_offset = 0.2
    s = FakeSession(true_offset, rtt=0.6)
    out = clockmod.sync(session=s, samples=10, log=lambda *_: None)
    assert out.lo <= true_offset <= out.hi


def test_next_open_is_future_and_at_9am_kst():
    c = clockmod.ClockSync(offset=0.0, synced=True, lo=0, hi=0)
    epoch = clockmod.next_open_epoch(c)
    assert epoch > time.time()
    kst = dt.datetime.fromtimestamp(epoch + config.KST_OFFSET_SECONDS, dt.timezone.utc)
    assert kst.hour == 9 and kst.minute == 0 and kst.second == 0
    # 다음 09시는 24시간 이내
    assert epoch - time.time() <= 86400 + 1


def test_target_date_is_lead_days_after_open_day():
    c = clockmod.ClockSync(offset=0.0, synced=True, lo=0, hi=0)
    open_epoch = clockmod.next_open_epoch(c)
    target = clockmod.target_date_for(c, 14, open_epoch=open_epoch)
    open_kst = dt.datetime.fromtimestamp(open_epoch + config.KST_OFFSET_SECONDS, dt.timezone.utc)
    expect = (open_kst + dt.timedelta(days=14)).strftime("%Y%m%d")
    assert target == expect
    assert len(target) == 8 and target.isdigit()


def test_sleep_until_is_accurate():
    c = clockmod.ClockSync(offset=0.0, synced=True, lo=0, hi=0)
    target = time.time() + 0.4
    clockmod.sleep_until(c, target)
    drift = time.time() - target
    assert 0 <= drift < 0.05, drift


def test_server_now_applies_offset():
    c = clockmod.ClockSync(offset=12.5, synced=True, lo=12, hi=13)
    assert abs(c.server_now() - (time.time() + 12.5)) < 0.05
    assert abs(c.local_time_for(1000.0) - (1000.0 - 12.5)) < 1e-6


def test_unsynced_clock_reports_it():
    c = clockmod.ClockSync()
    assert "실패" in c.describe()


# ------------------------------------------------------------- 재측정 (v1.0.6)
#
# 고객은 전날 오후에 켜두고 다음 날 09시를 기다린다. 한 번 잰 오프셋을 18시간
# 들고 가면 그만큼 낡는다. 그래서 5분마다 다시 잰다.

class DriftingSession(FakeSession):
    """호출할 때마다 서버 시계가 조금씩 벌어지는 가짜 서버."""

    def __init__(self, true_offset, rtt=0.01, drift_per_call=0.0):
        super().__init__(true_offset, rtt)
        self.drift_per_call = drift_per_call
        self.calls = 0

    def head(self, url, **kw):
        self.calls += 1
        self.true_offset += self.drift_per_call
        return super().head(url, **kw)


class DeadSession:
    def head(self, url, **kw):
        raise OSError("network down")


def test_resync_adopts_the_fresh_measurement_and_keeps_the_correction():
    c = clockmod.sync(session=FakeSession(0.30, rtt=0.01), samples=12,
                      log=lambda *_: None)
    c.note_too_early(0.12)                       # 실전에서 배운 보정
    learned = c.correction
    assert learned > 0

    fresh = clockmod.sync(session=FakeSession(-0.45, rtt=0.01), samples=12,
                          log=lambda *_: None)
    out = c.adopt(fresh)

    assert out["adopted"] is True
    assert abs(c.offset - (-0.45)) < 0.12, c.offset
    assert c.resyncs == 1 and len(c.history) == 1
    # 서버 동작에 대한 학습은 측정과 무관하므로 그대로 남는다.
    assert c.correction == learned
    # 옛 구간과 또 교집합하지 않는다(그랬다면 새 offset 이 옛 구간에 갇힌다).
    assert c.lo <= -0.45 <= c.hi


def test_a_failed_resync_keeps_the_last_good_offset():
    c = clockmod.sync(session=FakeSession(0.25, rtt=0.01), samples=12,
                      log=lambda *_: None)
    good = c.offset
    dead = clockmod.sync(session=DeadSession(), samples=3, log=lambda *_: None)
    assert not dead.synced
    out = c.adopt(dead)
    assert out["adopted"] is False
    assert c.offset == good and c.synced and c.resyncs == 0


def test_keeper_remeasures_on_its_interval_and_follows_the_drift():
    sess = DriftingSession(0.10, rtt=0.005, drift_per_call=0.004)
    c = clockmod.sync(session=sess, samples=12, log=lambda *_: None)
    lines = []
    keeper = clockmod.ClockKeeper(c, interval=5.0, samples=8,
                                  log=lines.append, session_factory=lambda: sess)
    keeper.start()
    try:
        deadline = time.time() + 20.0
        while c.resyncs < 3 and time.time() < deadline:
            keeper.request_now("테스트")
            time.sleep(1.5)
    finally:
        keeper.stop()
    assert c.resyncs >= 3, (c.resyncs, lines)
    assert sum("재측정" in s for s in lines) >= 3, lines
    # 서버가 앞으로 흘러갔으면 오프셋도 따라가야 한다.
    assert c.offset > 0.10


def test_keeper_never_measures_inside_the_quiet_window_before_the_fire():
    sess = FakeSession(0.0, rtt=0.005)
    c = clockmod.sync(session=sess, samples=12, log=lambda *_: None)
    lines = []
    keeper = clockmod.ClockKeeper(
        c, interval=5.0, samples=6, log=lines.append,
        session_factory=lambda: sess,
        quiet_seconds=90.0,
        quiet_server_epoch=c.server_now() + 30.0)   # 정각이 30초 뒤 = 이미 정숙구간
    assert keeper.in_quiet_window() is True
    assert keeper.sync_now("정각 직전") is False
    assert c.resyncs == 0
    keeper.start()
    try:
        keeper.request_now("정각 직전")
        time.sleep(0.5)
    finally:
        keeper.stop()
    assert c.resyncs == 0, "정각 직전에는 절대 재측정하지 않는다"
    assert any("멈춥니다" in s for s in lines), lines


def test_keeper_survives_a_dead_network_and_reports_it():
    c = clockmod.sync(session=FakeSession(0.2, rtt=0.005), samples=12,
                      log=lambda *_: None)
    good = c.offset
    lines = []
    keeper = clockmod.ClockKeeper(c, interval=5.0, samples=3, log=lines.append,
                                  session_factory=DeadSession)
    assert keeper.sync_now("망 끊김", force=True) is False
    assert c.offset == good and c.synced
    assert any("실패" in s and "그대로 씁니다" in s for s in lines), lines


def test_a_single_drift_sample_never_moves_the_offset():
    c = clockmod.sync(session=FakeSession(0.3, rtt=0.01), samples=12,
                      log=lambda *_: None)
    before = c.offset
    t0 = time.time()
    t1 = t0 + 0.02
    server_second = float(int(t0 + 0.3))          # 서버가 알려준 초
    note = c.note_drift_sample(server_second, t0, t1)
    assert note["usable"] and note["consistent"]
    assert c.offset == before


def test_a_real_drift_is_flagged_but_still_does_not_move_the_offset():
    c = clockmod.sync(session=FakeSession(0.3, rtt=0.01), samples=12,
                      log=lambda *_: None)
    before = c.offset
    t0 = time.time()
    note = c.note_drift_sample(float(int(t0 + 5.0)), t0, t0 + 0.02)
    assert note["usable"] and not note["consistent"]
    assert abs(note["deviationMs"]) > 1000
    assert c.offset == before


def test_the_shipped_interval_is_five_minutes():
    """고객에게 '5분' 이라고 답했다. 코드가 그 값이어야 한다."""
    assert config.RESYNC_SECONDS == 300
    assert config.SESSION_TOUCH_SECONDS == config.RESYNC_SECONDS
    c = clockmod.ClockSync(offset=0.0, synced=True, lo=0, hi=0)
    assert clockmod.ClockKeeper(c)._every() == "5분마다"


# ------------------------------------------------------- v1.0.10: 밀리초 서버시각
#
# childcare.go.kr 은 eGovFrame 세션 필터가 모든 동적 응답에
# `Set-Cookie: egovLatestServerTime=<epoch ms>` 를 붙인다. 이 값이 있으면
# Date 헤더의 1초 양자화가 사라지고, 한 발의 구간 폭이 1초+왕복 -> 왕복이 된다.
#
# 2026-09-01 이 서버에서 실측한 헤더(그대로):
#   Date: Tue, 01 Sep 2026 00:15:08 GMT
#   Set-Cookie: WMONID=...; Expires=...; Path=/;SameSite=None;Secure;,
#               JSESSIONID=...; path=/; HttpOnly;SameSite=None;Secure;,
#               egovExpireSessionTime=1788225308489; path=/; secure;SameSite=None;Secure;,
#               egovLatestServerTime=1788221708489; path=/; secure;SameSite=None;Secure;
REAL_SET_COOKIE = (
    "WMONID=Z1YjKO97WCV; Expires=Wed, 01-Sep-2027 09:15:08 GMT; "
    "Path=/;SameSite=None;Secure;, "
    "JSESSIONID=kQyKBKDR4wJQvoCFW1zkaUxOgQ8lwWB8Rf9aQ02s.pcms71; path=/; "
    "HttpOnly;SameSite=None;Secure;, "
    "egovExpireSessionTime=1788225308489; path=/; secure;SameSite=None;Secure;, "
    "egovLatestServerTime=1788221708489; path=/; secure;SameSite=None;Secure;"
)


class MsResponse:
    def __init__(self, date_header, server_ms):
        self.headers = {
            "Date": date_header,
            "Set-Cookie": (f"WMONID=abc; Path=/;SameSite=None;Secure;, "
                           f"egovExpireSessionTime={server_ms + 3600000}; path=/;, "
                           f"egovLatestServerTime={server_ms}; path=/; secure;"),
        }


class MsSession:
    """밀리초 서버시각 쿠키까지 붙여주는 가짜 서버.

    req_leg / resp_leg 로 편도 지연을 비대칭으로 줄 수 있다. 실측(2026-09-01)이
    바로 그런 모양이었다: 요청쪽 127ms, 응답쪽 25ms.
    """

    def __init__(self, true_offset, req_leg=0.05, resp_leg=0.01):
        self.true_offset = true_offset
        self.req_leg = req_leg
        self.resp_leg = resp_leg

    def head(self, url, **kw):
        time.sleep(self.req_leg)
        server_now = time.time() + self.true_offset
        time.sleep(self.resp_leg)
        whole = int(server_now)
        return MsResponse(email.utils.formatdate(whole, usegmt=True),
                          int(round(server_now * 1000)))


def test_the_real_set_cookie_header_yields_millisecond_server_time():
    """실측 헤더 원문에서 밀리초 시각이 나와야 한다. 지어낸 문자열이 아니다."""
    v = clockmod._parse_server_ms({"Set-Cookie": REAL_SET_COOKIE})
    assert v == 1788221708.489
    # Date 헤더가 가리키는 초와 같은 초여야 한다(같은 응답의 두 시계).
    d = clockmod._parse_date_header("Tue, 01 Sep 2026 00:15:08 GMT")
    assert int(v) == int(d)
    # egovExpireSessionTime 을 잘못 집으면 1시간 틀린다.
    assert v != 1788225308.489


def test_millisecond_time_is_ignored_when_absent_or_absurd():
    assert clockmod._parse_server_ms({"Set-Cookie": "JSESSIONID=x; path=/"}) is None
    assert clockmod._parse_server_ms({}) is None
    assert clockmod._parse_server_ms(
        {"Set-Cookie": "egovLatestServerTime=1; path=/"}) is None
    assert clockmod._parse_server_ms(
        {"Set-Cookie": "egovLatestServerTime=99999999999999; path=/"}) is None


def test_the_shipped_v1_0_10_measurement_is_much_tighter_than_v1_0_9():
    """**출하 설정끼리** 비교한다. 이것이 v1.0.10 의 전부다.

    v1.0.9  Date 헤더(1초) + `/?menuno=1`(무거운 JSP). 고객 PC 실측 왕복
            780~1060ms, 잔여 폭 869ms → 한쪽 오차 ±435ms → 조준점 685ms.
            왕복이 표본 간격과 비슷해서 초 경계 위상이 겹쳐 잘 안 좁혀진다.
    v1.0.10 밀리초 쿠키 + config.CLOCK_PROBE_PATH(가벼운 경로). 이 서버 실측
            왕복 150ms, 잔여 폭 123~273ms.

    두 변화(1초 양자화 제거, 가벼운 경로)는 한 묶음이다. 밀리초 시각이
    **요청이 들어온 순간**에 찍히기 때문에 렌더링이 싼 경로를 골라도 되고,
    그래서 왕복이 작아진다. 아래 숫자는 그 두 가지를 같이 재현한 것이다.
    """
    true_offset = 0.412
    old = clockmod.sync(session=FakeSession(true_offset, rtt=0.94),
                        samples=8, log=lambda *_: None)
    new = clockmod.sync(session=MsSession(true_offset, req_leg=0.13, resp_leg=0.02),
                        samples=12, log=lambda *_: None)

    assert old.resolution == "date" and new.resolution == "ms"
    # 둘 다 진짜 offset 을 품고 있어야 한다(좁히다가 놓치면 안 된다).
    assert old.lo <= true_offset <= old.hi
    assert new.lo <= true_offset <= new.hi
    assert new.uncertainty < 0.25, new.uncertainty
    assert old.uncertainty > 0.6, old.uncertainty
    assert old.uncertainty > new.uncertainty * 3, (old.uncertainty, new.uncertainty)
    # 그리고 그것이 곧 조준점 차이다.
    assert old.safe_arrival_after() > 0.6
    assert new.safe_arrival_after() <= 0.45


def test_one_sample_carries_a_whole_second_of_doubt_only_on_the_date_path():
    """한 발이 주는 구간 폭. 여기가 v1.0.10 이 건드린 정확한 지점이다.

        Date 헤더  offset ∈ [S - t1, S + 1 - t0]   폭 = **1초** + 왕복
        밀리초     offset ∈ [S - t1, S - t0]       폭 = 왕복

    여러 발을 교집합해 그 1초를 깎는 게 v1.0.9 의 전략이었는데, 왕복이
    표본 간격만큼 크면 위상이 겹쳐서 잘 안 깎인다(고객 PC 에서 12발을 쓰고도
    869ms 가 남았다). 밀리초 시각은 깎을 것 자체를 없앤다.
    """
    true_offset = -0.31
    one_date = clockmod.sync(session=FakeSession(true_offset, rtt=0.08),
                             samples=1, log=lambda *_: None)
    one_ms = clockmod.sync(session=MsSession(true_offset, req_leg=0.06,
                                             resp_leg=0.02),
                           samples=1, log=lambda *_: None)
    assert one_date.samples == 1 and one_ms.samples == 1
    assert one_date.uncertainty >= 1.0, one_date.uncertainty
    assert one_ms.uncertainty < 0.2, one_ms.uncertainty
    # 한 발짜리라도 진짜 offset 은 구간 안에 있어야 한다.
    assert one_date.lo <= true_offset <= one_date.hi
    assert one_ms.lo <= true_offset <= one_ms.hi
    # 밀리초 한 발이 Date 열두 발보다 좁다는 게 요점이다.
    many_date = clockmod.sync(session=FakeSession(true_offset, rtt=0.94),
                              samples=6, log=lambda *_: None)
    assert one_ms.uncertainty < many_date.uncertainty, (
        one_ms.uncertainty, many_date.uncertainty)


def test_a_tight_clock_moves_the_aim_from_685ms_down_to_the_floor():
    """조준 공식은 그대로다. 앞쪽 항이 줄어드니 조준점이 따라 내려온다.

    2026-09-01 실전값: 오차 ±435ms -> 435 + 250 = 685ms.
    측정이 좁아지면 같은 공식이 하한까지 내려온다. 여유 상수는 그대로다.
    v1.0.12 에서 하한만 350 -> 250 으로 내렸다(config.py 주석 참고).
    """
    assert config.ARRIVAL_SAFETY_MS == 250.0        # 깎지 않았다
    assert config.ARRIVAL_MIN_AFTER_MS == 250.0

    loose = clockmod.ClockSync(synced=True, lo=-0.869, hi=0.0)   # 폭 869ms
    assert abs(loose.safe_arrival_after() * 1000 - 684.5) < 1.0

    tight = clockmod.sync(session=MsSession(0.2, req_leg=0.04, resp_leg=0.01),
                          samples=20, log=lambda *_: None)
    aim = tight.safe_arrival_after()
    assert aim * 1000 <= 450.0, aim * 1000
    assert aim * 1000 >= config.ARRIVAL_MIN_AFTER_MS


def test_the_aim_is_always_positive_and_above_the_residual_error():
    """정각 **전** 도착은 확정 실패다(2026-08-27 실측 1/1).

    그러니 조준점은 언제나 양수여야 하고, 우리가 모르는 만큼(한쪽 오차)보다
    커야 한다. 그래야 오차가 최악으로 나와도 정각을 넘긴다.
    """
    for width in (0.0, 0.02, 0.15, 0.4, 0.869, 1.6, 3.0):
        c = clockmod.ClockSync(synced=True, lo=-width, hi=0.0)
        aim = c.safe_arrival_after()
        assert aim > 0.0, width
        assert aim > c.uncertainty / 2.0 or aim == config.ARRIVAL_MAX_AFTER_MS / 1000.0, width
    # 측정 자체가 실패했으면 최대로 늦게 쏜다. 모를수록 늦게.
    never = clockmod.ClockSync()
    assert never.safe_arrival_after() * 1000 == config.ARRIVAL_MAX_AFTER_MS


def test_a_contradictory_sample_is_dropped_instead_of_wiping_the_others():
    """v1.0.9 는 교집합이 비면 그 샘플 하나로 **재시작**했다.

    튀는 한 발이 앞의 좋은 샘플을 전부 지울 수 있었다. 이제는 왕복이 나쁜
    쪽부터 버리고 살아남는 최대 집합을 쓴다.
    """
    good = [{"lo": 0.10, "hi": 0.20, "rtt": 0.05, "kind": "ms"} for _ in range(9)]
    liar = {"lo": 5.00, "hi": 5.10, "rtt": 0.90, "kind": "ms"}
    lo, hi, used, dropped = clockmod._intersect(good + [liar])
    assert (lo, hi) == (0.10, 0.20)
    assert used == 9 and dropped == 1


def test_the_drift_check_window_narrows_with_millisecond_resolution():
    c = clockmod.sync(session=MsSession(0.3, req_leg=0.02, resp_leg=0.005),
                      samples=12, log=lambda *_: None)
    t0 = time.time()
    t1 = t0 + 0.04
    stamp = t0 + 0.3 + 0.02
    wide = c.note_drift_sample(float(int(stamp)), t0, t1, "date")
    tight = c.note_drift_sample(stamp, t0, t1, "ms")
    ww = wide["windowMs"][1] - wide["windowMs"][0]
    tw = tight["windowMs"][1] - tight["windowMs"][0]
    assert ww - tw > 900, (ww, tw)
    assert tight["consistent"] is True
    # 어느 쪽이든 오프셋은 절대 움직이지 않는다.
    before = c.offset
    c.note_drift_sample(stamp, t0, t1, "ms")
    assert c.offset == before


def test_the_probe_endpoint_is_read_only_and_never_the_booking_path():
    """시각 프로브가 예약 등록 경로를 두들기면 안 된다. 절대로.

    childcare.go.kr 의 취소는 전화로만 된다. 잘못 들어간 예약 한 건이
    놓친 예약보다 훨씬 나쁘다.
    """
    assert "InsertOcreqst" not in config.CLOCK_PROBE_PATH
    assert config.CLOCK_PROBE_PATH.startswith("/")
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "aisarang", "clock.py"), encoding="utf-8").read()
    assert "InsertOcreqst" not in src
