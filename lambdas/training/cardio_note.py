"""cardio_note.py — the cardio block's note in Hevy, prescription first (#5048), dosed from the menu (#5076).

WHY THIS EXISTS

The live 2026-10-18 cycling note (routine `014e1142…`, read from DynamoDB on 2026-10-18) was:

    Last: level 11, 10.60 mi in 45:30 (14.0 mph) — 16 Oct ["Level 11 flat"] · his calibration: L9-10 is
    easy (25 Jun) — Recumbent, 20 min, talk test — full sentences throughout. No HR target. Not the
    treadmill: 168-min walk yesterday, week already 1.7 h over the ramp. Builds aerobic base without
    loading feet. Optional if in AF.

History, calibration, modality, duration, intensity gate, a negative, a rationale and a conditional,
with no imperative. The owner: "I have no clue what you want me to do, do you want me to do level 11
flat? should I do intervals or climb a hill? Should I be pushing harder if I'm green recovery?"

THE NOTE (two lines at most)

  line 1 — THE RULE LINE, one fixed grammar (`LINE1_RE`):
      <machine> · <minutes> min · <dose> <flat | intervals a×b | hill | walk> · <clock rule> · <effort words>
      dose = "level <N> at <S> mph" (a bike; " at <S> mph" left out when no ride at that level is on
      record, "level <N> " left out only when no level is known at all) or "incline <I>% at <S> mph" /
      "incline <I>–<J>% at <S> mph" (the treadmill walk / its hill);
      e.g. "Recumbent bike · 30 min · level 11 at 14.6 mph flat · level 11 for 30 · check in every 10 min · RPE 4–5,
            full sentences"
           "Recumbent bike · 30 min · level 10 at 12.3 mph hill · level 10 for 6 · then +1 level every 2 min from 6 to 14
            · then -1 level every 2 min from 14 to 22 · then 10 from 22 to 30 · RPE 5–7, short phrases on the climbs"
      The CLOCK RULE (#5374) is the block as he runs it from his wrist: an iPad covers the console, so nothing is set
      up on the machine, and the watch does not alert, so every change is a minute he reads off the watch clock.
      Its grammar — HOLD / ALT / RAMP / SPRINT clauses joined by " · then ", times in session-clock minutes — is
      `training.wrist_clock`'s (`RULE_RE`, defined in that module's docstring and embedded in `LINE1_RE` as the
      `clock` group). Every change point sits on the owner's 2/5/10-minute grid, every line asks him to remember at
      most `wrist_clock.MAX_NUMBERS` machine numbers (owner amendment 2026-10-26), and the clock adds up to the
      block's minutes exactly — the block's sets (and so `cardio_menu.movement_minutes`) are never touched.
      The shapes, each dosed from the menu (`clock_shape`):
        easy / the incline walk  one level the whole block, a talk-test check-in every `EASY_CHECK_IN_MINUTES`;
        tempo                    one level held (the menu's tempo dose), the effort words name the talk test;
        hills                    the base, then +step every `cardio_menu.HILL_STEP_MINUTES` up `HILL_CLIMB_STEPS`
                                 steps (the treadmill: up to the top of the menu's incline band), the same back
                                 down, the base to the end;
        intervals                the base, then the menu's `efforts` × work-minutes at `INTERVAL_LEVEL_STEP` above it
                                 every work+easy minutes, the base to the end.
      The effort words are the menu's RPE band and talk test (`cardio_menu.effort_words`) — never an HR
      number while the 2026-10-10 constraint holds its HR half. No line says "program" or "preset": nothing is
      set up on the machine;
  line 2, the recovery answer, the dose's reason when it stepped (same RPE at a higher level / incline),
  then at most one sentence of why.

WHAT IS CHOSEN WHERE

The KIND (easy / tempo / hills / intervals / the incline walk) and the MACHINE are the menu's
weekly placement (`training.cardio_menu.choose_kind`, read from `charter_value('cardio_menu')`), and
the caller passes the kind in. The bike level is still DERIVED from the last ride's level and his
calibration note (`cardio_progression.cardio_facts` / `level_verdict`) and rises one level only on a
`raise` verdict; the treadmill dose is `cardio_menu.treadmill_dose` over his treadmill history.

The 2026-10-10 standing constraint's intensity half ("no push") is retired from 2026-10-18
(`standing_constraints.intensity_gate_active`, owner ruling 7); before that day it still holds a
block easy, so a replay of an older day composes what that day composed. Its HR half (no HR target)
stays. Pure: no I/O, no clock.
"""

