"""recent_aerobic.py — what his legs did in the last three days, per activity (#4387).

WHY THIS EXISTS

On 2026-09-27 the coach planned Mon 09-28: trap-bar + squat, then 60 min of incline treadmill.
Its only aerobic input was `constraint_block.walking` — a 7-day TOTAL in hours, over a window
that ended at target − 2. It never saw Sunday, and it had no per-walk duration and no heart rate.
Strava held 4.4 h / 13.4 mi of outdoor walking on 09-26..27 — walks of 102 and 165 min at
~116 bpm average, both over the walking redlines (≤ 75 min per walk, ≤ 105 bpm). No critic saw
them; the red team approved the treadmill (`CORRECTION#2026-09-27#5a60fd05`).

A total cannot say "yesterday was 2¾ hours on foot". This block can:

  * ONE ROW PER ACTIVITY over the last three days through target − 1 — date, source, device,
    modality (walk / treadmill / cycling / recumbent), moving time, distance, elevation, average
    and max HR — each flagged against `owner_redlines.walking_floor_hr_wk` (`over_75_min`,
    `avg_hr_over_ceiling`);
  * the SAME sources and the SAME time de-dup as the weekly walking hours (#3930/#4068): Strava
    Walk/Hike/Ride UNION the Hevy treadmill/walking/cycling blocks Strava cannot see, a
    WHOOP/Garmin walk recorded over a Hevy cardio session's minutes counted once. The primitives
    are `training.walking_volume`'s — this module adds per-row detail, never a second rule;
  * weight-bearing hours in the last 48 h and 72 h, and week-to-date hours against the ramp
    (`ramp_hr_per_wk_max`) and the target (`target_hr_wk`).

It is PURE: the partitions are read by `mcp.shared_quantities.recent_aerobic_layer`, the one
module that owns the walking definition, and handed in. `None` for a source means it could not
be read — never zero hours.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from common.pacific_time import parse_day_key, shift_day_key

from training import cardio_hr, owner_redlines, walking_volume

RECENT_AEROBIC_VERSION = "recent-aerobic@1.0.0"

RECENT_DAYS = 3  # the rows: target − 3 .. target − 1 (tonight's plan sees today)
READ_DAYS = 14  # the partition read: covers the prior Mon–Sun week and the trailing-7 comparison
WEIGHT_BEARING = ("walk", "treadmill")
_WALKING = owner_redlines.REDLINES["walking_floor_hr_wk"]
# "2–3 per day, none over 75 min" — `walking_floor_hr_wk.walks` (owner-history). A test holds this
# number equal to the phrase in the redline, so the two cannot drift apart.
WALK_MAX_MIN = 75
HR_CEILING_BPM = int(_WALKING["hr_ceiling_bpm"])
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
                }
            )
    return rows


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


def _public_row(r: dict[str, Any]) -> dict[str, Any]:
    wb = r["modality"] in WEIGHT_BEARING
    minutes = round(r["seconds"] / 60.0, 1)
    out = {
        "date": r["date"],
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
        "flags": {
            "over_75_min": bool(wb and minutes > WALK_MAX_MIN),
            "avg_hr_over_ceiling": None if r.get("avg_hr") is None else float(r["avg_hr"]) > HR_CEILING_BPM,
        },
    }
    if r.get("hr_source"):
        out["hr_source"] = r["hr_source"]
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
) -> dict[str, Any]:
    """The `constraint_block.recent_aerobic` block for a plan on `target_date`. Pure.

    `today` is the Pacific day the plan is made: when it is target − 1 (the nightly pre-draft,
    the evening chat) today's activities are IN, and the block says the day is still in progress."""
    w = window(target_date)
    end = w["end"]
    s_raw = _strava_rows(strava_items or [])
    h_rows = _hevy_rows(hevy_workouts or [], strava_items or [])
    s_kept, dedup = walking_volume.dedup_strava(s_raw, walking_volume.hevy_cardio_intervals(hevy_workouts or []))
    for r in s_kept:  # dedup_strava copies each row it keeps, with `seconds` cut to the unclaimed part
        r["seconds_removed"] = max(0.0, r["seconds_as_recorded"] - r["seconds"])
    rows = sorted((_public_row(r) for r in s_kept + h_rows), key=lambda r: (r["date"], r["start_utc"] or ""))
    unreadable = [n for n, v in (("strava", strava_items), ("hevy", hevy_workouts)) if v is None]
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
    in_progress = end >= today
    honesty = [f"{n} could not be read — every total below is a FLOOR, never zero hours for {n}" for n in unreadable]
    if in_progress:
        honesty.append(f"{end} is still in progress — its rows are the activities completed so far")
    if dedup["untimed"]:
        honesty.append(f"{dedup['untimed']} Strava activit{'y' if dedup['untimed'] == 1 else 'ies'} carried no timestamp — counted whole")
    return {
        "layer": "recent_aerobic",
        "version": RECENT_AEROBIC_VERSION,
        "state": "read_failed" if len(unreadable) == 2 else "read",
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
        },
        "totals_are_floor": bool(unreadable),
        "unreadable_sources": unreadable,
        "redlines": {
            "walk_max_min": WALK_MAX_MIN,
            "hr_ceiling_bpm": HR_CEILING_BPM,
            "provenance": _WALKING["provenance"],
            "source": "owner_redlines.walking_floor_hr_wk",
        },
        "joints_trigger": {"weight_bearing_hr_48h": WEIGHT_BEARING_48H_TRIGGER_HR, **TRIGGER_PROVENANCE},
        "dedup": dedup,
        "honesty": honesty,
    }


