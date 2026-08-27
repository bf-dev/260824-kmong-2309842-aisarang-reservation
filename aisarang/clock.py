# -*- coding: utf-8 -*-
"""서버 시각 동기화.

PC 시계는 믿지 않는다. 예약이 열리는 기준은 아이사랑 서버의 시계다.

childcare.go.kr 은 전용 시간 API 를 주지 않지만, 모든 HTTP 응답에
RFC 7231 `Date:` 헤더를 붙인다. 이 헤더는 초 단위라 그대로 쓰면 최대 1초가
틀어진다. 그래서 구간 교집합으로 초 이하까지 좁힌다.

한 번의 샘플에서 알 수 있는 것:
  로컬시각 t_mid 에 서버가 응답을 만들었고, 그때 서버 시각은 [S, S+1) 이었다.
  offset = server - local 이라 하면  offset ∈ [S - t_mid, S + 1 - t_mid).
샘플을 여러 번 받아 이 구간들을 교집합하면 offset 이 수십 ms 까지 좁혀진다.
서버의 '초가 바뀌는 순간'을 여러 각도에서 협공하는 셈이다.

t_mid 는 요청 직전/직후 로컬시각의 중점이다(왕복 지연이 대칭이라고 가정).
비대칭 지연은 그대로 오차로 남으므로, 마지막에 safe_arrival_after 여유가 흡수한다.

**한 번 재고 끝내지 않는다 (v1.0.6).** 고객은 전날 오후에 프로그램을 켜두고
다음 날 09시를 기다리기도 한다(실제 로그: 14:35 에 시작해서 09:00 발사).
그 사이에 PC 시계는 서버 시계와 조금씩 벌어지고, 처음 한 번 잰 오프셋은
그만큼 낡는다. 그래서 ClockKeeper 가 프로그램이 도는 내내
config.RESYNC_SECONDS(=5분)마다 처음과 똑같은 방식으로 다시 잰다.
"""
from __future__ import annotations

import email.utils
import threading
import time
from dataclasses import dataclass, field

from . import config


