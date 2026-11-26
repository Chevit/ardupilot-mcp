# db

SQLite schema, record types and write helpers for parameter storage.

## Overview

Stores one firmware version per vehicle ([ADR 0001](../adr/0001-single-firmware-version-per-vehicle.md)). Rows are
unique on `(vehicle, name, backend)`: `backend` is `NULL` for a parameter's main definition and non-null for driver
variants (e.g. `AP_BattMonitor_Analog`). `firmware_version` is provenance, not part of the key. Keyword search uses an
FTS5 table whose `rowid` equals `parameters.id`.

Tables: `parameters`, `parameter_values` (enum values / bitmask bits, `ON DELETE CASCADE`), `parameters_fts` (FTS5,
`unicode61` tokenizer), `ingestions` (one row per load).

## Public API

### DEFAULT_DB_PATH / SCHEMA

```python
DEFAULT_DB_PATH  # <repo>/data/ardupilot.db
SCHEMA: str      # CREATE ... IF NOT EXISTS script for every table and index
```

### ParameterValue

```python
@dataclass
class ParameterValue:
    value: str          # "0", "1", or a bit index like "5"
    label: str          # "Disabled", "Fast Attitude", ...
    is_bit: bool = False
```

### Parameter

```python
@dataclass
class Parameter:
    vehicle: str
    firmware_version: str
    name: str
    backend: str | None = None
    display_name: str | None = None
    description: str | None = None
    section: str | None = None
    units: str | None = None
    range_min: float | None = None
    range_max: float | None = None
    increment: float | None = None
    reboot_required: bool = False
    is_bitmask: bool = False
    read_only: bool = False
    advanced: bool = False
    source_url: str | None = None
    values: list[ParameterValue] = field(default_factory=list)
```

One parsed parameter, as produced by [scraper](scraper.md) and written by `upsert_parameter`.

### open_connection

```python
def open_connection(db_path=DEFAULT_DB_PATH) -> sqlite3.Connection
```

Opens a connection with foreign keys on and `sqlite3.Row` rows, creating the parent directory. The caller commits and
closes. Used by [`ParameterCatalog`](catalog.md), which holds one connection open.

### connect

```python
@contextmanager
def connect(db_path=DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]
```

Context manager around `open_connection`: commits on clean exit, always closes.

### init_schema

```python
def init_schema(db_path: Path = DEFAULT_DB_PATH) -> None
```

Runs `SCHEMA`. Idempotent.

### reset_vehicle

```python
def reset_vehicle(conn: sqlite3.Connection, vehicle: str) -> None
```

Deletes every `parameters` and `parameters_fts` row for `vehicle` (values cascade). Other vehicles are untouched.
`ingestions` history is kept.

### ingested_version

```python
def ingested_version(conn: sqlite3.Connection, vehicle: str) -> str | None
```

The firmware version stored for `vehicle`, or `None` if it has never been ingested.

### upsert_parameter

```python
def upsert_parameter(conn: sqlite3.Connection, param: Parameter, scraped_at: str) -> int
```

Replaces the row matching `(vehicle, name, backend)` (compared with `IS`, so `NULL` backends match), inserts its
values and FTS entry (`values_text` is `"value=label ..."`), and returns the new row id.

### record_ingestion

```python
def record_ingestion(conn: sqlite3.Connection, vehicle: str, firmware_version: str,
                     source_path: str, scraped_at: str, count: int) -> None
```

Appends one row to `ingestions` (`count` is stored as `param_count`).

## Usage examples

```python
from ardupilot_mcp import db

db.init_schema()
with db.connect() as conn:
    db.reset_vehicle(conn, "plane")
    db.upsert_parameter(conn, db.Parameter(vehicle="plane", firmware_version="4.8.0", name="RTL_ALTITUDE"),
                        scraped_at="2026-01-01T00:00:00+00:00")
```
