"""Smoke test: server.py registers all six tools against a real FastMCP instance."""

from __future__ import annotations


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
