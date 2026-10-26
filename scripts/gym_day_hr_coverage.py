#!/usr/bin/env python3
"""scripts/gym_day_hr_coverage.py — which records carry heart rate over one gym day's lift (#5390 box 1).

WHY. `training.workout_identity` keeps Hevy's own Strava push as the lift's heart-rate member when it carries
its own heart rate (#5390). Whether that is the right record — and whether Hevy's watch workout stops when
the watch's Workout app starts for the cardio block (watchOS runs one workout session at a time) — is read
from the raw records of a gym day. This prints that read for one Pacific day, so the read under the
2026-10-26 recording protocol is one command per gym day.

WHAT IT READS (read-only S3 GETs and LISTs; nothing is written; no Strava API call, no token refresh):
  * the raw Strava day files, `raw_date_key_candidates("strava", d)` for the day and the next one (an
    evening session is filed under the next UTC day); rows sit under `{"raw": {"activities": [...]}}`.
  * the raw Health Auto Export payload archive, listed by PREFIX under the `apple_health` raw_layout
    (`timestamped`: many deliveries a day, no per-day key), delivery days d-1 .. d+LAG — a workout is
    delivered on or after its own day. The thin `workouts` sub-archive carries no origin and no heart-rate
    series, so the full payload is the source. A workout seen in several deliveries is one (by vendor id;
    the copy with the most heart-rate samples is kept).
  Both read paths come from `ingestion.source_registry`; no key is built by hand.

WHAT IT PRINTS — spans, counts and booleans only. Never a heart-rate value, a zone split, an energy, a
distance, a location or a clock time: every instant is an OFFSET in minutes from the start of Hevy's push
(the lift's span: Hevy pushes the whole session), and a record's heart rate is reported as whether it
carries one and how many minutes / samples of it fall inside that span.

  per record: kind (strava / healthkit), who (Strava `device_name`; HealthKit origin via
              `training.walking_volume.apple_workout_source`), label (sport / workout name),
              start offset, minutes, minutes inside the lift span, carries heart rate, and
              Strava: heart-rate minutes (the sum of its zone seconds) — HealthKit: samples, samples
              inside the span, first/last sample offsets.
  summary:    the Hevy pushes and how many carry their own heart rate; the minutes of the span covered by
              the OTHER heart-rate records (what the lift would read without the push); and, for each
              Hevy-origin HealthKit workout, its gap to the watch's own workouts (an inference input for
              "does the Hevy watch workout stop when the Workout app starts", never a verdict).

RUN:  python3 scripts/gym_day_hr_coverage.py --date 2026-10-25
      python3 scripts/gym_day_hr_coverage.py --date 2026-10-27 --lag-days 3 --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common.pacific_time import pacific_date_of  # noqa: E402
from ingestion.health_auto_export_sleep import parse_instant  # noqa: E402 — the HAE writer's own instant parser
from ingestion.source_registry import raw_date_key_candidates, raw_layout_for  # noqa: E402
from training.walking_volume import apple_workout_source  # noqa: E402
from training.workout_identity import carries_own_hr  # noqa: E402

BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
HEVY_DEVICE = "hevy"
WATCH = "apple_health"  # the watch's own workouts (`apple_workout_source`)
HEVY_ORIGIN = "apple_health/hevy"
_HR_SERIES = "heartRateData"
_ZONE_KEYS = tuple(f"zone{i}_seconds" for i in range(1, 6))
DEFAULT_LAG_DAYS = 2


def _num(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f else 0.0


def _strava_start(a: dict[str, Any]) -> Optional[datetime]:
    return parse_instant(str(a.get("start_date") or "")) if a.get("start_date") else None


# ── normalise the raw records (pure) ──────────────────────────────────────────────────


def strava_records(activities: Iterable[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    """The day's Strava activities (Pacific date of the start), one per `strava_id`."""
    out: dict[str, dict[str, Any]] = {}
    for a in activities:
        if not isinstance(a, dict):
            continue
        start = _strava_start(a)
        if start is None or pacific_date_of(start.isoformat()) != day:
            continue
        secs = _num(a.get("elapsed_time_seconds")) or _num(a.get("moving_time_seconds"))
        sid = str(a.get("strava_id") or a.get("id") or f"{start.isoformat()}#{len(out)}")
        out[sid] = {
            "kind": "strava",
            "who": str(a.get("device_name") or "unknown"),
            "label": str(a.get("sport_type") or a.get("type") or "unknown"),
            "start": start,
            "end": start + timedelta(seconds=secs),
            "carries_hr": carries_own_hr(a),
            "hr_seconds": sum(_num(a.get(k)) for k in _ZONE_KEYS),
            "samples": None,
        }
    return sorted(out.values(), key=lambda r: r["start"])