from __future__ import annotations

import re
from typing import Any

from training import wrist_clock

CARDIO_NOTE_VERSION = "cardio-note@3.0.0"  # 3.0.0 = the clock rule on line 1 (#5374)

# movement_key -> the machine as line 1 names it. `cycling` is the program's knee-sparing recumbent
# (`recent_aerobic.cardio_pick`: "cycling (recumbent)").
MACHINES: dict[str, str] = {
    "cycling": "Recumbent bike",
    "treadmill": "Treadmill",
    "walking": "Walk",
    "elliptical": "Elliptical",
    "rowing_machine": "Rower",
    "air_bike": "Air bike",
}
BIKES = ("cycling", "air_bike")
WALKS = ("treadmill",)

# ── the thresholds this note acts on, each labelled (ADR-105) ─────────────────────────
# PLATFORM-CHOSEN, not his variance: the step he may add on a green day when the ride feels easy.
GREEN_ADD_MINUTES = 5
# PLATFORM-CHOSEN: each interval effort sits this many levels above the base, with the menu's easy block
# at the base level between (the effort count and the minutes are the menu's, `cardio_menu.interval_set`).
INTERVAL_LEVEL_STEP = 2
# PLATFORM-CHOSEN (#5374): a bike / rower / elliptical hill climbs this many steps of `HILL_LEVEL_STEP` levels and comes
# back down (the treadmill's climb is the menu's own incline band instead).
HILL_CLIMB_STEPS = 4
HILL_LEVEL_STEP = 1
# PLATFORM-CHOSEN (#5374): an easy block's talk-test check-in, on the owner's 10-minute grid.
EASY_CHECK_IN_MINUTES = 10
LABELS = {
    "green_add_minutes": "platform-chosen",
    "interval_level_step": "platform-chosen",
    "hill_climb_steps": "platform-chosen",
    "hill_level_step": "platform-chosen",
    "easy_check_in_minutes": "platform-chosen",
}

SHAPES = ("flat", "intervals", "hill", "walk")
# kind -> line 1's shape word
KIND_SHAPE = {"easy": "flat", "tempo": "flat", "intervals": "intervals", "hills": "hill", "incline_treadmill_walk": "walk"}

# Line 1. The shape alternation is the grammar's own, so a fifth shape cannot slip in unnamed. The `clock` group is
# `wrist_clock.RULE_PATTERN` (#5374); it is optional so a note composed before the clock rule still reads as composed.
LINE1_RE = re.compile(
    r"^(?P<machine>[A-Z][A-Za-z ]+) · (?P<minutes>\d+) min · "
    r"(?:level (?P<level>\d+)(?: at (?P<mph>\d+(?:\.\d)?) mph)? "
    r"|incline (?P<incline>\d+(?:\.\d)?)(?:–(?P<incline_top>\d+(?:\.\d)?))?% at (?P<walk_mph>\d+(?:\.\d)?) mph )?"
    r"(?P<shape>flat|intervals \d+×\d+|hill|walk) · "
    rf"(?:(?P<clock>{wrist_clock.RULE_PATTERN}) · )?"
    r"(?P<effort>\S.*)$"
)

_INTERVAL_WORD = re.compile(r"\binterval|\b\d+\s*[x×]\s*\d+\b", re.IGNORECASE)
_HILL_WORD = re.compile(r"\bhill|\bclimb", re.IGNORECASE)


def machine_for(movement_key: str) -> str | None:
    """Line 1's machine for a cardio movement, or None when the key is not a cardio machine."""
    return MACHINES.get(str(movement_key or ""))


def is_composed(note: str | None) -> bool:
    """True when the note's first line is already this module's line 1 (re-drafting never stacks)."""
    first = (note or "").strip().split("\n", 1)[0]
    return bool(LINE1_RE.match(first))


