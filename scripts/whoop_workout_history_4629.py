#!/usr/bin/env python3
"""scripts/whoop_workout_history_4629.py — report, READ-ONLY, what the two owner writes #4629
waits on would touch in the stored Whoop workout history: the duplicate date keys (box 3) and the
sport-name relabel (box 2). ``--dry-run`` prints COUNTS ONLY; ``--apply`` executes the same plan.

WHY. Until #4629 every workout the vendor returned for a UTC-day fetch was filed under that day,
and the vendor returns any workout that OVERLAPS the window — so a workout running across 00:00
UTC was written under two date keys (181 of 2,520 ids at filing). The writer now files each id
once, under the UTC day it STARTED (#4644 Q11, consistent with #3913; ``whoop_lambda.
workout_files_under``). And until #4629 ``sport_name`` came from a hand-written id table that
disagreed with the vendor on 21 of its 24 ids; the writer now stores the payload's own label.
Neither change touches the rows already stored. Removing the extra copies and relabelling history
are the owner's writes, run after his rulings (#4644 Q10/Q11, 2026-10-17/18): ``--dry-run`` measures
them, ``--apply`` performs them.

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
``legacy_sport_name`` (``--apply``).

WRITE MODE (``--apply``, mutually exclusive with ``--dry-run``; both build ONE plan, ``build_plan``,
and print its ``plan_sha256`` so the dry-run the owner read is provably the apply that ran):

  delete      only a copy whose id ALSO has a row under its UTC start day, and only the non-start-day
              copy. ``assert_no_id_loses_last_row`` refuses the WHOLE run if any id would lose its
              last row. An id with no row on its start day is a re-key, never touched here.
  relabel     ``sport_name`` := vendor label (resolved exactly as ``plan_relabel`` does: the row's
              own vendor label, then the archive record, then the one-label sport id); the previous
              label goes to ``legacy_sport_name`` (never overwritten once set). Unresolved rows are
              untouched and counted.
  --keep-label L   (repeatable) rows whose current ``sport_name`` is L are excluded from the relabel.
  --limit N        at most N writes in total (deletes first), for a bounded first apply.
  --report PATH    JSON of the counts (rows_deleted, rows_relabelled, rows_kept_by_label,
                   rows_unresolved, per-label change table).
  --list-plan      print the per-id plan (always printed by --apply before the first write).

THE FRAME is the writer's own: ``whoop_lambda._utc_day`` (the reconciler's expected key), imported,
so this report can never key a workout differently from ingestion.

RUN:  AWS_MAX_ATTEMPTS=1 python3 scripts/whoop_workout_history_4629.py --dry-run
      AWS_MAX_ATTEMPTS=1 python3 scripts/whoop_workout_history_4629.py --dry-run --no-archive
      AWS_MAX_ATTEMPTS=1 python3 scripts/whoop_workout_history_4629.py --apply --keep-label Yoga --report <path>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")
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


class UnsafeDeletePlan(RuntimeError):
    """A planned deletion would leave a workout id with no row at all."""


def _resolve_vendor(r: dict, by_wid: dict, by_sport: dict):
    """The vendor label for one row, in ``plan_relabel``'s precedence; None when unresolvable."""
    if r.get("vendor_sport_name"):
        return str(r["vendor_sport_name"])
    if _wid(r) in by_wid:
        return by_wid[_wid(r)]
    if r.get("sport_id") is not None and len(by_sport.get(int(r["sport_id"]), ())) == 1:
        return next(iter(by_sport[int(r["sport_id"])]))
    return None


