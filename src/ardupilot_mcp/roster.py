"""Vehicle Roster — the authoritative list of Vehicles this install knows
about. See CONTEXT.md for the Vehicle Roster definition and
docs/adr/0002-vehicle-roster-owns-the-vehicle-list.md for why the roster
lives outside code rather than as a hardcoded enum.

Lookup order, first match wins:
    1. an explicit path (e.g. --vehicles-config) — required to exist
    2. data/vehicles.json — Docker's bind-mounted override directory
    3. the packaged default shipped inside this package

An override at (1) or (2) REPLACES the packaged roster entirely; it is not
merged over it. A Vehicle absent from the loaded roster does not exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


PACKAGED_ROSTER_PATH = Path(__file__).resolve().parent / "vehicles.json"
DEFAULT_OVERRIDE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "vehicles.json"
)


@dataclass(frozen=True)
class VehicleEntry:
    """One Vehicle Roster entry: where to fetch it, whether --all should."""
    url: str
    enabled: bool = True


def load_roster(path: Optional[Path] = None) -> dict[str, VehicleEntry]:
    """Load the Vehicle Roster as {vehicle_name: VehicleEntry}.

    If `path` is given, it must exist — an explicit request for a missing
    file is an error, not a silent fallback. Otherwise falls through to
    data/vehicles.json, then the packaged default.
    """
    if path is not None:
        resolved = Path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"Vehicle Roster not found: {resolved}")
    elif DEFAULT_OVERRIDE_PATH.exists():
        resolved = DEFAULT_OVERRIDE_PATH
    else:
        resolved = PACKAGED_ROSTER_PATH

    raw = json.loads(resolved.read_text(encoding="utf-8"))
    return {
        name: VehicleEntry(url=entry["url"], enabled=entry.get("enabled", True))
        for name, entry in raw.items()
    }


def enabled_vehicles(roster: dict[str, VehicleEntry]) -> list[str]:
    """Vehicle names with enabled=true, sorted."""
    return sorted(name for name, entry in roster.items() if entry.enabled)
