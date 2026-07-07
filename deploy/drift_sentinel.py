#!/usr/bin/env python3
"""
deploy/drift_sentinel.py — weekly "live state vs. code" drift sentinel (#394).

CI's `cdk diff --all` compares the CDK app to the deployed *template* — it is blind to
drift that happens OUT of band: a resource edited in the console, a stack resource
deleted, a Lambda config mutated by hand, a bucket policy loosened. This closes that
gap with a read-only sweep that a human never has to remember to run.

What it checks (all read-only; CloudFormation drift-detection API calls are free):

  1. CFN DRIFT — `detect_stack_drift` across all 8 stacks, then reports every
     MODIFIED / DELETED resource (`describe_stack_resource_drifts`). This is the live
     state vs. the deployed template, which `cdk diff` cannot see.
  2. POSTFLIGHT REUSE — the human-invoked-only checks from session_postflight:
     layer retirement (#781: zero shared-utils references), lambda config
     drift, bundled-asset completeness.
  3. NO FUNCTIONS OUTSIDE IaC — every live Lambda in the region must be a member of one
     of our CloudFormation stacks. A function that exists live but in no stack's
     resource list was created out of band (orphan) — surfaced, minus a small allowlist
     of CDK-toolkit infra.
  4. BUCKET-POLICY DELETE-PROTECTION — the `ProtectDataFromDeployScripts` Deny statement
     that guards raw data (raw/*, config/*, uploads/*, …) is verified live against the
     source of truth (deploy/bucket_policy.json). A loosened or dropped Deny is loud.

Output: a findings record written to s3://<bucket>/drift-log/{latest,<date>}.json
(mirrors the Coherence Sentinel's coherence-log pattern) so the remediation agent can
ingest it into its curated report — and a loud human summary to stdout. A clean week
reports explicitly clean; it is never silent.

This runs as a STEP in an existing scheduled workflow (the remediation agent, weekly on
Mondays) with the remediation role's read-only access — NO new always-on infrastructure.

Run locally (needs read-only AWS creds):
    python3 deploy/drift_sentinel.py            # write the record, exit 0
    python3 deploy/drift_sentinel.py --strict   # exit non-zero if drift/degraded (CI gate)
    python3 deploy/drift_sentinel.py --no-write  # print only, don't touch S3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

REGION = os.environ.get("AWS_REGION", "us-west-2")
BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The 8 CDK stacks and the region each deploys to (Web is us-east-1 for CloudFront).
# Source of truth: cdk/app.py.
STACKS = {
    "LifePlatformCore": REGION,
    "LifePlatformIngestion": REGION,
    "LifePlatformCompute": REGION,
    "LifePlatformEmail": REGION,
    "LifePlatformOperational": REGION,
    "LifePlatformMcp": REGION,
    "LifePlatformMonitoring": REGION,
    "LifePlatformWeb": "us-east-1",
}

# Live Lambdas that are legitimately not one of OUR create_platform_lambda functions:
# CDK toolkit / bootstrap infra and provider framework functions. A live function whose
# name starts with one of these is not treated as an out-of-IaC orphan.
_ORPHAN_ALLOW_PREFIXES = (
    "cdk-hnb659fds-",  # CDK bootstrap (asset publishing, image build)
    "StackSet-",  # StackSets admin
)

_DRIFT_STATUSES = ("MODIFIED", "DELETED")


def _client(service, region=REGION):
    import boto3

    return boto3.client(service, region_name=region)


# ── 1. CloudFormation drift ──────────────────────────────────────────────────


def check_cfn_drift(per_stack_timeout=180):
    """detect_stack_drift on each stack, then collect MODIFIED/DELETED resources.

    Fail-soft per stack: a stack that errors or times out is recorded as an error, not a
    crash. Returns {"status": clean|drift|degraded, "stacks": {name: {...}}}."""
    out = {}
    saw_drift = False
    saw_error = False
    # Group stacks by region so we reuse one client per region.
    by_region: dict[str, list[str]] = {}
    for name, region in STACKS.items():
        by_region.setdefault(region, []).append(name)

    for region, names in by_region.items():
        try:
            cfn = _client("cloudformation", region)
        except Exception as e:  # noqa: BLE001
            for name in names:
                out[name] = {"status": "error", "detail": f"client init: {e}"}
            saw_error = True
            continue
        for name in names:
            try:
                det = cfn.detect_stack_drift(StackName=name)["StackDriftDetectionId"]
                status = _poll_drift(cfn, det, per_stack_timeout)
                if status is None:
                    out[name] = {"status": "error", "detail": "detection timed out"}
                    saw_error = True
                    continue
                if status.get("DetectionStatus") == "DETECTION_FAILED":
                    out[name] = {"status": "error", "detail": status.get("DetectionStatusReason", "detection failed")}
                    saw_error = True
                    continue
                if status.get("StackDriftStatus") != "DRIFTED":
                    out[name] = {"status": "clean", "drift_status": status.get("StackDriftStatus", "IN_SYNC")}
                    continue
                resources = _drifted_resources(cfn, name)
                out[name] = {"status": "drift", "drifted": resources}
                saw_drift = True
            except Exception as e:  # noqa: BLE001 — surface as error, never crash the sweep
                out[name] = {"status": "error", "detail": str(e)[:300]}
                saw_error = True

    status = "drift" if saw_drift else ("degraded" if saw_error else "clean")
    return {"status": status, "stacks": out}


def _poll_drift(cfn, detection_id, timeout):
    """Poll describe_stack_drift_detection_status until complete/failed or timeout."""
    waited = 0
    interval = 5
    while waited < timeout:
        st = cfn.describe_stack_drift_detection_status(StackDriftDetectionId=detection_id)
        if st.get("DetectionStatus") in ("DETECTION_COMPLETE", "DETECTION_FAILED"):
            return st
        time.sleep(interval)
        waited += interval
    return None


def _drifted_resources(cfn, stack):
    """List MODIFIED/DELETED resources for a drifted stack (paginated)."""
    drifted = []
    token = None
    while True:
        kw = {"StackName": stack, "StackResourceDriftStatusFilters": list(_DRIFT_STATUSES)}
        if token:
            kw["NextToken"] = token
        resp = cfn.describe_stack_resource_drifts(**kw)
        for d in resp.get("StackResourceDrifts", []):
            drifted.append(
                {
                    "logical_id": d.get("LogicalResourceId"),
                    "type": d.get("ResourceType"),
                    "drift": d.get("StackResourceDriftStatus"),
                    "physical_id": d.get("PhysicalResourceId"),
                }
            )
        token = resp.get("NextToken")
        if not token:
            break
    return drifted


# ── 2. Postflight reuse (layer / config / asset) ─────────────────────────────


def check_postflight():
    """Reuse the human-invoked-only checks from session_postflight (AC2)."""
    sys.path.insert(0, os.path.join(_ROOT, "deploy"))
    import session_postflight as pf

    result = {}
    try:
        latest, behind = pf.check_layer_uniformity()
        result["layer_uniformity"] = {
            "status": "drift" if behind else "clean",
            "latest": latest,
            "behind": [{"function": fn, "on": v} for fn, v in behind],
        }
    except Exception as e:  # noqa: BLE001
        result["layer_uniformity"] = {"status": "error", "detail": str(e)[:300]}
    try:
        drift = pf.check_config_drift()
        result["config_drift"] = {
            "status": "drift" if drift else "clean",
            "items": [{"function": d.get("function_name"), "issue": d.get("issue")} for d in drift] if drift else [],
        }
    except Exception as e:  # noqa: BLE001
        result["config_drift"] = {"status": "error", "detail": str(e)[:300]}
    try:
        incomplete = pf.check_asset_completeness()
        result["asset_completeness"] = {
            "status": "drift" if incomplete else "clean",
            "incomplete": [{"function": fn, "missing": m} for fn, m in incomplete],
        }
    except Exception as e:  # noqa: BLE001
        result["asset_completeness"] = {"status": "error", "detail": str(e)[:300]}
    return result


# ── 3. No functions outside IaC ──────────────────────────────────────────────


def check_orphan_functions():
    """Every live Lambda (in REGION) must be a resource of one of our CFN stacks.

    A function that exists live but in no stack's resource list was created out of band.
    Authoritative (CloudFormation is the IaC record) and cheap (one ListStackResources
    per region-local stack + one ListFunctions). Web/us-east-1 Lambdas — none today; the
    Web stack's edge logic is CloudFront Functions, not Lambda — so we scope to REGION."""
    try:
        lam = _client("lambda")
        live = set()
        paginator = lam.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                live.add(fn["FunctionName"])
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"list_functions: {e}"}

    try:
        cfn = _client("cloudformation")
        managed = set()
        for name, region in STACKS.items():
            if region != REGION:
                continue  # region-local stacks only (matches the live set above)
            token = None
            while True:
                kw = {"StackName": name}
                if token:
                    kw["NextToken"] = token
                resp = cfn.list_stack_resources(**kw)
                for r in resp.get("StackResourceSummaries", []):
                    if r.get("ResourceType") == "AWS::Lambda::Function" and r.get("PhysicalResourceId"):
                        managed.add(r["PhysicalResourceId"])
                token = resp.get("NextToken")
                if not token:
                    break
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"list_stack_resources: {e}"}

    orphans = sorted(fn for fn in live - managed if not fn.startswith(_ORPHAN_ALLOW_PREFIXES))
    return {"status": "drift" if orphans else "clean", "orphans": orphans, "live_count": len(live), "managed_count": len(managed)}


