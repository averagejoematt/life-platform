"""session_block.py — the three-line session block that heads exercise 1's Hevy note (#5428, Lane A).

THE STANDARD (HEVY_NOTE_STANDARD §3.1, owner rulings of 2026-10-27, latest wins)

Exercise 1's Pinned Routine Note opens with exactly three lines, then a blank line, then the
lift's own note:

    Upper volume · RPE 8–9 on big lifts
    Low energy → first 2 lifts + easy cardio.
    Top reps at RPE 7 or less → +10 lb on sets left; 7.5–8.5 → +5. Under 40 lb: +5 max. Dumbbells per hand. Once per lift.

(#5428 re-grade #2, 2026-10-31: a session whose only cardio is a hard kind reads `Low energy → first 2 lifts + cardio, no
hard efforts.` — `cardio_kinds_of` — and the load rule closed the RPE 7.5 / 8.5 gap, dropped pins and "later sets".)

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
LOW_ENERGY_LINES = hevy_note_grammar.LOW_ENERGY_LINES
# The load rule (R3). The step is the charter's plate step (`progression.gain_rule.step_lb`), read, never typed here.
LOAD_RULE_HEAD = hevy_note_grammar.LOAD_RULE_HEAD
LIGHT_LOAD_LB = hevy_note_grammar.SMALL_LOAD_LB  # R3's panel safeguard: under this load a 2-pin jump is too large a share


def step_lb(read: Callable[..., Any] | None = None) -> Any:
    """One pin: the charter's plate step, or None when the charter cannot be read."""
    try:
        from training.training_charter import charter_value

        return (read or charter_value)("progression.gain_rule.step_lb")
    except Exception:  # noqa: BLE001 — the rule then names pins only
        return None


def load_rule_line(step: Any, other_lifts: bool = False) -> str:
    """`Top reps at RPE 7 or less → +10 lb on sets left; 7.5–8.5 → +5. Under 40 lb: +5 max. Dumbbells per hand. Once per lift.`"""
    return hevy_note_grammar.load_rule_line(float(step) if step else None, other_lifts=other_lifts)


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


def render(
    day: str, band: Any, step: Any, cardio_kinds: list[str] | None = None, ex1_working_sets: int = 2, others_multi: bool = True
) -> str:
    """The block, newline-joined: the session line, the low-energy line (`cardio_kinds`, `cardio_kinds_of`), then the
    load rule's two lines (`hevy_note_grammar.rule_mode`): as written when exercise 1 has 2+ working sets; addressed to
    `Other lifts:` when exercise 1 has one and another lift has 2+ (#5428 re-grade #4 — dropping it left the session with
    no in-session rule); none when no lift can step."""
    head = [session_line(day, band), hevy_note_grammar.low_energy_line(cardio_kinds)]
    mode = hevy_note_grammar.rule_mode(ex1_working_sets, others_multi)
    return "\n".join(head + ([load_rule_line(step, other_lifts=mode == "others")] if mode else []))


def steppable(ex: Any) -> bool:
    """A rep-counted lift with 2+ working sets — one the load rule can step (not a carry, ride or timed block)."""
    sets = getattr(ex, "sets", None) or []
    reps = any(getattr(s, "reps", None) is not None or getattr(s, "rep_range_start", None) is not None for s in sets)
    timed = any(getattr(s, "distance_meters", None) or getattr(s, "duration_seconds", None) for s in sets)
    return reps and not timed and working_sets_of(ex) >= 2


def rule_args(exercises: Any) -> tuple[int, bool]:
    """(exercise 1's working sets, whether another lift is steppable) — what picks the block's load rule."""
    exs = list(exercises or [])
    return (working_sets_of(exs[0]) if exs else 2), any(steppable(e) for e in exs[1:])


def working_sets_of(ex: Any) -> int:
    """Exercise 1's working-set count (W rows excluded) — whether the load rule heads it."""
    return sum(1 for s in getattr(ex, "sets", None) or [] if str(getattr(s, "type", "") or "").lower() not in ("warmup", "warm_up"))