@dataclass
class ClockSync:
    """서버 시각과 로컬 시각의 차이(초)."""

    offset: float = 0.0
    lo: float = float("-inf")
    hi: float = float("inf")
    samples: int = 0
    rtt_best: float = float("inf")
    synced: bool = False
    detail: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    # 서버가 "예약시간전" 이라고 답했을 때 붙는 보정치(초). 아래 note_too_early 참고.
    correction: float = 0.0
    correction_notes: list = field(default_factory=list)
    # 재측정 이력. 몇 번 다시 쟀고 마지막이 언제였는지 로그/진단에 남는다.
    resyncs: int = 0
    last_sync_local: float = 0.0
    history: list = field(default_factory=list)
    drift_notes: list = field(default_factory=list)
    _lock: object = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def uncertainty(self) -> float:
        if self.lo == float("-inf") or self.hi == float("inf"):
            return float("inf")
        return self.hi - self.lo

    @property
    def one_way(self) -> float:
        """편도(보내는 쪽) 지연 추정치, 초.

        고객이 손으로 성공시킬 때 누른 시각은 08:59:59.xxx 였다. 즉 맞춰야 하는
        것은 '로컬에서 쏘는 시각'이 아니라 '서버에 도착하는 시각'이다.
        도착시각 = 로컬발사시각 + 편도지연 이므로, 편도지연만큼 미리 쏴야 한다.
        측정 가능한 것은 왕복(rtt)뿐이라 대칭을 가정해 절반으로 잡는다.
        비대칭이면 그만큼 오차가 남고, 그 오차는 safe_arrival_after 여유가 흡수한다.
        """
        if self.rtt_best == float("inf"):
            return 0.0
        return self.rtt_best / 2.0

    def server_now(self) -> float:
        return time.time() + self.offset

    def local_time_for(self, server_epoch: float) -> float:
        """서버 기준 시각을 로컬 time.time() 기준으로 환산."""
        return server_epoch - self.offset

    def local_fire_for_arrival(self, arrival_server_epoch: float) -> float:
        """서버에 이 시각에 '도착'시키려면 로컬 시계로 언제 쏴야 하는가."""
        return self.local_time_for(arrival_server_epoch) - self.one_way + self.correction

    def arrival_for_local_fire(self, local_epoch: float) -> float:
        """로컬 시계로 이 시각에 쏘면 서버 기준 언제 도착하는가(추정)."""
        return local_epoch + self.offset + self.one_way - self.correction

    def safe_arrival_after(self, safety: float = None) -> float:
        """정각 **뒤** 몇 초에 도착하도록 조준할지. 초 단위, 항상 양수.

        2026-08-27 09:00:00 에 v1.0.8 은 정각 300ms **전** 도착을 노렸고,
        서버는 "아직 예약 가능한 시간이 아닙니다." 로 그 한 발을 버렸다.
        서버는 자기 시계로 정각 전에 닿은 요청을 무조건 거절한다. 그러니
        조준점은 정각 뒤여야 하고, 얼마나 뒤인지는 **그 순간 측정된 오차**로
        정한다. 반올림한 상수를 쓰지 않는 이유가 이것이다.

            뒤로 미룰 양 = (오프셋 잔여구간 폭 / 2) + safety

        앞쪽 항은 우리가 서버 시각을 얼마나 모르는지 그 자체다(구간 교집합의
        한쪽 오차). 2026-08-27 실측 네 번: 434.0 / 421.5 / 423.6 / 434.6 ms.
        뒤쪽 항은 왕복 흔들림(146.5ms) + 발사 경로 지연(약 50ms) + 서버가
        Date 를 찍기까지의 시간(약 50ms) 이다. 기본 250ms.

        측정에 실패해 구간이 무한대면 최대값으로 간다. 모를수록 늦게 쏜다.
        """
        if safety is None:
            safety = config.ARRIVAL_SAFETY_MS / 1000.0
        half = self.uncertainty / 2.0
        if (not self.synced) or half != half or half == float("inf"):
            half = config.ARRIVAL_MAX_AFTER_MS / 1000.0
        want = half + max(float(safety), 0.0)
        lo = config.ARRIVAL_MIN_AFTER_MS / 1000.0
        hi = config.ARRIVAL_MAX_AFTER_MS / 1000.0
        return min(max(want, lo), hi)

    def note_too_early(self, est_arrival_offset: float,
                       margin: float = 0.03) -> float:
        """서버가 "예약시간전" 이라고 답한 사실로 도착 추정을 보정한다.

        우리 추정으로는 정각 대비 est_arrival_offset(초) 에 도착했다. 서버가
        "아직 예약시간이 아니다" 라고 답했다면, 실제 도착은 정각 **이전**이었다.
        즉 추정오차 err = (추정 도착 - 실제 도착) 에 대해

            추정 - err < 정각        →      err > est_arrival_offset

        est_arrival_offset 이 0 이상일 때만 새로운 정보다(우리는 정각 이후에
        도착했다고 믿었는데 서버는 아니라고 했으니, 그만큼은 확실히 이르다).
        일부러 앞당겨 쏜 경우(음수)에는 "예약시간전" 이 당연하므로 아무것도
        배우지 못한다. 배운 만큼 다음 발사를 뒤로 미룬다.

        돌려주는 값은 이번에 추가된 보정치(초). 0 이면 배운 게 없다는 뜻이다.
        """
        if est_arrival_offset is None or est_arrival_offset < 0:
            return 0.0
        want = est_arrival_offset + margin
        if want <= self.correction:
            return 0.0
        added = want - self.correction
        self.correction = want
        self.correction_notes.append(
            {"estArrivalOffsetMs": round(est_arrival_offset * 1000, 1),
             "correctionMs": round(self.correction * 1000, 1)})
        return added

    # -- 재측정 ------------------------------------------------------
    def adopt(self, fresh: "ClockSync") -> dict:
        """새로 잰 결과를 받아들인다. 실패한 측정은 절대 받지 않는다.

        받아들이는 것은 '방금 잰 값' 뿐이다. 구간(lo/hi)을 예전 것과 또 교집합
        하지 않는다. PC 시계와 서버 시계는 시간이 지나면 실제로 벌어지기 때문에,
        몇 시간 전 구간과 교집합하면 이미 틀린 구간에 새 측정을 가둬버린다.
        (한 번의 측정 안에서 하는 교집합은 그대로 유지된다. 그게 정확도의 핵심이다.)

        '예약시간전' 응답으로 얻은 보정치(correction)는 서버 동작에 대한 학습이라
        측정과 무관하다. 그래서 그대로 들고 간다.

        돌려주는 값: 이번 재측정으로 오프셋이 얼마나 움직였는지(초 단위 delta 포함).
        """
        if not fresh.synced:
            return {"adopted": False, "deltaMs": 0.0}
        with self._lock:
            before = self.offset if self.synced else fresh.offset
            self.offset = fresh.offset
            self.lo, self.hi = fresh.lo, fresh.hi
            self.samples = fresh.samples
            self.rtt_best = fresh.rtt_best
            self.detail = fresh.detail
            self.errors = fresh.errors
            self.synced = True
            self.resyncs += 1
            self.last_sync_local = time.time()
            row = {"at": round(self.last_sync_local, 3),
                   "n": self.resyncs,
                   "offsetMs": round(self.offset * 1000, 1),
                   "deltaMs": round((self.offset - before) * 1000, 1),
                   "uncertaintyMs": (round(self.uncertainty * 1000, 1)
                                     if self.uncertainty != float("inf") else None),
                   "rttBestMs": (round(self.rtt_best * 1000, 1)
                                 if self.rtt_best != float("inf") else None),
                   "samples": self.samples}
            self.history.append(row)
            if len(self.history) > 400:
                del self.history[:100]
        return {"adopted": True, "deltaMs": row["deltaMs"], "row": row}

    def age_seconds(self) -> float:
        """마지막 측정이 몇 초 전이었는지."""
        if not self.last_sync_local:
            return float("inf")
        return max(0.0, time.time() - self.last_sync_local)

    def note_drift_sample(self, server_epoch: float, t0: float, t1: float) -> dict:
        """샘플 한 개(세션 유지 응답의 Date 헤더)로 어긋남만 확인한다.

        **이 한 발로 오프셋을 움직이지 않는다.** Date 헤더는 초 단위라 한 발의
        구간은 최소 1초 폭이고, 왕복이 튀면 더 넓어진다. 그걸 그대로 반영하면
        잘 좁혀둔 값이 노이즈에 끌려다닌다. 그래서 판정만 한다:

          · 지금 오프셋이 이 샘플의 구간 안에 있으면 → 이상 없음
          · 벗어나 있으면 → 시계가 실제로 벌어진 것이므로 '즉시 다시 재라' 고 알린다

        권위는 언제나 12발짜리 구간 교집합(sync)이다.
        """
        rtt = max(0.0, t1 - t0)
        if rtt > 5.0 or rtt <= 0.0 or not self.synced:
            return {"usable": False, "reason": "rtt_out_of_range",
                    "rttMs": round(rtt * 1000, 1)}
        t_mid = t0 + rtt / 2.0
        half = rtt / 2.0
        lo = (server_epoch - t_mid) - half
        hi = (server_epoch + 1.0 - t_mid) + half
        margin = 0.05                       # 초 경계 판정의 여유
        offset = self.offset
        if offset < lo - margin:
            deviation = offset - (lo - margin)
        elif offset > hi + margin:
            deviation = offset - (hi + margin)
        else:
            deviation = 0.0
        note = {"usable": True,
                "consistent": deviation == 0.0,
                "deviationMs": round(deviation * 1000, 1),
                "offsetMs": round(offset * 1000, 1),
                "rttMs": round(rtt * 1000, 1),
                "windowMs": [round(lo * 1000, 1), round(hi * 1000, 1)]}
        with self._lock:
            self.drift_notes.append(note)
            if len(self.drift_notes) > 200:
                del self.drift_notes[:50]
        return note

    def describe(self) -> str:
        if not self.synced:
            return "서버 시각 동기화 실패 (PC 시계 사용)"
        return (
            f"서버 시각 동기화 완료: 보정 {self.offset * 1000:+.0f}ms "
            f"(오차 ±{self.uncertainty * 1000 / 2:.0f}ms, 샘플 {self.samples}개, "
            f"최소왕복 {self.rtt_best * 1000:.0f}ms, "
            f"편도 추정 {self.one_way * 1000:.0f}ms)"
        )


