"""tests/test_store_vendor_reconcile_4638.py — #4638 box 2.

The Strava and Whoop reconcilers only ever looked API → store (DI-2 / TR-07): what the
vendor has that the store lacks. An edit or a delete made in the vendor's app produces the
OPPOSITE difference, and nothing looked there. These tests drive each `_reconcile` end to
end with a mocked vendor list and store, in BOTH directions, and pin:

  * Strava: stored ids absent from the vendor's trailing list, and changed name / sport
    type / duration, are reported as metrics; a stored day the vendor now has zero
    activities for is rewritten as an explicit empty (tombstoned) day — and only that day,
    only inside the window's interior, never when the whole vendor list is empty, and never
    more than the per-run cap.
  * Whoop: stored workout ids absent from the vendor list, and changed sport / start / end,
    are reported as metrics; the path stays read-only on the store.

Stored rows are built through each lambda's own normaliser (`strava._normalize`,
`whoop._extract_workout`) so the fixture is the shape the writer actually stores.
"""

import json
import os
import types
from datetime import datetime, timedelta, timezone

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion import (
    strava_lambda as strava,  # noqa: E402
    whoop_lambda as whoop,  # noqa: E402
)

# ── Strava ────────────────────────────────────────────────────────────────────


def _today():
    return datetime.now(timezone.utc).date()


def _day(n_back: int) -> str:
    return (_today() - timedelta(days=n_back)).isoformat()


def _api_activity(aid, day, hhmm="15:00", name="Morning Walk", sport_type="Walk", moving=1800, elapsed=1900):
    """A Strava /athlete/activities summary row (the fields _normalize reads)."""
    return {
        "id": aid,
        "name": name,
        "type": sport_type,
        "sport_type": sport_type,
        "start_date": f"{day}T{hhmm}:00Z",
        "start_date_local": f"{day}T08:00:00Z",
        "timezone": "(GMT-08:00) America/Los_Angeles",
        "moving_time": moving,
        "elapsed_time": elapsed,
        "distance": 2400.0,
        "total_elevation_gain": 10.0,
        "has_heartrate": False,
        "map": {"summary_polyline": ""},
    }


def _stored(api_row):
    return strava._normalize(api_row)


class _RecordingTable:
    def __init__(self):
        self.puts = []

    def put_item(self, Item):
        self.puts.append(Item)


def _run_strava(monkeypatch, api_activities, stored_by_day):
    table = _RecordingTable()
    emitted = {}

    fake_boto3 = types.SimpleNamespace(
        resource=lambda *a, **k: types.SimpleNamespace(Table=lambda name: table),
        client=lambda *a, **k: types.SimpleNamespace(),
    )
    monkeypatch.setattr(strava, "boto3", fake_boto3)
    monkeypatch.setattr(strava, "authenticate", lambda sd: sd)

    from common import secret_cache

    monkeypatch.setattr(secret_cache, "get_secret_json", lambda sid, client: {"access_token": "t"})
    monkeypatch.setattr(
        strava,
        "_fetch_stored_days",
        lambda tbl, start_date, end_date: {d: list(a) for d, a in stored_by_day.items() if start_date <= d <= end_date},
    )
    monkeypatch.setattr(strava, "_fetch_activities_in_range", lambda secret, after, before: (api_activities, secret))
    monkeypatch.setattr(strava, "_emit_reconciliation_metric", lambda n: emitted.setdefault("missing", n))
    monkeypatch.setattr(strava, "_emit_store_vendor_metrics", lambda a, c, e: emitted.update({"absent": a, "changed": c, "emptied": e}))

    body = json.loads(strava._reconcile({"reconcile": True}, None)["body"])
    return body, table.puts, emitted


def test_strava_a_day_whose_activities_are_all_deleted_is_written_empty(monkeypatch):
    """The acceptance case: the vendor's (successful, non-empty) list has zero activities
    for a day the store holds a row for → that day is rewritten as an explicit empty day."""
    gone_day, kept_day = _day(5), _day(3)
    deleted = _api_activity(5001, gone_day)
    kept = _api_activity(5002, kept_day)

    body, puts, emitted = _run_strava(monkeypatch, [kept], {gone_day: [_stored(deleted)], kept_day: [_stored(kept)]})

    sv = body["store_vendor"]
    assert sv["absent"] == [{"id": "5001", "date": gone_day}]
    assert sv["emptied_days"] == [gone_day]
    assert sv["empty_day_writes_skipped"] is None
    assert emitted == {"missing": 0, "absent": 1, "changed": 0, "emptied": 1}

    assert len(puts) == 1
    item = puts[0]
    assert (item["pk"], item["sk"]) == ("USER#matthew#SOURCE#strava", f"DATE#{gone_day}")
    assert item["activity_count"] == 0 and item["activities"] == [] and item["sport_types"] == []
    assert item["tombstone"] is True
    assert item["tombstoned_reason"] == strava.EMPTIED_DAY_REASON
    assert item["emptied_activity_ids"] == ["5001"]


