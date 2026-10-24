"""health/travel_food.py — the travel food kit: a day built to the charter, its grocery list, the packing list and the
hotel/restaurant playbook (#5104 N10, epic #5092).

Owner rulings 2026-10-23: the late-December trip is a PLANNED MAINTENANCE WEEK (R3, #5107), so the food decisions are
made before he leaves, by mid-December; weekday meal service + weekend cooking at home (R6: the service does not
travel); no excluded foods (R7). Everything here is DETERMINISTIC — templates and arithmetic over the charter's numbers,
no model call — so there is no AI budget class to spend and nothing to hallucinate:

  1. THE TRAVEL DAY (`travel_day`): four protein feedings (`nutrition.protein.feedings_per_day`), each built from a
     fixed travel-friendly core at or above the feeding threshold, then the SIDES that best close the fat, carb and
     fibre floors (`nutrition.floors`) inside the day's calorie band, found by an exhaustive search over a small fixed
     grid (deterministic: the same target always yields the same day). The calorie target is the caller's — the one
     resolver (`health.calorie_target.resolve`, day type `travel`) for a deficit day, the maintenance estimate for the
     maintenance week. A floor the day cannot close inside the band is a WARNING with the gap, never hidden (the floors
     are warnings, charter `nutrition.calories.floor_role`).
  2. THE GROCERY LIST (`grocery_list`): any menu in the day shape (a list of `travel_day` outputs — N9's weekly menu, when
     it is built, can hand its own days to the same function) summed per item and turned into packages, grouped by store
     section; only the items bought at the destination.
  3. THE TRAVEL KIT (`travel_kit`): the shelf-stable items packed from home (servings x (trip days + spare days)) and
     the equipment that makes the day possible away from a kitchen.
  4. THE PLAYBOOK (`playbook`): hotel breakfast, restaurant, travel-day, convenience-store, maintenance-week and logging
     rules, every number read from the charter (or the resolved target), none restated.

PRIVACY (a PUBLIC repo): the foods are GENERIC — typical label values for common foods, no brand, no store, and nothing
from his food log. Owner-specific anchor foods belong to N9's owner-only table, never here. The kit is owner context;
`disruption.constraint` carries the playbook (the owner's plan block) and `get_exercise_notes action='travel_kit'`
serves the whole kit; no published surface reads this module.
"""

from __future__ import annotations

import datetime as _dt
import itertools
import math
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

VERSION = "travel-food@1.0.0"
ISSUE = "#5104"
CALIBRATION_KIND = "travel_food_kit"
SOURCE = "config/training_charter.json nutrition.travel_food + travel.windows (the trip's dates)"
MACROS = ("kcal", "protein_g", "carb_g", "fat_g", "fibre_g")
FLOOR_MACROS = ("fat", "carb", "fibre")

CharterReader = Callable[[str], Any]

