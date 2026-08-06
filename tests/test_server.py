"""Smoke test: server.py registers all six tools against a real FastMCP instance."""

from __future__ import annotations

import pytest


def test_server_registers_all_six_tools():
    from ardupilot_mcp import server

    tool_names = {t.name for t in server.mcp._tool_manager.list_tools()}

    assert tool_names == {
        "list_versions",
        "lookup_parameter",
        "search_parameters",
        "semantic_search",
        "list_parameters",
        "diff_parameter",
    }


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
