"""platform_memory.py — the platform-memory category taxonomy + the coach-prompt
consumption seam (#1482, epic #1476: conversation as the fourth ingestion channel).

This module is the CANONICAL category registry for the platform_memory DDB
partition (pk = USER#{user}#SOURCE#platform_memory, sk = MEMORY#<category>#<date>).
docs/SCHEMA.md documents the taxonomy; this registry is the enforcement point —
the MCP write tool (mcp/tools_memory.py) rejects categories that aren't here, and
phase_taxonomy's durable/scoped split for platform_memory must agree with the
``durable`` flag here (cross-registry drift gate in tests/test_platform_memory_block.py).

Two halves:

1. MEMORY_CATEGORIES — per-category rules: sanctioned write channels, the
   relevance window for prompt injection (retention_days), a privacy tier, which
   coach domains the category informs, and whether records survive an experiment
   reset (durable → cross_phase in lambdas/phase_taxonomy.py).

2. platform_memory_block() — the bounded, provenance-honest prompt block of
   CONVERSATION-DERIVED memories (channel == "conversation") that ai_calls
   injects into coach generation prompts alongside the journal-mood block.
   Mirrors the coach_checkin.recent_checkins_block idiom: pure formatting over
   the store, returns "" on empty or ANY failure — a context block must never
   break a prompt. The block sits in the system prompt ABOVE the few-shot
   block, so its numbers enter the ADR-104 fabrication allow-list via
   ai_calls._allowlist_prompt — injected memories are valid grounding sources
   by construction, not by exemption.

Token budget (ADR-063, the $85/mo guard): the block is hard-capped by
DEFAULT_MAX_ITEMS records and DEFAULT_MAX_CHARS characters (~450 tokens) per
coach per generation — a bounded, deterministic cost, never an open-ended dump.

Privacy tiers (issue #1482; #1483 will formalize the public-site side):
  - "public_ok"     — a coach may cite it on public-facing surfaces.
  - "coach_context" — injected into coach prompts as background; the rendered
                      line is marked "(shared in confidence)" and the block
                      instructs the coach to let it inform the read without
                      restating the specifics.
  - "private"       — NEVER injected into any generation prompt; readable only
                      via the MCP read tool.
A record may carry its own privacy_tier field; it may only TIGHTEN the
category default (public_ok < coach_context < private), never loosen it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date as _date, datetime, timezone

logger = logging.getLogger(__name__)

MEMORY_SOURCE = "platform_memory"
MEMORY_SK_PREFIX = "MEMORY#"

# ── channels ─────────────────────────────────────────────────────────────────
CHANNEL_CONVERSATION = "conversation"  # Matthew ↔ Claude chat, written via MCP (#1476)
CHANNEL_COMPUTED = "computed"  # platform lambdas / restart tooling writing directly
CHANNELS = (CHANNEL_CONVERSATION, CHANNEL_COMPUTED)

# ── privacy tiers (ordered loosest → tightest) ───────────────────────────────
TIER_PUBLIC_OK = "public_ok"
TIER_COACH_CONTEXT = "coach_context"
TIER_PRIVATE = "private"
PRIVACY_TIERS = (TIER_PUBLIC_OK, TIER_COACH_CONTEXT, TIER_PRIVATE)
_TIER_RANK = {t: i for i, t in enumerate(PRIVACY_TIERS)}

# Bare operational coach ids. Kept as a local literal so this module imports
# with zero deps; tests assert it equals persona_registry.OPERATIONAL_SHORT_IDS.
COACH_DOMAINS = frozenset({"sleep", "training", "nutrition", "mind", "physical", "glucose", "labs", "explorer"})
ALL_DOMAINS = "all"

# ── the taxonomy ─────────────────────────────────────────────────────────────
# Every category that may legally exist in the partition. Fields:
#   description     — what belongs here (chat modes #1479 read this via
#                     list_memory_categories to route writes).
#   channels        — sanctioned write channels.
#   retention_days  — the relevance window: records older than this are never
#                     prompt-injected (store retention is separate — see SCHEMA.md).
#   privacy_tier    — default tier (per-record override may only tighten).
#   coach_domains   — "all" or a frozenset of bare coach ids this category
#                     informs (per-record `domains` list may narrow further).
#   durable         — True → cross_phase (survives an experiment reset); must
#                     agree with phase_taxonomy.MEMORY_DURABLE/SCOPED_CATEGORIES.
MEMORY_CATEGORIES: dict[str, dict] = {
    # ── conversation-derived (the #1476 fourth channel) ──────────────────────
    "life_context": {
        "description": "Durable life events and situation shared in chat — travel, work stress, family, schedule disruptions.",
        "channels": (CHANNEL_CONVERSATION,),
        "retention_days": 365,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": True,
    },
    "constraints_preferences": {
        "description": "Standing constraints and preferences — equipment, injuries, food dislikes, timing, what framing works for him.",
        "channels": (CHANNEL_CONVERSATION,),
        "retention_days": 730,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": True,
    },
    "coaching_calibration": {
        "description": "How to coach Matthew — computed response patterns plus explicit asks from chat ('push harder').",
        "channels": (CHANNEL_CONVERSATION, CHANNEL_COMPUTED),
        "retention_days": 365,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    "failure_patterns": {
        "description": "Conditions preceding low days — computed attribution plus failure modes Matthew narrates in chat.",
        "channels": (CHANNEL_CONVERSATION, CHANNEL_COMPUTED),
        "retention_days": 180,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    "what_worked": {
        "description": "Episodic wins — above-baseline outcomes and what produced them (computed or told in chat).",
        "channels": (CHANNEL_CONVERSATION, CHANNEL_COMPUTED),
        "retention_days": 365,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    # ── computed-only (existing IC features; never conversation-writable) ────
    "weekly_plate": {
        "description": "Weekly plate history for anti-repeat (weekly_plate_lambda).",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 60,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": frozenset({"nutrition"}),
        "durable": False,
    },
    "personal_curves": {
        "description": "Personal response curves (IC-10) — e.g. weight-loss rate vs. intake.",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 365,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    "journey_milestone": {
        "description": "Weight/health milestones with biological significance (IC-6).",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 365,
        "privacy_tier": TIER_PUBLIC_OK,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    "insight": {
        "description": "Ad-hoc structured insights stored to memory.",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 90,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    "experiment_result": {
        "description": "Concluded experiment outcomes.",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 365,
        "privacy_tier": TIER_PUBLIC_OK,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    "intention_tracking": {
        "description": "Stated intentions vs. actual outcomes (IC-8, daily-insight compute).",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 30,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    "hypothesis_monitoring": {
        "description": "Compact hypothesis-engine monitoring block (IC-16 consumption).",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 60,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": False,
    },
    # ── durable system/baseline records (restart tooling, Day-1 capture) ─────
    "baseline_snapshot": {
        "description": "Day-1 baseline capture — survives resets.",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 3650,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": ALL_DOMAINS,
        "durable": True,
    },
    "re_entry": {
        "description": "Restart tooling re-entry marker.",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 3650,
        "privacy_tier": TIER_PRIVATE,
        "coach_domains": ALL_DOMAINS,
        "durable": True,
    },
    "cycle_marker": {
        "description": "Experiment-cycle marker (restart tooling).",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 3650,
        "privacy_tier": TIER_PRIVATE,
        "coach_domains": ALL_DOMAINS,
        "durable": True,
    },
    "cycle": {
        "description": "Experiment-cycle record (restart tooling).",
        "channels": (CHANNEL_COMPUTED,),
        "retention_days": 3650,
        "privacy_tier": TIER_PRIVATE,
        "coach_domains": ALL_DOMAINS,
        "durable": True,
    },
}

# Historical / suggested-name aliases → canonical category. Writes through the
# MCP tool are normalized; reads accept either form. ("failure_pattern" was the
# original IC-1 singular; the compute lambda writes the plural. "episodic_wins"
# is issue #1482's suggested name for what the store already calls what_worked.)
CATEGORY_ALIASES = {
    "failure_pattern": "failure_patterns",
    "episodic_wins": "what_worked",
}

# ── prompt-injection budget (ADR-063) ────────────────────────────────────────
DEFAULT_MAX_ITEMS = 6
DEFAULT_MAX_CHARS = 1800  # ≈450 tokens — hard deterministic cap per coach per generation
_LINE_TEXT_CAP = 280  # per-record text cap inside the block
# Per-category read window for the block's DDB queries (PR #1581 review fix).
# Within ONE category the sk suffix is the date, so a descending begins_with
# query is truly newest-first; the headroom over DEFAULT_MAX_ITEMS absorbs rows
# the in-code filters drop AFTER the read (DynamoDB applies Limit BEFORE any
# FilterExpression — tombstones, private tier, per-record domain narrowing).
_PER_CATEGORY_QUERY_LIMIT = 25

_META_FIELDS = {
    "pk",
    "sk",
    "category",
    "date",
    "stored_at",
    "written_at",
    "written_by",
    "channel",
    "provenance",
    "privacy_tier",
    "domains",
    "phase",
    "cycle",
    "tombstone",
    "tombstoned_at",
    "record_type",
    "version",
}


def canonical_category(name) -> str | None:
    """Resolve a category name (or alias) to its canonical registry key, else None."""
    if not isinstance(name, str) or not name:
        return None
    name = name.strip()
    if name in MEMORY_CATEGORIES:
        return name
    return CATEGORY_ALIASES.get(name)


def sanctioned_categories() -> list[str]:
    """All canonical categories, sorted — the MCP write tool's valid set."""
    return sorted(MEMORY_CATEGORIES)


