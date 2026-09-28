# -*- coding: utf-8 -*-
"""2026-09-28 09:00:00: we gave up on the queue after 2.4s. v1.0.20 waits it out.

The customer log that day (v1.0.19):

    [09:00:00] [확인] 1발째 ... 가상대기열: 앞에 32명
    [09:00:02] 판정을 읽지 못했지만 가상대기열에 서 있습니다. ... 멈춥니다.

The diagnostic ZIP shows the real InsertOcreqst went out at +2,665ms, after
the queue released. Nobody read its answer, so the run ended as
unknown_submitted.

v1.0.20 rules pinned here:
  - read_outcome_detail(queue_timeout=...) keeps waiting while the NetFunnel
    queue is up (sticky), then reads the real verdict once it releases.
  - Nothing is clicked while queued (burst neither fires nor re-presses).
  - A queue that never clears still ends as honest unknown at the cap.
  - The pre-hour first shot (-500ms) followed by a genuine too_early leads to
    a recovery shot aimed at open +140ms, even if the verdict came late
    through a queue.
"""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import booking, config, handover  # noqa: E402

QUEUE_0928 = {"queue": True, "ahead": 32, "behind": 4, "eta": "04초",
              "progress": "0 % (0/32)"}


def _body(msg: str, val: str = "") -> str:
    return json.dumps({"returnmsg": msg, "returnval": val}, ensure_ascii=False)


class _TimedDriver:
    """A browser whose queue and submit follow a wall-clock script.

    queue_windows : list of (start, end) seconds after construction during
                    which the NetFunnel layer is up.
    submit_at     : seconds after construction when InsertOcreqst starts
                    (None = never).
    done_after    : seconds after submit start when the response lands.
    body          : response body text.
    """

    def __init__(self, queue_windows, submit_at=None, done_after=0.3,
                 body="", status=200, fired=True):
        self.t0 = time.time()
        self.queue_windows = list(queue_windows)
        self.submit_at = submit_at
        self.done_after = done_after
        self.body = body
        self.status = status
        self.fired = fired
        self.page_source = "<html><body></body></html>"
        self.queue_polls_while_up = 0
        self.clicks = 0

    def _t(self):
        return time.time() - self.t0

    def _queued(self):
        t = self._t()
        return any(a <= t < b for a, b in self.queue_windows)

    def execute_script(self, script, *args):
        if "__aisarangSubmit" in script:
            if self.submit_at is None or self._t() < self.submit_at:
                return None
            done = self._t() >= self.submit_at + self.done_after
            return {"seq": 1, "url": "/InsertOcreqst.do", "method": "POST",
                    "t0": 1, "t1": 2 if done else 0, "done": done,
                    "status": self.status if done else 0,
                    "responseBody": self.body if done else "",
                    "responseHeaders": "date: Mon, 28 Sep 2026 00:00:02 GMT",
                    "firedAt": 1, "stale": False}
        if "__aisarang_fired_at" in script:
            return 1_790_000_000_000 if self.fired else 0
        if "NetFunnel_Loading_Popup" in script:
            if self._queued():
                self.queue_polls_while_up += 1
                return dict(QUEUE_0928)
            return {"queue": False}
        if "click" in script.lower():
            self.clicks += 1
        return []

    @property
    def switch_to(self):
        raise RuntimeError("no alert")


# ------------------------------------------------ read_outcome_detail


def test_a_queue_longer_than_the_old_giveup_is_waited_out_and_the_ok_is_read():
    """The 09-28 shape: queue for 2.7s, then the POST goes out and succeeds."""
    drv = _TimedDriver([(0.0, 2.7)], submit_at=2.75, done_after=0.2,
                       body=_body(booking.OK_REAL, "success"))
    lines = []
    out = booking.read_outcome_detail(drv, timeout=1.6, submit_timeout=9.0,
                                      queue_timeout=6.0, log=lines.append)
    assert out.code == booking.R_OK, out
    assert out.source == "submit"
    assert out.queued is True and out.queue_cleared is True
    assert out.queue_wait_ms >= 2400.0, out.queue_wait_ms
    assert out.queue.get("ahead") == 32
    assert drv.queue_polls_while_up > 10
    joined = "\n".join(lines)
    assert "가상대기열에 섰습니다" in joined
    assert "대기열이 풀렸습니다" in joined
    d = out.as_dict()
    assert d["queueCleared"] is True and d["queueWaitMs"] >= 2400.0


def test_the_verdict_after_the_queue_can_be_a_genuine_too_early():
    drv = _TimedDriver([(0.0, 2.6)], submit_at=2.7, done_after=0.1,
                       body=_body(booking.TOO_EARLY_REAL))
    out = booking.read_outcome_detail(drv, timeout=1.6, submit_timeout=9.0,
                                      queue_timeout=6.0)
    assert out.code == booking.R_TOO_EARLY
    assert handover.is_genuine_too_early(out) is True
    assert out.queued is True and out.queue_cleared is True


