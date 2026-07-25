"""lambdas/web/site_api_nutrition.py — nutrition energy + macro endpoints (nutrition_overview, deficit_sustainability).

Split out of site_api_observatory.py (#1654 slice 3 — god-module breakup). The
routed handler entrypoints stay in the site_api_observatory facade as thin
delegators; this module holds the logic. Handlers receive the facade's globals()
as `_g` and read the monkeypatched/injectable state (table / _query_source /
_experiment_date / EXPERIMENT_START) via `_g["<name>"]`. This module does NOT
import the facade — no import cycle. All other shared helpers come straight from
site_api_common (identical binding semantics to the pre-split facade).
"""

import os
from datetime import datetime, timedelta, timezone

import digest_utils  # bundled shared module — compute_confidence tiering (ADR-105)
import stats_core  # bundled shared module (#529): the one sanctioned stats implementation

from web.site_api_common import (
    _get_profile,
    _ok,
    logger,
)

_DELIVERY_PUBLIC = os.environ.get("NUTRITION_DELIVERY_PUBLIC", "").strip().lower() in ("1", "true", "yes")

_BLUEPRINT_PUBLIC = os.environ.get("NUTRITION_BLUEPRINT_PUBLIC", "").strip().lower() in ("1", "true", "yes")

_TDEE_FIELDS = ("expenditure_kcal", "tdee_kcal", "tdee", "expenditure")

_RDO_MIN_OVERLAP_DAYS = 14

_RDO_IMPACT_R = 0.15


def _resolve_mf_tdee(items):
    """Return (tdee_float, source_label) from the most recent MacroFactor record carrying
    an expenditure/TDEE value, else (None, None). The label 'macrofactor_adaptive' names
    MacroFactor's adaptive expenditure honestly — it is a measured estimate, not a guess."""
    for it in reversed(items or []):
        for field in _TDEE_FIELDS:
            raw = it.get(field)
            if raw in (None, ""):
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if val > 0:
                return val, "macrofactor_adaptive"
    return None, None


def _mifflin_tdee(weight_lbs):
    """Profile-derived TDEE estimate: Mifflin-St Jeor × 1.55 activity, from body weight
    (height 183 cm / age 35 / male are the profile constants). Callers label this
    'estimate_mifflin' — it is never conflated with MacroFactor's measured adaptive
    expenditure (#484). Returns None when weight is missing."""
    try:
        wkg = float(weight_lbs) * 0.453592
    except (TypeError, ValueError):
        return None
    if wkg <= 0:
        return None
    return round((10 * wkg + 6.25 * 182.88 - 5 * 35 + 5) * 1.55)


def _latest_weight_lbs(start, today, *, _g):
    """Most recent Withings weigh-in (lbs) in the window, or None."""
    _query_source = _g["_query_source"]
    wt = _query_source("withings", start, today)
    if not wt:
        return None
    latest = sorted(wt, key=lambda x: x.get("sk", ""))[-1]
    try:
        return float(latest.get("weight_lbs"))
    except (TypeError, ValueError):
        return None


