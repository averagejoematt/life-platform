"""
health_auto_export_workouts.py — every Apple workout the HAE webhook carries, as one owner-only
DynamoDB summary per workout id on the apple_health day row (#4973, epic #4967).

Why a sibling: until #4973 the webhook kept only RECOVERY-type workouts in DynamoDB (Pliability,
Breathwrk, yoga … as `*_minutes` aggregates, v1.6.0) and wrote a thin record of every workout to
the S3 `workouts` sub-archive; a walk, a ride or a lift the watch recorded never reached the
table, and its heart-rate series, heart-rate recovery, effort score and running dynamics were
dropped. The recovery aggregates and the S3 sub-archive are unchanged (moved here verbatim so the
webhook module stays under its size baseline); this module ADDS the all-type summary.

The contract (docs/SCHEMA.md "Apple workouts"):

  * CAPTURE ALL, PER SOURCE. Every vendor key HAE sends is kept under HAE's own name: every
    scalar, and every `{qty, units}` / nested dict (heartRate.avg, estimatedEffortScore,
    distance, intensity, temperature, source …) recursively. Nothing is picked, renamed or
    combined with Strava, Hevy or Whoop — the one read-side resolver
    (`training.workout_identity`) decides which records are one workout.
  * SERIES ARE SUMMARISED, NOT DROPPED. A per-sample list (heartRateData, heartRateRecovery,
    activeEnergy, stepCount, running power / stride / ground contact / vertical oscillation —
    whatever HAE sends) becomes `derived.series[<vendor key>] = {n, mean, min, max, units}`.
    From the heart-rate series: `derived.hr_seconds_by_bpm5` (seconds per 5-bpm bin — the
    distribution any zone definition can be read from later; NO band is assumed here, the
    #4627 rule) and `derived.hr_recovery` (bpm at the end, 60 s and 120 s after, and the drops).
    Structural lists (segments, splits, events) are counted; `activities` (a multi-sport
    workout's legs) keep their scalar/dict fields. The full payload — every sample, every
    split — stays in the raw S3 archive (`save_raw_payload`), which this module does not touch.
  * GPS NEVER IN THE TABLE. The `route` (and any lat/lon key at any depth) is not stored; the
    summary keeps only `derived.route_points` (a count). The route lives in the owner-only raw
    S3 payload archive.
  * IDENTITY BY VENDOR ID. The day row's `apple_workouts` map is keyed by HAE's workout `id`;
    a re-send of the same workout is the SAME entry (field-merged: a key the new copy carries
    replaces the stored one, a key it lacks is kept — a partial re-send never erases a fuller
    stored summary, #3119's lesson). A workout with no id is not stored (it cannot be deduped);
    it remains in the raw archive.
  * DAY FRAME. A workout is filed under the UTC day of its start, derived by the webhook's own
    `parse_date_str` (passed in) — the same day `process_workouts` uses for the S3 sub-archive.
  * PRIVACY. `apple_workouts` is Tier-2 owner-only (`lambdas/privacy/field_tiers.py`).

Pure derivation (`summarize_workout`, `summaries_by_day`) is separate from the one writer
(`write_apple_workouts`) so the tests exercise the rule without AWS.
"""

import logging
import math
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from ingestion.health_auto_export_sleep import parse_instant

try:
    from common.platform_logger import get_logger

    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)

WORKOUTS_FIELD = "apple_workouts"
SUMMARY_VERSION = "hae-workout-summary@1"

# Never stored in the table, at any depth (the route is a list of lat/lon fixes).
GPS_KEYS = frozenset({"route", "routes", "latitude", "longitude", "lat", "lon", "lng", "latlng", "coordinate", "coordinates", "gps"})
# A per-sample reading carries a timestamp and a value under one of these keys.
_READING_VALUE_KEYS = ("qty", "Avg")
_HR_SERIES_KEY = "heartRateData"
_HR_RECOVERY_KEY = "heartRateRecovery"
_HR_BIN_BPM = 5
_MAX_SAMPLE_GAP_S = 300.0  # a gap longer than this is not attributed to the previous sample
_DEFAULT_SAMPLE_S = 60.0  # HAE's heart-rate series is per minute
_RECOVERY_OFFSETS_S = (60, 120)
_RECOVERY_TOLERANCE_S = 30.0


# ── the recovery aggregates + S3 sub-archive records (v1.6.0, moved verbatim from the webhook) ──

