"""session_block.py — the three-line session block that heads exercise 1's Hevy note (#5428, Lane A).

THE STANDARD (HEVY_NOTE_STANDARD §3.1, owner rulings of 2026-10-27, latest wins)

Exercise 1's Pinned Routine Note opens with exactly three lines, then a blank line, then the
lift's own note:

    Upper volume · RPE 8–9 on big lifts
    Low energy → first 2 lifts + easy cardio.
    Top reps at RPE 7 or less → +10 lb (2 pins) on later sets; at RPE 8 → +5 lb (1 pin). Under 40 lb: +5 max. Once per lift.

No safety or medical line, no daily gate, no Whoop-band header, no bookkeeping (protein, rate,
badges), no provenance (`inputs_current_through`, the loaded-lifting streak) and no critics'
verdict block. Those stay STORED on the routine (`inputs_snapshot`) and in the dry-run and chat.

None of the three lines is clinical, so they are code text, but every number in them is the charter's:
the session line's RPE is the compounds band (`effort_ceilings.class_bands`) and one pin is the plate step
(`progression.gain_rule.step_lb`) — never a typed copy (tests/test_training_charter_derivation_5068.py).

The same module carries the one plain clause a critic's APPLIED change writes on the exercise it
changed (standard §3.8: `2 sets today: first time in 5 weeks.`) — no issue numbers, no critic or
field names — and `why_note_for`, which keeps the compiler's separate WHY line from repeating the
session line when the block is already on exercise 1.

Pure: no I/O beyond the charter read `render_for` does (injectable `read`).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from training import hevy_note_grammar

# Lines 2 and 3 are Lane D's grammar (`hevy_note_grammar`), so the block, routine_title's fallback and the linter read
# one text.
LOW_ENERGY_LINE = hevy_note_grammar.LOW_ENERGY_LINE
# The load rule (R3). One pin is the charter's plate step (`progression.gain_rule.step_lb`), read, never typed here.
LOAD_RULE_HEAD = "Top reps at RPE 7 or less → "
LIGHT_LOAD_LB = hevy_note_grammar.SMALL_LOAD_LB  # R3's panel safeguard: under this load a 2-pin jump is too large a share


def step_lb(read: Callable[..., Any] | None = None) -> Any:
    """One pin: the charter's plate step, or None when the charter cannot be read."""
    try:
        from training.training_charter import charter_value

        return (read or charter_value)("progression.gain_rule.step_lb")
    except Exception:  # noqa: BLE001 — the rule then names pins only
        return None


def load_rule_line(step: Any) -> str:
    """`Top reps at RPE 7 or less → +10 lb (2 pins) on later sets; at RPE 8 → +5 lb (1 pin). Under 40 lb: +5 max. Once per lift.`"""
    return hevy_note_grammar.load_rule_line(float(step) if step else None)


# ‹Day› by the program's session role first (`inputs_snapshot.calendar.session_role`), then the archetype.
DAY_LABELS: dict[str, str] = {
    "upper_volume": "Upper volume",
    "upper_heavy": "Upper heavy",
    "lower_volume": "Lower volume",
    "lower_heavy": "Lower heavy",
    "shoulders_arms": "Shoulders + arms",
    "full": "Full body",
    "full_body": "Full body",
    "minimum": "Minimum",
    "travel": "Travel",
    "upper": "Upper",
    "lower": "Lower",
    "push": "Push",
    "pull": "Pull",
    "legs": "Legs",
}
DEFAULT_DAY = "Session"

SESSION_LINE_RE = re.compile(r"^(?P<day>.+?) · RPE (?P<band>\d+(?:\.\d+)?(?:–\d+(?:\.\d+)?)?) on big lifts$")
CLAUSE_MAX_CHARS = 50


def day_label(session_role: Any = None, archetype: Any = None) -> str:
    """The session line's ‹Day›: the role's label, else the archetype's, else `Session`."""
    for key in (session_role, archetype):
        label = DAY_LABELS.get(str(key or "").strip().lower())
        if label:
            return label
    return DEFAULT_DAY


def _band_text(band: Any) -> str | None:
    if not band:
        return None
    lo, hi = float(band[0]), float(band[-1])
    return f"{lo:g}" if lo == hi else f"{lo:g}–{hi:g}"


def session_line(day: str, band: Any) -> str:
    """`‹Day› · RPE ‹a–b› on big lifts`; just `‹Day›` when the charter band could not be read (absence is absence)."""
    text = _band_text(band)
    return f"{day} · RPE {text} on big lifts" if text else day


def render(day: str, band: Any, step: Any) -> str:
    """The three lines, newline-joined."""
    return "\n".join((session_line(day, band), LOW_ENERGY_LINE, load_rule_line(step)))


def compounds_band(read: Callable[..., Any] | None = None) -> list[Any] | None:
    """The charter's compounds RPE band, or None when it cannot be read."""
    try:
        from training import effort_ceilings

        bands = effort_ceilings.class_bands(read) if read is not None else effort_ceilings.class_bands()
        return bands.get(effort_ceilings.COMPOUNDS)
    except Exception:  # noqa: BLE001 — the session line then names the day only
        return None