def _parse_date_header(value: str) -> float | None:
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt is None:
            return None
        return dt.timestamp()
    except Exception:
        return None


def sync(session=None, samples: int = 12, url: str | None = None,
         log=lambda *_: None, diag=None, deadline: float | None = None,
         quiet: bool = False) -> ClockSync:
    """Date 헤더를 여러 번 받아 offset 구간을 좁힌다.

    deadline 을 주면 그 로컬 시각을 넘겨서까지 샘플을 더 받지 않는다. 재측정이
    정각 근처까지 늘어지는 일을 막기 위한 것이다(회선이 느리면 12발에 15초까지
    걸린다). 그때까지 받은 샘플만으로 판정한다.
    """
    import requests

    sess = session or requests.Session()
    target = url or (config.BASE_URL + "/?menuno=1")
    out = ClockSync()

    errors: list[str] = []
    for i in range(samples):
        if deadline is not None and time.time() >= deadline:
            break
        try:
            t0 = time.time()
            r = sess.head(target, timeout=8, allow_redirects=False,
                          headers={"Cache-Control": "no-cache"})
            t1 = time.time()
        except Exception as exc:  # noqa: BLE001
            # 왜 실패했는지 남긴다. 망 차단인지 SSL/번들 문제인지 구분해야 한다.
            errors.append(f"{type(exc).__name__}: {exc}")
            continue

        raw = r.headers.get("Date")
        if not raw:
            continue
        s = _parse_date_header(raw)
        if s is None:
            continue

        rtt = t1 - t0
        t_mid = t0 + rtt / 2.0
        # 왕복 지연의 비대칭 가능성만큼 구간을 넓혀 안전하게 잡는다.
        half = rtt / 2.0
        lo = (s - t_mid) - half
        hi = (s + 1.0 - t_mid) + half

        new_lo = max(out.lo, lo)
        new_hi = min(out.hi, hi)
        if new_lo <= new_hi:                # 교집합이 살아있을 때만 반영
            out.lo, out.hi = new_lo, new_hi
        else:                               # 시계가 튀었으면 이 샘플로 재시작
            out.lo, out.hi = lo, hi

        out.samples += 1
        out.rtt_best = min(out.rtt_best, rtt)
        out.detail.append(
            {"i": i, "dateHeader": raw, "rttMs": round(rtt * 1000, 1),
             "loMs": round(out.lo * 1000, 1), "hiMs": round(out.hi * 1000, 1)}
        )
        time.sleep(0.13)                    # 초 경계를 여러 위상에서 훑는다

    if out.samples:
        out.offset = (out.lo + out.hi) / 2.0
        out.synced = True
        out.last_sync_local = time.time()

    out.errors = errors
    if not quiet:
        log(out.describe())
    if errors and not out.synced:
        log(f"서버 시각 요청 실패 사유: {errors[0]}")
    if diag is not None:
        try:
            diag.add_json("clock_sync.json",
                          {"offsetMs": round(out.offset * 1000, 1),
                           "uncertaintyMs": round(out.uncertainty * 1000, 1)
                           if out.uncertainty != float("inf") else None,
                           "target": target,
                           "errors": errors[:10],
                           "samples": out.detail})
        except Exception:
            pass
    return out


