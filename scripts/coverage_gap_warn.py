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

WHAT IT DOES:
  (1) Coverage floor drift: parses the `line-rate` attribute off the <coverage>
      root of a Cobertura coverage.xml (produced by `pytest --cov ...
      --cov-report=xml`), compares measured line coverage to the enforced floor,
      and emits a GitHub Actions `::warning::` annotation when the gap exceeds a
      threshold (default 10 points) — so a human is reminded to ratchet the floor
      up.
  (2) Suite-duration budget (optional, #1349): when `--duration-seconds` is
      passed (the caller measures its own job wall-clock — this script has no
      way to observe it), emits a `::warning::` when the measured duration
      exceeds `--duration-budget-seconds` (default 480s / 8min) — the same
      self-reminding-ratchet shape as (1), applied to suite cost instead of
      coverage.
  It NEVER fails the build: every error path (missing file, unparseable XML,
  missing attribute, missing/invalid duration) is fail-open — it prints a note
  and exits 0. The floor enforcement itself stays the job of `--cov-fail-under`;
  both checks here are advisory only.

USAGE:
  python3 scripts/coverage_gap_warn.py --coverage-xml coverage.xml --floor 40
  python3 scripts/coverage_gap_warn.py --coverage-xml coverage.xml --floor 40 --gap-threshold 10
  python3 scripts/coverage_gap_warn.py --coverage-xml coverage.xml --floor 40 \
      --duration-seconds 294 --duration-budget-seconds 480

EXIT CODE: always 0 (advisory; a parse blip must never red the build).
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from typing import Optional


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
            f"({measured_seconds - budget_seconds:.0f}s over). Suite wall-clock has been climbing "
            f"(157s -> 294s over 6 days, #1349) — investigate slow tests or raise the budget deliberately."
        )
    return None


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
        default=480.0,
        help="Emit a warning when --duration-seconds exceeds this (default: 480s / 8min).",
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
