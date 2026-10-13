# -*- coding: utf-8 -*-
"""v1.0.27: the first [확인] arrival aim is a customer setting.

Owner instruction (2026-10-13): the customer asked almost daily for a new aim
(-230 -> -240 -> -280) and had to wait for a build each time. The aim is now
the GUI field "[확인] 도착 목표 (정각 기준, ms)", stored under the NEW key
settings.json `confirm_aim_ms`. These tests pin:

  - the key absent (every v1.0.26 PC) -> the code default -280, source 기본값
  - a custom value (-300) flows to the aim, the startup line and the
    "조준 확정" line, source 설정값
  - invalid input is rejected with a Korean message, never a crash, and an
    invalid value in the file falls back to the default
  - stale obsolete keys (confirm_prehour_lead_ms etc.) never override it and
    are still stripped from the file
  - a plain save never freezes the default into the file (1.0.15 / 1.0.17 trap)
"""
import json

import pytest

from aisarang import config
from aisarang.runner import Runner, aim_confirm_line, aim_startup_line


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(config, "settings_path", lambda: p)
    return p


def _write(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_the_new_key_is_not_obsolete_and_not_a_frozen_default():
    assert config.CONFIRM_AIM_KEY == "confirm_aim_ms"
    assert config.CONFIRM_AIM_KEY not in config._OBSOLETE
    # Not in DEFAULT_SETTINGS: save_settings writes every DEFAULT_SETTINGS key,
    # which is exactly how 1.0.15 / 1.0.17 froze old defaults into the file.
    assert config.CONFIRM_AIM_KEY not in config.DEFAULT_SETTINGS
    for dead in ("arrival_safety_ms", "confirm_prehour_lead_ms",
                 "arrival_prehour_lead_ms", "reopen_max", "reopen_seconds"):
        assert dead in config._OBSOLETE
    assert config.CONFIRM_PREHOUR_LEAD_MS == -280.0
    assert config.CONFIRM_AIM_LABEL == "[확인] 도착 목표 (정각 기준, ms)"


def test_a_v1026_settings_file_without_the_key_gets_minus_280(settings_file):
    # What the customer PC has today (v1.0.26 wrote every DEFAULT_SETTINGS key).
    v1026 = dict(config.DEFAULT_SETTINGS)
    v1026["use_hours"] = 9
    _write(settings_file, v1026)
    data = config.load_settings()
    assert config.CONFIRM_AIM_KEY not in data
    r = Runner()
    assert r._arrival_aim(data) * 1000.0 == -280.0
    assert r._arrival_aim_source(data) == config.AIM_SOURCE_DEFAULT
    assert config.resolve_confirm_aim(data) == (-280.0, "default")
    start = aim_startup_line(-280.0, "default")
    assert "정각 280ms 전 도착 (서버시각 08:59:59.720, 기본값 -280ms" in start
    line = aim_confirm_line(r._arrival_aim(data), r._arrival_aim_source(data))
    assert line.startswith("조준 확정: 도착 목표 정각 -280ms (기본값, 서버시각 08:59:59.720")
    # Reported in every upload's meta.
    assert config.peek_confirm_aim() == (-280.0, "default")
    # And a plain save (what on_start does) must not freeze -280 into the file.
    assert config.save_settings(data)
    assert config.CONFIRM_AIM_KEY not in _read(settings_file)


def test_no_settings_file_at_all_gets_minus_280(settings_file):
    data = config.load_settings()
    r = Runner()
    assert r._arrival_aim(data) == -0.28
    assert r._arrival_aim({}) == -0.28
    assert r._arrival_aim(None) == -0.28
    assert r._arrival_aim_source(None) == config.AIM_SOURCE_DEFAULT


def test_a_custom_value_flows_to_the_aim_and_the_log_lines(settings_file):
    data = config.load_settings()
    data[config.CONFIRM_AIM_KEY] = -300
    assert config.save_settings(data)
    assert _read(settings_file)[config.CONFIRM_AIM_KEY] == -300

    data = config.load_settings()
    assert data[config.CONFIRM_AIM_KEY] == -300
    r = Runner()
    aim = r._arrival_aim(data)
    assert aim * 1000.0 == -300.0
    assert r._arrival_aim_source(data) == config.AIM_SOURCE_SETTINGS
    start = aim_startup_line(aim * 1000.0, r._arrival_aim_source(data))
    assert "정각 300ms 전 도착 (서버시각 08:59:59.700, 설정값 -300ms" in start
    line = aim_confirm_line(aim, r._arrival_aim_source(data))
    assert line.startswith("조준 확정: 도착 목표 정각 -300ms (설정값, 서버시각 08:59:59.700")
    assert config.peek_confirm_aim() == (-300.0, "settings")

    # The fire time moves with it (40ms round trip -> 20ms one way).
    from aisarang import clock as clockmod
    c = clockmod.ClockSync()
    c.offset, c.rtt_best = 0.0, 0.040
    c.lo, c.hi = -0.01, 0.01
    c.samples = 8
    c.synced = True
    assert c.one_way == 0.020
    open_epoch = 1_800_000_000.0
    fire = c.local_fire_for_arrival(open_epoch + aim)
    assert abs(fire - (open_epoch - 0.320)) < 1e-6


def test_after_the_hour_and_zero_values_read_correctly():
    assert "정각 120ms 뒤 도착 (서버시각 09:00:00.120, 설정값 +120ms" in \
        aim_startup_line(120.0, "settings")
    assert "조준 확정: 도착 목표 정각 +120ms (설정값, 서버시각 09:00:00.120, 정각 뒤 도착" in \
        aim_confirm_line(0.12, "settings")
    assert "정각 도착 (서버시각 09:00:00.000" in aim_startup_line(0.0, "settings")


@pytest.mark.parametrize("raw,want", [
    ("-280", -280), ("-300", -300), ("  -250 ", -250), ("+120", 120),
    ("0", 0), ("-280ms", -280), ("−300", -300), ("-1000", -1000),
    ("1000", 1000), (-300, -300), (-300.0, -300),
])
def test_valid_input_is_accepted(raw, want):
    v, err = config.parse_confirm_aim_ms(raw)
    assert err == "" and v == want


@pytest.mark.parametrize("raw", [
    "abc", "-28o", "-280.5", "1,000", "--280", "-1001", "1001", "99999",
    "-0.28", -280.5, float("nan"), True, [], {}, "280 ms ms",
])
def test_invalid_input_is_rejected_with_a_korean_message(raw):
    v, err = config.parse_confirm_aim_ms(raw)
    assert v is None
    assert err.startswith("[확인] 도착 목표는")


def test_blank_input_means_default():
    assert config.parse_confirm_aim_ms("") == (-280, "")
    assert config.parse_confirm_aim_ms("   ") == (-280, "")


def test_an_invalid_value_in_the_file_falls_back_to_default(settings_file):
    for bad in ("abc", 5000, -99999, 12.5, None, "", "  "):
        _write(settings_file, {"use_hours": 9, config.CONFIRM_AIM_KEY: bad})
        data = config.load_settings()
        assert config.CONFIRM_AIM_KEY not in data, bad
        assert Runner()._arrival_aim(data) == -0.28, bad
        assert Runner()._arrival_aim_source(data) == "default"
        # resolve also refuses junk passed straight in
        assert config.resolve_confirm_aim({config.CONFIRM_AIM_KEY: bad})[0] == -280.0
    # an invalid key is dropped from disk, a valid customer value is kept
    _write(settings_file, {"use_hours": 7, config.CONFIRM_AIM_KEY: "abc"})
    config.load_settings()
    on_disk = _read(settings_file)
    assert config.CONFIRM_AIM_KEY not in on_disk
    assert on_disk["use_hours"] == 7


def test_stale_obsolete_keys_do_not_override(settings_file):
    # A PC that ran 1.0.20 .. 1.0.26 might still carry these.
    for lead in (-500.0, -250.0, -100.0, -200.0, -230.0, -240.0, 900.0):
        _write(settings_file, {
            "confirm_prehour_lead_ms": lead, "arrival_prehour_lead_ms": lead,
            "arrival_safety_ms": 250, "arrival_after_ms": 250,
            "reopen_max": 2, "reopen_seconds": 15, "use_hours": 9})
        data = config.load_settings()
        assert Runner()._arrival_aim(data) == -0.28, lead
        assert Runner()._arrival_aim_source(data) == "default"
        on_disk = _read(settings_file)
        for dead in ("confirm_prehour_lead_ms", "arrival_prehour_lead_ms",
                     "arrival_safety_ms", "reopen_max", "reopen_seconds"):
            assert dead not in on_disk, (lead, dead)
        assert config.CONFIRM_AIM_KEY not in on_disk

    # With a customer value AND stale keys, the customer value wins and the
    # stale keys are stripped.
    _write(settings_file, {"confirm_prehour_lead_ms": -240.0,
                           "arrival_prehour_lead_ms": -240.0,
                           config.CONFIRM_AIM_KEY: -310, "use_hours": 9})
    data = config.load_settings()
    assert Runner()._arrival_aim(data) == -0.31
    on_disk = _read(settings_file)
    assert on_disk[config.CONFIRM_AIM_KEY] == -310
    assert "confirm_prehour_lead_ms" not in on_disk
    # Stale keys injected into a live dict are not read either.
    assert config.resolve_confirm_aim({"confirm_prehour_lead_ms": -999}) == (-280.0, "default")


def test_the_default_still_moves_for_pcs_that_never_set_it(settings_file, monkeypatch):
    """The 1.0.15 / 1.0.17 trap: a saved default must not shadow a new constant."""
    data = config.load_settings()
    config.save_settings(data)
    monkeypatch.setattr(config, "CONFIRM_PREHOUR_LEAD_MS", -260.0)
    data = config.load_settings()
    assert Runner()._arrival_aim(data) == -0.26


def test_the_reporter_meta_carries_the_aim_and_its_source(settings_file):
    from aisarang.reporter import Diagnostics
    m = Diagnostics().meta()
    assert m["aimMsEffective"] == -280.0 and m["aimSource"] == "default"
    assert m["aimSourceLabel"] == "기본값"
    assert m["aimPrehourLeadMs"] == -280.0
    _write(settings_file, {config.CONFIRM_AIM_KEY: -300})
    m = Diagnostics().meta()
    assert m["aimMsEffective"] == -300.0 and m["aimSource"] == "settings"
    assert m["aimSourceLabel"] == "설정값"
    assert m["aimSettingsKey"] == "confirm_aim_ms"


def test_finish_meta_reports_the_source(settings_file):
    r = Runner()
    sent = []
    r.diag.upload = lambda headline, meta=None, **k: sent.append((headline, meta))
    r.settings = {config.CONFIRM_AIM_KEY: -300}
    out = r._finish(False, "test", {"name": "x", "stcode": "1"}, "20261028", [])
    meta = out["meta"]
    assert meta["resolvedAimMs"] == -300.0
    assert meta["aimSource"] == "settings confirm_aim_ms"
    assert meta["aimSourceLabel"] == "설정값"
    assert sent and sent[0][1]["resolvedAimMs"] == -300.0
    r.settings = {}
    meta = r._finish(False, "test", {"name": "x", "stcode": "1"}, "20261028", [])["meta"]
    assert meta["resolvedAimMs"] == -280.0
    assert meta["aimSource"] == "default CONFIRM_PREHOUR_LEAD_MS"
    assert meta["aimSourceLabel"] == "기본값"
