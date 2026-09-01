# -*- coding: utf-8 -*-
"""아이사랑 시간제보육 예약 - 진입점 (Kmong 고객 2309842 / 주문 7566483).

고객이 쓰는 방법은 하나뿐이다: exe 를 더블클릭하면 창이 뜬다.
아래 --console/--selftest/--guidemo 는 우리 CI/진단 전용이다.

--noconsole 로 빌드되면 sys.stdout 이 None 이라, 맨 print 나
sys.stdout.reconfigure 한 줄에 창이 그대로 죽는다. 그래서 출력은
전부 _out() 을 거친다.
"""
from __future__ import annotations

import sys

from aisarang import config
from aisarang.reporter import Diagnostics, install_excepthook


def _out(line: str = "") -> None:
    """stdout 이 없어도(--noconsole) 절대 죽지 않는 출력.

    두 번째 시도가 필요한 이유: windows-latest 러너가 이 exe 의 stdout 을
    파일로 리디렉션하면 인코딩이 cp1252 가 된다. 그러면 한글 한 줄이
    UnicodeEncodeError 를 내고, 예전에는 그 줄이 **조용히 사라졌다**
    (CI 가 그 줄을 찾다가 섰다). 이제는 못 찍는 글자만 대체하고 줄은 남긴다.
    제품 경로에서는 sys.stdout 이 None 이라 아무 일도 하지 않는다.
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


def _reopen_probe(drv, expect_code: str = "") -> dict:
    """결과 알림 화면에서 되살리기가 무엇을 누르는지 프로즌 exe 로 확인한다.

    2026-08-27 캡처(too_early_alert.html, expect_code 없음):
      - 서버 원문이 우리 판정기로 too_early 로 읽히는가
      - 되살리기 문(`_Reopen`)이 열리는가
      - 눌리는 것이 [예약하기] 하나와 알림 [확인] 하나뿐인가
        (예약 확인창의 [확인] 은 **0회** 여야 한다)

    2026-09-01 캡처(taken_alert.html, expect_code=R_TAKEN):
      - 서버 원문이 taken 으로 읽히는가
      - 되살리기 문이 **열리지 않는가** (열리면 대기열 맨 뒤로 간다)
      - 아무것도 눌리지 않는가

    사이트의 진짜 fnSave 는 픽스처에서 제거돼 있다(넷퍼널과 ajax 를 부른다).
    그 자리에 계수기를 놓아 진짜 버튼의 진짜 onclick 이 불렸는지만 센다.
    """
    from aisarang import booking, handover

    drv.execute_script(
        "window.__fnSave = 0; window.fnSave = function(){ window.__fnSave++; };"
        "window.__alertClose = 0; window.__confirmClick = 0;"
        "document.querySelectorAll(\"[id^='layer-popup-close']\").forEach("
        "  function(a){ a.addEventListener('click', function(){"
        "    window.__alertClose++; }); });"
        "document.querySelectorAll(\"[id='layer-confirm-popup-confirm2']\").forEach("
        "  function(a){ a.addEventListener('click', function(){"
        "    window.__confirmClick++; }); });")

    want = booking.TAKEN_REAL if expect_code == booking.R_TAKEN \
        else booking.TOO_EARLY_REAL
    notices = booking.read_notices(drv)
    hit = [n for n in notices if want in n]
    classified = booking.classify(hit[0]) if hit else "no_text"

    class _Now:
        def server_now(self):
            return 1001.0

    gate = handover._Reopen(_Now(), 1000.0, 2, 15.0)
    # 실제 경로와 똑같이, 방금 읽어낸 판정 결과를 그대로 문에 먹인다.
    gate.note_outcome(expect_code or booking.R_TOO_EARLY)
    st = handover.read_state(drv)
    allowed = gate.allowed(st)
    if allowed:
        gate.do(drv, lambda *_: None)
    got = drv.execute_script(
        "return {save: window.__fnSave, alert: window.__alertClose,"
        "        confirm: window.__confirmClick};") or {}
    return {"classified": classified, "allowed": bool(allowed),
            "fnSave": int(got.get("save") or 0),
            "alertClosed": int(got.get("alert") or 0),
            "confirmClicked": int(got.get("confirm") or 0),
            "text": (hit[0][:120] if hit else "")}


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    diag = Diagnostics()
    install_excepthook(diag)
    diag.log(f"{config.APP_SLUG} v{config.APP_VERSION} 시작 (argv={argv})")

    try:
        # tkinter 없이 돌아가는 모드들 먼저
        if "--selftest" in argv:
            from aisarang.runner import Runner
            r = Runner(status_cb=_out, log_cb=_out, diag=diag)
            out = r.selfcheck()
            for k, v in out.items():
                _out(f"{k}: {v}")
            ok = (isinstance(out.get("centers"), int) and out["centers"] > 0
                  and out.get("default_found")
                  # 시각 동기화가 됐다면 재측정도 실제로 돌아야 한다(2회 이상).
                  and (not out.get("clock_ok") or out.get("clock_resyncs", 0) >= 2))
            diag.upload("셀프테스트 " + ("성공" if ok else "실패"),
                        {"result": "success" if ok else "fail", "mode": "selftest"},
                        blocking=True)
            _out("SELFTEST " + ("OK" if ok else "FAILED"))
            return 0 if ok else 1

        if "--arrivaltest" in argv:
            # 도착시각 모델 검증. 서버의 초 경계 앞뒤로 쏴서, 응답 Date 헤더가
            # 기대한 초를 가리키는지 본다. 우리 진단/CI 전용이다.
            from aisarang import clock as clockmod, site
            sess = site.make_session()
            out = clockmod.measure_arrival(session=sess, log=_out, diag=diag)
            for row in out["samples"]:
                _out(str(row))
            _out(f"ARRIVAL {out['matched']}/{out['total']} matched, "
                 f"oneWayMs={out['oneWayMs']} offsetMs={out['offsetMs']}")
            diag.upload("도착시각 검증", {"mode": "arrivaltest",
                                     "matched": f"{out['matched']}/{out['total']}",
                                     "oneWayMs": out["oneWayMs"]}, blocking=True)
            return 0 if out["matched"] == out["total"] and out["total"] else 1

        if any(a.startswith("--clocktest") for a in argv):
            # 서버 시각 재측정이 정말 주기적으로 도는지 실제로 돌려서 본다.
            # 제품이 쓰는 바로 그 ClockKeeper 를 그대로 쓴다(우리 CI/진단 전용).
            #   --clocktest=<분>        얼마나 돌릴지 (기본 16분)
            #   --interval=<초>         재측정 주기 (기본 config.RESYNC_SECONDS)
            import time as _t

            from aisarang import clock as clockmod, site
            minutes, interval = 16.0, float(config.RESYNC_SECONDS)
            for a in argv:
                if a.startswith("--clocktest="):
                    minutes = float(a.split("=", 1)[1])
                if a.startswith("--interval="):
                    interval = float(a.split("=", 1)[1])
            sess = site.make_session()
            c = clockmod.sync(session=sess, log=_out, diag=diag)
            keeper = clockmod.ClockKeeper(c, interval=interval, log=_out, diag=diag)
            keeper.start()
            _out(f"CLOCKTEST 시작: {interval:.0f}초마다 재측정, {minutes:.1f}분 동안")
            end = _t.time() + minutes * 60.0
            while _t.time() < end:
                _t.sleep(1.0)
            keeper.stop()
            # 요약은 ASCII 로 찍는다. CI 가 파이프로 읽을 때 인코딩에 걸리지
            # 않아야 하고, 여기 숫자가 곧 "정말 다시 쟀다" 는 증거이기 때문이다.
            for row in c.history:
                _out(f"RESYNC n={row['n']} at={row['at']:.3f} "
                     f"offsetMs={row['offsetMs']:+.1f} deltaMs={row['deltaMs']:+.1f} "
                     f"uncertaintyMs={row['uncertaintyMs']} samples={row['samples']} "
                     f"resolution={row.get('resolution', 'date')}")
            n = c.resyncs
            diag.add_json("clocktest.json",
                          {"intervalSeconds": interval, "minutes": minutes,
                           "resyncs": n, "history": c.history})
            diag.upload(f"시각 재측정 점검: {n}회", {"mode": "clocktest",
                                              "resyncs": n,
                                              "intervalSeconds": interval},
                        blocking=True)
            _out(f"CLOCKTEST {'OK' if n >= 2 else 'FAILED'} resyncs={n}")
            return 0 if n >= 2 else 1

        if any(a.startswith("--rectest") for a in argv):
            # 진단 기록 모드를 프로즌 exe 로 실제로 돌려본다(우리 CI 전용).
            # **로컬 fixture 서버에만** 붙는다. 고객 사이트에는 어떤 경우에도
            # 이 모드로 가지 않는다(아래 가드).
            import time as _t

            from aisarang import automation
            from aisarang.recorder import DiagRecorder
            base = config.BASE_URL
            if not (base.startswith("http://127.0.0.1")
                    or base.startswith("http://localhost")):
                _out(f"RECTEST REFUSED: base is not a local fixture ({base})")
                return 2
            drv = automation.build_driver(headless=True, log=_out)
            rec = DiagRecorder(log=_out, status=_out, diag=diag)
            rec.driver = drv
            rec.start(start_url=base + "/rec")

            def _wait(js, seconds=30.0):
                end = _t.time() + seconds
                while _t.time() < end:
                    try:
                        if drv.execute_script("return " + js):
                            return True
                    except Exception:
                        pass
                    _t.sleep(0.3)
                return False

            def _where():
                """실패했을 때 브라우저가 실제로 무엇을 보고 있었는지 남긴다.

                2026-09-01 CI 에서 이 하네스가 30초씩 두 번 헛기다리고 섰는데,
                로그에 남은 것이 숫자뿐이라 원인을 좁힐 수 없었다. 브라우저가
                픽스처 화면에 있었는지 크롬 오류 화면에 있었는지만 알면
                한 번에 갈린다. ASCII 로만 찍는다(러너 stdout 은 cp1252 다).
                """
                try:
                    url = drv.current_url
                except Exception as exc:  # noqa: BLE001
                    return f"url=<{type(exc).__name__}>"
                try:
                    body = drv.execute_script(
                        "return (document.body ? document.body.innerText : '')"
                        ".slice(0, 160);") or ""
                except Exception as exc:  # noqa: BLE001
                    body = f"<{type(exc).__name__}>"
                ascii_body = body.encode("ascii", "replace").decode("ascii")
                ascii_body = " ".join(ascii_body.split())
                return f"url={url} body={ascii_body!r}"

            reserved, clicks = None, 0
            try:
                # 여기서 누르는 것은 **사람 역할의 CI 하네스**다. 기록기 자신은
                # 아무것도 누르지 않는다(recorder.py 에 클릭 경로가 없다).
                if _wait("!!document.querySelector('input[name=occasionChk]')"):
                    drv.find_element("css selector", "input[name=occasionChk]").click()
                else:
                    _out(f"RECTEST no-child-radio {_where()}")
                # 실물 id 다. v1.0.7 에서 fixture 를 고객 캡처의 진짜 마크업으로
                # 바꿨는데(#timecareTableAddBtn / #timecareConfirm) 이 하네스만
                # 예전에 우리가 지어낸 #btnAdd / #btnReserve 를 계속 눌러서
                # NoSuchElement 로 헛발질했고, 클릭 3회를 못 채워 CI 가 섰다.
                if not _wait("!!document.getElementById('timecareTableAddBtn')"):
                    _out(f"RECTEST no-add-button {_where()}")
                for sel in ("#timecareTableAddBtn", "#timecareConfirm"):
                    try:
                        drv.find_element("css selector", sel).click()
                        _t.sleep(1.5)
                    except Exception as exc:  # noqa: BLE001
                        _out(f"harness click {sel} failed: {type(exc).__name__}")
                _t.sleep(2.0)
                reserved = drv.execute_script("return window.__reserved;")
                clicks = drv.execute_script("return window.__humanClicks || 0;")
            finally:
                s = rec.stop()
                try:
                    drv.quit()
                except Exception:
                    pass
            wanted = len(s.get("wanted") or [])
            _out(f"RECTEST pages={s.get('pages')} requests={s.get('requests')} "
                 f"wanted={wanted} clicks={clicks} reserved={reserved} "
                 f"skipped={len(s.get('skipped') or [])}")
            for w in (s.get("wanted") or []):
                _out(f"RECTEST wanted-url {w.get('url')} bytes={w.get('bytes')}")
            ok = (wanted >= 2 and reserved is False and s.get("pages", 0) >= 2
                  and clicks == 3)
            _out(f"RECTEST {'OK' if ok else 'FAILED'}")
            return 0 if ok else 1

        if any(a.startswith("--handovertest") for a in argv):
            # 인계 모드를 **실물 캡처 마크업**에 대고 프로즌 exe 로 돌린다.
            # 두 가지를 증명한다.
            #   1) 사람이 만들어 둔 확인창에서는 실제로 [확인] 이 눌린다
            #   2) 확인창이 없거나(대기열 화면) 체크가 꺼져 있으면 누르지 않는다
            # 실사이트에는 가지 않는다. ci/fixtures/real/ 로컬 http 서버 전용이다.
            import functools as _ft
            import os as _os
            import threading as _th
            import time as _t
            from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

            from aisarang import automation, booking, handover

            # 픽스처 폴더는 exe 안에 없다(빌드에 포함하지 않는다). CI 가
            # --handovertest=<dir> 로 체크아웃의 경로를 넘긴다.
            real_dir = ""
            for a in argv:
                if a.startswith("--handovertest="):
                    real_dir = a.split("=", 1)[1]
            if not real_dir:
                real_dir = _os.path.join(
                    _os.path.dirname(_os.path.abspath(__file__)),
                    "ci", "fixtures", "real")
            if not _os.path.isdir(real_dir):
                _out(f"HANDOVERTEST REFUSED: no fixtures at {real_dir}")
                return 2

            # file:// 로 띄우면 안 된다. 크롬이 문서마다 오리진을 따로 줘서
            # CSS 가 제대로 안 붙고, 그러면 .popup_wrap{display:none} 이 죽어
            # 숨어 있어야 할 확인창 사본까지 '보인다' 로 판정된다.
            class _Quiet(SimpleHTTPRequestHandler):
                def log_message(self, *a):
                    pass

            httpd = ThreadingHTTPServer(
                ("127.0.0.1", 0), _ft.partial(_Quiet, directory=real_dir))
            port = httpd.server_address[1]
            _th.Thread(target=httpd.serve_forever, daemon=True).start()

            rows = []
            drv = automation.build_driver(headless=True, log=_out)
            try:
                def visit(name, tick):
                    drv.get(f"http://127.0.0.1:{port}/{name}")
                    _t.sleep(0.6)
                    if tick:
                        # 사람이 손으로 체크한 것을 재현한다. click 은 attribute 가
                        # 아니라 property 를 바꾸므로 캡처에는 남지 않는다.
                        drv.execute_script(
                            "var b=document.getElementById('rowSchChkNo0');"
                            "if(b){b.checked=true;}")
                    st = handover.read_state(drv)
                    fired = booking.fire_confirm(drv) if st.ready() else False
                    rows.append((name, tick, st, fired))
                    _out(f"HANDOVERTEST page={name} ticked={tick} "
                         f"modal={st.modal} confirm={st.confirm} armed={st.armed} "
                         f"rowTicked={st.ticked > 0} queue={st.queue} "
                         f"ready={st.ready()} fired={fired}")
                    # CI 가 판정에 쓰는 줄은 전부 ASCII 로 찍는다. 러너가
                    # stdout 을 파일로 받으면 cp1252 라서 한글 줄은 대체문자로
                    # 바뀐다(위 _out 참고). 한글 줄은 사람이 읽는 용도로만 남긴다.
                    _out(f"HANDOVERTEST   queueAhead={st.queue_ahead} "
                         f"queueBehind={st.queue_behind} "
                         f"blockers={len(st.blockers())} "
                         f"confirmId={st.confirm_id or '-'}")
                    _out(f"HANDOVERTEST   line={handover.describe(st)}")
                    if not st.ready():
                        _out(f"HANDOVERTEST   why={'; '.join(st.blockers())}")

                visit("modal_open.html", True)              # 사람이 만든 확인창 → 발사
                visit("modal_open.html", False)             # 체크 꺼짐 → 발사 금지
                visit("netfunnel_waiting.html", True)       # 대기열 → 발사 금지
                visit("grid_selected_row_added.html", True)  # 확인창 없음 → 발사 금지
                # 2026-08-27 09:00:00 의 그 화면. [확인] 한 발이 확인창을
                # 소비하고 그 자리에 '예약시간전' 알림이 떴다. 여기서도 쏘지
                # 않는다(쏠 창이 없다). 대신 서버 원문이 그대로 읽히고
                # too_early 로 분류되는지, 되살리기 문이 열리는지를 본다.
                visit("too_early_alert.html", True)
                too_early = _reopen_probe(drv)
                # 2026-09-01 09:00:00 의 그 화면. 도착 추정 정각 +686ms 에
                # 서버가 '선예약' 으로 자리를 뺏겼다고 답했다. 여기서도 쏘지
                # 않고(쏠 창이 없다), 되살리기 문은 **열리면 안 된다**.
                visit("taken_alert.html", True)
                taken = _reopen_probe(drv, expect_code=booking.R_TAKEN)
                _out(f"HANDOVERTEST   tooEarlyText={too_early['classified']} "
                     f"reopenAllowed={too_early['allowed']} "
                     f"fnSave={too_early['fnSave']} "
                     f"alertClosed={too_early['alertClosed']} "
                     f"confirmClicked={too_early['confirmClicked']}")
                _out(f"HANDOVERTEST   takenText={taken['classified']} "
                     f"reopenAllowed={taken['allowed']} "
                     f"fnSave={taken['fnSave']} "
                     f"alertClosed={taken['alertClosed']} "
                     f"confirmClicked={taken['confirmClicked']}")
            finally:
                try:
                    drv.quit()
                except Exception:
                    pass
                try:
                    httpd.shutdown()
                    httpd.server_close()
                except Exception:
                    pass

            by = {(n, t): (st, f) for n, t, st, f in rows}
            fire_st, fire_ok = by[("modal_open.html", True)]
            ok = (fire_ok is True and fire_st.ready() is True
                  and fire_st.confirm_id == "layer-confirm-popup-confirm2"
                  and by[("modal_open.html", False)][1] is False
                  and by[("netfunnel_waiting.html", True)][0].queue is True
                  and by[("netfunnel_waiting.html", True)][1] is False
                  and by[("grid_selected_row_added.html", True)][1] is False
                  and by[("too_early_alert.html", True)][1] is False
                  and too_early["classified"] == "too_early"
                  and too_early["allowed"] is True
                  and too_early["fnSave"] == 1
                  and too_early["alertClosed"] == 1
                  and too_early["confirmClicked"] == 0
                  # 선예약: 쏘지 않고, [예약하기] 를 다시 누르지도 않는다.
                  and by[("taken_alert.html", True)][1] is False
                  and taken["classified"] == "taken"
                  and taken["allowed"] is False
                  and taken["fnSave"] == 0
                  and taken["alertClosed"] == 0
                  and taken["confirmClicked"] == 0)
            fired_total = sum(1 for _n, _t2, _s, f in rows if f)
            _out(f"HANDOVERTEST fired={fired_total}/6 expected=1")
            diag.add_json("handovertest.json", {
                "rows": [{"page": n, "ticked": t, "state": s.as_dict(),
                          "fired": f} for n, t, s, f in rows],
                "tooEarly": too_early, "taken": taken})
            diag.upload("인계 모드 점검 " + ("성공" if ok else "실패"),
                        {"mode": "handovertest",
                         "result": "success" if ok else "fail",
                         "fired": fired_total}, blocking=True)
            _out(f"HANDOVERTEST {'OK' if ok else 'FAILED'}")
            return 0 if ok else 1

        if "--guiselftest" in argv:
            from aisarang.gui import run_construct_selftest
            rc = run_construct_selftest()
            _out("GUI CONSTRUCT OK")
            return rc

        if "--guidemo" in argv:
            hold = 60000
            for a in argv:
                if a.startswith("--hold="):
                    try:
                        hold = int(a.split("=", 1)[1])
                    except Exception:
                        pass
            from aisarang.gui import run_demo
            # --showrecord: 설정 영역을 끝까지 내려 '5. 진단 기록' 카드를 보여준다.
            run_demo(hold_ms=hold, diag=diag, show_record="--showrecord" in argv)
            return 0

        if "--console" in argv:
            from aisarang.runner import Runner
            settings = config.load_settings()
            r = Runner(status_cb=_out, log_cb=_out, diag=diag)
            done = {}
            r.done_cb = lambda res: done.update(res)
            r.start(settings)
            while r.is_running():
                import time
                time.sleep(1)
            _out(str(done))
            return 0 if done.get("ok") else 1

        # 기본: 고객이 보는 화면
        from aisarang.gui import run_gui
        run_gui(diag=diag)
        diag.upload("프로그램 정상 종료", {"result": "closed", "mode": "gui"},
                    blocking=True)
        return 0

    except Exception as exc:  # noqa: BLE001
        diag.upload_exception(exc, "main")
        try:
            import tkinter.messagebox as mb
            mb.showerror("오류", f"프로그램 시작 중 문제가 생겼습니다.\n\n"
                                f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
        _out(f"FATAL {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
