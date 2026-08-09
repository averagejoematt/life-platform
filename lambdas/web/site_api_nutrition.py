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

from common import (
    digest_utils,  # bundled shared module — compute_confidence tiering (ADR-105)
    stats_core,  # bundled shared module (#529): the one sanctioned stats implementation
)
from health import tdee as health_tdee  # ADR-152 / #2310: THE one TDEE definition

from web.site_api_common import (
    _get_profile,
    _ok,
    _window_span,
    logger,
    nutrition_delivery_public,
)

# Shared with site_api_meals.food_delivery_overview (#2209) — both readers of the
# food_delivery DDB partition parse the SAME env var through the SAME helper so they
# can never drift out of sync.
_DELIVERY_PUBLIC = nutrition_delivery_public()

_BLUEPRINT_PUBLIC = os.environ.get("NUTRITION_BLUEPRINT_PUBLIC", "").strip().lower() in ("1", "true", "yes")

_TDEE_FIELDS = ("expenditure_kcal", "tdee_kcal", "tdee", "expenditure")

_RDO_MIN_OVERLAP_DAYS = 14

_RDO_IMPACT_R = 0.15

# Phase-1 "Ignition" rate target: 3 lb/week ≈ 1,500 kcal/day (matches the profile /
# ai_calls Phase-1 target). Module scope so the genesis-week empty state publishes the
# SAME loss_rate constants the populated branch does (#2221 shape parity).
_TARGET_RATE_LB_WK = 3
_KCAL_PER_LB = 3500
_REQUIRED_DEFICIT_KCAL = round(_TARGET_RATE_LB_WK * _KCAL_PER_LB / 7)  # 1500

# Last-resort protein lines, used ONLY when canonical_facts carries a value that will not
# coerce. The authoritative default lives in the `_prof.get(<key>, <default>)` call itself,
# whose literal shape tests/test_protein_contract.py pins against the producer.
_PROTEIN_TARGET_FALLBACK_G = 190.0
_PROTEIN_FLOOR_FALLBACK_G = 170.0


