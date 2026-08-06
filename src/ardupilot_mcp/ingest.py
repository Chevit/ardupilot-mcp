"""Ingest pipeline: parse an ArduPilot HTML page and load rows into SQLite.

Ingest is scoped to a single vehicle. Re-running against the same vehicle
replaces its rows wholesale (see
docs/adr/0001-single-firmware-version-per-vehicle.md); other vehicles are
left untouched, so you can hold several vehicles side by side, each at its
own one stored firmware version.

Four ways to provide the source page:

    # every enabled vehicle on the Vehicle Roster, one invocation
    uv run python -m ardupilot_mcp.ingest --all --build-vectors

    # only the named vehicles from the Roster (any name in it, enabled or
    # not) — same behaviour as --all, just scoped
    uv run python -m ardupilot_mcp.ingest --roster plane --build-vectors

    # a single vehicle, fetched directly — vehicle and firmware version
    # auto-detected from the URL/page
    uv run python -m ardupilot_mcp.ingest \\
        --url https://ardupilot.org/copter/docs/parameters.html

    # from a page already downloaded to disk
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
from typing import NamedTuple, Optional

import httpx

from .db import (
    DEFAULT_DB_PATH,
    connect,
    init_schema,
    record_ingestion,
    reset_vehicle,
    upsert_parameter,
)
from .fetch import detect_vehicle_from_url, fetch_url
from .roster import VehicleEntry, enabled_vehicles, load_roster
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


class VehicleIngestOutcome(NamedTuple):
    """One vehicle's result within an ingest_all() run. `error` is set (and
    count/firmware_version are None) when that vehicle's fetch/parse/write
    failed — the run continues past it rather than aborting everything."""
    vehicle: str
    success: bool
    count: Optional[int] = None
    firmware_version: Optional[str] = None
    error: Optional[str] = None


def _fetch_and_archive(
    url: str,
    vehicle: Optional[str],
    firmware_version: Optional[str],
    source_url: Optional[str],
    archive_dir: Path,
    http_client: Optional[httpx.Client],
    vehicles_config: Optional[Path],
    verbose: bool,
) -> tuple[Path, str, str, str]:
    """Fetch `url`, auto-detect vehicle/version, archive HTML to disk.

    Returns (archived_html_path, vehicle, firmware_version, source_url) —
    everything `ingest()` needs to fall through to the shared parse step.
    """
    if verbose:
        print(f"[fetch] downloading {url}", file=sys.stderr)
    html = fetch_url(url, client=http_client)

    if vehicle is None:
        roster_names = load_roster(vehicles_config).keys()
        vehicle = detect_vehicle_from_url(url, vehicle_names=roster_names)
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
    vehicles_config: Optional[Path] = None,
    verbose: bool = False,
) -> IngestResult:
    """Get the HTML (from disk or a URL) and write every parameter into the DB.

    Pass exactly one of `html_path` or `url`. With `html_path`, `vehicle`
    and `firmware_version` are required. With `url`, both are optional —
    vehicle is auto-detected from the URL against the Vehicle Roster (see
    roster.py; `vehicles_config` picks a non-default roster for that
    detection) and firmware_version from the page text; either can still be
    passed explicitly to override detection.

    Returns an IngestResult(count, vehicle, firmware_version) — the count of
    parameters loaded, plus whatever vehicle/firmware_version were actually
    used (useful when they were auto-detected rather than passed in).

    Existing DB rows for `vehicle` are replaced wholesale inside a single
    transaction; other vehicles remain intact.

    If `build_vectors=True`, also rebuilds this vehicle's slice of the
    semantic index after ingest completes.
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
            vehicles_config=vehicles_config,
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
        reset_vehicle(conn, vehicle)
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
            vehicle=vehicle,
            db_path=db_path,
            verbose=verbose,
        )

    return IngestResult(len(params), vehicle, firmware_version)


def _resolve_target_vehicles(
    roster: dict[str, VehicleEntry],
    vehicles: Optional[list[str]],
) -> list[str]:
    """Turn the caller's vehicle selection into the list to actually ingest.

    `None` means the unscoped run: every Vehicle with `enabled: true`. A
    list means exactly those Vehicles, whether or not they are enabled — an
    explicit name is a stronger signal than the Roster's `--all` default.

    Every name is validated against the Roster before anything is returned,
    so a typo aborts the whole run rather than costing the correctly-spelled
    vehicles their fetches. Duplicates are collapsed, first occurrence
    winning, so the caller sees progress in the order they asked for.
    """
    if vehicles is None:
        return enabled_vehicles(roster)

    unknown = [name for name in vehicles if name not in roster]
    if unknown:
        raise ValueError(
            f"unknown vehicle {', '.join(repr(n) for n in unknown)}; "
            f"the Vehicle Roster has: {', '.join(sorted(roster))}"
        )

    deduped: list[str] = []
    for name in vehicles:
        if name not in deduped:
            deduped.append(name)
    return deduped


