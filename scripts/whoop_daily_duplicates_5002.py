#!/usr/bin/env python3
"""scripts/whoop_daily_duplicates_5002.py — count and list, READ-ONLY, the stored Whoop day rows that
carry the PREVIOUS day's cycle copied field-for-field (#5002). It has no write mode.

WHY. Until #5002 the writer filed ``records[0]`` of each UTC-day cycle fetch under that day, and the
vendor returns every cycle that OVERLAPS the window — so before a new cycle existed, a day's fetch got
the prior day's still-open cycle and wrote its strain / kilojoule / heart rates / step count under the
new day too (DATE#2026-10-18 = DATE#2026-10-17 on all five, 2026-10-18T16:00Z). The writer now files
only the cycle that STARTED on the day and refuses a cycle id already on a neighbouring row
(``ingestion/whoop_cycle_day.py``). Rows already stored are untouched; removing their copied fields
is the owner's later apply. This script measures them and stops there.

THE SHAPE (the issue's own definition). A day row D is a DUPLICATE when the stored row for the
calendar day before it, D-1, exists and both rows carry ``strain`` and ``kilojoule``, and D equals
D-1 on all of ``kilojoule``, ``strain``, ``average_heart_rate``, ``max_heart_rate`` and
``step_count`` (absent on both counts as equal — ``step_count`` is a vendor field only from
2026-09-21), AND D carries no ``recovery_score``. Also reported, not counted: the same five-field
match where D DOES carry a recovery score (``same_cycle_fields_with_recovery``) — a row a later
refresh gave its own recovery but whose cycle fields still match the day before.

RUN:  AWS_MAX_ATTEMPTS=1 python3 scripts/whoop_daily_duplicates_5002.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

FIELDS = ("kilojoule", "strain", "average_heart_rate", "max_heart_rate", "step_count")
_PROJECTION = "sk, recovery_score, cycle_id, ingested_at, " + ", ".join(FIELDS)


def _norm(v):
    """A comparable, exponent-free string: Decimal('70') and Decimal('70.0') compare equal, print '70'."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    return str(v)


def _prev_day(d: str) -> str:
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def day_rows(rows: list) -> dict:
    """date -> row, for the DATE#YYYY-MM-DD day rows only (workout sub-rows are skipped)."""
    out = {}
    for r in rows:
        sk = str(r.get("sk", ""))
        if sk.startswith("DATE#") and len(sk) == len("DATE#YYYY-MM-DD"):
            out[sk[len("DATE#") :]] = r
    return out


def census(rows: list) -> dict:
    by_day = day_rows(rows)
    members, with_recovery = [], []
    for d in sorted(by_day):
        cur, prev = by_day[d], by_day.get(_prev_day(d))
        if prev is None or any(cur.get(f) is None or prev.get(f) is None for f in ("strain", "kilojoule")):
            continue
        if any(_norm(cur.get(f)) != _norm(prev.get(f)) for f in FIELDS):
            continue
        entry = {"date": d, "copies": _prev_day(d), **{f: _norm(cur.get(f)) for f in FIELDS}, "ingested_at": cur.get("ingested_at")}
        (with_recovery if cur.get("recovery_score") is not None else members).append(entry)
    return {
        "write_mode": "none",
        "day_rows_read": len(by_day),
        "first_day": min(by_day) if by_day else None,
        "last_day": max(by_day) if by_day else None,
        "duplicates": len(members),
        "members": members,
        "same_cycle_fields_with_recovery": len(with_recovery),
        "same_cycle_fields_with_recovery_members": with_recovery,
    }


def _read_store(table) -> list:
    from boto3.dynamodb.conditions import Key

    kwargs = {
        "KeyConditionExpression": Key("pk").eq(f"USER#{os.environ['USER_ID']}#SOURCE#whoop") & Key("sk").begins_with("DATE#"),
        "ProjectionExpression": _PROJECTION,
    }
    rows: list = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="required: this script only reports")
    args = ap.parse_args(argv)
    if not args.dry_run:
        print("refusing: this script has no write mode — pass --dry-run (removing the copied fields is the owner's apply)")
        return 2

    import boto3

    table = boto3.resource("dynamodb", region_name=os.environ["AWS_DEFAULT_REGION"]).Table(os.environ["TABLE_NAME"])
    print(json.dumps(census(_read_store(table)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
