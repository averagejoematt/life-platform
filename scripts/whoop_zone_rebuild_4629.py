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

WRITE-BACK (``--apply``, #4629 box 1). Until 2026-10-18 this script had no write mode on purpose:
repaired zones under two keys double-count, and every reader that sums Whoop zone 2 would have added a
fourth stack to the served Zone 2 number. Both preconditions are now met: the duplicate removal (box 3,
183 off-start-day copies removed 2026-10-18, one key per workout id) and the Zone 2 definition (ADR-162,
#4627). ``--dry-run`` and ``--apply`` build ONE plan (``build_plan``) and print the same
``plan_sha256``, so the dry-run the owner read is provably the apply that ran:

  * a stored workout row whose zone fields differ from ``zone_minutes_from_score`` on its archived
    record gets the recomputed fields SET (Decimal) via ``update_item``;
  * a stored zone field the recomputation does not carry (null-score workout, missing zone) is REMOVEd
    — never rewritten as 0 (ADR-104);
  * a row with no archived record is never touched (rows_unresolved); non-zone fields are never touched;
  * ``--report PATH`` writes {rows_updated, rows_zeros_removed, rows_unchanged, rows_unresolved,
    plan_sha256} as JSON. One attempt on the boto clients (``AWS_MAX_ATTEMPTS=1``).

Counts-only mode (neither flag) is unchanged. The plan lines name row keys, so they print only under
``--dry-run`` / ``--apply``.

It prints counts only: no workout ids, no dates, no values (CONVENTIONS: no live record keys in
lane output).

COVERAGE. The combined date tree (``raw_date_key("whoop", d)``) starts at the 2026-05-17 SIMP-2
migration; earlier days live in the per-metric ``sub_layouts`` generations and are reported as
days_missing, not guessed at.

RUN:  AWS_MAX_ATTEMPTS=1 python3 scripts/whoop_zone_rebuild_4629.py --start 2026-05-17 --dry-run --report <path>
      AWS_MAX_ATTEMPTS=1 python3 scripts/whoop_zone_rebuild_4629.py --start 2026-05-17 --apply --report <path>
      python3 scripts/whoop_zone_rebuild_4629.py                       # experiment start .. today
      python3 scripts/whoop_zone_rebuild_4629.py --start 2026-09-06 --end 2026-10-04 --compare-store
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")
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


def build_plan(day_payloads: dict, stored_rows: list) -> dict:
    """The ONE plan --dry-run prints and --apply executes. Per stored workout row: SET the recomputed
    zone fields, REMOVE stored zone fields the recomputation does not carry; rows with no archived record
    are unresolved, equal rows unchanged. Matched on (day, id), else on id when it sits on one archived day."""
    by_key: dict = {}
    days_of: dict = {}
    for day, payload in day_payloads.items():
        for rec in (workout_records(payload) if payload is not None else []):
            wid = str(rec.get("id"))
            by_key[(day, wid)] = zone_minutes_from_score(rec.get("score"))
            days_of.setdefault(wid, set()).add(day)
    rows: list = []
    c: Counter = Counter()
    for row in stored_rows:
        sk = str(row.get("sk", ""))
        if _WORKOUT_MARK not in sk:
            continue
        day, wid = sk[len("DATE#") :][:10], sk.split(_WORKOUT_MARK, 1)[1]
        if (day, wid) in by_key:
            want = by_key[(day, wid)]
        elif len(days_of.get(wid, ())) == 1:
            want = by_key[(next(iter(days_of[wid])), wid)]
        else:
            c["rows_unresolved"] += 1
            continue
        have = {k: row[k] for k in _ZONE_FIELDS if row.get(k) is not None}
        if _as_float_zones(want) == _as_float_zones(have) and set(want) == set(have):
            c["rows_unchanged"] += 1
            continue
        sets = {k: str(v) for k, v in sorted(want.items())}
        removes = sorted(k for k in have if k not in want)
        c["rows_updated" if sets else "rows_zeros_removed"] += 1
        rows.append({"sk": sk, "set": sets, "remove": removes})
    rows.sort(key=lambda r: r["sk"])
    counts = {k: c.get(k, 0) for k in ("rows_updated", "rows_zeros_removed", "rows_unchanged", "rows_unresolved")}
    return {"rows": rows, **counts, "plan_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def print_plan_lines(plan: dict) -> None:
    for r in plan["rows"]:
        print(f"ZONES sk={r['sk']} set={r['set']} remove={r['remove']}")


def apply_plan(table, plan: dict, user_id: str) -> int:
    """Execute the plan with update_item only (never put/delete); returns rows written."""
    pk = f"USER#{user_id}#SOURCE#whoop"
    written = 0
    for r in plan["rows"]:
        values = {f":z{i}": Decimal(v) for i, v in enumerate(r["set"].values())}
        expr = ""
        if r["set"]:
            expr += "SET " + ", ".join(f"{k} = :z{i}" for i, k in enumerate(r["set"]))
        if r["remove"]:
            expr += (" " if expr else "") + "REMOVE " + ", ".join(r["remove"])
        kw = {"Key": {"pk": pk, "sk": r["sk"]}, "UpdateExpression": expr, "ConditionExpression": "attribute_exists(sk)"}
        if values:
            kw["ExpressionAttributeValues"] = values
        table.update_item(**kw)
        written += 1
    return written


def main(argv: list | None = None, table=None, s3=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", default=EXPERIMENT_START_DATE)
    ap.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--compare-store", action="store_true", help="also read the stored rows (DynamoDB query, read-only)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the write-back plan and its plan_sha256; writes nothing")
    mode.add_argument("--apply", action="store_true", help="write the plan (update_item only)")
    ap.add_argument("--report", default=None, metavar="PATH", help="write the plan counts + plan_sha256 here as JSON")
    args = ap.parse_args(argv)
    planning = args.dry_run or args.apply

    if table is None or s3 is None:
        import boto3
        from botocore.config import Config

        cfg = Config(retries={"max_attempts": 1})
        region = os.environ["AWS_DEFAULT_REGION"]
        s3 = s3 or boto3.client("s3", region_name=region, config=cfg)
        if table is None and (planning or args.compare_store):
            table = boto3.resource("dynamodb", region_name=region, config=cfg).Table(os.environ["TABLE_NAME"])
    days = iter_days(args.start, args.end)
    payloads = _read_archive(s3, os.environ["S3_BUCKET"], days)
    stored = _read_store(table, args.start, args.end) if (planning or args.compare_store) else None
    print(
        json.dumps({"range": [args.start, args.end], "write_mode": "apply" if args.apply else "none", **tally(payloads, stored)}, indent=2)
    )
    if not planning:
        return 0
    plan = build_plan(payloads, stored)
    print_plan_lines(plan)
    result = {k: plan[k] for k in ("rows_updated", "rows_zeros_removed", "rows_unchanged", "rows_unresolved", "plan_sha256")}
    result["dry_run"] = not args.apply
    if args.apply:
        result["rows_written"] = apply_plan(table, plan, os.environ["USER_ID"])
    print(json.dumps(result, indent=2))
    if args.report:
        with open(args.report, "w") as fh:
            json.dump(result, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
