#!/usr/bin/env python3
"""scripts/check_deploy_deadman.py — the deploy dead-man (#4256, ADR-158).

WHAT THIS REPLACES
------------------
Until ADR-158 every CI/CD code deploy parked at the `production` environment's manual
approval. Keeping that one click from wedging the pipeline grew a watcher that approved
it (deploy/watch_deploy_gate.sh), a janitor that rejected superseded parks
(deploy-gate-janitor.yml), a phantom-wedge classifier (scripts/check_deploy_wedge.py)
and a merge serialiser (deploy/merge_train.sh). ADR-158 routes code around the gate —
only an additive-IAM CDK deploy (`Deploy IAM (production gate)`) still waits for a human
— so the machinery that kept a click-per-merge alive has nothing left to keep alive.
What is left to know is ONE fact: did what main merged actually reach AWS?

THE QUESTION
------------
Walk CI/CD's runs on main newest-first and classify each by its own job list:

    deployed      `Deploy` concluded success
    nothing       Plan green, `Deploy` skipped, the IAM gate job absent or skipped
                  (a docs-only push — nothing was ever owed)
    not-green     Plan did not conclude success (a red run is check_main_green's verdict,
                  not this one's — the owner's ruling reads "within N hours of a GREEN run")
    in-flight     still running (including parked at the IAM gate)
    undeployed    Plan green and the deploy did not happen: `Deploy` failed or was
                  cancelled (a superseded concurrency slot drops its diff), or `Deploy`
                  was skipped because the IAM gate job failed / was rejected

The walk stops at the first run whose `Deploy` shipped the WHOLE fleet (its "Fleet
deploy" step succeeded — a `deploy_all` dispatch always takes that path): everything
older is superseded by a whole-tree bundle. An undeployed or in-flight run older than
`--hours` above that line is the alarm. Recovery is always the same one command, and the
alarm prints it: `gh workflow run ci-cd.yml --ref main -f deploy_all=true`.

Exit codes (the #2753 three-way contract — the check itself must not fail dark):
    0  OK — nothing owed past the deadline
    1  ALARM — a green run on main has not deployed within the deadline
    2  INDETERMINATE — an API read failed; neither verdict is provable

`--alert` additionally keeps one tracking issue (label `deploy-deadman`) in step with the
verdict and fires the `urgent_alarm` repository_dispatch the remediation agent already
consumes, once per episode (an episode is the set of alarmed run ids). Best-effort: the
alert plumbing never changes the exit code.

Usage:
  python3 scripts/check_deploy_deadman.py              # classify; exit 0/1/2
  python3 scripts/check_deploy_deadman.py --hours 6    # deadline after a green Plan
  python3 scripts/check_deploy_deadman.py --alert      # + tracking issue / dispatch
  python3 scripts/check_deploy_deadman.py --deploy-base  # #4472: print plan's diff base (exit 0) or nothing (exit 2)
  python3 scripts/check_deploy_deadman.py --stale-lambdas  # #4472: live Lambdas older than their source (AWS read)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO = "averagejoematt/life-platform"
WORKFLOW = "ci-cd.yml"
BRANCH = "main"

# Job display names in ci-cd.yml. A rename there must land here too:
# tests/test_head_coverage_scheduled_consumer_2826.py pins all three against the file.
PLAN_JOB = "Plan deployments"
DEPLOY_JOB = "Deploy"
DEPLOY_IAM_JOB = "Deploy IAM (production gate)"
FLEET_STEP_PREFIX = "Fleet deploy"

# Hours after a green Plan before an undeployed run is an alarm. A code deploy takes
# minutes (run 36366557551: Plan done 01:50:00Z, Deploy done 02:02:35Z); the wait that
# can legitimately run long is a human reading an IAM diff, and four hours is a working
# block, not a night. The effective detection latency is this PLUS the scheduler's real
# gap (deploy-wedge-watch.yml: `*/15` declared, median ~0.7 h, p90 ~1.2 h measured).
DEADLINE_HOURS = 4.0

# One page of the newest runs on main. The walk stops at the first fleet deploy, and a
# fleet deploy happens on every shared-module change — a normal day has several.
RUNS_PAGE = 100
# Hard stop on job-list reads per sweep (one per walked run), not a recency window.
MAX_JOB_READS = 40

DEPLOYED = "deployed"
NOTHING = "nothing"
NOT_GREEN = "not-green"
IN_FLIGHT = "in-flight"
UNDEPLOYED = "undeployed"

EXIT_OK, EXIT_ALARM, EXIT_INDETERMINATE = 0, 1, 2

RECOVERY = "gh workflow run ci-cd.yml --ref main -f deploy_all=true"

ALERT_LABEL = "deploy-deadman"
ALERT_EVENT_TYPE = "urgent_alarm"
ALERT_MARKER_PREFIX = "<!-- deploy-deadman:"
ALERT_MARKER_SUFFIX = "-->"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _job(jobs: list[dict], name: str) -> dict | None:
    for j in jobs:
        if j.get("name") == name:
            return j
    return None


def classify_run(run: dict, jobs: list[dict], now: datetime) -> dict:
    """One run's deploy state from its own job list. Pure.

    `age_hours` is measured from the moment the run went green (Plan completed) — or from
    the run's creation while Plan has not finished. None only if no timestamp parses, and
    an unknown age is never read as fresh (see verdict())."""
    plan = _job(jobs, PLAN_JOB)
    deploy = _job(jobs, DEPLOY_JOB)
    iam = _job(jobs, DEPLOY_IAM_JOB)
    out = {"run_id": run.get("id"), "sha": (run.get("head_sha") or "")[:9], "event": run.get("event"), "fleet": False}

    if plan is None or plan.get("status") != "completed":
        started = _parse_iso(run.get("created_at"))
        out.update(state=IN_FLIGHT, reason="Plan has not finished")
    else:
        started = _parse_iso(plan.get("completed_at"))
        if plan.get("conclusion") != "success":
            out.update(state=NOT_GREEN, reason=f"Plan concluded {plan.get('conclusion')}")
        elif deploy is not None and deploy.get("conclusion") == "success":
            fleet = any(
                (s.get("name") or "").startswith(FLEET_STEP_PREFIX) and s.get("conclusion") == "success" for s in deploy.get("steps") or []
            )
            out.update(state=DEPLOYED, fleet=fleet, reason="fleet deploy" if fleet else "per-function deploy")
        elif any(j is not None and j.get("status") != "completed" for j in (deploy, iam)):
            gate = iam is not None and iam.get("status") == "waiting"
            out.update(state=IN_FLIGHT, reason="parked at the production gate (IAM)" if gate else "deploy still running")
        elif (deploy is None or deploy.get("conclusion") == "skipped") and (iam is None or iam.get("conclusion") in ("skipped", "success")):
            out.update(state=NOTHING, reason="nothing to deploy")
        elif deploy is not None and deploy.get("conclusion") not in ("skipped", None):
            out.update(state=UNDEPLOYED, reason=f"Deploy concluded {deploy.get('conclusion')}")
        else:
            out.update(state=UNDEPLOYED, reason=f"Deploy skipped because the IAM gate job concluded {(iam or {}).get('conclusion')}")

    out["age_hours"] = None if started is None else round((now - started).total_seconds() / 3600.0, 2)
    return out


def walk(runs: list[dict], jobs_for, now: datetime) -> list[dict]:
    """Classify runs newest-first until the first FLEET deploy (inclusive). Pure given
    `jobs_for(run) -> list[dict]`. A sha counts as deployed if ANY of its runs deployed
    (a re-run or a dispatch at the same sha settles it)."""
    ordered = sorted(runs, key=lambda r: str(r.get("created_at") or ""), reverse=True)
    rows: list[dict] = []
    reads = 0
    for run in ordered:
        if reads >= MAX_JOB_READS:
            break
        reads += 1
        row = classify_run(run, jobs_for(run), now)
        rows.append(row)
        if row["state"] == DEPLOYED and row["fleet"]:
            break
    deployed_shas = {r["sha"] for r in rows if r["state"] == DEPLOYED}
    for r in rows:
        if r["state"] in (UNDEPLOYED, IN_FLIGHT) and r["sha"] in deployed_shas:
            r["state"], r["reason"] = DEPLOYED, r["reason"] + " (another run at this sha deployed)"
    return rows


def last_deployed_sha(runs: list[dict], jobs_for, now: datetime) -> str | None:
    """#4472: the head sha of the newest run on main whose `Deploy` concluded success —
    the base ci-cd.yml's `plan` diffs from. Pure given `jobs_for`.

    `plan` used to diff `GITHUB_SHA~1` (its own push only). The deploy job's concurrency
    group keeps ONE pending job and cancels the older one, so a superseded run's merge
    never reached AWS (#4452's weekly-digest fix, 2026-09-29). Diffing from the last
    SUCCESSFUL deploy rolls every cancelled, failed or skipped run's files into the next
    plan. The head sha is an ancestor of the tree that deploy checked out (build_sha may
    stack a reconcile commit on it), so the diff is a superset — never a gap. None means
    no deploy in the readable window: the caller deploys everything, never guesses."""
    ordered = sorted(runs, key=lambda r: str(r.get("created_at") or ""), reverse=True)
    for reads, run in enumerate(ordered):
        if reads >= MAX_JOB_READS:
            break
        if classify_run(run, jobs_for(run), now)["state"] == DEPLOYED:
            return run.get("head_sha") or None
    return None


def verdict(rows: list[dict], hours: float = DEADLINE_HOURS) -> dict:
    """The alarm set: undeployed or in-flight rows past the deadline. Pure. An unknown age
    on an owed row alarms — it cannot be ruled out as a stale one (#2791's rule)."""
    alarms = [r for r in rows if r["state"] in (UNDEPLOYED, IN_FLIGHT) and (r.get("age_hours") is None or r["age_hours"] >= hours)]
    return {"alarms": alarms, "rows": rows, "hours": hours}


def render(state: dict) -> tuple[int, str]:
    lines = []
    for r in state["rows"]:
        age = "?" if r.get("age_hours") is None else f"{r['age_hours']:.1f}h"
        lines.append(f"  run {r['run_id']} sha {r['sha']} [{r['event']}] {r['state']:<10} {age:>7}  {r['reason']}")
    if not state["alarms"]:
        return EXIT_OK, "✅ deploy dead-man: nothing owed past the deadline.\n" + "\n".join(lines)
    head = (
        f"🛑 DEPLOY DEAD-MAN (#4256): {len(state['alarms'])} green run(s) on main not deployed within "
        f"{state['hours']:g}h — main is ahead of AWS.\n"
        f"   Recovery (ships the whole tree, supersedes every row below it): {RECOVERY}\n"
        "   A row parked at the production gate is an IAM diff waiting on the owner: approve or reject it in Actions."
    )
    return EXIT_ALARM, head + "\n" + "\n".join(lines)


# ── #4472 box 2: which LIVE Lambda is older than its source on main (read-only) ─────────
#
# The run walk above reads GitHub's side only. This reads AWS's: each mapped function's
# `LastModified` against the newest main commit that should have redeployed it — its own
# handler, any shared module (an unmapped lambdas/ file ships in every bundle), or a
# bundled config path. It is the direct check of the weekly-digest incident: the live zip
# predated #4452's merge while every run on main read green or cancelled.

# The reconcile bot's counter file is unmapped but never triggers a fleet deploy (#4250);
# counting it as shared would read the whole fleet stale after every count bump.
STALE_SHARED_EXCLUDE = ("lambdas/web/platform_counts.py",)
# A merge this recent may still be deploying; the nightly run never alarms on it.
STALE_GRACE_HOURS = 2.0


def _parse_aws_ts(ts: str | None) -> datetime | None:
    """`2026-09-29T18:00:59.000+0000` (Lambda's LastModified) → aware datetime."""
    if not ts:
        return None
    t = str(ts)
    if len(t) > 5 and t[-5] in "+-" and t[-4:].isdigit():
        t = t[:-2] + ":" + t[-2:]
    return _parse_iso(t)


def stale_functions(last_modified: dict, owed: dict, now: datetime, grace_hours: float = STALE_GRACE_HOURS) -> list[dict]:
    """Pure. `last_modified`: function -> live LastModified (datetime or None).
    `owed`: function -> (datetime of the newest main commit that should have redeployed
    it, what that commit touched). A function is stale when it is live-older than what it
    owes and the owed commit is past the grace window. A function main maps but AWS does
    not list is reported too — absence is never read as fresh."""
    rows = []
    for fn, (owed_at, why) in sorted(owed.items()):
        if owed_at is None or (now - owed_at).total_seconds() / 3600.0 < grace_hours:
            continue
        live = last_modified.get(fn)
        if live is None:
            rows.append({"function": fn, "live": None, "owed": owed_at, "why": why + " (function not listed by AWS)"})
        elif live < owed_at:
            rows.append({"function": fn, "live": live, "owed": owed_at, "why": why})
    return rows


def _git_ts(paths: list[str], excludes: tuple[str, ...] = ()) -> datetime | None:
    args = ["git", "log", "-1", "--format=%ct", "HEAD", "--", *paths, *(f":(exclude){e}" for e in excludes)]
    out = subprocess.run(args, capture_output=True, text=True, timeout=120, check=True).stdout.strip()
    return datetime.fromtimestamp(int(out), tz=timezone.utc) if out else None


def collect_owed(lambda_map_path: str = "ci/lambda_map.json") -> dict:
    """function -> (owed datetime, reason), from git history of the checked-out main."""
    with open(lambda_map_path) as f:
        mapped = {src: row for src, row in json.load(f)["lambdas"].items()}
    live_map = {src: row["function"] for src, row in mapped.items() if not row.get("native_deps") and not row.get("not_deployed")}
    bundled = subprocess.run(
        [sys.executable, "deploy/build_bundle.py", "--print-bundled-config-paths"], capture_output=True, text=True, timeout=120, check=True
    ).stdout.split()
    shared_at = _git_ts(["lambdas/", *bundled], excludes=(*mapped.keys(), *STALE_SHARED_EXCLUDE))
    owed = {}
    for src, fn in live_map.items():
        own_at = _git_ts([src])
        if shared_at is not None and (own_at is None or shared_at > own_at):
            owed[fn] = (shared_at, "a shared module / bundled config changed")
        else:
            owed[fn] = (own_at, f"{src} changed")
    return owed


def collect_last_modified(lambda_map_path: str = "ci/lambda_map.json") -> dict:
    """function -> live LastModified, across every region the map names (a `region` key,
    else the pipeline's own region — two web functions live in us-east-1)."""
    with open(lambda_map_path) as f:
        default = os.environ.get("AWS_REGION") or "us-west-2"
        regions = {row.get("region") or default for row in json.load(f)["lambdas"].values()}
    live: dict = {}
    for region in sorted(regions):
        out = subprocess.run(
            [
                "aws",
                "lambda",
                "list-functions",
                "--region",
                region,
                "--query",
                "Functions[].[FunctionName,LastModified]",
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        ).stdout
        live.update({name: _parse_aws_ts(ts) for name, ts in json.loads(out)})
    return live


def render_stale(rows: list[dict]) -> tuple[int, str]:
    if not rows:
        return EXIT_OK, "✅ live Lambdas: none older than its source on main."
    lines = [
        f"🛑 {len(rows)} live Lambda(s) older than their source on main (#4472) — main is ahead of AWS.",
        f"   Recovery: {RECOVERY}",
    ]
    for r in rows:
        live = r["live"].strftime("%Y-%m-%dT%H:%MZ") if r["live"] else "absent"
        lines.append(f"  {r['function']:<40} live {live}  owes {r['owed'].strftime('%Y-%m-%dT%H:%MZ')}  {r['why']}")
    return EXIT_ALARM, "\n".join(lines)


# ── alerting (thin `gh` I/O; every failure is swallowed into the returned status) ─────


def episode_key(state: dict) -> str:
    return ",".join(sorted(str(r["run_id"]) for r in state["alarms"]))


def parse_marker(body: str | None) -> str | None:
    if not body or ALERT_MARKER_PREFIX not in body:
        return None
    start = body.index(ALERT_MARKER_PREFIX) + len(ALERT_MARKER_PREFIX)
    end = body.find(ALERT_MARKER_SUFFIX, start)
    return None if end == -1 else body[start:end].strip()


def _gh(args: list[str], stdin: str | None = None) -> str:
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, timeout=60, check=True).stdout


def _gh_api(path: str):
    return json.loads(_gh(["api", path]))


def maybe_alert(state: dict, report: str, now: datetime) -> str:
    try:
        issues = [i for i in _gh_api(f"repos/{REPO}/issues?state=open&labels={ALERT_LABEL}&per_page=5") if "pull_request" not in i]
        existing = issues[0] if issues else None
        if not state["alarms"]:
            if existing is None:
                return "alert-skip: healthy, no tracking issue"
            _gh(["api", f"repos/{REPO}/issues/{existing['number']}", "--method", "PATCH", "-f", "state=closed"])
            return f"alert-rearmed: closed #{existing['number']}"
        key = episode_key(state)
        if existing is not None and parse_marker(existing.get("body")) == key:
            return f"alert-throttled: episode {key} already alerted"
        body = f"{report}\n\n{ALERT_MARKER_PREFIX}{key}{ALERT_MARKER_SUFFIX}\n"
        if existing is None:
            # One label and no `type:*` — an instrument's throttle row, exempt from the backlog
            # contract by check_backlog_hygiene.is_instrument_marker (#3853); REST creates the
            # label on first use.
            title = "[auto-filed] Deploy dead-man — main is ahead of AWS"
            _gh(["api", f"repos/{REPO}/issues", "-f", f"title={title}", "-f", f"body={body}", "-f", f"labels[]={ALERT_LABEL}"])
        else:
            _gh(["api", f"repos/{REPO}/issues/{existing['number']}", "--method", "PATCH", "-f", f"body={body}"])
        payload = {
            "alarm_name": "deploy-deadman",
            "state": "ALARM",
            "reason": report.splitlines()[0],
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_id": state["alarms"][0]["run_id"],
            "kind": "deploy-deadman",
        }
        _gh(
            ["api", f"repos/{REPO}/dispatches", "--method", "POST", "--input", "-"],
            json.dumps({"event_type": ALERT_EVENT_TYPE, "client_payload": payload}),
        )
        return f"alert-fired: episode {key}"
    except Exception as e:  # noqa: BLE001 - alerting is best-effort; the exit code already decided
        return f"alert-error: {e}"


def collect() -> tuple[list[dict], dict]:
    runs = _gh_api(f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?branch={BRANCH}&per_page={RUNS_PAGE}").get("workflow_runs", [])
    cache: dict = {}

    def jobs_for(run: dict) -> list[dict]:
        rid = run.get("id")
        if rid not in cache:
            cache[rid] = _gh_api(f"repos/{REPO}/actions/runs/{rid}/jobs?per_page=100").get("jobs", [])
        return cache[rid]

    return runs, jobs_for


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=DEADLINE_HOURS, help="deadline after a green Plan (default %(default)s)")
    ap.add_argument("--alert", action="store_true", help="keep the tracking issue + urgent_alarm dispatch in step")
    ap.add_argument("--stale-lambdas", action="store_true", help="#4472: live Lambdas older than their source on main (AWS read)")
    ap.add_argument("--deploy-base", action="store_true", help="#4472: print the last successfully deployed sha (plan's diff base)")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    if args.stale_lambdas:
        try:
            rows = stale_functions(collect_last_modified(), collect_owed(), now)
        except Exception as e:  # noqa: BLE001 - an unreadable AWS/git read is INDETERMINATE, never OK
            print(f"⚠️  stale-Lambda check INDETERMINATE: {e}")
            return EXIT_INDETERMINATE
        code, report = render_stale(rows)
        print(report)
        return code
    if args.deploy_base:
        # stdout carries the sha and nothing else; an unreadable API or no deploy in the
        # window prints nothing and exits INDETERMINATE — plan then deploys everything.
        try:
            runs, jobs_for = collect()
            sha = last_deployed_sha(runs, jobs_for, now)
        except Exception as e:  # noqa: BLE001 - unreadable is INDETERMINATE, never a guessed base
            print(f"deploy-base INDETERMINATE: {e}", file=sys.stderr)
            return EXIT_INDETERMINATE
        if not sha:
            print(f"deploy-base INDETERMINATE: no successful Deploy in the newest {MAX_JOB_READS} runs on {BRANCH}", file=sys.stderr)
            return EXIT_INDETERMINATE
        print(sha)
        return EXIT_OK
    try:
        runs, jobs_for = collect()
        state = verdict(walk(runs, jobs_for, now), args.hours)
    except Exception as e:  # noqa: BLE001 - an unreadable API is INDETERMINATE, never OK
        print(f"⚠️  deploy dead-man INDETERMINATE: could not read the Actions API ({e}) — decode by hand.")
        return EXIT_INDETERMINATE
    code, report = render(state)
    print(report)
    if args.alert:
        print(maybe_alert(state, report, now))
    return code


if __name__ == "__main__":
    sys.exit(main())
