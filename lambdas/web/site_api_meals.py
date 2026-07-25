"""lambdas/web/site_api_meals.py — meal-level nutrition endpoints (protein_sources, frequent_meals, meal_glucose, food_delivery_overview, meal_responses).

Split out of site_api_observatory.py (#1654 slice 3 — god-module breakup). The
routed handler entrypoints stay in the site_api_observatory facade as thin
delegators; this module holds the logic. Handlers receive the facade's globals()
as `_g` and read the monkeypatched/injectable state (table / _query_source /
_experiment_date / EXPERIMENT_START) via `_g["<name>"]`. This module does NOT
import the facade — no import cycle. All other shared helpers come straight from
site_api_common (identical binding semantics to the pre-split facade).
"""

import json
from datetime import datetime, timezone

from web.site_api_common import (
    CORS_HEADERS,
    _error,
    _ok,
    logger,
)


def protein_sources(*, _g) -> dict:
    """
    GET /api/protein_sources
    Returns: Top protein sources from MacroFactor food_log, aggregated by food name.
    Cache: 3600s.
    """
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
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


def frequent_meals(*, _g) -> dict:
    """GET /api/frequent_meals — Top meals by frequency from MacroFactor food logs."""
    _query_source = _g["_query_source"]
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


def meal_glucose(*, _g) -> dict:
    """GET /api/meal_glucose — Cross-reference MacroFactor meals with Dexcom CGM spikes."""
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
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


def food_delivery_overview(*, _g) -> dict:
    """
    GET /api/food_delivery_overview
    Returns: 30-day food delivery stats from food_delivery DDB partition.
    Cache: 3600s.
    """
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
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


def meal_responses(*, _g) -> dict:
    """GET /api/meal_responses — Returns CGM x MacroFactor meal response data."""
    table = _g["table"]
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
