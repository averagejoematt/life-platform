"""tests/test_deploy_wedge_2052.py — the deploy-wedge detector's negative tests (#2052).

The detector is only worth shipping if it tells the wedge apart from the two states it
LOOKS like. All three occurred within 24h on 2026-08-02/03, so every fixture here is a
real API payload (see tests/fixtures/deploy_wedge/README.md), not an invention.

The load-bearing fact these tests pin: `queued_behind` and `phantom_wedge` are
**byte-identical at the single-run level** — same run.status, same Deploy job status,
same empty pending_deployments. `test_wedge_and_queued_behind_are_indistinguishable_per_run`
asserts that identity directly, so if a future refactor tries to classify from one run's
fields the test says why it cannot work.
"""

import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import check_deploy_wedge as cdw  # noqa: E402

_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "deploy_wedge")


def load(name):
    with open(os.path.join(_FIXTURES, f"{name}.json"), encoding="utf-8") as f:
        data = json.load(f)
    now = datetime.fromisoformat(data["now"].replace("Z", "+00:00"))
    return data, now


def classify(name, threshold=cdw.DEFAULT_THRESHOLD_MIN):
    data, now = load(name)
    return cdw.classify_fleet(data["runs"], data["jobs"], data["pending"], now=now, threshold_min=threshold)


# --------------------------------------------------------------------------
# The four states, each from its real payload.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture,expected",
    [
        ("phantom_wedge", cdw.PHANTOM_WEDGE),
        ("queued_behind", cdw.QUEUED_BEHIND),
        ("awaiting_approval", cdw.AWAITING_APPROVAL),
        ("stranded_approval", cdw.STRANDED_APPROVAL),
    ],
)
def test_each_real_state_classifies_correctly(fixture, expected):
    assert classify(fixture)["kind"] == expected


@pytest.mark.parametrize(
    "fixture,exit_code",
    [
        ("phantom_wedge", 1),  # needs a human NOW
        ("stranded_approval", 1),  # needs a human NOW
        ("queued_behind", 0),  # the invariant working
        ("awaiting_approval", 0),  # normal post-merge state
    ],
)
def test_only_the_two_incident_states_exit_nonzero(fixture, exit_code):
    code, _ = cdw.render(classify(fixture))
    assert code == exit_code


# --------------------------------------------------------------------------
# The negative test that matters: why a per-run classifier cannot work.
# --------------------------------------------------------------------------


def test_wedge_and_queued_behind_are_indistinguishable_per_run():
    """The wedged run and the legitimately-blocked run have identical single-run state.

    If this ever stops being true, the detector could be simplified — but as measured on
    2026-08-02/03 it IS true, and it is the reason five recurrences were misdiagnosed.
    """
    wedge_data, _ = load("phantom_wedge")
    behind_data, _ = load("queued_behind")

    wedged_run = wedge_data["runs"][0]
    blocked_run = behind_data["runs"][0]

    def fingerprint(run, data):
        job = cdw.deploy_job(data["jobs"][str(run["id"])])
        return (run["status"], job["status"], bool(data["pending"].get(str(run["id"]))))

    assert fingerprint(wedged_run, wedge_data) == fingerprint(blocked_run, behind_data)
    assert fingerprint(wedged_run, wedge_data) == ("pending", "pending", False)


def test_the_only_discriminator_is_the_holder():
    """Removing the holder from the healthy fixture turns it into a wedge, and nothing else does."""
    data, now = load("queued_behind")
    assert cdw.classify_fleet(data["runs"], data["jobs"], data["pending"], now=now)["kind"] == cdw.QUEUED_BEHIND

    # Drop the holding run (30828914859) — the blocked run's own fields are untouched.
    runs = [r for r in data["runs"] if r["id"] != 30828914859]
    assert cdw.classify_fleet(runs, data["jobs"], data["pending"], now=now)["kind"] == cdw.PHANTOM_WEDGE


def test_a_completed_holder_does_not_hold_the_group():
    """The 2026-08-02 burst's cancelled runs must NOT be read as holders.

    They are present in the phantom fixture's run list with Deploy jobs — but completed.
    A classifier that counted them would have called the real wedge 'queued-behind'.
    """
    data, now = load("phantom_wedge")
    held = cdw.holders(data["runs"], data["jobs"], "main", exclude_run_id=30769861255)
    assert held == []
    assert cdw.classify_fleet(data["runs"], data["jobs"], data["pending"], now=now)["kind"] == cdw.PHANTOM_WEDGE


