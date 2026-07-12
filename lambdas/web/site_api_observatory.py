"""
lambdas/web/site_api_observatory.py — observatory page endpoint handlers.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 2, 2026-05-26).
These serve /api/{nutrition,training,physical,mind}_overview plus supporting
endpoints (frequent meals, meal glucose, strength benchmarks, food delivery,
strength deep-dive, journal analysis, benchmark trends, meal responses).

All shared helpers (_ok, _error, table, _query_source, _latest_item, etc.)
are imported from site_api_common — no circular references.
"""

import json
import os
import time  # noqa: F401 — used by some handlers
from datetime import datetime, timedelta, timezone
from decimal import Decimal  # noqa: F401 — kept for handlers that convert types

import digest_utils  # shared layer — compute_confidence tiering (ADR-105)
import stats_core  # shared layer (#529): the one sanctioned stats implementation
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    CORS_HEADERS,
    EXPERIMENT_START,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _experiment_date,
    _get_profile,
    _is_blocked_vice,
    _ok,
    _query_source,
    logger,
    table,
)

# ── Privacy flags (Phase 2): private-by-default behavioural / blueprint signals are gated
# at the SERVER — with the flag OFF (the default, env var unset) the private data is never
# even computed into the public API response. Flip only by setting the env var, after Matthew
# confirms. P2.3 = food-delivery off-protocol tell; P2.5 = present-vs-PROVEN_BLUEPRINT (never
# public — kept dark behind a flag that stays off).
_DELIVERY_PUBLIC = os.environ.get("NUTRITION_DELIVERY_PUBLIC", "").strip().lower() in ("1", "true", "yes")
_BLUEPRINT_PUBLIC = os.environ.get("NUTRITION_BLUEPRINT_PUBLIC", "").strip().lower() in ("1", "true", "yes")
_TRAIN_BLUEPRINT_PUBLIC = os.environ.get("TRAINING_BLUEPRINT_PUBLIC", "").strip().lower() in ("1", "true", "yes")

