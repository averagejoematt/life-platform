"""
health_auto_export_sleep.py — the Apple Watch's own sleep record, stored as its own
`sleep_*_apple` fields on the apple_health day row (#4971, epic #4967).

Why a sibling: until #4971 the HAE webhook dropped `sleep_analysis` whole (a Tier-3 skip,
"Eight Sleep is SOT"). The owner wears the watch nightly and ruled on 2026-10-17 to "keep
both [Whoop and Apple Watch], so we can figure out whether we average the result set or
determine primary and backup source" — so Apple's night is CAPTURED, beside Whoop's and
Eight Sleep's, and interpreted later (the dual-wear agreement study, #4974).

The contract (docs/SCHEMA.md "Apple sleep fields"):

  * OWN FIELDS ONLY. Every field this module writes ends in `_apple` and is listed in
    `APPLE_SLEEP_FIELDS`; it never writes a Whoop or Eight Sleep field name, and no
    `METRIC_TRUTH` facet reads these fields as truth.
  * APPLE READINGS ONLY. HealthKit is an aggregator: Whoop and Eight Sleep both write
    their own nights into it, and HAE exports them under `sleep_analysis` with
    `source: "WHOOP"` / `"Eight Sleep"` (seen live 2026-10-04/05). A reading is kept only
    when EVERY `|`-separated part of its source names an Apple device — stricter than the
    generic `is_apple_device`, which accepts a missing source.
  * DAY FRAME. A night is filed under the morning it ENDS: the UTC day (the apple_health
    `day_key_frame`, #3677) of its wake instant, derived by the webhook's own
    `parse_date_str` (passed in) — this module derives no day of its own. For any wake
    before 17:00 PT that UTC day IS the Pacific wake date, and for any onset after 17:00 PT it is the key Whoop files
    the same night under (#3913: a sleep begun 21:44 PT 09-18 is on DATE#2026-09-19).
  * ABSENCE (ADR-104). No Apple reading -> no field. A stage with no reading is absent,
    never 0. HAE's aggregated export zero-fills, so in that shape an unstaged night (core,
    deep and rem all 0) carries no stage fields, and a 0 in-bed / unspecified is absent.
  * RE-SENDS. HAE syncs incrementally and re-sends what it already sent. Every reading
    is merged into the row's `_rd_sleep_apple` map keyed by its identity (stage, start,
    end, device; stored wins a collision — the #4628 unique-reading rule), and the night
    is recomputed from the WHOLE map: stage minutes are the UNION of that stage's
    intervals, so an overlapping re-send is counted once, never summed. A night-summary
    re-send is never added to another: the fullest summary (largest total, then in-bed)
    is the night.

Pure derivation (`entries_from_metrics`, `derive_night`) is separate from the one writer
(`write_apple_sleep`) so the tests exercise the rule without AWS.
"""

import logging
import re
from collections import defaultdict
from datetime import timedelta, timezone
from decimal import Decimal

from common.pacific_time import parse_iso_utc

try:
    from common.platform_logger import get_logger

    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)

SLEEP_METRIC_NAMES = frozenset({"sleep_analysis", "Sleep Analysis"})

# The row's reading map — every Apple sleep reading ever delivered for the night.
RD_FIELD = "_rd_sleep_apple"

# Every value field this module may write (the SCHEMA rows + the field_tiers rows are
# checked against this tuple). RD_FIELD is listed separately.
APPLE_SLEEP_FIELDS = (
    "sleep_total_hours_apple",
    "sleep_in_bed_hours_apple",
    "sleep_core_min_apple",
    "sleep_deep_min_apple",
    "sleep_rem_min_apple",
    "sleep_awake_min_apple",
    "sleep_unspecified_min_apple",
    "sleep_start_apple",
    "sleep_end_apple",
    "sleep_in_bed_start_apple",
    "sleep_in_bed_end_apple",
    "sleep_source_apple",
    "sleep_record_kind_apple",
)

