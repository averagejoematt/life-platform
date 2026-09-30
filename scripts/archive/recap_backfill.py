#!/usr/bin/env python3
"""scripts/recap_backfill.py — the back-catalogue, Day 1 to yesterday (#3741).

THE ASK

*"i also want to generate all for the experiment to date so i can post retroactively…
Right now, if it's day 8, I'd have had 8 visuals that I can just quickly generate and then
post each one."*

WHY --check EXISTS AND RUNS FIRST

`computed_metrics` for Day D is written by the compute cron on Day D+1, so the earliest
days of a cycle may simply not have a row — and a card rendered from a missing row is
either nothing (the honest outcome) or, if anyone ever defaults a None to a zero, a public
lie about a day that is over and cannot be re-lived. So the first mode prints what is
actually there, per day, per partition. The check is the answer; the render is what you do
about it.

USAGE
    python3 scripts/recap_backfill.py --check
    python3 scripts/recap_backfill.py --invoke                # render + store, send nothing
    python3 scripts/recap_backfill.py --invoke --deliver      # render + send
    python3 scripts/recap_backfill.py --invoke --date 2026-09-08 --force

Renders run through the deployed Lambda rather than locally: the card that reaches
Instagram should be the one the schedule will produce every morning, not one this laptop
produced once with a different Pillow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

REGION = os.environ.get("AWS_REGION", "us-west-2")
FUNCTION = os.environ.get("RECAP_FUNCTION", "recap-card-generator")
TABLE = os.environ.get("TABLE_NAME", "life-platform")

#: The partitions a card can be built from. `computed_metrics` and `habit_scores` are
#: single-row-per-day; the rest are queried by prefix.
DAY_ROW_SOURCES = ["computed_metrics", "habit_scores", "strava", "macrofactor", "withings"]
PREFIX_SOURCES = ["hevy", "notion"]


def _dates(start: str, end: str) -> list[str]:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _presence(table, day: str) -> dict[str, str]:
    from boto3.dynamodb.conditions import Key

    out: dict[str, str] = {}
    for src in DAY_ROW_SOURCES:
        try:
            item = table.get_item(Key={"pk": f"USER#matthew#SOURCE#{src}", "sk": f"DATE#{day}"}).get("Item")
            out[src] = "yes" if item else "—"
        except Exception as e:  # noqa: BLE001
            out[src] = f"ERR:{type(e).__name__}"
    for src in PREFIX_SOURCES:
        try:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"USER#matthew#SOURCE#{src}") & Key("sk").begins_with(f"DATE#{day}"),
                Limit=5,
            )
            n = len(resp.get("Items", []))
            out[src] = str(n) if n else "—"
        except Exception as e:  # noqa: BLE001
            out[src] = f"ERR:{type(e).__name__}"
    return out


def cmd_check(args) -> int:
    import boto3
    from common.constants import EXPERIMENT_START_DATE
    from common.pacific_time import pacific_day_n

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    days = _dates(args.start or EXPERIMENT_START_DATE, args.end)

    cols = DAY_ROW_SOURCES + PREFIX_SOURCES
    print(f"{'date':<12} {'day':>4}  " + "  ".join(f"{c[:8]:>8}" for c in cols))
    print("-" * (18 + 10 * len(cols)))
    for day in days:
        p = _presence(table, day)
        n = pacific_day_n(EXPERIMENT_START_DATE, day)
        print(f"{day:<12} {n:>4}  " + "  ".join(f"{p[c]:>8}" for c in cols))
    print(
        "\ncomputed_metrics for day D is written by the compute cron on D+1 — a '—' on the most "
        "recent row is expected, not a fault. A '—' further back is a day the card will honestly "
        "decline to draw."
    )
    return 0


def cmd_invoke(args) -> int:
    import boto3
    from common.constants import EXPERIMENT_START_DATE

    lam = boto3.client("lambda", region_name=REGION)
    days = [args.date] if args.date else _dates(args.start or EXPERIMENT_START_DATE, args.end)

    print(f"{'date':<12} {'outcome':<18} chosen")
    print("-" * 60)
    failures = 0
    for day in days:
        payload = {"date": day, "deliver": bool(args.deliver), "force": bool(args.force)}
        try:
            resp = lam.invoke(FunctionName=FUNCTION, InvocationType="RequestResponse", Payload=json.dumps(payload).encode())
            body = json.loads(resp["Payload"].read() or b"{}")
        except Exception as e:  # noqa: BLE001
            print(f"{day:<12} {'INVOKE FAILED':<18} {type(e).__name__}: {e}")
            failures += 1
            continue
        if body.get("FunctionError") or "errorMessage" in body:
            print(f"{day:<12} {'ERROR':<18} {str(body)[:90]}")
            failures += 1
            continue
        out = body.get("body") or body
        outcome = out.get("outcome") or out.get("status") or "?"
        chosen = ",".join(out.get("chosen") or []) or "-"
        delivered = out.get("delivered") or {}
        extra = f"  delivered={delivered}" if delivered else ""
        print(f"{day:<12} {outcome:<18} {chosen}{extra}")
        if outcome in ("held", "blocked"):
            failures += 1
    if failures:
        print(f"\n{failures} day(s) did not produce a sent card — read the rows above before re-running.")
    return 1 if failures else 0


def main() -> int:
    from common.pacific_time import pacific_now

    yesterday = (pacific_now().date() - timedelta(days=1)).isoformat()

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="print per-day data presence and exit")
    ap.add_argument("--invoke", action="store_true", help="invoke the deployed Lambda for each day")
    ap.add_argument("--deliver", action="store_true", help="with --invoke: actually send (default: render and store only)")
    ap.add_argument("--force", action="store_true", help="re-render a day that already delivered")
    ap.add_argument("--date", help="a single date instead of the range")
    ap.add_argument("--start", help="range start (default: the experiment genesis)")
    ap.add_argument("--end", default=yesterday, help="range end (default: yesterday PT — today is not a finished day)")
    args = ap.parse_args()

    if args.check:
        return cmd_check(args)
    if args.invoke:
        return cmd_invoke(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