def _num(v):
    """``float(v)`` or ``None`` — never raises (#2221).

    Both partitions this module reads are hand-uploaded exports: MacroFactor writes an
    unpopulated Expenditure cell as ``"--"``, Withings can carry an empty weight. A bare
    ``float(row["field"])` anywhere in the handler turns ONE malformed cell into a 500 on
    the whole nutrition door — every other panel on the page included. ``_resolve_mf_tdee``
    and ``_mifflin_tdee`` already guarded the identical coercion; the rest of the module
    did not. An unreadable value is ABSENT (ADR-104 withhold-don't-recompute), never 0."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _deficit_label(deficit_pct):
    """The BS-12 deficit-intensity ladder, in ONE place (#2221).

    A NEGATIVE percentage is a SURPLUS — eating above maintenance. Both ladders used to
    fall through to ``maintenance``, so a reader running a 600 kcal/day surplus was told
    they were holding steady. ``deficit_sustainability`` pairs its label with
    ``in_deficit: False``; the ``loss_rate`` panel on /api/nutrition_overview carries no
    such guard, so the label was the only thing the reader had."""
    if deficit_pct is None:
        return None
    if deficit_pct > 25:
        return "aggressive"
    if deficit_pct > 15:
        return "moderate"
    if deficit_pct > 5:
        return "mild"
    if deficit_pct < -5:
        return "surplus"
    return "maintenance"


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


def _mifflin_tdee(weight_lbs, strava_items=None, profile=None):
    """The ADR-152 TDEE estimate — Mifflin-St Jeor BMR + MEASURED trailing-7-day exercise
    energy — from the ONE shared implementation in ``health.tdee`` (#2310).

    This is the ESTIMATE fallback only: MacroFactor's measured adaptive expenditure stays
    the site's primary whenever it is fresh, and callers keep labelling this branch
    ``estimate_mifflin`` so it is never conflated with the measured figure (#484).
    What changed is the formula behind the label: the flat × 1.55 activity multiplier is
    retired, so the public door and the two MCP surfaces now publish ONE definition
    instead of two ~2× apart. Maintenance only — no deficit is folded in here; callers
    that publish a target subtract it explicitly.

    Returns None when weight or profile height is missing (ADR-104: Mifflin is 6.25 kcal
    per cm of height — assuming one would publish a guess as a measurement)."""
    prof = profile if profile is not None else (_get_profile() or {})
    height_in = prof.get("height_inches")
    age_years, age_basis, _ = health_tdee.resolve_age(prof.get("date_of_birth"))
    wkg = _num(weight_lbs)
    ex = health_tdee.exercise_energy(strava_items, (wkg or 0.0) * health_tdee.LB_TO_KG)
    budget = health_tdee.energy_budget(
        weight_lbs=weight_lbs,
        height_inches=height_in,
        age_years=age_years,
        age_basis=age_basis,
        sex=(prof.get("biological_sex") or "male"),
        exercise_kcal=ex["kcal"],
        exercise_energy_days=ex["days"],
        exercise_energy_basis=ex["basis"],
        deficit_kcal=0,  # TDEE means MAINTENANCE (ADR-152)
    )
    return budget["tdee"] if budget else None


def _latest_weight_lbs(start, today, *, _g):
    """Most recent Withings weigh-in (lbs) in the window, or None."""
    _query_source = _g["_query_source"]
    wt = _query_source("withings", start, today)
    if not wt:
        return None
    latest = sorted(wt, key=lambda x: x.get("sk", ""))[-1]
    return _num(latest.get("weight_lbs"))


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


def _mf(item, field, alt_field=None):
    """Resolve a MacroFactor macro field across both the legacy short field name
    (``calories``, ``protein_g``, …) and the current ``total_*_kcal``/``total_*_g``
    name. Module-scope (#2217 — was a closure duplicated per-call inside
    ``nutrition_overview``); ``deficit_sustainability`` shares this single accessor
    instead of its own inline ``total_calories_kcal``-only extraction, which
    silently produced a fabricated ``avg_intake_kcal: 0`` / ``deficit_pct: 100.0``
    on any day logged only under the legacy ``calories`` field.

    #2221 — resolves by PRESENCE, not truthiness. The old ``a or b`` chain made an
    HONESTLY LOGGED ZERO indistinguishable from an absent field: a zero-fiber
    carnivore/shake day dropped out of ``avg_fiber_g`` (inflating the published
    average) and a fully-logged 0 kcal fast published ``latest_calories: None`` —
    "not logged" for a day that WAS. Absence and zero are not the same value
    (ADR-104). Coercion goes through ``_num``, so one malformed cell yields an
    absent macro rather than a ValueError out of the whole handler."""
    names = [field, alt_field or f"total_{field}"]
    if field == "calories":
        names.append("total_calories_kcal")
    for name in names:
        v = _num(item.get(name))
        if v is not None:
            return v
    return None


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

    # One protein story on every door: target (stretch) and floor (graded) are the
    # SAME profile values daily_metrics_compute writes into canonical_facts
    # (protein_g_target/protein_g_floor). This page used to hardcode 190 and call it
    # the "floor" while the coaches graded against the real 170 floor — a reader
    # crossing doors saw two truths.
    # #2221: coerced through `_num` like every other read — a non-numeric
    # protein_target_g in canonical_facts used to 500 the whole nutrition door rather
    # than fall back to the documented default. Found by the derived AST guard in
    # tests/test_site_api_nutrition_behavior.py, not by any marker.
    #
    # #2337: read ABOVE the empty-branch return, so the genesis/no-data branch serves
    # the same configured numbers the populated branch does. It used to hardcode 190
    # and 170 in three further places below; with MacroFactor quiet (#2326) the empty
    # branch is the LIVE branch, so those copies were the ones a reader actually saw.
    #
    # The `.get("<key>", <default>)` LITERAL shape is load-bearing:
    # tests/test_protein_contract.py regex-matches key+default here against
    # daily_metrics_compute's producer so the doors cannot tell two protein truths
    # again. Keep the literal; add the guard around it, never instead of it.
    _prof = _get_profile()
    protein_target = _num(_prof.get("protein_target_g", 190))
    if protein_target is None:
        protein_target = _PROTEIN_TARGET_FALLBACK_G
    protein_floor = _num(_prof.get("protein_floor_g", 170))
    if protein_floor is None:
        protein_floor = _PROTEIN_FLOOR_FALLBACK_G

    items = _query_source("macrofactor", d30, today)
    if not items:
        # Genesis week / no logging yet — return a shaped-but-empty 200 so the
        # site renders an honest empty state instead of a console 503.
        #
        # #2360: the adherence RATES are None here, never 0. A rate over an empty set
        # is undefined, not zero (ADR-104) — publishing 0 made the front-end grade a
        # protein failure out of no observations at all ("floor missed every logged
        # day · 0/0"). The *day counts* stay 0 because those are honest counts of a
        # thing that did not happen; it is the percentage that has no denominator.
        _empty_grp = {
            "avg_calories": None,
            "avg_protein_g": None,
            "avg_carbs_g": None,
            "avg_fat_g": None,
            "avg_fiber_g": None,
            "days": 0,
            "count": 0,
            "protein_hit_pct": None,
        }
        return _ok(
            {
                "nutrition": {
                    "avg_calories": None,
                    "avg_protein_g": None,
                    "avg_carbs_g": None,
                    "avg_fat_g": None,
                    "avg_fiber_g": None,
                    "protein_target_g": protein_target,
                    "protein_hit_pct": None,
                    "protein_hit_days": 0,
                    "protein_floor_g": protein_floor,
                    "protein_floor_hit_pct": None,
                    "protein_floor_hit_days": 0,
                    "days_logged": 0,
                    "tdee": None,
                    # #2221: the populated block always publishes tdee_source (the
                    # measured-vs-estimated label the front-end renders next to the
                    # number); on a genesis week the key was simply absent.
                    "tdee_source": None,
                    "avg_deficit": None,
                    "cal_7d_avg": None,
                    "pro_7d_avg": None,
                    "cal_avg_recent": None,
                    "cal_avg_recent_window_days": 0,
                    "pro_avg_recent_g": None,
                    "pro_avg_recent_g_window_days": 0,
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
                # #2221 — SHAPE PARITY. The front-end binds one payload shape; this
                # branch used to omit nine top-level keys the populated branch
                # publishes, so `data.loss_rate.protein_hit_pct` threw for the whole
                # first stretch of every cycle — exactly when the empty state is
                # supposed to render gracefully. Every key below is present-and-empty,
                # never fabricated. food_delivery / blueprint_benchmark are the
                # flag-gated private panels: with the flags off the populated branch
                # also publishes None and NEITHER branch queries the private
                # partition, so shape parity costs nothing privacy-wise.
                "loss_rate": {
                    "target_rate_lb_wk": _TARGET_RATE_LB_WK,
                    "required_deficit_kcal": _REQUIRED_DEFICIT_KCAL,
                    "actual_deficit_kcal": None,
                    "gap_kcal": None,
                    "implied_rate_lb_wk": None,
                    "deficit_pct": None,
                    "deficit_label": None,
                    "protein_hit_pct": None,
                    "protein_floor_hit_pct": None,
                    "protein_floor_g": protein_floor,
                },
                "meal_rhythm": {
                    "avg_protein_per_meal": None,
                    "protein_distribution_score": None,
                    "per_day_window": [],
                    "time_distribution": [],
                    "reference_window_hrs": 8,
                    "days_with_meal_times": 0,
                },
                "electrolytes": {
                    "avg_sodium_mg": None,
                    "sodium_ref_low": 1500,
                    "sodium_ref_high": 2300,
                    "potassium_pct": None,
                    "days_logged": 0,
                },
                "lean_mass": None,
                "projection": None,
                "reconciliation": {"days": [], "overlap_days": 0, "min_days": 14, "ready": False},
                "food_delivery": None,
                "blueprint_benchmark": None,
                "micronutrients": {"sufficiency": {}, "avg_pct": None, "protein_distribution_score": None, "as_of": None},
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

    cal_vals = [_mf(i, "calories") for i in items if _mf(i, "calories") is not None]
    pro_vals = [_mf(i, "protein_g", "total_protein_g") for i in items if _mf(i, "protein_g", "total_protein_g") is not None]
    carb_vals = [_mf(i, "carbs_g", "total_carbs_g") for i in items if _mf(i, "carbs_g", "total_carbs_g") is not None]
    fat_vals = [_mf(i, "fat_g", "total_fat_g") for i in items if _mf(i, "fat_g", "total_fat_g") is not None]
    fiber_vals = [_mf(i, "fiber_g", "total_fiber_g") for i in items if _mf(i, "fiber_g", "total_fiber_g") is not None]

    # protein_target / protein_floor are read from the profile ABOVE the empty-branch
    # return (#2337) so both branches serve the same configured numbers.
    #
    # #2360: `else None`, never `else 0`. `items` can be non-empty while `pro_vals` is
    # empty — days logged with no protein cell — and that is still a rate with no
    # denominator. The old `else 0` published "0% of days cleared the floor" for a set
    # nobody graded, which the front-end then rendered as an active failure.
    protein_hit_days = sum(1 for v in pro_vals if v >= protein_target)
    protein_hit_pct = round(protein_hit_days / len(pro_vals) * 100) if pro_vals else None
    floor_hit_days = sum(1 for v in pro_vals if v >= protein_floor)
    floor_hit_pct = round(floor_hit_days / len(pro_vals) * 100) if pro_vals else None

    # Latest day
    latest = items[-1] if items else {}
    latest_date = latest.get("date") or latest.get("sk", "").replace("DATE#", "")

    # 7-day vs 30-day comparison.
    # #2221 fixed the eighth-day bug HERE, in this one filter, by making the lower bound
    # exclusive (`> d7`) while `d7` was still `today - 7`. #2338 moved the repair upstream:
    # `_experiment_date(7)` now returns `today - 6`, the inclusive start of a 7-day window,
    # matching the inclusive `between` every other query in this file already uses. The
    # bound is therefore INCLUSIVE again — keeping `>` on top of the fixed helper would
    # drop the oldest day and average a 7-day label over six days, the same class of error
    # in the other direction. The set of dates and the `_window_span` below stay identical,
    # and both still shrink together when genesis clamps the window.
    items_7d = [i for i in items if (i.get("date") or i.get("sk", "").replace("DATE#", "")) >= d7]
    cal_7d = [_mf(i, "calories") for i in items_7d if _mf(i, "calories") is not None]
    pro_7d = [_mf(i, "protein_g", "total_protein_g") for i in items_7d if _mf(i, "protein_g", "total_protein_g") is not None]
    # #1919: `d7` is genesis-clamped (_experiment_date), so `items_7d` can hold far
    # fewer than 7 days early in a cycle while `cal_7d_avg`/`pro_7d_avg` kept the
    # `_7d` name regardless. The real average is never hidden — it ships
    # unconditionally as cal_avg_recent/pro_avg_recent_g; the legacy `_7d`-named
    # keys gate on the window genuinely spanning 7 real days (the #1917 rule).
    _w7 = _window_span(d7, today, 7)

    # TDEE from the most recent record carrying MacroFactor's adaptive expenditure (#484).
    # When none is present (no populated Expenditure column uploaded), fall back to a
    # profile-derived estimate from the latest weigh-in — labeled, so the deficit panel
    # shows a real (honestly-flagged) number instead of None.
    tdee, tdee_source = _resolve_mf_tdee(items)
    if tdee is None:
        est = _mifflin_tdee(_latest_weight_lbs(d30, today, _g=_g), _g["_query_source"]("strava", d7, today))
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
        # #2221: grade only the days that actually logged protein — the headline
        # `nutrition.protein_hit_pct` divides by exactly that set. This one divided by
        # EVERY day in the bucket and coerced a missing value to 0 via `(… or 0) >=`,
        # so an unlogged macro counted as a MISS. One field name, two definitions: a
        # reader comparing the panels saw 100% and 50%. Absence is not a miss (ADR-104).
        # #2360: `else None` — an empty bucket (a weekend with nothing logged) has no
        # adherence rate to report, and `_empty_grp` publishes None for exactly this
        # key. Returning 0 made "no weekend data" render as "cleared the target on 0%
        # of weekend days."
        vals = [v for v in (_mf(x, "protein_g", "total_protein_g") for x in group) if v is not None]
        return round(sum(1 for v in vals if v >= protein_target) / len(vals) * 100) if vals else None

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
    TARGET_RATE_LB_WK = _TARGET_RATE_LB_WK
    KCAL_PER_LB = _KCAL_PER_LB
    required_deficit = _REQUIRED_DEFICIT_KCAL
    deficit_pct = round(deficit / tdee * 100, 1) if (deficit is not None and tdee) else None
    deficit_label = _deficit_label(deficit_pct)
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
    bucket_protein: dict[int, float] = {}
    bucket_cal: dict[int, float] = {}
    total_meals_sum = 0
    # #2221: the numerator and the denominator of grams-per-meal must come from the SAME
    # set of days. Protein used to be summed over EVERY day in the window while meals
    # were summed only over days carrying `total_meals`, so a single day missing its meal
    # count doubled the published figure.
    protein_on_meal_days = 0.0
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
            bucket_protein[b] = bucket_protein.get(b, 0.0) + (_num(e.get("protein_g")) or 0.0)
            bucket_cal[b] = bucket_cal.get(b, 0.0) + (_num(e.get("calories_kcal")) or 0.0)
        if len(times) >= 2:
            per_day_window.append({"date": d, "first_min": min(times), "last_min": max(times)})
        _meals = _num(i.get("total_meals"))
        if _meals:
            total_meals_sum += int(_meals)
            _day_protein = _mf(i, "protein_g", "total_protein_g")
            if _day_protein is not None:
                protein_on_meal_days += _day_protein
        _pds = _num(i.get("protein_distribution_score"))
        if _pds is not None:
            pds_vals.append(_pds)

    meal_rhythm = {
        "avg_protein_per_meal": round(protein_on_meal_days / total_meals_sum, 1) if total_meals_sum else None,
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
    sodium_vals = [v for v in (_num(i.get("total_sodium_mg")) for i in items) if v is not None]
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
        lean_lb = _num(w.get("fat_free_mass_lbs"))
        if lean_lb is not None:
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
    # #2221: coerced through `_num` like `_latest_weight_lbs` a few lines above — this
    # copy of the identical read was unguarded, so ONE non-numeric Withings weight 500'd
    # /api/nutrition_overview outright.
    cur_weight = None
    for w in sorted(wt_items, key=lambda x: x.get("sk", ""), reverse=True):
        cur_weight = _num(w.get("weight_lbs"))
        if cur_weight is not None:
            break

    # ── Standing self-grading prediction (P2.1): project the next weight crossing from the
    # current implied rate (intake vs maintenance), with a confidence band (rate ±25%). The
    # bet + band are stated now; the verdict resolves over weeks (pending until the date).
    projection = None
    implied = loss_rate.get("implied_rate_lb_wk")
    if cur_weight is not None and implied and implied > 0:
        # Next 5-lb mark strictly below the current weight. #2221: this was
        # `int((cur_weight - 0.1) // 5) * 5` — the 0.1 lb epsilon existed to stop a weight
        # sitting exactly ON a mark from targeting itself, but it also created a 0.1 lb
        # dead zone just above every mark, so 195.05 lb bet on 190 instead of 195: ten
        # pounds further out than the real next crossing. Test the on-the-mark case
        # exactly instead of nudging the input.
        target_w = int(cur_weight // 5) * 5
        if target_w == cur_weight:  # already standing on a mark — bet the next one down
            target_w -= 5
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
        wv = _num(w.get("weight_lbs"))
        if wv is not None:
            w_series[dd] = wv
    recon_days = []
    start_actual = None
    if tdee:
        # #2221 — ONE baseline for both trajectories. `cum_def` used to accumulate from
        # the first LOGGED day while `start_actual` anchored to the first WEIGHED day, so
        # when the scale started later than the food log every un-weighed prefix day was
        # added to the projected line and to nothing on the actual line. The published
        # `gap_lbs` — sold to the reader as "logging accuracy / TDEE drift" — was inflated
        # by exactly that prefix. Accumulate from the first day carrying BOTH a logged
        # intake and a weigh-in; earlier days have no baseline to be measured against, so
        # they carry no projected value rather than a misleading one (ADR-104).
        baseline_date = next((t["date"] for t in trend if t.get("calories") is not None and t["date"] in w_series), None)
        cum_def = 0.0
        for t in trend:
            cal = t.get("calories")
            if cal is None:
                continue
            if baseline_date is not None and t["date"] < baseline_date:
                recon_days.append({"date": t["date"], "projected_loss_lbs": None, "actual_loss_lbs": None})
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
        rv = _num(w.get("recovery_score"))
        if rv is not None:
            recovery_by_date[dd] = rv
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
        deliv_def: list[float] = []
        home_def: list[float] = []
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
            from ingestion.source_registry import DEFAULT_STALE_HOURS, stale_hours_overrides

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
                "cal_7d_avg": (round(sum(cal_7d) / len(cal_7d)) if cal_7d else None) if _w7["full"] else None,
                "pro_7d_avg": (round(sum(pro_7d) / len(pro_7d), 1) if pro_7d else None) if _w7["full"] else None,
                "cal_avg_recent": round(sum(cal_7d) / len(cal_7d)) if cal_7d else None,
                "cal_avg_recent_window_days": _w7["actual_days"],
                "pro_avg_recent_g": round(sum(pro_7d) / len(pro_7d), 1) if pro_7d else None,
                "pro_avg_recent_g_window_days": _w7["actual_days"],
                "latest_date": latest_date,
                # The latest COMPLETE day is the live nutrition state (manual end-of-day
                # upload → always ~24h behind by design). today_pending true means the
                # current day's intake simply hasn't been uploaded yet — expected, not a
                # logging gap. Front-end labels "through <as_of>", never "not logged today".
                "as_of": latest_date,
                "today_pending": bool(latest_date and latest_date < today),
                "lag_days": _nut_lag_days,
                "stalled": _nut_stalled,
                # #2221: guarded on PRESENCE, like every average above. These two used to
                # guard on truthiness, so a fully-logged 0 kcal fast day published
                # `latest_calories: None` — "not logged" for a day that was.
                "latest_calories": round(_mf(latest, "calories")) if _mf(latest, "calories") is not None else None,
                "latest_protein_g": (
                    round(_mf(latest, "protein_g", "total_protein_g"), 1)
                    if _mf(latest, "protein_g", "total_protein_g") is not None
                    else None
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

    _f = _num

    # #2217: read intake through the same _mf accessor nutrition_overview uses, so a
    # day logged only under the legacy `calories` field name (rather than the current
    # `total_calories_kcal`) still contributes its real intake instead of silently
    # dropping out and fabricating a 100%-deficit "aggressive" verdict from zero rows.
    cals = [_mf(i, "calories") for i in mf if _mf(i, "calories") is not None]
    avg_cal = round(sum(cals) / len(cals)) if cals else 0
    tdee, tdee_source = _resolve_mf_tdee(mf)
    if not tdee:  # Fallback: profile-derived Mifflin estimate from the latest weigh-in (#484)
        est = _mifflin_tdee(
            _latest_weight_lbs(start, today, _g=_g),
            _query_source("strava", (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d"), today),
        )
        if est:
            tdee, tdee_source = est, "estimate_mifflin"
        else:
            tdee, tdee_source = 2400, "estimate_default"
    deficit_kcal = round(tdee - avg_cal)
    deficit_pct = round(deficit_kcal / tdee * 100, 1) if tdee else 0
    in_deficit = deficit_kcal > 200
    deficit_label = _deficit_label(deficit_pct)  # #2221: one ladder, and it has a surplus branch

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
    # Channel 4 — habit completion.
    # #2221 READER/WRITER AGREEMENT: `ingestion/habitify_lambda.py` writes
    # `completion_pct` (pending-aware) and `completion_pct_strict`, plus `by_group[*].pct`
    # over the nine P40 groups. There is no "Tier 0" group and NOTHING in the repo has
    # ever written `tier_0_completion_rate` or `t0_rate`, so this channel was structurally
    # dark: the list was always [], the direction always "insufficient_data", `t0_bad`
    # always False. (`mcp/tools_nutrition.py` carried the identical dead read and was
    # corrected the same way.) Presence, not truthiness: a 0% completion day is the
    # single strongest sign the cut is costing something, and the old `or` dropped it
    # from the series entirely (ADR-104).
    t0 = []
    for h in habit:
        hv = _f(h.get("completion_pct"))
        if hv is None:
            hv = _f(h.get("completion_pct_strict"))
        if hv is not None:
            t0.append(hv)
    t0_dir, t0_d = trend_dir(t0)
    t0_bad = t0_dir == "declining" and abs(t0_d) > 10
    # Channel 5 — training output (Strava kJ/day)
    daily_kj: dict[str, float] = {}
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
                # #2221: `days` was the literal 14 while `start` is genesis-clamped by
                # `_experiment_date` — three days into a cycle the payload claimed a
                # 14-day period over a 3-day window. `_window_span` is the one place a
                # window's real length is measured (#1917).
                "period": {"start": start, "end": today, "days": _window_span(start, today, 14)["actual_days"]},
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
