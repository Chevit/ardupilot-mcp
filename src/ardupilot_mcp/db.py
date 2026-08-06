"""SQLite schema and query layer for the ArduPilot MCP server.

Stores parameter metadata for the Vehicles in the Vehicle Roster (see
roster.py), one firmware version at a time per vehicle — see
docs/adr/0001-single-firmware-version-per-vehicle.md. FTS5 provides keyword
search; vectors live in LanceDB (see vectors.py) and reference parameters.id.

Uniqueness: (vehicle, name, backend).
  - `backend` is NULL for the primary definition of a parameter and
    non-NULL for driver variants (e.g. AP_BattMonitor_Analog vs SMBus).
  - `firmware_version` is provenance only, not part of the key — it is
    whatever version the Vehicle Roster's URL last pointed at for that
    vehicle. Re-ingesting a vehicle replaces its rows wholesale, regardless
    of whether the firmware_version changed.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "ardupilot.db"
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS parameters (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle          TEXT NOT NULL,
    firmware_version TEXT NOT NULL,
    name             TEXT NOT NULL,
    backend          TEXT,                 -- 'AP_BattMonitor_Analog', NULL for main definition
    display_name     TEXT,
    description      TEXT,
    section          TEXT,
    units            TEXT,
    range_min        REAL,
    range_max        REAL,
    increment        REAL,
    reboot_required  INTEGER NOT NULL DEFAULT 0,
    is_bitmask       INTEGER NOT NULL DEFAULT 0,
    read_only        INTEGER NOT NULL DEFAULT 0,
    advanced         INTEGER NOT NULL DEFAULT 0,
    source_url       TEXT,
    scraped_at       TEXT,
    UNIQUE (vehicle, name, backend)
);
CREATE INDEX IF NOT EXISTS idx_parameters_name    ON parameters(name);
CREATE INDEX IF NOT EXISTS idx_parameters_section ON parameters(section);
CREATE INDEX IF NOT EXISTS idx_parameters_backend ON parameters(backend);
CREATE INDEX IF NOT EXISTS idx_parameters_fw      ON parameters(vehicle, firmware_version);

CREATE TABLE IF NOT EXISTS parameter_values (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    parameter_id INTEGER NOT NULL REFERENCES parameters(id) ON DELETE CASCADE,
    value        TEXT NOT NULL,
    label        TEXT NOT NULL,
    is_bit       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pv_parameter ON parameter_values(parameter_id);

CREATE VIRTUAL TABLE IF NOT EXISTS parameters_fts USING fts5(
    name,
    display_name,
    description,
    values_text,
    section,
    backend,
    vehicle          UNINDEXED,
    firmware_version UNINDEXED,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS ingestions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle          TEXT NOT NULL,
    firmware_version TEXT NOT NULL,
    source_path      TEXT,
    scraped_at       TEXT NOT NULL,
    param_count      INTEGER NOT NULL
);
"""


@dataclass
class ParameterValue:
    value: str          # "0", "1", or bit index like "5"
    label: str          # "Disabled", "Ignore RSSI", "Fast Attitude", etc.
    is_bit: bool = False


@dataclass
class Parameter:
    vehicle: str
    firmware_version: str               # e.g. '4.8.0'
    name: str
    backend: Optional[str] = None       # e.g. 'AP_BattMonitor_Analog'
    display_name: Optional[str] = None
    description: Optional[str] = None
    section: Optional[str] = None
    units: Optional[str] = None
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    increment: Optional[float] = None
    reboot_required: bool = False
    is_bitmask: bool = False
    read_only: bool = False
    advanced: bool = False
    source_url: Optional[str] = None
    values: list[ParameterValue] = field(default_factory=list)


def open_connection(db_path=DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a raw connection with FKs on and Row row factory.

    The caller owns the connection's lifetime — commit and close it
    themselves. Used directly by ParameterCatalog, which holds one
    connection open for its process lifetime; connect() below wraps this
    for the common open/commit/close-per-call case.

    Accepts either a str or a Path.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect(db_path=DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a connection via open_connection(). Commits on clean exit, always closes.

    Accepts either a str or a Path.
    """
    conn = open_connection(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_schema(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Create all tables and indexes. Idempotent."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def reset_vehicle(conn: sqlite3.Connection, vehicle: str) -> None:
    """Wipe all rows for a vehicle before a re-ingest.

    Only touches the requested vehicle — other vehicles remain intact.
    """
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM parameters WHERE vehicle = ?",
        (vehicle,),
    )]
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"DELETE FROM parameters_fts WHERE rowid IN ({placeholders})", ids
    )
    conn.execute(
        "DELETE FROM parameters WHERE vehicle = ?",
        (vehicle,),
    )


def ingested_version(conn: sqlite3.Connection, vehicle: str) -> Optional[str]:
    """The single firmware_version stored for a vehicle, or None if it has
    never been ingested. Provenance lookup, not a query filter — see
    docs/adr/0001-single-firmware-version-per-vehicle.md."""
    row = conn.execute(
        "SELECT firmware_version FROM parameters WHERE vehicle = ? LIMIT 1",
        (vehicle,),
    ).fetchone()
    return row["firmware_version"] if row is not None else None


def upsert_parameter(
    conn: sqlite3.Connection, param: Parameter, scraped_at: str
) -> int:
    """Insert (or replace) a parameter and its values. Returns the row id.

    IS used for backend comparison because NULL != NULL under equality.
    Matches on (vehicle, name, backend) only — firmware_version is
    provenance, not part of the key, so upserting a new version of an
    already-stored parameter replaces it regardless of the old value.
    """
    conn.execute(
        """DELETE FROM parameters
           WHERE vehicle = ? AND name = ? AND backend IS ?""",
        (param.vehicle, param.name, param.backend),
    )
    cur = conn.execute(
        """
        INSERT INTO parameters (
            vehicle, firmware_version, name, backend,
            display_name, description, section,
            units, range_min, range_max, increment,
            reboot_required, is_bitmask, read_only, advanced,
            source_url, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            param.vehicle, param.firmware_version, param.name, param.backend,
            param.display_name, param.description, param.section,
            param.units, param.range_min, param.range_max, param.increment,
            int(param.reboot_required), int(param.is_bitmask),
            int(param.read_only), int(param.advanced),
            param.source_url, scraped_at,
        ),
    )
    param_id = cur.lastrowid

    if param.values:
        conn.executemany(
            """INSERT INTO parameter_values (parameter_id, value, label, is_bit)
               VALUES (?, ?, ?, ?)""",
            [(param_id, v.value, v.label, int(v.is_bit)) for v in param.values],
        )

    values_text = " ".join(f"{v.value}={v.label}" for v in param.values)
    conn.execute(
        """
        INSERT INTO parameters_fts (
            rowid, name, display_name, description, values_text,
            section, backend, vehicle, firmware_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            param_id, param.name, param.display_name or "",
            param.description or "", values_text,
            param.section or "", param.backend or "",
            param.vehicle, param.firmware_version,
        ),
    )
    return param_id


def record_ingestion(
    conn: sqlite3.Connection,
    vehicle: str,
    firmware_version: str,
    source_path: str,
    scraped_at: str,
    count: int,
) -> None:
    conn.execute(
        """INSERT INTO ingestions
           (vehicle, firmware_version, source_path, scraped_at, param_count)
           VALUES (?, ?, ?, ?, ?)""",
        (vehicle, firmware_version, source_path, scraped_at, count),
    )