_ASLEEP_STAGES = ("core", "deep", "rem", "unspecified")
_STAGE_FIELD = {
    "core": "sleep_core_min_apple",
    "deep": "sleep_deep_min_apple",
    "rem": "sleep_rem_min_apple",
    "awake": "sleep_awake_min_apple",
    "unspecified": "sleep_unspecified_min_apple",
}
# HAE / HealthKit stage labels, lower-cased with non-letters stripped.
_STAGE_ALIASES = {
    "core": "core",
    "asleepcore": "core",
    "light": "core",
    "deep": "deep",
    "asleepdeep": "deep",
    "rem": "rem",
    "asleeprem": "rem",
    "awake": "awake",
    "inbed": "in_bed",
    "asleep": "unspecified",
    "asleepunspecified": "unspecified",
    "unspecified": "unspecified",
}
# Samples further apart than this belong to different sleep sessions.
SESSION_GAP = timedelta(hours=2)
_MAX_NIGHT_HOURS = 24.0


def parse_instant(value):
    """An HAE stamp ('2026-10-04 09:05:55 -0700', ISO, or 'Z') -> aware datetime, else None.

    The device's own offset is KEPT (common.pacific_time.parse_iso_utc's contract) so the
    stored onset/wake strings carry the frame the watch recorded them in."""
    if not value or not isinstance(value, str):
        return None
    s = re.sub(r"\s+", "", value.strip().replace(" ", "T", 1))
    m = re.match(r"^(.*[T\d])([+-]\d{2})(\d{2})$", s)
    if m:
        s = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    return parse_iso_utc(s)


def is_apple_sleep_source(source, is_apple_device):
    """True only when every `|`-part of the source is an Apple device (never a blank source)."""
    parts = [p.strip() for p in (source or "").split("|") if p.strip()]
    return bool(parts) and all(is_apple_device(p) for p in parts)


def _stage(label):
    return _STAGE_ALIASES.get(re.sub(r"[^a-z]", "", str(label or "").lower()))


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _hours_factor(units):
    u = (units or "hr").lower().strip()
    return 1 / 60.0 if u in ("min", "mins", "minute", "minutes") else 1.0


def _sample_entry(reading, source):
    """An unaggregated HAE sample -> (key, entry) or None."""
    stage = _stage(reading.get("value"))
    start = parse_instant(reading.get("startDate") or reading.get("start"))
    end = parse_instant(reading.get("endDate") or reading.get("end"))
    if stage is None or start is None or end is None or end <= start:
        return None
    s_utc, e_utc = start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()
    entry = {"kind": "sample", "stage": stage, "start": start.isoformat(), "end": end.isoformat(), "source": source}
    return f"s|{stage}|{s_utc}|{e_utc}|{source}", entry, end


def _summary_entry(reading, source, units):
    """An aggregated HAE night summary -> (key, entry, wake) or None. Every vendor field is kept."""
    wake = parse_instant(reading.get("sleepEnd")) or parse_instant(reading.get("inBedEnd"))
    if wake is None:
        return None
    factor = _hours_factor(units)
    entry = {"kind": "summary", "source": source, "units_reported": units or "hr"}  # durations below are hours
    for k, v in reading.items():
        if k == "source":
            continue
        n = _num(v) if not isinstance(v, str) else None
        entry[k] = round(n * factor, 4) if n is not None else v
    start = reading.get("sleepStart") or reading.get("inBedStart") or ""
    key = f"n|{start}|{reading.get('sleepEnd') or reading.get('inBedEnd')}|{source}"
    return key, entry, wake


