"""FastMCP server exposing ArduPilot parameter Q&A over local SQLite + LanceDB.

Run manually (for testing):
    uv run python -m ardupilot_mcp.server

Wire into Claude Desktop by adding a stdio entry to your
claude_desktop_config.json — see the project README.

All queries are 100% local. The vector store loads its embedding model
lazily on the first semantic query; before that the process is very cheap
and startup is instant, which keeps Claude Desktop responsive.

`vehicle` has no default on any tool — the Vehicle Roster (see roster.py)
decides which vehicles exist, and a wrong silent default (e.g. always
"plane") is worse than a client having to call list_vehicles() first. The
two search tools (search_parameters, semantic_search) accept vehicle=None
to mean "every enabled vehicle"; lookup_parameter, list_parameters, and
diff_parameter always hard-scope to the vehicle(s) given.
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
def list_vehicles() -> list[dict[str, Any]]:
    """List every Vehicle on the Vehicle Roster.

    Call this first if you're unsure which vehicle to pass — every other
    tool requires one, with no default. Each entry reports the vehicle
    name, whether it's enabled (fetched by --all ingest runs), and
    ingested_version — the firmware version currently stored, or null if
    this vehicle has never been ingested.
    """
    return _get_catalog().list_vehicles()


@mcp.tool()
def lookup_parameter(name: str, vehicle: str) -> dict[str, Any] | None:
    """Look up an ArduPilot parameter by exact name.

    Use this when the user references a specific parameter by name
    (e.g. "what does RC_OPTIONS do?", "valid values for LOG_BITMASK",
    "range of THR_MAX"). Names look like ALL_CAPS_WITH_UNDERSCORES.

    Returns the full definition including description, units, range,
    and any enum/bitmask values. Returns None if not found.

    Args:
        name: Exact parameter name, case-sensitive (e.g. "RC_OPTIONS").
        vehicle: e.g. "plane", "copter". Call list_vehicles() if unsure.
    """
    return _get_catalog().lookup_parameter(name, vehicle)


@mcp.tool()
def search_parameters(
    query: str,
    vehicle: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Keyword search over parameter names, descriptions, sections, and enum labels.

    Backed by SQLite FTS5. Best for exact-word queries. Value labels are
    indexed too, so 'Fast Attitude' will find LOG_BITMASK (which has that
    bit meaning).

    Query syntax follows FTS5: bare words are AND-ed; use double quotes for
    phrases ('"attitude locking"'); use * for prefix ('RTL*').

    Args:
        query: Search terms.
        vehicle: Restrict to one vehicle (e.g. "plane"). Omit to search
            every enabled vehicle on the Vehicle Roster — results are
            tagged with which vehicle they came from.
        limit: Maximum results (default 10).
    """
    return _get_catalog().search_parameters(query, vehicle, limit)


@mcp.tool()
def semantic_search(
    query: str,
    vehicle: Optional[str] = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Semantic (vector) search over parameter descriptions.

    Use this for conceptual questions where the user is describing a symptom
    or behavior rather than naming a specific parameter — e.g. "why is my
    plane climbing too aggressively on RTL?", "how do I make landings
    smoother?", "параметри для стабілізації висоти".

    Multilingual — Ukrainian and English work equally well.

    Args:
        query: Natural-language question or description.
        vehicle: Restrict to one vehicle. Omit to search every enabled
            vehicle — when a parameter matches in several, the results are
            deduped and the entry reports every vehicle that matched via a
            `vehicles` field, so "which vehicles have X?" is answerable
            directly.
        k: Number of results to return (default 5).
    """
    return _get_catalog().semantic_search(query, vehicle, k)


@mcp.tool()
def list_parameters(
    vehicle: str,
    prefix: Optional[str] = None,
    section: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Browse a vehicle's parameters by name prefix or section.

    Use this when the user asks to see a family of parameters, e.g.
    "list all RTL parameters", "what's in the AHRS group", "show me the
    ARSPD_ family".

    Args:
        vehicle: e.g. "plane", "copter". Call list_vehicles() if unsure.
        prefix: Name prefix to match. "RTL" matches RTL_ALTITUDE, RTL_CLIMB_MIN, etc.
                Do not include a trailing underscore.
        section: Section name. Case-insensitive.
        limit: Maximum results (default 50).
    """
    return _get_catalog().list_parameters(vehicle, prefix, section, limit)


@mcp.tool()
def diff_parameter(
    name: str,
    vehicle_a: str,
    vehicle_b: str,
) -> dict[str, Any]:
    """Compare a parameter's definition across two ArduPilot vehicles.

    Reports field-by-field differences (description, range, units, values,
    bitmask bits) between the two vehicles' definitions of the same
    parameter name. Useful for "how does RTL_ALT differ between plane and
    copter?"-style questions.

    Returns a dict with keys 'name', 'vehicle_a', 'vehicle_b',
    'exists_in_a', 'exists_in_b', 'version_a', 'version_b',
    'version_mismatch', and 'differences' (list of field-level diffs).
    version_a/version_b are each vehicle's stored firmware_version —
    provenance, not something you pass in — and version_mismatch is true
    when the two vehicles happen to be pinned to different versions on the
    Vehicle Roster, since that can itself explain part of the diff. If the
    parameter is missing in either vehicle, 'differences' is empty and the
    exists_* flags convey that.

    Args:
        name: Parameter name (case-sensitive).
        vehicle_a: e.g. "plane".
        vehicle_b: e.g. "copter".
    """
    return _get_catalog().diff_parameter(name, vehicle_a, vehicle_b)


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
