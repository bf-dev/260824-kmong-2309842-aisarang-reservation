# -*- coding: utf-8 -*-
"""설정값과 사용자 설정 파일 (Kmong 고객 2309842 / 주문 7566483).

고객이 손으로 고쳐야 하는 설정 파일은 없다. 이 파일의 DEFAULT_SETTINGS 는
첫 실행 때 쓰이는 초기값일 뿐이고, 그 뒤로는 전부 프로그램 화면에서 바꾼다.
바뀐 값은 %APPDATA%/AisarangReservation/settings.json 에 저장된다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "아이사랑 시간제보육 예약"
APP_SLUG = "aisarang-reservation"
APP_VERSION = "1.0.1"

# Kmong 고객 식별자. 로그/진단/업로드 경로 전부에 이 값이 찍힌다.
CUSTOMER_ID = "2309842"
ORDER_ID = "7566483"

# 진단 업로드 (사내 표준 Artifacts API)
WORKS_API = "https://works.insu.ng/works/api"
ARTIFACT_SOURCE = f"{APP_SLUG}-diag"

# 자동 업데이트
STATIC_BASE = f"https://works.insu.ng/works/public/{CUSTOMER_ID}"
VERSION_URL = f"{STATIC_BASE}/version-aisarang.json"

# 대상 사이트.
# AISARANG_BASE_URL 은 우리 CI 전용이다(녹화된 응답을 되먹이는 로컬 서버).
# 고객 실행 경로에서는 절대 설정되지 않는다.
BASE_URL = os.environ.get("AISARANG_BASE_URL") or "https://www.childcare.go.kr"
LOGIN_PAGE_ID = "/?menuno=506&ltype=id"          # 아이디 로그인 탭
LOGIN_PAGE_CERT = "/?menuno=506&ltype=cert"      # 공동/금융인증서 로그인 탭
LOGIN_POST = "/icms/login/login.html"
SEARCH_PAGE = "/?menuno=242"                     # 시간제보육 기관찾기
SEARCH_AJAX = "/icms/nursery/TmpCareSlLAjax.html"
SIDO_AJAX = "/icms/nursery/NurseryMapSidoList.html"
GUGUN_AJAX = "/icms/nursery/NurseryMapGuGunList.html"
OPER_AJAX = "/icms/nursery/TmpCareOperView.html"
RESERVE_PAGE = "/?menuno=605"                    # 시간제보육 입소신청 (인증서 세션 필요)
STATUS_PAGE = "/?menuno=245"                     # 시간제보육 신청현황

# 시간제보육은 "이용일 14일 전 09:00" 에 열린다.
# 근거: childcare.go.kr ?menuno=242 페이지 내 공지 -
#   "(변경) 이용일 14일 전 09:00 부터 예약 가능"
OPEN_HOUR = 9
OPEN_MINUTE = 0
OPEN_LEAD_DAYS = 14

KST_OFFSET_SECONDS = 9 * 3600

# 고객이 알려준 기본 센터 (2026-08-24, 고객 원문: "서초구 신반포 센터 기본값으로")
# stcode 는 실제 사이트 검색 결과에서 확인한 값이다.
DEFAULT_CENTER = {
    "stcode": "11650000416",
    "name": "서초구육아종합지원센터(신반포)",
    "unityYn": "N",
    "ctprvn": "11000",
    "ctprvnName": "서울특별시",
    "signgu": "11650",
    "signguName": "서초구",
}

DEFAULT_SETTINGS = {
    "center": dict(DEFAULT_CENTER),
    "login_mode": "manual",      # manual | cert
    "mbrid": "",
    "time_slots": [],            # 예: ["09:00", "10:00"]
    "lead_days": OPEN_LEAD_DAYS,
    "target_date": "",           # 비우면 lead_days 로 자동 계산
    "prefire_ms": 300,           # 서버시간 09:00:00 기준 몇 ms 앞서 쏠지
    "retry_seconds": 20,         # 정각 이후 재시도 지속 시간
    "retry_interval_ms": 400,
    "dry_run": False,            # True 면 마지막 신청 버튼 직전에서 멈춤
    "keep_browser_open": True,
}


def _appdata_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "AisarangReservation"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        d = Path(os.path.expanduser("~"))
    return d


def settings_path() -> Path:
    return _appdata_dir() / "settings.json"


def log_dir() -> Path:
    d = _appdata_dir() / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def profile_dir() -> Path:
    """셀레니움 크롬 프로필. 로그인 세션이 여기 남아 다음 실행에서 재사용된다."""
    d = _appdata_dir() / "chrome-profile"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    data["center"] = dict(DEFAULT_CENTER)
    try:
        p = settings_path()
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k in data:
                        data[k] = v
                if not isinstance(data.get("center"), dict) or not data["center"].get("stcode"):
                    data["center"] = dict(DEFAULT_CENTER)
    except Exception:
        pass
    return data


def save_settings(data: dict) -> bool:
    try:
        payload = {k: data.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS}
        settings_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
