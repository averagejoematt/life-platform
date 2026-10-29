"""health/weekly_menu.py — the weekly menu, built by code from the owner's anchor foods (#5103 N9, epic #5092).

WHY THIS EXISTS

Meal planning was two model-written emails prompted with a calorie number; no code checked a macro and no menu existed
before the week started. This module builds the week's food BY CONSTRUCTION: every day is a deterministic fit of the
owner's own anchor foods to that day's resolved target, so the menu hits the numbers because the code put them there,
and a day the anchors cannot fit says so with each miss named.

WHERE EVERY NUMBER COMES FROM (none is restated here)

  * the DAY: `training.food_panel.build_food_plan` — seven `health.calorie_target.resolve` days (titration over charter,
    each typed lifting/rest by the training calendar, the lifting uplift on a lifting day, the pre/post session fuel);
  * the RULES: the charter's protein range low, feedings per day, feeding threshold, the fat/carbohydrate/fibre floors,
    the eating window and the prescribed band's width (read through `health.travel_food.targets`, the same reader the
    travel kit uses), and `nutrition.weekly_menu` (the cook days, R6; the off-limits switch, R7; the anchor minimum and
    the serving caps — platform defaults named as such in the charter);
  * the FOODS: the owner's anchor-food table, the `anchor_foods` key of the owner-only charter twin
    (`training.training_charter`: env -> gitignored local file -> owner-private S3; the committed
    `config/training_charter.private.example.json` documents the row shape with nulls). The repo is PUBLIC: no anchor
    food is ever in a tracked file, and the tests use invented placeholder foods.

THE FIT (per day, deterministic — the same plan and table always give the same menu)

  1. FEEDING CORES: every combination of at most `core_anchors_max` anchors whose protein reaches the feeding threshold
     (the post-session feeding on a lifting day: the larger of the threshold and the post-session protein), at the
     fewest servings that reach it and at most one feeding's share of the day's kcal, sorted by kcal (the most
     protein-dense first). A day starts with one core per feeding, rotated through the cheapest cores by the day's
     position in the week (variety), inside the per-day serving caps.
  2. THE SEARCH: a best-improvement local search over the day — a side serving added or removed, one food traded for
     one or two others (or two for one), or one feeding's core replaced — minimising (the miss, the distance): the miss
     is the floor shortfall at the Atwater rate (a gram of protein, carbohydrate or fibre short costs 4 kcal, fat 9: the
     travel kit's exchange rate) plus the kcal outside the day's band; the distance from the day's kcal breaks ties.
     A day whose own rotation ends unfit is searched again from the next rotations; the first that fits is the day.
  2b. THE EXACT SEARCH (`_exact_day`, #5103 search quality): when no rotation fits, a local optimum is not evidence
     that no better set exists (the synthetic proof of 2026-10-29 found days on which a set missing by far less existed
     than the one the local search stopped at). So the day is searched exactly: every assignment of one core per feeding, and for each a
     branch-and-bound over every side serving count of every anchor, cut only where a bound proves no completion can
     beat the best set found (a fractional-knapsack bound on the floors against the band). The result is the day's one
     best set under a total order (the miss, the distance, the servings, the counts in id order): a fit when any set
     fits, else the least miss any set of the anchors can reach — the same input always gives the same set. Its node
     budget (per day and per build) bounds the time; a day that reaches it keeps the best found and says so.
  3. THE CHECK: kcal inside the day's band (the resolved kcal +/- half the prescribed band's width), protein at the
     range low, every feeding at its threshold, every floor met. `fits` is all of them; `misses` names each one short.

THE FOOD-QUALITY TARGETS (#5105, `nutrition.food_quality`, read and checked by `health.food_quality`): the fibre floor is
one of the day's floors above (the ONE fibre floor); the fatty-fish weekly range is enforced across the week — every day
is fitted with the fatty-fish anchors (rows tagged `fatty_fish: true`) kept off it, then the range's low end is placed
as one pinned serving on each of that many days (`_fit_week`), ALWAYS (trading the target away for a day's fit is an
owner ruling, not the fitter's), on the days where it costs least (`_fish_cost`: a day that still fits first, else the
smallest miss it adds; the spread breaks ties); a day it leaves unfit names its misses like any unfit day, and only a
serving no free day can take at all is left unplaced, with the reason on the report's short count. The owner-only
lab-driven priorities row, when the caller holds it, rides the report. The menu's `quality` names every target the week
misses (`quality.misses`) and every unreadable one (`quality.problems`) — never silently — and `food_plan` carries the
rows the food panel checks the same way.

The feedings are laid inside the one eating window (`nutrition.eating_window`): feeding i opens at i x (eating hours /
feedings) hours after the window opens, so all of them sit inside it. On a lifting day one feeding is the post-session
feeding (it moves with the session; the window offset is where it sits when the session is mid-window).

NO MODEL CALL. The issue's box is "AI writes prose only; numbers come from code"; this module writes no prose a model
would add value to, so there is no Bedrock call and no budget class — the menu's lines are templates over the code's
numbers (`lines`). The grocery list (#5104 box 1, "generated from the menu") reads the cook days of this menu, skips the trip's travel
days (their food is the travel kit's) and is rendered beside the menu in `lines` (grouped by the anchor's optional
`section` column).

THE FIXED MEALS (owner ruling 2026-10-26, Session CH: "Plan around the Fuller dinner"): from the week of 2026-10-25
the owner eats a prepared meal-service dinner every day, one container whose printed label is the truth. The
owner-only twin's `fixed_meals` key (`training.training_charter`, the same channel as the anchors) lists each fixed
feeding: `id`, `label`, `slot` (dinner = the day's last feeding; breakfast = its first), the label values (`kcal`,
`protein_g`, `carb_g`, `fat_g`; `fibre_g` may be null — unknown, counted as none, so the anchors carry the whole fibre
floor), `days` (the weekday names it applies to) and `source` (free text). On a day it applies to, the fixed feeding is
subtracted from the day's band and floors before the cores and the search (`targets.remaining`), counts as ONE of the
charter's feedings (the four feedings of 40 g+ stand: the anchors build the others, and the cores are sized to the
remainder's share), sits in its slot inside the window, and is rendered as fixed ("log its printed label"). It is never
moved, shrunk or dropped: a remainder the anchors cannot fit is a day marked unfit with each miss named (the fixed meal
named first), and an unreadable fixed row refuses the menu (`fixed_meal_unreadable`) rather than plan a day of food on
top of a dinner it cannot see. No `fixed_meals` key (or an empty list) is the menu exactly as before. The quality rows
and the food panel's plan carry the fixed feeding with its nutrition, so both grade the whole day.

OWNER-ONLY. The menu carries his foods: it is served on the owner's MCP read (`get_exercise_notes action='weekly_menu'`)
and nowhere public.
"""

from __future__ import annotations

import bisect
import copy
import itertools
import json
import logging
import math
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from health import food_quality, travel_food

logger = logging.getLogger(__name__)

VERSION = "weekly-menu@1.4.0"  # 1.4.0 #5103/#5105: the exact day search and fish on its least-cost days; 1.3.0 #5104: the grocery list skips travel days and is rendered in `lines`; 1.2.0 #5103: the fixed meals (a fixed dinner planned around); 1.1.0 #5105: food quality
ISSUE = "#5103"
POLICY_PATH = "nutrition.weekly_menu"
ANCHORS_PATH = "anchor_foods"  # the owner-only twin's key (training_charter.PRIVATE_KEYS)
FIXED_PATH = "fixed_meals"  # the owner-only twin's fixed feedings (training_charter.PRIVATE_KEYS) — the meal-service dinner
FIXED = "fixed"  # the `when` of a fixed feeding
# Where a fixed feeding sits among the day's feedings: breakfast is the first, dinner the last.
SLOTS = ("breakfast", "dinner")
FIXED_REQUIRED = ("kcal", "protein_g", "carb_g", "fat_g")  # fibre_g may be null (unknown; counted as none)
MACROS = travel_food.MACROS  # kcal, protein_g, carb_g, fat_g, fibre_g
GRAMS = ("protein_g", "carb_g", "fat_g", "fibre_g")
# The exchange rate between a floor gram short and a calorie: the Atwater factors (fibre at the carbohydrate rate, as
# the travel kit's search prices it). A physical constant of the search, not a target.
ATWATER = {"protein_g": 4.0, "carb_g": 4.0, "fat_g": 9.0, "fibre_g": 4.0}
# Bound on the local search (moves taken per day); every move strictly lowers the cost, so it ends far sooner.
MAX_MOVES = 400
# Bounds on the exact search (`_exact_day`), in branch-and-bound nodes (~20 microseconds each): per day, and shared by
# every exact search one menu build runs (the week's days and its fatty-fish trials), so a build's search time has a
# ceiling whatever the table. A real day ends far below either (tests/test_weekly_menu_search_5103.py measures it); a
# day that reaches one keeps the best set found so far and says the search stopped.
EXACT_NODE_BUDGET = 60_000
WEEK_NODE_BUDGET = 240_000
POST_SESSION = "post_session"
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SERVICE_COOK, SERVICE_MEAL = "cook", "meal_service"
TRAVEL_DAY = "travel"  # the plan's `day_type` on a travel-window / travel-disruption date (health.calorie_target.resolve)

