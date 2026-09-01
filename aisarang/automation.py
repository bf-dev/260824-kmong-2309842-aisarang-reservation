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

import json
import re
import time
from collections import deque

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
    # 네트워크 기록을 켠다. 이걸 안 켜면 driver.get_log("performance") 가 그냥
    # 예외를 던지고, capture() 의 network_*.json 이 **한 번도 만들어지지 않는다**
    # (고객 진단 ZIP 50개를 뒤져 확인했다: network_*.json 0건).
    # 그래서 [예약하기] 가 정말 서버로 아무것도 안 보내는지조차 확인할 수 없었다.
    # traceCategories 는 절대 넣지 않는다. 빈 문자열을 주면 chromedriver 가
    # "cannot parse traceCategories / cannot be empty" 로 **크롬을 아예 안 띄운다**
    # (실측: InvalidArgumentException, 크롬 149 / chromedriver 149).
    # 09시에 크롬이 안 뜨는 것보다 나쁜 실패는 없다.
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    opts.add_experimental_option("perfLoggingPrefs", {
        "enableNetwork": True,
        "enablePage": True,
    })

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
    install_net_recorder(driver, log)
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

_NET_RING = deque(maxlen=config.NET_RING_MAX)


def drain_network(driver, raise_on_error: bool = False) -> list:
    """chromedriver 의 performance 로그를 비워서 CDP 메시지 목록으로 돌려준다.

    두 가지 일을 한다.
      1. 우리가 볼 수 있게 파싱해서 돌려준다.
      2. **드라이버 쪽 버퍼를 비운다.** 09시까지 몇 시간을 대기하는 프로그램이라
         안 비우면 계속 쌓인다.
    돌려준 것과 별개로 마지막 config.NET_RING_MAX 건은 링버퍼에 남겨, capture()
    가 언제 불려도 직전 구간의 네트워크를 같이 담을 수 있게 한다.

    raise_on_error 는 진단 기록 모드가 쓴다. 삼켜버리면 브라우저가 이미 죽었는데도
    "잘 돌았다" 로 보여서, 죽은 세션에 계속 재시도하게 된다(실측으로 걸렸다).
    예약 경로(capture)에서는 기본값 그대로 조용히 넘어간다.
    """
    out = []
    try:
        entries = driver.get_log("performance")
    except Exception:
        if raise_on_error:
            raise
        return out
    for entry in entries or []:
        try:
            msg = json.loads(entry.get("message", "{}")).get("message", {})
        except Exception:
            continue
        if not msg:
            continue
        out.append(msg)
        _NET_RING.append(msg)
    return out


# 이 조각이 URL 에 들어 있으면 링버퍼에서 절대 버리지 않는다.
# 09시에 무슨 일이 있었는지 말해주는 유일한 줄들이다.
_NET_KEEP_ALWAYS = ("InsertOcreqst", "ts.wseq", "OccasionTime", "SelectTotalTime",
                    "SelectDupleTime", "/icms/occasion/")


def _network_digest(limit: int = config.NET_DIGEST_LIMIT) -> list:
    """링버퍼에서 요청/응답을 간추린다(본문 없음, 헤더 없음).

    v1.0.9 까지는 여기서 **마지막 300건만** 남겼다. 그래서 2026-09-01 캡처에서
    09시 훨씬 전에 발급된 가상대기열 티켓(opcode=5002)이 통째로 잘려 나갔고,
    "대기열 티켓이 없었다" 는 틀린 결론을 고객에게 보고했다(진짜 근거는
    sessionStorage 의 NetFunnel_ID 였다). 그래서 세 가지를 바꿨다.

      1. 상한을 300 → config.NET_DIGEST_LIMIT(1500) 으로 올린다. ZIP 이 94KB
         밖에 안 되므로 여유가 충분하다.
      2. 잘라야 할 때는 **앞과 뒤를 같이** 남긴다(가운데를 버린다). 페이지가
         뜰 때 벌어진 일과 발사 직후에 벌어진 일이 둘 다 필요하다.
      3. 예약/대기열 관련 줄은 어디에 있든 무조건 남긴다(_NET_KEEP_ALWAYS).
    """
    rows = []
    for msg in _NET_RING:
        method = msg.get("method", "")
        p = msg.get("params", {}) or {}
        if method == "Network.requestWillBeSent":
            r = p.get("request", {}) or {}
            rows.append({"id": p.get("requestId"), "kind": "request",
                         "method": r.get("method"), "url": r.get("url"),
                         "type": p.get("type"),
                         "hasPostData": bool(r.get("postData"))})
        elif method == "Network.responseReceived":
            r = p.get("response", {}) or {}
            rows.append({"id": p.get("requestId"), "kind": "response",
                         "status": r.get("status"), "url": r.get("url"),
                         "mime": r.get("mimeType")})
        elif method == "Network.loadingFailed":
            rows.append({"id": p.get("requestId"), "kind": "failed",
                         "error": p.get("errorText")})
    return _trim_middle(rows, limit)


