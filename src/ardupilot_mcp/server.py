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

import sqlite3
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .db import (
    DEFAULT_DB_PATH,
    connect,
    list_versions as _list_versions_db,
)
from .vectors import (
    DEFAULT_MODEL_CACHE_PATH,
    DEFAULT_VECTORS_PATH,
    VectorStore,
)


mcp = FastMCP("ardupilot-docs")

# Lazy vector store — model weights are only loaded on first semantic query.
_store: Optional[VectorStore] = None


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #

def _get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore(
            path=DEFAULT_VECTORS_PATH,
            model_cache_path=DEFAULT_MODEL_CACHE_PATH,
        )
    return _store


def _latest_version(vehicle: str) -> Optional[str]:
    with connect(DEFAULT_DB_PATH) as conn:
        versions = _list_versions_db(conn, vehicle)
    return versions[-1] if versions else None


def _row_to_param(
    conn: sqlite3.Connection, row: sqlite3.Row, include_values: bool = True
) -> dict[str, Any]:
    """Convert a parameters row into a JSON-friendly dict, optionally with values."""
    out = {
        "id": row["id"],
        "name": row["name"],
        "vehicle": row["vehicle"],
        "firmware_version": row["firmware_version"],
        "backend": row["backend"],
        "display_name": row["display_name"],
        "description": row["description"],
        "section": row["section"],
        "units": row["units"],
        "range": (
            {"min": row["range_min"], "max": row["range_max"]}
            if row["range_min"] is not None
            else None
        ),
        "increment": row["increment"],
        "is_bitmask": bool(row["is_bitmask"]),
        "read_only": bool(row["read_only"]),
        "advanced": bool(row["advanced"]),
        "source_url": row["source_url"],
    }
    if include_values:
        vals = conn.execute(
            """SELECT value, label, is_bit
               FROM parameter_values
               WHERE parameter_id = ?
               ORDER BY id""",
            (row["id"],),
        ).fetchall()
        out["values"] = [
            {"value": v["value"], "label": v["label"], "is_bit": bool(v["is_bit"])}
            for v in vals
        ]
    return out


# --------------------------------------------------------------------------- #
# Tools                                                                       #
# --------------------------------------------------------------------------- #

