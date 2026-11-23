"""lambdas/experiment/lift_outcomes.py — training outcomes a pre-registered experiment can name (#6209).

``experiment_design.DESIGN_METRICS`` resolves every criterion slug to a stored daily field. Training has no such field:
the effort and strength of a session live in the logged sets of the ``hevy`` partition (rows
``DATE#<day>#WORKOUT#<id>``, ``exercises[].sets[]`` with ``type`` / ``weight_kg`` / ``reps`` / ``rpe``). This module derives
three per-session series from those sets, deterministically, and keeps the raw observations beside them.

The three metrics (the registry entries in ``LIFT_METRICS`` are the documentation of record):

* ``lift_session_rpe`` — the mean RPE of the session's ``normal`` loaded sets. Raw self-report; a session with fewer than
  ``MIN_RATED_SETS`` rated sets has no value.
* ``lift_e1rm_index`` — for each exercise, the session's best ``normal`` set as an Epley e1RM ``w * (1 + reps / 30)``,
  as a percent of that exercise's reference: its mean session-best over the BASELINE window. An exercise has a reference
  when it has ``MIN_BASELINE_SESSIONS`` baseline sessions — nothing else decides it. A session's value is the mean over
  the referenced exercises it contains (at least ``MIN_EXERCISES``), so the two arms can differ in exercise mix; each
  arm's mix is recorded. **It confounds programmed load with performance**: when the programme raises the prescribed
  weight, this index rises whether or not he got stronger.
* ``lift_effort_adjusted_e1rm_index`` — the same, on rated sets only, with the reps left in reserve added back:
  ``w * (1 + (reps + (10 - rpe)) / 30)``. **It depends on self-reported effort** — a drifting RPE scale moves it.

THE BASELINE IS A SNAPSHOT, NOT A RE-READ (owner condition, 2026-11-23). ``capture_baseline`` reads the baseline window
once and returns an immutable record: every exercise by KEY (template id, else ``name:<lowercased title>``) with its
display name, template id, references, session counts and the source rows behind them (workout, date, best set), plus
each metric's baseline-arm day values and session records, ``captured_at``, the window and the engine version. The
caller stores it write-once on the experiment row. ``derive`` then takes the baseline arm and every reference FROM THE
SNAPSHOT and computes only the other days from rows — so a baseline row edited, backfilled or tombstoned after capture
moves nothing, and a later session never changes a baseline value. Without a snapshot ``derive`` computes no value at
all (state ``no_baseline_snapshot``); it never recomputes a reference.

Identity is never guessed: a session logged without a template id is ``name:<title>``, a different key from the same
movement logged with one, and the analysis reports that mismatch under exclusions instead of merging them.

A day with no session is ABSENT from the series, never 0. Two sessions on one day: the day value is the mean of the
session values (the observations still count sessions). Pure — stdlib + ``common.hevy_schema`` only; the caller owns the
read and the write.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Iterable

from common.hevy_schema import is_warmup_set, set_number, set_type_of

ENGINE = "lift-outcomes-v2"
LIFT_SOURCE = "hevy"
LIFT_SESSION_RPE = "lift_session_rpe"
LIFT_E1RM_INDEX = "lift_e1rm_index"
LIFT_EFFORT_E1RM_INDEX = "lift_effort_adjusted_e1rm_index"
NO_BASELINE_SNAPSHOT = "no_baseline_snapshot"

MIN_RATED_SETS = 3  # lift_session_rpe: fewer rated sets than this and the session has no value
MIN_EXERCISES = 2  # an index session needs this many referenced exercises
MIN_BASELINE_SESSIONS = 2  # an exercise needs this many baseline sessions to carry a reference
MIN_BASELINE_VALUED = 5  # = experiment_design.MIN_POINTS_PER_ARM (a test pins the two equal; no import — that module imports this)
RPE_FLOOR, RPE_CEILING = 1.0, 10.0  # a rating outside the scale is treated as unrated

_MIX = (
    " The two arms can differ in exercise mix: a session is valued over whichever referenced exercises it contains, and "
    "each arm's mix is recorded."
)

#: The registry entry for each derived metric — label, unit, the exact definition, and what it cannot tell apart.
LIFT_METRICS: dict[str, dict[str, str]] = {
    LIFT_SESSION_RPE: {
        "label": "Lifting session RPE",
        "unit": "RPE (1-10)",
        "definition": (
            f"Mean RPE of the session's sets with type 'normal', weight_kg > 0 and reps > 0 that carry a rating; "
            f"no value when fewer than {MIN_RATED_SETS} such sets are rated."
        ),
        "caveat": "Raw self-report: it measures how hard the sessions felt, not what was lifted.",
    },
    LIFT_E1RM_INDEX: {
        "label": "Lifting e1RM index (% of baseline)",
        "unit": "% of baseline",
        "definition": (
            "Per exercise, the session's best 'normal' set as Epley e1RM weight_kg * (1 + reps / 30), as a percent of that "
            "exercise's reference — its mean session-best over the baseline window, frozen in a snapshot at capture; an "
            f"exercise has a reference when it has at least {MIN_BASELINE_SESSIONS} baseline sessions. The session value is "
            f"the mean over the referenced exercises it contains (at least {MIN_EXERCISES})." + _MIX
        ),
        "caveat": (
            "Logged performance: it confounds programmed load with performance — it rises when the programme prescribes "
            "more weight, whether or not the lifter got stronger."
        ),
    },
    LIFT_EFFORT_E1RM_INDEX: {
        "label": "Lifting effort-adjusted e1RM index (% of baseline)",
        "unit": "% of baseline",
        "definition": (
            "As the e1RM index, on rated sets only, with reps in reserve added from the rating: "
            "weight_kg * (1 + (reps + (10 - rpe)) / 30)." + _MIX
        ),
        "caveat": (
            "Separates 'the programme prescribed more' from 'the same work got easier or harder', but depends on "
            "self-reported effort: a drifting RPE scale moves it."
        ),
    },
}

INDEX_METRICS = (LIFT_E1RM_INDEX, LIFT_EFFORT_E1RM_INDEX)

Work = tuple[str, str, str, float, float, "float | None"]  # (key, display name, template id, weight_kg, reps, rpe)


def is_lift_metric(field: object) -> bool:
    """True when a DESIGN_METRICS field is one of the derived lift series (it names no stored attribute)."""
    return field in LIFT_METRICS


# ── reading the stored rows ──────────────────────────────────────────────────


def _session_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """The per-workout rows, oldest first, in a fixed order. A tombstoned (superseded) row and a legacy day aggregate
    (no ``#WORKOUT#`` in its sort key) are not sessions."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or r.get("tombstone"):
            continue
        sk = str(r.get("sk") or "")
        if "#WORKOUT#" not in sk or len(sk) < 15:
            continue
        out.append(r)
    return sorted(out, key=lambda r: (str(r.get("sk"))[5:15], str(r.get("start_time") or ""), str(r.get("sk"))))


def _day(row: dict[str, Any]) -> str:
    return str(row.get("sk"))[5:15]


def _workout_id(row: dict[str, Any]) -> str:
    return str(row.get("source_workout_id") or str(row.get("sk")).rsplit("#", 1)[-1])


def exercise_identity(ex: dict[str, Any]) -> tuple[str, str, str]:
    """(key, display name, template id). The Hevy template id IS the identity when present — a renamed movement keeps its
    key — else ``name:<lowercased title>``. The two forms never match each other: no identity is guessed."""
    name = str(ex.get("name") or ex.get("title") or "").strip()
    tid = str(ex.get("template_id") or "").strip()
    return (f"tid:{tid}" if tid else f"name:{name.lower()}"), name, tid


def _new_counts() -> dict[str, int]:
    return {"sets_total": 0, "sets_warmup": 0, "sets_other_type": 0, "sets_unloaded": 0, "sets_unrated": 0, "sets_rated": 0}


def _read_session(row: dict[str, Any]) -> tuple[list[Work], dict[str, int]]:
    """The session's working sets, and what was set aside.

    Kept: type 'normal', weight_kg > 0, reps > 0. Set aside and counted: warm-ups, every other type (dropset, failure, …),
    unloaded or rep-less sets (bodyweight, timed cardio, carries). A kept set with no rating — or one outside 1-10 — is
    counted unrated and carries rpe None."""
    counts = _new_counts()
    work: list[Work] = []
    for ex in row.get("exercises") or []:
        if not isinstance(ex, dict):
            continue
        key, name, tid = exercise_identity(ex)
        for s in ex.get("sets") or []:
            if not isinstance(s, dict):
                continue
            counts["sets_total"] += 1
            if is_warmup_set(s):
                counts["sets_warmup"] += 1
                continue
            if set_type_of(s) != "normal":
                counts["sets_other_type"] += 1
                continue
            w, reps = set_number(s.get("weight_kg")), set_number(s.get("reps"))
            if w <= 0 or reps <= 0:
                counts["sets_unloaded"] += 1
                continue
            rpe: float | None = set_number(s.get("rpe")) if s.get("rpe") not in (None, "") else None
            if rpe is None or not (RPE_FLOOR <= rpe <= RPE_CEILING):
                counts["sets_unrated"] += 1
                rpe = None
            else:
                counts["sets_rated"] += 1
            work.append((key, name, tid, w, reps, rpe))
    return work, counts


def _e1rm(metric: str, w: float, reps: float, rpe: float | None) -> float | None:
    if metric == LIFT_EFFORT_E1RM_INDEX:
        return None if rpe is None else w * (1 + (reps + (10 - rpe)) / 30)
    return w * (1 + reps / 30)


def _best_sets(work: list[Work], metric: str) -> dict[str, dict[str, Any]]:
    """exercise key → the session's best set under the metric's formula (first set wins a tie — rows are ordered)."""
    best: dict[str, dict[str, Any]] = {}
    for key, name, tid, w, reps, rpe in work:
        e = _e1rm(metric, w, reps, rpe)
        if e is None or (key in best and e <= best[key]["e1rm"]):
            continue
        best[key] = {
            "display_name": name,
            "template_id": tid or None,
            "best_set": {"weight_kg": round(w, 3), "reps": reps, "rpe": rpe},
            "e1rm": round(e, 4),
        }
    return best


def _prescription_flag(row: dict[str, Any]) -> dict[str, Any]:
    """The on-ingest prescribed-versus-performed readback the row already carries (``adherence``, #412), or absent.
    ``status`` is matched / ad_hoc / ambiguous; ``as_prescribed`` is the session verdict (yes / no / progressed / unknown)."""
    adh = row.get("adherence")
    if not isinstance(adh, dict):
        return {"adherence_status": None, "as_prescribed": None}
    ap = adh.get("as_prescribed")
    return {"adherence_status": adh.get("status"), "as_prescribed": ap.get("verdict") if isinstance(ap, dict) else None}


# ── one session ──────────────────────────────────────────────────────────────


def _session_record(row: dict[str, Any], metric: str, refs: dict[str, float] | None) -> tuple[dict[str, Any], dict[str, int]]:
    """The audit record of one session under one metric: its value (or why none), the keys used and the best set behind
    each, and the prescription flag. ``refs`` None means no snapshot — no value is computed."""
    work, counts = _read_session(row)
    rec: dict[str, Any] = {"date": _day(row), "sk": str(row.get("sk")), "workout_id": _workout_id(row)}
    value: float | None = None
    reason: str | None = None
    if metric == LIFT_SESSION_RPE:
        rated = [w[5] for w in work if w[5] is not None]
        rec["n_rated_sets"] = len(rated)
        if refs is None:
            reason = NO_BASELINE_SNAPSHOT
        elif len(rated) < MIN_RATED_SETS:
            reason = f"{len(rated)} rated sets (needs {MIN_RATED_SETS})"
        else:
            value = sum(r for r in rated if r is not None) / len(rated)
        rec["exercises"] = {}
        rec["keys_used"] = []
    else:
        best = _best_sets(work, metric)
        used = sorted(k for k in best if refs and k in refs)
        for k, b in best.items():
            b["used"] = k in used
            b["pct_of_reference"] = round(b["e1rm"] / refs[k] * 100, 4) if refs and k in refs else None
        rec["exercises"] = {k: best[k] for k in sorted(best)}
        rec["keys_used"] = used
        if refs is None:
            reason = NO_BASELINE_SNAPSHOT
        elif len(used) < MIN_EXERCISES:
            reason = f"{len(used)} referenced exercises (needs {MIN_EXERCISES})"
        else:
            value = sum(best[k]["pct_of_reference"] for k in used) / len(used)
    rec["value"] = round(value, 4) if value is not None else None
    rec["no_value_reason"] = reason
    rec.update(_prescription_flag(row))
    return rec, counts


def _arm(records: list[tuple[dict[str, Any], dict[str, int]]], lo: str, hi: str) -> dict[str, Any]:
    """One arm's raw observations: sessions read and valued, every set set aside, the exercise mix (key → sessions it
    was valued in), the prescription tally, and every session record."""
    counts = _new_counts()
    verdicts: dict[str, int] = {}
    mix: dict[str, int] = {}
    for rec, c in records:
        for k, v in c.items():
            counts[k] += v
        verdicts[str(rec["as_prescribed"])] = verdicts.get(str(rec["as_prescribed"]), 0) + 1
        if rec["value"] is not None:
            for k in rec["keys_used"]:
                mix[k] = mix.get(k, 0) + 1
    valued = [rec for rec, _c in records if rec["value"] is not None]
    return {
        "start": lo,
        "end": hi,
        "n_sessions": len(records),
        "n_sessions_valued": len(valued),
        "n_days_valued": len({rec["date"] for rec in valued}),
        **counts,
        "exercise_mix": dict(sorted(mix.items())),
        "as_prescribed_counts": dict(sorted(verdicts.items())),
        "sessions": [rec for rec, _c in records],
    }


def _day_values(records: list[tuple[dict[str, Any], dict[str, int]]]) -> dict[str, float]:
    by_day: dict[str, list[float]] = {}
    for rec, _c in records:
        if rec["value"] is not None:
            by_day.setdefault(rec["date"], []).append(rec["value"])
    return {d: round(sum(v) / len(v), 2) for d, v in sorted(by_day.items())}


# ── the snapshot ─────────────────────────────────────────────────────────────


def capture_baseline(rows: Iterable[Any], window_start: str, window_end: str, *, start_date: str, captured_at: str, today: str) -> dict:
    """The immutable baseline snapshot for ALL three metrics, from the rows of [window_start, window_end] as they stand
    now. ``captured_after_start`` / ``capture_lag_days`` say honestly when it was taken later than the start."""
    sessions = [r for r in _session_rows(rows) if window_start <= _day(r) <= window_end]
    exercises: dict[str, dict[str, Any]] = {}
    for metric in INDEX_METRICS:
        for row in sessions:
            work, _c = _read_session(row)
            for key, b in _best_sets(work, metric).items():
                ex = exercises.setdefault(
                    key,
                    {
                        "display_name": b["display_name"],
                        "template_id": b["template_id"],
                        "references": {},
                        "n_sessions": {},
                        "source_rows": {},
                    },
                )
                ex["source_rows"].setdefault(metric, []).append(
                    {
                        "date": _day(row),
                        "sk": str(row.get("sk")),
                        "workout_id": _workout_id(row),
                        "best_set": b["best_set"],
                        "e1rm": b["e1rm"],
                    }
                )
    for ex in exercises.values():
        for metric in INDEX_METRICS:
            src = ex["source_rows"].get(metric, [])
            ex["n_sessions"][metric] = len(src)
            ex["references"][metric] = round(sum(s["e1rm"] for s in src) / len(src), 4) if len(src) >= MIN_BASELINE_SESSIONS else None
    arms: dict[str, Any] = {}
    values: dict[str, dict[str, float]] = {}
    for metric in LIFT_METRICS:
        refs = _refs({"exercises": exercises}, metric)
        recs = [_session_record(r, metric, refs) for r in sessions]
        arms[metric] = _arm(recs, window_start, window_end)
        values[metric] = _day_values(recs)
    lag = (date.fromisoformat(today) - date.fromisoformat(start_date)).days
    return {
        "engine": ENGINE,
        "captured_at": captured_at,
        "window": {"start": window_start, "end": window_end},
        "start_date": start_date,
        "captured_after_start": lag > 0,
        "capture_lag_days": max(lag, 0),
        "exercises": {k: exercises[k] for k in sorted(exercises)},
        "baseline_values": values,
        "arms": arms,
    }


def _refs(snapshot: dict, metric: str) -> dict[str, float]:
    """key → reference for the metric (only exercises that earned one). The RPE metric has no references (empty)."""
    if metric not in INDEX_METRICS:
        return {}
    return {
        k: float(ex["references"][metric])
        for k, ex in (snapshot.get("exercises") or {}).items()
        if (ex.get("references") or {}).get(metric) is not None
    }


def snapshot_is_usable(snapshot: object) -> bool:
    return isinstance(snapshot, dict) and isinstance(snapshot.get("window"), dict) and isinstance(snapshot.get("baseline_values"), dict)


def _exclusions(snapshot: dict, metric: str, window_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every exercise that could not count, by KEY, with the reason — thin baseline, absent from the baseline, or an
    identity mismatch (the same title logged with a template id on one side and without on the other)."""
    out: dict[str, dict[str, Any]] = {}
    snap_ex = snapshot.get("exercises") or {}
    refs = _refs(snapshot, metric)
    for k, ex in snap_ex.items():
        if k not in refs:
            n = (ex.get("n_sessions") or {}).get(metric, 0)
            out[k] = {
                "display_name": ex.get("display_name"),
                "template_id": ex.get("template_id"),
                "reason": f"{n} baseline sessions (needs {MIN_BASELINE_SESSIONS})",
            }
    by_name: dict[str, list[str]] = {}
    for k, ex in snap_ex.items():
        by_name.setdefault(str(ex.get("display_name") or "").lower(), []).append(k)
    for rec in window_records:
        for k, b in rec["exercises"].items():
            if k in snap_ex or k in out:
                continue
            twins = [t for t in by_name.get(str(b["display_name"]).lower(), []) if t != k]
            reason = (
                f"no baseline reference under this identity; the baseline logged the same title as {twins[0]} — "
                "a template id present on one side and missing on the other is never matched by name"
                if twins
                else "not in the baseline window"
            )
            out[k] = {"display_name": b["display_name"], "template_id": b["template_id"], "reason": reason}
    return {k: out[k] for k in sorted(out)}


def derive(metric: str, rows: Iterable[Any], windows: dict[str, str], snapshot: dict | None = None) -> dict[str, Any]:
    """Derive one lift metric. The baseline arm and every reference come from ``snapshot``; only days outside its
    window are computed from ``rows``. Without a usable snapshot no value is computed (state ``no_baseline_snapshot``).

    Returns ``{"values": {day: value}, "observations": {...}}``; a day without a valued session is absent."""
    if metric not in LIFT_METRICS:
        raise ValueError(f"not a lift metric: {metric!r}")
    obs: dict[str, Any] = {"metric": metric, "definition": LIFT_METRICS[metric]["definition"], "caveat": LIFT_METRICS[metric]["caveat"]}
    rows_s = _session_rows(rows)
    if not snapshot_is_usable(snapshot):
        recs = [_session_record(r, metric, None) for r in rows_s]
        obs.update(
            {
                "state": NO_BASELINE_SNAPSHOT,
                "reference_e1rm_kg": {},
                "exercises_used": [],
                "exercises_excluded": {},
                "arms": {
                    "baseline": _arm(
                        [x for x in recs if windows["baseline_start"] <= x[0]["date"] <= windows["baseline_end"]],
                        windows["baseline_start"],
                        windows["baseline_end"],
                    ),
                    "analysis": _arm(
                        [x for x in recs if windows["analysis_start"] <= x[0]["date"] <= windows["analysis_end"]],
                        windows["analysis_start"],
                        windows["analysis_end"],
                    ),
                },
            }
        )
        return {"values": {}, "observations": obs}
    assert snapshot is not None
    ws, we = snapshot["window"]["start"], snapshot["window"]["end"]
    refs = _refs(snapshot, metric)
    later = [_session_record(r, metric, refs) for r in rows_s if not (ws <= _day(r) <= we)]
    values = {**{d: float(v) for d, v in (snapshot["baseline_values"].get(metric) or {}).items()}, **_day_values(later)}
    window_recs = [x for x in later if windows["analysis_start"] <= x[0]["date"] <= windows["analysis_end"]]
    snap_ex = snapshot.get("exercises") or {}
    obs.update(
        {
            "state": "ok",
            "snapshot": {k: snapshot.get(k) for k in ("engine", "captured_at", "window", "captured_after_start", "capture_lag_days")},
            "reference_e1rm_kg": {
                k: {
                    "display_name": snap_ex[k].get("display_name"),
                    "template_id": snap_ex[k].get("template_id"),
                    "reference": refs[k],
                    "n_sessions": (snap_ex[k].get("n_sessions") or {}).get(metric),
                }
                for k in sorted(refs)
            },
            "exercises_used": sorted(refs),
            "exercises_excluded": _exclusions(snapshot, metric, [x[0] for x in window_recs]) if metric in INDEX_METRICS else {},
            "arms": {
                "baseline": (snapshot.get("arms") or {}).get(metric),
                "analysis": _arm(window_recs, windows["analysis_start"], windows["analysis_end"]),
            },
        }
    )
    return {"values": dict(sorted(values.items())), "observations": obs}


# ── the close path's seam (the caller injects its read; this module never does I/O) ──

Query = Callable[[str, str, str], list[Any]]


def read_series(
    query: Query, source: str, metric: str, windows: dict[str, str], start: str, end: str, snapshot: dict | None
) -> dict[str, float]:
    """day → value over [start, end]: baseline-window days from the snapshot, every other day from rows against the
    snapshot's references."""
    return {d: v for d, v in derive(metric, query(source, start, end), windows, snapshot)["values"].items() if start <= d <= end}


def attach_observations(
    stats: dict[str, Any], query: Query, source: str, metric: str, windows: dict[str, str], snapshot: dict | None
) -> dict[str, Any]:
    """Put the raw observations of a lift criterion on the analysis stats (no-op for any other metric). Returns ``stats``."""
    if is_lift_metric(metric):
        rows = query(source, windows["analysis_start"], windows["analysis_end"])
        stats["observations"] = derive(metric, rows, windows, snapshot)["observations"]
    return stats


def baseline_note(snapshot: dict | None, metric: str, start_date: str) -> str | None:
    """#6209 (d): the advisory a creation returns — never a refusal."""
    if not snapshot_is_usable(snapshot):
        return (
            f"Baseline not captured yet: the start {start_date} is in the future, so the baseline window is incomplete. It is "
            "captured write-once at the first analysis read on or after the start, and marked captured_after_start."
        )
    assert snapshot is not None
    n = len(snapshot["baseline_values"].get(metric) or {})
    if n < MIN_BASELINE_VALUED:
        return (
            f"Only {n} baseline days with a {metric} value (the analysis needs {MIN_BASELINE_VALUED}): as registered, the "
            "verdict will be inconclusive by construction."
        )
    return None
