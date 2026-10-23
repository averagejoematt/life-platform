#!/usr/bin/env python3
"""scripts/hae_additive_backfill_4628.py — rebuild the five additive Apple Health day fields
from the raw webhook archive (#4628 box 4; owner Q3 "yes — rebuild from the raw archive").

WHY. From 2026-06-21 the phone's export app delivered INCREMENTAL payloads, and until PR #4962
the writer kept the largest single sync of the day (max-of-source, then GREATEST on write) as the
day total for ``steps``, ``active_calories``, ``basal_calories``, ``distance_walk_run_miles`` and
``flights_climbed``. Every delivery was archived verbatim under the ``apple_health`` raw_layout
prefix, so the delivered readings are still there; this script replays them.

WHAT IT DOES (default, read-only). For every UTC day in [--since, --until]:
  1. lists the archived deliveries by PREFIX, as the registry's ``raw_layout`` says a backfill
     must (the archive is ``timestamped`` — many objects per day, no per-day key to guess) —
     delivery days from since-1 to until+8, because a reading of UTC day D is delivered on D or
     D+1 (the key's day is the DELIVERY day) and a late re-send can land up to 7 days after
     (the live maximum measured on 2026-10-18 — the totals block prints it);
  2. reads every one (threaded GETs; ``AWS_MAX_ATTEMPTS=1``, 60 s read timeout) in RECEIPT
     order (the ``received-at`` metadata the writer stamps, else LastModified) and runs each
     through the writer's own two steps — ``payload_readings`` (the reading's own UTC day, the
     reading's own timestamp as the dedup key) and ``merge_readings`` (a re-sent reading counts
     once; a re-sent timestamp with a new quantity is a revision, every version kept) — then ``day_value`` for the sum. All three are imported
     from ``lambdas/ingestion/health_auto_export_additive.py``: there is no second
     implementation here;
  3. reads the stored ``apple_health`` day rows over the same range (one DynamoDB QUERY);
  4. prints a per-day diff table (stored -> delivered, delta, flags) and a JSON totals block:
     days read, days with/without an archive, days differing, per-field deltas, the maximum
     delivery lag observed.

WRITE MODE — THE OWNER'S / DRIVER'S LINE ONLY. ``--apply``, per day that has archived readings
AND an existing day row (a row is never created) and whose stored values differ or lack the stamp:
  * merges the replayed readings into the per-field S3 objects the live writer sums from
    (``raw_date_key("apple_health", day, sub="additive_<field>")``, same body shape, a stored
    reading moved only by a revision the replay saw, every version kept in ``revisions``) — so the writer's next delivery for that day extends the
    rebuilt total instead of restarting it from one delivery;
  * ``UpdateItem`` SETs the five fields (Decimal), their one derived companion the writer also
    sets (``total_calories_burned`` = active + basal) and ``delivered_readings_only = true``
    (the SCHEMA.md stamp — Q3's label, "what the phone delivered"), under
    ``attribute_exists(sk)``, and nothing else on the row. A field with no archived reading that
    day is left as stored (reported, never zeroed).
A second run writes nothing (the per-day diff is then empty).

WHAT IT CANNOT DO. Readings the phone never delivered are not in any archive. The rebuilt value
is the delivered sum, labelled so on the row; on non-walk days it stays short of the wrist
count (#4628 caveat 1 — which device a steps read uses is the read-side truth facet, Q4).

RUN:  AWS_MAX_ATTEMPTS=1 python3 scripts/hae_additive_backfill_4628.py                      # dry run, 2026-06-21 .. today
      AWS_MAX_ATTEMPTS=1 python3 scripts/hae_additive_backfill_4628.py --since 2026-10-01 --until 2026-10-14
      AWS_MAX_ATTEMPTS=1 python3 scripts/hae_additive_backfill_4628.py --apply              # OWNER / DRIVER ONLY
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import health_auto_export_additive as additive  # noqa: E402
from ingestion.health_auto_export_lambda import METRIC_MAP, _merge_is_valid, parse_date_str  # noqa: E402
from ingestion.source_registry import raw_date_key, raw_layout_for  # noqa: E402

SOURCE = "apple_health"
INCREMENTAL_SINCE = "2026-06-21"  # the day the export went incremental (#4628, dated by archive volume)
FIELDS = additive.ADDITIVE_SUM_FIELDS
PROVENANCE = additive.PROVENANCE_FIELD
DERIVED = "total_calories_burned"  # the writer's one derived companion (health_auto_export_additive.apply_archived_sums)
DELIVERY_SLACK_DAYS = 8  # the live archive's measured maximum re-send lag is 7 days (dry run 2026-10-18)
TOLERANCE = 0.005  # the writer stores 2 dp
_SHORT = {
    "steps": "steps",
    "active_calories": "active",
    "basal_calories": "basal",
    "distance_walk_run_miles": "dist",
    "flights_climbed": "flights",
}


# ── the archive ───────────────────────────────────────────────────────────────


def _leaf_pattern(layout: dict) -> re.Pattern:
    """A matcher for the archive's leaf, built from the registry's own ``filename`` and
    ``filename_legacy`` facets (classification only — a key is never constructed from it)."""
    alts = []
    for facet in (layout.get("filename"), layout.get("filename_legacy")):
        if facet:
            pat = re.escape(facet).replace("DD", r"\d{2}", 1).replace(r"\{contenthash16\}", r"[0-9a-f]{16}").replace("HHMMSS", r"\d{6}")
            alts.append(f"(?:{pat})")
    return re.compile("^" + "|".join(alts) + "$")


def _list(s3, bucket: str, prefix: str):
    kwargs = {"Bucket": bucket, "Prefix": prefix}
    while True:
        resp = s3.list_objects_v2(**kwargs)
        yield from resp.get("Contents", [])
        if not resp.get("IsTruncated"):
            return
        kwargs["ContinuationToken"] = resp["NextContinuationToken"]


def archive_keys(s3, bucket: str, since: str, until: str, today: date) -> list[tuple[str, str, object]]:
    """[(key, delivery_day, LastModified)] for every archived delivery whose DELIVERY day is in
    [since-1, until+slack], oldest delivery first. Listed under the registry prefix."""
    layout = raw_layout_for(SOURCE)
    if layout.get("scheme") != "timestamped":
        raise ValueError(f"{SOURCE} raw_layout is {layout.get('scheme')!r}; this replay is written for the timestamped archive")
    leaf_re = _leaf_pattern(layout)
    first = date.fromisoformat(since) - timedelta(days=1)
    last = min(date.fromisoformat(until) + timedelta(days=DELIVERY_SLACK_DAYS), today)
    out = []
    month = first.replace(day=1)
    while month <= last:
        for obj in _list(s3, bucket, f"{layout['prefix']}/{month:%Y}/{month:%m}/"):
            leaf = obj["Key"].rsplit("/", 1)[-1]
            if not leaf_re.match(leaf):
                continue
            try:
                delivered = month.replace(day=int(leaf[:2]))  # both facets start with DD
            except ValueError:
                continue
            if first <= delivered <= last:
                out.append((obj["Key"], delivered.isoformat(), obj.get("LastModified")))
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    out.sort(key=lambda t: (str(t[2]), t[0]))
    return out


def read_payloads(s3, bucket: str, keys: list, workers: int = 8) -> list[tuple[str, str, dict, str]]:
    """[(key, delivery_day, payload, received_at)] in RECEIPT order: the ``received-at`` metadata the
    writer stamps on each delivery (microseconds, #4628), else the listed LastModified (whole seconds:
    a same-second tie keeps the listing's (LastModified, key) order, which no older archive can resolve)."""

    def _get(item):
        key, delivered, modified = item
        resp = s3.get_object(Bucket=bucket, Key=key)
        received = (resp.get("Metadata") or {}).get("received-at") or additive.received_stamp(
            modified if isinstance(modified, datetime) else None
        )
        return key, delivered, json.loads(resp["Body"].read()), received

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        got = list(pool.map(_get, keys))
    return sorted(got, key=lambda t: t[3])  # stable: equal stamps keep the listed order


def _metrics(payload: dict) -> list:
    """The handler's own unwrapping: HAE wraps everything in a ``data`` key."""
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    return data.get("metrics", []) if isinstance(data, dict) else []


def replay(payloads: list) -> tuple[dict, Counter]:
    """{reading_day: {field: {"units", "readings": {source: {ts: qty}}, "revisions", "deliveries": n}}} plus
    replay stats — each delivery, in receipt order, through the writer's ``payload_readings`` + ``merge_readings``."""
    acc: dict = {}
    stats: Counter = Counter()
    for key, delivered, payload, received_at in payloads:
        stats["payloads_read"] += 1
        for day, per_field in additive.payload_readings(_metrics(payload), METRIC_MAP, parse_date_str).items():
            lag = (date.fromisoformat(delivered) - date.fromisoformat(day)).days
            stats["max_delivery_lag_days"] = max(stats["max_delivery_lag_days"], lag)
            for field, entry in per_field.items():
                slot = acc.setdefault(day, {}).setdefault(
                    field, {"units": entry["units"], "readings": {}, "revisions": {}, "deliveries": 0}
                )
                slot["readings"], _, slot["revisions"] = additive.merge_readings(
                    slot["readings"], entry["readings"], slot["revisions"], received_at
                )
                slot["deliveries"] += 1
    return acc, stats


def day_values(per_field: dict) -> dict:
    """{field: the writer's day value} for one replayed day."""
    return {field: additive.day_value(field, slot["readings"], slot["units"]) for field, slot in per_field.items()}


# ── the store ─────────────────────────────────────────────────────────────────


def read_rows(table, pk: str, since: str, until: str) -> dict:
    """{day: stored row (five fields + stamp + derived)} — day rows only, never a workout sub-row."""
    from boto3.dynamodb.conditions import Key

    names = {f"#f{i}": f for i, f in enumerate((*FIELDS, PROVENANCE, DERIVED))}
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{since}", f"DATE#{until}~"),
        "ProjectionExpression": "sk, " + ", ".join(names),
        "ExpressionAttributeNames": names,
    }
    rows: dict = {}
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            sk = str(item.get("sk", ""))
            if sk.startswith("DATE#") and sk.count("#") == 1:
                rows[sk[len("DATE#") :]] = item
        if not resp.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def iter_days(since: str, until: str) -> list[str]:
    d, last = date.fromisoformat(since), date.fromisoformat(until)
    out = []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ── the diff ──────────────────────────────────────────────────────────────────


