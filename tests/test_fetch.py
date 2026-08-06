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
