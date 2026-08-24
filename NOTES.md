# 260824-kmong-2309842-aisarang-reservation

아이사랑(childcare.go.kr) **시간제보육** 예약을 매일 오전 9시 오픈 순간에 넣는
Windows 프로그램. Kmong 고객 2309842 (거대한고봉밥), 주문 7566483, 150,000원.

- Neoworks customerId: `05788f12-b025-48ba-bb01-7c45121013d8`
- Artifacts / 정적호스팅 키: `2309842` (Kmong partnerId)
- 저장소: https://github.com/bf-dev/260824-kmong-2309842-aisarang-reservation (**public**, Actions 무료분 때문)

## 실행 / 빌드

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/ -q        # 61 passed
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

## 실사이트 단계별 검증 맵 (2026-08-24)

1·3단계는 KR 프록시(egress 115.68.232.141), 2·4·5·6단계는 KR 프록시와 직접 접속
양쪽으로 확인했다. 증거 파일은 `docs/site-map/` 에 그대로 저장돼 있다.
저장 전에 전부 `masking.mask()` 를 통과시켰고 세션 식별자도 지웠다.
**추정으로 채운 칸은 없다. 못 본 것은 못 봤다고 적는다.**

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

### 4단계 — 2주 뒤 오픈분의 날짜/시간대 화면  ❌ **여전히 도달 못 함. 이유가 확정됐다.**

이번엔 **고객 계정으로 로그인한 상태**에서 열어봤다
(`07-reserve-605-idsession.html`). 결과는 비로그인 때와 같은 빈 화면이고,
**왜 비었는지를 서버가 직접 말해준다.** 605 페이지의 인라인 스크립트에
서버가 두 값을 찍어 내려준다:

```js
let targetMode = "CT";      // 이 화면이 요구하는 인증 등급 = 공동인증서
var loginMode  = "ID";      // 지금 내 세션의 인증 등급 = 아이디 로그인
if (targetMode == 'CT' && loginMode != 'CT') {
    icmsLayerPopup.alert({ contents : "공동인증서 로그인이 필요합니다." },
        function(res){ window.location.href = "/?menuno=506&ltype=cert&returnUrl=/?menuno=242"; });
}
```

| 측정 (아이디 로그인 세션) | 값 |
|---|---|
| `POST /?menuno=605` | HTTP 200, 60,003 B |
| `<div id="contents">` 안 | **0 B (완전히 빈 div)** |
| 날짜/시간대/신청 버튼 | **0개** |
| 서버가 찍은 `loginMode` / `targetMode` | **`ID` / `CT`** |
| 화면이 띄우는 문구 | "공동인증서 로그인이 필요합니다." |

`?menuno=245`(신청현황), `?menuno=617`(아동등록)도 **똑같이 `targetMode="CT"`**.
617 만 문구가 `"공동인증서/간편인증서 로그인이 필요합니다."` 다
→ **간편인증도 CT 등급으로 쳐준다는 뜻**(605 에서도 될 가능성이 높지만,
간편인증을 실제로 해본 것은 아니라 확정은 아니다).

**즉 아이디 로그인으로는 4·5단계가 절대 안 열린다. 클라이언트 우회도 불가능하다**
— 자바스크립트 분기만 막는 문제가 아니라 `#contents` 자체를 서버가 안 그린다.
고객이 처음에 말한 "사이트에서는 공동인증서로 로그인합니다"가 정확했다.

**없는 것: 고객 PC 에 설치된 실제 공동인증서(또는 간편인증) 세션.**
이건 서버에서 만들 수 없다. AnySign4PC 가 고객 PC 에서 도는 프로그램이라서다.

### 5단계 — 최종 예약 제출 요청 (URL/메서드/헤더/전체 파라미터)  ❌ **도달 못 함**
4단계가 안 열리므로 5단계도 못 본다. 4단계와 달리 여기는 **추가 정보가 아예 없다**:
- 로그인 상태 605 응답에도 예약 로직은 **한 줄도 없다**. 인라인 스크립트 8개는
  전부 공용 보일러플레이트(로딩 표시, devtools 차단, 인증등급 체크)뿐이다.
- 외부 JS 24개 중 예약 로직이 든 파일 없음. 공용 번들
  `cpcommon.js`(113KB) / `common.js`(126KB) / `fncommon.js`(23KB) 를
  `Occasion|TmpCare|ChildRes|fnRes` 로 훑어도 **일치 0건**.
- 목록 화면 주석의 구경로는 죽어 있다:
  `POST /cpis2gi/occasion/OccasionChildResIs.jsp` → **404 "시스템 점검 중"**
  `POST /cpis2gi/occasion/OccasionChildResPiIs.jsp` → **404**

→ 예약 폼과 제출 로직은 **인증서 세션에만 서버가 찍어주는 인라인 JSP 출력**이다.

