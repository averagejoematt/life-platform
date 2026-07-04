"""
scenario_explorer_lambda.py — conditional what-followed distributions (#550, ADR-105).

The correlation engine finds associations; readers could never interrogate them.
This lambda precomputes, nightly, the distribution of what historically FOLLOWED
days matching each of a curated lever set ("slept 7.5h+", "zone-2 minutes",
"logged every meal", …): for each (lever, outcome) cell — next-day recovery,
mood, energy, sleep, HRV — the matched-day distribution summary, the comparison
against non-matching days, and a moving-block-bootstrap 95% CI on the difference
(stats_core; deterministic, seeded).

The anti-causal framing is the feature and ships in the payload: this is what
*followed*, never what it *causes*. Honesty gates:
  - a cell renders only when the matched arm's EFFECTIVE sample size (AR(1)-
    corrected, stats_core.effective_sample_size) clears MIN_EFFECTIVE_N — thin
    cells are hidden, not padded;
  - every surviving cell carries its raw n and n_eff.

Day-rows are the hypothesis engine's build_data_narrative — one assembly, not a
parallel copy (ADR-105). Zero AI calls. Output: one summary row per day at
pk USER#matthew#SOURCE#scenarios / sk DATE#{today} (EXPERIMENT_SCOPED), served
read-only by /api/scenarios.

Runs nightly at 12:10 UTC (~5:10 AM PT) — after the overnight ingest, well before
anyone reads the page.
"""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import stats_core

try:
    from platform_logger import get_logger

    logger = get_logger("scenario-explorer")
except ImportError:
    import logging

    logger = logging.getLogger("scenario-explorer")
    logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
SCENARIOS_PK = f"USER#{USER_ID}#SOURCE#scenarios"

LOOKBACK_DAYS = 180
MIN_EFFECTIVE_N = 8  # matched-arm effective n below this → the cell is hidden
MIN_COMPARISON_N = 8

# The curated lever set. Each lever needs `field` present on the day-row; `test`
# decides membership. A lever is a day-description, not an intervention — the
# payload's framing line says so explicitly.
LEVERS = [
    {"slug": "sleep_7p5", "label": "Slept 7.5h or more", "field": "total_sleep_hrs", "test": lambda v: v >= 7.5},
    {"slug": "sleep_short", "label": "Slept under 6.5h", "field": "total_sleep_hrs", "test": lambda v: v < 6.5},
    {"slug": "workout_day", "label": "Trained that day", "field": "workout", "test": lambda v: bool(v)},
    {"slug": "zone2_20", "label": "20+ zone-2 minutes", "field": "zone2_min", "test": lambda v: v >= 20},
    {"slug": "steps_10k", "label": "10k+ steps", "field": "steps", "test": lambda v: v >= 10000},
    {"slug": "protein_150", "label": "150g+ protein", "field": "protein_g", "test": lambda v: v >= 150},
    {"slug": "meals_logged", "label": "Logged every meal", "field": "calories", "test": lambda v: v > 0},
    {"slug": "high_recovery", "label": "Woke at 66%+ recovery", "field": "recovery", "test": lambda v: v >= 66},
]

# What we look at on the FOLLOWING day.
OUTCOMES = [
    {"metric": "recovery", "label": "Recovery", "unit": "%"},
    {"metric": "total_sleep_hrs", "label": "Sleep", "unit": "h"},
    {"metric": "hrv", "label": "HRV", "unit": "ms"},
    {"metric": "mood", "label": "Mood", "unit": "/10"},
    {"metric": "energy", "label": "Energy", "unit": "/10"},
]

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


