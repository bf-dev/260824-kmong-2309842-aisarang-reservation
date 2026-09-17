# -*- coding: utf-8 -*-
"""'예약시간전' 회복을 **실물 캡처 + 진짜 크롬 + 진짜 서버 응답**으로 끝까지 돌린다.

왜 이 파일이 따로 있나 (v1.0.15)
------------------------------------------------------------------
v1.0.15 는 조준 여유를 250 → 175ms 로 당겼다. 당긴 만큼 이른 쪽으로 틀릴
확률이 올라가고, 그 방향의 실패가 '아침을 잃는 것' 이 아니라 '한 번 더 쏘는
것' 이어야 이 조준이 정당해진다. 즉 **회복 경로가 이번 판의 안전망 그 자체**다.

기존 시험들은 이 경로를 조각으로만 봤다.
  tests/test_handover.py   `_Reopen` 게이트 + 실물 마크업에서 무엇이 눌리는가
                           (단, 회복 후 **다시 쏴서 성공하는** 왕복은 가짜 시계와
                            스크립트된 상태로만 본다)
  main.py --handovertest   `fnSave=1 alertClosed=1 confirmClicked=0` 한 컷

이 파일은 그 사이를 잇는다. 한 브라우저 안에서:

  1. 사람이 만들어 둔 확인창(modal_open.html 실물) 위에서 [확인] 을 쏜다
  2. 서버가 **정각 전** 이라 '아직 예약 가능한 시간이 아닙니다.' 로 답한다
     (2026-08-27 09:00:00 의 서버 원문 returnmsg, 실물 응답 본문으로 내려준다)
  3. handover.burst 가 스스로 알림을 닫고 [예약하기] 를 다시 눌러 확인창을
     되살린다. 사이트의 진짜 fnSave → icmsLayerPopup.confirm2 경로를 그대로
     재현해 확인창이 실제로 다시 열린다.
  4. 정각을 넘겼으므로 서버가 이번에는 성공 원문으로 답한다
     ('1건 예약 중 1건 예약되었습니다.' = 2026-09-03 09:00:00 실물)
  5. burst 가 reserved 로 끝난다

즉 "이른 한 발은 잃은 아침이 아니라 재시도다" 를 실물로 증명한다.

시계만 가짜다. 09:00:00 을 기다릴 수 없기 때문이다(그래서 open_epoch 를
지금으로 놓고 첫 발을 정각 직전에 쏜다). 페이지, 마크업, 서버 응답 본문,
분류기, 회복 경로, 재발사는 전부 출하되는 그 코드다.

    python ci/too_early_retry_check.py            # 크롬 필요
"""
from __future__ import annotations

import functools
import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from aisarang import automation, booking, handover  # noqa: E402

REAL = os.path.join(HERE, "fixtures", "real")


def _out(line: str = "") -> None:
    """한글이 섞여도 죽지 않는 출력.

    windows-latest 러너에서 이 스크립트의 stdout 은 cp1252 다. 그대로 한글을
    찍으면 UnicodeEncodeError 로 **시험 자체가** 죽는다(2026-09-17 CI 실측:
    제품은 멀쩡한데 이 하네스가 그 이유로 빨간불이었다). main.py 의 `_out` 과
    같은 처리를 한다: 못 찍는 글자만 대체하고 줄은 반드시 남긴다.
    판정에 쓰는 `RETRY...` 줄은 전부 ASCII 라 이 대체에 걸리지 않는다.
    """
    if sys.stdout is None:
        return
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        return
    except Exception:
        pass
    try:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        safe = (line + "\n").encode(enc, "replace").decode(enc, "replace")
        sys.stdout.write(safe)
        sys.stdout.flush()
    except Exception:
        pass

# 서버 원문 그대로. 지어낸 글자를 쓰지 않는다(v1.0.8 의 순환논증을 되돌리지 않기 위해).
TOO_EARLY_BODY = json.dumps(
    {"returnmsg": booking.TOO_EARLY_REAL, "returnval": ""}, ensure_ascii=False)
OK_BODY = json.dumps(
    {"returnmsg": booking.OK_REAL, "returnval": "success"}, ensure_ascii=False)

