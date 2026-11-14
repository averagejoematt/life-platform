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
    "calves": ("standing_calf_raise_machine", "calf_raise_machine", "seated_calf_raise", "standing_calf_raise_dumbbell"),
    "biceps": ("db_curl", "bicep_curl_machine", "hammer_curl_dumbbell"),
    "triceps": ("cable_tricep_pushdown", "triceps_extension_cable", "overhead_triceps_extension_cable"),
}
"""A muscle under its aim with no slot left to grow takes the first of these the gym serves (familiar movements first; the
time fit and the pain rule still apply). Practitioner consensus: low-fatigue isolation for the target muscle."""
FOUR_DAY_MEV = ("shoulders", "biceps", "triceps")
"""Owner ruling 3: a 4-morning week drops shoulders+arms but holds these at MEV, direct + indirect, counted."""
ANYWHERE = ("abs", "calves")
"""Low-fatigue isolation a fill may put on any morning, not only its half of the body (fix round 10: the 3-set slot cap leaves the
calves two slots short of MEV on the lower mornings)."""
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
        "host": "upper_heavy",
    },
    1: {"roles": ("upper_heavy",), "partners": {"upper_heavy": (("lower_volume", ("squat", "hinge")),)}, "host": "upper_heavy"},
}
"""Mornings -> the week. 4: shoulders+arms skipped (ruling 3), the other templates as they are. 1-3: FULL-BODY mornings — the
host's anchors plus the partner role's named anchors; the host's accessories go, and the weekly plan adds back only what a
target needs (abs, a priority muscle under maintenance). Heuristic (practitioner consensus for a 1-3 day full-body week)."""
FULL_BODY_MAX_MOVEMENTS = 6
MAX_MOVEMENTS = 8
"""A split morning takes no fill past 8 movements (practitioner consensus for a 75-minute session; fix round 10)."""
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
    """One working set's credit by THE set-credit table (`live_settings` set_credit): the target's landmark muscle 1.0, each
    secondary (the library's, plus every other muscle the movement is rated for) half a set unless `never` drops it; each delt
    head direct 1.0, plus the pattern's indirect head credit. A movement with no library target falls back to the catalog."""
    t = entry.get("target") or {}
    prim = str(t.get("primary") or (catalog or {}).get(str(key), {}).get("primary_muscle") or "")
    out: Counter = Counter()
    if not prim or prim == "other":
        return {}
    sc = cfg.value("set_credit")
    pattern = str(entry.get("pattern"))
    never = set(sc["never"].get("*", ())) | set(sc["never"].get(pattern, ()))
    land = LANDMARK_OF.get(prim, prim)
    out[land] += 1.0
    marks = _marks()
    rated = sorted(
        x
        for x in {str(h.get("target")) for h in entry.get("hypertrophy") or [] if h.get("target") and h.get("tier")} - {prim}
        if LANDMARK_OF.get(x, x) in marks  # a rated landmark muscle (a sub-head row such as triceps_long_head is its muscle's)
    )
    for m in dict.fromkeys(LANDMARK_OF.get(str(x), str(x)) for x in list(t.get("secondary") or []) + rated):
        if m != land and m not in never:
            out[m] += float(sc["secondary"])
    if prim in HEADS:
        out[prim] += 1.0
    for head, c in (sc["delt"].get(pattern) or {}).items():
        if head != prim:
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


SHORT_ROTATION = ("calves", "side_delts", "triceps")
"""Fix round 10 (the ninth red team: three 1-morning weeks running served calves 0, side delts 0, triceps 1.5 every week): a
1-3 morning week aims ONE of these at a 2-set slot, rotating by ISO week — consecutive short weeks rotate what is under target,
with no state to keep."""


