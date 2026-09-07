#!/usr/bin/env python3
"""scripts/ci_run_verdicts.py — what a `cancelled` CI/CD rollup actually means (#3530).

THE DEFECT THIS EXISTS TO CLOSE
-------------------------------
Two readers of main's CI/CD history — `scripts/check_main_green.py` (the /wrap
green-main gate) and `scripts/check_ci_warnings.py` (the warning-triage gate) —
both skipped EVERY run whose rollup conclusion was `cancelled`, on the stated
reason "cancelled runs are superseded pushes, not verdicts". That reason was
true when it was written and is false now:

  * ci-cd.yml's WORKFLOW-level concurrency group has carried `${{ github.run_id }}`
    since #2009 (`ci-cd.yml:129`), so it is unique per run — nothing supersedes a
    CI/CD run any more.
  * The `deploy` job keeps its own group `ci-cd-deploy-${{ github.ref }}`
    (`ci-cd.yml:861-862`). GitHub allows exactly ONE pending entry per group, so a
    newer run's Deploy EVICTS the older run's still-pending Deploy. The evicted
    `Deploy` job concludes `cancelled`, which makes the whole RUN conclude
    `cancelled` — no matter what the validation jobs above it already concluded.

So on this repo a `cancelled` rollup is routinely a run whose `test / Unit Tests`
job FAILED and whose only cancellation was a Deploy that was never going to run.
Both readers walked straight past it to an older `success` and reported main
green at a sha that had no verdict at all. Live on 2026-09-04 (three times in one
night; `reference_a_cancelled_ci_rollup_hides_real_failures`).

THE RULE, STATED ONCE
---------------------
The rollup conclusion is not the verdict. The run's own JOBS are:

  cancelled-superseded      no job concluded `failure` and no step inside any job
                            concluded `failure`, and no job's own duration reached
                            its configured `timeout-minutes` ceiling — nothing had
                            gone wrong when the cancel landed. Safe to skip: it
                            carries no verdict.
  cancelled-carries-failure some job concluded `failure`, OR some step concluded
                            `failure` inside a job that was later cancelled (the
                            failure happened BEFORE the cancel). This is a RED.
  cancelled-timeout         (#3678) no job failed, but some job's OWN duration sat
                            at or past its declared `timeout-minutes` ceiling —
                            GitHub's wall clock killed a job that was still green,
                            not a newer push evicting it. This is DISTINCT from a
                            supersession precisely because the cures are opposite:
                            a supersession is ignored (a re-run needs nothing), a
                            timeout means the ceiling itself is wrong (raise it or
                            split the job) and re-running spends the same minutes
                            to re-prove a green that already existed. Only
                            reachable when the caller supplies `timeouts_by_job_name`
                            (`ci_job_timeouts.py`) — without it this class collapses
                            into `cancelled-superseded`, same as before #3678.
  cancelled-indeterminate   the job list could not be read. Never skippable —
                            "could not verify" must not read as "superseded".

Both readers import these functions. The rule is NOT restated in either of them:
#3212's lesson (logic living inside one consumer that the other could not reach)
is exactly how a two-reader divergence gets built.

JOB PAYLOAD SHAPE
-----------------
`jobs` is the `jobs` array of `GET /repos/{owner}/{repo}/actions/runs/{id}/jobs`
(pinned verbatim in `tests/fixtures/cancelled_runs/`). `gh run view <id> --json
jobs` returns the same three fields these predicates read — `name`,
`conclusion`, `steps[].conclusion` — plus (#3678) `started_at`/`completed_at`,
which `job_hit_its_own_timeout()` reads to tell a genuine timeout from an
eviction.
"""

from __future__ import annotations

import json
from datetime import datetime

# The four things a `cancelled` rollup can mean. Module constants so both
# readers (and their tests) share ONE vocabulary rather than each matching on a
# phrase — the #3199 lesson: every phrase-matched classifier in this repo has
# failed in the field.
CANCELLED_SUPERSEDED = "cancelled-superseded"
CANCELLED_CARRIES_FAILURE = "cancelled-carries-failure"
CANCELLED_TIMEOUT = "cancelled-timeout"
CANCELLED_INDETERMINATE = "cancelled-indeterminate"

