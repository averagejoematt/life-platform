"""lambdas/experiment/lift_outcomes.py — training outcomes a pre-registered experiment can name (#6209).

``experiment_design.DESIGN_METRICS`` resolves every criterion slug to a stored daily field. Training has no such field:
the effort and strength of a session live in the logged sets of the ``hevy`` partition (rows
``DATE#<day>#WORKOUT#<id>``, ``exercises[].sets[]`` with ``type`` / ``weight_kg`` / ``reps`` / ``rpe``). This module derives
three per-session series from those sets, deterministically, and keeps the raw observations beside them.

The three metrics (the registry entries in ``LIFT_METRICS`` are the documentation of record):

* ``lift_session_rpe`` — the mean RPE of the session's ``normal`` loaded sets. Raw self-report; a session with fewer than
  ``MIN_RATED_SETS`` rated sets has no value.
* ``lift_e1rm_index`` — for each exercise, the session's best ``normal`` set as an Epley e1RM ``w * (1 + reps / 30)``,
  as a percent of that exercise's mean session-best over the BASELINE window. The session value is the mean over the
  exercises present in both windows (``MIN_EXERCISES`` of them, each with ``MIN_BASELINE_SESSIONS`` baseline sessions).
  **It confounds programmed load with performance**: when the programme raises the prescribed weight, this index rises
  whether or not he got stronger.
* ``lift_effort_adjusted_e1rm_index`` — the same, on rated sets only, with the reps left in reserve added back:
  ``w * (1 + (reps + (10 - rpe)) / 30)``. A heavier prescription done at a higher RPE moves it less than the raw index;
  the same work at a lower RPE moves it up. **It depends on self-reported effort** — a drifting RPE scale moves it.

The index is relative to the baseline window, so the reference means are computed ONLY from the baseline window that
``experiment_design.design_windows`` derives from the frozen ``start_date`` and ``baseline_days`` — the close date never
moves it, and later sessions never feed it. The baseline arm therefore averages about 100.

A day with no session is ABSENT from the series, never 0. Two sessions on one day: the day value is the mean of the
session values (the observations still count sessions). Pure — stdlib + ``common.hevy_schema`` only; the caller owns the
read.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from common.hevy_schema import is_warmup_set, set_number, set_type_of

LIFT_SOURCE = "hevy"
LIFT_SESSION_RPE = "lift_session_rpe"
LIFT_E1RM_INDEX = "lift_e1rm_index"
LIFT_EFFORT_E1RM_INDEX = "lift_effort_adjusted_e1rm_index"

MIN_RATED_SETS = 3  # lift_session_rpe: fewer rated sets than this and the session has no value
MIN_EXERCISES = 2  # an index session needs this many eligible exercises
MIN_BASELINE_SESSIONS = 2  # an exercise needs this many baseline sessions to carry a reference
RPE_FLOOR, RPE_CEILING = 1.0, 10.0  # a rating outside the scale is treated as unrated

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
            "exercise's mean session-best over the frozen baseline window; the session value is the mean over the exercises "
            f"present in both windows (at least {MIN_EXERCISES}, each with at least {MIN_BASELINE_SESSIONS} baseline sessions)."
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
            "weight_kg * (1 + (reps + (10 - rpe)) / 30)."
        ),
        "caveat": (
            "Separates 'the programme prescribed more' from 'the same work got easier or harder', but depends on "
            "self-reported effort: a drifting RPE scale moves it."
        ),
    },
}

_INDEX_METRICS = (LIFT_E1RM_INDEX, LIFT_EFFORT_E1RM_INDEX)


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


def _exercise_key(ex: dict[str, Any]) -> tuple[str, str]:
    """(key, display name). The Hevy template id is the identity when present — two titles for one movement are one
    exercise — else the lowercased title."""
    name = str(ex.get("name") or ex.get("title") or "").strip()
    tid = str(ex.get("template_id") or "").strip()
    return (f"tid:{tid}" if tid else f"name:{name.lower()}"), name


def _new_counts() -> dict[str, int]:
    return {"sets_total": 0, "sets_warmup": 0, "sets_other_type": 0, "sets_unloaded": 0, "sets_unrated": 0, "sets_rated": 0}


def _read_session(row: dict[str, Any]) -> tuple[list[tuple[str, str, float, float, float | None]], dict[str, int]]:
    """The session's working sets as (exercise key, name, weight_kg, reps, rpe or None), and what was set aside.

    Kept: type 'normal', weight_kg > 0, reps > 0. Set aside and counted: warm-ups, every other type (dropset, failure, …),
    unloaded or rep-less sets (bodyweight, timed cardio, carries). A kept set with no rating — or one outside 1-10 — is
    counted unrated and carries rpe None."""
    counts = _new_counts()
    work: list[tuple[str, str, float, float, float | None]] = []
    for ex in row.get("exercises") or []:
        if not isinstance(ex, dict):
            continue
        key, name = _exercise_key(ex)
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
            work.append((key, name, w, reps, rpe))
    return work, counts


def _best_by_exercise(work: list[tuple[str, str, float, float, float | None]], metric: str) -> dict[str, float]:
    """exercise key → the session's best e1RM under the metric's formula (rated sets only for the effort-adjusted one)."""
    best: dict[str, float] = {}
    for key, _name, w, reps, rpe in work:
        if metric == LIFT_EFFORT_E1RM_INDEX:
            if rpe is None:
                continue
            e1rm = w * (1 + (reps + (10 - rpe)) / 30)
        else:
            e1rm = w * (1 + reps / 30)
        if e1rm > best.get(key, 0.0):
            best[key] = e1rm
    return best


def _prescription_flag(row: dict[str, Any]) -> dict[str, Any]:
    """The on-ingest prescribed-versus-performed readback the row already carries (``adherence``, #412), or absent.
    ``status`` is matched / ad_hoc / ambiguous; ``as_prescribed`` is the session verdict (yes / no / progressed / unknown)."""
    adh = row.get("adherence")
    if not isinstance(adh, dict):
        return {"adherence_status": None, "as_prescribed": None}
    ap = adh.get("as_prescribed")
    return {"adherence_status": adh.get("status"), "as_prescribed": ap.get("verdict") if isinstance(ap, dict) else None}


# ── the derivation ───────────────────────────────────────────────────────────


def _in(day: str, lo: str, hi: str) -> bool:
    return lo <= day <= hi


def _references(sessions: list[dict[str, Any]], windows: dict[str, str]) -> tuple[dict[str, float], dict[str, Any]]:
    """The frozen per-exercise reference (mean baseline session-best) for the eligible exercises, and the exclusions.

    Eligible: at least MIN_BASELINE_SESSIONS baseline sessions AND at least one analysis-window session. Only baseline-window
    sessions feed a reference; nothing after the start does."""
    base_bests: dict[str, list[float]] = {}
    in_window: set[str] = set()
    names: dict[str, str] = {}
    for s in sessions:
        day = s["day"]
        for key, val in s["best"].items():
            names.setdefault(key, s["names"][key])
            if _in(day, windows["baseline_start"], windows["baseline_end"]):
                base_bests.setdefault(key, []).append(val)
            elif _in(day, windows["analysis_start"], windows["analysis_end"]):
                in_window.add(key)
    refs: dict[str, float] = {}
    excluded: dict[str, str] = {}
    for key in sorted(set(base_bests) | in_window):
        n_base = len(base_bests.get(key, []))
        if n_base == 0:
            excluded[names[key]] = "analysis window only"
        elif key not in in_window:
            excluded[names[key]] = "baseline window only"
        elif n_base < MIN_BASELINE_SESSIONS:
            excluded[names[key]] = f"{n_base} baseline session (needs {MIN_BASELINE_SESSIONS})"
        else:
            refs[key] = sum(base_bests[key]) / n_base
    return refs, {"excluded": excluded, "names": names}


def derive(metric: str, rows: Iterable[Any], windows: dict[str, str]) -> dict[str, Any]:
    """Derive one lift metric over every session in ``rows``.

    ``windows`` is ``experiment_design.design_windows(...)`` — the index reference reads ONLY its baseline window.
    Returns ``{"values": {day: value}, "sessions": [...], "observations": {...}}``; a day without a valued session is
    absent from ``values``."""
    if metric not in LIFT_METRICS:
        raise ValueError(f"not a lift metric: {metric!r}")
    sessions = []
    for row in _session_rows(rows):
        work, counts = _read_session(row)
        best = _best_by_exercise(work, metric)
        names = {key: name for key, name, *_rest in work}
        sessions.append({"row": row, "day": _day(row), "work": work, "counts": counts, "best": best, "names": names})

    refs: dict[str, float] = {}
    exclusions: dict[str, Any] = {"excluded": {}, "names": {}}
    if metric in _INDEX_METRICS:
        refs, exclusions = _references(sessions, windows)

    for s in sessions:
        s["value"], s["reason"] = _session_value(metric, s, refs)

    by_day: dict[str, list[float]] = {}
    for s in sessions:
        if s["value"] is not None:
            by_day.setdefault(s["day"], []).append(s["value"])
    values = {day: round(sum(v) / len(v), 2) for day, v in sorted(by_day.items())}

    obs: dict[str, Any] = {
        "metric": metric,
        "definition": LIFT_METRICS[metric]["definition"],
        "caveat": LIFT_METRICS[metric]["caveat"],
        "arms": {
            "baseline": _arm(sessions, windows["baseline_start"], windows["baseline_end"]),
            "analysis": _arm(sessions, windows["analysis_start"], windows["analysis_end"]),
        },
    }
    if metric in _INDEX_METRICS:
        names = exclusions["names"]
        obs["exercises_used"] = sorted(names[k] for k in refs)
        obs["exercises_excluded"] = exclusions["excluded"]
        obs["reference_e1rm_kg"] = {names[k]: round(v, 2) for k, v in sorted(refs.items(), key=lambda kv: names[kv[0]])}
        obs["reference_window"] = {"start": windows["baseline_start"], "end": windows["baseline_end"]}
    return {"values": values, "sessions": sessions, "observations": obs}


def _session_value(metric: str, s: dict[str, Any], refs: dict[str, float]) -> tuple[float | None, str | None]:
    if metric == LIFT_SESSION_RPE:
        rated = [rpe for *_x, rpe in s["work"] if rpe is not None]
        if len(rated) < MIN_RATED_SETS:
            return None, f"{len(rated)} rated sets (needs {MIN_RATED_SETS})"
        return sum(rated) / len(rated), None
    pct = [s["best"][k] / refs[k] * 100 for k in sorted(s["best"]) if k in refs]
    if len(pct) < MIN_EXERCISES:
        return None, f"{len(pct)} eligible exercises (needs {MIN_EXERCISES})"
    return sum(pct) / len(pct), None


def _arm(sessions: list[dict[str, Any]], lo: str, hi: str) -> dict[str, Any]:
    """The raw observations of one arm: sessions read, sessions valued, every set set aside, and the per-session record
    (value, why none, and the prescribed-versus-performed flag the row carries)."""
    mine = [s for s in sessions if _in(s["day"], lo, hi)]
    counts = _new_counts()
    for s in mine:
        for k, v in s["counts"].items():
            counts[k] += v
    verdicts: dict[str, int] = {}
    per_session = []
    for s in mine:
        flag = _prescription_flag(s["row"])
        verdicts[str(flag["as_prescribed"])] = verdicts.get(str(flag["as_prescribed"]), 0) + 1
        per_session.append(
            {
                "date": s["day"],
                "workout_id": str(s["row"].get("source_workout_id") or str(s["row"].get("sk")).rsplit("#", 1)[-1]),
                "value": round(s["value"], 2) if s["value"] is not None else None,
                "no_value_reason": s["reason"],
                **flag,
            }
        )
    return {
        "start": lo,
        "end": hi,
        "n_sessions": len(mine),
        "n_sessions_valued": sum(1 for s in mine if s["value"] is not None),
        "n_days_valued": len({s["day"] for s in mine if s["value"] is not None}),
        **counts,
        "as_prescribed_counts": dict(sorted(verdicts.items())),
        "sessions": per_session,
    }


# ── the close path's seam (the caller injects its read; this module never does I/O) ──

Query = Callable[[str, str, str], list[Any]]


def read_series(query: Query, source: str, metric: str, windows: dict[str, str], start: str, end: str) -> dict[str, float]:
    """day → value over [start, end], computed against the FROZEN baseline reference: the read always spans the baseline
    window too, so a randomization or counterfactual series over another range shares the one reference."""
    rows = query(source, min(start, windows["baseline_start"]), max(end, windows["analysis_end"]))
    return {d: v for d, v in derive(metric, rows, windows)["values"].items() if start <= d <= end}


def attach_observations(stats: dict[str, Any], query: Query, source: str, metric: str, windows: dict[str, str]) -> dict[str, Any]:
    """Put the raw observations of a lift criterion on the analysis stats (no-op for any other metric). Returns ``stats``."""
    if is_lift_metric(metric):
        stats["observations"] = derive(metric, query(source, windows["baseline_start"], windows["analysis_end"]), windows)["observations"]
    return stats
