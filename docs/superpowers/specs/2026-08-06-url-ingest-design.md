# Direct URL ingest for ArduPilot parameter pages

## Problem

Ingest currently requires the user to manually download the parameters HTML
page (e.g. from `https://ardupilot.org/plane/docs/parameters.html`), save it
locally, and pass `--html <path> --vehicle <v> --firmware-version <ver>`.
This is a manual, error-prone step before every ingest.

## Goal

Let `ardupilot-refresh` fetch the page directly from a URL, auto-detecting
the vehicle (from the URL path) and firmware version (from the page text),
so the common case is:

```bash
uv run python -m ardupilot_mcp.ingest --url https://ardupilot.org/copter/docs/parameters.html
```

Out of scope: automated/scheduled refresh, `scripts/refresh.py` changes,
multi-vehicle batch fetch, offline/proxy configuration.

## Architecture

### New module: `src/ardupilot_mcp/fetch.py`

- `fetch_url(url: str) -> str` — `httpx.get(url, follow_redirects=True)`,
  raises `RuntimeError` on network failure or non-2xx status, returns
  `response.text` on success.
- `detect_vehicle_from_url(url: str) -> str | None` — regex match on the URL
  path for `/(plane|copter|rover|sub)/docs/parameters`; returns `None` if no
  segment matches.

### `scraper.py` additions

- `detect_version(html: str) -> str | None` — regex over the page text for
  the pattern that currently reads e.g. "Full Parameter List of Plane latest
  V4.8.0 dev" (`V(\d+\.\d+\.\d+)`); returns `None` if not found.
- Refactor `parse_html_file(path, ...)` into a thin wrapper: read the file,
  delegate to a new `parse_html(html: str, vehicle, firmware_version,
  source_url) -> list[Parameter]` that holds the existing parse logic. Both
  the file path and the URL path share this core; parsing behavior is
  unchanged.

### `ingest.py` — `ingest()` signature changes

```python
def ingest(
    html_path: Optional[Path] = None,
    url: Optional[str] = None,
    vehicle: Optional[str] = None,
    firmware_version: Optional[str] = None,
    source_url: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
    build_vectors: bool = False,
    vectors_path: Optional[Path] = None,
    verbose: bool = False,
) -> int:
```

Exactly one of `html_path` / `url` must be given (enforced by the CLI's
mutually exclusive, required argparse group; `ingest()` itself raises
`ValueError` if both or neither are given, for callers that skip the CLI).

**URL path:**

1. `html = fetch_url(url)`.
2. `vehicle = vehicle or detect_vehicle_from_url(url)` — raise `ValueError`
   if still `None`.
3. `firmware_version = firmware_version or detect_version(html)` — raise
   `ValueError` if still `None`.
4. `source_url = source_url or url`.
5. Build the conventional filename `Complete Parameter List — {Vehicle}
   documentation {firmware_version}.html` (title-cased vehicle, matching
   the naming convention `scripts/refresh.py`'s `discover_pairs` already
   expects) and write `html` to `data/ardupilot-docs/<that name>` — archives
   the fetch the same way a manual download would have.
6. `parse_html(html, vehicle, firmware_version, source_url)`.

**Local-file path:** unchanged. `vehicle` and `firmware_version` remain
required in this branch — local files carry no auto-detectable version
metadata beyond the filename convention, and the user is expected to pass
flags matching the file they chose.

The rest of `ingest()` (DB write, optional vector rebuild) is unchanged.

### CLI (`main()`)

- `--html` and `--url` become a mutually exclusive, required argparse group
  (replacing today's single required `--html`).
- `--vehicle` and `--firmware-version` become optional (`required=False`).
  Still required in practice when `--html` is used — validated by `ingest()`
  raising `ValueError` if the local-file branch is missing either.
- `--source-url` unchanged (optional); when `--url` is given and
  `--source-url` is omitted, it defaults to the fetched URL.

Example usage:

```bash
# common case — vehicle + version auto-detected
ardupilot-refresh --url https://ardupilot.org/copter/docs/parameters.html

# override auto-detected version (e.g. pin to a stable release page)
ardupilot-refresh --url https://ardupilot.org/plane/docs/parameters.html \
    --firmware-version 4.8.0
```

## Error handling

No new exception-handling machinery — `main()` has no top-level
try/except today; errors propagate as uncaught exceptions with Python's
default non-zero exit and traceback. New failure modes follow the same
pattern:

- Network failure (timeout, DNS, non-2xx) → `RuntimeError` from
  `fetch_url`.
- Vehicle undetectable from URL → `ValueError` from `ingest()`, message
  tells the user to pass `--vehicle` explicitly.
- Version undetectable from page text → `ValueError` from `ingest()`,
  message tells the user to pass `--firmware-version` explicitly.
- Both/neither of `--html`/`--url` given → argparse's own mutually
  exclusive group error (CLI layer), or `ValueError` from `ingest()` for
  direct callers.

## Testing

Repo has `tests/test_scraper.py` and `tests/test_refresh.py` (pytest) despite
CLAUDE.md's "no dedicated test suite" note — new tests follow that existing
style:

- `detect_vehicle_from_url`: table of URLs → expected vehicle, including a
  no-match case.
- `detect_version`: sample page-text snippets → expected version, including
  a no-match case.
- `fetch_url`: `httpx.MockTransport` for success and non-2xx cases — no real
  network calls in tests.
- `ingest()` URL path: integration-style test using `httpx.MockTransport` to
  return a canned parameters HTML fixture; asserts the archived file lands
  under `data/ardupilot-docs/` with the conventional name and that DB rows
  appear.
- Existing `parse_html_file`/`parse_html` tests unchanged — parsing logic is
  relocated, not modified.

## Documentation

README documents the manual-download ingest flow (`--html` usage) — once
implementation lands, run the `/documentation:update-readme` skill to fold
in the new `--url` flag and auto-detect behavior so README stays accurate.