# Recovery workout types — these are NOT tracked by Strava and represent
# mobility/breathwork/recovery modalities we want to aggregate.
# Maps HealthKit workout name → category for DynamoDB fields.
RECOVERY_WORKOUT_TYPES = {
    # Flexibility / Mobility (Pliability, stretching apps)
    "Flexibility": "flexibility",
    "flexibility": "flexibility",
    # Breathwork (Breathwrk, Wim Hof, etc.)
    "Mind and Body": "breathwork",
    "mind_and_body": "breathwork",
    "Breathing": "breathwork",
    "breathing": "breathwork",
    # Yoga / Pilates
    "Yoga": "yoga",
    "yoga": "yoga",
    "Pilates": "pilates",
    "pilates": "pilates",
    # Cooldown / Tai Chi
    "Cooldown": "cooldown",
    "cooldown": "cooldown",
    "Tai Chi": "tai_chi",
    "tai_chi": "tai_chi",
}


def _energy_kcal(w):
    """Active energy: prefer the summary field, fall back to summing readings."""
    aeb = w.get("activeEnergyBurned", {})
    if isinstance(aeb, dict) and aeb.get("qty") is not None:
        try:
            return round(float(aeb["qty"]), 1)
        except (ValueError, TypeError):
            return 0
    ae_readings = w.get("activeEnergy", [])
    if ae_readings:
        return round(sum(float(r.get("qty", 0)) for r in ae_readings), 1)
    return 0


def _recovery_aggregate(recovery):
    cat_minutes = defaultdict(float)
    cat_sessions = defaultdict(int)
    for w in recovery:
        cat_minutes[w["category"]] += w["duration_min"]
        cat_sessions[w["category"]] += 1
    agg = {}
    for cat in ("flexibility", "breathwork", "yoga", "pilates"):
        if cat_minutes.get(cat):
            agg[f"{cat}_minutes"] = round(cat_minutes[cat], 1)
            agg[f"{cat}_sessions"] = cat_sessions[cat]
    for cat in ("cooldown", "tai_chi"):
        if cat_minutes.get(cat):
            agg[f"{cat}_minutes"] = round(cat_minutes[cat], 1)
    agg["recovery_workout_minutes"] = round(sum(cat_minutes.values()), 1)
    agg["recovery_workout_sessions"] = len(recovery)
    agg["recovery_workout_types"] = ", ".join(sorted(set(w["category"] for w in recovery)))
    return agg


def process_workouts(workouts, day_of):
    """
    Process workouts from HAE payload (v1.6.0).

    Classifies each workout, and aggregates recovery-type workouts (flexibility, breathwork,
    yoga, etc.) for DynamoDB. Every type is returned for the S3 sub-archive; the all-type
    DynamoDB summary is `write_apple_workouts` (#4973).

    Returns:
        daily_workouts: dict of date → list of normalized workout dicts (all types, for S3)
        daily_agg: dict of date → {flexibility_minutes, breathwork_minutes, etc.} (recovery only, for DDB)
    """
    daily_workouts = defaultdict(list)
    for w in workouts:
        date = day_of(w.get("start", ""))
        if not date:
            continue
        name = w.get("name", "Unknown")
        try:
            duration_sec = float(w.get("duration", 0))
        except (ValueError, TypeError):
            duration_sec = 0
        category = RECOVERY_WORKOUT_TYPES.get(name, "other")
        daily_workouts[date].append(
            {
                "id": w.get("id", ""),
                "name": name,
                "category": category,
                "start": w.get("start", ""),
                "end": w.get("end", ""),
                "duration_min": round(duration_sec / 60, 1),
                "active_energy_kcal": _energy_kcal(w),
                "is_indoor": w.get("isIndoor"),
                "is_recovery_type": category != "other",
            }
        )
    daily_agg = {}
    for date, wkts in daily_workouts.items():
        recovery = [w for w in wkts if w["is_recovery_type"]]
        if recovery:
            daily_agg[date] = _recovery_aggregate(recovery)
    return daily_workouts, daily_agg


# ── the all-type summary (#4973) ─────────────────────────────────────────────────────


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _scalar(v):
    """A storable scalar (str / bool / finite number), else None."""
    if isinstance(v, (str, bool)):
        return v if v != "" else None
    return _num(v)


def _clean(obj):
    """A vendor dict with every scalar and nested dict kept, GPS keys and lists dropped."""
    out = {}
    for k, v in obj.items():
        if k in GPS_KEYS:
            continue
        if isinstance(v, dict):
            sub = _clean(v)
            if sub:
                out[k] = sub
        elif not isinstance(v, list):
            s = _scalar(v)
            if s is not None:
                out[k] = s
    return out


def _is_reading_list(v):
    return bool(v) and all(isinstance(r, dict) for r in v) and any(any(k in r for k in _READING_VALUE_KEYS) for r in v)


