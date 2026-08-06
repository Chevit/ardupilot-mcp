"""Tests for the SQLite schema and connection helpers."""

from __future__ import annotations

import sqlite3

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
