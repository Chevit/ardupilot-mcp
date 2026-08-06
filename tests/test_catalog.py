"""Tests for ParameterCatalog — the read-side seam over SQLite + VectorStore."""

from __future__ import annotations

import json

import pytest

from ardupilot_mcp import db
from ardupilot_mcp.catalog import ParameterCatalog


@pytest.fixture
def roster_path(tmp_path):
    path = tmp_path / "vehicles.json"
    path.write_text(json.dumps({
        "plane": {"url": "https://example.test/plane.html", "enabled": True},
        "copter": {"url": "https://example.test/copter.html", "enabled": True},
        "blimp": {"url": "https://example.test/blimp.html", "enabled": False},
    }))
    return path


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_schema(path)
    return path


@pytest.fixture
def catalog(tmp_path, roster_path, db_path):
    with db.connect(db_path) as conn:
        # RC_OPTIONS on plane and, separately, on copter — same name,
        # different definitions, used for cross-vehicle diffing.
        db.upsert_parameter(
            conn,
            db.Parameter(
                vehicle="plane", firmware_version="4.8.0", name="RC_OPTIONS",
                display_name="RC options", description="RC input options",
                section="RC Input", is_bitmask=True,
                values=[
                    db.ParameterValue(value="0", label="Ignore RC Receiver", is_bit=True),
                    db.ParameterValue(value="14", label="Clear MAVLink overrides", is_bit=True),
                ],
            ),
            scraped_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_parameter(
            conn,
            db.Parameter(
                vehicle="copter", firmware_version="4.7.0", name="RC_OPTIONS",
                display_name="RC options", description="RC input options",
                section="RC Input", is_bitmask=True,
                values=[db.ParameterValue(value="0", label="Ignore RC Receiver", is_bit=True)],
            ),
            scraped_at="2026-01-01T00:00:00+00:00",
        )
        # BATT2_I2C_BUS: a main (backend=None) definition plus two backend variants.
        db.upsert_parameter(
            conn,
            db.Parameter(
                vehicle="plane", firmware_version="4.8.0", name="BATT2_I2C_BUS",
                description="Battery monitor I2C bus number", section="Battery Monitor",
                range_min=0, range_max=3,
            ),
            scraped_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_parameter(
            conn,
            db.Parameter(
                vehicle="plane", firmware_version="4.8.0", name="BATT2_I2C_BUS",
                backend="AP_BattMonitor_SMBus",
                description="Battery monitor I2C bus number", section="Battery Monitor",
                range_min=0, range_max=3,
            ),
            scraped_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_parameter(
            conn,
            db.Parameter(
                vehicle="plane", firmware_version="4.8.0", name="BATT2_I2C_BUS",
                backend="AP_BattMonitor_INA2xx",
                description="Battery monitor I2C bus number", section="Battery Monitor",
                range_min=0, range_max=3,
            ),
            scraped_at="2026-01-01T00:00:00+00:00",
        )

    cat = ParameterCatalog(
        db_path=db_path,
        vectors_path=tmp_path / "vectors.lance",
        model_cache_path=tmp_path / "model-cache",
        vehicles_config=roster_path,
    )
    yield cat
    cat.close()


# -- list_vehicles -- #

def test_list_vehicles_reports_enabled_and_ingested_state(catalog):
    result = {v["vehicle"]: v for v in catalog.list_vehicles()}

    assert result["plane"] == {
        "vehicle": "plane", "enabled": True, "ingested_version": "4.8.0",
    }
    assert result["copter"] == {
        "vehicle": "copter", "enabled": True, "ingested_version": "4.7.0",
    }
    # On the roster, disabled, never ingested.
    assert result["blimp"] == {
        "vehicle": "blimp", "enabled": False, "ingested_version": None,
    }


# -- lookup_parameter: vehicle is a hard filter, required -- #

def test_lookup_parameter_requires_vehicle(catalog):
    with pytest.raises(TypeError):
        catalog.lookup_parameter("RC_OPTIONS")


def test_lookup_parameter_returns_the_stored_version(catalog):
    param = catalog.lookup_parameter("RC_OPTIONS", vehicle="plane")
    assert param["firmware_version"] == "4.8.0"
    assert len(param["values"]) == 2


def test_lookup_parameter_is_scoped_to_vehicle(catalog):
    plane_param = catalog.lookup_parameter("RC_OPTIONS", vehicle="plane")
    copter_param = catalog.lookup_parameter("RC_OPTIONS", vehicle="copter")
    assert len(plane_param["values"]) == 2
    assert len(copter_param["values"]) == 1


def test_lookup_parameter_not_found_returns_none(catalog):
    assert catalog.lookup_parameter("NOPE", vehicle="plane") is None


def test_lookup_parameter_reports_backend_variants(catalog):
    param = catalog.lookup_parameter("BATT2_I2C_BUS", vehicle="plane")
    assert param["backend"] is None
    assert param["backend_variants"] == ["AP_BattMonitor_INA2xx", "AP_BattMonitor_SMBus"]


# -- search_parameters: vehicle=None means "all enabled" -- #

def test_search_parameters_scoped_to_one_vehicle(catalog):
    results = catalog.search_parameters("options", vehicle="plane")
    assert {r["vehicle"] for r in results} == {"plane"}


def test_search_parameters_vehicle_none_searches_all_enabled(catalog):
    results = catalog.search_parameters("options", vehicle=None)
    assert {r["vehicle"] for r in results} == {"plane", "copter"}


def test_search_parameters_vehicle_none_excludes_disabled(catalog, db_path):
    # blimp is on the roster but disabled ("enabled": False in roster_path),
    # yet already has data — the state left behind by an explicit one-off
    # `--vehicle blimp` ingest (Q11: enabled governs fetching, not
    # reachability). vehicle=None must not surface it...
    with db.connect(db_path) as conn:
        db.upsert_parameter(
            conn,
            db.Parameter(vehicle="blimp", firmware_version="1.0.0", name="ANOTHER_OPTIONS",
                         description="options for blimp"),
            scraped_at="2026-01-01T00:00:00+00:00",
        )

    unscoped = catalog.search_parameters("options", vehicle=None)
    assert "blimp" not in {r["vehicle"] for r in unscoped}

    # ...but an explicit vehicle="blimp" query still reaches it.
    scoped = catalog.search_parameters("options", vehicle="blimp")
    assert {r["vehicle"] for r in scoped} == {"blimp"}


def test_search_parameters_no_firmware_version_param(catalog):
    # firmware_version is provenance-only now; search_parameters must not
    # accept it as a filter argument at all.
    with pytest.raises(TypeError):
        catalog.search_parameters("options", firmware_version="4.8.0")


# -- list_parameters: vehicle is a hard filter, required -- #

def test_list_parameters_requires_vehicle(catalog):
    with pytest.raises(TypeError):
        catalog.list_parameters(prefix="BATT2")


def test_list_parameters_by_prefix(catalog):
    results = catalog.list_parameters(vehicle="plane", prefix="BATT2")
    assert [r["name"] for r in results] == ["BATT2_I2C_BUS"]
    assert results[0]["backend"] is None  # backend variants excluded from browse


def test_list_parameters_by_section(catalog):
    results = catalog.list_parameters(vehicle="plane", section="RC Input")
    assert [r["name"] for r in results] == ["RC_OPTIONS"]


def test_list_parameters_scoped_to_vehicle(catalog):
    results = catalog.list_parameters(vehicle="copter", section="RC Input")
    assert [r["vehicle"] for r in results] == ["copter"]


# -- diff_parameter: now compares two VEHICLES, not two versions -- #

def test_diff_parameter_compares_vehicles(catalog):
    result = catalog.diff_parameter("RC_OPTIONS", "plane", "copter")
    assert result["vehicle_a"] == "plane"
    assert result["vehicle_b"] == "copter"
    assert result["exists_in_a"] is True
    assert result["exists_in_b"] is True
    assert [d["field"] for d in result["differences"]] == ["values"]


def test_diff_parameter_reports_version_provenance_and_mismatch(catalog):
    # plane is 4.8.0, copter is 4.7.0 in the fixture — different versions,
    # so comparing across vehicles must flag that the two sides aren't at
    # the same firmware_version.
    result = catalog.diff_parameter("RC_OPTIONS", "plane", "copter")
    assert result["version_a"] == "4.8.0"
    assert result["version_b"] == "4.7.0"
    assert result["version_mismatch"] is True


def test_diff_parameter_no_mismatch_when_versions_match(catalog, tmp_path, roster_path):
    db_path = tmp_path / "same_version.db"
    db.init_schema(db_path)
    with db.connect(db_path) as conn:
        for vehicle in ("plane", "copter"):
            db.upsert_parameter(
                conn,
                db.Parameter(vehicle=vehicle, firmware_version="4.8.0", name="X"),
                scraped_at="2026-01-01T00:00:00+00:00",
            )
    cat = ParameterCatalog(
        db_path=db_path, vectors_path=tmp_path / "v2.lance",
        model_cache_path=tmp_path / "mc2", vehicles_config=roster_path,
    )
    try:
        result = cat.diff_parameter("X", "plane", "copter")
        assert result["version_mismatch"] is False
    finally:
        cat.close()


def test_diff_parameter_missing_in_one_vehicle(catalog):
    result = catalog.diff_parameter("BATT2_I2C_BUS", "plane", "copter")
    assert result["exists_in_a"] is True
    assert result["exists_in_b"] is False
    assert result["differences"] == []


# -- semantic_search -- #

def test_semantic_search_returns_empty_when_no_vector_index(catalog):
    assert catalog.semantic_search("why is my plane climbing", vehicle="plane") == []