@pytest.mark.parametrize("msg,code", [
    (booking.TAKEN_REAL, booking.R_TAKEN),
    ("정원초과입니다.", booking.R_FULL),
])
def test_the_verdict_after_the_queue_can_be_taken_or_full(msg, code):
    drv = _TimedDriver([(0.0, 2.5)], submit_at=2.55, done_after=0.1,
                       body=_body(msg))
    out = booking.read_outcome_detail(drv, timeout=1.6, submit_timeout=9.0,
                                      queue_timeout=6.0)
    assert out.code == code, out
    assert out.queued is True


def test_a_flickering_queue_keeps_the_wait_alive():
    """Queue up, gap of 0.3s, queue up again, then release and answer.

    The gap is shorter than SUBMIT_START_GRACE, so the reader must not treat
    the first release as 'nothing is coming' and quit.
    """
    drv = _TimedDriver([(0.0, 1.4), (1.7, 3.0)], submit_at=3.1,
                       done_after=0.1, body=_body(booking.OK_REAL, "success"))
    lines = []
    out = booking.read_outcome_detail(drv, timeout=1.6, submit_timeout=9.0,
                                      queue_timeout=8.0, log=lines.append)
    assert out.code == booking.R_OK, out
    assert out.queue_cleared is True
    assert any("다시 떴습니다" in x for x in lines), lines


def test_a_queue_that_never_clears_ends_as_unknown_at_the_cap():
    drv = _TimedDriver([(0.0, 999.0)], submit_at=None)
    t = time.time()
    out = booking.read_outcome_detail(drv, timeout=0.3, submit_timeout=0.5,
                                      queue_timeout=1.5)
    took = time.time() - t
    assert out.code == booking.R_UNKNOWN
    assert out.queued is True and out.queue_cleared is False
    assert 1.4 <= took < 3.0, took
    assert out.queue_wait_ms >= 1400.0


def test_without_queue_timeout_the_old_giveup_is_unchanged():
    """queue_timeout=None is exactly v1.0.19: gives up at the old hard end."""
    drv = _TimedDriver([(0.0, 2.7)], submit_at=2.75, done_after=0.2,
                       body=_body(booking.OK_REAL, "success"))
    t = time.time()
    out = booking.read_outcome_detail(drv, timeout=0.3, submit_timeout=1.0)
    assert time.time() - t < 2.0
    assert out.code == booking.R_UNKNOWN
    assert out.queued is True


def test_stop_ends_a_long_queue_wait_quickly():
    drv = _TimedDriver([(0.0, 999.0)], submit_at=None)
    stop = threading.Event()
    threading.Timer(0.4, stop.set).start()
    t = time.time()
    out = booking.read_outcome_detail(drv, timeout=0.3, submit_timeout=0.5,
                                      queue_timeout=60.0, stop_event=stop)
    assert time.time() - t < 2.0
    assert out.code == booking.R_UNKNOWN and out.queued is True


def test_the_queue_cap_is_generous():
    assert config.QUEUE_WAIT_SECONDS >= 60.0


# ------------------------------------------------ handover.burst


class _Clock:
    """Server clock that advances with real time from a chosen origin."""

    def __init__(self, origin: float):
        self.origin = origin
        self.t0 = time.time()
        self.targets = []
        self.correction = 0.0

    def server_now(self):
        return self.origin + (time.time() - self.t0)

    def arrival_for_local_fire(self, local_epoch):
        return self.origin + (local_epoch - self.t0)

    def local_fire_for_arrival(self, arrival_epoch):
        self.targets.append(arrival_epoch)
        return self.t0 + (arrival_epoch - self.origin)

    def note_too_early(self, *_a, **_kw):
        return 0.0


def _state(**kw):
    base = dict(modal=True, modal_text="예약하시겠습니까?", confirm=True,
                armed=True, rows=1, ticked=1, on_reserve_page=True)
    base.update(kw)
    return handover.LiveState(**base)


def _closed(**kw):
    base = dict(modal=False, confirm=False, armed=False, rows=1, ticked=1,
                on_reserve_page=True)
    base.update(kw)
    return handover.LiveState(**base)


class _Watcher:
    def __init__(self, states):
        self._states = list(states)
        self.state = self._states[0]

    def poll(self):
        self.state = self._states[0]
        if len(self._states) > 1:
            self._states.pop(0)
        return self.state


