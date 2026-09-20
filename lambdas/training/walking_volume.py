"""walking_volume.py — the derived walking/cardio volume layer (#3930).

WHY THIS EXISTS

`plan_next_session` read walking from Strava alone. On the week of 13–19 Sep that read
returned 5.09 hr/wk against the owner's 8.5 hr/wk floor and reported the walking gap as
"the largest gap on the board" — the FIRST line of the constraint block, by design, so the
wrongest number in the block was also the loudest. It was wrong because Matthew logs
treadmill and cycling blocks INSIDE his Hevy sessions: on 13–19 Sep those blocks carry
8.33 hr of measured duration that no consumer of the walking floor could see.

A floor stated in hours must be measured in hours from every source that produces them.
This module is that union: one derived layer, per-source breakdown in its own output, so a
reader can see WHICH source carried the hours rather than being handed a single number.

WHAT IT REFUSES TO DO

Apple Health steps are not a walking proxy and this layer will not let them become one.
For the same 13–19 Sep window the step count reads ~1,869/day against ~6 hr/wk of logged
outdoor walking — the phone is in a pocket on a desk, not on a treadmill rail. The
exclusion travels IN the output (`excluded_proxies`) with its reason, because an exclusion
a caller cannot see is an exclusion the next caller re-litigates.

A steps figure CAN be estimated from duration, and `derived_steps_estimate()` will do it —
labelled DERIVED, carrying its assumed cadence, in its own field, with `never_merge_into`
naming the measured field it must never be added to. An estimate that lands in the
measured column is indistinguishable from a measurement forever (the attest-never-backfill
rule); an estimate that carries its own method is just arithmetic.

THE OVERLAP RULING (verified against live DDB, 2026-09-19, window 2026-09-13..19)

A Hevy session is mirrored into Strava as ONE activity typed `WeightTraining` or `Workout`
carrying the session title ("Foundation - Engine - 1 - 9"), never as its component cardio
blocks. Strava counting is restricted to ambulatory/cycling activity types, so a mirrored
Hevy session can never be counted twice: it does not match on the Strava side at all. The
seven Strava `Walk` activities in that window are separate outdoor walks.
"""

from __future__ import annotations

from typing import Any

WALKING_VOLUME_VERSION = "walking-volume@1.0.0"

# ── what counts ──────────────────────────────────────────────────────────────────────
# Strava activity `type`/`sport_type` (lower-cased) → the modality it counts as.
STRAVA_COUNTED_TYPES: dict[str, str] = {
    "walk": "walking",
    "hike": "walking",
    "ride": "cycling",
    "virtualride": "cycling",
    "ebikeride": "cycling",
}

# Hevy exercise-name substrings (lower-cased) → modality. Hevy names are free text from the
# exercise library; the live 13–19 Sep window contains exactly "Walking", "Treadmill",
# "Cycling" and "Stretching". Substrings, not equality, so "Treadmill (Incline)" counts.
HEVY_COUNTED_NAMES: tuple[tuple[str, str], ...] = (
    ("treadmill", "walking"),
    ("walking", "walking"),
    ("incline walk", "walking"),
    ("rucking", "walking"),
    ("cycling", "cycling"),
    ("stationary bike", "cycling"),
    ("air bike", "cycling"),
    ("echo bike", "cycling"),
    ("assault bike", "cycling"),
)

# The floor is a WALKING/CYCLING volume floor derived from the campaign that worked. Rowing,
# elliptical and stair machines produce real minutes and are deliberately NOT folded in —
# they would inflate a number whose provenance measured walking. They are reported by name
# under `not_counted` so the choice is visible rather than silent.
MODALITIES = ("walking", "cycling")

# Assumed cadence for the DERIVED steps arithmetic. Not measured, not Matthew's, not stored.
ASSUMED_CADENCE_SPM = 100

