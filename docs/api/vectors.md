# vectors

LanceDB-backed semantic search over parameter passages, embedded with `intfloat/multilingual-e5-small` on onnxruntime.

## Overview

One LanceDB table (`parameters`) holds every vehicle's vectors, keyed by `(vehicle, name)` — never by SQLite row id,
which changes on every re-ingest. Rebuilding a vehicle replaces only that vehicle's slice. The model is the
upstream repo's fp32 ONNX export, downloaded on first use into `data/model-cache/`, and run directly rather than
through sentence-transformers ([ADR 0004](../adr/0004-onnx-embeddings.md)).

e5 needs task prefixes: passages are embedded as `"passage: {text}"`, queries as `"query: {text}"`. Skipping them
silently degrades retrieval. Vectors are mean-pooled and L2-normalised, so LanceDB's default L2 distance ranks the
same as cosine.

## Public API

### Constants

```python
DEFAULT_VECTORS_PATH      # <repo>/data/vectors.lance
DEFAULT_MODEL_CACHE_PATH  # <repo>/data/model-cache
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384
TABLE_NAME = "parameters"
Encoder = Callable[[list[str]], list[list[float]]]
```

`Encoder` is the injectable replacement for the real model, used by tests (`encoder=` on `rebuild`, `search`,
`rebuild_from_db`). An injected encoder receives texts without e5 prefixes.

### compose_passage

```python
def compose_passage(name: str, display_name: str | None, description: str | None, section: str | None,
                    is_bitmask: bool, values: Iterable[tuple[str, str]]) -> str
```

Builds the text embedded for one parameter:
`NAME: Display Name (Section: S). Description. Values: 0=Disabled, 1=Enabled` (or `Bits:` for bitmasks). Only the
first 15 values are rendered, followed by `, ...(+N more)`.

### E5OnnxModel

```python
class E5OnnxModel:
    def __init__(self, model_name: str, cache_folder: Path) -> None
    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray
```

Downloads `onnx/model.onnx` and `onnx/tokenizer.json` from the Hugging Face repo `model_name` into `cache_folder` (cached
after the first call), and runs them on the CPU execution provider. `encode` tokenizes with truncation at 512 tokens
and padding, takes `last_hidden_state`, mean-pools over the attention mask and L2-normalises. Returns an
`(len(texts), 384)` float32 array; an empty input returns shape `(0, 384)`. Does not add e5 prefixes.

### VectorStore

```python
class VectorStore:
    def __init__(self, path=DEFAULT_VECTORS_PATH, model_name: str = DEFAULT_MODEL,
                 model_cache_path=DEFAULT_MODEL_CACHE_PATH) -> None
```

Opens (creating directories if needed) the LanceDB database at `path`. The model loads lazily through the `model`
property, on the first encode.

#### rebuild

```python
def rebuild(self, rows: list[dict[str, Any]], vehicle: str, encoder: Encoder | None = None) -> int
```

Replaces `vehicle`'s slice of the index. Each row needs `name`, `vehicle`, `firmware_version`, `text`; all must belong
to `vehicle`. `text` is embedded (with the `passage:` prefix when using the real model) and not stored. An empty
`rows` deletes the vehicle's slice. If it finds a legacy table keyed by `param_id`, it drops the whole table and
prints a stderr notice to rebuild every vehicle. Returns the number of vectors written.

#### search

```python
def search(self, query: str, k: int = 5, vehicles: Sequence[str] | None = None,
           encoder: Encoder | None = None) -> list[dict[str, Any]]
```

Top-`k` nearest passages, optionally restricted to `vehicles`. Each hit has `name`, `vehicle`, `firmware_version`,
`vector` and `_distance`. Returns `[]` if no index exists yet.

### rebuild_from_db

```python
def rebuild_from_db(store: VectorStore, vehicle: str, db_path=DEFAULT_DB_PATH,
                    encoder: Encoder | None = None, verbose: bool = False) -> int
```

Reads `vehicle`'s main definitions (backend variants skipped) and their values from SQLite, composes passages, and
calls `store.rebuild`. Raises `ValueError` if the vehicle has never been ingested. Returns the vector count.

## Usage examples

```python
from ardupilot_mcp.vectors import VectorStore, rebuild_from_db

store = VectorStore()
rebuild_from_db(store, "plane", verbose=True)
for hit in store.search("compass calibration", k=3, vehicles=["plane"]):
    print(hit["name"], hit["_distance"])
```

## Dependencies

- `lancedb`, `pyarrow`, `numpy`; `onnxruntime`, `tokenizers`, `huggingface-hub` (imported only when the model loads).
- [db](db.md) for `rebuild_from_db`.
