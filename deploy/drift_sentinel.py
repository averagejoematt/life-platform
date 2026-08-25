#!/usr/bin/env python3
"""
deploy/drift_sentinel.py — weekly "live state vs. code" drift sentinel (#394).

CI's `cdk diff --all` compares the CDK app to the deployed *template* — it is blind to
drift that happens OUT of band: a resource edited in the console, a stack resource
deleted, a Lambda config mutated by hand, a bucket policy loosened. This closes that
gap with a read-only sweep that a human never has to remember to run.

What it checks (all read-only; CloudFormation drift-detection API calls are free):

  1. CFN DRIFT — `detect_stack_drift` across all 9 stacks, then reports every
     MODIFIED / DELETED resource (`describe_stack_resource_drifts`). This is the live
     state vs. the deployed template, which `cdk diff` cannot see. Two documented
     PropertyDifference patterns are known CFN drift-detection false positives, not
     real out-of-band changes (#1781 — see `_known_cfn_noise_reason`): an
     ApiGatewayV2 Stage access-log ARN's trailing `:*`, and a Lambda Function URL's
     lowercased-live CORS header names. A resource whose every difference matches
     one of those never counts as drift — it's recorded under `filtered_noise`
     instead so it stays visible without paging anyone.
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
  4b. S3 LIFECYCLE CONFIGURATION (DIL-026, #2799) — the bucket is imported into CDK, so
     lifecycle rules live in deploy/s3_lifecycle.json / deploy/apply_s3_lifecycle.sh
     instead of a template. Live `get-bucket-lifecycle-configuration` is compared
     rule-by-ID against that same JSON (the file `apply_s3_lifecycle.sh` PUTs verbatim —
     single writer). Closes the gap the DIL-026 finding named: `imports/` had zero
     NoncurrentVersionExpiration coverage (2.23GB, unbounded age) and nothing detected
     it — the only backstop was the post-hoc bucket-size alarm, which cannot name which
     prefix drifted.
  5. SITE/MAIN SHA ANCESTRY (#751) — the live https://averagejoematt.com/version.json
     build SHA must be an ancestor of (or equal to) origin/main HEAD. CI's I22
     (tests/test_integration_aws.py::test_i22_site_version_sha_on_main) checks this
     right after a deploy; this is the STANDING scheduled version that catches
     out-of-band drift BETWEEN deploys (no new always-on infra — read-only HTTPS GET
     + local `git merge-base --is-ancestor`).
  6. GITHUB CONFIG POSTURE (#1320, epic #1355) — GET-only `gh api` asserts of the
     GitHub-side controls the docs make claims about, against the checked-in
     documented posture in deploy/github_posture.json: `production` environment
     protection (the #1319 dead-approval-gate class), the `main` branch ruleset
     (id 19162901: force-push + deletion blocks, #1325), the fast-lane
     required-checks ruleset + repo auto-merge toggle (#1662, ADR-148 — written
     by scripts/apply_branch_protection.py), and vulnerability/
     Dependabot-alert enablement (ADR-082's CVE-remediation channel). Never
     mutates GitHub. Fail-soft on token-scope gaps: an unreadable surface reports
     an honest "credential lacks scope X" needs-owner line (with the exact
     fine-grained-PAT permission to add), never a red.
  7. MAIN-PUSH RUN LIVENESS (#1544) — push-event workflow runs stopped QUEUING
     for six consecutive merges on 2026-07-19 (~3h, not red — ABSENT). This
     compares /commits on main vs /actions/runs?event=push: a trigger-matching
     merge older than the grace window with no queued run is the alarm. Path-
     filter aware (a commit touching only e.g. handovers/ legitimately triggers
     nothing — see PUSH_TRIGGER_GLOBS).
  8. GITHUB QUOTA/BILLING (#1334, #1453) — GitHub became a metered production
     dependency when the repo went private (2026-07-13): CI, site-deploy, and this
     agent itself all run on Actions minutes billed against the account's plan
     allowance. Reads the enhanced-billing usage API (#1613 — the legacy
     /settings/billing/actions endpoint is 410 Gone since 2026-07-26) via the
     GH_BILLING_TOKEN user-scoped PAT; warn at 70% of the included allowance,
     visibility-aware (public-repo minutes are free → reported, warn-suppressed),
     paid overage always warns. FAIL-SOFT without the PAT: the built-in
     GITHUB_TOKEN cannot read billing endpoints, so it reports a clearly-labeled
     "billing usage API unavailable" line rather than erroring. Independently
     lists the top wall-clock-consuming workflows over the trailing 7 days
     (`gh run list`, needs only `actions: read`) so a run-rate regression is
     attributable even without billing-API access.
  9. HAE WEBHOOK INGRESS PARITY (#1946) — a pre-IaC console-created HTTP API
     coexisted with the CDK-managed one for months after the July IaC cutover,
     each with its own apigateway-invoke grant on the `health-auto-export-webhook`
     Lambda (the orphan's scoped to a wildcard `/*/*`, the CDK one to the
     declared `/*/*/ingest` route). Asserts the Lambda's live resource policy
     carries EXACTLY ONE apigateway-invoke statement, scoped to the API id
     derived live from LifePlatformIngestion's own `AWS::ApiGatewayV2::Api`
     resource (guard-the-SET — never a hand-pasted API id) and its declared
     route. Any future console-created ingress, or a re-widened grant, reds
     this check.

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
import re
import sys
import time
from datetime import datetime, timezone

REGION = os.environ.get("AWS_REGION", "us-west-2")
BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The 9 CDK stacks and the region each deploys to (Web is us-east-1 for CloudFront).
# Source of truth: cdk/app.py.
STACKS = {
    "LifePlatformCore": REGION,
    "LifePlatformIngestion": REGION,
    "LifePlatformCompute": REGION,
    "LifePlatformEmail": REGION,
    "LifePlatformOperational": REGION,
    "LifePlatformServe": REGION,
    "LifePlatformMcp": REGION,
    "LifePlatformMonitoring": REGION,
    "LifePlatformWeb": "us-east-1",
    "LifePlatformBackup": "us-east-2",  # DIL-027 raw/ replica — see cdk/stacks/backup_stack.py
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
                resources, noise = _drifted_resources(cfn, name)
                if resources:
                    out[name] = {"status": "drift", "drifted": resources}
                    if noise:
                        out[name]["filtered_noise"] = noise
                    saw_drift = True
                else:
                    # CFN says DRIFTED but every flagged resource's differences matched
                    # a documented false-positive (#1781) — clean for our purposes, the
                    # noise stays visible rather than silently vanishing.
                    out[name] = {
                        "status": "clean",
                        "drift_status": status.get("StackDriftStatus", "IN_SYNC"),
                        "filtered_noise": noise,
                        "detail": "CFN reported DRIFTED but every PropertyDifference matched a documented false-positive (#1781)",
                    }
            except Exception as e:  # noqa: BLE001 — surface as error, never crash the sweep
                out[name] = {"status": "error", "detail": str(e)[:300]}
                saw_error = True

    status = "drift" if saw_drift else ("degraded" if saw_error else "clean")
    # #1227: a DEAD capability must not report as a soft "degraded". If every stack
    # errored AND every error is an AccessDenied, the cfn_drift check is dead-on-arrival
    # (a missing IAM action, not a transient) — escalate to a first-class "error" so it
    # surfaces as needs-human instead of being buried in "degraded" behind continue-on-
    # error. The IAM-parity lesson: verify the capability, don't report a dead one soft.
    if (
        out
        and all(v.get("status") == "error" for v in out.values())
        and all("AccessDenied" in (v.get("detail") or "") for v in out.values())
    ):
        status = "error"
        return {"status": status, "stacks": out, "dead_capability": "all stacks AccessDenied (missing IAM action)"}
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


# ── Known CFN drift-detection false positives (#1781) ────────────────────────
# The 2026-07-26 sentinel sweep flagged AWS::IAM::Role MODIFIED across 7 stacks.
# Triaging every describe_stack_resource_drifts PropertyDifference against the
# live IAM state + the code that actually calls each API found two resource/
# property combinations that are NEVER a functional difference — CloudFormation
# drift detection itself disagreeing with the live API's own normalization,
# not a real out-of-band change:
#
#   1. AWS::ApiGatewayV2::Stage AccessLogSettings.DestinationArn — the stack's
#      stored template always renders this log-group ARN with a trailing ':*'
#      wildcard; the live GetStage response never includes it. Same destination
#      log group either way (verified against HaeWebhookApiDefaultStage).
#   2. AWS::Lambda::Url Cors.AllowHeaders — a Function URL's live
#      GetFunctionUrlConfig response lowercases every header name; the
#      CDK-authored casing (e.g. "Content-Type") only survives in the template.
#      HTTP header names are case-insensitive (RFC 7230 §3.2), so a case-only
#      difference is cosmetic (verified against SiteApiLambdaFunctionUrl,
#      SiteApiAiLambdaFunctionUrl, EmailSubscriberLambdaFunctionUrl).
#
# A PropertyDifference matching one of these is never silently dropped — a
# resource whose EVERY difference is known noise moves to "filtered_noise" in
# the sweep record (still visible) instead of counting as drift. A resource
# with a MIX of real + noise differences still reports the real ones as drift.
# Never widen this beyond the exact, verified pattern below — no blanket
# resource-type or stack-wide suppression (the issue's own AC: "never a
# blanket ignore").
_NOISE_ACCESS_LOG_ARN = re.compile(r"^/AccessLogSettings/DestinationArn$")
_NOISE_CORS_HEADER = re.compile(r"^/Cors/AllowHeaders/\d+$")


def _known_cfn_noise_reason(resource_type, prop):
    """Return a short justification string if `prop` (one PropertyDifference
    dict) is a documented CFN drift-detection false positive, else None."""
    path = prop.get("PropertyPath") or ""
    expected = prop.get("ExpectedValue")
    actual = prop.get("ActualValue")
    if not isinstance(expected, str) or not isinstance(actual, str):
        return None
    if resource_type == "AWS::ApiGatewayV2::Stage" and _NOISE_ACCESS_LOG_ARN.match(path) and expected == actual + ":*":
        return "CFN template wildcard-suffixes the access-log ARN; live GetStage never does (#1781)"
    if resource_type == "AWS::Lambda::Url" and _NOISE_CORS_HEADER.match(path) and expected != actual and expected.lower() == actual.lower():
        return "Lambda Function URL lowercases CORS header names live; case-only, RFC 7230 is case-insensitive (#1781)"
    return None


def _drifted_resources(cfn, stack):
    """List MODIFIED/DELETED resources for a drifted stack (paginated).

    Returns (drifted, filtered_noise). `drifted` holds resources with at least
    one PropertyDifference that isn't documented CFN noise (#1781, see above).
    A resource whose every difference matches a known-noise pattern moves
    entirely to `filtered_noise` instead — visible in the record, but not
    counted toward "status": "drift"."""
    drifted = []
    filtered_noise = []
    token = None
    while True:
        kw = {"StackName": stack, "StackResourceDriftStatusFilters": list(_DRIFT_STATUSES)}
        if token:
            kw["NextToken"] = token
        resp = cfn.describe_stack_resource_drifts(**kw)
        for d in resp.get("StackResourceDrifts", []):
            rtype = d.get("ResourceType")
            entry = {
                "logical_id": d.get("LogicalResourceId"),
                "type": rtype,
                "drift": d.get("StackResourceDriftStatus"),
                "physical_id": d.get("PhysicalResourceId"),
            }
            diffs = d.get("PropertyDifferences") or []
            noise_diffs = []
            has_real_diff = not diffs  # no PropertyDifferences at all (e.g. DELETED) -> always real
            for p in diffs:
                reason = _known_cfn_noise_reason(rtype, p)
                if reason:
                    noise_diffs.append({"PropertyPath": p.get("PropertyPath"), "reason": reason})
                else:
                    has_real_diff = True
            if has_real_diff:
                drifted.append(entry)
            elif noise_diffs:
                filtered_noise.append({**entry, "known_noise": noise_diffs})
        token = resp.get("NextToken")
        if not token:
            break
    return drifted, filtered_noise


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


def check_oidc_iam():
    """The OIDC identities (deploy/remediation/golden-eval/diagnosis roles + provider)
    must match the checked-in JSON under infra/iam/ exactly (#687 S-E6-01).

    Delegates to deploy/verify_oidc_iam.py — the same read-only comparator CI's
    post-deploy checks run — so an out-of-band trust or permission change is caught
    within a week even if no deploy happens."""
    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(_ROOT, "deploy", "verify_oidc_iam.py")],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"verify_oidc_iam: {e}"}
    if proc.returncode == 0:
        return {"status": "clean"}
    drift_lines = [ln.strip() for ln in proc.stdout.splitlines() if "[DRIFT]" in ln]
    return {"status": "drift", "detail": "OIDC/IAM identities differ from infra/iam/", "mismatches": drift_lines[:10]}


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


# ── 4b. S3 lifecycle declared-vs-live (DIL-026, #2799) ───────────────────────
# The bucket is imported into CDK (`Bucket.from_bucket_name`), so lifecycle rules
# live in deploy/s3_lifecycle.json / deploy/apply_s3_lifecycle.sh instead of a
# template — exactly the shape `check_bucket_policy` above already covers for the
# bucket POLICY. Lifecycle had no equivalent: `imports/` sat with zero
# NoncurrentVersionExpiration coverage (2.23GB of noncurrent versions, unbounded
# age) and nothing would ever have said so — the only backstop was the post-hoc
# `life-platform-s3-bucket-size-high` alarm, which fires on the SUM across every
# prefix and cannot name which one drifted. Compared by rule ID against the same
# JSON `apply_s3_lifecycle.sh` PUTs verbatim (single writer, #886): a declared ID
# absent live, a live ID absent from the declaration, or a rule whose Filter /
# Expiration / NoncurrentVersionExpiration / Transitions / AbortIncompleteMultipartUpload
# differs is drift.
_LIFECYCLE_COMPARE_KEYS = (
    "Filter",
    "Status",
    "Expiration",
    "NoncurrentVersionExpiration",
    "Transitions",
    "AbortIncompleteMultipartUpload",
)


def _lifecycle_rule_diff(expected_rule, live_rule):
    """True if any comparison-relevant field differs between the declared and
    live version of the SAME rule ID (caller has already matched them by ID)."""
    return any(expected_rule.get(k) != live_rule.get(k) for k in _LIFECYCLE_COMPARE_KEYS)


def check_s3_lifecycle():
    """The live S3 lifecycle configuration must match deploy/s3_lifecycle.json
    exactly — the same file `apply_s3_lifecycle.sh` PUTs verbatim, so this is a
    declared-vs-live comparison with a single writer on the declared side (never a
    second, independently-maintained expectation to drift against the first)."""
    try:
        with open(os.path.join(_ROOT, "deploy", "s3_lifecycle.json")) as f:
            expected_cfg = json.load(f)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"read declared s3_lifecycle.json: {e}"}
    expected = {r["ID"]: r for r in expected_cfg.get("Rules", [])}

    try:
        s3 = _client("s3")
        live_cfg = s3.get_bucket_lifecycle_configuration(Bucket=BUCKET)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"get_bucket_lifecycle_configuration: {e}"}
    live = {r["ID"]: r for r in live_cfg.get("Rules", [])}

    missing = sorted(set(expected) - set(live))
    extra = sorted(set(live) - set(expected))
    changed = sorted(rid for rid in (set(expected) & set(live)) if _lifecycle_rule_diff(expected[rid], live[rid]))

    status = "drift" if (missing or extra or changed) else "clean"
    result = {
        "status": status,
        "missing_rule_ids": missing,
        "extra_rule_ids": extra,
        "changed_rule_ids": changed,
        "expected_count": len(expected),
        "live_count": len(live),
    }
    if status == "drift":
        parts = []
        if missing:
            parts.append(f"declared but missing live: {missing}")
        if extra:
            parts.append(f"live but not declared: {extra}")
        if changed:
            parts.append(f"present both sides but differ: {changed}")
        result["detail"] = "; ".join(parts)
    return result


def _fetch_live_version(url):
    """GET /version.json and parse it. Raises on any network/parse failure — the
    caller turns that into a soft 'error' status, never a crash."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 — fixed https URL
        return json.loads(r.read())


def _git_fetch_main():
    """Best-effort `git fetch origin main` so the local ref is current. Non-fatal:
    a stale-but-present ref is still useful, so failures are swallowed."""
    import subprocess

    subprocess.run(["git", "fetch", "origin", "main", "--quiet"], check=True, capture_output=True, cwd=_ROOT, timeout=30)


def _merge_base_is_ancestor(sha, ref="origin/main"):
    """Return the `git merge-base --is-ancestor` CompletedProcess (returncode 0 = sha
    is an ancestor of/equal to ref; 1 = exists but diverged; 128 = sha unknown)."""
    import subprocess

    return subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref], cwd=_ROOT, capture_output=True, timeout=30)


