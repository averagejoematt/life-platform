"""manage_meals MCP tool — the derived meal layer (read + regroup).

One fat tool (SIMP-1) with four actions:
  get_day(date)               → grouped meals/snacks for a date (reads macrofactor_meals)
  most_eaten(start,end,...)   → rank meals by signature/template_id, snacks by member token
  regroup_day(date, dry_run)  → re-run the deterministic grouper on raw + upsert projection
  list_templates()            → the seed template library

Henning standard: every aggregate keys on the deterministic `template_id`/`signature`,
NEVER the (inferred, mutable) display name — a flaky name can't corrupt a count.
`uncategorized` is excluded from analytics; an n-floor (`min_n`) gates "most-eaten".
Snacks aggregate by canonical member token (not the "Snack" occasion) so co-logged
staples aren't undercounted.

Reads the derived `macrofactor_meals` partition directly (no phase filter — the
projection carries no phase attr). regroup_day runs the layer's meal_grouper +
meal_projection (the same deterministic system of record the backfill uses).
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from mcp.config import USER_ID, logger, table
from mcp.core import query_source

MEALS_SOURCE = "macrofactor_meals"
MEALS_PK = f"USER#{USER_ID}#SOURCE#{MEALS_SOURCE}"
_CORE_MACROS = ["calories_kcal", "protein_g", "carbs_g", "fat_g"]


def _d2f(obj):
    if isinstance(obj, list):
        return [_d2f(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def _valid_date(d):
    try:
        datetime.strptime(d, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _query_meal_items(start_date, end_date):
    items, kwargs = [], {
        "KeyConditionExpression": Key("pk").eq(MEALS_PK) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}~"),
    }
    while True:
        r = table.query(**kwargs)
        items += r.get("Items", [])
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return _d2f(items)


# ── actions ───────────────────────────────────────────────────────────────────
def _get_day(date):
    if not _valid_date(date):
        return {"error": "Provide a valid date YYYY-MM-DD."}
    items = sorted(_query_meal_items(date, date), key=lambda it: it.get("ordinal", 0))
    if not items:
        return {"date": date, "meals": [], "note": "No meal projection for this date. Try regroup_day, or backfill hasn't run."}
    return {
        "date": date,
        "count": len(items),
        "meals": [
            {
                "ordinal": it.get("ordinal"),
                "name": it.get("meal_name"),
                "kind": it.get("kind"),
                "template_id": it.get("template_id"),
                "inferred": True,
                "confidence": it.get("confidence"),
                "time": (it.get("time_window") or {}).get("start"),
                "rollup": it.get("rollup"),
                "members": [r.get("food_name") for r in (it.get("member_refs") or [])],
                "sides": [s.get("food_name") for s in (it.get("sides") or [])],
                "signature": it.get("signature"),
            }
            for it in items
        ],
    }


def _most_eaten(start_date, end_date, limit, min_n):
    if not (_valid_date(start_date) and _valid_date(end_date)):
        return {"error": "Provide valid start_date and end_date (YYYY-MM-DD)."}
    items = _query_meal_items(start_date, end_date)

    meal_agg = defaultdict(lambda: {"count": 0, "names": defaultdict(int), "dates": set(), "macro_sum": defaultdict(float)})
    snack_agg = defaultdict(lambda: {"count": 0, "dates": set()})
    for it in items:
        kind = it.get("kind")
        if kind == "meal":
            key = it.get("template_id") or it.get("signature")  # NEVER the display name
            a = meal_agg[key]
            a["count"] += 1
            a["names"][it.get("meal_name") or "?"] += 1
            a["dates"].add(it.get("date"))
            for m in _CORE_MACROS:
                a["macro_sum"][m] += float((it.get("rollup") or {}).get(m, 0) or 0)
        elif kind == "snack":
            # aggregate by canonical member token, not the "Snack" occasion
            for ref in it.get("member_refs") or []:
                tok = ref.get("token")
                if not tok:
                    continue
                snack_agg[tok]["count"] += 1
                snack_agg[tok]["dates"].add(it.get("date"))
        # uncategorized excluded from analytics (Henning / SPEC §6)

    meals = []
    for key, a in meal_agg.items():
        if a["count"] < min_n:
            continue
        top_name = max(a["names"].items(), key=lambda kv: kv[1])[0]
        meals.append(
            {
                "key": key,
                "name": top_name,
                "count": a["count"],
                "days": len(a["dates"]),
                "avg_macros": {m: round(a["macro_sum"][m] / a["count"], 1) for m in _CORE_MACROS},
            }
        )
    meals.sort(key=lambda x: (-x["count"], x["key"]))

    snacks = [{"token": tok, "count": s["count"], "days": len(s["dates"])} for tok, s in snack_agg.items() if s["count"] >= min_n]
    snacks.sort(key=lambda x: (-x["count"], x["token"]))

    return {
        "window": {"start": start_date, "end": end_date},
        "n_floor": min_n,
        "inferred": True,
        "note": "Meals keyed on template_id/signature (not display name); uncategorized excluded; snacks by member token.",
        "most_eaten_meals": meals[:limit],
        "top_snack_staples": snacks[:limit],
    }


def _regroup_day(date, dry_run):
    if not _valid_date(date):
        return {"error": "Provide a valid date YYYY-MM-DD."}
    try:
        from meal_grouper import group_day  # shared layer
        from meal_projection import write_day_projection
    except ImportError as e:
        logger.error("meal grouper/projection not importable (layer not deployed?): %s", e)
        return {"error": f"Meal grouper unavailable in this Lambda (rebuild + deploy the shared layer): {e}"}

    raw = query_source("macrofactor", date, date)
    food_log = (raw[0].get("food_log") if raw else None) or []
    if not food_log:
        return {"date": date, "error": "No raw MacroFactor food_log for this date (daily-summary or no data)."}

    groups = group_day(food_log)  # asserts conservation; raises on reconcile failure
    res = write_day_projection(table, date, groups, user=USER_ID, dry_run=dry_run)
    meals = sorted((g for g in groups if g["kind"] == "meal"), key=lambda g: g["time_window"]["start"] or "")
    return {
        "date": date,
        "dry_run": dry_run,
        "wrote": res["wrote"],
        "stale_pruned": res["stale_pruned"],
        "meals": [g["meal_name"] for g in meals],
        "snacks": sum(1 for g in groups if g["kind"] == "snack"),
        "uncategorized": sum(1 for g in groups if g["kind"] == "uncategorized"),
    }


def _list_templates():
    try:
        from meal_templates_seed import get_seed_templates
    except ImportError as e:
        return {"error": f"Seed templates unavailable (rebuild + deploy the shared layer): {e}"}
    tpls = get_seed_templates()
    return {
        "count": len(tpls),
        "templates": [
            {
                "template_id": t["template_id"],
                "name": t["name"],
                "anchors": t["anchors"],
                "modifiers": t["modifiers"],
                "key_modifiers": t.get("key_modifiers") or [],
                "source": t["source"],
            }
            for t in tpls
        ],
    }


def tool_manage_meals(args):
    """Dispatch the manage_meals actions."""
    args = args or {}
    action = (args.get("action") or "").strip()
    if action == "get_day":
        return _get_day(args.get("date"))
    if action == "most_eaten":
        return _most_eaten(
            args.get("start_date"),
            args.get("end_date"),
            int(args.get("limit", 10)),
            int(args.get("min_n", 3)),
        )
    if action == "regroup_day":
        return _regroup_day(args.get("date"), bool(args.get("dry_run", False)))
    if action == "list_templates":
        return _list_templates()
    return {"error": "Unknown action. Use: get_day | most_eaten | regroup_day | list_templates."}
