#!/usr/bin/env python3
"""scripts/find_test_verdict_owner.py — one full-suite verdict per pushed sha (#4252).

NOT a gate, and deliberately not named like one (`check_*`, `verify_*`, `*_guard`,
`*_gate`, `*_audit` are the shapes `scripts/gate_census.py` recognises). It mints no
verdict and never exits non-zero. It answers one question for ci-cd.yml's `test` job:
does ANOTHER CI/CD run already own the `test / Unit Tests` verdict for the tree this
run is about to test?

WHY THE QUESTION EXISTS
-----------------------
ci-cd.yml's `reconcile` job does not test the pushed commit. It checks out the BRANCH
TIP (`git checkout -B main origin/main`), and `build_sha` — the sha every downstream
job checks out — is that tip, or the reconcile commit this run pushed on top of it.
When several pushes land together (a merge train, or a merge followed by its own
reconcile commit), every one of their runs converges on the SAME tip and runs the
same 33-minute coverage pass on the same sha.

Measured on the 45 `test / Unit Tests` jobs of the 54 completed push runs before this
change (2026-09-27 05:46Z → 23:02Z; the checkout sha read from each job's own log):
45 jobs tested only 21 distinct shas. 24 were byte-identical repeats, ~770 runner-
minutes. Example: 62bd98a71 was unit-tested FOUR times, by the runs for 75d3d5fc6,
7d35a2f09, 76a4a554f and 62bd98a71 itself.

THE RULE
--------
A run SKIPS its unit-test pass only when all of these hold:

  1. the event is `push` (a `workflow_dispatch` always tests);
  2. `build_sha != GITHUB_SHA` — this run is testing a commit that is NOT its own
     head, i.e. a later push (or this run's own reconcile commit);
  3. a `push` run of ci-cd.yml exists whose `head_sha == build_sha`. That run's
     `reconcile` checks out the same tip, so it tests the same sha, and its rollup
     is what every reader of that sha's status sees;
  4. that owner has not already ENDED without a Unit Tests verdict (completed with
     the job skipped or cancelled — e.g. its own reconcile job failed).

Condition 3 is load-bearing, not decoration: a push made with GITHUB_TOKEN mints no
workflow run. Measured: 440eabc46 (#4350, a Dependabot auto-merge) has no CI/CD run
at all, and the only unit-test verdict it ever got came from 306e29780's run, whose
reconcile found it as the tip. Under this rule that run finds no owner and tests it,
exactly as before.

WHAT THIS IS NOT
----------------
It is not a merge-ref / PR-run dedup ("the PR already tested this tree"). That was
measured and rejected: across the last 42 PR squash-merges to main, the PR's latest
pr-checks run had tested the SAME base the squash landed on in only 5 (the base had
moved in 37 — a reconcile commit alone moves it). And the moved-base case is exactly
what the post-merge pass exists for (#4304 + #4317: two green PRs, main red after
both). Same-sha identity needs no tree reasoning and cannot mistake one tree for
another.

FAIL-OPEN TO TESTING
--------------------
Any API error, an unparseable response, or a missing token yields "no owner" and the
run tests itself. The only thing this script can do wrong is make a run test when it
did not need to.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass

WORKFLOW_FILE = "ci-cd.yml"
UNIT_TESTS_JOB = "test / Unit Tests"
# A run still in one of these states will reach the unit-test job (or end visibly red).
_LIVE_STATUSES = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
# A completed owner counts only if its Unit Tests job actually reached a verdict.
_VERDICT_CONCLUSIONS = frozenset({"success", "failure"})
# This run's own reconcile push takes a few seconds to mint its run. Poll only when
# no owner is found; a GITHUB_TOKEN push never mints one, so the wait is bounded.
POLL_ATTEMPTS = 6
POLL_SECONDS = 15


@dataclass(frozen=True)
class RunInfo:
    run_id: int
    head_sha: str
    event: str
    path: str
    status: str
    unit_tests_conclusion: str | None = None  # read only for completed runs


def decide(*, event: str, head_sha: str, build_sha: str, run_id: int, candidates: list[RunInfo]) -> tuple[int | None, str]:
    """(owner_run_id or None, reason). Pure. None means THIS run tests."""
    if event != "push":
        return None, f"event is {event!r}, not push — this run tests"
    if not build_sha or not head_sha:
        return None, "build_sha or head_sha missing — this run tests"
    if build_sha == head_sha:
        return None, f"build_sha {build_sha[:9]} is this run's own head — this run owns its verdict"
    owners = sorted(
        (
            c
            for c in candidates
            if c.head_sha == build_sha and c.event == "push" and c.path.endswith(f"/{WORKFLOW_FILE}") and c.run_id != run_id
        ),
        key=lambda c: c.run_id,
    )
    if not owners:
        return None, (f"no push run of {WORKFLOW_FILE} exists for {build_sha[:9]} " "(a GITHUB_TOKEN push mints none) — this run tests it")
    for owner in owners:
        if owner.status in _LIVE_STATUSES:
            return owner.run_id, f"run {owner.run_id} (push of {build_sha[:9]}, {owner.status}) owns the verdict"
        if owner.status == "completed" and owner.unit_tests_conclusion in _VERDICT_CONCLUSIONS:
            return owner.run_id, (
                f"run {owner.run_id} (push of {build_sha[:9]}) already concluded " f"{UNIT_TESTS_JOB} = {owner.unit_tests_conclusion}"
            )
    return None, (f"every push run for {build_sha[:9]} ended without a {UNIT_TESTS_JOB} verdict — this run tests it")


def _gh_json(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def fetch_candidates(repo: str, build_sha: str) -> list[RunInfo]:
    data = _gh_json(f"repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?head_sha={build_sha}&event=push&per_page=20")
    runs: list[RunInfo] = []
    for r in data.get("workflow_runs") or []:
        concl = None
        if r.get("status") == "completed":
            jobs = _gh_json(f"repos/{repo}/actions/runs/{r['id']}/jobs?per_page=100").get("jobs") or []
            concl = next((j.get("conclusion") for j in jobs if j.get("name") == UNIT_TESTS_JOB), None)
        runs.append(
            RunInfo(
                run_id=int(r["id"]),
                head_sha=r.get("head_sha") or "",
                event=r.get("event") or "",
                path=r.get("path") or "",
                status=r.get("status") or "",
                unit_tests_conclusion=concl,
            )
        )
    return runs


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    head_sha = os.environ.get("GITHUB_SHA", "")
    build_sha = os.environ.get("BUILD_SHA", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = int(os.environ.get("GITHUB_RUN_ID", "0") or 0)

    owner: int | None = None
    reason = ""
    try:
        needs_lookup = event == "push" and bool(build_sha) and build_sha != head_sha
        attempts = max(1, POLL_ATTEMPTS) if needs_lookup else 1
        for attempt in range(attempts):
            candidates = fetch_candidates(repo, build_sha) if needs_lookup else []
            owner, reason = decide(event=event, head_sha=head_sha, build_sha=build_sha, run_id=run_id, candidates=candidates)
            if owner is not None or attempt == attempts - 1:
                break
            time.sleep(POLL_SECONDS)
    except Exception as exc:  # fail-open to testing, by design
        owner, reason = None, f"lookup failed ({exc.__class__.__name__}: {exc}) — this run tests"

    verdict = "SKIP (owned elsewhere)" if owner else "RUN"
    line = f"{UNIT_TESTS_JOB} for {build_sha[:9] or '?'}: {verdict} — {reason}"
    print(line)
    for var, text in (
        ("GITHUB_OUTPUT", f"owner_run={owner or ''}\n"),
        ("GITHUB_STEP_SUMMARY", f"### Unit-test verdict owner (#4252)\n{line}\n"),
    ):
        dest = os.environ.get(var)
        if dest:
            with open(dest, "a", encoding="utf-8") as fh:
                fh.write(text)
    if owner and repo:
        print(f"owner: https://github.com/{repo}/actions/runs/{owner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
