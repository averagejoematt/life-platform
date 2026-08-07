#!/usr/bin/env python3
"""scripts/coverage_gap_warn.py — self-reminding ratchet for the CI coverage floor
and the Unit Tests suite-duration budget (#1206, #1349).

THE PROBLEM THIS SOLVES:
  The CI coverage gate (.github/workflows/ci-cd.yml, `--cov-fail-under`) is a
  regression floor that must be RATCHETED UP over time (ADR-080/ADR-107). Nobody
  gets reminded to raise it, so the floor silently drifts far below actual measured
  coverage — #1206 found a ~20-point gap (floor 25 vs measured 45.6%), meaning ~45%
  of line coverage could vanish before CI reds. This is the exact drift class the
  #1189 guardrails police for docs, but no check watched the workflow floor itself.

  #1349 adds a second, same-shaped leak: nothing watches the Unit Tests job's own
  wall-clock. The suite went 157s (07-12) -> 195s (07-13) -> 294s (07-18) with no
  standing reminder — the same "silently drifts until someone happens to notice"
  failure mode as the coverage floor, just on suite cost instead of coverage.
  #1966 (2026-08-04) is the budget's first real triage: by then the suite had grown
  5,108 -> 9,396+ tests and the job was measuring 641-725s (avg ~688s) against the
  480s budget it first breached at 520s a week earlier. `pytest --durations=25`
  showed no dominating outlier (slowest single test 6.25s of a 162s local run) —
  honest broad growth, not a few slow tests to trim — so the budget moved to 900s
  (deliberate headroom above the measured range, not a re-derivation of 480 from
  scratch) and #1966 also added the standing-warning triage gate
  (`scripts/check_ci_warnings.py`, /wrap step (e11)) so the NEXT breach can't sit
  unactioned the way this one did. It didn't hold long: the SAME session then
  merged ~200 more tests and breached the new 900s budget too (985s), proof the
  gate does its job (#2152, 2026-08-06). Re-derived from ALL 8 green-main runs in
  the post-#2132 era (704-985s, avg ~830s) — budget moved to 1200s (~22%
  headroom above the observed max / ~45% above the average). See ci-test.yml's
  comment for the full derivation.

WHAT IT DOES:
  (1) Coverage floor drift: parses the `line-rate` attribute off the <coverage>
      root of a Cobertura coverage.xml (produced by `pytest --cov ...
      --cov-report=xml`), compares measured line coverage to the enforced floor,
      and emits a GitHub Actions `::warning::` annotation when the gap exceeds a
      threshold (default 10 points) — so a human is reminded to ratchet the floor
      up.
  (2) Suite-duration budget (optional, #1349, raised #1966, re-raised #2152): when
      `--duration-seconds` is passed (the caller measures its own job
      wall-clock — this script has no way to observe it), emits a `::warning::`
      when the measured duration exceeds `--duration-budget-seconds` (default
      1200s / 20min, derived #2152 — see ci-test.yml's comment for the
      measure-first derivation) — the same self-reminding-ratchet shape as (1),
      applied to suite cost instead of coverage.
  (3) MEASURED-coverage high-water ratchet (#1658, added 2026-08-06): the hole
      the other two leave open. `--cov-fail-under` is deliberately set a few
      points BELOW measured coverage so normal fluctuation doesn't red main —
      but that headroom is completely unguarded. At the floor/measured values
      this check was written against (53 / 57.19%), ~4.2 points of real
      coverage — roughly 2,900 statements — could be deleted with every gate
      still green and check (1) still silent (it only fires when the gap gets
      BIGGER). This check compares measured coverage to a committed high-water
      mark and, with `--fail-on-regression`, EXITS 1 when measured falls more
      than `--high-water-tolerance` points below it. That is what makes the
      ratchet up-only in the thing that actually matters (real coverage) rather
      than only in the literal that describes it.

  Checks (1) and (2) NEVER fail the build: every error path (missing file,
  unparseable XML, missing attribute, missing/invalid duration) is fail-open —
  it prints a note and exits 0. Check (3) is also fail-open by default and only
  becomes enforcing when `--fail-on-regression` is passed (ci-test.yml passes
  it); an unreadable coverage.xml still exits 0 even then, so a parse blip can
  never red main. The floor enforcement itself stays the job of
  `--cov-fail-under`.

USAGE:
  python3 scripts/coverage_gap_warn.py --coverage-xml coverage.xml --floor 40
  python3 scripts/coverage_gap_warn.py --coverage-xml coverage.xml --floor 40 --gap-threshold 10
  python3 scripts/coverage_gap_warn.py --coverage-xml coverage.xml --floor 40 \
      --duration-seconds 830 --duration-budget-seconds 1200
  python3 scripts/coverage_gap_warn.py --coverage-xml coverage.xml --floor 60 \
      --high-water 64.4 --fail-on-regression

EXIT CODE: 0, except when `--fail-on-regression` is passed AND measured coverage
  is more than the tolerance below the high-water mark, in which case 1.
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

# The suite-duration budget's canonical default (#1349, raised #1966, re-raised
# #2152 — see the ci-test.yml comment and coverage_gap_warn.py's module docstring
# above for the measure-first derivation). ci-test.yml always passes
# --duration-budget-seconds explicitly, so this default only matters for a
# bare/manual invocation — but it is also the THIRD literal in the #1349-style
# ratchet (mirrors the coverage floor's three-literal pattern):
# tests/test_duration_budget_ratchet.py asserts this constant, the ci-test.yml
# literal, and its own committed high-water mark all agree, so the three can't
# silently drift apart the way the coverage floor could before #1658.
DEFAULT_DURATION_BUDGET_SECONDS = 1200.0

# How far measured coverage may fall below the committed high-water mark before the
# regression check (3) fails the build (#1658). This is NOT slack to spend — it
# absorbs the honest jitter of a coverage number that moves whenever a test's own
# import graph changes, so the gate catches real deletion instead of flapping on
# noise. 1.5 points is ~1,050 statements at the current ~70k-statement base: far
# more than jitter, far less than the ~4pt floor headroom this check exists to
# close. Tighten it as the suite stabilises; do not widen it to dodge a red.
DEFAULT_HIGH_WATER_TOLERANCE_POINTS = 1.5


def parse_line_rate_pct(coverage_xml_path: str) -> Optional[float]:
    """Return measured line coverage as a percentage (0-100), or None on any failure.

    Cobertura XML stores coverage as a `line-rate` fraction (0.0-1.0) on the
    <coverage> root element. We multiply by 100 to get a percentage.
    """
    try:
        tree = ET.parse(coverage_xml_path)  # noqa: S314 — trusted own-artifact: coverage.xml written by our own pytest --cov run in CI
        root = tree.getroot()
        line_rate = root.get("line-rate")
        if line_rate is None:
            return None
        return float(line_rate) * 100.0
    except (OSError, ET.ParseError, ValueError):
        return None


def evaluate(measured_pct: Optional[float], floor: float, gap_threshold: float) -> Optional[str]:
    """Return a warning message when (measured - floor) > gap_threshold, else None.

    Returns None (silent) when coverage could not be measured (fail-open) or when
    the gap is within threshold.
    """
    if measured_pct is None:
        return None
    gap = measured_pct - floor
    if gap > gap_threshold:
        return (
            f"Coverage floor ({floor:.0f}%) lags measured line coverage "
            f"({measured_pct:.1f}%) by {gap:.1f} points (> {gap_threshold:.0f}). "
            f"Ratchet --cov-fail-under up in .github/workflows/ci-cd.yml (ADR-080/ADR-107)."
        )
    return None


def evaluate_duration(measured_seconds: Optional[float], budget_seconds: float) -> Optional[str]:
    """Return a warning message when measured_seconds > budget_seconds, else None.

    Returns None (silent) when duration wasn't measured (fail-open) or is within
    budget. Mirrors `evaluate()`'s shape but the comparison is a straight ceiling
    (not a gap-vs-threshold), since a duration budget doesn't have a "floor" —
    just a "don't go over this" line.
    """
    if measured_seconds is None:
        return None
    if measured_seconds > budget_seconds:
        return (
            f"Unit Tests job took {measured_seconds:.0f}s, over the {budget_seconds:.0f}s budget "
            f"({measured_seconds - budget_seconds:.0f}s over). Suite wall-clock has climbed before "
            f"(157s -> 294s -> 688s avg -> 830s avg, #1349/#1966/#2152) — this run's /wrap must triage it "
            f"(scripts/check_ci_warnings.py, step (e11)): investigate slow tests, or raise the budget "
            f"deliberately again with the same measure-first rationale."
        )
    return None


def evaluate_high_water(measured_pct: Optional[float], high_water: Optional[float], tolerance: float) -> Tuple[str, Optional[str]]:
    """Compare measured coverage to the committed high-water mark (#1658).

    Returns a ``(status, message)`` tuple where status is one of:

      "skip"     — nothing to say (no measurement, or no high-water configured).
                   Fail-open: the caller must treat this as success.
      "ok"       — measured is at/above the high-water minus tolerance.
      "regress"  — measured fell MORE than ``tolerance`` points below the
                   high-water mark. This is the up-only violation: real coverage
                   was deleted. With --fail-on-regression the caller exits 1.
      "raise"    — measured exceeds the mark by MORE than ``tolerance``, so the
                   committed mark is meaningfully stale and should be ratcheted
                   up. Advisory only: a PR that IMPROVES coverage must never be
                   blocked by the ratchet, it just gets a nudge to bank the gain.

    The asymmetry is the whole point — down is a failure, up is a reminder.

    Note the deadband on the "raise" side is deliberate. Coverage drifts upward a
    few hundredths of a point every time a test is added, so warning on ANY excess
    would emit a `::warning::` on essentially every green run — and standing CI
    warnings are not free here: `scripts/check_ci_warnings.py` (/wrap step (e11))
    obligates a same-session triage decision for each one. A nudge that fires
    constantly is a nudge nobody reads (the #1966 lesson). Requiring the SAME
    tolerance band on both sides means the mark is treated as current while
    measured sits within ±tolerance of it, and only a real accumulation of new
    coverage asks for a re-bank.
    """
    if measured_pct is None or high_water is None:
        return ("skip", None)
    surplus = measured_pct - high_water
    if surplus > tolerance:
        return (
            "raise",
            f"Measured line coverage ({measured_pct:.2f}%) is {surplus:.2f} points ABOVE the committed "
            f"high-water mark ({high_water:.2f}%), past the {tolerance:.2f}pt deadband. Bank the gain: bump "
            f"RATCHET_HIGH_WATER in tests/test_coverage_floor_ratchet.py and the --high-water literal in "
            f"ci-test.yml so the new level becomes the floor of the floor (#1658).",
        )
    shortfall = high_water - measured_pct
    if shortfall > tolerance:
        return (
            "regress",
            f"COVERAGE REGRESSION: measured line coverage ({measured_pct:.2f}%) is {shortfall:.2f} points "
            f"below the committed high-water mark ({high_water:.2f}%), past the {tolerance:.2f}pt tolerance. "
            f"Coverage is up-only (ADR-080/ADR-107, #1658): restore the deleted tests, or — if the drop is "
            f"legitimate (e.g. a covered module was deleted wholesale) — lower RATCHET_HIGH_WATER in "
            f"tests/test_coverage_floor_ratchet.py and the ci-test.yml --high-water literal in the SAME PR, "
            f"with the reason in the PR body.",
        )
    return (
        "ok",
        f"coverage_gap_warn: measured {measured_pct:.2f}% within ±{tolerance:.2f}pt of the " f"{high_water:.2f}% high-water mark; OK.",
    )


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Warn when the CI coverage floor lags measured coverage, and/or when the Unit "
        "Tests job exceeds a duration budget (both advisory, fail-open)."
    )
    parser.add_argument("--coverage-xml", default="coverage.xml", help="Path to Cobertura coverage.xml (default: coverage.xml).")
    parser.add_argument("--floor", type=float, required=True, help="The enforced --cov-fail-under floor, in percent.")
    parser.add_argument(
        "--gap-threshold", type=float, default=10.0, help="Emit a warning when the gap exceeds this many points (default: 10)."
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Measured Unit Tests job wall-clock, in seconds (#1349). Omit to skip the duration check entirely.",
    )
    parser.add_argument(
        "--duration-budget-seconds",
        type=float,
        default=DEFAULT_DURATION_BUDGET_SECONDS,
        help=f"Emit a warning when --duration-seconds exceeds this (default: {DEFAULT_DURATION_BUDGET_SECONDS:.0f}s / 15min).",
    )
    parser.add_argument(
        "--high-water",
        type=float,
        default=None,
        help="Committed measured-coverage high-water mark, in percent (#1658). Omit to skip the regression check entirely.",
    )
    parser.add_argument(
        "--high-water-tolerance",
        type=float,
        default=DEFAULT_HIGH_WATER_TOLERANCE_POINTS,
        help=(
            "How far measured coverage may fall below --high-water before the regression check trips "
            f"(default: {DEFAULT_HIGH_WATER_TOLERANCE_POINTS}pt)."
        ),
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit 1 when measured coverage regresses past the --high-water tolerance (#1658). Default is advisory-only.",
    )
    args = parser.parse_args(argv)

    measured_pct = parse_line_rate_pct(args.coverage_xml)
    if measured_pct is None:
        # Fail-open: never red the build over a missing/unparseable coverage file.
        print(f"coverage_gap_warn: could not read line-rate from {args.coverage_xml!r}; skipping (advisory).")
    else:
        message = evaluate(measured_pct, args.floor, args.gap_threshold)
        if message:
            # GitHub Actions annotation — surfaces on the run + the PR, non-fatal.
            print(f"::warning title=Coverage floor is drifting::{message}")
        else:
            print(
                f"coverage_gap_warn: floor {args.floor:.0f}% vs measured {measured_pct:.1f}% "
                f"within {args.gap_threshold:.0f}pt threshold; OK."
            )

    if args.duration_seconds is not None:
        duration_message = evaluate_duration(args.duration_seconds, args.duration_budget_seconds)
        if duration_message:
            print(f"::warning title=Unit Tests job is over its duration budget::{duration_message}")
        else:
            print(f"coverage_gap_warn: duration {args.duration_seconds:.0f}s within " f"{args.duration_budget_seconds:.0f}s budget; OK.")

    # (3) #1658 — the measured-coverage high-water ratchet. Only this check can
    # fail the build, and only when the caller opted in with --fail-on-regression.
    status, hw_message = evaluate_high_water(measured_pct, args.high_water, args.high_water_tolerance)
    if status == "regress":
        print(f"::error title=Coverage regressed below the high-water mark::{hw_message}")
        if args.fail_on_regression:
            return 1
    elif status == "raise":
        print(f"::warning title=Coverage high-water mark is stale::{hw_message}")
    elif status == "ok":
        print(hw_message)

    return 0


if __name__ == "__main__":
    sys.exit(main())