def targets(lib: dict[str, Any], mornings: int, high_fatigue: bool = False, monday: str | None = None) -> dict[str, dict[str, float]]:
    """Muscle (and delt head) -> {floor, aim, cap} in hard sets for this week (module doc 1). `monday`: a short week's rotation."""
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
        elif m in prio:  # the plan then lifts it to the arms and calves (`_priority_parity`)
            out[m] = {"floor": mev, "aim": mev, "cap": mav}
        elif mornings == 4 and m in FOUR_DAY_MEV:  # ruling 3: the week without shoulders+arms holds them at MEV, counted
            out[m] = {"floor": mev, "aim": mev, "cap": mav}
        else:  # a full week aims every other muscle at MEV (its floor stays MV: time and recovery may take it there)
            out[m] = {"floor": mv, "aim": mev if mornings >= 5 and not high_fatigue else mv, "cap": mav}
    for head, aim in cfg.value("delt_heads").items():  # a short week aims at the side delt pro rata (no floor: time decides)
        if not short:
            out[head] = {"floor": float(aim), "aim": float(aim), "cap": 99.0}
        elif head == "side_delts":
            out[head] = {"floor": 0.0, "aim": float(math.ceil(float(aim) * mornings / 5)), "cap": 99.0}
    if short and monday:
        from common.pacific_time import parse_day_key

        d = parse_day_key(str(monday)[:10])
        owed = SHORT_ROTATION[d.isocalendar()[1] % len(SHORT_ROTATION)] if d else None
        if owed in out:
            out[owed]["aim"] = max(out[owed]["aim"], float(cfg.value("slot_min_sets")) + 1)  # two short: its fill slot joins
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
    hi = int(cfg.value("slot_max_sets"))
    for r in rows:  # fix round 10: a template slot written at 4 sets is served at the slot cap (the calf slots)
        r["sets"] = min(r["sets"], hi) if r["kind"] == "accessory" and r["intensity"] != "carry" else r["sets"]
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


def _press_trade(rows: list[dict[str, Any]], lib: dict[str, Any], source: str = "lateral_raise") -> list[str]:
    """Ruling 6: the overhead press runs `press_sets`; the extra sets come off the lateral raises (shoulders+arms first).
    `source` "face_pull" is the owner's alternative (the rear-delt surplus pays), computed for the report only."""
    press = next((r for r in rows if r["role"] == "shoulders_arms" and r["pattern"] == "overhead_press"), None)
    if press is None:
        return []
    extra = max(0, int(_settings(lib).get("press_sets") or 1) - press["sets"])
    press["sets"] += extra
    gave = 0
    for r in sorted((r for r in rows if r["kind"] == "accessory" and source in str(r["key"])), key=lambda r: r["role"] != "shoulders_arms"):
        while gave < extra and r["sets"] > int(cfg.value("slot_min_sets")):
            r["sets"] -= 1
            gave += 1
    return [f"press: overhead press {press['sets']} sets, {gave} from the {source.replace('_', ' ')}s (ruling 6)"] if extra else []


def _fill_key(muscle: str, catalog: dict[str, Any], lib: dict[str, Any], taken: set[str]) -> str | None:
    from training import selection_engine as se

    for key in FILL.get(muscle, ()):
        entry = lib_entry(key, catalog, lib)
        if key in catalog and key not in taken and entry and not se.availability(entry, lib, None):
            return key
    return None


def _fill_role(muscle: str, rows: list[dict[str, Any]], roles: tuple[str, ...], week: dict[str, Any]) -> str | None:
    """The drafted morning a fill lands on: its half of the body (upper / lower; abs and calves anywhere), not already holding the
    muscle's fill, the least planned time first (`_morning_load`), under the full-body movement cap."""
    from training import program_structure as ps

    half = "upper" if muscle in UPPER else ("lower" if muscle not in ANYWHERE else None)
    best = None
    for role in roles:
        here = [r for r in rows if r["role"] == role]
        full = bool((week.get("partners") or {}).get(role))
        if len(here) >= (FULL_BODY_MAX_MOVEMENTS if full else MAX_MOVEMENTS):
            continue
        if half and not full and ps.SESSION_TEMPLATES[role]["archetype"] != half:
            continue
        if any(r.get("fill") == muscle or (r["kind"] == "accessory" and r["credit"].get(muscle)) for r in here):
            continue
        n = _morning_load(here)
        if best is None or n < best[0]:
            best = (n, role)
    return best[1] if best else None