def cardio_kinds_of(exercises: Any) -> list[str]:
    """The menu kind of every cardio block in the session: its composed note's line 1 (`cardio_note.composed_kind`), else
    its rationale tag's last field (`cardio:cycling:menu:intervals`). The low-energy line reads them (#5428 re-grade #2:
    "+ easy cardio" over a session whose only cardio was intervals)."""
    from training import cardio_note

    kinds: list[str] = []
    for ex in exercises or []:
        if not cardio_note.machine_for(str(getattr(ex, "movement_key", "") or "")):
            continue
        kind = cardio_note.composed_kind(getattr(ex, "notes", None))
        if not kind:
            tag = str(getattr(ex, "rationale_tag", "") or "")
            kind = tag.split(":")[-1] if tag.startswith("cardio") and tag.count(":") >= 3 else "easy"
        kinds.append(kind)
    return kinds


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
    exercises = getattr(ir, "exercises", None) or []
    first, others = rule_args(exercises)
    return render(day, band if band is not None else compounds_band(read), step_lb(read), cardio_kinds_of(exercises), first, others)


def split(note: str | None) -> tuple[str, str]:
    """(the session block, the lift's own note). The block is "" when the note does not open with one. The block is
    everything before the first blank line once line 2 is a low-energy line: two lines on a one-set exercise 1, four
    with the load rule, three in the pre-re-grade-#3 form."""
    text = note or ""
    head, _sep, rest = text.partition("\n\n")
    lines = head.split("\n")
    if (
        len(lines) >= 2
        and lines[1] in LOW_ENERGY_LINES
        and (len(lines) == 2 or lines[2].startswith((LOAD_RULE_HEAD, hevy_note_grammar.OTHER_LIFTS_HEAD)))
    ):
        return head, rest.strip("\n")
    return "", text


def session_effort(block: str) -> str | None:
    """The session line's band as an effort line (`RPE 8–9`), or None."""
    m = SESSION_LINE_RE.match((block or "").split("\n", 1)[0])
    return f"RPE {m.group('band')}" if m else None


def _own_lines(block: str, own: str) -> list[str]:
    """Exercise 1's own lines with its effort line restored when the block's session line carries it (deduped on the wire,
    `_join`), so the reason-slot logic below always sees line 1 as the effort."""
    lines = own.split("\n") if own.strip() else []
    eff = session_effort(block) if block else None
    if eff and (not lines or not hevy_note_grammar.EFFORT_RE.match(lines[0])):
        lines = [eff] + lines
    return lines


def place(note: str | None, block: str) -> str:
    """`block`, a blank line, then the lift's own note. Idempotent: an existing block is replaced, never stacked.
    #5428 re-grade #3: exercise 1's own `RPE 8–9` is dropped when the session line already says it (it printed twice)."""
    block_was, own = split(note)
    return _join(block, _own_lines(block_was or block, own.strip()))


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


def sync_low_energy(ir: Any) -> bool:
    """Re-read the low-energy line off the session's cardio as it now stands (a critic swap or drop can change it after
    the block was placed — #5428 re-grade #2). IN PLACE; True when line 2 changed. A note with no block is left alone."""
    exercises = getattr(ir, "exercises", None) or []
    if not exercises:
        return False
    note = getattr(exercises[0], "notes", "") or ""
    block, own = split(note)
    if not block:
        return False
    lines = block.split("\n")
    want = hevy_note_grammar.low_energy_line(cardio_kinds_of(exercises))
    if lines[1] == want:
        return False
    lines[1] = want
    exercises[0].notes = "\n".join(lines) + ("\n\n" + own if own else "")
    return True


def dedupe_effort(lines: list[str], block: str) -> list[str]:
    """Drop exercise 1's own effort line when it repeats the session line's band (#5428 re-grade #3)."""
    eff = session_effort(block) if block else None
    return lines[1:] if eff and lines and lines[0] == eff else lines


def block_of(ir: Any) -> str:
    """The session block on exercise 1's note ("" when there is none)."""
    exercises = getattr(ir, "exercises", None) or []
    return split(getattr(exercises[0], "notes", "") or "")[0] if exercises else ""


def why_note_for(ir: Any, fallback: str) -> str:
    """The compiler's WHY line: "" when exercise 1 already opens with the session block (its first line IS
    the session line — a second one would only repeat it), else `fallback` (`routine_title.format_why_note`) —
    conformed to this routine when it is a session block (#5428 re-grade #3: the role's static block carried the
    load rule onto a one-set exercise 1 and "+ easy cardio" onto an intervals-only session)."""
    if block_of(ir):
        return ""
    return conform_block(fallback, ir) if split(fallback)[0] == fallback.strip() and fallback.strip() else fallback


