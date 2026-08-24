# -*- coding: utf-8 -*-
"""실제 예약을 수행하는 브라우저 자동화.

왜 requests 가 아니라 진짜 브라우저인가
--------------------------------------
실사이트를 읽어 확인한 사실:

1. 시간제보육 예약 화면(?menuno=605)은 **공동인증서로 로그인한 세션**에만
   그려진다. 로그인 안 한 상태로 POST 하면 껍데기만 온다(실측 55KB 중
   본문 0). 목록 화면의 gotoOccasionRes() 안에는 서버가 상황에 따라
   내보내는 분기가 그대로 박혀 있다:
       icmsLayerPopup.alert({contents : "공동인증서 로그인이 필요합니다."});
   고객이 화면에서 본 그 문구다.

2. 공동인증서 로그인은 AnySign4PC(한컴위드) 로컬 모듈이 처리한다
   (/icms/AnySign/anySign4PCInterface.js, fnXecureLogin →
   AnySign.SignDataWithVID → 폼의 aResult 채우고 /icms/login/login.html 로 전송).
   이 모듈은 고객 PC 에 설치되어 돌아가는 프로그램이라, 서버에서 흉내낼 수
   없고 흉내내서도 안 된다. 인증서와 비밀번호는 고객 PC 를 떠나지 않는다.

그래서 고객 PC 의 크롬을 그대로 몬다. 인증서는 원래 있던 자리에 있고,
비밀번호는 이 프로그램 화면에 입력된 값이 AnySign 입력칸으로 바로 들어간다.

3. 사이트에 devtools 차단(disable-devtool)이 걸려 있어 개발자도구를 열면
   자동 로그아웃된다. 그래서 자동화 중에는 절대 devtools 를 열지 않는다.
"""
from __future__ import annotations

import re
import time

from . import config


# ---------------------------------------------------------------- 드라이버

