# ArduPilot MCP

Local-only MCP server exposing ArduPilot firmware parameter Q&A — keyword search, semantic search, and cross-vehicle diffing — to Claude Desktop and similar MCP clients.

## Language

**Parameter**:
A single ArduPilot firmware setting, identified by name, tied to a vehicle and firmware version. Carries description, units, range, section, and optional enum/bitmask values.
_Avoid_: setting, config value, field.

**ParameterValue**:
One named value a Parameter can take — either an enum entry (e.g. `0=Disabled`) or a single bit in a bitmask.
_Avoid_: enum, option, choice.

**Vehicle**:
The ArduPilot firmware family a Parameter belongs to. Which Vehicles exist is defined by the Vehicle Roster, never by code.
_Avoid_: platform, firmware type, type.

**Vehicle Roster**:
The authoritative list of Vehicles this install knows about — each with a source URL and an enabled flag. The single source of truth for which Vehicles exist; a Vehicle absent from the Roster does not exist.
_Avoid_: vehicle config, source catalog, registry.

**Firmware version**:
The ArduPilot release a Parameter's definition was scraped from (e.g. `4.8.0`). Provenance only — exactly one is stored per Vehicle, so it is never something you search or filter by.
_Avoid_: release, build.

**Backend**:
The driver variant a Parameter definition applies to (e.g. `AP_BattMonitor_Analog`). `NULL`/absent means the main, backend-agnostic definition — the one returned by default.
_Avoid_: driver, variant (unqualified).

**ParameterCatalog**:
The single seam through which Parameters are looked up by name, keyword-searched, semantically searched, browsed by prefix/section, listed, and diffed across Vehicles. Holds the keyword index and the VectorStore behind one interface so callers never touch either directly.
_Avoid_: catalog service, parameter store, DB layer.

**VectorStore**:
The semantic index over Parameter descriptions, holding every enabled Vehicle at its one stored Firmware version.
_Avoid_: vector DB, embedding index (as the primary name — fine as description).

**Ingest**:
The act of parsing one Vehicle's HTML parameter reference and loading it into the ParameterCatalog's stores, replacing everything previously stored for that Vehicle.
_Avoid_: import, scrape (scrape is the parsing step within ingest, not the whole act).
