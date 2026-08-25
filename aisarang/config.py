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
APP_VERSION = "1.0.6"

# 서버 시각을 다시 맞추는 주기(초). 고객에게 "5분" 이라고 약속한 값이다.
# 프로그램이 도는 동안 계속(오픈 전 대기 / 준비 240초 / 확인창 홀드) 이 주기로
# 다시 측정한다. 근거와 예외(정각 직전 정지)는 clock.ClockKeeper 머리말 참고.
RESYNC_SECONDS = 300
# 정각 몇 초 전부터 재측정을 멈출지. 발사 순간에는 어떤 것도 끼어들지 않는다.
RESYNC_QUIET_SECONDS = 90
# 대기 중 세션 유지 신호 주기. 재측정과 같은 5분으로 맞춘다(고객 로그에서
# 두 줄이 나란히 보이도록). 세션 수명은 60분 실측이라 5분은 충분히 잦다.
SESSION_TOUCH_SECONDS = RESYNC_SECONDS

# 배포 형식. v1.0.5 부터 폴더(ZIP) 배포다. 한 덩어리 exe(--onefile)는 실행할
# 때마다 자기 자신을 %TEMP% 에 풀어놓는데, 윈도우 디펜더가 그 동작을 오탐해
# 파일을 격리해버린다(고객 PC 실제 사례, 2026-08-25). 폴더 배포는 푸는 동작이
# 없다. 자세한 것은 updater.py 머리말과 NOTES.md 참고.
PACKAGE_KIND = "onedir"

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
    "child_name": "",            # 시간제보육 아동 선택 화면의 아동명 (비우면 첫 번째)
    "class_name": "",            # 반명 (비우면 첫 번째 실제 값)
    "use_hours": 9,              # 이용시간 select 의 값 (1~9시간)
    "time_slots": [],            # 시작 시간대 우선순위. 예: ["09:00", "10:00"]
    "lead_days": OPEN_LEAD_DAYS,
    "target_date": "",           # 비우면 lead_days 로 자동 계산
    # 준비(검색~예약하기)를 정각 몇 초 전에 시작할지. 준비는 여유 있게 끝내고
    # 모달을 열어둔 채 기다린다. 정각에 쏘는 것은 [확인] 하나뿐이다.
    "setup_seconds": 240,
    # [확인] 요청이 서버 09:00:00 보다 몇 ms 먼저 '도착'하게 할지.
    # 조금 이르면 서버가 "예약시간전" 이라고 답하고 자리는 살아 있으므로
    # 곧바로 다시 쏜다. 조금 늦으면 "정원초과" 라 되돌릴 수 없다.
    # 그래서 기본값은 이른 쪽이다.
    "arrival_lead_ms": 300,
    "retry_seconds": 20,         # 정각 이후 [확인] 재시도 지속 시간
    "confirm_retry_ms": 90,      # '예약시간전' 일 때 재발사 간격
    "dry_run": False,            # True 면 [확인] 직전에서 멈춘다
    "keep_browser_open": True,
}

# 옛 설정 파일 호환. v1.0.3 까지는 prefire_ms 였고 의미가 같다.
_RENAMED = {"prefire_ms": "arrival_lead_ms"}


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
                    k = _RENAMED.get(k, k)
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
