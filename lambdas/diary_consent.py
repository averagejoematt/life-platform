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
"""

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
