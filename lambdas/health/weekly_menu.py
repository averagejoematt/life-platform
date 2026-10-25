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
     A day whose own rotation ends unfit is searched again from the next rotations before it is called unfit; the
     best of them is kept.
  3. THE CHECK: kcal inside the day's band (the resolved kcal +/- half the prescribed band's width), protein at the
     range low, every feeding at its threshold, every floor met. `fits` is all of them; `misses` names each one short.

THE FOOD-QUALITY TARGETS (#5105, `nutrition.food_quality`, read and checked by `health.food_quality`): the fibre floor is
one of the day's floors above (the ONE fibre floor); the fatty-fish weekly range is enforced across the week — every day
is fitted with the fatty-fish anchors (rows tagged `fatty_fish: true`) kept off it, then the range's low end is placed
as one pinned serving on each of that many spread days (`_fit_week`); the owner-only lab-driven priorities row, when the
caller holds it, rides the report. The menu's `quality` names every target the week misses (`quality.misses`) and every
unreadable one (`quality.problems`) — never silently — and `food_plan` carries the rows the food panel checks the same way.

The feedings are laid inside the one eating window (`nutrition.eating_window`): feeding i opens at i x (eating hours /
feedings) hours after the window opens, so all of them sit inside it. On a lifting day one feeding is the post-session
feeding (it moves with the session; the window offset is where it sits when the session is mid-window).

NO MODEL CALL. The issue's box is "AI writes prose only; numbers come from code"; this module writes no prose a model
would add value to, so there is no Bedrock call and no budget class — the menu's lines are templates over the code's
numbers (`lines`). The grocery list (#5104 box 1, "generated from the menu") reads the cook days of this menu.

OWNER-ONLY. The menu carries his foods: it is served on the owner's MCP read (`get_exercise_notes action='weekly_menu'`)
and nowhere public.
"""

from __future__ import annotations

import copy
import itertools
import logging
import math
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from health import food_quality, travel_food

logger = logging.getLogger(__name__)

VERSION = "weekly-menu@1.1.0"  # 1.1.0 #5105: the food-quality targets (fatty fish placed, the quality report)
ISSUE = "#5103"
POLICY_PATH = "nutrition.weekly_menu"
ANCHORS_PATH = "anchor_foods"  # the owner-only twin's key (training_charter.PRIVATE_KEYS)
MACROS = travel_food.MACROS  # kcal, protein_g, carb_g, fat_g, fibre_g
GRAMS = ("protein_g", "carb_g", "fat_g", "fibre_g")
# The exchange rate between a floor gram short and a calorie: the Atwater factors (fibre at the carbohydrate rate, as
# the travel kit's search prices it). A physical constant of the search, not a target.
ATWATER = {"protein_g": 4.0, "carb_g": 4.0, "fat_g": 9.0, "fibre_g": 4.0}
# Bound on the local search (moves taken per day); every move strictly lowers the cost, so it ends far sooner.
MAX_MOVES = 400
POST_SESSION = "post_session"
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SERVICE_COOK, SERVICE_MEAL = "cook", "meal_service"

# The named reasons a menu is not built (built=False) or a day does not fit. A caller states the reason; it never
# substitutes a remembered menu.
NO_ANCHOR_TABLE = "no_anchor_table"
TOO_FEW_ANCHORS = "too_few_anchors"
NO_FEEDING_CORE = "no_feeding_core"
NO_CALORIE_TARGET = "no_calorie_target"
NO_POLICY = "no_policy"
NO_PLAN = "no_plan"
DAY_UNFIT = "day_unfit"
REASON_CODES = (NO_ANCHOR_TABLE, TOO_FEW_ANCHORS, NO_FEEDING_CORE, NO_CALORIE_TARGET, NO_POLICY, NO_PLAN, DAY_UNFIT)

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
                **food_quality.tags(row),  # #5105: fatty_fish, nutrient_tags (optional columns)
            }
        )
    usable.sort(key=lambda a: a["id"])
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


def _lay_out(
    cores: Sequence[Counts], sides: Counts, t: Mapping[str, Any], post_slot: Optional[int], by_id: Mapping[str, Any]
) -> list[dict]:
    """The day's feedings: the cores in order, each side serving dealt to the feeding with the fewest kcal so far
    (largest sides first, ids breaking ties), each feeding placed in the window."""
    per = [dict(c) for c in cores]
    kcal = [_totals(c, by_id)["kcal"] for c in per]
    servings = sorted(((by_id[k]["kcal"], k) for k, n in sides.items() for _ in range(n)), key=lambda x: (-x[0], x[1]))
    for k_kcal, k in servings:
        i = min(range(len(per)), key=lambda j: (kcal[j], j))
        per[i][k] = per[i].get(k, 0) + 1
        kcal[i] += k_kcal
    hours = _num(t.get("eating_hours"))
    step = hours / len(per) if hours and per else None
    out = []
    for i, counts in enumerate(per):
        when = POST_SESSION if i == post_slot else ("first" if i == 0 else "meal")
        need = t["post_session_protein_g"] if i == post_slot else t["feeding_threshold_g"]
        items = [
            {"item": k, "servings": n, "label": by_id[k]["label"], "serving": by_id[k]["serving"]} for k, n in sorted(counts.items()) if n
        ]
        out.append(
            {
                "name": f"feeding {i + 1}" + (" (post-session)" if when == POST_SESSION else ""),
                "when": when,
                "window_offset_h": round(i * step, 2) if step is not None else None,
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
) -> dict[str, Any]:
    """One plan day fitted from the anchors. `index` is the day's position in the week (the core rotation). `exclude`
    keeps anchors off the day; `fixed` pins servings into it (counted, never moved) — the week's fatty-fish placement
    (#5105) uses both."""
    t = day_targets(day, read)
    weekday = WEEKDAY_NAMES[datetime.strptime(str(day.get("date"))[:10], "%Y-%m-%d").weekday()]  # a calendar-day key
    base = {
        "date": day.get("date"),
        "weekday": weekday,
        "day_type": day.get("day_type"),
        "service": SERVICE_COOK if weekday in pol["cook_days"] else SERVICE_MEAL,
        "targets": t,
    }
    if not _ready(t):
        return {**base, "fits": False, "reason_code": NO_CALORIE_TARGET, "misses": ["no resolved kcal or an unreadable charter rule"]}
    by_id = {a["id"]: a for a in anchors}
    pinned: Counts = {k: int(n) for k, n in (fixed or {}).items() if n and k in by_id}
    off = set(exclude) | set(pinned)
    anchors = [a for a in anchors if a["id"] not in off]  # the foods the search may move
    caps = {a["id"]: int(a["cap"]) for a in anchors}
    fixed_vec = _vec(pinned, by_id)
    post_slot = 1 if (t["post_session_protein_g"] is not None and t["feedings"] > 1) else (0 if t["post_session_protein_g"] else None)
    share = float(t["kcal"]) / t["feedings"]  # a core is at most one feeding's share of the day: protein-led, never a whole meal plan
    cores = [c for c in feeding_cores(anchors, float(t["feeding_threshold_g"]), pol["core_max"]) if _totals(c, by_id)["kcal"] <= share]
    post_cores = (
        [c for c in feeding_cores(anchors, float(t["post_session_protein_g"]), pol["core_max"]) if _totals(c, by_id)["kcal"] <= share]
        if post_slot is not None
        else cores
    )
    if not cores or not post_cores:
        return {
            **base,
            "fits": False,
            "reason_code": NO_FEEDING_CORE,
            "misses": ["no anchor combination reaches the feeding threshold inside one feeding's share of the day's kcal"],
        }
    pools = [post_cores if slot == post_slot else cores for slot in range(t["feedings"])]
    best: Optional[dict[str, Any]] = None
    span = t["feedings"] + len(WEEKDAY_NAMES)  # the rotation pool's size (see _pick_cores)
    for offset in [(index + j) % span for j in range(span)]:  # the day's own rotation first, then the next starts
        start = _pick_cores(cores, post_cores, t["feedings"], post_slot, offset, caps)
        if start is None:
            continue
        picked, sides = _search_day(start, pools, anchors, t, fixed_vec)
        sides = _merge(sides, pinned)
        feedings = _lay_out(picked, sides, t, post_slot, by_id)
        tot = _totals(_used(picked, sides), by_id)
        checks, misses = _check(tot, feedings, t)
        cand = {"feedings": feedings, "totals": tot, "checks": checks, "misses": misses, "fits": all(checks.values()), "rotation": offset}
        if best is None or _cost(tot, t) < _cost(best["totals"], t):
            best = cand
        if cand["fits"]:
            break
    if best is None:
        return {**base, "fits": False, "reason_code": NO_FEEDING_CORE, "misses": ["the serving caps cannot hold one core per feeding"]}
    return {**base, **best, "reason_code": None if best["fits"] else DAY_UNFIT}


# ── the week ──────────────────────────────────────────────────────────────────────────────────────────────────
def _refused(code: str, reason: str, **extra: Any) -> dict[str, Any]:
    logger.warning("weekly menu not built: %s (%s)", code, reason)
    return {"version": VERSION, "issue": ISSUE, "tier": "owner_only", "built": False, "reason_code": code, "reason": reason, **extra}


def _fish_ids(anchors: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(a["id"] for a in anchors if a.get("fatty_fish"))


def _fit_week(
    days: Sequence[Mapping[str, Any]],
    anchors: Sequence[Mapping[str, Any]],
    pol: Mapping[str, Any],
    qpol: Mapping[str, Any],
    read: CharterReader,
) -> list[dict[str, Any]]:
    """Every day fitted, with the fatty-fish target enforced (#5105): every day is first fitted with the fatty-fish
    anchors kept off it, then the low end of the charter's weekly range is placed — one pinned serving on each of that
    many days, spread across the week (the day nearest each even slot first, the next nearest when a day cannot fit
    it), the fish anchors taken in turn. A day the fish-free fit cannot build (fish was its only protein core) is
    fitted with fish allowed; the quality report then names any count outside the range. With no readable range or no
    tagged anchor the week is fitted as before."""
    fish = _fish_ids(anchors)
    rng = qpol.get("fish_range")
    if not fish or rng is None:
        return [fit_day(d, anchors, pol, i, read) for i, d in enumerate(days)]
    fitted = []
    for i, d in enumerate(days):
        day = fit_day(d, anchors, pol, i, read, exclude=fish)
        fitted.append(fit_day(d, anchors, pol, i, read) if day.get("reason_code") == NO_FEEDING_CORE else day)
    placed = [sum(i_["servings"] for f in d.get("feedings") or [] for i_ in f["items"] if i_["item"] in fish) for d in fitted]
    free = [i for i, n in enumerate(placed) if not n]
    need = max(0, math.ceil(rng[0] - sum(placed)))
    chosen: set[int] = set()
    for k in range(min(need, len(free))):
        ideal = (k + 0.5) * len(days) / need
        for i in sorted(free, key=lambda j: (abs(j + 0.5 - ideal), j)):
            if i in chosen:
                continue
            cand = fit_day(days[i], anchors, pol, i, read, exclude=fish, fixed={fish[k % len(fish)]: 1})
            if cand.get("fits") or (not fitted[i].get("fits") and cand.get("feedings")):
                fitted[i] = cand
                chosen.add(i)
                break
    return fitted


def build(
    plan: Optional[Mapping[str, Any]],
    *,
    read: Optional[CharterReader] = None,
    anchors_raw: Any = None,
    priorities: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """The week's menu over a `food_panel.build_food_plan` plan. `anchors_raw` is the anchor table (default: the
    owner-only twin's `anchor_foods`); `priorities` is the owner-only lab-driven priorities row
    (`training.lab_priorities.from_rows`, #5111) when the caller holds one. Never raises: an unbuildable menu is
    `{built: False, reason_code, reason}` with a code from REASON_CODES; a built menu with a day the anchors cannot fit
    carries `fits_all: False`, `reason_code: day_unfit` and each day's misses; a week that misses a food-quality target
    (#5105) carries `quality_met: False` and each miss named in `quality.misses`."""
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
    qpol = food_quality.policy(read)
    fitted = _fit_week(days, anchors, pol, qpol, read)
    refused = next((d for d in fitted if d.get("reason_code") in (NO_CALORIE_TARGET, NO_FEEDING_CORE)), None)
    if refused is not None:
        return _refused(str(refused["reason_code"]), f"{refused['date']}: {'; '.join(refused['misses'])}", anchor_problems=problems)
    unfit = [d for d in fitted if not d["fits"]]
    if unfit:
        logger.warning("weekly menu: %d day(s) the anchors cannot fit: %s", len(unfit), [(d["date"], d["misses"]) for d in unfit])
    by_id = {a["id"]: a for a in anchors}
    note = "" if _fish_ids(anchors) else "no anchor in the table is tagged fatty_fish"
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
    menu["grocery_list"] = grocery_list(menu, anchors)
    menu["lines"] = lines(menu)
    return menu


# ── what reads the menu: the panel's plan, the grocery list, the words ────────────────────────────────────────
def food_plan(plan: Mapping[str, Any], menu: Mapping[str, Any]) -> dict[str, Any]:
    """The food plan with each day's intended feedings replaced by the MENU's (the grams the anchors actually carry,
    the post-session one tagged) — the plan `training.food_panel.prescore` grades. A copy; the plan is untouched."""
    out = copy.deepcopy(dict(plan))
    by_date = {d["date"]: d for d in menu.get("days") or [] if d.get("feedings")}
    for d in out.get("days") or []:
        m = by_date.get(d.get("date"))
        if m is not None:
            d["feedings"] = [{"when": f["when"], "protein_g": f["protein_g"]} for f in m["feedings"]]
    out["case_id"] = f"{out.get('case_id') or 'food'}::menu"
    q = menu.get("quality") or {}
    out["quality_days"] = q.get("rows") or []  # #5105: what training.food_panel checks the week's quality targets over
    return out


def _days(menu: Mapping[str, Any], which: str) -> list[Mapping[str, Any]]:
    days = [d for d in menu.get("days") or [] if d.get("feedings")]
    return days if which == "all" else [d for d in days if d.get("service") == SERVICE_COOK]


def grocery_list(menu: Mapping[str, Any], anchors: Iterable[Mapping[str, Any]], which: str = SERVICE_COOK) -> list[dict[str, Any]]:
    """The shop for the menu's cook days (`which='all'` for every day): servings per anchor summed over the days
    (`travel_food.menu_counts`, the same day shape), packages rounded up from the anchor's own package size."""
    by_id = {a["id"]: a for a in anchors}
    out = []
    for k, n in sorted(travel_food.menu_counts(_days(menu, which)).items()):
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
            }
        )
    return out


def lines(menu: Mapping[str, Any]) -> list[str]:
    """The menu in words: one line per day (its target, what the anchors land at, its feedings) — templates over the
    code's numbers, no model."""
    out = []
    for d in menu.get("days") or []:
        t, tot = d.get("targets") or {}, d.get("totals") or {}
        if not d.get("feedings"):
            out.append(f"{d.get('weekday')} {d.get('date')}: not fitted ({'; '.join(d.get('misses') or [])})")
            continue
        fed = "; ".join(
            f"{f['name']} (+{f['window_offset_h']:g} h): " + ", ".join(f"{i['servings']:g} x {i['label']}" for i in f["items"])
            for f in d["feedings"]
        )
        verdict = "fits" if d.get("fits") else "DOES NOT FIT: " + "; ".join(d.get("misses") or [])
        out.append(
            f"{d['weekday']} {d['date']} ({d.get('day_type')}, {d.get('service')}): target {t.get('kcal')} kcal; "
            f"menu {tot.get('kcal'):g} kcal, protein {tot.get('protein_g'):g} g, fat {tot.get('fat_g'):g} g, "
            f"carbohydrate {tot.get('carb_g'):g} g, fibre {tot.get('fibre_g'):g} g — {verdict}. {fed}"
        )
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
