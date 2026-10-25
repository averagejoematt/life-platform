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

  line 1, one fixed grammar (`LINE1_RE`):
      <machine> · <minutes> min · <dose> <flat | intervals a×b | hill | walk> · <effort rule>
      dose = "level <N> at <S> mph" (a bike; " at <S> mph" left out when no ride at that level is on
      record, "level <N> " left out only when no level is known at all) or "incline <I>% at <S> mph" /
      "incline <I>–<J>% at <S> mph" (the treadmill walk / its hill);
      e.g. "Recumbent bike · 30 min · level 11 at 14.6 mph flat · RPE 4–5, full sentences"
           "Treadmill · 30 min · incline 8% at 2.8 mph walk · RPE 4–6, full sentences"
      The effort rule is the menu's RPE band and talk test (`cardio_menu.effort_words`) — never an HR
      number while the 2026-10-10 constraint holds its HR half;
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

CARDIO_NOTE_VERSION = "cardio-note@2.0.0"

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
LABELS = {
    "green_add_minutes": "platform-chosen",
    "interval_level_step": "platform-chosen",
}

SHAPES = ("flat", "intervals", "hill", "walk")
# kind -> line 1's shape word
KIND_SHAPE = {"easy": "flat", "tempo": "flat", "intervals": "intervals", "hills": "hill", "incline_treadmill_walk": "walk"}

# Line 1. The shape alternation is the grammar's own, so a fifth shape cannot slip in unnamed.
LINE1_RE = re.compile(
    r"^(?P<machine>[A-Z][A-Za-z ]+) · (?P<minutes>\d+) min · "
    r"(?:level (?P<level>\d+)(?: at (?P<mph>\d+(?:\.\d)?) mph)? "
    r"|incline (?P<incline>\d+(?:\.\d)?)(?:–(?P<incline_top>\d+(?:\.\d)?))?% at (?P<walk_mph>\d+(?:\.\d)?) mph )?"
    r"(?P<shape>flat|intervals \d+×\d+|hill|walk) · (?P<effort>\S.*)$"
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
    """The shape a performed ride's own note names. A note that names none is a flat ride."""
    text = strip_negated(note)
    if _INTERVAL_WORD.search(text):
        return "intervals"
    if _HILL_WORD.search(text):
        return "hill"
    return "flat"


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


def prescribed_level(facts: dict[str, Any] | None, verdict: dict[str, Any] | None, *, constrained: bool) -> tuple[int | None, int | None]:
    """(today's level, the level to hold on a yellow/red day). (None, None) when no level is known.

    The base is the last ride's single level; failing that, the top of the span his own calibration
    note called easy ("L9-10 is easy" -> 10). One level up only on a `raise` verdict (his own speed at
    the level clearing his own within-level spread, `cardio_progression.level_verdict`) and never
    while the "no push" gate holds."""
    f = facts or {}
    base = f.get("last_level")
    if base is None:
        for c in f.get("calibration") or []:
            anchor = (c.get("anchors") or [{}])[0]
            if str(anchor.get("verdict") or "").lower() == "easy" and anchor.get("level_high") is not None:
                base = int(anchor["level_high"])
                break
    if base is None:
        return None, None
    base = int(base)
    if not constrained and (verdict or {}).get("verdict") == "raise":
        return base + 1, base
    return base, base


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
    kind: str, level: int | None, hr_ceiling_bpm: int | None = None, incline: float | None = None, minutes: int | None = None
) -> str:
    """The effort rule: the menu's RPE band and talk test, plus the shape's own instruction.
    `hr_ceiling_bpm` is the owner's redline CAP on the average (never a target), passed only when no
    standing constraint forbids HR prescriptions."""
    from training import cardio_menu

    words = cardio_menu.effort_words(kind)
    if kind == "intervals":
        _n, work, easy = cardio_menu.interval_set()
        hard = f"level {level + INTERVAL_LEVEL_STEP}" if level is not None else "a harder level"
        band = cardio_menu.rpe_band("intervals")
        rule = (
            f"{work} min at {hard}, {easy} min easy between, RPE {band[0]} on the hard minutes"
            if band
            else f"{work} min at {hard}, {easy} min easy between"
        )
    elif kind == "hills" and incline is not None:
        step = (cardio_menu.block("incline_treadmill_walk").get("step") or {}).get("incline_pct")
        rule = f"{words}; up {_fmt(float(step or 1))}% every {cardio_menu.HILL_STEP_MINUTES} min, then back down"
    elif kind == "hills":
        rule = f"the hill program, {words}"
    elif kind == "tempo":
        # the menu's label names its own minutes ("hard flat 40"); a block of another length is just "tempo"
        label = cardio_menu.block("tempo").get("label") if minutes == cardio_menu.own_minutes("tempo") else None
        rule = f"{label or 'tempo'}: {words}"
    else:
        rule = words
    return rule + (f", average HR ≤ {int(hr_ceiling_bpm)} bpm" if hr_ceiling_bpm else "")


def dose_text(dose: dict[str, Any], kind: str) -> str:
    """Line 1's dose words, with their trailing space (empty when no dose is known)."""
    if dose.get("incline_pct") is not None:
        inc = float(dose["incline_pct"])
        if kind == "hills":
            from training import cardio_menu

            top = (cardio_menu.block("incline_treadmill_walk").get("starting_dose") or {}).get("incline_pct") or [inc, inc]
            return f"incline {_fmt(inc)}–{_fmt(max(inc, float(top[1])))}% at {dose['mph']} mph "
        return f"incline {_fmt(inc)}% at {dose['mph']} mph "
    if dose.get("level") is None:
        return ""
    return f"level {dose['level']}" + (f" at {dose['mph']} mph " if dose.get("mph") is not None else " ")


def line1(machine: str, minutes: int, kind: str, dose: dict[str, Any], hr_ceiling_bpm: int | None = None) -> str:
    rule = effort_rule(kind, dose.get("level"), hr_ceiling_bpm, dose.get("incline_pct"), int(minutes))
    return f"{machine} · {int(minutes)} min · {dose_text(dose, kind)}{shape_label(kind)} · {rule}"


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
    first = line1(machine, int(minutes), kind, dose, cap)
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
        "level_basis": (
            dose.get("basis")
            if is_walk
            else (
                "last ride's level"
                if (facts or {}).get("last_level") is not None
                else ("his calibration note's easy span" if dose.get("level") is not None else "no level on the record")
            )
        ),
        "verdict": _verdict_word(verdict, dose, is_walk),
        "rpe": list(cardio_menu.rpe_band(kind) or ()),
        "minutes": int(minutes),
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
