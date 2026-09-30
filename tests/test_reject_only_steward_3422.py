"""tests/test_reject_only_steward_3422.py — what survives the lease janitor's retirement (#3422, #4256).

#3422 mechanized the reject half of production-gate lease disposal as the #3021
superseded-lease janitor (`scripts/check_deploy_wedge.py --janitor --apply`, run by
`deploy-gate-janitor.yml`). ADR-158 (#4256) routed code deploys around the gate, so
there are no superseded code-deploy leases left to reject, and the janitor was
retired with the phantom-wedge classifier (#4256 box 3). What it left behind is
still load-bearing, and pinned here:

1. THE REJECTION-RECORD / GREEN-MAIN CONTRACT. `scripts/check_main_green.py`
   classifies a rejected lease as "rejected-and-superseded, not a red main" (#2590)
   from the run's own approvals record, and reads the comment's FIRST LINE back as
   the reason. Months of janitor-rejected runs sit in main's history, and a human
   can still reject the one gate left (the additive-IAM deploy) with
   `deploy/reject_deployment.sh`. The comment below is a FROZEN copy of the retired
   janitor's grammar (captured from `build_rejection_comment` at the retirement
   commit), and the approvals/job shapes are from real run 33577150903.

2. REJECT-ONLY IS STRUCTURAL (#2833; ADR-129 amendment 2026-08-30): no workflow
   invokes the approve-capable session scripts.

3. THE RETIREMENT HOLDS: the janitor workflow and the wedge classifier stay gone —
   the deploy dead-man (`scripts/check_deploy_deadman.py`) is the one watcher.
"""

import os
import sys
from pathlib import Path

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import check_main_green as cmg  # noqa: E402

OLD_SHA = "1111" + "0" * 36
NEW_SHA = "3333" + "0" * 36

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


# A FROZEN copy of the retired janitor's rejection comment for runs 101 -> 102 (#4256):
# check_deploy_wedge.build_rejection_comment(older, newer) at the retirement commit.
JANITOR_COMMENT = (
    "Auto-rejected by the deploy-gate lease janitor (#3021): run 101 (sha 111100000000) is superseded "
    "by run 102 (sha 333300000000, a strict descendant on main). Approving would deploy a stale sha; "
    "leaving it waiting holds the deploy-group slot (#2467). This run now renders as the rejected shape "
    "check_main_green.py disregards (#2590)."
)


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
    comment = JANITOR_COMMENT
    approvals = _steward_approvals(comment)
    # The REAL classifier, not a re-derivation: rejected + Deploy-sole-failure.
    assert cmg.is_deploy_rejection(REJECTED_RUN_JOBS, approvals) is True


def test_the_readback_reason_is_the_whole_comment_and_names_both_runs():
    comment = JANITOR_COMMENT
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
    comment = JANITOR_COMMENT
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
    comment = JANITOR_COMMENT
    assert cmg.is_deploy_rejection(REJECTED_RUN_JOBS, _steward_approvals(comment, state="approved")) is False
    assert cmg.is_deploy_rejection(REJECTED_RUN_JOBS, []) is False
    assert cmg.is_deploy_rejection(REJECTED_RUN_JOBS, None) is False


def test_positive_control_a_rejection_with_a_second_red_job_is_a_real_red():
    # Rejected AND something else failed: the rejection is not the whole story.
    comment = JANITOR_COMMENT
    jobs = [dict(j) for j in REJECTED_RUN_JOBS]
    jobs[2] = {"name": "test / Unit Tests", "conclusion": "failure"}
    assert cmg.is_deploy_rejection(jobs, _steward_approvals(comment)) is False


# ---------------------------------------------------------------------------
# 2. Reject-only is STRUCTURAL (#2833 / ADR-129), and 3. the retirement holds (#4256).
# ---------------------------------------------------------------------------


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


def test_the_janitor_and_the_wedge_classifier_stay_retired():
    """#4256 box 3: ADR-158 left no superseded code-deploy lease to reject, and the janitor
    failed every sweep reading the Actions API. The deploy dead-man is the one watcher."""
    assert not Path(_REPO, ".github", "workflows", "deploy-gate-janitor.yml").exists()
    assert not Path(_REPO, "scripts", "check_deploy_wedge.py").exists()
    assert Path(_REPO, "scripts", "check_deploy_deadman.py").exists()
    for wf in sorted(Path(_REPO, ".github", "workflows").glob("*.yml")):
        text = wf.read_text()
        assert "check_deploy_wedge.py" not in text, f"{wf.name} still runs the retired wedge classifier"
        assert "DEPLOY_GATE_JANITOR_TOKEN" not in text, f"{wf.name} still reads the retired janitor's token"
