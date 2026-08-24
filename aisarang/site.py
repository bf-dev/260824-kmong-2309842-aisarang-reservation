# -*- coding: utf-8 -*-
"""아이사랑(childcare.go.kr) 공개 조회 엔드포인트.

여기 있는 것은 전부 로그인 없이 열리는 조회 API 다. 실제 사이트의
프론트엔드 번들에서 그대로 읽어온 파라미터 목록이라 필드가 모자라거나
남지 않는다. (근거: /?menuno=242 의 #pagingForm 과 인라인 스크립트)

  POST /icms/nursery/NurseryMapSidoList.html                 -> 시/도 목록
  POST /icms/nursery/NurseryMapGuGunList.html  sido=11000    -> 시/군/구 목록
  POST /icms/nursery/TmpCareSlLAjax.html                     -> 시간제보육 기관 목록
       unityYn pageNum ctprvn ctprvnName signgu signguName dong callType crname
  POST /icms/nursery/TmpCareOperView.html      stcode        -> 운영사항

예약 자체(?menuno=605)는 공동인증서 세션이 있어야 화면이 그려지므로
여기가 아니라 automation.py 에서 실제 브라우저로 처리한다.
"""
from __future__ import annotations

import html
import re

from . import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def make_session(proxy: str | None = None):
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": config.BASE_URL + config.SEARCH_PAGE,
    })
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def _post(session, path: str, data: dict | None = None, timeout: int = 20,
          diag=None):
    url = config.BASE_URL + path
    r = session.post(url, data=data or {}, timeout=timeout)
    if diag is not None:
        try:
            diag.add_response("POST", url, r.status_code, r.text[:200_000])
        except Exception:
            pass
    return r


def list_sido(session, diag=None) -> list[dict]:
    """시/도 목록. [{'code': '11000', 'name': '서울특별시'}, ...]"""
    r = _post(session, config.SIDO_AJAX, diag=diag)
    out = []
    try:
        for row in r.json().get("sidoList", []):
            out.append({"code": row.get("ARCODE", ""), "name": row.get("ARNAME", "")})
    except Exception:
        pass
    return out


def list_gugun(session, sido_code: str, diag=None) -> list[dict]:
    """시/군/구 목록. 이름은 '서울특별시 서초구' 형태로 내려온다."""
    r = _post(session, config.GUGUN_AJAX, {"sido": sido_code}, diag=diag)
    out = []
    try:
        data = r.json()
        rows = data.get("gugunList") or data.get("guGunList") or []
        for row in rows:
            code = row.get("ARCODE", "")
            name = row.get("ARNAME", "")
            if not code.startswith(sido_code[:2]):
                continue
            short = name.split(" ", 1)[1] if " " in name else name
            out.append({"code": code, "name": short, "fullName": name})
    except Exception:
        pass
    return out


# 결과 목록은 <li class="preschool"> 블록의 반복이다. 블록 단위로 먼저 자른
# 뒤에 안에서 필드를 뽑는다. 정규식 하나로 li 끝을 lookahead 하려 하면 안쪽의
# <ul class="result_info"> 가 닫히는 </ul> 에 먼저 걸려 이용대상/운영정보가
# 통째로 잘려 나간다(실제로 그렇게 잘렸었다).
_CENTER_BLOCK = re.compile(r'<li class="preschool">', re.S)
_TITLE = re.compile(r'id="infoMove"[^>]*data-val="(?P<code>\d+)"[^>]*>(?P<name>[^<]+)</a>', re.S)
_ADDR = re.compile(r"<address>(.*?)</address>", re.S)
_TEL = re.compile(r"연락처\s*:\s*([0-9\-]+)")
_STATUS = re.compile(r"예약\s*:\s*(.*?)</li>", re.S)
_TARGET = re.compile(r"<dt>이용대상</dt>\s*<dd>(.*?)</dd>", re.S)


def _text(fragment: str) -> str:
    t = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def search_centers(session, ctprvn: str, ctprvn_name: str, signgu: str,
                   signgu_name: str, unity_yn: str = "N", crname: str = "",
                   page: int = 1, diag=None) -> list[dict]:
    """시간제보육 기관 검색. unity_yn: 'N'=독립반, 'Y'=통합반."""
    data = {
        "unityYn": unity_yn,
        "pageNum": str(page),
        "ctprvn": ctprvn,
        "ctprvnName": ctprvn_name,
        "signgu": signgu,
        "signguName": signgu_name,
        "dong": "",
        "callType": "road",
        "crname": crname,
    }
    r = _post(session, config.SEARCH_AJAX, data, timeout=30, diag=diag)
    body = r.text
    if diag is not None:
        try:
            diag.add_page(f"centers_{signgu}_{unity_yn}", config.BASE_URL + config.SEARCH_AJAX, body)
        except Exception:
            pass

    return parse_center_list(body, unity_yn, ctprvn, ctprvn_name, signgu, signgu_name)


def parse_center_list(body: str, unity_yn: str, ctprvn: str = "", ctprvn_name: str = "",
                      signgu: str = "", signgu_name: str = "") -> list[dict]:
    """TmpCareSlLAjax 응답 조각을 센터 목록으로 바꾼다."""
    out: list[dict] = []
    seen: set[str] = set()
    blocks = _CENTER_BLOCK.split(body)[1:]
    for block in blocks:
        t = _TITLE.search(block)
        if not t:
            continue
        code = t.group("code")
        name = html.unescape(t.group("name")).strip()
        if code in seen:
            continue
        seen.add(code)
        rest = block
        addr = _text(_ADDR.search(rest).group(1)) if _ADDR.search(rest) else ""
        tel = _TEL.search(rest).group(1) if _TEL.search(rest) else ""
        status = _text(_STATUS.search(rest).group(1)) if _STATUS.search(rest) else ""
        target = _text(_TARGET.search(rest).group(1)) if _TARGET.search(rest) else ""
        out.append({
            "stcode": code,
            "name": name,
            "address": addr,
            "tel": tel,
            "status": status,
            "target": target,
            "unityYn": unity_yn,
            "ctprvn": ctprvn,
            "ctprvnName": ctprvn_name,
            "signgu": signgu,
            "signguName": signgu_name,
        })
    return out


def search_centers_both(session, ctprvn: str, ctprvn_name: str, signgu: str,
                        signgu_name: str, crname: str = "", diag=None) -> list[dict]:
    """독립반 + 통합반을 한 번에. 화면에서는 구분해서 보여준다."""
    rows: list[dict] = []
    for unity in ("N", "Y"):
        try:
            rows.extend(search_centers(session, ctprvn, ctprvn_name, signgu,
                                       signgu_name, unity, crname, diag=diag))
        except Exception:
            continue
    return rows


def operation_info(session, stcode: str, diag=None) -> str:
    """센터 운영사항(운영 요일/시간) 텍스트."""
    try:
        r = _post(session, config.OPER_AJAX, {"stcode": stcode}, diag=diag)
        return _text(r.text)
    except Exception:
        return ""
