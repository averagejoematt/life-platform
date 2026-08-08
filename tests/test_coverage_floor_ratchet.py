"""tests/test_coverage_floor_ratchet.py — #1658: the UP-ONLY coverage-floor ratchet.

The CI coverage gate (`--cov-fail-under`) is a regression floor that must only ever
RISE (ADR-080/ADR-107). Before this guard it was a bare literal in one workflow line,
so a PR could silently lower it and shed real coverage with nobody the wiser (#1206
found it had drifted ~20pts below measured for exactly that reason).

This guard makes the floor a ratchet:

  RATCHET_FLOOR below is the committed high-water mark. The guard asserts that all
  THREE places the floor is expressed —
    1. pyproject.toml  [tool.coverage.report] fail_under   (canonical; coverage.py reads it)
    2. .github/workflows/ci-cd.yml  `--cov-fail-under=N`   (the enforced CI gate)
    3. .github/workflows/ci-cd.yml  coverage_gap_warn `--floor N`  (the drift reminder)
  are ALL EQUAL and NEVER BELOW RATCHET_FLOOR.

  Up-only semantics: to RAISE the floor, bump all three literals AND RATCHET_FLOOR
  together (this test then passes at the higher value). To LOWER the real gate you
  would have to edit RATCHET_FLOOR here too — a deliberate, reviewable change to a
  file whose whole purpose is the banner "the floor can only go up." A silent
  one-line drop in the workflow reds this test instead of shipping.

THE SECOND RATCHET (#1658, 2026-08-06) — MEASURED coverage, not just the literal:

  The floor above is deliberately set a few points BELOW measured coverage so
  ordinary fluctuation doesn't red main. That headroom was entirely unguarded:
  at the values that motivated this (floor 53, measured 57.19%), ~4.2 points —
  roughly 2,900 statements — could be deleted with every gate still green, and
  the gap-warner stays silent because it only fires when the gap GROWS.

  RATCHET_HIGH_WATER below closes it. It records measured line coverage as of the
  PR that last raised it; CI passes it to `coverage_gap_warn.py --high-water
  --fail-on-regression`, which EXITS 1 when measured falls more than the
  tolerance (1.5pt) below it. The asymmetry is deliberate: a drop past tolerance
  fails, a rise only warns that the mark is stale — a PR that improves coverage
  is never blocked by the ratchet meant to protect it.

Same ratchet shape as tests/test_root_clutter_guard.py (#1652) — a committed
invariant + a guard that fails when a change makes it worse.
"""

import os
import re
import sys

# ── THE RATCHET. UP-ONLY. This number may only ever INCREASE. ────────────────
# Raising it: bump this + the two ci-cd.yml literals + pyproject fail_under in one
# PR, after verifying the suite clears the new value with headroom (a floor you
# barely clear reds main intermittently). LOWERING it needs an explicit, justified
# PR — coverage regressions do not get to slip in silently (ADR-080/ADR-107, #1658).
# Ratcheted 47->53 by #2152 (2026-08-06): measured 57.1% on a green post-#2132
# main run, 10.1pts above the old 47 floor (past the 10pt gap-warn threshold) —
# 53 restores the same ~4pt headroom-under-measured margin #1658 used originally.
# Ratcheted 53->58 by #1658 (2026-08-06): the tranche of real tests in that PR
# moved MEASURED coverage 57.19% -> 62.58% on the base it was written against
# (+5.39pt, 3,789 statements newly covered across 11 previously near-untested
# modules); re-measured 62.64% after rebasing onto e3498ad7, which is the number
# RATCHET_HIGH_WATER below records. 58 keeps the same ~4.6pt
# headroom-under-measured convention at the new level.
# Ratcheted 58->66 by #1658 TRANCHE 2 (2026-08-08): 17 more behavioral test files
# moved MEASURED coverage 63.14% -> 70.50% on this branch's base (+7.36pt, 5,208
# statements newly covered across 17 modules that sat at 4-56%). 66 keeps the same
# ~4.4pt headroom-under-measured convention. NOTE for whoever ticks #1658's third
# acceptance box: measured coverage is now PAST 70, but this enforced floor is
# deliberately NOT 70 — a floor set 0.4pt under measured flaps on every ordinary
# run. Enforcing 70 as the merge gate needs measured ~74.6 first.
RATCHET_FLOOR = 66

