"""live_volume.py — THE one weekly volume plan and THE one time fit of the live engine (#5861, fix round 9: consolidation). LIVE only.

Fix rounds 1-8 grew about twelve interacting volume mechanisms (an allocation, a parity rule, a priority add, at-MAV donors, a
quadriceps slot, a week floor, an abs floor, an arms floor, a trunk floor with its fallback order, cardio-room trims, a set cap
and a time fit) — several of them only there to undo another. Round 9 replaces them with two:

  1. ONE WEEKLY HARD-SET PLAN PER MUSCLE (`week_plan`). From the mornings declared this week, each muscle gets a target:
       * a priority muscle (`priority_muscles`) a floor of MEV and an aim a quarter of the way to MAV;
       * every other muscle a floor of its maintenance volume (MV), never more than its MAV;
       * direct abs `abs_direct_sets_per_week` (halved on a 1-3 morning or high-fatigue week);
       * each delt head counted apart with explicit fractional credit (pressing -> front and, overhead, half a side; rowing ->
         rear), side and rear each with an aim (owner ruling #9);
       * on a 1-3 morning week, each priority muscle and each major pattern at maintenance: MV x mornings / 3 (2-3 sets min).
     The template week is sized to it: isolation surplus over MAV gives first; a muscle under its aim grows its own isolation
     slots (never past 3 sets), then takes its FILL movement as a 2-set slot on the drafted morning that has the fewest sets
     of its half of the body. The overhead press's extra sets (ruling 6) come from the side-delt (lateral raise) sets.
  2. ONE TIME FIT (`time_fit`), the 75-minute morning as written (warm-ups included) and the session set ceiling: sets come off
     by ONE priority order — non-priority accessory back-offs, then non-priority anchor back-offs, then a priority muscle's
     last sets — never under 2 working sets; an accessory at 2 is dropped whole only when no back-off is left. Anchors never go.

Short weeks (1-3 mornings) are FULL-BODY mornings (`SHORT_WEEKS`): the host role's anchors plus a partner role's anchors, 4-6
movements at 2-3 working sets each — never a 1-set anchor, never "delete the last sessions" (owner ruling #5).

The ONE hard-set counter is `hard_sets` (the sample-week script and the deliverables read it too). Every number is a labelled
heuristic in `live_settings.HEURISTICS`."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from training import live_settings as cfg

ISSUE = "#5861"
HEADS = ("front_delts", "side_delts", "rear_delts")
LANDMARK_OF = {
    "front_delts": "shoulders",
    "side_delts": "shoulders",
    "rear_delts": "shoulders",
    "lats": "back",
    "upper_back": "back",
    "traps": "back",
    "lower_back": "back",
    "adductors": "glutes",
    "abductors": "glutes",
    "obliques": "abs",
}
"""A library target -> its landmark muscle (config/training_landmarks.json)."""
MAJOR = ("chest", "back", "quadriceps", "hamstrings", "glutes")
FILL: dict[str, tuple[str, ...]] = {
    "quadriceps": ("leg_extension_machine", "single_leg_extension", "leg_press", "goblet_squat"),
    "abs": ("machine_crunch", "cable_crunch", "reverse_crunch"),
    "chest": ("cable_chest_fly", "chest_fly_machine", "chest_fly_dumbbell", "push_up"),
    "side_delts": ("db_lateral_raise", "lateral_raise_machine", "lateral_raise_cable_single_arm"),
    "hamstrings": ("leg_curl",),
}
"""A muscle under its aim with no slot left to grow takes the first of these the gym serves (familiar movements first; the
time fit and the pain rule still apply). Practitioner consensus: low-fatigue isolation for the target muscle."""
FOUR_DAY_MEV = ("shoulders", "biceps", "triceps")
"""Owner ruling 3: a 4-morning week drops shoulders+arms but holds these at MEV, direct + indirect, counted."""
FILL_FIRST = ("abs",)
"""Owner ruling #8: direct ab sets are spread over the mornings — a second morning's slot before a third set in one slot."""
UPPER = ("chest", "back", "shoulders", "biceps", "triceps", "side_delts", "front_delts", "rear_delts")
SHORT_WEEKS: dict[int, dict[str, Any]] = {
    4: {"roles": ("upper_heavy", "lower_heavy", "upper_volume", "lower_volume"), "partners": {}, "host": "lower_volume"},
    3: {
        "roles": ("upper_heavy", "lower_heavy", "upper_volume"),
        "partners": {
            "upper_heavy": (("lower_volume", ("squat",)),),
            "lower_heavy": (("shoulders_arms", ("overhead_press",)),),
            "upper_volume": (("lower_volume", ("hinge",)),),
        },
        "host": "upper_volume",
    },
    2: {
        "roles": ("upper_heavy", "lower_heavy"),
        "partners": {
            "upper_heavy": (("lower_volume", ("squat", "hinge")),),
            "lower_heavy": (("upper_volume", ("bench", "row", "vertical_pull")),),
        },
        "host": "lower_heavy",
    },
    1: {"roles": ("upper_heavy",), "partners": {"upper_heavy": (("lower_volume", ("squat", "hinge")),)}, "host": "upper_heavy"},
}
"""Mornings -> the week. 4: shoulders+arms skipped (ruling 3), the other templates as they are. 1-3: FULL-BODY mornings — the
host's anchors plus the partner role's named anchors; the host's accessories go, and the weekly plan adds back only what a
target needs (abs, a priority muscle under maintenance). Heuristic (practitioner consensus for a 1-3 day full-body week)."""
FULL_BODY_MAX_MOVEMENTS = 6
FULL_BODY_SETS = (2, 3)