def diff_day(day: str, per_field: dict | None, row: dict | None) -> dict:
    """One day's verdict: {day, status, fields: {f: (stored, delivered, delta)}, needs_write}."""
    if per_field is None:
        return {"day": day, "status": "no-archive", "fields": {}, "needs_write": False, "deliveries": 0}
    values = day_values(per_field)
    fields = {}
    for field in FIELDS:
        if field not in values:
            continue
        stored = None if row is None or row.get(field) is None else float(row[field])
        fields[field] = (stored, values[field], None if stored is None else round(values[field] - stored, 2))
    if row is None:
        return {"day": day, "status": "no-row", "fields": fields, "needs_write": False, "deliveries": _deliveries(per_field)}
    differing = any(d is None or abs(d) > TOLERANCE for _, _, d in fields.values())
    stamped = row.get(PROVENANCE) is True
    status = "differs" if differing else ("unstamped" if not stamped else "same")
    return {"day": day, "status": status, "fields": fields, "needs_write": differing or not stamped, "deliveries": _deliveries(per_field)}


def _deliveries(per_field: dict) -> int:
    return max((slot["deliveries"] for slot in per_field.values()), default=0)


def summarize(verdicts: list) -> dict:
    """The totals block: days read / with archive / without / differing, per-field deltas."""
    t: Counter = Counter()
    per_field = {f: Counter() for f in FIELDS}
    for v in verdicts:
        t["days_read"] += 1
        t[f"days_{v['status'].replace('-', '_')}"] += 1
        if v["status"] != "no-archive":
            t["days_with_archive"] += 1
        for field, (stored, delivered, delta) in v["fields"].items():
            pf = per_field[field]
            pf["days_with_readings"] += 1
            if stored is None:
                pf["days_stored_absent"] += 1
                continue
            if abs(delta) > TOLERANCE:
                pf["days_differing"] += 1
                pf["days_stored_under"] += delta > 0
                pf["days_stored_over"] += delta < 0
                pf["sum_delta"] = round(pf["sum_delta"] + delta, 2)
                pf["sum_stored"] = round(pf["sum_stored"] + stored, 2)
                pf["sum_delivered"] = round(pf["sum_delivered"] + delivered, 2)
    t["days_to_write"] = sum(1 for v in verdicts if v["needs_write"])
    for k in ("days_with_archive", "days_no_archive", "days_no_row", "days_differs", "days_unstamped", "days_same"):
        t.setdefault(k, 0)
    out = dict(sorted(t.items()))
    out["per_field"] = {
        f: {
            **{k: 0 for k in ("days_with_readings", "days_differing", "days_stored_under", "days_stored_over", "days_stored_absent")},
            **dict(c),
        }
        for f, c in per_field.items()
    }
    return out


