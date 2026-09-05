"""tests/test_reject_only_steward_3422.py — the mechanized reject-only lease steward's
two load-bearing contracts (#3422).

#3422 asked for the reject half of production-gate lease disposal to be mechanized.
The mechanized artifact ALREADY EXISTS — the #3021 superseded-lease janitor
(`scripts/check_deploy_wedge.py --janitor --apply`, run every 15 minutes by
`deploy-gate-janitor.yml` under `DEPLOY_GATE_JANITOR_TOKEN`; it ran as a step of
`deploy-wedge-watch.yml` until #3422's event hook moved it, 2026-09-04) — so this file does not
add a second steward; it pins the two contracts #3422's acceptance names, which
#3021's own test file (`tests/test_deploy_gate_janitor_3021.py`) left unpinned:

1. THE REJECTION-COMMENT / GREEN-MAIN CONTRACT. `scripts/check_main_green.py`
   classifies a rejected lease as "rejected-and-superseded, not a red main" (#2590)
   from the run's own approvals record — `is_deploy_rejection()` (state "rejected"
   present, "approved" absent, Deploy the sole failing job) — and reads the
   rejection comment's FIRST LINE back verbatim as the operator-facing reason
   (`rejection_reason()`). A steward whose comment that classifier cannot read
   turns every mechanical rejection into a false red main. The fixtures here are
   the wire: the approvals record is shaped from a REAL captured rejection
   (run 33577150903, 2026-09-02) and the job list is that run's real job set.

2. REJECT-ONLY IS STRUCTURAL, NOT A FLAG (#2833; ADR-129 amendment 2026-08-30:
   approval is a human act, and there is no re-promotion path without a new ADR).
   The negative controls below assert the steward module exposes no approve
   capability, that its one pending_deployments writer posts state "rejected" and
   nothing else, and that no workflow invokes the approve-capable session scripts
   (`deploy/approve_deployment.sh`, `deploy/watch_deploy_gate.sh`).

Plus the Session R rule recorded on #3422 — THE RUN-BEARING-SHA RULE: a
`[skip-reconcile]` tip commit mints NO CI/CD run, so "reject proper ancestors of
origin/main" over-rejects (it would reject the newest run-bearing lease whenever the
tip itself carries no run). The janitor's predicate never consults origin/main at
all: its candidate set is RUNS (waiting leases + completed successful deploys), so a
run-less tip can never supersede anything — pinned explicitly here.

Only pure logic is unit-tested; no test ever invokes `gh` (the same convention as
tests/test_deploy_gate_janitor_3021.py).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import check_deploy_wedge as cdw  # noqa: E402
import check_main_green as cmg  # noqa: E402

OLD_SHA = "1111" + "0" * 36
NEW_SHA = "3333" + "0" * 36
# The [skip-reconcile] tip: a real sha on main that MINTS NO CI/CD RUN.
TIP_SHA = "9999" + "0" * 36


def _run(rid, sha, created, branch="main", status="waiting"):
    return {"id": rid, "head_sha": sha, "head_branch": branch, "status": status, "created_at": created}


def _descendant_map(pairs):
    def is_descendant(older, newer):
        return pairs.get((older, newer), False)

    return is_descendant


# The REAL job shape of a janitor/steward-rejected run — captured from run
# 33577150903 (rejected 2026-09-02): Deploy is the sole failure, downstream jobs
# skipped, "Notify failure" success. Fixture must be the wire.
REJECTED_RUN_JOBS = [
    {"name": "Reconcile derived artifacts", "conclusion": "success"},
    {"name": "lint / Lint + Syntax Check", "conclusion": "success"},
    {"name": "test / Unit Tests", "conclusion": "success"},
    {"name": "Deploy-critical tests", "conclusion": "success"},
    {"name": "Plan deployments", "conclusion": "success"},
    {"name": "Deploy", "conclusion": "failure"},
    {"name": "Visual + AI-vision QA", "conclusion": "skipped"},
    {"name": "Smoke test", "conclusion": "skipped"},
    {"name": "Post-deploy integration checks (I1/I2/I5)", "conclusion": "skipped"},
    {"name": "Auto-rollback (smoke failure)", "conclusion": "skipped"},
    {"name": "Notify failure", "conclusion": "success"},
]


def _steward_approvals(comment, state="rejected"):
    # The wire shape of GET /repos/{o}/{r}/actions/runs/{id}/approvals, trimmed to
    # the fields check_main_green reads — captured from run 33577150903.
    return [
        {
            "user": {"login": "averagejoematt", "id": 174924761, "type": "User"},
            "state": state,
            "comment": comment,
            "environments": [{"id": 12797761864, "name": "production"}],
        }
    ]


# ---------------------------------------------------------------------------
# 1. The rejection-comment grammar is a CONTRACT with check_main_green.py.
# ---------------------------------------------------------------------------


def test_a_janitor_rejection_record_reads_as_not_a_red_main():
    older = _run(101, OLD_SHA, "2026-09-02T01:00:00Z")
    newer = _run(102, NEW_SHA, "2026-09-02T02:00:00Z")
    comment = cdw.build_rejection_comment(older, newer)
    approvals = _steward_approvals(comment)
    # The REAL classifier, not a re-derivation: rejected + Deploy-sole-failure.
    assert cmg.is_deploy_rejection(REJECTED_RUN_JOBS, approvals) is True


def test_the_readback_reason_is_the_whole_comment_and_names_both_runs():
    older = _run(101, OLD_SHA, "2026-09-02T01:00:00Z")
    newer = _run(102, NEW_SHA, "2026-09-02T02:00:00Z")
    comment = cdw.build_rejection_comment(older, newer)
    # rejection_reason() reads back the FIRST LINE verbatim — so the grammar is
    # "one substantive line": a multi-line comment would silently truncate the
    # operator-facing audit trail.
    assert "\n" not in comment
    reason = cmg.rejection_reason(_steward_approvals(comment))
    assert reason == comment
    # Substantive and stable: the superseded and superseding runs, both shas, and
    # the two contracts it cites.
    assert "101" in reason and "102" in reason
    assert OLD_SHA[:12] in reason and NEW_SHA[:12] in reason
    assert "#3021" in reason and "#2590" in reason


def test_the_full_pipeline_verdict_disregards_a_janitor_rejected_run():
    # The #2590 session shape: the newest completed run is the rejected failure,
    # the run beneath it succeeded. The gate must report GREEN with the rejection
    # NAMED, never a red main.
    older = _run(101, OLD_SHA, "2026-09-02T01:00:00Z")
    newer = _run(102, NEW_SHA, "2026-09-02T02:00:00Z")
    comment = cdw.build_rejection_comment(older, newer)
    runs = [
        {"status": "completed", "conclusion": "failure", "headSha": OLD_SHA, "databaseId": 101, "createdAt": "2026-09-02T01:00:00Z"},
        {
            "status": "completed",
            "conclusion": "success",
            "headSha": "aaaa" + "0" * 36,
            "databaseId": 90,
            "createdAt": "2026-09-01T20:00:00Z",
        },
    ]

    def probe(run):
        assert run.get("databaseId") == 101  # only the failure is probed
        return REJECTED_RUN_JOBS, _steward_approvals(comment)

    rejected, verdict_jobs = cmg.scan_rejections(runs, probe)
    assert [e["run"]["databaseId"] for e in rejected] == [101]
    state = cmg.classify_pipeline(runs, latest_failure_jobs=verdict_jobs, rejected=rejected)
    assert state["kind"] == cmg.GREEN
    code, message = cmg.render(state)
    assert code == 0
    # The lease was actioned, not swallowed: the operator sees the reason verbatim.
    assert "REJECTED" in message
    assert comment in message


def test_positive_control_an_approved_then_broken_deploy_still_reads_red():
    # The same job shape WITHOUT a rejection record is a genuinely broken Deploy
    # and must still read red — the conjunction's first clause is load-bearing.
    older = _run(101, OLD_SHA, "2026-09-02T01:00:00Z")
    newer = _run(102, NEW_SHA, "2026-09-02T02:00:00Z")
    comment = cdw.build_rejection_comment(older, newer)
    assert cmg.is_deploy_rejection(REJECTED_RUN_JOBS, _steward_approvals(comment, state="approved")) is False
    assert cmg.is_deploy_rejection(REJECTED_RUN_JOBS, []) is False
    assert cmg.is_deploy_rejection(REJECTED_RUN_JOBS, None) is False


def test_positive_control_a_rejection_with_a_second_red_job_is_a_real_red():
    # Rejected AND something else failed: the rejection is not the whole story.
    older = _run(101, OLD_SHA, "2026-09-02T01:00:00Z")
    newer = _run(102, NEW_SHA, "2026-09-02T02:00:00Z")
    comment = cdw.build_rejection_comment(older, newer)
    jobs = [dict(j) for j in REJECTED_RUN_JOBS]
    jobs[2] = {"name": "test / Unit Tests", "conclusion": "failure"}
    assert cmg.is_deploy_rejection(jobs, _steward_approvals(comment)) is False


# ---------------------------------------------------------------------------
# 2. The run-bearing-sha rule (Session R, recorded on #3422).
# ---------------------------------------------------------------------------


def test_a_runless_tip_sha_cannot_supersede_anything():
    # origin/main's tip is a [skip-reconcile] commit: it strictly descends from the
    # one waiting lease's sha but MINTS NO RUN. "Reject proper ancestors of the
    # tip" would kill this lease; the janitor's candidate set is runs only, so the
    # newest RUN-BEARING lease survives.
    lease = _run(101, OLD_SHA, "2026-09-02T01:00:00Z")
    rel = {(OLD_SHA, TIP_SHA): True}
    assert cdw.find_superseded_leases([lease], [], _descendant_map(rel)) == []


def test_the_newest_run_bearing_lease_survives_a_runless_tip():
    # Two leases; the tip (run-less) descends from both. Only the older lease is
    # rejected, and only on the proof of the newer RUN-BEARING lease — the tip
    # never enters the predicate.
    older = _run(101, OLD_SHA, "2026-09-02T01:00:00Z")
    newest = _run(102, NEW_SHA, "2026-09-02T02:00:00Z")
    rel = {(OLD_SHA, NEW_SHA): True, (OLD_SHA, TIP_SHA): True, (NEW_SHA, TIP_SHA): True}
    pairs = cdw.find_superseded_leases([older, newest], [], _descendant_map(rel))
    assert [(p["run"]["id"], p["superseded_by"]["id"]) for p in pairs] == [(101, 102)]


# ---------------------------------------------------------------------------
# 3. Reject-only is STRUCTURAL (#2833 / ADR-129) — the negative controls.
# ---------------------------------------------------------------------------


def test_the_steward_module_exposes_no_approve_callable():
    # The module carries approval-related CONSTANTS (AWAITING_APPROVAL,
    # STRANDED_APPROVAL — detection vocabulary), but no callable that could
    # approve: reject-only is the absence of the code path, not a flag.
    approve_callables = [n for n in dir(cdw) if "approv" in n.lower() and callable(getattr(cdw, n))]
    assert approve_callables == []


def test_reject_lease_posts_exactly_one_write_and_its_state_is_rejected(monkeypatch):
    posted = []
    monkeypatch.setattr(cdw, "_gh_api", lambda path: [{"environment": {"id": 7}}, {"environment": {"id": 9}}])

    def fake_subprocess_run(cmd, **kwargs):
        posted.append((cmd, json.loads(kwargs["input"])))
        # The wire shape reject_lease reads back (#3422): a CompletedProcess, exit 0.
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(cdw.subprocess, "run", fake_subprocess_run)
    cdw.reject_lease(123, "steward comment")
    assert len(posted) == 1
    cmd, body = posted[0]
    assert any("pending_deployments" in part for part in cmd)
    assert body["state"] == "rejected"
    assert body["environment_ids"] == [7, 9]
    assert body["comment"] == "steward comment"


def test_the_module_source_never_writes_an_approved_state():
    src = Path(_REPO, "scripts", "check_deploy_wedge.py").read_text()
    # No wire write of state "approved", under any quoting/spacing.
    assert re.search(r"""state["']?\s*[:=]\s*["']approved""", src) is None


def test_no_workflow_invokes_the_approve_capable_scripts():
    # The set, not the instance: NO workflow may run deploy/approve_deployment.sh
    # or deploy/watch_deploy_gate.sh (the approve-young/reject-by-age session
    # watcher #3422's design explicitly declines to mechanize). Approval stays a
    # human act made from a human session.
    workflows = sorted(Path(_REPO, ".github", "workflows").glob("*.yml"))
    assert workflows, "workflow directory unreadable — this control would be vacuous"
    for wf in workflows:
        text = wf.read_text()
        assert "approve_deployment.sh" not in text, f"{wf.name} invokes the approve half"
        assert "watch_deploy_gate.sh" not in text, f"{wf.name} runs the approve-capable session watcher"


def test_the_janitor_workflow_step_is_the_reject_sweep_and_grants_no_approval():
    text = Path(_REPO, ".github", "workflows", "deploy-gate-janitor.yml").read_text()
    assert "--janitor --apply" in text  # the mechanized reject-only sweep
    assert "DEPLOY_GATE_JANITOR_TOKEN" in text  # the required-reviewer credential
    assert re.search(r"""state["']?\s*[:=]\s*["']approved""", text) is None
