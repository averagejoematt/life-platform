"""
tools_memory.py — IC-1: Platform Memory DDB partition.

The compounding intelligence substrate. Stores structured key-value memories
computed by the platform: failure patterns, episodic "what worked" records,
coaching calibration, weekly plate history, and future IC features.

DDB key pattern: pk=USER#matthew#SOURCE#platform_memory,
                 sk=MEMORY#<category>#<date>#<content-hash10>   (#4171 — one row PER NOTE)
                 sk=MEMORY#<category>#<date>                    (legacy — one row per category-day)

#4171 (2026-09-26, P2 data loss): the key used to be one row per category per day and the
default was to overwrite, so approving a queued training note at 02:16:35Z silently erased
the injury note written on the same key 60 s earlier. Every write is now ADDITIVE — the
sort key ends in a content hash, so a second same-day note is a second row and a replayed
identical write converges on the first (mcp/idempotency.py: CONTENT_KEY). The ONLY way to
overwrite is `replace_key=<exact sk>`, and both branches are CONDITIONAL puts
(attribute_not_exists / attribute_exists on the row) so a race cannot clobber either way.
Every reader ranges or prefixes on `MEMORY#<category>#<date…>`, so legacy 3-segment rows
and 4-segment rows are served together, newest first.

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

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from common.pacific_time import pacific_now  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

from mcp.config import USER_ID as _user_id_ref, table as _table_ref
from mcp.core import decimal_to_float as _d2f
from mcp.layer_status import DERIVED_LAYERS, LAYER_DEGRADED, LAYER_OK, counted, layer_fields, read_status

try:
    # Shared, bundled module (#781) — staged at zip root in the Lambda.
    from ai import platform_memory as _pm
    from common.numeric import floats_to_decimal as _floats_to_decimal
except ImportError:  # pragma: no cover — MCP bundle always ships lambdas/ at root
    if not TYPE_CHECKING:
        from lambdas import platform_memory as _pm
        from lambdas.common.numeric import floats_to_decimal as _floats_to_decimal


def _get_table():
    return _table_ref


def _get_user_id():
    return _user_id_ref


MEMORY_SOURCE = "platform_memory"

# #4355: the MCP role has no dynamodb:DeleteItem for this partition (checked live
# 2026-09-27T22:59Z — AccessDeniedException) and is deliberately NOT getting one — the
# scoped grant this role does carry (macrofactor_meals, LeadingKeys) exists for exactly one
# other tool, and widening it for chat-facing memory would let an LLM-driven call erase a
# row instead of just marking it gone. So delete is a SOFT delete: an UpdateItem tombstone
# (`deleted_at` + `deleted_reason`), conditional so a race can neither double-tombstone nor
# resurrect one, using an action this role already holds unconditionally. Every reader of
# the partition (`tool_read_platform_memory`, `tool_list_memory_categories`, the coach
# prompt's `select_conversation_memories`, and the compute readers of computed categories)
# skips a row once `deleted_at` is set — the row stays in DDB (auditable, and cheaply
# reversible by a human with console access) but is gone from every surface a coach or a
# chat tool can see. This is a DIFFERENT flag from the experiment-restart `tombstone=true`
# (phase_filter.singleton_visible) — reusing that field would make `restart_rollback.py
# --full-unwind` resurrect a note Matthew explicitly asked to delete.
_DELETED_AT_FIELD = "deleted_at"
_DELETED_REASON_FIELD = "deleted_reason"
_DEFAULT_DELETE_REASON = "mcp_delete"

# #2663: page cap for the category census. The window can no longer be pushed into the
# key condition (the sk's date is its LAST segment, not its first), so the partition is
# read whole and filtered after. Bounded so a runaway partition cannot hang the tool —
# `scan_exhausted` in the response says plainly when the cap was the stopping condition.
_MEMORY_MAX_PAGES = 20

# Canonical sanctioned set — derived from the code registry (#1482), never a
# second hand-maintained list. Aliases (failure_pattern → failure_patterns,
# episodic_wins → what_worked) are normalized on write/read.
VALID_CATEGORIES = set(_pm.MEMORY_CATEGORIES)


def _memory_pk():
    return f"USER#{_get_user_id()}#SOURCE#{MEMORY_SOURCE}"


def _channels_of(category):
    """Which writers a category admits (#1482 registry) — part of the layer_health block."""
    spec = _pm.MEMORY_CATEGORIES.get(category) or {}
    return list(spec.get("channels") or [])


def _sk(category, date_str):
    """The category-day PREFIX (and the legacy one-row-per-day key). Readers range on it;
    #4171 writers append a content hash (`_note_sk`) so a same-day note never shares a key."""
    return f"MEMORY#{category}#{date_str}"


# #4171: the per-note suffix. Ten hex chars of sha256 over the canonical JSON of what the
# writer supplied (content + the validated privacy_tier/domains) — the same canonical form
# as `mcp.audit.args_hash`, and the same shape as `mark_journal_quote`'s
# QUOTE#{date}#{sha256(norm(quote))[:10]}, the in-repo CONTENT_KEY precedent.
_NOTE_HASH_LEN = 10


def _note_hash(content: dict, privacy_tier, domains) -> str:
    payload = {"content": content, "privacy_tier": privacy_tier, "domains": domains}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_NOTE_HASH_LEN]


