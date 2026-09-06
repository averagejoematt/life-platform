#!/usr/bin/env python3
"""scripts/regrade_level_claims_3551.py — correct, ON THE RECORD, every PREDICTION# row
whose claim is a numeric LEVEL ("Recovery score will be approximately 53.5%") but whose
stored spec is `directional` (#3551).

WHAT IT DOES (dry-run by default; nothing is written without --apply):

  * PENDING rows (live, evaluable): the spec is RE-SPECIFIED as a `point` spec — the
    target parsed from the claim, the tolerance derived from the metric's trailing
    30-day personal SD as of the row's created_date (ADR-105 rule 4), the target date
    = created + window ('tomorrow' → 1 day). The prior spec is kept under
    `respecified_from`, with `respecified_at` and the reason.
  * DECIDED rows (confirmed / refuted): the verdict is RE-GRADED as the level claim
    it was — the reading on the target date against target ± tolerance — using the
    evaluator's own `_evaluate_point`. The prior verdict (status + outcome_notes) is
    kept under `verdict_correction.prior`, and the new outcome_notes carry a
    `verdict_correction` block so the correction is visible wherever outcome_notes
    render (the coach scorecard, /api/predictions). A row whose re-grade is
    inconclusive (no reading on the target date) is ANNOTATED — status unchanged,
    the correction block records that the original verdict graded a different claim
    — never silently left as a confirmed up-trend.
  * Tombstoned PENDING rows (archived cycles) are listed and skipped: the evaluator
    never grades them and they never enter the ledger.

RUN:  python3 scripts/regrade_level_claims_3551.py            # dry-run: prints the plan
      python3 scripts/regrade_level_claims_3551.py --apply    # writes the corrections
      python3 scripts/regrade_level_claims_3551.py --coach explorer_coach --json plan.json

Reads DynamoDB only in dry-run. Read-only AWS is sanctioned for a lane; --apply is an
owner/driver act (this is a DDB mutation) and is refused unless explicitly passed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import boto3  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402
from coach import (
    coach_prediction_evaluator as ev,  # noqa: E402
    prediction_emission as pe,  # noqa: E402
)
from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402
from common.numeric import decimals_to_float  # noqa: E402
from experiment.measurable_metrics import METRIC_SOURCES  # noqa: E402

USER_ID = os.environ["USER_ID"]
TABLE = os.environ["TABLE_NAME"]
TRAILING_DAYS = 30
CORRECTION_REASON = (
    "#3551: the claim is a numeric level; it was stored as a directional spec ('recover' in DIR_UP_WORDS "
    "matched the metric name) and graded as a 14-day trend sign. Re-graded as the level claim it was."
)


def _table():
    return boto3.resource("dynamodb", region_name=os.environ["AWS_DEFAULT_REGION"]).Table(TABLE)


def _query_all(table, **kwargs):
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _source_rows(table, metric, start, end, cache):
    base = metric
    for suffix in ("_7day_avg", "_14day_avg", "_30day_avg"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    source = METRIC_SOURCES.get(base)
    if not source:
        return base, []
    key = (source, start, end)
    if key not in cache:
        rows = _query_all(
            table,
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#{source}") & Key("sk").between("DATE#" + start, "DATE#" + end),
        )
        cache[key] = sorted((decimals_to_float(r) for r in rows), key=lambda r: str(r.get("sk", "")))
    return base, cache[key]


def _trailing_values(table, metric, as_of, cache):
    start = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=TRAILING_DAYS)).strftime("%Y-%m-%d")
    base, rows = _source_rows(table, metric, start, as_of, cache)
    out = []
    for r in rows:
        v = r.get(base)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isnan(f):
            out.append(f)
    return out


def _point_cache_for(table, metric, target_date, cache):
    """A data_cache shaped the way coach_prediction_evaluator._metric_value_on reads
    it, anchored on the target date so the reading ON that date is in range."""
    base = metric
    for suffix in ("_7day_avg", "_14day_avg", "_30day_avg"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    source = METRIC_SOURCES.get(base)
    start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=ev.POINT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    _, rows = _source_rows(table, metric, start, target_date, cache)
    return {f"{source}:{ev.POINT_LOOKBACK_DAYS}": rows}


def plan(table, coaches, include_archived_pending=False):
    cache = {}
    out = []
    for coach_id in coaches:
        rows = _query_all(table, KeyConditionExpression=Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#"))
        for raw in rows:
            rec = decimals_to_float(raw)
            spec = rec.get("evaluation") or {}
            if spec.get("type") != "directional":
                continue
            metric = spec.get("metric")
            claim = rec.get("claim_natural") or ""
            shape = pe.classify_claim_shape(claim, metric)
            if shape["shape"] != "level":
                continue
            status = rec.get("status")
            tombstoned = bool(rec.get("tombstone"))
            created = rec.get("created_date") or ""
            timeframe = shape.get("window_hint") or ""
            window = pe.prediction_window_days(timeframe) if timeframe else int(spec.get("evaluation_window_days") or 14)
            entry = {
                "pk": rec["pk"],
                "sk": rec["sk"],
                "coach": coach_id,
                "status": status,
                "tombstoned": tombstoned,
                "created_date": created,
                "claim": claim,
                "metric": metric,
                "current_spec": {k: spec.get(k) for k in ("type", "condition", "evaluation_window_days")},
                "target": shape["target"],
                "window_days": window,
            }
            if status in ("pending", "confirming") and tombstoned and not include_archived_pending:
                entry["action"] = "skip:archived-pending"
                out.append(entry)
                continue
            if not created or not metric:
                entry["action"] = "skip:unresolvable"
                out.append(entry)
                continue
            tol = pe.point_tolerance_from_series(_trailing_values(table, metric, created, cache), lookback_days=TRAILING_DAYS)
            if not tol:
                entry["action"] = "annotate:no-tolerance"
                entry["note"] = "no personal SD derivable as of created_date — cannot be re-specified as a point spec"
                out.append(entry)
                continue
            tolerance, rule, _n = tol
            new_spec = pe.build_point_eval_spec(metric, shape["target"], tolerance, rule, window, created)
            entry["new_spec"] = new_spec
            if status in ("pending", "confirming"):
                entry["action"] = "respecify"
            elif status in ("confirmed", "refuted"):
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                result = ev._evaluate_point(rec, new_spec, _point_cache_for(table, metric, new_spec["target_date"], cache), today)
                entry["regrade"] = result
                entry["action"] = "regrade" if result and result["status"] in ("confirmed", "refuted") else "annotate:inconclusive"
                entry["prior_outcome_notes"] = rec.get("outcome_notes")
            else:
                entry["action"] = f"skip:{status}"
            out.append(entry)
    return out


def apply(table, entries):
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for e in entries:
        action = e["action"]
        key = {"pk": e["pk"], "sk": e["sk"]}
        if action == "respecify":
            table.update_item(
                Key=key,
                UpdateExpression="SET evaluation = :spec, respecified_from = :old, respecified_at = :at, respecified_reason = :why",
                ExpressionAttributeValues={
                    ":spec": _decimalize(e["new_spec"]),
                    ":old": _decimalize(e["current_spec"]),
                    ":at": now,
                    ":why": CORRECTION_REASON,
                },
            )
            written += 1
        elif action in ("regrade", "annotate:inconclusive"):
            prior = {"status": e["status"], "outcome_notes": e.get("prior_outcome_notes"), "corrected_at": now, "reason": CORRECTION_REASON}
            result = e.get("regrade") or {}
            new_status = result["status"] if action == "regrade" else e["status"]
            notes = {
                "actual_value": result.get("actual_value"),
                "reason": result.get("reason", ""),
                "beats_null": result.get("beats_null", False),
                "bayesian_update": None,
                "algo_version": ev.ALGO_VERSION,
                "verdict_correction": {
                    "issue": "#3551",
                    "prior_status": e["status"],
                    "prior_reason": _prior_reason(e.get("prior_outcome_notes")),
                    "corrected_at": now,
                    "regraded_as": "point",
                    "correction": (
                        f"previously {e['status'].upper()} as a 14-day trend; re-graded as a level claim → {new_status.upper()}"
                        if action == "regrade"
                        else f"previously {e['status'].upper()} as a 14-day trend of a claim that was a level; no reading on the target date, so the verdict cannot be re-derived and stands ANNOTATED, not endorsed"
                    ),
                },
            }
            table.update_item(
                Key=key,
                UpdateExpression="SET #s = :status, evaluation = :spec, outcome_notes = :notes, verdict_correction = :vc",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": new_status,
                    ":spec": _decimalize(e["new_spec"]),
                    ":notes": json.dumps(notes),
                    ":vc": _decimalize({"prior": prior, "regraded_as": "point", "new_status": new_status}),
                },
            )
            written += 1
    return written


def _prior_reason(notes):
    try:
        return (json.loads(notes or "{}") or {}).get("reason")
    except (TypeError, ValueError):
        return notes


def _decimalize(obj):
    from decimal import Decimal

    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _decimalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimalize(v) for v in obj]
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the corrections (a DDB mutation — owner/driver act)")
    ap.add_argument("--coach", action="append", help="restrict to one coach id (repeatable)")
    ap.add_argument(
        "--include-archived-pending", action="store_true", help="also re-specify tombstoned pending rows (default: list + skip)"
    )
    ap.add_argument("--json", help="write the plan here as JSON")
    args = ap.parse_args()

    table = _table()
    coaches = args.coach or list(OPERATIONAL_COACH_IDS)
    entries = plan(table, coaches, include_archived_pending=args.include_archived_pending)
    by_action = {}
    for e in entries:
        by_action.setdefault(e["action"], []).append(e)
    print(f"#3551 level-claims-stored-as-directional: {len(entries)} row(s) across {len(coaches)} coach partition(s)")
    for action, rows in sorted(by_action.items()):
        print(f"  {action:24} n={len(rows)}")
    for e in entries:
        if e["action"].startswith("skip:archived"):
            continue
        line = f"- [{e['action']}] {e['coach']} {e['sk']} status={e['status']} created={e['created_date']} metric={e['metric']}"
        line += f"\n    claim: {e['claim']!r}"
        if e.get("new_spec"):
            ns = e["new_spec"]
            line += f"\n    point: {ns['threshold']} ± {ns['tolerance']} on {ns['target_date']} ({ns['tolerance_rule']})"
        if e.get("regrade"):
            line += f"\n    regrade: {e['regrade']['status']} — {e['regrade']['reason']}"
        if e.get("note"):
            line += f"\n    note: {e['note']}"
        print(line)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, default=str)
        print(f"plan written to {args.json}")
    if args.apply:
        n = apply(table, entries)
        print(f"APPLIED {n} correction(s)")
    else:
        print("dry-run — nothing written (pass --apply to write the corrections)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