def _recovery_deficit_overlay(deficit_by_date: dict, recovery_by_date: dict, start_date: str, end_date: str) -> dict:
    """
    RQA-08 (#388): overlay this morning's recovery score against the PRIOR day's
    caloric deficit (tdee - calories) — recovery lags the stimulus by one night,
    so day D's recovery is paired with day D-1's deficit.

    `deficit_by_date` / `recovery_by_date` are {"YYYY-MM-DD": float} maps; a
    calendar day absent from a map is data-absent, not zero. Walks every
    calendar day from start_date to end_date inclusive so a day with no
    MacroFactor upload or no Whoop sync renders as an explicit None in the
    output — never interpolated or dropped (acceptance criterion: gaps stay
    gaps). No Pearson r anywhere in the returned payload — only n, a
    compute_confidence tier, and a correlative (never causal) caption.
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return {
            "days": [],
            "overlap_days": 0,
            "min_days": _RDO_MIN_OVERLAP_DAYS,
            "ready": False,
            "confidence": "LOW",
            "caption": None,
        }

    days = []
    cur = start
    while cur <= end:
        d = cur.strftime("%Y-%m-%d")
        prior = (cur - timedelta(days=1)).strftime("%Y-%m-%d")
        days.append(
            {
                "date": d,
                "recovery": recovery_by_date.get(d),
                "prior_deficit_kcal": deficit_by_date.get(prior),
            }
        )
        cur += timedelta(days=1)

    xs = [row["prior_deficit_kcal"] for row in days if row["prior_deficit_kcal"] is not None and row["recovery"] is not None]
    ys = [row["recovery"] for row in days if row["prior_deficit_kcal"] is not None and row["recovery"] is not None]
    n = len(xs)
    ready = n >= _RDO_MIN_OVERLAP_DAYS

    r = None
    n_eff = n
    if n >= 3:
        r = stats_core.pearson_r(xs, ys, min_n=3)
        n_eff = stats_core.effective_sample_size(xs, ys)

    conf_level = digest_utils.compute_confidence(n=n, n_eff=n_eff, days_of_data=n).get("level", "LOW")

    if not ready:
        caption = (
            f"Recovery vs. yesterday's deficit: {n} overlapping day{'s' if n != 1 else ''} logged so far — the "
            f"overlay needs {_RDO_MIN_OVERLAP_DAYS}+ before it says anything about how the two move together."
        )
    elif conf_level == "LOW" or r is None:
        caption = (
            "Both lines are drawing in, but it's still too early to tell whether recovery and the prior day's "
            "deficit move together — check back as more days land."
        )
    elif abs(r) < _RDO_IMPACT_R:
        caption = "No consistent relationship has shown up yet between recovery and the prior day's deficit at this sample size."
    elif r < 0:
        caption = (
            "Recovery has tended to run lower the morning after a heavier deficit day, and higher after a lighter "
            "one — correlative, not causal, and still an early read."
        )
    else:
        caption = (
            "Recovery and the prior day's deficit have tended to move together rather than in opposite directions "
            "— correlative, not causal, and still an early read."
        )

    return {
        "days": days,
        "overlap_days": n,
        "min_days": _RDO_MIN_OVERLAP_DAYS,
        "ready": ready,
        "confidence": conf_level,
        "caption": caption,
    }


def nutrition_overview(*, _g) -> dict:
    """
    GET /api/nutrition_overview
    Returns: 30-day macro averages, protein adherence, eating window, deficit status.
    Source: MacroFactor DynamoDB partition.
    Cache: 3600s.
    """
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    d7 = _experiment_date(7)

    items = _query_source("macrofactor", d30, today)
    if not items:
        # Genesis week / no logging yet — return a shaped-but-empty 200 so the
        # site renders an honest empty state instead of a console 503.
        _empty_grp = {
            "avg_calories": None,
            "avg_protein_g": None,
            "avg_carbs_g": None,
            "avg_fat_g": None,
            "avg_fiber_g": None,
            "days": 0,
            "count": 0,
            "protein_hit_pct": 0,
        }
        return _ok(
            {
                "nutrition": {
                    "avg_calories": None,
                    "avg_protein_g": None,
                    "avg_carbs_g": None,
                    "avg_fat_g": None,
                    "avg_fiber_g": None,
                    "protein_target_g": 190,
                    "protein_hit_pct": 0,
                    "protein_hit_days": 0,
                    "protein_floor_g": 170,
                    "protein_floor_hit_pct": 0,
                    "protein_floor_hit_days": 0,
                    "days_logged": 0,
                    "tdee": None,
                    "avg_deficit": None,
                    "cal_7d_avg": None,
                    "pro_7d_avg": None,
                    # Nutrition is a manual end-of-day upload, so it is ALWAYS ~24h
                    # behind by design — "live" nutrition is the latest COMPLETE day.
                    # Never assert today as the latest (the old `latest_date: today`
                    # read as "logged today, zero calories"). today_pending says the
                    # current day's intake simply hasn't arrived yet — not a failure.
                    "latest_date": None,
                    "as_of": None,
                    "today_pending": True,
                    "lag_days": None,
                    "stalled": False,
                    "latest_calories": None,
                    "latest_protein_g": None,
                },
                "nutrition_trend": [],
                "weekday_vs_weekend": {"weekday": dict(_empty_grp), "weekend": dict(_empty_grp)},
                "eating_window": None,
                "periodization": {"training_day": dict(_empty_grp), "rest_day": dict(_empty_grp)},
                "recovery_deficit_overlay": {
                    "days": [],
                    "overlap_days": 0,
                    "min_days": _RDO_MIN_OVERLAP_DAYS,
                    "ready": False,
                    "confidence": "LOW",
                    "caption": None,
                },
            },
            cache_seconds=300,
        )

    items.sort(key=lambda x: x.get("sk", ""))

    def safe_avg(field):
        vals = [float(i[field]) for i in items if i.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def safe_sum_avg(field):
        return safe_avg(field)

    # Support both old field names (calories) and new (total_calories_kcal)
    def _mf(item, field, alt_field=None):
        v = item.get(field) or item.get(alt_field or f"total_{field}")
        if v is None and field == "calories":
            v = item.get("total_calories_kcal")
        return float(v) if v is not None else None

    cal_vals = [_mf(i, "calories") for i in items if _mf(i, "calories") is not None]
    pro_vals = [_mf(i, "protein_g", "total_protein_g") for i in items if _mf(i, "protein_g", "total_protein_g") is not None]
    carb_vals = [_mf(i, "carbs_g", "total_carbs_g") for i in items if _mf(i, "carbs_g", "total_carbs_g") is not None]
    fat_vals = [_mf(i, "fat_g", "total_fat_g") for i in items if _mf(i, "fat_g", "total_fat_g") is not None]
    fiber_vals = [_mf(i, "fiber_g", "total_fiber_g") for i in items if _mf(i, "fiber_g", "total_fiber_g") is not None]

    # One protein story on every door: target (stretch) and floor (graded) are the
    # SAME profile values daily_metrics_compute writes into canonical_facts
    # (protein_g_target/protein_g_floor). This page used to hardcode 190 and call it
    # the "floor" while the coaches graded against the real 170 floor — a reader
    # crossing doors saw two truths.
    _prof = _get_profile()
    protein_target = float(_prof.get("protein_target_g", 190))
    protein_floor = float(_prof.get("protein_floor_g", 170))
    protein_hit_days = sum(1 for v in pro_vals if v >= protein_target)
    protein_hit_pct = round(protein_hit_days / len(pro_vals) * 100) if pro_vals else 0
    floor_hit_days = sum(1 for v in pro_vals if v >= protein_floor)
    floor_hit_pct = round(floor_hit_days / len(pro_vals) * 100) if pro_vals else 0

    # Latest day
    latest = items[-1] if items else {}
    latest_date = latest.get("date") or latest.get("sk", "").replace("DATE#", "")

    # 7-day vs 30-day comparison
    items_7d = [i for i in items if (i.get("date") or i.get("sk", "").replace("DATE#", "")) >= d7]
    cal_7d = [_mf(i, "calories") for i in items_7d if _mf(i, "calories") is not None]
    pro_7d = [_mf(i, "protein_g", "total_protein_g") for i in items_7d if _mf(i, "protein_g", "total_protein_g") is not None]

    # TDEE from the most recent record carrying MacroFactor's adaptive expenditure (#484).
    # When none is present (no populated Expenditure column uploaded), fall back to a
    # profile-derived estimate from the latest weigh-in — labeled, so the deficit panel
    # shows a real (honestly-flagged) number instead of None.
    tdee, tdee_source = _resolve_mf_tdee(items)
    if tdee is None:
        est = _mifflin_tdee(_latest_weight_lbs(d30, today, _g=_g))
        if est:
            tdee, tdee_source = est, "estimate_mifflin"
    avg_cal = round(sum(cal_vals) / len(cal_vals)) if cal_vals else None
    deficit = round(tdee - avg_cal) if tdee and avg_cal else None

    # Daily trend for chart
    trend = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        trend.append(
            {
                "date": d,
                "calories": round(_mf(i, "calories")) if _mf(i, "calories") is not None else None,
                "protein_g": (
                    round(_mf(i, "protein_g", "total_protein_g"), 1) if _mf(i, "protein_g", "total_protein_g") is not None else None
                ),
                "carbs_g": round(_mf(i, "carbs_g", "total_carbs_g"), 1) if _mf(i, "carbs_g", "total_carbs_g") is not None else None,
                "fat_g": round(_mf(i, "fat_g", "total_fat_g"), 1) if _mf(i, "fat_g", "total_fat_g") is not None else None,
            }
        )

    # ── Weekday vs Weekend comparison ──
    weekday_items = []
    weekend_items = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        try:
            dow = datetime.strptime(d, "%Y-%m-%d").weekday()
        except Exception:
            continue
        if dow >= 5:
            weekend_items.append(i)
        else:
            weekday_items.append(i)

    def _group_avg(group, field, alt_field=None):
        vals = [_mf(x, field, alt_field) for x in group if _mf(x, field, alt_field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _group_pro_hit(group):
        hits = sum(1 for x in group if (_mf(x, "protein_g", "total_protein_g") or 0) >= protein_target)
        return round(hits / len(group) * 100) if group else 0

    weekday_vs_weekend = {
        "weekday": {
            "avg_calories": _group_avg(weekday_items, "calories"),
            "avg_protein_g": _group_avg(weekday_items, "protein_g", "total_protein_g"),
            "avg_carbs_g": _group_avg(weekday_items, "carbs_g", "total_carbs_g"),
            "avg_fat_g": _group_avg(weekday_items, "fat_g", "total_fat_g"),
            "avg_fiber_g": _group_avg(weekday_items, "fiber_g", "total_fiber_g"),
            "days": len(weekday_items),
            "protein_hit_pct": _group_pro_hit(weekday_items),
        },
        "weekend": {
            "avg_calories": _group_avg(weekend_items, "calories"),
            "avg_protein_g": _group_avg(weekend_items, "protein_g", "total_protein_g"),
            "avg_carbs_g": _group_avg(weekend_items, "carbs_g", "total_carbs_g"),
            "avg_fat_g": _group_avg(weekend_items, "fat_g", "total_fat_g"),
            "avg_fiber_g": _group_avg(weekend_items, "fiber_g", "total_fiber_g"),
            "days": len(weekend_items),
            "protein_hit_pct": _group_pro_hit(weekend_items),
        },
    }

    # ── Eating window (first/last meal time from food_log) ──
    eating_windows = []
    for i in items:
        food_log = i.get("food_log") or []
        times = []
        for entry in food_log:
            t = entry.get("time")
            if t:
                try:
                    parts = t.split(":")
                    hour_min = int(parts[0]) * 60 + int(parts[1])
                    times.append(hour_min)
                except (ValueError, IndexError):
                    pass
        if len(times) >= 2:
            first = min(times)
            last = max(times)
            window_hrs = round((last - first) / 60, 1)
            eating_windows.append(
                {
                    "first_meal_min": first,
                    "last_meal_min": last,
                    "window_hrs": window_hrs,
                }
            )

    eating_window = None
    if eating_windows:
        avg_first = round(sum(e["first_meal_min"] for e in eating_windows) / len(eating_windows))
        avg_last = round(sum(e["last_meal_min"] for e in eating_windows) / len(eating_windows))
        avg_window = round(sum(e["window_hrs"] for e in eating_windows) / len(eating_windows), 1)
        eating_window = {
            "avg_hours": avg_window,
            "avg_first_meal": f"{avg_first // 60}:{avg_first % 60:02d}",
            "avg_last_meal": f"{avg_last // 60}:{avg_last % 60:02d}",
            "days_with_data": len(eating_windows),
        }

    # ── Caloric periodization (training days vs rest days) ──
    strava_items_30d = _query_source("strava", d30, today)
    training_dates = set()
    for s in strava_items_30d:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")
        training_dates.add(d)

    training_day_items = []
    rest_day_items = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        if d in training_dates:
            training_day_items.append(i)
        else:
            rest_day_items.append(i)

    periodization = {
        "training_day": {
            "avg_calories": _group_avg(training_day_items, "calories"),
            "avg_protein_g": _group_avg(training_day_items, "protein_g", "total_protein_g"),
            "count": len(training_day_items),
        },
        "rest_day": {
            "avg_calories": _group_avg(rest_day_items, "calories"),
            "avg_protein_g": _group_avg(rest_day_items, "protein_g", "total_protein_g"),
            "count": len(rest_day_items),
        },
    }
    # Compute deficit for each group if TDEE is available
    if tdee:
        for key in ("training_day", "rest_day"):
            avg = periodization[key]["avg_calories"]
            periodization[key]["avg_deficit"] = round(tdee - avg) if avg else None

    # ── Loss-rate readout (P0.9): the deficit chain + sustainability flag ──
    # Phase-1 "Ignition" target: 3 lb/week ≈ 1,500 kcal/day deficit (matches the profile /
    # ai_calls Phase-1 target). The full multi-channel sustainability early-warning (HRV,
    # sleep, recovery, habits, training) lives in the get_deficit_sustainability MCP tool;
    # here we surface only the rate chain + the deficit-intensity label (same BS-12 rubric).
    TARGET_RATE_LB_WK = 3
    KCAL_PER_LB = 3500
    required_deficit = round(TARGET_RATE_LB_WK * KCAL_PER_LB / 7)  # 1500
    deficit_pct = round(deficit / tdee * 100, 1) if (deficit is not None and tdee) else None
    if deficit_pct is None:
        deficit_label = None
    elif deficit_pct > 25:
        deficit_label = "aggressive"
    elif deficit_pct > 15:
        deficit_label = "moderate"
    elif deficit_pct > 5:
        deficit_label = "mild"
    else:
        deficit_label = "maintenance"
    loss_rate = {
        "target_rate_lb_wk": TARGET_RATE_LB_WK,
        "required_deficit_kcal": required_deficit,
        "actual_deficit_kcal": deficit,
        "gap_kcal": (required_deficit - deficit) if deficit is not None else None,
        "implied_rate_lb_wk": round(deficit * 7 / KCAL_PER_LB, 1) if deficit is not None else None,
        "deficit_pct": deficit_pct,
        "deficit_label": deficit_label,
        "protein_hit_pct": protein_hit_pct,
        # The floor (170) is what "the protein floor holds" language grades against —
        # the target (190) is the stretch line, not the floor.
        "protein_floor_hit_pct": floor_hit_pct,
        "protein_floor_g": protein_floor,
    }

    # ── Meal rhythm (P1.1): per-meal timing + protein, from food_log entries (each entry
    # carries time + protein_g + calories_kcal). Powers §4 (eating-window ribbon + meal-
    # time-of-day distribution) and §2 (real avg-protein/meal + the legitimate distribution
    # score the ingestion already computes occasion-aware, reviving the P0.3 placeholder).
    def _tmin(t):
        try:
            p = str(t).split(":")
            return int(p[0]) * 60 + int(p[1])
        except (ValueError, IndexError, AttributeError):
            return None

    per_day_window = []
    bucket_protein, bucket_cal = {}, {}
    total_meals_sum = 0
    pds_vals = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        times = []
        for e in i.get("food_log") or []:
            mins = _tmin(e.get("time"))
            if mins is None:
                continue
            times.append(mins)
            b = (mins // 120) * 2  # 2-hour bucket start hour
            bucket_protein[b] = bucket_protein.get(b, 0.0) + float(e.get("protein_g") or 0)
            bucket_cal[b] = bucket_cal.get(b, 0.0) + float(e.get("calories_kcal") or 0)
        if len(times) >= 2:
            per_day_window.append({"date": d, "first_min": min(times), "last_min": max(times)})
        if i.get("total_meals"):
            total_meals_sum += int(i["total_meals"])
        if i.get("protein_distribution_score") is not None:
            pds_vals.append(float(i["protein_distribution_score"]))

    total_protein_window = sum(pro_vals) if pro_vals else 0
    meal_rhythm = {
        "avg_protein_per_meal": round(total_protein_window / total_meals_sum, 1) if total_meals_sum else None,
        "protein_distribution_score": round(sum(pds_vals) / len(pds_vals)) if pds_vals else None,
        "per_day_window": per_day_window[-14:],  # last 2 weeks for the ribbon
        "time_distribution": [
            {"hour": h, "protein_g": round(bucket_protein[h], 1), "calories": round(bucket_cal.get(h, 0))} for h in sorted(bucket_protein)
        ],
        "reference_window_hrs": 8,  # the 16:8 reference (8h eating window)
        "days_with_meal_times": len(per_day_window),
    }

    # ── Electrolytes (P1.2): sodium (raw total — ingested but NOT in the sufficiency map,
    # since it's a range not a "more is better" nutrient) + potassium, framed as the
    # water-weight honesty check on a cut. NOT a bare hydration ring (off-brand, out of scope).
    sodium_vals = [float(i["total_sodium_mg"]) for i in items if i.get("total_sodium_mg") is not None]
    _pot = ((latest or {}).get("micronutrient_sufficiency") or {}).get("potassium_mg") or {}
    electrolytes = {
        "avg_sodium_mg": round(sum(sodium_vals) / len(sodium_vals)) if sodium_vals else None,
        "sodium_ref_low": 1500,
        "sodium_ref_high": 2300,
        "potassium_pct": _pot.get("pct"),
        "days_logged": len(items),
    }

    # ── Lean mass (P1.4): from Withings body-comp → grounds the protein target as a
    # g/kg-lean muscle-retention floor in §2 (Helms: ~2.3 g/kg FFM to retain muscle on a cut).
    lean_mass = None
    wt_items = _query_source("withings", _experiment_date(60), today)
    lean_lb = None
    for w in sorted(wt_items, key=lambda x: x.get("sk", ""), reverse=True):
        if w.get("fat_free_mass_lbs") is not None:
            lean_lb = float(w["fat_free_mass_lbs"])
            break
    if lean_lb is not None:
        lean_kg = lean_lb * 0.453592
        floor_gkg = 2.3
        lean_mass = {
            "lean_mass_lb": round(lean_lb, 1),
            "lean_mass_kg": round(lean_kg, 1),
            "target_g_per_kg_lean": round(protein_target / lean_kg, 2) if lean_kg else None,
            "floor_g_per_kg_lean": floor_gkg,
            "floor_protein_g": round(lean_kg * floor_gkg),
        }

    # Latest weight (for the projection + reconciliation), from the same Withings query.
    cur_weight = None
    for w in sorted(wt_items, key=lambda x: x.get("sk", ""), reverse=True):
        if w.get("weight_lbs") is not None:
            cur_weight = float(w["weight_lbs"])
            break

    # ── Standing self-grading prediction (P2.1): project the next weight crossing from the
    # current implied rate (intake vs maintenance), with a confidence band (rate ±25%). The
    # bet + band are stated now; the verdict resolves over weeks (pending until the date).
    projection = None
    implied = loss_rate.get("implied_rate_lb_wk")
    if cur_weight is not None and implied and implied > 0:
        target_w = int((cur_weight - 0.1) // 5) * 5  # next 5-lb mark below current
        to_go = cur_weight - target_w
        now = datetime.now(timezone.utc)

        def _proj(rate):
            return (now + timedelta(weeks=to_go / rate)).strftime("%Y-%m-%d")

        projection = {
            "metric": "weight",
            "current_weight_lbs": round(cur_weight, 1),
            "target_weight_lbs": target_w,
            "implied_rate_lb_wk": implied,
            "projected_date": _proj(implied),
            "band_earliest": _proj(implied * 1.25),
            "band_latest": _proj(implied * 0.75),
            "basis": "current intake vs estimated maintenance over the logged window",
            "verdict": "pending",  # resolves confirmed/refuted/drifted as the date arrives
            "resolves_on": _proj(implied),
        }

    # ── Reconciliation (P2.2): projected loss from energy balance vs the actual Withings
    # trend. Two trajectories; the gap is the honest logging-accuracy / TDEE-drift story.
    # Gated on ≥2 weeks of overlapping days (NEVER a Pearson/correlation chip — honesty rule).
    w_series = {}
    for w in wt_items:
        dd = w.get("date") or w.get("sk", "").replace("DATE#", "")
        if w.get("weight_lbs") is not None:
            w_series[dd] = float(w["weight_lbs"])
    recon_days = []
    start_actual = None
    if tdee:
        cum_def = 0.0
        for t in trend:
            cal = t.get("calories")
            if cal is None:
                continue
            cum_def += tdee - cal
            aw = w_series.get(t["date"])
            if start_actual is None and aw is not None:
                start_actual = aw
            recon_days.append(
                {
                    "date": t["date"],
                    "projected_loss_lbs": round(cum_def / KCAL_PER_LB, 2),
                    "actual_loss_lbs": (round(start_actual - aw, 2) if (aw is not None and start_actual is not None) else None),
                }
            )
    overlap = sum(1 for r in recon_days if r["actual_loss_lbs"] is not None)
    reconciliation = {"days": recon_days, "overlap_days": overlap, "min_days": 14, "ready": overlap >= 14}
    if reconciliation["ready"]:
        _last = [r for r in recon_days if r["actual_loss_lbs"] is not None][-1]
        reconciliation["projected_loss_lbs"] = _last["projected_loss_lbs"]
        reconciliation["actual_loss_lbs"] = _last["actual_loss_lbs"]
        reconciliation["gap_lbs"] = round(_last["projected_loss_lbs"] - _last["actual_loss_lbs"], 2)

    # ── Recovery vs prior-day deficit overlay (RQA-08, #388): does the diet's
    # aggressiveness and the body's recovery move together? Deficit is keyed by the
    # SAME day-by-day (tdee - calories) math as the reconciliation chart above;
    # recovery comes from the Whoop partition. The alignment/confidence machinery
    # lives in _recovery_deficit_overlay so it's unit-testable without DynamoDB.
    whoop_items = _query_source("whoop", d30, today)
    recovery_by_date = {}
    for w in whoop_items:
        dd = w.get("date") or w.get("sk", "").replace("DATE#", "")
        if w.get("recovery_score") is not None:
            recovery_by_date[dd] = float(w["recovery_score"])
    deficit_by_date = {}
    if tdee:
        for t in trend:
            if t.get("calories") is not None:
                deficit_by_date[t["date"]] = tdee - t["calories"]
    recovery_deficit_overlay = _recovery_deficit_overlay(deficit_by_date, recovery_by_date, d30, today)

    # ── Food-delivery off-protocol tell (P2.3, PRIVATE-by-default — flag OFF). With the flag
    # off, the delivery source is never queried and nothing private enters the response.
    food_delivery = None
    if _DELIVERY_PUBLIC:
        fd_items = _query_source("food_delivery", d30, today)
        delivery_dates = {(fd.get("date") or fd.get("sk", "").replace("DATE#", "")) for fd in fd_items}
        deliv_def, home_def = [], []
        for i in items:
            cal = _mf(i, "calories")
            if cal is None or not tdee:
                continue
            dd = i.get("date") or i.get("sk", "").replace("DATE#", "")
            (deliv_def if dd in delivery_dates else home_def).append(tdee - cal)
        food_delivery = {
            "public": True,
            "delivery_days": len(deliv_def),
            "home_days": len(home_def),
            "avg_deficit_delivery": round(sum(deliv_def) / len(deliv_def)) if deliv_def else None,
            "avg_deficit_home": round(sum(home_def) / len(home_def)) if home_def else None,
        }

    # ── Present-vs-PROVEN_BLUEPRINT benchmark (P2.5, NEVER public — flag stays OFF). The
    # blueprint (BENCH-1 training_reference) is hard-private per ADR-089; with the flag off
    # (default) it is never queried and nothing blueprint-derived enters the response.
    blueprint_benchmark = None
    if _BLUEPRINT_PUBLIC:
        tr = _query_source("training_reference", "2010-01-01", today)
        latest_tr = sorted(tr, key=lambda x: x.get("sk", ""))[-1] if tr else None
        if latest_tr:
            blueprint_benchmark = {
                "public": True,
                "confidence": latest_tr.get("confidence"),
                "current_avg_protein_g": round(sum(pro_vals) / len(pro_vals), 1) if pro_vals else None,
                "protein_target_g": protein_target,
                "note": "present protein vs the proven loss-period blueprint",
            }

    # Staleness honesty (truth audit 2026-07-10): "reflects complete days — through
    # Jun 24" normalized a 16-day-dead log as routine upload lag. Emit the real lag +
    # a stalled flag graded against the macrofactor threshold in source_registry (the
    # one place staleness thresholds live) so the front-end can say "logging stopped".
    _nut_lag_days = None
    _nut_stalled = False
    if latest_date:
        try:
            from source_registry import DEFAULT_STALE_HOURS, stale_hours_overrides

            _nut_lag_days = max(0, (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(latest_date, "%Y-%m-%d")).days)
            _mf_stale_hours = stale_hours_overrides().get("macrofactor") or DEFAULT_STALE_HOURS
            _nut_stalled = _nut_lag_days * 24 > _mf_stale_hours
        except Exception as _lag_e:
            logger.warning(f"[nutrition_overview] lag computation failed (non-fatal): {_lag_e}")

    return _ok(
        {
            "nutrition": {
                "avg_calories": round(sum(cal_vals) / len(cal_vals)) if cal_vals else None,
                "avg_protein_g": round(sum(pro_vals) / len(pro_vals), 1) if pro_vals else None,
                "avg_carbs_g": round(sum(carb_vals) / len(carb_vals), 1) if carb_vals else None,
                "avg_fat_g": round(sum(fat_vals) / len(fat_vals), 1) if fat_vals else None,
                "avg_fiber_g": round(sum(fiber_vals) / len(fiber_vals), 1) if fiber_vals else None,
                "protein_target_g": protein_target,
                "protein_hit_pct": protein_hit_pct,
                "protein_hit_days": protein_hit_days,
                "protein_floor_g": protein_floor,
                "protein_floor_hit_pct": floor_hit_pct,
                "protein_floor_hit_days": floor_hit_days,
                "days_logged": len(items),
                "tdee": round(tdee) if tdee else None,
                "tdee_source": tdee_source,
                "avg_deficit": deficit,
                "cal_7d_avg": round(sum(cal_7d) / len(cal_7d)) if cal_7d else None,
                "pro_7d_avg": round(sum(pro_7d) / len(pro_7d), 1) if pro_7d else None,
                "latest_date": latest_date,
                # The latest COMPLETE day is the live nutrition state (manual end-of-day
                # upload → always ~24h behind by design). today_pending true means the
                # current day's intake simply hasn't been uploaded yet — expected, not a
                # logging gap. Front-end labels "through <as_of>", never "not logged today".
                "as_of": latest_date,
                "today_pending": bool(latest_date and latest_date < today),
                "lag_days": _nut_lag_days,
                "stalled": _nut_stalled,
                "latest_calories": round(_mf(latest, "calories")) if _mf(latest, "calories") else None,
                "latest_protein_g": (
                    round(_mf(latest, "protein_g", "total_protein_g"), 1) if _mf(latest, "protein_g", "total_protein_g") else None
                ),
            },
            "nutrition_trend": trend,
            "loss_rate": loss_rate,
            "meal_rhythm": meal_rhythm,
            "electrolytes": electrolytes,
            "lean_mass": lean_mass,
            "projection": projection,
            "reconciliation": reconciliation,
            "recovery_deficit_overlay": recovery_deficit_overlay,
            "food_delivery": food_delivery,
            "blueprint_benchmark": blueprint_benchmark,
            "weekday_vs_weekend": weekday_vs_weekend,
            "eating_window": eating_window,
            "periodization": periodization,
            # Micronutrient sufficiency + protein-distribution score — rich in the MacroFactor
            # record, surfaced nowhere before (reverse-QA). Genuinely novel + anti-Blueprint.
            "micronutrients": {
                "sufficiency": (latest or {}).get("micronutrient_sufficiency") or {},
                "avg_pct": (latest or {}).get("micronutrient_avg_pct"),
                "protein_distribution_score": (latest or {}).get("protein_distribution_score"),
                "as_of": latest_date,
            },
        },
        cache_seconds=3600,
    )


def deficit_sustainability(*, _g) -> dict:
    """
    GET /api/deficit_sustainability — RQA-05. Port of the MCP get_deficit_sustainability
    (BS-12): the multi-signal "is the cut costing you?" read. Monitors 5 channels over a
    trailing 14-day window (phase-filtered → post-genesis only): HRV, sleep quality, recovery,
    Tier-0 habit completion, training output. Each channel's first-third avg vs last-third avg
    sets a direction; concurrent degradations → a severity. Deficit context uses MacroFactor's
    real adaptive TDEE (consistent with /api/nutrition_overview), not a Harris-Benedict guess.
    Honest empty state when <7 logged days. Correlative, n=1, never alarm-red.
    """
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = _experiment_date(14)
    mf = _query_source("macrofactor", start, today)
    if len(mf) < 7:
        return _ok(
            {
                "deficit_sustainability": {
                    "available": False,
                    "days_logged": len(mf),
                    "reason": "Needs ≥7 logged days; the cut is too new to read its cost yet.",
                }
            },
            cache_seconds=3600,
        )

    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    cals = [_f(i.get("total_calories_kcal")) for i in mf]
    cals = [c for c in cals if c]
    avg_cal = round(sum(cals) / len(cals)) if cals else 0
    tdee, tdee_source = _resolve_mf_tdee(mf)
    if not tdee:  # Fallback: profile-derived Mifflin estimate from the latest weigh-in (#484)
        est = _mifflin_tdee(_latest_weight_lbs(start, today, _g=_g))
        if est:
            tdee, tdee_source = est, "estimate_mifflin"
        else:
            tdee, tdee_source = 2400, "estimate_default"
    deficit_kcal = round(tdee - avg_cal)
    deficit_pct = round(deficit_kcal / tdee * 100, 1) if tdee else 0
    in_deficit = deficit_kcal > 200
    deficit_label = "aggressive" if deficit_pct > 25 else "moderate" if deficit_pct > 15 else "mild" if deficit_pct > 5 else "maintenance"

    src = {s: sorted(_query_source(s, start, today), key=lambda x: x.get("sk", "")) for s in ("whoop", "habitify", "strava")}
    whoop, habit, strava = src["whoop"], src["habitify"], src["strava"]

    def trend_dir(vals):
        v = [x for x in vals if x is not None]
        if len(v) < 6:
            return "insufficient_data", 0
        third = len(v) // 3
        first_avg = sum(v[:third]) / third
        last_avg = sum(v[-third:]) / third
        if first_avg == 0:
            return "stable", 0
        dp = round((last_avg - first_avg) / abs(first_avg) * 100, 1)
        return ("declining", dp) if dp < -5 else ("improving", dp) if dp > 5 else ("stable", dp)

    # Channel 1 — HRV
    hrv = [_f(w.get("hrv")) for w in whoop if w.get("hrv")]
    hrv_dir, hrv_d = trend_dir(hrv)
    hrv_bad = hrv_dir == "declining" and abs(hrv_d) > 8
    # Channel 2 — sleep quality (efficiency OR deep%)
    eff = [
        _f(w.get("sleep_efficiency_pct") or w.get("sleep_efficiency_percentage"))
        for w in whoop
        if (w.get("sleep_efficiency_pct") or w.get("sleep_efficiency_percentage"))
    ]
    deep = [
        (_f(w.get("slow_wave_sleep_hours")) or 0) / max(_f(w.get("sleep_duration_hours")) or 1, 1) * 100
        for w in whoop
        if w.get("slow_wave_sleep_hours") and w.get("sleep_duration_hours")
    ]
    eff_dir, eff_d = trend_dir(eff)
    deep_dir, deep_d = trend_dir(deep)
    sleep_bad = (eff_dir == "declining" and abs(eff_d) > 3) or (deep_dir == "declining" and abs(deep_d) > 8)
    # Surface the sub-signal that actually triggered the strain (deep% can flag while
    # efficiency holds) so the displayed direction never reads "stable" next to "strain".
    if sleep_bad and eff_dir != "declining":
        eff_dir, eff_d = deep_dir, deep_d
    # Channel 3 — recovery
    rec = [_f(w.get("recovery_score")) for w in whoop if w.get("recovery_score")]
    rec_dir, rec_d = trend_dir(rec)
    rec_bad = rec_dir == "declining" and abs(rec_d) > 10
    # Channel 4 — Tier-0 habit completion
    t0 = [
        _f(h.get("tier_0_completion_rate") or h.get("t0_rate"))
        for h in habit
        if (h.get("tier_0_completion_rate") or h.get("t0_rate")) is not None
    ]
    t0_dir, t0_d = trend_dir(t0)
    t0_bad = t0_dir == "declining" and abs(t0_d) > 10
    # Channel 5 — training output (Strava kJ/day)
    daily_kj = {}
    for s in strava:
        d = s.get("sk", "").replace("DATE#", "")
        daily_kj[d] = daily_kj.get(d, 0) + (_f(s.get("total_kilojoules")) or 0)
    train = [daily_kj[d] for d in sorted(daily_kj)]
    train_dir, train_d = trend_dir(train)
    train_bad = train_dir == "declining" and abs(train_d) > 15

    channels = [
        {"name": "HRV", "status": "degraded" if hrv_bad else "stable", "direction": hrv_dir, "delta_pct": hrv_d},
        {"name": "Sleep quality", "status": "degraded" if sleep_bad else "stable", "direction": eff_dir, "delta_pct": eff_d},
        {"name": "Recovery", "status": "degraded" if rec_bad else "stable", "direction": rec_dir, "delta_pct": rec_d},
        {"name": "Habit completion", "status": "degraded" if t0_bad else "stable", "direction": t0_dir, "delta_pct": t0_d},
        {"name": "Training output", "status": "degraded" if train_bad else "stable", "direction": train_dir, "delta_pct": train_d},
    ]
    degraded = sum(1 for c in channels if c["status"] == "degraded")
    if not in_deficit:
        severity, verdict = "not_in_deficit", "No active deficit right now — nothing to strain."
    elif degraded >= 4:
        severity, verdict = (
            "critical",
            "Four-plus systems are bending under the deficit at once — the cut is outrunning recovery. Time to eat a little more and back off intensity.",
        )
    elif degraded >= 3:
        severity, verdict = (
            "warning",
            "Three systems are slipping together — the deficit is starting to cost more than it's worth. A small bump in food and a deload would buy it back.",
        )
    elif degraded >= 2:
        severity, verdict = "watch", "Two systems are showing strain — worth watching; this either settles or builds."
    else:
        severity, verdict = (
            "sustainable",
            "The body's absorbing the deficit — recovery, sleep, and output are holding while the weight comes off.",
        )

    return _ok(
        {
            "deficit_sustainability": {
                "available": True,
                "period": {"start": start, "end": today, "days": 14},
                "deficit": {
                    "in_deficit": in_deficit,
                    "avg_intake_kcal": avg_cal,
                    "tdee": round(tdee),
                    "tdee_source": tdee_source,
                    "deficit_kcal": deficit_kcal,
                    "deficit_pct": deficit_pct,
                    "label": deficit_label,
                },
                "channels": channels,
                "degraded_count": degraded,
                "severity": severity,
                "verdict": verdict,
            }
        },
        cache_seconds=3600,
    )
