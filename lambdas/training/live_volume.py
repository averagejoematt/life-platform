"""live_volume.py — THE one weekly volume plan and THE one time fit of the live engine (#5861, fix round 9: consolidation). LIVE only.

Fix rounds 1-8 grew about twelve interacting volume mechanisms (an allocation, a parity rule, a priority add, at-MAV donors, a
quadriceps slot, a week floor, an abs floor, an arms floor, a trunk floor with its fallback order, cardio-room trims, a set cap
and a time fit) — several of them only there to undo another. Round 9 replaces them with two:

  1. ONE WEEKLY HARD-SET PLAN PER MUSCLE (`week_plan`). From the mornings declared this week, each muscle gets a target:
       * a priority muscle (`priority_muscles`) a floor of MEV and an aim ABOVE it — `priority_aim_share` of the way to MAV;
       * every other muscle a floor of its maintenance volume (MV), an aim of MEV on a full week, never more than its MAV;
       * direct abs `abs_direct_sets_per_week` (halved on a 1-3 morning week);
       * each delt head counted apart with explicit fractional credit (pressing -> front and, overhead, half a side; rowing ->
         rear), side and rear each with an aim (owner ruling #9);
       * on a 1-3 morning week, maintenance pro rata: MV x mornings / 3 (a priority muscle MEV x mornings / 3).
     The template week is sized to it: isolation surplus over MAV gives first; then ONE STEP spends the free minutes (`spend`,
     fix round 11): while a muscle sits under its aim, the one FURTHEST under it (plus what last week left it short — the weekly
     memory that rotates short weeks) takes a set on the morning with the most free minutes that may hold it — its isolation
     slot grows (never past 3 sets), else a 2-set low-fatigue FILL slot joins; never past the movement cap or the minutes the
     morning has (the conditioning host keeps its dose's minutes, ruling 1). Nothing is cut to make a priority look bigger. The
     overhead press's extra sets (ruling 6) come from the side-delt (lateral raise) sets. After the pain rule the same step
     spends that morning's minutes on what the pain rule took (`spend_session`), from reviewed, low-stress movements only.
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
    "glutes": ("machine_hip_thrust", "db_hip_thrust", "glute_kickback_machine", "hip_thrust_barbell"),
    "back": ("seated_cable_row_bar_grip", "lat_pulldown", "db_chest_supported_rows", "straight_arm_lat_pulldown_cable"),
    "rear_delts": ("face_pull", "reverse_pec_deck", "chest_supported_reverse_fly_dumbbell"),
}
"""A muscle under its aim with no slot left to grow takes the first of these the gym serves (familiar movements first; the
time fit and the pain rule still apply). Practitioner consensus: low-fatigue isolation for the target muscle."""
ARMS = ("biceps", "triceps")
"""Owner ruling 9 as an outcome (fix round 11): on a full week a priority muscle's aim is at least one set over the busier arm —
reached by spending free minutes (or, time short, sets OVER another muscle's own aim), never by cutting an arm under its aim."""
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


def targets(lib: dict[str, Any], mornings: int) -> dict[str, dict[str, float]]:
    """Muscle (and delt head) -> {floor, aim, cap} in hard sets for this week (module doc 1)."""
    s = _settings(lib)
    prio = {str(m) for m in s.get("priority_muscles") or []}
    out: dict[str, dict[str, float]] = {}
    short = mornings <= 3
    per = float(cfg.value("short_week_floor"))
    for m, lm in _marks().items():
        mv, mev, mav = float(lm.get("MV", 0)), float(lm["MEV"]), float(lm["MAV"])
        if m == "abs":  # owner ruling #8: ~4 direct sets a week; a 1-3 morning week halves it
            n = float(s.get("abs_direct_sets_per_week") or 0)
            n = math.ceil(n / 2) if short else n
            out[m] = {"floor": 0.0 if short else n, "aim": n, "cap": mav}  # a short week: no floor, the rotation takes its turn
        elif short:  # a 1-3 morning week holds maintenance pro rata; a priority muscle aims at MEV pro rata
            floor = max(float(cfg.value("slot_min_sets")), math.ceil(mv * mornings / per)) if (m in prio or m in MAJOR) else 0.0
            aim = max(floor, math.ceil((mev if m in prio else mv) * mornings / per))
            out[m] = {"floor": floor, "aim": aim, "cap": mav}
        elif m in prio:  # fix round 11: a priority muscle aims ABOVE MEV — a quarter of the way to MAV (priority_aim_share)
            out[m] = {"floor": mev, "aim": float(math.ceil(mev + float(cfg.value("priority_aim_share")) * (mav - mev))), "cap": mav}
        elif mornings == 4 and m in FOUR_DAY_MEV:  # ruling 3: the week without shoulders+arms holds them at MEV, counted
            out[m] = {"floor": mev, "aim": mev, "cap": mav}
        else:  # a full week aims every other muscle at MEV (its floor stays MV: time and recovery may take it there)
            out[m] = {"floor": mv, "aim": mev if mornings >= 5 else mv, "cap": mav}
    for head, aim in cfg.value("delt_heads").items():  # pro rata under 5 mornings (fix round 11: the 4-day week drops shoulders+arms)
        n = float(math.ceil(float(aim) * min(mornings, 5) / 5))
        if mornings >= 5 or head == "side_delts":  # under 5 mornings no floor: time decides (ruling 3 holds the shoulders)
            out[head] = {"floor": n if mornings >= 5 else 0.0, "aim": n, "cap": 99.0}
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


def _fill_keys(
    muscle: str, catalog: dict[str, Any], lib: dict[str, Any], taken: set[str], overlay: Any = None, ok: Any = None
) -> list[str]:
    """The FILL movements for `muscle` the gym serves (`overlay`: the private equipment and pain notes), reviewed (owner ruling
    16: missing data is no proof of suitability), not already in the week, and passing `ok` (the session's pain rule) — in FILL
    order (familiar, low-fatigue isolation first)."""
    from training import live_pain, selection_engine as se

    out = []
    for key in FILL.get(muscle, ()):
        entry = lib_entry(key, catalog, lib)
        if key in catalog and key not in taken and entry and live_pain.reviewed(entry) and not se.availability(entry, lib, overlay):
            if not se.pain_exclusion(entry, overlay) and (ok is None or ok(key, entry)):
                out.append(key)
    return out


def _half_ok(muscle: str, role: str, full: bool) -> bool:
    """A muscle's isolation goes on its half of the body (upper / lower); abs and calves anywhere; a full-body morning takes both."""
    from training import program_structure as ps

    if full or muscle in ANYWHERE:
        return True
    half = (ps.SESSION_TEMPLATES.get(role) or {}).get("archetype")
    return half is None or (muscle in UPPER) == (half == "upper")


def _rest_seconds(intensity: Any) -> int:
    from training.program_structure import EXPOSURES

    return int((EXPOSURES.get(str(intensity)) or EXPOSURES["accessory"])["rest_seconds"])


def plan_minutes(rows: list[dict[str, Any]]) -> float:
    """A morning's planned lifting minutes from its plan rows — the one time model (`session_shape.session_minutes_estimate`,
    warm-ups assumed for the compound anchors and for every slot the plan added), so the plan spends the minutes the time fit
    will measure."""
    from training.session_shape import session_minutes_estimate

    ex = [  # a slot the plan added may be new to him: its "find the load" warm-up set is counted (an upper bound)
        {
            "kind": r["kind"],
            "pattern": r["pattern"],
            "sets": [{}] * (int(r["sets"]) + bool(r.get("fill"))),
            "rest_seconds": _rest_seconds(r["intensity"]),
        }
        for r in rows
    ]
    if any(r.get("guest") for r in rows):  # a full-body morning's paired anchors rest once per pair (`FULL_BODY_PAIRS`)
        pats = {str(e["pattern"]): e for e in ex if e["kind"] == "anchor"}
        for a, b in FULL_BODY_PAIRS:
            if a in pats and b in pats:
                pats[a]["rest_seconds"] = 0
    return float(session_minutes_estimate(ex)["lifting_minutes"]) if ex else 0.0


def free_minutes(rows: list[dict[str, Any]], role: str, host: str | None, lib: dict[str, Any], reserve: bool = True) -> float:
    """The minutes this morning's lifting may still take: the lifting ceiling less the plan's minutes (an upper bound: every
    anchor's warm-ups assumed, no paired-set saving), less the conditioning dose's reserve on its host morning under the shared
    cap (owner ruling 1 + the ruled one hard dose a week: the dose takes only what lifting leaves, so the plan leaves it room
    rather than filling it with isolation). No reserve on a 1-2 morning week (lifting first) or with `reserve` False."""
    from training.session_shape import lifting_minutes_cap

    cap = float(lifting_minutes_cap())
    shared = _settings(lib).get("session_cap_includes_cardio")
    if reserve and shared and role == host and len({r["role"] for r in rows}) >= 3:
        cap -= float(cfg.value("conditioning_reserve_minutes"))
    return cap - plan_minutes([r for r in rows if r["role"] == role])


def _iso(m: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The isolation slots whose main credit is `m` (a delt head: its landmark muscle's slots that credit the head)."""
    return [
        r
        for r in rows
        if r["kind"] == "accessory"
        and r["intensity"] != "carry"
        and max(r["credit"], key=r["credit"].get, default="") in (m, LANDMARK_OF.get(m, m))
        and r["credit"].get(m)
    ]


def spend(
    rows: list[dict[str, Any]],
    tg: dict[str, dict[str, float]],
    roles: list[str],
    full: dict[str, bool],
    room: Any,
    add: Any,
    last: dict[str, str] | None = None,
    budget: float | None = None,
    lead: frozenset[str] = frozenset(),
) -> list[str]:
    """THE ONE STEP that spends free minutes (fix round 11 — it replaces the grow/fill rules, the priority parity, the short-week
    rotation and the pain refill): while a muscle sits under its aim, the one FURTHEST under it as a share of its aim (one under its floor first; on a
    tie the one he trained longest ago — `last`, the weekly memory that rotates short weeks) takes one more set on the morning with
    the most free minutes (`room(role)`) that may hold it: an isolation slot it already has grows (never past `slot_max_sets`),
    else `add(muscle, role)` places a new 2-set slot (a second movement only once the first is full). Never past the movement
    cap. Time or the week's set `budget` short: a muscle OVER its own aim gives the set (`_make_room`) — never under its aim.
    `lead`: the priority muscles, whose aim is also one set over the busier arm (`_aim`). Returns the lines."""
    lo, hi = int(cfg.value("slot_min_sets")), int(cfg.value("slot_max_sets"))
    one = plan_minutes([{"kind": "accessory", "pattern": None, "sets": 1, "intensity": "accessory"}])
    blocked: set[str] = set()
    lines: list[str] = []
    gave: Counter = Counter()
    for _ in range(96):
        c = _count(rows)
        need = sorted(  # under its FLOOR first (a ruled hold, ruling 3), then the furthest under its aim
            (m for m in tg if m not in blocked and c[m] + 1e-9 < _aim(m, c, tg, lead)),
            key=lambda m: (c[m] + 1e-9 >= tg[m]["floor"], -round(1 - c[m] / _aim(m, c, tg, lead), 2), (last or {}).get(m, ""), m),
        )
        if not need:
            break
        m, placed = need[0], False
        for role in sorted((r for r in roles if _half_ok(m, r, full.get(r, False))), key=lambda r: (-room(r, m), roles.index(r))):
            here = [r for r in rows if r["role"] == role]
            grow = [r for r in _iso(m, here) if r["sets"] < hi]
            spread = m in FILL_FIRST and _spread(m, rows, roles, full, room, lo)  # owner ruling #8: abs over the mornings
            if grow and not spread and _make_room(rows, tg, lead, role, m, one, room, budget, gave):
                max(grow, key=lambda r: (r.get("fill") == m, -r["sets"]))["sets"] += 1
                placed = True
                break
            full_up = len(here) >= (FULL_BODY_MAX_MOVEMENTS if full.get(role) else MAX_MOVEMENTS)
            if len(_iso(m, here)) < 2 and not grow and add(m, role, probe=True):
                if _make_room(rows, tg, lead, role, m, lo * one, room, budget, gave, slot=full_up):
                    new = add(m, role)
                    rows.append(new)
                    lines.append(f"spend: {role} + {new['key']} x{lo} ({m} under its aim of {_aim(m, _count(rows), tg, lead):g})")
                    placed = True
                    break
        if not placed:
            blocked.add(m)
    return lines + (
        [f"spend: time short — {', '.join(f'{k} -{n}' for k, n in sorted(gave.items()))} set(s) over their own aim"] if gave else []
    )


def _aim(m: str, c: Counter, tg: dict[str, dict[str, float]], lead: frozenset[str]) -> float:
    """A muscle's aim now: its target's, and for a `lead` (priority) muscle on a full week at least one set over the busier arm
    (owner ruling 9 read as an outcome, reached by adding — `ARMS`)."""
    aim = float(tg[m]["aim"])
    if m in lead:
        top = max((c[x] for x in ARMS if x not in lead), default=0.0)
        aim = max(aim, min(float(tg[m]["cap"]), math.floor(top) + 1.0))
    return aim


def _make_room(
    rows: list[dict[str, Any]],
    tg: dict[str, dict[str, float]],
    lead: frozenset[str],
    role: str,
    m: str,
    need: float,
    room: Any,
    budget: float | None,
    gave: Counter,
    slot: bool = False,
) -> bool:
    """Room for `need` minutes on `role` (and, `slot`, a movement place) and inside the week's set `budget`: free minutes first,
    else a set from the isolation slot whose main muscle sits furthest OVER its own aim (that morning's for time, any morning's
    for the budget) — never under its aim, never a delt head under its aim, never the muscle being served, never a muscle's last
    isolation slot of the week; a 2-set slot (or one freeing a movement place) goes whole. A morning over the ceiling takes
    nothing more."""
    lo = int(cfg.value("slot_min_sets"))
    one = plan_minutes([{"kind": "accessory", "pattern": None, "sets": 1, "intensity": "accessory"}])
    if room(role, m) < 0:
        return False
    n = int(round(need / one))
    while room(role, m) < need or slot or (budget is not None and sum(r["sets"] for r in rows) + n > budget):
        c = _count(rows)
        here = room(role, m) < need or slot

        def ok(r: dict[str, Any]) -> bool:
            take = r["sets"] if (slot or r["sets"] <= lo) else 1
            if take == r["sets"] and len(_iso(_main(r), rows)) <= 1:
                return False  # never a muscle's last isolation slot of the week (its only leg curl, its only curl)
            return all(c[k] - v * take >= _aim(k, c, tg, lead) if k in tg else True for k, v in r["credit"].items())

        give = [
            r
            for r in rows
            if (r["role"] == role or not here) and r["kind"] == "accessory" and r["intensity"] != "carry" and r["credit"]
            and _main(r) != m and m not in r["credit"] and not r.get("fill") and ok(r)
        ]  # fmt: skip
        if not give:
            return False
        r = max(give, key=lambda r: (c[_main(r)] - _aim(_main(r), c, tg, lead) if _main(r) in tg else 0.0, r["sets"], rows.index(r)))
        whole = slot or r["sets"] <= lo
        gave[_main(r)] += r["sets"] if whole else 1
        if whole:  # drop, don't shave: its muscles all stay at their aims without it
            rows.remove(r)
            slot = False
        else:
            r["sets"] -= 1
    return True


def _main(r: dict[str, Any]) -> str:
    return max(r["credit"], key=r["credit"].get, default="")


def _spread(m: str, rows: list[dict[str, Any]], roles: list[str], full: dict[str, bool], room: Any, lo: int) -> bool:
    """Owner ruling #8: direct ab sets are spread over the mornings — another morning that may still take a new slot comes first."""
    one = plan_minutes([{"kind": "accessory", "pattern": None, "sets": 1, "intensity": "accessory"}])
    return any(
        not _iso(m, [r for r in rows if r["role"] == role]) and room(role, m) >= lo * one and _half_ok(m, role, full.get(role, False))
        for role in roles
    )


def last_trained(workouts: Any, catalog: dict[str, Any], lib: dict[str, Any], day: str) -> dict[str, str]:
    """The weekly memory: muscle (and delt head) -> the last day before `day`'s week he LOGGED a working set crediting it (the
    set-credit table). It only breaks ties in `spend` — the muscle trained longest ago takes the free slot first, so consecutive
    short weeks rotate — never a catch-up set (owner ruling 2: a missed week is not recovered set for set)."""
    from common.pacific_time import parse_day_key, shift_day_key

    d = parse_day_key(str(day)[:10])
    if d is None or not workouts:
        return {}
    monday = shift_day_key(str(day)[:10], -d.weekday())
    by_tid = {str(e.get("template_id") or "").upper(): e for e in (lib.get("movements") or {}).values() if e.get("template_id")}
    out: dict[str, str] = {}
    for w in workouts:
        date = str(w.get("date") or str(w.get("sk") or "")[5:15])[:10]
        if date >= monday:
            continue
        for x in w.get("exercises") or []:
            entry = by_tid.get(str(x.get("template_id") or "").upper()) or lib_entry(x.get("template_id"), catalog, lib)
            if not any(str(st.get("type") or "normal") != "warmup" for st in x.get("sets") or []):
                continue
            for m in credits(entry) if entry else {}:
                out[m] = max(out.get(m, ""), date)
    return out


def week_plan(
    catalog: dict[str, Any],
    lib: dict[str, Any],
    mornings: int,
    press_source: str = "lateral_raise",
    last: dict[str, str] | None = None,
    overlay: Any = None,
) -> dict[str, Any]:
    """The week's plan (module doc 1): {week, rows (every drafted morning's rows, sized), targets, counts, under, host, lines}.
    Pure over the catalog, the library, the mornings and the weekly memory (`last`); the same for every morning of the week."""
    week = week_shape(mornings)
    rows = [r for role in week["roles"] for r in day_rows(role, week, catalog, lib)]
    lines = _press_trade(rows, lib, press_source)
    tg = targets(lib, week["mornings"])
    lo = int(cfg.value("slot_min_sets"))
    prio = {str(m) for m in _settings(lib).get("priority_muscles") or []}
    surplus = _surplus(rows, tg, prio, lines)
    surplus()  # 1. surplus over the cap gives first
    host = _host(week, rows)
    roles = list(week["roles"])
    full = {r: bool((week.get("partners") or {}).get(r)) for r in roles}
    taken = {str(r["key"]) for r in rows}

    def add(m: str, role: str, probe: bool = False) -> Any:
        here = {lib_entry(r["key"], catalog, lib).get("pattern") for r in rows if r["role"] == role}  # never the same pattern twice
        keys = [k for k in _fill_keys(m, catalog, lib, taken, overlay) if lib_entry(k, catalog, lib).get("pattern") not in here]
        if not keys or probe:
            return bool(keys)
        taken.add(keys[0])
        new = {"kind": "accessory", "slot": f"fill_{m}", "intensity": "accessory", "movement_key": keys[0], "sets": [{}] * lo}
        return _row(role, new, catalog, lib) | {"fill": m}

    lead = frozenset(m for m in prio if m in tg) if week["mornings"] >= 5 else frozenset()
    room = lambda role, m=None: free_minutes(rows, role, host, lib)  # noqa: E731 — the ruled dose keeps its minutes (ruling 1)
    lines += spend(rows, tg, roles, full, room, add, last, _redline_sets(), lead)  # 2. the one step
    surplus()  # 3. again: a head's aim may have grown its muscle past MAV (ruling 9)
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
        "host": host,
        "lines": lines,
    }


def _surplus(rows: list[dict[str, Any]], tg: dict[str, dict[str, float]], prio: set[str], lines: list[str]) -> Any:
    """Surplus over the cap gives first: non-priority isolation, largest slot first, never under 2; a slot already at 2 goes whole
    when every muscle and head it trains stays at its aim (ruling 9: never force total shoulder volume)."""
    lo = int(cfg.value("slot_min_sets"))

    def run() -> None:
        for m, t in tg.items():
            while _count(rows)[m] > t["cap"] and m not in prio:
                give = [r for r in _iso(m, rows) if r["sets"] > lo and not _head_needs(r, rows, tg)]
                if give:
                    max(give, key=lambda r: (r["sets"], rows.index(r)))["sets"] -= 1
                    continue
                whole = [r for r in _iso(m, rows) if r["sets"] and _spare(r, rows, tg)]
                if not whole:
                    break
                gone = whole[-1]
                rows.remove(gone)
                lines.append(f"surplus: {gone['role']} - {gone['key']} ({m} over its MAV, every head at its aim)")

    return run


def _host(week: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Fix round 10: the week's hard conditioning dose goes on the drafted morning with the most free minutes (its template
    plan, before any fill) — never the heavy lower day or the morning before it; the template host breaks a tie. Owner ruling 1:
    the dose takes only the minutes lifting leaves, never a lifting set (the plan reserves its minutes there)."""
    from training import program_structure as ps

    order = list(ps.SPLIT_ROLES)
    ok = [r for r in week["roles"] if r != "lower_heavy" and order[(order.index(r) + 1) % len(order)] != "lower_heavy"]
    if not ok:
        return str(week["host"])
    load = {r: plan_minutes([x for x in rows if x["role"] == r]) for r in ok}
    return min(ok, key=lambda r: (load[r], r != week["host"], order.index(r)))


def conditioning_host(plan: dict[str, Any]) -> str:
    """The week's conditioning host (`_host`, decided before the plan spends its free minutes)."""
    return str(plan.get("host") or _host(plan["week"], plan["rows"]))


def spend_session(rx: dict[str, Any], ctx: dict[str, Any], flags: list[dict[str, Any]]) -> list[str]:
    """IN PLACE, live only — the same ONE step on this morning after the session fit and the pain rule (fix round 11: it replaces
    the refill): each muscle this morning's planned share lost (a lift the gym cannot serve, a routed or skipped lift, a swap
    that trains it less) is a shortfall, and this morning's free minutes go to the
    one furthest under first, from REVIEWED movements the gym serves that load every flagged joint LOW (FILL first, then the
    muscle's reviewed route, `live_pain.muscle_route`). With none, the muscle is zero here by design. Returns the lines."""
    from training import live_pain
    from training.program_structure import EXPOSURES

    plan = ctx.get("volume_plan") or {}
    role = str(rx.get("session_role") or "")
    planned = _count([r for r in plan.get("rows") or [] if r["role"] == role])
    rows = [_row(role, e, ctx["catalog"], ctx["lib"]) for e in rx["exposures"]]
    now = _count(rows)
    week_t, week_c = plan.get("targets") or {}, plan.get("counts") or {}

    def ruled(m: str, v: float) -> float:  # a muscle the loss takes under its WEEK floor (ruling 3's hold) is served first
        short = float(week_c.get(m, 0.0)) - v + now[m] < float((week_t.get(m) or {}).get("floor", 0.0))
        return float(v) if short else 0.0

    if not any(m not in HEADS and now[m] + 1.0 <= v for m, v in planned.items()):
        return []
    # every planned muscle keeps its planned share (none donates under it); only a muscle a full set short is served
    tg = {
        m: {"floor": ruled(m, v), "aim": float(v) if now[m] + 1.0 <= v else min(float(v), now[m]), "cap": 99.0}
        for m, v in planned.items()
        if m not in HEADS
    }
    joints = sorted({j for f in flags for j in f["joints"]})
    taken = {str(e.get("movement_key")) for e in rx["exposures"]}
    lo = int(cfg.value("slot_min_sets"))

    def ok(key: str, entry: dict[str, Any]) -> bool:
        return live_pain._low(entry, joints) and not _unservable(key, ctx)

    def add(m: str, r: str, probe: bool = False) -> Any:
        keys = _fill_keys(m, ctx["catalog"], ctx["lib"], taken, ctx.get("overlay"), ok)
        seed = next(iter(FILL.get(m, ())), None)
        key = keys[0] if keys else (live_pain.muscle_route({"movement_key": seed}, ctx, taken, joints) if seed else None)
        if not key or probe:
            return bool(key)
        taken.add(key)
        new = {"kind": "accessory", "slot": f"spend_{m}", "intensity": "accessory", "movement_key": key, "sets": [{}] * lo}
        return _row(r, new, ctx["catalog"], ctx["lib"]) | {"fill": m}

    def room(_r: str, _m: str | None = None) -> float:
        return free_minutes(rows, role, str(plan.get("host") or ""), ctx["lib"])

    full = bool(((plan.get("week") or {}).get("partners") or {}).get(role))  # a split morning keeps its half of the body
    lines = spend(rows, tg, [role], {role: full}, room, add)
    by_key = {str(e.get("movement_key")): e for e in rx["exposures"]}
    for r in rows:
        e = by_key.get(str(r["key"]))
        if e is not None:
            _resize(e, r["sets"])
            continue
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
                "live_added": r["slot"],
            }
        )
    out = [
        f"added (live): {(ctx['catalog'].get(r['key']) or {}).get('title') or r['key']} {r['sets']} x 8-15 — {r['fill']}, reviewed "
        "and low on the flagged joint, in this morning's free minutes"
        for r in rows
        if r.get("fill") and str(r["key"]) not in by_key
    ]
    return out if lines else []


