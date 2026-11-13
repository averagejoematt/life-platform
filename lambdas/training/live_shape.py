"""live_shape.py — the fourth red team's WEEK-SHAPE fixes (#5861 FIX4). LIVE only: every entry point is reached from a live hook
(`live_program.plan` / `cardio_fit`, `live_session.for_live_draft` / `fit_routine`, `live_balance.allocation_plan`,
`mcp.draft_standing_constraint.gate_draft` through `live_program.cardio_context`), each of which returns before reading anything
unless the draft ran the live session fit (`live_session.MARK`, which exists only when the exercise library is `approved`).
tests/test_no_live_change_5861_l6.py pins the served proposed-mode drafts byte for byte.

WHY IT EXISTS. A fourth independent red team (2026-11-12, programming C+) read the generated weeks as a coach would:

  1. VOLUME (`reallocate`, `week_ceiling`, `quad_slot`). The live additions put the week at 76 working sets (the owner's
     redline is 75: `owner_redlines` total_hard_sets_wk); chest and quadriceps — priority muscles — sat at MEV+1 while the
     shoulders sat at MAV; a leg extension (rated S for the rectus femoris, logged often) was never served because the
     selection only swaps like for like. Now muscles AT their MAV give isolation sets too (not only those over it), the
     priority muscles at or under MEV + PRIORITY_MARGIN take them, a quadriceps isolation slot is added on the lower-volume
     day when the quads sit there and his history shows the movement, and the week is held to the redline.
  2. DROP, DON'T SHAVE (`no_single_sets`). Time trims left one-set accessories and one-set superset halves.
  3. ORDER AND THE HEAVY PULL (`order_lower_volume`, `deadlift_shape`). The lower-volume day put the RDL before the back squat
     (the erectors tire first). The heavy-day squat + deadlift pairing is the owner's ruling (#5694) and stays; the
     deadlift's shape is a setting (`heavy_day_deadlift_shape`: `as_today` = top set + two back-offs, `top_plus_backoff` =
     top set + one back-off).
  4. THE AEROBIC GAP UNDER THE SHARED CAP (`walk_prompt`, `walk_note`). The engine reported "~64 min short" and served
     nothing. One optional, concrete walk now closes the gap on the conditioning host's morning; under the default cap an easy
     ride is no longer added when one walk covers what is left (WALK_PROMPT). #5861 FIX6 (ruling 12): the gap is measured
     against RECORDED walking with intensity evidence (`cardio_model.recorded_aerobic`); steps alone earn no credit.
  5. THE KETTLEBELL SLOT UNDER STRAIN (`kb_under_strain`): `kb_slot_under_strain` `as_today` (the slot follows its placement)
     or `drop` — the red team's recommendation: an overreached or deload-recommended week drops the KB hinge.

Every number here is a labelled PLATFORM HEURISTIC (practitioner consensus at best), owner-adjustable; none is validated.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

SETTINGS_DEFAULTS: dict[str, Any] = {
    "heavy_day_deadlift_shape": "top_plus_backoff",  # #5861 FIX6: owner ruling 5 (2026-11-13), was as_today
    "kb_slot_under_strain": "drop",  # #5861 FIX6: owner ruling 7, was as_today
}
"""OWNER DECISIONS, today's behaviour by default. `heavy_day_deadlift_shape` `as_today` (the heavy exposure's top set + two
back-offs) | `top_plus_backoff` (top set + one back-off: the fourth red team's recommendation for a heavy trainee in a deficit).
`kb_slot_under_strain` `as_today` (the slot follows `kb_slot_role` / `kb_slot_when_stacked`) | `drop` (the red team's
recommendation: a strained, overreached or deload-recommended week drops the kettlebell hinge)."""
VOLUME: dict[str, dict[str, Any]] = {
    "priority_margin": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "fourth red team (2026-11-12): chest 9 and quadriceps 9.5 (MEV 8; the count credits a secondary set at half) were "
        "left 'done' at MEV + 1 while the shoulders sat at MAV — a priority muscle at or under MEV + 2 takes freed sets first",
    },
    "at_mav_give": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "a muscle AT its MAV (not only over it) gives up to two isolation sets a week while a priority muscle needs them "
        "(never a slot under two sets, never a pinned slot or a carry)",
    },
}
QUAD_SLOT: dict[str, Any] = {
    "keys": ("leg_extension_machine", "single_leg_extension", "leg_press_machine"),
    "role": "lower_volume",
    "sets": 2,
    "history_min": 3,
    "label": HEURISTIC,
    "basis": "fourth red team: the leg extension (hypertrophy S for the rectus femoris) was never served — the selection swaps like for "
    "like and no template slot asks for a knee-extension isolation. When the quadriceps sit at or under MEV + priority_margin, "
    "the QUAD_SLOT `role` (its template has no quadriceps accessory) takes a two-set quadriceps isolation: the first of `keys` his history shows "
    "(logged on history_min+ days in the catalog) and the gym has; its sets come from the freed / at-MAV sets",
}
WALK_PROMPT: dict[str, dict[str, Any]] = {
    "max_minutes": {
        "value": 40,
        "label": HEURISTIC,
        "basis": "one optional brisk walk covers a weekly aerobic gap up to this size (a 30-45 min walk is an ordinary day's "
        "addition); under the default cap a larger gap still earns an easy ride, a smaller one is the walk's",
    },
    "min_minutes": {"value": 15, "label": HEURISTIC, "basis": "a gap under 15 minutes is noise against the recorded walking: no prompt"},
    "active_steps": {
        "value": 7500,
        "label": HEURISTIC,
        "basis": "#5861 FIX8 (owner ruling 12; the seventh red team: a 14k-step walker served easy rides and a 40-min walk prompt): "
        "when the recorded workouts leave the week short but the steps average at least ~7,500/day (the conventional 'somewhat "
        "active' line, a population heuristic), the aerobic minutes are UNKNOWN, not missing — reported, never turned into a gap. "
        "A purposeful aerobic prompt needs short recorded minutes AND low steps",
    },
}


def intensity_unknown(aer: dict[str, Any] | None) -> bool:
    """WALK_PROMPT active_steps (ruling 12): the recorded minutes leave the week short, but the steps say he is moving — the
    intensity is unknown, so there is no gap to close."""
    from training import cardio_model

    a = aer or {}
    steps = a.get("steps_per_day")
    short = int(a.get("walking_min_per_wk") or 0) < int(cardio_model.WEEKLY_MODERATE_MIN[0])
    return bool(short and steps is not None and float(steps) >= float(WALK_PROMPT["active_steps"]["value"]))


def _settings(lib: dict[str, Any] | None = None) -> dict[str, Any]:
    from training import live_program, selection_engine as se

    return live_program.settings(lib if lib is not None else se.load_library_failsoft())


# ── 1. volume ────────────────────────────────────────────────────────────────
def week_redline() -> int:
    """The owner's weekly hard-set ceiling: `owner_redlines` lifting_sessions_per_wk total_hard_sets_wk (top)."""
    from training import owner_redlines

    return int(owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"][1])


def _slot_sets(r: dict[str, Any], deltas: dict[tuple[str, str], int]) -> int:
    return int(r["sets"]) + deltas.get((r["role"], str(r["slot"])), 0)


def quad_slot_key(catalog: dict[str, Any], lib: dict[str, Any]) -> str | None:
    """QUAD_SLOT's movement: the first key his history shows (catalog sessions >= history_min) that the gym has."""
    from training import selection_engine as se

    idx = se.key_index(lib, catalog)
    for key in QUAD_SLOT["keys"]:
        c = catalog.get(key) or {}
        entry = (lib.get("movements") or {}).get(idx["to_lib"].get(key) or "") or {}
        if c and entry and int(c.get("sessions") or 0) >= int(QUAD_SLOT["history_min"]) and not se.availability(entry, lib, None):
            return key
    return None


def reallocate(env: dict[str, Any]) -> list[dict[str, Any]]:
    """IN PLACE on env["deltas"] / env["freed"]: the priority muscles at or under MEV + priority_margin take sets — the freed
    over-MAV sets first, then up to at_mav_give from each muscle AT its MAV; the quadriceps take a QUAD_SLOT isolation (two sets)
    when they qualify. Returns the added slots [{role, slot, key, sets, muscle}]."""
    from training import live_balance as lb

    rows, deltas, marks, pinned = env["rows"], env["deltas"], env["marks"], env["pinned"]
    margin, give = int(VOLUME["priority_margin"]["value"]), int(VOLUME["at_mav_give"]["value"])
    floor = int(lb.ALLOCATION["over_mav_floor"]["value"])
    given: Counter = Counter()
    adds: list[dict[str, Any]] = []

    def week() -> Counter:
        out = lb._sum(rows, deltas)
        for a in adds:
            out[a["muscle"]] += a["sets"]
        return out

    def take_one() -> bool:  # one isolation set from a muscle AT its MAV (largest slot first, latest in the week on a tie)
        w = week()
        cands = [
            r
            for r in rows
            if r["kind"] == "accessory"
            and r["slot"] not in pinned
            and r["intensity"] != "carry"
            and r["muscle"] in marks
            and w[r["muscle"]] >= float(marks[r["muscle"]]["MAV"])
            and given[r["muscle"]] < give
            and _slot_sets(r, deltas) > floor
        ]
        if not cands:
            return False
        r = max(cands, key=lambda r: (_slot_sets(r, deltas), rows.index(r)))
        deltas[(r["role"], str(r["slot"]))] = deltas.get((r["role"], str(r["slot"])), 0) - 1
        given[r["muscle"]] += 1
        env["freed"] += 1
        return True

    for m in env["priority"]:
        lm = marks.get(m) or {}
        if not lm or week()[m] > float(lm["MEV"]) + margin:
            continue
        key = quad_slot_key(env["catalog"], env["lib"]) if m == "quadriceps" else None
        n = int(QUAD_SLOT["sets"])
        while key and env["freed"] < n and take_one():
            pass
        if key and env["freed"] >= n:
            adds.append({"role": QUAD_SLOT["role"], "slot": "live_quad_slot", "key": key, "sets": n, "muscle": m})
            env["freed"] -= n
            continue
        for r in [r for r in rows if r["kind"] == "accessory" and r["muscle"] == m and r["slot"] not in pinned]:
            if week()[m] > float(lm["MEV"]) + margin:
                break
            k = (r["role"], str(r["slot"]))
            if deltas.get(k, 0) >= int(lb.ALLOCATION["add_per_slot"]["value"]):
                continue
            if env["freed"] <= 0 and not take_one():
                break
            deltas[k] = deltas.get(k, 0) + 1
            env["freed"] -= 1
    return adds


def week_ceiling(env: dict[str, Any], adds: list[dict[str, Any]]) -> list[str]:
    """IN PLACE on env["deltas"]: the week's planned working sets (templates + allocation + added slots + the trunk floor) held
    to `week_redline` — one isolation set at a time from the muscle furthest over its MEV (never a slot under two sets, a pinned
    slot, a carry or a set the allocation just gave a priority muscle), then a whole isolation accessory. Returns the lines."""
    from training import live_balance as lb, live_program

    rows, deltas, marks, pinned = env["rows"], env["deltas"], env["marks"], env["pinned"]
    floor = int(lb.ALLOCATION["over_mav_floor"]["value"])
    cap = week_redline()
    extra = sum(a["sets"] for a in adds) + int(live_program.TRUNK_FLOOR["sets"]["value"])
    lines = []

    def total() -> int:
        return sum(_slot_sets(r, deltas) for r in rows) + extra

    while total() > cap:
        w = lb._sum(rows, deltas)
        for a in adds:
            w[a["muscle"]] += a["sets"]
        cands = [
            r
            for r in rows
            if r["kind"] == "accessory"
            and r["slot"] not in pinned
            and r["intensity"] != "carry"
            and r["muscle"] in marks
            and deltas.get((r["role"], str(r["slot"])), 0) <= 0
            and _slot_sets(r, deltas) > 0
        ]
        if not cands:
            break
        r = max(cands, key=lambda r: (w[r["muscle"]] - float(marks[r["muscle"]]["MEV"]), rows.index(r)))
        k = (r["role"], str(r["slot"]))
        n = _slot_sets(r, deltas)
        deltas[k] = deltas.get(k, 0) - (1 if n > floor else n)  # a slot at its floor goes whole: drop, don't shave
        lines.append(f"{r['role']}.{r['slot']} -{1 if n > floor else n} set(s): the week held to {cap} (owner_redlines total_hard_sets_wk)")
    return lines


def add_slots(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE, live only (`live_program.plan`, BEFORE the pain rule so a flag reaches it): this session's added slots from the
    week's allocation (`QUAD_SLOT`). Returns the rationale lines."""
    from training import live_balance as lb
    from training.program_structure import EXPOSURES

    plan_ = ctx.get("allocation") or lb.allocation_plan(ctx["catalog"], ctx["lib"], lb._skipped(ctx))
    ctx["allocation"] = plan_
    lines = []
    for a in plan_.get("adds") or []:
        if a["role"] != rx.get("session_role") or any(e.get("movement_key") == a["key"] for e in rx["exposures"]):
            continue
        rx["exposures"].append(
            {
                "kind": "accessory",
                "pattern": None,
                "slot": a["slot"],
                "intensity": "accessory",
                "movement_key": a["key"],
                "resolution_note": None,
                "sets": [{"kind": "working", "reps": [10, 15]} for _ in range(int(a["sets"]))],
                "rest_seconds": int(EXPOSURES["accessory"]["rest_seconds"]),
                "live_added": "quad_slot",
                "live_cost": "low",
            }
        )
        title = (ctx["catalog"].get(a["key"]) or {}).get("title") or a["key"]
        before = (plan_.get("before") or {}).get(a["muscle"])
        lines.append(
            f"added (live): {title} {a['sets']} x 10-15 — {a['muscle']} at {before:g} sets/wk, a priority muscle at MEV + "
            f"{VOLUME['priority_margin']['value']} or under; his history shows it (QUAD_SLOT, heuristic)"
        )
    return lines


# ── 2. drop, don't shave ─────────────────────────────────────────────────────
def no_single_sets(blocks: list[Any], movements: dict[str, Any]) -> list[str]:
    """IN PLACE: an accessory block (never an anchor, a carry or a timed block) left at ONE working set is dropped, and a
    superset it was in is unpaired. Returns the titles dropped."""
    from training import warmup_sets
    from training.live_session import _unpair

    out = []
    for b in list(blocks):
        tag = str(b.rationale_tag or "")
        if not tag.startswith("accessory:") or tag.endswith(":carry") or warmup_sets.working_set_count(b.sets) != 1:
            continue
        if any(getattr(s, "duration_seconds", None) or getattr(s, "distance_meters", None) for s in b.sets):
            continue
        blocks.remove(b)
        _unpair(blocks, getattr(b, "superset_id", None))
        out.append((movements.get(b.movement_key) or {}).get("title") or b.movement_key)
    return out


def next_drop(
    blocks: list[Any], movements: dict[str, Any], taken: Counter, fixed: set[str] | None = None, rx: dict[str, Any] | None = None
) -> int | None:
    """The accessory block the time fit drops next (live): one whose muscle stays at or over its MEV for the week without it,
    the largest surplus first; else the last-listed accessory (today's order). An owner-pinned slot or a live addition
    (`fixed`: the carry, the kettlebell slot, the trunk floor) goes only when nothing else is left. `taken` (IN PLACE) counts the
    sets already off per landmark muscle. None when no accessory is left."""
    from training import block_model, live_week, selection_engine as se, warmup_sets

    lib = se.load_library_failsoft() or {}
    week, marks = live_week.week_sets(movements, lib, rx), block_model.load_landmarks() or {}
    acc = [i for i, b in enumerate(blocks) if str(b.rationale_tag or "").startswith("accessory:")]
    acc = [i for i in acc if blocks[i].movement_key not in (fixed or set())] or acc
    if not acc:
        return None
    best = None
    for i in acc:
        m = live_week.landmark_muscle(blocks[i].movement_key, movements, lib)
        n = warmup_sets.working_set_count(blocks[i].sets)
        lm = marks.get(m) or {}
        left = week[m] - taken[m] - n
        if lm and m != "abs" and left >= float(lm["MEV"]):
            cand = (left - float(lm["MEV"]), i)
            best = cand if best is None or cand > best else best
    if best is None:  # #5861 FIX8: none stays at MEV — the LOWEST-PRIORITY accessory goes (a non-priority muscle, the one
        prio = [str(p) for p in _settings(lib).get("priority_muscles") or []]  # nearest its MEV after the drop), never last-listed

        def harm(i: int) -> tuple[int, float, int]:
            m = live_week.landmark_muscle(blocks[i].movement_key, movements, lib)
            left = week[m] - taken[m] - warmup_sets.working_set_count(blocks[i].sets)
            return (int(m in prio), -(left - float((marks.get(m) or {}).get("MEV") or 0)), -i)

        best = (0.0, min(acc, key=harm))
    i = best[1]
    m = live_week.landmark_muscle(blocks[i].movement_key, movements, lib)
    taken[m] += warmup_sets.working_set_count(blocks[i].sets)
    return i


def precious(block: Any, movements: dict[str, Any], taken: Counter, rx: dict[str, Any] | None = None) -> bool:
    """#5861 FIX8: dropping `block` would take a PRIORITY muscle under its MEV for the week (`taken` already counts it off) —
    the time fit trims the anchors' back-offs (TIME_FIT) before it goes."""
    from training import block_model, live_week, selection_engine as se
    from training.live_rulings import ARMS_FLOOR

    lib = se.load_library_failsoft() or {}
    m = live_week.landmark_muscle(block.movement_key, movements, lib)
    prio = [str(p) for p in _settings(lib).get("priority_muscles") or []]
    mark = (rx or {}).get("live_session") or {}
    marks = (block_model.load_landmarks() or {}).get(m) or {}
    left = live_week.week_sets(movements, lib, rx)[m] - taken[m]
    if m in prio and left < float(marks.get("MEV") or 0):
        return True
    # a week without shoulders+arms (ruling 3): its arms floor — MV on a dip week, MEV on a short week — is a floor too
    arms = "shoulders_arms" in set(mark.get("week_skip") or ()) and m in ARMS_FLOOR["muscles"]["value"]
    return arms and left < float(marks.get("MV" if mark.get("week_mode") not in (None, "short") else "MEV") or 0)


# ── 3. order and the heavy pull ──────────────────────────────────────────────
def order_lower_volume(rx: dict[str, Any]) -> list[str]:
    """IN PLACE: on the lower-volume day the squat anchor comes before the hinge anchor (the RDL tires the erectors the squat
    needs). Returns the rationale lines."""
    ex = rx["exposures"]
    full = any(e.get("live_full_body") for e in ex)  # #5861 FIX8: a full-body day's guest squat and hinge too (seventh red team)
    if rx.get("session_role") != "lower_volume" and not full:
        return []
    hinge = next((i for i, e in enumerate(ex) if e.get("kind") == "anchor" and e.get("pattern") == "hinge"), None)
    squat = next((i for i, e in enumerate(ex) if e.get("kind") == "anchor" and e.get("pattern") == "squat"), None)
    if hinge is None or squat is None or squat < hinge:
        return []
    ex.insert(hinge, ex.pop(squat))
    day = "on lower volume" if rx.get("session_role") == "lower_volume" else "on a full-body day"
    return [f"order (live): the squat before the hinge {day} — the RDL tires the erectors the squat needs"]


def deadlift_shape(rx: dict[str, Any], lib: dict[str, Any] | None = None) -> list[str]:
    """IN PLACE, the setting `heavy_day_deadlift_shape`: `top_plus_backoff` serves the heavy-day hinge anchor as its top set +
    ONE back-off; `as_today` (default) leaves the top set + two back-offs. The squat + deadlift pairing itself stays (#5694)."""
    if _settings(lib).get("heavy_day_deadlift_shape") != "top_plus_backoff" or rx.get("session_role") != "lower_heavy":
        return []
    for e in rx["exposures"]:
        if e.get("kind") != "anchor" or e.get("pattern") != "hinge" or e.get("intensity") != "heavy":
            continue
        backs = [i for i, s in enumerate(e.get("sets") or []) if s.get("kind") == "back_off"]
        if len(backs) <= 1:
            return []
        for i in reversed(backs[1:]):
            e["sets"].pop(i)
        return ["deadlift (live option): top set + one back-off (heavy_day_deadlift_shape=top_plus_backoff); the pairing stays (#5694)"]
    return []


# ── 4. the aerobic gap ───────────────────────────────────────────────────────
def aerobic_gap(live: dict[str, Any], today_minutes: int = 0) -> int | None:
    """The week's aerobic minutes still missing: the guideline floor less the walking credit, less every block performed this
    week before today, less today's block. None when steps were not read (unknown is never a gap)."""
    from training import cardio_model, live_balance

    aer = live.get("aerobic") or {}
    if not aer or intensity_unknown(aer):  # FIX8 (ruling 12): steps of unknown intensity are never a manufactured deficit
        return None
    since, day = live_balance.week_start(str(live.get("target_date") or "")), str(live.get("target_date") or "")
    done = sum(
        int(r.get("duration_sec") or 0) // 60
        for rows in (live.get("by_machine") or {}).values()
        for r in rows or []
        if since <= str(r.get("date") or "")[:10] < day
    )
    return int(cardio_model.WEEKLY_MODERATE_MIN[0]) - int(aer.get("walking_min_per_wk") or 0) - done - int(today_minutes)


def walk_covers(kind: str, live: dict[str, Any]) -> list[str] | None:
    """Under the DEFAULT cap, an easy ride the walk prompt can replace: lines when the remaining gap is at most WALK_PROMPT
    max_minutes (no ride — the host morning's walk covers it), else None (the ride stays)."""
    from training import live_program

    shared = bool((live.get("settings") or {}).get("session_cap_includes_cardio"))
    gap = aerobic_gap(live)
    if shared or kind in live_program.HARD_KINDS or gap is None or gap > int(WALK_PROMPT["max_minutes"]["value"]):
        return None
    return [
        f"cardio (live): no easy ride — ~{max(gap, 0)} min short of the weekly aerobic floor: one optional walk covers it "
        f"(WALK_PROMPT, heuristic)"
    ]


def walk_prompt(live: dict[str, Any] | None, today_minutes: int = 0) -> list[str]:
    """On the conditioning host's morning (one prompt a week), when the week's gap after steps and every block is at least
    WALK_PROMPT min_minutes: one optional walk, its minutes capped at max_minutes, as a `walk (live):` line. Else []."""
    if not live or live.get("role") != live.get("host"):
        return []
    gap = aerobic_gap(live, today_minutes)
    if gap is None or gap < int(WALK_PROMPT["min_minutes"]["value"]):
        return []
    minutes = min(int(WALK_PROMPT["max_minutes"]["value"]), int(-(-gap // 5) * 5))
    return [
        f"walk (live): optional brisk walk {minutes} min today — the week is ~{gap} min short after recorded walking and blocks (WALK_PROMPT)"
    ]


WALK_LINE = "Optional today: brisk walk {m} min, any time."


def walk_note(ideal: Any, lines: list[str] | None) -> None:
    """IN PLACE: a `walk (live):` line becomes exercise 1's last own line (what he reads at 5 am). Idempotent; no-op otherwise."""
    import re

    hit = next((ln for ln in lines or [] if ln.startswith("walk (live):")), None)
    m = re.search(r"brisk walk (\d+) min", hit or "")
    exercises = getattr(ideal, "exercises", None) or []
    if not m or not exercises:
        return
    text = WALK_LINE.format(m=m.group(1))
    note = exercises[0].notes or ""
    if text not in note:
        exercises[0].notes = f"{note}\n{text}".strip()


# ── 5. the kettlebell slot under strain ──────────────────────────────────────
def kb_under_strain(rx: dict[str, Any]) -> list[str]:
    """IN PLACE, the setting `kb_slot_under_strain` `drop`: on a strained / overreached / deload-recommended day the kettlebell
    slot is dropped wherever it was placed. Default `as_today`: nothing changes. Returns the rationale lines."""
    from training.live_balance import KB_SLOT_KEY

    fat = rx.get("fatigue") or {}
    strained = fat.get("state") in ("strained", "overreached") or fat.get("action") == "deload_recommended"
    if _settings().get("kb_slot_under_strain") != "drop" or not strained:
        return []
    kb = [e for e in rx.get("exposures") or [] if e.get("slot") == KB_SLOT_KEY]
    if not kb:
        return []
    rx["exposures"] = [e for e in rx["exposures"] if e.get("slot") != KB_SLOT_KEY]
    return [f"dropped (live): the kettlebell slot — {fat.get('state') or fat.get('action')} day (kb_slot_under_strain=drop)"]


# ── 5. the 75-minute ceiling on a short week (#5861 FIX8) ───────────────────
TIME_FIT: dict[str, dict[str, Any]] = {
    "guest_min_sets": {
        "value": 1,
        "label": "heuristic",
        "basis": "#5861 FIX8 (seventh red team: 1-2 morning weeks drafted 78-83 min): a full-body day's GUEST anchors (the partner "
        "role's, `live_rules.full_body`) give their back-off sets first, down to the top set — the session's own anchors keep theirs",
    },
    "anchor_min_sets": {
        "value": 2,
        "label": "heuristic",
        "basis": "#5861 FIX8: when every accessory has gone and the routine still runs long, each anchor gives back-off sets down to "
        "its top set and one more (the deload shape's compound floor, `live_program.DELOAD_SHAPE` compound_sets) — never past the cap",
    },
}


def trim_anchor_backoffs(
    blocks: list[Any], rx: dict[str, Any], movements: dict[str, Any], cap: int, guests: bool, priority: bool = True
) -> list[str]:
    """IN PLACE (TIME_FIT, live only — `live_session.fit_routine`): back-off sets come off the anchors, last-listed first, until the
    routine fits `cap` — the full-body day's guest anchors (down to guest_min_sets) when `guests`, else every anchor (down to
    anchor_min_sets), a PRIORITY muscle's anchor last and only when `priority`. Returns the titles that gave sets."""
    from training import warmup_sets
    from training.session_shape import routine_minutes

    guest = {str(e.get("movement_key")) for e in rx.get("exposures") or [] if e.get("live_full_body")}
    floor = int(TIME_FIT["guest_min_sets" if guests else "anchor_min_sets"]["value"])
    pool = [b for b in blocks if str(b.rationale_tag or "").startswith("anchor:") and (str(b.movement_key) in guest if guests else True)]
    from training import live_week, selection_engine as se

    lib = se.load_library_failsoft() or {}
    prio = {str(m) for m in _settings(lib).get("priority_muscles") or []}
    # a priority muscle's anchor (the bench for the chest, the squat for the quadriceps) gives its back-offs last
    pool = [b for b in pool if priority and live_week.landmark_muscle(b.movement_key, movements, lib) in prio] + [
        b for b in pool if live_week.landmark_muscle(b.movement_key, movements, lib) not in prio
    ]
    gave: list[str] = []
    while routine_minutes(blocks, movements)["lifting_minutes"] > cap:
        pick = next((b for b in reversed(pool) if warmup_sets.working_set_count(b.sets) > floor), None)
        if pick is None:
            break
        last = max(i for i, s in enumerate(pick.sets) if not warmup_sets.is_warmup(s))
        pick.sets = list(pick.sets[:last]) + list(pick.sets[last + 1 :])
        title = str((movements.get(pick.movement_key) or {}).get("title") or pick.movement_key)
        gave.append(title)
    return gave
