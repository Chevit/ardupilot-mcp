# Direct URL Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `ardupilot-refresh` (`ingest.py`) fetch an ArduPilot parameters
page directly from a URL (e.g. `https://ardupilot.org/copter/docs/parameters.html`),
auto-detecting vehicle from the URL and firmware version from the page
text, instead of requiring a manual download-and-flag-matching step.

**Architecture:** New `fetch.py` module owns network I/O (`fetch_url`) and
URL-based vehicle detection (`detect_vehicle_from_url`). `scraper.py` gains
one pure-text helper, `detect_version`, and its existing `parse_html_file`
is split into a thin file-reading wrapper plus a shared `parse_html(html, ...)`
core so both the local-file path and the new URL path parse identically.
`ingest.py`'s `ingest()` grows a `url` parameter that fetches, auto-detects,
archives to `data/ardupilot-docs/` (matching the filename convention
`scripts/refresh.py` already expects), then falls through to the existing
parse/DB/vector pipeline unchanged. The CLI's `--html`/`--url` become a
required mutually exclusive pair; `--vehicle`/`--firmware-version` become
optional (still required in practice for `--html`, auto-detected for `--url`).

**Tech Stack:** Python 3.10+, `httpx` (already a dependency, used via
`httpx.Client` + `httpx.MockTransport` in tests — no new dependency),
`pytest`.

Spec: `docs/superpowers/specs/2026-08-06-url-ingest-design.md`

---

## Tasks

### Task 1: `fetch.py` — detect vehicle from URL

**Files:**

- Create: `src/ardupilot_mcp/fetch.py`
- Test: `tests/test_fetch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetch.py`:

```python
"""Tests for network fetch + URL-based auto-detection (fetch.py).

No real network calls — fetch_url is tested against httpx.MockTransport.
"""

from __future__ import annotations

import httpx
import pytest

from ardupilot_mcp.fetch import detect_vehicle_from_url, fetch_url


@pytest.mark.parametrize("url,expected", [
    ("https://ardupilot.org/copter/docs/parameters.html", "copter"),
    ("https://ardupilot.org/plane/docs/parameters.html", "plane"),
    ("https://ardupilot.org/rover/docs/parameters.html", "rover"),
    ("https://ardupilot.org/sub/docs/parameters.html", "sub"),
    ("https://ardupilot.org/docs/some-other-page.html", None),
    ("https://example.com/totally-unrelated.html", None),
])
def test_detect_vehicle_from_url(url, expected):
    assert detect_vehicle_from_url(url) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ardupilot_mcp.fetch'`

- [ ] **Step 3: Write minimal implementation**

Create `src/ardupilot_mcp/fetch.py`:

```python
"""Fetch ArduPilot parameter reference pages directly from ardupilot.org.

Complements scraper.py's local-file parsing: this module owns network I/O
(`fetch_url`) and the URL-shape heuristic (`detect_vehicle_from_url`) that
let ingest.py skip the manual "download the page, guess the flags" step.
"""

from __future__ import annotations

import re
from typing import Optional

import httpx

# "https://ardupilot.org/copter/docs/parameters.html" -> "copter"
_VEHICLE_URL_RE = re.compile(r"/(plane|copter|rover|sub)/docs/parameters")


def detect_vehicle_from_url(url: str) -> Optional[str]:
    """Extract the vehicle segment from an ardupilot.org parameters URL.

    Returns None if the URL doesn't match the expected
    "/<vehicle>/docs/parameters..." shape.
    """
    m = _VEHICLE_URL_RE.search(url)
    return m.group(1) if m else None


def fetch_url(url: str, client: Optional[httpx.Client] = None) -> str:
    """Download `url` and return its body as text.

    Raises RuntimeError on any network failure or non-2xx response — callers
    don't need httpx's exception hierarchy, just "it failed, here's why."

    `client` is injectable for tests (pass an httpx.Client wired to an
    httpx.MockTransport). When omitted, a short-lived client is created and
    closed around this one request.
    """
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"failed to fetch {url}: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    return response.text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ardupilot_mcp/fetch.py tests/test_fetch.py
git commit -m "feat: add fetch.py with vehicle-from-URL detection"
```

