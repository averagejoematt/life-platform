"""lift_note.py — the generator's lift note, composed LAST from what the engine decided (#5428).

THE DEFECT (four-voice review of the last 30 routines, graded C−; generator-written notes since 10-23 ≈ D): a lift
note was assembled by every pass that touched the block — the history line ("Last: 36.5kg 8/8/8 (19 Sep)"), the
exposure cue ("VOLUME: 3 sets of 8–12 @ RPE 8–9 (charter compound ceiling)"), the floor/ramp provenance ("Week 5 load
… 80% of your band anchor … v0.3 §3 … Down on the day if you must, never up."), the progression's reasoning ("hold:
… has a set with no RPE logged — not evidence …") and the warm-up clause. Up to 532 characters, kg beside lb, the set
count beside rows that disagreed with it, and the instruction last.

THE STANDARD (`HEVY_NOTE_STANDARD.md` §3.2–3.4, owner rulings 2026-10-27). Hevy already shows every row's load x reps,
the W rows and the PREVIOUS column, so the note carries only what a row cannot:

    RPE a–b[, last set RPE c–d]     line 1, always — the charter's band (`session_cues.exposure_cue`)
    ‹one reason›                    only when a row moves more than one step from PREVIOUS, or the scheme changes
    ‹one cue›                       the first exercise of a movement family (`movement_cues`)

A movement with no session on file, or none in `STALE_AFTER_DAYS`, is the pick-load form: a no-load W row of 8 ahead
of the engine's start load, and `W set: up to 8 easy reps, test the load.` (`find the load.` when the rows carry
no load). A stale PREVIOUS more than one step from the row still gets its reason (`Lighter: first time in 2 years.`):
Hevy shows that PREVIOUS beside the row, and the drop needs a why (#5428 re-grade #2, 2026-10-31).

WHAT LEAVES THE WIRE, NOT THE RECORD. The passes still compute everything they did — the floor, the ramp, the hold, the
progression — and their text is kept on `inputs_snapshot["lift_notes"][key]["detail"]` and in the rationale, where
the dry-run and the coach chat read it. Only the Hevy note is rewritten.

Pure: every input is a value the generator already holds. No reads, no clock.
"""

from __future__ import annotations

import re
from typing import Any

from training import hevy_note_grammar, movement_cues
from training.rep_scheme import LB_IN_KG, implement_step_lb
from training.session_cues import effort_line, exposure_cue

STALE_AFTER_DAYS = 180
"""A PREVIOUS older than this is not a load to quote (a 2022 chest-fly anchor at another bodyweight); the note becomes
the pick-load form. HEVY_NOTE_STANDARD §3.3: "the newest one is over 180 days old". It was 28 (the detraining line,
`load_ramp.DETRAINING_ANCHOR_AGE_DAYS`) until the 2026-10-30 re-grade: a lift with a fresh PREVIOUS 33–131 days old read
"find the load" beside a row that carried his own logged load. The detraining discount stays the engine's, in the load.
§3.3's second test, a bodyweight more than 20 lb away, needs the weigh-in at PREVIOUS's date, which
`exercise_history.previous_load` does not carry (§10.2 is still open on it)."""

PICK_LOAD_W_REPS = hevy_note_grammar.PICK_LOAD_W_REPS
PICK_LOAD_LINE = hevy_note_grammar.pick_load_line(PICK_LOAD_W_REPS)
PICK_LOAD_OPEN_LINE = hevy_note_grammar.pick_load_line(PICK_LOAD_W_REPS, rows_loaded=False)
ROTATION_HEAD = hevy_note_grammar.ROTATION_HEAD
rotation_line = hevy_note_grammar.rotation_line  # #5083: the rotated accessory's one reason line, from the grammar

_TIMES = {2: "twice", 3: "three times", 4: "four times", 5: "five times"}


def _days_between(a: str, b: str) -> int | None:
    from common.pacific_time import parse_day_key

    da, db = parse_day_key(str(a or "")), parse_day_key(str(b or ""))
    return (db - da).days if (da is not None and db is not None) else None


def is_stale(previous: dict[str, Any] | None, target_date: str) -> bool:
    """True when he has no session of the movement on file, or the newest is older than `STALE_AFTER_DAYS`."""
    if not previous:
        return True
    gap = _days_between(str(previous.get("date") or ""), target_date)
    return gap is None or gap > STALE_AFTER_DAYS


