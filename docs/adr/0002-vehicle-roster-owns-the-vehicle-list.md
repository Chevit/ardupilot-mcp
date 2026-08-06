# The Vehicle Roster owns the vehicle list

The set of supported vehicles was hardcoded in three places — a regex in
`fetch.py`, `argparse` choices in `ingest.py`, and the glossary — and all three
had drifted: they listed four vehicles when ArduPilot publishes six
(`blimp` and `antennatracker` serve parameter pages too, and
`detect_vehicle_from_url` returned `None` for both). We moved the roster into a
JSON config file, the **Vehicle Roster**, and made every one of those sites
derive from its keys.

## Considered Options

- **Config holds URLs only, vehicle list stays in code.** Rejected: adding a
  vehicle would still require a code change, which is the one scenario the file
  exists to handle. The drift above is what that option produces.
- **TOML instead of JSON, for real `#` comments.** Rejected: `tomllib` is 3.11+
  and `requires-python` is `>=3.10`, so it costs a `tomli` dependency or a
  Python bump — for a flat name-to-URL map. Entries that should ship documented
  but inactive carry `"enabled": false` instead, which has the further advantage
  of being visible to the program: `list_vehicles()` can report "available, not
  ingested", whereas a commented-out line is invisible.

## Consequences

- Lookup order: packaged `src/ardupilot_mcp/vehicles.json` (ships in the wheel,
  so a fresh clone and a fresh container both work with no setup), overridden by
  `data/vehicles.json` (the only Docker-bind-mounted directory, so container
  users edit it without touching compose) or `--vehicles-config PATH`.
- An override **fully replaces** the packaged roster rather than merging over
  it. Merging produces "I removed `sub` from my config but `sub` still appears",
  which is a debugging trap; full replacement makes the file's content exactly
  what you get, at the cost of copying all six lines to change one.
- An entry carries a URL and an `enabled` flag, and no version field. The
  version always comes from `detect_version(html)` — two sources of truth for
  the same fact is how you get a database labelled 4.7.0 holding 4.6.3 content.
  Pinning a version means pointing the URL at a versioned page.
- `enabled` governs **fetching only**. `--vehicle blimp` still works as a
  deliberate one-off override, and already-ingested data stays reachable under
  an explicit `vehicle="blimp"` query; but an unscoped `vehicle=None` search
  covers the enabled roster only, since off-roster data surfacing there is the
  surprise.
