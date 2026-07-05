#!/usr/bin/env python3
"""
deploy/check_deploy_drift.py — guard the dual deployment planes (#382).

Two independent, cheap deploy-code paths coexist here: some function code ships
via `deploy/deploy_lambda.sh` (a direct `update-function-code` push, done "for
speed" — see `docs/SITE_UPLEVEL_PLAYBOOK.md`'s narrative-lambda note), while the
CDK stacks in `cdk/stacks/` still own those same functions' full definition
(code asset, env vars, IAM, layers, schedule). Two ways that combination bites:

  1. STALE CHECKOUT: `cdk deploy` (and every `deploy/*.sh` script) packages the
     CURRENT WORKING TREE, not `origin/main`. If your checkout is missing
     lambdas/cdk/mcp commits that are already on `origin/main` — most commonly
     because you're on a branch forked before a sibling PR merged — a stack
     deploy from here reasserts the OLD code, silently reverting whatever was
     shipped directly to `main` since your branch forked. This nearly shipped
     a stale checkout over the public cockpit's date-handling fixes (see
     `docs/CONVENTIONS.md` §2/§3 — this automates that documented reflex).
     `sync_site_to_s3.sh` already has this guard for `site/`; this is the
     equivalent for `lambdas/` / `cdk/` / `mcp/`.

  2. LIVE CODE DRIFT: the reverse direction. A function was updated directly
     via `deploy_lambda.sh` (or a console edit) since the LAST `cdk deploy` of
     its owning stack. CloudFormation's own drift-detection knows this — the
     live resource's `Code` (or other) property no longer matches what the
     stack's template last asserted. A blind `cdk deploy --all` of that stack
     would push the STACK'S (older) asset back over the newer, directly-pushed
     code. This check runs `detect_stack_drift` scoped to the stack(s) you're
     about to deploy and flags any Lambda whose `Code` has drifted.

Usage:
    # Before ANY `cdk deploy` — checkout freshness only (git, offline):
    python3 deploy/check_deploy_drift.py

    # Before deploying specific stacks — adds the live-code-drift AWS check:
    python3 deploy/check_deploy_drift.py LifePlatformCompute LifePlatformEmail

    # Overrides (rare, intentional — mirrors sync_site_to_s3.sh's ALLOW_STALE_SITE):
    python3 deploy/check_deploy_drift.py --allow-stale-checkout
    python3 deploy/check_deploy_drift.py LifePlatformCompute --allow-live-drift

Exit 0 = safe to deploy. Exit 1 = blocked (see stdout for which check failed).
Prefer the wrapper `bash deploy/cdk_deploy.sh <Stack...>`, which runs this guard
then execs the real `cdk deploy` — see docs/CONVENTIONS.md for the guarded path.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

REGION = os.environ.get("AWS_REGION", "us-west-2")

# The code trees that own function definitions: Lambda source, CDK stack
# definitions (IAM/env/schedule/layer wiring), and the MCP tool package (its
# own CDK-managed stack, LifePlatformMcp).
DEFAULT_GUARDED_PATHS = ("lambdas/", "cdk/", "mcp/")

_ENV_ALLOW_STALE = "ALLOW_STALE_DEPLOY_CHECKOUT"
_ENV_ALLOW_LIVE_DRIFT = "ALLOW_LIVE_LAMBDA_DRIFT"


# ── 1. Checkout freshness (git only, no AWS) ─────────────────────────────────


def _run_git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def check_checkout_freshness(paths=DEFAULT_GUARDED_PATHS, ref="origin/main", cwd=None, fetch=True):
    """Is this checkout missing any `paths` commits that `ref` already has?

    Mirrors the site clobber guard in `sync_site_to_s3.sh`. Returns:
      {"status": "fresh"|"stale"|"unknown", "missing_commits": int, "detail": str}

    Fail-soft: an offline fetch or a non-repo cwd returns "unknown", never
    crashes — this must never be the reason a deploy can't run when the network
    is the only thing missing (matches the existing site guard's fail-soft path).
    """
    if fetch:
        fetch_res = _run_git(["fetch", "origin", "main", "--quiet"], cwd=cwd)
        if fetch_res.returncode != 0:
            return {
                "status": "unknown",
                "missing_commits": 0,
                "detail": f"couldn't fetch origin/main (offline?): {fetch_res.stderr.strip()}",
            }

    rev_res = _run_git(["rev-list", "--count", f"HEAD..{ref}", "--", *paths], cwd=cwd)
    if rev_res.returncode != 0:
        return {"status": "unknown", "missing_commits": 0, "detail": f"git rev-list failed: {rev_res.stderr.strip()}"}

    try:
        missing = int(rev_res.stdout.strip() or "0")
    except ValueError:
        return {"status": "unknown", "missing_commits": 0, "detail": f"unexpected rev-list output: {rev_res.stdout!r}"}

    if missing > 0:
        return {
            "status": "stale",
            "missing_commits": missing,
            "detail": f"{ref} has {missing} commit(s) touching {list(paths)} this checkout lacks — "
            f"a deploy from here would ship OLD code over a live fix.",
        }
    return {"status": "fresh", "missing_commits": 0, "detail": f"checkout matches {ref} for {list(paths)}"}


# ── 2. Live-code drift (CloudFormation drift detection, read-only AWS) ──────


def _cfn_client(region=REGION):
    import boto3

    return boto3.client("cloudformation", region_name=region)


def _poll_drift(cfn, detection_id, timeout=120, interval=5):
    waited = 0
    while waited < timeout:
        st = cfn.describe_stack_drift_detection_status(StackDriftDetectionId=detection_id)
        if st.get("DetectionStatus") in ("DETECTION_COMPLETE", "DETECTION_FAILED"):
            return st
        time.sleep(interval)
        waited += interval
    return None


def _drifted_lambda_properties(cfn, stack_name):
    """Lambda-function resources with MODIFIED/DELETED drift, split into code vs
    other (env/layers/tags/...) property differences. A `Code` difference means
    the live function was updated out of band since the last `cdk deploy` of
    this stack — nothing else touches Lambda `Code` outside CloudFormation."""
    findings = []
    token = None
    while True:
        kw = {"StackName": stack_name, "StackResourceDriftStatusFilters": ["MODIFIED", "DELETED"]}
        if token:
            kw["NextToken"] = token
        resp = cfn.describe_stack_resource_drifts(**kw)
        for d in resp.get("StackResourceDrifts", []):
            if d.get("ResourceType") != "AWS::Lambda::Function":
                continue
            props = d.get("PropertyDifferences", [])
            code_props = [p for p in props if str(p.get("PropertyPath", "")).startswith("/Code")]
            other_props = [p for p in props if p not in code_props]
            findings.append(
                {
                    "function": d.get("PhysicalResourceId"),
                    "logical_id": d.get("LogicalResourceId"),
                    "code_drift": bool(code_props),
                    "code_properties": [p.get("PropertyPath") for p in code_props],
                    "other_properties": [p.get("PropertyPath") for p in other_props],
                }
            )
        token = resp.get("NextToken")
        if not token:
            break
    return findings


def check_live_code_drift(stack_names, region=REGION, timeout=120):
    """Run CFN drift-detection on each stack about to be deployed. Returns:
      {"status": "clean"|"drift"|"error", "stacks": {name: {...}}}
    `status == "drift"` means at least one function's live `Code` has diverged
    from the stack's template — the exact scenario a blind `cdk deploy` would
    silently clobber."""
    cfn = _cfn_client(region)
    out = {}
    saw_code_drift = False
    saw_error = False
    for name in stack_names:
        try:
            det_id = cfn.detect_stack_drift(StackName=name)["StackDriftDetectionId"]
            status = _poll_drift(cfn, det_id, timeout=timeout)
            if status is None:
                out[name] = {"status": "error", "detail": "drift detection timed out"}
                saw_error = True
                continue
            if status.get("DetectionStatus") == "DETECTION_FAILED":
                out[name] = {"status": "error", "detail": status.get("DetectionStatusReason", "detection failed")}
                saw_error = True
                continue
            if status.get("StackDriftStatus") != "DRIFTED":
                out[name] = {"status": "clean", "functions": []}
                continue
            fns = _drifted_lambda_properties(cfn, name)
            code_drifted = [f for f in fns if f["code_drift"]]
            if code_drifted:
                out[name] = {"status": "drift", "functions": fns}
                saw_code_drift = True
            elif fns:
                out[name] = {"status": "config_drift_only", "functions": fns}
            else:
                out[name] = {"status": "clean", "functions": []}
        except Exception as e:  # noqa: BLE001 — surface as error, never crash the gate
            out[name] = {"status": "error", "detail": str(e)[:300]}
            saw_error = True

    overall = "drift" if saw_code_drift else ("error" if saw_error else "clean")
    return {"status": overall, "stacks": out}


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stacks", nargs="*", help="CDK stack name(s) about to be deployed (enables the live-code-drift check)")
    ap.add_argument("--paths", nargs="*", default=list(DEFAULT_GUARDED_PATHS), help="guarded code trees for the checkout-freshness check")
    ap.add_argument(
        "--allow-stale-checkout", action="store_true", help=f"override the checkout-freshness block (or set {_ENV_ALLOW_STALE}=1)"
    )
    ap.add_argument(
        "--allow-live-drift", action="store_true", help=f"override the live-code-drift block (or set {_ENV_ALLOW_LIVE_DRIFT}=1)"
    )
    ap.add_argument(
        "--skip-live-check", action="store_true", help="skip the AWS CloudFormation drift check (git-only, e.g. no AWS creds handy)"
    )
    ap.add_argument(
        "--no-fetch", action="store_true", help="skip `git fetch` (use whatever origin/main the local repo already knows about)"
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    allow_stale = args.allow_stale_checkout or os.environ.get(_ENV_ALLOW_STALE) == "1"
    allow_live_drift = args.allow_live_drift or os.environ.get(_ENV_ALLOW_LIVE_DRIFT) == "1"

    result = {"checkout": None, "live_drift": None, "blocked": False, "reasons": []}

    checkout = check_checkout_freshness(paths=args.paths, fetch=not args.no_fetch)
    result["checkout"] = checkout
    if checkout["status"] == "stale" and not allow_stale:
        result["blocked"] = True
        result["reasons"].append("stale checkout")

    if args.stacks and not args.skip_live_check:
        live = check_live_code_drift(args.stacks)
        result["live_drift"] = live
        if live["status"] == "drift" and not allow_live_drift:
            result["blocked"] = True
            result["reasons"].append("live code drift")
    elif args.stacks:
        result["live_drift"] = {"status": "skipped"}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_human(result, allow_stale, allow_live_drift)

    return 1 if result["blocked"] else 0


def _print_human(result, allow_stale, allow_live_drift):
    co = result["checkout"]
    icon = {"fresh": "🟢", "stale": "🔴", "unknown": "🟡"}.get(co["status"], "·")
    print(f"{icon} checkout freshness: {co['status']} — {co['detail']}")
    if co["status"] == "stale" and allow_stale:
        print("   ⚠️  overridden (--allow-stale-checkout) — proceeding anyway")

    live = result["live_drift"]
    if live is None:
        print("· live code drift: not checked (no stack names given)")
    elif live.get("status") == "skipped":
        print("· live code drift: skipped (--skip-live-check)")
    else:
        icon = {"clean": "🟢", "drift": "🔴", "error": "🟡"}.get(live["status"], "·")
        print(f"{icon} live code drift: {live['status']}")
        for name, s in live.get("stacks", {}).items():
            st = s.get("status")
            mark = {"clean": "🟢", "drift": "🔴", "config_drift_only": "🟡", "error": "🟡"}.get(st, "·")
            print(f"   {mark} {name}: {st}")
            for fn in s.get("functions", []):
                if fn["code_drift"]:
                    print(f"        🔴 {fn['function']} — CODE drifted ({fn['code_properties']}) — direct push since last deploy")
                elif fn.get("other_properties"):
                    print(f"        🟡 {fn['function']} — config drifted ({fn['other_properties']}), no code risk")
            if st == "error":
                print(f"        {s.get('detail', '')}")
        if live["status"] == "drift" and allow_live_drift:
            print("   ⚠️  overridden (--allow-live-drift) — proceeding anyway")

    if result["blocked"]:
        print(f"\n⛔ BLOCKED: {', '.join(result['reasons'])}.")
        print("   Fix: git merge/rebase origin/main (checkout), or reconcile the live code")
        print("   with cdk (e.g. `cdk deploy` intentionally, or re-run `deploy_lambda.sh`")
        print("   from a checkout that has both), then re-run this guard.")
        print(
            f"   Override (intentional): --allow-stale-checkout / --allow-live-drift, or {_ENV_ALLOW_STALE}=1 / {_ENV_ALLOW_LIVE_DRIFT}=1"
        )
    else:
        print("\n✅ safe to deploy")


if __name__ == "__main__":
    sys.exit(main())
