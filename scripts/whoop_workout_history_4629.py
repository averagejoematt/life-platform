#!/usr/bin/env python3
"""scripts/whoop_workout_history_4629.py — report, READ-ONLY, what the two owner writes #4629
waits on would touch in the stored Whoop workout history: the duplicate date keys (box 3) and the
sport-name relabel (box 2). It prints COUNTS ONLY and has no write mode.

WHY. Until #4629 every workout the vendor returned for a UTC-day fetch was filed under that day,
and the vendor returns any workout that OVERLAPS the window — so a workout running across 00:00
UTC was written under two date keys (181 of 2,520 ids at filing). The writer now files each id
once, under the UTC day it STARTED (#4644 Q11, consistent with #3913; ``whoop_lambda.
workout_files_under``). And until #4629 ``sport_name`` came from a hand-written id table that
disagreed with the vendor on 21 of its 24 ids; the writer now stores the payload's own label.
Neither change touches the rows already stored. Removing the extra copies and relabelling history
are the owner's writes, run after his rulings — so this script measures them and stops there.

WHAT IT REPORTS.

  keys        workout_rows / distinct_workout_ids / ids_under_two_or_more_keys
              rows_off_start_day          a copy under a key that is NOT the UTC start day — the
                                          rows the approved removal would delete
              ids_with_no_row_on_start_day  an id none of whose keys is its start day (deleting
                                          off-start-day copies would lose it — a re-key, not a
                                          delete; ``..._and_two_keys`` is the subset also duplicated)
              rows_without_start_time     nothing to key on; left alone
  relabel     rows_vendor_labelled        ``sport_name`` already equals the vendor's label
              rows_relabel_from_row       the row's own ``vendor_sport_name`` names it (#4922)
              rows_relabel_from_archive   the raw archive holds this workout id's own record
              rows_relabel_by_sport_id    only the id is known, and the archive maps that sport id
                                          to exactly one vendor label (an inference from the wire,
                                          never a hand-written table — reported apart for that reason)
              rows_unresolved             none of the above — left as stored
              label_changes               old label -> vendor label, with row counts (labels are not
                                          record keys; no ids, dates or values are printed)

THE RELABEL SHAPE (#4644 Q10 recommended answer: "yes, vendor names, old label kept as an
alias"): ``sport_name`` := the vendor label, and the old table label is kept beside it as
``legacy_sport_name``. That write is NOT here. Neither is the duplicate removal.

THE FRAME is the writer's own: ``whoop_lambda._utc_day`` (the reconciler's expected key), imported,
so this report can never key a workout differently from ingestion.

RUN:  AWS_MAX_ATTEMPTS=1 python3 scripts/whoop_workout_history_4629.py --dry-run
      AWS_MAX_ATTEMPTS=1 python3 scripts/whoop_workout_history_4629.py --dry-run --no-archive
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
from ingestion.whoop_lambda import _utc_day  # noqa: E402

_WORKOUT_MARK = "#WORKOUT#"
# The combined per-day archive tree starts at the 2026-05-17 SIMP-2 migration (see
# scripts/whoop_zone_rebuild_4629.py); earlier rows resolve from the row or the sport id, or not at all.
ARCHIVE_START = "2026-05-17"


def _key_day(sk: str) -> str:
    return sk[len("DATE#") :][:10]


def _wid(row: dict) -> str:
    sk = str(row.get("sk", ""))
    return str(row.get("workout_id") or sk.split(_WORKOUT_MARK, 1)[-1])


def workout_rows(rows: list) -> list:
    return [r for r in rows if _WORKOUT_MARK in str(r.get("sk", ""))]


def tally_keys(rows: list) -> dict:
    """Counts for box 3 over stored whoop items (day rows are ignored)."""
    c: Counter = Counter()
    by_id: dict = {}
    for r in workout_rows(rows):
        c["workout_rows"] += 1
        by_id.setdefault(_wid(r), []).append(r)
    c["distinct_workout_ids"] = len(by_id)
    for copies in by_id.values():
        days = {_key_day(str(r["sk"])) for r in copies}
        if len(days) > 1:
            c["ids_under_two_or_more_keys"] += 1
        start_days = {_utc_day(r.get("start_time")) for r in copies} - {None}
        if not start_days:
            c["rows_without_start_time"] += len(copies)
            continue
        start_day = sorted(start_days)[0]
        off = [r for r in copies if _key_day(str(r["sk"])) != start_day]
        if len(off) == len(copies):
            c["ids_with_no_row_on_start_day"] += 1
            if len(days) > 1:
                c["ids_with_no_row_on_start_day_and_two_keys"] += 1
        elif len(days) > 1:
            c["rows_off_start_day"] += len(off)
    for k in (
        "ids_under_two_or_more_keys",
        "rows_off_start_day",
        "ids_with_no_row_on_start_day",
        "ids_with_no_row_on_start_day_and_two_keys",
        "rows_without_start_time",
    ):
        c.setdefault(k, 0)
    return dict(sorted(c.items()))


def archive_labels(day_payloads: dict) -> tuple[dict, dict]:
    """(workout id -> vendor label, sport id -> set of vendor labels) from archived day payloads."""
    by_wid: dict = {}
    by_sport: dict = {}
    for payload in day_payloads.values():
        for rec in (((payload or {}).get("raw") or {}).get("workouts") or {}).get("records") or []:
            label = rec.get("sport_name")
            if not label:
                continue
            by_wid[str(rec.get("id"))] = str(label)
            if rec.get("sport_id") is not None:
                by_sport.setdefault(int(rec["sport_id"]), set()).add(str(label))
    return by_wid, by_sport


def plan_relabel(rows: list, by_wid: dict, by_sport: dict) -> dict:
    """Counts for box 2: which stored rows a relabel would change, and from which evidence."""
    c: Counter = Counter()
    changes: Counter = Counter()
    for r in workout_rows(rows):
        stored = r.get("sport_name")
        vendor, path = None, None
        if r.get("vendor_sport_name"):
            vendor, path = str(r["vendor_sport_name"]), "rows_relabel_from_row"
        elif _wid(r) in by_wid:
            vendor, path = by_wid[_wid(r)], "rows_relabel_from_archive"
        elif r.get("sport_id") is not None and len(by_sport.get(int(r["sport_id"]), ())) == 1:
            vendor, path = next(iter(by_sport[int(r["sport_id"])])), "rows_relabel_by_sport_id"
        if vendor is None:
            c["rows_unresolved"] += 1
            continue
        if stored == vendor:
            c["rows_vendor_labelled"] += 1
            continue
        c[path] += 1
        changes[f"{stored} -> {vendor}"] += 1
    for k in ("rows_vendor_labelled", "rows_relabel_from_row", "rows_relabel_from_archive", "rows_relabel_by_sport_id", "rows_unresolved"):
        c.setdefault(k, 0)
    out = dict(sorted(c.items()))
    out["sport_ids_with_conflicting_vendor_labels"] = sum(1 for labels in by_sport.values() if len(labels) > 1)
    out["label_changes"] = dict(changes.most_common())
    return out


def _read_store(table) -> list:
    from boto3.dynamodb.conditions import Key

    kwargs = {
        "KeyConditionExpression": Key("pk").eq(f"USER#{os.environ['USER_ID']}#SOURCE#whoop") & Key("sk").begins_with("DATE#"),
        "ProjectionExpression": "sk, workout_id, start_time, sport_id, sport_name, vendor_sport_name",
    }
    rows: list = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _read_archive(s3, bucket: str, start: str, end: str) -> dict:
    out: dict = {}
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    while d <= last:
        try:
            out[d.isoformat()] = json.loads(s3.get_object(Bucket=bucket, Key=raw_date_key("whoop", d.isoformat()))["Body"].read())
        except s3.exceptions.NoSuchKey:
            out[d.isoformat()] = None
        d += timedelta(days=1)
    return out


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="required: this script only reports")
    ap.add_argument("--no-archive", action="store_true", help="skip the S3 archive read (relabel evidence from the rows only)")
    args = ap.parse_args(argv)
    if not args.dry_run:
        print("refusing: this script has no write mode — pass --dry-run (the removal and the relabel are the owner's writes)")
        return 2

    import boto3

    region = os.environ["AWS_DEFAULT_REGION"]
    rows = _read_store(boto3.resource("dynamodb", region_name=region).Table(os.environ["TABLE_NAME"]))
    payloads: dict = {}
    if not args.no_archive:
        today = datetime.now(timezone.utc).date().isoformat()
        payloads = _read_archive(boto3.client("s3", region_name=region), os.environ["S3_BUCKET"], ARCHIVE_START, today)
    by_wid, by_sport = archive_labels(payloads)
    report = {
        "write_mode": "none",
        "archive_days_read": sum(1 for p in payloads.values() if p is not None),
        "keys": tally_keys(rows),
        "relabel": plan_relabel(rows, by_wid, by_sport),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
