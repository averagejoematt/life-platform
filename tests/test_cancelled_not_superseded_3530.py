"""tests/test_cancelled_not_superseded_3530.py — a `cancelled` rollup is not a
supersession on this repo, and neither green-reader may treat it as one (#3530).

THE DEFECT
----------
`scripts/check_main_green.py` and `scripts/check_ci_warnings.py` both skipped
every run whose ROLLUP conclusion was `cancelled`, on the stated reason
"cancelled runs are superseded pushes, not verdicts". That reason expired at
#2009: ci-cd.yml's workflow-level concurrency group has carried
`${{ github.run_id }}` ever since (`ci-cd.yml:129`), so it is unique per run and
NOTHING supersedes a CI/CD run any more. The one canceller left is the `deploy`
job's own group `ci-cd-deploy-${{ github.ref }}` (`ci-cd.yml:861-862`): GitHub
allows exactly one pending entry, so a newer run's Deploy EVICTS the older run's
still-pending Deploy, that job concludes `cancelled`, and the whole run rolls up
`cancelled` — regardless of what the validation jobs above it already concluded.

Live, 2026-09-04 (`reference_a_cancelled_ci_rollup_hides_real_failures`):
`gh run view 33843742114 --json jobs` → `failure  test / Unit Tests` (the ADR-080
coverage gate) alongside `cancelled  Deploy` with ZERO steps, and both readers
walked past it to an older `success`. A real red at HEAD read as green at the
previous sha.

THE TWO LIVE SPECIMENS THIS FILE PINS
-------------------------------------
Both captured read-only from
`gh api repos/averagejoematt/life-platform/actions/runs/<id>/jobs?per_page=100`
— the exact call `ci_run_verdicts.fetch_run_jobs` makes — and stored verbatim
under `tests/fixtures/cancelled_runs/` (fixture-must-be-the-wire):

  run 33843742114  (main @ b248a70c, 2026-09-04T06:17:16Z) — CANCELLED rollup,
                   `test / Unit Tests` = failure (failing step: "Test coverage
                   gate (regression floor, ADR-080)"), `Deploy` = cancelled with
                   0 steps. THE RED THAT HID.
  run 33937903965  (main @ e6daab64, 2026-09-05T02:01:59Z) — CANCELLED rollup,
                   every validation job `success`, `Deploy` = cancelled with 0
                   steps (evicted from the deploy group by the next merge's run).
                   A GENUINE supersession — it must still be skipped.

The negative control runs BOTH directions off the first fixture: as captured it
must RED, and with its one failing job (and that job's failing step) flipped to
`cancelled` — i.e. mutated into the second specimen's shape — it must PASS. A
guard that only ever sees the red case cannot tell you it is measuring anything.
"""

from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_ci_warnings as ccw  # noqa: E402
import check_main_green as cmg  # noqa: E402
import ci_run_verdicts as civ  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES = os.path.join(_REPO, "tests", "fixtures", "cancelled_runs")

CARRIES_FAILURE_ID = 33843742114
SUPERSEDED_ID = 33937903965

CARRIES_FAILURE_JOBS = civ.load_fixture_jobs(os.path.join(_FIXTURES, "run_33843742114_cancelled_carries_failure.json"))
SUPERSEDED_JOBS = civ.load_fixture_jobs(os.path.join(_FIXTURES, "run_33937903965_cancelled_superseded.json"))


def _supersede(jobs: list[dict]) -> list[dict]:
    """The negative-control mutation: turn the carrying-a-failure specimen into a
    genuine supersession by concluding its failing job — and that job's failing
    STEP — `cancelled`, exactly as GitHub records a job killed before it failed.

    The step has to move with the job: `failing_job_names` deliberately also
    counts a `failure` STEP inside a cancelled job (the "a step failed before the
    cancel" shape), so flipping the job alone would leave a real red behind and
    the control would prove nothing about the rollup rule.
    """
    out = copy.deepcopy(jobs)
    for job in out:
        if job.get("conclusion") == "failure":
            job["conclusion"] = "cancelled"
        for step in job.get("steps") or []:
            if step.get("conclusion") == "failure":
                step["conclusion"] = "cancelled"
    return out