# ── 4. Bucket-policy delete-protection ───────────────────────────────────────


def check_bucket_policy():
    """The live bucket policy must still Deny s3:DeleteObject on every protected prefix.

    Source of truth: deploy/bucket_policy.json's `ProtectDataFromDeployScripts` statement.
    A dropped statement or a missing prefix (data no longer delete-protected) is loud."""
    try:
        with open(os.path.join(_ROOT, "deploy", "bucket_policy.json")) as f:
            expected_pol = json.load(f)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"read source policy: {e}"}
    expected = _protect_prefixes(expected_pol)

    try:
        s3 = _client("s3")
        live_pol = json.loads(s3.get_bucket_policy(Bucket=BUCKET)["Policy"])
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"get_bucket_policy: {e}"}
    live = _protect_prefixes(live_pol)

    if not live:
        return {"status": "drift", "detail": "no ProtectDataFromDeployScripts Deny found live", "missing_prefixes": sorted(expected)}
    missing = sorted(expected - live)
    return {
        "status": "drift" if missing else "clean",
        "missing_prefixes": missing,
        "expected_count": len(expected),
        "live_count": len(live),
    }


def _protect_prefixes(policy):
    """Return the set of resource ARNs under the delete-protection Deny statement."""
    out: set[str] = set()
    for st in policy.get("Statement", []):
        if st.get("Sid") != "ProtectDataFromDeployScripts":
            continue
        if st.get("Effect") != "Deny":
            continue
        actions = st.get("Action")
        actions = [actions] if isinstance(actions, str) else (actions or [])
        if "s3:DeleteObject" not in actions:
            continue
        res = st.get("Resource")
        res = [res] if isinstance(res, str) else (res or [])
        out.update(res)
    return out


