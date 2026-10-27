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
of the engine's start load, and `W set: up to 8 easy reps, find the load.` in place of a reason.

WHAT LEAVES THE WIRE, NOT THE RECORD. The passes still compute everything they did — the floor, the ramp, the hold, the
progression — and their text is kept on `inputs_snapshot["lift_notes"][key]["detail"]` and in the rationale, where
the dry-run and the coach chat read it. Only the Hevy note is rewritten.

Pure: every input is a value the generator already holds. No reads, no clock.
"""

from __future__ import annotations

import re
from typing import Any

from training import movement_cues
from training.rep_scheme import LB_IN_KG, implement_step_lb
from training.session_cues import effort_line, exposure_cue

STALE_AFTER_DAYS = 28
"""A PREVIOUS older than this is not a load to quote (the review's 'Last: 36.5kg … (19 Sep)' five weeks on, and a 2022
chest-fly anchor at another bodyweight); the note becomes the pick-load form. 28 days is the module's detraining line
(`load_ramp.DETRAINING_ANCHOR_AGE_DAYS`): past it, the engine's own anchor is discounted as detrained."""

PICK_LOAD_W_REPS = 8
PICK_LOAD_LINE = f"W set: up to {PICK_LOAD_W_REPS} easy reps, find the load."
ROTATION_HEAD = "New: replaces "


