#!/usr/bin/env python3
"""scripts/resolve_steps_day_4630.py — reproduce ONE day's resolved steps (and the movement score built
on them) from the stored DynamoDB rows, and say which source won and why (#4630 box 4).

READ-ONLY. Four GetItem reads on the day's DATE# rows — whoop, apple_health, garmin (the registry's
`METRIC_TRUTH["steps"]` fallback order) and strava (the exercise half of the movement score) — plus the
profile row (`step_target`) and the stored day grade (`component_movement`). Nothing is written,
nothing is invoked, no model is called. The steps come from `common.metric_truth.resolve_steps` — the
SAME resolver every reader calls — and the score from `health.scoring_engine.score_movement`, so this
command cannot resolve the day differently from the day grade.

Output is counts only (no record keys): each source's candidate count, the winner and the reason, the
movement score recomputed under the resolver, and the stored component for comparison. A stored
component computed before the resolver shipped reads Apple's `steps` alone, so the two can differ
on a day the wrist out-counted the phone — the comparison line says so rather than hiding it.

RUN:  AWS_MAX_ATTEMPTS=1 python3 scripts/resolve_steps_day_4630.py --date 2026-10-14
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.digest_utils import d2f  # noqa: E402
from common.metric_truth import resolve_steps, steps_sources  # noqa: E402
from common.strava_read_seam import strava_read_seam  # noqa: E402
from health.scoring_engine import score_movement  # noqa: E402

USER = os.environ["USER_ID"]


def _row(table: Any, source: str, day: str) -> Optional[dict]:
    item = table.get_item(Key={"pk": f"USER#{USER}#SOURCE#{source}", "sk": f"DATE#{day}"}).get("Item")
    return strava_read_seam(source, d2f(item)) if item else None


def explain_day(table: Any, day: str) -> list[str]:
    """The report lines for `day` — pure over `table.get_item`, so a fake table drives it in tests."""
    rows = {src: _row(table, src, day) for src in steps_sources()}
    res = resolve_steps(rows)
    out = [f"date {day}  (metric steps, precedence {' > '.join(steps_sources())})"]
    for src in steps_sources():
        state = "no row" if rows[src] is None else ("no usable count" if res.candidates[src] is None else f"{res.candidates[src]:,.0f}")
        out.append(f"  {src:<13} {state}")
    out.append(f"resolved {('%d' % res.count) if res.count is not None else 'none'} from {res.source or '-'} — {res.reason}")
    profile = d2f(table.get_item(Key={"pk": f"USER#{USER}", "sk": "PROFILE#v1"}).get("Item") or {})
    data = {
        "whoop": rows.get("whoop"),
        "apple": rows.get("apple_health"),
        "garmin": rows.get("garmin"),
        "strava": _row(table, "strava", day),
    }
    score, details = score_movement(data, profile)
    out.append(
        f"movement {score} = exercise {details.get('exercise_score')} x0.50 + steps {details.get('step_score')} x0.50 "
        f"(step_target {profile.get('step_target', 7000)})"
    )
    stored = (d2f(table.get_item(Key={"pk": f"USER#{USER}#SOURCE#day_grade", "sk": f"DATE#{day}"}).get("Item") or {})).get(
        "component_movement"
    )
    if stored is None:
        out.append("stored component_movement: none")
    else:
        same = "matches" if float(stored) == float(score or -1) else "differs — the stored grade predates the resolver or read other rows"
        out.append(f"stored component_movement {stored:g} ({same})")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", required=True, help="the DATE# day to reproduce, YYYY-MM-DD")
    args = ap.parse_args(argv)
    import boto3  # deferred: the pure path above is testable without AWS

    table = boto3.resource("dynamodb", region_name=os.environ["AWS_DEFAULT_REGION"]).Table(os.environ["TABLE_NAME"])
    print("\n".join(explain_day(table, args.date)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