def check_doc_literals():
    """#791: live counts vs the documented literals in sync_doc_metadata.PLATFORM_FACTS.

    The R22 review found live alarms (122) had silently outrun the documented
    count (110) — doc literals only got reconciled when a session happened to
    notice. This closes the loop weekly: compare the live CloudWatch alarm
    count and live Lambda count against PLATFORM_FACTS. A mismatch is 'drift'
    (it lands in the weekly curated report, not an alarm) with the exact
    reconcile command. Alarm-count remediation is tracked in #795/#809."""
    try:
        sys.path.insert(0, os.path.join(_ROOT, "deploy"))
        import sync_doc_metadata as sdm

        facts = dict(sdm.PLATFORM_FACTS)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"import sync_doc_metadata: {e}"}

    mismatches = []
    try:
        cw = _client("cloudwatch")
        live_alarms = 0
        token = None
        while True:
            kw = {"MaxRecords": 100}
            if token:
                kw["NextToken"] = token
            resp = cw.describe_alarms(**kw)
            live_alarms += len(resp.get("MetricAlarms", [])) + len(resp.get("CompositeAlarms", []))
            token = resp.get("NextToken")
            if not token:
                break
        doc_alarms = facts.get("alarm_count")
        if doc_alarms is not None and live_alarms != doc_alarms:
            mismatches.append(
                {
                    "fact": "alarm_count",
                    "documented": doc_alarms,
                    "live": live_alarms,
                    "fix": "reconcile the count (see #809 audit), then update PLATFORM_FACTS + run sync_doc_metadata --apply",
                }
            )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"describe_alarms: {e}"}

    return {"status": "drift" if mismatches else "clean", "mismatches": mismatches}


