#!/usr/bin/env python3
"""The #5371 uploader inventory and 7-day proof read, as one command (READ-ONLY).

    python3 scripts/strava_uploader_proof.py --since 2026-10-26 --until 2026-11-02
    python3 scripts/strava_uploader_proof.py --since 2026-10-26 --until 2026-11-02 --json

`docs/integrations/strava-best-practices-2026-10.md` §5 describes the read that closes the issue:
which app uploaded each stored Strava activity, whether WHOOP still pushes on a gym day, whether the
watch pushes its own workouts, the seam's fold count and `MissingActivityCount{Source=strava}`.
This is that read, so nobody re-derives it by hand. It compares the window with the equal-length
window before it (the baseline).

Read-only by construction, and NEVER the Strava API: the token refresh rotates the stored secret,
which is a write. The uploader is the stored raw row's `device_name`
(`raw/matthew/strava/activities/YYYY/MM/YYYY-MM-DD.json`, rows under `{"raw": {"activities": [...]}}`),
the metric is a CloudWatch read. Counts only: no heart rate, distance, location or name is printed.

A "gym day" is a day on which Hevy's own push to Strava exists (device_name "Hevy") — the proxy the
inventory used; a day with no Hevy push is not read as a gym day, so a window with none leaves the
WHOOP-on-a-gym-day line `n/a` rather than a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

BUCKET = "matthew-life-platform"
REGION = "us-west-2"
KEY = "raw/matthew/strava/activities/{y}/{m}/{d}.json"
# The raw file carries many numeric fields as strings (the DynamoDB writer normalises them, the seam
# needs numbers), so every string that parses as a number is cast, except these text fields.
_TEXT = frozenset(
    ("strava_id", "name", "device_name", "type", "sport_type", "start_date", "start_date_local", "timezone", "summary_polyline", "gear_id")
    + ("location_city", "location_state", "location_country")
)
WATCH_PREFIX = "Apple Watch"


def days(since: date, until: date) -> list[date]:
    if until <= since:
        raise ValueError("--until must be after --since")
    return [since + timedelta(days=i) for i in range((until - since).days)]


def load_day(s3, d: date) -> list[dict]:
    """The stored raw activities of one local day; [] when no file exists (a day with no workout)."""
    key = KEY.format(y=f"{d.year:04d}", m=f"{d.month:02d}", d=d.isoformat())
    try:
        body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except Exception as e:  # noqa: BLE001 - a missing key is the normal "no activity" day
        if getattr(e, "response", {}).get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return []
        raise
    return list(((json.loads(body) or {}).get("raw") or {}).get("activities") or [])


def _num(activity: dict) -> dict:
    out = dict(activity)
    for k, v in activity.items():
        if k not in _TEXT and isinstance(v, str):
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out


def fold_count(day_activities: list[dict]) -> int:
    """The seam's `duplicate_activity_count` for one day (0 when it folds nothing)."""
    from common.strava_read_seam import dedup_strava_day

    out = dedup_strava_day({"activities": [_num(a) for a in day_activities]})
    return int(out.get("duplicate_activity_count") or 0)


def read_window(s3, since: date, until: date) -> dict:
    """Counts for one window of local days, distinct by `strava_id`."""
    seen: set = set()
    by_device: Counter = Counter()
    by_device_sport: Counter = Counter()
    trainer_by_device: Counter = Counter()
    gym_days: list[str] = []
    whoop_on_gym_day = 0
    watch_rows = 0
    folds = 0
    for d in days(since, until):
        acts = [a for a in load_day(s3, d) if a.get("strava_id") not in seen]
        for a in acts:
            seen.add(a.get("strava_id"))
        if not acts:
            continue
        folds += fold_count(acts)
        devices = [str(a.get("device_name") or "(none)") for a in acts]
        for a, dev in zip(acts, devices):
            by_device[dev] += 1
            by_device_sport[f"{dev} / {a.get('sport_type') or a.get('type') or '?'}"] += 1
            if a.get("trainer") in (True, "True", "true"):
                trainer_by_device[dev] += 1
        if "Hevy" in devices:
            gym_days.append(d.isoformat())
            whoop_on_gym_day += devices.count("WHOOP")
        watch_rows += sum(1 for dev in devices if dev.startswith(WATCH_PREFIX))
    return {
        "since": since.isoformat(),
        "until_exclusive": until.isoformat(),
        "activities": len(seen),
        "by_device": dict(by_device.most_common()),
        "by_device_sport": dict(by_device_sport.most_common()),
        "trainer_true_by_device": dict(trainer_by_device),
        "gym_days": gym_days,
        "whoop_rows_on_gym_days": whoop_on_gym_day if gym_days else None,
        "watch_rows": watch_rows,
        "seam_fold_count": folds,
    }


def missing_activity_max(cloudwatch, since: date, until: date) -> list[float]:
    """Daily Maximum of `MissingActivityCount{Source=strava}` (one value per datapoint, oldest first)."""
    resp = cloudwatch.get_metric_statistics(
        Namespace="LifePlatform/IngestReconciliation",
        MetricName="MissingActivityCount",
        Dimensions=[{"Name": "Source", "Value": "strava"}],
        StartTime=datetime(since.year, since.month, since.day, tzinfo=timezone.utc),
        EndTime=datetime(until.year, until.month, until.day, tzinfo=timezone.utc),
        Period=86400,
        Statistics=["Maximum"],
    )
    return [float(p["Maximum"]) for p in sorted(resp.get("Datapoints", []), key=lambda p: p["Timestamp"])]


def build_report(s3, cloudwatch, since: date, until: date) -> dict:
    span = (until - since).days
    base_since, base_until = since - timedelta(days=span), since
    window, baseline = read_window(s3, since, until), read_window(s3, base_since, base_until)
    window["missing_activity_daily_max"] = missing_activity_max(cloudwatch, since, until)
    baseline["missing_activity_daily_max"] = missing_activity_max(cloudwatch, base_since, base_until)
    return {"window": window, "baseline": baseline}


def render(report: dict) -> str:
    out = []
    for label in ("baseline", "window"):
        w = report[label]
        out.append(f"== {label}: {w['since']} .. {w['until_exclusive']} (exclusive) — {w['activities']} distinct activities")
        out.append("  by uploader (device_name): " + ", ".join(f"{k} {v}" for k, v in w["by_device"].items()))
        out.append("  trainer:true by uploader: " + (", ".join(f"{k} {v}" for k, v in w["trainer_true_by_device"].items()) or "none"))
        out.append(f"  gym days (Hevy push present): {len(w['gym_days'])} {w['gym_days']}")
        wg = w["whoop_rows_on_gym_days"]
        out.append(f"  WHOOP rows on gym days: {'n/a (no gym day in the window)' if wg is None else wg}")
        out.append(f"  watch ({WATCH_PREFIX}) rows: {w['watch_rows']}")
        out.append(f"  seam fold count (duplicate_activity_count summed): {w['seam_fold_count']}")
        out.append(f"  MissingActivityCount{{Source=strava}} daily max: {w['missing_activity_daily_max']}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", required=True, type=date.fromisoformat, help="first local day, inclusive")
    ap.add_argument("--until", required=True, type=date.fromisoformat, help="last local day, exclusive")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    import boto3

    report = build_report(boto3.client("s3", region_name=REGION), boto3.client("cloudwatch", region_name=REGION), args.since, args.until)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
