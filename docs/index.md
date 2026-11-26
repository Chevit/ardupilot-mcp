# ardupilot-mcp documentation

MCP server for ArduPilot parameter Q&A: keyword and semantic search over a local SQLite + LanceDB store scraped from
ArduPilot's parameter reference pages. Setup and usage are in the [README](../README.md); domain terms are in
[CONTEXT.md](../CONTEXT.md).

## API reference

| Module | Description |
|---|---|
| [server](api/server.md) | The six MCP tools and the `ardupilot-mcp` entry point (stdio / streamable HTTP). |
| [catalog](api/catalog.md) | `ParameterCatalog`, the read-side seam every tool queries through. |
| [ingest](api/ingest.md) | Fetch → load → rebuild-vectors pipeline and the `ardupilot-refresh` CLI. |
| [vectors](api/vectors.md) | LanceDB vector store and the onnxruntime e5 embedding model. |
| [db](api/db.md) | SQLite schema, `Parameter` records and write helpers. |
| [scraper](api/scraper.md) | Parser for ArduPilot's Sphinx-generated parameter HTML. |
| [fetch](api/fetch.md) | HTTP download from ardupilot.org and vehicle detection from URLs. |
| [roster](api/roster.md) | Vehicle Roster loading: which vehicles exist and which `--all` fetches. |

## Architecture decisions

| ADR | Decision |
|---|---|
| [0001](adr/0001-single-firmware-version-per-vehicle.md) | One firmware version stored per vehicle. |
| [0002](adr/0002-vehicle-roster-owns-the-vehicle-list.md) | The Vehicle Roster owns the vehicle list. |
| [0003](adr/0003-diff-assumes-one-shared-firmware-version.md) | `diff_parameter` assumes one shared firmware version. |
| [0004](adr/0004-onnx-embeddings.md) | Embeddings run on onnxruntime, not sentence-transformers. |

## Design specs and plans

- [Docker Compose launch — design](superpowers/specs/2026-08-06-docker-compose-launch-design.md)
- [URL ingest — design](superpowers/specs/2026-08-06-url-ingest-design.md)
- [Architecture improvements — plan](superpowers/plans/2026-08-06-architecture-improvements.md)
- [Docker Compose launch — plan](superpowers/plans/2026-08-06-docker-compose-launch.md)
- [URL ingest — plan](superpowers/plans/2026-08-06-url-ingest.md)
