#!/usr/bin/env python3
"""
backfill_insight_identity.py — give every stored insight a stable id and an age (#2678).

WHY. Of 33 rows in the USER#matthew#SOURCE#insights partition, 32 carried an empty
`insight_id` and an empty `date_saved` (2026-08-14 bug bash, data-integrity station).
Three writers share the partition: the mcp `save_insight` tool and the insight-email
parser both stamp the fields; `lambdas/content/insight_writer.py` — the high-volume
ledger writer behind the daily brief and the digests — stamped neither. Consequences:
`update_insight_outcome` cannot address those rows (no id), and staleness reads as
unknown for all of them (no timestamp), so an insight from March resurfaces exactly
like one written today.

The writer fix (same PR) stamps both fields on every new insight_writer row. This
script corrects the existing archive:

  insight_id — derived from the sk: everything after the "INSIGHT#" prefix. That is
      exactly the contract the mcp reader already uses (`sk = f"INSIGHT#{insight_id}"`),
      so a backfilled row becomes addressable by update_insight_outcome with no reader
      change.
  date_saved — best effort, first source that yields a real YYYY-MM-DD date:
      1. the row's own `date` attribute (insight_writer stamps it)
      2. the row's `created_at` (ISO timestamp — first 10 chars)
      3. the date embedded in the sk itself (INSIGHT#<date-or-ISO-ts>#... — first
         10 chars of the first segment)
      A row yielding none of these is reported as UNFIXABLE (a tombstone candidate
      for the operator) and is NOT written.

Idempotent: rows already carrying both fields non-empty are skipped, so a re-run
reports 0 to backfill. Writes only ever SET the two identity attributes — no other
attribute is touched, nothing is deleted. All written values are strings (no
float/Decimal concern).

Read-only by default (the restart_pipeline pattern). Apply with --apply:

  python3 deploy/backfill_insight_identity.py            # dry-run report
  python3 deploy/backfill_insight_identity.py --apply    # write the backfill
"""

import argparse
import os
import re
from datetime import datetime

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
INSIGHTS_PK = "USER#matthew#SOURCE#insights"
SK_PREFIX = "INSIGHT#"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(candidate):
    """The YYYY-MM-DD string if it is a real calendar date, else None."""
    if not isinstance(candidate, str):
        return None
    candidate = candidate.strip()[:10]
    if not _DATE_RE.match(candidate):
        return None
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        return None
    return candidate


def derive_date_saved(row):
    """Best-effort (date_saved, source) for a row, or (None, None).

    Precedence: the row's own `date` attribute, then `created_at`, then the
    date embedded in the sk's first segment. Every insight_writer row carries
    `date` + `created_at`; the sk fallback covers rows from any writer whose
    key embeds a date or ISO timestamp.
    """
    for attr in ("date", "created_at"):
        d = _valid_date(row.get(attr, ""))
        if d:
            return d, attr
    sk = row.get("sk", "")
    if sk.startswith(SK_PREFIX):
        first_segment = sk[len(SK_PREFIX) :].split("#", 1)[0]
        d = _valid_date(first_segment)
        if d:
            return d, "sk"
    return None, None


def classify_row(row):
    """Classify one insight row for the backfill.

    Returns (action, insight_id, date_saved, date_source) where action is one of:
      "complete"   — both fields already non-empty; nothing to do
      "backfill"   — write the derived insight_id + date_saved
      "unfixable"  — no date derivable from any source; report, never write
    """
    has_id = bool(str(row.get("insight_id", "") or "").strip())
    has_date = bool(_valid_date(row.get("date_saved", "")))
    if has_id and has_date:
        return "complete", None, None, None

    sk = row.get("sk", "")
    insight_id = str(row.get("insight_id", "") or "").strip() or sk[len(SK_PREFIX) :]
    date_saved = _valid_date(row.get("date_saved", ""))
    date_source = "existing"
    if not date_saved:
        date_saved, date_source = derive_date_saved(row)
    if not date_saved or not insight_id:
        return "unfixable", None, None, None
    return "backfill", insight_id, date_saved, date_source


def fetch_insight_rows(table):
    """All rows in the insights partition, following the pagination cursor."""
    from boto3.dynamodb.conditions import Key

    rows, cursor = [], None
    while True:
        kwargs = {"KeyConditionExpression": Key("pk").eq(INSIGHTS_PK) & Key("sk").begins_with(SK_PREFIX)}
        if cursor:
            kwargs["ExclusiveStartKey"] = cursor
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        cursor = resp.get("LastEvaluatedKey")
        if not cursor:
            return rows


def run(table, apply=False):
    """Classify (and with apply=True, write) the backfill. Returns the report dict."""
    rows = fetch_insight_rows(table)
    report = {"total": len(rows), "complete": 0, "backfill": [], "unfixable": [], "written": 0}

    for row in rows:
        action, insight_id, date_saved, date_source = classify_row(row)
        if action == "complete":
            report["complete"] += 1
        elif action == "backfill":
            report["backfill"].append({"sk": row["sk"], "insight_id": insight_id, "date_saved": date_saved, "date_source": date_source})
        else:
            report["unfixable"].append({"sk": row.get("sk", "?")})

    if apply:
        for fix in report["backfill"]:
            table.update_item(
                Key={"pk": INSIGHTS_PK, "sk": fix["sk"]},
                UpdateExpression="SET insight_id = :i, date_saved = :d",
                ExpressionAttributeValues={":i": fix["insight_id"], ":d": fix["date_saved"]},
            )
            report["written"] += 1

    return report


def main():
    ap = argparse.ArgumentParser(description="Backfill insight_id + date_saved on stored insights (#2678)")
    ap.add_argument("--apply", action="store_true", help="write the backfill (default: dry-run report)")
    args = ap.parse_args()

    import boto3

    table = boto3.resource("dynamodb", region_name="us-west-2").Table(TABLE_NAME)
    report = run(table, apply=args.apply)

    print(f"Scanned {report['total']} INSIGHT# rows in {TABLE_NAME} ({INSIGHTS_PK})\n")
    print(f"  complete (both fields already set): {report['complete']}")
    print(f"  needing backfill:                   {len(report['backfill'])}")
    print(f"  unfixable (no derivable date):      {len(report['unfixable'])}\n")

    for fix in report["backfill"]:
        print(f"  {fix['sk']}")
        print(f"     -> insight_id={fix['insight_id']}  date_saved={fix['date_saved']} (from {fix['date_source']})")
    for row in report["unfixable"]:
        print(f"  UNFIXABLE (tombstone candidate — not written): {row['sk']}")

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply to backfill.")
        return 0

    print(f"\nWrote {report['written']} row(s).")
    remaining = len(report["backfill"]) - report["written"] + len(report["unfixable"])
    print(f"Count after the run: {report['complete'] + report['written']} of {report['total']} rows carry both fields; {remaining} remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