def _reading_value(r):
    return _num(r.get("qty")) if "qty" in r else _num(r.get("Avg"))


def series_summary(readings):
    """`{n, mean, min, max, units}` of one per-sample vendor list (Min/Max honoured when present)."""
    vals = [v for v in (_reading_value(r) for r in readings) if v is not None]
    if not vals:
        return {}
    lows = [x for x in (_num(r.get("Min")) for r in readings) if x is not None] or vals
    highs = [x for x in (_num(r.get("Max")) for r in readings) if x is not None] or vals
    units = next((r.get("units") for r in readings if r.get("units")), None)
    out = {"n": len(vals), "mean": round(sum(vals) / len(vals), 3), "min": min(lows), "max": max(highs)}
    if units:
        out["units"] = units
    return out


def _timed(readings):
    """[(instant, value)] sorted by time, for readings that carry both."""
    got = []
    for r in readings or ():
        t, v = parse_instant(r.get("date")), _reading_value(r) if isinstance(r, dict) else None
        if t is not None and v is not None:
            got.append((t, v))
    return sorted(got, key=lambda x: x[0])


def hr_seconds_by_bpm(readings):
    """Seconds per 5-bpm bin of the heart-rate series ({'110': 240.0, …}); each sample holds until
    the next (capped at 5 min), the last one for a minute. No zone band is assumed here."""
    timed = _timed(readings)
    bins = defaultdict(float)
    for i, (t, bpm) in enumerate(timed):
        gap = (timed[i + 1][0] - t).total_seconds() if i + 1 < len(timed) else _DEFAULT_SAMPLE_S
        bins[str(int(bpm // _HR_BIN_BPM) * _HR_BIN_BPM)] += min(max(gap, 0.0), _MAX_SAMPLE_GAP_S)
    return {k: round(v, 1) for k, v in sorted(bins.items(), key=lambda kv: int(kv[0])) if v > 0}


def hr_recovery(workout):
    """Heart-rate recovery from the workout's own series: bpm at the end, at +60 s / +120 s, the drops."""
    end = parse_instant(workout.get("end"))
    series, rec = _timed(workout.get(_HR_SERIES_KEY)), _timed(workout.get(_HR_RECOVERY_KEY))
    if end is None or not rec:
        return {}
    at_end = [v for t, v in series if t <= end]
    out = {"samples": len(rec)}
    end_bpm = at_end[-1] if at_end else rec[0][1]
    out["end_bpm"] = end_bpm
    for offset in _RECOVERY_OFFSETS_S:
        target = end + timedelta(seconds=offset)
        t, bpm = min(rec, key=lambda x: abs((x[0] - target).total_seconds()))
        if abs((t - target).total_seconds()) <= _RECOVERY_TOLERANCE_S:
            out[f"bpm_{offset}s"] = bpm
            out[f"drop_{offset}s"] = round(end_bpm - bpm, 1)
    return out


def summarize_workout(w):
    """One HAE workout -> its owner-only summary, or None without a vendor id / start."""
    if not isinstance(w, dict) or not w.get("id") or not w.get("start"):
        return None
    out, derived = {}, {"version": SUMMARY_VERSION}
    series, counts = {}, {}
    for k, v in w.items():
        if k in GPS_KEYS:
            if isinstance(v, list):
                derived["route_points"] = len(v)
            continue
        if isinstance(v, dict):
            sub = _clean(v)
            if sub:
                out[k] = sub
        elif isinstance(v, list):
            if k == "activities":
                legs = [_clean(a) for a in v if isinstance(a, dict)]
                if legs:
                    out[k] = legs
            elif _is_reading_list(v):
                summ = series_summary(v)
                if summ:
                    series[k] = summ
            elif v:
                counts[k] = len(v)
        else:
            s = _scalar(v)
            if s is not None:
                out[k] = s
    if series:
        derived["series"] = series
    if counts:
        derived["counts"] = counts
    bins = hr_seconds_by_bpm(w.get(_HR_SERIES_KEY))
    if bins:
        derived["hr_seconds_by_bpm5"] = bins
    rec = hr_recovery(w)
    if rec:
        derived["hr_recovery"] = rec
    out["derived"] = derived
    return out


def summaries_by_day(workouts, day_of):
    """`{day: {workout_id: summary}}` for every workout in one payload (all types)."""
    days = defaultdict(dict)
    skipped = 0
    for w in workouts or ():
        summ = summarize_workout(w)
        day = day_of(summ["start"]) if summ else None
        if not summ or not day:
            skipped += 1
            continue
        days[day][str(summ["id"])] = summ
    if skipped:
        logger.warning("[HAE workouts] %d workout(s) without an id/start not summarised (kept in the raw archive)", skipped)
    return dict(days)


def merge_summaries(stored, new):
    """Field-merge by workout id: a key the new copy carries wins, a key it lacks is kept
    (`derived` is merged one level down, so a re-send without a series keeps its stored summary)."""
    merged = {k: dict(v) for k, v in (stored or {}).items() if isinstance(v, dict)}
    for wid, summ in new.items():
        old = merged.get(wid, {})
        rec = {**old, **summ}
        if isinstance(old.get("derived"), dict) and isinstance(summ.get("derived"), dict):
            rec["derived"] = {**old["derived"], **summ["derived"]}
        merged[wid] = rec
    return merged


def _plain(obj):
    """DynamoDB value (Decimals) -> plain floats, recursively."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


def to_ddb(obj):
    """Floats -> Decimal (boto3 rejects float), recursively; non-finite values dropped."""
    if isinstance(obj, bool) or obj is None or isinstance(obj, (str, int, Decimal)):
        return obj
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4))) if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: c for k, c in ((k, to_ddb(v)) for k, v in obj.items()) if c is not None}
    if isinstance(obj, list):
        return [c for c in (to_ddb(v) for v in obj) if c is not None]
    return obj


def _default_phase():
    try:
        from ingestion.ingestion_framework import phase_for_date

        return phase_for_date
    except ImportError:  # pragma: no cover — layer unavailable locally
        return None


def write_apple_workouts(workouts, table, day_of, key_of, phase_for_date=_default_phase):
    """Merge every workout's summary into its apple_health day row's `apple_workouts` map.

    Returns the number of day rows written. Read-merge-write per day: if the stored map cannot
    be read the day is SKIPPED, never written payload-only (a partial re-send must not overwrite
    a fuller stored map); the next re-send heals it."""
    written = 0
    if phase_for_date is _default_phase:
        phase_for_date = _default_phase()
    for day, new in sorted(summaries_by_day(workouts, day_of).items()):
        key = key_of(day)
        try:
            item = table.get_item(Key=key, ProjectionExpression="#w", ExpressionAttributeNames={"#w": WORKOUTS_FIELD}).get("Item", {})
        except Exception as e:  # noqa: BLE001 — fail toward stored history
            logger.warning("[HAE workouts] %s: stored map unreadable, day skipped: %s", day, e)
            continue
        stored = _plain(item.get(WORKOUTS_FIELD)) if isinstance(item, dict) else None
        merged = merge_summaries(stored if isinstance(stored, dict) else {}, new)
        names = {"#w": WORKOUTS_FIELD, "#src": "source", "#dt": "date"}
        values = {":w": to_ddb(merged), ":src": "apple_health", ":dt": day}
        sets = ["#w = :w", "#src = if_not_exists(#src, :src)", "#dt = if_not_exists(#dt, :dt)"]
        if phase_for_date is not None:
            names["#ph"], values[":ph"] = "phase", phase_for_date(day)
            sets.append("#ph = if_not_exists(#ph, :ph)")
        try:
            table.update_item(
                Key=key, UpdateExpression="SET " + ", ".join(sets), ExpressionAttributeNames=names, ExpressionAttributeValues=values
            )
        except Exception as e:  # noqa: BLE001 — one day's summary must not fail the webhook
            logger.error("[HAE workouts] %s: summary write failed: %s", day, e)
            continue
        written += 1
    if written:
        logger.info("[HAE workouts] all-type summaries written for %d day(s)", written)
    return written


def ingest(workouts, *, save_s3, merge_day, table, day_of, key_of):
    """The webhook's whole workouts step: S3 sub-archive (all types), the recovery aggregates
    (v1.6.0) and the all-type summary (#4973). Returns the handler's counters."""
    counts = {"workout_days": 0, "workout_new": 0, "recovery_days": 0, "workout_summary_days": 0}
    if not workouts:
        logger.info("No workouts in payload")
        return counts
    daily_workouts, daily_agg = process_workouts(workouts, day_of)
    logger.info("Workout types found: %s", sorted({f"{w['name']} ({w['category']})" for ws in daily_workouts.values() for w in ws}))
    for date_str, wkts in daily_workouts.items():
        n = save_s3(date_str, wkts)
        if n > 0:
            counts["workout_new"] += n
            counts["workout_days"] += 1
    for date_str, agg in daily_agg.items():
        merge_day(date_str, agg)
        counts["recovery_days"] += 1
    counts["workout_summary_days"] = write_apple_workouts(workouts, table, day_of, key_of)
    return counts
