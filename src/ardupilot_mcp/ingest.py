"""Ingest pipeline: parse an ArduPilot HTML page and load rows into SQLite.

Ingest is scoped to a single (vehicle, firmware_version) pair. Re-running
against the same pair replaces those rows atomically; other versions are
left untouched, so you can hold multiple firmware versions side by side.

Example:

    uv run python -m ardupilot_mcp.ingest \\
        --html "D:/Downloads/Ardu/Complete Parameter List — Plane documentation 4.8.0.html" \\
        --vehicle plane \\
        --firmware-version 4.8.0 \\
        --source-url https://ardupilot.org/plane/docs/parameters.html
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .db import (
    DEFAULT_DB_PATH,
    connect,
    init_schema,
    record_ingestion,
    reset_vehicle_version,
    upsert_parameter,
)
from .scraper import parse_html_file

def ingest(
    html_path: Path,
    vehicle: str,
    firmware_version: str,
    source_url: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
    build_vectors: bool = False,
    vectors_path: Optional[Path] = None,
    verbose: bool = False,
) -> int:
    """Parse the HTML file and write every parameter into the DB.

    Returns the number of parameters loaded. Existing rows for
    (vehicle, firmware_version) are replaced atomically inside a single
    transaction; other versions remain intact.

    If `build_vectors=True`, also rebuilds the semantic index for this
    (vehicle, firmware_version) after ingest completes.
    """
    html_path = Path(html_path).resolve()
    if not html_path.exists():
        raise FileNotFoundError(html_path)

    if verbose:
        print(f"[scrape] {vehicle} {firmware_version}: parsing {html_path.name}",
              file=sys.stderr)
    params = parse_html_file(
        html_path,
        vehicle=vehicle,
        firmware_version=firmware_version,
        source_url=source_url,
    )
    if verbose:
        print(f"[scrape] got {len(params)} parameters", file=sys.stderr)

    init_schema(db_path)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with connect(db_path) as conn:
        reset_vehicle_version(conn, vehicle, firmware_version)
        for p in params:
            upsert_parameter(conn, p, scraped_at)
        record_ingestion(
            conn, vehicle, firmware_version, str(html_path), scraped_at, len(params),
        )

    if verbose:
        print(f"[db] wrote {len(params)} rows -> {db_path}", file=sys.stderr)

    if build_vectors:
        # Imported lazily so users who never enable vectors don't pay the
        # sentence-transformers / torch import cost.
        from .vectors import VectorStore, rebuild_from_db, DEFAULT_VECTORS_PATH
        store = VectorStore(path=vectors_path or DEFAULT_VECTORS_PATH)
        rebuild_from_db(
            store,
            db_path=db_path,
            vehicle=vehicle,
            firmware_version=firmware_version,
            verbose=verbose,
        )

    return len(params)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest an ArduPilot parameter reference HTML file into SQLite.",
    )
    parser.add_argument("--html", required=True, type=Path,
                        help="Path to the parameters HTML file")
    parser.add_argument("--vehicle", required=True,
                        choices=["plane", "copter", "rover", "sub"])
    parser.add_argument("--firmware-version", required=True,
                        help="Firmware version string, e.g. 4.8.0 or 4.6.3")
    parser.add_argument("--source-url", default=None,
                        help="Canonical URL to record with each row")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help="SQLite DB path")
    parser.add_argument("--build-vectors", action="store_true",
                        help="Also rebuild the semantic index for this version")
    parser.add_argument("--vectors-path", type=Path, default=None,
                        help="LanceDB directory (defaults to data/vectors.lance)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    n = ingest(
        html_path=args.html,
        vehicle=args.vehicle,
        firmware_version=args.firmware_version,
        source_url=args.source_url,
        db_path=args.db,
        build_vectors=args.build_vectors,
        vectors_path=args.vectors_path,
        verbose=not args.quiet,
    )
    print(f"ingested {n} parameters ({args.vehicle} {args.firmware_version}) "
          f"-> {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