def check_site_sha_ancestry():
    """#751: the LIVE site's /version.json build SHA must be an ancestor of (or equal
    to) origin/main HEAD. CI's I22 (tests/test_integration_aws.py) catches this right
    after a deploy, but only runs on a deploy and needs a full-history checkout. This is
    the STANDING scheduled check that catches drift BETWEEN deploys — e.g. a manual
    site sync from a stale/unmerged branch, or a rollback that never got a matching
    merge. Read-only: one HTTPS GET + a local `git merge-base --is-ancestor`."""
    url = os.environ.get("SITE_VERSION_URL", "https://averagejoematt.com/version.json")
    try:
        version_data = _fetch_live_version(url)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"fetch {url}: {e}"}

    live_sha = (version_data.get("build") or "").strip()
    if not live_sha:
        return {"status": "error", "detail": "version.json has no 'build' field"}

    try:
        _git_fetch_main()
    except Exception:  # noqa: BLE001 — non-fatal; fall back to whatever ref is local
        pass

    try:
        result = _merge_base_is_ancestor(live_sha)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"merge-base check: {e}", "live_sha": live_sha}

    if result.returncode == 0:
        return {"status": "clean", "live_sha": live_sha}
    if result.returncode == 128:
        return {
            "status": "drift",
            "live_sha": live_sha,
            "detail": f"live SHA {live_sha!r} not found in git history at all — deployed from an unmerged branch or a different clone",
        }
    return {
        "status": "drift",
        "live_sha": live_sha,
        "detail": f"live SHA {live_sha!r} exists but is not an ancestor of origin/main — site has diverged from main",
    }


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


