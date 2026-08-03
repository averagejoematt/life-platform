#!/usr/bin/env python3
"""config_twin_sync.py — the deploy path + drift check for bucket-root `config/` (#2019).

Bucket-root `config/` was the third deploy prefix with NO deploy path. A merged
change to a repo `config/` file never reached S3, and three stacked layers hid
it: no sync step, a no-TTL warm-container cache in the site-api Lambda, and a
3600s CloudFront TTL on `/api/*`. Measured live 2026-08-02: withdrawn citations
kept being served for ~13h after the withdrawal merged, with CI green throughout.

Two modes, and the read-only one is the DEFAULT:

    python3 deploy/config_twin_sync.py                # drift check (read-only)
    python3 deploy/config_twin_sync.py --strict       # …and exit 1 on drift
    python3 deploy/config_twin_sync.py --json         # machine-readable report
    python3 deploy/config_twin_sync.py --apply        # sync drifted twins to S3

`--apply` uploads EXPLICIT FILES ONLY — never `aws s3 sync`, never `--delete`,
never a prefix-level operation (ADR-032/033/046). Bucket-root `config/` also
holds Lambda-written runtime state and out-of-band objects
(`config/requirements/*`, an auth session pickle) that a prefix sync would
clobber or strip. The twin set is derived by `config_twin_registry` and
runtime-written keys are excluded there.

After a successful upload `--apply` also closes the two staleness layers that
made the incident invisible: it invalidates `/api/*` and recycles the site-api
Lambda's warm containers (a description-only update — no code, no config
change) so the freshly synced object actually starts serving.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_twin_registry import Twin, derive  # noqa: E402

S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
DISTRIBUTION_ID = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "E3S424OXQZ8NBE")
SITE_API_FUNCTION = os.environ.get("SITE_API_FUNCTION", "life-platform-site-api")

# Consumers under this tree are the public serving path — a drifted twin they
# read is actively being served to readers, so it invalidates + recycles.
SERVING_PATH_PREFIX = "lambdas/web/"
SERVING_INVALIDATION_PATH = "/api/*"

STATUS_OK = "ok"
STATUS_DRIFT = "drift"
STATUS_MISSING = "missing"
STATUS_ERROR = "error"

_ICON = {STATUS_OK: "🟢", STATUS_DRIFT: "🔴", STATUS_MISSING: "🔴", STATUS_ERROR: "🟡"}


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_twin(twin: Twin, s3) -> dict:
    """Compare repo bytes to the live S3 object. Read-only (GetObject)."""
    try:
        with open(twin.repo_path, "rb") as handle:
            local = handle.read()
    except OSError as exc:
        return {"key": twin.key, "status": STATUS_ERROR, "detail": f"repo read failed: {exc}"}

    try:
        remote = s3.get_object(Bucket=S3_BUCKET, Key=twin.key)["Body"].read()
    except Exception as exc:  # NoSuchKey, AccessDenied, transport errors
        if "NoSuchKey" in type(exc).__name__ or "NoSuchKey" in str(exc):
            return {
                "key": twin.key,
                "status": STATUS_MISSING,
                "detail": "no S3 object — the repo twin has never been deployed",
                "consumed": twin.consumed,
                "serving": _is_serving(twin),
            }
        return {"key": twin.key, "status": STATUS_ERROR, "detail": f"S3 read failed: {exc}"}

    local_sha, remote_sha = _sha256(local), _sha256(remote)
    return {
        "key": twin.key,
        "status": STATUS_OK if local_sha == remote_sha else STATUS_DRIFT,
        "local_sha256": local_sha,
        "s3_sha256": remote_sha,
        "consumed": twin.consumed,
        "serving": _is_serving(twin),
        "consumers": list(twin.consumers),
    }


def _is_serving(twin: Twin) -> bool:
    return any(module.startswith(SERVING_PATH_PREFIX) for module in twin.consumers)


def run_check(twins: list[Twin], s3) -> dict:
    results = [check_twin(twin, s3) for twin in twins]
    drifted = [r for r in results if r["status"] in (STATUS_DRIFT, STATUS_MISSING)]
    return {
        "bucket": S3_BUCKET,
        "twin_count": len(twins),
        "results": results,
        "drifted": [r["key"] for r in drifted],
        "serving_drift": [r["key"] for r in drifted if r.get("serving")],
        "errors": [r["key"] for r in results if r["status"] == STATUS_ERROR],
        "clean": not drifted,
    }


def apply_sync(report: dict, twins: list[Twin], s3, cloudfront=None, lambda_client=None) -> dict:
    """Upload the drifted twins — explicit files only, never a prefix sync."""
    by_key = {t.key: t for t in twins}
    uploaded, failed = [], []

    for key in report["drifted"]:
        twin = by_key[key]
        try:
            with open(twin.repo_path, "rb") as handle:
                body = handle.read()
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=body,
                ContentType="application/json" if key.endswith(".json") else "text/plain",
                CacheControl="max-age=60",
            )
            uploaded.append(key)
        except Exception as exc:
            failed.append({"key": key, "error": str(exc)})

    actions = {"uploaded": uploaded, "failed": failed, "invalidated": None, "recycled": None}
    if not uploaded:
        return actions

    # Only recycle/invalidate when the public serving path actually reads one of
    # the objects we just changed — otherwise this is a no-op cost.
    if any(_is_serving(by_key[key]) for key in uploaded):
        if cloudfront is not None:
            try:
                resp = cloudfront.create_invalidation(
                    DistributionId=DISTRIBUTION_ID,
                    InvalidationBatch={
                        "Paths": {"Quantity": 1, "Items": [SERVING_INVALIDATION_PATH]},
                        "CallerReference": f"config-twin-sync-{int(time.time())}",
                    },
                )
                actions["invalidated"] = resp["Invalidation"]["Id"]
            except Exception as exc:
                failed.append({"key": SERVING_INVALIDATION_PATH, "error": str(exc)})

        # Warm-container recycle: the site-api config caches are process-global.
        # A description-only update forces new containers without touching code,
        # env or IAM — the same move that remediated the incident by hand.
        if lambda_client is not None:
            try:
                lambda_client.update_function_configuration(
                    FunctionName=SITE_API_FUNCTION,
                    Description=f"config twin sync {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                )
                actions["recycled"] = SITE_API_FUNCTION
            except Exception as exc:
                failed.append({"key": SITE_API_FUNCTION, "error": str(exc)})

    return actions


def _print_human(report: dict, registry) -> None:
    print(f"config twin drift — s3://{report['bucket']}/config/ ({report['twin_count']} derived twins)")
    for result in report["results"]:
        if result["status"] == STATUS_OK:
            continue
        icon = _ICON[result["status"]]
        tag = " [SERVING]" if result.get("serving") else ""
        print(f"  {icon} {result['status'].upper():8} {result['key']}{tag}")
        if result.get("detail"):
            print(f"           {result['detail']}")
    if report["clean"]:
        print("  🟢 all derived twins match S3")
    else:
        print(f"\n  {len(report['drifted'])} drifted / {len(report['serving_drift'])} on the public serving path")
        print("  fix: python3 deploy/config_twin_sync.py --apply")
    if registry.unresolved_writers:
        print("\n  🟡 unresolvable config/ write sites (review — may need excluding):")
        for site in registry.unresolved_writers:
            print(f"     {site}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="upload drifted twins to S3 (default is read-only check)")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any derived twin has drifted")
    parser.add_argument("--json", action="store_true", dest="as_json", help="machine-readable report")
    parser.add_argument("--include-unconsumed", action="store_true", help="also check twins no deployed module reads")
    args = parser.parse_args()

    import boto3

    repo_root = _repo_root()
    registry = derive(repo_root)
    twins = [t for t in registry.twins if args.include_unconsumed or t.consumed]

    s3 = boto3.client("s3", region_name=AWS_REGION)
    report = run_check(twins, s3)

    if args.apply:
        report["apply"] = apply_sync(
            report,
            twins,
            s3,
            cloudfront=boto3.client("cloudfront", region_name="us-east-1"),
            lambda_client=boto3.client("lambda", region_name=AWS_REGION),
        )

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report, registry)
        if args.apply:
            actions = report["apply"]
            print(f"\n  uploaded: {len(actions['uploaded'])} · invalidated: {actions['invalidated']} · recycled: {actions['recycled']}")
            for failure in actions["failed"]:
                print(f"  🔴 FAILED {failure['key']}: {failure['error']}")

    if args.apply:
        return 1 if report["apply"]["failed"] else 0
    if args.strict and not report["clean"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
