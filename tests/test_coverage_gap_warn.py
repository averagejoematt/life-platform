"""tests/test_coverage_gap_warn.py — offline guard for the coverage-floor drift warner
and the #1349 suite-duration budget warning it now also carries.

Non-vacuous regression guard for #1206: proves scripts/coverage_gap_warn.py emits a
warning when the floor lags measured coverage by > the threshold, stays silent at/below
the threshold, and is strictly fail-open (missing/garbage coverage.xml never reds CI).

#1349 extends this file to cover the sibling duration-budget check: the suite's own
wall-clock (157s -> 294s over 6 days, no standing reminder) now gets the same
self-reminding-ratchet treatment as the coverage floor, reusing this script rather than
standing up new machinery.
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


# ---- evaluate_duration: the #1349 suite-duration budget check ---------------


def test_evaluate_duration_fires_over_budget():
    # the #1349 evidence condition: 294s measured vs an 8min (480s) budget is
    # under budget today, so pin a case that's actually over it.
    msg = cgw.evaluate_duration(500.0, 480.0)
    assert msg is not None and "budget" in msg.lower()


def test_evaluate_duration_silent_within_budget():
    assert cgw.evaluate_duration(294.0, 480.0) is None


def test_evaluate_duration_boundary_exactly_budget_is_silent():
    # exactly at budget is NOT over -> silent (mirrors the gap-threshold boundary rule)
    assert cgw.evaluate_duration(480.0, 480.0) is None


def test_evaluate_duration_just_over_budget_fires():
    assert cgw.evaluate_duration(480.01, 480.0) is not None


def test_evaluate_duration_none_measured_is_silent():
    # fail-open: no duration measurement never warns
    assert cgw.evaluate_duration(None, 480.0) is None


def test_main_duration_check_is_opt_in(tmp_path, capsys):
    """Omitting --duration-seconds must not touch the duration check at all — existing
    (pre-#1349) invocations of this script stay byte-for-byte behaviorally unchanged."""
    path = _write_coverage_xml(tmp_path, "0.4558")
    rc = cgw.main(["--coverage-xml", path, "--floor", "40"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "duration" not in out.lower()


def test_main_fires_duration_warning_when_over_budget(tmp_path, capsys):
    path = _write_coverage_xml(tmp_path, "0.4558")
    rc = cgw.main(["--coverage-xml", path, "--floor", "40", "--duration-seconds", "600", "--duration-budget-seconds", "480"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "::warning" in out
    assert "600" in out and "480" in out


def test_main_silent_duration_within_budget(tmp_path, capsys):
    path = _write_coverage_xml(tmp_path, "0.4558")
    rc = cgw.main(["--coverage-xml", path, "--floor", "40", "--duration-seconds", "200", "--duration-budget-seconds", "480"])
    out = capsys.readouterr().out
    assert rc == 0
    # coverage is within threshold at floor=40 too, so no ::warning:: of any kind
    assert "::warning" not in out
    assert "OK" in out
