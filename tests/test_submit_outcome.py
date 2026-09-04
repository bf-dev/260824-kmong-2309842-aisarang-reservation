# -*- coding: utf-8 -*-
"""예약 제출의 **서버 응답 본문**으로 판정한다 (v1.0.12).

왜 이 파일이 생겼나. 2026-09-04 09:00:00, 고객 PC, v1.0.11:

    [09:00:00] 조준 확정: 도착 목표 정각 +350ms (시각 오차 ±24ms + 여유 250ms)
    [09:00:01] 지금 [확인] 을 누릅니다!
    [09:00:02] [확인] 1발째 · 도착 추정 정각 +352ms · 서버: (문구 없음) [unknown]

고객은 자기 화면에서 '선예약' 을 읽었는데 우리 로그는 아무것도 못 적었다.
08-28 / 09-01 / 09-02 / 09-04 네 번 같은 일이 있었다. 한 발이 전부인 도구가
그 한 발의 판정을 못 남기는 것이 이 프로젝트에서 제일 나쁜 실패다.

그런데 그날 진단 ZIP 에는 답이 그대로 있었다
(`xhr_bodies_handover_after.json` → `ci/fixtures/real/insert_ocreqst_taken.json`):

    {"returnmsg":"1건 예약 중 1건 예약이 선예약으로 인해 예약되지 않았습니다.",
     "returnval":""}

    HTTP 200, date: Fri, 04 Sep 2026 00:00:00 GMT, 왕복 3,418ms

왕복이 3.4초인데 화면 판정 창은 1.6초였다. 답이 오는 도중에 우리가 포기한 것이다.

여기서 못박는 것:
  1. 픽스처의 문구가 booking.TAKEN_REAL 과 글자 그대로 같다 (지어낸 글자 금지)
  2. 그 본문이 taken 으로 분류된다 (unknown 이 아니다)
  3. 화면이 아무 말도 안 해도 본문만으로 판정이 선다
  4. 응답이 화면 판정 창보다 늦게 와도 기다린다
  5. 지난 발사의 응답을 이번 발사의 판정으로 쓰지 않는다
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import booking, handover

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "ci", "fixtures", "real",
                       "insert_ocreqst_taken.json")


def _fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------ 실물 문구 대조

def test_the_fixture_is_the_servers_own_words():
    """픽스처가 우리 상수와 글자 그대로 같아야 한다.

    v1.0.8 때 우리가 지어낸 '예약시간전' 픽스처로 분류기를 시험해서 순환논증이
    된 적이 있다. 이 파일은 2026-09-04 고객 PC 응답 본문 바이트 그대로다.
    """
    fx = _fixture()
    assert fx["status"] == 200
    assert fx["url"].endswith("InsertOcreqst.html")
    got = booking.parse_submit_body(fx["responseBody"])
    assert got["parsed"] is True
    assert got["returnmsg"] == booking.TAKEN_REAL, got["returnmsg"]
    # 그날 서버는 returnval 을 빈 문자열로 보냈다(= success 가 아니다).
    assert got["returnval"] == ""


def test_the_real_body_classifies_as_taken_not_unknown():
    """이 한 줄이 09-04 로그의 [unknown] 을 대체한다."""
    fx = _fixture()
    msg = booking.parse_submit_body(fx["responseBody"])["returnmsg"]
    assert booking.classify(msg) == booking.R_TAKEN
    assert booking.outcome_label(booking.R_TAKEN) != \
        booking.outcome_label(booking.R_UNKNOWN)
    # 뺏긴 자리는 다시 쏘지 않는다(대기열 맨 뒤로 가는 짓을 부르지 않는다).
    assert booking.result_is_retryable(booking.R_TAKEN) is False


def test_every_known_verbatim_server_string_has_its_own_label():
    """지금까지 실물로 받은 세 문구가 서로 다른 코드로 갈린다."""
    assert booking.classify(booking.OK_REAL) == booking.R_OK
    assert booking.classify(booking.OK_REAL_ALERT) == booking.R_OK
    assert booking.classify(booking.TAKEN_REAL) == booking.R_TAKEN
    assert booking.classify(booking.TOO_EARLY_REAL) == booking.R_TOO_EARLY
    codes = {booking.classify(s) for s in (booking.OK_REAL, booking.TAKEN_REAL,
                                           booking.TOO_EARLY_REAL)}
    assert len(codes) == 3, codes


def test_the_body_parser_survives_a_truncated_or_broken_json():
    """본문이 잘려도 문구는 건진다. 판정을 통째로 잃는 것보다 낫다."""
    body = '{"returnmsg":"' + booking.TAKEN_REAL + '","returnva'
    got = booking.parse_submit_body(body)
    assert got["parsed"] is False
    assert got["returnmsg"] == booking.TAKEN_REAL
    assert booking.classify(got["returnmsg"]) == booking.R_TAKEN


def test_an_empty_body_is_not_a_verdict():
    for body in ("", "   ", "<html>nope</html>"):
        got = booking.parse_submit_body(body)
        assert got["returnmsg"] == ""
        assert booking.classify(got["returnmsg"]) == booking.R_UNKNOWN


# ------------------------------------------------------------ 가짜 드라이버

class FakeDriver:
    """execute_script 만 흉내낸다. 화면은 아무 말도 하지 않는다(09-04 그대로)."""

    def __init__(self, slot=None, page_source=""):
        self.slot = slot
        self.page_source = page_source
        self.scripts = 0

    def execute_script(self, script, *args):
        self.scripts += 1
        if "__aisarangSubmit" in script:
            if self.slot is None:
                return None
            return dict(self.slot)
        # 화면 읽기(_JS_READ_NOTICE 등)는 전부 빈 결과.
        return []

    @property
    def switch_to(self):
        raise RuntimeError("no alert")


def _slot(done=True, body=None, stale=False, status=200):
    fx = _fixture()
    return {"seq": 1, "url": fx["url"], "method": "POST",
            "t0": 1788480001289, "t1": 1788480004707 if done else 0,
            "done": done, "status": status if done else 0,
            "responseBody": (fx["responseBody"] if body is None else body)
            if done else "",
            "responseHeaders": f"date: {fx['date']}\r\ncontent-type: {fx['contentType']}\r\n",
            "firedAt": 1788480001200, "stale": stale}


def test_the_verdict_comes_from_the_body_when_the_screen_says_nothing():
    d = FakeDriver(slot=_slot())
    out = booking.read_outcome_detail(d, timeout=0.4)
    assert out.code == booking.R_TAKEN
    assert out.text == booking.TAKEN_REAL
    assert out.source == "submit"
    assert out.status == 200
    assert out.returnval == ""
    # 서버가 요청을 받은 초. 도착 추정이 아니라 서버가 찍어준 값이다.
    assert out.server_date == "Fri, 04 Sep 2026 00:00:00 GMT"
    assert out.elapsed_ms == 3418.0
    assert out.submit_seen and out.submit_done


def test_a_pending_submit_is_waited_for_past_the_screen_window():
    """09-04 의 진짜 원인. 3.4초 걸리는 답을 1.6초 만에 포기했다."""
    d = FakeDriver(slot=_slot(done=False))
    t0 = time.time()
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=1.0)
    waited = time.time() - t0
    assert waited > 0.3, waited          # 화면 창을 넘겨 기다렸다
    assert waited < 2.0, waited          # 그러나 상한은 지킨다
    assert out.submit_seen is True
    assert out.submit_done is False
    assert out.code == booking.R_UNKNOWN


def test_nothing_submitted_means_we_do_not_wait_at_all():
    """제출이 없으면 기다릴 것도 없다. 화면 창만 쓴다."""
    d = FakeDriver(slot=None)
    t0 = time.time()
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=5.0)
    waited = time.time() - t0
    assert waited < 1.0, waited
    assert out.submit_seen is False
    assert out.code == booking.R_UNKNOWN


def test_a_stale_response_from_an_earlier_shot_is_ignored():
    """지난 발사의 답을 이번 발사의 판정으로 쓰면 조용히 틀린다."""
    d = FakeDriver(slot=_slot(stale=True))
    got = booking.submit_response(d)
    assert got["seen"] is False
    assert got["stale"] is True
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=0.3)
    assert out.source != "submit"
    assert out.code == booking.R_UNKNOWN


def test_the_short_form_still_returns_a_two_tuple():
    """옛 호출부(read_outcome)는 그대로 (코드, 원문) 을 받는다."""
    d = FakeDriver(slot=_slot())
    code, text = booking.read_outcome(d, timeout=0.4)
    assert (code, text) == (booking.R_TAKEN, booking.TAKEN_REAL)


# ------------------------------------------------------------ 훅 / 안전

def test_the_hook_keeps_a_submit_slot_that_the_ring_buffer_cannot_drop():
    """제출 응답이 40건 상한에 밀려 사라지면 09-04 가 그대로 돌아온다."""
    from aisarang import automation

    js = automation._JS_NET_RECORDER
    assert "__aisarangSubmit" in js
    assert "openSubmit" in js and "closeSubmit" in js
    # 전용 칸은 LOG 배열(push/MAX_ROWS)과 무관해야 한다.
    open_at = js.index("function openSubmit")
    close_at = js.index("function closeSubmit")
    assert close_at > open_at
    body = js[open_at:js.index("function clip(")]
    assert "MAX_ROWS" not in body, "제출 칸이 링버퍼 상한에 묶여 있습니다"
    assert "LOG" not in body, "제출 칸이 링버퍼에 묶여 있습니다"
    # 상한에 걸려 push 가 조용히 실패해도 제출 칸은 살아야 한다.
    assert "window.__aisarangSubmit = slot" in body


def test_the_fetch_wrapper_still_calls_the_original_on_window():
    """`_fetch.apply(this, ...)` 로 되돌리면 엄격 모드 페이지가 죽는다.

    2026-09-01 에 실제로 고객 페이지의 fetch 를 그렇게 망가뜨렸다.
    test_diagnostics 에도 같은 못이 있지만, 제출 칸을 fetch 갈래에도 넣었으므로
    여기서 한 번 더 박는다.
    """
    from aisarang import automation

    js = automation._JS_NET_RECORDER
    assert "_fetch.apply(window, arguments)" in js
    assert "_fetch.apply(this" not in js


def test_the_slot_reader_never_asks_for_the_request_body():
    """요청 본문에는 아동 주민번호가 들어 있다. 판정 경로로 끌어오지 않는다."""
    assert "requestBody" not in booking._JS_SUBMIT_SLOT
    d = FakeDriver(slot=_slot())
    got = booking.submit_response(d)
    assert "requestBody" not in got


def test_the_slot_reader_does_not_switch_windows_or_click():
    """페이지 접촉은 execute_script 한 줄뿐이다. 창 전환도 클릭도 없다."""
    js = booking._JS_SUBMIT_SLOT
    for token in (".click(", "window.open", "location", "submit("):
        assert token not in js, token
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "aisarang", "booking.py"),
               encoding="utf-8").read()
    head = src[src.index("def submit_response"):src.index("class Outcome")]
    for token in ("switch_to", "driver.get", "window_handles"):
        assert token not in head, token


def test_the_handover_wait_is_long_enough_for_the_measured_round_trip():
    """09-04 실측 왕복 3,418ms. 상한이 그보다 짧으면 또 놓친다."""
    fx = _fixture()
    assert fx["elapsedMs"] == 3418
    assert handover.SUBMIT_TIMEOUT * 1000.0 > fx["elapsedMs"], \
        handover.SUBMIT_TIMEOUT
    # 화면 판정 창은 여전히 짧다. 재발사 간격을 늘리면 안 된다.
    assert handover.OUTCOME_TIMEOUT <= 2.0


def test_the_shot_record_carries_the_evidence():
    """진단 ZIP 에 '무엇을 근거로 그렇게 판정했는지' 가 남아야 한다."""
    out = booking.Outcome(code=booking.R_TAKEN, text=booking.TAKEN_REAL,
                          source="submit", status=200,
                          body=_fixture()["responseBody"],
                          server_date="Fri, 04 Sep 2026 00:00:00 GMT",
                          elapsed_ms=3418.0, submit_seen=True,
                          submit_done=True)
    shot = handover.HandoverShot(attempt=1, fired=True,
                                 code=out.code, text=out.text, outcome=out)
    d = shot.as_dict()
    assert d["code"] == booking.R_TAKEN
    assert d["label"] == booking.outcome_label(booking.R_TAKEN)
    assert d["outcome"]["source"] == "submit"
    assert booking.TAKEN_REAL in d["outcome"]["body"]
    assert d["outcome"]["serverDate"] == "Fri, 04 Sep 2026 00:00:00 GMT"
    assert d["outcome"]["elapsedMs"] == 3418.0
