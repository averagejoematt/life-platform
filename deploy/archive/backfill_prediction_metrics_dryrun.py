"""
backfill_prediction_metrics_dryrun.py — One-shot survey + optional apply.

Walks every COACH#{coach_id}/PREDICTION# record with status in
{pending, confirming} and evaluation.type == "machine", classifies whether
its metric is already allowlisted, normalizable to an allowlisted key, or
unsalvageable (→ should be marked qualitative).

Default mode: dry-run (prints counts + samples, writes nothing).
Pass --apply to actually update records.

Why this exists: v7.16.0 fixed the forward path so NEW predictions store
a normalized metric or qualitative type. Historical predictions extracted
BEFORE v7.16.0 still hold prose metric_hints; they'll keep churning daily
inconclusive evaluations until their window elapses (14-30 days). This
script speeds the cleanup.
"""

import os
import sys
import argparse
from collections import Counter

# Reuse the same normalizer + allowlist as the live extractor — single source
# of truth (lambdas/coach_state_updater.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

from coach_state_updater import (  # noqa: E402
    MEASURABLE_METRICS,
    _normalize_metric_hint,
)

import boto3  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402

REGION = "us-west-2"
TABLE_NAME = "life-platform"

# Match COACH_IDS from coach_prediction_evaluator.py:59
COACH_IDS = [
    "sleep_coach", "nutrition_coach", "training_coach",
    "mind_coach", "physical_coach", "glucose_coach",
    "labs_coach", "explorer_coach",
]

EVALUABLE_STATUSES = {"pending", "confirming"}


def classify(item):
    """Return a tuple: (action, normalized_metric_or_none).

    action ∈ {already_ok, remap, qualitative, skip}
      - already_ok: machine + metric already in MEASURABLE_METRICS, leave alone
      - remap:      machine + metric is prose but normalizes — update metric in place
      - qualitative: machine + metric is prose and unsalvageable — switch to qualitative
      - skip:       not a candidate (non-machine, terminal status, etc.)
    """
    status = item.get("status", "")
    if status not in EVALUABLE_STATUSES:
        return ("skip", None)
    evaluation = item.get("evaluation") or {}
    eval_type = evaluation.get("type", "")
    if eval_type != "machine":
        return ("skip", None)
    metric = (evaluation.get("metric") or "")
    if isinstance(metric, str) and metric in MEASURABLE_METRICS:
        return ("already_ok", metric)
    normalized = _normalize_metric_hint(metric) if isinstance(metric, str) else None
    if normalized:
        return ("remap", normalized)
    return ("qualitative", None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually write updates. Default is dry-run.")
    parser.add_argument("--samples", type=int, default=5,
                        help="How many sample records to print per action bucket.")
    args = parser.parse_args()

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)

    totals = Counter()
    samples = {"already_ok": [], "remap": [], "qualitative": []}
    updates_planned = []  # list of (pk, sk, action, new_metric_or_none)

    for coach_id in COACH_IDS:
        pk = f"COACH#{coach_id}"
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("PREDICTION#"),
        }
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                action, new_metric = classify(item)
                totals[(coach_id, action)] += 1
                totals[("_total", action)] += 1
                if action in samples and len(samples[action]) < args.samples:
                    samples[action].append({
                        "coach_id": coach_id,
                        "sk": item.get("sk"),
                        "current_metric": (item.get("evaluation") or {}).get("metric"),
                        "claim_snippet": (item.get("claim_natural") or "")[:80],
                        "new_metric": new_metric,
                    })
                if action in ("remap", "qualitative"):
                    updates_planned.append((pk, item["sk"], action, new_metric))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    print("=" * 70)
    print("SURVEY (status ∈ {pending, confirming}, evaluation.type == machine)")
    print("=" * 70)
    for coach_id in COACH_IDS:
        line = f"{coach_id:18}"
        for action in ("already_ok", "remap", "qualitative"):
            line += f"  {action}={totals[(coach_id, action)]:4d}"
        print(line)
    print("-" * 70)
    line = f"{'TOTAL':18}"
    for action in ("already_ok", "remap", "qualitative"):
        line += f"  {action}={totals[('_total', action)]:4d}"
    print(line)

    print()
    for bucket, label in [("remap", "REMAP (prose → allowlisted key)"),
                          ("qualitative", "QUALITATIVE (prose → mark qualitative)")]:
        print(f"\n--- Samples: {label} ---")
        for s in samples[bucket]:
            print(f"  [{s['coach_id']}] {s['sk']}")
            print(f"    claim:   {s['claim_snippet']!r}")
            print(f"    metric:  {s['current_metric']!r}")
            if s["new_metric"]:
                print(f"    → new:   {s['new_metric']!r}")
            print()

    if not args.apply:
        print(f"\nDRY-RUN. {len(updates_planned)} updates would be applied. "
              "Re-run with --apply to commit.")
        return

    # Apply phase
    print(f"\nAPPLYING {len(updates_planned)} updates...")
    applied = 0
    failed = 0
    for pk, sk, action, new_metric in updates_planned:
        try:
            if action == "remap":
                table.update_item(
                    Key={"pk": pk, "sk": sk},
                    UpdateExpression="SET evaluation.#m = :m, backfilled_at = :t, backfill_action = :a",
                    ExpressionAttributeNames={"#m": "metric"},
                    ExpressionAttributeValues={
                        ":m": new_metric,
                        ":t": "2026-05-17",
                        ":a": "remap_to_measurable",
                    },
                )
            elif action == "qualitative":
                table.update_item(
                    Key={"pk": pk, "sk": sk},
                    UpdateExpression="SET evaluation.#t = :q, backfilled_at = :ts, backfill_action = :a",
                    ExpressionAttributeNames={"#t": "type"},
                    ExpressionAttributeValues={
                        ":q": "qualitative",
                        ":ts": "2026-05-17",
                        ":a": "demote_to_qualitative",
                    },
                )
            applied += 1
        except Exception as e:
            print(f"  FAIL {pk} / {sk}: {e}")
            failed += 1
    print(f"\nDone. applied={applied} failed={failed}")


if __name__ == "__main__":
    main()