# ── 6/7. GitHub config posture (#1320) + main-push run liveness (#1544) ──────
# Extracted to sentinel_github.py (module-size ceiling #1665, same split shape as
# sentinel_quota.py below). Imported here so run_sweep and existing callers/tests
# keep the ds.check_github_config / ds.check_github_push_runs names; GitHub-internal
# fakes must patch sentinel_github directly (a re-export is not a patch point).
from sentinel_github import (  # noqa: E402,F401,I001
    DEFAULT_REPO,
    GITHUB_POSTURE_FILE,
    PAT_FIX,
    PUSH_TRIGGER_GLOBS,
    _commit_files,
    _gh_api_result,
    _github_repo,
    _is_bot_commit,
    _judge_required_checks,
    _load_github_posture,
    _matches_push_trigger,
    _parse_gh_date,
    check_github_config,
    check_github_push_runs,
)

# ── 8. GitHub quota/billing observability (#1334, #1453, #1613) ─────────────
# Extracted to sentinel_quota.py (module-size ceiling #1665). Imported here so
# run_sweep and existing callers/tests keep the ds.check_github_quota name;
# quota-internal fakes patch sentinel_quota directly.
from sentinel_quota import (  # noqa: E402,F401
    GITHUB_ACTIONS_INCLUDED_MINUTES,
    GITHUB_ACTIONS_WARN_PCT,
    _gh_api_json,
    _gh_run_list_trailing,
    _run_duration_seconds,
    check_github_quota,
)

