# ingest

Ingest pipeline and the `ardupilot-refresh` CLI: get a parameters page, load it into SQLite, optionally rebuild the
semantic index.

## Overview

Three steps, each its own function: `fetch_page` (URL) or `read_page` (saved file) produces a `Page`; `load` writes it
to SQLite; `rebuild_vectors` refreshes the semantic index once for every vehicle loaded. `ingest_all` and `main`
compose them.

Re-ingesting a vehicle replaces its rows wholesale, whatever the firmware version
([ADR 0001](../adr/0001-single-firmware-version-per-vehicle.md)). Other vehicles are untouched.

## Public API

### Page

```python
class Page(NamedTuple):
    html: str
    vehicle: str
    firmware_version: str
    source_url: str | None
    source_path: Path
```

One vehicle's parameter page, ready to load. `source_path` is the HTML on disk (the archive copy for a fetched page)
and is recorded in the `ingestions` table.

### VehicleIngestOutcome

```python
class VehicleIngestOutcome(NamedTuple):
    vehicle: str
    success: bool
    count: int | None = None
    firmware_version: str | None = None
    error: str | None = None
```

One vehicle's result within `ingest_all`. On failure `error` is set and `count`/`firmware_version` are `None`.

### fetch_page

```python
def fetch_page(url: str, vehicle: str | None = None, firmware_version: str | None = None,
               source_url: str | None = None, vehicle_names: Iterable[str] | None = None,
               archive_dir: Path = DEFAULT_ARCHIVE_DIR, http_client: httpx.Client | None = None,
               verbose: bool = False) -> Page
```

Downloads `url`, detects the vehicle from the URL (bounded by `vehicle_names`, default the Roster's keys) and the
firmware version from the page text, unless overridden. Saves the HTML to
`archive_dir/Complete Parameter List — <Vehicle> documentation <version>.html` (default `data/ardupilot-docs/`).
Raises `RuntimeError` if the fetch fails, `ValueError` if vehicle or version can't be detected.

### read_page

```python
def read_page(html_path: Path, vehicle: str, firmware_version: str, source_url: str | None = None) -> Page
```

Reads a saved page. Vehicle and version are required — nothing is detected. Raises `FileNotFoundError`.

### load

```python
def load(page: Page, db_path: Path = DEFAULT_DB_PATH, verbose: bool = False) -> int
```

Parses `page` and replaces its vehicle's rows in one transaction, then records an `ingestions` row. Does not touch
the semantic index. Returns the number of parameters loaded.

### rebuild_vectors

```python
def rebuild_vectors(vehicles: list[str], db_path: Path = DEFAULT_DB_PATH,
                    vectors_path: Path | None = None, verbose: bool = False) -> None
```

Rebuilds the semantic index for each of `vehicles` from SQLite with a single `VectorStore`, so the embedding model
loads once. Each vehicle must already be loaded (otherwise `ValueError` from
[`rebuild_from_db`](vectors.md#rebuild_from_db)). An empty list is a no-op.

### ingest_all

```python
def ingest_all(vehicles: list[str] | None = None, vehicles_config: Path | None = None,
               db_path: Path = DEFAULT_DB_PATH, build_vectors: bool = False,
               vectors_path: Path | None = None, archive_dir: Path = DEFAULT_ARCHIVE_DIR,
               http_client: httpx.Client | None = None, verbose: bool = False) -> list[VehicleIngestOutcome]
```

Fetches and loads several Roster vehicles. `vehicles=None` means every enabled vehicle (`--all`); a list means exactly
those, enabled or not (`--roster`), in the given order with duplicates collapsed. Unknown names raise `ValueError`
before any fetch. A vehicle that fails with `ValueError`, `RuntimeError` or `FileNotFoundError` is recorded and the
run continues. With `build_vectors=True`, vectors are rebuilt once at the end for every vehicle that succeeded.

### main

```python
def main(argv: list[str] | None = None) -> int
```

Console-script entry point (`ardupilot-refresh`). Returns 0 on success, 1 if any vehicle failed or on an
argument/IO error (printed as a one-line `error:` message rather than a traceback).

| Flag | Meaning |
|---|---|
| `--html PATH` / `--url URL` / `--all` / `--roster NAME...` | Source; exactly one is required. |
| `--vehicle` | Required with `--html`; auto-detected from `--url`. |
| `--firmware-version` | Required with `--html`; auto-detected from the page with `--url`. |
| `--source-url` | Canonical URL to record; defaults to `--url`. |
| `--db PATH` | SQLite path (default `data/ardupilot.db`). |
| `--build-vectors` | Also rebuild the semantic index for the ingested vehicle(s). |
| `--vectors-path PATH` | LanceDB directory (default `data/vectors.lance`). |
| `--vehicles-config PATH` | Roster file (default `data/vehicles.json` if present, else packaged). |
| `-q`, `--quiet` | Suppress progress output on stderr. |

`--vehicle`, `--firmware-version` and `--source-url` are rejected with `--all`/`--roster`.

## Usage examples

```bash
uv run ardupilot-refresh --all --build-vectors
uv run ardupilot-refresh --roster plane copter --build-vectors
uv run ardupilot-refresh --url https://ardupilot.org/copter/docs/parameters.html
uv run ardupilot-refresh --html saved.html --vehicle plane --firmware-version 4.8.0
```

```python
from ardupilot_mcp.ingest import ingest_all

for o in ingest_all(vehicles=["plane"], build_vectors=True):
    print(o.vehicle, o.success, o.count or o.error)
```

## Dependencies

- [fetch](fetch.md), [scraper](scraper.md), [db](db.md), [roster](roster.md); [vectors](vectors.md) imported lazily,
  only when vectors are rebuilt.
