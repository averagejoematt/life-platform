"""
hevy_render.py — where every charter prescription field shows in the Hevy app (#5083).

The machine twin of docs/integrations/hevy-render-table.md: one row per prescription field the
charter adds, naming the Hevy wire field the compiler writes it to, where the app shows it, and
the FALLBACK when Hevy has no field for it. `render_check(body)` reads a COMPILED routine body
(hevy_compiler output — this module builds no wire body and names no template key) and reports,
field by field, where each one will show and whether its line starts inside the visible window.

Why a table at all: a field can pass the API and still never reach the gym floor. #3938 is the
precedent — `routine.notes` was accepted on every write for months and never read back. Hevy's
routine wire has NO field for a reason, an RPE, a bike level or a treadmill speed (RPE is logged
on PERFORMED sets only), so those ride in the exercise's Pinned Routine Note
(`hevy_note_types.PINNED_ROUTINE_NOTE_FIELD`). Only warm-up sets (`type: warmup`), the rep range,
rest and supersets have native homes.

THE ORDERING RULE (so a reason line is never the part a cut lands on):
  1. Exercise 0's note opens with the session WHY line (`routine_title.format_why_note`), which
     stays under VISIBLE_NOTE_CHARS.
  2. Each exercise's OWN note opens with its prescription line: the progression / stall-step
     reason (`routine_generator._progress_block`, `draft_custom_session.attach_step_due`), the
     cardio dose line (`cardio_note` line 1), the minimum-session cue (`disruption._cue`).
  3. History cues, the warm-up clause, the branch menu (`hevy_compiler._place_routine_note`) and
     the critics' block (`tools_plan._place_block_on_first_exercise`) come after.

VISIBLE_NOTE_CHARS is evidence, not a contract: the owner observed Hevy showing ~150 characters
of an exercise note (#4070, `mcp/tools_plan.HEVY_NOTE_OBSERVED_VISIBLE_CHARS`, a must-agree
pair pinned by tests/test_hevy_render_5083.py). It sizes this report's window; nothing truncates
on it. The live proof (a committed routine opened in the app) is what settles it.

Pure: no I/O, no clock.
"""

from __future__ import annotations

import re
from typing import Any

from training.cardio_note import LINE1_RE
from training.hevy_note_types import PINNED_ROUTINE_NOTE_FIELD
from training.warmup_sets import is_warmup

RENDER_TABLE_VERSION = "hevy-render@1.0.0"

# The owner-observed visible window of a Hevy note (#4070). Sizes the report; never a truncation.
VISIBLE_NOTE_CHARS = 150

# Where a row lands. `native` = a Hevy field built for it; `note` = the Pinned Routine Note
# fallback; `not_shown` = carried in the IR only, by design; `deferred` = no producer yet.
NATIVE, NOTE, NOT_SHOWN, DEFERRED = "native", "note", "not_shown", "deferred"

