"""recent_aerobic.py — what his legs did in the last three days, per activity (#4387).

WHY THIS EXISTS

On 2026-09-27 the coach planned Mon 09-28: trap-bar + squat, then 60 min of incline treadmill.
Its only aerobic input was `constraint_block.walking` — a 7-day TOTAL in hours, over a window
that ended at target − 2. It never saw Sunday, and it had no per-walk duration and no heart rate.
Strava held 4.4 h / 13.4 mi of outdoor walking on 09-26..27 — walks of 102 and 165 min at
~116 bpm average, both over the then walking redlines (≤ 75 min per walk, ≤ 105 bpm). No critic saw
them; the red team approved the treadmill (`CORRECTION#2026-09-27#5a60fd05`).

A total cannot say "yesterday was 2¾ hours on foot". This block can:

  * ONE ROW PER ACTIVITY over the last three days through target − 1 — date, source, device,
    modality (walk / treadmill / cycling / recumbent), moving time, distance, elevation, average
    and max HR — each flagged against `owner_redlines.walking_floor_hr_wk`'s walk length
    (`over_75_min`); its heart rate is a MEASUREMENT with its basis (`avg_hr_basis`), never a grade;
  * the SAME sources and the SAME time de-dup as the weekly walking hours (#3930/#4068): Strava
    Walk/Hike/Ride UNION the Hevy treadmill/walking/cycling blocks Strava cannot see, a
    WHOOP/Garmin walk recorded over a Hevy cardio session's minutes counted once. The primitives
    are `training.walking_volume`'s — this module adds per-row detail, never a second rule;
  * weight-bearing hours in the last 48 h and 72 h, and week-to-date hours against the ramp
    (`ramp_hr_per_wk_max`) and the target (`target_hr_wk`);
  * #4503 OD7 — the STANDALONE walks of the trailing 7 days (and the 7 before): Strava walks whose
    minutes outside every Hevy session (the gym window — lifting sessions too, not only cardio
    ones) reach `standalone_walks.min_minutes`, de-duplicated across devices by the same
    `walking_volume.dedup_strava` rule. A walk with no timestamp cannot be placed against a gym
    window; it is counted in `untimed`, never as standalone, and makes a short count UNKNOWN.

THE HEART-RATE LINE IS RETIRED (#5916, owner ruling 2026-11-13). OD2's cap on a walk's average and
its target are history (`redline_changelog.RETIRED_WALKING_HR_LINE`). Easy walking is prescribed
and judged by the talk test plus RPE (`EASY_EFFORT_CUE`, read from the redline's `easy_rpe_max`).
Heart rate is still recorded on every row that has one, labelled as a measurement with its basis,
and nothing here grades it: no `avg_hr_over_ceiling` flag, no cap on the block's `redlines`, no HR
field on `cardio_pick`. Records written before the ruling keep the flags they were written with.

THE WATCH BACKSTOP (#5369/#5371): from 2026-10-26 WHOOP no longer shares to Strava and the watch
uploads its own workouts. A caller may hand in the apple_health day rows (`apple_items`); the watch's
own walks and rides (`walking_volume.apple_sessions`) join LAST in the same time de-dup — Hevy, then
Strava, then Apple (`walking_volume.dedup_sources`) — so a walk only the watch recorded is a row and a
walk it also uploaded is one row. An Apple row carries the modality, minutes and start only: its
heart rate, distance and device stay in the owner-only map (the walk's HR flag reads unknown).

THE WALK-SIGNAL CHECK (#5669): on 2026-10-20 a WHOOP walk reached Strava, was ingested, then left
Strava's list; the #4638 reconciler tombstoned the day and this block read it as a day with no
walk — no floor, no honesty line. A caller may hand in WHOOP + Habitify rows (`completeness_inputs`);
`walking_volume.completeness` — the weekly layer's own check, not a second rule — names any WHOOP
walking workout no counted walk or Hevy cardio session overlaps, and any completed walk habit on a
day with no counted walking. A gap is a SIGNAL, never hours: it turns the totals into a floor, and
every reader below that turns a total into a decision treats a window holding a gap as unknown in
the direction the missing walk could flip (`aerobic_minutes_7d`, `legs_loaded`, `weekly_reports`).

It is PURE: the partitions are read by `mcp.shared_quantities.recent_aerobic_layer`, the one
module that owns the walking definition, and handed in. `None` for a source means it could not
be read — never zero hours.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from common.pacific_time import pacific_weekday, parse_day_key, shift_day_key

from training import cardio_hr, owner_redlines, redline_changelog, standing_constraints, walking_volume

# 1.1.0 (#5369): the watch's own walks/rides as a third source; 1.2.0 (#5669): the walk-signal completeness check;
# 1.3.0 (#5669): the owner's walk corrections, labelled `owner_correction`; 1.4.0 (#5916): heart rate is a measurement
# with its basis, never graded — the talk test plus RPE replace the cap and the target
RECENT_AEROBIC_VERSION = "recent-aerobic@1.4.0"

RECENT_DAYS = 3  # the rows: target − 3 .. target − 1 (tonight's plan sees today)
READ_DAYS = 14  # the partition read: covers the prior Mon–Sun week and the trailing-7 comparison
WEIGHT_BEARING = ("walk", "treadmill")
_WALKING = owner_redlines.REDLINES["walking_floor_hr_wk"]
# "2–3 per day, none over 75 min" — `walking_floor_hr_wk.walks` (owner-history). A test holds this
# number equal to the phrase in the redline, so the two cannot drift apart.
WALK_MAX_MIN = 75
# #5916 (owner ruling 2026-11-13): THE intensity line — the talk test plus the redline's easy-effort RPE. No bpm.
EASY_EFFORT_CUE = standing_constraints.easy_effort_cue(int(_WALKING["easy_rpe_max"]))
# What a row's heart rate IS since #5916: a measurement, stated with its basis, graded against nothing.
HR_NOT_GRADED = "information only, never graded against a fixed ceiling (owner ruling 2026-11-13, #5916)"
AVG_HR_BASIS_DEVICE = f"measured: the recording device's average over the whole activity; {HR_NOT_GRADED}"
AVG_HR_BASIS_JOINED = "measured: wearable heart rate joined over the block's inferred minutes ({basis}); " + HR_NOT_GRADED
# RETIRED 2026-11-13 (#5916). Nothing in this module prescribes or grades against these two. The names stay ONLY because
# `coach.critics_aerobic` (another lane's file) still formats them into its swap sentence; delete both with that change.
HR_CEILING_BPM = int(redline_changelog.RETIRED_WALKING_HR_LINE["hr_ceiling_bpm"])
HR_TARGET_BPM = int(redline_changelog.RETIRED_WALKING_HR_LINE["hr_target_bpm"])
_STANDALONE = _WALKING["standalone_walks"]  # #4503 OD7: >= 3 walks/wk of >= 20 min outside a gym window
_M_PER_MI = 1609.344

# The joints_tendons trigger (#4387). POPULATION-DERIVED, not his variance (ADR-105): the value is
# the issue's acceptance threshold — roughly two redline-length walks (2 × 75 min = 2.5 h) plus a
# half-hour of ordinary daily walking inside two days. It is not fitted to his own tendon or knee
# record; re-derive it from his pain-note history once the note layer holds a season of it.
WEIGHT_BEARING_48H_TRIGGER_HR = 3.0
TRIGGER_PROVENANCE = {
    "provenance": "population-derived",
    "derived_by": (
        "#4387 acceptance (owner incident 2026-09-27): ~two redline-length walks (2 × 75 min) plus ordinary daily walking in 48 h; "
        "NOT his variance — re-derive from his pain-note history"
    ),
}


def _hours(seconds: float) -> float:
    return round(float(seconds) / 3600.0, 2)


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _hevy_modality(name: str) -> str | None:
    """walk / treadmill / cycling / recumbent for a COUNTED Hevy block (walking_volume decides what counts)."""
    counted = walking_volume._modality_for_hevy(name)
    if counted is None:
        return None
    nl = (name or "").lower()
    if "recumbent" in nl:
        return "recumbent"
    if counted == "cycling":
        return "cycling"
    return "treadmill" if ("treadmill" in nl or "incline walk" in nl) else "walk"


def _strava_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items or []:
        day = (item.get("date") or str(item.get("sk", "")).replace("DATE#", ""))[:10]
        for a in item.get("activities") or []:
            counted = walking_volume._modality_for_strava(a)
            if not counted:
                continue
            start = walking_volume._parse_utc(a.get("start_date"))
            elapsed = walking_volume._float(a.get("elapsed_time_seconds") or a.get("elapsed_time"))
            dist_mi = _num(a.get("distance_miles"))
            if dist_mi is None and _num(a.get("distance_meters")) is not None:
                dist_mi = float(a["distance_meters"]) / _M_PER_MI
            rows.append(
                {
                    "date": day,
                    "source": "strava",
                    "device": a.get("device_name"),
                    "modality": "walk" if counted == "walking" else "cycling",
                    "label": (a.get("sport_type") or a.get("type") or "").strip(),
                    "seconds": walking_volume._float(a.get("moving_time_seconds") or a.get("moving_time")),
                    "seconds_as_recorded": walking_volume._float(a.get("moving_time_seconds") or a.get("moving_time")),
                    "start": start,
                    "end": (start + timedelta(seconds=elapsed)) if (start is not None and elapsed > 0) else None,
                    "distance_mi": round(dist_mi, 2) if dist_mi is not None else None,
                    "elevation_ft": _num(a.get("total_elevation_gain_feet")),
                    "avg_hr": _num(a.get("average_heartrate")),
                    "max_hr": _num(a.get("max_heartrate")),
                    "avg_hr_basis": AVG_HR_BASIS_DEVICE,
                }
            )
    return rows


def _apple_rows(items: Any, start: str, end: str) -> list[dict[str, Any]]:
    """The watch's own counted walks/rides over [start, end] (Pacific) as block rows — minutes and
    start only; HR, distance and elevation unknown (owner-only, #5369)."""
    counted, _skipped = walking_volume.apple_sessions(items or [], start, end)
    rows: list[dict[str, Any]] = []
    for c in counted:
        indoor = "indoor" in str(c.get("label") or "").lower()
        rows.append(
            {
                **c,
                "modality": "cycling" if c["modality"] == "cycling" else ("treadmill" if indoor else "walk"),
                "seconds_as_recorded": c["seconds"],
                "distance_mi": None,
                "elevation_ft": None,
                "avg_hr": None,
                "max_hr": None,
            }
        )
    return rows


def _correction_row(c: dict[str, Any]) -> dict[str, Any]:
    """A COUNTED owner correction (#5669) as a block row: an outdoor walk with his minutes; no start, HR, distance or
    device — he measured the duration, nothing else. `method` labels it wherever the row surfaces."""
    return {
        **c,
        "modality": "walk",
        "seconds_as_recorded": c["seconds"],
        "distance_mi": None,
        "elevation_ft": None,
        "avg_hr": None,
        "max_hr": None,
    }


def _block_hr(w: dict[str, Any], idx: int, activities: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The block's OWN heart rate (#4412): the stored `cardio_hr` join when it is joined, else the same
    pure join over the Strava activities in hand (the stored copy may predate the wearable's arrival)."""
    stored = cardio_hr.block_for(w, idx)
    if stored is not None and stored.get("state") == "joined":
        return dict(stored)
    for b in cardio_hr.join_workout(w, activities)["blocks"]:
        if b["exercise_index"] == idx:
            return b
    return None


def _hevy_rows(workouts: list[dict[str, Any]], strava_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per counted Hevy cardio block. Hevy carries no heart rate; the block's own minutes
    (inferred from the session tail) are joined to the wearable HR over them (`training.cardio_hr`,
    #4412). Below the coverage threshold, or no overlap, the HR is None — unknown, never 0."""
    activities = [a for item in strava_items or [] for a in item.get("activities") or []]
    rows: list[dict[str, Any]] = []
    for w in workouts or []:
        day = (w.get("date") or str(w.get("sk", "")).replace("DATE#", ""))[:10]
        start, end = walking_volume._parse_utc(w.get("start_time")), walking_volume._parse_utc(w.get("end_time"))
        for idx, ex in enumerate(w.get("exercises") or []):
            name = (ex.get("name") or ex.get("exercise_name") or "").strip()
            modality = _hevy_modality(name)
            sets = ex.get("sets") or []
            seconds = sum(walking_volume._float(s.get("duration_sec") or s.get("duration_seconds")) for s in sets)
            if not modality or not seconds:
                continue
            dist_m = sum(walking_volume._float(s.get("distance_m")) for s in sets)
            hr = _block_hr(w, idx, activities) or {}
            joined = hr.get("state") == "joined"
            rows.append(
                {
                    "date": day,
                    "source": "hevy",
                    "device": "hevy",
                    "modality": modality,
                    "label": name,
                    "seconds": seconds,
                    "start": start,
                    "end": end,
                    "distance_mi": round(dist_m / _M_PER_MI, 2) if dist_m else None,
                    "elevation_ft": None,
                    "avg_hr": _num(hr.get("avg_hr")) if joined else None,
                    "max_hr": _num(hr.get("max_hr")) if joined else None,
                    "avg_hr_basis": AVG_HR_BASIS_JOINED.format(basis=hr.get("avg_hr_basis") or "#4412 join"),
                    "hr_source": (
                        f"the block's inferred minutes ({(hr.get('window') or {}).get('timing')}), from a {hr.get('hr_source')} "
                        f"Strava record, coverage {hr.get('hr_coverage')} (#4412 join)"
                        if joined
                        else None
                    ),
                    "hr_coverage": _num(hr.get("hr_coverage")),
                    "hr_state": hr.get("state") or "unknown",
                }
            )
    return rows


def gym_windows(workouts: list[dict[str, Any]] | None) -> list[tuple[Any, Any]]:
    """[start_time, end_time] of EVERY timed Hevy session — the gym window a standalone walk sits outside (#4503 OD7).

    Wider than `walking_volume.hevy_cardio_intervals` (cardio-carrying sessions only): a walk recorded
    over a lifting session is the walk to the rack, not a standalone walk."""
    out = []
    for w in workouts or []:
        start, end = walking_volume._parse_utc(w.get("start_time")), walking_volume._parse_utc(w.get("end_time"))
        if start is not None and end is not None and end > start:
            out.append((start, end))
    return out


def standalone_walks(
    strava_raw: list[dict[str, Any]],
    workouts: list[dict[str, Any]] | None,
    start: str,
    end: str,
    apple_raw: list[dict[str, Any]] | None = None,
    correction_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The OD7 walk count over [start, end]: Strava walks — and, wired, the watch's own walks (#5369),
    last — whose de-duplicated minutes OUTSIDE every gym window reach the redline's `min_minutes`.
    Pure. The time rule is `walking_volume.dedup_strava`'s, with every Hevy session claiming its
    interval first — so a WHOOP + Garmin pair of one walk counts once, a walk the watch also uploaded
    counts once, and a walk inside a session counts only its minutes outside it."""
    walks = [r for r in strava_raw if r["modality"] == "walk" and start <= r["date"] <= end]
    if apple_raw is None:
        kept, _ = walking_volume.dedup_strava(walks, gym_windows(workouts))
    else:
        a_walks = [r for r in apple_raw if r["modality"] in WEIGHT_BEARING and start <= r["date"] <= end]
        s_kept, a_kept, _ = walking_volume.dedup_sources(walks, a_walks, gym_windows(workouts))
        kept = s_kept + a_kept
    min_s = float(_STANDALONE["min_minutes"]) * 60.0
    timed = [r for r in kept if r.get("start") is not None and r.get("end") is not None]
    counted = sorted((r for r in timed if r["seconds"] >= min_s), key=lambda r: r["start"])
    walks = [
        {
            "date": r["date"],
            "weekday": pacific_weekday(r["date"]),  # #5274: standalone_walks.*.walks[]
            "start_utc": r["start"].isoformat(),
            "minutes_outside_gym": round(r["seconds"] / 60.0, 1),
            "device": r.get("device"),
        }
        for r in counted
    ]
    # #5669: a COUNTED owner correction is an outdoor walk by its kind — outside every gym window by definition,
    # untimed by nature. It counts when its minutes reach min_minutes, labelled, never as a device's walk.
    for c in correction_rows or []:
        if c["modality"] == "walk" and start <= c["date"] <= end and c["seconds"] >= min_s:
            walks.append(
                {
                    "date": c["date"],
                    "weekday": pacific_weekday(c["date"]),
                    "start_utc": None,
                    "minutes_outside_gym": round(c["seconds"] / 60.0, 1),
                    "device": None,
                    "method": walking_volume.CORRECTION_METHOD,
                }
            )
    return {
        "start": start,
        "end": end,
        "count": len(walks),
        "untimed": len(kept) - len(timed),
        "walks": walks,
    }


def _public_row(r: dict[str, Any]) -> dict[str, Any]:
    wb = r["modality"] in WEIGHT_BEARING
    minutes = round(r["seconds"] / 60.0, 1)
    out = {
        "date": r["date"],
        "weekday": pacific_weekday(r["date"]),  # #5274: the Pacific weekday, quoted — never derived by the model
        "source": r["source"],
        "device": r.get("device"),
        "modality": r["modality"],
        "weight_bearing": wb,
        "moving_seconds": int(round(r["seconds"])),
        "moving_min": minutes,
        "distance_mi": r.get("distance_mi"),
        "elevation_ft": r.get("elevation_ft"),
        "avg_hr": r.get("avg_hr"),
        "max_hr": r.get("max_hr"),
        "start_utc": r["start"].isoformat() if r.get("start") else None,
        # #5916: the walk-length line is the only flag. Heart rate is a measurement (`avg_hr_basis`), never a grade.
        "flags": {"over_75_min": bool(wb and minutes > WALK_MAX_MIN)},
    }
    if r.get("avg_hr") is not None:
        out["avg_hr_basis"] = r.get("avg_hr_basis") or AVG_HR_BASIS_DEVICE
    if r.get("hr_source"):
        out["hr_source"] = r["hr_source"]
    if r.get("method"):  # #5669: an owner correction says so on every row it rides
        out["method"] = r["method"]
    if r["source"] == "hevy":  # #4412: the join's verdict rides every Hevy row — joined or unknown, never a silent 0
        out["hr_state"], out["hr_coverage"] = r.get("hr_state"), r.get("hr_coverage")
    if r.get("seconds_removed"):
        out["dedup_seconds_removed"] = int(round(r["seconds_removed"]))
    return out


def _monday(day: str) -> str:
    d = parse_day_key(day)
    return (d - timedelta(days=d.weekday())).isoformat() if d else day


def _sum_hr(rows: list[dict[str, Any]], start: str, end: str, *, weight_bearing_only: bool = False) -> float:
    return _hours(sum(r["moving_seconds"] for r in rows if start <= r["date"] <= end and (r["weight_bearing"] or not weight_bearing_only)))


def window(target_date: str) -> dict[str, str]:
    """The days this block reads for a plan on `target_date` — through target − 1, the day the plan is made."""
    end = shift_day_key(target_date, -1)
    return {"start": shift_day_key(end, -(READ_DAYS - 1)), "end": end, "recent_start": shift_day_key(end, -(RECENT_DAYS - 1))}


def build(
    *,
    target_date: str,
    today: str,
    strava_items: list[dict[str, Any]] | None,
    hevy_workouts: list[dict[str, Any]] | None,
    apple_items: Any = walking_volume.NOT_WIRED,
    completeness_inputs: dict[str, list[dict[str, Any]] | None] | None = None,
) -> dict[str, Any]:
    """The `constraint_block.recent_aerobic` block for a plan on `target_date`. Pure.

    `today` is the Pacific day the plan is made: when it is target − 1 (the nightly pre-draft,
    the evening chat) today's activities are IN, and the block says the day is still in progress.
    `apple_items` (#5369): the apple_health day rows over the read (one UTC day past it); a failed
    Apple read (None) makes the totals a floor, as any unreadable source does.
    `completeness_inputs` (#5669): WHOOP + Habitify rows over the read — `walking_volume.completeness`
    over the whole read window; a gap makes the totals a floor and is named under `completeness.gaps`.
    None (the default) is a caller that did not ask: `completeness.status == "not_checked"`."""
    w = window(target_date)
    end = w["end"]
    wired = apple_items is not walking_volume.NOT_WIRED
    s_raw = _strava_rows(strava_items or [])
    a_raw = _apple_rows(apple_items, w["start"], end) if wired else None
    h_rows = _hevy_rows(hevy_workouts or [], strava_items or [])
    hevy_iv = walking_volume.hevy_cardio_intervals(hevy_workouts or [])
    if a_raw is None:
        s_kept, dedup = walking_volume.dedup_strava(s_raw, hevy_iv)
        a_kept: list[dict[str, Any]] = []
    else:
        s_kept, a_kept, dedup = walking_volume.dedup_sources(s_raw, a_raw, hevy_iv)
    for r in s_kept + a_kept:  # the de-dup copies each row it keeps, with `seconds` cut to the unclaimed part
        r["seconds_removed"] = max(0.0, r["seconds_as_recorded"] - r["seconds"])
    sources: tuple[tuple[str, Any], ...] = (("strava", strava_items), ("hevy", hevy_workouts))
    if wired:
        sources += (("apple_health", apple_items),)
    unreadable = [n for n, v in sources if v is None]
    # #5669: the owner's corrections — the weekly layer's rule (`walking_volume.apply_corrections`), never a second one
    signal_inputs, correction_rows = walking_volume._split_inputs(completeness_inputs)
    as_counted = [{**r, "modality": "walking" if r["modality"] in WEIGHT_BEARING else "cycling"} for r in s_kept + a_kept + h_rows]
    corr = walking_volume.apply_corrections(correction_rows, w["start"], end, as_counted, not unreadable)
    c_rows = [_correction_row(c) for c in corr["applied"]]
    rows = sorted((_public_row(r) for r in s_kept + a_kept + h_rows + c_rows), key=lambda r: (r["date"], r["start_utc"] or ""))
    wtd_start = _monday(end)
    prior_start, prior_end = shift_day_key(wtd_start, -7), shift_day_key(wtd_start, -1)
    wtd = _sum_hr(rows, wtd_start, end)
    prior_week = _sum_hr(rows, prior_start, prior_end)
    ramp = float(_WALKING["ramp_hr_per_wk_max"])
    target_wk = float(_WALKING["target_hr_wk"])
    trailing = _sum_hr(rows, shift_day_key(end, -6), end)
    prior7 = _sum_hr(rows, shift_day_key(end, -13), shift_day_key(end, -7))
    recent = [r for r in rows if r["date"] >= w["recent_start"]]
    h48_start = shift_day_key(end, -1)
    over_75_48h = [r for r in recent if r["date"] >= h48_start and r["flags"]["over_75_min"]]
    complete = walking_volume.resolve_gaps(
        walking_volume.completeness(
            window_start=w["start"], window_end=end, counted=as_counted, hevy_intervals=hevy_iv, inputs=signal_inputs
        ),
        corr,
    )
    in_progress = end >= today
    honesty = [f"{n} could not be read — every total below is a FLOOR, never zero hours for {n}" for n in unreadable]
    if in_progress:
        honesty.append(f"{end} is still in progress — its rows are the activities completed so far")
    if dedup["untimed"]:
        honesty.append(f"{dedup['untimed']} Strava activit{'y' if dedup['untimed'] == 1 else 'ies'} carried no timestamp — counted whole")
    honesty.extend(walking_volume.completeness_honesty(complete))
    honesty.extend(walking_volume.correction_honesty(corr))
    return {
        "layer": "recent_aerobic",
        "version": RECENT_AEROBIC_VERSION,
        "state": "read_failed" if strava_items is None and hevy_workouts is None else "read",
        "window": {"start": w["recent_start"], "end": end, "days": RECENT_DAYS, "end_in_progress": in_progress},
        "rows": recent,
        "totals": {
            "weight_bearing_hr_48h": _sum_hr(rows, h48_start, end, weight_bearing_only=True),
            "weight_bearing_hr_72h": _sum_hr(rows, w["recent_start"], end, weight_bearing_only=True),
            "aerobic_hr_72h": _sum_hr(rows, w["recent_start"], end),
            "walks_over_75_min_48h": len(over_75_48h),
            "week_to_date": {
                "start": wtd_start,
                "end": end,
                "hours": wtd,
                "prior_week": {"start": prior_start, "end": prior_end, "hours": prior_week},
                "ramp_hr_per_wk_max": ramp,
                "ramp_ceiling_hr": round(prior_week + ramp, 2),
                "target_hr_wk": target_wk,
                "over_ramp": wtd > prior_week + ramp,
                "over_target": wtd > target_wk,
            },
            "trailing_7d": {"start": shift_day_key(end, -6), "end": end, "hours": trailing},
            "prior_7d": {"start": shift_day_key(end, -13), "end": shift_day_key(end, -7), "hours": prior7},
            "standalone_walks": {
                "min_per_wk": int(_STANDALONE["min_per_wk"]),
                "min_minutes": int(_STANDALONE["min_minutes"]),
                "rule": (
                    "a Strava walk (or the watch's own walk, when the apple rows were read — #5369) whose de-duplicated "
                    "minutes outside every Hevy session (the gym window) reach min_minutes"
                ),
                "trailing_7d": standalone_walks(s_raw, hevy_workouts, shift_day_key(end, -6), end, a_raw, c_rows),
                "prior_7d": standalone_walks(s_raw, hevy_workouts, shift_day_key(end, -13), shift_day_key(end, -7), a_raw, c_rows),
            },
        },
        "totals_are_floor": bool(unreadable) or bool(complete["gaps"]),
        "unreadable_sources": unreadable,
        "completeness": complete,
        "owner_corrections": walking_volume.corrections_public(corr),
        "redlines": {
            "walk_max_min": WALK_MAX_MIN,
            # #5916: no heart-rate cap and no target. The intensity line is the talk test plus RPE.
            "intensity": EASY_EFFORT_CUE,
            "heart_rate": f"avg_hr / max_hr on a row are measurements, each with its `avg_hr_basis`; {HR_NOT_GRADED}",
            "provenance": _WALKING["provenance"],
            "source": "owner_redlines.walking_floor_hr_wk",
        },
        "joints_trigger": {"weight_bearing_hr_48h": WEIGHT_BEARING_48H_TRIGGER_HR, **TRIGGER_PROVENANCE},
        "dedup": dedup,
        "honesty": honesty,
    }


# ── what the block says to the drafter and to the critic ──────────────────────────────
def gap_days(block: dict[str, Any] | None, start: str, end: str) -> list[str]:
    """The days in [start, end] the walk-signal check (#5669) says hold a walk no source counted."""
    gaps = ((block or {}).get("completeness") or {}).get("gaps") or []
    return sorted({g["date"] for g in gaps if start <= str(g.get("date") or "") <= end})


def aerobic_minutes_7d(block: dict[str, Any] | None) -> float | None:
    """The generator's `z2_minutes_7d` (#4410): the block's trailing-7-day walking + cycling hours, in
    minutes — the ONE recent-aerobic quantity, never a second count. None = UNKNOWN (ADR-104): an
    unread block, or a trailing week that is a FLOOR — a source was unreadable, or a walk signal in
    those 7 days has no counted walk (#5669) — because a floor below the portfolio floor cannot say
    he is below it. A gap only in the prior week leaves the trailing week's count exact. Never 0
    for an unread week."""
    if not block or block.get("state") != "read":
        return None
    t7 = (block.get("totals") or {}).get("trailing_7d") or {}
    floor_unread = block.get("unreadable_sources") if "unreadable_sources" in block else block.get("totals_are_floor")
    if floor_unread or gap_days(block, str(t7.get("start") or ""), str(t7.get("end") or "")):
        return None
    hours = t7.get("hours")
    return None if hours is None else round(float(hours) * 60.0, 1)


def last_cardio_block_hr(block: dict[str, Any] | None) -> dict[str, Any] | None:
    """The most recent Hevy cardio block in the block's rows WITH its joined heart rate (#4412), or None.

    None = no Hevy cardio block in the window, or none whose HR joined — unknown, never a 0 bpm.

    #5916 (owner ruling 2026-11-13): the average is a MEASUREMENT with its basis and is graded against nothing.
    `over_ceiling` stays in the shape as None ("not graded") only because `coach.critics_aerobic` (another lane's
    file) reads the key by name; drop it with that reader."""
    rows = [r for r in (block or {}).get("rows") or [] if r.get("source") == "hevy" and r.get("hr_state") == "joined"]
    if not rows:
        return None
    r = max(rows, key=lambda x: (x.get("date") or "", x.get("start_utc") or ""))
    return {
        "date": r["date"],
        "weekday": pacific_weekday(r["date"]),  # #5274: last_cardio_block_hr
        "modality": r["modality"],
        "avg_hr": r["avg_hr"],
        "max_hr": r.get("max_hr"),
        "hr_coverage": r.get("hr_coverage"),
        "avg_hr_basis": r.get("avg_hr_basis") or AVG_HR_BASIS_JOINED.format(basis="#4412 join"),
        "over_ceiling": None,
    }


def legs_loaded(block: dict[str, Any] | None) -> tuple[bool | None, str]:
    """(True when the last 48 h carried heavy weight-bearing volume, why). None = unread."""
    if not block or block.get("state") != "read":
        return None, "recent aerobic load was not read"
    t = block.get("totals") or {}
    wb, over = float(t.get("weight_bearing_hr_48h") or 0.0), int(t.get("walks_over_75_min_48h") or 0)
    if wb >= WEIGHT_BEARING_48H_TRIGGER_HR or over:
        parts = [f"{wb} h weight-bearing in 48 h (trigger {WEIGHT_BEARING_48H_TRIGGER_HR} h, population-derived)"]
        if over:
            parts.append(f"{over} walk(s) over the {WALK_MAX_MIN}-min redline")
        return True, "; ".join(parts)
    end = str((block.get("window") or {}).get("end") or "")
    missed = gap_days(block, shift_day_key(end, -1), end) if end else []
    if missed:  # #5669: the 48 h total is a floor — "fresh" is exactly what an uncounted walk could falsify
        return None, (
            f"{wb} h weight-bearing in 48 h is a FLOOR — a walk signal on {', '.join(missed)} has no counted walk, so fresh legs "
            "cannot be claimed"
        )
    return False, f"{wb} h weight-bearing in 48 h, no walk over {WALK_MAX_MIN} min"


def is_lower(archetype: Any) -> bool:
    """A lower-body session: the `lower` / `legs` archetypes, or a charter `split.sequence` name that opens with
    'lower' (#5069). One definition, `cardio_menu.is_lower` (#5076), shared with the cardio menu's placement."""
    from training import cardio_menu

    return cardio_menu.is_lower(archetype)


def cardio_pick(block: dict[str, Any] | None, archetype: Any, target_date: str | None = None) -> dict[str, Any]:
    """The cardio modality for a session — picked from the block, never copied from the last session.

    A lower session, a heavy walking weekend, or an unread block gets cycling (recumbent, the
    program's knee-sparing substitute); the treadmill only when the legs are fresh.

    #5916 (owner ruling 2026-11-13): the pick carries NO heart-rate field on any day. Its `intensity` is the
    redline's line, the talk test plus RPE (`EASY_EFFORT_CUE`).
    #5000: with `target_date`, on a day a standing constraint forbids HR prescriptions
    (`training.standing_constraints`) the pick also names the constraint (`hr_fields_dropped_by`)."""
    loaded, why = legs_loaded(block)
    if is_lower(archetype):
        modality, reason = "cycling", f"a lower session — the legs are already the session's work ({why})"
    elif loaded is None:
        modality, reason = "cycling", f"{why} — the knee-sparing default, never a guessed-fresh treadmill"
    elif loaded:
        modality, reason = "cycling", why
    else:
        modality, reason = "treadmill", f"the legs are fresh: {why}"
    pick = {
        "movement_key": modality,
        "modality": "cycling (recumbent)" if modality == "cycling" else "treadmill",
        "intensity": EASY_EFFORT_CUE,
        "reason": reason,
        "rule": "lower session or loaded legs -> cycling; treadmill only when the legs are fresh (#4387)",
    }
    if target_date is None:
        return pick
    return standing_constraints.talk_test_pick(pick, standing_constraints.active_constraint(target_date))


def _standalone_half(block: dict[str, Any]) -> tuple[str, str]:
    """(state, detail) for the OD7 walk-count half of walking_collapse (#4503)."""
    sw = (block.get("totals") or {}).get("standalone_walks")
    if not sw:
        return "unknown", "standalone walks were not counted on this block"
    if "strava" in (block.get("unreadable_sources") or []):
        return "unknown", "standalone walks: Strava could not be read"
    t, need = sw["trailing_7d"], int(sw["min_per_wk"])
    what = f"{t['count']} standalone walk(s) ≥ {sw['min_minutes']} min outside a gym window {t['start']}..{t['end']} (report under {need})"
    if t["count"] >= need:
        return "clear", what
    if t["count"] + int(t["untimed"]) >= need:
        return "unknown", what + f"; {t['untimed']} untimed walk(s) could not be placed against a gym window"
    missed = gap_days(block, t["start"], t["end"])
    if missed:  # #5669: an uncounted walk could be the missing standalone walk
        return "unknown", what + f"; a walk signal on {', '.join(missed)} has no counted walk — the count is a floor"
    return "tripped", what


def collapse_actuator(state: str, designation: dict[str, Any] | None) -> dict[str, Any]:
    """The OD7 actuator MARK on the walking_collapse row (#4503). It SENDS NOTHING: it states that the
    designated human would be the same-day actuator, and whether the private config designates one.
    `designation` is `coach.named_human_contact.designation_status`'s identity-free answer, or None when
    it was not read (the config is read only on a tripped row, so an ordinary night never touches it)."""
    spec = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "walking_collapse")["actuator"]
    d = designation or {"designation": "not_read", "armed": None}
    return {
        **spec,
        "designation": d["designation"],
        "armed": d.get("armed"),
        "would_actuate": state == "tripped" and d["designation"] == "designated",
        "note": "a mark only — no message is sent from this row; the contact path is coach.named_human_contact's (disengagement only, #4063 A)",
    }


def weekly_reports(block: dict[str, Any] | None, collapse_pct: float) -> dict[str, tuple[str, Any, str]]:
    """(state, observed, detail) for the two REPORT-ONLY walking tripwires — never a veto (#4387).

    walking_collapse has two halves since #4503 OD7: the hours week-over-week, and the standalone walk
    count. Either tripped trips it; otherwise either unknown leaves it unknown; `observed` stays the
    hours ratio (None when it has no ratio)."""
    if not block or block.get("state") != "read":
        why = "the recent-aerobic read failed or was not supplied"
        return {"walking_collapse": ("unknown", None, why), "walking_overshoot": ("unknown", None, why)}
    t = block["totals"]
    this, last = t["trailing_7d"]["hours"], t["prior_7d"]["hours"]
    floor = " (a FLOOR — a source was unreadable or a walk signal has no counted walk)" if block.get("totals_are_floor") else ""
    # #5669: a gap makes its week's hours a floor. A floored THIS week can fake a collapse; a floored
    # LAST week can hide one — each makes only the verdict it could falsify unknown.
    gap_this = gap_days(block, t["trailing_7d"]["start"], t["trailing_7d"]["end"])
    gap_last = gap_days(block, t["prior_7d"]["start"], t["prior_7d"]["end"])
    if last > 0:
        wow = round((this - last) / last * 100.0, 1)
        hours_state = "tripped" if wow < -collapse_pct else "clear"
        if (hours_state == "tripped" and gap_this) or (hours_state == "clear" and gap_last):
            hours_state = "unknown"
            floor += f"; uncounted walk signal(s) on {', '.join(gap_this if gap_this else gap_last)} (#5669)"
        hours = (
            hours_state,
            wow,
            f"walking+cycling {this} h vs {last} h the 7 days before ({wow:+}%, report at -{collapse_pct:g}%){floor}",
        )
    else:
        hours = ("unknown", None, f"the prior 7 days read 0 h — no week-over-week ratio; trailing 7 d {this} h{floor}")
    walks_state, walks_detail = _standalone_half(block)
    states = (hours[0], walks_state)
    state = "tripped" if "tripped" in states else ("unknown" if "unknown" in states else "clear")
    collapse = (state, hours[1], f"{hours[2]}; {walks_detail}")
    wk = t["week_to_date"]
    over = [f"above the {wk['target_hr_wk']:g} h target" if wk["over_target"] else None]
    over.append(f"above last week + the {wk['ramp_hr_per_wk_max']:g} h ramp ({wk['ramp_ceiling_hr']} h)" if wk["over_ramp"] else None)
    named = [s for s in over if s]
    detail = f"week to date {wk['start']}..{wk['end']}: {wk['hours']} h" + (" — " + "; ".join(named) if named else "") + floor
    overshoot = "tripped" if named else "clear"
    # #5669: a floored week-to-date can hide an overshoot; a floored prior week lowers the ramp ceiling and
    # can fake one that rests on the ramp alone. Only the verdict the missing walk could flip goes unknown.
    gap_wtd = gap_days(block, wk["start"], wk["end"])
    gap_prior = gap_days(block, wk["prior_week"]["start"], wk["prior_week"]["end"])
    if (overshoot == "clear" and gap_wtd) or (overshoot == "tripped" and not wk["over_target"] and gap_prior):
        overshoot = "unknown"
        detail += f"; uncounted walk signal(s) on {', '.join(gap_wtd or gap_prior)} (#5669)"
    return {"walking_collapse": collapse, "walking_overshoot": (overshoot, wk["hours"], detail)}
