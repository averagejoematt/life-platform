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
  1. Exercise 0's note opens with the session block (#5428: the session line, the low-energy line
     and the load rule), written ONCE — by `session_block.place_on_first` on the draft paths, and the
     compiler's WHY (`routine_title.format_why_note`) only when no block is there.
  2. Each exercise's OWN note opens with its prescription line: the progression / stall-step
     reason (`routine_generator._progress_block`, `draft_custom_session.attach_step_due`), the
     cardio dose line (`cardio_note` line 1), the minimum-session cue (`disruption._cue`).
  3. Anything else comes after: the branch menu (`hevy_compiler._place_routine_note`). Since #5428
     the wake-recovery band block and the critics' block no longer reach the wire.

VISIBLE_NOTE_CHARS is RETIRED as a window (#5428): the owner's in-app screenshots (2026-10-26) show
Hevy renders an exercise note IN FULL, so length costs scroll, not visibility. No problem is raised
on it any more; `in_window` stays on each hit as information only. Length is now the note linter's
phone-line budget (`hevy_note_lint` rule L7). The constant stays until its must-agree twin
`mcp/tools_plan.HEVY_NOTE_OBSERVED_VISIBLE_CHARS` is removed with it (#5428 lane A).

THE NOTE LINT (#5428): `render_check` also runs `hevy_note_lint` over the body and reports it as
`note_lint` (mode, problems, not-checked rules), and each lint problem joins `problems` prefixed
NOTE_LINT_PREFIX, so dry_run shows them. Warn mode: nothing here refuses a write.

Pure apart from the note lint's one cached movement-catalog read; no clock.
"""

from __future__ import annotations

import re
from typing import Any

from training.cardio_note import LINE1_RE
from training.hevy_note_types import PINNED_ROUTINE_NOTE_FIELD
from training.warmup_sets import is_warmup

RENDER_TABLE_VERSION = "hevy-render@1.2.0"  # 1.2.0 = the window retired, the note lint joined (#5428)

# The owner-observed visible window of a Hevy note (#4070), retired as a window by #5428 (notes render in full).
VISIBLE_NOTE_CHARS = 150
NOTE_LINT_PREFIX = "note lint: "

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
        "issue": "#5068 #5085",
        "producer": "training_charter.charter_version",
        "home": NOT_SHOWN,
        "wire": "none (inputs_snapshot.charter_version + inputs_snapshot.nightly_predraft.charter_version)",
        "shows": "not shown in any Hevy note or footer; the IR and the pre-draft's draft mark carry it",
        "fallback": "-",
    },
)

FIELDS = tuple(r["field"] for r in RENDER_TABLE)

# The producers' own grammars (their lead words), so a field is found by what wrote it. A reason
# starts a line or a sentence, and it is SEARCHED for anywhere in the note: a reason buried behind
# another block is reported `not_leading` / `beyond_window`, never `absent` (#5083 review).
_LEAD = r"(?:^|(?<=\. ))"
_PROGRESSION_RE = re.compile(_LEAD + r"(?:\+\d+(?:\.\d+)? lb to \d|\+\d+ reps? to \d|hold(?::| \d)|floor \d|re-entry:)", re.M)
_STALL_RE = re.compile(_LEAD + r"(?:Step due: )?\+\d+(?:\.\d+)? (?:lb|reps?) to [^\n]*self-reported RPE", re.M)
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


def _hit(where: str, offset: int, leads: bool = True) -> dict[str, Any]:
    return {"where": where, "offset": offset, "in_window": offset < VISIBLE_NOTE_CHARS, "leads": leads}


def _reason_field(text: str) -> str:
    return "stall_step" if _STALL_RE.match(text) else "progression_reason"


def expected_reasons(ir: Any) -> list[dict[str, str]]:
    """The reason lines the IR says MUST reach the wire, so 'expected but not found' is a problem, not
    `absent`: every generator progression that changed a set (`inputs_snapshot.load_floors`, #5052) and
    every chat-draft step authored below the stall step (`inputs_snapshot.step_due`, #5057)."""
    snap = getattr(ir, "inputs_snapshot", None) or {}
    out: list[dict[str, str]] = []
    for key, mv in ((snap.get("load_floors") or {}).get("movements") or {}).items():
        prog = (mv or {}).get("progression") or {}
        if prog.get("changes") and prog.get("reason"):
            out.append({"field": _reason_field(prog["reason"]), "movement_key": key, "text": prog["reason"]})
    step_due = snap.get("step_due")
    rows: list[Any] = step_due if isinstance(step_due, list) else []
    for row in rows:
        if not row.get("carried") and row.get("reason"):
            out.append({"field": "stall_step", "movement_key": str(row.get("movement_key")), "text": f"Step due: {row['reason']}"})
    return out


def _reason_hits(where: str, own: str, base: int) -> dict[str, list[dict[str, Any]]]:
    """Every progression / stall reason in the note, wherever it sits; `leads` says whether it opens the note."""
    out: dict[str, list[dict[str, Any]]] = {}
    taken: set[int] = set()
    for field, rx in (("stall_step", _STALL_RE), ("progression_reason", _PROGRESSION_RE)):
        for m in rx.finditer(own):
            if m.start() in taken:
                continue
            taken.add(m.start())
            at = ", first line" if m.start() == 0 else f", char {m.start()}"
            out.setdefault(field, []).append(_hit(where + at, base + m.start(), leads=m.start() == 0))
    return out


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
    else:
        out.update(_reason_hits(where, own, base))
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


def _missing(expected: list[dict[str, str]], notes: list[str]) -> dict[str, list[str]]:
    """field -> the movements whose expected reason text is on no exercise note of the wire."""
    out: dict[str, list[str]] = {}
    for e in expected:
        if not any(e["text"] in n for n in notes):
            out.setdefault(e["field"], []).append(e["movement_key"])
    return out


def _status(r: dict[str, str], hits: list[dict[str, Any]], missing: list[str]) -> tuple[str, list[str]]:
    """(the row's status, its problems) — missing > not_leading > lands. (#5428: `beyond_window` is retired — Hevy
    shows a note in full — so a hit past VISIBLE_NOTE_CHARS is no longer a problem.)"""
    f = r["field"]
    if r["home"] in (DEFERRED, NOT_SHOWN):
        return r["home"], []
    if missing:
        return "missing", [f"{f}: expected on the wire for {', '.join(missing)} (the IR records it) but not found in any note"]
    if not hits:
        return "absent", []
    if buried := [h for h in hits if not h.get("leads", True)]:
        return "not_leading", [f"{f}: does not lead its note ({buried[0]['where']}); the ordering rule puts the reason first"]
    return "lands", []


def render_check(body: dict[str, Any], session_note: str | None = None, ir: Any = None) -> dict[str, Any]:
    """Where each charter field of a compiled routine body will show in the Hevy app.

    `session_note` is the WHY line the compiler was handed (`why_note`); with it the check can
    tell exercise 0's own note from the session line ahead of it. `ir` (the RoutineSpec that was
    compiled) names the reason lines that MUST be on the wire (`expected_reasons`), so a reason the
    IR recorded but the wire lacks is a problem, never `absent`. Returns `fields` (one row per
    RENDER_TABLE field: `status` lands | not_leading | missing | absent | deferred | not_shown, and
    `found`), the session note's length, `note_lint` (#5428: the note linter's result in its mode), and
    `problems` (a reason line that does not lead its note, an expected reason not on the wire, a
    warm-up set after a working set, and every note-lint problem prefixed NOTE_LINT_PREFIX)."""
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
    for i, ex in enumerate(exercises):
        own, base = _own_note(i, str(ex.get(PINNED_ROUTINE_NOTE_FIELD) or ""), session)
        for by_field in (_note_hits(i, own, base), _set_hits(i, ex)):
            for k, v in by_field.items():
                found.setdefault(k, []).extend(v)
        problems += _warmup_order_problems(i, ex)
    expected = expected_reasons(ir) if ir is not None else None
    missing = _missing(expected or [], [str(ex.get(PINNED_ROUTINE_NOTE_FIELD) or "") for ex in exercises])
    rows = []
    for r in RENDER_TABLE:
        hits = found.get(r["field"], [])
        status, row_problems = _status(r, hits, missing.get(r["field"], []))
        problems += row_problems
        rows.append({"field": r["field"], "status": status, "wire": r["wire"], "shows": r["shows"], "found": hits})
    note_lint = _note_lint(body, ir)
    problems += [NOTE_LINT_PREFIX + p for p in note_lint.get("problems", [])]
    return {
        "version": RENDER_TABLE_VERSION,
        "title": routine.get("title", ""),
        "visible_note_chars": VISIBLE_NOTE_CHARS,
        "session_note": {"text": session, "chars": len(session), "under_window": len(session) <= VISIBLE_NOTE_CHARS},
        "expected_reasons": expected,
        "fields": rows,
        "note_lint": note_lint,
        "problems": problems,
    }


def _note_lint(body: dict[str, Any], ir: Any) -> dict[str, Any]:
    """The note linter's verdict on the body (#5428), with its mode. Fail-soft: a linter error is reported, never raised."""
    from training import hevy_note_lint

    try:
        res = hevy_note_lint.lint_wire(body, ir)
    except Exception as e:  # noqa: BLE001 — the dry-run report must not die on a linter bug
        return {"mode": hevy_note_lint.lint_mode(), "error": f"{type(e).__name__}: {e}", "problems": [], "not_checked": ["every rule"]}
    return {"mode": hevy_note_lint.lint_mode(), **res.to_dict()}
