# -*- coding: utf-8 -*-
"""실행 중에 서버 시각을 다시 재는 것이 실제 흐름에 연결돼 있는지 (v1.0.6).

clock.py 단위 검증은 test_clock.py 에 있다. 여기서는 runner 가
  · 다시 잰 값을 실제로 조준에 반영하는가 (홀드 중에도)
  · 세션 유지 응답의 Date 헤더로 어긋남을 잡아 재측정을 앞당기는가
  · 고객에게 약속한 주기(5분)를 쓰는가
를 본다.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import booking, clock as clockmod, config, runner as runnermod


class FakeKeeper:
    def __init__(self):
        self.calls = []

    def request_now(self, reason=""):
        self.calls.append(reason)

    def sync_now(self, reason="", force=False):
        self.calls.append("sync:" + reason)
        return True

    def stop(self):
        pass


def _runner():
    lines = []
    r = runnermod.Runner(log_cb=lines.append)
    r.clock = clockmod.ClockSync(offset=0.0, lo=-0.05, hi=0.05, synced=True,
                                 rtt_best=0.0, samples=12)
    return r, lines


def test_the_shipped_touch_interval_matches_the_resync_interval():
    """고객 로그에 두 줄이 5분 간격으로 나란히 찍히도록 맞춰둔 값이다."""
    assert runnermod.Runner.SESSION_TOUCH_SECONDS == config.SESSION_TOUCH_SECONDS
    assert config.SESSION_TOUCH_SECONDS == config.RESYNC_SECONDS == 300


def test_hold_follows_a_clock_that_was_remeasured_mid_hold(monkeypatch):
    """홀드 중에 시각을 다시 쟀으면 발사 시각도 그만큼 따라 움직여야 한다."""
    r, _ = _runner()
    r.HOLD_CHECK_SECONDS = 0.2
    monkeypatch.setattr(booking, "modal_still_held", lambda d, p: True)

    arrival = time.time() + 5.0          # 서버 기준 5초 뒤 도착 목표
    # 홀드가 시작되고 나서 재측정 결과가 들어온다: 서버가 우리 생각보다 2.5초 앞선다.
    def _remeasure():
        time.sleep(0.4)
        r.clock.offset = 2.5
    import threading
    threading.Thread(target=_remeasure, daemon=True).start()

    t0 = time.time()
    r._hold_modal(booking.Prepared(), arrival, {}, "20260908", [9], 9, {},
                  arrival + 0.3)
    elapsed = time.time() - t0
    # 새 값 기준 발사 시각은 +2.5초. 옛 값 그대로였다면 +5초까지 붙잡고 있었다.
    assert 1.5 < elapsed < 3.5, elapsed


def test_drift_check_asks_for_an_immediate_remeasure_when_it_disagrees():
    r, lines = _runner()
    keeper = FakeKeeper()
    r.keeper = keeper
    t0 = time.time()
    # 서버가 우리 생각보다 5초 앞서 있다고 알려주는 한 발.
    r._drift_check({"ok": True, "dateEpoch": float(int(t0 + 5.0)),
                    "t0": t0, "t1": t0 + 0.02})
    assert keeper.calls, lines
    assert any("어긋남" in s for s in lines), lines
    # 그래도 한 발로 오프셋을 움직이지는 않는다.
    assert r.clock.offset == 0.0


def test_drift_check_is_quiet_when_the_clock_agrees():
    r, lines = _runner()
    keeper = FakeKeeper()
    r.keeper = keeper
    t0 = time.time()
    r._drift_check({"ok": True, "dateEpoch": float(int(t0)),
                    "t0": t0, "t1": t0 + 0.02})
    assert keeper.calls == []
    assert any("어긋남 없음" in s for s in lines), lines


def test_drift_check_ignores_a_touch_that_returned_nothing():
    r, lines = _runner()
    r.keeper = FakeKeeper()
    r._drift_check({"ok": False, "dateEpoch": None})
    r._drift_check({})
    assert r.keeper.calls == []
