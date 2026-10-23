"""food_panel.py — the panel rubric's FOOD seats: the week's food plan graded like the training plan (#5110, epic #5094).

WHY THIS EXISTS

The 2026-10-18 nutrition panel review graded the food side once, in prose, with no baseline; the training plan got
a fixed rubric in #5072 and the food plan did not. This module puts the food plan through the SAME harness: the
same letter scale and pass bar (the charter's `panel_target` — overall A, every seat 9 of 10 or better with its
concession named), the same blinded judge on the same routes (`panel_judge`, `charter.judge` weekly and
`charter.judge_gate` in CI), the same negative-control discipline and the same golden gate.

THE SEATS (`config/panel_rubric.json` `food_panel.seats`) are schools and roles, never people; each seat's
concession is READ from the charter's `nutrition.concession_ledger` at grade time and the seat keys must equal the
ledger's keys (tests/test_food_panel_5110.py).

THE FOOD PLAN (the one input shape — a golden fixture and the weekly real plan are both this; `build_food_plan`):

    {"case_id", "panel": "food", "week_start", "charter_version",
     "days": [7 x {date, day_type, kcal, base_kcal, uplift_kcal, band_low, band_high, floor_any_day_kcal,
                   floor_lifting_day_kcal, source, provenance, charter_version, balance_held, split,
                   pre_post_session, feedings: [{when, protein_g}]}],
     "protein": {range_low, range_high, feedings_per_day, feeding_threshold_g, feeding_target_g},
     "floors": {fat, carb, fibre},
     "titration": the week's titration record (health.titration) or None}

Every day is `health.calorie_target.resolve(...)` — the ONE calorie target, titration over charter, training-day
fuel on a typed day — exactly as the plan's `training_day_fuel` block resolves it. The day's `feedings` lay the
protein engine's own rule (the charter's feedings per day, each at or above the per-feeding threshold, the
post-session protein counted as one) out as the day's intended feedings: grams and timing only, no food names
(R5/R6 are the owner's, #5091). Nothing here is free text from a person.

THE CHECKS read the plan's fields against the charter's rules (read at grade time, never copied): a plan that does
not carry its evidence (no band, no split, no feedings, no titration decision) scores 0 on that criterion —
absence is not credit. Every check returns `(score 0-10, evidence)`.

Built on the panel defaults R1 (eat up to the band now, refit weekly) and R2 (the range in four feedings of the
threshold or more), pending the owner's answers on #5091.
"""

from __future__ import annotations

import copy
import math
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from training import panel_rubric
from training.training_charter import charter_value, charter_version

PANEL = "food"
RUBRIC_KEY = "food_panel"
LEDGER_PATH = "nutrition.concession_ledger"
WEEK_DAYS = timedelta(weeks=1).days
RESOLVED_SOURCES = ("titration", "charter")
TITRATION_ACTIONS = ("hold", "up", "down")
POST_SESSION = "post_session"
DISRUPTED = "disrupted"
# Rounding slack when the resolver's whole-gram split is turned back into kcal (three macros, each rounded).
SPLIT_TOLERANCE_KCAL = 10
DAY_FIELDS = (
    "day_type",
    "kcal",
    "base_kcal",
    "uplift_kcal",
    "band_low",
    "band_high",
    "floor_any_day_kcal",
    "floor_lifting_day_kcal",
    "source",
    "provenance",
    "charter_version",
    "balance_held",
    "split",
    "pre_post_session",
)
TITRATION_FIELDS = ("week", "action", "step_kcal", "kcal", "band_low", "band_high", "position", "reason_code", "reason")

FOOD_INSTRUCTIONS = (
    "PANEL RUBRIC JUDGE — FOOD PLAN\n\n"
    "You grade ONE week of a food plan against a fixed rubric, as a nine-seat expert panel. Each seat is a school "
    "or role in nutrition; the charter above names what each one concedes to the deadline and what it gets in return "
    "(nutrition.concession_ledger). You see the plan only — not who or what wrote it — and you must not guess.\n\n"
    "Grade ONLY the criteria listed below; every other criterion was already scored from the plan's own fields. "
    "Score each 0-10 (10 = exemplary for this person under this charter, 9 = meets the bar, 7 = a visible gap, "
    "5 = half there, 0 = absent or contrary). Judge what the plan actually prescribes, not what it says about "
    "itself. Then, per seat, say whether the plan delivers what the seat was promised in return for its concession "
    "(concession_held) and give one short reason (why) naming the day or line you judged from.\n\n"
    "Return JSON only, in the schema given. No preamble.\n\nCRITERIA TO GRADE\n"
)


