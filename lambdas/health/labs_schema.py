"""labs_schema.py — the ONE accessor for the nested labs draw schema (#3283).

SCHEMA.md is authoritative: a labs draw record (sk ``DATE#YYYY-MM-DD``) stores
its values ONLY as a nested ``biomarkers`` map of marker_key → marker object
(``{value, value_numeric, unit, ref_text, flag, ...}``) — never as top-level
scalars. Two consumers each hand-rolled this read and each was written against
a top-level schema that has never existed:

- #1993 — ``lambdas/intelligence/ai_expert_analyzer_lambda.py``'s labs
  extractor hunted top-level ``*_flag`` keys (fixed 2026-08-02 via
  ``intelligence/labs_facts.py``);
- #3283 — ``lambdas/health/labs_coaching.py`` read top-level scalar fields and
  returned "" on every run since it was written.

The shared-accessor ruling (#3283 acceptance box 5): the schema knowledge —
"where do a draw's marker values live, and what is a draw record at all" —
lives here, once, and both consumers import it. What is NOT shared is the
per-consumer shaping (labs_facts wants display strings + declared out-of-range
counts; labs_coaching wants one float per marker, newest draw wins) — those
stay with their consumers, because forcing them through one function would
couple two unrelated output contracts to protect against a bug class that
lives entirely in the map read below.

Bundled into every function's deploy package (#781); ``intelligence`` already
imports from ``health`` (see ``health.pillar_absence`` in the expert analyzer).
"""

from typing import Any, Dict, Optional


def is_draw_record(item: Any) -> bool:
    """True only for a draw record (sk ``DATE#...``).

    The labs partition also holds ``PROVIDER#<provider>#<period>`` metadata
    items, which sort BEFORE the ``DATE#`` items in a descending query and
    carry top-level numerics (``out_of_range_count`` etc.) but no per-marker
    map — they must never feed marker extraction.
    """
    return isinstance(item, dict) and str(item.get("sk", "")).startswith("DATE#")


def biomarker_map(item: Any) -> Dict[str, Dict[str, Any]]:
    """The nested ``biomarkers`` map off a draw record.

    Returns only dict-shaped entries (the schema's marker objects); ``{}`` when
    the map is absent or mis-shaped. This is the read both #1993 and #3283 got
    wrong by not making — do not read marker values off the item's top level.
    """
    raw = item.get("biomarkers") if isinstance(item, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {key: entry for key, entry in raw.items() if isinstance(entry, dict)}


def marker_numeric(entry: Any) -> Optional[float]:
    """A marker object's numeric reading, or None for qualitative results.

    ``value_numeric`` is preferred (SCHEMA.md: the numeric-for-trending field,
    null for qualitative values); the raw ``value`` is the fallback for records
    that predate ``value_numeric``. Non-numeric values yield None, never a
    crash — qualitative markers are simply not coachable by threshold rules.
    """
    if not isinstance(entry, dict):
        return None
    for field in ("value_numeric", "value"):
        raw = entry.get(field)
        if raw is None:
            continue
        try:
            return float(raw)
        except (ValueError, TypeError):
            continue
    return None