def ingest_all(
    vehicles: Optional[list[str]] = None,
    vehicles_config: Optional[Path] = None,
    db_path: Path = DEFAULT_DB_PATH,
    build_vectors: bool = False,
    vectors_path: Optional[Path] = None,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    http_client: Optional[httpx.Client] = None,
    verbose: bool = False,
) -> list[VehicleIngestOutcome]:
    """Ingest several Vehicles from the Roster in one call.

    `vehicles=None` ingests every enabled Vehicle on the Roster (the `--all`
    run). Passing a list of names ingests exactly those instead (`--roster`),
    ignoring their `enabled` flag; unknown names raise ValueError before any
    fetch happens. See `_resolve_target_vehicles`.

    One vehicle failing (network error, undetectable version, ...) does not
    abort the run — ingest is already atomic per vehicle, so a partial run
    leaves no torn state. Every vehicle is attempted; outcomes are returned
    for the caller (main()) to report and turn into a non-zero exit code.

    If `build_vectors=True`, the semantic index is rebuilt once at the end,
    covering every vehicle that succeeded — not once per vehicle, since that
    would reload the embedding model on every single vehicle.
    """
    roster = load_roster(vehicles_config)
    outcomes: list[VehicleIngestOutcome] = []

    for name in _resolve_target_vehicles(roster, vehicles):
        entry = roster[name]
        try:
            result = ingest(
                url=entry.url,
                vehicle=name,
                db_path=db_path,
                build_vectors=False,
                archive_dir=archive_dir,
                http_client=http_client,
                vehicles_config=vehicles_config,
                verbose=verbose,
            )
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            if verbose:
                print(f"[ingest] {name}: FAILED — {exc}", file=sys.stderr)
            outcomes.append(VehicleIngestOutcome(vehicle=name, success=False, error=str(exc)))
            continue
        outcomes.append(VehicleIngestOutcome(
            vehicle=name, success=True,
            count=result.count, firmware_version=result.firmware_version,
        ))

    if build_vectors:
        succeeded = [o.vehicle for o in outcomes if o.success]
        if succeeded:
            from .vectors import VectorStore, rebuild_from_db, DEFAULT_VECTORS_PATH
            store = VectorStore(path=vectors_path or DEFAULT_VECTORS_PATH)
            for name in succeeded:
                rebuild_from_db(store, vehicle=name, db_path=db_path, verbose=verbose)

    return outcomes


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest ArduPilot parameter reference HTML into SQLite.",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--html", type=Path,
                               help="Path to the parameters HTML file")
    source_group.add_argument("--url",
                               help="URL to fetch the parameters page from directly, "
                                    "e.g. https://ardupilot.org/copter/docs/parameters.html")
    source_group.add_argument("--all", action="store_true",
                               help="Ingest every enabled vehicle on the Vehicle Roster")
    source_group.add_argument("--roster", nargs="+", metavar="VEHICLE", default=None,
                               help="Ingest only the named vehicles from the Vehicle Roster, "
                                    "e.g. --roster plane copter. Works for vehicles marked "
                                    "enabled: false, which only --all skips")
    parser.add_argument("--vehicle", default=None,
                         help="Required with --html; auto-detected from --url if omitted "
                              "(against the Vehicle Roster's known names)")
    parser.add_argument("--firmware-version", default=None,
                         help="Required with --html; auto-detected from the page "
                              "if --url is used and this is omitted")
    parser.add_argument("--source-url", default=None,
                         help="Canonical URL to record with each row "
                              "(defaults to --url if given)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                         help="SQLite DB path")
    parser.add_argument("--build-vectors", action="store_true",
                         help="Also rebuild the semantic index for the ingested vehicle(s)")
    parser.add_argument("--vectors-path", type=Path, default=None,
                         help="LanceDB directory (defaults to data/vectors.lance)")
    parser.add_argument("--vehicles-config", type=Path, default=None,
                         help="Vehicle Roster JSON path (default: data/vehicles.json "
                              "if present, else the packaged roster)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.all or args.roster:
        # Every vehicle's URL comes from the Roster and its firmware version
        # from the fetched page, so these three can't mean anything here.
        # Dropping them silently would make e.g.
        # `--roster plane --firmware-version 4.7.0` look like it pinned a
        # version when it didn't.
        conflicting = [
            flag for flag, value in (
                ("--vehicle", args.vehicle),
                ("--firmware-version", args.firmware_version),
                ("--source-url", args.source_url),
            ) if value is not None
        ]
        if conflicting:
            parser.error(
                f"{', '.join(conflicting)} cannot be combined with --all/--roster "
                "(vehicle comes from the Vehicle Roster, firmware version from the page)"
            )

        try:
            outcomes = ingest_all(
                vehicles=args.roster,
                vehicles_config=args.vehicles_config,
                db_path=args.db,
                build_vectors=args.build_vectors,
                vectors_path=args.vectors_path,
                verbose=not args.quiet,
            )
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            # Unknown --roster name, or an unreadable --vehicles-config.
            # Same reasoning as the single-vehicle handler below: a clean
            # one-liner, not a traceback.
            print(f"error: {exc}", file=sys.stderr)
            return 1

        failed = [o for o in outcomes if not o.success]
        for o in outcomes:
            if o.success:
                print(f"ingested {o.count} parameters ({o.vehicle} {o.firmware_version}) -> {args.db}")
            else:
                print(f"error: {o.vehicle}: {o.error}", file=sys.stderr)
        return 1 if failed else 0

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
            vehicles_config=args.vehicles_config,
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
