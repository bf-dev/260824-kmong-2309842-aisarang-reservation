# -*- coding: utf-8 -*-
"""실행 흐름 조립.

로그인 → 서버시각 동기화 → **준비(검색~예약하기)** → 확인창을 열어둔 채 대기
→ 09:00:00 에 [확인] 한 발 → 결과 보고.
"""
from __future__ import annotations

import re
import threading
import time

from . import automation, booking, clock as clockmod, config, site
from .masking import register_secret
from .reporter import Diagnostics


def _hours_from_slots(slots) -> list:
    """화면의 시간대 칩("09:00")을 표의 열(9)로 바꾼다. 순서 = 우선순위."""
    out = []
    for s in slots or []:
        m = re.search(r"(\d{1,2})", str(s))
        if not m:
            continue
        h = int(m.group(1))
        if h not in out:
            out.append(h)
    return out


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
        self.keeper: clockmod.ClockKeeper | None = None
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
                if self.keeper is not None:
                    self.keeper.stop()
                    self.keeper = None
            except Exception:
                pass
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
    #
    # 순서가 v1.0.4 에서 바뀌었다. 고객이 자기 인증서 세션을 화면녹화해서
    # 보내준 덕분에 4·5단계를 실제로 보게 됐고, 고객이 손으로 성공시키는
    # 방법도 같이 알게 됐다:
    #
    #   이용일은 자정에 목록에 뜨지만 **예약이 되는 것은 09:00 정각**이다.
    #   그래서 9시 전에 검색~[예약하기] 까지 다 해두고 "예약" 모달을 열어둔 채
    #   기다리다가, 정각에 [확인] 한 번만 누른다. 실패는 언제나 그 한 클릭이
    #   조금 늦거나(→ 정원초과) 조금 이른(→ 예약시간전) 것이었다.
    #
    # 그래서 여기서도 준비(1~8단계)는 여유 있게 끝내고, 모달을 붙잡은 채
    # 대기하다가, **[확인] 요청만** 서버 09:00:00 에 도착하도록 쏜다.

    def _run(self, settings: dict, cert_password: str) -> dict:
        center = settings.get("center") or dict(config.DEFAULT_CENTER)
        slots = list(settings.get("time_slots") or [])
        hours = int(settings.get("use_hours", 9) or 9)
        dry_run = bool(settings.get("dry_run"))
        preferred = _hours_from_slots(slots)

        self.status("서버 시각을 맞추는 중입니다...")
        sess = site.make_session()
        self.clock = clockmod.sync(session=sess, samples=12,
                                   log=self.log, diag=self.diag)
        self.status(self.clock.describe())

        open_epoch = clockmod.next_open_epoch(self.clock)

        # 여기서부터 끝까지, 5분마다 같은 방식으로 다시 잰다. 한 번 재고 마는 게
        # 아니다(고객은 전날 오후에 켜두기도 한다). 정각 90초 전에는 스스로 멈춘다.
        self.keeper = clockmod.ClockKeeper(
            self.clock, interval=config.RESYNC_SECONDS, log=self.log,
            diag=self.diag, stop_event=self.stop_event,
            quiet_server_epoch=open_epoch)
        self.keeper.start()
        self.log(f"서버 시각은 {config.RESYNC_SECONDS // 60}분마다 다시 맞춥니다 "
                 f"(정각 {config.RESYNC_QUIET_SECONDS}초 전부터는 멈춥니다).")
        target_date = (settings.get("target_date") or "").strip()
        if not target_date:
            target_date = clockmod.target_date_for(
                self.clock, int(settings.get("lead_days", config.OPEN_LEAD_DAYS)),
                open_epoch=open_epoch)

        lead = int(settings.get("arrival_lead_ms", 300)) / 1000.0
        setup_seconds = max(int(settings.get("setup_seconds", 240)), 60)

        self.status(f"대상: {center.get('name')} / 이용일 {target_date} / {hours}시간"
                    + (f" / 시작 우선순위 {', '.join(slots)}" if slots else ""))
        self.log(f"[확인] 목표 도착: 정각 {lead * 1000:.0f}ms 전 / "
                 f"편도 추정 {self.clock.one_way * 1000:.0f}ms 만큼 미리 발사 / "
                 f"준비 시작은 정각 {setup_seconds}초 전")

        self.status("크롬을 실행합니다...")
        self.driver = automation.build_driver(log=self.log)

        if not self._login(settings, cert_password):
            return self._finish(False, "로그인하지 못했습니다.", center, target_date, slots)
        cert_password = ""

        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        # 예약 화면은 공동인증서 세션에서만 열린다(실측). 아이디 로그인이면
        # 서버가 화면을 아예 안 그리므로 여기서 걸러 알려주고 기다린다.
        try:
            automation.open_reservation_page(self.driver, center, self.log, self.diag)
            self.log(f"로그인 등급 확인: {automation.login_grade(self.driver)}")
            if automation.page_says_cert_required(self.driver):
                self.status("아이디 로그인 상태로는 예약 화면이 열리지 않습니다. "
                            "크롬 창에서 공동인증서로 다시 로그인해 주세요.")
                automation.wait_for_cert_session(
                    self.driver, center, self.log, self.stop_event, self.diag,
                    deadline_epoch=open_epoch - setup_seconds, clock=self.clock)
        except Exception as exc:  # noqa: BLE001
            self.log(f"로그인 등급 확인 실패(무시): {exc}")

        # 준비 시작 시각까지는 세션만 살려둔다(세션 수명 60분 실측).
        setup_at = open_epoch - setup_seconds
        if self.clock.server_now() < setup_at:
            remain = setup_at - self.clock.server_now()
            self.status(f"09시 오픈까지 대기 중입니다. "
                        f"(약 {remain / 60:.0f}분 뒤 예약 준비를 시작합니다)")
            self._wait_keeping_session(setup_at)
        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        # 준비를 시작하는 이 자리에서 한 번 새로 잰다. 정각에 쏘는 한 발은
        # 어젯밤에 잰 값이 아니라 방금 잰 값으로 조준해야 한다.
        if self.keeper is not None:
            self.keeper.sync_now("준비 시작 직전")
        self.log(f"조준 기준: {self.clock.describe()}")

        # --- 1~8단계: 준비. 실패하면 남은 시간 안에서 다시 시도한다. ---
        prep = self._prepare_with_retries(center, target_date, preferred, hours,
                                          settings, open_epoch)
        if prep is None or not prep.ok:
            msg = prep.message if prep else "예약 준비를 하지 못했습니다."
            detail = dict(prep.detail) if prep else {}
            if prep is not None and prep.prepared is not None:
                detail.update(prep.prepared.as_meta())
                detail["reason"] = prep.reason
            return self._finish(False, msg, center, target_date, slots, detail)

        p = prep.prepared
        self.status(f"준비 완료. 확인창을 열어둔 채 09:00:00 을 기다립니다. "
                    f"({target_date} {p.start_hour:02d}시부터 {p.hours}시간, "
                    f"남은 자리 {p.cell_capacity})")

        if dry_run:
            booking.dismiss_modal(self.driver, self.log)
            meta = p.as_meta()
            meta["reason"] = "dry_run"
            return self._finish(
                True, "[연습 모드] 예약 확인창까지 열었고 [확인] 은 누르지 않았습니다. "
                      "실제 예약은 만들어지지 않았습니다.",
                center, target_date, slots, meta)

        # --- 대기: 모달을 붙잡고 있는다. 닫히거나 체크가 풀리면 다시 세운다. ---
        # 발사 시각은 홀드 중에도 다시 계산한다. 그 사이에 시각을 다시 쟀으면
        # 새 값으로 조준해야 하기 때문이다.
        self._hold_modal(p, open_epoch - lead, center, target_date, preferred,
                         hours, settings, open_epoch)
        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        # --- 9단계: [확인] 만 정각에 쏜다. ---
        fire_local = self.clock.local_fire_for_arrival(open_epoch - lead)
        clockmod.sleep_until_local(fire_local, self.stop_event)
        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        self.status("지금 [확인] 을 누릅니다!")
        res = booking.confirm_burst(
            self.driver, p, self.clock, open_epoch,
            retry_seconds=int(settings.get("retry_seconds", 20)),
            retry_ms=int(settings.get("confirm_retry_ms", 90)),
            log=self.log, diag=self.diag, stop_event=self.stop_event)
        automation.capture(self.driver, self.diag, "after_confirm")

        # 정원초과라면 다음 우선 시간대로 한 번 더 간다(고객이 지정했을 때만).
        if (not res.ok) and res.reason == "full" and len(preferred) > 1:
            rest = [h for h in preferred if h != p.start_hour]
            self.status(f"{p.start_hour:02d}시는 정원초과입니다. 다음 우선순위 "
                        f"{rest[0]:02d}시로 한 번 더 시도합니다.")
            second = self._prepare_with_retries(center, target_date, rest, hours,
                                                settings, open_epoch,
                                                until=open_epoch + int(
                                                    settings.get("retry_seconds", 20)) + 60)
            if second is not None and second.ok:
                res2 = booking.confirm_burst(
                    self.driver, second.prepared, self.clock, open_epoch,
                    retry_seconds=8,
                    retry_ms=int(settings.get("confirm_retry_ms", 90)),
                    log=self.log, diag=self.diag, stop_event=self.stop_event)
                automation.capture(self.driver, self.diag, "after_confirm_2")
                if res2.ok:
                    res = res2
                    p = second.prepared

        detail = dict(res.detail)
        detail.update(p.as_meta())
        detail["reason"] = res.reason
        detail["clockCorrectionMs"] = round(self.clock.correction * 1000, 1)
        return self._finish(res.ok, res.message, center, target_date, slots, detail)

    # -- 로그인 --------------------------------------------------------
    def _login(self, settings: dict, cert_password: str) -> bool:
        mode = settings.get("login_mode", "manual")
        if automation.is_logged_in(self.driver):
            self.status("이미 로그인되어 있습니다.")
            return True
        if mode == "cert" and cert_password:
            self.status("공동인증서로 로그인합니다...")
            if automation.start_cert_login(self.driver, cert_password,
                                           log=self.log, diag=self.diag):
                return True
            self.status("자동 인증서 로그인이 끝나지 않았습니다. 크롬 창에서 로그인해 주세요.")
        else:
            self.status("크롬 창에서 직접 로그인해 주세요. 로그인되면 자동으로 진행합니다.")
        return automation.wait_for_manual_login(self.driver, self.log, self.stop_event)

    # -- 준비 재시도 ----------------------------------------------------
    def _prepare_with_retries(self, center, target_date, preferred, hours,
                              settings, open_epoch, until=None):
        """준비(1~8단계). 정각 직전까지 여유를 두고 몇 번이든 다시 해본다.

        여기서 실패하면 예약은 만들어지지 않는다. 그래서 마음껏 재시도해도
        안전하다. 다만 정각을 넘겨 계속 붙잡고 있지는 않는다.
        """
        # 준비를 마쳐야 하는 시각. 최소 15초는 남기고 끝낸다.
        stop_at = until if until is not None else (open_epoch - 15)
        attempt = 0
        last = None
        while not self.stop_event.is_set():
            attempt += 1
            self.status(f"예약 준비 {attempt}회차 (검색 → 센터 → 아동 → 반/이용시간 "
                        f"→ 날짜 칸 → 추가 → 체크)")
            last = booking.prepare(self.driver, center, target_date, preferred,
                                   hours, settings.get("class_name", ""),
                                   settings.get("child_name", ""),
                                   log=self.log, diag=self.diag)
            if last.ok:
                opened = booking.open_modal(self.driver, last.prepared,
                                            self.log, self.diag)
                if opened.ok:
                    return opened
                last = opened
            self.log(f"준비 실패({last.reason}): {last.message}")
            # 다시 해도 결과가 바뀌지 않는 것들은 즉시 멈춘다.
            # child_mismatch: 고객이 적은 아동명이 목록에 없다. 다시 돌려봐야
            # 같은 결과이고, 그렇다고 다른 아동으로 예약하면 절대 안 된다.
            if last.reason in ("cert_required", "child_mismatch"):
                return last
            remain = stop_at - self.clock.server_now()
            if remain <= 5:
                return last
            wait = min(max(remain - 5, 1.0), 20.0)
            self.log(f"{wait:.0f}초 뒤 다시 준비합니다. (정각까지 "
                     f"{open_epoch - self.clock.server_now():.0f}초)")
            if self.stop_event.wait(wait):
                break
        return last

    # -- 모달을 붙잡고 대기 --------------------------------------------
    HOLD_CHECK_SECONDS = 5.0

    def _hold_modal(self, p, arrival_epoch, center, target_date, preferred, hours,
                    settings, open_epoch) -> None:
        """확인창을 열어둔 채 발사 시각까지 기다린다.

        홀드 중에 창이 닫히거나(고객이 실수로 눌렀거나 사이트가 닫았거나)
        세션이 끊기면 조용히 실패하는 게 최악이다. 주기적으로 확인하고,
        시간이 남아 있으면 확인 경로를 다시 세운다.

        arrival_epoch 는 [확인] 요청이 서버에 도착해야 하는 시각(서버 기준)이다.
        로컬 발사 시각은 매번 다시 계산한다. 홀드 중에 시각을 다시 쟀다면
        그만큼 발사 시각도 따라 움직여야 한다.
        """
        while not self.stop_event.is_set():
            fire_local = self.clock.local_fire_for_arrival(arrival_epoch)
            remain = fire_local - time.time()
            if remain <= 0.5:
                return
            self.stop_event.wait(min(remain - 0.4, self.HOLD_CHECK_SECONDS))
            if self.stop_event.is_set():
                return
            if self.clock.local_fire_for_arrival(arrival_epoch) - time.time() <= 0.5:
                return
            try:
                if booking.modal_still_held(self.driver, p):
                    continue
            except Exception as exc:  # noqa: BLE001
                self.log(f"확인창 상태 확인 실패(무시): {type(exc).__name__}")
                continue
            self.log("확인창이 닫혔거나 체크가 풀렸습니다. 다시 세웁니다.")
            self.status("확인창을 다시 세우는 중입니다...")
            if booking.redrive_confirm(self.driver, p, self.log):
                self.log("확인창을 다시 열어두었습니다.")
                continue
            # 확인 경로만으로 못 살리면 준비부터 다시 한다(시간이 남아 있을 때만).
            if fire_local - time.time() < 20:
                self.log("남은 시간이 부족해 준비를 다시 하지 않습니다.")
                return
            again = self._prepare_with_retries(center, target_date, preferred,
                                               hours, settings, open_epoch)
            if again is not None and again.ok and again.prepared is not None:
                p.__dict__.update(again.prepared.__dict__)
                self.log("준비를 다시 마쳤습니다.")
            else:
                self.log("준비를 다시 하지 못했습니다. 남은 시간 동안 계속 시도합니다.")

    # -- 대기 중 세션 유지 --------------------------------------------
    # 세션 수명 60분 실측. 5분 주기는 넉넉하고, 서버 시각 재측정과 같은 주기라
    # 고객 로그에 두 줄이 나란히 찍힌다.
    SESSION_TOUCH_SECONDS = config.SESSION_TOUCH_SECONDS

    def _wait_keeping_session(self, until_server_epoch: float) -> None:
        """정각 대기 중에도 로그인 세션이 살아 있게 주기적으로 요청을 보낸다.

        그 응답의 Date 헤더로 시계 점검도 같이 한다. 어차피 나가는 요청이라
        공짜다. 다만 이 한 발로 오프셋을 움직이지는 않는다(노이즈가 크다).
        어긋난 것이 보이면 제대로 된 12발 재측정을 앞당겨 부른다.
        """
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
                touched = automation.touch_session(self.driver, self.log)
                if touched.get("ok"):
                    self.log("세션 유지 신호를 보냈습니다.")
                self._drift_check(touched)
                # 네트워크 로그 버퍼를 비운다(몇 시간 대기하면 계속 쌓인다).
                try:
                    automation.drain_network(self.driver)
                except Exception:
                    pass

    def _drift_check(self, touched: dict) -> None:
        """세션 유지 응답의 Date 헤더로 '어긋났는지' 만 본다."""
        try:
            stamp = touched.get("dateEpoch")
            t0, t1 = touched.get("t0"), touched.get("t1")
            if not stamp or t0 is None or t1 is None:
                return
            note = self.clock.note_drift_sample(stamp, t0, t1)
            if not note.get("usable"):
                return
            if note["consistent"]:
                self.log(f"세션 유지 응답으로 시각 점검: 어긋남 없음 "
                         f"(왕복 {note['rttMs']:.0f}ms, 현재 보정 "
                         f"{note['offsetMs']:+.0f}ms)")
                return
            self.log(f"세션 유지 응답으로 시각 점검: 어긋남 {note['deviationMs']:+.0f}ms "
                     f"→ 곧바로 서버 시각을 다시 잽니다.")
            if self.keeper is not None:
                self.keeper.request_now("시계 어긋남 감지")
        except Exception as exc:  # noqa: BLE001
            self.log(f"시각 점검 실패(무시): {type(exc).__name__}")

    def _finish(self, ok: bool, message: str, center: dict, target_date: str,
                slots: list, detail: dict | None = None) -> dict:
        self.status(message)
        meta = {
            "mode": "dry_run" if detail and detail.get("reason") == "dry_run" else "live",
            "center": f"{center.get('name')} ({center.get('stcode')})",
            "targetDate": target_date,
            "slots": ", ".join(slots) if slots else "(지정 없음)",
            "serverOffsetMs": round(self.clock.offset * 1000, 1),
            "oneWayMs": round(self.clock.one_way * 1000, 1),
            "clockCorrectionMs": round(self.clock.correction * 1000, 1),
            "clockResyncs": self.clock.resyncs,
            "clockResyncIntervalSec": config.RESYNC_SECONDS,
            "clockAgeSec": (round(self.clock.age_seconds(), 1)
                            if self.clock.last_sync_local else None),
            "result": "success" if ok else "fail",
        }
        if detail:
            meta.update({f"detail_{k}": v for k, v in detail.items()})
        # 서버가 [확인] 에 뭐라고 답했는지는 매번 원문 그대로 남긴다.
        # 다음 실행의 도착 보정을 여기서 읽기 때문이다.
        shots = (detail or {}).get("shots") or []
        if shots:
            self.log("[확인] 응답 기록:")
            for s in shots:
                self.log(f"  {s.get('attempt')}발 · 도착 {s.get('arrivalOffsetMs'):+.0f}ms "
                         f"· [{s.get('code')}] {s.get('text', '')}")
            try:
                self.diag.add_json("confirm_shots.json", {
                    "openTargetLeadMs": None,
                    "clockCorrectionMs": round(self.clock.correction * 1000, 1),
                    "correctionNotes": self.clock.correction_notes,
                    "shots": shots,
                })
            except Exception:
                pass
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
        self.clock = c
        out["clock"] = c.describe()
        out["clock_ok"] = c.synced
        if c.errors:
            out["clock_error"] = c.errors[0]

        # 재측정이 말뿐이 아니라는 것을 여기서 실제로 보인다. 제품이 09시까지
        # 5분마다 부르는 바로 그 경로를 두 번 부른다.
        keeper = clockmod.ClockKeeper(c, interval=config.RESYNC_SECONDS,
                                      samples=6, log=self.log, diag=self.diag,
                                      session_factory=lambda: sess)
        self.keeper = keeper
        self.log(f"서버 시각 재측정 주기: {config.RESYNC_SECONDS // 60}분 "
                 f"(정각 {config.RESYNC_QUIET_SECONDS}초 전부터는 멈춥니다)")
        for i in (1, 2):
            keeper.sync_now(f"점검용 재측정 {i}/2", force=True)
        out["clock_resyncs"] = c.resyncs
        out["clock_after_resync"] = c.describe()
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