def _note_sk(category, date_str, content, privacy_tier, domains) -> str:
    return f"{_sk(category, date_str)}#{_note_hash(content, privacy_tier, domains)}"


def _sk_parts(sk: str) -> tuple[str | None, str | None]:
    """(category, date) named by a MEMORY# sort key — 3-segment legacy or 4-segment note."""
    parts = str(sk or "").split("#")
    if len(parts) < 3 or parts[0] != "MEMORY":
        return None, None
    return parts[1], parts[2]


def _is_conditional_failure(exc: Exception) -> bool:
    return "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailed" in str(exc)


def _same_category_key(category: str, sk: str) -> bool:
    """True when `sk` names `category` (aliases included — legacy rows may carry the alias spelling)."""
    named, _date = _sk_parts(sk)
    return named is not None and _pm.canonical_category(named) == category


# ==============================================================================
# TOOL FUNCTIONS
# ==============================================================================


def tool_write_platform_memory(args: dict) -> dict:
    """
    Store a structured memory record in the platform_memory partition — ADDITIVELY (#4171).

    Args (via args dict):
        category: Memory category — must be in the sanctioned taxonomy
                  (lambdas/platform_memory.py, #1482); aliases normalized
                  (e.g. 'episodic_wins' → 'what_worked').
        content: Dict of key-value data to store. Will be merged into the DDB item.
                 Put the human-readable core in a 'summary' or 'text' field —
                 that's what the coach-prompt block renders.
        date: Date key for the record (YYYY-MM-DD). Defaults to today.
        replace_key: The EXACT sort key (as `read_platform_memory` returns it in `sk`) of the
                     ONE record to rewrite. This is the only path that overwrites anything, and
                     it is a conditional put (attribute_exists) — replacing a key that is not
                     there is refused, never a silent insert. Without it every write is a new
                     row keyed MEMORY#<category>#<date>#<content-hash>; an identical replay
                     converges on the existing row (status "unchanged").
        privacy_tier: Optional per-record override ('public_ok' | 'coach_context'
                      | 'private') — may only TIGHTEN the category default.
        domains: Optional list of bare coach ids this memory is relevant to
                 (e.g. ["nutrition", "training"]); default = the category rule.

    `overwrite` was RETIRED by #4171 — its default (True) is what erased the 2026-09-25
    injury note. `overwrite=true` is refused with a pointer to `replace_key`;
    `overwrite=false` (the old additive form) is accepted and ignored.

    Returns:
        {"status": "stored" | "replaced" | "unchanged", "sk": "...", "category": "...", "date": "..."}
    """
    raw_category = args.get("category", "")
    content = args.get("content", {})
    date = args.get("date")
    replace_key = args.get("replace_key")
    privacy_tier = args.get("privacy_tier")
    domains = args.get("domains")

    table = _get_table()
    today = pacific_now().date().isoformat()

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
    if args.get("overwrite") is True:
        return {
            "error": (
                "`overwrite` was retired by #4171 — every write is additive, so nothing here overwrites by default. "
                "To rewrite ONE existing record pass replace_key=<its exact sk from read_platform_memory>; "
                "to add a note alongside the existing ones, drop the overwrite argument."
            ),
            "hint": "read_platform_memory(category=…) lists each record's sk — that is the handle replace_key takes",
        }
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

    # #4171: the key. A named record is the ONLY thing a write may replace, and the name
    # must be one of this category's own rows — a replace_key naming another category (or
    # not a MEMORY# key at all) is a caller error, never a cross-category overwrite.
    if replace_key is not None:
        if not isinstance(replace_key, str) or not replace_key.strip():
            return {"error": "replace_key must be the exact sk string of the record to rewrite"}
        replace_key = replace_key.strip()
        if not _same_category_key(category, replace_key):
            return {
                "error": f"replace_key {replace_key!r} does not name a '{category}' record — "
                "it must be a sk returned by read_platform_memory for this category",
            }
        _cat, key_date = _sk_parts(replace_key)
        if date and date != key_date:
            return {"error": f"date {date!r} disagrees with the date inside replace_key ({key_date!r}) — drop `date` to keep the row's day"}
        date_str = key_date or today
        sk = replace_key
    else:
        date_str = date or today
        sk = _note_sk(category, date_str, content, privacy_tier, domains)

    # Honest provenance (#1482): this tool is the CHAT surface — a write through
    # it is conversation-channel when the category sanctions conversation,
    # otherwise it inherits the category's (computed) channel.
    spec = _pm.MEMORY_CATEGORIES[category]
    channel = _pm.CHANNEL_CONVERSATION if _pm.CHANNEL_CONVERSATION in spec["channels"] else spec["channels"][0]

    pk = _memory_pk()

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
    if replace_key is not None:
        item["replaced_at"] = item["stored_at"]

    # Decimal before DDB — the whole item, nested values included (common.numeric).
    item = _floats_to_decimal(item)

    # #4171: BOTH branches are conditional. There is no unconditional put in this tool —
    # tests/test_platform_memory_block.py walks this function's AST to keep it that way.
    if replace_key is not None:
        try:
            table.put_item(Item=item, ConditionExpression="attribute_exists(sk)")
        except Exception as e:  # noqa: BLE001 — only the conditional failure is ours to interpret
            if _is_conditional_failure(e):
                return {
                    "error": f"nothing to replace at {sk!r} — that key is not in the store (deleted, or never written). "
                    "Nothing was written. Drop replace_key to add the note as a new record.",
                    "sk": sk,
                }
            raise
        return {"status": "replaced", "sk": sk, "replaced_key": sk, "category": category, "date": date_str, "channel": channel}

    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001
        if _is_conditional_failure(e):
            # A replay: the identical note already sits on this key. Nothing to add, nothing lost.
            return {
                "status": "unchanged",
                "reason": "an identical record already exists on this key — a replayed write converges (#3114). "
                "A distinct note needs different content; a rewrite of this one needs replace_key.",
                "sk": sk,
                "category": category,
                "date": date_str,
            }
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
    canonical = _pm.canonical_category(category)
    if canonical is None:
        # #3920: the SAME error the write path returns — a read of a category that does not exist
        # is a caller's mistake, not a measured `count: 0` with `sanctioned: false` beside it.
        return {
            "error": f"unknown category '{category}' — reads must name a sanctioned taxonomy category (#1482)",
            "sanctioned_categories": _pm.sanctioned_categories(),
            "conversation_categories": _pm.conversation_categories(),
            "hint": "call list_memory_categories for the full taxonomy (descriptions, channels, privacy tiers)",
        }
    category = canonical

    table = _get_table()
    days = min(max(1, int(days)), 365)
    limit = min(max(1, int(limit)), 50)

    today = pacific_now().date()
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
                    # #4355: a soft-deleted note is a tombstone (deleted_at set), never
                    # `delete_item` — filter it out here rather than at the caller, or
                    # `read_platform_memory`/stage 1 would keep quoting it.
                    "FilterExpression": f"attribute_not_exists({_DELETED_AT_FIELD})",
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
    except Exception as e:
        # #3769: an unreadable layer withholds its count (None, never 0) and omits the
        # list an empty read would have returned — an empty list is a claim.
        status, reason = read_status(error=e)
        return {
            "error": str(e),
            "category": category,
            "count": counted(status, 0),
            **layer_fields(status, reason, producer=DERIVED_LAYERS["platform_memory"]["producer"], channels=_channels_of(category)),
        }
    records = [_d2f(i) for i in resp.get("Items", [])]
    # #4171: the sk STAYS on each record — it is the handle `replace_key` (write) and `key`
    # (delete) take, and a caller cannot name a row it was never shown. Only the pk is
    # dropped (one constant for the whole partition, no information). Within one day the
    # key orders notes by content hash, so the page is re-sorted newest-first by the
    # instant each note was stored; the date stays the primary order.
    clean = []
    for r in records:
        if r.get(_DELETED_AT_FIELD):
            # #4355: belt-and-suspenders — the query's own FilterExpression already
            # excludes tombstoned rows against real DynamoDB, but a soft-deleted row
            # must never surface even if that server-side filter is ever bypassed
            # (a test double, a future caller that drops _apply_phase_filter, etc).
            continue
        r.pop("pk", None)
        clean.append(r)
    clean.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("stored_at") or ""), str(r.get("sk") or "")), reverse=True)
    # A successful read of a sanctioned category with nothing in the window is a measured
    # zero (nobody wrote); the health block says which channels COULD have written it.
    return {
        "category": category,
        "records": clean,
        "count": counted(LAYER_OK, len(clean)),
        **layer_fields(
            LAYER_OK,
            producer=DERIVED_LAYERS["platform_memory"]["producer"],
            channels=_channels_of(category),
            sanctioned=category in VALID_CATEGORIES,
        ),
    }


