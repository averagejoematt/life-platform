"""
stall_detector.py — a stall may not be called from performed data alone (#3928).

THE DEFECT THIS MODULE EXISTS TO END
------------------------------------
At a FIXED load × FIXED reps, estimated 1RM is constant *by construction*: Epley is
a pure function of (weight, reps), so a series of identical sets produces an
identical e1RM series no matter how the lift actually felt or what it cost. When
the platform itself prescribed that fixed load × those fixed reps, a "stall" read
off the performed data is not an observation about Matthew — it is the platform
re-reading the number it wrote down. The only residual signal in that window is
RPE, which is **self-reported**, and the owner's ruling (2026-09-19, §7 of the
owner-private TRAINING_CALIBRATION.md) is explicit:

    a stall may not be called from performed data alone — diff prescribed vs
    performed before calling a stall, and label RPE as self-reported wherever it
    drives the call.

So the prescribed-vs-performed diff is an **input to the detector**, not a
courtesy the caller may skip: ``assess_stall`` takes session points that each
carry their own prescription, and the one thing it can never return on a window
that matched the prescription at fixed load × fixed reps is ``stall``.

THE VERDICTS
------------
``stall``        the prescription asked for MORE (load or reps climbed across the
                 window) and the performed top-set e1RM did not follow, flat
                 inside its own noise band. Names both numbers in ``reason``.
``progressing``  net e1RM rose beyond that lift's own session-to-session noise.
``regressing``   net e1RM fell beyond it.
``unknown``      every other state — and deliberately the state a matched, fixed
                 prescription lands in. ``unknown`` is a real answer here, not a
                 failure: "we cannot tell from this window" has never been the
                 same claim as "he is not progressing" (ADR-104).

THRESHOLDS ARE PERSONAL VARIANCE, NEVER ROUND NUMBERS (ADR-105 rule 4)
----------------------------------------------------------------------
"Flat" is not "±5 lb". It is *inside one SD of that lift's own session-to-session
e1RM deltas* — the same construction ``coach_event_triggers.detect_lift_pr`` uses
for a PR, and for the same reason: a 2.5 lb wobble on a lift that swings 15 lb
between sessions is not news in either direction. Same for RPE: a drift only
counts when it clears the SD of his own RPE deltas.

RPE IS LABELLED WHEREVER IT IS USED
-----------------------------------
Any output whose reasoning consulted RPE carries ``basis: "self-reported RPE"``
at the top level and an ``rpe`` block naming n and the drift. An output that
never consulted it carries ``basis: "measured load × reps"``. The field is on the
verdict, not in prose, so a downstream renderer cannot drop the label while
keeping the number.

NO I/O. The module is pure: dataclasses in, dict out, no clock, no AWS, no model.
The fetch half lives at the call site (``mcp/tools_hevy_routine.py`` action
``stall_check``), which is what makes every branch below directly fixture-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# ── Verdicts ──────────────────────────────────────────────────────────────────
VERDICT_STALL = "stall"
VERDICT_PROGRESSING = "progressing"
VERDICT_REGRESSING = "regressing"
VERDICT_UNKNOWN = "unknown"

# ── Bases (the label on the input a verdict actually leaned on) ───────────────
BASIS_MEASURED = "measured load × reps"
BASIS_SELF_REPORTED_RPE = "self-reported RPE"

# ── Prescription-match states ─────────────────────────────────────────────────
MATCH_AS_PRESCRIBED = "as_prescribed"
MATCH_DEVIATED = "deviated"
MATCH_UNREADABLE = "unreadable"

# ── Thresholds (every one is a window or an n, never a verdict) ───────────────
MIN_SESSIONS = 3  # two deltas is the floor for any personal noise scale
NOISE_K = 1.0  # a move must clear 1 SD of the lift's own session deltas
RPE_NOISE_K = 1.0  # same treatment for the self-reported series
LOAD_TOLERANCE_KG = 0.05  # float-compare guard only; Hevy stores kg to 2dp
E1RM_EPSILON_LB = 0.1  # ditto, on the derived series

_WARMUP_TYPES = {"warmup", "warm_up", "warm-up"}


@dataclass
class SessionPoint:
    """One session of ONE movement, carrying its own prescription.

    ``load_kg``/``reps``/``rpe`` are what was performed on the top working set.
    ``prescribed_load_kg``/``prescribed_reps`` are what the routine IR pushed for
    that day asked for. Both prescription fields ``None`` means there was no plan
    on file to diff against — which is itself a reason the detector may not call a
    stall, never a licence to fall back on performed data alone.
    """

    date: str
    load_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None
    prescribed_load_kg: float | None = None
    prescribed_reps: int | None = None

    def match(self) -> str:
        """as_prescribed | deviated | unreadable — the per-session diff verdict."""
        if self.prescribed_load_kg is None or self.prescribed_reps is None:
            return MATCH_UNREADABLE
        if self.load_kg is None or self.reps is None:
            return MATCH_UNREADABLE
        load_same = abs(float(self.load_kg) - float(self.prescribed_load_kg)) <= LOAD_TOLERANCE_KG
        reps_same = int(self.reps) == int(self.prescribed_reps)
        return MATCH_AS_PRESCRIBED if (load_same and reps_same) else MATCH_DEVIATED


# ── Small numeric helpers (kept local so the module stays import-light) ───────


def _num(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _stdev(values: list[float]) -> float | None:
    """Population SD. None below two observations — a spread needs a spread."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def _e1rm_lb(load_kg: float | None, reps: int | None) -> float | None:
    """Epley estimated 1RM in POUNDS.

    Delegated to ``coach.coach_event_triggers.e1rm_lb`` — the fleet already has ONE
    Epley with one rep gate (1–12), shared by the phone coach and the site's strength
    surface, and a second copy here is exactly how two surfaces start telling two
    truths about the same lift. Imported lazily so this module keeps a pure, cheap
    import for the gates and for tests.
    """
    from coach.coach_event_triggers import e1rm_lb

    return e1rm_lb(load_kg, reps)


