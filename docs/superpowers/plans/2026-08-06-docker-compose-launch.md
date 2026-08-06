# Docker Compose Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ardupilot-mcp` launchable via Docker Compose in two modes — local stdio (for same-machine Claude clients) and remote streamable-http (for a Claude client on another machine) — using one image and one compose file.

**Architecture:** A single `Dockerfile` builds an image containing the `uv`-managed venv and the project's console scripts. `docker-compose.yml` defines two services from that image (`mcp-stdio`, `mcp-http`) that differ only in command/env. `server.py` gains a small, unit-tested env-var switch (`MCP_TRANSPORT`, `MCP_HTTP_PORT`) so the same entry point serves either transport. `./data` bind-mounts into both containers so the SQLite DB, LanceDB index, and model cache persist on the host exactly as they do today for the non-Docker workflow.

**Tech Stack:** Docker, Docker Compose, `uv`, existing `mcp[cli]`/FastMCP server.

**Spec:** `docs/superpowers/specs/2026-08-06-docker-compose-launch-design.md`

---

### Task 1: `server.py` transport switch (TDD)

**Files:**
- Modify: `src/ardupilot_mcp/server.py` (the `main()` function at the bottom, currently just `mcp.run()`)
- Test: `tests/test_server.py` (append to existing file — do not remove the existing `test_server_registers_all_six_tools` test)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
def test_server_settings_defaults_to_stdio():
    from ardupilot_mcp.server import _server_settings

    transport, host, port = _server_settings({})

    assert transport == "stdio"
    assert host == "0.0.0.0"
    assert port == 8000


def test_server_settings_reads_streamable_http_and_custom_port():
    from ardupilot_mcp.server import _server_settings

    transport, host, port = _server_settings(
        {"MCP_TRANSPORT": "streamable-http", "MCP_HTTP_PORT": "9001"}
    )

    assert transport == "streamable-http"
    assert host == "0.0.0.0"
    assert port == 9001


def test_server_settings_rejects_unknown_transport():
    from ardupilot_mcp.server import _server_settings

    with pytest.raises(ValueError, match="MCP_TRANSPORT"):
        _server_settings({"MCP_TRANSPORT": "sse"})
```

Add `import pytest` to the top of `tests/test_server.py` alongside the existing `from __future__ import annotations` line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — `ImportError: cannot import name '_server_settings' from 'ardupilot_mcp.server'` (3 new tests error, 1 existing test still passes)

- [ ] **Step 3: Implement `_server_settings` and wire it into `main()`**

In `src/ardupilot_mcp/server.py`, add `import os` to the imports at the top (alongside the existing `from typing import Any, Optional`), then replace the current entry-point block:

```python
def main() -> None:
    """stdio transport for Claude Desktop and similar MCP clients."""
    mcp.run()


if __name__ == "__main__":
    main()
```

with:

```python
def _server_settings(env: dict[str, str] | None = None) -> tuple[str, str, int]:
    """Resolve (transport, host, port) from environment variables.

    MCP_TRANSPORT selects "stdio" (default) or "streamable-http". host is
    always "0.0.0.0" — required for Docker's port publishing to reach the
    process inside the container; it's simply unused in stdio mode.
    MCP_HTTP_PORT sets the port for streamable-http mode (default 8000,
    unused in stdio mode).
    """
    env = os.environ if env is None else env
    transport = env.get("MCP_TRANSPORT", "stdio")
    if transport not in ("stdio", "streamable-http"):
        raise ValueError(f"Unknown MCP_TRANSPORT: {transport!r}")
    port = int(env.get("MCP_HTTP_PORT", "8000"))
    return transport, "0.0.0.0", port


def main() -> None:
    """Entry point. Transport selected via MCP_TRANSPORT env var.

    Defaults to stdio, for Claude Desktop and similar MCP clients. Set
    MCP_TRANSPORT=streamable-http (with optional MCP_HTTP_PORT) to serve
    remote clients instead — see the Docker section of CLAUDE.md.
    """
    transport, host, port = _server_settings()
    if transport == "streamable-http":
        mcp.settings.host = host
        mcp.settings.port = port
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS — all 4 tests (1 existing + 3 new) pass

- [ ] **Step 5: Commit**

```bash
git add src/ardupilot_mcp/server.py tests/test_server.py
git commit -m "feat: add MCP_TRANSPORT env switch for streamable-http mode

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `Dockerfile`

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Write `.dockerignore`**

```
.venv/
data/
.git/
__pycache__/
*.pyc
.pytest_cache/
docs/
tests/
.claude/
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# Install dependencies first, in their own cached layer — this layer only
# invalidates when pyproject.toml/uv.lock change, not on every source edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Now bring in the source and install the project itself, registering the
# ardupilot-mcp / ardupilot-refresh console scripts.
COPY src ./src
RUN uv sync --frozen --no-dev

