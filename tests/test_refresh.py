"""Tests for scripts/refresh.py.

Loaded via importlib rather than sys.path manipulation since scripts/ isn't
part of the installed ardupilot_mcp package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "refresh.py"


def _load_refresh_module():
    spec = importlib.util.spec_from_file_location("refresh", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def refresh():
    return _load_refresh_module()


def test_discover_pairs_parses_known_filenames(refresh, tmp_path):
    (tmp_path / "Complete Parameter List — Plane documentation 4.8.0.html").write_text("")
    (tmp_path / "Complete Parameter List — Copter documentation 4.5.0.html").write_text("")

    pairs = refresh.discover_pairs(tmp_path)

    assert sorted((vehicle, fw) for vehicle, fw, _ in pairs) == [
        ("copter", "4.5.0"),
        ("plane", "4.8.0"),
    ]


def test_discover_pairs_skips_unrecognized_files(refresh, tmp_path, capsys):
    # .glob("*.html") only enumerates HTML files in the first place — a
    # stray non-HTML file (e.g. notes.txt) is never a candidate and never
    # reaches the warning branch. What DOES reach it: an .html file that
    # doesn't match the naming convention.
    (tmp_path / "Complete Parameter List — Plane documentation 4.8.0.html").write_text("")
    (tmp_path / "random_export.html").write_text("")

    pairs = refresh.discover_pairs(tmp_path)

    assert [(vehicle, fw) for vehicle, fw, _ in pairs] == [("plane", "4.8.0")]
    assert "skipping unrecognized file: random_export.html" in capsys.readouterr().err