# The states that let a reader skip the run without looking further. Deliberately
# a one-element set rather than "not CARRIES_FAILURE": an INDETERMINATE read must
# fall on the NOT-skippable side, so a `gh` hiccup can never manufacture a green —
# and CANCELLED_TIMEOUT is deliberately NOT here either (#3678): a job hitting its
# own ceiling is a defect to surface, not a non-verdict to walk past.
CANCELLED_SKIPPABLE = frozenset({CANCELLED_SUPERSEDED})

# #3678: how much of the ceiling a job's observed duration must reach before this
# module calls it a genuine timeout rather than an early eviction. GitHub's own
# kill lands a little past the exact `timeout-minutes*60` mark (teardown/reporting
# lag — the pr-checks fast-lane job was observed killed at 15m22s against a 15m0s
# ceiling, 22s over), so the window is symmetric: `[ceiling - slack, +inf)`. An
# eviction from a `cancel-in-progress` concurrency group typically lands seconds
# after the job starts (or before it starts at all), nowhere near a multi-minute
# ceiling, so 45s of slack cannot confuse the two on any observed case.
TIMEOUT_DETECTION_SLACK_SECONDS = 45.0

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def job_duration_seconds(job: dict) -> float | None:
    """Wall-clock seconds between a job's `started_at` and `completed_at`. Pure.

    `None` when either timestamp is missing/unparseable — never a false zero.
    """
    if not isinstance(job, dict):
        return None
    started, completed = job.get("started_at"), job.get("completed_at")
    if not started or not completed:
        return None
    try:
        return (datetime.strptime(completed, _TS_FMT) - datetime.strptime(started, _TS_FMT)).total_seconds()
    except (ValueError, TypeError):
        return None


def job_hit_its_own_timeout(
    job: dict, timeout_minutes: float | None, slack_seconds: float = TIMEOUT_DETECTION_SLACK_SECONDS
) -> bool | None:
    """Did THIS job's own cancellation happen at its configured ceiling? Pure.

    Returns `None` (unproven, never treated as True) when the job's own
    conclusion is not `cancelled`, when no ceiling is known for it, or when its
    duration cannot be computed — the same "unproven is not superseded" posture
    `cancelled_is_skippable()` already holds for the run level.
    """
    if not isinstance(job, dict) or job.get("conclusion") != "cancelled":
        return False if isinstance(job, dict) else None
    if timeout_minutes is None:
        return None
    duration = job_duration_seconds(job)
    if duration is None:
        return None
    return duration >= (float(timeout_minutes) * 60.0) - slack_seconds


def failing_job_names(jobs: list[dict] | None) -> list[str]:
    """Names of every job in `jobs` that carries a real failure. Pure.

    A job counts as failing when its OWN conclusion is `failure`, or when any of
    its steps concluded `failure` — the second clause is the "a step failed
    before the cancel" shape, where GitHub rolls the job up as `cancelled`
    because the kill landed after the red step but before the job ended.
    Deploy is NOT special-cased: a Deploy that genuinely `failure`d is a red, and
    a Deploy evicted from its concurrency group concludes `cancelled` with zero
    steps, which this function correctly reports as no failure at all.
    """
    out: list[str] = []
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        name = job.get("name") or "?"
        if job.get("conclusion") == "failure":
            out.append(name)
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("conclusion") == "failure":
                out.append(f"{name} (step: {step.get('name') or '?'})")
                break
    return out