# ── THE MEASURED-COVERAGE HIGH-WATER MARK. UP-ONLY. (#1658) ──────────────────
# Actual measured line coverage (lambdas/ + mcp/) as of the PR that last raised
# this, NOT a target. CI feeds it to coverage_gap_warn.py --high-water with
# --fail-on-regression, so a PR that deletes real coverage reds instead of
# quietly spending the floor's headroom. Raising it: re-measure with the CI
# invocation, bump this + the ci-test.yml --high-water literal together. LOWERING
# it is legitimate only when covered code is deliberately DELETED (the ratio, not
# the tests, moved) — and then only in the same PR, with the reason in the body.
# Raised 62.64 -> 70.40 by #1658 tranche 2 (2026-08-08). Measured 70.50 with the
# CI job's exact invocation and pinned deps after rebasing onto 367896b4; the mark
# is banked a tenth of a point UNDER that. The mark is a floor for real coverage,
# so rounding down costs nothing and buys jitter margin against main's churn.
RATCHET_HIGH_WATER = 70.40

# The regression tolerance CI runs with. Mirrors coverage_gap_warn.py's default;
# asserted equal below so the two can't drift (the #1206 drift class again).
HIGH_WATER_TOLERANCE = 1.5

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_PYPROJECT = os.path.join(_REPO, "pyproject.toml")
# The enforced coverage gate (--cov-fail-under / coverage_gap_warn --floor) moved into
# the reusable ci-test.yml when #1655 split ci-cd.yml. Read the whole CI gate surface so
# this ratchet-guard follows the literal wherever it lives.
_CI_FILES = [os.path.join(_REPO, ".github", "workflows", f) for f in ("ci-cd.yml", "ci-test.yml", "ci-lint.yml")]
_CI = _CI_FILES[0]  # kept for messages/back-compat

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — CI + local both run 3.11+
    tomllib = None


