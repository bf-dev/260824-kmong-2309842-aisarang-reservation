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
                  and out.get("default_found"))
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
            run_demo(hold_ms=hold, diag=diag)
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
