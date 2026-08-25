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
