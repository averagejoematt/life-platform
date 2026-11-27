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

Token budget (ADR-063, the $215/mo guard): the block is hard-capped by
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
from datetime import date as _date

from common.pacific_time import pacific_now  # #2811: memory relevance windows age in Pacific days

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
# #2334 roster-copy waiver: the zero-dep import contract above is deliberate;
# equality is enforced by tests/test_platform_memory_block.py AND re-asserted by
# tests/test_coach_roster_set_guard_2334.py.
COACH_DOMAINS = frozenset({"sleep", "nutrition", "mind", "physical", "glucose", "labs", "explorer"})
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
    "training": {
        # #4077: `write_platform_memory` rejected this domain outright, so a standing
        # training constraint stated in chat (the RDL gate, a toe flag, a back flag) had
        # no durable home — it survived only as conversational context, gone the next
        # session. Distinct from `constraints_preferences` (that category is EVERY
        # standing constraint, cross-domain) so `plan_next_session` stage 1 can read
        # ONE narrow, training-scoped category without a coach filter on every record.
        "description": (
            "Standing training constraints stated in chat — a gate, a toe flag, a back flag, or similar — "
            "that plan_next_session stage 1 must plan around until Matthew says otherwise."
        ),
        "channels": (CHANNEL_CONVERSATION,),
        "retention_days": 730,
        "privacy_tier": TIER_COACH_CONTEXT,
        "coach_domains": frozenset({"physical"}),  # physical_coach absorbs training (persona_registry)
        "durable": True,
    },
    "personal_record": {
        # #6287 (owner rulings 2026-11-26): a reviewed personal record from conversation — a
        # recollection, a confirmed event, his own statement, or an interpretation he looked
        # at. Three rules make it different from life_context, and they are code, not prose:
        #   * QUEUE-ONLY: write_platform_memory refuses a direct write; the row is written
        #     only inside manage_pending_writes' approve call (pending_writes.approval_scope),
        #     which stamps owner_reviewed_at. "Permission to save privately is not permission
        #     to share with coaches" — so the default tier is PRIVATE, and coach_context is a
        #     per-item opt-in given at enqueue (OPT_IN_TIERS); public_ok is impossible.
        #   * PROVENANCE: evidence_kind + event_date/event_date_precision + source_ref are
        #     validated (validate_provenance); an interpretation is never injected as fact.
        #   * A record with an event_date is exempt from the relevance window below.
        "description": (
            "Reviewed personal record from conversation (owner statement, confirmed event, recollection, self-report, "
            "observed pattern, interpretation) with evidence_kind + event_date provenance. QUEUE-ONLY: written only by "
            "manage_pending_writes approve; private unless coach_context is chosen per item at enqueue."
        ),
        "channels": (CHANNEL_CONVERSATION,),
        "retention_days": 365,
        "privacy_tier": TIER_PRIVATE,
        "coach_domains": ALL_DOMAINS,
        "durable": True,
        "queue_only": True,
        "provenance_required": True,
        "opt_in_tiers": (TIER_COACH_CONTEXT,),
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
    # #6287 provenance — rendered as the line's label, never as its text
    "evidence_kind",
    "event_date",
    "event_date_precision",
    "source_ref",
    "owner_reviewed_at",
    "reviewed_via",
    # #6294 life-domain tags — read by the owner-only development profile, never rendered as text
    "life_domains",
    "life_direction",
}

# ── #6287: provenance for reviewed personal records ──────────────────────────
EVIDENCE_KINDS = (
    "owner_statement",
    "confirmed_event",
    "recollection",
    "self_report",
    "observed_pattern",
    "ai_interpretation",
    "competing_hypothesis",
    "confirmed_insight",
    "rejected_interpretation",
)
#: Kinds that may reach a coach prompt (at coach_context tier only), each with its label.
#: observed_pattern is deliberately absent: until the owner rules otherwise a pattern is an
#: observation about him, not something he said — it stays readable, never injected.
INJECTABLE_EVIDENCE_LABELS = {
    "owner_statement": "his statement",
    "confirmed_event": "confirmed event",
    "recollection": "recollection",
    "self_report": "self-report",
    "confirmed_insight": "confirmed insight",
}
#: Never injected as fact, at any tier. A rejected interpretation is KEPT (so it is not
#: re-proposed) and is never injected.
NON_INJECTABLE_EVIDENCE = frozenset({"ai_interpretation", "competing_hypothesis", "rejected_interpretation"})

DATE_PRECISIONS = ("day", "month", "season", "year", "unknown")
SEASONS = ("spring", "summer", "autumn", "winter")
_SEASON_ALIASES = {"fall": "autumn"}

#: Fields the approval path stamps — a caller can never supply them.
APPROVAL_STAMPED_FIELDS = ("owner_reviewed_at", "reviewed_via")