def _is_warmup(s: Any) -> bool:
    return str(getattr(s, "type", "") or "").lower() in ("warmup", "warm_up", "warm-up")


def _working(sets: list[Any]) -> list[Any]:
    return [s for s in sets or [] if not _is_warmup(s)]


def _top_lb(sets: list[Any]) -> float | None:
    loads = [float(s.weight_kg) for s in _working(sets) if getattr(s, "weight_kg", None)]
    return round(max(loads) / LB_IN_KG, 1) if loads else None


def _rep_hi(sets: list[Any]) -> int | None:
    his = [int(getattr(s, "rep_range_end", None) or getattr(s, "reps", None) or 0) for s in _working(sets)]
    his = [h for h in his if h > 0]
    return max(his) if his else None


def delta_word(row_lb: float | None, previous_lb: float | None, step_lb: float | None) -> str | None:
    """'Heavier' / 'Lighter' when the row is more than one implement step from PREVIOUS, else None (no reason needed).
    Lane D's `hevy_note_grammar.delta_word` (the linter's own rule); a stack with no fixed step is never judged."""
    return hevy_note_grammar.delta_word(row_lb, previous_lb, step_lb)


def _rpe_text(rpe: Any) -> str:
    return f"RPE {float(rpe):g}"


def _heavier_why(previous: dict[str, Any] | None) -> str:
    """'15 reps was RPE 7' — what he did last time that earns the heavier row."""
    if not previous or not previous.get("reps"):
        return "a step up from last time"
    rpe = previous.get("rpe")
    return f"{int(previous['reps'])} reps was {_rpe_text(rpe)}" if rpe is not None else f"{int(previous['reps'])} reps last time"


def _same_load_after_a_grind(row_lb: float | None, previous: dict[str, Any] | None, re_entry: bool) -> bool:
    """The prescribed top load equals PREVIOUS and PREVIOUS ran to RPE 10 (#5428): the band asks for the same load at a
    lower effort, so the note says so. A re-entry lift carries its layoff clause instead; a stack with no logged RPE is
    not judged."""
    if re_entry or row_lb is None or not previous or previous.get("lb") is None or previous.get("rpe") is None:
        return False
    return abs(float(row_lb) - float(previous["lb"])) < 1e-6 and float(previous["rpe"]) >= hevy_note_grammar.SAME_LOAD_FROM_RPE


def _held_at_top(row_lb: float | None, previous: dict[str, Any] | None, rep_hi: int | None, prog: dict[str, Any], re_entry: bool) -> bool:
    """The engine HOLDS the load at PREVIOUS although PREVIOUS reached the top of the rep range at RPE <= 8.5 (#5428
    re-grade #2: the reverse fly at 60 x 15 @ 8.5 and the pushdown at 50 x 15 @ 8.5 read as "never progresses"). The
    gain rule wants the top twice in a row, and the load rule moves it in-session at RPE <= 8.5 — the note says so."""
    if re_entry or row_lb is None or not rep_hi or not previous or previous.get("lb") is None or previous.get("rpe") is None:
        return False
    if (prog or {}).get("basis") not in (None, "hold"):
        return False
    return (
        abs(float(row_lb) - float(previous["lb"])) < 0.6
        and int(float(previous.get("reps") or 0)) >= int(rep_hi)
        and float(previous["rpe"]) <= hevy_note_grammar.HELD_TOP_MAX_RPE
    )


def _stall_why(prog: dict[str, Any], history: list[dict[str, Any]] | None) -> str:
    """'8s were RPE 8 three times' — the stall rule's run, in his words."""
    dates = set(prog.get("dates") or [])
    reps = int(prog.get("from_reps") or 0)
    rpes = [
        float(x["rpe"])
        for s in history or []
        if str(s.get("date") or "") in dates
        for x in s.get("sets") or []
        if x.get("rpe") is not None and int(x.get("reps") or 0) == reps
    ]
    times = _TIMES.get(len(dates), f"{len(dates)} times")
    effort = f"RPE {max(rpes):g}" if rpes else "inside the band"
    return f"{reps}s were {effort} {times}"