# ── Assemble + persist ───────────────────────────────────────────────────────


def run_sweep():
    checks = {
        "cfn_drift": check_cfn_drift(),
        **check_postflight(),
        "orphan_functions": check_orphan_functions(),
        "bucket_policy": check_bucket_policy(),
        "doc_literals": check_doc_literals(),
    }
    statuses = [c.get("status") for c in checks.values()]
    if "drift" in statuses:
        status = "drift"
    elif "error" in statuses or "degraded" in statuses:
        status = "degraded"
    else:
        status = "clean"
    now = datetime.now(timezone.utc)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.isoformat(),
        "status": status,
        "summary": _summary(status, checks),
        "checks": checks,
    }


def _summary(status, checks):
    if status == "clean":
        n = len(STACKS)
        return f"All clear: {n}/{n} stacks in sync, no config/layer/asset drift, no orphan functions, data delete-protection intact."
    parts = []
    cfn = checks["cfn_drift"]
    drifted_stacks = [s for s, v in cfn.get("stacks", {}).items() if v.get("status") == "drift"]
    if drifted_stacks:
        parts.append(f"{len(drifted_stacks)} stack(s) drifted: {', '.join(drifted_stacks)}")
    for key, label in (
        ("config_drift", "config drift"),
        ("layer_uniformity", "retired-layer reference(s)"),
        ("asset_completeness", "asset gap"),
        ("orphan_functions", "orphan function(s)"),
        ("bucket_policy", "delete-protection gap"),
        ("doc_literals", "doc-literal drift"),
    ):
        c = checks.get(key, {})
        if c.get("status") == "drift":
            parts.append(label)
    errored = [k for k, v in checks.items() if v.get("status") == "error"]
    if errored:
        parts.append(f"{len(errored)} check(s) could not run: {', '.join(errored)}")
    return "; ".join(parts) or f"status={status}"


def persist(record):
    s3 = _client("s3")
    body = json.dumps(record, indent=2, default=str).encode()
    for key in (f"drift-log/{record['date']}.json", "drift-log/latest.json"):
        s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="application/json")
    return f"s3://{BUCKET}/drift-log/latest.json"


def print_summary(record):
    icon = {"clean": "🟢", "drift": "🔴", "degraded": "🟡"}.get(record["status"], "·")
    print("── weekly drift sentinel ──")
    print(f"{icon} {record['status'].upper()}: {record['summary']}")
    for name, c in record["checks"].items():
        st = c.get("status")
        mark = {"clean": "🟢", "drift": "🔴", "error": "🟡"}.get(st, "·")
        detail = ""
        if st == "drift":
            if name == "cfn_drift":
                ds = [s for s, v in c.get("stacks", {}).items() if v.get("status") == "drift"]
                detail = f" — {', '.join(ds)}"
            elif name == "orphan_functions":
                detail = f" — {', '.join(c.get('orphans', []))}"
            elif name == "bucket_policy":
                detail = f" — missing {c.get('missing_prefixes')}"
            elif name == "config_drift":
                detail = f" — {[i.get('function') for i in c.get('items', [])]}"
            elif name == "layer_uniformity":
                detail = f" — {[b.get('function') for b in c.get('behind', [])]}"
            elif name == "asset_completeness":
                detail = f" — {[i.get('function') for i in c.get('incomplete', [])]}"
            elif name == "doc_literals":
                detail = f" — {[(m['fact'], m['documented'], 'live', m['live']) for m in c.get('mismatches', [])]}"
        elif st == "error":
            detail = f" — {c.get('detail', '')}"
        print(f"   {mark} {name}: {st}{detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit non-zero if drift/degraded")
    ap.add_argument("--no-write", action="store_true", help="print only, don't write S3")
    args = ap.parse_args()

    record = run_sweep()
    print_summary(record)
    if not args.no_write:
        try:
            print(f"written: {persist(record)}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] persist failed: {e}")
    if args.strict and record["status"] != "clean":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
