"""character_public_rows.py — the served rows of a pillar or headline with no public number (#6224).

Owner rulings 2026-11-26: Mind is not scored in public, and while ``character_privacy.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE``
is on every chain-carried value is served as "being recalculated". The writers of the public files
(``character_stats.json``, the buddy page) build their rows here, so each says the state and never defaults a number in.
"""

from __future__ import annotations

from typing import Any, Optional

from health import character_privacy


def site_pillar(name: str, pd: Any, emoji: str = "") -> Optional[dict[str, Any]]:
    """The ``character_stats.json`` pillar row of a pillar with no public number, else None (the caller's scored row):
    Mind (not scored), a pending pillar (consistency), or a verbatim pillar whose level is pending (its raw score stays)."""
    pd = pd if isinstance(pd, dict) else {}
    if not (character_privacy.is_not_scored(pd) or pd.get("scores_pending") or pd.get("level_pending")):
        return None
    row: dict[str, Any] = {"name": name, "emoji": emoji, "level": None, "tier": None, "xp_delta": None, "challenge_bonus_xp": None}
    row["trend"] = "neutral"
    if pd.get("level_pending") and not pd.get("not_instrumented"):
        return dict(row, raw_score=float(pd.get("raw_score", 0)), not_instrumented=False, level_pending=True)
    return dict(
        row,
        raw_score=None,
        not_instrumented=True,
        not_scored=bool(pd.get("not_scored")),
        not_scored_note=pd.get("not_scored_note"),
        scores_pending=bool(pd.get("scores_pending") or pd.get("level_pending")),
    )


def pending_headline(**extra: Any) -> dict[str, Any]:
    """The headline of a public file while the scores are being recalculated: the state and the note, no number."""
    out: dict[str, Any] = {"level": None, "tier": None, "tier_emoji": None, "xp_total": None}
    out.update({"status": character_privacy.PENDING_STATUS, "pending_note": character_privacy.PENDING_NOTE})
    out.update(extra)
    return out
