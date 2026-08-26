"""tests/test_gate_census_lane_3000.py — #3000: the census's own lane + visibility ratchet.

Epic #2578's fourth acceptance box: "a recurring check keeps the inventory honest, so a
newly-added gate cannot enter the platform unverified." Measured 2026-08-22: `gate_census`
matched zero workflow files (`grep -rn "gate_census" .github/workflows/*.yml
.claude/commands/*.md` — nothing). `tests/test_gate_census_2578.py` mutation-proves the
census's EXTRACTORS against synthetic fixtures; nothing anywhere ran the census against
the REAL repo and asked whether a gate had entered with no verdict. This file is that ask.

THE LANE (box 1 — "runs in a lane triggered by its own inputs, not only by hand")
-----------------------------------------------------------------------------------
The census's inputs are `.github/workflows/**`, the gate registries (lambdas/tests/
scripts/deploy/mcp — `gate_census.discover_registry_gates`'s own `_REGISTRY_ROOTS`), and
`tests/**`. `tests/conftest.py`'s `_PREMERGE_EXTRA_FILES` already runs
`test_gate_census_2578.py` in `pr-checks.yml`'s "Pre-merge test lane" job — this file joins
it as a sibling entry. That job has NO `paths:` filter at all (`pr-checks.yml` is
deliberately unfiltered so it stays the one REQUIRED status check that can't silently
un-require itself — see that workflow's own comment), so it is triggered by literally
every PR, which trivially covers the three named inputs and everything else besides. No
workflow YAML edit was needed to satisfy this box.

THE RATCHET (boxes 2 + 5 — "a newly added gate with no verdict is visible" / "mutation-
proved")
-----------------------------------------------------------------------------------
A CI-step gate id is POSITIONAL (`gate_census.py`'s own docstring: inserting one step
slides every later id onto a different gate), so "is THIS SPECIFIC gate id new" is not a
stable question to gate a PR on — the census's own `orphan_proofs`/mismatch machinery
already treats an id shift as a fact to surface, not silently absorb, and this file
inherits that honesty rather than fighting it. What IS stable is the AGGREGATE: the count
of gates carrying the `unproven` verdict. `unproven` is the honest DEFAULT — nearly every
gate in this repo carries it, and that is fine; #2578 slice 2 proves a few able to fail
deliberately, one mutation at a time. What must not happen SILENTLY is that population
growing without anyone having to say so. So `BASELINE_UNPROVEN_GATES` below is a ceiling,
in the SAME shape as `tests/test_coverage_floor_ratchet.py`'s `RATCHET_HIGH_WATER`: it may
only be RAISED by a deliberate, reviewable edit to this file, in the same PR that grew the
inventory — which is exactly "stated, not silently absorbed" (the acceptance's own words).

`test_check_function_reds_on_a_synthetic_unverified_addition` is the mutation proof the
acceptance box asks for: it plants a gate that entered with no verdict using SYNTHETIC
integers (no repo dependency at all) and shows the decision function reds. The live check
below is the second, separate half — it runs the rule against the real, current inventory.

WHY THIS FILE DOES NOT CALL `gate_census.build_census()` A SECOND TIME
-----------------------------------------------------------------------------------
`tests/test_gate_census_error_bars_2639.py` already computes the full-repo census (all 5
families) at MODULE level — `CENSUS = gate_census.build_census(pathlib.Path(_REPO))` —
and pytest COLLECTION imports every file under `tests/` regardless of which tests a `-m`
filter will actually run, so that ~7s (measured 2026-08-24: `python3 scripts/
gate_census.py --json /dev/null` took 7.3s wall-clock) is ALREADY paid once per lane,
whether or not `test_gate_census_lane_3000.py` exists. The #3106 unit suite is already 7s
over its 1500s budget (`tests/test_duration_budget_ratchet.py`), so a second independent
`build_census()` call here would make that worse for nothing — this file reuses 2639's
already-computed `CENSUS` when it is available in `sys.modules`, and falls back to
building its own only when run in isolation (e.g. `pytest tests/test_gate_census_lane_
3000.py` alone, which a developer might do locally).
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ══════════════════════════════════════════════════════════════════════════════
# THE RATCHET. `unproven` may only ever FALL without a deliberate, reasoned bump.
# ══════════════════════════════════════════════════════════════════════════════
# Raising it: run `python3 scripts/gate_census.py`, read "gates found" / "no verdict
# attempted" off the report header, and bump BOTH numbers below in the SAME PR that grew
# the inventory — with a one-line reason, exactly the test_coverage_floor_ratchet.py
# convention. Headroom is deliberately generous on landing (2026-08-24): this session is
# running with dozens of concurrent worktrees each touching workflows/registries, so the
# live count will keep moving between this measurement and merge.
#
# Seeded 2026-08-24 (#3000): measured 523 gates total, 513 unproven, 7 proven, 3
# attempted-unproven (`python3 scripts/gate_census.py --json`). Ceilings banked with
# headroom above that, not at the exact measured value.
# 2026-08-26 (#3202): 560 → 561. The one new entry, named because a ceiling bump whose
# diff does not say what grew the inventory is the silent drift this ratchet exists to
# prevent. Diffed census-vs-census (origin/main tree vs this branch): exactly one id
# ADDED, none removed —
#
#     guard::lambdas/ai/coach_gate_retention.py   family=guard-script   verdict=unproven
#
# RULING: it is NOT a gate, and it is unproven by CLASSIFICATION rather than by neglect.
# The file is `ai_calls._retain_coach_brief_flag`'s body, extracted so the #1665 module-size
# ratchet on `ai_calls.py` stayed honest; it persists a fired quality-gate verdict as eval
# data (`eval_retention.retain`). It enforces nothing, blocks nothing, and is deliberately
# fail-soft (`except Exception: pass` — "retention is never load-bearing"), so #2578's
# can-fail bar does not apply: there is no failure for it to be proven capable of.
# It matched on FILENAME ONLY — `_GUARD_NAME`'s `.*_gate[a-z0-9_]*\.py$` alternative fires
# on "coach_GATE_retention.py" — and then landed in `discover_guard_scripts`' `no_nonzero_exit`
# bucket, whose own detail line already anticipates this case: "it may be a library, or it
# may be unable to fail". It is a library. Recorded here rather than dodged by renaming the
# module, because the name is accurate (it IS the coach gate's retention) and because the
# census's own false-positive rate is worth seeing in the ledger.
# Unproven is 535 against the 550 ceiling — untouched, no bump needed.
BASELINE_TOTAL_GATES = 561
BASELINE_UNPROVEN_GATES = 550


def check_unproven_ceiling(total_gates: int, unproven_gates: int) -> tuple[bool, str]:
    """Pure decision function. Takes its numbers as arguments — never reads the live
    repo itself — so the RULE can be mutation-proven independent of today's count."""
    if unproven_gates > BASELINE_UNPROVEN_GATES:
        return False, (
            f"{unproven_gates} gates now carry no verdict, above the committed ceiling "
            f"{BASELINE_UNPROVEN_GATES}. A gate entered the platform with no verdict and "
            "nothing said so out loud: either give it a verdict (PROVEN_CAN_FAIL / "
            "ATTEMPTED_UNPROVEN in scripts/gate_census.py) or bump BASELINE_UNPROVEN_GATES "
            "(and BASELINE_TOTAL_GATES) here, in the SAME PR, with a reason (#3000)."
        )
    if total_gates > BASELINE_TOTAL_GATES:
        return False, (
            f"{total_gates} gates found, above the committed ceiling {BASELINE_TOTAL_GATES} "
            "— bump BASELINE_TOTAL_GATES here in the same PR that grew the inventory (#3000)."
        )
    return True, f"{total_gates} gates found ({unproven_gates} unproven), within the committed ceiling."