def _settings(lib: dict[str, Any] | None) -> dict[str, Any]:
    return cfg.settings(lib)


def _marks() -> dict[str, Any]:
    from training import block_model

    return block_model.load_landmarks() or {}


def lib_entry(key: Any, catalog: dict[str, Any], lib: dict[str, Any]) -> dict[str, Any]:
    from training import selection_engine as se

    lid = se.key_index(lib, catalog)["to_lib"].get(str(key)) if key else None
    return ((lib.get("movements") or {}).get(lid) or {}) if lid else {}


def credits(entry: dict[str, Any], key: Any = None, catalog: dict[str, Any] | None = None) -> dict[str, float]:
    """One working set's credit: the library target's landmark muscle 1.0, each secondary `secondary_credit`; each delt head
    direct 1.0 or by `delt_credit` from the lift's pattern. A movement with no library target falls back to the catalog's muscle."""
    t = entry.get("target") or {}
    prim = str(t.get("primary") or (catalog or {}).get(str(key), {}).get("primary_muscle") or "")
    out: Counter = Counter()
    if not prim or prim == "other":
        return {}
    land = LANDMARK_OF.get(prim, prim)
    out[land] += 1.0
    for sec in t.get("secondary") or []:
        m = LANDMARK_OF.get(str(sec), str(sec))
        if m != land:
            out[m] += float(cfg.value("secondary_credit"))
    if prim in HEADS:
        out[prim] += 1.0
    else:
        for head, c in (cfg.value("delt_credit").get(str(entry.get("pattern"))) or {}).items():
            out[head] += float(c)
    return dict(out)


def landmark_muscle(key: Any, catalog: dict[str, Any], lib: dict[str, Any] | None) -> str:
    """A movement's main landmark muscle (its largest set credit), else "other"."""
    c = {k: v for k, v in credits(lib_entry(key, catalog, lib or {}), key, catalog).items() if k not in HEADS}
    return max(c, key=c.get) if c else "other"


def hard_sets(items: Any) -> dict[str, float]:
    """THE hard-set counter: items of (library entry, working sets, top prescribed RPE or None, key, catalog). A set is hard at
    `hard_rpe`+ (None counts: a plan row's prescription is hard by design). Landmark muscles and the three delt heads."""
    out: Counter = Counter()
    hard = float(cfg.value("hard_rpe"))
    for entry, n, rpe, key, catalog in items:
        if rpe is not None and float(rpe) < hard:
            continue
        for m, c in credits(entry, key, catalog).items():
            out[m] += c * int(n)
    return {k: round(v, 1) for k, v in sorted(out.items())}


