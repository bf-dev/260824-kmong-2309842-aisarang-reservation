# 260824-kmong-2309842-aisarang-reservation

아이사랑(childcare.go.kr) **시간제보육** 예약을 매일 오전 9시 오픈 순간에 넣는
Windows 프로그램. Kmong 고객 2309842 (거대한고봉밥), 주문 7566483, 150,000원.

- Neoworks customerId: `05788f12-b025-48ba-bb01-7c45121013d8`
- Artifacts / 정적호스팅 키: `2309842` (Kmong partnerId)
- 저장소: https://github.com/bf-dev/260824-kmong-2309842-aisarang-reservation (**public**, Actions 무료분 때문)

## 실행 / 빌드

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/ -q        # 227 passed (v1.0.10, 크롬 있으면 브라우저 포함)
python3 main.py                              # GUI (고객이 쓰는 화면)
python3 main.py --selftest                   # 실서버 조회 + 서버시각 동기화 점검
python3 main.py --guidemo --hold=60000       # CI 스크린샷용 데모 (실제 조회 수행)
python3 main.py --guidemo --showrecord       # 같은 데모인데 '5. 진단 기록' 카드가 보이게 스크롤
python3 main.py --arrivaltest                # 도착시각 모델 실검증 (서버 Date 헤더로 대조)
python3 main.py --clocktest=1.2 --interval=20  # 시각 재측정이 정말 주기적으로 도는지 (v1.0.6)
AISARANG_BASE_URL=http://127.0.0.1:18777 \
  python3 main.py --rectest                  # 진단 기록 모드 실행 (로컬 fixture 전용, v1.0.6)
python3 ci/fixture_server.py 18777           # --rectest 가 붙을 로컬 서버 (/rec 화면)
python3 main.py --handovertest               # 인계 모드를 실물 캡처에 대고 실행 (v1.0.9)
                                             #   기대: fired=1/6, HANDOVERTEST OK
python3 ci/build_netfunnel_fixture.py <ZIP>  # 대기열 픽스처 재생성 (v1.0.8)
python3 ci/build_too_early_fixture.py <ZIP>  # '예약시간전' 픽스처 재생성 (v1.0.9)
python3 ci/build_taken_fixture.py <ZIP>     # '선예약'(자리 뺏김) 픽스처 재생성 (v1.0.10)
```

빌드는 GitHub Actions `windows-latest` (`.github/workflows/build.yml`).
`winbuild`(windows-builder VM)는 이 작업 시점에 **ssh unreachable** 이라 못 썼다
(`winbuild status` 는 azure running / tailscale active 인데 ssh 만 죽어 있었다).
Actions 는 public repo 라 무료분으로 돌아간다. private 로 바꾸면 계정 전체
spending limit 때문에 즉시 막힌다.

**빌드 산출물은 v1.0.5 부터 exe 가 아니라 ZIP 이다** (`--onedir`, 아래
"배포 형식이 바뀌었다" 절 참고). CI 가 `out/aisarang-reservation-<ver>.zip` 을
만들고 그 안에서 실제로 실행까지 해본다. 게시 전에 CI 에서 **윈도우 디펜더
실제 스캔**을 통과해야 한다(`ci/defender_scan.ps1`, FLAGGED 면 빌드 실패).

배포:
```bash
gh run download <runId> -n aisarang-reservation -D out/ci-<ver>       # CI 산출물
sha256sum out/ci-<ver>/out/aisarang-reservation-<ver>.zip             # CI 로그의 값과 대조
~/workspace/scripts/works-publish 2309842 out/ci-<ver>/out/aisarang-reservation-<ver>.zip
# Caddy 로 실제 내려받아 sha256 다시 대조한 뒤에만 매니페스트를 갱신한다
curl -s -o /tmp/x.zip --resolve works.insu.ng:443:127.0.0.1 \
  "https://works.insu.ng/works/public/2309842/aisarang-reservation-<ver>.zip?cb=$RANDOM"
install -m 0644 version-aisarang.json \
  /home/bfdev/neoworks/apps/gateway/artifacts/public/2309842/version-aisarang.json
```
매니페스트에는 `zipUrl` 만 넣는다. `exeUrl` 을 같이 넣으면 1.0.4 이하의 옛
업데이터가 ZIP 을 exe 자리에 덮어써서 프로그램을 망가뜨린다.

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
  그리고 **셀레니움 크롬 자체를 오탐한다**(2026-08-24 실측, 6단계 참고).
  v1.0.3 부터 이 파일만 네트워크에서 막는다. devtools 는 여전히 열지 말 것.
- `netfunnel-pcms.js` (넷퍼널 가상대기열). **2026-08-26 실측: 9시 직전에는 실제로
  켜진다.** 목록 화면 소스에서는 주석 처리돼 있지만, [예약하기] 를 누르는 순간
  사이트가 `netfunnel-pcms.js` / `netfunnel-skin.js` 를 XHR 로 불러오고
  `nf.childcare.go.kr:8443/ts.wseq?opcode=5101` 로 대기열에 세운다. 그동안
  예약 확인창은 **열리지 않는다**. 순번과 예상 대기는 `#NetFunnel_Loading_Popup`
  안에서 읽는다. 자세한 것은 아래 v1.0.8 절. 다시 누르면 맨 뒤로 간다.

## 실사이트 단계별 검증 맵 (2026-08-24 / 4·5단계는 2026-08-25 갱신)

1·3단계는 KR 프록시(egress 115.68.232.141), 2·6단계는 KR 프록시와 직접 접속
양쪽으로 확인했다. 증거 파일은 `docs/site-map/` 에 그대로 저장돼 있다.
저장 전에 전부 `masking.mask()` 를 통과시켰고 세션 식별자도 지웠다.

**4·5단계는 2026-08-25 에 고객이 보내준 인증서 세션 화면녹화로 바뀌었다.**
서버에서는 절대 볼 수 없는 화면이라(공동인증서 세션 전용) 이게 유일한 증거다.
원본 영상: `artifacts/attachments/2309842/349612618-52077510-IMG_8675.MOV` (51초),
프레임: `docs/site-map/recording/r01..r12`.

**추정으로 채운 칸은 없다. 못 본 것은 못 봤다고 적는다.**

### 코드 지도

| 파일 | 맡은 것 |
|---|---|
| `aisarang/site.py` | 공개 조회 API (시도/구군/기관검색/운영사항) |
| `aisarang/clock.py` | 서버시각 동기화 + **도착시각 모델** + `note_too_early` 보정 |
| `aisarang/automation.py` | 크롬 띄우기, devtools 오탐 차단, 로그인/세션/인증등급, 진단 수집 |
| **`aisarang/booking.py`** | **4·5단계 전부.** 준비(1~8) / 홀드 / [확인] 발사 / 응답 분류 |
| `aisarang/runner.py` | 순서 조립: 동기화 → 로그인 → 준비 → 홀드 → 정각 [확인] → 보고 |
| `aisarang/reporter.py` | 매 실행 진단 ZIP 업로드 (Artifacts API) |
| `ci/fixtures/reserve_page.html` | 녹화를 보고 재현한 4·5단계 화면(구조만). 진짜 크롬 테스트용 |

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
  `mbrid/uspass/ltype=id/flag=PISl/kybrdscrtyyn=N`). **아이디 로그인만으로는
  4·5단계가 열리지 않는다는 것을 이제 실측으로 확정했다** (2·4단계 참고).

### 2단계 — 로그인 후 세션 상태  ✅ 확인함 (2026-08-24, 고객 계정 아이디 로그인)

고객이 자기 아이디/비밀번호를 알려주어 **실제로 로그인해서** 확인했다.
(자격증명은 이 문서를 포함해 어떤 파일에도 적지 않는다. 채팅에만 있다.)

- 로그인 요청: `POST /icms/login/login.html` (폼 `frmLoginId` 그대로)
  `mbrid uspass ltype=id flag=PISl loginPageType=01 nMbrYN=N kybrdscrtyyn=N
   introYN= returnUrl= ssoReturnMenuno=1 issacweb_data=`
  → **302** `Location: /?menuno=1&loginPageType=01&flag=DR&introYN=`  = 성공
- 실패는 → **302** `Location: /?menuno=50&returnUrl=&introYN=` 이고, 이어지는
  페이지에 서버가 문구를 찍어 내려준다(`04-login-id-fail.html`):
  ```html
  <!-- 세션 메세지 체크 -->
  <script>icmsLayerPopup.alert({ contents : "아이디 또는 패스워드가 일치하지 않습니다." });</script>
  ```
  빈 값으로 보내면 같은 자리에 `"잘못된 정보입니다."` 가 오고 302 도 안 난다.
  → **결과 판정은 이 블록을 읽는 게 정답이다.** `automation.read_session_message()`
  가 이 정규식을 들고 있고 `read_result()` 가 본문 키워드보다 먼저 본다.
- 성공 후 쿠키: `JSESSIONID WMONID egovExpireSessionTime egovLatestServerTime`
  **+ `mbrno` + `uid`** (뒤 두 개가 로그인 표식)
- **세션 수명 60분(실측).** 로그인 직후
  `egovExpireSessionTime - egovLatestServerTime = 3,600,000 ms`.
  → 전날 밤에 인증서 로그인을 해두는 운영은 **불가능**하다. 그래서
  `runner._wait_keeping_session()` 이 09시까지 10분마다 세션을 건드린다.
- **`kybrdscrtyyn=N` 이면 비밀번호는 평문 폼필드로 간다.** 로그인 페이지의
  `npPfsStart()`(키보드보안)는 버튼을 눌러야만 돌고 자동 실행되지 않는다.
  `issacweb_data` 는 빈 hidden 그대로다(암호화 모듈 JS 자체가 페이지에 없다).

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

### 4단계 — 예약 화면(아동 선택 → 반/이용시간 → 날짜×시간 표)  ✅ **이제 봤다**

**증거의 출처가 바뀌었다.** 2026-08-25 고객이 **자기 공동인증서 세션을 직접
화면녹화해서 보내주었다** (51초, 휴대폰으로 모니터를 찍은 것이라 흐리지만
흐름은 다 읽힌다). 프레임은 `docs/site-map/recording/` 에 저장했다.
아래는 그 프레임에서 읽은 것만 적는다. **id/class 는 여전히 못 읽는다**
(녹화 해상도 568x320). 그래서 코드의 선택자는 이름이 아니라 **구조와 글자**로
찾는다(자세한 것은 `aisarang/booking.py` 머리말).

| 화면 | 프레임 | 읽은 것 |
|---|---|---|
| 검색 | `r01-search-region-picker.jpg` | 구분 라디오(**독립반** / 통합반), 지역 = 시/도·시/군/구 **2단 목록 위젯**(왼쪽 시/도, 오른쪽 시/군/구), 검색어(placeholder `어린이집명`), **조회** |
| 결과 목록 | `r02`, `r03` | 센터별 이름·주소·연락처·`예약가능` 뱃지 + 오른쪽 초록 **[시간제보육 예약]** 버튼. 신반포 센터가 목록에 있고 즐겨찾기(★) 표시돼 있다 |
| **아동 선택** | `r04`, `r05` | **"시간제보육 아동 선택"** 표: 선택(라디오) / 아동명 / 생년월일 / 개월수. → **NOTES 이전 판에 없던 단계다.** 라디오 하나 고르고 파란 버튼으로 진행 |
| 상세 | `r06` | 이용기관명 `서초구육아종합지원센터(신반포) (02-596-9340)`, 주소 `[06504] 서울특별시 서초구 신반포로19길 26`, 탭 `이용정보 신청` / `통합반 이용정보 신청`, **예약 가능일 `2026-08-25 ~ 2026-09-08`**(= 오늘 ~ 2주 뒤), **반명** select, **이용시간** select(옵션 `선택,1,2,…,9`) |
| 안내문 | `r06` | `· 예약방법 : 이용시간 선택 > 이용시간의 숫자선택 > 추가 버튼 클릭 > …` / `· 예약상태 [0] 이용가능시간대 [X] 이용불가시간대 (숫자는 이용 가능한 아동수)` / `· 시간제보육 결제금액 : 시간당 정부지원 3,000원, 부모부담금 2,000원` / 문의 `1661-9361` |
| **날짜×시간 표** | `r07`, `r08` | 헤더 첫 칸 `날짜/시간`, 그 뒤 열이 **시(09 10 11 12 13 14 15 16 …)**. 행이 날짜 `2026-09-02(수)` ~ `2026-09-08(화)`. 칸 값은 **남은 정원 숫자** 또는 **X**. 표 위에 `※ 점심시간(12시)을 포함하여 예약하실 경우 점심도시락을 지참하여…` |

표에서 실제로 본 값 (`r08`, `r09`):
```
2026-09-05(토) X X X X X X X X X     ← 미운영
2026-09-06(일) X X X X X X X X X
2026-09-07(월) 0 0 0 1 0 0 0 0 0     ← 남은 자리 0 = 이미 다 나감
2026-09-08(화) 2 2 2 2 2 2 2 2 2     ← 이번에 새로 열린 날. 전부 2명 남음
```
**그래서 X 와 0 은 "누르면 안 되는 칸"이 아니라 "자리가 없는 칸"이다.**
코드는 이 둘을 클릭하지 않고 `no_capacity` 로 보고한다
(`booking.pick_cell`, `tests/test_booking.py::test_x_and_zero_are_reported_not_clicked`).

표 아래에는 **[추가] [삭제]** 버튼과 월 누적 시간(`8월 예약시간 : 75시간`,
`9월 예약시간 : 35시간`)이 있다.

### 5단계 — 추가 → 체크 → 예약하기 → **예약 모달의 [확인]**  ✅ **이제 봤다**

| 단계 | 프레임 | 읽은 것 |
|---|---|---|
| 칸 클릭 | `r08` → `r09` | 숫자 칸을 누르면 **이용시간(9)만큼 연속된 칸**이 파랗게 칠해진다. 09-08 행 전체가 칠해진 상태 |
| [추가] | `r09` | 아래 **선택표**에 행이 생긴다: `선택`(체크박스, **처음엔 꺼져 있다**) / `반명`(매송아이) / `이용일`(2026-09-08(화)) / `이용시간`(`09 00 - 18 00 (9시간)`) |
| 체크 | `r10` | 그 행의 체크박스를 **직접 켜야 한다** |
| [예약하기] | `r10` | 선택표 오른쪽 아래 파란 버튼 |
| **예약 모달** | `r10`, `r11` | 제목 `예약`, 본문 `월 이용 시간이 60시간을 초과할 경우 바우처 지원이 되지 않습니다 ※ 시간당 5,000원으로 이용 / 8월 현재 예약 시간 포함하여 60시간을 초과합니다 / 예약하시겠습니까?`, 버튼 **확인 / 취소**, 우상단 X |
| [확인] | `r11` | **여기서 비로소 예약이 전송된다.** [예약하기] 는 아직 아무것도 보내지 않는다 |

#### 여기서 타이밍의 의미가 바뀌었다 (v1.0.4 의 핵심)

고객 진술(2026-08-25):
> 2주 뒤 날짜는 **자정에** 목록에 나타나지만, **예약이 되는 것은 09:00** 이다.
> 그래서 9시 전에 [예약하기] 까지 다 눌러 모달을 열어두고 기다리다가,
> 정각에 **[확인] 한 번만** 누른다. 실패는 언제나 그 한 클릭이
> 조금 늦거나 조금 이른 것이었다.

그리고 그 두 실패가 **서버 응답으로 구분된다**(고객 진술):

| 클릭이 | 서버 문구 | 뜻 | 우리가 하는 일 |
|---|---|---|---|
| 조금 **이르면** | `예약시간전` | 아직 안 열렸다. **자리는 그대로 살아 있다** | 즉시 재발사(기본 90ms 간격). 그리고 이 응답으로 도착 추정을 보정한다 |
| 조금 **늦으면** | `정원초과` | 그 칸은 이미 나갔다 | **더 두들기지 않는다.** 그대로 보고하고, 고객이 시작 시간대를 여러 개 지정했으면 다음 것으로 한 번 더 간다 |

→ 그래서 v1.0.4 는 준비(1~8단계)와 발사(9단계)를 **분리한다**:

```
정각 -240초   준비 시작: 검색 → 센터 → 아동 → 반/이용시간 → 날짜칸 → 추가 → 체크
              → [예약하기] → 모달 열림 → [확인] 버튼을 window.__aisarang_ok 에 조준
정각 -240..0초 모달을 붙잡고 대기. 5초마다 "확인 버튼 살아있나 / 체크 켜져있나" 확인.
              닫혔으면 확인 경로만 다시 세운다(redrive_confirm). 그것도 안 되면 준비부터.
정각 -300ms   [확인] 발사 (도착 기준. 편도지연만큼 더 일찍 로컬 발사)
정각 이후 20초 예약시간전이면 계속 재발사 / 정원초과면 즉시 중단 / 완료면 끝
```

발사 순간에 하는 일은 `window.__aisarang_fire()` 한 줄이다. 모달을 파싱하거나
버튼을 다시 찾지 않는다(그 시간이 곧 지연이다). `__aisarang_fire` 는 버튼이
화면에서 사라졌으면 **누르지 않고 false 를 돌려준다**.

