#!/usr/bin/env python3
"""deploy/check_bucket_notification_drift.py — the S3 ingestion-trigger drift check (#4643).

Four ingestion paths start from an S3 event notification on `matthew-life-platform`:
MacroFactor CSVs, inbound insight email, food-delivery CSVs and tape-measurement imports.
The notifications live in ONE bucket-level document that CDK does not own — `cdk/stacks/`
only grants `s3.amazonaws.com` permission to invoke each function. A
`put-bucket-notification-configuration` call REPLACES the whole document, so one
out-of-band edit that forgets an entry silently disarms that trigger. Until this check,
nothing would notice short of the source going stale (60 days for measurements).

This compares the live document with `EXPECTED_NOTIFICATIONS` below, field by field:
the notification Id, the target function, the event list and the prefix/suffix filter.
It reports four kinds of difference:

  * missing     — an expected notification is not live (a dropped trigger)
  * unexpected  — a live notification this file does not list (an untracked trigger)
  * changed     — same Id, different function/events/filter (a re-pointed trigger)
  * non_lambda  — any Topic/Queue/EventBridge configuration (this bucket has none)

Read-only: one `s3:GetBucketNotification` call (`get_bucket_notification_configuration`).
It never writes S3 and never touches a Lambda. The repair is in docs/RUNBOOK.md,
"S3 bucket notifications (ingestion triggers outside CDK)".

Usage:
    python3 deploy/check_bucket_notification_drift.py                  # print, exit 0
    python3 deploy/check_bucket_notification_drift.py --strict         # exit 1 on drift or error
    python3 deploy/check_bucket_notification_drift.py --json           # machine-readable
    python3 deploy/check_bucket_notification_drift.py --fixture F.json # compare a saved document
"""

from __future__ import annotations

import argparse
import json
import os
import sys

BUCKET = "matthew-life-platform"
REGION = "us-west-2"

# The expected live set. Changing a notification means changing it here in the same PR
# (and in the bucket, through the runbook procedure). Prefix/Suffix of None means no rule.
EXPECTED_NOTIFICATIONS: tuple[dict, ...] = (
    {
        "id": "MacroFactorCSVIngest",
        "function": "macrofactor-data-ingestion",
        "events": ("s3:ObjectCreated:*",),
        "prefix": "uploads/macrofactor/",
        "suffix": ".csv",
    },
    {
        "id": "InboundEmailInsightParser",
        "function": "insight-email-parser",
        "events": ("s3:ObjectCreated:*",),
        "prefix": "raw/inbound_email/",
        "suffix": None,
    },
    {
        "id": "FoodDeliveryCSVIngest",
        "function": "food-delivery-ingestion",
        "events": ("s3:ObjectCreated:*",),
        "prefix": "imports/food_delivery/",
        "suffix": ".csv",
    },
    {
        "id": "MeasurementsCSVIngest",
        "function": "measurements-ingestion",
        "events": ("s3:ObjectCreated:*",),
        "prefix": "imports/measurements/",
        "suffix": None,
    },
)

_NON_LAMBDA_KEYS = ("TopicConfigurations", "QueueConfigurations", "EventBridgeConfiguration")


def _function_name(arn: str) -> str:
    # arn:aws:lambda:<region>:<acct>:function:<name>[:<qualifier>]
    parts = (arn or "").split(":")
    if len(parts) >= 7 and parts[5] == "function":
        return parts[6] + (f":{parts[7]}" if len(parts) > 7 else "")
    return arn or ""


def normalise_live(doc: dict) -> list[dict]:
    """Turn a GetBucketNotificationConfiguration response into the EXPECTED shape."""
    out = []
    for cfg in doc.get("LambdaFunctionConfigurations") or []:
        rules = {}
        for rule in ((cfg.get("Filter") or {}).get("Key") or {}).get("FilterRules") or []:
            rules[str(rule.get("Name", "")).lower()] = rule.get("Value")
        out.append(
            {
                "id": cfg.get("Id"),
                "function": _function_name(cfg.get("LambdaFunctionArn", "")),
                "events": tuple(sorted(cfg.get("Events") or [])),
                "prefix": rules.get("prefix"),
                "suffix": rules.get("suffix"),
            }
        )
    return out


