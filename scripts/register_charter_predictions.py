#!/usr/bin/env python3
"""register_charter_predictions.py — the four dated predictions for the May-2027 charter build (#5089).

Dry-run by default; ``--apply`` writes (AWS write — the driver runs it from main, never a lane).

WHICH STORE, AND WHY
--------------------
Two PREDICTION# stores exist:

* ``COACH#{coach}_coach`` / ``PREDICTION#`` — the coach ledger. Rejected: it feeds coach hit-rates,
  Bayesian confidence and the PUBLIC ``/api/predictions``; these are the build's bets, not a coach's
  calls, and they are owner-only.
* ``USER#matthew#SOURCE#diary_claims`` / ``PREDICTION#{stated_date}#{slug}`` — the subject-claimed,
  ``visibility: private`` ledger (``privacy/diary_claims.py``). Chosen. The daily
  ``coach-prediction-evaluator`` scans it (``DIARY_CLAIMS_PK``), ``get_predictions`` lists it, no
  public surface reads it (``site_api_coach`` reads ``COACH#`` only), and ``coach_id`` is the empty
  string so no coach's calibration can absorb it.

``tool_evaluate_prediction`` cannot grade either store (it only edits legacy ``coach_thread`` arrays),
and the daily evaluator can resolve none of these four metrics (e1RM, stall count, a steps *fraction*,
a band count are not in ``measurable_metrics.METRIC_SOURCES``). So each row is written
``status: observation`` with ``evaluation.type: qualitative`` — the evaluator structurally skips it and
never retires it as ungradeable-pending — and carries a ``measurement`` block that names the function,
the window and the threshold, so the block retro (#5079) grades it MECHANICALLY and then flips status
to confirmed/refuted. The row shape is ``diary_claims.build_claim_record``'s, field for field.

IDEMPOTENT: the sort key is ``diary_claims.claim_sk(stated_date, claim)`` — deterministic — and the
write is conditional on the key not existing, so a re-run reports ``already_registered`` and never
duplicates. No clock is read except the ``registered_at`` stamp added at ``--apply`` time.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from privacy import diary_claims as dc  # noqa: E402

TABLE = "life-platform"
REGION = "us-west-2"
USER_ID = "matthew"

BASELINE_DATE = "2026-10-18"  # the baseline the build is graded against; also the stated (registration) date
EVALUATE_ON = "2026-12-06"  # the block ends here; #5079 grades on/after this date
HORIZON_DAYS = 49
SOURCE = "charter_build"
RECORD_TYPE = "charter_prediction"

# charter: training.rate_band_lb_wk (#5068 — W1 moves this read to the charter)
RATE_FLOOR_LB_WK, RATE_CEILING_LB_WK = 3.0, 3.5
# charter: training.steps_floor (#5068 — W1 moves this read to the charter)
STEPS_FLOOR = 12000

PREDICTIONS = [
    {
        "key": "anchor_e1rm_up",
        "claim": "By 2026-12-06 the estimated 1RM of every anchor lift is above its 2026-10-18 baseline.",
        "measurement": {
            "function": "coach.coach_event_triggers.session_bests (Hevy workouts; Epley e1rm_lb, best set per lift per session)",
            "tool": "get_exercise_history",
            "subject": "each anchor lift (charter anchor list; until #5068 lands: compound lifts with >= 3 sessions before the baseline)",
            "baseline": f"max e1rm_lb over sessions dated <= {BASELINE_DATE}",
            "current": f"max e1rm_lb over sessions dated {BASELINE_DATE} < d <= {EVALUATE_ON}",
            "condition": "gt",
            "threshold": "baseline (per lift)",
            "pass_rule": "confirmed iff every anchor lift's current > its baseline; refuted if any is not; inconclusive if a lift has no post-baseline session",
        },
    },
    {
        "key": "zero_accessory_stalls",
        "claim": "In the last two weeks of the block (2026-11-23 to 2026-12-06) no accessory movement stalls across any 3 consecutive sessions.",
        "measurement": {
            "function": "training.stall_detector.assess_stall over each accessory's sessions (training.accessory_strength_trend lists the accessories)",
            "tool": "get_exercise_history",
            "window": "2026-11-23..2026-12-06",
            "unit": "any 3 consecutive sessions of one accessory movement",
            "condition": "eq",
            "threshold": 0,
            "pass_rule": "confirmed iff no 3-session run in the window has verdict 'stall'; a movement with fewer than 3 sessions is not scored; no scorable movement = inconclusive",
        },
    },
    {
        "key": "steps_floor_90pct",
        "claim": f"The {STEPS_FLOOR:,}-step daily floor is met on at least 90% of days from 2026-10-19 to 2026-12-06.",
        "measurement": {
            "function": "common.metric_truth.steps_by_date (the per-day resolved steps; METRIC_TRUTH facet)",
            "tool": "get_daily_metrics (steps)",
            "window": "2026-10-19..2026-12-06",
            "per_day_comparator": "gte",
            "per_day_threshold": STEPS_FLOOR,
            "condition": "gte",
            "threshold": 0.90,
            "pass_rule": "share = days >= floor / days with a resolved reading; a day with no reading is missing, not a miss; confirmed iff share >= 0.90",
        },
    },
    {
        "key": "rate_in_band_4_of_6",
        "claim": f"The 7-day loss rate sits inside {RATE_FLOOR_LB_WK}-{RATE_CEILING_LB_WK} lb/wk on at least 4 of the 6 weekly reads ending 2026-11-01 .. 2026-12-06 (Sundays).",
        "measurement": {
            "function": "training.prescription_forecast.measured_week_rate (rate_lb_wk per week_end)",
            "tool": "get_weight_loss_progress",
            "window": "6 weekly reads, week_end 2026-11-01 .. 2026-12-06",
            "band_lb_wk": [RATE_FLOOR_LB_WK, RATE_CEILING_LB_WK],
            "condition": "gte",
            "threshold": 4,
            "pass_rule": "count weeks with measurable and floor <= rate_lb_wk <= ceiling; an unmeasurable week is missing, not a miss; confirmed iff count >= 4, refuted once the misses make 4 impossible",
        },
    },
]


def build_record(spec: dict, user_id: str = USER_ID) -> dict:
    """One row in ``diary_claims.build_claim_record``'s shape, minus the clock fields."""
    claim = spec["claim"]
    sk = dc.claim_sk(BASELINE_DATE, claim)
    claim_id = sk[len(dc.SK_PREFIX) :]
    m = spec["measurement"]
    return {
        "pk": dc.claims_pk(user_id),
        "sk": sk,
        "prediction_id": claim_id,
        "claim_id": claim_id,
        "record_type": RECORD_TYPE,
        "coach_id": "",
        "claimant": user_id,
        "source": SOURCE,
        "created_date": BASELINE_DATE,
        "stated_date": BASELINE_DATE,
        "claim_natural": claim,
        "criterion": m["pass_rule"],
        "metric": spec["key"],
        "subdomain": "training",
        # qualitative => the daily evaluator skips it (never retires it); #5079 grades via `measurement`.
        "evaluation": {
            "type": "qualitative",
            "metric": spec["key"],
            "evaluation_window_days": HORIZON_DAYS,
            "graded_by": "block_retro_5079",
        },
        "measurement": m,
        "horizon_days": HORIZON_DAYS,
        "grade_by": EVALUATE_ON,
        "evaluate_on": EVALUATE_ON,
        "confidence": dc.parse_confidence("medium"),
        "confidence_stated": "medium",
        "status": "observation",
        "visibility": "private",
        "schema_version": dc.SCHEMA_VERSION,
    }


