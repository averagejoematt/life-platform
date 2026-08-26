"""
CGM / glucose tools.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from common.pacific_time import pacific_now, pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from ingestion.source_registry import raw_date_key, raw_year_prefix  # bundled shared module: the X-9 raw/ layout facts (#2278/#2286)

from mcp.config import S3_BUCKET, USER_PREFIX, logger, s3_client, table
from mcp.core import query_source

# ── CGM helpers ──

# SEC-3 (HIGH): Compiled once at module load — avoids recompiling on every CGM call.
# Used by _load_cgm_readings to prevent S3 path traversal via malformed date_str.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ── Dashboard thresholds — ONE source of truth for the published note AND the flags ──
#
# Everything here is mg/dL (or a percentage). The writer
# (lambdas/ingestion/health_auto_export_lambda.py::process_blood_glucose) converts
# mmol/L at ingest with the 18.0182 factor, so nothing stored is ever mmol/L.
#
# Two bars, deliberately distinct and both published: a TARGET (the optimal bar the
# response prints) and a WARN bar (the clinically concerning one). Before #2221 the
# note printed the target and the flag enforced the warn bar with no way for the
# reader to tell which was the platform's actual line — a glucose SD of 22 was above
# the printed target and produced no flag at all.
_TARGET_MEAN = 100  # optimal mean glucose
_TARGET_SD = 20  # optimal glucose variability (SD)
_WARN_SD = 25  # SD above which the excursion is a warning, not a target miss
_TARGET_TIR = 90  # % of time in 70-180
_TARGET_TBR = 4  # % of time below 70 (international CGM consensus target)
_TARGET_FASTING = 90  # optimal fasting proxy (the day's minimum)
_WARN_FASTING = 100  # ADA impaired-fasting-glucose threshold
_DEFAULT_DASHBOARD_DAYS = 30

# First year the HAE webhook wrote raw/{user}/cgm_readings/ — a fixed PAST year, unlike
# the old hard-coded end year, which silently emptied the fasting view on 2027-01-01.
_CGM_FIRST_YEAR = 2024

# ADR-105: a decile computed from fewer than ten observations is an order statistic
# relabelled, not a percentile. Below this n the distribution's percentile curve is
# withheld rather than fabricated.
_MIN_N_FOR_PERCENTILES = 10

_DASHBOARD_NOTE = (
    f"Targets: mean <{_TARGET_MEAN}, SD <{_TARGET_SD}, TIR >{_TARGET_TIR}%, "
    f"time below 70 <{_TARGET_TBR}%, fasting <{_TARGET_FASTING}. "
    "Time above 140 triggers insulin + inflammation. "
    f"Severity 'warning' marks the clinical bar (SD >{_WARN_SD}, fasting >{_WARN_FASTING}); "
    "'advisory' marks a target miss short of it."
)


def _num(value):
    """Coerce a stored DynamoDB attribute to ``float``, or ``None`` when it is absent
    or unusable.

    ADR-104 behavioural absence: a day the sensor did not measure is ABSENT. A glucose
    minimum of 0 mg/dL is incompatible with life and a 0% time-in-range is a diabetic
    emergency — neither is a fact about Matthew's blood, both are ``.get(key, 0)`` about
    a missing attribute, and once one enters a mean it fabricates a clinical flag.

    Returning ``None`` (rather than raising) also keeps one non-numeric row from taking
    the whole dashboard down with a ValueError, the way ``_load_cgm_readings`` already
    degrades per-reading.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rounded(value, digits=1):
    return None if value is None else round(value, digits)