def _to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def _quantile(sorted_vals, q):
    """Linear-interpolation quantile over a pre-sorted list."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def split_next_day_values(rows_by_date, lever, outcome_metric):
    """(matched, comparison) lists of the outcome on the day AFTER lever-True /
    lever-False days. A day counts only when the lever field is present that day
    AND the outcome exists the next day — absence is absence, never imputed."""
    from datetime import timedelta

    matched, comparison = [], []
    for date_str, row in rows_by_date.items():
        v = row.get(lever["field"])
        if v is None:
            continue
        try:
            is_match = bool(lever["test"](float(v) if not isinstance(v, bool) else v))
        except (TypeError, ValueError):
            continue
        next_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        nxt = rows_by_date.get(next_date, {}).get(outcome_metric)
        if nxt is None:
            continue
        (matched if is_match else comparison).append(float(nxt))
    return matched, comparison


def build_cell(matched, comparison):
    """One (lever, outcome) cell, or None when the effective n is too thin to be
    honest. Deterministic: seeded bootstrap, AR(1)-corrected n_eff."""
    if len(matched) < MIN_EFFECTIVE_N or len(comparison) < MIN_COMPARISON_N:
        return None
    n_eff = stats_core.effective_sample_size(matched)
    if n_eff < MIN_EFFECTIVE_N:
        return None
    sm = sorted(matched)
    diff_ci = stats_core.bootstrap_mean_diff_ci(comparison, matched)
    cell = {
        "n": len(matched),
        "n_eff": round(n_eff, 1),
        "n_comparison": len(comparison),
        "median": round(_quantile(sm, 0.5), 1),
        "p25": round(_quantile(sm, 0.25), 1),
        "p75": round(_quantile(sm, 0.75), 1),
        "mean": round(sum(matched) / len(matched), 1),
        "comparison_mean": round(sum(comparison) / len(comparison), 1),
        "diff": round(sum(matched) / len(matched) - sum(comparison) / len(comparison), 2),
    }
    if diff_ci:
        cell["diff_ci95"] = [round(diff_ci[0], 2), round(diff_ci[1], 2)]
        cell["ci_excludes_zero"] = bool(diff_ci[0] > 0 or diff_ci[1] < 0)
    return cell


def build_payload(rows_by_date, today_str):
    levers_out = []
    hidden = 0
    for lever in LEVERS:
        n_matched_days = sum(
            1 for r in rows_by_date.values() if r.get(lever["field"]) is not None and _safe_test(lever, r.get(lever["field"]))
        )
        outcomes = {}
        for oc in OUTCOMES:
            matched, comparison = split_next_day_values(rows_by_date, lever, oc["metric"])
            cell = build_cell(matched, comparison)
            if cell is None:
                hidden += 1
                continue
            cell["label"] = oc["label"]
            cell["unit"] = oc["unit"]
            outcomes[oc["metric"]] = cell
        levers_out.append(
            {
                "slug": lever["slug"],
                "label": lever["label"],
                "n_matched_days": n_matched_days,
                "outcomes": outcomes,
            }
        )
    return {
        "pk": SCENARIOS_PK,
        "sk": f"DATE#{today_str}",
        "record_type": "scenario_summary",
        "date": today_str,
        "window_days": LOOKBACK_DAYS,
        "levers": levers_out,
        "cells_hidden_thin": hidden,
        "min_effective_n": MIN_EFFECTIVE_N,
        "framing": "distributions of what FOLLOWED similar days — correlative by design, never causal",
    }


def _safe_test(lever, v):
    try:
        return bool(lever["test"](float(v) if not isinstance(v, bool) else v))
    except (TypeError, ValueError):
        return False


def lambda_handler(event: dict, context) -> dict:
    try:
        # One day-row assembly for the whole platform (ADR-105): the hypothesis
        # engine's. Same asset bundle, so a plain sibling import.
        import hypothesis_engine_lambda as eng

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data = eng.gather_data(days=LOOKBACK_DAYS)
        rows = eng.build_data_narrative(data)
        rows_by_date = {r["date"]: r for r in rows if r.get("date")}

        payload = build_payload(rows_by_date, today_str)
        try:
            from compute_metadata import tag_record

            payload = tag_record(payload, source_id="scenarios")
        except ImportError:
            pass
        table.put_item(Item=_to_decimal({k: v for k, v in payload.items() if v is not None}))

        cells = sum(len(lv["outcomes"]) for lv in payload["levers"])
        result = {
            "date": today_str,
            "days": len(rows_by_date),
            "levers": len(payload["levers"]),
            "cells": cells,
            "cells_hidden_thin": payload["cells_hidden_thin"],
        }
        logger.info(json.dumps(result))
        return result
    except Exception as e:
        logger.error(f"Handler failed: {e}")
        raise
