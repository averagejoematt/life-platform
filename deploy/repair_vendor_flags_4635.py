#!/usr/bin/env python3
"""
repair_vendor_flags_4635.py — put the vendor's own values onto rows stored before #4635.

Two partitions, one class (a vendor flag or enum stored with a meaning other than the
vendor's). The ingestion fix only reaches rows written after it deploys; this is the
repair for the rows already there. It never recomputes a night or a task list — it
only adds the fields the transform now writes, taken from the archived raw payload
each stored row was built from.

  eightsleep  adds `vendor_incomplete` (+ `vendor_processing`, `vendor_lag_minutes`
              when the vendor sent them) from the day entry whose `day` is the row's
              own date. Sleep figures on the row are left exactly as they are. A row
              is only touched when the archived night is still the night that was
              stored (same sleep duration); otherwise it is reported and skipped.

  todoist     adds `priority_counts_vendor` (count of active tasks per API priority
              integer) and rewrites the derived `priority_breakdown` in the app's
              p1..p4 order (API 4 = p1_urgent). Source of the counts, in order:
                archive   the archived payload's active tasks (the vendor's integers)
                mirrored  no archive for that date — the stored labels read backwards,
                          which is exact because the old map was a pure mirror
              When both exist and disagree the row is reported and skipped.

Read-only by default. Apply with --apply.

  python3 deploy/repair_vendor_flags_4635.py                      # dry-run, both sources
  python3 deploy/repair_vendor_flags_4635.py --source eightsleep  # dry-run, one source
  python3 deploy/repair_vendor_flags_4635.py --since 2026-09-01   # dry-run, bounded
  python3 deploy/repair_vendor_flags_4635.py --apply              # write
"""

import argparse
import json
import os
import sys
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

TABLE = "life-platform"
BUCKET = "matthew-life-platform"
REGION = "us-west-2"
USER_ID = "matthew"

VENDOR_PRIORITIES = (1, 2, 3, 4)
LABEL_BY_VENDOR = {4: "p1_urgent", 3: "p2_high", 2: "p3_medium", 1: "p4_normal"}
LEGACY_LABEL_BY_VENDOR = {1: "p1_urgent", 2: "p2_high", 3: "p3_medium", 4: "p4_normal"}


# ── Pure planners (no AWS — unit-tested) ───────────────────────────────────────


def _unwrap(archive):
    """The fetch_day payload inside an archived object (`{"fetched_at", "raw"}`),
    tolerating an object that is already the bare payload."""
    if isinstance(archive, dict) and isinstance(archive.get("raw"), dict):
        return archive["raw"]
    return archive if isinstance(archive, dict) else {}


def plan_eightsleep(item, archive):
    """→ (status, fields). status is one of:
    update | current | no-day | night-differs | no-flag."""
    date_str = str(item.get("sk", ""))[len("DATE#") :]
    raw = _unwrap(archive)
    trends = raw.get("trends") if isinstance(raw.get("trends"), dict) else raw
    day = next((d for d in (trends.get("days") or []) if isinstance(d, dict) and d.get("day") == date_str), None)
    if day is None:
        return "no-day", {}
    stored_h = item.get("sleep_duration_hours")
    sleep_s = day.get("sleepDuration")
    if stored_h is not None and sleep_s is not None and abs(float(stored_h) - round(sleep_s / 3600.0, 2)) > 0.011:
        return "night-differs", {}
    fields = {}
    if isinstance(day.get("incomplete"), bool):
        fields["vendor_incomplete"] = day["incomplete"]
    if isinstance(day.get("processing"), bool):
        fields["vendor_processing"] = day["processing"]
    lag = day.get("lagMinutes")
    if isinstance(lag, (int, float)) and not isinstance(lag, bool):
        fields["vendor_lag_minutes"] = lag
    if not fields:
        return "no-flag", {}
    if all(_same(item.get(k), v) for k, v in fields.items()):
        return "current", fields
    return "update", fields


def _same(stored, want):
    if isinstance(want, bool) or isinstance(stored, bool):
        return stored is want
    if stored is None:
        return False
    return abs(float(stored) - float(want)) < 1e-9


def counts_from_tasks(tasks):
    counts = {str(p): 0 for p in VENDOR_PRIORITIES}
    unknown = 0
    for t in tasks:
        p = t.get("priority") if isinstance(t, dict) else None
        if isinstance(p, bool) or p not in VENDOR_PRIORITIES:
            unknown += 1
        else:
            counts[str(p)] += 1
    if unknown:
        counts["unknown"] = unknown
    return counts


def counts_from_legacy_breakdown(breakdown):
    return {str(p): int(breakdown.get(label, 0)) for p, label in LEGACY_LABEL_BY_VENDOR.items()}


