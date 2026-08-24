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

import time
from dataclasses import dataclass, field

from . import clock as clockmod
from . import config


@dataclass
class RunResult:
    ok: bool = False
    message: str = ""
    detail: dict = field(default_factory=dict)


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
    log("크롬을 실행했습니다.")
    return driver


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


def page_says_cert_required(driver) -> bool:
    try:
        return "공동인증서 로그인이 필요합니다" in driver.page_source
    except Exception:
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


# ------------------------------------------------------- 날짜/시간대 선택

def _date_variants(yyyymmdd: str) -> list[str]:
    y, m, d = yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:8]
    return [
        yyyymmdd,
        f"{y}-{m}-{d}",
        f"{y}.{m}.{d}",
        f"{y}/{m}/{d}",
    ]


def select_date(driver, yyyymmdd: str, log=lambda *_: None) -> bool:
    """예약 달력에서 이용일 셀을 고른다."""
    from selenium.webdriver.common.by import By

    variants = _date_variants(yyyymmdd)
    # 1) 값/속성에 날짜가 박힌 요소
    for v in variants:
        for sel in (f"[data-date='{v}']", f"[data-ymd='{v}']", f"[value='{v}']",
                    f"[id='{v}']", f"a[onclick*='{v}']", f"td[onclick*='{v}']",
                    f"[data-day='{v}']"):
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed() and el.is_enabled():
                        driver.execute_script("arguments[0].click();", el)
                        log(f"이용일 {yyyymmdd} 을 선택했습니다.")
                        return True
            except Exception:
                continue
    # 2) 날짜 입력칸
    for sel in ("input#resDate", "input[name*=date i]", "input[name*=ymd i]",
                "input.datepicker"):
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed():
                    driver.execute_script(
                        "arguments[0].value=arguments[1];"
                        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                        el, yyyymmdd)
                    log(f"이용일 {yyyymmdd} 을 입력했습니다.")
                    return True
        except Exception:
            continue
    # 3) 달력의 '일' 숫자 셀
    day = str(int(yyyymmdd[6:8]))
    try:
        for el in driver.find_elements(By.XPATH,
                                       f"//td[normalize-space(text())='{day}']"
                                       f"|//a[normalize-space(text())='{day}']"):
            cls = (el.get_attribute("class") or "").lower()
            if "disabled" in cls or "off" in cls:
                continue
            if el.is_displayed():
                driver.execute_script("arguments[0].click();", el)
                log(f"달력에서 {day}일을 선택했습니다.")
                return True
    except Exception:
        pass
    log(f"이용일 {yyyymmdd} 셀을 찾지 못했습니다.")
    return False


def select_time_slots(driver, slots: list[str], log=lambda *_: None) -> int:
    """원하는 시간대를 고른다. 고른 개수를 돌려준다."""
    from selenium.webdriver.common.by import By

    if not slots:
        return 0
    picked = 0
    for slot in slots:
        hh = slot.split(":")[0].lstrip("0") or "0"
        needles = [slot, slot.replace(":", ""), f"{hh}시"]
        done = False
        for needle in needles:
            if done:
                break
            xp = (f"//label[contains(.,'{needle}')]"
                  f"|//td[contains(.,'{needle}')]//input"
                  f"|//*[@data-time='{needle}']"
                  f"|//input[@value='{needle}']")
            try:
                for el in driver.find_elements(By.XPATH, xp):
                    cls = (el.get_attribute("class") or "").lower()
                    if "disabled" in cls or el.get_attribute("disabled"):
                        continue
                    if not el.is_displayed():
                        continue
                    driver.execute_script("arguments[0].click();", el)
                    picked += 1
                    done = True
                    log(f"시간대 {slot} 선택")
                    break
            except Exception:
                continue
        if not done:
            log(f"시간대 {slot} 은 화면에 없습니다(마감이거나 미운영).")
    return picked


SUBMIT_TEXTS = ("신청하기", "예약하기", "신청", "예약", "확인")


def find_submit(driver):
    from selenium.webdriver.common.by import By
    for text in SUBMIT_TEXTS:
        xp = (f"//button[contains(normalize-space(.),'{text}')]"
              f"|//a[contains(normalize-space(.),'{text}')]"
              f"|//input[@type='submit' and contains(@value,'{text}')]")
        try:
            for el in driver.find_elements(By.XPATH, xp):
                if el.is_displayed() and el.is_enabled():
                    return el, text
        except Exception:
            continue
    return None, ""


