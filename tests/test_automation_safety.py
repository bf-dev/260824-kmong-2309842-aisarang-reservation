# -*- coding: utf-8 -*-
"""예약 시도의 안전 불변식.

실패 모드는 반드시 "예약이 안 됨" 이어야 한다. "엉뚱한 날짜/시간에 예약됨" 은
고객 계정에 실제 예약을 만들고, 취소는 센터 전화로만 되기 때문에 훨씬 나쁘다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import automation


class FakeDriver:
    """attempt_once 가 실제로 무엇을 눌렀는지 기록하는 가짜 드라이버."""

    def __init__(self, page_source="<html></html>"):
        self.page_source = page_source
        self.current_url = "https://www.childcare.go.kr/?menuno=605"
        self.clicked = []

    def get(self, url):
        self.current_url = url

    def execute_script(self, script, *a):
        if "click" in script:
            self.clicked.append(a[0] if a else "?")
        return {}

    def find_elements(self, by, sel):
        return []

    def find_element(self, by, sel):
        raise Exception("none")

    def get_cookies(self):
        return []

    def get_log(self, kind):
        return []


def _patch(monkeypatch, **kw):
    monkeypatch.setattr(automation, "open_reservation_page", lambda *a, **k: None)
    monkeypatch.setattr(automation, "handle_netfunnel", lambda *a, **k: None)
    monkeypatch.setattr(automation, "page_says_cert_required",
                        lambda d: kw.get("cert_required", False))
    monkeypatch.setattr(automation, "select_date", lambda *a, **k: kw.get("date_ok", True))
    monkeypatch.setattr(automation, "select_time_slots", lambda *a, **k: kw.get("slots_picked", 0))
    monkeypatch.setattr(automation, "select_first_available_slot",
                        lambda *a, **k: kw.get("first_slot", 0))
    submitted = []
    monkeypatch.setattr(automation, "find_submit",
                        lambda d: (("EL", "신청하기") if kw.get("submit_exists", True)
                                   else (None, "")))
    monkeypatch.setattr(automation, "accept_confirm", lambda *a, **k: None)
    monkeypatch.setattr(automation, "read_result", lambda d: ("ok", "신청이 완료"))
    return submitted


def test_never_submits_when_date_not_found(monkeypatch):
    _patch(monkeypatch, date_ok=False)
    d = FakeDriver()
    r = automation.attempt_once(d, {"stcode": "1", "name": "x"}, "20260908",
                                ["09:00"], dry_run=False)
    assert not r.ok
    assert r.detail["reason"] == "date_not_open"
    assert d.clicked == []          # 아무것도 누르지 않았다


def test_never_submits_when_requested_slot_missing(monkeypatch):
    _patch(monkeypatch, date_ok=True, slots_picked=0)
    d = FakeDriver()
    r = automation.attempt_once(d, {"stcode": "1"}, "20260908", ["09:00"], dry_run=False)
    assert not r.ok
    assert r.detail["reason"] == "slot_unavailable"
    assert d.clicked == []


def test_never_submits_with_empty_selection_when_no_slot_requested(monkeypatch):
    """시간대를 지정하지 않았는데 열린 시간대도 없으면 제출하지 않는다."""
    _patch(monkeypatch, date_ok=True, first_slot=0)
    d = FakeDriver()
    r = automation.attempt_once(d, {"stcode": "1"}, "20260908", [], dry_run=False)
    assert not r.ok
    assert r.detail["reason"] == "slot_unavailable"
    assert d.clicked == []


def test_no_slot_requested_picks_first_open_one(monkeypatch):
    _patch(monkeypatch, date_ok=True, first_slot=1)
    d = FakeDriver()
    r = automation.attempt_once(d, {"stcode": "1"}, "20260908", [], dry_run=False)
    assert r.ok
    assert d.clicked, "제출 클릭이 일어나야 한다"


def test_dry_run_stops_before_submit(monkeypatch):
    _patch(monkeypatch, date_ok=True, slots_picked=1)
    d = FakeDriver()
    r = automation.attempt_once(d, {"stcode": "1"}, "20260908", ["09:00"], dry_run=True)
    assert r.ok
    assert r.detail["reason"] == "dry_run"
    assert d.clicked == [], "연습 모드는 절대 제출을 누르지 않는다"


def test_cert_gate_is_reported_not_bypassed(monkeypatch):
    _patch(monkeypatch, cert_required=True)
    d = FakeDriver()
    r = automation.attempt_once(d, {"stcode": "1"}, "20260908", ["09:00"], dry_run=False)
    assert not r.ok
    assert r.detail["reason"] == "cert_required"
    assert d.clicked == []


def test_burst_stops_immediately_on_cert_gate(monkeypatch):
    """인증서 게이트는 재시도해봐야 소용없다. 즉시 빠져나와야 한다."""
    _patch(monkeypatch, cert_required=True)

    class C:
        def server_now(self):
            return 0.0

    calls = []
    real = automation.attempt_once

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(automation, "attempt_once", counting)
    r = automation.burst(FakeDriver(), {"stcode": "1"}, "20260908", ["09:00"], False,
                         C(), -10.0, 20, 10)
    assert not r.ok
    assert len(calls) == 1