# The named reasons a menu is not built (built=False) or a day does not fit. A caller states the reason; it never
# substitutes a remembered menu.
NO_ANCHOR_TABLE = "no_anchor_table"
TOO_FEW_ANCHORS = "too_few_anchors"
NO_FEEDING_CORE = "no_feeding_core"
NO_CALORIE_TARGET = "no_calorie_target"
NO_POLICY = "no_policy"
NO_PLAN = "no_plan"
DAY_UNFIT = "day_unfit"
FIXED_MEAL_UNREADABLE = "fixed_meal_unreadable"
REASON_CODES = (NO_ANCHOR_TABLE, TOO_FEW_ANCHORS, NO_FEEDING_CORE, NO_CALORIE_TARGET, NO_POLICY, NO_PLAN, DAY_UNFIT, FIXED_MEAL_UNREADABLE)

CharterReader = Callable[[str], Any]
Counts = dict[str, int]


def _default_reader(dotted: str) -> Any:
    from training.training_charter import charter_value  # noqa: PLC0415 — lazy: import-safe offline

    return charter_value(dotted)


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None and n.is_integer() and n > 0 else None


# ── the policy and the anchor table ───────────────────────────────────────────────────────────────────────────
def policy(read: Optional[CharterReader] = None) -> dict[str, Any]:
    """The charter's `nutrition.weekly_menu` block, the numbers checked: `{cook_days, min_anchors, cap, core_max}`, or
    `{}` when any is unreadable (the menu is then not built, reason no_policy — never a guessed cap)."""
    v = (read or _default_reader)(POLICY_PATH)
    block = v if isinstance(v, dict) else {}
    cook = [d for d in block.get("cook_days") or [] if d in WEEKDAY_NAMES]
    out = {
        "cook_days": cook,
        "min_anchors": _int(block.get("min_anchors")),
        "cap": _int(block.get("max_servings_per_anchor_per_day")),
        "core_max": _int(block.get("core_anchors_max")),
    }
    return out if None not in out.values() else {}


def parse_anchors(raw: Any, cap: int) -> tuple[list[dict[str, Any]], list[str]]:
    """The usable anchors and one line per row set aside (no id, a duplicate id, a missing or negative label value,
    no calories, or marked off_limits — R7's switch). A row's own `max_per_day` replaces the charter's default cap for
    that food (his table knows a vegetable from a shake). The lines name the row by its id only (an id is the owner's
    key, not a food name)."""
    usable: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(raw if isinstance(raw, list) else []):
        rid = str((row or {}).get("id") or "").strip() if isinstance(row, dict) else ""
        tag = rid or f"row {i}"
        if not rid:
            problems.append(f"{tag}: no id")
            continue
        if rid in seen:
            problems.append(f"{tag}: duplicate id")
            continue
        seen.add(rid)
        vals = {m: _num(row.get(m)) for m in MACROS}
        bad = [m for m, v in vals.items() if v is None or v < 0]
        if bad or not vals["kcal"]:
            problems.append(f"{tag}: unreadable label value(s) {bad or ['kcal']}")
            continue
        if row.get("off_limits") is True:
            problems.append(f"{tag}: off_limits (never placed)")
            continue
        own = _int(row.get("max_per_day"))
        pkg = row.get("package") if isinstance(row.get("package"), dict) else {}
        usable.append(
            {
                "id": rid,
                "label": str(row.get("label") or rid),
                "serving": str(row.get("serving") or "1 serving"),
                **{m: float(v or 0.0) for m, v in vals.items()},
                "cap": own or cap,
                "package": {"label": pkg.get("label"), "servings": _num(pkg.get("servings"))},
                "section": str(row.get("section") or "").strip() or None,  # #5104: the store section (optional column)
                **food_quality.tags(row),  # #5105: fatty_fish, nutrient_tags (optional columns)
            }
        )
    usable.sort(key=lambda a: a["id"])
    return usable, problems


def _weekdays(raw: Any) -> Optional[list[str]]:
    """A fixed row's `days` as weekday names in week order (a full name or its first three letters, any case), or None
    when the list is empty, not a list, or names something that is not a weekday."""
    if not isinstance(raw, list) or not raw:
        return None
    keys = {n.lower(): n for n in WEEKDAY_NAMES} | {n[:3].lower(): n for n in WEEKDAY_NAMES}
    named = [keys.get(str(d).strip().lower()) if isinstance(d, str) else None for d in raw]
    if None in named:
        return None
    return [n for n in WEEKDAY_NAMES if n in named]