def reason_line(
    *,
    prog: dict[str, Any] | None,
    intensity: str | None,
    row_lb: float | None,
    previous: dict[str, Any] | None,
    step_lb: float | None,
    rep_lo: int | None,
    rep_hi: int | None,
    history: list[dict[str, Any]] | None,
    re_entry: bool,
) -> str:
    """At most ONE reason (standard §3.2), or "": a scheme change (the stall rule's rep step), a heavier row the gain rule
    earned, any top row more than one step from PREVIOUS, or the same load as a PREVIOUS that ran to RPE 10 (#5428, owner
    ruling 2026-10-30: without the reason, "same load" reads as a copy of the grind). A reason never repeats a number the
    rows already show."""
    prog = prog or {}
    if prog.get("basis") == "step" and prog.get("step_kind") == "reps" and prog.get("next_reps") and rep_hi:
        return f"Now aiming {int(prog['next_reps'])}–{int(rep_hi)}: {_stall_why(prog, history)}."
    word = delta_word(row_lb, (previous or {}).get("lb"), step_lb)
    if prog.get("basis") == "step" and prog.get("changes"):
        word = word or "Heavier"
    if word is None and _same_load_after_a_grind(row_lb, previous, re_entry):
        return hevy_note_grammar.SAME_LOAD_LINE
    if word is None and _held_at_top(row_lb, previous, rep_hi, prog, re_entry):
        return hevy_note_grammar.held_top_line(rep_hi)
    if word == "Heavier":
        return f"Heavier: {_heavier_why(previous)}."
    if word == "Lighter":
        chase = rep_hi or rep_lo
        if re_entry:
            return "Lighter: back after a break."
        if intensity == "volume":
            return f"Volume day: chase {chase}." if chase else "Volume day."
        return f"Lighter: chase {chase}." if chase else "Lighter today."
    return ""


def _add_feeler(block: Any) -> bool:
    """The pick-load form's no-load W row of `PICK_LOAD_W_REPS`, ahead of the working rows — only on a rep-typed block that
    carries no W row yet (a warmed compound already climbs). Returns True when it was added."""
    from training.routine_ir import Set

    sets = list(block.sets or [])
    if not sets or any(_is_warmup(s) for s in sets):
        return False
    if any(getattr(s, "distance_meters", None) or getattr(s, "duration_seconds", None) for s in sets):
        return False
    block.sets = [Set(type="warmup", reps=PICK_LOAD_W_REPS)] + sets
    return True


def _intensity_of(block: Any, entry: dict[str, Any]) -> str:
    tag = str(getattr(block, "rationale_tag", "") or "")
    parts = tag.split(":")
    if len(parts) >= 3 and parts[0] in ("anchor", "accessory"):
        return parts[-1]
    return "volume" if entry.get("anchor_family") else "accessory"


def _skip(block: Any) -> bool:
    tag = str(getattr(block, "rationale_tag", "") or "")
    if tag.startswith(("cardio", "mobility", "stretch")):
        return True
    return any(getattr(s, "duration_seconds", None) for s in block.sets or [])


AUTHORED_LINE_MAX_CHARS = 120
_AUTHORED_EFFORT_RE = re.compile(r"^RPE \d+(?:\.5)?(?:–\d+(?:\.5)?)?(?:, last set RPE \d+(?:\.5)?(?:–\d+(?:\.5)?)?)?$")
# what a kept line may not carry beyond the grammar's banned vocabulary (`hevy_note_grammar.BANNED`, linter L1) and its
# restated-row shapes (L2): a load x reps, a set count, `@`, the tier words of the retired branch menus, and the
# pick-load form's own subject (that W line is the composer's)
_AUTHORED_DIRTY_RE = re.compile(
    r"\d\s*(?:x|×)\s*\d|\b\d+\s*(?:x|×)\b|\bsets? of\b|\d+ sets?\b|Last:|@|\bfloor\b|subtract|"
    r"GREEN|YELLOW|RED\b|\d+(?:\.\d+)?\s*(?:lb|lbs)\b|\bno (?:load|history)\b|\blog it\b|pick (?:it|a load|the load)",
    re.I,
)


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_COUNTED_RE = re.compile(r"RPE \d+(?:\.5)?(?:[–-]\d+(?:\.5)?)?|\b\d+ (?:reps?|min|weeks?|days?|steps?)\b|\b\d+s\b")


def _stray_number(line: str) -> bool:
    """A digit outside an effort (`RPE 9`), a rep / minute / week count or a rep-target plural (`8s`) — a load, a date or
    a set row restated, which the rows and PREVIOUS already show (standard §1.1)."""
    return any(ch.isdigit() for ch in _COUNTED_RE.sub("", line))