# ── 9. CodeQL open-alert regrowth (#1902) ────────────────────────────────────
#
# The 2026-08 triage (#1902) drove the open-alert list on main to zero: every
# alert was either fixed or dismissed with a written reason. From then on, an
# OPEN alert is by definition un-triaged — so the steady-state budget is 0 and
# any count above it is drift (a genuinely new finding, or a fixed one that
# regressed). NB a just-merged fix stays open until CodeQL's next analysis of
# main; that window self-clears within one push cycle and is not worth a grace
# knob.
#
# #2578 AUTOPSY (2026-08-24) — this check shipped armed and has never once read the
# API. Every persisted sentinel record since it landed (drift-log/2026-08-03,
# -08-10, -08-24) carries `codeql_alerts: {"status": "error"}`, 3/3, while 7 open
# alerts (2 high) sat 13–14 days un-triaged on main. Three independent defects, all
# fixed here + in the workflow's permissions block:
#
#   (a) CREDENTIAL — the check called `sentinel_quota._gh_api_json`, whose #1613
#       contract is to swap GH_TOKEN for GH_BILLING_TOKEN/GH_POSTURE_TOKEN whenever
#       either is set. GH_BILLING_TOKEN IS set live (repo secret since 2026-07-26),
#       so every code-scanning GET went out on a billing-scoped user PAT. Now uses
#       `_gh_api_result` (the #1320 classified GET) via `_codeql_api`, which also
#       retries on the ambient token when the posture PAT is scope-gapped.
#   (b) PERMISSION — .github/workflows/remediation-agent.yml declares an explicit
#       `permissions:` block, which zeroes every unlisted scope. It never granted
#       `security-events: read`, which GET /code-scanning/alerts requires, so even
#       the built-in GITHUB_TOKEN 403'd. Granted in that workflow by this change.
#   (c) FAIL-SOFT — an unreadable list returned `status: "error"`, and `error` is
#       NOT `drift`: `remediation/drift_report.as_signal` only emits a needs-human
#       triage signal for `drift`, and only checks whose own status is `drift` land
#       in its `flagging` map. The check's entire trace was one clause at the tail
#       of a summary already reading "6 stack(s) drifted; …". Surfacing that lands
#       nowhere is the same as not firing — so an unreadable list is now DRIFT.
# ── 10. raw/ cross-region backup (DIL-027, #3042) ────────────────────────────
# Own module (same split shape as sentinel_github/sentinel_quota): the backup is
# the platform's only protection for unrecomputable data, and a replication
# configuration is exactly the control that gets verified once and believed
# forever. Read that module's docstring for what it can and cannot fail on.
from sentinel_replication import check_raw_replication  # noqa: E402,F401