def test_strava_both_directions_in_one_pass(monkeypatch):
    """API → store (a vendor activity never stored) and store → vendor (a stored id the
    vendor no longer lists) are reported side by side by the same run."""
    day = _day(4)
    never_stored = _api_activity(6001, day, "15:00")
    still_there = _api_activity(6002, day, "18:00")
    deleted = _api_activity(6003, day, "20:00")

    body, puts, emitted = _run_strava(monkeypatch, [never_stored, still_there], {day: [_stored(still_there), _stored(deleted)]})

    assert body["missing_ids"] == ["6001"]
    assert body["store_vendor"]["absent"] == [{"id": "6003", "date": day}]
    # The day still has vendor activities → a partial delete is reported, never written.
    assert body["store_vendor"]["empty_day_candidates"] == []
    assert puts == []
    assert emitted["missing"] == 1 and emitted["absent"] == 1 and emitted["emptied"] == 0


def test_strava_changed_name_sport_and_duration_are_reported_not_written(monkeypatch):
    day = _day(6)
    stored = _stored(_api_activity(7001, day, name="Morning Walk", sport_type="Walk", moving=1800, elapsed=1900))
    vendor = _api_activity(7001, day, name="Hike up the hill", sport_type="Hike", moving=1500, elapsed=1600)

    body, puts, emitted = _run_strava(monkeypatch, [vendor], {day: [stored]})

    changed = body["store_vendor"]["changed"]
    assert changed == [{"id": "7001", "date": day, "fields": ["name", "sport_type", "moving_time_seconds", "elapsed_time_seconds"]}]
    assert body["store_vendor"]["absent"] == []
    assert puts == []
    assert emitted["changed"] == 1


def test_strava_an_unchanged_window_reports_nothing(monkeypatch):
    day = _day(2)
    row = _api_activity(7101, day)

    body, puts, emitted = _run_strava(monkeypatch, [row], {day: [_stored(row)]})

    assert body["store_vendor"]["absent_count"] == 0
    assert body["store_vendor"]["changed_count"] == 0
    assert puts == []
    assert emitted == {"missing": 0, "absent": 0, "changed": 0, "emptied": 0}


def test_strava_empty_day_guards(monkeypatch):
    """No write when the vendor list is wholly empty (a lost scope looks exactly like this),
    none past the per-run cap, and none on the window's first or last day."""
    # 1. vendor list wholly empty
    day = _day(5)
    body, puts, _ = _run_strava(monkeypatch, [], {day: [_stored(_api_activity(8001, day))]})
    assert body["store_vendor"]["empty_day_candidates"] == [day]
    assert body["store_vendor"]["empty_day_writes_skipped"] == "vendor_list_empty"
    assert puts == []

    # 2. over the cap: every candidate is held, none written
    anchor = _api_activity(8100, _day(1))
    stored = {_day(n): [_stored(_api_activity(8100 + n, _day(n)))] for n in range(2, 3 + strava.MAX_EMPTIED_DAYS_PER_RUN)}
    stored[_day(1)] = [_stored(anchor)]
    body, puts, _ = _run_strava(monkeypatch, [anchor], stored)
    assert len(body["store_vendor"]["empty_day_candidates"]) == strava.MAX_EMPTIED_DAYS_PER_RUN + 1
    assert body["store_vendor"]["empty_day_writes_skipped"].startswith("over_cap")
    assert puts == []

    # 3. the window's edge days (first, and today) are never judged
    first = _day(strava.RECONCILE_WINDOW_DAYS)
    today = _day(0)
    anchor = _api_activity(8200, _day(3))
    body, puts, _ = _run_strava(
        monkeypatch,
        [anchor],
        {first: [_stored(_api_activity(8201, first))], today: [_stored(_api_activity(8202, today))], _day(3): [_stored(anchor)]},
    )
    assert body["store_vendor"]["empty_day_candidates"] == []
    assert puts == []


def test_strava_a_day_with_an_id_still_listed_elsewhere_is_not_emptied(monkeypatch):
    """An activity whose start time was edited onto another day is still at the vendor —
    its old day is not a deletion."""
    old_day, new_day = _day(5), _day(4)
    stored = _stored(_api_activity(9001, old_day))
    moved = _api_activity(9001, new_day)

    body, puts, _ = _run_strava(monkeypatch, [moved], {old_day: [stored]})

    assert body["store_vendor"]["empty_day_candidates"] == []
    assert puts == []


# ── Whoop ─────────────────────────────────────────────────────────────────────


def _vendor_workout(wid, day, start="18:00", end="18:45", sport_id=63):
    return {
        "id": wid,
        "sport_id": sport_id,
        "start": f"{day}T{start}:00.000Z",
        "end": f"{day}T{end}:00.000Z",
        "score_state": "SCORED",
        "score": {"strain": 8.1, "average_heart_rate": 120, "max_heart_rate": 150, "kilojoule": 900.0, "zone_duration": {}},
    }