def refill(rx: dict[str, Any], ctx: dict[str, Any], flags: list[dict[str, Any]], skipped: int) -> list[str]:
    """IN PLACE, live only (fix round 10, the ninth red team: pain weeks left 30-40 free minutes beside untrained muscles): for
    each lift the pain rule skipped, ONE fill slot of the morning's half (priority muscles first, then FILL order, calves anywhere,
    never abs) whose movement is reviewed and loads every flagged joint LOW, at the slot minimum — the time fit trims it if the
    morning runs over. Returns the lines."""
    from training import live_pain, program_structure as ps
    from training.program_structure import EXPOSURES

    if skipped <= 0:
        return []
    role = str(rx.get("session_role") or "")
    half = (ps.SESSION_TEMPLATES.get(role) or {}).get("archetype")
    prio = [str(m) for m in _settings(ctx["lib"]).get("priority_muscles") or []]
    order = [  # abs keep their ruled weekly dose (owner ruling #8): never a refill
        m
        for m in dict.fromkeys(prio + list(FILL))
        if m not in FILL_FIRST and (m in ANYWHERE or half is None or (m in UPPER) == (half == "upper"))
    ]
    taken = {str(e.get("movement_key")) for e in rx["exposures"]}
    joints = sorted({j for f in flags for j in f["joints"]})
    lines = []
    for m in order:
        if skipped <= 0:
            break
        key = next(
            (
                k
                for k in FILL.get(m, ())
                if k in ctx["catalog"] and k not in taken and live_pain._low(lib_entry(k, ctx["catalog"], ctx["lib"]), joints)
                and not _unavailable(k, ctx)
            ),
            None,
        )  # fmt: skip
        if not key:
            continue
        taken.add(key)
        skipped -= 1
        n = int(cfg.value("slot_min_sets"))
        rx["exposures"].append(
            {
                "kind": "accessory",
                "pattern": None,
                "slot": f"refill_{m}",
                "intensity": "accessory",
                "movement_key": key,
                "resolution_note": None,
                "sets": [{"kind": "working", "reps": [8, 15]} for _ in range(n)],
                "rest_seconds": int(EXPOSURES["accessory"]["rest_seconds"]),
                "live_added": f"refill_{m}",
            }
        )
        title = (ctx["catalog"].get(key) or {}).get("title") or key
        lines.append(f"refill (live): {title} {n} x 8-15 — {m}, reviewed and low on the flagged joint, in a pain-skipped lift's time")
    return lines


def _unavailable(key: str, ctx: dict[str, Any]) -> bool:
    from training import selection_engine as se

    entry = lib_entry(key, ctx["catalog"], ctx["lib"])
    return not entry or bool(se.availability(entry, ctx["lib"], ctx.get("overlay")))


def _morning_load(rows: list[dict[str, Any]]) -> int:
    """A morning's planned minutes, as a count: an anchor set counts double (its warm-ups and longer rest — the #5799 time
    model's two big costs). The fill and the conditioning dose go where it is least (fix round 10). Heuristic."""
    return sum(r["sets"] * (2 if r["kind"] == "anchor" else 1) for r in rows)


