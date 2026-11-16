"""tests/test_strava_ingest_capture_all_5696.py — #5696: the Strava ingest stores every activity.

Until #5696 `strava_lambda._dedup` dropped any activity starting within 120 s of another, of any
sport, and on a richness tie kept the earlier one. 7 vendor activities in the 90 days to
2026-11-10 were never stored — among them the Apple Watch Ultra 4's own 10-18 walk (4163 s,
2.95 km), dropped for a 17-minute WHOOP chunk of the same walk. The capture-all ruling (10-04)
and docs/SCHEMA.md say copies are STORED and resolved at the read seam; these tests pin that:

  * the ingest's `fetch_day` keeps every activity the vendor lists, near-simultaneous or not;
  * `common.strava_read_seam` then keeps the watch's recording — over a WHOOP chunk (richness),
    over Hevy's push of the same session (the ECHO RULE), and beside a Hevy push of a DIFFERENT
    sport (a gym ride is not a copy of the lift);
  * a partial WHOOP chunk still loses to the Hevy push it is a piece of (#4627, unchanged);
  * the two readers inside `lambdas/ingestion/` that the #4419 AST guard does not sweep are
    safe: the enricher's percentile population goes through the seam, and reconcile no longer
    lets a stored sibling hide a vendor activity the store lacks.

The activity shapes are the live vendor records (ids, starts, durations, devices) read
read-only from the Strava API on 2026-11-10; names are stripped.
"""

import os

for _k, _v in {"S3_BUCKET": "t", "TABLE_NAME": "life-platform", "USER_ID": "matthew", "AWS_DEFAULT_REGION": "us-west-2"}.items():
    os.environ.setdefault(_k, _v)

from common import strava_read_seam as seam  # noqa: E402
from ingestion import strava_lambda as strava  # noqa: E402

DAY = "2026-10-18"


def _api(id_, sport, start_utc, start_local, elapsed, distance, device, has_hr=True):
    """A raw Strava list-endpoint activity (the shape `fetch_day` receives)."""
    return {
        "id": id_,
        "name": sport,
        "sport_type": sport,
        "type": sport,
        "start_date": start_utc,
        "start_date_local": start_local,
        "elapsed_time": elapsed,
        "moving_time": elapsed,
        "distance": distance,
        "has_heartrate": has_hr,
        "device_name": device,
        "map": {"summary_polyline": ""},
    }


# 2026-10-18, live: the watch's own walk, and WHOOP's auto-detected 17 min of it 116 s later.
WATCH_WALK = _api(20669445621, "Walk", "2026-10-18T22:01:04Z", "2026-10-18T15:01:04Z", 4163, 2952.9, "Apple Watch Ultra 4")
WHOOP_WALK = _api(20641189677, "Walk", "2026-10-18T22:03:00Z", "2026-10-18T15:03:00Z", 1019, 0.0, "WHOOP")
# 2026-10-19, live: Hevy's push of the lift, and WHOOP's 19-minute chunk of it 68 s later.
HEVY_LIFT_1019 = _api(20647779260, "WeightTraining", "2026-10-19T12:18:52Z", "2026-10-19T05:18:52Z", 7820, 0.0, "Hevy")
WHOOP_LIFT_1019 = _api(20646783818, "WeightTraining", "2026-10-19T12:20:00Z", "2026-10-19T05:20:00Z", 1139, 0.0, "WHOOP")


def _fetch_day(monkeypatch, acts, day=DAY):
    monkeypatch.setattr(strava, "_fetch_activities_in_range", lambda s, a, b: ([dict(x) for x in acts], s))
    monkeypatch.setattr(strava, "_fetch_activity_zones", lambda sid, s: ({}, s))
    monkeypatch.setattr(strava, "_fetch_activity_streams", lambda sid, s: ({}, s))
    monkeypatch.setattr(strava, "_stored_enrichment", lambda d: {})
    out = strava.fetch_day({"access_token": "x"}, day)
    return strava.transform(out, day)[0]


def _ids(acts):
    return sorted(a["strava_id"] for a in acts)


def test_the_ingest_stores_both_copies_of_a_near_simultaneous_pair(monkeypatch):
    row = _fetch_day(monkeypatch, [WATCH_WALK, WHOOP_WALK])
    assert _ids(row["activities"]) == ["20641189677", "20669445621"]
    assert row["activity_count"] == 2  # the stored row is verbatim; the seam restates the totals


def test_the_ingest_has_no_dedupe_left_to_call():
    assert not hasattr(strava, "_dedup"), "#5696: an ingest-time dedupe drops vendor activities before they are stored"


def test_the_seam_keeps_the_watch_walk_over_the_whoop_chunk_the_old_ingest_kept(monkeypatch):
    row = _fetch_day(monkeypatch, [WATCH_WALK, WHOOP_WALK])
    out = seam.strava_read_seam("strava", row)
    assert _ids(out["activities"]) == ["20669445621"]
    assert out["activity_count"] == 1 and out["duplicate_activity_count"] == 1
    assert out["total_moving_time_seconds"] == 4163


