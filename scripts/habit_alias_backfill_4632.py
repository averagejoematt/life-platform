#!/usr/bin/env python3
"""scripts/habit_alias_backfill_4632.py — count (and, owner-run only, back-fill) the vendor habit id
and the ingest-derived ``aliases`` onto the historical ``SOURCE#habitify`` day rows (#4632 box 1,
#4644 Q26: "same habit keeps its streak (id-keyed), applied to the history too").

WHY. Rows ingested before #4921 (2026-10-15) key ``habit_statuses`` by display name only; the vendor's
habit id was never stored, so every rename in history (2026-08-09, 2026-08-15, 2026-10-03) splits a
habit's series in two. The archive at ``raw_layout`` (``source_registry.raw_date_key``) still holds the
journal the writer saw that day, id per entry. Since #4945 the writer stamps ``habit_id`` and derives
``aliases`` from id continuity against the nearest earlier stored day; this script does the same
derivation over the whole stored history, in date order, so the chain the writer builds forward is
also true backward.

WHAT IT DOES (default, read-only). ONE DynamoDB Query over the habitify partition in [--start, --end]
(``sk, habit_statuses, updated_at`` only) and one S3 GetObject per stored day that has statuses. For
each day, ascending, every status entry resolves its id — the stored ``habit_id`` if the row already
carries one, else the day's archived ``journal[*].name -> id``, else the name's id across the WHOLE
archive when that name only ever mapped to one id (an ambiguous name is never stamped) — and gains as
``aliases`` every OTHER name that id carried on an earlier stored day (the writer's own
``_merge_aliases``: sorted, de-duplicated, the entry's own name excluded). It prints COUNTS ONLY:

  stored_day_rows / rows_with_statuses / rows_without_statuses (gap `absent` markers)
  days_archived / days_archive_missing
  entries_total / entries_with_id_already / entries_gaining_id / entries_without_id
  entries_gaining_aliases / ids_with_more_than_one_name (renames the history carries)
  ambiguous_names (a name that mapped to two ids — never stamped) / same_day_duplicate_ids
  rows_to_rewrite

No record keys, no dates, no habit names (CONVENTIONS: no live record keys or habit names in output).

WRITE MODE — THE OWNER'S LINE ONLY. ``--apply`` rewrites ``habit_statuses`` on exactly the
``rows_to_rewrite`` set, one ``UpdateItem`` per row, conditioned on the row existing AND its
``updated_at`` being the one the plan read (``attribute_exists(sk) AND updated_at = :u``), so it never
creates a row and never races the writer: a row the ingest touched in between is skipped and counted
(``rows_skipped_changed_underneath``), never overwritten. Nothing else on the row changes — statuses,
values, notes and ``updated_at`` are carried verbatim (Decimal in, Decimal out; a float anywhere in
the map is refused before the call). A re-run is a no-op (``rows_to_rewrite: 0``). A lane never runs it.

COVERAGE. The default window ends two Pacific days before today: the writer re-reads yesterday and
today on every run (``LOOKBACK_DAYS``) and derives their aliases itself; everything older is only
re-read when the row is missing, which is why the history needs this one pass. The stored history
starts 2026-02-23 and the archive 2026-03; the stored days before it carry no ``habit_statuses``
(``rows_without_statuses``, 35 on the first dry run) and are left alone.

AWS. One client config throughout: ``AWS_MAX_ATTEMPTS=1`` (no retries) and a 60 s read timeout — the
same plain call pattern as the brief's ``aws … --cli-read-timeout 60``.

RUN:  python3 scripts/habit_alias_backfill_4632.py                      # dry run, first stored day .. today-2
      python3 scripts/habit_alias_backfill_4632.py --apply              # OWNER ONLY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")

from common.pacific_time import pacific_today  # noqa: E402
from ingestion.habitify_lambda import _merge_aliases  # noqa: E402  — the writer's own alias merge
from ingestion.source_registry import raw_date_key  # noqa: E402

SOURCE = "habitify"
FIELD = "habit_statuses"
HISTORY_START = "2026-01-01"  # before the first stored habitify day (2026-02-23); the archive starts 2026-03 (backfilled 2026-05-30)
READ_TIMEOUT_S = 60


def default_end() -> str:
    """Two Pacific days before today: the writer owns yesterday and today (LOOKBACK_DAYS)."""
    return (date.fromisoformat(pacific_today()) - timedelta(days=2)).isoformat()


def archive_name_ids(payload: dict | None) -> dict[str, str] | None:
    """{display name: vendor habit id} from one archived day — the framework envelope is {fetched_at, raw}.

    Archived (``is_archived``) journal entries are included: a stored entry can only have come from
    a journal entry, and the writer skipped archived ones, so including them here cannot stamp a
    wrong id — it only lets a name that was later archived still resolve. ``None`` = no archive.
    """
    if payload is None:
        return None
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else payload
    out: dict[str, str] = {}
    for entry in (raw or {}).get("journal") or []:
        name, habit_id = entry.get("name"), entry.get("id")
        if isinstance(name, str) and name and habit_id:
            out[name] = str(habit_id)
    return out


def _global_name_ids(day_maps: dict[str, dict | None]) -> tuple[dict[str, str], set]:
    """(name -> its ONE id across the archive, names that ever mapped to two ids)."""
    ids_by_name: dict[str, set] = {}
    for m in day_maps.values():
        for name, habit_id in (m or {}).items():
            ids_by_name.setdefault(name, set()).add(habit_id)
    ambiguous = {n for n, ids in ids_by_name.items() if len(ids) > 1}
    return {n: next(iter(ids)) for n, ids in ids_by_name.items() if len(ids) == 1}, ambiguous


def _resolve_id(name: str, hs: dict, day_map: dict | None, global_map: dict, ambiguous: set):
    if hs.get("habit_id"):
        return str(hs["habit_id"])
    if day_map and name in day_map:
        return day_map[name]
    if name in ambiguous:
        return None
    return global_map.get(name)


def _plan_day(statuses: dict, day_map, global_map, ambiguous, seen: dict, c: Counter) -> dict | None:
    """The rewritten status map for one day, or None when nothing on it changes. Updates ``seen``."""
    changed = False
    new_statuses: dict = {}
    day_names: dict[str, set] = {}
    for name, hs in statuses.items():
        if not isinstance(hs, dict):
            new_statuses[name] = hs
            continue
        c["entries_total"] += 1
        habit_id = _resolve_id(name, hs, day_map, global_map, ambiguous)
        if habit_id is None:
            c["entries_without_id"] += 1
            new_statuses[name] = hs
            continue
        new = dict(hs)
        if hs.get("habit_id"):
            c["entries_with_id_already"] += 1
        else:
            new["habit_id"] = habit_id
            c["entries_gaining_id"] += 1
        before = set(hs.get("aliases") or ())
        _merge_aliases(new, seen.get(habit_id, set()) - {name})
        if set(new.get("aliases") or ()) != before:
            c["entries_gaining_aliases"] += 1
        if habit_id in day_names:
            c["same_day_duplicate_ids"] += 1
        day_names.setdefault(habit_id, set()).update({name}, new.get("aliases") or ())
        changed = changed or new != hs
        new_statuses[name] = new
    for habit_id, names in day_names.items():  # the day's names join the chain AFTER the day is planned
        seen.setdefault(habit_id, set()).update(names)
    return new_statuses if changed else None


def plan(rows: list[dict], raw_by_day: dict[str, dict | None]) -> tuple[dict, dict]:
    """(counts, rewrites). ``rewrites`` maps a row's sk to (new habit_statuses, the updated_at it was planned from)."""
    c: Counter = Counter()
    day_maps = {d: archive_name_ids(p) for d, p in raw_by_day.items()}
    c["days_archived"] = sum(1 for m in day_maps.values() if m is not None)
    c["days_archive_missing"] = sum(1 for m in day_maps.values() if m is None)
    global_map, ambiguous = _global_name_ids(day_maps)
    c["ambiguous_names"] = len(ambiguous)
    seen: dict[str, set] = {}  # {habit_id: every name it has carried on an earlier stored day}
    rewrites: dict = {}
    for row in sorted(rows, key=lambda r: str(r.get("sk", ""))):
        sk = str(row.get("sk", ""))
        c["stored_day_rows"] += 1
        statuses = row.get(FIELD)
        if not isinstance(statuses, dict) or not statuses:
            c["rows_without_statuses"] += 1
            continue
        c["rows_with_statuses"] += 1
        new_statuses = _plan_day(statuses, day_maps.get(sk[len("DATE#") :]), global_map, ambiguous, seen, c)
        if new_statuses is not None:
            rewrites[sk] = (new_statuses, row.get("updated_at"))
    c["rows_to_rewrite"] = len(rewrites)
    c["ids_with_more_than_one_name"] = sum(1 for names in seen.values() if len(names) > 1)
    for k in (
        "rows_without_statuses",
        "entries_total",
        "entries_with_id_already",
        "entries_gaining_id",
        "entries_without_id",
        "entries_gaining_aliases",
        "same_day_duplicate_ids",
    ):
        c.setdefault(k, 0)
    return dict(sorted(c.items())), rewrites


