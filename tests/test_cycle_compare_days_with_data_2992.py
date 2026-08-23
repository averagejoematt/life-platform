"""#2992: cycle_compare's `days_with_data` counts distinct DATES, never distinct SKs.

The live defect (2026-08-22): whoop stores workout sub-rows
(`DATE#YYYY-MM-DD#WORKOUT#<uuid>`) whose SKs fall lexicographically inside the
daily-row `between()` range, so counting distinct SKs inflated the matched-window
"Days with data" past the window itself — the reader-truth oracle caught cycle 14
claiming 8 days of data on Day 6, and cycle 1 claimed 16 in the same 6-day window.

The invariant under test: for every cycle, days_with_data is the number of
distinct calendar dates with at least one row from either source, and can never
exceed window_days.
"""

import json
from datetime import datetime, timedelta

from web import site_api_rollups
from web.site_api_common import PT


def _fixture_g(geneses, rows_by_source):
    """Minimal `_g` facade: fixed geneses, canned query results, no pre-start."""

    def _query_source(source, start, end, include_pilot=False):
        # Reproduce the real between() semantics: lexicographic SK range, which is
        # exactly what lets `DATE#<date>#WORKOUT#...` sub-rows into a daily window.
        lo, hi = f"DATE#{start}", f"DATE#{end}"
        return [r for r in rows_by_source.get(source, ()) if lo <= r["sk"] <= hi + "￿"]

    return {
        "CYCLE_GENESES": geneses,
        "_query_source": _query_source,
        "pre_start_meta": lambda: None,
    }


def test_workout_subrows_do_not_inflate_days_with_data():
    today = datetime.now(PT).date()
    genesis = (today - timedelta(days=5)).isoformat()  # Day 6 of the cycle → window 6

    d1 = genesis
    d2 = (today - timedelta(days=4)).isoformat()
    whoop = [
        {"sk": f"DATE#{d1}", "recovery_score": 50, "sleep_duration_hours": 7.0},
        {"sk": f"DATE#{d2}", "recovery_score": 60, "sleep_duration_hours": 7.5},
        # Two workout sub-rows on d2 — the live inflation shape.
        {"sk": f"DATE#{d2}#WORKOUT#5c539cdb-08c2-40cb-bed2-46a9420a9c4e"},
        {"sk": f"DATE#{d2}#WORKOUT#73448a5f-bc43-4eb2-b5a4-b81fc2cee235"},
    ]
    withings = [
        {"sk": f"DATE#{d1}", "weight_lbs": 300.0},
    ]

    resp = site_api_rollups.cycle_compare(_g=_fixture_g({1: genesis}, {"whoop": whoop, "withings": withings}))
    body = json.loads(resp["body"])

    (cycle,) = body["cycles"]
    # 2 distinct dates carry data (d1, d2) — the 2 sub-rows on d2 add nothing.
    assert cycle["days_with_data"] == 2, cycle


def test_days_with_data_never_exceeds_window():
    today = datetime.now(PT).date()
    genesis = (today - timedelta(days=5)).isoformat()  # window 6

    # A dense cycle: a daily row AND a workout sub-row on every one of the 6 days.
    whoop = []
    for i in range(6):
        d = (datetime.strptime(genesis, "%Y-%m-%d").date() + timedelta(days=i)).isoformat()
        whoop.append({"sk": f"DATE#{d}", "recovery_score": 55, "sleep_duration_hours": 7.2})
        whoop.append({"sk": f"DATE#{d}#WORKOUT#aaaaaaaa-0000-0000-0000-{i:012d}"})

    resp = site_api_rollups.cycle_compare(_g=_fixture_g({1: genesis}, {"whoop": whoop, "withings": []}))
    body = json.loads(resp["body"])

    (cycle,) = body["cycles"]
    assert cycle["days_with_data"] == 6, cycle
    assert cycle["days_with_data"] <= body["window_days"], (cycle, body["window_days"])