def composed_kind(note: str | None) -> str | None:
    """The menu kind a composed note (this module's line 1) already carries, or None when it is not one.
    A re-draft keeps it, so recomposing never re-places a block it already placed."""
    m = LINE1_RE.match((note or "").strip().split("\n", 1)[0])
    if not m:
        return None
    shape = m.group("shape")
    if shape == "walk":
        return "incline_treadmill_walk"
    if shape.startswith("intervals"):
        return "intervals"
    if shape == "hill":
        return "hills"
    return "tempo" if re.match(r"(?:hard flat \d+|tempo):", m.group("effort")) else "easy"


# #5312 — a note that rules a kind OUT ("No intervals", "skip the hills", "without tempo") never names it.
_NEGATED_KIND = re.compile(
    r"\b(?:no|not|without|skip|skipping|avoid|avoiding|never|don'?t(?:\s+do)?|instead\s+of)\s+"
    r"(?:(?:any|the|a|an|hard|fast|hill|high|intense|short)\s+)*"
    r"(?:intervals?|interval\w*|hills?|hilly|climbs?|climbing|tempo|hard)\b",
    re.IGNORECASE,
)


def strip_negated(note: str | None) -> str:
    """`note` with every negated kind word ("no intervals", "not tempo", "skip the intervals") removed, so a kind
    the author ruled out is never read as the kind he asked for."""
    return _NEGATED_KIND.sub(" ", note or "")


def shape_of(note: str | None) -> str:
    """The shape a performed ride's own note names. A note that names none is a flat ride.

    #5374: his own clock grammar counts too ("8/12 for 2 mins for 20 mins" is intervals, "+1 level every 2 mins from
    40 to 60" is a hill; a ride that mixes them takes the one with more minutes, `wrist_clock.family`)."""
    text = strip_negated(note)
    if _INTERVAL_WORD.search(text):
        return "intervals"
    if _HILL_WORD.search(text):
        return "hill"
    clock = wrist_clock.parse_note(text)
    if clock["status"] == "shaped":
        return {"intervals": "intervals", "hills": "hill"}.get(clock["family"], "flat")
    return "flat"


def clock_of(note: str | None) -> dict[str, Any] | None:
    """The clock rule a composed note's line 1 carries, as its structured shape (`wrist_clock.parse_rule`), or None when
    line 1 is not composed or predates the clock rule."""
    m = LINE1_RE.match((note or "").strip().split("\n", 1)[0])
    if not m or not m.group("clock"):
        return None
    shape = wrist_clock.parse_rule(m.group("clock"))
    if shape is not None:
        shape["total_min"] = int(m.group("minutes")) if shape.get("total_min") is None else shape["total_min"]
    return shape


def week_kinds(sessions_by_machine: dict[str, list[dict[str, Any]]] | None, week_start: str, target_date: str) -> list[str]:
    """The menu kinds of this week's performed cardio blocks in [week_start, target_date), oldest first.

    `sessions_by_machine` is movement_key -> its `cardio_index` entry (each `{date, note, ...}`, plus `served_kind`
    when `cardio_menu.annotate_served` matched the routine he performed — #5076: his empty-note rides)."""
    from training import cardio_menu

    rows: list[tuple[str, str]] = []
    for key, sessions in (sessions_by_machine or {}).items():
        for s in sessions or []:
            d = str(s.get("date") or "")[:10]
            if week_start <= d < target_date:
                rows.append((d, cardio_menu.kind_of_performed(key, s.get("note"), s.get("served_kind"))))
    rows.sort()
    return [k for _, k in rows]


def performed_shape(note_text: str | None, total_min: int | None = None) -> dict[str, Any]:
    """A performed cardio block's own note as a structured clock shape (#5374; `training_notes.performed_shape`).

    A composed note pasted back is read through its line-1 clock rule; anything else through his note grammar
    (`wrist_clock.parse_note`). `total_min` (the block's logged duration) closes a clause with no end ("sprint 2
    every 10"). The 10-25 note (verbatim, the test fixture) reads as three clauses over 60 minutes:
        "8/12 for 2 mins for 20 mins / 8/14 for 2 mins for 20 mins / 8 level up every 2 mins from 40 to 60 to level 18"
    -> alternate 8/12 every 2 min 0–20, alternate 8/14 every 2 min 20–40, +1 level every 2 min 40–60 from 8 to 18.
    Deterministic, no model."""
    composed = clock_of(note_text)
    return composed if composed is not None else wrist_clock.parse_note(note_text, total_min)


