"""live_week.py — the WEEK-shaped half of the live programming policy (#5861, second red team). LIVE only: every entry point
is reached from a live hook (`live_program.plan`, `live_program.guard_loads` / `annotate` / `cardio_fit`, `live_session.
for_live_draft` / `fit_exposures` / `fit_routine`), each of which returns before reading anything unless the draft ran the live
session fit (`live_session.MARK`, which exists only when the exercise library is `approved`). tests/test_no_live_change_5861_l6.py
pins the served proposed-mode drafts byte for byte.

WHY IT EXISTS. A second independent red team (2026-11-13) read the integrated engine's GENERATED weeks and the owner's real-data
run as a coach would and graded the programming C+. Each rule below answers one of its findings in the generated week:

  1. THE KETTLEBELL SLOT (`kb_slot`, `kb_note`, `kb_seed`). The owner-pinned KB deadlift logs under Hevy's "Sumo Deadlift"
     (template D20D7BBE, an owner-ruled stand-in — the template stays). The note never said "kettlebell", asked RPE 9-10 and
     "find the load": a reader at 5 am could load a barbell sumo pull as a second heavy hinge. Now the note names the
     implement, the effort is capped at RPE 7-8 (an entry drill into the swing), and the bell he swings loads it.
  2. CARDIO ROOM (`make_cardio_room`, `cardio_progress`). Under the shared 75-minute cap the engine never traded lifting for
     cardio: the week's only conditioning was a 13-minute stub while the delts sat over MAV. Now sets come off the muscles
     furthest over MAV first (then the largest surplus over MEV, never below it) until a CARDIO_ROOM minimum block fits; and
     the block's minutes follow `cardio_model.progress` week to week (duration, then frequency, then intensity).
  3. THE MEDICAL STOP LINE (`symptom_gate`, `review_line`). `owner_redlines.TRIPWIRES` `medical_stop_lines` is evaluated by
     `health.tripwire_readers.medical_stop_lines` (report-only). The draft now reads that row: tripped -> no hard cardio, a
     review line. Traced, not grepped: its palpitations and syncope arms are SELF-REPORT with no input on the platform
     (they read `unknown` until the check-in lane, #5819, supplies one); the measured arms (labs, the RHR rise) can trip.
  4. BEHIND SCHEDULE (`behind_schedule`, `keep_the_anchors`, `behind_schedule_roles`) — an OFF-by-default live option
     (`programming_settings.behind_schedule_week`, owner decision pending): when BEHIND_SCHEDULE missed_min of the last
     fortnight's planned sessions were missed, the week is offered as fewer, shorter sessions that keep the anchors (anchors
     + one accessory per major muscle, ~45 min) instead of trimming sets off five long ones.
  5. COVERAGE (`vertical_pull_fallback`, `novel_start`, `press_sets`). A garage week with a pull-up bar served no vertical
     pull; a movement new to him entered a deload at 4-6 reps; the week's only vertical press is one set (a charter decision —
     an off-by-default option here).

Every number here is a labelled PLATFORM HEURISTIC (practitioner consensus at best), owner-adjustable; none is validated.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

KB_SLOT: dict[str, dict[str, Any]] = {
    "effort": {
        "value": [7, 8],
        "label": HEURISTIC,
        "basis": "the KB deadlift is the entry drill into the swing (kb_entry, owner ruling 2026-11-11): this cap practises the "
        "hinge with one bell; it needs no grind, and the session already holds a loaded hinge",
    },
    "implement_line": {
        "value": "KB deadlift — logged as Sumo Deadlift.",
        "label": HEURISTIC,
        "basis": "Hevy has no Kettlebell Deadlift template, so the slot logs under 'Sumo Deadlift' (owner-ruled stand-in); the "
        "note names the implement so nobody loads a barbell sumo pull",
    },
}
CARDIO_ROOM: dict[str, dict[str, Any]] = {
    "min_block": {
        "value": 20,
        "label": HEURISTIC,
        "basis": "the shortest aerobic block worth its warm-up (practitioner consensus: 20-30 min continuous); under the shared "
        "75-minute cap lifting gives sets to protect it",
    },
    "min_sets": {"value": 2, "label": HEURISTIC, "basis": "an accessory trimmed for cardio room keeps at least two working sets"},
}
BEHIND_SCHEDULE: dict[str, dict[str, Any]] = {
    "missed_min": {
        "value": 5,
        "label": HEURISTIC,
        "basis": "5 or more of the fortnight's 10 planned sessions missed (fatigue_model adherence_low is under 60% done) — the "
        "point where a shorter week he can keep beats a long week he skips; owner decision pending",
    },
    "session_minutes": {"value": 45, "label": HEURISTIC, "basis": "a ~45-minute morning: anchors + one accessory per major muscle"},
    "sets": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "two hard sets per kept exposure (an anchor's top set and one more): the maintenance dose a short week keeps — "
        "strength is retained on far less volume than it was built with (practitioner consensus)",
    },
}
NOVEL_START: dict[str, dict[str, Any]] = {
    "reps": {
        "value": [6, 8],
        "label": HEURISTIC,
        "basis": "a movement swapped in that he has not done this block never starts in a 4-6 strength range (red team: a new "
        "machine hip thrust at 4-6 in a deload); 6-8 keeps the novel-again caps (owner ruling OD1: reps <= 8, RPE <= 7)",
    },
    "rpe": {"value": 7, "label": HEURISTIC, "basis": "the novel-again cap (OD1)"},
}
FAMILIAR_SWAP: dict[str, dict[str, Any]] = {
    "min_exposures": {
        "value": 3,
        "label": HEURISTIC,
        "basis": "#5861 FIX7 (sixth red team: a DB row for a barbell lifter capped at the novelty effort on its first sessions): a swap into the SAME "
        "movement pattern (barbell / dumbbell / machine / cable variants) for a lift logged 3+ times in the block is familiar — "
        "set 1 finds the load, then the sets work at target; the novelty cap is for a new movement pattern, not a new implement",
    },
}
VERTICAL_PULL_FALLBACK: tuple[str, ...] = (
    "pull_up_band",
    "chin_up_band",
    "pull_up_negative",
    "chin_up",
    "pull_up",
    "db_lat_pullovers",
    "pullover_dumbbell",
)
"""HEURISTIC fallback order (practitioner consensus) when a vertical-pull anchor has no available member (a garage with a bar
and no pulldown station): a band-assisted pull-up (when the library carries one — a data-lane key), a negative, the bodyweight
pull-up/chin-up (each only while its gates open: fail-closed), then the dumbbell pull-over (the lat through shoulder
extension, no gate). A key the library or the catalog does not carry is skipped."""
CARDIO_PROTOCOL = {
    "easy": "moderate_continuous",
    "incline_treadmill_walk": "moderate_continuous",
    "hills": "incline_resistance_progression",
    "tempo": "tempo_threshold",
    "intervals": "structured_intervals",
}
"""The menu kind -> the cardio model's protocol whose progression rule doses it (`cardio_model.progress`)."""
LANDMARK_OF = {
    "front_delts": "shoulders",
    "side_delts": "shoulders",
    "rear_delts": "shoulders",
    "obliques": "abs",
    "quadriceps_rectus_femoris": "quadriceps",
    "gastrocnemius": "calves",
    "soleus": "calves",
}
"""Library target -> the volume-landmark muscle (config/training_landmarks.json) it counts toward."""
MAJOR = ("chest", "back", "shoulders", "biceps", "triceps", "quadriceps", "hamstrings", "glutes", "calves")


