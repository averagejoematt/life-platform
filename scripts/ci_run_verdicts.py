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
                            concluded `failure` — nothing had gone wrong when the
                            cancel landed. Safe to skip: it carries no verdict.
  cancelled-carries-failure some job concluded `failure`, OR some step concluded
                            `failure` inside a job that was later cancelled (the
                            failure happened BEFORE the cancel). This is a RED.
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
`conclusion`, `steps[].conclusion` — so either source works.
"""

from __future__ import annotations

import json

# The three things a `cancelled` rollup can mean. Module constants so both
# readers (and their tests) share ONE vocabulary rather than each matching on a
# phrase — the #3199 lesson: every phrase-matched classifier in this repo has
# failed in the field.
CANCELLED_SUPERSEDED = "cancelled-superseded"
CANCELLED_CARRIES_FAILURE = "cancelled-carries-failure"
CANCELLED_INDETERMINATE = "cancelled-indeterminate"

# The states that let a reader skip the run without looking further. Deliberately
# a one-element set rather than "not CARRIES_FAILURE": an INDETERMINATE read must
# fall on the NOT-skippable side, so a `gh` hiccup can never manufacture a green.
CANCELLED_SKIPPABLE = frozenset({CANCELLED_SUPERSEDED})


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


def classify_cancelled_run(jobs: list[dict] | None) -> str:
    """One of the three CANCELLED_* constants for a run whose rollup is `cancelled`.

    `jobs is None` means the job list could not be read — INDETERMINATE, never
    SUPERSEDED. An EMPTY list is different and is treated the same way: a
    completed run always has jobs, so zero of them means the read told us
    nothing.
    """
    if not jobs:
        return CANCELLED_INDETERMINATE
    return CANCELLED_CARRIES_FAILURE if failing_job_names(jobs) else CANCELLED_SUPERSEDED


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