def _n(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── the panel ─────────────────────────────────────────────────────────────────────────────
def view(rubric: dict[str, Any]) -> dict[str, Any]:
    """The food panel as a rubric the shared harness reads (`seats`, `letters`, `calibration`, `version`)."""
    food = rubric.get(RUBRIC_KEY) or {}
    return {
        "version": rubric.get("version"),
        "letters": rubric["letters"],
        "calibration": food.get("calibration") or {},
        "seats": food.get("seats") or {},
    }


def concession(seat: str) -> dict[str, Any] | None:
    """The seat's concession, READ from the charter's nutrition ledger at grade time (never copied into the rubric)."""
    entry = (charter_value(LEDGER_PATH, {}) or {}).get(seat)
    return dict(entry) if isinstance(entry, dict) else None


def rules() -> dict[str, float | None]:
    """The charter rules the checks grade against — read now, so a re-versioned value moves every check."""
    from health import macro_floors, protein_engine  # noqa: PLC0415 — lazy: the health engines only when grading

    return {
        "floor_any": _n(charter_value("nutrition.calories.floor_any_day_kcal")),
        "floor_lift": _n(charter_value("nutrition.calories.floor_lifting_day_kcal")),
        "floor_7d": _n(charter_value("nutrition.calories.floor_7d_mean_kcal")),
        "minimum": _n(charter_value("nutrition.calories.planned_minimum_any_weight_kcal")),
        "protein_low": _n(protein_engine.range_low()),
        "feedings": _n(charter_value("nutrition.protein.feedings_per_day")),
        "threshold": _n(charter_value("nutrition.protein.feeding_threshold_g")),
        "max_step": _n(charter_value("nutrition.titration.max_step_kcal")),
        "steps_floor": _n(charter_value("steps.floor")),
        "fat": _n(macro_floors.floor_g("fat")),
        "carb": _n(macro_floors.floor_g("carb")),
        "fibre": _n(macro_floors.floor_g("fibre")),
    }


# ── the food plan, from what the platform already resolves ────────────────────────────────
def intended_feedings(day_type: str, pre_post: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The protein engine's feeding rule as the day's intended feedings: the charter's count, each at the low end of
    the per-feeding target (raised so the day reaches the range's low end), the post-session protein counted as one
    feeding on a lifting day. Empty when the charter carries no feeding rule (absence, never a guessed rhythm)."""
    r = rules()
    n, low = int(r["feedings"] or 0), r["protein_low"]
    band = charter_value("nutrition.protein.feeding_target_g") or []
    per = _n(band[0]) if band else r["threshold"]
    if n < 1 or low is None or per is None:
        return []
    post = _n(((pre_post or {}).get("post") or {}).get("protein_g")) if day_type == "lifting" else None
    fixed = [post] if post is not None else []
    rest = n - len(fixed)
    each = max(per, math.ceil((low - sum(fixed)) / rest)) if rest else 0
    out = [{"when": "first" if i == 0 else "meal", "protein_g": int(each)} for i in range(rest)]
    out += [{"when": POST_SESSION, "protein_g": int(g)} for g in fixed]
    return out


def titration_view(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """The week's titration decision, the fields the panel reads (a DynamoDB record's Decimals become floats)."""
    if not isinstance(record, dict):
        return None
    out: dict[str, Any] = {}
    for k in TITRATION_FIELDS:
        v = record.get(k)
        out[k] = _n(v) if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) else v
    raw = record.get("inputs")
    inputs: dict[str, Any] = raw if isinstance(raw, dict) else {}
    out["inputs"] = {"steps_avg": _n(inputs.get("steps_avg")), "steps_floor": _n(inputs.get("steps_floor"))}
    return out


def build_food_plan(
    week_start: str,
    *,
    planned_dates: list[str] | None = None,
    disruption: dict[str, Any] | None = None,
    disruption_records: list[dict[str, Any]] | None = None,
    titration_reader: Callable[[str], dict[str, Any] | None] | None = None,
    case_id: str | None = None,
    block_workouts: list[dict[str, Any]] | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """The week's food plan as the platform resolves it: 7 x `calorie_target.resolve` (titration over charter, the
    day typed lifting/rest, training-day fuel) + the intended feedings + the protein rule, the macro floors and the
    week's titration record. `titration_reader(iso_monday)` is injected (the MCP job wires the table); with none, no
    record is read and every day resolves from the charter. With `block_workouts` (the Hevy record) the days are typed
    by the per-date calendar (`training_calendar`, #5191; `today` splits credited from planned) and supersede
    `planned_dates` (the committed routines' dates, the fallback).

    `disruption_records` (#5215; the #5088 records, read by the caller through `disruption.load_records_failsoft`):
    a date inside an ACTIVE record is typed `disrupted`, ahead of the calendar/routine-derived type and the travel
    window; the panel's code half then grades that day as the minimum viable day. A record outside the week changes
    nothing."""
    from health import calorie_target  # noqa: PLC0415

    from training import disruption as disruption_mode  # noqa: PLC0415

    reader = titration_reader or (lambda week: None)
    start = datetime.strptime(str(week_start)[:10], "%Y-%m-%d").date()  # a calendar-day key, not an instant
    dates = [(start + timedelta(days=i)).isoformat() for i in range(WEEK_DAYS)]
    planned = [str(d)[:10] for d in planned_dates or [] if d] if planned_dates is not None else None
    if block_workouts is not None:
        from common.pacific_time import shift_day_key  # noqa: PLC0415

        from training import training_calendar  # noqa: PLC0415

        after = today or shift_day_key(dates[-1], 1)  # default: a retrospective week, every date typed by its credit
        cal = training_calendar.planned_dates_over(dates, training_calendar.credited_dates(block_workouts, dates[-1]), after)
        planned = cal if cal is not None else planned
    types = [calorie_target.classify_day_type(d, planned_dates=planned, disruption=disruption)["day_type"] for d in dates]
    modes = [disruption_mode.state(disruption_records, d) for d in dates] if disruption_records else []
    for i, st in enumerate(modes):
        if st.get("phase") == disruption_mode.PHASE_ACTIVE:
            types[i] = DISRUPTED
    days = []
    for i, (d, t) in enumerate(zip(dates, types)):
        r = calorie_target.resolve(d, titration_reader=reader, day_type=t, week_day_types=types)
        row = {"date": d, **{k: r.get(k) for k in DAY_FIELDS}}
        if t == DISRUPTED:
            row["disruption_template"] = modes[i].get("template")
        row["feedings"] = intended_feedings(t, r.get("pre_post_session"))
        days.append(row)
    r = rules()
    band = charter_value("nutrition.protein.feeding_target_g")
    return {
        "case_id": case_id or f"food::{dates[0]}",
        "panel": PANEL,
        "week_start": dates[0],
        "charter_version": charter_version(),
        "days": days,
        "protein": {
            "range_low": r["protein_low"],
            "range_high": _n(charter_value("nutrition.protein.range_g.high")),
            "feedings_per_day": r["feedings"],
            "feeding_threshold_g": r["threshold"],
            "feeding_target_g": list(band) if isinstance(band, list) else None,
        },
        "floors": {"fat": r["fat"], "carb": r["carb"], "fibre": r["fibre"]},
        "titration": titration_view(reader(calorie_target.week_monday(dates[0]))),
    }


# ── the checks: (features) -> (score 0-10, evidence) ──────────────────────────────────────
def plan_features(case: dict[str, Any]) -> dict[str, Any]:
    days = [d for d in case.get("days") or [] if isinstance(d, dict)]
    return {
        "days": days,
        "lifting": [d for d in days if d.get("day_type") == "lifting"],
        "protein": case.get("protein") or {},
        "floors": case.get("floors") or {},
        "titration": case.get("titration") if isinstance(case.get("titration"), dict) else None,
        "rules": rules(),
    }


def _share(n: int, d: int) -> float:
    return panel_rubric._share(n, d)


def _over_week(ok: int, f: dict[str, Any]) -> float:
    """A week-level share: a plan with fewer than seven days is graded over seven (a missing day is not credit)."""
    return _share(ok, max(len(f["days"]), WEEK_DAYS))


def _feeding_g(day: dict[str, Any]) -> list[float]:
    return [g for g in (_n(x.get("protein_g")) for x in day.get("feedings") or [] if isinstance(x, dict)) if g is not None]


def check_target_resolved(f: dict[str, Any]) -> tuple[float, str]:
    ok = [d for d in f["days"] if _n(d.get("kcal")) and d.get("source") in RESOLVED_SOURCES]
    srcs = sorted({str(d.get("source")) for d in f["days"]})
    return _over_week(len(ok), f), f"{len(ok)} of {len(f['days'])} days resolved by the one calorie resolver (sources {srcs})"


def check_in_band(f: dict[str, Any]) -> tuple[float, str]:
    def inside(d: dict[str, Any]) -> bool:
        base, lo, hi = _n(d.get("base_kcal")), _n(d.get("band_low")), _n(d.get("band_high"))
        return base is not None and lo is not None and hi is not None and lo <= base <= hi

    ok = [d for d in f["days"] if inside(d)]
    return _over_week(len(ok), f), f"{len(ok)} of {len(f['days'])} days have a base target inside their stated band"


def _floor_for(d: dict[str, Any], r: dict[str, Any]) -> float | None:
    return r["floor_lift"] if d.get("day_type") == "lifting" and r["floor_lift"] is not None else r["floor_any"]


def check_day_floors(f: dict[str, Any]) -> tuple[float, str]:
    r = f["rules"]
    under = [
        f"{d.get('date')} {d.get('kcal')!r}" for d in f["days"] if _floor_for(d, r) is None or (_n(d.get("kcal")) or 0) < _floor_for(d, r)
    ]
    ok = len(f["days"]) - len(under)
    return _over_week(ok, f), f"{ok} of {len(f['days'])} days at or above their floor" + (f"; under: {under[:7]}" if under else "")


def check_week_floor(f: dict[str, Any]) -> tuple[float, str]:
    kcal = [_n(d.get("kcal")) for d in f["days"]]
    known = [k for k in kcal if k is not None]
    floor = f["rules"]["floor_7d"]
    if floor is None or len(known) < WEEK_DAYS:
        return 0.0, f"{len(known)} days with a target; seven-day floor {floor!r} — not gradeable"
    mean = sum(known) / len(known)
    return (10.0 if mean >= floor else 0.0), f"week mean {round(mean)} kcal against the seven-day floor {int(floor)}"


def check_protein_range(f: dict[str, Any]) -> tuple[float, str]:
    low, plan_low = f["rules"]["protein_low"], _n(f["protein"].get("range_low"))
    if low is None or plan_low is None or plan_low < low:
        return 0.0, f"the plan's protein range low {plan_low!r} does not carry the charter's {low!r}"
    ok = [d for d in f["days"] if (_n((d.get("split") or {}).get("protein_g")) or 0) >= low]
    return _over_week(len(ok), f), f"{len(ok)} of {len(f['days'])} days plan protein at or above the range low {low:g} g"


def minimum_day_held(d: dict[str, Any], r: dict[str, Any]) -> bool:
    """The reduced day a disruption mode grades (#5215): the mode HOLDS the protein floor (charter `disruption.holds`),
    so a disrupted day is met when it plans a resolved target at the any-day calorie floor and the protein range's low
    end — no four feedings, no fat or carbohydrate floor. While the charter's floors are WARNINGS (`floor_role`, owner
    ruling 2026-10-23 R1: the ~1,500 target sits under the 1,600 floor by choice) the calorie half is a resolved target;
    the floor gap stays visible in `day_floors_held`. Absent evidence is not met."""
    kcal, floor, low = _n(d.get("kcal")), r["floor_any"], r["protein_low"]
    protein = _n((d.get("split") or {}).get("protein_g"))
    warning = charter_value("nutrition.calories.floor_role") == "warning"
    kcal_ok = kcal is not None and (warning or (floor is not None and kcal >= floor))
    return low is not None and kcal_ok and protein is not None and protein >= low


def _reduced(d: dict[str, Any]) -> bool:
    return d.get("day_type") == DISRUPTED


def _note(f: dict[str, Any]) -> str:
    n = sum(1 for d in f["days"] if _reduced(d))
    return f"; {n} disrupted day(s) graded as the minimum viable day" if n else ""


def check_four_feedings(f: dict[str, Any]) -> tuple[float, str]:
    want, thr = f["rules"]["feedings"], f["rules"]["threshold"]
    if not want or thr is None:
        return 0.0, "the charter carries no feeding rule"
    ok = [d for d in f["days"] if (minimum_day_held(d, f["rules"]) if _reduced(d) else sum(1 for g in _feeding_g(d) if g >= thr) >= want)]
    return _over_week(len(ok), f), f"{len(ok)} of {len(f['days'])} days plan {int(want)} feedings at or above {thr:g} g{_note(f)}"


def check_feedings_cover(f: dict[str, Any]) -> tuple[float, str]:
    low = f["rules"]["protein_low"]
    ok = [
        d
        for d in f["days"]
        if (minimum_day_held(d, f["rules"]) if _reduced(d) else low is not None and _feeding_g(d) and sum(_feeding_g(d)) >= low)
    ]
    return _over_week(len(ok), f), f"{len(ok)} of {len(f['days'])} days whose feedings add up to the range low {low!r} g{_note(f)}"


def check_post_session(f: dict[str, Any]) -> tuple[float, str]:
    thr = f["rules"]["threshold"]
    if not f["lifting"] or thr is None:
        return 0.0, f"{len(f['lifting'])} lifting days typed on the plan — no post-session feeding to grade"

    def fed(d: dict[str, Any]) -> bool:
        post = (d.get("feedings") or []) and [x for x in d["feedings"] if x.get("when") == POST_SESSION]
        stated = _n((((d.get("pre_post_session") or {}).get("post")) or {}).get("protein_g"))
        return bool(post) and stated is not None and stated >= thr and all((_n(x.get("protein_g")) or 0) >= thr for x in post)

    ok = [d for d in f["lifting"] if fed(d)]
    return _share(len(ok), len(f["lifting"])), f"{len(ok)} of {len(f['lifting'])} lifting days count a post-session feeding at {thr:g} g"


def check_macro_floors(f: dict[str, Any]) -> tuple[float, str]:
    r = f["rules"]
    if r["fibre"] is None or (_n(f["floors"].get("fibre")) or 0) < r["fibre"]:
        return 0.0, f"the plan does not carry the fibre floor ({f['floors'].get('fibre')!r} vs {r['fibre']!r})"
    miss, short_days = [], set()
    for d in f["days"]:
        if _reduced(d) and minimum_day_held(d, r):
            continue
        s = d.get("split") or {}
        for macro, key in (("fat", "fat_g"), ("carb", "carb_g")):
            if r[macro] is None or (_n(s.get(key)) or 0) < r[macro]:
                miss.append(f"{d.get('date')} {macro} {s.get(key)!r}")
                short_days.add(d.get("date"))
    ok = len(f["days"]) - len(short_days)
    return _over_week(ok, f), f"{ok} of {len(f['days'])} days hold the fat and carbohydrate floors{_note(f)}" + (
        f"; under: {miss[:7]}" if miss else ""
    )


def check_training_day_fuel(f: dict[str, Any]) -> tuple[float, str]:
    if not f["lifting"]:
        return 0.0, "no lifting day typed on the plan — training-day fuel cannot be read"
    ok = [d for d in f["lifting"] if (_n(d.get("uplift_kcal")) or 0) > 0 and isinstance(d.get("pre_post_session"), dict)]
    return _share(len(ok), len(f["lifting"])), f"{len(ok)} of {len(f['lifting'])} lifting days carry an uplift and pre/post session fuel"


def check_week_balanced(f: dict[str, Any]) -> tuple[float, str]:
    kcal = [k for k in (_n(d.get("kcal")) for d in f["days"]) if k is not None]
    base = [b for b in (_n(d.get("base_kcal")) for d in f["days"]) if b is not None]
    if len(f["days"]) < WEEK_DAYS or len(kcal) != len(f["days"]) or len(base) != len(f["days"]):
        return 0.0, f"{len(f['days'])} days, some without a target — the week's balance cannot be read"
    gap = abs(sum(kcal) - sum(base)) / WEEK_DAYS
    held = all(d.get("balance_held") is True for d in f["days"])
    ok = held and gap <= SPLIT_TOLERANCE_KCAL
    return (10.0 if ok else 0.0), f"the week averages {round(gap)} kcal/day off its base; every day balance_held = {held}"


def check_split_accounts(f: dict[str, Any]) -> tuple[float, str]:
    def adds_up(d: dict[str, Any]) -> bool:
        s, k = d.get("split") or {}, _n(d.get("kcal"))
        p, fat, c = (_n(s.get(x)) for x in ("protein_g", "fat_g", "carb_g"))
        if p is None or fat is None or c is None or k is None:
            return False
        return abs(4 * p + 9 * fat + 4 * c - k) <= SPLIT_TOLERANCE_KCAL

    ok = [d for d in f["days"] if adds_up(d)]
    return _over_week(len(ok), f), f"{len(ok)} of {len(f['days'])} days whose protein, fat and carbohydrate add up to the day's kcal"


def check_titration_decided(f: dict[str, Any]) -> tuple[float, str]:
    t = f["titration"]
    if not t or t.get("action") not in TITRATION_ACTIONS or not t.get("reason"):
        return 0.0, "no titration decision with a reason on the week"
    return 10.0, f"titration {t.get('action')} ({t.get('reason_code')})"


def check_titration_bounded(f: dict[str, Any]) -> tuple[float, str]:
    t, r = f["titration"], f["rules"]
    if not t:
        return 0.0, "no titration decision on the week"
    step, kcal = abs(_n(t.get("step_kcal")) or 0), _n(t.get("kcal"))
    ok = r["max_step"] is not None and step <= r["max_step"] and kcal is not None and (r["minimum"] is None or kcal >= r["minimum"])
    return (10.0 if ok else 0.0), f"step {step:g} kcal (cap {r['max_step']!r}), target {kcal!r} (planned minimum {r['minimum']!r})"


def check_steps_before_food(f: dict[str, Any]) -> tuple[float, str]:
    t, floor = f["titration"], f["rules"]["steps_floor"]
    if not t:
        return 0.0, "no titration decision on the week"
    inputs = t.get("inputs") or {}
    if floor is None or _n(inputs.get("steps_floor")) != floor:
        return 0.0, f"the decision's steps floor {inputs.get('steps_floor')!r} is not the charter's {floor!r}"
    if t.get("action") == "down" and (_n(inputs.get("steps_avg")) or 0) < floor:
        return 0.0, f"food came down with steps {inputs.get('steps_avg')!r} under the floor"
    return 10.0, f"steps floor carried ({int(floor)}); action {t.get('action')}"


def check_reasons(f: dict[str, Any]) -> tuple[float, str]:
    ok = [d for d in f["days"] if d.get("provenance") and d.get("charter_version")]
    t = f["titration"]
    unexplained = bool(t) and not t.get("reason")
    score = 0.0 if unexplained else _over_week(len(ok), f)
    return score, f"{len(ok)} of {len(f['days'])} days carry their source and charter version" + (
        "; the titration has no reason" if unexplained else ""
    )


CHECKS: dict[str, Callable[[dict[str, Any]], tuple[float, str]]] = {
    "calorie_target_resolved": check_target_resolved,
    "week_in_band": check_in_band,
    "day_floors_held": check_day_floors,
    "week_mean_floor": check_week_floor,
    "protein_range_every_day": check_protein_range,
    "four_feedings_planned": check_four_feedings,
    "feedings_cover_the_range": check_feedings_cover,
    "post_session_feeding": check_post_session,
    "macro_floors_held": check_macro_floors,
    "training_day_fuel": check_training_day_fuel,
    "week_balanced": check_week_balanced,
    "split_accounts_for_kcal": check_split_accounts,
    "titration_decided": check_titration_decided,
    "titration_step_bounded": check_titration_bounded,
    "steps_before_food": check_steps_before_food,
    "numbers_carry_their_reason": check_reasons,
}


def prescore(case: dict[str, Any], rubric: dict[str, Any]) -> dict[str, Any]:
    """Every CODE criterion of every food seat. Seat -> criterion id -> {score, evidence, by}."""
    feats = plan_features(case)
    out: dict[str, dict[str, Any]] = {}
    for seat, spec in view(rubric)["seats"].items():
        out[seat] = {}
        for c in spec["criteria"]:
            if c.get("by") == panel_rubric.BY_CODE:
                score, evidence = CHECKS[c["check"]](feats)
                out[seat][c["id"]] = {"score": round(float(score), 1), "evidence": evidence, "by": panel_rubric.BY_CODE}
    return out


# ── what the judge sees: the plan, blinded ────────────────────────────────────────────────
def _g(v: Any) -> str:
    n = _n(v)
    return "?" if n is None else f"{n:g}"


def _fuel_line(pp: dict[str, Any] | None) -> str:
    if not isinstance(pp, dict):
        return ""
    pre, post = pp.get("pre") or {}, pp.get("post") or {}
    win = pre.get("minutes_before") or []
    when = f" {_g(win[0])}-{_g(win[-1])} min before" if win else ""
    return (
        f"; pre-session {_g(pre.get('carb_g'))} g carbohydrate + {_g(pre.get('protein_g'))} g protein{when}"
        f"; post-session {_g(post.get('carb_g'))} g carbohydrate + {_g(post.get('protein_g'))} g protein within {_g(post.get('minutes_after'))} min"
    )


_ENGINE_STAMP = re.compile(r"[\w.-]+@\d[\w.]*|\b\d+\.\d+\.\d+\b")


def _blind(text: str) -> str:
    """The training scrub (issue numbers, versions, engine words) plus `name@x.y.z` stamps and bare versions."""
    return panel_rubric._scrub(_ENGINE_STAMP.sub("", str(text or "")))


def blind_text(case: dict[str, Any]) -> str:
    """The food plan as a judge reads it: the rule, each day's target, split, feedings and session fuel, the week's
    refit — and NOTHING that names an engine, a version, an issue or a record key (provenance is not rendered)."""
    p, fl = case.get("protein") or {}, case.get("floors") or {}
    band = p.get("feeding_target_g") or []
    lines = [
        "FOOD PLAN — one week",
        f"  protein rule: {_g(p.get('range_low'))}-{_g(p.get('range_high'))} g a day in {_g(p.get('feedings_per_day'))} feedings "
        f"of {_g(p.get('feeding_threshold_g'))} g or more" + (f" (target {_g(band[0])}-{_g(band[-1])} g each)" if band else ""),
        f"  floors: fat {_g(fl.get('fat'))} g, carbohydrate {_g(fl.get('carb'))} g, fibre {_g(fl.get('fibre'))} g",
    ]
    for i, d in enumerate(case.get("days") or []):
        s = d.get("split") or {}
        fed = "/".join(
            f"{_g(x.get('protein_g'))}{' (post-session)' if x.get('when') == POST_SESSION else ''}" for x in d.get("feedings") or []
        )
        band_txt = f"band {_g(d.get('band_low'))}-{_g(d.get('band_high'))}" if d.get("band_low") is not None else "no band"
        split = f"protein {_g(s.get('protein_g'))} g, fat {_g(s.get('fat_g'))} g, carbohydrate {_g(s.get('carb_g'))} g" if s else "no split"
        lines.append(
            f"  DAY {i + 1} ({d.get('day_type') or 'unknown'}): {_g(d.get('kcal'))} kcal (base {_g(d.get('base_kcal'))}, "
            f"{band_txt}; from {d.get('source') or 'unstated'}) — {split}; feedings {fed or 'none planned'}{_fuel_line(d.get('pre_post_session'))}"
        )
    t = case.get("titration") or {}
    lines.append("WEEK CONTEXT")
    lines.append(
        f"  weekly refit: {t.get('action')} — {_blind(str(t.get('reason') or ''))}; step {_g(t.get('step_kcal'))} kcal"
        if t
        else "  weekly refit: none on file"
    )
    return "\n".join(lines)


def build_body(case: dict[str, Any], rubric: dict[str, Any], route: str) -> dict[str, Any]:
    """The Messages body for one food plan: the cached charter block, the food rubric, the blinded plan."""
    from training import charter_ai, panel_judge  # noqa: PLC0415 — panel_judge imports this module

    v = view(rubric)
    return {
        "max_tokens": panel_judge.MAX_TOKENS,
        "temperature": 0,
        "system": charter_ai.system_blocks(route, FOOD_INSTRUCTIONS + panel_judge.criteria_text(v)),
        "messages": [{"role": "user", "content": "FOOD PLAN UNDER REVIEW\n\n" + blind_text(case)}],
    }


# ── the grade ─────────────────────────────────────────────────────────────────────────────
def grade_case(
    case: dict[str, Any],
    rubric: dict[str, Any],
    *,
    route: str | None = None,
    call: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The full grade of one food plan: the code pre-score, the shared judge, the combination (food concessions)."""
    from training import panel_judge  # noqa: PLC0415

    route = route or panel_judge.WEEKLY_ROUTE
    v = view(rubric)
    graded = panel_judge.grade_scored(
        case, v, prescore(case, rubric), build_body(case, rubric, route), route=route, call=call, concession_of=concession
    )
    graded["panel"] = PANEL
    return graded


def _flat_constant(case: dict[str, Any]) -> None:
    """The retired shape: one flat number under the any-day floor every day, no band, no split, no feedings, no refit."""
    r = rules()
    flat = (r["floor_any"] or 0) - (r["max_step"] or 0)
    for d in case.get("days") or []:
        d.update(kcal=flat, base_kcal=flat, uplift_kcal=0, band_low=None, band_high=None, source="constant", provenance="")
        d.update(split=None, pre_post_session=None, feedings=[], balance_held=None)
    case["protein"], case["titration"] = {}, None


def _no_refit_no_fuel(case: dict[str, Any]) -> None:
    """No weekly titration decision and every day untyped: the base every day, no session fuel."""
    case["titration"] = None
    for d in case.get("days") or []:
        d.update(day_type="unknown", kcal=d.get("base_kcal"), uplift_kcal=0, pre_post_session=None)
        d["feedings"] = [dict(x, when="meal") if x.get("when") == POST_SESSION else x for x in d.get("feedings") or []]


# name -> (the mutation, the food criteria it MUST fail). The golden fixtures carry hand-built controls of the same
# defects; tests hold that both paths fail the same criteria.
CONTROL_MUTATIONS: dict[str, tuple[Callable[[dict[str, Any]], None], tuple[str, ...]]] = {
    "flat_constant_no_protein_structure": (
        _flat_constant,
        ("energy_balance_metabolism.in_band", "protein_lean_mass.four_feedings", "obesity_medicine.day_floors"),
    ),
    "no_refit_no_fuel": (_no_refit_no_fuel, ("energy_balance_metabolism.weekly_refit", "sports_dietitian.training_day_fuel")),
}


def negative_controls(case: dict[str, Any]) -> list[dict[str, Any]]:
    """The real food plan made bad (copies — the plan itself is untouched). Each must FAIL the target."""
    out = []
    for name, (mutate, must_fail) in CONTROL_MUTATIONS.items():
        c = copy.deepcopy(case)
        mutate(c)
        c["case_id"] = f"{case.get('case_id') or 'food'}::control::{name}"
        c["expect_fail"] = list(must_fail)
        out.append(c)
    return out


def grade_week(
    plan: dict[str, Any],
    rubric: dict[str, Any],
    *,
    call: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    route: str | None = None,
) -> dict[str, Any]:
    """The weekly food grade: the real plan, then each negative control, back-to-back on the same route."""
    from training import panel_judge  # noqa: PLC0415

    real = grade_case(plan, rubric, route=route, call=call)
    controls = []
    for c in negative_controls(plan):
        g = grade_case(c, rubric, route=route, call=call)
        controls.append(
            {
                "control": c["case_id"].split("::")[-1],
                "target_met": g["target_met"],
                "missed": panel_judge.failed_expectations(g, c["expect_fail"]),
            }
        )
    leaky = [c["control"] for c in controls if c["missed"]]
    if leaky:
        real["degraded_reasons"].append(f"food negative control(s) passed what they must fail: {leaky}")
    real.update(controls=controls, degraded=bool(real["degraded_reasons"]) or real["degraded"], week_start=plan.get("week_start"))
    return real


def row_summary(grade: dict[str, Any] | None) -> dict[str, Any] | None:
    """The food half of the weekly PANEL# row: scores, letters, reasons and controls — never the plan itself."""
    if not grade:
        return None
    return {
        "overall_score": (grade.get("overall") or {}).get("score"),
        "overall_letter": (grade.get("overall") or {}).get("letter"),
        "target_met": grade.get("target_met"),
        "seat_scores": {s: v["score"] for s, v in (grade.get("seats") or {}).items()},
        "seats": grade.get("seats"),
        "seats_below_floor": grade.get("seats_below_floor"),
        "concessions_unnamed": grade.get("concessions_unnamed"),
        "degraded": grade.get("degraded"),
        "degraded_reasons": grade.get("degraded_reasons"),
        "controls": grade.get("controls"),
        "judge": grade.get("judge"),
        "calibration": grade.get("calibration"),
    }
