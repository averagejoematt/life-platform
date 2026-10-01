"""training/cardio_hr.py — a Hevy cardio block joined to the wearable HR over its minutes (#4412).

WHY THIS EXISTS

Hevy logs a recumbent bike or a treadmill block as a duration and a distance — no heart rate.
WHOOP (and Garmin, when it is not paused, ADR-074) recorded the SAME minutes, and both reach the
platform as Strava activities (`USER#matthew#SOURCE#strava`, `activities[]`: `start_date` UTC,
`elapsed_time_seconds`, `average_heartrate`, `max_heartrate`, `zone{n}_seconds`, `device_name`).
Without the join, intensity on the bike and the treadmill — the aerobic side of the program —
was invisible to the engine and to the aerobic critic.

THE JOIN (computed here, never by a model)

  * THE BLOCK'S MINUTES ARE INFERRED. Hevy sets carry no timestamps — only the session's
    `start_time`/`end_time`. Cardio and stretching sit at the TAIL of his sessions, so a block's
    end is `session_end − Σ(durations of the timed blocks after it)` (`timing: inferred_tail`).
    A block at the head of a session is placed the same way from `start_time`
    (`inferred_head`). When a block has a lifted exercise on both sides its minutes cannot be
    placed and the join is `unknown` — never a guess. The inference ignores rest and
    transition time between the tail blocks, so the window can be off by a few minutes; the
    record says `timing` so no reader mistakes it for a measured interval.
  * THE MATCHER IS THE DE-DUP'S. HR-covered minutes are `common.activity_overlap.hr_intervals`
    and the covered share is `activity_overlap.overlap_seconds` — the SAME derivation the
    Hevy↔Strava load and calorie de-dup use (#4075/#4158). ONE difference, by design
    (`lift_is_echo=False`): only Hevy's own push is dropped, not every lift-labelled activity.
    1.0.0 dropped those too and joined nothing on the live sessions (#4412 proof read,
    2026-10-01): WHOOP records his whole gym session as Cross Training / Activity, it reaches
    Strava as `WeightTraining`, and that record is the one wearable that measured the bike
    minutes at the tail. The #3716 ruling says Cross Training is not the recumbent MODALITY;
    it never said its heart rate may not be used.
  * THE CANDIDATES ARE STRAVA + WHOOP. WHOOP pushes only SOME workouts to Strava (the 09-28
    'Activity', avg 135, never reached it), so the store also reads the WHOOP workout
    partition (`whoop_activity` maps a row to the activity shape). A Strava row from the WHOOP
    device that starts within `START_WINDOW_MIN` of a WHOOP workout is the same record twice
    and is dropped; WHOOP rows are de-duplicated by `workout_id` (one workout sits in two date
    partitions when it crosses midnight).
  * `hr_coverage` = covered seconds / block seconds. At or above `HR_COVERAGE_MIN` the block
    is `joined`: `avg_hr` is the overlap-weighted mean of the overlapping activities' averages,
    `max_hr` their max (an ACTIVITY max — it may fall outside the block's own minutes; the
    record says so), `zone_seconds` each activity's zone seconds prorated by its overlap share
    (`zone_basis: prorated_by_overlap` — a uniform-distribution assumption, labelled) — and only
    when EVERY overlapping activity carries zones (the WHOOP rows' zone minutes are not used:
    they read 0 on sessions with a 135 bpm average, so they are not a measurement).
    `avg_hr` is an ACTIVITY average too: a WHOOP gym session averages the lifting minutes in.
  * Below the threshold, or no overlap: `unknown` — `avg_hr`/`max_hr`/`zone_seconds` are None,
    NEVER 0 (ADR-104). `hr_coverage` still reports the measured share (0.0 when nothing
    overlapped), so the reader sees why.
  * HR drift and 60-s recovery need a per-second series over the block; the wire carries only
    per-activity summaries, whose `hr_recovery` describes the ACTIVITY's end, not the block's.
    Both are recorded as None with the reason — the prerequisite for the v0.5 test battery is
    stated, not faked.

`HR_COVERAGE_MIN` is 0.5 — the platform's existing "same minutes" convention (#4068: at least
half of the shorter record overlaps). It is a CONVENTION, not derived from his variance and not
a population norm (ADR-105): re-derive it once enough joined blocks exist to measure how far the
tail inference drifts from the wearable's own interval.

Pure — no boto3, no I/O, no clock reads.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional

from common import activity_overlap
from common.pacific_time import parse_iso_utc
from common.strava_read_seam import START_WINDOW_MIN

from training import walking_volume

CARDIO_HR_VERSION = "cardio-hr@1.1.0"

HR_COVERAGE_MIN = 0.5
COVERAGE_PROVENANCE = {
    "provenance": "convention",
    "derived_by": (
        "#4068's same-minutes rule (at least half overlaps); NOT his variance, NOT a population norm (ADR-105) — "
        "re-derive from the measured drift between the inferred tail window and the wearable interval"
    ),
}
ZONES = tuple(f"zone{i}_seconds" for i in range(1, 6))
_NO_SERIES = "no per-second HR series on the wire — the activity summary's hr_recovery describes the activity's end, not the block's"


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):  # a flattened DDB NULL reads as True — absent, never 1
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _block_seconds(ex: Mapping[str, Any]) -> float:
    return sum(_num(s.get("duration_sec") or s.get("duration_seconds")) or 0.0 for s in ex.get("sets") or [])


def _is_timed_only(ex: Mapping[str, Any]) -> bool:
    """A block whose every set is a duration (cardio, stretching) — no reps, no load."""
    sets = ex.get("sets") or []
    if not sets:
        return False
    for s in sets:
        if not (_num(s.get("duration_sec") or s.get("duration_seconds")) or 0) > 0:
            return False
        if _num(s.get("reps")) or _num(s.get("weight_kg")):
            return False
    return True


def cardio_modality(ex: Mapping[str, Any]) -> Optional[str]:
    """walking / cycling for a Hevy cardio block — `walking_volume`'s counted-name rule, the one definition."""
    name = str(ex.get("name") or ex.get("exercise_name") or "")
    return walking_volume._modality_for_hevy(name) if _block_seconds(ex) > 0 else None


