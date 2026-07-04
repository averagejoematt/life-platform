#!/usr/bin/env python3
"""
audit_subscriber_ledger.py — one-off audit of the subscriber ledger.

Scans USER#matthew#SOURCE#subscribers, categorises every record as:
  synthetic  — source==canary or email prefix matches canary+*
  real       — confirmed subscribers
  expired    — pending_confirmation + token_expires in the past
  pending    — pending_confirmation + token still live
  tombstoned — previously cleaned up

Prints a summary and, with --purge-synthetics, deletes synthetic + tombstoned records.
With --resend-expired, re-sends a fresh confirmation token to expired-pending records
(only if the token is in the past and the record is not synthetic).

Run from repo root:
    python3 scripts/audit_subscriber_ledger.py
    python3 scripts/audit_subscriber_ledger.py --purge-synthetics
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import boto3

REGION = "us-west-2"
TABLE_NAME = "life-platform"
PK = "USER#matthew#SOURCE#subscribers"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purge-synthetics", action="store_true", help="Delete synthetic + tombstoned records")
    args = parser.parse_args()

    ddb = boto3.client("dynamodb", region_name=REGION)
    now = datetime.now(timezone.utc).isoformat()

    # Scan the subscribers partition
    items = []
    kwargs: dict = {
        "TableName": TABLE_NAME,
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": {"S": PK}},
    }
    while True:
        resp = ddb.query(**kwargs)
        items.extend(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    total = len(items)
    print(f"Total records: {total}")

    synthetic, real, expired, pending, tombstoned, other = [], [], [], [], [], []

    for item in items:
        sk = item.get("sk", {}).get("S", "")
        status = item.get("status", {}).get("S", "")
        source = item.get("source", {}).get("S", "")
        email = item.get("email", {}).get("S", "")
        token_exp = item.get("token_expires", {}).get("S", "")
        is_tomb = item.get("tombstone", {}).get("BOOL", False)

        is_synthetic = source == "canary" or email.startswith("canary+") or status.startswith("smoke_test_cleanup")

        if is_synthetic or is_tomb:
            (synthetic if is_synthetic else tombstoned).append(sk)
        elif status == "confirmed":
            real.append({"sk": sk, "email": email, "source": source})
        elif status == "pending_confirmation":
            if token_exp and token_exp < now:
                expired.append({"sk": sk, "email": email, "source": source, "token_expires": token_exp})
            else:
                pending.append({"sk": sk, "email": email, "source": source, "token_expires": token_exp})
        else:
            other.append({"sk": sk, "status": status, "source": source})

    print(f"\n  confirmed (real):          {len(real)}")
    for r in real:
        print(f"    {r['email']} (source={r['source']})")

    print(f"\n  pending (token live):      {len(pending)}")
    for p in pending[:5]:
        print(f"    {p['email']} expires={p['token_expires'][:10]} source={p['source']}")
    if len(pending) > 5:
        print(f"    ... and {len(pending) - 5} more")

    print(f"\n  expired pending:           {len(expired)}")
    for e in expired:
        print(f"    {e['email']} expired={e['token_expires'][:10]} source={e['source']}")

    print(f"\n  synthetic (canary):        {len(synthetic)}")
    print(f"  tombstoned:                {len(tombstoned)}")
    print(f"  other:                     {len(other)}")
    for o in other:
        print(f"    {o}")

    if args.purge_synthetics:
        to_delete = synthetic + tombstoned
        print(f"\nPurging {len(to_delete)} synthetic/tombstoned records...")
        deleted = 0
        for sk in to_delete:
            try:
                ddb.delete_item(
                    TableName=TABLE_NAME,
                    Key={"pk": {"S": PK}, "sk": {"S": sk}},
                )
                deleted += 1
            except Exception as exc:
                print(f"  WARN: could not delete {sk}: {exc}")
        print(f"Deleted {deleted}/{len(to_delete)} records.")
    else:
        print(f"\nRun with --purge-synthetics to delete {len(synthetic) + len(tombstoned)} synthetic/tombstoned records.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
