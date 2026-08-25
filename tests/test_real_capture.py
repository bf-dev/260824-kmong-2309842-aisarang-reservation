# -*- coding: utf-8 -*-
"""2026-08-25 고객 캡처의 **진짜 4~9단계 화면**에 대고 선택자를 돌린다.

이 파일이 다른 테스트와 다른 점은 근거의 출처다. 여기 픽스처는 우리가
만든 재현본이 아니라, 고객이 자기 PC(Windows 10 19045)에서 진짜 공동인증서
세션으로 진단 기록 모드를 돌리고 예약 흐름을 손으로 끝까지 걸었을 때
서버가 실제로 내려준 응답 그대로다(개인정보만 가명 치환).

  ci/fixtures/real/occasion_time_main_slpl.html  4~9단계를 그리는 ajax 응답
  ci/fixtures/real/grid_ready.html               날짜x시간 표가 그려진 상태
  ci/fixtures/real/grid_selected_row_added.html  칸 선택 + 선택표 1행
  ci/fixtures/real/modal_open.html               예약 확인창이 열린 상태

이 캡처가 들어오기 전까지 4~9단계에는 실제 마크업이 한 줄도 없었고,
그래서 아래 결함들이 전부 살아 있었다. 각 테스트는 그 결함 하나씩을 못박는다.

file:// 이 아니라 http 로 띄운다. file:// 은 문서마다 오리진이 달라 CSS 가
제대로 안 붙고, 그러면 `.popup_wrap{display:none}` 이 죽어서 숨어 있어야 할
확인창 사본까지 '보인다' 로 판정된다.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ci"))

from aisarang import booking  # noqa: E402

REAL_DIR = os.path.join(ROOT, "ci", "fixtures", "real")

pytestmark = pytest.mark.skipif(
    not os.path.isdir(REAL_DIR),
    reason="실물 캡처 픽스처가 없습니다 (python ci/build_real_fixtures.py)",
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
              # 바깥 네트워크는 막고 로컬 픽스처 서버만 연다.
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

    def go(name):
        d.get(srv.url(name))
        return d

    try:
        yield go
    finally:
        try:
            d.quit()
        except Exception:
            pass
        srv.__exit__(None, None, None)


# ------------------------------------------------------------------ 6단계 표

def test_grid_reads_exactly_the_real_time_cells(site):
    """숨은 벌점/개월 칸을 시간대로 착각하지 않는다.

    실물 한 줄은 이렇게 생겼다:
        th#day_0 + a#tm_9_0 .. a#tm_17_0 (9칸)
        + td#pp_0(벌점 2) + td#bm_0(개월 10) + td#nsc_0(0)   <- display:none
    예전 _JS_SCAN_GRID 는 '첫 칸이 날짜인 줄의 모든 td' 를 칸으로 세고,
    헤더에 글자가 없으면 시각을 `8 + 열번호` 로 지어냈다. 그래서 14x9=126
    이어야 할 표가 **168칸**으로 읽혔고, 없는 18/19/20시가 각각
    남은 자리 2명 / 10명 / 0명 으로 잡혔다.
    """
    d = site("grid_ready.html")
    raw = d.execute_script(booking._JS_SCAN_GRID)
    assert raw is not None
    assert raw["how"] == "crtminfo", raw.get("how")
    assert len(raw["rows"]) == 14, len(raw["rows"])
    assert len(raw["cells"]) == 126, len(raw["cells"])

    hours = sorted({c["hour"] for c in raw["cells"]})
    assert hours == [9, 10, 11, 12, 13, 14, 15, 16, 17], hours
    # 숨은 열에서 온 유령 시간대가 하나도 없어야 한다.
    assert 18 not in hours and 19 not in hours and 20 not in hours


def test_grid_dates_come_from_the_hidden_resdt_input(site):
    """이용일의 정답은 화면 글자가 아니라 input[name=resdt] 의 YYYYMMDD 다."""
    d = site("grid_ready.html")
    g = booking.read_grid(d)
    dates = [r["date"] for r in g.rows]
    assert dates[0] == "20260826", dates[:3]
    assert all(re.fullmatch(r"\d{8}", x) for x in dates), dates
    # 화면 표기는 2026-08-26(수) 형식이고, 그것도 같이 남아 있어야 한다.
    assert g.rows[0]["label"].startswith("2026-08-26(수)"), g.rows[0]["label"]


def test_grid_cell_ids_are_unpadded_hours(site):
    """칸 id 는 tm_9_0 이지 tm_09_0 이 아니다. 헤더 글자('09')와 다르다."""
    d = site("grid_ready.html")
    g = booking.read_grid(d)
    c = g.find("20260826", 9)
    assert c is not None
    assert c.el_id == "tm_9_0", c.el_id


def test_zero_and_x_cells_are_never_pickable(site):
    """0 은 '자리 없음' 이 아니라 예약대기 전용이고, 우리에겐 못 누르는 칸이다.

    사이트의 selectDay2 는 칸 값이 "0" 이면 wait_gb 를 Y 로 두고
    resbgntm/resendtm 을 비운다. 그 상태로 [추가] 를 누르면 f_AddQualRow 가
    "예약 가능 시간이 아닙니다" 로 막는다. X 는 더 말할 것도 없다.
    """
    d = site("grid_ready.html")
    g = booking.read_grid(d)
    # 실측: 08-26 은 09시와 17시만 1명, 나머지는 0
    assert g.summary("20260826") == (
        "20260826: 09=1 10=0 11=0 12=0 13=0 14=0 15=0 16=0 17=1"), g.summary("20260826")
    cell, why = booking.pick_cell(g, "20260826", [10, 11, 12])
    assert cell is None, cell
    assert "자리" in why
    # 토요일 줄은 전부 X 다.
    sat = g.row_cells("20260829")
    assert sat and all(c.blocked for c in sat), [c.text for c in sat]


def test_no_phantom_hour_can_be_selected(site):
    """숨은 칸의 숫자(벌점 2, 개월 10)를 자리로 착각해 고르지 않는다."""
    d = site("grid_ready.html")
    g = booking.read_grid(d)
    for h in (18, 19, 20):
        assert g.find("20260826", h) is None, h
    cell, why = booking.pick_cell(g, "20260826", [18, 19])
    assert cell is None
    assert "칸 없음" in why, why


def test_selected_cell_is_marked_with_on_and_title(site):
    """고른 칸의 표시는 class 'on' + title='선택됨' 이다 (실측)."""
    d = site("grid_selected_row_added.html")
    mark = d.execute_script(booking._JS_CELL_IS_ON, "tm_9_2")
    assert mark is not None
    assert mark["on"] is True
    assert mark["title"] == "선택됨"
    assert mark["innerOn"] is True
    # 안 고른 칸은 표시가 없어야 한다.
    other = d.execute_script(booking._JS_CELL_IS_ON, "tm_10_2")
    assert other["on"] is False and other["title"] == ""


# ------------------------------------------------------------------ 4·5단계

def test_class_and_hours_selects_are_clname_and_rtm(site):
    """반명은 select#clname, 이용시간은 select#rtm (값 1~9)."""
    d = site("occasion_time_main_slpl.html")
    info = d.execute_script(r"""
      var cl = document.getElementById('clname');
      var rt = document.getElementById('rtm');
      var v = [];
      for (var i = 0; i < rt.options.length; i++) if (rt.options[i].value) v.push(rt.options[i].value);
      return {clName: cl.name, clChange: cl.getAttribute('onchange'),
              rtName: rt.name, rtChange: rt.getAttribute('onchange'), rtVals: v};""")
    assert info["clName"] == "clname"
    assert info["clChange"] == "fnSerChange();"
    assert info["rtName"] == "rtm"
    assert info["rtChange"] == "fnTimeReset();"
    assert info["rtVals"] == ["1", "2", "3", "4", "5", "6", "7", "8", "9"]


