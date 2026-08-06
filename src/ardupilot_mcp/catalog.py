"""ParameterCatalog — the single seam through which Parameters are looked
up, keyword-searched, semantically searched, browsed, and diffed across
Vehicles. See CONTEXT.md for the ParameterCatalog definition.

Holds one persistent SQLite connection for its process lifetime (safe under
FastMCP's single-threaded, run-to-completion sync tool calls — no locking
needed), one VectorStore, and the Vehicle Roster (see roster.py) — the
authority on which vehicles exist and which are enabled for unscoped
("vehicle=None") search. The embedding model still loads lazily on first
semantic_search call.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from .db import DEFAULT_DB_PATH, ingested_version, open_connection
from .roster import enabled_vehicles, load_roster
from .vectors import DEFAULT_MODEL_CACHE_PATH, DEFAULT_VECTORS_PATH, VectorStore

# vehicle=None semantic_search over-fetches this many candidates per
# requested result before deduping by parameter name, so that a
# near-identical parameter shared across several vehicles doesn't crowd out
# every other result (see docs/adr referenced from CONTEXT.md's VectorStore
# entry and the grilling session's Q14).
_SEMANTIC_SEARCH_OVERFETCH = 4


class ParameterCatalog:
    """Read-side seam over SQLite parameter storage, the semantic
    VectorStore, and the Vehicle Roster."""

    def __init__(
        self,
        db_path=DEFAULT_DB_PATH,
        vectors_path=DEFAULT_VECTORS_PATH,
        model_cache_path=DEFAULT_MODEL_CACHE_PATH,
        vehicles_config: Optional[Path] = None,
    ) -> None:
        self._conn: sqlite3.Connection = open_connection(db_path)
        self._store = VectorStore(path=vectors_path, model_cache_path=model_cache_path)
        self._roster = load_roster(vehicles_config)

    def close(self) -> None:
        """Close the held SQLite connection. The VectorStore's LanceDB handle
        and (if loaded) embedding model are released with the process."""
        self._conn.close()

    # -- internals -- #

    def _enabled_vehicles(self) -> list[str]:
        return enabled_vehicles(self._roster)

    def _row_to_param(
        self, row: sqlite3.Row, include_values: bool = True
    ) -> dict[str, Any]:
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
            vals = self._conn.execute(
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

    def _hits_to_params(
        self,
        hits: list[dict[str, Any]],
        vehicles_by_name: Optional[dict[str, set]] = None,
    ) -> list[dict[str, Any]]:
        """Turn VectorStore.search() hits into full parameter dicts.

        If `vehicles_by_name` is given, each result also carries a
        `vehicles` field — every vehicle whose match collapsed into this
        one (see semantic_search's vehicle=None dedup).
        """
        if not hits:
            return []
        ids = [h["param_id"] for h in hits]
        rows = {
            r["id"]: r
            for r in self._conn.execute(
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
            p = self._row_to_param(r, include_values=False)
            p["distance"] = float(h["_distance"])
            if vehicles_by_name is not None:
                p["vehicles"] = sorted(vehicles_by_name[h["name"]])
            out.append(p)
        return out

    # -- public interface -- #

    def list_vehicles(self) -> list[dict[str, Any]]:
        """Every Vehicle on the Roster, its enabled flag, and whichever
        firmware_version is currently ingested for it (None if never
        ingested). The client's way to discover what `vehicle` values are
        valid — every other tool requires one, with no default."""
        out = []
        for name in sorted(self._roster):
            entry = self._roster[name]
            out.append({
                "vehicle": name,
                "enabled": entry.enabled,
                "ingested_version": ingested_version(self._conn, name),
            })
        return out

    def lookup_parameter(self, name: str, vehicle: str) -> Optional[dict[str, Any]]:
        """Exact-name lookup, hard-scoped to `vehicle`. None if not found."""
        row = self._conn.execute(
            """SELECT * FROM parameters
               WHERE vehicle = ? AND name = ?
               ORDER BY (backend IS NULL) DESC
               LIMIT 1""",
            (vehicle, name),
        ).fetchone()
        if row is None:
            return None
        param = self._row_to_param(row)

        variants = self._conn.execute(
            """SELECT backend FROM parameters
               WHERE vehicle = ? AND name = ? AND backend IS NOT NULL
               ORDER BY backend""",
            (vehicle, name),
        ).fetchall()
        if variants:
            param["backend_variants"] = [v["backend"] for v in variants]
        return param

    def search_parameters(
        self,
        query: str,
        vehicle: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """FTS5 keyword search over name/description/section/enum labels.

        `vehicle=None` searches every enabled Vehicle on the Roster (an
        explicit `vehicle=` always reaches its data regardless of enabled —
        see roster.py); a given `vehicle` hard-scopes to just that one.
        """
        if vehicle is not None:
            vehicle_filter_sql = "AND p.vehicle = ?"
            vehicle_params: tuple = (vehicle,)
        else:
            enabled = self._enabled_vehicles()
            if not enabled:
                return []
            placeholders = ",".join("?" * len(enabled))
            vehicle_filter_sql = f"AND p.vehicle IN ({placeholders})"
            vehicle_params = tuple(enabled)

        rows = self._conn.execute(
            f"""SELECT p.*, snippet(parameters_fts, 2, '[', ']', ' ... ', 12) AS snippet
                FROM parameters_fts
                JOIN parameters p ON p.id = parameters_fts.rowid
                WHERE parameters_fts MATCH ?{vehicle_filter_sql}
                ORDER BY rank
                LIMIT ?""",
            (query, *vehicle_params, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            p = self._row_to_param(r, include_values=False)
            p["snippet"] = r["snippet"]
            out.append(p)
        return out

    def semantic_search(
        self,
        query: str,
        vehicle: Optional[str] = None,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Vector search over parameter descriptions.

        `vehicle=None` searches every enabled Vehicle and dedups results by
        parameter name — the same parameter matching in several vehicles
        collapses into one result carrying a `vehicles` field, keeping the
        best (lowest-distance) match's data as the representative. A given
        `vehicle` hard-scopes to just that one, no dedup needed.
        """
        if vehicle is not None:
            hits = self._store.search(query, k=k, vehicles=[vehicle])
            return self._hits_to_params(hits)

        enabled = self._enabled_vehicles()
        if not enabled:
            return []
        hits = self._store.search(
            query, k=k * _SEMANTIC_SEARCH_OVERFETCH, vehicles=enabled
        )
        if not hits:
            return []

        best_by_name: dict[str, dict[str, Any]] = {}
        vehicles_by_name: dict[str, set] = defaultdict(set)
        for h in hits:
            name = h["name"]
            vehicles_by_name[name].add(h["vehicle"])
            if name not in best_by_name or h["_distance"] < best_by_name[name]["_distance"]:
                best_by_name[name] = h

        ranked = sorted(best_by_name.values(), key=lambda h: h["_distance"])[:k]
        return self._hits_to_params(ranked, vehicles_by_name=vehicles_by_name)

    def list_parameters(
        self,
        vehicle: str,
        prefix: Optional[str] = None,
        section: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Browse by name prefix and/or section, hard-scoped to `vehicle`.
        Excludes backend variants."""
        where = ["vehicle = ?", "backend IS NULL"]
        params: list[Any] = [vehicle]
        if prefix:
            where.append("name LIKE ? ESCAPE '\\'")
            safe_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"{safe_prefix}%")
        if section:
            where.append("LOWER(section) = LOWER(?)")
            params.append(section)
        params.append(limit)

        rows = self._conn.execute(
            f"""SELECT * FROM parameters
                WHERE {' AND '.join(where)}
                ORDER BY name
                LIMIT ?""",
            params,
        ).fetchall()
        return [self._row_to_param(r, include_values=False) for r in rows]

    def diff_parameter(
        self,
        name: str,
        vehicle_a: str,
        vehicle_b: str,
    ) -> dict[str, Any]:
        """Field-by-field diff of one parameter's main definition across
        two Vehicles (see docs/adr/0001-single-firmware-version-per-vehicle.md
        for why this compares vehicles rather than versions).

        `version_a`/`version_b` in the result are each side's stored
        firmware_version — provenance, not a query input — and
        `version_mismatch` flags when they differ, since a Vehicle Roster
        entry can pin a vehicle to an older version than another.
        """
        def _fetch(vehicle: str) -> Optional[dict[str, Any]]:
            row = self._conn.execute(
                """SELECT * FROM parameters
                   WHERE vehicle = ? AND name = ? AND backend IS NULL
                   LIMIT 1""",
                (vehicle, name),
            ).fetchone()
            return self._row_to_param(row) if row is not None else None

        a = _fetch(vehicle_a)
        b = _fetch(vehicle_b)

        version_a = a.get("firmware_version") if a is not None else None
        version_b = b.get("firmware_version") if b is not None else None

        result: dict[str, Any] = {
            "name": name,
            "vehicle_a": vehicle_a,
            "vehicle_b": vehicle_b,
            "exists_in_a": a is not None,
            "exists_in_b": b is not None,
            "version_a": version_a,
            "version_b": version_b,
            "version_mismatch": (
                a is not None and b is not None and version_a != version_b
            ),
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

        def _val_tuples(p: dict) -> list[tuple]:
            return [(v["value"], v["label"], v["is_bit"]) for v in p.get("values", [])]

        if _val_tuples(a) != _val_tuples(b):
            result["differences"].append({
                "field": "values",
                "version_a": a.get("values"),
                "version_b": b.get("values"),
            })

        return result
