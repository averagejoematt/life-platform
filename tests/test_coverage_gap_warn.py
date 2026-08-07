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


# ---- evaluate_high_water: the #1658 measured-coverage regression ratchet -----
#
# This is the check that closes the hole the other two leave: --cov-fail-under sits
# deliberately BELOW measured coverage for anti-flap headroom, and nothing watched
# that headroom. These tests pin the asymmetry that makes the ratchet up-only —
# a drop past tolerance is an ERROR, a rise is only a nudge.


def test_evaluate_high_water_regression_past_tolerance_is_an_error():
    status, msg = cgw.evaluate_high_water(60.0, 64.5, 1.5)
    assert status == "regress"
    # The message must name both numbers and the shortfall so the CI annotation is
    # actionable without opening the artifact.
    assert "60.00" in msg and "64.50" in msg and "4.50" in msg


def test_evaluate_high_water_drop_within_tolerance_is_ok():
    """A 1.0pt dip under a 1.5pt tolerance is jitter, not deletion — must not trip."""
    status, msg = cgw.evaluate_high_water(63.5, 64.5, 1.5)
    assert status == "ok"
    assert "OK" in msg


def test_evaluate_high_water_boundary_exactly_at_tolerance_is_ok():
    """Exactly at the tolerance is NOT a regression — the comparison is strict `>`,
    matching evaluate()/evaluate_duration()'s boundary semantics."""
    status, _ = cgw.evaluate_high_water(63.0, 64.5, 1.5)
    assert status == "ok"


def test_evaluate_high_water_just_past_tolerance_regresses():
    status, _ = cgw.evaluate_high_water(62.99, 64.5, 1.5)
    assert status == "regress"


def test_evaluate_high_water_well_above_mark_asks_for_a_raise_not_a_failure():
    """A PR that IMPROVES coverage must never be blocked — it gets a nudge to bank it."""
    status, msg = cgw.evaluate_high_water(66.5, 64.5, 1.5)
    assert status == "raise"
    assert "RATCHET_HIGH_WATER" in msg


def test_evaluate_high_water_exactly_at_mark_is_ok_not_raise():
    status, _ = cgw.evaluate_high_water(64.5, 64.5, 1.5)
    assert status == "ok"


def test_evaluate_high_water_small_upward_drift_stays_silent():
    """The deadband that keeps this from warning on every green run: coverage creeps up
    by hundredths whenever a test is added, and a `::warning::` on each one would make
    check_ci_warnings.py (/wrap step (e11)) triage noise forever."""
    status, _ = cgw.evaluate_high_water(64.56, 64.5, 1.5)
    assert status == "ok"


def test_evaluate_high_water_raise_deadband_is_symmetric_with_the_regression_band():
    """Exactly +tolerance is still OK; just past it asks for the re-bank — the same
    strict-`>` boundary the regression side uses."""
    assert cgw.evaluate_high_water(66.0, 64.5, 1.5)[0] == "ok"
    assert cgw.evaluate_high_water(66.01, 64.5, 1.5)[0] == "raise"


def test_evaluate_high_water_unmeasured_or_unconfigured_is_skip():
    """Fail-open on both axes: no coverage.xml, or no --high-water passed."""
    assert cgw.evaluate_high_water(None, 64.5, 1.5) == ("skip", None)
    assert cgw.evaluate_high_water(64.5, None, 1.5) == ("skip", None)


def test_main_high_water_check_is_opt_in(tmp_path, capsys):
    """Omitting --high-water leaves pre-#1658 invocations behaviorally unchanged."""
    path = _write_coverage_xml(tmp_path, "0.5719")
    rc = cgw.main(["--coverage-xml", path, "--floor", "53"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "high-water" not in out.lower()


def test_main_exits_1_on_regression_only_with_fail_flag(tmp_path, capsys):
    path = _write_coverage_xml(tmp_path, "0.5000")
    args = ["--coverage-xml", path, "--floor", "45", "--high-water", "57.19"]

    # Advisory by default: the ::error:: annotation is emitted, but exit stays 0.
    rc_advisory = cgw.main(args)
    assert rc_advisory == 0
    assert "::error" in capsys.readouterr().out

    # Enforcing when the caller opts in — this is what ci-test.yml passes.
    rc_enforced = cgw.main(args + ["--fail-on-regression"])
    assert rc_enforced == 1
    assert "::error" in capsys.readouterr().out


def test_main_improving_coverage_never_fails_even_when_enforcing(tmp_path, capsys):
    """The up-only guarantee: exceeding the mark is a warning and exit 0, never a red."""
    path = _write_coverage_xml(tmp_path, "0.7000")
    rc = cgw.main(["--coverage-xml", path, "--floor", "53", "--high-water", "62.64", "--fail-on-regression"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "::warning title=Coverage high-water mark is stale" in out
    assert "::error" not in out


def test_main_unreadable_coverage_xml_never_reds_the_build(tmp_path, capsys):
    """A parse blip must stay fail-open even under --fail-on-regression — the gate
    exists to catch deleted tests, not to red main on a missing artifact."""
    rc = cgw.main(["--coverage-xml", str(tmp_path / "nope.xml"), "--floor", "53", "--high-water", "57.19", "--fail-on-regression"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "::error" not in out