def prescribed_level(facts: dict[str, Any] | None, verdict: dict[str, Any] | None, *, constrained: bool) -> tuple[int | None, int | None]:
    """(today's level, the level to hold on a yellow/red day). (None, None) when no level is known.

    The base is the last ride's single level; failing that, the top of the span his own calibration
    note called easy ("L9-10 is easy" -> 10). One level up only on a `raise` verdict (his own speed at
    the level clearing his own within-level spread, `cardio_progression.level_verdict`) and never
    while the "no push" gate holds."""
    base = _base_level(facts)[0]
    if base is None:
        return None, None
    base = int(base)
    if not constrained and (verdict or {}).get("verdict") == "raise":
        return base + 1, base
    return base, base


def _base_level(facts: dict[str, Any] | None) -> tuple[int | None, str]:
    """(the base level, where it came from): the last ride's single level (his note's, or — his note silent — the base
    level of the routine he performed, `cardio_progression.prescribed_level_of`, #5076); failing that, the top of the span his own
    calibration note called easy; failing that (#5374), the lowest level of his last ride when it was a clock-shaped ride
    ("8/12 for 2 mins …" returns to 8) — never the shaped ride's top level, which the single-level reader used to take."""
    f = facts or {}
    if f.get("last_level") is not None:
        if f.get("last_level_status") == "prescribed_level":
            # #5076: his note was silent, so the level is the one the routine he performed prescribed — stated as that
            return int(f["last_level"]), "the level his last ride's routine prescribed"
        return int(f["last_level"]), "last ride's level"
    for c in f.get("calibration") or []:
        anchor = (c.get("anchors") or [{}])[0]
        if str(anchor.get("verdict") or "").lower() == "easy" and anchor.get("level_high") is not None:
            return int(anchor["level_high"]), "his calibration note's easy span"
    shaped = f.get("last_shape") or {}
    if shaped.get("base_level") is not None:
        return int(shaped["base_level"]), "the lowest level of his last (clock-shaped) ride"
    return None, "no level on the record"


def shape_label(kind: str) -> str:
    from training import cardio_menu

    shape = KIND_SHAPE.get(kind, "flat")
    if shape == "intervals":
        efforts, work, _easy = cardio_menu.interval_set()
        return f"intervals {efforts}×{work}"
    return shape


def _fmt(v: float) -> str:
    return f"{v:g}"


def effort_rule(
    kind: str, level: int | None = None, hr_ceiling_bpm: int | None = None, incline: float | None = None, minutes: int | None = None
) -> str:
    """The effort words: the menu's RPE band and talk test (tempo: under its label). The shape itself — the hard
    minutes, the climb — is the clock rule's (`clock_shape`), never words here. `hr_ceiling_bpm` is the owner's
    redline CAP on the average (never a target), passed only when no standing constraint forbids HR prescriptions.
    `level` and `incline` are kept for callers; the clock rule carries them now."""
    from training import cardio_menu

    words = cardio_menu.effort_words(kind)
    if kind == "tempo":
        # the menu's label names its own minutes ("hard flat 40"); a block of another length is just "tempo"
        label = cardio_menu.block("tempo").get("label") if minutes == cardio_menu.own_minutes("tempo") else None
        rule = f"{label or 'tempo'}: {words}"
    else:
        rule = words
    return rule + (f", average HR ≤ {int(hr_ceiling_bpm)} bpm" if hr_ceiling_bpm else "")


