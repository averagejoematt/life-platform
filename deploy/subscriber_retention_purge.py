#!/usr/bin/env python3
"""
deploy/subscriber_retention_purge.py — purge/anonymize unsubscribed subscriber rows
after the retention window Matthew signs into docs/DATA_GOVERNANCE.md (#1350).

BACKGROUND
  lambdas/web/email_subscriber_lambda.py stores subscriber rows at
  pk=USER#{USER_ID}#SOURCE#subscribers / sk=EMAIL#{sha256(email)} with a PLAINTEXT
  `email` field. Historically (the "Raj directive" code comment) unsubscribed rows
  were NEVER hard-deleted — retained forever "for analytics", undocumented. #1350
  found that posture indefensible for the one PII class belonging to people other
  than Matthew, and required an owner-signed retention decision instead of an
  in-code directive attributed to a fictional persona.

NO DEFAULT WINDOW — --window-days is REQUIRED on every invocation, with no fallback.
  The choice of window is Matthew's signature: docs/DATA_GOVERNANCE.md's "Subscriber
  emails" retention-table row must be SIGNED (not "UNSIGNED — owner signs per #1350")
  before this script represents the authorized production posture. Running it before
  that is still SAFE (dry-run by default; --apply is an explicit, separate flag) but
  is not yet backed by a signed policy.

MODES
  --mode purge      hard-delete the DDB row (irreversible)
  --mode anonymize  scrub the plaintext `email` field + drop `ip_hash`, keep the sk
                     (the sha256 hash), `status`, and timestamps for aggregate
                     analytics; stamps `anonymized_at`

SCOPE — only rows with status == "unsubscribed" AND `unsubbed_at` older than the
  window are touched. Pending/confirmed subscribers are never touched by this script.
  Deleting ONE specific subscriber on request (right-to-be-forgotten, independent of
  the retention window) is a different path: lambdas/operational/delete_user_data_lambda.py
  via {"subscriber_email": "...", "confirm": "DELETE"} — see #1350.

ONE-COMMAND USAGE (after Matthew signs the window into DATA_GOVERNANCE.md)
  python3 deploy/subscriber_retention_purge.py --window-days 365 --mode anonymize --apply
  python3 deploy/subscriber_retention_purge.py --window-days 365 --mode purge          # dry run (no --apply)

Requires AWS credentials with dynamodb:Query/DeleteItem/UpdateItem on the life-platform
table (same access class as the other deploy/*.py one-off DDB scripts, e.g.
purge_stale_chronicle_drafts.py). This script is source only — running it is a live
DynamoDB write and is Matthew's call, not something a worktree agent executes.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ.get("TABLE_NAME", os.environ.get("LIFE_PLATFORM_TABLE", "life-platform"))
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
SUBSCRIBERS_PK = f"USER#{USER_ID}#SOURCE#subscribers"


def _is_purge_eligible(item: dict, cutoff_iso: str) -> bool:
    """True if `item` is an unsubscribed row whose unsubbed_at predates `cutoff_iso`.
    Pure function (no boto3) so it's directly unit-testable."""
    return item.get("status") == "unsubscribed" and bool(item.get("unsubbed_at")) and item["unsubbed_at"] < cutoff_iso


def _scan_unsubscribed(table, cutoff_iso: str) -> list[dict]:
    """Every subscriber row eligible for purge/anonymize as of `cutoff_iso`. Paginates
    the single subscribers partition (one Query per page — small partition, no scan)."""
    items: list[dict] = []
    resp = table.query(KeyConditionExpression=Key("pk").eq(SUBSCRIBERS_PK))
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(SUBSCRIBERS_PK),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return [it for it in items if _is_purge_eligible(it, cutoff_iso)]


def _apply_purge(table, offenders: list[dict], mode: str) -> int:
    """Execute `mode` against every offender. Returns the count acted on."""
    now_iso = datetime.now(timezone.utc).isoformat()
    for it in offenders:
        if mode == "purge":
            table.delete_item(Key={"pk": SUBSCRIBERS_PK, "sk": it["sk"]})
        else:  # anonymize
            table.update_item(
                Key={"pk": SUBSCRIBERS_PK, "sk": it["sk"]},
                UpdateExpression="SET email = :r, anonymized_at = :a REMOVE ip_hash",
                ExpressionAttributeValues={":r": "[redacted]", ":a": now_iso},
            )
    return len(offenders)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--window-days",
        type=int,
        required=True,
        help="Retention window in days since unsubscribe. REQUIRED, no default — this is Matthew's signed choice (#1350).",
    )
    ap.add_argument(
        "--mode", choices=["purge", "anonymize"], required=True, help="purge = hard-delete row; anonymize = scrub email, keep hash/status."
    )
    ap.add_argument("--apply", action="store_true", help="Perform the writes. Default is dry run (list offenders only).")
    args = ap.parse_args()

    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=args.window_days)).isoformat()
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    offenders = _scan_unsubscribed(table, cutoff_iso)

    print(f"{len(offenders)} unsubscribed subscriber row(s) older than {args.window_days}d (cutoff {cutoff_iso}).")
    for it in offenders:
        print(f"  sk={it['sk']}  unsubbed_at={it.get('unsubbed_at')}")

    if not args.apply:
        print(f"\nDry run — nothing changed. Re-run with --apply to {args.mode} these rows.")
        return

    n = _apply_purge(table, offenders, args.mode)
    print(f"\n{args.mode}d {n} row(s).")


if __name__ == "__main__":
    main()
