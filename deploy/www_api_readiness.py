#!/usr/bin/env python3
"""deploy/www_api_readiness.py — both site deploys wait for the Site API they read, then resume on their own.

THE INCIDENT (2026-11-12, run 43124939822). #5827 changed the Site API (CR2_PUBLIC on, so the
already-registered /api/coach_room_words starts answering 200) and the v9 build in ONE merge. The push
started web-preview-deploy.yml at once; the Site API code only ships through CI's fleet deploy (or a
laptop deploy/deploy_site_api.sh), and that run was held at Plan by an OWNER-REQUIRED IAM diff. So the
v9 root deploy exported its snapshot from, and smoke-tested against, the OLD Site API: the live-route
sweep read /api/coach_room_words 404, smoke went red, the rollback was declined (the failing surface
was `api`, which a site revert cannot cure) and the run stayed red until a manual deploy_site_api.sh
(01:05Z) and a re-dispatch (run 43132127307). A route probe would not have caught it — the route
existed; a flag in lambdas/common/narrative_allowlist.py flipped — and a sleep cannot outwait an IAM
gate.

THE SIGNAL. Every Lambda bundle carries the commit it was built from (build_info.json git_sha, #2377).
The commit the Site API OWES is derived, never listed: scripts/check_deploy_deadman.collect_owed_commits
— the newest commit on this checkout touching the Site API handler, any shared lambdas/ module or any
bundled config path, the same answer the nightly stale-Lambda dead-man uses. The site is READY when the
live bundle's commit contains the owed one (deploy/bundle_ancestry.classify: SAME, or the owed commit is
an ancestor of live). Behind or diverged is NOT READY. A bundle with no fingerprint, or a sha this
checkout cannot resolve, is UNVERIFIED and proceeds with a warning — the deploy-path posture since #2377
(an unverifiable deploy must be visible, not blocked); the smoke gate still judges it.

TWO TARGETS, ONE DECISION. The legacy site/** pipeline (site-deploy.yml — /coaching/ and every other kept
shell) has the same exposure: its pages fetch, and its smoke + visual sweeps judge, the same live Site API,
and before this gate it relied only on the hand-maintained route list in deploy/api_deploy_sequencing.json
(which cannot see a flag flip on a registered route — the incident's exact shape). It runs the SAME `check`
and defers the same way; `resume` walks both workflows' run histories (TARGETS) and re-dispatches each one
whose newest decisive run is a deferral. The route registry stays as the secondary line (PR-time advisory +
the smoke/visual 404 downgrade for an UNVERIFIED or break-glass run) — docs/CONVENTIONS.md §4b.

THE POLICY (defer, never wait). A not-ready v9 run skips its build/sync and runs the `deferred` job: a
step summary, a warning annotation and one SNS line. Nothing is synced, so nothing can roll back; a real
smoke/visual failure on a ready run still rolls back exactly as before. The run is RESUMED by
`resume`, invoked from web-deploy-resume.yml (on every CI/CD completion, and on a
schedule as the backstop) and from the laptop deploy paths (deploy_site_api.sh, deploy_fleet.sh). It
dispatches ONE deploy per target whose newest decisive run is a deferral, once the API is ready. No
deadlock with CI's production gate: CI never waits on the site and the site never waits on CI — it
defers and is resumed by whichever API deploy lands. A deferral still outstanding after
STALE_DEFERRAL_HOURS reds the resume run (the dead-man) — timed from the FIRST deferral of the unbroken
streak, so a stream of merges each deferring behind the same stuck API cannot keep resetting the clock.

Subcommands:
  check            web-preview-deploy.yml / site-deploy.yml `api-readiness` job → ready=true|false (+verdict/reason) in
                   $GITHUB_OUTPUT. WWW_API_READINESS=skip (dispatch-only break-glass) → ready=true.
  notify-deferred  the `deferred` job (--target v9|site) → step summary + SNS (a failed publish fails the job).
  resume           dispatch each deferred deploy once the API is ready (--target narrows); exit 1 on a stale deferral.

Exit: 0 decided (either way) · 1 error / stale deferral · the check REFUSES a shallow clone (exit 1):
in a depth-1 checkout `git log -1 -- <paths>` answers HEAD for everything and ancestry is unresolvable,
which would turn the gate into a silent UNVERIFIED pass.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from deploy import bundle_ancestry, www_owned_paths  # noqa: E402
from scripts import check_deploy_deadman  # noqa: E402

GH_REPO = "averagejoematt/life-platform"
WORKFLOW = "web-preview-deploy.yml"
LAMBDA_MAP = os.path.join(REPO, "ci", "lambda_map.json")
#: The Site API's handler — the key the function name is DERIVED from (ci/lambda_map.json).
SITE_API_HANDLER = "lambdas/web/site_api_lambda.py"

# Job display names in web-preview-deploy.yml — the run-history interface `resume` reads.
# tests/test_www_api_readiness.py pins all three against the workflow file.
DEFERRED_JOB = "Deferred: the Site API is not serving this commit's code yet"
DEPLOY_JOB = "Live snapshot → build → sync to the resolved target"
ROOT_SMOKE_JOB = "Site smoke test (root deploy)"

# The legacy site/** pipeline's job display names (site-deploy.yml) — pinned the same way.
SITE_WORKFLOW = "site-deploy.yml"
SITE_DEFERRED_JOB = "Deferred: the Site API is not serving this commit's code yet"
SITE_DEPLOY_JOB = "Deploy public site"
SITE_SMOKE_JOB = "Site smoke test"


@dataclass(frozen=True)
class Target:
    """One production deploy path that reads the live Site API and so defers behind it."""

    key: str
    workflow: str
    label: str
    deferred_job: str
    deploy_job: str
    smoke_job: str
    #: True: a deploy-job success whose smoke never ran is NOT a deploy. site-deploy.yml's deploy job
    #: succeeds as a no-op when superseded (its smoke is skipped); v9 needs smoke only at the root.
    smoke_always: bool


V9 = Target("v9", WORKFLOW, "v9 deploy", DEFERRED_JOB, DEPLOY_JOB, ROOT_SMOKE_JOB, smoke_always=False)
SITE = Target("site", SITE_WORKFLOW, "site/** deploy", SITE_DEFERRED_JOB, SITE_DEPLOY_JOB, SITE_SMOKE_JOB, smoke_always=True)
TARGETS = {t.key: t for t in (V9, SITE)}

READY, NOT_READY, UNVERIFIED, BREAK_GLASS = "ready", "not-ready", "unverified", "break-glass"
#: A deferral older than this with no resume reds the resume run. CI deploys minutes after a green
#: Plan (ADR-158); the long pole is an owner reading an IAM diff, which the deploy dead-man allows 4 h
#: (check_deploy_deadman.DEADLINE_HOURS). Twice that, so this pages after the deploy dead-man has.
STALE_DEFERRAL_HOURS = 2 * check_deploy_deadman.DEADLINE_HOURS
MAX_RUNS = 30
IN_FLIGHT_STATUSES = ("queued", "in_progress", "waiting", "pending", "requested")


# ── the readiness decision (pure) ───────────────────────────────────────────────────────────────
def decide(live_sha: str | None, owed_sha: str | None, is_ancestor=None) -> tuple[str, str]:
    """(state, reason). Pure given `is_ancestor` (default: git in this checkout) — the incident replays offline."""
    verdict = bundle_ancestry.classify(live_sha, owed_sha, is_ancestor=is_ancestor or bundle_ancestry.git_is_ancestor)
    live, owed = (live_sha or "none")[:8], (owed_sha or "none")[:8]
    if verdict in (bundle_ancestry.SAME, bundle_ancestry.STALE):
        return READY, f"the live Site API ({live}) contains the commit it owes ({owed})"
    if verdict == bundle_ancestry.FAST_FORWARD:
        return NOT_READY, f"the live Site API ({live}) is BEHIND the commit it owes ({owed}) — its code deploy has not landed"
    if verdict == bundle_ancestry.DIVERGED:
        return NOT_READY, f"the live Site API ({live}) has DIVERGED from main's owed commit ({owed}) — deployed from off main"
    return UNVERIFIED, f"cannot verify the live Site API ({live}) against the owed commit ({owed}) — proceeding unverified"


def site_api_function(lambda_map: str = LAMBDA_MAP) -> tuple[str, str]:
    """(function name, region) for SITE_API_HANDLER, read from ci/lambda_map.json."""
    with open(lambda_map, encoding="utf-8") as f:
        row = json.load(f)["lambdas"][SITE_API_HANDLER]
    return row["function"], row.get("region") or os.environ.get("AWS_REGION") or "us-west-2"


def is_shallow() -> bool:
    out = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=REPO, capture_output=True, text=True, timeout=30)
    return out.stdout.strip() == "true"


def evaluate() -> dict:
    """Read the owed commit (git) and the live one (AWS, read-only) and decide."""
    fn, region = site_api_function()
    owed = check_deploy_deadman.collect_owed_commits(LAMBDA_MAP, only={fn}).get(fn)
    owed_sha = owed[0] if owed else None
    live_sha = check_deploy_deadman.collect_deployed_shas({fn: region}).get(fn)
    state, reason = decide(live_sha, owed_sha)
    return {"function": fn, "state": state, "reason": reason, "live_sha": live_sha or "", "owed_sha": owed_sha or ""}


# ── resume: which run is decisive? (pure over the run history) ──────────────────────────────────
def classify_run(run: dict, jobs: list[dict], live_at_root: bool, target: Target = V9) -> str:
    """'in-flight' | 'deferred' | 'deployed' | 'other' for one run of `target`'s workflow."""
    if run.get("status") in IN_FLIGHT_STATUSES:
        return "in-flight"
    by_name = {j.get("name"): j.get("conclusion") for j in jobs}
    if by_name.get(target.deferred_job) in ("success", "failure"):  # a failed SNS publish is still a deferral
        return "deferred"
    need_smoke = target.smoke_always or live_at_root
    if by_name.get(target.deploy_job) == "success" and (not need_smoke or by_name.get(target.smoke_job) not in (None, "skipped")):
        return "deployed"
    return "other"  # refused dispatch, failed export, a superseded no-op, a preview run after the cut-over