def conform_block(block: str, ir: Any) -> str:
    """`block`'s session line, with the low-energy line and the load rule this routine calls for."""
    exercises = getattr(ir, "exercises", None) or []
    lines = block.strip().split("\n")
    mode = hevy_note_grammar.rule_mode(*rule_args(exercises)) if exercises else None
    rule = load_rule_line(step_lb(), other_lifts=mode == "others").split("\n") if mode else []
    return "\n".join([lines[0], hevy_note_grammar.low_energy_line(cardio_kinds_of(exercises))] + rule)


# ── a critic's applied change, as one plain clause on the exercise it changed (standard §3.8) ──────────
def gap_words(days: Any) -> str | None:
    """`first time in 5 weeks` / `first time in 10 days` / `first time in 17 months`, from a days-since count (None below
    7 days or when the count is unknown)."""
    gap = hevy_note_grammar.gap_text(days)
    return f"first time in {gap}" if gap else None


# what a reason says when a layoff verdict's gap is not on the verdict (§6.3: a safety change keeps a reason — never a
# bare `3 sets today.`, the 2026-10-30 re-grade's standing calf raise, whose days-since value read None)
BREAK_WORDS = "back after a break"
NEW_TO_LOG_WORDS = "new to the log"


def days_between(a: Any, b: Any) -> int | None:
    from common.pacific_time import parse_day_key

    da, db = parse_day_key(str(a or "")[:10]), parse_day_key(str(b or "")[:10])
    return (db - da).days if (da is not None and db is not None) else None


def is_layoff(verdict: dict[str, Any] | None) -> bool:
    """A critic change answering a days-since signal (the joints critic's stale-lift cap)."""
    return str((verdict or {}).get("metric") or "").startswith("days_since")


def layoff_gap(verdict: dict[str, Any] | None, previous_date: Any, target_date: Any) -> int | None:
    """The layoff's gap in days from what is known: the verdict's own days-since value, else Hevy's PREVIOUS date
    (`inputs_snapshot["previous_loads"]`) to the target day, else None (nothing logged that either read can see)."""
    try:
        return int(float((verdict or {}).get("value")))
    except (TypeError, ValueError):
        return days_between(previous_date, target_date) if previous_date else None


def change_reason(verdict: dict[str, Any] | None, gap_days: Any = None) -> str | None:
    """The plain why behind a critic's change, from its metric — never its prose, critic name or citation. A layoff
    always has one: its gap (`gap_days`, `layoff_gap`), else `back after a break`."""
    v = verdict or {}
    metric = str(v.get("metric") or "")
    if metric.startswith("days_since"):
        return gap_words(v.get("value")) or gap_words(gap_days) or BREAK_WORDS
    if metric == "consecutive_training_days" or v.get("critic") == "joints_tendons":
        return "a lighter day for the joints"
    return None


def layoff_capped(gap_days: int | None, note: str | None) -> bool:
    """OD1 (owner ruling 2026-09-30, `layoff_tiers`): exposures 1–3 after a gap of more than 90 days, or a novel-again
    lift, run at RPE ≤ 7 — the effort treatment `lift_note` gives a capped exposure. True when the gap is over that line
    or unknown, or the lift's note already carries the composer's `No jumps` line."""
    from training.layoff_tiers import REENTRY_MAX_GAP_DAYS

    if any(ln.startswith(hevy_note_grammar.NO_JUMPS) for ln in split(note)[1].split("\n")):
        return True
    return gap_days is None or int(gap_days) > REENTRY_MAX_GAP_DAYS


def capped_clause(working_sets: int, gap_days: Any = None, existing: str | None = None) -> str:
    """A critic's set cap on a capped exposure, as the lift's ONE `No jumps` line (≤ one phone line, so the pick-load W
    line and the family cue still fit): `No jumps: 3 sets today, 19 weeks off.` The gap is the composer's own `No jumps`
    line's when there is one (`existing`), so the two never disagree."""
    head = f"{hevy_note_grammar.NO_JUMPS}: {working_sets} set{'' if working_sets == 1 else 's'} today"
    m = re.search(r"session (\d+) back", existing or "")
    if m:
        return f"{head}, session {m.group(1)} back."
    m = re.search(r"first time in (.+?)\.$", existing or "")
    gap = m.group(1) if m else hevy_note_grammar.gap_text(gap_days)
    if gap:
        return f"{head}, {gap} off."
    return f"{head}, {NEW_TO_LOG_WORDS}." if gap_days is None else f"{head}, {BREAK_WORDS}."


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


