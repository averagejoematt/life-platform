#!/usr/bin/env python3
"""scripts/reconcile_child_guard.py — refuse to reject the CI/CD run that OWNS a merge's deploy (#5384).

THE INCIDENT (2026-10-26, Session CH; docs/INCIDENT_LOG.md)
-----------------------------------------------------------
PR #5383 merged at 3ead5f4ee. The reconcile bot's `chore(reconcile): regenerate derived
artifacts after merge [skip-reconcile]` commit (e43171b26) then minted a SECOND CI/CD run.
The land skill said "reject any gated run whose sha is an ancestor of main", so the merge's
run 40263440771 was rejected at the production gate. But the reconcile run's Plan had
already logged `deploy-base: this push is a reconcile commit and the run at its parent is
alive or deployed; that run ships this tree` (#4250, `check_deploy_deadman.py --deploy-base`)
and skipped its own Deploy. Net: the parent's run was rejected, the child deferred to it,
and nothing deployed until a manual `gh run rerun` + approve (~20 min).

Two rules disagreed — "ancestor of main -> reject" and "the parent's run owns the deploy of
a reconcile child's tree". This module is the structural half of the fix: the reject path
asks it first. A run is PROTECTED when a NEWER CI/CD run on main exists whose head commit is
a reconcile commit (subject `chore(reconcile)` + `[skip-reconcile]`, the exact predicate
`check_deploy_deadman.RECONCILE_SUBJECT_PREFIX` / `RECONCILE_MARKER` use) whose single
PARENT is this run's head sha. Rejecting that run strands the merge, so
`deploy/reject_deployment.sh` refuses unless `--force-ancestor` is passed (a real merge train
where the parent run is genuinely superseded).

Exit codes (the #2753 three-way contract, read by deploy/reject_deployment.sh):
    0  CLEAR      — no reconcile child owns this run's deploy; the reject may proceed
    3  PROTECTED  — a reconcile child's Plan defers to this run; refuse, print the approve command
    2  INDETERMINATE — an API read failed; neither verdict is provable, so the caller refuses too
                   (the reject is irreversible; `--force-ancestor` is the explicit override)

THE OTHER HALF — THE STRANDED SHAPE (`stranded_reconcile_shape`, read by check_main_green.py)
When the reject already happened (a hand `gh api` call, an older script, a janitor), the
state it leaves is recognisable: the NEWEST run on main is a reconcile run that concluded
`success` with `Deploy` skipped, while the run at its PARENT concluded failure/cancelled
with Plan green and the deploy leg as the red job. That is not a green main — nothing
shipped. check_main_green names it and prints the one recovery command.

Usage:
    python3 scripts/reconcile_child_guard.py <run_id>
"""

from __future__ import annotations

import json
import subprocess
import sys

REPO = "averagejoematt/life-platform"
WORKFLOW = "ci-cd.yml"
BRANCH = "main"

# Kept equal to scripts/check_deploy_deadman.py's pair (that file owns the plan-side rule);
# tests/test_reconcile_child_guard_5384.py pins the equality so the two cannot drift.
RECONCILE_SUBJECT_PREFIX = "chore(reconcile)"
RECONCILE_MARKER = "[skip-reconcile]"

EXIT_CLEAR, EXIT_INDETERMINATE, EXIT_PROTECTED = 0, 2, 3

RUNS_PAGE = 100


def is_reconcile_subject(subject: str | None) -> bool:
    """The bot's commit subject: the prefix AND the marker, as `reconcile_push_parent` requires."""
    s = (subject or "").strip()
    return s.startswith(RECONCILE_SUBJECT_PREFIX) and RECONCILE_MARKER in s


def _subject(run: dict) -> str:
    return ((run.get("head_commit") or {}).get("message") or "").split("\n", 1)[0]


def find_reconcile_child(target: dict, runs: list[dict], parents_of) -> dict | None:
    """The newest CI/CD run on main that is the reconcile child of `target`, or None. Pure
    given `parents_of(sha) -> list[str]` (the commit's parent shas; raises on a failed read).

    `runs` are workflow-run dicts as the REST API returns them (`id`, `head_sha`,
    `created_at`, `head_commit.message`). The subject on the run is only a PRE-FILTER; the
    verdict is the commit's real parent list, so a hand-pushed commit that merely carries the
    marker, or a reconcile commit stacked on a different parent, never protects a run."""
    target_sha = target.get("head_sha")
    if not target_sha:
        return None
    newer = [r for r in runs if r.get("id") != target.get("id") and str(r.get("created_at") or "") > str(target.get("created_at") or "")]
    for run in sorted(newer, key=lambda r: str(r.get("created_at") or ""), reverse=True):
        if run.get("head_sha") == target_sha or not is_reconcile_subject(_subject(run)):
            continue
        if parents_of(run["head_sha"]) == [target_sha]:
            return run
    return None


