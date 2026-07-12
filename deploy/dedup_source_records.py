#!/usr/bin/env python3
"""
dedup_source_records.py — delete duplicate DATE# records for one raw-timeseries
source (#1092, generalized from the eightsleep case).

THE CLASS (2026-07-10 truth audit, finding 21): an evening ingestion run that
crosses UTC midnight stamps "today" in UTC and writes the SAME physical session
under a second, later DATE# — the eightsleep instance wrote one night
(sleep_start 2026-07-10T07:46:59Z) under BOTH DATE#2026-07-10 and
DATE#2026-07-11, double-counting it in every 30-day average. The three verified
duplicates (2026-06-27 / 2026-07-03 / 2026-07-11) sat in Matthew's manual
Sunday queue; this script is that pass, foldable into the restart pipeline
(`restart_pipeline.py --dedup-source <name>`).

HOW A DUPLICATE IS IDENTIFIED (deterministic, conservative):
  1. Only rows carrying at least one full ISO datetime value (a session anchor
     like sleep_start / measurement_time_utc) participate — bare markers such
     as gap-filled `no_data` rows share identical content by design and must
     NEVER group as duplicates.
  2. The content fingerprint is every attribute EXCEPT the key/date dimension
     and write-metadata (pk, sk, date, phase, cycle, tombstone*, ingested_at,
     …). Two rows are duplicates only when the remaining content — including
     the session anchors — is identical.
  3. Within a duplicate group the EARLIEST DATE# is kept and the later rows are
     deleted: the UTC-rollover class always duplicates FORWARD (UTC "today" is
     ahead of Pacific "today"), so the earlier date is the real wake/measure day.

SAFETY: the source must classify RAW_TIMESERIES in lambdas/phase_taxonomy.py —
experiment-scoped partitions are the wipe's job (tombstone, never delete) and
cross-phase partitions are never touched. Dry-run by default; --apply deletes.

Usage:
    python3 deploy/dedup_source_records.py --source eightsleep            # dry-run
    python3 deploy/dedup_source_records.py --source eightsleep --apply    # delete
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import phase_taxonomy as taxonomy  # noqa: E402  (ADR-077 registry — the class guard)

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"

# Key/date dimension + write-metadata: excluded from the content fingerprint so a
# re-ingested copy of the same session (different ingested_at, wrong DATE#) still
# fingerprints identically to the original.
EXCLUDE_KEYS = frozenset(
    {
        "pk",
        "sk",
        "date",
        "phase",
        "cycle",
        "tombstone",
        "tombstone_reason",
        "tombstoned_at",
        "ingested_at",
        "ingestion_run_id",
        "updated_at",
        "created_at",
        "last_updated",
        "fetched_at",
        "retrieved_at",
        "backfilled",
        "ttl",
        "expires_at",
    }
)

# A full ISO datetime (date + time) — the session-identity anchor. A bare date
# does NOT qualify: it is exactly the dimension the bug gets wrong.
_ISO_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _jsonable(value):
    """Normalize DDB values for a stable fingerprint (Decimal, sets)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _has_session_anchor(content: dict) -> bool:
    """True when any (nested) value carries a full ISO datetime."""
    blob = json.dumps(_jsonable(content), default=str)
    return bool(_ISO_DATETIME_RE.search(blob))


def fingerprint(item: dict) -> str | None:
    """Content fingerprint for duplicate detection, or None when the row has no
    session-identity anchor (e.g. gap-filled no_data markers) and must not group."""
    content = {k: v for k, v in item.items() if k not in EXCLUDE_KEYS}
    if not content or not _has_session_anchor(content):
        return None
    return json.dumps(_jsonable(content), sort_keys=True, default=str)


def find_duplicate_groups(items: list[dict]) -> list[list[dict]]:
    """Group DATE# rows by content fingerprint; return groups with >1 row, each
    sorted by sk ascending (index 0 = the keeper, the earliest date)."""
    by_fp: dict[str, list[dict]] = {}
    for item in items:
        fp = fingerprint(item)
        if fp is None:
            continue
        by_fp.setdefault(fp, []).append(item)
    groups = [sorted(rows, key=lambda r: str(r["sk"])) for rows in by_fp.values() if len(rows) > 1]
    return sorted(groups, key=lambda g: str(g[0]["sk"]))


def validate_source(source: str) -> str | None:
    """Return an error string unless `source` is a registered RAW_TIMESERIES source."""
    cls = taxonomy.SOURCE_CLASS.get(source)
    if cls is None:
        return f"unknown source {source!r} — not in phase_taxonomy.SOURCE_CLASS"
    if cls != taxonomy.RAW_TIMESERIES:
        return (
            f"source {source!r} is {cls}, not raw_timeseries — dedup only operates on "
            "raw measured/logged facts (scoped partitions are the wipe's job; "
            "cross-phase partitions are never touched)"
        )
    return None


def query_date_rows(table, source: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    items: list[dict] = []
    kwargs = {"KeyConditionExpression": Key("pk").eq(f"USER#{USER}#SOURCE#{source}") & Key("sk").begins_with("DATE#")}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="raw-timeseries source name (e.g. eightsleep)")
    ap.add_argument("--apply", action="store_true", help="delete the duplicate rows (default: dry-run)")
    args = ap.parse_args()

    err = validate_source(args.source)
    if err:
        print(f"REFUSED: {err}")
        return 2

    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    items = query_date_rows(table, args.source)
    groups = find_duplicate_groups(items)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"dedup_source_records — source={args.source} — {len(items)} DATE# rows — mode: {mode}")

    deleted: list[str] = []
    lines = [f"dedup report — source={args.source} — mode={mode}", f"generated={datetime.now(timezone.utc).isoformat()}", ""]
    for group in groups:
        keeper, dups = group[0], group[1:]
        print(f"  duplicate session — keeping {keeper['sk']}, {'deleting' if args.apply else 'would delete'}:")
        lines.append(f"keep {keeper['sk']}")
        for dup in dups:
            print(f"    ✗ {dup['sk']}")
            lines.append(f"  delete {dup['sk']}")
            if args.apply:
                table.delete_item(Key={"pk": dup["pk"], "sk": dup["sk"]})
            deleted.append(str(dup["sk"]))
    if not groups:
        print("  no duplicate sessions found — nothing to do.")
        lines.append("no duplicate sessions found")

    report = REPO_ROOT / "docs" / "restart" / "_dedup_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n")
    verb = "deleted" if args.apply else "would delete"
    print(f"done. {verb} {len(deleted)} duplicate row(s). Report: {report.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
