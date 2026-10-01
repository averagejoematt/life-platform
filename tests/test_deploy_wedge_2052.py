"""tests/test_deploy_wedge_2052.py — the deploy watchdog workflow's invariants (#2052, #4256).

The phantom-wedge classifier this file used to test (`scripts/check_deploy_wedge.py`, with
its real-payload fixtures) was retired by #4256 box 3: ADR-158 moved the production gate
off the code `deploy` job, and the deploy dead-man (`scripts/check_deploy_deadman.py`)
alarms on ANY green run on main that has not deployed within its deadline — a wedged
Deploy is such a run. What remains here are the invariants of the workflow that hosts
the dead-man (still `deploy-wedge-watch.yml`, so the cron-freshness registry, the
dark-flag sweep and the census keep their key): it observes ci-cd.yml from OUTSIDE, so it
must own no concurrency group, run unattended, and never hold AWS credentials.
"""

import os

# --------------------------------------------------------------------------
# The watchdog workflow's structural invariants. Text-based on purpose, like
# tests/test_workflow_hygiene.py: CI's `test` job installs only pytest/boto3/botocore.
# --------------------------------------------------------------------------

_WATCHER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".github", "workflows", "deploy-wedge-watch.yml")


def _uncommented_lines(path):
    with open(path, encoding="utf-8") as f:
        return [ln for ln in f.read().splitlines() if not ln.lstrip().startswith("#")]


def test_the_watchdog_owns_no_concurrency_group():
    """A watchdog for a stuck concurrency queue must not be able to wedge the same way.

    This is the whole reason it is a separate workflow. If someone later adds a
    `concurrency:` block "for tidiness", the detector becomes wedgeable by the very
    failure it exists to catch.
    """
    keys = [ln for ln in _uncommented_lines(_WATCHER) if ln.startswith("concurrency:") or ln.strip().startswith("concurrency:")]
    assert keys == [], f"deploy-wedge-watch.yml must not declare concurrency: {keys}"


def test_the_watchdog_runs_on_a_schedule_and_on_demand():
    body = "\n".join(_uncommented_lines(_WATCHER))
    assert "schedule:" in body, "must detect unattended — the wedge appears at 2am"
    assert "workflow_dispatch:" in body, "must be runnable on demand as the escape hatch"
    assert "cron:" in body


def test_the_watchdog_never_deploys_and_never_touches_aws():
    """It re-dispatches ci-cd.yml, which still stops at the production gate. It must not
    hold AWS credentials or invoke a deploy script itself."""
    body = "\n".join(_uncommented_lines(_WATCHER))
    for forbidden in ("aws-actions/configure-aws-credentials", "cdk_deploy", "deploy_fleet", "deploy_lambda", "sync_site_to_s3"):
        assert forbidden not in body, f"watchdog must not {forbidden}"
    assert "environment:" not in body, "watchdog must not sit behind the production gate it monitors"


def test_the_wedge_recovery_path_stays_retired():
    """#4256: `--recover` (cancel + re-dispatch) left with the classifier. The dead-man's
    alarm prints the one recovery command; the watchdog never acts unattended."""
    body = "\n".join(_uncommented_lines(_WATCHER))
    assert "check_deploy_wedge.py" not in body
    assert "recover" not in body
    assert "actions: write" not in body, "nothing cancels or re-dispatches a run any more"


# --- deploy/watch_deploy_gate.sh was RETIRED by #4256 (ADR-158): code deploys no longer
# park at the production gate, so nothing needs auto-approving, and the one gate left
# (the additive-IAM deploy) is a human's click by the owner's ruling. Its two text pins
# (#2467's reject-not-skip posture) went with it; the reject wrapper stays. ---

_DEPLOY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy")


def test_the_session_gate_watcher_stays_retired():
    """ADR-158: an auto-approver would click the one gate the owner kept for himself."""
    assert not os.path.exists(os.path.join(_DEPLOY_DIR, "watch_deploy_gate.sh"))


def test_reject_wrapper_exists_and_posts_state_rejected():
    reject = os.path.join(_DEPLOY_DIR, "reject_deployment.sh")
    with open(reject, encoding="utf-8") as f:
        body = f.read()
    assert '"state": "rejected"' in body
    assert "pending_deployments" in body
    assert os.access(reject, os.X_OK), "reject_deployment.sh must be executable like approve_deployment.sh"
