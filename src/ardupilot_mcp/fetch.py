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