def test_select_hours_uses_the_real_rtm_select(site):
    d = site("occasion_time_main_slpl.html")
    got = booking.select_hours(d, 3)
    assert got == 3
    assert d.execute_script(
        "return document.getElementById('rtm').value;") == "3"


# ------------------------------------------------------------------ 7·8단계

def test_add_and_reserve_buttons_are_targeted_by_their_real_ids(site):
    """[추가]=#timecareTableAddBtn, [예약하기]=#timecareConfirm.

    글자로만 찾으면 위험한 이웃이 있다. 같은 btn_right 안에 [삭제]/[새로고침]
    이 있고, [예약하기] 바로 옆이 [예약대기](id=tooltip) 다.
    """
    d = site("grid_ready.html")
    got = d.execute_script(r"""
      var a = document.getElementById('timecareTableAddBtn');
      var b = document.getElementById('timecareConfirm');
      return {add: a.textContent.trim(), addFn: a.getAttribute('onclick'),
              res: b.textContent.trim(), resFn: b.getAttribute('onclick'),
              wait: document.getElementById('tooltip').textContent.trim()};""")
    assert got["add"] == "추가" and got["addFn"] == "f_AddQualRow();"
    assert got["res"] == "예약하기" and got["resFn"] == "fnSave();"
    # 옆에 예약대기가 실제로 있다. 이래서 글자만으로는 부족하다.
    assert got["wait"] == "예약대기"