def _mean_and_n(values):
    """(mean, n) over the values that are actually present. ADR-105: every aggregate
    carries the n behind it, and different fields on the same window legitimately have
    different n."""
    present = [v for v in values if v is not None]
    if not present:
        return None, 0
    return round(sum(present) / len(present), 1), len(present)


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
        # #2286: resolved from the registry, never assembled from parts. The raw/ zone
        # is three-generation fractured in prefix AND leaf filename (X-9/#1256), so a
        # hand-built key is a coin flip that fails by returning nothing.
        key = raw_date_key("apple_health", date_str, sub="cgm_readings")
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
    end_date = args.get("end_date") or pacific_today()
    start_date = args.get("start_date")
    if not start_date:
        # `days` is DECLARED in mcp/registry.py's get_cgm inputSchema; before #2221 it was
        # never read, so a model passing days=7 exactly as instructed was answered about a
        # month. #1917 window-name honesty: query_source's `sk BETWEEN` is inclusive on
        # BOTH bounds, so an N-day window subtracts N-1 — not N, which spans N+1 days.
        span = _num(args.get("days"))
        span = _DEFAULT_DASHBOARD_DAYS if span is None else max(1, min(int(span), 3650))
        try:
            anchor = datetime.strptime(end_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            anchor = pacific_now()
            end_date = anchor.strftime("%Y-%m-%d")
        start_date = (anchor - timedelta(days=span - 1)).strftime("%Y-%m-%d")

    items = query_source("apple_health", start_date, end_date)
    if not items:
        return {"error": "No Apple Health data in range."}

    glucose_days = [i for i in sorted(items, key=lambda x: x.get("date", "")) if i.get("blood_glucose_avg") is not None]
    if not glucose_days:
        return {"error": "No blood glucose data in range. Requires Dexcom Stelo + webhook."}

    rows = []
    cgm_ct = 0
    unusable = 0
    for item in glucose_days:
        avg = _num(item.get("blood_glucose_avg"))
        if avg is None:
            # The mean is the one field the day cannot be published without.
            unusable += 1
            continue
        readings = _num(item.get("blood_glucose_readings_count"))
        row = {
            "date": item.get("date"),
            "avg": round(avg, 1),
            "min": _rounded(_num(item.get("blood_glucose_min"))),
            "max": _rounded(_num(item.get("blood_glucose_max"))),
            "std_dev": _rounded(_num(item.get("blood_glucose_std_dev"))),
            "readings": None if readings is None else int(readings),
            "time_in_range_pct": _rounded(_num(item.get("blood_glucose_time_in_range_pct"))),
            "time_above_140_pct": _rounded(_num(item.get("blood_glucose_time_above_140_pct"))),
            "time_below_70_pct": _rounded(_num(item.get("blood_glucose_time_below_70_pct"))),
            "source": item.get("cgm_source", "unknown"),
        }
        rows.append(row)
        if item.get("cgm_source") == "dexcom_stelo":
            cgm_ct += 1

    if not rows:
        return {"error": "No usable blood glucose values in range."}

    avg_vals = [r["avg"] for r in rows]
    min_vals = [r["min"] for r in rows if r["min"] is not None and r["min"] > 0]
    sd_mean, n_sd = _mean_and_n([r["std_dev"] for r in rows])
    tir_mean, n_tir = _mean_and_n([r["time_in_range_pct"] for r in rows])
    a140_mean, n_a140 = _mean_and_n([r["time_above_140_pct"] for r in rows])
    tbr_mean, n_tbr = _mean_and_n([r["time_below_70_pct"] for r in rows])

    # ADR-105: a day built from one fingerstick is not the same observation as a day
    # built from 288 sensor readings. When every day carries its reading count the mean
    # is reading-weighted (the standard CGM mean-glucose definition); when any day's
    # count is missing we fall back to the unweighted mean of daily means and SAY SO,
    # rather than inventing a weight for the day we cannot count.
    weights = [r["readings"] for r in rows]
    if all(w is not None and w > 0 for w in weights):
        total_readings = sum(weights)
        avg_glucose = round(sum(r["avg"] * r["readings"] for r in rows) / total_readings, 1)
        weighting = f"reading-weighted (n={total_readings} readings across {len(rows)} days)"
    else:
        total_readings = None
        avg_glucose = round(sum(avg_vals) / len(avg_vals), 1)
        missing = sum(1 for w in weights if w is None or w <= 0)
        weighting = f"unweighted daily means (reading count missing on {missing} of {len(rows)} days)"

    summary = {
        "total_days": len(rows),
        "cgm_days": cgm_ct,
        "manual_days": len(rows) - cgm_ct,
        "avg_glucose": avg_glucose,
        "avg_glucose_weighting": weighting,
        "total_readings": total_readings,
        "avg_fasting_proxy": round(sum(min_vals) / len(min_vals), 1) if min_vals else None,
        "avg_variability_sd": sd_mean,
        "avg_time_in_range_pct": tir_mean,
        "avg_time_above_140_pct": a140_mean,
        "avg_time_below_70_pct": tbr_mean,
        # ADR-105: each aggregate's own n — they differ whenever a row is partial.
        "n": {
            "avg_glucose": len(rows),
            "avg_fasting_proxy": len(min_vals),
            "avg_variability_sd": n_sd,
            "avg_time_in_range_pct": n_tir,
            "avg_time_above_140_pct": n_a140,
            "avg_time_below_70_pct": n_tbr,
        },
    }
    if unusable:
        summary["days_dropped_unusable"] = unusable

    flags = []
    mean_g = summary["avg_glucose"]
    if mean_g is not None and mean_g > _TARGET_MEAN:
        flags.append({"severity": "warning", "message": f"Mean glucose {mean_g} > {_TARGET_MEAN} mg/dL optimal threshold."})
    sd = summary["avg_variability_sd"]
    if sd is not None and sd > _WARN_SD:
        flags.append({"severity": "warning", "message": f"Glucose variability SD {sd} > {_WARN_SD} target. Large postprandial spikes."})
    elif sd is not None and sd > _TARGET_SD:
        flags.append(
            {
                "severity": "advisory",
                "message": f"Glucose variability SD {sd} above the <{_TARGET_SD} target (warning bar is {_WARN_SD}).",
            }
        )
    tir = summary["avg_time_in_range_pct"]
    if tir is not None and tir < _TARGET_TIR:
        flags.append({"severity": "warning", "message": f"Time in range {tir}% < {_TARGET_TIR}% target."})
    # Hypoglycemia is the only glucose excursion that is acutely dangerous, and until
    # #2221 it was the one excursion the dashboard would not mention: time_below_70_pct
    # was computed per-day and then read by nothing.
    tbr = summary["avg_time_below_70_pct"]
    if tbr is not None and tbr > _TARGET_TBR:
        flags.append(
            {
                "severity": "warning",
                "message": f"Time below 70 mg/dL {tbr}% > {_TARGET_TBR}% target. Hypoglycemia is the acutely dangerous excursion.",
            }
        )
    fp = summary.get("avg_fasting_proxy")
    if fp is not None and fp > _WARN_FASTING:
        flags.append({"severity": "warning", "message": f"Fasting proxy {fp} > {_WARN_FASTING} mg/dL. Target <{_TARGET_FASTING}."})
    elif fp is not None and fp > _TARGET_FASTING:
        flags.append(
            {
                "severity": "advisory",
                "message": f"Fasting proxy {fp} above the <{_TARGET_FASTING} target (warning bar is {_WARN_FASTING}).",
            }
        )

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
        "note": _DASHBOARD_NOTE,
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
    # These four window arguments are UNDECLARED in mcp/registry.py's get_cgm
    # inputSchema, so nothing upstream validates them: a bare float()/int() here meant a
    # malformed tool call returned a ValueError stack trace instead of the error envelope
    # the dispatcher's own `valid_views` branch exists to produce, and an out-of-range
    # window silently produced a nonsensical nadir set.
    hours = {}
    for name, default in (("nadir_start_hour", 0.0), ("nadir_end_hour", 6.0), ("deep_nadir_start_hour", 2.0), ("deep_nadir_end_hour", 5.0)):
        raw = args.get(name, default)
        val = _num(raw)
        if val is None:
            return {"error": f"Invalid {name}: {raw!r} is not a number.", "hint": f"{name} is an hour of day, 0-24."}
        if not 0.0 <= val <= 24.0:
            return {"error": f"Invalid {name}: {val} is outside the 0-24 hour range.", "hint": f"{name} is an hour of day, 0-24."}
        hours[name] = val
    nadir_start = hours["nadir_start_hour"]  # midnight
    nadir_end = hours["nadir_end_hour"]  # 6 AM
    # 2-5 AM avoids dawn phenomenon cortisol rise (4-7 AM per Attia/Patrick)
    deep_start = hours["deep_nadir_start_hour"]  # 2 AM
    deep_end = hours["deep_nadir_end_hour"]  # 5 AM
    if nadir_start >= nadir_end:
        return {"error": f"Invalid overnight window: nadir_start_hour ({nadir_start}) must be before nadir_end_hour ({nadir_end})."}
    if deep_start >= deep_end:
        return {"error": f"Invalid deep window: deep_nadir_start_hour ({deep_start}) must be before deep_nadir_end_hour ({deep_end})."}
    min_readings_raw = _num(args.get("min_overnight_readings", 6))  # need ~30 min coverage
    if min_readings_raw is None or min_readings_raw < 1:
        return {
            "error": f"Invalid min_overnight_readings: {args.get('min_overnight_readings')!r}.",
            "hint": "min_overnight_readings is a positive integer count of readings.",
        }
    min_readings = int(min_readings_raw)

    # ── Discover all CGM days from S3 ─────────────────────────────────────
    # The year list used to be hard-coded ["2024/", "2025/", "2026/"], which made this
    # view a dated time bomb: every CGM day from 2027-01-01 onward would have been
    # invisible and the view would have answered "No CGM data found in S3." for a sensor
    # streaming normally. The range now runs from the first year the Stelo webhook wrote
    # through NEXT year (the +1 covers the year boundary and any writer whose local day
    # is ahead of UTC). Listing an empty prefix costs one cheap ListObjectsV2 call.
    paginator = s3_client.get_paginator("list_objects_v2")
    cgm_days = []  # list of "YYYY-MM-DD"
    this_year = datetime.now(timezone.utc).year
    # #2286: both the listing prefix AND the reverse-parse come from the registry.
    # They used to be two hand-written copies of the same literal, and the comment
    # documenting the key shape still showed the PRE-user-segment form
    # (`raw/cgm_readings/…`) — the exact doc rot that produced #2278.
    tree_prefix = raw_year_prefix("apple_health", _CGM_FIRST_YEAR, sub="cgm_readings").rsplit("/", 2)[0] + "/"
    for year in range(_CGM_FIRST_YEAR, max(this_year + 1, _CGM_FIRST_YEAR) + 1):
        try:
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=raw_year_prefix("apple_health", year, sub="cgm_readings")):
                for obj in page.get("Contents", []):
                    key = obj["Key"]  # <registry prefix>/YYYY/MM/DD.json
                    parts = key.replace(tree_prefix, "").replace(".json", "").split("/")
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
        """Distribution statistics that refuse to exist below the n they need.

        ADR-104/105: an SD over one observation is UNDEFINED, not 0 — and the old
        literal-0 substitution was read straight back out as "Very stable overnight
        nadirs (SD 0 mg/dL) -- strong metabolic consistency", a clinical verdict derived
        entirely from a single number equalling itself. Percentiles are withheld below
        _MIN_N_FOR_PERCENTILES for the same reason.
        """
        if not vals:
            return None
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        pctiles = {"p10": None, "p25": None, "p75": None, "p90": None}
        if n >= _MIN_N_FOR_PERCENTILES:
            pctiles = {
                "p10": round(vals_sorted[int(n * 0.1)], 1),
                "p25": round(vals_sorted[int(n * 0.25)], 1),
                "p75": round(vals_sorted[int(n * 0.75)], 1),
                "p90": round(vals_sorted[int(n * 0.9)], 1),
            }
        return {
            "label": label,
            "n": n,
            "mean": round(statistics.mean(vals_sorted), 1),
            "median": round(statistics.median(vals_sorted), 1),
            "std_dev": round(statistics.stdev(vals_sorted), 1) if n > 1 else None,
            "min": vals_sorted[0],
            "max": vals_sorted[-1],
            **pctiles,
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
    lab_kwargs = _apply_phase_filter(
        {"KeyConditionExpression": Key("pk").eq(USER_PREFIX + "labs") & Key("sk").begins_with("DATE#")}, include_pilot=True
    )
    # Paginate. The biomarker maps are large; a single-page read silently truncates the
    # draw history the moment the partition crosses 1 MB, and every z-score, bias band and
    # lab trend below would then be computed from a prefix with nothing in the response
    # saying so. The S3 discovery above already paginates — this was the odd one out.
    lab_items = []
    while True:
        lab_resp = table.query(**lab_kwargs)
        lab_items.extend(lab_resp.get("Items", []))
        last_key = lab_resp.get("LastEvaluatedKey")
        if not last_key:
            break
        lab_kwargs["ExclusiveStartKey"] = last_key
    lab_draws = []
    for item in lab_items:
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

    # Sort on the DRAW date, which is the only chronology the trend below is entitled to
    # read. DynamoDB returns sk order — the import/report date — and a backfilled older
    # panel files under a LATER sk than the draw it contains, so `lab_draws[0]` was not
    # the oldest draw. (The sibling reader mcp/labs_helpers._query_all_lab_draws sorts,
    # but it sorts by `sk` too, so it does not actually solve this; only draw_date does.)
    lab_draws.sort(key=lambda d: (d.get("draw_date") or ""))

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
        if on_stats and on_stats["std_dev"]:  # None (n<2) and 0 both mean "no z-score is defined"
            z_overnight = round((lab_val - on_stats["mean"]) / on_stats["std_dev"], 2)
        z_deep = None
        if deep_stats and deep_stats["std_dev"]:
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
        # ADR-105: this block is the tool's verdict on whether the CGM can stand in for a
        # venous draw, and it is the difference of two MEANS. Both n's ride with it — a
        # single coincidence must not read like a year of paired data.
        bias["n_lab_draws"] = len(lab_draws)
        bias["n_nights"] = on_stats["n"]
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

        if bias["n_lab_draws"] < 2 or bias["n_nights"] < 3:
            bias["interpretation"] += (
                f" Provisional: computed from {bias['n_lab_draws']} lab draw(s) and {bias['n_nights']} night(s) "
                "— too few paired observations to characterise agreement."
            )

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

    if on_stats and on_stats["std_dev"] is not None and on_stats["std_dev"] > 8:
        insights.append(
            f"High overnight nadir variability (SD {on_stats['std_dev']} mg/dL). Factors: meal timing, alcohol, sleep quality, stress."
        )
    elif on_stats and on_stats["std_dev"] is not None and on_stats["std_dev"] < 4:
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
        # Always a LIST. It used to degrade to a bare STRING when there was no same-day
        # overlap, so a consumer taking len() got 48 single characters instead of zero
        # validations — and the consumer here is an LLM reading the JSON. The explanation
        # moved to a sibling note, the way cgm_coverage and bias_analysis already do it.
        "direct_validations": direct_validations,
        "direct_validations_note": (None if direct_validations else "No same-day overlap between CGM and lab draws."),
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
        result = {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'dashboard' for time-in-range, variability, mean glucose, clinical flags. 'fasting' for overnight nadir-based fasting glucose validation.",
        }
    else:
        result = VALID_VIEWS[view](args)
    # R13-F09: the disclaimer rides on EVERY response, not only the successful ones.
    # "No blood glucose data in range. Requires Dexcom Stelo + webhook." is itself a
    # health statement, and it was the one response shipping without the qualifier.
    if isinstance(result, dict):
        result["_disclaimer"] = _CGM_DISCLAIMER
    return result
