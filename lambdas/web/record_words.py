"""record_words.py — the ONE place the coaches' record is compared with a simple guess (#4580 round 1, lane E).

Site-to-A round 1 found the week page saying the coaches were measured "against a simple guess that
nothing changes from the last reading" (web/edition_scorecard.py's AI rule) while the record block's
verdict (``beats_simple_guess``) is the Brier skill against the BASE RATE — a guess that gives every
call the same chance of coming true, the share of checked calls that have. Two yardsticks were both
called "a guess", and the front page printed the exact rate as a third sentence of its own.

So: the sentence is written here, once, and every route that emits it imports it
(tests/test_edition_one_number_4580.py greps for the literal). The exact rate rides beside it as
``baseline`` — a field a page may show on tap, never a second sentence. The per-call persistence rule
("a guess that nothing changes", coach/coach_baseline.py, #4585) is a DIFFERENT comparison, scored call
by call; it keeps its own words on the call and coach pages and is never called this sentence.

Pure: no I/O, no clock.
"""

from __future__ import annotations

from typing import Any

#: The three states of the comparison, in the words every page prints. Short, one verdict each.
GUESS_BEATS = "The coaches beat a simple guess."
GUESS_NOT_YET = "The coaches do not beat a simple guess yet."
GUESS_TOO_FEW = "Too few checked calls yet to compare the coaches with a simple guess."

#: What the simple guess IS, for a rule text: the base rate, not persistence.
GUESS_RULE_WORDS = "a simple guess that gives every call the same chance of coming true — the share of checked calls that have so far"
BASELINE_RULE = "base_rate"


def guess_sentence(beats: bool | None) -> str:
    """``True`` → beats; ``False`` → not yet; ``None`` (no skill reading) → too few."""
    if beats is None:
        return GUESS_TOO_FEW
    return GUESS_BEATS if beats else GUESS_NOT_YET


def baseline(right: Any, decided: Any, beats: bool | None = None) -> dict | None:
    """The exact rate behind the sentence, as a field: ``{"rule", "rate", "rate_pct", "text"}``.

    ``rate`` is the share of checked calls that came true (what the base-rate guess assigns every call);
    ``text`` is the long form a page may show on tap. None when there is no decided count."""
    if not isinstance(decided, int) or not isinstance(right, int) or decided <= 0 or right < 0:
        return None
    rate = right / decided
    pct = round(rate * 100)
    if beats is None:
        text = f"A guess that every call has a {pct}% chance of coming true is the comparison; too few calls are checked to make it yet."
    elif beats:
        text = f"The coaches do better than a guess that every call has a {pct}% chance of coming true."
    else:
        text = f"A guess that every call has a {pct}% chance of coming true does about as well."
    return {"rule": BASELINE_RULE, "rate": round(rate, 3), "rate_pct": pct, "text": text}