#### '예약시간전' 으로 시계를 고치는 방법 (`clock.note_too_early`)

우리 추정으로 정각 대비 `A` 에 도착했는데 서버가 "아직 예약시간이 아니다"
라고 했다면, 실제 도착은 정각 **이전**이었다. 추정오차 `err` 에 대해
`추정 - err < 정각` 이므로 `err > A`. **A ≥ 0 일 때만 새 정보다**
(일부러 앞당겨 쏜 음수 A 에서는 예약시간전이 당연하므로 배울 게 없다).
배운 만큼(`A + 30ms`) 다음 발사를 뒤로 미룬다.
`tests/test_booking.py::test_note_too_early_corrects_only_when_we_thought_we_were_late`.

#### 안전 불변식 (그대로 유지, 오히려 강해졌다)

`Prepared.ready()` 가 네 가지를 **모두** 요구한다. 하나라도 거짓이면
`[예약하기]` 도 `[확인]` 도 누르지 않는다.

1. `cell_selected` — 날짜 칸을 눌렀고 **표의 표시가 실제로 바뀌었다**
   (class 이름을 맞히지 않는다. 클릭 전후 지문을 비교한다: `_JS_CELL_MARKS`)
2. `row_ticked` — 선택표 행의 체크박스가 **지금 켜져 있다**(발사 직전 재확인)
3. `modal_open` — "예약하시겠습니까?" 모달이 떠 있다
4. `armed` — 그 모달 안의 [확인] 버튼을 잡아뒀다

테스트: `tests/test_automation_safety.py`(준비 쪽 6개),
`tests/test_booking.py`(발사 쪽), `tests/test_browser_flow.py`(**진짜 크롬**).

#### 진짜 브라우저로 검증했다 (`tests/test_browser_flow.py`)

가짜 드라이버로는 "선택자가 실제 DOM 을 잡는가" 를 증명할 수 없다. 그래서
녹화를 보고 같은 **구조**의 화면을 다시 만들어(`ci/fixtures/reserve_page.html`)
헤드리스 크롬으로 실제로 돌린다. 스크린샷:
`docs/site-map/recording/r13-reconstructed-flow-modal.png`.

이 테스트가 **실제 버그를 하나 잡았다**: 아동 선택 표에도 라디오가 있어서
"체크박스/라디오가 있는 첫 표" 로 선택표를 찾으면 **아동 표를 집는다**.
`_JS_SCAN_SLOT_ROWS` 가 "이용일(날짜)이 있는 표 > 체크박스 표 > 라디오 표"
로 점수를 매기도록 고쳤다.

> 선택자를 이 fixture 에 맞춰 고정하면 안 된다. fixture 는 구조 재현일 뿐이고
> 진짜 마크업은 아직 못 봤다. 고객 실행 진단의 `page_source/*.html` 로 굳혀라.

### 6단계 — 치명적 함정: 사이트의 devtools 감지가 셀레니움을 오탐한다  ✅ 확인 + 수정함

**v1.0.2 를 그대로 돌렸으면 09시에 로그아웃당했다.** 실측:

```
셀레니움으로 크롬 실행 → https://www.childcare.go.kr/?menuno=242 열기
→ 1초 안에 alert("부정 사용 방지를 위하여 개발자 도구 사용을 차단합니다.")
→ window.location.href = "/logout"
```

개발자도구를 연 적이 없다. `disable-devtool.0.3.7.min.js` 가 자동화된 크롬을
devtools 로 오탐한다. 우리 `build_driver()` 옵션 그대로 재현했고, 두 번 다 1초 안에 터졌다.

수정: `neutralize_devtool_blocker()` 가 CDP `Network.setBlockedURLs` 로
`*disable-devtool*` **파일 하나만** 막는다(+ 크롬 버전 대비용 무해한 stub 이중화).
페이지 인라인 코드는 `typeof DisableDevtool !== 'undefined'` 로 감싸여 있어서
없으면 `console.error` 한 줄 남기고 정상 동작한다. 수정 후 실측:
16초간 alert 없음 / `/logout` 없음 / 제목 "시간제보육기관찾기..." 정상 / `#pagingForm` 존재.

> 여전히 **개발자도구는 절대 열지 말 것**. 우리가 끈 것은 "열지도 않았는데 튀는 오탐"이다.

## 맞춰야 하는 건 '발사'가 아니라 '도착' (v1.0.3, v1.0.4 에서 대상이 좁아졌다)

> **v1.0.4**: 이 도착 모델이 적용되는 요청은 이제 **[확인] 클릭 하나뿐**이다.
> 앞의 검색/센터/아동/반/시간/칸/추가/체크/[예약하기] 는 정각 훨씬 전에 끝내둔다.
> `arrival_lead_ms`(옛 `prefire_ms`)는 그 [확인] 요청을 정각보다 몇 ms 먼저
> **도착**시킬지를 뜻한다.


고객 보고: 손으로 성공시킬 때 누른 시각은 **08:59:59.xxx**, 정각 전이었다.
즉 기준은 요청이 **서버에 닿는 시각**이다. 로컬에서 09:00:00.000 에 쏘면
편도지연만큼 늦게 도착한다.

```
목표도착 = 09:00:00 - prefire_ms(기본 300ms)
발사시각 = clock.local_fire_for_arrival(목표도착)
         = (목표도착 - 서버오프셋) - 편도지연(=최소왕복/2)
```

`prefire_ms` 의 의미가 바뀌었다: 예전엔 "로컬에서 몇 ms 일찍 쏠지",
지금은 "**서버에 몇 ms 일찍 도착시킬지**". 편도지연 보정은 그 위에 자동으로 붙는다.

**도착 모델을 실제로 검증했다** (`main.py --arrivaltest`, `clock.measure_arrival`).
서버 초 경계 B 의 앞뒤로 겨냥해 쏘고, 응답 `Date:` 헤더가 가리키는 초를 본다.
delta<0 이면 B-1, delta>0 이면 B 가 나와야 한다. 실측 (이 서버 → childcare.go.kr):

| 실행 | 최소왕복 | 편도추정 | delta -300 / -120 / +60 / +250ms | 결과 |
|---|---|---|---|---|
| 1 | 778ms | 389ms | 전부 기대한 초 | **4/4** |
| 2 | 793ms | 396ms | 전부 기대한 초 | **4/4** |
| 3 | 856ms | 428ms | 전부 기대한 초 | **4/4** |

스케줄러 발사 오차는 **0.15 ~ 0.52ms**. 즉 오차의 지배 요인은 여전히
서버시각 추정치와 왕복지연이지, 우리 타이머가 아니다.
왕복 800ms 짜리 회선에서도 12/12 로 맞았으니, 고객 PC(국내 회선, 왕복 10~30ms)
에서는 훨씬 좁게 맞는다.

`runner` 는 실제로 쏜 순간을 기록해 **"도착 추정이 정각 대비 몇 ms 였는지"** 를
로그와 진단에 남긴다(`fire_error_ms`, `arrival_offset_ms`).

> 아직 모르는 것: 서버가 **정각보다 이른 도착을 거부하는지**, 거부한다면 몇 ms부터인지.
> 확인하려면 실제 예약을 만들어야 해서 안 했다. 그래서 기본값을 고객이 손으로
> 성공시킨 구간(정각 300ms 전 도착)에 두고, 거부당해도 `retry_seconds`(기본 20초)
> 동안 재시도가 정각 이후로 이어진다.

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

## 배포 형식이 바뀌었다: 한 파일 exe → 폴더 ZIP (v1.0.5, 2026-08-25)

### 무슨 일이 있었나

고객이 v1.0.4 exe 를 내려받아 더블클릭했더니 윈도우가 이렇게 답했다(고객 사진):

> 지정한 장치, 경로 또는 파일에 액세스할 수 없습니다.
> 이 항목에 액세스할 수 있는 권한이 없는 것 같습니다.

### 진단 (추측이 아니라 측정한 것)

1. **호스팅 문제가 아니다.** Caddy 경유로 실제 내려받은 바이트의 sha256 이
   빌드 바이트와 같다(`da8f84b2…b77d1`), 200, mode 644. 다운로드는 성공했다.
2. **정적 시그니처 탐지도 아니다.** windows-latest 에서 정의를 최신
   (엔진 1.1.26070.7 / 서명 1.457.329.0)으로 올린 뒤 그 파일 그대로 스캔:
   `Scanning …\v104.exe found no threats` → **VERDICT v1.0.4-onefile: CLEAN**.
   즉 "이 파일은 바이러스다" 라는 판정이 아니다.
   (러너는 `RealTimeProtectionEnabled: False` 라 실행 시점 동작 감시와
   클라우드 평판은 재현할 수 없다. 그래서 여기서 CLEAN 이 나온 것이
   "고객 PC 에서도 안 막힌다" 는 뜻은 아니다. 못 본 것은 못 봤다고 적는다.)
3. **고객 PC 의 실제 측정치가 남았다.** 2026-08-25T05:24Z 에 고객 PC 에서
   v1.0.4 진단 ZIP 이 올라왔다(`frozen: true`, Windows 10 19045).
   `run.log` 의 첫 줄이 **14:15:30**, 다음 줄(서버 시각 동기화 시작)이
   **14:19:14**. 즉 프로세스가 뜨고 파이썬 코드 첫 줄이 도는 데까지
   **3분 44초**가 걸렸다. `--onefile` 은 실행할 때마다 29MB 를 %TEMP% 에
   풀어놓고, 실시간 감시가 그 1,300여 개 파일을 전부 훑는다. 이것이
   같은 exe 가 "안 열린다 → 한참 뒤 열린다" 로 보이는 이유이고,
   9시 정각 작업에서는 그 자체로 치명적이다.

→ 결론: **범인은 onefile 의 %TEMP% 자가압축해제다.** 파일 내용이 아니라 실행
   방식이 문제이므로, 그 동작을 없애는 것이 고칠 수 있는 유일한 지점이다.
   (고객에게 백신을 끄라고 하지 않는다.)

### 무엇을 바꿨나

| | v1.0.4 | v1.0.5 |
|---|---|---|
| 패키징 | `--onefile` exe 1개 | **`--onedir` + ZIP** (`exe` + `_internal/`) |
| 실행 시 | 매번 %TEMP% 에 자가압축해제 | 푸는 동작 **없음** |
| 파일 메타데이터 | 없음 | **버전 리소스 + 아이콘** (`ci/version_info.txt`, `ci/app.ico`) |
| 자동 업데이트 | `exeUrl` 한 파일 교체 | **`zipUrl` 폴더 통째 교체**(robocopy), 옛 `exeUrl` 경로도 유지 |
| 디펜더 검증 | 없었다 | **CI 에서 실제 스캔**(`ci/defender_scan.ps1`), FLAGGED 면 빌드 실패 |

`MpCmdRun.exe -Scan -ScanType 3 -File <path> -DisableRemediation` 를 쓴다.
`-MustBeClean` 을 주면 탐지 시 빌드를 세운다. **스캔하지 않은 것은 올리지 않는다.**

고객 쪽 순서는 `_읽어주세요.txt` 2번에 적어뒀다: ZIP **속성 → 차단 해제**
(MOTW 제거) → 압축 풀기 → 폴더 안의 exe 실행. exe 만 따로 옮기면 안 된다.

### 아동 선택 단계도 같이 고쳤다 (진짜 마크업을 처음 봤다)

같은 진단 ZIP 의 `page_source/0002_reservation_page.html` 이 **인증서 세션의
진짜 예약 화면**이다. NOTES 가 "다음 사람이 굳혀라" 라고 적어둔 바로 그 파일이다.
읽은 것:

```html
<input type="radio" name="occasionChk" onclick="listChildSelect();"
       data-usereqstcnt="1" data-chcaregbyn="Y" ...>
```
```js
function listChildSelect() {
  if (usereqstcnt < 1) { alert('이용신청서를 먼저 등록해주세요.'); ... }
  else if ($('#unityyn').val() == 'N') $('[data-tab=divOccasionTimeSlPL]').trigger('click');
  else                                 $('[data-tab=divOccasionTimePils]').trigger('click');
}
// 탭 클릭 → fnChildInfo() → POST /icms/occasion/OccasionTimeMainSlPL.html
//         → 반명/이용시간/날짜표를 ajax 로 그려넣는다
```

여기서 v1.0.4 의 실제 버그 두 개가 드러난다.

1. **라디오가 이미 켜져 있으면 우리는 누르지 않았다.** 그런데 이 클릭이
   이용정보 화면(반명/이용시간/날짜표)을 여는 **유일한 트리거**다.
   안 누르면 그 뒤 단계가 전부 빈 화면을 뒤진다. → 항상 누른다.
2. **화면이 ajax 로 늦게 그려진다.** 곧바로 다음 단계로 가면 아직 없다.
   → `_JS_USEINFO_READY` 로 최대 15초 기다린다. 라디오 onclick 이 안 돌았을
   때를 위해 `[data-tab=…]` 탭을 직접 누르는 두 번째 경로도 둔다.
   그리고 `alert()` 이 뜨면(이용신청서 미등록) 닫고 그대로 보고한다.
   안 닫으면 셀레니움의 이후 모든 명령이 그 자리에서 막힌다.

`ci/fixtures/child_select.html` 이 그 실제 구조를 재현한 것이고(개인정보는
가짜 값), `tests/test_browser_flow.py` 의 마지막 두 개가 **진짜 크롬**으로
"이미 체크된 라디오도 눌러서 화면을 연다 / alert 을 닫고 보고한다" 를 검증한다.

> 개인정보 주의: 원본 `page_source` 에는 아동 이름이 그대로 있다. 저장소에는
> 절대 넣지 않는다. 예전에 fixture 에 실명이 들어가 있던 것도 이번에 지웠다.

### 아직 못 본 것 (그대로 남아 있다)

날짜×시간 표 / [추가] / 선택표 / [예약하기] / 예약 모달의 **진짜 마크업은
여전히 못 봤다.** 고객 실행이 09시 대기 상태에서 멈춰서 그 화면까지는
진단에 안 담겼다. 다음 실행 진단의 `page_source/*_after_add_and_tick.html`,
`*_modal_open_armed.html` 을 보고 굳혀라.

## v1.0.6 (2026-08-25): 진단 기록 모드 + 5분 시각 재측정 + 아동/선택표 오선택 수정

### 1) 진단 기록 모드 (`aisarang/recorder.py`, GUI '5. 진단 기록')

**왜.** 날짜×시간 표부터 예약 모달까지의 진짜 마크업을 우리는 아직 못 봤다.
그 화면은 아동 라디오 클릭으로 오는 ajax 응답
(`SelectOccasionChild.html` / `OccasionTimeMainSlPL.html` /
`OccasionTimeMainPiIs.html`) 안에 들어 있고, 공동인증서 세션에서만 열린다.
고객 실행 진단은 전부 "09시 대기 중"에서 멈춰 거기까지 가지 않았다.
그래서 **사람이 손으로 걸어가고 우리는 옆에서 받아적는** 모드를 만들었다.

**설계 원칙 세 개.**
1. 아무것도 누르지 않는다. 첫 화면을 여는 `driver.get()` 말고는 클릭/자동
   진행/자동 닫기/자동 제출이 **코드에 존재하지 않는다.**
   `tests/test_recorder_flow.py::test_the_recorder_has_no_way_to_click_anything`
   이 소스에 `.click()` / `.submit()` / `send_keys` / `ActionChains` /
   `dispatchEvent` 가 없다는 것을 못박는다. 누가 "한 번만 눌러주자" 를 넣으면
   테스트가 깨진다.
2. 사람을 방해하지 않는다. 펌프는 `network / console / clicks / screen` 네
   단계로 나뉘고 **단계마다 따로** 감싼다. 하나가 실패해도 나머지는 돌고,
   실패는 `record/summary.json` 의 `skipped[]` 에 남는다.
3. 잃지 않는다. 5분마다 중간 업로드, 중지 때 한 번 더(그때는 blocking).
   브라우저가 닫히면 그 자리에서 마지막 업로드를 하고 끝낸다.

**남기는 것**: `record/wanted/*.html`(그 세 응답 본문), `record/network.json`
(요청/응답 URL·메서드·상태·헤더·postData, 쿠키 값은 이름만),
`record/bodies/*.txt`, `page_source/*.html`(화면이 의미 있게 바뀔 때마다),
`record/clicks.json`, `record/console.json`, `cookies_record.json`(이름/길이만).

**함정 두 개를 여기서 실제로 밟았다.**
- `driver.quit()` 로 크롬드라이버가 사라지면 셀레니움은 "no such window" 가
  아니라 **연결 거부**를 던진다. `_is_gone()` 이 그걸 몰라서 기록기가 죽은
  세션에 1초마다 영원히 재시도했다. 연결 계열 문구를 전부 넣고, 그래도 못
  알아본 경우를 위해 "한 바퀴에서 아무것도 성공 못 함"이 `DEAD_ROUNDS`(3)회
  이어지면 끊긴 것으로 본다.
