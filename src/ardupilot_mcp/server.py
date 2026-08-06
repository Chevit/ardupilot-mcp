"""FastMCP server exposing ArduPilot parameter Q&A over local SQLite + LanceDB.

Run manually (for testing):
    uv run python -m ardupilot_mcp.server

Wire into Claude Desktop by adding a stdio entry to your
claude_desktop_config.json — see the project README.

All queries are 100% local. The vector store loads its embedding model
lazily on the first semantic query; before that the process is very cheap
and startup is instant, which keeps Claude Desktop responsive.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .catalog import ParameterCatalog


mcp = FastMCP("ardupilot-docs")

# Lazy catalog — the SQLite connection opens on first tool call; the
# semantic model loads even later, on first semantic_search call.
_catalog: Optional[ParameterCatalog] = None


def _get_catalog() -> ParameterCatalog:
    global _catalog
    if _catalog is None:
        _catalog = ParameterCatalog()
    return _catalog


# --------------------------------------------------------------------------- #
# Tools                                                                       #
# --------------------------------------------------------------------------- #

@mcp.tool()
def list_versions(vehicle: str = "plane") -> list[str]:
    """List firmware versions available in the local database.

    Call this first if you're unsure which versions are indexed. Currently
    only 'plane' is supported. Returns a list like ['4.6.3', '4.8.0'].
    """
    return _get_catalog().list_versions(vehicle)


@mcp.tool()
def lookup_parameter(
    name: str,
    firmware_version: Optional[str] = None,
    vehicle: str = "plane",
) -> dict[str, Any] | None:
    """Look up an ArduPilot parameter by exact name.

    Use this when the user references a specific parameter by name
    (e.g. "what does RC_OPTIONS do?", "valid values for LOG_BITMASK",
    "range of THR_MAX"). Names look like ALL_CAPS_WITH_UNDERSCORES.

    Returns the full definition including description, units, range,
    and any enum/bitmask values. Returns None if not found.

    Args:
        name: Exact parameter name, case-sensitive (e.g. "RC_OPTIONS").
        firmware_version: e.g. "4.8.0" or "4.6.3". Omit to use the latest.
        vehicle: "plane" (only supported vehicle for now).
    """
    return _get_catalog().lookup_parameter(name, firmware_version, vehicle)


@mcp.tool()
def search_parameters(
    query: str,
    firmware_version: Optional[str] = None,
    limit: int = 10,
    vehicle: str = "plane",
) -> list[dict[str, Any]]:
    """Keyword search over parameter names, descriptions, sections, and enum labels.

    Backed by SQLite FTS5. Best for exact-word queries or when you need to
    search a specific firmware version. Value labels are indexed too, so
    'Fast Attitude' will find LOG_BITMASK (which has that bit meaning).

    Query syntax follows FTS5: bare words are AND-ed; use double quotes for
    phrases ('"attitude locking"'); use * for prefix ('RTL*').

    Args:
        query: Search terms.
        firmware_version: Filter to a version. Omit to search all versions.
        limit: Maximum results (default 10).
        vehicle: "plane".
    """
    return _get_catalog().search_parameters(query, firmware_version, limit, vehicle)


@mcp.tool()
def semantic_search(
    query: str,
    k: int = 5,
    vehicle: str = "plane",
) -> list[dict[str, Any]]:
    """Semantic (vector) search over parameter descriptions.

    Use this for conceptual questions where the user is describing a symptom
    or behavior rather than naming a specific parameter — e.g. "why is my
    plane climbing too aggressively on RTL?", "how do I make landings
    smoother?", "параметри для стабілізації висоти".

    Multilingual — Ukrainian and English work equally well.
    Only searches the latest indexed firmware version (semantic index does
    not cover older versions; use search_parameters for those).

    Args:
        query: Natural-language question or description.
        k: Number of results to return (default 5).
        vehicle: "plane".
    """
    return _get_catalog().semantic_search(query, k, vehicle)


@mcp.tool()
def list_parameters(
    prefix: Optional[str] = None,
    section: Optional[str] = None,
    firmware_version: Optional[str] = None,
    vehicle: str = "plane",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Browse parameters by name prefix or section.

    Use this when the user asks to see a family of parameters, e.g.
    "list all RTL parameters", "what's in the AHRS group", "show me the
    ARSPD_ family".

    Args:
        prefix: Name prefix to match. "RTL" matches RTL_ALTITUDE, RTL_CLIMB_MIN, etc.
                Do not include a trailing underscore.
        section: Section name. Use list_sections() first if unsure. Case-insensitive.
        firmware_version: Version filter. Defaults to the latest indexed.
        vehicle: "plane".
        limit: Maximum results (default 50).
    """
    return _get_catalog().list_parameters(prefix, section, firmware_version, vehicle, limit)


@mcp.tool()
def diff_parameter(
    name: str,
    version_a: str,
    version_b: str,
    vehicle: str = "plane",
) -> dict[str, Any]:
    """Compare a parameter across two ArduPilot firmware versions.

    Reports field-by-field differences (description, range, units, values,
    bitmask bits) between the two versions. Useful for understanding what
    changed when upgrading firmware.

    Returns a dict with keys 'name', 'version_a', 'version_b', 'exists_in_a',
    'exists_in_b', and 'differences' (list of field-level diffs). If the
    parameter is missing in either version, 'differences' is empty and the
    exists_* flags convey that.

    Args:
        name: Parameter name (case-sensitive).
        version_a: e.g. "4.6.3".
        version_b: e.g. "4.8.0".
        vehicle: "plane".
    """
    return _get_catalog().diff_parameter(name, version_a, version_b, vehicle)


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #

def _server_settings(env: dict[str, str] | None = None) -> tuple[str, str, int]:
    """Resolve (transport, host, port) from environment variables.

    MCP_TRANSPORT selects "stdio" (default) or "streamable-http". host is
    always "0.0.0.0" — required for Docker's port publishing to reach the
    process inside the container; it's simply unused in stdio mode.
    MCP_HTTP_PORT sets the port for streamable-http mode (default 8000,
    unused in stdio mode).
    """
    env = os.environ if env is None else env
    transport = env.get("MCP_TRANSPORT", "stdio")
    if transport not in ("stdio", "streamable-http"):
        raise ValueError(f"Unknown MCP_TRANSPORT: {transport!r}")
    port = int(env.get("MCP_HTTP_PORT", "8000"))
    return transport, "0.0.0.0", port


def main() -> None:
    """Entry point. Transport selected via MCP_TRANSPORT env var.

    Defaults to stdio, for Claude Desktop and similar MCP clients. Set
    MCP_TRANSPORT=streamable-http (with optional MCP_HTTP_PORT) to serve
    remote clients instead — see the Docker section of CLAUDE.md.
    """
    transport, host, port = _server_settings()
    if transport == "streamable-http":
        mcp.settings.host = host
        mcp.settings.port = port
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