확실히 아는 5단계의 유일한 부분은 진입 요청이다(실측, 목록 화면
`gotoOccasionRes()` 원문 그대로):
`document.pfrm` 에 `stcode`/`unityYn`/`unityynall` 을 넣고
`action="/?menuno=605"` 로 POST. `automation.open_reservation_page()` 가 이걸 그대로 한다.

### 그래서 코드가 이 공백을 어떻게 다루는가
4·5단계를 추측으로 채우지 않았다. `automation.py` 의 `select_date` /
`select_time_slots` / `find_submit` 은 **여러 후보를 순서대로 시도하는 적응형**이고,
매 시도마다 그 시점의 DOM 을 진단 ZIP 으로 올린다. 그리고 **날짜 선택에 성공하지
못하면 절대 제출하지 않는다**(`attempt_once` 가 `date_not_open` 으로 먼저 빠진다).
즉 실패 모드가 "엉뚱한 날짜를 예약함"이 아니라 "예약이 안 됨"이다.
연습 모드는 마지막 버튼 직전에서 멈추므로 예약을 만들지 않고 DOM 만 받아올 수 있다.

이번에 추가된 것: **인증 등급을 먼저 판정한다.** `login_grade()` 가 서버가 찍어준
`loginMode` 를 읽어 `cert`/`id`/`none` 을 돌려주고, 아이디 세션이면
`attempt_once` 가 제출 근처도 안 가고 이렇게 끝낸다(실브라우저 실측 문구):

> 아이디로 로그인된 상태입니다. 이 화면은 공동인증서 세션에서만 열립니다.
> 크롬 창에서 공동인증서로 다시 로그인해 주세요.

그리고 `runner` 는 09시를 기다리기 전에 이 판정을 먼저 하고, 등급이 모자라면
`wait_for_cert_session()` 으로 "예약 화면이 실제로 열릴 때까지" 기다린다
(로그아웃 링크 유무가 아니라 **화면이 열리는지**로 판정한다. 아이디 로그인도
로그인이라 로그아웃 링크는 똑같이 보이기 때문이다).

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

## 맞춰야 하는 건 '발사'가 아니라 '도착' (v1.0.3)

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

**`?menuno=605` 의 인증서 세션 DOM 을 우리는 여전히 못 봤다.**
고객 아이디/비밀번호로는 열리지 않는다는 것만 확정했다(4단계 참고).
공동인증서는 고객 PC 에 있고 AnySign4PC 로만 풀리므로 서버에서 만들 수 없다.

→ **다음 사람이 제일 먼저 할 일은 그대로다.** 고객이 프로그램을 한 번 돌리면
(연습 모드 권장) 진단 ZIP 이 `artifacts/private/05788f12-.../` 에 올라온다.
거기 `page_source/*_reservation_page.html` 를 열어 실제 선택자를 확인하고
`select_date` / `select_time_slots` / `find_submit` 을 그 DOM 에 맞게 굳혀라.
연습 모드(`dry_run`)는 마지막 버튼 직전에서 멈추므로 예약을 만들지 않는다.

두 번째로 확인할 것: **간편인증도 `loginMode == "CT"` 로 쳐주는가.**
617 의 문구가 "공동인증서/간편인증서 로그인이 필요합니다" 라 그럴 가능성이 높다.
사실이면 고객이 인증서 없이 간편인증(카카오/PASS 등)으로도 돌릴 수 있어서
운영이 훨씬 편해진다. 고객 실행 진단의 `loginMode` 값 한 줄이면 판정된다.

세 번째: **서버가 정각보다 이른 도착을 거부하는지.** 실제 예약을 만들어야
알 수 있어서 확인하지 않았다.

### 고객 계정으로 실제로 해본 것 / 하지 않은 것 (2026-08-24)
했다: 아이디 로그인(성공 1회), `?menuno=242/605/245/617` 조회, 서초구 센터 목록,
실브라우저로 로그인→예약화면→등급판정→**로그아웃**까지 1회.
안 했다: **예약 제출은 단 한 번도 시도하지 않았다.** 신청 버튼 근처에도 가지 않았다.
`attempt_once` 는 인증 등급에서 먼저 막혀 끝났다(`reason: cert_required`).
디스크에 남긴 것 없음: 자격증명, 쿠키값, 세션파일 전부 남기지 않았다.
(로그인 확인 중 부수적으로 확인된 것: 이 계정의 즐겨찾기에 신반포 센터가
이미 등록돼 있다 → 기본 센터 선택이 맞다는 교차확인.)

## 하면 안 되는 것

- 고객 계정으로 반복 예약 테스트 금지. 실제 예약이 생기고 취소는 센터 전화(1661-9361)로만 된다.
- 개발자도구 열기 금지 (자동 로그아웃).
- 이미 서빙된 exe 파일명 덮어쓰기 금지 (Cloudflare 엣지 캐시 → 업데이트 루프).
- 인증서 비밀번호를 로그/커밋/메시지에 남기지 말 것. 화면 입력 → 메모리 → 즉시 폐기.