# 사이트의 진짜 예약 확인창을 다시 여는 스크립트.
#
# 실물 `fnSave()` 는 NetFunnel_Action → insertOcreqst() → icmsLayerPopup.confirm2
# 였다(ci/fixtures/real/modal_open.raw.html:2397 원문). 픽스처에서는 넷퍼널과
# 사이트 번들이 제거돼 있으므로, **확인창을 여는 부분과 [확인] 콜백이 예약을
# POST 하는 부분**만 같은 모양으로 되살린다. 대기열은 이 시험의 대상이 아니다
# (대기열이 뜨면 되살리기가 영구히 잠기는 것은 test_handover.py 가 본다).
_JS_SITE = r"""
window.__fnSave = 0;
window.__submits = 0;

function _visible(e) {
  if (!e) return false;
  var r = e.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

function _shell() {
  // 껍데기는 페이지에 두 벌 있고 id 가 중복이다. 지금 보이는 쪽을 쓰고,
  // 둘 다 숨어 있으면(확인창이 소비된 직후) 첫 번째를 되살린다.
  var shells = document.querySelectorAll("[id='layer-confirm-popup2']");
  for (var i = 0; i < shells.length; i++) {
    if (_visible(shells[i])) return shells[i];
  }
  return shells[0] || null;
}

function _openConfirm() {
  var shell = _shell();
  if (!shell) return false;
  var p = shell.querySelector("[id='layer-confirm-popup-contents2']");
  if (p) p.innerHTML = '예약하시겠습니까?';
  shell.style.display = 'block';
  var ok = shell.querySelector("[id='layer-confirm-popup-confirm2']");
  if (!ok) return false;
  // 사이트의 confirm2 콜백과 같은 자리: [확인] 을 누르면 예약이 POST 된다.
  ok.onclick = function () {
    shell.style.display = 'none';        // 확인창은 한 발에 소비된다
    window.__submits++;
    var x = new XMLHttpRequest();
    x.open('POST', '/icms/occasion/InsertOcreqst.html', true);
    x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    x.onreadystatechange = function () {
      if (x.readyState !== 4) return;
      var data = {};
      try { data = JSON.parse(x.responseText); } catch (e) {}
      // 사이트와 같은 자리에 같은 문구를 찍는다(alert2).
      var al = document.querySelectorAll("[id='layer-alert-popup2']")[0];
      if (al) {
        var ap = al.querySelector("[id='layer-alert-popup-contents2']");
        if (ap) ap.textContent = data.returnmsg || '';
        al.style.display = 'block';
      }
    };
    x.send('resgb=R');
    return false;
  };
  return true;
}

// [예약하기] 의 진짜 onclick 은 fnSave() 다. 그 이름 그대로 걸어둔다.
window.fnSave = function () {
  window.__fnSave++;
  _openConfirm();
};

// 캡처는 확인창이 **이미 떠 있는** 순간이다(사람이 [예약하기] 를 눌러 둔 화면).
// 그 창의 [확인] 에도 사이트와 같은 콜백이 걸려 있어야 첫 발이 예약을 POST 한다.
// 이것을 빼먹으면 첫 발이 아무것도 보내지 않고 확인창 본문만 읽혀 unknown 이 된다.
_openConfirm();
return true;
"""


class _Handler(SimpleHTTPRequestHandler):
    """픽스처를 내주고, 예약 POST 에는 '정각 전/후' 에 맞는 실물 원문을 답한다.

    `server_open` 은 **서버 자기 시계의 정각**이다. 우리가 믿는 정각
    (`_Clock` 에 주는 open_epoch)과 일부러 다르게 둘 수 있고, 그 차이가
    실전에서 '예약시간전' 을 두 번 이상 맞는 유일한 경로다: 우리 시계로는
    정각을 넘겼는데 서버는 아직 아니라고 답하는 상황.
    """

    server_open = 0.0
    posts = []

    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        if "InsertOcreqst" not in self.path:
            return self._send(404, "text/plain", b"no")
        # 이것이 이 시험의 핵심 한 줄이다. 서버는 자기 시계로 정각 전에
        # 닿은 요청을 거절한다(2026-08-27 실측). 정각을 넘기면 받아준다.
        early = time.time() < type(self).server_open
        body = TOO_EARLY_BODY if early else OK_BODY
        type(self).posts.append({"early": early, "at": time.time()})
        return self._send(200, "application/json;charset=UTF-8",
                          body.encode("utf-8"))


