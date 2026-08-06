# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repo.

## What this is

MCP server exposing ArduPilot parameter Q&A (keyword + semantic search) over a local
SQLite + LanceDB store, scraped from ArduPilot's Sphinx-generated HTML parameter docs.

## Commands

Package manager is `uv`. No dedicated test suite exists yet.

```bash
# Run the MCP server (stdio transport, for manual testing / Claude Desktop)
uv run python -m ardupilot_mcp.server

# Ingest every enabled vehicle on the Vehicle Roster in one call — vehicle
# and firmware version are auto-detected per vehicle, vectors rebuilt once
# at the end covering every vehicle that succeeded
uv run python -m ardupilot_mcp.ingest --all --build-vectors

# Or ingest a single vehicle by fetching directly from ardupilot.org
uv run python -m ardupilot_mcp.ingest \
    --url https://ardupilot.org/copter/docs/parameters.html \
    --build-vectors

# Or from a locally saved HTML file
uv run python -m ardupilot_mcp.ingest \
    --html "data/ardupilot-docs/Complete Parameter List — Plane documentation 4.8.0.html" \
    --vehicle plane \
    --firmware-version 4.8.0 \
    --source-url https://ardupilot.org/plane/docs/parameters.html \
    --build-vectors   # optional: also rebuild the semantic index for this vehicle
```

Each vehicle stores exactly one firmware version at a time; re-ingesting a vehicle replaces its
rows wholesale (see "Gotchas" and `docs/adr/0001-single-firmware-version-per-vehicle.md`). Which
vehicles exist, their URLs, and whether `--all` fetches them is the **Vehicle Roster**
(`src/ardupilot_mcp/vehicles.json`, overridable via `data/vehicles.json` or `--vehicles-config` —
see `docs/adr/0002-vehicle-roster-owns-the-vehicle-list.md`).

Console script entry points (`pyproject.toml`): `ardupilot-mcp` → `server:main`,
`ardupilot-refresh` → `ingest:main` (note: *not* `scripts/refresh.py`, which is unused).

## Docker

Alternative to the local `uv` workflow above — builds the same console
scripts into an image, runs via `docker compose`. See
`docs/superpowers/specs/2026-08-06-docker-compose-launch-design.md` for the
full design rationale.

```bash
# Build the image (both services share it)
docker compose build

# Ingest through the container instead of a host uv environment — same
# CLI, same flags as the "Commands" section above, writes into the
# bind-mounted ./data
docker compose run --rm mcp-stdio ardupilot-refresh --all --build-vectors

# Or a single vehicle:
docker compose run --rm mcp-stdio ardupilot-refresh \
    --url https://ardupilot.org/copter/docs/parameters.html \
    --build-vectors

# data/vehicles.json (bind-mounted) overrides the packaged Vehicle Roster —
# edit it there to change a vehicle's URL, pin an older version, or
# enable/disable a vehicle for --all.
```

**Local stdio client** (Claude Desktop/Code on the same machine as the
Docker host) — point the client's MCP server command at compose, run from
the repo root:

```json
{
  "mcpServers": {
    "ardupilot": {
      "command": "docker",
      "args": ["compose", "-f", "/path/to/ardupilot-mcp/docker-compose.yml", "run", "--rm", "mcp-stdio"]
    }
  }
}
```

Prefer `-f <absolute-path>` over a `cwd` field — not all MCP clients honor `cwd`, and
without it `docker compose` fails with `no configuration file provided: not found`
because it can't find `docker-compose.yml`. `-f` works regardless of the client's
working directory.

**Remote HTTP client** (Claude client on a different machine than the
Docker host) — start the long-running service on the host that has the
data:

```bash
docker compose up -d mcp-http
```

Then point the remote client at `http://<docker-host>:8000/mcp`. No
app-level auth is built in — only expose `mcp-http` on a trusted network,
VPN, or behind a reverse proxy that adds auth.

## Architecture

- `roster.py` — loads the Vehicle Roster (`vehicles.json`, packaged; overridable via
  `data/vehicles.json` or `--vehicles-config`): the authoritative list of which vehicles exist,
  their source URLs, and whether `--all` fetches them. See
  `docs/adr/0002-vehicle-roster-owns-the-vehicle-list.md`.
- `db.py` — SQLite schema + query layer. `parameters` + `parameter_values` tables,
  FTS5 virtual table for keyword search. Unique key: `(vehicle, name, backend)` — one firmware
  version stored per vehicle at a time; `firmware_version` is a provenance column, not part of
  the key. See `docs/adr/0001-single-firmware-version-per-vehicle.md`.
- `scraper.py` — parses Sphinx-generated ArduPilot parameter HTML into `Parameter` records.
- `ingest.py` — orchestrates scrape → SQLite write → optional vector rebuild. CLI entry point.
  `--all` loops the Roster's enabled vehicles, continuing past a failed one, and rebuilds vectors
  once at the end (not once per vehicle — avoids reloading the embedding model repeatedly).
- `vectors.py` — LanceDB-backed semantic search layer using `intfloat/multilingual-e5-small`.
  One table holds every vehicle; `rebuild()` replaces only the given vehicle's slice.
- `catalog.py` — the seam through which all six tools query SQLite + the vector store + the
  Vehicle Roster.
- `server.py` — FastMCP server exposing the tools: `list_vehicles`, `lookup_parameter`,
  `search_parameters` (FTS5), `semantic_search` (vectors), `list_parameters`, `diff_parameter`.
  `vehicle` has no default anywhere.

## Gotchas

- **e5 embedding prefixes**: queries must be encoded as `"query: {text}"`, indexed passages
  as `"passage: {text}"`. Skipping the prefix silently degrades retrieval quality — no error.
- **Backend variants**: a parameter can have multiple rows differing by `backend` (e.g. driver
  variants). The main definition is `backend IS NULL`; lookups prefer it via
  `ORDER BY (backend IS NULL) DESC`.
- **One firmware version per vehicle** — re-ingesting a vehicle replaces its rows wholesale,
  regardless of whether the firmware_version changed. There is no cross-version diffing anymore;
  `diff_parameter` compares two *vehicles* instead.
- **`vehicle=None` is a real, different thing from "no vehicle passed"** — only
  `search_parameters`/`semantic_search` accept it, meaning "every enabled vehicle on the Roster".
  `lookup_parameter`/`list_parameters`/`diff_parameter` require an explicit vehicle string; there
  is no default.
- **`enabled: false` on the Roster only affects `--all`** — an explicit `--vehicle blimp` ingest,
  or an explicit `vehicle="blimp"` query, still works. Only the unscoped `vehicle=None` search
  tools skip disabled vehicles.
- **Semantic `vehicle=None` dedups by parameter name** — over-fetches `k * 4` candidates across
  enabled vehicles, then collapses same-named matches into one result carrying a `vehicles` list,
  so the returned count is an approximate `k`, not exact.

## Data bootstrap

`data/` is entirely gitignored — a fresh clone has no SQLite DB, no vector index, and no
source HTML. To rebuild from scratch, run `ardupilot-refresh --all --build-vectors` (see
Commands above) — it fetches every enabled vehicle on the Vehicle Roster directly from
ardupilot.org. For a single vehicle or a page not on the Roster, pass `--url` instead.

## Conventions

No linter/formatter is configured. Match the existing style: `from __future__ import
annotations`, Google-style docstrings with `Args:`, dataclasses for records, modern union
typing (`X | None`).
