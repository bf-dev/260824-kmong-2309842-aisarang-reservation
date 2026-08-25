# -*- coding: utf-8 -*-
"""진단 기록 모드 (Kmong 고객 2309842).

왜 필요한가
-----------
예약 화면의 뒷단계(반명/이용시간 → 날짜×시간 표 → [추가] → 선택표 → [예약하기]
→ '예약' 모달)의 **진짜 마크업을 우리는 아직 한 번도 본 적이 없다.**
그 UI 는 아동 라디오를 눌러야 오는 ajax 응답
(/icms/occasion/OccasionTimeMainSlPL.html 등) 안에 들어 있고, 그 화면은
공동인증서 세션에서만 열린다. 지금까지 올라온 고객 진단 ZIP 6건은 전부
"09시 오픈까지 대기 중" 에서 멈춰 거기까지 가지 않았다.

그래서 **사람이 손으로 끝까지 걸어가고 우리는 옆에서 받아적기만 하는** 모드를
만든다. 설계 원칙은 셋뿐이다.

  1. **아무것도 누르지 않는다.** 첫 화면을 여는 것 말고는 클릭도, 자동 진행도,
     자동 닫기도, 자동 제출도 없다. 예약을 만들 수 있는 코드 경로가 이 모드에는
     아예 존재하지 않는다.
  2. **사람을 방해하지 않는다.** 기록은 별도 스레드에서 돌고, 실패는 전부
     삼키고 계속한다. 사람이 빠르게 클릭하든, 기록 도중에 페이지를 넘기든,
     레이어를 열었다 닫든, 브라우저를 닫아버리든 오류창이 뜨지 않는다.
  3. **잃지 않는다.** 중지 버튼을 누를 때만이 아니라 주기적으로도 올린다.
     PC 가 꺼져도 그때까지 모은 것은 서버에 가 있다.

무엇을 남기는가
---------------
  record/summary.json    타임라인 요약(방문 URL, 기록 건수, 놓친 것)
  record/network.json    모든 요청/응답의 URL·상태·헤더(본문 제외)
  record/wanted/*.html   우리가 못 본 그 세 개의 ajax 응답 본문
  record/bodies/*.txt    그 밖의 텍스트 응답 본문(개수/크기 제한)
  record/clicks.json     사람이 무엇을 눌렀는지(선택자/글자), 순서 재현용
  record/console.json    브라우저 콘솔
  page_source/*.html     화면이 바뀔 때마다의 DOM 전체(레이어 열림 포함)
  cookies_record.json    쿠키 **이름만**. 값은 담지 않는다.

개인정보: 나가는 모든 문자열은 reporter.Diagnostics.add_text() 한 지점에서
masking.mask() 를 통과한다. 그 위에 이 모듈이 화면에서 읽은 아동명/보호자명을
register_secret() 으로 등록해 문자열째로 지운다. 쿠키 값은 애초에 담지 않는다.
"""
from __future__ import annotations

import json
import re
import threading
import time

from . import automation, config
from .masking import register_secret
from .reporter import Diagnostics

# 우리가 아직 못 본 화면을 실어오는 응답들. 이것만은 무슨 일이 있어도 남긴다.
WANTED_URLS = (
    "SelectOccasionChild.html",
    "OccasionTimeMainSlPL.html",
    "OccasionTimeMainPiIs.html",
)

TEXT_MIME = re.compile(r"(text/|json|xml|javascript|html|urlencoded)", re.I)

# ZIP 항목 수는 reporter.MAX_ENTRIES(120) 에서 잘린다. 넘치면 **나중에 담긴 것이
# 조용히 버려진다**. 우리가 제일 잃으면 안 되는 것(찾던 응답 + 요약/네트워크)은
# 나중에 담기므로, 화면/본문 쪽에 여유를 남겨둔다. 40 + 40 + 나머지 < 120.
MAX_PAGES = 40                  # page_source 최대 장수
MAX_BODIES = 40                 # 따로 저장하는 본문 최대 개수
MAX_BODY_CHARS = 300_000
FLUSH_SECONDS = 300             # 주기적 업로드(서버 시각 재측정과 같은 5분)
PUMP_SECONDS = 1.0
DEAD_ROUNDS = 3                 # 이만큼 연속으로 아무것도 못 하면 끊긴 것으로 본다