# what a critic clause opens with (`applied_clause`): one is never displaced by another — each is a safety change (§6.3)
CLAUSE_RE = re.compile(r"^(?:\d+ sets? today|Lighter today|Heavier today|Fewer reps today)[:.]|^No jumps: \d+ sets? today, ")


def _displaceable(line: str) -> bool:
    """A computed reason that yields the one reason slot to a critic clause. A capped exposure's `No jumps` line opts the
    lift out of the load rule (a safety cap after a break), so it keeps its line, as does an earlier critic clause."""
    return bool(hevy_note_grammar.REASON_RE.match(line)) and not CLAUSE_RE.match(line) and not line.startswith(hevy_note_grammar.NO_JUMPS)


def _fit(block: str, lines: list[str]) -> list[str]:
    """Drop the optional #5049 prep clause (R8: "if overkill skip") from the cue line when a critic's clause has pushed
    the lift past its phone budget (§7: lift note ≤ 4, exercise 1 ≤ 11). The family cue itself stays (§6.1)."""

    def over(ls: list[str]) -> bool:
        own = "\n".join(ls)
        g = hevy_note_grammar
        return g.phone_lines(own) > g.LIFT_MAX_LINES or bool(block and g.phone_lines(block + "\n\n" + own) > g.EX1_MAX_LINES)

    if not over(lines):
        return lines
    out = []
    for ln in lines:
        prep = next((p for p in hevy_note_grammar.PREP_CUES.values() if ln.startswith(p + " ")), None)
        out.append(ln[len(prep) + 1 :] if prep else ln)
    return out


def _join(block: str, lines: list[str]) -> str:
    own_out = "\n".join(dedupe_effort(_fit(block, lines), block))
    if not block:
        return own_out
    return block + ("\n\n" + own_out if own_out else "")


def add_reason(note: str | None, clause: str | None) -> str:
    """Write `clause` as THE reason line of the lift's OWN note, below any session block. Idempotent — a clause already
    on the note is not written twice.

    One reason per lift (standard §3.2, whose reason list includes the critic clause) and the clause is a safety change
    that is never dropped (§6.3), so it takes the reason slot: a computed reason already there (`New: replaces …`,
    `Heavier: …`, `Volume day: …`) gives way to it — the displaced line stays on the stored record
    (`inputs_snapshot["lift_notes"]`). A capped exposure's `No jumps` line and an earlier critic clause keep their
    lines, and the clause goes in after line 1 (the effort line). #5428 replay, 2026-10-29: the joints critic's
    `3 sets today: …` stacked on a seated calf raise's rotation line, pick-load line and cue — 5 phone lines > 4. A
    clause that still pushes the note over budget drops the optional prep clause from the cue line (`_fit`)."""
    text = note or ""
    if not clause or clause in text.split("\n"):
        return text
    block, own = split(text)
    lines = _own_lines(block, own)
    slot = next((i for i, ln in enumerate(lines[1:], start=1) if _displaceable(ln)), None)
    lines = lines[:slot] + [clause] + lines[slot + 1 :] if slot is not None else lines[:1] + [clause] + lines[1:]
    return _join(block, lines)


def add_capped_reason(note: str | None, clause: str, rpe_max: Any) -> str:
    """A critic's set cap on a capped exposure (`layoff_capped`): line 1 becomes the cap's effort (`RPE 7` — the
    "last set RPE 9–10" of the band would contradict it) and `clause` (`capped_clause`) takes the `No jumps` line's
    slot, else a displaceable computed reason's, else goes in after line 1 — the same effort treatment `lift_note`
    gives a capped exposure (the 2026-10-30 re-grade: a capped seated calf raise kept RPE 9–10 and the +10 lb rule).
    An earlier critic clause keeps its line. Idempotent."""
    text = note or ""
    block, own = split(text)
    lines = _own_lines(block, own)
    if not lines:
        return text
    if hevy_note_grammar.EFFORT_RE.match(lines[0]):
        lines[0] = hevy_note_grammar.effort_line(rpe_max)
    if clause not in lines:
        slot = next(
            (i for i, ln in enumerate(lines[1:], start=1) if ln.startswith(hevy_note_grammar.NO_JUMPS)),
            next((i for i, ln in enumerate(lines[1:], start=1) if _displaceable(ln)), None),
        )
        lines = lines[:slot] + [clause] + lines[slot + 1 :] if slot is not None else lines[:1] + [clause] + lines[1:]
    return _join(block, lines)