def conversation_categories() -> list[str]:
    """Categories a chat mode may write (channel 'conversation' sanctioned)."""
    return sorted(c for c, spec in MEMORY_CATEGORIES.items() if CHANNEL_CONVERSATION in spec["channels"])


def taxonomy_summary() -> list[dict]:
    """Compact registry view for list_memory_categories — what chat modes (#1479)
    read to route a takeaway into a sanctioned category."""
    out = []
    for cat in sanctioned_categories():
        spec = MEMORY_CATEGORIES[cat]
        out.append(
            {
                "category": cat,
                "description": spec["description"],
                "channels": list(spec["channels"]),
                "privacy_tier": spec["privacy_tier"],
                "retention_days": spec["retention_days"],
                "conversation_writable": CHANNEL_CONVERSATION in spec["channels"],
            }
        )
    return out


def normalize_domain(coach_id) -> str | None:
    """'sleep_coach' / 'sleep' → 'sleep'; unknown → None."""
    if not isinstance(coach_id, str) or not coach_id:
        return None
    bare = coach_id.strip().removesuffix("_coach")
    return bare if bare in COACH_DOMAINS else None


def effective_tier(record: dict, spec: dict) -> str:
    """The category default, tightened (never loosened) by a per-record override."""
    default = spec["privacy_tier"]
    override = record.get("privacy_tier")
    if override in _TIER_RANK and _TIER_RANK[override] > _TIER_RANK[default]:
        return override
    return default


