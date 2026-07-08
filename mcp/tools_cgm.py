"""
CGM / glucose tools.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from mcp.config import S3_BUCKET, USER_ID, USER_PREFIX, logger, s3_client, table
from mcp.core import query_source

# ── CGM helpers ──

# SEC-3 (HIGH): Compiled once at module load — avoids recompiling on every CGM call.
# Used by _load_cgm_readings to prevent S3 path traversal via malformed date_str.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_cgm_readings(date_str):
    """
    Load 5-minute CGM readings from S3 for a given date.
    Returns list of (hour_decimal, value_mg_dl) tuples sorted by time.

    SEC-3 (HIGH): date_str is validated before S3 key construction to prevent
    path traversal (e.g. '../../config/board_of_directors' -> wrong S3 object).
    A malformed date_str would split("-") into unexpected segments and produce
    a key like raw/matthew/cgm_readings/../../config/..., reading an unintended
    object. The regex + strptime checks eliminate this class of input entirely.
    """
    # Validate format and calendar validity before constructing S3 key
    if not _DATE_RE.match(str(date_str)):
        logger.warning("_load_cgm_readings: invalid date_str format: %r -- rejecting", date_str)
        return []
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning("_load_cgm_readings: non-calendar date: %r -- rejecting", date_str)
        return []
    try:
        y, m, d = date_str.split("-")
        key = f"raw/{USER_ID}/cgm_readings/{y}/{m}/{d}.json"
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        readings = json.loads(resp["Body"].read())
        result = []
        for r in readings:
            val = r.get("value")
            time_str = r.get("time", "")
            if val is None or not time_str:
                continue
            # Parse "2024-10-15 11:04:29 -0800" format
            try:
                parts = time_str.strip().split(" ")
                hms = parts[1].split(":")
                hour_dec = int(hms[0]) + int(hms[1]) / 60 + int(hms[2]) / 3600
                result.append((hour_dec, float(val)))
            except (IndexError, ValueError):
                continue
        return sorted(result, key=lambda x: x[0])
    except s3_client.exceptions.NoSuchKey:
        return []
    except Exception as e:
        logger.warning(f"CGM read failed for {date_str}: {e}")
        return []


def _get_cgm_dashboard(args):
    """CGM glucose daily dashboard from DynamoDB aggregates."""
    end_date = args.get("end_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"))

    items = query_source("apple_health", start_date, end_date)
    if not items:
        return {"error": "No Apple Health data in range."}

    glucose_days = [i for i in sorted(items, key=lambda x: x.get("date", "")) if i.get("blood_glucose_avg") is not None]
    if not glucose_days:
        return {"error": "No blood glucose data in range. Requires Dexcom Stelo + webhook."}

    rows = []
    cgm_ct = 0
    for item in glucose_days:
        row = {
            "date": item.get("date"),
            "avg": round(float(item["blood_glucose_avg"]), 1),
            "min": round(float(item.get("blood_glucose_min", 0)), 1),
            "max": round(float(item.get("blood_glucose_max", 0)), 1),
            "std_dev": round(float(item.get("blood_glucose_std_dev", 0)), 1),
            "readings": int(float(item.get("blood_glucose_readings_count", 0))),
            "time_in_range_pct": round(float(item.get("blood_glucose_time_in_range_pct", 0)), 1),
            "time_above_140_pct": round(float(item.get("blood_glucose_time_above_140_pct", 0)), 1),
            "time_below_70_pct": round(float(item.get("blood_glucose_time_below_70_pct", 0)), 1),
            "source": item.get("cgm_source", "unknown"),
        }
        rows.append(row)
        if item.get("cgm_source") == "dexcom_stelo":
            cgm_ct += 1

    avg_vals = [r["avg"] for r in rows]
    min_vals = [r["min"] for r in rows if r["min"] > 0]
    sd_vals = [r["std_dev"] for r in rows]
    tir_vals = [r["time_in_range_pct"] for r in rows]
    a140 = [r["time_above_140_pct"] for r in rows]

    summary = {
        "total_days": len(rows),
        "cgm_days": cgm_ct,
        "manual_days": len(rows) - cgm_ct,
        "avg_glucose": round(sum(avg_vals) / len(avg_vals), 1),
        "avg_fasting_proxy": round(sum(min_vals) / len(min_vals), 1) if min_vals else None,
        "avg_variability_sd": round(sum(sd_vals) / len(sd_vals), 1),
        "avg_time_in_range_pct": round(sum(tir_vals) / len(tir_vals), 1),
        "avg_time_above_140_pct": round(sum(a140) / len(a140), 1),
    }

    flags = []
    if summary["avg_glucose"] > 100:
        flags.append({"severity": "warning", "message": f"Mean glucose {summary['avg_glucose']} > 100 mg/dL optimal threshold."})
    if summary["avg_variability_sd"] > 25:
        flags.append(
            {
                "severity": "warning",
                "message": f"Glucose variability SD {summary['avg_variability_sd']} > 25 target. Large postprandial spikes.",
            }
        )
    if summary["avg_time_in_range_pct"] < 90:
        flags.append({"severity": "warning", "message": f"Time in range {summary['avg_time_in_range_pct']}% < 90% target."})
    fp = summary.get("avg_fasting_proxy")
    if fp and fp > 100:
        flags.append({"severity": "warning", "message": f"Fasting proxy {fp} > 100 mg/dL. Target <90."})

    trend = None
    if len(avg_vals) >= 6:
        mid = len(avg_vals) // 2
        f_avg = sum(avg_vals[:mid]) / mid
        s_avg = sum(avg_vals[mid:]) / (len(avg_vals) - mid)
        pct = round((s_avg - f_avg) / f_avg * 100, 1) if f_avg else 0
        trend = {
            "first_half": round(f_avg, 1),
            "second_half": round(s_avg, 1),
            "pct_change": pct,
            "direction": "improving" if pct < -2 else "worsening" if pct > 2 else "stable",
        }

    return {
        "period": {"start": start_date, "end": end_date},
        "summary": summary,
        "trend": trend,
        "clinical_flags": flags or [],
        "daily": rows,
        "note": "Targets: mean <100, SD <20, TIR >90%, fasting <90. Time above 140 triggers insulin + inflammation.",
    }


def _get_fasting_glucose_validation(args):
    """
    Validate CGM fasting glucose proxy against venous lab draws.

    Two modes:
      1. Direct validation: same-day CGM overnight nadir vs lab fasting glucose
      2. Statistical validation: CGM nadir distribution vs historical lab values

    Computes proper overnight nadir using 00:00-06:00 window (avoids dawn
    phenomenon cortisol rise per Attia/Huberman). Also computes the narrower
    02:00-05:00 "deep nadir" which excludes both late digestion and dawn effect.

    Returns: nadir distribution, lab comparisons, bias analysis, confidence.
    """
    import statistics

    # ── Parameters ────────────────────────────────────────────────────────
    nadir_start = float(args.get("nadir_start_hour", 0))  # midnight
    nadir_end = float(args.get("nadir_end_hour", 6))  # 6 AM
    # 2-5 AM avoids dawn phenomenon cortisol rise (4-7 AM per Attia/Patrick)
    deep_start = float(args.get("deep_nadir_start_hour", 2))  # 2 AM
    deep_end = float(args.get("deep_nadir_end_hour", 5))  # 5 AM
    min_readings = int(args.get("min_overnight_readings", 6))  # need ~30 min coverage

    # ── Discover all CGM days from S3 ─────────────────────────────────────
    paginator = s3_client.get_paginator("list_objects_v2")
    cgm_days = []  # list of "YYYY-MM-DD"
    for prefix_year in ["2024/", "2025/", "2026/"]:
        try:
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"raw/{USER_ID}/cgm_readings/{prefix_year}"):
                for obj in page.get("Contents", []):
                    key = obj["Key"]  # raw/cgm_readings/2024/10/01.json
                    parts = key.replace(f"raw/{USER_ID}/cgm_readings/", "").replace(".json", "").split("/")
                    if len(parts) == 3:
                        y, m, d = parts
                        cgm_days.append(f"{y}-{m.zfill(2)}-{d.zfill(2)}")
        except Exception:
            continue
    cgm_days.sort()

    if not cgm_days:
        return {"error": "No CGM data found in S3."}

    # ── Compute overnight nadirs for each day ────────────────────────────
    nadir_results = []  # list of dicts per day
    for date_str in cgm_days:
        readings = _load_cgm_readings(date_str)
        if not readings:
            continue

        # Filter to overnight window (midnight to nadir_end)
        overnight = [(h, v) for h, v in readings if nadir_start <= h < nadir_end]
        deep_night = [(h, v) for h, v in readings if deep_start <= h < deep_end]

        if len(overnight) < min_readings:
            continue

        overnight_vals = [v for _, v in overnight]
        on_min = min(overnight_vals)
        on_avg = sum(overnight_vals) / len(overnight_vals)
        on_min_time = None
        for h, v in overnight:
            if v == on_min:
                hh = int(h)
                mm = int((h - hh) * 60)
                on_min_time = f"{hh:02d}:{mm:02d}"
                break

        deep_min = None
        deep_avg = None
        if len(deep_night) >= 4:
            deep_vals = [v for _, v in deep_night]
            deep_min = min(deep_vals)
            deep_avg = round(sum(deep_vals) / len(deep_vals), 1)

        # Full-day min for comparison (current proxy method)
        all_vals = [v for _, v in readings]
        daily_min = min(all_vals) if all_vals else None

        nadir_results.append(
            {
                "date": date_str,
                "overnight_nadir": on_min,
                "overnight_avg": round(on_avg, 1),
                "overnight_nadir_time": on_min_time,
                "overnight_readings": len(overnight),
                "deep_nadir": deep_min,
                "deep_avg": deep_avg,
                "daily_min": daily_min,
                "daily_min_vs_overnight": round(daily_min - on_min, 1) if daily_min is not None else None,
            }
        )

    if not nadir_results:
        return {"error": "Insufficient overnight CGM readings across all days."}

    # ── Distribution stats ───────────────────────────────────────────────
    on_nadirs = [r["overnight_nadir"] for r in nadir_results]
    deep_nadirs = [r["deep_nadir"] for r in nadir_results if r["deep_nadir"] is not None]
    daily_mins = [r["daily_min"] for r in nadir_results if r["daily_min"] is not None]

    def dist_stats(vals, label):
        if not vals:
            return None
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        return {
            "label": label,
            "n": n,
            "mean": round(statistics.mean(vals_sorted), 1),
            "median": round(statistics.median(vals_sorted), 1),
            "std_dev": round(statistics.stdev(vals_sorted), 1) if n > 1 else 0,
            "min": vals_sorted[0],
            "max": vals_sorted[-1],
            "p10": round(vals_sorted[int(n * 0.1)], 1),
            "p25": round(vals_sorted[int(n * 0.25)], 1),
            "p75": round(vals_sorted[int(n * 0.75)], 1),
            "p90": round(vals_sorted[int(n * 0.9)], 1),
        }

    distributions = {
        "overnight_nadir_00_06": dist_stats(on_nadirs, "Overnight nadir (00:00-06:00)"),
        "deep_nadir_02_05": dist_stats(deep_nadirs, "Deep nadir (02:00-05:00)"),
        "daily_minimum": dist_stats(daily_mins, "Daily minimum (current proxy)"),
    }

    # ── Load lab fasting glucose ─────────────────────────────────────────
    from boto3.dynamodb.conditions import Key

    from mcp.core import _apply_phase_filter  # ADR-058

    # ADR-058: longitudinal/clinical archive — cross-phase by design (owner decision 2026-06-06)
    lab_resp = table.query(
        **_apply_phase_filter(
            {"KeyConditionExpression": Key("pk").eq(USER_PREFIX + "labs") & Key("sk").begins_with("DATE#")}, include_pilot=True
        )
    )
    lab_draws = []
    for item in lab_resp.get("Items", []):
        glucose_bm = item.get("biomarkers", {}).get("glucose", {})
        val = glucose_bm.get("value_numeric")
        if val is not None:
            lab_draws.append(
                {
                    "draw_date": item.get("draw_date"),
                    "fasting_glucose_mg_dl": float(val),
                    "provider": item.get("lab_provider", "unknown"),
                }
            )

    # ── Direct validation (same-day overlap) ─────────────────────────────
    nadir_by_date = {r["date"]: r for r in nadir_results}
    direct_validations = []
    for draw in lab_draws:
        dd = draw["draw_date"]
        if dd in nadir_by_date:
            nr = nadir_by_date[dd]
            diff_overnight = round(draw["fasting_glucose_mg_dl"] - nr["overnight_nadir"], 1)
            diff_deep = round(draw["fasting_glucose_mg_dl"] - nr["deep_nadir"], 1) if nr["deep_nadir"] else None
            direct_validations.append(
                {
                    "date": dd,
                    "lab_fasting_glucose": draw["fasting_glucose_mg_dl"],
                    "cgm_overnight_nadir": nr["overnight_nadir"],
                    "cgm_deep_nadir": nr["deep_nadir"],
                    "cgm_daily_min": nr["daily_min"],
                    "lab_minus_cgm_overnight": diff_overnight,
                    "lab_minus_cgm_deep": diff_deep,
                    "provider": draw["provider"],
                }
            )

    # ── Statistical validation (no overlap) ──────────────────────────────
    stat_validations = []
    on_stats = distributions["overnight_nadir_00_06"]
    deep_stats = distributions["deep_nadir_02_05"]

    for draw in lab_draws:
        lab_val = draw["fasting_glucose_mg_dl"]
        z_overnight = None
        if on_stats and on_stats["std_dev"] > 0:
            z_overnight = round((lab_val - on_stats["mean"]) / on_stats["std_dev"], 2)
        z_deep = None
        if deep_stats and deep_stats["std_dev"] > 0:
            z_deep = round((lab_val - deep_stats["mean"]) / deep_stats["std_dev"], 2)

        pct = None
        if on_nadirs:
            below = sum(1 for v in on_nadirs if v <= lab_val)
            pct = round(below / len(on_nadirs) * 100, 1)

        stat_validations.append(
            {
                "draw_date": draw["draw_date"],
                "lab_fasting_glucose": lab_val,
                "vs_overnight_nadir": {
                    "z_score": z_overnight,
                    "percentile_of_nadir_dist": pct,
                    "within_1sd": abs(z_overnight) <= 1 if z_overnight is not None else None,
                    "within_2sd": abs(z_overnight) <= 2 if z_overnight is not None else None,
                },
                "vs_deep_nadir": (
                    {
                        "z_score": z_deep,
                        "within_1sd": abs(z_deep) <= 1 if z_deep is not None else None,
                    }
                    if z_deep is not None
                    else None
                ),
                "provider": draw["provider"],
            }
        )

    # ── Bias analysis ────────────────────────────────────────────────────
    bias = {}
    if on_stats and lab_draws:
        lab_mean = sum(d["fasting_glucose_mg_dl"] for d in lab_draws) / len(lab_draws)
        bias["lab_mean_fasting"] = round(lab_mean, 1)
        bias["cgm_overnight_nadir_mean"] = on_stats["mean"]
        bias["cgm_daily_min_mean"] = distributions["daily_minimum"]["mean"] if distributions["daily_minimum"] else None
        bias["lab_minus_cgm_overnight"] = round(lab_mean - on_stats["mean"], 1)
        if distributions["daily_minimum"]:
            bias["lab_minus_cgm_daily_min"] = round(lab_mean - distributions["daily_minimum"]["mean"], 1)
        if deep_stats:
            bias["cgm_deep_nadir_mean"] = deep_stats["mean"]
            bias["lab_minus_cgm_deep"] = round(lab_mean - deep_stats["mean"], 1)

        # Agreement bands per Dexcom Stelo MARD ~9% (FDA 510(k) K203370)
        diff = bias["lab_minus_cgm_overnight"]
        if abs(diff) <= 5:
            bias["interpretation"] = "Excellent agreement -- CGM overnight nadir closely matches lab fasting glucose."
            bias["confidence"] = "high"
        elif abs(diff) <= 10:
            direction = "higher" if diff > 0 else "lower"
            bias["interpretation"] = (
                f"Good agreement -- lab reads ~{abs(diff)} mg/dL {direction} than CGM nadir. Within expected CGM accuracy range (+-10-15 mg/dL for Stelo)."
            )
            bias["confidence"] = "moderate"
        elif abs(diff) <= 20:
            direction = "higher" if diff > 0 else "lower"
            bias["interpretation"] = (
                f"Moderate discrepancy -- lab reads ~{abs(diff)} mg/dL {direction}. Dexcom Stelo has MARD ~9% which can produce this gap. Consider a same-day validation."
            )
            bias["confidence"] = "low"
        else:
            bias["interpretation"] = (
                f"Significant discrepancy ({abs(diff)} mg/dL). CGM interstitial glucose lags venous by design, but this gap warrants investigation."
            )
            bias["confidence"] = "very_low"

    # ── Insights ─────────────────────────────────────────────────────────
    insights = []

    if distributions["daily_minimum"] and on_stats:
        dm = distributions["daily_minimum"]["mean"]
        on = on_stats["mean"]
        diff = round(dm - on, 1)
        if abs(diff) > 3:
            insights.append(
                f"Daily minimum averages {dm} vs overnight nadir {on} ({diff:+.1f} mg/dL). "
                f"{'Daily min occurs outside overnight window -- current proxy slightly underestimates true fasting.' if diff < 0 else 'Daily min typically IS the overnight nadir -- current proxy is reasonable.'}"
            )
        else:
            insights.append(
                f"Daily minimum ({dm}) and overnight nadir ({on}) are very close -- current fasting proxy is a good approximation."
            )

    if deep_stats and on_stats:
        diff = round(deep_stats["mean"] - on_stats["mean"], 1)
        if abs(diff) > 2:
            insights.append(
                f"Deep nadir (2-5 AM: {deep_stats['mean']}) differs from broad overnight (0-6 AM: {on_stats['mean']}) by {diff:+.1f} mg/dL. "
                f"Dawn phenomenon may be raising late-night readings."
            )

    if on_stats and on_stats["std_dev"] > 8:
        insights.append(
            f"High overnight nadir variability (SD {on_stats['std_dev']} mg/dL). Factors: meal timing, alcohol, sleep quality, stress."
        )
    elif on_stats and on_stats["std_dev"] < 4:
        insights.append(f"Very stable overnight nadirs (SD {on_stats['std_dev']} mg/dL) -- strong metabolic consistency.")

    if len(lab_draws) >= 3:
        recent = lab_draws[-1]["fasting_glucose_mg_dl"]
        oldest = lab_draws[0]["fasting_glucose_mg_dl"]
        if recent > oldest + 5:
            insights.append(
                f"Lab fasting glucose trending up: {oldest} -> {recent} mg/dL over {len(lab_draws)} draws. Monitor with CGM confirmation."
            )
        elif recent < oldest - 5:
            insights.append(f"Lab fasting glucose trending down: {oldest} -> {recent} mg/dL -- positive trajectory.")

    if not direct_validations:
        insights.append(
            "No same-day CGM + lab data available. Schedule your next blood draw while wearing the Stelo for gold-standard validation."
        )

    return {
        "cgm_coverage": {
            "first_date": cgm_days[0],
            "last_date": cgm_days[-1],
            "total_cgm_days": len(cgm_days),
            "days_with_valid_overnight": len(nadir_results),
        },
        "distributions": distributions,
        "lab_draws": lab_draws,
        "direct_validations": direct_validations if direct_validations else "No same-day overlap between CGM and lab draws.",
        "statistical_validations": stat_validations,
        "bias_analysis": bias,
        "insights": insights,
        "methodology": {
            "overnight_window": f"{int(nadir_start):02d}:00 - {int(nadir_end):02d}:00",
            "deep_nadir_window": f"{int(deep_start):02d}:00 - {int(deep_end):02d}:00",
            "min_readings_required": min_readings,
            "cgm_device": "Dexcom Stelo (MARD ~9%)",
            "note": "Interstitial glucose (CGM) lags venous blood by 5-15 min and can differ by +-10-15 mg/dL. Lab draws are single-point; CGM captures continuous overnight minimum.",
        },
        "board_of_directors": {
            "Attia": "Fasting glucose <90 mg/dL is optimal. Overnight CGM nadir is more informative than a single lab draw -- it captures the true metabolic baseline every night.",
            "Patrick": "Dawn phenomenon (4-7 AM cortisol rise) elevates glucose. The 2-5 AM deep nadir avoids this confounder and gives the cleanest fasting signal.",
            "Huberman": "Glucose regulation is a proxy for metabolic flexibility. Low overnight variability + clean nadirs indicate good insulin sensitivity and hepatic glucose control.",
        },
    }


# R13-F09: Standard medical disclaimer for CGM health-assessment responses.
_CGM_DISCLAIMER = (
    "For personal health tracking only. Not medical advice. "
    "Consult a qualified healthcare provider before making health decisions based on this data."
)


def tool_get_cgm(args):
    """Unified CGM intelligence dispatcher."""
    VALID_VIEWS = {
        "dashboard": _get_cgm_dashboard,
        "fasting": _get_fasting_glucose_validation,
    }
    view = (args.get("view") or "dashboard").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'dashboard' for time-in-range, variability, mean glucose, clinical flags. 'fasting' for overnight nadir-based fasting glucose validation.",
        }
    result = VALID_VIEWS[view](args)
    # R13-F09: Inject disclaimer into all CGM view responses
    if isinstance(result, dict) and "error" not in result:
        result["_disclaimer"] = _CGM_DISCLAIMER
    return result
