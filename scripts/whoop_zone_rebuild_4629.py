#!/usr/bin/env python3
"""scripts/whoop_zone_rebuild_4629.py — recompute Whoop per-workout zone minutes from the raw
S3 archive and print COUNTS ONLY (#4629, the read-side rebuild path).

WHY. Until #4629 the Whoop workout transform read ``score.zone_duration`` (singular); the vendor's
key is ``zone_durations``, so every stored workout row carries six zeros, and a null-score workout
got six zeros it never had. The archive at ``raw_layout`` (``source_registry.raw_date_key``) still
holds what the vendor sent, so the true zone minutes are recomputable per workout.

WHAT IT DOES. For each day in [--start, --end] it reads that day's archived payload, runs every
workout record through ``whoop_lambda.zone_minutes_from_score`` — the SAME function the writer now
uses, so the rebuild cannot compute zones differently from ingestion — and tallies:

  days_requested / days_archived / days_missing
  workout_records / records_null_score / records_with_zone_durations / records_nonzero_zones
  distinct_workout_ids / ids_under_two_or_more_days   (the #4629 box-3 duplicate class)

With ``--compare-store`` it also reads the stored Whoop workout rows over the same range (a
DynamoDB QUERY, read-only) and adds stored_workout_rows / stored_rows_nonzero_zones /
stored_rows_differing (a stored row whose zone fields differ from the recomputation, including
fabricated zeros on a null-score workout).

THERE IS NO WRITE MODE. No --apply, no put/update/delete, on purpose: zone history is not
rewritten from a lane. Writing the recomputed values back waits on two things the issue names —
the duplicate removal (#4629 box 3, 181 ids under two keys, an approved one-off owner write) and
the Zone 2 definition (#4627) — because repaired zones under two keys double-count, and every
reader that sums Whoop zone 2 would add a fourth stack to the served Zone 2 number. The write-back,
when it comes, is the owner's to run.

It prints counts only: no workout ids, no dates, no values (CONVENTIONS: no live record keys in
lane output).

COVERAGE. The combined date tree (``raw_date_key("whoop", d)``) starts at the 2026-05-17 SIMP-2
migration; earlier days live in the per-metric ``sub_layouts`` generations and are reported as
days_missing, not guessed at.

RUN:  python3 scripts/whoop_zone_rebuild_4629.py                       # experiment start .. today
      python3 scripts/whoop_zone_rebuild_4629.py --start 2026-09-06 --end 2026-10-04 --compare-store
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

from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from ingestion.source_registry import raw_date_key  # noqa: E402
from ingestion.whoop_lambda import zone_minutes_from_score  # noqa: E402

_ZONE_FIELDS = tuple(f"zone_{i}_minutes" for i in range(6))
_WORKOUT_MARK = "#WORKOUT#"


def iter_days(start: str, end: str) -> list[str]:
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def workout_records(payload: dict | None) -> list:
    """The workout records of one archived day — the framework's envelope is {fetched_at, raw}."""
    raw = (payload or {}).get("raw") or {}
    return list((raw.get("workouts") or {}).get("records") or [])


def _as_float_zones(fields: dict) -> dict:
    return {k: round(float(fields[k]), 2) for k in _ZONE_FIELDS if fields.get(k) is not None}


def tally(day_payloads: dict, stored_rows: list | None = None) -> dict:
    """Counts only. ``day_payloads`` maps an ISO day to its archived payload (None = not archived);
    ``stored_rows`` (optional) are stored whoop items carrying ``sk`` and any zone fields."""
    c: Counter = Counter()
    days_by_id: dict = {}
    recomputed: dict = {}
    for day, payload in day_payloads.items():
        c["days_requested"] += 1
        if payload is None:
            c["days_missing"] += 1
            continue
        c["days_archived"] += 1
        for rec in workout_records(payload):
            c["workout_records"] += 1
            wid = str(rec.get("id"))
            days_by_id.setdefault(wid, set()).add(day)
            score = rec.get("score")
            if score is None:
                c["records_null_score"] += 1
            elif isinstance(score.get("zone_durations"), dict):
                c["records_with_zone_durations"] += 1
            zones = _as_float_zones(zone_minutes_from_score(score))
            if any(v > 0 for v in zones.values()):
                c["records_nonzero_zones"] += 1
            recomputed[(day, wid)] = zones
    c["distinct_workout_ids"] = len(days_by_id)
    c["ids_under_two_or_more_days"] = sum(1 for days in days_by_id.values() if len(days) > 1)
    if stored_rows is not None:
        _tally_store(c, recomputed, stored_rows)
    return dict(sorted(c.items()))


def _tally_store(c: Counter, recomputed: dict, stored_rows: list) -> None:
    c["stored_workout_rows"] = 0
    c["stored_rows_nonzero_zones"] = 0
    c["stored_rows_differing"] = 0
    for row in stored_rows:
        sk = str(row.get("sk", ""))
        if _WORKOUT_MARK not in sk:
            continue
        c["stored_workout_rows"] += 1
        stored = _as_float_zones(row)
        if any(v > 0 for v in stored.values()):
            c["stored_rows_nonzero_zones"] += 1
        day, wid = sk[len("DATE#") :][:10], sk.split(_WORKOUT_MARK, 1)[1]
        if (day, wid) in recomputed and recomputed[(day, wid)] != stored:
            c["stored_rows_differing"] += 1


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


def _read_store(table, start: str, end: str) -> list:
    from boto3.dynamodb.conditions import Key

    kwargs = {
        "KeyConditionExpression": Key("pk").eq(f"USER#{os.environ['USER_ID']}#SOURCE#whoop")
        & Key("sk").between(f"DATE#{start}", f"DATE#{end}~"),
        "ProjectionExpression": "sk, " + ", ".join(_ZONE_FIELDS),
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
    ap.add_argument("--start", default=EXPERIMENT_START_DATE)
    ap.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--compare-store", action="store_true", help="also read the stored rows (DynamoDB query, read-only)")
    args = ap.parse_args(argv)

    import boto3

    region = os.environ["AWS_DEFAULT_REGION"]
    days = iter_days(args.start, args.end)
    payloads = _read_archive(boto3.client("s3", region_name=region), os.environ["S3_BUCKET"], days)
    stored = None
    if args.compare_store:
        stored = _read_store(boto3.resource("dynamodb", region_name=region).Table(os.environ["TABLE_NAME"]), args.start, args.end)
    print(json.dumps({"range": [args.start, args.end], "write_mode": "none", **tally(payloads, stored)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
