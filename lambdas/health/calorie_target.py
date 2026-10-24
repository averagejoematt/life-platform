"""calorie_target.py — THE one calorie target (#5095, epic #5091).

Before this module six readers held three different targets: a generated 1,500 kcal constant
(scoring, the character sheet, the daily brief, the weekly/monthly/nutrition/partner emails, the
hypothesis and insight engines), the redlines' prescribed band (the nutrition critics only) and
TDEE minus 500 (the macros tool and the coach's domain facts). Every one of them now asks
``resolve()`` — or the thin ``target_kcal()`` — so they cannot disagree.

ORDER (first hit wins):
  1. the week's TITRATION record, when a reader returns one. The record lives at
     ``USER#matthew#SOURCE#nutrition_titration`` / ``WEEK#<iso-monday>`` (docs/SCHEMA.md); its
     writer is the weekly titration engine (``health.titration``, #5096). A caller may inject a
     reader; when none is injected, a resolve INSIDE A LAMBDA uses ``titration.lambda_default_reader``
     (a cached, fail-soft table read), so every surface states the titrated target. Outside a Lambda
     (a unit test, a laptop) no reader is used unless one is injected.
  2. the charter's ``nutrition.calories`` block (config/training_charter.json): ``target_kcal``
     inside ``prescribed_band_kcal`` (owner ruling 2026-10-23 R1, #5091: stay ~1,500).
A titration record written under a charter version before ``records_from_version`` is not read (a
record from before the re-target is not the base). The energy floors are WARNINGS (owner ruling R1:
kept, not removed, never a clamp): a resolved target, or a typed day, under its floor carries the
gap in ``floor_warnings`` and in ``provenance`` — nothing lifts it to the floor. An unreadable
charter resolves to ``kcal: None`` with ``source: "unavailable"`` — never a remembered number
(ADR-104); every reader treats None as "no target", not zero.

PURE outside a Lambda: no table handle, no clock unless ``day`` is omitted (then Pacific today, the platform's day).
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
DAY_TYPES = ("lifting", "rest", "travel", "disrupted", "unknown")  # disrupted: a recorded disruption covers the date (#5215)


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
# A lifting day is the base plus the lifting uplift; a rest day stays at the base and is NOT paid back below it, so the
# week averages above the base by design (owner ruling 2026-10-23, #5091 follow-up 2); charter ``nutrition.training_day``.


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
        "basis": "no per-date calendar was read (the sequence alone cannot type a date): base target, lifting uplift conditional",
    }


def _grams(kcal: float, protein_g: float, fat_g: float) -> float:
    return max(0.0, (kcal - 4 * protein_g - 9 * fat_g) / 4)


def _apply_day_type(
    out: Dict[str, Any], base: Optional[float], day_type: Optional[str], week_types: Optional[Sequence[str]], read: CharterReader
) -> None:
    dt = day_type if day_type in DAY_TYPES else "unknown"
    out["day_type"], out["uplift_kcal"], out["split"], out["pre_post_session"] = dt, 0, None, None
    out["floor_warnings"] = []
    cfg = read(TRAINING_DAY_PATH)
    cfg = cfg if isinstance(cfg, dict) else {}
    if base is None:
        return
    p_low = _num(read("nutrition.protein.range_g.low"))
    fat_pct = _num(cfg.get("fat_pct_of_base_kcal"))
    fat_floor = _num(read("nutrition.floors.fat.floor_g"))
    # split_rule: fat is the larger of fat_pct of the base and the fat floor (owner ruling 2026-10-23 on #5212: it stays)
    fat_g = max(base * fat_pct / 100 / 9, fat_floor or 0.0) if fat_pct is not None else None
    # rest_day_rule (owner ruling 2026-10-23, #5091 follow-up 2): +uplift on a lifting day, every other day at the base —
    # no rest-day payback below the target, so the week averages above the base by design
    # a planned maintenance date (#5107) is the whole day's estimated burn: no lifting uplift on top of it
    delta = (_num(cfg.get("lifting_uplift_kcal")) or 0.0) if dt == "lifting" and not out.get("maintenance_day") else 0.0
    final = base + delta
    floor_any, floor_lift = _num(out.get("floor_any_day_kcal")), _num(out.get("floor_lifting_day_kcal"))
    floor = floor_lift if (dt == "lifting" and floor_lift is not None) else floor_any
    out["balance_held"] = final >= base  # the training-day rule held: no planned day under its base target
    if floor is not None and final < floor:
        # owner ruling 2026-10-23 R1 (#5091): the floors stay as WARNINGS — reported, never a clamp that raises the target
        warning = f"{dt} day {int(round(final))} kcal is {int(round(floor - final))} kcal under its {int(floor)} kcal floor (a warning, not a clamp)"
        out["floor_warnings"].append(warning)
        out["provenance"] += f"; {warning}"
    out["kcal"] = int(round(final))
    out["uplift_kcal"] = int(round(final - base))
    if delta:
        out["provenance"] += f"; {dt} day {out['uplift_kcal']:+d} kcal (training_day rule, no rest-day payback)"
    if p_low is not None and fat_g is not None:
        out["split"] = {
            "protein_g": int(round(p_low)),
            "fat_g": int(round(fat_g)),
            "carb_g": int(round(_grams(final, p_low, fat_g))),
            "rule": "protein and fat held at the base day's grams (fat never under its floor); the lifting uplift is carbohydrate",
        }
    if dt in ("lifting", "travel"):
        pre, post = cfg.get("pre_session"), cfg.get("post_session")
        out["pre_post_session"] = {"pre": pre, "post": post} if isinstance(pre, dict) and isinstance(post, dict) else None


def plan_block(date: str, disruption: Optional[Dict[str, Any]] = None, calendar: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The plan's `training_day_fuel` (#5101, owner-only). With a typed `calendar` (`training.training_calendar`,
    #5191) the date is lifting/rest/travel and the block carries the typed week (`week_days`, `week_mean_kcal`), whose
    mean is the base plus the lifting uplift spread over the week (no rest-day payback, owner ruling 2026-10-23); `week_balance_held`
    says no day of it sits under its base. Without one (the Hevy record or the count unread) a non-travel
    date is `unknown` at the base target plus `if_lifting_day` / `if_rest_day`, stated as conditional."""
    planned = (calendar or {}).get("planned_dates")
    if planned is not None:
        return _typed_block(date, disruption, calendar or {}, planned)
    typed = classify_day_type(date, disruption=disruption)
    out = resolve(date, day_type=typed["day_type"])
    out["day_type_basis"] = typed["basis"] + (f" ({calendar.get('reason')})" if calendar and calendar.get("reason") else "")
    if typed["day_type"] == "unknown":
        out["if_lifting_day"] = {
            k: v for k, v in resolve(date, day_type="lifting").items() if k in ("kcal", "uplift_kcal", "split", "pre_post_session")
        }
        out["if_rest_day"] = {k: v for k, v in resolve(date, day_type="rest").items() if k in ("kcal", "uplift_kcal", "split")}
    return out