def test_slot_row_values_live_in_inputs_not_in_text(site):
    """선택표 칸의 내용은 innerText 가 아니라 input.value 에 있다.

    실물 행:
      <td><input id="sdate0" value="2026-08-28(금)" readonly>
          <input type="hidden" id="resdt0" value="20260828"></td>
    예전 스캐너는 텍스트만 읽어서 이 행을 통째로 빈 문자열로 봤다. 그래서
    date 가 늘 비었고, tick_slot_row 는 날짜로 행을 찾지 못해 매번
    rows[-1] 폴백으로 떨어졌으며, 안전장치에 남는 row_text 도 비어 있었다.
    """
    d = site("grid_selected_row_added.html")
    # 텍스트만 읽으면 정말로 비어 있다는 것부터 못박는다.
    text_only = d.execute_script(
        "var t=document.querySelector('#INFOQUALF tbody tr');"
        "return (t.innerText||t.textContent||'').trim();")
    assert text_only == "", repr(text_only)

    got = d.execute_script(booking._JS_SCAN_SLOT_ROWS)
    assert got["how"] == "INFOQUALF", got.get("how")
    assert len(got["rows"]) == 1, got["rows"]
    row = got["rows"][0]
    assert row["date"] == "20260828", row
    assert row["boxId"] == "rowSchChkNo0", row
    assert "해솔아이" in row["text"], row["text"]
    assert "09 : 00" in row["text"], row["text"]


def test_slot_scanner_never_picks_the_child_table(site):
    """아동 표를 선택표로 고르면 엉뚱한 것을 예약하게 된다."""
    d = site("grid_selected_row_added.html")
    got = d.execute_script(booking._JS_SCAN_SLOT_ROWS)
    ti = got["tableIndex"]
    tag = d.execute_script(
        "return document.querySelectorAll('table')[arguments[0]].id;", ti)
    assert tag == "INFOQUALF", tag


# ------------------------------------------------------------------ 9단계

def test_the_page_really_has_two_confirm_shells(site):
    """공용 확인창 껍데기가 페이지에 두 벌 들어 있고 하나만 열려 있다.

    id 가 중복이므로 getElementById 를 쓰면 안 된다. 숨은 쪽에는 사이트가
    콜백을 묶지 않았으므로 그걸 누르면 조용히 아무 일도 안 일어난다.
    """
    d = site("modal_open.html")
    got = d.execute_script(r"""
      var sh = document.querySelectorAll("[id='layer-confirm-popup2']");
      var out = [];
      for (var i = 0; i < sh.length; i++) {
        var r = sh[i].getBoundingClientRect();
        out.push({vis: r.width > 0 && r.height > 0,
                  body: (sh[i].textContent||'').indexOf('예약하시겠습니까') >= 0});
      }
      // 한 껍데기 안에서 닫기 id 가 두 번 나온다(X, 취소).
      var closes = sh[0].querySelectorAll("[id='layer-confirm-popup-close2']").length;
      return {shells: out, closes: closes};""")
    assert len(got["shells"]) == 2, got
    assert [s["vis"] for s in got["shells"]] == [True, False], got
    assert got["shells"][0]["body"] is True
    assert got["closes"] == 2, got["closes"]


def test_modal_anchors_on_the_visible_confirm2_shell(site):
    d = site("modal_open.html")
    m = d.execute_script(booking._JS_MODAL)
    assert m is not None
    assert m["how"] == "layer-confirm-popup2", m
    assert m["okId"] == "layer-confirm-popup-confirm2", m
    assert "예약하시겠습니까" in m["text"], m["text"]


def test_arming_targets_confirm2_inside_the_open_shell(site):
    """최종 [확인] 은 -confirm 이 아니라 **-confirm2** 다.

    layerpopup.js 의 confirm2 가 콜백을 묶는 대상이 그것이고, 예약 흐름은
    confirm2 를 쓴다. 그리고 반드시 **떠 있는 껍데기 안의** 버튼이어야 한다.
    """
    d = site("modal_open.html")
    assert d.execute_script(booking._JS_MODAL) is not None
    assert d.execute_script(booking._JS_ARM) is True
    got = d.execute_script(r"""
      var b = window.__aisarang_ok;
      var shell = b.closest("[id='layer-confirm-popup2']");
      var r = b.getBoundingClientRect();
      return {id: b.id, text: (b.textContent||'').trim(),
              visible: r.width > 0 && r.height > 0,
              shellStyle: shell ? shell.getAttribute('style') : null};""")
    assert got["id"] == "layer-confirm-popup-confirm2", got
    assert got["text"] == "확인"
    assert got["visible"] is True
    assert "display: block" in (got["shellStyle"] or ""), got


def test_still_armed_and_fire_do_not_touch_a_hidden_button(site):
    """창이 닫히면 쏘지 않는다. 발사는 되돌릴 수 없으므로 닫히는 쪽이 안전하다."""
    d = site("modal_open.html")
    d.execute_script(booking._JS_MODAL)
    assert d.execute_script(booking._JS_ARM) is True
    assert d.execute_script(booking._JS_STILL_ARMED) is True
    # 창을 닫으면 조준이 풀려야 하고, 발사는 거부돼야 한다.
    d.execute_script(
        "document.querySelectorAll(\"[id='layer-confirm-popup2']\")[0]"
        ".style.display='none';")
    assert d.execute_script(booking._JS_STILL_ARMED) is False
    assert d.execute_script(booking._JS_FIRE) is False


