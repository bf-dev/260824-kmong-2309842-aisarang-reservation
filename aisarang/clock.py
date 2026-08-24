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
비대칭 지연은 그대로 오차로 남으므로, 마지막에 prefire_ms 로 여유를 준다.
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
        비대칭이면 그만큼 오차가 남고, 그 오차는 arrival_lead_ms 여유가 흡수한다.
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
         log=lambda *_: None, diag=None) -> ClockSync:
    """Date 헤더를 여러 번 받아 offset 구간을 좁힌다."""
    import requests

    sess = session or requests.Session()
    target = url or (config.BASE_URL + "/?menuno=1")
    out = ClockSync()

    errors: list[str] = []
    for i in range(samples):
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

    out.errors = errors
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
