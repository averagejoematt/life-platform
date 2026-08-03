#!/usr/bin/env python3
"""scripts/check_main_green.py — the /wrap green-main gate (#1327, stranded-aware per #1901).

A session may not close declaring victory over a red main it never looked at:
on 2026-07-18 a wrap wrote "main GREEN (1c641b6a)" while that sha's own push
run had concluded FAILURE. This gate makes the check mechanical.

#1901 taught it the two STRANDED DEPLOY states, which the #1327 version read
straight past:

  * **Stranded production approval** — a run sits at the `production` approval
    gate with `status=waiting`. Because ci-cd.yml sets
    `concurrency: cancel-in-progress: false`, every later run queues behind it
    (0 jobs, `pending`) — which reads exactly like the phantom-concurrency
    class (`reference_push_ci_silent_death`) but has the OPPOSITE fix.
    Tell: phantom = 0 jobs AND no other run in the group; stranded gate =
    0-job runs queued BEHIND an older run in `waiting`. (Observed 2026-07-28:
    run 30324990970 held the gate ~15h; the #1653 merge queued behind it and
    never started.)
  * **Stranded Plan (R8-ST6)** — the run FAILED, but the only red job is
    "Plan deployments" and "Deploy" was skipped, everything else green: the
    IAM-review gate is holding deploys until a pending `cdk_deploy.sh` runs
    from main. This is not an ordinary red — every subsequent merge's deploy
    strands too, invisibly, until the CDK deploy clears it.

#2052 adds the THIRD stranded state, which the two above cannot express:

  * **Phantom deploy wedge** — the run's `Deploy` job is blocked in the
    `ci-cd-deploy-<ref>` concurrency group by an entry that corresponds to no
    real run. Since the #2009 redesign this no longer presents as `0 jobs`:
    the run shows FIVE GREEN JOBS and sits `pending`, which reads as "waiting
    for approval" — but `pending_deployments` is empty and will stay empty,
    because GitHub evaluates concurrency BEFORE the environment rule, so the
    gate never opens and there is nothing to approve. Every tell documented
    for the older phantom class keys on "0 jobs" and is therefore now blind.
    Detection lives in `scripts/check_deploy_wedge.py` (it needs per-run JOB
    state, which `gh run list` does not carry); this gate consumes its verdict.
    Distinguishing it from the stranded-approval class above is NOT possible
    from a single run — the two are byte-identical — it turns entirely on
    whether any other in-flight run actually holds the deploy group.

Verdicts:
  * green                → exit 0
  * green + a YOUNG waiting run (< ~2h at the approval gate) → exit 0 with a
    notice (a manual production approval pending is the pipeline's normal
    post-merge state, not an incident — until it ages past the threshold)
  * stranded-approval / stranded-plan / stranded-deploy-wedge / red /
    no-verdict → print the decode contract and exit 1. The wrap may proceed
    ONLY by writing the one-line decode into the handover (e.g. `**Main:**
    stranded — run 303… waiting at the production gate since 03:06Z, #1901
    class`) and re-running with --decoded to acknowledge.

A phantom deploy wedge outranks every other verdict INCLUDING green: while it
holds, no deploy can start, so the last completed run's success is a stale
fact about a pipeline that is no longer able to ship.

Cancelled runs are skipped (superseded pushes carry no signal); the newest
run that actually finished is the completed-run verdict.

Usage:
  python3 scripts/check_main_green.py             # gate: not-green main → exit 1
  python3 scripts/check_main_green.py --decoded   # operator wrote the decode line → exit 0 with reminder
"""

import json
import subprocess
import sys
from datetime import datetime, timezone

# A run parked at the production approval gate is normal right after a merge
# (the approval is manual by design) — it becomes an incident when it ages.
STRANDED_WAIT_HOURS = 2.0

# Verdict kinds (module constants so tests and consumers share the vocabulary).
GREEN = "green"
RED = "red"
STRANDED_APPROVAL = "stranded-approval"
STRANDED_PLAN = "stranded-plan"
STRANDED_DEPLOY_WEDGE = "stranded-deploy-wedge"
NO_VERDICT = "no-verdict"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_hours(run: dict, now: datetime) -> float | None:
    created = _parse_iso(run.get("createdAt"))
    if created is None:
        return None
    return (now - created).total_seconds() / 3600.0


