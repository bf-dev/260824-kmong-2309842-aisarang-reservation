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

    @property
    def uncertainty(self) -> float:
        if self.lo == float("-inf") or self.hi == float("inf"):
            return float("inf")
        return self.hi - self.lo

    def server_now(self) -> float:
        return time.time() + self.offset

    def local_time_for(self, server_epoch: float) -> float:
        """서버 기준 시각을 로컬 time.time() 기준으로 환산."""
        return server_epoch - self.offset

    def describe(self) -> str:
        if not self.synced:
            return "서버 시각 동기화 실패 (PC 시계 사용)"
        return (
            f"서버 시각 동기화 완료: 보정 {self.offset * 1000:+.0f}ms "
            f"(오차 ±{self.uncertainty * 1000 / 2:.0f}ms, 샘플 {self.samples}개, "
            f"최소왕복 {self.rtt_best * 1000:.0f}ms)"
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

    for i in range(samples):
        try:
            t0 = time.time()
            r = sess.head(target, timeout=8, allow_redirects=False,
                          headers={"Cache-Control": "no-cache"})
            t1 = time.time()
        except Exception:
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

    log(out.describe())
    if diag is not None:
        try:
            diag.add_json("clock_sync.json",
                          {"offsetMs": round(out.offset * 1000, 1),
                           "uncertaintyMs": round(out.uncertainty * 1000, 1)
                           if out.uncertainty != float("inf") else None,
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
    kst = _dt.datetime.utcfromtimestamp(base + config.KST_OFFSET_SECONDS)
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
