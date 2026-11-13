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
    cardio_load    THE CARDIO SEAM (L4): `cardio_model.cardio_load(...)`'s output as it is (`hard_minutes`, `minutes`, ...),
                   or `{"state": "low" | "moderate" | "high"}` — `cardio_state` reads either; `high` is one strain signal
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
from typing import Any

from training.stall_detector import MIN_SESSIONS

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
    "muscle_sets_over_mrv": {
        "value": "MRV",
        "label": HEURISTIC,
        "basis": "weekly hard sets above the muscle's MRV landmark (config/training_landmarks.json — practitioner volume "
        "landmarks, not individual measurements); no landmark = unknown",
    },
    "e1rm_drop_pct": {
        "value": 0.05,
        "label": HEURISTIC,
        "basis": "the latest pair of exposures of a compound both more than 5% under its best earlier e1RM (Epley) in the window "
        "— the platform's existing practice line (critics_fatigue), not a citation and not his own variance",
    },
    "trend_recent_days": {
        "value": 14,
        "label": HEURISTIC,
        "basis": "double progression repeats a load while the reps climb, and a movement trained twice a week repeats it inside "
        "one week, so a tie is not a stall: a movement PROGRESSES when its best e1RM in the last 14 days (back from its latest "
        "exposure) beats its best before them, and STALLS when it does not (#5861 L6) — a fortnight of weekly sessions",
    },
    "trend_min_exposures": {
        "value": MIN_SESSIONS,
        "label": HEURISTIC,
        "basis": "the stall detector's own trend floor (stall_detector.MIN_SESSIONS)",
    },
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
    "discomfort_window_days": {
        "value": 14,
        "label": HEURISTIC,
        "basis": "a fortnight, inclusive: a weekly movement's latest sessions sit 7 and 14 days back on its own weekday",
    },
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
        "`mcp/tools_plan._recovery_tier`); red is one strain signal. Inside an HR regime marker's window it is unknown. An ACWR "
        "of high / very_high (Whoop strain, also HR-derived) votes in the SAME signal, never a second one (#5861 L6)",
    },
    "cardio_hard_minutes_high": {
        "value": 60,
        "label": HEURISTIC,
        "basis": "more hard cardio minutes (cardio_model.HARD_RPE or above) in the window than the charter's own conditioning "
        "budget (two blocks a week of at most 30 min) reads as high cardio load. Walking from steps (`cardio_model.cardio_load` "
        "steps_by_day) is counted and reported but is NOT a strain vote: a high daily step count is this trainee's baseline, and "
        "a spike rule needs a personal multi-week baseline nobody has set (an owner decision, #5861 L6)",
    },
    "reset_detect_pct": {
        "value": 0.07,
        "label": HEURISTIC,
        "basis": "#5861 FIX7 (sixth red team: the reset ratchet): an exposure whose top working load sits 7%+ under the comparable "
        "exposure before it, not ground out (RPE < 9), is a load DROP — a STALL_RULE reset, a LOAD_POLICY cut or a deload (~10%, "
        "floored to the implement step); the trend is judged from that exposure on, never against the pre-drop best",
    },
    "post_reset_min_exposures": {
        "value": 3,
        "label": HEURISTIC,
        "basis": "#5861 FIX7: after a reset no stall (or regression) call before 3 exposures since it, the reset session included — "
        "a reset is a short rebuild, not a weekly cut: a lift resets at most once per 3 post-reset exposures",
    },
    "deficit_hold_pct": {
        "value": 0.03,
        "label": HEURISTIC,
        "basis": "#5861 FIX7: in a calorie deficit an e1RM held within 3% of its best at steady effort (top-set RPE not drifting up "
        "by rpe_drift) is MAINTAINED, the retention goal met — it holds and keeps building reps/effort; a reset is for rep loss with "
        "effort drift (practitioner consensus for a cut, not a measured band; re-tuned at the block retro)",
    },
    "deficit_rate_pct_bw": {
        "value": 0.25,
        "label": HEURISTIC,
        "basis": "#5861 FIX7: a deficit is read when the weekly loss over the weigh-ins the draft read "
        "between the oldest and newest week of weigh-ins read is at least 0.25 %BW/week; under two weeks of weigh-ins = unknown (the stall rule then stands)",
    },
    "sleep_short_hours": {"value": 6.5, "label": HEURISTIC, "basis": "the charter's progression refusal text (sleep < 6.5 h)"},
    "adherence_low": {
        "value": 0.6,
        "label": HEURISTIC,
        "basis": "fewer than 60% of the planned sessions performed in 14 days: keep the plan short and never add — adherence "
        "comes first for long-term results. With no other reduction it takes one step (reduce_sets_per_step) of accessory sets off "
        "(#5861 L6: the basis said 'short' and the code only reported it); anchors held",
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

RESET_MIN_KG = 4.5
"""#5861 FIX7, heuristic (part of `reset_detect_pct`): a load drop under ~10 lb is an implement step on a light lift (dumbbells,
a stack), never read as a reset — a stall reset or a cut on an anchor is 10%+ of a working load."""
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
    from common.pacific_time import parse_day_key  # a calendar-day key, never an instant (#3609)

    a, d = parse_day_key(str(as_of)[:10]), parse_day_key(str(day)[:10])
    return (a - d).days if a and d else None


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


def _trend(
    points: list[tuple[str, float | None, float | None, float | None, int | None]],
    deficit: bool | None = None,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    """One movement's performed trend from its top working sets (day, e1RM, RPE, load, reps), oldest first. #5861 FIX7: judged
    from the latest reset on (`_reset_start`): with fewer than post_reset_min_exposures since it the trend is `rebuilding`
    (no stall or regression call); in a deficit a held e1RM at steady effort is `holding`, never `stalled` (`_judge`)."""
    keep = [i for i, p in enumerate(points) if p[1] is not None]
    pts = [points[i] for i in keep]
    rl = [(roles or [])[i] if i < len(roles or []) else "" for i in keep]
    start, scheme = _reset_start(pts, deficit, rl)
    if start is None:
        return _judge(pts, deficit, rl)
    since, need = pts[start:], int(THRESHOLDS["post_reset_min_exposures"]["value"])
    reset = {"reset_at": pts[start][0], "since_reset": len(since)}
    if len(since) < need:
        trend = "rebuilding" if scheme else "returning"  # a stall reset's rep scheme stays; a cut / deload drop just builds back
        why = f"a load drop on {pts[start][0]}: {len(since)} of {need} exposures since — {trend}, no stall call (post_reset_min_exposures)"
        return {"trend": trend, "why": why, **reset}
    return _judge(since, deficit, rl[start:]) | reset


def _reset_start(
    pts: list[tuple[str, float | None, float | None, float | None, int | None]], deficit: bool | None, roles: list[str] | None = None
) -> tuple[int | None, bool]:
    """(index, scheme) of the latest load DROP in the window (`reset_detect_pct`): a top load 7%+ under the latest COMPARABLE
    exposure before it (`_comparable`: the same session role, else a top set within 3 reps — a volume day's lighter squat is not a
    drop from the heavy day's) and not ground out (RPE < 9: a lighter load ground out is a regression). Whatever made it — a stall
    reset, a regression cut, a deload — judging the next exposures against the pre-drop best is the ratchet the sixth red team
    proved. `scheme`: the drop came with MORE reps than the exposure before it (the stall reset's own signature: its rep scheme
    stays while the load builds back). A drop inside the post-reset window is not a second drop. (None, False) = none."""
    start, scheme, drop = None, False, float(THRESHOLDS["reset_detect_pct"]["value"])
    need = int(THRESHOLDS["post_reset_min_exposures"]["value"])
    roles = roles or [""] * len(pts)
    tight = _two_band(pts, drop)  # a heavy day and a volume day on one template (titles unread): compare within 1 rep only
    for k in range(1, len(pts)):
        j = next((i for i in range(k - 1, -1, -1) if _comparable(pts[i], pts[k], roles[i], roles[k], 1 if tight else 3)), None)
        before, now = (pts[j][3] if j is not None else None), pts[k][3]
        if j is None or before is None or now is None or now > before * (1 - drop) or before - now < RESET_MIN_KG:
            continue  # not a drop — or one implement step on a light lift (a 2.5-lb dumbbell jump is noise, not a reset)
        if pts[k][2] is not None and float(pts[k][2]) >= 9.0:
            continue  # a lighter load ground out at RPE 9+ is a regression, never a reset done as written
        if start is not None and k - start < need:
            continue  # still rebuilding from the last drop: a lighter session here is not a second one
        start = k
        scheme = pts[k][4] is not None and pts[j][4] is not None and int(pts[k][4] or 0) > int(pts[j][4] or 0)
    return start, scheme


def _comparable(a: tuple[Any, ...], b: tuple[Any, ...], role_a: str, role_b: str, reps: int = 3) -> bool:
    """Two exposures of one lift prescribed alike: the same session role when both are known, else top sets within `reps` reps."""
    if role_a and role_b:
        return role_a == role_b
    return a[4] is not None and b[4] is not None and abs(int(a[4]) - int(b[4])) <= reps


def _two_band(pts: list[tuple[str, float | None, float | None, float | None, int | None]], drop: float) -> bool:
    """The window shows a lift trained in two bands (a heavy day and a lighter volume day): somewhere a 7%+ lighter exposure is
    followed straight away by a climb back to the heavier load — never what a reset or a cut does."""
    loads = [p[3] for p in pts]
    return any(
        a is not None and b is not None and c is not None and b <= a * (1 - drop) and c >= a * 0.97
        for a, b, c in zip(loads, loads[1:], loads[2:])
    )


def session_role(workout: dict[str, Any]) -> str:
    """The session role a Hevy workout title names (`LOWER-HEAVY — W10 — …` -> `lower_heavy`); '' when it names none."""
    import re

    head = re.split(r"\s+[—–-]\s+", str(workout.get("title") or "").strip(), maxsplit=1)[0]
    role = re.sub(r"[^a-z]+", "_", head.lower()).strip("_")
    return role if role in ("upper_heavy", "lower_heavy", "shoulders_arms", "upper_volume", "lower_volume", "full_body") else ""


def _judge(
    pts: list[tuple[str, float | None, float | None, float | None, int | None]], deficit: bool | None = None, roles: list[str] | None = None
) -> dict[str, Any]:
    """The trend over readable points (the pre-FIX7 rule), plus the deficit hold (`deficit_hold_pct`, judged per session role:
    a heavy day and a volume day of one lift are each held against their own best)."""
    from training import stall_detector

    if len(pts) < 2:
        return {"trend": "unknown", "why": f"{len(pts)} exposure(s) with a readable top set"}
    drop = THRESHOLDS["e1rm_drop_pct"]["value"]
    e1 = [float(p[1] or 0.0) for p in pts]
    best_before = max(e1[:-2]) if len(e1) > 2 else e1[0]
    if len(e1) > 2 and all(v < best_before * (1 - drop) for v in e1[-2:]):
        return {"trend": "regressing", "why": f"the latest pair of exposures are both more than {drop:.0%} under the best before them"}
    if _recent_best(pts, e1):
        return {"trend": "progressing", "why": f"a new best e1RM in the last {THRESHOLDS['trend_recent_days']['value']} days"}
    if _load_pr(pts):  # #5861 FIX7: a heavier top load at an equal e1RM is the double progression stepping, never a stall
        return {"trend": "progressing", "why": "a heavier top load in the recent window at a held e1RM (the double progression's step)"}
    if len(pts) < THRESHOLDS["trend_min_exposures"]["value"]:
        return {"trend": "unknown", "why": "no new best yet, and below trend_min_exposures for a stall call"}
    try:  # #5057: the same load x reps at an easy RPE is the PRESCRIPTION holding still — a load step, never a rotation
        sp = [stall_detector.SessionPoint(date=d, load_kg=ld, reps=r, rpe=rpe) for d, _e, rpe, ld, r in pts]
        step = stall_detector.step_due(sp)
    except Exception:  # noqa: BLE001 — no charter on this bundle: no step call, the trend still stands
        step = None
    if step is not None:
        return {"trend": "step_due", "why": "the prescription held still at an easy RPE — the load steps, the movement stays"}
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(roles or [""] * len(pts)):
        groups.setdefault(r or "", []).append(i)
    if deficit and all(_held([pts[i] for i in ix], [e1[i] for i in ix]) for ix in groups.values()):
        band = THRESHOLDS["deficit_hold_pct"]["value"]
        return {"trend": "holding", "why": f"in a deficit: e1RM within {band:.0%} of its best at steady effort — maintained, not stalled"}
    return {"trend": "stalled", "why": f"no new best e1RM over the last {len(pts)} exposures at working effort"}


def _held(pts: list[tuple[str, float | None, float | None, float | None, int | None]], e1: list[float]) -> bool:
    """`deficit_hold_pct`: the latest effort-adjusted e1RM within the band of the best, and its top-set RPE not `rpe_drift` over
    the best's. Effort-adjusted (`_e1rm_rir`): a top set's reps plus its reps in reserve (10 - RPE) — 4 reps at RPE 8 and 6 at
    RPE 10 are the same strength; with no RPE logged the plain Epley e1RM stands."""
    adj = [_e1rm_rir(p) or v for p, v in zip(pts, e1)]
    best = max(range(len(adj)), key=lambda i: adj[i])
    if adj[-1] < adj[best] * (1 - float(THRESHOLDS["deficit_hold_pct"]["value"])):
        return False
    rpe_now, rpe_best = pts[-1][2], pts[best][2]
    return rpe_now is None or rpe_best is None or float(rpe_now) - float(rpe_best) < float(THRESHOLDS["rpe_drift"]["value"])


def _e1rm_rir(p: tuple[str, float | None, float | None, float | None, int | None]) -> float | None:
    """Epley on reps + reps in reserve (10 - RPE, RPE clamped 6-10); None without a load, reps and RPE."""
    if p[2] is None or p[3] is None or p[4] is None:
        return None
    rir = 10.0 - min(10.0, max(6.0, float(p[2])))
    return float(p[3]) * 2.20462262 * (1 + (int(p[4]) + rir) / 30.0)


def loss_rate_pct(weights_by_day: Any) -> float | None:
    """The weekly loss (%BW/week) between the oldest and the newest 7 days of the last 28 days of weigh-ins read; None under two
    weeks of them."""
    from common.pacific_time import parse_day_key

    raw = {parse_day_key(str(k)[:10]): _num(v) for k, v in (weights_by_day or {}).items()} if isinstance(weights_by_day, dict) else {}
    days = {d: float(v) for d, v in raw.items() if d is not None and v}
    if days:  # the last four weeks of weigh-ins only: the CURRENT rate, never the whole history's
        days = {d: v for d, v in days.items() if (max(days) - d).days < 28}
    if not days or (max(days) - min(days)).days < 13:
        return None
    lo, hi = min(days), max(days)
    old = [v for d, v in days.items() if (d - lo).days < 7]
    new = [v for d, v in days.items() if (hi - d).days < 7]
    weeks = max((hi - lo).days / 7.0 - 1.0, 1.0)
    return (sum(old) / len(old) - sum(new) / len(new)) / weeks / (sum(new) / len(new)) * 100


def in_deficit(weights_by_day: Any) -> bool | None:
    """`deficit_rate_pct_bw` over `loss_rate_pct`; None under two weeks of weigh-ins. Read here, not through the loss-rate module
    (no live path reads the rate proposal: the rate-proposal guard)."""
    rate = loss_rate_pct(weights_by_day)
    return None if rate is None else rate >= float(THRESHOLDS["deficit_rate_pct_bw"]["value"])


def _load_pr(pts: list[tuple[str, float | None, float | None, float | None, int | None]]) -> bool:
    """The recent window's (`trend_recent_days`) heaviest top load beats every earlier one, its effort under a grind (RPE < 9)."""
    span = THRESHOLDS["trend_recent_days"]["value"]
    recent = [p for p in pts if (_ago(str(pts[-1][0]), str(p[0])) or 0) < span]
    earlier = pts[: len(pts) - len(recent)]
    loads = [float(p[3]) for p in earlier if p[3] is not None]
    hit = [p for p in recent if p[3] is not None and (p[2] is None or float(p[2]) < 9.0)]
    return bool(loads and hit) and max(float(p[3]) for p in hit) > max(loads) + 0.1


def _recent_best(pts: list[tuple[str, float | None, float | None, float | None, int | None]], e1: list[float]) -> bool:
    """`trend_recent_days`: the best e1RM inside the recent window (back from the latest exposure) beats the best before it.
    With nothing before the window, any exposure after the first beating the first counts (a new movement climbing)."""
    span = THRESHOLDS["trend_recent_days"]["value"]
    recent = [v for p, v in zip(pts, e1) if (_ago(str(pts[-1][0]), str(p[0])) or 0) < span]
    earlier = e1[: len(e1) - len(recent)]
    if not earlier:
        return max(e1[1:]) > e1[0]
    return max(recent) > max(earlier)


def movement_signals(
    workouts: list[dict[str, Any]] | None, *, as_of: str, window_days: int = 42, deficit: bool | None = None
) -> dict[str, dict[str, Any]]:
    """Template id -> {exposures, trend, why, discomfort_sessions, pain_sessions, rpe_drift} over the window (the block).
    `deficit` (#5861 FIX7, `in_deficit`): True lets a held e1RM read `holding`; None/False keeps the stall rule."""
    from training.live_rules import LIGHT, note_class  # #5861 FIX5: a joint-located "sore" at the mild line is light discomfort
    from training.training_notes_pain import DISCOMFORT, PAIN

    recent = THRESHOLDS["discomfort_window_days"]["value"]
    by: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    role_of = {(_day(w), id(x)): session_role(w) for w in workouts or [] for x in w.get("exercises") or []}
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
        # #5861 L6: an INCLUSIVE fortnight — a weekly lift's previous two exposures sit 7 and 14 days back on its own weekday
        classes = [(day, note_class(str(ex.get("notes") or ""))) for day, ex in rows if (_ago(as_of, day) or 0) <= recent]
        out[tid] = {
            "exposures": len(rows),
            **_trend(points, deficit, [role_of.get((d, id(x)), "") for d, x in rows]),
            "discomfort_sessions": sum(1 for _d, c in classes if c == DISCOMFORT),
            "light_sessions": sum(1 for _d, c in classes if c == LIGHT),  # FIX5: kept, lighter (the joint rule) — never swapped
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
    """Redundant axial fatigue: >= axial_stack_count spine-loading squat/hinge exposures inside axial_stack_window_hours, or two
    heavy hinges inside hinge_stack_window_hours. #5861 FIX5: ONE spine-loading definition (`live_balance.spine_loading`, the
    stacking rule's and the gates'), and the windows are the table's values (the fifth red team: 72 h and 48 h were hard-coded)."""
    from training.live_balance import spine_loading

    axial = []
    for day, tid, ex in _exposures(workouts, as_of, int(THRESHOLDS["axial_stack_window_hours"]["value"]) // 24):
        row = index.get(tid) or {}
        if spine_loading({"pattern": row.get("pattern"), "job": row.get("job"), "joint_stress": {"spinal_load": row.get("spinal_load")}}):
            if sum(1 for s in _working(ex.get("sets")) if _hard(s)) >= 2:
                axial.append({"day": day, "movement_id": row.get("movement_id"), "pattern": row.get("pattern")})
    out = []
    if len(axial) >= THRESHOLDS["axial_stack_count"]["value"]:
        out.append({"finding": "axial_stacking", "exposures": axial, "threshold": "axial_stack_window_hours"})
    hinge_days = int(THRESHOLDS["hinge_stack_window_hours"]["value"]) // 24
    hinges = [a for a in axial if a["pattern"] == "hinge" and (_ago(as_of, a["day"]) or 0) < hinge_days]
    if len(hinges) >= 2:
        out.append({"finding": "hinge_stacking", "exposures": hinges, "threshold": "hinge_stack_window_hours"})
    return out


def hevy_cardio_load(
    workouts: list[dict[str, Any]] | None,
    lib: dict[str, Any] | None,
    *,
    as_of: str,
    days: int = 7,
    steps_by_day: dict[str, Any] | None = None,
) -> dict | None:
    """The cardio seam's live feed (L4): the Hevy record's timed cardio blocks in the window, as `cardio_model.cardio_load`
    sessions (`movement_id` + `entry`, minutes from the logged durations, the block's highest logged RPE). Walking and the
    other sources are the cardio model's own reads, not this one. None when the window holds no timed cardio."""
    from training import cardio_model

    mv = (lib or {}).get("movements") or {}
    index = library_index(lib)
    sessions = []
    for _day_, tid, ex in _exposures(workouts, as_of, days):
        mid = (index.get(tid) or {}).get("movement_id")
        if not mid or (index.get(tid) or {}).get("pattern") != "cardio":
            continue
        sets = ex.get("sets") or []
        secs = sum(_num(x.get("duration_seconds")) or 0.0 for x in sets if isinstance(x, dict))
        rpes = [r for r in (_num(x.get("rpe")) for x in sets if isinstance(x, dict)) if r is not None]
        if secs > 0:
            sessions.append({"movement_id": mid, "entry": mv.get(mid), "minutes": secs / 60.0, "rpe": max(rpes) if rpes else None})
    if not sessions and not steps_by_day:
        return None
    return cardio_model.cardio_load(sessions, steps_by_day=steps_by_day or None)  # #5861 L6: the walking dose rides apart


def adherence(workouts: list[dict[str, Any]] | None, *, as_of: str, planned_per_week: int, days: int = 14) -> dict[str, Any]:
    """Performed lifting sessions in the window against the plan's sessions per week (the split's role count)."""
    if workouts is None:
        return {"state": "unknown", "why": "the Hevy record was not read"}
    performed = len({_day(w) for w in workouts if _ago(as_of, _day(w)) is not None and 0 <= (_ago(as_of, _day(w)) or 0) < days})
    planned = planned_per_week * days // 7
    ratio = round(performed / planned, 2) if planned else None
    low = ratio is not None and ratio < THRESHOLDS["adherence_low"]["value"]
    # #5861 L6: the record is the BLOCK's — a block that started inside the window under-counts; only a record reaching back
    # over the whole window may shorten a session (`assess`), so a block start is never read as missed sessions
    oldest = max((_ago(as_of, _day(w)) or 0) for w in workouts) if workouts else 0
    return {
        "state": "low" if low else "ok",
        "performed": performed,
        "planned": planned,
        "ratio": ratio,
        "window_covered": oldest >= days - 1,
    }


# ── the decision ──────────────────────────────────────────────────────────────
def cardio_state(load: dict[str, Any] | None) -> str | None:
    """The cardio seam (L4): a given `state`, else `cardio_model.cardio_load`'s `hard_minutes` against
    `cardio_hard_minutes_high`; None = unread."""
    if not isinstance(load, dict):
        return None
    if load.get("state") in CARDIO_LOAD_STATES:
        return str(load["state"])
    hard = _num(load.get("hard_minutes"))
    if hard is None:
        return None
    return (
        "high"
        if hard > THRESHOLDS["cardio_hard_minutes_high"]["value"]
        else ("moderate" if (_num(load.get("minutes")) or 0) > 0 else "low")
    )


def _signal(name: str, state: str, why: str, threshold: str | None) -> dict[str, Any]:
    return {"signal": name, "state": state, "why": why, "threshold": threshold}


def _systemic(
    readiness: str | None,
    acwr: str | None,
    sleep_hours: float | None,
    cardio_load: dict[str, Any] | None,
    hard_sets: dict,
    landmarks: dict | None,
    movs: dict,
) -> list[dict[str, Any]]:
    out = []
    tier = str(readiness or "").lower()
    high_acwr = str(acwr or "").lower() in ("high", "very_high")
    if tier in ("green", "yellow", "red"):
        # #5861 L6: ACWR (Whoop strain) and the readiness tier (Whoop recovery) are both HR-derived — ONE vote, never two
        why = f"readiness tier {tier}" + (f", ACWR {acwr}" if high_acwr else "")
        strain = tier == str(THRESHOLDS["readiness_strain"]["value"]) or high_acwr  # #5861 FIX5: the table's tier, read
        out.append(_signal("readiness", "strain" if strain else "ok", why, "readiness_strain"))
    else:
        out.append(_signal("readiness", "unknown", f"readiness {tier or 'not read'} — HR-derived tiers are not effort evidence", None))
    if sleep_hours is None:
        out.append(_signal("sleep", "unknown", "sleep not read", None))
    else:
        short = sleep_hours < THRESHOLDS["sleep_short_hours"]["value"]
        out.append(
            _signal("sleep", "strain" if short else "ok", "short night" if short else "sleep at or over the line", "sleep_short_hours")
        )
    cl = cardio_state(cardio_load)
    walk = (cardio_load or {}).get("walking") if isinstance(cardio_load, dict) else None
    walked = f"; steps ~{walk.get('steps_per_day')}/day reported (no aerobic credit, ruling 12), not a strain vote" if walk else ""
    out.append(
        _signal(
            "cardio_load",
            "strain" if cl == "high" else ("ok" if cl in CARDIO_LOAD_STATES else "unknown"),
            f"cardio load {cl}{walked}",
            "cardio_hard_minutes_high",
        )
    )
    over = sorted(m for m, n in hard_sets.items() if (((landmarks or {}).get(m) or {}).get("MRV") or 1e9) < n)
    out.append(
        _signal(
            "weekly_sets",
            "strain" if over else ("ok" if landmarks else "unknown"),
            f"over MRV: {', '.join(over)}" if over else "no muscle over its MRV landmark",
            "muscle_sets_over_mrv",
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


FATIGUE_LEVELS = {"recovered": "low", "normal": "normal", "strained": "elevated", "overreached": "high"}
"""L5's interface (the unwired loss-rate band proposal's `fatigue_level`, vocabulary low | normal | elevated | high): the
recovery state mapped one-to-one. `elevated` is that proposal's watch, `high` (a recommended deload) its slow-down. Named,
never imported: no live module reads the rate proposal before the owner decides (L5's own guard)."""


def fatigue_level(state: str | None) -> str | None:
    """L5's `fatigue_level` for a recovery state (`FATIGUE_LEVELS`); None when unknown."""
    return FATIGUE_LEVELS.get(str(state)) if state else None


def assess(
    *,
    workouts: list[dict[str, Any]] | None,
    lib: dict[str, Any] | None,
    as_of: str,
    readiness: str | None = None,
    sleep_hours: float | None = None,
    cardio_load: dict[str, Any] | None = None,
    acwr: str | None = None,
    landmarks: dict[str, Any] | None = None,
    planned_per_week: int = 5,
    session_minutes: float | None = None,
    minutes_ceiling: float | None = None,
    deficit: bool | None = None,
) -> dict[str, Any]:
    """The recovery state and the recommended action (module doc). Pure; deterministic for its inputs."""
    index = library_index(lib)
    movs = movement_signals(workouts, as_of=as_of, deficit=deficit)
    hard = hard_sets_by_muscle(workouts, index, as_of=as_of)
    stacking = axial_stacking(workouts, index, as_of=as_of)
    adh = adherence(workouts, as_of=as_of, planned_per_week=planned_per_week)
    signals = _systemic(readiness, acwr, sleep_hours, cardio_load, hard, landmarks, movs)
    strain = [s["signal"] for s in signals if s["state"] == "strain"]
    regressing = any(s["signal"] == "strength" and s["state"] == "strain" for s in signals)
    bad_day = any(s["signal"] in ("readiness", "sleep") and s["state"] == "strain" for s in signals)
    deload = len(strain) >= THRESHOLDS["deload_at_strain_signals"]["value"] or (regressing and bad_day)
    step = THRESHOLDS["reduce_sets_per_step"]["value"]
    reduce = 0 if len(strain) < THRESHOLDS["reduce_at_strain_signals"]["value"] else min(6, step * (len(strain) - 1))
    reasons = [f"{len(strain)} strain signals"] if reduce else []
    strained = bool(reduce)  # the recovery STATE reads strain only; an adherence trim is not a recovery verdict
    state = "overreached" if deload else ("strained" if strained else ("normal" if strain or adh["state"] == "low" else "recovered"))
    if adh["state"] == "low" and adh.get("window_covered") and not reduce:  # #5861 L6: `adherence_low`'s "keep it short"
        reduce, reasons = step, ["adherence low: a shorter session is easier to keep; anchors held"]
    over = session_minutes is not None and minutes_ceiling is not None and session_minutes > minutes_ceiling
    return {
        "issue": ISSUE,
        "version": VERSION,
        "as_of": as_of,
        "state": state,
        "fatigue_level": fatigue_level(state),  # L5's loss-rate proposal input (vocabulary: FATIGUE_LEVELS)
        "action": "deload_recommended" if deload else ("reduce" if reduce else "maintain"),
        "reduce_sets": reduce,
        "reduce_reasons": reasons,
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
def trim_accessory_sets(exposures: list[dict[str, Any]], n: int, order: list[dict[str, Any]] | None = None) -> int:
    """Take up to `n` sets off, IN PLACE: in `order` (default: the accessories, last-listed first), one set per pass, never
    below an exposure's `live_min_sets` (default one) and never a top set. The default order never touches an anchor; the
    live order (`live_program.trim_order`, #5861 red team) takes compounds' back-offs first, never below two sets. Returns
    the sets removed."""
    removed = 0
    order = order if order is not None else [e for e in exposures if e.get("kind") == "accessory"][::-1]
    progressed = True
    while removed < n and progressed:
        progressed = False
        for e in order:
            if removed >= n:
                break
            idx = [i for i, s in enumerate(e.get("sets") or []) if s.get("kind") != "top"]
            if len(e.get("sets") or []) > int(e.get("live_min_sets") or 1) and idx:
                e["sets"].pop(idx[-1])
                removed += 1
                progressed = True
    return removed


def apply_to_session(
    rx: dict[str, Any], rotation: dict[str, Any] | None, assessment: dict[str, Any] | None, trim_order: Any = None
) -> dict[str, Any]:
    """The live draft's reduction: with the selection LIVE and an assessment that recommends `reduce` (or a deload, whose
    reduction is applied while the deload itself waits for his word), take `reduce_sets` accessory sets off a COPY of the
    prescription and record it as `fatigue`. In shadow (or with no assessment) the prescription is returned untouched —
    the same object, byte for byte."""
    if ((rotation or {}).get("selection") or {}).get("mode") != MODE_LIVE or not isinstance(assessment, dict):
        return rx
    out = copy.deepcopy(rx)
    n = int(assessment.get("reduce_sets") or 0)
    adh_only = any(str(r).startswith("adherence") for r in assessment.get("reduce_reasons") or [])
    pick = getattr(trim_order, "adherence", None) if adh_only and callable(getattr(trim_order, "adherence", None)) else trim_order
    order = pick(out["exposures"]) if callable(pick) else None  # #5861 L6: surplus-first, else last-listed first
    shaped = assessment.get("action") == "deload_recommended" and any(e.get("live_cost") for e in out["exposures"])
    if shaped:  # #5861 red team: a recommended deload cuts the compounds and keeps isolation (live_program.deload_shape)
        from training import live_program

        removed = live_program.deload_shape(out["exposures"], confirmed=bool(out.get("deload_trim")))  # FIX7: his word applies RPE 7
    else:
        removed = trim_accessory_sets(out["exposures"], n, order) if n > 0 else 0
    if removed:
        from training.session_cues import exposure_cue
        from training.session_shape import session_minutes_estimate

        for e in out["exposures"]:
            e["cue"] = exposure_cue(e["intensity"], e["sets"])
        out["total_sets"] = sum(len(e["sets"]) for e in out["exposures"])
        out["session_minutes"] = session_minutes_estimate(out["exposures"])
    keep = ("state", "fatigue_level", "action", "reduce_sets", "reduce_reasons", "strain_signals", "swaps", "deload", "version")
    out["fatigue"] = {k: assessment.get(k) for k in keep} | {"sets_removed": removed} | ({"shape": "deload_shape"} if shaped else {})
    return out


def for_live_draft(
    rx: dict[str, Any], rotation: dict[str, Any] | None, inputs: Any, block_workouts: list[dict[str, Any]] | None, trim_order: Any = None
) -> dict:
    """The draft path's hook (`full_body_session._prescription`): LIVE only — assess from what the draft already carries
    (the generator inputs' readiness tier, the block's Hevy record, the library, the landmarks, the session estimate) and
    apply the reduction. In shadow it returns `rx` itself before reading anything. Never raises: a failure keeps `rx`."""
    if ((rotation or {}).get("selection") or {}).get("mode") != MODE_LIVE:
        return rx
    try:
        from training import block_model, program_structure, selection_engine
        from training.training_charter import charter_value

        lib, as_of = selection_engine.load_library_failsoft(), str(getattr(inputs, "target_date", ""))
        assessment = assess(
            workouts=block_workouts,
            lib=lib,
            as_of=as_of,
            readiness=getattr(inputs, "recovery_tier", None),
            acwr=getattr(inputs, "acwr_flag", None),  # #5861 L6: the autoreg key (`high` / `very_high`), one HR-derived vote
            sleep_hours=getattr(inputs, "sleep_hours", None),
            cardio_load=getattr(inputs, "cardio_load", None)
            or hevy_cardio_load(block_workouts, lib, as_of=as_of, steps_by_day=getattr(inputs, "steps_by_day", None)),  # the L4 seam
            landmarks=block_model.load_landmarks(),
            planned_per_week=len(program_structure.SPLIT_ROLES),
            session_minutes=(rx.get("session_minutes") or {}).get("lifting_minutes"),
            minutes_ceiling=charter_value("split.session_minutes.lifting_ceiling"),
            deficit=in_deficit(getattr(inputs, "weights_by_day", None)),  # #5861 FIX7: a held e1RM in a deficit is not a stall
        )
    except Exception as e:  # noqa: BLE001 — the fatigue model never blocks a draft
        import logging

        logging.getLogger(__name__).warning(f"fatigue_model: assessment failed ({type(e).__name__}) — the draft is unchanged")
        return rx
    return apply_to_session(rx, rotation, assessment, trim_order)