def parse_fixed_meals(raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The owner-only twin's fixed feedings and one line per unreadable row. Absent (None) or an empty list is no fixed
    meal and no problem. A row is unreadable when it has no id or a duplicate one, a slot outside SLOTS, a missing or
    negative label value (fibre_g may be null), no calories, or no readable weekday; two rows on the same weekday and
    slot are a problem too. The caller refuses the menu on any problem: a fixed meal is never silently dropped."""
    if raw is None or raw == []:
        return [], []
    if not isinstance(raw, list):
        return [], [f"{FIXED_PATH} is not a list of fixed feedings"]
    usable: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(raw):
        rid = str((row or {}).get("id") or "").strip() if isinstance(row, dict) else ""
        tag = f"fixed {rid or f'row {i}'}"
        if not rid:
            problems.append(f"{tag}: no id")
            continue
        if rid in seen:
            problems.append(f"{tag}: duplicate id")
            continue
        seen.add(rid)
        vals = {m: _num(row.get(m)) for m in FIXED_REQUIRED}
        fib_raw = row.get("fibre_g")
        fib = _num(fib_raw)
        bad = [m for m, v in vals.items() if v is None or v < 0] + (["fibre_g"] if fib_raw is not None and (fib is None or fib < 0) else [])
        if bad or not vals["kcal"]:
            problems.append(f"{tag}: unreadable label value(s) {bad or ['kcal']}")
            continue
        slot = str(row.get("slot") or "").strip().lower()
        if slot not in SLOTS:
            problems.append(f"{tag}: slot {row.get('slot')!r} is not one of {list(SLOTS)}")
            continue
        days = _weekdays(row.get("days"))
        if days is None:
            problems.append(f"{tag}: days {row.get('days')!r} names no readable weekday list")
            continue
        usable.append(
            {
                "id": rid,
                "label": str(row.get("label") or rid),
                "slot": slot,
                **{m: float(v or 0.0) for m, v in vals.items()},
                "fibre_g": fib,  # None: unknown (counted as none, so the anchors carry the whole fibre floor)
                "days": days,
                "source": str(row.get("source") or "") or None,
            }
        )
    clash = sorted(
        {(d, m["slot"]) for m in usable for d in m["days"] if sum(1 for o in usable if o["slot"] == m["slot"] and d in o["days"]) > 1}
    )
    problems += [f"fixed {slot} on {day}: more than one fixed row" for day, slot in clash]
    usable.sort(key=lambda m: (SLOTS.index(m["slot"]), m["id"]))
    return usable, problems


# ── the day's numbers ─────────────────────────────────────────────────────────────────────────────────────────
def day_targets(day: Mapping[str, Any], read: Optional[CharterReader] = None) -> dict[str, Any]:
    """The numbers one plan day is fitted to: the resolver's kcal for the day, the band (+/- half the prescribed band's
    width around it), the protein range low, the feedings and their threshold (the post-session feeding's on a lifting
    day), the floors (a lifting day's carbohydrate line raised to the session carbohydrate), and the window."""
    t = travel_food.targets(_num(day.get("kcal")), read)
    floors = {f"{m}_g": v for m, v in (t.get("floors_g") or {}).items()}
    floors["protein_g"] = t.get("protein_floor_g")
    raw_pp = day.get("pre_post_session")
    pp: Mapping[str, Any] = raw_pp if isinstance(raw_pp, dict) else {}
    pre, post = (pp.get("pre") or {}), (pp.get("post") or {})
    lifting = day.get("day_type") == "lifting"
    thr = t.get("feeding_threshold_g")
    post_g = _num(post.get("protein_g")) if lifting else None
    session_carb = (_num(pre.get("carb_g")) or 0.0) + (_num(post.get("carb_g")) or 0.0) if lifting else 0.0
    if floors.get("carb_g") is not None and session_carb > floors["carb_g"]:
        floors["carb_g"] = session_carb
    kcal, tol = t.get("kcal"), t.get("tolerance_kcal")
    return {
        "kcal": kcal,
        "tolerance_kcal": tol,
        "band": [kcal - tol, kcal + tol] if kcal is not None and tol is not None else None,
        "floors_g": floors,
        "feedings": t.get("feedings") or 0,
        "feeding_threshold_g": thr,
        "post_session_protein_g": max(thr, post_g) if (thr is not None and post_g is not None) else None,
        "eating_hours": t.get("eating_hours"),
        "window_type": t.get("window_type"),
    }


def _ready(t: Mapping[str, Any]) -> bool:
    return bool(t.get("band") and t.get("feedings") and t.get("feeding_threshold_g") is not None) and None not in t["floors_g"].values()


# ── the search ────────────────────────────────────────────────────────────────────────────────────────────────
def _totals(counts: Mapping[str, float], by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    return {m: round(sum(float(by_id[k][m]) * n for k, n in counts.items()), 1) for m in MACROS}


def feeding_cores(anchors: Sequence[Mapping[str, Any]], need_g: float, core_max: int) -> list[Counts]:
    """Every combination of at most `core_max` anchors at the fewest servings (each inside its cap) whose protein
    reaches `need_g`, minimal (no serving can be dropped), sorted by kcal then ids: the most protein-dense first."""
    out: list[tuple[float, tuple[str, ...], Counts]] = []
    for size in range(1, core_max + 1):
        for combo in itertools.combinations(anchors, size):
            for servings in itertools.product(*(range(1, int(a["cap"]) + 1) for a in combo)):
                g = sum(a["protein_g"] * s for a, s in zip(combo, servings))
                if g < need_g:
                    continue
                if any(g - a["protein_g"] >= need_g for a in combo):
                    continue  # not minimal: a serving could be dropped and still reach
                kcal = sum(a["kcal"] * s for a, s in zip(combo, servings))
                out.append((round(kcal, 1), tuple(a["id"] for a in combo), {a["id"]: s for a, s in zip(combo, servings)}))
    out.sort(key=lambda x: (x[0], x[1], tuple(x[2].values())))
    seen: set[tuple[tuple[str, int], ...]] = set()
    uniq = []
    for _k, _ids, counts in out:
        key = tuple(sorted(counts.items()))
        if key not in seen:
            seen.add(key)
            uniq.append(counts)
    return uniq


def _pick_cores(
    cores: Sequence[Counts], post_cores: Sequence[Counts], n: int, post_slot: Optional[int], offset: int, caps: Mapping[str, int]
) -> Optional[list[Counts]]:
    """`n` cores for the day, distinct where the pool allows, walking each pool from `offset` (the day's rotation),
    inside the per-day caps. None when the caps cannot hold `n` cores."""
    used: Counts = {}
    picked: list[Counts] = []
    for slot in range(n):
        pool = post_cores if slot == post_slot else cores
        window = list(pool[: n + len(WEEKDAY_NAMES)])  # the rotation pool: the cheapest cores, enough for a week of variety
        order = [window[(offset + j) % len(window)] for j in range(len(window))] if window else []
        order += [c for c in pool if c not in order]
        choice = None
        for fresh_only in (True, False):
            for c in order:
                if fresh_only and c in picked:
                    continue
                if all(used.get(k, 0) + s <= caps[k] for k, s in c.items()):
                    choice = c
                    break
            if choice is not None:
                break
        if choice is None:
            return None
        picked.append(choice)
        for k, s in choice.items():
            used[k] = used.get(k, 0) + s
    return picked


def _cost(tot: Mapping[str, float], t: Mapping[str, Any]) -> tuple[float, float]:
    """(the miss, the distance): the floor shortfall at the Atwater rate plus the kcal outside the day's band — what
    makes a day unfit — first; the distance from the day's kcal only breaks ties between days that miss equally."""
    gap = sum(ATWATER[m] * max(0.0, float(f) - tot[m]) for m, f in t["floors_g"].items())
    dist = abs(tot["kcal"] - float(t["kcal"]))
    return round(gap + max(0.0, dist - float(t["tolerance_kcal"])), 3), round(dist, 3)


def _used(picked: Sequence[Counts], sides: Mapping[str, int]) -> Counts:
    out: Counts = dict(sides)
    for c in picked:
        for k, n in c.items():
            out[k] = out.get(k, 0) + n
    return out


def _vec(counts: Mapping[str, int], by_id: Mapping[str, Mapping[str, Any]]) -> tuple[float, ...]:
    return tuple(sum(float(by_id[k][m]) * n for k, n in counts.items()) for m in MACROS)


def _cost_vec(v: Sequence[float], t: Mapping[str, Any]) -> tuple[float, float]:
    return _cost(dict(zip(MACROS, v)), t)


def _side_moves(ids: Sequence[str], sides: Mapping[str, int]) -> Iterable[tuple[str, dict[str, int]]]:
    """Every side move as (text, {id: +/-servings}): add one; remove one; remove one and add one or two; remove two
    and add one. The two-serving moves let the search trade one food for two smaller ones (and back), which a
    single-serving step cannot do across the band's edge."""
    have = [k for k in ids if sides.get(k, 0) > 0]
    for k in ids:
        yield f"+{k}", {k: 1}
    for k in have:
        yield f"-{k}", {k: -1}
        for j in ids:
            if j == k:
                continue
            yield f"-{k}+{j}", {k: -1, j: 1}
            for m in ids:
                if m >= j and m != k:
                    yield f"-{k}+{j}+{m}", _merge({k: -1, j: 1}, {m: 1})
        for k2 in have:
            if k2 >= k and (k2 != k or sides.get(k, 0) > 1):
                for j in ids:
                    if j not in (k, k2):
                        yield f"-{k}-{k2}+{j}", _merge({k: -1, j: 1}, {k2: -1})


def _merge(a: Mapping[str, int], b: Mapping[str, int]) -> dict[str, int]:
    out = dict(a)
    for k, n in b.items():
        out[k] = out.get(k, 0) + n
    return out


def _search_day(
    picked: list[Counts],
    pools: Sequence[Sequence[Counts]],
    anchors: Sequence[Mapping[str, Any]],
    t: Mapping[str, Any],
    fixed_vec: Optional[Sequence[float]] = None,
) -> tuple[list[Counts], Counts]:
    """Best-improvement local search from the day's starting cores: a side move (`_side_moves`) or one feeding's core
    replaced by another core from that feeding's pool, every move inside the per-day caps. Ties go to the fewest
    servings, then the move's text (ids), so it is deterministic; every move taken strictly lowers the cost, so it
    ends at a local optimum (or MAX_MOVES). Totals are kept as a running vector, so a move costs a few additions.
    `fixed_vec` is the macro vector of servings pinned into the day (a placed fatty-fish serving, #5105): counted in
    every total, never moved."""
    by_id = {a["id"]: a for a in anchors}
    caps = {a["id"]: int(a["cap"]) for a in anchors}
    unit = {k: _vec({k: 1}, by_id) for k in caps}
    ids = sorted(caps)
    sides: Counts = {}
    used = _used(picked, sides)
    base = tuple(fixed_vec) if fixed_vec is not None else (0.0,) * len(MACROS)
    tot = tuple(x + b for x, b in zip(_vec(used, by_id), base))
    best = (_cost_vec(tot, t), sum(used.values()))
    for _ in range(MAX_MOVES):
        choice: Optional[tuple[tuple[tuple[float, float], int], str, dict[str, int], Optional[tuple[int, Counts]]]] = None
        for tag, delta in _side_moves(ids, sides):
            if any(sides.get(k, 0) + d < 0 or used.get(k, 0) + d > caps[k] for k, d in delta.items()):
                continue
            v = tuple(x + sum(unit[k][i] * d for k, d in delta.items()) for i, x in enumerate(tot))
            sc = (_cost_vec(v, t), best[1] + sum(delta.values()))
            if choice is None or (sc, tag) < (choice[0], choice[1]):
                choice = (sc, tag, delta, None)
        for slot, pool in enumerate(pools):
            old = picked[slot]
            for ci, core in enumerate(pool):
                if core == old:
                    continue
                delta = _merge({k: -n for k, n in old.items()}, core)
                if any(used.get(k, 0) + d > caps[k] for k, d in delta.items()):
                    continue
                v = tuple(x + sum(unit[k][i] * d for k, d in delta.items()) for i, x in enumerate(tot))
                tag = f"core{slot}={ci:04d}"
                sc = (_cost_vec(v, t), best[1] + sum(delta.values()))
                if choice is None or (sc, tag) < (choice[0], choice[1]):
                    choice = (sc, tag, delta, (slot, core))
        if choice is None or choice[0] >= best:
            break
        sc, _tag, delta, core_move = choice
        if core_move is None:
            sides = {k: n for k, n in _merge(sides, delta).items() if n}
        else:
            picked = [*picked[: core_move[0]], core_move[1], *picked[core_move[0] + 1 :]]
        used = {k: n for k, n in _merge(used, delta).items() if n}
        tot = tuple(x + b for x, b in zip(_vec(used, by_id), base))
        best = (sc[0], sum(used.values()))
    return picked, sides


def _knapsack_curves(items: Sequence[tuple[float, tuple[float, ...], int]]) -> list[tuple[list[float], list[float]]]:
    """For each floor gram (protein, carbohydrate, fat, fibre, in GRAMS order), the most of it `items` can add for a
    given added kcal when servings may be fractional: the fractional-knapsack curve (cumulative kcal, cumulative grams),
    the items taken densest-first. Concave and non-decreasing, so it bounds what ANY whole-serving choice of the items
    adds at that kcal."""
    out = []
    for gi in range(1, len(MACROS)):
        order = sorted(items, key=lambda it: (-(it[1][gi] / it[1][0]), it[1][0]))
        ks, gs = [0.0], [0.0]
        for kcal, vec, cap in order:
            ks.append(ks[-1] + vec[0] * cap)
            gs.append(gs[-1] + vec[gi] * cap)
        out.append((ks, gs))
    return out


def _curve_at(curve: tuple[list[float], list[float]], k: float) -> float:
    ks, gs = curve
    if k >= ks[-1]:
        return gs[-1]
    i = bisect.bisect_right(ks, k)
    k0, k1 = ks[i - 1], ks[i]
    return gs[i - 1] + (gs[i] - gs[i - 1]) * ((k - k0) / (k1 - k0) if k1 > k0 else 0.0)


def _curve_inverse(curve: tuple[list[float], list[float]], g: float) -> Optional[float]:
    """The least added kcal at which the curve reaches `g` grams (None when it never does)."""
    ks, gs = curve
    if g <= 0:
        return 0.0
    if g > gs[-1]:
        return None
    i = bisect.bisect_left(gs, g)
    g0, g1 = gs[i - 1], gs[i]
    return ks[i - 1] + (ks[i] - ks[i - 1]) * ((g - g0) / (g1 - g0) if g1 > g0 else 0.0)


def _miss_bound(
    cur: Sequence[float], curves: Sequence[tuple[list[float], list[float]]], kinks: Sequence[float], t: Mapping[str, Any]
) -> float:
    """A lower bound on the miss (`_cost`'s first term) of every completion of a partial day: the day's totals so far
    are `cur`, and the foods still to choose can add at most `curves[g](K)` grams of each floor gram at added kcal K.
    The bound is the least, over K, of h(K) = the floor shortfall at those grams plus the kcal outside the band at
    cur + K. Valid because a real completion with added kcal K adds no more of any gram than its curve allows there.
    h is convex and piecewise linear (each curve is concave), so its least value sits at a kink: the curves' own
    breakpoints (`kinks`, sorted), the band's edges and each floor's crossing. The least over `kinks` is found by
    bisection (a convex sequence), and the true least lies within one breakpoint of it — where only the band edges and
    the crossings can add a kink — so those few are evaluated too."""
    lo, hi = t["band"]
    floors = [float(t["floors_g"].get(m) or 0.0) - cur[gi + 1] for gi, m in enumerate(GRAMS)]
    weights = [ATWATER[m] for m in GRAMS]
    top = kinks[-1] if kinks else 0.0

    def h(k: float) -> float:
        gap = sum(w * max(0.0, need - _curve_at(cv, k)) for cv, w, need in zip(curves, weights, floors) if need > 0)
        kc = cur[0] + k
        return gap + max(0.0, kc - hi) + max(0.0, lo - kc)

    extra = [edge for edge in (lo - cur[0], hi - cur[0]) if 0.0 < edge < top]
    for gi, need in enumerate(floors):
        if need > 0:
            k = _curve_inverse(curves[gi], need)
            if k is not None and 0.0 < k < top:
                extra.append(k)
    if not kinks:
        return h(0.0)
    left, right = 0, len(kinks) - 1
    while left < right:
        mid = (left + right) // 2
        if h(kinks[mid]) <= h(kinks[mid + 1]):
            right = mid
        else:
            left = mid + 1
    return min([h(kinks[left]), *(h(k) for k in extra)])


def _decompose(counts: Mapping[str, int], pools: Sequence[Sequence[Counts]]) -> Optional[list[Counts]]:
    """One core per feeding (feeding i's from `pools[i]`, in pool order) whose servings all sit inside `counts`, or
    None when no assignment does. The first assignment in pool order is taken, so the split is deterministic."""
    failed: set[tuple[int, tuple[tuple[str, int], ...]]] = set()

    def walk(slot: int, left: dict[str, int]) -> Optional[list[Counts]]:
        if slot == len(pools):
            return []
        memo = (slot, tuple(sorted((k, n) for k, n in left.items() if n)))
        if memo in failed:
            return None
        for core in pools[slot]:
            if all(left.get(k, 0) >= n for k, n in core.items()):
                rest = walk(slot + 1, {k: n - core.get(k, 0) for k, n in left.items()})
                if rest is not None:
                    return [core, *rest]
        failed.add(memo)
        return None

    return walk(0, dict(counts))


def _core_sets(pools: Sequence[Sequence[Counts]], caps: Mapping[str, int]) -> list[tuple[Counts, ...]]:
    """Every way to give each feeding one core from its pool inside the per-day caps, one entry per distinct serving
    total (feedings that share a pool take its cores as a multiset: the order of two equal feedings is not a choice),
    in a fixed order (pool order), so the search below walks them the same way every time."""
    groups: dict[int, list[int]] = {}
    for slot, pool in enumerate(pools):
        groups.setdefault(id(pool), []).append(slot)
    plans = [(slots, pools[slots[0]]) for slots in groups.values()]
    choices = [list(itertools.combinations_with_replacement(range(len(pool)), len(slots))) for slots, pool in plans]
    out: list[tuple[Counts, ...]] = []
    seen: set[tuple[tuple[str, int], ...]] = set()
    for pick in itertools.product(*choices):
        by_slot: dict[int, Counts] = {}
        for (slots, pool), idx in zip(plans, pick):
            for slot, ci in zip(slots, idx):
                by_slot[slot] = pool[ci]
        total: Counts = {}
        for c in by_slot.values():
            for k, n in c.items():
                total[k] = total.get(k, 0) + n
        if any(n > caps.get(k, 0) for k, n in total.items()):
            continue
        sig = tuple(sorted(total.items()))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(tuple(by_slot[slot] for slot in range(len(pools))))
    return out


def _exact_day(
    pools: Sequence[Sequence[Counts]],
    anchors: Sequence[Mapping[str, Any]],
    t: Mapping[str, Any],
    fixed_vec: Optional[Sequence[float]] = None,
    incumbent: Optional[Mapping[str, int]] = None,
    require: Optional[Mapping[str, int]] = None,
    budget: int = EXACT_NODE_BUDGET,
) -> tuple[Optional[tuple[list[Counts], Counts]], dict[str, Any]]:
    """The day's BEST set, exactly. Every assignment of one core per feeding (`_core_sets`) is taken in turn, and for
    each a branch-and-bound over every side serving count of every anchor (0 up to what its cap leaves) — together,
    every set the local search could ever reach. It minimises one total order (the miss, the distance, the servings,
    the counts in id order), so the answer is the one global optimum whatever the starting point, and the same input
    always gives the same set (split into cores by `_decompose`, so the split is a function of the set alone). A branch
    is cut only when no completion can beat the best set found: its miss bound (`_miss_bound`) is above the best miss,
    or the best fits and no completion can land nearer the day's kcal. The `incumbent` (the local search's set) seeds
    the bound. `require` names servings every set must hold (the day's pinned fatty fish: in a core or as a side).
    Returns ((cores, sides), stats) — None when no assignment fits the caps — with stats {nodes, core_sets,
    complete}: `complete` is False only when the `budget` of nodes ran out first (the best found so far is kept and the
    day says so)."""
    by_id = {a["id"]: a for a in anchors}
    ids = sorted(by_id)
    caps = {k: int(by_id[k]["cap"]) for k in ids}
    base = tuple(fixed_vec) if fixed_vec is not None else (0.0,) * len(MACROS)
    unit_of = {k: _vec({k: 1}, by_id) for k in ids}
    target = float(t["kcal"])
    stats: dict[str, Any] = {"nodes": 0, "core_sets": 0, "complete": True}

    def key(total: Mapping[str, int], vec: Sequence[float]) -> tuple[Any, ...]:
        return (*_cost_vec(vec, t), sum(total.values()), tuple(total.get(k, 0) for k in ids))

    best: list[Any] = [None, None]  # key, total counts
    need = {k: int(n) for k, n in (require or {}).items() if n}
    if incumbent is not None:
        inc = {k: int(n) for k, n in incumbent.items() if n}
        if all(inc.get(k, 0) >= n for k, n in need.items()) and _decompose(inc, pools) is not None:
            vec = tuple(b + sum(unit_of[k][i] * n for k, n in inc.items()) for i, b in enumerate(base))
            best[:] = [key(inc, vec), inc]

    def cut(cur: Sequence[float], miss_lb: float, reach: float) -> bool:
        """True when no completion of this branch can beat the best set found."""
        if best[0] is None:
            return False
        if miss_lb > best[0][0] + 1e-3:
            return True
        if best[0][0] == 0.0:  # the best fits: only a fit nearer the day's kcal can beat it
            lo_k, hi_k = cur[0], cur[0] + reach
            dist_lb = 0.0 if lo_k <= target <= hi_k else min(abs(lo_k - target), abs(hi_k - target))
            return dist_lb > best[0][1] + 1e-3
        return False

    def sides_search(core_total: Counts) -> None:
        must = {k: max(0, n - core_total.get(k, 0)) for k, n in need.items()}  # required servings no core holds
        if any(core_total.get(k, 0) + n > caps.get(k, 0) for k, n in must.items()):
            return
        core_total = _merge(core_total, {k: n for k, n in must.items() if n})
        left = {k: caps[k] - core_total.get(k, 0) for k in ids}
        # The biggest foods first: deciding them early shrinks what the rest can add, which tightens every bound.
        order = sorted((k for k in ids if left[k] > 0), key=lambda k: (-unit_of[k][0] * left[k], k))
        unit = [unit_of[k] for k in order]
        room = [left[k] for k in order]
        curves, kinks, reach = [], [], []
        for i in range(len(order) + 1):
            cv = _knapsack_curves([(unit[j][0], unit[j], room[j]) for j in range(i, len(order))])
            curves.append(cv)
            kinks.append(sorted({k for ks, _gs in cv for k in ks}))
            reach.append(sum(u[0] * r for u, r in zip(unit[i:], room[i:])))
        counts = [0] * len(order)
        start = tuple(b + sum(unit_of[k][i] * n for k, n in core_total.items()) for i, b in enumerate(base))

        def dfs(i: int, cur: tuple[float, ...]) -> None:
            stats["nodes"] += 1
            if stats["nodes"] > budget:
                stats["complete"] = False
                return
            if i == len(order):
                total = dict(core_total)
                for k, n in zip(order, counts):
                    if n:
                        total[k] = total.get(k, 0) + n
                kk = key(total, cur)
                if best[0] is None or kk < best[0]:
                    best[:] = [kk, total]
                return
            children = []
            for n in range(room[i] + 1):
                nxt = tuple(c + x * n for c, x in zip(cur, unit[i]))
                children.append((_miss_bound(nxt, curves[i + 1], kinks[i + 1], t), -n, nxt))
            children.sort()  # the most promising branch first: a good set is found early, so more is cut
            for miss_lb, neg_n, nxt in children:
                if cut(nxt, miss_lb, reach[i + 1]):
                    continue
                counts[i] = -neg_n
                dfs(i + 1, nxt)
                if not stats["complete"]:
                    return
            counts[i] = 0

        if not cut(start, _miss_bound(start, curves[0], kinks[0], t), reach[0]):
            dfs(0, start)

    # Every assignment's start is bounded first with what ALL the anchors could add (a looser bound than the one its own
    # side search uses, so it cuts nothing a tighter bound would keep), and the assignments are walked best bound
    # first: a good set early cuts the rest at a glance.
    every = _knapsack_curves([(unit_of[k][0], unit_of[k], caps[k]) for k in ids])
    every_kinks = sorted({k for ks, _gs in every for k in ks})
    every_reach = sum(unit_of[k][0] * caps[k] for k in ids)
    starts = []
    for pos, assignment in enumerate(_core_sets(pools, caps)):
        core_total: Counts = {}
        for c in assignment:
            for k, n in c.items():
                core_total[k] = core_total.get(k, 0) + n
        start = tuple(b + sum(unit_of[k][i] * n for k, n in core_total.items()) for i, b in enumerate(base))
        starts.append((_miss_bound(start, every, every_kinks, t), pos, start, core_total))
    starts.sort(key=lambda x: (x[0], x[1]))
    for miss_lb, _pos, start, core_total in starts:
        stats["core_sets"] += 1
        stats["nodes"] += 1
        if stats["nodes"] > budget:
            stats["complete"] = False
            break
        if cut(start, miss_lb, every_reach):
            continue
        sides_search(core_total)
        if not stats["complete"]:
            break
    if best[1] is None:
        return None, stats
    picked = _decompose(best[1], pools)
    if picked is None:  # unreachable: every set above holds an assignment; kept so a bug is named, never served
        return None, {**stats, "complete": False}
    sides = dict(best[1])
    for core in picked:  # one core at a time: two feedings' cores may share an anchor
        sides = _merge(sides, {k: -n for k, n in core.items()})
    return (list(picked), {k: n for k, n in sorted(sides.items()) if n}), stats


# ── one day ───────────────────────────────────────────────────────────────────────────────────────────────────
def _check(tot: Mapping[str, float], feedings: Sequence[Mapping[str, Any]], t: Mapping[str, Any]) -> tuple[dict[str, bool], list[str]]:
    lo, hi = t["band"]
    checks = {"kcal_in_band": lo <= tot["kcal"] <= hi}
    misses = [] if checks["kcal_in_band"] else [f"kcal {tot['kcal']:g} outside {lo:g}-{hi:g}"]
    for m, f in t["floors_g"].items():
        ok = tot[m] >= float(f)
        checks[f"{m}_at_floor"] = ok
        if not ok:
            misses.append(f"{m} {tot[m]:g} under {float(f):g}")
    short = [f"{fd['name']} {fd['protein_g']:g} g under {fd['need_g']:g} g" for fd in feedings if fd["protein_g"] < fd["need_g"]]
    checks["every_feeding_counts"] = not short and len(feedings) == t["feedings"]
    misses += short
    return checks, misses


def _fixed_vec(fixed_meals: Sequence[Mapping[str, Any]]) -> tuple[float, ...]:
    """The macro vector of the day's fixed feedings (an unknown fibre counted as none)."""
    return tuple(sum(float(m.get(k) or 0.0) for m in fixed_meals) for k in MACROS)


def remainder(t: Mapping[str, Any], fixed_meals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the day leaves the anchors once its fixed feedings are subtracted: the band and the kcal moved down by the
    fixed kcal, each floor less the fixed grams (never below 0), the feedings less one per fixed feeding. `fibre_unknown`
    names the fixed rows whose fibre is null (counted as none: the anchors carry the whole fibre floor)."""
    fx = dict(zip(MACROS, _fixed_vec(fixed_meals)))
    lo, hi = t["band"]
    return {
        "fixed": [m["id"] for m in fixed_meals],
        "fixed_kcal": round(fx["kcal"], 1),
        "fixed_g": {g: round(fx[g], 1) for g in GRAMS},
        "kcal": round(float(t["kcal"]) - fx["kcal"], 1),
        "band": [round(lo - fx["kcal"], 1), round(hi - fx["kcal"], 1)],
        "floors_g": {m: round(max(0.0, float(f) - fx[m]), 1) for m, f in t["floors_g"].items()},
        "feedings": max(0, int(t["feedings"]) - len(fixed_meals)),
        "fibre_unknown": [m["id"] for m in fixed_meals if m.get("fibre_g") is None],
    }


def _lay_out(
    cores: Sequence[Counts],
    sides: Counts,
    t: Mapping[str, Any],
    post_slot: Optional[int],
    by_id: Mapping[str, Any],
    fixed_meals: Sequence[Mapping[str, Any]] = (),
) -> list[dict]:
    """The day's feedings: the cores in order, each side serving dealt to the feeding with the fewest kcal so far
    (largest sides first, ids breaking ties), the fixed feedings in their slots (breakfast first, dinner last, never
    given a side), each feeding placed in the window. A day whose every feeding is fixed deals its sides onto the last
    fixed feeding (its items then list them)."""
    per = [dict(c) for c in cores]
    kcal = [_totals(c, by_id)["kcal"] for c in per]
    servings = sorted(((by_id[k]["kcal"], k) for k, n in sides.items() for _ in range(n)), key=lambda x: (-x[0], x[1]))
    spill: Counts = {}
    for k_kcal, k in servings:
        if not per:
            spill[k] = spill.get(k, 0) + 1
            continue
        i = min(range(len(per)), key=lambda j: (kcal[j], j))
        per[i][k] = per[i].get(k, 0) + 1
        kcal[i] += k_kcal
    order: list[tuple[str, Any]] = [(FIXED, m) for m in fixed_meals if m["slot"] == "breakfast"]
    order += [("anchor", i) for i in range(len(per))]
    order += [(FIXED, m) for m in fixed_meals if m["slot"] == "dinner"]
    hours = _num(t.get("eating_hours"))
    step = hours / len(order) if hours and order else None
    last_fixed = max((j for j, (kind, _x) in enumerate(order) if kind == FIXED), default=None)
    out = []
    for pos, (kind, x) in enumerate(order):
        offset = round(pos * step, 2) if step is not None else None
        if kind == FIXED:
            extra = spill if pos == last_fixed else {}
            side = _totals(extra, by_id)
            out.append(
                {
                    "name": f"feeding {pos + 1} (fixed {x['slot']})",
                    "when": FIXED,
                    "slot": x["slot"],
                    "window_offset_h": offset,
                    "need_g": t["feeding_threshold_g"],
                    "fixed": {"id": x["id"], "label": x["label"], "source": x.get("source"), "fibre_known": x.get("fibre_g") is not None},
                    "items": [
                        {"item": k, "servings": n, "label": by_id[k]["label"], "serving": by_id[k]["serving"]}
                        for k, n in sorted(extra.items())
                    ],
                    **{m: round(float(x.get(m) or 0.0) + side[m], 1) for m in MACROS},
                }
            )
            continue
        i, counts = x, per[x]
        when = POST_SESSION if i == post_slot else ("first" if pos == 0 else "meal")
        need = t["post_session_protein_g"] if i == post_slot else t["feeding_threshold_g"]
        items = [
            {"item": k, "servings": n, "label": by_id[k]["label"], "serving": by_id[k]["serving"]} for k, n in sorted(counts.items()) if n
        ]
        out.append(
            {
                "name": f"feeding {pos + 1}" + (" (post-session)" if when == POST_SESSION else ""),
                "when": when,
                "window_offset_h": offset,
                "need_g": need,
                "items": items,
                **_totals(counts, by_id),
            }
        )
    return out


def fit_day(
    day: Mapping[str, Any],
    anchors: Sequence[Mapping[str, Any]],
    pol: Mapping[str, Any],
    index: int,
    read: Optional[CharterReader] = None,
    *,
    exclude: Iterable[str] = (),
    fixed: Optional[Mapping[str, int]] = None,
    fixed_meals: Sequence[Mapping[str, Any]] = (),
    search: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One plan day fitted from the anchors. `index` is the day's position in the week (the core rotation). `exclude`
    keeps anchors off the day; `fixed` pins servings into it (counted, never moved) — the week's fatty-fish placement
    (#5105) uses both. `fixed_meals` are the parsed fixed feedings (`parse_fixed_meals`); the ones whose `days` name
    this weekday are subtracted first (`remainder`, reported as `targets.remaining`), counted as feedings and laid in
    their slots. `search` is the build's shared exact-search state ({nodes_left, memo}: the week's node budget and the
    completed searches, so an identical day is searched once); None gives this day its own.

    The day is fitted in two steps. The local search (`_search_day`) runs from the day's core rotation (variety across
    the week) and the next rotations; the first rotation that fits is the day. When none fits, the exact search
    (`_exact_day`) finds the day's best set — a fit if any exists, else the least miss — so a day is never called unfit
    while a fitting set exists, and an unfit day misses by the least any set of the anchors can. `search` on the day
    names which step chose it (and, for the exact one, its nodes and whether it ran to completion)."""
    t = day_targets(day, read)
    weekday = WEEKDAY_NAMES[datetime.strptime(str(day.get("date"))[:10], "%Y-%m-%d").weekday()]  # a calendar-day key
    today = [m for m in fixed_meals if weekday in m["days"]]
    base = {
        "date": day.get("date"),
        "weekday": weekday,
        "day_type": day.get("day_type"),
        "service": SERVICE_COOK if weekday in pol["cook_days"] else SERVICE_MEAL,
        "targets": t,
    }
    if not _ready(t):
        return {**base, "fits": False, "reason_code": NO_CALORIE_TARGET, "misses": ["no resolved kcal or an unreadable charter rule"]}
    rem = remainder(t, today) if today else None
    if rem is not None:
        t = {**t, "remaining": rem}
        base["targets"] = t
    n_anchor = rem["feedings"] if rem is not None else t["feedings"]  # the feedings the anchors build
    by_id = {a["id"]: a for a in anchors}
    pinned: Counts = {k: int(n) for k, n in (fixed or {}).items() if n and k in by_id}
    off = set(exclude) | set(pinned)
    anchors = [a for a in anchors if a["id"] not in off]  # the foods the search may move
    caps = {a["id"]: int(a["cap"]) for a in anchors}
    fixed_vec = _vec(pinned, by_id)
    if today:
        fixed_vec = tuple(a + b for a, b in zip(fixed_vec, _fixed_vec(today)))  # counted in every total, never moved
    pps = t["post_session_protein_g"]
    post_slot = 1 if (pps is not None and n_anchor > 1) else (0 if pps and n_anchor else None)
    # A core is at most one feeding's share of what the anchors have (the day, less its fixed feedings): protein-led,
    # never a whole meal plan.
    share = (float(rem["kcal"]) if rem is not None else float(t["kcal"])) / n_anchor if n_anchor else 0.0

    def _pool(need: float, capped: bool, foods: Sequence[Mapping[str, Any]]) -> list[Counts]:
        return [c for c in feeding_cores(foods, need, pol["core_max"]) if not capped or _totals(c, by_id)["kcal"] <= share]

    def _pools(capped: bool, foods: Sequence[Mapping[str, Any]]) -> tuple[list[Counts], list[Counts]]:
        main = _pool(float(t["feeding_threshold_g"]), capped, foods)
        return main, (_pool(float(pps), capped, foods) if post_slot is not None else main)

    capped = True
    cores, post_cores = _pools(capped, anchors)
    if today and n_anchor and (not cores or not post_cores):
        # The fixed feedings leave less than any core: the day is still fitted (with the uncapped cores) and the check
        # names what the remainder cannot hold — the fixed meal is never shrunk or dropped to make room.
        capped = False
        cores, post_cores = _pools(capped, anchors)
    if n_anchor and (not cores or not post_cores):
        return {
            **base,
            "fits": False,
            "reason_code": NO_FEEDING_CORE,
            "misses": ["no anchor combination reaches the feeding threshold inside one feeding's share of the day's kcal"],
        }
    pools = [post_cores if slot == post_slot else cores for slot in range(n_anchor)]
    best: Optional[dict[str, Any]] = None
    span = n_anchor + len(WEEKDAY_NAMES)  # the rotation pool's size (see _pick_cores)
    fx = dict(zip(MACROS, _fixed_vec(today)))

    def _day(
        picked: list[Counts], moved: Counts, rotation: Optional[int], search: dict[str, Any], add_pinned: bool = True
    ) -> dict[str, Any]:
        sides = _merge(moved, pinned) if add_pinned else dict(moved)
        feedings = _lay_out(picked, sides, t, post_slot, by_id, today)
        tot = _totals(_used(picked, sides), by_id)
        if today:
            tot = {m: round(tot[m] + fx[m], 1) for m in MACROS}
        checks, misses = _check(tot, feedings, t)
        if rem is not None and misses:
            misses.insert(
                0,
                f"after the fixed {' + '.join(m['slot'] for m in today)} ({rem['fixed_kcal']:g} kcal, "
                f"{rem['fixed_g']['protein_g']:g} g protein) the anchors had {rem['band'][0]:g}-{rem['band'][1]:g} kcal "
                f"for {n_anchor} feeding(s)",
            )
        if misses and search.get("method") == "exact" and not search.get("complete", True):
            misses.append(f"the exact search stopped at its node budget ({search.get('nodes')} nodes): a better set may exist")
        return {
            "feedings": feedings,
            "totals": tot,
            "checks": checks,
            "misses": misses,
            "fits": all(checks.values()),
            "rotation": rotation,
            "search": search,
            "_counts": _used(picked, sides),  # every anchor serving of the day (the pinned ones included)
        }

    for offset in [(index + j) % span for j in range(span)]:  # the day's own rotation first, then the next starts
        start = _pick_cores(cores, post_cores, n_anchor, post_slot, offset, caps)
        if start is None:
            continue
        picked, sides = _search_day(start, pools, anchors, t, fixed_vec)
        cand = _day(picked, sides, offset, {"method": "local"})
        if best is None or _cost(cand["totals"], t) < _cost(best["totals"], t):
            best = cand
        if cand["fits"]:
            break
    if best is None:
        return {**base, "fits": False, "reason_code": NO_FEEDING_CORE, "misses": ["the serving caps cannot hold one core per feeding"]}
    if not best["fits"]:
        # No rotation's local optimum fits: the exact search finds the day's best set (a fit when one exists, else the
        # least miss), seeded with the local optimum so it only ever improves on it. A pinned serving is held exactly
        # (its count is both its cap and its minimum) but may sit inside a feeding's core. The misses stay named.
        foods = [*anchors, *({**by_id[k], "cap": n} for k, n in sorted(pinned.items()))]
        ex_cores, ex_post = _pools(capped, foods) if pinned else (cores, post_cores)
        ex_pools = [ex_post if slot == post_slot else ex_cores for slot in range(n_anchor)]
        ex_vec = _fixed_vec(today) if today else None
        sig = json.dumps(
            [[sorted(c.items()) for c in pool] for pool in ex_pools]
            + [[[a["id"], int(a["cap"]), *(a[m] for m in MACROS)] for a in foods], t["band"], t["kcal"], sorted(t["floors_g"].items())]
            + [ex_vec, sorted(pinned.items())]
        )
        state = search if search is not None else {}
        memo = state.setdefault("memo", {})
        if sig in memo:  # the same day's search already ran to completion: its optimum is THE optimum (seed-free)
            found, stats = memo[sig]
        else:
            left = int(state.get("nodes_left", EXACT_NODE_BUDGET))
            found, stats = _exact_day(
                ex_pools, foods, t, ex_vec, incumbent=best["_counts"], require=pinned, budget=max(0, min(EXACT_NODE_BUDGET, left))
            )
            if "nodes_left" in state:
                state["nodes_left"] = left - stats["nodes"]
            if stats["complete"]:
                memo[sig] = (found, stats)
        if found is not None:
            best = _day(found[0], found[1], None, {"method": "exact", **stats}, add_pinned=False)
    best.pop("_counts", None)
    return {**base, **best, "reason_code": None if best["fits"] else DAY_UNFIT}


# ── the week ──────────────────────────────────────────────────────────────────────────────────────────────────
def _refused(code: str, reason: str, **extra: Any) -> dict[str, Any]:
    logger.warning("weekly menu not built: %s (%s)", code, reason)
    return {"version": VERSION, "issue": ISSUE, "tier": "owner_only", "built": False, "reason_code": code, "reason": reason, **extra}


def _fish_ids(anchors: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(a["id"] for a in anchors if a.get("fatty_fish"))


def _miss(day: Mapping[str, Any]) -> float:
    """A fitted day's miss (`_cost`'s first term; 0 for a day that fits), or infinity for a day with no feedings."""
    return _cost(day["totals"], day["targets"])[0] if day.get("feedings") and day.get("totals") else math.inf


def _fish_cost(before: Mapping[str, Any], cand: Mapping[str, Any]) -> Optional[tuple[int, float]]:
    """What a fatty-fish serving costs a day, as the placement ranks it (lower is better): (0 when the day fits with
    it, else 1; the miss it adds over the day's fish-free fit, negative when it helps). None when the day cannot take
    one at all (no feedings with it). The charter's low end is placed whatever it costs (trading the target away is an
    owner ruling, never the fitter's): this only decides WHERE it costs least."""
    if not cand.get("feedings"):
        return None
    return (0 if cand.get("fits") else 1, round(_miss(cand) - _miss(before), 3))


def _fit_week(
    days: Sequence[Mapping[str, Any]],
    anchors: Sequence[Mapping[str, Any]],
    pol: Mapping[str, Any],
    qpol: Mapping[str, Any],
    read: CharterReader,
    fixed_meals: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, Any]], str]:
    """Every day fitted, with the fatty-fish target enforced (#5105), and the reason any serving of the low end could
    not be placed ('' when all were). Every day is first fitted with the fatty-fish anchors kept off it, then the low
    end of the charter's weekly range is ALWAYS placed — one pinned serving on each of that many days, the fish anchors
    taken in turn — on the days where it costs the least (`_fish_cost`): a day that fits with it first, else the
    smallest miss it adds over the day's fish-free fit; the spread across the week (the day nearest each even slot)
    only breaks ties. A day the fish leaves unfit names its misses exactly as any unfit day does. A serving is left
    unplaced only when no free day can take one; the quality report then names the short count with that reason. A day
    the fish-free fit cannot build (fish was its only protein core) is fitted with fish allowed; the quality report
    names any count outside the range. With no readable range or no tagged anchor the week is fitted as before. The
    fixed feedings (`fixed_meals`) ride every fit: the fish is placed around them."""
    fish = _fish_ids(anchors)
    rng = qpol.get("fish_range")
    search: dict[str, Any] = {"nodes_left": WEEK_NODE_BUDGET, "memo": {}}  # one budget and memo for the whole build
    if not fish or rng is None:
        return [fit_day(d, anchors, pol, i, read, fixed_meals=fixed_meals, search=search) for i, d in enumerate(days)], ""
    fitted = []
    for i, d in enumerate(days):
        day = fit_day(d, anchors, pol, i, read, exclude=fish, fixed_meals=fixed_meals, search=search)
        fitted.append(
            fit_day(d, anchors, pol, i, read, fixed_meals=fixed_meals, search=search) if day.get("reason_code") == NO_FEEDING_CORE else day
        )
    placed = [sum(i_["servings"] for f in d.get("feedings") or [] for i_ in f["items"] if i_["item"] in fish) for d in fitted]
    free = [i for i, n in enumerate(placed) if not n]
    need = max(0, math.ceil(rng[0] - sum(placed)))
    chosen: set[int] = set()
    tried: dict[tuple[int, str], dict[str, Any]] = {}
    for k in range(need):
        ideal = (k + 0.5) * len(days) / need
        fid = fish[k % len(fish)]
        ranked = []
        for i in free:
            if i in chosen:
                continue
            if (i, fid) not in tried:
                tried[(i, fid)] = fit_day(
                    days[i], anchors, pol, i, read, exclude=fish, fixed={fid: 1}, fixed_meals=fixed_meals, search=search
                )
            cost = _fish_cost(fitted[i], tried[(i, fid)])
            if cost is not None:
                ranked.append((cost, abs(i + 0.5 - ideal), i))
        if not ranked:
            break
        i = min(ranked)[2]
        fitted[i] = tried[(i, fish[k % len(fish)])]
        chosen.add(i)
    short = need - len(chosen)
    note = f"{short} serving(s) not placed: no free day could take a fatty-fish serving" if short > 0 else ""
    return fitted, note


def build(
    plan: Optional[Mapping[str, Any]],
    *,
    read: Optional[CharterReader] = None,
    anchors_raw: Any = None,
    priorities: Optional[Mapping[str, Any]] = None,
    fixed_meals_raw: Any = None,
) -> dict[str, Any]:
    """The week's menu over a `food_panel.build_food_plan` plan. `anchors_raw` is the anchor table (default: the
    owner-only twin's `anchor_foods`); `fixed_meals_raw` the fixed feedings (default: the twin's `fixed_meals`; absent
    or empty is the menu exactly as before, an unreadable row refuses it with `fixed_meal_unreadable`); `priorities`
    is the owner-only lab-driven priorities row (`training.lab_priorities.from_rows`, #5111) when the caller holds one.
    Never raises: an unbuildable menu is `{built: False, reason_code, reason}` with a code from REASON_CODES; a built
    menu with a day the anchors cannot fit carries `fits_all: False`, `reason_code: day_unfit` and each day's misses; a
    week that misses a food-quality target (#5105) carries `quality_met: False` and each miss named in `quality.misses`."""
    read = read or _default_reader
    days = [d for d in (plan or {}).get("days") or [] if isinstance(d, dict)]
    if not days:
        return _refused(NO_PLAN, "no food plan days to fit (training.food_panel.build_food_plan)")
    pol = policy(read)
    if not pol:
        return _refused(NO_POLICY, f"the charter's {POLICY_PATH} block is missing or a number is unreadable")
    raw = read(ANCHORS_PATH) if anchors_raw is None else anchors_raw
    if not isinstance(raw, list) or not raw:
        return _refused(NO_ANCHOR_TABLE, "no anchor-food table: the owner-only charter twin carries no anchor_foods rows")
    anchors, problems = parse_anchors(raw, pol["cap"])
    if len(anchors) < pol["min_anchors"]:
        return _refused(
            TOO_FEW_ANCHORS,
            f"{len(anchors)} usable anchor food(s), fewer than the charter's min_anchors {pol['min_anchors']}",
            anchor_problems=problems,
        )
    fixed_meals, fixed_problems = parse_fixed_meals(read(FIXED_PATH) if fixed_meals_raw is None else fixed_meals_raw)
    if fixed_problems:
        return _refused(
            FIXED_MEAL_UNREADABLE,
            f"the owner-only twin's {FIXED_PATH} has an unreadable row (a fixed meal is never dropped): {'; '.join(fixed_problems)}",
            fixed_meal_problems=fixed_problems,
            anchor_problems=problems,
        )
    qpol = food_quality.policy(read)
    fitted, fish_held = _fit_week(days, anchors, pol, qpol, read, fixed_meals)
    refused = next((d for d in fitted if d.get("reason_code") in (NO_CALORIE_TARGET, NO_FEEDING_CORE)), None)
    if refused is not None:
        return _refused(str(refused["reason_code"]), f"{refused['date']}: {'; '.join(refused['misses'])}", anchor_problems=problems)
    unfit = [d for d in fitted if not d["fits"]]
    if unfit:
        logger.warning("weekly menu: %d day(s) the anchors cannot fit: %s", len(unfit), [(d["date"], d["misses"]) for d in unfit])
    by_id = {a["id"]: a for a in anchors}
    note = fish_held if _fish_ids(anchors) else "no anchor in the table is tagged fatty_fish"
    quality = food_quality.check_week(food_quality.day_rows(fitted, by_id), qpol, priorities, fish_note=note)
    if not quality["met"]:
        logger.warning("weekly menu: food-quality targets missed: %s %s", quality["misses"], quality["problems"])
    menu = {
        "version": VERSION,
        "issue": ISSUE,
        "tier": "owner_only",
        "built": True,
        "week_start": (plan or {}).get("week_start"),
        "charter_version": (plan or {}).get("charter_version"),
        "fits_all": not unfit,
        "reason_code": DAY_UNFIT if unfit else None,
        "unfit_days": [{"date": d["date"], "misses": d["misses"]} for d in unfit],
        "quality_met": quality["met"],
        "quality": quality,
        "anchors_used": len(anchors),
        "anchor_problems": problems,
        "days": fitted,
    }
    if fixed_meals:
        menu["fixed_meals"] = fixed_meals  # the fixed feedings planned around (owner data, owner-only menu)
    menu["grocery_list"] = grocery_list(menu, anchors)
    menu["grocery_travel_days"] = travel_days(menu)  # #5104: dates the home shop skips (the travel kit's)
    menu["lines"] = lines(menu)
    return menu


# ── what reads the menu: the panel's plan, the grocery list, the words ────────────────────────────────────────
def _plan_feeding(f: Mapping[str, Any]) -> dict[str, Any]:
    """One menu feeding as the food panel's plan row: its timing and protein; a fixed feeding also carries its slot,
    its id and its label values, so the panel grades the whole day."""
    row: dict[str, Any] = {"when": f["when"], "protein_g": f["protein_g"]}
    if f.get("fixed"):
        row.update(fixed=True, slot=f.get("slot"), id=f["fixed"].get("id"), **{m: f.get(m) for m in MACROS if m != "protein_g"})
        if not f["fixed"].get("fibre_known"):
            row["fibre_g"] = None  # unknown on the label table (the day's fibre counts it as none)
    return row


def food_plan(plan: Mapping[str, Any], menu: Mapping[str, Any]) -> dict[str, Any]:
    """The food plan with each day's intended feedings replaced by the MENU's (the grams the anchors actually carry,
    the post-session one tagged, a fixed feeding with its label values) — the plan `training.food_panel.prescore`
    grades. A copy; the plan is untouched."""
    out = copy.deepcopy(dict(plan))
    by_date = {d["date"]: d for d in menu.get("days") or [] if d.get("feedings")}
    for d in out.get("days") or []:
        m = by_date.get(d.get("date"))
        if m is not None:
            d["feedings"] = [_plan_feeding(f) for f in m["feedings"]]
    out["case_id"] = f"{out.get('case_id') or 'food'}::menu"
    q = menu.get("quality") or {}
    out["quality_days"] = q.get("rows") or []  # #5105: what training.food_panel checks the week's quality targets over
    return out


def _days(menu: Mapping[str, Any], which: str) -> list[Mapping[str, Any]]:
    days = [d for d in menu.get("days") or [] if d.get("feedings")]
    return days if which == "all" else [d for d in days if d.get("service") == SERVICE_COOK]


def travel_days(menu: Mapping[str, Any]) -> list[str]:
    """The menu's dates that fall on a travel day (the plan's day type): the food for those is the travel kit's, shopped
    at the destination (`health.travel_food.grocery_list`), so the home grocery list does not buy it."""
    return [str(d.get("date")) for d in menu.get("days") or [] if d.get("day_type") == TRAVEL_DAY]


def grocery_list(menu: Mapping[str, Any], anchors: Iterable[Mapping[str, Any]], which: str = SERVICE_COOK) -> list[dict[str, Any]]:
    """The shop for the menu's cook days (`which='all'` for every day): servings per anchor summed over the days
    (`travel_food.menu_counts`, the same day shape), packages rounded up from the anchor's own package size. A travel
    day (#5104: the trip's dates) is not shopped here — its food is the travel kit's."""
    by_id = {a["id"]: a for a in anchors}
    days = [d for d in _days(menu, which) if d.get("day_type") != TRAVEL_DAY]
    out = []
    for k, n in sorted(travel_food.menu_counts(days).items()):
        a = by_id.get(k)
        if a is None or n <= 0:
            continue
        per = (a.get("package") or {}).get("servings") or 1.0
        out.append(
            {
                "item": k,
                "label": a["label"],
                "servings": round(n, 2),
                "serving": a["serving"],
                "packages": math.ceil(round(n / float(per), 6)),
                "package": (a.get("package") or {}).get("label"),
                "section": a.get("section"),
            }
        )
    return out


def grocery_lines(menu: Mapping[str, Any]) -> list[str]:
    """The grocery list in words (a template over `menu['grocery_list']`, no model): one line per store section
    (`other` for an anchor with no section), each item as servings and the packages to buy, plus a line that names the
    travel days left off the shop and points at the travel kit. Empty when the menu has neither."""
    out: list[str] = []
    by_section: dict[str, list[str]] = {}
    for g in menu.get("grocery_list") or []:
        pkg = f" = {g['packages']} x {g['package']}" if g.get("package") else f" = {g['packages']} package(s)"
        by_section.setdefault(g.get("section") or "other", []).append(f"{g['label']}: {g['servings']:g} x {g['serving']}{pkg}")
    cook = ", ".join(sorted({d["weekday"] for d in menu.get("days") or [] if d.get("service") == SERVICE_COOK and d.get("feedings")}))
    for section in sorted(by_section, key=lambda x: (x == "other", x)):
        out.append(f"Grocery list, {section} (cook days {cook}): " + "; ".join(by_section[section]))
    skipped = menu.get("grocery_travel_days") or []
    if skipped:
        out.append(
            f"Travel days not shopped here ({', '.join(skipped)}): that food is the travel kit "
            "(get_exercise_notes action='travel_kit': packing list, destination grocery list, playbook)."
        )
    return out


def _feeding_line(f: Mapping[str, Any]) -> str:
    head = f"{f['name']} (+{f['window_offset_h']:g} h): "
    items = ", ".join(f"{i['servings']:g} x {i['label']}" for i in f["items"])
    fx = f.get("fixed")
    if not fx:
        return head + items
    fib = f"{f['fibre_g']:g} g fibre" if fx.get("fibre_known") else "fibre unknown"
    return (
        head + f"{f.get('slot')}: {fx['label']} — fixed, planned at {f['kcal']:g} kcal, {f['protein_g']:g} g protein, {fib}; "
        "log its printed label" + (f"; with {items}" if items else "")
    )


def lines(menu: Mapping[str, Any]) -> list[str]:
    """The menu in words: one line per day (its target, what the anchors land at, its feedings) — templates over the
    code's numbers, no model."""
    out = []
    for d in menu.get("days") or []:
        t, tot = d.get("targets") or {}, d.get("totals") or {}
        if not d.get("feedings"):
            out.append(f"{d.get('weekday')} {d.get('date')}: not fitted ({'; '.join(d.get('misses') or [])})")
            continue
        fed = "; ".join(_feeding_line(f) for f in d["feedings"])
        verdict = "fits" if d.get("fits") else "DOES NOT FIT: " + "; ".join(d.get("misses") or [])
        out.append(
            f"{d['weekday']} {d['date']} ({d.get('day_type')}, {d.get('service')}): target {t.get('kcal')} kcal; "
            f"menu {tot.get('kcal'):g} kcal, protein {tot.get('protein_g'):g} g, fat {tot.get('fat_g'):g} g, "
            f"carbohydrate {tot.get('carb_g'):g} g, fibre {tot.get('fibre_g'):g} g — {verdict}. {fed}"
        )
    out.extend(grocery_lines(menu))  # before the quality line, which stays the last (the callers read lines[-1])
    q = menu.get("quality")
    if isinstance(q, dict):
        fish = q.get(food_quality.FISH) or {}
        head = "Food quality: " + (
            "every target met" if q.get("met") else "MISSED: " + "; ".join([*q.get("misses", []), *q.get("problems", [])])
        )
        if fish:
            head += f". Fatty fish {fish.get('servings'):g} serving(s) (target {fish['range'][0]}-{fish['range'][1]}) on {', '.join(fish.get('days') or []) or 'no day'}"
        out.append(f"{head}. {(q.get(food_quality.PRIORITIES) or {}).get('line', '')}".rstrip())
    return out
