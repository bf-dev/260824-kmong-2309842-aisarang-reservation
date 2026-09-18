# -*- coding: utf-8 -*-
"""2026-09-18 의 **거짓 실패**를 실물 캡처 + 진짜 크롬으로 재현하고 고쳐졌음을 증명한다.

왜 이 파일이 따로 있나 (v1.0.16)
------------------------------------------------------------------
09-18 09:00:00 에 우리 [확인] 은 예약을 **성공시켰는데** 프로그램은
`too_early` 를 적고 `result=fail` 로 끝냈다. 고객은 성공한 아침을 실패로
보고받았다. 원인은 화면에 14분간 남아 있던 죽은 알림 문구다.

`tests/test_false_failure_0918.py` 는 이 동작을 단위로 못박지만, 그 시험의
DOM 은 대부분 스텁이다. 이 파일은 **진짜 크롬 + 실물 캡처 마크업**에서
같은 것을 걷는다. 09-15 의 `too_early_retry_check.py` 와 같은 급의 증거다.

두 가지를 증명한다.
  1. 옛 판정(발사 스냅샷 없음)은 숨은 문구를 읽어 `too_early` 를 돌려준다
     → 이것이 그날 고객에게 일어난 일이다
  2. 새 판정(발사 스냅샷 있음)은 그 문구를 판정에서 제외한다
     → `too_early` 가 나오지 않는다

그리고 회복이 죽지 않았음을 같이 본다: 서버가 **정말** '예약시간전' 을
답하면(응답 본문) 예전처럼 `too_early` 로 읽고 되살리기 문이 열린다.

    python ci/stale_notice_check.py            # 크롬 필요
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from aisarang import booking, handover  # noqa: E402

REAL = os.path.join(HERE, "fixtures", "real")
FIXTURE = "stale_alert_after_reopen.html"

# 그날 화면에 남아 있던 원문. 지어낸 글자가 아니다(08:46:00 응답의 returnmsg).
STALE_TEXT = "아직 예약 가능한 시간이 아닙니다."
TOO_EARLY_BODY = json.dumps(
    {"returnmsg": booking.TOO_EARLY_REAL, "returnval": ""}, ensure_ascii=False)
OK_BODY = json.dumps(
    {"returnmsg": booking.OK_REAL, "returnval": "success"}, ensure_ascii=False)


def _out(line: str = "") -> None:
    """한글이 섞여도 죽지 않는 출력(windows-latest 의 stdout 은 cp1252 다).

    판정에 쓰는 `CHECK...` 줄은 전부 ASCII 라 이 대체에 걸리지 않는다.
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


def _driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    o = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1400,1200",
              "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"):
        o.add_argument(a)
    return webdriver.Chrome(options=o)


def _ready(d) -> None:
    for _ in range(100):
        if d.execute_script("return document.readyState;") in ("interactive",
                                                               "complete"):
            return
        time.sleep(0.05)
    raise SystemExit("page never became ready")


def _install_slot(d, body: str) -> None:
    """서버 응답 본문이 도착한 상태를 만든다(제출 전용 칸)."""
    d.execute_script(
        "window.__aisarangSubmit = {seq:1,"
        " url:'/icms/occasion/InsertOcreqst.html', method:'POST',"
        " t0: Date.now(), t1: Date.now(), done:true, status:200,"
        " requestBody:'', responseBody: arguments[0],"
        " responseHeaders:'date: Fri, 18 Sep 2026 00:00:01 GMT\\r\\n'};",
        body)