# ── what the block says to the drafter and to the critic ──────────────────────────────
def aerobic_minutes_7d(block: dict[str, Any] | None) -> float | None:
    """The generator's `z2_minutes_7d` (#4410): the block's trailing-7-day walking + cycling hours, in
    minutes — the ONE recent-aerobic quantity, never a second count. None = UNKNOWN (ADR-104): an
    unread block, or totals that are a FLOOR because a source was unreadable (a floor below the
    portfolio floor cannot say he is below it). Never 0 for an unread week."""
    if not block or block.get("state") != "read" or block.get("totals_are_floor"):
        return None
    hours = ((block.get("totals") or {}).get("trailing_7d") or {}).get("hours")
    return None if hours is None else round(float(hours) * 60.0, 1)


def last_cardio_block_hr(block: dict[str, Any] | None) -> dict[str, Any] | None:
    """The most recent Hevy cardio block in the block's rows WITH its joined heart rate (#4412), or None.

    None = no Hevy cardio block in the window, or none whose HR joined — unknown, never a 0 bpm."""
    rows = [r for r in (block or {}).get("rows") or [] if r.get("source") == "hevy" and r.get("hr_state") == "joined"]
    if not rows:
        return None
    r = max(rows, key=lambda x: (x.get("date") or "", x.get("start_utc") or ""))
    return {
        "date": r["date"],
        "modality": r["modality"],
        "avg_hr": r["avg_hr"],
        "max_hr": r.get("max_hr"),
        "hr_coverage": r.get("hr_coverage"),
        "over_ceiling": r["avg_hr"] is not None and float(r["avg_hr"]) > HR_CEILING_BPM,
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
    return False, f"{wb} h weight-bearing in 48 h, no walk over {WALK_MAX_MIN} min"


def is_lower(archetype: Any) -> bool:
    return str(archetype or "").strip().lower() in ("lower", "legs", "lower-heavy", "lower-volume")


def cardio_pick(block: dict[str, Any] | None, archetype: Any) -> dict[str, Any]:
    """The cardio modality for a session — picked from the block, never copied from the last session.

    A lower session, a heavy walking weekend, or an unread block gets cycling (recumbent, the
    program's knee-sparing substitute); the treadmill only when the legs are fresh."""
    loaded, why = legs_loaded(block)
    if is_lower(archetype):
        modality, reason = "cycling", f"a lower session — the legs are already the session's work ({why})"
    elif loaded is None:
        modality, reason = "cycling", f"{why} — the knee-sparing default, never a guessed-fresh treadmill"
    elif loaded:
        modality, reason = "cycling", why
    else:
        modality, reason = "treadmill", f"the legs are fresh: {why}"
    return {
        "movement_key": modality,
        "modality": "cycling (recumbent)" if modality == "cycling" else "treadmill",
        "hr_ceiling_bpm": HR_CEILING_BPM,
        "reason": reason,
        "rule": "lower session or loaded legs -> cycling; treadmill only when the legs are fresh (#4387)",
    }


def weekly_reports(block: dict[str, Any] | None, collapse_pct: float) -> dict[str, tuple[str, Any, str]]:
    """(state, observed, detail) for the two REPORT-ONLY walking tripwires — never a veto (#4387)."""
    if not block or block.get("state") != "read":
        why = "the recent-aerobic read failed or was not supplied"
        return {"walking_collapse": ("unknown", None, why), "walking_overshoot": ("unknown", None, why)}
    t = block["totals"]
    this, last = t["trailing_7d"]["hours"], t["prior_7d"]["hours"]
    floor = " (a FLOOR — a source was unreadable)" if block.get("totals_are_floor") else ""
    if last > 0:
        wow = round((this - last) / last * 100.0, 1)
        state = "tripped" if wow < -collapse_pct else "clear"
        collapse = (state, wow, f"walking+cycling {this} h vs {last} h the 7 days before ({wow:+}%, report at -{collapse_pct:g}%){floor}")
    else:
        collapse = ("unknown", None, f"the prior 7 days read 0 h — no week-over-week ratio; trailing 7 d {this} h{floor}")
    wk = t["week_to_date"]
    over = [f"above the {wk['target_hr_wk']:g} h target" if wk["over_target"] else None]
    over.append(f"above last week + the {wk['ramp_hr_per_wk_max']:g} h ramp ({wk['ramp_ceiling_hr']} h)" if wk["over_ramp"] else None)
    named = [s for s in over if s]
    detail = f"week to date {wk['start']}..{wk['end']}: {wk['hours']} h" + (" — " + "; ".join(named) if named else "") + floor
    return {"walking_collapse": collapse, "walking_overshoot": ("tripped" if named else "clear", wk["hours"], detail)}