def test_the_seam_keeps_a_watch_ride_beside_a_hevy_push_starting_within_two_minutes(monkeypatch):
    """The issue's own case: a gym ride is a block of the lift, not a copy of it. The old ingest
    dropped whichever of the two was poorer; both are stored now and the seam keeps both
    (workout_identity places the ride inside the lift — #5697)."""
    hevy = _api(1, "WeightTraining", "2026-10-18T17:48:24Z", "2026-10-18T10:48:24Z", 9758, 0.0, "Hevy")
    ride = _api(2, "Ride", "2026-10-18T17:49:30Z", "2026-10-18T10:49:30Z", 1349, 0.0, "Apple Watch Ultra 4")
    row = _fetch_day(monkeypatch, [hevy, ride])
    assert _ids(row["activities"]) == ["1", "2"]
    assert _ids(seam.strava_read_seam("strava", row)["activities"]) == ["1", "2"]


def test_the_seam_picks_the_watch_recording_over_the_hevy_echo_of_the_same_session(monkeypatch):
    """The ECHO RULE. Hevy's push carries the LOGGED session length, so it is routinely a few
    seconds longer than the watch's recording of the same lift — and the richness score alone
    then keeps the echo. A device recording covering >= CONTAINMENT_SHARE of the push wins."""
    hevy = _api(1, "WeightTraining", "2026-10-18T17:48:24Z", "2026-10-18T10:48:24Z", 7820, 0.0, "Hevy")
    watch = _api(2, "WeightTraining", "2026-10-18T17:49:24Z", "2026-10-18T10:49:24Z", 7700, 0.0, "Apple Watch Ultra 4")
    row = _fetch_day(monkeypatch, [hevy, watch])
    a_hevy, a_watch = sorted(row["activities"], key=lambda a: a["strava_id"])
    assert seam._richness(a_hevy) > seam._richness(a_watch), "non-vacuity: richness alone would keep the echo"
    assert _ids(seam.strava_read_seam("strava", row)["activities"]) == ["2"]
    # order-independent: the rule does not depend on which copy starts first
    assert [a["strava_id"] for a in seam.dedup_activities([a_watch, a_hevy])] == ["2"]


def test_an_exact_richness_tie_keeps_the_recording_not_the_echo():
    hevy = {"strava_id": "1", "sport_type": "WeightTraining", "start_date": "2026-10-18T17:48:24Z", "device_name": "Hevy"}
    watch = {"strava_id": "2", "sport_type": "WeightTraining", "start_date": "2026-10-18T17:48:24Z", "device_name": "Garmin epix (Gen2)"}
    assert seam._richness(hevy) == seam._richness(watch)
    assert [a["strava_id"] for a in seam.dedup_activities([hevy, watch])] == ["2"]
    assert [a["strava_id"] for a in seam.dedup_activities([watch, hevy])] == ["2"]


def test_a_partial_whoop_chunk_still_loses_to_the_hevy_push_it_is_a_piece_of(monkeypatch):
    """#4627 unchanged: WHOOP's 19 min of a 2 h 10 min lift is not the session."""
    row = _fetch_day(monkeypatch, [HEVY_LIFT_1019, WHOOP_LIFT_1019], day="2026-10-19")
    assert _ids(row["activities"]) == ["20646783818", "20647779260"]
    assert _ids(seam.strava_read_seam("strava", row)["activities"]) == ["20647779260"]


# ── the two ingestion-side readers the #4419 AST guard does not sweep ─────────────────────────


def test_reconcile_reports_a_vendor_activity_whose_stored_sibling_has_its_own_id():
    api = [{"id": 20669445621, "start_date": "2026-10-18T22:01:04Z"}, {"id": 20641189677, "start_date": "2026-10-18T22:03:00Z"}]
    stored = [{"strava_id": "20641189677", "start_date": "2026-10-18T22:03:00Z"}]  # what the old ingest kept
    assert [a["id"] for a in strava._activities_missing_from_store(api, stored)] == [20669445621]


def test_the_enricher_ranks_against_a_deduped_population_and_writes_back_every_copy(monkeypatch):
    from ingestion import enrichment_lambda as en

    day = {
        "pk": f"{en.USER_PREFIX}strava",
        "sk": f"DATE#{DAY}",
        "date": DAY,
        "activities": [strava._normalize(dict(WATCH_WALK)), strava._normalize(dict(WHOOP_WALK))],
    }
    seen = {}

    def lookup(items):
        seen["pool"] = [a["strava_id"] for d in items for a in d.get("activities", [])]
        return [], []

    class Tbl:
        updates = []

        def update_item(self, **kw):
            self.updates.append(kw)

    monkeypatch.setattr(en, "query_source", lambda src, lo, hi: [day] if src == "strava" else [])
    monkeypatch.setattr(en, "build_percentile_lookup", lookup)
    monkeypatch.setattr(en, "table", Tbl())
    en.enrich_date_range(DAY, DAY)
    assert seen["pool"] == ["20669445621"], "the percentile population counts one session once"
    written = Tbl.updates[0]["ExpressionAttributeValues"][":acts"]
    assert sorted(a["strava_id"] for a in written) == ["20641189677", "20669445621"], "the write-back must keep every stored copy"
