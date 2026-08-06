"""Fetch ArduPilot parameter reference pages directly from ardupilot.org.

Complements scraper.py's local-file parsing: this module owns network I/O
(`fetch_url`) and the URL-shape heuristic (`detect_vehicle_from_url`) that
let ingest.py skip the manual "download the page, guess the flags" step.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

import httpx

from .roster import load_roster


def detect_vehicle_from_url(
    url: str, vehicle_names: Optional[Iterable[str]] = None
) -> Optional[str]:
    """Extract the vehicle segment from an ardupilot.org parameters URL.

    `vehicle_names` bounds which names count as a match — defaults to the
    Vehicle Roster's keys (see roster.py) so this stays in sync with
    whatever vehicles the roster knows about, without a hardcoded list
    (see docs/adr/0002-vehicle-roster-owns-the-vehicle-list.md).

    Returns None if the URL doesn't match the expected
    "/<vehicle>/docs/parameters..." shape for a known vehicle name.
    """
    if vehicle_names is None:
        vehicle_names = load_roster().keys()
    pattern = "|".join(re.escape(name) for name in vehicle_names)
    if not pattern:
        return None
    m = re.search(rf"/({pattern})/docs/parameters", url)
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
