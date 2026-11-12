"""fatigue_model.py — fatigue and recovery as first-class inputs to the draft (#5861 L3). Pure: no reads, no clock.

WHY THIS EXISTS. The engine audit (2026-11-12, gap 4) found a lot of fatigue SENSING and almost no closed loop: readiness,
ACWR, sleep, joint discomfort, cardio load and the strength trend did not move a single set in the drafted routine, and
`discomfort` (`training_notes_pain.pain_class`, #5800) was acted on nowhere. This module turns those inputs into ONE
recovery state and ONE recommended action, every threshold labelled `heuristic` or `validated` (THRESHOLDS). Nothing here
is validated against an outcome trial; every number is a labelled practitioner heuristic, and says where it came from.

WHAT IT READS (each optional; an unread input is `unknown`, never "fine"):
    workouts       the Hevy record (`session_sequence.load_block_workouts` rows: `date`/`sk`, `exercises[{template_id,
                   title, sets[{type, weight_kg, reps, rpe}], notes}]`, `adherence.session_time`)
    library        the exercise library — each template's primary/secondary muscles, pattern, job, resistance profile
    readiness      the recovery tier the draft already carries (`green | yellow | red | re-baselining`); HR-derived tiers
                   are NOT effort evidence inside an HR regime marker's window (`re-baselining` reads unknown)
    sleep_hours    last night's sleep, when a caller read it
    cardio_load    THE CARDIO SEAM (L4, `cardio_model`): `{"state": "low" | "moderate" | "high", "source": ...}` — the
                   cardio + walking load the cardio model computes; `high` is one systemic strain signal
    landmarks      `config/training_landmarks.json` `muscles` (MRV per muscle — practitioner landmarks, heuristic)

WHAT IT RETURNS (`assess`): `state` (recovered | normal | strained | overreached), `action` (maintain | reduce |
deload_recommended), `reduce_sets` (accessory sets to take off — NEVER a positive number: this model never adds volume
because a slot exists), `swaps` (movements to replace with a lower-fatigue variant, and why), the deload record (deloads
stay owner-confirmed — charter `deload.owner_gated`, owner ruling 2026-10-18 — so a deload is RECOMMENDED and surfaced,
never applied here), and every signal with the threshold it was judged by. "Maintain strength with less fatigue": a
reduction takes accessory sets only; anchors and their top sets are held (`apply_to_session`).

LIVE ONLY. `apply_to_session` changes a draft only when the selection ran LIVE (`selection_engine.mode() == "live"`, the
library `approved`); in shadow it returns the prescription untouched (the same object).
"""

from __future__ import annotations

import copy
import datetime as _dt
from typing import Any

ISSUE = "#5861"
VERSION = "fatigue-model@0.1.0"
HEURISTIC, VALIDATED = "heuristic", "validated"
MODE_LIVE = "live"  # `selection_engine.MODE_LIVE` (not imported: this module stays import-light)

