"""Smoke test: server.py registers all six tools against a real FastMCP instance."""

from __future__ import annotations

import pytest


def test_server_registers_all_six_tools():
    from ardupilot_mcp import server

    tool_names = {t.name for t in server.mcp._tool_manager.list_tools()}

    assert tool_names == {
        "list_vehicles",
        "lookup_parameter",
        "search_parameters",
        "semantic_search",
        "list_parameters",
        "diff_parameter",
    }


@pytest.mark.parametrize("tool_name,required_params", [
    ("lookup_parameter", {"name", "vehicle"}),
    ("list_parameters", {"vehicle"}),
    ("diff_parameter", {"name", "vehicle_a", "vehicle_b"}),
])
def test_hard_filtered_tools_require_vehicle_no_default(tool_name, required_params):
    # Q3: vehicle is required with no default on every hard-filtered tool —
    # the client must state it explicitly every call. FastMCP's generated
    # schema marks a param "required" exactly when the Python signature has
    # no default, so this is checked at the schema level.
    from ardupilot_mcp import server

    tool = next(t for t in server.mcp._tool_manager.list_tools() if t.name == tool_name)
    schema_required = set(tool.parameters.get("required", []))
    assert required_params <= schema_required


@pytest.mark.parametrize("tool_name", ["search_parameters", "semantic_search"])
def test_search_tools_vehicle_is_optional(tool_name):
    # Q4: the two search tools allow vehicle=None to mean "all enabled".
    from ardupilot_mcp import server

    tool = next(t for t in server.mcp._tool_manager.list_tools() if t.name == tool_name)
    schema_required = set(tool.parameters.get("required", []))
    assert "vehicle" not in schema_required


def test_search_tool_end_to_end_survives_natural_language_query(tmp_path, monkeypatch):
    # Through FastMCP's call_tool, as a client would: punctuation in the
    # query must not reach the client as a raw SQLite error.
    import asyncio
    import json

    from ardupilot_mcp import db, server
    from ardupilot_mcp.catalog import ParameterCatalog

    roster = tmp_path / "vehicles.json"
    roster.write_text(json.dumps({"plane": {"url": "https://example.test/p.html"}}))
    db_path = tmp_path / "t.db"
    db.init_schema(db_path)
    with db.connect(db_path) as conn:
        db.upsert_parameter(conn, db.Parameter(
            vehicle="plane", firmware_version="4.8.0", name="RTL_ALTITUDE",
            description="Altitude to hold during RTL",
        ), scraped_at="2026-01-01T00:00:00+00:00")
    cat = ParameterCatalog(db_path=db_path, vectors_path=tmp_path / "v.lance",
                           model_cache_path=tmp_path / "mc", vehicles_config=roster)
    monkeypatch.setattr(server, "_catalog", cat)
    try:
        result = asyncio.run(server.mcp.call_tool(
            "search_parameters", {"query": "what is the RTL altitude?"}))
    finally:
        cat.close()

    assert "RTL_ALTITUDE" in str(result)


def test_server_settings_defaults_to_stdio():
    from ardupilot_mcp.server import _server_settings

    transport, host, port = _server_settings({})

    assert transport == "stdio"
    assert host == "0.0.0.0"
    assert port == 8000


def test_server_settings_reads_streamable_http_and_custom_port():
    from ardupilot_mcp.server import _server_settings

    transport, host, port = _server_settings(
        {"MCP_TRANSPORT": "streamable-http", "MCP_HTTP_PORT": "9001"}
    )

    assert transport == "streamable-http"
    assert host == "0.0.0.0"
    assert port == 9001


def test_server_settings_rejects_unknown_transport():
    from ardupilot_mcp.server import _server_settings

    with pytest.raises(ValueError, match="MCP_TRANSPORT"):
        _server_settings({"MCP_TRANSPORT": "sse"})