def _settings() -> dict[str, Any]:
    from training import live_program, selection_engine as se

    return live_program.settings(se.load_library_failsoft())


# ── 1. the kettlebell slot ────────────────────────────────────────────────────
def kb_slot(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE: the KB deadlift (kb_entry's entry movement) carries KB_SLOT's effort band and the implement mark the note
    reads (`kb_note`). Returns the rationale lines."""
    from training import kb_entry

    lo, hi = KB_SLOT["effort"]["value"]
    lines = []
    for e in rx["exposures"]:
        if e.get("movement_key") != kb_entry.ENTRY:
            continue
        e["live_effort"] = min(int(hi), int(e.get("live_effort") or 99))
        e["live_effort_band"] = [int(lo), int(hi)]
        e["live_kb"] = True
        lines.append(
            f"kettlebell slot (live): {KB_SLOT['implement_line']['value'][:-1]}; RPE {lo}–{hi}, an entry drill (KB_SLOT, heuristic)"
        )
    return lines


def kb_note(note: str) -> str:
    """The implement line right under the effort line (never displacing a reason or the pick-load line). Idempotent."""
    from training import session_block as sb
    from training.live_balance import kb_note_line

    line = kb_note_line()  # #5861 FIX3: the custom template, when the owner sets one, needs no stand-in line
    if line in note.split("\n"):
        return note
    block, own = sb.split(note)
    lines = sb._own_lines(block, own)
    return sb._join(block, lines[:1] + [line] + lines[1:])


def kb_seed(
    blocks: list[Any], rx: dict[str, Any], history_index: Any, movements: dict[str, Any], target_date: str, rationale: list
) -> None:
    """IN PLACE, live only: a KB deadlift block with no load on its rows takes the bell — its own last KB deadlift, else the
    bell he last swung (one kettlebell, logged as the bell's weight) — so the note never says "find the load" while his
    history names the bell. Nothing on file: unchanged (the load is genuinely unknown)."""
    from training import kb_entry
    from training.exercise_history import previous_load

    if not any(e.get("live_kb") for e in rx.get("exposures") or []):
        return
    swing = str((movements.get(kb_entry.TARGET) or {}).get("hevy_template_id_hint") or "").upper() or None
    for b in blocks:
        work = [s for s in b.sets if str(getattr(s, "type", "") or "normal") != "warmup"]
        if b.movement_key != kb_entry.ENTRY or not work or any(getattr(s, "weight_kg", None) for s in work):
            continue
        custom = str(_settings().get("kb_deadlift_template_id") or "").strip() or None  # FIX3: his own KB template first
        # #5861 FIX6: a custom Hevy template id is a lower-case UUID and the history index keeps the id as logged — read it as
        # given (and upper-cased, for a built-in-style id), never only upper-cased
        mine = [previous_load(history_index, t, target_date) for t in dict.fromkeys((custom, (custom or "").upper())) if t]
        bell = next((b for b in mine if b), None) or previous_load(history_index, kb_entry.ENTRY_TEMPLATE_ID, target_date)
        bell = bell or previous_load(history_index, swing, target_date)
        if not bell or not bell.get("lb"):
            continue
        for s in work:
            s.weight_kg = round(float(bell["lb"]) * 0.45359237, 3)
        rationale.append(f"kettlebell slot (live): the bell on file ({bell['lb']:g} lb, {bell['date']}) — one kettlebell, no load to find")


# ── 2. cardio room and progression ────────────────────────────────────────────
def landmark_muscle(key: str | None, catalog: dict[str, Any], lib: dict[str, Any] | None) -> str:
    """The volume-landmark muscle a movement counts toward: the library's target (mapped by LANDMARK_OF), else the catalog's
    primary muscle. A catalog `other` (the kettlebell deadlift, the swing) reads the library's target — glutes, not nowhere."""
    from training import selection_engine as se

    lid = se.key_index(lib or {}, catalog)["to_lib"].get(str(key)) if lib else None
    target = ((((lib or {}).get("movements") or {}).get(lid) or {}).get("target") or {}) if lid else {}
    primary = target.get("primary") or (catalog.get(str(key)) or {}).get("primary_muscle")
    return LANDMARK_OF.get(str(primary), str(primary))


def week_sets(catalog: dict[str, Any], lib: dict[str, Any] | None, rx: dict[str, Any] | None = None) -> Counter:
    """The program week's planned sets per landmark muscle (primary 1.0, each secondary 0.5 — the fatigue model's convention),
    from the five role templates AFTER the week's allocation by priority (#5861 FIX3, `live_balance.allocation_plan`). `rx`
    (#5861 FIX6): the drafted session, whose live mark names the roles this week skips — a short week's count."""
    from training import live_balance

    skip = tuple(((rx or {}).get("live_session") or {}).get("week_skip") or ()) or None
    return live_balance.allocated_week(catalog, lib or {}, skip)


def _hard_blocked(rx: dict[str, Any]) -> bool:
    fat, mark = rx.get("fatigue") or {}, rx.get("live_session") or {}
    strain = set(fat.get("strain_signals") or [])
    return bool(
        mark.get("symptom_tripwire")
        or fat.get("action") == "deload_recommended"
        or fat.get("state") in ("strained", "overreached")
        or strain & {"readiness", "sleep", "cardio_load"}
    )


def cardio_reserve(rx: dict[str, Any]) -> int:
    """Minutes the lifting leaves for cardio under the shared cap (`session_cap_includes_cardio`): CARDIO_ROOM min_block on the
    conditioning host (shoulders+arms, or the short / dip week's host) when hard work is not blocked today; else 0 (lifting keeps
    every set; an easy block takes only the room lifting leaves, `live_balance.easy_gap` / `min_block`)."""
    if not _settings().get("session_cap_includes_cardio"):
        return 0
    on = (rx.get("live_session") or {}).get("conditioning_host") or "shoulders_arms"  # FIX3: the short week's host
    host = rx.get("session_role") == on and not _hard_blocked(rx)
    # FIX3: only the host buys room — with the conservative steps credit an uncovered week is common, and trimming every
    # morning's lifting for an easy block gutted the week (the walking gap is closed by walking first: live_balance.easy_gap)
    return int(CARDIO_ROOM["min_block"]["value"]) if host else 0


def make_cardio_room(blocks: list[Any], rx: dict[str, Any], movements: dict[str, Any], cap: int, shape: dict) -> dict:
    """IN PLACE, live only (`live_session.fit_routine`): under the shared cap, take working sets off accessories until the routine
    as written leaves `cardio_reserve` minutes — the muscle furthest over its MAV first, then the largest surplus over MEV
    (never below MEV for the week, never below CARDIO_ROOM min_sets, never an anchor, a carry or a trunk drill). Returns the
    re-measured shape (or `shape` untouched)."""
    from training import cardio_menu

    reserve = cardio_reserve(rx)
    full = max(reserve, int(cardio_menu.cardio_cap_minutes() or reserve))
    if not reserve or shape.get("lifting_minutes") is None or shape["lifting_minutes"] <= cap - full:
        return shape
    from training import block_model, program_structure, selection_engine as se, warmup_sets
    from training.session_shape import routine_minutes

    lib = se.load_library_failsoft() or {}
    week, marks = week_sets(movements, lib, rx), (block_model.load_landmarks() or {})
    over_mav_only = _settings().get("cardio_room_takes") == "over_mav_only"  # #5861 FIX6, owner ruling 1
    taken: Counter = Counter()
    before = shape["lifting_minutes"]
    paired = _pair_antagonists(blocks, rx) if shape["lifting_minutes"] > cap - reserve else []  # charter: pair before cutting
    # #5861 FIX3 ran a second pass to ONE set here; FIX4 (fourth red team: "drop, don't shave") stops at two sets and lets
    # `_drop_for_room` take whole isolation accessories instead — the room still comes from isolation, never the intervals
    for floor in (int(CARDIO_ROOM["min_sets"]["value"]),):  # #5861 FIX4: never to one set — whole accessories go next
        while True:
            now = routine_minutes(blocks, movements)["lifting_minutes"]
            # sets over a muscle's MAV buy the WHOLE block (they add little); a surplus over MEV buys only the minimum block
            tiers = (0, 1) if now > cap - reserve else ((0,) if now > cap - full and floor > 1 else ())
            tiers = tuple(t for t in tiers if t == 0) if over_mav_only else tiers  # FIX6 ruling 1: never sets a muscle needs
            if not tiers or not _trim_one(blocks, movements, lib, (week, marks, taken, floor, _fixed(rx)), tiers):
                break
    dropped = [] if over_mav_only else _drop_for_room(blocks, rx, movements, lib, (week, marks, taken), cap - reserve)  # FIX3
    if not taken and not paired:
        return shape
    new = program_structure.enforce_session_shape(blocks, movements) | {
        "working_sets": sum(warmup_sets.working_set_count(b.sets) for b in blocks)
    }
    how = [f"supersets {', '.join(paired)}"] if paired else []
    how += [", ".join(f"{n} {m}" for m, n in sorted(taken.items())) + " set(s) off (over MAV first)"] if taken else []
    how += [f"dropped {', '.join(dropped)}"] if dropped else []
    (rx.get("live_session") or {}).setdefault("lines", []).append(
        f"cardio room (live): ~{before} -> ~{new['lifting_minutes']} min lifting — {'; '.join(how)} — room for the aerobic block "
        f"inside the shared {cap}-min cap (CARDIO_ROOM, heuristic; the block's minutes are its own line)"
    )
    return new


def _drop_for_room(blocks: list[Any], rx: dict[str, Any], movements: dict[str, Any], lib: dict[str, Any], env: tuple, limit: float) -> list:
    """IN PLACE (#5861 FIX3): when set trims could not make the minimum aerobic block fit, whole isolation accessories go —
    the one whose muscle the week holds furthest over its MEV first (the delt surplus before anything else), never an
    anchor, a carry, a pinned slot or a live addition, never a muscle the week would leave under its MEV. Returns titles."""
    from training.session_shape import routine_minutes

    week, marks, taken = env
    out = []
    priority = {str(m) for m in _settings().get("priority_muscles") or []}
    while routine_minutes(blocks, movements)["lifting_minutes"] > limit:
        cands, late = [], []
        for i, b in enumerate(blocks):
            tag = str(b.rationale_tag or "")
            if not tag.startswith("accessory:") or tag.endswith(":carry") or b.movement_key in _fixed(rx):
                continue
            m = landmark_muscle(b.movement_key, movements, lib)
            n = sum(1 for st in b.sets if str(getattr(st, "type", "") or "normal") != "warmup")
            lm = marks.get(m) or {}
            if lm and m != "abs" and week[m] - taken[m] - n >= float(lm["MEV"]):
                cands.append((week[m] - taken[m] - float(lm["MEV"]), i, b, m, n))
            elif lm and m != "abs" and m not in priority:
                late.append((week[m] - taken[m] - float(lm["MEV"]), i, b, m, n))
        # #5861 FIX4 (drop, don't shave): no one-set pass any more, so as the LAST resort before the minimum aerobic block is cut a
        # NON-priority isolation accessory may go even under its MEV (the shared cap is the owner's choice of conditioning)
        cands = cands or late
        if not cands:
            break
        _s, i, b, m, n = max(cands, key=lambda c: c[:2])
        blocks.pop(i)
        taken[m] += n
        out.append((movements.get(b.movement_key) or {}).get("title") or b.movement_key)
    return out


def _fixed(rx: dict[str, Any]) -> set[str]:
    """Movements a set trim never touches: an owner-pinned slot (the carry, the kettlebell slot) and a live addition (the trunk
    floor, the short week's carry) — each is there for a purpose its set count carries."""
    from training import selection_live

    role = str(rx.get("session_role") or "")
    pinned = {sid.split(".", 1)[1] for sid in selection_live.SLOT_OBJECTIVES if sid.startswith(f"{role}.")}
    return {str(e.get("movement_key")) for e in rx.get("exposures") or [] if e.get("slot") in pinned or e.get("live_added")}


def _trim_one(blocks: list[Any], movements: dict[str, Any], lib: dict[str, Any], env: tuple, tiers: tuple) -> bool:
    """Take ONE working set off the accessory whose landmark muscle sits furthest over its MAV (tier 0), else furthest over its
    MEV (tier 1, never taking the week under MEV) — `tiers` says which may give; never an anchor, a carry, a trunk drill, a
    pinned slot or a live addition (`_fixed`), or an exposure at `floor` sets. Last-listed first on a tie. Returns False when
    nothing may give."""
    week, marks, taken, floor, fixed = env
    cands = []
    for i, b in enumerate(blocks):
        tag = str(b.rationale_tag or "")
        work = [s for s in b.sets if str(getattr(s, "type", "") or "normal") != "warmup"]
        if not tag.startswith("accessory:") or tag.endswith(":carry") or len(work) <= floor or b.movement_key in fixed:
            continue
        m = landmark_muscle(b.movement_key, movements, lib)
        lm, n = marks.get(m) or {}, week[m] - taken[m]
        if not lm or m == "abs":
            continue
        if n > float(lm["MAV"]):
            cands.append((0, -(n - float(lm["MAV"])), -i, b, m))
        elif n - 1 >= float(lm["MEV"]):
            cands.append((1, -(n - float(lm["MEV"])), -i, b, m))
    cands = [c for c in cands if c[0] in tiers]
    if not cands:
        return False
    _t, _x, _i, b, m = min(cands, key=lambda c: c[:3])
    idx = [j for j, s in enumerate(b.sets) if str(getattr(s, "type", "") or "normal") != "warmup"]
    b.sets.pop(idx[-1])
    taken[m] += 1
    return True


def trim_sets_for_time(blocks: list[Any], rx: dict[str, Any], movements: dict[str, Any], cap: int) -> Counter:
    """IN PLACE, live only (`live_session.fit_routine`, before any accessory is DROPPED): sets before exercises — working sets
    come off the accessories whose muscles sit over MAV, then over MEV (never taking the week under MEV, never below CARDIO_ROOM
    min_sets), until the routine fits `cap`. Returns the sets taken per muscle (empty when nothing could give)."""
    from training import block_model, selection_engine as se
    from training.session_shape import routine_minutes

    lib = se.load_library_failsoft() or {}
    taken: Counter = Counter()
    week, marks = week_sets(movements, lib, rx), block_model.load_landmarks() or {}
    # every accessory down to CARDIO_ROOM min_sets; #5861 FIX4 retired the second pass to ONE set (one-set accessories and
    # superset halves are noise) — `fit_routine` then drops whole accessories, the largest surplus over MEV first
    for floor in (int(CARDIO_ROOM["min_sets"]["value"]),):  # #5861 FIX4: drop, don't shave — then whole accessories (fit_routine)
        env = (week, marks, taken, floor, _fixed(rx))
        while routine_minutes(blocks, movements)["lifting_minutes"] > cap and _trim_one(blocks, movements, lib, env, (0, 1)):
            pass
    return taken


def _pair_antagonists(blocks: list[Any], rx: dict[str, Any]) -> list[str]:
    """IN PLACE: the charter's antagonist pairs (`split.supersets.pairs`, by template slot) that are not yet a superset share
    one — the first member's rest goes, the second sits right after it (as `session_shape.pair_supersets` does on a
    prescription). Returns the pair names."""
    from training.training_charter import charter_value

    slot_of = {e.get("movement_key"): e.get("slot") or e.get("movement_key") for e in rx.get("exposures") or []}
    used = [int(getattr(b, "superset_id", None) or 0) for b in blocks]
    sid, names = max(used + [0]), []
    for pair in charter_value("split.supersets.pairs") or []:
        free = [b for b in blocks if str(b.rationale_tag or "").startswith("accessory:") and getattr(b, "superset_id", None) is None]
        a = next((b for b in free if slot_of.get(b.movement_key) in pair["first"]), None)
        b2 = next((b for b in free if slot_of.get(b.movement_key) in pair["second"]), None)
        if a is None or b2 is None:
            continue
        sid += 1
        blocks.remove(b2)
        blocks.insert(blocks.index(a) + 1, b2)
        b2.rest_seconds = max(int(a.rest_seconds or 0), int(b2.rest_seconds or 0))
        a.rest_seconds, a.superset_id, b2.superset_id = 0, sid, sid
        names.append(str(pair["name"]))
    return names


def _performed(kind: str, live: dict[str, Any]) -> list[dict[str, Any]]:
    """His performed blocks of `kind` before the draft day, most recent first: {date, minutes, rpe}."""
    from training import cardio_menu

    out = []
    for key, sessions in (live.get("by_machine") or {}).items():
        for s in sessions or []:
            d = str(s.get("date") or "")[:10]
            if not d or d >= str(live.get("target_date") or "9999"):
                continue
            k = cardio_menu.kind_of_performed(key, s.get("note"), s.get("served_kind"), s.get("served_swap_kind"), s.get("set_rpe"))
            if k != kind:
                continue
            rpe = s.get("set_rpe") if s.get("set_rpe") is not None else cardio_menu.logged_rpe(s.get("note"))
            out.append({"date": d, "minutes": int(s.get("duration_sec") or 0) // 60, "rpe": rpe})
    return sorted(out, key=lambda r: r["date"], reverse=True)


def cardio_progress(kind: str, live: dict[str, Any], minutes: int) -> tuple[int, list[str]]:
    """The block's minutes this week by `cardio_model.progress` over his performed blocks of the same kind (the protocol's
    rule: symptoms, recovery and logged effort first; then duration, then frequency, then intensity). Only a DURATION step
    or a step back moves the minutes (within CARDIO_ROOM min_block and the menu's cap); a frequency or intensity step is
    named for the owner — the charter's placement owns frequency. No performed block of this kind: the menu's dose."""
    from common.pacific_time import shift_day_key

    from training import cardio_menu, cardio_model

    name = CARDIO_PROTOCOL.get(kind)
    rows = _performed(kind, live) if name else []
    if not rows or not rows[0]["minutes"]:
        return minutes, []
    last = rows[0]
    held = next((i for i, r in enumerate(rows) if abs(r["minutes"] - last["minutes"]) > 1), len(rows))
    week_ago = shift_day_key(str(live.get("target_date")), -7)
    band = cardio_menu.wire_band(kind) or (0, 99)
    rpe = last["rpe"]
    state = {
        "minutes": last["minutes"],
        "sessions_per_wk": sum(1 for r in rows if r["date"] >= week_ago),
        "held_sessions": held,
        "rpe": None if rpe is None else ("over" if float(rpe) > band[1] else ("under" if float(rpe) < band[0] else "in")),
        "recovery": "poor" if live.get("state") in ("strained", "overreached") else "ok",
        "symptoms": bool(live.get("tripwire")),
    }
    p = cardio_model.progress(name, state)
    out = minutes
    if p["action"] in ("add_duration", "step_back"):
        out = max(int(CARDIO_ROOM["min_block"]["value"]), min(int(p["minutes"]), int(minutes)))
    return out, [
        f"cardio progression (live): {name} — last {last['minutes']} min on {last['date']} -> {out} min: {p['action']} "
        f"({p['reason']}; cardio_model.progress, heuristic)"
    ]


# ── 3. the medical stop line ─────────────────────────────────────────────────
def symptom_gate(row: Any, workouts: Any = None, as_of: Any = None) -> dict[str, Any] | None:
    """The `medical_stop_lines` tripwire row (`health.tripwire_readers.medical_stop_lines`) -> {tripwire, lines} when TRIPPED,
    else None. `unknown` (the self-report palpitations / syncope arms with no input) is never read as tripped or as clear.
    #5861 FIX5: those two arms' self-report — a symptom he logged on a Hevy note in the last fortnight (`live_rules.self_report`,
    over `workouts` before `as_of`) — trips the draft's gate too."""
    if not isinstance(row, dict) or row.get("state") != "tripped":
        from training.live_rules import self_report

        return self_report(workouts, as_of)
    arms = (row.get("observed") or {}).get("arms") or {}
    hit = sorted(k for k, a in arms.items() if isinstance(a, dict) and a.get("state") == "tripped")
    return {"tripwire": str(row.get("id") or "medical_stop_lines"), "lines": hit or ["a stop line"]}


def review_line(trip: dict[str, Any]) -> str:
    return (
        f"review (live): {trip['tripwire']} tripped ({', '.join(trip['lines'])}) — no hard cardio until it is reviewed "
        "(owner_redlines medical_stop_lines; the clinical action is his clinician's, not the engine's)"
    )


# ── 4. behind schedule ───────────────────────────────────────────────────────
def behind_schedule(workouts: Any, as_of: str, lib: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any] | None:
    """The live option `programming_settings.behind_schedule_week` (default False): {missed, planned, performed} when at least
    BEHIND_SCHEDULE missed_min of the fortnight's planned sessions were missed over a fully covered window; else None.
    `force` (#5861 FIX3, `live_balance.adherence_response`): the same reading for the default dip response."""
    from training import fatigue_model, live_program, program_structure as ps, selection_engine as se

    if not force and not live_program.settings(lib if lib is not None else se.load_library_failsoft()).get("behind_schedule_week"):
        return None
    adh = fatigue_model.adherence(workouts, as_of=as_of, planned_per_week=len(ps.SPLIT_ROLES))
    if adh.get("state") == "unknown" or not adh.get("window_covered"):
        return None
    missed = int(adh["planned"]) - int(adh["performed"])
    if missed < int(BEHIND_SCHEDULE["missed_min"]["value"]):
        return None
    return {"missed": missed, "planned": adh["planned"], "performed": adh["performed"]}


def behind_schedule_roles(roles: list[str], behind: dict[str, Any] | None) -> tuple[list[str], str | None]:
    """The behind-schedule week's sessions: four (shoulders+arms skipped — L5's short-week rule, so both lower days and both
    upper days keep their anchors; its carry and trunk floor move to the last session). The cron's session sequence still
    credits by position — wiring this into `session_sequence` is the owner's call, as for the short week."""
    if not behind:
        return roles, None
    from training.live_program import SHORT_WEEK_SKIP

    kept = [r for r in roles if r != SHORT_WEEK_SKIP]
    if behind.get("mode") == "dip":  # #5861 FIX3: the default response to a dip (live_balance.lighter_week)
        return kept, (
            f"adherence dip (live, adherence_response=short_week): {behind['missed']} of the last {behind['planned']} planned "
            f"sessions missed — a {len(kept)}-session week, anchors whole, accessories at 2 sets, ~60 min each"
        )
    return kept, (
        f"behind schedule (live option, heuristic): {behind['missed']} of the last {behind['planned']} planned sessions missed — "
        f"a {len(kept)}-session 'keep the anchors' week, ~{BEHIND_SCHEDULE['session_minutes']['value']} min each"
    )


def keep_the_anchors(rx: dict[str, Any], ctx: dict[str, Any], behind: dict[str, Any] | None) -> list[str]:
    """IN PLACE: a behind-schedule session keeps every anchor, every owner-pinned slot (the carry, the kettlebell slot) and ONE
    accessory per major muscle no anchor of the session already trains (the first listed); the rest wait. The routine is
    then fitted to BEHIND_SCHEDULE session_minutes (`live_session.fit_routine`). Returns the rationale lines."""
    if not behind or behind.get("mode") == "dip":
        return []
    from training import selection_live

    pinned = {sid.split(".", 1)[1] for sid in selection_live.SLOT_OBJECTIVES if sid.startswith(f"{rx.get('session_role')}.")}
    lib = ctx["lib"]
    covered = {landmark_muscle(e.get("movement_key"), ctx["catalog"], lib) for e in rx["exposures"] if e.get("kind") == "anchor"}
    keep, gone = [], []
    n = int(BEHIND_SCHEDULE["sets"]["value"])
    for e in rx["exposures"]:
        m = landmark_muscle(e.get("movement_key"), ctx["catalog"], lib)
        if e.get("kind") == "anchor" or e.get("slot") in pinned or e.get("intensity") == "carry":
            keep.append(e)
        elif m in MAJOR and m not in covered:
            covered.add(m)
            keep.append(e)
        else:
            gone.append((ctx["catalog"].get(e.get("movement_key")) or {}).get("title") or e.get("movement_key"))
    for e in keep:  # the anchors keep their top set and one more; an accessory two hard sets
        sets = e.get("sets") or []
        while len(sets) > n:
            idx = [i for i, st in enumerate(sets) if st.get("kind") != "top"]
            if not idx:
                break
            sets.pop(idx[-1])
    rx["exposures"] = keep
    ctx["behind"] = behind  # the trunk floor waits too (live_program.trunk_floor)
    rx.setdefault("live_session_cap", int(BEHIND_SCHEDULE["session_minutes"]["value"]))
    return [
        f"behind schedule (live option): {behind['missed']} of {behind['planned']} planned sessions missed in 14 days — anchors + one "
        f"accessory per major muscle, ~{BEHIND_SCHEDULE['session_minutes']['value']} min"
        + (f"; waiting: {', '.join(map(str, gone))}" if gone else "")
    ]


# ── 5. coverage ──────────────────────────────────────────────────────────────
def vertical_pull_fallback(e: dict[str, Any], ctx: dict[str, Any], taken: set[str]) -> str | None:
    """A live-only fallback for a VERTICAL-PULL anchor no member of which the gym can serve (`live_session.fit_exposures`):
    the first key of VERTICAL_PULL_FALLBACK the catalog can write, the gym has, no locked gate holds (fail-closed) and the
    skill ceiling allows. None when the exposure is not a vertical pull or nothing is servable."""
    from training import live_session as ls

    if e.get("kind") != "anchor" or e.get("pattern") != "vertical_pull":
        return None
    for key in VERTICAL_PULL_FALLBACK:
        c = ctx["catalog"].get(key)
        if not c or key in taken or int(c.get("skill_tier", 99)) > ctx["ceiling"]:
            continue
        if ls._blocked(key, ctx, False) is None and ls._servable(key, ctx) is None:
            return key
    return None


def novel_start(rx: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> list[str]:
    """IN PLACE: an exposure SWAPPED in (equipment, pain, discomfort, stacking) whose movement has no exposure in the block's
    record starts at NOVEL_START reps and RPE — never a 4-6 strength range on a movement new to him. Returns the lines."""
    seen = {str(x.get("template_id") or "").upper() for w in workouts or [] for x in w.get("exercises") or []}
    lo, hi = NOVEL_START["reps"]["value"]
    lines = []
    for e in rx["exposures"]:
        if not e.get("live_swap") or e.get("intensity") == "carry":
            continue
        tid = str((ctx["catalog"].get(e.get("movement_key")) or {}).get("hevy_template_id_hint") or "").upper()
        reps = [s.get("reps") for s in e.get("sets") or [] if s.get("reps")]
        if not reps:
            continue
        if familiar_swap(e, ctx, workouts):  # #5861 FIX7: a like-for-like swap for a lifter who logs the pattern is not novel
            e["live_familiar"] = True  # (seen this block or not: a layoff cap on it is lifted too, `familiar_note`)
            if tid and tid in seen:
                continue
            title = (ctx["catalog"].get(e.get("movement_key")) or {}).get("title") or e.get("movement_key")
            lines.append(
                f"familiar swap (live): {title} — the same pattern as the {FAMILIAR_SWAP['min_exposures']['value']}+-exposure lift it "
                "replaces: set 1 finds the load, then work at target (FAMILIAR_SWAP, heuristic)"
            )
            continue
        if tid and tid in seen:
            continue
        low = int(reps[0][0]) < int(lo)  # #5861 FIX5: the RPE cap reaches every new movement, isolation too; reps move only below 6
        for s in e["sets"] if low else []:
            if s.get("reps"):
                s["reps"] = [int(lo), int(hi)]
        e["live_effort"] = min(int(NOVEL_START["rpe"]["value"]), int(e.get("live_effort") or 99))
        title = (ctx["catalog"].get(e.get("movement_key")) or {}).get("title") or e.get("movement_key")
        where = f"starts at {lo}-{hi} reps, RPE <= 7" if low else "starts at RPE <= 7"
        lines.append(f"new movement (live): {title} {where} — new to him this block (NOVEL_START, heuristic)")
    return lines


def familiar_swap(e: dict[str, Any], ctx: dict[str, Any], workouts: Any) -> bool:
    """FAMILIAR_SWAP: the swapped-in movement shares the replaced one's library pattern, and the replaced one has
    min_exposures+ logged exposures in the record."""
    lib_of = lambda k: ((ctx["lib"].get("movements") or {}).get(ctx["idx"]["to_lib"].get(str(k)) or "") or {})  # noqa: E731
    src = (e.get("live_swap") or {}).get("from")
    old, new = lib_of(src), lib_of(e.get("movement_key"))
    if not old or not new or not old.get("pattern") or old.get("pattern") != new.get("pattern"):
        return False
    tid = str(old.get("template_id") or "").upper()
    n = sum(1 for w in workouts or [] for x in w.get("exercises") or [] if str(x.get("template_id") or "").upper() == tid)
    return n >= int(FAMILIAR_SWAP["min_exposures"]["value"])


FAMILIAR_LINE = "Familiar swap: set 1 finds the load."


def familiar_note(note: str, e: dict[str, Any]) -> str:
    """A FAMILIAR_SWAP exposure's note: no layoff / novelty cap — line 1 at the exposure's working effort (RPE 8–9, or its own
    stricter cap: a pain variant's 8 stays) and the layoff line replaced by FAMILIAR_LINE."""
    from training import hevy_note_grammar as g, session_block as sb

    if not e.get("live_familiar"):
        return note
    block, own = sb.split(note or "")
    lines = sb._own_lines(block, own)
    cap = int(e.get("live_effort") or 9)
    want = g.effort_line((8, 9) if cap >= 9 else cap)
    if lines and g.EFFORT_RE.match(lines[0]):
        top = max(float(x) for x in __import__("re").findall(r"\d+(?:\.\d+)?", lines[0].split(",")[0]))
        lines[0] = want if top < min(cap, 8) else lines[0]
    lines = [FAMILIAR_LINE if g.LAYOFF_RE.match(ln) or g.PICK_LOAD_OPEN_TAIL in ln else ln for ln in lines]
    return sb._join(block, list(dict.fromkeys(lines)))


def press_sets(rx: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """IN PLACE, the live option `programming_settings.press_sets` (default 1 = the charter's `overhead_press_per_wk`, #5162):
    above 1, the shoulders+arms overhead-press anchor gets that many working sets. #5861 FIX4: the week's allocation counts them
    (`live_balance._template_rows`), so the trade lands on the week's delt isolation there. Returns the rationale lines."""
    from training import selection_engine as se
    from training.live_balance import _press_sets  # #5861 FIX6: the ruled default (3) when the library omits the key

    want = _press_sets(se.load_library_failsoft())
    if want <= 1 or rx.get("session_role") != "shoulders_arms":
        return []
    press = next((e for e in rx["exposures"] if e.get("kind") == "anchor" and e.get("pattern") == "overhead_press"), None)
    if press is None:
        return []
    added = 0
    while len(press["sets"]) < want:  # #5861 FIX4: the week's allocation counted these sets (live_balance._template_rows) and took
        press["sets"].append(dict(press["sets"][-1]))  # them from the delt isolation already — no second donor here
        added += 1
    return (
        [
            f"press (live option): overhead press {len(press['sets'])} sets, traded from the delt isolation by the week's allocation (press_sets)"
        ]
        if added
        else []
    )