def assert_decimal_safe(value, path: str = FIELD) -> None:
    """boto3 refuses float; the resource layer hands us Decimal and we must hand Decimal back."""
    if isinstance(value, float):
        raise TypeError(f"float at {path} — the rewrite would be refused by DynamoDB")
    if isinstance(value, dict):
        for k, v in value.items():
            assert_decimal_safe(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple, set)):
        for i, v in enumerate(value):
            assert_decimal_safe(v, f"{path}[{i}]")


def apply_rewrites(table, pk: str, rewrites: dict) -> dict:
    """OWNER ONLY. Rewrites the status map on rows the plan read, skipping any the writer touched since."""
    from botocore.exceptions import ClientError

    written = skipped = 0
    for sk, (new_statuses, updated_at) in rewrites.items():
        assert_decimal_safe(new_statuses)
        kwargs = {
            "Key": {"pk": pk, "sk": sk},
            "UpdateExpression": "SET #f = :m",
            "ExpressionAttributeNames": {"#f": FIELD},
            "ExpressionAttributeValues": {":m": new_statuses},
        }
        if updated_at is None:
            kwargs["ConditionExpression"] = "attribute_exists(sk) AND attribute_not_exists(updated_at)"
        else:
            kwargs["ConditionExpression"] = "attribute_exists(sk) AND updated_at = :u"
            kwargs["ExpressionAttributeValues"][":u"] = updated_at
        try:
            table.update_item(**kwargs)
            written += 1
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            skipped += 1
    return {"rows_written": written, "rows_skipped_changed_underneath": skipped}