# ── 1. the shared predicate, against the live payloads ───────────────────────


def test_live_specimen_carrying_a_failure_is_not_superseded():
    assert civ.classify_cancelled_run(CARRIES_FAILURE_JOBS) == civ.CANCELLED_CARRIES_FAILURE
    assert civ.failing_job_names(CARRIES_FAILURE_JOBS) == ["test / Unit Tests"]
    assert civ.cancelled_is_skippable(civ.CANCELLED_CARRIES_FAILURE) is False


def test_live_specimen_with_only_an_evicted_deploy_is_superseded():
    assert civ.classify_cancelled_run(SUPERSEDED_JOBS) == civ.CANCELLED_SUPERSEDED
    assert civ.failing_job_names(SUPERSEDED_JOBS) == []
    assert civ.cancelled_is_skippable(civ.CANCELLED_SUPERSEDED) is True


def test_negative_control_the_same_fixture_flipped_reads_as_superseded():
    """The mutation proof: the ONLY difference between the two verdicts is the
    job/step conclusions, not the rollup — both fixtures roll up `cancelled`."""
    assert civ.classify_cancelled_run(_supersede(CARRIES_FAILURE_JOBS)) == civ.CANCELLED_SUPERSEDED


def test_a_failed_step_inside_a_cancelled_job_still_counts():
    """ "The kill landed after the red step" — the job rolls up `cancelled`, but a
    step already concluded `failure`, so the run carries a real failure."""
    jobs = copy.deepcopy(CARRIES_FAILURE_JOBS)
    for job in jobs:
        if job.get("conclusion") == "failure":
            job["conclusion"] = "cancelled"  # steps deliberately NOT flipped
    assert civ.classify_cancelled_run(jobs) == civ.CANCELLED_CARRIES_FAILURE
    assert any("Test coverage gate" in n for n in civ.failing_job_names(jobs))


def test_an_unreadable_job_list_is_indeterminate_never_superseded():
    assert civ.classify_cancelled_run(None) == civ.CANCELLED_INDETERMINATE
    assert civ.classify_cancelled_run([]) == civ.CANCELLED_INDETERMINATE
    assert civ.cancelled_is_skippable(civ.CANCELLED_INDETERMINATE) is False


def test_fetch_run_jobs_degrades_to_none_never_to_an_empty_success():
    def _boom(args):
        raise RuntimeError("HTTP 403: rate limited")

    assert civ.fetch_run_jobs(_boom, "o/r", 1) is None
    assert civ.fetch_run_jobs(lambda args: {"jobs": SUPERSEDED_JOBS}, "o/r", 1) == SUPERSEDED_JOBS


def test_both_readers_consume_the_one_module():
    """Both readers import the predicate rather than re-deriving it. A second
    copy is how #3212 built a two-consumer divergence. (That the rule BINDS in
    each reader is proved behaviourally in sections 2 and 4 — this is only the
    "one home" half.)"""
    for name in ("check_main_green.py", "check_ci_warnings.py"):
        src = open(os.path.join(_REPO, "scripts", name), encoding="utf-8").read()
        assert "import ci_run_verdicts" in src, f"{name} must consume the shared predicate"


# ── 2. check_main_green.py — the cancelled red must reach the verdict ────────


def _run(run_id, sha, conclusion="cancelled", status="completed"):
    return {"databaseId": run_id, "headSha": sha, "conclusion": conclusion, "status": status, "createdAt": "2026-09-04T06:17:16Z"}


THE_HIDING_HISTORY = [
    _run(CARRIES_FAILURE_ID, "b248a70c112cc8fb6894f5b9800d8dc414920288"),
    _run(1, "0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0ld0", conclusion="success"),
]


def _probe_jobs_from(mapping):
    return lambda run: mapping.get(run.get("databaseId"))


