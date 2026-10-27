"""
hevy_note_lint.py — the style linter for Hevy routine notes (#5428; rules L1–L13 of
`docs/coaching/HEVY_NOTE_STANDARD.md` §8).

It reads what Matthew will read: the COMPILED wire body (`hevy_compiler` output) plus the IR it
came from. The IR names each block's movement, which the catalog turns into an implement kind
(`kind_of`), and carries `inputs_snapshot["previous_loads"]` — Hevy's PREVIOUS column, the last
performed working load per movement. Without that key the PREVIOUS rule reports itself
"not checked" by name; it never passes silently.

Where it runs:
  * `hevy_compiler.to_create_body` / `to_update_body` — every writer (the MCP tool, the nightly
    cron, the restamp) passes there. Mode `HEVY_NOTE_LINT_MODE`: `warn` (the default) logs the
    problems and never changes or blocks a write; `off` skips. `enforce` is reserved for the
    commit gate (`mcp/hevy_prescription_gate.py`, lane D2 of #5428), which refuses on
    ENFORCE_RULES; the compiler only ever logs.
  * `hevy_render.render_check` — dry_run shows the problems.
  * CI — tests/test_hevy_note_lint_5428.py over the golden corpus (clean) and the archived
    originals (every one fails).

The prototype is the review's `lint_notes.py` (2026-10-27); every one of its checks is here
under its standard rule id. Pure apart from `catalog=None`, which reads the movement catalog
once per process through `logging_conventions.catalog_movements` (fail-soft: an unread catalog
degrades kinds to the movement key and says so in `not_checked`).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

from training import hevy_note_grammar as g

logger = logging.getLogger(__name__)

LINT_VERSION = "hevy-note-lint@1.0.0"
MODE_ENV = "HEVY_NOTE_LINT_MODE"
MODES = ("off", "warn", "enforce")
DEFAULT_MODE = "warn"
# the rules the commit gate refuses on in enforce mode (code plan, lane D2)
ENFORCE_RULES = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L12")
PREVIOUS_LOADS_KEY = "previous_loads"
RULES = {
    "L1": "no banned token",
    "L2": "no restated rows",
    "L3": "line-1 grammar by note type",
    "L4": "text agrees with the rows (set count, W reps, a reason when a row moves more than one step from PREVIOUS)",
    "L5": "loadable steps; W rows ascend below the work",
    "L6": "one effort expression on a lift's line 1",
    "L7": "phone-line budgets",
    "L8": "safety facts present (family cue, cardio effort leads, no HR lead target)",
    "L9": "clock lines: minutes, at most 3 levels, interval start minutes",
    "L10": "an After line exactly when a Hevy block follows the cardio",
    "L11": "per hand on dumbbell and carry loads only; no speed off the treadmill",
    "L12": "exercise 1 opens with the session block; nothing truncated",
    "L13": "the first dumbbell compound at 50 lb per hand or more has a W row",
}

KG_PER_LB = 0.45359237
Row = tuple[str, Optional[float], Optional[str]]  # ("W" | "N", load in lb or None, reps / "30 min" / None)
Previous = Union[float, list[Optional[float]], None]


@dataclass
class LintExercise:
    name: str
    kind: str  # one of hevy_note_grammar.KINDS
    rows: list[Row]
    note: str
    compound: bool = False
    family: Optional[str] = None  # cue family (hevy_note_grammar.FAMILY_CUES); None = unknown, cue rules skip it
    anchor_family: Optional[str] = None  # catalog anchor family (prep cues)
    previous_lb: Previous = None  # Hevy's PREVIOUS: one load, or one per working row; None = never done / unknown


@dataclass
class LintRoutine:
    exercises: list[LintExercise]
    previous_supplied: bool = False  # inputs_snapshot carried previous_loads
    title: str = ""
    not_checked: list[str] = field(default_factory=list)


@dataclass
class Problem:
    rule: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.rule} {self.where}: {self.message}" if self.where else f"{self.rule} {self.message}"


@dataclass
class LintResult:
    problems: list[Problem]
    not_checked: list[str]
    total_chars: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    def lines(self) -> list[str]:
        return [str(p) for p in self.problems]

    def rules(self) -> set[str]:
        return {p.rule for p in self.problems}

    def to_dict(self) -> dict[str, Any]:
        return {"version": LINT_VERSION, "problems": self.lines(), "not_checked": list(self.not_checked), "total_chars": self.total_chars}


# ── the checks ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _working(rows: list[Row]) -> list[Row]:
    return [r for r in rows if r[0] == "N"]


def _split_session(note: str) -> tuple[Optional[str], str]:
    """(the session block, exercise 1's own note). None when the note does not open with a session line."""
    head, sep, rest = note.partition("\n\n")
    first = head.split("\n", 1)[0]
    if not g.SESSION_LINE_RE.match(first):
        return None, note
    return head, rest if sep else ""


def _lint_session(session: str, note: str, out: list[Problem]) -> None:
    lines = session.split("\n")
    if len(lines[0]) > g.SESSION_LINE_MAX_CHARS:
        out.append(Problem("L7", "session line", f"{len(lines[0])} chars > {g.SESSION_LINE_MAX_CHARS}"))
    is_test = lines[0].startswith(g.TEST_DAY + " · ")
    want = [lines[0]] if is_test else [lines[0], g.LOW_ENERGY_LINE, g.LOAD_RULE_LINE]
    if lines != want:
        out.append(
            Problem("L3", "session block", f"is {len(lines)} line(s); the grammar is the session line, the low-energy line, the load rule")
        )
    if g.phone_lines(session) > g.SESSION_BLOCK_MAX_LINES:
        out.append(Problem("L7", "session block", f"{g.phone_lines(session)} phone lines > {g.SESSION_BLOCK_MAX_LINES}"))
    if g.phone_lines(note) > g.EX1_MAX_LINES:
        out.append(
            Problem(
                "L7",
                "[1]",
                f"exercise 1 note is {g.phone_lines(note)} phone lines > {g.EX1_MAX_LINES}: its set rows leave the first screen",
            )
        )


def _banned(note: str, where: str, out: list[Problem]) -> None:
    for pat, label, case_sensitive in g.BANNED:
        text = note
        for exempt in g.BANNED_EXEMPT.get(label, ()):
            text = text.replace(exempt, "")
        hit = re.search(pat, text, flags=0 if case_sensitive else re.I)
        if hit:
            out.append(Problem("L1", where, f"banned ({label}): {hit.group(0)!r}"))
    if g.TRUNCATION_RE.search(note):
        out.append(Problem("L12", where, "a note is never truncated ('…')"))
    for ln in note.split("\n"):
        if len(ln) > g.LINE_MAX_CHARS:
            out.append(Problem("L7", where, f"line {len(ln)} chars > {g.LINE_MAX_CHARS}: {ln[:40]!r}"))


def _previous_for(prev: Previous, i: int) -> Optional[float]:
    if isinstance(prev, list):
        return prev[i] if i < len(prev) else (prev[-1] if prev else None)
    return prev


def _lint_previous(ex: LintExercise, lines: list[str], where: str, out: list[Problem]) -> None:
    """L4: a working row more than one step from Hevy's PREVIOUS carries a reason, in the right direction."""
    if ex.previous_lb is None or ex.kind == "carry":
        return
    reasons = [ln for ln in lines[1:] if g.REASON_RE.match(ln) or ln.startswith("W set: up to")]
    for i, r in enumerate(_working(ex.rows)):
        prev = _previous_for(ex.previous_lb, i)
        step = g.implement_step_lb(ex.kind, prev) or 5.0
        word = g.delta_word(r[1], prev, step)
        if not word:
            continue
        if not reasons:
            out.append(
                Problem(
                    "L4",
                    where,
                    f"working row {i + 1} is {g.fmt_num(r[1] or 0)} lb against PREVIOUS {g.fmt_num(prev or 0)} lb with no reason line",
                )
            )
            return
        opposite = g.LIGHTER if word == g.HEAVIER else g.HEAVIER
        if any(ln.startswith(opposite + ":") for ln in reasons):
            out.append(Problem("L4", where, f"the reason says {opposite} but row {i + 1} is {word.lower()} than PREVIOUS"))
            return


def _lint_lift(ex: LintExercise, body: str, where: str, out: list[Problem]) -> None:
    lines = body.split("\n")
    l1 = lines[0]
    rx = g.CARRY_LINE1_RE if ex.kind == "carry" else g.EFFORT_RE
    if not rx.match(l1):
        out.append(Problem("L3", where, f"line 1 is not the {'carry' if ex.kind == 'carry' else 'effort'} grammar: {l1!r}"))
    if g.phone_lines(body) > g.LIFT_MAX_LINES:
        out.append(Problem("L7", where, f"lift note {g.phone_lines(body)} phone lines > {g.LIFT_MAX_LINES}"))
    for ln in lines:
        if g.RESTATED_ROWS_RE.search(ln):
            out.append(Problem("L2", where, f"restates the set rows (Hevy shows them, with PREVIOUS): {ln!r}"))
    work = _working(ex.rows)
    msets = g.SET_COUNT_RE.search(body)
    if msets and int(msets.group(1)) != len(work):
        out.append(Problem("L4", where, f"text says {msets.group(1)} sets, the rows hold {len(work)} working sets"))
    loads = g.NAMED_LOAD_RE.findall(body)
    if ex.kind in g.PER_HAND_KINDS and any(not ph for ph in loads):
        out.append(Problem("L11", where, "a dumbbell load without 'per hand'"))
    if ex.kind not in g.PER_HAND_KINDS and "per hand" in body:
        out.append(Problem("L11", where, f"'per hand' on a {ex.kind} lift"))
    for lb in sorted({r[1] for r in work if r[1] is not None}):
        step = g.implement_step_lb(ex.kind, lb) if ex.kind in ("barbell", "dumbbell") else None
        if step and not g.on_step(lb, step):
            out.append(Problem("L5", where, f"{ex.kind} load {g.fmt_num(lb)} lb is not on a {g.fmt_num(step)} lb step"))
    for lb in sorted({r[1] for r in ex.rows if r[0] == "W" and r[1] is not None}):
        if ex.kind in ("barbell", "dumbbell") and not g.on_step(lb, g.WARMUP_ROUNDING_LB):
            out.append(Problem("L5", where, f"warm-up {g.fmt_num(lb)} lb is not on a {g.fmt_num(g.WARMUP_ROUNDING_LB)} lb step"))
    if ex.kind != "carry" and l1.count("RPE") - l1.count("last set RPE") != 1:
        out.append(Problem("L6", where, f"line 1 carries {l1.count('RPE')} RPE expressions"))
    _lint_previous(ex, lines, where, out)


_CLOCK_NUM = re.compile(r"(?<![\w.])(\d+)(?![\w.%])")
_MIN_LIST_BEFORE = re.compile(r"min(?: [\d]+[,]?)*(?:,| and)? ?$")


def _lint_cardio(body: str, where: str, followed: bool, out: list[Problem]) -> None:
    lines = body.split("\n")
    m = g.CARDIO_LINE1_RE.match(lines[0])
    if not m:
        out.append(Problem("L3", where, f"cardio line 1 grammar: {lines[0]!r}"))
    elif "mph" in body and m["machine"] not in g.SPEED_MACHINES:
        out.append(Problem("L11", where, f"speed on a {m['machine']} (an output, not a setting)"))
    if g.phone_lines(body) > g.CARDIO_MAX_LINES:
        out.append(Problem("L7", where, f"cardio note {g.phone_lines(body)} phone lines > {g.CARDIO_MAX_LINES}"))
    if g.CARDIO_MINUTES_ON_LINE1_RE.search(lines[0]):
        out.append(Problem("L2", where, "line 1 restates the duration row"))
    if len(lines[0]) > g.CARDIO_LINE1_MAX_CHARS:
        out.append(Problem("L7", where, f"cardio line 1 {len(lines[0])} chars > {g.CARDIO_LINE1_MAX_CHARS}"))
    if len(body) > g.CARDIO_NOTE_MAX_CHARS:
        out.append(Problem("L7", where, f"cardio note {len(body)} chars > {g.CARDIO_NOTE_MAX_CHARS}"))
    clock = [ln for ln in lines if ln.startswith(g.CLOCK_PREFIX)]
    hard = bool(m and m["hard"])
    rpe_lo = float(m["rpe"].split("–")[0]) if m else 0.0
    if (hard or rpe_lo >= 6) and not clock:
        out.append(Problem("L9", where, "a tempo, hill or interval ride without a ⌚ clock line"))
    for c in clock:
        if len(c) > g.CLOCK_LINE_MAX_CHARS:
            out.append(Problem("L7", where, f"clock line {len(c)} chars > {g.CLOCK_LINE_MAX_CHARS}"))
        # every number on the clock line is a level (L11), a grade (8%), or carries "min" on one side
        for mt in _CLOCK_NUM.finditer(c):
            before, after = c[: mt.start()], c[mt.end() :]
            if before.endswith("L") or after.startswith(" min") or _MIN_LIST_BEFORE.search(before):
                continue
            out.append(Problem("L9", where, f"clock number {mt.group(1)} has no 'min' unit"))
            break
        levels = set(re.findall(r"L(\d+)", c)) | set(re.findall(r"L(\d+)", lines[0]))
        if len(levels) > g.CLOCK_MAX_LEVELS:
            out.append(Problem("L9", where, f"{len(levels)} levels > {g.CLOCK_MAX_LEVELS}"))
    if hard and not any(re.search(r"at min \d+(?:, \d+)+", c) for c in clock):
        out.append(Problem("L9", where, "intervals without their start minutes"))
    has_after = any(ln.startswith("After:") for ln in lines)
    if followed and not has_after:
        out.append(Problem("L10", where, "a Hevy block follows the cardio but there is no After line"))
    if not followed and has_after:
        out.append(Problem("L10", where, "an After line with nothing after the cardio"))
    for ln in lines:
        if ln.startswith("After:") and len(ln) > g.AFTER_LINE_MAX_CHARS:
            out.append(Problem("L7", where, f"After line {len(ln)} chars > {g.AFTER_LINE_MAX_CHARS}"))
    if g.HR_RE.search(body) and not re.search(r"RPE", lines[0]):
        out.append(Problem("L8", where, "HR used as the lead cardio target (RPE and the talk test lead; zones not re-baselined)"))


def _lint_cues(rt: LintRoutine, bodies: list[str], out: list[Problem], not_checked: list[str]) -> None:
    """L8: the first exercise of each cue family carries a cue; no cue from another family; prep cues match."""
    cue_family = {v: k for k, v in g.FAMILY_CUES.items()}
    prep_family = {v: k for k, v in g.PREP_CUES.items()}
    seen: set[str] = set()
    known = 0
    for i, (ex, body) in enumerate(zip(rt.exercises, bodies)):
        where = f"[{i + 1}] {ex.name}"
        present = {fam for cue, fam in cue_family.items() if cue in body}
        if ex.family is not None:
            known += 1
            wrong = sorted(present - {ex.family})
            if wrong:
                out.append(Problem("L8", where, f"a {wrong[0]} cue on a {ex.family} exercise"))
            if ex.family not in seen:
                lines = body.split("\n")[1:]
                free = [ln for ln in lines if not g.REASON_RE.match(ln) and not ln.startswith("W set:") and ln not in prep_family]
                if ex.family not in present and not free:
                    out.append(Problem("L8", where, f"first {ex.family} exercise without its cue ({g.FAMILY_CUES[ex.family]!r})"))
                seen.add(ex.family)
        for cue, fam in prep_family.items():
            if cue in body and ex.anchor_family is not None and ex.anchor_family != fam:
                out.append(Problem("L8", where, f"the {fam} prep cue on a {ex.anchor_family} lift"))
    if not known:
        not_checked.append("L8 family cue: no exercise's cue family is known")


def lint_routine(rt: LintRoutine) -> LintResult:
    """Every rule over one routine. `problems == []` is the A-grade bar."""
    out: list[Problem] = []
    not_checked = list(rt.not_checked)
    exs = rt.exercises
    bodies: list[str] = []
    total = 0
    for i, ex in enumerate(exs):
        where = f"[{i + 1}] {ex.name}"
        note = ex.note or ""
        body = note
        if i == 0:
            session, body = _split_session(note)
            if session is None:
                out.append(Problem("L12", where, "exercise 1 does not open with the session block"))
            else:
                _lint_session(session, note, out)
        bodies.append(body)
        total += len(note)
        _banned(note, where, out)
        if ex.kind == "cardio":
            followed = any(e.kind != "cardio" for e in exs[i + 1 :])
            _lint_cardio(body, where, followed, out)
        elif ex.kind == "mobility":
            if body and g.phone_lines(body) > g.MOBILITY_MAX_LINES:
                out.append(Problem("L7", where, f"mobility note {g.phone_lines(body)} phone lines > {g.MOBILITY_MAX_LINES}"))
        else:
            _lint_lift(ex, body, where, out)
        mw = g.W_TEXT_RE.search(body)
        if mw:
            wreps = {r[2] for r in ex.rows if r[0] == "W"}
            said = mw.group(2) or mw.group(1)
            if wreps != {said}:
                out.append(Problem("L4", where, f"the W text says {said} reps, the W rows hold {sorted(str(w) for w in wreps)}"))
        w = [r[1] for r in ex.rows if r[0] == "W" and r[1] is not None]
        work = [r[1] for r in _working(ex.rows) if r[1] is not None]
        if w and (w != sorted(w) or (work and w[-1] >= work[0])):
            out.append(Problem("L5", where, "warm-up rows do not ascend below the work"))
    for i, ex in enumerate(exs):
        if ex.kind == "dumbbell" and ex.compound:
            work = [r[1] for r in _working(ex.rows) if r[1]]
            if work and max(work) >= g.DB_BIG_STEP_FROM_LB:
                if not any(r[0] == "W" for r in ex.rows):
                    out.append(Problem("L13", f"[{i + 1}] {ex.name}", "the first dumbbell compound at 50 lb per hand or more has no W row"))
                break
    _lint_cues(rt, bodies, out, not_checked)
    if not rt.previous_supplied:
        not_checked.append(f"L4 PREVIOUS: inputs_snapshot[{PREVIOUS_LOADS_KEY!r}] absent")
    if total > g.ROUTINE_TOTAL_MAX_CHARS:
        out.append(Problem("L7", "routine", f"total {total} chars > {g.ROUTINE_TOTAL_MAX_CHARS}"))
    return LintResult(problems=out, not_checked=not_checked, total_chars=total)


# ── fixtures and the wire ──────────────────────────────────────────────────────────────────────────────────────────


def routine_from_dict(d: dict[str, Any]) -> LintRoutine:
    """The fixture shape (tests/fixtures/hevy_notes_2026_10/*.json): {"exercises": [{"name", "kind", "rows":
    [[type, lb, reps]], "note", "compound", "family", "anchor_family", "previous_lb"}], "previous_supplied"}."""
    exs = [
        LintExercise(
            name=str(e["name"]),
            kind=str(e["kind"]),
            rows=[(str(r[0]), None if r[1] is None else float(r[1]), None if r[2] is None else str(r[2])) for r in e.get("rows") or []],
            note=str(e.get("note") or ""),
            compound=bool(e.get("compound")),
            family=e.get("family"),
            anchor_family=e.get("anchor_family"),
            previous_lb=e.get("previous_lb"),
        )
        for e in d.get("exercises") or []
    ]
    return LintRoutine(exercises=exs, previous_supplied=bool(d.get("previous_supplied")), title=str(d.get("title") or ""))


_CARRY_RE = re.compile(r"carry|carries|farmer|suitcase", re.I)
_MOBILITY_RE = re.compile(r"stretch|mobility|yoga|foam roll", re.I)


def kind_of(movement_key: str, entry: Optional[dict[str, Any]]) -> str:
    """The implement kind of one movement, from its catalog entry (`equipment`, Hevy type, primary muscle)."""
    from training.cardio_note import MACHINES  # the cardio machines the composer knows

    e = entry or {}
    key = str(movement_key or "").lower()
    title = str(e.get("title") or key)
    if key in MACHINES or e.get("primary_muscle") == "cardio":
        return "cardio"
    if e.get("hevy_type") == "short_distance_weight" or _CARRY_RE.search(title) or _CARRY_RE.search(key):
        return "carry"
    if _MOBILITY_RE.search(title) or _MOBILITY_RE.search(key):
        return "mobility"
    eq = e.get("equipment")
    if eq is None:
        for word, kind in (
            ("dumbbell", "dumbbell"),
            ("db_", "dumbbell"),
            ("barbell", "barbell"),
            ("cable", "cable"),
            ("machine", "machine"),
        ):
            if word in key:
                return kind
        return "other"
    return {"dumbbell": "dumbbell", "barbell": "barbell", "machine": "machine", "plate": "machine", "cable": "cable"}.get(
        str(eq), "bodyweight" if eq in ("none", "resistance_band") else "other"
    )


def family_of(movement_key: str, entry: Optional[dict[str, Any]]) -> Optional[str]:
    """The cue family (standard §4) the linter can derive on its own: the catalog anchor family, with the leg press
    told apart from the squat. Lane B's movement_cues may supply a fuller classifier (`lint_wire(family_of=...)`)."""
    e = entry or {}
    title = str(e.get("title") or movement_key or "").lower()
    if "leg press" in title:
        return "leg_press"
    if "calf" in title and "press" in title:
        return "calf_press"
    return g.ANCHOR_TO_CUE_FAMILY.get(str(e.get("anchor_family") or ""))


def entry_for(movement_key: str, catalog: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The catalog entry for a movement key; a `tmpl:<id>` key (a block the chat named by Hevy template) resolves
    through the entries' `hevy_template_id_hint`."""
    cat = catalog or {}
    key = str(movement_key or "")
    if key in cat:
        return cat[key]
    if key.lower().startswith("tmpl:"):
        tid = key[5:].strip().upper()
        for entry in cat.values():
            if isinstance(entry, dict) and str(entry.get("hevy_template_id_hint") or "").strip().upper() == tid:
                return entry
    return None


def _reps_of(s: dict[str, Any]) -> Optional[str]:
    rr = s.get("rep_range") or {}
    lo, hi = rr.get("start"), rr.get("end")
    if lo is not None and hi is not None:
        return f"{lo}" if lo == hi else f"{lo}–{hi}"
    if s.get("reps") is not None:
        return str(s["reps"])
    if s.get("duration_seconds"):
        return f"{int(round(float(s['duration_seconds']) / 60))} min"
    if s.get("distance_meters"):
        return f"{g.fmt_num(float(s['distance_meters']))} m"
    return None


def _rows_of(sets: list[dict[str, Any]]) -> list[Row]:
    rows: list[Row] = []
    for s in sets or []:
        kind = "W" if str(s.get("type") or "") == "warmup" else "N"
        kg = s.get("weight_kg")
        lb = None if kg is None else round(float(kg) / KG_PER_LB, 1)
        rows.append((kind, lb, _reps_of(s)))
    return rows


def _previous_value(v: Any) -> Previous:
    if isinstance(v, dict):
        v = v.get("loads_lb", v.get("lb"))
    if isinstance(v, (list, tuple)):
        return [None if x is None else float(x) for x in v]
    return None if v is None else float(v)


def from_wire(
    body: dict[str, Any],
    ir: Any = None,
    *,
    catalog: Optional[dict[str, Any]] = None,
    family_fn: Optional[Callable[[str, Optional[dict[str, Any]]], Optional[str]]] = None,
) -> LintRoutine:
    """A compiled wire body (+ the IR it came from) as a LintRoutine. The IR's primary exercises pair with the wire's
    exercises by position (the compiler emits them in order); without an IR every kind is 'other'."""
    routine = (body or {}).get("routine") or body or {}
    wire = routine.get("exercises") or []
    keys: list[str] = []
    snap: dict[str, Any] = {}
    if ir is not None:
        from training.hevy_compiler import _primary_exercises

        keys = [str(b.movement_key) for b in _primary_exercises(ir)]
        snap = getattr(ir, "inputs_snapshot", None) or {}
    not_checked: list[str] = []
    if catalog is None:
        from training.logging_conventions import catalog_movements

        catalog = catalog_movements()
    if not catalog:
        not_checked.append("kinds: the movement catalog was not read; kinds come from the movement keys")
    if ir is None:
        not_checked.append("kinds: no IR; every exercise is linted as 'other'")
    prev_map = snap.get(PREVIOUS_LOADS_KEY)
    fam = family_fn or family_of
    exs: list[LintExercise] = []
    for i, w in enumerate(wire):
        key = keys[i] if i < len(keys) else ""
        entry = entry_for(key, catalog) if key else None
        exs.append(
            LintExercise(
                name=str((entry or {}).get("title") or key or f"exercise {i + 1}"),
                kind=kind_of(key, entry) if key else "other",
                rows=_rows_of(w.get("sets") or []),
                note=str(w.get("notes") or ""),
                compound=bool((entry or {}).get("anchor_family")),
                family=fam(key, entry) if key else None,
                anchor_family=(entry or {}).get("anchor_family"),
                previous_lb=_previous_value(prev_map.get(key)) if isinstance(prev_map, dict) else None,
            )
        )
    return LintRoutine(
        exercises=exs, previous_supplied=isinstance(prev_map, dict), title=str(routine.get("title") or ""), not_checked=not_checked
    )


def lint_wire(body: dict[str, Any], ir: Any = None, *, catalog: Optional[dict[str, Any]] = None, family_fn: Any = None) -> LintResult:
    """Lint a compiled routine body (hevy_compiler output) against the standard."""
    return lint_routine(from_wire(body, ir, catalog=catalog, family_fn=family_fn))


def lint_mode() -> str:
    """HEVY_NOTE_LINT_MODE: off | warn (default) | enforce. An unknown value reads as warn."""
    v = (os.environ.get(MODE_ENV) or DEFAULT_MODE).strip().lower()
    return v if v in MODES else DEFAULT_MODE


def refusing(result: LintResult) -> list[Problem]:
    """The problems the commit gate refuses on in enforce mode."""
    return [p for p in result.problems if p.rule in ENFORCE_RULES]


def check_compiled(body: dict[str, Any], ir: Any = None) -> Optional[LintResult]:
    """The compiler's hook: lint, LOG, return. It never raises and never changes the body, in any mode — a lint
    defect cannot block a write (the commit gate is where enforce refuses)."""
    mode = lint_mode()
    if mode == "off":
        return None
    try:
        res = lint_wire(body, ir)
    except Exception as e:  # noqa: BLE001 — a linter bug must never block a routine write
        logger.warning(f"hevy note lint: not run ({type(e).__name__}: {e})")
        return None
    if res.problems:
        title = str(((body or {}).get("routine") or {}).get("title") or "")
        shown = "; ".join(res.lines()[:12])
        more = f" (+{len(res.problems) - 12} more)" if len(res.problems) > 12 else ""
        logger.warning(f"hevy note lint ({mode}): {len(res.problems)} problem(s) on {title!r}: {shown}{more}")
    return res
