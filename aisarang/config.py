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
APP_VERSION = "1.0.17"

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
#
# v1.0.12 (2026-09-04): **하한만** 350 → 250ms 로 내렸다. 공식도 여유(250ms)도
# 그대로다. 하한 350 은 시각 오차가 ±435~495ms 이던 시절(Date 헤더의 1초
# 양자화)에 정해진 값이다. v1.0.10 부터 밀리초 서버시각을 쓰고, 고객 PC 실측
# 오차가 ±24~27ms 라 앞쪽 항이 사실상 사라졌다. 고객 로그 원문:
#   09-03  "조준 확정: 도착 목표 정각 +350ms (시각 오차 ±27ms + 여유 250ms)"
#   09-04  "조준 확정: 도착 목표 정각 +350ms (시각 오차 ±24ms + 여유 250ms)"
# 27+250=277, 24+250=274 인데 둘 다 하한에 걸려 350 으로 올라갔다. 즉 지금은
# 하한이 조준점을 혼자 정하고 있었다. 250 으로 내리면 계산값 274~277ms 이
# 그대로 조준점이 된다. 정각 **전** 도착은 서버가 확정 거절하지만(2026-08-27
# 실측), ±24ms 오차에서 274ms 조준의 최악은 정각 +250ms 라 여전히 뒤다.
# 오차가 나쁜 아침에는 uncertainty/2 항이 알아서 조준점을 밀어 올린다
# (±100ms → 350ms, ±200ms → 450ms). 그래서 하한을 내려도 이른 쪽 위험은
# 늘지 않는다. 하한은 측정이 비정상적으로 좋게 나왔을 때의 바닥일 뿐이다.
#
# **이것이 승률을 올린다는 근거는 없다.** 실측 도착 대 결과:
#   -296ms 거절 / +686 패 / +793 승 / +686 패 / +803 패 / +363 승 / +352 패.
# 350~800ms 안에서 도착 시각은 결과를 예측하지 못한다(+352 패, +363 승).
# 안전하고 고객이 두 번 요청했기 때문에 내린 것이지, 이긴다고 보고 내린 것이 아니다.
#
# v1.0.15 (2026-09-17): **여유를 250 → 175ms 로 깎았다.** 한 걸음(75ms)만
# 당긴다. 하한도 같이 175 로 내렸다(하한이 여유보다 크면 하한이 조준점을 혼자
# 정해버린다. v1.0.12 에서 이미 한 번 그랬다). 공식은 그대로다:
#   조준점 = 시각 오차(한쪽) + 여유
#
# 왜 깎았나. 09-17 09:00:00 고객 PC 로그 원문:
#   조준 확정: 도착 목표 정각 +275ms (시각 오차 ±25ms + 여유 250ms)
#   [확인] 1발째 · 도착 추정 정각 +279ms · 서버: 1건 예약 중 1건 예약이
#          선예약으로 인해 예약되지 않았습니다. [taken]
# 그날 고객은 휴대폰 앱으로 **손으로** 우리보다 먼저 넣었다. 자리가 279ms
# 안에 나간다는 뜻이고, 여유 250ms 는 그중 우리가 스스로 붙인 지각이다.
# 같은 조건(±25ms)이면 이제 25 + 175 = 200ms 를 조준한다(275 → 200).
#
# **왜 한 번에 더 안 깎는가.** 이른 쪽은 서버가 확정 거절하고(2026-08-27
# 실측 1/1), 늦는 쪽은 자리를 잃는다. 즉 양쪽 다 비용이 있는 구간이라
# 한 번에 크게 옮기면 무엇이 좋아졌는지/나빠졌는지 알 수 없다. 75ms 씩
# 옮기고 실측 도착값을 보는 것이 이 판의 방식이다. 다음 걸음은 이 상수
# 한 줄만 바꾸면 된다(아래 세 상수가 전부 여기 모여 있는 이유다).
#
# 이 250ms 의 내역(위 v1.0.9 주석)은 세 항이었다. 그중 하나가 실측으로 사라졌다.
#   왕복 흔들림 146.5ms → v1.0.10 부터 밀리초 서버시각을 쓰고, 고객 PC 실측
#                        최소왕복이 50~62ms 다(09-17 로그: 최소왕복 62ms,
#                        편도 추정 31ms). 편도는 이미 one_way 로 따로 빠져
#                        있어서 여유에 또 얹을 이유가 없었다. 이 항을 통째로
#                        빼는 대신 절반만(75ms) 남겨 이번 걸음에 쓴다.
#   발사 경로 지연  50ms → 남긴다. 셀레니움→크롬→네트워크는 여전히 있다.
#   서버 Date 찍기  50ms → 남긴다.
# 즉 175 = 50 + 50 + (왕복 흔들림 146.5 의 절반 75). 반올림한 숫자가 아니다.
#
# 이른 쪽이 위험하다는 사실은 **바뀌지 않았다**(2026-08-27 실측 1/1: 정각
# 296ms 전 도착 → 확정 거절). 그래서 이 판은 여유를 깎는 동시에 이른 쪽의
# 회복을 단단하게 만든다. '예약시간전' 을 맞으면 확인창을 되살려 정각을
# 넘길 때까지 다시 쏜다(REOPEN_EARLY_* 와 handover._Reopen 참고).
# 회복이 있는 방향으로 틀리는 것이 이 판의 요점이다:
#   이르면 → 되살려 다시 쏜다 (자리는 아직 아무도 못 가져갔다. 서버가
#            정각 전 요청을 전부 거절하므로 남도 못 넣는다.)
#   늦으면 → 되살릴 것이 없다. 자리는 이미 나갔다(09-16 / 09-17 실측).
# ±25ms 에서 200ms 조준의 최악(한쪽 오차만큼 이른 쪽)은 정각 +175ms 라
# 여전히 정각 뒤다. 오차가 나쁜 아침에는 앞쪽 항이 알아서 조준점을 밀어
# 올린다(±100ms → 275ms, ±200ms → 375ms, ±435ms → 610ms).
# v1.0.16 (2026-09-18): **여유를 그대로 175ms 로 둔다.** 되돌리려다 멈췄다.
#
# 09-18 09:00:00 로그는 처음에 이렇게 읽혔다:
#   [확인] 1발째 · 도착 추정 정각 +199ms · 서버: 아직 예약 가능한 시간이
#          아닙니다. [too_early]
# 즉 "175 로 깎은 것이 너무 이르러 확정 거절당했다" 로 보였고, 250 으로
# 되돌릴 계획이었다. **그 판정이 틀렸다.** 같은 날 진단 ZIP 을 열어보니
# 그 발사는 예약을 **성공시켰다**:
#   - 우리 클릭(__aisarang_fired_at) 과 같은 ms 에 대기열 표(opcode=5101)
#   - 695ms 뒤 opcode=5004 = NetFunnel_Complete(). 사이트는 이것을 ajax
#     success 콜백 **안에서** 부른다
#   - 곧바로 `/?menuno=245` 이동. 실물 스크립트는 `returnval == "success"`
#     일 때만 이동한다
#   - 신청현황에 새 줄: `2026-10-02 09:00~17:00 ... 상태: 예약`
#     (data-ocseq=5733117). 08:45 의 중복확인은 `{"returnValue":"N"}` 이라
#     그 줄은 그날 우리가 만든 것이다
# `too_early` 는 고객이 08:46 에 손으로 한 번 눌러 받은 14분 묵은 알림이고,
# `display:none` 껍데기 안에 남아 있던 것을 우리 판정기가 읽은 것이다.
#
# 그러므로 **+199ms 는 이긴 조준이다.** 되돌리면 이긴 값을 버린다.
# 실측 도착 대 결과에 이 한 줄이 추가된다:
#   -296 거절 / +686 패 / +793 승 / +686 패 / +803 패 / +363 승 / +352 패 /
#   +279 패(09-17, 고객이 손으로 먼저) / **+199 승 (09-18)**
# 지금까지 관측된 승리 중 가장 이른 도착이다. 다음 걸음(더 깎기)은 이 판의
# 판정 고침이 실전 한 번을 더 통과한 뒤에 본다. 하한도 175 로 유지한다.
#
# v1.0.17 (2026-09-22): **여유 175 → 140ms.** v1.0.16 이 기다리라고 한
# "실전 한 번 더" 가 통과했다. 09-22 09:00:00 실전 로그:
#   조준 확정: 도착 목표 정각 +203ms (시각 오차 ±28ms + 여유 175ms)
# 판정기(InsertOcreqst / menuno=245 응답 본문 읽기)도 이 판에서 그대로
# 맞게 돌았다. 즉 09-18 의 +199 승리가 우연이 아니었고, 고친 판정이
# 실전을 한 번 더 통과했다. 고객이 직접 "조금만 더 앞으로" 를 요청했다.
#
# 140 의 산수(175 와 같은 방식, 왕복 흔들림 항만 더 깎는다):
#   발사 경로 지연   50ms → 남긴다 (셀레니움→크롬→네트워크).
#   서버 Date 찍기   50ms → 남긴다.
#   왕복 흔들림      40ms → v1.0.15 는 146.5 의 절반인 75 를 얹었다. 그
#                          146.5 는 초 단위 서버시각을 쓰던 v1.0.9 까지의
#                          숫자다. v1.0.10 부터 밀리초 서버시각을 쓰고
#                          고객 PC 실측 최소왕복은 50~62ms(편도 ~31ms)이며,
#                          편도는 이미 one_way 로 따로 빠져 있다. 게다가
#                          측정 오차 자체는 앞의 uncertainty/2 항이 매
#                          아침 따로 실어 준다. 여기 남길 몫은 그 절반의
#                          절반이면 충분하다: 75 → 40.
# 즉 140 = 50 + 50 + 40. 이것도 반올림한 숫자가 아니다.
#
# ±28ms 아침이면 조준은 14 + 140 = 정각 +154ms... 가 아니라 +168ms 다
# (uncertainty/2 = 28, 로그의 ±28 은 uncertainty*500 = 반폭 표기라서
# uncertainty=0.056s → half=28ms). 실전 기준 203 → 168ms.
# 이른 쪽 최악(오차가 통째로 이른 쪽으로 몰릴 때)은 +140ms 로 여전히
# 정각 뒤다. 그리고 이르러도 회복이 있다: 서버는 정각 전 요청을 전부
# 거절하므로(2026-08-27 실측) '예약시간전' 은 자리가 아직 아무에게도
# 안 갔다는 뜻이고, REOPEN_EARLY_* 가 확인창을 되살려 다시 쏜다.
# 늦는 쪽에는 회복이 없다(09-16 / 09-17 실측). 이 판도 회복이 있는
# 방향으로 틀리게 두는 것은 같다.
#
# **하한도 같이 140 으로 내린다.** 하한이 여유보다 크면 하한이 조준점을
# 혼자 정해 버려서 여유를 깎은 것이 아무 일도 안 한다. v1.0.12 에서 이미
# 한 번 그랬다. 상수 둘은 항상 같이 움직인다.
ARRIVAL_MIN_AFTER_MS = 140.0
ARRIVAL_MAX_AFTER_MS = 1200.0
ARRIVAL_SAFETY_MS = 140.0