def targets(lib: dict[str, Any], mornings: int, high_fatigue: bool = False) -> dict[str, dict[str, float]]:
    """Muscle (and delt head) -> {floor, aim, cap} in hard sets for this week (module doc 1)."""
    s = _settings(lib)
    prio = {str(m) for m in s.get("priority_muscles") or []}
    out: dict[str, dict[str, float]] = {}
    short = mornings <= 3
    for m, lm in _marks().items():
        mv, mev, mav = float(lm.get("MV", 0)), float(lm["MEV"]), float(lm["MAV"])
        if m == "abs":
            n = float(s.get("abs_direct_sets_per_week") or 0)
            n = math.ceil(n / 2) if (short or high_fatigue) else n
            out[m] = {"floor": n, "aim": n, "cap": mav}
        elif short:
            floor = max(float(cfg.value("slot_min_sets")), math.ceil(mv * mornings / 3)) if (m in prio or m in MAJOR) else 0.0
            aim = max(floor, math.ceil(mev * mornings / 3)) if m in prio else floor  # a priority muscle aims at MEV pro rata
            out[m] = {"floor": floor, "aim": aim, "cap": mav}
        elif m in prio:
            out[m] = {"floor": mev, "aim": mev + round(float(cfg.value("priority_aim")) * (mav - mev)), "cap": mav}
        elif mornings == 4 and m in FOUR_DAY_MEV:  # ruling 3: the week without shoulders+arms holds them at MEV, counted
            out[m] = {"floor": mev, "aim": mev, "cap": mav}
        else:
            out[m] = {"floor": mv, "aim": mv, "cap": mav}
    if not short:
        for head, aim in cfg.value("delt_heads").items():
            out[head] = {"floor": float(aim), "aim": float(aim), "cap": 99.0}
    return out


def week_shape(mornings: int) -> dict[str, Any]:
    """The week for `mornings` (SHORT_WEEKS; 5 = the split as designed)."""
    from training import program_structure as ps

    if mornings >= len(ps.SPLIT_ROLES):
        return {"roles": tuple(ps.SPLIT_ROLES), "partners": {}, "host": "shoulders_arms", "mornings": len(ps.SPLIT_ROLES)}
    return {**SHORT_WEEKS[max(1, int(mornings))], "mornings": max(1, int(mornings))}


def _row(role: str, e: dict[str, Any], catalog: dict[str, Any], lib: dict[str, Any], guest: bool = False) -> dict[str, Any]:
    entry = lib_entry(e.get("movement_key"), catalog, lib)
    return {
        "role": role,
        "slot": str(e.get("slot") or e.get("pattern") or e.get("movement_key")),
        "kind": e.get("kind"),
        "intensity": e.get("intensity"),
        "pattern": e.get("pattern"),
        "key": e.get("movement_key"),
        "sets": len(e.get("sets") or []),
        "credit": credits(entry, e.get("movement_key"), catalog),
        "guest": guest,
    }


def day_rows(role: str, week: dict[str, Any], catalog: dict[str, Any], lib: dict[str, Any]) -> list[dict[str, Any]]:
    """One morning's template rows this week: the role's template, or on a full-body morning its anchors plus the partners'."""
    from training import program_structure as ps

    rx = ps.session_prescription_for_role(role, catalog_movements=catalog)
    rows = [_row(role, e, catalog, lib) for e in rx["exposures"] if not _kb_slot(e)]
    partners = (week.get("partners") or {}).get(role)
    if not partners:
        return [r for r in rows if not (r["role"] == "shoulders_arms" and r["intensity"] == "carry" and week["mornings"] < 5)]
    rows = [r for r in rows if r["kind"] == "anchor"]
    for prole, patterns in partners:
        for e in ps.session_prescription_for_role(prole, catalog_movements=catalog)["exposures"]:
            if e.get("kind") == "anchor" and e.get("pattern") in patterns and e.get("movement_key") not in {r["key"] for r in rows}:
                r = _row(role, e, catalog, lib, guest=True)
                r["sets"] = max(FULL_BODY_SETS[0], min(FULL_BODY_SETS[1], r["sets"]))
                rows.append(r | {"slot": f"guest_{e.get('pattern')}"})
    for r in rows:
        r["sets"] = max(FULL_BODY_SETS[0], min(FULL_BODY_SETS[1], r["sets"])) if r["kind"] == "anchor" else r["sets"]
    return rows