def _canon(entry: dict) -> dict:
    return {**entry, "events": tuple(sorted(entry["events"]))}


def compare(doc: dict, expected: tuple[dict, ...] = EXPECTED_NOTIFICATIONS) -> dict:
    """Compare a live notification document with the expected set. Pure; no AWS."""
    live = normalise_live(doc)
    exp_by_id = {e["id"]: _canon(e) for e in expected}
    live_by_id: dict = {}
    duplicates = []
    for entry in live:
        if entry["id"] in live_by_id:
            duplicates.append(entry["id"])
        live_by_id[entry["id"]] = entry

    missing = [exp_by_id[i] for i in exp_by_id if i not in live_by_id]
    unexpected = [live_by_id[i] for i in live_by_id if i not in exp_by_id]
    changed = []
    for i, want in exp_by_id.items():
        got = live_by_id.get(i)
        if got is None:
            continue
        diffs = {k: {"expected": want[k], "live": got[k]} for k in ("function", "events", "prefix", "suffix") if want[k] != got[k]}
        if diffs:
            changed.append({"id": i, "diffs": diffs})
    non_lambda = [k for k in _NON_LAMBDA_KEYS if doc.get(k)]

    drift = bool(missing or unexpected or changed or non_lambda or duplicates)
    return {
        "status": "drift" if drift else "clean",
        "bucket": BUCKET,
        "expected_count": len(exp_by_id),
        "live_count": len(live),
        "live": live,
        "missing": missing,
        "unexpected": unexpected,
        "changed": changed,
        "non_lambda": non_lambda,
        "duplicate_ids": duplicates,
    }


def fetch_live(bucket: str = BUCKET, region: str = REGION) -> dict:
    import boto3  # lazy: the pure compare path (and its tests) needs no AWS SDK

    doc = boto3.client("s3", region_name=region).get_bucket_notification_configuration(Bucket=bucket)
    doc.pop("ResponseMetadata", None)
    return doc


def check(fixture: str | None = None) -> dict:
    try:
        if fixture:
            with open(fixture) as fh:
                doc = json.load(fh)
        else:
            doc = fetch_live()
    except Exception as exc:  # report, never mask: an unreadable document is not "clean"
        return {"status": "error", "bucket": BUCKET, "detail": f"{type(exc).__name__}: {exc}"}
    return compare(doc)


def _fmt(entry: dict) -> str:
    return f"{entry['id']} -> {entry['function']} events={list(entry['events'])} " f"prefix={entry['prefix']!r} suffix={entry['suffix']!r}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="exit non-zero on drift or error")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--fixture", help="compare a saved get-bucket-notification-configuration JSON instead of live")
    args = ap.parse_args(argv)

    result = check(args.fixture)
    status = result.get("status")

    if args.json:
        print(json.dumps(result, indent=2, default=list))
    else:
        source = args.fixture or f"s3://{BUCKET} (live)"
        print(f"bucket notification drift: {status}  [{source}]")
        if status == "error":
            print(f"  detail: {result.get('detail')}")
        else:
            print(f"  expected {result['expected_count']}, live {result['live_count']}")
            for entry in result["live"]:
                print(f"  live: {_fmt(entry)}")
            for entry in result["missing"]:
                print(f"  MISSING (trigger dropped): {_fmt(entry)}")
            for entry in result["unexpected"]:
                print(f"  UNEXPECTED (not in EXPECTED_NOTIFICATIONS): {_fmt(entry)}")
            for item in result["changed"]:
                print(f"  CHANGED {item['id']}: {item['diffs']}")
            for key in result["non_lambda"]:
                print(f"  NON-LAMBDA configuration present: {key}")
            for i in result["duplicate_ids"]:
                print(f"  DUPLICATE Id: {i}")
            if status == "drift":
                print('  FIX: docs/RUNBOOK.md -> "S3 bucket notifications (ingestion triggers outside CDK)"')

    if args.strict and status != "clean":
        return 1
    return 0


if __name__ == "__main__":
    os.environ.setdefault("AWS_REGION", REGION)
    sys.exit(main())
