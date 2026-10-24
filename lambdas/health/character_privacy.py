"""character_privacy.py — the character sheet's owner-only components (#5129).

The character sheet is a PUBLIC surface (/api/character, site/character_stats.json, the level-up
timeline). Some components read a source whose tier is owner-only — the first is Mind's
``stress_management``, which reads the evening check-in's ``stress`` rating (#5106).
``privacy.field_tiers`` declares that partition owner-only, and ``docs/DATA_GOVERNANCE.md`` records
the owner's ruling: "no public projection of any kind", with two named exceptions (the partner
letter and the silence alert), neither of which is the character sheet.

So such a component is:

* **held out** of the pillar arithmetic — its weight is in neither the sum nor the coverage, so the
  published pillar score, data coverage and confidence cannot move with what he reported, nor tell
  a check-in day from a quiet one. Only an explicit owner ruling, written into the config as
  ``in_pillar_score: true``, puts it in;
* **never named** — not on a driver list (top / dragging / no_data) and not as a level-up event's
  ``top_driver``, at any setting;
* still **recorded** in the pillar's component details (score + flags) on the stored DDB record,
  which only the owner's own surfaces (MCP) read.

The hold is fail-CLOSED in code (``OWNER_ONLY_COMPONENTS``), not only in the config twin: a lambda
deployed ahead of its config must not publish one stress-derived Mind score.
"""

from __future__ import annotations

from typing import Any, Optional

STRESS_SCALE_MAX = 4  # the evening check-in's 0-4 scale (coach/evening_checkin.py), 4 = the most stressed

# component -> the owner-only source it reads (privacy.field_tiers SOURCE_TIERS)
OWNER_ONLY_COMPONENTS = {"stress_management": "evening_checkin"}


def stress_management_score(checkin: Optional[dict[str, Any]]) -> Optional[float]:
    """0-100 from the evening check-in's ``stress`` (0-4), inverted: 0 ("no stress") is 100, 4 is 0.

    None when there was no check-in that evening, no stress rating, or a value off the scale — the
    component is then unavailable for the day (never a stand-in from another source; before #5129
    it was Whoop recovery, a physiology proxy that scored a good night's sleep as calm)."""
    raw = (checkin or {}).get("stress")
    try:
        stress = float(raw)
    except (TypeError, ValueError):
        return None
    if not 0 <= stress <= STRESS_SCALE_MAX:
        return None
    return round((STRESS_SCALE_MAX - stress) / STRESS_SCALE_MAX * 100, 1)


def component_visibility(name: str, comp_cfg: Any) -> tuple[bool, bool]:
    """(owner_only, held_out) for one configured component.

    owner_only — the code registry or the config's ``owner_only_input`` names an owner-only source.
    held_out   — the config says ``in_pillar_score: false``, or the component is owner-only and the
                 config does not say ``in_pillar_score: true`` (fail-closed)."""
    cfg = comp_cfg if isinstance(comp_cfg, dict) else {}
    owner_only = name in OWNER_ONLY_COMPONENTS or bool(cfg.get("owner_only_input"))
    held_out = cfg.get("in_pillar_score") is False or (owner_only and cfg.get("in_pillar_score") is not True)
    return owner_only, held_out


def is_private_detail(detail: Any) -> bool:
    """True for a component-details entry that must never be named on a published surface."""
    return isinstance(detail, dict) and bool(detail.get("owner_only") or detail.get("held_out"))


def event_driver_score(name: str, detail: Any) -> Optional[float]:
    """The score a level-up event may name this component by, or None — private keys, non-dict
    entries, owner-only components and non-positive scores never drive an event line."""
    if name.startswith("_") or not isinstance(detail, dict) or is_private_detail(detail):
        return None
    score = detail.get("score")
    return score if isinstance(score, (int, float)) and score > 0 else None