class ClockKeeper(threading.Thread):
    """프로그램이 도는 내내 서버 시각을 다시 재는 스레드.

    왜 필요한가. 고객은 전날 오후에 켜두고 다음 날 09시를 기다린다(실제 로그:
    14:35 시작 → 09:00 발사, 18시간). 처음 한 번 잰 오프셋을 18시간 들고 가면
    그 사이 PC 시계가 서버 시계와 벌어진 만큼 그대로 틀린다.

    규칙 (순서가 곧 우선순위다):
      1. 발사를 절대 방해하지 않는다. 정각 config.RESYNC_QUIET_SECONDS(90초)
         전부터는 아무것도 재지 않는다. 그 뒤로는 다시 켜지지 않는다.
         재측정은 브라우저를 전혀 건드리지 않는 별도 스레드의 requests 호출이라
         [확인] 클릭 경로와 겹치지도 않는다.
      2. 실패해도 아무 일도 일어나지 않는다. 마지막으로 성공한 값을 그대로 쓰고
         로그만 남긴다. 재측정 실패로 실행이 중단되는 일은 없다.
      3. 권위는 언제나 12발 구간 교집합이다(sync). 세션 유지 응답으로 얻는
         한 발짜리 샘플은 '어긋났는지' 판정만 하고, 어긋났으면 여기에 즉시
         다시 재라고 알린다(request_now).
    """

    def __init__(self, clock: ClockSync, interval: float = config.RESYNC_SECONDS,
                 samples: int = 12, log=lambda *_: None, diag=None,
                 stop_event=None, session_factory=None,
                 quiet_seconds: float = config.RESYNC_QUIET_SECONDS,
                 quiet_server_epoch: float | None = None):
        super().__init__(daemon=True, name="clock-keeper")
        self.clock = clock
        self.interval = max(float(interval), 5.0)
        self.samples = int(samples)
        self.log = log
        self.diag = diag
        self.stop_event = stop_event or threading.Event()
        self.session_factory = session_factory
        self.quiet_seconds = float(quiet_seconds)
        self.quiet_server_epoch = quiet_server_epoch   # 보통 정각(open_epoch)
        self.failures = 0
        self._wake = threading.Event()
        self._pending_reason = ""
        self._announced_quiet = False
        self._session = None

    # -- 밖에서 부르는 것 --------------------------------------------
    def request_now(self, reason: str = "") -> None:
        """다음 주기를 기다리지 않고 곧바로 다시 재게 한다."""
        self._pending_reason = reason
        self._wake.set()

    def in_quiet_window(self) -> bool:
        if self.quiet_server_epoch is None:
            return False
        return self.clock.server_now() >= self.quiet_server_epoch - self.quiet_seconds

    def stop(self) -> None:
        self.stop_event.set()
        self._wake.set()

    def sync_now(self, reason: str = "", force: bool = False) -> bool:
        """지금 이 자리에서(같은 스레드에서) 한 번 다시 잰다.

        준비(240초 창)를 시작하기 직전처럼 '지금 이 값이 최신이어야 하는' 자리에서
        부른다. 정각 직전이면 force 가 아닌 한 재지 않는다.
        """
        if self.in_quiet_window() and not force:
            return False
        return self._measure(reason, force=force)

    # -- 내부 ---------------------------------------------------------
    def _make_session(self):
        if self._session is not None:
            return self._session
        try:
            if self.session_factory is not None:
                self._session = self.session_factory()
            else:
                from . import site
                self._session = site.make_session()
        except Exception:                      # noqa: BLE001
            import requests
            self._session = requests.Session()
        return self._session

    def _budget_deadline(self, force: bool = False) -> float:
        """이번 측정을 언제까지 끝내야 하는지(로컬 시각)."""
        hard = time.time() + max(self.interval * 0.5, 20.0)
        if self.quiet_server_epoch is None or force:
            return hard
        quiet_local = self.clock.local_time_for(
            self.quiet_server_epoch - self.quiet_seconds)
        return min(hard, quiet_local)

    def _measure(self, reason: str = "", force: bool = False) -> bool:
        deadline = self._budget_deadline(force)
        if deadline - time.time() < 2.0:
            # 정각이 코앞이다. 지금 재느니 마지막 값을 그대로 쓰는 게 낫다.
            return False
        before = self.clock.offset if self.clock.synced else None
        try:
            fresh = sync(session=self._make_session(), samples=self.samples,
                         log=lambda *_: None, quiet=True, deadline=deadline)
        except Exception as exc:              # noqa: BLE001
            fresh = None
            self.log(f"서버 시각 재측정 실패(무시하고 계속합니다): {type(exc).__name__}")
        if fresh is None or not fresh.synced:
            self.failures += 1
            self._session = None              # 다음 번엔 새 연결로
            self.log("서버 시각 재측정 실패(무시하고 계속합니다). "
                     "직전에 맞춘 값을 그대로 씁니다: "
                     + self._short(self.clock))
            return False
        out = self.clock.adopt(fresh)
        n = self.clock.resyncs
        tail = f" · {reason}" if reason else ""
        if before is None:
            self.log(f"서버 시각 재측정({self._every()}, {n}회차): "
                     + self._short(self.clock) + tail)
        else:
            self.log(
                f"서버 시각 재측정({self._every()}, {n}회차): "
                f"보정 {before * 1000:+.0f}ms → {self.clock.offset * 1000:+.0f}ms "
                f"(변화 {out['deltaMs']:+.0f}ms, 오차 ±{self.clock.uncertainty * 500:.0f}ms, "
                f"샘플 {self.clock.samples}개, 최소왕복 {self.clock.rtt_best * 1000:.0f}ms)"
                + tail)
        self._dump()
        return True

    def _every(self) -> str:
        if self.interval % 60 == 0:
            return f"{int(self.interval // 60)}분마다"
        return f"{self.interval:.0f}초마다"

    @staticmethod
    def _short(c: ClockSync) -> str:
        if not c.synced:
            return "아직 한 번도 맞추지 못했습니다"
        return (f"보정 {c.offset * 1000:+.0f}ms "
                f"(오차 ±{c.uncertainty * 500:.0f}ms, 최소왕복 {c.rtt_best * 1000:.0f}ms)")

    def _dump(self) -> None:
        if self.diag is None:
            return
        try:
            self.diag.add_json("clock_resync.json", {
                "intervalSeconds": self.interval,
                "quietSeconds": self.quiet_seconds,
                "resyncs": self.clock.resyncs,
                "failures": self.failures,
                "offsetMs": round(self.clock.offset * 1000, 1),
                "history": self.clock.history[-60:],
                "driftChecks": self.clock.drift_notes[-60:],
            })
        except Exception:
            pass

    def run(self) -> None:
        while not self.stop_event.is_set():
            self._wake.wait(self.interval)
            if self.stop_event.is_set():
                return
            forced = self._wake.is_set()
            reason = self._pending_reason if forced else ""
            self._wake.clear()
            self._pending_reason = ""
            if self.in_quiet_window():
                if not self._announced_quiet:
                    self._announced_quiet = True
                    self.log(f"정각 {self.quiet_seconds:.0f}초 전입니다. 발사에 방해되지 "
                             f"않도록 서버 시각 재측정을 여기서 멈춥니다 "
                             f"(마지막 값: {self._short(self.clock)}).")
                continue
            self._measure(reason)


