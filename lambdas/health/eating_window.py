"""eating_window.py — THE eating window (#5099, epic #5091): the charter's `nutrition.eating_window`, read once.

The owner ruled 16:8 on 2026-10-23 (R2 on #5091): the day's feedings fit inside ONE 8-hour eating window. The charter
states a DURATION, not a clock: it names no opening or closing time, so nothing here invents one. A day is graded on
the span between its first and last timed meal — inside when the span fits in `eating_hours`.

PURE: no DynamoDB, no clock, no model. The caller hands in the MacroFactor `food_log` it already read. The only read
is the charter (bundled, cached) — and a PUBLISHED surface (lambdas/web, lambdas/emails) must not make even that read
(tests/test_training_charter_privacy_5087.py): it passes the block from `training_charter.public_view()` as `data`,
which the whitelist carries for exactly this.

WHAT COUNTS AS A MEAL. A food-log row with a parseable local `HH:MM` and food energy: `calories_kcal` above zero, or
— when the row carries no calorie figure — any protein, carbohydrate or fat above zero. A zero-energy row (water, a
zero-calorie supplement) does not open the window.

UNKNOWN, NEVER A MISS (ADR-104). A day with no timed meal is `unknown`. A day where some meal rows carry no time is
`unknown` unless its TIMED rows alone already span past the window (then it is `outside`: the untimed rows can only
widen the span). An unreadable charter block is `unknown` — the window is never a remembered number.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from training import training_charter

CHARTER_PATH = "nutrition.eating_window"
VERSION = "eating-window@1.0.0"
_ENERGY_FIELDS = ("protein_g", "carbs_g", "fat_g")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def block(data: Optional[Mapping[str, Any]] = None) -> Optional[dict[str, Any]]:
    """The validated window `{type, eating_hours, fasting_hours, rule}`, or None when the block is absent or malformed.

    `data` is the block itself (a published surface passes `public_view()["nutrition"]["eating_window"]`); None reads
    the charter. Valid = a positive `eating_hours` under 24 whose `fasting_hours`, when stated, completes the day."""
    raw = training_charter.charter_value(CHARTER_PATH) if data is None else data
    if not isinstance(raw, Mapping):
        return None
    eating = _num(raw.get("eating_hours"))
    if eating is None or not 0 < eating < 24:
        return None
    fasting = _num(raw.get("fasting_hours"))
    if fasting is not None and abs(fasting + eating - 24) > 1e-9:
        return None  # a window that does not add up to a day is not a window this module can grade against
    kind = raw.get("type")
    hours: float | int = int(eating) if eating.is_integer() else eating  # 8, as the charter states it (the wire is an integer)
    return {
        "type": kind if isinstance(kind, str) and kind else f"{24 - eating:g}:{eating:g}",
        "eating_hours": hours,
        "fasting_hours": 24 - hours,
        "rule": raw.get("rule") if isinstance(raw.get("rule"), str) else None,
    }


def published_block(view: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The window block out of a `training_charter.public_view()` result — `{}` (never None, which would read the
    charter) when the view carries none, so a published surface's absent block stays an absence."""
    nutrition = (view or {}).get("nutrition") if isinstance(view, Mapping) else None
    win = nutrition.get("eating_window") if isinstance(nutrition, Mapping) else None
    return win if isinstance(win, Mapping) else {}


def published_text() -> str:
    """`describe()` over the PUBLISHED whitelist only — the one call a lambdas/web or lambdas/emails module makes."""
    return describe(published_block(training_charter.public_view()))


def published_eating_hours() -> Optional[float]:
    """The window's `eating_hours` over the PUBLISHED whitelist only, or None when the view carries no valid block."""
    b = block(published_block(training_charter.public_view()))
    return None if b is None else b["eating_hours"]


def eating_minutes(data: Optional[Mapping[str, Any]] = None) -> Optional[int]:
    b = block(data)
    return None if b is None else round(b["eating_hours"] * 60)


def describe(data: Optional[Mapping[str, Any]] = None) -> str:
    """The window as prompt / email text: `16:8 (one 8-hour eating window)`; a stated absence when unreadable."""
    b = block(data)
    if b is None:
        return "the plan's eating window (not stated: the charter block is unreadable)"
    return f"{b['type']} (one {b['eating_hours']:g}-hour eating window)"


def _minutes(hhmm: Any) -> Optional[int]:
    try:
        h, m = str(hhmm).strip().split(":")[:2]
        h_i, m_i = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    if not (0 <= h_i < 24 and 0 <= m_i < 60):
        return None
    return h_i * 60 + m_i


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _is_meal(row: Mapping[str, Any]) -> bool:
    kcal = _num(row.get("calories_kcal"))
    if kcal is not None:
        return kcal > 0
    return any((_num(row.get(f)) or 0) > 0 for f in _ENERGY_FIELDS)


def evaluate_day(food_log: Optional[list], data: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """One day's window verdict.

    `status` is `inside` | `outside` | `unknown`; `inside` mirrors it as True / False / None. `first` / `last` are the
    timed meals' `HH:MM`, `span_min` the minutes between them, `untimed_meals` the meal rows with no parseable time."""
    b = block(data)
    out: dict[str, Any] = {
        "version": VERSION,
        "window": b["type"] if b else None,
        "eating_hours": b["eating_hours"] if b else None,
        "first": None,
        "last": None,
        "span_min": None,
        "untimed_meals": 0,
        "status": "unknown",
        "inside": None,
    }
    times: list[int] = []
    for row in food_log or []:
        if not isinstance(row, Mapping) or not _is_meal(row):
            continue
        t = _minutes(row.get("time"))
        if t is None:
            out["untimed_meals"] += 1
        else:
            times.append(t)
    if b is None:
        out["reason"] = "charter_unreadable"
        return out
    if not times:
        out["reason"] = "no_timed_meal"
        return out
    first, last = min(times), max(times)
    span = last - first
    out.update(first=_hhmm(first), last=_hhmm(last), span_min=span)
    limit = round(b["eating_hours"] * 60)
    if span > limit:
        out.update(status="outside", inside=False)
    elif out["untimed_meals"]:
        out["reason"] = "untimed_meals"  # the timed rows fit, but an untimed meal could sit anywhere in the day
    else:
        out.update(status="inside", inside=True)
    return out
