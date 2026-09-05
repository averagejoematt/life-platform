"""tests/test_rejected_deployment_2590.py — a rejected gated run is not a red main (#2590).

Two standing conventions collided. #2467 says a gated run is a lease: approve or
reject, never leave waiting. The /wrap (e2) gate says main must be green. But a
REJECTED production deployment lands the run as `conclusion: failure` with
`Deploy` as the sole red job (it never executed), so obeying #2467 made
`check_main_green.py` report a red main — five times on 2026-08-11/12.

The load-bearing direction is the SECOND one: a genuinely broken `Deploy` job has
the identical job shape and must still read RED. So the split is derived from the
run's own approval record, never from "Deploy failed with no log".

Every fixture below is a real 2026-08-11/12 API capture (payloads trimmed to the
fields the gate reads):

  31526418513  32734614d  approvals=[rejected]  failing=[Deploy]                  → not a verdict
  31527749522  b177805f6  approvals=[rejected]  failing=[Deploy]                  → not a verdict
  31528727429  aad9ae137  approvals=[rejected]  failing=[Deploy]                  → not a verdict
  31556350198  c78c93369  approvals=[rejected]  failing=[test / Unit Tests, Deploy] → REAL red
  31532737505  7f228a76b  approvals=[approved]  (success)

The fourth line is why the conjunction is a conjunction and not a shortcut: two
of the five runs rejected that night ALSO had a genuine unit-test failure, and
keying on the rejection alone would have declared main green over it.

Every test here FAILS on the pre-#2590 tree (missing symbols / old semantics).
"""

import importlib.util
import os
import sys
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = datetime(2026, 8, 12, 6, 0, 0, tzinfo=timezone.utc)


