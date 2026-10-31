"""cardio_note.py — the cardio block's note in Hevy: the level, the ride clock, the effort, the watch step (#5428).

WHY THIS EXISTS

The 2026-10-26 easy ride went out as "Recumbent bike · 30 min · level 18 at 13.8 mph flat · level 18 for 30 · check in
every 10 min · RPE 4–5, full sentences" plus a rationale tail — the minutes the set row already shows, a speed he cannot
see under the iPad, a level read off the TOP of his 10-25 ramp (his usual is 11–12), and a recovery paragraph. A
four-voice review graded the generated cardio notes D; `HEVY_NOTE_STANDARD.md` §3.7 (issue #5428) is the A-grade form.

THE NOTE (≤ 4 lines; `HEVY_NOTE_STANDARD.md` §3.7)

    line 1   <Machine> · <levels> · [hard ]RPE <a[–b]> (<talk words>)                  always (`LINE1_RE`)
    line 2   ⌚ ride clock: <rule>   (`⌚ walk clock:` on the treadmill)                  tempo / hills / intervals
    line 3   Full sentences as rep 1 ends → L<n> reps.                                    intervals (the escape)
    line 4   <one why>                                                                   optional, a route choice only
    line 4   After: end watch cardio, restart Hevy.                                       when a Hevy block follows

  * No minutes (the set row shows them). No speed on a bike, elliptical or rower (an output under the iPad); a treadmill's
    speed and grade ARE settings, so they are prescribed, with `today` when they differ from his usual (his own last
    logged treadmill notes, "3.3 / 1.5 incline", read by `wrist_clock.parse_walk`).
  * RPE and the talk test lead; the talk words are fixed per effort (`TALK_WORDS`). No HR target: his zones are not
    re-derived since the 2026-10-10 episode and the medication change (§10 Q1), so `hr_ceiling_bpm` is accepted for the
    callers' signature and never printed.
  * The clock rule is read off the session clock from 0 in whole minutes, `min` on every time, at most three levels,
    ≤ `CLOCK_LINE_MAX` characters (the owner's wrist-clock rule, 2026-10-25: an iPad covers the console and the watch
    does not alert). Intervals list every start minute, name the level before, between and after the hard reps, and carry
    one escape upward on its own line, checked as rep 1 ends.
  * Levels come from HIS log (`steady_level`: the median of his last single-level rides), never from the top of a ramp:
    easy = steady, tempo = steady + 1, intervals = steady before / between / after and steady + 1 hard (an escape one
    more), hills climb from steady. A treadmill hill starts no steeper than his steepest logged grade.
  * `After:` (owner protocol 2026-10-27): the watch's cardio workout and Hevy's watch workout cannot run together, so a
    cardio block a Hevy block follows reminds him to restart Hevy's (`apply_after_lines`, idempotent).

The structured clock (`clock_shape`) is the same `wrist_clock` structure as before, so adherence grades a performed shape
against the prescribed one (`clock_of` reads the note back). A note composed in the earlier grammar (line 1 carrying
"<machine> · <N> min · level …") still reads (`LEGACY_LINE1_RE`): performed routines keep their history.

The recovery answer, the dose's reason and the seated/feet sentence leave the wire; they stay in the audit
(`inputs_snapshot.cardio_notes`). Pure: no I/O, no clock.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

from training import hevy_note_grammar, wrist_clock

CARDIO_NOTE_VERSION = "cardio-note@4.2.0"  # 4.0.0 = the #5428 standard: level · effort line, ⌚ ride clock, After line
# 4.1.0 = the 2026-10-30 re-grade: ≤ 3 levels on a bike hill, the talk words' band on line 1, `walk clock` on a treadmill
# 4.2.0 = the 2026-10-31 re-grade #2: intervals ride his steady level before / between / after, a one-level escape on its
# own line, checked as rep 1 ends

# movement_key -> the machine as line 1 names it. `cycling` is the program's knee-sparing recumbent
# (`recent_aerobic.cardio_pick`: "cycling (recumbent)").
MACHINES: dict[str, str] = {
    "cycling": "Recumbent",
    "treadmill": "Treadmill",
    "walking": "Walk",
    "elliptical": "Elliptical",
    "rowing_machine": "Rower",
    "air_bike": "Air bike",
}
BIKES = ("cycling", "air_bike")
WALKS = ("treadmill",)

# ── the thresholds this note acts on, each labelled (ADR-105) ─────────────────────────
# PLATFORM-CHOSEN (panel, #5428): an interval's hard minutes sit one level over his steady level. Re-grade #2
# (2026-10-31): its easy minutes — before, between and after the reps — ARE his steady level (standard §3.7: "between" =
# his steady L11; it was one under, L10), and the escape (full sentences as rep 1 ends) is ONE level, not two.
INTERVAL_LEVEL_STEP = 1
INTERVAL_EASY_STEP = 0
INTERVAL_ESCAPE_STEP = hevy_note_grammar.INTERVAL_ESCAPE_STEP
# PLATFORM-CHOSEN (#5374): a hill climbs this many steps of `HILL_LEVEL_STEP` levels and back down. #5428 re-grade
# (2026-10-30): standard §3.7 caps a clock rule at 3 levels (`hevy_note_grammar.CLOCK_MAX_LEVELS`), so a bike hill is
# steady + 2 — four steps were L11 → L15, five levels. A treadmill hill climbs GRADES, not levels (1% a step, the
# standard's own `6% → 10%` example), so it keeps four.
HILL_CLIMB_STEPS = hevy_note_grammar.CLOCK_MAX_LEVELS - 1
HILL_WALK_CLIMB_STEPS = 4
HILL_LEVEL_STEP = 1
# PLATFORM-CHOSEN (#5428, the corpus's tempo ride): the tempo talk-test check-ins, at min 5 and then every 10, none in
# the last 10 minutes.
TEMPO_FIRST_CHECK_MIN = 5
TEMPO_CHECK_EVERY_MIN = 10
# PLATFORM-CHOSEN (#5428): his steady level is the median of this many of his last single-level rides.
STEADY_RIDES = 5
# #5428 standard §7: the clock line's phone budget (owner-calibrated by one screenshot, §5 rollout).
CLOCK_LINE_MAX = 110
ROUTE_WHY_MAX = 60
LABELS = {
    "interval_level_step": "platform-chosen",
    "interval_easy_step": "platform-chosen",
    "interval_escape_step": "platform-chosen",
    "hill_climb_steps": "platform-chosen",
    "hill_walk_climb_steps": "platform-chosen",
    "hill_level_step": "platform-chosen",
    "tempo_first_check_min": "platform-chosen",
    "tempo_check_every_min": "platform-chosen",
    "steady_rides": "platform-chosen",
}

# the fixed talk-test words per effort (standard §3.7): full sentences = RPE 4–5, short phrases = 6–7, a few words = 8
TALK_WORDS = tuple(hevy_note_grammar.TALK_WORDS)  # Lane D's grammar: the linter reads the same words
CLOCK_PREFIX = hevy_note_grammar.CLOCK_PREFIX
CLOCK_PREFIXES = hevy_note_grammar.CLOCK_PREFIXES  # `walk clock` on the treadmill (`hevy_note_grammar.clock_prefix_for`)
AFTER_LINE = hevy_note_grammar.AFTER_LINE
CARDIO_KINDS_SHAPE = {"easy": "flat", "tempo": "flat", "intervals": "intervals", "hills": "hill", "incline_treadmill_walk": "walk"}
KIND_SHAPE = CARDIO_KINDS_SHAPE

_N = r"\d{1,2}(?:\.\d{1,2})?"
_MACHINE_ALT = "|".join(re.escape(v) for v in sorted(set(MACHINES.values()), key=len, reverse=True))
# Line 1 (#5428). Named groups `level`, `mph`, `walk_mph` and `effort` are read by `hevy_render` (the render table);
# `mph` is a bike's speed, which is never prescribed (an output), so it is an always-empty group kept for that reader.
LINE1_RE = re.compile(
    rf"^(?P<machine>{_MACHINE_ALT}) · (?P<mph>)"
    rf"(?:(?P<today>today )?(?P<walk_mph>{_N}) mph, (?P<incline>{_N})%(?: → (?P<incline_top>{_N})%)?"
    r"|L(?P<level>\d{1,2})(?:/L(?P<level_hard>\d{1,2})| → L(?P<level_top>\d{1,2}))?"
    r"|(?P<pick>your level|your pace)) · "
    rf"(?P<effort>(?P<hard>hard )?RPE (?P<rpe_lo>\d)(?:–(?P<rpe_hi>\d))? \((?P<talk>{'|'.join(TALK_WORDS)})\))$"
)
# The note grammar before #5428 (cardio-note@3.0.0), kept so a performed routine's note still reads (history).
LEGACY_LINE1_RE = re.compile(
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


def _first_line(note: str | None) -> str:
    return (note or "").strip().split("\n", 1)[0]


def _clock_line(note: str | None) -> str | None:
    for ln in (note or "").strip().split("\n")[1:]:
        if ln.startswith(CLOCK_PREFIXES):
            return ln.split(": ", 1)[1]
    return None


def is_composed(note: str | None) -> bool:
    """True when the note's first line is this module's line 1, in either grammar (re-drafting never stacks)."""
    first = _first_line(note)
    return bool(LINE1_RE.match(first) or LEGACY_LINE1_RE.match(first))


def read_line1(note: str | None) -> dict[str, Any] | None:
    """A composed note's line 1 as named facts — {grammar, machine, kind, level, base_level, mph, incline_pct, top} —
    or None when line 1 is not composed. `level` is the dose's level (tempo: steady + 1; intervals: the hard level);
    `base_level` the easy-effort level the dose was built on (his steady level). Both grammars read."""
    first = _first_line(note)
    m = LINE1_RE.match(first)
    if m:
        out: dict[str, Any] = {"grammar": "4", "machine": m.group("machine"), "today": bool(m.group("today"))}
        if m.group("walk_mph") is not None:
            out.update(
                kind="hills" if m.group("incline_top") else "incline_treadmill_walk",
                mph=float(m.group("walk_mph")),
                incline_pct=float(m.group("incline")),
                top=float(m.group("incline_top")) if m.group("incline_top") else None,
                level=None,
                base_level=None,
            )
            return out
        lv = int(m.group("level")) if m.group("level") else None
        if m.group("level_hard"):
            hard = int(m.group("level_hard"))
            out.update(kind="intervals", level=hard, base_level=hard - INTERVAL_LEVEL_STEP, easy_level=lv, top=None)
        elif m.group("level_top"):
            out.update(kind="hills", level=lv, base_level=lv, top=int(m.group("level_top")))
        elif m.group("hard"):
            out.update(kind="intervals", level=None, base_level=None, top=None)
        elif m.group("talk") == "short phrases":
            from training import cardio_menu

            out.update(kind="tempo", level=lv, base_level=(lv - cardio_menu.TEMPO_LEVEL_STEP) if lv else None, top=None)
        else:
            out.update(kind="easy", level=lv, base_level=lv, top=None)
        out["mph"] = out["incline_pct"] = None
        return out
    m = LEGACY_LINE1_RE.match(first)
    if not m:
        return None
    shape = m.group("shape")
    if shape == "walk":
        kind = "incline_treadmill_walk"
    elif shape.startswith("intervals"):
        kind = "intervals"
    elif shape == "hill":
        kind = "hills"
    else:
        kind = "tempo" if re.match(r"(?:hard flat \d+|tempo):", m.group("effort")) else "easy"
    lv = int(m.group("level")) if m.group("level") else None
    from training import cardio_menu

    base = (lv - cardio_menu.TEMPO_LEVEL_STEP) if (lv is not None and kind == "tempo") else lv
    return {
        "grammar": "3",
        "machine": m.group("machine"),
        "kind": kind,
        "level": lv,
        "base_level": base,
        "mph": float(m.group("mph") or m.group("walk_mph")) if (m.group("mph") or m.group("walk_mph")) else None,
        "incline_pct": float(m.group("incline")) if m.group("incline") else None,
        "top": float(m.group("incline_top")) if m.group("incline_top") else None,
        "today": False,
    }


def composed_kind(note: str | None) -> str | None:
    """The menu kind a composed note (this module's line 1, either grammar) already carries, or None when it is not one.
    A re-draft keeps it, so recomposing never re-places a block it already placed."""
    facts = read_line1(note)
    return facts["kind"] if facts else None


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


# ── reading a composed note back as its clock (adherence grades against it) ───────────
_RE_TEMPO_CLOCK = re.compile(r"^at min (?P<pts>[\d, and]+), full sentences → one level up, a few words → one down$")
_RE_INTERVAL_CLOCK = re.compile(
    r"^(?:L(?P<hard>\d{1,2})|hard) (?P<work>\d{1,2}) min at min (?P<starts>[\d, ]+); (?:L(?P<easy>\d{1,2})|easy)"
    r" (?:before, between, after|between)\."  # 4.2.0 names the warm-up and cool-down level; 4.1.0's `between` still reads
    r"(?: Full sentences at min \d{1,3} → L\d{1,2} from min \d{1,3}\.)?$"
)
_RE_HILL_CLOCK = re.compile(
    rf"^(?:L(?P<base>\d{{1,2}})|(?P<base_pct>{_N})%|your level) to min (?P<warm>\d{{1,3}})"
    rf" · (?:up a level|\+(?P<step>{_N})%) every (?P<every>\d{{1,2}}) min to min (?P<top>\d{{1,3}})"
    rf" · down the same to min (?P<down>\d{{1,3}})(?: · (?:L\d{{1,2}}|{_N}%|your level) to the end)?$"
)


def _numbers(text: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", text)]


def clock_of(note: str | None, total_min: int | None = None) -> dict[str, Any] | None:
    """The clock a composed note prescribes, as its structured shape (`wrist_clock.resolve`), or None when line 1 is not
    composed (or a legacy note predates the clock rule). `total_min` is the block's own minutes (the set row): the note
    no longer states them, so a hold to the end closes on it."""
    first = _first_line(note)
    legacy = LEGACY_LINE1_RE.match(first)
    if legacy and not LINE1_RE.match(first):
        if not legacy.group("clock"):
            return None
        shape = wrist_clock.parse_rule(legacy.group("clock"))
        if shape is not None:
            shape["total_min"] = int(legacy.group("minutes")) if shape.get("total_min") is None else shape["total_min"]
        return shape
    facts = read_line1(note)
    if not facts:
        return None
    walk = facts.get("incline_pct") is not None
    unit = "%" if walk else "level"
    base: Any = (wrist_clock.num(f"{facts['incline_pct']:g}") if walk else facts.get("level")) or "base"
    clock = _clock_line(note) or ""
    clauses: list[dict[str, Any]]
    if (m := _RE_INTERVAL_CLOCK.match(clock)) is not None:
        starts = _numbers(m.group("starts"))
        work = int(m.group("work"))
        hard: Any = int(m.group("hard")) if m.group("hard") else "base+1"
        easy: Any = int(m.group("easy")) if m.group("easy") else "base"
        every = (starts[1] - starts[0]) if len(starts) > 1 else work * 2
        end = starts[-1] + every
        clauses = [{"type": "hold", "value": easy, "start": 0, "end": starts[0]}]
        clauses.append({"type": "sprint", "value": hard, "work": work, "every": every, "start": starts[0], "end": end})
        if total_min and int(total_min) > end:
            clauses.append({"type": "hold", "value": easy, "start": end, "end": int(total_min)})
    elif (m := _RE_HILL_CLOCK.match(clock)) is not None:
        start_v: Any = (
            int(m.group("base")) if m.group("base") else (wrist_clock.num(m.group("base_pct")) if m.group("base_pct") else "base")
        )
        step = wrist_clock.num(m.group("step")) if m.group("step") else HILL_LEVEL_STEP
        every, warm, top, down = int(m.group("every")), int(m.group("warm")), int(m.group("top")), int(m.group("down"))
        clauses = [
            {"type": "hold", "value": start_v, "start": 0, "end": warm},
            {"type": "ramp", "step": step, "every": every, "start": warm, "end": top},
            {"type": "ramp", "step": -step, "every": every, "start": top, "end": down},
        ]
        if total_min and int(total_min) > down:
            clauses.append({"type": "hold", "value": start_v, "start": down, "end": int(total_min)})
        unit = "%" if m.group("base_pct") else unit
    else:
        clauses = [{"type": "hold", "value": base, "start": 0, "end": int(total_min) if total_min else None}]
        if (m := _RE_TEMPO_CLOCK.match(clock)) is not None:
            pts = _numbers(m.group("pts"))
            clauses.append({"type": "check_in", "every": (pts[1] - pts[0]) if len(pts) > 1 else TEMPO_CHECK_EVERY_MIN})
    for c in clauses:
        c.setdefault("unit", unit)
    shape = wrist_clock.resolve(clauses, total_min)
    shape["status"] = "shaped" if any(c["type"] != "hold" for c in shape["clauses"]) else "steady"
    shape["unit"] = unit
    if not shape["levels"] and total_min is None:
        # an open-ended block (its minutes not passed): the levels it names still read
        named = sorted({v for c in shape["clauses"] for v in [c.get("value")] if isinstance(v, (int, float)) and not isinstance(v, bool)})
        shape.update(levels=named, base_level=named[0] if named else None, top_level=named[-1] if named else None)
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


def performed_shape(note_text: str | None, total_min: int | None = None, machine: str | None = None) -> dict[str, Any]:
    """A performed cardio block's own note as a structured clock shape (#5374; `training_notes.performed_shape`).

    A composed note pasted back is read through `clock_of`; anything else through his note grammar
    (`wrist_clock.parse_note`) and, for a treadmill or a note it does not read, his treadmill grammar
    (`wrist_clock.parse_walk`: "3.3 / 1.5 incline" = 3.3 mph at 1.5% the whole block, "3.3 / 1.5, 4.0 / 3 from 20" =
    a change at min 20). `machine` is the block's movement key or title when the caller has it ("treadmill" lets a bare
    "3 / 1" read as speed / incline; on a bike "8/12" is his level alternation). `total_min` (the block's logged
    duration) closes a clause with no end. Bike shorthand reads too: "Level 11 flat" is level 11 the whole block.
    The 10-25 note (verbatim, the test fixture) reads as three clauses over 60 minutes:
        "8/12 for 2 mins for 20 mins / 8/14 for 2 mins for 20 mins / 8 level up every 2 mins from 40 to 60 to level 18"
    -> alternate 8/12 every 2 min 0–20, alternate 8/14 every 2 min 20–40, +1 level every 2 min 40–60 from 8 to 18.
    Deterministic, no model."""
    if is_composed(note_text):
        composed = clock_of(note_text, total_min)
        if composed is not None:
            return composed
    treadmill = "treadmill" in str(machine or "").lower()
    if treadmill:
        walk = wrist_clock.parse_walk(note_text, total_min, treadmill=True)
        if walk["status"] != "none":
            return walk
    shape = wrist_clock.parse_note(note_text, total_min)
    if shape["status"] != "none":
        return shape
    walk = wrist_clock.parse_walk(note_text, total_min, treadmill=treadmill)
    return walk if walk["status"] != "none" else shape


# ── the levels, from his log ─────────────────────────────────────────────────────────
def steady_level(facts: dict[str, Any] | None) -> int | None:
    """His logged steady level: the median (low) of the levels of his last `STEADY_RIDES` single-level rides
    (`cardio_progression.cardio_facts` `series` — a clock-shaped ride and a prescribed hard ride are never in it, so the
    top of a ramp can never become "the" level, #5399). None when no single-level ride is on record."""
    series = [r for r in (facts or {}).get("series") or [] if isinstance(r.get("level"), int) and not isinstance(r.get("level"), bool)]
    series.sort(key=lambda r: str(r.get("date")))
    recent = [int(r["level"]) for r in series[-STEADY_RIDES:]]
    return int(statistics.median_low(recent)) if recent else None


def prescribed_level(facts: dict[str, Any] | None, verdict: dict[str, Any] | None, *, constrained: bool) -> tuple[int | None, int | None]:
    """(today's level, the level to hold on a yellow/red day). (None, None) when no level is known.

    The base is the last ride's single level; failing that (#5428), his logged steady level; failing that, the top of the
    span his own calibration note called easy ("L9-10 is easy" -> 10). One level up only on a `raise` verdict (his own
    speed at the level clearing his own within-level spread, `cardio_progression.level_verdict`) and never while the
    "no push" gate holds."""
    base = _base_level(facts)[0]
    if base is None:
        return None, None
    base = int(base)
    if not constrained and (verdict or {}).get("verdict") == "raise":
        return base + 1, base
    return base, base


def _base_level(facts: dict[str, Any] | None) -> tuple[int | None, str]:
    """(the base level, where it came from): the last ride's single level (his note's, or — his note silent — the base
    level of the routine he performed, `cardio_progression.prescribed_level_of`, #5076); failing that (#5428 — the last
    ride was clock-shaped, or carried no level), his logged steady level (`steady_level`), so the 10-25 ramp's 8 and 18
    are both ignored and the next easy ride is his usual 11; failing that, the top of the span his own calibration note
    called easy; failing that (#5374), the lowest level of his last (clock-shaped) ride — never its top level."""
    f = facts or {}
    if f.get("last_level") is not None:
        if f.get("last_level_status") == "prescribed_level":
            # #5076: his note was silent, so the level is the one the routine he performed prescribed — stated as that
            return int(f["last_level"]), "the level his last ride's routine prescribed"
        return int(f["last_level"]), "last ride's level"
    steady = steady_level(f)
    if steady is not None:
        return steady, f"his logged steady level (median of his last {STEADY_RIDES} single-level rides)"
    for c in f.get("calibration") or []:
        anchor = (c.get("anchors") or [{}])[0]
        if str(anchor.get("verdict") or "").lower() == "easy" and anchor.get("level_high") is not None:
            return int(anchor["level_high"]), "his calibration note's easy span"
    shaped = f.get("last_shape") or {}
    if shaped.get("base_level") is not None:
        return int(shaped["base_level"]), "the lowest level of his last (clock-shaped) ride"
    return None, "no level on the record"


def _fmt(v: float) -> str:
    return f"{v:g}"


def talk_words(kind: str) -> str:
    """The fixed talk-test words for a kind's effort (`TALK_WORDS`): `cardio_menu.talk_word` — the menu's own talk
    test, failing that its RPE band by the standard's table (4–5 full sentences, 6–7 short phrases, 8 a few words)."""
    from training import cardio_menu

    return cardio_menu.talk_word(kind)


def wire_band(kind: str) -> tuple[int, int]:
    """The RPE band line 1 prints (`cardio_menu.wire_band`: the menu's band clipped to its talk words' row), so the words
    and the number agree — the 2026-10-30 re-grade read "RPE 5–7 (short phrases)" on a hill, where RPE 5 is full
    sentences."""
    from training import cardio_menu

    return cardio_menu.wire_band(kind) or (4, 5)


def effort_text(kind: str) -> str:
    """Line 1's effort: `RPE a–b (talk words)`; intervals `hard RPE n (a few words)`."""
    band = wire_band(kind)
    rpe = f"RPE {band[0]}" if band[0] == band[1] else f"RPE {band[0]}–{band[1]}"
    return f"{'hard ' if kind == 'intervals' else ''}{rpe} ({talk_words(kind)})"


def _times(points: list[int]) -> str:
    """5, 15, 25 -> "5, 15 and 25"."""
    words = [str(p) for p in points]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def interval_plan(total: int) -> dict[str, Any] | None:
    """The menu's interval set laid on the ride clock, centred: {starts, work, every} or None when the block is too short
    for one effort with a 2-min warm-up. 30 min of 5 × 2 min (2 easy) -> efforts at min 6, 10, 14, 18, 22."""
    from training import cardio_menu

    efforts, work, easy = cardio_menu.interval_set()
    period = int(work) + int(easy)
    if period <= 0 or efforts <= 0:
        return None
    n = int(efforts)
    while n > 0 and int(total) - (n * period - int(easy)) < 4:
        n -= 1
    if n <= 0:
        return None
    span = n * period - int(easy)
    warm = max(2, wrist_clock.floor_to_grid((int(total) - span) / 2, 2))
    return {"starts": [warm + i * period for i in range(n)], "work": int(work), "every": period}


def tempo_checks(total: int) -> list[int]:
    """Talk-test check-ins on a tempo ride: min 5, then every 10, none in the last 10 minutes (30 min -> 5, 15)."""
    pts, t = [], TEMPO_FIRST_CHECK_MIN
    while t <= max(TEMPO_FIRST_CHECK_MIN, int(total) - TEMPO_CHECK_EVERY_MIN):
        pts.append(t)
        t += TEMPO_CHECK_EVERY_MIN
    return pts


def _lv(v: Any) -> str:
    return f"L{v}" if isinstance(v, int) else "your level"


def clock_shape(kind: str, minutes: int, dose: dict[str, Any], *, walk: bool) -> tuple[list[dict[str, Any]], str, str | None]:
    """(the clauses, the unit, the ⌚ line or None) of the block (#5374, #5428). The clauses always add up to `minutes`
    and are `wrist_clock`'s structure; the ⌚ line is their phone form (no ⌚ line on an easy ride or the incline walk:
    one level, nothing to watch). `dose` carries `level` (a bike: the dose level), `steady` (his steady level) and, on a
    treadmill, `incline_pct` (the hill's start)."""
    total = int(minutes)
    if walk:
        unit = "%"
        base: Any = wrist_clock.num(f"{float(dose['incline_pct']):g}") if dose.get("incline_pct") is not None else "base"
    else:
        unit = "level"
        base = dose.get("level") if dose.get("level") is not None else "base"
    if kind == "hills":
        from training import cardio_menu

        every = int(cardio_menu.HILL_STEP_MINUTES)
        step: Any = HILL_LEVEL_STEP
        if walk:
            walk_block = cardio_menu.block("incline_treadmill_walk")
            step = wrist_clock.num(f"{float((walk_block.get('step') or {}).get('incline_pct') or 1):g}")
        clauses = wrist_clock.hill(base, step, HILL_WALK_CLIMB_STEPS if walk else HILL_CLIMB_STEPS, every, total)
        if len(clauses) < 3:
            return clauses, unit, None
        warm, top, down = clauses[0]["end"], clauses[1]["end"], clauses[2]["end"]
        start_txt = f"{_fmt(float(base))}%" if walk and not isinstance(base, str) else (_lv(base) if not walk else "your level")
        up = f"+{_fmt(float(step))}%" if walk else "up a level"
        line = f"{start_txt} to min {warm} · {up} every {every} min to min {top} · down the same to min {down}"
        prefix = hevy_note_grammar.WALK_CLOCK_PREFIX if walk else CLOCK_PREFIX
        if down < total and len(prefix) + len(line) + len(f" · {start_txt} to the end") <= CLOCK_LINE_MAX:
            line += f" · {start_txt} to the end"  # left implicit only when it would break the phone budget
        return clauses, unit, line
    if kind == "intervals" and not walk:
        plan = interval_plan(total)
        steady = dose.get("steady")
        easy: Any = (int(steady) - INTERVAL_EASY_STEP) if isinstance(steady, int) else "base"
        hard: Any = (int(steady) + INTERVAL_LEVEL_STEP) if isinstance(steady, int) else f"base+{INTERVAL_LEVEL_STEP}"
        if plan is None:
            return wrist_clock.steady(easy, total)[0], unit, None
        starts, work, every = plan["starts"], plan["work"], plan["every"]
        end = starts[-1] + every
        clauses = [
            {"type": "hold", "value": easy, "start": 0, "end": starts[0]},
            {"type": "sprint", "value": hard, "work": work, "every": every, "start": starts[0], "end": min(end, total)},
        ]
        if end < total:
            clauses.append({"type": "hold", "value": easy, "start": end, "end": total})
        hard_txt = f"L{hard}" if isinstance(hard, int) else "hard"
        easy_txt = f"L{easy}" if isinstance(easy, int) else "easy"
        # re-grade #2: the easy level is named for the warm-up and the cool-down too; the escape is its own line
        # (`interval_escape`), so the talk check reads as the END of rep 1, not a minute that is also the easy start
        line = f"{hard_txt} {work} min at min {', '.join(str(s) for s in starts)}; {easy_txt} {INTERVAL_EASY_WORDS}."
        return clauses, unit, line
    clauses, _every = wrist_clock.steady(base, total)
    if kind == "tempo" and not walk:
        pts = tempo_checks(total)
        clauses = clauses + [{"type": "check_in", "every": TEMPO_CHECK_EVERY_MIN}]
        return clauses, unit, f"at min {_times(pts)}, full sentences → one level up, a few words → one down"
    return clauses, unit, None


INTERVAL_EASY_WORDS = "before, between, after"


def interval_escape(kind: str, dose: dict[str, Any], minutes: int, *, walk: bool) -> str | None:
    """An interval ride's escape line (`hevy_note_grammar.interval_escape_line`): one level over the hard level, checked
    as rep 1 ends; None off a bike interval, with no steady level, or with fewer than two reps (nothing after rep 1)."""
    steady = dose.get("steady")
    if kind != "intervals" or walk or not isinstance(steady, int):
        return None
    plan = interval_plan(int(minutes))
    if plan is None or len(plan["starts"]) < 2:
        return None
    return hevy_note_grammar.interval_escape_line(steady + INTERVAL_LEVEL_STEP + INTERVAL_ESCAPE_STEP)


def levels_text(kind: str, dose: dict[str, Any], *, walk: bool, usual: dict[str, Any] | None = None, top: Any = None) -> str:
    """Line 1's levels: a bike `L11` / `L10/L12` (intervals: easy/hard) / `L11 → L15` (hills); a treadmill
    `[today ]3.0 mph, 8%[ → 12%]`, `today` when the speed or the grade differs from his usual (`usual`, his own log)."""
    if walk:
        mph, inc = dose.get("mph"), dose.get("incline_pct")
        if mph is None or inc is None:
            return "your pace"
        text = f"{float(mph):.1f} mph, {_fmt(float(inc))}%"
        if top is not None and float(top) > float(inc):
            text += f" → {_fmt(float(top))}%"
        if usual and (abs(float(usual["speed_mph"]) - float(mph)) > 0.05 or abs(float(usual["incline_pct"]) - float(inc)) > 0.05):
            text = "today " + text
        return text
    level = dose.get("level")
    if kind == "intervals":
        steady = dose.get("steady")
        if not isinstance(steady, int):
            return "your level"
        return f"L{steady - INTERVAL_EASY_STEP}/L{steady + INTERVAL_LEVEL_STEP}"
    if not isinstance(level, int):
        return "your level"
    if kind == "hills" and isinstance(top, int) and top > level:
        return f"L{level} → L{top}"
    return f"L{level}"


def after_line_needed(exercises: list[Any] | None, index: int) -> bool:
    """True when a non-cardio (Hevy) block follows the cardio block at `index` — the watch's cardio workout has to end
    and Hevy's watch workout restart (owner protocol 2026-10-27)."""
    rest = list(exercises or [])[index + 1 :]  # noqa: E203
    return any(
        not machine_for(str(getattr(ex, "movement_key", "") or (ex.get("movement_key") if isinstance(ex, dict) else ""))) for ex in rest
    )


def with_after(note: str | None, followed: bool) -> str:
    """`note` with exactly one `After:` line at its end when `followed`, and none when not (idempotent)."""
    lines = [ln for ln in (note or "").rstrip().split("\n") if ln.strip() != AFTER_LINE]
    while lines and not lines[-1].strip():
        lines.pop()
    if followed:
        lines.append(AFTER_LINE)
    return "\n".join(lines)


def apply_after_lines(exercises: list[Any] | None) -> int:
    """Stamp (or remove) the `After:` line on every COMPOSED cardio note by the list's current order. Idempotent; call it
    after any pass that reorders, swaps or appends blocks. Returns how many notes changed."""
    exs = list(exercises or [])
    changed = 0
    for i, ex in enumerate(exs):
        key = str(getattr(ex, "movement_key", "") or "")
        note = getattr(ex, "notes", None)
        if not machine_for(key) or not note or not LINE1_RE.match(_first_line(note)):
            continue
        new = with_after(note, after_line_needed(exs, i))
        if new != note:
            ex.notes = new
            changed += 1
    return changed


def usual_walk(sessions: list[dict[str, Any]] | None, n: int = 3) -> dict[str, Any] | None:
    """His usual treadmill speed and grade: over his last `n` treadmill notes his own grammar reads
    (`wrist_clock.parse_walk`), the median (low) speed and the median (low) grade of their first segments. None when
    no note of his reads."""
    from training import cardio_menu

    walks = [w for w in (cardio_menu.walk_dose_of(s) for s in sessions or []) if w and w.get("from_note")][:n]
    if not walks:
        return None
    return {
        "speed_mph": statistics.median_low([float(w["mph"]) for w in walks]),
        "incline_pct": statistics.median_low([float(w["incline_pct"]) for w in walks]),
        "steepest_pct": max(float(w["incline_pct"]) for w in walks),
        "n": len(walks),
        "dates": [w["date"] for w in walks],
    }


def steepest_walk(sessions: list[dict[str, Any]] | None) -> float | None:
    """The steepest grade on any treadmill walk of his on record (his note's, `cardio_menu.walk_dose_of`), or None."""
    from training import cardio_menu

    grades = [float(w["incline_pct"]) for w in (cardio_menu.walk_dose_of(s) for s in sessions or []) if w]
    return max(grades) if grades else None


_ROUTE_WHY_RE = re.compile(r"^[A-Z][^:\n]{1,40}: [^\n]+\.$")
_ROUTE_WORD = re.compile(r"\b(?:bike|treadmill|rower|elliptical|walk|feet|foot|legs|knees?|seated)\b", re.IGNORECASE)


def route_why_of(note: str | None) -> str | None:
    """A route choice an author wrote into the note ("Bike, not treadmill: rest the feet.") — the one why that stays on
    the wire (standard §6.5: a route chosen for an injury keeps its one-line why). Any line but line 1, the ⌚ line and
    the After line, ≤ `ROUTE_WHY_MAX` characters, "<choice>: <reason>." naming a machine or a body part; else None."""
    lines = (note or "").strip().split("\n")
    for ln in lines[1:] if is_composed(note) else lines:
        ln = ln.strip()
        if not ln or ln.startswith(CLOCK_PREFIXES) or ln == AFTER_LINE or len(ln) > ROUTE_WHY_MAX:
            continue
        if _ROUTE_WHY_RE.match(ln) and _ROUTE_WORD.search(ln.split(":", 1)[0] + " " + ln.split(":", 1)[1]):
            return ln
    return None


def why_sentence(movement_key: str, archetype: Any, aerobic_block: dict[str, Any] | None) -> str:
    """The route's why, for the audit (it no longer reaches the wire on a generated note, #5428)."""
    from training import cardio_menu

    seated = movement_key in BIKES or movement_key in ("rowing_machine", "elliptical")
    block = aerobic_block or {}
    if block.get("state") != "read":
        return "Seated, so the feet rest." if seated else ""
    if seated:
        if cardio_menu.is_lower(archetype):
            return "Seated, so the legs keep today's lifting as their work."
        return "Seated, so the feet rest."
    return "On your feet today: the legs are fresh."


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
    followed: bool = False,
    route_why: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """(the note, the audit). Line 1 matches `LINE1_RE`; the ⌚ line rides tempo / hills / intervals; `route_why` (a
    chat author's route choice, ≤ `ROUTE_WHY_MAX` characters, e.g. "Bike, not treadmill: rest the feet.") is the only
    why that reaches the wire; `followed` adds the `After:` line (a Hevy block follows this one).

    `kind` is the menu block (`cardio_menu.choose_kind`); None = the machine's easy kind. `constraint` is the active
    standing constraint (`standing_constraints.active_constraint`), None when there is none; its "no push" half (before
    2026-10-18) still holds a hard kind easy. `hr_ceiling_bpm` and `recovery_band` are accepted for the callers and
    never printed: RPE and the talk test lead, no HR target (standard §3.7). `previous` is
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
    usual = None
    steepest = None
    if is_walk:
        dose = dict(cardio_menu.treadmill_dose(treadmill_sessions))
        usual = usual_walk(treadmill_sessions)
        steepest = steepest_walk(treadmill_sessions)
        if kind == "hills" and steepest is not None and dose.get("incline_pct") is not None and steepest < float(dose["incline_pct"]):
            # #5428: a hill starts no steeper than the steepest grade he has walked
            dose["hill_start_basis"] = (
                f"his steepest logged grade {_fmt(steepest)}% (the menu's start is {_fmt(float(dose['incline_pct']))}%)"
            )
            dose["incline_pct"] = steepest
    else:
        dose = dict(cardio_menu.bike_dose(kind, facts, verdict, constrained=gate))
    clauses, unit, clock_line = clock_shape(kind, int(minutes), dose, walk=is_walk)
    shape = wrist_clock.resolve([dict(c, unit=unit) for c in clauses], int(minutes))
    top = shape.get("top_level") if kind == "hills" else None
    first = f"{machine} · {levels_text(kind, dose, walk=is_walk, usual=usual, top=top)} · {effort_text(kind)}"
    lines = [first]
    if clock_line:
        lines.append(hevy_note_grammar.clock_line(clock_line, machine))
    escape = interval_escape(kind, dose, int(minutes), walk=is_walk)
    if escape:
        lines.append(escape)
    why_wire = (route_why or "").strip()
    if why_wire and len(why_wire) <= ROUTE_WHY_MAX:
        lines.append(why_wire)
    note = with_after("\n".join(lines), followed)
    from training import recent_aerobic

    off = cardio_menu.off_default(kind, movement_key, recent_aerobic.legs_loaded(aerobic_block)[0], previous)
    audit = {
        "version": CARDIO_NOTE_VERSION,
        "charter_version": _charter_version(),
        "kind": kind,
        "requested_kind": requested,
        "placement_why": placement_why,
        # #5076: why this is not the default incline walk, and the charter key that makes it so (None = the default)
        "off_default": off,
        "why": (off or {}).get("reason") or why_sentence(movement_key, archetype, aerobic_block) or None,
        "shape": KIND_SHAPE.get(kind, "flat"),
        "level": dose.get("level"),
        "steady_level": dose.get("steady"),
        "hold_level": dose.get("hold_level"),
        "mph": dose.get("mph"),
        "incline_pct": dose.get("incline_pct"),
        "usual_walk": usual,
        "today": bool(usual) and first.split(" · ")[1].startswith("today "),
        "dose_reason": dose.get("reason") or None,
        "hill_start_basis": dose.get("hill_start_basis"),
        "level_basis": dose.get("basis") if is_walk else _base_level(facts)[1],
        "verdict": _verdict_word(verdict, dose, is_walk),
        "rpe": list(cardio_menu.rpe_band(kind) or ()),
        "rpe_on_wire": list(wire_band(kind)),  # #5428: the menu band clipped to its talk words' row
        "minutes": int(minutes),
        "followed": bool(followed),
        # #5374: the clock as he runs it from his wrist, and its structure (adherence grades against it)
        "clock_rule": clock_line,
        "interval_escape": escape,
        "clock": {k: shape.get(k) for k in ("family", "total_min", "change_points", "levels", "unit")},
        "clock_off_grid": wrist_clock.off_grid(shape),
        "clock_numbers": wrist_clock.numbers_to_remember(shape),
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