def _is_key_row(row: dict) -> bool:
    url = row.get("url") or ""
    return any(k in url for k in _NET_KEEP_ALWAYS)


def _trim_middle(rows: list, limit: int) -> list:
    """상한을 넘으면 **가운데**를 버린다. 앞/뒤와 핵심 줄은 남긴다."""
    if limit <= 0 or len(rows) <= limit:
        return rows
    keep_idx = {i for i, r in enumerate(rows) if _is_key_row(r)}
    room = max(limit - len(keep_idx), 2)
    head = room // 2
    tail = room - head
    keep_idx |= set(range(min(head, len(rows))))
    keep_idx |= set(range(max(0, len(rows) - tail), len(rows)))
    out = []
    dropped = 0
    for i, r in enumerate(rows):
        if i in keep_idx:
            if dropped:
                out.append({"kind": "elided", "droppedEntries": dropped})
                dropped = 0
            out.append(r)
        else:
            dropped += 1
    if dropped:
        out.append({"kind": "elided", "droppedEntries": dropped})
    return out


# 페이지의 XHR/fetch 를 그대로 두고 **곁에서** 요청/응답 본문만 받아 적는다.
#
# 왜 필요한가. 2026-09-01 에 서버는 "1건 예약 중 1건 예약이 선예약으로 인해
# 예약되지 않았습니다." 를 돌려줬다. 사이트 스크립트가 화면에 찍는 것은
# `data.returnmsg` 하나뿐이고, 그 옆에 어떤 코드/필드가 같이 왔는지는
# **응답 본문에만** 있다. 그 본문이 진단 ZIP 에 없어서, 그 문구가 '자리를
# 뺏겼다' 인지 '중복 예약' 인지 가리는 데 캡처 네 개를 대조해야 했다.
#
# 안전 규칙(우선순위 순):
#   1. 고객 프로그램을 절대 망가뜨리지 않는다. 전부 try/catch 로 감싸고,
#      원래 핸들러를 교체하지 않는다(addEventListener 로 곁에 붙는다).
#   2. 응답을 건드리지 않는다. responseText 를 '읽기만' 한다.
#   3. 양을 묶는다. 요청 40건, 본문 20,000자.
#   4. 비밀번호로 보이는 필드는 값을 지운다.
_JS_NET_RECORDER = r"""
try {
  if (!window.__aisarangNet) {
    var LOG = window.__aisarangNet = [];
    var MAX_ROWS = 40, MAX_BODY = 20000;
    var WANT = ['InsertOcreqst', '/icms/occasion/', 'ts.wseq', 'OccasionTime'];
    function want(u){
      try { u = String(u || '');
        for (var i = 0; i < WANT.length; i++) { if (u.indexOf(WANT[i]) >= 0) return true; }
      } catch (e) {}
      return false;
    }
    function clip(v){
      try {
        v = (v === null || v === undefined) ? '' : String(v);
        // 비밀번호/인증서 값은 남기지 않는다.
        v = v.replace(/((?:pass|pwd|passwd|password|aResult|cert)[^=&]*=)[^&]*/gi, '$1[REDACTED]');
        if (v.length > MAX_BODY) {
          v = v.slice(0, MAX_BODY / 2) + '\n...[' + (v.length - MAX_BODY) +
              ' chars elided]...\n' + v.slice(v.length - MAX_BODY / 2);
        }
        return v;
      } catch (e) { return '[unreadable]'; }
    }
    function push(row){ try { if (LOG.length < MAX_ROWS) LOG.push(row); } catch (e) {} }

    var _open = XMLHttpRequest.prototype.open;
    var _send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) {
      try { this.__amethod = m; this.__aurl = u; } catch (e) {}
      return _open.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
      try {
        if (want(this.__aurl)) {
          var self = this, t0 = Date.now(), req = clip(body);
          self.addEventListener('loadend', function () {
            try {
              push({kind: 'xhr', method: self.__amethod, url: String(self.__aurl),
                    t0: t0, t1: Date.now(), status: self.status,
                    requestBody: req,
                    responseHeaders: clip(self.getAllResponseHeaders ?
                                          self.getAllResponseHeaders() : ''),
                    responseBody: clip(self.responseText)});
            } catch (e) {}
          });
        }
      } catch (e) {}
      return _send.apply(this, arguments);
    };

    if (window.fetch) {
      var _fetch = window.fetch;
      window.fetch = function (input, init) {
        var url = '';
        try { url = (typeof input === 'string') ? input : (input && input.url) || ''; } catch (e) {}
        // window 로 고정해서 부른다. `this` 를 그대로 넘기면, 엄격 모드 스크립트가
        // 맨몸으로 fetch(...) 를 부를 때 this 가 undefined 라서 크롬이
        // "Illegal invocation" 을 던진다. 즉 우리가 고객 페이지의 fetch 를
        // 망가뜨리게 된다. 1순위 규칙 위반이다.
        var p = _fetch.apply(window, arguments);
        try {
          if (want(url)) {
            var t0 = Date.now();
            p.then(function (r) {
              try {
                r.clone().text().then(function (txt) {
                  push({kind: 'fetch', url: String(url), t0: t0, t1: Date.now(),
                        status: r.status, responseBody: clip(txt)});
                }).catch(function () {});
              } catch (e) {}
              return r;
            }).catch(function () {});
          }
        } catch (e) {}
        return p;
      };
    }
  }
} catch (e) {}
"""