def week_plan(
    catalog: dict[str, Any],
    lib: dict[str, Any],
    mornings: int,
    high_fatigue: bool = False,
    press_source: str = "lateral_raise",
    monday: str | None = None,
) -> dict[str, Any]:
    """The week's plan (module doc 1): {rows (every drafted morning's rows, sized), targets, counts, under, lines}. Pure over the
    catalog, the library and the mornings; the same for every morning of the week."""
    week = week_shape(mornings)
    rows = [r for role in week["roles"] for r in day_rows(role, week, catalog, lib)]
    lines = _press_trade(rows, lib, press_source)
    tg = targets(lib, week["mornings"], high_fatigue, monday)
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

    def surplus() -> None:
        # surplus over the cap gives first (non-priority isolation, largest slot first, never under 2; a slot already at 2 goes
        #    whole when every muscle and head it trains stays at its aim — ruling 9: never force total shoulder volume)
        for m, t in tg.items():
            while _count(rows)[m] > t["cap"] and m not in prio:
                give = [r for r in iso(m) if r["sets"] > lo and not _head_needs(r, rows, tg)]
                if give:
                    max(give, key=lambda r: (r["sets"], rows.index(r)))["sets"] -= 1
                    continue
                whole = [r for r in iso(m) if r["sets"] and _spare(r, rows, tg)]
                if not whole:
                    break
                gone = whole[-1]
                rows.remove(gone)
                lines.append(f"surplus: {gone['role']} - {gone['key']} ({m} over its MAV, every head at its aim)")

    surplus()  # 1. surplus over the cap gives first
    # 2. under the aim: grow its isolation slots, then a fill slot (priority muscles, heads and abs first)
    order = sorted(tg, key=lambda m: (m not in prio, m != "abs", m not in HEADS, m))
    taken = {str(r["key"]) for r in rows}

    def grow(m: str) -> None:
        for r in iso(m):
            while _count(rows)[m] < tg[m]["aim"] and r["sets"] < hi:
                r["sets"] += 1

    def fill(m: str) -> bool:  # a fill slot of two sets on its own morning
        key, role = _fill_key(m, catalog, lib, taken), _fill_role(m, rows, week["roles"], week)
        if not (key and role):
            return False
        taken.add(key)
        new = {"kind": "accessory", "slot": f"fill_{m}", "intensity": "accessory", "movement_key": key, "sets": [{}] * lo}
        rows.append(_row(role, new, catalog, lib) | {"fill": m})
        lines.append(f"fill: {role} + {key} x{lo} ({m} under its aim of {tg[m]['aim']:g})")
        return True

    for m in order:
        if m not in FILL_FIRST:
            grow(m)
        if _count(rows)[m] + 1 < tg[m]["aim"]:  # two short or more
            fill(m)
        grow(m)
    surplus()  # 3. again after the fills: a head's aim may have grown its muscle past MAV (ruling 9)
    lines += _priority_parity(rows, tg, prio, grow, fill if week["mornings"] >= 5 else None)  # 4. a short week has no spare morning
    lines += _redline(rows, tg, prio)
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


PARITY_RIVALS = ("biceps", "triceps", "calves")
"""Owner ruling 9 (fix round 10, the ninth red team: priority chest 9 under biceps 11): a priority muscle's weekly hard sets are
not under these non-priority isolation muscles' (the shoulders stay out of the parity, owner ruling #9)."""


PARITY_TOLERANCE = 1.0
"""The plan counts the template's movements; the served week's selection (a face pull served as a reverse fly) and time fit move
a muscle by about a set — so the plan holds a priority muscle within one set of every rival, and the served weeks are checked
(tests/test_fix10_5861.py). Heuristic."""


