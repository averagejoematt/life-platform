#!/usr/bin/env python3
"""scripts/zone2_week_rebuild_4627.py — rebuild a week's Zone 2 minutes from the stored rows and
print the per-source, per-day table (#4627 box 3). READ-ONLY.

WHAT IT DOES. Reads the stored Strava day rows, the Whoop workout sub-rows and the Hevy workout rows
for [--start, --start + 6] (DynamoDB QUERY only — the same key ranges and the same derived-read rules
the site API's ``_query_source`` uses: ``strava_read_seam`` over Strava, superseded ``tombstone`` rows
dropped), then runs ``training.zone2_minutes.zone2_window`` — the ONE computation
``/api/training_overview``, ``/api/zone2`` and the MCP ``get_zone2_breakdown`` serve — and prints:

  * one row per date: Whoop Zone 2 min, Strava Zone 2 min, the counted total, Hevy cardio min
    (reported, never added to Zone 2) and the sessions with no stored time-in-zone;
  * the window totals: Zone 2 by source, the zone distribution, sessions counted / unmeasured.

The Whoop query is widened by one day on each side because Whoop rows are keyed by their UTC day
while the window is Pacific; the computation re-dates each workout from its ``start_time``.

``--whoop-from-archive`` (S3 GetObject, read-only) overlays each Whoop workout's zone fields IN
MEMORY with what the raw archive says, through ``whoop_lambda.zone_minutes_from_score`` — the
writer's own helper since #4629. Stored Whoop rows written before PR #4922 carry six fabricated
zeros (unmeasured here); this flag shows what the same computation returns once #4629's write-back
lands. Nothing is written back.

There is no write mode, and no workout ids are printed (``--sessions`` prints the per-session lines
with source, sport and minutes only).

RUN:  AWS_MAX_ATTEMPTS=1 python3 scripts/zone2_week_rebuild_4627.py --start 2026-09-28
      AWS_MAX_ATTEMPTS=1 python3 scripts/zone2_week_rebuild_4627.py --start 2026-09-28 --whoop-from-archive --sessions
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.strava_read_seam import strava_read_seam  # noqa: E402
from training.zone2_minutes import ZONE_KEYS, trailing_window, zone2_window  # noqa: E402

_COLS = ("date", "whoop", "strava", "zone_2_minutes", "hevy_cardio_minutes", "unmeasured_sessions")


def _plain(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


def _query(table, source: str, start: str, end: str) -> list:
    from boto3.dynamodb.conditions import Key

    kwargs = {
        "KeyConditionExpression": Key("pk").eq(f"USER#{os.environ['USER_ID']}#SOURCE#{source}")
        & Key("sk").between(f"DATE#{start}", f"DATE#{end}~")
    }
    rows: list = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    rows = [r for r in _plain(rows) if not r.get("tombstone")]
    return strava_read_seam(source, rows)


def overlay_archive_zones(whoop_rows: list, payloads: dict) -> list:
    """Whoop workout rows with zone fields replaced (in memory) by the archive's recomputation."""
    from ingestion.whoop_lambda import zone_minutes_from_score

    by_id = {}
    for payload in payloads.values():
        for rec in ((payload or {}).get("raw") or {}).get("workouts", {}).get("records") or []:
            by_id[str(rec.get("id"))] = {k: float(v) for k, v in zone_minutes_from_score(rec.get("score")).items()}
    out = []
    for row in whoop_rows:
        sk = str(row.get("sk", ""))
        if "#WORKOUT#" in sk:
            wid = str(row.get("workout_id") or sk.split("#WORKOUT#", 1)[1])
            if wid in by_id:
                row = {k: v for k, v in row.items() if not k.startswith("zone_")} | by_id[wid]
        out.append(row)
    return out


def render(result: dict, sessions: bool = False) -> str:
    lines = [f"Zone 2 rebuild {result['start_date']} .. {result['end_date']} ({result['dates']} dates) — {result['definition']}", ""]
    lines.append("  ".join(f"{c:>19}" if i else f"{c:<10}" for i, c in enumerate(_COLS)))
    for row in result["by_day"]:
        lines.append("  ".join(f"{row[c]:>19}" if i else f"{row[c]:<10}" for i, c in enumerate(_COLS)))
    bs = result["by_source"]
    lines += [
        "",
        f"TOTAL zone_2_minutes={result['zone_2_minutes']}  (whoop={bs['whoop']}  strava={bs['strava']})",
        f"hevy_cardio_minutes={result['hevy_cardio_minutes']} over {result['hevy_cardio_blocks']} blocks (reported, NOT Zone 2)",
        f"sessions_counted={result['sessions_counted']}  unmeasured_sessions={result['unmeasured_sessions']} ({result['unmeasured_minutes']} min, no stored time-in-zone)",
        "zones_minutes " + "  ".join(f"{k}={result['zones_minutes'][k]}" for k in ZONE_KEYS),
    ]
    if sessions:
        lines.append("")
        for s in result["sessions"]:
            used = ",".join(sorted({u.split(":", 1)[0] for u in s["used_ids"]})) or "-"
            lines.append(
                f"  {s['date']}  {str(s['sport'])[:18]:<18} dur={s['duration_minutes']:>6} min  z2={s['zone_2_minutes']}  "
                f"from={s['source'] or 'unmeasured'}  recordings={len(s['ids'])} ({used} used)"
            )
    return "\n".join(lines)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", required=True, help="first date of the week (YYYY-MM-DD)")
    ap.add_argument("--whoop-from-archive", action="store_true", help="overlay Whoop zones from the raw archive (S3 read-only)")
    ap.add_argument("--sessions", action="store_true", help="also print one line per counted session")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args(argv)

    start = date.fromisoformat(args.start)
    w_start, w_end = trailing_window((start + timedelta(days=6)).isoformat())
    pad_lo, pad_hi = (start - timedelta(days=1)).isoformat(), (start + timedelta(days=7)).isoformat()

    import boto3

    region = os.environ["AWS_DEFAULT_REGION"]
    table = boto3.resource("dynamodb", region_name=region).Table(os.environ["TABLE_NAME"])
    strava = _query(table, "strava", w_start, w_end)
    whoop = _query(table, "whoop", pad_lo, pad_hi)
    hevy = _query(table, "hevy", w_start, w_end)
    if args.whoop_from_archive:
        from ingestion.source_registry import raw_date_key

        s3 = boto3.client("s3", region_name=region)
        payloads = {}
        d = start - timedelta(days=1)
        while d <= start + timedelta(days=7):
            try:
                payloads[d.isoformat()] = json.loads(
                    s3.get_object(Bucket=os.environ["S3_BUCKET"], Key=raw_date_key("whoop", d.isoformat()))["Body"].read()
                )
            except s3.exceptions.NoSuchKey:
                payloads[d.isoformat()] = None
            d += timedelta(days=1)
        whoop = overlay_archive_zones(whoop, payloads)
    result = zone2_window(strava, whoop, hevy, w_start, w_end)
    print(json.dumps(result, indent=2, default=str) if args.json else render(result, sessions=args.sessions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