@mcp.tool()
def list_versions(vehicle: str = "plane") -> list[str]:
    """List firmware versions available in the local database.

    Call this first if you're unsure which versions are indexed. Currently
    only 'plane' is supported. Returns a list like ['4.6.3', '4.8.0'].
    """
    with connect(DEFAULT_DB_PATH) as conn:
        return _list_versions_db(conn, vehicle)


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
    if firmware_version is None:
        firmware_version = _latest_version(vehicle)
        if firmware_version is None:
            return None
    with connect(DEFAULT_DB_PATH) as conn:
        # Prefer the main definition (backend IS NULL) over driver variants.
        row = conn.execute(
            """SELECT * FROM parameters
               WHERE vehicle = ? AND firmware_version = ? AND name = ?
               ORDER BY (backend IS NULL) DESC
               LIMIT 1""",
            (vehicle, firmware_version, name),
        ).fetchone()
        if row is None:
            return None
        param = _row_to_param(conn, row)

        # If backend variants exist, expose them as a compact summary.
        variants = conn.execute(
            """SELECT backend FROM parameters
               WHERE vehicle = ? AND firmware_version = ? AND name = ?
                 AND backend IS NOT NULL
               ORDER BY backend""",
            (vehicle, firmware_version, name),
        ).fetchall()
        if variants:
            param["backend_variants"] = [v["backend"] for v in variants]
        return param


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
    fw_filter_sql = ""
    fw_params: tuple = ()
    if firmware_version is not None:
        fw_filter_sql = " AND p.firmware_version = ?"
        fw_params = (firmware_version,)

    with connect(DEFAULT_DB_PATH) as conn:
        rows = conn.execute(
            f"""SELECT p.*, snippet(parameters_fts, 2, '[', ']', ' ... ', 12) AS snippet
                FROM parameters_fts
                JOIN parameters p ON p.id = parameters_fts.rowid
                WHERE parameters_fts MATCH ?
                  AND p.vehicle = ?{fw_filter_sql}
                ORDER BY rank
                LIMIT ?""",
            (query, vehicle, *fw_params, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            p = _row_to_param(conn, r, include_values=False)
            p["snippet"] = r["snippet"]
            out.append(p)
        return out


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
    fw = _latest_version(vehicle)
    if fw is None:
        return []
    store = _get_store()
    hits = store.search(query, k=k, firmware_version=fw)
    if not hits:
        return []
    ids = [h["param_id"] for h in hits]
    with connect(DEFAULT_DB_PATH) as conn:
        # Fetch in-DB order then reorder to match ranking
        rows = {
            r["id"]: r
            for r in conn.execute(
                f"""SELECT * FROM parameters
                    WHERE id IN ({','.join('?' * len(ids))})""",
                ids,
            )
        }
        out: list[dict[str, Any]] = []
        for h in hits:
            r = rows.get(h["param_id"])
            if r is None:
                continue
            p = _row_to_param(conn, r, include_values=False)
            p["distance"] = float(h["_distance"])
            out.append(p)
        return out


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
    if firmware_version is None:
        firmware_version = _latest_version(vehicle)
        if firmware_version is None:
            return []

    where = ["vehicle = ?", "firmware_version = ?", "backend IS NULL"]
    params: list[Any] = [vehicle, firmware_version]
    if prefix:
        where.append("name LIKE ? ESCAPE '\\'")
        # Escape LIKE wildcards in the prefix itself, then append %
        safe_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"{safe_prefix}%")
    if section:
        where.append("LOWER(section) = LOWER(?)")
        params.append(section)
    params.append(limit)

    with connect(DEFAULT_DB_PATH) as conn:
        rows = conn.execute(
            f"""SELECT * FROM parameters
                WHERE {' AND '.join(where)}
                ORDER BY name
                LIMIT ?""",
            params,
        ).fetchall()
        return [_row_to_param(conn, r, include_values=False) for r in rows]


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
    def _fetch(conn: sqlite3.Connection, fw: str) -> Optional[dict[str, Any]]:
        row = conn.execute(
            """SELECT * FROM parameters
               WHERE vehicle = ? AND firmware_version = ? AND name = ?
                 AND backend IS NULL
               LIMIT 1""",
            (vehicle, fw, name),
        ).fetchone()
        return _row_to_param(conn, row) if row is not None else None

    with connect(DEFAULT_DB_PATH) as conn:
        a = _fetch(conn, version_a)
        b = _fetch(conn, version_b)

    result: dict[str, Any] = {
        "name": name,
        "version_a": version_a,
        "version_b": version_b,
        "exists_in_a": a is not None,
        "exists_in_b": b is not None,
        "differences": [],
    }
    if a is None or b is None:
        return result

    fields = ("description", "section", "units", "range", "increment",
              "is_bitmask", "read_only", "advanced", "display_name")
    for f in fields:
        if a.get(f) != b.get(f):
            result["differences"].append({
                "field": f,
                "version_a": a.get(f),
                "version_b": b.get(f),
            })

    # Values / bitmask bits — compare as ordered lists of (value, label, is_bit)
    def _val_tuples(p: dict) -> list[tuple]:
        return [(v["value"], v["label"], v["is_bit"]) for v in p.get("values", [])]

    if _val_tuples(a) != _val_tuples(b):
        result["differences"].append({
            "field": "values",
            "version_a": a.get("values"),
            "version_b": b.get("values"),
        })

    return result


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #

def main() -> None:
    """stdio transport for Claude Desktop and similar MCP clients."""
    mcp.run()


if __name__ == "__main__":
    main()