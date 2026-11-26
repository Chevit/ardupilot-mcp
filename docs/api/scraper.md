# scraper

Parses ArduPilot's Sphinx-generated parameter reference HTML into [`Parameter`](db.md#parameter) records.

## Overview

Each parameter on the page is a `<section>` with an `<h3>` heading `NAME[ (BackendClass)]: Display Name`, optional
"advanced users" / "reboot required" line-blocks, description `<p>`s, and a metadata table (Range, Units, Increment,
Values, Bitmask, ReadOnly). Values and Bitmask cells hold nested Value|Meaning or Bit|Meaning tables. The parameter's
section name comes from the nearest enclosing `<section>` with an `<h2>`. Verified against Plane 4.6 and 4.8.

Headings that don't match the `NAME: Display` shape are skipped. Unparseable ranges or increments leave those fields
`None`. Other columns (Calibration, Volatile, ...) are ignored.

## Public API

### detect_version

```python
def detect_version(html: str) -> str | None
```

Returns the first `V<major>.<minor>.<patch>` token in the page (e.g. `"...latest V4.8.0 dev"` → `"4.8.0"`), or
`None`.

### parse_html

```python
def parse_html(html: str, vehicle: str, firmware_version: str, source_url: str | None = None) -> list[Parameter]
```

Parses a page held in memory (with the `lxml` parser). Every returned `Parameter` is tagged with the given vehicle,
version and source URL.

### parse_html_file

```python
def parse_html_file(path: Path, vehicle: str, firmware_version: str,
                    source_url: str | None = None) -> list[Parameter]
```

Reads `path` as UTF-8 and calls `parse_html`.

## Usage examples

```python
from ardupilot_mcp.scraper import detect_version, parse_html

html = open("parameters.html", encoding="utf-8").read()
params = parse_html(html, vehicle="plane", firmware_version=detect_version(html) or "unknown")
print(len(params), params[0].name, params[0].range_min, params[0].range_max)
```

## Dependencies

- `beautifulsoup4` with the `lxml` parser.
