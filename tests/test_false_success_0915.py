# -*- coding: utf-8 -*-
"""2026-09-15 09:00:00 의 **거짓 성공**. 이 프로젝트 최악의 실패 모드다.

그날 고객 PC 로그(v1.0.12):

    [09:00:00] [확인] 1발째 · 도착 추정 정각 +278ms · 서버: 예약이 완료 [ok · 예약 성공]
    [09:00:00] 판정 근거: 화면 안내 문구 (서버 응답 본문은 못 봤습니다)

고객 화면에는 '선예약' 이 떴다. 우리는 '예약 성공' 을 찍었다.

진단 ZIP(`...-20260915-090001.zip`) 을 열어보면 그 순간 화면에 있던 것은
결과가 아니라 **넷퍼널 가상대기열** 안내다. `page_source/0002_handover_after.html`
의 `<div id="NetFunnel_Loading_Popup" style="display: block; ... visibility:
visible">` 안, 태그를 걷어낸 원문 그대로:

    시간제 보육 예약 대기 중 입니다. 예상대기시간 : 03초
    현재 앞에 31 명, 뒤에 1 명의 대기자가 있습니다.
    현재 접속 사용자가 많아 대기 중이며, 잠시만 기다리시면 예약이 완료됩니다.
    * 시간당 인원이 초과 될 경우 예약이 불가할 수 있습니다.

같은 ZIP 에서:
  - `layer-alert-popup-contents*` 여섯 개가 **전부 비어 있다**. 결과 알림은 없었다.
  - `xhr_bodies_handover_after.json` 의 `submit` 이 `null` 이다. InsertOcreqst 는
    아직 나가지도 않았다(`submitSeen: false`).
  - 네트워크 덤프에 `ts.wseq?opcode=5101`(대기열 진입) 한 건만 있고, 09-09/09-14
    에 있던 `opcode=5004`(반납) 가 없다. 우리는 줄에 선 채로 run 을 끝냈다.
  - '선예약' 이라는 글자는 ZIP 어디에도 없다. 고객이 그 문구를 본 것은 우리가
    이미 '성공' 을 찍고 끝낸 뒤였다.

원인은 두 개다. 이 파일은 그 둘을 각각 못박는다.

  결함 1  OK_WORDS 에 "예약이 완료" 라는 **조각**이 있었고, `_scan_page_source`
          가 page_source 통짜에서 그 조각을 집어 R_OK 를 돌려줬다. 그래서 로그의
          '서버 문구' 도 문장이 아니라 조각이었다. 부분일치는 금지한다.
  결함 2  `read_outcome_detail` 이 제출 응답을 기다리기 전에 화면 문구로 판정을
          끝내 버렸다. SUBMIT_WAIT_SECONDS=9.0 은 한 번도 쓰이지 않았다.

그리고 결함 1 의 독은 이 리포에 2026-08-26 부터 들어 있었다:
`ci/fixtures/real/netfunnel_waiting.html` 에 같은 문장이 그대로 있는데, 어떤
테스트도 그 픽스처를 분류기에 물려본 적이 없다.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from aisarang import booking  # noqa: E402

NETFUNNEL_FIXTURE = os.path.join(ROOT, "ci", "fixtures", "real",
                                 "netfunnel_waiting.html")
# 09-15 그날 화면에서 글자 그대로 잘라낸 것. 대기열 팝업 + **비어 있는** 알림
# 컨테이너 세 개. 우리가 가진 '진짜 패배' 표본은 이 모양이다.
LOSS_FIXTURE = os.path.join(ROOT, "ci", "fixtures", "real",
                            "netfunnel_queue_20260915.html")

# --------------------------------------------------------- 실물 문자열 (verbatim)
#
# 아래 두 개는 지어낸 글자가 아니다. 위 ZIP 과 커밋된 픽스처에서 그대로 옮겼다.

# 2026-09-15 09:00:00, 고객 화면. 우리가 '성공' 으로 읽은 그 문장.
QUEUE_SENTENCE_0915 = "현재 접속 사용자가 많아 대기 중이며, 잠시만 기다리시면 예약이 완료됩니다."

# 같은 팝업 전체(태그 제거 후). 숫자만 그날 값이다.
QUEUE_POPUP_0915 = (
    "시간제 보육 예약 대기 중 입니다. 예상대기시간 : 03초 "
    "현재 앞에 31 명, 뒤에 1 명의 대기자가 있습니다. "
    "현재 접속 사용자가 많아 대기 중이며, 잠시만 기다리시면 예약이 완료됩니다. "
    "* 시간당 인원이 초과 될 경우 예약이 불가할 수 있습니다. "
    "※ 재접속하시면 대기시간이 더 길어집니다. [중지]"
)

# 2026-09-09 / 09-14, 같은 고객, 서버 응답 본문에서 읽은 진짜 성공 문구.
OK_SENTENCE_REAL = booking.OK_REAL          # "1건 예약 중 1건 예약되었습니다."


# ============================================================ 결함 1: 분류기

def test_the_0915_queue_sentence_is_not_a_success():
    """이 한 줄이 09-15 의 거짓 성공 그 자체다."""
    code = booking.classify(QUEUE_SENTENCE_0915)
    assert code != booking.R_OK, (
        f"넷퍼널 대기열 안내를 '예약 성공' 으로 읽었다: {QUEUE_SENTENCE_0915!r}")
    assert code == booking.R_UNKNOWN, code


def test_the_whole_0915_queue_popup_is_not_a_success():
    code = booking.classify(QUEUE_POPUP_0915)
    assert code != booking.R_OK, code
    assert code == booking.R_UNKNOWN, code


def test_completed_and_not_completed_land_on_opposite_verdicts():
    """'예약이 완료되었습니다' 와 '예약이 완료되지 않았습니다' 는 정반대다.

    부분일치를 쓰면 뒤쪽이 앞쪽을 통째로 품기 때문에 둘이 같은 칸에 떨어진다.
    """
    assert booking.classify("예약이 완료되었습니다.") == booking.R_OK
    assert booking.classify("예약이 완료되지 않았습니다.") != booking.R_OK
    assert booking.classify("1건 예약 중 1건 예약되었습니다.") == booking.R_OK
    assert booking.classify("1건 예약 중 1건 예약되지 않았습니다.") != booking.R_OK


def test_a_future_tense_completion_is_not_a_completion():
    """'완료됩니다'(앞으로) 와 '완료되었습니다'(이미) 를 가른다."""
    assert booking.classify("잠시만 기다리시면 예약이 완료됩니다.") != booking.R_OK
    assert booking.classify("예약이 완료되었습니다.") == booking.R_OK


def test_the_real_taken_string_still_wins_its_own_label():
    """선예약은 지금까지 쓰던 R_TAKEN 과 그 라벨 그대로여야 한다."""
    assert booking.classify(booking.TAKEN_REAL) == booking.R_TAKEN
    assert booking.outcome_label(booking.R_TAKEN) == "선예약(다른 이용자가 먼저 가져감)"
    assert booking.classify(f"알림 {booking.TAKEN_REAL} 확인") == booking.R_TAKEN


def test_the_known_good_success_strings_still_pass():
    """고치면서 진짜 성공을 잃으면 안 된다. 셋 다 실물이다."""
    for s in (booking.OK_REAL, booking.OK_REAL_ALERT,
              "1건 예약 중 1건 예약되었습니다.",
              "예약이 정상적으로 완료되었습니다.",
              "신청이 완료되었습니다."):
        assert booking.classify(s) == booking.R_OK, s


def test_an_unrecognised_screen_string_is_unknown_never_ok():
    """읽어내지 못한 문구는 성공이 아니라 판정 불가다."""
    for s in ("", "   ", "잠시만 기다려 주십시오.", "처리 중입니다",
              "예약 내역을 확인해 주세요.", QUEUE_SENTENCE_0915):
        assert booking.classify(s) != booking.R_OK, s


# ============================================================ 결함 1: 페이지 훑기

class _PageDriver:
    """page_source 만 있는 드라이버. 화면 읽기 JS 는 전부 빈 결과."""

    def __init__(self, page_source: str, queue: bool = False):
        self.page_source = page_source
        self.queue = queue

    def execute_script(self, script, *args):
        if "__aisarangSubmit" in script:
            return None
        if "NetFunnel_Loading_Popup" in script:
            return {"queue": self.queue, "ahead": 31, "behind": 1,
                    "eta": "03초", "progress": "0 % (0/31)"}
        return []

    @property
    def switch_to(self):
        raise RuntimeError("no alert")


def _netfunnel_html() -> str:
    if not os.path.isfile(NETFUNNEL_FIXTURE):
        pytest.skip("netfunnel_waiting.html 픽스처가 없습니다")
    with open(NETFUNNEL_FIXTURE, encoding="utf-8") as fh:
        return fh.read()


def test_the_committed_netfunnel_fixture_carries_the_poison():
    """독이 든 문장이 리포 픽스처에 진짜로 들어 있다는 것부터 못박는다.

    실물에서 이 문장은 `<div>` 두 개에 걸쳐 있다. 그래서 태그를 걷어낸 뒤에
    대조한다. 통짜 `page_source` 훑기가 위험한 이유가 바로 이것이다.
    """
    import re as _re
    flat = _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", _netfunnel_html()))
    assert QUEUE_SENTENCE_0915.replace(" ", "") in flat.replace(" ", "")


def test_scanning_the_netfunnel_page_never_yields_a_success():
    """09-15 의 오프라인 재현. 이 페이지에서 R_OK 가 나오면 그게 그 사고다."""
    hit = booking._scan_page_source(_PageDriver(_netfunnel_html()))
    assert hit is None or hit[0] != booking.R_OK, hit


def _loss_html() -> str:
    if not os.path.isfile(LOSS_FIXTURE):
        pytest.skip("netfunnel_queue_20260915.html 픽스처가 없습니다")
    with open(LOSS_FIXTURE, encoding="utf-8") as fh:
        return fh.read()


def test_the_real_0915_screen_is_never_read_as_a_success():
    """그날 고객 화면 그대로를 물린다. 이게 이 파일의 본체다.

    실제로 자리는 제3자에게 넘어갔고 고객은 20260929 예약을 갖지 못했다.
    그런데 우리는 '예약 성공' 을 찍었다. 다시는 안 된다.
    """
    hit = booking._scan_page_source(_PageDriver(_loss_html()))
    assert hit is None or hit[0] != booking.R_OK, hit


def test_the_real_0915_screen_has_no_result_alert_at_all():
    """결과 알림 컨테이너는 그날 전부 비어 있었다. 읽을 결과가 없었다."""
    import re as _re
    for body in _re.findall(
            r'id="layer-alert-popup-contents\d?"[^>]*>(.*?)</',
            _loss_html(), _re.S):
        assert body.strip() == "", body


def test_the_0915_capture_contains_no_taken_string():
    """'선예약' 은 그 ZIP 어디에도 없다. 우리가 먼저 끝냈기 때문이다.

    서버가 보낸 선예약 원문의 출처는 09-04 캡처(booking.TAKEN_REAL) 다.
    두 근거를 섞어서 '09-15 에서 선예약 문구를 읽었다' 고 적으면 안 된다.
    """
    assert "선예약" not in _loss_html()


def test_a_real_alert_on_the_page_is_read_as_a_whole_sentence():
    """진짜 알림은 조각이 아니라 문장으로 기록되어야 한다(09-14 는 조각이었다)."""
    html = ('<div class="popup_wrap s_size wp400 type-alert2" '
            'id="layer-alert-popup2" style="display: block;">'
            '<h5>알림</h5><p class="f_18" id="layer-alert-popup-contents2">'
            + OK_SENTENCE_REAL + "</p></div>")
    hit = booking._scan_page_source(_PageDriver(html))
    assert hit is not None
    assert hit[0] == booking.R_OK
    assert hit[1] == OK_SENTENCE_REAL, hit[1]


# ============================================================ 결함 2: 기다리기


class _SubmitDriver:
    """제출 슬롯이 `delay` 초 뒤에 done 이 되는 드라이버."""

    def __init__(self, body: str, delay: float, page_source: str = "",
                 queue: bool = False, seen: bool = True):
        self.body = body
        self.ready_at = time.time() + delay
        self.page_source = page_source
        self.queue = queue
        self.seen = seen

    def execute_script(self, script, *args):
        if "__aisarangSubmit" in script:
            if not self.seen:
                return None
            done = time.time() >= self.ready_at
            return {"seq": 1, "url": "/icms/occasion/InsertOcreqst.html",
                    "method": "POST", "t0": 1789430400300,
                    "t1": 1789430400900 if done else 0, "done": done,
                    "status": 200 if done else 0,
                    "responseBody": self.body if done else "",
                    "responseHeaders":
                        "date: Tue, 15 Sep 2026 00:00:00 GMT\r\n",
                    "firedAt": 1789430400280, "stale": False}
        if "NetFunnel_Loading_Popup" in script:
            return {"queue": self.queue, "ahead": 31, "behind": 1,
                    "eta": "03초", "progress": "0 % (0/31)"}
        return []

    @property
    def switch_to(self):
        raise RuntimeError("no alert")


def test_the_screen_never_beats_a_submit_that_is_still_in_flight():
    """09-14 가 이것이었다. 응답이 77ms 뒤에 왔는데 화면으로 먼저 끝냈다.

    화면에는 성공 알림이 떠 있고 서버 본문은 '선예약' 이다. 본문이 이겨야 한다.
    """
    html = ('<p id="layer-alert-popup-contents2">' + OK_SENTENCE_REAL + "</p>")
    body = '{"returnmsg":"' + booking.TAKEN_REAL + '","returnval":""}'
    d = _SubmitDriver(body, delay=0.6, page_source=html)
    out = booking.read_outcome_detail(d, timeout=0.2, submit_timeout=3.0)
    assert out.source == "submit", out.source
    assert out.code == booking.R_TAKEN, (out.code, out.text)
    assert out.text == booking.TAKEN_REAL


def test_a_visible_queue_forbids_any_screen_verdict():
    """09-15. 대기열이 떠 있으면 아직 아무것도 제출되지 않았다.

    화면에 뭐가 쓰여 있든 그것은 이번 발사의 결과가 아니다. 제출이 끝내 안
    잡히면 답은 unknown 이지 ok 가 아니다.
    """
    d = _SubmitDriver("", delay=99.0, page_source=_netfunnel_html(),
                      queue=True, seen=False)
    out = booking.read_outcome_detail(d, timeout=0.2, submit_timeout=0.8)
    assert out.code != booking.R_OK, (out.code, out.text)
    assert out.code == booking.R_UNKNOWN, (out.code, out.text)
    assert out.queued is True


def test_the_queue_clearing_into_a_taken_body_is_read_as_taken():
    """대기열이 풀리고 서버가 '선예약' 이라고 답하면 그대로 taken 이다.

    09-15 에 9초를 기다렸다면 우리가 봤어야 할 결과다.
    """
    body = '{"returnmsg":"' + booking.TAKEN_REAL + '","returnval":""}'
    d = _SubmitDriver(body, delay=0.5, page_source=_netfunnel_html(),
                      queue=True)
    out = booking.read_outcome_detail(d, timeout=0.2, submit_timeout=3.0)
    assert out.source == "submit"
    assert out.code == booking.R_TAKEN, (out.code, out.text)


def test_a_screen_only_success_is_still_reachable_when_nothing_was_submitted():
    """제출이 끝내 안 잡히는 사이트 변경까지 막아버리면 도구가 죽는다.

    화면 창을 다 쓴 뒤에는 진짜 알림 문장으로 성공을 인정한다. 다만 근거는
    'screen' 으로 남아야 한다.
    """
    html = '<p id="layer-alert-popup-contents2">' + OK_SENTENCE_REAL + "</p>"
    d = _SubmitDriver("", delay=99.0, page_source=html, seen=False)
    out = booking.read_outcome_detail(d, timeout=0.4, submit_timeout=0.4)
    assert out.code == booking.R_OK, (out.code, out.text)
    assert out.source == "screen"
    assert out.text == OK_SENTENCE_REAL


def test_the_evidence_line_still_names_its_source():
    """`판정 근거:` 줄은 어떤 경로에서도 근거의 출처를 말해야 한다."""
    from aisarang import handover
    body = '{"returnmsg":"' + booking.OK_REAL + '","returnval":"success"}'
    sub = booking.read_outcome_detail(_SubmitDriver(body, delay=0.0),
                                      timeout=0.3, submit_timeout=1.0)
    assert "서버 응답 본문" in handover._evidence_line(sub)

    html = '<p id="layer-alert-popup-contents2">' + OK_SENTENCE_REAL + "</p>"
    scr = booking.read_outcome_detail(
        _SubmitDriver("", delay=99.0, page_source=html, seen=False),
        timeout=0.3, submit_timeout=0.3)
    assert "화면 안내 문구" in handover._evidence_line(scr)

    q = booking.read_outcome_detail(
        _SubmitDriver("", delay=99.0, page_source=_netfunnel_html(),
                      queue=True, seen=False),
        timeout=0.2, submit_timeout=0.5)
    line = handover._evidence_line(q)
    assert "대기열" in line, line
