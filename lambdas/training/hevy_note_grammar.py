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

GRAMMAR_VERSION = "hevy-note-grammar@1.0.0"

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
TEST_DAY = "Test"
# R3's small-load safeguard: under this load a lift moves one step at most (two steps on a 15 lb raise is +67 %).
SMALL_LOAD_LB = 40


def load_rule_line(step_lb: Optional[float]) -> str:
    """Session line 2, owner ruling 2026-10-27 R3: two load steps when the top reps land at RPE <= 7, one step at RPE 8,
    one step at most under SMALL_LOAD_LB, once per lift. The step is the charter's (`progression.gain_rule.step_lb`),
    so the line moves with it; with no charter step the line says pins only."""
    if not step_lb:
        return f"Top reps at RPE 7 or less → 2 pins on later sets; at RPE 8 → 1 pin. Under {SMALL_LOAD_LB} lb: 1 pin max. Once per lift."
    one, two = fmt_num(step_lb), fmt_num(2 * step_lb)
    return f"Top reps at RPE 7 or less → +{two} lb (2 pins) on later sets; at RPE 8 → +{one} lb (1 pin). Under {SMALL_LOAD_LB} lb: +{one} max. Once per lift."


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


def session_block(day: str, big_lift_rpe: Rpe) -> str:
    """The three-line block that heads exercise 1 (followed by a blank line, then exercise 1's own note)."""
    return "\n".join((session_line(day, big_lift_rpe), LOW_ENERGY_LINE, LOAD_RULE_LINE))


# ── lift notes (standard §3.2–3.4) ──────────────────────────────────────────────────────────────────────────────────
def effort_line(rpe: Rpe, last_set_rpe: Optional[Rpe] = None) -> str:
    """Line 1 of every lift note: `RPE a–b[, last set RPE c–d]`."""
    out = f"RPE {fmt_rpe(rpe)}"
    return f"{out}, last set RPE {fmt_rpe(last_set_rpe)}" if last_set_rpe is not None else out


PICK_LOAD_W_REPS = 8


def pick_load_line(w_reps: int = PICK_LOAD_W_REPS) -> str:
    """The pick-load form's line 2 (no history, or stale history), over a no-load W row of `w_reps`."""
    return f"W set: up to {w_reps} easy reps, find the load."


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
REASON_RE = re.compile(
    r"^(?:Heavier: |Lighter: |Volume day: |Now aiming \d+–\d+: |No jumps(?: today)?: |Set \d over RPE \d+(?:\.5)? → |\d+ sets today: )"
)


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
def carry_line1(rpe: Rpe) -> str:
    return f"RPE {fmt_rpe(rpe)} · pick the load per hand"


CARRY_CUE = "Tall, ribs down, bells off your legs."
CARRY_STEPS_LINE = "Steps go in the yards box."

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
AFTER_LINE = "After: end watch cardio, restart Hevy."


def talk_words_for(rpe: Rpe) -> str:
    """The fixed talk-test words for an RPE (the top of a range decides)."""
    hi = float(rpe[-1] if isinstance(rpe, (tuple, list)) else rpe)
    if hi <= 5:
        return "full sentences"
    if hi <= 7:
        return "short phrases"
    return "a few words"


def cardio_line1(machine: str, levels: str, rpe: Rpe, talk: Optional[str] = None, *, hard: bool = False) -> str:
    """`Recumbent · L11 · RPE 4–5 (full sentences)`; `hard=True` for an interval day's `hard RPE 8`.
    No minutes (the row shows them) and no speed on a bike, elliptical or rower (an output)."""
    if machine not in CARDIO_MACHINES:
        raise ValueError(f"cardio machine {machine!r} is not one of {CARDIO_MACHINES}")
    words = talk or talk_words_for(rpe)
    if words not in TALK_WORDS:
        raise ValueError(f"talk words {words!r} are not one of {tuple(TALK_WORDS)}")
    return f"{machine} · {levels} · {'hard ' if hard else ''}RPE {fmt_rpe(rpe)} ({words})"


def clock_line(rule: str) -> str:
    """`⌚ ride clock: ‹rule›` — times in whole minutes off the ride's own clock, `min` on every time."""
    return CLOCK_PREFIX + rule


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
CARRY_LINE1_RE = re.compile(rf"^RPE (?P<rpe>{RPE_RANGE}) · pick the load per hand$")
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
SET_COUNT_RE = re.compile(r"\b(\d+) (?:working )?sets (?:today|of)\b")
W_TEXT_RE = re.compile(r"W set: (?:up to )?(\d+)(?:–(\d+))?[ ,]")
# a load the text names: not a delta after Up/Down, not a fragment of a bigger number
NAMED_LOAD_RE = re.compile(rf"(?<!Up )(?<!Down )(?<![\d.]){LOAD} lb( per hand)?")
HR_RE = re.compile(r"bpm|heart rate|\bHR\b")
