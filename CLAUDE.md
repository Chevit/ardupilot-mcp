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

# Ingest a firmware version's parameter HTML into SQLite
uv run python -m ardupilot_mcp.ingest \
    --html "data/ardupilot-docs/Complete Parameter List — Plane documentation 4.8.0.html" \
    --vehicle plane \
    --firmware-version 4.8.0 \
    --source-url https://ardupilot.org/plane/docs/parameters.html \
    --build-vectors   # optional: also rebuild the semantic index for this version
```

Console script entry points (`pyproject.toml`): `ardupilot-mcp` → `server:main`,
`ardupilot-refresh` → `ingest:main` (note: *not* `scripts/refresh.py`, which is unused).

## Architecture

- `db.py` — SQLite schema + query layer. `parameters` + `parameter_values` tables,
  FTS5 virtual table for keyword search. Unique key: `(vehicle, firmware_version, name, backend)`.
- `scraper.py` — parses Sphinx-generated ArduPilot parameter HTML into `Parameter` records.
- `ingest.py` — orchestrates scrape → SQLite write → optional vector rebuild. CLI entry point.
- `vectors.py` — LanceDB-backed semantic search layer using `intfloat/multilingual-e5-small`.
- `server.py` — FastMCP server exposing the tools: `list_versions`, `lookup_parameter`,
  `search_parameters` (FTS5), `semantic_search` (vectors), `list_parameters`, `diff_parameter`.

## Gotchas

- **e5 embedding prefixes**: queries must be encoded as `"query: {text}"`, indexed passages
  as `"passage: {text}"`. Skipping the prefix silently degrades retrieval quality — no error.
- **Backend variants**: a parameter can have multiple rows differing by `backend` (e.g. driver
  variants). The main definition is `backend IS NULL`; lookups prefer it via
  `ORDER BY (backend IS NULL) DESC`.
- **Semantic index covers one version only** — the latest ingested firmware version for a
  vehicle. FTS5 keyword search (`search_parameters`) covers all ingested versions.
- **Reingest is atomic per `(vehicle, firmware_version)`** — re-running ingest replaces only
  that pair's rows; other versions are left intact.
- **Vehicle scope**: schema and the ingest CLI accept `plane|copter|rover|sub`, but only
  `plane` has ever been ingested and `server.py` defaults/hardcodes `vehicle="plane"`
  throughout. Treat copter/rover/sub as unimplemented, not just untested.
- **Known bug**: `list_parameters()`'s docstring tells callers to "Use `list_sections()`
  first if unsure" — no such tool exists in `server.py`. Don't call it.

## Data bootstrap

`data/` is entirely gitignored — a fresh clone has no SQLite DB, no vector index, and no
source HTML. To rebuild from scratch:

1. Download the target vehicle's parameter reference page, e.g.
   `https://ardupilot.org/plane/docs/parameters.html`.
2. Save it under `data/ardupilot-docs/`.
3. Run ingest (see Commands above) with `--source-url` set to that same URL.

## Conventions

No linter/formatter is configured. Match the existing style: `from __future__ import
annotations`, Google-style docstrings with `Args:`, dataclasses for records, modern union
typing (`X | None`).