def authored_lines(note: str | None) -> dict[str, str]:
    """The chat author's sentences that already read as the standard (#5428), for `compose_blocks(authored=...)`:
    `effort` — a sentence that IS an effort line (`RPE 7`), kept as line 1; `line` — the first other sentence of at most
    AUTHORED_LINE_MAX_CHARS with no restated row, no load or date, no banned word — the coach's own cue ("Elbows to
    hips, no lean-back."), which the standard counts as the exercise's cue (§4). Everything else is left to the composer
    and kept on the record as `detail`. Empty when nothing qualifies."""
    out: dict[str, str] = {}
    for raw in str(note or "").split("\n"):
        for part in _SENTENCE_RE.split(raw):
            line = " ".join(part.split())
            if not line:
                continue
            if _AUTHORED_EFFORT_RE.match(line.rstrip(".")):
                out.setdefault("effort", line.rstrip("."))
            elif "line" not in out and line not in hevy_note_grammar.PREP_CUES.values() and _clean_authored(line):
                out["line"] = line
    return out


def _clean_authored(line: str) -> bool:
    """A sentence fit for the cue slot: short, nothing banned, no number, and no second effort (line 1 is the only RPE)."""
    if any(re.search(pat, line, flags=0 if case else re.I) for pat, _label, case in hevy_note_grammar.BANNED):
        return False
    return (
        len(line) <= AUTHORED_LINE_MAX_CHARS
        and not hevy_note_grammar.TRUNCATION_RE.search(line)
        and not hevy_note_grammar.RESTATED_ROWS_RE.search(line)
        and not _AUTHORED_DIRTY_RE.search(line)
        and not _stray_number(line)
        and not re.search(r"\bRPE\b", line)
    )


def _step_due_line(prog: dict[str, Any], history: list[dict[str, Any]] | None) -> str:
    """The chat path's not-carried LOAD step (#5057, #5428): the rows hold the author's load, so the note names the step
    as a delta (never a load the rows would contradict) and the run that earned it: `Step due: +5 lb, 10s were RPE 8 twice.`"""
    inc_lb = (float(prog.get("next_load_kg") or 0) - float(prog.get("from_load_kg") or 0)) / LB_IN_KG
    return f"{hevy_note_grammar.STEP_DUE_HEAD}{round(inc_lb * 2) / 2:g} lb, {_stall_why(prog, history)}."


def _engine_reason(
    block: Any, entry: dict[str, Any], row: dict[str, Any], previous: dict[str, Any] | None, history: list | None, intensity: str
) -> str:
    """The computed reason for a block with a fresh PREVIOUS (`reason_line`), or the chat path's step-due line."""
    prog = row.get("progression") or {}
    if prog.get("authored_below") and prog.get("step_kind") == "load":
        return _step_due_line(prog, history)
    working = _working(block.sets)
    row_lb = _top_lb(block.sets)
    rep_lo = min((int(getattr(s, "rep_range_start", 0) or 0) for s in working), default=0) or None
    return reason_line(
        prog=prog,
        intensity=intensity,
        row_lb=row_lb,
        previous=previous,
        step_lb=implement_step_lb(entry.get("equipment"), row_lb),
        rep_lo=rep_lo,
        rep_hi=_rep_hi(block.sets),
        history=history,
        re_entry=bool(row.get("layoff_reason")),
    )


def _stale_reason(block: Any, entry: dict[str, Any], previous: dict[str, Any], target_date: str) -> str:
    """A stale PREVIOUS (§3.3) still shows in Hevy's PREVIOUS column, so a row more than one step from it says why
    (`hevy_note_grammar.stale_reason_line`), or "" within a step / on a stack with no fixed step."""
    row_lb = _top_lb(block.sets)
    word = delta_word(row_lb, previous.get("lb"), implement_step_lb(entry.get("equipment"), row_lb))
    if not word:
        return ""
    return hevy_note_grammar.stale_reason_line(
        word, hevy_note_grammar.gap_text(_days_between(str(previous.get("date") or ""), target_date))
    )


def _has_load(block: Any) -> bool:
    return any(getattr(s, "weight_kg", None) for s in _working(block.sets))


_LOADED_EQUIPMENT = ("barbell", "dumbbell", "machine", "cable", "kettlebell", "plate")
_UNLOADED_HEVY_TYPES = ("reps_only", "duration", "distance_duration")