# ── Per-muscle volume vs landmarks (training P1.3) — compact port of the MCP classifier
# (mcp/strength_helpers.classify_exercise + _VOLUME_LANDMARKS, core-mapping fix #186) since
# the site-api package can't import mcp/. Keep in sync if the MCP map changes.
_MUSCLE_MAP = [
    (["bench press", "chest press", "pec deck", "fly", "flye", "push up", "pushup"], ["Chest", "Triceps", "Shoulders"]),
    (["overhead press", "ohp", "shoulder press", "military press", "arnold"], ["Shoulders", "Triceps"]),
    (["tricep", "skull crusher", "pushdown", "push down", "close grip", "dip"], ["Triceps", "Chest"]),
    (["pull up", "pullup", "chin up", "chinup", "lat pulldown", "pull-up", "pull-down"], ["Back", "Biceps"]),
    (["row", "cable row", "t-bar", "seated row"], ["Back", "Biceps"]),
    (["deadlift"], ["Back", "Hamstrings", "Glutes", "Quads"]),
    (["back extension", "hyperextension", "good morning"], ["Back", "Hamstrings", "Glutes"]),
    (["bicep", "curl", "hammer curl"], ["Biceps"]),
    (["squat", "goblet"], ["Quads", "Glutes", "Hamstrings"]),
    (["leg press"], ["Quads", "Glutes", "Hamstrings"]),
    (["lunge", "step up", "bulgarian"], ["Quads", "Glutes", "Hamstrings"]),
    (["leg extension", "leg curl", "hamstring curl", "nordic"], ["Quads", "Hamstrings"]),
    (["hip thrust", "glute bridge", "hip abduct", "hip adduct"], ["Glutes", "Hamstrings"]),
    (["calf", "calves"], ["Calves"]),
    (
        [
            "plank",
            "crunch",
            "ab ",
            "abs ",
            "core",
            "oblique",
            "sit up",
            "situp",
            "hanging leg",
            "windshield",
            "leg raise",
            "knee raise",
            "russian twist",
            "hollow",
            "rollout",
            "ab wheel",
            "pallof",
            "anti-rotation",
            "anti rotation",
            "dead bug",
            "deadbug",
            "bird dog",
            "carry",
            "carries",
            "farmer",
            "suitcase",
            "woodchop",
            "wood chop",
        ],
        ["Core"],
    ),
]
_LANDMARKS = {
    "Chest": {"MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Back": {"MEV": 10, "MAV_lo": 14, "MAV_hi": 20, "MRV": 25},
    "Shoulders": {"MEV": 8, "MAV_lo": 12, "MAV_hi": 20, "MRV": 25},
    "Quads": {"MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Hamstrings": {"MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Glutes": {"MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 18},
    "Biceps": {"MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Triceps": {"MEV": 6, "MAV_lo": 10, "MAV_hi": 14, "MRV": 20},
    "Calves": {"MEV": 8, "MAV_lo": 12, "MAV_hi": 16, "MRV": 20},
    "Core": {"MEV": 4, "MAV_lo": 6, "MAV_hi": 16, "MRV": 25},
}


def _classify_muscles(name):
    nl = (name or "").lower()
    for kws, muscles in _MUSCLE_MAP:
        if any(k in nl for k in kws):
            return muscles
    return ["Other"]


def _compute_muscle_volume(hevy_items, num_weeks):
    """Per-muscle working-set volume vs MEV/MAV/MRV landmarks (sets/week)."""
    sets_by_muscle = {}
    for day in hevy_items:
        for ex in day.get("exercises") or day.get("workout_exercises") or []:
            nm = ex.get("name") or ex.get("exercise_name") or ""
            working = [s for s in (ex.get("sets") or []) if str(s.get("type") or s.get("set_type") or "normal").lower() != "warmup"]
            n = len(working)
            if not n:
                continue
            for m in _classify_muscles(nm):
                if m == "Other":
                    continue
                sets_by_muscle[m] = sets_by_muscle.get(m, 0) + n
    out = []
    for m in sorted(sets_by_muscle, key=lambda x: sets_by_muscle[x], reverse=True):
        spw = round(sets_by_muscle[m] / num_weeks, 1) if num_weeks else sets_by_muscle[m]
        lm = _LANDMARKS.get(m, {"MEV": 0, "MAV_lo": 0, "MAV_hi": 0, "MRV": 99})
        if spw < lm["MEV"]:
            status = "under"
        elif spw <= lm["MAV_hi"]:
            status = "optimal"
        elif spw <= lm["MRV"]:
            status = "high"
        else:
            status = "over"
        out.append(
            {
                "muscle": m,
                "sets_per_week": spw,
                "total_sets": sets_by_muscle[m],
                "MEV": lm["MEV"],
                "MAV_lo": lm["MAV_lo"],
                "MAV_hi": lm["MAV_hi"],
                "MRV": lm["MRV"],
                "status": status,
            }
        )
    return out


# Canonical expenditure/TDEE resolution (#484). MacroFactor's daily-summary export
# writes its adaptive maintenance estimate to `expenditure_kcal`; three generations of
# reader code looked for `tdee`/`tdee_kcal`/`expenditure` — field names nothing ever
# wrote — so the deficit chain silently served None end-to-end. Resolve across all of
# them, newest-first (the latest record may predate a populated Expenditure column), and
# report honest provenance.
_TDEE_FIELDS = ("expenditure_kcal", "tdee_kcal", "tdee", "expenditure")


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


def _latest_weight_lbs(start, today):
    """Most recent Withings weigh-in (lbs) in the window, or None."""
    wt = _query_source("withings", start, today)
    if not wt:
        return None
    latest = sorted(wt, key=lambda x: x.get("sk", ""))[-1]
    try:
        return float(latest.get("weight_lbs"))
    except (TypeError, ValueError):
        return None


# ── Recovery vs prior-day deficit overlay (RQA-08, #388) ───────────────────────
# Pure alignment + confidence-gating function (no I/O — the caller fetches DDB
# items) so it's unit-testable with fixture data. Per the issue spec this NEVER
# returns a raw correlation coefficient — at this small a sample size the honest
# posture is "overlay + descriptive caption only", the same stance the
# reconciliation chart above takes and the #535 correlation-report gate
# (mcp/helpers.correlation_report) formalized for the tool tier.
_RDO_MIN_OVERLAP_DAYS = 14  # matches the reconciliation/_corr_card convention elsewhere on this page
_RDO_IMPACT_R = 0.15  # same "worth describing at all" floor as mcp/helpers._CORR_IMPACT_R


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


def handle_nutrition_overview() -> dict:
    """
    GET /api/nutrition_overview
    Returns: 30-day macro averages, protein adherence, eating window, deficit status.
    Source: MacroFactor DynamoDB partition.
    Cache: 3600s.
    """
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
        est = _mifflin_tdee(_latest_weight_lbs(d30, today))
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


def handle_deficit_sustainability() -> dict:
    """
    GET /api/deficit_sustainability — RQA-05. Port of the MCP get_deficit_sustainability
    (BS-12): the multi-signal "is the cut costing you?" read. Monitors 5 channels over a
    trailing 14-day window (phase-filtered → post-genesis only): HRV, sleep quality, recovery,
    Tier-0 habit completion, training output. Each channel's first-third avg vs last-third avg
    sets a direction; concurrent degradations → a severity. Deficit context uses MacroFactor's
    real adaptive TDEE (consistent with /api/nutrition_overview), not a Harris-Benedict guess.
    Honest empty state when <7 logged days. Correlative, n=1, never alarm-red.
    """
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
        est = _mifflin_tdee(_latest_weight_lbs(start, today))
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


# ── #1084 honest-numbers read guards (ADR-105 rigor bar) ────────────────────
# A trailing mean below these floors is noise dressed as an average: per-day
# averages need >= _MIN_DAILY_AVG_N COMPLETE days (today, still accruing, never
# counts), and weekly averages need a >= _MIN_WEEKLY_WINDOW_DAYS complete-day
# genesis-clamped window before dividing. Below the floor the field is None
# (with an explicit n/reason where the payload carries one) and front-ends
# self-hide on null.
_MIN_DAILY_AVG_N = 3
_MIN_WEEKLY_WINDOW_DAYS = 7


def handle_training_overview() -> dict:
    """
    GET /api/training_overview
    Returns: workout frequency, zone 2 minutes, training load, strength summary.
    Sources: Strava (cardio), Hevy (strength), Whoop (strain).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)
    d30 = _experiment_date(30)

    # #1084 (ADR-077 "clamped, not hidden"): the "30d" window above is genesis-
    # clamped by _experiment_date, so early in a cycle it spans far fewer than 30
    # days. Weekly averages must divide by the REAL window length (the fixed /4.3
    # understated a 2-day cycle spread over "4.3 weeks") and read None below the
    # floor rather than extrapolating a day or two out to a week.
    _win_days = max((datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d30, "%Y-%m-%d")).days, 0)
    _win_weeks = _win_days / 7.0 if _win_days >= _MIN_WEEKLY_WINDOW_DAYS else None

    # Strava activities (90 days)
    strava_items = _query_source("strava", d90, today)
    strava_30d = [s for s in strava_items if (s.get("date") or s.get("sk", "").replace("DATE#", "")) >= d30]

    # Zone 2 detection: HR between 60-70% of max HR
    max_hr = 184  # Matthew's measured max HR — matches profile.max_heart_rate
    z2_low, z2_high = max_hr * 0.60, max_hr * 0.70
    z2_minutes_30d = 0
    # Z2 is recalculated after flattening activities below
    z2_target = 150  # minutes/week

    def _z2_weekly_stats(total_min):
        # #1084: weekly average over the real (genesis-clamped) window — None
        # below the _MIN_WEEKLY_WINDOW_DAYS floor; z2_pct rides along.
        wa = round(total_min / _win_weeks) if _win_weeks is not None else None
        pct = round(wa / z2_target * 100) if (wa is not None and z2_target) else None
        return wa, pct

    # Flatten nested activities lists from day-level Strava records
    all_activities_30d = []
    for s in strava_30d:
        acts = s.get("activities") or []
        if acts:
            for a in acts:
                a["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_30d.extend(acts)
        else:
            # Fallback: treat day record itself as a single activity
            s["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_30d.append(s)

    # Deduplicate WHOOP auto-detected activities that overlap with Garmin recordings.
    # WHOOP pushes duplicate workouts to Strava (often with 0 distance). If a Garmin
    # activity of the same sport_type exists on the same day, drop the WHOOP duplicate.
    def _dedup_whoop(activities):
        by_day_type = {}
        for a in activities:
            key = (a.get("_day_date", ""), (a.get("sport_type") or "").lower())
            by_day_type.setdefault(key, []).append(a)
        deduped = []
        for key, group in by_day_type.items():
            if len(group) > 1:
                non_whoop = [a for a in group if (a.get("device_name") or "").upper() != "WHOOP"]
                deduped.extend(non_whoop if non_whoop else [group[0]])
            else:
                deduped.extend(group)
        return deduped

    all_activities_30d = _dedup_whoop(all_activities_30d)

    all_activities_90d = []
    for s in strava_items:
        acts = s.get("activities") or []
        if acts:
            for a in acts:
                a["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_90d.extend(acts)
        else:
            s["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_90d.append(s)
    all_activities_90d = _dedup_whoop(all_activities_90d)

    total_workouts_90d = len(all_activities_90d)
    total_workouts_30d = len(all_activities_30d)
    # #1084: real-window weekly rate, None below the floor (was a fixed /4.3).
    weekly_avg = round(total_workouts_30d / _win_weeks, 1) if _win_weeks is not None else None

    # Activity type breakdown (30d)
    type_counts = {}
    for a in all_activities_30d:
        sport = a.get("sport_type") or a.get("type") or "Other"
        type_counts[sport] = type_counts.get(sport, 0) + 1
    top_activities = sorted(type_counts.items(), key=lambda x: -x[1])[:8]

    # Total training minutes and distance (30d)
    def _act_minutes(a):
        return float(a.get("duration_minutes") or a.get("moving_time_minutes") or (a.get("moving_time_seconds") or 0) / 60 or 0)

    def _act_miles(a):
        if a.get("distance_miles"):
            return float(a["distance_miles"])
        if a.get("distance_meters"):
            return float(a["distance_meters"]) * 0.000621371
        if a.get("distance"):
            return float(a["distance"]) / 1609.34
        return 0.0

    total_minutes_30d = sum(_act_minutes(a) for a in all_activities_30d)
    total_distance_mi = sum(_act_miles(a) for a in all_activities_30d)

    # ── Modality breakdown (30d) — group by sport_type with per-modality stats ──
    from collections import defaultdict as _dd2

    modality_map = _dd2(
        lambda: {
            "count": 0,
            "total_min": 0,
            "total_mi": 0,
            "total_elev_ft": 0,
            "hr_sum": 0,
            "hr_count": 0,
            "z2_min": 0,
        }
    )
    # Also compute prior 30d for trend (days 31-60)
    d60 = _experiment_date(60)
    prior_30d_acts = []
    for s in strava_items:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")
        if d60 <= d < d30:
            acts = s.get("activities") or [s]
            prior_30d_acts.extend(acts)
    prior_type_counts = {}
    for a in prior_30d_acts:
        sport = a.get("sport_type") or a.get("type") or "Other"
        prior_type_counts[sport] = prior_type_counts.get(sport, 0) + 1

    for a in all_activities_30d:
        sport = a.get("sport_type") or a.get("type") or "Other"
        m = modality_map[sport]
        m["count"] += 1
        dur = _act_minutes(a)
        m["total_min"] += dur
        m["total_mi"] += _act_miles(a)
        m["total_elev_ft"] += float(a.get("total_elevation_gain_feet") or 0)
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        if avg_hr:
            m["hr_sum"] += float(avg_hr)
            m["hr_count"] += 1
            if z2_low <= float(avg_hr) <= z2_high:
                m["z2_min"] += dur

    modality_breakdown = []
    for sport, m in sorted(modality_map.items(), key=lambda x: -x[1]["count"]):
        prior_count = prior_type_counts.get(sport, 0)
        trend = m["count"] - prior_count  # positive = more active
        modality_breakdown.append(
            {
                "type": sport,
                "count_30d": m["count"],
                "total_minutes_30d": round(m["total_min"]),
                "avg_duration_min": round(m["total_min"] / m["count"]) if m["count"] else 0,
                "avg_hr": round(m["hr_sum"] / m["hr_count"]) if m["hr_count"] else None,
                "total_distance_mi": round(m["total_mi"], 1),
                "total_elevation_ft": round(m["total_elev_ft"]),
                "z2_minutes": round(m["z2_min"]),
                "trend_vs_prior_30d": trend,
            }
        )

    # Recalculate Z2 from all flattened activities
    # Staleness honesty (truth audit 2026-07-10): the 30d average masks a quiet current
    # week (218 min/wk average over weeks at 21 and 15 min). Track the trailing-7d Z2
    # alongside it so the front-end can show the CURRENT week vs target honestly.
    _d7_cal = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    z2_minutes_30d = 0
    z2_trailing_7d = 0.0
    for a in all_activities_30d:
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        dur = _act_minutes(a)
        if avg_hr and dur:
            if z2_low <= float(avg_hr) <= z2_high:
                z2_minutes_30d += dur
                if (a.get("_day_date") or "") >= _d7_cal:
                    z2_trailing_7d += dur
    z2_weekly_avg, z2_pct = _z2_weekly_stats(z2_minutes_30d)

    # ── Walking stats — per-day step merge, Apple-Health-first ──
    # Garmin is rate-limited/dead and emits a phantom ~298-step record that used to block
    # the Apple-Health fallback (it only fired when Garmin was *empty*). Now merge both
    # sources per day, prefer Apple Health, and only accept a Garmin-only day if it's
    # plausible (>=1000 steps) — which drops the phantom 298. (#8)
    garmin_30d = _query_source("garmin", d30, today)
    ah_30d = _query_source("apple_health", d30, today)
    _PHANTOM_STEP_FLOOR = 1000
    steps_by_date: dict = {}
    for h in ah_30d:
        if h.get("steps") and float(h["steps"]) > 0:
            _d = h.get("date") or h.get("sk", "").replace("DATE#", "")
            steps_by_date[_d] = max(steps_by_date.get(_d, 0), int(float(h["steps"])))
    for g in garmin_30d:
        if g.get("steps") and float(g["steps"]) > 0:
            _d = g.get("date") or g.get("sk", "").replace("DATE#", "")
            gs = int(float(g["steps"]))
            if _d not in steps_by_date and gs >= _PHANTOM_STEP_FLOOR:
                steps_by_date[_d] = gs  # Garmin only when Apple Health absent AND plausible
    # #1084 root cause: this mean divided by however few days existed — including
    # an n=1 "average" of ONLY today's partial count on Day 1 (ADR-105 violation:
    # no n, no uncertainty). Guard: today never counts (steps accrue until
    # midnight) and the mean needs _MIN_DAILY_AVG_N complete days; below the
    # floor it is None with an explicit reason. The per-day trend still charts
    # today — a labeled daily value, not a fabricated average.
    _complete_step_days = {d: v for d, v in steps_by_date.items() if d < today}
    avg_daily_steps_n = len(_complete_step_days)
    if avg_daily_steps_n >= _MIN_DAILY_AVG_N:
        avg_daily_steps = round(sum(_complete_step_days.values()) / avg_daily_steps_n)
        avg_daily_steps_reason = None
    else:
        avg_daily_steps = None
        avg_daily_steps_reason = "insufficient_data"
    daily_steps_trend = []
    for _step_date in sorted(steps_by_date):
        try:
            _step_dow = datetime.strptime(_step_date, "%Y-%m-%d").weekday()
        except Exception:
            _step_dow = 0
        daily_steps_trend.append({"date": _step_date, "steps": steps_by_date[_step_date], "is_weekend": _step_dow >= 5})

    walk_activities = [a for a in all_activities_30d if (a.get("sport_type") or "").lower() in ("walk", "hike")]
    ruck_activities = [
        a for a in all_activities_30d if "ruck" in (a.get("name") or "").lower() or "ruck" in (a.get("sport_type") or "").lower()
    ]
    walking_data = {
        "avg_daily_steps": avg_daily_steps,
        # #1084 / ADR-105: the claim carries its n; when the avg is None the
        # reason says why (front-ends self-hide on the null either way).
        "avg_daily_steps_n": avg_daily_steps_n,
        "avg_daily_steps_reason": avg_daily_steps_reason,
        "total_walks_30d": len(walk_activities),
        "total_rucks_30d": len(ruck_activities),
        "total_miles_30d": round(sum(_act_miles(a) for a in walk_activities), 1),
        "avg_pace_min_per_mi": None,
        "z2_minutes_walking": round(
            sum(
                _act_minutes(a)
                for a in walk_activities
                if a.get("average_heartrate") and z2_low <= float(a["average_heartrate"]) <= z2_high
            )
        ),
        "daily_steps_trend": daily_steps_trend,
    }
    # Avg walking pace (min/mi)
    walk_w_speed = [a for a in walk_activities if a.get("average_speed_ms") and float(a["average_speed_ms"]) > 0]
    if walk_w_speed:
        avg_speed_ms = sum(float(a["average_speed_ms"]) for a in walk_w_speed) / len(walk_w_speed)
        walking_data["avg_pace_min_per_mi"] = round(26.8224 / avg_speed_ms, 1) if avg_speed_ms > 0 else None

    # ── Breathwork stats (Apple Health — check both breathwork_minutes and mindful_minutes) ──
    ah_30d = _query_source("apple_health", d30, today)
    bw_sessions = 0
    bw_minutes = 0.0
    for h in ah_30d:
        _bw = float(h.get("breathwork_minutes") or 0)
        _bs = int(float(h.get("breathwork_sessions") or 0))
        _mm = float(h.get("mindful_minutes") or 0)
        if _mm > 0 and _bw == 0:
            _bw = _mm
            _bs = max(_bs, 1)
        bw_sessions += _bs
        bw_minutes += _bw
    bw_weekly_trend = []
    bw_week_map = _dd2(lambda: {"sessions": 0, "minutes": 0.0})
    for h in ah_30d:
        d = h.get("date") or h.get("sk", "").replace("DATE#", "")
        try:
            wk = datetime.strptime(d, "%Y-%m-%d").strftime("%Y-W%V")
        except Exception:
            continue
        _bw = float(h.get("breathwork_minutes") or 0)
        _bs = int(float(h.get("breathwork_sessions") or 0))
        _mm = float(h.get("mindful_minutes") or 0)
        if _mm > 0 and _bw == 0:
            _bw = _mm
            _bs = max(_bs, 1)
        bw_week_map[wk]["sessions"] += _bs
        bw_week_map[wk]["minutes"] += _bw
    for wk in sorted(bw_week_map):
        bw_weekly_trend.append({"week": wk, **bw_week_map[wk]})
    breathwork_data = {
        "sessions_30d": bw_sessions,
        "total_minutes_30d": round(bw_minutes, 1),
        "avg_session_min": round(bw_minutes / bw_sessions, 1) if bw_sessions else None,
        "weekly_trend": bw_weekly_trend[-8:],
    }

    # ── V2: Daily modality minutes (30 days) for stacked bar chart ──
    _MODALITY_MAP = {
        "WeightTraining": "strength",
        "Workout": "strength",
        "Walk": "walking",
        "Hike": "hiking",
        "Ride": "cycling",
        "VirtualRide": "cycling",
        "Stretch": "stretching",
        "Yoga": "stretching",
        "Soccer": "soccer",
        "Breathwork": "breathwork",
    }
    _daily_mod = _dd2(lambda: _dd2(float))
    for a in all_activities_30d:
        _dm_date = a.get("_day_date", "")
        _dm_sport = a.get("sport_type") or a.get("type") or "Other"
        _dm_mapped = _MODALITY_MAP.get(_dm_sport, "other")
        _dm_dur = _act_minutes(a)
        _daily_mod[_dm_date][_dm_mapped] += _dm_dur
    # Add Apple Health breathwork minutes
    for h in ah_30d:
        _bw_d = h.get("date") or h.get("sk", "").replace("DATE#", "")
        _bw_min = float(h.get("breathwork_minutes") or 0)
        if _bw_min > 0:
            _daily_mod[_bw_d]["breathwork"] += _bw_min
    _mod_keys = ["strength", "walking", "cycling", "stretching", "soccer", "hiking", "breathwork", "other"]
    daily_modality_minutes_30d = []
    _exp_start_date = datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
    _days_since_exp = (datetime.now(timezone.utc) - _exp_start_date.replace(tzinfo=timezone.utc)).days + 1
    _mod_range = min(30, _days_since_exp)
    for i in range(_mod_range):
        dt = datetime.now(timezone.utc) - timedelta(days=_mod_range - 1 - i)
        _dm_d = dt.strftime("%Y-%m-%d")
        _dm_entry = {"date": _dm_d}
        _dm_total = 0
        for _mk in _mod_keys:
            _mv = round(_daily_mod.get(_dm_d, {}).get(_mk, 0))
            _dm_entry[_mk + "_min"] = _mv
            _dm_total += _mv
        _dm_entry["total_min"] = _dm_total
        daily_modality_minutes_30d.append(_dm_entry)

    # Whoop strain (30d)
    whoop_30d = _query_source("whoop", d30, today)
    # #1084 sibling guard: day strain accrues until midnight, so today's row is a
    # partial — exclude it, and require the same complete-day floor as the steps
    # mean before claiming a 30d average.
    strain_vals = [
        float(w["strain"]) for w in whoop_30d if w.get("strain") and (w.get("date") or w.get("sk", "").replace("DATE#", ""))[:10] < today
    ]
    avg_strain = round(sum(strain_vals) / len(strain_vals), 1) if len(strain_vals) >= _MIN_DAILY_AVG_N else None

    # Whoop workouts — per-workout HR zone data (enriches Strava)
    whoop_workouts = []
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot workouts
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}whoop")
                    & Key("sk").between(f"DATE#{d30}#WORKOUT#", f"DATE#{today}#WORKOUT#~"),
                }
            )
        )
        whoop_workouts = _decimal_to_float(resp.get("Items", []))
        # Add Whoop Z2 minutes from actual HR zones to the Z2 calculation
        for ww in whoop_workouts:
            z2_from_whoop = float(ww.get("zone_2_minutes", 0) or 0)
            if z2_from_whoop > 0:
                z2_minutes_30d += z2_from_whoop
                _ww_date = ww.get("date") or ww.get("sk", "").replace("DATE#", "")[:10]
                if (_ww_date or "") >= _d7_cal:
                    z2_trailing_7d += z2_from_whoop
        # Recalculate Z2 weekly avg with Whoop data
        if whoop_workouts:
            z2_weekly_avg, z2_pct = _z2_weekly_stats(z2_minutes_30d)
    except Exception as e:
        logger.warning(f"[training_overview] Whoop workout query failed (non-fatal): {e}")

    # Hevy — latest strength session info
    hevy_items = _query_source("hevy", d30, today)
    strength_sessions_30d = len(hevy_items)
    # P1.3 — per-muscle weekly volume vs MEV/MAV/MRV (core-mapping bug fixed upstream, #186).
    _mv_weeks = max(1.0, min(30, _days_since_exp) / 7.0)
    muscle_volume = _compute_muscle_volume(hevy_items, _mv_weeks)

    # P2.3 — present-vs-PROVEN_BLUEPRINT training benchmark (NEVER public — flag stays OFF).
    # With the flag off (default) training_reference is never queried; nothing blueprint-derived
    # enters the public response (ADR-089: the blueprint may not surface to any public surface).
    training_blueprint = None
    if _TRAIN_BLUEPRINT_PUBLIC:
        _tr = _query_source("training_reference", "2010-01-01", today)
        _latest_tr = sorted(_tr, key=lambda x: x.get("sk", ""))[-1] if _tr else None
        if _latest_tr:
            training_blueprint = {
                "public": True,
                "confidence": _latest_tr.get("confidence"),
                "note": "present training vs the proven loss-period blueprint",
            }

    # Weekly trend (for chart) — use flattened activities
    from collections import defaultdict as _dd

    week_buckets = _dd(lambda: {"workouts": 0, "minutes": 0, "z2_min": 0})
    for a in all_activities_90d:
        d = a.get("_day_date") or ""
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%V")
        except Exception:
            continue
        week_buckets[week_key]["workouts"] += 1
        dur = _act_minutes(a)
        week_buckets[week_key]["minutes"] += dur
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        if avg_hr and z2_low <= float(avg_hr) <= z2_high:
            week_buckets[week_key]["z2_min"] += dur

    weekly_trend = sorted(
        [
            {"week": k, "workouts": v["workouts"], "minutes": round(v["minutes"]), "z2_min": round(v["z2_min"])}
            for k, v in week_buckets.items()
        ],
        key=lambda x: x["week"],
    )[
        -12:
    ]  # last 12 weeks

    # Recent cardio — the merged Strava + Whoop activity list, PLUS cardio/mobility logged
    # as Hevy exercises (Matthew logs Cycling/Elliptical/Stretching inside his Hevy sessions,
    # carrying distance/duration). Hevy was previously treated as strength-only, so cycling +
    # stretching never surfaced here (#5/#6). Newest first; distance in mi + km.
    _CARDIO = {
        "run",
        "running",
        "trailrun",
        "treadmill",
        "ride",
        "cycling",
        "virtualride",
        "ebikeride",
        "walk",
        "hike",
        "row",
        "rowing",
        "swim",
        "swimming",
        "elliptical",
        "stairmaster",
        "stairstepper",
    }
    cardio_sessions = []
    for a in sorted(all_activities_30d, key=lambda x: x.get("_day_date", "") or "", reverse=True):
        sport = (a.get("sport_type") or a.get("type") or "").strip()
        mi = _act_miles(a)
        if sport.lower() not in _CARDIO and not mi:
            continue
        cardio_sessions.append(
            {
                "date": a.get("_day_date"),
                "sport": sport or "Activity",
                "distance_mi": round(mi, 2) if mi else None,
                "minutes": round(_act_minutes(a)) or None,
                "avg_hr": a.get("average_heartrate") or a.get("avg_hr"),
                "source": "whoop" if a.get("strain") is not None else "strava",
            }
        )
        if len(cardio_sessions) >= 20:
            break

    # Fold in cardio/mobility-bearing Hevy exercises (#5/#6). Each exercise's sets carry
    # distance_m / duration_sec; sum per exercise per workout. Mobility (Stretching/Yoga)
    # shows as a session even with no distance.
    _HEVY_CARDIO = {"cycling", "elliptical", "rowing", "treadmill", "stair", "ski erg", "ski-erg", "assault", "echo bike", "air bike"}
    _HEVY_MOBILITY = {"stretching", "stretch", "mobility", "yoga", "foam roll"}
    hevy_cardio_30d = _query_source("hevy", d30, today)
    _hevy_cardio_min = 0.0  # P0.4: Hevy bike/elliptical steady-cardio minutes → Zone-2 base
    for w in sorted(hevy_cardio_30d, key=lambda x: x.get("date") or x.get("sk", ""), reverse=True):
        wdate = w.get("date") or w.get("sk", "").replace("DATE#", "")[:10]
        for ex in w.get("exercises") or []:
            nm = (ex.get("name") or ex.get("exercise_name") or "").strip()
            nl = nm.lower()
            is_cardio = any(k in nl for k in _HEVY_CARDIO)
            is_mob = any(k in nl for k in _HEVY_MOBILITY)
            if not (is_cardio or is_mob):
                continue
            sets = ex.get("sets") or []
            dist_m = sum(float(s.get("distance_m") or 0) for s in sets)
            secs = sum(float(s.get("duration_sec") or 0) for s in sets)
            if is_cardio and secs:
                _hevy_cardio_min += secs / 60.0
                if (wdate or "") >= _d7_cal:
                    z2_trailing_7d += secs / 60.0
            cardio_sessions.append(
                {
                    "date": wdate,
                    "sport": nm or ("Mobility" if is_mob else "Cardio"),
                    "distance_mi": round(dist_m * 0.000621371, 2) if dist_m else None,
                    "minutes": round(secs / 60) or None,
                    "avg_hr": None,
                    "modality": "mobility" if is_mob else "cardio",
                    "source": "hevy",
                }
            )
    cardio_sessions = sorted(cardio_sessions, key=lambda x: x.get("date") or "", reverse=True)[:20]

    # P0.4 — Zone-2 is cross-source: fold Hevy bike/elliptical minutes (logged steady
    # cardio, no HR stream) into the Z2 base alongside Strava + Whoop. Never Strava-only.
    if _hevy_cardio_min:
        z2_minutes_30d += _hevy_cardio_min
        z2_weekly_avg, z2_pct = _z2_weekly_stats(z2_minutes_30d)

    return _ok(
        {
            "training": {
                "workouts_30d": total_workouts_30d,
                "workouts_90d": total_workouts_90d,
                "weekly_avg": weekly_avg,
                "total_minutes_30d": round(total_minutes_30d),
                "total_distance_mi": round(total_distance_mi, 1),
                "z2_weekly_avg_min": z2_weekly_avg,
                "z2_target_min": z2_target,
                # Staleness honesty: z2_pct is the 30d AVERAGE vs target, served uncapped
                # (a capped 100 hid that it was an average at all); z2_trailing_7d_min is
                # the current week — the number that goes quiet when training stops.
                "z2_pct": z2_pct,
                "z2_trailing_7d_min": round(z2_trailing_7d),
                "avg_strain": avg_strain,
                "strength_sessions_30d": strength_sessions_30d,
                "top_activities": [{"type": t, "count": c} for t, c in top_activities],
                "whoop_workout_count": len(whoop_workouts),
                "active_modalities": len(modality_breakdown),
                "avg_daily_steps": walking_data["avg_daily_steps"],
            },
            "modality_breakdown": modality_breakdown,
            "muscle_volume": muscle_volume,
            "training_blueprint": training_blueprint,
            "daily_modality_minutes_30d": daily_modality_minutes_30d,
            "walking": walking_data,
            "breathwork": breathwork_data,
            "weekly_trend": weekly_trend,
            "whoop_workouts": [
                {
                    "date": w.get("date"),
                    "sport_name": w.get("sport_name", "Activity"),
                    "strain": w.get("strain"),
                    "zone_2_minutes": w.get("zone_2_minutes"),
                    "zone_3_minutes": w.get("zone_3_minutes"),
                    "distance_meter": w.get("distance_meter"),
                    "average_heart_rate": w.get("average_heart_rate"),
                }
                for w in whoop_workouts[:20]
            ],
            "cardio_sessions": cardio_sessions,
        },
        cache_seconds=3600,
    )


def handle_weekly_physical_summary() -> dict:
    """
    GET /api/weekly_physical_summary
    Returns: 7-day array with per-day modality breakdown (Strava + Garmin steps + breathwork).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d7 = _experiment_date(7)

    strava_items = _query_source("strava", d7, today)
    garmin_items = _query_source("garmin", d7, today)
    ah_items = _query_source("apple_health", d7, today)

    # Build per-day maps
    garmin_by_date = {(g.get("date") or g.get("sk", "").replace("DATE#", "")): g for g in garmin_items}
    ah_by_date = {(h.get("date") or h.get("sk", "").replace("DATE#", "")): h for h in ah_items}

    # Flatten Strava activities by day, dedup by activity ID
    from collections import defaultdict

    day_activities = defaultdict(list)
    _seen_activity_ids = set()
    for s in strava_items:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")[:10]
        acts = s.get("activities") or [s]
        for a in acts:
            # Dedup: skip if we've already seen this activity ID
            _aid = str(a.get("activity_id") or a.get("id") or a.get("strava_id") or "")
            if _aid and _aid in _seen_activity_ids:
                continue
            if _aid:
                _seen_activity_ids.add(_aid)
            sport = a.get("sport_type") or a.get("type") or "Other"
            dur = float(a.get("duration_minutes") or a.get("moving_time_minutes") or (a.get("moving_time_seconds") or 0) / 60 or 0)
            day_activities[d].append({"type": sport, "minutes": round(dur)})

    # Build 7-day array
    days = []
    for i in range(7):
        dt = datetime.now(timezone.utc) - timedelta(days=6 - i)
        d = dt.strftime("%Y-%m-%d")
        dow = dt.strftime("%a")
        garmin = garmin_by_date.get(d, {})
        ah = ah_by_date.get(d, {})
        activities = day_activities.get(d, [])
        total_active_min = sum(a["minutes"] for a in activities)
        bw_min = float(ah.get("breathwork_minutes") or 0)
        mm_min = float(ah.get("mindful_minutes") or 0)
        if mm_min > 0 and bw_min == 0:
            bw_min = mm_min
        if bw_min > 0:
            activities.append({"type": "Breathwork", "minutes": round(bw_min)})
            total_active_min += bw_min
        # Steps: Apple Health first; Garmin only if AH absent AND plausible (drops the
        # phantom ~298 Garmin record — same fix as handle_training_overview, #8).
        _ah_steps = int(float(ah["steps"])) if ah.get("steps") and float(ah["steps"]) > 0 else None
        _gm_steps = int(float(garmin["steps"])) if garmin.get("steps") and float(garmin["steps"]) >= 1000 else None
        days.append(
            {
                "date": d,
                "day_of_week": dow,
                "steps": _ah_steps if _ah_steps is not None else _gm_steps,
                "activities": activities,
                "total_active_minutes": round(total_active_min),
            }
        )

    return _ok({"days": days}, cache_seconds=3600)


def handle_protein_sources() -> dict:
    """
    GET /api/protein_sources
    Returns: Top protein sources from MacroFactor food_log, aggregated by food name.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    items = _query_source("macrofactor", d30, today)
    if not items:
        return _ok({"sources": [], "as_of_date": today}, cache_seconds=300)

    from collections import defaultdict

    # Aggregate protein contribution by food name
    food_protein = defaultdict(lambda: {"total_protein": 0.0, "frequency": 0, "total_cal": 0.0})
    days_count = len(items)

    for day in items:
        food_log = day.get("food_log") or []
        for entry in food_log:
            name = (entry.get("food_name") or "").strip()
            if not name or len(name) < 3:
                continue
            pro = float(entry.get("protein_g") or 0)
            if pro < 1:
                continue  # Skip items with negligible protein
            f = food_protein[name]
            f["total_protein"] += pro
            f["frequency"] += 1
            f["total_cal"] += float(entry.get("calories_kcal") or 0)

    total_protein_all = sum(f["total_protein"] for f in food_protein.values())
    sources = []
    for name, f in sorted(food_protein.items(), key=lambda x: -x[1]["total_protein"]):
        avg_daily = round(f["total_protein"] / days_count, 1) if days_count else 0
        pct = round(f["total_protein"] / total_protein_all * 100, 1) if total_protein_all else 0
        sources.append(
            {
                "food": name,
                "avg_daily_g": avg_daily,
                "pct_of_total": pct,
                "frequency": f["frequency"],
                "avg_protein_per_serving": round(f["total_protein"] / f["frequency"], 1) if f["frequency"] else 0,
                "protein_cal_pct": round((f["total_protein"] * 4) / f["total_cal"] * 100) if f["total_cal"] > 0 else 0,
            }
        )
        if len(sources) >= 12:
            break

    return _ok(
        {
            "protein_sources": sources,
            "total_protein_30d_avg_g": round(total_protein_all / days_count, 1) if days_count else 0,
            "days_analyzed": days_count,
        },
        cache_seconds=3600,
    )


def handle_physical_overview() -> dict:
    """
    GET /api/physical_overview
    Returns: Latest + baseline DEXA scans, tape measurements, delta computations.
    Source: dexa + measurements DynamoDB partitions.
    Cache: 3600s.
    """
    datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── 1. DEXA scans (all, sorted ascending) ──
    dexa_pk = f"{USER_PREFIX}dexa"
    # clinical archive — DEXA is date-independent (owner decision 2026-06-06)
    dexa_resp = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(dexa_pk),
                "ScanIndexForward": True,
            },
            include_pilot=True,
        )
    )
    dexa_items = _decimal_to_float(dexa_resp.get("Items", []))

    # Baseline = most recent scan on or before EXPERIMENT_START (the starting point)
    # Latest = most recent scan after EXPERIMENT_START (progress since Day 1)
    latest_dexa = None
    baseline_dexa = None
    if dexa_items:
        pre_experiment = [d for d in dexa_items if (d.get("scan_date") or "") <= EXPERIMENT_START]
        post_experiment = [d for d in dexa_items if (d.get("scan_date") or "") > EXPERIMENT_START]
        baseline_dexa = pre_experiment[-1] if pre_experiment else dexa_items[0]
        if post_experiment:
            latest_dexa = post_experiment[-1]
        else:
            # No post-experiment scan yet — show baseline as the current state
            latest_dexa = baseline_dexa
            baseline_dexa = None  # no comparison until a future scan exists

    def _dexa_summary(item):
        if not item:
            return None
        bc = item.get("body_composition", {})
        bs = item.get("body_score", {})
        bone = item.get("bone", {})
        idx = item.get("indices", {})
        s360 = item.get("score_360", {})
        seg_fat = item.get("segmental_fat", {})
        seg_lean = item.get("segmental_lean", {})
        item.get("limbs", {})
        targets = item.get("targets", {})
        changes = item.get("changes_vs_baseline", {})
        return {
            "scan_date": item.get("scan_date", ""),
            "body_composition": {
                "total_mass_lb": bc.get("total_mass_lb"),
                "body_fat_pct": bc.get("body_fat_pct"),
                "fat_mass_lb": bc.get("fat_mass_lb"),
                "lean_mass_lb": bc.get("lean_mass_lb"),
                "visceral_fat_lb": bc.get("visceral_fat_lb"),
                "visceral_fat_g": bc.get("visceral_fat_g"),
                "android_fat_pct": bc.get("android_fat_pct"),
                "gynoid_fat_pct": bc.get("gynoid_fat_pct"),
                "ag_ratio": bc.get("ag_ratio"),
            },
            "body_score": {
                "grade": bs.get("grade"),
                "numeric": bs.get("numeric"),
                "percentile": bs.get("percentile"),
            },
            "bone": {
                "t_score": bone.get("t_score"),
                "z_score": bone.get("z_score"),
            },
            "indices": (
                {
                    "almi_kg_m2": idx.get("almi_kg_m2"),
                    "ffmi_kg_m2": idx.get("ffmi_kg_m2"),
                    "fmi_kg_m2": idx.get("fmi_kg_m2"),
                    "almi_percentile": idx.get("almi_percentile"),
                    "ffmi_rating": idx.get("ffmi_rating"),
                    "fmi_rating": idx.get("fmi_rating"),
                }
                if idx
                else None
            ),
            "score_360": (
                {
                    "score": s360.get("score"),
                    # Privacy: biological_age is fine to publish, but chronological_age and
                    # biological_age_delta would let a reader back out Matt's true age — omit both.
                    "biological_age": s360.get("biological_age"),
                }
                if s360
                else None
            ),
            "segmental_fat": (
                {
                    "arms_pct": seg_fat.get("arms_pct"),
                    "trunk_pct": seg_fat.get("trunk_pct"),
                    "legs_pct": seg_fat.get("legs_pct"),
                }
                if seg_fat
                else None
            ),
            "segmental_lean": (
                {
                    "total_lb": seg_lean.get("total_lb"),
                    "arms_lb": seg_lean.get("arms_lb"),
                    "trunk_lb": seg_lean.get("trunk_lb"),
                    "legs_lb": seg_lean.get("legs_lb"),
                }
                if seg_lean
                else None
            ),
            "targets": targets if targets else None,
            "changes_vs_baseline": changes if changes else None,
        }

    # Days since latest DEXA
    days_since_dexa = None
    next_dexa_recommended = None
    if latest_dexa:
        try:
            scan_dt = datetime.strptime(latest_dexa.get("scan_date", ""), "%Y-%m-%d")
            days_since_dexa = (datetime.now(timezone.utc).replace(tzinfo=None) - scan_dt).days
            next_dt = scan_dt + timedelta(days=90)
            next_dexa_recommended = next_dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # ── 2. Tape measurements (latest session) ──
    meas_pk = f"{USER_PREFIX}measurements"
    # ADR-058: tape measurements are progress-tracking — hide pilot records
    # (page shows an honest empty state until post-restart measurements exist)
    meas_resp = table.query(
        **with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(meas_pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    meas_items = _decimal_to_float(meas_resp.get("Items", []))
    tape = None
    tape_session_count = 0
    if meas_items:
        m = meas_items[0]
        # Count total sessions
        count_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot measurements
                    "KeyConditionExpression": Key("pk").eq(meas_pk),
                    "Select": "COUNT",
                }
            )
        )
        tape_session_count = count_resp.get("Count", 1)

        # Build tape data from raw measurement fields
        raw = {}
        derived = {}
        for k, v in m.items():
            if k in ("pk", "sk", "ingested_at", "source_file", "unit", "measured_by", "date", "session_number"):
                continue
            if k in ("waist_height_ratio", "bilateral_symmetry_bicep_in", "bilateral_symmetry_thigh_in", "trunk_sum_in", "limb_avg_in"):
                derived[k] = v
            elif k.endswith("_in"):
                raw[k] = v

        tape = {
            "session_date": m.get("date", m.get("sk", "").replace("DATE#", "")),
            "session_number": m.get("session_number", 1),
            **raw,
            "derived": {
                **derived,
                "waist_height_ratio_target": 0.5,
            },
        }

    # ── 3. Blood pressure (from apple_health) ──
    bp_data = None
    try:
        ah_pk = f"{USER_PREFIX}apple_health"
        ah_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot BP records
                    "KeyConditionExpression": Key("pk").eq(ah_pk) & Key("sk").begins_with("DATE#"),
                    "FilterExpression": "attribute_exists(bp_systolic) OR attribute_exists(blood_pressure_systolic)",
                    "ScanIndexForward": False,
                    "Limit": 30,
                    "ProjectionExpression": (
                        "sk, bp_systolic, bp_diastolic, blood_pressure_systolic, " "blood_pressure_diastolic, blood_pressure_readings_count"
                    ),
                }
            )
        )
        bp_items = _decimal_to_float(ah_resp.get("Items", []))
        if bp_items:
            latest_bp = bp_items[0]
            sys_val = latest_bp.get("bp_systolic") or latest_bp.get("blood_pressure_systolic")
            dia_val = latest_bp.get("bp_diastolic") or latest_bp.get("blood_pressure_diastolic")
            bp_date = latest_bp.get("sk", "").replace("DATE#", "")
            # Status classification
            bp_status = "normal"
            if sys_val and float(sys_val) >= 140 or (dia_val and float(dia_val) >= 90):
                bp_status = "high"
            elif sys_val and float(sys_val) >= 130 or (dia_val and float(dia_val) >= 80):
                bp_status = "elevated"
            # Build trend
            bp_trend = []
            for bpi in bp_items:
                s = bpi.get("bp_systolic") or bpi.get("blood_pressure_systolic")
                d = bpi.get("bp_diastolic") or bpi.get("blood_pressure_diastolic")
                if s:
                    bp_trend.append(
                        {
                            "date": bpi.get("sk", "").replace("DATE#", ""),
                            "systolic": float(s),
                            "diastolic": float(d) if d else None,
                        }
                    )
            bp_data = {
                "systolic": float(sys_val) if sys_val else None,
                "diastolic": float(dia_val) if dia_val else None,
                "date": bp_date,
                "status": bp_status,
                "readings_count": len(bp_items),
                "trend": bp_trend[:14],
            }
    except Exception as _bp_e:
        logger.warning(f"BP query failed (non-fatal): {_bp_e}")

    return _ok(
        {
            "latest_dexa": _dexa_summary(latest_dexa),
            "baseline_dexa": _dexa_summary(baseline_dexa),
            "dexa_scan_count": len(dexa_items),
            "days_since_dexa": days_since_dexa,
            "next_dexa_recommended": next_dexa_recommended,
            "tape_measurements": tape,
            "tape_session_count": tape_session_count,
            "blood_pressure": bp_data,
        },
        cache_seconds=3600,
    )


def handle_journal_analysis() -> dict:
    """
    GET /api/journal_analysis
    Returns 90-day journal theme analysis from cache partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)

    ja_pk = f"{USER_PREFIX}journal_analysis"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot journal analysis
                "KeyConditionExpression": Key("pk").eq(ja_pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))

    # Build theme frequency counts
    theme_counts = {}
    for item in items:
        for theme in item.get("themes", []):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

    total = len(items)
    top_themes = sorted(
        [{"theme": k, "count": v, "pct": round(v / max(total, 1) * 100)} for k, v in theme_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    # Sentiment trend — rolling 7-day average
    sentiment_trend = []
    daily_scores = [(item.get("date", ""), float(item.get("sentiment_score", 0))) for item in items]
    for i, (date, _) in enumerate(daily_scores):
        window = [s for _, s in daily_scores[max(0, i - 6) : i + 1]]
        sentiment_trend.append(
            {
                "date": date,
                "avg_sentiment": round(sum(window) / len(window), 3) if window else 0,
            }
        )

    daily_themes = []
    for item in items:
        # J-8 (#504): one_line_summary is a per-day journal digest — never
        # public. Aggregates (themes, sentiment) are the public surface.
        daily_themes.append(
            {
                "date": item.get("date", item.get("sk", "").replace("DATE#", "")),
                "dominant_theme": item.get("dominant_theme", "other"),
                "themes": item.get("themes", []),
                "sentiment_score": float(item.get("sentiment_score", 0)),
                "sentiment_label": item.get("sentiment_label", "neutral"),
                "word_count": item.get("word_count", 0),
            }
        )

    return _ok(
        {
            "daily_themes": daily_themes,
            "top_themes": top_themes,
            "total_analyzed": total,
            "date_range": {"start": d90, "end": today},
            "sentiment_trend": sentiment_trend,
        },
        cache_seconds=3600,
    )


def handle_mind_overview() -> dict:
    """
    GET /api/mind_overview
    Returns: mood/energy/stress trends, vice streaks, social connection quality,
    mind pillar score, cognitive patterns (when journal data is available).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    d90 = _experiment_date(90)

    # ── 1. Mind pillar from character_sheet ──
    mind_pillar = None
    cs_pk = f"{USER_PREFIX}character_sheet"
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": cs_pk, "sk": f"DATE#{date_str}"})
        record = _decimal_to_float(resp.get("Item"))
        if record:
            mp = record.get("pillar_mind", {})
            mind_pillar = {
                "level": float(mp.get("level", 1)),
                "raw_score": float(mp.get("raw_score", 0)),
                "tier": mp.get("tier", "Foundation"),
            }
            break

    # ── 2. State of mind / mood data (Apple Health How We Feel) ──
    som_items = _query_source("state_of_mind", d30, today)
    mood_entries = []
    for s in som_items:
        valence = s.get("valence")
        if valence is not None:
            mood_entries.append(
                {
                    "date": s.get("date") or s.get("sk", "").replace("DATE#", ""),
                    "valence": float(valence),
                    "label": s.get("label", ""),
                }
            )
    # Fallback: check apple_health partition for som_avg_valence (HAE writes here)
    if not mood_entries:
        ah_som = _query_source("apple_health", d30, today)
        for s in ah_som:
            valence = s.get("som_avg_valence")
            if valence is not None:
                mood_entries.append(
                    {
                        "date": s.get("date") or s.get("sk", "").replace("DATE#", ""),
                        "valence": float(valence),
                        "label": "",
                    }
                )
    mood_entries.sort(key=lambda x: x["date"])
    avg_valence = None
    if mood_entries:
        vals = [m["valence"] for m in mood_entries]
        avg_valence = round(sum(vals) / len(vals), 2)

    # ── 3. Vice streaks from habit_scores ──
    # Stage0 Fix 1 (2026-05-30): use _is_blocked_vice (matches both
    # blocked_vices full names AND blocked_vice_keywords substrings) so the
    # client doesn't have to ship a keyword list to filter what we missed.
    hs_pk = f"{USER_PREFIX}habit_scores"
    hs_resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(hs_pk),
                "ScanIndexForward": False,
                "Limit": 1,
            }
        )
    )
    hs_items = _decimal_to_float(hs_resp.get("Items", []))
    vice_data = []
    if hs_items:
        latest_hs = hs_items[0]
        raw_vs = latest_hs.get("vice_streaks") or {}
        if isinstance(raw_vs, dict):
            for name, streak_val in raw_vs.items():
                if _is_blocked_vice(name):
                    continue
                vice_data.append(
                    {
                        "name": name,
                        "current_streak": int(streak_val or 0),
                        "holding": int(streak_val or 0) > 0,
                    }
                )
        vice_data.sort(key=lambda v: -v["current_streak"])

    # ── 4. Social connection quality (interactions) ──
    int_pk = f"{USER_PREFIX}interactions"
    try:
        int_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot interactions
                    "KeyConditionExpression": Key("pk").eq(int_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}~"),
                    "ScanIndexForward": True,
                }
            )
        )
        interactions = _decimal_to_float(int_resp.get("Items", []))
    except Exception:
        interactions = []

    total_interactions = len(interactions)
    depth_counts = {"surface": 0, "meaningful": 0, "deep": 0}
    for i in interactions:
        d = (i.get("depth") or "surface").lower()
        if d in depth_counts:
            depth_counts[d] += 1
    meaningful_pct = round((depth_counts["meaningful"] + depth_counts["deep"]) / total_interactions * 100) if total_interactions else 0

    # ── 5. Temptation resist rate (90d) ──
    temp_pk = f"{USER_PREFIX}temptations"
    try:
        temp_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot temptations
                    "KeyConditionExpression": Key("pk").eq(temp_pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}~"),
                }
            )
        )
        temptations = _decimal_to_float(temp_resp.get("Items", []))
    except Exception:
        temptations = []

    total_temptations = len(temptations)
    resisted = sum(1 for t in temptations if t.get("resisted"))
    resist_rate = round(resisted / total_temptations * 100) if total_temptations else None

    # ── 6. Journal entry count (as journaling progress signal) ──
    journal_pk = f"{USER_PREFIX}notion"
    try:
        j_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot journal records
                    "KeyConditionExpression": Key("pk").eq(journal_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
                    "Select": "COUNT",
                }
            )
        )
        journal_count = j_resp.get("Count", 0)
    except Exception:
        journal_count = 0

    # ── 7. Meditation / breathwork (Apple Health) ──
    ah_mind = _query_source("apple_health", d30, today)
    meditation_sessions = []
    med_total_min = 0
    med_session_count = 0
    for h in ah_mind:
        _md = h.get("date") or h.get("sk", "").replace("DATE#", "")
        _bw_min = float(h.get("breathwork_minutes") or 0)
        _bw_sess = int(float(h.get("breathwork_sessions") or 0))
        # Also check mindful_minutes (Breathwrk app writes here via HAE)
        _mm_min = float(h.get("mindful_minutes") or 0)
        if _mm_min > 0 and _bw_min == 0:
            _bw_min = _mm_min
            _bw_sess = max(_bw_sess, 1)  # At least 1 session if we have minutes
        if _bw_min > 0 or _bw_sess > 0:
            meditation_sessions.append(
                {
                    "date": _md,
                    "minutes": round(_bw_min, 1),
                    "sessions": _bw_sess,
                }
            )
            med_total_min += _bw_min
            med_session_count += _bw_sess
    meditation_sessions.sort(key=lambda x: x["date"])
    meditation_data = {
        "sessions_30d": med_session_count,
        "total_minutes_30d": round(med_total_min, 1),
        "avg_session_min": round(med_total_min / med_session_count, 1) if med_session_count else None,
        "daily": meditation_sessions,
    }

    # ── 8. Vice streak timeline (30-day daily history) ──
    hs_30d_resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(hs_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    hs_30d_items = _decimal_to_float(hs_30d_resp.get("Items", []))
    vice_timeline = []
    for hs_day in hs_30d_items:
        day_date = hs_day.get("date") or hs_day.get("sk", "").replace("DATE#", "")
        raw_vs = hs_day.get("vice_streaks") or {}
        day_entry = {"date": day_date, "held": int(hs_day.get("vices_held", 0)), "total": int(hs_day.get("vices_total", 0))}
        # Include per-vice streaks (filtered)
        if isinstance(raw_vs, dict):
            streaks = {}
            for name, val in raw_vs.items():
                if _is_blocked_vice(name):
                    continue
                streaks[name] = int(val or 0)
            day_entry["streaks"] = streaks
        vice_timeline.append(day_entry)

    # ── 9. Energy level from journal analysis (latest entry) ──
    energy_level = None
    try:
        ja_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot journal analysis
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}journal_analysis")
                    & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
                    "ScanIndexForward": False,
                    "Limit": 5,
                }
            )
        )
        ja_items = _decimal_to_float(ja_resp.get("Items", []))
        energy_vals = [i.get("energy_level") for i in ja_items if i.get("energy_level")]
        if energy_vals:
            energy_level = energy_vals[0]  # Most recent
    except Exception:
        pass

    return _ok(
        {
            "mind": {
                "mind_pillar": mind_pillar,
                "avg_valence": avg_valence,
                "mood_entries_count": len(mood_entries),
                "journal_entries_30d": journal_count,
                "resist_rate_pct": resist_rate,
                "total_temptations_90d": total_temptations,
                "resisted_90d": resisted,
                "total_interactions_30d": total_interactions,
                "meaningful_pct": meaningful_pct,
                "depth_counts": depth_counts,
                "energy_level": energy_level,
            },
            "vice_streaks": vice_data,
            "vice_timeline": vice_timeline,
            "mood_trend": mood_entries[-30:],
            "meditation": meditation_data,
        },
        cache_seconds=3600,
    )


def handle_frequent_meals() -> dict:
    """GET /api/frequent_meals — Top meals by frequency from MacroFactor food logs."""
    from collections import Counter, defaultdict
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        items = _query_source("macrofactor", start_date, end_date)
        meal_counts = Counter()
        meal_macros = defaultdict(lambda: {"cal": 0, "protein": 0, "carbs": 0, "fat": 0, "count": 0})

        for day in items:
            food_log = day.get("food_log") or []
            for entry in food_log:
                name = (entry.get("food_name") or "").strip()
                if not name or len(name) < 3:
                    continue
                meal_counts[name] += 1
                m = meal_macros[name]
                m["cal"] += float(entry.get("calories_kcal") or 0)
                m["protein"] += float(entry.get("protein_g") or 0)
                m["carbs"] += float(entry.get("carbs_g") or 0)
                m["fat"] += float(entry.get("fat_g") or 0)
                m["count"] += 1

        top_meals = []
        for name, freq in meal_counts.most_common(8):
            m = meal_macros[name]
            cnt = m["count"] or 1
            avg_cal = round(m["cal"] / cnt)
            avg_pro = round(m["protein"] / cnt)
            avg_carb = round(m["carbs"] / cnt)
            ppc = round((avg_pro * 4 / avg_cal * 100)) if avg_cal > 0 else 0
            top_meals.append(
                {
                    "name": name,
                    "frequency": freq,
                    "avg_calories": avg_cal,
                    "avg_protein_g": avg_pro,
                    "avg_carbs_g": avg_carb,
                    "protein_cal_pct": ppc,
                }
            )

        return _ok({"meals": top_meals, "period_days": 30}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[frequent_meals] Failed: {e}")
        return _error(503, "Meal data temporarily unavailable.")


def handle_meal_glucose() -> dict:
    """GET /api/meal_glucose — Cross-reference MacroFactor meals with Dexcom CGM spikes."""
    from collections import defaultdict
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = _experiment_date(30)

    try:
        mf_items = _query_source("macrofactor", start_date, end_date)
        cgm_items = _query_source("apple_health", start_date, end_date)

        # Build a map of date → glucose readings for spike calculation
        daily_glucose = {}
        for item in cgm_items:
            date = item.get("sk", "").replace("DATE#", "")
            avg = float(item.get("blood_glucose_avg", 0) or 0)
            peak = float(item.get("blood_glucose_max", 0) or 0)
            baseline = float(item.get("blood_glucose_min", 0) or 0)
            tir = float(item.get("blood_glucose_time_in_range_pct", 0) or 0)
            if avg > 0:
                daily_glucose[date] = {"avg": avg, "peak": peak, "baseline": baseline, "tir": tir}

        # Aggregate meals with glucose context
        meal_data = defaultdict(
            lambda: {"cal": 0, "protein": 0, "carbs": 0, "count": 0, "spike_sum": 0, "spike_count": 0, "category": "meal"}
        )

        for day in mf_items:
            date = day.get("sk", "").replace("DATE#", "")
            food_log = day.get("food_log") or []
            glucose = daily_glucose.get(date)

            for entry in food_log:
                name = (entry.get("food_name") or "").strip()
                if not name or len(name) < 3:
                    continue
                cal = float(entry.get("calories_kcal") or 0)
                if cal < 100:
                    continue  # Skip small items (seasonings, condiments)

                m = meal_data[name]
                m["cal"] += cal
                m["protein"] += float(entry.get("protein_g") or 0)
                m["carbs"] += float(entry.get("carbs_g") or 0)
                m["count"] += 1

                # Estimate category from meal time
                time_str = entry.get("time") or ""
                if time_str:
                    try:
                        hour = int(time_str.split(":")[0])
                        if hour < 11:
                            m["category"] = "breakfast"
                        elif hour < 15:
                            m["category"] = "lunch"
                        elif hour < 18:
                            m["category"] = "snack"
                        else:
                            m["category"] = "dinner"
                    except (ValueError, IndexError):
                        pass

                # Approximate spike from daily glucose data
                if glucose and glucose["peak"] > 0 and glucose["avg"] > 0:
                    spike = glucose["peak"] - glucose["avg"]
                    # Weight by carb content — high-carb meals contribute more to spikes
                    carbs = float(entry.get("carbs_g") or 0)
                    if carbs > 20:
                        m["spike_sum"] += spike * 0.8
                        m["spike_count"] += 1
                    elif carbs > 5:
                        m["spike_sum"] += spike * 0.4
                        m["spike_count"] += 1

        # Build response — top 10 meals by frequency, with glucose grades
        results = []
        for name, m in sorted(meal_data.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
            cnt = m["count"] or 1
            avg_cal = round(m["cal"] / cnt)
            avg_pro = round(m["protein"] / cnt)
            avg_carb = round(m["carbs"] / cnt)
            avg_spike = round(m["spike_sum"] / m["spike_count"]) if m["spike_count"] > 0 else None

            # Grade based on estimated spike
            if avg_spike is None:
                grade = "?"
                curve = "gentle"
            elif avg_spike <= 15:
                grade = "A"
                curve = "flat"
            elif avg_spike <= 25:
                grade = "B"
                curve = "gentle"
            elif avg_spike <= 40:
                grade = "C"
                curve = "moderate"
            else:
                grade = "D"
                curve = "steep"

            results.append(
                {
                    "meal": name,
                    "category": m["category"],
                    "calories": avg_cal,
                    "protein": avg_pro,
                    "carbs": avg_carb,
                    "spike": avg_spike if avg_spike is not None else 0,
                    "grade": grade,
                    "curve": curve,
                }
            )

        return _ok({"meals": results, "period_days": 30, "has_cgm": bool(daily_glucose)}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[meal_glucose] Failed: {e}")
        return _error(503, "Meal glucose data temporarily unavailable.")


def handle_strength_benchmarks() -> dict:
    """GET /api/strength_benchmarks — Current 1RM and progress from Hevy data."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    targets = {
        # Matthew's personal 1RM goals -- should migrate to profile.strength_targets
        "Deadlift": 315,
        "Squat": 265,
        "Bench Press": 185,
        "Overhead Press": 135,
    }

    try:
        items = _query_source("hevy", start_date, end_date)
        # Find max weight for each target lift, AND a per-session (per-day) estimated-1RM
        # history so the front-end can render the Lift Index trend (P0.1) — load moving up
        # over weeks, never a 1RM target/goal.
        best = {}
        history = {t: {} for t in targets}  # lift -> {date: best_e1rm_that_day}
        for day in items:
            d = day.get("date") or day.get("sk", "").replace("DATE#", "")[:10]
            exercises = day.get("exercises") or day.get("workout_exercises") or []
            for ex in exercises:
                name = ex.get("exercise_name") or ex.get("name") or ""
                for target_name in targets:
                    if target_name.lower() in name.lower():
                        sets = ex.get("sets") or []
                        for s in sets:
                            # Hevy stores set weight in weight_kg (native unit); the old
                            # weight_lbs/weight read was always 0 → every 1RM read 0. Convert,
                            # then estimate 1RM via Epley (the column promises "estimated 1RM").
                            w_kg = s.get("weight_kg")
                            w = float(w_kg) * 2.2046226 if w_kg not in (None, "") else float(s.get("weight_lbs") or s.get("weight") or 0)
                            reps = int(s.get("reps") or 0)
                            if w <= 0 or reps < 1 or reps > 12:
                                continue
                            e1rm = w * (1 + reps / 30.0)  # Epley estimated 1RM (lb)
                            if e1rm > best.get(target_name, 0):
                                best[target_name] = e1rm
                            if d and e1rm > history[target_name].get(d, 0):
                                history[target_name][d] = e1rm

        benchmarks = []
        for lift, target in targets.items():
            current = best.get(lift, 0)
            logged = current > 0  # a lift not performed in the window isn't "0 / 0%" — it's no-data
            exceeded = logged and current > target  # already past the goal → "exceeded", not "129%"
            hist = [{"date": dd, "e1rm": round(history[lift][dd])} for dd in sorted(history[lift])]
            benchmarks.append(
                {
                    "lift": lift,
                    "current_1rm": round(current) if logged else None,
                    "target": target,
                    # Clamp progress at 100 (a goal already beaten isn't "129% of progress");
                    # None when the lift wasn't logged this window so the UI shows "—" not 0%.
                    "progress_pct": (min(100, round((current / target) * 100)) if target > 0 else 0) if logged else None,
                    "exceeded": exceeded,
                    "logged": logged,
                    # P0.1 Lift Index: per-session estimated-1RM trend (lb) + the count gate.
                    "history": hist,
                    "sessions": len(hist),
                }
            )

        return _ok({"benchmarks": benchmarks, "period_days": 90}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[strength_benchmarks] Failed: {e}")
        return _error(503, "Strength data temporarily unavailable.")


def handle_food_delivery_overview() -> dict:
    """
    GET /api/food_delivery_overview
    Returns: 30-day food delivery stats from food_delivery DDB partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    items = _query_source("food_delivery", d30, today)
    if not items:
        return _ok({"food_delivery": None}, cache_seconds=3600)

    from collections import Counter, defaultdict

    total_orders = len(items)
    total_spend = sum(float(i.get("amount") or 0) for i in items)
    platform_counts = Counter()
    weekly_counts = defaultdict(int)
    binge_days = 0

    for i in items:
        platform_counts[i.get("platform") or "Unknown"] += 1
        if i.get("binge"):
            binge_days += 1
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        try:
            wk = datetime.strptime(d, "%Y-%m-%d").strftime("%Y-W%V")
            weekly_counts[wk] += 1
        except Exception:
            pass

    weekly_trend = sorted([{"week": k, "orders": v} for k, v in weekly_counts.items()], key=lambda x: x["week"])

    return _ok(
        {
            "food_delivery": {
                "orders_30d": total_orders,
                "avg_spend": round(total_spend / total_orders, 2) if total_orders else 0,
                "total_spend_30d": round(total_spend, 2),
                "binge_days_30d": binge_days,
            },
            "platform_breakdown": [{"platform": p, "count": c} for p, c in platform_counts.most_common()],
            "weekly_trend": weekly_trend,
        },
        cache_seconds=3600,
    )


def handle_strength_deep_dive() -> dict:
    """
    GET /api/strength_deep_dive
    Returns: volume load trend, exercise variety, session patterns from Hevy data.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    items = _query_source("hevy", d90, today)
    if not items:
        return _ok({"strength": None, "message": "No strength data available"}, cache_seconds=3600)

    from collections import Counter, defaultdict

    # Volume load per week (sets × reps × weight)
    weekly_volume = defaultdict(float)
    exercise_freq = Counter()
    session_days = Counter()  # day of week
    Counter()  # hour of day
    total_sets_30d = 0
    exercises_30d = set()

    for day in items:
        d = day.get("date") or day.get("sk", "").replace("DATE#", "")
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%V")
        except Exception:
            continue

        exercises = day.get("exercises") or day.get("workout_exercises") or []
        for ex in exercises:
            name = ex.get("exercise_name") or ex.get("name") or "Unknown"
            sets = ex.get("sets") or []
            for s in sets:
                w = float(s.get("weight_lbs") or s.get("weight") or 0)
                r = int(s.get("reps") or 0)
                weekly_volume[week_key] += w * r
                total_sets_30d += 1 if d >= d30 else 0

            if d >= d30:
                exercise_freq[name] += 1
                exercises_30d.add(name)

        if d >= d30:
            session_days[dt.strftime("%a")] += 1

    volume_trend = sorted([{"week": k, "volume_lbs": round(v)} for k, v in weekly_volume.items()], key=lambda x: x["week"])[-12:]

    top_exercises = [{"name": n, "frequency": c} for n, c in exercise_freq.most_common(10)]

    return _ok(
        {
            "strength": {
                "sessions_90d": len(items),
                "sessions_30d": len([i for i in items if (i.get("date") or i.get("sk", "").replace("DATE#", "")) >= d30]),
                "distinct_exercises_30d": len(exercises_30d),
                "total_sets_30d": total_sets_30d,
            },
            "volume_trend": volume_trend,
            "top_exercises": top_exercises,
            "session_days": dict(session_days),
        },
        cache_seconds=3600,
    )


def handle_benchmark_trends() -> dict:
    """GET /api/benchmark_trends — Returns benchmark progress data."""
    try:
        # ADR-058: phase=pilot hidden by default; pre-genesis benchmarks won't leak.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": "USER#matthew#SOURCE#benchmarks"},
                    "ScanIndexForward": False,
                    "Limit": 30,
                }
            )
        )
        items = resp.get("Items", [])
        return {
            "statusCode": 200,
            "headers": {**CORS_HEADERS, "Cache-Control": "max-age=300"},
            "body": json.dumps({"trends": items}, default=str),
        }
    except Exception as e:
        logger.warning(f"[site_api] benchmark_trends: {e}")
        return {"statusCode": 200, "headers": {**CORS_HEADERS, "Cache-Control": "max-age=300"}, "body": json.dumps({"trends": []})}


def handle_meal_responses() -> dict:
    """GET /api/meal_responses — Returns CGM x MacroFactor meal response data."""
    try:
        # ADR-058: phase=pilot hidden by default.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": "USER#matthew#SOURCE#meal_responses"},
                    "ScanIndexForward": False,
                    "Limit": 50,
                }
            )
        )
        items = resp.get("Items", [])
        return {
            "statusCode": 200,
            "headers": {**CORS_HEADERS, "Cache-Control": "max-age=600"},
            "body": json.dumps({"meals": items}, default=str),
        }
    except Exception as e:
        logger.warning(f"[site_api] meal_responses: {e}")
        return {"statusCode": 200, "headers": {**CORS_HEADERS, "Cache-Control": "max-age=600"}, "body": json.dumps({"meals": []})}