# Default: run the MCP server over stdio. Overridden by:
#   - MCP_TRANSPORT=streamable-http env var (see server.py's main()), for
#     the mcp-http compose service.
#   - a command override, e.g. `docker compose run --rm mcp-stdio
#     ardupilot-refresh ...` to run the ingest CLI instead.
ENTRYPOINT ["uv", "run"]
CMD ["ardupilot-mcp"]
```

- [ ] **Step 3: Build the image and verify it succeeds**

Run: `docker build -t ardupilot-mcp .`
Expected: build completes with exit code 0, ends with the image ID (e.g. `Successfully built ...` / `naming to docker.io/library/ardupilot-mcp ... done`)

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "build: add Dockerfile for ardupilot-mcp image

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `docker-compose.yml`

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  mcp-stdio:
    build: .
    volumes:
      - ./data:/app/data
    stdin_open: true
    tty: false
    # Not meant to be left `up` — a Claude Desktop/Code stdio client spawns
    # it per-connection via: docker compose run --rm mcp-stdio
    # The same image/service also runs the ingest CLI, e.g.:
    #   docker compose run --rm mcp-stdio ardupilot-refresh --html "..." \
    #       --vehicle plane --firmware-version 4.8.0 \
    #       --source-url https://ardupilot.org/plane/docs/parameters.html \
    #       --build-vectors

  mcp-http:
    build: .
    volumes:
      - ./data:/app/data
    environment:
      MCP_TRANSPORT: streamable-http
      MCP_HTTP_PORT: "8000"
    ports:
      - "${PORT:-8000}:8000"
    restart: unless-stopped
    # Long-running: docker compose up -d mcp-http
    # Remote clients connect to http://<this-host>:8000/mcp
    # No app-level auth — expose only on a trusted network/VPN, or put a
    # reverse proxy with auth in front.
```

- [ ] **Step 2: Verify config parses**

Run: `docker compose config --quiet`
Expected: exits 0, no output (silent success means valid YAML + schema)

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "build: add docker-compose.yml with stdio and http services

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Manual verification — stdio mode + ingest through the container

**Files:** none (verification only)

- [ ] **Step 1: Build via compose**

Run: `docker compose build`
Expected: exit 0

- [ ] **Step 2: Ingest a fixture HTML file into the bind-mounted `data/` through the container**

(Assumes `data/ardupilot-docs/Complete Parameter List — Plane documentation 4.8.0.html` already exists on the host per CLAUDE.md's "Data bootstrap" section — reuse whatever's already there, e.g. from running the existing test fixtures, rather than re-downloading.)

Run:
```bash
docker compose run --rm mcp-stdio ardupilot-refresh \
    --html "data/ardupilot-docs/Complete Parameter List — Plane documentation 4.8.0.html" \
    --vehicle plane \
    --firmware-version 4.8.0 \
    --source-url https://ardupilot.org/plane/docs/parameters.html \
    --build-vectors
```
Expected: exit 0, ingest log output, and afterwards `data/ardupilot.db` and `data/vectors.lance` exist on the host (`ls data/`)

- [ ] **Step 3: Call a tool through the stdio container using the MCP dev inspector**

Run: `uv run mcp dev "docker compose run --rm mcp-stdio"` — or, if the `mcp` CLI's `dev` subcommand doesn't accept a shell string cleanly in this environment, use:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_versions","arguments":{}}}' | docker compose run --rm -T mcp-stdio
```
Expected: a JSON-RPC response containing `["4.8.0"]` (or whatever versions were ingested) in `result`

- [ ] **Step 4: No commit** (verification-only task, nothing to check in)

---

### Task 5: Manual verification — http mode

**Files:** none (verification only)

- [ ] **Step 1: Start the http service**

Run: `docker compose up -d mcp-http`
Expected: exit 0

- [ ] **Step 2: Confirm it's listening**

Run: `docker compose logs mcp-http`
Expected: log lines showing uvicorn started on `0.0.0.0:8000`, no traceback

- [ ] **Step 3: Call a tool over HTTP**

Run:
```bash
curl -s -X POST http://localhost:8000/mcp \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_versions","arguments":{}}}'
```
Expected: HTTP 200 (or the transport's usual initialize-then-call handshake — if the bare `tools/call` is rejected for missing session/initialize, that's expected MCP protocol behavior, not a bug; the goal of this step is confirming the port answers and returns MCP-shaped JSON/SSE, not a full client handshake)

- [ ] **Step 4: Tear down**

Run: `docker compose down`
Expected: exit 0, `mcp-http` container removed; `data/` on host still has the DB/vectors from Task 4 (bind mount persists past `down`)

- [ ] **Step 5: No commit** (verification-only task, nothing to check in)

---

### Task 6: Document Docker usage in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a "## Docker" section**

Insert a new `## Docker` section into `CLAUDE.md`, immediately after the existing `## Commands` section and before `## Architecture`:

```markdown
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
docker compose run --rm mcp-stdio ardupilot-refresh \
    --html "data/ardupilot-docs/Complete Parameter List — Plane documentation 4.8.0.html" \
    --vehicle plane \
    --firmware-version 4.8.0 \
    --source-url https://ardupilot.org/plane/docs/parameters.html \
    --build-vectors
```

**Local stdio client** (Claude Desktop/Code on the same machine as the
Docker host) — point the client's MCP server command at compose, run from
the repo root:

```json
{
  "mcpServers": {
    "ardupilot": {
      "command": "docker",
      "args": ["compose", "run", "--rm", "mcp-stdio"]
    }
  }
}
```

**Remote HTTP client** (Claude client on a different machine than the
Docker host) — start the long-running service on the host that has the
data:

```bash
docker compose up -d mcp-http
```

Then point the remote client at `http://<docker-host>:8000/mcp`. No
app-level auth is built in — only expose `mcp-http` on a trusted network,
VPN, or behind a reverse proxy that adds auth.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document docker compose usage in CLAUDE.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
