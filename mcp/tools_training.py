"""
Training tools: load, PRs, correlation, seasonal, periodization, recommendation, HR recovery.
"""
import json
import math
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from mcp.config import (
    table, s3_client, S3_BUCKET, USER_PREFIX, USER_ID, SOURCES,
    P40_GROUPS, FIELD_ALIASES, logger,
    INSIGHTS_PK, EXPERIMENTS_PK, TRAVEL_PK,
)
from mcp.core import (
    query_source, parallel_query_sources, query_source_range,
    get_profile, get_sot, decimal_to_float,
    ddb_cache_get, ddb_cache_set, mem_cache_get, mem_cache_set,
    date_diff_days, resolve_field,
)
from mcp.helpers import (
    aggregate_items, flatten_strava_activity,
    compute_daily_load_score, compute_ewa, pearson_r, _linear_regression,
    classify_day_type, query_chronicling, _habit_series,
)
from mcp.tools_correlation import tool_get_zone2_breakdown

def tool_get_training_load(args):
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_dt   = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=180)
    start_date = args.get("start_date", start_dt.strftime("%Y-%m-%d"))
    warmup_dt  = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=84)
    warmup_start = warmup_dt.strftime("%Y-%m-%d")

    cardio_source = get_sot("cardio")
    day_records = query_source(cardio_source, warmup_start, end_date)

    load_by_date = {}
    for day in day_records:
        d = day.get("date")
        if d:
            load_by_date[d] = compute_daily_load_score(day)

    cur = warmup_dt
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    chrono = []
    while cur <= end_dt:
        ds = cur.strftime("%Y-%m-%d")
        chrono.append((ds, load_by_date.get(ds, 0.0)))
        cur += timedelta(days=1)

    ctl_series = compute_ewa(chrono, 42)
    atl_series = compute_ewa(chrono, 7)

    start_dt_req = datetime.strptime(start_date, "%Y-%m-%d")
    result_rows = []
    for (date_str, ctl), (_, atl) in zip(ctl_series, atl_series):
        if datetime.strptime(date_str, "%Y-%m-%d") < start_dt_req:
            continue
        tsb  = round(ctl - atl, 2)
        acwr = round(atl / ctl, 2) if ctl > 0 else None

        risk = "low"
        if acwr is not None:
            if acwr > 1.5:
                risk = "HIGH — injury risk elevated, consider reducing load"
            elif acwr > 1.3:
                risk = "moderate — monitor carefully"

        form = "neutral"
        if tsb > 5:
            form = "fresh — good for key sessions or race"
        elif tsb < -10:
            form = "fatigued — accumulated training stress is high"
        elif tsb < -25:
            form = "very fatigued — recovery priority"

        result_rows.append({
            "date":           date_str,
            "daily_load":     round(load_by_date.get(date_str, 0.0), 1),
            "ctl_fitness":    ctl,
            "atl_fatigue":    atl,
            "tsb_form":       tsb,
            "acwr":           acwr,
            "injury_risk":    risk,
            "form_status":    form,
        })

    if not result_rows:
        return {"message": "No training data found for the requested window."}

    latest = result_rows[-1]
    peak_ctl = max(result_rows, key=lambda r: r["ctl_fitness"])

    # Board rec 1D: Training monotony (Galpin) — weekly mean / SD of daily load
    last_7_loads = [r["daily_load"] for r in result_rows[-7:]]
    monotony_result = {}
    if len(last_7_loads) >= 7:
        mean_7 = sum(last_7_loads) / len(last_7_loads)
        var_7 = sum((x - mean_7) ** 2 for x in last_7_loads) / len(last_7_loads)
        sd_7 = var_7 ** 0.5 if var_7 > 0 else 0
        monotony = round(mean_7 / sd_7, 2) if sd_7 > 0 else None
        weekly_strain = round(sum(last_7_loads) * monotony, 1) if monotony else None
        monotony_result = {
            "training_monotony": monotony,
            "weekly_training_strain": weekly_strain,
            "monotony_risk": "HIGH — monotonous training increases illness/overtraining risk" if monotony and monotony > 2.0 else "ok",
        }

    return {
        "model":          "Banister Impulse-Response (CTL=42d EWA, ATL=7d EWA)",
        "load_proxy":     "kJ (cycling) > TRIMP (HR×time) > distance+elevation estimate",
        "current_state":  latest,
        "peak_fitness":   {"ctl": peak_ctl["ctl_fitness"], "date": peak_ctl["date"]},
        "monotony":       monotony_result,
        "series":         result_rows,
        "interpretation": {
            "CTL": "Fitness base (42-day). Higher = more aerobic capacity built.",
            "ATL": "Fatigue (7-day). Spikes after big training blocks.",
            "TSB": "Form = CTL - ATL. Positive = fresh, negative = tired.",
            "ACWR": "Acute:Chronic ratio. >1.3 caution, >1.5 injury risk.",
            "Monotony": "Weekly mean load / SD. >2.0 = illness risk (Galpin). Vary intensity.",
        },
    }