def handle_workouts() -> dict:
    """
    GET /api/workouts
    Recent Hevy strength sessions with their per-exercise sets (reps × weight).
    Read-only — queries SOURCE#hevy WORKOUT# records for the last 30 days.
    Cache: 900s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot workouts
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}hevy")
                    & Key("sk").between(f"DATE#{d30}#WORKOUT#", f"DATE#{today}#WORKOUT#~"),
                    "ScanIndexForward": False,
                }
            )
        )
        items = _decimal_to_float(resp.get("Items", []))
    except Exception as exc:  # noqa: BLE001
        return _ok({"workouts": [], "error": str(exc)[:120]}, cache_seconds=300)

    def _num(v):
        try:
            return round(float(v), 1)
        except (TypeError, ValueError):
            return None

    workouts = []
    for w in items[:30]:
        exercises = []
        for ex in w.get("exercises") or []:
            sets = []
            for s in ex.get("sets") or []:
                sets.append(
                    {
                        "type": s.get("type") or "normal",
                        "reps": _num(s.get("reps")),
                        "weight_kg": _num(s.get("weight_kg")),
                        "rpe": _num(s.get("rpe")),
                        "distance_m": _num(s.get("distance_m")),
                    }
                )
            exercises.append({"name": ex.get("name"), "notes": ex.get("notes") or "", "sets": sets})
        workouts.append(
            {
                "date": w.get("date"),
                "title": w.get("title"),
                "duration_min": round((_num(w.get("duration_sec")) or 0) / 60),
                "total_volume_kg": _num(w.get("total_volume_kg")),
                "exercise_count": w.get("exercise_count"),
                "set_count": w.get("set_count"),
                "exercises": exercises,
            }
        )
    return _ok({"workouts": workouts, "count": len(workouts)}, cache_seconds=900)