def render_for(ir: Any, band: Any = None, read: Callable[..., Any] | None = None) -> str:
    """The block for a routine IR: its role/archetype for ‹Day›, the charter's compounds band for the RPE."""
    cal = ((getattr(ir, "inputs_snapshot", None) or {}).get("calendar")) or {}
    day = day_label(cal.get("session_role"), getattr(ir, "archetype", None))
    return render(day, band if band is not None else compounds_band(read), step_lb(read))


def split(note: str | None) -> tuple[str, str]:
    """(the session block, the lift's own note). The block is "" when the note does not open with one."""
    text = note or ""
    lines = text.split("\n")
    if len(lines) >= 3 and lines[1] == LOW_ENERGY_LINE and lines[2].startswith(LOAD_RULE_HEAD):
        return "\n".join(lines[:3]), "\n".join(lines[3:]).strip("\n")
    return "", text


def place(note: str | None, block: str) -> str:
    """`block`, a blank line, then the lift's own note. Idempotent: an existing block is replaced, never stacked."""
    own = split(note)[1].strip()
    return block + ("\n\n" + own if own else "")


def _is_lift(ex: Any) -> bool:
    """A block with a loaded or rep-counted set — not a timed cardio / mobility block."""
    return any(
        getattr(s, "reps", None) is not None or getattr(s, "weight_kg", None) is not None or getattr(s, "rep_range_start", None) is not None
        for s in getattr(ex, "sets", None) or []
    )


def place_on_first(ir: Any, band: Any = None, read: Callable[..., Any] | None = None) -> str | None:
    """Write the block at the head of exercise 1's note, IN PLACE. Returns the block, or None when there is
    nothing to head: no exercises, or no lift at all (a cardio-only session has no big lifts and no load rule)."""
    exercises = getattr(ir, "exercises", None) or []
    if not exercises or not any(_is_lift(ex) for ex in exercises):
        return None
    block = render_for(ir, band=band, read=read)
    exercises[0].notes = place(getattr(exercises[0], "notes", "") or "", block)
    return block


def block_of(ir: Any) -> str:
    """The session block on exercise 1's note ("" when there is none)."""
    exercises = getattr(ir, "exercises", None) or []
    return split(getattr(exercises[0], "notes", "") or "")[0] if exercises else ""


def why_note_for(ir: Any, fallback: str) -> str:
    """The compiler's WHY line: "" when exercise 1 already opens with the session block (its first line IS
    the session line — a second one would only repeat it), else `fallback` (`routine_title.format_why_note`)."""
    return "" if block_of(ir) else fallback


# ── a critic's applied change, as one plain clause on the exercise it changed (standard §3.8) ──────────
def gap_words(days: Any) -> str | None:
    """`first time in 5 weeks` / `first time in 10 days`, from a days-since count (None below 7 days)."""
    try:
        d = int(float(days))
    except (TypeError, ValueError):
        return None
    if d < 7:
        return None
    return f"first time in {round(d / 7)} weeks" if d >= 14 else f"first time in {d} days"


def change_reason(verdict: dict[str, Any] | None) -> str | None:
    """The plain why behind a critic's change, from its metric — never its prose, critic name or citation."""
    v = verdict or {}
    metric = str(v.get("metric") or "")
    if metric.startswith("days_since"):
        return gap_words(v.get("value"))
    if metric == "consecutive_training_days" or v.get("critic") == "joints_tendons":
        return "a lighter day for the joints"
    return None


def applied_clause(kind: str, *, working_sets: int | None = None, lighter: bool | None = None, reason: str | None = None) -> str | None:
    """One clause per change kind, ≤ CLAUSE_MAX_CHARS. `kind` is the change grammar's field
    (`set_count` / `total_sets` / `weight_lbs` / `reps`); a swap and a drop carry no clause here."""
    tail = f": {reason}." if reason else "."
    if kind in ("set_count", "total_sets") and working_sets:
        head = f"{working_sets} set{'' if working_sets == 1 else 's'} today"
    elif kind == "weight_lbs":
        head = "Lighter today" if lighter is not False else "Heavier today"
    elif kind == "reps":
        head = "Fewer reps today"
    else:
        return None
    clause = head + tail
    return clause if len(clause) <= CLAUSE_MAX_CHARS else head + "."


def add_reason(note: str | None, clause: str | None) -> str:
    """Insert `clause` as the reason line: after line 1 (the effort line) of the lift's OWN note, below any
    session block. Idempotent — a clause already on the note is not written twice."""
    text = note or ""
    if not clause or clause in text.split("\n"):
        return text
    block, own = split(text)
    lines = own.split("\n") if own.strip() else []
    lines = lines[:1] + [clause] + lines[1:]
    own_out = "\n".join(lines)
    return block + "\n\n" + own_out if block else own_out