def block_windows(workout: Mapping[str, Any]) -> list[dict[str, Any]]:
    """[{index, start, end, timing}] for each exercise whose minutes can be placed (inferred)."""
    start, end = parse_iso_utc(workout.get("start_time")), parse_iso_utc(workout.get("end_time"))
    exercises = list(workout.get("exercises") or [])
    out: list[dict[str, Any]] = []
    if start is None or end is None or end <= start:
        return out
    for i, ex in enumerate(exercises):
        secs = _block_seconds(ex)
        if secs <= 0:
            continue
        after, before = exercises[i + 1 :], exercises[:i]
        if all(_is_timed_only(e) for e in after):
            b_end = end - timedelta(seconds=sum(_block_seconds(e) for e in after))
            out.append({"index": i, "start": b_end - timedelta(seconds=secs), "end": b_end, "timing": "inferred_tail"})
        elif all(_is_timed_only(e) for e in before):
            b_start = start + timedelta(seconds=sum(_block_seconds(e) for e in before))
            out.append({"index": i, "start": b_start, "end": b_start + timedelta(seconds=secs), "timing": "inferred_head"})
    return out


def _hr_activities(activities: Iterable[Mapping[str, Any]]) -> list[tuple[Mapping[str, Any], datetime, datetime]]:
    rows = []
    for a in activities or []:
        if _num(a.get("average_heartrate")) is None:
            continue
        # the de-dup's own matcher, one activity at a time; only Hevy's own push is an echo here
        span = activity_overlap.hr_intervals([a], lift_is_echo=False)
        if span:
            rows.append((a, span[0][0], span[0][1]))
    return rows


