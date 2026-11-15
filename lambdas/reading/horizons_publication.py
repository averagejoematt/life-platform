"""horizons_publication.py — the publication stamp for the Horizons pick's coach-written text (#5947).

A Horizons pick is curated by an AI coach in an owner session (``mcp.tools_reading.tool_curate_horizon``)
whose context holds owner-only material, and its row lives in a partition the narrative publication
chokepoint (``web.narrative_publication``) does not gate. Until #5947 the coach's one-line pitch went
from that session to the public feed with NO gate at all — the retrospective beside it had one (#1673,
#1830); the pitch had none.

THE RULE, the retrospective's own: public by POSITIVE stamp, fail closed.

  * AT CURATE, every coach-typed string on the card (pitch, title, source) is screened and the verdict
    is stamped on the row: ``pitchStatus`` = ``published`` | ``held`` (+ neutral ``pitchHoldCategories``).
  * AT THE PUBLIC READ, the pitch is served only when the row carries ``pitchStatus == "published"``
    AND the text still clears today's screen (the vocabulary can widen after a stamp). A row with no
    stamp — every pick curated before this module — is withheld by construction.

THE SCREEN (``screen``) is deterministic and never raises: the #1673 gate's spine (the channel-derived
blocked vocabulary, real public figures, PII) plus the owner-only clinical vocabulary
(``privacy.clinical_screen``, required). If either vocabulary cannot be loaded the verdict is HELD — a
screen that could not run vouches for nothing. Category tokens are neutral and no term is ever echoed.

A keyword screen cannot see a paraphrase; the stamp is what makes the default "withheld", and the
curating coach sees the verdict in the dry-run preview before anything is stored.

Pure module: no AWS at import.
"""

from __future__ import annotations

from typing import Any, Optional

from privacy import broadcast_sensitivity_gate as gate, clinical_screen

STATUS_ATTR = "pitchStatus"
CATEGORIES_ATTR = "pitchHoldCategories"

STATUS_PUBLISHED = "published"
STATUS_HELD = "held"

CATEGORY_CLINICAL = "clinical"
CATEGORY_SCREEN_UNAVAILABLE = "screen_unavailable"

# Every coach-typed string that can reach the public card.
SCREENED_FIELDS = ("pitch", "title", "source")
# A pick's title and source are the work's own attribution (the link is verified): a real author or
# publisher named THERE is the citation, not the "public figure passed off as a platform coach" the
# real-name guard exists for. In the coach's own prose (the pitch) the guard holds, as it does for
# the retrospective.
ATTRIBUTION_FIELDS = ("title", "source")


def screen(text: Any) -> tuple:
    """``(status, categories)`` for one text. Never raises; an unloadable vocabulary HOLDS."""
    s = str(text or "")
    try:
        cats = list(gate.deterministic_findings(s))
        if clinical_screen.mentions(s, require=True):
            cats.append(CATEGORY_CLINICAL)
    except Exception:  # noqa: BLE001 — a screen that could not run never clears (fail closed)
        return STATUS_HELD, [CATEGORY_SCREEN_UNAVAILABLE]
    return (STATUS_HELD if cats else STATUS_PUBLISHED), cats


def is_clean(text: Any) -> bool:
    return screen(text)[0] == STATUS_PUBLISHED


def _field_categories(field: str, value: Any) -> list:
    cats = screen(value)[1]
    if field in ATTRIBUTION_FIELDS:
        cats = [c for c in cats if c != gate.CATEGORY_REAL_NAME]
    return cats


def attribution_has_finding(pick: dict) -> bool:
    """True when the title or source carries a POSITIVE finding (a term, PII) — the card is not served.
    An unavailable screen is not a finding: the verified title still shows, the pitch does not."""
    for field in ATTRIBUTION_FIELDS:
        value = (pick or {}).get(field)
        if value and [c for c in _field_categories(field, value) if c != CATEGORY_SCREEN_UNAVAILABLE]:
            return True
    return False


def stamp(pick: dict) -> dict:
    """The attributes ``tool_curate_horizon`` merges onto the row it stores (and shows in its preview)."""
    cats: list = []
    for field in SCREENED_FIELDS:
        value = (pick or {}).get(field)
        if not value:
            continue
        for c in _field_categories(field, value):
            if c not in cats:
                cats.append(c)
    attrs: dict = {STATUS_ATTR: STATUS_HELD if cats else STATUS_PUBLISHED}
    if cats:
        attrs[CATEGORIES_ATTR] = cats
    return attrs


def pitch_is_stamped_public(pick: dict) -> bool:
    """The stored verdict alone — what a producer that READS the pitch (the retrospective) keys on."""
    return bool((pick or {}).get("pitch")) and (pick or {}).get(STATUS_ATTR) == STATUS_PUBLISHED


def public_pitch(pick: dict) -> Optional[str]:
    """The pitch as the public feed may serve it, or None. Stamp AND a clean screen today."""
    if not pitch_is_stamped_public(pick):
        return None
    pitch = pick["pitch"]
    return pitch if is_clean(pitch) else None