def accept_confirm(driver, log=lambda *_: None) -> None:
    """사이트 자체 확인 레이어(icmsLayerPopup)의 확인 버튼을 누른다."""
    from selenium.webdriver.common.by import By
    time.sleep(0.4)
    for sel in (".type-confirm .btn_confirm", ".type-confirm a.btn",
                "#dimmed1 ~ div a", ".popup_wrap:not([style*='display: none']) a"):
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed() and "확인" in (el.text or ""):
                    driver.execute_script("arguments[0].click();", el)
                    log("확인 창을 눌렀습니다.")
                    return
        except Exception:
            continue
    try:
        driver.switch_to.alert.accept()
        log("브라우저 알림을 확인했습니다.")
    except Exception:
        pass


RESULT_OK = ("신청이 완료", "예약이 완료", "정상적으로 신청", "신청되었습니다",
             "예약되었습니다", "완료되었습니다")
RESULT_FAIL = ("마감", "정원", "이미 신청", "불가", "실패", "없습니다", "초과")


def read_result(driver) -> tuple[str, str]:
    """(상태, 사이트가 보여준 문구). 상태는 ok/fail/unknown."""
    try:
        src = driver.page_source
    except Exception:
        return "unknown", ""
    for kw in RESULT_OK:
        if kw in src:
            return "ok", kw
    for kw in RESULT_FAIL:
        if kw in src:
            return "fail", kw
    return "unknown", ""


# ---------------------------------------------------------------- 한 번의 시도

def attempt_once(driver, center: dict, target_date: str, slots: list[str],
                 dry_run: bool, log=lambda *_: None, diag=None) -> RunResult:
    open_reservation_page(driver, center, log, diag)
    handle_netfunnel(driver, log)

    if page_says_cert_required(driver):
        return RunResult(False, "공동인증서 로그인이 필요한 상태입니다. 로그인 후 다시 시도합니다.",
                         {"reason": "cert_required"})

    if not select_date(driver, target_date, log):
        capture(driver, diag, "date_not_found")
        return RunResult(False, f"{target_date} 이용일이 아직 열리지 않았습니다.",
                         {"reason": "date_not_open"})

    time.sleep(0.3)
    picked = select_time_slots(driver, slots, log)
    if slots and picked == 0:
        capture(driver, diag, "slot_not_found")
        return RunResult(False, "원하는 시간대가 열려 있지 않습니다.",
                         {"reason": "slot_unavailable"})

    el, text = find_submit(driver)
    if el is None:
        capture(driver, diag, "submit_not_found")
        return RunResult(False, "신청 버튼을 찾지 못했습니다.", {"reason": "no_submit"})

    if dry_run:
        capture(driver, diag, "dry_run_before_submit")
        return RunResult(True, f"[연습 모드] 여기서 '{text}' 를 누르면 신청됩니다. "
                               "실제 신청은 하지 않았습니다.",
                         {"reason": "dry_run", "button": text, "slots": picked})

    driver.execute_script("arguments[0].click();", el)
    log(f"'{text}' 를 눌렀습니다.")
    accept_confirm(driver, log)
    time.sleep(1.2)
    capture(driver, diag, "after_submit")

    status, kw = read_result(driver)
    if status == "ok":
        return RunResult(True, f"예약 신청이 완료되었습니다. ({kw})", {"reason": "submitted"})
    if status == "fail":
        return RunResult(False, f"신청이 반려되었습니다: {kw}", {"reason": "rejected"})
    return RunResult(True, "신청을 전송했습니다. 신청현황에서 확인해 주세요.",
                     {"reason": "submitted_unconfirmed"})


def burst(driver, center: dict, target_date: str, slots: list[str], dry_run: bool,
          clock_sync, fire_epoch: float, retry_seconds: int, retry_interval_ms: int,
          log=lambda *_: None, diag=None, stop_event=None) -> RunResult:
    """정각에 쏘고, 열릴 때까지 짧게 반복한다."""
    deadline = fire_epoch + retry_seconds
    attempt = 0
    last = RunResult(False, "시도하지 못했습니다.")
    while clock_sync.server_now() < deadline:
        if stop_event is not None and stop_event.is_set():
            return RunResult(False, "사용자가 중지했습니다.", {"reason": "stopped"})
        attempt += 1
        log(f"--- {attempt}번째 시도 (서버시각 기준 "
            f"{clock_sync.server_now() - fire_epoch:+.2f}초) ---")
        try:
            last = attempt_once(driver, center, target_date, slots, dry_run, log, diag)
        except Exception as exc:  # noqa: BLE001
            last = RunResult(False, f"시도 중 오류: {type(exc).__name__}")
            log(str(last.message))
            if diag is not None:
                try:
                    diag.add_text(f"error/attempt_{attempt}.txt", repr(exc))
                except Exception:
                    pass
        if last.ok:
            return last
        if last.detail.get("reason") in ("cert_required",):
            return last
        time.sleep(max(retry_interval_ms, 100) / 1000.0)
    last.detail["attempts"] = attempt
    return last
