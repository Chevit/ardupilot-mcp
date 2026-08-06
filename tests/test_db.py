"""Tests for the SQLite schema and connection helpers."""

from __future__ import annotations

import sqlite3

import pytest

from ardupilot_mcp import db


def test_open_connection_sets_row_factory_and_foreign_keys(tmp_path):
    conn = db.open_connection(tmp_path / "test.db")
    try:
        assert conn.row_factory is sqlite3.Row
        fk_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk_enabled == 1
    finally:
        conn.close()


def test_connect_commits_and_closes(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_schema(db_path)

    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO parameters (vehicle, firmware_version, name) VALUES (?, ?, ?)",
            ("plane", "4.8.0", "TEST_PARAM"),
        )

    # A fresh connection sees the committed row — connect() closed cleanly.
    conn2 = db.open_connection(db_path)
    try:
        row = conn2.execute(
            "SELECT name FROM parameters WHERE name = ?", ("TEST_PARAM",)
        ).fetchone()
        assert row["name"] == "TEST_PARAM"
    finally:
        conn2.close()


def test_unique_key_is_vehicle_name_backend_not_version(tmp_path):
    # ADR-0001: one firmware_version stored per vehicle. The uniqueness key
    # no longer includes firmware_version, so two rows for the same
    # (vehicle, name, backend) can never coexist even under different
    # firmware_version values. Non-NULL backend, since SQLite's UNIQUE
    # treats NULL != NULL — the NULL-backend case is handled by
    # upsert_parameter's manual delete-before-insert, not this constraint.
    db_path = tmp_path / "test.db"
    db.init_schema(db_path)
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO parameters (vehicle, firmware_version, name, backend) "
            "VALUES ('plane', '4.6.3', 'BATT2_I2C_BUS', 'AP_BattMonitor_SMBus')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO parameters (vehicle, firmware_version, name, backend) "
                "VALUES ('plane', '4.8.0', 'BATT2_I2C_BUS', 'AP_BattMonitor_SMBus')"
            )


def test_reset_vehicle_wipes_all_rows_for_that_vehicle_only(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_schema(db_path)
    with db.connect(db_path) as conn:
        db.upsert_parameter(
            conn,
            db.Parameter(vehicle="plane", firmware_version="4.6.3", name="RC_OPTIONS"),
            scraped_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_parameter(
            conn,
            db.Parameter(vehicle="copter", firmware_version="4.8.0", name="RC_OPTIONS"),
            scraped_at="2026-01-01T00:00:00+00:00",
        )

    with db.connect(db_path) as conn:
        db.reset_vehicle(conn, "plane")

    with db.connect(db_path) as conn:
        remaining = conn.execute("SELECT vehicle FROM parameters").fetchall()
        assert [r["vehicle"] for r in remaining] == ["copter"]
        fts_remaining = conn.execute(
            "SELECT vehicle FROM parameters_fts"
        ).fetchall()
        assert [r["vehicle"] for r in fts_remaining] == ["copter"]


def test_upsert_replaces_within_a_vehicle_regardless_of_version(tmp_path):
    # Ingesting plane again under a new firmware_version, without an
    # explicit reset_vehicle() first, still replaces the old row for the
    # same (vehicle, name, backend) — the key no longer distinguishes by
    # version, so an old and new version of the same parameter can't both
    # exist.
    db_path = tmp_path / "test.db"
    db.init_schema(db_path)
    with db.connect(db_path) as conn:
        db.upsert_parameter(
            conn,
            db.Parameter(vehicle="plane", firmware_version="4.6.3", name="RC_OPTIONS",
                         description="old"),
            scraped_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_parameter(
            conn,
            db.Parameter(vehicle="plane", firmware_version="4.8.0", name="RC_OPTIONS",
                         description="new"),
            scraped_at="2026-01-02T00:00:00+00:00",
        )

    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT firmware_version, description FROM parameters WHERE name = 'RC_OPTIONS'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["firmware_version"] == "4.8.0"
        assert rows[0]["description"] == "new"
