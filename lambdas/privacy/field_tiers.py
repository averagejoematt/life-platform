"""lambdas/privacy/field_tiers.py — per-field privacy tier, as structure (#2803).

WHY THIS EXISTS
---------------
A field's privacy tier was **prose**. `docs/SCHEMA.md` ruled `vascular_age`,
`metabolic_age` and `afib_result` **Tier-2 owner-only** — "never on a public surface and
never quoted into an AI narrative context" — and that ruling lived in exactly three
un-linked places: the SCHEMA paragraph, two comments in `withings_lambda.py`, and a
`TIER2_STRIP_FIELDS` literal inside `mcp/tools_data.py`. Nothing failed the build when a
consumer started reading one.

That is not hypothetical. #2782 swept the consumers of the new BodyScan fields and
concluded "all current consumers are field-selective"; #2809 measured it and the claim was
FALSE — `mcp/tools_data.py`'s generic row dumpers had been handing whole withings rows,
Tier-2 trio included, into Claude conversation context. The sweep enumerated
site_api_body/rollups/ai_context and `mcp/tools_health.py` and missed `tools_data.py`
entirely. ADR-154 concedes nothing leaked "only because prior sessions happened to build
them that way", and institutes a manual checklist.

A checklist is the thing that already failed. So the tier becomes a structural fact here,
and `tests/privacy_tier_wiring.py` derives the consumer set from the tree rather than from
a memory of who reads what — the "guard the SET, not the instance" rule, applied to the
class whose blast radius is public exposure of medical data.

WHAT THIS IS NOT
----------------
Not a scrubber and not a runtime gate. It is the *declaration*; enforcement lives in the
wiring test (build-time) and in each consumer's own field discipline (`_strip_tier2` in
`mcp/tools_data.py`, which now derives its strip set from here rather than restating it).
One copy of the ruling, many readers.
"""

from __future__ import annotations

# ── Tiers ─────────────────────────────────────────────────────────────────────
# 0  public          — may appear on averagejoematt.com and in AI narrative context
# 1  internal        — not published, but safe inside owner-facing tooling and AI context
# 2  owner-only      — NEVER a public surface, NEVER quoted into an AI narrative context.
#                      The owner's own MCP surface may return it *field-selectively*; a
#                      "dump the row" path must strip it (the #2809 distinction).
TIER_PUBLIC = 0
TIER_INTERNAL = 1
TIER_OWNER_ONLY = 2

VALID_TIERS = frozenset({TIER_PUBLIC, TIER_INTERNAL, TIER_OWNER_ONLY})

# ── The registry ──────────────────────────────────────────────────────────────
# Keyed by the DDB partition `source`, then field name. ONLY non-default tiers are
# listed: an unlisted field is TIER_PUBLIC by omission, which is the honest default for
# this platform (it publishes almost everything on purpose). Adding a Tier-2 field here
# is what arms the build-time gate for it — see tests/privacy_tier_wiring.py.
#
# Provenance for the withings trio: docs/SCHEMA.md "Privacy tiers (PhenoAge posture)",
# ruled in #2782, corrected in #2809. The PhenoAge posture (ADR: age NEVER returned) is
# the same reasoning one layer up — an age-class derived number is identifying in a way
# the underlying measurement is not.
FIELD_TIERS: dict[str, dict[str, int]] = {
    "withings": {
        "vascular_age": TIER_OWNER_ONLY,  # age-class, #2782
        "metabolic_age": TIER_OWNER_ONLY,  # age-class, same posture
        "afib_result": TIER_OWNER_ONLY,  # event-class medical result (ECG screening)
    },
}


def tier_of(source: str, field: str) -> int:
    """The declared tier for one field, defaulting to TIER_PUBLIC when unlisted."""
    return FIELD_TIERS.get(source, {}).get(field, TIER_PUBLIC)


def fields_at_tier(tier: int, source: str | None = None) -> frozenset[str]:
    """Every field declared at `tier`, optionally narrowed to one source.

    Returns a flat set of field NAMES — callers that need the source split should read
    `FIELD_TIERS` directly. Used by the wiring test to build its scan vocabulary and by
    `mcp/tools_data.py` to build its strip set, so neither restates the trio.
    """
    sources = [source] if source is not None else list(FIELD_TIERS)
    out: set[str] = set()
    for s in sources:
        out.update(f for f, t in FIELD_TIERS.get(s, {}).items() if t == tier)
    return frozenset(out)


def strip_map(tier: int = TIER_OWNER_ONLY) -> dict[str, frozenset[str]]:
    """`{source: {fields at or above `tier`}}` — the shape a row-stripper wants.

    `mcp/tools_data.py`'s `TIER2_STRIP_FIELDS` is this, so the strip set cannot drift
    from the ruling the way it did before #2803: there was a literal there and a
    paragraph in SCHEMA.md, and nothing compared them.
    """
    return {
        source: frozenset(f for f, t in fields.items() if t >= tier)
        for source, fields in FIELD_TIERS.items()
        if any(t >= tier for t in fields.values())
    }
