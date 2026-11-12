"""rpe_calibration.py — the RPE calibration set: predicted vs actual reps in reserve (#5797, epic #5051).

THE GAP. The RPE-adjusted e1RM (`load_ramp.rpe_adjusted_e1rm_kg`: RIR = 10 - logged RPE, Epley on reps + RIR) and every
hold built on it assume his logged RPE is accurate. Nothing measured it: no set was ever compared with what he predicted.

THE RULING (owner, 2026-11-11, #5797, gate:owner). Calibration sets go ONLY on non-barbell anchors (lat pulldown,
one-arm DB row, machine press) and the set STOPS AT THE FIRST SLOW REP, NOT FAILURE. His standing no-grinding rule
(2026-10-10) excludes every barbell rep-out. Every rule is charter data, `calibration.rpe` (`params`); the standing rule's
text is `calibration.rpe.standing_rule`, and `eligible` refuses `never_equipment` (barbell) even when the charter lists
the movement, so a barbell can never be calibrated by a config edit alone.

THE SET. On every `every_nth_exposure`-th exposure of an eligible movement (counted from `exposures_counted_from`), the
LAST back-off set (the last working set when the exposure has no back-offs) carries ONE note line, `NOTE_LINE`. Before
the set he logs, in the Hevy set's RPE field, the RPE he predicts for the row's top rep; then he does reps until the
first slow rep and logs the reps done. That is the least-friction capture: no new field, no new app — the RPE field he
already fills, read as a prediction on this one set. The rows are not changed and the set stays a normal set (never
Hevy's `failure` type).

THE PAIR (`pair`). predicted RIR = 10 - logged RPE; actual RIR = reps done + `rir_at_first_slow_rep` - the row's top rep
(a slow rep is not failure, so the reps he had left after it are the charter's value, owner-confirmed 2026-11-11 —
an assumption, not measured); error = actual - predicted. Positive: he had more in reserve than he predicted.

WHERE A PAIR LIVES. The mark (which set, which top rep) is on the draft (`inputs_snapshot.rpe_calibration.marks`) and on
its owner-only `routine_index` row (`routine_repo.versioned_items`); the performed set is his Hevy workout. The one history
loader (`exercise_history.load_history_indexes`) joins them by the Hevy routine id (`annotate`), so every load path — the
generator, the planner, the chat gate — reads the same pairs, and each draft records the per-movement report it used
(`report`). No new partition.

THE ADJUSTMENT (`hold_basis`). Descriptive until n >= `min_n`; then the mean with a Student's-t interval at
`interval_pct`. The hold's RIR moves by the mean error only when the interval excludes zero (ADR-104: a number the data
cannot separate from zero changes nothing), and the hold records it (`hold.rpe_basis: rpe_adjusted_calibrated`).

Pure apart from `load_marks_failsoft` (one Query of the routine index, fail-soft: a failed read is no pairs, never a
blocked draft).
"""

from __future__ import annotations

import logging
import math
from statistics import NormalDist, mean, stdev
from typing import Any

from training.training_charter import charter_value

logger = logging.getLogger(__name__)

CHARTER_PATH = "calibration.rpe"
NOTE_LINE = "Last set to first slow rep; RPE = guess."
"""The ONE instruction line (Hevy note standard: one short line, no 'failure', no RIR): 40 characters, ONE phone line, so
it fits beside a reason and a family cue. "RPE = guess": the set's RPE field holds his prediction, made before the set."""

ALWAYS_REFUSED = frozenset({"barbell"})
"""The standing no-grinding rule (owner, 2026-10-10; restated 2026-11-11, `calibration.rpe.standing_rule`): no barbell
rep-out, ever. Held here as well as in the charter so a charter edit alone can never calibrate a barbell lift."""

SNAPSHOT_KEY = "rpe_calibration"
PAIRED = "paired"
NO_PREDICTION = "no_prediction"
DESCRIPTIVE = "descriptive"
ESTIMATED = "estimated"
ABSENT = "absent"