def entries_from_metrics(metrics, is_apple_device, day_of):
    """`{night_day: {key: entry}}` for every Apple sleep reading in one payload.

    `day_of` is the webhook's own `parse_date_str` — the ONE place the apple_health
    partition's UTC day is derived (#3677/#3913) — applied to the wake instant, so this
    module adds no second UTC-day writer."""
    samples, nights = [], defaultdict(dict)
    for metric in metrics or ():
        if metric.get("name") not in SLEEP_METRIC_NAMES:
            continue
        units = (metric.get("units") or "").strip()
        for reading in metric.get("data") or ():
            source = (reading.get("source") or "").strip()
            if not is_apple_sleep_source(source, is_apple_device):
                continue
            if reading.get("value") is not None and (reading.get("startDate") or reading.get("start")):
                got = _sample_entry(reading, source)
                if got:
                    samples.append(got)
            else:
                got = _summary_entry(reading, source, units)
                if got:
                    nights[day_of(got[2].isoformat())][got[0]] = got[1]
    # Group samples into sessions; a session is filed under the UTC day of its last end.
    samples.sort(key=lambda t: parse_instant(t[1]["start"]))
    sessions = []
    for key, entry, end in samples:
        start = parse_instant(entry["start"])
        if not sessions or start - sessions[-1]["end"] > SESSION_GAP:
            sessions.append({"end": end, "entries": {}})
        sessions[-1]["entries"][key] = entry
        sessions[-1]["end"] = max(sessions[-1]["end"], end)
    for sess in sessions:
        nights[day_of(sess["end"].isoformat())].update(sess["entries"])
    return {d: e for d, e in nights.items() if e}


def _union_minutes(intervals):
    total, cur_s, cur_e = 0.0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += (cur_e - cur_s).total_seconds()
    return total / 60.0


def _from_samples(samples):
    by_stage = defaultdict(list)
    for e in samples:
        by_stage[e["stage"]].append((parse_instant(e["start"]), parse_instant(e["end"]), e))
    out = {"sleep_record_kind_apple": "samples"}
    for stage, field in _STAGE_FIELD.items():
        if by_stage.get(stage):
            out[field] = round(_union_minutes([(s, t) for s, t, _ in by_stage[stage]]), 1)
    asleep = [x for st in _ASLEEP_STAGES for x in by_stage.get(st, ())]
    if asleep:
        out["sleep_total_hours_apple"] = round(_union_minutes([(s, t) for s, t, _ in asleep]) / 60.0, 3)
        out["sleep_start_apple"] = min(asleep, key=lambda x: x[0])[2]["start"]
        out["sleep_end_apple"] = max(asleep, key=lambda x: x[1])[2]["end"]
    in_bed = by_stage.get("in_bed")
    if in_bed:
        out["sleep_in_bed_hours_apple"] = round(_union_minutes([(s, t) for s, t, _ in in_bed]) / 60.0, 3)
        out["sleep_in_bed_start_apple"] = min(in_bed, key=lambda x: x[0])[2]["start"]
        out["sleep_in_bed_end_apple"] = max(in_bed, key=lambda x: x[1])[2]["end"]
    out["sleep_source_apple"] = " | ".join(sorted({e["source"] for e in samples}))
    return out


def _iso(v):
    dt = parse_instant(v)
    return dt.isoformat() if dt else None


def _from_summary(s):
    out = {"sleep_record_kind_apple": "summary", "sleep_source_apple": s["source"]}
    hrs = {k: _num(s.get(k)) for k in ("totalSleep", "inBed", "core", "deep", "rem", "awake", "asleep")}
    if hrs["totalSleep"]:
        out["sleep_total_hours_apple"] = round(hrs["totalSleep"], 3)
        out["sleep_start_apple"], out["sleep_end_apple"] = _iso(s.get("sleepStart")), _iso(s.get("sleepEnd"))
    if hrs["inBed"]:
        out["sleep_in_bed_hours_apple"] = round(hrs["inBed"], 3)
        out["sleep_in_bed_start_apple"], out["sleep_in_bed_end_apple"] = _iso(s.get("inBedStart")), _iso(s.get("inBedEnd"))
    if any(hrs[k] for k in ("core", "deep", "rem")):  # a staged night: a reported 0 is a real 0
        for stage in ("core", "deep", "rem", "awake"):
            if hrs[stage] is not None:
                out[_STAGE_FIELD[stage]] = round(hrs[stage] * 60.0, 1)
    elif hrs["awake"]:  # unstaged night: awake only when reported non-zero (HAE zero-fills)
        out["sleep_awake_min_apple"] = round(hrs["awake"] * 60.0, 1)
    if hrs["asleep"]:
        out["sleep_unspecified_min_apple"] = round(hrs["asleep"] * 60.0, 1)
    return {k: v for k, v in out.items() if v is not None}


