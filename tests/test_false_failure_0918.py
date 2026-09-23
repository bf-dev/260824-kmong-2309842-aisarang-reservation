# -*- coding: utf-8 -*-
"""2026-09-18 09:00:00 의 **거짓 실패**. 09-15 거짓 성공의 정확한 거울상이다.

그날 고객 PC 로그(v1.0.15):

    [09:00:00] 지금 [확인] 을 누릅니다!
    [09:00:01] [확인] 1발째 · 도착 추정 정각 +199ms
               · 서버: 아직 예약 가능한 시간이 아닙니다. [too_early · 예약시간전(아직 안 열림)]
    [09:00:01] 판정 근거: 화면 안내 문구 (서버 응답 본문은 못 봤습니다)
    [09:00:21] result=fail

**예약은 성공했다.** 고객이 그렇게 말했고, 진단 ZIP 이 네 겹으로 받쳐준다
(`…-20260918-090021.zip`):

  1. 대기열 표 `ts.wseq?opcode=5101` 이 `__aisarang_fired_at`(1789689600971)과
     **같은 ms** 에 나갔다. 즉 우리 클릭이 사이트의 제출 경로를 실제로 탔다.
  2. 695ms 뒤 `ts.wseq?opcode=5004` = `NetFunnel_Complete()`. 사이트 실물
     스크립트는 이 호출을 InsertOcreqst 의 **ajax success 콜백 안에서만** 한다.
  3. 그 직후 `/?menuno=245` 로 이동했다. 실물 스크립트에서 그 이동은
     `if (data.returnval == "success")` 분기에만 있다.
  4. 신청현황(`OccasionChildResSlPL.html`) 응답에 새 줄이 있다:
     `2026-10-02 09:00 ~ 17:00 … 상태: 예약`, `data-ocseq="5733117"`.
     08:45:56 의 중복확인이 `{"returnValue":"N"}` 이었으니 그 줄은 그날 생겼다.

그런데 왜 `too_early` 를 적었나. 원인 둘이고 이 파일이 그 둘을 못박는다.

  결함 1  **화면에 14분 묵은 알림이 남아 있었다.** 08:46:00 에 이른 제출
          한 건이 나가 서버가 `아직 예약 가능한 시간이 아닙니다.` 를
          돌려줬고, 사이트는 그 글자를 지우지 않고 껍데기만
          `display:none` 으로 숨긴다. 우리 `_scan_page_source` 는 통짜
          HTML 을 보므로 숨은 글자를 그대로 읽었다.
          → 발사 **직전** 화면에 있던 문구는 이번 발사의 답이 아니다.

  결함 2  **제출이 시작되기도 전에 판정을 끝냈다.** `waitedMs` 가 77.9 다.
          사이트 경로는 [확인] → 대기열 표 → fnSubmit → ajax 라서 제출은
          수백 ms 뒤에 시작한다(그날 실측 695ms). 옛 코드는
          `submit_seen == False` 를 '아무것도 안 보냈다' 로 읽고 곧바로
          화면 판정으로 내려갔다.
          → 우리가 방금 쐈다면, 제출이 시작될 시간을 준다.

09-15 와 09-18 은 같은 병이다: **화면 문구를 이번 발사의 답으로 믿는 것.**
그래서 v1.0.16 은 '확실한 근거' 를 서버 응답 본문과 성공 이동으로 좁혔다.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ci"))

from aisarang import booking, config, handover  # noqa: E402

REAL_DIR = os.path.join(ROOT, "ci", "fixtures", "real")
STALE_FIXTURE = os.path.join(REAL_DIR, "stale_alert_after_reopen.html")

# 그날의 원문들. 지어낸 글자가 하나도 없다.
STALE_TEXT = "아직 예약 가능한 시간이 아닙니다."      # 08:46 응답, 화면에 남은 것
OK_BODY = '{"returnmsg":"1건 예약 중 1건 예약되었습니다.","returnval":"success"}'
TOO_EARLY_BODY = '{"returnmsg":"아직 예약 가능한 시간이 아닙니다.","returnval":""}'


# --------------------------------------------------------- 결함 1: 묵은 문구

class _FakeDriver:
    """page_source 와 발사 스냅샷만 있는 최소 드라이버."""

    def __init__(self, page_source="", prefire=(), slot=None, url=""):
        self.page_source = page_source
        self._prefire = list(prefire)
        self._slot = slot
        self._url = url

    def execute_script(self, script, *args):
        # 순서가 중요하다. 제출 칸을 읽는 스크립트(_JS_SUBMIT_SLOT)에도
        # `__aisarang_fired_at` 이 들어 있으므로 그것을 먼저 가른다.
        if "__aisarangSubmit" in script:
            return self._slot
        if "__aisarang_prefire_texts" in script:
            return list(self._prefire)
        if "__aisarang_fired_at" in script:
            return 1789689600971
        if "menuno=245" in script:
            return "menuno=245" in self._url
        return None

    @property
    def switch_to(self):
        raise RuntimeError("no alert")


def _hidden_stale_page() -> str:
    return (
        "<html><body>"
        '<div class="popup_wrap type-alert2" id="layer-alert-popup2" '
        'style="display: none;">'
        f'<p class="f_18" id="layer-alert-popup-contents2">{STALE_TEXT}</p>'
        "</div></body></html>"
    )


def test_the_stale_notice_alone_no_longer_decides_the_verdict():
    """**이 판의 핵심 수정.** 발사 전부터 있던 문구로는 판정하지 않는다.

    옛 코드는 이 화면에서 곧바로 `too_early` 를 돌려줬다. 그것이 09-18 이다.
    """
    d = _FakeDriver(page_source=_hidden_stale_page(),
                    prefire=[STALE_TEXT], slot=None)
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=0.5)

    assert out.code != booking.R_TOO_EARLY, (
        "발사 전부터 화면에 있던 문구를 이번 발사의 답으로 읽었습니다: "
        f"{out.as_dict()}")
    assert out.stale_skipped >= 0
    assert out.confident is False, "화면만 본 판정은 확실하지 않다고 적어야 한다"


def test_without_the_snapshot_the_same_page_would_still_read_too_early():
    """걸러내기가 왜 필요한지. 스냅샷이 없으면 옛 결과가 그대로 재현된다.

    이 시험은 수정의 **필요성**을 고정한다. 누가 `prefire_texts` 를 지우면
    이 줄이 아니라 위 줄이 깨지므로, 둘을 같이 둔다.
    """
    d = _FakeDriver(page_source=_hidden_stale_page(), prefire=[], slot=None)
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=0.5)
    assert out.code == booking.R_TOO_EARLY, out.as_dict()
    assert out.source == "screen"


def test_a_fresh_notice_that_was_not_there_before_still_counts():
    """묵은 것만 버린다. 발사 뒤에 새로 뜬 문구는 그대로 읽는다."""
    page = (
        "<html><body>"
        '<div class="popup_wrap type-alert2" id="layer-alert-popup2" '
        'style="display: block;">'
        '<p class="f_18" id="layer-alert-popup-contents2">'
        "1건 예약 중 1건 예약이 선예약으로 인해 예약되지 않았습니다.</p>"
        "</div></body></html>"
    )
    # 발사 직전에는 **다른** 글자가 있었다(묵은 '예약시간전').
    d = _FakeDriver(page_source=page, prefire=[STALE_TEXT], slot=None)
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=0.5)
    assert out.code == booking.R_TAKEN, out.as_dict()


def test_scan_page_source_skips_only_the_texts_we_saw_before_firing():
    """`_scan_page_source` 단위. 묶은 집합에 있는 문장만 건너뛴다."""
    src = _hidden_stale_page()

    class _D:
        page_source = src

    assert booking._scan_page_source(_D()) == (booking.R_TOO_EARLY, STALE_TEXT)
    assert booking._scan_page_source(_D(), stale={STALE_TEXT}) is None


# --------------------------------------------- 결함 2: 제출 시작을 안 기다렸다

def test_we_wait_for_the_submit_to_start_when_we_just_fired():
    """발사했는데 제출이 아직 안 잡혔으면, 화면만으로 끝내지 않는다.

    09-18 의 `waitedMs` 는 77.9 였다. 그날 제출은 695ms 뒤에 시작했다.
    """
    d = _FakeDriver(page_source=_hidden_stale_page(),
                    prefire=[STALE_TEXT], slot=None)
    t0 = time.time()
    booking.read_outcome_detail(d, timeout=0.2, submit_timeout=2.0)
    waited = time.time() - t0
    assert waited >= booking.SUBMIT_START_GRACE * 0.8, waited


def test_the_grace_is_documented_as_a_real_measurement():
    """상수가 반올림한 숫자가 아니라 실측에서 나왔다는 것을 고정한다."""
    assert booking.SUBMIT_START_GRACE >= 0.7, booking.SUBMIT_START_GRACE
    src = open(os.path.join(ROOT, "aisarang", "booking.py"),
               encoding="utf-8").read()
    assert "695" in src, "실측값(695ms)이 주석에서 사라졌습니다"


# ------------------------------------------- 성공 이동은 화면 문구보다 강하다

def test_navigating_to_the_status_page_is_read_as_success():
    """사이트는 `returnval == "success"` 일 때만 `/?menuno=245` 로 보낸다.

    즉 그 화면에 서 있다는 것 자체가 성공의 증거다. 09-18 에 우리는 그
    화면에 있었는데도 묵은 문구를 읽고 실패를 적었다.
    """
    d = _FakeDriver(page_source="<html><body></body></html>",
                    prefire=[STALE_TEXT], slot=None,
                    url="https://www.childcare.go.kr/?menuno=245")
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=0.5)
    assert out.code == booking.R_OK, out.as_dict()
    assert out.navigated is True
    assert out.confident is True
    assert "신청현황" in booking.evidence_line(out)


def test_the_status_page_wins_over_a_stale_too_early_notice():
    """묵은 '예약시간전' 이 화면에 있어도, 성공 이동이 이긴다."""
    d = _FakeDriver(page_source=_hidden_stale_page(),
                    prefire=[STALE_TEXT], slot=None,
                    url="https://www.childcare.go.kr/?menuno=245")
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=0.5)
    assert out.code == booking.R_OK, out.as_dict()


# ------------------------------------ 서버 응답 본문은 여전히 1순위 그대로다

def test_the_server_body_still_wins_and_is_still_confident():
    """v1.0.12~v1.0.15 의 계약을 깨지 않았다는 것."""
    slot = {"seq": 1, "url": "/icms/occasion/InsertOcreqst.html",
            "method": "POST", "t0": 1789689601000, "t1": 1789689601300,
            "done": True, "status": 200, "responseBody": OK_BODY,
            "responseHeaders": "date: Fri, 18 Sep 2026 00:00:01 GMT\r\n",
            "firedAt": 1789689600971, "stale": False}
    d = _FakeDriver(page_source=_hidden_stale_page(),
                    prefire=[STALE_TEXT], slot=slot)
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=1.0)
    assert out.code == booking.R_OK, out.as_dict()
    assert out.source == "submit"
    assert out.confident is True
    assert out.returnval == "success"


def test_a_real_too_early_from_the_server_body_is_still_too_early():
    """진짜 '예약시간전'(서버 원문)은 그대로 재시도 대상이다.

    걸러내기가 실전 회복을 막지 않는다는 것. 이 줄이 깨지면 v1.0.9~15 의
    회복이 죽는다.
    """
    slot = {"seq": 2, "url": "/icms/occasion/InsertOcreqst.html",
            "method": "POST", "t0": 1789689601000, "t1": 1789689601100,
            "done": True, "status": 200, "responseBody": TOO_EARLY_BODY,
            "responseHeaders": "date: Fri, 18 Sep 2026 00:00:01 GMT\r\n",
            "firedAt": 1789689600971, "stale": False}
    d = _FakeDriver(page_source=_hidden_stale_page(),
                    prefire=[STALE_TEXT], slot=slot)
    out = booking.read_outcome_detail(d, timeout=0.3, submit_timeout=1.0)
    assert out.code == booking.R_TOO_EARLY, out.as_dict()
    assert out.source == "submit"
    assert out.confident is True


# ----------------------------------- 되살리기 문은 서버 원문만 받는다 (v1.0.16)

class _Clk:
    def __init__(self, now):
        self._now = now

    def server_now(self):
        return self._now


OPEN = 1_000_000.0


def _closed_state():
    return handover.LiveState(modal=False, confirm=False, armed=False,
                              rows=1, ticked=1, on_reserve_page=True,
                              queue=False)


def test_a_screen_only_too_early_does_not_take_a_new_queue_ticket():
    """**09-18 의 두 번째 피해.** 화면 문구로 대기열 표를 새로 뽑지 않는다.

    그날 우리는 성공한 예약 뒤에 [예약하기] 를 다시 눌러 새 표를 받았다.
    근거는 묵은 화면 문구 하나였다. v1.0.18 부터는 문이 아예 달라졌다:
    제출 응답 본문 + 서버 원문('아직 예약 가능한 시간이 아닙니다.') 이
    둘 다 있어야 회복한다. 화면 문구(source="screen") 는 원문과 같더라도
    문을 열지 못한다.
    """
    g = handover._Reopen(_Clk(OPEN + 0.5), OPEN)
    g.note_outcome(booking.R_TOO_EARLY,
                   booking.Outcome(code=booking.R_TOO_EARLY,
                                   text=STALE_TEXT, source="screen"))
    assert g.allowed(_closed_state()) is False
    why = g.why_not(_closed_state())
    # v1.0.18: 거절 사유에 '원문 없음' 이 들어간다(화면 문구/대기열 문구 모두).
    assert "원문" in why, why
    assert handover.is_genuine_too_early(
        booking.Outcome(code=booking.R_TOO_EARLY, text=STALE_TEXT,
                        source="screen")) is False


def test_a_server_body_too_early_still_opens_the_gate():
    """진짜 '예약시간전' 이면 예전처럼 열린다. 회복을 죽이지 않았다."""
    g = handover._Reopen(_Clk(OPEN + 0.5), OPEN)
    g.note_outcome(booking.R_TOO_EARLY,
                   booking.Outcome(code=booking.R_TOO_EARLY,
                                   text=STALE_TEXT, source="submit",
                                   status=200, submit_seen=True,
                                   submit_done=True))
    assert g.allowed(_closed_state()) is True


# --------------------------------------- 되살리기 횟수는 실제 클릭만 센다

def test_the_reopen_counter_only_counts_presses_that_happened(monkeypatch):
    """09-18 로그의 `확인창 되살리기 1/6회차` 는 거짓이었다.

    그날 [예약하기] 를 실제로 누른 뒤에 `allowed` 가 다시 거절해서, 세어진
    1 회가 무엇을 뜻하는지 로그만으로는 알 수 없었다. 이제 **누르지 못한
    회차는 세지 않는다.**
    """
    logs = []
    monkeypatch.setattr(booking, "close_result_alert", lambda *a, **k: "")
    monkeypatch.setattr(booking, "repress_reserve_button",
                        lambda *a, **k: False)      # 버튼을 못 찾았다
    g = handover._Reopen(_Clk(OPEN + 0.5), OPEN)
    g.note_outcome(booking.R_TOO_EARLY,
                   booking.Outcome(code=booking.R_TOO_EARLY, source="submit",
                                   submit_seen=True, submit_done=True))

    assert g.do(object(), logs.append) is False
    assert g.used == 0, "누르지 못한 회차를 셌습니다"
    assert g.skipped == 1
    assert g.as_dict()["used"] == 0
    # 누르지 못했으면 '되살리기 N회차' 를 찍지도 않는다.
    assert not any("되살리기" in m for m in logs), logs


def test_the_reopen_counter_does_count_a_press_that_happened(monkeypatch):
    logs = []
    monkeypatch.setattr(booking, "close_result_alert", lambda *a, **k: "")
    monkeypatch.setattr(booking, "repress_reserve_button", lambda *a, **k: True)
    g = handover._Reopen(_Clk(OPEN + 0.5), OPEN)
    g.note_outcome(booking.R_TOO_EARLY,
                   booking.Outcome(code=booking.R_TOO_EARLY, source="submit",
                                   submit_seen=True, submit_done=True))

    assert g.do(object(), logs.append) is True
    assert g.used == 1 and g.skipped == 0
    assert any("되살리기 1/" in m for m in logs), logs


# ------------------------------------------------ 판정 규칙은 그대로다 (0915)

def test_the_success_keyword_rules_were_not_touched():
    """v1.0.13 의 거짓 성공 수정을 되돌리지 않았다."""
    # 조각 일치는 여전히 금지다.
    assert booking.classify("잠시만 기다리시면 예약이 완료됩니다.") != booking.R_OK
    assert booking.classify("현재 앞에 31 명, 뒤에 1 명의 대기자가 있습니다.") \
        != booking.R_OK
    # 실물 성공 문구는 여전히 성공이다.
    assert booking.classify(booking.OK_REAL) == booking.R_OK
    # 실물 선예약은 여전히 taken 이다.
    assert booking.classify(booking.TAKEN_REAL) == booking.R_TAKEN


def test_the_aim_never_goes_backwards_from_199ms():
    """09-18 의 +199ms 는 이긴 조준이다. **뒤로** 되돌리지 않는다.

    브리프는 처음에 250 으로 되돌리라고 했다. 캡처를 열어보니 그 발사는
    성공이었고, 되돌리면 이긴 값을 버리는 것이었다. 앞으로 당기는 것은
    다른 문제다. v1.0.17 은 고객 요청으로 140 까지 당겼고, 이 시험이 막는
    것은 어디까지나 **뒤로 가는** 변경이다.
    """
    assert config.ARRIVAL_SAFETY_MS <= 175.0
    assert config.ARRIVAL_SAFETY_MS == 140.0
    assert config.ARRIVAL_MIN_AFTER_MS == 140.0
    # 하한과 여유는 항상 같이 움직인다(v1.0.15 의 교훈).
    assert config.ARRIVAL_MIN_AFTER_MS == config.ARRIVAL_SAFETY_MS