def _typed_block(date: str, disruption: Optional[Dict[str, Any]], calendar: Dict[str, Any], planned: Sequence[str]) -> Dict[str, Any]:
    """`plan_block` on a typed week (#5191): every date of the calendar's week resolved against the same week types."""
    dates = list(calendar.get("dates") or [])
    basis = {x["date"]: x["basis"] for x in calendar.get("days") or []}
    typed = {d: classify_day_type(d, planned_dates=planned, disruption=disruption) for d in dates}
    types = [typed[d]["day_type"] for d in dates]
    week = [resolve(d, day_type=t, week_day_types=types) for d, t in zip(dates, types)]
    me = classify_day_type(date, planned_dates=planned, disruption=disruption)
    out = resolve(date, day_type=me["day_type"], week_day_types=types)
    out["day_type_basis"] = f"per-date calendar: {basis.get(date)}" if me["day_type"] != "travel" else me["basis"]
    out["week_days"] = [{"date": d, "day_type": t, "kcal": r["kcal"]} for d, t, r in zip(dates, types, week)]
    kcal = [r["kcal"] for r in week]
    out["week_mean_kcal"] = round(sum(kcal) / len(kcal), 1) if kcal and None not in kcal else None
    out["week_balance_held"] = all(r.get("balance_held") for r in week)
    out["calendar"] = {
        k: calendar.get(k) for k in ("lifting_days_per_wk", "credited_this_week", "typed_lifting_days", "reaches_count", "rule")
    }
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
    if titration_reader is None:
        from health.titration import lambda_default_reader  # noqa: PLC0415 — lazy: titration imports this module

        titration_reader = lambda_default_reader()
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
    stale = record_predates_retarget(record, block.get("records_from_version"))
    rec_kcal = None if stale else _num((record or {}).get("kcal"))
    if rec_kcal is not None and rec_kcal > 0:
        kcal: Optional[float] = rec_kcal
        out["source"] = "titration"
        out["provenance"] = f"titration record {titration_sk(week)}" + (
            f" ({record.get('reason')})" if record and record.get("reason") else ""
        )
        lo, hi = _num((record or {}).get("band_low")), _num((record or {}).get("band_high"))
        if lo is not None and hi is not None:
            out["band_low"], out["band_high"] = int(lo), int(hi)
        kcal = _maintenance_day(out, record, day, rec_kcal)
    else:
        kcal = _num(block.get("target_kcal"))
        if kcal is not None and kcal > 0:
            out["source"] = "charter"
            out["provenance"] = f"charter {CHARTER_PATH}.target_kcal v{out['charter_version']} (owner ruling 2026-10-23 R1: stay ~1,500)"
            if stale:
                out["provenance"] += (
                    f"; the week's titration record {titration_sk(week)} was written under charter v{(record or {}).get('charter_version')}, "
                    f"before the re-target at v{block.get('records_from_version')}, so it is not read"
                )
        else:
            kcal = None
    out["base_kcal"] = int(round(kcal)) if kcal is not None else None
    _apply_day_type(out, kcal, day_type, week_day_types, read)
    return out


