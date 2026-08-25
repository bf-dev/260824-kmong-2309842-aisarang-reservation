# -*- coding: utf-8 -*-
"""고객 PC 가 올려준 **진짜 예약 화면 마크업**에 대고 선택자를 돌린다.

재현 fixture 는 우리가 만든 것이라 우리 코드에 유리하게 생겼다. 이 파일은
다르다: 서버가 실제로 내려준 응답 그대로이고(개인정보만 가명), 그래서
v1.0.5 의 실제 버그 두 개가 여기서 그대로 재현된다.

  1. _JS_SCAN_SLOT_ROWS 가 **아동 표**를 선택표로 골랐다.
     아동 행에 생년월일(2025.10.22)이 있어서 `dated * 10` 으로 이겼다.
     그 뒤 tick_slot_row 가 아동 라디오를 켜고 "선택표 행을 체크했습니다" 라고
     남겼고, slot_row_is_ticked 가 참을 돌려주어 open_modal 의 안전장치까지
     통과했다. 즉 엉뚱한 것을 예약할 수 있는 경로였다.
  2. _JS_READ_NOTICE 가 이 화면의 알림 컨테이너를 하나도 못 봤다.
     실제 클래스는 `popup_wrap` 인데 선택자는 `.popup` 이었다.

크롬이 없으면 통째로 건너뛴다.
"""
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import booking

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.join(ROOT, "ci", "fixtures", "real_reservation_page.html")


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
    d.get(pathlib.Path(REAL).as_uri())
    yield d
    try:
        d.quit()
    except Exception:
        pass


def test_the_child_table_is_never_taken_for_the_slot_table(drv):
    """이 화면에는 선택표가 아직 없다. 그러면 '없다' 고 해야 한다."""
    data = booking.read_slot_rows(drv)
    rows = data.get("rows") or []
    assert not any("개월" in str(r.get("text", "")) for r in rows), rows
    assert any(s.get("why") == "child_table" for s in (data.get("skipped") or [])), data


def test_tick_never_ticks_the_child_radio_on_this_page(drv):
    """v1.0.5 는 여기서 아동 라디오를 켜고 성공했다고 로그를 남겼다."""
    lines = []
    ok, row_idx, row_text = booking.tick_slot_row(drv, "20260908", lines.append)
    assert ok is False, (row_idx, row_text, lines)
    assert "개월" not in row_text
    assert drv.execute_script(
        "return document.querySelector('input[name=occasionChk]').checked;") is False
    # 그리고 그 상태로는 안전장치가 잠겨 있어야 한다.
    assert booking.slot_row_is_ticked(drv) is False
    p = booking.Prepared(target_date="20260908", cell_selected=True,
                         row_ticked=ok, row_index=row_idx)
    res = booking.open_modal(drv, p)
    assert not res.ok and res.reason == "guard_row"


def test_the_real_notice_containers_are_actually_found(drv):
    """실제 컨테이너는 popup_wrap 이다. .popup 으로는 하나도 안 잡혔다."""
    assert drv.execute_script(
        "return document.querySelectorAll('.popup_wrap').length;") > 0
    drv.execute_script(
        "var e = document.querySelector('.popup_wrap');"
        "e.style.display = 'block'; e.style.width = '400px'; e.style.height = '200px';"
        "e.innerHTML = '<p>예약시간전입니다.</p>';")
    notices = booking.read_notices(drv)
    assert any("예약시간전" in n for n in notices), notices
    assert booking.classify(" ".join(notices)) == booking.R_TOO_EARLY


def test_the_child_row_still_reads_correctly_on_the_real_page(drv):
    """같은 화면에서 아동 선택 자체는 정상으로 남아 있어야 한다."""
    got = booking._js(drv, booking._JS_PICK_CHILD, "아동가", default=None)
    assert got and got.get("found") and got.get("matched")
    assert got.get("how") == "occasionChk"
    assert "아동가" in got.get("line", "")

    # 없는 이름이면 아무것도 누르지 않는다.
    miss = booking._js(drv, booking._JS_PICK_CHILD, "없는아이", default=None)
    assert miss and miss.get("found") and miss.get("matched") is False
    assert miss.get("clicked") is False