def main() -> int:
    path = os.path.join(REAL, FIXTURE)
    if not os.path.isfile(path):
        _out(f"fixture missing: {path}")
        _out("run: python ci/build_stale_alert_fixture.py")
        return 2

    from real_fixture_server import RealFixtureServer

    failures = []
    with RealFixtureServer(REAL) as srv:
        d = _driver()
        try:
            d.get(srv.url(FIXTURE))
            _ready(d)

            # 이 픽스처가 정말 '사람 눈에는 안 보이는데 DOM 에는 있다' 인가.
            live = d.execute_script(
                "var p=document.getElementById('layer-alert-popup-contents2');"
                "var s=document.getElementById('layer-alert-popup2');"
                "return {text:(p?p.textContent.trim():null),"
                " h:(s?s.getBoundingClientRect().height:null)};")
            _out(f"stale text in live DOM : {live['text']}")
            _out(f"stale shell height     : {live['h']}  (0 = hidden)")
            if live["text"] != STALE_TEXT:
                failures.append("fixture does not carry the real stale text")
            if live["h"]:
                failures.append("fixture shell is visible; it must be hidden")

            # ---------------------------------------------- 1) 옛 동작 재현
            d.execute_script("window.__aisarangSubmit = null;"
                             "window.__aisarang_prefire_texts = [];"
                             "window.__aisarang_fired_at = 0;")
            old = booking.read_outcome_detail(d, timeout=0.4,
                                              submit_timeout=0.6)
            _out(f"CHECK old-verdict      : code={old.code} source={old.source or '-'}")
            if old.code != booking.R_TOO_EARLY:
                failures.append(
                    "the 09-18 bug no longer reproduces without the snapshot; "
                    "this harness has stopped testing anything")

            # ---------------------------------------------- 2) 새 동작
            d.execute_script("window.__aisarangSubmit = null;"
                             "window.__aisarang_prefire_texts = [arguments[0]];"
                             "window.__aisarang_fired_at = Date.now();",
                             STALE_TEXT)
            new = booking.read_outcome_detail(d, timeout=0.4,
                                              submit_timeout=0.6)
            _out(f"CHECK new-verdict      : code={new.code} "
                 f"confident={new.confident} stale={new.stale_skipped}")
            if new.code == booking.R_TOO_EARLY:
                failures.append(
                    "a pre-existing notice still decided the verdict")
            if new.confident:
                failures.append("a screen-only verdict claimed confidence")

            # ------------------------- 3) 진짜 '예약시간전' 은 그대로 살아 있다
            d.execute_script("window.__aisarang_prefire_texts = [arguments[0]];"
                             "window.__aisarang_fired_at = Date.now();",
                             STALE_TEXT)
            _install_slot(d, TOO_EARLY_BODY)
            real_early = booking.read_outcome_detail(d, timeout=0.4,
                                                     submit_timeout=1.0)
            _out(f"CHECK real-too-early   : code={real_early.code} "
                 f"source={real_early.source} confident={real_early.confident}")
            if real_early.code != booking.R_TOO_EARLY:
                failures.append("a genuine server too_early stopped being read")
            if not real_early.confident:
                failures.append("a server-body verdict lost its confidence")

            # 그 근거로는 되살리기 문이 열려야 한다(회복이 죽지 않았다).
            class _Clk:
                def server_now(self):
                    return 1_000_000.5

            gate = handover._Reopen(_Clk(), 1_000_000.0)
            gate.note_outcome(real_early.code, real_early)
            st = handover.LiveState(modal=False, confirm=False, armed=False,
                                    rows=1, ticked=1, on_reserve_page=True,
                                    queue=False)
            opened = gate.allowed(st)
            _out(f"CHECK reopen-gate      : allowed={opened}")
            if not opened:
                failures.append("the recovery gate no longer opens on a real "
                                "server too_early")

            # 화면 문구만인 too_early 로는 열리지 않아야 한다.
            gate2 = handover._Reopen(_Clk(), 1_000_000.0)
            gate2.note_outcome(new.code, new)
            if gate2.allowed(st):
                failures.append("the recovery gate opened on screen text only")
            _out(f"CHECK reopen-screen    : allowed={gate2.allowed(st)} "
                 f"(must be False)")

            # ------------------------------- 4) 성공 본문은 성공으로 읽힌다
            d.execute_script("window.__aisarang_prefire_texts = [arguments[0]];"
                             "window.__aisarang_fired_at = Date.now();",
                             STALE_TEXT)
            _install_slot(d, OK_BODY)
            ok = booking.read_outcome_detail(d, timeout=0.4, submit_timeout=1.0)
            _out(f"CHECK success-body     : code={ok.code} "
                 f"returnval={ok.returnval} confident={ok.confident}")
            if ok.code != booking.R_OK:
                failures.append("a real success body stopped reading as ok")
        finally:
            try:
                d.quit()
            except Exception:
                pass

    _out()
    if failures:
        for f in failures:
            _out(f"FAIL: {f}")
        _out("STALE NOTICE CHECK: FAILED")
        return 1
    _out("STALE NOTICE CHECK: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
