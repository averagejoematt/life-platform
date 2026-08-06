#!/usr/bin/env python3
"""
deploy/teardown_hae_orphan_api.py — retire the pre-IaC health-ingest API (#1946).

A pre-IaC console-created HTTP API (`health-auto-export-api`, id a76xwxt2wa,
created 2026-02-24, `"tags": {}` — no CloudFormation owner) has coexisted with
the CDK-managed one (`LifePlatformIngestion`'s `HaeWebhookApi`) since the July
IaC cutover. Both route `POST /ingest` to the same `health-auto-export-webhook`
Lambda; both hold their own `lambda:InvokeFunction` resource-policy grant — the
orphan's scoped to the wildcard `arn:...:execute-api:...:<id>/*/*` (every
stage/method/route) vs. the CDK statement's route-scoped `.../*/*/ingest`.
Measured 2026-08-05: the orphan API has taken **zero requests in the trailing
7 days** (`AWS/ApiGateway Count`, empty datapoint set) while the CDK-managed
API served 15-26/day over the same window — the cutover is complete; only the
teardown was never executed.

This script:
  1. DERIVES the CDK-managed API id live from `LifePlatformIngestion`'s own
     `AWS::ApiGatewayV2::Api` resource (guard-the-SET, shared with
     `deploy/drift_sentinel.check_hae_webhook_ingress` via
     `get_cdk_managed_hae_api_id()` — never a hand-pasted literal, so this
     still does the right thing after a stack replacement, or if a THIRD
     console-created API shows up).
  2. Finds every live `health-auto-export-api` that is NOT that id — the
     orphan set (expected: just a76xwxt2wa today, but nothing here assumes
     that literal).
  3. RE-MEASURES zero-traffic for each orphan (AWS/ApiGateway Count, trailing
     N days, default 7) before touching anything — the acceptance criterion
     for this teardown is "re-run the zero-traffic measurement on deletion
     day," not trust a stale finding.
  4. Deletes each still-zero-traffic orphan API (`--apply` only) and revokes
     its Lambda invoke grant(s) on `health-auto-export-webhook`.

Idempotent: run it again after a successful `--apply` and it reports "nothing
to do" (the orphan is already gone from both the API list and the resource
policy) rather than erroring.

Usage:
    python3 deploy/teardown_hae_orphan_api.py                    # dry-run (default): prints, deletes nothing
    python3 deploy/teardown_hae_orphan_api.py --apply             # actually delete
    python3 deploy/teardown_hae_orphan_api.py --lookback-days 14  # widen the re-measurement window
    python3 deploy/teardown_hae_orphan_api.py --apply --force     # delete even if traffic was seen (NOT recommended)

Before running --apply: confirm the Health Auto Export phone-app config points
at the CDK-managed API (the id this script prints as "CDK-managed API (kept)")
— see docs/RUNBOOK.md's Apple Health section. This script only measures
CloudWatch traffic on the ORPHAN; it cannot see the phone's configured
endpoint.

This is an AWS-mutating script — run it attended, through the normal deploy
path (CLAUDE.md: "Deploys happen from main, by the driver, after merge"), not
from a worktree branch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drift_sentinel import HAE_WEBHOOK_FUNCTION, get_cdk_managed_hae_api_id  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")
HAE_API_NAME = "health-auto-export-api"
DEFAULT_LOOKBACK_DAYS = 7


def _client(service, region=REGION):
    import boto3

    return boto3.client(service, region_name=region)


def list_hae_apis(apigw):
    """Every live HTTP API named `health-auto-export-api` (paginated)."""
    items = []
    token = None
    while True:
        kw = {}
        if token:
            kw["NextToken"] = token
        resp = apigw.get_apis(**kw)
        items.extend(resp.get("Items", []))
        token = resp.get("NextToken")
        if not token:
            break
    return [a for a in items if a.get("Name") == HAE_API_NAME]


def find_orphan_apis(apigw=None, cfn=None):
    """Every live `health-auto-export-api` that is NOT the CDK-managed one.

    Returns `(orphans, cdk_api_id)`. Raises RuntimeError if the CDK-managed id
    can't be derived (an unexpected shape in LifePlatformIngestion — abort
    rather than guess)."""
    apigw = apigw or _client("apigatewayv2")
    cdk_api_id, err = get_cdk_managed_hae_api_id(cfn)
    if err:
        raise RuntimeError(f"could not derive the CDK-managed API id: {err}")

    apis = list_hae_apis(apigw)
    orphans = [a for a in apis if a.get("ApiId") != cdk_api_id]
    return orphans, cdk_api_id


def measure_traffic(api_id, days=DEFAULT_LOOKBACK_DAYS, cw=None):
    """Sum of `AWS/ApiGateway Count` over the trailing `days` days. Returns
    `(total_requests, datapoint_count)`."""
    cw = cw or _client("cloudwatch")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    resp = cw.get_metric_statistics(
        Namespace="AWS/ApiGateway",
        MetricName="Count",
        Dimensions=[{"Name": "ApiId", "Value": api_id}],
        StartTime=start,
        EndTime=end,
        Period=86400,
        Statistics=["Sum"],
    )
    datapoints = resp.get("Datapoints", [])
    total = sum(dp.get("Sum", 0) for dp in datapoints)
    return total, len(datapoints)


def find_orphan_lambda_grants(function_name, orphan_api_ids, lam=None):
    """Apigateway-invoke resource-policy statements on `function_name` whose
    SourceArn references one of `orphan_api_ids`. Fail-soft to `[]` if the
    function has no resource policy at all (nothing to revoke)."""
    lam = lam or _client("lambda")
    try:
        policy = json.loads(lam.get_policy(FunctionName=function_name)["Policy"])
    except Exception as e:  # noqa: BLE001 — covers ResourceNotFoundException (no policy) and transient errors alike
        if "ResourceNotFoundException" in type(e).__name__ or "ResourceNotFoundException" in str(e):
            return []
        raise
    hits = []
    for stmt in policy.get("Statement", []):
        principal = stmt.get("Principal") or {}
        if principal.get("Service") != "apigateway.amazonaws.com":
            continue
        source_arn = ((stmt.get("Condition") or {}).get("ArnLike") or {}).get("AWS:SourceArn", "")
        if any(f":{oid}/" in source_arn or source_arn.endswith(f":{oid}") for oid in orphan_api_ids):
            hits.append({"sid": stmt.get("Sid"), "source_arn": source_arn})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry-run, deletes nothing)")
    ap.add_argument(
        "--force",
        action="store_true",
        help="delete even if the re-measurement finds non-zero traffic in the lookback window (NOT recommended)",
    )
    ap.add_argument(
        "--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS, help=f"traffic re-measurement window (default {DEFAULT_LOOKBACK_DAYS})"
    )
    args = ap.parse_args()

    print("life-platform HAE orphan-API teardown (#1946)")
    print(f"region={REGION}  mode={'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    try:
        orphans, cdk_api_id = find_orphan_apis()
    except RuntimeError as e:
        print(f"ABORT: {e}")
        return 1
    print(f"CDK-managed API (kept): {cdk_api_id}")

    if not orphans:
        # Also check for a stray Lambda grant with no matching API at all (e.g. an
        # API deleted out of band but its permission statement left behind) —
        # nothing to derive an "orphan API id" from there, so this pass only
        # reports the clean case. The drift gate (check_hae_webhook_ingress)
        # covers a stray-grant-with-no-API shape independently.
        print(f"No orphan {HAE_API_NAME} found outside CloudFormation. Nothing to do.")
        return 0

    orphan_ids = [a["ApiId"] for a in orphans]
    print(f"orphan API(s) found: {', '.join(orphan_ids)}")

    exit_code = 0
    apis_to_grant_cleanup = []
    for api in orphans:
        api_id = api["ApiId"]
        print(f"\n--- {api_id} ---")
        print(f"  name: {api.get('Name')}  created: {api.get('CreatedDate')}  tags: {api.get('Tags') or {}}")

        total, n_datapoints = measure_traffic(api_id, args.lookback_days)
        print(f"  AWS/ApiGateway Count, trailing {args.lookback_days}d: {total} request(s) across {n_datapoints} datapoint(s)")
        if total > 0 and not args.force:
            print("  SKIP: non-zero traffic in the lookback window.")
            print(f"        Confirm the HAE phone-app config points at the CDK-managed API ({cdk_api_id})")
            print("        before deleting. Pass --force to delete anyway (not recommended).")
            exit_code = 1
            continue

        apis_to_grant_cleanup.append(api_id)
        if not args.apply:
            print(f"  (dry-run) would delete API {api_id}")
            continue

        apigw = _client("apigatewayv2")
        try:
            apigw.delete_api(ApiId=api_id)
            print(f"  deleted API {api_id}")
        except Exception as e:  # noqa: BLE001
            if "NotFoundException" in type(e).__name__:
                print(f"  API {api_id} already gone (idempotent no-op)")
            else:
                print(f"  ERROR deleting API {api_id}: {e}")
                exit_code = 1

    grants = find_orphan_lambda_grants(HAE_WEBHOOK_FUNCTION, apis_to_grant_cleanup)
    if grants:
        print(f"\norphan Lambda invoke grant(s) on {HAE_WEBHOOK_FUNCTION}:")
        for g in grants:
            print(f"  sid={g['sid']} source_arn={g['source_arn']}")
        if args.apply:
            lam = _client("lambda")
            for g in grants:
                try:
                    lam.remove_permission(FunctionName=HAE_WEBHOOK_FUNCTION, StatementId=g["sid"])
                    print(f"  revoked {g['sid']}")
                except Exception as e:  # noqa: BLE001
                    if "ResourceNotFoundException" in type(e).__name__:
                        print(f"  {g['sid']} already gone (idempotent no-op)")
                    else:
                        print(f"  ERROR revoking {g['sid']}: {e}")
                        exit_code = 1
        else:
            print("  (dry-run) would revoke the grant(s) above")
    elif apis_to_grant_cleanup:
        print(f"\nno orphan Lambda invoke grant(s) found on {HAE_WEBHOOK_FUNCTION} for the API(s) above.")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to execute.")
        print("NEXT after --apply: python3 deploy/check_hae_webhook_ingress_drift.py   (expect status=clean)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
