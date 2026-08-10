#!/usr/bin/env python3
"""strava_type_census.py — the activity-type census the population rule is derived from (#2331).

`lambdas/ingestion/strava_population.py` decides, per Strava activity type, whether
distance and elevation are *measurements of that activity* (so a `0` is a value) or
metrics the activity does not have (so absence is the honest storage). That decision
is only trustworthy if the type set it covers is the set ingestion actually produces —
a hand-typed list silently omits whatever the athlete did last month.

So the type set is machine-derived: this script reads every stored Strava day
(read-only DDB query, no writes anywhere) and emits the census to
``config/strava_activity_type_census.json``. ``tests/test_strava_population.py``
then asserts that every censused type carries an explicit decision, which is what
turns "we thought about the types" into "no observed type is undecided".

Usage::

    python3 scripts/strava_type_census.py                 # print the census
    python3 scripts/strava_type_census.py --write         # refresh the committed JSON

Re-run it when a new sport shows up in the archive; if the census gains a type the
registry does not decide, the test goes red and the decision gets made deliberately.
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

CENSUS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "strava_activity_type_census.json")

USER_ID = os.environ.get("USER_ID", "matthew")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")


def _activity_type(activity: dict) -> str:
    return str(activity.get("sport_type") or activity.get("type") or "").strip() or "Unknown"


def collect() -> dict:
    """Query every stored Strava day and tally activity types. Read-only."""
    import boto3
    from boto3.dynamodb.conditions import Key

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    kwargs = {"KeyConditionExpression": Key("pk").eq(f"USER#{USER_ID}#SOURCE#strava")}
    items = []
    while True:
        page = table.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    counts: Counter = Counter()
    dist_zero: Counter = Counter()
    elev_zero: Counter = Counter()
    activity_total = 0
    for item in items:
        for act in item.get("activities") or []:
            activity_total += 1
            t = _activity_type(act)
            counts[t] += 1
            d = act.get("distance_meters")
            if d is not None and float(d) == 0:
                dist_zero[t] += 1
            e = act.get("total_elevation_gain_meters")
            if e is not None and float(e) == 0:
                elev_zero[t] += 1

    return {
        "_provenance": {
            "generated_by": "scripts/strava_type_census.py",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": f"DynamoDB {TABLE_NAME} pk=USER#{USER_ID}#SOURCE#strava (read-only query)",
            "day_records": len(items),
            "activities": activity_total,
            "note": "Every type listed here MUST carry an explicit decision in lambdas/ingestion/strava_population.py.",
        },
        "types": {
            t: {"activities": n, "zero_distance": dist_zero[t], "zero_elevation": elev_zero[t]}
            for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help=f"overwrite {CENSUS_PATH}")
    args = ap.parse_args()

    census = collect()
    text = json.dumps(census, indent=2) + "\n"
    if args.write:
        with open(CENSUS_PATH, "w") as fh:
            fh.write(text)
        print(f"wrote {CENSUS_PATH}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
