# 260824-kmong-2309842-aisarang-reservation

아이사랑(childcare.go.kr) **시간제보육** 예약을 매일 오전 9시 오픈 순간에 넣는
Windows 프로그램. Kmong 고객 2309842 (거대한고봉밥), 주문 7566483, 150,000원.

- Neoworks customerId: `05788f12-b025-48ba-bb01-7c45121013d8`
- Artifacts / 정적호스팅 키: `2309842` (Kmong partnerId)
- 저장소: https://github.com/bf-dev/260824-kmong-2309842-aisarang-reservation (**public**, Actions 무료분 때문)

## 실행 / 빌드

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/ -q        # 44 passed
python3 main.py                              # GUI (고객이 쓰는 화면)
python3 main.py --selftest                   # 실서버 조회 + 서버시각 동기화 점검
python3 main.py --guidemo --hold=60000       # CI 스크린샷용 데모 (실제 조회 수행)
```

빌드는 GitHub Actions `windows-latest` (`.github/workflows/build.yml`).
`winbuild`(windows-builder VM)는 이 작업 시점에 **ssh unreachable** 이라 못 썼다
(`winbuild status` 는 azure running / tailscale active 인데 ssh 만 죽어 있었다).
Actions 는 public repo 라 무료분으로 돌아간다. private 로 바꾸면 계정 전체
spending limit 때문에 즉시 막힌다.

배포:
```bash
~/workspace/scripts/works-publish 2309842 out/aisarang-reservation-<ver>.exe
# 그리고 version-aisarang.json 의 exeUrl 을 새 파일로 갱신
```

## 사이트 구조 (실측, 2026-08-24)

전부 KR 프록시 + 직접 접속 양쪽으로 확인했다. **이 사이트는 해외 IP를 막지 않는다**
(이 서버에서 직접 200 이 온다). 그래서 CI 에서도 진짜 조회가 돌아간다.

### 공개 (로그인 불필요) — `site.py` 가 쓰는 것
| 용도 | 엔드포인트 | 파라미터 |
|---|---|---|
| 시/도 목록 | `POST /icms/nursery/NurseryMapSidoList.html` | 없음 → `{ARCODE, ARNAME}` |
| 시/군/구 | `POST /icms/nursery/NurseryMapGuGunList.html` | `sido=11000` |
| 기관 검색 | `POST /icms/nursery/TmpCareSlLAjax.html` | `unityYn pageNum ctprvn ctprvnName signgu signguName dong callType=road crname` |
| 운영사항 | `POST /icms/nursery/TmpCareOperView.html` | `stcode` |

파라미터 목록은 `/?menuno=242` 의 `#pagingForm` 에서 그대로 가져온 것이다.
하나라도 빠지면 엉뚱한 결과가 나온다.

### 로그인
| 방식 | 폼 | 필드 |
|---|---|---|
| 아이디 | `frmLoginId` → `POST /icms/login/login.html` | `mbrid uspass ltype=id flag=PISl loginPageType=01 kybrdscrtyyn=N returnUrl ssoReturnMenuno issacweb_data` |
| 공동인증서 | `frmLoginCert` → 같은 URL | `aResult`(AnySign 서명값) `certType=C` `flag=PCSl` `kybrdscrtyyn=N` |

`kybrdscrtyyn=N` 이라 키보드보안(nppfs)은 강제가 아니다.

### 핵심: 왜 브라우저 자동화인가
1. **예약 화면 `?menuno=605` (시간제보육 입소신청) 은 공동인증서 세션에만 그려진다.**
   비로그인으로 `stcode/unityYn/unityynall` 을 POST 하면 55KB 응답 중 본문은 빈 껍데기다.
   목록 화면의 `gotoOccasionRes()` 안에 서버가 상황에 따라 내보내는 분기가 그대로 있다:
   `icmsLayerPopup.alert({contents:"공동인증서 로그인이 필요합니다."})`.
   **고객이 화면에서 본 그 문구가 여기서 나온다.** 고객 보고가 정확했다.
2. 공동인증서 로그인은 **AnySign4PC (한컴위드)** 로컬 모듈이 처리한다.
   `/icms/AnySign/anySign4PCInterface.js` → `fnXecureLogin()` (in `xecureCommon.js`)
   → `AnySign.SignDataWithVID(...)` → 콜백이 폼의 `aResult` 를 채우고 submit.
   이 모듈은 **고객 PC 에 설치되어 도는 프로그램**이라 서버에서 재현 불가.
   인증서/비밀번호가 PC를 안 떠나는 것도 이 구조 덕분이다.
   `CertShare`, `Hancom Secure Root Authority` 설치가 전제 (사이트 FAQ 에 명시).