def join_block(b0: datetime, b1: datetime, activities: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The HR fields for one block window against a day's Strava activities."""
    acts = _hr_activities(activities)
    block_s = (b1 - b0).total_seconds()
    covered = activity_overlap.overlap_seconds(b0, b1, activity_overlap.hr_intervals([a for a, _, _ in acts], lift_is_echo=False))
    coverage = round(covered / block_s, 3) if block_s > 0 else 0.0
    used = [(a, activity_overlap.overlap_seconds(b0, b1, [(s, e)]), s, e) for a, s, e in acts]
    used = [u for u in used if u[1] > 0]
    base: dict[str, Any] = {
        "hr_coverage": coverage,
        "coverage_min": HR_COVERAGE_MIN,
        "hr_drift": None,
        "hr_recovery_60s": None,
        "drift_recovery_reason": _NO_SERIES,
    }
    if not used or coverage < HR_COVERAGE_MIN:
        why = "no HR-bearing wearable activity overlaps the block" if not used else f"coverage {coverage} < {HR_COVERAGE_MIN}"
        return {**base, "state": "unknown", "reason": why, "hr_source": None, "avg_hr": None, "max_hr": None, "zone_seconds": None}
    weight = sum(u[1] for u in used)
    avg = sum((_num(a.get("average_heartrate")) or 0.0) * ov for a, ov, _, _ in used) / weight
    maxes = [m for m in (_num(a.get("max_heartrate")) for a, _, _, _ in used) if m is not None]
    zones: Optional[dict[str, int]] = None
    if all(any(_num(a.get(z)) is not None for z in ZONES) for a, _, _, _ in used):
        zones = {z: 0 for z in ZONES}
        for a, ov, s, e in used:
            share = ov / max((e - s).total_seconds(), 1.0)
            for z in ZONES:
                zones[z] += int(round((_num(a.get(z)) or 0.0) * share))
    devices = sorted({str(a.get("device_name") or "unknown") for a, _, _, _ in used})
    return {
        **base,
        "state": "joined",
        "reason": f"{int(covered)} s of {int(block_s)} s inside {len(used)} HR-bearing activit{'y' if len(used) == 1 else 'ies'}",
        "hr_source": "+".join(devices),
        "hr_activities": [
            {
                "start_date": a.get("start_date"),
                "sport_type": a.get("sport_type") or a.get("type"),
                "device": a.get("device_name"),
                "whoop_workout_id": a.get("whoop_workout_id"),
                "overlap_s": int(ov),
            }
            for a, ov, _, _ in used
        ],
        "avg_hr": round(avg, 1),
        "max_hr": max(maxes) if maxes else None,
        "avg_hr_basis": "overlap-weighted activity averages — an activity that spans lifting minutes averages them in",
        "max_hr_basis": "activity max — may fall outside the block's minutes",
        "zone_seconds": zones,
        "zone_basis": "prorated_by_overlap" if zones else None,
    }


def whoop_activity(row: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """A WHOOP workout row (`USER#…#SOURCE#whoop`, `DATE#…#WORKOUT#…`) in the activity shape, or None."""
    s, e = parse_iso_utc(row.get("start_time")), parse_iso_utc(row.get("end_time"))
    if s is None or e is None or e <= s:
        return None
    return {
        "start_date": s.isoformat(),
        "elapsed_time_seconds": (e - s).total_seconds(),
        "average_heartrate": row.get("average_heart_rate"),
        "max_heartrate": row.get("max_heart_rate"),
        "sport_type": row.get("sport_name"),
        "device_name": "WHOOP",
        "whoop_workout_id": row.get("workout_id"),
    }


def candidates(
    strava: Optional[Iterable[Mapping[str, Any]]], whoop_rows: Optional[Iterable[Mapping[str, Any]]]
) -> Optional[list[Mapping[str, Any]]]:
    """Strava activities + WHOOP workouts, each session once. None only when BOTH reads failed."""
    if strava is None and whoop_rows is None:
        return None
    seen: set[str] = set()
    whoop: list[dict[str, Any]] = []
    for r in whoop_rows or []:
        a = whoop_activity(r)
        wid = str(r.get("workout_id") or r.get("sk") or "")
        if a is not None and wid not in seen:
            seen.add(wid)
            whoop.append(a)
    starts = [parse_iso_utc(a["start_date"]) for a in whoop]
    window = timedelta(minutes=START_WINDOW_MIN)
    out: list[Mapping[str, Any]] = list(whoop)
    for act in strava or []:
        st = parse_iso_utc(act.get("start_date"))
        twin = str(act.get("device_name") or "").strip().lower() == "whoop" and st is not None
        if twin and any(w is not None and abs(w - st) <= window for w in starts):
            continue  # the WHOOP workout's own Strava copy — the direct row stands for it
        out.append(act)
    return out


def join_workout(
    workout: Mapping[str, Any],
    activities: Optional[Iterable[Mapping[str, Any]]],
    whoop_workouts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """The `cardio_hr` record for one Hevy workout: one entry per cardio block. Pure.

    `activities` is every Strava activity and `whoop_workouts` every WHOOP workout row that could
    overlap the session (the session's day and the next — an evening session crosses UTC
    midnight). `None` = that partition could not be read; when NEITHER could, every block is
    `unknown` with that reason, never 0."""
    windows = {w["index"]: w for w in block_windows(workout)}
    acts = candidates(activities, whoop_workouts)
    blocks: list[dict[str, Any]] = []
    for i, ex in enumerate(workout.get("exercises") or []):
        modality = cardio_modality(ex)
        if not modality:
            continue
        w = windows.get(i)
        row: dict[str, Any] = {
            "exercise_index": i,
            "name": ex.get("name"),
            "template_id": ex.get("template_id"),  # the NORMALIZED record (hevy_compiler owns the raw Hevy schema)
            "modality": modality,
            "duration_s": int(_block_seconds(ex)),
            "window": {"start_utc": w["start"].isoformat(), "end_utc": w["end"].isoformat(), "timing": w["timing"]} if w else None,
        }
        if w is None:
            row.update(state="unknown", reason="block minutes cannot be placed — lifted exercises on both sides", hr_coverage=None)
            row.update(hr_source=None, avg_hr=None, max_hr=None, zone_seconds=None)
        elif acts is None:
            row.update(state="unknown", reason="the Strava and WHOOP partitions could not be read", hr_coverage=None)
            row.update(hr_source=None, avg_hr=None, max_hr=None, zone_seconds=None)
        else:
            row.update(join_block(w["start"], w["end"], acts))
        blocks.append(row)
    return {"version": CARDIO_HR_VERSION, "blocks": blocks, "threshold": {"hr_coverage_min": HR_COVERAGE_MIN, **COVERAGE_PROVENANCE}}


def block_for(workout: Mapping[str, Any], exercise_index: int) -> Optional[Mapping[str, Any]]:
    """The stored joined record for one exercise of a Hevy workout, or None."""
    rec = workout.get("cardio_hr")
    blocks = rec.get("blocks") if isinstance(rec, Mapping) else None
    for b in blocks or []:
        if _num(b.get("exercise_index")) == exercise_index:
            return b
    return None