THRESHOLDS: dict[str, dict[str, Any]] = {
    "hard_set_rpe_min": {
        "value": 6.0,
        "label": HEURISTIC,
        "basis": "a working set logged at RPE >= 6 (about 4 reps in reserve or closer) is a hard set; a working set with no "
        "RPE logged counts too (he logs RPE on few sets) — practitioner consensus, not a measured stimulus threshold",
    },
    "secondary_muscle_credit": {
        "value": 0.5,
        "label": HEURISTIC,
        "basis": "fractional-set convention: a hard set credits its primary muscle 1.0 and each secondary muscle 0.5 — a "
        "common counting convention, not a measured stimulus ratio",
    },
    "weekly_sets_over": {
        "value": "MRV",
        "label": HEURISTIC,
        "basis": "weekly hard sets above the muscle's MRV landmark (config/training_landmarks.json — practitioner volume "
        "landmarks, not individual measurements); no landmark = unknown",
    },
    "e1rm_drop_pct": {
        "value": 0.05,
        "label": HEURISTIC,
        "basis": "the latest two exposures of a compound both more than 5% under its best earlier e1RM (Epley) in the window "
        "— the platform's existing practice line (critics_fatigue), not a citation and not his own variance",
    },
    "trend_min_exposures": {"value": 3, "label": HEURISTIC, "basis": "a trend claim needs three exposures (stall_detector.MIN_SESSIONS)"},
    "rpe_drift": {
        "value": 1.0,
        "label": HEURISTIC,
        "basis": "the same load x reps logged at least 1 RPE point harder than its first exposure in the window",
    },
    "discomfort_sessions": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "two sessions with a discomfort-class note (training_notes_pain.pain_class) on one movement inside "
        "discomfort_window_days -> swap it for a lower-fatigue variant; a pain-class note already excludes (#5806)",
    },
    "discomfort_window_days": {"value": 14, "label": HEURISTIC, "basis": "two weeks: about two exposures of a weekly movement"},
    "axial_stack_window_hours": {
        "value": 72,
        "label": HEURISTIC,
        "basis": "three or more free-weight squat/hinge compound exposures inside 72 h (e.g. squat + conventional deadlift + "
        "RDL) is redundant axial fatigue — practitioner consensus",
    },
    "axial_stack_count": {"value": 3, "label": HEURISTIC, "basis": "see axial_stack_window_hours"},
    "hinge_stack_window_hours": {
        "value": 48,
        "label": HEURISTIC,
        "basis": "two heavy free-weight hinge exposures inside 48 h (heavy hinge stacking) — practitioner consensus",
    },
    "readiness_strain": {
        "value": "red",
        "label": HEURISTIC,
        "basis": "the readiness tier the draft carries (green >= 67 / yellow >= 34 / red, the vendor's own bands, "
        "`mcp/tools_plan._recovery_tier`); red is one strain signal. Inside an HR regime marker's window it is unknown",
    },
    "sleep_short_hours": {"value": 6.5, "label": HEURISTIC, "basis": "the charter's progression refusal text (sleep < 6.5 h)"},
    "adherence_low": {
        "value": 0.6,
        "label": HEURISTIC,
        "basis": "fewer than 60% of the planned sessions performed in 14 days: keep the plan short and never add — adherence "
        "comes first for long-term results",
    },
    "reduce_at_strain_signals": {
        "value": 2,
        "label": HEURISTIC,
        "basis": "one strain signal is noise; two independent ones take reduce_sets_per_step accessory sets off",
    },
    "reduce_sets_per_step": {"value": 2, "label": HEURISTIC, "basis": "two accessory sets per strain signal from the second, cap 6"},
    "deload_at_strain_signals": {
        "value": 3,
        "label": HEURISTIC,
        "basis": "three or more strain signals, or a compound regressing on a red-readiness / short-sleep day, RECOMMEND a "
        "deload (owner-confirmed; owner_redlines.deload is the dose)",
    },
}
"""Every threshold the model judges by, with its label and basis. Nothing is `validated` today (no outcome trial behind
any number); a threshold is promoted to `validated` only with a verified citation."""

CARDIO_LOAD_STATES = ("low", "moderate", "high")
AXIAL_PATTERNS = ("squat", "hinge")
SWAP_FATIGUE_ORDER = ("free_weight", "bodyweight", "machine_plate_loaded", "cable", "machine_selectorized")
"""Resistance profiles from most to least systemic/stability cost — the swap direction under fatigue (heuristic)."""


# ── small helpers ─────────────────────────────────────────────────────────────
def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _day(w: dict[str, Any]) -> str:
    return str(w.get("date") or str(w.get("sk") or "")[5:15])[:10]


def _ago(as_of: str, day: str) -> int | None:
    try:
        return (_dt.date.fromisoformat(as_of[:10]) - _dt.date.fromisoformat(day[:10])).days
    except ValueError:
        return None


def _working(sets: Any) -> list[dict[str, Any]]:
    return [s for s in sets or [] if isinstance(s, dict) and str(s.get("type") or s.get("set_type") or "normal").lower() != "warmup"]


def _hard(s: dict[str, Any]) -> bool:
    rpe = _num(s.get("rpe"))
    return rpe is None or rpe >= THRESHOLDS["hard_set_rpe_min"]["value"]


def _e1rm(s: dict[str, Any]) -> float | None:
    from coach.coach_event_triggers import e1rm_lb  # the fleet's ONE Epley (stall_detector delegates to it too)

    return e1rm_lb(s.get("weight_kg"), s.get("reps"))