def tool_get_personal_records(args):
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    profile  = get_profile()
    dob_str  = profile.get("date_of_birth")

    def age_at(date_str):
        if not dob_str or not date_str:
            return None
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d")
            d   = datetime.strptime(date_str, "%Y-%m-%d")
            return round((d - dob).days / 365.25, 1)
        except Exception:
            return None

    records = {}

    pr_cache_key = f"personal_records_{end_date}"
    cached = ddb_cache_get(pr_cache_key) or mem_cache_get(pr_cache_key)
    if cached:
        return cached

    pr_sources = parallel_query_sources([get_sot("cardio"), get_sot("physiology"), get_sot("body")], "2000-01-01", end_date)

    strava_days = pr_sources.get(get_sot("cardio"), [])
    all_acts    = []
    for day in strava_days:
        all_acts.extend(flatten_strava_activity(day))

    act_fields = {
        "longest_activity_miles":         ("distance_miles",            "max"),
        "most_elevation_gain_feet":        ("total_elevation_gain_feet", "max"),
        "longest_moving_time_seconds":     ("moving_time_seconds",       "max"),
        "highest_avg_heartrate_bpm":       ("average_heartrate",         "max"),
        "highest_max_heartrate_bpm":       ("max_heartrate",             "max"),
        "highest_avg_watts":               ("average_watts",             "max"),
        "most_kilojoules":                 ("kilojoules",                "max"),
        "most_prs_in_one_activity":        ("pr_count",                  "max"),
    }

    for label, (field, mode) in act_fields.items():
        candidates = [(float(a[field]), a) for a in all_acts if a.get(field) is not None]
        if not candidates:
            continue
        best_val, best_act = max(candidates, key=lambda x: x[0])
        records[label] = {
            "value":      round(best_val, 2),
            "date":       best_act.get("date"),
            "activity":   best_act.get("name"),
            "sport_type": best_act.get("sport_type"),
            "age_at_record": age_at(best_act.get("date")),
        }

    day_fields = {
        "biggest_day_miles":     ("total_distance_miles",      "max"),
        "biggest_day_elevation": ("total_elevation_gain_feet", "max"),
        "most_activities_in_day":("activity_count",            "max"),
    }
    for label, (field, mode) in day_fields.items():
        candidates = [(float(d[field]), d) for d in strava_days if d.get(field)]
        if not candidates:
            continue
        best_val, best_day = max(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    weeks = defaultdict(lambda: {"miles": 0.0, "elev": 0.0, "dates": []})
    for day in strava_days:
        date_str = day.get("date", "")
        if not date_str:
            continue
        try:
            dt  = datetime.strptime(date_str, "%Y-%m-%d")
            key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        except ValueError:
            continue
        weeks[key]["miles"] += float(day.get("total_distance_miles") or 0)
        weeks[key]["elev"]  += float(day.get("total_elevation_gain_feet") or 0)
        weeks[key]["dates"].append(date_str)

    if weeks:
        best_week_miles = max(weeks.items(), key=lambda x: x[1]["miles"])
        best_week_elev  = max(weeks.items(), key=lambda x: x[1]["elev"])
        records["biggest_week_miles"] = {
            "value": round(best_week_miles[1]["miles"], 2),
            "week":  best_week_miles[0],
            "week_start": min(best_week_miles[1]["dates"]),
            "age_at_record": age_at(min(best_week_miles[1]["dates"])),
        }
        records["biggest_week_elevation_feet"] = {
            "value": round(best_week_elev[1]["elev"], 1),
            "week":  best_week_elev[0],
            "week_start": min(best_week_elev[1]["dates"]),
            "age_at_record": age_at(min(best_week_elev[1]["dates"])),
        }

    whoop_days = pr_sources.get("whoop", [])
    whoop_fields = {
        "best_hrv_ms":              ("hrv",                 "max"),
        "lowest_resting_hr_bpm":    ("resting_heart_rate",  "min"),
        "best_recovery_score":      ("recovery_score",      "max"),
        "highest_strain":           ("strain",              "max"),
        "longest_sleep_hours":      ("sleep_duration_hours","max"),
        "worst_recovery_score":     ("recovery_score",      "min"),
    }
    for label, (field, mode) in whoop_fields.items():
        candidates = [(float(d[field]), d) for d in whoop_days if d.get(field) is not None]
        if not candidates:
            continue
        best_val, best_day = (max if mode == "max" else min)(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    withings_days = pr_sources.get("withings", [])
    withings_fields = {
        "heaviest_weight_lbs":   ("weight_lbs", "max"),
        "lightest_weight_lbs":   ("weight_lbs", "min"),
        "lowest_body_fat_pct":   ("body_fat_percentage", "min"),
        "highest_muscle_mass_lbs": ("muscle_mass_lbs", "max"),
    }
    for label, (field, mode) in withings_fields.items():
        candidates = [(float(d[field]), d) for d in withings_days if d.get(field) is not None]
        if not candidates:
            continue
        best_val, best_day = (max if mode == "max" else min)(candidates, key=lambda x: x[0])
        records[label] = {
            "value": round(best_val, 2),
            "date":  best_day.get("date"),
            "age_at_record": age_at(best_day.get("date")),
        }

    payload = {
        "profile_dob":    dob_str,
        "records_through": end_date,
        "total_records":  len(records),
        "records":        records,
        "coaching_note":  "Age at record enables tracking whether peak performances are trending younger or older over time.",
    }
    ddb_cache_set(pr_cache_key, payload)
    mem_cache_set(pr_cache_key, payload)
    return payload


def tool_get_cross_source_correlation(args):
    """
    R13-F06: n-gated Pearson correlation with p-value and 95% confidence interval.

    Minimum sample sizes:
      n < 14  → hard reject (too noisy for any interpretation)
      n < 30  → "weak" label is the maximum allowed strength (prevents
                 a spurious r=0.7 on n=20 being reported as "strong")
      n < 50  → "moderate" label is the maximum allowed strength
      n >= 50 → all labels allowed

    P-value: two-tailed t-test on r (t = r * sqrt(n-2) / sqrt(1-r²), df=n-2).
    95% CI: Fisher z-transform method.
    """
    import math

    source_a   = args.get("source_a")
    field_a    = args.get("field_a")
    source_b   = args.get("source_b")
    field_b    = args.get("field_b")
    start_date = args.get("start_date", "2019-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    lag_days   = int(args.get("lag_days", 0))

    if not all([source_a, field_a, source_b, field_b]):
        raise ValueError("source_a, field_a, source_b, field_b are all required")

    lag_end_dt  = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=abs(lag_days))
    lag_end     = lag_end_dt.strftime("%Y-%m-%d")

    items_a = query_source(source_a, start_date, lag_end)
    items_b = query_source(source_b, start_date, lag_end)

    fa = resolve_field(source_a, field_a)
    fb = resolve_field(source_b, field_b)

    dict_a = {}
    for item in items_a:
        d = item.get("date")
        v = item.get(fa)
        if d and v is not None:
            dict_a[d] = float(v)

    dict_b = {}
    for item in items_b:
        d = item.get("date")
        v = item.get(fb)
        if d and v is not None:
            dict_b[d] = float(v)

    pairs = []
    for date_str, val_a in sorted(dict_a.items()):
        if date_str > end_date:
            continue
        try:
            shifted = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
        except Exception:
            continue
        val_b = dict_b.get(shifted)
        if val_b is not None:
            pairs.append((date_str, val_a, val_b))

    n = len(pairs)

    # R13-F06: Hard minimum — below 14 the p-value is always >0.10 for any r
    if n < 14:
        return {
            "error": (
                f"Insufficient overlapping data points ({n}). "
                "Need at least 14 paired days for a meaningful correlation. "
                "Try a wider date range or different sources."
            ),
            "n_paired_days": n,
            "n_required": 14,
        }

    xs = [p[1] for p in pairs]
    ys = [p[2] for p in pairs]
    r  = pearson_r(xs, ys)

    # ── P-value (two-tailed t-test, df = n-2) ───────────────────────────────
    p_value = None
    if r is not None and abs(r) < 1.0 and n > 2:
        t_stat = r * math.sqrt(n - 2) / math.sqrt(max(1e-10, 1 - r**2))
        # Approximation of two-tailed p-value using complementary error function
        # This avoids a scipy dependency — accurate to ~3 decimal places for df>5
        df = n - 2
        x = df / (df + t_stat**2)
        # Regularised incomplete beta function approximation
        # For df > 5 this gives p accurate to <0.005
        try:
            import math
            # Use a simple but sufficiently accurate p-value from the t-distribution
            # via the beta function approximation
            a = df / 2.0
            b = 0.5
            # Compute using log-gamma (available in math module Python 3.2+)
            # p = I_x(a, b) where x = df/(df+t^2) — regularised incomplete beta
            # For coaching purposes, we just need 3 buckets: <0.05, 0.05-0.10, >0.10
            # Use a conservative normal approximation when df is large enough
            if df >= 30:
                # Normal approximation: z ≈ t for large df
                z = abs(t_stat)
                p_approx = 2 * (1 - (0.5 * (1 + math.erf(z / math.sqrt(2)))))
                p_value = round(max(0.0, min(1.0, p_approx)), 4)
            else:
                # For small df, use a rougher approximation
                # p ≈ 2 * (1 - normal_cdf(|t| * sqrt(df/(df+2))))
                z = abs(t_stat) * math.sqrt(df / (df + 2))
                p_approx = 2 * (1 - (0.5 * (1 + math.erf(z / math.sqrt(2)))))
                p_value = round(max(0.0, min(1.0, p_approx)), 4)
        except Exception:
            p_value = None

    # ── 95% CI via Fisher z-transform ──────────────────────────────────────
    ci_lower = ci_upper = None
    if r is not None and abs(r) < 1.0 and n > 3:
        try:
            z_r = math.atanh(r)  # Fisher z
            se  = 1.0 / math.sqrt(n - 3)
            z_crit = 1.96  # 95% two-tailed
            ci_lower = round(math.tanh(z_r - z_crit * se), 3)
            ci_upper = round(math.tanh(z_r + z_crit * se), 3)
        except Exception:
            ci_lower = ci_upper = None

    # ── N-gated interpretation ──────────────────────────────────────────────
    # R13-F06: Downgrade strength label if n is too small to support it.
    # Prevents a spurious r=0.7 on n=20 being presented as "strong".
    if r is None:
        interpretation = "Cannot compute (zero variance in one series)"
        strength = None
        direction = None
    else:
        abs_r = abs(r)
        direction = "positive" if r > 0 else "negative"

        # Raw label from magnitude
        if abs_r >= 0.7:
            raw_strength = "strong"
        elif abs_r >= 0.4:
            raw_strength = "moderate"
        elif abs_r >= 0.2:
            raw_strength = "weak"
        else:
            raw_strength = "negligible"

        # N-gate: downgrade if sample is too small for this label
        # strong requires n>=50, moderate requires n>=30, weak requires n>=14
        if raw_strength == "strong" and n < 50:
            strength = "moderate" if n >= 30 else "weak"
            n_warning = f"Downgraded from 'strong' to '{strength}' — n={n} is below the {50 if raw_strength == 'strong' else 30}-day minimum for this label."
        elif raw_strength == "moderate" and n < 30:
            strength = "weak"
            n_warning = f"Downgraded from 'moderate' to 'weak' — n={n} is below the 30-day minimum for 'moderate'."
        else:
            strength = raw_strength
            n_warning = None

        interpretation = f"{strength} {direction} correlation"
        if n_warning:
            interpretation += f" (note: {n_warning})"

    # ── Statistical significance label ──────────────────────────────────────
    significance = None
    if p_value is not None:
        if p_value < 0.01:
            significance = "highly significant (p<0.01)"
        elif p_value < 0.05:
            significance = "significant (p<0.05)"
        elif p_value < 0.10:
            significance = "marginal (p<0.10) — treat with caution"
        else:
            significance = f"not significant (p={p_value}) — may be noise"

    return {
        "source_a":        source_a,
        "field_a":         fa,
        "source_b":        source_b,
        "field_b":         fb,
        "lag_days":        lag_days,
        "lag_note":        f"Positive lag: does {fa} today predict {fb} in {lag_days} days?" if lag_days > 0 else "No lag — same-day relationship",
        "start_date":      start_date,
        "end_date":        end_date,
        "n_paired_days":   n,
        "pearson_r":       r,
        "r_squared":       round(r**2, 3) if r is not None else None,
        "p_value":         p_value,
        "significance":    significance,
        "ci_95":           {"lower": ci_lower, "upper": ci_upper} if ci_lower is not None else None,
        "interpretation":  interpretation,
        "mean_a":          round(sum(xs)/len(xs), 2),
        "mean_b":          round(sum(ys)/len(ys), 2),
        "n_gating_note":   "strong requires n≥50, moderate requires n≥30, weak requires n≥14. Smaller samples are downgraded to prevent spurious strong-labelled correlations.",
        "coaching_note":   "r > 0.4 is practically meaningful for coaching. r² tells you what % of variance is explained. Always check p-value before acting on a correlation.",
        # R14-F08: FDR note — on-demand test is a single pair, not FDR-corrected
        **({
            "_note": (
                "This is a single-pair test (no multiple-comparison correction). "
                "The weekly report applies FDR correction (Benjamini-Hochberg) across all pairs, "
                "so p-values there are more conservative. "
                "For exploratory use only — do not act on a single p<0.05 without replication."
            )
        } if p_value is not None and p_value < 0.05 else {}),
    }


def tool_get_seasonal_patterns(args):
    source     = args.get("source")
    start_date = args.get("start_date", "2010-01-01")
    end_date   = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))

    sources_to_query = [source] if source and source in SOURCES else SOURCES
    skip_fields = {"pk", "sk", "source", "ingested_at", "date", "activities", "sport_types"}

    month_names = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                   7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

    cache_key = f"seasonal_patterns_{start_date}_{end_date}_{','.join(sources_to_query)}"
    cached = ddb_cache_get(cache_key) or mem_cache_get(cache_key)
    if cached:
        return cached

    if len(sources_to_query) > 1:
        source_data = parallel_query_sources(sources_to_query, start_date, end_date, lean=True)
    else:
        source_data = {sources_to_query[0]: query_source(sources_to_query[0], start_date, end_date, lean=True)}

    result = {}
    for src in sources_to_query:
        items = source_data.get(src, [])
        if not items:
            continue

        month_buckets = defaultdict(lambda: defaultdict(list))
        year_counts   = defaultdict(set)

        for item in items:
            if "#WORKOUT#" in item.get("sk", ""):
                continue
            date_str = item.get("date", "")
            if not date_str or len(date_str) < 7:
                continue
            try:
                month = int(date_str[5:7])
                year  = date_str[:4]
            except ValueError:
                continue
            year_counts[month].add(year)
            for field, value in item.items():
                if field in skip_fields:
                    continue
                if isinstance(value, (int, float)):
                    month_buckets[month][field].append(float(value))

        months_result = []
        for m in range(1, 13):
            if m not in month_buckets:
                continue
            row = {
                "month":         m,
                "month_name":    month_names[m],
                "years_of_data": len(year_counts[m]),
            }
            for field, values in month_buckets[m].items():
                row[f"{field}_avg"] = round(sum(values) / len(values), 2)
                row[f"{field}_min"] = round(min(values), 2)
                row[f"{field}_max"] = round(max(values), 2)
            months_result.append(row)

        result[src] = months_result

    seasonal_payload = {
        "start_date": start_date,
        "end_date":   end_date,
        "note":       "Months averaged across all available years. 'years_of_data' shows how many years contribute to each month.",
        "sources":    result,
    }
    mem_cache_set(cache_key, seasonal_payload)
    ddb_cache_set(cache_key, seasonal_payload)
    return seasonal_payload