def _feeler_fits(block: Any, entry: dict[str, Any], chat: bool) -> bool:
    """Is the pick-load form right for this block? Never for a bodyweight / band / timed movement (there is no load to
    find). On the chat path also never when the author put a load on the rows (the load is chosen), and only for a
    catalog implement that takes one (a `tmpl:` block the catalog does not know, e.g. a burpee, gets no feeler)."""
    if entry.get("hevy_type") in _UNLOADED_HEVY_TYPES or entry.get("equipment") in ("none", "resistance_band"):
        return False
    if chat:
        return not _has_load(block) and entry.get("equipment") in _LOADED_EQUIPMENT
    return True


def no_jumps_line(caps: dict[str, Any]) -> str:
    """A capped exposure's reason (standard §3.2, R3 "opts out by name"): exposure 1 names the gap,
    `No jumps: first time in 19 weeks.`; exposures 2–3 `No jumps today: session 2 back after a break.`"""
    n = int(caps.get("exposure") or 1)
    gap = hevy_note_grammar.gap_text(caps.get("gap_days"))
    if n == 1:
        return f"{hevy_note_grammar.NO_JUMPS}: first time in {gap}." if gap else f"{hevy_note_grammar.NO_JUMPS}: first time on it."
    return f"{hevy_note_grammar.NO_JUMPS} today: session {n} back after a break."


def _ex1_room() -> int:
    """Phone lines exercise 1's own note may take under the session block (standard §7: exercise 1 total ≤ 11, the
    block, then a blank line), measured on the longest ‹Day› the block can carry."""
    from training import session_block

    longest = max(hevy_note_grammar.SESSION_DAYS, key=len)
    block = session_block.render(longest, session_block.compounds_band(), session_block.step_lb())
    return min(hevy_note_grammar.LIFT_MAX_LINES, hevy_note_grammar.EX1_MAX_LINES - 1 - hevy_note_grammar.phone_lines(block))


def _cue_for(family: str | None, entry: dict[str, Any], lines: list[str], room: int) -> str:
    """The family cue, with the #5049 prep clause when the note still fits its budget with it (R8: one prep cue per
    compound family, "if overkill skip"); a reason line no longer drops the prep by itself."""
    with_prep = movement_cues.cue_line(family, entry.get("anchor_family"), with_prep=True)
    if hevy_note_grammar.phone_lines("\n".join(lines + [with_prep])) <= room:
        return with_prep
    return movement_cues.cue_line(family, entry.get("anchor_family"), with_prep=False)


