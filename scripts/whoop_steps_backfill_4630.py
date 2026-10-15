#!/usr/bin/env python3
"""scripts/whoop_steps_backfill_4630.py — count (and, owner-run only, back-fill) the Whoop day rows
that would gain the vendor's daily ``step_count`` from the raw S3 archive (#4630 box 1).

WHY. Whoop's daily cycle record has carried ``step_count`` since 2026-09-21 and the writer dropped
it until #4630; the archive at ``raw_layout`` (``source_registry.raw_date_key``) still holds what the
vendor sent. The writer now stores it on the Whoop day row under its own name; this script finds the
already-stored days that lack it.

WHAT IT DOES (default, read-only). For each day in [--start, --end] it reads that day's archived
payload, runs the archived cycle through ``whoop_lambda._extract_cycle`` — the SAME function the
writer uses, so the back-fill cannot read the count differently from ingestion — and reads the
stored Whoop day rows over the same range (a DynamoDB QUERY). It prints COUNTS ONLY:

  days_requested / days_archived / days_missing / archived_days_with_step_count
  stored_day_rows / stored_rows_with_step_count
  rows_that_would_gain_step_count     archive carries a count, the stored day row has none
  archived_count_without_day_row      archive carries a count, no stored day row (never created here)
  stored_rows_differing               the row already has a count that differs from the archive's
                                      (reported, never overwritten — a later refresh is newer)

No record keys, no dates, no values (CONVENTIONS: no live record keys in lane output).

WRITE MODE — THE OWNER'S LINE ONLY. ``--apply`` sets ``step_count`` on exactly the
``rows_that_would_gain_step_count`` set, one ``UpdateItem`` per row, conditioned on the row existing
AND not yet carrying the field (``attribute_exists(sk) AND attribute_not_exists(step_count)``), so it
never creates a row, never overwrites a count, and a re-run is a no-op. It writes nothing else: no
merge with Apple's steps, no max, no comparison (owner rule 2026-10-04). A lane never runs it.

COVERAGE. The combined date tree starts at the 2026-05-17 SIMP-2 migration (the default --start);
earlier days are in the per-metric ``sub_layouts`` generations, which predate the vendor's step
field anyway, and are reported as days_missing rather than guessed at.

RUN:  python3 scripts/whoop_steps_backfill_4630.py                      # dry run, 2026-05-17 .. today
      python3 scripts/whoop_steps_backfill_4630.py --apply              # OWNER ONLY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion.source_registry import raw_date_key  # noqa: E402
from ingestion.whoop_lambda import _extract_cycle  # noqa: E402

COMBINED_TREE_START = "2026-05-17"  # the SIMP-2 migration date — see source_registry's whoop raw_layout
FIELD = "step_count"


def iter_days(start: str, end: str) -> list[str]:
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def archived_step_count(payload: dict | None):
    """The writer's own reading of one archived day — the framework's envelope is {fetched_at, raw}."""
    raw = (payload or {}).get("raw") or {}
    return _extract_cycle(raw.get("cycle") or {}).get(FIELD)


def plan(day_payloads: dict, stored_rows: list) -> tuple[dict, dict]:
    """(counts, gains). ``gains`` maps a stored day row's sk to the count it would gain."""
    c: Counter = Counter()
    by_day = {str(r.get("sk", ""))[len("DATE#") :]: r for r in stored_rows if "#WORKOUT#" not in str(r.get("sk", ""))}
    c["stored_day_rows"] = len(by_day)
    c["stored_rows_with_step_count"] = sum(1 for r in by_day.values() if r.get(FIELD) is not None)
    gains: dict = {}
    for day, payload in day_payloads.items():
        c["days_requested"] += 1
        if payload is None:
            c["days_missing"] += 1
            continue
        c["days_archived"] += 1
        steps = archived_step_count(payload)
        if steps is None:
            continue
        c["archived_days_with_step_count"] += 1
        row = by_day.get(day)
        if row is None:
            c["archived_count_without_day_row"] += 1
        elif row.get(FIELD) is None:
            gains[row["sk"]] = steps
        elif row[FIELD] != steps:
            c["stored_rows_differing"] += 1
    c["rows_that_would_gain_step_count"] = len(gains)
    for k in ("archived_days_with_step_count", "archived_count_without_day_row", "stored_rows_differing"):
        c.setdefault(k, 0)
    return dict(sorted(c.items())), gains


def apply_gains(table, pk: str, gains: dict) -> int:
    """OWNER ONLY. Adds the field to existing rows that lack it; never creates or overwrites."""
    from botocore.exceptions import ClientError

    written = 0
    for sk, steps in gains.items():
        try:
            table.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression="SET #f = :v",
                ConditionExpression="attribute_exists(sk) AND attribute_not_exists(#f)",
                ExpressionAttributeNames={"#f": FIELD},
                ExpressionAttributeValues={":v": steps},
            )
            written += 1
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
    return written


def _read_archive(s3, bucket: str, days: list) -> dict:
    out: dict = {}
    for day in days:
        try:
            body = s3.get_object(Bucket=bucket, Key=raw_date_key("whoop", day))["Body"].read()
        except s3.exceptions.NoSuchKey:
            out[day] = None
            continue
        out[day] = json.loads(body)
    return out


def _read_store(table, pk: str, start: str, end: str) -> list:
    from boto3.dynamodb.conditions import Key

    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start}", f"DATE#{end}~"),
        "ProjectionExpression": "sk, #f",
        "ExpressionAttributeNames": {"#f": FIELD},
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
    ap.add_argument("--start", default=COMBINED_TREE_START)
    ap.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--apply", action="store_true", help="OWNER ONLY: add step_count to the rows that lack it")
    args = ap.parse_args(argv)

    import boto3

    region = os.environ["AWS_DEFAULT_REGION"]
    pk = f"USER#{os.environ['USER_ID']}#SOURCE#whoop"
    table = boto3.resource("dynamodb", region_name=region).Table(os.environ["TABLE_NAME"])
    payloads = _read_archive(boto3.client("s3", region_name=region), os.environ["S3_BUCKET"], iter_days(args.start, args.end))
    counts, gains = plan(payloads, _read_store(table, pk, args.start, args.end))
    report = {"range": [args.start, args.end], "mode": "apply" if args.apply else "dry-run", **counts}
    if args.apply:
        report["rows_written"] = apply_gains(table, pk, gains)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