def top_working_set(sets: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The heaviest non-warm-up set of a Hevy exercise block.

    Wire shape (raw ``/v1/workouts`` item): ``{"type": "normal"|"warmup", "weight_kg":
    float, "reps": int, "rpe": float|None}``. The normalized DDB record renames
    ``type`` → ``set_type``, so both spellings are read — a reader that knew only one
    of them would silently grade warm-ups as working sets on half the corpus.

    Returns ``{"weight_kg", "reps", "rpe"}`` with None values when nothing qualifies.
    """
    best: dict[str, Any] = {"weight_kg": None, "reps": None, "rpe": None}
    best_w: float | None = None
    for s in sets or []:
        if not isinstance(s, dict):
            continue
        stype = str(s.get("type") or s.get("set_type") or "normal").strip().lower()
        if stype in _WARMUP_TYPES:
            continue
        w = _num(s.get("weight_kg"))
        r = _num(s.get("reps"))
        if w is None or r is None:
            continue
        if best_w is None or w > best_w:
            best_w = w
            best = {"weight_kg": w, "reps": int(r), "rpe": _num(s.get("rpe"))}
    return best


def diff_prescribed_vs_performed(
    ir: Any,
    performed_sets_by_template: dict[str, list[dict[str, Any]]],
    template_for: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-movement prescribed-vs-performed diff for ONE session.

    ``ir`` is the ``RoutineSpec`` that was pushed. ``performed_sets_by_template`` is
    that day's performed sets already grouped by Hevy template id, and
    ``template_for`` maps ``movement_key`` → template id. BOTH are passed in rather
    than derived here, for two different reasons: template resolution is I/O (catalog
    + template cache), and reading the Hevy wire key is the compiler-isolation gate's
    single-file concern (`tests/test_hevy_compiler_isolation.py`) — the grouping is
    done once, at the call site the ledger names. What is left here is pure logic, so
    every branch is directly fixture-testable.

    Returns ``{movement_key: {template_id, prescribed_load_kg, prescribed_reps,
    performed_load_kg, performed_reps, performed_rpe, match}}``. A movement the
    routine prescribed and he never performed is reported with performed values None
    and ``match: "unreadable"`` — absence is absence, never compliance (ADR-104).
    """
    tmap = dict(template_for or {})
    performed_by_tid = {str(k): (v or []) for k, v in (performed_sets_by_template or {}).items()}

    out: dict[str, dict[str, Any]] = {}
    for block in getattr(ir, "exercises", []) or []:
        key = getattr(block, "movement_key", "") or ""
        tid = tmap.get(key) or (key[len("tmpl:") :] if key.startswith("tmpl:") else None)
        prescribed = top_working_set(
            [
                {"type": getattr(s, "type", "normal"), "weight_kg": getattr(s, "weight_kg", None), "reps": getattr(s, "reps", None)}
                for s in (getattr(block, "sets", []) or [])
            ]
        )
        did = top_working_set(performed_by_tid.get(str(tid), [])) if tid else {"weight_kg": None, "reps": None, "rpe": None}
        row = {
            "template_id": tid,
            "prescribed_load_kg": prescribed["weight_kg"],
            "prescribed_reps": prescribed["reps"],
            "performed_load_kg": did["weight_kg"],
            "performed_reps": did["reps"],
            "performed_rpe": did["rpe"],
        }
        row["match"] = SessionPoint(
            date=str(getattr(ir, "target_date", "") or ""),
            load_kg=did["weight_kg"],
            reps=did["reps"],
            rpe=did["rpe"],
            prescribed_load_kg=prescribed["weight_kg"],
            prescribed_reps=prescribed["reps"],
        ).match()
        out[key] = row
    return out


def session_point_from_diff(date: str, row: dict[str, Any]) -> SessionPoint:
    """Lift one ``diff_prescribed_vs_performed`` row into a detector input."""
    return SessionPoint(
        date=date,
        load_kg=row.get("performed_load_kg"),
        reps=row.get("performed_reps"),
        rpe=row.get("performed_rpe"),
        prescribed_load_kg=row.get("prescribed_load_kg"),
        prescribed_reps=row.get("prescribed_reps"),
    )


def _rpe_block(points: list[SessionPoint]) -> dict[str, Any] | None:
    """The self-reported series, or None when it cannot be read as a trend.

    Every field is labelled at birth: this block is the only place RPE enters the
    verdict, and it carries its own ``basis`` so a caller that renders the block
    alone still ships the label.
    """
    rpes = [(p.date, _num(p.rpe)) for p in points if _num(p.rpe) is not None]
    if len(rpes) < 2:
        return None
    values = [float(v) for _, v in rpes if v is not None]
    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    band = _stdev(deltas)
    net = values[-1] - values[0]
    if band is None:
        direction = "unreadable"
    elif net > band:
        direction = "rising"
    elif net < -band:
        direction = "falling"
    else:
        direction = "flat"
    return {
        "basis": BASIS_SELF_REPORTED_RPE,
        "n_sessions_with_rpe": len(values),
        "first": values[0],
        "last": values[-1],
        "net_delta": round(net, 2),
        "noise_band": round(band, 2) if band is not None else None,
        "direction": direction,
        "note": "RPE is Matthew's own rating of the set, not a measurement.",
    }


def _prescription_summary(points: list[SessionPoint]) -> dict[str, Any]:
    matches = [p.match() for p in points]
    readable = [p for p in points if p.match() != MATCH_UNREADABLE]
    prescriptions = {(round(float(p.prescribed_load_kg or 0), 2), int(p.prescribed_reps or 0)) for p in readable}
    performed = {(round(float(p.load_kg or 0), 2), int(p.reps or 0)) for p in readable}
    return {
        "sessions_compared": len(points),
        "as_prescribed": matches.count(MATCH_AS_PRESCRIBED),
        "deviated": matches.count(MATCH_DEVIATED),
        "unreadable": matches.count(MATCH_UNREADABLE),
        "prescription_varied": len(prescriptions) > 1,
        "performed_varied": len(performed) > 1,
        "per_session": [{"date": p.date, "match": m} for p, m in zip(points, matches)],
    }


def _fixed_prescription_label(points: list[SessionPoint]) -> str:
    p = next((q for q in points if q.match() != MATCH_UNREADABLE), None)
    if p is None:
        return "an unreadable prescription"
    return f"{round(float(p.prescribed_load_kg or 0), 2)} kg × {int(p.prescribed_reps or 0)}"


def assess_stall(
    points: Iterable[SessionPoint],
    *,
    movement_key: str = "",
    min_sessions: int = MIN_SESSIONS,
    noise_k: float = NOISE_K,
) -> dict[str, Any]:
    """Call — or refuse to call — a stall on ONE movement.

    ``points`` are that movement's sessions OLDEST FIRST, each carrying its own
    prescription (that is the prescribed-vs-performed diff, and it is required
    input). Returns a verdict dict; see the module docstring for the four values
    and what each one means.
    """
    pts = list(points)
    presc = _prescription_summary(pts)
    rpe = _rpe_block(pts)
    e1rms = [(p, _e1rm_lb(p.load_kg, p.reps)) for p in pts]
    series = [{"date": p.date, "load_kg": p.load_kg, "reps": p.reps, "e1rm_lb": (round(v, 1) if v is not None else None)} for p, v in e1rms]

    def _out(verdict: str, reason: str, *, used_rpe: bool = False, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "movement_key": movement_key,
            "verdict": verdict,
            # The label travels ON the verdict, not in prose: a renderer cannot keep
            # the number and drop the provenance (#3928 acceptance 2).
            "basis": BASIS_SELF_REPORTED_RPE if used_rpe else BASIS_MEASURED,
            "signals_used": ["load", "reps"] + (["rpe"] if used_rpe else []),
            "n_sessions": len(pts),
            "reason": reason,
            "prescribed_vs_performed": presc,
            "e1rm_lb_series": series,
        }
        if rpe is not None:
            result["rpe"] = rpe
        result.update(extra or {})
        return result

    # 1. Not enough sessions for any trend claim, in either direction.
    if len(pts) < min_sessions:
        return _out(VERDICT_UNKNOWN, f"{len(pts)} session(s) — below the {min_sessions}-session floor for a trend claim.")

    # 2. No prescription on file at all. This is the exact state the owner's ruling
    #    names: without the diff there is nothing but performed data, so no stall.
    if presc["unreadable"] == len(pts):
        return _out(
            VERDICT_UNKNOWN,
            "No prescribed load × reps on file for any session in this window — a stall cannot be "
            "called from performed data alone (#3928). Open the routine IR for these dates first.",
        )

    # 3. He did exactly what the platform prescribed, and the prescription never moved.
    #    e1RM is constant BY CONSTRUCTION here; the series is the prescription read back.
    if presc["deviated"] == 0 and presc["unreadable"] == 0 and not presc["prescription_varied"]:
        label = _fixed_prescription_label(pts)
        reason = (
            f"Every one of these {len(pts)} sessions was performed exactly as prescribed, at a fixed "
            f"{label}. At fixed load × fixed reps e1RM is constant by construction, so this window "
            f"carries no stall signal — the series is the prescription read back."
        )
        if rpe is not None:
            reason += (
                f" The only residual signal is self-reported RPE, which went {rpe['first']} → {rpe['last']} "
                f"({rpe['direction']}); it is his own rating, and it does not license a stall verdict."
            )
            return _out(VERDICT_UNKNOWN, reason, used_rpe=True)
        return _out(VERDICT_UNKNOWN, reason)

    # 4. There is room to read the performed series: either the prescription moved, or
    #    he did something other than what it said.
    usable = [(p, v) for p, v in e1rms if v is not None]
    if len(usable) < min_sessions:
        return _out(
            VERDICT_UNKNOWN,
            f"Only {len(usable)} of {len(pts)} sessions yield an estimated 1RM (Epley is gated to 1–12 reps; "
            "bodyweight and long rep-out sets are excluded) — below the floor for a trend claim.",
        )

    values = [float(v) for _, v in usable]
    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    band_sd = _stdev(deltas)
    band = noise_k * band_sd if band_sd is not None else 0.0
    net = values[-1] - values[0]

    if net > band + E1RM_EPSILON_LB:
        return _out(
            VERDICT_PROGRESSING,
            f"Estimated 1RM rose {round(net, 1)} lb across {len(usable)} sessions, clearing this lift's own "
            f"±{round(band, 1)} lb session-to-session noise band.",
        )
    if net < -(band + E1RM_EPSILON_LB):
        return _out(
            VERDICT_REGRESSING,
            f"Estimated 1RM fell {round(abs(net), 1)} lb across {len(usable)} sessions, clearing this lift's own "
            f"±{round(band, 1)} lb session-to-session noise band.",
        )

    # Flat. Whether that is a STALL depends entirely on what was ASKED for.
    readable = [p for p in pts if p.match() != MATCH_UNREADABLE]
    asked_more = False
    if readable:
        first_ask, last_ask = readable[0], readable[-1]
        asked_more = float(last_ask.prescribed_load_kg or 0) > float(first_ask.prescribed_load_kg or 0) + LOAD_TOLERANCE_KG or int(
            last_ask.prescribed_reps or 0
        ) > int(first_ask.prescribed_reps or 0)

    if readable and presc["prescription_varied"] and asked_more:
        first_ask, last_ask = readable[0], readable[-1]
        reason = (
            f"The prescription climbed from {round(float(first_ask.prescribed_load_kg or 0), 2)} kg × "
            f"{int(first_ask.prescribed_reps or 0)} to {round(float(last_ask.prescribed_load_kg or 0), 2)} kg × "
            f"{int(last_ask.prescribed_reps or 0)}, and the performed estimated 1RM did not follow — net "
            f"{round(net, 1)} lb across {len(usable)} sessions, inside its own ±{round(band, 1)} lb noise band."
        )
        if rpe is not None and rpe["direction"] == "rising":
            reason += (
                f" Self-reported RPE rose {rpe['first']} → {rpe['last']} over the same window, which corroborates "
                "the call — and is his own rating, not a measurement."
            )
            return _out(VERDICT_STALL, reason, used_rpe=True)
        return _out(VERDICT_STALL, reason)

    return _out(
        VERDICT_UNKNOWN,
        f"Estimated 1RM is flat (net {round(net, 1)} lb, inside its own ±{round(band, 1)} lb noise band), but the "
        f"prescription never asked for more across this window ({presc['deviated']} of {len(pts)} sessions deviated "
        "from it). A flat series under a prescription that did not climb is not a stall — it is the plan being held.",
    )