3. 모바일 앱 경로는 막혔다: `m.childcare.go.kr` 은 모든 경로가 302 → 403,
   `api.childcare.go.kr` 은 "Megaware Runtime" 껍데기만 응답. 앱 API 는 공개돼 있지 않다.
   그리고 사이트 FAQ 가 "아이사랑 앱에 있던 공동인증서" 를 언급한다 = **앱도 인증서를 쓴다.**
   고객이 말한 "앱은 아이디 로그인" 은 앱 진입 로그인이고, 거래는 인증서다.

### 09:00 규칙 (사이트 공지 원문)
`/?menuno=242` 인라인 스크립트에 남아 있는 공지:
> (기존) 이용일 14일 전 00:00 부터 예약 가능
> **(변경) 이용일 14일 전 09:00 부터 예약 가능**  ※ 2025.9.1. 예약 건부터 적용

고객이 말한 "오늘 오전 9시에 2주후 오늘 예약이 열립니다" 와 정확히 일치.

### 방해 요소
- `disable-devtool.0.3.7.min.js` — **개발자도구를 열면 `/logout` 으로 강제 로그아웃**된다.
  자동화 중 devtools 를 절대 열지 말 것. Selenium 자체는 문제없다.
- `netfunnel-pcms.js` (넷퍼널 가상대기열) 이 배포돼 있다. 목록 화면에서는 주석 처리돼
  있지만 9시 몰릴 때 서버가 켤 수 있다. `automation.handle_netfunnel()` 이 대기 처리.

## 실사이트 단계별 검증 맵 (2026-08-24, 전부 KR 프록시 egress 115.68.232.141 경유)

증거 파일은 `docs/site-map/` 에 그대로 저장돼 있다. **추정으로 채운 칸은 없다.
못 본 것은 못 봤다고 적는다.**

### 1단계 — 시간제보육 진입과 로그인 게이트  ✅ 확인함
- 진입: `GET /?menuno=242` → HTTP 200, 69,654B (`01-entry-242.html`)
  화면: 구분(독립반/통합반) · 지역 선택 · 검색어 · 조회 (스크린샷으로도 확인)
- 목록 조각: `POST /icms/nursery/TmpCareSlLAjax.html` → 200, 21,319B
  (`03-centers-seocho-N.html`). 각 센터에 `시간제보육 예약` 버튼이 붙어 있고
  `data-stcode` / `data-unityyn` 를 들고 `gotoOccasionRes()` 를 부른다.
- **게이트 원문** (`03-centers-seocho-N.html` 의 `gotoOccasionRes` 안, 서버가
  상황에 따라 주석을 풀어 내보내는 분기):
  ```js
  icmsLayerPopup.alert({ contents : "공동인증서 로그인이 필요합니다." });
  return ;
  ```
  **고객이 화면에서 본 문구가 정확히 이것이다. 고객 보고가 맞았다.**
- 인증서 로그인 화면: `GET /?menuno=506&ltype=cert` → 200, 89,776B (`02-login-cert.html`)
  탭 3개: `gotoLogin('simple')` 간편인증 / `gotoLogin('cert')` 인증서 / `gotoLogin('id')` 아이디
  ```html
  <form name="frmLoginCert" action="/icms/login/login.html" method="post">
    <input name="returnUrl"> <input name="loginPageType" value="01">
    <input name="aResult">              <!-- 공동인증서 서명 결과 -->
    <input name="kybrdscrtyyn" value="N"> <input name="certType" value="C">
    <input name="flag" id="flag" value="PCSl">   <!-- 어린이집이면 NCSl -->
    <input name="ssoReturnMenuno" value="1">
  <button onclick="fnXecureLogin();">공동/금융인증서 로그인</button>
  ```
