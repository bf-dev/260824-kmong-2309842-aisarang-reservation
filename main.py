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
    """stdout 이 없어도(--noconsole) 절대 죽지 않는 출력."""
    try:
        if sys.stdout is not None:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except Exception:
        pass


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
            c = clockmod.sync(session=sess, samples=12, log=_out, diag=diag)
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
                     f"uncertaintyMs={row['uncertaintyMs']} samples={row['samples']}")
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

            reserved, clicks = None, 0
            try:
                # 여기서 누르는 것은 **사람 역할의 CI 하네스**다. 기록기 자신은
                # 아무것도 누르지 않는다(recorder.py 에 클릭 경로가 없다).
                if _wait("!!document.querySelector('input[name=occasionChk]')"):
                    drv.find_element("css selector", "input[name=occasionChk]").click()
                # 실물 id 다. v1.0.7 에서 fixture 를 고객 캡처의 진짜 마크업으로
                # 바꿨는데(#timecareTableAddBtn / #timecareConfirm) 이 하네스만
                # 예전에 우리가 지어낸 #btnAdd / #btnReserve 를 계속 눌러서
                # NoSuchElement 로 헛발질했고, 클릭 3회를 못 채워 CI 가 섰다.
                _wait("!!document.getElementById('timecareTableAddBtn')")
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
                    _out(f"HANDOVERTEST   line={handover.describe(st)}")
                    if st.queue:
                        _out(f"HANDOVERTEST   queue={st.queue_line()}")
                    if not st.ready():
                        _out(f"HANDOVERTEST   blockers={'; '.join(st.blockers())}")

                visit("modal_open.html", True)              # 사람이 만든 확인창 → 발사
                visit("modal_open.html", False)             # 체크 꺼짐 → 발사 금지
                visit("netfunnel_waiting.html", True)       # 대기열 → 발사 금지
                visit("grid_selected_row_added.html", True)  # 확인창 없음 → 발사 금지
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
                  and by[("grid_selected_row_added.html", True)][1] is False)
            fired_total = sum(1 for _n, _t2, _s, f in rows if f)
            _out(f"HANDOVERTEST fired={fired_total}/4 (기대: 1)")
            diag.add_json("handovertest.json", {
                "rows": [{"page": n, "ticked": t, "state": s.as_dict(),
                          "fired": f} for n, t, s, f in rows]})
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
