"""
Nutrition tools: micronutrients, meal timing, macros, food log.
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


# ── MacroFactor reference data ──

_MICRONUTRIENT_TARGETS = {
    "total_fiber_g":            {"rda": 38,    "optimal": 50,    "unit": "g",   "category": "Macros",     "score": True},
    "total_omega3_total_g":     {"rda": 1.6,   "optimal": 4.0,   "unit": "g",   "category": "Fatty Acids","score": True},
    "total_omega3_dha_g":       {"rda": 0.5,   "optimal": 2.0,   "unit": "g",   "category": "Fatty Acids","score": True},
    "total_omega3_epa_g":       {"rda": 0.5,   "optimal": 1.5,   "unit": "g",   "category": "Fatty Acids","score": True},
    "total_omega6_g":           {"rda": None,  "optimal": None,  "unit": "g",   "category": "Fatty Acids"},
    "total_sodium_mg":          {"rda": 1500,  "optimal": 1500,  "unit": "mg",  "category": "Minerals",   "upper_limit": 2300},
    "total_potassium_mg":       {"rda": 3400,  "optimal": 4700,  "unit": "mg",  "category": "Minerals",   "score": True},
    "total_calcium_mg":         {"rda": 1000,  "optimal": 1200,  "unit": "mg",  "category": "Minerals",   "score": True, "upper_limit": 2500},
    "total_magnesium_mg":       {"rda": 420,   "optimal": 500,   "unit": "mg",  "category": "Minerals",   "score": True},
    "total_iron_mg":            {"rda": 8,     "optimal": 18,    "unit": "mg",  "category": "Minerals",   "score": True, "upper_limit": 45},
    "total_zinc_mg":            {"rda": 11,    "optimal": 15,    "unit": "mg",  "category": "Minerals",   "score": True, "upper_limit": 40},
    "total_selenium_mcg":       {"rda": 55,    "optimal": 100,   "unit": "mcg", "category": "Minerals",   "score": True, "upper_limit": 400},
    "total_copper_mg":          {"rda": 0.9,   "optimal": 2.0,   "unit": "mg",  "category": "Minerals",   "score": True, "upper_limit": 10},
    "total_phosphorus_mg":      {"rda": 700,   "optimal": 1000,  "unit": "mg",  "category": "Minerals",   "score": True},
    "total_vitamin_a_mcg":      {"rda": 900,   "optimal": 1500,  "unit": "mcg", "category": "Vitamins",   "score": True, "upper_limit": 3000},
    "total_vitamin_c_mg":       {"rda": 90,    "optimal": 500,   "unit": "mg",  "category": "Vitamins",   "score": True},
    "total_vitamin_d_mcg":      {"rda": 20,    "optimal": 50,    "unit": "mcg", "category": "Vitamins",   "score": True, "upper_limit": 100},
    "total_vitamin_e_mg":       {"rda": 15,    "optimal": 30,    "unit": "mg",  "category": "Vitamins",   "score": True, "upper_limit": 1000},
    "total_vitamin_k_mcg":      {"rda": 120,   "optimal": 300,   "unit": "mcg", "category": "Vitamins",   "score": True},
    "total_b1_thiamine_mg":     {"rda": 1.2,   "optimal": 5.0,   "unit": "mg",  "category": "B Vitamins", "score": True},
    "total_b2_riboflavin_mg":   {"rda": 1.3,   "optimal": 3.0,   "unit": "mg",  "category": "B Vitamins", "score": True},
    "total_b3_niacin_mg":       {"rda": 16,    "optimal": 25,    "unit": "mg",  "category": "B Vitamins", "score": True, "upper_limit": 35},
    "total_b5_pantothenic_mg":  {"rda": 5,     "optimal": 10,    "unit": "mg",  "category": "B Vitamins", "score": True},
    "total_b6_pyridoxine_mg":   {"rda": 1.7,   "optimal": 5.0,   "unit": "mg",  "category": "B Vitamins", "score": True, "upper_limit": 100},
    "total_b12_cobalamin_mcg":  {"rda": 2.4,   "optimal": 10.0,  "unit": "mcg", "category": "B Vitamins", "score": True},
    "total_folate_mcg":         {"rda": 400,   "optimal": 600,   "unit": "mcg", "category": "B Vitamins", "score": True, "upper_limit": 1000},
    "total_choline_mg":         {"rda": 550,   "optimal": 750,   "unit": "mg",  "category": "Other",      "score": True},
    "total_caffeine_mg":        {"rda": None,  "optimal": None,  "unit": "mg",  "category": "Other",      "upper_limit": 400},
}
_MICRO_CATEGORY_ORDER  = ["Macros", "Fatty Acids", "Minerals", "Vitamins", "B Vitamins", "Other"]
_OMEGA_RATIO_TARGET    = 4.0    # Attia / Simopoulos: keep O6:O3 < 4:1
_LEUCINE_MPS_THRESHOLD = 2.5    # g leucine per meal to trigger MPS (Phillips / Attia)


def tool_get_micronutrient_report(args):
    """
    Score ~25 micronutrients against RDA and longevity-optimal targets.
    Flags chronic deficiencies (avg < 60% RDA), near-miss gaps (60-90%), upper-limit exceedances,
    omega-6:omega-3 ratio, and generates actionable longevity commentary.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=29)).strftime("%Y-%m-%d"))

    items = query_source("macrofactor", start_date, end_date)
    if not items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    n = len(items)
    totals_sum   = defaultdict(float)
    totals_count = defaultdict(int)
    for item in items:
        for field in _MICRONUTRIENT_TARGETS:
            v = item.get(field)
            if v is not None:
                totals_sum[field]   += float(v)
                totals_count[field] += 1

    categories   = {}
    deficiencies = []
    near_gaps    = []
    exceedances  = []

    for cat in _MICRO_CATEGORY_ORDER:
        cat_rows = []
        for field, meta in _MICRONUTRIENT_TARGETS.items():
            if meta.get("category") != cat:
                continue
            if totals_count[field] == 0:
                continue
            avg_val = round(totals_sum[field] / totals_count[field], 2)
            rda     = meta.get("rda")
            optimal = meta.get("optimal")
            ul      = meta.get("upper_limit")
            unit    = meta["unit"]
            row = {"field": field, "average": avg_val, "unit": unit, "days_logged": totals_count[field]}
            if rda:
                pct_rda = round(avg_val / rda * 100, 1)
                row["rda"]     = rda
                row["pct_rda"] = pct_rda
                if meta.get("score"):
                    if pct_rda < 60:
                        row["status"] = "DEFICIENT"
                        deficiencies.append({"field": field, "average": avg_val, "unit": unit, "pct_rda": pct_rda, "rda": rda})
                    elif pct_rda < 90:
                        row["status"] = "LOW"
                        near_gaps.append({"field": field, "average": avg_val, "unit": unit, "pct_rda": pct_rda, "rda": rda})
                    elif ul and avg_val > ul:
                        row["status"] = "ABOVE_UPPER_LIMIT"
                        exceedances.append({"field": field, "average": avg_val, "unit": unit, "upper_limit": ul})
                    else:
                        row["status"] = "ADEQUATE"
            if optimal:
                row["optimal"]      = optimal
                row["pct_optimal"]  = round(avg_val / optimal * 100, 1)
            cat_rows.append(row)
        if cat_rows:
            categories[cat] = sorted(cat_rows, key=lambda r: r.get("pct_rda", 999))

    omega6 = totals_sum.get("total_omega6_g", 0) / max(totals_count.get("total_omega6_g", 1), 1)
    omega3 = totals_sum.get("total_omega3_total_g", 0) / max(totals_count.get("total_omega3_total_g", 1), 1)
    o6_o3  = round(omega6 / omega3, 1) if omega3 > 0 else None

    longevity_flags = []
    if o6_o3 and o6_o3 > _OMEGA_RATIO_TARGET:
        longevity_flags.append(f"Omega-6:Omega-3 ratio is {o6_o3}:1 (target <{_OMEGA_RATIO_TARGET}:1). Pro-inflammatory — increase EPA/DHA or reduce seed oils.")
    dha_avg = totals_sum.get("total_omega3_dha_g", 0) / max(totals_count.get("total_omega3_dha_g", 1), 1)
    if dha_avg < 1.0:
        longevity_flags.append(f"DHA averages {round(dha_avg,2)}g/day — below the 1g+ associated with cognitive protection (Rhonda Patrick). Add fatty fish ≥3x/week or algae-based DHA supplement.")
    mag_avg = totals_sum.get("total_magnesium_mg", 0) / max(totals_count.get("total_magnesium_mg", 1), 1)
    if mag_avg < 350:
        longevity_flags.append(f"Magnesium averages {round(mag_avg)}mg/day. Sub-optimal magnesium is linked to poor sleep quality, elevated cortisol, and lower HRV. Target 400-500mg from food + glycinate supplement.")
    vd_avg = totals_sum.get("total_vitamin_d_mcg", 0) / max(totals_count.get("total_vitamin_d_mcg", 1), 1)
    if vd_avg < 25:
        longevity_flags.append(f"Vitamin D from food averages {round(vd_avg,1)}mcg/day. Difficult to reach optimal serum levels (60-80 ng/mL) from diet alone in the Pacific Northwest — consider 4,000-5,000 IU D3+K2 supplement.")

    return {
        "period":          {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "summary":         {"deficiencies": len(deficiencies), "near_gaps": len(near_gaps), "exceedances": len(exceedances),
                            "omega6_omega3_ratio": o6_o3, "omega6_omega3_status": "OK" if o6_o3 and o6_o3 <= _OMEGA_RATIO_TARGET else "HIGH" if o6_o3 else "insufficient_data"},
        "longevity_flags": longevity_flags,
        "deficiencies":    deficiencies,
        "near_gaps":       near_gaps,
        "exceedances":     exceedances,
        "by_category":     categories,
    }


def tool_get_meal_timing(args):
    """
    Eating window analysis: first bite, last bite, window duration, caloric distribution
    across morning/midday/evening/late, circadian consistency (SD of meal times),
    and overlap with sleep onset. Based on Satchin Panda / Salk Institute TRF research.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=29)).strftime("%Y-%m-%d"))

    items = query_source("macrofactor", start_date, end_date)
    if not items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    def t2d(t):
        if not t:
            return None
        try:
            p = str(t).strip().split(":")
            return int(p[0]) + int(p[1]) / 60
        except Exception:
            return None

    def d2hm(d):
        if d is None:
            return None
        h = int(d) % 24
        m = int(round((d % 1) * 60))
        if m == 60:
            h += 1; m = 0
        return f"{h:02d}:{m:02d}"

    daily_rows  = []
    first_bites = []
    last_bites  = []
    windows     = []

    for item in sorted(items, key=lambda x: x["date"]):
        food_log = item.get("food_log", [])
        if not food_log:
            continue
        times = []
        morning_cal = midday_cal = evening_cal = late_cal = 0.0
        for entry in food_log:
            td  = t2d(entry.get("time"))
            cal = float(entry.get("calories_kcal", 0) or 0)
            if td is not None:
                times.append(td)
                if td < 11:   morning_cal += cal
                elif td < 15: midday_cal  += cal
                elif td < 20: evening_cal += cal
                else:         late_cal    += cal
        if not times:
            continue
        fb = min(times); lb = max(times); wh = round(lb - fb, 2)
        total_cal = float(item.get("total_calories_kcal", 0) or 0)
        first_bites.append(fb); last_bites.append(lb); windows.append(wh)
        daily_rows.append({
            "date": item["date"],
            "first_bite": d2hm(fb),
            "last_bite":  d2hm(lb),
            "eating_window_hrs": wh,
            "total_calories": round(total_cal, 0),
            "distribution": {
                "morning_pct": round(morning_cal / total_cal * 100, 1) if total_cal else 0,
                "midday_pct":  round(midday_cal  / total_cal * 100, 1) if total_cal else 0,
                "evening_pct": round(evening_cal / total_cal * 100, 1) if total_cal else 0,
                "late_pct":    round(late_cal    / total_cal * 100, 1) if total_cal else 0,
            },
            "late_eating_flag": lb >= 20.0,
        })

    if not daily_rows:
        return {"error": "No food log entries with timestamps found."}

    n = len(daily_rows)
    avg_fb  = sum(first_bites) / n
    avg_lb  = sum(last_bites)  / n
    avg_win = round(sum(windows) / n, 1)

    def stdev(vals):
        n2 = len(vals)
        if n2 < 2: return 0
        m = sum(vals) / n2
        return round(math.sqrt(sum((v - m)**2 for v in vals) / (n2 - 1)), 2)

    late_days = sum(1 for r in daily_rows if r["late_eating_flag"])

    # Eight Sleep sleep-onset overlap
    sleep_onset_avg = None
    try:
        si_items = query_source("eightsleep", start_date, end_date)
        onsets = []
        for si in si_items:
            onset_str = si.get("sleep_start_local") or si.get("sleep_onset_local")
            if onset_str:
                td = t2d(str(onset_str)[:5])
                if td is not None:
                    onsets.append(td if td > 8 else td + 24)
        if onsets:
            sleep_onset_avg = sum(onsets) / len(onsets)
    except Exception:
        pass

    pre_sleep_gap = None
    if sleep_onset_avg is not None:
        gap = sleep_onset_avg - avg_lb
        if gap < 0: gap += 24
        pre_sleep_gap = round(gap, 1)

    trf_flags = []
    if avg_win > 12:
        trf_flags.append(f"Average eating window is {avg_win}h — wider than the 10h TRF target. Try compressing to <10h for metabolic benefit.")
    if stdev(first_bites) > 1.5:
        trf_flags.append(f"First bite time varies by {stdev(first_bites)}h SD — inconsistent circadian signalling. Aim for <1h variation.")
    if late_days > n * 0.3:
        trf_flags.append(f"Eating after 8pm on {late_days}/{n} days. Late eating suppresses melatonin-mediated metabolic signalling.")
    if pre_sleep_gap is not None and pre_sleep_gap < 2.5:
        trf_flags.append(f"Average last bite → sleep gap is only {pre_sleep_gap}h. Panda recommends ≥3h to allow GLP-1 clearance before sleep onset.")

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "eating_window": {
            "avg_first_bite":                d2hm(avg_fb),
            "avg_last_bite":                 d2hm(avg_lb),
            "avg_window_hrs":                avg_win,
            "first_bite_consistency_sd_hrs": stdev(first_bites),
            "last_bite_consistency_sd_hrs":  stdev(last_bites),
            "trf_status": "OPTIMAL" if avg_win <= 10 else "BORDERLINE" if avg_win <= 12 else "WIDE",
        },
        "late_eating":  {"days_eating_after_8pm": late_days, "pct_days": round(late_days / n * 100, 1)},
        "sleep_overlap": {
            "avg_last_bite_to_sleep_hrs": pre_sleep_gap,
            "status": ("GOOD" if pre_sleep_gap and pre_sleep_gap >= 3 else
                       "MARGINAL" if pre_sleep_gap and pre_sleep_gap >= 2 else
                       "TOO_CLOSE" if pre_sleep_gap else "no_sleep_data"),
        },
        "circadian_flags": trf_flags,
        "daily_breakdown": daily_rows,
    }


def tool_get_nutrition_biometrics_correlation(args):
    """
    Pearson correlations between daily nutrition inputs and biometric outcomes across
    Whoop, Withings, and Eight Sleep. Optional lag tests next-day effects.
    This is the personalized insight layer — what does YOUR diet actually predict about
    YOUR recovery, sleep, HRV, and weight?
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=89)).strftime("%Y-%m-%d"))
    lag_days   = int(args.get("lag_days", 1))

    NUTRITION_FIELDS = [
        ("total_calories_kcal",  "Calories (kcal)"),
        ("total_protein_g",      "Protein (g)"),
        ("total_carbs_g",        "Carbs (g)"),
        ("total_fat_g",          "Fat (g)"),
        ("total_fiber_g",        "Fiber (g)"),
        ("total_omega3_total_g", "Omega-3 (g)"),
        ("total_sodium_mg",      "Sodium (mg)"),
        ("total_caffeine_mg",    "Caffeine (mg)"),
        ("total_magnesium_mg",   "Magnesium (mg)"),
        ("total_alcohol_g",      "Alcohol (g)"),
    ]
    BIOMETRIC_FIELDS = [
        ("whoop",      "hrv",                  "HRV (ms)"),
        ("whoop",      "recovery_score",        "Recovery Score"),
        ("whoop",      "resting_heart_rate",    "Resting HR (bpm)"),
        ("whoop",      "sleep_performance_pct", "Sleep Performance (%)"),
        ("whoop",      "strain",                "Strain"),
        ("withings",   "weight_lbs",            "Weight (lbs)"),
        ("eightsleep", "sleep_score",           "Sleep Score"),
        ("eightsleep", "efficiency",            "Sleep Efficiency (%)"),
        ("eightsleep", "hrv_avg_ms",            "Sleep HRV (ms)"),
    ]

    mf_items = query_source("macrofactor", start_date, end_date)
    if len(mf_items) < 14:
        return {"error": f"Need ≥14 days of MacroFactor data. Found {len(mf_items)}."}
    mf_by_date = {item["date"]: item for item in mf_items}

    bio_end  = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=lag_days + 1)).strftime("%Y-%m-%d")
    bio_srcs = list({src for src, _, _ in BIOMETRIC_FIELDS})
    bio_data = parallel_query_sources(bio_srcs, start_date, bio_end)
    bio_by_src = {src: {i["date"]: i for i in items} for src, items in bio_data.items()}

    results = []
    for nf, nf_label in NUTRITION_FIELDS:
        for bio_src, bf, bf_label in BIOMETRIC_FIELDS:
            bbd = bio_by_src.get(bio_src, {})
            pairs = []
            for ds, mf_item in mf_by_date.items():
                nv = mf_item.get(nf)
                if nv is None: continue
                bio_date = (datetime.strptime(ds, "%Y-%m-%d") + timedelta(days=lag_days)).strftime("%Y-%m-%d")
                bi = bbd.get(bio_date)
                if bi is None: continue
                bv = bi.get(bf)
                if bv is None: continue
                pairs.append((float(nv), float(bv)))
            if len(pairs) < 10:
                continue
            xs, ys = zip(*pairs)
            r = pearson_r(list(xs), list(ys))
            if r is None or abs(r) < 0.2:
                continue
            abs_r = abs(r)
            results.append({
                "nutrition":      nf_label,
                "biometric":      bf_label,
                "r":              r,
                "abs_r":          abs_r,
                "strength":       "strong" if abs_r >= 0.5 else "moderate" if abs_r >= 0.35 else "weak",
                "direction":      "positive" if r > 0 else "negative",
                "n_days":         len(pairs),
                "lag_days":       lag_days,
                "interpretation": f"{'Higher' if r > 0 else 'Lower'} {nf_label} → {'higher' if r > 0 else 'lower'} {bf_label} {'next day' if lag_days == 1 else f'{lag_days}d later' if lag_days > 1 else 'same day'}",
            })

    results.sort(key=lambda x: -x["abs_r"])
    actionable = [r for r in results if r["strength"] in ("strong", "moderate")]

    return {
        "period":              {"start_date": start_date, "end_date": end_date},
        "methodology":         f"Pearson r: nutrition → biometrics shifted +{lag_days} day(s). |r| ≥ 0.5 strong, ≥ 0.35 moderate, ≥ 0.2 weak. Only |r| ≥ 0.2 reported.",
        "top_findings":        results[:15],
        "actionable_findings": actionable,
        "total_tested":        len(NUTRITION_FIELDS) * len(BIOMETRIC_FIELDS),
        "significant_pairs":   len(results),
        "all_results":         results,
    }