# ── the generic foods (typical label values per serving; log the real label) ──────────────────────────────────────
# where: pack = shelf-stable, brought from home (the travel kit); buy = perishable, bought at the destination (the
# grocery list); order = a restaurant plate (the playbook). `package` turns servings into what is actually bought.
ITEMS: dict[str, dict[str, Any]] = {
    "whey": {
        "label": "whey protein, unflavoured or any flavour",
        "serving": "1 scoop (about 30 g)",
        "kcal": 120,
        "protein_g": 25,
        "carb_g": 2,
        "fat_g": 1.5,
        "fibre_g": 0,
        "where": "pack",
        "section": "protein",
        "package": {"label": "single-serve packet or a pre-measured bag", "servings": 1},
    },
    "greek_yogurt": {
        "label": "plain nonfat Greek yogurt",
        "serving": "1 single-serve cup (about 170 g)",
        "kcal": 100,
        "protein_g": 17,
        "carb_g": 6,
        "fat_g": 0.5,
        "fibre_g": 0,
        "where": "buy",
        "section": "dairy",
        "package": {"label": "4-pack of single cups", "servings": 4},
    },
    "tuna_pouch": {
        "label": "tuna or salmon pouch in water",
        "serving": "1 pouch (about 74 g)",
        "kcal": 80,
        "protein_g": 17,
        "carb_g": 0,
        "fat_g": 1,
        "fibre_g": 0,
        "where": "pack",
        "section": "protein",
        "package": {"label": "pouch", "servings": 1},
    },
    "jerky": {
        "label": "lean beef or turkey jerky",
        "serving": "1 oz (28 g)",
        "kcal": 80,
        "protein_g": 13,
        "carb_g": 4,
        "fat_g": 1,
        "fibre_g": 0,
        "where": "pack",
        "section": "protein",
        "package": {"label": "2.5 oz bag", "servings": 2.5},
    },
    "cooked_chicken": {
        "label": "ready-cooked chicken breast (rotisserie, grilled strips or a deli counter)",
        "serving": "5 oz cooked (about 140 g)",
        "kcal": 235,
        "protein_g": 44,
        "carb_g": 0,
        "fat_g": 5,
        "fibre_g": 0,
        "where": "buy",
        "section": "protein",
        "package": {"label": "10 oz pack of cooked breast", "servings": 2},
    },
    "lean_protein_plate": {
        "label": "a grilled lean protein (chicken, white fish, sirloin, shrimp)",
        "serving": "5 oz cooked, about a palm and a half",
        "kcal": 230,
        "protein_g": 42,
        "carb_g": 0,
        "fat_g": 6,
        "fibre_g": 0,
        "where": "order",
        "section": "restaurant",
        "package": None,
    },
    "vegetables": {
        "label": "non-starchy vegetables (salad greens, broccoli, green beans, peppers)",
        "serving": "1 cup",
        "kcal": 35,
        "protein_g": 2,
        "carb_g": 7,
        "fat_g": 0.2,
        "fibre_g": 2.5,
        "where": "buy",
        "section": "produce",
        "package": {"label": "12 oz bag or tray (about 4 cups)", "servings": 4},
    },
    "berries": {
        "label": "raspberries or blackberries",
        "serving": "1 cup",
        "kcal": 64,
        "protein_g": 1.5,
        "carb_g": 15,
        "fat_g": 0.8,
        "fibre_g": 8,
        "where": "buy",
        "section": "produce",
        "package": {"label": "6 oz clamshell (about 1.25 cups)", "servings": 1.25},
    },
    "chia": {
        "label": "chia seeds",
        "serving": "1 tablespoon (12 g)",
        "kcal": 58,
        "protein_g": 2,
        "carb_g": 5,
        "fat_g": 3.7,
        "fibre_g": 4,
        "where": "pack",
        "section": "pantry",
        "package": {"label": "pre-measured bag, by tablespoon", "servings": 1},
    },
    "avocado": {
        "label": "avocado",
        "serving": "half a medium avocado",
        "kcal": 120,
        "protein_g": 1.5,
        "carb_g": 6,
        "fat_g": 11,
        "fibre_g": 5,
        "where": "buy",
        "section": "produce",
        "package": {"label": "avocado", "servings": 2},
    },
    "olive_oil": {
        "label": "olive oil or an oil-based dressing",
        "serving": "1 tablespoon",
        "kcal": 120,
        "protein_g": 0,
        "carb_g": 0,
        "fat_g": 14,
        "fibre_g": 0,
        "where": "buy",
        "section": "pantry",
        "package": {"label": "single-serve packet or a small bottle", "servings": 1},
    },
    "almonds": {
        "label": "almonds or mixed nuts",
        "serving": "1 oz (28 g, about a small handful)",
        "kcal": 165,
        "protein_g": 6,
        "carb_g": 6,
        "fat_g": 14,
        "fibre_g": 3.5,
        "where": "pack",
        "section": "pantry",
        "package": {"label": "1 oz single-serve pack", "servings": 1},
    },
    "oats": {
        "label": "plain instant oats",
        "serving": "1 packet (28 g)",
        "kcal": 100,
        "protein_g": 4,
        "carb_g": 19,
        "fat_g": 2,
        "fibre_g": 3,
        "where": "pack",
        "section": "pantry",
        "package": {"label": "packet", "servings": 1},
    },
    "potato": {
        "label": "a baked potato or a cup of cooked rice",
        "serving": "1 medium potato or 3/4 cup cooked rice",
        "kcal": 160,
        "protein_g": 4,
        "carb_g": 37,
        "fat_g": 0.2,
        "fibre_g": 4,
        "where": "order",
        "section": "restaurant",
        "package": None,
    },
    "apple": {
        "label": "an apple, pear or orange",
        "serving": "1 medium fruit",
        "kcal": 95,
        "protein_g": 0.5,
        "carb_g": 25,
        "fat_g": 0.3,
        "fibre_g": 4.4,
        "where": "buy",
        "section": "produce",
        "package": {"label": "fruit", "servings": 1},
    },
}