# ── #6294: the life domains a reviewed personal record may be tagged to ─────────
#: The closed vocabulary = the keys of the development profile's domain registry
#: (`health.development_profile.DOMAINS`; tests/test_development_profile_6294.py holds them equal).
#: Kept here as a literal so this module keeps its zero-dep import. A SEPARATE field from
#: `domains` (which names coach ids): `life_domains` says which part of his life the record
#: speaks to, and nothing reads it but the owner-only profile.
LIFE_DOMAINS = (
    "physical_capacity",
    "behavioural_consistency",
    "learning_and_experimentation",
    "self_understanding",
    "emotional_wellbeing",
    "social_connection",
    "meaning_and_fulfilment",
    "confidence_and_agency",
    "coping_and_flexibility",
)
#: His own reading of which way the record points, in the domain(s) it is tagged to. Optional.
LIFE_DIRECTIONS = ("better", "same", "harder", "unclear")
#: Only a record in his own words, or one he confirmed, may be tagged to a life domain: an
#: interpretation, a competing hypothesis, a rejected interpretation or an observed pattern is
#: never evidence about how he is doing (owner rulings 2026-11-26).
LIFE_DOMAIN_TAGGABLE_KINDS = frozenset({"owner_statement", "self_report", "confirmed_event", "recollection", "confirmed_insight"})


def _validate_life_tags(fields: dict, kind: str) -> tuple[str | None, dict]:
    """#6294: (error, normalized) for the optional ``life_domains`` / ``life_direction`` tags."""
    domains, direction = fields.get("life_domains"), fields.get("life_direction")
    if domains in (None, []) and direction is None:
        return None, {}
    if not isinstance(domains, list) or not domains:
        return "life_direction needs life_domains — a non-empty list of life domains", {}
    bad = [d for d in domains if d not in LIFE_DOMAINS]
    if bad:
        return f"unknown life domain(s) {bad} — valid: {list(LIFE_DOMAINS)}", {}
    if kind not in LIFE_DOMAIN_TAGGABLE_KINDS:
        return (
            f"evidence_kind '{kind}' cannot be tagged to a life domain — only his own words or what he confirmed "
            f"({sorted(LIFE_DOMAIN_TAGGABLE_KINDS)}) count as evidence about how he is doing",
            {},
        )
    out: dict = {"life_domains": sorted(set(domains), key=LIFE_DOMAINS.index)}
    if direction is not None:
        if direction not in LIFE_DIRECTIONS:
            return f"life_direction must be one of {list(LIFE_DIRECTIONS)}", {}
        out["life_direction"] = direction
    return None, out


def _infer_precision(event_date: str) -> str | None:
    s = event_date
    if len(s) == 4 and s.isdigit():
        return "year"
    if len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:].isdigit():
        return "month"
    if len(s) == 10:
        return "day"
    if s[:4].isdigit() and s[4:5] == "-":
        return "season"
    return None


def normalize_event_date(event_date, precision) -> tuple[str | None, str | None, str | None]:
    """(error, event_date, precision) for a personal record's event date.

    Accepted shapes, one per precision: day ``YYYY-MM-DD``, month ``YYYY-MM``,
    season ``YYYY-<spring|summer|autumn|winter>`` (``fall`` → ``autumn``), year ``YYYY``.
    ``unknown`` carries no date. A precision given with a date must match the date's shape;
    a date given without one has its precision inferred from the shape."""
    if precision is not None and precision not in DATE_PRECISIONS:
        return f"event_date_precision must be one of {list(DATE_PRECISIONS)}", None, None
    if event_date in (None, ""):
        if precision in (None, "unknown"):
            return None, None, ("unknown" if precision == "unknown" else None)
        return f"event_date_precision '{precision}' needs an event_date (or use 'unknown')", None, None
    if not isinstance(event_date, str):
        return "event_date must be a string", None, None
    s = event_date.strip().lower()
    if precision == "unknown":
        return "event_date_precision 'unknown' takes no event_date — drop one of them", None, None
    shape = _infer_precision(s)
    if shape is None:
        return f"event_date {event_date!r} is not YYYY, YYYY-MM, YYYY-<season> or YYYY-MM-DD", None, None
    if precision is not None and precision != shape:
        return f"event_date {event_date!r} has {shape} precision but event_date_precision says '{precision}'", None, None
    try:
        if shape == "day":
            s = _date.fromisoformat(s).isoformat()
        elif shape == "month":
            month = int(s[5:])
            if not 1 <= month <= 12:
                raise ValueError(month)
        elif shape == "season":
            season = _SEASON_ALIASES.get(s[5:], s[5:])
            if season not in SEASONS:
                raise ValueError(season)
            s = f"{s[:4]}-{season}"
        int(s[:4])
    except (TypeError, ValueError):
        return f"event_date {event_date!r} is not a valid {shape}", None, None
    return None, s, shape


