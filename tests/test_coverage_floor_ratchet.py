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
RATCHET_FLOOR = 47

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_PYPROJECT = os.path.join(_REPO, "pyproject.toml")
_CI = os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — CI + local both run 3.11+
    tomllib = None


def _pyproject_fail_under():
    with open(_PYPROJECT, "rb") as fh:
        data = tomllib.load(fh)
    return data["tool"]["coverage"]["report"]["fail_under"]


def _ci_text():
    with open(_CI, encoding="utf-8") as fh:
        return fh.read()


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