# 사람이 무엇을 눌렀는지만 받아적는다. 어떤 것도 대신 누르지 않는다.
_INTERACTION_JS = r"""
(function () {
  var qn = "__QUEUE__";
  if (Object.prototype.hasOwnProperty.call(window, qn)) return;
  var q = { q: [], drain: function () { var a = this.q; this.q = []; return a; } };
  Object.defineProperty(window, qn, {value: q, enumerable: false});
  function sel(el) {
    try {
      if (!el || !el.tagName) return '';
      var s = el.tagName.toLowerCase();
      if (el.id) return s + '#' + el.id;
      if (el.name) return s + '[name=' + el.name + ']';
      if (el.className && typeof el.className === 'string') {
        var c = el.className.trim().split(/\s+/).slice(0, 3).join('.');
        if (c) s += '.' + c;
      }
      return s;
    } catch (e) { return ''; }
  }
  ['click', 'change', 'submit'].forEach(function (t) {
    document.addEventListener(t, function (e) {
      try {
        var el = e.target;
        q.q.push({ts: Date.now(), type: t, tag: el.tagName || '',
                  selector: sel(el),
                  text: ((el.innerText || el.value || '') + '').slice(0, 120),
                  url: location.href});
      } catch (err) {}
    }, true);
  });
})();
"""

# 화면이 "의미 있게" 바뀌었는지 보는 지문. 길이만 보면 광고/시계 때문에 매초
# 바뀐다. 표 개수, 보이는 레이어, 버튼 글자를 함께 본다.
_FINGERPRINT_JS = r"""
function vis(e){
  try {
    var r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    var s = window.getComputedStyle(e);
    return s.visibility !== 'hidden' && s.display !== 'none';
  } catch (err) { return false; }
}
var tables = document.querySelectorAll('table').length;
var rows = document.querySelectorAll('tr').length;
var boxes = document.querySelectorAll('input[type=checkbox],input[type=radio]').length;
var opens = [];
var pops = document.querySelectorAll('[class*=popup],[class*=pop_],[class*=layer],[role=dialog]');
for (var i = 0; i < pops.length; i++) {
  if (vis(pops[i])) opens.push((pops[i].id || pops[i].className || '').toString().slice(0, 40));
}
var body = document.body ? (document.body.innerText || '') : '';
var marks = ['반명', '이용시간', '날짜/시간', '추가', '예약하기', '예약하시겠습니까',
             '예약시간전', '정원초과'];
var seen = [];
for (var m = 0; m < marks.length; m++) if (body.indexOf(marks[m]) >= 0) seen.push(marks[m]);
return {url: location.href, tables: tables, rows: rows, boxes: boxes,
        opens: opens.join('|'), seen: seen.join('|'), len: body.length};
"""

# 화면에 있는 사람 이름을 찾아 마스킹 대상으로 등록하기 위한 것.
# (읽어서 지우려는 것이지 저장하려는 것이 아니다.)
_NAMES_JS = r"""
var out = [];
function push(v) { if (v) out.push(String(v)); }
var rs = document.querySelectorAll("input[type=radio][name=occasionChk]");
for (var i = 0; i < rs.length; i++) {
  push((rs[i].getAttribute('title') || '').replace(/선택\s*$/, ''));
  var tr = rs[i].closest('tr');
  if (tr) {
    var a = tr.querySelector('a');
    if (a) push((a.innerText || a.textContent || '').trim());
  }
}
var me = document.querySelector('.my_account a, .member .my_account a');
if (me) push((me.innerText || me.textContent || '').trim());
return out;
"""

_NAME_OK = re.compile(r"^[가-힣]{2,4}$")
_NAME_SKIP = {"로그인", "로그아웃", "마이룸", "아동선택", "아동", "선택", "예약",
              "이용", "신청", "정보", "확인", "취소", "검색", "조회"}