def build_driver(headless: bool = False, log=lambda *_: None):
    """고객 PC 의 크롬을 띄운다. 프로필을 재사용해 로그인 세션이 남는다."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument(f"--user-data-dir={config.profile_dir()}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--lang=ko-KR")
    opts.add_argument("--window-size=1280,960")
    if headless:
        opts.add_argument("--headless=new")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    try:
        driver = webdriver.Chrome(options=opts)
    except Exception:
        # 드라이버가 PATH 에 없을 때만 다운로드를 시도한다.
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                                  options=opts)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"},
        )
    except Exception:
        pass

    neutralize_devtool_blocker(driver, log)
    log("크롬을 실행했습니다.")
    return driver


def neutralize_devtool_blocker(driver, log=lambda *_: None) -> bool:
    """사이트의 disable-devtool 이 우리를 오탐해 로그아웃시키는 것을 막는다.

    실측(2026-08-24, 이 프로젝트의 셀레니움 옵션 그대로):
      크롬을 셀레니움으로 띄워 /?menuno=242 를 열면 **1초 안에**
      alert("부정 사용 방지를 위하여 개발자 도구 사용을 차단합니다.") 가 뜨고
      페이지가 /logout 으로 넘어간다. 개발자도구를 연 적이 없는데도 그렇다.
      (disable-devtool 0.3.7 의 탐지 규칙이 자동화된 크롬을 devtools 로 본다.)
      09시 정각에 이게 터지면 고객은 로그아웃된 채로 예약을 놓친다.

    그래서 그 스크립트 파일 하나만 네트워크에서 막는다. 페이지의 인라인
    코드는 `typeof DisableDevtool !== 'undefined'` 로 감싸여 있어서, 없으면
    console.error 한 줄만 남기고 그대로 정상 동작한다(실측으로 확인).
    개발자도구를 여는 것이 아니라, 열지도 않았는데 튀는 오탐을 끄는 것이다.
    """
    ok = False
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs",
                               {"urls": ["*disable-devtool*"]})
        ok = True
    except Exception as exc:  # noqa: BLE001
        log(f"devtool 차단 스크립트 무력화(1차) 실패: {type(exc).__name__}")
    try:
        # 1차가 안 먹는 크롬 버전을 대비한 이중 안전장치.
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "try{Object.defineProperty(window,'DisableDevtool',"
                       "{value:function(){},writable:false,configurable:false});}"
                       "catch(e){}"},
        )
        ok = True
    except Exception:
        pass
    if ok:
        log("사이트의 개발자도구 감지 스크립트를 차단했습니다(오탐 로그아웃 방지).")
    return ok


# ---------------------------------------------------------------- 진단 수집

def capture(driver, diag, label: str) -> None:
    """현재 페이지의 HTML / 쿠키 / 스토리지를 진단 ZIP 에 담는다."""
    if diag is None:
        return
    try:
        diag.add_page(label, driver.current_url, driver.page_source)
    except Exception:
        pass
    try:
        diag.add_json(f"cookies_{label}.json", driver.get_cookies())
    except Exception:
        pass
    for kind in ("localStorage", "sessionStorage"):
        try:
            data = driver.execute_script(
                f"var o={{}};for(var i=0;i<{kind}.length;i++)"
                f"{{var k={kind}.key(i);o[k]={kind}.getItem(k);}}return o;"
            )
            diag.add_json(f"{kind}_{label}.json", data)
        except Exception:
            pass
    try:
        logs = driver.get_log("performance")
        diag.add_json(f"network_{label}.json", logs[-200:])
    except Exception:
        pass


# ---------------------------------------------------------------- 로그인

LOGIN_MARKERS = ("로그아웃", "마이페이지", "logout")


def is_logged_in(driver) -> bool:
    try:
        body = driver.find_element("tag name", "body").text
        return any(m in body for m in LOGIN_MARKERS)
    except Exception:
        return False


def login_grade(driver) -> str:
    """지금 세션의 인증 등급. 'cert' | 'id' | 'none'.

    예약 화면(?menuno=605)을 한 번 열어 서버가 찍어준 loginMode 를 읽는다.
    이 값은 우리가 추측한 게 아니라 서버가 페이지에 박아 내려주는 값이다.
    """
    try:
        src = driver.page_source
    except Exception:
        return "none"
    login_mode, _ = read_login_mode(src)
    if login_mode == "CT":
        return "cert"
    if login_mode:
        return "id"
    return "cert" if is_logged_in(driver) else "none"


def touch_session(driver, log=lambda *_: None) -> bool:
    """세션 유지용 가벼운 요청.

    실측: 로그인 직후 egovExpireSessionTime - egovLatestServerTime = 3,600,000ms.
    즉 세션은 마지막 활동 기준 60분이면 끊긴다. 전날 밤에 인증서 로그인을 해두는
    운영은 불가능하고, 09시 직전까지 세션을 살려둬야 한다.
    """
    try:
        driver.execute_script(
            "try{var x=new XMLHttpRequest();"
            "x.open('HEAD','/?menuno=1&_ka='+Date.now(),true);x.send();}catch(e){}"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"세션 유지 요청 실패(무시): {type(exc).__name__}")
        return False


def open_cert_login(driver, log=lambda *_: None) -> None:
    driver.get(config.BASE_URL + config.LOGIN_PAGE_CERT)
    time.sleep(1.5)
    log("공동인증서 로그인 화면을 열었습니다.")


def start_cert_login(driver, cert_password: str, log=lambda *_: None,
                     diag=None, timeout: int = 120) -> bool:
    """AnySign 인증서 창을 띄우고 비밀번호를 넣는다.

    AnySign4PC 의 화면 구성은 설치 버전에 따라 다르다. 그래서 여러 후보를
    순서대로 시도하고, 못 찾으면 실패로 끝내지 않고 '고객이 직접 인증서 창을
    마무리하도록' 넘긴다(그 사이에도 프로그램은 로그인 완료를 기다린다).
    어떤 DOM 이 실제로 떴는지는 진단으로 올라가므로 다음 버전에서 바로 굳힌다.
    """
    from selenium.webdriver.common.by import By

    open_cert_login(driver, log)
    capture(driver, diag, "cert_login_page")

    try:
        driver.execute_script("if (typeof fnXecureLogin === 'function') fnXecureLogin();")
        log("인증서 창을 호출했습니다 (fnXecureLogin).")
    except Exception:
        try:
            driver.find_element(By.ID, "loginBtn").click()
        except Exception:
            log("인증서 로그인 버튼을 찾지 못했습니다. 화면에서 직접 눌러주세요.")

    time.sleep(2.5)
    capture(driver, diag, "anysign_dialog")

    # AnySign 비밀번호 입력칸 후보들. iframe 안에 있을 수도 있다.
    candidates = [
        (By.ID, "anysign_password"),
        (By.ID, "certPassword"),
        (By.ID, "inputCertPw"),
        (By.CSS_SELECTOR, "#AnySign4PC input[type=password]"),
        (By.CSS_SELECTOR, ".anysign input[type=password]"),
        (By.CSS_SELECTOR, "input[type=password][id*=pw i]"),
        (By.CSS_SELECTOR, "input[type=password]"),
    ]

    def _try_fill(scope_desc: str) -> bool:
        for by, sel in candidates:
            try:
                els = driver.find_elements(by, sel)
            except Exception:
                continue
            for el in els:
                try:
                    if not el.is_displayed():
                        continue
                    el.clear()
                    el.send_keys(cert_password)
                    log(f"인증서 비밀번호를 입력했습니다 ({scope_desc}).")
                    return True
                except Exception:
                    continue
        return False

    filled = _try_fill("메인 문서")
    if not filled:
        try:
            for fr in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    driver.switch_to.frame(fr)
                    if _try_fill("iframe"):
                        filled = True
                        break
                finally:
                    driver.switch_to.default_content()
        except Exception:
            pass

    if filled:
        for by, sel in [(By.CSS_SELECTOR, "#AnySign4PC .btn_confirm"),
                        (By.CSS_SELECTOR, "button.confirm"),
                        (By.CSS_SELECTOR, ".anysign .ok"),
                        (By.XPATH, "//button[contains(.,'확인')]"),
                        (By.XPATH, "//a[contains(.,'확인')]")]:
            try:
                for el in driver.find_elements(by, sel):
                    if el.is_displayed():
                        el.click()
                        log("인증서 확인을 눌렀습니다.")
                        raise StopIteration
            except StopIteration:
                break
            except Exception:
                continue
    else:
        log("인증서 창의 입력칸을 자동으로 찾지 못했습니다. "
            "떠 있는 인증서 창에서 직접 비밀번호를 넣어주세요. 그대로 기다립니다.")

    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_logged_in(driver):
            log("로그인이 확인되었습니다.")
            capture(driver, diag, "after_cert_login")
            return True
        time.sleep(1.0)

    capture(driver, diag, "cert_login_timeout")
    log("제한시간 안에 로그인이 확인되지 않았습니다.")
    return False


def wait_for_cert_session(driver, center: dict, log=lambda *_: None,
                          stop_event=None, diag=None,
                          deadline_epoch: float | None = None,
                          clock=None, poll: float = 5.0) -> bool:
    """예약 화면이 실제로 열릴 때까지(= 인증서 세션이 될 때까지) 기다린다.

    '로그인했다' 가 아니라 '이 화면이 열린다' 를 기준으로 판정한다. 아이디
    로그인도 로그인이긴 해서 로그아웃 링크 유무로는 구분이 안 되기 때문이다.
    """
    driver.get(config.BASE_URL + config.LOGIN_PAGE_CERT)
    log("공동인증서 로그인 화면을 열었습니다. 인증서로 로그인해 주세요.")
    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        if deadline_epoch is not None and clock is not None:
            if clock.server_now() >= deadline_epoch:
                log("인증서 로그인 대기 시간이 끝났습니다.")
                capture(driver, diag, "cert_wait_timeout")
                return False
        time.sleep(poll)
        try:
            if not is_logged_in(driver):
                continue
            open_reservation_page(driver, center, log, None)
            if not page_says_cert_required(driver):
                log("공동인증서 세션이 확인되었습니다. 예약 화면이 열립니다.")
                capture(driver, diag, "cert_session_ready")
                return True
        except Exception:
            continue


def wait_for_manual_login(driver, log=lambda *_: None, stop_event=None,
                          timeout: int = 1800) -> bool:
    """고객이 직접 로그인할 때까지 기다린다."""
    driver.get(config.BASE_URL + config.LOGIN_PAGE_CERT)
    log("열린 크롬 창에서 직접 로그인해 주세요. 로그인되면 자동으로 인식합니다.")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            return False
        if is_logged_in(driver):
            log("로그인이 확인되었습니다.")
            return True
        time.sleep(1.5)
    return False


# ---------------------------------------------------------------- 예약 화면

def open_reservation_page(driver, center: dict, log=lambda *_: None,
                          diag=None) -> None:
    """?menuno=605 로 stcode/unityYn 을 POST 한다.

    사이트가 하는 것과 똑같이 폼 submit 으로 보낸다(세션 쿠키가 그대로 실린다).
    참고: 목록 화면의 gotoOccasionRes() 가 document.pfrm 에 값을 넣고
    action="/?menuno=605" 로 submit 하는 흐름 그대로다.
    """
    driver.get(config.BASE_URL + config.SEARCH_PAGE)
    time.sleep(0.8)
    script = """
    var c = arguments[0];
    var f = document.createElement('form');
    f.method = 'post';
    f.action = '/?menuno=605';
    function add(n, v) {
      var i = document.createElement('input');
      i.type = 'hidden'; i.name = n; i.value = v; f.appendChild(i);
    }
    add('stcode', c.stcode);
    add('unityYn', c.unityYn || 'N');
    add('unityynall', '');
    document.body.appendChild(f);
    f.submit();
    """
    driver.execute_script(script, {"stcode": center["stcode"],
                                   "unityYn": center.get("unityYn", "N")})
    time.sleep(2.0)
    log(f"예약 화면을 열었습니다: {center.get('name', center['stcode'])}")
    capture(driver, diag, "reservation_page")


# 서버가 페이지에 직접 찍어 내려주는 두 변수. 실측(2026-08-24, 고객 계정)으로 확인:
#   ?menuno=605 / 245 / 617  →  let targetMode = "CT";   (그 화면이 요구하는 인증 등급)
#   아이디 로그인 세션        →  var loginMode  = "ID";
#   둘이 다르면 화면은 "공동인증서 로그인이 필요합니다" 를 띄우고 인증서 로그인으로 보낸다.
#   그리고 이때 <div id="contents"> 는 **완전히 비어 있다**(서버가 아예 안 그린다).
_RE_LOGIN_MODE = re.compile(r'var\s+loginMode\s*=\s*"([^"]*)"')
_RE_TARGET_MODE = re.compile(r'let\s+targetMode\s*=\s*"([^"]*)"')
# 서버가 세션 메시지를 뿌리는 자리. 로그인 실패/제출 결과가 여기로 나온다.
_RE_SESSION_MSG = re.compile(
    r"<!--\s*세션 메세지 체크\s*-->\s*<script>\s*icmsLayerPopup\.alert\(\s*\{\s*"
    r'contents\s*:\s*"([^"]*)"',
    re.S,
)


def read_login_mode(page_source: str) -> tuple[str, str]:
    """(loginMode, targetMode). 서버가 찍어준 값이라 추측이 아니다."""
    lm = _RE_LOGIN_MODE.search(page_source or "")
    tm = _RE_TARGET_MODE.search(page_source or "")
    return (lm.group(1) if lm else ""), (tm.group(1) if tm else "")


def read_session_message(page_source: str) -> str:
    """서버가 내려보낸 안내 문구(로그인 실패, 신청 결과 등). 없으면 빈 문자열."""
    m = _RE_SESSION_MSG.search(page_source or "")
    return m.group(1) if m else ""


def contents_is_empty(page_source: str) -> bool:
    """<div id="contents"> 안이 비었는지. 인증 등급 미달이면 서버가 통째로 비운다."""
    m = re.search(r'id="contents"[^>]*>(.*?)</div>', page_source or "", re.S)
    if not m:
        return False
    return len(m.group(1).strip()) == 0


def page_says_cert_required(driver) -> bool:
    """이 화면이 공동인증서 세션을 요구하는데 지금 세션이 그게 아닌 상태인가."""
    try:
        src = driver.page_source
    except Exception:
        return False
    if "공동인증서 로그인이 필요합니다" in src or "공동인증서/간편인증서 로그인이 필요합니다" in src:
        return True
    login_mode, target_mode = read_login_mode(src)
    if target_mode == "CT" and login_mode != "CT":
        return True
    return False


def handle_netfunnel(driver, log=lambda *_: None, max_wait: int = 60) -> None:
    """넷퍼널(가상대기열)이 뜨면 통과할 때까지 기다린다.

    사이트에 netfunnel-pcms.js 가 실제로 배포돼 있다. 9시 정각에 대기열이
    열리면 곧바로 재시도해봐야 소용이 없으므로 순번이 빠질 때까지 둔다.
    """
    deadline = time.time() + max_wait
    seen = False
    while time.time() < deadline:
        try:
            src = driver.page_source
        except Exception:
            return
        if "NetFunnel" not in src and "대기하고 계십니다" not in src:
            if seen:
                log("대기열을 통과했습니다.")
            return
        if not seen:
            seen = True
            log("가상대기열에 들어갔습니다. 순번을 기다립니다...")
        time.sleep(1.0)


# ------------------------------------------------------- 예약 흐름

# 4·5단계(검색 → 센터 → 아동 → 반/이용시간 → 날짜칸 → 추가 → 체크 →
# 예약하기 → 확인)는 booking.py 가 담당한다. 그 순서는 고객이 보내준
# 인증서 세션 화면녹화에서 그대로 읽어낸 것이다
# (docs/site-map/recording/, NOTES.md 4·5단계).
#
# 이 파일에는 드라이버/로그인/세션/진단만 남긴다.


def read_result(driver) -> tuple[str, str]:
    """(상태, 사이트가 보여준 문구). booking.classify 로 판정한다."""
    from . import booking
    try:
        src = driver.page_source
    except Exception:
        return booking.R_UNKNOWN, ""
    msg = read_session_message(src)
    if msg:
        return booking.classify(msg), msg
    for word in (booking.OK_WORDS + booking.TOO_EARLY_WORDS + booking.FULL_WORDS):
        if word in src:
            return booking.classify(word), word
    return booking.R_UNKNOWN, ""
