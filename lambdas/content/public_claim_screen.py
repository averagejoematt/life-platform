"""public_claim_screen.py — a model-written line that makes an unsupported medical claim, or calls a pending food day
empty, is withheld from a public surface (#6224; owner ruling 2026-11-23, "these claims must not remain publicly served").

THE TWO CLAIMS IT EXISTS FOR (paraphrased; the served originals stay off the public repo):

  * a medical milestone the platform never computed (a weight read as the point where a risk changes). The SAME deterministic screen the Morning Brief applies to its recommendations
    (``content.brief_rec_screen``, #6240) decides it here: reused, never forked. A public line carries no provenance,
    so it is never "grounded" and every high-stakes class is withheld; the genomic class is never shown anywhere.
  * a day whose food export has not arrived described as nothing eaten / nothing logged. MacroFactor reaches the
    platform by a manual export (~24 h behind by design), so a missing row before the export lands is PENDING, never
    zero. ``common.food_log_state.arrival`` is the ONE answer to "has that day's export arrived?" (the brief and the
    day page read it too); a line that makes a food-log claim about a day that is not ``arrived`` is withheld. An
    unknown arrival (no stamp, no data day, a failed read) is not ``arrived``: the claim cannot be checked, so it is
    not served.

THE UNIT. A unit is one model-written field (the daily line, one recommendation, one coach read). If any sentence in
it trips a rule the WHOLE unit is withheld — never a sentence cut out of it, which would leave a residue that still
points at the claim ("that's not a number on a scale…"). That matches both precedents: the brief screen holds a whole
recommendation, and the narrative publication gate empties a whole value. The words are never rewritten and the
stored row is never touched; the owner's own tools keep reading it.

No clock. The one read (``last_food_arrival_day``) goes through the caller's table handle; everything else is pure.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from common import food_log_state

from content import brief_rec_screen

logger = logging.getLogger(__name__)

FOOD_LOG_PENDING = "food_log_pending"  # the reason a food-log claim about a not-arrived day is withheld

# A sentence that says what was (or was not) logged/eaten: a food word AND a logging word in the same sentence.
_FOOD_WORD = re.compile(r"\b(nutrition|food|foods|meals?|calories|kcal|protein|carbs?|fat grams|macros?|intake|eating|ate)\b", re.I)
_LOG_WORD = re.compile(r"\b(logged|unlogged|logging|log|tracked|untracked|recorded)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: Any) -> list:
    """The unit's sentences (a unit with no terminal punctuation is one sentence)."""
    return [s for s in _SENTENCE.split(str(text or "").strip()) if s.strip()]


def medical_classes(text: Any) -> list:
    """Every high-stakes class ``brief_rec_screen`` finds in any sentence of the unit, in order, de-duplicated.
    A public line has no grounded source, so any class means withheld (``brief_rec_screen.screen(..., "")``)."""
    out: list = []
    for s in sentences(text):
        shown, classes = brief_rec_screen.screen(s, "")
        if not shown:
            out.extend(c for c in classes if c not in out)
    return out


def food_log_claim(text: Any) -> bool:
    """True when a sentence of the unit says what was or was not logged/eaten."""
    return any(_FOOD_WORD.search(s) and _LOG_WORD.search(s) for s in sentences(text))


def withheld_reasons(text: Any, *, data_day: Any = None, last_arrival_day: Any = None) -> list:
    """Why the unit may not be published (empty = publishable). ``data_day`` is the day the line describes;
    ``last_arrival_day`` is ``food_log_state``'s Pacific day the newest export landed."""
    reasons = medical_classes(text)
    if food_log_claim(text) and food_log_state.arrival(data_day, last_arrival_day) != food_log_state.ARRIVED:
        reasons.append(FOOD_LOG_PENDING)
    return reasons


def publishable(text: Any, *, data_day: Any = None, last_arrival_day: Any = None) -> Any:
    """The unit unchanged when it may be published, else None (the caller serves its existing empty state)."""
    if text is None or not str(text).strip():
        return text
    return None if withheld_reasons(text, data_day=data_day, last_arrival_day=last_arrival_day) else text


def last_food_arrival_day(table_client: Any, user_id: str = "matthew") -> Optional[str]:
    """``food_log_state``'s Pacific day the newest MacroFactor export landed, or None (no table, a failed read, no
    stamp). None is "unknown", and an unknown arrival never licenses a food-log claim."""
    if table_client is None:
        return None
    try:
        fresh = food_log_state.read_freshness(table_client, f"USER#{user_id}#SOURCE#")
    except Exception as e:  # noqa: BLE001 — fail-soft: unknown, so a food-log claim is withheld
        logger.warning("[public_claim_screen] food-log freshness read failed (non-fatal): %s", type(e).__name__)
        return None
    day = (fresh or {}).get("last_arrival_day")
    return str(day) if day else None


def screen_public_lines(
    elena_hero_line: Any, brief_excerpt: Any, group_narratives: Any, *, data_day: Any = None, last_arrival_day: Any = None
):
    """(elena_hero_line, brief_excerpt, group_narratives) — the daily brief's AI lines as public_stats.json and pulse.json
    carry them — with every unit this module withholds set to None (a withheld ``group_narratives`` entry is dropped).
    Each field is one unit. The log carries the field name and the reasons only, never the words."""

    def one(name: str, text: Any) -> Any:
        if not isinstance(text, str) or not text.strip():
            return text
        reasons = withheld_reasons(text, data_day=data_day, last_arrival_day=last_arrival_day)
        if reasons:
            logger.warning("[public_claim_screen] public line withheld: field=%s reasons=%s", name, ",".join(reasons))
            return None
        return text

    narratives = group_narratives
    if isinstance(group_narratives, dict):
        narratives = {k: v for k, v in ((k, one(f"group_narratives.{k}", v)) for k, v in group_narratives.items()) if v is not None}
    return one("elena_hero_line", elena_hero_line), one("brief_excerpt", brief_excerpt), narratives
