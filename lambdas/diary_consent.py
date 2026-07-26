"""
diary_consent.py — the V3-consent gate for surfacing a private diary entry publicly.

#1574 (epic #1564). When a coach reacts to a Video Diary / Solo Recording entry on
the PUBLIC lab-notes surface, the reader must NEVER see unmarked private journal
content. This module is the single chokepoint that decides what — if anything — of a
private entry may cross into a public-facing generation brief.

The #1483 ADR (the full per-LINE quote/allude consent tier) is still deferred; until
it ships a per-line schema this module implements its three-tier contract at the
ENTRY level, and does so FAIL-CLOSED:

  quote   — the owner explicitly cleared one specific verbatim line for public
            quoting (entry field ``public_quote``), AND that line grounds as a
            literal substring of the entry body (the ADR-104 invariant). Only then
            may the coach quote it. If the cleared line does not ground, we DROP the
            quote and fall back to allude exposure — never a paraphrased "quote".

  allude  — the entry is cleared for a public *paraphrase* only. The coarse public
            theme (the same 8-way ``dominant_theme`` laundering the rest of the
            platform uses) may inform the reaction, but NO verbatim journal text is
            ever exposed.

  private — the default, and the value for ANY unmarked / malformed / unknown entry.
            The entry never crosses into a public reaction at all:
            ``public_context()`` returns ``None`` → no reaction is generated → nothing
            renders on the site (AC3).

The consent tier is read from the entry's ``public_reaction_consent`` field
(owner-set — e.g. a Notion property on the diary page). Anything not exactly
``"quote"`` or ``"allude"`` resolves to ``private``. The raw entry body
(``raw_text``), the mood text, and ``enriched_notable_quote`` are NEVER placed in the
public context unless (quote tier) the specific ``public_quote`` line was cleared AND
grounds as a literal substring.

Bundled shared module (#781) — no AWS, no I/O, pure functions, so the leak-proof
invariant is unit-testable without any live call.

#1483 (ADR-142 tier 2) also lives here: the conversation-allude channel. Coach
check-in conversations (CHECKIN# answers and the conversation LEARNING# trail
they produce — ADR-141, coach_calibration.py) are Matthew-private verbatim, but
public coach narrative may allude to them at exactly three strengths: that a
conversation OCCURRED, its COARSE theme (the same 8-way laundered vocabulary as
``public_theme``), and the resulting read/confidence DELTA. See the
``conversation_reference`` section below — the projection is BUILT from an
allowlist, never filtered from the source record, so verbatim text cannot ride
along: leakage is structurally impossible, not just discouraged.
"""

import re as _re

TIER_QUOTE = "quote"
TIER_ALLUDE = "allude"
TIER_PRIVATE = "private"
CONSENT_TIERS = (TIER_QUOTE, TIER_ALLUDE, TIER_PRIVATE)

# The owner-set marker on a journal entry that opts it in to a public coach reaction.
CONSENT_FIELD = "public_reaction_consent"
# The owner-cleared verbatim line (quote tier only).
QUOTE_FIELD = "public_quote"

# Theme-tag → public dominant_theme category. Kept structurally identical to the
# canonical reducer in intelligence/journal_analyzer_lambda.categorize_themes — it is
# copied here (not imported) deliberately: this is the privacy hot path, and it must
# stay hermetic (no boto3-bearing intelligence-lambda import) so the leak test can run
# with zero dependencies. If _THEME_CATEGORIES changes there, mirror it here.
_THEME_CATEGORIES = [
    ("anxiety_stress", ("stress", "anxiet", "worry", "overwhelm", "fear", "pressure", "uncertain")),
    ("health_body", ("health", "fitness", "sleep", "food", "weight", "body", "training", "workout", "diet", "energy")),
    ("relationships", ("family", "friend", "partner", "relationship", "social", "love", "kids", "marriage")),
    ("work_ambition", ("work", "career", "project", "productiv", "leader", "achieve", "business", "job")),
    ("gratitude", ("gratitude", "grateful", "thankful", "appreciat")),
    ("personal_growth", ("growth", "habit", "identity", "progress", "goal", "improve", "discipline", "learning")),
    ("reflection", ("reflect", "philosoph", "existential", "meaning", "past", "memory")),
]


def _norm(s):
    return " ".join(str(s or "").split()).lower()


def public_theme(entry):
    """The coarse public 8-way dominant_theme for an entry — the ONLY theme signal
    that may reach a public generation. Prefers a pre-computed ``dominant_theme``
    (already the public category), else launders ``enriched_themes`` through the same
    keyword map as the canonical reducer. Never returns a raw private theme tag."""
    pre = _norm(entry.get("dominant_theme"))
    public_cats = {c for c, _ in _THEME_CATEGORIES} | {"other"}
    if pre in public_cats:
        return pre
    for tag in entry.get("enriched_themes") or []:
        t = _norm(tag)
        for category, keywords in _THEME_CATEGORIES:
            if any(k in t for k in keywords):
                return category
    return "other"


