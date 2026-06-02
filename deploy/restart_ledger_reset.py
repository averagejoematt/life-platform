#!/usr/bin/env python3
"""
restart_ledger_reset.py — reset the accountability ledger to $0.

The ledger lives at pk=USER#matthew#SOURCE#ledger: LEDGER#<ts> transaction
records + a TOTALS#current aggregate that /api/ledger reads DIRECTLY (it does
not honour tombstones for the ledger). So an experiment restart must explicitly
delete the transactions AND zero TOTALS#current — tombstoning alone leaves the
site showing stale non-zero totals. On restart the ledger starts fresh at $0.

Dry-run default; pass --apply to commit. Idempotent (safe to re-run).

    python3 deploy/restart_ledger_reset.py            # dry-run
    python3 deploy/restart_ledger_reset.py --apply    # commit
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE = "life-platform"
REGION = "us-west-2"
LEDGER_PK = "USER#matthew#SOURCE#ledger"


def main() -> int:
    apply = "--apply" in sys.argv
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)

    txns: list[dict] = []
    lek = None
    while True:
        kw = dict(KeyConditionExpression=Key("pk").eq(LEDGER_PK) & Key("sk").begins_with("LEDGER#"))
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        txns.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
    totals = table.get_item(Key={"pk": LEDGER_PK, "sk": "TOTALS#current"}).get("Item")

    print(f"ledger reset — {len(txns)} transaction(s); TOTALS#current {'present' if totals else 'absent'}")
    print(f"  mode: {'APPLY' if apply else 'DRY RUN (pass --apply to commit)'}")
    if not apply:
        print("  (dry run — nothing changed)")
        return 0

    with table.batch_writer() as bw:
        for x in txns:
            bw.delete_item(Key={"pk": LEDGER_PK, "sk": x["sk"]})
    table.put_item(Item={
        "pk": LEDGER_PK, "sk": "TOTALS#current",
        "total_donated_usd": 0, "total_bounties_usd": 0, "total_punishments_usd": 0,
        "bounty_count": 0, "punishment_count": 0,
        "reset_at": datetime.now(timezone.utc).isoformat(),
        "reset_reason": "experiment_restart",
    })
    print(f"  ✓ deleted {len(txns)} transaction(s); TOTALS#current zeroed → ledger now $0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
