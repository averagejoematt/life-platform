"""cardio_note.py — the cardio block's note in Hevy, prescription first (#5048).

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
      <machine> · <minutes> min · level <N> <flat | intervals a×b | hill> · <effort rule>
      e.g. "Recumbent bike · 20 min · level 11 flat · talk-test pace, full sentences"
      (`level <N> ` is left out only when no level is known — a treadmill, whose notes carry none);
  line 2, the recovery question answered from the day's state, then at most one sentence of why.

The level is still DERIVED from the last ride's level and his calibration note
(`cardio_progression.cardio_facts` / `level_verdict`) — the derivation stays, the "Last: …" sentence
goes. "Optional if the ECG is not sinus" is the standing-constraint gate's own line
(`standing_constraints.gate_lines`), never repeated here. No sentence starts with "Not".

THE SHAPE RULE (never a default)

`flat` is the default. `intervals 5×2` is chosen only when the week's previous ride was flat, the week
is under the walking ramp, a level is known, the block is long enough and there is no standing
constraint; `hill` only for the next ride after a flat and an intervals ride in the same week, on a
machine with a hill program. Yellow or red recovery, an over-ramp or unread week, or the 2026-10-10
standing constraint (no push) all hold the ride flat. Pure: no I/O, no clock.
"""

from __future__ import annotations

import re
from typing import Any

CARDIO_NOTE_VERSION = "cardio-note@1.0.0"

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
HILL_MACHINES = ("cycling", "elliptical")  # a hill program on the console; a treadmill hill is an incline, not this shape
BIKES = ("cycling", "air_bike")

# ── the thresholds this note acts on, each labelled (ADR-105) ─────────────────────────
# PLATFORM-CHOSEN, not his variance: the step he may add on a green day when the ride feels easy.
GREEN_ADD_MINUTES = 5
# PLATFORM-CHOSEN: the interval set — efforts × minutes, each effort INTERVAL_LEVEL_STEP levels above
# the base, with an equal easy block at the base level between. 5 × (2 + 2) = 20 min, the shortest block
# the shape fits in.
INTERVALS = (5, 2)
INTERVAL_LEVEL_STEP = 2
INTERVAL_MIN_MINUTES = INTERVALS[0] * INTERVALS[1] * 2
LABELS = {
    "green_add_minutes": "platform-chosen",
    "intervals": "platform-chosen",
    "interval_level_step": "platform-chosen",
}

SHAPES = ("flat", "intervals", "hill")
EFFORT_FLAT = "talk-test pace, full sentences"