def _kb_slot(e: dict[str, Any]) -> bool:
    """Owner rulings #2/#6/#7: no kettlebell hinge slot under live — the swing stays gated and optional, never a hinge filler."""
    return str(e.get("slot") or "") == "kettlebell_swing"


def _count(rows: list[dict[str, Any]]) -> Counter:
    out: Counter = Counter()
    for r in rows:
        for m, c in r["credit"].items():
            out[m] += c * r["sets"]
    return out


def _press_trade(rows: list[dict[str, Any]], lib: dict[str, Any]) -> list[str]:
    """Ruling 6: the overhead press runs `press_sets`; the extra sets come off the lateral raises (shoulders+arms first)."""
    press = next((r for r in rows if r["role"] == "shoulders_arms" and r["pattern"] == "overhead_press"), None)
    if press is None:
        return []
    extra = max(0, int(_settings(lib).get("press_sets") or 1) - press["sets"])
    press["sets"] += extra
    gave = 0
    for r in sorted(
        (r for r in rows if r["kind"] == "accessory" and "lateral_raise" in str(r["key"])), key=lambda r: r["role"] != "shoulders_arms"
    ):
        while gave < extra and r["sets"] > int(cfg.value("slot_min_sets")):
            r["sets"] -= 1
            gave += 1
    return [f"press: overhead press {press['sets']} sets, {gave} from the lateral raises (ruling 6)"] if extra else []


def _fill_key(muscle: str, catalog: dict[str, Any], lib: dict[str, Any], taken: set[str]) -> str | None:
    from training import selection_engine as se

    for key in FILL.get(muscle, ()):
        entry = lib_entry(key, catalog, lib)
        if key in catalog and key not in taken and entry and not se.availability(entry, lib, None):
            return key
    return None


def _fill_role(muscle: str, rows: list[dict[str, Any]], roles: tuple[str, ...], week: dict[str, Any]) -> str | None:
    """The drafted morning a fill lands on: its half of the body (upper / lower; abs anywhere), not already holding the muscle's
    fill, the fewest planned sets first, under the full-body movement cap."""
    from training import program_structure as ps

    half = "upper" if muscle in UPPER else ("lower" if muscle != "abs" else None)
    best = None
    for role in roles:
        here = [r for r in rows if r["role"] == role]
        full = bool((week.get("partners") or {}).get(role))
        if full and len(here) >= FULL_BODY_MAX_MOVEMENTS:
            continue
        if half and not full and ps.SESSION_TEMPLATES[role]["archetype"] != half:
            continue
        if any(r.get("fill") == muscle or (r["kind"] == "accessory" and r["credit"].get(muscle)) for r in here):
            continue
        n = sum(r["sets"] for r in here)
        if best is None or n < best[0]:
            best = (n, role)
    return best[1] if best else None


