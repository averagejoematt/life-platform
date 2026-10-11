#!/usr/bin/env python3
"""scripts/regrade_count_claims_4541.py — list, and on --apply correct ON THE RECORD, every
PREDICTION# row whose sentence is a COUNT claim ("at least K of N days >= X") (#4541).

Until #4541 such a claim was graded by whatever spec it was stored with — a `directional`
spec by EWMA slope, a `machine` spec by the latest reading — so a count of 3 of 7 could be
CONFIRMED. This sweep re-grades every count-shaped row with the evaluator's own count rule
(`coach.prediction_count_grader.grade`, through `coach_prediction_evaluator`'s own source
read) and prints, per row: call id, coach, sentence, old verdict, the day-by-day values, the
count and the new verdict; then each affected coach's record (`coach.coach_record`) before
and after.

WHAT --apply WRITES (dry-run by default; nothing is written without it):

  * a DECIDED row (confirmed / refuted) whose new verdict differs: status + outcome become
    the count verdict; outcome_notes carry a `verdict_correction` block (issue, prior status,
    prior reason, corrected_at) so the correction shows wherever the notes render; the prior
    verdict is kept under `verdict_correction` on the row. A row already carrying a #4541
    correction is skipped (idempotent).
  * a DECIDED row whose re-grade is UNGRADEABLE or inconclusive is ANNOTATED: status stays,
    the correction block records that the stored verdict graded the sentence by another rule.
  * pending / expired / inconclusive rows are listed only — the deployed evaluator grades
    the pending ones; nothing else here is a verdict.

NOT written, even with --apply (named so nobody assumes otherwise): the coach's
CONFIDENCE#{subdomain} Beta counts (a confirmed->refuted correction would move one unit of
alpha to beta) and the LEARNING# row the original grade wrote. Both are flagged per row.

RUN:  python3 scripts/regrade_count_claims_4541.py            # dry-run: prints the plan
      python3 scripts/regrade_count_claims_4541.py --apply    # owner/driver act (DDB mutation)

Reads DynamoDB only in dry-run. Read-only AWS is sanctioned for a lane; --apply is refused
unless explicitly passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from boto3.dynamodb.conditions import Key  # noqa: E402
from coach import (
    coach_prediction_evaluator as ev,  # noqa: E402
    coach_record,  # noqa: E402
    prediction_count_grader as cg,  # noqa: E402
)
from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from common.numeric import decimals_to_float  # noqa: E402

ISSUE = "#4541"
DECIDED = ("confirmed", "refuted")


def _query_all(table, **kwargs):
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _partition_rows(table, pk):
    return [decimals_to_float(r) for r in _query_all(table, KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("PREDICTION#"))]


def _old_reason(row):
    try:
        return (json.loads(row.get("outcome_notes") or "{}") or {}).get("reason")
    except (TypeError, ValueError):
        return row.get("outcome_notes")


def _already_corrected(row):
    vc = row.get("verdict_correction")
    return isinstance(vc, dict) and vc.get("issue") == ISSUE


def plan(table, partitions, today):
    data_cache: dict = {}
    entries, rows_by_pk = [], {}
    for pk in partitions:
        rows = _partition_rows(table, pk)
        rows_by_pk[pk] = rows
        for row in rows:
            spec = row.get("evaluation") or {}
            if not cg.is_count_shaped(row.get("claim_natural")) or spec.get("type", "machine") not in cg.COUNT_GRADED_TYPES:
                continue
            result = cg.grade(row, spec, data_cache, today, ev._get_source_data, ev._extract_metric_series) or {}
            status = row.get("status")
            new = result.get("status")
            ungraded = str(result.get("reason", "")).startswith(cg.NOT_GRADED_PREFIX)
            if row.get("tombstone"):
                action = "skip:tombstoned"
            elif _already_corrected(row):
                action = "skip:already-corrected"
            elif status not in DECIDED:
                action = f"list:{status}"
            elif ungraded or new not in DECIDED:
                action = "annotate:not-gradeable-by-count"
            elif new == status:
                action = "unchanged"
            else:
                action = "regrade"
            entries.append(
                {
                    "pk": row["pk"],
                    "sk": row["sk"],
                    "call_id": row.get("prediction_id") or row["sk"].replace("PREDICTION#", ""),
                    "coach": row.get("coach_id") or "(subject)",
                    "subdomain": row.get("subdomain"),
                    "sentence": row.get("claim_natural"),
                    "spec_type": spec.get("type"),
                    "old_status": status,
                    "old_reason": _old_reason(row),
                    "old_bayesian_update": (
                        (json.loads(row.get("outcome_notes") or "{}") or {}).get("bayesian_update") if row.get("outcome_notes") else None
                    ),
                    "new_status": new,
                    "count": result.get("actual_value"),
                    "count_claim": result.get("count_claim"),
                    "day_values": result.get("day_values"),
                    "new_reason": result.get("reason"),
                    "action": action,
                }
            )
    return entries, rows_by_pk


def record_impact(entries, rows_by_pk):
    """{coach: {cycle: (before, after), career: (before, after)}} for coaches a regrade touches."""
    changed = {(e["pk"], e["sk"]): e["new_status"] for e in entries if e["action"] == "regrade"}
    out = {}
    for pk, rows in rows_by_pk.items():
        if not any(k[0] == pk for k in changed):
            continue
        after_rows = [dict(r, status=changed[(pk, r["sk"])]) if (pk, r["sk"]) in changed else r for r in rows]
        out[pk] = {
            "cycle": (
                coach_record.record_from_rows(rows, genesis=EXPERIMENT_START_DATE),
                coach_record.record_from_rows(after_rows, genesis=EXPERIMENT_START_DATE),
            ),
            "career": (
                coach_record.record_from_rows(rows, genesis=None, career=True),
                coach_record.record_from_rows(after_rows, genesis=None, career=True),
            ),
        }
    return out


def apply(table, entries):
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for e in entries:
        if e["action"] not in ("regrade", "annotate:not-gradeable-by-count"):
            continue
        regrade = e["action"] == "regrade"
        new_status = e["new_status"] if regrade else e["old_status"]
        correction = {
            "issue": ISSUE,
            "prior_status": e["old_status"],
            "prior_reason": e["old_reason"],
            "corrected_at": now,
            "regraded_as": "count",
            "correction": (
                f"previously {e['old_status'].upper()} by another rule; the sentence is a count claim, counted → {new_status.upper()}"
                if regrade
                else f"previously {e['old_status'].upper()} by another rule; the sentence is a count claim the count rule cannot "
                "grade, so the verdict stands ANNOTATED, not endorsed"
            ),
        }
        notes = {
            "actual_value": e["count"],
            "reason": e["new_reason"] or "",
            "beats_null": regrade and new_status == "confirmed",
            "bayesian_update": None,
            "algo_version": ev.ALGO_VERSION,
            "verdict_correction": correction,
        }
        if regrade:
            notes["graded_as"] = "count"  # the readers' marker (prediction_grading.build_outcome_notes)
        table.update_item(
            Key={"pk": e["pk"], "sk": e["sk"]},
            UpdateExpression="SET #s = :status, outcome = :status, outcome_notes = :notes, verdict_correction = :vc",
            ConditionExpression="attribute_not_exists(verdict_correction) OR verdict_correction.issue <> :issue",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": new_status, ":notes": json.dumps(notes), ":vc": correction, ":issue": ISSUE},
        )
        written += 1
    return written


def _fmt_days(day_values):
    if not day_values:
        return "-"
    return ", ".join(f"{d[5:]} {'—' if v is None else f'{v:g}'}" for d, v in day_values)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the corrections (a DDB mutation — owner/driver act)")
    ap.add_argument("--json", help="write the plan here as JSON")
    ap.add_argument("--all", action="store_true", help="print every count-shaped row, not only decided ones")
    args = ap.parse_args()

    today = ev.pacific_today()
    partitions = [f"COACH#{c}" for c in OPERATIONAL_COACH_IDS] + [ev.DIARY_CLAIMS_PK]
    entries, rows_by_pk = plan(ev.table, partitions, today)

    by_action: dict = {}
    for e in entries:
        by_action.setdefault(e["action"], []).append(e)
    print(f"{ISSUE} count-shaped PREDICTION# rows: {len(entries)} across {len(partitions)} partition(s), graded as of {today}")
    for action, rows in sorted(by_action.items()):
        print(f"  {action:34} n={len(rows)}")
    print()
    print("| call id | coach | sentence | old verdict | day-by-day values | count | new verdict | action |")
    print("|---|---|---|---|---|---|---|---|")
    for e in entries:
        if not args.all and e["old_status"] not in DECIDED:
            continue
        cc = e.get("count_claim") or {}
        bound = f"{cc.get('k')} of {cc.get('n')} needed" if cc else ""
        print(
            f"| `{e['call_id']}` | {e['coach']} | {e['sentence']} | {e['old_status']} ({e['old_reason']}) | {_fmt_days(e['day_values'])} "
            f"| {e['count'] if e['count'] is not None else '—'} {('(' + bound + ')') if bound else ''} "
            f"| {e['new_status']}{'' if e['new_status'] in DECIDED else ' — ' + str(e['new_reason'])} | {e['action']} |"
        )
    impact = record_impact(entries, rows_by_pk)
    print()
    for pk, rec in impact.items():
        for scope, (before, after) in rec.items():
            print(
                f"{pk} {scope} record: {before['confirmed']} of {before['n']} right -> {after['confirmed']} of {after['n']} right"
                f" (refuted {before['refuted']} -> {after['refuted']})"
            )
    for e in by_action.get("regrade", []):
        if e["old_bayesian_update"]:
            print(
                f"NOT WRITTEN by this script: {e['coach']} CONFIDENCE#{e['subdomain']} took '{e['old_bayesian_update']}' from the "
                f"old grade of {e['call_id']}; the corrected grade is '{'success' if e['new_status'] == 'confirmed' else 'failure'}'"
            )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, default=str)
        print(f"plan written to {args.json}")
    if args.apply:
        print(f"APPLIED {apply(ev.table, entries)} correction(s)")
    else:
        print("dry-run — nothing written (pass --apply to write the corrections)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