def healthkit_records(workouts: Iterable[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    """The day's HealthKit workouts from HAE payloads (Pacific date of the start), one per vendor id —
    the copy carrying the most heart-rate samples."""
    best: dict[str, dict[str, Any]] = {}
    for w in workouts:
        if not isinstance(w, dict):
            continue
        start, end = parse_instant(w.get("start")), parse_instant(w.get("end"))
        if start is None or end is None or pacific_date_of(start.isoformat()) != day:
            continue
        samples = sorted(t for t in (parse_instant(r.get("date")) for r in w.get(_HR_SERIES) or () if isinstance(r, dict)) if t is not None)
        wid = str(w.get("id") or f"{start.isoformat()}#{w.get('name')}")
        rec = {
            "kind": "healthkit",
            "who": apple_workout_source(w),
            "label": str(w.get("name") or "unknown"),
            "start": start,
            "end": end,
            "carries_hr": bool(samples),
            "hr_seconds": None,
            "samples": samples,
        }
        if wid not in best or len(samples) > len(best[wid]["samples"]):
            best[wid] = rec
    return sorted(best.values(), key=lambda r: r["start"])


# ── the report (pure) ─────────────────────────────────────────────────────────────────


def _minutes(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 60.0, 1)


def _overlap_s(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> float:
    return max(0.0, (min(e1, e2) - max(s1, s2)).total_seconds())


def _union_s(spans: list[tuple[datetime, datetime]], lo: datetime, hi: datetime) -> float:
    clipped = sorted((max(s, lo), min(e, hi)) for s, e in spans if min(e, hi) > max(s, lo))
    total, cur_s, cur_e = 0.0, None, None
    for s, e in clipped:
        if cur_e is None or s > cur_e:
            if cur_e is not None and cur_s is not None:
                total += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None and cur_s is not None:
        total += (cur_e - cur_s).total_seconds()
    return total


def report(day: str, strava: list[dict[str, Any]], healthkit: list[dict[str, Any]]) -> dict[str, Any]:
    """Spans, counts and booleans for one day — the lift span is the longest Hevy push."""
    records = sorted(strava + healthkit, key=lambda r: r["start"])
    pushes = [r for r in strava if r["who"].strip().lower() == HEVY_DEVICE]
    anchor = max(pushes, key=lambda r: r["end"] - r["start"]) if pushes else None
    origin = anchor["start"] if anchor else (records[0]["start"] if records else None)
    lo, hi = (anchor["start"], anchor["end"]) if anchor else (None, None)
    rows = []
    for r in records:
        row: dict[str, Any] = {
            "kind": r["kind"],
            "who": r["who"],
            "label": r["label"],
            "start_offset_min": _minutes(origin, r["start"]) if origin else None,
            "minutes": _minutes(r["start"], r["end"]),
            "minutes_in_lift_span": round(_overlap_s(r["start"], r["end"], lo, hi) / 60.0, 1) if anchor else None,
            "carries_hr": r["carries_hr"],
        }
        if r["kind"] == "strava":
            row["hr_minutes"] = round((r["hr_seconds"] or 0.0) / 60.0, 1)
        else:
            inside = [t for t in r["samples"] if anchor and lo <= t <= hi]
            row["hr_samples"] = len(r["samples"])
            row["hr_samples_in_lift_span"] = len(inside) if anchor else None
            row["first_sample_offset_min"] = _minutes(origin, r["samples"][0]) if r["samples"] and origin else None
            row["last_sample_offset_min"] = _minutes(origin, r["samples"][-1]) if r["samples"] and origin else None
        rows.append(row)
    summary: dict[str, Any] = {
        "hevy_pushes": len(pushes),
        "hevy_pushes_carrying_own_hr": sum(1 for p in pushes if p["carries_hr"]),
        "lift_span_minutes": _minutes(lo, hi) if anchor else None,
    }
    if anchor:
        others = [(r["start"], r["end"]) for r in records if r["carries_hr"] and r is not anchor]
        summary["span_minutes_covered_by_other_hr_records"] = round(_union_s(others, lo, hi) / 60.0, 1)
        summary["span_minutes_covered_by_the_push"] = summary["lift_span_minutes"] if anchor["carries_hr"] else 0.0
    watch = [r for r in healthkit if r["who"] == WATCH]
    relations = []
    for h in (r for r in healthkit if r["who"] == HEVY_ORIGIN):
        for w in watch:
            relations.append(
                {
                    "hevy_origin_offset_min": _minutes(origin, h["start"]) if origin else None,
                    "watch_label": w["label"],
                    "overlap_min": round(_overlap_s(h["start"], h["end"], w["start"], w["end"]) / 60.0, 1),
                    "hevy_start_minus_watch_end_min": _minutes(w["end"], h["start"]),
                    "watch_start_minus_hevy_end_min": _minutes(h["end"], w["start"]),
                }
            )
    summary["hevy_origin_healthkit_workouts"] = sum(1 for r in healthkit if r["who"] == HEVY_ORIGIN)
    summary["watch_workouts"] = len(watch)
    summary["hevy_origin_vs_watch"] = relations
    return {"date": day, "records": rows, "summary": summary}


# ── I/O (read-only) ───────────────────────────────────────────────────────────────────


def _get_json(s3: Any, key: str) -> Optional[Any]:
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None


def read_strava(s3: Any, day: str) -> list[dict[str, Any]]:
    acts: list[dict[str, Any]] = []
    d0 = date.fromisoformat(day)
    for d in (d0, d0 + timedelta(days=1)):
        for key in raw_date_key_candidates("strava", d.isoformat()):
            body = _get_json(s3, key)
            if body is None:
                continue
            raw = body.get("raw", body) if isinstance(body, dict) else {}
            acts.extend(a for a in (raw.get("activities") or []) if isinstance(a, dict))
            break  # the first generation that exists for that date
    return acts


def read_healthkit(s3: Any, day: str, lag_days: int) -> tuple[list[dict[str, Any]], int]:
    prefix = raw_layout_for("apple_health")["prefix"]
    d0 = date.fromisoformat(day)
    keys: list[str] = []
    for i in range(-1, lag_days + 1):
        d = d0 + timedelta(days=i)
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=f"{prefix}/{d:%Y}/{d:%m}/{d:%d}_"):
            keys.extend(o["Key"] for o in page.get("Contents", []))
    with ThreadPoolExecutor(max_workers=8) as pool:
        bodies = list(pool.map(lambda k: _get_json(s3, k), keys))
    workouts: list[dict[str, Any]] = []
    for body in bodies:
        data = body.get("data", body) if isinstance(body, dict) else {}
        workouts.extend(w for w in (data.get("workouts") or []) if isinstance(w, dict))
    return workouts, len(keys)


def _print_table(rep: dict[str, Any], deliveries: int) -> None:
    origin = "the start of Hevy's push" if rep["summary"]["hevy_pushes"] else "the first record (no Hevy push: not a gym day)"
    print(f"{rep['date']}  (offsets in minutes from {origin}; {deliveries} HAE deliveries read)")
    for r in rep["records"]:
        hr = (
            f"hr_min={r['hr_minutes']}"
            if r["kind"] == "strava"
            else f"samples={r['hr_samples']} in_span={r['hr_samples_in_lift_span']} first={r['first_sample_offset_min']} last={r['last_sample_offset_min']}"
        )
        print(
            f"  {r['kind']:<9} {r['who'][:28]:<28} {r['label'][:30]:<30} +{r['start_offset_min']:>6} "
            f"{r['minutes']:>6} min  in_span={r['minutes_in_lift_span']}  hr={r['carries_hr']}  {hr}"
        )
    print("  summary:", json.dumps(rep["summary"], sort_keys=True))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", required=True, help="the Pacific gym day, YYYY-MM-DD")
    ap.add_argument("--lag-days", type=int, default=DEFAULT_LAG_DAYS, help="HAE delivery days read after the day")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    date.fromisoformat(args.date)
    import boto3  # local: the pure functions above import without AWS

    s3 = boto3.client("s3", region_name=REGION)
    workouts, deliveries = read_healthkit(s3, args.date, args.lag_days)
    rep = report(args.date, strava_records(read_strava(s3, args.date), args.date), healthkit_records(workouts, args.date))
    if args.json:
        print(json.dumps({**rep, "hae_deliveries_read": deliveries}, indent=2, sort_keys=True))
    else:
        _print_table(rep, deliveries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