# ── 11. sentinel cadence dead-man (#3130) ─────────────────────────────────────
# Own module (same split shape as sentinel_github/sentinel_quota/sentinel_replication):
# a self-report at the START of each run asserting the PREVIOUS run(s) left a
# drift-log record, so a sentinel run that dies before persist() is caught by the
# NEXT run rather than vanishing silently (the #3112 autopsy: the 2026-08-17 run
# failed outright and nothing noticed the 08-10 → 08-24 gap). Read that module's
# docstring for the mechanism choice (self-report over a new CloudWatch alarm) and
# the #2578 fail-closed precedent it mirrors.
from sentinel_cadence import check_sentinel_cadence  # noqa: E402,F401

CODEQL_ALERT_BUDGET = 0

# The one-time fix for a scope-gapped code-scanning read (#2578), carried in the
# finding itself so the report names the remedy instead of "auth/scope?".
CODEQL_SCOPE_FIX = (
    "fix: grant `security-events: read` in the calling workflow's `permissions:` block "
    "(GET /code-scanning/alerts is 403 without it), and give any PAT that overrides the "
    "ambient GITHUB_TOKEN the repository permission `Code scanning alerts: read`"
)


def _codeql_api(path, timeout=60):
    """Classified GET of the code-scanning API on a credential that can actually read it.

    Deliberately NOT `sentinel_quota._gh_api_json` — see defect (a) above. Prefers the
    posture PAT (that is `_gh_api_result`'s contract) but retries ONCE on the ambient
    GITHUB_TOKEN when the PAT comes back scope-gapped, so adding a PAT without
    `Code scanning alerts: read` cannot re-dark this check the way GH_BILLING_TOKEN did.

    Returns `_gh_api_result`'s `(data, errinfo)` pair."""
    data, err = _gh_api_result(path, timeout=timeout)
    if err and err.get("classification") == "scope" and os.environ.get("GH_POSTURE_TOKEN"):
        saved = os.environ.pop("GH_POSTURE_TOKEN")
        try:
            data, err = _gh_api_result(path, timeout=timeout)
        finally:
            os.environ["GH_POSTURE_TOKEN"] = saved
    return data, err


