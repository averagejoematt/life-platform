"""stance_lint.py — the deterministic lint a coach STANCE must pass before it is kept.

Two regex rules the stance writer (coach_history_summarizer) has always applied, moved
here by #4217 when that module reached its size ceiling — same patterns, same names
(the summarizer imports them under its historical `_`-prefixed aliases):

  * ``contains_raw_vitals`` / ``vital_hits`` — a stance cites NO raw physiological
    number (HRV ms, RHR bpm, weights, percentages): the read describes patterns and
    positions, never invents a value the platform cannot trace (ADR-104).
  * ``claims_change`` — language asserting the read has EVOLVED is only allowed when a
    real change signal exists (a logged correction or a stage shift vs the prior stance).
"""

from __future__ import annotations

import re

RAW_VITAL_RE = re.compile(
    r"\b\d{2,3}\s?(?:bpm|ms|mg/?dl|lbs?|kg|kcal|cal)\b"
    r"|\b(?:rhr|hrv|recovery|resting heart rate|resting hr|deep|rem)\b[^.\n]{0,14}?\b\d"
    r"|\b\d{1,3}(?:\.\d+)?\s?%",
    re.IGNORECASE,
)

# Language that asserts the read has evolved — only allowed when a real signal of
# change exists (a logged correction or a stage shift vs the prior stance).
CHANGE_RE = re.compile(
    r"\b(?:chang|shift|revis|reconsider|no longer|used to|previously|earlier I|"
    r"moved (?:on |from )|updated my|come around|changed my mind|where I once)",
    re.IGNORECASE,
)


def contains_raw_vitals(text):
    """True if the text cites a raw physiological number the stance must not invent."""
    return bool(RAW_VITAL_RE.search(text or ""))


def vital_hits(stance):
    """Count raw-vital citations across the prose fields of a stance dict."""
    if not isinstance(stance, dict):
        return 0
    prose = " ".join(
        [
            str(stance.get("headline_read", "")),
            str(stance.get("how_my_read_changed", "")),
            str(stance.get("confidence_note", "")),
            " ".join(str(x) for x in stance.get("focused_on_now", []) or []),
            " ".join(str(x) for x in stance.get("set_aside_for_now", []) or []),
        ]
    )
    return len(RAW_VITAL_RE.findall(prose))


def claims_change(text):
    """True if the prose asserts the read has evolved (needs a real change signal)."""
    return bool(CHANGE_RE.search(text or ""))