def build_records() -> list[dict]:
    return [build_record(s) for s in PREDICTIONS]


def _decimalize(obj):
    from decimal import Decimal

    return json.loads(json.dumps(obj), parse_float=Decimal)


def apply_records(table, records: list[dict], now_iso: str) -> list[dict]:
    """Conditional put per row; returns [{prediction_id, result}]. Re-runs report already_registered."""
    out = []
    for rec in records:
        item = _decimalize({**rec, "registered_at": now_iso})
        try:
            table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)")
            out.append({"prediction_id": rec["prediction_id"], "result": "registered"})
        except Exception as e:  # noqa: BLE001
            if getattr(e, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            out.append({"prediction_id": rec["prediction_id"], "result": "already_registered"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write to DynamoDB (default: dry-run)")
    args = ap.parse_args(argv)
    records = build_records()
    if not args.apply:
        print(f"DRY RUN — would conditionally put {len(records)} rows into {TABLE} (registered_at is stamped at --apply):")
        for r in records:
            print(json.dumps({**r, "registered_at": "<stamped at apply>"}, indent=2, sort_keys=True))
        return 0
    from datetime import datetime, timezone

    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    for row in apply_records(table, records, datetime.now(timezone.utc).isoformat()):
        print(f"{row['result']}: {row['prediction_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