- `fnXecureLogin()` 실체 (`02-xecureCommon.js`):
  ```js
  AnySign.SignDataWithVID(AnySign.mXgateAddress, AnySign.mCAList, "isarang",
                          '16','isarang','10','', AnySign.mLimitedTrial,
                          SignDataCMS_callback);
  ```
  → **AnySign4PC(한컴위드) 로컬 모듈**이 인증서 목록/비밀번호 UI를 띄우고 서명해
  `aResult` 를 채운 뒤 폼을 submit 한다. 서버에서 재현 불가능하고, 그래서
  인증서와 비밀번호가 고객 PC 를 떠나지 않는다.
- 아이디 로그인도 웹에 존재한다(`02-login-id.html`, `frmLoginId` →
  `mbrid/uspass/ltype=id/flag=PISl/kybrdscrtyyn=N`). 하지만 아이디 로그인만으로는
  아래 4·5단계가 열리지 않는다(그래서 고객이 인증서 안내를 받은 것).
- **자격증명은 일절 시도하지 않았다.** 로그인 POST 는 한 번도 보내지 않았다.

### 2단계 — 로그인 후 세션 상태  ❌ **도달 못 함**
실제 공동인증서와 고객 계정이 있어야만 만들어지는 상태다. 우리가 확인한 것은
경계뿐이다: 비로그인 세션에서 `icms/usr/MemberCertRegCheckAjax.html` 은 error
페이지를 돌려준다(`menuno=242` 로 POST, 자격증명 없이).
**없는 것: 실제 공동인증서 + 그 인증서가 등록된 고객 계정.**

### 3단계 — 지역/센터 목록과 서초구 신반포의 실제 코드  ✅ 확인함
- `POST /icms/nursery/NurseryMapSidoList.html` → 200, 787B (`03-sido.json`)
  → `{"ARCODE":"11000","ARNAME":"서울특별시"}` 외 16개
- `POST /icms/nursery/NurseryMapGuGunList.html` body `sido=11000` → 200, 22,381B
  (`03-gugun-seoul.json`) → 서울 25개 구, `{"ARCODE":"11650","ARNAME":"서울특별시 서초구"}`
- `POST /icms/nursery/TmpCareSlLAjax.html` 전체 파라미터(사이트 `#pagingForm` 그대로):
  `unityYn pageNum ctprvn ctprvnName signgu signguName dong callType=road crname`
- 서초구 결과: 독립반 9곳 + 통합반 1곳. **기본 센터는 여기서 나왔다**:
  ```
  stcode 11650000416  서초구육아종합지원센터(신반포)  unityYn=N
  서울특별시 서초구 신반포로19길 26 / 02-596-9340 / 6개월~36개월 미만 / 예약가능
  ```
  (`03-centers-seocho-N.html` 8번째 항목. 고객이 말한 "서초구 신반포 센터"와 일치)

### 4단계 — 2주 뒤 오픈분의 날짜/시간대 화면  ❌ **도달 못 함**
`POST /?menuno=605` (body `stcode=11650000416&unityYn=N&unityynall=`) 는
비로그인에서도 HTTP 200 을 주지만 **내용이 없다** (`05-reserve-605-anon.html`):

| 측정 | 값 |
|---|---|
| `#contents` 블록 | 3,861 B |
| `#contents` 보이는 텍스트 | **70자** (팝업 "닫기/확인/취소" 뿐) |
| `<form>` 개수 | **0** |
| `<input>` 개수 | **0** |
| 달력/datepicker 위젯 | **0** |
| 신청·예약 버튼 | **0** |

`?menuno=245`(신청현황), `?menuno=617`(아동등록)도 **완전히 동일한 3,861B / 70자 /
form 0개** 껍데기를 준다. 즉 시간제보육 거래 화면 전체가 하나의 인증 게이트 뒤에 있다.

09:00 규칙 자체는 사이트 공지로 확인됨(아래 참조). **없는 것: 실제 공동인증서.**

### 5단계 — 최종 예약 제출 요청 (URL/메서드/헤더/전체 파라미터)  ❌ **도달 못 함**
프론트엔드 번들에서 뽑아보려 했으나 **그런 번들이 없다.** 확인한 것:
- 비로그인 605 페이지가 부르는 외부 JS 20개는 전부 공용(jquery, AnySign, 레이어팝업 등).
  예약 로직이 든 파일은 없다.
- 공용 번들 `/icms/js/cpcommon.js`(113KB), `common.js`(126KB), `fncommon.js`(23KB)를
  받아 `Occasion|TmpCare|ChildRes|fnRes` 로 훑었다 → **일치 0건**.
