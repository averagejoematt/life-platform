"""
tools_memory.py — IC-1: Platform Memory DDB partition.

The compounding intelligence substrate. Stores structured key-value memories
computed by the platform: failure patterns, episodic "what worked" records,
coaching calibration, weekly plate history, and future IC features.

DDB key pattern: pk=USER#matthew#SOURCE#platform_memory, sk=MEMORY#<category>#<date>

Tools:
  136. write_platform_memory  — store a memory record
  137. read_platform_memory   — retrieve recent memories by category
  138. list_memory_categories — what categories exist with record counts
  139. delete_platform_memory — delete a specific memory record

Categories seeded now:
  weekly_plate   — plate history for anti-repeat (P1)
  failure_pattern — when IC-4 is built
  what_worked    — when IC-9 is built
  coaching_calibration — when IC-11 is built
  personal_curves — when IC-10 is built
  journey_milestone — for IC-6 milestone architecture
"""

import json
from datetime import datetime, timedelta, timezone
from mcp.config import table as _table_ref, USER_ID as _user_id_ref
from mcp.core import decimal_to_float as _d2f

def _get_table():
    return _table_ref

def _get_user_id():
    return _user_id_ref

MEMORY_SOURCE = "platform_memory"

VALID_CATEGORIES = {
    "weekly_plate",
    "failure_pattern",
    "what_worked",
    "coaching_calibration",
    "personal_curves",
    "journey_milestone",
    "insight",
    "experiment_result",
}


def _memory_pk():
    return f"USER#{_get_user_id()}#SOURCE#{MEMORY_SOURCE}"


def _sk(category, date_str):
    return f"MEMORY#{category}#{date_str}"


# ==============================================================================
# TOOL FUNCTIONS
# ==============================================================================

def tool_write_platform_memory(category: str, content: dict, date: str = None,
                                overwrite: bool = True) -> dict:
    """
    Store a structured memory record in the platform_memory partition.

    Args:
        category: Memory category (e.g. 'failure_pattern', 'what_worked',
                  'coaching_calibration', 'journey_milestone', 'weekly_plate').
        content: Dict of key-value data to store. Will be merged into the DDB item.
        date: Date key for the record (YYYY-MM-DD). Defaults to today.
        overwrite: If True (default), overwrites existing record for this category+date.

    Returns:
        {"status": "stored", "sk": "...", "category": "...", "date": "..."}
    """
    table = _get_table()
    today = datetime.now(timezone.utc).date().isoformat()
    date_str = date or today

    if not category:
        return {"error": "category is required"}
    if not isinstance(content, dict):
        return {"error": "content must be a dict"}

    pk = _memory_pk()
    sk = _sk(category, date_str)

    item = {
        "pk": pk,
        "sk": sk,
        "category": category,
        "date": date_str,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }
    item.update(content)

    if overwrite:
        table.put_item(Item=item)
    else:
        # Conditional write — don't overwrite if exists
        try:
            table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
        except Exception as e:
            if "ConditionalCheckFailed" in str(e):
                return {"status": "skipped", "reason": "record already exists", "sk": sk}
            raise

    return {"status": "stored", "sk": sk, "category": category, "date": date_str}


def tool_read_platform_memory(category: str, days: int = 30, limit: int = 10) -> dict:
    """
    Retrieve recent memory records for a given category.

    Args:
        category: Memory category to retrieve.
        days: How many days back to look (default 30, max 365).
        limit: Max records to return (default 10, max 50).

    Returns:
        {"category": "...", "records": [...], "count": N}
    """
    table = _get_table()
    days = min(max(1, days), 365)
    limit = min(max(1, limit), 50)

    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()

    pk = _memory_pk()
    start_sk = _sk(category, start)
    end_sk = _sk(category, end) + "~"  # ~ sorts after all dates

    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s": start_sk,
                ":e": end_sk,
            },
            ScanIndexForward=False,
            Limit=limit,
        )
        records = [_d2f(i) for i in resp.get("Items", [])]
        # Remove internal DDB keys from response for readability
        clean = []
        for r in records:
            r.pop("pk", None)
            r.pop("sk", None)
            clean.append(r)
        return {"category": category, "records": clean, "count": len(clean)}
    except Exception as e:
        return {"error": str(e), "category": category}


def tool_list_memory_categories(days: int = 90) -> dict:
    """
    List all memory categories that have records, with counts.

    Args:
        days: How many days back to scan (default 90).

    Returns:
        {"categories": [{"category": "...", "count": N, "latest_date": "..."}], "total_records": N}
    """
    table = _get_table()
    days = min(max(1, days), 365)

    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()

    pk = _memory_pk()
    start_sk = f"MEMORY#{start}"
    end_sk = f"MEMORY#~"

    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s": start_sk,
                ":e": end_sk,
            },
            ProjectionExpression="sk, category, #d",
            ExpressionAttributeNames={"#d": "date"},
        )
        items = resp.get("Items", [])

        # Group by category
        from collections import defaultdict
        cats = defaultdict(list)
        for item in items:
            cat = item.get("category", "unknown")
            date = item.get("date", "")
            cats[cat].append(date)

        result = []
        for cat, dates in sorted(cats.items()):
            result.append({
                "category": cat,
                "count": len(dates),
                "latest_date": max(dates) if dates else None,
                "oldest_date": min(dates) if dates else None,
            })

        return {
            "categories": result,
            "total_records": len(items),
            "lookback_days": days,
        }
    except Exception as e:
        return {"error": str(e)}


def tool_delete_platform_memory(category: str, date: str) -> dict:
    """
    Delete a specific memory record by category + date.

    Args:
        category: Memory category.
        date: Date of the record to delete (YYYY-MM-DD).

    Returns:
        {"status": "deleted", "sk": "..."} or {"status": "not_found"}
    """
    table = _get_table()
    pk = _memory_pk()
    sk = _sk(category, date)

    try:
        # Check it exists first
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        if not resp.get("Item"):
            return {"status": "not_found", "sk": sk}
        table.delete_item(Key={"pk": pk, "sk": sk})
        return {"status": "deleted", "sk": sk, "category": category, "date": date}
    except Exception as e:
        return {"error": str(e), "sk": sk}