class _ReopeningWatcher:
    """Dialog up until the first shot, then closed until [예약하기] is
    re-pressed, then up again. `calls` is the shared counter dict."""

    def __init__(self, calls, queue_polls_after_repress=0):
        self.calls = calls
        self.q_left = queue_polls_after_repress
        self.state = _state()

    def poll(self):
        if self.calls["fire"] == 0:
            self.state = _state()
        elif self.calls["repress"] < self.calls["fire"]:
            self.state = _closed()
        elif self.q_left > 0:
            self.q_left -= 1
            self.state = _closed(queue=True)
        else:
            self.state = _state()
        return self.state


def _wire(monkeypatch, outcomes, log_fire_state=None, clock=None, calls=None):
    """outcomes: Outcome, or (Outcome, seconds the read took on the server
    clock). The second form simulates a verdict that came late via a queue."""
    calls = calls if calls is not None else {}
    calls.update({"fire": 0, "repress": 0, "close": 0, "waits": [],
                  "queue_timeout": []})

    def fake_fire(_d):
        calls["fire"] += 1
        if log_fire_state is not None:
            assert not log_fire_state().queue, "fired on top of the queue"
        return True

    def fake_outcome(_d, timeout=0.0, submit_timeout=None, queue_timeout=None,
                     log=None, stop_event=None):
        calls["queue_timeout"].append(queue_timeout)
        item = outcomes[min(calls["fire"], len(outcomes)) - 1]
        if isinstance(item, tuple):
            item, took = item
            clock.origin += took
        return item

    def fake_repress(_d, log=lambda *_: None):
        calls["repress"] += 1
        return True

    def fake_close(_d, log=lambda *_: None):
        calls["close"] += 1
        return booking.TOO_EARLY_REAL

    def fake_wait(local_epoch, stop_event=None, spin_ms=40):
        calls["waits"].append(local_epoch)

    monkeypatch.setattr(handover, "fire", fake_fire)
    monkeypatch.setattr(booking, "read_outcome_detail", fake_outcome)
    monkeypatch.setattr(booking, "repress_reserve_button", fake_repress)
    monkeypatch.setattr(booking, "close_result_alert", fake_close)
    monkeypatch.setattr(handover.clockmod, "sleep_until_local", fake_wait)
    return calls


OPEN = 1_790_000_000.0


def _too_early(queued=False):
    return booking.Outcome(code=booking.R_TOO_EARLY,
                           text=booking.TOO_EARLY_REAL, source="submit",
                           status=200, submit_seen=True, submit_done=True,
                           queued=queued, queue=dict(QUEUE_0928) if queued else {})


def _ok():
    return booking.Outcome(code=booking.R_OK, text=booking.OK_REAL,
                           source="submit", status=200, submit_seen=True,
                           submit_done=True, returnval="success")


def test_prehour_shot_then_recovery_is_aimed_at_plus_140ms(monkeypatch):
    """The v1.0.20 plan end to end: first shot lands before the hour, the
    server says too_early, the program re-presses and waits for open +140ms,
    then fires the recovery shot which succeeds."""
    clock = _Clock(OPEN - 0.5)       # first shot arrives at about -500ms
    calls = _wire(monkeypatch, [_too_early(), _ok()], clock=clock)
    lines = []
    res = handover.burst(object(), clock, OPEN, _ReopeningWatcher(calls),
                         log=lines.append, retry_seconds=3, retry_ms=20,
                         reopen_max=6, reopen_seconds=2.0)
    assert res.ok is True and res.reason == "reserved", res
    assert calls["fire"] == 2 and calls["repress"] == 1, calls
    first = res.detail["shots"][0]
    assert -560.0 <= first["arrivalOffsetMs"] <= -440.0, first
    assert clock.targets == [pytest.approx(OPEN + 0.140)], clock.targets
    assert len(calls["waits"]) == 1
    assert any("+140ms" in x for x in lines), lines
    # Every read is allowed to wait out a queue with the generous cap.
    assert calls["queue_timeout"] == [config.QUEUE_WAIT_SECONDS] * 2


def test_burst_never_clicks_while_the_queue_is_up(monkeypatch):
    """Queue shows before the first shot: no fire, no re-press, it waits and
    fires the moment the confirm dialog is back."""
    watcher = _Watcher([_closed(queue=True)] * 8 + [_state()])
    calls = _wire(monkeypatch, [_ok()], log_fire_state=lambda: watcher.state)
    res = handover.burst(object(), _Clock(OPEN), OPEN, watcher,
                         log=lambda *_: None, retry_seconds=1, retry_ms=20)
    assert res.ok is True
    assert calls["fire"] == 1 and calls["repress"] == 0, calls


