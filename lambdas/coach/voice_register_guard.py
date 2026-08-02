"""
voice_register_guard.py — deterministic coach-voice register check (#1987).

Two write paths hand a coach's own LLM-summarized text back into the platform
verbatim: the `observatory_summary` extraction (item 8 of the extraction prompt
in `coach_state_updater.py`, served preferentially at
`web/site_api_coach.py::handle_coach_analysis`) and the `position_summary`
parser in `intelligence/intelligence_common.py::extract_thread_from_narrative`.
Both prompts already ask the model to "preserve the coach's distinctive voice"
in first person, but a prompt asking nicely is not a guarantee (the
"prompt rules can't guarantee structure" class, ADR-105) — live output has
drifted into third-person meta-narration ("The coach pivots from data to
ownership...", "the glucose coach is in calibration mode...") and has leaked
raw markdown emphasis asterisks ("do your targets feel like *your* future")
straight through to the rendered card.

This module is the deterministic (zero-AI-cost) backstop, mirroring the
sibling anti-pattern check (item 7 of the same extraction prompt): a regex
reject for third-person coach register, and a markdown-emphasis strip so a
literal `*word*` never displays raw. Both callers apply `sanitize_summary()`
and, on rejection, fall back to their own existing content path (the OUTPUT#
record's `content` field or the raw narrative) rather than inventing a new
control-flow pattern beside the one that's already there.

Per-coach domain words for the "the {domain} coach" pattern are DERIVED from
`persona_registry.OPERATIONAL_SHORT_IDS` — never hand-listed — so a persona
roster change (new coach, renamed domain) is covered automatically with no
edit here.
"""

import re

from coach import persona_registry

# ══════════════════════════════════════════════════════════════════════════════
# THIRD-PERSON REGISTER CHECK
# ══════════════════════════════════════════════════════════════════════════════


def _domain_words():
    """Per-coach short ids ('sleep', 'glucose', ...) — derived, never hand-listed."""
    return list(persona_registry.OPERATIONAL_SHORT_IDS)


def _third_person_pattern():
    """Matches 'the coach' (generic) or 'the {domain} coach' (per-persona), case-insensitive.

    Rebuilt per call (not module-level) so a warm container that refreshes the
    persona registry mid-life picks up a roster change without a redeploy.
    """
    domains = _domain_words()
    domain_alt = "|".join(re.escape(d) for d in domains)
    pattern = rf"\bthe (?:(?:{domain_alt}) )?coach\b" if domains else r"\bthe coach\b"
    return re.compile(pattern, re.IGNORECASE)


def is_third_person(text):
    """True if `text` refers to the coach in third person ('the coach' / 'the {domain} coach')."""
    if not text:
        return False
    return bool(_third_person_pattern().search(text))


# ══════════════════════════════════════════════════════════════════════════════
# MARKDOWN EMPHASIS STRIP
# ══════════════════════════════════════════════════════════════════════════════

# Bold first (**word**) so a leftover single-asterisk pass doesn't split it in half.
_MD_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
# Single-asterisk emphasis (*word* / *a few words*). Requires non-whitespace
# immediately inside both delimiters so stray/unpaired asterisks and inline
# multiplication ("3 * 4") are left alone.
_MD_EMPHASIS = re.compile(r"\*([^\s*][^*\n]*[^\s*]|[^\s*])\*")


def strip_markdown_emphasis(text):
    """Convert markdown emphasis to plain text ('*your*' -> 'your'). No-op if none present."""
    if not text:
        return text
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_EMPHASIS.sub(r"\1", text)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED CHECK
# ══════════════════════════════════════════════════════════════════════════════


def sanitize_summary(text):
    """Markdown-strip then third-person-check a coach summary field.

    Returns (cleaned_text_or_None, rejected: bool):
      - Markdown emphasis is always stripped from the returned text.
      - If the (post-strip) text is still in third-person coach register, the
        text is REJECTED: returns (None, True) so the caller falls back to its
        own existing content path instead of publishing meta-narration in the
        coach's voice slot.
      - Falsy input passes through unchanged, not rejected.
    """
    if not text:
        return text, False
    cleaned = strip_markdown_emphasis(text)
    if is_third_person(cleaned):
        return None, True
    return cleaned, False