def clock_shape(kind: str, minutes: int, dose: dict[str, Any], *, walk: bool) -> tuple[list[dict[str, Any]], str, int | None]:
    """(the clauses, the unit, the check-in minutes) of the block's clock rule (#5374), dosed from the menu: the level (or
    incline) is the dose's, the interval set and the incline band and step are the charter's
    (`cardio_menu.interval_set`, `blocks.incline_treadmill_walk`), the step minutes are `cardio_menu.HILL_STEP_MINUTES`.
    The clauses always add up to `minutes`. With no level on record the rule rides "base" (his own pick, by the RPE)."""
    from training import cardio_menu

    total = int(minutes)
    if walk:
        unit = "%"
        base: Any = float(dose["incline_pct"]) if dose.get("incline_pct") is not None else "base"
        base = wrist_clock.num(f"{base:g}") if isinstance(base, float) else base
    else:
        unit = "level"
        base = dose.get("level") if dose.get("level") is not None else "base"
    if kind == "hills":
        every = int(cardio_menu.HILL_STEP_MINUTES)
        if walk:
            walk_block = cardio_menu.block("incline_treadmill_walk")
            step = float((walk_block.get("step") or {}).get("incline_pct") or 1)
            top = float(((walk_block.get("starting_dose") or {}).get("incline_pct") or [0, 0])[1])
            steps = int(round((top - float(base)) / step)) if isinstance(base, (int, float)) and step > 0 else HILL_CLIMB_STEPS
            step_v = wrist_clock.num(f"{step:g}")
        else:
            steps, step_v = HILL_CLIMB_STEPS, HILL_LEVEL_STEP
        return wrist_clock.hill(base, step_v, steps, every, total), unit, None
    if kind == "intervals" and not walk:
        efforts, work, easy = cardio_menu.interval_set()
        hard = base + INTERVAL_LEVEL_STEP if isinstance(base, int) else f"base+{INTERVAL_LEVEL_STEP}"
        return wrist_clock.intervals(base, hard, efforts, work, easy, total), unit, None
    check_in = EASY_CHECK_IN_MINUTES if kind in ("easy", "incline_treadmill_walk") else None
    clauses, every_ = wrist_clock.steady(base, total, check_in)
    return clauses, unit, every_


def clock_rule(kind: str, minutes: int, dose: dict[str, Any], *, walk: bool) -> str:
    """The block's clock rule as one line under `wrist_clock.RULE_RE`."""
    clauses, unit, check_in = clock_shape(kind, minutes, dose, walk=walk)
    return wrist_clock.render(clauses, unit, check_in)


def dose_text(dose: dict[str, Any], kind: str, peak: float | None = None) -> str:
    """Line 1's dose words, with their trailing space (empty when no dose is known). `peak` is the top of the clock rule's
    climb on a treadmill hill (#5374: the band the rule actually climbs, so the two never disagree)."""
    if dose.get("incline_pct") is not None:
        inc = float(dose["incline_pct"])
        if kind == "hills":
            if peak is None:
                from training import cardio_menu

                top = (cardio_menu.block("incline_treadmill_walk").get("starting_dose") or {}).get("incline_pct") or [inc, inc]
                peak = max(inc, float(top[1]))
            if float(peak) > inc:
                return f"incline {_fmt(inc)}–{_fmt(float(peak))}% at {dose['mph']} mph "
        return f"incline {_fmt(inc)}% at {dose['mph']} mph "
    if dose.get("level") is None:
        return ""
    return f"level {dose['level']}" + (f" at {dose['mph']} mph " if dose.get("mph") is not None else " ")


def line1(machine: str, minutes: int, kind: str, dose: dict[str, Any], hr_ceiling_bpm: int | None = None, *, walk: bool = False) -> str:
    """THE RULE LINE: machine · minutes · dose and shape · the clock rule · the effort words."""
    words = effort_rule(kind, dose.get("level"), hr_ceiling_bpm, dose.get("incline_pct"), int(minutes))
    clock = clock_rule(kind, int(minutes), dose, walk=walk)
    peak = None
    if walk and kind == "hills":
        shape = wrist_clock.parse_rule(clock)
        peak = (shape or {}).get("top_level")
    return f"{machine} · {int(minutes)} min · {dose_text(dose, kind, peak)}{shape_label(kind)} · {clock} · {words}"