def check_codeql_alerts():
    data, err = _codeql_api("repos/{owner}/{repo}/code-scanning/alerts?state=open&per_page=100")
    if err or not isinstance(data, list):
        # FAIL CLOSED (#2578, defect (c)): an alert list we cannot read is
        # indistinguishable from an un-triaged one, and proving main is triaged is the
        # entire job of this check. "Couldn't run" is therefore drift — it reaches
        # drift_report.as_signal's needs-human triage path, which `error` never did.
        detail = (err or {}).get("detail") or "code-scanning API returned a non-list body"
        return {
            "status": "drift",
            "reason": "unreadable",
            "open_count": None,
            "sample": [],
            "detail": f"CodeQL alert list UNREADABLE — cannot prove main is triaged ({detail}). {CODEQL_SCOPE_FIX}",
        }
    n = len(data)
    sample = []
    for a in data[:10]:
        loc = (a.get("most_recent_instance") or {}).get("location") or {}
        sample.append(f"{(a.get('rule') or {}).get('id')} @ {loc.get('path')}:{loc.get('start_line')}")
    drifted = n > CODEQL_ALERT_BUDGET
    result = {
        "status": "drift" if drifted else "clean",
        "reason": "regrowth" if drifted else "triaged",
        "open_count": n,
        "sample": sample,
    }
    if drifted:
        result["detail"] = (
            f"{n} open CodeQL alert(s) on main (budget {CODEQL_ALERT_BUDGET}) — triage each to fixed or "
            "dismissed-with-reason (#1902); a fix merged since the last CodeQL analysis of main clears on its own"
        )
    return result


# ── 10. HAE webhook ingress parity (#1946) ───────────────────────────────────
#
# A pre-IaC console-created HTTP API (`health-auto-export-api`, id a76xwxt2wa,
# `"tags": {}` — no CloudFormation owner) coexisted with the CDK-managed one
# for months after the July IaC cutover, each holding its own apigateway-invoke
# grant on `health-auto-export-webhook` — the orphan's scoped to the wildcard
# `/*/*` (every stage/method/route) vs. the CDK statement's route-scoped
# `/*/*/ingest`. Guard-the-SET: the expected API id is DERIVED live from
# LifePlatformIngestion's own `AWS::ApiGatewayV2::Api` resource, never
# hand-pasted, so a stack replacement (new physical id) doesn't false-positive
# and a THIRD console-created API doesn't go unnoticed either.
HAE_WEBHOOK_FUNCTION = "health-auto-export-webhook"
HAE_INGESTION_STACK = "LifePlatformIngestion"
# Mirrors the POST /ingest route CDK declares (add_routes() in
# cdk/stacks/ingestion_stack.py) — HttpLambdaIntegration auto-grants exactly
# this SourceArn suffix; any other suffix (or the bare `/*/*` wildcard) is a
# wider-than-declared grant.
HAE_ROUTE_SOURCE_ARN_SUFFIX = "/*/*/ingest"


