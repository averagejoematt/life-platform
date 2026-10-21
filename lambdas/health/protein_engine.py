"""protein_engine.py — THE protein engine (#5098, epic #5091): the charter's protein range, four feedings, one hit.

PURE: no DynamoDB, no clock, no model. The caller hands in the MacroFactor day row it already read (readers are
injected); the only read here is the charter (`config/training_charter.json` `nutrition.protein`, bundled, cached).

ONE HIT DEFINITION. `hit(total_g)` is `health.protein_floor.met_floor(total_g, range low)` — strictly at or above the
charter's range low, no tolerance (#5003 keeps the tolerance an owner ruling). The scoring engine, the macros view, the
critics and the `protein_floor_missed` tripwire (`training.redline_rate.protein_days_missed`) all call it; the
published surfaces that count hit days call `met_floor` with the plan's floor, which a contract test holds equal to
the charter's range low (tests/test_protein_engine_5098.py).

FEEDINGS. MacroFactor food-log rows carry a local `HH:MM`. Rows within `feeding_merge_minutes` of a feeding's first
row are one feeding (the same grouping the ingest's protein-distribution score uses). A day whose rows carry no time
— or no row at all — has an UNKNOWN feeding count (None), never 0 (ADR-104).

THE BREAKFAST NUDGE (`nudge_decide`). Behind = no feeding at or above `feeding_threshold_g` logged at or before the
later of the charter cut-off and the tick. Owner-only, at most once a Pacific day (`PROTEIN_NUDGE#<date>`), sent by
`emails.protein_nudge_runner` on the coach-nudge hourly tick. The copy is information, never a command. NO ROW FOR
TODAY WITHHOLDS (`no_same_day_log`): the only protein source is an end-of-day upload, so an absent row at breakfast
is the upload's lag, not a missed feeding; armed but silent until a same-day food source exists (#5187).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from common.constants import PLAN_DAILY_PROTEIN_MIN_G
from common.macrofactor_fields import protein_meals_at
from training import training_charter

from health.protein_floor import met_floor

ENGINE_VERSION = "protein-engine@1.0.0"
NUDGE_VERSION = "protein-nudge@1.1.0"
KEY_PREFIX = "PROTEIN_NUDGE#"
BUDGET_SILENCE_TIER = 2  # = steps_nudge.BUDGET_SILENCE_TIER: a deterministic owner note, silenced with the coach nudge
_P = "nutrition.protein."


def _cv(path: str, default: Any = None) -> Any:
    return training_charter.charter_value(_P + path, default)


def range_low() -> float:
    """The range's low end — THE floor a day is graded against, as the charter states it (170, not 170.0). Falls
    back to the plan constant only when the bundled charter is unreadable (the contract test holds the two equal)."""
    return _cv("range_g.low", PLAN_DAILY_PROTEIN_MIN_G)


def range_high() -> Optional[float]:
    return _cv("range_g.high")


def hit(total_g: Optional[float], floor: Optional[float] = None) -> Optional[bool]:
    """THE hit: True at or above the range low (strict), None for an unlogged day — never a miss."""
    return met_floor(total_g, range_low() if floor is None else floor)


def _minutes(hhmm: Any) -> Optional[int]:
    try:
        h, m = str(hhmm).strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def feedings(food_log: Optional[list], merge_minutes: Optional[int] = None) -> Optional[list[dict[str, Any]]]:
    """The day's feedings `[{time, g}]` in time order, or None when no row carries a time and a protein figure."""
    merge = merge_minutes if merge_minutes is not None else _cv("feeding_merge_minutes")
    if merge is None:
        return None  # no charter grouping rule: the feeding count is unknown, never a guessed window
    merge = int(merge)
    timed = []
    for row in food_log or []:
        t, g = _minutes((row or {}).get("time")), (row or {}).get("protein_g")
        if t is not None and g is not None:
            timed.append((t, float(g)))
    if not timed:
        return None
    timed.sort()
    out: list[dict[str, Any]] = []
    start, total = timed[0]
    for t, g in timed[1:]:
        if t - start <= merge:
            total += g
        else:
            out.append({"time": _hhmm(start), "g": round(total, 1)})
            start, total = t, g
    out.append({"time": _hhmm(start), "g": round(total, 1)})
    return out


