# ArduPilot MCP

Local-only MCP server exposing ArduPilot firmware parameter Q&A — keyword search, semantic search, and cross-version diffing — to Claude Desktop and similar MCP clients.

## Language

**Parameter**:
A single ArduPilot firmware setting, identified by name, tied to a vehicle and firmware version. Carries description, units, range, section, and optional enum/bitmask values.
_Avoid_: setting, config value, field.

**ParameterValue**:
One named value a Parameter can take — either an enum entry (e.g. `0=Disabled`) or a single bit in a bitmask.
_Avoid_: enum, option, choice.

**Vehicle**:
The ArduPilot firmware family a Parameter belongs to — `plane`, `copter`, `rover`, or `sub`. Only `plane` is currently ingested.
_Avoid_: platform, firmware type.

**Firmware version**:
The ArduPilot release a Parameter's definition was scraped from (e.g. `4.8.0`). The same Parameter name can have different definitions across versions — that's what diffing compares.
_Avoid_: release, build.

**Backend**:
The driver variant a Parameter definition applies to (e.g. `AP_BattMonitor_Analog`). `NULL`/absent means the main, backend-agnostic definition — the one returned by default.
_Avoid_: driver, variant (unqualified).

**ParameterCatalog**:
The single seam through which a firmware version's parameters are looked up by name, keyword-searched, semantically searched, browsed by prefix/section, listed, and diffed across versions. Holds the keyword index and the VectorStore behind one interface so callers never touch either directly.
_Avoid_: catalog service, parameter store, DB layer.

**VectorStore**:
The semantic index over Parameter descriptions for one firmware version at a time — the newest ingested version only. Older versions are reachable through keyword search but not semantic search.
_Avoid_: vector DB, embedding index (as the primary name — fine as description).

**Ingest**:
The act of parsing one vehicle+firmware_version's HTML parameter reference and loading it into the ParameterCatalog's stores, replacing any prior ingest of that same vehicle+firmware_version.
_Avoid_: import, scrape (scrape is the parsing step within ingest, not the whole act).