# Line 1. The shape alternation is the grammar's own, so a fourth shape cannot slip in unnamed.
LINE1_RE = re.compile(
    r"^(?P<machine>[A-Z][A-Za-z ]+) · (?P<minutes>\d+) min · (?:level (?P<level>\d+) )?(?P<shape>flat|intervals \d+×\d+|hill) · (?P<effort>\S.*)$"
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


def shape_of(note: str | None) -> str:
    """The shape a performed ride's own note names. A note that names none is a flat ride."""
    text = note or ""
    if _INTERVAL_WORD.search(text):
        return "intervals"
    if _HILL_WORD.search(text):
        return "hill"
    return "flat"


def week_shapes(sessions: list[dict[str, Any]] | None, week_start: str, target_date: str) -> list[str]:
    """The shapes of this template's rides in [week_start, target_date), oldest first.

    `sessions` is a `cardio_index` entry (most-recent first, each `{date, note, ...}`)."""
    rows = [s for s in sessions or [] if week_start <= str(s.get("date") or "")[:10] < target_date]
    rows.sort(key=lambda s: str(s.get("date") or ""))
    return [shape_of(s.get("note")) for s in rows]


def prescribed_level(facts: dict[str, Any] | None, verdict: dict[str, Any] | None, *, constrained: bool) -> tuple[int | None, int | None]:
    """(today's level, the level to hold on a yellow/red day). (None, None) when no level is known.

    The base is the last ride's single level; failing that, the top of the span his own calibration
    note called easy ("L9-10 is easy" -> 10). One level up only on a `raise` verdict (his own speed at
    the level clearing his own within-level spread, `cardio_progression.level_verdict`) and never
    under a standing constraint."""
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


def choose_shape(
    *,
    movement_key: str,
    minutes: int,
    level: int | None,
    prior_week_shapes: list[str],
    over_ramp: bool | None,
    constrained: bool,
    recovery_band: str | None = None,
) -> tuple[str, str]:
    """(shape, why it was chosen). `flat` unless every condition for a harder shape holds."""
    if constrained:
        return "flat", "the 2026-10-10 standing constraint: no push"
    if recovery_band in ("yellow", "red"):
        return "flat", f"{recovery_band} recovery"
    if over_ramp is None:
        return "flat", "the week's walking load was not read"
    if over_ramp:
        return "flat", "the week is over the walking ramp"
    if level is None:
        return "flat", "no level to build a harder shape on"
    if not prior_week_shapes:
        return "flat", "the week's first ride is flat"
    if prior_week_shapes[-1] == "flat" and "intervals" not in prior_week_shapes and minutes >= INTERVAL_MIN_MINUTES:
        return "intervals", "the week's last ride was flat and the ramp allows"
    if (
        "flat" in prior_week_shapes
        and "intervals" in prior_week_shapes
        and "hill" not in prior_week_shapes
        and movement_key in HILL_MACHINES
    ):
        return "hill", "the week already has a flat and an intervals ride and the ramp allows"
    return "flat", "the week's harder shapes are done"


def shape_label(shape: str) -> str:
    return f"intervals {INTERVALS[0]}×{INTERVALS[1]}" if shape == "intervals" else shape


def effort_rule(shape: str, level: int | None, hr_ceiling_bpm: int | None = None) -> str:
    """The effort rule. `hr_ceiling_bpm` is the owner's redline CAP on the average (never a target), and
    the caller passes it only when no standing constraint forbids HR prescriptions."""
    if shape == "intervals" and level is not None:
        rule = f"{INTERVALS[1]} min at level {level + INTERVAL_LEVEL_STEP}, {INTERVALS[1]} min easy between"
    elif shape == "hill":
        rule = "the hill program, talk-test pace on the climbs"
    else:
        rule = EFFORT_FLAT
    return rule + (f", average HR ≤ {int(hr_ceiling_bpm)} bpm" if hr_ceiling_bpm else "")


def line1(machine: str, minutes: int, level: int | None, shape: str, hr_ceiling_bpm: int | None = None) -> str:
    lvl = f"level {level} " if level is not None else ""
    return f"{machine} · {int(minutes)} min · {lvl}{shape_label(shape)} · {effort_rule(shape, level, hr_ceiling_bpm)}"


def recovery_answer(
    *, shape: str, level: int | None, hold_level: int | None, constraint: dict[str, Any] | None, recovery_band: str | None
) -> str:
    """The recovery question, answered. Under the standing constraint: no push, whatever the band."""
    if constraint:
        return f"No push — talk test only, no HR target (standing constraint since {constraint.get('active_from')})."
    hold = f"hold level {hold_level}" if hold_level is not None else "hold the pace"
    add = f"add {GREEN_ADD_MINUTES} min if it feels easy (the {GREEN_ADD_MINUTES}-min step is platform-chosen)"
    if shape != "flat":
        flat = f"ride it flat at level {hold_level}" if hold_level is not None else "ride it flat"
        harder = (
            f"{shape_label(shape)} at +{INTERVAL_LEVEL_STEP} levels is platform-chosen" if shape == "intervals" else "platform-chosen shape"
        )
        if recovery_band == "green":
            return f"Green: as written ({harder})."
        return f"Green: as written; yellow or red: {flat} ({harder})."
    if recovery_band == "green":
        return f"Green: {hold}; {add}."
    if recovery_band in ("yellow", "red"):
        return f"{recovery_band.capitalize()}: {hold}."
    return f"Green: {hold}, {add}; yellow or red: {hold}."


def why_sentence(movement_key: str, archetype: Any, aerobic_block: dict[str, Any] | None) -> str:
    """At most one sentence of why, stated positively (no sentence starts with "Not")."""
    from training import recent_aerobic

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
        if recent_aerobic.is_lower(archetype):
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
    facts: dict[str, Any] | None = None,
    verdict: dict[str, Any] | None = None,
    aerobic_block: dict[str, Any] | None = None,
    prior_week_shapes: list[str] | None = None,
    constraint: dict[str, Any] | None = None,
    recovery_band: str | None = None,
    hr_ceiling_bpm: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """(the note, the audit). ≤ 2 lines; line 1 matches `LINE1_RE`.

    `constraint` is the active standing constraint (`standing_constraints.active_constraint`), None when
    there is none. `recovery_band` is the day's green/yellow/red when known, None at draft time (the note
    then answers both branches). `hr_ceiling_bpm` (the owner's walking redline cap on the average) is
    printed only when there is no constraint — under one, no HR number is ever written."""
    machine = machine_for(movement_key) or str(movement_key).replace("_", " ").capitalize()
    constrained = bool(constraint)
    level, hold_level = prescribed_level(facts, verdict, constrained=constrained)
    wk = ((aerobic_block or {}).get("totals") or {}).get("week_to_date") or {}
    over_ramp = wk.get("over_ramp") if (aerobic_block or {}).get("state") == "read" else None
    shape, shape_why = choose_shape(
        movement_key=movement_key,
        minutes=int(minutes),
        level=level,
        prior_week_shapes=list(prior_week_shapes or []),
        over_ramp=over_ramp,
        constrained=constrained,
        recovery_band=recovery_band,
    )
    if shape != "flat":  # a harder shape never rides a raised level: the raise and the shape are one step each
        level = hold_level
    first = line1(machine, int(minutes), level, shape, None if constrained else hr_ceiling_bpm)
    second = " ".join(
        p
        for p in (
            recovery_answer(shape=shape, level=level, hold_level=hold_level, constraint=constraint, recovery_band=recovery_band),
            why_sentence(movement_key, archetype, aerobic_block),
        )
        if p
    )
    note = first + ("\n" + second if second else "")
    audit = {
        "version": CARDIO_NOTE_VERSION,
        "level": level,
        "hold_level": hold_level,
        "level_basis": (
            "last ride's level"
            if (facts or {}).get("last_level") is not None
            else ("his calibration note's easy span" if level is not None else "no level on the record")
        ),
        "verdict": (verdict or {}).get("verdict"),
        "shape": shape,
        "shape_why": shape_why,
        "prior_week_shapes": list(prior_week_shapes or []),
        "constraint": (constraint or {}).get("id"),
        "recovery_band": recovery_band,
        "labels": LABELS,
    }
    return note, audit