class DiagRecorder:
    """수동 조작을 방해하지 않고 화면/네트워크/DOM 을 계속 받아적는다."""

    def __init__(self, log=lambda *_: None, status=lambda *_: None,
                 diag: Diagnostics | None = None):
        self.log = log
        self.status = status
        self.diag = diag or Diagnostics()
        self.driver = None
        self.running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._queue_name = "__aisarang_rec_" + str(int(time.time()))
        self.reqs: dict = {}
        self.order: list = []
        self.clicks: list = []
        self.console: list = []
        self.visited: list = []
        self.pages = 0
        self.bodies = 0
        self.wanted_seen: list = []
        self.skipped: list = []
        self.started_at = 0.0
        self._last_print = ""
        self._last_flush = 0.0
        self._names: set = set()
        self._dead_rounds = 0

    # ------------------------------------------------------------ 시작
    def is_running(self) -> bool:
        return bool(self.running and self._thread and self._thread.is_alive())

    def start(self, start_url: str | None = None) -> bool:
        if self.is_running():
            self.log("이미 진단 기록 중입니다.")
            return True
        try:
            # 앞선 기록에서 쓰던 크롬이 이미 닫혔을 수 있다(고객이 창을 닫고
            # 다시 [진단 기록 시작] 을 누르는 것은 아주 자연스러운 순서다).
            # 살아 있는지 한 번 찔러보고, 죽었으면 새로 띄운다.
            if self.driver is not None:
                try:
                    self.driver.execute_script("return 1;")
                except Exception:
                    self.driver = None
            if self.driver is None:
                self.status("크롬을 실행합니다(진단 기록)...")
                self.driver = automation.build_driver(log=self.log)
            self._enable_cdp()
            self.started_at = time.time()
            self._last_flush = time.time()
            self._dead_rounds = 0
            self.running = True
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="diag-recorder")
            self._thread.start()
            url = start_url or (config.BASE_URL + config.SEARCH_PAGE)
            try:
                self.driver.get(url)
            except Exception as exc:  # noqa: BLE001
                self._skip("first_get", exc)
            self.log("진단 기록을 시작했습니다. 이제 크롬 창에서 평소처럼 "
                     "손으로 진행해 주세요.")
            self.log("  (프로그램은 아무것도 누르지 않습니다. 보고 받아적기만 합니다.)")
            self.status("진단 기록 중입니다. 예약 확인창까지 가신 뒤 [기록 중지] 를 눌러주세요.")
            return True
        except Exception as exc:  # noqa: BLE001
            self.running = False
            self.log(f"진단 기록을 시작하지 못했습니다: {type(exc).__name__}: {exc}")
            self.status("진단 기록을 시작하지 못했습니다.")
            return False

    def _enable_cdp(self) -> None:
        try:
            self.driver.execute_cdp_cmd("Network.enable", {
                "maxTotalBufferSize": 32 * 1024 * 1024,
                "maxResourceBufferSize": 16 * 1024 * 1024,
            })
        except Exception as exc:  # noqa: BLE001
            self._skip("network_enable", exc)
        try:
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": _INTERACTION_JS.replace("__QUEUE__", self._queue_name)})
        except Exception as exc:  # noqa: BLE001
            self._skip("inject_interaction", exc)
        try:
            self.driver.execute_script(
                _INTERACTION_JS.replace("__QUEUE__", self._queue_name))
        except Exception:
            pass

    # ------------------------------------------------------------ 본 루프
    def _loop(self) -> None:
        while self.running:
            try:
                self._pump()
            except Exception as exc:  # noqa: BLE001
                # 여기서 죽으면 기록이 끊긴다. 무슨 일이 있어도 계속 돈다.
                self._skip("pump", exc)
            time.sleep(PUMP_SECONDS)

    def _pump(self) -> None:
        alive = True
        worked = False
        for step, fn in (("network", self._pump_network),
                         ("console", self._pump_console),
                         ("clicks", self._pump_clicks),
                         ("screen", self._pump_screen)):
            try:
                fn()
                worked = True
            except Exception as exc:  # noqa: BLE001
                self._skip(step, exc)
                if _is_gone(exc):
                    alive = False
                    break
        # 메시지로 못 알아본 끊김도 있다(크롬드라이버가 통째로 사라지면
        # urllib3 의 연결거부가 올라온다). 한 바퀴에서 **아무 것도** 성공하지
        # 못한 상태가 이어지면 그냥 끊긴 것으로 본다. 여기서 멈추지 않으면
        # 죽은 세션에 1초마다 영원히 재시도한다.
        if alive and not worked:
            self._dead_rounds += 1
            if self._dead_rounds >= DEAD_ROUNDS:
                alive = False
        elif worked:
            self._dead_rounds = 0
        if not alive:
            self.log("크롬 창이 닫힌 것 같습니다. 지금까지 기록한 것을 올립니다.")
            self.running = False
            try:
                self._flush("browser_closed", blocking=True)
            except Exception:
                pass
            return
        if time.time() - self._last_flush >= FLUSH_SECONDS:
            self._last_flush = time.time()
            try:
                self._flush("periodic")
            except Exception as exc:  # noqa: BLE001
                self._skip("flush", exc)

    # -- 네트워크 -----------------------------------------------------
    def _pump_network(self) -> None:
        for msg in automation.drain_network(self.driver, raise_on_error=True):
            try:
                self._handle_net(msg.get("method", ""), msg.get("params", {}) or {})
            except Exception as exc:  # noqa: BLE001
                self._skip("handle_net", exc)

    def _handle_net(self, method: str, params: dict) -> None:
        rid = params.get("requestId")
        if not rid:
            return
        rec = self.reqs.get(rid)
        if rec is None:
            rec = {"id": rid, "url": None, "method": None, "status": None,
                   "mime": None, "reqHeaders": {}, "respHeaders": {},
                   "postData": None, "type": None, "failed": None,
                   "bodySaved": None, "bytes": 0}
            self.reqs[rid] = rec
            self.order.append(rid)
        if method == "Network.requestWillBeSent":
            r = params.get("request", {}) or {}
            rec["url"] = r.get("url")
            rec["method"] = r.get("method")
            rec["postData"] = r.get("postData")
            rec["type"] = params.get("type")
            rec["reqHeaders"].update(r.get("headers") or {})
        elif method == "Network.requestWillBeSentExtraInfo":
            rec["reqHeaders"].update(params.get("headers") or {})
        elif method == "Network.responseReceived":
            resp = params.get("response", {}) or {}
            rec["status"] = resp.get("status")
            rec["mime"] = resp.get("mimeType")
            rec["url"] = rec["url"] or resp.get("url")
            rec["respHeaders"].update(resp.get("headers") or {})
        elif method == "Network.responseReceivedExtraInfo":
            rec["respHeaders"].update(params.get("headers") or {})
        elif method == "Network.loadingFailed":
            rec["failed"] = params.get("errorText")
        elif method == "Network.loadingFinished":
            self._save_body(rec)

    def _save_body(self, rec: dict) -> None:
        url = str(rec.get("url") or "")
        if not url or rec.get("bodySaved") is not None:
            return
        wanted = any(w in url for w in WANTED_URLS)
        mime = str(rec.get("mime") or "")
        if not wanted:
            if self.bodies >= MAX_BODIES:
                rec["bodySaved"] = "capped"
                return
            if not TEXT_MIME.search(mime):
                rec["bodySaved"] = "not_text"
                return
            if "childcare.go.kr" not in url and not url.startswith("http://127.0.0.1"):
                rec["bodySaved"] = "other_origin"
                return
        try:
            out = self.driver.execute_cdp_cmd("Network.getResponseBody",
                                              {"requestId": rec["id"]})
        except Exception as exc:  # noqa: BLE001
            rec["bodySaved"] = f"error: {type(exc).__name__}"
            return
        body = out.get("body") or ""
        if out.get("base64Encoded"):
            rec["bodySaved"] = "binary"
            return
        rec["bytes"] = len(body)
        name = _safe_name(url)
        if wanted:
            self.wanted_seen.append({"url": url, "bytes": len(body)})
            self.diag.add_text(f"record/wanted/{len(self.wanted_seen):02d}_{name}.html",
                               body[:MAX_BODY_CHARS])
            rec["bodySaved"] = "wanted"
            self.log(f"찾던 화면을 받아적었습니다: {name} ({len(body):,}자)")
            self.status(f"기록 중 · 찾던 응답 {len(self.wanted_seen)}건 확보")
        else:
            self.bodies += 1
            self.diag.add_text(f"record/bodies/{self.bodies:03d}_{name}.txt",
                               body[:MAX_BODY_CHARS])
            rec["bodySaved"] = "saved"

    # -- 콘솔 / 클릭 --------------------------------------------------
    def _pump_console(self) -> None:
        try:
            for row in self.driver.get_log("browser"):
                self.console.append(row)
        except Exception:
            pass
        if len(self.console) > 500:
            del self.console[:200]

    def _pump_clicks(self) -> None:
        drained = self.driver.execute_script(
            "var q = window[arguments[0]]; return (q && q.drain) ? q.drain() : [];",
            self._queue_name) or []
        if drained:
            self.clicks.extend(drained)
            if len(self.clicks) > 2000:
                del self.clicks[:500]

    # -- 화면 ---------------------------------------------------------
    def _pump_screen(self) -> None:
        fp = self.driver.execute_script("return (function(){" + _FINGERPRINT_JS
                                        + "})();") or {}
        url = str(fp.get("url") or "")
        if url and url not in self.visited:
            self.visited.append(url)
            self._register_names()
            try:
                self.driver.execute_script(
                    _INTERACTION_JS.replace("__QUEUE__", self._queue_name))
            except Exception:
                pass
        key = json.dumps([fp.get("url"), fp.get("tables"), fp.get("rows"),
                          fp.get("boxes"), fp.get("opens"), fp.get("seen")],
                         ensure_ascii=False)
        if key == self._last_print:
            return
        self._last_print = key
        label = _label_for(fp)
        self._snapshot(label, fp)

    def _snapshot(self, label: str, fp: dict) -> None:
        if self.pages >= MAX_PAGES:
            return
        try:
            html = self.driver.page_source
        except Exception as exc:  # noqa: BLE001
            self._skip("page_source", exc)
            return
        self.pages += 1
        try:
            self.diag.add_page(f"{self.pages:02d}_{label}",
                               str(fp.get("url") or ""), html)
        except Exception as exc:  # noqa: BLE001
            self._skip("add_page", exc)
        seen = str(fp.get("seen") or "")
        if seen:
            self.log(f"화면이 바뀌었습니다({label}): {seen}")

    def _register_names(self) -> None:
        """화면에 보이는 사람 이름을 마스킹 대상으로 등록한다(지우기 위해서다)."""
        try:
            for raw in (self.driver.execute_script(
                    "return (function(){" + _NAMES_JS + "})();") or []):
                name = str(raw).strip()
                if not _NAME_OK.match(name) or name in _NAME_SKIP:
                    continue
                if name in self._names:
                    continue
                self._names.add(name)
                register_secret(name)
        except Exception:
            pass

    # ------------------------------------------------------------ 정리
    def _skip(self, where: str, exc: Exception) -> None:
        row = {"at": round(time.time(), 3), "where": where,
               "error": f"{type(exc).__name__}: {exc}"[:200]}
        with self._lock:
            self.skipped.append(row)
            if len(self.skipped) > 300:
                del self.skipped[:100]

    def summary(self) -> dict:
        return {
            "customerId": config.CUSTOMER_ID,
            "appVersion": config.APP_VERSION,
            "mode": "diag_record",
            "startedAt": self.started_at,
            "elapsedSec": round(time.time() - self.started_at, 1)
            if self.started_at else 0,
            "visited": self.visited[-40:],
            "requests": len(self.order),
            "pages": self.pages,
            "bodies": self.bodies,
            "clicks": len(self.clicks),
            "wanted": self.wanted_seen,
            "wantedTargets": list(WANTED_URLS),
            "skipped": self.skipped[-60:],
            "namesRedacted": len(self._names),
        }

    def _network_rows(self) -> list:
        rows = []
        for rid in self.order[-800:]:
            rec = self.reqs.get(rid) or {}
            rows.append({k: rec.get(k) for k in
                         ("url", "method", "status", "mime", "type", "failed",
                          "bodySaved", "bytes", "postData")}
                        | {"reqHeaders": _clean_headers(rec.get("reqHeaders")),
                           "respHeaders": _clean_headers(rec.get("respHeaders"))})
        return rows

    def _cookie_names(self) -> list:
        """쿠키는 **이름만** 담는다. 세션 값은 절대 담지 않는다."""
        out = []
        try:
            for c in self.driver.get_cookies():
                out.append({"name": c.get("name"), "domain": c.get("domain"),
                            "path": c.get("path"), "httpOnly": c.get("httpOnly"),
                            "secure": c.get("secure"),
                            "valueLength": len(str(c.get("value") or ""))})
        except Exception:
            pass
        return out

    def _flush(self, why: str, blocking: bool = False) -> None:
        """지금까지 모은 것을 ZIP 으로 올린다. 중지 때만이 아니라 주기적으로도."""
        s = self.summary()
        s["flushReason"] = why
        self.diag.add_json("record/summary.json", s)
        self.diag.add_json("record/network.json", self._network_rows())
        self.diag.add_json("record/clicks.json", self.clicks[-500:])
        self.diag.add_json("record/console.json", self.console[-200:])
        self.diag.add_json("cookies_record.json", self._cookie_names())
        meta = {"mode": "diag_record", "result": why,
                "requests": s["requests"], "pages": s["pages"],
                "wanted": len(self.wanted_seen), "clicks": s["clicks"]}
        self.diag.upload(
            f"진단 기록({why}): 페이지 {s['pages']}장 / 요청 {s['requests']}건 / "
            f"찾던 응답 {len(self.wanted_seen)}건", meta, blocking=blocking)
        self.log(f"진단 기록을 서버로 보냈습니다({why}): 페이지 {s['pages']}장, "
                 f"요청 {s['requests']}건, 찾던 응답 {len(self.wanted_seen)}건")

    def stop(self) -> dict:
        """기록을 멈추고 마지막으로 한 번 더 올린다. 크롬 창은 닫지 않는다."""
        self.running = False
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=6)
        try:
            self._pump_network()
        except Exception:
            pass
        try:
            self._snapshot("final", self.driver.execute_script(
                "return (function(){" + _FINGERPRINT_JS + "})();") or {})
        except Exception as exc:  # noqa: BLE001
            self._skip("final_snapshot", exc)
        s = self.summary()
        try:
            # 마지막 한 번은 끝까지 기다린다. "보냈습니다" 라고 말하려면
            # 실제로 갔는지 확인한 뒤여야 한다(백그라운드 스레드는 프로그램을
            # 그대로 닫으면 사라진다).
            self._flush("stopped", blocking=True)
        except Exception as exc:  # noqa: BLE001
            self._skip("final_flush", exc)
            self.log("진단 기록 업로드에 실패했습니다(무시하고 계속합니다).")
        self.status(f"진단 기록을 마쳤습니다. 페이지 {s['pages']}장 / "
                    f"찾던 응답 {len(self.wanted_seen)}건")
        return s


