# -*- coding: utf-8 -*-
"""실행 흐름 조립: 로그인 → 서버시각 동기화 → 09:00 대기 → 제출 → 보고."""
from __future__ import annotations

import threading
import time

from . import automation, clock as clockmod, config, site
from .masking import register_secret
from .reporter import Diagnostics


class Runner:
    """GUI 가 붙잡고 쓰는 실행기. 모든 진행은 status_cb 로 흘려보낸다."""

    def __init__(self, status_cb=lambda *_: None, log_cb=lambda *_: None,
                 done_cb=lambda *_: None, diag: Diagnostics | None = None):
        self.status_cb = status_cb
        self.log_cb = log_cb
        self.done_cb = done_cb
        self.diag = diag or Diagnostics()
        self.stop_event = threading.Event()
        self.driver = None
        self.clock = clockmod.ClockSync()
        self._thread: threading.Thread | None = None

    # -- 로그 ---------------------------------------------------------
    def log(self, line: str) -> None:
        try:
            self.diag.log(line)
        except Exception:
            pass
        try:
            self.log_cb(line)
        except Exception:
            pass

    def status(self, line: str) -> None:
        try:
            self.status_cb(line)
        except Exception:
            pass
        self.log(line)

    # -- 제어 ---------------------------------------------------------
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        self.stop_event.set()

    def start(self, settings: dict, cert_password: str = "") -> None:
        if self.is_running():
            return
        self.stop_event.clear()
        if cert_password:
            register_secret(cert_password)
        self._thread = threading.Thread(
            target=self._guarded, args=(settings, cert_password), daemon=True)
        self._thread.start()

    def _guarded(self, settings: dict, cert_password: str) -> None:
        result = {"ok": False, "message": "실행이 끝나지 않았습니다."}
        try:
            result = self._run(settings, cert_password)
        except Exception as exc:  # noqa: BLE001
            self.log(f"실행 오류: {type(exc).__name__}: {exc}")
            try:
                self.diag.upload_exception(exc, "runner")
            except Exception:
                pass
            result = {"ok": False, "message": f"오류로 중단되었습니다: {type(exc).__name__}"}
        finally:
            # 인증서 비밀번호는 메모리에서 즉시 버린다.
            cert_password = ""
            try:
                if self.driver is not None and not settings.get("keep_browser_open", True):
                    self.driver.quit()
                    self.driver = None
            except Exception:
                pass
            try:
                self.done_cb(result)
            except Exception:
                pass

    # -- 본 흐름 -------------------------------------------------------
    def _run(self, settings: dict, cert_password: str) -> dict:
        center = settings.get("center") or dict(config.DEFAULT_CENTER)
        slots = list(settings.get("time_slots") or [])
        dry_run = bool(settings.get("dry_run"))

        self.status("서버 시각을 맞추는 중입니다...")
        sess = site.make_session()
        self.clock = clockmod.sync(session=sess, samples=12,
                                   log=self.log, diag=self.diag)
        self.status(self.clock.describe())

        fire_open = clockmod.next_open_epoch(self.clock)
        target_date = (settings.get("target_date") or "").strip()
        if not target_date:
            target_date = clockmod.target_date_for(
                self.clock, int(settings.get("lead_days", config.OPEN_LEAD_DAYS)),
                open_epoch=fire_open)
        prefire = int(settings.get("prefire_ms", 300)) / 1000.0
        fire_at = fire_open - prefire

        self.status(f"대상: {center.get('name')} / 이용일 {target_date}"
                    + (f" / 시간대 {', '.join(slots)}" if slots else ""))

        self.status("크롬을 실행합니다...")
        self.driver = automation.build_driver(log=self.log)

        # 로그인
        mode = settings.get("login_mode", "manual")
        if automation.is_logged_in(self.driver):
            self.status("이미 로그인되어 있습니다.")
        elif mode == "cert" and cert_password:
            self.status("공동인증서로 로그인합니다...")
            ok = automation.start_cert_login(self.driver, cert_password,
                                             log=self.log, diag=self.diag)
            if not ok:
                self.status("자동 인증서 로그인이 끝나지 않았습니다. "
                            "크롬 창에서 로그인해 주세요.")
                if not automation.wait_for_manual_login(
                        self.driver, self.log, self.stop_event):
                    return self._finish(False, "로그인하지 못했습니다.", center,
                                        target_date, slots)
        else:
            self.status("크롬 창에서 직접 로그인해 주세요. 로그인되면 자동으로 진행합니다.")
            if not automation.wait_for_manual_login(
                    self.driver, self.log, self.stop_event):
                return self._finish(False, "로그인을 확인하지 못했습니다.", center,
                                    target_date, slots)

        cert_password = ""  # 더 이상 필요 없다

        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        # 예열: 정각 1분 전에 예약 화면을 미리 띄워 세션/캐시를 데운다.
        prewarm_at = fire_open - 60
        if self.clock.server_now() < prewarm_at:
            remain = prewarm_at - self.clock.server_now()
            self.status(f"09시 오픈까지 대기 중입니다. (약 {remain / 60:.0f}분 뒤 예열)")
            clockmod.sleep_until(self.clock, prewarm_at, self.stop_event)
        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        self.status("예열 중입니다 (예약 화면 미리 열기)...")
        try:
            automation.open_reservation_page(self.driver, center, self.log, self.diag)
            if automation.page_says_cert_required(self.driver):
                self.status("이 계정은 아직 공동인증서 로그인 상태가 아닙니다. "
                            "크롬 창에서 인증서로 로그인해 주세요.")
                automation.wait_for_manual_login(self.driver, self.log, self.stop_event, 600)
        except Exception as exc:  # noqa: BLE001
            self.log(f"예열 실패(무시): {exc}")

        # 정각 대기
        self.status("09:00:00 정각을 기다립니다...")
        clockmod.sleep_until(self.clock, fire_at, self.stop_event)
        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        self.status("지금 신청합니다!")
        res = automation.burst(
            self.driver, center, target_date, slots, dry_run, self.clock, fire_open,
            int(settings.get("retry_seconds", 20)),
            int(settings.get("retry_interval_ms", 400)),
            log=self.log, diag=self.diag, stop_event=self.stop_event)

        return self._finish(res.ok, res.message, center, target_date, slots, res.detail)

    def _finish(self, ok: bool, message: str, center: dict, target_date: str,
                slots: list, detail: dict | None = None) -> dict:
        self.status(message)
        meta = {
            "mode": "dry_run" if detail and detail.get("reason") == "dry_run" else "live",
            "center": f"{center.get('name')} ({center.get('stcode')})",
            "targetDate": target_date,
            "slots": ", ".join(slots) if slots else "(지정 없음)",
            "serverOffsetMs": round(self.clock.offset * 1000, 1),
            "result": "success" if ok else "fail",
        }
        if detail:
            meta.update({f"detail_{k}": v for k, v in detail.items()})
        try:
            self.diag.upload(
                ("예약 성공: " if ok else "예약 실패: ") + message, meta)
        except Exception:
            pass
        return {"ok": ok, "message": message, "meta": meta}

    # -- 진단 전용 실행 -------------------------------------------------
    def selfcheck(self) -> dict:
        """네트워크/서버시각/조회 API 가 살아 있는지 확인한다(브라우저 없이)."""
        out = {}
        sess = site.make_session()
        c = clockmod.sync(session=sess, samples=6, log=self.log, diag=self.diag)
        out["clock"] = c.describe()
        try:
            sido = site.list_sido(sess, self.diag)
            out["sido"] = len(sido)
        except Exception as exc:  # noqa: BLE001
            out["sido"] = f"실패 {exc}"
        try:
            rows = site.search_centers_both(
                sess, config.DEFAULT_CENTER["ctprvn"], config.DEFAULT_CENTER["ctprvnName"],
                config.DEFAULT_CENTER["signgu"], config.DEFAULT_CENTER["signguName"],
                diag=self.diag)
            out["centers"] = len(rows)
            out["default_found"] = any(
                r["stcode"] == config.DEFAULT_CENTER["stcode"] for r in rows)
        except Exception as exc:  # noqa: BLE001
            out["centers"] = f"실패 {exc}"
        return out