def get_cdk_managed_hae_api_id(cfn=None):
    """Derive the CDK-managed HAE webhook API's physical id from LifePlatformIngestion's
    own `AWS::ApiGatewayV2::Api` resource — never a hand-pasted literal (guard-the-SET).

    Returns `(api_id, error)`: exactly one of the two is non-None/non-empty. `error` is a
    human-readable string when the stack didn't resolve to exactly one such resource
    (a genuinely unexpected shape, not "no orphan found" — that's a separate question).
    Shared by `check_hae_webhook_ingress` (drift check) and `teardown_hae_orphan_api.py`
    (the owner-run cleanup), so both agree on what "CDK-managed" means."""
    cfn = cfn or _client("cloudformation")
    try:
        cdk_api_ids = []
        token = None
        while True:
            kw = {"StackName": HAE_INGESTION_STACK}
            if token:
                kw["NextToken"] = token
            resp = cfn.list_stack_resources(**kw)
            for r in resp.get("StackResourceSummaries", []):
                if r.get("ResourceType") == "AWS::ApiGatewayV2::Api" and r.get("PhysicalResourceId"):
                    cdk_api_ids.append(r["PhysicalResourceId"])
            token = resp.get("NextToken")
            if not token:
                break
    except Exception as e:  # noqa: BLE001
        return None, f"list_stack_resources({HAE_INGESTION_STACK}): {e}"

    if len(cdk_api_ids) != 1:
        return None, f"expected exactly 1 AWS::ApiGatewayV2::Api in {HAE_INGESTION_STACK}, found {len(cdk_api_ids)}: {cdk_api_ids}"
    return cdk_api_ids[0], None


def check_hae_webhook_ingress():
    """The webhook Lambda's resource policy must carry EXACTLY ONE apigateway
    invoke grant, scoped to the CDK-managed API's declared POST /ingest route.

    A second grant (an orphan console-created API, #1946) or a widened
    SourceArn (the bare `/*/*` wildcard instead of `/*/*/ingest`) is the
    unmanaged-ingress defect class this closes."""
    cdk_api_id, err = get_cdk_managed_hae_api_id()
    if err:
        return {"status": "error", "detail": err}
    expected_suffix = f"{cdk_api_id}{HAE_ROUTE_SOURCE_ARN_SUFFIX}"

    try:
        lam = _client("lambda")
        policy = json.loads(lam.get_policy(FunctionName=HAE_WEBHOOK_FUNCTION)["Policy"])
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"get_policy({HAE_WEBHOOK_FUNCTION}): {e}"}

    invoke_statements = []
    for stmt in policy.get("Statement", []):
        principal = stmt.get("Principal") or {}
        if principal.get("Service") != "apigateway.amazonaws.com":
            continue
        source_arn = ((stmt.get("Condition") or {}).get("ArnLike") or {}).get("AWS:SourceArn", "")
        invoke_statements.append({"sid": stmt.get("Sid"), "source_arn": source_arn})

    if len(invoke_statements) != 1:
        return {
            "status": "drift",
            "cdk_api_id": cdk_api_id,
            "invoke_statements": invoke_statements,
            "detail": (
                f"expected exactly 1 apigateway-invoke statement on {HAE_WEBHOOK_FUNCTION}, "
                f"found {len(invoke_statements)} — an out-of-IaC ingress grant"
            ),
        }

    source_arn = invoke_statements[0]["source_arn"]
    if not source_arn.endswith(expected_suffix):
        return {
            "status": "drift",
            "cdk_api_id": cdk_api_id,
            "invoke_statements": invoke_statements,
            "detail": (
                f"invoke grant SourceArn {source_arn!r} does not match the CDK-managed API's "
                f"declared route (expected suffix {expected_suffix!r}) — wider-than-declared grant"
            ),
        }

    return {"status": "clean", "cdk_api_id": cdk_api_id, "invoke_statements": invoke_statements}


# ── Assemble + persist ───────────────────────────────────────────────────────


