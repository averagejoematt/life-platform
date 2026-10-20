"""macro_floors.py — THE fat / carbohydrate / fibre floor grade (#5102, epic #5091): pure, no DynamoDB, no clock, no model.

The floors are the charter's (`config/training_charter.json` `nutrition.floors`, read through `training_charter.charter_value`);
the redlines (`owner_redlines.fat_floor_g` / `carb_floor_g`) read the same block. ONE HIT DEFINITION, like the protein engine:
a day meets a floor when its logged total is at or above it, strictly. A missing or malformed field is `unknown`
(`met` None), never a miss (ADR-104). The scoring engine, the nutrition critics and any macro view call `evaluate_day`.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from training import training_charter

MODULE_VERSION = "macro-floors@1.0.0"
# macro -> (MacroFactor day-row field, charter key under nutrition.floors, display name)
MACROS = {
    "fat": ("total_fat_g", "fat", "fat"),
    "carb": ("total_carbs_g", "carb", "carbohydrate"),
    "fibre": ("total_fiber_g", "fibre", "fibre"),
}


def floor_g(macro: str) -> Optional[float]:
    """The charter's floor for `macro` (fat | carb | fibre), or None when the charter does not carry it."""
    return training_charter.charter_value(f"nutrition.floors.{MACROS[macro][1]}.floor_g")


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool) or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def hit(value_g: Optional[float], floor: Optional[float]) -> Optional[bool]:
    """THE hit: True at or above the floor (strict, no tolerance), None when either side is unknown."""
    if value_g is None or floor is None:
        return None
    return value_g >= floor


def grade(macro: str, value: Any) -> dict[str, Any]:
    """One macro on one day: `{value_g, floor_g, met, unknown}`."""
    v, f = _num(value), _num(floor_g(macro))
    met = hit(v, f)
    return {"value_g": round(v, 1) if v is not None else None, "floor_g": f, "met": met, "unknown": met is None}


def evaluate_day(row: Optional[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The three floors for one MacroFactor day row (None = no row: all three unknown)."""
    row = row or {}
    return {m: grade(m, row.get(MACROS[m][0])) for m in MACROS}


def miss_text(macro: str, g: Mapping[str, Any]) -> Optional[str]:
    """The report line for a miss, carrying the floor AND the value; None when the floor was met or is unknown."""
    if g.get("met") is not False:
        return None
    return f"{MACROS[macro][2]} {g['value_g']:g} g is below the {g['floor_g']:g} g floor"


def score(days: Mapping[str, Mapping[str, Any]]) -> Optional[int]:
    """0-100 for the daily grade: the mean of the KNOWN floors, each 100 when met and `80 * value / floor` below
    (the protein half's curve). None when all three are unknown, so the component drops the slot rather than guess."""
    parts = []
    for g in days.values():
        if g["met"] is None:
            continue
        parts.append(100.0 if g["met"] else max(0.0, 80.0 * g["value_g"] / g["floor_g"]))
    return round(sum(parts) / len(parts)) if parts else None
