"""tests/test_deploy_gate_janitor_3021.py — the superseded-lease janitor's decision core.

#2052/#2467/#2149 built DETECTION of wedged/stranded production-gate leases; disposal of
a superseded `waiting` lease stayed manual every documented time (>=5 — #2901, #2937,
the 2026-08-20 2.6h strand, the 2026-08-22 pair, the #2467 zombies). #3021 adds the
disposal. This file mutation-proofs the PURE decision layer in
`scripts/check_deploy_wedge.py`:

  - `gate_waiting_leases`   — which runs are leases the janitor may even consider
  - `find_superseded_leases`— the whole reject/keep decision (the predicate the issue's
                              acceptance names: newest-waiting kept, older-waiting
                              rejected on strict-descendant proof, non-main ignored,
                              unknown ancestry never rejects)
  - `build_rejection_comment` — the audit trail (superseded id + sha AND superseding id)

I/O (`_compare_is_descendant`, `_deployed_superseders`, `reject_lease`, the workflow
step) is prose-verified per the same convention as tests/test_deploy_wedge_alert_2149.py
— only pure logic is unit-tested here; no test ever invokes `gh`.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import check_deploy_wedge as cdw  # noqa: E402


def _run(rid, sha, created, branch="main", status="waiting"):
    return {"id": rid, "head_sha": sha, "head_branch": branch, "status": status, "created_at": created}


def _descendant_map(pairs):
    """is_descendant stub from an explicit relation: {(older_sha, newer_sha): verdict}.
    Any pair not in the map is False — a mutation that queries a pair the test did not
    sanction shows up as 'not rejected', never as a spurious rejection."""

    def is_descendant(older, newer):
        return pairs.get((older, newer), False)

    return is_descendant


# --------------------------------------------------------------------------
# gate_waiting_leases — the admissible-lease filter.
# --------------------------------------------------------------------------


def test_gate_waiting_leases_admits_only_main_waiting_gateparked_with_pending():
    runs = [
        _run(1, "a" * 40, "2026-08-22T01:00:00Z"),  # admissible
        _run(2, "b" * 40, "2026-08-22T02:00:00Z", branch="issue-99-x"),  # non-main
        _run(3, "c" * 40, "2026-08-22T03:00:00Z", status="completed"),  # completed
        _run(4, "d" * 40, "2026-08-22T04:00:00Z"),  # Deploy in_progress, not waiting
        _run(5, "e" * 40, "2026-08-22T05:00:00Z"),  # empty pending_deployments
        _run(6, "f" * 40, "2026-08-22T06:00:00Z"),  # no Deploy job yet
    ]
    jobs = {
        "1": [{"name": "Deploy", "status": "waiting"}],
        "2": [{"name": "Deploy", "status": "waiting"}],
        "3": [{"name": "Deploy", "status": "completed"}],
        "4": [{"name": "Deploy", "status": "in_progress"}],
        "5": [{"name": "Deploy", "status": "waiting"}],
        "6": [{"name": "Lint", "status": "in_progress"}],
    }
    pending = {"1": [{"environment": {"id": 7}}], "2": [{"environment": {"id": 7}}], "5": []}
    out = cdw.gate_waiting_leases(runs, jobs, pending)
    assert [r["id"] for r in out] == [1]


def test_gate_waiting_leases_matches_deploy_job_exactly_not_by_prefix():
    # "Deploy-critical tests" waiting must not read as a gate-parked lease.
    runs = [_run(1, "a" * 40, "2026-08-22T01:00:00Z")]
    jobs = {"1": [{"name": "Deploy-critical tests", "status": "waiting"}]}
    pending = {"1": [{"environment": {"id": 7}}]}
    assert cdw.gate_waiting_leases(runs, jobs, pending) == []


# --------------------------------------------------------------------------
# find_superseded_leases — the reject/keep decision.
# --------------------------------------------------------------------------

OLD_SHA = "1111" + "0" * 36
MID_SHA = "2222" + "0" * 36
NEW_SHA = "3333" + "0" * 36


def test_older_waiting_rejected_newest_waiting_kept():
    older = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    newest = _run(102, NEW_SHA, "2026-08-22T02:00:00Z")
    pairs = cdw.find_superseded_leases([older, newest], [], _descendant_map({(OLD_SHA, NEW_SHA): True}))
    assert [(p["run"]["id"], p["superseded_by"]["id"]) for p in pairs] == [(101, 102)]


def test_three_waiting_only_the_newest_survives():
    a = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    b = _run(102, MID_SHA, "2026-08-22T02:00:00Z")
    c = _run(103, NEW_SHA, "2026-08-22T03:00:00Z")
    rel = {(OLD_SHA, NEW_SHA): True, (OLD_SHA, MID_SHA): True, (MID_SHA, NEW_SHA): True}
    pairs = cdw.find_superseded_leases([a, b, c], [], _descendant_map(rel))
    rejected = {p["run"]["id"]: p["superseded_by"]["id"] for p in pairs}
    assert set(rejected) == {101, 102}
    assert 103 not in rejected
    # newest-first candidate order: both are superseded by the newest lease, 103
    assert rejected == {101: 103, 102: 103}


def test_non_descendant_pair_is_not_rejected():
    older = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    newest = _run(102, NEW_SHA, "2026-08-22T02:00:00Z")
    pairs = cdw.find_superseded_leases([older, newest], [], _descendant_map({(OLD_SHA, NEW_SHA): False}))
    assert pairs == []


def test_unknown_ancestry_never_rejects():
    older = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    newest = _run(102, NEW_SHA, "2026-08-22T02:00:00Z")
    pairs = cdw.find_superseded_leases([older, newest], [], _descendant_map({(OLD_SHA, NEW_SHA): None}))
    assert pairs == []


def test_non_main_runs_ignored_on_both_sides():
    # A non-main "older" is never a rejection target; a non-main "newer" never proves
    # supersession — even with a true descendant relation on both.
    older_branch = _run(101, OLD_SHA, "2026-08-22T01:00:00Z", branch="issue-7-x")
    older_main = _run(102, MID_SHA, "2026-08-22T02:00:00Z")
    newer_branch = _run(103, NEW_SHA, "2026-08-22T03:00:00Z", branch="issue-8-y")
    rel = {(OLD_SHA, MID_SHA): True, (OLD_SHA, NEW_SHA): True, (MID_SHA, NEW_SHA): True}
    pairs = cdw.find_superseded_leases([older_branch, older_main, newer_branch], [], _descendant_map(rel))
    assert pairs == []  # only ONE main waiting lease remains — it is the newest, kept


def test_same_sha_redispatch_is_not_superseded():
    older = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    newest = _run(102, OLD_SHA, "2026-08-22T02:00:00Z")  # same commit re-dispatched
    pairs = cdw.find_superseded_leases([older, newest], [], _descendant_map({(OLD_SHA, OLD_SHA): True}))
    assert pairs == []


def test_completed_deployed_run_supersedes_an_older_waiting_lease():
    a = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    b = _run(102, MID_SHA, "2026-08-22T02:00:00Z")
    deployed = _run(900, NEW_SHA, "2026-08-22T03:00:00Z", status="completed")
    # a's supersession is proven ONLY via the completed deploy, not via b
    rel = {(OLD_SHA, NEW_SHA): True, (OLD_SHA, MID_SHA): False, (MID_SHA, NEW_SHA): False}
    pairs = cdw.find_superseded_leases([a, b], [deployed], _descendant_map(rel))
    assert [(p["run"]["id"], p["superseded_by"]["id"]) for p in pairs] == [(101, 900)]


def test_newest_waiting_lease_survives_even_a_newer_completed_deploy():
    # Absolute rule: the janitor never touches the newest waiting lease — a human
    # decides that one, even when a completed run has already deployed past it.
    only = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    deployed = _run(900, NEW_SHA, "2026-08-22T03:00:00Z", status="completed")
    pairs = cdw.find_superseded_leases([only], [deployed], _descendant_map({(OLD_SHA, NEW_SHA): True}))
    assert pairs == []


def test_superseder_must_be_strictly_newer_by_created_at():
    older = _run(101, OLD_SHA, "2026-08-22T02:00:00Z")
    newest = _run(102, NEW_SHA, "2026-08-22T03:00:00Z")
    stale_deploy = _run(900, MID_SHA, "2026-08-22T01:00:00Z", status="completed")  # OLDER than the lease
    rel = {(OLD_SHA, MID_SHA): True, (OLD_SHA, NEW_SHA): False}
    pairs = cdw.find_superseded_leases([older, newest], [stale_deploy], _descendant_map(rel))
    assert pairs == []


def test_ancestry_is_queried_older_to_newer():
    # Argument-order mutation guard: the predicate must ask "is NEWER a descendant of
    # OLDER", i.e. is_descendant(older_sha, newer_sha).
    older = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    newest = _run(102, NEW_SHA, "2026-08-22T02:00:00Z")
    calls = []

    def spy(o, n):
        calls.append((o, n))
        return True

    cdw.find_superseded_leases([older, newest], [], spy)
    assert calls == [(OLD_SHA, NEW_SHA)]


def test_missing_sha_never_rejects():
    older = _run(101, "", "2026-08-22T01:00:00Z")
    newest = _run(102, NEW_SHA, "2026-08-22T02:00:00Z")
    pairs = cdw.find_superseded_leases([older, newest], [], _descendant_map({("", NEW_SHA): True}))
    assert pairs == []


# --------------------------------------------------------------------------
# build_rejection_comment — the audit trail.
# --------------------------------------------------------------------------


def test_rejection_comment_carries_both_run_ids_and_shas():
    older = _run(101, OLD_SHA, "2026-08-22T01:00:00Z")
    newer = _run(102, NEW_SHA, "2026-08-22T02:00:00Z")
    comment = cdw.build_rejection_comment(older, newer)
    assert "101" in comment
    assert "102" in comment
    assert OLD_SHA[:12] in comment
    assert NEW_SHA[:12] in comment
    assert "#3021" in comment
    assert "#2590" in comment  # names the shape check_main_green.py disregards
