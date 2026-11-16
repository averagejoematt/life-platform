"""session_time.py — a performed session's MEASURED lifting minutes, and the per-set time model re-derived from them (#5799).

WHAT IS MEASURED. Hevy's workout payload carries the workout's `start_time` and `end_time` and NO per-set timestamp: the set
keys are index, type, weight_kg, reps, distance_meters, duration_seconds, rpe and custom_metric (read on three raw
`raw/hevy/{id}.json` objects, 2026-11-11). So a session's lifting minutes are the workout's length minus the logged
durations of its TIMED blocks (cardio and stretching: every set a duration with no reps and no load). A loaded carry keeps
its load and stays lifting. That is the only measurement the payload allows; nothing finer is claimed.

THE MODEL IT FEEDS. `session_shape.SESSION_TIME_MODEL` prices a set as `set_seconds + the block's rest_seconds`. A matched
session (the routine it was performed from is known) gives one sample of `set_seconds`: its measured lifting seconds per
performed lifting set, less the routine's mean prescribed rest per lifting set. `derive_set_seconds` takes the median once
the charter's `split.session_minutes.measured_min_sessions` samples exist. The recorded result is `MEASURED_SET_SECONDS`,
produced by `scripts/derive_session_time_model.py` (read-only DynamoDB) — re-run it to refresh the record.

Stored per session on the Hevy record's `adherence.session_time` (`health.adherence_calc.derive_adherence`), beside the
routine's estimate and the charter's `lifting_ceiling`, so a draft can read the trailing measured median for its role
(`role_median_minutes`).
"""

from __future__ import annotations

import statistics
from typing import Any

from common.pacific_time import parse_iso_utc

from training.training_charter import charter_value

BASIS = (
    "workout end_time - start_time, minus the logged durations of timed blocks (cardio, stretching); Hevy's payload has "
    "no per-set timestamps (#5799)"
)

# The recorded derivation (`scripts/derive_session_time_model.py`, read-only DynamoDB). `set_seconds` is the median of the
# per-session samples; `n` and `as_of` say what it stands on. Re-run the script and paste its output here to refresh it.
MEASURED_SET_SECONDS: dict[str, Any] = {
    "set_seconds": 99,
    "n": 45,
    "as_of": "2026-11-10",
    "window": ["2026-09-07", "2026-11-10"],
    "sample_iqr": [86.0, 110.1],
    "source": "scripts/derive_session_time_model.py",
}


def _set_seconds_logged(st: dict[str, Any]) -> int:
    return int(st.get("duration_seconds") or st.get("duration_sec") or 0)


def is_timed_block(ex: dict[str, Any]) -> bool:
    """A performed block every set of which is a duration with no reps and no load: cardio or stretching, never lifting."""
    sets = ex.get("sets") or []
    return bool(sets) and all(_set_seconds_logged(s) and not s.get("reps") and not s.get("weight_kg") for s in sets)


def _workout_seconds(performed: dict[str, Any]) -> int | None:
    start, end = parse_iso_utc(performed.get("start_time")), parse_iso_utc(performed.get("end_time"))
    if start is not None and end is not None:
        return int((end - start).total_seconds())
    dur = performed.get("duration_sec")
    return int(dur) if dur else None


def _mean_rest_per_lifting_set(ir: Any, catalog_movements: dict[str, Any]) -> float | None:
    """The routine's prescribed rest, averaged over its lifting sets (warm-up rows included, as `routine_minutes` counts them)."""
    from training.session_shape import _block_kind

    sets = rest = 0
    for b in getattr(ir, "exercises", None) or []:
        if _block_kind(b, catalog_movements) != "lifting":
            continue
        n = len(getattr(b, "sets", None) or [])
        sets += n
        rest += n * int(getattr(b, "rest_seconds", None) or 0)
    return rest / sets if sets else None


def _role_of(ir: Any) -> str | None:
    snap = getattr(ir, "inputs_snapshot", None) or {}
    return (snap.get("calendar") or {}).get("session_role") or snap.get("session_role")


def measure(performed: dict[str, Any], ir: Any = None, catalog_movements: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The session's measured lifting minutes (`BASIS`), against the ceiling and, when the routine is known, its estimate.

    `performed` is a raw Hevy workout or a normalized record (both duration spellings are read). None when the workout has no
    readable length. `implied_set_seconds` is this session's sample for `derive_set_seconds` (None on a cardio-only day)."""
    from training.session_shape import lifting_minutes_cap, routine_minutes

    total = _workout_seconds(performed)
    if not total or total <= 0:
        return None
    exercises = performed.get("exercises") or []
    timed = sum(_set_seconds_logged(s) for ex in exercises if is_timed_block(ex) for s in ex.get("sets") or [])
    lifting_sets = sum(len(ex.get("sets") or []) for ex in exercises if not is_timed_block(ex))
    lifting_s = max(0, total - timed)
    cap = lifting_minutes_cap()
    out: dict[str, Any] = {
        "lifting_minutes": round(lifting_s / 60.0, 1),
        "workout_minutes": round(total / 60.0, 1),
        "timed_block_minutes": round(timed / 60.0, 1),
        "lifting_sets": lifting_sets,
        "ceiling_minutes": cap,
        "over_ceiling": lifting_s / 60.0 > cap,
        "basis": BASIS,
    }
    if ir is not None:
        movements = catalog_movements or {}
        out["estimate_minutes"] = routine_minutes(list(getattr(ir, "exercises", None) or []), movements)["lifting_minutes"]
        out["session_role"] = _role_of(ir)
        rest = _mean_rest_per_lifting_set(ir, movements)
        out["implied_set_seconds"] = round(lifting_s / lifting_sets - rest, 1) if lifting_sets and rest is not None else None
    return out


def _session_time(rec: dict[str, Any]) -> dict[str, Any]:
    return ((rec or {}).get("adherence") or {}).get("session_time") or {}


def role_median_minutes(workouts: list[dict[str, Any]] | None, role: str) -> dict[str, Any] | None:
    """The trailing measured median of a role's lifting minutes over `workouts` (the block's Hevy records), with its n.
    None when no record of that role carries a measurement (records before #5799 carry none)."""
    vals = [
        float(st["lifting_minutes"])
        for st in (_session_time(w) for w in workouts or [])
        if st.get("session_role") == role and st.get("lifting_sets") and st.get("lifting_minutes") is not None
    ]
    if not vals:
        return None
    return {"median_minutes": round(statistics.median(vals), 1), "n": len(vals), "role": role, "basis": BASIS}


def min_sessions() -> int:
    """The charter's minimum measured sessions before `set_seconds` is re-derived (`split.session_minutes.measured_min_sessions`)."""
    return int(charter_value("split.session_minutes.measured_min_sessions"))


def derive_set_seconds(samples: list[tuple[str, float]]) -> dict[str, Any]:
    """`set_seconds` from (date, implied_set_seconds) samples: their median, n, window and as-of date — or `insufficient`
    below the charter minimum, when the model must not be re-derived."""
    vals = sorted(v for _, v in samples if v is not None)
    dates = sorted(d for d, v in samples if v is not None)
    need = min_sessions()
    if len(vals) < need:
        return {"status": "insufficient", "n": len(vals), "min_n": need}
    q = statistics.quantiles(vals, n=4)
    return {
        "set_seconds": int(round(statistics.median(vals))),
        "n": len(vals),
        "as_of": dates[-1],
        "window": [dates[0], dates[-1]],
        "sample_iqr": [round(q[0], 1), round(q[2], 1)],
        "source": "scripts/derive_session_time_model.py",
    }
