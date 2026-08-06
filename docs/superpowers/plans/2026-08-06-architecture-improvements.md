# ArduPilot MCP Architecture Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the four architecture-review candidates (C, A, B, D) grilled and confirmed for `ardupilot-mcp`: fix VectorStore's internal task-prefix leak and filter-string injection risk, collapse the six MCP tool wrappers into one `ParameterCatalog` seam, give the HTML scraper a golden-fixture test surface (fixing a real `reboot_required` gap along the way), and fill in the empty `scripts/refresh.py` stub.

**Architecture:** Order is C → A → B → D. C lands first as a standalone `vectors.py` cleanup so `ParameterCatalog` (A) is built on an already-clean `VectorStore`. B (scraper tests) and D (refresh script) are independent of A/C and of each other. The repo has zero tests today — Task 1 bootstraps pytest before anything else.

**Tech Stack:** Python 3.10+, pytest, sqlite3 (stdlib), lancedb 0.34, BeautifulSoup4/lxml, FastMCP (`mcp[cli]`), uv for dependency management.

---

## Task 1: Bootstrap test infrastructure

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest as a dev dependency**

Run: `cd /Users/che/Documents/Projects/ardupilot-mcp && uv add --dev pytest`

Expected: `pyproject.toml` gains a `[dependency-groups]` (or `[tool.uv] dev-dependencies`, depending on uv's current convention) entry containing `pytest`; `uv.lock` is updated.

- [ ] **Step 2: Add pytest config**

Add this section to `pyproject.toml` (anywhere after `[project]`, e.g. right before `[build-system]`):

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Verify pytest runs with zero tests**

Run: `uv run pytest`
Expected: exits with pytest's "no tests ran" status (exit code 5) and no import errors — confirms the `ardupilot_mcp` package and its dependencies (bs4, lancedb, mcp) are importable from the test environment.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pytest dev dependency and config"
```

---

## Task 2: vectors.py — split the internal task-prefix encoder (Candidate C, part 1)

**Files:**
- Modify: `src/ardupilot_mcp/vectors.py:118-125` (the `_default_encoder` method), and its two call sites at lines ~148 and ~194
- Test: `tests/test_vectors.py` (new file)

`_default_encoder(texts, task)` is private and only called from inside `VectorStore` (`rebuild()` passes `task="passage"`, `search()` passes `task="query"`). Splitting it into two dedicated methods removes a stringly-typed internal parameter and the typo risk it carries.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vectors.py`:

```python
"""Tests for the semantic search layer.

These tests never download the real e5 model: VectorStore.rebuild()/search()
already accept an `encoder` override for exactly this purpose, and the
internal _encode_passages/_encode_queries prefixing is tested by swapping in
a recording fake SentenceTransformer.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from ardupilot_mcp.vectors import EMBEDDING_DIM, VectorStore


class _RecordingModel:
    """Fake SentenceTransformer that records what it was asked to encode."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True):
        self.calls.append(list(texts))
        return np.zeros((len(texts), EMBEDDING_DIM), dtype="float32")


def _store(tmp_path) -> VectorStore:
    return VectorStore(
        path=tmp_path / "vectors.lance",
        model_cache_path=tmp_path / "model-cache",
    )


def test_encode_passages_adds_passage_prefix(tmp_path):
    store = _store(tmp_path)
    fake_model = _RecordingModel()
    store._model = fake_model  # bypass lazy real-model loading

    store._encode_passages(["RC_OPTIONS: RC options"])

    assert fake_model.calls == [["passage: RC_OPTIONS: RC options"]]


def test_encode_queries_adds_query_prefix(tmp_path):
    store = _store(tmp_path)
    fake_model = _RecordingModel()
    store._model = fake_model

    store._encode_queries(["why is my plane climbing"])

    assert fake_model.calls == [["query: why is my plane climbing"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vectors.py -v`
Expected: FAIL — `AttributeError: 'VectorStore' object has no attribute '_encode_passages'` (and same for `_encode_queries`).

- [ ] **Step 3: Replace `_default_encoder` with the two split methods**

In `src/ardupilot_mcp/vectors.py`, replace lines 118-125:

```python
    def _default_encoder(self, texts: list[str], task: str) -> list[list[float]]:
        """Encode with the e5 prefix appropriate for the task."""
        prefix = "query: " if task == "query" else "passage: "
        prefixed = [prefix + t for t in texts]
        arr = self.model.encode(
            prefixed, batch_size=64, show_progress_bar=False, convert_to_numpy=True
        )
        return [row.tolist() for row in arr]
```

with:

```python
    def _encode_passages(self, texts: list[str]) -> list[list[float]]:
        """Encode passages for indexing, with the e5 'passage:' prefix."""
        prefixed = ["passage: " + t for t in texts]
        arr = self.model.encode(
            prefixed, batch_size=64, show_progress_bar=False, convert_to_numpy=True
        )
        return [row.tolist() for row in arr]

    def _encode_queries(self, texts: list[str]) -> list[list[float]]:
        """Encode queries for search, with the e5 'query:' prefix."""
        prefixed = ["query: " + t for t in texts]
        arr = self.model.encode(
            prefixed, batch_size=64, show_progress_bar=False, convert_to_numpy=True
        )
        return [row.tolist() for row in arr]
```

- [ ] **Step 4: Update the two call sites**

In `rebuild()`, replace:

```python
        if encoder is None:
            vectors = self._default_encoder(texts, task="passage")
        else:
            vectors = encoder(texts)
```

with:

```python
        if encoder is None:
            vectors = self._encode_passages(texts)
        else:
            vectors = encoder(texts)
```

In `search()`, replace:

```python
        if encoder is None:
            qvec = self._default_encoder([query], task="query")[0]
        else:
            qvec = encoder([query])[0]
```

with:

```python
        if encoder is None:
            qvec = self._encode_queries([query])[0]
        else:
            qvec = encoder([query])[0]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_vectors.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/ardupilot_mcp/vectors.py tests/test_vectors.py
git commit -m "refactor: split VectorStore's _default_encoder into _encode_passages/_encode_queries"
```

---

## Task 3: vectors.py — parameterized LanceDB filter (Candidate C, part 2)

**Files:**
- Modify: `src/ardupilot_mcp/vectors.py:24-25` (imports), `:198-201` (the `where()` call in `search()`)
- Test: `tests/test_vectors.py` (append)

Replaces `q.where(f"firmware_version = '{firmware_version}'")` — raw string interpolation into a SQL-like filter — with LanceDB's typed `col()`/`lit()` expression API, confirmed present in the installed lancedb 0.34.0 (`lancedb.expr.col`, `lancedb.expr.lit`). Eliminates the injection-shaped risk at the root; no value ever touches a SQL string.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vectors.py`:

```python
def _identity_encoder(texts: list[str]) -> list[list[float]]:
    """Deterministic fake encoder: identical text -> identical vector."""
    vectors = []
    for t in texts:
        digest = hashlib.sha256(t.encode("utf-8")).digest()
        vectors.append([digest[i % len(digest)] / 255.0 for i in range(EMBEDDING_DIM)])
    return vectors


def test_rebuild_and_search_roundtrip(tmp_path):
    store = _store(tmp_path)
    rows = [
        {"param_id": 1, "name": "RC_OPTIONS", "vehicle": "plane",
         "firmware_version": "4.8.0", "text": "RC input options"},
        {"param_id": 2, "name": "LOG_BITMASK", "vehicle": "plane",
         "firmware_version": "4.8.0", "text": "Log bitmask control"},
        {"param_id": 3, "name": "RC_OPTIONS", "vehicle": "plane",
         "firmware_version": "4.6.3", "text": "RC input options"},
    ]

    n = store.rebuild(rows, encoder=_identity_encoder)
    assert n == 3

    hits = store.search(
        "RC input options", k=5, firmware_version="4.8.0", encoder=_identity_encoder
    )
    assert [h["param_id"] for h in hits] == [1]


def test_search_firmware_version_with_special_characters(tmp_path):
    store = _store(tmp_path)
    tricky_version = "4.8.0'; DROP TABLE parameters; --"
    rows = [
        {"param_id": 1, "name": "RC_OPTIONS", "vehicle": "plane",
         "firmware_version": tricky_version, "text": "RC input options"},
        {"param_id": 2, "name": "RC_OPTIONS", "vehicle": "plane",
         "firmware_version": "4.6.3", "text": "RC input options"},
    ]
    store.rebuild(rows, encoder=_identity_encoder)

    hits = store.search(
        "RC input options", k=5, firmware_version=tricky_version, encoder=_identity_encoder
    )

    assert [h["param_id"] for h in hits] == [1]
```

- [ ] **Step 2: Run tests to verify they fail (or misbehave)**

Run: `uv run pytest tests/test_vectors.py -v -k "roundtrip or special_characters"`
Expected: `test_search_firmware_version_with_special_characters` FAILs — the f-string filter produces a malformed LanceDB/SQL filter for a value containing `'`, either raising an error or matching zero/wrong rows. (`test_rebuild_and_search_roundtrip` may already pass since it uses plain version strings — that's fine, it becomes a regression guard.)

- [ ] **Step 3: Add the `lancedb.expr` import**

In `src/ardupilot_mcp/vectors.py`, after line 25 (`import pyarrow as pa`), add:

```python
from lancedb.expr import col, lit
```

- [ ] **Step 4: Replace the filter construction**

Replace:

```python
        q = table.search(qvec).limit(k)
        if firmware_version:
            # LanceDB uses SQL-style where clauses. Single quotes for strings.
            q = q.where(f"firmware_version = '{firmware_version}'")
        return q.to_list()
```

with:

```python
        q = table.search(qvec).limit(k)
        if firmware_version:
            q = q.where(col("firmware_version") == lit(firmware_version))
        return q.to_list()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_vectors.py -v`
Expected: PASS (4 tests total: the 2 prefix tests from Task 2, the 2 new ones)

- [ ] **Step 6: Commit**

```bash
git add src/ardupilot_mcp/vectors.py tests/test_vectors.py
git commit -m "fix: use lancedb col()/lit() instead of string-interpolated filter"
```

---

## Task 4: db.py — extract `open_connection()` (Candidate A, part 1)

**Files:**
- Modify: `src/ardupilot_mcp/db.py:115-130` (the `connect()` context manager)
- Test: `tests/test_db.py` (new file)

`ParameterCatalog` needs a connection it holds open for its lifetime, not one that closes after each call. `connect()`'s setup (Row factory, `PRAGMA foreign_keys`) needs to be shared, not duplicated. `open_connection()` becomes the raw primitive; `connect()` becomes a thin context-manager wrapper around it, so `ingest.py`'s existing usage is unaffected.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `AttributeError: module 'ardupilot_mcp.db' has no attribute 'open_connection'`

- [ ] **Step 3: Extract `open_connection()` and rebuild `connect()` on top of it**

In `src/ardupilot_mcp/db.py`, replace:

```python
@contextmanager
def connect(db_path=DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a connection with FKs on and Row row factory. Commits on clean exit.

    Accepts either a str or a Path.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
```

with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `uv run pytest -v`
Expected: PASS (all tests from Tasks 1-4)

- [ ] **Step 6: Commit**

```bash
git add src/ardupilot_mcp/db.py tests/test_db.py
git commit -m "refactor: extract db.open_connection() from connect()"
```

---

## Task 5: catalog.py — the ParameterCatalog module (Candidate A, part 2)

**Files:**
- Create: `src/ardupilot_mcp/catalog.py`
- Test: `tests/test_catalog.py` (new file)

The single seam through which a firmware version's parameters are looked up, keyword-searched, semantically searched, browsed, and diffed. Holds one persistent SQLite connection (safe: FastMCP runs sync tool calls on a single thread, run-to-completion, no interleaving mid-call) and one `VectorStore` (embedding model stays lazy). Methods mirror the six MCP tool names 1:1. Returns plain dicts — the shaping logic that was `server.py`'s `_row_to_param` moves here. Not-found stays `None`, matching today's contract.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ardupilot_mcp.catalog'`

- [ ] **Step 3: Create `src/ardupilot_mcp/catalog.py`**

```python
"""ParameterCatalog — the single seam through which a firmware version's
parameters are looked up, keyword-searched, semantically searched, browsed,
and diffed. See CONTEXT.md for the ParameterCatalog definition.

Holds one persistent SQLite connection for its process lifetime (safe under
FastMCP's single-threaded, run-to-completion sync tool calls — no locking
needed) and one VectorStore, whose embedding model still loads lazily on
first semantic_search call.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .db import DEFAULT_DB_PATH, list_versions as _list_versions_db, open_connection
from .vectors import DEFAULT_MODEL_CACHE_PATH, DEFAULT_VECTORS_PATH, VectorStore


class ParameterCatalog:
    """Read-side seam over SQLite parameter storage and the semantic VectorStore."""

    def __init__(
        self,
        db_path=DEFAULT_DB_PATH,
        vectors_path=DEFAULT_VECTORS_PATH,
        model_cache_path=DEFAULT_MODEL_CACHE_PATH,
    ) -> None:
        self._conn: sqlite3.Connection = open_connection(db_path)
        self._store = VectorStore(path=vectors_path, model_cache_path=model_cache_path)

    def close(self) -> None:
        """Close the held SQLite connection. The VectorStore's LanceDB handle
        and (if loaded) embedding model are released with the process."""
        self._conn.close()

    # -- internals -- #

    def _latest_version(self, vehicle: str) -> Optional[str]:
        versions = _list_versions_db(self._conn, vehicle)
        return versions[-1] if versions else None

    def _row_to_param(
        self, row: sqlite3.Row, include_values: bool = True
    ) -> dict[str, Any]:
        out = {
            "id": row["id"],
            "name": row["name"],
            "vehicle": row["vehicle"],
            "firmware_version": row["firmware_version"],
            "backend": row["backend"],
            "display_name": row["display_name"],
            "description": row["description"],
            "section": row["section"],
            "units": row["units"],
            "range": (
                {"min": row["range_min"], "max": row["range_max"]}
                if row["range_min"] is not None
                else None
            ),
            "increment": row["increment"],
            "is_bitmask": bool(row["is_bitmask"]),
            "read_only": bool(row["read_only"]),
            "advanced": bool(row["advanced"]),
            "source_url": row["source_url"],
        }
        if include_values:
            vals = self._conn.execute(
                """SELECT value, label, is_bit
                   FROM parameter_values
                   WHERE parameter_id = ?
                   ORDER BY id""",
                (row["id"],),
            ).fetchall()
            out["values"] = [
                {"value": v["value"], "label": v["label"], "is_bit": bool(v["is_bit"])}
                for v in vals
            ]
        return out

    # -- public interface -- #

    def list_versions(self, vehicle: str = "plane") -> list[str]:
        """Firmware versions ingested for a vehicle, ascending."""
        return _list_versions_db(self._conn, vehicle)

    def lookup_parameter(
        self,
        name: str,
        firmware_version: Optional[str] = None,
        vehicle: str = "plane",
    ) -> Optional[dict[str, Any]]:
        """Exact-name lookup. Omit firmware_version for the latest. None if not found."""
        if firmware_version is None:
            firmware_version = self._latest_version(vehicle)
            if firmware_version is None:
                return None
        row = self._conn.execute(
            """SELECT * FROM parameters
               WHERE vehicle = ? AND firmware_version = ? AND name = ?
               ORDER BY (backend IS NULL) DESC
               LIMIT 1""",
            (vehicle, firmware_version, name),
        ).fetchone()
        if row is None:
            return None
        param = self._row_to_param(row)

        variants = self._conn.execute(
            """SELECT backend FROM parameters
               WHERE vehicle = ? AND firmware_version = ? AND name = ?
                 AND backend IS NOT NULL
               ORDER BY backend""",
            (vehicle, firmware_version, name),
        ).fetchall()
        if variants:
            param["backend_variants"] = [v["backend"] for v in variants]
        return param

    def search_parameters(
        self,
        query: str,
        firmware_version: Optional[str] = None,
        limit: int = 10,
        vehicle: str = "plane",
    ) -> list[dict[str, Any]]:
        """FTS5 keyword search over name/description/section/enum labels."""
        fw_filter_sql = ""
        fw_params: tuple = ()
        if firmware_version is not None:
            fw_filter_sql = " AND p.firmware_version = ?"
            fw_params = (firmware_version,)

        rows = self._conn.execute(
            f"""SELECT p.*, snippet(parameters_fts, 2, '[', ']', ' ... ', 12) AS snippet
                FROM parameters_fts
                JOIN parameters p ON p.id = parameters_fts.rowid
                WHERE parameters_fts MATCH ?
                  AND p.vehicle = ?{fw_filter_sql}
                ORDER BY rank
                LIMIT ?""",
            (query, vehicle, *fw_params, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            p = self._row_to_param(r, include_values=False)
            p["snippet"] = r["snippet"]
            out.append(p)
        return out

    def semantic_search(
        self,
        query: str,
        k: int = 5,
        vehicle: str = "plane",
    ) -> list[dict[str, Any]]:
        """Vector search over the latest firmware version's descriptions."""
        fw = self._latest_version(vehicle)
        if fw is None:
            return []
        hits = self._store.search(query, k=k, firmware_version=fw)
        if not hits:
            return []
        ids = [h["param_id"] for h in hits]
        rows = {
            r["id"]: r
            for r in self._conn.execute(
                f"""SELECT * FROM parameters
                    WHERE id IN ({','.join('?' * len(ids))})""",
                ids,
            )
        }
        out: list[dict[str, Any]] = []
        for h in hits:
            r = rows.get(h["param_id"])
            if r is None:
                continue
            p = self._row_to_param(r, include_values=False)
            p["distance"] = float(h["_distance"])
            out.append(p)
        return out

    def list_parameters(
        self,
        prefix: Optional[str] = None,
        section: Optional[str] = None,
        firmware_version: Optional[str] = None,
        vehicle: str = "plane",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Browse by name prefix and/or section. Excludes backend variants."""
        if firmware_version is None:
            firmware_version = self._latest_version(vehicle)
            if firmware_version is None:
                return []

        where = ["vehicle = ?", "firmware_version = ?", "backend IS NULL"]
        params: list[Any] = [vehicle, firmware_version]
        if prefix:
            where.append("name LIKE ? ESCAPE '\\'")
            safe_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"{safe_prefix}%")
        if section:
            where.append("LOWER(section) = LOWER(?)")
            params.append(section)
        params.append(limit)

        rows = self._conn.execute(
            f"""SELECT * FROM parameters
                WHERE {' AND '.join(where)}
                ORDER BY name
                LIMIT ?""",
            params,
        ).fetchall()
        return [self._row_to_param(r, include_values=False) for r in rows]

    def diff_parameter(
        self,
        name: str,
        version_a: str,
        version_b: str,
        vehicle: str = "plane",
    ) -> dict[str, Any]:
        """Field-by-field diff of one parameter's main definition across two versions."""
        def _fetch(fw: str) -> Optional[dict[str, Any]]:
            row = self._conn.execute(
                """SELECT * FROM parameters
                   WHERE vehicle = ? AND firmware_version = ? AND name = ?
                     AND backend IS NULL
                   LIMIT 1""",
                (vehicle, fw, name),
            ).fetchone()
            return self._row_to_param(row) if row is not None else None

        a = _fetch(version_a)
        b = _fetch(version_b)

        result: dict[str, Any] = {
            "name": name,
            "version_a": version_a,
            "version_b": version_b,
            "exists_in_a": a is not None,
            "exists_in_b": b is not None,
            "differences": [],
        }
        if a is None or b is None:
            return result

        fields = ("description", "section", "units", "range", "increment",
                  "is_bitmask", "read_only", "advanced", "display_name")
        for f in fields:
            if a.get(f) != b.get(f):
                result["differences"].append({
                    "field": f,
                    "version_a": a.get(f),
                    "version_b": b.get(f),
                })

        def _val_tuples(p: dict) -> list[tuple]:
            return [(v["value"], v["label"], v["is_bit"]) for v in p.get("values", [])]

        if _val_tuples(a) != _val_tuples(b):
            result["differences"].append({
                "field": "values",
                "version_a": a.get("values"),
                "version_b": b.get("values"),
            })

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ardupilot_mcp/catalog.py tests/test_catalog.py
git commit -m "feat: add ParameterCatalog seam over SQLite + VectorStore"
```

---

## Task 6: server.py — thin tool wrappers over ParameterCatalog (Candidate A, part 3)

**Files:**
- Modify: `src/ardupilot_mcp/server.py` (full rewrite)
- Test: `tests/test_server.py` (new file)

The six `@mcp.tool` functions become pass-throughs to a lazily-constructed, module-level `ParameterCatalog` singleton — mirroring today's lazy `VectorStore` singleton pattern. Docstrings (the real interface for the LLM caller) are preserved verbatim.

- [ ] **Step 1: Write the failing test**

Create `tests/test_server.py`:

```python
"""Smoke test: server.py registers all six tools against a real FastMCP instance."""

from __future__ import annotations


def test_server_registers_all_six_tools():
    from ardupilot_mcp import server

    tool_names = {t.name for t in server.mcp._tool_manager.list_tools()}

    assert tool_names == {
        "list_versions",
        "lookup_parameter",
        "search_parameters",
        "semantic_search",
        "list_parameters",
        "diff_parameter",
    }
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS already (today's server.py registers the same six tools) — this test exists to catch the rewrite in Step 3 breaking registration, not to drive new behavior. Confirm it passes now before touching server.py.

- [ ] **Step 3: Rewrite `src/ardupilot_mcp/server.py`**

Replace the entire file with:

```python
"""FastMCP server exposing ArduPilot parameter Q&A over local SQLite + LanceDB.

Run manually (for testing):
    uv run python -m ardupilot_mcp.server

Wire into Claude Desktop by adding a stdio entry to your
claude_desktop_config.json — see the project README.

All queries are 100% local. The vector store loads its embedding model
lazily on the first semantic query; before that the process is very cheap
and startup is instant, which keeps Claude Desktop responsive.
"""

from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .catalog import ParameterCatalog


mcp = FastMCP("ardupilot-docs")

# Lazy catalog — the SQLite connection opens on first tool call; the
# semantic model loads even later, on first semantic_search call.
_catalog: Optional[ParameterCatalog] = None


def _get_catalog() -> ParameterCatalog:
    global _catalog
    if _catalog is None:
        _catalog = ParameterCatalog()
    return _catalog


# --------------------------------------------------------------------------- #
# Tools                                                                       #
# --------------------------------------------------------------------------- #

@mcp.tool()
def list_versions(vehicle: str = "plane") -> list[str]:
    """List firmware versions available in the local database.

    Call this first if you're unsure which versions are indexed. Currently
    only 'plane' is supported. Returns a list like ['4.6.3', '4.8.0'].
    """
    return _get_catalog().list_versions(vehicle)


@mcp.tool()
def lookup_parameter(
    name: str,
    firmware_version: Optional[str] = None,
    vehicle: str = "plane",
) -> dict[str, Any] | None:
    """Look up an ArduPilot parameter by exact name.

    Use this when the user references a specific parameter by name
    (e.g. "what does RC_OPTIONS do?", "valid values for LOG_BITMASK",
    "range of THR_MAX"). Names look like ALL_CAPS_WITH_UNDERSCORES.

    Returns the full definition including description, units, range,
    and any enum/bitmask values. Returns None if not found.

    Args:
        name: Exact parameter name, case-sensitive (e.g. "RC_OPTIONS").
        firmware_version: e.g. "4.8.0" or "4.6.3". Omit to use the latest.
        vehicle: "plane" (only supported vehicle for now).
    """
    return _get_catalog().lookup_parameter(name, firmware_version, vehicle)


@mcp.tool()
def search_parameters(
    query: str,
    firmware_version: Optional[str] = None,
    limit: int = 10,
    vehicle: str = "plane",
) -> list[dict[str, Any]]:
    """Keyword search over parameter names, descriptions, sections, and enum labels.

    Backed by SQLite FTS5. Best for exact-word queries or when you need to
    search a specific firmware version. Value labels are indexed too, so
    'Fast Attitude' will find LOG_BITMASK (which has that bit meaning).

    Query syntax follows FTS5: bare words are AND-ed; use double quotes for
    phrases ('"attitude locking"'); use * for prefix ('RTL*').

    Args:
        query: Search terms.
        firmware_version: Filter to a version. Omit to search all versions.
        limit: Maximum results (default 10).
        vehicle: "plane".
    """
    return _get_catalog().search_parameters(query, firmware_version, limit, vehicle)


@mcp.tool()
def semantic_search(
    query: str,
    k: int = 5,
    vehicle: str = "plane",
) -> list[dict[str, Any]]:
    """Semantic (vector) search over parameter descriptions.

    Use this for conceptual questions where the user is describing a symptom
    or behavior rather than naming a specific parameter — e.g. "why is my
    plane climbing too aggressively on RTL?", "how do I make landings
    smoother?", "параметри для стабілізації висоти".

    Multilingual — Ukrainian and English work equally well.
    Only searches the latest indexed firmware version (semantic index does
    not cover older versions; use search_parameters for those).

    Args:
        query: Natural-language question or description.
        k: Number of results to return (default 5).
        vehicle: "plane".
    """
    return _get_catalog().semantic_search(query, k, vehicle)


@mcp.tool()
def list_parameters(
    prefix: Optional[str] = None,
    section: Optional[str] = None,
    firmware_version: Optional[str] = None,
    vehicle: str = "plane",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Browse parameters by name prefix or section.

    Use this when the user asks to see a family of parameters, e.g.
    "list all RTL parameters", "what's in the AHRS group", "show me the
    ARSPD_ family".

    Args:
        prefix: Name prefix to match. "RTL" matches RTL_ALTITUDE, RTL_CLIMB_MIN, etc.
                Do not include a trailing underscore.
        section: Section name. Use list_sections() first if unsure. Case-insensitive.
        firmware_version: Version filter. Defaults to the latest indexed.
        vehicle: "plane".
        limit: Maximum results (default 50).
    """
    return _get_catalog().list_parameters(prefix, section, firmware_version, vehicle, limit)


@mcp.tool()
def diff_parameter(
    name: str,
    version_a: str,
    version_b: str,
    vehicle: str = "plane",
) -> dict[str, Any]:
    """Compare a parameter across two ArduPilot firmware versions.

    Reports field-by-field differences (description, range, units, values,
    bitmask bits) between the two versions. Useful for understanding what
    changed when upgrading firmware.

    Returns a dict with keys 'name', 'version_a', 'version_b', 'exists_in_a',
    'exists_in_b', and 'differences' (list of field-level diffs). If the
    parameter is missing in either version, 'differences' is empty and the
    exists_* flags convey that.

    Args:
        name: Parameter name (case-sensitive).
        version_a: e.g. "4.6.3".
        version_b: e.g. "4.8.0".
        vehicle: "plane".
    """
    return _get_catalog().diff_parameter(name, version_a, version_b, vehicle)


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #

def main() -> None:
    """stdio transport for Claude Desktop and similar MCP clients."""
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it still passes**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS — registration is unchanged, only the tool bodies moved into `ParameterCatalog`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (all tests from Tasks 1-6)

- [ ] **Step 6: Commit**

```bash
git add src/ardupilot_mcp/server.py tests/test_server.py
git commit -m "refactor: collapse server.py's six tool wrappers onto ParameterCatalog"
```

---

## Task 7: scraper.py — parse the reboot-required note (Candidate B, part 1)

**Files:**
- Modify: `src/ardupilot_mcp/scraper.py:72-106` (`_parse_parameter`), add a new `_has_reboot_required_flag` function mirroring `_has_advanced_flag` (currently at lines 113-119)
- Test: `tests/test_scraper.py` (new file, this task adds the first test to it — Tasks 8-9 append more)

Real gap found during the architecture review: `Parameter.reboot_required` exists on the dataclass but `scraper.py` never sets it, even though the HTML carries a "Note: Reboot required after change" line-block (visible on `BATT2_I2C_BUS` in both fixture files). Fixed here with the same pattern already proven correct for the advanced-flag case.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scraper.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: FAIL — `assert False is True` on `smbus.reboot_required is True` (the field is always `False` today).

- [ ] **Step 3: Add `_has_reboot_required_flag` and wire it in**

In `src/ardupilot_mcp/scraper.py`, after `_has_advanced_flag` (currently lines 113-119):

```python
def _has_advanced_flag(section: Tag) -> bool:
    """Detect the 'Note: This parameter is for advanced users' line-block."""
    for div in section.find_all("div", class_="line-block", recursive=False):
        em = div.find("em", string=re.compile("advanced users", re.I))
        if em is not None:
            return True
    return False
```

add:

```python
def _has_reboot_required_flag(section: Tag) -> bool:
    """Detect the 'Note: Reboot required after change' line-block."""
    for div in section.find_all("div", class_="line-block", recursive=False):
        em = div.find("em", string=re.compile("reboot required", re.I))
        if em is not None:
            return True
    return False
```

Then in `_parse_parameter`, replace:

```python
    param = Parameter(
        vehicle=vehicle,
        firmware_version=firmware_version,
        name=name,
        backend=backend,
        display_name=display or None,
        section=_find_section_name(section),
        source_url=source_url,
        advanced=_has_advanced_flag(section),
        description=_extract_description(section),
    )
```

with:

```python
    param = Parameter(
        vehicle=vehicle,
        firmware_version=firmware_version,
        name=name,
        backend=backend,
        display_name=display or None,
        section=_find_section_name(section),
        source_url=source_url,
        advanced=_has_advanced_flag(section),
        reboot_required=_has_reboot_required_flag(section),
        description=_extract_description(section),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add src/ardupilot_mcp/scraper.py tests/test_scraper.py
git commit -m "fix: parse 'Reboot required after change' into Parameter.reboot_required"
```

---

## Task 8: scraper.py — golden fixture tests (Candidate B, part 2)

**Files:**
- Test: `tests/test_scraper.py` (append)

Pins today's real ArduPilot doc parsing: exact parameter counts per fixture, and four more parameters covering distinct code paths (bitmask growth, identical-across-versions baseline, plain numeric range/units/increment, a cross-version rename). Any of these breaking means either the upstream doc changed or the parser regressed — both worth a human look.

- [ ] **Step 1: Write the tests**

Append to `tests/test_scraper.py`:

```python
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
```

- [ ] **Step 2: Run tests, expect PASS immediately**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: PASS (6 tests total, including the one from Task 7). These pin already-correct behavior — there's no implementation step because `parse_html_file` already handles all of this; the test IS the deliverable.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scraper.py
git commit -m "test: pin scraper.py behavior against real ArduPilot fixture files"
```

---

## Task 9: scraper.py — synthetic edge-case tests (Candidate B, part 3)

**Files:**
- Test: `tests/test_scraper.py` (append)

Pins the regex/branch rules themselves (`_HEADING_RE`, `_RANGE_RE`, backend capture, advanced-flag detection) using small synthetic HTML, independent of whether the current real docs happen to exercise each branch.

- [ ] **Step 1: Write the tests**

Append to `tests/test_scraper.py`:

```python
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
```

- [ ] **Step 2: Run tests, expect PASS immediately**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: PASS (11 tests total). Like Task 8, these pin already-correct behavior — the test is the deliverable.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (all tests from Tasks 1-9)

- [ ] **Step 4: Commit**

```bash
git add tests/test_scraper.py
git commit -m "test: pin scraper.py regex/branch edge cases with synthetic HTML"
```

---

## Task 10: scripts/refresh.py — fill in the empty stub (Candidate D)

**Files:**
- Modify: `scripts/refresh.py` (currently 0 bytes)
- Test: `tests/test_refresh.py` (new file)

A one-shot "bring my local data up to date" script: scans `data/ardupilot-docs/` for known-format HTML files, ingests every one found, then rebuilds the semantic index for each vehicle's latest version. Zero arguments — `ingest.py`'s CLI already covers the flexible per-file path.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_refresh.py`:

```python
"""Tests for scripts/refresh.py.

Loaded via importlib rather than sys.path manipulation since scripts/ isn't
part of the installed ardupilot_mcp package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "refresh.py"


def _load_refresh_module():
    spec = importlib.util.spec_from_file_location("refresh", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def refresh():
    return _load_refresh_module()


def test_discover_pairs_parses_known_filenames(refresh, tmp_path):
    (tmp_path / "Complete Parameter List — Plane documentation 4.8.0.html").write_text("")
    (tmp_path / "Complete Parameter List — Copter documentation 4.5.0.html").write_text("")

    pairs = refresh.discover_pairs(tmp_path)

    assert sorted((vehicle, fw) for vehicle, fw, _ in pairs) == [
        ("copter", "4.5.0"),
        ("plane", "4.8.0"),
    ]


def test_discover_pairs_skips_unrecognized_files(refresh, tmp_path, capsys):
    (tmp_path / "Complete Parameter List — Plane documentation 4.8.0.html").write_text("")
    (tmp_path / "notes.txt").write_text("irrelevant")

    pairs = refresh.discover_pairs(tmp_path)

    assert [(vehicle, fw) for vehicle, fw, _ in pairs] == [("plane", "4.8.0")]
    assert "skipping unrecognized file: notes.txt" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_refresh.py -v`
Expected: FAIL — `scripts/refresh.py` is empty, so `spec.loader.exec_module(module)` succeeds but `refresh.discover_pairs` doesn't exist: `AttributeError: module 'refresh' has no attribute 'discover_pairs'`.

- [ ] **Step 3: Write `scripts/refresh.py`**

```python
"""One-shot refresh: ingest every ArduPilot parameter HTML file found in
data/ardupilot-docs/, then rebuild the semantic index for each vehicle's
latest version.

Run manually:
    uv run python scripts/refresh.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from ardupilot_mcp.ingest import ingest
from ardupilot_mcp.vectors import DEFAULT_VECTORS_PATH, VectorStore, rebuild_from_db

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "ardupilot-docs"

_FILENAME_RE = re.compile(
    r"Complete Parameter List — (\w+) documentation ([\d.]+)\.html"
)


def discover_pairs(data_dir: Path = DATA_DIR) -> list[tuple[str, str, Path]]:
    """Scan data_dir for (vehicle, firmware_version, html_path) triples.

    Files that don't match the expected naming convention are skipped with
    a stderr warning rather than aborting the whole refresh.
    """
    pairs: list[tuple[str, str, Path]] = []
    for html_path in sorted(data_dir.glob("*.html")):
        m = _FILENAME_RE.search(html_path.name)
        if m is None:
            print(f"[refresh] skipping unrecognized file: {html_path.name}",
                  file=sys.stderr)
            continue
        vehicle = m.group(1).lower()
        firmware_version = m.group(2)
        pairs.append((vehicle, firmware_version, html_path))
    return pairs


def main() -> int:
    pairs = discover_pairs()
    if not pairs:
        print(f"[refresh] no recognized HTML files found in {DATA_DIR}", file=sys.stderr)
        return 1

    latest_by_vehicle: dict[str, str] = {}
    for vehicle, firmware_version, html_path in pairs:
        ingest(
            html_path=html_path,
            vehicle=vehicle,
            firmware_version=firmware_version,
            source_url=None,
            verbose=True,
        )
        current = latest_by_vehicle.get(vehicle)
        if current is None or firmware_version > current:
            latest_by_vehicle[vehicle] = firmware_version

    for vehicle, firmware_version in latest_by_vehicle.items():
        store = VectorStore(path=DEFAULT_VECTORS_PATH)
        rebuild_from_db(store, vehicle=vehicle, firmware_version=firmware_version, verbose=True)

    print(
        f"[refresh] done — {len(pairs)} file(s) ingested, "
        f"{len(latest_by_vehicle)} vector index(es) rebuilt",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_refresh.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (all tests from Tasks 1-10)

- [ ] **Step 6: Commit**

```bash
git add scripts/refresh.py tests/test_refresh.py
git commit -m "feat: fill in scripts/refresh.py — scan and ingest all known HTML files"
```

---

## Self-Review

**Spec coverage:**
- Candidate C (encode split + parameterized filter): Tasks 2-3. ✅
- Candidate A (ParameterCatalog): Tasks 4-6 (db.py refactor, catalog.py, server.py rewrite). ✅
- Candidate B (scraper tests + reboot_required fix): Tasks 7-9. ✅
- Candidate D (scripts/refresh.py): Task 10. ✅
- Test infrastructure bootstrap (repo had zero tests): Task 1. ✅

**Placeholder scan:** No TBD/TODO/"add appropriate handling" markers — every step has complete code or an exact command with expected output.

**Type consistency:** `ParameterCatalog` method names and signatures in Task 5 match what Task 6's `server.py` calls exactly (`list_versions(vehicle)`, `lookup_parameter(name, firmware_version, vehicle)`, `search_parameters(query, firmware_version, limit, vehicle)`, `semantic_search(query, k, vehicle)`, `list_parameters(prefix, section, firmware_version, vehicle, limit)`, `diff_parameter(name, version_a, version_b, vehicle)`). `db.open_connection` (Task 4) is the exact name `catalog.py` (Task 5) imports. `VectorStore._encode_passages`/`_encode_queries` (Task 2) are the exact names Task 3's filter fix leaves untouched. `refresh.discover_pairs` (Task 10) matches what `tests/test_refresh.py` calls.