def classify_cancelled_run(jobs: list[dict] | None, timeouts_by_job_name: dict[str, float] | None = None) -> str:
    """One of the four CANCELLED_* constants for a run whose rollup is `cancelled`.

    `jobs is None` means the job list could not be read — INDETERMINATE, never
    SUPERSEDED. An EMPTY list is different and is treated the same way: a
    completed run always has jobs, so zero of them means the read told us
    nothing.

    `timeouts_by_job_name` (#3678, `ci_job_timeouts.timeout_minutes_by_job_name()`)
    is optional and additive: when a caller supplies it and no job carries a real
    failure, every job is checked against its own declared ceiling
    (`job_hit_its_own_timeout`) before falling back to SUPERSEDED. Omitting it
    reproduces the pre-#3678 behaviour exactly — no existing caller's verdicts
    change just by upgrading this module.
    """
    if not jobs:
        return CANCELLED_INDETERMINATE
    if failing_job_names(jobs):
        return CANCELLED_CARRIES_FAILURE
    if timeouts_by_job_name:
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if job_hit_its_own_timeout(job, timeouts_by_job_name.get(job.get("name"))):
                return CANCELLED_TIMEOUT
    return CANCELLED_SUPERSEDED


def classify_cancelled_check(
    check_name: str,
    started_at: str | None,
    completed_at: str | None,
    timeouts_by_job_name: dict[str, float] | None = None,
    slack_seconds: float = TIMEOUT_DETECTION_SLACK_SECONDS,
) -> str:
    """`classify_cancelled_run`'s sibling for a SINGLE PR check (#3678).

    `deploy/wait_pr_green.sh` never sees a run's `jobs` array — `gh pr checks
    --json` gives it one row per check with `startedAt`/`completedAt` already
    attached (the SAME two timestamps `job_hit_its_own_timeout` reads), so this
    needs no extra `gh` call: the pure evaluator stays pure. Returns
    CANCELLED_TIMEOUT, CANCELLED_SUPERSEDED, or CANCELLED_INDETERMINATE — never
    CANCELLED_CARRIES_FAILURE, because an attached `failure` bucket is already a
    hard red by name; this function only exists to explain a `cancel` bucket.
    """
    timeouts_by_job_name = timeouts_by_job_name or {}
    timeout_minutes = timeouts_by_job_name.get(check_name)
    if timeout_minutes is None:
        return CANCELLED_INDETERMINATE
    duration = job_duration_seconds({"started_at": started_at, "completed_at": completed_at})
    if duration is None:
        return CANCELLED_INDETERMINATE
    hit = duration >= (float(timeout_minutes) * 60.0) - slack_seconds
    return CANCELLED_TIMEOUT if hit else CANCELLED_SUPERSEDED


def describe_cancelled_check(check_name: str, verdict: str) -> str:
    """One operator-readable line for a `cancel`-bucket PR check (#3678).

    Companion to `describe_cancelled` (run-level, #3530) at check-level — printed
    by `deploy/wait_pr_green.sh` next to its existing `NONGREEN <name> <state>`
    line, never replacing it."""
    if verdict == CANCELLED_TIMEOUT:
        return (
            f"CANCEL-DIAGNOSIS {check_name}: TIMEOUT — this check's own duration reached its "
            "configured timeout-minutes ceiling (#3678). Not a supersession: raise or split the "
            "ceiling, a re-run will not fix it."
        )
    if verdict == CANCELLED_SUPERSEDED:
        return (
            f"CANCEL-DIAGNOSIS {check_name}: SUPERSEDED — cancelled well before its own ceiling, "
            "consistent with a `cancel-in-progress` concurrency eviction (a newer push), not a defect."
        )
    return (
        f"CANCEL-DIAGNOSIS {check_name}: INDETERMINATE — no declared ceiling or timing was available "
        "for this check name; superseded vs. timeout is unproven (#3678)."
    )


def cancelled_is_skippable(verdict: str | None) -> bool:
    """True iff a reader may walk past this cancelled run to an older one.

    `None` (the run was never probed) reads as skippable so the PURE functions
    keep their pre-#3530 behaviour for callers that supply no job data at all;
    every LIVE caller in this repo probes, and their tests pin that they do.
    """
    if verdict is None:
        return True
    return verdict in CANCELLED_SKIPPABLE