- `automation.drain_network()` 는 예외를 삼켰다. 그래서 브라우저가 죽었는데도
  "잘 돌았다"로 보였다. 기록기는 `raise_on_error=True` 로 부른다(예약 경로는
  기본값 그대로 조용히 넘어간다).

**검증**: `tests/test_recorder_flow.py` 가 진짜 크롬 + 진짜 fixture 서버로
11개를 돌린다(누르지 않음 / 못 본 응답 본문 확보 / 화면 변화 스냅샷 /
레이어 여닫기 / 이동 중 기록 유지 / 헤더에 쿠키값 없음 / 주기 업로드 /
브라우저 닫힘 / 제품 옵션으로 크롬이 실제로 뜨는지).
`ci/fixture_server.py` 의 `/rec` 화면에 계기가 두 개 심어져 있다:
`window.__humanClicks`(클릭 수)와 `window.__reserved`(예약 계기).
CI 는 프로즌 exe 로 `--rectest` 를 돌려 `reserved=False` 를 확인한다.

### 2) 서버 시각을 5분마다 다시 잰다 (`clock.ClockKeeper`)

전날 오후에 켜두면 09시에는 몇 시간 전 오프셋으로 쏘게 된다.
`config.RESYNC_SECONDS=300` 마다 다시 재고, `RESYNC_QUIET_SECONDS=90` 초
전부터는 멈춘다(발사에 끼어들지 않는다). 실패해도 마지막 성공값으로 간다.
실제 실행 로그(고객 진단으로 올라온 것):

```
서버 시각 재측정 주기: 5분 (정각 90초 전부터는 멈춥니다)
서버 시각 재측정(5분마다, 1회차): 보정 -246ms → -628ms
  (변화 -382ms, 오차 ±789ms, 샘플 6개, 최소왕복 905ms)
```

`main.py --clocktest=<분> --interval=<초>` 가 제품이 쓰는 그 ClockKeeper 를
그대로 돌려 `RESYNC n=...` 줄을 찍는다. CI 가 프로즌 exe 로 3줄 이상을 요구한다.

### 3) 아동 표를 선택표로 골라 엉뚱한 라디오를 켜던 문제

`ci/fixtures/real_reservation_page.html`(고객 PC 가 올린 진짜 마크업, 이름만
가명)에 대고 돌리면 v1.0.5 가 그대로 재현된다. 아동 행의 생년월일
`2025.10.22` 가 날짜 정규식을 통과해 `dated * 10` 으로 이겼고, `tick_slot_row`
가 `rows[-1]` 로 떨어져 **아동 라디오를 켜고** "선택표 행을 체크했습니다" 를
남겼다. `slot_row_is_ticked` 까지 참이 되어 `open_modal` 의 안전장치를 통과했다.
→ 아동 표는 후보에서 배제하고, 점수를 **이용시간 구간**(`09 00 - 18 00 (9시간)`)
기준으로 바꿨다. 마지막 행 폴백도 "선택표 행처럼 생겼을 때만" 쓴다.
그리고 `_JS_READ_NOTICE` 의 `.popup` 은 실제 컨테이너 `popup_wrap` 에 **맞지
않는다**(클래스 이름 전체가 popup_wrap 이다). 부분일치로 바꿨다.
테스트: `tests/test_real_markup.py`(진짜 크롬).

### 4) 크롬 네트워크 로그를 실제로 켰다 + 크롬이 아예 안 뜨던 함정

`capture()` 의 `network_*.json` 은 고객 진단 ZIP 50개 중 **한 건도** 없었다.
`goog:loggingPrefs` 가 없어서 `get_log("performance")` 가 언제나 예외였기
때문이다. 이제 옵션을 켜고 `drain_network()` 로 링버퍼에 받는다.

> **`perfLoggingPrefs` 에 `traceCategories: ""` 를 넣지 말 것.** chromedriver 가
> `cannot parse traceCategories / cannot be empty` 로 **크롬을 아예 안 띄운다**
> (실측: 크롬 149 / chromedriver 149, InvalidArgumentException). 작업 중에 실제로
> 그 상태였다. 09시에 크롬이 안 뜨는 것보다 나쁜 실패는 없어서,
> `test_the_products_own_chrome_options_actually_launch_chrome` 이 제품 옵션
> 그대로 크롬을 띄워본다.

## v1.0.7 (2026-08-25): 실물 마크업 확보 - 4~9단계를 추론에서 사실로

**이 판의 전부는 근거의 교체다.** 기능을 새로 만들지 않았다. 4~9단계가
그동안 "구조와 글자로 더듬어 찾기" 였던 것을, 고객이 실제로 받은 응답의
id 로 바꿨다. 그 과정에서 **살아 있던 결함 다섯 개**가 드러났다.

### 무엇이 들어왔나

2026-08-25T08:53~08:57Z, 고객이 자기 PC(Windows 10 19045)에서 진짜 공동인증서
세션으로 v1.0.6 의 [진단 기록] 을 돌리고 예약 흐름을 **손으로 확인창까지**
걸었다. ZIP 두 개(두 번째가 상위집합):

```
artifacts/private/05788f12-b025-48ba-bb01-7c45121013d8/
  1787648224328-…-175705.zip   872,236 B  진단기록  페이지 14장 / 요청 373건 / 찾던 응답 2건
  1787648258593-…-175739.zip   872,254 B  같은 세션, GUI 종료 (meta/run.log 만 다름)
```

그 안에 우리가 한 번도 못 봤던 `/icms/occasion/OccasionTimeMainSlPL.html`
응답(35,922 B)이 통째로 들어 있다. **4~9단계를 그리는 화면이 전부 여기 있다.**

픽스처로 굳혀 두었다 (개인정보 치환 후 커밋됨):

```
ci/fixtures/real/occasion_time_main_slpl.html       이용정보 ajax 응답 (DOM 판정용, 스크립트 제거)
ci/fixtures/real/occasion_time_main_slpl.raw.html   같은 것, 스크립트 보존 (사이트 JS 문구 확인용)
ci/fixtures/real/grid_ready.html                    날짜x시간 표가 그려진 화면
ci/fixtures/real/grid_selected_row_added.html       칸 선택됨 + 선택표 1행
ci/fixtures/real/modal_open.html                    예약 확인창이 열린 상태
ci/fixtures/real/modal_open.raw.html                같은 것, 스크립트 보존
ci/fixtures/real/assets/*.css                       실물 CSS (가시성 판정에 필수, 아래 참고)
```

다시 만들려면: `python ci/build_real_fixtures.py <ZIP경로>` (기본값은 위 두 번째 ZIP).
개인정보가 한 글자라도 남으면 스크립트가 0 이 아닌 코드로 끝난다.

### 실측된 진짜 마크업 (이제 이게 기준이다)

```html
<!-- 4단계 반명. option 은 selectOcTaClList.html 응답으로 채워진다(value=clseq) -->
<select class="selectbox" name="clname" id="clname" onchange="fnSerChange();" title="반명 선택">

<!-- 5단계 이용시간. value 는 "1".."9" (시간 수) -->
<select class="selectbox" name="rtm" id="rtm" onchange="fnTimeReset();" title="이용시간 선택">

<!-- 6단계 날짜x시간 표: #crtminfo > table, 헤더 09..17 (0채움), 14행 x 9열 = 126칸 -->
<th id="day_0" class="table_tit1" scope="row">2026-08-26(수)
    <input type="hidden" name="resdt" id="resdt" value="20260826"></th>
<td><a href="javascript:;" class="time-option" id="tm_9_0"
       onclick="selectDay2(this,'9',0);"><i class="count" title="이용가능">1</i></a></td>
<!-- 고른 뒤 -->
<a class="time-option on" id="tm_9_2" title="선택됨"><i class="count on">1</i></a>
<!-- 이용불가 -->
<i class="count not" title="이용불가능">X</i>
<!-- 같은 tr 끝에 화면에 안 보이는 세 칸이 더 있다 -->
<td id="pp_0" style="display:none">2</td>   <!-- 벌점 -->
<td id="bm_0" style="display:none">10</td>  <!-- 개월수 -->
<td id="nsc_0" style="display:none">0</td>

<!-- 7단계 -->
<a href="javascript:;" id="timecareTableAddBtn" class="btn h50" onclick="f_AddQualRow();">추가</a>

<!-- 8단계 선택표. 내용은 글자가 아니라 input 의 value 에 있다 -->
<table id="INFOQUALF"> … <tr id="tId_0">
  <td><input type="checkbox" id="rowSchChkNo0" name="rowQualChkNo" class="chkHd"> …
  <td><input id="sdate0" value="2026-08-28(금)" readonly>
      <input type="hidden" id="resdt0" value="20260828"></td>
  <td><input id="restime0" value="09 : 00  ~  10 : 00  (1시간)" readonly> …

<!-- 9단계 -->
<a href="javascript:;" class="btn h50" id="timecareConfirm" onClick="fnSave();">예약하기</a>
<a href="javascript:;" class="btn lightgray h50" id="tooltip" …>예약대기</a>   <!-- 바로 옆! -->
```

### 확인창 문제는 이제 끝났다 (제일 중요)

예약 흐름은 `icmsLayerPopup.**confirm2**` 를 쓴다 (`layerpopup.js` 실측):

```js
icmsLayerPopup.confirm2({title:"예약", contents: confirmText,
                         thisFocus:"#timecareConfirm"}, function(res){ … InsertOcreqst … })
// confirm2 는 #layer-confirm-popup-title2 / -contents2 를 채우고
// #layer-confirm-popup2 와 #dimmed_confirm2 를 show() 한다.
// [확인] 콜백을 묶는 대상은 #layer-confirm-popup-confirm2 다.
```

따라서 **최종 [확인] 은 `#layer-confirm-popup-confirm` 이 아니라
`#layer-confirm-popup-confirm2`** 다. 전자를 눌렀다면 사이트가 그 버튼에
아무 콜백도 묶지 않았으므로 **조용히 아무 일도 일어나지 않았을 것이다.**

그리고 그 페이지에는 공용 팝업 껍데기가 **두 벌** 들어 있다:

| 사본 | 인라인 style | 본문 | 실제 상태 |
|---|---|---|---|
| 1번째 | `display: block` | "…예약하시겠습니까?" | **지금 열린 진짜 창** |
| 2번째 | 없음 | 비어 있음 | `.popup_wrap{display:none}` 으로 숨음 |

`id` 가 중복이므로 **`getElementById` 를 쓰면 안 된다**. `querySelectorAll` +
가시성으로 고른다. 같은 이유로 `id="layer-confirm-popup-close2"` 는 한 껍데기
안에서도 두 번 나온다(X 닫기, [취소]).

실측 본문 (고객은 이번 달 60시간을 이미 넘겨서 안내가 앞에 붙는다):

```
월 이용 시간이 60시간을 초과할 경우 바우처 지원이 불가합니다. ※ 시간당 5,000원으로 이용
8월 현재 예약 시간 포함하여 60시간을 초과합니다.
예약하시겠습니까?
```

즉 `"예약하시겠습니까"` 문구 자체는 **실물로 확인됐다**(사이트 JS 의
`confirmText` 기본값이고, 60시간 초과 분기에서도 마지막 줄이 그대로다).

### 고친 결함 다섯 개 (전부 실물에서 재현됨)

1. **날짜x시간 표를 126칸이 아니라 168칸으로 읽었다.**
   예전 `_JS_SCAN_GRID` 는 "첫 칸이 날짜인 줄의 모든 td" 를 칸으로 세고,
   헤더에 숫자가 없으면 시각을 `8 + 열번호` 로 지어냈다. 숨은
   `td#pp_0`(벌점 2) / `td#bm_0`(개월 10) / `td#nsc_0` 가 각각
   **18시=자리 2명 / 19시=자리 10명 / 20시=0** 으로 잡혔다.
   → 이제 `a[id^=tm_]` 이 있는 **보이는** td 만 세고, 시각은 헤더가 아니라
   `tm_<시각>_<행>` 의 id 에서 읽는다(헤더는 `09`, id 는 `tm_9_`; 0채움이 다르다).
   이용일도 화면 글자가 아니라 `input[name=resdt]` 의 `YYYYMMDD` 에서 읽는다.

2. **선택표 행이 통째로 빈 문자열로 읽혔다.**
   내용이 `input.value` 에 있는데 `innerText` 만 읽었다. 그래서 `date` 가 늘
   비었고, `tick_slot_row` 는 날짜로 행을 못 찾아 **매번 `rows[-1]` 폴백**으로
   떨어졌으며, 안전장치에 남는 `row_text` 도 비어 있었다.
   → `#INFOQUALF` 를 1순위로 잡고, 칸의 글자 + input value 를 합쳐 읽는다.

3. **확인창 본문이 '실패' 로 분류됐다.**
   실측 본문에 `불가` 와 `초과합니다` 가 둘 다 들어 있고, 옛 `FAIL_WORDS` 에
   그 두 조각이 있었다. 확인창이 화면에 남아 있는 동안 `read_outcome` 이 돌면
   **성공한 예약을 '실패' 로 보고**할 수 있었다.
   → `classify()` 가 질문(`하시겠습니까`)을 먼저 걸러 `R_UNKNOWN` 을 준다.
   `FAIL_WORDS` 에서 `불가` / `초과합니다` 를 뺐다.

4. **`"예약 가능 시간이 아닙니다"` 를 '아직 안 열렸다' 로 읽고 계속 재발사했다.**
   실물에서 이 문구는 사이트가 **클라이언트에서** 띄우는 거절이다
   (`selectDay2` 가 칸 값 "X" 일 때, `f_AddQualRow` 가 예약대기 전용 칸일 때).
   영영 열리지 않을 칸에 대고 정각의 남은 20초를 전부 태우는 경로였다.
   → 새 코드 `R_NOT_BOOKABLE`(재시도 안 함)로 분리했고
   `confirm_burst` 가 즉시 멈춘다. `"예약시간전"` 계열만 재시도로 남았다.

5. **우리 마스킹이 증거를 훼손하고 있었다.**
   `masking._PWKEY` 가 CSS 선택자 `input[type="password"]` 를 비밀번호로 오인해
   닫는 `]` 를 `***REDACTED***` 로 바꿨다. 그 자리에서 CSS 문법이 깨져 크롬이
   121KB 짜리 `sub.css` 를 **10,091번째 글자에서 읽다 멈췄고**, 뒤에 있던
   `.popup_wrap{display:none}`(65,394번째 글자)이 통째로 죽었다. 그러면
   숨어 있어야 할 확인창 두 번째 사본까지 "보인다" 로 렌더된다.
   → `_PWKEY` 의 값 부분에서 `]` 를 뺐다(`)`/`;` 는 그대로 둔다: 그 글자가 든
   진짜 비밀번호가 덜 지워지면 안 되니까). `ci/build_real_fixtures.py` 의
   `repair_masked_css()` 가 **이미 받은** 캡처의 그 자리를 되돌린다.

### 캡처에서 발견한 것 중 코드가 아닌 것

- **인증서 비밀번호가 `record/clicks.json` 에 평문으로 남았다.**
  기록기가 XecureWeb 키패드 입력칸(`input#xwup_certselect_tek_input1`)의
  `change` 이벤트 값을 그대로 적었다. 워크스페이스 추출본에서는 지웠고,
  값은 어디에도 옮기지 않았다.
  **다음 사람 할 일: `recorder.py` 가 클릭/변경 이벤트의 `text` 를 남길 때
  비밀번호성 입력(`type=password`, `xwup*`, `xkeypad*`)은 값을 아예 안 담도록
  막아라.** `masking` 은 ZIP 직전 한 지점에서만 도는데, 이 값은 그 규칙
  (`_PWKEY` 는 키=값 형태를 찾는다)에 걸리는 모양이 아니었다.
- 고객은 **이번 달 60시간을 이미 초과**했다. 그래서 확인창에 바우처 안내가
  앞에 붙는다. 우리 판정이 그 문구에 걸려 넘어지면 안 된다(위 3번).
- 고객의 반은 **하나뿐이다**(`해솔아이`). 사이트의 `fnSetCl` 이
  `clList.length == 1` 이면 자동 선택하고 `fnSerChange()` 까지 부른다.
  그래서 클릭 기록에 `#clname` 조작이 없다.
- 실측된 열린 자리: 08-26 은 09시와 17시만 1명, 나머지 0. 토·일은 전부 X.

### 감사 결과 (같은 51개 기준, 실행해서 낸 숫자)

```
python ci/selector_audit.py --verbose      # 항목별
```

| | 2026-08-25 오전 (v1.0.6) | 2026-08-25 저녁 (v1.0.7 게시본) |
|---|---|---|
| 확인 (실물 캡처) | 22 | **51** |
| 영상 복원본에만 근거 | 15 | **1** |
| 미확인 | 12 | **1** |
| 합계 | 51 | 53 |
| 제품 _JS_* 실물 실행 | (없음) | **13/13 통과** |

53 인 이유: 어제의 51 에 두 개가 새로 생겼다. "숨은 벌점/개월 열"(결함 1번의
원인이라 따로 못박을 값어치가 있다), 그리고 "결과 안내 껍데기
`#layer-alert-popup2`" ([확인] 이후 서버 답이 도착하는 자리. 아래 참고).