RENDER_TABLE: tuple[dict[str, str], ...] = (
    {
        "field": "session_note",
        "issue": "#3938 #5069",
        "producer": "routine_title.format_why_note",
        "home": NOTE,
        "wire": "routine.exercises[0].notes (head)",
        "shows": "first exercise's Pinned Routine Note, first line",
        "fallback": "routine.notes never reads back (#3938), so the session line heads exercise 0's note; kept under the window",
    },
    {
        "field": "progression_reason",
        "issue": "#5052",
        "producer": "load_progression.next_prescription",
        "home": NOTE,
        "wire": "routine.exercises[].notes",
        "shows": "that exercise's Pinned Routine Note, first line",
        "fallback": "no reason field on the routine wire; leads the exercise's own note",
    },
    {
        "field": "stall_step",
        "issue": "#5057",
        "producer": "load_progression.stall_step",
        "home": NOTE,
        "wire": "routine.exercises[].notes",
        "shows": "that exercise's Pinned Routine Note, first line",
        "fallback": "no reason field on the routine wire; leads the exercise's own note (chat drafts: 'Step due:')",
    },
    {
        "field": "rotation_note",
        "issue": "#5075",
        "producer": "none yet (#5075 deferred)",
        "home": DEFERRED,
        "wire": "routine.exercises[].notes (planned)",
        "shows": "that exercise's Pinned Routine Note (planned)",
        "fallback": "when built: leads the note after the progression reason",
    },
    {
        "field": "cardio_level",
        "issue": "#5048 #5076",
        "producer": "cardio_note.compose (line 1)",
        "home": NOTE,
        "wire": "routine.exercises[].notes",
        "shows": "the cardio exercise's Pinned Routine Note, line 1 ('level N')",
        "fallback": "no level field on a routine set; line 1 of the note",
    },
    {
        "field": "cardio_speed",
        "issue": "#5048 #5076",
        "producer": "cardio_note.compose (line 1)",
        "home": NOTE,
        "wire": "routine.exercises[].notes",
        "shows": "the cardio exercise's Pinned Routine Note, line 1 ('at S mph')",
        "fallback": "no speed field on a routine set; line 1 of the note",
    },
    {
        "field": "cardio_rpe",
        "issue": "#5048 #5076",
        "producer": "cardio_note.compose (line 1)",
        "home": NOTE,
        "wire": "routine.exercises[].notes",
        "shows": "the cardio exercise's Pinned Routine Note, line 1 ('RPE a-b')",
        "fallback": "RPE is logged on performed sets only; line 1 of the note",
    },
    {
        "field": "cardio_duration",
        "issue": "#5048",
        "producer": "the cardio block's sets",
        "home": NATIVE,
        "wire": "routine.exercises[].sets[].duration_seconds",
        "shows": "the set row's time column (also 'N min' on note line 1)",
        "fallback": "-",
    },
    {
        "field": "warmup_sets",
        "issue": "#5049",
        "producer": "warmup_sets.attach_warmups",
        "home": NATIVE,
        "wire": "routine.exercises[].sets[].type = warmup",
        "shows": "set rows marked W, ahead of the working sets; 'Warm up:' clause in the note",
        "fallback": "-",
    },
    {
        "field": "effort_ceiling",
        "issue": "#5058",
        "producer": "effort_ceilings (via routine_title / program_structure cues)",
        "home": NOTE,
        "wire": "routine.exercises[].notes",
        "shows": "'RPE a-b' in the session line and the slot cue",
        "fallback": "no RPE field on the routine wire; the note",
    },
    {
        "field": "rep_range",
        "issue": "#5052",
        "producer": "the slot's rep scheme",
        "home": NATIVE,
        "wire": "routine.exercises[].sets[].rep_range",
        "shows": "the set row's reps column ('6-10')",
        "fallback": "-",
    },
    {
        "field": "rest_seconds",
        "issue": "-",
        "producer": "the block's rest",
        "home": NATIVE,
        "wire": "routine.exercises[].rest_seconds",
        "shows": "the exercise's rest timer",
        "fallback": "-",
    },
    {
        "field": "superset_id",
        "issue": "-",
        "producer": "the block's superset",
        "home": NATIVE,
        "wire": "routine.exercises[].superset_id",
        "shows": "the exercises grouped as a superset",
        "fallback": "-",
    },
    {
        "field": "minimum_session",
        "issue": "#5088",
        "producer": "disruption.to_routine",
        "home": NOTE,
        "wire": "routine.exercises[0].notes (head) + routine.exercises[].notes",
        "shows": "the session line and each exercise's 'Minimum:' cue",
        "fallback": "the title is the convention's at commit (Phase - Type - N - Y); the label rides the session line",
    },
    {
        "field": "charter_version",
        "issue": "#5068",
        "producer": "training_charter.charter_version",
        "home": NOT_SHOWN,
        "wire": "none (inputs_snapshot only)",
        "shows": "not shown; the IR carries it",
        "fallback": "-",
    },
)

FIELDS = tuple(r["field"] for r in RENDER_TABLE)

# The producers' own grammars (their lead words), so a field is found by what wrote it.
_PROGRESSION_RE = re.compile(r"^(?:\+\d+(?:\.\d+)? lb to \d|\+\d+ reps? to \d|hold\b|floor \d|re-entry:)")
_STALL_RE = re.compile(r"^(?:Step due: )?\+\d+(?:\.\d+)? (?:lb|reps?) to .*self-reported RPE")
_RPE_RE = re.compile(r"\bRPE \d")
_MINIMUM_PREFIX = "Minimum:"  # disruption._cue's lead word


def _routine(body: dict[str, Any]) -> dict[str, Any]:
    return (body or {}).get("routine") or {}


def _own_note(i: int, note: str, session: str) -> tuple[str, int]:
    """(exercise i's OWN note, its offset in the wire note) — exercise 0's starts after the session line."""
    if i == 0 and session and note.startswith(session):
        rest = note[len(session) :]
        stripped = rest.lstrip("\n")
        return stripped, len(note) - len(stripped)
    return note, 0


def _hit(where: str, offset: int) -> dict[str, Any]:
    return {"where": where, "offset": offset, "in_window": offset < VISIBLE_NOTE_CHARS}