# The four protein cores, in eating order. Each sits at or above the charter's feeding threshold on its own (the test
# reads the threshold from the charter), so every feeding counts whatever sides the search adds.
CORES: tuple[dict[str, Any], ...] = (
    {"name": "first feeding (the room: shaker + cup)", "items": {"whey": 1, "greek_yogurt": 1}},
    {"name": "lunch (grocery or deli)", "items": {"cooked_chicken": 1}},
    {"name": "afternoon (from the bag)", "items": {"tuna_pouch": 2, "jerky": 1}},
    {"name": "dinner (the restaurant plate)", "items": {"lean_protein_plate": 1}},
)

# The sides the search places: the feedings each rides in (servings dealt round-robin over them, so a large maintenance
# day spreads across meals instead of piling onto one plate) and its serving grid (whole servings, day total).
# Vegetables are never zero: lunch and the restaurant plate carry them by default.
SIDES: tuple[tuple[str, tuple[int, ...], tuple[int, ...]], ...] = (
    ("vegetables", (1, 3), (2, 3, 4)),
    ("berries", (0,), (0, 1, 2)),
    ("chia", (0,), (0, 1, 2, 3)),
    ("avocado", (1, 3), (0, 1, 2)),
    ("olive_oil", (3, 1), (0, 1, 2)),
    ("almonds", (2,), (0, 1, 2)),
    ("oats", (0,), (0, 1, 2)),
    ("potato", (3, 1), (0, 1, 2, 3)),
    ("apple", (2,), (0, 1)),
)
# The search's exchange rate between a floor gram short and a calorie off the target: the floors are warnings and the
# target is the owner's number (R1), so a gram short costs what the gram would have cost in calories (fat 9, carb and
# fibre 4) — no more.
KCAL_PER_G = {"fat": 9.0, "carb": 4.0, "fibre": 4.0}
# The everyday protein foods the convenience-store fallback names (their grams come from ITEMS).
FALLBACK = ("whey", "greek_yogurt", "cooked_chicken", "tuna_pouch", "jerky")

EQUIPMENT: tuple[str, ...] = (
    "a shaker bottle (the first feeding and any shake)",
    "the whey pre-measured into single-scoop bags or packets",
    "a tablespoon measure (chia, oil)",
    "zip bags and one lidded container (the afternoon feeding travels in the day bag)",
    "a small insulated bag with an ice pack (yogurt and chicken between the store and the room)",
    "travel cutlery; pouches rather than cans (no opener needed)",
)


# ── the charter numbers (one read each; the reader is injectable for tests) ─────────────────────────────────────────
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


def targets(kcal: Optional[float], read: Optional[CharterReader] = None) -> dict[str, Any]:
    """The day's numbers: the calorie target the caller resolved, and every floor and feeding rule from the charter."""
    read = read or _default_reader
    band = read("nutrition.calories.prescribed_band_kcal")
    edges = [_num(x) for x in band] if isinstance(band, (list, tuple)) and len(band) == 2 else []
    lo, hi = (edges[0], edges[1]) if len(edges) == 2 else (None, None)
    half = (hi - lo) / 2 if lo is not None and hi is not None and hi >= lo else None  # the band's half-width, centred on the target
    window = read("nutrition.eating_window") or {}
    return {
        "kcal": int(round(kcal)) if kcal is not None else None,
        "tolerance_kcal": int(half) if half is not None else None,
        "protein_floor_g": _num(read("nutrition.protein.range_g.low")),
        "feedings": int(_num(read("nutrition.protein.feedings_per_day")) or 0),
        "feeding_threshold_g": _num(read("nutrition.protein.feeding_threshold_g")),
        "feeding_target_g": read("nutrition.protein.feeding_target_g"),
        "eating_hours": _num(window.get("eating_hours")) if isinstance(window, dict) else None,
        "window_type": window.get("type") if isinstance(window, dict) else None,
        "floors_g": {m: _num(read(f"nutrition.floors.{m}.floor_g")) for m in FLOOR_MACROS},
        "post_session": read("nutrition.training_day.post_session"),
        "core_habits": read("habits.core") or [],
    }