STEPS_EXCLUSION = {
    "source": "apple_health",
    "field": "steps",
    "used_as_proxy": False,
    "reason": (
        "Apple Health steps are NOT a walking proxy and are excluded from this layer by construction: over "
        "13–19 Sep 2026 they read ~1,869/day against ~6 hr/wk of logged outdoor walking, because the phone is "
        "not carried on a treadmill or a bike. A step count measures phone-carrying, not walking volume (#3930)."
    ),
}


def _hours(seconds: float) -> float:
    return round(seconds / 3600.0, 2)


def _modality_for_strava(activity: dict[str, Any]) -> str | None:
    t = (activity.get("sport_type") or activity.get("type") or "").strip().lower()
    return STRAVA_COUNTED_TYPES.get(t)


def _modality_for_hevy(name: str) -> str | None:
    nl = (name or "").strip().lower()
    for key, modality in HEVY_COUNTED_NAMES:
        if key in nl:
            return modality
    return None


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def strava_sessions(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """(counted sessions, names of the activity types seen and NOT counted).

    Live shape (DDB `USER#matthew#SOURCE#strava` / `DATE#...`, read 2026-09-19): the day item
    carries `activities: [{type, sport_type, moving_time_seconds, name, ...}]`.
    """
    counted: list[dict[str, Any]] = []
    skipped: list[str] = []
    for item in items or []:
        day = (item.get("date") or str(item.get("sk", "")).replace("DATE#", ""))[:10]
        for a in item.get("activities") or []:
            modality = _modality_for_strava(a)
            label = (a.get("sport_type") or a.get("type") or "").strip() or "Activity"
            if not modality:
                if label not in skipped:
                    skipped.append(label)
                continue
            counted.append(
                {
                    "date": day,
                    "source": "strava",
                    "modality": modality,
                    "label": a.get("name") or label,
                    "seconds": _float(a.get("moving_time_seconds") or a.get("moving_time")),
                }
            )
    return counted, skipped


def hevy_sessions(workouts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """(counted cardio blocks, names of the exercises seen and NOT counted).

    Live shape (DDB `USER#matthew#SOURCE#hevy` / `DATE#...#WORKOUT#<id>`, read 2026-09-19):
    `exercises: [{name, sets: [{duration_sec, distance_m, reps, weight_kg, ...}]}]`. A cardio
    block is one exercise with one set carrying `duration_sec`. `tool_get_workouts` cannot be
    used here — its `_slim_workout` projection drops `exercises` unless include_sets is set,
    and the per-workout detail tool costs a five-year scan per workout.
    """
    counted: list[dict[str, Any]] = []
    skipped: list[str] = []
    for w in workouts or []:
        day = (w.get("date") or str(w.get("sk", "")).replace("DATE#", ""))[:10]
        for ex in w.get("exercises") or []:
            name = (ex.get("name") or ex.get("exercise_name") or "").strip()
            modality = _modality_for_hevy(name)
            seconds = sum(_float(s.get("duration_sec") or s.get("duration_seconds")) for s in ex.get("sets") or [])
            if not modality:
                # only a block that actually carries duration is worth naming as skipped —
                # otherwise every barbell lift in the session lands in the list
                if seconds and name and name not in skipped:
                    skipped.append(name)
                continue
            if not seconds:
                continue
            counted.append({"date": day, "source": "hevy", "modality": modality, "label": name, "seconds": seconds})
    return counted, skipped


def derived_steps_estimate(walking_hours: float | None, cadence_spm: int = ASSUMED_CADENCE_SPM) -> dict[str, Any] | None:
    """Steps implied by walking DURATION at an ASSUMED cadence. Never a measurement (#3930).

    Returned in its own field, labelled DERIVED, carrying the method and the assumption, with
    `never_merge_into` naming the measured field it may not be added to. Callers that want a
    step count must read the measured one or this one — never their sum.
    """
    if walking_hours is None:
        return None
    return {
        "label": "DERIVED",
        "field": "derived_steps_estimate",
        "value": int(round(walking_hours * 60.0 * cadence_spm)),
        "method": "walking duration x assumed cadence",
        "assumed_cadence_spm": cadence_spm,
        "measured": False,
        "never_merge_into": "steps",
        "note": (
            "An ESTIMATE from duration at an assumed cadence — not Matthew's measured cadence and not a step "
            "count. It must never be summed into, or substituted for, the measured `steps` field: a synthetic "
            "value in a measured column is indistinguishable from a measurement forever."
        ),
    }


def build(
    *,
    window_start: str,
    window_end: str,
    strava_items: list[dict[str, Any]] | None,
    hevy_workouts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """The derived walking-volume layer: Strava UNION Hevy cardio blocks, in HOURS.

    `None` for either argument means the source could not be READ — which is not zero hours.
    An unreadable or silent source makes the total a FLOOR (`total_is_floor`) and says so in
    `honesty`; it never quietly contributes 0.
    """
    s_counted, s_skipped = strava_sessions(strava_items or [])
    h_counted, h_skipped = hevy_sessions(hevy_workouts or [])

    def _source_block(raw: list[dict[str, Any]] | None, counted: list[dict[str, Any]], skipped: list[str]) -> dict:
        if raw is None:
            return {"status": "unreadable", "hours": None, "sessions": 0, "by_modality": {}, "not_counted": []}
        if not raw:
            return {"status": "no_records", "hours": None, "sessions": 0, "by_modality": {}, "not_counted": []}
        by_mod = {m: _hours(sum(c["seconds"] for c in counted if c["modality"] == m)) for m in MODALITIES}
        return {
            "status": "read",
            "hours": _hours(sum(c["seconds"] for c in counted)),
            "sessions": len(counted),
            "by_modality": {m: v for m, v in by_mod.items() if v},
            "not_counted": skipped,
        }

    by_source = {
        "strava": _source_block(strava_items, s_counted, s_skipped),
        "hevy": _source_block(hevy_workouts, h_counted, h_skipped),
    }
    contributing = [b for b in by_source.values() if b["hours"] is not None]
    silent = [n for n, b in by_source.items() if b["hours"] is None]

    total_hr = _hours(sum(c["seconds"] for c in s_counted + h_counted)) if contributing else None
    by_modality = {m: _hours(sum(c["seconds"] for c in s_counted + h_counted if c["modality"] == m)) for m in MODALITIES}

    honesty: list[str] = []
    for name in silent:
        status = by_source[name]["status"]
        honesty.append(
            f"{name} contributed NOTHING to this total ({status}) — the figure is a floor, not the week's volume"
            if status == "unreadable"
            else f"{name} returned no records in the window ({status}) — counted as unmeasured, never as zero hours"
        )
    if not contributing:
        honesty.append("neither source could be read — walking volume is UNKNOWN for this window, which is not the same as none")

    return {
        "layer": "walking_volume",
        "version": WALKING_VOLUME_VERSION,
        "unit": "hours",
        "window": {"start": window_start, "end": window_end, "days": 7},
        "total_hr": total_hr,
        "total_is_floor": bool(silent and contributing),
        "by_source": by_source,
        "by_modality": {m: v for m, v in by_modality.items() if v},
        "counted_modalities": list(MODALITIES),
        "counting_rule": (
            "Strava activities typed " + "/".join(sorted(STRAVA_COUNTED_TYPES)) + " PLUS Hevy exercise blocks named "
            "treadmill/walking/cycling, summed as DURATION in hours — the unit the floor is stated in. Rowing, "
            "elliptical and stair machines are not folded in; they are listed under each source's `not_counted`."
        ),
        "overlap_rule": (
            "A Hevy session is mirrored into Strava as one WeightTraining/Workout activity carrying the session "
            "title, never as its component cardio blocks, and those types are not counted on the Strava side — so "
            "the union cannot double-count a Hevy cardio block (verified against live DDB 2026-09-13..19)."
        ),
        "excluded_proxies": [dict(STEPS_EXCLUSION)],
        "derived_steps_estimate": derived_steps_estimate(by_modality.get("walking") if contributing else None),
        "honesty": honesty,
    }
