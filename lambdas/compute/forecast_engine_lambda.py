"""
forecast_engine_lambda.py — deterministic next-day / next-7-day expectations (#541, ADR-105).

The platform classified state (adaptive mode) and extrapolated one trend (weight
projection) but never said what it EXPECTS to happen next. This lambda closes that:
every morning it fits simple exponential smoothing (stats_core.ewma_forecast —
stdlib, deterministic, seeded-free math) to the recent history of recovery, sleep
duration, and weight, and writes h=1 and h=7 expectations with 80% intervals.

Honesty is the design:
  - Every forecast is FROZEN at issue time (point, interval, model id) and
    auto-resolves when its target date's actual arrives — resolution writes one
    row to the CROSS_PHASE SOURCE#calibration ledger (record_type
    "forecast_resolution"), so the platform's forecasting skill is a graded,
    reset-surviving public record.
  - The coverage stat ("did the 80% interval cover 80%?") is computed from the
    resolved rows and published with every summary — no resolutions, no claim.
  - Framing is strictly "expectation from observed patterns" — never causal.

Record layout (pk USER#matthew#SOURCE#forecast, EXPERIMENT_SCOPED):
  sk FORECAST#{target_date}#{metric}#h{h}   — one frozen forecast, resolved in place
  sk DATE#{issued_date}                     — daily summary (today's forecasts +
                                              today's resolutions + running coverage)
Resolutions additionally write pk USER#matthew#SOURCE#calibration,
  sk CALIB#{resolved_date}#forecast-{metric}-h{h}-{target_date}.

Runs at 16:50 UTC (9:50 AM PT) — after daily-metrics (16:40), before the 17:00
daily-brief lane, so coaches narrate today's expectation, not yesterday's.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
import stats_core
from phase_filter import with_phase_filter  # ADR-058: default-deny pilot data

try:
    from platform_logger import get_logger

    logger = get_logger("forecast-engine")
except ImportError:
    import logging

    logger = logging.getLogger("forecast-engine")
    logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
FORECAST_PK = f"{USER_PREFIX}forecast"
CALIBRATION_PK = f"{USER_PREFIX}calibration"

MODEL_ID = "ewma-v1"
CONFIDENCE = 0.80
HORIZONS = (1, 7)
HISTORY_DAYS = 60
RESOLVE_LOOKBACK_DAYS = 10  # catch-up window for missed resolutions
COVERAGE_WINDOW_DAYS = 90

# What we forecast. `frame` is the human phrasing for an h=1 target (the coach/
# cockpit surfaces reuse it); weight is morning-weigh-in so "tomorrow morning".
METRICS = [
    {"metric": "recovery_pct", "source": "whoop", "field": "recovery_score", "unit": "%", "frame_h1": "tomorrow", "bounds": (0.0, 100.0)},
    {
        "metric": "sleep_hours",
        "source": "whoop",
        "field": "sleep_duration_hours",
        "unit": "h",
        "frame_h1": "tonight",
        "bounds": (0.0, 14.0),
    },
    {"metric": "weight_lbs", "source": "withings", "field": "weight_lbs", "unit": "lb", "frame_h1": "tomorrow morning", "bounds": None},
]

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


def d2f(obj):
    if isinstance(obj, list):
        return [d2f(i) for i in obj]
    if isinstance(obj, dict):
        return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_decimal(v) for v in obj]
    return obj


def fetch_series(source, field, start, end):
    """Date-ordered (date, value) list for one metric; days without the field drop out."""
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": USER_PREFIX + source,
            ":s": "DATE#" + start,
            ":e": "DATE#" + end,
        },
    }
    rows = []
    while True:
        r = table.query(**with_phase_filter(dict(kwargs)))
        rows.extend(r.get("Items", []))
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    out = []
    for item in sorted(rows, key=lambda i: i.get("sk", "")):
        v = item.get(field)
        if v is None:
            continue
        try:
            out.append((item["sk"].replace("DATE#", ""), float(v)))
        except (TypeError, ValueError):
            continue
    return out


def query_forecast_rows(sk_lo, sk_hi):
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {":pk": FORECAST_PK, ":s": sk_lo, ":e": sk_hi},
    }
    rows = []
    while True:
        r = table.query(**kwargs)
        rows.extend(d2f(i) for i in r.get("Items", []))
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return rows


def build_forecast_item(metric_cfg, fc, issued_date, target_date):
    """One frozen FORECAST# row from an ewma_forecast result. Pure builder (tested).

    Interval endpoints are clamped to the metric's physical bounds — a 106% recovery
    ceiling is a statistical artifact, not an expectation, and publishing it reads as
    dishonest. Actuals live inside the bounds too, so clamping never changes whether
    an interval covers its outcome."""
    h = fc["horizon"]
    point, lo, hi = fc["point"], fc["lo"], fc["hi"]
    bounds = metric_cfg.get("bounds")
    if bounds:
        b_lo, b_hi = bounds
        point = max(b_lo, min(b_hi, point))
        lo = max(b_lo, min(b_hi, lo))
        hi = max(b_lo, min(b_hi, hi))
    return {
        "pk": FORECAST_PK,
        "sk": f"FORECAST#{target_date}#{metric_cfg['metric']}#h{h}",
        "record_type": "forecast",
        "metric": metric_cfg["metric"],
        "source": metric_cfg["source"],
        "field": metric_cfg["field"],
        "unit": metric_cfg["unit"],
        "model": MODEL_ID,
        "horizon_days": h,
        "issued_date": issued_date,
        "target_date": target_date,
        "point": round(point, 1),
        "lo": round(lo, 1),
        "hi": round(hi, 1),
        "confidence": CONFIDENCE,
        "alpha": round(fc["alpha"], 2),
        "n_history": fc["n"],
        "resolved_at": None,
    }


def build_forecast_calibration_item(row, actual, covered, resolved_date):
    """One CROSS_PHASE calibration row per resolved forecast — the platform's
    graded forecasting record. Mirrors the hypothesis-resolution row shape."""
    return {
        "pk": CALIBRATION_PK,
        "sk": f"CALIB#{resolved_date}#forecast-{row['metric']}-h{row['horizon_days']}-{row['target_date']}",
        "record_type": "forecast_resolution",
        "metric": row["metric"],
        "model": row.get("model", MODEL_ID),
        "horizon_days": row["horizon_days"],
        "issued_date": row.get("issued_date"),
        "target_date": row["target_date"],
        "point": row.get("point"),
        "lo": row.get("lo"),
        "hi": row.get("hi"),
        "confidence": row.get("confidence", CONFIDENCE),
        "actual": round(float(actual), 1),
        "covered": covered,
        "abs_error": round(abs(float(actual) - float(row.get("point", 0.0))), 2),
        "resolved_at": resolved_date,
    }


def resolve_matured(today_str, actuals_by_source):
    """Resolve every unresolved FORECAST# row whose target date's actual exists.

    `actuals_by_source` maps source -> {date -> value-dict-by-field} (prefetched
    history). Returns the list of resolution summaries written today."""
    lookback = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=RESOLVE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    rows = query_forecast_rows(f"FORECAST#{lookback}", f"FORECAST#{today_str}#zzzz")
    resolutions = []
    for row in rows:
        if row.get("resolved_at") or row.get("record_type") != "forecast":
            continue
        day_values = actuals_by_source.get(row.get("source"), {}).get(row.get("target_date"), {})
        actual = day_values.get(row.get("field"))
        if actual is None:
            continue  # actual not in yet — retried until the lookback ages out
        covered = bool(row["lo"] <= float(actual) <= row["hi"])
        calib = build_forecast_calibration_item(row, actual, covered, today_str)
        try:
            table.put_item(Item=to_decimal({k: v for k, v in calib.items() if v is not None}))
        except Exception as e:
            logger.warning(f"calibration write failed for {row['sk']}: {e}")
        try:
            table.update_item(
                Key={"pk": FORECAST_PK, "sk": row["sk"]},
                UpdateExpression="SET resolved_at = :r, actual = :a, covered = :c",
                ExpressionAttributeValues={
                    ":r": today_str,
                    ":a": Decimal(str(round(float(actual), 1))),
                    ":c": covered,
                },
            )
        except Exception as e:
            logger.warning(f"forecast resolve update failed for {row['sk']}: {e}")
        resolutions.append(
            {
                "metric": row["metric"],
                "horizon_days": row["horizon_days"],
                "target_date": row["target_date"],
                "point": row.get("point"),
                "lo": row.get("lo"),
                "hi": row.get("hi"),
                "actual": round(float(actual), 1),
                "covered": covered,
            }
        )
    return resolutions


def compute_coverage(today_str):
    """Running interval-coverage from resolved FORECAST# rows (this cycle's record).

    The honest headline: n resolved, how many the 80% interval covered, overall
    and per horizon. Returns None when nothing has resolved yet — surfaces must
    then say "no graded forecasts yet", not invent a number."""
    start = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=COVERAGE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    rows = query_forecast_rows(f"FORECAST#{start}", f"FORECAST#{today_str}#zzzz")
    resolved = [r for r in rows if r.get("resolved_at") and r.get("covered") is not None]
    if not resolved:
        return None
    out = {"n_resolved": len(resolved), "n_covered": sum(1 for r in resolved if r["covered"])}
    out["coverage_pct"] = round(100.0 * out["n_covered"] / out["n_resolved"], 1)
    for h in HORIZONS:
        sub = [r for r in resolved if r.get("horizon_days") == h]
        if sub:
            out[f"h{h}"] = {
                "n_resolved": len(sub),
                "n_covered": sum(1 for r in sub if r["covered"]),
                "coverage_pct": round(100.0 * sum(1 for r in sub if r["covered"]) / len(sub), 1),
            }
    return out


def lambda_handler(event: dict, context) -> dict:
    today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    start = (today - timedelta(days=HISTORY_DAYS)).isoformat()

    # One prefetch per source powers both fitting and resolution.
    actuals_by_source = {}
    series_by_metric = {}
    for cfg in METRICS:
        series = fetch_series(cfg["source"], cfg["field"], start, today_str)
        series_by_metric[cfg["metric"]] = series
        day_map = actuals_by_source.setdefault(cfg["source"], {})
        for date_str, val in series:
            day_map.setdefault(date_str, {})[cfg["field"]] = val

    # 1) Grade what matured before issuing anything new.
    resolutions = resolve_matured(today_str, actuals_by_source)

    # 2) Issue today's frozen forecasts.
    forecasts = []
    for cfg in METRICS:
        values = [v for _, v in series_by_metric[cfg["metric"]]]
        for h in HORIZONS:
            fc = stats_core.ewma_forecast(values, horizon=h, confidence=CONFIDENCE)
            if fc is None:
                logger.info(f"{cfg['metric']} h{h}: insufficient history (n={len(values)}) — no forecast issued")
                continue
            target = (today + timedelta(days=h)).isoformat()
            item = build_forecast_item(cfg, fc, today_str, target)
            try:
                table.put_item(Item=to_decimal({k: v for k, v in item.items() if v is not None}))
            except Exception as e:
                logger.warning(f"forecast write failed for {item['sk']}: {e}")
                continue
            forecasts.append({k: item[k] for k in ("metric", "unit", "horizon_days", "target_date", "point", "lo", "hi")})
            forecasts[-1]["frame"] = cfg["frame_h1"] if h == 1 else f"in {h} days"

    # 3) Daily summary row — the one read the coach prompt + /api/forecast make.
    coverage = compute_coverage(today_str)
    summary = {
        "pk": FORECAST_PK,
        "sk": f"DATE#{today_str}",
        "record_type": "forecast_summary",
        "date": today_str,
        "model": MODEL_ID,
        "confidence": CONFIDENCE,
        "forecasts": forecasts,
        "resolutions_today": resolutions,
        "coverage": coverage,
    }
    try:
        from compute_metadata import tag_record

        summary = tag_record(summary, source_id="forecast")
    except ImportError:
        pass
    table.put_item(Item=to_decimal({k: v for k, v in summary.items() if v is not None}))

    result = {
        "date": today_str,
        "forecasts_issued": len(forecasts),
        "resolutions": len(resolutions),
        "coverage": coverage,
    }
    logger.info(json.dumps(result))
    return result