# ── the day ───────────────────────────────────────────────────────────────────────────────────────────────────
def _totals(counts: Mapping[str, float]) -> dict[str, float]:
    return {m: round(sum(ITEMS[k][m] * n for k, n in counts.items()), 1) for m in MACROS}


def _shortfall(tot: Mapping[str, float], floors: Mapping[str, Optional[float]]) -> float:
    """The floor gap in calorie terms (KCAL_PER_G)."""
    return sum(KCAL_PER_G[m] * max(0.0, (f or 0.0) - tot[f"{m}_g"]) for m, f in floors.items())


def _search(core_counts: Mapping[str, float], t: Mapping[str, Any]) -> tuple[dict[str, int], dict[str, float]]:
    """The side servings that best close the floors near the target: exhaustive over the fixed grid, lexicographic —
    inside the band first, then the smallest (floor gap + distance from the target) in calories, then the fewest
    servings. Deterministic: the same target always yields the same day."""
    kcal, tol, floors = float(t["kcal"]), float(t["tolerance_kcal"] or 0), t["floors_g"]
    base = _totals(core_counts)
    names = [s[0] for s in SIDES]
    best: Optional[tuple[tuple[float, ...], dict[str, int], dict[str, float]]] = None
    for combo in itertools.product(*(s[2] for s in SIDES)):
        tot = dict(base)
        for k, n in zip(names, combo):
            if n:
                for m in MACROS:
                    tot[m] += ITEMS[k][m] * n
        outside = max(0.0, abs(tot["kcal"] - kcal) - tol)
        key = (round(outside, 1), round(_shortfall(tot, floors) + abs(tot["kcal"] - kcal), 1), float(sum(combo)))
        if best is None or key < best[0]:
            best = (key, dict(zip(names, combo)), tot)
    assert best is not None  # the grid is never empty
    return best[1], {m: round(v, 1) for m, v in best[2].items()}


def _feeding(name: str, counts: Mapping[str, float]) -> dict[str, Any]:
    items = [{"item": k, "servings": n, "label": ITEMS[k]["label"], "serving": ITEMS[k]["serving"]} for k, n in counts.items() if n]
    return {"name": name, "items": items, **_totals(counts)}


