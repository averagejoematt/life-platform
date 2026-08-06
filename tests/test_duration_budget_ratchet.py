"""tests/test_duration_budget_ratchet.py — the suite-duration budget's
three-literal agreement guard (#1966).

The CI suite-duration budget (`coverage_gap_warn.py --duration-budget-seconds`,
#1349) went unenforced by any consistency check: the ONLY place it lived was a bare
literal in one workflow line. #1966 found it breached (520s measured vs the 480s
budget, since climbed further to 641-725s across 9,396+ tests) with nothing making
sure a deliberate raise actually landed everywhere the number is expressed.

This guard mirrors tests/test_coverage_floor_ratchet.py's shape exactly:

  BUDGET_SECONDS below is the committed value. The guard asserts that all THREE
  places the budget is expressed —
    1. scripts/coverage_gap_warn.py  DEFAULT_DURATION_BUDGET_SECONDS  (the
       script's own default, used by any bare/manual invocation)
    2. .github/workflows/ci-test.yml  `--duration-budget-seconds N`  (the value
       CI actually passes every run)
    3. THIS FILE's BUDGET_SECONDS constant                            (the
       committed, reviewable high-water mark)
  are ALL EQUAL.

  Unlike the coverage floor (which is enforced and up-only by construction — a
  regression there silently sheds real coverage), a duration budget can legitimately
  move either direction: up when honest test growth demands headroom (#1966's own
  fix), down after a real optimization pass trims dominating outliers. So this guard
  is agreement-only, not up-only — to change the budget, bump all three literals
  together in one reviewable PR (this test then passes at the new value); a
  one-line drift in just the workflow (or just the script default) reds this test
  instead of silently diverging from what's actually enforced.
"""

import os
import re

# ── THE BUDGET. Bump alongside the two literals below in the SAME PR. ────────
# #1966 (2026-08-04): raised 480 -> 900 after 6 sampled green-main runs measured
# 641-725s (avg ~688s) against a 9,396+-test suite with no dominating outlier in
# `pytest --durations=25` (honest broad growth, not a few slow tests) — 900s is
# ~24% headroom above the observed max.
# #2152 (2026-08-06): the 900s budget breached same-day (985s) after the same
# session merged ~200 more tests — raised 900 -> 1200 after sampling ALL 8
# green-main "Unit Tests" runs in the post-#2132 era: 704/945/745/745/922/764/
# 985/833s (avg ~830s, max 985s). See ci-test.yml's comment for the full
# derivation.
BUDGET_SECONDS = 1200

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPT = os.path.join(_REPO, "scripts", "coverage_gap_warn.py")
_CI_TEST = os.path.join(_REPO, ".github", "workflows", "ci-test.yml")


def _script_default():
    with open(_SCRIPT, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"DEFAULT_DURATION_BUDGET_SECONDS\s*=\s*([\d.]+)", src)
    assert m, "coverage_gap_warn.py no longer defines DEFAULT_DURATION_BUDGET_SECONDS"
    return float(m.group(1))


def _ci_duration_budget():
    with open(_CI_TEST, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"--duration-budget-seconds\s+(\d+)", src)
    assert m, "no --duration-budget-seconds N found in ci-test.yml — the enforced duration budget is missing"
    return int(m.group(1))


def test_script_default_matches_committed_budget():
    assert _script_default() == BUDGET_SECONDS, (
        f"scripts/coverage_gap_warn.py DEFAULT_DURATION_BUDGET_SECONDS={_script_default():.0f} disagrees with "
        f"the committed budget {BUDGET_SECONDS} in this file — bump both together."
    )


def test_ci_test_yml_matches_committed_budget():
    assert _ci_duration_budget() == BUDGET_SECONDS, (
        f"ci-test.yml --duration-budget-seconds={_ci_duration_budget()} disagrees with the committed "
        f"budget {BUDGET_SECONDS} in this file — bump both together."
    )


def test_all_three_budget_literals_agree():
    """The script default, the enforced CI value, and this file's committed budget
    must be the SAME number — otherwise a bare invocation of the script silently
    diverges from what CI actually enforces (the #1206/#1349 drift class, applied
    to duration instead of coverage)."""
    script_default = _script_default()
    ci_value = _ci_duration_budget()
    assert script_default == ci_value == BUDGET_SECONDS, (
        f"duration-budget literals disagree: script default={script_default:.0f}, "
        f"ci-test.yml={ci_value}, committed={BUDGET_SECONDS}. Keep all three in lockstep."
    )
