"""
hevy_note_grammar.py — the words, line shapes and budgets of a Hevy routine note (#5428).

The machine half of `docs/coaching/HEVY_NOTE_STANDARD.md`. Every producer that writes text into a
routine's Pinned Routine Note (`routine.exercises[].notes`) builds its lines from here, and
`training.hevy_note_lint` checks the compiled wire against the same constants, so the writer and
the checker cannot drift apart.

What a note is FOR (standard §1): Hevy already shows, per set row, the prescribed load × reps and
the PREVIOUS column, and it shows every note in full. So a note never restates the rows. A lift
note is the effort first, then at most one reason and one cue. Exercise 1's note opens with the
three-line session block. Length is scroll, so budgets are counted in phone lines.

Owner rulings this module encodes (dated in the standard §0):
  * 2026-10-27 R1/R2, then 2026-10-27 ~04:50Z: no medical, ECG or safety text on the wire. The
    session block is the session line, the low-energy option and the load rule — nothing else.
  * 2026-10-27 R3: the load rule (+10 lb at RPE <= 7, +5 lb at RPE 8, +5 max under 40 lb, once).
  * 2026-10-27 ~04:50Z: warm-up text is at most one prep-movement cue per compound family (the
    #5049 table: band pull-aparts / hip hinges / ankle and hip mobility). No general warm-up block.

Pure apart from one cached charter read at import (the load step in LOAD_RULE_LINE, the way routine_title reads
the compounds band); no clock.
"""

from __future__ import annotations

import re
from typing import Optional, Union

GRAMMAR_VERSION = "hevy-note-grammar@1.3.0"  # 1.1.0: re-grade #2; 1.2.0: re-grade #3; 1.3.0: re-grade #4 (see each builder)

Rpe = Union[float, int, tuple[float, float], list[float]]

# ── budgets (standard §7), in phone lines ───────────────────────────────────────────────────────────────────────────
# PHONE_CHARS is an INFERENCE (a conservative ~6.1-inch phone line); one screenshot of the next committed routine
# calibrates it. The test that stays true either way: exercise 1's first set row is on the first screen.
PHONE_CHARS = 40
SESSION_LINE_MAX_CHARS = 60
SESSION_BLOCK_MAX_LINES = 7
EX1_MAX_LINES = 11
LIFT_MAX_LINES = 4
CARDIO_MAX_LINES = 6
# #5428 re-grade #4: an interval ride's two-way escape (full sentences up; can't talk → shorter reps at the same level) is
# two phone lines; with line 1, the clock and the After line that is 7. Every other cardio note keeps 6.
CARDIO_INTERVAL_MAX_LINES = 7
CARDIO_LINE1_MAX_CHARS = 80
CARDIO_NOTE_MAX_CHARS = 240
CLOCK_LINE_MAX_CHARS = 110
AFTER_LINE_MAX_CHARS = 40
MOBILITY_MAX_LINES = 2
LINE_MAX_CHARS = 120  # no single line longer than three phone lines
ROUTINE_TOTAL_MAX_CHARS = 1600
CLOCK_MAX_LEVELS = 3