def travel_day(kcal: Optional[float], *, read: Optional[CharterReader] = None, label: str = "travel day") -> dict[str, Any]:
    """One day of food built to the charter at `kcal` (the caller's resolved target). Never raises: an unresolved
    target or an unreadable charter is `{built: False, reason}`, never a remembered number."""
    t = targets(kcal, read)
    if t["kcal"] is None or not t["feedings"] or t["protein_floor_g"] is None or t["feeding_threshold_g"] is None:
        return {
            "label": label,
            "built": False,
            "reason": "no calorie target resolved or the charter's protein rules are unreadable",
            "targets": t,
        }
    cores = [CORES[i % len(CORES)] for i in range(t["feedings"])]
    core_counts: dict[str, float] = {}
    for c in cores:
        for k, n in c["items"].items():
            core_counts[k] = core_counts.get(k, 0) + n
    sides, tot = _search(core_counts, t)
    per: list[dict[str, float]] = [dict(c["items"]) for c in cores]
    for k, slots, _grid in SIDES:
        usable = [x for x in slots if x < len(per)] or [len(per) - 1]
        for i in range(sides[k]):
            slot = usable[i % len(usable)]
            per[slot][k] = per[slot].get(k, 0) + 1
    feedings = [_feeding(c["name"], counts) for c, counts in zip(cores, per)]
    warnings = []
    for m, f in t["floors_g"].items():
        if f is not None and tot[f"{m}_g"] < f:
            warnings.append(
                f"{m} {tot[f'{m}_g']:g} g is {f - tot[f'{m}_g']:g} g under its {f:g} g floor inside this calorie band (a warning)"
            )
    lo, hi = t["kcal"] - (t["tolerance_kcal"] or 0), t["kcal"] + (t["tolerance_kcal"] or 0)
    checks = {
        "kcal_in_band": lo <= tot["kcal"] <= hi,
        "protein_at_floor": tot["protein_g"] >= t["protein_floor_g"],
        "every_feeding_counts": all(fd["protein_g"] >= t["feeding_threshold_g"] for fd in feedings),
        **{f"{m}_at_floor": (f is None or tot[f"{m}_g"] >= f) for m, f in t["floors_g"].items()},
    }
    if not checks["kcal_in_band"]:
        warnings.append(f"the day lands at {tot['kcal']:g} kcal, outside {lo}-{hi}: the side grid cannot reach this target")
    return {"label": label, "built": True, "targets": t, "feedings": feedings, "totals": tot, "checks": checks, "warnings": warnings}


