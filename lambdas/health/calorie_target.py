"""calorie_target.py — THE one calorie target (#5095, epic #5091).

Before this module six readers held three different targets: a generated 1,500 kcal constant
(scoring, the character sheet, the daily brief, the weekly/monthly/nutrition/partner emails, the
hypothesis and insight engines), the redlines' prescribed band (the nutrition critics only) and
TDEE minus 500 (the macros tool and the coach's domain facts). Every one of them now asks
``resolve()`` — or the thin ``target_kcal()`` — so they cannot disagree.

ORDER (first hit wins):
  1. the week's TITRATION record, when a reader is injected and returns one. The record lives at
     ``USER#matthew#SOURCE#nutrition_titration`` / ``WEEK#<iso-monday>`` (docs/SCHEMA.md); its
     writer is the weekly titration engine (#5096), which is NOT built yet — this module defines
     the seam and the record shape only, so no production caller injects a reader today.
  2. the charter's ``nutrition.calories`` block (config/training_charter.json): ``target_kcal``
     inside ``prescribed_band_kcal`` (the panel default R1, pending the owner's answer: eat up to
     the prescribed band now, refit weekly).
The any-day floor (``floor_any_day_kcal``) clamps whatever was resolved, and the clamp is named in
``provenance``. An unreadable charter resolves to ``kcal: None`` with ``source: "unavailable"`` —
never a remembered number (ADR-104); every reader treats None as "no target", not zero.

PURE: no table handle, no clock unless ``day`` is omitted (then Pacific today, the platform's day).
The charter read goes through ``training.training_charter`` — bundled, read once per container and
cached 15 min — so a per-request caller does no S3 read per call.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Optional, Union

CHARTER_PATH = "nutrition.calories"
TITRATION_SOURCE = "nutrition_titration"
TITRATION_PK = f"USER#matthew#SOURCE#{TITRATION_SOURCE}"
TITRATION_SK_PREFIX = "WEEK#"

#: A titration reader takes the week's ISO Monday (YYYY-MM-DD) and returns the stored record, or None.
TitrationReader = Callable[[str], Optional[Dict[str, Any]]]
#: A charter reader takes a dotted path and returns the value, or None.
CharterReader = Callable[[str], Any]

DayLike = Union[str, date, None]


def _day(day: DayLike) -> date:
    if isinstance(day, date):
        return day
    if not (isinstance(day, str) and day):
        from common.pacific_time import pacific_today  # noqa: PLC0415 — lazy: the clock only when no day is given

        day = pacific_today()
    return datetime.strptime(day[:10], "%Y-%m-%d").date()  # a calendar-day key, not an instant


def week_monday(day: DayLike) -> str:
    """The ISO Monday (YYYY-MM-DD) of the week containing ``day`` — the titration record's key."""
    d = _day(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def titration_sk(day: DayLike) -> str:
    return f"{TITRATION_SK_PREFIX}{week_monday(day)}"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _default_charter_reader(dotted: str) -> Any:
    from training.training_charter import charter_value  # noqa: PLC0415 — lazy: import-safe offline

    return charter_value(dotted)


def _charter_version(charter_reader: Optional[CharterReader]) -> Optional[str]:
    v = (charter_reader or _default_charter_reader)("version")
    return v if isinstance(v, str) else None


def resolve(
    day: DayLike = None,
    *,
    titration_reader: Optional[TitrationReader] = None,
    charter_reader: Optional[CharterReader] = None,
) -> Dict[str, Any]:
    """The calorie target for ``day``: ``{kcal, band_low, band_high, floor_any_day_kcal,
    floor_lifting_day_kcal, source, provenance, charter_version, week}``.

    ``source`` is ``"titration"``, ``"charter"`` or ``"unavailable"``. ``provenance`` says where the
    number came from in words, including a floor clamp when one applied."""
    read = charter_reader or _default_charter_reader
    block = read(CHARTER_PATH)
    block = block if isinstance(block, dict) else {}
    week = week_monday(day) if (day or titration_reader is not None) else None  # no clock read unless a week is needed
    band = block.get("prescribed_band_kcal") or [None, None]
    band_low, band_high = (_num(band[0]), _num(band[1])) if isinstance(band, (list, tuple)) and len(band) == 2 else (None, None)
    floor_any = _num(block.get("floor_any_day_kcal"))
    floor_lift = _num(block.get("floor_lifting_day_kcal"))
    out: Dict[str, Any] = {
        "kcal": None,
        "band_low": int(band_low) if band_low is not None else None,
        "band_high": int(band_high) if band_high is not None else None,
        "floor_any_day_kcal": int(floor_any) if floor_any is not None else None,
        "floor_lifting_day_kcal": int(floor_lift) if floor_lift is not None else None,
        "source": "unavailable",
        "provenance": f"charter {CHARTER_PATH} unreadable — no calorie target (never a remembered number)",
        "charter_version": _charter_version(charter_reader),
        "week": week,
    }

    record = titration_reader(week) if (titration_reader is not None and week) else None
    rec_kcal = _num((record or {}).get("kcal"))
    if rec_kcal is not None and rec_kcal > 0:
        kcal: Optional[float] = rec_kcal
        out["source"] = "titration"
        out["provenance"] = f"titration record {titration_sk(week)}" + (
            f" ({record.get('reason')})" if record and record.get("reason") else ""
        )
        lo, hi = _num((record or {}).get("band_low")), _num((record or {}).get("band_high"))
        if lo is not None and hi is not None:
            out["band_low"], out["band_high"] = int(lo), int(hi)
    else:
        kcal = _num(block.get("target_kcal"))
        if kcal is not None and kcal > 0:
            out["source"] = "charter"
            out["provenance"] = (
                f"charter {CHARTER_PATH}.target_kcal v{out['charter_version']} (panel default R1: eat up to the prescribed band)"
            )
        else:
            kcal = None

    if kcal is not None and floor_any is not None and kcal < floor_any:
        out["provenance"] += f"; clamped up to the any-day floor {int(floor_any)} kcal (resolved {int(kcal)})"
        kcal = floor_any
    out["kcal"] = int(round(kcal)) if kcal is not None else None
    return out


def target_kcal(day: DayLike = None, **readers: Any) -> Optional[int]:
    """The resolved kcal alone, for a reader that only states or grades against the number.
    None means no target could be resolved — a caller states that, it never substitutes one."""
    kcal = resolve(day, **readers)["kcal"]
    return int(kcal) if kcal is not None else None


def target_phrase(day: DayLike = None, **readers: Any) -> str:
    """``"2100 kcal"`` or ``"no calorie target resolved"`` — for prompt and email lines, so a missing
    charter reads as an absence, never as ``None kcal``."""
    kcal = target_kcal(day, **readers)
    return f"{kcal} kcal" if kcal is not None else "no calorie target resolved"