def week_plan(catalog: dict[str, Any], lib: dict[str, Any], mornings: int, high_fatigue: bool = False) -> dict[str, Any]:
    """The week's plan (module doc 1): {rows (every drafted morning's rows, sized), targets, counts, under, lines}. Pure over the
    catalog, the library and the mornings; the same for every morning of the week."""
    week = week_shape(mornings)
    rows = [r for role in week["roles"] for r in day_rows(role, week, catalog, lib)]
    lines = _press_trade(rows, lib)
    tg = targets(lib, week["mornings"], high_fatigue)
    lo, hi = int(cfg.value("slot_min_sets")), int(cfg.value("slot_max_sets"))
    prio = {str(m) for m in _settings(lib).get("priority_muscles") or []}

    def iso(m: str) -> list[dict[str, Any]]:
        return [
            r
            for r in rows
            if r["kind"] == "accessory"
            and r["intensity"] != "carry"
            and max(r["credit"], key=r["credit"].get, default="") in (m, LANDMARK_OF.get(m, m))
            and r["credit"].get(m)
        ]

    # 1. surplus over the cap gives first (non-priority isolation, largest slot first, never under 2)
    for m, t in tg.items():
        while _count(rows)[m] > t["cap"] and m not in prio:
            give = [r for r in iso(m) if r["sets"] > lo and not _head_needs(r, rows, tg)]
            if not give:
                break
            max(give, key=lambda r: (r["sets"], rows.index(r)))["sets"] -= 1
    # 2. under the aim: grow its isolation slots, then a fill slot (priority muscles, heads and abs first)
    order = sorted(tg, key=lambda m: (m not in prio, m not in HEADS, m != "abs", m))
    taken = {str(r["key"]) for r in rows}

    def grow(m: str) -> None:
        for r in iso(m):
            while _count(rows)[m] < tg[m]["aim"] and r["sets"] < hi:
                r["sets"] += 1

    for m in order:
        if m not in FILL_FIRST:
            grow(m)
        if _count(rows)[m] + 1 < tg[m]["aim"]:  # two short or more: a fill slot of two sets on its own morning
            key, role = _fill_key(m, catalog, lib, taken), _fill_role(m, rows, week["roles"], week)
            if key and role:
                taken.add(key)
                rows.append(
                    _row(
                        role,
                        {"kind": "accessory", "slot": f"fill_{m}", "intensity": "accessory", "movement_key": key, "sets": [{}] * lo},
                        catalog,
                        lib,
                    )
                    | {"fill": m}
                )
                lines.append(f"fill: {role} + {key} x{lo} ({m} under its aim of {tg[m]['aim']:g})")
        grow(m)
    counts = _count(rows)
    under = [
        {"muscle": m, "sets": round(counts[m], 1), "floor": t["floor"], "aim": t["aim"]}
        for m, t in tg.items()
        if counts[m] + 1e-9 < t["floor"]
    ]
    return {
        "week": week,
        "rows": rows,
        "targets": tg,
        "counts": {k: round(v, 1) for k, v in counts.items()},
        "under": under,
        "lines": lines,
    }


def _head_needs(r: dict[str, Any], rows: list[dict[str, Any]], tg: dict[str, dict[str, float]]) -> bool:
    """A slot whose delt head would fall under its aim keeps its sets."""
    c = _count(rows)
    return any(r["credit"].get(h) and c[h] - r["credit"][h] < tg.get(h, {}).get("aim", 0) for h in HEADS)


def press_trade_alternative(catalog: dict[str, Any], lib: dict[str, Any]) -> dict[str, Any]:
    """The owner's alternative to ruling 6 IN NUMBERS (reported, not applied): the press's extra sets from the rear-delt surplus
    (face pulls) instead of the lateral raises. {default: heads, alternative: heads}."""
    week = week_shape(5)
    base = [r for role in week["roles"] for r in day_rows(role, week, catalog, lib)]
    default = [dict(r) for r in base]
    _press_trade(default, lib)
    alt = [dict(r) for r in base]
    press = next(r for r in alt if r["role"] == "shoulders_arms" and r["pattern"] == "overhead_press")
    extra = max(0, int(_settings(lib).get("press_sets") or 1) - press["sets"])
    press["sets"] += extra
    for r in sorted((r for r in alt if "face_pull" in str(r["key"])), key=lambda r: r["role"] != "shoulders_arms"):
        while extra and r["sets"] > 2:
            r["sets"] -= 1
            extra -= 1
    pick = lambda rs: {h: round(_count(rs)[h], 1) for h in HEADS + ("shoulders",)}  # noqa: E731
    return {"default": pick(default), "alternative": pick(alt)}


