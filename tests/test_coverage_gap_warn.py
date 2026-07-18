"""tests/test_coverage_gap_warn.py — offline guard for the coverage-floor drift warner.

Non-vacuous regression guard for #1206: proves scripts/coverage_gap_warn.py emits a
warning when the floor lags measured coverage by > the threshold, stays silent at/below
the threshold, and is strictly fail-open (missing/garbage coverage.xml never reds CI).
"""

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "coverage_gap_warn.py"
_spec = importlib.util.spec_from_file_location("coverage_gap_warn", _SCRIPT)
cgw = importlib.util.module_from_spec(_spec)
sys.modules["coverage_gap_warn"] = cgw
_spec.loader.exec_module(cgw)


def _write_coverage_xml(tmp_path, line_rate):
    """Write a minimal Cobertura coverage.xml with the given line-rate fraction."""
    p = tmp_path / "coverage.xml"
    p.write_text(f'<?xml version="1.0" ?>\n<coverage line-rate="{line_rate}" version="7.0"></coverage>\n')
    return str(p)


# ---- parse_line_rate_pct ----------------------------------------------------


def test_parse_line_rate_pct_reads_fraction_as_percent(tmp_path):
    path = _write_coverage_xml(tmp_path, "0.4558")
    assert cgw.parse_line_rate_pct(path) == 45.58


def test_parse_line_rate_pct_missing_file_returns_none(tmp_path):
    assert cgw.parse_line_rate_pct(str(tmp_path / "nope.xml")) is None


def test_parse_line_rate_pct_garbage_returns_none(tmp_path):
    p = tmp_path / "coverage.xml"
    p.write_text("not xml <<<")
    assert cgw.parse_line_rate_pct(str(p)) is None


def test_parse_line_rate_pct_missing_attribute_returns_none(tmp_path):
    p = tmp_path / "coverage.xml"
    p.write_text('<?xml version="1.0" ?>\n<coverage version="7.0"></coverage>\n')
    assert cgw.parse_line_rate_pct(str(p)) is None


# ---- evaluate: the core guard logic -----------------------------------------


def test_evaluate_fires_above_threshold():
    # measured 45.6, floor 25 -> gap 20.6 > 10 -> warns (the exact #1206 condition)
    msg = cgw.evaluate(45.6, 25.0, 10.0)
    assert msg is not None and "Ratchet" in msg


def test_evaluate_silent_at_ratcheted_floor():
    # measured 45.6, floor 40 -> gap 5.6 <= 10 -> silent (the post-fix state)
    assert cgw.evaluate(45.6, 40.0, 10.0) is None


def test_evaluate_boundary_exactly_threshold_is_silent():
    # gap == 10 is NOT > 10 -> silent
    assert cgw.evaluate(50.0, 40.0, 10.0) is None


def test_evaluate_just_over_threshold_fires():
    assert cgw.evaluate(50.01, 40.0, 10.0) is not None


def test_evaluate_none_measured_is_silent():
    # fail-open: unmeasurable coverage never warns
    assert cgw.evaluate(None, 40.0, 10.0) is None


# ---- main(): end-to-end, always exit 0 --------------------------------------


def test_main_fires_warning_at_large_gap(tmp_path, capsys):
    path = _write_coverage_xml(tmp_path, "0.4558")
    rc = cgw.main(["--coverage-xml", path, "--floor", "25"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "::warning" in out


def test_main_silent_at_small_gap(tmp_path, capsys):
    path = _write_coverage_xml(tmp_path, "0.4558")
    rc = cgw.main(["--coverage-xml", path, "--floor", "40"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "::warning" not in out
    assert "OK" in out


def test_main_fail_open_on_missing_file(tmp_path, capsys):
    rc = cgw.main(["--coverage-xml", str(tmp_path / "absent.xml"), "--floor", "40"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "::warning" not in out
