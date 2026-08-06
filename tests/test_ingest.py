"""Tests for ingest.py's URL-based ingest path.

No real network calls — the URL path is exercised against an
httpx.MockTransport-backed client injected via ingest()'s http_client param.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ardupilot_mcp.ingest import ingest, ingest_all, main

_FIXTURE_HTML = """
<html><body>
<h2>Full Parameter List of Copter latest V4.9.0 dev</h2>
<section>
  <h3>FOO_BAR: A test parameter¶</h3>
  <p>Description.</p>
</section>
</body></html>
"""


def _mock_client(text: str = _FIXTURE_HTML, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=text)

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


def test_ingest_replaces_only_the_target_vehicle(tmp_path):
    # ADR-0001: re-ingesting a vehicle wipes it wholesale; other vehicles
    # (and their firmware_version) are untouched.
    from ardupilot_mcp import db as db_module

    db_path = tmp_path / "test.db"
    archive_dir = tmp_path / "ardupilot-docs"

    ingest(url="https://ardupilot.org/copter/docs/parameters.html",
           db_path=db_path, archive_dir=archive_dir, http_client=_mock_client())

    plane_html = """
    <html><body>
    <h2>Full Parameter List of Plane latest V4.8.0 dev</h2>
    <section><h3>PLANE_ONLY: A plane parameter¶</h3><p>Desc.</p></section>
    </body></html>
    """
    ingest(url="https://ardupilot.org/plane/docs/parameters.html",
           db_path=db_path, archive_dir=archive_dir, http_client=_mock_client(plane_html))

    with db_module.connect(db_path) as conn:
        vehicles = {r["vehicle"] for r in conn.execute("SELECT DISTINCT vehicle FROM parameters")}
    assert vehicles == {"copter", "plane"}


# -- --all -- #

@pytest.fixture
def roster_file(tmp_path):
    path = tmp_path / "vehicles.json"
    path.write_text(json.dumps({
        "plane": {"url": "https://ardupilot.org/plane/docs/parameters.html", "enabled": True},
        "copter": {"url": "https://ardupilot.org/copter/docs/parameters.html", "enabled": True},
        "blimp": {"url": "https://ardupilot.org/blimp/docs/parameters.html", "enabled": False},
    }))
    return path


def test_ingest_all_only_fetches_enabled_vehicles(tmp_path, roster_file):
    db_path = tmp_path / "test.db"
    archive_dir = tmp_path / "ardupilot-docs"
    fetched_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched_urls.append(str(request.url))
        return httpx.Response(200, text=_FIXTURE_HTML)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    outcomes = ingest_all(
        vehicles_config=roster_file, db_path=db_path, archive_dir=archive_dir,
        http_client=client, verbose=False,
    )

    assert {o.vehicle for o in outcomes} == {"plane", "copter"}  # blimp excluded
    assert all(o.success for o in outcomes)
    assert len(fetched_urls) == 2


def test_ingest_all_continues_past_one_failure(tmp_path, roster_file):
    db_path = tmp_path / "test.db"
    archive_dir = tmp_path / "ardupilot-docs"

    def handler(request: httpx.Request) -> httpx.Response:
        if "copter" in str(request.url):
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=_FIXTURE_HTML)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    outcomes = ingest_all(
        vehicles_config=roster_file, db_path=db_path, archive_dir=archive_dir,
        http_client=client, verbose=False,
    )

    by_vehicle = {o.vehicle: o for o in outcomes}
    assert by_vehicle["plane"].success is True
    assert by_vehicle["copter"].success is False
    assert by_vehicle["copter"].error is not None

    from ardupilot_mcp import db as db_module
    with db_module.connect(db_path) as conn:
        vehicles = {r["vehicle"] for r in conn.execute("SELECT DISTINCT vehicle FROM parameters")}
    assert vehicles == {"plane"}  # the failed vehicle wrote nothing


def test_ingest_all_rebuilds_vectors_once_for_all_successes(tmp_path, roster_file, monkeypatch):
    db_path = tmp_path / "test.db"
    archive_dir = tmp_path / "ardupilot-docs"
    client = _mock_client()

    model_loads = []

    class _FakeStore:
        def __init__(self, *a, **kw):
            pass

        def rebuild(self, rows, vehicle, encoder=None):
            model_loads.append(vehicle)
            return len(rows)

    import ardupilot_mcp.ingest as ingest_module
    monkeypatch.setattr(
        "ardupilot_mcp.vectors.VectorStore", _FakeStore,
    )

    ingest_all(
        vehicles_config=roster_file, db_path=db_path, archive_dir=archive_dir,
        http_client=client, build_vectors=True, verbose=False,
    )

    # One VectorStore instance handles both vehicles -- rebuild() called
    # once per successful vehicle, not once per vehicle PLUS a fresh model
    # load each time.
    assert set(model_loads) == {"plane", "copter"}


# -- main() CLI -- #

def test_main_rejects_both_html_and_url_flags(capsys):
    with pytest.raises(SystemExit):
        main([
            "--html", "x.html", "--url", "https://example.test/parameters.html",
            "--vehicle", "plane", "--firmware-version", "1.0",
        ])
    assert "not allowed with argument" in capsys.readouterr().err


def test_main_rejects_neither_html_nor_url_nor_all_flag(capsys):
    with pytest.raises(SystemExit):
        main([])
    assert "one of the arguments --html --url --all is required" in capsys.readouterr().err


def test_main_prints_clean_error_instead_of_traceback(tmp_path, capsys):
    # A missing --html path makes ingest() raise FileNotFoundError. main()
    # must catch it, print a one-line message, and return 1 — not let the
    # exception propagate as a raw traceback (this tool's audience per
    # README is explicitly non-technical Docker users).
    missing = tmp_path / "does-not-exist.html"
    exit_code = main([
        "--html", str(missing), "--vehicle", "plane", "--firmware-version", "1.0",
    ])
    assert exit_code == 1
    assert capsys.readouterr().err.startswith("error:")