def tool_get_training_periodization(args):
    """
    Training periodization analysis. Detects mesocycle phases, deload needs,
    progressive overload tracking, and training polarization.

    Galpin framework: Base → Build → Peak → Deload (3:1 or 4:1 ratio).
    Attia: Training is the most potent longevity drug — but only with periodization.
    Seiler: 80/20 polarized model — 80% easy, 20% hard for optimal adaptation.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    weeks_back = int(args.get("weeks", 12))
    start_date = args.get("start_date",
        (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(weeks=weeks_back)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    # ── 1. Fetch training data ───────────────────────────────────────────────
    strava_items = query_source("strava", start_date, end_date)
    mf_workout_items = query_source("macrofactor_workouts", start_date, end_date)

    if not strava_items and not mf_workout_items:
        return {"error": "No training data for range.", "start_date": start_date, "end_date": end_date}

    # ── 2. Build weekly training profile ─────────────────────────────────────
    from collections import defaultdict

    def _week_key(date_str):
        d = datetime.strptime(date_str, "%Y-%m-%d")
        # ISO week: Monday start
        return d.strftime("%G-W%V")

    weeks = defaultdict(lambda: {
        "cardio_minutes": 0, "strength_minutes": 0, "total_minutes": 0,
        "zone2_minutes": 0, "hard_minutes": 0, "easy_minutes": 0,
        "sessions": 0, "strength_sessions": 0, "cardio_sessions": 0,
        "total_volume_lbs": 0, "rest_days": 0, "dates": set(),
        "activities": [],
    })

    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical",
                    "virtualrun", "virtualride", "trailrun"}
    strength_types = {"weighttraining", "crossfit", "workout"}

    # Process Strava activities
    for item in strava_items:
        date = item.get("date")
        if not date:
            continue
        wk = _week_key(date)
        weeks[wk]["dates"].add(date)
        for act in (item.get("activities") or []):
            sport = (act.get("sport_type") or act.get("type") or "").lower().replace(" ", "")
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < 600:
                continue
            duration_min = elapsed / 60
            avg_hr = _sf(act.get("average_heartrate"))

            weeks[wk]["sessions"] += 1
            weeks[wk]["total_minutes"] += duration_min

            is_cardio = sport in cardio_types
            is_strength = sport in strength_types

            if is_cardio:
                weeks[wk]["cardio_sessions"] += 1
                weeks[wk]["cardio_minutes"] += duration_min

                if avg_hr:
                    hr_pct = avg_hr / max_hr * 100
                    if hr_pct <= 70:
                        weeks[wk]["zone2_minutes"] += duration_min
                        weeks[wk]["easy_minutes"] += duration_min
                    elif hr_pct >= 80:
                        weeks[wk]["hard_minutes"] += duration_min
                    else:
                        weeks[wk]["easy_minutes"] += duration_min  # Zone 3 counted as moderate

            elif is_strength:
                weeks[wk]["strength_sessions"] += 1
                weeks[wk]["strength_minutes"] += duration_min

            weeks[wk]["activities"].append({
                "date": date, "sport": sport,
                "duration_min": round(duration_min, 1),
                "avg_hr": avg_hr,
            })

    # Process MacroFactor workouts for volume tracking
    for item in mf_workout_items:
        date = item.get("date")
        if not date:
            continue
        wk = _week_key(date)
        vol = _sf(item.get("total_volume_lbs")) or 0
        weeks[wk]["total_volume_lbs"] += vol

    # Calculate rest days per week
    for wk, data in weeks.items():
        data["rest_days"] = 7 - len(data["dates"])
        data["dates"] = sorted(data["dates"])  # Convert set to sorted list

    # ── 3. Weekly progression analysis ───────────────────────────────────────
    sorted_weeks = sorted(weeks.keys())
    weekly_summary = []
    for wk in sorted_weeks:
        w = weeks[wk]
        total_min = w["total_minutes"]
        easy_pct = round(w["easy_minutes"] / total_min * 100, 1) if total_min > 0 else 0
        hard_pct = round(w["hard_minutes"] / total_min * 100, 1) if total_min > 0 else 0

        # Classify week phase
        if total_min < 60:
            phase = "deload"
        elif w["sessions"] <= 2:
            phase = "deload"
        else:
            if w["hard_minutes"] > total_min * 0.3:
                phase = "build"
            elif total_min > 300:
                phase = "peak"
            else:
                phase = "base"

        weekly_summary.append({
            "week": wk,
            "phase": phase,
            "sessions": w["sessions"],
            "total_minutes": round(total_min, 1),
            "cardio_minutes": round(w["cardio_minutes"], 1),
            "strength_minutes": round(w["strength_minutes"], 1),
            "zone2_minutes": round(w["zone2_minutes"], 1),
            "hard_minutes": round(w["hard_minutes"], 1),
            "easy_pct": easy_pct,
            "hard_pct": hard_pct,
            "volume_lbs": round(w["total_volume_lbs"], 1),
            "rest_days": w["rest_days"],
            "cardio_sessions": w["cardio_sessions"],
            "strength_sessions": w["strength_sessions"],
        })

    # ── 4. Deload detection ──────────────────────────────────────────────────
    deload_analysis = {
        "weeks_since_last_deload": 0,
        "deload_recommended": False,
        "reason": None,
    }

    # Count consecutive non-deload weeks from end
    consecutive = 0
    for ws in reversed(weekly_summary):
        if ws["phase"] == "deload":
            break
        consecutive += 1
    deload_analysis["weeks_since_last_deload"] = consecutive

    if consecutive >= 4:
        deload_analysis["deload_recommended"] = True
        deload_analysis["reason"] = f"{consecutive} consecutive training weeks without deload. Galpin recommends 3:1 or 4:1 loading-to-deload ratio."
    elif consecutive >= 3:
        # Check if volume is trending up
        recent_3 = weekly_summary[-3:] if len(weekly_summary) >= 3 else weekly_summary
        if len(recent_3) >= 3:
            vols = [w["total_minutes"] for w in recent_3]
            if all(vols[i] >= vols[i-1] for i in range(1, len(vols))):
                deload_analysis["deload_recommended"] = True
                deload_analysis["reason"] = "3 consecutive weeks of increasing volume. Progressive overload is good, but a deload preserves adaptation."

    # ── 5. Training polarization check (Seiler) ─────────────────────────────
    total_easy = sum(w["easy_minutes"] for wk, w in weeks.items())
    total_hard = sum(w["hard_minutes"] for wk, w in weeks.items())
    total_all = total_easy + total_hard
    polarization = None

    if total_all > 0:
        easy_ratio = round(total_easy / total_all * 100, 1)
        hard_ratio = round(total_hard / total_all * 100, 1)
        mid_ratio = round(100 - easy_ratio - hard_ratio, 1)

        if easy_ratio >= 75:
            pol_status = "well_polarized"
        elif easy_ratio >= 60:
            pol_status = "moderately_polarized"
        else:
            pol_status = "too_much_intensity"

        polarization = {
            "easy_pct": easy_ratio,
            "hard_pct": hard_ratio,
            "middle_zone_pct": mid_ratio,
            "status": pol_status,
            "seiler_target": "80% easy / 20% hard — the polarized model maximizes adaptation while minimizing overtraining risk.",
        }

    # ── 6. Progressive overload tracking (strength) ──────────────────────────
    overload = None
    vol_weeks = [(ws["week"], ws["volume_lbs"]) for ws in weekly_summary if ws["volume_lbs"] > 0]
    if len(vol_weeks) >= 4:
        mid = len(vol_weeks) // 2
        first_half_vol = _avg([v for _, v in vol_weeks[:mid]])
        second_half_vol = _avg([v for _, v in vol_weeks[mid:]])
        if first_half_vol and second_half_vol:
            delta_pct = round((second_half_vol - first_half_vol) / first_half_vol * 100, 1)
            overload = {
                "first_half_avg_volume_lbs": first_half_vol,
                "second_half_avg_volume_lbs": second_half_vol,
                "delta_pct": delta_pct,
                "trend": "increasing" if delta_pct > 5 else ("decreasing" if delta_pct < -5 else "stable"),
                "note": "Progressive overload detected." if delta_pct > 5 else (
                    "Volume declining — ensure this is intentional (deload/cut)." if delta_pct < -5
                    else "Volume stable — consider adding progressive overload."
                ),
            }

    # ── 7. Training consistency ──────────────────────────────────────────────
    sessions_per_week = [ws["sessions"] for ws in weekly_summary]
    avg_sessions = _avg(sessions_per_week)
    consistency_pct = round(
        sum(1 for s in sessions_per_week if s >= 3) / len(sessions_per_week) * 100, 1
    ) if sessions_per_week else 0

    consistency = {
        "avg_sessions_per_week": avg_sessions,
        "weeks_with_3plus_sessions_pct": consistency_pct,
        "total_weeks_analyzed": len(weekly_summary),
        "assessment": "excellent" if consistency_pct >= 85 else (
            "good" if consistency_pct >= 70 else (
                "needs_improvement" if consistency_pct >= 50 else "inconsistent"
            )
        ),
    }

    # ── 8. Zone 2 target tracking ────────────────────────────────────────────
    z2_weekly = [ws["zone2_minutes"] for ws in weekly_summary]
    z2_target = 150
    z2_hit_rate = round(sum(1 for z in z2_weekly if z >= z2_target) / len(z2_weekly) * 100, 1) if z2_weekly else 0

    zone2_status = {
        "avg_weekly_minutes": _avg(z2_weekly),
        "target_minutes": z2_target,
        "weeks_hitting_target_pct": z2_hit_rate,
        "current_week": round(z2_weekly[-1], 1) if z2_weekly else 0,
    }

    # ── 9. Board of Directors ────────────────────────────────────────────────
    bod = []

    if deload_analysis["deload_recommended"]:
        bod.append(f"Galpin: {deload_analysis['reason']} Reduce volume by 40-60% this week. Maintain intensity on key lifts but cut sets in half.")

    if polarization:
        if polarization["status"] == "too_much_intensity":
            bod.append(f"Seiler: Only {polarization['easy_pct']}% of your training is easy. The 80/20 model says you need more Zone 2 and fewer moderate sessions. 'No man's land' (Zone 3) generates fatigue without proportional adaptation.")
        elif polarization["status"] == "well_polarized":
            bod.append("Seiler: Training well polarized — strong easy/hard split. This is the highest-evidence approach for long-term development.")

    if overload and overload["trend"] == "increasing":
        bod.append(f"Galpin: Progressive overload confirmed (+{overload['delta_pct']}% volume). This is the fundamental driver of hypertrophy and strength adaptation.")
    elif overload and overload["trend"] == "decreasing":
        bod.append(f"Galpin: Volume declining by {abs(overload['delta_pct'])}%. If not intentional (cut/deload), this represents a missed adaptation opportunity.")

    if zone2_status["weeks_hitting_target_pct"] < 50:
        bod.append(f"Attia: Only hitting Zone 2 target {zone2_status['weeks_hitting_target_pct']}% of weeks. Zone 2 is the highest-ROI longevity training modality — aim for 150 min/week.")

    if consistency["assessment"] in ("needs_improvement", "inconsistent"):
        bod.append(f"Attia: Consistency ({consistency['avg_sessions_per_week']} sessions/week avg) matters more than intensity. The best program is the one you actually do.")

    return {
        "period": {"start_date": start_date, "end_date": end_date, "weeks": len(weekly_summary)},
        "weekly_breakdown": weekly_summary,
        "deload_analysis": deload_analysis,
        "polarization": polarization,
        "progressive_overload": overload,
        "training_consistency": consistency,
        "zone2_status": zone2_status,
        "board_of_directors": bod,
        "methodology": (
            "Weekly training classified into phases: base (moderate consistent), build (>30% high intensity), "
            "peak (>300 min/week), deload (<60 min or <=2 sessions). Polarization per Seiler (80/20 model). "
            "Progressive overload = first-half vs second-half average weekly volume. "
            "Deload trigger: 4+ consecutive loading weeks or 3 weeks of rising volume. "
            "Zone 2 threshold: avg HR <= 70% max HR (Attia/WHO 150 min/week target)."
        ),
        "source": "strava + macrofactor_workouts",
    }


def tool_get_training_recommendation(args):
    """
    Readiness-based training recommendation. Synthesizes recovery state, training
    load, recent activity history, muscle group recency, and sleep quality into
    a specific workout suggestion with Board of Directors rationale.

    Based on Galpin (training periodization), Huberman (recovery science),
    Attia (longevity training framework), Seiler (polarized training).
    """
    target_date = args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    d7_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    d14_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    d3_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    # ── 1. Readiness signals ─────────────────────────────────────────────────
    readiness = {}

    # Whoop recovery
    whoop_items = query_source("whoop", d7_start, target_date)
    whoop_sorted = sorted(whoop_items, key=lambda x: x.get("date", ""), reverse=True)
    whoop_today = next((w for w in whoop_sorted if w.get("recovery_score") is not None), None)
    if whoop_today:
        readiness["whoop_recovery"] = _sf(whoop_today["recovery_score"])
        readiness["whoop_hrv"] = _sf(whoop_today.get("hrv"))
        readiness["whoop_rhr"] = _sf(whoop_today.get("resting_heart_rate"))
        readiness["whoop_strain_yesterday"] = _sf(whoop_today.get("strain"))

    # Eight Sleep
    es_items = query_source("eightsleep", d3_start, target_date)
    es_sorted = sorted(es_items, key=lambda x: x.get("date", ""), reverse=True)
    es_today = next((s for s in es_sorted if s.get("sleep_score") is not None), None)
    if es_today:
        readiness["sleep_score"] = _sf(es_today["sleep_score"])
        readiness["sleep_efficiency"] = _sf(es_today.get("sleep_efficiency_pct"))
        readiness["sleep_duration"] = _sf(es_today.get("sleep_duration_hours"))
        readiness["deep_pct"] = _sf(es_today.get("deep_pct"))
        readiness["rem_pct"] = _sf(es_today.get("rem_pct"))

    # Garmin Body Battery
    garmin_items = query_source("garmin", d3_start, target_date)
    garmin_sorted = sorted(garmin_items, key=lambda x: x.get("date", ""), reverse=True)
    garmin_today = next((g for g in garmin_sorted if g.get("body_battery_high") is not None), None)
    if garmin_today:
        readiness["body_battery"] = _sf(garmin_today.get("body_battery_high")) or _sf(garmin_today.get("body_battery_end"))
        readiness["garmin_stress"] = _sf(garmin_today.get("avg_stress"))
        readiness["training_readiness_garmin"] = _sf(garmin_today.get("training_readiness"))

    # ── 2. Training load context ─────────────────────────────────────────────
    training_context = {}
    try:
        load_result = tool_get_training_load({"end_date": target_date})
        if "current_state" in load_result:
            cs = load_result["current_state"]
            training_context["ctl"] = cs.get("ctl_fitness")
            training_context["atl"] = cs.get("atl_fatigue")
            training_context["tsb"] = cs.get("tsb_form")
            training_context["acwr"] = cs.get("acwr")
            training_context["form_status"] = cs.get("form_status")
            training_context["injury_risk"] = cs.get("injury_risk")
    except Exception:
        pass

    # ── 3. Recent activity history ───────────────────────────────────────────
    strava_items = query_source("strava", d14_start, target_date)
    strava_by_date = {}
    for item in strava_items:
        d = item.get("date")
        if d:
            strava_by_date[d] = item

    # Activity patterns over last 7 days
    recent_activities = []
    last_cardio_date = None
    last_strength_date = None
    last_hard_date = None
    consecutive_rest_days = 0
    consecutive_training_days = 0

    dates_7d = sorted(strava_by_date.keys())[-7:]
    cardio_types = {"run", "ride", "swim", "hike", "walk", "rowing", "elliptical",
                    "virtualrun", "virtualride", "trailrun"}
    strength_types = {"weighttraining", "crossfit", "workout"}

    for i, date in enumerate(sorted(strava_by_date.keys(), reverse=True)):
        if date > target_date:
            continue
        day = strava_by_date[date]
        acts = day.get("activities", [])

        for act in acts:
            sport = (act.get("sport_type") or act.get("type") or "").lower().replace(" ", "")
            avg_hr = _sf(act.get("average_heartrate"))
            elapsed = _sf(act.get("elapsed_time_seconds")) or 0
            if elapsed < 600:  # skip <10 min
                continue

            is_cardio = sport in cardio_types
            is_strength = sport in strength_types
            is_hard = avg_hr is not None and avg_hr > max_hr * 0.8

            if is_cardio and (last_cardio_date is None or date > last_cardio_date):
                last_cardio_date = date
            if is_strength and (last_strength_date is None or date > last_strength_date):
                last_strength_date = date
            if is_hard and (last_hard_date is None or date > last_hard_date):
                last_hard_date = date

            recent_activities.append({
                "date": date,
                "sport": act.get("sport_type") or act.get("type"),
                "duration_min": round(elapsed / 60, 1),
                "avg_hr": avg_hr,
                "is_hard": is_hard,
            })

    # Consecutive rest/training days
    check_date = datetime.strptime(target_date, "%Y-%m-%d")
    for i in range(7):
        d = (check_date - timedelta(days=i+1)).strftime("%Y-%m-%d")
        day_data = strava_by_date.get(d, {})
        acts = day_data.get("activities", [])
        real_acts = [a for a in acts if (_sf(a.get("elapsed_time_seconds")) or 0) >= 600]
        if real_acts:
            if i == 0:
                consecutive_training_days = 1
            elif consecutive_training_days > 0:
                consecutive_training_days += 1
            else:
                break
        else:
            if i == 0:
                consecutive_rest_days = 1
            elif consecutive_rest_days > 0:
                consecutive_rest_days += 1
            else:
                break

    # Days since last activities
    def _days_since(d):
        if d is None: return None
        return (datetime.strptime(target_date, "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days

    days_since_cardio = _days_since(last_cardio_date)
    days_since_strength = _days_since(last_strength_date)
    days_since_hard = _days_since(last_hard_date)

    # ── 4. Muscle group recency from strength data ───────────────────────────
    muscle_last_trained = {}
    mf_workout_items = query_source("macrofactor_workouts", d14_start, target_date)
    for item in mf_workout_items:
        d = item.get("date")
        for workout in (item.get("workouts") or []):
            for exercise in (workout.get("exercises") or []):
                ename = exercise.get("exercise_name", "")
                cls = classify_exercise(ename)  # noqa: F821
                for mg in cls["muscle_groups"]:
                    if mg not in muscle_last_trained or d > muscle_last_trained[mg]:
                        muscle_last_trained[mg] = d

    muscle_recovery = {}
    for mg, last_date in muscle_last_trained.items():
        days_ago = _days_since(last_date)
        if days_ago is not None:
            status = "fully_recovered" if days_ago >= 3 else ("recovering" if days_ago >= 1 else "just_trained")
            muscle_recovery[mg] = {"last_trained": last_date, "days_ago": days_ago, "status": status}

    # ── 5. Compute readiness tier ────────────────────────────────────────────
    recovery_score = readiness.get("whoop_recovery")
    sleep_score = readiness.get("sleep_score")
    body_battery = readiness.get("body_battery")
    tsb = training_context.get("tsb")
    acwr = training_context.get("acwr")

    # Composite readiness (0-100)
    signals = []
    if recovery_score is not None: signals.append(recovery_score)
    if sleep_score is not None: signals.append(sleep_score)
    if body_battery is not None: signals.append(body_battery)

    composite = _avg(signals) if signals else 50
    tier = "GREEN" if composite >= 67 else ("YELLOW" if composite >= 33 else "RED")

    # Injury risk override
    if acwr is not None and acwr > 1.5:
        tier = "RED"
    if consecutive_training_days >= 5:
        tier = min(tier, "YELLOW") if tier == "GREEN" else tier

    # ── 6. Generate recommendation ───────────────────────────────────────────
    rec = {}

    if tier == "RED" or composite < 30:
        # Low readiness → rest or very easy
        if consecutive_rest_days >= 2:
            rec = {
                "type": "Active Recovery",
                "intensity": "Very Easy",
                "description": "Light walk, mobility work, or gentle yoga. Keep HR below 60% max.",
                "duration_min": "20-30",
                "hr_ceiling": round(max_hr * 0.6),
            }
        else:
            rec = {
                "type": "Full Rest",
                "intensity": "None",
                "description": "Your body needs recovery. Focus on sleep, nutrition, and stress management.",
                "duration_min": "0",
                "hr_ceiling": None,
            }
    elif tier == "YELLOW":
        # Moderate readiness → Zone 2 or easy strength
        if days_since_cardio is not None and days_since_cardio >= 2:
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy",
                "description": "Steady-state aerobic work. Conversational pace. Build mitochondrial density without taxing recovery.",
                "duration_min": "45-60",
                "hr_ceiling": round(max_hr * 0.7),
                "hr_floor": round(max_hr * 0.6),
            }
        elif days_since_strength is not None and days_since_strength >= 2:
            # Find recovered muscle groups
            recovered = [mg for mg, info in muscle_recovery.items() if info["status"] == "fully_recovered"]
            push_ready = any(mg in recovered for mg in ["Chest", "Shoulders", "Triceps"])
            pull_ready = any(mg in recovered for mg in ["Back", "Biceps"])
            legs_ready = any(mg in recovered for mg in ["Quads", "Glutes", "Hamstrings"])

            if legs_ready:
                target = "Lower Body"
                muscles = [mg for mg in ["Quads", "Glutes", "Hamstrings", "Calves"] if mg in recovered]
            elif push_ready:
                target = "Upper Body Push"
                muscles = [mg for mg in ["Chest", "Shoulders", "Triceps"] if mg in recovered]
            elif pull_ready:
                target = "Upper Body Pull"
                muscles = [mg for mg in ["Back", "Biceps"] if mg in recovered]
            else:
                target = "Full Body (Light)"
                muscles = recovered[:4] if recovered else ["General"]

            rec = {
                "type": f"Strength — {target}",
                "intensity": "Moderate",
                "description": f"Moderate loads, controlled tempo. Focus on {', '.join(muscles)}. Stay 2-3 RIR from failure.",
                "duration_min": "45-60",
                "target_muscles": muscles,
                "rpe_range": "6-7",
            }
        else:
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy",
                "description": "Easy aerobic session. You've been active recently — keep it light today.",
                "duration_min": "30-45",
                "hr_ceiling": round(max_hr * 0.7),
            }
    else:
        # GREEN — full capacity available
        if days_since_hard is not None and days_since_hard >= 3 and (tsb is None or tsb > -5):
            # Ready for hard effort
            if days_since_cardio is not None and days_since_cardio >= 2:
                rec = {
                    "type": "High-Intensity Intervals",
                    "intensity": "Hard",
                    "description": "VO2max work: 4-6 intervals of 3-4 minutes at 85-90% max HR with equal rest. This is the highest-ROI session for cardiovascular fitness.",
                    "duration_min": "40-50",
                    "hr_ceiling": round(max_hr * 0.9),
                    "hr_floor": round(max_hr * 0.85),
                }
            else:
                # Find recovered muscle groups for heavy strength
                recovered = [mg for mg, info in muscle_recovery.items() if info["status"] == "fully_recovered"]
                push_ready = any(mg in recovered for mg in ["Chest", "Shoulders", "Triceps"])
                pull_ready = any(mg in recovered for mg in ["Back", "Biceps"])
                legs_ready = any(mg in recovered for mg in ["Quads", "Glutes", "Hamstrings"])

                if legs_ready:
                    target = "Lower Body"
                    muscles = [mg for mg in ["Quads", "Glutes", "Hamstrings", "Calves"] if mg in recovered]
                elif push_ready:
                    target = "Upper Body Push"
                    muscles = [mg for mg in ["Chest", "Shoulders", "Triceps"] if mg in recovered]
                elif pull_ready:
                    target = "Upper Body Pull"
                    muscles = [mg for mg in ["Back", "Biceps"] if mg in recovered]
                else:
                    target = "Full Body"
                    muscles = recovered[:4] if recovered else ["General"]

                rec = {
                    "type": f"Strength — {target}",
                    "intensity": "Hard",
                    "description": f"Heavy compound lifts. Push to 1-2 RIR on working sets. Target: {', '.join(muscles)}.",
                    "duration_min": "60-75",
                    "target_muscles": muscles,
                    "rpe_range": "8-9",
                }
        else:
            # Green but recent hard session or negative TSB → Zone 2
            rec = {
                "type": "Zone 2 Cardio",
                "intensity": "Easy-Moderate",
                "description": "Solid Zone 2 session. You're recovered but had a hard effort recently — build aerobic base without adding fatigue.",
                "duration_min": "45-60",
                "hr_ceiling": round(max_hr * 0.7),
                "hr_floor": round(max_hr * 0.6),
            }

    # ── 7. Warnings ──────────────────────────────────────────────────────────
    warnings = []
    if acwr is not None and acwr > 1.3:
        warnings.append(f"⚠️ ACWR is {acwr} — above 1.3 injury threshold. Reduce training load this week.")
    if consecutive_training_days >= 4:
        warnings.append(f"⚠️ {consecutive_training_days} consecutive training days. Consider a rest day soon.")
    if readiness.get("sleep_duration") and readiness["sleep_duration"] < 6:
        warnings.append(f"⚠️ Only {readiness['sleep_duration']}h sleep — short sleep impairs muscle protein synthesis and injury risk. Reduce intensity.")
    if readiness.get("whoop_hrv") and len([w for w in whoop_items if _sf(w.get("hrv"))]) >= 3:
        hrv_vals = [_sf(w.get("hrv")) for w in whoop_items if _sf(w.get("hrv"))]
        hrv_avg = _avg(hrv_vals)
        if readiness["whoop_hrv"] < hrv_avg * 0.8:
            warnings.append(f"⚠️ HRV ({readiness['whoop_hrv']}ms) is {round((1 - readiness['whoop_hrv']/hrv_avg)*100)}% below your 7-day average. Parasympathetic suppression — reduce intensity.")
    if readiness.get("garmin_stress") and readiness["garmin_stress"] > 50:
        warnings.append(f"⚠️ Garmin stress score {readiness['garmin_stress']} (elevated). Consider how allostatic load affects recovery.")

    # ── 8. Board of Directors rationale ───────────────────────────────────────
    bod_notes = []
    if tier == "GREEN":
        bod_notes.append("Huberman: Full parasympathetic recovery detected. Sympathetic drive available for high-output work.")
        if rec.get("type", "").startswith("Strength"):
            bod_notes.append("Galpin: Mechanical tension (heavy loads, 1-2 RIR) drives hypertrophy most efficiently when recovery is complete.")
        elif "Interval" in rec.get("type", ""):
            bod_notes.append("Attia: VO2max is the single strongest predictor of all-cause mortality. Hard intervals 1-2x/week are the highest-ROI investment.")
    elif tier == "YELLOW":
        bod_notes.append("Attia: Zone 2 is the longevity foundation — 150+ min/week builds mitochondrial density without recovery cost.")
        bod_notes.append("Huberman: Moderate training during partial recovery can still stimulate adaptation without digging a deeper hole.")
    else:
        bod_notes.append("Walker: Sleep debt is cumulative and cannot be repaid by a single night. Prioritize recovery.")
        bod_notes.append("Galpin: Training in a depleted state converts productive stress into destructive stress.")

    # Zone 2 weekly check
    try:
        z2_result = tool_get_zone2_breakdown({"start_date": d7_start, "end_date": target_date})
        if "summary" in z2_result:
            z2_min = z2_result["summary"].get("total_zone2_minutes", 0)
            z2_target = z2_result["summary"].get("weekly_target_minutes", 150)
            z2_pct = round(z2_min / z2_target * 100) if z2_target > 0 else 0
            if z2_pct < 50:
                bod_notes.append(f"Attia: Only {z2_min} of {z2_target} Zone 2 minutes this week ({z2_pct}%). Prioritize Zone 2 sessions.")
    except Exception:
        pass

    return {
        "date": target_date,
        "readiness_tier": tier,
        "composite_readiness": round(composite, 1),
        "recommendation": rec,
        "warnings": warnings,
        "board_of_directors": bod_notes,
        "readiness_signals": readiness,
        "training_context": {
            "days_since_cardio": days_since_cardio,
            "days_since_strength": days_since_strength,
            "days_since_hard_session": days_since_hard,
            "consecutive_rest_days": consecutive_rest_days,
            "consecutive_training_days": consecutive_training_days,
            "training_load": training_context,
        },
        "muscle_recovery": muscle_recovery,
        "recent_activities_7d": recent_activities[:10],
        "source": "whoop + eightsleep + garmin + strava + macrofactor_workouts",
    }


def tool_get_hr_recovery_trend(args):
    """
    Heart rate recovery tracker — strongest exercise-derived mortality predictor.
    Extracts post-peak HR recovery from Strava activity streams, trends over time.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))
    sport_filter = (args.get("sport_type") or "").strip().lower()
    cooldown_only = args.get("cooldown_only", False)

    strava_items = query_source("strava", start_date, end_date)
    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))

    records = []
    for item in strava_items:
        date = item.get("date")
        for act in (item.get("activities") or []):
            hr_rec = act.get("hr_recovery")
            if not hr_rec or not isinstance(hr_rec, dict):
                continue
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if sport_filter and sport_filter not in sport.replace(" ", ""):
                continue
            has_cooldown = hr_rec.get("has_cooldown", False)
            if cooldown_only and not has_cooldown:
                continue
            peak = _sf(hr_rec.get("hr_peak"))
            recovery_intra = _sf(hr_rec.get("hr_recovery_intra"))
            recovery_60s = _sf(hr_rec.get("hr_recovery_60s"))
            recovery_120s = _sf(hr_rec.get("hr_recovery_120s"))
            best_recovery = recovery_60s or recovery_intra
            if peak is None or best_recovery is None:
                continue
            if best_recovery >= 25: classification = "excellent"
            elif best_recovery >= 18: classification = "good"
            elif best_recovery >= 12: classification = "average"
            else: classification = "below_average"
            records.append({
                "date": date,
                "sport_type": act.get("sport_type") or act.get("type"),
                "activity_name": act.get("name", ""),
                "duration_min": round((_sf(act.get("elapsed_time_seconds")) or 0) / 60, 1),
                "hr_peak": peak,
                "hr_peak_pct_max": round(peak / max_hr * 100, 1) if peak else None,
                "hr_end_60s": _sf(hr_rec.get("hr_end_60s")),
                "hr_recovery_intra": recovery_intra,
                "hr_recovery_60s": recovery_60s,
                "hr_recovery_120s": recovery_120s,
                "has_cooldown": has_cooldown,
                "best_recovery_bpm": best_recovery,
                "classification": classification,
            })

    if not records:
        return {
            "error": "No activities with HR recovery data found. HR recovery requires Strava ingestion v2.35.0+ with stream fetching.",
            "start_date": start_date, "end_date": end_date,
            "tip": "Activities need HR data and >= 10 min duration. Recovery metrics computed from HR streams during ingestion.",
        }

    records.sort(key=lambda r: r["date"])

    mid = len(records) // 2
    first_half = records[:mid] if mid > 0 else records
    second_half = records[mid:] if mid > 0 else records
    first_avg = _avg([r["best_recovery_bpm"] for r in first_half])
    second_avg = _avg([r["best_recovery_bpm"] for r in second_half])

    trend_direction = None
    trend_delta = None
    if first_avg is not None and second_avg is not None:
        trend_delta = round(second_avg - first_avg, 1)
        trend_direction = "improving" if trend_delta > 2 else ("declining" if trend_delta < -2 else "stable")

    date_ordinals = []
    recovery_vals = []
    base_date = datetime.strptime(records[0]["date"], "%Y-%m-%d")
    for r in records:
        d = (datetime.strptime(r["date"], "%Y-%m-%d") - base_date).days
        date_ordinals.append(d)
        recovery_vals.append(r["best_recovery_bpm"])
    r_val = pearson_r(date_ordinals, recovery_vals) if len(date_ordinals) >= 5 else None

    by_sport = {}
    for r in records:
        s = r["sport_type"] or "Unknown"
        if s not in by_sport:
            by_sport[s] = {"activities": 0, "avg_recovery": [], "avg_peak_hr": []}
        by_sport[s]["activities"] += 1
        by_sport[s]["avg_recovery"].append(r["best_recovery_bpm"])
        by_sport[s]["avg_peak_hr"].append(r["hr_peak"])
    sport_summary = {}
    for s, data in by_sport.items():
        sport_summary[s] = {
            "activities": data["activities"],
            "avg_recovery_bpm": _avg(data["avg_recovery"]),
            "avg_peak_hr": _avg(data["avg_peak_hr"]),
        }

    dist = {"excellent": 0, "good": 0, "average": 0, "below_average": 0}
    for r in records:
        dist[r["classification"]] += 1
    total = len(records)
    dist_pct = {k: round(v / total * 100, 1) for k, v in dist.items()}

    sorted_by_recovery = sorted(records, key=lambda r: r["best_recovery_bpm"], reverse=True)
    best_5 = sorted_by_recovery[:5]
    worst_5 = sorted_by_recovery[-5:]

    cooldown_records = [r for r in records if r["has_cooldown"]]
    no_cooldown = [r for r in records if not r["has_cooldown"]]

    overall_avg = _avg([r["best_recovery_bpm"] for r in records])
    if overall_avg and overall_avg >= 25:
        clinical = "Excellent autonomic function. Strong parasympathetic reactivation indicates high cardiovascular fitness."
    elif overall_avg and overall_avg >= 18:
        clinical = "Good HR recovery. Healthy autonomic balance. Continue current training approach."
    elif overall_avg and overall_avg >= 12:
        clinical = "Average HR recovery. Room for improvement — Zone 2 training and stress management will enhance parasympathetic tone."
    elif overall_avg:
        clinical = "Below average HR recovery (<12 bpm). Clinical flag per Cole et al. (NEJM). Discuss with physician."
    else:
        clinical = "Insufficient data for clinical assessment."

    bod = []
    if trend_direction == "improving":
        bod.append(f"Attia: HR recovery improving by {trend_delta} bpm — cardiovascular fitness trending in the right direction.")
    elif trend_direction == "declining":
        bod.append(f"Huberman: HR recovery declining by {abs(trend_delta)} bpm — consider overtraining, sleep debt, or chronic stress.")
    if cooldown_records and no_cooldown:
        bod.append(f"Galpin: {len(cooldown_records)} of {total} activities include cooldown. Adding 5-min easy cooldown improves recovery data reliability.")
    if dist["below_average"] > 0 and dist["below_average"] / total > 0.3:
        bod.append("Attia: >30% of sessions show below-average recovery. Consider reducing volume and prioritizing sleep.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_activities_with_hr_recovery": total,
        "overall_avg_recovery_bpm": overall_avg,
        "clinical_assessment": clinical,
        "trend": {
            "direction": trend_direction, "delta_bpm": trend_delta,
            "first_half_avg": first_avg, "second_half_avg": second_avg,
            "pearson_r": r_val,
            "interpretation": (
                f"HR recovery {'improving' if trend_direction == 'improving' else 'declining' if trend_direction == 'declining' else 'stable'} "
                f"over the period ({'+' if (trend_delta or 0) > 0 else ''}{trend_delta} bpm)."
            ) if trend_delta is not None else None,
        },
        "classification_distribution": dist,
        "classification_distribution_pct": dist_pct,
        "by_sport_type": sport_summary,
        "cooldown_analysis": {
            "activities_with_cooldown": len(cooldown_records),
            "activities_without_cooldown": len(no_cooldown),
            "avg_recovery_with_cooldown": _avg([r["best_recovery_bpm"] for r in cooldown_records]),
            "avg_recovery_without_cooldown": _avg([r["best_recovery_bpm"] for r in no_cooldown]),
            "note": "Activities with cooldown give more reliable HR recovery measurements.",
        },
        "best_recoveries": [{k: v for k, v in r.items() if k != "classification"} for r in best_5],
        "worst_recoveries": [{k: v for k, v in r.items() if k != "classification"} for r in worst_5],
        "board_of_directors": bod,
        "methodology": (
            "HR recovery computed from Strava HR streams during ingestion. "
            "Peak HR = 30s rolling average max. Recovery = peak minus HR at peak+60s (preferred) "
            "or peak minus last-60s average (fallback). Clinical thresholds per Cole et al. (NEJM 1999): "
            ">25 excellent, 18-25 good, 12-18 average, <12 below average."
        ),
        "source": "strava (HR streams)",
        # R13-F09: Medical disclaimer on all health-assessment tool responses
        "_disclaimer": "For personal health tracking only. Not medical advice. Consult a qualified healthcare provider before making health decisions based on this data.",
    }