def latest_completed_run(runs: list[dict]) -> dict | None:
    """Newest non-cancelled completed run (the completed-run verdict).

    Pure — unit-tested offline. `runs` is newest-first, as `gh run list`
    returns them. Cancelled runs are superseded pushes, not verdicts; skip.
    """
    for r in runs:
        if r.get("status") != "completed":
            continue
        if r.get("conclusion") == "cancelled":
            continue
        return r
    return None


def latest_main_conclusion(runs: list[dict]) -> tuple[str | None, str | None]:
    """(conclusion, headSha) of the newest non-cancelled completed run.

    Kept as the #1327 public surface (tests/test_unred_main_1327.py).
    """
    run = latest_completed_run(runs)
    if run is None:
        return None, None
    return run.get("conclusion"), run.get("headSha")


def waiting_runs(runs: list[dict]) -> list[dict]:
    """Runs parked at an environment approval gate (`status=waiting`)."""
    return [r for r in runs if r.get("status") == "waiting"]


def _job_shape(jobs: list[dict]) -> tuple[bool, bool, bool]:
    """(plan_failed, deploy_skipped, other_job_failed) for a run's job list."""
    plan_failed = deploy_skipped = other_failed = False
    for j in jobs:
        name = j.get("name", "")
        concl = j.get("conclusion")
        if name.startswith("Plan"):
            plan_failed = plan_failed or concl == "failure"
        elif name == "Deploy":
            deploy_skipped = deploy_skipped or concl == "skipped"
        elif concl == "failure":
            other_failed = True
    return plan_failed, deploy_skipped, other_failed


def is_plan_red_deploy_skipped(jobs: list[dict]) -> bool:
    """True iff the failure is the PURE R8-ST6 stranded-Plan shape:

    "Plan deployments" failed, "Deploy" was skipped, and NO other job failed
    (the "Notify failure" job succeeding is part of the shape, not a failure).
    A run where Unit Tests (or anything else) also failed is an ordinary red —
    it needs a fix, not just the pending CDK deploy — though its deploy path
    is STILL stranded (classify_pipeline carries that as `deploy_also_stranded`).
    """
    plan_failed, deploy_skipped, other_failed = _job_shape(jobs)
    return plan_failed and deploy_skipped and not other_failed


def classify_pipeline(
    runs: list[dict],
    latest_failure_jobs: list[dict] | None = None,
    now: datetime | None = None,
    deploy_wedge: dict | None = None,
) -> dict:
    """Classify main's pipeline state. Pure — fixture-tested offline (#1901/#2052).

    Returns {"kind", "sha", "run", "waiting", "overdue_waiting"} where kind is one of
    GREEN / RED / STRANDED_APPROVAL / STRANDED_PLAN / STRANDED_DEPLOY_WEDGE / NO_VERDICT.

    `deploy_wedge` is the verdict dict from `check_deploy_wedge.classify_fleet` (the
    caller supplies it — this gate reads `gh run list`, which carries no per-run job
    state, so it cannot detect the wedge itself).

    Precedence: a phantom deploy wedge outranks everything — while it holds, NO deploy
    can start and no approval is even possible, so a green completed run is a stale
    fact. Then an OVERDUE waiting run (it blocks every later run regardless of the last
    completed verdict). A young waiting run does not change the verdict — it is
    reported alongside it.
    """
    now = now or datetime.now(timezone.utc)
    waiting = waiting_runs(runs)
    overdue = [r for r in waiting if (_age_hours(r, now) or 0.0) >= STRANDED_WAIT_HOURS]

    plan_failed = deploy_skipped = other_failed = False
    if latest_failure_jobs:
        plan_failed, deploy_skipped, other_failed = _job_shape(latest_failure_jobs)

    wedged = [v for v in (deploy_wedge or {}).get("verdicts", []) if v.get("kind") == "phantom-wedge"]

    completed = latest_completed_run(runs)
    if wedged:
        kind = STRANDED_DEPLOY_WEDGE
    elif overdue:
        kind = STRANDED_APPROVAL
    elif completed is None:
        kind = NO_VERDICT
    elif completed.get("conclusion") == "success":
        kind = GREEN
    elif completed.get("conclusion") == "failure" and plan_failed and deploy_skipped and not other_failed:
        kind = STRANDED_PLAN
    else:
        kind = RED

    return {
        "kind": kind,
        "sha": (completed or {}).get("headSha"),
        "run": completed,
        "waiting": waiting,
        "overdue_waiting": overdue,
        "wedged": wedged,
        # An ordinary red can STILL have a stranded deploy path (Plan red +
        # Deploy skipped alongside another failure, e.g. live 2026-08-02).
        "deploy_also_stranded": kind == RED and plan_failed and deploy_skipped,
    }


