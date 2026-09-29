"""
Sick Day Checker — bundled shared utility (lambdas/ tree).

Provides a lightweight DDB check so all Lambdas can test whether a given
date has been flagged as a sick/rest day without duplicating query logic.

DDB schema:
  pk  = USER#<user_id>#SOURCE#sick_days
  sk  = DATE#YYYY-MM-DD
  fields: date, reason (optional), logged_at, schema_version
          cleared_at / cleared_reason — set only on a cleared (tombstoned) row, #4378

Used by:
  character_sheet_lambda      — freeze EMA on sick days
  daily_metrics_compute_lambda — store grade="sick", preserve streaks
  anomaly_detector_lambda      — suppress alert emails
  freshness_checker_lambda     — suppress stale-source alerts
  daily_brief_lambda           — show recovery banner, skip coaching

v1.0.0 — 2026-03-09
"""

from datetime import datetime, timezone

SICK_DAYS_SOURCE = "sick_days"

# #4378: clearing a sick day is a TOMBSTONE, not a DynamoDB delete — the MCP role (the
# only clearer: manage_sick_days action='clear') holds no dynamodb:DeleteItem on this
# partition; its one scoped grant is macrofactor_meals. A cleared row is stamped
# `cleared_at` (+ `cleared_reason`) by a conditional UpdateItem and stays in the table as
# the audit trail of a "logged in error" correction. EVERY reader goes through
# check_sick_day / get_sick_days_range (or `is_cleared` for its own query), which treat a
# cleared row as NOT a sick day — so character-sheet, daily-metrics, anomaly, freshness,
# daily-brief, adaptive-mode and the coach-prediction evaluator all stop counting it at
# once. Re-logging the date is a put_item that overwrites the tombstone whole.
CLEARED_AT_FIELD = "cleared_at"
CLEARED_REASON_FIELD = "cleared_reason"


from common.digest_utils import d2f as _d2f  # shared bundled helpers (#970)


def is_cleared(item):
    """True iff this sick-day row was cleared (tombstoned, #4378) — not a sick day."""
    return bool((item or {}).get(CLEARED_AT_FIELD))


def check_sick_day(table, user_id, date_str):
    """Return sick day record dict for *date_str*, or None if not flagged.

    Safe to call from any Lambda — returns None on any error rather than raising.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        return _d2f(item) if item and not is_cleared(item) else None
    except Exception as e:
        print(f"[WARN] sick_day_checker.check_sick_day({date_str}): {e}")
        return None


def get_sick_days_range(table, user_id, start_date, end_date):
    """Return list of sick day record dicts within a date range (inclusive).

    Returns empty list on any error.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s": f"DATE#{start_date}",
                ":e": f"DATE#{end_date}~",
            },
        )
        return [_d2f(i) for i in resp.get("Items", []) if not is_cleared(i)]
    except Exception as e:
        print(f"[WARN] sick_day_checker.get_sick_days_range({start_date}→{end_date}): {e}")
        return []


def write_sick_day(table, user_id, date_str, reason=None):
    """Write a sick day record. Idempotent — safe to call multiple times for the same date."""
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    item = {
        "pk": pk,
        "sk": sk,
        "date": date_str,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
    }
    if reason:
        item["reason"] = reason
    table.put_item(Item=item)
    return item


def clear_sick_day(table, user_id, date_str, reason=None):
    """Clear (tombstone) the sick-day flag for *date_str* — #4378, never DeleteItem.

    Returns the ``cleared_at`` instant, or None when there was no live flag to clear
    (absent, or already cleared — the condition fails and nothing is written).
    Any other DynamoDB error propagates: a failed clear must never read as success.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    cleared_at = datetime.now(timezone.utc).isoformat()
    try:
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression=f"SET {CLEARED_AT_FIELD} = :ca, {CLEARED_REASON_FIELD} = :cr",
            ConditionExpression=f"attribute_exists(sk) AND attribute_not_exists({CLEARED_AT_FIELD})",
            ExpressionAttributeValues={":ca": cleared_at, ":cr": (reason or "logged_in_error")},
        )
    except Exception as e:  # noqa: BLE001 — only the lost condition is "nothing to clear"
        if "ConditionalCheckFailed" in f"{type(e).__name__} {e}":
            return None
        raise
    return cleared_at