def library_index(lib: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Template id (upper) -> {movement_id, primary, secondary, pattern, job, resistance_profile, spinal_load} from the
    library's own fields."""
    out: dict[str, dict[str, Any]] = {}
    for mid, e in ((lib or {}).get("movements") or {}).items():
        tid = str(e.get("template_id") or "").upper()
        if not tid:
            continue
        tgt = e.get("target") or {}
        out[tid] = {
            "movement_id": mid,
            "title": e.get("title"),
            "primary": tgt.get("primary"),
            "secondary": list(tgt.get("secondary") or []),
            "pattern": e.get("pattern"),
            "job": e.get("job"),
            "resistance_profile": e.get("resistance_profile"),
            "spinal_load": (e.get("joint_stress") or {}).get("spinal_load"),
        }
    return out


def _exposures(workouts: list[dict[str, Any]] | None, as_of: str, days: int) -> list[tuple[str, str, dict[str, Any]]]:
    """(day, template id, exercise) for every logged exercise in the `days` up to and including `as_of`, oldest first."""
    out = []
    for w in workouts or []:
        day = _day(w)
        ago = _ago(as_of, day) if len(day) == 10 else None
        if ago is None or ago < 0 or ago >= days:
            continue
        for ex in w.get("exercises") or []:
            out.append((day, str(ex.get("template_id") or "").upper(), ex))
    return sorted(out, key=lambda r: r[0])


# ── the inputs, one function each ─────────────────────────────────────────────
def hard_sets_by_muscle(workouts: list[dict[str, Any]] | None, index: dict[str, dict[str, Any]], *, as_of: str, days: int = 7) -> dict:
    """Muscle -> hard sets in the window, primary 1.0 and each secondary `secondary_muscle_credit` (heuristic). A template
    the library cannot place is counted under `unplaced`, never guessed."""
    credit = THRESHOLDS["secondary_muscle_credit"]["value"]
    out: dict[str, float] = {}
    for _day_, tid, ex in _exposures(workouts, as_of, days):
        n = sum(1 for s in _working(ex.get("sets")) if _hard(s))
        if not n:
            continue
        row = index.get(tid)
        if not row or not row.get("primary"):
            out["unplaced"] = out.get("unplaced", 0.0) + n
            continue
        out[row["primary"]] = out.get(row["primary"], 0.0) + n
        for m in row["secondary"]:
            out[m] = out.get(m, 0.0) + n * credit
    return {k: round(v, 1) for k, v in sorted(out.items())}


def _trend(points: list[tuple[str, float | None, float | None, float | None, int | None]]) -> dict[str, Any]:
    """One movement's performed trend from its top working sets (day, e1RM, RPE, load, reps), oldest first."""
    from training import stall_detector

    pts = [p for p in points if p[1] is not None]
    if len(pts) < 2:
        return {"trend": "unknown", "why": f"{len(pts)} exposure(s) with a readable top set"}
    drop = THRESHOLDS["e1rm_drop_pct"]["value"]
    best_before = max(p[1] for p in pts[:-2]) if len(pts) > 2 else pts[0][1]
    if len(pts) > 2 and all(p[1] < best_before * (1 - drop) for p in pts[-2:]):
        return {"trend": "regressing", "why": f"the last two exposures are more than {drop:.0%} under the best before them"}
    if pts[-1][1] > max(p[1] for p in pts[:-1]):
        return {"trend": "progressing", "why": "the latest top set is a new best e1RM in the window"}
    if len(pts) < THRESHOLDS["trend_min_exposures"]["value"]:
        return {"trend": "unknown", "why": "two exposures, no new best — below the three-exposure floor for a stall"}
    try:  # #5057: the same load x reps at an easy RPE is the PRESCRIPTION holding still — a load step, never a rotation
        sp = [stall_detector.SessionPoint(date=d, load_kg=ld, reps=r, rpe=rpe) for d, _e, rpe, ld, r in pts]
        step = stall_detector.step_due(sp)
    except Exception:  # noqa: BLE001 — no charter on this bundle: no step call, the trend still stands
        step = None
    if step is not None:
        return {"trend": "step_due", "why": "the prescription held still at an easy RPE — the load steps, the movement stays"}
    return {"trend": "stalled", "why": f"no new best e1RM over the last {len(pts)} exposures at working effort"}


def movement_signals(workouts: list[dict[str, Any]] | None, *, as_of: str, window_days: int = 42) -> dict[str, dict[str, Any]]:
    """Template id -> {exposures, trend, why, discomfort_sessions, pain_sessions, rpe_drift} over the window (the block)."""
    from training.training_notes_pain import DISCOMFORT, PAIN, pain_class

    recent = THRESHOLDS["discomfort_window_days"]["value"]
    by: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for day, tid, ex in _exposures(workouts, as_of, window_days):
        if tid:
            by.setdefault(tid, []).append((day, ex))
    out: dict[str, dict[str, Any]] = {}
    for tid, rows in sorted(by.items()):
        points = []
        for day, ex in rows:
            ws = [s for s in _working(ex.get("sets")) if _num(s.get("weight_kg")) and _num(s.get("reps"))]
            top = max(ws, key=lambda s: (_e1rm(s) or 0.0), default=None)
            points.append(
                (
                    day,
                    _e1rm(top) if top else None,
                    _num((top or {}).get("rpe")),
                    _num((top or {}).get("weight_kg")),
                    _int((top or {}).get("reps")),
                )
            )
        classes = [(day, pain_class(str(ex.get("notes") or ""))) for day, ex in rows if (_ago(as_of, day) or 0) < recent]
        out[tid] = {
            "exposures": len(rows),
            **_trend(points),
            "discomfort_sessions": sum(1 for _d, c in classes if c == DISCOMFORT),
            "pain_sessions": sum(1 for _d, c in classes if c == PAIN),
            "rpe_drift": _rpe_drift(points),
        }
    return out


def _int(v: Any) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _rpe_drift(points: list[tuple[str, float | None, float | None, float | None, int | None]]) -> bool | None:
    """True when the same load x reps was logged `rpe_drift` points harder than its first logged exposure."""
    seen: dict[tuple[float, int], float] = {}
    drift = None
    for _d, _e, rpe, load, reps in points:
        if rpe is None or load is None or reps is None:
            continue
        key = (round(load, 1), reps)
        if key in seen:
            drift = bool(drift) or rpe - seen[key] >= THRESHOLDS["rpe_drift"]["value"]
        else:
            seen[key] = rpe
    return drift


def axial_stacking(workouts: list[dict[str, Any]] | None, index: dict[str, dict[str, Any]], *, as_of: str) -> list[dict[str, Any]]:
    """Redundant axial fatigue in the last 72 h: >= 3 free-weight squat/hinge compound exposures, or two heavy hinges in 48 h."""
    axial = []
    for day, tid, ex in _exposures(workouts, as_of, 3):
        row = index.get(tid) or {}
        if row.get("pattern") in AXIAL_PATTERNS and row.get("job") == "compound" and row.get("resistance_profile") == "free_weight":
            if sum(1 for s in _working(ex.get("sets")) if _hard(s)) >= 2:
                axial.append({"day": day, "movement_id": row.get("movement_id"), "pattern": row.get("pattern")})
    out = []
    if len(axial) >= THRESHOLDS["axial_stack_count"]["value"]:
        out.append({"finding": "axial_stacking", "exposures": axial, "threshold": "axial_stack_window_hours"})
    hinges = [a for a in axial if a["pattern"] == "hinge" and (_ago(as_of, a["day"]) or 0) < 2]
    if len(hinges) >= 2:
        out.append({"finding": "hinge_stacking", "exposures": hinges, "threshold": "hinge_stack_window_hours"})
    return out


def adherence(workouts: list[dict[str, Any]] | None, *, as_of: str, planned_per_week: int, days: int = 14) -> dict[str, Any]:
    """Performed lifting sessions in the window against the plan's sessions per week (the split's role count)."""
    if workouts is None:
        return {"state": "unknown", "why": "the Hevy record was not read"}
    performed = len({_day(w) for w in workouts if _ago(as_of, _day(w)) is not None and 0 <= (_ago(as_of, _day(w)) or 0) < days})
    planned = planned_per_week * days // 7
    ratio = round(performed / planned, 2) if planned else None
    low = ratio is not None and ratio < THRESHOLDS["adherence_low"]["value"]
    return {"state": "low" if low else "ok", "performed": performed, "planned": planned, "ratio": ratio}


# ── the decision ──────────────────────────────────────────────────────────────
def _signal(name: str, state: str, why: str, threshold: str | None) -> dict[str, Any]:
    return {"signal": name, "state": state, "why": why, "threshold": threshold}


def _systemic(
    readiness: str | None,
    sleep_hours: float | None,
    cardio_load: dict[str, Any] | None,
    hard_sets: dict,
    landmarks: dict | None,
    movs: dict,
) -> list[dict[str, Any]]:
    out = []
    tier = str(readiness or "").lower()
    if tier in ("green", "yellow", "red"):
        out.append(_signal("readiness", "strain" if tier == "red" else "ok", f"readiness tier {tier}", "readiness_strain"))
    else:
        out.append(_signal("readiness", "unknown", f"readiness {tier or 'not read'} — HR-derived tiers are not effort evidence", None))
    if sleep_hours is None:
        out.append(_signal("sleep", "unknown", "sleep not read", None))
    else:
        short = sleep_hours < THRESHOLDS["sleep_short_hours"]["value"]
        out.append(
            _signal("sleep", "strain" if short else "ok", "short night" if short else "sleep at or over the line", "sleep_short_hours")
        )
    cl = (cardio_load or {}).get("state")
    out.append(
        _signal("cardio_load", "strain" if cl == "high" else ("ok" if cl in CARDIO_LOAD_STATES else "unknown"), f"cardio load {cl}", None)
    )
    over = sorted(m for m, n in hard_sets.items() if (((landmarks or {}).get(m) or {}).get("MRV") or 1e9) < n)
    out.append(
        _signal(
            "weekly_sets",
            "strain" if over else ("ok" if landmarks else "unknown"),
            f"over MRV: {', '.join(over)}" if over else "no muscle over its MRV landmark",
            "weekly_sets_over",
        )
    )
    regress = sorted(t for t, s in movs.items() if s.get("trend") == "regressing")
    out.append(
        _signal(
            "strength", "strain" if regress else ("ok" if movs else "unknown"), f"regressing: {len(regress)} movement(s)", "e1rm_drop_pct"
        )
    )
    drift = sorted(t for t, s in movs.items() if s.get("rpe_drift"))
    out.append(
        _signal("effort_drift", "strain" if len(drift) >= 2 else ("ok" if movs else "unknown"), f"{len(drift)} drifting", "rpe_drift")
    )
    return out


def _swaps(movs: dict[str, dict[str, Any]], stacking: list[dict[str, Any]], index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for tid, s in sorted(movs.items()):
        if s.get("discomfort_sessions", 0) >= THRESHOLDS["discomfort_sessions"]["value"]:
            out.append(
                {
                    "template_id": tid,
                    "movement_id": (index.get(tid) or {}).get("movement_id"),
                    "why": "discomfort",
                    "threshold": "discomfort_sessions",
                }
            )
    for f in stacking:
        last = f["exposures"][-1]
        out.append({"movement_id": last["movement_id"], "why": f["finding"], "threshold": f["threshold"]})
    return out


def assess(
    *,
    workouts: list[dict[str, Any]] | None,
    lib: dict[str, Any] | None,
    as_of: str,
    readiness: str | None = None,
    sleep_hours: float | None = None,
    cardio_load: dict[str, Any] | None = None,
    landmarks: dict[str, Any] | None = None,
    planned_per_week: int = 5,
    session_minutes: float | None = None,
    minutes_ceiling: float | None = None,
) -> dict[str, Any]:
    """The recovery state and the recommended action (module doc). Pure; deterministic for its inputs."""
    index = library_index(lib)
    movs = movement_signals(workouts, as_of=as_of)
    hard = hard_sets_by_muscle(workouts, index, as_of=as_of)
    stacking = axial_stacking(workouts, index, as_of=as_of)
    adh = adherence(workouts, as_of=as_of, planned_per_week=planned_per_week)
    signals = _systemic(readiness, sleep_hours, cardio_load, hard, landmarks, movs)
    strain = [s["signal"] for s in signals if s["state"] == "strain"]
    regressing = any(s["signal"] == "strength" and s["state"] == "strain" for s in signals)
    bad_day = any(s["signal"] in ("readiness", "sleep") and s["state"] == "strain" for s in signals)
    deload = len(strain) >= THRESHOLDS["deload_at_strain_signals"]["value"] or (regressing and bad_day)
    step = THRESHOLDS["reduce_sets_per_step"]["value"]
    reduce = 0 if len(strain) < THRESHOLDS["reduce_at_strain_signals"]["value"] else min(6, step * (len(strain) - 1))
    state = "overreached" if deload else ("strained" if reduce else ("normal" if strain or adh["state"] == "low" else "recovered"))
    over = session_minutes is not None and minutes_ceiling is not None and session_minutes > minutes_ceiling
    return {
        "issue": ISSUE,
        "version": VERSION,
        "as_of": as_of,
        "state": state,
        "action": "deload_recommended" if deload else ("reduce" if reduce else "maintain"),
        "reduce_sets": reduce,
        "never_adds": True,
        "maintain_strength": "a reduction takes accessory sets only; anchors and their top sets are held" if reduce else None,
        "swaps": _swaps(movs, stacking, index),
        "deload": {
            "recommended": deload,
            "applies": "owner-confirmed only (charter deload.owner_gated; the DELOAD# record is his word)",
            "triggers": strain if deload else [],
        },
        "signals": signals,
        "strain_signals": strain,
        "hard_sets_7d": hard,
        "stacking": stacking,
        "adherence": adh,
        "session_minutes": {"estimate": session_minutes, "ceiling": minutes_ceiling, "over": over},
        "movements": movs,
        "thresholds": THRESHOLDS,
    }


# ── the live draft hook ───────────────────────────────────────────────────────
def trim_accessory_sets(exposures: list[dict[str, Any]], n: int) -> int:
    """Take up to `n` sets off the accessories, IN PLACE: last-listed first, one set per pass, never below one set and never
    a top set; anchors are never touched. Returns the sets removed."""
    removed = 0
    order = [e for e in exposures if e.get("kind") == "accessory"][::-1]
    progressed = True
    while removed < n and progressed:
        progressed = False
        for e in order:
            if removed >= n:
                break
            idx = [i for i, s in enumerate(e.get("sets") or []) if s.get("kind") != "top"]
            if len(e.get("sets") or []) > 1 and idx:
                e["sets"].pop(idx[-1])
                removed += 1
                progressed = True
    return removed


def apply_to_session(rx: dict[str, Any], rotation: dict[str, Any] | None, assessment: dict[str, Any] | None) -> dict[str, Any]:
    """The live draft's reduction: with the selection LIVE and an assessment that recommends `reduce` (or a deload, whose
    reduction is applied while the deload itself waits for his word), take `reduce_sets` accessory sets off a COPY of the
    prescription and record it as `fatigue`. In shadow (or with no assessment) the prescription is returned untouched —
    the same object, byte for byte."""
    if ((rotation or {}).get("selection") or {}).get("mode") != MODE_LIVE or not isinstance(assessment, dict):
        return rx
    out = copy.deepcopy(rx)
    n = int(assessment.get("reduce_sets") or 0)
    removed = trim_accessory_sets(out["exposures"], n) if n > 0 else 0
    if removed:
        from training.session_cues import exposure_cue
        from training.session_shape import session_minutes_estimate

        for e in out["exposures"]:
            e["cue"] = exposure_cue(e["intensity"], e["sets"])
        out["total_sets"] = sum(len(e["sets"]) for e in out["exposures"])
        out["session_minutes"] = session_minutes_estimate(out["exposures"])
    keep = ("state", "action", "reduce_sets", "strain_signals", "swaps", "deload", "version")
    out["fatigue"] = {k: assessment.get(k) for k in keep} | {"sets_removed": removed}
    return out


def for_live_draft(rx: dict[str, Any], rotation: dict[str, Any] | None, inputs: Any, block_workouts: list[dict[str, Any]] | None) -> dict:
    """The draft path's hook (`full_body_session._prescription`): LIVE only — assess from what the draft already carries
    (the generator inputs' readiness tier, the block's Hevy record, the library, the landmarks, the session estimate) and
    apply the reduction. In shadow it returns `rx` itself before reading anything. Never raises: a failure keeps `rx`."""
    if ((rotation or {}).get("selection") or {}).get("mode") != MODE_LIVE:
        return rx
    try:
        from training import block_model, program_structure, selection_engine
        from training.training_charter import charter_value

        assessment = assess(
            workouts=block_workouts,
            lib=selection_engine.load_library_failsoft(),
            as_of=str(getattr(inputs, "target_date", "")),
            readiness=getattr(inputs, "recovery_tier", None),
            sleep_hours=getattr(inputs, "sleep_hours", None),
            cardio_load=getattr(inputs, "cardio_load", None),  # THE CARDIO SEAM (L4 cardio_model)
            landmarks=block_model.load_landmarks(),
            planned_per_week=len(program_structure.SPLIT_ROLES),
            session_minutes=(rx.get("session_minutes") or {}).get("lifting_minutes"),
            minutes_ceiling=charter_value("split.session_minutes.lifting_ceiling"),
        )
    except Exception as e:  # noqa: BLE001 — the fatigue model never blocks a draft
        import logging

        logging.getLogger(__name__).warning(f"fatigue_model: assessment failed ({type(e).__name__}) — the draft is unchanged")
        return rx
    return apply_to_session(rx, rotation, assessment)