# ── the session's share ──────────────────────────────────────────────────────
def apply(rx: dict[str, Any], ctx: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """IN PLACE: this morning's share of the plan — a full-body morning's composition (its accessories go, the partners' anchors
    join), each slot's planned set count, the plan's fill slots and the kettlebell slot's removal. Returns the lines."""
    from training import program_structure as ps
    from training.program_structure import EXPOSURES

    role = str(rx.get("session_role") or "")
    mine = [r for r in plan["rows"] if r["role"] == role]
    by_slot = {r["slot"]: r for r in mine}
    lines: list[str] = []
    full = bool((plan["week"].get("partners") or {}).get(role))
    keep = []
    for e in rx["exposures"]:
        slot = str(e.get("slot") or e.get("pattern") or e.get("movement_key"))
        if _kb_slot(e):
            lines.append("no KB hinge slot (rulings #2/#6/#7: the swing stays gated and optional, never a hinge filler)")
            continue
        if full and e.get("kind") != "anchor":
            continue
        if e.get("kind") != "anchor" and slot not in by_slot:
            continue  # a carry the short week does not draft
        r = by_slot.get(slot)
        if r is not None and e.get("sets"):
            _resize(e, r["sets"])
        keep.append(e)
    rx["exposures"] = keep
    if full:
        for prole, patterns in plan["week"]["partners"][role]:
            for e in ps.session_prescription_for_role(prole, catalog_movements=ctx["catalog"])["exposures"]:
                r = by_slot.get(f"guest_{e.get('pattern')}")
                if (
                    e.get("kind") == "anchor"
                    and e.get("pattern") in patterns
                    and r
                    and e.get("movement_key") not in {x.get("movement_key") for x in keep}
                ):
                    g = dict(e)
                    _resize(g, r["sets"])
                    rx["exposures"].append(g | {"live_full_body": prole, "slot": r["slot"]})
        lines.append(f"full body (live): {role} + {', '.join(p for p, _ in plan['week']['partners'][role])} anchors at 2-3 sets each")
    for r in mine:
        if r.get("fill") and r["key"] not in {e.get("movement_key") for e in rx["exposures"]}:
            rx["exposures"].append(
                {
                    "kind": "accessory",
                    "pattern": None,
                    "slot": r["slot"],
                    "intensity": "accessory",
                    "movement_key": r["key"],
                    "resolution_note": None,
                    "sets": [{"kind": "working", "reps": [8, 15]} for _ in range(r["sets"])],
                    "rest_seconds": int(EXPOSURES["accessory"]["rest_seconds"]),
                    "live_added": f"fill_{r['fill']}",
                }
            )
    return lines


FULL_BODY_PAIRS: tuple[tuple[str, str], ...] = (("bench", "row"), ("squat", "vertical_pull"), ("hinge", "overhead_press"))
"""A full-body morning's paired sets (anchor + its antagonist or the other half of the body, rest after the pair): what makes 4-6
movements at 2-3 sets fit 75 minutes with the warm-ups as written. Heuristic (practitioner consensus: paired sets keep the
work and save the rest)."""


def pair_anchors(rx: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """A full-body morning's paired sets (after the programming pass has ordered the session). Returns the line."""
    if not (plan["week"].get("partners") or {}).get(str(rx.get("session_role") or "")):
        return []
    return _pair_anchors(rx["exposures"])


def _pair_anchors(exposures: list[dict[str, Any]]) -> list[str]:
    """IN PLACE: FULL_BODY_PAIRS on a full-body morning's anchors (superset ids above any accessory pair). Returns the line."""
    sid = max([int(e.get("superset_id") or 0) for e in exposures] + [0])
    done = []
    for a_pat, b_pat in FULL_BODY_PAIRS:
        free = [e for e in exposures if e.get("kind") == "anchor" and not e.get("superset_id")]
        a = next((e for e in free if e.get("pattern") == a_pat), None)
        b = next((e for e in free if e.get("pattern") == b_pat), None)
        if a is None or b is None:
            continue
        sid += 1
        exposures.remove(b)
        exposures.insert(exposures.index(a) + 1, b)
        a["superset_id"] = b["superset_id"] = sid
        b["rest_seconds"] = max(int(a.get("rest_seconds") or 0), int(b.get("rest_seconds") or 0))
        a["rest_seconds"] = 0
        done.append(f"{a_pat} + {b_pat}")
    return [f"paired sets (live): {', '.join(done)} — a full-body morning's rest taken after each pair"] if done else []


def _resize(e: dict[str, Any], n: int) -> None:
    sets = list(e.get("sets") or [])
    while len(sets) > n:
        sets.pop()
    while sets and len(sets) < n:
        sets.append(dict(sets[-1]))
    e["sets"] = sets


# ── the one time fit ─────────────────────────────────────────────────────────
def _work(b: Any) -> int:
    return sum(1 for s in b.sets if str(getattr(s, "type", "") or "normal") != "warmup")


def _prio(key: Any, catalog: dict[str, Any], lib: dict[str, Any]) -> bool:
    """The movement's main muscle (its largest credit) is a priority muscle."""
    c = credits(lib_entry(key, catalog, lib), key, catalog)
    return bool(c) and max(c, key=c.get) in {str(m) for m in _settings(lib).get("priority_muscles") or []}


def next_cut(items: list[tuple[bool, bool, bool, int]]) -> tuple[int, str] | None:
    """THE trim order (`live_settings.TRIM_ORDER`) over items (anchor, carry, priority, working sets): (index, "set" | "drop") —
    the latest-listed candidate of the first tier that has one: non-priority accessory back-offs, non-priority anchor back-offs,
    priority back-offs; then a carry, a whole non-priority accessory at 2, a priority one. Anchors never under 2, never dropped."""
    floor = int(cfg.value("slot_min_sets"))
    tiers: list[list[tuple[int, str]]] = [[], [], [], [], [], []]
    for i, (anchor, carry, prio, n) in enumerate(items):
        if carry and not anchor:
            tiers[3].append((i, "drop"))
        elif n > floor:
            tiers[2 if prio else (1 if anchor else 0)].append((i, "set"))
        elif not anchor:
            tiers[5 if prio else 4].append((i, "drop"))
    return next((tier[-1] for tier in tiers if tier), None)


def fit_sets(rx: dict[str, Any], cap: Any, catalog: dict[str, Any], lib: dict[str, Any]) -> list[str]:
    """IN PLACE: the prescription held to the session set ceiling by `next_cut` (before the routine is built — the generator
    asserts the ceiling). Returns the line."""
    if not cap:
        return []
    ex = rx["exposures"]
    before = sum(len(e.get("sets") or []) for e in ex)
    while sum(len(e.get("sets") or []) for e in ex) > int(cap):
        items = [
            (e.get("kind") == "anchor", e.get("intensity") == "carry", _prio(e.get("movement_key"), catalog, lib), len(e.get("sets") or []))
            for e in ex
        ]
        nxt = next_cut(items)
        if nxt is None:
            break
        i, how = nxt
        if how == "drop":
            ex.pop(i)
        else:
            ex[i]["sets"] = list(ex[i]["sets"])[:-1]
    after = sum(len(e.get("sets") or []) for e in ex)
    return [f"set cap (live): {before} -> {after} working sets (the {cap}-set session ceiling, one trim order)"] if after < before else []


def time_fit(blocks: list[Any], rx: dict[str, Any], movements: dict[str, Any], cap: int) -> list[str]:
    """IN PLACE: the routine as written (warm-ups included) to `cap` minutes by `next_cut`. Returns the line (empty when it fits)."""
    from training import selection_engine as se
    from training.live_session import _unpair
    from training.session_shape import routine_minutes

    lib = se.load_library_failsoft() or {}
    kinds = {e.get("movement_key"): e for e in rx.get("exposures") or []}
    before = routine_minutes(blocks, movements)["lifting_minutes"]
    done: list[str] = []
    while routine_minutes(blocks, movements)["lifting_minutes"] > cap:
        lifts = [i for i, b in enumerate(blocks) if b.movement_key in kinds]
        items = [
            (
                kinds[blocks[i].movement_key].get("kind") == "anchor",
                kinds[blocks[i].movement_key].get("intensity") == "carry",
                _prio(blocks[i].movement_key, movements, lib),
                _work(blocks[i]),
            )
            for i in lifts
        ]
        nxt = next_cut(items)
        if nxt is None:
            break
        b = blocks[lifts[nxt[0]]]
        if nxt[1] == "drop":
            blocks.remove(b)
            _unpair(blocks, getattr(b, "superset_id", None))
            done.append(f"{b.movement_key} dropped")
        else:
            b.sets.pop(max(j for j, s in enumerate(b.sets) if str(getattr(s, "type", "") or "normal") != "warmup"))
            done.append(f"{b.movement_key} -1")
    if not done:
        return []
    after = routine_minutes(blocks, movements)["lifting_minutes"]
    return [
        f"time (live): ~{before} min as written (warm-ups included) > the {cap}-min cap — {', '.join(done)} (one order: "
        f"non-priority back-offs first, priority last) -> ~{after} min"
    ]
