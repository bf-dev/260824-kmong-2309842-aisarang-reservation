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
APP_VERSION = "1.0.10"

# 실행 방식.
#   handover  인계 모드 (기본). 사람이 아동~[예약하기] 까지 손으로 끝내 두면
#             프로그램은 예약 확인창의 [확인] 만 정각에 누른다.
#             2026-08-26 고객 요청으로 이것이 기본이 됐다. 그날 09시 직전의
#             가상대기열 때문에 자동 준비가 확인창을 못 열었고, 재준비가
#             고객이 만들어 둔 것을 반복해서 날렸다.
#   auto      자동 모드. 검색부터 [예약하기] 까지 프로그램이 걷는다(옛 기본).
MODE_HANDOVER = "handover"
MODE_AUTO = "auto"
RUN_MODES = (MODE_HANDOVER, MODE_AUTO)
RUN_MODE_LABELS = {
    MODE_HANDOVER: "인계 모드 ([확인] 만 누름)",
    MODE_AUTO: "자동 모드 (처음부터 프로그램이 진행)",
}


def normalize_run_mode(value) -> str:
    """옛 설정 파일과 오타를 흡수한다. 모르는 값은 인계 모드로 본다."""
    v = str(value or "").strip().lower()
    return v if v in RUN_MODES else MODE_HANDOVER

# ------------------------------------------------------------ 서버 시각 측정
# 시각 측정용 프로브 경로. **읽기 전용이어야 하고, 예약 경로면 절대 안 된다.**
# 조건 세 가지를 다 만족하는 것으로 골랐다(2026-09-01 실측, HEAD).
#   1) egovLatestServerTime 쿠키(밀리초 서버시각)를 붙인다 → 1초 양자화가 사라진다
#   2) 왕복이 짧다 → 구간이 좁다.  실측 150ms (`/?menuno=1` 은 980ms)
#   3) 예약 서버와 같은 앱 계층(/icms/occasion/) 이라 같은 시계를 본다
# InsertOcreqst.html 도 같은 성질이지만 **예약 등록 경로라 절대 두들기지 않는다.**
CLOCK_PROBE_PATH = "/icms/occasion/SelectTotalTime.html"
# 한 번 잴 때 쏘는 샘플 수. 왕복이 150ms 라 40발이 약 8초다(옛 12발은 12초였다).
CLOCK_SAMPLES = 40

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

# ------------------------------------------------------------------ 진단 용량
# v1.0.9 는 네트워크 요약을 **마지막 300건**만 남겼다. 2026-09-01 캡처에서
# 09시 한참 전에 발급된 가상대기열 티켓(opcode=5002)이 그 잘림에 통째로
# 날아갔고, 그 결과 "대기열 티켓이 없었다" 는 틀린 결론을 보고했다.
# ZIP 이 94KB 밖에 안 되니 아낄 이유가 없다.
NET_RING_MAX = 12000        # 크롬 CDP 메시지 링버퍼 (was 3000)
NET_DIGEST_LIMIT = 1500     # ZIP 에 남기는 요청/응답 줄 수 (was 300)

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