남은 둘:
- **영상 복원본만(1):** 이용신청서가 없는 계정에서 `listChildSelect()` 가
  띄우는 네이티브 alert 문구. 고객 계정에는 신청서가 있어서 안 뜬다.
  자동 accept 는 이미 구현돼 있다.
- **미확인(1): `예약시간전` / `정원초과` 의 서버 원문.**
  캡처 373건 어디에도 **없다.** 고객이 확인창에서 멈춰
  `InsertOcreqst.html` 이 **한 번도 호출되지 않았기 때문이다.**
  두 문구는 여전히 **고객이 글로 적어준 것뿐**이다. 그래서 단어 목록을
  좁히지 않고 넓게 열어두었다. 첫 실전 실행의 `confirm_shots.json` 에
  찍히는 원문으로 좁혀라. 그 전까지 CI 초록불은 "우리 분류기가 우리
  픽스처와 일치한다" 는 뜻일 뿐이라는 것을 잊지 마라.

  **게시 직전에 두 ZIP 을 다시 통째로 훑어 재확인했다**(2026-08-25 10:35Z):
  `page_source/` 14장, `record/bodies/` 전부, `record/network.json` 373건의
  응답 본문, `record/wanted/`, `run.log` 까지 `grep -r` 로 봤다.
  `예약시간전` 0건, `정원초과` 0건, **`정원` 이라는 두 글자조차 0건.**
  우리 CI 픽스처(`ci/fixture_server.py`)는 그 문구를 찍지만 그건 우리가 쓴
  것이므로 증거가 아니다. 그것을 서버 원문의 근거로 쓰지 말 것.

`제품 동작 검증 13개` 는 다른 질문이다: "사이트에 그 요소가 있는가" 가 아니라
"우리 코드가 그것을 실제로 맞히는가". 13/13 통과.

### [확인] 이후 서버 답이 도착하는 자리 (게시 직전에 추가로 못박음)

캡처된 `OccasionTimeMainSlPL.html` 의 `fnSave` 콜백이 근거다. 서버 답은
페이지 본문이 아니라 **alert2 껍데기**로 온다.

```js
customAjax.ajax({ type:"POST", url:"/icms/occasion/InsertOcreqst.html",
  data: $('#pfrm').serializeArray(),
  success: function(data){
    if (data.returnval == "success") {
      icmsLayerPopup.alert2({ contents : data.returnmsg }, function(){
        NetFunnel_Complete(); window.location.href = "/?menuno=245"; });
    } else { icmsLayerPopup.alert2({ contents : data.returnmsg }, ... ); }
```

그리고 `layerpopup.js` 의 `open("type-alert2")` 가 하는 일은 두 줄뿐이다.

```js
$("#layer-alert-popup-contents2").html(param.contents.nl2br());
$("#layer-alert-popup2").show();
```

- 그 껍데기도 확인창처럼 페이지에 **두 벌**이다(감사 항목으로 못박음).
  jQuery `#id` 는 앞의 한 벌만 건드리므로 우리 쪽은 id 를 믿지 말고
  **보이는 것**을 읽어야 한다. `_JS_READ_NOTICE` 가 그렇게 한다.
- 성공하면 `/?menuno=245`(예약내역) 로 이동한다. 이것도 성공 신호다.
- 실물에서 alert2 를 열고 `_JS_READ_NOTICE` → `classify` 까지 돌리는 검증이
  감사와 `tests/test_real_capture.py::test_the_server_answer_is_read_from_the_alert2_shell`
  에 있다. **문구**는 자리표시자다. 서버 원문은 여전히 미확인(위 참고).

### 픽스처를 다룰 때 반드시 지킬 것

- **`file://` 로 띄우지 마라.** 크롬은 file 문서마다 오리진을 따로 줘서 CSS 의
  `cssRules` 접근이 막히고, 실제로 스타일이 안 붙은 것처럼 보인다. 그러면
  `.popup_wrap{display:none}` 이 죽어 확인창 사본 판정이 뒤집힌다.
  `ci/real_fixture_server.py` 로 http 로 띄운다.
- 크롬 플래그 `--host-resolver-rules=MAP * ~NOTFOUND` 만 쓰면 **127.0.0.1 까지
  막힌다.** 반드시 `, EXCLUDE 127.0.0.1` 을 붙인다.
- CSS 를 손대지 마라(예전에 `url(...)` 을 `data:,` 로 바꿨다가 CSS 가 깨져
  같은 증상이 났다). 바깥 네트워크는 위 플래그로 막으면 된다.
- `<link>` 순서를 원본대로 유지한다. 알파벳순으로 붙이면 캐스케이드가 달라진다.

## v1.0.8 (2026-08-26): 인계 모드 + 가상대기열 + 재준비 금지

**이 판은 하나의 사고에서 나왔다. 고객이 그날 예약을 놓쳤고, 원인은 우리 코드였다.**

### 무슨 일이 있었나 (고객 진단 ZIP, 전부 실측)

```
artifacts/private/05788f12-b025-48ba-bb01-7c45121013d8/
  1787702295153-aisarang-reservation-2309842-20260826-085814.zip
  523,608 B  v1.0.7  Windows 10 19045  mode=gui  08:36:37 ~ 08:58:14 KST
```

`run.log` 는 08:56:11 부터 08:58:08 까지 **똑같은 8단계를 네 번** 반복한다.
매 회차 마지막 세 줄이 이것이다.

```
[08:57:32] [예약하기] 를 눌렀습니다 (#timecareConfirm).
[08:57:40] 준비 실패(no_modal): 예약 확인창이 열리지 않았습니다.
[08:57:40] 20초 뒤 다시 준비합니다. (정각까지 140초)
```

**확인창 자리에 무엇이 있었는지는 캡처에 그대로 남아 있다.**
`page_source/0005_modal_not_open.html` 의 꼬리(원문 그대로):

```html
<div id="NetFunnel_Loading_Popup" style="display: block; ... visibility: visible; z-index: 32002;">
  <b>시간제 보육 예약 <span style="color:#013dc1"> 대기 중</span>입니다.</b>
  <b>예상대기시간 : <span id="NetFunnel_Loading_Popup_TimeLeft">2분  10초 </span></b>
  <div id="Progress_Print">6 % (5/77) - 130.931468-2****** sec</div>
  현재 앞에 <b><span id="NetFunnel_Loading_Popup_Count">72</span></b> 명,
  뒤에 <b><span id="NetFunnel_Loading_Popup_NextCnt">26</span></b> 명의 대기자가 있습니다.
  <div>현재 접속 사용자가 많아 대기 중이며, 잠시만 기다리시면 </div>
  <div>예약이 완료됩니다.</div>
  <div>*<b><span style="color: red;">시간당 인원이 초과</span>될 경우 예약이 불가할 수 있습니다.</b></div>
  <b>※ 재접속하시면 대기시간이 더 길어집니다. <span id="NetFunnel_Countdown_Stop">[중지]</span></b>
</div>
<div id="mpopup_bg" style="... display: block;">   <!-- 딤 -->
<div id="pop_iframe" style="... display: block;">
```

`network_modal_not_open.json` 이 뒷받침한다. [예약하기] 직후
`nf.childcare.go.kr:8443/ts.wseq?opcode=5101`(대기열 진입) → `opcode=5002` 폴링이
줄줄이 찍혀 있다. **넷퍼널은 켜져 있었다.** (NOTES 예전 판이 "목록 화면에서는
주석 처리돼 있다" 고 적어둔 것과 모순되지 않는다. 목록 화면이 아니라
[예약하기] 시점에 XHR 로 `netfunnel-pcms.js` / `netfunnel-skin.js` 를 불러온다.)

그리고 레이어가 직접 적어 놓은 마지막 줄이 이 판의 전부다.

> ※ 재접속하시면 대기시간이 더 길어집니다.

v1.0.7 은 정확히 그 짓을 세 번 했다. 세 캡처의 순번이 그 대가다.

| 회차 | 캡처 | 앞에 선 사람 | 뒤에 | 예상 대기 | Progress |
|---|---|---|---|---|---|
| 1 | `0005_modal_not_open.html` | **72명** | 26 | 2분 10초 | 6 % (5/77) |
| 2 | `0010_modal_not_open.html` | **138명** | 26 | 3분 50초 | 3 % (5/143) |
| 3 | `0015_modal_not_open.html` | **177명** | 18 | 4분 32초 | 3 % (6/183) |

고객 원문:
> "아 이게 4분전으로 셋팅하니까 이미 앞에 대기자가 많아서 그때부터 오류가 생깁니다."
> "예약이 원래대로 안되니까 프로그램은 다시 처음부터 다시 아동선택을 하게 되고
>  그게 반복되서 오늘은 결국 못했네요"
> "제가 아동선택부터 시간선택까지 모두 끝내놓으면 프로그램은 확인만 누르는
>  방식을 변경 요청드립니다."

### 1) 인계 모드 (`aisarang/handover.py`, 이제 **기본 모드**)

사람이 아동~[예약하기] 까지 손으로 끝내 확인창을 띄워 두면, 프로그램은
**그 확인창의 [확인] 만** 정각에 맞춰 누른다. 도착 기준 조준, '예약시간전'
재발사, '정원초과' 즉시 중단은 자동 모드와 같은 코드다.

**하지 않는 것이 이 모드의 정의다.** 화면 이동, 검색, 센터 열기, 아동/반/시간
선택, 칸 클릭, [추가], 체크, [예약하기] 가 **소스에 존재하지 않는다.**
`tests/test_handover.py::test_handover_has_no_way_to_touch_the_page_except_the_final_confirm`
이 `ast` 로 파싱해서 (문서화 문자열 제외) `.click(` / `.submit(` / `send_keys` /
`ActionChains` / `dispatchEvent` / `driver.get(` / `booking.prepare` /
`booking.open_modal` / `booking.press_*` / `booking.redrive_confirm` 이
하나도 없다는 것을 못박는다. 누가 "확인창이 닫혔으니 [예약하기] 한 번만 다시
눌러주자" 를 넣으면 테스트가 깨진다. **그 한 번이 72명을 177명으로 만들었다.**

유일한 발사 경로는 `booking.fire_confirm(driver)` 한 줄이다. 조준(`_JS_ARM`,
= `window.__aisarang_fire` 를 만드는 일)조차 `booking.py` 가 한다. 그래서
`handover.py` 안에는 누를 수 있는 자바스크립트가 한 조각도 없다.

예외가 딱 하나 있다: 시작 직후 `_handover_open_once()` 가 예약 화면까지 한 번
열어준다. 그것도 **먼저 화면을 읽어서** 확인창이 이미 떠 있거나 선택표 체크가
켜져 있거나 예약 화면 위라면 **열지 않는다.** 고객이 8시 58분에 프로그램을
다시 켰을 때 자기가 만들어 둔 것을 우리가 날리면 안 되기 때문이다.

### 2) 안전 불변식을 살아 있는 화면에서 다시 만든다

이것이 이번 판의 진짜 설계 변경이다.

`Prepared.ready()` 는 **우리가 우리 클릭으로 세운 플래그**를 본다.
`cell_selected` 는 `click_cell` 안에서만 참이 되고 그 뒤로 **한 번도 다시
계산되지 않는다.** 사람이 손으로 만든 화면에서는 영원히 거짓이다. 그대로
두면 인계 모드는 구조적으로 발사할 수 없다.

`handover.LiveState.ready()` 는 매번 `_JS_HANDOVER_STATE` 한 번으로 페이지에서
다시 읽는다.

1. `modal`: 보이는 `#layer-confirm-popup2` 껍데기가 있고 본문이 비어 있지 않다
2. `confirm`: 그 안의 `#layer-confirm-popup-confirm2` 가 보인다
3. `asks`: 본문이 예약 질문이다 (`...하시겠습니까`)
4. `ticked > 0`: `#INFOQUALF` 의 체크박스가 **지금** 켜져 있다
5. `armed`: `booking._JS_ARM` 이 그 버튼을 실제로 잡았다

하나라도 거짓이면 누르지 않고 이유를 한국어로 크게 남긴다(`blockers()`).
**취소가 센터 전화(1661-9361)로만 되므로 잘못된 예약은 놓친 예약보다 나쁘다.**

> 함정: 체크박스는 `page_source` 로 알 수 없다. `click` 은 attribute 가 아니라
> **property** 를 바꾸고 `page_source` 는 attribute 만 직렬화한다. 그래서
> `ci/fixtures/real/modal_open.html` 에는 고객이 켠 체크가 남아 있지 않다.
> 실행 중에는 살아 있는 DOM 의 `.checked` 를 읽으므로 문제가 없고, 테스트에서는
> `b.checked = true` 로 사람의 클릭을 재현한다. 이 사실을 모르고 픽스처만
> 보면 "체크가 꺼져 있는데 왜 발사하지" 로 잘못 판단하게 된다.

### 3) 대기열을 실패가 아니라 상태로 다룬다

`booking._JS_QUEUE` / `queue_info()` / `queue_line()` 이 실물 id
(`#NetFunnel_Loading_Popup`, `_Count`, `_NextCnt`, `_TimeLeft`, `#Progress_Print`)
로 순번을 읽는다. 스킨이 바뀔 때를 위한 글자 경로도 둔다.

- `wait_modal()` 이 (본문, 대기열을 봤는가) 튜플을 돌려준다. 대기열에 서 있으면
  `deadline_local`(정각 5초 전)까지 기다린다. 대기열이 없으면 예전처럼 8초.
- `open_modal()` 의 실패 코드가 `no_modal` / **`no_modal_queue`** 로 갈린다.
- `automation.handle_netfunnel()` 을 고쳤다. **v1.0.7 은
  `"NetFunnel" not in driver.page_source` 로 판정했는데, [예약하기] 를 누르면
  사이트가 `ts.wseq` 스크립트 태그를 문서에 남기므로 대기열이 지나간 뒤에도
  그 문자열이 계속 잡혔다.** 이제 보이는 레이어로만 판정한다.
  `tests/test_handover.py::test_handle_netfunnel_no_longer_trips_on_the_leftover_script_tag`
  가 그 태그를 실제로 심어놓고 확인한다.

### 4) [예약하기] 를 누른 뒤에는 준비를 다시 하지 않는다 (자동 모드)

`Runner.PRESSED_RESERVE = ("no_modal", "no_modal_queue", "not_armed")`.
이 코드가 나오면 `_prepare_with_retries` 는 **즉시 재준비를 포기하고**
`_watch_for_late_modal()` 로 넘어간다. 그 함수는 누르지 않는다. 1초마다
확인창이 열렸는지 읽고, 열리면 그 자리에서 조준해 성공으로 바꾼다.
대기열이 보이면 순번을 상태줄에 계속 적는다.

`_hold_modal()` 에서도 같은 규칙이다. 예전에는 `redrive_confirm` 이 실패하면
`_prepare_with_retries` 를 다시 불렀다(= 검색 화면부터). 그 경로를 지웠다.

누르기 **전** 단계의 실패(`guard_cell` / `guard_row` / `no_reserve_button` /
`no_capacity` / `cell_not_selected` / `row_not_ticked`)는 예전처럼 재시도한다.
그때는 대기열 표를 쥐고 있지 않으므로 잃을 것이 없다.

`tests/test_handover.py::test_auto_mode_never_re_prepares_once_reserve_was_pressed`
가 호출 수로 못박는다: `prepare` 1회, `open_modal` 1회, `_watch_for_late_modal` 1회.

### 5) 화면 (고객이 사진으로 찍어 보내는 그 줄)

- 카드 "1. 실행 방식" 이 새로 생겼다. 기본이 인계 모드이고, 각 방식이 무엇을
  하는지 카드 안에 한국어로 적혀 있다. 나머지 카드 번호가 하나씩 밀렸다.
- 실행하면 결과 표시줄 **위에** 어두운 상태판이 펼쳐진다(`App.set_state`).
  ```
  인계 모드 ([확인] 만 누름) | 확인창 감지됨 | 선택표 체크 켜짐 | [확인] 까지 00:41
  확인창 감지됨 · 선택표 체크 켜짐 · 정각에 [확인] 을 누릅니다
  ```
  칸 색: 초록 = 됨, 빨강 = 안 됨, 주황 = 대기열.
- 폴링 주기 `handover.POLL_SECONDS = 0.5`. 고객이 [예약하기] 를 누르면
  0.5초 안에 "확인창 감지됨" 으로 바뀐다.
- 정각 90초 전(`Runner.NAG_SECONDS`)에도 준비가 안 돼 있으면 크게 알린다.

### 실측 증거 (이 서버, 진짜 크롬, 실물 캡처)

```
python main.py --handovertest
HANDOVERTEST page=modal_open.html ticked=True  modal=True  ... ready=True  fired=True
HANDOVERTEST page=modal_open.html ticked=False modal=True  ... ready=False fired=False
   blockers=선택표 행의 체크가 켜져 있지 않습니다
HANDOVERTEST page=netfunnel_waiting.html ticked=True modal=False queue=True ready=False fired=False
   queue=가상대기열 대기 중 (앞에 72명, 뒤에 26명, 예상 2분 10초)
HANDOVERTEST page=grid_selected_row_added.html ticked=True modal=False ready=False fired=False
HANDOVERTEST fired=1/4 (기대: 1)
HANDOVERTEST OK
```