# ── The mutation proof (#3000 acceptance: "mutation-proved") ────────────────────────


def test_check_function_passes_at_the_committed_ceiling():
    ok, msg = check_unproven_ceiling(BASELINE_TOTAL_GATES, BASELINE_UNPROVEN_GATES)
    assert ok, msg


def test_check_function_reds_on_a_synthetic_unverified_addition():
    """The mutation: ONE synthetic gate appears, unproven — nothing else about the repo
    moved. Proven with integers, never the live repo, so this can never flake or drift."""
    ok, msg = check_unproven_ceiling(BASELINE_TOTAL_GATES + 1, BASELINE_UNPROVEN_GATES + 1)
    assert not ok, "a gate added with no verdict must red this check"
    assert "no verdict" in msg


def test_check_function_reds_on_total_growth_even_if_every_new_gate_is_verified():
    """The other half: total gates rising past the ceiling reds too, even when the
    unproven count did not move — the total ceiling exists so a big verified addition
    still gets a deliberate, visible bump rather than silently absorbing headroom."""
    ok, msg = check_unproven_ceiling(BASELINE_TOTAL_GATES + 5, BASELINE_UNPROVEN_GATES)
    assert not ok
    assert "gates found" in msg


def test_baseline_unproven_never_exceeds_baseline_total():
    """A cheap internal-consistency guard on the ratchet itself — a gate cannot be
    'unproven' and not exist."""
    assert BASELINE_UNPROVEN_GATES <= BASELINE_TOTAL_GATES


# ── The live check — the actual guard over the real, current inventory ──────────────

_ERR_BARS_MODULE = "test_gate_census_error_bars_2639"


def _live_census() -> dict:
    cached = sys.modules.get(_ERR_BARS_MODULE)
    if cached is not None and hasattr(cached, "CENSUS"):
        return cached.CENSUS  # already computed during collection — see module docstring
    pytest.importorskip("yaml", reason="gate_census's CI-family walk needs PyYAML")
    import gate_census

    return gate_census.build_census(pathlib.Path(_REPO))


def test_live_unproven_gate_count_is_within_the_committed_ceiling():
    """THE guard. Runs the census against the real repo tree and checks the aggregate
    against the ratchet above — the check that #2578's fourth acceptance box asked for
    and that nothing in this platform ran until #3000."""
    census = _live_census()
    gates = census["gates"]
    total = len(gates)
    unproven = sum(1 for g in gates if g["verdict"] == "unproven")
    ok, msg = check_unproven_ceiling(total, unproven)
    assert ok, msg
