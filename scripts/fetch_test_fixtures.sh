#!/usr/bin/env bash
# Regenerate tests/fixtures/ — the golden HTML the scraper's golden tests
# (tests/test_scraper.py) run against. Deliberately separate from
# data/ardupilot-docs/, which `ardupilot-refresh` reads/writes: an ingest run
# must never silently change what the test suite asserts against.
#
# 4.6.3 is pinned to a stable, versioned URL and will never change upstream.
# 4.8.0 is the current stable and has no versioned URL to pin to (ArduPilot
# only publishes parameters-<Vehicle>-stable-V<x.y.z>.html for superseded
# versions) — re-running this after 4.8.0 ships an update may require
# re-pinning the golden count in test_pinned_parameter_count_480.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p tests/fixtures

fetch() {
    local url="$1" out="$2"
    echo "fetching $url -> $out" >&2
    curl -sL --fail "$url" -o "tests/fixtures/$out"
}

fetch "https://ardupilot.org/plane/docs/parameters-Plane-stable-V4.6.3.html" \
      "Complete Parameter List — Plane documentation 4.6.3.html"
fetch "https://ardupilot.org/plane/docs/parameters.html" \
      "Complete Parameter List — Plane documentation 4.8.0.html"

echo "done." >&2
