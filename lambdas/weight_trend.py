"""
weight_trend.py — the ONE weight-trajectory computation (regression rate + projection).

The website (`site_api_vitals.handle_journey`) and the daily brief (which writes
`public_stats.json`) both derive the weekly rate + goal projection. Before this they
diverged — the brief used a raw 7-day delta, the API a 28-day regression — so the same
fact rendered as -13.75 lb/wk in one place and -7.33 in another, and the projection
implied losing 115 lb in five weeks. This is the shared, correct implementation both
call, so the number is identical everywhere.

Early-cut water weight makes a raw rate wildly fast, so the rate is flagged
`rate_provisional` and the projection suppressed until the weigh-in record spans
>= 21 days (matches the existing handle_journey guard). Pure module, layer-deployed.
"""

from datetime import datetime, timedelta, timezone


def _record_date(item):
    """YYYY-MM-DD for a DDB day record (date attr, else the sk)."""
    d = item.get("date") or str(item.get("sk", "")).replace("DATE#", "")[:10]
    return d if len(str(d)) == 10 else None


def _record_weight_lbs(item):
    """weight_lbs from a record, converting weight_kg when only kg is stored."""
    w = item.get("weight_lbs")
    if w is not None:
        try:
            return float(w)
        except (TypeError, ValueError):
            return None
    kg = item.get("weight_kg")
    try:
        kg = float(kg) if kg is not None else None
    except (TypeError, ValueError):
        return None
    if kg is not None and kg < 200:  # sanity: a >200 "kg" value is a mis-unit record
        return kg * 2.20462
    return None


def latest_weight(withings_records, apple_records=None):
    """The ONE latest-weight resolution (#491/M-5/M-6): Withings backscan +
    Apple Health backscan, most recent date wins (Withings wins ties — it is
    the source of truth; Apple is the travel/fallback scale).

    Before this, three surfaces resolved "current weight" three different ways —
    vitals checked only the single latest apple_health item (a steps record →
    fallback dead, M-6), journey ignored Apple entirely, and the character sheet
    had its own kg-converting backscan. Pure function over already-fetched
    record lists (callers bound the Apple query to ~7 days); no I/O.

    Returns {"weight_lbs": float|None, "as_of": "YYYY-MM-DD"|None,
             "source": "withings"|"apple_health"|None}.
    """
    best = {"weight_lbs": None, "as_of": None, "source": None}
    for source, records in (("withings", withings_records), ("apple_health", apple_records)):
        for item in records or []:
            if not isinstance(item, dict):
                continue
            d, w = _record_date(item), _record_weight_lbs(item)
            if d is None or w is None:
                continue
            # strictly-newer keeps Withings on ties (it's scanned first)
            if best["as_of"] is None or d > best["as_of"]:
                best = {"weight_lbs": w, "as_of": d, "source": source}
    return best


def weight_trajectory(
    weight_series,
    current_weight,
    goal_weight,
    ref_dt=None,
    window_days=28,
    provisional_days=21,
):
    """Regression weekly rate + suppressed-when-provisional goal projection.

    weight_series: list of (date_str 'YYYY-MM-DD', weight_lbs), any order.
    Returns a dict: weekly_rate_lbs, slope_per_day, rate_provisional,
    weighin_span_days, projected_goal_date (None when provisional), days_to_goal.
    """
    ref = ref_dt or datetime.now(timezone.utc)
    cutoff = (ref - timedelta(days=window_days)).strftime("%Y-%m-%d")
    recent = sorted((d, w) for d, w in weight_series if d >= cutoff and w)

    weekly_rate, slope_per_day = 0.0, 0.0
    if len(recent) >= 4:
        x0 = datetime.strptime(recent[0][0], "%Y-%m-%d")
        x = [(datetime.strptime(d, "%Y-%m-%d") - x0).days for d, _ in recent]
        y = [float(w) for _, w in recent]
        n = len(x)
        sx, sy = sum(x), sum(y)
        sxy = sum(a * b for a, b in zip(x, y))
        sxx = sum(a * a for a in x)
        denom = n * sxx - sx * sx
        slope_per_day = (n * sxy - sx * sy) / denom if denom else 0.0
        weekly_rate = round(slope_per_day * 7, 2)

    span = (datetime.strptime(recent[-1][0], "%Y-%m-%d") - datetime.strptime(recent[0][0], "%Y-%m-%d")).days if len(recent) >= 2 else 0
    provisional = span < provisional_days

    projected_goal_date, days_to_goal = None, None
    if (
        weekly_rate < 0
        and current_weight is not None
        and goal_weight is not None
        and current_weight > goal_weight
        and not provisional
        and abs(slope_per_day) > 0
    ):
        days = (current_weight - goal_weight) / abs(slope_per_day)
        projected_goal_date = (ref + timedelta(days=days)).strftime("%Y-%m-%d")
        days_to_goal = int(days)

    return {
        "weekly_rate_lbs": weekly_rate,
        "slope_per_day": slope_per_day,
        "rate_provisional": provisional,
        "weighin_span_days": span,
        "projected_goal_date": projected_goal_date,
        "days_to_goal": days_to_goal,
    }
