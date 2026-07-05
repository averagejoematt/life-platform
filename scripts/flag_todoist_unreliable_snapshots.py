#!/usr/bin/env python3
"""
flag_todoist_unreliable_snapshots.py — annotate the poisoned Todoist range (#478 / ADR-122).

Why: from the v1-API migration (~2026-05-10) until the #478 fix deploys, every
Todoist DATE# snapshot carried garbage load numbers — `overdue_count` and
`due_today_count` were ≈ the WHOLE active list (the `filter` param was silently
ignored by `GET /tasks`), and `active_count` was page-capped at 200. These are
point-in-time counts: the true overdue/active set on a past date is unrecoverable.
Per ADR-122 we annotate, we do NOT fake — each poisoned record gets
`snapshot_unreliable=true` plus a reason so no forecast, threshold-derivation, or
narrative treats those load figures as real. The `completed_*` fields on the same
records are sourced from a different (date-correct) endpoint and remain trustworthy;
the flag scopes only the load-snapshot fields, documented in the reason.

What it does: for every USER#matthew#SOURCE#todoist DATE# item whose date falls in
[--since, --until], set snapshot_unreliable / snapshot_unreliable_reason /
snapshot_unreliable_fields, unless already flagged.

Read-only by default. Apply with --apply. Run this AFTER the #478 fix has deployed
and produced its first clean ingestion, with --until set to the LAST poisoned date
(the day before the corrected ingestion first ran).

  python3 scripts/flag_todoist_unreliable_snapshots.py --until 2026-07-05         # dry-run
  python3 scripts/flag_todoist_unreliable_snapshots.py --until 2026-07-05 --apply # write flags
"""

import argparse
import sys
from datetime import date

import boto3
from boto3.dynamodb.conditions import Key

TABLE = "life-platform"
REGION = "us-west-2"
PK = "USER#matthew#SOURCE#todoist"

# The v1-API migration that introduced the ignored-filter / page-cap bug (#478).
DEFAULT_SINCE = "2026-05-10"

REASON = (
    "Todoist v1 filter/pagination bug (#478 / ADR-122): overdue_count and "
    "due_today_count ≈ the full active list (the /tasks filter param was ignored), "
    "and active_count was page-capped at 200. Load snapshot is unrecoverable "
    "point-in-time data — annotated, not corrected."
)
UNRELIABLE_FIELDS = ["active_count", "overdue_count", "due_today_count"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=DEFAULT_SINCE, help=f"first poisoned date, inclusive (default {DEFAULT_SINCE})")
    ap.add_argument(
        "--until",
        default=date.today().isoformat(),
        help="last poisoned date, inclusive — set to the day BEFORE the fix's first clean ingestion",
    )
    ap.add_argument("--apply", action="store_true", help="write flags (default: dry-run)")
    args = ap.parse_args()

    if args.since > args.until:
        print(f"ERROR: --since {args.since} is after --until {args.until}", file=sys.stderr)
        return 2

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    items, kwargs = [], {
        "KeyConditionExpression": Key("pk").eq(PK) & Key("sk").between(f"DATE#{args.since}", f"DATE#{args.until}"),
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    scanned = flagged = already = 0
    for it in items:
        sk = it.get("sk", "")
        if not sk.startswith("DATE#"):
            continue
        scanned += 1
        if it.get("snapshot_unreliable"):
            already += 1
            continue
        flagged += 1
        print(f"  flag {sk[5:]}  (active={it.get('active_count')} overdue={it.get('overdue_count')} due_today={it.get('due_today_count')})")
        if args.apply:
            table.update_item(
                Key={"pk": PK, "sk": sk},
                UpdateExpression="SET snapshot_unreliable = :t, snapshot_unreliable_reason = :r, snapshot_unreliable_fields = :f",
                ExpressionAttributeValues={":t": True, ":r": REASON, ":f": UNRELIABLE_FIELDS},
            )

    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    print(f"\n{mode}: {scanned} todoist records in [{args.since}..{args.until}], {flagged} newly flagged, {already} already flagged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