def _unservable(key: str, ctx: dict[str, Any]) -> bool:
    from training import live_session

    return bool(live_session._servable(key, ctx))


def _spare(r: dict[str, Any], rows: list[dict[str, Any]], tg: dict[str, dict[str, float]]) -> bool:
    """The whole slot can go: every muscle and head it credits stays at or over its aim (and floor) without it."""
    c = _count(rows)
    return all(c[m] - v * r["sets"] >= max(tg.get(m, {}).get("aim", 0.0), tg.get(m, {}).get("floor", 0.0)) for m, v in r["credit"].items())


def _redline_sets() -> int:
    from training import owner_redlines

    return int(owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"][1])


def _redline(rows: list[dict[str, Any]], tg: dict[str, dict[str, float]], prio: set[str]) -> list[str]:
    """The owner's weekly hard-set redline as a CHECK on the plan: over it, one set at a time comes off the non-priority isolation
    slot whose main muscle sits furthest over its floor (never a slot under 2, never a floor broken). Returns the lines."""
    cap = _redline_sets()
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
    floor, apportioned to `role`'s morning by its share of the muscle's planned sets (every morning's fit spends only its share);
    none for a muscle whose only isolation slot of the week this is (the time fit then cuts it last)."""
    here = _count([r for r in plan["rows"] if r["role"] == role]) if role else None
    out = {}
    for m, t in plan["targets"].items():
        if not t["floor"]:
            continue
        total = float(plan["counts"].get(m, 0.0))
        share = (float(here.get(m, 0.0)) / total) if (here is not None and total) else 1.0
        out[m] = round((total - float(t["floor"])) * share, 2)
    for m in {_main(r) for r in plan["rows"]}:  # fix round 11: a muscle's ONLY isolation slot of the week (its leg curl) goes last
        if len(_iso(m, plan["rows"])) == 1 and m in out:
            out[m] = 0.0
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
