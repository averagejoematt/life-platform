"""brief_food_delivery.py — the Morning Brief's food-delivery streak line (moved out of daily_brief_lambda, #6175).

Moved verbatim (behaviour unchanged) to pay for the hybrid-trial lines under the module-size ceiling (#1665);
`daily_brief_lambda.get_food_delivery_brief_signal()` is the unchanged entry point and hands in its own table,
clock and Pacific day, so the suite's module-wide time freeze still reaches it.
"""

from __future__ import annotations

from common.digest_utils import get_food_delivery_streak_state


def signal(table, user_id, now_utc, today_str):
    """Returns a one-line signal for the daily brief nutrition section.

    Reads the food_delivery STREAK#current record via the shared #2235 read path
    (get_food_delivery_streak_state) and returns a contextual message about the
    current delivery-free streak or recent order — None (no line at all) once the
    source is stale, rather than a frozen count from the last import. Non-fatal —
    returns None on any error.

    Gated by nutrition_delivery_public() (P2.3, #2209/#2210, this door #2233) —
    checked BEFORE the query, matching the sibling readers in
    web/site_api_meals.py and web/site_api_nutrition.py. With the flag off
    (default), the food_delivery partition is never queried and no
    delivery-derived narrative reaches the daily brief, group_narratives, or
    the public public_stats.json artifact it feeds. The gate lives INSIDE this
    function (not at its one current call site) so every future caller is
    protected without anyone needing to remember to re-check the flag.
    """
    from web.site_api_common import nutrition_delivery_public

    if not nutrition_delivery_public():
        return None
    try:
        streak = get_food_delivery_streak_state(table, user_id, now=now_utc)
        if not streak:
            return None
        streak_days = int(streak.get("streak_days", 0))
        last_order = streak.get("last_order_date", "")
        if last_order == today_str:
            return "Food delivery ordered today — nutrition score modifier applied (0.85x)."
        if streak_days >= 30:
            return f"Delivery-free streak: {streak_days} days — nutrition bonus active (1.10x)."
        if streak_days >= 14:
            return f"Delivery-free streak: {streak_days} days — nutrition bonus active (1.05x)."
        if streak_days >= 7:
            return f"Delivery-free streak: {streak_days} days — nutrition bonus active (1.02x)."
        if streak_days > 0:
            return f"Delivery-free streak: {streak_days} days."
        return None
    except Exception:
        return None