# '예약시간전' 회복 창(초). 정각 이후 이 시간 안에는 확인창 되살리기를
# 넉넉하게 허용한다. 근거: 서버는 자기 시계로 정각 전에 닿은 요청을 **전부**
# 거절하므로(2026-08-27 실측), 이 구간의 '예약시간전' 은 "자리는 아직 아무도
# 가져가지 못했고 우리가 이르기만 했다" 는 뜻이다. 그러니 이때는 두들기는
# 것이 맞다. 여유를 깎은 만큼 이 회복이 안전망이 된다.
REOPEN_EARLY_SECONDS = 2.0
# 그 창 안에서의 되살리기 상한. 되살리기 한 번은 [예약하기] 재클릭 =
# 넷퍼널 대기열 진입이라 무한히 허용하지 않는다. 한 번의 회복 주기는
# 실측 400~800ms(발사 → 응답 → 알림 닫기 → 재클릭 → 확인창)라
# 2초에 6번이면 창을 다 쓴다. 대기열이 한 번이라도 보이면 이 상한과
# 무관하게 영구히 잠긴다(handover._Reopen.lock).
REOPEN_EARLY_MAX = 6

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
    # 0 이면 자동: 그때그때 측정된 시각 오차 + ARRIVAL_SAFETY_MS.
    # 근거와 산수는 위 ARRIVAL_* 상수 주석에 있다.
    "arrival_after_ms": 0,
    "retry_seconds": 20,         # 정각 이후 [확인] 재시도 지속 시간
    "confirm_retry_ms": 90,      # '예약시간전' 일 때 재발사 간격
    "dry_run": False,            # True 면 [확인] 직전에서 멈춘다
    "keep_browser_open": True,
}

