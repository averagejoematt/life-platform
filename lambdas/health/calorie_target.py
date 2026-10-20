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
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Union

CHARTER_PATH = "nutrition.calories"
TITRATION_SOURCE = "nutrition_titration"
TITRATION_PK = f"USER#matthew#SOURCE#{TITRATION_SOURCE}"
TITRATION_SK_PREFIX = "WEEK#"

#: A titration reader takes the week's ISO Monday (YYYY-MM-DD) and returns the stored record, or None.
TitrationReader = Callable[[str], Optional[Dict[str, Any]]]
#: A charter reader takes a dotted path and returns the value, or None.
CharterReader = Callable[[str], Any]

DayLike = Union[str, date, None]

TRAINING_DAY_PATH = "nutrition.training_day"
DAY_TYPES = ("lifting", "rest", "travel", "unknown")


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


# ── training-day fuel (#5101, epic #5091) ───────────────────────────────────────────────────
# Built on the panel default R1 (eat up to the band now, refit weekly). The uplift on a lifting day is
# balanced by the rest days, so the WEEK averages the base target; charter ``nutrition.training_day``.


def classify_day_type(
    day: DayLike,
    *,
    planned_dates: Optional[Iterable[str]] = None,
    disruption: Optional[Dict[str, Any]] = None,
    charter_reader: Optional[CharterReader] = None,
) -> Dict[str, str]:
    """``{day_type, basis}`` for a date: ``travel`` (an active travel disruption, or a charter travel window),
    else ``lifting``/``rest`` from the PLAN (``planned_dates`` = the dates with a planned routine, when the plan was
    read), else ``unknown``. The split sequence has no calendar (it serves the next undone session every day, a rest day
    only postpones it), so it cannot type a date and never yields ``lifting`` or ``rest``; a plan that was not read
    is an absence, never ``rest``."""
    read = charter_reader or _default_charter_reader
    d = _day(day).isoformat()
    dis = disruption or {}
    if dis.get("phase") == "active" and dis.get("template") == "travel":
        lo, hi = str(dis.get("start_date") or "")[:10], str(dis.get("until") or "")[:10]
        if lo and lo <= d and (not hi or d <= hi):
            return {"day_type": "travel", "basis": "disruption record (travel template active)"}
    for w in read("travel.windows") or []:
        lo, hi = str((w or {}).get("start") or "")[:10], str((w or {}).get("end") or "")[:10]
        if lo and hi and lo <= d <= hi:
            return {"day_type": "travel", "basis": f"charter travel window {w.get('label')}"}
    if planned_dates is not None:
        planned = {str(x)[:10] for x in planned_dates}
        return {"day_type": "lifting" if d in planned else "rest", "basis": "planned routine for the date"}
    return {
        "day_type": "unknown",
        "basis": "no per-date plan calendar (the sequence cannot type a date): base target, lifting uplift conditional",
    }


def _grams(kcal: float, protein_g: float, fat_g: float) -> float:
    return max(0.0, (kcal - 4 * protein_g - 9 * fat_g) / 4)


def _apply_day_type(
    out: Dict[str, Any], base: Optional[float], day_type: Optional[str], week_types: Optional[Sequence[str]], read: CharterReader
) -> None:
    dt = day_type if day_type in DAY_TYPES else "unknown"
    out["day_type"], out["uplift_kcal"], out["split"], out["pre_post_session"] = dt, 0, None, None
    cfg = read(TRAINING_DAY_PATH)
    cfg = cfg if isinstance(cfg, dict) else {}
    if base is None:
        return
    uplift = _num(cfg.get("lifting_uplift_kcal")) or 0.0
    n_lift = list(week_types).count("lifting") if week_types is not None else (_num(read("split.lifting_days_per_wk")) or 0)
    n_rest = list(week_types).count("rest") if week_types is not None else 7 - n_lift
    delta = 0.0
    if dt == "lifting":
        delta = uplift
    elif dt == "rest" and n_rest > 0:
        delta = -uplift * n_lift / n_rest
    final = base + delta
    floor_any, floor_lift = _num(out.get("floor_any_day_kcal")), _num(out.get("floor_lifting_day_kcal"))
    floor = floor_lift if (dt == "lifting" and floor_lift is not None) else floor_any
    out["balance_held"] = True
    if floor is not None and final < floor:
        out[
            "provenance"
        ] += f"; {dt} day clamped up to its floor {int(floor)} kcal (resolved {int(final)}) — the weekly balance is NOT held"
        final, out["balance_held"] = floor, False
    out["kcal"] = int(round(final))
    out["uplift_kcal"] = int(round(final - base))
    if dt != "unknown" and delta:
        out["provenance"] += f"; {dt} day {out['uplift_kcal']:+d} kcal (training_day rule, panel default R1)"
    p_low = _num(read("nutrition.protein.range_g.low"))
    fat_pct = _num(cfg.get("fat_pct_of_base_kcal"))
    if p_low is not None and fat_pct is not None:
        fat_g = base * fat_pct / 100 / 9
        out["split"] = {
            "protein_g": int(round(p_low)),
            "fat_g": int(round(fat_g)),
            "carb_g": int(round(_grams(final, p_low, fat_g))),
            "rule": "protein and fat held at the base day's grams; the uplift and the rest-day offset are carbohydrate",
        }
    if dt in ("lifting", "travel"):
        pre, post = cfg.get("pre_session"), cfg.get("post_session")
        out["pre_post_session"] = {"pre": pre, "post": post} if isinstance(pre, dict) and isinstance(post, dict) else None


def plan_block(date: str, disruption: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The plan's `training_day_fuel` (#5101, owner-only): today's resolution (no per-date calendar exists yet, so a
    non-travel date is `unknown` at the base target) plus `if_lifting_day` / `if_rest_day`, stated as conditional."""
    typed = classify_day_type(date, disruption=disruption)
    out = resolve(date, day_type=typed["day_type"])
    out["day_type_basis"] = typed["basis"]
    if typed["day_type"] == "unknown":
        out["if_lifting_day"] = {
            k: v for k, v in resolve(date, day_type="lifting").items() if k in ("kcal", "uplift_kcal", "split", "pre_post_session")
        }
        out["if_rest_day"] = {k: v for k, v in resolve(date, day_type="rest").items() if k in ("kcal", "uplift_kcal", "split")}
    return out


def resolve(
    day: DayLike = None,
    *,
    titration_reader: Optional[TitrationReader] = None,
    charter_reader: Optional[CharterReader] = None,
    day_type: Optional[str] = None,
    week_day_types: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """The calorie target for ``day``: ``{kcal, band_low, band_high, floor_any_day_kcal,
    floor_lifting_day_kcal, source, provenance, charter_version, week, day_type, base_kcal,
    uplift_kcal, split}``. ``kcal`` is the FINAL kcal for the day; with no ``day_type`` (every caller
    before #5101) the day is ``unknown`` and ``kcal`` is the base — nothing else changes.

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
    out["base_kcal"] = int(round(kcal)) if kcal is not None else None
    _apply_day_type(out, kcal, day_type, week_day_types, read)
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