def _category_of(record: dict) -> str | None:
    cat = record.get("category")
    if not cat:
        sk = str(record.get("sk") or "")
        if sk.startswith(MEMORY_SK_PREFIX) and sk.count("#") >= 2:
            cat = sk.split("#", 2)[1]
    return canonical_category(cat)


def _date_of(record: dict) -> _date | None:
    raw = record.get("date")
    if not raw:
        sk = str(record.get("sk") or "")
        parts = sk.split("#")
        raw = parts[2] if len(parts) >= 3 else None
    try:
        return _date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _record_text(record: dict) -> str:
    """Human-readable payload of a memory record for the prompt line. Prefers an
    explicit text field; falls back to a compact k=v join of non-meta fields."""
    for key in ("summary", "text", "note", "detail", "content", "what", "pattern"):
        val = record.get(key)
        if isinstance(val, str) and val.strip():
            text = val.strip()
            break
        if isinstance(val, (dict, list)) and val:
            text = json.dumps(val, default=str, separators=(", ", ": "))
            break
    else:
        parts = []
        for k in sorted(record):
            if k in _META_FIELDS:
                continue
            v = record[k]
            if v in (None, "", [], {}):
                continue
            parts.append(f"{k}: {v if isinstance(v, str) else json.dumps(v, default=str, separators=(', ', ': '))}")
        text = "; ".join(parts)
    text = " ".join(text.split())  # collapse whitespace/newlines — one record, one line
    if len(text) > _LINE_TEXT_CAP:
        text = text[: _LINE_TEXT_CAP - 1].rstrip() + "…"
    return text


