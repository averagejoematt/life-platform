"""
tests/test_diary_consent.py — the V3-consent leak boundary for diary reactions (#1574).

The load-bearing assertion (AC1): UNMARKED private journal content can NEVER cross into
the public context handed to a coach-reaction generator. The rest pins the three-tier
(#1483) contract: private ⇒ nothing, allude ⇒ theme-only (no verbatim), quote ⇒ only a
grounded, owner-cleared line.
"""

import os
import sys

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
sys.path.insert(0, _LAMBDAS)

import diary_consent as dc  # noqa: E402

# A deliberately sensitive raw entry — every distinctive token here is a canary: if any
# of them ever appears in a public context, the leak boundary is broken.
_SECRET_BODY = (
    "Relapsed again last night after the fight with Dana. I smoked and then watched porn "
    "until 3am and felt disgusting. The specific thing I can't tell anyone is the debt."
)
_CANARIES = ["Dana", "smoked", "porn", "disgusting", "debt", "relapsed", "3am"]


def _flatten(obj):
    """All string content of a returned context, concatenated — so a canary can't hide
    in a nested value."""
    if obj is None:
        return ""
    parts = []
    for v in obj.values():
        parts.append(str(v))
    return " ".join(parts).lower()


def _entry(**over):
    base = {
        "raw_text": _SECRET_BODY,
        "enriched_themes": ["relapse", "shame", "relationship_conflict"],
        "enriched_notable_quote": "I felt disgusting until 3am",  # NOT auto-public
        "channel": "video_diary",
        "date": "2026-07-25",
    }
    base.update(over)
    return base


# ── AC1: the leak boundary ───────────────────────────────────────────────────────


def test_unmarked_entry_yields_no_public_context():
    """No consent marker ⇒ private ⇒ None. The single most important assertion: an
    entry that was never opted in produces NOTHING to hand a public generator."""
    assert dc.resolve_consent(_entry()) == dc.TIER_PRIVATE
    assert dc.public_context(_entry()) is None


def test_unmarked_entry_never_leaks_a_single_raw_token():
    ctx = dc.public_context(_entry())
    assert ctx is None  # and therefore, trivially, nothing leaks
    # Also prove it for the strongest opt-in short of consent: an entry marked with an
    # UNRECOGNISED value must still fail closed to private.
    for bad in ["public_ok", "yes", "true", "1", "PUBLIC", "share", None, 1]:
        assert dc.resolve_consent(_entry(public_reaction_consent=bad)) == dc.TIER_PRIVATE, bad
        assert dc.public_context(_entry(public_reaction_consent=bad)) is None, bad


def test_allude_tier_exposes_theme_but_no_verbatim_journal_text():
    ctx = dc.public_context(_entry(public_reaction_consent="allude"))
    assert ctx is not None
    assert ctx["tier"] == dc.TIER_ALLUDE
    assert "quote" not in ctx  # allude NEVER carries verbatim text
    flat = _flatten(ctx)
    for canary in _CANARIES:
        assert canary.lower() not in flat, f"allude context leaked raw token: {canary!r}"
    # the notable_quote is NOT public just because it exists
    assert "disgusting" not in flat
    # what it DOES carry is the laundered public theme
    assert ctx["theme"] in {c for c, _ in dc._THEME_CATEGORIES} | {"other"}


def test_quote_tier_only_exposes_the_owner_cleared_grounded_line():
    cleared = "Today I chose to show up anyway."
    entry = _entry(
        raw_text=_SECRET_BODY + " " + cleared,
        public_reaction_consent="quote",
        public_quote=cleared,
    )
    ctx = dc.public_context(entry)
    assert ctx is not None
    assert ctx["tier"] == dc.TIER_QUOTE
    assert ctx["quote"] == cleared
    flat = _flatten(ctx)
    # the cleared line is the ONLY verbatim text; the secret body still never appears
    for canary in _CANARIES:
        assert canary.lower() not in flat, f"quote context leaked raw token: {canary!r}"


def test_quote_that_does_not_ground_is_dropped_and_downgraded_to_allude():
    """An owner may mark quote tier but paste a line that isn't a literal substring of
    the entry (a typo, a paraphrase). ADR-104: it MUST NOT be quoted — we downgrade to
    allude exposure rather than serve an ungrounded 'quote'."""
    entry = _entry(
        public_reaction_consent="quote",
        public_quote="A line that was never actually in the entry body at all.",
    )
    ctx = dc.public_context(entry)
    assert ctx is not None
    assert "quote" not in ctx
    assert ctx["tier"] == dc.TIER_ALLUDE  # reported exposure reflects reality


def test_public_theme_launders_raw_tags_to_the_public_category():
    # a raw private-sounding tag set reduces to a coarse public bucket, never echoed raw
    theme = dc.public_theme(_entry(enriched_themes=["family", "marriage"]))
    assert theme == "relationships"
    assert dc.public_theme(_entry(enriched_themes=["totally_unmapped_tag"])) == "other"


def test_grounded_quote_ignores_whitespace_and_case_but_not_content():
    entry = _entry(raw_text="Line one.\n\n   I  showed   up.  Line three.")
    assert dc._grounded_quote({**entry, "public_quote": "i showed up"}) == "i showed up"
    assert dc._grounded_quote({**entry, "public_quote": "I did not show up"}) is None