def tool_list_memory_categories(args: dict) -> dict:
    """
    List all memory categories that have records, with counts.

    Args (via args dict):
        days: How many days back to scan (default 90).

    Returns:
        {"categories": [{"category": "...", "count": N, "latest_date": "..."}], "total_records": N}
    """
    days = min(max(1, int(args.get("days", 90))), 365)

    table = _get_table()
    today = pacific_now().date()
    start = (today - timedelta(days=days)).isoformat()

    # #2663: `days` was applied to the WRONG SEGMENT of the sort key. The sk is
    # `MEMORY#<category>#<date>` (see _memory_sk), but the query ranged
    # `BETWEEN "MEMORY#<start-date>" AND "MEMORY#~"` — comparing a date string against
    # CATEGORY NAMES. Lexically every category ('b'…'w') sorts above any 'YYYY-…' and
    # below '~', so the range matched the entire partition no matter what `days` said,
    # and a 1-day window returned records from May. The argument was not decorative, as
    # filed — it was a filter silently evaluated against the wrong thing, which is worse:
    # it would also have EXCLUDED a whole category the day one was named with a leading
    # digit. Date cannot be range-queried from this key at all, so the window is applied
    # after the read, over a fully paginated partition.
    pk = _memory_pk()

    try:
        from mcp.core import _apply_phase_filter  # ADR-058

        items: list[dict] = []
        start_key = None
        pages = 0
        while pages < _MEMORY_MAX_PAGES:
            params = _apply_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :p)",
                    "ExpressionAttributeValues": {":pk": pk, ":p": "MEMORY#"},
                    # #4355: project deleted_at too (filtered below) — a soft-deleted note
                    # must not count in the category census either.
                    "ProjectionExpression": f"sk, category, #d, {_DELETED_AT_FIELD}",
                    "ExpressionAttributeNames": {"#d": "date"},
                }
            )
            if start_key is not None:
                params["ExclusiveStartKey"] = start_key
            resp = table.query(**params)
            items.extend(resp.get("Items", []))
            start_key = resp.get("LastEvaluatedKey")
            pages += 1
            if not start_key:
                break

        # Group by category, keeping only records inside the requested window. The date
        # falls back to the sk's own DATE segment (index 2 — #4171 keys carry a content
        # hash after it, so "last segment" is no longer the date): it is the authoritative
        # copy (the key is built from it), so a row missing the duplicate `date` attribute
        # is dated correctly rather than silently landing in every window as "".
        from collections import defaultdict

        cats = defaultdict(list)
        in_window = 0
        for item in items:
            if item.get(_DELETED_AT_FIELD):
                continue  # #4355: a soft-deleted note is not a live record — don't census it
            date = item.get("date") or (_sk_parts(item.get("sk", ""))[1] or "")
            if not date or date < start:
                continue
            in_window += 1
            cats[item.get("category", "unknown")].append(date)

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

        # #3769: a page-capped census is a DEGRADED read — every count is a floor and the
        # response says so in the contract's own vocabulary, not only in `scan_exhausted`.
        status, reason = (
            (LAYER_OK, "")
            if start_key is None
            else (LAYER_DEGRADED, f"census stopped at the {_MEMORY_MAX_PAGES}-page cap — counts are floors")
        )
        return {
            "categories": result,
            # ADR-104: say what each number counted. `total_records` is the window (what
            # `categories` sums to); `records_scanned` is the whole partition it was
            # filtered out of. `scan_exhausted` False means even that is a floor.
            "total_records": counted(status, in_window),
            "records_scanned": counted(status, len(items)),
            "scan_exhausted": start_key is None,
            "lookback_days": days,
            "window_start": start,
            # #1482: the sanctioned taxonomy (code registry: lambdas/platform_memory.py)
            # — chat modes (#1479) read this to route takeaways into valid categories.
            "taxonomy": _pm.taxonomy_summary(),
            **layer_fields(status, reason, producer=DERIVED_LAYERS["platform_memory"]["producer"], pages_read=pages),
        }
    except Exception as e:
        status, reason = read_status(error=e)
        return {
            "error": str(e),
            "total_records": counted(status, 0),
            "records_scanned": counted(status, 0),
            "lookback_days": days,
            **layer_fields(status, reason, producer=DERIVED_LAYERS["platform_memory"]["producer"]),
        }


