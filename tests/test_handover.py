# -*- coding: utf-8 -*-
"""인계 모드를 **실물 캡처 마크업**에 대고 진짜 크롬으로 돌린다.

여기 픽스처는 재현본이 아니다.

  ci/fixtures/real/modal_open.html
      2026-08-25, 고객이 자기 공동인증서 세션에서 손으로 확인창까지 걸었을 때
      서버가 실제로 내려준 화면. **사람이 만든 설정**의 실물이 이것이다.
  ci/fixtures/real/grid_selected_row_added.html
      같은 세션, 칸 선택 + 선택표 1행. 확인창은 아직 없다.
  ci/fixtures/real/netfunnel_waiting.html
      2026-08-26 08:57 고객 PC 캡처의 **진짜 가상대기열 레이어**
      (`ci/build_netfunnel_fixture.py`). 그날 확인창 자리에 뜬 것이 이것이다.
  ci/fixtures/real/too_early_alert.html
      2026-08-27 09:00:00 고객 PC 캡처의 **진짜 '예약시간전' 알림**
      (`ci/build_too_early_fixture.py`). [확인] 한 발이 확인창을 소비하고
      그 자리에 뜬 것이 이것이고, 문구는 InsertOcreqst.html 의 returnmsg
      원문("아직 예약 가능한 시간이 아닙니다.") 이다.

이 파일이 못박는 것은 두 가지뿐이고, 둘 다 브리프의 요구다.
  1. 사람이 만들어 둔 설정 위에서는 **실제로 발사한다**
  2. 확인창이 없거나 대기열이거나 체크가 꺼져 있으면 **절대 발사하지 않는다**

체크박스에 대한 주의: 캡처에는 사람이 켠 체크가 남지 않는다. click 은
attribute 가 아니라 property 를 바꾸고 page_source 는 attribute 만 직렬화하기
때문이다. 그래서 아래에서 `.checked = true` 로 사람이 켠 상태를 되살린다.
실행 중에는 살아 있는 DOM 의 `.checked` 를 그대로 읽으므로 이 문제가 없다.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ci"))

from aisarang import automation, booking, config, handover  # noqa: E402

REAL_DIR = os.path.join(ROOT, "ci", "fixtures", "real")

pytestmark = pytest.mark.skipif(
    not all(os.path.isfile(os.path.join(REAL_DIR, n))
            for n in ("netfunnel_waiting.html", "too_early_alert.html",
                      "taken_alert.html")),
    reason="실물 캡처 픽스처가 없습니다 (python ci/build_netfunnel_fixture.py, "
           "python ci/build_too_early_fixture.py, python ci/build_taken_fixture.py)",
)


def _driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"selenium 없음: {exc}")
    o = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1400,1200",
              "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"):
        o.add_argument(a)
    try:
        return webdriver.Chrome(options=o)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"크롬을 띄우지 못함: {type(exc).__name__}")


@pytest.fixture(scope="module")
def site():
    from real_fixture_server import RealFixtureServer
    srv = RealFixtureServer(REAL_DIR)
    srv.__enter__()
    d = _driver()

    def go(name, tick=False):
        d.get(srv.url(name))
        assert d.execute_script("return document.readyState;") in ("interactive",
                                                                  "complete")
        if tick:
            got = d.execute_script(
                "var b=document.getElementById('rowSchChkNo0');"
                "if(!b) return false; b.checked = true; return b.checked;")
            assert got is True, "선택표 체크박스를 찾지 못했습니다"
        return d

    try:
        yield go
    finally:
        try:
            d.quit()
        except Exception:
            pass
        srv.__exit__(None, None, None)


# --------------------------------------------------- 사람이 만든 설정에서 쏜다

def test_handover_fires_on_a_setup_a_human_made(site):
    """확인창이 열려 있고 선택표 체크가 켜져 있으면 실제로 [확인] 을 누른다.

    v1.0.7 의 `Prepared.ready()` 로는 이 상황에서 절대 못 쐈다. 그 판정은
    `cell_selected` 를 보는데 그 값은 우리 `click_cell` 안에서만 참이 되고
    다시 계산되지 않기 때문이다. 인계 모드는 살아 있는 화면에서 다시 읽는다.
    """
    d = site("modal_open.html", tick=True)
    st = handover.read_state(d)

    assert st.modal is True, st.as_dict()
    assert st.modal_how == "layer-confirm-popup2", st.modal_how
    assert "예약하시겠습니까" in st.modal_text, st.modal_text[:120]
    assert st.asks is True
    assert st.confirm is True
    # 최종 [확인] 은 -confirm 이 아니라 -confirm2 다(layerpopup.js 의 confirm2).
    assert st.confirm_id == "layer-confirm-popup-confirm2", st.confirm_id
    assert st.ticked == 1, st.as_dict()
    assert "해솔아이" in st.row_text, st.row_text
    assert st.armed is True
    assert st.queue is False
    assert st.ready() is True, st.blockers()

    assert handover.fire(d) is True
    fired_at = d.execute_script("return window.__aisarang_fired_at;")
    assert fired_at, "발사 시각이 기록되지 않았습니다"
    # 눌린 것이 떠 있는 껍데기 안의 -confirm2 인지 확인한다.
    got = d.execute_script(
        "var b = window.__aisarang_ok;"
        "var s = b.closest(\"[id='layer-confirm-popup2']\");"
        "return {id: b.id, text: (b.textContent||'').trim(),"
        "        shellStyle: s ? s.getAttribute('style') : null};")
    assert got["id"] == "layer-confirm-popup-confirm2", got
    assert got["text"] == "확인"
    assert "display: block" in (got["shellStyle"] or ""), got


def test_the_program_never_navigates_or_prepares_in_this_mode(site):
    """읽고 조준하는 동안 주소도, 화면 내용도 바뀌지 않는다."""
    d = site("modal_open.html", tick=True)
    before = d.current_url
    marks = d.execute_script(
        "return {html: document.body.innerHTML.length,"
        " rows: document.querySelectorAll('#INFOQUALF tr').length};")
    for _ in range(5):
        handover.read_state(d)
    after = d.execute_script(
        "return {html: document.body.innerHTML.length,"
        " rows: document.querySelectorAll('#INFOQUALF tr').length};")
    assert d.current_url == before
    assert after == marks, (marks, after)


# --------------------------------------------------- 안 되는 상황에서는 안 쏜다

def test_handover_refuses_when_the_dialog_is_missing(site):
    """설정은 다 돼 있는데 확인창이 없다. 누르지 않는다."""
    d = site("grid_selected_row_added.html", tick=True)
    st = handover.read_state(d)

    assert st.on_reserve_page is True
    assert st.ticked == 1, st.as_dict()
    assert st.modal is False, st.modal_text[:120]
    assert st.confirm is False and st.armed is False
    assert st.ready() is False
    assert "예약 확인창이 화면에 없습니다" in st.blockers(), st.blockers()

    assert handover.fire(d) is False
    assert d.execute_script("return window.__aisarang_ok;") is None
    assert "확인창 없음" in handover.describe(st), handover.describe(st)


def test_handover_refuses_when_the_row_tick_is_off(site):
    """확인창은 떠 있는데 선택표 체크가 꺼져 있다. 누르지 않는다.

    잘못된 행이 예약되면 되돌릴 수 없다(취소는 센터 전화로만 된다).
    그래서 막히는 쪽으로 실패한다.
    """
    d = site("modal_open.html", tick=False)
    st = handover.read_state(d)

    assert st.modal is True and st.confirm is True and st.armed is True
    assert st.ticked == 0, st.as_dict()
    assert st.ready() is False
    assert "선택표 행의 체크가 켜져 있지 않습니다" in st.blockers(), st.blockers()


def test_handover_waits_out_the_real_queue_instead_of_calling_it_a_failure(site):
    """2026-08-26 그 화면. 대기열은 실패가 아니라 기다릴 상태다."""
    d = site("netfunnel_waiting.html", tick=True)
    st = handover.read_state(d)

    assert st.queue is True, st.as_dict()
    # 캡처된 실측값 그대로.
    assert st.queue_ahead == 72, st.queue_ahead
    assert st.queue_behind == 26, st.queue_behind
    assert "2분" in st.queue_eta and "10초" in st.queue_eta, st.queue_eta
    assert st.modal is False
    assert st.ready() is False
    assert handover.fire(d) is False

    line = handover.describe(st)
    assert "가상대기열" in line and "72명" in line, line
    assert "앞에 72명" in st.queue_line(), st.queue_line()


def test_the_capture_says_a_reload_makes_the_wait_longer(site):
    """레이어가 직접 적어 놓은 경고. 이 판의 이유다."""
    d = site("netfunnel_waiting.html")
    body = d.execute_script(
        "var e = document.querySelectorAll(\"[id='NetFunnel_Loading_Popup']\")[0];"
        "return (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();")
    assert "대기 중" in body, body
    assert "재접속하시면 대기시간이 더 길어집니다" in body, body
    assert "현재 앞에 72 명" in body.replace("  ", " "), body


# ------------------------------- 2026-08-27 09:00 의 그 화면 (실물 캡처, 진짜 크롬)

def test_the_real_too_early_alert_is_read_and_classified(site):
    """그날 서버가 실제로 돌려준 문구를, 그날의 실제 마크업에서 읽는다.

    v1.0.8 까지 우리 분류기 시험은 순환논증이었다. 픽스처가 우리가 지어낸
    '예약시간전' 을 찍고 우리가 그것을 알아맞혔다. 이제 기준은
    InsertOcreqst.html 의 returnmsg 원문이다.
    """
    d = site("too_early_alert.html", tick=True)

    shown = d.execute_script(
        "var out=[];"
        "document.querySelectorAll(\"[id='layer-alert-popup2']\").forEach(function(e){"
        "  if (e.getBoundingClientRect().height > 0)"
        "    out.push((e.innerText||e.textContent||'').replace(/\\s+/g,' ').trim());"
        "});"
        "return out;")
    assert len(shown) == 1, shown
    assert booking.TOO_EARLY_REAL in shown[0], shown[0]

    # 우리 판정기가 읽는 경로(read_notices)로도 같은 글자가 나와야 한다.
    notices = booking.read_notices(d)
    hit = [n for n in notices if booking.TOO_EARLY_REAL in n]
    assert hit, notices[:5]
    assert booking.classify(hit[0]) == booking.R_TOO_EARLY, hit[0]

    # 그리고 이 화면은 '쏠 수 없는' 화면이다: 확인창이 소비돼 사라졌다.
    st = handover.read_state(d)
    assert st.modal is False and st.ready() is False
    assert st.on_reserve_page is True and st.ticked == 1, st.as_dict()
    assert st.queue is False


def test_the_real_too_early_wording_is_not_the_sites_own_refusal():
    """실물 두 문구가 한 글자 차이다. 섞이면 재시도할 자리를 버리게 된다.

        예약시간전  "아직 예약 가능**한** 시간이 아닙니다."  (서버 returnmsg)
        칸 거절     "예약 가능 시간이 아닙니다."             (selectDay2)
    """
    assert booking.classify(booking.TOO_EARLY_REAL) == booking.R_TOO_EARLY
    assert booking.classify("예약 가능 시간이 아닙니다.") == booking.R_NOT_BOOKABLE
    # '아직' 이 붙으면 어느 표기든 '아직 안 열렸다' 로 읽는다.
    assert booking.classify("아직 예약 가능 시간이 아닙니다.") == booking.R_TOO_EARLY
    assert booking.result_is_retryable(booking.classify(booking.TOO_EARLY_REAL))


# ------------------------------- 2026-09-01 09:00 의 그 화면 (실물 캡처, 진짜 크롬)

def test_the_real_taken_alert_is_read_and_classified(site):
    """2026-09-01 에 서버가 실제로 돌려준 '선예약' 문구를 그날 마크업에서 읽는다.

    그날 조준은 정각 +685ms, 도착 추정 +686ms 였고 서버 답은 이것이었다.
    v1.0.9 의 분류기는 이 문구를 [unknown] 으로 흘렸다. 동작 자체는 안전했지만
    (되살리기가 too_early 에서만 열리므로 잠겨 있었다) 라벨이 틀렸다.
    """
    d = site("taken_alert.html", tick=True)

    shown = d.execute_script(
        "var out=[];"
        "document.querySelectorAll(\"[id='layer-alert-popup2']\").forEach(function(e){"
        "  if (e.getBoundingClientRect().height > 0)"
        "    out.push((e.innerText||e.textContent||'').replace(/\\s+/g,' ').trim());"
        "});"
        "return out;")
    assert len(shown) == 1, shown
    assert booking.TAKEN_REAL in shown[0], shown[0]

    notices = booking.read_notices(d)
    hit = [n for n in notices if booking.TAKEN_REAL in n]
    assert hit, notices[:5]
    assert booking.classify(hit[0]) == booking.R_TAKEN, hit[0]

    # 이 화면도 '쏠 수 없는' 화면이다: [확인] 한 발이 확인창을 소비했다.
    st = handover.read_state(d)
    assert st.modal is False and st.ready() is False
    assert st.on_reserve_page is True and st.ticked == 1, st.as_dict()


def test_the_taken_wording_in_the_fixture_is_the_servers_own(site):
    """상수가 우리가 지어낸 글자가 아니라는 것을 픽스처에서 대조한다.

    v1.0.8 때 지어낸 '예약시간전' 픽스처가 분류기 시험을 순환논증으로 만들었다.
    ci/build_taken_fixture.py 는 고객 PC 캡처 ZIP 에서 알림 레이어를 그대로
    떠온다. 그러니 그 파일 안의 글자와 booking.TAKEN_REAL 이 같아야 한다.
    """
    raw = open(os.path.join(REAL_DIR, "taken_alert.html"), encoding="utf-8").read()
    m = re.search(r'id="layer-alert-popup-contents2">([^<]+)<', raw)
    assert m, "픽스처에서 알림 본문을 찾지 못했습니다"
    assert m.group(1).strip() == booking.TAKEN_REAL, m.group(1)


def test_taken_is_not_confused_with_success_or_too_early():
    """성공 문구와 선예약 문구는 앞부분이 같다. 절대 섞이면 안 된다.

        성공    "1건 예약 중 1건 예약되었습니다."           (2026-08-31 실물)
        선예약  "1건 예약 중 1건 예약이 선예약으로 인해 …"  (2026-09-01 실물)
    """
    ok_real = "1건 예약 중 1건 예약되었습니다."
    assert booking.classify(ok_real) == booking.R_OK
    assert booking.classify(booking.TAKEN_REAL) == booking.R_TAKEN
    assert booking.classify(f"알림 {booking.TAKEN_REAL} 확인") == booking.R_TAKEN
    # 건수 접두사는 제출 줄 수에 따라 변한다. 뼈대만 보므로 따라가야 한다.
    assert booking.classify(
        "3건 예약 중 2건 예약이 선예약으로 인해 예약되지 않았습니다.") == booking.R_TAKEN
    # 다시 쏴도 자리는 돌아오지 않는다.
    assert not booking.result_is_retryable(booking.R_TAKEN)
    # too_early 와도, 사이트 자체 거절과도 갈린다.
    assert booking.classify(booking.TOO_EARLY_REAL) == booking.R_TOO_EARLY
    assert booking.classify("예약 가능 시간이 아닙니다.") == booking.R_NOT_BOOKABLE


def test_taken_never_reopens_the_reserve_button():
    """선예약을 맞으면 되살리기 문은 영구히 잠긴다. [예약하기] 재클릭 금지.

    2026-08-26 에 재진입이 고객을 72번 -> 177번으로 밀어냈다. 그날의 교훈이
    새 결과 코드에도 그대로 적용되는지 여기서 못박는다.
    """
    gate = handover._Reopen(_FakeClock(OPEN + 1.0), OPEN, 2, 15.0)
    gate.note_outcome(booking.R_TAKEN)
    assert gate.locked is True
    st = handover.LiveState(on_reserve_page=True, ticked=1, modal=False,
                            confirm=False, queue=False)
    assert gate.allowed(st) is False
    assert "unknown" not in gate.why_not(st)


def test_recovery_closes_the_real_alert_and_presses_the_real_reserve_button(site):
    """되살리기가 실물 마크업 위에서 정확히 두 개만 누른다는 것을 못박는다.

    누르는 것: 알림의 [확인](#layer-popup-close2) 하나, [예약하기]
    (#timecareConfirm, onclick=fnSave()) 하나. 그게 전부다.
    예약 확인창의 [확인](-confirm2)은 **한 번도 눌리지 않는다.**

    사이트의 진짜 fnSave 는 픽스처에서 제거돼 있다(넷퍼널과 ajax 를 부른다).
    그 자리에 계수기를 놓아 '진짜 버튼의 진짜 onclick 이 불렸는가' 만 센다.
    """
    d = site("too_early_alert.html", tick=True)
    d.execute_script(
        "window.__fnSave = 0; window.fnSave = function(){ window.__fnSave++; };"
        "window.__alertClose = 0; window.__confirmClick = 0;"
        "document.querySelectorAll(\"[id^='layer-popup-close']\").forEach("
        "  function(a){ a.addEventListener('click', function(){"
        "    window.__alertClose++; }); });"
        "document.querySelectorAll(\"[id='layer-confirm-popup-confirm2']\").forEach("
        "  function(a){ a.addEventListener('click', function(){"
        "    window.__confirmClick++; }); });")

    gate = handover._Reopen(_FakeClock(OPEN + 1.0), OPEN, 2, 15.0)
    gate.note_outcome(booking.R_TOO_EARLY)
    st = handover.read_state(d)
    assert gate.allowed(st) is True, gate.why_not(st)
    assert gate.do(d, lambda *_: None) is True

    got = d.execute_script(
        "return {save: window.__fnSave, alert: window.__alertClose,"
        "        confirm: window.__confirmClick};")
    assert got["save"] == 1, got          # [예약하기] 정확히 한 번
    assert got["alert"] == 1, got         # 알림 닫기 정확히 한 번
    assert got["confirm"] == 0, got       # 확인창은 건드리지 않았다
    assert gate.used == 1 and gate.locked is False


def test_close_result_alert_never_touches_the_confirm_dialog(site):
    """확인창이 떠 있는 화면에서 알림 닫기를 불러도 아무것도 누르지 않는다."""
    d = site("modal_open.html", tick=True)
    d.execute_script(
        "window.__confirmClick = 0;"
        "document.querySelectorAll(\"[id='layer-confirm-popup-confirm2']\").forEach("
        "  function(a){ a.addEventListener('click', function(){"
        "    window.__confirmClick++; }); });")
    assert booking.close_result_alert(d) == ""
    assert d.execute_script("return window.__confirmClick;") == 0
    # 확인창은 그대로 살아 있다.
    assert handover.read_state(d).ready() is True


# --------------------------------------------------- booking 쪽 대기열 판정기

def test_booking_queue_reader_agrees_with_the_handover_reader(site):
    """두 판정기가 같은 화면에서 같은 답을 내야 한다.

    발사 순간의 왕복을 줄이려고 인계 모드는 자기 스크립트 한 벌을 따로
    들고 있다. 그 둘이 어긋나면 한쪽만 대기열을 못 본다.
    """
    d = site("netfunnel_waiting.html")
    q = booking.queue_info(d)
    st = handover.read_state(d)
    assert q["queue"] is True and st.queue is True
    assert q["ahead"] == st.queue_ahead == 72, (q, st.queue_ahead)
    assert q["behind"] == st.queue_behind == 26, (q, st.queue_behind)
    assert "앞에 72명" in booking.queue_line(q), booking.queue_line(q)

    d2 = site("modal_open.html")
    assert booking.queue_info(d2).get("queue") is False


def test_handle_netfunnel_no_longer_trips_on_the_leftover_script_tag(site):
    """v1.0.7 은 page_source 에 'NetFunnel' 이 있으면 대기열로 봤다.

    [예약하기] 를 누르면 사이트가 ts.wseq 스크립트 태그를 문서에 남기므로
    그 판정은 대기열이 지나간 뒤에도 계속 참이었다. 이제는 보이는 레이어로만
    판정한다.
    """
    d = site("modal_open.html")
    d.execute_script(
        "var s = document.createElement('script');"
        "s.src = 'https://nf.childcare.go.kr:8443/ts.wseq?opcode=5002"
        "&prefix=NetFunnel.gRtype=5002;&aid=mcis_0';"
        "document.head.appendChild(s);")
    assert "NetFunnel" in d.page_source
    assert booking.queue_info(d).get("queue") is False
    assert automation.handle_netfunnel(d, max_wait=2) is False


# --------------------------------------------------- 이 모드는 누를 수가 없다

HANDOVER_SRC = os.path.join(ROOT, "aisarang", "handover.py")

FORBIDDEN = (
    ".click(", ".submit(", "send_keys", "ActionChains", "dispatchEvent",
    "driver.get(", ".execute_async_script",
    # 준비 단계로 되돌아가는 모든 경로.
    "booking.prepare", "booking.open_modal", "booking.press_",
    "booking.click_cell", "booking.tick_slot_row", "booking.redrive_confirm",
    "booking.select_", "booking.choose_", "open_reservation_page",
)


def _code_without_docs(path: str) -> str:
    """주석과 문서화 문자열을 걷어낸 '진짜 코드' 만 돌려준다.

    이 파일은 자기 자신이 무엇을 하지 않는지 문서화 문자열에 길게 적어 두므로,
    글자만 찾으면 그 설명에 걸린다. ast 로 파싱해서 코드만 본다.
    """
    import ast

    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            node.body = body[1:] or [ast.Pass()]
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


# v1.0.9 에서 이 목록이 딱 한 칸 넓어졌다. **의도적으로.**
#
# 2026-08-27 09:00:00, [확인] 한 발이 정각 296ms 전에 도착했고 서버가
# "아직 예약 가능한 시간이 아닙니다." 로 버렸다. 그 클릭에 확인창이 소비돼
# 사라졌고, v1.0.8 에는 거기서 할 수 있는 일이 없었다. 자리는 살아 있는데
# 쏠 창이 없었다. 사이트 스크립트 실물상 확인창을 여는 길은 fnSave() 하나뿐이라
# (booking.py 의 v1.0.9 주석에 원문이 있다), 되살리려면 [예약하기] 를 다시
# 눌러야 한다.
#
# 그래서 이 테스트는 "누를 수 있는 코드가 없다" 를 못박는 것을 그만두고,
# **정확히 이 셋만 있다** 를 못박는다. 넷째가 생기면 여기서 깨진다.
PAGE_TOUCHING = {
    "fire_confirm",            # 유일한 발사 경로
    "repress_reserve_button",  # '예약시간전' 뒤에만, _Reopen.do 안에서만
    "close_result_alert",      # 되살리기 직전 결과 알림 닫기
}

# handover.py 가 booking 에서 가져다 쓰는 것 중 화면을 건드리지 않는 것들.
READ_ONLY_BOOKING = {
    "_JS_ARM", "read_outcome", "classify", "StepResult",
    "R_OK", "R_FULL", "R_NOT_BOOKABLE", "R_TOO_EARLY", "R_UNKNOWN", "R_FAIL",
    # R_TAKEN 은 '선예약'(자리를 뺏김) 결과 코드다. 읽기만 하는 상수이므로
    # 화면을 건드리지 않는다. 2026-09-01 실물 응답에서 왔다.
    "R_TAKEN",
    "TOO_EARLY_REAL", "TAKEN_REAL",
    # v1.0.12: 판정 근거를 서버 응답 본문에서 읽는다. 셋 다 읽기 전용이다.
    # read_outcome_detail 은 execute_script 로 window.__aisarangSubmit 를
    # **읽기만** 한다(클릭/제출/화면 이동 없음). outcome_label 은 사전 조회,
    # SUBMIT_WAIT_SECONDS 는 상수다.
    "read_outcome_detail", "outcome_label", "SUBMIT_WAIT_SECONDS",
}


def _booking_attrs_used(path: str) -> dict:
    """handover.py 가 부르는 booking.<이름> 을 전부 모은다: 이름 -> 감싼 함수들."""
    import ast

    tree = ast.parse(open(path, encoding="utf-8").read())
    owner = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                owner.setdefault(id(child), node.name)
    used = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id == "booking"):
            continue
        used.setdefault(node.attr, set()).add(owner.get(id(node), "<module>"))
    return used


def test_handover_touches_the_page_only_through_three_named_calls():
    """이 모드가 화면을 건드리는 길이 정확히 셋뿐이라는 것을 못박는다.

    v1.0.8 까지 이 테스트는 "누를 수 있는 코드가 한 줄도 없다" 였다. v1.0.9 는
    '예약시간전' 응답에 한해 [예약하기] 재클릭을 허용하므로, 같은 강도를
    유지하려면 목록을 지우는 게 아니라 **화이트리스트로 바꿔야** 한다.
    넷째 경로가 생기면 여기서 깨진다.
    """
    body = _code_without_docs(HANDOVER_SRC)
    for token in FORBIDDEN:
        assert token not in body, f"인계 모드에 {token} 이 들어왔습니다"

    used = _booking_attrs_used(HANDOVER_SRC)
    touching = set(used) - READ_ONLY_BOOKING
    assert touching == PAGE_TOUCHING, (
        f"화면을 건드리는 booking 호출이 달라졌습니다: {sorted(touching)}")


def test_the_reserve_button_is_reachable_only_from_the_too_early_gate():
    """[예약하기] 재클릭은 `_Reopen.do` 한 곳에서만 나올 수 있다.

    다른 함수가 그것을 부르기 시작하면(예: 확인창이 없을 때 그냥 눌러버리기)
    2026-08-26 의 72명 → 138명 → 177명 이 그대로 돌아온다.
    """
    used = _booking_attrs_used(HANDOVER_SRC)
    assert used["repress_reserve_button"] == {"do"}, used["repress_reserve_button"]
    assert used["close_result_alert"] == {"do"}, used["close_result_alert"]
    assert used["fire_confirm"] == {"fire"}, used["fire_confirm"]

    # `do` 는 _Reopen 의 메서드이고, burst 안에서 `allowed()` 를 통과한
    # 자리에서만 불린다.
    import ast

    tree = ast.parse(open(HANDOVER_SRC, encoding="utf-8").read())
    klass = next(n for n in tree.body
                 if isinstance(n, ast.ClassDef) and n.name == "_Reopen")
    assert "do" in {m.name for m in klass.body
                    if isinstance(m, ast.FunctionDef)}

    burst = next(n for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "burst")
    calls = [n for n in ast.walk(burst)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "do"]
    assert len(calls) == 1, "burst 안에서 되살리기는 정확히 한 자리에서만 불린다"
    guards = [n for n in ast.walk(burst)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "allowed"]
    assert len(guards) == 1, "되살리기 문은 정확히 한 번만 열린다"


def test_handover_state_script_only_reads():
    """상태 스크립트에는 조작 코드가 없다. 조준조차 booking 이 한다."""
    js = handover._JS_HANDOVER_STATE
    for token in (".click(", ".submit(", "dispatchEvent", ".value =",
                  "__aisarang_fire"):
        assert token not in js, token
    assert "window.__aisarang_modal = e;" in js


# --------------------------------------------------- 자동 모드의 재준비 금지

def test_pressing_reserve_disables_re_preparation():
    """[예약하기] 를 누른 뒤의 실패 코드는 재준비 금지 목록에 있어야 한다."""
    from aisarang.runner import Runner
    assert set(Runner.PRESSED_RESERVE) == {"no_modal", "no_modal_queue",
                                           "not_armed"}
    # 반대로 누르기 전의 실패는 재시도 가능해야 한다.
    for reason in ("guard_cell", "guard_row", "no_reserve_button",
                   "no_capacity", "cell_not_selected", "row_not_ticked"):
        assert reason not in Runner.PRESSED_RESERVE, reason


def test_auto_mode_never_re_prepares_once_reserve_was_pressed(monkeypatch):
    """오늘 아침 그 루프가 다시 돌지 않는다는 것을 실제 호출 수로 못박는다.

    v1.0.7 은 `open_modal` 이 no_modal 이면 20초 뒤 `prepare` 를 처음부터 다시
    불렀고, 그것을 정각까지 반복했다(고객 로그에 4회차까지 찍혀 있다).
    이제는 한 번 누른 뒤에는 준비를 다시 하지 않는다.
    """
    import threading

    from aisarang import runner as runnermod

    calls = {"prepare": 0, "open_modal": 0, "watch": 0}

    def fake_prepare(*a, **kw):
        calls["prepare"] += 1
        return booking.StepResult(True, "준비가 끝났습니다.", "prepared",
                                  booking.Prepared(target_date="20260909"))

    def fake_open_modal(driver, p, log=None, diag=None, deadline_local=None):
        calls["open_modal"] += 1
        return booking.StepResult(
            False, "가상대기열에서 순번을 기다리는 중입니다. 앞에 72명",
            "no_modal_queue", p, {"queue": {"queue": True, "ahead": 72}})

    monkeypatch.setattr(booking, "prepare", fake_prepare)
    monkeypatch.setattr(booking, "open_modal", fake_open_modal)

    r = runnermod.Runner()
    r.stop_event = threading.Event()
    r.driver = object()
    monkeypatch.setattr(r, "_watch_for_late_modal",
                        lambda last, open_epoch: calls.__setitem__(
                            "watch", calls["watch"] + 1))

    class _Clock:
        correction = 0.0

        def server_now(self):
            return 1000.0

        def local_time_for(self, epoch):
            return epoch

    r.clock = _Clock()
    out = r._prepare_with_retries({}, "20260909", [9], 9, {}, 1240.0)

    assert calls["prepare"] == 1, calls
    assert calls["open_modal"] == 1, calls
    assert calls["watch"] == 1, "확인창이 늦게라도 열리는지는 지켜봐야 한다"
    assert out.reason == "no_modal_queue"
    assert not out.ok


def test_run_mode_defaults_to_handover_and_survives_a_bad_value():
    assert config.normalize_run_mode(None) == config.MODE_HANDOVER
    assert config.normalize_run_mode("") == config.MODE_HANDOVER
    assert config.normalize_run_mode("nonsense") == config.MODE_HANDOVER
    assert config.normalize_run_mode("AUTO") == config.MODE_AUTO
    assert config.DEFAULT_SETTINGS["run_mode"] == config.MODE_HANDOVER


def test_describe_lines_are_readable_korean():
    """고객이 화면을 사진으로 찍어 보낸다. 그 줄이 읽혀야 한다."""
    ready = handover.LiveState(modal=True, modal_text="예약하시겠습니까?",
                               confirm=True, armed=True, ticked=1)
    assert handover.describe(ready) == (
        "확인창 감지됨 · 선택표 체크 켜짐 · 정각에 [확인] 을 누릅니다")
    assert handover.describe(handover.LiveState()) == (
        "확인창 없음 · 크롬 창에서 예약 확인창까지 진행해 주세요")
    assert handover.describe(handover.LiveState(ticked=1)) == (
        "선택표 체크 켜짐 · 확인창 없음 ([예약하기] 를 눌러주세요)")
    queued = handover.LiveState(queue=True, queue_ahead=138, queue_eta="3분  50초")
    assert "앞에 138명" in handover.describe(queued)
    for line in (handover.describe(ready), handover.describe(queued)):
        assert "—" not in line
        assert re.search(r"[가-힣]", line)


@pytest.mark.parametrize("name", ["netfunnel_waiting.html", "too_early_alert.html"])
def test_the_captured_fixtures_carry_no_personal_data(name):
    """픽스처는 커밋된다."""
    body = open(os.path.join(REAL_DIR, name),
                encoding="utf-8", errors="replace").read()
    allowed = {"100000000000000001", "200101-3000000", "t***@example.com",
               "010-0000-0000", "010", "0000", "000", "00", "00000", "0",
               "테스트로 1", "000-000"}
    for pat in (r"(?<!\d)\d{18}(?!\d)", r"\d{6}\s*-\s*[1-4]\d{6}",
                r"[\w.+-]+@[\w-]+\.[\w.]+",
                r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}"):
        for hit in re.findall(pat, body):
            text = hit if isinstance(hit, str) else "".join(hit)
            assert text in allowed, (pat, text[:24])


# ------------------------------------ '예약시간전' 되살리기 (v1.0.9, 실전 실패의 결과)
#
# 2026-08-27 09:00:00 고객 PC 진단 ZIP `…-20260827-090021.zip`:
#
#   [09:00:00] [확인] 1발째 · 도착 추정 정각 -296ms
#              · 서버: 알림 아직 예약 가능한 시간이 아닙니다. 확인 [too_early]
#   [09:00:01] 선택표 체크 켜짐 · 확인창 없음 ([예약하기] 를 눌러주세요)
#
# 한 발이 전부였다. 확인창이 클릭에 소비됐기 때문이다. 이제 그 응답에 한해
# [예약하기] 를 다시 눌러 창을 되살린다. 아래가 그 문의 자물쇠 전부다.

class _FakeClock:
    """server_now 만 필요한 자리에 쓰는 가짜 시계."""

    def __init__(self, now: float, step: float = 0.0):
        self._now = float(now)
        self._step = float(step)

    def server_now(self) -> float:
        now = self._now
        self._now += self._step
        return now

    def arrival_for_local_fire(self, local_epoch: float) -> float:
        return self._now

    def note_too_early(self, *_a, **_kw) -> float:
        return 0.0


OPEN = 1000.0


def _closed(**kw) -> "handover.LiveState":
    """[확인] 을 쏜 직후의 화면: 확인창은 사라졌고 선택표 체크는 그대로다."""
    base = dict(modal=False, confirm=False, armed=False,
                rows=1, ticked=1, on_reserve_page=True, queue=False)
    base.update(kw)
    return handover.LiveState(**base)


def _gate(code=booking.R_TOO_EARLY, now=OPEN + 2.0, max_times=2, seconds=15.0):
    g = handover._Reopen(_FakeClock(now), OPEN, max_times, seconds)
    if code is not None:
        g.note_outcome(code)
    return g


def test_reopen_opens_only_for_a_too_early_answer():
    assert _gate().allowed(_closed()) is True


@pytest.mark.parametrize("code", [booking.R_FULL, booking.R_NOT_BOOKABLE,
                                  booking.R_UNKNOWN, booking.R_FAIL,
                                  booking.R_OK])
def test_reopen_refuses_every_other_answer(code):
    """정원초과 / 칸 거절 / 미분류 / 실패 / 성공. 어느 것도 되살리지 않는다.

    특히 정원초과는 자리가 나간 것이라 다시 눌러도 소용이 없고, 미분류는
    무슨 일이 일어났는지 모르는 상태라 손대면 안 된다.
    """
    assert _gate(code=code).allowed(_closed()) is False


def test_reopen_refuses_when_nothing_was_ever_fired():
    """아직 한 발도 안 쐈는데 확인창이 없는 것은 그냥 '고객이 아직 안 눌렀다' 다."""
    assert _gate(code=None).allowed(_closed()) is False


def test_reopen_never_fires_while_the_queue_layer_is_up():
    """가상대기열 위에서는 절대 누르지 않는다. 그게 이 모드가 생긴 이유다."""
    assert _gate().allowed(_closed(queue=True, ticked=1)) is False


def test_reopen_locks_forever_once_a_queue_shows_up():
    """되살린 뒤 대기열이 뜨면 기다린다. 다시 누르면 맨 뒤로 간다."""
    g = _gate()
    g.lock("가상대기열에 섰습니다(다시 누르면 맨 뒤로 갑니다)")
    g.note_outcome(booking.R_TOO_EARLY)
    assert g.allowed(_closed()) is False
    assert "대기열" in g.why_not(_closed())


def test_reopen_refuses_when_the_dialog_is_still_open():
    """창이 살아 있으면 되살릴 이유가 없다. 그냥 다시 쏘면 된다."""
    assert _gate().allowed(_closed(modal=True, confirm=True, armed=True)) is False


def test_reopen_refuses_when_the_prepared_screen_is_gone():
    """선택표 체크가 풀렸거나 예약 화면을 벗어났으면 누르지 않는다."""
    assert _gate().allowed(_closed(ticked=0)) is False
    assert _gate().allowed(_closed(on_reserve_page=False)) is False


def test_reopen_respects_the_wall_clock_window():
    """정각 전에는 안 누르고, 마감(reopen_seconds)이 지나도 안 누른다."""
    assert _gate(now=OPEN - 0.5).allowed(_closed()) is False
    assert _gate(now=OPEN + 14.9, seconds=15.0).allowed(_closed()) is True
    assert _gate(now=OPEN + 15.1, seconds=15.0).allowed(_closed()) is False


def test_reopen_is_hard_capped():
    """상한을 넘겨서 누르지 않는다. 0 이면 아예 안 누른다."""
    g = _gate(max_times=2)
    g.used = 2
    assert g.allowed(_closed()) is False
    assert _gate(max_times=0).allowed(_closed()) is False


def test_reopen_needs_a_fresh_too_early_for_each_press(monkeypatch):
    """한 번 되살린 뒤에는 새 '예약시간전' 이 있어야 또 누를 수 있다."""
    monkeypatch.setattr(booking, "close_result_alert", lambda *a, **k: "")
    monkeypatch.setattr(booking, "repress_reserve_button", lambda *a, **k: True)
    g = _gate(max_times=2)
    assert g.do(object(), lambda *_: None) is True
    assert g.allowed(_closed()) is False        # 아직 새 답을 못 들었다
    g.note_outcome(booking.R_TOO_EARLY)
    assert g.allowed(_closed()) is True


def test_reopen_locks_when_the_reserve_button_is_gone(monkeypatch):
    monkeypatch.setattr(booking, "close_result_alert", lambda *a, **k: "")
    monkeypatch.setattr(booking, "repress_reserve_button", lambda *a, **k: False)
    g = _gate()
    assert g.do(object(), lambda *_: None) is False
    g.note_outcome(booking.R_TOO_EARLY)
    assert g.allowed(_closed()) is False


# --------------------------------------------------- burst 전체 흐름

class _ScriptedWatcher:
    """poll() 이 미리 정해둔 상태를 차례로 돌려준다. 마지막 것은 계속 유지."""

    def __init__(self, states):
        self._states = list(states)
        self.state = self._states[0]

    def poll(self):
        self.state = self._states[0]
        if len(self._states) > 1:
            self._states.pop(0)
        return self.state


def _ready(**kw):
    base = dict(modal=True, modal_text="예약하시겠습니까?", confirm=True,
                armed=True, rows=1, ticked=1, on_reserve_page=True)
    base.update(kw)
    return handover.LiveState(**base)


def _run_burst(monkeypatch, states, outcomes, **kw):
    calls = {"fire": 0, "repress": 0, "close": 0}

    def fake_fire(_driver):
        calls["fire"] += 1
        return True

    def fake_outcome(_driver, timeout=0.0, submit_timeout=None):
        # handover.burst 가 부르는 이름은 v1.0.12 부터 read_outcome_detail 이고,
        # 돌려주는 것은 (코드, 원문) 이 아니라 Outcome 이다. 여기서 튜플을 계속
        # 돌려주면 shot.code 에 튜플이 들어가 모든 분기가 조용히 빗나간다.
        code, text = outcomes[min(calls["fire"], len(outcomes)) - 1]
        return booking.Outcome(code=code, text=text, source="screen")

    def fake_repress(_driver, log=lambda *_: None):
        calls["repress"] += 1
        return True

    def fake_close(_driver, log=lambda *_: None):
        calls["close"] += 1
        return booking.TOO_EARLY_REAL

    monkeypatch.setattr(handover, "fire", fake_fire)
    monkeypatch.setattr(booking, "read_outcome_detail", fake_outcome)
    monkeypatch.setattr(booking, "repress_reserve_button", fake_repress)
    monkeypatch.setattr(booking, "close_result_alert", fake_close)

    opts = dict(retry_seconds=3, retry_ms=20, reopen_max=2, reopen_seconds=3.0)
    opts.update(kw)
    res = handover.burst(object(), _FakeClock(OPEN + 0.5, step=0.12), OPEN,
                         _ScriptedWatcher(states), log=lambda *_: None, **opts)
    return res, calls


def test_burst_recovers_from_a_real_too_early_and_wins_the_second_shot(monkeypatch):
    """2026-08-27 그대로: 첫 발이 '예약시간전' → 창 되살리기 → 두 번째 발 성공.

    문구는 지어낸 것이 아니라 그날 서버가 실제로 돌려준 원문이다.
    """
    res, calls = _run_burst(
        monkeypatch,
        states=[_ready(), _closed(), _ready()],
        outcomes=[(booking.R_TOO_EARLY, booking.TOO_EARLY_REAL),
                  (booking.R_OK, "예약이 완료되었습니다.")])
    assert res.ok is True and res.reason == "reserved"
    assert calls["fire"] == 2, calls
    assert calls["repress"] == 1, calls
    assert calls["close"] == 1, "되살리기 전에 결과 알림을 닫는다"
    assert res.detail["reopen"]["used"] == 1
    assert res.detail["confirmAttempts"] == 2


def test_burst_never_represses_after_a_capacity_answer(monkeypatch):
    """'정원초과' 는 자리가 나간 것이다. 두들기지 않는다."""
    res, calls = _run_burst(
        monkeypatch,
        states=[_ready(), _closed(), _closed()],
        outcomes=[(booking.R_FULL, "정원초과입니다.")])
    assert res.ok is False and res.reason == "full"
    assert calls["fire"] == 1 and calls["repress"] == 0, calls


def test_burst_never_represses_after_an_unrecognised_answer(monkeypatch):
    """무슨 일이 일어났는지 모르면 손대지 않는다."""
    res, calls = _run_burst(
        monkeypatch,
        states=[_ready(), _closed(), _closed(), _closed()],
        outcomes=[(booking.R_UNKNOWN, "??")])
    assert calls["repress"] == 0, calls
    assert res.detail["reopen"]["locked"] is True


def test_burst_waits_out_a_queue_that_appears_after_the_repress(monkeypatch):
    """되살렸더니 대기열이 떴다. 기다린다. 절대 다시 누르지 않는다."""
    res, calls = _run_burst(
        monkeypatch,
        states=[_ready(), _closed(), _closed(queue=True)],
        outcomes=[(booking.R_TOO_EARLY, booking.TOO_EARLY_REAL)])
    assert calls["fire"] == 1
    assert calls["repress"] == 1, calls
    assert res.detail["reopen"]["locked"] is True
    assert "대기열" in res.detail["reopen"]["lockReason"]


def test_burst_stops_at_the_repress_cap(monkeypatch):
    """계속 '예약시간전' 이어도 **되살리기**는 상한까지만 한다.

    상한이 걸리는 것은 [예약하기] 재클릭 쪽이다. 그 뒤에 고객이 손으로 창을
    다시 열어주면 그 창에는 여전히 쏜다(그게 이 모드의 본래 일이다).
    아래 마지막 _ready() 가 그 경우이고, 되살리기 수는 그대로 2 다.
    """
    res, calls = _run_burst(
        monkeypatch,
        states=[_ready(), _closed(), _ready(), _closed(), _ready(),
                _closed(), _ready(), _closed()],
        outcomes=[(booking.R_TOO_EARLY, booking.TOO_EARLY_REAL)] * 6,
        reopen_max=2)
    assert calls["repress"] == 2, calls
    assert calls["close"] == 2, calls
    assert calls["fire"] == 4, calls
    assert res.detail["reopen"]["used"] == 2
    assert res.ok is False


def test_burst_never_represses_without_a_shot(monkeypatch):
    """확인창이 처음부터 없었으면(고객이 아직 안 눌렀다) 우리가 누르지 않는다."""
    res, calls = _run_burst(
        monkeypatch,
        states=[_closed(), _closed(), _closed()],
        outcomes=[(booking.R_OK, "")])
    assert calls["fire"] == 0 and calls["repress"] == 0, calls
    assert res.reason == "never_ready"
