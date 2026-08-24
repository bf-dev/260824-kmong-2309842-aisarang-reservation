# 260824-kmong-2309842-aisarang-reservation

아이사랑(childcare.go.kr) **시간제보육** 예약을 매일 오전 9시 오픈 순간에 넣는
Windows 프로그램. Kmong 고객 2309842 (거대한고봉밥), 주문 7566483, 150,000원.

- Neoworks customerId: `05788f12-b025-48ba-bb01-7c45121013d8`
- Artifacts / 정적호스팅 키: `2309842` (Kmong partnerId)
- 저장소: https://github.com/bf-dev/260824-kmong-2309842-aisarang-reservation (**public**, Actions 무료분 때문)

## 실행 / 빌드

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/ -q        # 88 passed (크롬 있으면 브라우저 6개 포함)
python3 main.py                              # GUI (고객이 쓰는 화면)
python3 main.py --selftest                   # 실서버 조회 + 서버시각 동기화 점검
python3 main.py --guidemo --hold=60000       # CI 스크린샷용 데모 (실제 조회 수행)
python3 main.py --arrivaltest                # 도착시각 모델 실검증 (서버 Date 헤더로 대조)
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

## 배포 현황 (v1.0.3, 2026-08-24)

- exe: https://works.insu.ng/works/public/2309842/aisarang-reservation-1.0.3.exe
  (29,123,682 bytes, `PE32+ executable (GUI) x86-64`, mode 644)
  **서빙 바이트 sha256 = 빌드 바이트 sha256 = `b09c19d67eec0887e7df0fbebda6dd8aa7c49e5321efce044caba58ed88eeb28`**
  (Caddy 경유로 실제 내려받아 대조했다. 게이트웨이 루프백으로 확인하면 안 된다.)
  1.0.0 / 1.0.2 도 같은 경로에 그대로 남아 있다. **이미 서빙된 파일명은 절대 덮어쓰지 않는다.**
- 업데이트 매니페스트: https://works.insu.ng/works/public/2309842/version-aisarang.json → 1.0.3
- CI: GitHub Actions run **32720166581**, 전 단계 green
  (unit tests 61 → build → PE 확인 → **라이브 selftest** → fixture selftest →
   GUI construct → GUI 스크린샷)
- 스크린샷: `out/gui.png` (실제 Windows 창을 캡처, v1.0.3 표기와 실측 결과 표시:
  "서초구 센터 10곳 조회, 기본 센터(신반포) 확인, 보정 -349ms, 최소왕복 900ms, 편도 추정 450ms")
- Artifacts: `artifacts-check 2309842` 에 프로즌 exe 가 올린 v1.0.3 행 2건
  (2026-08-24T11:08, Windows 2025Server, `aisarang-reservation-diag`)

### 측정된 근거

프로즌 exe 가 실제 Windows(`frozen: True`)에서 매 실행 진단을 올린다.
왕복지연에 따라 정밀도가 갈리는 것이 그대로 찍힌다:

| 대상 | 최소 왕복 | 동기화 오차 |
|---|---|---|
| 라이브 childcare.go.kr (러너→한국) | 870~900ms | ±481 ~ ±882ms |
| 로컬 fixture 서버 | 0~1ms | **±67 ~ ±171ms** |

고객 PC(국내 회선 → 국내 정부 서버)는 아래쪽 구간에 해당한다.

발사 정밀도 실측: 목표 대비 **0.15 ~ 0.52ms**.
도착 정확도 실측: **3회 연속 4/4 (합계 12/12)** — 위 "도착" 절 표 참고.

## 아직 굳히지 못한 것 (다음 사람이 볼 것)

1. **진짜 마크업(id/class)은 여전히 못 봤다.** 녹화는 568x320 이라 글자는
   읽혀도 속성은 안 읽힌다. 그래서 `booking.py` 는 이름이 아니라 구조/글자로
   찾는다. 고객이 한 번 돌리면(연습 모드 권장) 진단 ZIP 이
   `artifacts/private/05788f12-.../` 에 올라온다. 거기
   `page_source/*_modal_open_armed.html`, `*_after_add_and_tick.html`,
   `grid.json` 을 열어 실제 선택자로 굳혀라. 그때
   `ci/fixtures/reserve_page.html` 도 진짜 마크업으로 바꿔라.
2. **"예약시간전" / "정원초과" 의 정확한 원문**을 아직 우리 눈으로 본 적은
   없다(고객이 말로 알려준 문구다). `booking.TOO_EARLY_WORDS` /
   `FULL_WORDS` 에 표기 흔들림까지 넣어뒀지만, 첫 실전 실행의
   `confirm_shots.json` 에 찍힌 원문으로 좁혀라.
3. **간편인증도 `loginMode == "CT"` 로 쳐주는가.** 617 의 문구가
   "공동인증서/간편인증서 로그인이 필요합니다" 라 그럴 가능성이 높다.
   고객 실행 진단의 `loginMode` 값 한 줄이면 판정된다.
4. **서버가 정각보다 얼마나 이른 도착을 거부하는지.** 이제 `예약시간전`
   응답으로 실전 중에 스스로 좁힌다(`clock.note_too_early`). 첫 실행의
   `correctionNotes` 를 보고 `arrival_lead_ms` 기본값을 조정하면 된다.
5. **[예약하기] 가 정말 서버로 아무것도 안 보내는지** 는 고객 진술과 화면
   흐름으로만 안다(모달이 클라이언트에서 계산된 60시간 안내를 띄운다).
   진단의 `network_*.json` 으로 확인하면 확정된다.

### 고객 계정으로 실제로 해본 것 / 하지 않은 것

했다(2026-08-24): 아이디 로그인 1회, `?menuno=242/605/245/617` 조회,
서초구 센터 목록, 실브라우저로 로그인→예약화면→등급판정→로그아웃 1회.
했다(2026-08-25): 고객이 보내준 **녹화 영상 프레임 판독**, 재현 화면으로
헤드리스 크롬 실행 검증.

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
- 이미 서빙된 exe 파일명 덮어쓰기 금지 (Cloudflare 엣지 캐시 → 업데이트 루프).
- 인증서 비밀번호를 로그/커밋/메시지에 남기지 말 것. 화면 입력 → 메모리 → 즉시 폐기.
