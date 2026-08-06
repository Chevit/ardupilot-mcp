"""One-shot refresh: ingest every ArduPilot parameter HTML file found in
data/ardupilot-docs/, then rebuild the semantic index for each vehicle's
latest version.

Run manually:
    uv run python scripts/refresh.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from ardupilot_mcp.ingest import ingest
from ardupilot_mcp.vectors import DEFAULT_VECTORS_PATH, VectorStore, rebuild_from_db

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "ardupilot-docs"

_FILENAME_RE = re.compile(
    r"Complete Parameter List — (\w+) documentation ([\d.]+)\.html"
)


def discover_pairs(data_dir: Path = DATA_DIR) -> list[tuple[str, str, Path]]:
    """Scan data_dir for (vehicle, firmware_version, html_path) triples.

    Files that don't match the expected naming convention are skipped with
    a stderr warning rather than aborting the whole refresh.
    """
    pairs: list[tuple[str, str, Path]] = []
    for html_path in sorted(data_dir.glob("*.html")):
        m = _FILENAME_RE.search(html_path.name)
        if m is None:
            print(f"[refresh] skipping unrecognized file: {html_path.name}",
                  file=sys.stderr)
            continue
        vehicle = m.group(1).lower()
        firmware_version = m.group(2)
        pairs.append((vehicle, firmware_version, html_path))
    return pairs


def main() -> int:
    pairs = discover_pairs()
    if not pairs:
        print(f"[refresh] no recognized HTML files found in {DATA_DIR}", file=sys.stderr)
        return 1

    latest_by_vehicle: dict[str, str] = {}
    for vehicle, firmware_version, html_path in pairs:
        ingest(
            html_path=html_path,
            vehicle=vehicle,
            firmware_version=firmware_version,
            source_url=None,
            verbose=True,
        )
        current = latest_by_vehicle.get(vehicle)
        if current is None or firmware_version > current:
            latest_by_vehicle[vehicle] = firmware_version

    for vehicle, firmware_version in latest_by_vehicle.items():
        store = VectorStore(path=DEFAULT_VECTORS_PATH)
        rebuild_from_db(store, vehicle=vehicle, firmware_version=firmware_version, verbose=True)

    print(
        f"[refresh] done — {len(pairs)} file(s) ingested, "
        f"{len(latest_by_vehicle)} vector index(es) rebuilt",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
