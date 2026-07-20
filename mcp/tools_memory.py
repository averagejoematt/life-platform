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

The category taxonomy is CODE, not prose (#1482): lambdas/platform_memory.py
is the canonical registry (per-category channels, retention/relevance window,
privacy tier, coach-domain relevance, durable-vs-scoped). Writes here are
validated against it and stamped with honest provenance (channel, provenance)
so the coach-prompt consumption seam (platform_memory.platform_memory_block)
can inject conversation-derived memories without passing them off as data.
"""

from datetime import datetime, timedelta, timezone

from mcp.config import USER_ID as _user_id_ref, table as _table_ref
from mcp.core import decimal_to_float as _d2f

try:
    # Shared, bundled module (#781) — staged at zip root in the Lambda.
    import platform_memory as _pm
except ImportError:  # pragma: no cover — MCP bundle always ships lambdas/ at root
    from lambdas import platform_memory as _pm


def _get_table():
    return _table_ref


def _get_user_id():
    return _user_id_ref


MEMORY_SOURCE = "platform_memory"

# Canonical sanctioned set — derived from the code registry (#1482), never a
# second hand-maintained list. Aliases (failure_pattern → failure_patterns,
# episodic_wins → what_worked) are normalized on write/read.
VALID_CATEGORIES = set(_pm.MEMORY_CATEGORIES)


def _memory_pk():
    return f"USER#{_get_user_id()}#SOURCE#{MEMORY_SOURCE}"


def _sk(category, date_str):
    return f"MEMORY#{category}#{date_str}"


# ==============================================================================
# TOOL FUNCTIONS
# ==============================================================================


def tool_write_platform_memory(args: dict) -> dict:
    """
    Store a structured memory record in the platform_memory partition.

    Args (via args dict):
        category: Memory category — must be in the sanctioned taxonomy
                  (lambdas/platform_memory.py, #1482); aliases normalized
                  (e.g. 'episodic_wins' → 'what_worked').
        content: Dict of key-value data to store. Will be merged into the DDB item.
                 Put the human-readable core in a 'summary' or 'text' field —
                 that's what the coach-prompt block renders.
        date: Date key for the record (YYYY-MM-DD). Defaults to today.
        overwrite: If True (default), overwrites existing record for this category+date.
        privacy_tier: Optional per-record override ('public_ok' | 'coach_context'
                      | 'private') — may only TIGHTEN the category default.
        domains: Optional list of bare coach ids this memory is relevant to
                 (e.g. ["nutrition", "training"]); default = the category rule.

    Returns:
        {"status": "stored", "sk": "...", "category": "...", "date": "..."}
    """
    raw_category = args.get("category", "")
    content = args.get("content", {})
    date = args.get("date")
    overwrite = args.get("overwrite", True)
    privacy_tier = args.get("privacy_tier")
    domains = args.get("domains")

    table = _get_table()
    today = datetime.now(timezone.utc).date().isoformat()
    date_str = date or today

    if not raw_category:
        return {"error": "category is required"}
    category = _pm.canonical_category(raw_category)
    if category is None:
        return {
            "error": f"unknown category '{raw_category}' — writes must land in a sanctioned taxonomy category (#1482)",
            "sanctioned_categories": _pm.sanctioned_categories(),
            "conversation_categories": _pm.conversation_categories(),
            "hint": "call list_memory_categories for the full taxonomy (descriptions, channels, privacy tiers)",
        }
    if not isinstance(content, dict):
        return {"error": "content must be a dict"}
    # PR #1581 review (minor): content-supplied domains/privacy_tier go through
    # the SAME validation as the top-level args (args win) — a domains list
    # smuggled inside `content` can no longer silently exclude the record from
    # every coach, and an invalid tier is rejected instead of stored raw.
    if privacy_tier is None:
        privacy_tier = content.get("privacy_tier")
    if domains is None:
        domains = content.get("domains")
    if privacy_tier is not None and privacy_tier not in _pm.PRIVACY_TIERS:
        return {"error": f"privacy_tier must be one of {list(_pm.PRIVACY_TIERS)}"}
    if domains is not None:
        if not isinstance(domains, list):
            return {"error": "domains must be a list of bare coach ids"}
        normalized = [_pm.normalize_domain(d) for d in domains]
        if any(d is None for d in normalized):
            return {"error": f"unknown coach domain in {domains} — valid: {sorted(_pm.COACH_DOMAINS)}"}
        domains = normalized

    # Honest provenance (#1482): this tool is the CHAT surface — a write through
    # it is conversation-channel when the category sanctions conversation,
    # otherwise it inherits the category's (computed) channel.
    spec = _pm.MEMORY_CATEGORIES[category]
    channel = _pm.CHANNEL_CONVERSATION if _pm.CHANNEL_CONVERSATION in spec["channels"] else spec["channels"][0]

    pk = _memory_pk()
    sk = _sk(category, date_str)

    item = {
        "pk": pk,
        "sk": sk,
    }
    item.update(content)
    # Meta fields win over any same-named content keys — keys and provenance
    # are stamped by the platform, never supplied by the writer.
    item.update(
        {
            "pk": pk,
            "sk": sk,
            "category": category,
            "date": date_str,
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "channel": channel,
            "provenance": "mcp",
        }
    )
    if privacy_tier is not None:
        item["privacy_tier"] = privacy_tier
    if domains is not None:
        item["domains"] = domains

    # Convert any float values to Decimal for DynamoDB compatibility
    from decimal import Decimal as _Dec

    for k, v in item.items():
        if isinstance(v, float):
            item[k] = _Dec(str(v))

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

    return {"status": "stored", "sk": sk, "category": category, "date": date_str, "channel": channel}


def tool_read_platform_memory(args: dict) -> dict:
    """
    Retrieve recent memory records for a given category.

    Args (via args dict):
        category: Memory category to retrieve.
        days: How many days back to look (default 30, max 365).
        limit: Max records to return (default 10, max 50).

    Returns:
        {"category": "...", "records": [...], "count": N}
    """
    category = args.get("category", "")
    days = args.get("days", 30)
    limit = args.get("limit", 10)

    # Accept aliases on read too (failure_pattern → failure_patterns, …).
    category = _pm.canonical_category(category) or category

    table = _get_table()
    days = min(max(1, int(days)), 365)
    limit = min(max(1, int(limit)), 50)

    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()

    pk = _memory_pk()
    start_sk = _sk(category, start)
    end_sk = _sk(category, end) + "~"  # ~ sorts after all dates

    try:
        from mcp.core import _apply_phase_filter  # ADR-058

        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                    "ExpressionAttributeValues": {
                        ":pk": pk,
                        ":s": start_sk,
                        ":e": end_sk,
                    },
                    "ScanIndexForward": False,
                    "Limit": limit,
                }
            )
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


def tool_list_memory_categories(args: dict) -> dict:
    """
    List all memory categories that have records, with counts.

    Args (via args dict):
        days: How many days back to scan (default 90).

    Returns:
        {"categories": [{"category": "...", "count": N, "latest_date": "..."}], "total_records": N}
    """
    days = args.get("days", 90)

    table = _get_table()
    days = min(max(1, int(days)), 365)

    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()

    pk = _memory_pk()
    start_sk = f"MEMORY#{start}"
    end_sk = "MEMORY#~"

    try:
        from mcp.core import _apply_phase_filter  # ADR-058

        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
                    "ExpressionAttributeValues": {
                        ":pk": pk,
                        ":s": start_sk,
                        ":e": end_sk,
                    },
                    "ProjectionExpression": "sk, category, #d",
                    "ExpressionAttributeNames": {"#d": "date"},
                }
            )
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
            result.append(
                {
                    "category": cat,
                    "count": len(dates),
                    "latest_date": max(dates) if dates else None,
                    "oldest_date": min(dates) if dates else None,
                }
            )

        return {
            "categories": result,
            "total_records": len(items),
            "lookback_days": days,
            # #1482: the sanctioned taxonomy (code registry: lambdas/platform_memory.py)
            # — chat modes (#1479) read this to route takeaways into valid categories.
            "taxonomy": _pm.taxonomy_summary(),
        }
    except Exception as e:
        return {"error": str(e)}


def tool_delete_platform_memory(args: dict) -> dict:
    """
    Delete a specific memory record by category + date.

    Args (via args dict):
        category: Memory category.
        date: Date of the record to delete (YYYY-MM-DD).

    Returns:
        {"status": "deleted", "sk": "..."} or {"status": "not_found"}
    """
    category = args.get("category", "")
    date = args.get("date", "")

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
