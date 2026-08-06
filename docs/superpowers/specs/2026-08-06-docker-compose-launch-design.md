# Docker Compose launch for ardupilot-mcp

Date: 2026-08-06
Status: approved

## Goal

Let the MCP server be launched via Docker Compose instead of a local `uv`
environment, to simplify install and usage. Must support two connection
modes, since Claude may connect from the same machine or from a remote one:

1. **Local stdio** — Claude Desktop/Code on the same machine spawns the
   container as a subprocess and talks MCP over stdio, same as today's
   `uv run python -m ardupilot_mcp.server`.
2. **Remote HTTP** — the server runs long-lived on a separate machine
   (mac/linux/windows host running Docker), and a remote Claude client
   connects over the network via MCP's streamable-http transport.

Non-goals: containerizing multi-vehicle support (still `plane`-only, per
existing CLAUDE.md gotchas), adding authentication to the HTTP transport,
CI/publishing the image to a registry.

## Design

### Single image, two compose services

One `Dockerfile` builds one image; `docker-compose.yml` defines two services
from it that differ only in command/env — no need for separate Dockerfiles
or a separate ingest image.

```yaml
services:
  mcp-stdio:
    build: .
    volumes: ["./data:/app/data"]
    stdin_open: true
    tty: false
    # never `up` — invoked per-connection via: docker compose run --rm mcp-stdio

  mcp-http:
    build: .
    volumes: ["./data:/app/data"]
    environment:
      MCP_TRANSPORT: streamable-http
      MCP_HTTP_PORT: "8000"
    ports: ["${PORT:-8000}:8000"]
    restart: unless-stopped
```

`mcp-stdio` is a one-shot `run`, matching how MCP clients spawn stdio
subprocesses on demand. `mcp-http` is a standing service the operator
starts once with `docker compose up -d mcp-http`.

### Dockerfile

- Base: `python:3.12-slim`.
- Copy the `uv` binary from `ghcr.io/astral-sh/uv` (no separate installer
  step).
- `COPY pyproject.toml uv.lock ./` then `uv sync --frozen --no-dev` first,
  before copying `src/`, so dependency layers cache across source edits.
  The CPU-only torch index is already pinned in `pyproject.toml`
  (`tool.uv.sources` / `tool.uv.index`), so no extra index config needed in
  the image.
- Copy `src/`, sync again to register the console-script entry points.
- `ENTRYPOINT ["uv", "run", "ardupilot-mcp"]` — default behavior is the
  existing stdio server; `docker compose run --rm mcp-stdio` needs no
  extra args, matching today's `ardupilot-mcp` console script.
- `.dockerignore`: `.venv/`, `data/`, `.git/`, `__pycache__/`, `*.pyc`,
  `.pytest_cache/`, `docs/`, `tests/`.

### `server.py` transport switch

Small, targeted change to `main()`:

- Read `MCP_TRANSPORT` env var — `stdio` (default) or `streamable-http`.
- Read `MCP_HTTP_PORT` env var — default `8000`, used only in http mode.
- Call `mcp.run(transport=...)` with the appropriate transport, binding
  `0.0.0.0` in http mode (required for Docker port publishing to work; the
  actual exposure surface is controlled by compose's `ports:` mapping and
  host firewall, not the app's bind address).
- No other tool or business logic changes.

### Data / ingest

- `./data` bind-mounts into both services at `/app/data`. `DEFAULT_DB_PATH`
  and friends in `db.py`/`vectors.py` already resolve to `<repo>/data/...`
  relative to the package location, so no path changes needed — the mount
  point lines up automatically as long as the container's working
  directory mirrors the repo layout.
- Bootstrap flow is unchanged conceptually from CLAUDE.md's existing
  "Data bootstrap" section, just run through the container instead of a
  host `uv` environment:

  ```bash
  docker compose run --rm mcp-stdio ardupilot-refresh \
      --html "data/ardupilot-docs/Complete Parameter List — Plane documentation 4.8.0.html" \
      --vehicle plane \
      --firmware-version 4.8.0 \
      --source-url https://ardupilot.org/plane/docs/parameters.html \
      --build-vectors
  ```

- Semantic search still lazily downloads the `intfloat/multilingual-e5-small`
  model into `data/model-cache` on first `semantic_search` call — same
  lazy-load behavior as today, just now needs container-level internet
  access once. Because `model-cache` lives under the bind-mounted `data/`,
  it persists across container restarts/rebuilds like the SQLite DB and
  LanceDB index do.

### Security posture (HTTP mode)

No application-level auth is added. `mcp-http` is documented as
network-trust-only: an operator exposing it beyond localhost is
responsible for binding to a trusted interface, VPN, or reverse proxy with
its own auth. This matches the current reality of FastMCP's
streamable-http transport (no built-in auth) and keeps the server itself
simple.

### Docs

Add to README (or a new section in CLAUDE.md) two client config examples:

- **Local/stdio**: Claude Desktop/Code config points its MCP server
  `command` at `docker compose run --rm mcp-stdio`, run from the repo root
  (compose needs `docker-compose.yml` in the cwd, or `-p`/`--project-directory`
  pointed at it).
- **Remote/HTTP**: with `mcp-http` left running via `docker compose up -d
  mcp-http` on the remote host, the client's MCP config points at
  `http://<host>:8000/mcp` (exact path to be confirmed against FastMCP's
  streamable-http route during implementation) plus the network-trust
  caveat above.

## Testing

No project test suite exists for infra/deployment concerns (per CLAUDE.md,
"No dedicated test suite exists yet" — this remains a Python-source-level
statement; Docker build/run isn't unit-testable the same way). Verification
is manual:

1. `docker compose build` succeeds.
2. `docker compose run --rm mcp-stdio ardupilot-refresh ...` ingests
   successfully into bind-mounted `data/`.
3. A stdio MCP client (or `mcp` dev inspector) can call `list_versions`
   through `docker compose run --rm mcp-stdio`.
4. `docker compose up -d mcp-http`, then an HTTP MCP client can call
   `list_versions` against `http://localhost:8000/mcp`.
5. `docker compose down` / rebuild doesn't lose data (bind mount persists).
