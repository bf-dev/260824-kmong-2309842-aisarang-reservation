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
        # 맞춰야 하는 것은 '요청이 서버에 닿는 시각'이다. 고객이 손으로 성공시킨
        # 클릭도 08:59:59.xxx 였다(= 도착이 정각 언저리). 그래서 목표 도착시각을
        # 정각보다 lead 만큼 앞에 두고, 편도지연만큼 더 일찍 쏜다.
        lead = int(settings.get("prefire_ms", 300)) / 1000.0
        want_arrival = fire_open - lead
        fire_at_local = self.clock.local_fire_for_arrival(want_arrival)
        self.log(f"목표 도착: 정각 {lead * 1000:.0f}ms 전 / "
                 f"편도 추정 {self.clock.one_way * 1000:.0f}ms 만큼 미리 발사")

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

        # 로그인 등급 확인: 예약 화면은 공동인증서 세션에서만 열린다(실측).
        # 아이디 로그인으로는 서버가 화면을 아예 안 그리므로 여기서 걸러 알려준다.
        try:
            automation.open_reservation_page(self.driver, center, self.log, self.diag)
            grade = automation.login_grade(self.driver)
            self.log(f"로그인 등급 확인: {grade}")
            if automation.page_says_cert_required(self.driver):
                self.status("아이디 로그인 상태로는 예약 화면이 열리지 않습니다. "
                            "크롬 창에서 공동인증서로 다시 로그인해 주세요.")
                automation.wait_for_cert_session(
                    self.driver, center, self.log, self.stop_event, self.diag,
                    deadline_epoch=fire_open - 30, clock=self.clock)
        except Exception as exc:  # noqa: BLE001
            self.log(f"로그인 등급 확인 실패(무시): {exc}")

        # 예열: 정각 1분 전에 예약 화면을 미리 띄워 세션/캐시를 데운다.
        # 그 전까지는 세션이 끊기지 않게 주기적으로 툭툭 건드린다(세션 수명 60분 실측).
        prewarm_at = fire_open - 60
        if self.clock.server_now() < prewarm_at:
            remain = prewarm_at - self.clock.server_now()
            self.status(f"09시 오픈까지 대기 중입니다. (약 {remain / 60:.0f}분 뒤 예열)")
            self._wait_keeping_session(prewarm_at)
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

        # 정각 대기 (도착 기준)
        self.status("09:00:00 정각을 기다립니다...")
        clockmod.sleep_until_local(fire_at_local, self.stop_event)
        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        # 실제로 쏜 순간을 기록해 '도착이 정각 대비 몇 ms 였는지'를 남긴다.
        fired_local = time.time()
        self.fire_error_ms = (fired_local - fire_at_local) * 1000.0
        self.arrival_offset_ms = (
            self.clock.arrival_for_local_fire(fired_local) - fire_open) * 1000.0
        self.log(f"발사: 예정 대비 {self.fire_error_ms:+.1f}ms, "
                 f"도착 추정 정각 대비 {self.arrival_offset_ms:+.0f}ms")

        self.status("지금 신청합니다!")
        res = automation.burst(
            self.driver, center, target_date, slots, dry_run, self.clock, fire_open,
            int(settings.get("retry_seconds", 20)),
            int(settings.get("retry_interval_ms", 400)),
            log=self.log, diag=self.diag, stop_event=self.stop_event)

        return self._finish(res.ok, res.message, center, target_date, slots, res.detail)

    # -- 대기 중 세션 유지 --------------------------------------------
    SESSION_TOUCH_SECONDS = 600      # 세션 수명 60분 실측 → 10분마다 건드린다

    def _wait_keeping_session(self, until_server_epoch: float) -> None:
        """정각 대기 중에도 로그인 세션이 살아 있게 주기적으로 요청을 보낸다."""
        while not self.stop_event.is_set():
            remain = until_server_epoch - self.clock.server_now()
            if remain <= 0:
                return
            step = min(remain, self.SESSION_TOUCH_SECONDS)
            clockmod.sleep_until(self.clock, self.clock.server_now() + step,
                                 self.stop_event)
            if self.stop_event.is_set():
                return
            if until_server_epoch - self.clock.server_now() > 5:
                if automation.touch_session(self.driver, self.log):
                    self.log("세션 유지 신호를 보냈습니다.")

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
        out["clock_ok"] = c.synced
        if c.errors:
            out["clock_error"] = c.errors[0]
        try:
            sido = site.list_sido(sess, self.diag)
            out["sido"] = len(sido)
        except Exception as exc:  # noqa: BLE001
            out["sido"] = f"실패 {type(exc).__name__}: {exc}"
            self.log(f"시도 목록 실패: {type(exc).__name__}: {exc}")
        try:
            rows = site.search_centers_both(
                sess, config.DEFAULT_CENTER["ctprvn"], config.DEFAULT_CENTER["ctprvnName"],
                config.DEFAULT_CENTER["signgu"], config.DEFAULT_CENTER["signguName"],
                diag=self.diag)
            out["centers"] = len(rows)
            out["default_found"] = any(
                r["stcode"] == config.DEFAULT_CENTER["stcode"] for r in rows)
        except Exception as exc:  # noqa: BLE001
            out["centers"] = f"실패 {type(exc).__name__}: {exc}"
            self.log(f"기관 조회 실패: {type(exc).__name__}: {exc}")
        return out