def plan_todoist(item, archive):
    """→ (status, fields). status is one of:
    update-archive | update-mirrored | current | no-priority-data | disagree."""
    if isinstance(item.get("priority_counts_vendor"), dict) and item["priority_counts_vendor"]:
        return "current", {}
    legacy = item.get("priority_breakdown")
    legacy_counts = counts_from_legacy_breakdown(legacy) if isinstance(legacy, dict) and legacy else None
    raw = _unwrap(archive) if archive is not None else {}
    active = raw.get("active_tasks")
    archive_counts = counts_from_tasks(active) if isinstance(active, list) else None

    if archive_counts is None and legacy_counts is None:
        return "no-priority-data", {}
    if archive_counts is not None and legacy_counts is not None:
        # The old writer filed an unusable priority under "p4_normal" (API 4 when read
        # backwards), so compare with the archive's unknowns folded the same way.
        folded = {k: v for k, v in archive_counts.items() if k != "unknown"}
        folded["4"] += archive_counts.get("unknown", 0)
        if folded != legacy_counts:
            return "disagree", {"archive": archive_counts, "stored_read_backwards": legacy_counts}
    counts = archive_counts if archive_counts is not None else legacy_counts
    status = "update-archive" if archive_counts is not None else "update-mirrored"
    return status, {
        "priority_counts_vendor": counts,
        "priority_breakdown": {label: int(counts.get(str(p), 0)) for p, label in LABEL_BY_VENDOR.items()},
    }


# ── AWS shell ──────────────────────────────────────────────────────────────────


def _query_all(table, pk, since):
    from boto3.dynamodb.conditions import Key

    cond = Key("pk").eq(pk) & (Key("sk").gte(f"DATE#{since}") if since else Key("sk").begins_with("DATE#"))
    items, kwargs = [], {"KeyConditionExpression": cond}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


UNREADABLE = object()  # an archive object exists but this principal cannot read it


def _load_archive(s3, source, date_str):
    """The archived raw object for one day, trying every documented key generation.
    None when no generation exists; UNREADABLE when one exists but GetObject is
    denied (some older objects sit under a KMS key that no longer resolves) — the
    caller counts those out loud rather than treating them as absent. Any other S3
    error propagates."""
    from botocore.exceptions import ClientError
    from ingestion.source_registry import raw_date_key_candidates

    denied = False
    for key in raw_date_key_candidates(source, date_str):
        try:
            return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                continue
            if code == "AccessDenied":
                denied = True
                continue
            raise
    return UNREADABLE if denied else None


def _to_ddb(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _to_ddb(x) for k, x in v.items()}
    return v


def _write(table, pk, sk, fields):
    names = {f"#f{i}": k for i, k in enumerate(fields)}
    table.update_item(
        Key={"pk": pk, "sk": sk},
        UpdateExpression="SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(fields))),
        ConditionExpression="attribute_exists(pk)",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues={f":v{i}": _to_ddb(v) for i, v in enumerate(fields.values())},
    )


def _is_day_row(item):
    """A plain `DATE#YYYY-MM-DD` row that holds data — not a sub-item, not an
    absence marker."""
    return len(str(item.get("sk", ""))) == len("DATE#YYYY-MM-DD") and not item.get("absent")


def run(source, planner, table, s3, since, apply):
    pk = f"USER#{USER_ID}#SOURCE#{source}"
    tally: dict[str, int] = {}
    flagged = []
    for item in _query_all(table, pk, since):
        if not _is_day_row(item):
            continue
        date_str = item["sk"][len("DATE#") :]
        archive = _load_archive(s3, source, date_str)
        if archive is UNREADABLE:
            tally["archive-unreadable"] = tally.get("archive-unreadable", 0) + 1
            archive = None  # todoist can still mirror the stored labels; eightsleep cannot
        if archive is None and source == "eightsleep":
            tally["no-archive"] = tally.get("no-archive", 0) + 1
            continue
        status, fields = planner(item, archive)
        tally[status] = tally.get(status, 0) + 1
        if source == "eightsleep" and fields.get("vendor_incomplete") is True:
            flagged.append(date_str)
        if status in ("disagree", "night-differs"):
            print(f"  {source} {date_str}  SKIPPED ({status}) {fields or ''}")
        if status.startswith("update"):
            if source == "eightsleep" and fields.get("vendor_incomplete") is not True:
                pass  # an unflagged night: counted, not listed — the list is the flagged ones
            elif source == "eightsleep":
                print(f"  eightsleep {date_str}  {fields}")
            if apply:
                _write(table, pk, item["sk"], fields)
    mode = "APPLIED" if apply else "DRY-RUN (no writes)"
    print(f"{mode} {source}: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    if source == "eightsleep":
        print(f"  nights the vendor flagged incomplete: {len(flagged)} — {', '.join(flagged) or 'none'}")
    return tally


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the fields (default: dry-run, no writes)")
    ap.add_argument("--source", choices=("eightsleep", "todoist", "both"), default="both")
    ap.add_argument("--since", help="only rows dated YYYY-MM-DD or later (default: every row)")
    args = ap.parse_args()

    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    s3 = boto3.client("s3", region_name=REGION)
    if args.source in ("eightsleep", "both"):
        run("eightsleep", plan_eightsleep, table, s3, args.since, args.apply)
    if args.source in ("todoist", "both"):
        run("todoist", plan_todoist, table, s3, args.since, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