def _num(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def format_row(v: dict) -> str:
    cells = []
    for field in FIELDS:
        if field not in v["fields"]:
            cells.append(f"{_SHORT[field]}: -")
            continue
        stored, delivered, delta = v["fields"][field]
        s = "none" if stored is None else _num(stored)
        d = "" if delta is None else f" ({'+' if delta >= 0 else '-'}{_num(abs(delta))})"
        cells.append(f"{_SHORT[field]}: {s}->{_num(delivered)}{d}")
    return f"{v['day']}  {v['deliveries']:>3}d  {v['status']:<10}  " + "  ".join(cells)


# ── the write (owner / driver only) ───────────────────────────────────────────


def _read_object(s3, bucket: str, key: str) -> dict:
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except s3.exceptions.NoSuchKey:
        return {}


def _merge_replayed(stored: dict, slot: dict) -> tuple[dict, dict, int]:
    """The stored object + the replay, through the writer's own ``merge_readings``: each reading's
    first replayed version, then every later version in receipt order, so a revision the replay saw
    moves the value exactly as it would have live. Returns (readings, revisions, changes)."""
    replayed_revs = slot.get("revisions") or {}
    first = {
        src: {ts: (replayed_revs.get(src, {}).get(ts) or [["", q]])[0][1] for ts, q in tsq.items()} for src, tsq in slot["readings"].items()
    }
    merged, changes, revisions = additive.merge_readings(stored.get("readings"), first, stored.get("revisions"))
    for src, tsv in replayed_revs.items():
        for ts, versions in tsv.items():
            for received_at, qty in versions[1:]:
                merged, n, revisions = additive.merge_readings(merged, {src: {ts: qty}}, revisions, received_at)
                changes += n
    return merged, revisions, changes


def rebuild_archive(s3, bucket: str, day: str, per_field: dict) -> tuple[dict, int]:
    """Merge the replayed readings into the writer's per-field objects; returns (values, objects_written).
    The value is summed from the MERGED object — what the writer will sum on its next delivery."""
    values, written = {}, 0
    for field, slot in per_field.items():
        key = raw_date_key(SOURCE, day, sub=f"additive_{field}")
        stored = _read_object(s3, bucket, key)
        merged, revisions, changes = _merge_replayed(stored, slot)
        units = stored.get("units") or slot["units"]
        if changes or not stored:
            body = {"field": field, "date": day, "units": units, "readings": merged}
            if revisions:
                body["revisions"] = revisions
            s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(body, sort_keys=True), ContentType="application/json")
            written += 1
        values[field] = additive.day_value(field, merged, units)
    return values, written