def plan_deletes(rows: list) -> tuple[list, int]:
    """(deletes, skipped_ids): the off-start-day copies of ids that also have a start-day row."""
    by_id: dict = {}
    for r in workout_rows(rows):
        by_id.setdefault(_wid(r), []).append(r)
    deletes: list = []
    skipped = 0
    for wid, copies in sorted(by_id.items()):
        days = {_key_day(str(r["sk"])) for r in copies}
        if len(days) < 2:
            continue
        start_days = {_utc_day(r.get("start_time")) for r in copies} - {None}
        if len(start_days) != 1 or next(iter(start_days)) not in days:
            skipped += 1  # no/ambiguous start time, or no row on the start day: a re-key, not a delete
            continue
        start_day = next(iter(start_days))
        keep = sorted(str(r["sk"]) for r in copies if _key_day(str(r["sk"])) == start_day)[0]
        for r in sorted(copies, key=lambda x: str(x["sk"])):
            if _key_day(str(r["sk"])) != start_day:
                deletes.append({"workout_id": wid, "delete_sk": str(r["sk"]), "keep_sk": keep})
    return deletes, skipped


def assert_no_id_loses_last_row(rows: list, deletes: list) -> None:
    """Refuse the whole run if the planned deletions would leave any workout id with zero rows."""
    gone = {d["delete_sk"] for d in deletes}
    left: Counter = Counter()
    for r in workout_rows(rows):
        if str(r["sk"]) not in gone:
            left[_wid(r)] += 1
    lost = sorted({d["workout_id"] for d in deletes if left[d["workout_id"]] == 0})
    if lost:
        raise UnsafeDeletePlan(f"{len(lost)} workout id(s) would lose their last row: {lost[:5]}")


def build_plan(rows: list, by_wid: dict, by_sport: dict, keep_labels=(), limit: int | None = None) -> dict:
    """The ONE plan --dry-run prints and --apply executes (deletes first, then relabels, capped by limit)."""
    keep = {str(k) for k in keep_labels}
    deletes, skipped = plan_deletes(rows)
    assert_no_id_loses_last_row(rows, deletes)
    gone = {d["delete_sk"] for d in deletes}
    relabels: list = []
    kept: Counter = Counter()
    unresolved = 0
    for r in sorted(workout_rows(rows), key=lambda x: str(x["sk"])):
        if str(r["sk"]) in gone:
            continue
        vendor = _resolve_vendor(r, by_wid, by_sport)
        if vendor is None:
            unresolved += 1
            continue
        stored = r.get("sport_name")
        if stored == vendor:
            continue
        if stored is not None and str(stored) in keep:
            kept[str(stored)] += 1
            continue
        relabels.append({"workout_id": _wid(r), "sk": str(r["sk"]), "from": None if stored is None else str(stored), "to": vendor})
    if limit is not None:
        deletes = deletes[: max(limit, 0)]
        relabels = relabels[: max(limit - len(deletes), 0)]
    changes = Counter(f"{x['from']} -> {x['to']}" for x in relabels)
    plan = {
        "deletes": deletes,
        "relabels": relabels,
        "ids_skipped_rekey_or_ambiguous": skipped,
        "rows_kept_by_label": sum(kept.values()),
        "kept_by_label": dict(sorted(kept.items())),
        "rows_unresolved": unresolved,
        "label_changes": dict(changes.most_common()),
    }
    plan["plan_sha256"] = hashlib.sha256(json.dumps([deletes, relabels], sort_keys=True).encode()).hexdigest()
    return plan


def plan_summary(plan: dict) -> dict:
    return {
        "rows_to_delete": len(plan["deletes"]),
        "rows_to_relabel": len(plan["relabels"]),
        "rows_kept_by_label": plan["rows_kept_by_label"],
        "kept_by_label": plan["kept_by_label"],
        "rows_unresolved": plan["rows_unresolved"],
        "ids_skipped_rekey_or_ambiguous": plan["ids_skipped_rekey_or_ambiguous"],
        "label_changes": plan["label_changes"],
        "plan_sha256": plan["plan_sha256"],
    }