def compose_blocks(
    blocks: list[Any],
    catalog_movements: dict[str, Any],
    *,
    load_floors: dict[str, Any] | None,
    history_index: dict[str, list] | None,
    target_date: str,
    rotations: dict[str, str] | None = None,
    authored: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Rewrite every lift block's note to the standard, IN PLACE, after every load and warm-up pass. Returns the
    `inputs_snapshot` record: `previous_loads` (Hevy's PREVIOUS, for the linter) and `lift_notes` (per movement: the
    note, the reason kind and its line, whether the pick-load form fired, and the replaced text as `detail`).

    `rotations` (`variant_rotation.swaps`: served key -> the title it replaces) gives a rotated accessory its ONE reason
    line, `New: replaces …` (#5083) — only when the movement is genuinely new to him: NO PREVIOUS at all (the 2026-10-30
    re-grade: a hammer curl and a face pull he had logged weeks before read "New"; re-grade #2, 2026-10-31: a machine
    lateral raise whose PREVIOUS column showed 65 lb x 10 from 2024 read "New" beside a 35 lb row). A stale PREVIOUS
    more than one step from the row gets `stale_reason_line` (`Lighter: first time in 2 years.`) instead; a rotation onto
    a lift with any PREVIOUS keeps its computed reason and the swap stays on the record (`rotation_of`). The line never
    outranks a capped exposure's `No jumps` line, and the pick-load W line still follows it — that line is the
    instruction for the feeler W row, not a second reason.

    A capped exposure (OD1, the ramp's `exposure_caps`) reads `RPE 7` and opts out of the load rule by name
    (`no_jumps_line`); a critic's layoff set cap gets the same treatment downstream (`session_block.add_capped_reason`).

    `authored` is the chat path's (`draft_custom`, #5428): per movement, the author's own sentences that already read as
    the standard (`authored_lines`) — `effort` replaces line 1, `line` takes the cue slot (a chat-era technique cue counts
    as the cue, standard §4, so the family cue is not added beside it). On that path a block whose rows carry the
    author's load never gets the pick-load feeler (the load is chosen)."""
    from training.exercise_history import previous_load

    movements = (load_floors or {}).get("movements") or {}
    previous_loads: dict[str, Any] = {}
    notes: dict[str, Any] = {}
    seen_families: set[str] = set()
    for index, block in enumerate(blocks or []):
        if _skip(block):
            continue
        key = str(block.movement_key)
        entry = (catalog_movements or {}).get(key) or {}
        tid = entry.get("hevy_template_id_hint") or (key[len("tmpl:") :] if key.startswith("tmpl:") else None)
        previous = previous_load(history_index, tid, target_date)
        if previous is not None:
            previous_loads[key] = previous
        intensity = _intensity_of(block, entry)
        family = movement_cues.family_of(key, entry)
        detail = str(block.notes or "")
        if intensity == "carry" or family == "carry":
            block.notes = exposure_cue("carry", [])
            seen_families.add("carry")
            notes[key] = {"note": block.notes, "reason": None, "reason_line": None, "pick_load": False, "detail": detail}
            continue
        own = (authored or {}).get(key) or {}
        row = movements.get(key) or {}
        caps = (row.get("ramp") or {}).get("exposure_caps")
        stale = is_stale(previous, target_date)
        line1 = own.get("effort") or exposure_cue(intensity, [{}] * max(1, len(_working(block.sets))))
        line2, pick, reason_kind = "", False, None
        if caps:
            # OD1: a capped exposure after a long gap opts out of the session's load rule, by name
            line1 = effort_line(caps.get("rpe_max"))
            line2, reason_kind = no_jumps_line(caps), "no_jumps"
        elif stale:
            pick = _feeler_fits(block, entry, authored is not None) and _add_feeler(block)
            reason_kind = "pick_load" if pick else None
            if previous is not None:
                line2 = _stale_reason(block, entry, previous, target_date)
                reason_kind = line2.split(":")[0] if line2 else reason_kind
        else:
            line2 = _engine_reason(block, entry, row, previous, (history_index or {}).get(tid) if tid else None, intensity)
            reason_kind = line2.split(":")[0] if line2 else None
        swapped = (rotations or {}).get(key)
        lead = rotation_line(swapped) if swapped and previous is None and reason_kind != "no_jumps" else ""
        if lead:
            reason_kind = "rotation"
        pick_line = (PICK_LOAD_LINE if _has_load(block) else PICK_LOAD_OPEN_LINE) if pick else ""
        body = [x for x in (line1, lead, line2, pick_line) if x]
        cue = own.get("line") or ""
        if family and family not in seen_families:
            cue = cue or _cue_for(family, entry, body, _ex1_room() if index == 0 else hevy_note_grammar.LIFT_MAX_LINES)
            seen_families.add(family)
        block.notes = "\n".join(body + ([cue] if cue else []))
        notes[key] = {
            "note": block.notes,
            "reason": reason_kind,
            "reason_line": (lead or line2) or None,
            "authored_line": own.get("line"),
            "pick_load": pick,
            "detail": detail,
        }
        if swapped and not lead:
            notes[key]["rotation_of"] = swapped  # #5428: a swap onto a lift he did recently is not "New" on the wire
    return {"previous_loads": previous_loads, "lift_notes": notes}


def render_floor_cue(floor: dict[str, Any]) -> str:
    """The floor's line for the CHAT and the dry-run (moved here from `routine_generator`, #5428 — it no longer reaches a
    Hevy note; the generator's note is `compose_blocks`). Factual only — a load, a date, a bodyweight band.

    Never a conditional: the whole defect is a cue that makes the athlete decide
    whether to 'go for' a number the platform already watched him hit.
    """
    if not floor or floor.get("status") != "ok" or not floor.get("floor_kg"):
        return ""
    if floor.get("ramp"):  # #4090: a v0.3 entry-ramp load names the ramp, not a best-load floor
        from training.load_ramp import render_ramp_cue

        return render_ramp_cue(floor)
    from training.routine_generator import _fmt_load

    basis = floor.get("basis") or {}
    reps = "/".join(str(r) for r in (basis.get("reps") or []))
    got = f"{_fmt_load(float(basis.get('weight_kg') or 0))}"
    if reps:
        got += f" x {reps}"
    cue = f"Floor {_fmt_load(float(floor['floor_kg']))} — you did {got} on {basis.get('date')} at {basis.get('bodyweight_lb')} lb."
    if floor.get("layoff_reason"):
        cue += f" Discounted {floor['discount_pct']}% for the layoff."
    return cue + " Down on the day if you must, never up."
