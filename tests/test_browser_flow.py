# -*- coding: utf-8 -*-
"""진짜 브라우저에서 4·5단계를 끝까지 돌린다.

가짜 드라이버로는 "선택자가 실제 DOM 을 잡는가" 를 증명할 수 없다. 그래서
고객 녹화를 보고 다시 만든 화면(ci/fixtures/reserve_page.html)을 헤드리스
크롬으로 실제로 열어서, booking.py 가 다음을 하는지 본다:

  반명/이용시간 고르기 → 표 읽기(X/0/2 구분) → 칸 클릭 →
  선택 표시가 진짜 바뀌었는지 확인 → 추가 → 체크 → 예약하기 →
  "예약" 모달 → [확인] 조준 → 발사 → 서버 문구 판정

크롬이 없으면 통째로 건너뛴다(우리 개발 환경 사정이지 제품 문제가 아니다).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import booking

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "ci", "fixtures", "reserve_page.html")


def _driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"selenium 없음: {exc}")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1200")
    try:
        return webdriver.Chrome(options=opts)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"크롬을 띄우지 못함: {type(exc).__name__}")


@pytest.fixture(scope="module")
def drv():
    d = _driver()
    yield d
    try:
        d.quit()
    except Exception:
        pass


def _open(d, answers="ok"):
    import pathlib
    d.get(pathlib.Path(FIXTURE).as_uri() + "?answers=" + answers)


def test_grid_is_read_with_capacity_and_x(drv):
    _open(drv)
    g = booking.read_grid(drv)
    assert g.has_date("20260908")
    assert g.summary("20260908") == "20260908: 09=2 10=2 11=2 12=2 13=2 14=2 15=2 16=2 17=2"
    # X 행과 0 행은 자리가 없는 것으로 읽혀야 한다.
    assert booking.pick_cell(g, "20260905", [9])[0] is None
    assert booking.pick_cell(g, "20260904", [9])[0] is None
    # 1 이 하나 있는 행은 그 칸만 잡힌다.
    cell, why = booking.pick_cell(g, "20260907", [])
    assert cell is not None and cell.hour == 12 and "1명" in why


def test_x_and_zero_cells_are_never_clicked(drv):
    _open(drv)
    booking.select_hours(drv, 9)
    g = booking.read_grid(drv)
    zero = g.find("20260904", 9)
    assert zero is not None and not zero.available
    # 눌러봐도 사이트가 무시하므로 '선택되지 않음' 으로 보고돼야 한다.
    assert booking.click_cell(drv, g, zero) is False


def test_full_flow_to_the_modal_and_a_successful_confirm(drv):
    _open(drv, "ok")
    assert booking.select_class(drv) == "매송아이"
    assert booking.select_hours(drv, 9) == 9

    g = booking.read_grid(drv)
    cell, _ = booking.pick_cell(g, "20260908", [9])
    assert cell is not None
    assert booking.click_cell(drv, g, cell) is True

    assert booking.press_add(drv) is True
    ok, row_idx, row_text = booking.tick_slot_row(drv, "20260908")
    assert ok
    assert "2026-09-08" in row_text and "9시간" in row_text
    assert booking.slot_row_is_ticked(drv, row_idx)

    p = booking.Prepared(target_date="20260908", start_hour=9, hours=9,
                         cell_selected=True, row_ticked=True, row_index=row_idx)
    res = booking.open_modal(drv, p)
    assert res.ok, res.message
    assert "예약하시겠습니까" in p.modal_text
    assert p.ready()

    assert drv.execute_script("return window.__fired;") == 0
    assert booking.fire_confirm(drv) is True
    code, text = booking.read_outcome(drv, timeout=3)
    assert code == booking.R_OK
    assert "완료" in text


def test_too_early_then_open_is_retried_until_it_takes(drv):
    """'예약시간전' 두 번 → 세 번째에 성공. 확인 경로만 다시 세운다."""
    _open(drv, "too_early,too_early,ok")
    booking.select_class(drv)
    booking.select_hours(drv, 9)
    g = booking.read_grid(drv)
    cell, _ = booking.pick_cell(g, "20260908", [9])
    booking.click_cell(drv, g, cell)
    booking.press_add(drv)
    ok, row_idx, _ = booking.tick_slot_row(drv, "20260908")
    p = booking.Prepared(target_date="20260908", start_hour=9, hours=9,
                         cell_selected=True, row_ticked=ok, row_index=row_idx)
    assert booking.open_modal(drv, p).ok

    class Clock:
        offset = 0.0
        one_way = 0.0
        correction = 0.0
        correction_notes = []

        def server_now(self):
            return -0.2

        def arrival_for_local_fire(self, t):
            return -0.2

        def note_too_early(self, est, margin=0.03):
            return 0.0

    res = booking.confirm_burst(drv, p, Clock(), 0.0, retry_seconds=5, retry_ms=1)
    assert res.ok, res.message
    assert drv.execute_script("return window.__fired;") == 3
    assert [s["code"] for s in res.detail["shots"]] == ["too_early", "too_early", "ok"]


def test_full_stops_after_one_shot(drv):
    _open(drv, "full,ok")
    booking.select_class(drv)
    booking.select_hours(drv, 9)
    g = booking.read_grid(drv)
    cell, _ = booking.pick_cell(g, "20260908", [9])
    booking.click_cell(drv, g, cell)
    booking.press_add(drv)
    ok, row_idx, _ = booking.tick_slot_row(drv, "20260908")
    p = booking.Prepared(target_date="20260908", start_hour=9, hours=9,
                         cell_selected=True, row_ticked=ok, row_index=row_idx)
    booking.open_modal(drv, p)

    class Clock:
        offset = 0.0
        one_way = 0.0
        correction = 0.0
        correction_notes = []

        def server_now(self):
            return -0.2

        def arrival_for_local_fire(self, t):
            return 0.05

        def note_too_early(self, est, margin=0.03):
            return 0.0

    res = booking.confirm_burst(drv, p, Clock(), 0.0, retry_seconds=5, retry_ms=1)
    assert not res.ok
    assert res.reason == "full"
    assert drv.execute_script("return window.__fired;") == 1, "정원초과는 두들기지 않는다"


def test_confirm_is_not_fired_when_the_row_check_is_gone(drv):
    """홀드 중에 체크가 풀리면 [예약하기] 도 [확인] 도 누르지 않는다."""
    _open(drv, "ok")
    booking.select_class(drv)
    booking.select_hours(drv, 9)
    g = booking.read_grid(drv)
    cell, _ = booking.pick_cell(g, "20260908", [9])
    booking.click_cell(drv, g, cell)
    booking.press_add(drv)
    ok, row_idx, _ = booking.tick_slot_row(drv, "20260908")
    p = booking.Prepared(target_date="20260908", start_hour=9, hours=9,
                         cell_selected=True, row_ticked=ok, row_index=row_idx)
    # 체크를 다시 꺼버린다(고객이 실수로 눌렀거나 화면이 다시 그려진 상황).
    drv.execute_script(
        "document.querySelector('#picked input[type=checkbox]').checked = false;")
    res = booking.open_modal(drv, p)
    assert not res.ok and res.reason == "guard_row"
    assert drv.execute_script(
        "return document.getElementById('layer').classList.contains('open');") is False


# --------------------------------------------------------------- 3단계 아동
# 아래 fixture 는 고객 PC 진단 ZIP 에서 읽은 **실제 마크업**을 재현한 것이다
# (2026-08-25T05:24Z, 인증서 세션. 개인정보는 가짜 값으로 바꿨다).
CHILD_FIXTURE = os.path.join(ROOT, "ci", "fixtures", "child_select.html")


def _open_child(d):
    import pathlib
    d.get(pathlib.Path(CHILD_FIXTURE).as_uri())


def test_child_radio_is_clicked_even_when_already_checked(drv):
    """실제 사이트에서 이용정보 화면을 여는 유일한 트리거가 이 클릭이다.

    라디오에 checked 가 이미 걸려 있어도 누르지 않으면 반명/이용시간/날짜표가
    영영 안 나온다. 그 화면이 ajax 로 늦게 그려지는 것까지 같이 본다.
    """
    _open_child(drv)
    assert drv.execute_script(
        "return document.querySelector('input[name=occasionChk]').checked;") is True
    assert drv.execute_script("return window.loads;") == 0

    line = booking.select_child(drv, "")
    assert "아동가" in line
    assert drv.execute_script("return window.loads;") >= 1, "이용정보 화면을 열지 않았다"
    # select_child 가 돌아온 시점에는 이미 그려져 있어야 한다(기다렸어야 한다).
    assert booking.select_class(drv) == "매송아이"
    assert booking.select_hours(drv, 9) == 9


def test_child_selection_reports_the_site_alert_and_never_hangs(drv):
    """이용신청서가 없으면 사이트가 alert 을 띄운다. 닫지 않으면 그 뒤가 전부 막힌다."""
    _open_child(drv)
    drv.execute_script(
        "document.querySelector('input[name=occasionChk]')"
        ".setAttribute('data-usereqstcnt','0');")
    lines = []
    line = booking.select_child(drv, "", log=lines.append)
    assert "아동가" in line
    assert any("이용신청서" in s for s in lines), lines
    # alert 이 닫혔으므로 이후 조작이 정상적으로 된다.
    assert drv.execute_script("return 1 + 1;") == 2
