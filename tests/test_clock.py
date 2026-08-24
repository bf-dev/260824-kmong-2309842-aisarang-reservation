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