감사: `의존성 58개: 확인 56 / 영상복원본만 1 / 미확인 1`,
`제품 동작 검증 19개 중 19개 통과`.

### 새 픽스처

```
ci/fixtures/real/netfunnel_waiting.html    2026-08-26 08:57 의 진짜 대기열 레이어
```

`python ci/build_netfunnel_fixture.py <ZIP경로>` 로 다시 만든다.
만드는 방식이 중요하다: **오늘 캡처의 페이지 본문에는 아동 실명이 평문으로
4번 남아 있다.** 그래서 본문은 쓰지 않고, 이미 개인정보가 지워진
`grid_selected_row_added.html` 에 **대기열 레이어 조각만** 붙인다.
그 조각에는 개인정보 모양이 하나도 없고(스크립트가 검사하고 실패하면 종료),
`tests/test_handover.py::test_the_netfunnel_fixture_carries_no_personal_data`
가 커밋된 결과물을 한 번 더 본다.

## v1.0.9 (2026-08-27): the aim moved from before the hour to after it

Written in English on purpose (house rule for engineer notes). The Korean strings
quoted below are verbatim server/UI text and must not be translated.

### What happened: the first real 09:00 firing of handover mode failed

Customer evidence ZIP (their own PC, Windows 10 10.0.19045, frozen v1.0.8):
`/home/bfdev/neoworks/apps/gateway/artifacts/private/05788f12-b025-48ba-bb01-7c45121013d8/1787788821324-aisarang-reservation-2309842-20260827-090021.zip`
(a second ZIP `…-090512.zip` is the same run's shutdown dump, identical except the
two upload lines at the tail).

```
[08:38:51] [확인] 목표 도착: 정각 300ms 전 / 편도 추정 364ms 만큼 미리 발사
[08:59:24] 정각 90초 전 ... 마지막 값: 보정 -1319ms (오차 ±435ms, 최소왕복 740ms)
[08:59:59] 발사 직전 점검: 확인창 감지됨 · 선택표 체크 켜짐
[09:00:00] [확인] 1발째 · 도착 추정 정각 -296ms
           · 서버: 알림 아직 예약 가능한 시간이 아닙니다. 확인 [too_early]
[09:00:01] 선택표 체크 켜짐 · 확인창 없음 ([예약하기] 를 눌러주세요)
[09:00:01] [확인] 을 누를 수 없는 상태입니다: 예약 확인창이 화면에 없습니다
```

Everything about the run was healthy: the customer had the confirm dialog open and
held from 08:39:49, the tick was on, the preflight passed, and the shot went out at
the intended instant. **We aimed at the wrong instant.** `arrival_lead_ms = 300`
meant "arrive 300 ms BEFORE the hour", and the server discards anything that lands
before its own 09:00:00.000. That was a guaranteed loss, not bad luck.

### The site's own script, captured (this is now the reference)

`page_source/0002_handover_after.html` in that ZIP contains the real inline JS.
Three facts come straight out of it and they drive everything below.

```js
<a href="javascript:;" class="btn h50" id="timecareConfirm" onclick="fnSave();">예약하기</a>

var fnSave = function () {
    ...INFOQUALF row count check / frm.resYn check / first-time-use notice...
    NetFunnel_Action({action_id: "mcis_0"}, function(ev,ret){ insertOcreqst(); });   // 대기열 진입
}
function insertOcreqst () {
    if(!timeChk) { alert("이용시간을 선택해 주시기 바랍니다.") -> NetFunnel_Complete(); return; }
    if(!dayChk)  { alert("이용정보를 선택해 주시기 바랍니다.") -> NetFunnel_Complete(); return; }
    ...builds confirmText, incl. the 60-hour warning...
    icmsLayerPopup.confirm2({title:"예약", contents: confirmText}, function(res) {
        frm.resgb.value = "R"; fnLoddingStart();
        customAjax.ajax({ type:"POST", url:"/icms/occasion/InsertOcreqst.html",
            data: $('#pfrm').serializeArray(),
            success: function(data){
                frm.resYn.value = "N"; fnLoddingEnd();
                if (data.returnval == "success") {
                    alert2(data.returnmsg) -> NetFunnel_Complete(); location.href = "/?menuno=245";
                } else {
                    alert2(data.returnmsg) -> NetFunnel_Complete();     // no navigation
                }
            },
            error: function(res){ frm.resYn.value = "N"; NetFunnel_Complete(); fnLoddingEnd(); }
        });
    });
}
```

1. **The confirm dialog can only be opened by `fnSave()`.** There is no other entry
   point. Once our 확인 click consumes it, the ONLY way back is re-pressing 예약하기.
2. **`fnSave()` enters the NetFunnel queue immediately** (`NetFunnel_Action`), before
   the dialog exists. That is exactly what wrecked 2026-08-26 (72 -> 138 -> 177).
3. **A failed submit does not navigate.** Only `returnval == "success"` sends the
   browser to `/?menuno=245`. So after a rejection the child/date/time/tick are all
   still on the page: re-pressing is a re-click, not a re-preparation.

There is also a fourth fact worth knowing, and it is a warning:
**`frm.resYn.value` is never set to `"Y"` anywhere in this script.** The
`if(frm.resYn.value == "Y") alert("처리중입니다.")` guard at the top of `fnSave` is
dead code in practice. So **the site has no client-side duplicate-submit guard on
this path.** See "why we do NOT burst-fire" below.

### 1) The arrival target: -300 ms  ->  +685 ms (measured, not rounded)

Old: `config.DEFAULT_SETTINGS["arrival_lead_ms"] = 300`, target = `open_epoch - 0.300`.
New: `arrival_after_ms = 0` (auto), target = `open_epoch + clock.safe_arrival_after()`.

```
aim = clamp( uncertainty/2 + arrival_safety_ms , ARRIVAL_MIN_AFTER_MS , ARRIVAL_MAX_AFTER_MS )
              350 ms                                                     1200 ms
```

`uncertainty` is the residual width of the offset interval the Date-header
intersection leaves; half of it is our one-sided clock error. Measured on the
customer's PC on 2026-08-27, four syncs: **868.1 / 843.0 / 847.3 / 869.2 ms**, so a
one-sided error of **434.0 / 421.5 / 423.6 / 434.6 ms**. Worst = 434.6 ms.

`arrival_safety_ms` defaults to 250 ms and is itself built from that day's numbers:

| component | value | where it comes from |
|---|---|---|
| RTT jitter, one-way | 146.5 ms | (worst 994.6 - best 701.6) / 2, `clock_sync.json` |
| Selenium -> Chrome -> wire dispatch | ~50 ms | budget, not separately measured |
| server's pre-`Date`-stamp processing | ~50 ms | budget, not separately measured |
| **total** | **~250 ms** | |

So with 2026-08-27's own numbers: **434.6 + 250 = 684.6 ms after the hour**, versus
the 300 ms *before* it that we shipped. A 985 ms swing. It is not a constant: on the
CI runner (uncertainty ~133 ms) the same formula asks for 316.6 ms and gets clamped
up to the 350 ms floor.

**Why err late, explicitly.** The two failure directions are not symmetric:

- Too early is a **certain** rejection. Proven 1/1 on the only real firing we have.
  The server does not "maybe" accept an early request; it discards it.
- Too late risks 정원초과. **Never once observed** in any capture (08-25 373 requests,
  08-26, 08-27). We have never arrived late, so we have zero evidence that ~0.7 s of
  lateness costs the slot.
- And when the crowd is big enough for 0.7 s to matter, NetFunnel is on, which
  serializes everyone anyway and makes sub-second aim irrelevant (08-26: 72 ahead).
- Asymmetric recovery: too-early now has a bounded recovery (below). Too-late has
  none, but too-late is also the direction with no observed cost.

Note this is the *aim*, not the achieved arrival. The estimator's own error is what
the margin is paying for.

**A dead-setting trap, handled.** The customer's `%APPDATA%/AisarangReservation/settings.json`
still contains `arrival_lead_ms: 300`. `config._OBSOLETE` drops that key (and
`prefire_ms`) on load instead of renaming it, so the old value cannot come back.
`tests/test_arrival.py::test_the_dead_setting_cannot_come_back_from_an_old_settings_file`
pins that. **If you ever rename this setting again, do the same thing.**

### 2) The too_early recovery (`handover._Reopen`)

One shot used to be all we got. Now, and ONLY after a `too_early` classification,
the program closes the result alert and re-presses 예약하기 once to re-open the
confirm dialog, then fires again. Eight conditions, all required:

1. the last fired shot classified exactly `too_early` (not full, not not_bookable,
   not unknown, not fail, not ok)
2. we actually fired at least once (a missing dialog with no prior shot is just
   "the customer has not pressed 예약하기 yet" and we never press for them)
3. the confirm dialog is currently absent (if it is open, just re-fire)
4. still on the reserve page AND the slot row tick is still on
5. no NetFunnel queue layer visible
6. `open_epoch <= server_now() < open_epoch + reopen_seconds` (default 15 s)
7. under the cap (`reopen_max`, default 2)
8. not locked

Locking is the important one. `_Reopen.lock()` is permanent and fires on: any
non-`too_early` outcome, `#timecareConfirm` not found, and **a queue layer appearing
after our re-press**. Point 8 + point 5 together are what keeps 2026-08-26 from
repeating. After a re-press we wait the queue out, we never press again.

Each re-press also requires a *fresh* `too_early`: `_Reopen.do()` clears `last_code`,
so two presses need two rejections.

The recovery presses exactly two things, both verified against the real captured
markup: the alert's own close anchor (`[id^=layer-popup-close]`, which is what makes
the site run `NetFunnel_Complete()` and hand the queue ticket back) and
`#timecareConfirm`. `booking.close_result_alert` explicitly skips any shell whose id
or class says confirm, so it can never click 확인 on the reservation dialog.

`booking.repress_reserve_button` is deliberately **stricter** than `press_reserve`:
no text-matching fallback, `#timecareConfirm` or nothing.

### 3) Why we do NOT burst-fire several 확인 clicks

Considered and rejected. RTT is ~740 ms, so 3 clicks 90 ms apart would all be in
flight before the first answer returns. If two of them succeed we create **two real
reservations**, and cancellation on this site is phone-only. And the captured script
shows there is **no client-side duplicate guard** (`resYn` is never set to `"Y"`), so
"the site will reject the second one" is not supported by evidence. We have no
server-side dedupe evidence either way. Not shipped. Do not ship it later without a
capture proving the server rejects a duplicate.

### 4) The `too_early` wording is now evidence-backed. 정원초과 still is not.

Real server text, first ever observed, from the site's own alert2 layer:

```html
<div class="popup_wrap s_size wp400 type-alert2" id="layer-alert-popup2">
  <h5>알림</h5>
  <p class="f_18" id="layer-alert-popup-contents2">아직 예약 가능한 시간이 아닙니다.</p>
  <a href="#none" class="btn" id="layer-popup-close2">확인</a>
```

This is `data.returnmsg` from `InsertOcreqst.html`. It is now `booking.TOO_EARLY_REAL`
and every fixture and test uses that constant. `ci/fixtures/reserve_page.html` used to
print our invented `'예약시간전'`, which made the classifier tests circular; it now
prints the real string.

**Watch this one-character gap. It is a live hazard:**

```
too_early     "아직 예약 가능한 시간이 아닙니다."      <- server returnmsg (real)
not_bookable  "예약 가능 시간이 아닙니다."             <- site selectDay2() (real)
```

`가능한` vs `가능`. They do not substring-match each other, so ordering alone happens
to work, but that is luck. `booking._RE_NOT_YET` now promotes any `아직 …시간이
아닙니다` to `too_early` **before** the NOT_BOOKABLE list is consulted. Keep the word
lists wide, keep that regex first.

정원초과 remains **customer-report only**. Zero occurrences in every capture we have,
because we have never arrived late. `ci/selector_audit.py` item 9 is now split into a
CONFIRMED row (too_early) and an UNCONF row (정원초과). When a real 정원초과 lands,
fix `FULL_WORDS` from the capture and move that row.

### 5) What else the ZIP told us

- **No NetFunnel queue was engaged today.** Whole-capture NetFunnel traffic was:
  `opcode=5101` at page render (23:39:49Z, the env check), then after our POST an
  `opcode=5004` complete carrying a key. There is **no `opcode=5002`** anywhere, i.e.
  no queue ticket was ever issued, and `detail_handoverState.queue` is `false`.
  That is why the aim mattered at all today: with a queue, position dominates.
- **Exactly one `InsertOcreqst.html` POST** in the whole capture (index 296/300 of
  `network_handover_after.json`), status 200. One click, one submit. No duplicate.
- **`NetFunnel_Complete` ran at 09:00:04.2** (the 5004 cache-buster is
  `1787788804211`), ~4 s after the POST, i.e. when the alert was closed. Confirms the
  release path and is why the recovery closes the alert before re-pressing.
- **The real arrival skew is NOT measurable from this capture.** Our -296 ms figure is
  our own estimate. `clock.note_too_early` only learns when the estimate is >= 0
  ("we thought we were late and the server says we were early"). At -296 ms the
  server's `too_early` is exactly what we predicted, so it carries no information and
  `detail_clockCorrectionMs` is `0.0`. A `too_early` at a POSITIVE estimated arrival
  would be the measurement we still lack. With the new aim we may finally get one:
  if it happens, the correction machinery is already wired.
- `meta.json`: `serverOffsetMs -1319.3`, `oneWayMs 369.8`, `clockResyncs 3`,
  `clockAgeSec 357`, `result "fail"`, `detail_reason "exhausted"`.
- The confirm dialog body was the 60-hour voucher warning ending in `예약하시겠습니까?`,
  matched by `modalHow=layer-confirm-popup2` / `confirmId=layer-confirm-popup-confirm2`.
  The v1.0.7/1.0.8 selector work is confirmed correct on a live 09:00 screen.

### 6) The ast test was widened deliberately, not deleted

`test_handover_has_no_way_to_touch_the_page_except_the_final_confirm` is gone and
replaced by two tests:

- `test_handover_touches_the_page_only_through_three_named_calls` walks `handover.py`
  with `ast`, collects every `booking.<attr>` reference, subtracts a read-only
  whitelist, and asserts the remainder is **exactly**
  `{fire_confirm, repress_reserve_button, close_result_alert}`. A fourth page-touching
  call breaks the build.
- `test_the_reserve_button_is_reachable_only_from_the_too_early_gate` asserts
  `repress_reserve_button` and `close_result_alert` are called only from `_Reopen.do`,
  that `fire_confirm` is called only from `fire`, and that inside `burst` there is
  exactly one `.do(` call and exactly one `.allowed(` guard.

The old FORBIDDEN token list is still applied on top (no `.click(`, no `driver.get(`,
no `booking.press_`, no `booking.prepare`, ...).

### New fixture

`ci/fixtures/real/too_early_alert.html`, built by `ci/build_too_early_fixture.py`
from that ZIP: the sanitised `grid_selected_row_added.html` base with its **empty**
alert shell swapped for the **filled** one from the 09:00 capture, forced visible.
Same PII-shape gate as the netfunnel builder. The page carries the real 예약하기
button with its real `onclick="fnSave();"`; the site's own scripts are stripped from
fixtures (they would call NetFunnel and ajax), so tests install a counter on
`window.fnSave` and count that the real button's real handler name was invoked once.

```bash
python ci/build_too_early_fixture.py [ZIP]     # regenerate
python main.py --handovertest                  # expects: fired=1/5, HANDOVERTEST OK
```

## v1.0.10 (2026-09-01): 늦는 것도 지는 것이었다

Written in English-first house style; the Korean strings quoted below are verbatim
server/UI text and must not be translated.

### What happened: 2026-09-01 09:00:00, aimed +685ms, lost the slot

```
[08:59:59] 조준 확정: 도착 목표 정각 +685ms (시각 오차 ±435ms + 여유 250ms)
[09:00:02] [확인] 1발째 · 도착 추정 정각 +686ms
           · 서버: 알림 1건 예약 중 1건 예약이 선예약으로 인해 예약되지 않았습니다. 확인 [unknown]
[09:00:10] 사이트가 가상대기열을 띄웠습니다 ... (앞에 319명, 뒤에 1명, 예상 1분 10초)
```

`…-20260901-090020.zip`, v1.0.9 frozen, targetDate 20260915, serverOffsetMs -655.6.

### 1) What "선예약" actually means: PROVEN "someone else got it"

The verdict is **(a) proven "someone else got it"**, and it is NOT a duplicate of a
booking the customer already held. The proof does not rest on reading the Korean.

**The response body is NOT in the capture.** `requests/0000.json` and
`requests/0001.json` hold only the two public `site.py` lookups
(`NurseryMapSidoList` / `NurseryMapGuGunList`). `network_*.json` records url +
status + mime only, never bodies. So the `InsertOcreqst.html` JSON (`54164.737`,
`application/json`, 200) is gone. There is no numeric result code to read on any of
the four days. That gap is exactly what TASK 5 below closes.

**The page's own JS does not name the branches either.** From
`page_source/0002_handover_after.html`, `insertOcreqst()` does:

```js
success: function(data){
    if (data.returnval == "success") { alert2(data.returnmsg); location.href="/?menuno=245"; }
    else                             { alert2(data.returnmsg); }   // no navigation
}
```

`returnval` is a two-way flag and `returnmsg` is server-composed prose. The client
has **no** outcome vocabulary at all; there are no sibling branches to read. Anyone
looking for the mapping in the page JS will not find it. Stop looking.

**What does settle it is the site's own capacity counter.** `selectDay2()` reads the
day x hour cell text as remaining seats:

```js
var tValue = $("#tm_" + tt + "_" + row).text();
if (tValue == "X")      { alert("예약 가능 시간이 아닙니다."); return; }
else if (tValue == "0") { wait_gb = "Y"; ... }      // 0 = no seat, waitlist only
else                    { ... }                      // >0 = that many seats free
```

and the markup carries it plainly: `<i class="count" title="이용가능">2</i>`.
Extracted from the captures:

| capture | date row | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 |
|---|---|---|---|---|---|---|---|---|---|---|
| 09-01 08:59 preflight | **20260915** (target) | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| 09-01 08:59 preflight | 20260914 (won 08-31) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| 08-31 08:59 preflight | **20260914** (target) | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |

Four facts, and together they close it:

1. **Capacity is 2 per hour**, and a freshly opened day starts at 2/2 free. Every
   capture agrees.
2. At 08:59 on 09-01 the target day 20260915 showed **2 free on every hour**. Nothing
   was pre-claimed.
3. **Nobody, including our customer, can hold a booking for 20260915 before
   09:00:00.000.** Proven 1/1 on 2026-08-27: a submit landing at -296ms got
   `아직 예약 가능한 시간이 아닙니다.` The server discards everything before the hour.
   The customer also did not book by hand that day.
4. Therefore the only reservations that can exist for that slot at 09:00:00.686 are
   ones **other users** created inside those 686 ms. That is what 선예약 refers to.

Corroboration, same capture: 20260914 (which we won at +793ms on 08-31) reads 0 on
hours 09-16 and **1** on hour 17. Our booking took one of the two seats on 09-16;
somebody else took the other. Both seats of a fresh day are gone within a day. And on
09-01 there were **319 people** in the NetFunnel queue at 09:00:10 for 2 seats.

**So the aiming asymmetry does invert.** We had reasoned "early is a certain loss,
late is probably fine because we have never seen a capacity rejection". We had never
seen one because we were reading it as `unknown`. +686ms is not good enough on a
contested day. Both directions lose now; early still loses *certainly*, so the aim
stays positive but must be much smaller.

Honest limit: this is a temporal-impossibility + capacity argument, not a result
code. With v1.0.10 persisting the body (TASK 5), the next occurrence gives the code.

### 2) The clock: ±435ms -> ±76ms, and it is a measurement, not a shaved constant

The formula is untouched:

```
aim = clamp( uncertainty/2 + ARRIVAL_SAFETY_MS , 350 , 1200 )      ARRIVAL_SAFETY_MS = 250
```

`ARRIVAL_SAFETY_MS` is still **250**. Nothing was shaved. The dominant term
(`uncertainty/2`, 435ms on 09-01) got smaller because the measurement got better.

**The find: childcare.go.kr publishes a millisecond server clock.** It runs on
eGovFrame, whose session filter stamps every dynamic response:

```
Date: Tue, 01 Sep 2026 00:15:08 GMT
Set-Cookie: ... egovExpireSessionTime=1788225308489; ... egovLatestServerTime=1788221708489; ...
```

`1788221708489` = 00:15:08.489, the same second the `Date` header names, to the ms.
That kills the 1-second quantisation outright. `clock._parse_server_ms`.

**It is stamped at request ENTRY, not at response generation.** Measured on three
endpoints whose rendering cost differs by 6x, `cookie - t0` is constant:

| endpoint | rtt | cookie - t0 | t1 - cookie |
|---|---|---|---|
| `/icms/occasion/SelectTotalTime.html` | 150ms | **128ms** | 23ms |
| `/?menuno=245` | 369ms | **128ms** | 241ms |
| `/?menuno=1` | 980ms | **127ms** | 854ms |

That matters twice over. First, the cookie time IS the arrival instant we are trying
to aim at. Second, the 780-1060ms "rtt" v1.0.9 measured on `/?menuno=1` was almost
entirely **JSP rendering after arrival**, not network. So we can probe a cheap
endpoint and get a far tighter interval for free.

`config.CLOCK_PROBE_PATH = "/icms/occasion/SelectTotalTime.html"`: read-only, same
`/icms/occasion/` app tier as the submit, ms cookie, 150ms rtt.
**`InsertOcreqst.html` has the same properties and must NEVER be probed.** A test
asserts the string does not appear in `clock.py`.

Per-sample interval, which is the whole change:

```
Date header   offset ∈ [S - t1, S + 1 - t0]     width = 1s + rtt
ms cookie     offset ∈ [S - t1, S     - t0]     width = rtt
```

Measured live from this server, 3 runs each, old shipped config vs new shipped config:

```
v1.0.9   Date + /?menuno=1,   12 samples : 1075.4 / 1092.9 / 1113.3 ms  (half ±537-557ms)
v1.0.10  ms   + probe path,   40 samples :  123.4 /  268.5 /  270.9 ms  (half ± 62-135ms)
                                            mean 1093.9 -> 220.9 ms  = 4.95x tighter
```

(The customer's own line measured 869ms on the old path; this host is off-shore so
its absolute numbers are worse than theirs in both columns. The ratio is the point.)

Sanity: the two estimators are consistent. New offset +39.2 ±61.7 sits inside old
-367.6 ±537.7. The old midpoint was biased ~400ms low because it assumed symmetric
legs on a page whose response leg is 854ms; that bias was partly cancelled by
`one_way = rtt/2` being over-estimated by a similar amount. Luck, not design. Gone now.

Cross-checked that it is one clock, not per-node clocks. Four endpoints, same window:

```
/icms/occasion/SelectTotalTime.html  [ -22.6, +250.3]  unc 272.9ms
/?menuno=245                         [-214.2, +125.7]  unc 339.9ms
/?menuno=1                           [-805.7, +125.6]  unc 931.2ms
/icms/nursery/NurseryMapSidoList     [ -56.1, +125.6]  unc 181.7ms
all 6 pairs overlap; all share hi ~ +125.6ms  (= min request leg, identical everywhere)
```

**Resulting aim.** With half-uncertainty 62-135ms, `want = half + 250` = 312-385ms,
so it lands on or just above the 350ms floor. Measured on this host: **+378ms**
(vs +685ms on 09-01). On the customer's faster Korean line the uncertainty should be
tighter still and it will sit on the 350ms floor.

**End-to-end validation, real arrivals, harmless HEAD requests.** `measure_arrival`
now reads the ms cookie back, so we finally measure the ACTUAL arrival instead of
estimating it. Aiming at the shipped +378ms, 8 shots:

```
실제 도착 +628 +441 +406 +430 +442 +384 +415 +416 ms
오차      +250  +63  +28  +52  +64   +6  +37  +38 ms      (mean +67, worst +250)
정각 전에 도착한 발: 0/8
```

Every shot landed after the boundary, mean overshoot +67ms (the request leg exceeds
`rtt/2` slightly; absorbed by the safety margin, and it errs in the direction that is
merely a race rather than a certain rejection). The one +250ms outlier had a 533ms
rtt spike; that is precisely what `ARRIVAL_SAFETY_MS` is paying for.

**Why the floor stays 350.** It is far above the residual half-uncertainty
(62-135ms), so the clamp is honest, and arriving before the hour is still the only
*certain* loss. Do not lower it without a new capture. A test pins that the aim is
always positive and always exceeds the residual one-sided error.

Also changed, same reason: `note_drift_sample` takes the ms stamp when available
(window shrinks from 1s+rtt to rtt), and `automation.touch_session` now hits the
probe path and reads `egovLatestServerTime` out of `document.cookie` (the cookie is
not HttpOnly). Same session-keeping effect, 6x cheaper, ms-resolution drift check.

### 3) The classifier learned 선예약

`booking.TAKEN_REAL` is the verbatim captured string and `booking.R_TAKEN = "taken"`
is a code distinct from `R_FULL`, because the evidence grades differ (선예약: 2 real
observations; 정원초과: zero, ever).

```
_RE_TAKEN = re.compile(r"선예약[^.。]{0,16}예약되지\s*않")     # counts vary, skeleton does not
```

Checked after `OK_WORDS`/`FULL_WORDS` and before `NOT_BOOKABLE`/`FAIL`. Keeping OK
first preserves the invariant that a real success is never read as a loss: the 08-31
success `1건 예약 중 1건 예약되었습니다.` and the 09-01 loss
`1건 예약 중 1건 예약이 선예약으로 인해 예약되지 않았습니다.` share a prefix.

The fixture is `ci/fixtures/real/taken_alert.html`, generated by
`ci/build_taken_fixture.py` straight out of the customer's ZIP (same PII-shape gate as
the other builders). A test re-reads the string out of that file and compares it to
`TAKEN_REAL`, so an invented wording cannot creep back in.

`R_TAKEN` is non-retryable everywhere and the reopen gate locks on it, same as
`R_FULL`. It is deliberately **not** wired into `runner`'s "try the next preferred
hour" fallback: that path calls `_prepare_with_retries`, which re-presses 예약하기 and
re-enters the queue. That is the 2026-08-26 disaster.

**On 정원초과: I believe it is dead vocabulary the site never sends.** Now that 선예약
is proven to be this site's lost-race response, the customer's written "정원초과" reads
as their paraphrase of what happened, not a quoted string. Zero occurrences across
08-25, 08-26, 08-27, 08-28, 08-31, 09-01. **I did not delete it** (keeping it costs
nothing and catches the day it really arrives) but `selector_audit` item 9 still
carries it as UNCONF with that reasoning written in.

### 4) The queue: we were never in it, and cannot get an earlier ticket than we have

Answer: **queue position gates entry to `fnSave()`, not the submit.** Holding an
earlier ticket is not an available lever, because we already hold the best one.

`sessionStorage_handover_preflight.json`, **all four days**:

```
NetFunnel_ID = 5002:200:key=<226 hex>&nwait=0&nnext=0&tps=0.000000&ttl=0&...
```

A ticket was already held before the shot, with `nwait=0`, on every single day
including the success. And it is the same ticket that carried the submit: on 09-01
the preflight key `6016A84CD6E2721BE2D3537F2A18E792…` is byte-identical to the key in
the `opcode=5004` (NetFunnel_Complete) issued right after our POST at 00:00:09.418Z.
Same on 08-28 and 08-27.

Why: the customer presses 예약하기 around 08:40. `fnSave()` calls `NetFunnel_Action`
FIRST, gets a ticket (uncontested at 08:40, so `nwait=0`), and only then opens the
confirm dialog we hold. So the handover design already walks past the 09:00 queue
twenty minutes early. That is a property worth protecting.

The 319-person queue at 09:00:10 was a **new** ticket taken **after** our POST:
`InsertOcreqst` is request index 136 in the after-dump, the `5002` entries start at
index 139, after the 5004 released ours. Decoding the key tails (they are hex-encoded
ASCII) gives `,1,1,319,0` / `,0,1,309,0` / `,10,1,305,0`, matching the log's
319 -> 309 -> 305. It is the crowd arriving at 09:00, not us.

Conclusion: milliseconds ARE the lever here, not queue position. **No re-queueing or
retry behaviour was implemented.** `--handovertest` now includes the 선예약 screen and
asserts `fnSave=0 alertClosed=0 confirmClicked=0`, and CI fails if that changes.

Noted while reading `selectDay2`, NOT implemented: a cell reading `"0"` sets
`wait_gb="Y"` and the site registers a **예약대기 (waitlist)** via
`reswaitdt`/`reswaitbgntm`/`reswaitendtm` instead of a reservation. That is a real
second lever for days we lose the race, but it changes what the customer receives, so
it needs the owner's call first.

### 5) Diagnostics: the 300-entry truncation that made me report a wrong conclusion

`_network_digest` returned `rows[-300:]`. On 09-01 the after-dump's earliest entry is
id `54164.420`, i.e. **419 earlier requests were silently gone**, and the queue
ticket issuance sat inside them. I reported "no queue ticket was ever issued". The
ticket was in `sessionStorage` the whole time.

- `config.NET_RING_MAX` 3000 -> **12000**, `config.NET_DIGEST_LIMIT` 300 -> **1500**.
- Trimming now drops the **middle**, not the head (`_trim_middle`), and records
  `{"kind":"elided","droppedEntries":N}` so a gap is never silent again.
- Rows matching `_NET_KEEP_ALWAYS` (`InsertOcreqst`, `ts.wseq`, `/icms/occasion/`, …)
  are kept wherever they sit.

**And the bodies are persisted now.** `automation._JS_NET_RECORDER` is installed via
`Page.addScriptToEvaluateOnNewDocument` in `build_driver` and records request body,
response body, response headers, status, and t0/t1 for `InsertOcreqst` /
`/icms/occasion/` / `ts.wseq`. `capture()` writes it as `xhr_bodies_<label>.json`.

It is built so it cannot break the customer's page, in this priority order:
it never replaces a handler (`addEventListener('loadend')`, not `onreadystatechange`),
never consumes a response (`r.clone()` for fetch), always calls the original
(`_open/_send/_fetch.apply`), every branch is inside try/catch (10 try / 10 catch, 2
then / 2 catch, asserted by test), redacts `pass|pwd|password|aResult|cert`, and caps
at 40 rows / 20,000 chars with middle-elision.

Verified in a real headless Chrome against a local server (never the live site):
the page's own `onreadystatechange` still receives the JSON, and we recorded
`"returnval":"fail"`, the 선예약 `returnmsg`, `resdt=20260915` in the request, the
password replaced by `[REDACTED]`, and the response `date` header. That last one is a
bonus: `getAllResponseHeaders()` exposes `Date` on a same-origin XHR, so the next
09:00 gives us the submit's real arrival second, which we have never had.

### Tests

227 passed (was 201). New: `tests/test_diagnostics.py` (11), plus additions to
`test_clock.py`, `test_handover.py`, `test_updater.py`.
`ci/selector_audit.py`: 60 dependencies, 58 confirmed / 1 recon-only /
1 unconfirmed (정원초과), 26/26 product checks pass.
`--handovertest` -> `fired=1/6`, `--selftest` OK, `--arrivaltest` as quoted above.

### The trap this release walks straight into: 1.0.9 -> 1.0.10

`"1.0.10" < "1.0.9"` as strings. `updater.version_tuple` splits on `.` and compares
ints, so it is correct, and `test_one_point_ten_is_newer_than_one_point_nine` now
pins exactly this case. If you ever swap that for a string compare, every customer
freezes on their current build forever.

## 배포 현황 (v1.0.9, 2026-08-27 00:52Z) ← 지난 판

- 프로그램: https://works.insu.ng/works/public/2309842/aisarang-reservation-1.0.9.zip
  (29,240,054 bytes, mode 644, ZIP 안 최상위 폴더 `aisarang-reservation-1.0.9/`)
  **빌드 바이트 sha256 = CI 가 찍은 값 = Caddy 로 실제 내려받은 바이트 sha256 =
  `60f96c5f11b2c3ad6d6eef8bbf431cc05cbc2c7110eea9208a7969959f84f279`**
  (게이트웨이 루프백으로 확인하면 안 된다. `--resolve works.insu.ng:443:127.0.0.1`)
- 매니페스트: `version-aisarang.json` → 1.0.9 (`zipUrl` 만, `exeUrl` 없음)
  **실제 게시된 매니페스트를 받아 제품의 `updater.choose_download` 를 돌린 결과:**
  1.0.4 → zip, 1.0.5 → zip, 1.0.6 → zip, 1.0.7 → zip, **1.0.8 → zip(1.0.9)**,
  1.0.9 → None. 고객 PC 는 08-27 아침에 1.0.8 을 돌렸다. 켜두면 15분 안에 1.0.9 가
  된다(`CHECK_SECONDS = 900`).
- CI: GitHub Actions run **33027433255** (커밋 c8edcad), 전 단계 green.
  unit **201** → 실물 캡처 회귀 24(진짜 크롬) → **인계 모드 42(진짜 크롬)** →
  셀렉터 감사 → onedir 빌드 → PE 확인 → ZIP → 디펜더 정의 갱신 + 실제 스캔 3건 →
  fixture selftest → GUI construct → ZIP 을 풀어서 그 exe 로 selftest →
  시각 재측정(프로즌) → 진단 기록(프로즌) → **인계 모드(프로즌)** → 스크린샷 3장 → sha256.
  (라이브 selftest 는 러너에서 childcare.go.kr 이 안 닿아 skip. 늘 그렇다.)
- 감사: `의존성 59개: 확인 57 / 영상복원본만 1 / 미확인 1`,
  `제품 동작 검증 23개 중 23개 통과`. v1.0.8 대비 +1 의존성(예약시간전 실물 문구가
  UNCONF → CONFIRMED 로 갈라져 나왔다), +4 제품 검증(전부 too_early 화면).