# ── the menu, the grocery list and the kit ───────────────────────────────────────────────────────────────────
def _day_counts(day: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for fd in day.get("feedings") or []:
        for it in fd.get("items") or []:
            out[it["item"]] = out.get(it["item"], 0) + float(it["servings"])
    return out


def menu_counts(menu: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Servings per item over a menu (a list of days in the `travel_day` shape)."""
    out: dict[str, float] = {}
    for day in menu:
        for k, n in _day_counts(day).items():
            out[k] = out.get(k, 0) + n
    return out


def _line(k: str, servings: float) -> dict[str, Any]:
    it, pkg = ITEMS[k], ITEMS[k].get("package") or {}
    per = float(pkg.get("servings") or 1)
    return {
        "item": k,
        "label": it["label"],
        "servings": round(servings, 2),
        "serving": it["serving"],
        "packages": math.ceil(round(servings / per, 6)),
        "package": pkg.get("label"),
    }


def grocery_list(menu: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The destination shop for a menu, by store section: only the `buy` items, servings summed, packages rounded up."""
    out: dict[str, list[dict[str, Any]]] = {}
    for k, n in sorted(menu_counts(menu).items()):
        if ITEMS[k]["where"] == "buy" and n > 0:
            out.setdefault(ITEMS[k]["section"], []).append(_line(k, n))
    return out


def travel_kit(menu: Sequence[Mapping[str, Any]], spare_days: int = 0) -> dict[str, Any]:
    """What is packed from home: the menu's `pack` items plus `spare_days` of them (a delay, a missed shop), and the
    equipment."""
    days = max(1, len(menu))
    out = []
    for k, n in sorted(menu_counts(menu).items()):
        if ITEMS[k]["where"] == "pack" and n > 0:
            out.append(_line(k, n * (days + spare_days) / days))
    return {"food": out, "equipment": list(EQUIPMENT), "spare_days": spare_days}


def _g(k: str, n: float = 1) -> float:
    return round(float(ITEMS[k]["protein_g"]) * n, 1)


def _bag_line() -> str:
    """The afternoon core in words with its own grams (from ITEMS, never a restated number)."""
    core = CORES[2]["items"]
    parts = [f"{n:g} x {ITEMS[k]['label']} ({ITEMS[k]['serving']})" for k, n in core.items()]
    return " + ".join(parts) + f" = {sum(_g(k, n) for k, n in core.items()):g} g protein"


def _per_serving_line() -> str:
    return "; ".join(f"{ITEMS[k]['label']} {ITEMS[k]['serving']} {_g(k):g} g" for k in FALLBACK)


def _fallback_example(thr: Optional[float]) -> str:
    """The first pair of fallback foods (in FALLBACK order) that clears the threshold, with its sum."""
    for a, b in itertools.combinations(FALLBACK, 2):
        if thr is not None and _g(a) + _g(b) >= thr:
            return f" (e.g. {ITEMS[a]['label']} + {ITEMS[b]['label']} = {_g(a) + _g(b):g} g)"
    return ""


# ── the playbook (rules with the charter's numbers) ──────────────────────────────────────────────────────────
def playbook(
    t: Mapping[str, Any], *, day: Optional[Mapping[str, Any]] = None, maintenance_kcal: Optional[int] = None
) -> list[dict[str, Any]]:
    """The hotel/restaurant playbook. `t` = `targets(...)`; `day` = a built travel day (its feeding sizes become the
    per-meal budgets); `maintenance_kcal` = the maintenance week's target when known."""
    kcal = f"{t['kcal']} kcal" if t.get("kcal") is not None else "the day's resolved target"
    thr, n, ftg = t.get("feeding_threshold_g"), t.get("feedings"), t.get("feeding_target_g") or []
    aim = f"{ftg[0]:g}-{ftg[1]:g} g" if isinstance(ftg, (list, tuple)) and len(ftg) == 2 else f"at least {thr:g} g"
    floors = ", ".join(f"{m} {v:g} g" for m, v in (t.get("floors_g") or {}).items() if v is not None)
    budget = {fd["name"]: int(fd["kcal"]) for fd in (day or {}).get("feedings") or []}
    dinner = next((v for k, v in budget.items() if k.startswith("dinner")), None)
    post = t.get("post_session") or {}
    bag, per_serving, example = _bag_line(), _per_serving_line(), _fallback_example(thr)
    scoops = max(1, math.ceil((thr or 0) / float(ITEMS["whey"]["protein_g"])))
    habits = [str(h.get("label")) for h in t.get("core_habits") or [] if isinstance(h, dict) and h.get("label")]
    out: list[dict[str, Any]] = [
        {
            "section": "the numbers",
            "rules": [
                f"{kcal}; protein at least {t.get('protein_floor_g'):g} g in {n} feedings of {aim}, each at least {thr:g} g to count.",
                f"All {n} feedings inside one {t.get('eating_hours'):g}-hour eating window ({t.get('window_type')}), on local time from the first one.",
                f"The floors to aim at: {floors}. A floor the day misses is a warning, never a reason to skip a feeding.",
            ],
        },
        {
            "section": "hotel breakfast",
            "rules": [
                f"Protein first: the first feeding is {thr:g} g or more before anything else (eggs or egg whites, Greek yogurt, a shake from the bag).",
                "Fruit and vegetables next; a pastry or a juice is not banned (no food is excluded), it is paid for out of the day.",
            ],
        },
        {
            "section": "restaurant",
            "rules": [
                "Order the protein first: a grilled lean protein about a palm and a half (5 oz cooked), vegetables doubled.",
                "Sauces and dressings on the side; a tablespoon of oil or dressing is about 120 kcal and gets logged.",
                (f"The dinner plate is about {dinner} kcal in this plan; " if dinner else "")
                + "a potato or rice side fits when what is left of the day has room for it.",
                "Log the closest database entry for the plate, with an estimate for the oil. An estimate beats a blank day.",
            ],
        },
        {
            "section": "travel days (airport, car, flight)",
            "rules": [
                f"The afternoon feeding travels in the day bag with no fridge: {bag}.",
                f"A {scoops}-scoop shake in water ({_g('whey', scoops):g} g) is a whole feeding when a meal time falls in transit.",
                "Water before caffeine; the eating window restarts on local time from the first feeding at the destination.",
            ],
        },
        {
            "section": "convenience-store fallback",
            "rules": [
                f"Protein per serving: {per_serving}. Add servings until they pass {thr:g} g{example}.",
                "Add a piece of fruit or a nut pack for the floors.",
            ],
        },
        {
            "section": "maintenance week (owner ruling 2026-10-23 R3, #5107)",
            "rules": [
                (
                    f"The calorie target this week is the maintenance estimate, {maintenance_kcal} kcal: the same day, larger sides."
                    if maintenance_kcal
                    else "The calorie target this week is the maintenance estimate (#5107 sets it): the same day, larger sides."
                ),
                f"Protein, the {n} feedings and the eating window do not change; only the sides grow.",
                "Steps and the short sessions are held as in disruption mode; the scale is read, not chased, this week.",
            ],
        },
        {
            "section": "before you leave",
            "rules": [
                "Pause the weekday meal service for the trip dates and restart it for the week you return (owner ruling R6).",
                "Pack the travel kit; shop the grocery list on arrival day.",
                "Tell the coach the trip dates so they land in the charter's travel window, then switch disruption mode on (template travel).",
            ],
        },
    ]
    if habits:
        out.append(
            {
                "section": "the core habits travel too",
                "rules": [
                    f"No food is excluded from the plan (owner ruling R7); the core habits still count every day: {', '.join(habits)}."
                ],
            }
        )
    if isinstance(post, dict) and post.get("protein_g"):
        out[0]["rules"].append(f"On a session day the post-session feeding ({post['protein_g']:g} g protein) is one of the {n}.")
    return out


# ── the whole kit (the MCP read) and the disruption mode's view ──────────────────────────────────────────────
def policy(read: Optional[CharterReader] = None) -> dict[str, Any]:
    """The charter's `nutrition.travel_food` block, as read."""
    v = (read or _default_reader)("nutrition.travel_food")
    return dict(v) if isinstance(v, dict) else {}


def _window(read: CharterReader, label: Any) -> dict[str, Any]:
    for w in read("travel.windows") or []:
        if isinstance(w, dict) and (label is None or w.get("label") == label):
            return w
    return {}


def trip_days(read: Optional[CharterReader] = None) -> tuple[int, str]:
    """(days, basis): the window's own dates when set, else the charter's default trip length."""
    read = read or _default_reader
    pol = policy(read)
    w = _window(read, pol.get("window_label"))
    s, e = _day(w.get("start")), _day(w.get("end"))
    if s and e and e >= s:
        return (e - s).days + 1, f"travel window {w.get('label')} {s.isoformat()}..{e.isoformat()}"
    return int(_num(pol.get("default_trip_days")) or 7), "nutrition.travel_food.default_trip_days (the trip dates are not set)"


def build(
    kcal: Optional[float], *, maintenance_kcal: Optional[float] = None, days: Optional[int] = None, read: Optional[CharterReader] = None
) -> dict[str, Any]:
    """The whole kit: the deficit travel day at `kcal`, the maintenance day when `maintenance_kcal` is known, the menu
    (the trip's days at the maintenance day when the trip is a maintenance week and its target is known, else the
    deficit day), the grocery list, the packing list and the playbook."""
    read = read or _default_reader
    pol = policy(read)
    n_days, basis = (days, "requested") if days else trip_days(read)
    deficit = travel_day(kcal, read=read, label="travel day at the resolved target")
    maint = travel_day(maintenance_kcal, read=read, label="maintenance-week day") if maintenance_kcal else None
    use = maint if (pol.get("maintenance_week") and maint and maint.get("built")) else deficit
    menu = [use] * n_days if use.get("built") else []
    t = use.get("targets") or targets(kcal, read)
    return {
        "version": VERSION,
        "issue": ISSUE,
        "tier": "owner_only",
        "window": pol.get("window_label"),
        "ready_by": pol.get("ready_by"),
        "trip_days": n_days,
        "trip_days_basis": basis,
        "maintenance_week": bool(pol.get("maintenance_week")),
        "menu_day": use.get("label"),
        "days": {"deficit": deficit, "maintenance": maint},
        "maintenance_pending": None if maint else "no maintenance estimate given: pass maintenance_kcal (#5107 sets the estimate)",
        "grocery_list": grocery_list(menu),
        "travel_kit": travel_kit(menu, int(_num(pol.get("spare_days")) or 0)),
        "playbook": playbook(
            t, day=use if use.get("built") else None, maintenance_kcal=int(maintenance_kcal) if maintenance_kcal else None
        ),
        "rulings": {k: pol.get(k) for k in ("meal_service", "excluded_foods_rule", "maintenance_rule")},
        "values": "generic typical label values per serving (no brand, nothing from the food log): log the real label",
    }


def mode_view(template: Optional[str], *, offered: bool = False, read: Optional[CharterReader] = None) -> Optional[dict[str, Any]]:
    """What disruption mode carries on a travel day (or when it offers a travel window): the playbook with the charter's
    numbers (the calorie line points at the day's resolved target, never a restated number) and where the whole kit is.
    None off a travel template."""
    if template != "travel":
        return None
    t = targets(None, read)
    return {
        "playbook": playbook(t),
        "offered_only": offered,
        "kit": "get_exercise_notes action='travel_kit' (the grocery list, the packing list, the day plan)",
        "kcal": "the day's resolved target: constraint_block.training_day_fuel (day type travel)",
        "issue": ISSUE,
    }


# ── the dated reminder (one calibration-cadence row) ─────────────────────────────────────────────────────────
def _day(v: Any) -> Optional[_dt.date]:
    from common.pacific_time import parse_day_key  # noqa: PLC0415 — THE calendar-day parse; no clock is read

    return parse_day_key(str(v)[:10]) if v else None


def calibration_row(today: str, read: Optional[CharterReader] = None) -> dict[str, Any]:
    """The travel_food_kit row for `today` (#5104). Never raises.

    ok        before the prompt window; the trip dates are set (the kit is sized and the mode can offer); or after
              `retire_after` (the trip is behind him)
    due       from `prompt_days_before_ready` days before `ready_by`: one prompt (the key is the window's start)
    missed_2  from `ready_by` with the trip dates still unset: the dead-man, fixed text
    unknown   the charter carries no ready-by date or no prompt days (nothing is guessed)
    """
    from training import calibration_cadence as cc  # noqa: PLC0415 — the shared state names

    read = read or _default_reader
    pol = policy(read)
    base: dict[str, Any] = {"kind": CALIBRATION_KIND, "source": SOURCE, "prompt": None, "last_logged": None, "missed_cycles": 0}
    t, ready, retire = _day(today), _day(pol.get("ready_by")), _day(pol.get("retire_after"))
    lead = _num(pol.get("prompt_days_before_ready"))
    if t is None or ready is None or lead is None or lead < 0:
        return {**base, "state": cc.UNKNOWN, "detail": "no valid today, or the charter carries no travel_food ready_by / prompt days"}
    due = ready - _dt.timedelta(days=int(lead))
    row = {
        **base,
        "cycle_start": due.isoformat(),
        "due_on": due.isoformat(),
        "dead_man_on": ready.isoformat(),
        "days_until_due": (due - t).days,
        "prompt_key": cc.prompt_key(CALIBRATION_KIND, due.isoformat()),
    }
    w = _window(read, pol.get("window_label"))
    label = pol.get("window_label") or "the trip"
    if retire is not None and t > retire:
        return {**row, "state": cc.OK, "detail": f"{label} is past (retire_after {retire.isoformat()})"}
    if _day(w.get("start")) and _day(w.get("end")):
        return {**row, "state": cc.OK, "detail": f"the trip dates are set ({w.get('start')}..{w.get('end')}): the kit is sized to them"}
    if t < due:
        return {**row, "state": cc.OK}
    lead_days = read("disruption.offer.travel_lead_days")
    if t < ready:
        row["state"] = cc.DUE
        row["prompt"] = (
            f"The travel food kit for {label} is ready: ask your coach for it (get_exercise_notes action='travel_kit') for the "
            "grocery list, the packing list and the hotel/restaurant playbook. Tell your coach the trip dates so they land in "
            f"the charter's travel window before {ready.isoformat()}: the kit sizes to them and disruption mode offers itself "
            f"{lead_days} days ahead."
        )
        return row
    return {
        **row,
        "state": cc.MISSED_2,
        "missed_cycles": 1,
        "alert": (
            f"{label}: the travel food kit is ready but the trip dates are still not set, so the kit is sized to a default "
            "length and disruption mode cannot offer itself. Tell your coach the dates this week."
        ),
    }