def params() -> dict[str, Any]:
    """The charter's `calibration.rpe` block ({} when the charter cannot be read: then nothing is eligible)."""
    return dict(charter_value(CHARTER_PATH, {}) or {})


# ── eligibility and the schedule ─────────────────────────────────────────────────────────────────────────────────


def eligible(movement_key: str, entry: dict[str, Any] | None, p: dict[str, Any] | None = None) -> tuple[bool, str]:
    """(eligible, why) for one movement. A barbell is refused FIRST, before the list is read (the standing no-grinding
    rule, `calibration.rpe.standing_rule`): listing a barbell lift in `eligible` cannot calibrate it."""
    p = params() if p is None else p
    equipment = str((entry or {}).get("equipment") or "").lower()
    # the barbell is refused even when the charter's own `never_equipment` is missing or edited: the standing rule is not config
    if not equipment or equipment in ALWAYS_REFUSED | {str(e).lower() for e in p.get("never_equipment") or []}:
        return False, f"never on a {equipment or 'movement with no equipment on file'} (standing no-grinding rule)"
    if movement_key not in (p.get("eligible") or []):
        return False, "not an eligible movement"
    return True, "eligible"


def exposure_number(sessions: list[dict[str, Any]] | None, target_date: str, since: str | None) -> int:
    """This session's exposure number for one movement: 1 + the distinct days he performed it on or after `since`
    and before `target_date`."""
    days = {str(s.get("date") or "") for s in sessions or []}
    return 1 + len({d for d in days if d and d < target_date and (not since or d >= since)})


def _working(sets: list[Any]) -> list[Any]:
    return [s for s in sets or [] if str(getattr(s, "type", "") or "").lower() not in ("warmup", "warm_up", "warm-up")]


def _top_rep(s: Any) -> int | None:
    v = getattr(s, "rep_range_end", None) or getattr(s, "reps", None)
    return int(v) if v else None


def _skip_reason(key: str, block: Any, entry: dict[str, Any], ctx: dict[str, Any], p: dict[str, Any]) -> str | None:
    """Why this exposure carries no calibration set, or None when it is due."""
    ok, why = eligible(key, entry, p)
    if not ok:
        return why
    for flag, reason in (("deload", "a deload week"), ("red_day", "a red day")):
        if ctx.get(flag):
            return reason
    row = (ctx.get("movements") or {}).get(key) or {}
    note = (ctx.get("lift_notes") or {}).get(key) or {}
    if (row.get("ramp") or {}).get("exposure_caps"):
        return "an OD1-capped exposure after a layoff"
    if note.get("layoff_return"):
        return "a first session back after a long layoff"
    if key not in (ctx.get("previous_loads") or {}):
        return "a lift with no PREVIOUS"
    work = _working(block.sets)
    # never the only working set, whatever the charter says: the top set the gain and stall rules read stays a real rating
    if len(work) < max(2, int(p.get("min_working_sets") or 0)) or _top_rep(work[-1]) is None:
        return "fewer working sets than the calibration set needs"
    nth = int(p.get("every_nth_exposure") or 0)
    n = exposure_number(ctx["history"].get(ctx["tid"]) or [], ctx["target_date"], p.get("exposures_counted_from"))
    ctx["exposure"] = n
    return None if nth and n % nth == 0 else f"exposure {n}, not a multiple of {nth}"


def _note_room(index: int) -> int:
    from training import hevy_note_grammar, lift_note

    return lift_note._ex1_room() if index == 0 else hevy_note_grammar.LIFT_MAX_LINES


