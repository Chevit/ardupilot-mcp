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