def resolve_consent(entry):
    """The entry's public-reaction consent tier, FAIL-CLOSED.

    Returns one of ``quote`` / ``allude`` / ``private``. Anything not explicitly a
    recognised opt-in value (absent field, typo, ``None``, ``"public_ok"``, an int,
    …) resolves to ``private`` — the safe default. Consent is never inferred from
    content; it must be an explicit owner marker.
    """
    tier = str(entry.get(CONSENT_FIELD) or "").strip().lower()
    if tier == TIER_QUOTE:
        return TIER_QUOTE
    if tier == TIER_ALLUDE:
        return TIER_ALLUDE
    return TIER_PRIVATE


def _grounded_quote(entry):
    """The owner-cleared verbatim quote IFF it grounds as a literal substring of the
    entry body (ADR-104), else None. Mirrors journal_enrichment_lambda._ground_causal_hints
    normalisation (collapse whitespace, casefold) so a quote can't be licensed by a
    formatting difference."""
    q = str(entry.get(QUOTE_FIELD) or "").strip()
    if not q:
        return None
    body = _norm(entry.get("raw_text"))
    if _norm(q) and _norm(q) in body:
        return q
    return None


def public_context(entry):
    """The ONLY fields safe to hand to a public-facing coach-reaction generator, or
    ``None`` when the entry is private (⇒ no reaction, nothing renders).

    The returned dict deliberately contains NO raw journal text: only the laundered
    public theme, the capture channel (provenance), the date, and — for a grounded
    quote-tier entry only — the single owner-cleared verbatim line. This is the
    leak-proof boundary: an unmarked entry can produce no public context at all, and
    an allude-tier entry can produce no verbatim text at all.
    """
    consent = resolve_consent(entry)
    if consent == TIER_PRIVATE:
        return None

    quote = _grounded_quote(entry) if consent == TIER_QUOTE else None
    # "tier" reports the ACTUAL exposure: a quote-tier entry whose cleared line
    # doesn't ground is exposed only at allude strength (theme, no verbatim).
    exposed_tier = TIER_QUOTE if quote else TIER_ALLUDE

    ctx = {
        "tier": exposed_tier,
        "theme": public_theme(entry),
        "channel": str(entry.get("channel") or "video_diary"),
        "date": entry.get("date") or entry.get("entry_date"),
    }
    if quote:
        ctx["quote"] = quote
    return ctx


# ── #1483 (ADR-142 tier 2) — conversation references: coaches ALLUDE to
#    check-in conversations without quoting them ─────────────────────────────
#
# Source records: the channel=conversation LEARNING# rows written by
# lambdas/coach_calibration.py (ADR-141). Their `answer_quote`, `takeaway`, and
# `question` fields quote or reconstruct Matthew's verbatim check-in answers —
# Matthew-private, never public. What IS public (this tier):
#   (a) that a conversation occurred            → `occurred` / `date`
#   (b) its theme at COARSE granularity         → `theme` — laundered through
#       the SAME 8-way public vocabulary as every other allude surface
#   (c) the resulting read/confidence change    → `direction` + bounded `weight`
#       (the ADR-141 delta, already public-adjacent provenance)
# NOTHING else. `conversation_reference` BUILDS its output dict field-by-field
# from this allowlist — it never copies-and-filters the source record — so the
# private fields cannot ride along even if the schema grows.

CONVERSATION_KIND = "conversation_reference"
CONVERSATION_SANCTIONED_FIELDS = ("kind", "occurred", "date", "coach_id", "theme", "direction", "weight")
_CONVERSATION_DIRECTIONS = ("up", "down", "hold")

_PUBLIC_THEME_SET = frozenset(c for c, _ in _THEME_CATEGORIES) | {"other"}

# Evaluator-vocabulary subdomains (coach_calibration.normalize_subdomain slugs
# like 'protein_intake', 'evening_discipline') that the journal keyword map
# alone can't place. INPUT-side widening only — the OUTPUT vocabulary stays
# exactly the 8 public categories + "other"; an unmatched slug is "other",
# never a raw private tag.
_CONVERSATION_THEME_EXTRA = (
    ("health_body", ("protein", "nutrition", "recovery", "hrv", "glucose", "cgm", "hydration", "cardio", "strength", "readiness", "steps")),
    ("anxiety_stress", ("mood", "emotion", "burnout")),
    ("personal_growth", ("consistency", "adherence", "motivation", "streak", "routine", "evening", "morning")),
)

_ISO_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COACH_SLUG_RE = _re.compile(r"[^a-z0-9_]+")