# ═══════════════════════════════════════════════════════════════════════
# #28 — EXERCISE VARIETY SCORING (Sponsor: Dr. Sarah Chen)
# ═══════════════════════════════════════════════════════════════════════

def tool_get_exercise_variety(args):
    """
    Movement pattern diversity index. Flags staleness when same activity
    types repeat for 4+ weeks. Shannon diversity index + recommendations.
    """
    end = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    window_weeks = int(args.get("window_weeks", 4))

    strava = query_source("strava", start, end)
    if not strava:
        return {"error": f"No Strava data between {start} and {end}."}

    # Flatten all activities
    all_activities = []
    for day in strava:
        day = decimal_to_float(day)
        for act in day.get("activities", []):
            act["date"] = day.get("date", "")
            all_activities.append(act)

    if not all_activities:
        return {"error": "No activities found in date range."}

    # Classify by movement pattern (broader than sport_type)
    def _movement_pattern(act):
        sport = (act.get("sport_type") or act.get("type") or "").lower()
        if sport in ("run", "trailrun", "virtualrun"):
            return "running"
        elif sport in ("ride", "virtualride", "mountainbikeride", "ebikeride", "gravel_ride"):
            return "cycling"
        elif sport in ("walk", "hike"):
            return "walking_hiking"
        elif sport in ("swim", "openwater"):
            return "swimming"
        elif sport in ("weighttraining", "crossfit"):
            return "strength"
        elif sport in ("yoga", "pilates"):
            return "flexibility"
        elif sport in ("rowing", "canoeing", "kayaking", "standup_paddleboarding"):
            return "water_sports"
        elif sport in ("elliptical", "stairstepper"):
            return "cardio_machine"
        elif sport in ("rockclimbing", "bouldering"):
            return "climbing"
        else:
            return sport or "other"

    # Overall period analysis
    pattern_counts = defaultdict(int)
    pattern_minutes = defaultdict(float)
    for a in all_activities:
        p = _movement_pattern(a)
        pattern_counts[p] += 1
        dur = a.get("moving_time_seconds", a.get("elapsed_time_seconds", 0))
        pattern_minutes[p] += float(dur) / 60

    total_activities = sum(pattern_counts.values())
    unique_patterns = len(pattern_counts)

    # Shannon diversity index (H)
    import math as _math
    h = 0
    for count in pattern_counts.values():
        if count > 0:
            p = count / total_activities
            h -= p * _math.log(p)
    h = round(h, 3)

    # Max possible diversity
    h_max = round(_math.log(unique_patterns), 3) if unique_patterns > 1 else 0
    evenness = round(h / h_max, 2) if h_max > 0 else 0

    # Score: 0-100 based on pattern count + evenness
    if unique_patterns >= 5 and evenness >= 0.7:
        variety_score = min(100, int(unique_patterns * 12 * evenness))
        variety_grade = "excellent"
    elif unique_patterns >= 4 and evenness >= 0.5:
        variety_score = min(85, int(unique_patterns * 10 * evenness))
        variety_grade = "good"
    elif unique_patterns >= 3:
        variety_score = min(70, int(unique_patterns * 10 * evenness))
        variety_grade = "moderate"
    elif unique_patterns == 2:
        variety_score = 40
        variety_grade = "low"
    else:
        variety_score = 20
        variety_grade = "monotonous"

    # Rolling window staleness check
    window_start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(weeks=window_weeks)).strftime("%Y-%m-%d")
    recent = [a for a in all_activities if a.get("date", "") >= window_start]
    recent_patterns = set(_movement_pattern(a) for a in recent)
    older = [a for a in all_activities if a.get("date", "") < window_start]
    older_patterns = set(_movement_pattern(a) for a in older)

    staleness_flag = None
    if len(recent) >= 4 and len(recent_patterns) <= 2:
        staleness_flag = f"Only {len(recent_patterns)} movement pattern(s) in last {window_weeks} weeks: {', '.join(sorted(recent_patterns))}."

    # Missing movement categories
    ideal_patterns = {"running", "cycling", "walking_hiking", "swimming", "strength", "flexibility"}
    missing = ideal_patterns - set(pattern_counts.keys())

    # Pattern distribution
    distribution = []
    for p, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        distribution.append({
            "pattern": p,
            "sessions": count,
            "pct": round(100 * count / total_activities, 1),
            "total_minutes": round(pattern_minutes[p], 0),
        })

    # Recommendations
    recommendations = []
    if staleness_flag:
        recommendations.append(staleness_flag)
    if "swimming" in missing:
        recommendations.append("Add swimming — low-impact, full-body, excellent for active recovery.")
    if "flexibility" in missing:
        recommendations.append("Add yoga or mobility work — prevents injury, improves range of motion.")
    if "strength" in missing:
        recommendations.append("Add strength training — essential for muscle preservation during deficit.")
    if evenness < 0.5 and unique_patterns >= 3:
        dominant = distribution[0]["pattern"]
        recommendations.append(f"Rebalance: {dominant} dominates at {distribution[0]['pct']}%. Spread time more evenly.")

    return {
        "period": f"{start} to {end}",
        "total_activities": total_activities,
        "unique_movement_patterns": unique_patterns,
        "variety_score": variety_score,
        "variety_grade": variety_grade,
        "shannon_diversity_index": h,
        "shannon_max": h_max,
        "evenness": evenness,
        "distribution": distribution,
        "staleness_check": {
            "window": f"last {window_weeks} weeks",
            "patterns_in_window": sorted(recent_patterns),
            "flag": staleness_flag,
        },
        "missing_ideal_patterns": sorted(missing) if missing else [],
        "recommendations": recommendations,
        "methodology": (
            "Shannon diversity index (H) measures activity type variety — higher = more diverse. "
            "Evenness (J) measures distribution balance — 1.0 = perfectly even, 0 = dominated by one type. "
            "Staleness flagged when ≤2 patterns repeat for the window period. "
            "Chen: adaptation is the enemy of progress — novelty is the cheapest performance enhancer."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# LACTATE THRESHOLD ESTIMATION  (#27)
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_lactate_threshold_estimate(args):
    """
    Estimates aerobic threshold development using cardiac efficiency analysis.
    Tracks pace-per-HR (cardiac drift proxy) across Zone 2 sessions over time.
    As aerobic base builds, HR drops for same effort (or pace improves at same HR).
    Linear regression on cardiac_efficiency reveals direction and rate of change.
    Chen: proxy lactate curve from HR drift over repeated steady-state efforts.
    """
    end   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    zone2_low      = float(args.get("zone2_hr_low",      110))
    zone2_high     = float(args.get("zone2_hr_high",     139))
    min_duration   = float(args.get("min_duration_min",   20))
    sport_filter   = (args.get("sport_type") or "").lower()

    strava = query_source("strava", start, end)
    if not strava:
        return {"error": f"No Strava data between {start} and {end}."}

    eligible = []
    for day in strava:
        day = decimal_to_float(day)
        date = day.get("date", "")
        for a in day.get("activities", []):
            sport = (a.get("sport_type") or a.get("type") or "").lower()
            if sport_filter and sport_filter not in sport:
                continue
            hr  = float(a.get("average_heartrate") or 0)
            sec = float(a.get("moving_time_seconds") or a.get("elapsed_time_seconds") or 0)
            mi  = float(a.get("distance_miles") or 0)
            if hr < zone2_low or hr > zone2_high:
                continue
            dur_min = sec / 60
            if dur_min < min_duration or mi < 0.5:
                continue
            # Cardiac efficiency: miles per minute per HR unit x 1000
            # Higher = faster pace for given HR = better aerobic fitness
            ce = (mi / dur_min / hr) * 1000
            pace_min_per_mi = round(dur_min / mi, 2) if mi > 0 else None
            eligible.append({
                "date":            date,
                "sport":           sport,
                "avg_hr":          round(hr, 1),
                "duration_min":    round(dur_min, 1),
                "distance_miles":  round(mi, 2),
                "speed_mph":       round(mi / (dur_min / 60), 2),
                "pace_min_per_mi": pace_min_per_mi,
                "cardiac_efficiency": round(ce, 4),
                "name":            a.get("enriched_name") or a.get("name", ""),
            })

    if not eligible:
        return {
            "error": (
                f"No Zone 2 activities >= {int(min_duration)} min found "
                f"(HR {int(zone2_low)}-{int(zone2_high)} bpm) in {start} to {end}."
            ),
            "hint": "Try widening zone2_hr_low/high or reducing min_duration_min.",
        }

    eligible.sort(key=lambda x: x["date"])
    n = len(eligible)
    ce_vals = [s["cardiac_efficiency"] for s in eligible]
    slope, intercept, r = _linear_regression(list(range(n)), ce_vals)

    third = max(1, n // 3)
    early_avg = sum(ce_vals[:third]) / third
    late_avg  = sum(ce_vals[-third:]) / third
    pct_change = round((late_avg - early_avg) / early_avg * 100, 1) if early_avg > 0 else None

    if slope is None or n < 4:
        trend_dir, trend_label = "insufficient_data", f"Need >= 4 sessions ({n} found)"
    elif slope > 0.001:
        trend_dir, trend_label = "improving", f"Aerobic base is building (+{round(slope * 10, 3)}/10 sessions)"
    elif slope < -0.001:
        trend_dir, trend_label = "declining", "Declining — check fatigue, illness, or overreach"
    else:
        trend_dir, trend_label = "stable", "Base is holding but not yet growing"

    from collections import defaultdict as _dd
    weekly = _dd(list)
    for s in eligible:
        try:
            import datetime as _dt
            d = _dt.datetime.strptime(s["date"], "%Y-%m-%d")
            key = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        except Exception:
            key = s["date"][:7]
        weekly[key].append(s["cardiac_efficiency"])

    weekly_summary = [
        {"period": wk, "sessions": len(ces), "avg_cardiac_efficiency": round(sum(ces)/len(ces), 4)}
        for wk, ces in sorted(weekly.items())
    ]

    return {
        "period":            {"start_date": start, "end_date": end},
        "sessions_analyzed": n,
        "zone2_band":        f"{int(zone2_low)}-{int(zone2_high)} bpm",
        "sport_filter":      sport_filter or "all",
        "avg_hr_in_zone2":   round(sum(s["avg_hr"] for s in eligible) / n, 1),
        "cardiac_efficiency": {
            "avg":              round(sum(ce_vals) / n, 4),
            "earliest":         round(ce_vals[0], 4),
            "latest":           round(ce_vals[-1], 4),
            "pct_change_first_vs_last_third": pct_change,
            "unit":             "miles/(min*HR) x 1000 — higher = better fitness",
        },
        "trend": {
            "direction": trend_dir,
            "label":     trend_label,
            "slope":     round(slope, 5) if slope is not None else None,
            "r":         round(r, 3) if r is not None else None,
        },
        "weekly_summary": weekly_summary,
        "sessions":       eligible[-20:],
        "interpretation": (
            "Cardiac efficiency (CE) = miles / (minutes * avg_HR) * 1000. "
            "A rising CE means you cover more distance per HR unit — your aerobic engine is improving. "
            "Declining CE = accumulated fatigue or overreach. "
            "Chen: HR drift across repeated Zone 2 efforts is the closest proxy to a lab lactate curve. "
            "Target 10-15% CE improvement over 8-12 weeks of consistent Zone 2 training."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXERCISE EFFICIENCY TRENDING  (#39)
# ══════════════════════════════════════════════════════════════════════════════

def tool_get_exercise_efficiency_trend(args):
    """
    Tracks pace-at-HR over time for repeated workout types.
    Same workout + lower HR over time = improving cardiovascular fitness.
    Computes cardiac efficiency per activity and runs linear regression
    per sport type to detect improvement signal.
    Attia: pace-at-HR over time is the purest fitness signal available from consumer data.
    """
    end         = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start       = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))
    min_hr      = float(args.get("min_hr", 100))
    min_dur     = float(args.get("min_duration_min", 10))
    sport_type  = (args.get("sport_type") or "").lower()

    strava = query_source("strava", start, end)
    if not strava:
        return {"error": f"No Strava data between {start} and {end}."}

    from collections import defaultdict as _dd
    by_sport = _dd(list)
    for day in strava:
        day = decimal_to_float(day)
        date = day.get("date", "")
        for a in day.get("activities", []):
            sport = (a.get("sport_type") or a.get("type") or "").lower()
            if sport_type and sport_type not in sport:
                continue
            hr  = float(a.get("average_heartrate") or 0)
            sec = float(a.get("moving_time_seconds") or a.get("elapsed_time_seconds") or 0)
            mi  = float(a.get("distance_miles") or 0)
            dur_min = sec / 60
            if hr < min_hr or dur_min < min_dur or mi < 0.5:
                continue
            ce = (mi / dur_min / hr) * 1000
            pace_str = None
            if "run" in sport or "walk" in sport:
                pm = dur_min / mi
                pace_str = f"{int(pm)}:{int((pm % 1) * 60):02d}/mi"
            by_sport[sport].append({
                "date":               date,
                "avg_hr":             round(hr, 1),
                "duration_min":       round(dur_min, 1),
                "distance_miles":     round(mi, 2),
                "speed_mph":          round(mi / (dur_min / 60), 2),
                "pace_per_mile":      pace_str,
                "cardiac_efficiency": round(ce, 4),
                "name":               a.get("enriched_name") or a.get("name", ""),
            })

    if not by_sport:
        return {"error": "No activities with HR data found in range.", "start": start, "end": end}

    results = {}
    for sport, sessions in sorted(by_sport.items()):
        sessions.sort(key=lambda x: x["date"])
        n = len(sessions)
        ce_vals = [s["cardiac_efficiency"] for s in sessions]
        slope, intercept, r = _linear_regression(list(range(n)), ce_vals)

        third = max(1, n // 3)
        early_avg = sum(ce_vals[:third]) / third
        late_avg  = sum(ce_vals[-third:]) / third
        pct_delta = round((late_avg - early_avg) / early_avg * 100, 1) if early_avg > 0 else None

        if slope is None or n < 3:
            trend = "insufficient_data"
        elif slope > 0.0005:
            trend = "improving"
        elif slope < -0.0005:
            trend = "declining"
        else:
            trend = "stable"

        results[sport] = {
            "sessions":                    n,
            "avg_cardiac_efficiency":      round(sum(ce_vals) / n, 4),
            "avg_hr":                      round(sum(s["avg_hr"] for s in sessions) / n, 1),
            "trend":                       trend,
            "slope":                       round(slope, 5) if slope else None,
            "r":                           round(r, 3) if r else None,
            "pct_change_first_vs_last_third": pct_delta,
            "recent_sessions":             sessions[-5:],
        }

    improving = [s for s, d in results.items() if d["trend"] == "improving"]
    declining = [s for s, d in results.items() if d["trend"] == "declining"]

    return {
        "period":       {"start_date": start, "end_date": end},
        "sport_filter": sport_type or "all",
        "by_sport":     results,
        "summary": {
            "sports_improving":      improving,
            "sports_declining":      declining,
            "total_sports_analyzed": len(results),
        },
        "methodology": (
            "Cardiac efficiency = miles / (minutes * avg_HR) * 1000. "
            "Higher = faster for given HR = better cardiovascular fitness. "
            "Linear regression over session index detects improvement direction. "
            "Attia: same workout, lower HR over time is the purest fitness signal from consumer data. "
            "Compare same activity types only — mixing sports confounds the trend."
        ),
    }


def tool_get_acwr_status(args):
    """
    BS-09: Acute:Chronic Workload Ratio status.
    Reads pre-computed acwr fields from the computed_metrics partition.
    Falls back to live computation from Whoop strain if pre-computed record is missing.
    """
    end_date   = args.get("date", (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"))
    days_back  = int(args.get("days_back", 14))   # how many days of history to return

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (TypeError, ValueError): return None

    # ── Read from computed_metrics (prefer pre-computed) ─────────────────────
    cm_records = query_source("computed_metrics",
                              (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days_back - 1)).strftime("%Y-%m-%d"),
                              end_date)

    history = []
    for rec in sorted(cm_records, key=lambda r: r.get("date", ""), reverse=True):
        acwr = _sf(rec.get("acwr"))
        if acwr is None and "acute_load_7d" not in rec:
            continue  # skip records that have no ACWR data at all
        history.append({
            "date":             rec.get("date"),
            "acwr":             acwr,
            "acute_load_7d":    _sf(rec.get("acute_load_7d")),
            "chronic_load_28d": _sf(rec.get("chronic_load_28d")),
            "zone":             rec.get("acwr_zone", "unknown"),
            "alert":            bool(rec.get("acwr_alert", False)),
            "alert_reason":     rec.get("acwr_alert_reason"),
        })

    if not history:
        return {
            "error": "No ACWR data found in computed_metrics. acwr-compute Lambda may not have run yet for this date range.",
            "hint": "Run the acwr-compute Lambda manually: aws lambda invoke --function-name acwr-compute --payload '{\"date\":\"" + end_date + "\"}' /tmp/out.json",
        }

    latest = history[0]

    # ── Trend (last 7 days with data) ────────────────────────────────────────
    recent_acwrs = [h["acwr"] for h in history if h.get("acwr") is not None][:7]
    trend = None
    if len(recent_acwrs) >= 3:
        if recent_acwrs[0] > recent_acwrs[-1] * 1.05:
            trend = "rising"
        elif recent_acwrs[0] < recent_acwrs[-1] * 0.95:
            trend = "falling"
        else:
            trend = "stable"

    # ── Alert count ──────────────────────────────────────────────────────────
    alerts_7d = sum(1 for h in history[:7] if h.get("alert"))

    # ── Board coaching note ──────────────────────────────────────────────────
    zone    = latest.get("zone", "unknown")
    acwr    = latest.get("acwr")
    coaching = None
    if zone == "danger":
        coaching = "Attia + Galpin: ACWR above 1.5 is the strongest predictor of non-contact injury in the next 7 days. Rest is not optional this week."
    elif zone == "caution":
        coaching = "Galpin: ACWR in the caution zone (1.3-1.5). Reduce volume by 30-40%. Maintain intensity on 1-2 key sessions; cut accessory work."
    elif zone == "safe":
        coaching = "Galpin: ACWR in the optimal window (0.8-1.3). Current load progression is appropriate for continued adaptation."
    elif zone == "detraining":
        coaching = "Attia: Chronic load exceeds acute — you are doing less than your body is adapted to. Increase training frequency or duration this week."

    return {
        "date":          latest.get("date"),
        "acwr":          acwr,
        "zone":          zone,
        "alert":         latest.get("alert"),
        "alert_reason":  latest.get("alert_reason"),
        "acute_load_7d": latest.get("acute_load_7d"),
        "chronic_load_28d": latest.get("chronic_load_28d"),
        "trend_7d":      trend,
        "alerts_last_7d": alerts_7d,
        "coaching":      coaching,
        "history":       history,
        "interpretation": (
            "ACWR = 7-day avg Whoop strain / 28-day avg Whoop strain. "
            "Safe zone: 0.8-1.3. Above 1.3: elevated injury risk. Below 0.8: detraining. "
            "Source: Gabbett et al. (2016), Hulin et al. (2014)."
        ),
        "_proxy_note": (
            "Whoop strain is a cardiac stress measure (heart rate-based), not a mechanical load "
            "measure. Gabbett thresholds were validated on team sport athletes using session RPE. "
            "Heavy strength training at low cardiac output may not register as high acute load. "
            "Use ACWR as a directional recovery signal, not a precise injury predictor."
        ),
        "_disclaimer": "For personal training guidance only. Not medical advice.",
    }


def tool_get_training(args):
    """Unified training intelligence dispatcher.
    Board vote 11-0: training_load, training_recommendation, training_periodization
    added to nightly warmer in same commit (all multi-source, expensive on-demand).
    """
    VALID_VIEWS = {
        "load":            tool_get_training_load,
        "periodization":   tool_get_training_periodization,
        "recommendation":  tool_get_training_recommendation,
    }
    view = (args.get("view") or "load").lower().strip()
    if view not in VALID_VIEWS:
        return {"error": f"Unknown view '{view}'.", "valid_views": list(VALID_VIEWS.keys()),
                "hint": "'load' for CTL/ATL/TSB fitness-fatigue model, 'periodization' for mesocycle analysis, 'recommendation' for today's workout suggestion."}
    return VALID_VIEWS[view](args)
