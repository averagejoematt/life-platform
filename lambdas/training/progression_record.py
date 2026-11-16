"""progression_record.py — the engine's own record of the load steps it prescribed (#5762, epic #5051).

WHY THIS EXISTS

The block-1 retro (#5496) could not grade the scorecard's "Engine progression logic" row from a stored record:
its code rule is `progression.steps_taken / progression.step_opportunities`, and nothing counted the double-
progression steps the ENGINE prescribed (#5052) or the `step_due` verdicts it raised (#5057) across a block. The
retro supplied a session proxy (every new top-set high), which cannot tell an engine step from a load he raised
himself (`progression.self_raised_load`).

TWO HALVES, ONE RECORD

  * `movement_record(ir)` — per movement, the progression basis the draft applied: one of the charter's
    `progression.bases` (`floor_raise`, `hold`, `step`, `re_entry`, `load_progression.BASES`) or None when the
    engine applied none, and whether it was a `step_due` step (the stall rule's trigger). Built from what the
    draft already stores — the generator's `inputs_snapshot.load_floors.movements[*].progression`
    (`routine_generator._progress_block`) and the chat draft's `inputs_snapshot.step_due` rows
    (`draft_custom_session.attach_step_due`). `stamp(ir)` writes it onto `inputs_snapshot.progression_basis`
    at the one persist step every drafting path takes (`routine_repo.draft_versioned`), so the committed
    version carries it. RECORDING ONLY: no prescription is read differently or changed here.
  * `block_progression(routines, history_index, start=, end=)` — the block-level reader: over the routines
    committed in a date window, `steps_taken` (an engine-prescribed step he then performed at or above its
    load — and reps, for a rep step), `step_due`, `stalls` (`stall_detector.assess_stall` over the block's
    prescribed-vs-performed points, the `stall_check` pairing) and, SEPARATELY, `progressed` (a load he raised
    above the prescription himself, at or under the effort limit — never an engine step). The block retro
    (`block_retro.assemble_evidence(progression=...)`) and the weekly panel's double-progression criterion
    (`panel_rubric.plan_features`) read this record.

A routine stored before the stamp landed is DERIVED from the same snapshot fields by the same function
(`record_of`), and says so (`recorded: false`) — the reader never guesses a basis the draft did not store.

Chat drafts (`draft_custom`) carry the caller's loads verbatim (ADR-069): the engine applied no basis to them,
so a chat movement records `basis: None` (`source: chat_authored`) unless the stall rule named a step on it.

Pure: inputs are values the caller already loaded. No boto3, no clock.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Optional

RECORD_KEY = "progression_basis"
RECORDED_BY = "progression_record@1"
COMMITTED_STATUSES = ("active", "unverified")
SRC_GENERATOR = "routine_generator"
SRC_CHAT_STEP = "chat_step_due"
SRC_CHAT = "chat_authored"
SRC_RE_ENTRY = "re_entry_variant"
SRC_NONE = "no_progression_pass"
_KEEP = ("trigger", "step_kind", "next_load_kg", "next_reps", "reason", "load_convention")


def _snapshot(ir: Any) -> dict[str, Any]:
    return dict(getattr(ir, "inputs_snapshot", None) or {})


def _entry(basis: Optional[str], step_due: bool, applied: bool, source: str, template_id: Any, prog: Mapping[str, Any]) -> dict:
    out = {"basis": basis, "step_due": bool(step_due), "applied": bool(applied), "source": source, "template_id": template_id or None}
    out.update({k: prog.get(k) for k in _KEEP if prog.get(k) is not None})
    return out


def _generator_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    from training import load_progression as lp

    prog = row.get("progression") or {}
    basis = prog.get("basis") if prog.get("basis") in lp.BASES else None
    applied = basis in (lp.BASIS_STEP, lp.BASIS_FLOOR_RAISE)  # `apply_to_sets` writes these (raise only); hold/re_entry write nothing
    step_due = basis == lp.BASIS_STEP and prog.get("trigger") == lp.TRIGGER_STALL_RULE
    return _entry(basis, step_due, applied, SRC_GENERATOR if basis else SRC_NONE, row.get("template_id"), prog)


def movement_record(ir: Any) -> dict[str, dict[str, Any]]:
    """{movement_key: {basis, step_due, applied, source, template_id, trigger?, step_kind?, next_load_kg?, next_reps?,
    reason?}} for every exercise of `ir`. `applied` is True when the draft's working sets carry the engine's load."""
    from training import load_progression as lp

    snap = _snapshot(ir)
    floors = ((snap.get("load_floors") or {}).get("movements")) or {}
    raw_steps = snap.get("step_due")
    steps = {str(r.get("movement_key")): r for r in raw_steps if isinstance(r, dict)} if isinstance(raw_steps, list) else {}
    chat = str(getattr(ir, "source_action", "") or "") == "draft_custom" or raw_steps is not None
    variant = str(getattr(ir, "variant", "") or "")
    out: dict[str, dict[str, Any]] = {}
    for b in getattr(ir, "exercises", None) or []:
        key = str(getattr(b, "movement_key", "") or "")
        row = floors.get(key) or {}
        if (row.get("progression") or {}).get("basis"):
            out[key] = _generator_entry(row)
        elif key in steps:
            r = steps[key]
            out[key] = _entry(lp.BASIS_STEP, True, bool(r.get("carried")), SRC_CHAT_STEP, row.get("template_id"), r)
        elif variant == lp.BASIS_RE_ENTRY:
            out[key] = _entry(lp.BASIS_RE_ENTRY, False, False, SRC_RE_ENTRY, row.get("template_id"), {})
        else:
            out[key] = _entry(None, False, False, SRC_CHAT if chat else SRC_NONE, row.get("template_id"), {})
    return out


def stamp(ir: Any) -> Any:
    """Write `inputs_snapshot.progression_basis` onto `ir` (in place; returns it). Fail-soft by the caller's contract:
    `routine_repo.draft_versioned` wraps it, so a record that cannot be built never blocks a draft."""
    ir.inputs_snapshot = {**_snapshot(ir), RECORD_KEY: {"recorded_by": RECORDED_BY, "movements": movement_record(ir)}}
    return ir


def record_of(ir: Any) -> dict[str, Any]:
    """The stored record, or — for a routine drafted before #5762 — the same record derived from its snapshot."""
    stored = _snapshot(ir).get(RECORD_KEY)
    if isinstance(stored, dict) and isinstance(stored.get("movements"), dict):
        return {**stored, "recorded": True}
    return {"recorded_by": RECORDED_BY, "movements": movement_record(ir), "recorded": False}


