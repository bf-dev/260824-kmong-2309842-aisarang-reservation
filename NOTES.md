# 260824-kmong-2309842-aisarang-reservation

아이사랑(childcare.go.kr) **시간제보육** 예약을 매일 오전 9시 오픈 순간에 넣는
Windows 프로그램. Kmong 고객 2309842 (거대한고봉밥), 주문 7566483, 150,000원.

- Neoworks customerId: `05788f12-b025-48ba-bb01-7c45121013d8`
- Artifacts / 정적호스팅 키: `2309842` (Kmong partnerId)
- 저장소: https://github.com/bf-dev/260824-kmong-2309842-aisarang-reservation (**public**, Actions 무료분 때문)

## 실행 / 빌드

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/ -q        # 130 passed (크롬 있으면 브라우저 19개 포함)
python3 main.py                              # GUI (고객이 쓰는 화면)
python3 main.py --selftest                   # 실서버 조회 + 서버시각 동기화 점검
python3 main.py --guidemo --hold=60000       # CI 스크린샷용 데모 (실제 조회 수행)
python3 main.py --guidemo --showrecord       # 같은 데모인데 '5. 진단 기록' 카드가 보이게 스크롤
python3 main.py --arrivaltest                # 도착시각 모델 실검증 (서버 Date 헤더로 대조)
python3 main.py --clocktest=1.2 --interval=20  # 시각 재측정이 정말 주기적으로 도는지 (v1.0.6)
AISARANG_BASE_URL=http://127.0.0.1:18777 \
  python3 main.py --rectest                  # 진단 기록 모드 실행 (로컬 fixture 전용, v1.0.6)
python3 ci/fixture_server.py 18777           # --rectest 가 붙을 로컬 서버 (/rec 화면)
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
- `netfunnel-pcms.js` (넷퍼널 가상대기열) 이 배포돼 있다. 목록 화면에서는 주석 처리돼
  있지만 9시 몰릴 때 서버가 켤 수 있다. `automation.handle_netfunnel()` 이 대기 처리.

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

## 배포 현황 (v1.0.7, 2026-08-25 10:40Z) ← 지금 서빙 중

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

6. **넷퍼넬 대기열 표를 4분 붙잡고 있어도 유효한가.** 위 5번의 결과로 새로
   생긴 질문이다. `NetFunnel_Action` 은 [예약하기] 시점에 통과하고
   `NetFunnel_Complete()` 는 [확인] 콜백에서 불린다. 그 사이(우리는 최대
   4분)에 표가 만료되는지는 캡처로 알 수 없다. 첫 실전 실행의
   `network_*.json` 에서 `ts.wseq` 응답 코드를 보고 판정하라.
   만약 만료된다면 준비 시각(`setup_seconds`, 지금 240)을 줄여야 한다.

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
  스스로 거부하게 해뒀다. 그 가드를 풀지 말 것.