def mark_session(blocks: list[Any], catalog_movements: dict[str, Any], *, note_record: dict[str, Any], context: dict[str, Any]) -> dict:
    """IN PLACE: give each due exposure its calibration line and return the snapshot record {marks, skipped}.

    `context`: deload, red_day, load_floors, history_index, target_date. Runs after `lift_note.compose_blocks`, whose
    record (`note_record`) says which lifts are layoff returns and which have a PREVIOUS. A note with no room for the
    line under the Hevy note budget defers the set (recorded) rather than overrun the budget."""
    from training import hevy_note_grammar

    p = params()
    marks: list[dict[str, Any]] = []
    skipped: dict[str, str] = {}
    for index, block in enumerate(blocks or []):
        key = str(block.movement_key)
        entry = (catalog_movements or {}).get(key) or {}
        ctx = {
            **context,
            "movements": (context.get("load_floors") or {}).get("movements"),
            "lift_notes": note_record.get("lift_notes"),
            "previous_loads": note_record.get("previous_loads"),
            "history": context.get("history_index") or {},
            "tid": entry.get("hevy_template_id_hint"),
        }
        why = _skip_reason(key, block, entry, ctx, p)
        if why is None and hevy_note_grammar.phone_lines(f"{block.notes}\n{NOTE_LINE}") > _note_room(index):
            why = "no room for the line under the note budget (deferred)"
        if why is not None:
            if key in (p.get("eligible") or []):
                skipped[key] = why
            continue
        block.notes = f"{block.notes}\n{NOTE_LINE}" if block.notes else NOTE_LINE
        work = _working(block.sets)
        marks.append(
            {
                "movement_key": key,
                "template_id": ctx["tid"],
                "exposure": ctx["exposure"],
                "target_reps": _top_rep(work[-1]),
                "set": len(work),
            }
        )
        if key in (note_record.get("lift_notes") or {}):
            note_record["lift_notes"][key]["note"] = block.notes
    return {"marks": marks, "skipped": skipped, "line": NOTE_LINE}


# ── the pair, the history join and the report ────────────────────────────────────────────────────────────────────


def pair(mark: dict[str, Any], sets: list[dict[str, Any]], p: dict[str, Any] | None = None) -> dict[str, Any]:
    """One exposure's predicted vs actual reps in reserve, read off its LAST performed set (the calibration set is the
    last working set, and the index lists warm-ups first). A set with no RPE logged has no prediction: not paired."""
    p = params() if p is None else p
    last = (sets or [])[-1] if sets else {}
    target, reps, rpe = int(mark.get("target_reps") or 0), int(last.get("reps") or 0), last.get("rpe")
    base = {"target_reps": target, "reps_done": reps, "set_index": len(sets or []) - 1, "exposure": mark.get("exposure")}
    if rpe is None or not target or reps <= 0:
        return {**base, "status": NO_PREDICTION}
    predicted = 10.0 - float(rpe)
    actual = float(reps + int(p.get("rir_at_first_slow_rep") or 0) - target)
    return {
        **base,
        "status": PAIRED,
        "predicted_rpe": float(rpe),
        "predicted_rir": predicted,
        "actual_rir": actual,
        "error": actual - predicted,
    }


def annotate(index: dict[str, list], marks_by_routine: dict[str, list[dict[str, Any]]], p: dict[str, Any] | None = None) -> int:
    """IN PLACE: stamp `calibration` (the pair) on every history session that performed a marked set — the same Hevy
    routine, the same template. Returns the number stamped."""
    p = params() if p is None else p
    stamped = 0
    for tid, sessions in (index or {}).items():
        for s in sessions or []:
            marks = marks_by_routine.get(str(s.get("hevy_routine_id") or "")) or []
            mark = next((m for m in marks if m.get("template_id") == tid), None)
            if mark is not None and s.get("sets"):
                s["calibration"] = pair(mark, s["sets"], p)
                stamped += 1
    return stamped


def marks_from_index_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """{hevy routine id -> marks} from `routine_index` rows; a row never pushed to Hevy has nothing to join."""
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows or []:
        rid, marks = str(r.get("hevy_routine_id") or ""), r.get(SNAPSHOT_KEY)
        if rid and isinstance(marks, list) and marks:
            out.setdefault(rid, []).extend(dict(m) for m in marks if isinstance(m, dict))
    return out