def select_conversation_memories(records, coach_id=None, max_items: int = DEFAULT_MAX_ITEMS, today: _date | None = None) -> list[dict]:
    """Filter raw partition records down to the injectable conversation-derived
    set for one coach: channel == conversation, category sanctioned for
    conversation, tier not private, inside the category relevance window, and
    domain-relevant. Returns newest-first, capped at max_items."""
    today = today or datetime.now(timezone.utc).date()
    domain = normalize_domain(coach_id) if coach_id else None
    picked = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("channel") != CHANNEL_CONVERSATION:
            continue  # honest provenance: only records STAMPED as chat-derived
        cat = _category_of(rec)
        if cat is None:
            continue
        spec = MEMORY_CATEGORIES[cat]
        if CHANNEL_CONVERSATION not in spec["channels"]:
            continue
        if effective_tier(rec, spec) == TIER_PRIVATE:
            continue
        rec_date = _date_of(rec)
        if rec_date is None or (today - rec_date).days > spec["retention_days"] or rec_date > today:
            continue
        domains = rec.get("domains") or spec["coach_domains"]
        if domain is not None and domains != ALL_DOMAINS:
            allowed = {normalize_domain(d) for d in domains} if not isinstance(domains, str) else {normalize_domain(domains)}
            if domain not in allowed:
                continue
        picked.append((rec_date, cat, rec))
    picked.sort(key=lambda t: (t[0].isoformat(), str(t[2].get("sk") or "")), reverse=True)
    return [{"date": d.isoformat(), "category": c, "record": r} for d, c, r in picked[: max(1, int(max_items))]]


_BLOCK_HEADER = (
    "CONVERSATION-DERIVED CONTEXT (platform memory — things Matthew shared in chat with his AI; " "self-reported words, NOT sensor data):"
)

_BLOCK_RULES = (
    "How to use this honestly (ADR-104):\n"
    '- These are things Matthew TOLD his AI in conversation — cite them as "you mentioned" / "you told me", '
    "never as measured data.\n"
    "- If a memory conflicts with current sensor/log data, the data wins — the discrepancy itself may be worth naming.\n"
    "- Never invent details beyond what's written here; the absence of a memory is not evidence of anything.\n"
    "- Lines marked (shared in confidence) may shape your read and tone, but do NOT restate their specifics in your section."
)