- 프로즌 exe 실측 (windows-latest, CI 로그):
  ```
  RESYNC n=1 offsetMs=-24.4 deltaMs=-37.8 uncertaintyMs=133.0 samples=12
  RESYNC n=2 offsetMs=+21.7 deltaMs=+46.2 uncertaintyMs=77.1  samples=12
  RESYNC n=3 offsetMs=-25.8 deltaMs=-47.5 uncertaintyMs=57.9  samples=12
  HANDOVERTEST   tooEarlyText=too_early reopenAllowed=True fnSave=1
                 alertClosed=1 confirmClicked=0
  HANDOVERTEST fired=1/5 expected=1 → HANDOVERTEST OK
  ```
  마지막 줄이 이번 판의 핵심 증거다. 실물 '예약시간전' 화면에서 되살리기가
  [예약하기] 를 **정확히 한 번**, 알림 닫기를 **정확히 한 번** 누르고, 예약
  확인창의 [확인] 은 **0회** 눌렀다.
- 디펜더 실제 판정: `VERDICT v1.0.9-onedir: CLEAN`, `VERDICT v1.0.9-zip: CLEAN`.
  러너는 `RealTimeProtectionEnabled: False` 라 실행 시점 동작 감시는 재현되지 않는다.
  그 이상으로 말하지 말 것.
- 스크린샷(진짜 윈도우 창, 세션 1): `docs/gui-1.0.9-handover.png`,
  `docs/gui-1.0.9.png`, `docs/gui-1.0.9-record.png`. 응답 판정기 줄에
  `'예약시간전': 'too_early'` 가 **실물 원문으로** 찍혀 있다.
- Artifacts: 이 서버에서 돌린 `--handovertest` 진단 1건과 배포 기록
  `aisarang-reservation-devnote` 1건이 `matched:true` 로 저장됐다
  (devnote id `1b8e248f-e4b0-45fa-ba19-61d8514eff35`).

## 배포 현황 (v1.0.8, 2026-08-26 01:10Z) ← 지난 판

- 프로그램: https://works.insu.ng/works/public/2309842/aisarang-reservation-1.0.8.zip
  (29,231,071 bytes, mode 644, ZIP 안 최상위 폴더 `aisarang-reservation-1.0.8/`
   = `aisarang-reservation.exe` + `_internal/` + `사용안내.txt`, 1,352 항목)
  **빌드 바이트 sha256 = CI 가 찍은 값 = Caddy 로 실제 내려받은 바이트 sha256 =
  `761a849f42ecb6fd07b097a02d62e78ff45a6204b8650187b4d3eb58c2021124`**
  (게이트웨이 루프백으로 확인하면 안 된다. `--resolve works.insu.ng:443:127.0.0.1`)
- 매니페스트: `version-aisarang.json` → 1.0.8 (`zipUrl` 만, `exeUrl` 없음)
  **실제 게시된 매니페스트를 받아 제품의 `updater.choose_download` 를 돌린 결과:**
  1.0.4 → zip, 1.0.5 → zip, 1.0.6 → zip, **1.0.7 → zip(1.0.8)**, 1.0.8 → None.
  고객 PC 는 08-26 아침에 1.0.7 을 돌렸다. **프로그램을 켜두면 15분 안에 1.0.8 이
  된다**(`CHECK_SECONDS = 900`). 1.0.4 는 옛 업데이터라 `exeUrl` 만 보므로
  자동 갱신되지 않는다(의도한 것이다).
- CI: GitHub Actions run **32916723591** (커밋 fd2d719), 전 단계 green.
  unit **166** → 실물 캡처 회귀 24(진짜 크롬) → **인계 모드 15(진짜 크롬)** →
  셀렉터 감사 → onedir 빌드 → PE 확인 → ZIP → 디펜더 정의 갱신 + 실제 스캔 3건 →
  라이브 selftest → fixture selftest → GUI construct → ZIP 을 풀어서 그 exe 로
  selftest → 시각 재측정(프로즌) → 진단 기록(프로즌) → **인계 모드(프로즌)** →
  스크린샷 3장 → sha256.
- 감사: `의존성 58개: 확인 56 / 영상복원본만 1 / 미확인 1`,
  `제품 동작 검증 19개 중 19개 통과`.
- 프로즌 exe 실측 (windows-latest, CI 로그):
  ```
  RESYNC n=1 offsetMs=-43.1 deltaMs=-44.0 uncertaintyMs=133.2 samples=12
  RESYNC n=2 offsetMs=+1.5  deltaMs=+44.5 uncertaintyMs=77.8  samples=12
  RESYNC n=3 offsetMs=+49.7 deltaMs=+48.2 uncertaintyMs=131.8 samples=12
  RECTEST pages=4 requests=6 wanted=2 clicks=3 reserved=False skipped=0 → RECTEST OK
  HANDOVERTEST page=modal_open.html ticked=True  ... ready=True  fired=True
                 confirmId=layer-confirm-popup-confirm2
  HANDOVERTEST page=modal_open.html ticked=False ... ready=False fired=False
  HANDOVERTEST page=netfunnel_waiting.html ... queue=True ready=False fired=False
                 queueAhead=72 queueBehind=26
  HANDOVERTEST page=grid_selected_row_added.html ... modal=False ready=False fired=False
  HANDOVERTEST fired=1/4 expected=1 → HANDOVERTEST OK
  ```
- 디펜더 실제 판정: `VERDICT v1.0.8-onedir: CLEAN`, `VERDICT v1.0.8-zip: CLEAN`.
  러너는 `RealTimeProtectionEnabled: False` 라 실행 시점 동작 감시는 재현되지 않는다.
  그 이상으로 말하지 말 것.
- 스크린샷(진짜 윈도우 창, 세션 1, 896x717): `docs/gui-1.0.8-handover.png`
  (**새 '1. 실행 방식' 카드 + 인계 상태판**: `인계 모드 ([확인] 만 누름) |
  확인창 감지됨 | 선택표 체크 켜짐 | [확인] 까지 00:41`, 그리고 로그에
  `대기열 실측(2026-08-26 08:57): 가상대기열 대기 중 (앞에 72명, 뒤에 26명, 예상 2분 10초)`),
  `docs/gui-1.0.8.png`, `docs/gui-1.0.8-record.png`. 194 / 196 / 204 colours.
- Artifacts: 이 서버에서 돌린 `--handovertest` 진단 1건(v1.0.8 표기)과
  배포 기록 `aisarang-reservation-devnote` 1건이 `matched:true` 로 저장됐다
  (id `b9cf41b1-8465-45c1-9b3e-d34b7e648aae`). `artifacts-check 2309842` 로 확인.

### 이번 판에서 CI 가 한 번 섰다. 게시물이 아니라 로그 인코딩이었다.

**run 32916034550 (eca77ee)** 프로즌 exe 의 `--handovertest` 는 **정확히 통과했다**
(`fired=1/4`, `HANDOVERTEST OK`). 그런데 CI 가 찾던 요약 줄
`HANDOVERTEST fired=1/4 (기대: 1)` 이 로그에 **없었다.** windows-latest 러너가
exe 의 stdout 을 파일로 리디렉션하면 인코딩이 cp1252 가 되고, 한글이 든 줄은
`UnicodeEncodeError` 를 내는데 `main._out()` 이 그것을 삼켜 **줄이 통째로 사라졌다.**
같은 함정을 어제 `selector_audit.py` 에서 한 번 밟았는데(NOTES v1.0.7 절), 그때는
스크립트에 `reconfigure` 를 넣어 고쳤다. 제품에는 그럴 수 없다(`--noconsole` 이라
`sys.stdout` 이 None). 그래서 `_out` 에 **두 번째 시도**를 붙였다: 못 찍는 글자만
대체하고 줄은 남긴다. 그리고 **CI 가 판정에 쓰는 줄은 전부 ASCII 로** 찍는다
(`queueAhead=72 queueBehind=26 blockers=1 confirmId=...`). 한글 줄은 사람이 읽는
용도로만 남긴다.

> 다음 사람에게: 프로즌 exe 가 찍는 줄을 CI 가 `-match` 로 검사할 거라면
> **그 줄에 한글을 넣지 마라.** 러너에서 조용히 사라진다.

## 배포 현황 (v1.0.7, 2026-08-25 10:40Z) ← 지난 판

- 프로그램: https://works.insu.ng/works/public/2309842/aisarang-reservation-1.0.7.zip
  (29,199,016 bytes, mode 644, ZIP 안 최상위 폴더 `aisarang-reservation-1.0.7/`
   = `aisarang-reservation.exe` + `_internal/` + `사용안내.txt`, 1,352 항목)
  **빌드 바이트 sha256 = CI 가 찍은 값 = Caddy 로 실제 내려받은 바이트 sha256 =
  `cf27c315d8a1125b73be95d892d252f57318066bf6e69824598462ee1fd2e6cc`**
  (게이트웨이 루프백으로 확인하면 안 된다. `--resolve works.insu.ng:443:127.0.0.1`)
- 매니페스트: `version-aisarang.json` → 1.0.7 (`zipUrl` 만, `exeUrl` 없음)
  실제 게시된 매니페스트를 받아 `updater.choose_download` 를 돌린 결과:
  1.0.4 → zip, 1.0.5 → zip, **1.0.6 → zip(1.0.7)**, 1.0.7 → None.
  **1.0.6 을 쓰는 PC 는 프로그램을 켜두면 15분 안에 자동으로 1.0.7 이 된다**
  (`CHECK_SECONDS = 900`). 고객은 08-25 저녁에 1.0.6 으로 진단 기록을 돌렸으므로
  1.0.6 이다. 1.0.4 는 옛 업데이터라 `exeUrl` 만 보므로 자동 갱신되지 않는다.
- CI: GitHub Actions run **32837296603** (커밋 b39a29c), 전 단계 green.
  unit **151** → 실물 캡처 회귀(진짜 크롬) → 셀렉터 감사 → onedir 빌드 → PE 확인 →
  ZIP → 디펜더 정의 갱신 + 실제 스캔 3건 → fixture selftest → GUI construct →
  ZIP 을 풀어서 그 exe 로 selftest → 시각 재측정(프로즌) → 진단 기록(프로즌) →
  스크린샷 2장 → sha256.
- 감사(같은 스크립트, CI 로그): `의존성 53개: 확인 51 / 영상복원본만 1 / 미확인 1`,
  `제품 동작 검증 13개 중 13개 통과`.
- 프로즌 exe 실측: `CLOCKTEST OK resyncs=3`,
  `RECTEST pages=4 requests=13 wanted=2 clicks=3 reserved=False skipped=0` → RECTEST OK.
  `clicks=3` 은 CI 하네스(사람 역할)가 누른 수이고 `reserved=False` 는 예약 계기가
  끝까지 꺼져 있었다는 뜻이다. 기록기는 한 번도 누르지 않았다.
- 디펜더 실제 판정: `VERDICT v1.0.7-onedir: CLEAN`, `VERDICT v1.0.7-zip: CLEAN`.
  러너는 `RealTimeProtectionEnabled: False` 라 실행 시점 동작 감시는 재현되지 않는다.
  그 이상으로 말하지 말 것.
- 스크린샷(진짜 윈도우 창, 세션 1): `docs/gui-1.0.7.png`(라이브가 막혀서 실측
  응답으로 채운 조회 결과 + 5분 재측정 로그가 화면에 보인다),
  `docs/gui-1.0.7-record.png`(진단 기록 카드). 896x717, 192 / 156 colours.
- Artifacts: 프로즌 exe 가 CI 에서 올린 진단 5건이 실제로 저장됐고
  (`aisarang-reservation-diag`, v1.0.7 표기), 배포 기록 `aisarang-devnote` 1건도
  `matched:true` 로 들어갔다. `artifacts-check 2309842` 로 확인.

### 이번 판에서 CI 가 세 번 섰다. 원인은 전부 게시물이 아니라 발판이었다.

1. **run 32834436312 (d724df6)** `selector_audit.py` 가 윈도우 러너의 cp1252
   stdout 에 한글을 찍다 `UnicodeEncodeError`. 감사 판정은 이미 다 나온 뒤였다.
   → 콘솔 전용 CI 스크립트라 stdout/stderr 을 utf-8 로 재설정. **제품에는 넣지 말 것**
   (`--noconsole` 이라 `sys.stdout` 이 None 이다).
2. **run 32835549489** `test_real_markup.py` 의 **첫 테스트만** 실패.
   `read_slot_rows` 가 `{how:'none', tableIndex:-1}` = 표를 하나도 못 봄 = 그 순간
   문서가 없었다는 뜻(픽스처에는 table 이 2개다). 단정을 풀지 않고, 드라이버
   픽스처가 문서를 실제로 확인하고 넘기도록 고쳤다(+ 바깥 네트워크 차단).
3. **run 32836231656** 얼린 exe 의 `--rectest` 가 `#btnAdd` / `#btnReserve` 를
   눌렀다. v1.0.7 에서 fixture 를 실물 id 로 바꿨는데(`#timecareTableAddBtn` /
   `#timecareConfirm`) `main.py` 의 하네스만 안 고쳐져 있었다.
   → **픽스처의 id 를 바꾸면 `main.py --rectest` 하네스도 같이 고쳐라.**

## 배포 현황 (v1.0.6, 2026-08-25 07:50Z) ← 지난 판

- 프로그램: https://works.insu.ng/works/public/2309842/aisarang-reservation-1.0.6.zip
  (29,196,243 bytes, mode 644, ZIP 안 최상위 폴더 `aisarang-reservation-1.0.6/`
   = `aisarang-reservation.exe`(PE32+ GUI) + `_internal/` + `사용안내.txt`, 1,352 항목)
  **빌드 바이트 sha256 = CI 가 찍은 값 = Caddy 로 실제 내려받은 바이트 sha256 =
  `55364fbdbc4fae0f493dac74c912fa0af52a21e78a753039d658f570078288b0`**
  (게이트웨이 루프백으로 확인하면 안 된다. `--resolve works.insu.ng:443:127.0.0.1`)
- 매니페스트: https://works.insu.ng/works/public/2309842/version-aisarang.json → 1.0.6 (`zipUrl` 만)
  `choose_download` 실측: 1.0.4 → zip, 1.0.5 → zip, 1.0.6 → None.
  **1.0.5 를 쓰는 PC 는 프로그램을 켜두면 15분 안에 자동으로 1.0.6 이 된다.**
  1.0.4 는 옛 업데이터라 `exeUrl` 만 보므로 자동 갱신되지 않는다(의도한 것이다).
  고객이 마지막으로 실제 실행한 것은 v1.0.4 였다 → **새 링크를 보내야 한다.**
- CI: GitHub Actions run **32822319572**, 전 단계 green
  (unit **131** → onedir 빌드 → PE + 버전리소스 → ZIP → 디펜더 정의 갱신 +
   실제 스캔 3건 → **라이브 selftest(이번엔 러너가 childcare.go.kr 에 닿았다)** →
   fixture selftest → GUI construct → ZIP 을 풀어서 그 exe 로 selftest →
   **시각 재측정(프로즌 exe)** → **진단 기록(프로즌 exe)** → 스크린샷 2장 → sha256)
  131개에 진짜 크롬 19개가 들어 있다(4·5단계 6 + 아동선택 2 + 진짜 마크업 3 +
  진단 기록 8).
- 프로즌 exe 실측 (windows-latest, CI 로그):
  ```
  RESYNC n=1 offsetMs=+53.0 deltaMs=+19.8 uncertaintyMs=133.8 samples=12
  RESYNC n=2 offsetMs=+29.7 deltaMs=-23.2 uncertaintyMs=63.3  samples=12
  RESYNC n=3 offsetMs=+5.8  deltaMs=-24.0 uncertaintyMs=133.8 samples=12
  RECTEST pages=4 requests=53 wanted=2 clicks=3 reserved=False skipped=0
  RECTEST wanted-url .../SelectOccasionChild.html  bytes=370
  RECTEST wanted-url .../OccasionTimeMainSlPL.html bytes=799
  ```
  `clicks=3` 은 CI 하네스(사람 역할)가 누른 수이고 `reserved=False` 는
  예약 계기가 끝까지 꺼져 있었다는 뜻이다. 즉 기록기는 한 번도 누르지 않았다.
- 디펜더 실제 판정: `VERDICT v1.0.6-onedir: CLEAN`, `VERDICT v1.0.6-zip: CLEAN`
  (같은 엔진으로 v1.0.4-onefile 도 CLEAN). 러너는 `RealTimeProtectionEnabled: False`
  라 실행 시점 동작 감시는 여전히 재현되지 않는다. 그 이상으로 말하지 말 것.
- 스크린샷(진짜 윈도우 창, 세션 1): `docs/gui-1.0.6.png`(라이브 조회 결과),
  `docs/gui-1.0.6-record.png`(설정을 끝까지 내려 **[진단 기록 시작] / [기록 중지]**
  버튼이 보이는 컷). 896x717, 187 / 160 colours.