def test_main_green_pre_3530_behaviour_is_the_bug_this_reproduces():
    """With NO cancelled verdicts supplied (the pre-#3530 code path), the gate
    still walks past the cancelled run to the older green — pinned so the
    regression is visible as a behaviour difference, not just a diff."""
    assert cmg.latest_completed_run(THE_HIDING_HISTORY)["databaseId"] == 1


def test_main_green_reds_on_the_live_cancelled_with_failure_specimen():
    verdicts, notes = cmg.scan_cancelled(THE_HIDING_HISTORY, _probe_jobs_from({CARRIES_FAILURE_ID: CARRIES_FAILURE_JOBS}))
    assert verdicts == {CARRIES_FAILURE_ID: civ.CANCELLED_CARRIES_FAILURE}

    assert cmg.latest_completed_run(THE_HIDING_HISTORY, cancelled_verdicts=verdicts)["databaseId"] == CARRIES_FAILURE_ID

    state = cmg.classify_pipeline(THE_HIDING_HISTORY, cancelled_verdicts=verdicts, cancelled_notes=notes)
    assert state["kind"] == cmg.RED
    assert state["sha"] == "b248a70c112cc8fb6894f5b9800d8dc414920288"

    code, message = cmg.render(state)
    assert code == 1
    assert "main is CANCELLED at b248a70c" in message
    assert "test / Unit Tests" in message
    assert "NOT a superseded push" in message


def test_main_green_negative_control_the_flipped_fixture_passes_through():
    """Same history, same code path — only the job conclusions differ. The gate
    must skip the cancelled run and report the older green."""
    verdicts, notes = cmg.scan_cancelled(THE_HIDING_HISTORY, _probe_jobs_from({CARRIES_FAILURE_ID: _supersede(CARRIES_FAILURE_JOBS)}))
    assert verdicts == {CARRIES_FAILURE_ID: civ.CANCELLED_SUPERSEDED}
    state = cmg.classify_pipeline(THE_HIDING_HISTORY, cancelled_verdicts=verdicts, cancelled_notes=notes)
    assert state["kind"] == cmg.GREEN
    code, message = cmg.render(state)
    assert code == 0
    assert "genuine supersession" in message, "a skipped run must still be NAMED (#2590 discipline)"


def test_main_green_skips_the_live_superseded_specimen():
    history = [_run(SUPERSEDED_ID, "e6daab648e0cdced9a451b63d23dc947472626c1"), THE_HIDING_HISTORY[1]]
    verdicts, notes = cmg.scan_cancelled(history, _probe_jobs_from({SUPERSEDED_ID: SUPERSEDED_JOBS}))
    assert verdicts == {SUPERSEDED_ID: civ.CANCELLED_SUPERSEDED}
    assert cmg.latest_completed_run(history, cancelled_verdicts=verdicts)["databaseId"] == 1


def test_main_green_unreadable_jobs_do_not_manufacture_a_green():
    verdicts, notes = cmg.scan_cancelled(THE_HIDING_HISTORY, _probe_jobs_from({}))  # probe returns None
    assert verdicts == {CARRIES_FAILURE_ID: civ.CANCELLED_INDETERMINATE}
    state = cmg.classify_pipeline(THE_HIDING_HISTORY, cancelled_verdicts=verdicts, cancelled_notes=notes)
    assert state["kind"] == cmg.RED
    code, message = cmg.render(state)
    assert code == 1
    assert "could NOT be read" in message


def test_scan_cancelled_walks_through_failures_to_reach_an_older_cancel():
    """A `failure` run between two cancels does not end the cancelled walk —
    `scan_rejections` may yet classify it as a REJECTED non-verdict (#2590), in
    which case the older cancelled run is the one that decides."""
    history = [
        _run(9, "f" * 40, conclusion="failure"),
        _run(CARRIES_FAILURE_ID, "b248a70c112cc8fb6894f5b9800d8dc414920288"),
        THE_HIDING_HISTORY[1],
    ]
    verdicts, _ = cmg.scan_cancelled(history, _probe_jobs_from({CARRIES_FAILURE_ID: CARRIES_FAILURE_JOBS}))
    assert verdicts == {CARRIES_FAILURE_ID: civ.CANCELLED_CARRIES_FAILURE}


