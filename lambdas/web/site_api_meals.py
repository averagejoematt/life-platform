"""lambdas/web/site_api_meals.py — meal-level nutrition endpoints (protein_sources, frequent_meals, meal_glucose, food_delivery_overview).

Split out of site_api_observatory.py (#1654 slice 3 — god-module breakup). The
routed handler entrypoints stay in the site_api_observatory facade as thin
delegators; this module holds the logic. Handlers receive the facade's globals()
as `_g` and read the monkeypatched/injectable state (table / _query_source /
_experiment_date / EXPERIMENT_START) via `_g["<name>"]`. This module does NOT
import the facade — no import cycle. All other shared helpers come straight from
site_api_common (identical binding semantics to the pre-split facade).
"""

from datetime import datetime
from typing import Any, cast

from web.site_api_common import (
    PT,
    _error,
    _ok,
    _window_span,
    logger,
    nutrition_delivery_public,
)

# Food-delivery off-protocol tell (P2.3, PRIVATE-by-default — flag OFF, #2209). Shared
# with site_api_nutrition.food_delivery gate — same env var, same helper, so this
# reader can never drift out of sync with the sibling. With the flag off, the delivery
# source is never queried and nothing private (spend/binge figures) enters the response.
_DELIVERY_PUBLIC = nutrition_delivery_public()


def protein_sources(*, _g) -> dict:
    """
    GET /api/protein_sources
    Returns: Top protein sources from MacroFactor food_log, aggregated by food name.
    Cache: 3600s.
    """
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(PT).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    # #1919: `d30` is genesis-clamped, so `days_count` (already published beside
    # this field, ADR-105) can be far fewer than 30 early in a cycle while
    # `total_protein_30d_avg_g` kept the `_30d` name regardless. The real value
    # is never hidden — it ships unconditionally as total_protein_avg_g; the
    # legacy `_30d`-named key gates on the window genuinely spanning 30 real
    # days (the #1917 rule).
    _w30 = _window_span(d30, today, 30)

    def _envelope(sources: list, avg_g: float | None, days_count: int, *, as_of: str | None = None) -> dict:
        """The ONE published shape for this endpoint.

        Empty and populated payloads are built here so they cannot diverge again:
        before this, the quiet path returned `{sources, as_of_date}` and the
        populated path `{protein_sources, total_protein_*, days_analyzed}` — two
        payloads with ZERO keys in common, so `site/legacy/nutrition/index.html`
        (which reads `d.protein_sources` alone) rendered nothing on Day 1 of a
        cycle and the ADR-105 sample size vanished exactly when it mattered most.
        """
        data = {
            "protein_sources": sources,
            "total_protein_30d_avg_g": avg_g if _w30["full"] else None,
            "total_protein_avg_g": avg_g,
            "total_protein_avg_g_window_days": _w30["actual_days"],
            "days_analyzed": days_count,
        }
        if as_of is not None:
            data["as_of_date"] = as_of
        return data

    try:
        items = _query_source("macrofactor", d30, today)
    except Exception as e:
        # No exception guard existed here at all (unlike frequent_meals /
        # meal_glucose, which wrap the same arithmetic). One non-numeric
        # `protein_g` escaped the handler AND the facade delegator, so the
        # Function URL answered 502 for /api/protein_sources — which the site
        # smoke test reads as a fleet-wide regression and auto-rolls back on.
        logger.warning(f"[protein_sources] Failed: {e}")
        return _error(503, "Protein source data temporarily unavailable.")

    if not items:
        return _ok(_envelope([], None, 0, as_of=today), cache_seconds=300)

    from collections import defaultdict

    # Aggregate protein contribution by food name
    food_protein: dict[str, dict[str, float]] = defaultdict(lambda: {"total_protein": 0.0, "frequency": 0, "total_cal": 0.0})
    # ADR-104: a day the source SYNCED but nothing was eaten into is not a
    # measured zero-protein day — it is an unmeasured day. Counting it in the
    # denominator published a lower protein average as fact and dragged the
    # ADR-105 `days_analyzed` n away from the days actually measured.
    logged_days = [d for d in items if d.get("food_log")]
    days_count = len(logged_days)

    sources: list[dict[str, Any]] = []
    try:
        for day in logged_days:
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
        for name, f in sorted(food_protein.items(), key=lambda x: -x[1]["total_protein"]):
            sources.append(
                {
                    "food": name,
                    "avg_daily_g": round(f["total_protein"] / days_count, 1) if days_count else None,
                    "pct_of_total": round(f["total_protein"] / total_protein_all * 100, 1) if total_protein_all else 0,
                    "frequency": f["frequency"],
                    "avg_protein_per_serving": round(f["total_protein"] / f["frequency"], 1) if f["frequency"] else 0,
                    # ADR-104: a food logged with protein but NO calorie figure (the
                    # common shape for a hand-entered whole food) is unmeasurable
                    # here. Shipping 0 said "none of this food's calories are
                    # protein" — the exact inverse of the truth for a pure-protein
                    # item. Absence is None.
                    "protein_cal_pct": round((f["total_protein"] * 4) / f["total_cal"] * 100) if f["total_cal"] > 0 else None,
                }
            )
            if len(sources) >= 12:
                break

        _total_protein_avg_g = round(total_protein_all / days_count, 1) if days_count else None
    except Exception as e:
        logger.warning(f"[protein_sources] Failed: {e}")
        return _error(503, "Protein source data temporarily unavailable.")

    return _ok(_envelope(sources, _total_protein_avg_g, days_count), cache_seconds=3600)