def next_open_epoch(clock: ClockSync, hour: int = config.OPEN_HOUR,
                    minute: int = config.OPEN_MINUTE) -> float:
    """서버(KST) 기준으로 다음 09:00 의 epoch 초를 돌려준다."""
    now = clock.server_now()
    kst = now + config.KST_OFFSET_SECONDS
    day_start = kst - (kst % 86400)                  # 그날 KST 00:00
    target = day_start + hour * 3600 + minute * 60
    if target <= kst:
        target += 86400
    return target - config.KST_OFFSET_SECONDS


def target_date_for(clock: ClockSync, lead_days: int = config.OPEN_LEAD_DAYS,
                    open_epoch: float | None = None) -> str:
    """그 09:00 에 열리는 이용일(YYYYMMDD, KST)."""
    import datetime as _dt

    base = open_epoch if open_epoch is not None else next_open_epoch(clock)
    kst = _dt.datetime.fromtimestamp(base + config.KST_OFFSET_SECONDS, _dt.timezone.utc)
    return (kst + _dt.timedelta(days=lead_days)).strftime("%Y%m%d")


class Countdown(threading.Thread):
    """정각까지 남은 시간을 UI 로 흘려보내는 스레드."""

    def __init__(self, clock: ClockSync, fire_epoch: float, tick_cb, stop_event):
        super().__init__(daemon=True)
        self.clock = clock
        self.fire_epoch = fire_epoch
        self.tick_cb = tick_cb
        self.stop_event = stop_event

    def run(self) -> None:
        while not self.stop_event.is_set():
            remain = self.fire_epoch - self.clock.server_now()
            if remain <= 0:
                break
            try:
                self.tick_cb(remain)
            except Exception:
                pass
            self.stop_event.wait(0.2 if remain < 10 else 0.5)


