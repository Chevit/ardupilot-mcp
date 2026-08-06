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
  <h3>FOO_BAR: A test parameter¶</h3>
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