def frequent_meals(*, _g) -> dict:
    """GET /api/frequent_meals — Top meals by frequency from MacroFactor food logs."""
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    from collections import Counter, defaultdict

    # NB: no `from datetime import ...` here. The re-import used to shadow the
    # module-level binding on line 13, so `monkeypatch.setattr(meals, "datetime",
    # ...)` — the seam every #1084/#1917 window test uses — silently no-opped for
    # this handler and its date arithmetic could not be pinned at a boundary.
    end_date = datetime.now(PT).strftime("%Y-%m-%d")
    # Genesis clamp (ADR-077). This was the only meal endpoint deriving its lower
    # bound as `now - 30d` with no EXPERIMENT_START clamp, so a prior-cycle row
    # not yet phase-tagged (the reset tags asynchronously) surfaced on the new
    # cycle's page with no genesis-derived floor to fall back on.
    start_date = _experiment_date(30)
    period_days = _window_span(start_date, end_date, 30)["actual_days"]

    try:
        items = _query_source("macrofactor", start_date, end_date)
        meal_counts: Counter[str] = Counter()
        meal_macros: dict[str, dict[str, float]] = defaultdict(lambda: {"cal": 0, "protein": 0, "carbs": 0, "fat": 0, "count": 0})

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
            # ADR-104 (#2330): a meal whose calories were never logged has no
            # measurable protein share — publishing 0 graded it LOW on the legacy
            # nutrition page for protein it was never measured for. None matches
            # the protein_sources sibling above. Measured-zero (calories logged,
            # zero protein) still computes honestly to 0.
            ppc = round((avg_pro * 4 / avg_cal * 100)) if avg_cal > 0 else None
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

        # #1917 reader-truth: `period_days` carries its window in the VALUE, so the
        # AST guard in test_window_name_honesty_1917.py never saw it. Shipping the
        # literal 30 told the reader the table covered 30 days on Day 5 of a cycle.
        return _ok({"meals": top_meals, "period_days": period_days}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[frequent_meals] Failed: {e}")
        return _error(503, "Meal data temporarily unavailable.")


def meal_glucose(*, _g) -> dict:
    """GET /api/meal_glucose — Cross-reference MacroFactor meals with Dexcom CGM spikes."""
    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    from collections import defaultdict

    # No `from datetime import ...` re-import here either — see frequent_meals.
    end_date = datetime.now(PT).strftime("%Y-%m-%d")
    start_date = _experiment_date(30)
    period_days = _window_span(start_date, end_date, 30)["actual_days"]

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
        meal_data: dict[str, dict[str, Any]] = defaultdict(
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
        results: list[dict[str, Any]] = []
        for name, m in sorted(meal_data.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
            cnt = m["count"] or 1
            avg_cal = round(m["cal"] / cnt)
            avg_pro = round(m["protein"] / cnt)
            avg_carb = round(m["carbs"] / cnt)
            avg_spike = round(m["spike_sum"] / m["spike_count"]) if m["spike_count"] > 0 else None

            # Grade based on estimated spike. ADR-104: an unmeasurable meal (no CGM
            # coverage that day, or <=5 g carbs so no spike sample was taken) is
            # ABSENT on every field that describes the rise — it used to grade "?"
            # while simultaneously publishing `spike: 0` ("no glucose rise") and
            # `curve: "gentle"`, the same shape word a measured grade-B meal gets.
            if avg_spike is None:
                grade = "?"
                curve = "unknown"
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
                    "spike": avg_spike,
                    "grade": grade,
                    "curve": curve,
                }
            )

        return _ok({"meals": results, "period_days": period_days, "has_cgm": bool(daily_glucose)}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[meal_glucose] Failed: {e}")
        return _error(503, "Meal glucose data temporarily unavailable.")


def food_delivery_overview(*, _g) -> dict:
    """
    GET /api/food_delivery_overview
    Returns: 30-day food delivery stats from food_delivery DDB partition.
    Cache: 3600s.

    Gated by NUTRITION_DELIVERY_PUBLIC (#2209) — checked BEFORE the query, matching
    the sibling site_api_nutrition.py tell: with the flag off (default), the
    food_delivery source is never queried and nothing private enters the response.
    """
    if not _DELIVERY_PUBLIC:
        # Deliberately the BARE key (#2209): with the flag off nothing
        # delivery-shaped enters the response at all — not even the empty
        # `platform_breakdown` / `weekly_trend` arrays the flag-on path publishes.
        return _ok({"food_delivery": None}, cache_seconds=3600)

    _query_source = _g["_query_source"]
    _experiment_date = _g["_experiment_date"]
    today = datetime.now(PT).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    try:
        items = _query_source("food_delivery", d30, today)
        if not items:
            # Envelope parity: a quiet 30-day window (Day 1 of a cycle) must still
            # publish the two arrays the populated payload does, or a consumer that
            # iterates either one without a null guard throws on the empty state.
            return _ok({"food_delivery": None, "platform_breakdown": [], "weekly_trend": []}, cache_seconds=3600)

        from collections import Counter, defaultdict

        total_orders = len(items)
        # The week parse below was already guarded; this sum was not, so a
        # currency-formatted amount ("$24.50" — the shape a hand-entered or
        # scraped record takes) 502'd the endpoint.
        total_spend = sum(float(i.get("amount") or 0) for i in items)
        platform_counts: Counter[str] = Counter()
        weekly_counts: dict[str, int] = defaultdict(int)
        binge_days = 0

        for i in items:
            platform_counts[i.get("platform") or "Unknown"] += 1
            if i.get("binge"):
                binge_days += 1
            d = i.get("date") or i.get("sk", "").replace("DATE#", "")
            try:
                wk = datetime.strptime(d, "%Y-%m-%d").strftime("%G-W%V")
                weekly_counts[wk] += 1
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[food_delivery_overview] Failed: {e}")
        return _error(503, "Food delivery data temporarily unavailable.")

    weekly_trend = sorted([{"week": k, "orders": v} for k, v in weekly_counts.items()], key=lambda x: cast(str, x["week"]))

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
