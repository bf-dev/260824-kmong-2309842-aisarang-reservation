# -*- coding: utf-8 -*-
"""맞춰야 하는 것은 '발사 시각'이 아니라 '도착 시각'이다.

고객이 손으로 성공시킬 때 누른 시각은 08:59:59.xxx 였다. 즉 요청이 서버에
닿는 순간이 정각 언저리여야 한다. 로컬에서 정각에 쏘면 편도지연만큼 늦게
도착한다. 그래서 편도지연을 빼고 쏜다.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import clock as clockmod


def _clock(offset=0.0, rtt=0.040):
    c = clockmod.ClockSync()
    c.offset = offset
    c.rtt_best = rtt
    c.lo, c.hi = offset - 0.01, offset + 0.01
    c.samples = 8
    c.synced = True
    return c


def test_one_way_is_half_the_best_rtt():
    assert _clock(rtt=0.040).one_way == 0.020


def test_unmeasured_rtt_does_not_shift_anything():
    c = clockmod.ClockSync()
    assert c.one_way == 0.0


def test_fire_is_earlier_than_the_wanted_arrival_by_one_way():
    c = _clock(offset=0.0, rtt=0.040)
    arrival = 1_800_000_000.0
    assert abs(c.local_fire_for_arrival(arrival) - (arrival - 0.020)) < 1e-9


def test_server_offset_and_one_way_both_apply():
    c = _clock(offset=1.5, rtt=0.100)          # 서버가 로컬보다 1.5초 빠름
    arrival = 1_800_000_000.0
    # 로컬시각 = 서버시각 - offset, 거기서 편도(50ms)만큼 더 앞당긴다
    assert abs(c.local_fire_for_arrival(arrival) - (arrival - 1.5 - 0.050)) < 1e-9


def test_arrival_is_the_inverse_of_fire():
    c = _clock(offset=-0.3, rtt=0.080)
    arrival = 1_800_000_000.0
    fire = c.local_fire_for_arrival(arrival)
    assert abs(c.arrival_for_local_fire(fire) - arrival) < 1e-9


def test_firing_at_the_open_instant_would_arrive_late():
    """예전 방식(로컬에서 정각에 발사)은 편도지연만큼 늦게 도착한다."""
    c = _clock(offset=0.0, rtt=0.060)
    open_epoch = 1_800_000_000.0
    late = c.arrival_for_local_fire(c.local_time_for(open_epoch)) - open_epoch
    assert abs(late - 0.030) < 1e-6      # float64 로 epoch 를 다루는 만큼의 오차


def test_sleep_until_local_is_accurate():
    target = time.time() + 0.25
    clockmod.sleep_until_local(target)
    assert 0 <= time.time() - target < 0.02


def test_sleep_until_arrival_wakes_one_way_early():
    c = _clock(offset=0.0, rtt=0.200)          # 편도 100ms
    arrival = time.time() + 0.35
    clockmod.sleep_until_arrival(c, arrival)
    fired = time.time()
    assert -0.02 < (arrival - fired) - 0.100 < 0.02


def test_describe_reports_the_one_way_estimate():
    assert "편도 추정 20ms" in _clock(rtt=0.040).describe()