class _Clock:
    """서버 시각을 흉내내는 시계. 다만 **추정 오차를 일부러 넣는다**.

    `skew` 는 "우리가 실제보다 늦게 도착했다고 믿는 양" 이다. 실전에서 이른
    쪽 실패가 생기는 이유가 정확히 이것이다: 우리 추정으로는 정각 뒤에
    도착했는데 서버 시계로는 아직 전이었다. 그 상황이어야
    `note_too_early` 가 배울 것이 있다(추정 오프셋이 0 이상일 때만 새 정보다).

    skew 를 0 으로 두면 우리가 "일부러 앞당겨 쐈다" 는 뜻이 되고, 그때
    '예약시간전' 은 당연한 답이라 아무것도 배우지 않는 것이 맞다.

    `note_too_early` 는 **제품의 clock.ClockSync 것을 그대로** 빌려 부른다.
    이 판에서 '매 발 보정' 으로 바꾼 그 경로가 실제로 도는지 같이 보기 위해서다.
    """

    def __init__(self, open_epoch: float, skew: float = 0.0):
        self.open_epoch = open_epoch
        self.skew = float(skew)
        self.correction = 0.0
        self.correction_notes = []
        self.learned = []

    def server_now(self) -> float:
        return time.time()

    def arrival_for_local_fire(self, local_epoch: float) -> float:
        # 우리 추정. skew 만큼 낙관적이다(실제보다 늦게 도착했다고 믿는다).
        return local_epoch + self.skew

    def note_too_early(self, est_arrival_offset: float, margin: float = 0.03):
        from aisarang.clock import ClockSync
        delta = ClockSync.note_too_early(self, est_arrival_offset, margin)
        if delta:
            self.learned.append(round(delta * 1000, 1))
        return delta


def _driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    o = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1400,1200",
              "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"):
        o.add_argument(a)
    return webdriver.Chrome(options=o)