# --------------------------------------------------------------- 도착 조준 (v1.0.9)
#
# v1.0.8 까지는 [확인] 요청을 **정각보다 300ms 먼저** 도착시키는 것이 목표였다.
# 2026-08-27 09:00:00, 인계 모드의 첫 실전 발사가 그 값 때문에 실패했다.
#
#   [09:00:00] [확인] 1발째 · 도착 추정 정각 -296ms
#              · 서버: 알림 아직 예약 가능한 시간이 아닙니다. 확인 [too_early]
#
# 서버는 자기 시계로 09:00:00.000 **전에** 도착한 요청을 그냥 거절한다.
# 즉 -300ms 조준은 확정 실패였다. 이제는 정각 **뒤**로 조준한다.
#
# 얼마나 뒤로? 반올림한 숫자가 아니라 그날 측정된 값에서 뽑는다.
#   - 서버 시각 오프셋의 잔여 구간 폭 (clock.uncertainty). 2026-08-27 실측
#     4회: 868.1 / 843.0 / 847.3 / 869.2 ms → 절반(= 한쪽 오차) 최대 434.6ms.
#   - 그 위에 얹는 여유(ARRIVAL_SAFETY_MS 기본 250ms) 내역:
#       왕복 흔들림 (994.6ms 최악 - 701.6ms 최소) / 2 = 146.5ms
#       셀레니움→크롬→네트워크 발사 지연            ≈  50ms
#       서버가 요청을 받고 Date 를 찍기까지의 시간   ≈  50ms
#     → 합계 약 250ms
#   2026-08-27 값으로 계산하면 434.6 + 250 = 약 685ms 뒤가 목표가 된다.
#
# 비대칭이 요점이다. 이르면 **확정 거절**(1/1 실측). 늦으면 '정원초과' 위험인데
# 어떤 캡처에서도 한 번도 관측된 적이 없다. 그래서 늦는 쪽으로 틀린다.
# v1.0.10 (2026-09-01): 상수는 **하나도 깎지 않았다.** 대신 앞쪽 항(시각 오차)을
# 실제로 줄였다. eGov 세션 필터가 붙여주는 egovLatestServerTime 쿠키가 밀리초
# 서버시각이라, Date 헤더의 1초 양자화가 통째로 사라진다(clock._parse_server_ms).
# 이 서버에서 실측한 잔여 구간 폭: 869ms → 152ms (한쪽 오차 434ms → 76ms).
# 같은 공식에 넣으면 76 + 250 = 326ms 이고 아래 하한 350ms 로 올라간다.
# 즉 조준점이 685ms → 350ms 로 내려온다. 공식은 그대로다.
ARRIVAL_MIN_AFTER_MS = 350.0
ARRIVAL_MAX_AFTER_MS = 1200.0
ARRIVAL_SAFETY_MS = 250.0

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
    "run_mode": MODE_HANDOVER,   # handover | auto
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
    # [확인] 요청이 서버 09:00:00 **뒤** 몇 ms 에 도착하게 할지.
    # 0 이면 자동: 그때그때 측정된 시각 오차 + arrival_safety_ms.
    # 근거와 산수는 위 ARRIVAL_* 상수 주석에 있다.
    "arrival_after_ms": 0,
    "arrival_safety_ms": int(ARRIVAL_SAFETY_MS),
    "retry_seconds": 20,         # 정각 이후 [확인] 재시도 지속 시간
    "confirm_retry_ms": 90,      # '예약시간전' 일 때 재발사 간격
    # '예약시간전' 을 맞아 확인창이 닫혔을 때만, [예약하기] 를 다시 눌러
    # 확인창을 되살리는 횟수 상한과 벽시계 마감(정각 기준 초).
    # 다른 어떤 결과에서도 다시 누르지 않는다. handover.burst 참고.
    "reopen_max": 2,
    "reopen_seconds": 15,
    "dry_run": False,            # True 면 [확인] 직전에서 멈춘다
    "keep_browser_open": True,
}

# 옛 설정 파일의 죽은 키. **매핑하지 않는다.** v1.0.8 까지의
# arrival_lead_ms(=정각 300ms 전 도착)는 2026-08-27 실전에서 확정 실패였고,
# 고객 PC 의 settings.json 에 그 값이 그대로 남아 있다. 이름을 바꿔 두면
# load_settings 가 모르는 키로 흘려버리므로 옛 값이 되살아나지 않는다.
_OBSOLETE = ("prefire_ms", "arrival_lead_ms")


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
                    if k in _OBSOLETE:
                        continue
                    if k in data:
                        data[k] = v
                if not isinstance(data.get("center"), dict) or not data["center"].get("stcode"):
                    data["center"] = dict(DEFAULT_CENTER)
    except Exception:
        pass
    try:
        data["run_mode"] = normalize_run_mode(data.get("run_mode"))
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
