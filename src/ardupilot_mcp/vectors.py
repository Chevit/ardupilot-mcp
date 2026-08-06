"""Semantic search layer.

Embeds parameter descriptions with `intfloat/multilingual-e5-small` (384-dim,
~120 MB, multilingual including Ukrainian) and stores them in LanceDB.

The vector table holds ONE firmware version at a time. Rebuilding replaces
the table entirely. This matches the design decision to only semantic-index
the latest ArduPilot version — FTS in SQLite covers older versions for
exact/keyword lookups.

Note on e5 models: they require task-specific prefixes for correct behaviour.
  - passages being indexed:  "passage: {text}"
  - queries at search time:  "query: {text}"
Skipping the prefixes silently degrades retrieval quality.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, TYPE_CHECKING

import lancedb
import pyarrow as pa

from .db import DEFAULT_DB_PATH, connect, list_versions

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
        encoder: Optional[Encoder] = None,
    ) -> int:
        """Drop the current table (if any) and reindex from scratch.

        Each input row must contain:
            param_id (int), name (str), vehicle (str),
            firmware_version (str), text (str)

        `text` is what gets embedded and is NOT retained after this call.
        If `encoder` is None, the real e5 model is used.
        """
        if not rows:
            if TABLE_NAME in self._db.table_names():
                self._db.drop_table(TABLE_NAME)
            return 0

        texts = [r["text"] for r in rows]
        if encoder is None:
            vectors = self._encode_passages(texts)
        else:
            vectors = encoder(texts)

        records: list[dict[str, Any]] = []
        for r, v in zip(rows, vectors):
            records.append({
                "param_id": int(r["param_id"]),
                "name": r["name"],
                "vehicle": r["vehicle"],
                "firmware_version": r["firmware_version"],
                "vector": v,
            })

        schema = pa.schema([
            ("param_id",         pa.int64()),
            ("name",             pa.string()),
            ("vehicle",          pa.string()),
            ("firmware_version", pa.string()),
            ("vector",           pa.list_(pa.float32(), EMBEDDING_DIM)),
        ])

        if TABLE_NAME in self._db.table_names():
            self._db.drop_table(TABLE_NAME)
        self._db.create_table(TABLE_NAME, data=records, schema=schema)
        return len(records)

    # -- querying -- #
    def search(
        self,
        query: str,
        k: int = 5,
        firmware_version: Optional[str] = None,
        encoder: Optional[Encoder] = None,
    ) -> list[dict[str, Any]]:
        """Return the top-k passages nearest to `query`.

        Each result is a dict with `param_id`, `name`, `vehicle`,
        `firmware_version`, and `_distance` (LanceDB's cosine distance).
        """
        if TABLE_NAME not in self._db.table_names():
            return []
        table = self._db.open_table(TABLE_NAME)

        if encoder is None:
            qvec = self._encode_queries([query])[0]
        else:
            qvec = encoder([query])[0]

        q = table.search(qvec).limit(k)
        if firmware_version:
            # LanceDB uses SQL-style where clauses. Single quotes for strings.
            q = q.where(f"firmware_version = '{firmware_version}'")
        return q.to_list()


# --------------------------------------------------------------------------- #
# Rebuild from SQLite                                                         #
# --------------------------------------------------------------------------- #

def rebuild_from_db(
    store: VectorStore,
    db_path=DEFAULT_DB_PATH,
    vehicle: str = "plane",
    firmware_version: Optional[str] = None,
    encoder: Optional[Encoder] = None,
    verbose: bool = False,
) -> int:
    """(Re)build the vector index from SQLite.

    If `firmware_version` is None, uses the highest version present for
    the vehicle (lexicographic sort — works for semver-like strings).
    """
    with connect(db_path) as conn:
        if firmware_version is None:
            versions = list_versions(conn, vehicle)
            if not versions:
                raise ValueError(f"No firmware versions ingested for {vehicle!r}")
            firmware_version = versions[-1]

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
    n = store.rebuild(rows, encoder=encoder)
    if verbose:
        print(f"[vectors] wrote {n} vectors -> {store.path}", file=sys.stderr)
    return n