def _note_hits(i: int, own: str, base: int) -> dict[str, list[dict[str, Any]]]:
    """The charter fields found in one exercise's own note, each with where its line starts."""
    where = f"exercise {i + 1} note"
    out: dict[str, list[dict[str, Any]]] = {}
    first = own.split("\n", 1)[0]
    m = LINE1_RE.match(first)
    if m:
        if m.group("level"):
            out["cardio_level"] = [_hit(where + ", line 1", base)]
        if m.group("mph") or m.group("walk_mph"):
            out["cardio_speed"] = [_hit(where + ", line 1", base)]
        if _RPE_RE.search(m.group("effort") or ""):
            out["cardio_rpe"] = [_hit(where + ", line 1", base)]
    elif _STALL_RE.match(own):
        out["stall_step"] = [_hit(where + ", first line", base)]
    elif _PROGRESSION_RE.match(own):
        out["progression_reason"] = [_hit(where + ", first line", base)]
    if own.startswith(_MINIMUM_PREFIX):
        out["minimum_session"] = [_hit(where + ", first line", base)]
    if not m and (rpe := _RPE_RE.search(own)):
        out["effort_ceiling"] = [_hit(where, base + rpe.start())]
    return out


def _set_hits(i: int, ex: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    sets = ex.get("sets") or []
    where = f"exercise {i + 1}"
    out: dict[str, list[dict[str, Any]]] = {}
    warm = [s for s in sets if is_warmup(s)]
    if warm:
        out["warmup_sets"] = [{"where": f"{where} set rows ({len(warm)} W)", "offset": None, "in_window": True}]
    if any(s.get("duration_seconds") for s in sets):
        out["cardio_duration"] = [{"where": f"{where} set rows (time)", "offset": None, "in_window": True}]
    if any(s.get("rep_range") for s in sets):
        out["rep_range"] = [{"where": f"{where} set rows (reps)", "offset": None, "in_window": True}]
    if ex.get("rest_seconds"):
        out["rest_seconds"] = [{"where": f"{where} rest timer", "offset": None, "in_window": True}]
    if ex.get("superset_id") is not None:
        out["superset_id"] = [{"where": f"{where} superset", "offset": None, "in_window": True}]
    return out


def _warmup_order_problems(i: int, ex: dict[str, Any]) -> list[str]:
    seen_work = False
    for s in ex.get("sets") or []:
        if not is_warmup(s):
            seen_work = True
        elif seen_work:
            return [f"exercise {i + 1}: a warm-up set sits after a working set"]
    return []


def render_check(body: dict[str, Any], session_note: str | None = None) -> dict[str, Any]:
    """Where each charter field of a compiled routine body will show in the Hevy app.

    `session_note` is the WHY line the compiler was handed (`why_note`); with it the check can
    tell exercise 0's own note from the session line ahead of it. Returns `fields` (one row per
    RENDER_TABLE field: `status` lands | beyond_window | absent | deferred | not_shown, and
    `found`), the session line's length against the window, and `problems` (a reason line that
    starts beyond the window, a session line over it, a warm-up set after a working set)."""
    routine = _routine(body)
    exercises = routine.get("exercises") or []
    session = (session_note or "").strip()
    found: dict[str, list[dict[str, Any]]] = {}
    problems: list[str] = []
    if session:
        found.setdefault("session_note", []).append(_hit("exercise 1 note, line 1", 0))
        if rpe := _RPE_RE.search(session):
            found.setdefault("effort_ceiling", []).append(_hit("session line", rpe.start()))
        if exercises and not str(exercises[0].get(PINNED_ROUTINE_NOTE_FIELD) or "").startswith(session):
            problems.append("the session line does not head exercise 1's note")
        if len(session) > VISIBLE_NOTE_CHARS:
            problems.append(f"the session line is {len(session)} chars, over the {VISIBLE_NOTE_CHARS}-char visible window")
    for i, ex in enumerate(exercises):
        own, base = _own_note(i, str(ex.get(PINNED_ROUTINE_NOTE_FIELD) or ""), session)
        for by_field in (_note_hits(i, own, base), _set_hits(i, ex)):
            for k, v in by_field.items():
                found.setdefault(k, []).extend(v)
        problems += _warmup_order_problems(i, ex)
    rows = []
    for r in RENDER_TABLE:
        hits = found.get(r["field"], [])
        if r["home"] in (DEFERRED, NOT_SHOWN):
            status = r["home"]
        elif not hits:
            status = "absent"
        elif all(h["in_window"] for h in hits):
            status = "lands"
        else:
            status = "beyond_window"
            problems.append(f"{r['field']}: starts past the {VISIBLE_NOTE_CHARS}-char visible window at {hits[0]['where']}")
        rows.append({"field": r["field"], "status": status, "wire": r["wire"], "shows": r["shows"], "found": hits})
    return {
        "version": RENDER_TABLE_VERSION,
        "title": routine.get("title", ""),
        "visible_note_chars": VISIBLE_NOTE_CHARS,
        "session_note": {"text": session, "chars": len(session), "under_window": len(session) <= VISIBLE_NOTE_CHARS},
        "fields": rows,
        "problems": problems,
    }