def _read_archive(s3, bucket: str, days: list) -> dict:
    out: dict = {}
    for day in days:
        try:
            body = s3.get_object(Bucket=bucket, Key=raw_date_key(SOURCE, day))["Body"].read()
        except s3.exceptions.NoSuchKey:
            out[day] = None
            continue
        out[day] = json.loads(body)
    return out


def _read_store(table, pk: str, start: str, end: str) -> list:
    from boto3.dynamodb.conditions import Key

    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start}", f"DATE#{end}"),
        "ProjectionExpression": "sk, #f, updated_at",
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
    ap.add_argument("--start", default=HISTORY_START)
    ap.add_argument("--end", default=None, help="last day to touch (default: two Pacific days before today)")
    ap.add_argument("--apply", action="store_true", help="OWNER ONLY: rewrite habit_statuses on the rows the plan names")
    args = ap.parse_args(argv)
    end = args.end or default_end()

    import boto3
    from botocore.config import Config

    cfg = Config(read_timeout=READ_TIMEOUT_S, retries={"total_max_attempts": 1})
    region = os.environ["AWS_DEFAULT_REGION"]
    pk = f"USER#{os.environ['USER_ID']}#SOURCE#{SOURCE}"
    table = boto3.resource("dynamodb", region_name=region, config=cfg).Table(os.environ["TABLE_NAME"])
    rows = _read_store(table, pk, args.start, end)
    days = sorted(str(r.get("sk", ""))[len("DATE#") :] for r in rows if isinstance(r.get(FIELD), dict) and r.get(FIELD))
    payloads = _read_archive(boto3.client("s3", region_name=region, config=cfg), os.environ["S3_BUCKET"], days)
    counts, rewrites = plan(rows, payloads)
    report = {"range": [args.start, end], "mode": "apply" if args.apply else "dry-run", **counts}
    if args.apply:
        report.update(apply_rewrites(table, pk, rewrites))
    print(json.dumps(report, indent=2, default=lambda v: int(v) if isinstance(v, Decimal) else str(v)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