def tool_get_nutrition_summary(args):
    """
    Daily macro breakdown + rolling averages for any date range.
    Returns per-day rows and period averages for calories, protein, carbs, fat, fiber,
    sodium, caffeine, omega-3, and key micronutrients.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=29)).strftime("%Y-%m-%d"))

    pk = USER_PREFIX + "macrofactor"
    table = get_table()
    items = query_date_range(table, pk, start_date, end_date)

    if not items:
        return {"error": "No MacroFactor data found for the requested range.", "start_date": start_date, "end_date": end_date}

    MACRO_FIELDS = [
        ("total_calories_kcal",  "calories_kcal"),
        ("total_protein_g",      "protein_g"),
        ("total_carbs_g",        "carbs_g"),
        ("total_fat_g",          "fat_g"),
        ("total_fiber_g",        "fiber_g"),
        ("total_sodium_mg",      "sodium_mg"),
        ("total_caffeine_mg",    "caffeine_mg"),
        ("total_omega3_total_g", "omega3_total_g"),
        ("total_potassium_mg",   "potassium_mg"),
        ("total_magnesium_mg",   "magnesium_mg"),
        ("total_vitamin_d_mcg",  "vitamin_d_mcg"),
        ("total_alcohol_g",      "alcohol_g"),
    ]

    daily_rows = []
    for item in sorted(items, key=lambda x: x["date"]):
        row = {"date": item["date"], "entries_logged": item.get("entries_count", 0)}
        for db_field, out_field in MACRO_FIELDS:
            v = item.get(db_field)
            if v is not None:
                row[out_field] = float(v)
        # Derived: protein % of calories
        cal  = row.get("calories_kcal", 0)
        prot = row.get("protein_g", 0)
        if cal > 0:
            row["protein_pct_of_calories"] = round(prot * 4 / cal * 100, 1)
        # Board rec 1A: fiber density (Norton) — normalizes for caloric intake
        fib = row.get("fiber_g", 0)
        if cal > 0 and fib > 0:
            row["fiber_per_1000kcal"] = round(fib / (cal / 1000), 1)
        daily_rows.append(row)

    # Period averages
    def avg(field):
        vals = [r[field] for r in daily_rows if field in r]
        return round(sum(vals) / len(vals), 1) if vals else None

    averages = {out: avg(out) for _, out in MACRO_FIELDS}
    averages["protein_pct_of_calories"] = avg("protein_pct_of_calories")
    averages["fiber_per_1000kcal"] = avg("fiber_per_1000kcal")

    # Reference targets (from profile / common goals)
    TARGETS = {
        "calories_kcal":    2400,
        "protein_g":        180,
        "fiber_g":          30,
        "fiber_per_1000kcal": 14,   # Board rec 1A (Norton): minimum fiber density
        "sodium_mg":        2300,
        "omega3_total_g":   2.0,
        "vitamin_d_mcg":    20,
    }
    target_comparison = {}
    for field, target in TARGETS.items():
        avg_val = averages.get(field)
        if avg_val is not None:
            target_comparison[field] = {
                "target":  target,
                "average": avg_val,
                "gap":     round(avg_val - target, 1),
                "pct_of_target": round(avg_val / target * 100, 1),
            }

    return {
        "period":            {"start_date": start_date, "end_date": end_date, "days_with_data": len(daily_rows)},
        "daily_averages":    averages,
        "target_comparison": target_comparison,
        "daily_breakdown":   daily_rows,
    }


def tool_get_macro_targets(args):
    """
    Compare actual nutrition vs calorie / protein targets.
    Pulls recent Withings weight to compute TDEE-based calorie target,
    then scores daily adherence to each macro goal.
    """
    end_date   = args.get("end_date",   datetime.utcnow().strftime("%Y-%m-%d"))
    days       = int(args.get("days", 30))
    start_date = args.get("start_date") or (
        (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    )
    calorie_target = args.get("calorie_target")   # optional override
    protein_target = args.get("protein_target")   # optional override

    table = get_table()
    pk_mf = USER_PREFIX + "macrofactor"
    items = query_date_range(table, pk_mf, start_date, end_date)

    if not items:
        return {"error": "No MacroFactor data found.", "start_date": start_date, "end_date": end_date}

    # Pull current weight for TDEE estimate if no calorie_target override
    if not calorie_target:
        try:
            pk_wt = USER_PREFIX + "withings"
            wt_items = query_date_range(table, pk_wt,
                (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d"),
                end_date)
            wt_items_sorted = sorted(wt_items, key=lambda x: x["date"], reverse=True)
            if wt_items_sorted:
                weight_lbs = float(wt_items_sorted[0].get("weight_lbs", 0))
                # Mifflin-St Jeor BMR for male (approx for Matthew)
                weight_kg = weight_lbs * 0.453592
                # height 72in = 182.88cm, age ~35
                bmr = 10 * weight_kg + 6.25 * 182.88 - 5 * 35 + 5
                tdee_estimate = round(bmr * 1.55)  # moderate activity
                calorie_target = calorie_target or tdee_estimate
        except Exception:
            pass
    calorie_target = calorie_target or 2400
    protein_target = protein_target or 180

    daily_rows = []
    hits_cal  = hits_prot = hits_fiber = 0
    for item in sorted(items, key=lambda x: x["date"]):
        cal   = float(item.get("total_calories_kcal", 0) or 0)
        prot  = float(item.get("total_protein_g",     0) or 0)
        fiber = float(item.get("total_fiber_g",       0) or 0)
        fat   = float(item.get("total_fat_g",         0) or 0)
        carbs = float(item.get("total_carbs_g",       0) or 0)

        cal_pct  = round(cal  / calorie_target * 100, 1)
        prot_pct = round(prot / protein_target * 100, 1)

        hit_cal  = 0.85 <= cal / calorie_target <= 1.10
        hit_prot = prot >= protein_target * 0.95
        hit_fiber = fiber >= 25

        hits_cal   += int(hit_cal)
        hits_prot  += int(hit_prot)
        hits_fiber += int(hit_fiber)

        daily_rows.append({
            "date":            item["date"],
            "calories_kcal":   round(cal, 0),
            "calories_pct":    cal_pct,
            "protein_g":       round(prot, 1),
            "protein_pct":     prot_pct,
            "fat_g":           round(fat, 1),
            "carbs_g":         round(carbs, 1),
            "fiber_g":         round(fiber, 1),
            "hit_calorie_target":  hit_cal,
            "hit_protein_target":  hit_prot,
            "hit_fiber_target":    hit_fiber,
        })

    n = len(daily_rows)
    return {
        "period":           {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "targets": {
            "calories_kcal":  calorie_target,
            "protein_g":      protein_target,
            "fiber_g":        25,
            "note":           "Calorie target estimated from TDEE (Mifflin-St Jeor × 1.55 activity factor) unless overridden.",
        },
        "adherence": {
            "calorie_target_hit_pct":  round(hits_cal  / n * 100, 1) if n else 0,
            "protein_target_hit_pct":  round(hits_prot / n * 100, 1) if n else 0,
            "fiber_target_hit_pct":    round(hits_fiber / n * 100, 1) if n else 0,
        },
        "daily_breakdown": daily_rows,
    }


def tool_get_food_log(args):
    """
    Return individual food entries logged on a specific date.
    Useful for 'what did I eat yesterday?', 'show me my food diary'.
    """
    date_str = args.get("date", (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"))

    table = get_table()
    pk = USER_PREFIX + "macrofactor"

    response = table.get_item(Key={"pk": pk, "sk": f"DATE#{date_str}"})
    item     = response.get("Item")

    if not item:
        return {"error": f"No MacroFactor data for {date_str}. Check the date or re-export from MacroFactor."}

    # Build clean food log
    food_log = item.get("food_log", [])
    clean_log = []
    for entry in food_log:
        clean_entry = {
            "food":         entry.get("food_name", "Unknown"),
            "time":         entry.get("time"),
            "serving":      entry.get("serving_size"),
            "calories":     entry.get("calories_kcal"),
            "protein_g":    entry.get("protein_g"),
            "carbs_g":      entry.get("carbs_g"),
            "fat_g":        entry.get("fat_g"),
            "fiber_g":      entry.get("fiber_g"),
        }
        clean_entry = {k: float(v) if isinstance(v, Decimal) else v
                       for k, v in clean_entry.items() if v is not None}
        clean_log.append(clean_entry)

    # Day totals
    totals = {
        "calories_kcal": float(item.get("total_calories_kcal") or 0),
        "protein_g":     float(item.get("total_protein_g")     or 0),
        "carbs_g":       float(item.get("total_carbs_g")        or 0),
        "fat_g":         float(item.get("total_fat_g")          or 0),
        "fiber_g":       float(item.get("total_fiber_g")        or 0),
        "sodium_mg":     float(item.get("total_sodium_mg")      or 0),
        "caffeine_mg":   float(item.get("total_caffeine_mg")    or 0),
        "omega3_total_g":float(item.get("total_omega3_total_g") or 0),
    }

    return {
        "date":          date_str,
        "entries_logged": item.get("entries_count", len(food_log)),
        "daily_totals":  totals,
        "food_log":      clean_log,
    }


def tool_get_nutrition(args):
    """
    Unified nutrition intelligence dispatcher. Routes to the appropriate
    underlying function based on the 'view' parameter.
    """
    VALID_VIEWS = {
        "summary":       tool_get_nutrition_summary,
        "macros":        tool_get_macro_targets,
        "meal_timing":   tool_get_meal_timing,
        "micronutrients": tool_get_micronutrient_report,
    }
    view = (args.get("view") or "summary").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "Default is 'summary'. Use 'macros' for calorie/protein adherence, 'meal_timing' for eating window analysis, 'micronutrients' for RDA scoring.",
        }
    return VALID_VIEWS[view](args)
