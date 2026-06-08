#!/usr/bin/env python3
"""
restart_ledger_reset.py — reset the accountability ledger to $0 for a new run,
WITHOUT destroying history (ADR-077 decision F).

The ledger lives at pk=USER#matthew#SOURCE#ledger: LEDGER#<ts> transaction
records + a TOTALS#current aggregate that /api/ledger reads DIRECTLY (it does
not honour tombstones for the ledger). An experiment restart must zero
TOTALS#current so the new run starts at $0 — but "nothing is ever deleted":

  1. Roll the closing run's TOTALS#current into a durable LIFETIME#aggregate
     (cross_phase — never wiped), with a per-cycle breakdown. Lifetime-donated
     dollars is the strongest accountability anchor and must survive every reset.
  2. TOMBSTONE the LEDGER# transactions (+ phase=pilot + cycle=N) instead of
     hard-deleting them — they stay queryable as cycle history, hidden from the
     current run's views.
  3. Zero TOTALS#current for the fresh run.

Dry-run default; pass --apply to commit. Idempotent (safe to re-run).

    python3 deploy/restart_ledger_reset.py            # dry-run
    python3 deploy/restart_ledger_reset.py --apply    # commit
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE = "life-platform"
REGION = "us-west-2"
LEDGER_PK = "USER#matthew#SOURCE#ledger"
SSM_CYCLE_PARAM = "/life-platform/experiment-cycle"
DEFAULT_CYCLE = 2

_MONEY_FIELDS = ("total_donated_usd", "total_bounties_usd", "total_punishments_usd")
_COUNT_FIELDS = ("bounty_count", "punishment_count")


def current_cycle() -> int:
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"])
    except Exception:
        return DEFAULT_CYCLE


def _num(v) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal(0)


def main() -> int:
    apply = "--apply" in sys.argv
    cycle = current_cycle()
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    now_iso = datetime.now(timezone.utc).isoformat()

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
    totals = table.get_item(Key={"pk": LEDGER_PK, "sk": "TOTALS#current"}).get("Item") or {}
    lifetime = table.get_item(Key={"pk": LEDGER_PK, "sk": "LIFETIME#aggregate"}).get("Item") or {}

    # Compute the rolled-forward lifetime aggregate (closing run's totals added in).
    new_lifetime = {f: _num(lifetime.get(f)) + _num(totals.get(f)) for f in _MONEY_FIELDS}
    new_counts = {f: int(_num(lifetime.get(f)) + _num(totals.get(f))) for f in _COUNT_FIELDS}

    print(
        f"ledger reset — cycle={cycle} — {len(txns)} transaction(s); "
        f"TOTALS#current {'present' if totals else 'absent'}; "
        f"LIFETIME#aggregate {'present' if lifetime else 'absent'}"
    )
    print("  closing-run totals: " + ", ".join(f"{f}={totals.get(f, 0)}" for f in _MONEY_FIELDS))
    print("  lifetime after roll-forward: " + ", ".join(f"{f}={new_lifetime[f]}" for f in _MONEY_FIELDS))
    print(f"  mode: {'APPLY' if apply else 'DRY RUN (pass --apply to commit)'}")
    if not apply:
        print("  (dry run — nothing changed; would tombstone txns, roll LIFETIME, zero TOTALS)")
        return 0

    # 1. Roll the closing totals into the durable LIFETIME aggregate (+ per-cycle row).
    item = {"pk": LEDGER_PK, "sk": "LIFETIME#aggregate", "updated_at": now_iso}
    item.update({f: new_lifetime[f] for f in _MONEY_FIELDS})
    item.update({f: new_counts[f] for f in _COUNT_FIELDS})
    table.put_item(Item=item)
    table.put_item(
        Item={
            "pk": LEDGER_PK,
            "sk": f"CYCLE_TOTALS#{cycle:03d}",
            "cycle": cycle,
            "closed_at": now_iso,
            **{f: _num(totals.get(f)) for f in _MONEY_FIELDS},
            **{f: int(_num(totals.get(f))) for f in _COUNT_FIELDS},
        }
    )

    # 2. Tombstone the transactions (keep history, hide from current run).
    for x in txns:
        table.update_item(
            Key={"pk": LEDGER_PK, "sk": x["sk"]},
            UpdateExpression="SET tombstone = :t, tombstoned_at = :ts, #p = :ph, #cyc = :c",
            ExpressionAttributeNames={"#p": "phase", "#cyc": "cycle"},
            ExpressionAttributeValues={":t": True, ":ts": now_iso, ":ph": "pilot", ":c": cycle},
        )

    # 3. Zero TOTALS#current for the fresh run.
    table.put_item(
        Item={
            "pk": LEDGER_PK,
            "sk": "TOTALS#current",
            "total_donated_usd": 0,
            "total_bounties_usd": 0,
            "total_punishments_usd": 0,
            "bounty_count": 0,
            "punishment_count": 0,
            "reset_at": now_iso,
            "reset_reason": "experiment_restart",
            "reset_cycle": cycle,
        }
    )
    print(
        f"  ✓ rolled LIFETIME (donated=${new_lifetime['total_donated_usd']}); "
        f"tombstoned {len(txns)} txn(s) as cycle {cycle}; TOTALS#current zeroed → run starts at $0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