def write_row(table, pk: str, day: str, values: dict) -> bool:
    """SET the rebuilt fields + the derived total + the stamp on an EXISTING row; nothing else."""
    from botocore.exceptions import ClientError

    fields = {f: round(v, 2) for f, v in values.items()}
    if fields.get("active_calories") is not None and fields.get("basal_calories") is not None:
        fields[DERIVED] = round(fields["active_calories"] + fields["basal_calories"], 2)
    if not _merge_is_valid(dict(fields), day):
        return False
    names = {f"#f{i}": f for i, f in enumerate(fields)}
    names["#p"] = PROVENANCE
    vals = {f":v{i}": Decimal(str(fields[f])) for i, f in enumerate(fields)}
    vals[":p"] = True
    expr = "SET " + ", ".join(f"{n} = :v{n[2:]}" for n in names if n != "#p") + ", #p = :p"
    try:
        table.update_item(
            Key={"pk": pk, "sk": f"DATE#{day}"},
            UpdateExpression=expr,
            ConditionExpression="attribute_exists(sk)",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=vals,
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        return False
    return True


def apply_days(s3, bucket: str, table, pk: str, replayed: dict, verdicts: list) -> dict:
    c: Counter = Counter()
    for v in verdicts:
        if not v["needs_write"]:
            continue
        values, objects = rebuild_archive(s3, bucket, v["day"], replayed[v["day"]])
        c["archive_objects_written"] += objects
        if write_row(table, pk, v["day"], values):
            c["rows_written"] += 1
        else:
            c["rows_refused"] += 1
    for k in ("archive_objects_written", "rows_written", "rows_refused"):
        c.setdefault(k, 0)
    return dict(c)


# ── main ──────────────────────────────────────────────────────────────────────


def _clients():
    import boto3
    from botocore.config import Config

    cfg = Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 1})
    region = os.environ["AWS_DEFAULT_REGION"]
    return boto3.client("s3", region_name=region, config=cfg), boto3.resource("dynamodb", region_name=region, config=cfg).Table(
        os.environ["DYNAMODB_TABLE"]
    )