def _is_gone(exc: Exception) -> bool:
    """크롬 창이 닫혔거나 세션이 끊긴 오류인가.

    창을 닫으면 셀레니움이 "no such window / invalid session id" 를 준다.
    그런데 크롬드라이버 프로세스까지 사라지면 그런 말은 아예 안 나오고
    **연결 거부**만 올라온다. 그것까지 여기서 알아봐야 죽은 세션에 1초마다
    영원히 재시도하지 않는다(실측: 테스트에서 그렇게 돌았다).
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(k in text for k in ("invalid session id", "no such window",
                                   "target window already closed",
                                   "web view not found", "disconnected",
                                   "chrome not reachable",
                                   "connection refused", "max retries exceeded",
                                   "failed to establish a new connection",
                                   "connection aborted", "remote end closed",
                                   "session deleted", "unable to connect",
                                   "newconnectionerror", "connectionerror"))


def _clean_headers(headers) -> dict:
    """헤더에서 쿠키/인증 값은 이름만 남기고 지운다."""
    out = {}
    try:
        for k, v in (headers or {}).items():
            lk = str(k).lower()
            if lk in ("cookie", "set-cookie", "authorization", "proxy-authorization"):
                names = []
                for part in str(v).split(";"):
                    n = part.split("=", 1)[0].strip()
                    if n:
                        names.append(n)
                out[k] = "<값 제거됨: " + ", ".join(names[:12]) + ">"
            else:
                out[k] = v
    except Exception:
        return {}
    return out


def _safe_name(url: str) -> str:
    tail = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "index"
    tail = re.sub(r"[^A-Za-z0-9._-]", "_", tail)[:60]
    return tail or "page"


def _label_for(fp: dict) -> str:
    seen = str(fp.get("seen") or "")
    if "예약하시겠습니까" in seen:
        return "modal_open"
    if "예약하기" in seen:
        return "after_add_and_tick"
    if "날짜/시간" in seen:
        return "grid"
    if "반명" in seen or "이용시간" in seen:
        return "useinfo"
    if fp.get("opens"):
        return "layer_open"
    return "page"
