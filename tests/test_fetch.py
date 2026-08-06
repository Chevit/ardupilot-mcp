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