def is_committed(ir: Any) -> bool:
    """Pushed to Hevy: active / unverified, or archived after it was pushed (a committed routine archived later)."""
    status = str(getattr(ir, "status", "") or "")
    return status in COMMITTED_STATUSES or (status == "archived" and bool(getattr(ir, "hevy_pushed_at", None)))


# ── the block reader ──────────────────────────────────────────────────────────────


def _template_for(ir: Any, movements: Mapping[str, Any], catalog: Mapping[str, Any] | None) -> dict[str, str]:
    from health.adherence_calc import _catalog_entry_for

    out: dict[str, str] = {}
    for b in getattr(ir, "exercises", None) or []:
        key = str(getattr(b, "movement_key", "") or "")
        tid = (movements.get(key) or {}).get("template_id") or (
            _catalog_entry_for(key, dict(catalog)).get("hevy_template_id_hint") if catalog else None
        )
        if tid:
            out[key] = str(tid)
    return out


def _limit_for(ir: Any, catalog: Mapping[str, Any] | None, limits: Mapping[str, Any] | None) -> dict[str, Any]:
    """movement_key -> the charter effort limit (the `self_raised_load` line); empty without a catalog."""
    if not catalog:
        return {}
    from health.adherence_calc import _catalog_entry_for

    from training import load_progression as lp

    lim = dict(limits) if limits is not None else lp.effort_limits()
    keys = [str(getattr(b, "movement_key", "") or "") for b in getattr(ir, "exercises", None) or []]
    return {k: lp.grading_limits(lp.movement_class(_catalog_entry_for(k, dict(catalog))), lim)["limit_rpe"] for k in keys if k}


