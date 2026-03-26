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
    "baseline_snapshot",
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


# ==============================================================================
# BASELINE SNAPSHOT — Day 1 capture
# ==============================================================================

def tool_capture_baseline(args: dict) -> dict:
    """
    Capture a full-state baseline snapshot across all key domains.
    Stores a permanent record in platform_memory under 'baseline_snapshot'.

    This is designed to be run once on Day 1 (April 1, 2026) to create
    the anchor point that all future progress is measured against.

    Args:
        date: Optional date override (YYYY-MM-DD). Defaults to today.
        label: Optional label (e.g. 'day_1', 'month_3'). Defaults to 'day_1'.
        force: If True, overwrites any existing snapshot for that date.
               Defaults to False (safety against accidental re-runs).

    Returns:
        Full snapshot record with all captured metrics.
    """
    from boto3.dynamodb.conditions import Key as DDBKey
    from decimal import Decimal

    table = _get_table()
    uid = _get_user_id()
    today = datetime.now(timezone.utc).date().isoformat()
    date_str = args.get("date") or today
    label = args.get("label", "day_1")
    force = args.get("force", False)

    # Safety: don't overwrite unless forced
    if not force:
        existing_pk = _memory_pk()
        existing_sk = _sk("baseline_snapshot", date_str)
        existing = table.get_item(Key={"pk": existing_pk, "sk": existing_sk})
        if existing.get("Item"):
            return {
                "error": "Baseline snapshot already exists for this date.",
                "date": date_str,
                "hint": "Use force=true to overwrite, or choose a different date.",
            }

    def _latest_from(source, proj=None):
        """Get most recent record from a source partition."""
        pk = f"USER#{uid}#SOURCE#{source}"
        kwargs = {
            "KeyConditionExpression": DDBKey("pk").eq(pk),
            "Limit": 1,
            "ScanIndexForward": False,
        }
        if proj:
            kwargs["ProjectionExpression"] = proj
        resp = table.query(**kwargs)
        items = resp.get("Items", [])
        return _d2f(items[0]) if items else None

    def _latest_sot(domain):
        """Get most recent SOT record for a domain."""
        pk = f"USER#{uid}#SOURCE#sot"
        prefix = f"DOMAIN#{domain}#"
        resp = table.query(
            KeyConditionExpression=DDBKey("pk").eq(pk) & DDBKey("sk").begins_with(prefix),
            Limit=1,
            ScanIndexForward=False,
        )
        items = resp.get("Items", [])
        return _d2f(items[0]) if items else None

    # ── Gather data across domains ────────────────────────────
    snapshot = {
        "label": label,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    # Weight / body composition
    withings = _latest_from("withings")
    if withings:
        snapshot["weight_lbs"] = withings.get("weight_lbs") or withings.get("weight")
        snapshot["body_fat_pct"] = withings.get("body_fat_pct") or withings.get("fat_ratio")
        snapshot["muscle_mass_lbs"] = withings.get("muscle_mass_lbs")
        snapshot["weight_date"] = withings.get("date")

    # Blood pressure
    bp = _latest_from("blood_pressure")
    if bp:
        snapshot["systolic"] = bp.get("systolic")
        snapshot["diastolic"] = bp.get("diastolic")
        snapshot["heart_rate_bp"] = bp.get("heart_rate")
        snapshot["bp_date"] = bp.get("date")

    # Whoop recovery / HRV / RHR
    whoop = _latest_from("whoop")
    if whoop:
        snapshot["hrv"] = whoop.get("hrv")
        snapshot["resting_hr"] = whoop.get("resting_heart_rate")
        snapshot["recovery_score"] = whoop.get("recovery_score")
        snapshot["sleep_score"] = whoop.get("sleep_score")
        snapshot["whoop_date"] = whoop.get("date")

    # Character Sheet score
    char_sot = _latest_sot("character")
    if char_sot:
        snapshot["character_composite"] = char_sot.get("composite_score")
        snapshot["character_pillars"] = {
            k: v for k, v in char_sot.items()
            if k.endswith("_score") and k != "composite_score"
        }
        snapshot["character_date"] = char_sot.get("date")

    # Habit completion (latest SOT)
    habit_sot = _latest_sot("habits")
    if habit_sot:
        snapshot["t0_completion_pct"] = habit_sot.get("tier0_completion_pct")
        snapshot["overall_completion_pct"] = habit_sot.get("completion_pct")
        snapshot["habit_date"] = habit_sot.get("date")

    # Vice streaks
    vice_sot = _latest_sot("vices")
    if vice_sot:
        snapshot["vice_streaks"] = {
            k: v for k, v in vice_sot.items()
            if "streak" in k.lower() or "days" in k.lower()
        }
        snapshot["vice_date"] = vice_sot.get("date")

    # CGM / glucose (if available)
    cgm = _latest_from("cgm")
    if cgm:
        snapshot["avg_glucose"] = cgm.get("average_glucose") or cgm.get("avg_glucose")
        snapshot["time_in_range_pct"] = cgm.get("time_in_range_pct")
        snapshot["cgm_date"] = cgm.get("date")

    # Nutrition (latest MacroFactor)
    macro = _latest_from("macrofactor")
    if macro:
        snapshot["calories"] = macro.get("calories")
        snapshot["protein_g"] = macro.get("protein")
        snapshot["nutrition_date"] = macro.get("date")

    # ── Store the snapshot ────────────────────────────────────
    result = tool_write_platform_memory(
        category="baseline_snapshot",
        content=snapshot,
        date=date_str,
        overwrite=force,
    )

    return {
        "status": result.get("status", "error"),
        "label": label,
        "date": date_str,
        "domains_captured": [
            k for k in [
                "weight" if "weight_lbs" in snapshot else None,
                "blood_pressure" if "systolic" in snapshot else None,
                "recovery" if "hrv" in snapshot else None,
                "character" if "character_composite" in snapshot else None,
                "habits" if "t0_completion_pct" in snapshot else None,
                "vices" if "vice_streaks" in snapshot else None,
                "glucose" if "avg_glucose" in snapshot else None,
                "nutrition" if "calories" in snapshot else None,
            ] if k
        ],
        "snapshot": snapshot,
    }