- 비로그인 605 의 인라인 스크립트 8개에도 예약 로직 없음(SSO/인증서 체크 보일러플레이트뿐).
- 목록 화면에 주석으로 남은 구경로는 죽어 있다:
  `POST /cpis2gi/occasion/OccasionChildResIs.jsp` → **404 "시스템 점검 중"**
  `POST /cpis2gi/occasion/OccasionChildResPiIs.jsp` → **404**

→ 결론: 예약 폼과 제출 로직은 **정적 파일이 아니라 인증된 세션에만 서버가 찍어주는
인라인 JSP 출력**이다. 인증서 없이는 URL도 파라미터 목록도 알아낼 방법이 없다.
**없는 것: 실제 공동인증서 (+ 그 인증서가 등록된 계정).**

우리가 확실히 아는 5단계의 유일한 부분은 진입 요청이다(실측):
`POST /?menuno=605`, body `stcode`/`unityYn`/`unityynall`, HTTP 200, 51,666B.

### 그래서 코드가 이 공백을 어떻게 다루는가
4·5단계를 추측으로 채우지 않았다. `automation.py` 의 `select_date` /
`select_time_slots` / `find_submit` 은 **여러 후보를 순서대로 시도하는 적응형**이고,
매 시도마다 그 시점의 DOM 을 진단 ZIP 으로 올린다. 그리고 **날짜 선택에 성공하지
못하면 절대 제출하지 않는다**(`attempt_once` 가 `date_not_open` 으로 먼저 빠진다).
즉 실패 모드가 "엉뚱한 날짜를 예약함"이 아니라 "예약이 안 됨"이다.
연습 모드는 마지막 버튼 직전에서 멈추므로 예약을 만들지 않고 DOM 만 받아올 수 있다.

## 서버 시각 동기화 (`clock.py`)

전용 시간 API 가 없어서 `Date:` 응답 헤더를 쓴다. 초 단위라 그대로 쓰면 최대 1초 오차.
**구간 교집합**으로 좁힌다: 샘플마다 `offset ∈ [S - t_mid - rtt/2, S + 1 - t_mid + rtt/2]`
를 얻고 이것들을 교집합한다. 초 경계를 여러 위상에서 훑도록 130ms 간격으로 샘플링.

측정값:
- 이 서버 → KR SOCKS 프록시 경유 (RTT 857ms): 오차 ±484ms
- 이 서버 → 직접 (RTT ~200ms): 오차 ±100ms 수준
- **고객 PC(국내 가정회선, RTT 10~30ms): ±15ms 수준으로 수렴**

즉 정확도는 왕복지연에 지배된다. 그래서 `prefire_ms`(기본 300ms) 로 여유를 준다.
`tests/test_clock.py` 가 진짜 offset 을 아는 가짜 서버로 수렴을 검증한다.

## 기본 센터 (고객 지정)

고객 원문 2026-08-24: "서초구 신반포 센터 기본값으로 넣어주시면 될거같습니다"

```
stcode   11650000416
name     서초구육아종합지원센터(신반포)
unityYn  N (독립반)
지역      서울특별시 11000 / 서초구 11650
주소      서울특별시 서초구 신반포로19길 26   ☎ 02-596-9340
이용대상  6개월~36개월 미만
```
실사이트 검색으로 확인한 값이고 `tests/test_site.py` 가 고정해 둔다.
화면에서 얼마든지 바꿀 수 있다(요구사항대로 저장되는 "기본값"일 뿐).

서초구 전체: 독립반 9곳 + 통합반 1곳(양재복지관어린이집 11650000090).

## Artifacts API

`reporter.py` 가 매 실행마다 ZIP 하나를 올린다. 성공 실행도 올린다.
- `source`: `aisarang-reservation-diag`
- `customerId`: `2309842` → 게이트웨이가 `05788f12-...` 로 resolve (`matched: true` 확인함)
- 저장 위치: `artifacts/private/05788f12-b025-48ba-bb01-7c45121013d8/`
- 내용: `meta.json`, `run.log`, `clock_sync.json`, `page_source/*.html`,
  `requests/*.json`, `cookies_*.json`, `localStorage_*.json`, `error/traceback.txt`

**마스킹은 `Diagnostics.add_text()` 한 지점에서 강제된다.** 다른 경로로 새지 않게
일부러 단일 통과점으로 만들었다. 주민번호/전화/카드/이메일/이름 필드/
비밀번호·서명값 키를 지운다. 인증서 비밀번호는 `register_secret()` 으로 등록돼
문자열 치환으로 한 번 더 지워진다.

