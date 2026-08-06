"""Ingest pipeline: parse an ArduPilot HTML page and load rows into SQLite.

Ingest is scoped to a single (vehicle, firmware_version) pair. Re-running
against the same pair replaces those rows atomically; other versions are
left untouched, so you can hold multiple firmware versions side by side.

Two ways to provide the source page — pass exactly one:

    # from a page already downloaded to disk
    uv run python -m ardupilot_mcp.ingest \\
        --html "D:/Downloads/Ardu/Complete Parameter List — Plane documentation 4.8.0.html" \\
        --vehicle plane \\
        --firmware-version 4.8.0 \\
        --source-url https://ardupilot.org/plane/docs/parameters.html

    # fetched directly — vehicle and firmware version auto-detected
    uv run python -m ardupilot_mcp.ingest \\
        --url https://ardupilot.org/copter/docs/parameters.html
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

import httpx

from .db import (
    DEFAULT_DB_PATH,
    connect,
    init_schema,
    record_ingestion,
    reset_vehicle_version,
    upsert_parameter,
)
from .fetch import detect_vehicle_from_url, fetch_url
from .scraper import detect_version, parse_html_file

DEFAULT_ARCHIVE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "ardupilot-docs"
)


class IngestResult(NamedTuple):
    """What ingest() actually did — count plus the resolved vehicle/version.

    Resolution matters for the --url path: vehicle/firmware_version may have
    been auto-detected rather than passed in, so callers (the CLI) need a
    way to find out what was actually ingested.
    """
    count: int
    vehicle: str
    firmware_version: str


def _fetch_and_archive(
    url: str,
    vehicle: Optional[str],
    firmware_version: Optional[str],
    source_url: Optional[str],
    archive_dir: Path,
    http_client: Optional[httpx.Client],
    verbose: bool,
) -> tuple[Path, str, str, str]:
    """Fetch `url`, auto-detect vehicle/version, archive HTML to disk.

    Returns (archived_html_path, vehicle, firmware_version, source_url) —
    everything `ingest()` needs to fall through to the shared parse step.
    """
    if verbose:
        print(f"[fetch] downloading {url}", file=sys.stderr)
    html = fetch_url(url, client=http_client)

    vehicle = vehicle or detect_vehicle_from_url(url)
    if vehicle is None:
        raise ValueError(
            f"could not detect vehicle from URL {url!r}; pass --vehicle explicitly"
        )

    firmware_version = firmware_version or detect_version(html)
    if firmware_version is None:
        raise ValueError(
            "could not detect firmware version from page; "
            "pass --firmware-version explicitly"
        )

    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_name = (
        f"Complete Parameter List — {vehicle.capitalize()} documentation "
        f"{firmware_version}.html"
    )
    archive_path = archive_dir / archive_name
    archive_path.write_text(html, encoding="utf-8")
    if verbose:
        print(f"[fetch] archived -> {archive_path}", file=sys.stderr)

    return archive_path, vehicle, firmware_version, (source_url or url)


def ingest(
    html_path: Optional[Path] = None,
    url: Optional[str] = None,
    vehicle: Optional[str] = None,
    firmware_version: Optional[str] = None,
    source_url: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
    build_vectors: bool = False,
    vectors_path: Optional[Path] = None,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    http_client: Optional[httpx.Client] = None,
    verbose: bool = False,
) -> IngestResult:
    """Get the HTML (from disk or a URL) and write every parameter into the DB.

    Pass exactly one of `html_path` or `url`. With `html_path`, `vehicle`
    and `firmware_version` are required. With `url`, both are optional —
    vehicle is auto-detected from the URL path and firmware_version from
    the page text; either can still be passed explicitly to override
    detection.

    Returns an IngestResult(count, vehicle, firmware_version) — the count of
    parameters loaded, plus whatever vehicle/firmware_version were actually
    used (useful when they were auto-detected rather than passed in).

    Existing DB rows for (vehicle, firmware_version) are replaced atomically
    inside a single transaction; other versions remain intact.

    If `build_vectors=True`, also rebuilds the semantic index for this
    (vehicle, firmware_version) after ingest completes.
    """
    if (html_path is None) == (url is None):
        raise ValueError("pass exactly one of html_path or url")

    if url is not None:
        html_path, vehicle, firmware_version, source_url = _fetch_and_archive(
            url=url,
            vehicle=vehicle,
            firmware_version=firmware_version,
            source_url=source_url,
            archive_dir=archive_dir,
            http_client=http_client,
            verbose=verbose,
        )
    else:
        if vehicle is None or firmware_version is None:
            raise ValueError(
                "--vehicle and --firmware-version are required when using --html"
            )
        html_path = Path(html_path).resolve()
        if not html_path.exists():
            raise FileNotFoundError(html_path)

    if verbose:
        print(f"[scrape] {vehicle} {firmware_version}: parsing {Path(html_path).name}",
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

    return IngestResult(len(params), vehicle, firmware_version)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest an ArduPilot parameter reference HTML file into SQLite.",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--html", type=Path,
                               help="Path to the parameters HTML file")
    source_group.add_argument("--url",
                               help="URL to fetch the parameters page from directly, "
                                    "e.g. https://ardupilot.org/copter/docs/parameters.html")
    parser.add_argument("--vehicle", default=None,
                         choices=["plane", "copter", "rover", "sub"],
                         help="Required with --html; auto-detected from --url if omitted")
    parser.add_argument("--firmware-version", default=None,
                         help="Required with --html; auto-detected from the page "
                              "if --url is used and this is omitted")
    parser.add_argument("--source-url", default=None,
                         help="Canonical URL to record with each row "
                              "(defaults to --url if given)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                         help="SQLite DB path")
    parser.add_argument("--build-vectors", action="store_true",
                         help="Also rebuild the semantic index for this version")
    parser.add_argument("--vectors-path", type=Path, default=None,
                         help="LanceDB directory (defaults to data/vectors.lance)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = ingest(
            html_path=args.html,
            url=args.url,
            vehicle=args.vehicle,
            firmware_version=args.firmware_version,
            source_url=args.source_url,
            db_path=args.db,
            build_vectors=args.build_vectors,
            vectors_path=args.vectors_path,
            verbose=not args.quiet,
        )
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        # Non-technical Docker users are the primary audience (per README) —
        # a bare traceback is the wrong default here. ingest()'s own
        # ValueError/RuntimeError messages are already written to be
        # actionable on their own (see _fetch_and_archive).
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"ingested {result.count} parameters "
          f"({result.vehicle} {result.firmware_version}) -> {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
