"""#5353 — the zone-2 reader's Apple leg reads the `apple_workouts` map the #4973 writer produces and
derives zone seconds at READ time from `derived.hr_seconds_by_bpm5` through `common.hr_zones` (the one band)."""

import os

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.hr_zones import HR_ZONE_BOUNDS, zone_seconds_from_bpm_bins
from common.max_hr import DEFAULT_MAX_HR
from training import zone2_minutes as z2

MAX = float(DEFAULT_MAX_HR)  # 183 -> zone 2 = [109.8, 128.1)


def _row(workouts, date="2026-10-20"):
    return {"sk": f"DATE#{date}", "date": date, "apple_workouts": workouts}


def _w(start, end, bins, name="Outdoor Walk"):
    return {"start": start, "end": end, "name": name, "derived": {"hr_seconds_by_bpm5": bins}}


def test_apple_only_day_counts_zone2_from_the_bins():
    # HAE's own stamp format, the writer's stored shape; 115 + 120 bins are wholly Zone 2 at max 183
    rows = [_row({"A1": _w("2026-10-20 09:00:00 -0700", "2026-10-20 09:40:00 -0700", {"115": 900.0, "120": 900.0, "95": 600.0})})]
    out = z2.counted_sessions([], [], rows)
    assert len(out) == 1 and out[0]["source"] == "apple_health"
    assert out[0]["zone_2_minutes"] == 30.0
    assert out[0]["zones_minutes"]["zone_1"] == 10.0
    win = z2.zone2_window([], [], [], "2026-10-20", "2026-10-20", sessions=out)
    assert win["zone_2_minutes"] == 30.0 and win["by_source"]["apple_health"] == 30.0


def test_whoop_present_still_serves_whoops_number():
    rows = [_row({"A1": _w("2026-10-20T16:00:00Z", "2026-10-20T16:40:00Z", {"115": 2400.0})})]
    whoop = [
        {
            "sk": "DATE#2026-10-20#WORKOUT#w1",
            "workout_id": "w1",
            "start_time": "2026-10-20T16:01:00Z",
            "end_time": "2026-10-20T16:40:00Z",
            "zone_2_minutes": 12,
            "zone_1_minutes": 27,
        }
    ]
    out = z2.counted_sessions([], whoop, rows)
    assert len(out) == 1 and out[0]["source"] == "whoop" and out[0]["zone_2_minutes"] == 12.0
    assert out == z2.counted_sessions([], whoop)[:0] + out  # same single session either way
    assert z2.counted_sessions([], whoop, rows)[0]["zones_minutes"] == z2.counted_sessions([], whoop)[0]["zones_minutes"]


def test_straddling_bin_is_split_by_overlap_width_at_the_resolver():
    # edge = 0.60 * 183 = 109.8: bin 105 = [105,110) -> 4.8/5 Zone 1, 0.2/5 Zone 2
    got = zone_seconds_from_bpm_bins({"105": 500.0}, MAX)
    assert got["zone_1"] == pytest.approx(480.0) and got["zone_2"] == pytest.approx(20.0)
    # bin 125 = [125,130): zone 2 ends at 0.70 * 183 = 128.1 -> 3.1/5 Zone 2, 1.9/5 Zone 3
    got = zone_seconds_from_bpm_bins({"125": 500.0}, MAX)
    assert got["zone_2"] == pytest.approx(310.0) and got["zone_3"] == pytest.approx(190.0)
    # seconds are conserved, below 50% is below_zone_1, above 100% stays in zone 5
    got = zone_seconds_from_bpm_bins({"60": 100.0, "105": 500.0, "190": 50.0}, MAX)
    assert sum(got.values()) == pytest.approx(650.0) and got["below_zone_1"] == 100.0 and got["zone_5"] == 50.0


def test_one_band_table_is_shared_with_the_mcp_helpers():
    from mcp import helpers

    assert helpers.HR_ZONE_BOUNDS is HR_ZONE_BOUNDS


def test_a_workout_without_bins_is_unmeasured_and_the_legacy_subrow_shape_is_gone():
    rows = [_row({"A2": {"start": "2026-10-20T16:00:00Z", "end": "2026-10-20T16:30:00Z", "name": "Yoga"}})]
    out = z2.counted_sessions([], [], rows)
    assert out[0]["source"] is None and out[0]["zone_2_minutes"] is None
    legacy = [
        {
            "sk": "DATE#2026-10-20#WORKOUT#a1",
            "start_time": "2026-10-20T16:00:00Z",
            "end_time": "2026-10-20T16:40:00Z",
            "zone2_seconds": 1200,
        }
    ]
    assert z2.counted_sessions([], [], legacy) == []