def test_a_queued_too_early_still_gets_its_recovery_shot(monkeypatch):
    """The verdict came 20s late through the queue. The reopen window is
    re-measured from the verdict, so the genuine too_early is still recovered
    (v1.0.19 locked forever the moment a queue showed)."""
    clock = _Clock(OPEN - 0.5)
    # The first read sits in the queue for 20.5s: the verdict lands at +20s,
    # far past the plain open+2s reopen window.
    calls = _wire(monkeypatch, [(_too_early(queued=True), 20.5), _ok()],
                  clock=clock)
    res = handover.burst(object(), clock, OPEN, _ReopeningWatcher(calls),
                         log=lambda *_: None, retry_seconds=3, retry_ms=20,
                         reopen_max=6, reopen_seconds=2.0)
    assert res.ok is True, res.detail
    assert calls["repress"] == 1 and calls["fire"] == 2, calls
    # The first verdict did not lock the gate: one reopen was used and its
    # window was re-measured from the queued verdict (+20s).
    assert res.detail["reopen"]["used"] == 1
    assert res.detail["reopen"]["verdictAt"] >= OPEN + 19.9


def test_a_queue_after_the_repress_is_waited_out_without_a_second_click(monkeypatch):
    """Re-pressed, then the queue appears and releases into the confirm
    dialog. One re-press, one recovery fire, no extra clicks."""
    calls = {}
    watcher = _ReopeningWatcher(calls, queue_polls_after_repress=6)
    clock = _Clock(OPEN + 0.2)
    _wire(monkeypatch, [_too_early(), _ok()], clock=clock, calls=calls,
          log_fire_state=lambda: watcher.state)
    res = handover.burst(object(), clock, OPEN, watcher,
                         log=lambda *_: None, retry_seconds=3, retry_ms=20,
                         reopen_max=6, reopen_seconds=2.0)
    assert res.ok is True
    assert calls["repress"] == 1 and calls["fire"] == 2, calls


def test_an_unknown_after_a_capped_queue_still_stops(monkeypatch):
    """At the cap, a queued unknown is still 'do not fire again'."""
    unk = booking.Outcome(code=booking.R_UNKNOWN, queued=True,
                          queue=dict(QUEUE_0928))
    calls = _wire(monkeypatch, [unk])
    res = handover.burst(object(), _Clock(OPEN), OPEN,
                         _Watcher([_state(), _state()]),
                         log=lambda *_: None, retry_seconds=3, retry_ms=20)
    assert res.reason == "unknown_submitted"
    assert calls["fire"] == 1 and calls["repress"] == 0


def test_reopen_window_is_measured_from_a_queued_verdict():
    clock = _Clock(OPEN + 30.0)
    g = handover._Reopen(clock, OPEN, 6, 2.0)
    g.note_outcome(booking.R_TOO_EARLY, _too_early(queued=True))
    assert g.allowed(_closed()) is True
    # Without the queue the window is open .. open+2s and +30s is too late.
    g2 = handover._Reopen(clock, OPEN, 6, 2.0)
    g2.note_outcome(booking.R_TOO_EARLY, _too_early(queued=False))
    assert g2.allowed(_closed()) is False
    # Still never while the queue layer is up.
    assert g.allowed(_closed(queue=True)) is False


# ------------------------------------------------ auto mode redrive


class _RedriveDriver:
    """After [예약하기] the queue is up for `queue_s`, then the modal opens."""

    def __init__(self, queue_s):
        self.queue_s = queue_s
        self.pressed_at = None
        self.presses = 0

    def _t(self):
        return 0.0 if self.pressed_at is None else time.time() - self.pressed_at

    def execute_script(self, script, *args):
        return []

    @property
    def switch_to(self):
        raise RuntimeError("no alert")


def test_auto_mode_redrive_waits_out_a_queue_longer_than_3s(monkeypatch):
    drv = _RedriveDriver(queue_s=3.6)

    def press(_d, log=lambda *_: None):
        drv.presses += 1
        drv.pressed_at = time.time()
        return True

    monkeypatch.setattr(booking, "still_armed", lambda _d: False)
    monkeypatch.setattr(booking, "slot_row_is_ticked", lambda *_a: True)
    monkeypatch.setattr(booking, "press_reserve", press)
    monkeypatch.setattr(booking, "queue_info",
                        lambda _d: dict(QUEUE_0928) if drv._t() < drv.queue_s
                        else {"queue": False})
    monkeypatch.setattr(booking, "modal_info",
                        lambda _d: {"text": "예약하시겠습니까?"}
                        if drv._t() >= drv.queue_s else {})
    monkeypatch.setattr(booking, "arm_confirm", lambda *_a, **_k: True)
    p = booking.Prepared()
    t = time.time()
    assert booking.redrive_confirm(drv, p, lambda *_: None) is True
    assert time.time() - t >= 3.5
    assert drv.presses == 1
    assert p.armed is True
