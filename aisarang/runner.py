# -*- coding: utf-8 -*-
"""실행 흐름 조립.

로그인 → 서버시각 동기화 → **준비(검색~예약하기)** → 확인창을 열어둔 채 대기
→ 09:00:00 에 [확인] 한 발 → 결과 보고.
"""
from __future__ import annotations

import re
import threading
import time

from . import automation, booking, clock as clockmod, config, handover, site
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
                 done_cb=lambda *_: None, diag: Diagnostics | None = None,
                 state_cb=lambda *_: None):
        self.status_cb = status_cb
        self.log_cb = log_cb
        self.done_cb = done_cb
        # 인계 모드에서 화면 위쪽 상태판을 갱신하는 통로.
        # {"mode","line","ready","queue","secondsToFire", ...} 를 흘려보낸다.
        self.state_cb = state_cb
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

    def state(self, payload: dict) -> None:
        """상태판 갱신. 실패해도 실행을 막지 않는다."""
        try:
            self.state_cb(dict(payload))
        except Exception:
            pass

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
        mode = config.normalize_run_mode(settings.get("run_mode"))
        self.run_mode = mode

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
        self.log(f"실행 방식: {config.RUN_MODE_LABELS[mode]}")
        self.log(f"[확인] 목표 도착: 정각 {lead * 1000:.0f}ms 전 / "
                 f"편도 추정 {self.clock.one_way * 1000:.0f}ms 만큼 미리 발사"
                 + ("" if mode == config.MODE_HANDOVER
                    else f" / 준비 시작은 정각 {setup_seconds}초 전"))

        self.status("크롬을 실행합니다...")
        self.driver = automation.build_driver(log=self.log)

        if not self._login(settings, cert_password):
            return self._finish(False, "로그인하지 못했습니다.", center, target_date, slots)
        cert_password = ""

        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        if mode == config.MODE_HANDOVER:
            return self._run_handover(settings, center, target_date, slots,
                                      open_epoch, lead, dry_run)

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

    # -- 인계 모드 -----------------------------------------------------
    #
    # 고객 요청 원문 (2026-08-26, 그날 예약을 놓친 뒤):
    #   "제가 아동선택부터 시간선택까지 모두 끝내놓으면 프로그램은 확인만
    #    누르는 방식을 변경 요청드립니다."
    #
    # 그래서 이 경로에는 준비(검색/센터/아동/반/시간/칸/추가/체크/예약하기)가
    # **없다**. 화면 이동도 아래 _handover_open_once() 한 번뿐이고, 그것도
    # 고객이 이미 만들어 둔 화면 위에서는 하지 않는다.

    # 발사 몇 초 전에 마지막 점검을 할지. 이 시간 안에 화면을 다시 읽고
    # 조준까지 끝낸 뒤, 남은 시간을 정확히 재워서 쏜다.
    PREFLIGHT_SECONDS = 1.5
    # 준비가 안 됐다고 크게 알리기 시작하는 시점(정각 대비).
    NAG_SECONDS = 90.0

    def _run_handover(self, settings: dict, center: dict, target_date: str,
                      slots: list, open_epoch: float, lead: float,
                      dry_run: bool) -> dict:
        self.status("인계 모드입니다. 크롬 창에서 아동 선택부터 [예약하기] 까지 "
                    "직접 진행해 주세요. 프로그램은 확인창의 [확인] 만 누릅니다.")
        self.log("이 모드에서 프로그램이 누르는 것은 예약 확인창의 [확인] 하나뿐입니다. "
                 "화면 이동, 검색, 아동/반/시간 선택, [추가], 체크, [예약하기] 는 "
                 "하지 않습니다.")

        self._handover_open_once(center)

        watcher = handover.Watcher(
            self.driver, log=self.log,
            on_state=lambda st: self._handover_state(st, open_epoch, lead))

        # --- 정각까지: 계속 읽고, 계속 알려준다. 누르지 않는다.
        nagged = False
        while not self.stop_event.is_set():
            fire_local = self.clock.local_fire_for_arrival(open_epoch - lead)
            preflight_at = fire_local - self.PREFLIGHT_SECONDS
            if time.time() >= preflight_at:
                break
            watcher.wait_until(min(preflight_at, time.time() + 5.0),
                               self.stop_event)
            remain = open_epoch - self.clock.server_now()
            if (not nagged) and remain <= self.NAG_SECONDS \
                    and not watcher.state.ready() and not watcher.state.queue:
                nagged = True
                self.status(f"정각 {remain:.0f}초 전인데 예약 확인창이 아직 없습니다. "
                            f"크롬 창에서 [예약하기] 까지 진행해 주세요.")
                self.log("확인창이 없으면 [확인] 을 누르지 않습니다. 잘못 누르는 것보다 "
                         "안 누르는 쪽이 안전합니다(취소는 센터 전화로만 됩니다).")
            self._handover_touch_session(open_epoch)

        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date,
                                slots, {"reason": "stopped",
                                        "handoverState": watcher.state.as_dict()})

        # --- 마지막 점검. 발사 직전에 살아 있는 화면에서 다시 읽는다.
        st = watcher.poll()
        automation.capture(self.driver, self.diag, "handover_preflight")
        self.log("발사 직전 점검: " + handover.describe(st))
        if not st.ready():
            msg = ("예약 확인창이 준비되지 않아 [확인] 을 누르지 않았습니다: "
                   + "; ".join(st.blockers()))
            self.status(msg)
            self.log("이 상태에서 누르면 엉뚱한 예약이 될 수 있습니다. "
                     "그래서 누르지 않았습니다.")
            # 정각을 지나서라도 확인창이 열리면 쏜다(대기열에 잡혔을 수 있다).
            res = handover.burst(
                self.driver, self.clock, open_epoch, watcher,
                retry_seconds=int(settings.get("retry_seconds", 20)),
                retry_ms=int(settings.get("confirm_retry_ms", 90)),
                log=self.log, diag=self.diag, stop_event=self.stop_event)
            automation.capture(self.driver, self.diag, "handover_after")
            detail = dict(res.detail)
            detail["reason"] = res.reason
            detail["preflight"] = st.as_dict()
            if not res.ok and res.reason == "never_ready":
                return self._finish(False, msg, center, target_date, slots, detail)
            return self._finish(res.ok, res.message, center, target_date, slots,
                                detail)

        if dry_run:
            meta = {"reason": "dry_run", "handoverState": st.as_dict()}
            return self._finish(
                True, "[연습 모드] 확인창을 확인했고 [확인] 은 누르지 않았습니다. "
                      "실제 예약은 만들어지지 않았습니다.",
                center, target_date, slots, meta)

        fire_local = self.clock.local_fire_for_arrival(open_epoch - lead)
        clockmod.sleep_until_local(fire_local, self.stop_event)
        if self.stop_event.is_set():
            return self._finish(False, "사용자가 중지했습니다.", center, target_date, slots)

        self.status("지금 [확인] 을 누릅니다!")
        res = handover.burst(
            self.driver, self.clock, open_epoch, watcher,
            retry_seconds=int(settings.get("retry_seconds", 20)),
            retry_ms=int(settings.get("confirm_retry_ms", 90)),
            log=self.log, diag=self.diag, stop_event=self.stop_event,
            preflight=st)
        automation.capture(self.driver, self.diag, "handover_after")

        detail = dict(res.detail)
        detail["reason"] = res.reason
        detail["preflight"] = st.as_dict()
        detail["clockCorrectionMs"] = round(self.clock.correction * 1000, 1)
        return self._finish(res.ok, res.message, center, target_date, slots, detail)

    def _handover_open_once(self, center: dict) -> None:
        """예약 화면까지만 한 번 열어준다. 그 뒤로는 화면을 건드리지 않는다.

        고객이 이미 손으로 만들어 둔 화면 위에서는 **열지 않는다.** 오늘
        고객이 잃은 것이 바로 그것이라, 여기서 같은 실수를 반복하면 안 된다.
        """
        try:
            st = handover.read_state(self.driver)
        except Exception:  # noqa: BLE001
            st = handover.LiveState(error="read_failed")
        if st.modal or st.ticked > 0 or st.on_reserve_page:
            self.log("이미 예약 화면이 열려 있어 그대로 둡니다. "
                     "프로그램은 화면을 이동시키지 않습니다.")
            return
        try:
            automation.open_reservation_page(self.driver, center, self.log, self.diag)
            self.log(f"로그인 등급 확인: {automation.login_grade(self.driver)}")
            if automation.page_says_cert_required(self.driver):
                self.status("이 화면은 공동인증서 세션에서만 열립니다. "
                            "크롬 창에서 공동인증서로 다시 로그인해 주세요.")
        except Exception as exc:  # noqa: BLE001
            self.log(f"예약 화면을 열지 못했습니다(무시): {type(exc).__name__}: {exc}")
        self.log("여기까지가 프로그램이 여는 마지막 화면입니다. "
                 "이제부터는 크롬 창에서 직접 진행해 주세요.")

    def _handover_state(self, st, open_epoch: float, lead: float) -> None:
        """상태판 한 줄. 고객이 이 화면을 사진으로 찍어 보낸다."""
        try:
            fire_local = self.clock.local_fire_for_arrival(open_epoch - lead)
            secs = max(0.0, fire_local - time.time())
        except Exception:
            secs = 0.0
        self.state({
            "mode": config.MODE_HANDOVER,
            "modeLabel": config.RUN_MODE_LABELS[config.MODE_HANDOVER],
            "line": handover.describe(st),
            "ready": st.ready(),
            "modal": st.modal,
            "ticked": st.ticked > 0,
            "queue": st.queue,
            "queueLine": st.queue_line() if st.queue else "",
            "secondsToFire": secs,
        })

    # 인계 모드에서도 세션은 살려야 한다(세션 수명 60분 실측). 다만 대기 루프가
    # 화면 폴링이라, 세션 유지는 시각을 재서 따로 부른다.
    def _handover_touch_session(self, open_epoch: float) -> None:
        last = getattr(self, "_last_touch", 0.0)
        now = time.time()
        if now - last < self.SESSION_TOUCH_SECONDS:
            return
        self._last_touch = now
        if open_epoch - self.clock.server_now() <= config.RESYNC_QUIET_SECONDS:
            return          # 정각 직전에는 어떤 것도 끼어들지 않는다
        touched = automation.touch_session(self.driver, self.log)
        if touched.get("ok"):
            self.log("세션 유지 신호를 보냈습니다.")
        self._drift_check(touched)
        try:
            automation.drain_network(self.driver)
        except Exception:
            pass

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
    #
    # 2026-08-26 에 고객이 예약을 놓친 원인이 바로 이 함수였다.
    # [예약하기] 를 누른 뒤 확인창이 안 열리면(= 가상대기열에 섰다는 뜻)
    # **검색 화면부터 준비를 통째로 다시** 했다. 그래서 매번 대기열 맨 뒤로
    # 갔고, 앞에 선 사람이 72명 → 138명 → 177명 으로 불어났다.
    # 대기열 레이어가 스스로 이렇게 적어 놓았는데도 그랬다:
    #     ※ 재접속하시면 대기시간이 더 길어집니다.
    #
    # 그래서 규칙을 하나 세운다. **[예약하기] 를 한 번이라도 누른 뒤에는
    # 준비를 다시 하지 않는다.** 기다리거나, 보고하고 멈춘다.
    PRESSED_RESERVE = ("no_modal", "no_modal_queue", "not_armed")

    def _prepare_with_retries(self, center, target_date, preferred, hours,
                              settings, open_epoch, until=None):
        """준비(1~8단계). [예약하기] 를 누르기 전까지만 몇 번이든 다시 해본다.

        [예약하기] 전 단계에서의 실패는 예약을 만들지 않으므로 재시도해도
        안전하다. 그 뒤의 실패는 다르다(위 주석 참고).
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
                # 대기열에 서게 되면 정각 직전까지 기다린다. 확인창은 순번이
                # 와야 열리고, 우리 설계는 그 표를 미리 쥐어두는 것이 목적이다.
                deadline_local = self.clock.local_time_for(open_epoch - 5)
                opened = booking.open_modal(self.driver, last.prepared,
                                            self.log, self.diag,
                                            deadline_local=deadline_local)
                if opened.ok:
                    return opened
                last = opened
            self.log(f"준비 실패({last.reason}): {last.message}")

            if last.reason in self.PRESSED_RESERVE:
                # 여기서 준비를 다시 하면 오늘 아침 일이 그대로 반복된다.
                self.status("[예약하기] 를 이미 눌렀으므로 준비를 다시 하지 않습니다. "
                            "지금 상태 그대로 두고 확인창이 열리는지 지켜봅니다.")
                self.log("처음부터 다시 하면 가상대기열 맨 뒤로 갑니다"
                         "(2026-08-26 실측: 앞에 72명 → 138명 → 177명). "
                         "그래서 다시 하지 않습니다.")
                self._watch_for_late_modal(last, open_epoch)
                return last
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

    def _watch_for_late_modal(self, last, open_epoch: float) -> None:
        """[예약하기] 를 누른 뒤 늦게라도 확인창이 열리는지 지켜본다.

        누르지 않는다. 읽기만 한다. 열리면 그 자리에서 조준까지 해서
        `last` 를 성공으로 바꾼다.
        """
        deadline = open_epoch - 2
        told = False
        while not self.stop_event.is_set() and self.clock.server_now() < deadline:
            info = booking.modal_info(self.driver)
            if info.get("text"):
                p = last.prepared
                p.modal_open, p.modal_text = True, str(info["text"])
                p.armed = booking.arm_confirm(self.driver, self.log)
                if p.armed:
                    self.status("확인창이 열렸습니다. 정각에 [확인] 을 누릅니다.")
                    last.ok = True
                    last.reason = "modal_armed"
                    last.message = "예약 확인창을 열어두고 대기합니다."
                    return
            q = booking.queue_info(self.driver)
            if q.get("queue"):
                self.status(booking.queue_line(q) + " · 확인창을 기다립니다")
            elif not told:
                told = True
                self.status("확인창이 열리지 않았고 대기열도 보이지 않습니다. "
                            "크롬 창에서 [예약하기] 를 한 번 눌러주세요.")
            if self.stop_event.wait(1.0):
                return

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
            q = booking.queue_info(self.driver)
            if q.get("queue"):
                # 대기열에 잡혀 있는 것이지 창이 죽은 게 아니다. 기다린다.
                self.status(booking.queue_line(q) + " · 확인창을 기다립니다")
                continue
            self.log("확인창이 닫혔거나 체크가 풀렸습니다. 확인 경로만 다시 세웁니다.")
            self.status("확인창을 다시 세우는 중입니다...")
            if booking.redrive_confirm(self.driver, p, self.log):
                self.log("확인창을 다시 열어두었습니다.")
                continue
            # 여기서 준비를 처음부터 다시 하면 안 된다. [예약하기] 를 이미
            # 눌렀으므로 대기열 맨 뒤로 가고, 사람이 만들어 둔 것도 날아간다
            # (2026-08-26 실측: 앞에 72명 → 138명 → 177명).
            self.status("확인창을 다시 열지 못했습니다. 준비를 처음부터 다시 하면 "
                        "대기열 맨 뒤로 가므로 그렇게 하지 않습니다. "
                        "크롬 창에서 [예약하기] 를 눌러 확인창을 열어주세요.")
            self._watch_for_late_modal(
                booking.StepResult(False, "", "no_modal", p), open_epoch)

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
