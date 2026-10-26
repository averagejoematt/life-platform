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
Hevy session can never be counted twice: it does not match on the Strava side at all.

THE DE-DUP RULING (#4068, verified against live DDB 2026-09-22, window 2026-09-15..21)

The 09-19 ruling above was half the story. The seven Strava `Walk` activities were NOT all
separate outdoor walks: WHOOP auto-detects the treadmill/bike block INSIDE a Hevy session
and posts it to Strava as its own `Walk` ("Afternoon Walk", device WHOOP). In 15–21 Sep five
of the six counted Strava walks (1.02 + 0.97 + 0.98 + 1.05 + 1.73 = 5.75 h) start and end
inside a Hevy session that already carries the same treadmill/walking/cycling block — the
09-21 one is 22:38–00:22 UTC inside a 22:35–00:45 Engine session holding 1.0 h treadmill +
0.75 h cycling. Counted twice, that read 15.82 h for a week whose de-duplicated volume is
10.07 h. Garmin and WHOOP can ALSO both record one outdoor walk.

So the union is now de-duplicated IN TIME, one rule for both overlaps:
  * a Hevy session carrying a counted cardio block claims its [start_time, end_time]
    interval first — its blocks are the logged record, with the modality named;
  * then Strava's counted activities, longest first, each counting only the part of its
    [start_date, start_date + elapsed] interval no earlier claim covers (moving time scaled
    by the uncovered fraction of elapsed time).
A record without a timestamp cannot be placed in time; it is counted whole and the output
says how many such records the de-dup could not see (`dedup.untimed`).

THE WATCH BACKSTOP (#5369/#5371, owner acts 2026-10-26)

Until 2026-10-26 every walk reached this layer through Strava, because WHOOP pushed what it
detected there. From that day WHOOP no longer shares to Strava and the watch uploads its own
workouts — but an outdoor walk the watch does not upload would vanish from a Strava-only read.
So a caller may hand in the apple_health day rows (`apple_items`): the watch's OWN walking and
cycling workouts in the owner-only `apple_workouts` map join the union as a third source, last
in the same time de-dup — Hevy claims first, then Strava, then Apple, each counting only the
time no earlier claim covers. A walk only the watch recorded counts; a walk the watch also
uploaded to Strava counts once. A HealthKit workout another app wrote (Hevy, the pliability
app, WHOOP) is that app's record, not the watch's, and is not read here (`apple_workout_source`).
History keeps its WHOOP copies in Strava and the future will not; the rule needs neither.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from common.pacific_time import pacific_date_of, pacific_weekday, parse_iso_utc

WALKING_VOLUME_VERSION = (
    "walking-volume@1.2.0"  # 1.1.0 (#4068): time de-dup across Strava devices and against Hevy sessions; 1.2.0 (#5369): the watch backstop
)

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

# HealthKit workout names as Health Auto Export sends them (lower-cased) → modality. The walking
# and cycling half of `training.workout_identity.APPLE_FAMILY`, which builds on this map so the
# two layers share one vocabulary ("outdoor cycling" is the name HAE sends for a watch ride, live
# raw archive 2026-10-21; "indoor cycling" the watch's gym-bike workout, 2026-10-25).
APPLE_COUNTED_NAMES: dict[str, str] = {
    "walking": "walking",
    "outdoor walk": "walking",
    "indoor walk": "walking",
    "hiking": "walking",
    "cycling": "cycling",
    "outdoor cycle": "cycling",
    "indoor cycle": "cycling",
    "outdoor cycling": "cycling",
    "indoor cycling": "cycling",
}
APPLE_SOURCE = "apple_health"
APPLE_WORKOUTS_FIELD = "apple_workouts"  # owner-only (privacy.field_tiers); read for start/end/duration/name/source only

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
            start = _parse_utc(a.get("start_date"))
            elapsed = _float(a.get("elapsed_time_seconds") or a.get("elapsed_time"))
            counted.append(
                {
                    "date": day,
                    "source": "strava",
                    "modality": modality,
                    "label": a.get("name") or label,
                    "device": a.get("device_name"),
                    "seconds": _float(a.get("moving_time_seconds") or a.get("moving_time")),
                    "start": start,
                    "end": (start + timedelta(seconds=elapsed)) if (start is not None and elapsed > 0) else None,
                }
            )
    return counted, skipped


def _parse_utc(v: Any) -> datetime | None:
    """A UTC instant from Strava's `start_date` / Hevy's `start_time` (both ISO-8601 UTC on the
    live rows). NOT `start_date_local`: that one carries a `Z` it has not earned."""
    if not isinstance(v, str) or not v:
        return None
    return parse_iso_utc(v)


_APPLE_DEVICE_TOKENS = ("apple watch", "iphone", "ipad")


def apple_workout_source(w: dict[str, Any]) -> str:
    """`apple_health` for a workout the watch/phone recorded (or one with no origin on record);
    `apple_health/<origin>` for one another app wrote INTO HealthKit — Hevy's own lift
    (`com.hevyapp.hevy`), the pliability app's mobility session (`com.romwodllc.romwod`), a
    WHOOP workout — so the identity resolver can fold it into that app's record, never count it
    as a second watch session (#5369). An identifier under `com.apple.` is the watch/phone."""
    src = w.get("source")
    name = str((src.get("name") if isinstance(src, dict) else src) or "").replace("\xa0", " ").strip().lower()
    ident = str((src.get("identifier") if isinstance(src, dict) else "") or "").strip().lower()
    if ident.startswith("com.apple.") or not name or any(tok in name for tok in _APPLE_DEVICE_TOKENS):
        return APPLE_SOURCE
    return APPLE_SOURCE + "/" + "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")


def apple_workout_records(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Bare workout records, or apple_health DATE# day rows whose `apple_workouts` map
    (`ingestion.health_auto_export_workouts`, #4973) holds one summary per HAE workout id. A
    summary without its own `id` takes the map key; one id seen twice (a neighbouring row) is
    one record."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items or []:
        nested = item.get(APPLE_WORKOUTS_FIELD)
        pairs = list(nested.items()) if isinstance(nested, dict) else [(None, item)]
        for key, w in pairs:
            if not isinstance(w, dict):
                continue
            wid = str(w.get("id") or key or "")
            if wid and wid in seen:
                continue
            if wid:
                seen.add(wid)
            out.append(w if w.get("id") or not wid else {**w, "id": wid})
    return out


def apple_sessions(
    items: list[dict[str, Any]] | None, window_start: str | None = None, window_end: str | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """(the watch's own counted walking/cycling workouts, names seen and NOT counted).

    Only `apple_workout_source(w) == "apple_health"` — the watch's own record. The rows are keyed by
    the UTC day of the start, so a caller reads one UTC day past its window and this keeps the
    workouts whose PACIFIC start date lies in [window_start, window_end] (either bound optional).
    No heart rate, distance, route or device name leaves this function — only the modality, the
    workout's name as its label, its duration and its interval."""
    counted: list[dict[str, Any]] = []
    skipped: list[str] = []
    for w in apple_workout_records(items):
        if apple_workout_source(w) != APPLE_SOURCE:
            continue
        name = str(w.get("name") or "").strip()
        start, end = _parse_utc(w.get("start")), _parse_utc(w.get("end"))  # ISO or HAE's 'YYYY-MM-DD HH:MM:SS -0700'
        day = pacific_date_of(str(w.get("start") or "")) or ""
        if (window_start and day and day < window_start) or (window_end and day and day > window_end):
            continue
        modality = APPLE_COUNTED_NAMES.get(name.lower())
        if not modality:
            if name and name not in skipped:
                skipped.append(name)
            continue
        seconds = _float(w.get("duration")) or _float(w.get("duration_min")) * 60.0
        if not seconds and start is not None and end is not None:
            seconds = (end - start).total_seconds()
        if start is not None and end is None and seconds > 0:
            end = start + timedelta(seconds=seconds)
        counted.append(
            {
                "date": day,
                "source": APPLE_SOURCE,
                "modality": modality,
                "label": name,
                "device": "apple_watch",
                "seconds": seconds,
                "start": start,
                "end": end,
            }
        )
    return counted, skipped


def hevy_cardio_intervals(workouts: list[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    """[start_time, end_time] of every Hevy session that carries a COUNTED cardio block.

    These claim their time first in the de-dup: the block inside is the logged record, with
    its modality named, and any Strava walk recorded over the same minutes is that block seen
    a second time by a wrist sensor (#4068)."""
    out: list[tuple[datetime, datetime]] = []
    for w in workouts or []:
        start, end = _parse_utc(w.get("start_time")), _parse_utc(w.get("end_time"))
        if start is None or end is None or end <= start:
            continue
        for ex in w.get("exercises") or []:
            name = (ex.get("name") or ex.get("exercise_name") or "").strip()
            if _modality_for_hevy(name) and any(_float(s.get("duration_sec") or s.get("duration_seconds")) for s in ex.get("sets") or []):
                out.append((start, end))
                break
    return out


def _uncovered_seconds(start: datetime, end: datetime, claimed: list[tuple[datetime, datetime]]) -> float:
    """Seconds of [start, end] that no interval in `claimed` covers."""
    covered = 0.0
    spans = sorted((max(a, start), min(b, end)) for a, b in claimed if a < end and b > start)
    cur_a: datetime | None = None
    cur_b: datetime | None = None
    for a, b in spans:
        if cur_b is None or a > cur_b:
            if cur_a is not None and cur_b is not None:
                covered += (cur_b - cur_a).total_seconds()
            cur_a, cur_b = a, b
        elif b > cur_b:
            cur_b = b
    if cur_a is not None and cur_b is not None:
        covered += (cur_b - cur_a).total_seconds()
    return max(0.0, (end - start).total_seconds() - covered)


def uncovered_seconds(start: datetime, end: datetime, claimed: list[tuple[datetime, datetime]]) -> float:
    """Seconds of [start, end] that no interval in `claimed` covers (the #4068 primitive, public for
    `training.zone2_minutes`' cross-session claim, #5369)."""
    return _uncovered_seconds(start, end, claimed)


_WHY = {
    "strava": "overlaps a Hevy cardio session or a longer Strava activity already counted",
    APPLE_SOURCE: "overlaps a Hevy cardio session, a Strava activity or a longer watch workout already counted",
}


def _claim_in_time(
    records: list[dict[str, Any]], claimed: list[tuple[datetime, datetime]], source: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """(kept, removed, untimed) — each record, longest first, keeps only the moving time proportional
    to the part of its elapsed interval nothing in `claimed` covers; its interval then joins `claimed`
    (mutated). An untimed record is kept whole."""
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    untimed = 0
    for c in sorted(records, key=lambda c: -c["seconds"]):
        start, end = c.get("start"), c.get("end")
        if start is None or end is None:
            untimed += 1
            kept.append(c)
            continue
        elapsed = (end - start).total_seconds()
        free = _uncovered_seconds(start, end, claimed)
        keep_s = c["seconds"] * (free / elapsed) if elapsed > 0 else c["seconds"]
        if keep_s < c["seconds"] - 0.5:
            entry = {
                "date": c["date"],
                "weekday": pacific_weekday(c["date"]),  # #5274: today.dedup / walking.dedup / recent_aerobic.dedup removed[]
                "label": c["label"],
                "device": c.get("device"),
                "hours_removed": _hours(c["seconds"] - keep_s),
                "why": _WHY[source],
            }
            if source != "strava":
                entry["source"] = source
            removed.append(entry)
        claimed.append((start, end))
        if keep_s > 0.5:
            kept.append({**c, "seconds": keep_s})
    return kept, removed, untimed


def _dedup_record(removed: list[dict[str, Any]], untimed: int, with_apple: bool) -> dict[str, Any]:
    record = {
        "rule": "Hevy cardio sessions claim their interval first; Strava activities, longest first, count only unclaimed time",
        "removed": sorted(removed, key=lambda r: r["date"]),
        "hours_removed": _hours(sum(float(r["hours_removed"]) * 3600.0 for r in removed)),
        "untimed": untimed,
    }
    if with_apple:
        record["apple_rule"] = "then the watch's own workouts, longest first, count only the time Hevy and Strava left unclaimed (#5369)"
    return record


def dedup_strava(
    strava_counted: list[dict[str, Any]], hevy_intervals: list[tuple[datetime, datetime]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(Strava sessions with overlapping seconds removed, the de-dup record) — the #4068 rule.

    Hevy sessions carrying counted cardio claim their intervals first; then Strava's counted
    activities, longest first, each keep only the moving time proportional to the part of
    their elapsed interval nothing earlier claimed. One rule covers both overlaps the live
    record carries: a WHOOP walk inside a Hevy treadmill session, and a Garmin + WHOOP pair
    recording one outdoor walk. Untimed activities are kept whole and counted in `untimed`."""
    kept, removed, untimed = _claim_in_time(strava_counted, list(hevy_intervals), "strava")
    return kept, _dedup_record(removed, untimed, with_apple=False)


def dedup_sources(
    strava_counted: list[dict[str, Any]],
    apple_counted: list[dict[str, Any]],
    hevy_intervals: list[tuple[datetime, datetime]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """(Strava kept, Apple kept, the de-dup record) — `dedup_strava`'s rule with the watch's own
    workouts LAST (#5369): Hevy claims, then Strava (longest first), then Apple (longest first),
    each counting only the time every earlier claim left free."""
    claimed = list(hevy_intervals)
    s_kept, s_removed, s_untimed = _claim_in_time(strava_counted, claimed, "strava")
    a_kept, a_removed, a_untimed = _claim_in_time(apple_counted, claimed, APPLE_SOURCE)
    return s_kept, a_kept, _dedup_record(s_removed + a_removed, s_untimed + a_untimed, with_apple=True)


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


#: `apple_items` default: the caller did not wire the watch backstop (distinct from None = the read failed).
NOT_WIRED: Any = object()


def build(
    *,
    window_start: str,
    window_end: str,
    strava_items: list[dict[str, Any]] | None,
    hevy_workouts: list[dict[str, Any]] | None,
    apple_items: Any = NOT_WIRED,
) -> dict[str, Any]:
    """The derived walking-volume layer: Strava UNION Hevy cardio blocks, in HOURS.

    `None` for either argument means the source could not be READ — which is not zero hours.
    An unreadable or silent source makes the total a FLOOR (`total_is_floor`) and says so in
    `honesty`; it never quietly contributes 0.

    `apple_items` (#5369, the watch backstop): the apple_health day rows over the window (one UTC
    day past it — see `apple_sessions`). The watch's own walking/cycling workouts join LAST in the
    time de-dup. Unlike Strava and Hevy, an Apple read with nothing counted is ordinary (a watch
    workout only adds what no other source holds) and never makes the total a floor; a FAILED
    Apple read (None) does, because a walk only the watch recorded could be missing.
    """
    s_raw, s_skipped = strava_sessions(strava_items or [])
    h_counted, h_skipped = hevy_sessions(hevy_workouts or [])
    wired = apple_items is not NOT_WIRED
    a_raw, a_skipped = apple_sessions(apple_items or [], window_start, window_end) if wired else ([], [])
    if wired:
        s_counted, a_counted, dedup = dedup_sources(s_raw, a_raw, hevy_cardio_intervals(hevy_workouts or []))
    else:
        s_counted, dedup = dedup_strava(s_raw, hevy_cardio_intervals(hevy_workouts or []))
        a_counted = []

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
    if wired and apple_items is None:
        by_source[APPLE_SOURCE] = _source_block(None, [], [])
        silent.append(APPLE_SOURCE)
    elif wired:
        # no counted watch workout is the ordinary case, never a silent source
        by_source[APPLE_SOURCE] = (
            _source_block(apple_items, a_counted, a_skipped)
            if a_raw
            else {"status": "no_records", "hours": None, "sessions": 0, "by_modality": {}, "not_counted": a_skipped}
        )
        if a_raw:
            contributing.append(by_source[APPLE_SOURCE])

    every = s_counted + h_counted + a_counted
    total_hr = _hours(sum(c["seconds"] for c in every)) if contributing else None
    by_modality = {m: _hours(sum(c["seconds"] for c in every if c["modality"] == m)) for m in MODALITIES}

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
    if dedup["untimed"]:
        honesty.append(
            f"{dedup['untimed']} Strava activit{'y' if dedup['untimed'] == 1 else 'ies'} carried no start timestamp — the "
            "cross-device de-dup could not place them in time, so they are counted whole"
        )

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
            "title, and those types are not counted on the Strava side. A WHOOP- or Garmin-detected Walk recorded "
            "over the same minutes as a Hevy cardio session, or two devices recording one walk, is de-duplicated IN "
            "TIME so the union cannot double-count it (#4068; live 2026-09-15..21: 5.75 h of WHOOP walks sat inside "
            "Hevy treadmill sessions)."
        ),
        "dedup": dedup,
        "excluded_proxies": [dict(STEPS_EXCLUSION)],
        "derived_steps_estimate": derived_steps_estimate(by_modality.get("walking") if contributing else None),
        "honesty": honesty,
    }


def walking_minutes_for_day(
    *,
    day: str,
    strava_items: list[dict[str, Any]] | None,
    hevy_workouts: list[dict[str, Any]] | None,
    apple_items: Any = NOT_WIRED,
) -> dict[str, Any] | None:
    """The WALKING-modality minutes of ONE day, from the day rows a compute already holds (ADR-163).

    Not a second definition: it is `build` over the single day — the same counted types and names,
    the same #4068 time de-dup (a WHOOP walk recorded inside a Hevy treadmill session is that block
    seen twice and counts once) — reading only the `walking` modality (cycling is the layer's other
    modality and is not walking time). None when neither source has a record for the day: unknown,
    never zero minutes (ADR-104). A source with records but no counted walking reads 0.
    """
    layer = build(window_start=day, window_end=day, strava_items=strava_items, hevy_workouts=hevy_workouts, apple_items=apple_items)
    if layer["total_hr"] is None:
        return None
    walking_hr = float(layer["by_modality"].get("walking") or 0.0)
    by_source = {
        name: (round(float(block["by_modality"].get("walking") or 0.0) * 60.0, 1) if block["hours"] is not None else None)
        for name, block in layer["by_source"].items()
    }
    return {
        "minutes": round(walking_hr * 60.0, 1),
        "by_source": by_source,
        "dedup_minutes_removed": round(float(layer["dedup"]["hours_removed"]) * 60.0, 1),
        "version": layer["version"],
    }