def install_net_recorder(driver, log=lambda *_: None) -> bool:
    """예약 POST 의 요청/응답 **본문**을 받아 적는 훅을 설치한다.

    새 문서마다 자동으로 다시 걸리도록 CDP 로 등록하고, 이미 떠 있는 문서에도
    한 번 바로 넣는다. 실패해도 예약 경로는 그대로 간다(진단만 얇아진다).
    """
    ok = False
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                               {"source": _JS_NET_RECORDER})
        ok = True
    except Exception as exc:  # noqa: BLE001
        log(f"네트워크 본문 기록기 등록 실패(무시): {type(exc).__name__}")
    try:
        driver.execute_script(_JS_NET_RECORDER)
        ok = True
    except Exception:
        pass
    return ok


def _page_net_bodies(driver) -> list:
    try:
        return driver.execute_script("return window.__aisarangNet || [];") or []
    except Exception:
        return []


def capture(driver, diag, label: str) -> None:
    """현재 페이지의 HTML / 쿠키 / 스토리지 / 네트워크를 진단 ZIP 에 담는다."""
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
    # 네트워크. v1.0.5 까지는 여기서 get_log("performance") 를 그냥 불렀는데,
    # 옵션에 goog:loggingPrefs 가 없어서 언제나 예외였다. 그래서 진단 ZIP 50개에
    # network_*.json 이 단 한 건도 없었다. 이제 옵션을 켜고 링버퍼로 받는다.
    try:
        drain_network(driver)
        diag.add_json(f"network_{label}.json", _network_digest())
    except Exception:
        pass
    # 예약 POST 의 요청/응답 **본문**. v1.0.9 ZIP 에 이게 없어서 서버 응답의
    # 코드/필드를 볼 수 없었다(NOTES.md v1.0.10 참고).
    try:
        bodies = _page_net_bodies(driver)
        if bodies:
            diag.add_json(f"xhr_bodies_{label}.json", bodies)
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


# 세션 유지 + 공짜 시계 점검.
#
# v1.0.10 에서 두 가지가 바뀌었다.
#   1) 대상이 `/?menuno=1`(무거운 JSP, 실측 왕복 0.8~1.1초) 에서
#      config.CLOCK_PROBE_PATH(실측 왕복 0.15초) 로 바뀌었다. 둘 다 같은 eGov
#      세션 필터를 지나므로 세션 유지 효과는 같고, 왕복이 좁을수록 점검이 좁다.
#   2) 응답 뒤 `document.cookie` 에서 egovLatestServerTime 을 읽는다. 이 쿠키는
#      HttpOnly 가 아니라(실측: path=/; secure; SameSite=None) JS 가 읽을 수
#      있고, **밀리초** 서버시각이다. Date 헤더(1초)보다 훨씬 좁은 점검이 된다.
_JS_TOUCH_SESSION = r"""
var cb = arguments[arguments.length - 1];
var path = arguments[0];
var t0 = Date.now();
function cookieMs(){
  try {
    var m = /(?:^|;\s*)egovLatestServerTime=(\d{10,16})/.exec(document.cookie || '');
    return m ? Number(m[1]) : null;
  } catch (e) { return null; }
}
var before = cookieMs();
function done(o){
  o.t0 = t0; o.t1 = Date.now();
  try {
    var now = cookieMs();
    o.serverMs = (now && now !== before) ? now : null;
  } catch (e) { o.serverMs = null; }
  try { cb(o); } catch (e) {}
}
try {
  fetch(path + (path.indexOf('?') >= 0 ? '&' : '?') + '_ka=' + t0,
        {method: 'HEAD', cache: 'no-store', credentials: 'same-origin'})
    .then(function (r) { done({ok: true, status: r.status,
                               date: r.headers.get('Date')}); })
    .catch(function (e) { done({ok: false, error: String(e)}); });
} catch (e) { done({ok: false, error: String(e)}); }
"""