def _priority_parity(rows: list[dict[str, Any]], tg: dict[str, dict[str, float]], prio: set[str], grow: Any, fill: Any) -> list[str]:
    """IN PLACE, each priority muscle at most PARITY_TOLERANCE under every PARITY_RIVALS muscle in the plan. The rival pays first — one set from its largest
    isolation slot, or a whole 2-set slot — down to half a set over its MEV; then the
    priority muscle grows its own isolation slots (never past the slot cap) or, on a full week (`fill` given), takes its fill
    slot. Never under a rival's floor."""
    lo, paid, filled = int(cfg.value("slot_min_sets")), 0, set()
    marks = _marks()
    for margin in (0.5,):  # a ruled floor (the 4-day week's MEV, ruling 3) keeps a whole set of margin
        keep = {m: max(tg.get(m, {}).get("floor", 0.0) + 1, float((marks.get(m) or {}).get("MEV", 0.0)) + margin) for m in PARITY_RIVALS}
        for p in sorted(m for m in prio if m in tg):
            for _ in range(24):
                c = _count(rows)
                rivals = sorted((m for m in PARITY_RIVALS if m not in prio and c[m] > c[p] + PARITY_TOLERANCE + 1e-9), key=lambda x: -c[x])
                if not rivals:
                    break
                give = [
                    r
                    for r in rows
                    if r["kind"] == "accessory" and r["intensity"] != "carry" and max(r["credit"], key=r["credit"].get, default="") == rivals[0]
                    and c[rivals[0]] - r["credit"][rivals[0]] * (1 if r["sets"] > lo else r["sets"]) >= keep[rivals[0]]
                ]  # fmt: skip
                if not give:
                    break
                r = max(give, key=lambda r: (r["sets"], rows.index(r)))
                paid += 1 if r["sets"] > lo else r["sets"]
                if r["sets"] > lo:
                    r["sets"] -= 1
                else:
                    rows.remove(r)
    for p in sorted(m for m in prio if m in tg):
        c = _count(rows)
        top = max((c[m] for m in PARITY_RIVALS if m not in prio), default=0.0)
        if c[p] + PARITY_TOLERANCE + 1e-9 < top:
            tg[p]["aim"] = max(tg[p]["aim"], min(tg[p]["cap"], math.ceil(top)))
            grow(p)
            if _count(rows)[p] + PARITY_TOLERANCE + 1e-9 < top and fill is not None and p not in filled:
                filled.add(p)
                fill(p)
    return [f"priority: {paid} arm/calf set(s) off so {', '.join(sorted(prio))} sit at or over them (ruling 9)"] if paid else []


def conditioning_host(plan: dict[str, Any]) -> str:
    """Fix round 10 (the ninth red team): the week's hard conditioning dose goes on the drafted morning with the most free
    minutes (`_morning_load`) — never the heavy lower day or the morning before it; the template host breaks a tie. Owner ruling 1: the dose takes only the minutes lifting leaves, never a lifting set.
    """
    from training import program_structure as ps

    roles = list(ps.SPLIT_ROLES)
    week = plan["week"]
    ok = [r for r in week["roles"] if r != "lower_heavy" and roles[(roles.index(r) + 1) % len(roles)] != "lower_heavy"]
    if not ok:
        return str(week["host"])
    load = {r: _morning_load([x for x in plan["rows"] if x["role"] == r]) for r in ok}
    return min(ok, key=lambda r: (load[r], r != week["host"], roles.index(r)))


def _spare(r: dict[str, Any], rows: list[dict[str, Any]], tg: dict[str, dict[str, float]]) -> bool:
    """The whole slot can go: every muscle and head it credits stays at or over its aim (and floor) without it."""
    c = _count(rows)
    return all(c[m] - v * r["sets"] >= max(tg.get(m, {}).get("aim", 0.0), tg.get(m, {}).get("floor", 0.0)) for m, v in r["credit"].items())