# 옛 설정 파일의 죽은 키. **매핑하지 않는다.** v1.0.8 까지의
# arrival_lead_ms(=정각 300ms 전 도착)는 2026-08-27 실전에서 확정 실패였고,
# 고객 PC 의 settings.json 에 그 값이 그대로 남아 있다. 이름을 바꿔 두면
# load_settings 가 모르는 키로 흘려버리므로 옛 값이 되살아나지 않는다.
#
# v1.0.15 에서 셋이 더 죽었다: arrival_safety_ms / reopen_max / reopen_seconds.
# **이것이 이 판에서 제일 조용한 함정이었다.** 세 값은 고객이 화면에서 바꾼
# 적이 한 번도 없다(gui._collect 는 이 키들을 건드리지 않는다). 그런데
# save_settings 가 DEFAULT_SETTINGS 의 모든 키를 파일에 쓰기 때문에, 고객
# PC 의 settings.json 에는 v1.0.14 시절의 값이 그대로 박혀 있다:
#   arrival_safety_ms: 250, reopen_max: 2, reopen_seconds: 15
# 그리고 runner 는 settings.get("arrival_safety_ms", 상수) 로 읽는다. 즉
# 상수만 175 로 내리면 고객 PC 에서는 파일의 250 이 이겨서 **조준이 하나도
# 바뀌지 않는다.** 실제로 확인했다(파일 250 + 새 상수 175 → 조준 275ms).
# 이 세 값은 고객 설정이 아니라 우리가 실측으로 정하는 공학 상수다. 그래서
# 파일에 쓰지도 않고(DEFAULT_SETTINGS 에서 빠졌다), 읽지도 않는다(여기 등록).
# 읽는 쪽은 전부 위 상수로 폴백한다. 앞으로 조준을 옮길 때는 상수 한 줄만
# 바꾸면 고객 PC 에 그대로 도달한다.
_OBSOLETE = ("prefire_ms", "arrival_lead_ms",
             "arrival_safety_ms", "reopen_max", "reopen_seconds")


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
    stale = []
    try:
        p = settings_path()
        if p.exists():
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k in _OBSOLETE:
                        stale.append(k)
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
    # v1.0.17: 죽은 키가 파일에 남아 있으면 **그 자리에서 파일을 다시 쓴다.**
    # 읽는 쪽은 이미 위에서 건너뛰므로 동작에는 영향이 없지만, 고객 PC 의
    # settings.json 에 arrival_safety_ms: 250 / 175 같은 옛 값이 계속 박혀
    # 있으면 다음 사람이 파일만 보고 "조준이 175 로 돌고 있다" 고 잘못 읽는다.
    # 실제로 09-17 에 그렇게 한 번 헤맸다. 한 번 지우면 끝이다.
    # 지우는 것은 우리가 만든 죽은 키뿐이고, 고객이 화면에서 정한 값은
    # save_settings 가 그대로 다시 쓴다.
    if stale:
        try:
            save_settings(data)
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
