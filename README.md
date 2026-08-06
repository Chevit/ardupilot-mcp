# ardupilot-mcp

MCP server exposing ArduPilot firmware parameter Q&A — keyword search, semantic search, and
cross-version diffing — to Claude Desktop, Claude Code, and other MCP clients. Runs 100% locally
against a SQLite + LanceDB store scraped from ArduPilot's Sphinx-generated HTML parameter docs.

## Features

- **Exact lookup** — look up a parameter by name, with full metadata (description, units, range,
  enum/bitmask values).
- **Keyword search** — FTS5-backed search across all ingested firmware versions.
- **Semantic search** — embedding-based search (`intfloat/multilingual-e5-small`) over the latest
  ingested firmware version.
- **Cross-version diffing** — field-by-field diff of a parameter's definition between two firmware
  versions.
- **Local-only** — no network calls at query time beyond the one-time embedding model download.

## Requirements

Before you start, you need two things installed on your computer:

1. **Docker Desktop** — download from [docker.com](https://www.docker.com/products/docker-desktop/)
   and install it like any other app. This is the only way you'll run things — no need to install
   Python or any other developer tools.
2. **A terminal app** — on Mac, open the app called "Terminal" (search for it with Spotlight,
   `Cmd+Space`). On Windows, open "Command Prompt" or "PowerShell" (search in the Start menu).

Every command below gets typed into that terminal window, one at a time, followed by Enter.

## Step-by-step setup

1. Get a copy of this project onto your computer. If you were given a folder, just make sure you
   know where it is. In the terminal, move into that folder:

   ```bash
   cd path/to/ardupilot-mcp
   ```

   (Replace `path/to/ardupilot-mcp` with the real folder location — you can usually drag the
   folder into the terminal window instead of typing the path.)

2. Get the parameter reference page for the vehicle you care about. Open this link in your web
   browser:

   `https://ardupilot.org/plane/docs/parameters.html`

3. Save that page: in your browser's menu choose "Save Page As…" (or `Cmd+S` / `Ctrl+S`), and save
   it into the `data/ardupilot-docs/` folder inside the project folder from step 1. If that folder
   doesn't exist yet, create it first.

4. Build the app (only needed once, or after an update):

   ```bash
   docker compose build
   ```

   This takes a few minutes the first time. Wait for it to finish.

5. Load the parameter data you saved in step 3 into the app's database:

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --html "data/ardupilot-docs/Complete Parameter List — Plane documentation 4.8.0.html" --vehicle plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html --build-vectors
   ```

   If your saved file has a different name (e.g. a different version number), adjust the part
   after `--html` to match the exact file name in `data/ardupilot-docs/`.

You're set up. The next section explains how to actually use it.

## Using it with Claude Desktop / Claude Code

This app is a "tool" that Claude can call — you don't run it by itself, you tell Claude how to
find it, then talk to Claude as usual.

1. Open your Claude Desktop / Claude Code settings file (search your Claude app's settings for
   "MCP servers" if unsure where this lives).
2. Add this entry, replacing `/path/to/ardupilot-mcp` with the real folder path from setup step 1:

   ```json
   {
     "mcpServers": {
       "ardupilot": {
         "command": "docker",
         "args": ["compose", "run", "--rm", "mcp-stdio"],
         "cwd": "/path/to/ardupilot-mcp"
       }
     }
   }
   ```

3. Restart Claude Desktop / Claude Code.
4. Ask Claude something like "what does the RC_OPTIONS parameter do?" — Claude will use this tool
   automatically.

## Advanced: running as a shared server

If you want one computer to run this and other people's Claude clients to connect to it over the
network, start the long-running version instead:

```bash
docker compose up -d mcp-http
```

Other people then point their Claude client at `http://<this-computer's-address>:8000/mcp` instead
of using the `docker compose run` command above. There's no login/password built in, so only do
this on a network you trust (home network, VPN, or similar) — don't expose it to the open
internet.

## Advanced: running without Docker

If you'd rather run this with Python directly instead of Docker, you need
[`uv`](https://docs.astral.sh/uv/) and Python 3.10+ installed. Then:

```bash
uv sync
uv run python -m ardupilot_mcp.ingest \
    --html "data/ardupilot-docs/Complete Parameter List — Plane documentation 4.8.0.html" \
    --vehicle plane \
    --firmware-version 4.8.0 \
    --source-url https://ardupilot.org/plane/docs/parameters.html \
    --build-vectors
uv run python -m ardupilot_mcp.server
```

Console script entry points (`pyproject.toml`): `ardupilot-mcp` → `server:main`,
`ardupilot-refresh` → `ingest:main`.

## MCP tools

`server.py` exposes six tools via FastMCP:

- `list_versions` — firmware versions available in the local database.
- `lookup_parameter` — exact-name lookup, with backend-variant handling.
- `search_parameters` — FTS5 keyword search, all ingested versions.
- `semantic_search` — embedding-based search, latest ingested version only.
- `list_parameters` — browse parameters by prefix/section.
- `diff_parameter` — field-by-field diff of a parameter between two firmware versions.

## Project structure

- `src/ardupilot_mcp/db.py` — SQLite schema + query layer. `parameters` + `parameter_values`
  tables, FTS5 virtual table for keyword search. Unique key:
  `(vehicle, firmware_version, name, backend)`.
- `src/ardupilot_mcp/scraper.py` — parses Sphinx-generated ArduPilot parameter HTML into
  `Parameter` records.
- `src/ardupilot_mcp/ingest.py` — orchestrates scrape → SQLite write → optional vector rebuild.
  CLI entry point.
- `src/ardupilot_mcp/vectors.py` — LanceDB-backed semantic search layer.
- `src/ardupilot_mcp/catalog.py` — the seam through which all six tools query the SQLite + vector
  stores.
- `src/ardupilot_mcp/server.py` — FastMCP server exposing the six tools above.
- `Dockerfile`, `docker-compose.yml` — container build and stdio/http launch services.

## Running tests

```bash
uv run pytest
```

## Known limitations

- Only the `plane` vehicle has ever been ingested; `copter`/`rover`/`sub` are accepted by the
  schema and ingest CLI but unimplemented in practice — `server.py` defaults/hardcodes
  `vehicle="plane"` throughout.
- The semantic index covers one firmware version at a time (the latest ingested for a vehicle).
  Keyword search covers all ingested versions.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
