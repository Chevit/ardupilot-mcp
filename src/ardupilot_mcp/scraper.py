"""HTML parser for ArduPilot parameter reference pages.

Structure per parameter (Sphinx-generated, verified against Plane 4.6 and 4.8):

    <section id="param-slug-display-slug">
      <span id="param-slug"></span>
      <h3>PARAM_NAME[ (BackendClass)]: Display Name<a>...¶</a></h3>
      [<div class="line-block">...advanced users note...</div>]
      <p>Description.</p>
      <div class="wy-table-responsive">
        <table>
          <thead><tr><th>Range</th><th>Units</th>...</tr></thead>
          <tbody><tr><td>-100 to 100</td><td>meters</td>...</tr></tbody>
        </table>
      </div>
    </section>

Values/Bitmask columns contain nested tables with Value|Meaning or Bit|Meaning.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, Optional

from bs4 import BeautifulSoup, Tag

from .db import Parameter, ParameterValue


# "PARAM_NAME (BackendClass): Display" or "PARAM_NAME: Display"
_HEADING_RE = re.compile(
    r"^([A-Z][A-Z0-9_]+)(?:\s*\(([^)]+)\))?\s*:\s*(.*?)\s*$"
)

# "-100 to 100" | "0.0 1.0" | "0 65535"
_RANGE_RE = re.compile(r"^\s*(-?[\d.]+)\s+(?:to\s+)?(-?[\d.]+)\s*$")


def parse_html_file(
    path: Path,
    vehicle: str,
    firmware_version: str,
    source_url: Optional[str] = None,
) -> list[Parameter]:
    """Parse a Sphinx-generated ArduPilot parameters HTML page.

    Every returned Parameter is tagged with the given vehicle and
    firmware_version so it can be stored alongside other versions.
    """
    html = Path(path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    return list(_iter_parameters(soup, vehicle, firmware_version, source_url))


def _iter_parameters(
    soup: BeautifulSoup,
    vehicle: str,
    firmware_version: str,
    source_url: Optional[str],
) -> Iterator[Parameter]:
    for section in soup.find_all("section"):
        h3 = section.find("h3", recursive=False)
        if h3 is None:
            continue
        param = _parse_parameter(section, h3, vehicle, firmware_version, source_url)
        if param is not None:
            yield param


def _parse_parameter(
    section: Tag,
    h3: Tag,
    vehicle: str,
    firmware_version: str,
    source_url: Optional[str],
) -> Optional[Parameter]:
    heading = _clean(h3.get_text())
    m = _HEADING_RE.match(heading)
    if m is None:
        return None
    name, backend, display = m.group(1), m.group(2), m.group(3).strip()

    param = Parameter(
        vehicle=vehicle,
        firmware_version=firmware_version,
        name=name,
        backend=backend,
        display_name=display or None,
        section=_find_section_name(section),
        source_url=source_url,
        advanced=_has_advanced_flag(section),
        reboot_required=_has_reboot_required_flag(section),
        description=_extract_description(section),
    )

    # Metadata table — most Sphinx themes wrap it in <div class="wy-table-responsive">
    # but some versions render the <table> as a direct child of the section.
    # `find("table")` is recursive and returns the first descendant, which is
    # always the outer metadata table (Values/Bitmask cells contain nested
    # tables, but those come later in document order).
    table = section.find("table")
    if table is not None:
        _parse_metadata_table(table, param)

    return param


def _clean(text: str) -> str:
    return text.replace("\u00b6", "").strip()


def _has_advanced_flag(section: Tag) -> bool:
    """Detect the 'Note: This parameter is for advanced users' line-block."""
    for div in section.find_all("div", class_="line-block", recursive=False):
        em = div.find("em", string=re.compile("advanced users", re.I))
        if em is not None:
            return True
    return False


def _has_reboot_required_flag(section: Tag) -> bool:
    """Detect the 'Note: Reboot required after change' line-block."""
    for div in section.find_all("div", class_="line-block", recursive=False):
        em = div.find("em", string=re.compile("reboot required", re.I))
        if em is not None:
            return True
    return False


def _extract_description(section: Tag) -> Optional[str]:
    """Concatenate top-level <p> texts under the section (skips nested)."""
    paragraphs = [
        _clean(p.get_text(" ", strip=True))
        for p in section.find_all("p", recursive=False)
    ]
    joined = "\n\n".join(p for p in paragraphs if p)
    return joined or None


def _find_section_name(param_section: Tag) -> Optional[str]:
    """Walk up until we hit a <section> containing an <h2>; use its text."""
    parent = param_section.find_parent("section")
    while parent is not None:
        h2 = parent.find("h2", recursive=False)
        if h2 is not None:
            return _clean(h2.get_text())
        parent = parent.find_parent("section")
    return None


def _parse_metadata_table(table: Tag, param: Parameter) -> None:
    """Read <thead> for column names, first <tbody> row for values."""
    thead = table.find("thead")
    tbody = table.find("tbody")
    if thead is None or tbody is None:
        return

    headers = [_clean(th.get_text()) for th in thead.find_all("th")]
    row = tbody.find("tr")
    if row is None:
        return
    cells = row.find_all("td", recursive=False)

    for header, cell in zip(headers, cells):
        key = header.lower()
        if key == "range":
            _apply_range(param, _clean(cell.get_text(" ", strip=True)))
        elif key == "units":
            param.units = _clean(cell.get_text(" ", strip=True)) or None
        elif key == "increment":
            try:
                param.increment = float(_clean(cell.get_text()))
            except ValueError:
                pass
        elif key == "values":
            param.values.extend(_parse_nested_values(cell, is_bit=False))
        elif key == "bitmask":
            param.is_bitmask = True
            param.values.extend(_parse_nested_values(cell, is_bit=True))
        elif key == "readonly":
            param.read_only = _clean(cell.get_text()).lower() in {"yes", "true", "1"}
        # Calibration / Volatile / (any future column): ignored for now.


def _parse_nested_values(cell: Tag, is_bit: bool) -> list[ParameterValue]:
    """Parse the nested Value|Meaning (or Bit|Meaning) table inside a cell."""
    inner = cell.find("table")
    if inner is None:
        return []
    body = inner.find("tbody")
    if body is None:
        return []
    out: list[ParameterValue] = []
    for row in body.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        out.append(
            ParameterValue(
                value=_clean(tds[0].get_text()),
                label=_clean(tds[1].get_text(" ", strip=True)),
                is_bit=is_bit,
            )
        )
    return out


def _apply_range(param: Parameter, text: str) -> None:
    m = _RANGE_RE.match(text)
    if m is None:
        return
    try:
        param.range_min = float(m.group(1))
        param.range_max = float(m.group(2))
    except ValueError:
        pass