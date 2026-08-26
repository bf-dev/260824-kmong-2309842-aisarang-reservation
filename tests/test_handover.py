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
    not os.path.isfile(os.path.join(REAL_DIR, "netfunnel_waiting.html")),
    reason="실물 캡처 픽스처가 없습니다 (python ci/build_netfunnel_fixture.py)",
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


def test_handover_has_no_way_to_touch_the_page_except_the_final_confirm():
    """소스에 누를 수 있는 코드가 한 줄도 없다는 것을 못박는다.

    누가 "확인창이 닫혔으니 [예약하기] 한 번만 다시 눌러주자" 를 넣으면 이
    테스트가 깨진다. 그 한 번이 2026-08-26 에 고객의 대기열 순번을
    72명 → 138명 → 177명 으로 밀어냈다.
    """
    body = _code_without_docs(HANDOVER_SRC)
    for token in FORBIDDEN:
        assert token not in body, f"인계 모드에 {token} 이 들어왔습니다"
    # 유일하게 허용된 발사 경로.
    assert "booking.fire_confirm(driver)" in body


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


def test_the_netfunnel_fixture_carries_no_personal_data():
    """픽스처는 커밋된다."""
    body = open(os.path.join(REAL_DIR, "netfunnel_waiting.html"),
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