def _pyproject_fail_under():
    with open(_PYPROJECT, "rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["coverage"]["report"]["fail_under"]


def _ci_text():
    parts = []
    for p in _CI_FILES:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                parts.append(fh.read())
    return "\n".join(parts)


def _ci_cov_fail_under():
    m = re.search(r"--cov-fail-under=(\d+)", _ci_text())
    assert m, "no --cov-fail-under=N found in ci-cd.yml — the enforced coverage gate is missing"
    return int(m.group(1))


def _ci_gap_warn_floor():
    m = re.search(r"coverage_gap_warn\.py[^\n]*?--floor\s+(\d+)", _ci_text())
    assert m, "no coverage_gap_warn.py --floor N found in ci-cd.yml"
    return int(m.group(1))


def test_pyproject_floor_meets_ratchet():
    fu = _pyproject_fail_under()
    assert fu >= RATCHET_FLOOR, (
        f"pyproject.toml fail_under={fu} is BELOW the committed ratchet {RATCHET_FLOOR}. "
        "The coverage floor is up-only (ADR-080/ADR-107, #1658) — do not lower it."
    )


def test_ci_cov_fail_under_meets_ratchet():
    ci = _ci_cov_fail_under()
    assert ci >= RATCHET_FLOOR, f"ci-cd.yml --cov-fail-under={ci} is below the ratchet {RATCHET_FLOOR} — up-only."


def test_ci_gap_warn_floor_meets_ratchet():
    gw = _ci_gap_warn_floor()
    assert gw >= RATCHET_FLOOR, f"ci-cd.yml coverage_gap_warn --floor={gw} is below the ratchet {RATCHET_FLOOR} — up-only."


def test_all_three_floor_literals_agree():
    """The canonical pyproject floor, the enforced CI gate, and the gap-warn floor
    must be the SAME number — otherwise the reminder or the belt-and-suspenders gate
    silently diverges from what's actually enforced (the #1206 drift class)."""
    fu = _pyproject_fail_under()
    ci = _ci_cov_fail_under()
    gw = _ci_gap_warn_floor()
    assert fu == ci == gw, (
        f"coverage floor literals disagree: pyproject fail_under={fu}, "
        f"ci --cov-fail-under={ci}, gap-warn --floor={gw}. Keep all three in lockstep."
    )


# ── The #1658 measured-coverage high-water ratchet ───────────────────────────


def _ci_high_water():
    m = re.search(r"--high-water\s+([0-9.]+)", _ci_text())
    assert m, "no `--high-water N` found in the CI workflows — the #1658 coverage-regression gate is missing"
    return float(m.group(1))


def _ci_high_water_tolerance():
    """The tolerance is optional on the CLI (it defaults inside the script), so fall
    back to the script's own default rather than asserting a literal that need not exist."""
    m = re.search(r"--high-water-tolerance\s+([0-9.]+)", _ci_text())
    if m:
        return float(m.group(1))
    src = open(os.path.join(_REPO, "scripts", "coverage_gap_warn.py"), encoding="utf-8").read()
    d = re.search(r"DEFAULT_HIGH_WATER_TOLERANCE_POINTS\s*=\s*([0-9.]+)", src)
    assert d, "coverage_gap_warn.py no longer defines DEFAULT_HIGH_WATER_TOLERANCE_POINTS"
    return float(d.group(1))


def test_ci_high_water_matches_the_ratchet():
    """The committed mark and the literal CI actually enforces must be the same number —
    otherwise the gate silently guards a different level than this file advertises."""
    ci_hw = _ci_high_water()
    assert ci_hw == RATCHET_HIGH_WATER, (
        f"CI --high-water={ci_hw} disagrees with RATCHET_HIGH_WATER={RATCHET_HIGH_WATER}. "
        "Bump both together (#1658) — a mismatch means the enforced level isn't the recorded one."
    )


def test_high_water_tolerance_matches_the_script_default():
    assert _ci_high_water_tolerance() == HIGH_WATER_TOLERANCE, (
        f"the enforced high-water tolerance ({_ci_high_water_tolerance()}) disagrees with this file's "
        f"HIGH_WATER_TOLERANCE ({HIGH_WATER_TOLERANCE}). Keep them in lockstep."
    )


def test_high_water_sits_above_the_floor():
    """The high-water mark records MEASURED coverage, which is by construction above the
    anti-flap floor. If this ever inverts, one of the two numbers is wrong."""
    assert RATCHET_HIGH_WATER > RATCHET_FLOOR, (
        f"RATCHET_HIGH_WATER ({RATCHET_HIGH_WATER}) must exceed RATCHET_FLOOR ({RATCHET_FLOOR}) — "
        "the high-water is measured coverage, the floor is the deliberately-lower gate."
    )


def test_floor_headroom_is_covered_by_the_high_water_gate():
    """The reason #1658 added the second ratchet: the floor's headroom must not exceed
    what the high-water gate actually polices, or coverage can be spent unnoticed again.

    Concretely — a drop is caught at (high_water - tolerance). If that catch line fell
    BELOW the floor, everything between them would be an unguarded hole, which is exactly
    the pre-#1658 state this guard exists to prevent."""
    catch_line = RATCHET_HIGH_WATER - HIGH_WATER_TOLERANCE
    assert catch_line > RATCHET_FLOOR, (
        f"the high-water gate catches regressions below {catch_line:.2f}%, which is not above the "
        f"{RATCHET_FLOOR}% floor — coverage between them would be unguarded. Raise the floor, "
        "raise the high-water, or tighten the tolerance."
    )


def test_ci_passes_fail_on_regression():
    """Advisory-by-default is the script's contract; CI must opt in, or the gate is
    decorative (the ADR-125 #1927 class: a gate that reports green while dark)."""
    text = _ci_text()
    assert "--fail-on-regression" in text, (
        "the CI coverage-regression step does not pass --fail-on-regression, so a real coverage "
        "regression would only print an annotation and still pass (#1658)."
    )