def sleep_until(clock: ClockSync, server_epoch: float, stop_event=None,
                spin_ms: int = 40) -> None:
    """서버 기준 지정 시각까지 대기. 마지막 spin_ms 는 바쁜 대기로 정밀하게."""
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        remain = server_epoch - clock.server_now()
        if remain <= spin_ms / 1000.0:
            break
        time.sleep(min(remain - spin_ms / 1000.0, 0.25))
    while clock.server_now() < server_epoch:
        if stop_event is not None and stop_event.is_set():
            return
        time.sleep(0.001)


def sleep_until_local(local_epoch: float, stop_event=None,
                      spin_ms: int = 40) -> None:
    """로컬 time.time() 기준 시각까지 대기. 마지막 spin_ms 는 바쁜 대기."""
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        remain = local_epoch - time.time()
        if remain <= spin_ms / 1000.0:
            break
        time.sleep(min(remain - spin_ms / 1000.0, 0.25))
    while time.time() < local_epoch:
        if stop_event is not None and stop_event.is_set():
            return
        time.sleep(0.001)


def sleep_until_arrival(clock: ClockSync, arrival_server_epoch: float,
                        stop_event=None, spin_ms: int = 40) -> None:
    """요청이 서버에 arrival_server_epoch 에 '도착'하도록 그만큼 미리 깨어난다."""
    sleep_until_local(clock.local_fire_for_arrival(arrival_server_epoch),
                      stop_event=stop_event, spin_ms=spin_ms)


