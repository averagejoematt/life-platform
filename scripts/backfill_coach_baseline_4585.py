#!/usr/bin/env python3
"""scripts/backfill_coach_baseline_4585.py — score the "nothing changes" rule on every
coach call graded BEFORE the grader started freezing it (#4585, epic #4580).

WHAT IT DOES (dry-run by default; nothing is written without --apply):

  For every coach's PREDICTION# partition it takes the record's own decided row-set —
  ``coach_record.decided_rows`` at the live ``EXPERIMENT_START_DATE``, the same rows the
  served count is counted from (this experiment only; no lifetime, no earlier start) —
  and, for each row that carries no ``baseline`` yet, computes the rule's verdict with the
  SAME functions the grader now runs at grading time:

    * a direction call      → ``coach_baseline.verdict`` on the slope the grade already
                              recorded in ``outcome_notes.actual_value`` (no data read);
    * a number / yes-no call → the metric's last reading before the filing day, read
                              through the evaluator's own phase-filtered source cache,
                              then ``coach_baseline.verdict`` against the graded reading;
    * a dispute-docket row  → the docket's frozen criterion off its ``RESOLVED#`` row,
                              then ``coach_baseline.docket_stamp``.

  With --apply each stamp is written by ``coach_baseline.write_stamp(only_if_absent=True)``
  — a conditional ``SET baseline`` that refuses a row already stamped, so a second run (or
  a run racing the daily grader) changes nothing: IDEMPOTENT. A row whose source read came
  back empty is left unstamped and listed; re-running later retries it.

RUN:  python3 scripts/backfill_coach_baseline_4585.py             # dry-run: the plan + the tally
      python3 scripts/backfill_coach_baseline_4585.py --apply     # writes the stamps
      python3 scripts/backfill_coach_baseline_4585.py --json out.json

Reads DynamoDB only in dry-run. --apply is a DynamoDB WRITE — an owner/driver act, never
a lane's — and is refused unless explicitly passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from boto3.dynamodb.conditions import Key  # noqa: E402
from coach import coach_baseline, coach_record  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from common.numeric import decimals_to_float  # noqa: E402

DOCKET_PK = "ENSEMBLE#docket"


def _evaluator():
    """The grader module — imported lazily so the pure helpers below stay testable."""
    from coach import coach_prediction_evaluator as ev

    return ev


def _coach_ids():
    from web.site_api_coach_ledger import _CALIB_COACH_ID_MAP

    return list(_CALIB_COACH_ID_MAP.values())  # every seat, retired included — their rows are real


def partition_rows(table, coach_id):
    """The coach's whole PREDICTION# partition, paginated, unprojected."""
    rows, kwargs = [], {"KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#")}
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return [decimals_to_float(r) for r in rows]
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def graded_actual(row):
    """The reading (or slope) the grader recorded, from ``outcome_notes``."""
    try:
        return (json.loads(row.get("outcome_notes") or "{}") or {}).get("actual_value")
    except (TypeError, ValueError):
        return None


def docket_for(table, row):
    """The RESOLVED# docket row a docket PREDICTION# row came from — matched on the
    resolution day, the pair and the subdomain the ``docket_ref`` OPEN# key names."""
    ref = str(row.get("docket_ref") or "")
    parts = ref.split("#")
    if len(parts) < 3 or not row.get("outcome_date"):
        return None
    pair, subdomain = parts[1], parts[2]
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(DOCKET_PK) & Key("sk").begins_with(f"RESOLVED#{str(row['outcome_date'])[:10]}#{pair}#")
    )
    for item in resp.get("Items") or []:
        item = decimals_to_float(item)
        if item.get("subdomain") == subdomain and isinstance(item.get("criterion"), dict):
            return item
    return None


def stamp_for(table, row, data_cache, io):
    """The ``baseline`` map for one already-graded row, or None when undecidable today."""
    get_source_data, extract_metric_series, noise_band = io
    if row.get("source") == "dispute_docket":
        docket = docket_for(table, row)
        if not docket:
            return coach_baseline.stamp(None, coach_baseline.INCOMPLETE_SPEC)
        holds = (docket.get("verdict") or {}).get("holds")
        if holds is None:
            return coach_baseline.stamp(None, coach_baseline.INCOMPLETE_SPEC)
        return coach_baseline.docket_stamp(docket, bool(holds), data_cache, get_source_data, extract_metric_series)
    spec = row.get("evaluation") or {}
    result = {"actual_value": graded_actual(row)}
    status = coach_record.graded_status(row)
    return coach_baseline.stamp_at_grading(row, spec, result, status, data_cache, get_source_data, extract_metric_series, noise_band)


def plan(table, coach_ids, io, genesis=EXPERIMENT_START_DATE):
    """[(coach_id, row, stamp)] for every decided row this experiment that has no stamp."""
    out, data_cache = [], {}
    for coach_id in coach_ids:
        for row in coach_record.decided_rows(partition_rows(table, coach_id), genesis=genesis):
            if isinstance(row.get("baseline"), dict):
                continue
            out.append((coach_id, row, stamp_for(table, row, data_cache, io)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="WRITE the stamps (a DynamoDB mutation) — default is a dry run")
    ap.add_argument("--json", help="also write the plan to this path")
    args = ap.parse_args(argv)

    ev = _evaluator()
    table = ev.table
    io = (ev._get_source_data, ev._extract_metric_series, ev.DIRECTIONAL_NOISE_THRESHOLD)
    rows = plan(table, _coach_ids(), io)

    stamped = [(c, r, s) for c, r, s in rows if s]
    waiting = [(c, r) for c, r, s in rows if not s]
    # The tally as it will read once the stamps land — over every decided row, stamped or not.
    preview = coach_baseline.comparison_block(
        [dict(r, baseline=s) if s else r for _c, r, s in rows]
        + [
            r
            for cid in _coach_ids()
            for r in coach_record.decided_rows(partition_rows(table, cid), genesis=EXPERIMENT_START_DATE)
            if isinstance(r.get("baseline"), dict)
        ]
    )
    print(
        f"genesis {EXPERIMENT_START_DATE} · {len(rows)} decided row(s) without a stamp · {len(stamped)} decidable now · {len(waiting)} waiting on a source read"
    )
    for key in coach_baseline.RECORDS:
        rec = preview["records"][key]
        if rec["graded"]:
            print(
                f"  {coach_baseline.RECORD_WORDS[key]:<28} graded {rec['graded']:>3} · scored {rec['scored']:>3} · coaches right {rec['coach_right_on_scored']:>3}"
                f" · rule right {rec['rule_right']:>3} · unscorable {rec['unscorable']:>3} {rec['unscorable_reasons'] or ''}"
            )
    print(f"  sentence once stamped: {preview['rule_sentence'] or preview['sentence']}")
    for c, r in waiting:
        print(f"  WAITING {c} {r.get('sk')}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([{"coach": c, "sk": r.get("sk"), "baseline": s} for c, r, s in rows], fh, indent=1, default=str)

    if not args.apply:
        print("dry run — nothing written. Re-run with --apply to write the stamps.")
        return 0
    written = sum(1 for c, r, s in stamped if coach_baseline.write_stamp(table, r["pk"], r["sk"], s, only_if_absent=True))
    print(f"APPLIED: {written} of {len(stamped)} stamp(s) written (a refused write = already stamped — idempotent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
