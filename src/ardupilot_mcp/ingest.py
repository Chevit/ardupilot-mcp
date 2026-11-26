"""Ingest pipeline: get an ArduPilot parameters page, load it into SQLite,
optionally rebuild the semantic index.

Three steps, each its own function: `fetch_page` (URL) or `read_page`
(saved file) produce a `Page`; `load` writes it to SQLite; `rebuild_vectors`
refreshes the semantic index once for every Vehicle loaded. `ingest_all`
and `main` compose them.

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
from typing import Iterable, NamedTuple

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
from .scraper import detect_version, parse_html

DEFAULT_ARCHIVE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "ardupilot-docs"
)


class Page(NamedTuple):
    """One Vehicle's parameter reference page, ready to load.

    Produced by `fetch_page` (URL) or `read_page` (saved file); consumed by
    `load`. `source_path` is where the HTML lives on disk — the archive copy
    for a fetched page — and is recorded in the ingestions table.
    """
    html: str
    vehicle: str
    firmware_version: str
    source_url: str | None
    source_path: Path


class VehicleIngestOutcome(NamedTuple):
    """One vehicle's result within an ingest_all() run. `error` is set (and
    count/firmware_version are None) when that vehicle's fetch/parse/write
    failed — the run continues past it rather than aborting everything."""
    vehicle: str
    success: bool
    count: int | None = None
    firmware_version: str | None = None
    error: str | None = None


def fetch_page(
    url: str,
    vehicle: str | None = None,
    firmware_version: str | None = None,
    source_url: str | None = None,
    vehicle_names: Iterable[str] | None = None,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    http_client: httpx.Client | None = None,
    verbose: bool = False,
) -> Page:
    """Download `url`, detect its vehicle/version, and archive the HTML.

    Args:
        url: The ardupilot.org parameters page to fetch.
        vehicle: Overrides detection from the URL.
        firmware_version: Overrides detection from the page text.
        source_url: Canonical URL to record; defaults to `url`.
        vehicle_names: Names the URL is matched against when `vehicle` is
            None; defaults to the packaged/overridden Vehicle Roster's keys.
        archive_dir: Where the fetched HTML is saved.
        http_client: Client used for fetching; `None` creates a default one.
        verbose: Print progress to stderr.

    Raises:
        RuntimeError: If the fetch fails.
        ValueError: If vehicle or firmware version can't be detected.
    """
    if verbose:
        print(f"[fetch] downloading {url}", file=sys.stderr)
    html = fetch_url(url, client=http_client)

    if vehicle is None:
        vehicle = detect_vehicle_from_url(url, vehicle_names=vehicle_names)
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
    archive_path = archive_dir / (
        f"Complete Parameter List — {vehicle.capitalize()} documentation "
        f"{firmware_version}.html"
    )
    archive_path.write_text(html, encoding="utf-8")
    if verbose:
        print(f"[fetch] archived -> {archive_path}", file=sys.stderr)

    return Page(html, vehicle, firmware_version, source_url or url, archive_path)


def read_page(
    html_path: Path,
    vehicle: str,
    firmware_version: str,
    source_url: str | None = None,
) -> Page:
    """Read a parameters page saved to disk.

    Args:
        html_path: The saved HTML file.
        vehicle: Which Vehicle the page describes.
        firmware_version: Which Firmware version the page describes.
        source_url: Canonical URL to record with each row, if known.

    Raises:
        FileNotFoundError: If `html_path` doesn't exist.
    """
    html_path = Path(html_path).resolve()
    if not html_path.exists():
        raise FileNotFoundError(html_path)
    html = html_path.read_text(encoding="utf-8")
    return Page(html, vehicle, firmware_version, source_url, html_path)


def load(page: Page, db_path: Path = DEFAULT_DB_PATH, verbose: bool = False) -> int:
    """Parse `page` and replace its Vehicle's rows in SQLite.

    The Vehicle's existing rows are replaced wholesale inside one
    transaction (ADR 0001); other Vehicles are untouched. The semantic index
    is not touched — see `rebuild_vectors`.

    Args:
        page: From `fetch_page` or `read_page`.
        db_path: SQLite database to write into.
        verbose: Print progress to stderr.

    Returns:
        The number of parameters loaded.
    """
    if verbose:
        print(f"[scrape] {page.vehicle} {page.firmware_version}: "
              f"parsing {page.source_path.name}", file=sys.stderr)
    params = parse_html(
        page.html,
        vehicle=page.vehicle,
        firmware_version=page.firmware_version,
        source_url=page.source_url,
    )
    if verbose:
        print(f"[scrape] got {len(params)} parameters", file=sys.stderr)

    init_schema(db_path)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        reset_vehicle(conn, page.vehicle)
        for p in params:
            upsert_parameter(conn, p, scraped_at)
        record_ingestion(
            conn, page.vehicle, page.firmware_version, str(page.source_path),
            scraped_at, len(params),
        )

    if verbose:
        print(f"[db] wrote {len(params)} rows -> {db_path}", file=sys.stderr)
    return len(params)


def rebuild_vectors(
    vehicles: list[str],
    db_path: Path = DEFAULT_DB_PATH,
    vectors_path: Path | None = None,
    verbose: bool = False,
) -> None:
    """Rebuild the semantic index for `vehicles` from SQLite, with one
    VectorStore so the embedding model loads once for all of them.

    Args:
        vehicles: Vehicles to rebuild; each must already be loaded.
        db_path: SQLite database to read from.
        vectors_path: LanceDB directory; `None` uses the default location.
        verbose: Print progress to stderr.
    """
    if not vehicles:
        return
    # Imported lazily so users who never enable vectors don't pay the
    # sentence-transformers / torch import cost.
    from .vectors import DEFAULT_VECTORS_PATH, VectorStore, rebuild_from_db
    store = VectorStore(path=vectors_path or DEFAULT_VECTORS_PATH)
    for name in vehicles:
        rebuild_from_db(store, vehicle=name, db_path=db_path, verbose=verbose)


def _resolve_target_vehicles(
    roster: dict[str, VehicleEntry],
    vehicles: list[str] | None,
) -> list[str]:
    """Turn the caller's vehicle selection into the list to actually ingest.

    `None` means the unscoped run: every Vehicle with `enabled: true`. A
    list means exactly those Vehicles, whether or not they are enabled — an
    explicit name is a stronger signal than the Roster's `--all` default.

    Every name is validated against the Roster before anything is returned,
    so a typo aborts the whole run rather than costing the correctly-spelled
    vehicles their fetches. Duplicates are collapsed, first occurrence
    winning, so the caller sees progress in the order they asked for.

    Args:
        roster: The loaded Vehicle Roster, keyed by vehicle name.
        vehicles: Names to ingest, or `None` for every enabled Vehicle.

    Returns:
        The vehicle names to ingest, in order, without duplicates.

    Raises:
        ValueError: If any name in `vehicles` is not on the Roster.
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
    vehicles: list[str] | None = None,
    vehicles_config: Path | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    build_vectors: bool = False,
    vectors_path: Path | None = None,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    http_client: httpx.Client | None = None,
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

    Args:
        vehicles: Roster names to ingest, or `None` for every enabled Vehicle.
        vehicles_config: Path to a non-default Vehicle Roster file.
        db_path: SQLite database to write into.
        build_vectors: Rebuild the semantic index once after all vehicles.
        vectors_path: LanceDB directory; `None` uses the default location.
        archive_dir: Where fetched HTML pages are saved.
        http_client: Client used for fetching; `None` creates a default one.
        verbose: Print progress for each vehicle.

    Returns:
        One VehicleIngestOutcome per vehicle attempted, in ingest order.

    Raises:
        ValueError: If `vehicles` names a vehicle not on the Roster.
    """
    roster = load_roster(vehicles_config)
    outcomes: list[VehicleIngestOutcome] = []

    for name in _resolve_target_vehicles(roster, vehicles):
        try:
            page = fetch_page(
                roster[name].url, vehicle=name, archive_dir=archive_dir,
                http_client=http_client, verbose=verbose,
            )
            count = load(page, db_path=db_path, verbose=verbose)
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            if verbose:
                print(f"[ingest] {name}: FAILED — {exc}", file=sys.stderr)
            outcomes.append(VehicleIngestOutcome(vehicle=name, success=False, error=str(exc)))
            continue
        outcomes.append(VehicleIngestOutcome(
            vehicle=name, success=True,
            count=count, firmware_version=page.firmware_version,
        ))

    if build_vectors:
        rebuild_vectors(
            [o.vehicle for o in outcomes if o.success],
            db_path=db_path, vectors_path=vectors_path, verbose=verbose,
        )

    return outcomes


def main(argv: list[str] | None = None) -> int:
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

    verbose = not args.quiet
    try:
        if args.url is not None:
            # The Roster is only needed to detect the vehicle from the URL;
            # an explicit --vehicle skips loading it.
            names = (None if args.vehicle is not None
                     else load_roster(args.vehicles_config).keys())
            page = fetch_page(
                args.url, vehicle=args.vehicle,
                firmware_version=args.firmware_version,
                source_url=args.source_url, vehicle_names=names, verbose=verbose,
            )
        else:
            if args.vehicle is None or args.firmware_version is None:
                raise ValueError(
                    "--vehicle and --firmware-version are required when using --html"
                )
            page = read_page(args.html, args.vehicle, args.firmware_version,
                             args.source_url)
        count = load(page, db_path=args.db, verbose=verbose)
        if args.build_vectors:
            rebuild_vectors([page.vehicle], db_path=args.db,
                            vectors_path=args.vectors_path, verbose=verbose)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        # Non-technical Docker users are the primary audience (per README) —
        # a bare traceback is the wrong default here. fetch_page()'s own
        # ValueError/RuntimeError messages are already written to be
        # actionable on their own.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"ingested {count} parameters "
          f"({page.vehicle} {page.firmware_version}) -> {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
