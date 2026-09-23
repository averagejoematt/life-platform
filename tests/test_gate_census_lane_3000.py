"""tests/test_gate_census_lane_3000.py — #3000: the census's own lane + visibility ratchet.

Epic #2578's fourth acceptance box: "a recurring check keeps the inventory honest, so a
newly-added gate cannot enter the platform unverified." Measured 2026-08-22: `gate_census`
matched zero workflow files (`grep -rn "gate_census" .github/workflows/*.yml
.claude/skills/*/SKILL.md` — nothing). `tests/test_gate_census_2578.py` mutation-proves the
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

THE PER-ENTRANT RULE (#3536, 2026-09-05 — the forensic RCA's class 4, "prove one, mint one")
-----------------------------------------------------------------------------------
A count ceiling has two holes. With 541 committed over 536–538 live, sixteen new guards
could enter unproven with nothing said (the #3536 finding: 35 of 101 source-scanning guards
since 08-21 carry no must-fail control, and the ratchet never spoke). And at ZERO headroom
a PR that proves one old gate can still mint one new unproven gate for free — the count
does not move. So the rule is now keyed by gate: every live `unproven` gate must be a line
in `tests/gate_census_unproven_residue.py`, the dated, shrink-only ledger of the installed
base at the seal (`check_unproven_entrants` below). A gate that is not there arrives with a
verdict or it does not land, and the only other green path is a NEW LINE in the ledger —
in the diff, dated, with a reason. `BASELINE_UNPROVEN_GATES` is now DERIVED from the
ledger's size (one source of truth; the count rule stays as the coarse layer and the
pure-integer mutation proofs still pin it), `UNPROVEN_CEILING_HIGH_WATER` holds the
ledger's count down-only, and `RATCHET_DOWN_SLACK` is 0: a ledger line whose gate is no
longer live-unproven is printed BY NAME every run (non-fatal, #3329) so the delete that
records the progress is never a surprise. CI-step ids are positional, so the ledger keys
that family on workflow + `<job> / <step label>` (`stable_key`) — an inserted step is not a
false entrant; a relabelled one is a real decision on the PR that relabels it.

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
from collections.abc import Iterable, Mapping

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "scripts"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gate_census_unproven_residue import UNPROVEN_RESIDUE  # noqa: E402

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
#   [SUPERSEDED 2026-08-31 by the 575 -> 581 entry at the bottom of this block: the
#   six survivors are now IN the denominator carrying `not-applicable` + a reason.
#   'not unproven' still holds and is the part that mattered; 'not in the total'
#   does not. The paragraph is kept as the record of what was true then.]
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
# 558 -> 560: the same PR's second half adds TWO real gates, and both ARE inventory
# growth of the honest kind — the reconcile job could report success while unable to
# derive what it was there to reconcile (#3234, main red twice on 2026-08-27):
#
#   ci::ci-cd.yml::reconcile::4              the self-check STEP
#   guard::deploy/verify_doc_facts_derivable.py  the script it runs
#
# Both counted, deliberately, and they are not a double count under the #3220 Q2 rule:
# the step can fail for reasons the script cannot (the runner, the `if:`), and the script
# is invocable outside CI. Appended as the LAST step of its job on purpose — a CI-step id
# is positional (`::<job>::<index>`), so inserting one mid-job slides every later id onto
# a different gate; `orphan_proofs` is empty on the measured run, which is the check that
# it did not.
#
# MEASURE WITH THE NEW FILE STAGED. `gate_census._tracked_files` derives its corpus from
# git, so an UNTRACKED new guard script is invisible and the census reads one low — 559,
# not 560, measured here before `git add -N`. A ceiling set from that reading would have
# redded the very commit that introduced the file.
#
# BASELINE_UNPROVEN_GATES is deliberately NOT moved — all six arrive unproven, taking the
# live count 527 -> 533, still under the committed 541. Six new rows of real #2578 work;
# none of them is a verdict this PR claims to have watched fail.
#
# 560 -> 561: #3079's `structural::test_shared_image_prepare_3079.py` — the AST census that
# keeps ONE screenshot -> vision-judge prepare path (the fresh-eyes pass had a second,
# undownscaled copy). It arrives PROVEN, not unproven: the mutation is recorded in
# gate_census.PROVEN_CAN_FAIL (the pre-#3079 raw-base64 body restored verbatim -> exit 1,
# 6 of 8 failed; baseline 8 passed, reverted 8 passed). So the live unproven count goes
# 533 -> 533, not 534, and BASELINE_UNPROVEN_GATES stays where the entry above left it.
#
# Measured with the file TRACKED, per the warning three paragraphs up — it read 560 as an
# untracked file and 561 once committed. That warning earned its keep on this PR.
# 561 -> 563 (2026-08-28, #3260/#3261/#3257 batch): TWO real gates, verified
# entry-by-entry rather than inferred from the delta — both trees were `git archive`d
# and each ran its OWN scripts/gate_census.py --json, then the id SETS were diffed:
# ADDED exactly {registry::scripts/doc_facts_og.py::_EXEMPT,
# structural::test_alarm_emission_dimension_3260.py}, REMOVED {} (main 561, branch 563).
# That method matters here: a bare count delta cannot tell an addition from a
# simultaneous add+remove, and #3220 measured ten libraries entering this inventory on a
# filename substring alone.
#   • the registry entry is family 3 — `scripts/doc_facts_og.py` is the OG-card literal
#     derivation extracted out of check_doc_facts.py for #3261, and its module-level
#     `_EXEMPT` binding mints one gate PER the family-3 rule. It is an exemption registry,
#     which is exactly what that family exists to count.
#   • the structural entry is family 5 — `test_alarm_emission_dimension_3260.py` sweeps
#     `lambdas/` for alarm/emission dimension agreement, and registering it in
#     `_PREMERGE_EXTRA_FILES` (tests/conftest.py) is itself what mints it.
# Both arrive UNPROVEN: live unproven 518 -> 520 against the committed 541, so
# BASELINE_UNPROVEN_GATES is NOT moved — it still has headroom and moving it would spend
# margin this PR did not need.
# 563 -> 564 (2026-08-28, #3245): ONE further real gate carried by this branch and
# preserved through the merge with main's own 561->563 raise above (originally recorded
# as 561 -> 562). The reason it was first written for still holds verbatim:
#   ONE real gate, `guard::scripts/hooks/guard_bash.py` — the
# PreToolUse hook that flags a merge with no named-check assertion, a deploy from a
# worktree, and a force-push to main. Verified as a genuine addition rather than the
# prose-phantom this comment warns about: the census gate-id sets were diffed before and
# after, and that id is the only member added. Registering
# `tests/test_skill_contract.py` in _PREMERGE_EXTRA_FILES also mints a gate, so the
# measurement was taken with every new file `git add`ed — an untracked guard measures as
# absent. Unproven fell 541 -> 534 over the same window (#3242's adjudication); that
# ceiling is left where its owner set it.
# 564 -> 565 (2026-08-29, #3294): ONE real gate,
# `structural::test_absence_coverage_3294.py` — the channels_quiet reader enumeration
# (family 5; registering it in _PREMERGE_EXTRA_FILES is part of the same PR). Verified by
# id-set diff, not count delta: each tree ran its own scripts/gate_census.py --json;
# ADDED exactly {structural::test_absence_coverage_3294.py}, REMOVED {} (main 564,
# branch 565). Measured with the file TRACKED (`git add` first — an untracked guard
# measures as absent). It arrives PROVEN: the mutation is a planted raw-list reader in
# lambdas/common/, re-runnable via `gate_census_mutations.py --run --gate
# structural::test_absence_coverage_3294.py` (ARMED 1/1 on the recording run), so the
# live unproven count does not move and BASELINE_UNPROVEN_GATES stays where its owner
# set it.
# 565 -> 566 (2026-08-29, #3284): ONE real gate —
#   qa::lambdas/operational/qa_check_permalink_blackhole.py::check_published_permalink_reachable
# the nightly cross-check that no URL published in the live /journal/posts.json is also a
# redirect source (map leg: the bundled redirects.map; live leg: a no-redirect-follow GET of
# each permalink). It exists because the one redirect gate that DID exist (redirect_spotcheck,
# #1430) *confirmed* the week-04 blackhole as correct behaviour — the direction was missing,
# not the coverage. Verified the #3260 way: both trees ran their OWN scripts/gate_census.py
# --json (the new files `git add`ed first — an untracked guard measures as absent), id SETS
# diffed: ADDED exactly the one id above, REMOVED {} (pre-train main 564, branch 565; re-based onto the merged #3294 raise, so the running total is 566). It arrives
# UNPROVEN by the census (live unproven 521 -> 522, under the committed 541, which is NOT
# moved); its fail path has a scripted positive control in tests/test_permalink_blackhole_3284.py,
# and its first LIVE verdict is designed-in: the live leg is expected-red on the first nightly
# after deploy until Matthew publishes the regenerated v4-redirects CloudFront function.
# 566 -> 569 (2026-08-29, #3279): THREE real gates from the sentinel's first events
# client — verified by id-set diff, each tree's own scripts/gate_census.py --json
# (pre-#3284 main 565, this branch 568): ADDED exactly
# {sentinel::deploy/sentinel_events.py::check_eventbridge_rules,
#  registry::deploy/sentinel_events.py::KNOWN_OUT_OF_IAC_RULES::life-platform-mcp-canary-15min,
#  registry::deploy/sentinel_events.py::KNOWN_OUT_OF_IAC_RULES::life-platform-nightly-warmer},
# REMOVED {}. Stacked on #3284's one-gate raise above: 565 + 1 + 3 = 569. The sentinel
# check arrives PROVEN (three-mutation record); the two registry ids are the allowlist's
# own family-3 mint. BASELINE_UNPROVEN_GATES stays where its owner set it.
# 569 -> 570 (2026-08-30, #3293): ONE real gate,
# `structural::test_direction_of_travel_ruling_3293.py` — the direction-of-travel surface
# registry (family 5; registering it in _PREMERGE_EXTRA_FILES is part of the same PR).
# Verified by id-set diff, not count delta: each tree ran its OWN scripts/gate_census.py
# --json with the new file `git add`ed first (an untracked guard measures as absent);
# ADDED exactly {structural::test_direction_of_travel_ruling_3293.py}, REMOVED {} (main
# 569, branch 570). It arrives PROVEN — the mutation is a planted unregistered importer
# in lambdas/web/, re-runnable via `gate_census_mutations.py --run --gate
# test_direction_of_travel_ruling_3293.py` (ARMED 1/1 on the recording run) — so the live
# unproven count does not move (524 -> 524) and BASELINE_UNPROVEN_GATES stays where its
# owner set it.
# 570 -> 571 (2026-08-30, #3278): ONE real gate —
#   sentinel::deploy/sentinel_log_retention.py::check_log_retention
# the sweep's first log-group read and its first multi-region one (the documented 90-day
# security-log tier measured 30d in two regions and NEVER_EXPIRE in five). Verified the
# #3260 way: both trees ran their OWN scripts/gate_census.py --json with the new files
# `git add`ed first; id SETS diffed: ADDED exactly the one id above, REMOVED {} (main 570,
# branch 571). It arrives PROVEN (both family-6 halves in tests/test_security_log_retention_3278.py,
# indexed in gate_census_proofs.py) so the live unproven count does not move (524 -> 524) and
# BASELINE_UNPROVEN_GATES stays where its owner set it.
# 571 -> 572 (2026-08-30, #2848): ONE real gate,
# `guard::scripts/check_operating_knowledge_ledger.py` — the operating-knowledge ledger guard
# (family 2, guard-script); its test, tests/test_operating_knowledge_ledger_2848.py, joins
# _PREMERGE_EXTRA_FILES in the same PR (the census keys the gate on the script, so registering
# the test minted no second id). Verified by id-set diff, not count delta: each tree ran its
# OWN gate_census.build_census with the new files `git add`ed first (main 3d398fc75 = 571,
# branch = 572); ADDED exactly {guard::scripts/check_operating_knowledge_ledger.py},
# REMOVED {}. It arrives UNPROVEN by the census (live unproven 524 -> 525, under the
# committed 541, which is NOT moved) and carries the static `exempt-by-incompleteness`
# flag: the heuristic matches three early `if not X: return` shapes, each of which RETURNS
# an error — a missing snapshot block or an unparseable table is a red, never a skip —
# pinned by test_a_missing_snapshot_block_reds and the module's non-vacuity floors. No
# PROVEN_CAN_FAIL entry is claimed: its mutation proofs run on synthetic text with an
# injected `tracked` predicate, not through gate_census_mutations.py.
# 572 -> 573 (2026-08-31, #3336): ONE real gate, `structural::test_iam_twin_free_3336.py` — the
# derivation guard that no deploy/ script may embed an IAM policy document for a role with a
# checked-in infra/iam/*.json (the 2026-08-30 shell-twin incident). Registered in
# _PREMERGE_EXTRA_FILES in the same PR (it rglobs deploy/). Verified by id-set diff: each tree
# ran its OWN scripts/gate_census.py --json (main b73a0d77e = 572, branch = 573); ADDED exactly
# {structural::test_iam_twin_free_3336.py}, REMOVED {}. It arrives PROVEN — a MutationSpec in
# scripts/gate_census_mutations.py plants an untracked deploy/_census_probe_2999.sh heredoc
# naming the remediation role (ARMED: baseline 16 passed / mutated 1 failed / reverted 16
# passed) and STRUCTURAL_PROOFS records it — so live unproven stays 525 and
# BASELINE_UNPROVEN_GATES (541) is not moved.
# 573 -> 574 (2026-08-31, #3318; stacked on #3336 — this branch rebased onto PR #3338): ONE real gate, `guard::scripts/check_pr_closing_set.py`
# — detector B of the closure contract (the PR's closing set asserted against the lane's
# declared target on deploy/wait_pr_green.sh's merge-eligible verdict). Verified by id-set
# diff, not count delta: this branch's own scripts/gate_census.py --json with every new
# file `git add`ed (an untracked guard measures as absent) ADDED exactly that one id,
# REMOVED {} (#3338 tip b68cba0b6 = 573, branch 574); the registry-family regex matches none of the new
# module-level names, so scripts/closure_contract.py mints nothing. It arrives UNPROVEN by
# the census's own ledger (live unproven 525, under the committed 541, which is NOT
# moved) while its fail path is on record three ways: scripted positive controls in
# tests/test_closure_contract_3318.py (PR #3226 / PR #3253 fixtures NONGREEN, PR #3313
# OK, every rule mutation-proven on the control), a live NONGREEN on the real PRs #3226
# and #3253, and a live NONGREEN on its OWN PR's draft body (#3331) before the merge.
# 574 -> 575 (2026-08-31, #3315; stacked on #3318 — this branch rebased onto PR #3341): ONE real gate, `structural::test_ci_dark_flag_sweep_3315.py`
# — the dark-flag sweep (no CI step may reach a dependency its job never installs;
# registering it in _PREMERGE_EXTRA_FILES is part of the same PR). Verified by id-set
# diff (each tree ran its OWN scripts/gate_census.py --json; main from a `git archive`
# export): ADDED {structural::test_ci_dark_flag_sweep_3315.py}, REMOVED {}, plus the
# count-neutral index rename of deploy-wedge-watch.yml's `ci::…::watch::N` ids (two setup
# steps inserted ahead of them: {9,10} in, {1,2} out — no proof or attempt keys on those
# ids). It arrives PROVEN — the mutation is a planted probe workflow carrying the
# pre-#3315 fresh-eyes install line, re-runnable via `gate_census_mutations.py --run
# --gate test_ci_dark_flag_sweep_3315.py` — so the live unproven count does not move and
# BASELINE_UNPROVEN_GATES stays where its owner set it. NOT counted, deliberately: this
# PR's first push showed 576 because the sweep's `_GATE_TOOLS` tuple matched the census's
# registry-name pattern and entered as six `registry::` phantom gates — the #3220
# name-only misfire, cured by renaming the constant, not by bumping onto noise.
# 575 -> 578 (2026-08-31, #2834; stacked on #3315 — rebased onto PR #3339): THREE real gates, one of them PROVEN. TOTAL only —
# BASELINE_UNPROVEN_GATES is NOT moved (live unproven 525 -> 527, still 14 under 541).
# Verified by id-set diff, not count delta: each tree ran its OWN scripts/gate_census.py
# --json with the new files `git add`ed first (#3339 tip 68d087626 = 575, branch = 578).
#   ADDED   guard::deploy/iam_additive_gate.py  -> `can-fail (proven)`. The additive-IAM
#           gate itself, with a real two-direction mutation recorded in
#           gate_census_proofs.GUARD_PROOFS: six defects planted one at a time into a copy
#           of the committed synth slice (iam:PassRole; a foreign Code.S3Bucket; s3:DeleteObject
#           on raw/*; ssm:PutParameter on the remediation kill-switch; the deployed side
#           removed) -> exit 1/1/1/1/2, clean baseline and revert both exit 0, and the
#           2026-08-14 grant still ALLOW-ADDITIVE.
#   ADDED   ci::ci-cd.yml::deploy::2 and ::3 -> unproven, deliberately. They are the Deploy
#           job's dead-man and the additive-IAM deploy step; proving them means watching an
#           approval-gated PRODUCTION deploy fail, which is not a local mutation. The
#           decision they carry IS proven, at the gate above. Recorded rather than absorbed.
#   ADDED   ci::ci-cd.yml::deploy::6 / REMOVED ci::ci-cd.yml::deploy::4 — index churn, not a
#           gate: CI-step ids are positional and the two new steps sit ahead of the code
#           deploys (review N2), sliding the tail by two. Count-neutral, and no proof or
#           attempt record keys on those ids (orphan_proofs: [], unattached_attempts: []).
# 578 -> 584 (2026-08-31, #3329; owner decision of the same date, option B): NOT six new
# gates and NOT a re-baseline — six gates that were always there and were being held OUT
# of the denominator. #3220's name-only candidates now enter the inventory carrying the
# explicit `not-applicable` verdict (the epic's own third term) with a one-line recorded
# reason each, because "570 gates, plus six we do not count" is a number with a silent
# asterisk. Verified by id-set diff, not count delta: each tree ran its OWN
# scripts/gate_census.py --json (main exported with `git archive` at bbd19b112 = 578,
# branch = 584, both trees fully staged — a mid-rebase reading is +4, see the warning above);
# ADDED exactly
#   guard::lambdas/ai/grounding_gate_params.py     guard::lambdas/experiment/experiment_gates.py
#   guard::lambdas/ai/quality_gate_contract.py     guard::tests/conformance_guard_lib.py
#   guard::lambdas/common/item_size_guard.py       guard::tests/truth_baseline_audit.py
# REMOVED {}. BASELINE_UNPROVEN_GATES does NOT move and must not: a not-applicable row is
# not unproven work, and the live unproven count is unchanged at 528 across the diff
# (measured both sides). The whole #3220 invariant — a name-only match can never inflate
# #2578's pile of real proof work — is now enforced by the verdict's TYPE rather than by
# the row's absence, which is the stronger form.
# 584 -> 587 (2026-08-31, #3324; rebased onto main 191c8846b after #3329 took 584; originally measured against PR #3339's
# merge): THREE real gates. Two registry entries — `WRITE_PATH_EXEMPT[/api/cohort_submit]`
# and `WRITE_PATH_EXEMPT[/api/replicate_certify]` in deploy/capture_api_schemas.py — restore
# two POST-only endpoints that were hand-added to tests/api_schemas/_exemptions.json when
# their features shipped (#1394, #1393) but never registered in the script's own
# classification dict, so an un-scoped full `capture_api_schemas.py` recapture (this PR's
# dated #3324 recapture) silently downgraded both to a live-probed "capture-failed-405" and
# broke test_write_path_exemptions_cover_every_post_only_simple_route; registering them here
# makes a future full recapture idempotent. The third is `structural::test_api_schema_
# completeness.py` — the file already enumerated the committed snapshot tree with the
# non-recursive glob.glob; switching to Path's recursive walk (a genuine improvement: a
# nested subdir under tests/api_schemas/ was previously invisible to it) matches
# tests/premerge_derivation.py's `_SWEEP_PATTERN` and correctly joins family 5. Verified
# by id-set diff (each tree ran its
# OWN scripts/gate_census.py --json; main from a `git archive` export at this branch's own
# merge-base, 575): ADDED exactly the three ids above, REMOVED {}. It arrives PROVEN — a
# MutationSpec plants a captured FIXTURE (a copy of tests/api_schemas/api_vitals.json's real
# shape with one key hand-removed, never the live site) and STRUCTURAL_PROOFS records it
# (ARMED: baseline 32 passed / mutated 1 failed / reverted 32 passed) — so live unproven
# moves only by the two registry entries (526 -> 528, still under the committed 541, which
# is NOT moved).
# 587 -> 588 (2026-08-31, #3352): ONE real gate — `ci::site-deploy.yml::visual-qa::6`, the
# `Classify the failing surface (rollback scope check)` step. It is the #3352 scope check's
# reporting half: it runs `tests/visual_qa_verdict.py` over the sweep's own report.json and
# exports the `site_reachable` job output `rollback-site-on-failure` reads before it decides
# whether reverting `site/**` can reach the defect at all. Verified by id-set diff, not by
# count delta (each tree ran its OWN scripts/gate_census.py --json, both fully staged):
# ADDED exactly {ci::site-deploy.yml::visual-qa::6}, REMOVED {}.
#
# It arrives UNPROVEN and that is the honest verdict rather than a gap: the step is an
# INSTRUMENT, not a gate — `visual_qa_verdict.main()` returns 0 on every input, including a
# missing or unparseable report, deliberately (the sweep already decided pass/fail; a second
# failure mode there would only give the rollback a new way not to happen, which is the
# defect #3352 exists to fix). The census's `not-applicable` verdict is keyed by file path
# and reaches the `guard` family only, so a ci-step with nothing to fail has no way to say
# so; recording that here is the next-best thing. The DECISION the step feeds is covered by
# `tests/test_visual_qa_verdict_3352.py` (16 tests over the two measured incident shapes plus
# the negative control) and by the workflow-shape assertions in
# `tests/test_site_deploy_workflow.py`. Live unproven moves 530 -> 531, well under the
# committed BASELINE_UNPROVEN_GATES = 541, which is NOT moved (down-only, #3329 option B).
# 588 -> 589 (2026-08-31, #3384): ONE real gate — `registry::deploy/doc_platform_counts.py::
# PR_EXEMPT_FIELDS::test_count`. The #3101 platform-counts literal sync was extracted out of
# zero-headroom sync_doc_metadata.py into the sibling, and the sibling declares the ONE
# literal `--check` reports as INFO instead of failing on a pull_request event (the counter
# a branch is policy-forbidden to commit; push/main stays enforced). The census's registry
# detector correctly reads that frozenset as an exemption registry — the same family as
# #3324's WRITE_PATH_EXEMPT entries. Verified by id-set diff, not count delta (each tree ran
# its OWN scripts/gate_census.py --json, branch fully staged; main from a `git archive`
# export at origin/main 345677877 = 588, branch = 589): ADDED exactly that one id,
# REMOVED {}.
#
# It arrives UNPROVEN by the census's own ledger while its fail path is on record the #3318
# way — scripted positive controls in tests/test_docs_ci_owns_doc_gates.py: widening the
# frozenset fails test_the_pr_exemption_covers_exactly_the_one_bot_owned_literal; honouring
# it outside pull_request fails test_the_exemption_is_dead_outside_pull_request_events;
# leaking it to any other literal fails test_every_other_literal_stays_enforced_on_
# pull_request; and a write through the exemption fails test_the_pr_exemption_never_writes_
# the_counter. Live unproven moves 531 -> 532, well under the committed
# BASELINE_UNPROVEN_GATES = 541, which is NOT moved (down-only, #3329 option B).
# 589 -> 590 (2026-09-01, #3395): ONE real gate — `guard::deploy/lib/smoke_verdict.sh`, the
# smoke leg's rollback reachability scope (the smoke edition of the #3352 scope check, after
# the 2026-09-01 P3: an `/api/vitals` data-plane smoke red reverted PR #3392's innocent site
# content). Verified by id-set diff, not count delta (each tree ran its OWN
# scripts/gate_census.py --json, branch fully staged; main at this branch's merge-base
# a64a18ee8 = 589, branch = 590): ADDED exactly {guard::deploy/lib/smoke_verdict.sh},
# REMOVED {}.
#
# It arrives UNPROVEN by the census's own detector ("shell entrypoint — slice 1 ships no
# shell detector") and, like the #3352 classifier step above, it is an INSTRUMENT, not a
# gate: `smoke_record_fail`/`smoke_emit_verdict` never fail the smoke run themselves — the
# smoke checks already decided pass/fail, and a second failure mode in the recorder would
# only give the rollback a new way not to happen. The DECISION the verdict feeds is covered
# functionally (real bash, positive AND negative controls: api/infra reds emit
# `site_reachable=false`, a site-only or unknown-surface red keeps `true`, a recorder
# bypass stays fail-safe and loud) in tests/test_smoke_rollback_scope_3395.py, and the
# workflow-shape half by the same file's structural assertions. Live unproven moves
# 532 -> 533, under the committed BASELINE_UNPROVEN_GATES = 541, which is NOT moved
# (down-only, #3329 option B).
# 654 -> 655 (2026-09-18, #3599 box 3): ONE real gate — guard::deploy/prereg_truth_gate.py,
# the pre-seal truth contract (a frozen pre-registration whose coach roster, asserted starting
# weight or min_effect derivation disagrees with the platform's own facts may not acquire a
# hash). Measured twice, never by arithmetic, and BOTH with every new file COMMITTED — the
# #3511 note trailing the assignment below learned that the hard way and the same hole was live
# here: an untracked tests/test_prereg_truth_gate_3599.py + deploy/prereg_truth_gate.py are
# invisible to `gate_census._tracked_files`. RE-MEASURED after a rebase rather than
# incremented, which is the whole reason this line is 655 and not the 654 first recorded here:
# this lane and #3882's #3614 entrant each added exactly one gate and each measured 653 -> 654
# independently against origin/main 56c6c4e7a; #3882 merged first (63c7fc335), so on today's
# main the ceiling already reads 654 and this entrant is the second one. Rebased lane onto
# 63c7fc335, fully committed -> 655; a disposable `git archive origin/main` export at
# 63c7fc335, git-init'd and fully added -> 654. id-set diff between the two --json dumps:
# exactly {guard::deploy/prereg_truth_gate.py} enters, {} leaves. It arrives PROVEN
# (GUARD_PROOFS in scripts/gate_census_proofs.py — four mutations planted one at a time in the
# real tracked module, each watched RED and reverted byte-identical, plus the live run on which
# it found a real defect: 7 blocking findings against the published cycle-17 seal, every
# finding kind reached by one real artifact). So unproven does NOT move (537 -> 537) and
# BASELINE_UNPROVEN_GATES, which is derived from the residue ledger, is untouched. Verdicts on
# the rebased lane {can-fail (proven) 109, unproven 537, not-applicable 6, attempted-unproven
# 3}. No registry-name phantom: FINDING_KINDS is deliberately not spelled `*_CLASSES`/`*_RULES`
# (#3315), and the id-set diff is what proves it rather than the intention.
BASELINE_TOTAL_GATES = 685  # 684 -> 685 (2026-09-23, #3597, re-merged on top of #4075's 684): ONE real entrant — `structural::test_obligation_carriers_3597.py`, the residue-registry derivation guard (every module-level `*_RESIDUE` binding and every tests/*_baseline.json / *residue*.json is registered with a carrier, condition, expiry and shrink consumer) plus the obligation-carrier and demote-field ratchets. It arrives PROVEN via the re-runnable harness (MutationSpec + STRUCTURAL_PROOFS in scripts/gate_census_mutations.py, ARMED 1/1: baseline 32 passed | mutated 1 failed :: test_the_live_residue_registry_meets_its_contract | reverted 32 passed), so unproven does NOT move and BASELINE_UNPROVEN_GATES is untouched. PRIOR: 683 -> 684 (2026-09-23, #4075, re-merged on top of #4107's 683): ONE real entrant — `structural::test_training_load.py`, the TRIMP-exponent rglob guard, PROVEN via the harness (ARMED 1/1: baseline 24 passed | mutated 1 failed | reverted 24 passed); unproven does NOT move. PRIOR: 682 -> 683 (2026-09-23, #4107): ONE real entrant — `structural::test_v03_nearest_band_anchor_4107.py`, the AST derivation guard that load_ramp.v03_floor is the ONE v0.3 load path (generator, planner and the draft_custom commit gate). It arrives PROVEN via the re-runnable harness (MutationSpec + STRUCTURAL_PROOFS in scripts/gate_census_mutations.py, ARMED 1/1: baseline 24 passed | mutated 1 failed :: test_derivation_guard_only_v03_floor_calls_the_ramp_and_the_fallback | reverted 24 passed), so unproven does NOT move and BASELINE_UNPROVEN_GATES is untouched. PRIOR: 681 -> 682 (2026-09-22, #4068): ONE real entrant — `structural::test_shared_quantities_4068.py`, the AST derivation guard that weekly walking hours and the loss rate are read through mcp.shared_quantities at every named critic/tool site (get_benchmark included) and that nothing else builds the walking layer. It arrives PROVEN via the re-runnable harness (MutationSpec + STRUCTURAL_PROOFS in scripts/gate_census_mutations.py, ARMED 1/1: baseline 24 passed | mutated 1 failed :: test_only_the_shared_module_builds_the_walking_layer | reverted 24 passed), so unproven does NOT move (540) and BASELINE_UNPROVEN_GATES is untouched. PRIOR: 680 -> 681 (2026-09-22, #4071): ONE real entrant — `structural::test_muscle_volume_working_sets_4071.py`, the AST derivation guard that `training.muscle_volume.working_sets_by_muscle` is the ONE per-muscle set computation in mcp/ + lambdas/training/. It arrives PROVEN via the re-runnable harness (MutationSpec in scripts/gate_census_mutations.py, ARMED 1/1: baseline 63 passed | mutated 1 failed :: test_no_second_per_muscle_set_computation_in_mcp_or_training | reverted 63 passed), so unproven does NOT move and BASELINE_UNPROVEN_GATES is untouched. MEASURED by id-set diff, never by arithmetic: this lane -> 681 rows {proven 130, unproven 540, not-applicable 6, attempted-unproven 5}; a disposable `git archive origin/main` export at 24996c6c2 -> 680 {129, 540, 6, 5}. Exactly {structural::test_muscle_volume_working_sets_4071.py} enters, {} leaves. PRIOR: 679 -> 680 (2026-09-21, #3760, resolved on top of #3913's 679): ONE real entrant — `structural::test_progress_viewer_privacy_3760.py`, the sweep that keeps the owner-only progress viewer unlinked (site/** rglob + sitemap/feeds/robots/redirects + a scripts/**/*.py generator sweep, plus the edge behaviour, the cookie-literal agreement and #3757's no-`raw/`-in-site_api ruling). It arrives PROVEN via the re-runnable harness (MutationSpec in scripts/gate_census_mutations.py, ARMED 1/1: baseline 16 passed | mutated 1 failed :: test_no_site_file_mentions_the_route | reverted 16 passed), so unproven does NOT move and BASELINE_UNPROVEN_GATES is untouched. MEASURED by id-set diff on the MERGE RESOLUTION tree, never by arithmetic: this lane -> 678 rows {proven 127, unproven 540, not-applicable 6, attempted-unproven 5}; a disposable `git archive origin/main` export -> 677 {126, 540, 6, 5}. Exactly {structural::test_progress_viewer_privacy_3760.py} enters, {} leaves.
# PRIOR NOTE (main's 679): 678 -> 679 (2026-09-21, #3913 box 3): ONE real entrant — `structural::test_day_key_frame_declaration_guard_3913.py` (two AST sweeps: lambdas/ingestion/ for the modules that DERIVE a UTC calendar day, each of which must carry an EXPLICIT day_key_frame on its registry entry — day_key_frame_for() returning 'utc' does not distinguish a declaration from silence resolving to a wrong default, which is how whoop understated its own staleness by 7h for months; and lambdas/ + mcp/ for any function that hand-anchors a YYYY-MM-DD day with a literal tzinfo and then measures a duration from it, which found a THIRD freshness consumer — site_api_status::_comp_status — after #3257 and #2817 each fixed 'the two'). It arrives PROVEN via the re-runnable harness (MutationSpec in scripts/gate_census_mutations.py, ARMED 1/1 — an untracked lambdas/ingestion/_census_probe_3913.py carrying a Zulu-anchored fetch window: baseline 16 passed, mutated 5 failed + 11 passed, reverted 16 passed), so unproven does NOT move and BASELINE_UNPROVEN_GATES is untouched. MEASURED by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 679 rows {proven 128, unproven 540, not-applicable 6, attempted-unproven 5}; a disposable `git archive origin/main` export (bfb163388), git-init'd and fully added -> 678 {127, 540, 6, 5}. RE-MEASURED after merging origin/main into the lane (the tip had moved 6 commits, two of them new test files): merged lane -> 679 {128, 540, 6, 5} vs a fresh export at 5c729ec9c -> 678 {127, 540, 6, 5}. Exactly {structural::test_day_key_frame_declaration_guard_3913.py} enters, {} leaves, no verdict moves, in both measurements. PRIOR NOTE (678): 677 -> 678 (2026-09-21, #3754 boxes 3+4): ONE real entrant — `structural::test_nutrition_critics_3754.py` (os.walk sweep of lambdas/ + mcp/ for any importer of health.nutrition_critics outside the ONE MCP resolver; the refeed / diet-break decision block is owner-only and must never reach site-api, an email or a narrative). It arrives PROVEN via the re-runnable harness (MutationSpec in scripts/gate_census_mutations.py, ARMED 1/1 — an untracked lambdas/web/_census_probe_3754.py carrying a parenthesised multi-line `from health import (..., nutrition_critics)`: baseline 62 passed, mutated 1 failed + 61 passed, reverted 62 passed), so unproven does NOT move and BASELINE_UNPROVEN_GATES is untouched. MEASURED by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 678 rows {proven 127, unproven 540, not-applicable 6, attempted-unproven 5}; a disposable `git archive origin/main` export (2c3b47d48), git-init'd and fully added -> 677 {126, 540, 6, 5}. Exactly {structural::test_nutrition_critics_3754.py} enters, {} leaves, no verdict moves. PRIOR NOTE (677): 676 -> 677 (2026-09-21, #3615 boxes 4+5): ONE real entrant — `structural::test_podcast_feed_link_3615.py` (no committed site/ page may carry a `rel=alternate` link to a feed the hook registry declares dark; the dark set is DERIVED from hook_registry's Absence rows, never hand-listed). It arrives PROVEN via the re-runnable harness (MutationSpec in scripts/gate_census_mutations.py, ARMED 1/1 — an untracked site/_census_probe_3615_box5/index.html advertising /podcast/feed.xml: baseline 8 passed, mutated 1 failed + 7 passed, reverted 8 passed), so unproven does NOT move and BASELINE_UNPROVEN_GATES is untouched. MEASURED by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 677 rows {proven 126, unproven 540, not-applicable 6, attempted-unproven 5}; a disposable `git archive origin/main` export (e2dac0e7e), git-init'd and fully added -> 676 {125, 540, 6, 5}. Exactly {structural::test_podcast_feed_link_3615.py} enters, {} leaves. PRIOR NOTE (676): 675 -> 676 (2026-09-21, #3621 boxes 2+5 re-merged onto main AFTER #4019's 675): ONE real entrant — `structural::test_protocol_lever_contract_3621.py` (the PROTOCOL# spawned_by write-contract sweep over lambdas/ + deploy/ + mcp/; three defects planted one at a time: predicate softened 4 failed, catalogue entry dropped 5 failed, the shell writer restored 1 failed; baseline and restore 27 passed). MEASURED on the merged tree by this ratchet test after `git add` of the resolved files (`676 gates found, above the committed ceiling 675`), never by arithmetic; the lane's own pre-merge reading was 675 against 674. PRIOR NOTE (675): # 674 -> 675 (2026-09-20 PT, #3599 box 2, resolved on top of #3615's 674): ONE real entrant — `structural::test_scoped_writer_provenance_guard_3599.py`, the SOURCE-tier sibling of the #2119 writer guard (every put_item writer landing a row on an EXPERIMENT_SCOPED `USER#matthew#SOURCE#*` partition must stamp or carry a dated waiver). It arrives PROVEN via the re-runnable harness (MutationSpec in scripts/gate_census_mutations.py, ARMED 1/1), so unproven does NOT move and BASELINE_UNPROVEN_GATES is untouched. MEASURED by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 674 rows {proven 123, unproven 540, not-applicable 6, attempted-unproven 5}; a disposable `git archive origin/main` export -> 673 {122, 540, 6, 5}. Exactly {structural::test_scoped_writer_provenance_guard_3599.py} enters, {} leaves. PRIOR NOTE: 672 -> 673 (2026-09-21, #3971 re-merged onto main AFTER #4005's 672): ONE real entrant — `guard::mcp/hevy_prescription_gate.py` (the subtract-only commit gate on manage_hevy_routine; `# gate-entrypoint:` marker inside the first 40 lines, GUARD_PROOFS hand-record, arrives PROVEN — three defects planted one at a time: refusal deleted 9 failed, exemption widened 14 failed, floor arm blinded 5 failed, reverted 18 passed). MEASURED on the merged tree by this ratchet test after `git add` of the resolved files (`673 gates found, above the committed ceiling 672`), never by arithmetic; the pre-merge lane reading was 670 against 669. PRIOR NOTE: 670 -> 672 (2026-09-21, #3621 box 4 re-merged onto main AFTER #4007's 670): TWO real entrants — `ci::citation-network-check.yml::verify::1` (attempted-unproven: a live retraction cannot be planted on NCBI/Crossref) and `guard::scripts/verify_citations.py` (PROVEN, `_fetch_json` monkeypatched to each failure shape with a matching-title control; tests/test_verify_citations_3621.py). MEASURED on the merged tree by this ratchet test after `git add` of the resolved files (the test read `672 gates found, above the committed ceiling 670`), never by arithmetic; the pre-merge lane reading was 671 against 669. PRIOR NOTE: 669 -> 670 (2026-09-21, #3005 fix-forward, merged onto main after #4006): ONE real entrant — `registry::tests/test_no_tool_attribution_3005.py::ALLOWLIST::scripts/install_hooks.sh` (the commit-msg hook names the banned forms to refuse them). Arrives PROVEN (REGISTRY_PROOFS, watched 2026-09-21 00:43Z before the entry existed). Re-measured on the merged tree by this test. PRIOR NOTE: 668 -> 669 (2026-09-20, #3620): ONE real entrant — `structural::test_ip_hash_salt_sweep_3620.py`, the repo-wide sha256(ip) sweep (an os.walk of lambdas/+mcp/ for any `.sha256(...)` call whose argument contains an `ip` token, triaged against an explicit allowlist). Measured by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 669 {can-fail (proven) 119, unproven 540, not-applicable 6, attempted-unproven 4}; a disposable `git archive origin/main` export -> 668 {118, 540, 6, 4}. Exactly {structural::test_ip_hash_salt_sweep_3620.py} enters, {} leaves. It arrives PROVEN — a MutationSpec in scripts/gate_census_mutations.py (an untracked lambdas/common/_census_probe_2999.py module planting `hashlib.sha256(source_ip.encode())`), ARMED 1/1: baseline 4 passed in 0.30s, mutated 1 failed (test_every_sha256_ip_call_site_is_triaged) + 3 passed in 0.31s, reverted 4 passed in 0.28s; full transcript in STRUCTURAL_PROOFS. BASELINE_UNPROVEN_GATES is unaffected — unproven stayed 540. Prior note, 667 -> 668 (2026-09-20, #3754): ONE real entrant — `structural::test_prior_cut_disclosure_3754.py`, the ADR-104 "not comparable to the prior cut" sentence-uniqueness sweep (an os.walk of lambdas/+mcp/ asserting the sentence is a literal string in exactly one file, lambdas/health/deficit_disclosures.py). Measured by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 668 {can-fail (proven) 118, unproven 540, not-applicable 6, attempted-unproven 4}; a disposable `git archive origin/main` export -> 667 {117, 540, 6, 4}. Exactly {structural::test_prior_cut_disclosure_3754.py} enters, {} leaves. It arrives PROVEN — a MutationSpec in scripts/gate_census_mutations.py (an untracked lambdas/health/_census_probe_3754.py planting a second, hand-typed copy of the sentence), ARMED 1/1: baseline 3 passed in 0.17s, mutated 1 failed (test_the_adr104_sentence_is_defined_in_exactly_one_file) + 2 passed in 0.18s, reverted 3 passed in 0.15s; full transcript in STRUCTURAL_PROOFS. BASELINE_UNPROVEN_GATES is unaffected — unproven stayed 540. Prior note, 666 -> 667 (2026-09-20, #3755): ONE real entrant — `structural::test_program_structure_3755.py`, the week-grid seam gate (an os.walk of lambdas/+mcp/ asserting config/training_week.json has exactly ONE reader, training/program_seam.py, plus AST delegation checks that routine_generator.generate_routines and tools_hevy_routine._action_draft_custom each reach it through resolve_week_grid). Measured by id-set diff on COMMITTED trees, never by arithmetic: this lane at 88e5ad923 -> 667 {can-fail (proven) 117, unproven 540, not-applicable 6, attempted-unproven 4}; a disposable `git archive origin/main` export at d7bbecdd5, git-init'd and fully added -> 666 {116, 540, 6, 4}. Exactly {structural::test_program_structure_3755.py} enters, {} leaves. It arrives PROVEN — a MutationSpec in scripts/gate_census_mutations.py (an untracked lambdas/training/_census_probe_3755.py planting a SECOND direct `_load_json("training_week.json")` read, which is the split the seam exists to close), ARMED 1/1: baseline 24 passed, mutated 1 failed (test_only_the_seam_names_the_week_config_filename) + 23 passed, reverted 24 passed; full transcript in STRUCTURAL_PROOFS. BASELINE_UNPROVEN_GATES is unaffected — unproven stayed 540. Prior note, 665 -> 666 (2026-09-20, #3609 box 3, merged onto main at 665): ONE real entrant — `structural::test_gsi_set_premerge_3609.py`, the new premerge GSI-set gate (deploy/deploy_reading_gsis.sh's add_gsi call list, every literal IndexName= on lambdas/+mcp/, and reading_keys.py's GSI*_NAME constants, all asserted equal to ADR-097's {GSI1, GSI2}). RE-MEASURED by id-set diff AFTER `git add`-ing the merge's two resolved conflicts (a mid-merge tracked-file listing lists a conflicted path 3x, once per stage, which briefly over-counted every registry:: gate keyed on this file by 2 — resolved and re-measured, never trusted mid-conflict): a disposable `git archive origin/main` export at c32e58c31 -> 663 {can-fail (proven) 114, unproven 540, not-applicable 6, attempted-unproven 3}; this lane merged -> 664 {115, 540, 6, 3}. Exactly {structural::test_gsi_set_premerge_3609.py} enters, {} leaves. It arrives PROVEN — a MutationSpec in scripts/gate_census_mutations.py (an untracked lambdas/coach/_census_probe_3609.py module planting `table.query(IndexName="GSI9", ...)`), ARMED 1/1: baseline 7 passed, mutated 1 failed (test_every_indexname_literal_on_the_live_surface_is_sanctioned) + 6 passed, reverted 7 passed; full transcript in STRUCTURAL_PROOFS. The gate's other two legs (the GSI*_NAME constant scan, the deploy-script add_gsi scan) carry their own embedded mutation-proof tests (test_planted_gsi_name_constant_is_caught / test_planted_add_gsi_call_is_caught), run every collection. BASELINE_UNPROVEN_GATES is unaffected — unproven stayed 540. Prior note, 660 -> 662 (2026-09-19, #3608 box 5): TWO real entrants, one gate in two halves — the CONVENTIONS §4 FAKE-creds parity run, which was a documented incantation and is now an actual CI step (`ci::.github/workflows/ci-cd.yml::test-critical / AWS creds parity …`) plus the assertion script it calls (`guard::scripts/verify_fake_creds_parity.py`). RE-MEASURED by id-set diff on the COMMITTED, rebased tree, never by arithmetic: this lane at HEAD -> 662 {can-fail (proven) 113, unproven 540, not-applicable 6, attempted-unproven 3}; a disposable `git archive origin/main` export at a3fd9854f -> 660 {113, 538, 6, 3} (re-measured after rebasing onto #3911/#3912, not carried over; the pre-rebase pair at 541f9855d read the same 662 / 660). Diffed BY STABLE KEY as well as by id, because the two disagree here and the disagreement is the finding: CI gate IDS are POSITIONAL (`ci::<wf>::<job>::<step-index>`), so inserting a step renamed the neighbouring lane step's id 3 -> 4 and the raw id diff reported one entrant and one departure with a net of zero. By stable key: exactly the two above enter, {} leaves. Both arrive UNPROVEN as dated lines in tests/gate_census_unproven_residue.py, and the reason is structural rather than a shrug — the failing arm needs a machine where REAL credentials are resolvable, and the CI runner by construction has none; both arms WERE watched locally (exit 1 naming method=shared-credentials-file without the §4 env prefix, exit 0 with it). BASELINE_UNPROVEN_GATES is derived from that ledger and moves 538 -> 540, which is exactly UNPROVEN_CEILING_HIGH_WATER (540) and therefore does not raise it. FIRST DRAFT FINDING, worth keeping: the step was originally `scripts/assert_fake_creds_parity.py` and the census could not see it at all — `_GATE_VERB` recognises `verify_[a-z_]+`, `check_*.py`, `*_gate.py`, `*_guard.py` and not `assert_*`, so a blocking CI step was a DARK gate; the id-set diff is what showed it (no entrant, only the positional shift), and the rename is the fix. SECOND re-measurement, same numbers: `scripts/main_green_expected_jobs.py` (the #1665 extraction out of check_main_green.py) is NOT an entrant — it is named so it matches none of `check_*`/`verify_*`/`*_guard`/`*_gate`/`*_audit` and it mints no verdict, which the id-set diff confirms rather than asserts. Prior note, #3620: 659 -> 660 (2026-09-19, #3620): ONE real gate — the bucket-policy drift leg appended to the EXISTING `drift` job step in .github/workflows/config-drift.yml (live `aws s3api get-bucket-policy` normalised against deploy/bucket_policy.json, plus the shrink-only anonymous-read prefix ratchet in deploy/anonymous_read_prefixes.txt). RE-MEASURED after rebasing onto #3731's 655 -> 659 rather than incremented, twice, on COMMITTED trees, and diffed BY ID: this lane at HEAD -> 660 {can-fail (proven) 113, unproven 538, not-applicable 6, attempted-unproven 3}; a disposable `git archive origin/main` export at c487b4ffc -> 659 {113, 537, 6, 3}. id-set diff between the two --json dumps: exactly {ci::config-drift.yml::drift::6} enters, {} leaves. The PROVEN ceiling is NOT moved (113 -> 113) because the entrant arrives UNPROVEN, as a dated line in tests/gate_census_unproven_residue.py: its failing arm needs a live AWS read under the deploy OIDC role, so a local mutation would be a verdict on a different gate (gate_census.ATTEMPTED_UNPROVEN records the same shape for the ci-lint gitleaks gate); the repo-side half of the SAME derivation IS mutation-proven by tests/test_anonymous_read_prefixes_3620.py::test_a_planted_addition_reds. BASELINE_UNPROVEN_GATES is not moved either — 537 -> 538 stays under it. The #3620 qa-smoke OAuth leg (lambdas/operational/qa_check_oauth_door.py) adds NO census row: the qa family discovers `check_*` defs in qa_smoke_lambda.py and this leg's probes are `_check_*` in a sibling module reached through one registration line — which the id-set diff above demonstrates by naming exactly one entrant, rather than being reasoned about. Prior note, #3731: — FOUR entrants, all arriving PROVEN, not ledgered: tests/repo_scan_cache.py's new disk-backed cache calls `os.walk` in `_tree_fingerprint()`, which makes the module match premerge_derivation.py's `_SWEEP_PATTERN` for the first time, so every test file that imports it (test_doc_facts_ops_1957.py, test_doc_facts_ops_2003.py, test_wiki_checkers.py, test_repo_scan_cache_3224.py) is newly discovered as a tree-sweeping `structural::` gate — correctly, the module genuinely sweeps the tree now. Each proved with the same real plant (docs/_census_probe_3731.md, a wrong CloudWatch alarm-count claim that is also a wiki-index/header violation) via `python3 scripts/gate_census_mutations.py --run --gate structural::test_X.py`, ARMED 4/4; full transcripts in scripts/gate_census_mutations.py's STRUCTURAL_PROOFS. Measured {can-fail (proven) 113, unproven 537, not-applicable 6, attempted-unproven 3} over 659 rows, on this branch rebased onto origin/main (#3889, #3894). BASELINE_UNPROVEN_GATES is unaffected (all four arrive proven; unproven stayed 537). Prior note, #3599 box 3: 654 -> 655 (2026-09-18, #3599 box 3) — the measurement is the comment block directly above, re-taken on the rebased tree, not carried over from the pre-rebase 654. Prior note, #3614: 653 -> 654 (2026-09-18, #3614): ONE real gate — `structural::test_grounding_sets_3614.py`, the two SETs the #1967 grounding registry did not carry (the audience/fail-mode facet, AST-read at each surface's disposition site, and the derived phase-prose census over every prompt builder). Measured twice and diffed by ID, never by arithmetic, and BOTH runs taken with the new files COMMITTED — the condition the note this line replaces was written about: this lane at a0cfa6a91 (rebased onto 9258da37f) -> 654, a disposable `git archive origin/main` export at 9258da37f -> 653. Re-measured after the rebase, not carried over: the first pair (01774bbd6 / 56c6c4e7a) read the same 654 / 653. id-set diff: exactly {structural::test_grounding_sets_3614.py} enters, {} leaves. It arrives PROVEN, so BASELINE_UNPROVEN_GATES is NOT moved and the live unproven count does not move at all (537 -> 537; can-fail 107 -> 108). The proof is a MutationSpec, run by the harness: a synthetic narrative door planted under lambdas/web that hand-types 'Today is Day {n} of the experiment, restarted on {start}' instead of obtaining the phase from ai_context — baseline 27 passed, mutated 3 failed, reverted 27 passed. The facet half's own control is a declaration rather than a file, so it is recorded as M2 on the same proof and also runs on every build against a deepcopy of the registry (flip one public surface to keep-best; and its inverse, which is what shows the AST derivation reads acts=False on 4 of the 32 surfaces rather than being constant-true).  # re-measured 2026-09-18 (#3511) on the MERGED tree, after merging origin/main (ad75a67ca) into this lane and with every new file COMMITTED — both conditions inherited from the note this line replaces, and the second bit once already on this branch: the first census run here was taken with the new files still untracked, read 650 (clean), and CI is what reported the real 651. Measured twice, never by arithmetic: merged tree -> 653, a disposable `git archive origin/main` export -> 652. Verdicts on the merged tree {can-fail (proven) 107, unproven 537, not-applicable 6, attempted-unproven 3}; unproven UNCHANGED at 537. id-set diff between the two --json dumps: exactly {guard::deploy/prereg_provenance_gate.py} enters, {} leaves, and it arrives PROVEN — the #3511 pre-genesis prediction provenance contract (a season PREDICTION# row presenting as pre-genesis must be in the frozen pre-registration; from genesis onward every sealed id must be live in the season). Four mutations planted one at a time in the real tracked module, each reverted before the next, plus the live run on which it found a real defect: 26 blocking findings, 16 of them every cycle-17 sealed bet stranded at phase=pilot. PRIOR NOTE (from main, merged in this resolution): 673 -> 674 (2026-09-21, #3615 boxes 1-3 re-merged onto main AFTER #4014's 673): ONE real entrant — `structural::test_hook_registry_3615.py` (the hooks registry derivation sweep: every site POST endpoint must be claimed by a hook row; MutationSpec ARMED 1/1 — baseline 28 passed, mutated 1 failed test_every_site_post_endpoint_is_claimed_by_a_hook_row, reverted 28 passed). MEASURED on the merged tree by this ratchet test after `git add` of the resolved files (`674 gates found, above the committed ceiling 673`), never by arithmetic; the pre-merge lane reading was 670 against 669. PRIOR NOTE: 672 -> 673 (2026-09-21, #3971 re-merged onto main AFTER #4005's 672): ONE real entrant — `guard::mcp/hevy_prescription_gate.py` (the subtract-only commit gate on manage_hevy_routine; `# gate-entrypoint:` marker inside the first 40 lines, GUARD_PROOFS hand-record, arrives PROVEN — three defects planted one at a time: refusal deleted 9 failed, exemption widened 14 failed, floor arm blinded 5 failed, reverted 18 passed). MEASURED on the merged tree by this ratchet test after `git add` of the resolved files (`673 gates found, above the committed ceiling 672`), never by arithmetic; the pre-merge lane reading was 670 against 669. PRIOR NOTE: 670 -> 672 (2026-09-21, #3621 box 4 re-merged onto main AFTER #4007's 670): TWO real entrants — `ci::citation-network-check.yml::verify::1` (attempted-unproven: a live retraction cannot be planted on NCBI/Crossref) and `guard::scripts/verify_citations.py` (PROVEN, `_fetch_json` monkeypatched to each failure shape with a matching-title control; tests/test_verify_citations_3621.py). MEASURED on the merged tree by this ratchet test after `git add` of the resolved files (the test read `672 gates found, above the committed ceiling 670`), never by arithmetic; the pre-merge lane reading was 671 against 669. PRIOR NOTE: 669 -> 670 (2026-09-21, #3005 fix-forward, merged onto main after #4006): ONE real entrant — `registry::tests/test_no_tool_attribution_3005.py::ALLOWLIST::scripts/install_hooks.sh` (the commit-msg hook names the banned forms to refuse them). Arrives PROVEN (REGISTRY_PROOFS, watched 2026-09-21 00:43Z before the entry existed). Re-measured on the merged tree by this test. PRIOR NOTE: 668 -> 669 (2026-09-20, #3620): ONE real entrant — `structural::test_ip_hash_salt_sweep_3620.py`, the repo-wide sha256(ip) sweep (an os.walk of lambdas/+mcp/ for any `.sha256(...)` call whose argument contains an `ip` token, triaged against an explicit allowlist). Measured by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 669 {can-fail (proven) 119, unproven 540, not-applicable 6, attempted-unproven 4}; a disposable `git archive origin/main` export -> 668 {118, 540, 6, 4}. Exactly {structural::test_ip_hash_salt_sweep_3620.py} enters, {} leaves. It arrives PROVEN — a MutationSpec in scripts/gate_census_mutations.py (an untracked lambdas/common/_census_probe_2999.py module planting `hashlib.sha256(source_ip.encode())`), ARMED 1/1: baseline 4 passed in 0.30s, mutated 1 failed (test_every_sha256_ip_call_site_is_triaged) + 3 passed in 0.31s, reverted 4 passed in 0.28s; full transcript in STRUCTURAL_PROOFS. BASELINE_UNPROVEN_GATES is unaffected — unproven stayed 540. Prior note, 667 -> 668 (2026-09-20, #3754): ONE real entrant — `structural::test_prior_cut_disclosure_3754.py`, the ADR-104 "not comparable to the prior cut" sentence-uniqueness sweep (an os.walk of lambdas/+mcp/ asserting the sentence is a literal string in exactly one file, lambdas/health/deficit_disclosures.py). Measured by id-set diff on COMMITTED trees, never by arithmetic: this lane -> 668 {can-fail (proven) 118, unproven 540, not-applicable 6, attempted-unproven 4}; a disposable `git archive origin/main` export -> 667 {117, 540, 6, 4}. Exactly {structural::test_prior_cut_disclosure_3754.py} enters, {} leaves. It arrives PROVEN — a MutationSpec in scripts/gate_census_mutations.py (an untracked lambdas/health/_census_probe_3754.py planting a second, hand-typed copy of the sentence), ARMED 1/1: baseline 3 passed in 0.17s, mutated 1 failed (test_the_adr104_sentence_is_defined_in_exactly_one_file) + 2 passed in 0.18s, reverted 3 passed in 0.15s; full transcript in STRUCTURAL_PROOFS. BASELINE_UNPROVEN_GATES is unaffected — unproven stayed 540. Prior note, 666 -> 667 (2026-09-20, #3755): ONE real entrant — `structural::test_program_structure_3755.py`, the week-grid seam gate (an os.walk of lambdas/+mcp/ asserting config/training_week.json has exactly ONE reader, training/program_seam.py, plus AST delegation checks that routine_generator.generate_routines and tools_hevy_routine._action_draft_custom each reach it through resolve_week_grid). Measured by id-set diff on COMMITTED trees, never by arithmetic: this lane at 88e5ad923 -> 667 {can-fail (proven) 117, unproven 540, not-applicable 6, attempted-unproven 4}; a disposable `git archive origin/main` export at d7bbecdd5, git-init'd and fully added -> 666 {116, 540, 6, 4}. Exactly {structural::test_program_structure_3755.py} enters, {} leaves. It arrives PROVEN — a MutationSpec in scripts/gate_census_mutations.py (an untracked lambdas/training/_census_probe_3755.py planting a SECOND direct `_load_json("training_week.json")` read, which is the split the seam exists to close), ARMED 1/1: baseline 24 passed, mutated 1 failed (test_only_the_seam_names_the_week_config_filename) + 23 passed, reverted 24 passed; full transcript in STRUCTURAL_PROOFS. BASELINE_UNPROVEN_GATES is unaffected — unproven stayed 540. Prior note, 665 -> 666 (2026-09-20, #3609 box 3, merged onto main at 665): ONE real entrant — `structural::test_gsi_set_premerge_3609.py`, the new premerge GSI-set gate (deploy/deploy_reading_gsis.sh's add_gsi call list, every literal IndexName= on lambdas/+mcp/, and reading_keys.py's GSI*_NAME constants, all asserted equal to ADR-097's {GSI1, GSI2}). RE-MEASURED by id-set diff AFTER `git add`-ing the merge's two resolved conflicts (a mid-merge tracked-file listing lists a conflicted path 3x, once per stage, which briefly over-counted every registry:: gate keyed on this file by 2 — resolved and re-measured, never trusted mid-conflict): a disposable `git archive origin/main` export at c32e58c31 -> 663 {can-fail (proven) 114, unproven 540, not-applicable 6, attempted-unproven 3}; this lane merged -> 664 {115, 540, 6, 3}. Exactly {structural::test_gsi_set_premerge_3609.py} enters, {} leaves. It arrives PROVEN — a MutationSpec in scripts/gate_census_mutations.py (an untracked lambdas/coach/_census_probe_3609.py module planting `table.query(IndexName="GSI9", ...)`), ARMED 1/1: baseline 7 passed, mutated 1 failed (test_every_indexname_literal_on_the_live_surface_is_sanctioned) + 6 passed, reverted 7 passed; full transcript in STRUCTURAL_PROOFS. The gate's other two legs (the GSI*_NAME constant scan, the deploy-script add_gsi scan) carry their own embedded mutation-proof tests (test_planted_gsi_name_constant_is_caught / test_planted_add_gsi_call_is_caught), run every collection. BASELINE_UNPROVEN_GATES is unaffected — unproven stayed 540. Prior note, 660 -> 662 (2026-09-19, #3608 box 5): TWO real entrants, one gate in two halves — the CONVENTIONS §4 FAKE-creds parity run, which was a documented incantation and is now an actual CI step (`ci::.github/workflows/ci-cd.yml::test-critical / AWS creds parity …`) plus the assertion script it calls (`guard::scripts/verify_fake_creds_parity.py`). RE-MEASURED by id-set diff on the COMMITTED, rebased tree, never by arithmetic: this lane at HEAD -> 662 {can-fail (proven) 113, unproven 540, not-applicable 6, attempted-unproven 3}; a disposable `git archive origin/main` export at a3fd9854f -> 660 {113, 538, 6, 3} (re-measured after rebasing onto #3911/#3912, not carried over; the pre-rebase pair at 541f9855d read the same 662 / 660). Diffed BY STABLE KEY as well as by id, because the two disagree here and the disagreement is the finding: CI gate IDS are POSITIONAL (`ci::<wf>::<job>::<step-index>`), so inserting a step renamed the neighbouring lane step's id 3 -> 4 and the raw id diff reported one entrant and one departure with a net of zero. By stable key: exactly the two above enter, {} leaves. Both arrive UNPROVEN as dated lines in tests/gate_census_unproven_residue.py, and the reason is structural rather than a shrug — the failing arm needs a machine where REAL credentials are resolvable, and the CI runner by construction has none; both arms WERE watched locally (exit 1 naming method=shared-credentials-file without the §4 env prefix, exit 0 with it). BASELINE_UNPROVEN_GATES is derived from that ledger and moves 538 -> 540, which is exactly UNPROVEN_CEILING_HIGH_WATER (540) and therefore does not raise it. FIRST DRAFT FINDING, worth keeping: the step was originally `scripts/assert_fake_creds_parity.py` and the census could not see it at all — `_GATE_VERB` recognises `verify_[a-z_]+`, `check_*.py`, `*_gate.py`, `*_guard.py` and not `assert_*`, so a blocking CI step was a DARK gate; the id-set diff is what showed it (no entrant, only the positional shift), and the rename is the fix. SECOND re-measurement, same numbers: `scripts/main_green_expected_jobs.py` (the #1665 extraction out of check_main_green.py) is NOT an entrant — it is named so it matches none of `check_*`/`verify_*`/`*_guard`/`*_gate`/`*_audit` and it mints no verdict, which the id-set diff confirms rather than asserts. Prior note, #3620: 659 -> 660 (2026-09-19, #3620): ONE real gate — the bucket-policy drift leg appended to the EXISTING `drift` job step in .github/workflows/config-drift.yml (live `aws s3api get-bucket-policy` normalised against deploy/bucket_policy.json, plus the shrink-only anonymous-read prefix ratchet in deploy/anonymous_read_prefixes.txt). RE-MEASURED after rebasing onto #3731's 655 -> 659 rather than incremented, twice, on COMMITTED trees, and diffed BY ID: this lane at HEAD -> 660 {can-fail (proven) 113, unproven 538, not-applicable 6, attempted-unproven 3}; a disposable `git archive origin/main` export at c487b4ffc -> 659 {113, 537, 6, 3}. id-set diff between the two --json dumps: exactly {ci::config-drift.yml::drift::6} enters, {} leaves. The PROVEN ceiling is NOT moved (113 -> 113) because the entrant arrives UNPROVEN, as a dated line in tests/gate_census_unproven_residue.py: its failing arm needs a live AWS read under the deploy OIDC role, so a local mutation would be a verdict on a different gate (gate_census.ATTEMPTED_UNPROVEN records the same shape for the ci-lint gitleaks gate); the repo-side half of the SAME derivation IS mutation-proven by tests/test_anonymous_read_prefixes_3620.py::test_a_planted_addition_reds. BASELINE_UNPROVEN_GATES is not moved either — 537 -> 538 stays under it. The #3620 qa-smoke OAuth leg (lambdas/operational/qa_check_oauth_door.py) adds NO census row: the qa family discovers `check_*` defs in qa_smoke_lambda.py and this leg's probes are `_check_*` in a sibling module reached through one registration line — which the id-set diff above demonstrates by naming exactly one entrant, rather than being reasoned about. Prior note, #3731: — FOUR entrants, all arriving PROVEN, not ledgered: tests/repo_scan_cache.py's new disk-backed cache calls `os.walk` in `_tree_fingerprint()`, which makes the module match premerge_derivation.py's `_SWEEP_PATTERN` for the first time, so every test file that imports it (test_doc_facts_ops_1957.py, test_doc_facts_ops_2003.py, test_wiki_checkers.py, test_repo_scan_cache_3224.py) is newly discovered as a tree-sweeping `structural::` gate — correctly, the module genuinely sweeps the tree now. Each proved with the same real plant (docs/_census_probe_3731.md, a wrong CloudWatch alarm-count claim that is also a wiki-index/header violation) via `python3 scripts/gate_census_mutations.py --run --gate structural::test_X.py`, ARMED 4/4; full transcripts in scripts/gate_census_mutations.py's STRUCTURAL_PROOFS. Measured {can-fail (proven) 113, unproven 537, not-applicable 6, attempted-unproven 3} over 659 rows, on this branch rebased onto origin/main (#3889, #3894). BASELINE_UNPROVEN_GATES is unaffected (all four arrive proven; unproven stayed 537). Prior note, #3599 box 3: 654 -> 655 (2026-09-18, #3599 box 3) — the measurement is the comment block directly above, re-taken on the rebased tree, not carried over from the pre-rebase 654. Prior note, #3614: 653 -> 654 (2026-09-18, #3614): ONE real gate — `structural::test_grounding_sets_3614.py`, the two SETs the #1967 grounding registry did not carry (the audience/fail-mode facet, AST-read at each surface's disposition site, and the derived phase-prose census over every prompt builder). Measured twice and diffed by ID, never by arithmetic, and BOTH runs taken with the new files COMMITTED — the condition the note this line replaces was written about: this lane at a0cfa6a91 (rebased onto 9258da37f) -> 654, a disposable `git archive origin/main` export at 9258da37f -> 653. Re-measured after the rebase, not carried over: the first pair (01774bbd6 / 56c6c4e7a) read the same 654 / 653. id-set diff: exactly {structural::test_grounding_sets_3614.py} enters, {} leaves. It arrives PROVEN, so BASELINE_UNPROVEN_GATES is NOT moved and the live unproven count does not move at all (537 -> 537; can-fail 107 -> 108). The proof is a MutationSpec, run by the harness: a synthetic narrative door planted under lambdas/web that hand-types 'Today is Day {n} of the experiment, restarted on {start}' instead of obtaining the phase from ai_context — baseline 27 passed, mutated 3 failed, reverted 27 passed. The facet half's own control is a declaration rather than a file, so it is recorded as M2 on the same proof and also runs on every build against a deepcopy of the registry (flip one public surface to keep-best; and its inverse, which is what shows the AST derivation reads acts=False on 4 of the 32 surfaces rather than being constant-true).  # re-measured 2026-09-18 (#3511) on the MERGED tree, after merging origin/main (ad75a67ca) into this lane and with every new file COMMITTED — both conditions inherited from the note this line replaces, and the second bit once already on this branch: the first census run here was taken with the new files still untracked, read 650 (clean), and CI is what reported the real 651. Measured twice, never by arithmetic: merged tree -> 653, a disposable `git archive origin/main` export -> 652. Verdicts on the merged tree {can-fail (proven) 107, unproven 537, not-applicable 6, attempted-unproven 3}; unproven UNCHANGED at 537. id-set diff between the two --json dumps: exactly {guard::deploy/prereg_provenance_gate.py} enters, {} leaves, and it arrives PROVEN — the #3511 pre-genesis prediction provenance contract (a season PREDICTION# row presenting as pre-genesis must be in the frozen pre-registration; from genesis onward every sealed id must be live in the season). Four mutations planted one at a time in the real tracked module, each reverted before the next, plus the live run on which it found a real defect: 26 blocking findings, 16 of them every cycle-17 sealed bet stranded at phase=pilot.

# Prior note: 664 -> 665 (2026-09-20, #3620 box 1): ONE real entrant — the live `/api/*` PII-surface sweep, scheduled for the first time (`ci::pii-endpoint-sweep.yml::sweep::3`, running deploy/pii_surface_guard.py --endpoints against the deployed production site on a new daily cron). Measured by id-set diff on this branch, MERGED onto origin/main (664): {can-fail (proven) 113, unproven 540, not-applicable 6, attempted-unproven 4} over 665 rows; a disposable `git archive origin/main` export -> 664 {113, 540, 6, 3}. Exactly {ci::pii-endpoint-sweep.yml::sweep::3} enters, {} leaves. It arrives `attempted-unproven`, NOT a plain-unproven ledger line: its failing arm needs a genuine PII tell live on prod or a genuinely unreachable content-filter channel, and staging either from a PR-lane mutation means planting a leak on prod or faking an AWS outage the runner does not actually have — the same shape ATTEMPTED_UNPROVEN already records for the ci-lint gitleaks entry and #3620's own bucket-policy-drift line, so the reason is added there (`scripts/gate_census.py::ATTEMPTED_UNPROVEN["ci::pii-endpoint-sweep.yml::sweep::3"]`) rather than as a new line in tests/gate_census_unproven_residue.py. BASELINE_UNPROVEN_GATES is therefore UNCHANGED at 540 — this entrant does not touch the down-only ceiling, deliberately: raising it is an owner call (test_the_unproven_ceiling_is_down_only), and this entrant does not need one. What IS mutation-proven, at the unit level, is the function the step wires: tests/test_public_surface_pii_guard.py::test_live_arm_unreachable_endpoint_is_a_violation_never_a_pass and its sibling planted-tell tests inject a fake fetcher into scan_endpoints() and assert it reports a violation rather than a silent pass.
# Prior note: 662 -> 664 (2026-09-20): #3625's test_bundle_zip_reproducible_3625.py AND #3772's check_orphan_routine_drafts, both proven in gate_census_proofs; the two PRs land in either order under one ceiling. Previous: 660 -> 662 (2026-09-19, #3608 box 5): TWO real entrants, one gate in two halves — the CONVENTIONS §4 FAKE-creds parity run, which was a documented incantation and is now an actual CI step (`ci::.github/workflows/ci-cd.yml::test-critical / AWS creds parity …`) plus the assertion script it calls (`guard::scripts/verify_fake_creds_parity.py`). RE-MEASURED by id-set diff on the COMMITTED, rebased tree, never by arithmetic: this lane at HEAD -> 662 {can-fail (proven) 113, unproven 540, not-applicable 6, attempted-unproven 3}; a disposable `git archive origin/main` export at a3fd9854f -> 660 {113, 538, 6, 3} (re-measured after rebasing onto #3911/#3912, not carried over; the pre-rebase pair at 541f9855d read the same 662 / 660). Diffed BY STABLE KEY as well as by id, because the two disagree here and the disagreement is the finding: CI gate IDS are POSITIONAL (`ci::<wf>::<job>::<step-index>`), so inserting a step renamed the neighbouring lane step's id 3 -> 4 and the raw id diff reported one entrant and one departure with a net of zero. By stable key: exactly the two above enter, {} leaves. Both arrive UNPROVEN as dated lines in tests/gate_census_unproven_residue.py, and the reason is structural rather than a shrug — the failing arm needs a machine where REAL credentials are resolvable, and the CI runner by construction has none; both arms WERE watched locally (exit 1 naming method=shared-credentials-file without the §4 env prefix, exit 0 with it). BASELINE_UNPROVEN_GATES is derived from that ledger and moves 538 -> 540, which is exactly UNPROVEN_CEILING_HIGH_WATER (540) and therefore does not raise it. FIRST DRAFT FINDING, worth keeping: the step was originally `scripts/assert_fake_creds_parity.py` and the census could not see it at all — `_GATE_VERB` recognises `verify_[a-z_]+`, `check_*.py`, `*_gate.py`, `*_guard.py` and not `assert_*`, so a blocking CI step was a DARK gate; the id-set diff is what showed it (no entrant, only the positional shift), and the rename is the fix. SECOND re-measurement, same numbers: `scripts/main_green_expected_jobs.py` (the #1665 extraction out of check_main_green.py) is NOT an entrant — it is named so it matches none of `check_*`/`verify_*`/`*_guard`/`*_gate`/`*_audit` and it mints no verdict, which the id-set diff confirms rather than asserts. Prior note, #3620: 659 -> 660 (2026-09-19, #3620): ONE real gate — the bucket-policy drift leg appended to the EXISTING `drift` job step in .github/workflows/config-drift.yml (live `aws s3api get-bucket-policy` normalised against deploy/bucket_policy.json, plus the shrink-only anonymous-read prefix ratchet in deploy/anonymous_read_prefixes.txt). RE-MEASURED after rebasing onto #3731's 655 -> 659 rather than incremented, twice, on COMMITTED trees, and diffed BY ID: this lane at HEAD -> 660 {can-fail (proven) 113, unproven 538, not-applicable 6, attempted-unproven 3}; a disposable `git archive origin/main` export at c487b4ffc -> 659 {113, 537, 6, 3}. id-set diff between the two --json dumps: exactly {ci::config-drift.yml::drift::6} enters, {} leaves. The PROVEN ceiling is NOT moved (113 -> 113) because the entrant arrives UNPROVEN, as a dated line in tests/gate_census_unproven_residue.py: its failing arm needs a live AWS read under the deploy OIDC role, so a local mutation would be a verdict on a different gate (gate_census.ATTEMPTED_UNPROVEN records the same shape for the ci-lint gitleaks gate); the repo-side half of the SAME derivation IS mutation-proven by tests/test_anonymous_read_prefixes_3620.py::test_a_planted_addition_reds. BASELINE_UNPROVEN_GATES is not moved either — 537 -> 538 stays under it. The #3620 qa-smoke OAuth leg (lambdas/operational/qa_check_oauth_door.py) adds NO census row: the qa family discovers `check_*` defs in qa_smoke_lambda.py and this leg's probes are `_check_*` in a sibling module reached through one registration line — which the id-set diff above demonstrates by naming exactly one entrant, rather than being reasoned about. Prior note, #3731: — FOUR entrants, all arriving PROVEN, not ledgered: tests/repo_scan_cache.py's new disk-backed cache calls `os.walk` in `_tree_fingerprint()`, which makes the module match premerge_derivation.py's `_SWEEP_PATTERN` for the first time, so every test file that imports it (test_doc_facts_ops_1957.py, test_doc_facts_ops_2003.py, test_wiki_checkers.py, test_repo_scan_cache_3224.py) is newly discovered as a tree-sweeping `structural::` gate — correctly, the module genuinely sweeps the tree now. Each proved with the same real plant (docs/_census_probe_3731.md, a wrong CloudWatch alarm-count claim that is also a wiki-index/header violation) via `python3 scripts/gate_census_mutations.py --run --gate structural::test_X.py`, ARMED 4/4; full transcripts in scripts/gate_census_mutations.py's STRUCTURAL_PROOFS. Measured {can-fail (proven) 113, unproven 537, not-applicable 6, attempted-unproven 3} over 659 rows, on this branch rebased onto origin/main (#3889, #3894). BASELINE_UNPROVEN_GATES is unaffected (all four arrive proven; unproven stayed 537). Prior note, #3599 box 3: 654 -> 655 (2026-09-18, #3599 box 3) — the measurement is the comment block directly above, re-taken on the rebased tree, not carried over from the pre-rebase 654. Prior note, #3614: 653 -> 654 (2026-09-18, #3614): ONE real gate — `structural::test_grounding_sets_3614.py`, the two SETs the #1967 grounding registry did not carry (the audience/fail-mode facet, AST-read at each surface's disposition site, and the derived phase-prose census over every prompt builder). Measured twice and diffed by ID, never by arithmetic, and BOTH runs taken with the new files COMMITTED — the condition the note this line replaces was written about: this lane at a0cfa6a91 (rebased onto 9258da37f) -> 654, a disposable `git archive origin/main` export at 9258da37f -> 653. Re-measured after the rebase, not carried over: the first pair (01774bbd6 / 56c6c4e7a) read the same 654 / 653. id-set diff: exactly {structural::test_grounding_sets_3614.py} enters, {} leaves. It arrives PROVEN, so BASELINE_UNPROVEN_GATES is NOT moved and the live unproven count does not move at all (537 -> 537; can-fail 107 -> 108). The proof is a MutationSpec, run by the harness: a synthetic narrative door planted under lambdas/web that hand-types 'Today is Day {n} of the experiment, restarted on {start}' instead of obtaining the phase from ai_context — baseline 27 passed, mutated 3 failed, reverted 27 passed. The facet half's own control is a declaration rather than a file, so it is recorded as M2 on the same proof and also runs on every build against a deepcopy of the registry (flip one public surface to keep-best; and its inverse, which is what shows the AST derivation reads acts=False on 4 of the 32 surfaces rather than being constant-true).  # re-measured 2026-09-18 (#3511) on the MERGED tree, after merging origin/main (ad75a67ca) into this lane and with every new file COMMITTED — both conditions inherited from the note this line replaces, and the second bit once already on this branch: the first census run here was taken with the new files still untracked, read 650 (clean), and CI is what reported the real 651. Measured twice, never by arithmetic: merged tree -> 653, a disposable `git archive origin/main` export -> 652. Verdicts on the merged tree {can-fail (proven) 107, unproven 537, not-applicable 6, attempted-unproven 3}; unproven UNCHANGED at 537. id-set diff between the two --json dumps: exactly {guard::deploy/prereg_provenance_gate.py} enters, {} leaves, and it arrives PROVEN — the #3511 pre-genesis prediction provenance contract (a season PREDICTION# row presenting as pre-genesis must be in the frozen pre-registration; from genesis onward every sealed id must be live in the season). Four mutations planted one at a time in the real tracked module, each reverted before the next, plus the live run on which it found a real defect: 26 blocking findings, 16 of them every cycle-17 sealed bet stranded at phase=pilot.

# ══════════════════════════════════════════════════════════════════════════════
# DOWN-ONLY (#3329, owner decision 2026-08-31 option B). Epic #2578's box 2 was
# re-scoped to the claim this census can verify: every gate entering after
# 2026-08-24 arrives proven under the #3000 ratchet, and the INSTALLED unproven base
# is tracked by this number, which may only move DOWN.
#
# So the ceiling below is no longer "bump it with a reason" — a new gate arrives with
# a verdict or it does not land. `UNPROVEN_CEILING_HIGH_WATER` is the structural half
# of that: raising BASELINE_UNPROVEN_GATES now reds `test_the_unproven_ceiling_is_down_only`
# as well, so a raise cannot be a one-token edit made at 2am to get a lane green. The
# sanctioned move is the opposite one — lower BOTH to the live count whenever the
# measurement allows, which is the progress record the epic asks for.
# 541 -> 540 (2026-09-05, #3536): the per-entrant rule lands. NOT a raise and not a
# re-baseline — the ceiling is now the SIZE of the ledger in
# tests/gate_census_unproven_residue.py: 538 live `unproven` gates measured on main at
# ea41f094b (597 total, 50 proven) plus TWO entrants named by PR that were already open
# and measured on their own branch exports at the seal (PR #3588's
# structural::test_no_dead_shared_defs_3538.py and PR #3583's
# registry::lambdas/ai/budget_guard.py::_SCOPE_ALL_CLASSES). Their merge is those lines'
# exit; until then the live advisory below prints them by name as ratchet-down available,
# which is the honest state, not a defect. The 16 of slack the count carried is gone —
# the third entrant from here needs a verdict or a dated ledger line, never a bump.
UNPROVEN_CEILING_HIGH_WATER = 540
# 596 -> 597 (2026-09-05, #3503): ONE real gate —
#   structural::test_composite_alarm_lookup_3390.py
# The #3390 guard was a two-test, one-file pin on `deploy/restart_verify.py`; #3503 widened
# it into a family-5 tree sweep over remediation/ scripts/ lambdas/ deploy/ cdk/ mcp/ that
# requires every `describe_alarms`/`describe_alarm_history` call to state its `AlarmTypes`
# (the API default is metric alarms only, so six real callers were structurally blind to
# both composite alarms). The widening is what mints it as a census gate: same file, new
# family. It arrives PROVEN, not unproven — `python3 scripts/gate_census_mutations.py --run
# --gate test_composite_alarm_lookup_3390.py` plants an untracked
# `deploy/_census_probe_3503.py` (a whole-estate sweep with no AlarmTypes) and reports
# ARMED: baseline 11 passed, mutated 1 failed / 10 passed on
# test_every_alarm_read_states_its_alarm_types, reverted 11 passed. So live UNPROVEN does
# not move (538 -> 538) and BASELINE_UNPROVEN_GATES stays where its owner set it.
# Measured by id-set diff with the tree git-added, per the warning above: exactly one id
# enters and none leaves.
# DERIVED since #3536: the ceiling IS the ledger. Lowering it means deleting a ledger
# line (the gate was proven, attempted, ruled not-applicable, or retired); it cannot be
# edited here at all, which is the point — there is no number to bump at 2am.
BASELINE_UNPROVEN_GATES = len(UNPROVEN_RESIDUE)

# The gap this ceiling is allowed to carry before the census says "you can ratchet down".
# 16 from 2026-08-24 to #3536 (541 committed vs 525–538 live), kept "so a lane that
# legitimately adds one unproven gate does not have to touch this file" — which is exactly
# the silent entry the #3536 finding measured (35 guards, no must-fail control, no ratchet
# line). ZERO since 2026-09-05: a lane that adds an unproven gate DOES touch a file, by
# design, and the file is the ledger. Non-fatal, reported by name, actionable.
RATCHET_DOWN_SLACK = 0

_CENSUS_FAMILIES = ("ci", "guard", "registry", "qa", "structural", "sentinel")


def stable_key(gate: dict) -> str:
    """The ledger key for one census gate row.

    Every family's id is content-keyed (a path, a registry name, a check function) except
    `ci`, whose id is positional — `ci::<wf>::<job>::<index>` — so inserting one step
    slides every later id (gate_census.py's own docstring; the reason #3000 ratcheted a
    COUNT). A CI step is keyed on its workflow path + the census's `<job> / <label>` name,
    which survives insertion and changes only on a relabel.
    """
    if gate["id"].startswith("ci::"):
        return f"ci::{gate['source']}::{gate['name']}"
    return gate["id"]


def check_unproven_entrants(unproven_keys: Iterable[str], residue: Mapping[str, str] = UNPROVEN_RESIDUE) -> tuple[bool, str]:
    """THE per-entrant rule (#3536). Pure — keys in, verdict out, no repo read.

    Every key the live census reports `unproven` must be in the ledger. A key that is not
    is a gate that entered with no verdict, and the count rule below cannot see it once
    another gate was proven in the same PR ("prove one, mint one").
    """
    keys = list(unproven_keys)
    entrants = sorted(k for k in keys if k not in residue)
    if entrants:
        return False, (
            f"{len(entrants)} gate(s) entered the platform with no verdict and no ledger line (#3536):\n  "
            + "\n  ".join(entrants)
            + "\nA new gate arrives PROVEN (a MutationSpec in scripts/gate_census_mutations.py or a record in "
            "scripts/gate_census_proofs.py), ATTEMPTED with the reason (gate_census.ATTEMPTED_UNPROVEN), or "
            "`not-applicable` with a reason (gate_census_enforcement.NOT_APPLICABLE_REASONS). If it truly must "
            "enter unproven, that is a dated line in tests/gate_census_unproven_residue.py with the reason — "
            "in the diff, never absorbed. If it is a registry-name phantom (#3315: a module-level name matching "
            "gate_census._REGISTRY_NAME), rename the constant."
        )
    return True, f"every live unproven gate ({len(keys)}) is in the ledger."


def ratchet_down_entries(unproven_keys: Iterable[str], residue: Mapping[str, str] = UNPROVEN_RESIDUE) -> list[str]:
    """Ledger lines whose gate is no longer live-unproven: proven, attempted, ruled
    not-applicable, retired, or (for the two in-flight seal entries) not yet merged. Each is
    a delete waiting to be made — the progress record the epic asks for, by name."""
    live = set(unproven_keys)
    return sorted(k for k in residue if k not in live)


def check_unproven_ceiling(total_gates: int, unproven_gates: int) -> tuple[bool, str]:
    """Pure decision function. Takes its numbers as arguments — never reads the live
    repo itself — so the RULE can be mutation-proven independent of today's count."""
    if unproven_gates > BASELINE_UNPROVEN_GATES:
        return False, (
            f"{unproven_gates} gates now carry no verdict, above the committed ceiling "
            f"{BASELINE_UNPROVEN_GATES}. A gate entered the platform with no verdict and "
            "nothing said so out loud: give it a verdict (PROVEN_CAN_FAIL / "
            "ATTEMPTED_UNPROVEN in scripts/gate_census.py), or — if nothing in it can fail "
            "— a `not-applicable` reason in gate_census_enforcement.NOT_APPLICABLE_REASONS. "
            "BASELINE_UNPROVEN_GATES is DOWN-ONLY since the 2026-08-31 owner decision on "
            "#3329 (option B) and since #3536 it is the SIZE of tests/gate_census_unproven_residue.py: "
            "there is no number to raise here; the entrant is named by check_unproven_entrants."
        )
    if total_gates > BASELINE_TOTAL_GATES:
        return False, (
            f"{total_gates} gates found, above the committed ceiling {BASELINE_TOTAL_GATES} "
            "— bump BASELINE_TOTAL_GATES here in the same PR that grew the inventory (#3000)."
        )
    return True, f"{total_gates} gates found ({unproven_gates} unproven), within the committed ceiling."


def ratchet_down_available(
    unproven_gates: int, ceiling: int = BASELINE_UNPROVEN_GATES, slack: int = RATCHET_DOWN_SLACK
) -> tuple[bool, str]:
    """Is the committed ceiling further above the live pile than the stated slack?

    NON-FATAL by design (#3329): this reports a move that is available, it does not
    fail a build for not having made it. A ratchet whose only voice is a red teaches
    people to raise the number; one that says "you can lower this by N" every run,
    out loud, is the direction-of-travel record the epic's box 2 was re-scoped to.

    Pure — integers in, verdict out, no repo read, so the RULE is mutation-provable
    independent of today's count.
    """
    gap = ceiling - unproven_gates
    if gap > slack:
        return True, (
            f"RATCHET DOWN AVAILABLE: {unproven_gates} unproven live vs the committed "
            f"{ceiling} — a gap of {gap}, past the stated slack of {slack}. Lower "
            f"BASELINE_UNPROVEN_GATES (and UNPROVEN_CEILING_HIGH_WATER with it) to "
            f"{unproven_gates} here; that edit IS the progress record (#3329)."
        )
    return False, f"{unproven_gates} unproven vs ceiling {ceiling} — gap {gap}, within the stated slack of {slack}."


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


# ── DOWN-ONLY (#3329) ───────────────────────────────────────────────────────────────


def test_the_unproven_ceiling_is_down_only():
    """The structural half of the owner's (B) decision: BASELINE_UNPROVEN_GATES may
    fall, never rise. A raise now has to move a SECOND number whose only purpose is to
    say "someone decided to go backwards", which is the difference between a ratchet
    and a variable."""
    assert BASELINE_UNPROVEN_GATES <= UNPROVEN_CEILING_HIGH_WATER, (
        f"BASELINE_UNPROVEN_GATES was raised to {BASELINE_UNPROVEN_GATES}, above the "
        f"recorded high water {UNPROVEN_CEILING_HIGH_WATER}. Under the 2026-08-31 owner "
        "decision on #3329 (option B) this ceiling is DOWN-ONLY: a new gate arrives with a "
        "verdict (proven / attempted / not-applicable-with-a-reason) rather than widening "
        "the pile. Since #3536 the ceiling is the ledger's size, so this red means a line was "
        "ADDED to tests/gate_census_unproven_residue.py without a matching delete. If a raise "
        "is genuinely right, that is an owner call and it re-dates the decision — it is not "
        "a lane's edit."
    )
    assert len(UNPROVEN_RESIDUE) == BASELINE_UNPROVEN_GATES  # the ceiling IS the ledger (#3536)


# ── THE PER-ENTRANT RULE (#3536) — mutation proofs on synthetic keys ───────────────────

_SYNTHETIC_LEDGER = {
    "guard::scripts/check_old_3536.py": "seal",
    "ci::.github/workflows/x.yml::job / Old step": "seal",
}


def test_entrant_rule_passes_when_every_unproven_gate_is_in_the_ledger():
    ok, msg = check_unproven_entrants(list(_SYNTHETIC_LEDGER), _SYNTHETIC_LEDGER)
    assert ok, msg


def test_entrant_rule_reds_on_one_unproven_gate_not_in_the_ledger():
    """THE mutation: one synthetic gate enters unproven and is not a ledger line."""
    ok, msg = check_unproven_entrants(list(_SYNTHETIC_LEDGER) + ["structural::test_new_3536.py"], _SYNTHETIC_LEDGER)
    assert not ok
    assert "structural::test_new_3536.py" in msg and "no verdict and no ledger line" in msg


def test_entrant_rule_closes_prove_one_mint_one():
    """The hole the count rule has and this one does not (forensic RCA class 4): one old
    gate leaves the unproven pile, one new gate joins it, the COUNT is unchanged — and the
    per-entrant rule still reds on the newcomer by name."""
    old = list(_SYNTHETIC_LEDGER)
    swapped = old[1:] + ["guard::scripts/check_new_3536.py"]
    assert len(swapped) == len(old)
    ok_count, _ = check_unproven_ceiling(BASELINE_TOTAL_GATES, BASELINE_UNPROVEN_GATES)  # the count rule cannot see it
    assert ok_count
    ok, msg = check_unproven_entrants(swapped, _SYNTHETIC_LEDGER)
    assert not ok and "guard::scripts/check_new_3536.py" in msg


def test_ratchet_down_entries_names_the_stale_ledger_line():
    stale = ratchet_down_entries(["guard::scripts/check_old_3536.py"], _SYNTHETIC_LEDGER)
    assert stale == ["ci::.github/workflows/x.yml::job / Old step"]
    assert ratchet_down_entries(list(_SYNTHETIC_LEDGER), _SYNTHETIC_LEDGER) == []


def test_stable_key_survives_a_ci_step_insertion_but_not_a_relabel():
    """The positional-id problem, on the census's own row shape (gate_census.Gate)."""
    row = {"id": "ci::ci-cd.yml::lint::3", "source": ".github/workflows/ci-cd.yml", "name": "lint / Run flake8"}
    slid = dict(row, id="ci::ci-cd.yml::lint::4")  # a step inserted ahead of it
    relabelled = dict(row, name="lint / Run flake8 (strict)")
    assert stable_key(row) == stable_key(slid) == "ci::.github/workflows/ci-cd.yml::lint / Run flake8"
    assert stable_key(relabelled) != stable_key(row)
    assert stable_key({"id": "guard::scripts/x.py", "source": "scripts/x.py", "name": "scripts/x.py"}) == "guard::scripts/x.py"


def test_the_ledger_is_well_formed():
    """Every key names a census family, no key carries a positional CI index, and every
    value is a dated reason — the ledger is a record, not a set."""
    for key, note in UNPROVEN_RESIDUE.items():
        family = key.split("::", 1)[0]
        assert family in _CENSUS_FAMILIES, key
        if family == "ci":
            assert not key.rsplit("::", 1)[-1].isdigit(), f"positional CI id in the ledger: {key}"
        assert note[:4].isdigit() and note[4] == "-", f"undated ledger line: {key} -> {note!r}"


def test_ratchet_down_is_reported_when_the_gap_exceeds_the_slack():
    """The mutation, on integers: one more gate of gap than the stated slack allows and
    the census says the move is available, by name and by number."""
    available, msg = ratchet_down_available(BASELINE_UNPROVEN_GATES - RATCHET_DOWN_SLACK - 1)
    assert available
    assert "RATCHET DOWN AVAILABLE" in msg and str(BASELINE_UNPROVEN_GATES - RATCHET_DOWN_SLACK - 1) in msg


def test_ratchet_down_is_silent_inside_the_stated_slack():
    """The negative control. Exactly at the slack is NOT a finding — a ratchet that
    nags at every value is one people learn to ignore."""
    available, msg = ratchet_down_available(BASELINE_UNPROVEN_GATES - RATCHET_DOWN_SLACK)
    assert not available
    assert "within the stated slack" in msg


def test_ratchet_down_is_never_fatal_by_construction():
    """It reports, it does not fail. This is the assertion that keeps a future author
    from wiring the advisory into the red path: the ONLY fatal rule in this file is
    `check_unproven_ceiling`, and a gap below the ceiling passes it."""
    ok, _ = check_unproven_ceiling(BASELINE_TOTAL_GATES, BASELINE_UNPROVEN_GATES - RATCHET_DOWN_SLACK - 50)
    assert ok


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


def test_live_unproven_gates_are_all_in_the_ledger():
    """THE per-entrant guard (#3536). Every gate the real census reports `unproven` is a
    dated line in tests/gate_census_unproven_residue.py. This is the check that reds the
    first PR to add a guard with no proof and no ledger line — by the gate's name."""
    census = _live_census()
    keys = [stable_key(g) for g in census["gates"] if g["verdict"] == "unproven"]
    assert len(keys) == len(set(keys)), "stable_key collided on the live census — two gates share a ledger key"
    ok, msg = check_unproven_entrants(keys)
    assert ok, msg


def test_the_live_ratchet_down_verdict_is_printed_whichever_way_it_falls(capsys):
    """The visible direction of travel (#3329's Outcome). Non-fatal, so its whole value
    is being SAID every run — a silent advisory is the shape this platform keeps finding
    behind a green board, so the test asserts it printed, not that it passed."""
    census = _live_census()
    gates = census["gates"]
    unproven = sum(1 for g in gates if g["verdict"] == "unproven")
    proven = sum(1 for g in gates if g["verdict"] == "can-fail (proven)")
    available, msg = ratchet_down_available(unproven)
    stale = ratchet_down_entries(stable_key(g) for g in gates if g["verdict"] == "unproven")
    # #3536 acceptance: the proven count is the ratchet's NUMERATOR, printed every run.
    print(f"[#3329] proven {proven}/{len(gates)} · unproven {unproven} · ledger {len(UNPROVEN_RESIDUE)} · {msg}")
    if stale:
        print(
            "[#3536] ledger lines whose gate is no longer live-unproven — delete them (the ratchet counts down):\n  " + "\n  ".join(stale)
        )
    assert msg.strip()
    assert str(unproven) in msg
    assert ("RATCHET DOWN AVAILABLE" in msg) is available
    assert available is bool(stale), "the count advisory and the by-name list must agree (slack is 0)"
    assert capsys.readouterr().out.strip(), "the direction-of-travel line must reach the run's output"
