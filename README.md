# ardupilot-mcp

MCP server exposing ArduPilot firmware parameter Q&A — keyword search, semantic search, and
cross-vehicle diffing — to Claude Desktop, Claude Code, and other MCP clients. Runs 100% locally
against a SQLite + LanceDB store scraped from ArduPilot's Sphinx-generated HTML parameter docs.

## Features

- **Exact lookup** — look up a parameter by name, with full metadata (description, units, range,
  enum/bitmask values).
- **Keyword search** — FTS5-backed search, scoped to one vehicle or across every enabled vehicle.
- **Semantic search** — embedding-based search (`intfloat/multilingual-e5-small`), same scoping;
  a parameter matching in several vehicles is deduped and tagged with which ones matched.
- **Cross-vehicle diffing** — field-by-field diff of a parameter's definition between two vehicles
  (e.g. "how does `LOG_BITMASK` differ between plane and copter?").
- **Local-only** — no network calls at query time beyond the one-time embedding model download.

Each vehicle stores exactly one firmware version at a time — whichever the Vehicle Roster's URL
currently points at. See "The Vehicle Roster" below.

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

2. Build the app (only needed once, or after an update):

   ```bash
   docker compose build
   ```

   This takes a few minutes the first time. Wait for it to finish.

3. Load parameter data — one command fetches every enabled vehicle on the Vehicle Roster
   (`plane`, `copter`, `rover`, `sub` by default) directly from ardupilot.org:

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --all --build-vectors
   ```

   Vehicle and firmware version are detected automatically. Only want one vehicle, or a page
   the roster doesn't already list?

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --url https://ardupilot.org/plane/docs/parameters.html --build-vectors
   ```

   > No internet access on this machine, or want to pin a specific saved-locally page? Open the
   > link above in a browser, "Save Page As…" into the `data/ardupilot-docs/` folder inside the
   > project folder (create it if it doesn't exist), then run the same command with
   > `--html "data/ardupilot-docs/<the saved file name>.html" --vehicle plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html`
   > in place of `--url ...`.

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
         "args": ["compose", "-f", "/path/to/ardupilot-mcp/docker-compose.yml", "run", "--rm", "mcp-stdio"]
       }
     }
   }
   ```

   > Some MCP clients don't honor a `cwd` field, which makes `docker compose` fail with
   > `no configuration file provided: not found` since it can't locate `docker-compose.yml`.
   > Passing `-f /path/to/ardupilot-mcp/docker-compose.yml` sidesteps that — it works
   > regardless of the client's working directory.

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
uv run python -m ardupilot_mcp.ingest --all --build-vectors
uv run python -m ardupilot_mcp.server
```

`--all` fetches every enabled vehicle on the Vehicle Roster. For a single vehicle, vehicle and
firmware version are auto-detected from the URL and page text: `uv run python -m
ardupilot_mcp.ingest --url https://ardupilot.org/plane/docs/parameters.html --build-vectors`. Pass
`--vehicle`/`--firmware-version` to override, or swap `--url <url>` for `--html "<path>" --vehicle
plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html` to
ingest from a page you already downloaded instead of fetching it.

Console script entry points (`pyproject.toml`): `ardupilot-mcp` → `server:main`,
`ardupilot-refresh` → `ingest:main`.

## The Vehicle Roster

Which vehicles exist, their source URLs, and whether `--all` fetches them live in the **Vehicle
Roster** — `vehicles.json`, packaged with the app. Ships with six vehicles: `plane`, `copter`,
`rover`, `sub` enabled; `blimp` and `antennatracker` present but disabled.

To change a URL, pin a vehicle to an older firmware version (ArduPilot publishes versioned pages
like `parameters-Copter-stable-V4.7.0.html` for superseded releases), or enable/disable a vehicle:
drop your own `vehicles.json` into `data/` (the directory Docker already bind-mounts) — it fully
replaces the packaged roster, so include every vehicle you still want. `--vehicles-config PATH`
picks a roster file outside `data/` for a single invocation.

An `enabled: false` entry only affects `--all` — `ardupilot-refresh --url ... --vehicle blimp`
still ingests it as a deliberate one-off, and once ingested it stays queryable by name; it's just
excluded from the unscoped `vehicle=None` search tools.

## MCP tools

`server.py` exposes six tools via FastMCP. `vehicle` has no default anywhere — call
`list_vehicles()` if unsure what to pass.

- `list_vehicles` — every vehicle on the Roster, its enabled flag, and its ingested_version (null
  if never ingested).
- `lookup_parameter` — exact-name lookup for one vehicle, with backend-variant handling.
- `search_parameters` — FTS5 keyword search. `vehicle` omitted searches every enabled vehicle.
- `semantic_search` — embedding-based search, same scoping as above.
- `list_parameters` — browse one vehicle's parameters by prefix/section.
- `diff_parameter` — field-by-field diff of a parameter between two vehicles.

## Project structure

- `src/ardupilot_mcp/roster.py` — loads the Vehicle Roster (`vehicles.json`): the authoritative
  list of which vehicles exist, their source URLs, and whether `--all` fetches them.
- `src/ardupilot_mcp/db.py` — SQLite schema + query layer. `parameters` + `parameter_values`
  tables, FTS5 virtual table for keyword search. Unique key: `(vehicle, name, backend)` — one
  firmware version stored per vehicle at a time.
- `src/ardupilot_mcp/scraper.py` — parses Sphinx-generated ArduPilot parameter HTML into
  `Parameter` records.
- `src/ardupilot_mcp/fetch.py` — network fetch (`fetch_url`) and URL → vehicle detection
  (`detect_vehicle_from_url`, matched against the Vehicle Roster's names) for the `--url`/`--all`
  ingest paths.
- `src/ardupilot_mcp/ingest.py` — orchestrates scrape → SQLite write → optional vector rebuild.
  CLI entry point; `--all` loops the Roster's enabled vehicles and rebuilds vectors once at the end.
- `src/ardupilot_mcp/vectors.py` — LanceDB-backed semantic search layer, holding every vehicle at
  once.
- `src/ardupilot_mcp/catalog.py` — the seam through which all six tools query the SQLite + vector
  stores + Vehicle Roster.
- `src/ardupilot_mcp/server.py` — FastMCP server exposing the six tools above.
- `Dockerfile`, `docker-compose.yml` — container build and stdio/http launch services.

See `docs/adr/` for the reasoning behind the single-version-per-vehicle storage model and the
Vehicle Roster, and `CONTEXT.md` for the project's glossary.

## Running tests

```bash
uv run pytest
```

Golden scraper tests read `tests/fixtures/` (gitignored, not the `data/` directory `ardupilot-refresh`
writes to) — regenerate with `scripts/fetch_test_fixtures.sh` if missing; they `skip` rather than
fail on a fresh clone.

## Known limitations

- The semantic index's `vehicle=None` cross-vehicle search over-fetches and dedupes by parameter
  name client-side, so the requested `k` is an approximate result count, not an exact one.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