def _maintenance_day(out: Dict[str, Any], record: Optional[Dict[str, Any]], day: DayLike, base: float) -> float:
    """#5107: on a date the week's titration record lists as a planned maintenance date, the record's maintenance kcal
    (and its band) serve; with no readable estimate the week's target serves and the provenance says so."""
    from health import maintenance_week  # noqa: PLC0415 — lazy, like the titration reader

    m = maintenance_week.resolve_day(record, _day(day).isoformat())
    if m is None:
        return base
    out["maintenance_day"] = True
    if m["kcal"] is None:
        out["provenance"] += f"; planned maintenance date ({m['label']}) with no readable maintenance estimate: the week's target serves"
        return base
    out["provenance"] += f"; planned maintenance date ({m['label']}): maintenance at the {m['basis']}"
    if m["band"]:
        out["band_low"], out["band_high"] = m["band"]
    return float(m["kcal"])


def _version(v: Any) -> Optional[tuple]:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except (TypeError, ValueError):
        return None


def record_predates_retarget(record: Optional[Dict[str, Any]], from_version: Any) -> bool:
    """True when a titration record was written under a charter version before ``nutrition.calories.records_from_version``
    (the 2026-10-23 re-target, R1): its kcal carried the old target, so neither the resolver nor the engine reads it as the
    base. A record with no readable version, or no rebase version on the charter, is read as before."""
    if not record or from_version is None:
        return False
    have, need = _version(record.get("charter_version")), _version(from_version)
    return have is not None and need is not None and have < need


def target_kcal(day: DayLike = None, **readers: Any) -> Optional[int]:
    """The resolved kcal alone, for a reader that only states or grades against the number.
    None means no target could be resolved — a caller states that, it never substitutes one."""
    kcal = resolve(day, **readers)["kcal"]
    return int(kcal) if kcal is not None else None


def calorie_band(day: DayLike = None, **readers: Any) -> Optional[tuple]:
    """The calorie habit's floor and ceiling for ``day`` (#5099: ``prescribed_band_kcal``, centred on the target, moved
    with it by a titration record): ``(band_low, band_high)``, or None when either edge is unresolved."""
    r = resolve(day, **readers)
    lo, hi = r.get("band_low"), r.get("band_high")
    return (int(lo), int(hi)) if lo is not None and hi is not None and lo <= hi else None


def target_phrase(day: DayLike = None, **readers: Any) -> str:
    """``"1500 kcal"`` or ``"no calorie target resolved"`` — for prompt and email lines, so a missing
    charter reads as an absence, never as ``None kcal``."""
    kcal = target_kcal(day, **readers)
    return f"{kcal} kcal" if kcal is not None else "no calorie target resolved"