def recovery_answer(
    *,
    kind: str,
    hold: str | None,
    constraint: dict[str, Any] | None,
    gate: bool,
    recovery_band: str | None,
) -> str:
    """The recovery question, answered. `hold` is the dose to hold ("level 11" / "8% at 2.8 mph")."""
    if gate:
        return f"No push — talk test only, no HR target (standing constraint since {(constraint or {}).get('active_from')})."
    if constraint and not constraint.get("hr_prescriptions_allowed", True):
        # the HR half of the constraint: Whoop's bands are not a read on this regime, so the answer is the feel
        easy_hold = f"hold {hold}" if hold else "hold the pace"
        if kind in ("tempo", "hills", "intervals"):
            return f"By feel, no HR target: as written; feel off, {easy_hold} at an easy effort."
        return f"By feel, no HR target: {easy_hold}."
    hold_txt = f"hold {hold}" if hold else "hold the pace"
    add = f"add {GREEN_ADD_MINUTES} min if it feels easy (the {GREEN_ADD_MINUTES}-min step is platform-chosen)"
    if kind in ("tempo", "hills", "intervals"):
        if recovery_band == "green":
            return "Green: as written."
        return f"Green: as written; yellow or red: {hold_txt} at an easy effort."
    if recovery_band == "green":
        return f"Green: {hold_txt}; {add}."
    if recovery_band in ("yellow", "red"):
        return f"{recovery_band.capitalize()}: {hold_txt}."
    return f"Green: {hold_txt}, {add}; yellow or red: {hold_txt}."


def why_sentence(movement_key: str, archetype: Any, aerobic_block: dict[str, Any] | None) -> str:
    """At most one sentence of why, stated positively (no sentence starts with "Not")."""
    from training import cardio_menu

    seated = movement_key in BIKES or movement_key in ("rowing_machine", "elliptical")
    block = aerobic_block or {}
    if block.get("state") != "read":
        return "Aerobic base, seated, so the feet rest." if seated else ""
    t = block.get("totals") or {}
    wb = t.get("weight_bearing_hr_48h")
    wk = t.get("week_to_date") or {}
    over = None
    if wk.get("over_ramp") and wk.get("hours") is not None and wk.get("ramp_ceiling_hr") is not None:
        over = round(float(wk["hours"]) - float(wk["ramp_ceiling_hr"]), 1)
    if seated:
        if cardio_menu.is_lower(archetype):
            return "Seated, so the legs keep today's lifting as their work."
        tail = f"; the week is already {over} h over the walking ramp" if over else ""
        if wb is not None:
            return f"Seated, so the feet rest after {wb} h on them in 48 h{tail}."
        return f"Seated, so the feet rest{tail}."
    if wb is not None:
        return f"On your feet today: the legs are fresh ({wb} h weight-bearing in 48 h)."
    return ""