def conversation_theme(subdomain):
    """The coarse public theme for a check-in subdomain — always one of the
    8 allowlisted categories or "other". Same laundering as ``public_theme``;
    a slug the map doesn't recognise degrades to "other", never leaks."""
    t = _norm(str(subdomain or "").replace("_", " "))
    if not t:
        return "other"
    for category, keywords in _THEME_CATEGORIES:
        if any(k in t for k in keywords):
            return category
    for category, keywords in _CONVERSATION_THEME_EXTRA:
        if any(k in t for k in keywords):
            return category
    return "other"


def conversation_reference(item):
    """The ONLY public projection of a conversation record, or ``None``.

    Accepts either a raw channel=conversation LEARNING# row (ADR-141) or an
    already-sanctioned reference (idempotent re-projection — consumers can
    defensively re-launder whatever they are handed). FAIL-CLOSED: anything
    else — a data-channel learning, a missing/malformed date, a bare CHECKIN#
    record (no ``channel``) — returns ``None`` and nothing renders.

    The returned dict is constructed key-by-key from
    ``CONVERSATION_SANCTIONED_FIELDS``; no source field is ever copied through
    wholesale, so ``answer_quote``/``takeaway``/``question`` are structurally
    unreachable from any public payload built on this."""
    item = item or {}
    is_ref = item.get("kind") == CONVERSATION_KIND
    if not is_ref and str(item.get("channel") or "").strip().lower() != "conversation":
        return None

    date = str(item.get("date") or "").strip()
    if not _ISO_DATE_RE.match(date):
        return None

    theme = item.get("theme") if is_ref else None
    if theme not in _PUBLIC_THEME_SET:
        theme = conversation_theme(item.get("subdomain")) if not is_ref else "other"

    d = str((item.get("direction") if is_ref else item.get("confidence_direction")) or "").strip().lower()
    if d not in _CONVERSATION_DIRECTIONS:
        d = "hold"

    try:
        w = float((item.get("weight") if is_ref else item.get("confidence_weight")) or 0)
    except (TypeError, ValueError):
        w = 0.0
    w = max(0.0, min(1.0, w))

    coach = _COACH_SLUG_RE.sub("", str(item.get("coach_id") or "").strip().lower())

    ref = {
        "kind": CONVERSATION_KIND,
        "occurred": True,
        "date": date,
        "theme": theme,
        "direction": d,
        "weight": round(w, 2),
    }
    if coach:
        ref["coach_id"] = coach
    return ref


# Reader/narrative copy for the laundered theme — deliberately vague, matching
# the coarse granularity of the tier ("other" renders as no theme at all).
CONVERSATION_THEME_COPY = {
    "anxiety_stress": "stress and worry",
    "health_body": "the body — training, sleep, food",
    "relationships": "relationships",
    "work_ambition": "work and ambition",
    "gratitude": "gratitude",
    "personal_growth": "habits and growth",
    "reflection": "reflection",
    "other": "",
}

_CONVERSATION_DIRECTION_COPY = {
    "up": "came away more confident in their read",
    "down": "walked their read back a step",
    "hold": "held their read where it was",
}

CONVERSATION_BLOCK_HEADER = "=== PRIVATE CONVERSATIONS (allude only — ADR-142 theme-referenceable tier) ==="


def conversation_prompt_block(items):
    """The ONLY form in which check-in conversations may enter a PUBLIC
    narrative-generation prompt (#1483). Every item is re-projected through
    ``conversation_reference`` — hand it raw LEARNING# rows or sanctioned refs,
    the rendered block is identical — so the block carries the sanctioned
    fields (date, coarse theme, read delta) and NOTHING else. The verbatim
    answers are deliberately absent from the prompt: a public generation
    cannot quote or reconstruct words it was never given (consistent with the
    ADR-104 grounding gates, which check outputs against sanctioned inputs).

    Empty/None/unsanctionable input → "" — the surface stays silent, it never
    scaffolds an empty section."""
    refs = [r for r in (conversation_reference(i) for i in items or []) if r]
    if not refs:
        return ""
    lines = [
        CONVERSATION_BLOCK_HEADER,
        "These coach check-in conversations happened during this window. You were not",
        "in the room: the words exchanged are private and are deliberately NOT in this",
        "prompt. You may reference that a conversation occurred, its coarse theme, and",
        "how it moved the coach's read — exactly what is listed below, nothing more.",
        "NEVER quote, paraphrase-as-quote, reconstruct, or invent dialogue from these",
        "conversations — write around the boundary, not through it.",
    ]
    for r in sorted(refs, key=lambda x: (x["date"], x.get("coach_id", ""))):
        coach = str(r.get("coach_id") or "").replace("_coach", "").replace("_", " ").strip()
        who = f"his {coach} coach" if coach else "one of his coaches"
        theme_copy = CONVERSATION_THEME_COPY.get(r["theme"], "")
        about = f" about {theme_copy}" if theme_copy else ""
        lines.append(f"- {r['date']}: Matthew and {who} talked{about}; the coach {_CONVERSATION_DIRECTION_COPY[r['direction']]}.")
    return "\n".join(lines)