# --------------------------------------------------------------------------
# Threshold + holder-state behaviour.
# --------------------------------------------------------------------------


def test_a_young_block_is_not_yet_a_wedge():
    """Ordinary runner queueing must not alarm. Same payload, threshold above the age."""
    data, now = load("phantom_wedge")
    # The Deploy job has been blocked ~12.2m at the fixture's `now`.
    assert cdw.classify_fleet(data["runs"], data["jobs"], data["pending"], now=now, threshold_min=60)["kind"] == cdw.HEALTHY


def test_the_wedge_is_caught_well_inside_the_observed_window():
    data, now = load("phantom_wedge")
    assert cdw.classify_fleet(data["runs"], data["jobs"], data["pending"], now=now, threshold_min=4)["kind"] == cdw.PHANTOM_WEDGE


def test_a_waiting_deploy_holds_the_group():
    """A run parked at the approval gate occupies the concurrency slot — that is WHY the
    #1901 stranded-approval class blocks every later run. Pinning it stops a refactor
    from 'simplifying' HOLDING_JOB_STATUSES down to in_progress."""
    assert "waiting" in cdw.HOLDING_JOB_STATUSES
    data, _ = load("queued_behind")
    held = cdw.holders(data["runs"], data["jobs"], "main", exclude_run_id=30830154876)
    assert [h["id"] for h in held] == [30828914859]


def test_stranded_and_awaiting_differ_only_by_age():
    """Same shape, different clock — the threshold is the whole distinction."""
    data, _ = load("awaiting_approval")
    early = datetime(2026, 8, 3, 16, 2, tzinfo=timezone.utc)
    late = datetime(2026, 8, 3, 19, 0, tzinfo=timezone.utc)
    assert cdw.classify_fleet(data["runs"], data["jobs"], data["pending"], now=early)["kind"] == cdw.AWAITING_APPROVAL
    assert cdw.classify_fleet(data["runs"], data["jobs"], data["pending"], now=late)["kind"] == cdw.STRANDED_APPROVAL


# --------------------------------------------------------------------------
# Shape guards.
# --------------------------------------------------------------------------


def test_deploy_critical_tests_is_not_mistaken_for_the_deploy_job():
    """'Deploy-critical tests' shares a prefix with 'Deploy' and always completes early.

    A prefix match would read it as a completed deploy and mask every wedge.
    """
    jobs = [
        {"name": "Deploy-critical tests", "status": "completed", "conclusion": "success", "started_at": "2026-08-02T22:22:41Z"},
        {"name": "Deploy", "status": "pending", "conclusion": None, "started_at": "2026-08-02T22:27:18Z"},
    ]
    assert cdw.deploy_job(jobs)["status"] == "pending"


def test_ui_spelling_queued_classifies_the_same_as_api_spelling_pending():
    """The issue body recorded the UI's 'queued'; the API says 'pending'. Both must work."""
    data, now = load("phantom_wedge")
    jobs = json.loads(json.dumps(data["jobs"]))
    cdw.deploy_job(jobs["30769861255"])["status"] = "queued"
    assert cdw.classify_fleet(data["runs"], jobs, data["pending"], now=now)["kind"] == cdw.PHANTOM_WEDGE


def test_no_deploy_job_yet_is_healthy():
    """Validation still in flight, or Plan concluded has_deploys=false."""
    runs = [{"id": 1, "status": "in_progress", "head_branch": "main", "head_sha": "abc", "created_at": "2026-08-03T16:00:00Z"}]
    jobs = {"1": [{"name": "Plan deployments", "status": "in_progress", "conclusion": None, "started_at": "2026-08-03T16:04:00Z"}]}
    now = datetime(2026, 8, 3, 16, 30, tzinfo=timezone.utc)
    assert cdw.classify_fleet(runs, jobs, {}, now=now)["kind"] == cdw.HEALTHY


def test_an_empty_fleet_is_healthy():
    assert cdw.classify_fleet([], {}, {}, now=datetime.now(timezone.utc))["kind"] == cdw.HEALTHY


def test_wedge_message_names_the_recovery_and_the_run():
    _, message = cdw.render(classify("phantom_wedge"))
    assert "30769861255" in message
    assert "deploy_all=true" in message
    assert "nothing to approve" in message


