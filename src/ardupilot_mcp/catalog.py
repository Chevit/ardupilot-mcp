"""ParameterCatalog — the single seam through which a firmware version's
parameters are looked up, keyword-searched, semantically searched, browsed,
and diffed. See CONTEXT.md for the ParameterCatalog definition.

Holds one persistent SQLite connection for its process lifetime (safe under
FastMCP's single-threaded, run-to-completion sync tool calls — no locking
needed) and one VectorStore, whose embedding model still loads lazily on
first semantic_search call.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .db import DEFAULT_DB_PATH, list_versions as _list_versions_db, open_connection
from .vectors import DEFAULT_MODEL_CACHE_PATH, DEFAULT_VECTORS_PATH, VectorStore


class ParameterCatalog:
    """Read-side seam over SQLite parameter storage and the semantic VectorStore."""

    def __init__(
        self,
        db_path=DEFAULT_DB_PATH,
        vectors_path=DEFAULT_VECTORS_PATH,
        model_cache_path=DEFAULT_MODEL_CACHE_PATH,
    ) -> None:
        self._conn: sqlite3.Connection = open_connection(db_path)
        self._store = VectorStore(path=vectors_path, model_cache_path=model_cache_path)

    def close(self) -> None:
        """Close the held SQLite connection. The VectorStore's LanceDB handle
        and (if loaded) embedding model are released with the process."""
        self._conn.close()

    # -- internals -- #

    def _latest_version(self, vehicle: str) -> Optional[str]:
        versions = _list_versions_db(self._conn, vehicle)
        return versions[-1] if versions else None

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

    # -- public interface -- #

    def list_versions(self, vehicle: str = "plane") -> list[str]:
        """Firmware versions ingested for a vehicle, ascending."""
        return _list_versions_db(self._conn, vehicle)

    def lookup_parameter(
        self,
        name: str,
        firmware_version: Optional[str] = None,
        vehicle: str = "plane",
    ) -> Optional[dict[str, Any]]:
        """Exact-name lookup. Omit firmware_version for the latest. None if not found."""
        if firmware_version is None:
            firmware_version = self._latest_version(vehicle)
            if firmware_version is None:
                return None
        row = self._conn.execute(
            """SELECT * FROM parameters
               WHERE vehicle = ? AND firmware_version = ? AND name = ?
               ORDER BY (backend IS NULL) DESC
               LIMIT 1""",
            (vehicle, firmware_version, name),
        ).fetchone()
        if row is None:
            return None
        param = self._row_to_param(row)

        variants = self._conn.execute(
            """SELECT backend FROM parameters
               WHERE vehicle = ? AND firmware_version = ? AND name = ?
                 AND backend IS NOT NULL
               ORDER BY backend""",
            (vehicle, firmware_version, name),
        ).fetchall()
        if variants:
            param["backend_variants"] = [v["backend"] for v in variants]
        return param

    def search_parameters(
        self,
        query: str,
        firmware_version: Optional[str] = None,
        limit: int = 10,
        vehicle: str = "plane",
    ) -> list[dict[str, Any]]:
        """FTS5 keyword search over name/description/section/enum labels."""
        fw_filter_sql = ""
        fw_params: tuple = ()
        if firmware_version is not None:
            fw_filter_sql = " AND p.firmware_version = ?"
            fw_params = (firmware_version,)

        rows = self._conn.execute(
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
            p = self._row_to_param(r, include_values=False)
            p["snippet"] = r["snippet"]
            out.append(p)
        return out

    def semantic_search(
        self,
        query: str,
        k: int = 5,
        vehicle: str = "plane",
    ) -> list[dict[str, Any]]:
        """Vector search over the latest firmware version's descriptions."""
        fw = self._latest_version(vehicle)
        if fw is None:
            return []
        hits = self._store.search(query, k=k, firmware_version=fw)
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
            out.append(p)
        return out

    def list_parameters(
        self,
        prefix: Optional[str] = None,
        section: Optional[str] = None,
        firmware_version: Optional[str] = None,
        vehicle: str = "plane",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Browse by name prefix and/or section. Excludes backend variants."""
        if firmware_version is None:
            firmware_version = self._latest_version(vehicle)
            if firmware_version is None:
                return []

        where = ["vehicle = ?", "firmware_version = ?", "backend IS NULL"]
        params: list[Any] = [vehicle, firmware_version]
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
        version_a: str,
        version_b: str,
        vehicle: str = "plane",
    ) -> dict[str, Any]:
        """Field-by-field diff of one parameter's main definition across two versions."""
        def _fetch(fw: str) -> Optional[dict[str, Any]]:
            row = self._conn.execute(
                """SELECT * FROM parameters
                   WHERE vehicle = ? AND firmware_version = ? AND name = ?
                     AND backend IS NULL
                   LIMIT 1""",
                (vehicle, fw, name),
            ).fetchone()
            return self._row_to_param(row) if row is not None else None

        a = _fetch(version_a)
        b = _fetch(version_b)

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

        def _val_tuples(p: dict) -> list[tuple]:
            return [(v["value"], v["label"], v["is_bit"]) for v in p.get("values", [])]

        if _val_tuples(a) != _val_tuples(b):
            result["differences"].append({
                "field": "values",
                "version_a": a.get("values"),
                "version_b": b.get("values"),
            })

        return result
