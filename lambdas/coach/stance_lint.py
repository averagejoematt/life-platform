"""stance_lint.py — the deterministic lint a coach STANCE must pass before it is kept.

Since #4649 it also carries the writer's side of the plain-words rule
(``coach.plain_words``): ``self_correction`` builds the one strict retry instruction for
a leaked number and/or a watch item a general reader could not read, ``retry_is_better``
decides whether that retry is kept, and ``keep_plain`` drops whatever still fails before
the record is stored — a watch item that is not plain is never written, so never served.

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

from coach import plain_words

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


VITALS_CORRECTION = (
    "\n\nSTRICT CORRECTION: your previous attempt cited raw numeric values (HRV/RHR/"
    "weights/percentages). Rewrite with ZERO numbers — describe patterns and positions only."
)


def _focus(stance):
    return stance.get("focused_on_now") if isinstance(stance, dict) else None


def _aside(stance):
    return stance.get("set_aside_for_now") if isinstance(stance, dict) else None


def _watch(stance):
    """Both printed lists, one after the other: 'watching now' and 'set aside' (#4714)."""
    return [*(_focus(stance) or []), *(_aside(stance) or [])]


def self_correction(stance):
    """The strict instruction for the ONE self-correcting retry, or "" when the draft needs none:
    a leaked raw number, a watch item that is not plain (#4649), or both in one message."""
    vitals = VITALS_CORRECTION if vital_hits(stance) > 0 else ""
    return vitals + plain_words.correction(plain_words.failing(_watch(stance)))


def retry_is_better(retry, first):
    """Keep the retry when it leaks fewer numbers; on a tie, when fewer of its printed items fail, then when more are plain."""
    if not isinstance(retry, dict):
        return False
    before, after = vital_hits(first), vital_hits(retry)
    if after != before:
        return after < before
    bad_r, bad_f = len(plain_words.failing(_watch(retry))), len(plain_words.failing(_watch(first)))
    return bad_r < bad_f or (bad_r == bad_f and len(plain_words.plain_items(_watch(retry))) > len(plain_words.plain_items(_watch(first))))


def keep_plain(stance, coach_id=None, logger=None):
    """The stance's watch list with every item that is not plain dropped (#4649). Nothing
    replaces a dropped item; the count and the reasons are logged, never the reader's problem."""
    dropped = plain_words.failing(_watch(stance))
    if dropped and logger is not None:
        logger.warning("[stance] %s: withheld %d watch item(s) that are not plain: %s", coach_id, len(dropped), dropped)
    return plain_words.plain_items(_focus(stance))


def keep_plain_aside(stance):
    """The stance's 'set aside' list with every item that is not plain dropped (#4714)."""
    return plain_words.plain_items(_aside(stance))