def refusal_message(run_id: str, child: dict) -> str:
    return (
        f"REFUSED (#5384): run {run_id} OWNS the deploy of a reconcile child's tree.\n"
        f"  Run {child.get('id')} (sha {(child.get('head_sha') or '')[:9]}) is the bot's reconcile commit on top of this run's\n"
        "  head. Its Plan logs `deploy-base: ... the run at its parent is alive or deployed; that run ships\n"
        "  this tree (#4250)` and SKIPS its own Deploy — rejecting this run strands the merge undeployed\n"
        "  (the 2026-10-26 incident: ~20 min dark until a rerun + approve).\n"
        f"  Approve the PARENT instead:   bash deploy/approve_deployment.sh {run_id}\n"
        "  A real merge train whose parent run is genuinely superseded: re-run with --force-ancestor."
    )


# ── the stranded shape (the post-hoc detector) ───────────────────────────────────

DEPLOY_JOBS = ("Deploy", "Deploy IAM (production gate)")
PLAN_JOB = "Plan deployments"


def _conclusion(jobs: list[dict], names: tuple[str, ...]) -> list[str | None]:
    return [j.get("conclusion") for j in jobs if j.get("name") in names]


def recovery_command(parent_run_id: object) -> str:
    return f"gh run rerun {parent_run_id} && bash deploy/approve_deployment.sh {parent_run_id}"


def stranded_reconcile_shape(runs: list[dict], jobs_for, parents_of) -> dict | None:
    """The stranded-reconcile shape, or None. Pure given `jobs_for(run) -> jobs|None` and
    `parents_of(sha) -> [parent shas]` (either may raise: the caller treats that as 'no claim').

    `runs` are `gh run list --json` dicts (`databaseId`, `headSha`, `status`, `conclusion`,
    `createdAt`, `displayTitle`). Every clause is load-bearing:
      * the NEWEST run is a completed `success` whose title is the reconcile subject — an older
        stranded pair that a later run has since re-deployed is history, not a live strand;
      * its own `Deploy` job concluded `skipped` (the #4250 deferral) — a reconcile run that
        deployed, or never had a Deploy decision, is not this shape;
      * the run at its single parent concluded `failure`/`cancelled` with Plan green and a
        deploy-leg job that failed/was cancelled — a parent that is red for a real validation
        failure is `check_main_green`'s ordinary red, not this."""
    ordered = sorted(runs, key=lambda r: str(r.get("createdAt") or ""), reverse=True)
    if not ordered:
        return None
    child = ordered[0]
    if child.get("status") != "completed" or child.get("conclusion") != "success":
        return None
    if not is_reconcile_subject(child.get("displayTitle")):
        return None
    child_jobs = jobs_for(child) or []
    if "skipped" not in _conclusion(child_jobs, ("Deploy",)):
        return None
    parents = parents_of(child["headSha"])
    if len(parents) != 1:
        return None
    parent = next((r for r in ordered[1:] if r.get("headSha") == parents[0]), None)
    if parent is None or parent.get("status") != "completed" or parent.get("conclusion") not in ("failure", "cancelled"):
        return None
    parent_jobs = jobs_for(parent) or []
    if _conclusion(parent_jobs, (PLAN_JOB,)) != ["success"]:
        return None
    if not any(c in ("failure", "cancelled") for c in _conclusion(parent_jobs, DEPLOY_JOBS)):
        return None
    return {"child": child, "parent": parent, "recovery": recovery_command(parent.get("databaseId"))}


# ── the impure half ──────────────────────────────────────────────────────────────


def _gh_json(args: list[str]):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def _parents_of(sha: str) -> list[str]:
    return [p["sha"] for p in _gh_json(["api", f"repos/{REPO}/commits/{sha}"]).get("parents") or []]


def check(run_id: str) -> tuple[int, str]:
    try:
        target = _gh_json(["api", f"repos/{REPO}/actions/runs/{run_id}"])
        if target.get("head_branch") != BRANCH:
            return EXIT_CLEAR, f"run {run_id} is not a {BRANCH} run — no reconcile child to protect."
        runs = _gh_json(["api", f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?branch={BRANCH}&per_page={RUNS_PAGE}"])["workflow_runs"]
        child = find_reconcile_child(target, runs, _parents_of)
    except Exception as e:  # noqa: BLE001 - an unreadable verdict is INDETERMINATE, never a silent CLEAR
        return EXIT_INDETERMINATE, (
            f"could not verify whether run {run_id} owns a reconcile child's deploy ({str(e)[:120]}) (#5384).\n"
            "  Refusing: a reject is irreversible. Re-run once the read recovers, or pass --force-ancestor."
        )
    if child is None:
        return EXIT_CLEAR, f"no newer reconcile child owns run {run_id}'s deploy."
    return EXIT_PROTECTED, refusal_message(run_id, child)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: reconcile_child_guard.py <run_id>", file=sys.stderr)
        return EXIT_INDETERMINATE
    code, message = check(args[0])
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