def measure_arrival(session=None, clock: ClockSync | None = None,
                    deltas_ms=(-300, -120, 60, 250), url: str | None = None,
                    log=lambda *_: None, diag=None) -> dict:
    """도착시각 모델을 실제로 검증한다.

    서버의 '초가 바뀌는 경계' B 를 골라, B + delta 에 도착하도록 쏜다.
    응답의 Date 헤더는 서버가 요청을 처리한 초(=도착한 초)를 알려주므로,
      delta < 0  이면 Date == B-1   (경계 직전에 도착)
      delta > 0  이면 Date == B     (경계 직후에 도착)
    가 나와야 한다. 이게 맞으면 '발사시각'이 아니라 '도착시각'을 맞추고 있다는
    뜻이다. Date 헤더는 1초 해상도라 한 발로는 초 단위까지만 말할 수 있고,
    경계 양쪽을 여러 delta 로 협공해서 sub-second 정확도를 보인다.
    """
    import requests

    sess = session or requests.Session()
    target = url or (config.BASE_URL + "/?menuno=1")
    c = clock if (clock is not None and clock.synced) else sync(
        session=sess, samples=12, log=log)

    rows = []
    for delta in deltas_ms:
        now_srv = c.server_now()
        boundary = float(int(now_srv) + 2)          # 넉넉히 2초 뒤 경계
        want_arrival = boundary + delta / 1000.0
        fire_local = c.local_fire_for_arrival(want_arrival)

        while time.time() < fire_local - 0.04:
            time.sleep(min(fire_local - time.time() - 0.04, 0.2))
        while time.time() < fire_local:
            time.sleep(0.0005)

        t0 = time.time()
        try:
            r = sess.head(target, timeout=8, allow_redirects=False,
                          headers={"Cache-Control": "no-cache"})
        except Exception as exc:  # noqa: BLE001
            rows.append({"deltaMs": delta, "error": f"{type(exc).__name__}: {exc}"})
            continue
        t1 = time.time()
        served = _parse_date_header(r.headers.get("Date", "")) or 0.0
        expected = boundary - 1 if delta < 0 else boundary
        rows.append({
            "deltaMs": delta,
            "fireLateMs": round((t0 - fire_local) * 1000, 2),   # 스케줄러 오차
            "estArrivalOffsetMs": round(
                (c.arrival_for_local_fire(t0) - boundary) * 1000, 1),
            "serverSecond": int(served),
            "expectedSecond": int(expected),
            "match": int(served) == int(expected),
            "rttMs": round((t1 - t0) * 1000, 1),
        })
        log(f"도착 검증 delta={delta:+}ms → 서버 처리 초 {int(served)} "
            f"(기대 {int(expected)}) {'일치' if rows[-1].get('match') else '불일치'}")
        time.sleep(0.4)

    ok = [r for r in rows if r.get("match")]
    out = {
        "offsetMs": round(c.offset * 1000, 1),
        "uncertaintyMs": (round(c.uncertainty * 1000, 1)
                          if c.uncertainty != float("inf") else None),
        "rttBestMs": round(c.rtt_best * 1000, 1) if c.rtt_best != float("inf") else None,
        "oneWayMs": round(c.one_way * 1000, 1),
        "matched": len(ok),
        "total": len(rows),
        "samples": rows,
    }
    if diag is not None:
        try:
            diag.add_json("arrival_check.json", out)
        except Exception:
            pass
    return out