def _case(name: str, server_lag: float, skew: float, want_shots: int,
          terminal: str, log) -> dict:
    """한 번의 시나리오를 실물 브라우저로 끝까지 돌리고 결과를 돌려준다.

    server_lag  **서버의 정각이 우리가 믿는 정각보다 얼마나 늦은지**(초).
                0.4 면 우리 시계로 정각 +0ms 인 순간에 서버는 아직 400ms 전
                이다. 이 값이 클수록 '예약시간전' 을 여러 번 맞는다. 되살리기
                게이트는 **우리가 믿는 정각 이후**에만 열리므로(조건 6),
                반복 회복을 만드는 길은 이것뿐이다.
    skew        우리 추정 도착이 실제보다 얼마나 낙관적인지(초).
                `_Clock` 머리말 참고. 이것이 0 이면 note_too_early 는
                배울 것이 없다(일부러 앞당겨 쏜 것으로 읽힌다).
    """
    _Handler.posts = []
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=REAL))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    drv = _driver()
    try:
        drv.get(f"http://127.0.0.1:{port}/modal_open.html")
        for _ in range(100):
            if drv.execute_script("return document.readyState;") in (
                    "interactive", "complete"):
                break
            time.sleep(0.05)
        drv.execute_script(
            "var b=document.getElementById('rowSchChkNo0');"
            "if(b){b.checked=true;}")
        automation.install_net_recorder(drv, log=lambda *_: None)
        drv.execute_script(_JS_SITE)

        watcher = handover.Watcher(drv, log=lambda *_: None)
        st = watcher.poll()
        if not st.ready():
            log(f"RETRY[{name}] REFUSED: preflight not ready: {st.blockers()}")
            return {"ok": False}

        # 정각은 **여기서** 정한다. 크롬 기동과 픽스처 로딩에 수 초가 걸리므로
        # 미리 정해두면 첫 발이 이미 정각을 넘겨버린다(실제로 한 번 그랬다).
        # 우리가 믿는 정각은 곧(50ms 뒤)이고, 서버의 정각은 그보다 server_lag
        # 만큼 늦다. 그래서 첫 발은 서버 기준으로 확실히 이르다.
        open_epoch = time.time() + 0.05
        _Handler.server_open = open_epoch + server_lag
        clock = _Clock(open_epoch, skew=skew)

        log(f"--- case {name}: serverLag={server_lag}s skew={skew}s "
            f"(기대: {want_shots}발, 마지막 {terminal})")
        res = handover.burst(
            drv, clock, open_epoch, watcher,
            retry_seconds=8, retry_ms=60,
            log=log, diag=None, stop_event=None, preflight=st)

        shots = res.detail.get("shots") or []
        reopen = res.detail.get("reopen") or {}
        fnsave = drv.execute_script("return window.__fnSave;")
        submits = drv.execute_script("return window.__submits;")
        codes = [s.get("code") for s in shots]
        early = sum(1 for p in _Handler.posts if p["early"])

        log(f"RETRY[{name}] shots={len(shots)} codes={codes}")
        log(f"RETRY[{name}] reopenUsed={reopen.get('used')}/{reopen.get('max')} "
            f"locked={reopen.get('locked')} fnSave={fnsave} submits={submits}")
        log(f"RETRY[{name}] serverPosts={len(_Handler.posts)} early={early} "
            f"correctionMs={clock.correction * 1000:.0f} learned={clock.learned}")
        log(f"RETRY[{name}] result ok={res.ok} reason={res.reason}")
        for s in shots:
            o = s.get("outcome") or {}
            log(f"RETRY[{name}]   shot{s.get('attempt')} "
                f"arrival={s.get('arrivalOffsetMs'):+.0f}ms "
                f"code={s.get('code')} source={o.get('source')} "
                f"text={s.get('text')!r}")

        # 발사 횟수는 벽시계에 달려 있어(서버 응답 왕복 + 되살리기 주기가
        # 매 실행 조금씩 다르다) 정확한 수를 단정하지 않는다. `want_shots` 는
        # **최소** 기대치다. 단정하는 것은 불변식이다.
        ok = (
            len(codes) >= max(2, want_shots)
            and codes[0] == booking.R_TOO_EARLY
            and codes[-1] == terminal
            # 이른 발이 전부 too_early 로 읽혔다(성공으로 새지 않았다).
            and all(c == booking.R_TOO_EARLY for c in codes[:-1])
            # 되살리기가 실제로 [예약하기] 를 눌렀고, 이른 발마다 한 번씩이다.
            # = 회복이 '한 번만' 일어나지 않는다는 증거.
            and int(reopen.get("used") or 0) == len(codes) - 1
            and int(fnsave or 0) == len(codes) - 1
            and early == len(codes) - 1
            # 제출 수 = 발사 수. 되살리기가 예약을 중복으로 넣지 않았다.
            and int(submits or 0) == len(codes)
            # 판정 근거는 전부 서버 응답 본문이다.
            and all((s.get("outcome") or {}).get("source") == "submit"
                    for s in shots)
            # 이른 발마다 배웠다(매 발 보정). 한 발이면 1회, 여러 발이면 여러 회.
            and clock.correction > 0
            and len(clock.learned) == len(codes) - 1
        )
        log(f"RETRY[{name}] {'OK' if ok else 'FAILED'}")
        return {"ok": ok, "codes": codes, "reopen": reopen,
                "correctionMs": round(clock.correction * 1000, 1),
                "learned": list(clock.learned), "reason": res.reason}
    finally:
        try:
            drv.quit()
        except Exception:
            pass
        httpd.shutdown()
        httpd.server_close()


def main() -> int:
    def log(s):
        _out(str(s))

    # 두 시나리오를 돈다. 둘 다 같은 실물 캡처, 같은 실물 서버 원문이다.
    #   early-once   이른 한 발 → 되살리기 → 성공        (브리프가 요구한 그림)
    #   early-twice  이른 두 발 → 되살리기 2회 → 성공    ('한 번만' 이 아님을 증명)
    cases = [
        # serverLag 0.3s: 이른 발 최소 1회 -> 되살리기 -> 성공.
        ("early-once", 0.3, 0.2, 2, booking.R_OK),
        # serverLag 1.2s: 되살리기를 여러 번 거쳐야 서버 정각을 넘긴다.
        ("early-repeat", 1.2, 0.2, 3, booking.R_OK),
    ]
    results = {}
    for name, lead, skew, want, terminal in cases:
        got = _case(name, lead, skew, want, terminal, log)
        results[name] = got
        if not got.get("ok"):
            log(f"RETRY FAILED at case {name}")
            return 1

    log("")
    log("=== summary ===")
    for name, got in results.items():
        log(f"{name:12s} codes={got['codes']} "
            f"reopenUsed={got['reopen'].get('used')} "
            f"correctionMs={got['correctionMs']} learned={got['learned']} "
            f"reason={got['reason']}")
    log("RETRY ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