def load_marks_failsoft(table: Any, start: str) -> dict[str, list[dict[str, Any]]]:
    """One Query of the routine index from `start` (DATE# keys) -> marks by Hevy routine id; {} when the read fails."""
    from boto3.dynamodb.conditions import Key

    from training.routine_repo import INDEX_PK

    rows: list[dict[str, Any]] = []
    try:
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(INDEX_PK) & Key("sk").gte(f"DATE#{start}")}
        while True:
            resp = table.query(**kwargs)
            rows += [r for r in resp.get("Items", []) if r.get("pk") in (None, INDEX_PK)]
            if not resp.get("LastEvaluatedKey"):
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    except Exception as e:  # noqa: BLE001 — no pairs, never a blocked draft
        logger.warning(f"rpe_calibration: the routine-index read failed ({type(e).__name__}) — no calibration pairs")
        return {}
    return marks_from_index_rows(rows)


def pairs_of(sessions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The paired calibration sets in one movement's history, newest first."""
    return [{**s["calibration"], "date": s.get("date")} for s in sessions or [] if (s.get("calibration") or {}).get("status") == PAIRED]


def _t_quantile(q: float, df: int) -> float:
    """Student's t quantile by the Cornish–Fisher expansion about the normal (within ~0.01 of the table from df 4 at
    the 80 % interval; conservative enough for a gate that only opens on an interval excluding zero)."""
    z = NormalDist().inv_cdf(q)
    v = float(df)
    return (
        z + (z**3 + z) / (4 * v) + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * v**2) + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / (384 * v**3)
    )


def summarize(errors: list[float], p: dict[str, Any] | None = None) -> dict[str, Any]:
    """n, mean, SD and — from `min_n` — the `interval_pct` interval; `adjusts` only when that interval excludes zero."""
    p = params() if p is None else p
    n, min_n, pct = len(errors), int(p.get("min_n") or 0), float(p.get("interval_pct") or 0)
    out: dict[str, Any] = {"n": n, "min_n": min_n, "mean_error_rir": None, "sd_rir": None, "interval": None, "adjusts": False}
    if not n:
        return {**out, "state": ABSENT, "reading": "no calibration set paired yet"}
    m = mean(errors)
    out.update(mean_error_rir=round(m, 2), sd_rir=round(stdev(errors), 2) if n > 1 else None)
    if not min_n or n < min_n or n < 2 or not pct:
        return {**out, "state": DESCRIPTIVE, "reading": f"descriptive: n {n} is under the {min_n} an estimate needs"}
    half = _t_quantile(0.5 + pct / 200.0, n - 1) * stdev(errors) / math.sqrt(n)
    lo, hi = round(m - half, 2), round(m + half, 2)
    adjusts = lo > 0 or hi < 0
    side = "more" if m > 0 else "less"
    reading = f"he had {abs(m):.1f} {side} reps in reserve than he predicted, n {n}" if adjusts else f"no bias separable from zero, n {n}"
    return {**out, "state": ESTIMATED, "interval": [lo, hi], "interval_pct": pct, "adjusts": adjusts, "reading": reading}


def hold_basis(sessions: list[dict[str, Any]] | None, p: dict[str, Any] | None = None) -> dict[str, Any]:
    """The hold's calibration for one movement: its summary plus `rir_offset` (the mean error when it adjusts, else 0)."""
    errors = [float(x["error"]) for x in pairs_of(sessions)]
    s = summarize(errors, p)
    return {**s, "rir_offset": float(s["mean_error_rir"]) if s["adjusts"] else 0.0}


def report(history_index: dict[str, list] | None, catalog_movements: dict[str, Any] | None, p: dict[str, Any] | None = None) -> dict:
    """Per eligible movement and pooled: the pairs and their summary (the draft's `inputs_snapshot` record)."""
    p = params() if p is None else p
    by_movement: dict[str, Any] = {}
    pooled: list[float] = []
    for key in p.get("eligible") or []:
        tid = ((catalog_movements or {}).get(key) or {}).get("hevy_template_id_hint")
        pairs = pairs_of((history_index or {}).get(tid)) if tid else []
        pooled += [float(x["error"]) for x in pairs]
        by_movement[key] = {"pairs": pairs, **summarize([float(x["error"]) for x in pairs], p)}
    return {"by_movement": by_movement, "pooled": summarize(pooled, p), "rir_at_first_slow_rep": p.get("rir_at_first_slow_rep")}