classify_v9_run = classify_run  # the #5844 name


def outstanding_deferral(runs: list[dict], jobs_for, live_at_root: bool, target: Target = V9) -> tuple[str, dict | None]:
    """Walk newest → oldest to the first decisive run. ('deferred', run) means a resume is owed."""
    for run in runs[:MAX_RUNS]:
        kind = classify_run(run, jobs_for(run), live_at_root, target)
        if kind in ("in-flight", "deferred", "deployed"):
            return kind, run
    return "none", None


def first_deferral_of_streak(runs: list[dict], jobs_for, live_at_root: bool, target: Target = V9) -> dict | None:
    """The OLDEST deferral since the last real deploy — where the dead-man's clock starts."""
    first = None
    for run in runs[:MAX_RUNS]:
        kind = classify_run(run, jobs_for(run), live_at_root, target)
        if kind == "deployed":
            break
        if kind == "deferred":
            first = run
    return first


def _gh_json(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def _run_age_hours(run: dict, now: datetime) -> float:
    at = datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
    return (now - at).total_seconds() / 3600.0


# ── subcommands ─────────────────────────────────────────────────────────────────────────────────
def _emit(pairs: dict) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            for k, v in pairs.items():
                fh.write(f"{k}={str(v).replace(chr(10), ' ')}\n")


def _summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def cmd_check() -> int:
    if (os.environ.get("WWW_API_READINESS") or "").strip() == "skip":
        reason = "break-glass: WWW_API_READINESS=skip (dispatch input api_readiness=skip) — building against whatever Site API is live"
        print(f"::warning title=Site API readiness skipped::{reason}")
        _emit({"ready": "true", "state": BREAK_GLASS, "reason": reason})
        return 0
    if is_shallow():
        print(
            "::error title=Site API readiness needs full history::a shallow checkout cannot derive the owed commit — checkout with fetch-depth: 0"
        )
        return 1
    r = evaluate()
    ready = r["state"] in (READY, UNVERIFIED)
    print(f"www_api_readiness: {r['function']}: {r['state']} — {r['reason']}")
    if r["state"] == UNVERIFIED:
        print(f"::warning title=Site API readiness unverified::{r['reason']}")
    _emit({"ready": "true" if ready else "false", "state": r["state"], "reason": r["reason"]})
    _summary(f"**Site API readiness:** `{r['state']}` — {r['reason']}")
    return 0


def cmd_notify_deferred(target: Target = V9) -> int:
    reason = os.environ.get("READINESS_REASON") or "(no reason recorded)"
    run_url = os.environ.get("RUN_URL", "")
    line = (
        f"{target.label} DEFERRED, not failed: {reason}. Nothing was synced. It resumes on its own when the Site API "
        f"deploy lands (web-deploy-resume.yml, or the laptop deploy_site_api.sh / deploy_fleet.sh). {run_url}"
    )
    print(f"::warning title={target.label} deferred::{line}")
    _summary(f"### ⏸️ {target.label} deferred\n\n{line}")
    topic = os.environ.get("SNS_TOPIC_ARN")
    if topic:
        subprocess.run(
            ["aws", "sns", "publish", "--topic-arn", topic, "--subject", f"{target.label} deferred: Site API not ready", "--message", line],
            check=True,
            capture_output=True,
            timeout=60,
        )
    return 0


def dispatch_command(target: Target, live_at_root: bool) -> list[str]:
    """The one `gh workflow run` that re-deploys `target` from main's tip."""
    cmd = ["gh", "workflow", "run", target.workflow, "--repo", GH_REPO, "--ref", "main"]
    if target is V9:
        cmd += ["-f", f"target={'root' if live_at_root else 'preview'}"]
    return cmd


def _break_glass(target: Target) -> str:
    extra = " -f target=root" if target is V9 else ""
    return f"gh workflow run {target.workflow} --ref main{extra} -f api_readiness=skip"


def resume_target(target: Target, live_at_root: bool, verdict, dry_run: bool = False) -> int:
    """Resume one target's deferral if one is outstanding and the API (verdict(), shared) is ready."""
    runs = _gh_json(f"repos/{GH_REPO}/actions/workflows/{target.workflow}/runs?branch=main&per_page={MAX_RUNS}").get("workflow_runs") or []
    cache: dict = {}

    def jobs_for(run: dict) -> list[dict]:
        if run["id"] not in cache:
            cache[run["id"]] = _gh_json(f"repos/{GH_REPO}/actions/runs/{run['id']}/jobs?per_page=100").get("jobs") or []
        return cache[run["id"]]

    kind, run = outstanding_deferral(runs, jobs_for, live_at_root, target)
    if kind != "deferred":
        print(
            f"www_api_readiness resume [{target.key}]: nothing to resume (newest decisive run: {kind}{'' if not run else ' ' + str(run.get('id'))})"
        )
        return 0
    first = first_deferral_of_streak(runs, jobs_for, live_at_root, target) or run
    age = _run_age_hours(first, datetime.now(timezone.utc))
    r = verdict()
    if r is None:
        return 1
    if r["state"] == NOT_READY:
        if age > STALE_DEFERRAL_HOURS:
            print(
                f"::error title={target.label} deferred {age:.1f} h::run {run['id']} (streak since run {first['id']}) is still waiting on "
                f"the Site API — {r['reason']}. Ship the API (gh workflow run ci-cd.yml --ref main -f deploy_all=true, or bash "
                f"deploy/deploy_site_api.sh), or break glass: {_break_glass(target)}"
            )
            return 1
        print(f"www_api_readiness resume [{target.key}]: run {run['id']} deferred {age:.1f} h ago; still waiting — {r['reason']}")
        return 0
    cmd = dispatch_command(target, live_at_root)
    print(
        f"www_api_readiness resume [{target.key}]: run {run['id']} was deferred; the Site API is {r['state']} ({r['reason']}) → {' '.join(cmd)}"
    )
    if not dry_run:
        subprocess.run(cmd, check=True, timeout=60)
    return 0


def cmd_resume(dry_run: bool = False, targets: tuple[Target, ...] = (V9, SITE)) -> int:
    live_at_root = www_owned_paths.live_at_root()
    memo: dict = {}

    def verdict() -> dict | None:  # ONE read of the API, shared by every target that needs it
        if "r" not in memo:
            if is_shallow():
                print("::error::resume needs full history to judge readiness — checkout with fetch-depth: 0")
                memo["r"] = None
            else:
                memo["r"] = evaluate()
        return memo["r"]

    rc = 0
    for target in targets:  # one target's error or stale deferral never blocks the other's resume
        try:
            rc |= resume_target(target, live_at_root, verdict, dry_run)
        except (subprocess.SubprocessError, OSError, ValueError, KeyError) as e:
            print(f"::error title=resume {target.key} failed::{type(e).__name__}: {e}")
            rc = 1
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("check", "notify-deferred", "resume"))
    ap.add_argument("--dry-run", action="store_true", help="resume: decide and print, never dispatch")
    ap.add_argument("--target", choices=sorted(TARGETS), help="notify-deferred: which deploy deferred (default v9); resume: only this one")
    args = ap.parse_args(argv)
    os.chdir(REPO)  # the owed derivation reads repo-relative paths and runs git here
    if args.command == "check":
        return cmd_check()
    if args.command == "notify-deferred":
        return cmd_notify_deferred(TARGETS[args.target or "v9"])
    return cmd_resume(dry_run=args.dry_run, targets=(TARGETS[args.target],) if args.target else (V9, SITE))


if __name__ == "__main__":
    sys.exit(main())
