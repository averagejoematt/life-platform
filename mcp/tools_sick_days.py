"""
Sick day MCP tools: log, view, and clear sick/rest days.

Tools:
  log_sick_day  — flag one or more dates as sick/rest days
  get_sick_days — list sick days within a date range
  clear_sick_day — remove a sick day flag (if logged in error)

DDB partition: SOURCE#sick_days
  pk = USER#<id>#SOURCE#sick_days
  sk = DATE#YYYY-MM-DD

Effects when a date is flagged:
  - Character Sheet EMA frozen (no gain, no penalty)
  - Day grade stored as "sick" (not scored)
  - Habit + streak timers preserved from previous day (not broken, not advanced)
  - Anomaly alerts suppressed
  - Freshness checker alerts suppressed
  - Daily Brief shows recovery banner, skips habit/nutrition coaching

v1.0.0 — 2026-03-09
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

from mcp.config import table, USER_ID, logger

SICK_DAYS_PK = f"USER#{USER_ID}#SOURCE#sick_days"


def _d2f(obj):
    if isinstance(obj, list):    return [_d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


# ── Tool: log_sick_day ────────────────────────────────────────────────────────

def tool_log_sick_day(args):
    """Flag one or more dates as sick/rest days."""
    date_arg  = args.get("date")
    dates_arg = args.get("dates")
    reason    = (args.get("reason") or "").strip()

    if not date_arg and not dates_arg:
        return {"error": "Provide 'date' (single YYYY-MM-DD) or 'dates' (list of YYYY-MM-DD)."}

    dates = dates_arg if dates_arg else [date_arg]

    for d in dates:
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            return {"error": f"Invalid date format: '{d}'. Use YYYY-MM-DD."}

    written = []
    for d in dates:
        item = {
            "pk":             SICK_DAYS_PK,
            "sk":             f"DATE#{d}",
            "date":           d,
            "logged_at":      datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        }
        if reason:
            item["reason"] = reason
        table.put_item(Item=item)
        written.append(d)
        logger.info(f"[sick_days] Logged sick day: {d} reason={reason or 'none'}")

    return {
        "status":  "logged",
        "dates":   written,
        "reason":  reason or None,
        "message": (
            f"Flagged {len(written)} sick day(s): {', '.join(written)}. "
            "Effects: Character Sheet EMA frozen, day grade = 'sick', "
            "streak timers preserved (not broken, not advanced), "
            "anomaly alerts suppressed, freshness alerts skipped, "
            "Daily Brief shows recovery banner. "
            "Re-run character-sheet-compute and daily-metrics-compute to apply retroactively."
        ),
    }


# ── Tool: get_sick_days ───────────────────────────────────────────────────────

def tool_get_sick_days(args):
    """List sick/rest days within a date range."""
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date  = args.get("end_date")  or today
    start_date = args.get("start_date") or (
        datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)
    ).strftime("%Y-%m-%d")

    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": SICK_DAYS_PK,
                ":s":  f"DATE#{start_date}",
                ":e":  f"DATE#{end_date}",
            },
        )
        items = [_d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.error(f"[sick_days] get_sick_days query failed: {e}")
        return {"error": str(e)}

    return {
        "sick_days":  items,
        "count":      len(items),
        "date_range": {"start": start_date, "end": end_date},
        "dates":      [i["date"] for i in items],
    }


# ── Tool: clear_sick_day ──────────────────────────────────────────────────────

def tool_clear_sick_day(args):
    """Remove a sick day flag (use if logged in error)."""
    date = args.get("date")
    if not date:
        return {"error": "Provide 'date' in YYYY-MM-DD format."}
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"error": f"Invalid date format: '{date}'. Use YYYY-MM-DD."}

    resp = table.get_item(Key={"pk": SICK_DAYS_PK, "sk": f"DATE#{date}"})
    if not resp.get("Item"):
        return {
            "status":  "not_found",
            "date":    date,
            "message": f"No sick day record found for {date}.",
        }

    table.delete_item(Key={"pk": SICK_DAYS_PK, "sk": f"DATE#{date}"})
    logger.info(f"[sick_days] Cleared sick day: {date}")

    return {
        "status":  "cleared",
        "date":    date,
        "message": (
            f"Sick day flag removed for {date}. "
            "Re-run character-sheet-compute and daily-metrics-compute with "
            "force=true to recompute affected records."
        ),
    }


def tool_manage_sick_days(args):
    """Unified sick day management dispatcher."""
    VALID_ACTIONS = {
        "list":  tool_get_sick_days,
        "log":   tool_log_sick_day,
        "clear": tool_clear_sick_day,
    }
    action = (args.get("action") or "list").lower().strip()
    if action not in VALID_ACTIONS:
        return {"error": f"Unknown action '{action}'.", "valid_actions": list(VALID_ACTIONS.keys()),
                "hint": "'list' to view sick days, 'log' to flag a date (requires date=), 'clear' to remove flag (requires date=)."}
    return VALID_ACTIONS[action](args)
