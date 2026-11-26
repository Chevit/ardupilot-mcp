# catalog

`ParameterCatalog`: the single read-side seam over SQLite, the vector store and the Vehicle Roster.

## Overview

Every MCP tool in [server](server.md) delegates to one `ParameterCatalog`. It holds one persistent SQLite connection
for the process lifetime, one [`VectorStore`](vectors.md), and the loaded [Vehicle Roster](roster.md), which decides
which vehicles an unscoped (`vehicle=None`) search covers. The connection is not thread-safe; it is safe here only
because the server runs tools one at a time on the event-loop thread.

## Public API

### ParameterCatalog

```python
class ParameterCatalog:
    def __init__(self, db_path=DEFAULT_DB_PATH, vectors_path=DEFAULT_VECTORS_PATH,
                 model_cache_path=DEFAULT_MODEL_CACHE_PATH, vehicles_config: Path | None = None) -> None
```

Creates the SQLite schema if missing (so a never-ingested store answers with empty results rather than "no such
table"), opens the connection, constructs the `VectorStore`, and loads the Roster (`vehicles_config` overrides the
lookup order described in [roster](roster.md)).

#### close

```python
def close(self) -> None
```

Closes the SQLite connection. The LanceDB handle and any loaded model are released with the process.

#### list_vehicles / lookup_parameter / search_parameters / semantic_search / list_parameters / diff_parameter

```python
def list_vehicles(self) -> list[dict[str, Any]]
def lookup_parameter(self, name: str, vehicle: str) -> dict[str, Any] | None
def search_parameters(self, query: str, vehicle: str | None = None, limit: int = 10) -> list[dict[str, Any]]
def semantic_search(self, query: str, vehicle: str | None = None, k: int = 5) -> list[dict[str, Any]]
def list_parameters(self, vehicle: str, prefix: str | None = None, section: str | None = None,
                    limit: int = 50) -> list[dict[str, Any]]
def diff_parameter(self, name: str, vehicle_a: str, vehicle_b: str) -> dict[str, Any]
```

Same semantics and return shapes as the MCP tools of the same name — see [server](server.md#mcp-tools). Details
that live here:

- `lookup_parameter` and `diff_parameter` upper-case `name` before matching.
- `search_parameters` catches `sqlite3.OperationalError` from invalid FTS5 syntax and retries with OR-joined quoted
  tokens; other errors propagate.
- `semantic_search` joins vector hits back to SQLite on `(vehicle, name)`, never on row id (ids change on every
  re-ingest). A hit whose parameter no longer exists in SQLite is silently dropped. With `vehicle=None`, the
  lowest-distance match for each name is the representative.
- An enabled-vehicle list that is empty makes both search methods return `[]`.

## Usage examples

```python
from ardupilot_mcp.catalog import ParameterCatalog

cat = ParameterCatalog()
try:
    print(cat.lookup_parameter("rtl_altitude", "plane")["units"])
    for hit in cat.semantic_search("return home when battery is low", k=3):
        print(hit["name"], hit["vehicles"], hit["distance"])
finally:
    cat.close()
```

## Dependencies

- [db](db.md) for the schema and connection, [vectors](vectors.md) for semantic search, [roster](roster.md) for
  vehicle names.