def _stored_workout(vendor_row, day):
    return {"sk": f"DATE#{day}#WORKOUT#{vendor_row['id']}", "workout_id": vendor_row["id"], **whoop._extract_workout(vendor_row)}


def _run_whoop(monkeypatch, vendor_workouts, stored_workouts, stored_sks=None, fetch_stored=None):
    emitted = {}
    writes = []

    class GuardTable:
        def __getattr__(self, name):
            if name in ("put_item", "update_item", "delete_item", "batch_writer"):
                writes.append(name)
            raise AttributeError(name)

    monkeypatch.setattr(whoop, "_table", GuardTable())
    monkeypatch.setattr(whoop, "check_breaker", lambda *a, **k: None)
    monkeypatch.setattr(
        whoop,
        "boto3",
        types.SimpleNamespace(
            resource=lambda *a, **k: types.SimpleNamespace(Table=lambda name: None),
            client=lambda *a, **k: types.SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(whoop, "authenticate", lambda sd: dict(sd))

    from common import secret_cache

    monkeypatch.setattr(secret_cache, "get_secret_json", lambda sid, client: {"access_token": "tok", "refresh_token": "rt"})
    monkeypatch.setattr(
        whoop, "_fetch_all_records", lambda token, endpoint, s, e, max_pages=60: [] if "sleep" in endpoint else vendor_workouts
    )
    sks = stored_sks if stored_sks is not None else {w["sk"] for w in stored_workouts}
    monkeypatch.setattr(whoop, "_fetch_stored_records", lambda table, s, e: (set(sks), []))
    monkeypatch.setattr(whoop, "_fetch_stored_workouts", fetch_stored or (lambda table, s, e: list(stored_workouts)))
    monkeypatch.setattr(whoop, "_emit_reconciliation_metric", lambda n: emitted.setdefault("missing", n))
    monkeypatch.setattr(whoop, "_emit_store_vendor_metrics", lambda a, c: emitted.update({"absent": a, "changed": c}))

    body = json.loads(whoop._reconcile({"reconcile": True}, None)["body"])
    return body, emitted, writes


def test_whoop_deleted_and_retyped_workouts_are_reported_read_only(monkeypatch):
    day = _day(5)
    kept = _vendor_workout("w-kept", day, "07:00", "07:30")
    deleted = _vendor_workout("w-deleted", day, "12:00", "12:40")
    retyped_before = _vendor_workout("w-retyped", day, "18:00", "18:45", sport_id=63)
    retyped_after = _vendor_workout("w-retyped", day, "18:00", "18:30", sport_id=1)

    stored = [_stored_workout(kept, day), _stored_workout(deleted, day), _stored_workout(retyped_before, day)]
    body, emitted, writes = _run_whoop(monkeypatch, [kept, retyped_after], stored)

    sv = body["store_vendor"]
    assert sv["absent"] == [{"id": "w-deleted", "date": day}]
    assert sv["changed"] == [{"id": "w-retyped", "date": day, "fields": ["sport_id", "end_time"]}]
    assert emitted == {"missing": 0, "absent": 1, "changed": 1}
    assert writes == []  # read-only on the store


def test_whoop_both_directions_in_one_pass(monkeypatch):
    day = _day(3)
    never_stored = _vendor_workout("w-new", day, "09:00", "09:30")
    deleted = _vendor_workout("w-gone", day, "16:00", "16:30")

    body, emitted, writes = _run_whoop(monkeypatch, [never_stored], [_stored_workout(deleted, day)])

    assert [m["id"] for m in body["missing"]] == ["w-new"]
    assert body["store_vendor"]["absent"] == [{"id": "w-gone", "date": day}]
    assert emitted["missing"] == 1 and emitted["absent"] == 1
    assert writes == []


def test_whoop_a_stored_workout_outside_the_judged_window_is_not_absent(monkeypatch):
    edge = _day(whoop.RECONCILE_WINDOW_DAYS)  # the leading day is never judged
    outside = _day(whoop.RECONCILE_WINDOW_DAYS + 1)
    rows = [_stored_workout(_vendor_workout("w-edge", edge), edge), _stored_workout(_vendor_workout("w-out", outside), outside)]

    body, emitted, _ = _run_whoop(monkeypatch, [], rows)

    assert body["store_vendor"]["absent"] == []
    assert emitted["absent"] == 0


def test_whoop_a_failed_store_vendor_read_never_costs_the_api_to_store_result(monkeypatch):
    day = _day(2)

    def boom(table, s, e):
        raise RuntimeError("throttled")

    body, emitted, _ = _run_whoop(monkeypatch, [_vendor_workout("w-new", day)], [], fetch_stored=boom)

    assert body["missing_count"] == 1
    assert body["store_vendor"] == {"error": "throttled"}
    assert "absent" not in emitted