def _fmt_run(r: dict, now: datetime) -> str:
    age = _age_hours(r, now)
    age_s = f"{age:.1f}h" if age is not None else "?"
    return f"run {r.get('databaseId')} sha {(r.get('headSha') or '')[:8]} (waiting {age_s})"


def render(state: dict, now: datetime | None = None) -> tuple[int, str]:
    """(exit_code, message) for a classified pipeline state. Pure."""
    now = now or datetime.now(timezone.utc)
    kind = state["kind"]
    sha8 = (state.get("sha") or "")[:8]
    lines: list[str] = []

    if kind == STRANDED_DEPLOY_WEDGE:
        lines.append("🛑 PHANTOM DEPLOY WEDGE (#2052 class) — main's deploy path is dead; a green completed run is a stale fact:")
        for v in state.get("wedged", []):
            lines.append(
                f"   run {v.get('run_id')} sha {v.get('sha')} — Deploy blocked {v.get('blocked_minutes')}m with NOTHING holding the deploy group."
            )
        lines.append(
            "   This is NOT the #1901 stranded-approval class even though it looks identical:\n"
            "   `pending_deployments` is EMPTY and stays empty — GitHub evaluates the job's\n"
            "   `concurrency` BEFORE the `production` environment rule, so the gate never opens\n"
            "   and there is nothing to approve. Waiting for it is waiting forever. Since #2009\n"
            "   moved the group onto the `deploy` job, the run shows five GREEN jobs, so every\n"
            "   documented '0 jobs' tell for this class is blind.\n"
            "   Recovery: `python3 scripts/check_deploy_wedge.py --recover` (cancels the wedged\n"
            "   run, re-dispatches ci-cd.yml with deploy_all=true — a dispatch carries no push\n"
            "   diff, so change detection would otherwise deploy nothing). Do NOT salt the\n"
            "   concurrency group: three salts failed across recurrences 1-3 (CONVENTIONS §4d)."
        )
        return 1, "\n".join(lines)

    if kind == STRANDED_APPROVAL:
        lines.append("🛑 STRANDED PRODUCTION APPROVAL (#1901 class) — main is NOT green and NOT ordinarily red:")
        for r in state["overdue_waiting"]:
            lines.append(f"   {_fmt_run(r, now)} is parked at the `production` approval gate.")
        lines.append(
            "   Every later CI/CD run queues behind it (status=pending, 0 jobs) because\n"
            "   concurrency is cancel-in-progress:false. This is NOT the phantom-concurrency\n"
            "   class (reference_push_ci_silent_death) — tell: phantom = 0 jobs AND no other\n"
            "   run in the group; stranded gate = 0-job runs queued BEHIND an older `waiting` run.\n"
            "   Recovery: action the gate — `bash deploy/approve_deployment.sh` (approve/reject\n"
            "   on Matthew's say-so). Do NOT cancel the waiting run: a cancelled run STRANDS its\n"
            "   deploy → recover with a `deploy_all=true` workflow_dispatch of ci-cd.yml."
        )
        return 1, "\n".join(lines)

    if kind == STRANDED_PLAN:
        lines.append(
            f"🛑 STRANDED DEPLOY — R8-ST6 Plan-red at {sha8} (#1901 class), not an ordinary red:\n"
            "   Only the `Plan deployments` job failed (the IAM-review gate) and `Deploy` was\n"
            "   SKIPPED; lint/tests are green. Every ci-cd deploy strands until the pending IAM\n"
            "   change deploys from main (`bash deploy/cdk_deploy.sh <Stack>` — needs Matthew's\n"
            "   in-the-moment ask), then recover the stranded fleet half with a `deploy_all=true`\n"
            "   workflow_dispatch of ci-cd.yml."
        )
    elif kind == GREEN:
        lines.append(f"✅ main GREEN — latest completed CI/CD run ({sha8}) succeeded.")
    elif kind == NO_VERDICT:
        lines.append("⚠️  no completed non-cancelled CI/CD run found on main — wait for the in-flight run or decode manually.")
    else:
        concl = ((state.get("run") or {}).get("conclusion") or "red").upper()
        lines.append(f"❌ main is {concl} at {sha8}.")
        if state.get("deploy_also_stranded"):
            lines.append(
                "   ⚠️  AND the deploy path is stranded (#1901): `Plan deployments` failed and\n"
                "   `Deploy` was skipped alongside the other red — fixing the failing job alone\n"
                "   will not deploy anything until the R8-ST6 Plan-red clears (pending\n"
                "   `bash deploy/cdk_deploy.sh <Stack>`, then a `deploy_all=true` dispatch)."
            )

    # Young waiting runs ride along as a notice on any verdict.
    for r in state["waiting"]:
        if r in state["overdue_waiting"]:
            continue
        lines.append(
            f"ℹ️  {_fmt_run(r, now)} is awaiting production approval (normal post-merge; "
            f"becomes the #1901 stranded class at {STRANDED_WAIT_HOURS:g}h — action it via deploy/approve_deployment.sh)."
        )

    return (0 if kind == GREEN else 1), "\n".join(lines)