def first_feeding_behind(fed: Optional[list], by: Optional[str] = None) -> Optional[bool]:
    """True when no feeding at or above the threshold is logged at or before `by` (default: the charter cut-off).
    None when the feedings are unknown or the charter names no threshold/cut-off."""
    threshold, by = _cv("feeding_threshold_g"), by or _cv("breakfast_nudge.cutoff_pt")
    limit = _minutes(by)
    if fed is None or threshold is None or limit is None:
        return None
    return not any(f["g"] >= float(threshold) and (_minutes(f["time"]) or 0) <= limit for f in fed)


def evaluate_day(row: Optional[Mapping[str, Any]], *, floor: Optional[float] = None) -> dict[str, Any]:
    """One day from its MacroFactor row (None = no row): the total, the range, THE hit and the feedings."""
    row = row or {}
    raw = row.get("total_protein_g")
    try:
        total = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        total = None  # a malformed rollup is unknown (the macros view's `measured()` rule), never a crash
    fed = feedings(row.get("food_log"))
    threshold = _cv("feeding_threshold_g")
    return {
        "date": row.get("date"),
        "total_g": round(total, 1) if total is not None else None,
        "range_low": range_low() if floor is None else floor,
        "range_high": range_high(),
        "hit": hit(total, floor),
        "feedings": fed,
        "feedings_40g": (sum(1 for f in fed if f["g"] >= float(threshold)) if fed is not None and threshold is not None else None),
        "feedings_target": _cv("feedings_per_day"),
        "first_feeding_behind": first_feeding_behind(fed),
        "charter_version": training_charter.charter_version(),
        "version": ENGINE_VERSION,
    }


def feedings_at_threshold(row: Optional[Mapping[str, Any]]) -> Optional[float]:
    """Feedings at the charter threshold: the engine's count from the food log; else a legacy ``meals`` list at the
    same threshold; None (unknown, never 0) when neither applies or the charter names no threshold (#5214)."""
    threshold = _cv("feeding_threshold_g")
    if threshold is None:
        return None
    counted = evaluate_day(row)["feedings_40g"]
    return float(counted) if counted is not None else protein_meals_at(dict(row or {}), float(threshold))


def idempotency_key(date: str) -> str:
    return f"{KEY_PREFIX}{date}"


def in_window(now_pt: datetime) -> bool:
    start, end = _minutes(_cv("breakfast_nudge.cutoff_pt")), _minutes(_cv("breakfast_nudge.window_end_pt"))
    now = now_pt.hour * 60 + now_pt.minute
    return start is not None and end is not None and start <= now < end


def copy(verdict: Mapping[str, Any]) -> str:
    return (
        f"No feeding of {verdict['threshold_g']} g or more is logged by {verdict['by']}. The plan's protein is {verdict['feedings_target']} feedings of {verdict['threshold_g']} g or more; "
        "a protein-first breakfast now keeps the other three in reach. Fine to skip; this is just where the morning stands."
    )


def nudge_decide(*, date: str, now_pt: datetime, row: Optional[Mapping[str, Any]], already_sent: bool, budget_tier: int) -> dict[str, Any]:
    """One verdict for the breakfast nudge: `send` plus the reason, with every number that decided it."""
    out: dict[str, Any] = {
        "date": date,
        "send": False,
        "reason": None,
        "key": idempotency_key(date),
        "version": NUDGE_VERSION,
        "charter_version": training_charter.charter_version(),
    }
    if budget_tier >= BUDGET_SILENCE_TIER:
        return {**out, "reason": f"budget_tier_{budget_tier}"}
    if not in_window(now_pt):
        return {**out, "reason": "outside_window"}
    if already_sent:
        return {**out, "reason": "already_sent"}
    cutoff = _cv("breakfast_nudge.cutoff_pt")
    by = max(cutoff, now_pt.strftime("%H:%M"), key=lambda s: _minutes(s) or 0)
    out.update(threshold_g=_cv("feeding_threshold_g"), feedings_target=_cv("feedings_per_day"), cutoff=cutoff, by=by)
    if out["threshold_g"] is None or out["feedings_target"] is None:
        return {**out, "reason": "no_charter_rule"}
    if not row:
        return {**out, "reason": "no_same_day_log"}  # the upload's lag, not a miss: withhold (the EVAL stamp still lands)
    fed = feedings(row.get("food_log"))
    out["feedings"] = fed
    behind = first_feeding_behind(fed, by)
    if behind is None:
        return {**out, "reason": "feedings_unknown"}
    if not behind:
        return {**out, "reason": "on_track"}
    out["send"], out["reason"] = True, "behind_logged_below"
    out["text"] = copy(out)
    return out