def describe_cancelled(run: dict, verdict: str, failing: list[str] | None = None) -> str:
    """One operator-readable line for a cancelled run a reader classified.

    Every cancelled run gets one — including the skipped ones. The #2590 lesson:
    a run the gate walks past must be REPORTED, so "the lease was actioned" can
    never be confused with "the gate is blind".
    """
    run_id = run.get("databaseId") or run.get("id") or "?"
    sha8 = (run.get("headSha") or run.get("head_sha") or "")[:8] or "?"
    if verdict == CANCELLED_CARRIES_FAILURE:
        names = ", ".join(failing or []) or "unnamed job(s)"
        return (
            f"🛑 run {run_id} sha {sha8} concluded `cancelled` but is NOT superseded (#3530) — "
            f"its own jobs carry a real failure: {names}."
        )
    if verdict == CANCELLED_TIMEOUT:
        return (
            f"⏱️  run {run_id} sha {sha8} concluded `cancelled` but is NOT a supersession (#3678) — "
            "a job's OWN duration reached its configured `timeout-minutes` ceiling while every step "
            "that ran was green. Cure is raising or splitting that ceiling, never a re-run: a re-run "
            "spends the same minutes re-proving a green that already existed."
        )
    if verdict == CANCELLED_INDETERMINATE:
        return (
            f"⚠️  run {run_id} sha {sha8} concluded `cancelled` and its job list could NOT be read — "
            "superseded vs. carrying-a-failure is unproven, so it is not skipped (#3530)."
        )
    return (
        f"ℹ️  run {run_id} sha {sha8} concluded `cancelled` with no failing job — a genuine supersession "
        "(the `ci-cd-deploy-<ref>` group evicted its pending Deploy), skipped as a non-verdict."
    )


def fetch_run_jobs(gh_json, repo: str, run_id) -> list[dict] | None:
    """The one impure step: `GET /actions/runs/{id}/jobs`, via the caller's own
    `gh` wrapper. Returns the jobs list, or None when the read failed.

    Impure I/O is injected (`gh_json`) rather than imported so this module stays
    offline-testable, and so the endpoint string lives in ONE place instead of
    once per reader.

    `per_page=100` rather than `--paginate`: on an OBJECT-returning endpoint
    `gh api --paginate` emits one JSON document per page, which `json.loads`
    rejects — the read would then look like a network failure and every cancelled
    run would go INDETERMINATE. A CI/CD run has 11 jobs; 100 is generous headroom
    for the single page this actually needs.
    """
    if not run_id:
        return None
    try:
        payload = gh_json(["api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"])
    except Exception:  # noqa: BLE001 — any gh/network/auth failure is INDETERMINATE, never SUPERSEDED
        return None
    if isinstance(payload, dict):
        jobs = payload.get("jobs")
        return jobs if isinstance(jobs, list) else None
    return payload if isinstance(payload, list) else None


def load_fixture_jobs(path: str) -> list[dict]:
    """The `jobs` array from a pinned `…/actions/runs/{id}/jobs` payload on disk."""
    with open(path) as fh:
        return json.load(fh)["jobs"]


if __name__ == "__main__":  # pragma: no cover - manual/debug CLI, and wait_pr_green.sh's
    # #3678 wiring: `diagnose-check <name> <startedAt> <completedAt>` needs the timeout
    # registry but must make ZERO `gh` calls (the pure-evaluator contract
    # `deploy/wait_pr_green.sh` and its tests hold this module to) — `ci_job_timeouts.py`
    # only reads local workflow YAML, never the network, so this stays safe to call from
    # inside `evaluate_checks_json`'s cancel branch.
    import os
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "diagnose-check":
        _SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
        if _SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, _SCRIPTS_DIR)
        import ci_job_timeouts  # noqa: E402 - after sys.path fix-up

        check_name, started_at, completed_at = sys.argv[2], sys.argv[3] or None, sys.argv[4] if len(sys.argv) > 4 else None
        timeouts = ci_job_timeouts.timeout_minutes_by_job_name()
        verdict = classify_cancelled_check(check_name, started_at, completed_at, timeouts)
        print(verdict)
        print(describe_cancelled_check(check_name, verdict), file=sys.stderr)
        sys.exit(0)
    print(__doc__)
