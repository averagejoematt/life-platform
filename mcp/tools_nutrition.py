"""
Nutrition tools: micronutrients, meal timing, macros, food log.
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta

from mcp.core import get_profile, pacific_today, parallel_query_sources, query_source


def _nutrition_through_date():
    """The latest COMPLETE nutrition day — the default end of any nutrition range.

    MacroFactor is a manual end-of-day Dropbox upload, so it is ALWAYS ~24h behind
    by design: today's intake doesn't exist until tomorrow. Defaulting a range to
    `today` (the old behavior across these tools) makes Claude read an absent today
    as "0 calories / hasn't logged today" — a pipeline characteristic mis-framed as
    a user failure. Anchor to yesterday (the latest complete day), matching
    tool_get_food_log. Callers may still pass an explicit end_date.
    """
    # Pacific day: "yesterday" must be relative to the PT calendar, else a caller in
    # the UTC-evening window gets today's (still-empty) PT day. See AUDIT BUG-03.
    return (datetime.strptime(pacific_today(), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


_DEFAULT_RANGE_DAYS = 30


def _nutrition_default_range(args, days=_DEFAULT_RANGE_DAYS):
    """Resolve (start_date, end_date) for a view the caller gave no explicit range.

    Both ends MUST come from one calendar frame. Every view used to anchor its end to
    `_nutrition_through_date()` (Pacific yesterday) while deriving its start from
    `datetime.now(timezone.utc) - 29 days`. Two frames defining one window make its
    LENGTH depend on where the clock sits relative to the UTC/PT boundary — 30 inclusive
    dates in the PT morning, 29 in the UTC-evening window — while the registry documents
    a flat "default: 30 days ago". Deriving the start from the RESOLVED end makes the
    span exactly `days` inclusive dates at every hour, and matches how the macros view
    (`_get_macro_targets`) has always computed its rolling window.
    """
    end_date = args.get("end_date") or _nutrition_through_date()
    start_date = args.get("start_date") or (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return start_date, end_date


def _latest_weight_lbs(wt_items):
    """The most recent Withings weight in `wt_items`, or None.

    A Withings row can sync WITHOUT a weight (a body-composition-only or partial sync),
    so "the latest row" is not the same thing as "the latest weigh-in". Reading
    `.get('weight_lbs', 0)` off the newest row put a ZERO through Mifflin-St Jeor and
    produced a 1508 kcal/day target for a 220 lb man (ADR-104: an absent measurement is
    not a measurement of zero). Pick the newest row that actually carries a weight.
    """
    for item in sorted(wt_items or [], key=lambda x: x.get("date", ""), reverse=True):
        raw = item.get("weight_lbs")
        if raw in (None, ""):
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return None


def _mifflin_tdee(weight_lbs):
    """Mifflin-St Jeor BMR x 1.55 moderate-activity multiplier, Matthew-specific
    (height 72in = 182.88cm, age ~35 — only used when the profile lookup fails)."""
    bmr = 10 * (weight_lbs * 0.453592) + 6.25 * 182.88 - 5 * 35 + 5
    return round(bmr * 1.55)


# ── MacroFactor reference data ──

# RDA: NIH DRI for adult males 31-50. "optimal": longevity targets per Attia/Patrick (not official guidelines). "upper": NIH Tolerable Upper Intake Level.
_MICRONUTRIENT_TARGETS = {
    "total_fiber_g": {"rda": 38, "optimal": 50, "unit": "g", "category": "Macros", "score": True},
    "total_omega3_total_g": {"rda": 1.6, "optimal": 4.0, "unit": "g", "category": "Fatty Acids", "score": True},
    "total_omega3_dha_g": {"rda": 0.5, "optimal": 2.0, "unit": "g", "category": "Fatty Acids", "score": True},
    "total_omega3_epa_g": {"rda": 0.5, "optimal": 1.5, "unit": "g", "category": "Fatty Acids", "score": True},
    "total_omega6_g": {"rda": None, "optimal": None, "unit": "g", "category": "Fatty Acids"},
    "total_sodium_mg": {"rda": 1500, "optimal": 1500, "unit": "mg", "category": "Minerals", "upper_limit": 2300},
    "total_potassium_mg": {"rda": 3400, "optimal": 4700, "unit": "mg", "category": "Minerals", "score": True},
    "total_calcium_mg": {"rda": 1000, "optimal": 1200, "unit": "mg", "category": "Minerals", "score": True, "upper_limit": 2500},
    "total_magnesium_mg": {"rda": 420, "optimal": 500, "unit": "mg", "category": "Minerals", "score": True},
    "total_iron_mg": {"rda": 8, "optimal": 18, "unit": "mg", "category": "Minerals", "score": True, "upper_limit": 45},
    "total_zinc_mg": {"rda": 11, "optimal": 15, "unit": "mg", "category": "Minerals", "score": True, "upper_limit": 40},
    "total_selenium_mcg": {"rda": 55, "optimal": 100, "unit": "mcg", "category": "Minerals", "score": True, "upper_limit": 400},
    "total_copper_mg": {"rda": 0.9, "optimal": 2.0, "unit": "mg", "category": "Minerals", "score": True, "upper_limit": 10},
    "total_phosphorus_mg": {"rda": 700, "optimal": 1000, "unit": "mg", "category": "Minerals", "score": True},
    "total_vitamin_a_mcg": {"rda": 900, "optimal": 1500, "unit": "mcg", "category": "Vitamins", "score": True, "upper_limit": 3000},
    "total_vitamin_c_mg": {"rda": 90, "optimal": 500, "unit": "mg", "category": "Vitamins", "score": True},
    "total_vitamin_d_mcg": {"rda": 20, "optimal": 50, "unit": "mcg", "category": "Vitamins", "score": True, "upper_limit": 100},
    "total_vitamin_e_mg": {"rda": 15, "optimal": 30, "unit": "mg", "category": "Vitamins", "score": True, "upper_limit": 1000},
    "total_vitamin_k_mcg": {"rda": 120, "optimal": 300, "unit": "mcg", "category": "Vitamins", "score": True},
    "total_b1_thiamine_mg": {"rda": 1.2, "optimal": 5.0, "unit": "mg", "category": "B Vitamins", "score": True},
    "total_b2_riboflavin_mg": {"rda": 1.3, "optimal": 3.0, "unit": "mg", "category": "B Vitamins", "score": True},
    "total_b3_niacin_mg": {"rda": 16, "optimal": 25, "unit": "mg", "category": "B Vitamins", "score": True, "upper_limit": 35},
    "total_b5_pantothenic_mg": {"rda": 5, "optimal": 10, "unit": "mg", "category": "B Vitamins", "score": True},
    "total_b6_pyridoxine_mg": {"rda": 1.7, "optimal": 5.0, "unit": "mg", "category": "B Vitamins", "score": True, "upper_limit": 100},
    "total_b12_cobalamin_mcg": {"rda": 2.4, "optimal": 10.0, "unit": "mcg", "category": "B Vitamins", "score": True},
    "total_folate_mcg": {"rda": 400, "optimal": 600, "unit": "mcg", "category": "B Vitamins", "score": True, "upper_limit": 1000},
    "total_choline_mg": {"rda": 550, "optimal": 750, "unit": "mg", "category": "Other", "score": True},
    "total_caffeine_mg": {"rda": None, "optimal": None, "unit": "mg", "category": "Other", "upper_limit": 400},
}
_MICRO_CATEGORY_ORDER = ["Macros", "Fatty Acids", "Minerals", "Vitamins", "B Vitamins", "Other"]
# Simopoulos 2002; ratio approach debated — some authorities question its validity
_OMEGA_RATIO_TARGET = 4.0  # Attia / Simopoulos: keep O6:O3 < 4:1
# Phillips 2016 MPS threshold; older adults may need 3g+ (anabolic resistance)
_LEUCINE_MPS_THRESHOLD = 2.5  # g leucine per meal to trigger MPS (Phillips / Attia)
# ONE fiber target for the whole module. `view=summary` published 30 g/day, `view=macros`
# published 25 under `targets`, and the macros hit test compared against a THIRD literal 25
# — so 27 g/day was simultaneously "90% of target" and "a hit" depending on which view was
# asked. One tool must not answer one question two ways. (The 38 g in
# `_MICRONUTRIENT_TARGETS` is a different quantity — the NIH RDA, not Matthew's target.)
_FIBER_TARGET_G = 30


def _get_micronutrient_report(args):
    """
    Score ~25 micronutrients against RDA and longevity-optimal targets.
    Flags chronic deficiencies (avg < 60% RDA), near-miss gaps (60-90%), upper-limit exceedances,
    omega-6:omega-3 ratio, and generates actionable longevity commentary.
    """
    start_date, end_date = _nutrition_default_range(args)

    items = query_source("macrofactor", start_date, end_date)
    if not items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    n = len(items)
    totals_sum = defaultdict(float)
    totals_count = defaultdict(int)
    for item in items:
        for field in _MICRONUTRIENT_TARGETS:
            v = item.get(field)
            if v is not None:
                totals_sum[field] += float(v)
                totals_count[field] += 1

    categories = {}
    deficiencies = []
    near_gaps = []
    exceedances = []

    for cat in _MICRO_CATEGORY_ORDER:
        cat_rows = []
        for field, meta in _MICRONUTRIENT_TARGETS.items():
            if meta.get("category") != cat:
                continue
            if totals_count[field] == 0:
                continue
            avg_val = round(totals_sum[field] / totals_count[field], 2)
            rda = meta.get("rda")
            optimal = meta.get("optimal")
            ul = meta.get("upper_limit")
            unit = meta["unit"]
            days_logged = totals_count[field]
            row = {"field": field, "average": avg_val, "unit": unit, "days_logged": days_logged}
            if rda:
                pct_rda = round(avg_val / rda * 100, 1)
                row["rda"] = rda
                row["pct_rda"] = pct_rda
                if meta.get("score"):
                    # ADR-105: the deficiency / near-gap lists are the part a reader quotes, and
                    # the docstring calls them CHRONIC. Each entry carries the n it averaged over,
                    # so a one-day shortfall cannot read as a thirty-day one.
                    entry = {
                        "field": field,
                        "average": avg_val,
                        "unit": unit,
                        "pct_rda": pct_rda,
                        "rda": rda,
                        "days_logged": days_logged,
                    }
                    if pct_rda < 60:
                        row["status"] = "DEFICIENT"
                        deficiencies.append(entry)
                    elif pct_rda < 90:
                        row["status"] = "LOW"
                        near_gaps.append(entry)
            # Upper-limit exceedance must NOT depend on `score` or on `rda` being set (#2248):
            # total_sodium_mg and total_caffeine_mg both carry an `upper_limit` but no `score`
            # (and caffeine has no `rda` at all), so nesting this under either silently excluded
            # the two most actionable overages in the table. Checked independently here, it fires
            # for every upper_limit entry regardless of score/rda. A scored+rda'd nutrient that
            # isn't DEFICIENT/LOW and isn't over its limit still lands on ADEQUATE, unchanged.
            if ul and avg_val > ul:
                row["status"] = "ABOVE_UPPER_LIMIT"
                exceedances.append({"field": field, "average": avg_val, "unit": unit, "upper_limit": ul, "days_logged": days_logged})
            elif meta.get("score") and rda and "status" not in row:
                row["status"] = "ADEQUATE"
            if optimal:
                row["optimal"] = optimal
                row["pct_optimal"] = round(avg_val / optimal * 100, 1)
            cat_rows.append(row)
        if cat_rows:
            categories[cat] = sorted(cat_rows, key=lambda r: r.get("pct_rda", 999))

    # ADR-104 — a nutrient that appears in NO record has no average, not an average of 0.
    # `totals_sum.get(f, 0) / max(totals_count.get(f, 1), 1)` turned every absence into a
    # factual 0.0, and every threshold below is a `<`, so a range that only logged fiber
    # fired ALL THREE longevity flags — three fabricated deficiencies, each with a
    # supplement recommendation attached. Every other number in this function is already
    # gated on `totals_count[field] == 0`; the flag block and the omega ratio were not.
    def logged_avg(field):
        count = totals_count.get(field, 0)
        return (totals_sum.get(field, 0.0) / count) if count else None

    omega6 = logged_avg("total_omega6_g")
    omega3 = logged_avg("total_omega3_total_g")
    o6_o3 = round(omega6 / omega3, 1) if (omega6 is not None and omega3) else None

    longevity_flags = []
    if o6_o3 and o6_o3 > _OMEGA_RATIO_TARGET:
        longevity_flags.append(
            f"Omega-6:Omega-3 ratio is {o6_o3}:1 (target <{_OMEGA_RATIO_TARGET}:1). Pro-inflammatory — increase EPA/DHA or reduce seed oils."
        )
    dha_avg = logged_avg("total_omega3_dha_g")
    if dha_avg is not None and dha_avg < 1.0:
        longevity_flags.append(
            f"DHA averages {round(dha_avg, 2)}g/day — below the 1g+ associated with cognitive protection (Rhonda Patrick). Add fatty fish ≥3x/week or algae-based DHA supplement."
        )
    mag_avg = logged_avg("total_magnesium_mg")
    if mag_avg is not None and mag_avg < 350:
        longevity_flags.append(
            f"Magnesium averages {round(mag_avg)}mg/day. Sub-optimal magnesium is linked to poor sleep quality, elevated cortisol, and lower HRV. Target 400-500mg from food + glycinate supplement."
        )
    vd_avg = logged_avg("total_vitamin_d_mcg")
    if vd_avg is not None and vd_avg < 25:
        longevity_flags.append(
            f"Vitamin D from food averages {round(vd_avg, 1)}mcg/day. Difficult to reach optimal serum levels (60-80 ng/mL) from diet alone in the Pacific Northwest — consider 4,000-5,000 IU D3+K2 supplement."
        )

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "summary": {
            "deficiencies": len(deficiencies),
            "near_gaps": len(near_gaps),
            "exceedances": len(exceedances),
            "omega6_omega3_ratio": o6_o3,
            "omega6_omega3_status": "OK" if o6_o3 and o6_o3 <= _OMEGA_RATIO_TARGET else "HIGH" if o6_o3 else "insufficient_data",
        },
        "longevity_flags": longevity_flags,
        "deficiencies": deficiencies,
        "near_gaps": near_gaps,
        "exceedances": exceedances,
        "by_category": categories,
    }


def _avg_sleep_onset_hour(start_date, end_date):
    """Average local sleep-onset hour over the window, from the Eight Sleep partition.

    Reader/writer agreement: `ingestion/eightsleep_lambda.py` writes `sleep_onset_hour`
    (a LOCAL fractional hour, e.g. 23.9, derived with the night's tz offset) alongside the
    raw UTC ISO `sleep_start`. This block used to read `sleep_start_local` / `sleep_onset_local`
    — the first is a GARMIN field name, the second has no writer anywhere in the repo — and
    then sliced `str(onset_str)[:5]` off it, which would have parsed "2026-" even had the
    field existed. Two independent faults over one feature is why nobody ever saw the
    sleep-overlap section fail: it was permanently dark, always "no_sleep_data", and Panda's
    ">=3h before sleep onset" flag could never fire.

    Returns None (never 0) when nothing in the window carries an onset.
    """
    onsets = []
    try:
        for si in query_source("eightsleep", start_date, end_date):
            hour = si.get("sleep_onset_hour")
            if hour is None and si.get("sleep_start"):
                hour = _hour_from_iso_local(si["sleep_start"])
            if hour is None:
                continue
            try:
                h = float(hour) % 24
            except (TypeError, ValueError):
                continue
            # An onset recorded before 08:00 local is a past-midnight bedtime; lift it onto
            # the same evening axis as the last bite so the gap arithmetic stays monotonic.
            onsets.append(h if h > 8 else h + 24)
    except Exception:
        return None
    return sum(onsets) / len(onsets) if onsets else None


def _hour_from_iso_local(ts_str):
    """Pacific fractional hour of a UTC ISO timestamp — the same conversion
    `mcp/helpers.py` applies when back-filling `sleep_onset_hour` from `sleep_start`."""
    try:
        from common.pacific_time import PACIFIC, parse_iso_utc

        dt = parse_iso_utc(ts_str)
        if dt is None:
            return None
        local = dt.astimezone(PACIFIC)
        return round(local.hour + local.minute / 60 + local.second / 3600, 2)
    except Exception:
        return None


def _get_meal_timing(args):
    """
    Eating window analysis: first bite, last bite, window duration, caloric distribution
    across morning/midday/evening/late, circadian consistency (SD of meal times),
    and overlap with sleep onset. Based on Satchin Panda / Salk Institute TRF research.
    """
    start_date, end_date = _nutrition_default_range(args)

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
            h += 1
            m = 0
        return f"{h:02d}:{m:02d}"

    daily_rows = []
    first_bites = []
    last_bites = []
    windows = []

    # `.get("date", "")`, not `x["date"]`: one malformed partition row without the
    # attribute used to raise KeyError straight out of the tool and take down the whole
    # answer, where the micronutrient view (which does not sort) kept working.
    for item in sorted(items, key=lambda x: x.get("date", "")):
        food_log = item.get("food_log", [])
        if not food_log:
            continue
        times = []
        entries_skipped = 0
        morning_cal = midday_cal = evening_cal = late_cal = 0.0
        for entry in food_log:
            td = t2d(entry.get("time"))
            cal = float(entry.get("calories_kcal", 0) or 0)
            if td is None:
                # `t2d` parses only HH:MM, and the string comes straight from a MacroFactor
                # CSV column whose format the platform does not control. A dropped entry
                # shrinks the eating window AND (before the denominator fix below) deflated
                # every distribution percentage — silently. Count it and publish the count.
                entries_skipped += 1
                continue
            times.append(td)
            if td < 11:
                morning_cal += cal
            elif td < 15:
                midday_cal += cal
            elif td < 20:
                evening_cal += cal
            else:
                late_cal += cal
        if not times:
            continue
        fb = min(times)
        lb = max(times)
        wh = round(lb - fb, 2)
        # ADR-104: divide by what was actually BUCKETED, not by the day-level rollup.
        # `macrofactor_lambda` drops zero-valued totals at write time, so a day missing
        # `total_calories_kcal` published a factual 0.0% in every bucket — a fully logged
        # day reading as "no calories in any part of the day" — and whenever the rollup and
        # the entries disagreed the four percentages silently failed to sum to 100.
        located_cal = morning_cal + midday_cal + evening_cal + late_cal
        day_cal = float(item.get("total_calories_kcal", 0) or 0)
        row = {
            "date": item.get("date", ""),
            "first_bite": d2hm(fb),
            "last_bite": d2hm(lb),
            "eating_window_hrs": wh,
            "total_calories": round(day_cal or located_cal, 0),
            "located_calories": round(located_cal, 0),
            "distribution": {
                "morning_pct": round(morning_cal / located_cal * 100, 1) if located_cal else 0,
                "midday_pct": round(midday_cal / located_cal * 100, 1) if located_cal else 0,
                "evening_pct": round(evening_cal / located_cal * 100, 1) if located_cal else 0,
                "late_pct": round(late_cal / located_cal * 100, 1) if located_cal else 0,
            },
            "late_eating_flag": lb >= 20.0,
            "entries_skipped": entries_skipped,
        }
        first_bites.append(fb)
        last_bites.append(lb)
        windows.append(wh)
        daily_rows.append(row)

    if not daily_rows:
        return {"error": "No food log entries with timestamps found."}

    n = len(daily_rows)
    avg_fb = sum(first_bites) / n
    avg_lb = sum(last_bites) / n
    avg_win = round(sum(windows) / n, 1)

    def stdev(vals):
        """Sample SD, or None below n=2.

        ADR-104/105: returning the literal 0 here is not a neutral placeholder — 0 is the
        BEST possible value on a consistency scale, so ONE logged day read as perfect
        circadian consistency and simultaneously suppressed the '>1.5h SD' flag. The one
        case where the tool has no idea was the case where it reassured him.
        """
        n2 = len(vals)
        if n2 < 2:
            return None
        m = sum(vals) / n2
        return round(math.sqrt(sum((v - m) ** 2 for v in vals) / (n2 - 1)), 2)

    fb_sd = stdev(first_bites)
    lb_sd = stdev(last_bites)
    late_days = sum(1 for r in daily_rows if r["late_eating_flag"])
    sleep_onset_avg = _avg_sleep_onset_hour(start_date, end_date)

    pre_sleep_gap = None
    if sleep_onset_avg is not None:
        gap = sleep_onset_avg - avg_lb
        if gap < 0:
            gap += 24
        pre_sleep_gap = round(gap, 1)

    # Panda/Salk 2018: 10h optimal TRF window; 12h minimum for metabolic benefit
    trf_flags = []
    if avg_win > 12:
        trf_flags.append(
            f"Average eating window is {avg_win}h — wider than the 10h TRF target. Try compressing to <10h for metabolic benefit."
        )
    if fb_sd is not None and fb_sd > 1.5:
        trf_flags.append(f"First bite time varies by {fb_sd}h SD — inconsistent circadian signalling. Aim for <1h variation.")
    if late_days > n * 0.3:
        trf_flags.append(f"Eating after 8pm on {late_days}/{n} days. Late eating suppresses melatonin-mediated metabolic signalling.")
    # >=3h pre-sleep fasting allows GLP-1 clearance (Panda 2018, Huberman); <2.5h too close
    if pre_sleep_gap is not None and pre_sleep_gap < 2.5:
        trf_flags.append(
            f"Average last bite → sleep gap is only {pre_sleep_gap}h. Panda recommends ≥3h to allow GLP-1 clearance before sleep onset."
        )

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "eating_window": {
            "avg_first_bite": d2hm(avg_fb),
            "avg_last_bite": d2hm(avg_lb),
            "avg_window_hrs": avg_win,
            "first_bite_consistency_sd_hrs": fb_sd,
            "last_bite_consistency_sd_hrs": lb_sd,
            "consistency_n_days": n,
            "trf_status": "OPTIMAL" if avg_win <= 10 else "BORDERLINE" if avg_win <= 12 else "WIDE",
        },
        "late_eating": {"days_eating_after_8pm": late_days, "pct_days": round(late_days / n * 100, 1)},
        "sleep_overlap": {
            "avg_last_bite_to_sleep_hrs": pre_sleep_gap,
            "status": (
                "GOOD"
                if pre_sleep_gap and pre_sleep_gap >= 3
                else "MARGINAL" if pre_sleep_gap and pre_sleep_gap >= 2 else "TOO_CLOSE" if pre_sleep_gap else "no_sleep_data"
            ),
        },
        "circadian_flags": trf_flags,
        "daily_breakdown": daily_rows,
    }


def _get_nutrition_summary(args):
    """
    Daily macro breakdown + rolling averages for any date range.
    Returns per-day rows and period averages for calories, protein, carbs, fat, fiber,
    sodium, caffeine, omega-3, and key micronutrients.
    """
    start_date, end_date = _nutrition_default_range(args)

    items = query_source("macrofactor", start_date, end_date)

    if not items:
        return {"error": "No MacroFactor data found for the requested range.", "start_date": start_date, "end_date": end_date}

    MACRO_FIELDS = [
        ("total_calories_kcal", "calories_kcal"),
        ("total_protein_g", "protein_g"),
        ("total_carbs_g", "carbs_g"),
        ("total_fat_g", "fat_g"),
        ("total_fiber_g", "fiber_g"),
        ("total_sodium_mg", "sodium_mg"),
        ("total_caffeine_mg", "caffeine_mg"),
        ("total_omega3_total_g", "omega3_total_g"),
        ("total_potassium_mg", "potassium_mg"),
        ("total_magnesium_mg", "magnesium_mg"),
        ("total_vitamin_d_mcg", "vitamin_d_mcg"),
        ("total_alcohol_g", "alcohol_g"),
    ]

    daily_rows = []
    for item in sorted(items, key=lambda x: x.get("date", "")):  # `.get`: a row with no date must not KeyError the tool
        row = {"date": item.get("date", ""), "entries_logged": item.get("entries_count", 0)}
        for db_field, out_field in MACRO_FIELDS:
            v = item.get(db_field)
            if v is not None:
                row[out_field] = float(v)
        # Derived: protein % of calories
        cal = row.get("calories_kcal", 0)
        prot = row.get("protein_g", 0)
        if cal > 0:
            row["protein_pct_of_calories"] = round(prot * 4 / cal * 100, 1)
        # Board rec 1A: fiber density (Norton) — normalizes for caloric intake
        fib = row.get("fiber_g", 0)
        if cal > 0 and fib > 0:
            row["fiber_per_1000kcal"] = round(fib / (cal / 1000), 1)
        daily_rows.append(row)

    # Period averages
    def field_n(field):
        return sum(1 for r in daily_rows if field in r)

    def avg(field):
        vals = [r[field] for r in daily_rows if field in r]
        return round(sum(vals) / len(vals), 1) if vals else None

    averages = {out: avg(out) for _, out in MACRO_FIELDS}
    averages["protein_pct_of_calories"] = avg("protein_pct_of_calories")
    averages["fiber_per_1000kcal"] = avg("fiber_per_1000kcal")

    # Reference targets (from profile / common goals)
    # Matthew-specific targets: 2400 kcal deficit, 180g protein (~0.8g/lb BW)
    TARGETS = {
        "calories_kcal": 2400,
        "protein_g": 180,
        "fiber_g": _FIBER_TARGET_G,
        "fiber_per_1000kcal": 14,  # Board rec 1A (Norton): minimum fiber density
        "sodium_mg": 2300,
        "omega3_total_g": 2.0,
        "vitamin_d_mcg": 20,
    }
    target_comparison = {}
    for field, target in TARGETS.items():
        avg_val = averages.get(field)
        if avg_val is not None:
            target_comparison[field] = {
                "target": target,
                "average": avg_val,
                "gap": round(avg_val - target, 1),
                "pct_of_target": round(avg_val / target * 100, 1),
                # ADR-105: `avg()` averages a per-FIELD sample, but the only n published used to
                # be `period.days_with_data` — the count of ROWS. A nutrient MacroFactor tracks
                # sporadically averaged over a smaller, invisible sample than the payload
                # advertised. Each comparison now states the n behind its own number.
                "n": field_n(field),
            }

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_data": len(daily_rows)},
        "daily_averages": averages,
        "target_comparison": target_comparison,
        "daily_breakdown": daily_rows,
    }


def _get_macro_targets(args):
    """
    Compare actual nutrition vs calorie / protein targets.
    Pulls recent Withings weight to compute TDEE-based calorie target,
    then scores daily adherence to each macro goal.
    """
    end_date = args.get("end_date", _nutrition_through_date())
    days = int(args.get("days", 30))
    start_date = args.get("start_date") or ((datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d"))
    calorie_target = args.get("calorie_target")  # optional override
    protein_target = args.get("protein_target")  # optional override

    items = query_source("macrofactor", start_date, end_date)

    if not items:
        return {"error": "No MacroFactor data found.", "start_date": start_date, "end_date": end_date}

    # Pull current weight for TDEE estimate if no calorie_target override
    if not calorie_target:
        try:
            wt_items = query_source(
                "withings", (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d"), end_date
            )
            weight_lbs = _latest_weight_lbs(wt_items)
            if weight_lbs is not None:
                calorie_target = _mifflin_tdee(weight_lbs)
        except Exception:
            pass
    calorie_target = calorie_target or 2400  # Matthew-specific targets: 2400 kcal deficit, 180g protein (~0.8g/lb BW)
    protein_target = protein_target or 180  # Matthew-specific targets: 2400 kcal deficit, 180g protein (~0.8g/lb BW)

    def measured(item, field):
        """The day's rollup for `field`, or None when the day carries none.

        ADR-104: `float(item.get(field, 0) or 0)` folded an UNLOGGED day into the adherence
        denominator as a failure. `macrofactor_lambda` drops zero-valued rollups at write
        time, so a day it could not total is exactly a day with the key absent — and the
        hit-rate he is graded on fell for days he simply did not upload.
        """
        raw = item.get(field)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    daily_rows = []
    hits = {"calorie": 0, "protein": 0, "fiber": 0}
    measured_days = {"calorie": 0, "protein": 0, "fiber": 0}
    for item in sorted(items, key=lambda x: x.get("date", "")):  # `.get`: a row with no date must not KeyError the tool
        cal = measured(item, "total_calories_kcal")
        prot = measured(item, "total_protein_g")
        fiber = measured(item, "total_fiber_g")
        fat = measured(item, "total_fat_g")
        carbs = measured(item, "total_carbs_g")

        hit_cal = (0.85 <= cal / calorie_target <= 1.10) if cal is not None else None
        hit_prot = (prot >= protein_target * 0.95) if prot is not None else None
        hit_fiber = (fiber >= _FIBER_TARGET_G) if fiber is not None else None
        for axis, hit in (("calorie", hit_cal), ("protein", hit_prot), ("fiber", hit_fiber)):
            if hit is not None:
                measured_days[axis] += 1
                hits[axis] += int(hit)

        daily_rows.append(
            {
                "date": item.get("date", ""),
                "calories_kcal": round(cal, 0) if cal is not None else None,
                "calories_pct": round(cal / calorie_target * 100, 1) if cal is not None else None,
                "protein_g": round(prot, 1) if prot is not None else None,
                "protein_pct": round(prot / protein_target * 100, 1) if prot is not None else None,
                "fat_g": round(fat, 1) if fat is not None else None,
                "carbs_g": round(carbs, 1) if carbs is not None else None,
                "fiber_g": round(fiber, 1) if fiber is not None else None,
                "hit_calorie_target": hit_cal,
                "hit_protein_target": hit_prot,
                "hit_fiber_target": hit_fiber,
            }
        )

    def hit_pct(axis):
        n_axis = measured_days[axis]
        return round(hits[axis] / n_axis * 100, 1) if n_axis else None

    n = len(daily_rows)
    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "targets": {
            "calories_kcal": calorie_target,
            "protein_g": protein_target,
            "fiber_g": _FIBER_TARGET_G,
            "note": "Calorie target estimated from TDEE (Mifflin-St Jeor × 1.55 activity factor) unless overridden.",
        },
        "adherence": {
            "calorie_target_hit_pct": hit_pct("calorie"),
            "protein_target_hit_pct": hit_pct("protein"),
            "fiber_target_hit_pct": hit_pct("fiber"),
            # The n behind each rate — days that actually carried the rollup, not days in range.
            "days_scored": dict(measured_days),
        },
        "daily_breakdown": daily_rows,
    }


def tool_get_nutrition(args):
    """
    Unified nutrition intelligence dispatcher. Routes to the appropriate
    underlying function based on the 'view' parameter.
    """
    VALID_VIEWS = {
        "summary": _get_nutrition_summary,
        "macros": _get_macro_targets,
        "meal_timing": _get_meal_timing,
        "micronutrients": _get_micronutrient_report,
    }
    view = (args.get("view") or "summary").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "Default is 'summary'. Use 'macros' for calorie/protein adherence, 'meal_timing' for eating window analysis, 'micronutrients' for RDA scoring.",
        }
    return VALID_VIEWS[view](args)


# ── BS-12: Deficit Sustainability Tracker ────────────────────────────────────


def tool_get_deficit_sustainability(args):
    """
    BS-12: Multi-signal early warning for unsustainable caloric deficit.
    Monitors 5 channels simultaneously over a rolling window:
      1. HRV trend (Whoop) — declining HRV under deficit = ANS stress
      2. Sleep quality (Whoop) — efficiency + deep sleep % degradation
      3. Recovery trend (Whoop) — sustained low recovery under deficit
      4. Habit completion (Habitify daily `completion_pct`) — behavioural unravelling
      5. Training output (Strava + Hevy) — volume/intensity dropping
    When 3+ of 5 degrade concurrently during an active deficit → flag.
    Attia / Huberman: aggressive deficits destroy adherence and muscle.
    """
    end_date = args.get("end_date", _nutrition_through_date())
    days = int(args.get("days", 14))
    start_date = args.get("start_date") or (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    # ── 1. Caloric deficit detection ──
    mf_items = query_source("macrofactor", start_date, end_date)
    if len(mf_items) < 7:
        return {"error": f"Need ≥7 days of MacroFactor data. Found {len(mf_items)}."}

    cals = [float(i.get("total_calories_kcal", 0) or 0) for i in mf_items if i.get("total_calories_kcal")]
    if not cals:
        # ADR-104: seven rows that carry no calorie rollup clear the `len(mf_items) < 7`
        # floor and then averaged to a factual ZERO intake, making `tdee - 0` a 100%
        # "aggressive" deficit fabricated entirely out of missing data — with every
        # severity verdict downstream computed against it. Absent intake is an error,
        # exactly as the <7-day case already is.
        return {"error": f"Need ≥7 days with a calorie rollup. Found {len(mf_items)} MacroFactor days, none carrying total_calories_kcal."}
    avg_cal = sum(cals) / len(cals)

    # Estimate TDEE from profile or Withings
    profile = get_profile()
    tdee_estimate = profile.get("tdee_estimate")
    if not tdee_estimate:
        weight_lbs = _latest_weight_lbs(query_source("withings", start_date, end_date))
        # Matthew-specific TDEE fallback for ~220lb moderately active male when the scale is silent
        tdee_estimate = _mifflin_tdee(weight_lbs) if weight_lbs is not None else 2400

    deficit_kcal = round(tdee_estimate - avg_cal)
    deficit_pct = round(deficit_kcal / tdee_estimate * 100, 1) if tdee_estimate else 0
    in_deficit = deficit_kcal > 200

    # ── 2. Pull multi-source data ──
    sources = parallel_query_sources(["whoop", "habitify", "strava", "hevy"], start_date, end_date)
    whoop_items = sorted(sources.get("whoop", []), key=lambda x: x.get("date", ""))
    habit_items = sorted(sources.get("habitify", []), key=lambda x: x.get("date", ""))
    strava_items = sorted(sources.get("strava", []), key=lambda x: x.get("date", ""))

    def safe_avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    def trend_direction(vals):
        """Simple: compare last-third avg to first-third avg."""
        v = [x for x in vals if x is not None]
        if len(v) < 6:
            return "insufficient_data", 0
        third = len(v) // 3
        first_avg = sum(v[:third]) / third
        last_avg = sum(v[-third:]) / third
        if first_avg == 0:
            return "stable", 0
        delta_pct = round((last_avg - first_avg) / abs(first_avg) * 100, 1)
        if delta_pct < -5:
            return "declining", delta_pct
        elif delta_pct > 5:
            return "improving", delta_pct
        return "stable", delta_pct

    # ── Channel 1: HRV trend ──
    hrv_vals = [float(w.get("hrv", 0)) for w in whoop_items if w.get("hrv")]
    hrv_dir, hrv_delta = trend_direction(hrv_vals)
    hrv_avg = safe_avg(hrv_vals)
    hrv_degraded = hrv_dir == "declining" and abs(hrv_delta) > 8

    # ── Channel 2: Sleep quality ──
    eff_vals = [
        float(w.get("sleep_efficiency_pct") or w.get("sleep_efficiency_percentage", 0))
        for w in whoop_items
        if w.get("sleep_efficiency_pct") or w.get("sleep_efficiency_percentage")
    ]
    deep_vals = [
        float(w.get("slow_wave_sleep_hours", 0)) / max(float(w.get("sleep_duration_hours", 1)), 1) * 100
        for w in whoop_items
        if w.get("slow_wave_sleep_hours") and w.get("sleep_duration_hours")
    ]
    eff_dir, eff_delta = trend_direction(eff_vals)
    deep_dir, deep_delta = trend_direction(deep_vals)
    sleep_degraded = (eff_dir == "declining" and abs(eff_delta) > 3) or (deep_dir == "declining" and abs(deep_delta) > 8)

    # ── Channel 3: Recovery trend ──
    rec_vals = [float(w.get("recovery_score", 0)) for w in whoop_items if w.get("recovery_score")]
    rec_dir, rec_delta = trend_direction(rec_vals)
    rec_avg = safe_avg(rec_vals)
    recovery_degraded = rec_dir == "declining" and abs(rec_delta) > 10

    # ── Channel 4: Habit completion ──
    # Reader/writer agreement: `ingestion/habitify_lambda.py` writes `completion_pct`
    # (pending-aware) and `completion_pct_strict`, plus `by_group[*].pct` over the nine
    # P40 groups — there is no "Tier 0" partition and NOTHING in the repo has ever
    # written `tier_0_completion_rate` or `t0_rate`. This channel therefore never carried
    # a value: the list was always [], the direction always "insufficient_data" and
    # `habits_degraded` always False, so behavioural unravelling — the earliest and most
    # actionable sign a cut is failing — was structurally invisible to the tool built to
    # catch it.
    t0_rates = []
    for h in habit_items:
        t0 = h.get("completion_pct")
        if t0 is None:
            t0 = h.get("completion_pct_strict")
        if t0 is not None:
            t0_rates.append(float(t0))
    t0_dir, t0_delta = trend_direction(t0_rates)
    t0_avg = safe_avg(t0_rates)
    habits_degraded = t0_dir == "declining" and abs(t0_delta) > 10

    # ── Channel 5: Training output ──
    daily_kj = {}
    for s in strava_items:
        d = s.get("date", "")
        kj = float(s.get("total_kilojoules", 0) or 0)
        daily_kj[d] = daily_kj.get(d, 0) + kj
    training_vals = [daily_kj[d] for d in sorted(daily_kj)] if daily_kj else []
    train_dir, train_delta = trend_direction(training_vals)
    training_degraded = train_dir == "declining" and abs(train_delta) > 15

    # ── Composite assessment ──
    channels = [
        {"name": "HRV", "status": "degraded" if hrv_degraded else "stable", "direction": hrv_dir, "delta_pct": hrv_delta, "avg": hrv_avg},
        {"name": "Sleep Quality", "status": "degraded" if sleep_degraded else "stable", "direction": eff_dir, "delta_pct": eff_delta},
        {
            "name": "Recovery",
            "status": "degraded" if recovery_degraded else "stable",
            "direction": rec_dir,
            "delta_pct": rec_delta,
            "avg": rec_avg,
        },
        {
            "name": "Habit Completion",
            "status": "degraded" if habits_degraded else "stable",
            "direction": t0_dir,
            "delta_pct": t0_delta,
            "avg": t0_avg,
        },
        {
            "name": "Training Output",
            "status": "degraded" if training_degraded else "stable",
            "direction": train_dir,
            "delta_pct": train_delta,
        },
    ]
    degraded_count = sum(1 for c in channels if c["status"] == "degraded")

    if not in_deficit:
        severity = "NOT_IN_DEFICIT"
        recommendation = "No active deficit detected. Monitor normally."
    elif degraded_count >= 4:
        severity = "CRITICAL"
        recommendation = f"4+ channels degrading under {deficit_kcal} kcal/day deficit. Increase intake by 300-400 kcal for 5-7 days. Prioritise sleep and reduce training intensity."
    elif degraded_count >= 3:
        severity = "WARNING"
        recommendation = f"3 channels degrading under {deficit_kcal} kcal/day deficit. Consider adding 200 kcal/day for 3-5 days and scheduling a deload."
    elif degraded_count >= 2:
        severity = "WATCH"
        recommendation = "2 channels showing stress. Monitor closely — this may resolve or escalate."
    else:
        severity = "SUSTAINABLE"
        recommendation = "Deficit appears sustainable. All systems holding."

    return {
        # ADR-105/#1917: `days` is the REQUESTED window; every intake figure below is
        # computed over however many days actually carried a calorie rollup. Publishing
        # only the request let seven logged days inside a fourteen-day ask read as "days: 14".
        "period": {"start_date": start_date, "end_date": end_date, "days": days, "days_with_data": len(cals)},
        "deficit": {
            "in_deficit": in_deficit,
            "avg_intake_kcal": round(avg_cal),
            "estimated_tdee": tdee_estimate,
            "deficit_kcal": deficit_kcal,
            "deficit_pct": deficit_pct,
            "deficit_label": (
                "aggressive" if deficit_pct > 25 else "moderate" if deficit_pct > 15 else "mild" if deficit_pct > 5 else "maintenance"
            ),
        },
        "channels": channels,
        "degraded_count": degraded_count,
        "severity": severity,
        "recommendation": recommendation,
        "methodology": (
            "Monitors 5 channels: HRV trend, sleep quality, recovery, habit completion, training output. "
            "Compares first-third vs last-third of the window. 3+ concurrent degradations = deficit unsustainable. "
            "Based on Attia, Huberman: aggressive deficits erode adherence, sleep, and lean mass."
        ),
    }


# ── IC-29: Metabolic Adaptation Intelligence ─────────────────────────────────


def _get_metabolic_adaptation(args):
    """
    IC-29: TDEE divergence tracker — detects metabolic adaptation during prolonged deficit.
    Compares expected weight loss (from caloric deficit) against actual weight loss.
    When actual loss < 60% of expected → adaptation flag.
    Lyle McDonald / Layne Norton: metabolic adaptation = TDEE suppression beyond
    what weight loss alone predicts. Key signal for diet breaks and reverse diets.
    """
    end_date = args.get("end_date", _nutrition_through_date())
    weeks = int(args.get("weeks", 8))
    start_date = args.get("start_date") or (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(weeks=weeks)).strftime("%Y-%m-%d")

    # Pull nutrition + weight data
    data = parallel_query_sources(["macrofactor", "withings"], start_date, end_date)
    mf_items = sorted(data.get("macrofactor", []), key=lambda x: x.get("date", ""))
    wt_items = sorted(data.get("withings", []), key=lambda x: x.get("date", ""))

    if len(mf_items) < 14:
        return {"error": f"Need ≥14 days of MacroFactor data. Found {len(mf_items)}."}
    if len(wt_items) < 4:
        return {"error": f"Need ≥4 Withings weigh-ins. Found {len(wt_items)}."}

    # ── Weekly aggregation ──
    def iso_week(date_str):
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%G-W%V")

    weekly_cal = defaultdict(list)
    weekly_wt = defaultdict(list)
    for item in mf_items:
        d = item.get("date", "")
        cal = item.get("total_calories_kcal")
        if d and cal:
            weekly_cal[iso_week(d)].append(float(cal))
    for item in wt_items:
        d = item.get("date", "")
        wt = item.get("weight_lbs")
        if d and wt:
            weekly_wt[iso_week(d)].append(float(wt))

    weeks_sorted = sorted(set(weekly_cal.keys()) & set(weekly_wt.keys()))
    if len(weeks_sorted) < 3:
        return {"error": "Need ≥3 weeks with both nutrition and weight data."}

    # Estimate TDEE from profile or Mifflin
    profile = get_profile()
    base_tdee = profile.get("tdee_estimate")
    if not base_tdee:
        first_wt = sum(weekly_wt[weeks_sorted[0]]) / len(weekly_wt[weeks_sorted[0]])
        base_tdee = _mifflin_tdee(first_wt)

    weekly_data = []
    for wk in weeks_sorted:
        avg_cal = sum(weekly_cal[wk]) / len(weekly_cal[wk])
        avg_wt = sum(weekly_wt[wk]) / len(weekly_wt[wk])
        weekly_data.append(
            {
                "week": wk,
                "avg_cal": round(avg_cal),
                "avg_weight": round(avg_wt, 1),
                "cal_days": len(weekly_cal[wk]),
                "wt_days": len(weekly_wt[wk]),
            }
        )

    # ── Expected vs actual weight loss ──
    # 1 lb fat ≈ 3500 kcal deficit
    # ADR-104/105: charge each week only the days it actually LOGGED. Multiplying by a
    # flat 7 billed every week a full seven days of deficit regardless — `cal_days` was
    # computed two blocks above and sat unused in the very dict being iterated. At two
    # logged days a week that inflates expected loss 3.5x (8.0 lb against a real 2.3),
    # collapsing the adaptation ratio from an honest 0.91 ("NONE") to 0.26 -> SEVERE:
    # "plateau territory... check thyroid markers at next blood draw." Partial logging
    # alone manufactured a metabolic-suppression diagnosis and a medical follow-up.
    total_deficit_kcal = 0
    for wd in weekly_data:
        weekly_deficit = (base_tdee - wd["avg_cal"]) * min(wd["cal_days"], 7)
        total_deficit_kcal += max(weekly_deficit, 0)  # only count deficit weeks

    expected_loss_lbs = round(total_deficit_kcal / 3500, 1)
    actual_loss_lbs = round(weekly_data[0]["avg_weight"] - weekly_data[-1]["avg_weight"], 1)

    # Adaptation ratio: actual / expected
    if expected_loss_lbs > 0.5:
        adaptation_ratio = round(actual_loss_lbs / expected_loss_lbs, 2)
    else:
        adaptation_ratio = None

    # Weekly rate analysis
    for i, wd in enumerate(weekly_data):
        if i == 0:
            wd["weekly_loss_lbs"] = None
        else:
            wd["weekly_loss_lbs"] = round(weekly_data[i - 1]["avg_weight"] - wd["avg_weight"], 2)

    # ADR-105: `rate_slowdown_pct` compares an "early" window to a "recent" one, but the two
    # fixed slices OVERLAP below nine weeks — and at the three-week minimum this tool accepts
    # they are the IDENTICAL two weeks, publishing a 0.0% slowdown as a measured comparison of
    # a period against itself. Derive the index sets and only compare when they are disjoint.
    n_weeks = len(weekly_data)
    early_idx = set(range(1, min(5, n_weeks)))
    recent_idx = set(range(max(0, n_weeks - 4), n_weeks))
    windows_disjoint = bool(early_idx) and bool(recent_idx) and not (early_idx & recent_idx)

    recent_rates = [weekly_data[i]["weekly_loss_lbs"] for i in sorted(recent_idx) if weekly_data[i].get("weekly_loss_lbs") is not None]
    early_rates = [weekly_data[i]["weekly_loss_lbs"] for i in sorted(early_idx) if weekly_data[i].get("weekly_loss_lbs") is not None]
    recent_avg = round(sum(recent_rates) / len(recent_rates), 2) if recent_rates else None
    early_avg = round(sum(early_rates) / len(early_rates), 2) if early_rates else None

    rate_slowdown = None
    if windows_disjoint and recent_avg is not None and early_avg is not None and early_avg > 0.3:
        rate_slowdown = round((1 - recent_avg / early_avg) * 100, 1)

    # ── Severity classification ──
    if adaptation_ratio is None:
        severity = "INSUFFICIENT_DATA"
        recommendation = "Not enough deficit data to assess metabolic adaptation."
    elif actual_loss_lbs < 0:
        # A GAIN has a negative ratio, which fell through every band to SEVERE and was then
        # interpolated into "Losing only -63% of expected" — nonsense, and it is the sentence
        # a reader quotes. The severity is right; the gain needs its own sentence.
        severity = "SEVERE"
        recommendation = (
            f"Weight is UP {abs(actual_loss_lbs)} lb over this window against an expected "
            f"{expected_loss_lbs} lb LOSS from the logged deficit. Before reading this as metabolic "
            "adaptation, check the inputs: intake under-logging, water/glycogen shifts and a "
            f"stale TDEE estimate ({base_tdee} kcal) all produce this shape. Re-weigh under "
            "consistent conditions for 7-10 days, then reassess."
        )
    elif adaptation_ratio >= 0.85:
        severity = "NONE"
        recommendation = "Weight loss tracking close to expected. No adaptation detected."
    elif adaptation_ratio >= 0.60:
        severity = "MILD"
        recommendation = (
            f"Losing {round(adaptation_ratio*100)}% of expected. Mild adaptation is normal "
            "during sustained deficit. Consider a 1-week maintenance-calorie diet break "
            "every 6-8 weeks (Trexler et al.)."
        )
    elif adaptation_ratio >= 0.35:
        severity = "MODERATE"
        recommendation = (
            f"Losing only {round(adaptation_ratio*100)}% of expected. TDEE has likely "
            "suppressed significantly. Recommend a 10-14 day diet break at estimated maintenance "
            f"({base_tdee} kcal) to restore metabolic rate before resuming deficit."
        )
    else:
        severity = "SEVERE"
        recommendation = (
            f"Losing only {round(adaptation_ratio*100)}% of expected — plateau territory. "
            "Strong recommendation: 2-3 week reverse diet (increase 100 kcal/week), "
            "then reassess TDEE before resuming any deficit. Check thyroid markers (TSH, T3, T4) "
            "at next blood draw."
        )

    return {
        "period": {"start_date": start_date, "end_date": end_date, "weeks_analysed": len(weeks_sorted)},
        "metabolic_adaptation": {
            "expected_loss_lbs": expected_loss_lbs,
            "actual_loss_lbs": actual_loss_lbs,
            "adaptation_ratio": adaptation_ratio,
            "severity": severity,
            "estimated_base_tdee": base_tdee,
        },
        "rate_analysis": {
            "early_avg_lbs_per_week": early_avg,
            "recent_avg_lbs_per_week": recent_avg,
            "rate_slowdown_pct": rate_slowdown,
            "rate_windows_disjoint": windows_disjoint,
        },
        "weekly_data": weekly_data,
        "recommendation": recommendation,
        "methodology": (
            "Compares cumulative caloric deficit (intake vs estimated TDEE) to actual weight change. "
            "Adaptation ratio = actual_loss / expected_loss. <0.60 = moderate adaptation, <0.35 = severe. "
            "Based on Trexler, McDonald, Norton metabolic adaptation frameworks. "
            "Note: weight fluctuations, water retention, and measurement error add noise — "
            "minimum 3-week window recommended for reliable signal."
        ),
    }