def compose(
    *,
    movement_key: str,
    minutes: int,
    target_date: str,
    archetype: Any = "",
    kind: str | None = None,
    facts: dict[str, Any] | None = None,
    verdict: dict[str, Any] | None = None,
    treadmill_sessions: list[dict[str, Any]] | None = None,
    aerobic_block: dict[str, Any] | None = None,
    constraint: dict[str, Any] | None = None,
    recovery_band: str | None = None,
    hr_ceiling_bpm: int | None = None,
    placement_why: str | None = None,
    previous: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """(the note, the audit). ≤ 2 lines; line 1 matches `LINE1_RE` and carries the dose.

    `kind` is the menu block (`cardio_menu.choose_kind`); None = the machine's easy kind. `constraint` is
    the active standing constraint (`standing_constraints.active_constraint`), None when there is none.
    `recovery_band` is the day's green/yellow/red when known, None at draft time (the note then answers
    both branches). `hr_ceiling_bpm` is printed only when there is no constraint. `previous` is
    `cardio_menu.previous_performed` (the recumbent rule, ruling 2026-10-25 on #5076); None = not read."""
    from training import cardio_menu, standing_constraints

    machine = machine_for(movement_key) or str(movement_key).replace("_", " ").capitalize()
    is_walk = movement_key in WALKS
    gate = standing_constraints.intensity_gate_active(constraint, target_date)
    requested = kind or ("incline_treadmill_walk" if is_walk else "easy")
    kind = requested
    if gate and kind in cardio_menu.HARD:
        kind = "incline_treadmill_walk" if is_walk else "easy"
    if is_walk and kind not in ("incline_treadmill_walk", "hills"):
        kind = "incline_treadmill_walk"
    if not is_walk and kind == "incline_treadmill_walk":
        kind = "easy"
    if is_walk:
        dose = cardio_menu.treadmill_dose(treadmill_sessions)
        hold = f"{_fmt(float(dose['incline_pct']))}% at {dose['mph']} mph"
    else:
        dose = cardio_menu.bike_dose(kind, facts, verdict, constrained=gate)
        hold = f"level {dose['hold_level']}" if dose.get("hold_level") is not None else None
    # the owner's walking HR cap rides only an easy block, and never under the constraint's HR half
    cap = None if (constraint or kind in cardio_menu.HARD) else hr_ceiling_bpm
    first = line1(machine, int(minutes), kind, dose, cap, walk=is_walk)
    clock = clock_of(first)
    from training import recent_aerobic

    # #5076: a block off the default walk says why. A conditioning kind the menu never runs on the treadmill states
    # that (its machines are the reason, not the feet); every other case keeps the seated/on-your-feet sentence.
    off = cardio_menu.off_default(kind, movement_key, recent_aerobic.legs_loaded(aerobic_block)[0], previous)
    why = off["reason"] if off and off["charter"] and off["charter"].startswith("cardio_menu.blocks.") else ""
    parts = (
        recovery_answer(kind=kind, hold=hold, constraint=constraint, gate=gate, recovery_band=recovery_band),
        (dose.get("reason") or "").rstrip(".") + "." if dose.get("reason") else "",
        why or why_sentence(movement_key, archetype, aerobic_block),
    )
    second = " ".join(p[0].upper() + p[1:] for p in parts if p)
    note = first + ("\n" + second if second else "")
    audit = {
        "version": CARDIO_NOTE_VERSION,
        "charter_version": _charter_version(),
        "kind": kind,
        "requested_kind": requested,
        "placement_why": placement_why,
        # #5076: why this is not the default incline walk, and the charter key that makes it so (None = the default)
        "off_default": off,
        "shape": KIND_SHAPE.get(kind, "flat"),
        "level": dose.get("level"),
        "hold_level": dose.get("hold_level"),
        "mph": dose.get("mph"),
        "incline_pct": dose.get("incline_pct"),
        "dose_reason": dose.get("reason") or None,
        "level_basis": dose.get("basis") if is_walk else _base_level(facts)[1],
        "verdict": _verdict_word(verdict, dose, is_walk),
        "rpe": list(cardio_menu.rpe_band(kind) or ()),
        "minutes": int(minutes),
        # #5374: the clock rule as he runs it from his wrist, and its structure (adherence grades against it)
        "clock_rule": m1.group("clock") if (m1 := LINE1_RE.match(first)) else None,
        "clock": {k: (clock or {}).get(k) for k in ("family", "total_min", "change_points", "levels", "unit")} if clock else None,
        "clock_off_grid": wrist_clock.off_grid(clock),
        "clock_numbers": wrist_clock.numbers_to_remember(clock),
        "constraint": (constraint or {}).get("id"),
        "no_push_gate": gate,
        "recovery_band": recovery_band,
        "labels": {**LABELS, **cardio_menu.LABELS},
    }
    return note, audit


def _verdict_word(verdict: dict[str, Any] | None, dose: dict[str, Any], is_walk: bool) -> str | None:
    """The audit's verdict. `level_verdict` reads only the last ride's level, so it says `no_level` when the dose's level
    came from his calibration note's easy span (#5201): a given level reads `calibration_level`, never `no_level`.
    It still claims no improvement (that is `claims_improvement`, True only on `raise`)."""
    word = (verdict or {}).get("verdict")
    if word == "no_level" and not is_walk and dose.get("level") is not None:
        return "calibration_level"
    return word


def _charter_version() -> str | None:
    from training import training_charter

    return training_charter.charter_version()