def derive_night(entries):
    """One night's `sleep_*_apple` fields from its whole reading map ({} when nothing usable).

    Samples win over summaries (they are the finer record); among summaries the fullest wins."""
    samples = [e for e in entries.values() if e.get("kind") == "sample"]
    if samples:
        out = _from_samples(samples)
    else:
        summaries = [e for e in entries.values() if e.get("kind") == "summary"]
        if not summaries:
            return {}
        out = _from_summary(max(summaries, key=lambda e: (_num(e.get("totalSleep")) or 0, _num(e.get("inBed")) or 0)))
    if (out.get("sleep_total_hours_apple") or 0) > _MAX_NIGHT_HOURS or (out.get("sleep_in_bed_hours_apple") or 0) > _MAX_NIGHT_HOURS:
        logger.error("[HAE sleep] implausible night refused: %s", out)
        return {}
    return out if len(out) > 2 else {}


def _plain(obj):
    """DynamoDB map (Decimals) -> plain floats, recursively."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    return obj


def _to_ddb(obj):
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4))) if obj == obj else None
    if isinstance(obj, dict):
        return {k: _to_ddb(v) for k, v in obj.items() if v is not None}
    return obj


def _default_phase():
    try:
        from ingestion.ingestion_framework import phase_for_date

        return phase_for_date
    except ImportError:  # pragma: no cover — layer unavailable locally
        return None


def write_apple_sleep(metrics, table, is_apple_device, day_of, key_of, phase_for_date=_default_phase):
    """Merge each Apple night in `metrics` into its apple_health day row. Returns nights written.

    The webhook hands in its own day derivation (`day_of`, parse_date_str) and row key
    (`key_of(day)`), so the partition's DATE# frame is decided in one module only.

    Read-merge-recompute per night: the stored `_rd_sleep_apple` map is unioned with this
    payload's readings (stored wins a collision) and the fields are recomputed from the
    union. If the stored map cannot be read the night is SKIPPED, not written payload-only —
    a partial re-send must never overwrite a fuller stored night (#3119's lesson); the
    next re-send heals it."""
    written = 0
    if phase_for_date is _default_phase:
        phase_for_date = _default_phase()
    for day, new_entries in sorted(entries_from_metrics(metrics, is_apple_device, day_of).items()):
        key = key_of(day)
        try:
            stored = table.get_item(Key=key, ProjectionExpression="#rd", ExpressionAttributeNames={"#rd": RD_FIELD}).get("Item", {})
        except Exception as e:  # noqa: BLE001 — fail toward stored history
            logger.warning("[HAE sleep] %s: stored map unreadable, night skipped: %s", day, e)
            continue
        merged = {**new_entries, **_plain(stored.get(RD_FIELD) or {})}
        fields = derive_night(merged)
        if not fields:
            continue
        names, values, sets = {"#rd": RD_FIELD, "#src": "source", "#dt": "date"}, {}, []
        for i, (f, v) in enumerate(fields.items()):
            names[f"#a{i}"], values[f":a{i}"] = f, _to_ddb(v)
            sets.append(f"#a{i} = :a{i}")
        values.update({":rd": _to_ddb(merged), ":src": "apple_health", ":dt": day})
        sets += ["#rd = :rd", "#src = if_not_exists(#src, :src)", "#dt = if_not_exists(#dt, :dt)"]
        if phase_for_date is not None:
            names["#ph"], values[":ph"] = "phase", phase_for_date(day)
            sets.append("#ph = if_not_exists(#ph, :ph)")
        # A field the recomputed night no longer carries is REMOVED, so a stale value cannot survive.
        stale = [f for f in APPLE_SLEEP_FIELDS if f not in fields]
        for j, f in enumerate(stale):
            names[f"#x{j}"] = f
        expr = "SET " + ", ".join(sets) + (" REMOVE " + ", ".join(f"#x{j}" for j in range(len(stale))) if stale else "")
        table.update_item(Key=key, UpdateExpression=expr, ExpressionAttributeNames=names, ExpressionAttributeValues=values)
        written += 1
    if written:
        logger.info("[HAE sleep] Apple sleep: %d night(s) written", written)
    return written