def test_stranded_message_names_the_approval_path_not_cancellation():
    _, message = cdw.render(classify("stranded_approval"))
    assert "approve_deployment.sh" in message
    assert "Do NOT cancel" in message


def test_wedge_threshold_agrees_with_check_main_green_on_stranded_hours():
    """The two gates must not disagree about when a wait becomes stranded (#1901/#2052)."""
    import check_main_green  # noqa: PLC0415

    assert cdw.STRANDED_WAIT_HOURS == check_main_green.STRANDED_WAIT_HOURS


# --------------------------------------------------------------------------
# check_main_green integration — acceptance bullet 3 of #2052.
# --------------------------------------------------------------------------


def _green_runs():
    """A run list whose completed verdict is GREEN — the fact the wedge must override."""
    return [
        {
            "databaseId": 30786589137,
            "status": "completed",
            "conclusion": "success",
            "headSha": "5f5405aa1234567890",
            "createdAt": "2026-08-03T05:14:16Z",
        }
    ]


def test_check_main_green_classifies_the_wedge_as_its_own_state():
    import check_main_green as cmg  # noqa: PLC0415

    state = cmg.classify_pipeline(_green_runs(), deploy_wedge=classify("phantom_wedge"))
    assert state["kind"] == cmg.STRANDED_DEPLOY_WEDGE
    assert state["kind"] not in (cmg.STRANDED_APPROVAL, cmg.STRANDED_PLAN)


def test_wedge_outranks_a_green_completed_run():
    """While a wedge holds, nothing can deploy — so 'main GREEN' is a stale fact, and the
    wrap gate must not let a session declare victory on it."""
    import check_main_green as cmg  # noqa: PLC0415

    state = cmg.classify_pipeline(_green_runs(), deploy_wedge=classify("phantom_wedge"))
    code, message = cmg.render(state)
    assert code == 1
    assert "PHANTOM DEPLOY WEDGE" in message
    assert "30769861255" in message


def test_wedge_verdict_tells_the_operator_not_to_salt():
    """Three salts failed across recurrences 1-3. The decode must say so, in place."""
    import check_main_green as cmg  # noqa: PLC0415

    _, message = cmg.render(cmg.classify_pipeline(_green_runs(), deploy_wedge=classify("phantom_wedge")))
    assert "Do NOT salt" in message
    assert "nothing to approve" in message


@pytest.mark.parametrize("fixture", ["queued_behind", "awaiting_approval", "stranded_approval"])
def test_non_wedge_states_do_not_trigger_the_wedge_verdict(fixture):
    """The other three real states must leave check_main_green's verdict alone."""
    import check_main_green as cmg  # noqa: PLC0415

    state = cmg.classify_pipeline(_green_runs(), deploy_wedge=classify(fixture))
    assert state["kind"] != cmg.STRANDED_DEPLOY_WEDGE


# --------------------------------------------------------------------------
# The watchdog workflow's own structural invariants.
#
# Text-based on purpose, like tests/test_workflow_hygiene.py: CI's `test` job installs
# only pytest/boto3/botocore, so a PyYAML dependency here would not run in CI.
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


def test_recovery_is_opt_in_not_automatic():
    """The scheduled run detects and alarms; it must never recover unattended."""
    body = "\n".join(_uncommented_lines(_WATCHER))
    assert "github.event_name == 'workflow_dispatch'" in body
    assert "inputs.recover == 'true'" in body


def test_recover_refuses_any_verdict_other_than_a_confirmed_wedge(capsys, monkeypatch):
    """The escape hatch must be inert on the three non-wedge states — cancelling a run
    that is legitimately queued or awaiting approval strands its deploy (#1901)."""

    def explode(*a, **k):  # any subprocess call here is a bug
        raise AssertionError("recover() must not shell out on a non-wedge verdict")

    monkeypatch.setattr(cdw.subprocess, "run", explode)
    for fixture in ("queued_behind", "awaiting_approval", "stranded_approval"):
        assert cdw.recover(classify(fixture)) == 1
    assert "refused" in capsys.readouterr().out


def test_absent_wedge_detection_leaves_the_legacy_verdict_untouched():
    """The detector is best-effort; losing it must not change green/red (#1327 surface)."""
    import check_main_green as cmg  # noqa: PLC0415

    assert cmg.classify_pipeline(_green_runs(), deploy_wedge=None)["kind"] == cmg.GREEN
    assert cmg.classify_pipeline(_green_runs())["kind"] == cmg.GREEN