def main(argv: list | None = None, s3=None, table=None, today: date | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", default=INCREMENTAL_SINCE, help="first UTC reading day (default: the incremental cutover)")
    ap.add_argument("--until", default=None, help="last UTC reading day (default: today, UTC)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--apply", action="store_true", help="OWNER / DRIVER ONLY: rebuild the archive objects and SET the rows")
    args = ap.parse_args(argv)
    today = today or datetime.now(timezone.utc).date()
    since, until = date.fromisoformat(args.since).isoformat(), (args.until or today.isoformat())
    date.fromisoformat(until)

    if s3 is None or table is None:
        s3, table = _clients()
    bucket, pk = os.environ["S3_BUCKET"], f"USER#{os.environ['USER_ID']}#SOURCE#{SOURCE}"

    keys = archive_keys(s3, bucket, since, until, today)
    replayed, stats = replay(read_payloads(s3, bucket, keys, args.workers))
    rows = read_rows(table, pk, since, until)
    verdicts = [diff_day(day, replayed.get(day), rows.get(day)) for day in iter_days(since, until)]

    print(f"# {SOURCE} additive rebuild — {since} .. {until} — {'APPLY' if args.apply else 'dry run'} (stored->delivered, delta)")
    for v in verdicts:
        print(format_row(v))
    report = {"range": [since, until], "mode": "apply" if args.apply else "dry-run", **dict(stats), **summarize(verdicts)}
    if args.apply:
        report["apply"] = apply_days(s3, bucket, table, pk, replayed, verdicts)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
