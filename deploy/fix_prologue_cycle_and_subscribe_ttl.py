#!/usr/bin/env python3
"""
fix_prologue_cycle_and_subscribe_ttl.py — one-shot data repair for #951 (items 3 + 4).

Idempotent, dry-run by default; the driver runs it post-merge. Two repairs:

1. PROLOGUE CYCLE STAMPS (issue #951 item 4 / ADR-077)
   The cycle-5 resurrect re-dated DATE#2026-02-28 ("Before the Numbers") as a live
   Prologue chapter but left its wipe-era `cycle=4` stamp, while its freshly-written
   Prologue siblings (DATE#2026-02-22, DATE#2026-03-03) carry cycle=5 — so the
   cycle-4 archive would contain a live cycle-5 chapter. Repair: every LIVE
   chronicle record (no tombstone, phase=experiment) whose `cycle` differs from the
   current SSM cycle is re-stamped to the current cycle. That is exactly the
   ADR-077 write-time convention (live experiment_scoped rows carry
   cycle=<current>), so the repair is safe to re-run any time: once stamps agree
   it does nothing. (restart_chronicle_handler.untombstone_and_redate now stamps
   cycle on resurrect, so this class of drift should not recur.)

2. SUBSCRIBE RATE-LIMIT TTL BACKFILL (issue #951 item 3)
   email_subscriber_lambda wrote its expiry epoch to attribute `expires_at`, but
   the table's TTL is configured on attribute `ttl` (verified:
   `aws dynamodb describe-time-to-live --table-name life-platform`), so ~550
   SUBSCRIBE#rate_limit rows were never reaped. The lambda now writes `ttl`; this
   backfills the stranded rows by copying `expires_at` (or deriving bucket-end+1h
   from the sk when absent) into `ttl`. Every stranded bucket is long past, so
   DynamoDB's TTL sweeper deletes them within ~48h of the backfill — cleanup via
   the sanctioned reaper rather than direct DeleteItem.

Usage:
    python3 deploy/fix_prologue_cycle_and_subscribe_ttl.py            # dry-run
    python3 deploy/fix_prologue_cycle_and_subscribe_ttl.py --apply    # commit
"""
from __future__ import annotations

import sys
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE = "life-platform"
REGION = "us-west-2"
CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
SUBSCRIBE_PK = "SUBSCRIBE#rate_limit"
SSM_CYCLE_PARAM = "/life-platform/experiment-cycle"
_RATE_WINDOW_SEC = 300  # email_subscriber_lambda._RATE_LIMIT_WINDOW_SEC
_RATE_GRACE_SEC = 3600  # +1h grace, matching the lambda's ttl math


def query_all(table, pk: str) -> list[dict]:
    items: list[dict] = []
    lek = None
    while True:
        kw = {"KeyConditionExpression": Key("pk").eq(pk)}
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
    return items


def current_cycle(ssm) -> int:
    return int(ssm.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"])


def fix_prologue_cycles(table, cycle: int, apply: bool) -> tuple[int, int]:
    """Re-stamp live (un-tombstoned, phase=experiment) chronicle rows to cycle=<current>."""
    live_mismatched = []
    rows = query_all(table, CHRONICLE_PK)
    for item in rows:
        if item.get("tombstone"):
            continue
        if item.get("phase") != "experiment":
            continue
        row_cycle = item.get("cycle")
        if row_cycle is not None and int(row_cycle) == cycle:
            continue
        live_mismatched.append((item["sk"], row_cycle))

    print(f"[1/2] chronicle cycle stamps — {len(rows)} rows, {len(live_mismatched)} live row(s) not stamped cycle={cycle}:")
    for sk, row_cycle in live_mismatched:
        print(f"    {sk}: cycle={row_cycle} → {cycle}" + ("" if apply else "  (dry-run)"))
        if apply:
            table.update_item(
                Key={"pk": CHRONICLE_PK, "sk": sk},
                UpdateExpression="SET #cyc = :c",
                ExpressionAttributeNames={"#cyc": "cycle"},
                ExpressionAttributeValues={":c": cycle},
            )
    if not live_mismatched:
        print("    nothing to do — all live chronicle rows already carry the current cycle.")
    return len(rows), len(live_mismatched)


def fix_subscribe_ttl(table, apply: bool) -> tuple[int, int]:
    """Copy expires_at → ttl on SUBSCRIBE#rate_limit rows missing the reaped attribute."""
    rows = query_all(table, SUBSCRIBE_PK)
    stranded = [r for r in rows if "ttl" not in r]
    print(f"\n[2/2] SUBSCRIBE#rate_limit TTL backfill — {len(rows)} rows, {len(stranded)} missing `ttl`:")
    fixed = 0
    for item in stranded:
        sk = item["sk"]
        ttl_val = item.get("expires_at")
        if ttl_val is None:
            # Derive bucket-end + 1h from the sk (IP#<hash>#BUCKET#<bucket>).
            try:
                bucket = int(str(sk).rsplit("#", 1)[-1])
                ttl_val = bucket * _RATE_WINDOW_SEC + _RATE_GRACE_SEC
            except ValueError:
                print(f"    SKIP {sk}: no expires_at and unparsable bucket")
                continue
        if apply:
            table.update_item(
                Key={"pk": SUBSCRIBE_PK, "sk": sk},
                UpdateExpression="SET #t = :ttl",
                ExpressionAttributeNames={"#t": "ttl"},
                ExpressionAttributeValues={":ttl": Decimal(str(int(ttl_val)))},
            )
        fixed += 1
    verb = "backfilled" if apply else "would backfill"
    print(f"    {verb} {fixed} row(s) — all past buckets; DDB's TTL sweeper reaps them within ~48h.")
    if not stranded:
        print("    nothing to do — every row already carries `ttl`.")
    return len(rows), fixed


def main() -> int:
    apply = "--apply" in sys.argv
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    cycle = current_cycle(boto3.client("ssm", region_name=REGION))
    print(f"fix_prologue_cycle_and_subscribe_ttl — current cycle={cycle} — mode: {'APPLY' if apply else 'DRY RUN'}")

    _, restamped = fix_prologue_cycles(table, cycle, apply)
    _, backfilled = fix_subscribe_ttl(table, apply)

    print(f"\ndone. chronicle re-stamped: {restamped}; subscribe ttl backfilled: {backfilled}." + ("" if apply else "  (dry-run)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
