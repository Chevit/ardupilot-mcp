"""Tests for ParameterCatalog — the read-side seam over SQLite + VectorStore."""

from __future__ import annotations

import pytest

from ardupilot_mcp import db
from ardupilot_mcp.catalog import ParameterCatalog


@pytest.fixture
def catalog(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_schema(db_path)
    with db.connect(db_path) as conn:
        # RC_OPTIONS: same name across two versions, values list grows.
        db.upsert_parameter(
            conn,
            db.Parameter(
                vehicle="plane", firmware_version="4.6.3", name="RC_OPTIONS",
                display_name="RC options", description="RC input options",
                section="RC Input", is_bitmask=True,
                values=[db.ParameterValue(value="0", label="Ignore RC Receiver", is_bit=True)],
            ),
            scraped_at="2026-01-01T00:00:00+00:00",
        )
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
    )
    yield cat
    cat.close()


def test_list_versions_returns_sorted_versions(catalog):
    assert catalog.list_versions("plane") == ["4.6.3", "4.8.0"]


def test_lookup_parameter_defaults_to_latest_version(catalog):
    param = catalog.lookup_parameter("RC_OPTIONS")
    assert param["firmware_version"] == "4.8.0"
    assert len(param["values"]) == 2


def test_lookup_parameter_specific_version(catalog):
    param = catalog.lookup_parameter("RC_OPTIONS", firmware_version="4.6.3")
    assert len(param["values"]) == 1


def test_lookup_parameter_not_found_returns_none(catalog):
    assert catalog.lookup_parameter("NOPE") is None


def test_lookup_parameter_reports_backend_variants(catalog):
    param = catalog.lookup_parameter("BATT2_I2C_BUS", firmware_version="4.8.0")
    assert param["backend"] is None
    assert param["backend_variants"] == ["AP_BattMonitor_INA2xx", "AP_BattMonitor_SMBus"]


def test_search_parameters_keyword_match(catalog):
    results = catalog.search_parameters("options")
    assert {r["firmware_version"] for r in results} == {"4.6.3", "4.8.0"}

    filtered = catalog.search_parameters("options", firmware_version="4.6.3")
    assert len(filtered) == 1
    assert filtered[0]["firmware_version"] == "4.6.3"


def test_list_parameters_by_prefix(catalog):
    results = catalog.list_parameters(prefix="BATT2", firmware_version="4.8.0")
    assert [r["name"] for r in results] == ["BATT2_I2C_BUS"]
    assert results[0]["backend"] is None  # backend variants excluded from browse


def test_list_parameters_by_section(catalog):
    results = catalog.list_parameters(section="RC Input", firmware_version="4.8.0")
    assert [r["name"] for r in results] == ["RC_OPTIONS"]


def test_diff_parameter_reports_value_differences(catalog):
    result = catalog.diff_parameter("RC_OPTIONS", "4.6.3", "4.8.0")
    assert result["exists_in_a"] is True
    assert result["exists_in_b"] is True
    assert [d["field"] for d in result["differences"]] == ["values"]


def test_diff_parameter_missing_in_one_version(catalog):
    result = catalog.diff_parameter("BATT2_I2C_BUS", "4.6.3", "4.8.0")
    assert result["exists_in_a"] is False
    assert result["exists_in_b"] is True
    assert result["differences"] == []


def test_semantic_search_returns_empty_when_no_vector_index(catalog):
    assert catalog.semantic_search("why is my plane climbing") == []