def _redline(rows: list[dict[str, Any]], tg: dict[str, dict[str, float]], prio: set[str]) -> list[str]:
    """The owner's weekly hard-set redline as a CHECK on the plan: over it, one set at a time comes off the non-priority isolation
    slot whose main muscle sits furthest over its floor (never a slot under 2, never a floor broken). Returns the lines."""
    from training import owner_redlines

    cap = int(owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"][1])
    lo, taken = int(cfg.value("slot_min_sets")), 0
    while sum(r["sets"] for r in rows) > cap:
        c = _count(rows)
        cands = [
            r
            for r in rows
            if r["kind"] == "accessory" and r["intensity"] != "carry" and r["sets"] > lo and r["credit"]
            and max(r["credit"], key=r["credit"].get) not in prio
            and all(c[m] - v >= tg.get(m, {}).get("floor", 0.0) for m, v in r["credit"].items())
        ]  # fmt: skip
        if not cands:
            break
        best = max(
            cands,
            key=lambda r: (
                c[max(r["credit"], key=r["credit"].get)] - tg.get(max(r["credit"], key=r["credit"].get), {}).get("floor", 0.0),
                rows.index(r),
            ),
        )
        best["sets"] -= 1
        taken += 1
    return [f"redline: {taken} set(s) off — the week held to the owner's {cap} hard sets"] if taken else []


def _head_needs(r: dict[str, Any], rows: list[dict[str, Any]], tg: dict[str, dict[str, float]]) -> bool:
    """A slot whose delt head would fall under its aim keeps its sets."""
    c = _count(rows)
    return any(r["credit"].get(h) and c[h] - r["credit"][h] < tg.get(h, {}).get("aim", 0) for h in HEADS)


def press_trade_alternative(catalog: dict[str, Any], lib: dict[str, Any]) -> dict[str, Any]:
    """The owner's alternative to ruling 6 IN NUMBERS (reported, never applied): the normal week's final plan with the press's
    extra sets from the lateral raises (the ruling, served) and from the rear-delt surplus (face pulls) — each delt head, the
    shoulders, and the plan's total sets."""
    out = {}
    for name, source in (("default", "lateral_raise"), ("alternative", "face_pull")):
        plan = week_plan(catalog, lib, 5, press_source=source)
        out[name] = {h: plan["counts"].get(h, 0.0) for h in HEADS + ("shoulders",)} | {"total_sets": sum(r["sets"] for r in plan["rows"])}
    return out


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
            title = (ctx["catalog"].get(r["key"]) or {}).get("title") or r["key"]
            aim = plan["targets"].get(r["fill"], {}).get("aim")
            lines.append(f"added (live): {title} {r['sets']} x 8-15 — {r['fill']} under its weekly aim of {aim:g} (live_volume fill)")
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


def _prio(key: Any, catalog: dict[str, Any], lib: dict[str, Any], slack: dict[str, float] | None = None) -> bool:
    """The time fit's protected tier: the movement's main muscle is a priority muscle, or the week's plan holds that muscle (or
    one of its delt heads) within one set of its floor (`slack`: plan count minus floor) — the last sets a floor needs go last."""
    c = credits(lib_entry(key, catalog, lib), key, catalog)
    if not c:
        return False
    main = max((m for m in c if m not in HEADS), key=c.get, default=None)
    if main in {str(m) for m in _settings(lib).get("priority_muscles") or []}:
        return True
    return any(m in (slack or {}) and (slack or {})[m] < 1.0 for m in c if m == main or m in HEADS)  # its main muscle or a head


def floor_slack(plan: dict[str, Any], role: str | None = None) -> dict[str, float]:
    """Muscle (and delt head) -> the hard sets the time fit may spend before the week's floor breaks: the plan's surplus over the
    floor, apportioned to `role`'s morning by its share of the muscle's planned sets (every morning's fit spends only its share)."""
    here = _count([r for r in plan["rows"] if r["role"] == role]) if role else None
    out = {}
    for m, t in plan["targets"].items():
        if not t["floor"]:
            continue
        total = float(plan["counts"].get(m, 0.0))
        share = (float(here.get(m, 0.0)) / total) if (here is not None and total) else 1.0
        out[m] = round((total - float(t["floor"])) * share, 2)
    return out


def next_cut(items: list[tuple[Any, ...]]) -> tuple[int, str] | None:
    """THE trim order (`live_settings.TRIM_ORDER`) over items (anchor, carry, priority, working sets[, slack]): (index, "set" |
    "drop") — the latest-listed candidate of the first tier that has one: non-priority accessory back-offs, non-priority anchor
    back-offs, (fix round 10) a whole non-priority accessory at 2 whose muscle stays over its floor without it, priority back-offs
    (the one whose muscle sits furthest over its floor first — `slack` — so a ruled floor breaks last); then a carry, any other
    whole non-priority accessory at 2, a priority one. Anchors never under 2, never dropped."""
    floor = int(cfg.value("slot_min_sets"))
    tiers: list[list[tuple[int, str]]] = [[], [], [], [], [], []]
    room = {i: float(it[4]) if len(it) > 4 else 0.0 for i, it in enumerate(items)}
    for i, (anchor, carry, prio, n, *_rest) in enumerate(items):
        if carry and not anchor:
            tiers[3].append((i, "drop"))
        elif n > floor:
            tiers[2 if prio else (1 if anchor else 0)].append((i, "set"))
        elif not anchor:
            tiers[5 if prio else 4].append((i, "drop"))
    tiers[2].sort(key=lambda c: (room[c[0]], c[0]))
    spare = [c for c in tiers[4] if len(items[c[0]]) > 4 and room[c[0]] >= items[c[0]][3]]  # its muscle stays over its floor
    order = [tiers[0], tiers[1], spare, tiers[2], tiers[3], tiers[4], tiers[5]]
    return next((tier[-1] for tier in order if tier), None)


def _room(key: Any, catalog: dict[str, Any], lib: dict[str, Any], slack: dict[str, float]) -> float:
    """How far a movement's main muscle (and its delt heads) sits over the week's floor: the least slack among them."""
    c = credits(lib_entry(key, catalog, lib), key, catalog)
    main = max((m for m in c if m not in HEADS), key=c.get, default=None)
    return min((float(slack[m]) for m in c if (m == main or m in HEADS) and m in slack), default=99.0)


def fit_sets(
    rx: dict[str, Any], cap: Any, catalog: dict[str, Any], lib: dict[str, Any], slack: dict[str, float] | None = None
) -> list[str]:
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
    """IN PLACE: the routine as written (warm-ups included) to `cap` minutes by `next_cut`. Returns the line (empty when it fits).
    Under the shared cap the conditioning dose takes only what lifting leaves (ruling 1: never strength work for cardio)."""
    from training import selection_engine as se
    from training.session_shape import routine_minutes

    lib = se.load_library_failsoft() or {}
    slack = (rx.get("live_session") or {}).get("floor_slack") or {}
    kinds = {e.get("movement_key"): e for e in rx.get("exposures") or []}
    before = routine_minutes(blocks, movements)["lifting_minutes"]
    done: list[str] = []
    done += _fit_to(blocks, kinds, movements, lib, slack, int(cap))
    if not done:
        return []
    after = routine_minutes(blocks, movements)["lifting_minutes"]
    return [
        f"time (live): ~{before} min as written (warm-ups included) > the {cap}-min cap — {', '.join(done)} (one order: "
        f"non-priority back-offs first, priority last) -> ~{after} min"
    ]


def _fit_to(
    blocks: list[Any],
    kinds: dict[str, Any],
    movements: dict[str, Any],
    lib: dict[str, Any],
    slack: dict[str, float],
    cap: int,
) -> list[str]:
    from training.live_session import _unpair
    from training.session_shape import routine_minutes

    done: list[str] = []
    while routine_minutes(blocks, movements)["lifting_minutes"] > cap:
        lifts = [i for i, b in enumerate(blocks) if b.movement_key in kinds]
        items = [
            (
                kinds[blocks[i].movement_key].get("kind") == "anchor",
                kinds[blocks[i].movement_key].get("intensity") == "carry",
                _prio(blocks[i].movement_key, movements, lib, slack),
                _work(blocks[i]),
                _room(blocks[i].movement_key, movements, lib, slack),
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
    return done