def phone_lines(text: str) -> int:
    """How many phone lines `text` wraps to at PHONE_CHARS per line (an empty line still costs one)."""
    return sum(max(1, -(-len(ln) // PHONE_CHARS)) for ln in (text or "").split("\n"))


# ── the session block (standard §3.1) ───────────────────────────────────────────────────────────────────────────────
SESSION_DAYS = (
    "Upper volume",
    "Upper heavy",
    "Lower volume",
    "Lower heavy",
    "Shoulders + arms",
    "Full body",
    "Minimum",
    "Travel",
)
# owner ruling 2026-10-27 ~04:50Z ("yes add it back"): the low-energy option returns as one line.
LOW_ENERGY_LINE = "Low energy → first 2 lifts + easy cardio."
# #5428 re-grade #2 (2026-10-31): a session whose only cardio is a hard kind (intervals, tempo, hills) has no easy cardio
# to fall back on, so the line names the change instead of promising a block that is not there.
LOW_ENERGY_HARD_CARDIO_LINE = "Low energy → first 2 lifts + cardio, no hard efforts."
LOW_ENERGY_LINES = (LOW_ENERGY_LINE, LOW_ENERGY_HARD_CARDIO_LINE)
HARD_CARDIO_KINDS = ("tempo", "hills", "intervals")  # `cardio_menu.HARD`


def low_energy_line(cardio_kinds: Optional[list[str]] = None) -> str:
    """Session line 2: the hard-cardio form when the session's cardio blocks are ALL hard kinds, else the ruled line."""
    kinds = [k for k in (cardio_kinds or []) if k]
    return LOW_ENERGY_HARD_CARDIO_LINE if kinds and all(k in HARD_CARDIO_KINDS for k in kinds) else LOW_ENERGY_LINE


TEST_DAY = "Test"
# R3's small-load safeguard: under this load a lift moves one step at most (two steps on a 15 lb raise is +67 %).
SMALL_LOAD_LB = 40


# R3's one-step band. #5428 re-grade #2 (2026-10-31): the rule said "RPE 7 or less" and "at RPE 8", so RPE 7.5 and 8.5 —
# his PREVIOUS on three lifts that day — fell in neither branch. The one-step branch now runs to the top of the band
# under it: everything up to 8.5 moves, RPE 9 holds.
ONE_STEP_RPE = (7.5, 8.5)
LOAD_RULE_HEAD = "Top reps at RPE 7 or less → "


OTHER_LIFTS_HEAD = "Other lifts: top reps at RPE 7 or less → "
# #5428 re-grade #5 (2026-10-31): "Under 40 lb: +5 lb max" was two steps on a 30-lb dumbbell (§5's step there is 2.5 lb)
# and said nothing when a lift is both a stack and under 40 lb. "One step" is §5's table's step for that implement, and a
# stack's next plate wins at any load.
LOAD_RULE_LIMITS = f"Under {SMALL_LOAD_LB} lb: one step. Stack: next plate at any load. Once per lift."


def load_rule_line(step_lb: Optional[float], *, other_lifts: bool = False) -> str:
    """The load rule (owner ruling 2026-10-27 R3): two load steps when the top reps land at RPE <= 7, one step at RPE
    7.5–8.5, one step at most under SMALL_LOAD_LB, once per lift. The step is the charter's
    (`progression.gain_rule.step_lb`), so the line moves with it.

    TWO lines, newline-joined (#5428 re-grade #3: the one-line form was five clauses with a unitless "+5"): the if/then,
    then the limits. Every step carries its unit; no "per hand" (a step adds to the row, and a dumbbell row is already
    per hand); a stack has no fixed step (§5), so its step is the next plate.

    `other_lifts` (re-grade #4, 2026-10-31): a one-set exercise 1 has no later set to step, but the rule must still reach
    the session's multi-set lifts — removing it left the routine with no in-session rule at all. So the block keeps it,
    addressed to them: `Other lifts: top reps …` (`rule_mode`)."""
    lo, hi = fmt_num(ONE_STEP_RPE[0]), fmt_num(ONE_STEP_RPE[1])
    head = OTHER_LIFTS_HEAD if other_lifts else LOAD_RULE_HEAD
    if not step_lb:
        first = f"{head}2 steps on later sets; {lo}–{hi} → 1 step."
        return first + f"\n{LOAD_RULE_LIMITS}"
    one, two = fmt_num(step_lb), fmt_num(2 * step_lb)
    first = f"{head}+{two} lb on later sets; {lo}–{hi} → +{one} lb."
    return first + f"\n{LOAD_RULE_LIMITS}"


def rule_fits(working_sets: int) -> bool:
    """Exercise 1 itself has a later set to step (#5428 re-grade #3)."""
    return int(working_sets or 0) >= 2


def rule_mode(ex1_working_sets: int, others_multi: bool = True) -> Optional[str]:
    """Which load rule the block carries (re-grade #4): `ex1` (exercise 1 has 2+ working sets: the rule as written),
    `others` (exercise 1 has one, another lift has 2+: `Other lifts: …`), or None (no lift in the session can step)."""
    if rule_fits(ex1_working_sets):
        return "ex1"
    return "others" if others_multi else None


def charter_step_lb() -> Optional[float]:
    """The charter's load step (cached charter read; None when the charter does not name one)."""
    from training.training_charter import charter_value

    v = charter_value("progression.gain_rule.step_lb")
    return float(v) if v else None


def fmt_num(v: float) -> str:
    """8.0 -> '8', 8.5 -> '8.5'."""
    return f"{float(v):g}"


def fmt_rpe(rpe: Rpe) -> str:
    """8 -> '8'; (8, 9) or [8, 9] -> '8–9' (en dash, the standard's range mark)."""
    if isinstance(rpe, (tuple, list)):
        lo, hi = rpe[0], rpe[-1]
        return fmt_num(lo) if float(lo) == float(hi) else f"{fmt_num(lo)}–{fmt_num(hi)}"
    return fmt_num(rpe)


def session_line(day: str, big_lift_rpe: Rpe) -> str:
    """Line 1 of exercise 1: `‹Day› · RPE a–b on big lifts`. `day` must be one of SESSION_DAYS."""
    if day not in SESSION_DAYS:
        raise ValueError(f"session day {day!r} is not one of {SESSION_DAYS}")
    return f"{day} · RPE {fmt_rpe(big_lift_rpe)} on big lifts"


def fitness_test_line(protocol: str) -> str:
    """A fitness-test day's line 1: `Test · ‹protocol›`."""
    return f"{TEST_DAY} · {protocol}"


# owner ruling 2026-10-27 R3, with the panel's two safeguards (one step max on a small load; RPE 8 is never a band top)
LOAD_RULE_LINE = load_rule_line(charter_step_lb())


LOAD_RULE_LINES = tuple(LOAD_RULE_LINE.split("\n"))
OTHER_LIFTS_RULE_LINES = tuple(load_rule_line(charter_step_lb(), other_lifts=True).split("\n"))


def rule_lines(mode: Optional[str]) -> list[str]:
    return list(LOAD_RULE_LINES) if mode == "ex1" else list(OTHER_LIFTS_RULE_LINES) if mode == "others" else []


def session_block(
    day: str, big_lift_rpe: Rpe, cardio_kinds: Optional[list[str]] = None, ex1_working_sets: int = 2, others_multi: bool = True
) -> str:
    """The block that heads exercise 1 (followed by a blank line, then exercise 1's own note): the session line, the
    low-energy line, then the load rule's two lines in the form `rule_mode` picks."""
    head = [session_line(day, big_lift_rpe), low_energy_line(cardio_kinds)]
    return "\n".join(head + rule_lines(rule_mode(ex1_working_sets, others_multi)))


# ── lift notes (standard §3.2–3.4) ──────────────────────────────────────────────────────────────────────────────────
def effort_line(rpe: Rpe, last_set_rpe: Optional[Rpe] = None) -> str:
    """Line 1 of every lift note: `RPE a–b[, last set RPE c–d]`."""
    out = f"RPE {fmt_rpe(rpe)}"
    return f"{out}, last set RPE {fmt_rpe(last_set_rpe)}" if last_set_rpe is not None else out


PICK_LOAD_W_REPS = 8


# #5428 re-grade #2 (2026-10-31): "find the load" over working rows that carry the engine's start load read as "ignore the
# rows". With a load on the rows the feeler checks THAT load; "find" is kept only where the rows carry none (a chat draft).
PICK_LOAD_FIXED_TAIL = "test the load."  # 40 chars with its head: one phone line, as "find the load." was
PICK_LOAD_OPEN_TAIL = "find the load."


# re-grade #4 (2026-10-31): "test the load." gave the test no result — the W line now says what the answer does. RPE 5 is
# the top of the talk table's "full sentences" row: a start load that easy is a step light.
PICK_LOAD_EASY_RPE = 5


def pick_load_line(w_reps: int = PICK_LOAD_W_REPS, *, rows_loaded: bool = True, step_text: Optional[str] = None) -> str:
    """The pick-load form's W line (no history, or stale history). Over loaded rows the feeler W row is AT the start load
    and the line is its result rule: `W set at RPE 5 or less → next plate.` (`step_text`: the lift's one step — a stack's
    next plate, a fixed implement's `+5 lb[ per hand]`); over unloaded rows (a chat draft, a no-load W row of `w_reps`):
    `W set: up to 8 easy reps, find the load.`"""
    if not rows_loaded:
        return f"W set: up to {w_reps} easy reps, {PICK_LOAD_OPEN_TAIL}"
    del step_text  # re-grade #5: "one step" (§5's step for the implement; a stack's next plate), not a typed number
    return f"W at RPE {PICK_LOAD_EASY_RPE} or less → one step, no more."


# the feeler W row carries the start load itself (it IS the test of that load), so the line is the result rule alone —
# one phone line, so a lift with a reason and its family cue stays inside 4. Re-grade #5: "no more" — the feeler's step
# IS the lift's once ("Once per lift"); "next plate" alone left a second step open on a lift last done years ago.
PICK_LOAD_RESULT_RE = re.compile(r"^W at RPE \d+ or less → one step, no more\.$")


def gap_text(days: Union[int, float, str, None]) -> Optional[str]:
    """A layoff in his words: `10 days` (7–13), `5 weeks` (to 26 weeks), `17 months` (to 2 years), `3 years`; None under
    7 days or when the gap is unknown. Weeks past half a year read as months: "first time in 76 weeks" is a sum."""
    if days is None:
        return None
    try:
        d = int(float(days))
    except (TypeError, ValueError):
        return None
    if d < 7:
        return None
    if d < 14:
        return f"{d} days"
    if d < 183:
        return f"{round(d / 7)} weeks"
    if d < 730:
        return f"{round(d / 30.44)} months"
    return f"{d // 365} years"


def sets_today_clause(n: int, why: str) -> str:
    """A critic's changed set count, checked against the working rows: `2 sets today: first incline in 5 weeks.`"""
    why = why.strip().rstrip(".")
    return f"{n} sets today: {why}."


# The reason words. A reason never repeats a number the rows already show.
HEAVIER = "Heavier"
LIGHTER = "Lighter"
VOLUME_DAY = "Volume day"
NOW_AIMING = "Now aiming"
NO_JUMPS = "No jumps"
# #5428 (owner ruling 2026-10-30): the same load as a PREVIOUS that ran to RPE 10, prescribed inside the band, says why
SAME_LOAD = "Same load"
SAME_LOAD_LINE = f"{SAME_LOAD}: aim to leave one more rep."
SAME_LOAD_FROM_RPE = 10.0
# #5428 re-grade #2 (2026-10-31): a held load after a PREVIOUS that reached the top of its rep range at RPE <= 8.5 read as
# "never progresses" (the reverse fly at 60 x 15 @ 8.5, the pushdown at 50 x 15 @ 8.5). The gain rule wants the top of the
# range twice in a row, and the load rule moves it in-session at RPE <= 8.5, so the note says what moves it.
HELD_TOP_MAX_RPE = 8.5


def _step_text(lb: Union[int, float], per_hand: bool) -> str:
    return f"+{fmt_num(lb)} lb" + (" per hand" if per_hand else "")


def held_top_line(
    rep_hi: Union[int, float],
    *,
    working_sets: int = 2,
    row_lb: Optional[float] = None,
    stack: bool = False,
    per_hand: bool = False,
    step_lb: Optional[float] = None,
    next_step_lb: Optional[float] = None,
    small_step_lb: Optional[float] = None,
) -> str:
    """A held load whose PREVIOUS reached the top of the range at RPE <= 8.5 (#5428): ONE timeline, the load rule's.

    Re-grade #3: the reason IS the load rule applied to this lift's set 1, in its implement's step (a stack: the next
    plate; under SMALL_LOAD_LB: one step; else two steps at RPE 7 or less, one at 7.5–8.5). Re-grade #4: it names its
    timeline in the rule's own words ("on later sets" — today) and opens on set 1, not "Same load to start"; a one-set
    lift has no later set, so it names the gain rule's step "next session" (`next_step_lb`)."""
    hi = fmt_num(rep_hi)
    if int(working_sets or 0) < 2:
        return f"{SAME_LOAD}: {hi} reps again → {_step_text(next_step_lb or step_lb or 5, per_hand)} next session."
    lo_rpe, hi_rpe = fmt_num(ONE_STEP_RPE[0]), fmt_num(ONE_STEP_RPE[1])
    one = float(step_lb or 5)
    head = f"{SET_1_HEAD}{hi} reps at RPE"
    if stack:
        return f"{head} {hi_rpe} or less → next plate on later sets."
    if row_lb is not None and float(row_lb) < SMALL_LOAD_LB:
        # under 40 lb: ONE step of the implement's own size (§5: 2.5 lb on a dumbbell under 50) — re-grade #5
        return f"{head} {hi_rpe} or less → {_step_text(small_step_lb or one, per_hand)} on later sets."
    return f"{head} 7 or less → {_step_text(2 * one, per_hand)} on later sets; {lo_rpe}–{hi_rpe} → {_step_text(one, per_hand)}."


SET_1_HEAD = "Set 1: "


# what a held-top reason must read as (lint L4): the in-session step on set 1, or the next-session step on a one-set lift
HELD_TOP_RE = re.compile(r"^(?:Set 1: \d+ reps at RPE .* on later sets|Same load: \d+ reps again → .* next session\.)")
# #5428 re-grade #3: a one-set exercise 1 carries no load rule (nothing to step today), so its note names the gain rule's
# next-session step instead — the live branch on the lift that most needs one
ONE_SET_HEAD = "One set: "


def one_set_line(rep_hi: Union[int, float], ceiling_rpe: Union[int, float], next_step_lb: float, per_hand: bool) -> str:
    """`One set: 10 reps at RPE 9 or less two sessions running → +5 lb per hand.` (the charter's gain rule: the top of
    the range on two consecutive same-type exposures, at or under the effort ceiling)."""
    return f"{ONE_SET_HEAD}{fmt_num(rep_hi)} reps at RPE {fmt_num(ceiling_rpe)} or less two sessions running → {_step_text(next_step_lb, per_hand)}."


def stale_reason_line(word: str, gap: Optional[str]) -> str:
    """A stale PREVIOUS (§3.3) more than one step from the row: `Lighter: first time in 2 years.` (`gap_text`), never
    `New: replaces …`, which is only for a lift with no PREVIOUS at all."""
    return f"{word}: first time in {gap}." if gap else f"{word}: back after a break."


# #5083/#5075: a rotated accessory's one reason — the exercise it stands in for, by its Hevy title
ROTATION_HEAD = "New: replaces "
# #5057 on the chat path: a stall-rule load step the author's rows did not take, named as a delta
STEP_DUE_HEAD = "Step due: +"
REASON_RE = re.compile(
    r"^(?:Heavier: |Lighter: |Volume day: |Now aiming \d+–\d+: |No jumps(?: today)?: |Set \d over RPE \d+(?:\.5)? → |\d+ sets? today[:.]"
    r"|New: replaces |Step due: \+|Same load(?: to start)?: |One set: |Set 1: \d+ reps at RPE "
    # a critic's applied load / rep change (`session_block.applied_clause`) is a reason too (standard §3.2's list, §3.8)
    r"|(?:Lighter|Heavier|Fewer reps) today[:.])"
)


def back_off_line(pct: int) -> str:
    """A minimum / travel lift's one instruction (§3.8): the session carries no loads, so the rows cannot show that the
    back-off is lighter than the top set. `Top set, then one back-off 10% lighter.`"""
    return f"Top set, then one back-off {int(pct)}% lighter."


def rotation_line(replaced_title: str) -> str:
    """`New: replaces Calf Press.` — never a slot id, a week count or an issue number (those stay in the rationale)."""
    return f"{ROTATION_HEAD}{str(replaced_title).strip().rstrip('.')}."


def reason_line(word: str, why: str) -> str:
    """`Heavier: 15 reps was RPE 7.` — word is HEAVIER / LIGHTER / VOLUME_DAY / NO_JUMPS."""
    why = why.strip().rstrip(".")
    return f"{word}: {why}."


# Hevy's PREVIOUS column vs the prescribed row: more than one implement step away needs a reason.
def delta_word(row_lb: Optional[float], previous_lb: Optional[float], step_lb: Optional[float]) -> Optional[str]:
    """'Heavier' / 'Lighter' when the row is more than one step from PREVIOUS, else None (no reason needed). A load with
    no fixed step (a stack) is never judged."""
    if row_lb is None or previous_lb is None or not step_lb or step_lb <= 0:
        return None
    diff = float(row_lb) - float(previous_lb)
    if diff > step_lb + 1e-6:
        return HEAVIER
    if -diff > step_lb + 1e-6:
        return LIGHTER
    return None


# ── implements and loadable steps (standard §5) ─────────────────────────────────────────────────────────────────────
KINDS = ("barbell", "dumbbell", "machine", "cable", "bodyweight", "carry", "cardio", "mobility", "other")
PER_HAND_KINDS = ("dumbbell", "carry")
DB_BIG_STEP_FROM_LB = 50.0
WARMUP_ROUNDING_LB = 5.0  # W rows round to 5 lb on a bar or a dumbbell (standard §3.4)


def implement_step_lb(kind: str, lb: Optional[float] = None) -> Optional[float]:
    """The loadable step: barbell 5; dumbbell 5 at >= 50 lb per hand, 2.5 below; plate machine 5. Stack and cable
    loads are 'a value he has logged on that machine', which has no fixed step, so None (not checked)."""
    if kind == "barbell":
        return 5.0
    if kind == "dumbbell":
        return 5.0 if (lb or 0) >= DB_BIG_STEP_FROM_LB else 2.5
    if kind == "machine":
        return 5.0
    return None


def on_step(lb: float, step: float) -> bool:
    q = float(lb) / step
    return abs(q - round(q)) < 0.02


# ── carry (standard §3.5) ───────────────────────────────────────────────────────────────────────────────────────────
def carry_line1(rpe: Rpe, start_lb: Optional[float] = None) -> str:
    """`RPE 8–9 · 60 lb per hand to start` when his last carry load is known (#5428 re-grade #3: "pick the load" gave no
    number to start from), else `RPE 8–9 · pick the load per hand`."""
    if start_lb:
        return f"RPE {fmt_rpe(rpe)} · {fmt_num(start_lb)} lb per hand to start"
    return f"RPE {fmt_rpe(rpe)} · pick the load per hand"


def carry_adjust_line(step_lb: Optional[float]) -> str:
    """The carry's one adjust rule after set 1 (re-grade #3): `Set 1 at RPE 7 or less: +10 lb per hand.` — two steps,
    the load rule's RPE <= 7 branch; anything harder stays."""
    return f"Set 1 at RPE 7 or less: {_step_text(2 * float(step_lb or 5), True)}."


CARRY_ADJUST_RE = re.compile(r"^Set 1 at RPE \d+(?:\.5)? or less: \+\d+(?:\.5)? lb per hand\.$")


CARRY_CUE = "Tall, ribs down, bells off your legs."
CARRY_STEPS_LINE = "Steps go in the yards box."
# #5428 re-grade #2 (2026-10-31): a carry row's distance is his STEP COUNT (owner 2026-10-25, #5373): the number the
# routine writes is the number his yards box shows (Hevy passes it through unconverted — his own logged carries read back
# as whole numbers, 50 / 60 / 60 on 2026-10-25). So a carry row is a whole number of steps and the note names no metres.
CARRY_METRE_RE = re.compile(r"\bmet(?:re|er)s?\b|\b\d+(?:\.\d+)? ?m\b", re.I)

# ── cardio (standard §3.7) ──────────────────────────────────────────────────────────────────────────────────────────
CARDIO_MACHINES = ("Recumbent", "Upright bike", "Treadmill", "Elliptical", "Rower", "Air bike")
SPEED_MACHINES = ("Treadmill",)  # speed is a setting only on the treadmill; elsewhere it is an output
# talk-test words per effort (the words lead; HR is not a lead target until his zones are re-baselined)
TALK_WORDS: dict[str, tuple[float, float]] = {
    "full sentences": (4, 5),
    "short phrases": (6, 7),
    "a few words": (8, 8),
}
CLOCK_PREFIX = "⌚ ride clock: "
# #5428 re-grade (2026-10-30): "ride clock" on a treadmill walk. The clock is the same watch clock, read from 0; the
# treadmill's line names the walk (standard §3.7, the clock rule).
WALK_CLOCK_PREFIX = "⌚ walk clock: "
CLOCK_PREFIXES = (CLOCK_PREFIX, WALK_CLOCK_PREFIX)
AFTER_LINE = "After: end watch cardio, restart Hevy."
# #5428 re-grade #2 (2026-10-31), §3.7 intervals: the talk check lands at the END of a hard rep (not a bare minute that is
# also where the easy minutes start), and the escape is one level.
INTERVAL_ESCAPE_STEP = 1


def interval_escape_line(up_level: int, hard_level: int) -> str:
    """`As rep 1 ends: full sentences → L13; can't talk → 1 min at L12.` — the talk check as rep 1 ends: full sentences
    (too easy) one level up; "a few words" is the target (line 1); can't talk (too hard) shortens the hard reps to 1 min
    at the SAME hard level — never below it (re-grade #4: `none → L11` was a non-standard word and dropped the reps to
    the recovery level, cancelling the intervals). Two phone lines."""
    return f"As rep 1 ends: full sentences → L{int(up_level)}; can't talk → 1 min at L{int(hard_level)}."


INTERVAL_ESCAPE_RE = re.compile(r"^As rep 1 ends: full sentences → L(?P<up>\d+); can't talk → 1 min at L(?P<hard>\d+)\.$")
# the easy minutes' talk words on the interval clock (warm-up, recoveries, cool-down: his steady level)
INTERVAL_EASY_TALK = "full sentences"


def clock_prefix_for(machine: str) -> str:
    """The ⌚ line's head for a cardio machine: `walk clock` on the treadmill, `ride clock` on every other machine."""
    return WALK_CLOCK_PREFIX if machine in SPEED_MACHINES else CLOCK_PREFIX


def is_clock_line(line: str) -> bool:
    return line.startswith(CLOCK_PREFIXES)


def _band_of(rpe: Rpe) -> tuple[float, float]:
    if isinstance(rpe, (tuple, list)):
        return float(rpe[0]), float(rpe[-1])
    return float(rpe), float(rpe)


def talk_words_for(rpe: Rpe) -> str:
    """The fixed talk-test words for an RPE or a band (standard §3.7's table): the row the band sits inside; a band that
    straddles two rows takes the row it overlaps most (ties: the easier row). Was "the top of a range decides", which
    labelled an RPE 5–7 band "short phrases" though RPE 5 is full sentences (the 2026-10-30 re-grade)."""
    lo, hi = _band_of(rpe)
    best, best_overlap = None, -1.0
    for words, (a, b) in TALK_WORDS.items():
        overlap = min(hi, b) - max(lo, a) + 1  # whole RPE points shared with the row
        if overlap > best_overlap:
            best, best_overlap = words, overlap
    if best_overlap <= 0:  # outside the table: under 4 is full sentences, over 8 a few words
        return "full sentences" if hi < 4 else "a few words"
    return str(best)


def _talk_row(words: str) -> tuple[float, float]:
    """The words' row of the table, open at the ends: full sentences is RPE 5 or less, a few words RPE 8 or more."""
    a, b = TALK_WORDS[words]
    words_order = list(TALK_WORDS)
    return (0.0 if words == words_order[0] else float(a)), (10.0 if words == words_order[-1] else float(b))


def talk_band(rpe: Rpe, words: str) -> tuple[float, float]:
    """The band line 1 prints beside `words`: the menu's band clipped to the words' row of the table, so the talk test
    and the RPE always agree (hills 5–7 with "short phrases on the climbs" -> 6–7; the incline walk 4–6 with "full
    sentences" -> 4–5, the standard's own treadmill example). A band wholly outside the row keeps the row."""
    lo, hi = _band_of(rpe)
    a, b = _talk_row(words)
    clipped = (max(lo, a), min(hi, b))
    return clipped if clipped[0] <= clipped[1] else (float(TALK_WORDS[words][0]), float(TALK_WORDS[words][1]))


def talk_agrees(rpe: Rpe, words: str) -> bool:
    """True when the RPE (or band) sits inside the talk words' row (lint L3 on cardio line 1)."""
    if words not in TALK_WORDS:
        return False
    lo, hi = _band_of(rpe)
    a, b = _talk_row(words)
    return a <= lo and hi <= b


def cardio_line1(machine: str, levels: str, rpe: Rpe, talk: Optional[str] = None, *, hard: bool = False) -> str:
    """`Recumbent · L11 · RPE 4–5 (full sentences)`; `hard=True` for an interval day's `hard RPE 8`.
    No minutes (the row shows them) and no speed on a bike, elliptical or rower (an output)."""
    if machine not in CARDIO_MACHINES:
        raise ValueError(f"cardio machine {machine!r} is not one of {CARDIO_MACHINES}")
    words = talk or talk_words_for(rpe)
    if words not in TALK_WORDS:
        raise ValueError(f"talk words {words!r} are not one of {tuple(TALK_WORDS)}")
    return f"{machine} · {levels} · {'hard ' if hard else ''}RPE {fmt_rpe(rpe)} ({words})"


def clock_line(rule: str, machine: str = "") -> str:
    """`⌚ ride clock: ‹rule›` (`⌚ walk clock:` on the treadmill) — whole minutes off the watch clock, `min` on every time."""
    return clock_prefix_for(machine) + rule


# ── cues (standard §4): the first exercise of each family per session ───────────────────────────────────────────────
FAMILY_CUES: dict[str, str] = {
    "press": "Breathe out on the press.",
    "squat": "Brace each rep, breathe between reps.",
    "hinge": "Brace; breathe out on the way up.",
    "leg_press": "As deep as your hips stay on the pad.",
    "calf_press": "Full stretch at the bottom; knees soft.",
    "pull": "Breathe out on the pull.",
    "lying_extension": "Elbows still.",
    "crunch": "Breathe out on the crunch.",
    "carry": CARRY_CUE,
}
# owner ruling 2026-10-27 ~04:50Z: warm-up text is ONE prep-movement cue per compound family, from the #5049 table
# (`warmup_sets.WARMUP_MOVEMENT_CUES`), optional. Keyed by the catalog's anchor family.
PREP_CUES: dict[str, str] = {
    "bench": "Band pull-aparts first.",
    "hinge": "Hip hinges first.",
    "squat": "Ankles + hips first.",
}
# the catalog anchor family -> the cue family above
ANCHOR_TO_CUE_FAMILY: dict[str, str] = {
    "bench": "press",
    "overhead_press": "press",
    "squat": "squat",
    "hinge": "hinge",
    "row": "pull",
    "vertical_pull": "pull",
}

# ── vocabulary (standard §5): banned on the wire (linter L1) ─────────────────────────────────────────────────────────
# (pattern, label, case-sensitive). Case-sensitive entries are the ones whose lower-case form is ordinary English.
BANNED: tuple[tuple[str, str, bool], ...] = (
    (r"#\d{3,}", "issue number", False),
    (r"\bv\d+\.\d+", "version id", False),
    (r"§", "section sign", False),
    (r"critic", "critics", False),
    (r"red team", "red team", False),
    (r"\bcharter\b", "charter", False),
    (r"tripwire", "tripwire", False),
    (r"\bengine\b", "engine", False),
    (r"\bplatform\b", "platform", False),
    (r"\bfloor \d|\bfloor:|IS the floor|load floor|rep floor", "floor jargon", False),
    (r"\bramp\b|ramp sets", "ramp jargon", False),
    # the prep cue's band pull-aparts is a movement (owner ruling 2026-10-27, R8), not the load model's band
    (r"e1RM|\banchor\b|\bband\b(?! pull-aparts)", "load-model jargon", False),
    (r"inputs_current_through|_\w+_|\w+_\w+\(", "code identifier", False),
    (r"standing-constraint|subtract-only|never up|is a bug", "rule jargon", False),
    (r"\bRIR\b|in the tank|\bleave \d", "non-RPE effort", False),
    (r"\bkg\b|\d+(?:\.\d+)?kg", "kg", False),
    (r"🟢|🟡|🔴|✅|⚠️|🛑|⛔", "tier emoji", False),
    (r"\bWhoop\b", "Whoop tiers", False),
    (r"\bhis\b|\bhe\b|\bhim\b", "third person", True),
    (r"APPROVE|FLAG\b|CHANGE:|applied:", "verdict text", True),
    (r"protein|lb/wk|calorie|badge|weigh", "bookkeeping", False),
    (r"Nosaka|Chen \d{4}|et al", "citation", False),
    (r"carried it|you carried", "'carried' on a non-carry", False),
    (r"as written", "empty phrase", False),
    (r"@ RPE|@\s*\d+(?:\.5)?(?:–\d+)? *\(", "@ used for effort or a date (loads only)", False),
    (r"Optional if", "per-exercise branch", False),
    (r"model paused|platform-chosen", "engine status", False),
    (
        r"\bmetoprolol\b|\bAF\b|afib|atrial|\bECG\b|\bSinus\b|cardiolog|beta-blocker|\bretake\b",
        "medical or gate text (owner ruling 2026-10-27: none on the wire)",
        False,
    ),
)
TRUNCATION_RE = re.compile(r"…|\.\.\.")

# ── line grammars (linter L2/L3) ────────────────────────────────────────────────────────────────────────────────────
LOAD = r"\d+(?:\.5)?"
RPE_RANGE = r"\d+(?:\.5)?(?:–\d+(?:\.5)?)?"
EFFORT_RE = re.compile(rf"^RPE (?P<rpe>{RPE_RANGE})(?:, last set RPE \d+(?:\.5)?–\d+(?:\.5)?)?$")
CARRY_LINE1_RE = re.compile(rf"^RPE (?P<rpe>{RPE_RANGE}) · (?:pick the load per hand|(?P<start>{LOAD}) lb per hand to start)$")
_TALK = "|".join(re.escape(w) for w in TALK_WORDS)
CARDIO_LINE1_RE = re.compile(
    rf"^(?P<machine>{'|'.join(re.escape(m) for m in CARDIO_MACHINES)}) · (?P<levels>[^·]+) · "
    rf"(?P<hard>hard )?RPE (?P<rpe>\d+(?:–\d+)?) \((?P<talk>{_TALK})\)$"
)
SESSION_LINE_RE = re.compile(
    rf"^(?:(?P<day>{'|'.join(re.escape(d) for d in SESSION_DAYS)}) · RPE (?P<rpe>{RPE_RANGE}) on big lifts"
    rf"|{TEST_DAY} · [^\n]{{3,50}})$"
)
RESTATED_ROWS_RE = re.compile(rf"^\d+ × \d|^Top \d+–\d+ @|^Last:|@ {LOAD} lb")
CARDIO_MINUTES_ON_LINE1_RE = re.compile(r"\b\d+ min · ")
# a set count the text states ("2 sets today: …" is the only one the standard writes; "3 sets of 8–12" is the old drift)
SET_COUNT_RE = re.compile(r"\b(\d+) (?:working )?sets? (?:today|of)\b")  # #5428: `1 set today` is a count too
W_TEXT_RE = re.compile(r"W set: (?:up to )?(\d+)(?:–(\d+))?[ ,]")
# a load the text names: not a delta after Up/Down, not a fragment of a bigger number
NAMED_LOAD_RE = re.compile(rf"(?<!Up )(?<!Down )(?<![\d.]){LOAD} lb( per hand)?")
HR_RE = re.compile(r"bpm|heart rate|\bHR\b")