# ------------------------------------------------- 확인창 문구는 결과가 아니다

def test_the_real_confirm_text_is_not_read_as_a_failure(site):
    """확인창 본문이 '실패' 로 분류되면 성공한 예약을 실패로 보고하게 된다.

    실측 본문에는 '지원이 불가합니다' 와 '60시간을 초과합니다' 가 둘 다
    들어 있다. 예전 FAIL_WORDS 에 '불가' 와 '초과합니다' 가 있었으므로
    이 문장은 그대로 R_FAIL 이었다.
    """
    d = site("modal_open.html")
    body = d.execute_script(
        "var p=document.querySelectorAll("
        "\"[id='layer-confirm-popup-contents2']\");"
        "for(var i=0;i<p.length;i++){var t=(p[i].innerText||'').trim();"
        "if(t) return t;} return '';")
    assert "예약하시겠습니까" in body
    assert "불가합니다" in body and "초과합니다" in body, body
    code = booking.classify(body)
    assert code != booking.R_FAIL, (code, body)
    assert code == booking.R_UNKNOWN, (code, body)
    assert not booking.result_is_retryable(code)


def test_site_side_rejections_are_not_retried():
    """사이트가 스스로 막는 문구는 재시도 대상이 아니다.

    문구는 OccasionTimeMainSlPL.html 의 사이트 자바스크립트에서 그대로 옮겼다.
    예전에는 '예약 가능 시간이 아닙니다' 가 TOO_EARLY 로 분류돼서, 영영
    열리지 않을 칸에 대고 정각의 남은 시간을 전부 태울 수 있었다.
    """
    for text in ("예약 가능 시간이 아닙니다.",
                 "이용시간이 중복되었습니다.",
                 "해당 아동은 이미 예약되어 있습니다.",
                 "해당월의 벌점이 초과하여 예약하실 수 없습니다.",
                 "해당 아동으로 신청 할 수 있는 반이 없습니다.",
                 "점심시간(12:00~13:00)만 예약은 불가능합니다."):
        code = booking.classify(text)
        assert code == booking.R_NOT_BOOKABLE, (text, code)
        assert not booking.result_is_retryable(code), text


def test_customer_reported_words_still_classify():
    """고객이 적어준 두 문구는 아직 서버 실물로 확인되지 않았다.

    2026-08-25 캡처(요청 373건)에 '예약시간전' / '정원초과' 는 한 건도 없다.
    고객이 확인창에서 멈춰 InsertOcreqst.html 이 호출된 적이 없기 때문이다.
    그래서 표기 흔들림을 넓게 열어 둔 채로 유지한다. 이 테스트는 그 상태를
    기록해 두는 것이지, 서버 문구를 증명하는 것이 아니다.
    """
    assert booking.classify("예약시간전입니다.") == booking.R_TOO_EARLY
    assert booking.result_is_retryable(booking.R_TOO_EARLY)
    assert booking.classify("정원초과 되었습니다.") == booking.R_FULL
    assert not booking.result_is_retryable(booking.R_FULL)


# ------------------------------------------------------------------ 위생

def test_the_real_fixtures_carry_no_personal_data():
    """픽스처는 커밋된다. 개인정보가 남으면 안 된다.

    검사도 **모양으로만** 한다. 고객의 진짜 값을 여기 적어두면 픽스처를
    깨끗이 만들어 놓고 정작 테스트 파일에 원본을 남기는 꼴이 된다.
    허용되는 것은 build_real_fixtures.py 가 넣는 더미뿐이다.
    """
    allowed = {"100000000000000001", "200101-3000000",
               "t***@example.com", "010-0000-0000",
               "010", "0000", "000", "00", "00000", "0",
               "테스트로 1", "000-000"}
    shapes = [
        r"(?<!\d)\d{18}(?!\d)",                       # 아동등록번호/회원번호
        r"\d{6}\s*-\s*[1-4]\d{6}",                    # 주민등록번호
        r"[\w.+-]+@[\w-]+\.[\w.]+",                   # 이메일
        r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}",      # 휴대폰
    ]
    for name in os.listdir(REAL_DIR):
        path = os.path.join(REAL_DIR, name)
        if not os.path.isfile(path) or not name.endswith(".html"):
            continue
        body = open(path, encoding="utf-8", errors="replace").read()
        for pat in shapes:
            for hit in re.findall(pat, body):
                text = hit if isinstance(hit, str) else "".join(hit)
                assert text in allowed, (name, pat, text[:24])
