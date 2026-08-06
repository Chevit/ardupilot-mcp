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