---

### Task 2: `fetch.py` — `fetch_url` network behavior

**Files:**

- Modify: `tests/test_fetch.py`

`fetch_url` was implemented in Task 1; this task adds the tests that pin its
mocked-network behavior (success and failure) so the implementation is
actually verified, not just imported.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetch.py`:

```python
def test_fetch_url_returns_body_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/parameters.html"
        return httpx.Response(200, text="<html>ok</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_url("https://example.test/parameters.html", client=client) == "<html>ok</html>"


def test_fetch_url_raises_runtime_error_on_http_status_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="failed to fetch"):
        fetch_url("https://example.test/missing.html", client=client)


def test_fetch_url_raises_runtime_error_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="failed to fetch"):
        fetch_url("https://example.test/unreachable.html", client=client)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: at this point the implementation from Task 1 already satisfies
these — if any of the three new tests FAIL, the Task 1 implementation has a
bug; fix `fetch_url` in `src/ardupilot_mcp/fetch.py` before proceeding.

- [ ] **Step 3: Confirm implementation (no change expected)**

`fetch_url` from Task 1 already wraps `client.get()` in `try/except
httpx.HTTPError` and calls `raise_for_status()`, which covers both the
4xx/5xx case (`HTTPStatusError`, a subclass of `HTTPError`) and the
transport-failure case (`ConnectError`, also a subclass of `HTTPError`). No
code change needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/test_fetch.py
git commit -m "test: pin fetch_url success/failure behavior against MockTransport"
```

---

### Task 3: `scraper.py` — `detect_version`

**Files:**

- Modify: `src/ardupilot_mcp/scraper.py:21-38` (imports/regexes)
- Modify: `src/ardupilot_mcp/scraper.py:41-54` (`parse_html_file`)
- Modify: `tests/test_scraper.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scraper.py`, after the existing imports (line 16):

```python
from ardupilot_mcp.scraper import detect_version, parse_html_file
```

(replaces the current `from ardupilot_mcp.scraper import parse_html_file`
import on that line)

Then append these tests to the file:

```python
def test_detect_version_finds_v_pattern():
    html = "<h2>Full Parameter List of Plane latest V4.8.0 dev</h2>"
    assert detect_version(html) == "4.8.0"


def test_detect_version_returns_none_when_absent():
    assert detect_version("<h2>Some unrelated page</h2>") is None


def test_detect_version_real_fixture(params_480):
    # params_480 fixture already parses FIXTURE_480; re-read the raw text
    # directly to confirm detect_version agrees with the version the
    # fixture was ingested under.
    html = FIXTURE_480.read_text(encoding="utf-8")
    assert detect_version(html) == "4.8.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scraper.py -v -k detect_version`
Expected: FAIL with `ImportError: cannot import name 'detect_version'`

- [ ] **Step 3: Write minimal implementation**

In `src/ardupilot_mcp/scraper.py`, add below the existing `_RANGE_RE`
definition (after line 38):

```python
# "Full Parameter List of Plane latest V4.8.0 dev" -> "4.8.0"
_VERSION_RE = re.compile(r"\bV(\d+\.\d+\.\d+)\b")


def detect_version(html: str) -> Optional[str]:
    """Extract the firmware version ArduPilot's doc generator stamped on
    the page (e.g. "...latest V4.8.0 dev" -> "4.8.0").

    Returns None if no version-shaped token is found.
    """
    m = _VERSION_RE.search(html)
    return m.group(1) if m else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scraper.py -v -k detect_version`
Expected: PASS (3 passed) — the third test requires `FIXTURE_480` to exist
on disk (`data/ardupilot-docs/Complete Parameter List — Plane documentation
4.8.0.html`); if that fixture is missing in your checkout (per CLAUDE.md,
`data/` is gitignored), this one test will error on the fixture, not on
`detect_version` — that's a pre-existing environment gap, not a regression.

- [ ] **Step 5: Commit**

```bash
git add src/ardupilot_mcp/scraper.py tests/test_scraper.py
git commit -m "feat: add scraper.detect_version for page-text version detection"
```

---

### Task 4: `scraper.py` — split `parse_html_file` into file-read + `parse_html` core

