#!/usr/bin/env python3
"""macrofactor_future_rows_cleanup.py — remove MacroFactor day rows dated AFTER today (#5431).

Background: MacroFactor's Granular Export carries projected values for days that have not
happened, and the summary parser used to write them (2026-10-27 04:14Z: DATE#2026-10-27
through DATE#2026-11-01, `_format: daily_summary`, `entries_count: 0`, an empty `food_log`,
and a positive `total_calories_kcal`). The parser now skips a strictly-future date; this
script removes the rows already written.

What it touches: `USER#<user>#SOURCE#macrofactor` rows whose sk is `DATE#<d>` with `<d>` strictly
after the Pacific date of the run. Today is never touched (it may be logged in progress).
A future row is DELETED only when it is exactly what the bad ingest wrote — `_format ==
daily_summary` AND `entries_count == 0`; the delete is conditional on both, so a row that
changed between the read and the delete survives. Any other future row (a real diary day
a user logged ahead?) is reported and left alone.

Usage:
    python3 scripts/macrofactor_future_rows_cleanup.py                       # dry run (default)
    python3 scripts/macrofactor_future_rows_cleanup.py --apply --backup <file.json>

The dry run prints row keys with `_format` / `entries_count` only — never a value. `--apply`
REQUIRES `--backup`; the backup (every future row, full content, so a delete can be undone) is
written and flushed BEFORE the first delete, and an existing file is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
PK = f"USER#{USER_ID}#SOURCE#macrofactor"

#: What the bad ingest wrote: the only rows this script will delete.
DELETABLE_FORMAT = "daily_summary"
_DAY_SK = re.compile(r"^DATE#\d{4}-\d{2}-\d{2}$")


def _today() -> str:
    from common.pacific_time import pacific_today

    return pacific_today()


def future_rows(table, today: str, keys_only: bool = True) -> list[dict]:
    """Every `DATE#` row of the macrofactor partition strictly after `today`, ascending.

    `keys_only` projects just pk, sk, `_format` and `entries_count` — all a dry run needs."""
    from boto3.dynamodb.conditions import Key

    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(PK) & Key("sk").between(f"DATE#{today}~", "DATE#9999-12-31~"),
        "ConsistentRead": True,
    }
    if keys_only:
        kwargs["ProjectionExpression"] = "pk, sk, #f, entries_count"
        kwargs["ExpressionAttributeNames"] = {"#f": "_format"}
    rows: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(r for r in resp.get("Items", []) if _DAY_SK.match(str(r.get("sk", ""))))
        if not resp.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def is_deletable(row: dict) -> bool:
    """True for exactly what the bad ingest wrote: a daily-summary row with no diary entries."""
    try:
        return row.get("_format") == DELETABLE_FORMAT and int(row.get("entries_count", -1)) == 0
    except (TypeError, ValueError):
        return False


def _jsonable(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def write_backup(rows: list[dict], backup_file: str, today: str) -> None:
    """Write every row in full to `backup_file` (never overwriting) and flush it to disk."""
    payload = {"issue": 5431, "table": TABLE_NAME, "pk": PK, "today_pacific": today, "rows": [_jsonable(r) for r in rows]}
    with open(backup_file, "x", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())


def delete_row(table, row: dict) -> bool:
    """Conditionally delete one row. False when the condition failed (the row changed)."""
    try:
        table.delete_item(
            Key={"pk": row["pk"], "sk": row["sk"]},
            ConditionExpression="#f = :fmt AND entries_count = :zero",
            ExpressionAttributeNames={"#f": "_format"},
            ExpressionAttributeValues={":fmt": DELETABLE_FORMAT, ":zero": 0},
        )
        return True
    except Exception as exc:  # noqa: BLE001 — only a failed condition is expected
        if (getattr(exc, "response", None) or {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _describe(row: dict) -> str:
    return f"  {row.get('sk')}  _format={row.get('_format')!r}  entries_count={row.get('entries_count')!r}"


def run(table, apply: bool, backup: str | None, today: str | None = None, out=print) -> int:
    """Dry run or apply. Returns a process exit code (0 ok, 2 refused)."""
    if apply and not backup:
        out("REFUSED: --apply requires --backup <file.json>; nothing was read or changed.")
        return 2
    today = today or _today()
    rows = future_rows(table, today, keys_only=not apply)
    doomed = [r for r in rows if is_deletable(r)]
    kept = [r for r in rows if not is_deletable(r)]
    out(f"{PK}: {len(rows)} row(s) dated after {today} (Pacific); {len(doomed)} deletable, {len(kept)} left alone")
    for r in doomed:
        out(_describe(r) + ("  -> delete" if apply else "  -> would delete"))
    for r in kept:
        out(_describe(r) + "  -> LEFT ALONE (not a daily_summary row with entries_count 0)")
    if not apply:
        out("Dry run only — re-run with --apply --backup <file.json> to delete.")
        return 0
    if not rows:
        out("Nothing to do.")
        return 0
    write_backup(rows, backup, today)
    out(f"Backup of {len(rows)} row(s) written to {backup}")
    deleted = skipped = 0
    for r in doomed:
        if delete_row(table, r):
            deleted += 1
        else:
            skipped += 1
            out(f"  {r['sk']}: condition failed (row changed since the read) — left in place")
    out(f"Deleted {deleted}, skipped {skipped}. Re-run without --apply to confirm 0 deletable rows remain.")
    return 0


def main(argv: list[str] | None = None, table=None) -> int:
    parser = argparse.ArgumentParser(description="Remove MacroFactor rows dated after today (#5431). Dry run by default.")
    parser.add_argument("--apply", action="store_true", help="Delete (requires --backup). Default: dry run.")
    parser.add_argument("--backup", help="Path of the JSON backup written before any delete (required with --apply).")
    args = parser.parse_args(argv)
    if args.apply and not args.backup:
        print("REFUSED: --apply requires --backup <file.json>; nothing was read or changed.")
        return 2
    if table is None:
        import boto3

        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    return run(table, args.apply, args.backup)


if __name__ == "__main__":
    sys.exit(main())
