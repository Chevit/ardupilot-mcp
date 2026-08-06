"""Semantic search layer.

Embeds parameter descriptions with `intfloat/multilingual-e5-small` (384-dim,
~120 MB, multilingual including Ukrainian) and stores them in LanceDB.

The vector table holds every Vehicle at once, one firmware version per
Vehicle (see docs/adr/0001-single-firmware-version-per-vehicle.md).
Rebuilding a Vehicle replaces only that Vehicle's rows, leaving the rest of
the table intact — see rebuild().

Note on e5 models: they require task-specific prefixes for correct behaviour.
  - passages being indexed:  "passage: {text}"
  - queries at search time:  "query: {text}"
Skipping the prefixes silently degrades retrieval quality.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, TYPE_CHECKING

import lancedb
import pyarrow as pa

from .db import DEFAULT_DB_PATH, connect, ingested_version

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


DEFAULT_VECTORS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "vectors.lance"
)
DEFAULT_MODEL_CACHE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "model-cache"
)
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384
TABLE_NAME = "parameters"

# Type of an encoder callable: takes a list of strings, returns matching vectors.
Encoder = Callable[[list[str]], list[list[float]]]


# --------------------------------------------------------------------------- #
# Passage composition                                                         #
# --------------------------------------------------------------------------- #

def compose_passage(
    name: str,
    display_name: Optional[str],
    description: Optional[str],
    section: Optional[str],
    is_bitmask: bool,
    values: Iterable[tuple[str, str]],
) -> str:
    """Build the text that gets embedded for a single parameter.

    Format:
        NAME: Display Name (Section: Group Parameters). Description text.
        Values: 0=Disabled, 1=Enabled, ...

    Values are truncated to the first 15 for very long bitmasks.
    """
    parts: list[str] = [name]
    if display_name:
        parts.append(f": {display_name}")
    if section:
        parts.append(f" (Section: {section})")
    parts.append(".")
    if description:
        parts.append(f" {description}")
    values_list = list(values)
    if values_list:
        kind = "Bits" if is_bitmask else "Values"
        head = values_list[:15]
        rendered = ", ".join(f"{v}={label}" for v, label in head)
        parts.append(f" {kind}: {rendered}")
        if len(values_list) > 15:
            parts.append(f", ...(+{len(values_list) - 15} more)")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# The vector store                                                            #
# --------------------------------------------------------------------------- #

class VectorStore:
    """LanceDB-backed vector store for parameter passages."""

    def __init__(
        self,
        path=DEFAULT_VECTORS_PATH,
        model_name: str = DEFAULT_MODEL,
        model_cache_path=DEFAULT_MODEL_CACHE_PATH,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.model_cache_path = Path(model_cache_path)
        self.model_cache_path.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name
        self._model: Optional["SentenceTransformer"] = None
        self._db = lancedb.connect(str(self.path))

    def _has_table(self) -> bool:
        return TABLE_NAME in self._db.list_tables().tables

    @staticmethod
    def _sql_quote(value: str) -> str:
        """Escape a value for embedding in a LanceDB SQL-style filter string."""
        return value.replace("'", "''")

    # -- model management (lazy) -- #
    @property
    def model(self) -> "SentenceTransformer":
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                self.model_name,
                cache_folder=str(self.model_cache_path),
            )
        return self._model

    def _encode_passages(self, texts: list[str]) -> list[list[float]]:
        """Encode passages for indexing, with the e5 'passage:' prefix."""
        prefixed = ["passage: " + t for t in texts]
        arr = self.model.encode(
            prefixed, batch_size=64, show_progress_bar=False, convert_to_numpy=True
        )
        return [row.tolist() for row in arr]

    def _encode_queries(self, texts: list[str]) -> list[list[float]]:
        """Encode queries for search, with the e5 'query:' prefix."""
        prefixed = ["query: " + t for t in texts]
        arr = self.model.encode(
            prefixed, batch_size=64, show_progress_bar=False, convert_to_numpy=True
        )
        return [row.tolist() for row in arr]

    # -- indexing -- #
    def rebuild(
        self,
        rows: list[dict[str, Any]],
        vehicle: str,
        encoder: Optional[Encoder] = None,
    ) -> int:
        """Replace one vehicle's slice of the index; every other vehicle's
        rows are left untouched.

        Each input row must contain:
            param_id (int), name (str), vehicle (str),
            firmware_version (str), text (str)
        All rows must belong to `vehicle` — this is a per-vehicle replace,
        not a general-purpose bulk load.

        `text` is what gets embedded and is NOT retained after this call.
        If `encoder` is None, the real e5 model is used.
        """
        schema = pa.schema([
            ("param_id",         pa.int64()),
            ("name",             pa.string()),
            ("vehicle",          pa.string()),
            ("firmware_version", pa.string()),
            ("vector",           pa.list_(pa.float32(), EMBEDDING_DIM)),
        ])

        records: list[dict[str, Any]] = []
        if rows:
            texts = [r["text"] for r in rows]
            vectors = self._encode_passages(texts) if encoder is None else encoder(texts)
            for r, v in zip(rows, vectors):
                records.append({
                    "param_id": int(r["param_id"]),
                    "name": r["name"],
                    "vehicle": r["vehicle"],
                    "firmware_version": r["firmware_version"],
                    "vector": v,
                })

        if self._has_table():
            table = self._db.open_table(TABLE_NAME)
            table.delete(f"vehicle = '{self._sql_quote(vehicle)}'")
            if records:
                table.add(records)
        elif records:
            self._db.create_table(TABLE_NAME, data=records, schema=schema)
        # else: no table yet and nothing to add — nothing to do.

        return len(records)

    # -- querying -- #
    def search(
        self,
        query: str,
        k: int = 5,
        vehicles: Optional[Sequence[str]] = None,
        encoder: Optional[Encoder] = None,
    ) -> list[dict[str, Any]]:
        """Return the top-k passages nearest to `query`.

        `vehicles`: restrict to these vehicle names, or None to search
        every vehicle present in the index.

        Each result is a dict with `param_id`, `name`, `vehicle`,
        `firmware_version`, and `_distance` (LanceDB's cosine distance).
        """
        if not self._has_table():
            return []
        table = self._db.open_table(TABLE_NAME)

        if encoder is None:
            qvec = self._encode_queries([query])[0]
        else:
            qvec = encoder([query])[0]

        q = table.search(qvec).limit(k)
        if vehicles is not None:
            quoted = ", ".join(f"'{self._sql_quote(v)}'" for v in vehicles)
            q = q.where(f"vehicle IN ({quoted})")
        return q.to_list()


# --------------------------------------------------------------------------- #
# Rebuild from SQLite                                                         #
# --------------------------------------------------------------------------- #

def rebuild_from_db(
    store: VectorStore,
    vehicle: str,
    db_path=DEFAULT_DB_PATH,
    encoder: Optional[Encoder] = None,
    verbose: bool = False,
) -> int:
    """(Re)build one vehicle's slice of the vector index from SQLite.

    Only `vehicle`'s rows in the index are replaced — every other vehicle's
    vectors are left untouched (VectorStore.rebuild()). Uses whatever
    firmware_version is currently stored for `vehicle` — there is exactly
    one per docs/adr/0001-single-firmware-version-per-vehicle.md.
    """
    with connect(db_path) as conn:
        firmware_version = ingested_version(conn, vehicle)
        if firmware_version is None:
            raise ValueError(f"{vehicle!r} has not been ingested")

        param_rows = conn.execute(
            """SELECT id, vehicle, firmware_version, name,
                      display_name, description, section, is_bitmask
               FROM parameters
               WHERE vehicle = ? AND firmware_version = ?
                 AND backend IS NULL          -- skip driver variants for now
               ORDER BY id""",
            (vehicle, firmware_version),
        ).fetchall()

        value_rows = conn.execute(
            """SELECT pv.parameter_id, pv.value, pv.label
               FROM parameter_values pv
               JOIN parameters p ON p.id = pv.parameter_id
               WHERE p.vehicle = ? AND p.firmware_version = ?
                 AND p.backend IS NULL
               ORDER BY pv.id""",
            (vehicle, firmware_version),
        ).fetchall()

    values_by_pid: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for r in value_rows:
        values_by_pid[r["parameter_id"]].append((r["value"], r["label"]))

    rows: list[dict[str, Any]] = []
    for p in param_rows:
        text = compose_passage(
            name=p["name"],
            display_name=p["display_name"],
            description=p["description"],
            section=p["section"],
            is_bitmask=bool(p["is_bitmask"]),
            values=values_by_pid.get(p["id"], []),
        )
        rows.append({
            "param_id": p["id"],
            "name": p["name"],
            "vehicle": p["vehicle"],
            "firmware_version": p["firmware_version"],
            "text": text,
        })

    if verbose:
        print(
            f"[vectors] embedding {len(rows)} passages "
            f"({vehicle} {firmware_version}) with {store.model_name}",
            file=sys.stderr,
        )
    n = store.rebuild(rows, vehicle=vehicle, encoder=encoder)
    if verbose:
        print(f"[vectors] wrote {n} vectors -> {store.path}", file=sys.stderr)
    return n