def _gate():
    path = os.path.join(_REPO, "scripts", "check_main_green.py")
    spec = importlib.util.spec_from_file_location("check_main_green_2590", path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


# ── real captured payloads ───────────────────────────────────────────────────

# `GET /repos/{o}/{r}/actions/runs/31527749522/approvals` (comment verbatim).
REJECTED_APPROVALS = [
    {
        "state": "rejected",
        "comment": (
            "Superseded: b177805f6 is an ancestor of main (8f2ece415). Rejecting per #2467 — "
            "a gated run is a lease: approve or reject, never leave waiting. "
            "One final fleet run covers all of tonight's merges."
        ),
        "environments": [{"name": "production"}],
    }
]

# `…/runs/31532737505/approvals` — the approved shape.
APPROVED_APPROVALS = [{"state": "approved", "comment": "", "environments": [{"name": "production"}]}]

# `gh run view 31527749522 --json jobs` — Deploy is the SOLE red; it never ran
# (0 steps, `--log-failed` → "log not found").
REJECTED_JOBS = [
    {"name": "Reconcile derived artifacts", "conclusion": "success"},
    {"name": "lint / Lint + Syntax Check", "conclusion": "success"},
    {"name": "Deploy-critical tests", "conclusion": "success"},
    {"name": "test / Unit Tests", "conclusion": "success"},
    {"name": "Plan deployments", "conclusion": "success"},
    {"name": "Deploy", "conclusion": "failure"},
    {"name": "Post-deploy integration checks (I1/I2/I5)", "conclusion": "skipped"},
    {"name": "Visual + AI-vision QA", "conclusion": "skipped"},
    {"name": "Auto-rollback (smoke failure)", "conclusion": "skipped"},
    {"name": "Smoke test", "conclusion": "skipped"},
    {"name": "Notify failure", "conclusion": "success"},
]

# `gh run view 31556350198 --json jobs` — rejected AND a real unit-test failure.
REJECTED_PLUS_REAL_RED_JOBS = [dict(j) for j in REJECTED_JOBS]
for _j in REJECTED_PLUS_REAL_RED_JOBS:
    if _j["name"] == "test / Unit Tests":
        _j["conclusion"] = "failure"


def _run(run_id, sha, conclusion="failure", status="completed", age_h=1.0):
    created = datetime.fromtimestamp(NOW.timestamp() - age_h * 3600.0, tz=timezone.utc)
    return {
        "status": status,
        "conclusion": conclusion,
        "headSha": sha,
        "databaseId": run_id,
        "createdAt": created.isoformat().replace("+00:00", "Z"),
    }


def _probe_from(mapping):
    """A fake `probe(run) -> (jobs, approvals)` over {run_id: (jobs, approvals)}."""

    def probe(run):
        return mapping.get(run.get("databaseId"), (None, None))

    return probe


# ── 1. the predicate, both directions ────────────────────────────────────────
def test_rejected_deployment_with_deploy_sole_red_is_a_rejection():
    g = _gate()
    assert g.is_deploy_rejection(REJECTED_JOBS, REJECTED_APPROVALS) is True


def test_approved_deployment_with_the_same_job_shape_is_NOT_a_rejection():
    """LOAD-BEARING: a genuinely broken Deploy job is byte-identical in shape.

    Only the approval record separates them, so the predicate must key on that.
    """
    g = _gate()
    assert g.is_deploy_rejection(REJECTED_JOBS, APPROVED_APPROVALS) is False


def test_no_approval_record_at_all_is_NOT_a_rejection():
    g = _gate()
    assert g.is_deploy_rejection(REJECTED_JOBS, []) is False
    assert g.is_deploy_rejection(REJECTED_JOBS, None) is False


def test_rejected_but_something_else_also_failed_is_a_REAL_red():
    """Run 31556350198 live: rejected AND Unit Tests red. The rejection is not
    the whole story, so it stays a verdict."""
    g = _gate()
    assert g.is_deploy_rejection(REJECTED_PLUS_REAL_RED_JOBS, REJECTED_APPROVALS) is False


def test_rejection_reason_is_the_operators_own_first_line():
    g = _gate()
    assert g.rejection_reason(REJECTED_APPROVALS).startswith("Superseded: b177805f6 is an ancestor of main")
    assert g.rejection_reason(APPROVED_APPROVALS) == "no reason recorded"


# ── 2. the walk ──────────────────────────────────────────────────────────────
def test_scan_walks_past_a_stack_of_rejections_to_the_real_verdict():
    g = _gate()
    runs = [
        _run(31528727429, "aad9ae137"),
        _run(31527749522, "b177805f6"),
        _run(31526418513, "32734614d"),
        _run(31457215150, "9388c1768", conclusion="success", age_h=26.0),
    ]
    probe = _probe_from({r: (REJECTED_JOBS, REJECTED_APPROVALS) for r in (31528727429, 31527749522, 31526418513)})
    rejected, jobs = g.scan_rejections(runs, probe)
    assert [e["run"]["databaseId"] for e in rejected] == [31528727429, 31527749522, 31526418513]
    assert jobs is None


def test_scan_stops_at_the_first_real_red_and_returns_its_jobs():
    g = _gate()
    runs = [_run(31528727429, "aad9ae137"), _run(31556350198, "c78c93369")]
    probe = _probe_from(
        {
            31528727429: (REJECTED_JOBS, REJECTED_APPROVALS),
            31556350198: (REJECTED_PLUS_REAL_RED_JOBS, REJECTED_APPROVALS),
        }
    )
    rejected, jobs = g.scan_rejections(runs, probe)
    assert [e["run"]["databaseId"] for e in rejected] == [31528727429]
    assert jobs == REJECTED_PLUS_REAL_RED_JOBS


def test_a_failed_probe_degrades_to_ordinary_red_never_to_a_false_green():
    g = _gate()
    runs = [_run(31527749522, "b177805f6")]
    rejected, jobs = g.scan_rejections(runs, _probe_from({}))
    assert rejected == [] and jobs is None


def test_probe_limit_bounds_the_walk():
    g = _gate()
    runs = [_run(9000 + i, f"sha{i:05d}") for i in range(12)]
    probe = _probe_from({9000 + i: (REJECTED_JOBS, REJECTED_APPROVALS) for i in range(12)})
    rejected, _ = g.scan_rejections(runs, probe, max_probes=3)
    assert len(rejected) == 3


# ── 3. end-to-end verdict + reporting ────────────────────────────────────────
def test_stack_of_rejections_over_a_success_reads_GREEN_and_is_reported():
    g = _gate()
    runs = [
        _run(31528727429, "aad9ae137"),
        _run(31527749522, "b177805f6"),
        _run(31526418513, "32734614d"),
        _run(31457215150, "9388c1768", conclusion="success", age_h=26.0),
    ]
    probe = _probe_from({r: (REJECTED_JOBS, REJECTED_APPROVALS) for r in (31528727429, 31527749522, 31526418513)})
    rejected, jobs = g.scan_rejections(runs, probe)
    state = g.classify_pipeline(runs, latest_failure_jobs=jobs, now=NOW, rejected=rejected)
    assert state["kind"] == g.GREEN
    assert state["sha"] == "9388c1768"
    code, msg = g.render(state, now=NOW)
    assert code == 0 and "GREEN" in msg
    # Skipped, but NOT swallowed: sha + reason, so the operator sees the lease
    # was actioned rather than the gate being blind.
    for sha in ("aad9ae13", "b177805f", "32734614"):
        assert sha in msg
    assert "REJECTED" in msg and "#2467" in msg
    assert "Superseded" in msg


def test_a_genuinely_failed_deploy_job_still_reads_RED():
    """The other direction. Same job shape, approved instead of rejected."""
    g = _gate()
    runs = [_run(31532737505, "7f228a76"), _run(31457215150, "9388c1768", conclusion="success", age_h=26.0)]
    probe = _probe_from({31532737505: (REJECTED_JOBS, APPROVED_APPROVALS)})
    rejected, jobs = g.scan_rejections(runs, probe)
    assert rejected == []
    state = g.classify_pipeline(runs, latest_failure_jobs=jobs, now=NOW, rejected=rejected)
    assert state["kind"] == g.RED
    assert state["sha"] == "7f228a76"
    code, msg = g.render(state, now=NOW)
    assert code == 1 and "FAILURE" in msg
    assert "REJECTED" not in msg


def test_rejections_are_reported_alongside_a_real_red_too():
    """A rejection stack sitting above a real red must not hide either fact."""
    g = _gate()
    runs = [_run(31528727429, "aad9ae137"), _run(31556350198, "c78c93369")]
    probe = _probe_from(
        {
            31528727429: (REJECTED_JOBS, REJECTED_APPROVALS),
            31556350198: (REJECTED_PLUS_REAL_RED_JOBS, REJECTED_APPROVALS),
        }
    )
    rejected, jobs = g.scan_rejections(runs, probe)
    state = g.classify_pipeline(runs, latest_failure_jobs=jobs, now=NOW, rejected=rejected)
    code, msg = g.render(state, now=NOW)
    assert code == 1
    assert "main is FAILURE at c78c9336" in msg
    assert "aad9ae13" in msg and "REJECTED" in msg


# ── 4. back-compat with #1327/#1901 ──────────────────────────────────────────
def test_latest_completed_run_unchanged_without_rejected_ids():
    g = _gate()
    runs = [_run(1, "aaa111", conclusion="cancelled"), _run(2, "bbb222", conclusion="success")]
    assert g.latest_completed_run(runs)["databaseId"] == 2
    assert g.latest_main_conclusion(runs) == ("success", "bbb222")


def test_classify_pipeline_without_the_rejected_kwarg_is_the_old_behaviour():
    g = _gate()
    runs = [_run(31527749522, "b177805f6")]
    state = g.classify_pipeline(runs, latest_failure_jobs=REJECTED_JOBS, now=NOW)
    assert state["kind"] == g.RED


# ── 5. #3530: a REJECTED run stacked on a CANCELLED-carrying-a-failure one ───
#
# The #3530 acceptance box, in this file because it is the interaction that
# matters: the two skip rules compose, and only one of the two runs below is a
# non-verdict. Payload shape captured from run 33843742114 on 2026-09-04 —
# CANCELLED rollup, `test / Unit Tests` = failure, `Deploy` = cancelled with ZERO
# steps (evicted from the `ci-cd-deploy-<ref>` group by the next run's Deploy).
# The full live payload is pinned at
# tests/fixtures/cancelled_runs/run_33843742114_cancelled_carries_failure.json
# and exercised end-to-end by tests/test_cancelled_not_superseded_3530.py.
CANCELLED_WITH_UNIT_TEST_RED_JOBS = [
    {"name": "Reconcile derived artifacts", "conclusion": "success"},
    {"name": "lint / Lint + Syntax Check", "conclusion": "success"},
    {"name": "Deploy-critical tests", "conclusion": "success"},
    {"name": "test / Unit Tests", "conclusion": "failure"},
    {"name": "Plan deployments", "conclusion": "success"},
    {"name": "Deploy", "conclusion": "cancelled", "steps": []},
    {"name": "Visual + AI-vision QA", "conclusion": "skipped"},
    {"name": "Smoke test", "conclusion": "skipped"},
    {"name": "Post-deploy integration checks (I1/I2/I5)", "conclusion": "skipped"},
    {"name": "Auto-rollback (smoke failure)", "conclusion": "skipped"},
    {"name": "Notify failure", "conclusion": "success"},
]


def test_a_cancelled_run_carrying_a_unit_test_red_is_the_verdict_not_a_skip():
    """The rejected run above it IS a non-verdict; the cancelled one below it is
    NOT. Pre-#3530 both were skipped and the gate reported the older green."""
    g = _gate()
    runs = [
        _run(31527749522, "b177805f6"),  # rejected production deployment — not a verdict
        _run(33843742114, "b248a70c1", conclusion="cancelled"),  # cancelled, carries a real red
        _run(2, "0ld0ld0ld", conclusion="success"),
    ]
    cancelled_verdicts, notes = g.scan_cancelled(
        runs, lambda r: CANCELLED_WITH_UNIT_TEST_RED_JOBS if r["databaseId"] == 33843742114 else None
    )
    rejected, jobs = g.scan_rejections(
        runs, _probe_from({31527749522: (REJECTED_JOBS, REJECTED_APPROVALS)}), cancelled_verdicts=cancelled_verdicts
    )
    assert [e["run"]["databaseId"] for e in rejected] == [31527749522]

    verdict = g.latest_completed_run(runs, rejected_ids={31527749522}, cancelled_verdicts=cancelled_verdicts)
    assert verdict["databaseId"] == 33843742114, "the cancelled run carrying a red IS the verdict"

    state = g.classify_pipeline(
        runs, latest_failure_jobs=jobs, now=NOW, rejected=rejected, cancelled_verdicts=cancelled_verdicts, cancelled_notes=notes
    )
    assert state["kind"] == g.RED
    code, msg = g.render(state, now=NOW)
    assert code == 1
    assert "main is CANCELLED at b248a70c" in msg
    assert "test / Unit Tests" in msg
    assert "b177805f6"[:8] in msg and "REJECTED" in msg
