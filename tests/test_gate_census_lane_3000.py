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
#
# TIGHTENED 2026-08-26 (#3220), 560 -> 551 / 550 -> 541. This is the ratchet doing
# its job, not a re-baseline: `scripts/gate_census.py` classified guards by FILENAME
# alone, so ten modules with no structural way to fail were sitting in the inventory
# because of a substring in their names. Measured by diffing the `--json` id sets
# across the fix (the method the issue itself used): exactly 10 ids REMOVED, 1 ADDED
# (`structural::test_gate_census_enforcement_3220.py`, the genuinely new test file
# this PR brings), total 560 -> 551, unproven 534 -> 525. Both numbers move by the
# same net 9 and keep their previous shape — total at measured, unproven with the
# same 16 of headroom it had before — so nothing about the ratchet's tension
# changed, only its honesty.
# The ten are printed by path under "NAME-MATCHED, NO ENFORCEMENT PATH" in the
# census report; they are UNPROVABLE, not unproven, and do not belong in #2578's
# denominator. Re-admitting one is a `# gate-entrypoint:` marker in that file.
#
#
# 2026-08-26 (#3222), 551 -> 552. TOTAL only. ONE gate added:
# `tests/test_fixture_frame_pairing_3222.py`, the fixture half of the PT-day contract.
# RE-DERIVED after #3220 landed, not incremented off the old 560 — this branch was
# written against the pre-#3220 classifier and its first number (561) is dead. Measured
# on the rebased tree with `python3 scripts/gate_census.py --json`: total 552, proven 24,
# unproven 525, unprovable 10. Two things worth recording because #3220 changed the rules
# underneath this gate:
#   * It still ENTERS the inventory under the structural classifier — it is not a
#     name-only match. `gate_census_enforcement.enforcement_evidence()` on the file
#     returns ['assert-statement', 'bool-verdict-api'], so it is admitted on what it
#     does, not on what it is called.
#   * It lands PROVEN, not unproven: it is registered in `PROVEN_CAN_FAIL` in
#     `scripts/gate_census.py` with a real two-direction mutation (the same planted
#     `datetime.now(timezone.utc).date()` reds it in a `pacific_today()` handler's test
#     and is silent in a `utc-exempt(#2811)` one). So UNPROVEN measures 525 — exactly
#     where #3220 left it — and this ceiling does not move at all.
#
# RAISED 2026-08-27 (#3213), total 552 -> 554; UNPROVEN UNCHANGED at 541 (measured
# 527, so the ceiling did not need to move and was not moved — confirmed, not assumed).
# Genuine inventory growth, not a re-baseline: #3213 adds the scheduled-workflow
# cadence watch, and its two gates were adjudicated ONE BY ONE rather than absorbed
# into a total. Measured by diffing the `--json` id sets against clean `main` at
# a68089414 (which measures 552, agreeing with its own committed ceiling), on a tree
# rebased onto it — exactly 2 ADDED, 0 REMOVED:
#
#   ci::cron-freshness.yml::cadence::3          the CI step that runs the watcher.
#   guard::scripts/check_cron_freshness.py      the guard entrypoint. Carries the
#     syntactic flag `exempt-by-incompleteness` — the #2619 shape, "the exemption
#     predicate is satisfied by the defect". ADJUDICATED AND CLOSED, not waved off:
#     it fires on `evaluate()`'s `if not row.get("watched"): continue`, which does
#     skip a row whose ruling is MISSING as well as one ruled unwatched. That gap is
#     covered by a second, independent path — `unruled_workflows()` reports the
#     unruled row and `render()` reds on it — and
#     `tests/test_cron_freshness_3213.py::test_i_registry_drift_alone_reds_the_run`
#     pins exactly that, so an unruled workflow cannot pass through the skip
#     unreported. A correct lead on a real pattern, closed by the design rather than
#     by the flag being wrong.
#
# Both stay `unproven` for the census's purposes (no PROVEN_CAN_FAIL entry is claimed
# here), which is why only the total moves.
#
# MEASURE ON A RESOLVED TREE — a mid-rebase reading of this number is WRONG, and it
# is wrong in the direction that makes you raise the ceiling too far. Measured
# 2026-08-27 while this very file sat unmerged (`UU`): the census read 554 -> 558.
# `gate_census._tracked_files` derives its corpus from git's tracked-path listing,
# which emits an unmerged path once PER STAGE — three copies of this file instead of
# one — and this file carries two module-level names the registry family expands
# entry-by-entry (`BASELINE_TOTAL_GATES` and `BASELINE_UNPROVEN_GATES` both match
# `.*_GATES`). Two spurious copies x two constants = exactly the +4 observed. Resolve
# the conflict, `git rebase --continue`, and only then run the census; a clean
# `git status` is the precondition for trusting any number out of it.
#
# (Second-order, learned the same way: do not spell git's tracked-path subcommand out
# in this file. `tests/premerge_derivation.py` treats that literal as one of its three
# tree-sweep idioms, so writing it in a COMMENT reclassified this file into the
# structural family and added a phantom gate — 554 -> 555, prose alone. Same shape as
# the name-matching #3220 removed, arriving through documentation instead of a filename.)
#
# This ceiling is MEANT to move with the real inventory (unlike the module-size
# ratchet, whose numbers may never rise). Lowering it after a real measurement is
# always welcome; raising it needs the reason in the same PR.
#
# 554 -> 558 (2026-08-27, #2578): NOT inventory growth — an ADJUDICATION. #3220 removed
# ten libraries that had entered this count on a filename substring alone, and
# deliberately did not re-admit any of them by hand, leaving the ruling open. All ten
# were ruled one at a time (the table lives in scripts/gate_census_enforcement.py, and
# the ruling for each of the four below is written IN the file it re-admits, which is
# the only sanctioned form — a hand-list at classify time is the thing this census
# replaces). FOUR carried a real verdict that no other row in this census reports:
#
#   lambdas/coach/coach_quality_gate.py    ADR-108: ai_calls holds the coach's brief
#   lambdas/intelligence/grounding_guard.py SS-10: field-notes holds, analyzer re-gens
#   lambdas/privacy/memoir_gate.py         #553: a twice-failing memoir is dropped
#   tests/pair_seam_guard_lib.py           #2847: the seam ratchet's own verdict
#
# The other six stay out on their merits, not by omission: two compute no verdict at all
# (grounding_gate_params, quality_gate_contract), one is fail-soft by construction and
# blocks nothing (item_size_guard), one is a threshold registry the engines read
# (experiment_gates), and two ARE gate logic whose verdict another census row already
# reports, so admitting them would count one verdict twice (conformance_guard_lib ->
# test_conformance_guard_2844.py; truth_baseline_audit -> the `visual-qa / Run visual +
# AI-vision QA sweep` CI step, itself a PROVEN row).
#
# Measured on a clean tree, both directions: 554 before the four markers, 558 after, and
# the id-set difference is exactly those four `guard::` ids and nothing else.
#
# 558 -> 559: the same PR's second half adds ONE real CI gate — ci-cd.yml's
# `reconcile / Reconcile verdict — the tree this job leaves must be literal-clean`. That
# one IS inventory growth, and it is the honest kind: the reconcile job could report
# success on a tree it left drifted (#3234, main red twice on 2026-08-27), and now it
# cannot. Appended as the LAST step of its job on purpose — a CI-step id is positional
# (`::<job>::<index>`), so inserting one mid-job slides every later id onto a different
# gate; `orphan_proofs` is empty on the measured run, which is the check that it did not.
#
# BASELINE_UNPROVEN_GATES is deliberately NOT moved — all five arrive unproven, taking
# the live count 527 -> 532, still under the committed 541. Five new rows of real #2578
# work; none of them is a verdict this PR claims to have watched fail.
BASELINE_TOTAL_GATES = 559
BASELINE_UNPROVEN_GATES = 541


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