def print_plan_lines(plan: dict) -> None:
    for d in plan["deletes"]:
        print(f"DELETE id={d['workout_id']} sk={d['delete_sk']} (keeps {d['keep_sk']})")
    for x in plan["relabels"]:
        print(f"RELABEL id={x['workout_id']} sk={x['sk']} {x['from']!r} -> {x['to']!r}")


def apply_plan(table, plan: dict, user_id: str) -> dict:
    """Execute the plan with delete_item / update_item; returns the counts that were written."""
    pk = f"USER#{user_id}#SOURCE#whoop"
    deleted = relabelled = 0
    for d in plan["deletes"]:
        table.delete_item(Key={"pk": pk, "sk": d["delete_sk"]}, ConditionExpression="attribute_exists(sk)")
        deleted += 1
    for x in plan["relabels"]:
        values = {":n": x["to"]}
        expr = "SET sport_name = :n"
        if x["from"] is not None:
            expr += ", legacy_sport_name = if_not_exists(legacy_sport_name, :o)"
            values[":o"] = x["from"]
            cond = "attribute_exists(sk) AND sport_name = :o"
        else:
            cond = "attribute_exists(sk)"
        table.update_item(Key={"pk": pk, "sk": x["sk"]}, UpdateExpression=expr, ConditionExpression=cond, ExpressionAttributeValues=values)
        relabelled += 1
    return {"rows_deleted": deleted, "rows_relabelled": relabelled}


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


def main(argv: list | None = None, table=None, s3=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report only; prints the plan --apply would execute")
    mode.add_argument("--apply", action="store_true", help="execute the duplicate removal and the relabel")
    ap.add_argument("--no-archive", action="store_true", help="skip the S3 archive read (relabel evidence from the rows only)")
    ap.add_argument(
        "--keep-label", action="append", default=[], metavar="LABEL", help="repeatable: leave rows with this current sport_name"
    )
    ap.add_argument("--limit", type=int, default=None, metavar="N", help="at most N writes in total (deletes first)")
    ap.add_argument("--report", default=None, metavar="PATH", help="write the JSON counts here")
    ap.add_argument("--list-plan", action="store_true", help="print the per-id plan lines (always on for --apply)")
    args = ap.parse_args(argv)

    if table is None:
        import boto3
        from botocore.config import Config

        cfg = Config(retries={"max_attempts": 1})
        region = os.environ["AWS_DEFAULT_REGION"]
        table = boto3.resource("dynamodb", region_name=region, config=cfg).Table(os.environ["TABLE_NAME"])
        s3 = s3 or boto3.client("s3", region_name=region, config=cfg)
    rows = _read_store(table)
    payloads: dict = {}
    if not args.no_archive:
        today = datetime.now(timezone.utc).date().isoformat()
        payloads = _read_archive(s3, os.environ["S3_BUCKET"], ARCHIVE_START, today)
    by_wid, by_sport = archive_labels(payloads)
    try:
        plan = build_plan(rows, by_wid, by_sport, args.keep_label, args.limit)
    except UnsafeDeletePlan as e:
        print(f"refusing the whole run: {e}")
        return 3
    report = {
        "write_mode": "apply" if args.apply else "none",
        "archive_days_read": sum(1 for p in payloads.values() if p is not None),
        "keys": tally_keys(rows),
        "relabel": plan_relabel(rows, by_wid, by_sport),
        "plan": plan_summary(plan),
    }
    print(json.dumps(report, indent=2))
    if args.list_plan or args.apply:
        print_plan_lines(plan)
    if args.apply:
        written = apply_plan(table, plan, os.environ["USER_ID"])
        result = {
            **written,
            "rows_kept_by_label": plan["rows_kept_by_label"],
            "rows_unresolved": plan["rows_unresolved"],
            "label_changes": plan["label_changes"],
            "plan_sha256": plan["plan_sha256"],
        }
        print(json.dumps({"applied": result}, indent=2))
    else:
        result = {"dry_run": True, **plan_summary(plan)}
    if args.report:
        with open(args.report, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
