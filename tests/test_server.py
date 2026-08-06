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