def format_platform_memory_block(selected: list[dict], max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Render selected memories (from select_conversation_memories) into the
    prompt block, hard-capped at max_chars. Returns "" when nothing survives."""
    if not selected:
        return ""
    budget = max(200, int(max_chars)) - len(_BLOCK_HEADER) - len(_BLOCK_RULES) - 2
    lines = []
    for entry in selected:
        rec = entry["record"]
        spec = MEMORY_CATEGORIES[entry["category"]]
        text = _record_text(rec)
        if not text:
            continue
        confidence = " (shared in confidence)" if effective_tier(rec, spec) == TIER_COACH_CONTEXT else ""
        line = f"- [{entry['date']} · {entry['category']}] {text}{confidence}"
        if budget - (len(line) + 1) < 0:
            break
        budget -= len(line) + 1
        lines.append(line)
    if not lines:
        return ""
    return _BLOCK_HEADER + "\n" + "\n".join(lines) + "\n" + _BLOCK_RULES


def _conversation_sk_prefixes() -> list[str]:
    """One sk prefix per conversation-sanctioned category, PLUS the legacy alias
    spellings that map to them (e.g. MEMORY#failure_pattern# for records that
    predate write-path normalization)."""
    prefixes = []
    for cat in conversation_categories():
        prefixes.append(f"{MEMORY_SK_PREFIX}{cat}#")
        for alias, target in CATEGORY_ALIASES.items():
            if target == cat:
                prefixes.append(f"{MEMORY_SK_PREFIX}{alias}#")
    return prefixes


def _query_conversation_records(table, per_category_limit: int = _PER_CATEGORY_QUERY_LIMIT) -> list[dict]:
    """Bounded per-category reads of JUST the conversation-sanctioned categories.

    PR #1581 review (MAJOR): the sk is MEMORY#<category>#<date>, so a single
    partition-wide descending query is CATEGORY-ALPHABETICAL, not newest-first —
    and DynamoDB applies Limit BEFORE the FilterExpression, so high-volume
    computed categories (intention_tracking is written daily, plus insight/
    hypothesis_monitoring/weekly_plate and their reset tombstones) would fill a
    fixed window and silently starve the conversation categories as the store
    grows. Querying each conversation category's own sk prefix makes computed-
    category growth irrelevant: a handful of small, bounded, truly newest-first
    queries. Results are deduped by (pk, sk) (alias prefixes can overlap a
    permissive test double)."""
    from boto3.dynamodb.conditions import Key

    user_id = os.environ.get("USER_ID", "matthew")
    pk = f"USER#{user_id}#SOURCE#{MEMORY_SOURCE}"
    try:
        from phase_filter import with_phase_filter  # ADR-058 — hide wiped/foreign-phase records
    except Exception:  # noqa: BLE001 — filter is an enhancement, never a dependency
        with_phase_filter = None
    records, seen = [], set()
    for prefix in _conversation_sk_prefixes():
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix),
            "ScanIndexForward": False,  # sk suffix is the date → newest-first WITHIN the category
            "Limit": per_category_limit,
        }
        if with_phase_filter is not None:
            try:
                kwargs = with_phase_filter(kwargs)
            except Exception:  # noqa: BLE001
                pass
        for rec in table.query(**kwargs).get("Items", []):
            key = (rec.get("pk"), rec.get("sk"))
            if key in seen:
                continue
            seen.add(key)
            records.append(rec)
    return records


def platform_memory_block(
    coach_id=None,
    table=None,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_chars: int = DEFAULT_MAX_CHARS,
    today: _date | None = None,
) -> str:
    """The consumption seam ai_calls injects (#1482): a bounded, provenance-honest
    block of conversation-derived platform memories relevant to one coach.

    Fail-soft by contract — returns "" on empty store, unknown coach, or ANY
    read failure; a context block must never break a generation."""
    try:
        if table is None:
            import boto3

            table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
                os.environ.get("TABLE_NAME", "life-platform")
            )
        records = _query_conversation_records(table)
        selected = select_conversation_memories(records, coach_id=coach_id, max_items=max_items, today=today)
        return format_platform_memory_block(selected, max_chars=max_chars)
    except Exception as e:  # noqa: BLE001 — a context block must never break a prompt
        logger.warning("[platform_memory] platform_memory_block failed: %s", e)
        return ""
