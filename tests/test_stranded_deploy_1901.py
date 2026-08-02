"""tests/test_stranded_deploy_1901.py — stranded-deploy state detection (#1901).

Replays the incident: run 30324990970 sat at the `production` approval gate
~15h (2026-07-28); every later run queued behind it with 0 jobs, main kept
reporting green, and the state was mis-diagnosed as the phantom-concurrency
class (reference_push_ci_silent_death) — which has the opposite fix and cost
a wrongly-cancelled run. Separately, the R8-ST6 IAM-review gate reds ONLY the
Plan job (Deploy skipped, tests green) and every later deploy strands until a
CDK deploy from main clears it — check_main_green.py read both states as
ordinary red/green.

Fixtures mirror real `gh run list` / `gh run view --json jobs` shapes
(the R8-ST6 job list is copied from live run 30757772757, 2026-08-02).
All offline — no gh, no AWS.
"""

import importlib.util
import os
from datetime import datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NOW = datetime(2026, 8, 2, 20, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _gate():
    spec = importlib.util.spec_from_file_location("check_main_green_1901", os.path.join(_REPO, "scripts", "check_main_green.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(status, conclusion, sha, run_id, hours_ago):
    return {
        "status": status,
        "conclusion": conclusion,
        "headSha": sha,
        "databaseId": run_id,
        "createdAt": _iso(NOW - timedelta(hours=hours_ago)),
    }


# The live R8-ST6 shape (run 30757772757): ONLY Plan red, Deploy skipped.
R8ST6_JOBS = [
    {"name": "Reconcile derived artifacts", "status": "completed", "conclusion": "success"},
    {"name": "lint / Lint + Syntax Check", "status": "completed", "conclusion": "success"},
    {"name": "Deploy-critical tests", "status": "completed", "conclusion": "success"},
    {"name": "test / Unit Tests", "status": "completed", "conclusion": "success"},
    {"name": "Plan deployments", "status": "completed", "conclusion": "failure"},
    {"name": "Deploy", "status": "completed", "conclusion": "skipped"},
    {"name": "Visual + AI-vision QA", "status": "completed", "conclusion": "skipped"},
    {"name": "Post-deploy integration checks (I1/I2/I5)", "status": "completed", "conclusion": "skipped"},
    {"name": "Smoke test", "status": "completed", "conclusion": "skipped"},
    {"name": "Auto-rollback (smoke failure)", "status": "completed", "conclusion": "skipped"},
    {"name": "Notify failure", "status": "completed", "conclusion": "success"},
]

# Ordinary red: Unit Tests failed, Plan fine, Deploy ran — nothing stranded.
ORDINARY_RED_JOBS = [dict(j) for j in R8ST6_JOBS]
for _j in ORDINARY_RED_JOBS:
    if _j["name"] == "test / Unit Tests":
        _j["conclusion"] = "failure"
    elif _j["name"] in ("Plan deployments", "Deploy"):
        _j["conclusion"] = "success"

# The live 2026-08-02 dual shape (run 30761026008): Unit Tests red AND
# Plan red + Deploy skipped — an ordinary red whose deploy path is ALSO
# stranded; a code fix alone will not deploy until the CDK deploy clears R8-ST6.
DUAL_RED_STRANDED_JOBS = [dict(j) for j in R8ST6_JOBS]
for _j in DUAL_RED_STRANDED_JOBS:
    if _j["name"] == "test / Unit Tests":
        _j["conclusion"] = "failure"


# ── classification: the four fixture classes ─────────────────────────────────
def test_ordinary_green():
    g = _gate()
    runs = [_run("completed", "success", "aaa111aa", 1, 1.0)]
    state = g.classify_pipeline(runs, now=NOW)
    assert state["kind"] == g.GREEN
    code, msg = g.render(state, now=NOW)
    assert code == 0 and "GREEN" in msg


def test_ordinary_red():
    g = _gate()
    runs = [_run("completed", "failure", "bbb222bb", 2, 1.0)]
    state = g.classify_pipeline(runs, latest_failure_jobs=ORDINARY_RED_JOBS, now=NOW)
    assert state["kind"] == g.RED
    code, msg = g.render(state, now=NOW)
    assert code == 1 and "FAILURE" in msg
    # An ordinary red must NOT be dressed up as a stranded state.
    assert "R8-ST6" not in msg and "STRANDED" not in msg


def test_stranded_approval():
    """The 2026-07-28 incident shape: an old `waiting` run, later runs queued
    behind it with 0 jobs, latest COMPLETED run green — the old gate said ✅."""
    g = _gate()
    runs = [
        _run("queued", "", "ddd444dd", 30330000000, 0.5),  # queued behind the gate, 0 jobs
        _run("waiting", "", "8d9a05cc", 30324990970, 15.0),  # parked at the approval gate
        _run("completed", "success", "ccc333cc", 3, 16.0),
    ]
    state = g.classify_pipeline(runs, now=NOW)
    assert state["kind"] == g.STRANDED_APPROVAL
    code, msg = g.render(state, now=NOW)
    assert code == 1
    # Names the class + the run id + sha (acceptance), and the recovery ritual.
    assert "STRANDED PRODUCTION APPROVAL" in msg
    assert "30324990970" in msg and "8d9a05cc" in msg
    assert "approve_deployment.sh" in msg
    assert "deploy_all=true" in msg
    # Distinguishes from the phantom-concurrency class explicitly.
    assert "phantom" in msg


def test_r8st6_plan_red_deploy_skipped():
    g = _gate()
    runs = [_run("completed", "failure", "c1d2ac95", 30757772757, 3.0)]
    state = g.classify_pipeline(runs, latest_failure_jobs=R8ST6_JOBS, now=NOW)
    assert state["kind"] == g.STRANDED_PLAN
    code, msg = g.render(state, now=NOW)
    assert code == 1
    assert "R8-ST6" in msg
    assert "cdk_deploy.sh" in msg and "deploy_all=true" in msg
    assert "c1d2ac95" in msg


# ── edges that made the incident expensive ───────────────────────────────────
def test_young_waiting_run_is_a_notice_not_a_red():
    """A production approval pending minutes after a merge is the pipeline's
    normal state — the gate must not cry wolf on every wrap-after-merge."""
    g = _gate()
    runs = [
        _run("waiting", "", "eee555ee", 5, 0.5),
        _run("completed", "success", "fff666ff", 6, 1.0),
    ]
    state = g.classify_pipeline(runs, now=NOW)
    assert state["kind"] == g.GREEN
    code, msg = g.render(state, now=NOW)
    assert code == 0
    assert "awaiting production approval" in msg  # visible, not silent


def test_overdue_waiting_outranks_a_green_completed_run():
    g = _gate()
    over = g.STRANDED_WAIT_HOURS + 0.1
    runs = [
        _run("waiting", "", "abc123ab", 7, over),
        _run("completed", "success", "fff666ff", 8, over + 1),
    ]
    assert g.classify_pipeline(runs, now=NOW)["kind"] == g.STRANDED_APPROVAL


def test_plan_red_with_other_failures_is_red_but_flags_the_stranded_deploy_path():
    """Unit Tests red + Plan red = a code fix is owed (NOT the stranded-plan
    verdict — the CDK deploy alone would not clear it), but the deploy path
    IS still stranded and the message must say both."""
    g = _gate()
    runs = [_run("completed", "failure", "d6373f0b", 30761026008, 1.0)]
    state = g.classify_pipeline(runs, latest_failure_jobs=DUAL_RED_STRANDED_JOBS, now=NOW)
    assert state["kind"] == g.RED
    assert state["deploy_also_stranded"] is True
    code, msg = g.render(state, now=NOW)
    assert code == 1
    assert "FAILURE" in msg and "stranded" in msg and "R8-ST6" in msg


def test_jobs_unavailable_degrades_to_ordinary_red():
    g = _gate()
    runs = [_run("completed", "failure", "abcd1234", 9, 1.0)]
    assert g.classify_pipeline(runs, latest_failure_jobs=None, now=NOW)["kind"] == g.RED


def test_1327_surface_preserved():
    """latest_main_conclusion stays the #1327 contract (skip cancelled)."""
    g = _gate()
    runs = [
        {"status": "completed", "conclusion": "cancelled", "headSha": "aaa111"},
        {"status": "in_progress", "conclusion": "", "headSha": "bbb222"},
        {"status": "completed", "conclusion": "success", "headSha": "ccc333"},
    ]
    assert g.latest_main_conclusion(runs) == ("success", "ccc333")


def test_conventions_records_the_distinguishing_tell():
    """Acceptance: CONVENTIONS.md carries the phantom-vs-stranded tell."""
    with open(os.path.join(_REPO, "docs", "CONVENTIONS.md")) as f:
        conv = f.read()
    low = conv.lower()
    assert "phantom" in low and "waiting" in low
    assert "approve_deployment.sh" in conv
    assert "deploy_all=true" in conv
