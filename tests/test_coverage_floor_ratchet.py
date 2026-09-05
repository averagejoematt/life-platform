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
# ~4.4pt headroom-under-measured convention.
# Ratcheted 66->74 by #1658 TRANCHE 3 (2026-08-08): 15 more behavioral test files
# moved MEASURED coverage 70.50% -> 78.24% on this branch's base 520a7c12 (+7.74pt,
# 5,565 statements newly covered across 15 modules that sat at 0-72% — the email
# renderers, the daily-brief HTML builder, the social write surface, the coach
# honesty engine and the whole untested mcp/tools_* family). 74 keeps the same
# ~4.2pt headroom-under-measured convention.
# #1658's THIRD acceptance box ("enforce 70% as the merge gate") is SATISFIED at
# this value: the enforced gate is 74, above 70, and it was set from a measurement
# rather than a target — tranche 2's note said that needed measured ~74.6, and
# measured is 78.24.
RATCHET_FLOOR = 74

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
# Raised 70.40 -> 78.10 by #1658 tranche 3 (2026-08-08). Measured 78.24 with the
# CI job's exact invocation and pinned deps on base 520a7c12; banked a tenth of a
# point under, same convention. The regression catch line is therefore 76.60%.
# Raised 78.10 -> 78.90 (2026-08-09) after #1658 tranche 4. Measured **79.02%** —
# read out of the CI job itself ("Required test coverage of 74% reached. Total
# coverage: 79.02%", run 31274908729 on green main e806d7e4), not re-derived
# locally: the local interpreter has no pytest-cov at the pinned 7.1.0 and a
# different cov version is a different measurement. Banked 0.12 under, same
# convention. The regression catch line is therefore 77.40%.
# Raised 78.90 -> 80.20 (2026-08-09, #2374): tranche 5 measured 80.21% and the gain
# sat unbanked — 2.81pt deletable inside the deadband with zero signal. Banked at
# 80.20 (just under measured, conservative); the ±1.5pt deadband itself is the
# documented nudge-fatigue design and stays.
# Raised 80.20 -> 81.60 (2026-08-16): green main run 31923965259 measured 81.71%,
# 1.51pt past the deadband — the ::warning:: fired and this is the sanctioned
# response (bank the gain, #1658). Same just-under-measured convention.
# Raised 81.60 -> 83.20 (2026-08-26): green main run 32925488120 measured 83.27%,
# 1.67pt past the deadband — same fired-warning, same sanctioned response, same
# just-under-measured convention.
RATCHET_HIGH_WATER = 83.20

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


# ── #3539: THE CI STEP'S PROSE MAY NOT CARRY AN UNCOMMITTED PERCENTAGE ────────
#
# The coverage-gate step's comment block carried three eras of hand-typed numbers at
# once — a "measured … 79.02%", a "banked at 83.20" and a catch line "78.90 - 1.5 =
# 77.40%" — against a green main that measured 83.84%. Nothing compared any of them to
# anything, because a comment is not a fact anyone owns: the numbers above (RATCHET_FLOOR,
# RATCHET_HIGH_WATER, HIGH_WATER_TOLERANCE) plus the lineage in this file's own comments
# ARE the owner, and the YAML prose was a phrase-keyed copy of them. The #2959/#3199
# family: a detector keyed on a phrase instead of on the fact.
#
# So: every percentage-shaped literal in that step's comments must equal one of this
# file's committed constants. Nothing else — not a measurement, not an arithmetic
# worked example, not a historical era. Lineage belongs here, where it sits next to the
# constant it explains and moves with it.
_COVERAGE_STEP_NAME = "Test coverage gate (regression floor, ADR-080)"

# A percentage-shaped literal: a number wearing %/pt/pts/points, or a bare decimal.
# The lookbehind keeps it off issue/ADR tokens (`#3539`, `ADR-080`) and version-ish text.
_PCT_RE = re.compile(r"(?<![\w.#\-])(\d+(?:\.\d+)?)\s*(?:%|pts?\b|points\b)|(?<![\w.#\-])(\d+\.\d+)(?![\w.])")


def _coverage_step_comment_lines(yaml_text):
    """The `#` comment lines of the coverage-gate step: from its `- name:` line to the
    first `run:`/`if:` key that ends the comment block."""
    lines = yaml_text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if _COVERAGE_STEP_NAME in ln and ln.strip().startswith("- name:"))
    except StopIteration:
        raise AssertionError(f"ci-test.yml no longer has a step named {_COVERAGE_STEP_NAME!r} — this guard has lost its subject")
    out = []
    for ln in lines[start + 1 :]:
        stripped = ln.strip()
        if stripped.startswith("#"):
            out.append(stripped)
            continue
        if stripped:  # the first non-comment key ends the block
            break
    return out


def _uncommitted_percentages(comment_lines):
    # Both spellings of each constant: str(83.20) is "83.2", and the CI literal is
    # written "83.20". A guard that rejects the very number CI passes is not a guard.
    committed = set()
    for value in (RATCHET_FLOOR, RATCHET_HIGH_WATER, HIGH_WATER_TOLERANCE):
        committed |= {str(value), f"{float(value)}", f"{float(value):.2f}", f"{float(value):g}"}
    bad = []
    for ln in comment_lines:
        for m in _PCT_RE.finditer(ln):
            value = m.group(1) or m.group(2)
            if value not in committed:
                bad.append((value, ln))
    return bad


def _ci_test_yaml():
    path = os.path.join(_REPO, ".github", "workflows", "ci-test.yml")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_ci_comment_carries_no_uncommitted_percentage():
    """Every percentage in the coverage-gate step's prose is one of this file's
    committed constants — see the block comment above."""
    bad = _uncommitted_percentages(_coverage_step_comment_lines(_ci_test_yaml()))
    assert not bad, (
        "ci-test.yml's coverage-gate comment carries percentage literal(s) that are not\n"
        f"RATCHET_FLOOR ({RATCHET_FLOOR}), RATCHET_HIGH_WATER ({RATCHET_HIGH_WATER}) or\n"
        f"HIGH_WATER_TOLERANCE ({HIGH_WATER_TOLERANCE}). A measurement written into a YAML\n"
        "comment is owned by nobody and is stale the day after (#3539: three eras of them\n"
        "sat there at once). Put the number in this file and let the comment point here:\n"
        + "\n".join(f"  {v}  in: {ln[:110]}" for v, ln in bad)
    )


def test_the_percentage_scan_fires_on_a_planted_measurement():
    """Mutation proof. A prohibition that matches nothing greens whether or not it
    works — plant each of the three era-shapes the step actually carried."""
    planted = [
        "# line coverage is 79.02% (read out of this job's own output)",
        "# the --high-water mark below is banked at 83.19,",
        "# polices measured coverage directly at 78.90 - 1.5 = 77.40%.",
        "# prevents BACKSLIDING with ~5.0pt headroom under measured",
    ]
    found = {v for v, _ in _uncommitted_percentages(planted)}
    assert {"79.02", "83.19", "78.90", "77.40", "5.0"} <= found, found

    # The committed constants themselves must NOT be flagged, or the guard forbids
    # the one thing it wants the comment to say.
    ok = [f"# the floor is {RATCHET_FLOOR}% and the mark is {RATCHET_HIGH_WATER}, tolerance {HIGH_WATER_TOLERANCE}pt"]
    assert not _uncommitted_percentages(ok)

    # ...and issue/ADR tokens are not percentages.
    assert not _uncommitted_percentages(["# ENFORCED regression floor (ADR-080/ADR-107). See #3539 and #1658."])