def rotation_line(replaced_title: str) -> str:
    """The rotated accessory's one reason line (#5083 / #5075, standard §3.2 voice): `New: replaces Calf Press.`
    — the exercise it stands in for, by the title he knows from Hevy. Never a slot id, a week count or an issue number."""
    return f"{ROTATION_HEAD}{str(replaced_title).strip().rstrip('.')}."


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
    The same rule as `hevy_note_grammar.delta_word` (Lane D's linter); a stack with no fixed step is never judged."""
    if row_lb is None or previous_lb is None or not step_lb:
        return None
    diff = float(row_lb) - float(previous_lb)
    if diff > step_lb + 1e-6:
        return "Heavier"
    if -diff > step_lb + 1e-6:
        return "Lighter"
    return None


def _rpe_text(rpe: Any) -> str:
    return f"RPE {float(rpe):g}"


def _heavier_why(previous: dict[str, Any] | None) -> str:
    """'15 reps was RPE 7' — what he did last time that earns the heavier row."""
    if not previous or not previous.get("reps"):
        return "a step up from last time"
    rpe = previous.get("rpe")
    return f"{int(previous['reps'])} reps was {_rpe_text(rpe)}" if rpe is not None else f"{int(previous['reps'])} reps last time"


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
    earned, or any top row more than one step from PREVIOUS. A reason never repeats a number the rows already show."""
    prog = prog or {}
    if prog.get("basis") == "step" and prog.get("step_kind") == "reps" and prog.get("next_reps") and rep_hi:
        return f"Now aiming {int(prog['next_reps'])}–{int(rep_hi)}: {_stall_why(prog, history)}."
    word = delta_word(row_lb, (previous or {}).get("lb"), step_lb)
    if prog.get("basis") == "step" and prog.get("changes"):
        word = word or "Heavier"
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
# what a kept line may not carry: a restated row (a load x reps, a set count, `Last:`, `@ load`), an effort word other
# than RPE, kg, and the engine/medical/bookkeeping vocabulary the standard bans (§5)
_AUTHORED_DIRTY_RE = re.compile(
    r"\d\s*(?:x|×)\s*\d|\b\d+\s*(?:x|×)\b|\bsets? of\b|\d+ sets?\b|Last:|@|\bkg\b|\d\s*kg|\bRIR\b|in the tank|\bleave \d|"
    r"#\d|\bv\d+\.\d|§|critic|red team|charter|engine|platform|tripwire|\bfloor\b|\bramp\b|e1RM|\banchor\b|\bband\b|"
    r"subtract|never up|ECG|\bAF\b|[Ss]inus|cardiolog|beta-blocker|metoprolol|protein|calorie|badge|weigh|Optional if|as written|…|"
    r"🟢|🟡|🔴|GREEN|YELLOW|RED\b|Whoop|\bhis\b|\bhe\b|\bhim\b|\d+(?:\.\d+)?\s*(?:lb|lbs)\b",
    re.I,
)


_COUNTED_RE = re.compile(r"RPE \d+(?:\.5)?(?:[–-]\d+(?:\.5)?)?|\b\d+ (?:reps?|min|weeks?|days?|steps?)\b|\b\d+s\b")


def _stray_number(line: str) -> bool:
    """A digit outside an effort (`RPE 9`), a rep / minute / week count or a rep-target plural (`8s`) — a load, a date or
    a set row restated, which the rows and PREVIOUS already show (standard §1.1)."""
    return any(ch.isdigit() for ch in _COUNTED_RE.sub("", line))


def authored_lines(note: str | None) -> dict[str, str]:
    """The chat author's lines that already read as the standard (#5428), for `compose_blocks(authored=...)`:
    `effort` — an author line that IS an effort line (`RPE 7`), kept as line 1; `reason` — the first other line of at most
    AUTHORED_LINE_MAX_CHARS with no restated row, no load, no banned word — his coach's own one reason or cue. Everything
    else is left to the composer (and kept on the record as `detail`). Empty when nothing qualifies."""
    out: dict[str, str] = {}
    for raw in str(note or "").split("\n"):
        line = " ".join(raw.split())
        if not line:
            continue
        if _AUTHORED_EFFORT_RE.match(line):
            out.setdefault("effort", line)
        elif (
            "reason" not in out and len(line) <= AUTHORED_LINE_MAX_CHARS and not _AUTHORED_DIRTY_RE.search(line) and not _stray_number(line)
        ):
            out["reason"] = line
    return out


def _step_due_line(prog: dict[str, Any], history: list[dict[str, Any]] | None) -> str:
    """The chat path's not-carried LOAD step (#5057, #5428): the rows hold the author's load, so the note names the step
    as a delta (never a load the rows would contradict) and the run that earned it: `Step due: +5 lb, 10s were RPE 8 twice.`"""
    inc_lb = (float(prog.get("next_load_kg") or 0) - float(prog.get("from_load_kg") or 0)) / LB_IN_KG
    return f"Step due: +{round(inc_lb * 2) / 2:g} lb, {_stall_why(prog, history)}."


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
    line, `New: replaces …` (#5083). It outranks a PREVIOUS delta reason (the swap is why the row is new) but
    never a capped exposure's `No jumps` line, and the pick-load W line still follows it — that line is the instruction
    for the feeler W row, not a second reason.

    `authored` is the chat path's (`draft_custom`, #5428): per movement, the author's own lines that already read as the
    standard (`authored_lines`) — `effort` replaces line 1, `reason` takes the one reason slot over a computed one. On
    that path a block whose rows carry the author's load never gets the pick-load feeler (the load is chosen)."""
    from training.exercise_history import previous_load

    movements = (load_floors or {}).get("movements") or {}
    previous_loads: dict[str, Any] = {}
    notes: dict[str, Any] = {}
    seen_families: set[str] = set()
    for block in blocks or []:
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
        line1 = own.get("effort") or exposure_cue(intensity, [{}] * max(1, len(_working(block.sets))))
        line2, pick, reason_kind = "", False, None
        if caps:
            # OD1: a capped exposure after a long gap opts out of the session's load rule, by name
            line1 = effort_line(caps.get("rpe_max"))
            line2, reason_kind = f"No jumps today: session {int(caps.get('exposure') or 1)} back after a break.", "no_jumps"
        elif is_stale(previous, target_date):
            pick = _feeler_fits(block, entry, authored is not None) and _add_feeler(block)
            line2, reason_kind = (PICK_LOAD_LINE, "pick_load") if pick else ("", None)
        else:
            line2 = _engine_reason(block, entry, row, previous, (history_index or {}).get(tid) if tid else None, intensity)
            reason_kind = line2.split(":")[0] if line2 else None
        lead = ""  # the one reason that sits ahead of a pick-load line: the swap, or the author's own
        swapped = (rotations or {}).get(key)
        if reason_kind != "no_jumps" and (own.get("reason") or swapped):
            lead = own.get("reason") or rotation_line(swapped or "")
            if reason_kind != "pick_load":
                line2 = ""  # one reason: it replaces the computed one
            reason_kind = "authored" if own.get("reason") else "rotation"
        reason_text = lead or (line2 if line2 and line2 != PICK_LOAD_LINE else "")
        cue = ""
        if family and family not in seen_families:
            cue = movement_cues.cue_line(family, entry.get("anchor_family"), with_prep=not (line2 or lead))
            seen_families.add(family)
        block.notes = "\n".join(x for x in (line1, lead, line2, cue) if x)
        notes[key] = {
            "note": block.notes,
            "reason": reason_kind,
            "reason_line": reason_text or None,
            "pick_load": pick,
            "detail": detail,
        }
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