def tool_delete_platform_memory(args: dict) -> dict:
    """
    Soft-delete a specific memory record by category + date (the legacy one-row-per-day
    key), or by its exact sort key (#4171 per-note row).

    The MCP role carries no dynamodb:DeleteItem for this partition (#4355) — this is a
    TOMBSTONE, not a DynamoDB delete. The row survives in the table (auditable) but is
    stamped `deleted_at`/`deleted_reason` and every reader (read_platform_memory,
    list_memory_categories, the coach prompt's memory block, the compute readers of
    computed categories) skips it from that instant on.

    Args (via args dict):
        category: Memory category.
        date: Date of the record to delete (YYYY-MM-DD) — names the legacy
              `MEMORY#<category>#<date>` row.
        key: The exact sk (as `read_platform_memory` returns it) — the only way to name a
             #4171 per-note row (`MEMORY#<category>#<date>#<hash>`). Must belong to `category`.
        reason: Optional short note on why (defaults to "mcp_delete").

    Returns:
        {"status": "deleted", "sk": "...", "deleted_at": "..."} or {"status": "not_found"}
    """
    category = args.get("category", "")
    date = args.get("date", "")
    key = args.get("key")
    reason = str(args.get("reason") or "").strip() or _DEFAULT_DELETE_REASON

    table = _get_table()
    pk = _memory_pk()
    if key is not None:
        if not isinstance(key, str) or not key.strip():
            return {"error": "key must be the exact sk string of the record to delete"}
        key = key.strip()
        canonical = _pm.canonical_category(category) if category else None
        if canonical is None or not _same_category_key(canonical, key):
            return {
                "error": f"key {key!r} does not name a '{category}' record — pass the sk read_platform_memory returned for this category"
            }
        sk = key
        date = date or (_sk_parts(sk)[1] or "")
    elif not date:
        return {"error": "date (the legacy category-day row) or key (an exact sk) is required"}
    else:
        sk = _sk(category, date)

    try:
        # Check it exists (and is not already tombstoned) first, for the honest
        # "not_found" branch — an UpdateItem on a missing key would otherwise SEED one
        # (attribute_exists guards that below, but a caller-visible "not_found" is clearer
        # than a conditional-check error string).
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        if not item or item.get(_DELETED_AT_FIELD):
            return {"status": "not_found", "sk": sk}
        deleted_at = datetime.now(timezone.utc).isoformat()
        # #4355: UpdateItem, never DeleteItem — the MCP role holds dynamodb:UpdateItem
        # unconditionally on this table already. Conditional on both attribute_exists(sk)
        # (never seed a row that isn't there) and attribute_not_exists(deleted_at) (never
        # re-tombstone — the first deletion's reason/instant wins a race).
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression=f"SET {_DELETED_AT_FIELD} = :da, {_DELETED_REASON_FIELD} = :dr",
            ConditionExpression=f"attribute_exists(sk) AND attribute_not_exists({_DELETED_AT_FIELD})",
            ExpressionAttributeValues={":da": deleted_at, ":dr": reason},
        )
        return {"status": "deleted", "sk": sk, "category": category, "date": date, "deleted_at": deleted_at}
    except Exception as e:  # noqa: BLE001 — a lost race (already deleted) reads as not_found
        if _is_conditional_failure(e):
            return {"status": "not_found", "sk": sk}
        return {"error": str(e), "sk": sk}


# ==============================================================================
# BASELINE SNAPSHOT — Day 1 capture
# ==============================================================================