def touch_session(driver, log=lambda *_: None) -> dict:
    """세션 유지용 가벼운 요청. **응답의 Date 헤더까지 받아온다.**

    실측: 로그인 직후 egovExpireSessionTime - egovLatestServerTime = 3,600,000ms.
    즉 세션은 마지막 활동 기준 60분이면 끊긴다. 전날 밤에 인증서 로그인을 해두는
    운영은 불가능하고, 09시 직전까지 세션을 살려둬야 한다.

    v1.0.6: 예전에는 XHR 을 쏘고 응답을 그냥 버렸다. 어차피 서버에 갔다 오는
    요청이므로 그 응답의 Date 헤더를 읽으면 공짜로 시계 점검이 하나 생긴다.
    같은 출처(same-origin) 라 헤더가 그대로 읽힌다. 이 값은 판정에만 쓰고
    오프셋을 직접 움직이지 않는다(clock.note_drift_sample 참고).

    돌려주는 것: {ok, dateEpoch, serverMs, t0, t1} (t0/t1/serverMs 는 로컬/서버
    epoch 초). serverMs 는 밀리초 해상도라 있으면 그쪽을 쓴다.
    """
    prev = None
    try:
        prev = driver.timeouts.script
    except Exception:
        prev = None
    try:
        driver.set_script_timeout(12)
    except Exception:
        pass
    try:
        raw = driver.execute_async_script(_JS_TOUCH_SESSION,
                                          config.CLOCK_PROBE_PATH) or {}
    except Exception as exc:  # noqa: BLE001
        # 여기서 실패해도 세션 유지 자체는 포기하지 않는다(옛 경로로 한 발).
        log(f"세션 유지 요청 실패(무시): {type(exc).__name__}")
        try:
            driver.execute_script(
                "try{var x=new XMLHttpRequest();"
                "x.open('HEAD','/?menuno=1&_ka='+Date.now(),true);x.send();}catch(e){}")
            return {"ok": True, "dateEpoch": None}
        except Exception:
            return {"ok": False, "dateEpoch": None}
    finally:
        try:
            if prev is not None:
                driver.set_script_timeout(prev)
        except Exception:
            pass

    out = {"ok": bool(raw.get("ok")), "dateEpoch": None, "serverMs": None,
           "status": raw.get("status"), "error": raw.get("error")}
    try:
        t0 = float(raw.get("t0") or 0) / 1000.0
        t1 = float(raw.get("t1") or 0) / 1000.0
        if t0 > 0 and t1 >= t0:
            out["t0"], out["t1"] = t0, t1
        from .clock import _parse_date_header
        stamp = _parse_date_header(raw.get("date") or "")
        if stamp is not None:
            out["dateEpoch"] = stamp
        # 밀리초 서버시각(쿠키). 있으면 점검 창이 1초 -> 왕복 폭으로 줄어든다.
        sms = raw.get("serverMs")
        if sms:
            v = float(sms) / 1000.0
            if 1_000_000_000.0 < v < 4_100_000_000.0:
                out["serverMs"] = v
    except Exception:
        pass
    return out


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


def handle_netfunnel(driver, log=lambda *_: None, max_wait: int = 60) -> bool:
    """넷퍼널(가상대기열) 레이어가 떠 있으면 사라질 때까지 기다린다.

    v1.0.7 까지 이 함수는 `"NetFunnel" not in driver.page_source` 로 판정했다.
    그런데 [예약하기] 를 누르면 사이트가 `netfunnel-pcms.js` 와
    `nf.childcare.go.kr:8443/ts.wseq?...&prefix=NetFunnel.gRtype=...` 스크립트
    태그를 **문서에 남긴다.** 그래서 대기열이 이미 지나갔는데도 문자열은
    계속 잡혔고, 반대로 진짜 대기 레이어가 떠 있어도 그 사실을 순번으로
    읽어내지 못했다. 이제는 **보이는 레이어**로 판정한다
    (`booking._JS_QUEUE`, 2026-08-26 고객 캡처의 실물 마크업).

    돌려주는 값: 대기열을 한 번이라도 봤는가.
    """
    from . import booking

    deadline = time.time() + max_wait
    seen = False
    last_log = 0.0
    while time.time() < deadline:
        q = booking.queue_info(driver)
        if not q.get("queue"):
            if seen:
                log("대기열을 통과했습니다.")
            return seen
        if not seen:
            seen = True
            log("가상대기열에 들어갔습니다. 순번을 기다립니다"
                "(다시 누르면 맨 뒤로 갑니다).")
        now = time.time()
        if now - last_log >= booking.QUEUE_LOG_SECONDS:
            last_log = now
            log(booking.queue_line(q))
        time.sleep(1.0)
    return seen


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
