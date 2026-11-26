# roster

Loads the Vehicle Roster: the authoritative list of vehicles, their parameter-page URLs, and whether `--all` fetches
them.

## Overview

A vehicle absent from the loaded Roster does not exist for this install
([ADR 0002](../adr/0002-vehicle-roster-owns-the-vehicle-list.md)). Lookup order, first match wins:

1. An explicit path (e.g. `--vehicles-config`), which must exist.
2. `data/vehicles.json`, the Docker-bind-mounted override.
3. The packaged `src/ardupilot_mcp/vehicles.json`.

An override replaces the packaged Roster entirely; it is not merged. `enabled` only affects `--all` and unscoped
(`vehicle=None`) searches; an explicitly named vehicle always works.

The file is a JSON object mapping vehicle name to `{"url": str, "enabled": bool}` (`enabled` defaults to `true`).
The packaged Roster lists `plane` and `copter` as enabled, and `rover`, `sub`, `blimp`, `antennatracker` as disabled.

## Public API

### VehicleEntry

```python
@dataclass(frozen=True)
class VehicleEntry:
    url: str
    enabled: bool = True
```

### load_roster

```python
def load_roster(path: Path | None = None) -> dict[str, VehicleEntry]
```

Loads the Roster using the lookup order above. Raises `FileNotFoundError` if `path` is given and missing. A malformed
entry without `url` raises `KeyError`.

### enabled_vehicles

```python
def enabled_vehicles(roster: dict[str, VehicleEntry]) -> list[str]
```

Names with `enabled: true`, sorted.

### PACKAGED_ROSTER_PATH / DEFAULT_OVERRIDE_PATH

```python
PACKAGED_ROSTER_PATH   # src/ardupilot_mcp/vehicles.json
DEFAULT_OVERRIDE_PATH  # <repo>/data/vehicles.json
```

## Usage examples

```json
{
  "plane": {"url": "https://ardupilot.org/plane/docs/parameters.html"},
  "rover": {"url": "https://ardupilot.org/rover/docs/parameters.html", "enabled": false}
}
```

```python
from ardupilot_mcp.roster import enabled_vehicles, load_roster

roster = load_roster()
print(enabled_vehicles(roster), roster["plane"].url)
```