**Files:**

- Modify: `src/ardupilot_mcp/scraper.py:41-54`

This is a pure refactor — behavior must not change. No new test; the
existing golden tests in `tests/test_scraper.py` (`test_pinned_parameter_count_*`,
etc.) are the regression check.

- [ ] **Step 1: Run existing tests to record the current baseline**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: note the pass/fail count (some may already fail/error if
`data/ardupilot-docs/` fixtures are absent in this checkout — that's fine,
just confirm the count doesn't get worse after this task).

- [ ] **Step 2: Replace `parse_html_file`**

In `src/ardupilot_mcp/scraper.py`, replace lines 41-54:

```python
def parse_html_file(
    path: Path,
    vehicle: str,
    firmware_version: str,
    source_url: Optional[str] = None,
) -> list[Parameter]:
    """Parse a Sphinx-generated ArduPilot parameters HTML page.

    Every returned Parameter is tagged with the given vehicle and
    firmware_version so it can be stored alongside other versions.
    """
    html = Path(path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    return list(_iter_parameters(soup, vehicle, firmware_version, source_url))
```

with:

```python
def parse_html_file(
    path: Path,
    vehicle: str,
    firmware_version: str,
    source_url: Optional[str] = None,
) -> list[Parameter]:
    """Read `path` and parse it as a Sphinx-generated ArduPilot parameters page.

    Thin wrapper around `parse_html` for the local-file case; see that
    function for the actual parsing behavior.
    """
    html = Path(path).read_text(encoding="utf-8")
    return parse_html(html, vehicle, firmware_version, source_url)


def parse_html(
    html: str,
    vehicle: str,
    firmware_version: str,
    source_url: Optional[str] = None,
) -> list[Parameter]:
    """Parse a Sphinx-generated ArduPilot parameters HTML page from a string.

    Every returned Parameter is tagged with the given vehicle and
    firmware_version so it can be stored alongside other versions. This is
    the shared core used by both `parse_html_file` (local file) and
    ingest.py's URL path (already-fetched text, no file needed).
    """
    soup = BeautifulSoup(html, "lxml")
    return list(_iter_parameters(soup, vehicle, firmware_version, source_url))
```

- [ ] **Step 3: Run tests to confirm behavior is unchanged**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: same pass/fail count as Step 1 — no new failures introduced by the
refactor.

- [ ] **Step 4: Commit**

```bash
git add src/ardupilot_mcp/scraper.py
git commit -m "refactor: split parse_html_file into file-read wrapper + parse_html core"
```

---

### Task 5: `ingest.py` — URL-based ingest path

**Files:**

- Modify: `src/ardupilot_mcp/ingest.py:1-96`
- Test: `tests/test_ingest.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest.py`:

```python
"""Tests for ingest.py's URL-based ingest path.

No real network calls — the URL path is exercised against an
httpx.MockTransport-backed client injected via ingest()'s http_client param.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ardupilot_mcp.ingest import ingest

_FIXTURE_HTML = """
<html><body>
<h2>Full Parameter List of Copter latest V4.9.0 dev</h2>
<section>
  <h3>FOO_BAR: A test parameter\u00b6</h3>
  <p>Description.</p>
</section>
</body></html>
"""


def _mock_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_FIXTURE_HTML)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ingest_from_url_auto_detects_and_archives(tmp_path):
    db_path = tmp_path / "test.db"
    archive_dir = tmp_path / "ardupilot-docs"

    result = ingest(
        url="https://ardupilot.org/copter/docs/parameters.html",
        db_path=db_path,
        archive_dir=archive_dir,
        http_client=_mock_client(),
        verbose=False,
    )

    assert result.count == 1
    assert result.vehicle == "copter"
    assert result.firmware_version == "4.9.0"

    archived = archive_dir / "Complete Parameter List — Copter documentation 4.9.0.html"
    assert archived.exists()
    assert "FOO_BAR" in archived.read_text(encoding="utf-8")


def test_ingest_from_url_respects_explicit_overrides(tmp_path):
    db_path = tmp_path / "test.db"
    archive_dir = tmp_path / "ardupilot-docs"

    result = ingest(
        url="https://ardupilot.org/copter/docs/parameters.html",
        vehicle="copter",
        firmware_version="9.9.9-override",
        db_path=db_path,
        archive_dir=archive_dir,
        http_client=_mock_client(),
        verbose=False,
    )

    assert result.firmware_version == "9.9.9-override"
    archived = archive_dir / "Complete Parameter List — Copter documentation 9.9.9-override.html"
    assert archived.exists()


def test_ingest_rejects_both_html_and_url(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        ingest(html_path=tmp_path / "x.html", url="https://example.test/parameters.html")


def test_ingest_rejects_neither_html_nor_url():
    with pytest.raises(ValueError, match="exactly one"):
        ingest()


def test_ingest_html_path_still_requires_vehicle_and_version(tmp_path):
    html_path = tmp_path / "some.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="--vehicle and --firmware-version"):
        ingest(html_path=html_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: FAIL — `TypeError: ingest() got an unexpected keyword argument 'url'`

- [ ] **Step 3: Rewrite `ingest()` in `src/ardupilot_mcp/ingest.py`**

Replace lines 1-96 (module docstring through the end of `ingest()`) with:

```python
"""Ingest pipeline: parse an ArduPilot HTML page and load rows into SQLite.

Ingest is scoped to a single (vehicle, firmware_version) pair. Re-running
against the same pair replaces those rows atomically; other versions are
left untouched, so you can hold multiple firmware versions side by side.

Two ways to provide the source page — pass exactly one:

    # from a page already downloaded to disk
    uv run python -m ardupilot_mcp.ingest \\
        --html "D:/Downloads/Ardu/Complete Parameter List — Plane documentation 4.8.0.html" \\
        --vehicle plane \\
        --firmware-version 4.8.0 \\
        --source-url https://ardupilot.org/plane/docs/parameters.html

    # fetched directly — vehicle and firmware version auto-detected
    uv run python -m ardupilot_mcp.ingest \\
        --url https://ardupilot.org/copter/docs/parameters.html
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

import httpx

from .db import (
    DEFAULT_DB_PATH,
    connect,
    init_schema,
    record_ingestion,
    reset_vehicle_version,
    upsert_parameter,
)
from .fetch import detect_vehicle_from_url, fetch_url
from .scraper import detect_version, parse_html_file

DEFAULT_ARCHIVE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "ardupilot-docs"
)


class IngestResult(NamedTuple):
    """What ingest() actually did — count plus the resolved vehicle/version.

    Resolution matters for the --url path: vehicle/firmware_version may have
    been auto-detected rather than passed in, so callers (the CLI) need a
    way to find out what was actually ingested.
    """
    count: int
    vehicle: str
    firmware_version: str


def _fetch_and_archive(
    url: str,
    vehicle: Optional[str],
    firmware_version: Optional[str],
    source_url: Optional[str],
    archive_dir: Path,
    http_client: Optional[httpx.Client],
    verbose: bool,
) -> tuple[Path, str, str, str]:
    """Fetch `url`, auto-detect vehicle/version, archive HTML to disk.

    Returns (archived_html_path, vehicle, firmware_version, source_url) —
    everything `ingest()` needs to fall through to the shared parse step.
    """
    if verbose:
        print(f"[fetch] downloading {url}", file=sys.stderr)
    html = fetch_url(url, client=http_client)

    vehicle = vehicle or detect_vehicle_from_url(url)
    if vehicle is None:
        raise ValueError(
            f"could not detect vehicle from URL {url!r}; pass --vehicle explicitly"
        )

    firmware_version = firmware_version or detect_version(html)
    if firmware_version is None:
        raise ValueError(
            "could not detect firmware version from page; "
            "pass --firmware-version explicitly"
        )

    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_name = (
        f"Complete Parameter List — {vehicle.capitalize()} documentation "
        f"{firmware_version}.html"
    )
    archive_path = archive_dir / archive_name
    archive_path.write_text(html, encoding="utf-8")
    if verbose:
        print(f"[fetch] archived -> {archive_path}", file=sys.stderr)

    return archive_path, vehicle, firmware_version, (source_url or url)


def ingest(
    html_path: Optional[Path] = None,
    url: Optional[str] = None,
    vehicle: Optional[str] = None,
    firmware_version: Optional[str] = None,
    source_url: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
    build_vectors: bool = False,
    vectors_path: Optional[Path] = None,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    http_client: Optional[httpx.Client] = None,
    verbose: bool = False,
) -> IngestResult:
    """Get the HTML (from disk or a URL) and write every parameter into the DB.

    Pass exactly one of `html_path` or `url`. With `html_path`, `vehicle`
    and `firmware_version` are required. With `url`, both are optional —
    vehicle is auto-detected from the URL path and firmware_version from
    the page text; either can still be passed explicitly to override
    detection.

    Returns an IngestResult(count, vehicle, firmware_version) — the count of
    parameters loaded, plus whatever vehicle/firmware_version were actually
    used (useful when they were auto-detected rather than passed in).

    Existing DB rows for (vehicle, firmware_version) are replaced atomically
    inside a single transaction; other versions remain intact.

    If `build_vectors=True`, also rebuilds the semantic index for this
    (vehicle, firmware_version) after ingest completes.
    """
    if (html_path is None) == (url is None):
        raise ValueError("pass exactly one of html_path or url")

    if url is not None:
        html_path, vehicle, firmware_version, source_url = _fetch_and_archive(
            url=url,
            vehicle=vehicle,
            firmware_version=firmware_version,
            source_url=source_url,
            archive_dir=archive_dir,
            http_client=http_client,
            verbose=verbose,
        )
    else:
        if vehicle is None or firmware_version is None:
            raise ValueError(
                "--vehicle and --firmware-version are required when using --html"
            )
        html_path = Path(html_path).resolve()
        if not html_path.exists():
            raise FileNotFoundError(html_path)

    if verbose:
        print(f"[scrape] {vehicle} {firmware_version}: parsing {Path(html_path).name}",
              file=sys.stderr)
    params = parse_html_file(
        html_path,
        vehicle=vehicle,
        firmware_version=firmware_version,
        source_url=source_url,
    )
    if verbose:
        print(f"[scrape] got {len(params)} parameters", file=sys.stderr)

    init_schema(db_path)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with connect(db_path) as conn:
        reset_vehicle_version(conn, vehicle, firmware_version)
        for p in params:
            upsert_parameter(conn, p, scraped_at)
        record_ingestion(
            conn, vehicle, firmware_version, str(html_path), scraped_at, len(params),
        )

    if verbose:
        print(f"[db] wrote {len(params)} rows -> {db_path}", file=sys.stderr)

    if build_vectors:
        # Imported lazily so users who never enable vectors don't pay the
        # sentence-transformers / torch import cost.
        from .vectors import VectorStore, rebuild_from_db, DEFAULT_VECTORS_PATH
        store = VectorStore(path=vectors_path or DEFAULT_VECTORS_PATH)
        rebuild_from_db(
            store,
            db_path=db_path,
            vehicle=vehicle,
            firmware_version=firmware_version,
            verbose=verbose,
        )

    return IngestResult(len(params), vehicle, firmware_version)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ardupilot_mcp/ingest.py tests/test_ingest.py
git commit -m "feat: add URL-based ingest path with vehicle/version auto-detection"
```

---

### Task 6: `ingest.py` CLI — `--url` flag, optional `--vehicle`/`--firmware-version`

**Files:**

- Modify: `src/ardupilot_mcp/ingest.py` (`main()`, now around line 168 after Task 5's insertions — search for `def main(`)
- Modify: `tests/test_ingest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest.py`:

```python
from ardupilot_mcp.ingest import main


def test_main_rejects_both_html_and_url_flags(capsys):
    with pytest.raises(SystemExit):
        main([
            "--html", "x.html", "--url", "https://example.test/parameters.html",
            "--vehicle", "plane", "--firmware-version", "1.0",
        ])
    assert "not allowed with argument" in capsys.readouterr().err


def test_main_rejects_neither_html_nor_url_flag(capsys):
    with pytest.raises(SystemExit):
        main([])
    assert "one of the arguments --html --url is required" in capsys.readouterr().err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ingest.py -v -k "main_rejects"`
Expected: FAIL — current `main()` has `--html` as a plain `required=True`
argument, not part of a mutually exclusive group, so `--url` isn't even a
recognized flag yet (`error: unrecognized arguments: --url ...`).

- [ ] **Step 3: Update `main()`**

Find `def main(` in `src/ardupilot_mcp/ingest.py` and replace the whole
function with:

```python
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest an ArduPilot parameter reference HTML file into SQLite.",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--html", type=Path,
                               help="Path to the parameters HTML file")
    source_group.add_argument("--url",
                               help="URL to fetch the parameters page from directly, "
                                    "e.g. https://ardupilot.org/copter/docs/parameters.html")
    parser.add_argument("--vehicle", default=None,
                         choices=["plane", "copter", "rover", "sub"],
                         help="Required with --html; auto-detected from --url if omitted")
    parser.add_argument("--firmware-version", default=None,
                         help="Required with --html; auto-detected from the page "
                              "if --url is used and this is omitted")
    parser.add_argument("--source-url", default=None,
                         help="Canonical URL to record with each row "
                              "(defaults to --url if given)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                         help="SQLite DB path")
    parser.add_argument("--build-vectors", action="store_true",
                         help="Also rebuild the semantic index for this version")
    parser.add_argument("--vectors-path", type=Path, default=None,
                         help="LanceDB directory (defaults to data/vectors.lance)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    result = ingest(
        html_path=args.html,
        url=args.url,
        vehicle=args.vehicle,
        firmware_version=args.firmware_version,
        source_url=args.source_url,
        db_path=args.db,
        build_vectors=args.build_vectors,
        vectors_path=args.vectors_path,
        verbose=not args.quiet,
    )
    print(f"ingested {result.count} parameters "
          f"({result.vehicle} {result.firmware_version}) -> {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: no failures beyond any pre-existing ones caused by missing
`data/ardupilot-docs/` fixtures (gitignored, per CLAUDE.md) — confirm the
count of *new* failures is zero relative to a run on `main` before this
plan's changes.

- [ ] **Step 6: Commit**

```bash
git add src/ardupilot_mcp/ingest.py tests/test_ingest.py
git commit -m "feat: add --url flag to ingest CLI, make --vehicle/--firmware-version optional"
```

---

### Task 7: Update README via `/documentation:update-readme`

**Files:**

- Modify: `README.md` (via skill, not hand-edited)

- [ ] **Step 1: Run the skill**

Invoke `/documentation:update-readme`. Point it at what changed: `ingest.py`
now accepts `--url` as an alternative to `--html`/`--vehicle`/`--firmware-version`
(auto-detected from the URL and page when using `--url`). The skill should
update the "Step-by-step setup" section (currently step 2-3's manual
"open the link, Save Page As…" instructions plus the `--html ...` command in
step 5) and the "Advanced: running without Docker" section's example command
to show the `--url` form as the primary path, keeping the `--html` form
documented as the fallback for offline/manual use.

- [ ] **Step 2: Review the diff**

Run: `git diff README.md`
Confirm: the `--url` flow reads as the recommended default (no more manual
"save the page" instructions as the primary path), the `--html` flow is
still documented as an alternative, and no other README sections
(Features, MCP tools, Project structure) were touched.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document --url ingest flow in README"
```

---

## Spec coverage check

- Fetch page by URL → Task 1, 2, 5.
- Auto-detect vehicle from URL → Task 1, 5.
- Auto-detect firmware version from page text → Task 3, 5.
- Archive fetched HTML to `data/ardupilot-docs/` with the conventional
  filename → Task 5.
- `--html`/`--url` mutually exclusive CLI, `--vehicle`/`--firmware-version`
  optional → Task 6.
- Local-file path unchanged, still requires `--vehicle`/`--firmware-version`
  → Task 5 (`test_ingest_html_path_still_requires_vehicle_and_version`).
- Error handling (network failure, undetectable vehicle/version, both/neither
  flags) → Task 2 (network), Task 5 (detection + both/neither), Task 6 (CLI
  mutual exclusivity).
- Shared parsing core (`parse_html`) for file and URL paths → Task 4.
- README documentation update → Task 7.