- Artifacts: 이 서버에서 돌린 `--rectest` 진단 ZIP 1건이 실제로 저장됐다
  (37,302 bytes, `record/wanted/01_SelectOccasionChild.html.html`,
   `record/wanted/02_OccasionTimeMainSlPL.html.html`, `record/network.json` 68행,
   `cookies_record.json` 은 비어 있고 세션 값은 어디에도 없다).
  + `aisarang-reservation-devnote` v1.0.6 1건.

## 배포 현황 (v1.0.5, 2026-08-25 05:40Z) ← 지난 판

- 프로그램: https://works.insu.ng/works/public/2309842/aisarang-reservation-1.0.5.zip
  (29,155,070 bytes, mode 644, ZIP 안 최상위 폴더 `aisarang-reservation-1.0.5/`
   = `aisarang-reservation.exe`(8.7MB, PE32+ GUI) + `_internal/` + `사용안내.txt`, 1,352 항목)
  **서빙 바이트 sha256 = 빌드 바이트 sha256 = CI 가 찍은 값 =
  `9c98e7030d7e96cdb87db5221c7f94e58f1d67f351059a2451a0c888eb64fdde`**
  (Caddy 경유로 실제 내려받아 대조. 게이트웨이 루프백으로 확인하면 안 된다.)
- 매니페스트: https://works.insu.ng/works/public/2309842/version-aisarang.json → 1.0.5 (`zipUrl`)
- CI: GitHub Actions run **32813175739**, 전 단계 green
  (unit **96** → onedir 빌드 → PE + 버전리소스 확인 → ZIP 패키징 →
   **디펜더 정의 갱신 + 실제 스캔 3건** → fixture selftest → GUI construct →
   **ZIP 을 풀어서 그 exe 로 selftest** → GUI 스크린샷 → sha256)
  96개에 **진짜 크롬 8개**가 들어 있다(4·5단계 흐름 6 + 아동선택 2).
  이 판에서는 러너가 childcare.go.kr 에 못 닿아(ConnectTimeout) 라이브
  selftest 는 skip 됐다. 5분 전 run **32812690275** 에서는 같은 코드로
  라이브 selftest exit 0 이었다. 러너 IP 대역 문제이지 제품 문제가 아니다.
- 디펜더 실제 판정 (엔진 1.1.26070.7 / 서명 1.457.329.0):
  ```
  VERDICT v1.0.4-onefile: CLEAN (no threats found)
  VERDICT v1.0.5-onedir : CLEAN (no threats found)
  VERDICT v1.0.5-zip    : CLEAN (no threats found)
  ```
  러너는 `RealTimeProtectionEnabled: False` 다. 즉 **실행 시점 동작 감시는
  여기서 재현되지 않는다.** 이 CLEAN 은 "정적 시그니처로는 안 걸린다" 까지만
  증명한다. 그 이상으로 말하지 말 것.
- 스크린샷: `docs/gui-1.0.5.png` (이번 빌드, fixture 데이터),
  `docs/gui-1.0.5-live.png` (5분 전 빌드, **라이브 조회** 결과가 찍힌 것).
  둘 다 실제 윈도우 창이고 화면은 v1.0.4 와 같다(버전 표기만 다르다).
- Artifacts: `aisarang-reservation-devnote` v1.0.5 1건 (`matched: true`,
  id 130fe445-1541-4352-a20b-1afd56149aa4)

## 배포 현황 (v1.0.4, 2026-08-25) ← 지난 판, 기록용

- exe: https://works.insu.ng/works/public/2309842/aisarang-reservation-1.0.4.exe
  (29,149,406 bytes, `PE32+ executable (GUI) x86-64`, mode 644)
  **서빙 바이트 sha256 = 빌드 바이트 sha256 = `da8f84b2276746a13713cc6276dbc4ed53c18534683bfbf9774e6feba71b77d1`**
  (Caddy 경유로 실제 내려받아 대조했다. 게이트웨이 루프백으로 확인하면 안 된다.)
  1.0.0 / 1.0.2 / 1.0.3 도 같은 경로에 그대로 남아 있다.
  **이미 서빙된 파일명은 절대 덮어쓰지 않는다.**
- 업데이트 매니페스트: https://works.insu.ng/works/public/2309842/version-aisarang.json → 1.0.4
- CI: GitHub Actions run **32791579911**, 전 단계 green
  (unit tests **88** → build → PE 확인 → **라이브 selftest** → fixture selftest →
   GUI construct → GUI 스크린샷). 88개에 **진짜 크롬으로 4·5단계를 끝까지 도는
  6개**가 포함돼 있고, windows-latest 에서도 skip 없이 다 돌았다.
- 스크린샷: `docs/gui-1.0.4.png` (실제 Windows 창. v1.0.4 표기 +
  "서초구 센터 10곳 조회, 기본 센터(신반포) 확인, 예약시간전/정원초과 판정 정상,
  보정 -338ms, 최소왕복 912ms, 편도 추정 456ms")
- Artifacts: `artifacts-check 2309842` 에 프로즌 v1.0.4 exe 가 올린 행 2건
  (2026-08-24T23:58, 23:59, Windows 2025Server, `aisarang-reservation-diag`)
  + `aisarang-reservation-devnote` v1.0.4 1건 (`matched: true`)

### v1.0.4 에서 바뀐 것 요약

| | v1.0.3 | v1.0.4 |
|---|---|---|
| 4·5단계 근거 | 없음(도달 못 함) | **고객 인증서 세션 화면녹화** |
| 정각에 쏘는 것 | 예약 화면 전체 시도 | **모달의 [확인] 한 번** |
| 준비 시점 | 정각 60초 전 예열 | **정각 240초 전에 8단계까지 완료 + 모달 홀드** |
| 실패 응답 | 뭉뚱그린 fail | **예약시간전(재시도) / 정원초과(중단)** 로 분리 |
| 시계 보정 | 실행 전 1회 | + **실전 중 '예약시간전' 응답으로 재보정** |
| 자리 없음 | 셀렉터 실패로 보임 | **X / 0 을 그대로 읽어 보고** |

### 측정된 근거

프로즌 exe 가 실제 Windows(`frozen: True`)에서 매 실행 진단을 올린다.
왕복지연에 따라 정밀도가 갈리는 것이 그대로 찍힌다:

| 대상 | 최소 왕복 | 동기화 오차 |
|---|---|---|
| 라이브 childcare.go.kr (러너→한국) | 870~912ms | ±481 ~ ±882ms |
| 로컬 fixture 서버 | 0~1ms | **±67 ~ ±171ms** |

고객 PC(국내 회선 → 국내 정부 서버)는 아래쪽 구간에 해당한다.

발사 정밀도 실측: 목표 대비 **0.15 ~ 0.52ms**.
도착 정확도 실측: **3회 연속 4/4 (합계 12/12)** — 위 "도착" 절 표 참고.

4·5단계 흐름 실측(재현 화면 + 진짜 크롬, 2026-08-25):
```
class: 매송아이 / hours: 9
grid rows: 20260902 … 20260908
20260908: 09=2 10=2 … 17=2      20260905: 09=X … 17=X
pick: 09시 칸 (남은 자리 2명)   click: True   add: True
tick: (True, 1, ' 매송아이 2026-09-08(화) 09 00 - 18 00 (9시간)')
modal: True / "…예약하시겠습니까? 확인 취소" / ready: True
burst: True  shots=[{"code":"too_early"},{"code":"ok"}]  fired count: 2
```

## 아직 굳히지 못한 것 (다음 사람이 볼 것)

1. ~~진짜 마크업은 절반만 확보했다~~ → **2026-08-25 저녁에 닫혔다.**
   고객이 진단 기록 모드로 확인창까지 걸어준 캡처로 4~9단계 실물을 전부
   받았다. 위 v1.0.7 절과 `ci/fixtures/real/` 참고. 감사 숫자는
   확인 22 → **50** (51~52개 중). 남은 것은 아래 2번 하나다.
2. **"예약시간전" / "정원초과" 의 서버 원문은 여전히 미확인이다.**
   2026-08-25 캡처 373건을 전수 검색했으나 **0건**이다. 고객이 확인창에서
   멈춰 `InsertOcreqst.html` 이 호출된 적이 없기 때문이다. 두 문구는
   **고객이 글로 적어준 것뿐**이고, `ci/fixtures/reserve_page.html` 이 그
   문구를 스스로 찍어 우리 분류기가 그걸 읽는 구조라 **그 테스트는 순환
   논증이다**. CI 초록불을 서버 문구의 증거로 읽지 마라.
   `booking.TOO_EARLY_WORDS` / `FULL_WORDS` 는 일부러 넓게 열어둔 상태다.
   첫 실전 실행의 `confirm_shots.json` 에 찍힌 원문으로 좁혀라.
   (실물로 확인된 사이트 문구들은 `NOT_BOOKABLE_WORDS` 에 모아두었다.
   그건 서버 결과가 아니라 화면이 먼저 막는 문구다.)
3. **간편인증도 `loginMode == "CT"` 로 쳐주는가.** 617 의 문구가
   "공동인증서/간편인증서 로그인이 필요합니다" 라 그럴 가능성이 높다.
   고객 실행 진단의 `loginMode` 값 한 줄이면 판정된다.
4. **서버가 정각보다 얼마나 이른 도착을 거부하는지.** 이제 `예약시간전`
   응답으로 실전 중에 스스로 좁힌다(`clock.note_too_early`). 첫 실행의
   `correctionNotes` 를 보고 `arrival_lead_ms` 기본값을 조정하면 된다.
5. ~~[예약하기] 가 정말 서버로 아무것도 안 보내는지~~ → **2026-08-25 캡처로 판정됐다.**
   `record/network.json` 373건의 **마지막 요청**이 [예약하기] 클릭이 부른 것이고,
   그것은 예약이 아니라 **넷퍼넬(대기열) 진입**이다:

   ```
   GET https://nf.childcare.go.kr:8443/ts.wseq?opcode=5101&...&aid=mcis_0
   ```

   `InsertOcreqst.html` 은 **캡처 전체에서 0건**이다. 즉 예약 전송은
   확인창의 [확인] 에서만 일어난다(사이트 JS 로도 확인: `fnSave` →
   `NetFunnel_Action({action_id:"mcis_0"}, insertOcreqst)` → `confirm2` →
   콜백에서 비로소 `POST /icms/occasion/InsertOcreqst.html` →
   성공하면 `alert2(returnmsg)` 후 `/?menuno=245` 로 이동).
   **우리 설계(정각 240초 전에 준비를 끝내고 확인창을 붙잡고 있다가 [확인]
   하나만 정각에 쏜다)가 대기열을 미리 통과해 두는 셈이라 유리하다.**

6. **넷퍼널 대기열은 '4분 전 준비' 를 통째로 무력화한다.** ~~표가 만료되는가~~ 보다
   먼저 밟힌 문제가 있었다. 2026-08-26 실측: 09시 4분 전에 [예약하기] 를 누르면
   대기열에 서게 되고(앞에 72명, 예상 2분 10초) **확인창 자체가 열리지 않는다.**
   "표를 미리 쥐어둔다" 는 설계가 성립하려면 대기열을 통과할 때까지 기다려야
   한다. v1.0.8 이 그렇게 고쳤고, 인계 모드에서는 사람이 원하는 시각에 직접
   줄을 선다. **아직 모르는 것은 그대로 남아 있다**: 통과한 표가 정각까지
   유효한지. 첫 실전 실행의 `network_*.json` 에서 `ts.wseq` 응답 코드로 판정하라.
7. **`setup_seconds` 기본값 240 이 인계 모드에서는 쓰이지 않는다.** 언제 줄을 설지는
   고객이 정한다. 자동 모드에서는 그대로 240 이지만, 대기열이 2~5분이면 4분
   전은 아슬아슬하다. 고객이 자동 모드를 다시 쓰게 되면 이 값을 재검토하라.

### 고객 계정으로 실제로 해본 것 / 하지 않은 것

했다(2026-08-24): 아이디 로그인 1회, `?menuno=242/605/245/617` 조회,
서초구 센터 목록, 실브라우저로 로그인→예약화면→등급판정→로그아웃 1회.
했다(2026-08-25): 고객이 보내준 **녹화 영상 프레임 판독**, 재현 화면으로
헤드리스 크롬 실행 검증.

**고객이 직접 돌린 기록(2026-08-25T05:15~05:24Z = 14:15~14:24 KST, v1.0.4).**
진단 ZIP `1787635468018-…-142428.zip` 에 다 남아 있다. 읽을 수 있는 것:
인증서 로그인 성공(`로그인 등급 확인: cert`), 예약 화면 진입 성공, 이용일
20260909 로 09시 대기 진입, 4분 뒤 고객이 [중지]. **예약은 만들어지지 않았다.**
동시에 두 가지가 확인됐다: (1) exe 가 결국 뜨기는 뜬다, (2) 뜨는 데 3분 44초가
걸린다(onefile %TEMP% 해제 + 실시간 감시). 그래서 v1.0.5 가 필요했다.

**안 했다: 예약 제출은 단 한 번도 시도하지 않았다.** 이번 판에서도
고객 사이트에는 아무 요청도 보내지 않았다(검증은 전부 로컬 fixture).
디스크에 남긴 것 없음: 자격증명, 쿠키값, 세션파일 전부 남기지 않았다.

> 자격증명은 **채팅에만** 있다. 고객이 아이디를 여러 번 다시 적어 철자가
> 흔들린 적이 있으니, 로그인이 실패하면 변형을 차례로 시도하지 말고
> 대화를 다시 읽어라. 이 계정은 고객에게 중요하다.

## 하면 안 되는 것

- 고객 계정으로 반복 예약 테스트 금지. 실제 예약이 생기고 취소는 센터 전화(1661-9361)로만 된다.
- **'정원초과' 를 받고 같은 칸을 다시 두들기지 말 것.** 이미 나간 자리이고,
  9시 정각의 서버에 의미 없는 부하만 준다. `confirm_burst` 가 즉시 멈춘다.
- 선택표 행 체크가 꺼진 채로 [예약하기]/[확인] 을 누르지 말 것
  (엉뚱한 행이 예약될 수 있다). `Prepared.ready()` 가 막는다.
- 개발자도구 열기 금지 (자동 로그아웃).
- 이미 서빙된 파일명(exe/zip) 덮어쓰기 금지 (Cloudflare 엣지 캐시 → 업데이트 루프).
- **`--onefile` 로 되돌리지 말 것.** 고객 PC 에서 실행 자체가 막혔고, 뜨더라도
  시작에만 3분 44초가 걸렸다. 9시 정각 작업에서는 그것만으로 실패다.
- 매니페스트에 `zipUrl` 과 `exeUrl` 을 같이 넣지 말 것 (옛 업데이터가 ZIP 을
  exe 자리에 덮어쓴다).
- **고객 진단 ZIP 의 `page_source` 원본을 저장소에 넣지 말 것.** 아동 이름 등이
  마스킹을 빠져나와 그대로 들어 있다. 구조만 재현해서 가짜 값으로 넣어라
  (`ci/fixtures/child_select.html` 이 그 방식이다).
- 인증서 비밀번호를 로그/커밋/메시지에 남기지 말 것. 화면 입력 → 메모리 → 즉시 폐기.
- **진단 기록 모드에 "한 번만 눌러주자" 를 넣지 말 것.** 이 모드는 예약을
  만들 수 없다는 것이 유일한 안전 근거다(고객에게도 그렇게 안내했다).
  `recorder.py` 에 클릭 경로가 없다는 것을 테스트가 소스로 못박아 둔다.
- **`perfLoggingPrefs` 에 `traceCategories: ""` 를 넣지 말 것.** chromedriver 가
  크롬을 아예 안 띄운다(위 v1.0.6 4번 참고).
- `--rectest` 를 실사이트로 돌리지 말 것. 로컬 fixture(127.0.0.1)가 아니면
  스스로 거부하게 해뒀다. 그 가드를 풀지 말 것. `--handovertest` 도 같다
  (로컬 http 픽스처 서버만 띄운다).
- **[예약하기] 를 누른 뒤에 준비를 처음부터 다시 하지 말 것.** 그것이 정확히
  2026-08-26 에 고객이 예약을 놓친 이유다. 대기열 맨 뒤로 가고(72명 → 138명 →
  177명), 사람이 만들어 둔 설정도 같이 날아간다. `Runner.PRESSED_RESERVE`
  목록을 줄이지 말 것.
- **인계 모드(`handover.py`)에 "한 번만 눌러주자" 를 넣지 말 것.** 이 모드는
  [확인] 말고는 아무것도 누를 수 없다는 것이 유일한 안전 근거이고, 고객에게도
  그렇게 안내했다. `tests/test_handover.py` 가 소스로 못박아 둔다.
- **`Prepared.ready()` 를 인계 모드에 쓰지 말 것.** `cell_selected` 는 우리
  `click_cell` 안에서만 참이 되고 다시 계산되지 않아서, 사람이 만든 화면에서는
  영원히 거짓이다. 인계 모드는 `handover.LiveState.ready()` 로 매번 다시 읽는다.
- **오늘(2026-08-26) 캡처의 `page_source` 를 저장소에 넣지 말 것.** 아동 실명이
  평문으로 4번 들어 있다. 대기열 픽스처는 레이어 조각만 떼어 붙인 것이다.
