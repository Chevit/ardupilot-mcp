# server

MCP server exposing ArduPilot parameter Q&A as six tools over stdio or streamable HTTP.

## Overview

`server.py` builds one `mcp.server.mcpserver.MCPServer` named `ardupilot-docs` and registers six tools, each a thin
delegate to a lazily created [`ParameterCatalog`](catalog.md). The catalog (and its SQLite connection) opens on the
first tool call; the embedding model loads later still, on the first `semantic_search`.

The tools are `async def` even though none of them awaits. The MCP SDK (2.x) runs sync tools in a worker-thread pool,
and the catalog's single SQLite connection must stay on one thread. `async def` makes the SDK run them one at a time
on the event-loop thread.

`vehicle` has no default anywhere. `search_parameters` and `semantic_search` accept `vehicle=None` (omitted), meaning
"every enabled vehicle on the [Vehicle Roster](roster.md)". The other tools require an explicit vehicle.

## Public API

### MCP tools

Each tool returns JSON-serialisable dicts. Parameter dicts share the shape produced by `ParameterCatalog`: `id`,
`name`, `vehicle`, `firmware_version`, `backend`, `display_name`, `description`, `section`, `units`,
`range` (`{"min", "max"}` or `null`), `increment`, `is_bitmask`, `read_only`, `advanced`, `source_url`, and, where
noted, `values` (`[{"value", "label", "is_bit"}]`).

#### list_vehicles

```python
async def list_vehicles() -> list[dict[str, Any]]
```

Every vehicle on the Roster, sorted by name, as `{"vehicle", "enabled", "ingested_version"}`. `ingested_version` is
the firmware version currently stored, or `null` if the vehicle has never been ingested. Clients call this to learn
valid `vehicle` values.

#### lookup_parameter

```python
async def lookup_parameter(name: str, vehicle: str) -> dict[str, Any] | None
```

Exact-name lookup (case-insensitive), hard-scoped to `vehicle`. Returns the main definition (`backend IS NULL`
preferred) including `values`. If driver variants exist, adds `backend_variants: [str]`. Returns `None` if not found,
including for an unknown vehicle.

#### search_parameters

```python
async def search_parameters(query: str, vehicle: str | None = None, limit: int = 10) -> list[dict[str, Any]]
```

SQLite FTS5 keyword search over name, display name, description, enum/bit labels, section and backend. Each result
carries a `snippet` with matches in `[...]`; no `values`. `query` is first tried as raw FTS5 syntax; if FTS5 rejects
it, its word tokens are re-run quoted and OR-joined, ranked by bm25. A query with no word tokens returns `[]`.

#### semantic_search

```python
async def semantic_search(query: str, vehicle: str | None = None, k: int = 5) -> list[dict[str, Any]]
```

Vector search with multilingual e5 embeddings (see [vectors](vectors.md)). Each result carries `distance` (lower is
closer); no `values`. With `vehicle=None`, over-fetches `4 * k` candidates across enabled vehicles and collapses
same-named matches into one result with a `vehicles: [str]` list, so the returned count is approximately `k`.

#### list_parameters

```python
async def list_parameters(vehicle: str, prefix: str | None = None, section: str | None = None,
                          limit: int = 50) -> list[dict[str, Any]]
```

Browse `vehicle`'s main definitions (backend variants excluded), sorted by name. `prefix` is a literal name prefix
(`%`, `_` and `\` are escaped); `section` matches case-insensitively. No `values`.

#### diff_parameter

```python
async def diff_parameter(name: str, vehicle_a: str, vehicle_b: str) -> dict[str, Any]
```

Field-by-field comparison of one parameter's main definition across two vehicles. Returns `name`, `vehicle_a`,
`vehicle_b`, `exists_in_a`, `exists_in_b`, and `differences: [{"field", "value_a", "value_b"}]`. Compared fields:
`description`, `section`, `units`, `range`, `increment`, `is_bitmask`, `read_only`, `advanced`, `display_name`,
`values`. If either side is missing, `differences` is empty. Assumes both vehicles are at the same firmware version
([ADR 0003](../adr/0003-diff-assumes-one-shared-firmware-version.md)).

### main

```python
def main() -> None
```

Console-script entry point (`ardupilot-mcp`). Reads the transport from the environment and runs the server:

| Variable        | Values                               | Default |
|-----------------|--------------------------------------|---------|
| `MCP_TRANSPORT` | `stdio`, `streamable-http`           | `stdio` |
| `MCP_HTTP_PORT` | integer port (HTTP mode only)        | `8000`  |

In HTTP mode it binds `0.0.0.0` (required for Docker port publishing) and serves at `/mcp`. An unknown
`MCP_TRANSPORT` raises `ValueError`. There is no built-in authentication.

## Usage examples

```bash
# stdio, for Claude Desktop / Claude Code on the same machine
uv run ardupilot-mcp

# streamable HTTP on port 9000
MCP_TRANSPORT=streamable-http MCP_HTTP_PORT=9000 uv run ardupilot-mcp
```

```python
import asyncio
from ardupilot_mcp import server

result = asyncio.run(server.mcp.call_tool("lookup_parameter", {"name": "RTL_ALTITUDE", "vehicle": "plane"}))
```

## Dependencies

- `mcp` 2.x (`MCPServer`).
- [catalog](catalog.md) for every query.
