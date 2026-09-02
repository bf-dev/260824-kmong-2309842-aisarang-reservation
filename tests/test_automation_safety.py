# -*- coding: utf-8 -*-
"""예약 시도의 안전 불변식 (준비 단계).

실패 모드는 반드시 "예약이 안 됨" 이어야 한다. "엉뚱한 날짜/시간에 예약됨" 은
고객 계정에 실제 예약을 만들고, 취소는 센터 전화로만 되기 때문에 훨씬 나쁘다.

v1.0.4 부터 흐름이 준비(1~8단계)와 발사([확인])로 나뉘었다. 여기서는 준비가
어디서 멈추는지를 본다. 발사 쪽 불변식은 test_booking.py 에 있다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import automation, booking


class FakeDriver:
    """무엇이 눌렸는지 기록하는 가짜 드라이버."""

    def __init__(self, page_source="<html></html>"):
        self.page_source = page_source
        self.current_url = "https://www.childcare.go.kr/?menuno=605"
        self.clicked = []

    def get(self, url):
        self.current_url = url

    def execute_script(self, script, *a):
        if "click" in script:
            self.clicked.append(script[:40])
        return None

    def find_elements(self, by, sel):
        return []

    def find_element(self, by, sel):
        raise Exception("none")

    def get_cookies(self):
        return []

    def get_log(self, kind):
        return []


def _grid(rows):
    g = booking.Grid(table_index=0)
    for date, texts in rows:
        g.rows.append({"date": date, "label": date, "row": len(g.rows) + 1})
        for i, t in enumerate(texts):
            g.cells.append(booking.Cell(date=date, hour=9 + i, text=t,
                                        capacity=booking._parse_cell_text(t),
                                        row=len(g.rows), col=i + 1))
    return g


def _patch(monkeypatch, grid=None, cert_required=False, cell_click=True,
           add_ok=True, tick_ok=True):
    monkeypatch.setattr(automation, "open_reservation_page", lambda *a, **k: None)
    monkeypatch.setattr(automation, "handle_netfunnel", lambda *a, **k: None)
    monkeypatch.setattr(automation, "capture", lambda *a, **k: None)
    monkeypatch.setattr(automation, "page_says_cert_required",
                        lambda d: cert_required)
    monkeypatch.setattr(automation, "login_grade", lambda d: "id")
    monkeypatch.setattr(booking, "choose_kind", lambda *a, **k: True)
    monkeypatch.setattr(booking, "choose_region", lambda *a, **k: True)
    monkeypatch.setattr(booking, "press_search", lambda *a, **k: True)
    monkeypatch.setattr(booking, "open_center", lambda *a, **k: True)
    monkeypatch.setattr(booking, "select_child",
                        lambda *a, **k: booking.ChildPick(ok=True, line="아동가"))
    monkeypatch.setattr(booking, "select_class", lambda *a, **k: "매송아이")
    monkeypatch.setattr(booking, "select_hours", lambda d, h, log=None: int(h))
    monkeypatch.setattr(booking, "read_grid",
                        lambda d, diag=None: grid or booking.Grid())
    monkeypatch.setattr(booking, "click_cell", lambda *a, **k: cell_click)
    monkeypatch.setattr(booking, "press_add", lambda *a, **k: add_ok)
    monkeypatch.setattr(booking, "tick_slot_row",
                        lambda d, date, log=None: (tick_ok, 3, "매송아이 2026-09-08"))
    monkeypatch.setattr(booking.time, "sleep", lambda *_: None)

    pressed = []
    monkeypatch.setattr(booking, "press_reserve",
                        lambda d, log=None: pressed.append("예약하기") or True)
    return pressed


CENTER = {"stcode": "11650000416", "name": "서초구육아종합지원센터(신반포)",
          "unityYn": "N", "ctprvnName": "서울특별시", "signguName": "서초구"}


def test_prepare_stops_when_target_date_row_is_not_open(monkeypatch):
    pressed = _patch(monkeypatch, grid=_grid([("20260907", ["2"] * 9)]))
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9], 9)
    assert not res.ok
    assert res.reason == "no_capacity"
    assert pressed == []


def test_prepare_reports_x_and_zero_instead_of_clicking(monkeypatch):
    pressed = _patch(monkeypatch, grid=_grid([("20260908", ["X", "0"] + ["0"] * 7)]))
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9, 10], 9)
    assert not res.ok
    assert res.reason == "no_capacity"
    assert "이용불가" in res.message and "0명" in res.message
    assert pressed == []


def test_prepare_stops_when_cell_did_not_actually_select(monkeypatch):
    """칸을 눌렀는데 표시가 안 바뀌면 선택된 게 아니다. 절대 진행하지 않는다."""
    pressed = _patch(monkeypatch, grid=_grid([("20260908", ["2"] * 9)]),
                     cell_click=False)
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9], 9)
    assert not res.ok
    assert res.reason == "cell_not_selected"
    assert pressed == []


def test_prepare_stops_when_row_is_not_ticked(monkeypatch):
    pressed = _patch(monkeypatch, grid=_grid([("20260908", ["2"] * 9)]),
                     tick_ok=False)
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9], 9)
    assert not res.ok
    assert res.reason == "row_not_ticked"
    assert res.prepared.row_ticked is False
    assert pressed == []


def test_prepare_stops_at_add_button(monkeypatch):
    pressed = _patch(monkeypatch, grid=_grid([("20260908", ["2"] * 9)]),
                     add_ok=False)
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9], 9)
    assert not res.ok
    assert res.reason == "no_add"
    assert pressed == []


def test_prepare_stops_when_the_requested_child_is_not_in_the_list(monkeypatch):
    """지정한 아동이 없으면 다른 아동으로 예약하지 않고 준비 자체를 멈춘다.

    v1.0.5 까지는 조용히 첫 번째 아동으로 진행했다. 아이가 둘 이상 등록된
    계정에서 그건 '엉뚱한 예약이 만들어짐' 이고, 취소는 센터 전화로만 된다.
    """
    pressed = _patch(monkeypatch, grid=_grid([("20260908", ["2"] * 9)]))
    monkeypatch.setattr(
        booking, "select_child",
        lambda *a, **k: booking.ChildPick(
            ok=False, reason="child_mismatch", requested="없는아이",
            candidates=["아동가 2025.10.22 10개월", "아동나 2024.03.05 29개월"],
            message="지정한 아동 '없는아이' 이(가) 목록에 없습니다."))
    clicked = []
    monkeypatch.setattr(booking, "click_cell", lambda *a, **k: clicked.append(1))
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9], 9, child_name="없는아이")
    assert not res.ok
    assert res.reason == "child_mismatch"
    assert clicked == [] and pressed == []
    # 업로드되는 detail 에 아동 이름이 실려나가지 않는다(개수만).
    assert res.detail["childCandidateCount"] == 2
    assert not any("아동가" in str(v) for v in res.detail.values())


def test_cert_gate_is_reported_not_bypassed(monkeypatch):
    pressed = _patch(monkeypatch, cert_required=True)
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9], 9)
    assert not res.ok
    assert res.reason == "cert_required"
    assert pressed == []


def test_full_prepare_reaches_the_modal(monkeypatch):
    pressed = _patch(monkeypatch, grid=_grid([("20260908", ["2"] * 9)]))
    monkeypatch.setattr(booking, "slot_row_is_ticked", lambda d, i=-1: True)
    monkeypatch.setattr(booking, "wait_modal",
                        lambda d, t=8.0, log=None, deadline_local=None:
                        ("예약하시겠습니까?", False))
    monkeypatch.setattr(booking, "arm_confirm", lambda d, log=None: True)
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9], 9)
    assert res.ok
    p = res.prepared
    assert p.start_hour == 9 and p.cell_capacity == 2 and p.row_ticked

    opened = booking.open_modal(d, p)
    assert opened.ok
    assert pressed == ["예약하기"]
    assert p.ready(), "확인 발사 조건이 모두 충족되어야 한다"


def test_dry_run_never_fires_confirm(monkeypatch):
    """연습 모드는 확인창까지만 연다. [확인] 은 누르지 않는다."""
    _patch(monkeypatch, grid=_grid([("20260908", ["2"] * 9)]))
    monkeypatch.setattr(booking, "slot_row_is_ticked", lambda d, i=-1: True)
    monkeypatch.setattr(booking, "wait_modal",
                        lambda d, t=8.0, log=None, deadline_local=None:
                        ("예약하시겠습니까?", False))
    monkeypatch.setattr(booking, "arm_confirm", lambda d, log=None: True)
    d = FakeDriver()
    res = booking.prepare(d, CENTER, "20260908", [9], 9)
    booking.open_modal(d, res.prepared)
    booking.dismiss_modal(d)
    assert not any("__aisarang_fire" in c for c in d.clicked)


# ---------------------------------------------------------------- 2026-09-02
# 고객이 09시 직전에 크롬드라이버 스택 덤프를 화면에서 복사해 우리에게 보내야
# 했다. 원인은 다른 크롬 창이 떠 있던 것이었고, 프로그램은 그것을 말해주지 않았다.

def test_chrome_busy_maps_to_a_korean_instruction():
    from aisarang import automation
    real = ("session not created: Chrome instance exited. "
            "Examine ChromeDriver verbose log to determine the cause.")
    err = automation.chrome_start_error(real, real, running=-1)
    assert isinstance(err, automation.ChromeStartError)
    text = str(err)
    assert "크롬 창을 모두 닫고" in text
    # 고객 화면에 스택 덤프가 새어 나가면 안 된다.
    assert "GetHandleVerifier" not in text
    assert "chromedriver!" not in text
    assert "Stacktrace" not in text


def test_a_running_chrome_alone_is_enough_to_give_the_close_chrome_message():
    from aisarang import automation
    err = automation.chrome_start_error("something else", "unknown", running=3)
    assert "크롬 창을 모두 닫고" in str(err)


def test_unknown_chrome_failure_still_gets_a_korean_message_not_a_stack():
    from aisarang import automation
    err = automation.chrome_start_error("boom", "boom", running=0)
    assert "크롬을 열지 못했습니다" in str(err)
    assert "Traceback" not in str(err)


def test_chrome_process_count_never_raises():
    from aisarang import automation
    assert isinstance(automation.chrome_process_count(), int)
