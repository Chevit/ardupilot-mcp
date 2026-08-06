"""Tests for the Vehicle Roster — the authoritative list of Vehicles this
install knows about. See CONTEXT.md for the Vehicle Roster definition and
ADR-0002 for why the roster lives outside code.
"""

from __future__ import annotations

import json

import pytest

from ardupilot_mcp.roster import (
    PACKAGED_ROSTER_PATH,
    VehicleEntry,
    enabled_vehicles,
    load_roster,
)


def test_packaged_roster_has_six_vehicles_two_enabled():
    roster = load_roster()
    assert set(roster) == {
        "plane", "copter", "rover", "sub", "blimp", "antennatracker",
    }
    # Only plane and copter are fetched by --all out of the box; the rest
    # ship present-but-disabled, reachable via --roster or --vehicle.
    assert enabled_vehicles(roster) == ["copter", "plane"]
    assert roster["blimp"].enabled is False
    assert roster["plane"].url == "https://ardupilot.org/plane/docs/parameters.html"


def test_packaged_roster_file_exists_on_disk():
    # load_roster()'s fallback depends on this file shipping in the package.
    assert PACKAGED_ROSTER_PATH.exists()


def test_explicit_path_overrides_completely(tmp_path):
    custom = tmp_path / "vehicles.json"
    custom.write_text(json.dumps({
        "plane": {"url": "https://example.test/plane.html", "enabled": True},
    }))

    roster = load_roster(custom)

    assert set(roster) == {"plane"}  # copter etc. are NOT merged in
    assert roster["plane"].url == "https://example.test/plane.html"


def test_explicit_path_missing_raises(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        load_roster(missing)


def test_enabled_defaults_to_true_when_omitted(tmp_path):
    custom = tmp_path / "vehicles.json"
    custom.write_text(json.dumps({
        "plane": {"url": "https://example.test/plane.html"},
    }))

    roster = load_roster(custom)

    assert roster["plane"].enabled is True


def test_vehicle_entry_is_a_simple_value_object():
    entry = VehicleEntry(url="https://example.test/x.html", enabled=False)
    assert entry.url == "https://example.test/x.html"
    assert entry.enabled is False