def validate_provenance(fields: dict) -> tuple[str | None, dict]:
    """(error, normalized) for a personal record's provenance fields.

    ``evidence_kind`` is required; ``event_date``/``event_date_precision`` per
    normalize_event_date; ``source_ref`` an opaque non-empty string (never fetched).
    ``owner_reviewed_at``/``reviewed_via`` are stamped by the approval path and refused here."""
    for stamped in APPROVAL_STAMPED_FIELDS:
        if fields.get(stamped) not in (None, ""):
            return f"{stamped} is stamped by the approval path (manage_pending_writes approve) — never supplied by the caller", {}
    kind = fields.get("evidence_kind")
    if kind not in EVIDENCE_KINDS:
        return f"evidence_kind is required and must be one of {list(EVIDENCE_KINDS)}", {}
    err, event_date, precision = normalize_event_date(fields.get("event_date"), fields.get("event_date_precision"))
    if err:
        return err, {}
    err, tags = _validate_life_tags(fields, kind)
    if err:
        return err, {}
    out = {"evidence_kind": kind, **tags}
    if event_date is not None:
        out["event_date"] = event_date
    if precision is not None:
        out["event_date_precision"] = precision
    ref = fields.get("source_ref")
    if ref is not None:
        if not isinstance(ref, str) or not ref.strip() or len(ref) > 200:
            return "source_ref must be a non-empty opaque string (≤200 chars), e.g. a Notion page id", {}
        out["source_ref"] = ref.strip()
    return None, out


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
                # #6287: "queue_only" → write it with manage_pending_writes(enqueue), never directly
                "write_path": "queue_only" if spec.get("queue_only") else "direct",
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
    """The category default, tightened (never loosened) by a per-record override.

    #6287: the one exception is a category's ``opt_in_tiers`` — a per-item choice the owner
    made at enqueue (personal_record: ``coach_context``). It is the ONLY loosening there
    is, and ``public_ok`` is never in that set."""
    default = spec["privacy_tier"]
    override = record.get("privacy_tier")
    if override in _TIER_RANK and _TIER_RANK[override] > _TIER_RANK[default]:
        return override
    if isinstance(override, str) and override in spec.get("opt_in_tiers", ()) and override != TIER_PUBLIC_OK:
        return override
    return default


def is_queue_only(category: str | None) -> bool:
    """#6287: True when a direct write_platform_memory call must be refused for `category`."""
    return bool(category and MEMORY_CATEGORIES.get(category, {}).get("queue_only"))


def injection_label(record: dict, spec: dict) -> str | None:
    """#6287: the evidence label a provenance-carrying record is injected under, or None
    when it must not be injected at all.

    A record (any category) whose evidence_kind is an interpretation, a competing
    hypothesis or a rejected interpretation is NEVER injected. In a provenance_required
    category a record must also carry an injectable evidence_kind and an owner_reviewed_at
    stamp. Records with no provenance in an ordinary category return "" (inject, no label)."""
    kind = record.get("evidence_kind")
    if kind in NON_INJECTABLE_EVIDENCE:
        return None
    if spec.get("provenance_required"):
        if kind not in INJECTABLE_EVIDENCE_LABELS or not record.get("owner_reviewed_at"):
            return None
    if kind not in INJECTABLE_EVIDENCE_LABELS:
        return "" if kind is None else None
    label = INJECTABLE_EVIDENCE_LABELS[kind]
    event_date = record.get("event_date")
    if event_date:
        label += f", event {event_date}"
    elif record.get("event_date_precision") == "unknown":
        label += ", date unknown"
    return label


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
    # #2811 — `today` is only used to age each record against its own stored day (the
    # category relevance window), and those days are Pacific. A UTC "today" after
    # 17:00 PT aged every memory by an extra day and dropped the oldest ones a day early.
    today = today or pacific_now().date()
    domain = normalize_domain(coach_id) if coach_id else None
    picked = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("deleted_at"):
            # #4355: delete_platform_memory is a tombstone (the MCP role has no
            # dynamodb:DeleteItem on this partition) — a soft-deleted note must not
            # keep steering a coach's chat context after Matthew asked it removed.
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
        label = injection_label(rec, spec)
        if label is None:
            continue  # #6287: an interpretation is never injected as fact
        rec_date = _date_of(rec)
        if rec_date is None or rec_date > today:
            continue
        # #6287: a record that names when its event happened is about that event, not about
        # how recently it was said — it is exempt from the category's relevance window.
        if not rec.get("event_date") and (today - rec_date).days > spec["retention_days"]:
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
        label = injection_label(rec, spec)
        if label is None:
            continue  # defence in depth — select_conversation_memories already dropped it
        kind = f" · {label}" if label else ""
        line = f"- [{entry['date']} · {entry['category']}{kind}] {text}{confidence}"
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
        from experiment.phase_filter import with_phase_filter  # ADR-058 — hide wiped/foreign-phase records
    except Exception:  # noqa: BLE001 — filter is an enhancement, never a dependency
        with_phase_filter = None
    records, seen = [], set()
    for prefix in _conversation_sk_prefixes():
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix),
            # #4355: exclude soft-deleted notes at the query itself — deleted_at rows
            # must not consume one of this bounded per-category window's Limit slots.
            "FilterExpression": "attribute_not_exists(deleted_at)",
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
