"""Tests for the ArduPilot parameter HTML scraper.

Golden tests run against the real HTML files in data/ardupilot-docs/ (no
synthetic copies — the fixture IS the thing that changes upstream, which is
exactly what these tests should react to). Edge-case tests use small
synthetic HTML snippets to pin regex/branch behavior independent of
whatever the current real docs happen to exercise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ardupilot_mcp.scraper import parse_html_file

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "ardupilot-docs"
FIXTURE_463 = FIXTURE_DIR / "Complete Parameter List — Plane documentation 4.6.3.html"
FIXTURE_480 = FIXTURE_DIR / "Complete Parameter List — Plane documentation 4.8.0.html"


@pytest.fixture(scope="module")
def params_463():
    return parse_html_file(FIXTURE_463, vehicle="plane", firmware_version="4.6.3")


@pytest.fixture(scope="module")
def params_480():
    return parse_html_file(FIXTURE_480, vehicle="plane", firmware_version="4.8.0")


def _by_name(params, name, backend=None):
    for p in params:
        if p.name == name and p.backend == backend:
            return p
    raise AssertionError(f"{name} (backend={backend}) not found")


def test_batt2_i2c_bus_backend_variants_grow(params_463, params_480):
    variants_463 = {p.backend for p in params_463 if p.name == "BATT2_I2C_BUS"}
    variants_480 = {p.backend for p in params_480 if p.name == "BATT2_I2C_BUS"}
    assert variants_463 == {"AP_BattMonitor_SMBus", "AP_BattMonitor_INA2xx"}
    assert variants_480 == {
        "AP_BattMonitor_SMBus", "AP_BattMonitor_INA2xx", "AP_BattMonitor_INA3221",
    }

    smbus = _by_name(params_480, "BATT2_I2C_BUS", backend="AP_BattMonitor_SMBus")
    assert smbus.range_min == 0
    assert smbus.range_max == 3
    assert smbus.advanced is True
    assert smbus.reboot_required is True


def test_pinned_parameter_count_463(params_463):
    assert len(params_463) == 4619


def test_pinned_parameter_count_480(params_480):
    assert len(params_480) == 5596


def test_rc_options_bitmask_grows_between_versions(params_463, params_480):
    rc_463 = _by_name(params_463, "RC_OPTIONS")
    rc_480 = _by_name(params_480, "RC_OPTIONS")
    assert rc_463.is_bitmask is True
    assert rc_463.advanced is True
    assert len(rc_463.values) == 14
    assert len(rc_480.values) == 15
    assert rc_480.values[-1].label == "Clear MAVLink overrides on any stick input"


def test_log_bitmask_identical_across_versions(params_463, params_480):
    lb_463 = _by_name(params_463, "LOG_BITMASK")
    lb_480 = _by_name(params_480, "LOG_BITMASK")
    assert len(lb_463.values) == len(lb_480.values) == 18
    assert lb_463.values[0].label == lb_480.values[0].label == "Fast Attitude"


def test_stab_pitch_down_range_units_increment(params_463, params_480):
    for params in (params_463, params_480):
        p = _by_name(params, "STAB_PITCH_DOWN")
        assert p.range_min == 0
        assert p.range_max == 15
        assert p.units == "degrees"
        assert p.increment == 0.1
        assert p.advanced is True


def test_telem_delay_renamed_between_versions(params_463, params_480):
    telem_463 = _by_name(params_463, "TELEM_DELAY")
    assert telem_463.units == "seconds"
    assert telem_463.range_min == 0
    assert telem_463.range_max == 30

    assert not any(p.name == "TELEM_DELAY" for p in params_480)
    assert any(p.name == "MAV_TELEM_DELAY" for p in params_480)


def _write_html(tmp_path, body: str) -> Path:
    html_path = tmp_path / "synthetic.html"
    html_path.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return html_path


def test_malformed_heading_is_skipped(tmp_path):
    html_path = _write_html(tmp_path, """
        <section>
          <h3>not a valid heading¶</h3>
          <p>Should be skipped.</p>
        </section>
        <section>
          <h3>REAL_PARAM: A real one¶</h3>
          <p>Kept.</p>
        </section>
    """)
    params = parse_html_file(html_path, vehicle="plane", firmware_version="9.9.9")
    assert [p.name for p in params] == ["REAL_PARAM"]


def test_heading_without_backend_suffix(tmp_path):
    html_path = _write_html(tmp_path, """
        <section>
          <h3>SIMPLE_PARAM: A simple parameter¶</h3>
          <p>Description.</p>
        </section>
    """)
    params = parse_html_file(html_path, vehicle="plane", firmware_version="9.9.9")
    assert params[0].backend is None


def test_heading_with_backend_suffix(tmp_path):
    html_path = _write_html(tmp_path, """
        <section>
          <h3>SOME_PARAM (SomeBackend): A driver-specific parameter¶</h3>
          <p>Description.</p>
        </section>
    """)
    params = parse_html_file(html_path, vehicle="plane", firmware_version="9.9.9")
    assert params[0].backend == "SomeBackend"


def test_range_with_to_wording_and_bare_space(tmp_path):
    html_path = _write_html(tmp_path, """
        <section>
          <h3>RANGE_WITH_TO: Param A¶</h3>
          <p>Desc.</p>
          <table><thead><tr><th>Range</th></tr></thead>
          <tbody><tr><td>-100 to 100</td></tr></tbody></table>
        </section>
        <section>
          <h3>RANGE_BARE: Param B¶</h3>
          <p>Desc.</p>
          <table><thead><tr><th>Range</th></tr></thead>
          <tbody><tr><td>0.0 1.0</td></tr></tbody></table>
        </section>
    """)
    params = parse_html_file(html_path, vehicle="plane", firmware_version="9.9.9")
    by_name = {p.name: p for p in params}
    assert by_name["RANGE_WITH_TO"].range_min == -100
    assert by_name["RANGE_WITH_TO"].range_max == 100
    assert by_name["RANGE_BARE"].range_min == 0.0
    assert by_name["RANGE_BARE"].range_max == 1.0


def test_advanced_flag_present_and_absent(tmp_path):
    html_path = _write_html(tmp_path, """
        <section>
          <h3>ADVANCED_PARAM: Param A¶</h3>
          <div class="line-block"><div class="line"><em>Note: This parameter is for advanced users</em></div></div>
          <p>Desc.</p>
        </section>
        <section>
          <h3>PLAIN_PARAM: Param B¶</h3>
          <p>Desc.</p>
        </section>
    """)
    params = parse_html_file(html_path, vehicle="plane", firmware_version="9.9.9")
    by_name = {p.name: p for p in params}
    assert by_name["ADVANCED_PARAM"].advanced is True
    assert by_name["PLAIN_PARAM"].advanced is False