def test_scan_rejections_stops_at_a_cancel_that_carries_a_failure():
    def _probe(run):
        raise AssertionError("scan_rejections must not probe past the cancelled verdict run")

    rejected, jobs = cmg.scan_rejections(THE_HIDING_HISTORY, _probe, cancelled_verdicts={CARRIES_FAILURE_ID: civ.CANCELLED_CARRIES_FAILURE})
    assert rejected == [] and jobs is None


def test_scan_cancelled_is_bounded():
    history = [_run(i, f"{i:040d}") for i in range(20)]
    calls = []

    def _probe(run):
        calls.append(run["databaseId"])
        return SUPERSEDED_JOBS

    verdicts, notes = cmg.scan_cancelled(history, _probe)
    assert len(calls) == cmg.CANCELLED_PROBE_LIMIT
    assert len(verdicts) == len(notes) == cmg.CANCELLED_PROBE_LIMIT


# ── 3. the #1327/#2590/#3212 contracts this change may not weaken ────────────


def test_decoded_escape_hatch_and_head_coverage_line_are_untouched():
    src = open(os.path.join(_REPO, "scripts", "check_main_green.py"), encoding="utf-8").read()
    assert 'decoded = "--decoded" in sys.argv' in src
    assert 'HEAD_COVERAGE_PREFIX = "HEAD-COVERAGE:"' in src
    assert 'lines.append(f"{HEAD_COVERAGE_PREFIX} {head_coverage_state_name(state)}' in src


def test_head_coverage_line_still_rides_along_on_a_cancelled_red():
    verdicts, notes = cmg.scan_cancelled(THE_HIDING_HISTORY, _probe_jobs_from({CARRIES_FAILURE_ID: CARRIES_FAILURE_JOBS}))
    state = cmg.classify_pipeline(THE_HIDING_HISTORY, cancelled_verdicts=verdicts, cancelled_notes=notes)
    state["head_sha"] = "b248a70c112cc8fb6894f5b9800d8dc414920288"
    state["head_cov"] = cmg.head_coverage(THE_HIDING_HISTORY, state["head_sha"])
    _, message = cmg.render(state)
    assert f"{cmg.HEAD_COVERAGE_PREFIX} " in message


# ── 4. check_ci_warnings.py — the same rule, the same module ─────────────────


def test_ci_warnings_does_not_triage_an_older_green_behind_a_hidden_red(monkeypatch):
    runs = [
        {"status": "completed", "conclusion": "cancelled", "headSha": "b248a70c", "databaseId": CARRIES_FAILURE_ID},
        {"status": "completed", "conclusion": "success", "headSha": "0ld0ld0ld", "databaseId": 1},
    ]

    def _gh(args):
        if args and args[0] == "run":
            return runs
        return {"jobs": CARRIES_FAILURE_JOBS}

    monkeypatch.setattr(ccw, "_gh_json", _gh)
    sha, err, notes = ccw.latest_green_main_info()
    assert (sha, err) == (None, None)
    assert any("test / Unit Tests" in n for n in notes)

    code, message = ccw.render([], sha, err, cancelled_notes=notes)
    assert code == 0, "not-green is check_main_green.py's gate, not this one"
    assert "test / Unit Tests" in message, "the hidden red must be NAMED here, not silently skipped"


def test_ci_warnings_negative_control_flipped_fixture_reaches_the_older_green(monkeypatch):
    runs = [
        {"status": "completed", "conclusion": "cancelled", "headSha": "b248a70c", "databaseId": CARRIES_FAILURE_ID},
        {"status": "completed", "conclusion": "success", "headSha": "0ld0ld0ld", "databaseId": 1},
    ]
    flipped = _supersede(CARRIES_FAILURE_JOBS)

    def _gh(args):
        if args and args[0] == "run":
            return runs
        return {"jobs": flipped}

    monkeypatch.setattr(ccw, "_gh_json", _gh)
    sha, err, notes = ccw.latest_green_main_info()
    assert (sha, err) == ("0ld0ld0ld", None)
    assert any("genuine supersession" in n for n in notes)
