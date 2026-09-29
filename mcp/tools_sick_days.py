"""
Sick day MCP tools: log, view, and clear sick/rest days.

Tools:
  log_sick_day  — flag one or more dates as sick/rest days
  get_sick_days — list sick days within a date range
  clear_sick_day — remove a sick day flag (if logged in error) — a tombstone, #4378

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

from datetime import datetime, timedelta, timezone

from mcp.config import USER_ID, logger, table

SICK_DAYS_PK = f"USER#{USER_ID}#SOURCE#sick_days"


from common.digest_utils import d2f as _d2f  # shared bundled helpers (#970)
from common.pacific_time import pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from health import sick_day_checker as _sdc  # #4378: THE clear (tombstone) + the cleared-row predicate every reader shares

# ── Tool: log_sick_day ────────────────────────────────────────────────────────


def _log_sick_day(args):
    """Flag one or more dates as sick/rest days."""
    date_arg = args.get("date")
    dates_arg = args.get("dates")
    reason = (args.get("reason") or "").strip()

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
            "pk": SICK_DAYS_PK,
            "sk": f"DATE#{d}",
            "date": d,
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        }
        if reason:
            item["reason"] = reason
        table.put_item(Item=item)
        written.append(d)
        logger.info(f"[sick_days] Logged sick day: {d} reason={reason or 'none'}")

    return {
        "status": "logged",
        "dates": written,
        "reason": reason or None,
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


def _get_sick_days(args):
    """List sick/rest days within a date range."""
    today = pacific_today()
    end_date = args.get("end_date") or today
    start_date = args.get("start_date") or (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")

    try:
        from mcp.core import _apply_phase_filter  # ADR-058

        # ADR-058: longitudinal/clinical archive — cross-phase by design (owner decision 2026-06-06)
        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                    "ExpressionAttributeValues": {
                        ":pk": SICK_DAYS_PK,
                        ":s": f"DATE#{start_date}",
                        ":e": f"DATE#{end_date}",
                    },
                },
                include_pilot=True,
            )
        )
        # #4378: a cleared (tombstoned) row is not a sick day — never listed.
        items = [_d2f(i) for i in resp.get("Items", []) if not _sdc.is_cleared(i)]
    except Exception as e:
        logger.error(f"[sick_days] get_sick_days query failed: {e}")
        return {"error": str(e)}

    return {
        "sick_days": items,
        "count": len(items),
        "date_range": {"start": start_date, "end": end_date},
        "dates": [i["date"] for i in items],
    }


# ── Tool: clear_sick_day ──────────────────────────────────────────────────────


def _clear_sick_day(args):
    """Remove a sick day flag (use if logged in error)."""
    date = args.get("date")
    if not date:
        return {"error": "Provide 'date' in YYYY-MM-DD format."}
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"error": f"Invalid date format: '{date}'. Use YYYY-MM-DD."}

    # #4378: the MCP role holds no dynamodb:DeleteItem on this partition — clear is a
    # conditional UpdateItem tombstone (cleared_at/cleared_reason) that every reader
    # (sick_day_checker.check_sick_day / get_sick_days_range, the list action above)
    # treats as "not a sick day". None = there was no live flag (absent or already cleared).
    reason = (args.get("reason") or "").strip() or None
    cleared_at = _sdc.clear_sick_day(table, USER_ID, date, reason=reason)
    if cleared_at is None:
        return {
            "status": "not_found",
            "date": date,
            "message": f"No sick day record found for {date} (or it was already cleared).",
        }
    logger.info(f"[sick_days] Cleared sick day: {date}")

    return {
        "status": "cleared",
        "date": date,
        "cleared_at": cleared_at,
        "message": (
            f"Sick day flag removed for {date} (tombstoned — no reader counts it as sick from now on). "
            "Re-run character-sheet-compute and daily-metrics-compute with "
            "force=true to recompute affected records."
        ),
    }


def tool_manage_sick_days(args):
    """Unified sick day management dispatcher."""
    VALID_ACTIONS = {
        "list": _get_sick_days,
        "log": _log_sick_day,
        "clear": _clear_sick_day,
    }
    action = (args.get("action") or "list").lower().strip()
    if action not in VALID_ACTIONS:
        return {
            "error": f"Unknown action '{action}'.",
            "valid_actions": list(VALID_ACTIONS.keys()),
            "hint": "'list' to view sick days, 'log' to flag a date (requires date=), 'clear' to remove flag (requires date=).",
        }
    return VALID_ACTIONS[action](args)