def _performed_on(history_index: Mapping[str, list], day: str) -> dict[str, list[dict[str, Any]]]:
    """{template_id: every set he logged for it on `day`} from the `exercise_history` index (Pacific day keys)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for tid, sessions in (history_index or {}).items():
        for s in sessions or []:
            if str(s.get("date") or "")[:10] == day:
                out.setdefault(str(tid), []).extend(s.get("sets") or [])
    return out


def _took(m: Mapping[str, Any], d: Mapping[str, Any]) -> bool:
    from training import load_progression as lp

    load, target = d.get("performed_load_kg"), m.get("next_load_kg")
    if load is None or target is None or float(load) < float(target) - lp.LOAD_TOLERANCE_KG:
        return False
    return m.get("step_kind") != lp.STEP_KIND_REPS or int(d.get("performed_reps") or 0) >= int(m.get("next_reps") or 0)


def _step_row(ir: Any, key: str, m: Mapping[str, Any], d: Mapping[str, Any], taken: bool) -> dict[str, Any]:
    return {
        "date": str(ir.target_date),
        "movement_key": key,
        "trigger": m.get("trigger"),
        "step_kind": m.get("step_kind"),
        "step_due": bool(m.get("step_due")),
        "applied": bool(m.get("applied")),
        "next_load_kg": m.get("next_load_kg"),
        "next_reps": m.get("next_reps"),
        "performed_load_kg": d.get("performed_load_kg"),
        "performed_reps": d.get("performed_reps"),
        "taken": taken,
    }


def _tally(c: Counter, rows: list, points: dict, ir: Any, key: str, m: Mapping[str, Any], d: Mapping[str, Any]) -> None:
    """One committed movement into the block's counts (see `block_progression`)."""
    from training import load_progression as lp, stall_detector as sd

    performed = d.get("performed_load_kg") is not None
    c["movements"] += 1
    c["performed"] += int(performed)
    c[f"basis:{m.get('basis') or 'none'}"] += 1
    engine_step = m.get("basis") == lp.BASIS_STEP and bool(m.get("applied"))
    c["step_due"] += int(bool(m.get("step_due")))
    if engine_step:
        taken = performed and _took(m, d)
        c["steps_prescribed"] += 1
        c["steps_taken"] += int(taken)
        c["steps_not_performed"] += int(not performed)
        c["steps_short"] += int(performed and not taken)
    if m.get("basis") == lp.BASIS_STEP or m.get("step_due"):
        rows.append(_step_row(ir, key, m, d, bool(engine_step and performed and _took(m, d))))
    elif d.get("match") == sd.MATCH_PROGRESSED:
        c["progressed"] += 1  # he raised it himself at or under the limit — never an engine step (`self_raised_load`)
    if d.get("template_id"):
        points.setdefault(str(d["template_id"]), {"key": key, "points": []})["points"].append(
            sd.session_point_from_diff(str(ir.target_date), d)
        )


def block_progression(
    routines: Iterable[Any],
    history_index: Mapping[str, list],
    *,
    start: str,
    end: str,
    catalog: Mapping[str, Any] | None = None,
    limits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The engine's progression record over `[start, end]` (Pacific day keys), from the routines committed there.

    Each committed routine is paired with the sets he logged for its movements ON ITS TARGET DAY (the history
    index, `exercise_history.load_history_indexes`), through `stall_detector.diff_prescribed_vs_performed`:

      steps_prescribed  movements whose draft carried an engine step (basis `step`, applied)
      steps_taken       those he performed at or above the step's load (and its reps, for a rep step)
      step_due          the stall rule's steps the engine raised (`step_due: true`), carried or not
      stalls            movements `assess_stall` calls `stall` over the block's prescribed-vs-performed points
      progressed        movements he carried ABOVE the prescription at or under the effort limit, where the engine
                        prescribed no step — `progression.self_raised_load`, counted apart, never as a step

    `catalog` (the movement catalog) resolves a template id the record lacks and sizes the effort limit; without
    it `progressed` is not computable and reads None. Absent is never zero (ADR-104)."""
    from training import stall_detector as sd
    from training.load_ramp import _rep_range_of

    chosen = sorted((r for r in routines if start <= str(getattr(r, "target_date", "") or "") <= end), key=lambda r: str(r.target_date))
    committed = [r for r in chosen if is_committed(r)]
    c: Counter = Counter()
    rows: list[dict[str, Any]] = []
    points: dict[str, dict[str, Any]] = {}
    ranges: dict[str, Any] = {}
    for ir in committed:
        rec = record_of(ir)
        c["recorded" if rec["recorded"] else "derived"] += 1
        movements = rec["movements"]
        diff = sd.diff_prescribed_vs_performed(
            ir, _performed_on(history_index, str(ir.target_date)), _template_for(ir, movements, catalog), _limit_for(ir, catalog, limits)
        )
        for b in ir.exercises or []:
            key = str(b.movement_key or "")
            ranges[key] = _rep_range_of(b.sets) or ranges.get(key)
            _tally(c, rows, points, ir, key, movements.get(key) or {}, diff.get(key) or {})
    stalled = sorted(
        p["key"]
        for p in points.values()
        if sd.assess_stall(p["points"], movement_key=p["key"], rep_range=ranges.get(p["key"])).get("verdict") == sd.VERDICT_STALL
    )
    return {
        "window": {"start": start, "end": end},
        "source": "progression_record.block_progression — the engine's own record (inputs_snapshot.progression_basis) "
        "paired with the sets logged on each committed routine's day",
        "routines_in_window": len(chosen),
        "committed_routines": len(committed),
        "recorded_routines": c["recorded"],
        "derived_routines": c["derived"],
        "movements": c["movements"],
        "movements_performed": c["performed"],
        "bases": {k.split(":", 1)[1]: v for k, v in sorted(c.items()) if k.startswith("basis:")},
        "steps_prescribed": c["steps_prescribed"],
        "steps_taken": c["steps_taken"],
        "steps_not_performed": c["steps_not_performed"],
        "steps_short": c["steps_short"],
        "step_due": c["step_due"],
        "stalls": len(stalled),
        "stalled_movements": stalled,
        "progressed": c["progressed"] if catalog else None,
        "steps": rows,
    }
