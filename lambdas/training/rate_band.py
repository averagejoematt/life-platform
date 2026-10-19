"""rate_band.py — the owner's rate band (#5074, epic #5067): ONE reader of `governing_goal.rate_band_lb_per_wk`.

Owner ruling 3 (2026-10-18): 3.0 lb/wk floor, 3.5 lb/wk ceiling, always shown in lb AND % of bodyweight. The
numbers live ONLY in `config/training_charter.json`; every reader (the redline rate target, the rate-advocate
and deficit critics, `get_weight_loss_progress`) gets them from here, which reads `charter_value()`.

HOW THE BAND COMPOSES WITH THE LANDING SCHEDULE. The charter band GOVERNS from any bodyweight above
`landing.deceleration_begins_lb` (240 lb). The weight-stepped landing in `owner_redlines.rate_schedule_lb_wk`
(220 lb and down) stays his own schedule: once the landing begins the rate steps DOWN on that schedule, in weight
not weeks, and the charter band no longer describes the target. `governs(weight)` is that single boundary.

PRECEDENCE. The owner clinical guidance record outranks the band wherever the two conflict. Only its neutral
`public_rules` lines are read (never the record), a line that caps a loss rate lowers the band's ceiling (and the
floor with it), and NOTHING from the record — not the text, not the number's source — is logged or returned:
the result carries a bare `guidance_capped: True`.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PATH = "governing_goal.rate_band_lb_per_wk"
_CAP_WORDS = re.compile(r"\b(?:cap|capped|max|maximum|limit|no more than|not exceed|at most|up to|under|below|ceiling)\b", re.I)
_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\s*(?:/|per|a|each)\s*(?:wk|week)\b", re.I)


def _charter_band() -> Optional[tuple[float, float]]:
    from training.training_charter import charter_value

    try:
        floor, ceiling = charter_value(_PATH + ".floor"), charter_value(_PATH + ".ceiling")
        if floor is None or ceiling is None:
            return None
        return float(floor), float(ceiling)
    except (TypeError, ValueError):
        return None


def landing_begins_lb() -> float:
    from training import owner_redlines

    return float(owner_redlines.REDLINES["landing"]["deceleration_begins_lb"])


def governs(weight_lb: Optional[float]) -> bool:
    """True while the charter band is the target: above the weight where his landing schedule begins."""
    return bool(weight_lb) and weight_lb > landing_begins_lb()


def guidance_cap_lb_wk(public_rules: Any) -> Optional[float]:
    """The lowest loss-rate cap a neutral `public_rules` line states, or None. Reads text; keeps no text."""
    caps: list[float] = []
    for line in public_rules or []:
        s = str(line)
        if _CAP_WORDS.search(s):
            caps.extend(float(m) for m in _RATE.findall(s))
    return min(caps) if caps else None


class GuidanceReadError(Exception):
    """The clinical-record read broke. Carries no detail: 'no cap' (None) and 'the read broke' are different answers (ADR-105)."""


def guidance_cap_for(table, user_id: str = "matthew") -> Optional[float]:
    """The clinical record's `public_rules` cap, or None when the record states none. A BROKEN read raises
    GuidanceReadError (no detail, logged by class only) so a caller reports READ_FAILED instead of reading 'no cap'."""
    if table is None:
        return None
    try:
        from health import clinical_facts as cf

        rows = cf.fetch_clinical_rows(table, user_id) or []
        g = next((r for r in rows if str(r.get("sk")) == "GUIDANCE#current"), None)
        return guidance_cap_lb_wk((g or {}).get("public_rules"))
    except Exception as e:  # noqa: BLE001 — re-raised detail-free; callers route it to their own failure reporting
        logger.warning("[rate_band] guidance read unavailable (%s)", type(e).__name__)
        raise GuidanceReadError("the clinical guidance read failed") from None


def flag_threshold_lb_wk(weight_lb: Optional[float], guidance_cap: Optional[float] = None) -> Optional[float]:
    """The "losing too fast" line at a bodyweight: his schedule's CAP there (the charter ceiling itself above the
    landing — ruling 3 names one ceiling, no tolerance on top — his own taper cap from the landing down), lowered by
    a guidance cap. None w/o a weight."""
    if not weight_lb or weight_lb <= 0:
        return None
    from training import redline_rate

    cap = redline_rate.rate_schedule_step(weight_lb).get("cap")
    if cap is None:
        return None
    return min(float(cap), float(guidance_cap)) if guidance_cap is not None else float(cap)


def band(weight_lb: Optional[float], guidance_cap: Optional[float] = None) -> Optional[dict[str, Any]]:
    """The band at a bodyweight, both units. None when the charter or the weight is unreadable.

    `guidance_cap` (lb/wk) is the clinical record's cap; when it is below the ceiling it wins."""
    cb = _charter_band()
    if cb is None or not weight_lb or weight_lb <= 0:
        return None
    floor, ceiling = cb
    capped = guidance_cap is not None and guidance_cap < ceiling
    if capped:
        ceiling = float(guidance_cap)
        floor = min(floor, ceiling)

    def pct(x: float) -> float:
        return round(x / weight_lb * 100, 2)

    return {
        "floor_lb_wk": floor,
        "ceiling_lb_wk": ceiling,
        "floor_pct_bw": pct(floor),
        "ceiling_pct_bw": pct(ceiling),
        "weight_lb": weight_lb,
        "governs": governs(weight_lb),
        "guidance_capped": capped,
        "source": _PATH,
    }


def position(rate_lb_wk: Optional[float], b: Optional[dict[str, Any]]) -> dict[str, Any]:
    """{in_band, position} for a measured loss rate (positive = losing); both None when either is unknown."""
    if rate_lb_wk is None or not b:
        return {"in_band": None, "position": None}
    pos = "below" if rate_lb_wk < b["floor_lb_wk"] else "above" if rate_lb_wk > b["ceiling_lb_wk"] else "in"
    return {"in_band": pos == "in", "position": pos}


def band_view(weight_lb: Optional[float], rate_lb_wk: Optional[float], guidance_cap: Optional[float] = None) -> Optional[dict[str, Any]]:
    """The tool-facing block: floor/ceiling in both units + where the measured rate sits."""
    b = band(weight_lb, guidance_cap)
    if b is None:
        return None
    return {
        "floor_lb_wk": b["floor_lb_wk"],
        "ceiling_lb_wk": b["ceiling_lb_wk"],
        "floor_pct_bw": b["floor_pct_bw"],
        "ceiling_pct_bw": b["ceiling_pct_bw"],
        **position(rate_lb_wk, b),
        "governs": b["governs"],
        "guidance_capped": b["guidance_capped"],
    }