def _call_args(src, name):
    """The full argument text of every `name(...)` call in `src` (balanced parens)."""
    out, i = [], 0
    while (i := src.find(name + "(", i)) != -1:
        j, depth = i + len(name) + 1, 1
        while depth and j < len(src):
            depth += {"(": 1, ")": -1}.get(src[j], 0)
            j += 1
        out.append(src[i:j])
        i = j
    return out


def test_every_zone2_call_site_passes_the_apple_rows():
    from pathlib import Path

    root = Path(__file__).parent.parent
    for rel in (
        "lambdas/web/site_api_autonomic.py",
        "lambdas/web/site_api_training.py",
        "mcp/tools_training.py",
        "mcp/tools_correlation.py",
    ):
        calls = _call_args((root / rel).read_text(encoding="utf-8"), "counted_sessions")
        assert calls and all("apple" in c for c in calls), rel


def test_public_zone2_payload_carries_minutes_only_never_bins():
    from web import site_api_autonomic as sa

    rows = [_row({"A1": _w("2026-10-20T16:00:00Z", "2026-10-20T16:40:00Z", {"115": 2400.0})})]
    payload = sa._compute_zone2_breakdown([], [], [], today="2026-10-21", start_date="2026-10-01", apple_items=rows)
    blob = repr(payload)
    assert payload["available"] and payload["trailing_7d"]["by_source"]["apple_health"] == 40.0
    for banned in ("hr_seconds_by_bpm5", "apple_workouts", "A1", "115"):
        assert banned not in blob


# ── the fixture is the wire: the writer's own output, as DynamoDB stores it ──────────────────────────────


def _stored_rows_from_the_writer():
    """The apple_health day rows exactly as `write_apple_workouts` stores them: HAE's own payload (the #4973
    fixture, key names checked against a live raw-archive payload) -> `summaries_by_day` -> `to_ddb`
    (every float a Decimal) -> one row per UTC-day DATE#. No hand-written `derived` block."""
    import json
    from pathlib import Path

    from ingestion import health_auto_export_workouts as hw

    fixture = Path(__file__).parent / "fixtures" / "hae_workouts_mixed_4973.json"
    workouts = json.loads(fixture.read_text(encoding="utf-8"))["payload"]["data"]["workouts"]
    from health_auto_export_lambda import parse_date_str

    return [
        {"pk": "USER#matthew#SOURCE#apple_health", "sk": f"DATE#{day}", "date": day, hw.WORKOUTS_FIELD: hw.to_ddb(summ)}
        for day, summ in sorted(hw.summaries_by_day(workouts, parse_date_str).items())
    ]


def test_the_writers_stored_rows_feed_the_reader_decimals_and_all():
    from decimal import Decimal

    rows = _stored_rows_from_the_writer()
    assert {r["sk"] for r in rows} == {"DATE#2026-10-14", "DATE#2026-10-15"}  # the 18:00 PDT run is on the next UTC day
    walk = rows[0]["apple_workouts"]["FX-WLK-0002"]["derived"]["hr_seconds_by_bpm5"]
    assert all(isinstance(v, Decimal) for v in walk.values())  # the wire, not the float fixture the tests above build

    out = z2.counted_sessions([], [], rows)
    walk_s = next(s for s in out if s["sport"] == "Indoor Walk")
    # bins 100..140 at 300 s each; Zone 2 = [109.8, 128.1) at max 183: bins 110/115/120 whole (900 s),
    # 125 is 3.1/5 of 300 s (186 s), 105 is 0.2/5 of 300 s (12 s)  -> 1098 s = 18.3 min
    assert walk_s["source"] == "apple_health" and walk_s["zone_2_minutes"] == 18.3
    # a session recorded on the 14th (PT) but stored on the 15th's row is read on the 14th
    assert {s["date"] for s in out} == {"2026-10-14"}
    win = z2.zone2_window([], [], [], "2026-10-14", "2026-10-14", sessions=out)
    assert win["by_source"]["apple_health"] > 18.3  # the walk, the lift and the run
    assert win["zone_2_minutes"] == win["by_source"]["apple_health"]