> 함정: `name="aResult" value="<서명값>"` 형태는 단순 `키=값` 규칙으로는
> `value=` 만 지우고 정작 서명값을 그대로 남긴다. `_PW_ATTR` / `_PW_ATTR_REV`
> 로 따로 처리한다. `tests/test_masking.py::test_signed_blob_masked` 가 잡아냈다.

## 배포 현황 (v1.0.2, 2026-08-24)

- exe: https://works.insu.ng/works/public/2309842/aisarang-reservation-1.0.2.exe
  (29,112,880 bytes, `PE32+ executable (GUI) x86-64`, mode 644,
  서빙 바이트 sha256 = 빌드 바이트 sha256 = `1c7a3f3a1c765965...` 로 대조 확인)
  (1.0.0 도 같은 경로에 남아 있다. 이미 서빙된 파일명은 덮어쓰지 않는다.)
- 업데이트 매니페스트: https://works.insu.ng/works/public/2309842/version-aisarang.json
- CI: GitHub Actions run 성공 (unit tests → build → PE 확인 → 라이브 selftest →
  fixture selftest → GUI construct → GUI 스크린샷)
- 스크린샷: `out/gui.png` (실제 Windows 창을 PrintWindow 로 캡처, 실측 결과 표시)

### 측정된 근거

프로즌 exe 가 실제 Windows(2025Server, `frozen: True`)에서 매 실행 진단을 올렸다.
왕복지연에 따라 정밀도가 갈리는 것이 그대로 찍혔다:

| 대상 | 최소 왕복 | 동기화 오차 |
|---|---|---|
| 라이브 childcare.go.kr (러너→한국) | 870~900ms | ±531 ~ ±882ms |
| 로컬 fixture 서버 | 0~1ms | **±67 ~ ±171ms** |

고객 PC(국내 회선 → 국내 정부 서버)는 아래쪽 구간에 해당한다.

발사 정밀도 실측(실서버 동기화 후 목표 시각에 쏘기, 3회):
목표 대비 **+0.4ms / +0.5ms / +1.1ms** (의도한 300ms prefire 제외 기준).
즉 오차의 지배 요인은 스케줄러가 아니라 서버 시각 추정치와 왕복지연이다.

기본 센터로 실제 예약 화면 POST 도 던져봤다:
`POST /?menuno=605 stcode=11650000416` → HTTP 200, 51,666 bytes,
제목 "시간제보육 입소신청". 비로그인 세션이라 신청 폼 자체는 안 그려진다
(= 사이트의 공동인증서 게이트가 정확히 여기서 걸린다).

## 아직 굳히지 못한 것 (다음 사람이 볼 것)

**`?menuno=605` 의 로그인 후 DOM 을 우리는 못 봤다.** 고객 계정 없이는 볼 수 없고,
고객 계정으로 반복 테스트를 하면 실제 예약이 생기므로 하지 않았다.
그래서 `automation.py` 의 날짜/시간대/신청버튼 선택은 **여러 후보를 순서대로
시도하는 적응형**이고, 시도할 때마다 그 시점의 DOM 을 진단 ZIP 으로 올린다.

→ **고객의 첫 실제 실행(또는 연습 모드 실행) 직후 `artifacts/private/05788f12-.../`
의 최신 ZIP 에서 `page_source/*_reservation_page.html` 를 열어 실제 선택자를 확인하고
`select_date` / `select_time_slots` / `find_submit` 을 그 DOM 에 맞게 굳혀라.**
연습 모드(`dry_run`)로 돌리면 실제 예약을 만들지 않고 DOM 만 안전하게 받아올 수 있다.
이게 이 프로젝트에서 제일 먼저 할 일이다.

## 하면 안 되는 것

- 고객 계정으로 반복 예약 테스트 금지. 실제 예약이 생기고 취소는 센터 전화(1661-9361)로만 된다.
- 개발자도구 열기 금지 (자동 로그아웃).
- 이미 서빙된 exe 파일명 덮어쓰기 금지 (Cloudflare 엣지 캐시 → 업데이트 루프).
- 인증서 비밀번호를 로그/커밋/메시지에 남기지 말 것. 화면 입력 → 메모리 → 즉시 폐기.
