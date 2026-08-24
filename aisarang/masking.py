# -*- coding: utf-8 -*-
"""개인정보 마스킹.

진단 업로드에 들어가는 모든 문자열은 예외 없이 이 모듈을 통과한다.
텍스트 요약, 로그, 페이지 HTML, 요청/응답 본문, 쿠키, 스토리지 전부 해당한다.
한 군데만 적용하고 끝내면 다른 경로로 원문이 새기 때문에 mask() 는
zip 에 넣기 직전 단일 지점(diagnostics.add_text)에서 강제된다.

인증서 비밀번호는 마스킹 이전에 애초에 어떤 수집 경로에도 들어가지 않는다.
그래도 실수로 섞였을 때를 대비해 register_secret() 로 등록된 값은
문자열 치환으로 한 번 더 지운다.
"""
from __future__ import annotations

import re
import threading

_secrets: set[str] = set()
_lock = threading.Lock()

# 주민등록번호 (앞 6자리 - 뒤 7자리)
_RRN = re.compile(r"\b(\d{6})[-\s]?([1-4]\d{6})\b")
# 휴대폰/일반 전화
_PHONE = re.compile(r"\b(01[016789]|0\d{1,2})[-\s.]?(\d{3,4})[-\s.]?(\d{4})\b")
# 카드번호 16자리
_CARD = re.compile(r"\b(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})\b")
# 이메일
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# 흔한 비밀번호/토큰 키=값 형태
_PWKEY = re.compile(
    r"((?:uspass|passwd|password|pwd|certpw|certPassword|aResult|aSignedMsg|aVidMsg|token|authorization)"
    r"\s*[=:\"']{1,3}\s*)([^&\"'<>\s,}]{1,4096})",
    re.IGNORECASE,
)
# 한글 이름이 들어가는 흔한 필드명
_NAMEKEY = re.compile(
    r"((?:mbrnm|mbrNm|usernm|userNm|chldNm|chldnm|name|nm|성명|이름)\s*[=:\"']{1,3}\s*)"
    r"([가-힣]{2,4})",
)
# 홀로 서 있는 한글 이름 태그값 (<td>홍길동</td> 같은 것)
_NAME_TAG = re.compile(r">\s*([가-힣]{2,4})\s*(?=</(?:td|span|strong|b|dd|li|p)>)")

_NAME_WHITELIST = {
    "어린이집", "서울시", "센터", "신청", "예약", "확인", "취소", "저장", "닫기",
    "선택", "완료", "대기", "가능", "불가", "전체", "오전", "오후", "시간제",
    "보육", "통합반", "독립반", "본인", "아동", "정보", "조회", "삭제", "등록",
    "결제", "안내", "목록", "내용", "구분", "지역", "검색", "이용", "운영",
}


def register_secret(value: str) -> None:
    """실행 중 절대 유출되면 안 되는 값(인증서 비밀번호 등)을 등록한다."""
    if not value or len(value) < 3:
        return
    with _lock:
        _secrets.add(value)


def clear_secrets() -> None:
    with _lock:
        _secrets.clear()


def _mask_rrn(m: re.Match) -> str:
    return f"{m.group(1)}-{m.group(2)[0]}******"


def _mask_phone(m: re.Match) -> str:
    return f"{m.group(1)}-****-{m.group(3)[-2:]}**"


def _mask_name(value: str) -> str:
    if len(value) <= 1:
        return value
    return value[0] + "*" * (len(value) - 1)


def mask(text) -> str:
    """어떤 값이든 마스킹된 문자열로 돌려준다. 절대 예외를 던지지 않는다."""
    if text is None:
        return ""
    try:
        if not isinstance(text, str):
            text = str(text)
    except Exception:
        return "<unprintable>"

    try:
        with _lock:
            secrets = list(_secrets)
        for s in secrets:
            if s:
                text = text.replace(s, "***REDACTED***")

        text = _RRN.sub(_mask_rrn, text)
        text = _CARD.sub(lambda m: f"{m.group(1)}-****-****-{m.group(4)}", text)
        text = _PHONE.sub(_mask_phone, text)
        text = _EMAIL.sub(
            lambda m: (m.group(0)[0] + "***@" + m.group(0).split("@", 1)[1]), text
        )
        text = _PWKEY.sub(lambda m: m.group(1) + "***REDACTED***", text)
        text = _NAMEKEY.sub(lambda m: m.group(1) + _mask_name(m.group(2)), text)
        text = _NAME_TAG.sub(
            lambda m: ">" + (m.group(1) if m.group(1) in _NAME_WHITELIST
                             else _mask_name(m.group(1))),
            text,
        )
        return text
    except Exception:
        return "<masking-failed>"
