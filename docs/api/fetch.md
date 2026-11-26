# fetch

HTTP download of parameter pages from ardupilot.org, and vehicle detection from a URL.

## Overview

Owns network I/O for [ingest](ingest.md)'s `--url`, `--all` and `--roster` paths. Vehicle names recognised in URLs
are bounded by the [Vehicle Roster](roster.md), not a hardcoded list.

## Public API

### detect_vehicle_from_url

```python
def detect_vehicle_from_url(url: str, vehicle_names: Iterable[str] | None = None) -> str | None
```

Returns the vehicle in a `/<vehicle>/docs/parameters...` URL if it is one of `vehicle_names` (default: the loaded
Roster's keys), else `None`. An empty `vehicle_names` returns `None`.

### fetch_url

```python
def fetch_url(url: str, client: httpx.Client | None = None) -> str
```

GETs `url` and returns the body text. Without `client`, uses a short-lived client that follows redirects with a 30 s
timeout. Any `httpx.HTTPError`, including non-2xx responses, is re-raised as `RuntimeError("failed to fetch ...")`.
`client` is injectable for tests (e.g. an `httpx.Client` on an `httpx.MockTransport`).

## Usage examples

```python
from ardupilot_mcp.fetch import detect_vehicle_from_url, fetch_url

url = "https://ardupilot.org/copter/docs/parameters.html"
assert detect_vehicle_from_url(url) == "copter"
html = fetch_url(url)
```

## Dependencies

- `httpx`; [roster](roster.md) for the default vehicle names.
