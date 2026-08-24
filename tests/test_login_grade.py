# -*- coding: utf-8 -*-
"""로그인 등급 판정 — 실측 조각으로 고정한다.

근거: 2026-08-24, 고객 계정으로 아이디 로그인한 뒤 ?menuno=605 를 열어 받은
실제 응답(docs/site-map/07-reserve-605-idsession.html). 서버가 페이지에
loginMode / targetMode 를 직접 찍어 내려주고, #contents 는 통째로 비어 있었다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import automation

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(ROOT, "ci", "fixtures", "reserve605_id_session.html")
LIVE = os.path.join(ROOT, "docs", "site-map", "07-reserve-605-idsession.html")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


class FakeDriver:
    def __init__(self, src):
        self.page_source = src
        self.current_url = "https://www.childcare.go.kr/?menuno=605"

    def find_element(self, by, sel):
        raise Exception("no body")


def test_server_stamped_modes_are_read():
    login_mode, target_mode = automation.read_login_mode(_read(FIXTURE))
    assert login_mode == "ID"
    assert target_mode == "CT"


def test_the_real_captured_page_says_the_same():
    login_mode, target_mode = automation.read_login_mode(_read(LIVE))
    assert (login_mode, target_mode) == ("ID", "CT")


def test_id_session_is_recognised_as_not_enough():
    d = FakeDriver(_read(FIXTURE))
    assert automation.page_says_cert_required(d) is True
    assert automation.login_grade(d) == "id"


def test_contents_is_detected_as_empty():
    assert automation.contents_is_empty(_read(FIXTURE)) is True


def test_cert_session_would_pass():
    src = _read(FIXTURE).replace('var loginMode = "ID"', 'var loginMode = "CT"')
    src = src.replace("공동인증서 로그인이 필요합니다", "예약 화면")
    d = FakeDriver(src)
    assert automation.page_says_cert_required(d) is False
    assert automation.login_grade(d) == "cert"


def test_session_message_is_read_from_the_real_login_failure():
    msg = automation.read_session_message(
        _read(os.path.join(ROOT, "docs", "site-map", "04-login-id-fail.html")))
    assert msg == "아이디 또는 패스워드가 일치하지 않습니다."


def test_result_prefers_the_server_message():
    src = ('<!-- 세션 메세지 체크 -->\n<script>\nicmsLayerPopup.alert({\n'
           '\tcontents : "신청이 완료되었습니다."\n});\n</script>')
    assert automation.read_result(FakeDriver(src)) == ("ok", "신청이 완료되었습니다.")
    # v1.0.4: 정원 관련 문구는 일반 실패가 아니라 'full' 로 따로 분류한다.
    # 재시도해서는 안 되는 결과이기 때문이다(booking.classify).
    src2 = src.replace("신청이 완료되었습니다.", "정원이 마감되었습니다.")
    status, msg = automation.read_result(FakeDriver(src2))
    assert status == "full" and msg == "정원이 마감되었습니다."


def test_no_message_and_no_keyword_is_unknown():
    assert automation.read_result(FakeDriver("<html><body>아무것도</body></html>")) == \
        ("unknown", "")