def run_sweep():
    checks = {
        "cfn_drift": check_cfn_drift(),
        **check_postflight(),
        "orphan_functions": check_orphan_functions(),
        "bucket_policy": check_bucket_policy(),
        "s3_lifecycle": check_s3_lifecycle(),
        "oidc_iam": check_oidc_iam(),
        "doc_literals": check_doc_literals(),
        "site_sha_ancestry": check_site_sha_ancestry(),
        "github_config": check_github_config(),
        "github_push_runs": check_github_push_runs(),
        "github_quota": check_github_quota(),
        "codeql_alerts": check_codeql_alerts(),
        "hae_webhook_ingress": check_hae_webhook_ingress(),
        "raw_replication": check_raw_replication(),
        "sentinel_cadence": check_sentinel_cadence(),
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
        ("s3_lifecycle", "S3 lifecycle configuration diverges from declared rules"),
        ("doc_literals", "doc-literal drift"),
        ("site_sha_ancestry", "live site SHA not on main"),
        ("github_config", "GitHub config diverges from documented posture"),
        ("github_push_runs", "main-push workflow runs not queuing"),
        ("hae_webhook_ingress", "HAE webhook ingress grant drift"),
        ("raw_replication", "raw/ cross-region backup not verified"),
        ("sentinel_cadence", "sentinel cadence gap — a missed/stale weekly drift-log record"),
    ):
        c = checks.get(key, {})
        if c.get("status") == "drift":
            parts.append(label)
    # codeql_alerts has TWO drift shapes and a fixed label would lie about one of them
    # (#2578): real regrowth vs. an unreadable list. Both are drift; say which.
    cq = checks.get("codeql_alerts", {})
    if cq.get("status") == "drift":
        parts.append(
            "CodeQL alert list UNREADABLE (fail-closed)"
            if cq.get("reason") == "unreadable"
            else f"{cq.get('open_count')} un-triaged open CodeQL alert(s)"
        )
    gq = checks.get("github_quota", {})
    if gq.get("status") == "drift" and gq.get("warn"):
        parts.append(gq["warn"])
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
        mark = {"clean": "🟢", "drift": "🔴", "error": "🟡", "degraded": "🟡", "unavailable": "⚪"}.get(st, "·")
        detail = ""
        if st == "drift":
            if name == "cfn_drift":
                ds = [s for s, v in c.get("stacks", {}).items() if v.get("status") == "drift"]
                detail = f" — {', '.join(ds)}"
            elif name == "orphan_functions":
                detail = f" — {', '.join(c.get('orphans', []))}"
            elif name == "bucket_policy":
                detail = f" — missing {c.get('missing_prefixes')}"
            elif name == "s3_lifecycle":
                detail = f" — {c.get('detail', '')}"
            elif name == "config_drift":
                detail = f" — {[i.get('function') for i in c.get('items', [])]}"
            elif name == "layer_uniformity":
                detail = f" — {[b.get('function') for b in c.get('behind', [])]}"
            elif name == "asset_completeness":
                detail = f" — {[i.get('function') for i in c.get('incomplete', [])]}"
            elif name == "doc_literals":
                detail = f" — {[(m['fact'], m['documented'], 'live', m['live']) for m in c.get('mismatches', [])]}"
            elif name == "site_sha_ancestry":
                detail = f" — {c.get('detail', '')}"
            elif name == "github_config":
                bad = {k: v.get("detail", "") for k, v in c.get("surfaces", {}).items() if v.get("status") == "drift"}
                detail = f" — {bad}"
            elif name == "github_push_runs":
                detail = f" — {c.get('detail', '')}"
            elif name == "github_quota":
                detail = f" — {c.get('warn', '')}"
            elif name == "codeql_alerts":
                # #2578: a drift line with no detail is a finding nobody can act on.
                detail = f" — {c.get('detail', '')}"
            elif name == "raw_replication":
                detail = f" — {c.get('detail', '')}"
            elif name == "sentinel_cadence":
                detail = f" — {c.get('detail', '')}"
        elif st == "degraded":
            # DIL-027: "could not observe" is a distinct verdict from clean and must
            # print its reason — a check that sampled nothing has not passed.
            detail = f" — {c.get('detail', '')}"

        elif st == "error":
            detail = f" — {c.get('detail', '')}"
        print(f"   {mark} {name}: {st}{detail}")
        # #1781: known-CFN-noise PropertyDifferences are never silently dropped — a
        # per-stack count always prints (whether the stack is clean or drift) so the
        # filter stays honest and visible.
        if name == "cfn_drift":
            noisy = {s: len(v.get("filtered_noise", [])) for s, v in c.get("stacks", {}).items() if v.get("filtered_noise")}
            if noisy:
                print(f"      [filtered known-noise, #1781] {noisy}")
        # #1320 fail-soft honesty: a scope-gapped GitHub surface surfaces its
        # needs-owner line (the exact PAT permission to add) — visible, never red.
        if name in ("github_config", "github_push_runs") and c.get("needs_owner"):
            print(f"      [needs-owner] {c['needs_owner']}")
        # GitHub quota/billing facts always print, regardless of status (#1334/#1453 —
        # this is a monthly-glance line, not just an alert): the real usage pct when
        # the billing API is available, the fail-soft reason when it isn't, and the
        # top-consuming workflows either way so run-rate regressions are attributable.
        if name == "github_quota":
            b = c.get("billing_api", {})
            if b.get("available"):
                print(f"      Actions minutes used: {b.get('total_minutes_used')}/{b.get('included_minutes')} ({b.get('pct_used')}%)")
            else:
                print(f"      {b.get('detail', 'billing API unavailable')}")
            for w in c.get("top_workflows_7d", [])[:5]:
                print(f"      · {w['workflow']}: {w['wall_clock_minutes']} min (7d wall-clock proxy)")
            if c.get("top_workflows_error"):
                print(f"      [warn] top-workflows proxy: {c['top_workflows_error']}")


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