def _gh_json(args: list[str]):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def main() -> int:
    decoded = "--decoded" in sys.argv
    try:
        runs = _gh_json(
            [
                "run",
                "list",
                "--branch",
                "main",
                "--workflow",
                "CI/CD",
                "--limit",
                "20",
                "--json",
                "status,conclusion,headSha,databaseId,createdAt",
            ]
        )
    except Exception as e:
        print(f"⚠️  check_main_green: could not read run list ({e}) — decode manually (gh run list --branch main)")
        return 1

    # Jobs are only needed to split ordinary red from the R8-ST6 stranded-Plan shape.
    jobs = None
    completed = latest_completed_run(runs)
    if completed is not None and completed.get("conclusion") == "failure" and completed.get("databaseId"):
        try:
            jobs = _gh_json(["run", "view", str(completed["databaseId"]), "--json", "jobs"]).get("jobs")
        except Exception as e:
            print(f"⚠️  check_main_green: could not read jobs for run {completed['databaseId']} ({e}) — treating as ordinary red")

    # #2052: the phantom deploy wedge needs per-run JOB state, which `gh run list`
    # does not carry. Best-effort — a detector failure must never turn a readable
    # green/red verdict into a hard error, so it degrades to "wedge unknown".
    wedge = None
    try:
        import check_deploy_wedge  # noqa: PLC0415 - optional, same directory

        in_flight, jobs_by_run, pending_by_run = check_deploy_wedge.collect()
        wedge = check_deploy_wedge.classify_fleet(in_flight, jobs_by_run, pending_by_run)
    except Exception as e:  # noqa: BLE001
        print(
            f"⚠️  check_main_green: deploy-wedge detection unavailable ({e}) — run scripts/check_deploy_wedge.py by hand if a deploy looks stuck."
        )

    state = classify_pipeline(runs, latest_failure_jobs=jobs, deploy_wedge=wedge)
    code, message = render(state)
    print(message)
    if code == 0:
        return 0
    if decoded:
        print("   --decoded acknowledged: the handover MUST carry the one-line `**Main:** …` decode.")
        return 0
    print(
        "   The wrap may not declare 'main GREEN'. Either fix it, or write the decode line\n"
        "   into the handover — `**Main:** <stranded|red> — <one-line cause>` — and re-run with --decoded."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
