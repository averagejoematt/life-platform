"""tests/test_whoop_reconcile.py — TR-07 (#415), epic #348.

Source-of-truth reconciliation generalized from Strava to Whoop: the whoop
lambda, invoked with {"reconcile": true}, pulls a trailing window of sleeps +
workouts from the Whoop API and diffs it against the store. Every other Whoop
freshness check reads only DDB and so sees only the high-water mark — blind to a
silent drop (a scored night, or a late-syncing workout, the API has but that
never landed). These tests drive _reconcile end-to-end and, per the acceptance
criteria, INDUCE a gap in the test window and assert the reconciler flags exactly
that gap — while dedup-aware twin records raise no false positive, and the run is
strictly read-only.
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

from ingestion import whoop_lambda as whoop  # noqa: E402


def _run_reconcile(monkeypatch, sleeps, workouts, stored_sks, stored_workout_starts):
    """Drive _reconcile with a fully mocked provider + store. Returns (body, emitted)."""
    emitted = {}

    def fake_fetch_all(token, endpoint, start_dt, end_dt, max_pages=60):
        return sleeps if "sleep" in endpoint else workouts

    def fake_stored(table, start_date, end_date):
        return set(stored_sks), list(stored_workout_starts)

    fake_boto3 = types.SimpleNamespace(
        resource=lambda *a, **k: types.SimpleNamespace(Table=lambda name: None),
        client=lambda *a, **k: types.SimpleNamespace(),
    )
    monkeypatch.setattr(whoop, "boto3", fake_boto3)
    # authenticate would hit the OAuth endpoint; return the secret unchanged so no
    # refresh + no secret writeback happens in the test.
    monkeypatch.setattr(whoop, "authenticate", lambda sd: dict(sd))

    import secret_cache

    monkeypatch.setattr(
        secret_cache,
        "get_secret_json",
        lambda sid, client: {"access_token": "tok", "refresh_token": "rt"},
    )
    monkeypatch.setattr(whoop, "_fetch_all_records", fake_fetch_all)
    monkeypatch.setattr(whoop, "_fetch_stored_records", fake_stored)
    monkeypatch.setattr(whoop, "_emit_reconciliation_metric", lambda n: emitted.setdefault("count", n))

    out = whoop._reconcile({"reconcile": True}, None)
    return json.loads(out["body"]), emitted.get("count")


def _sleep(day, nap=False, scored=True):
    return {"start": f"{day}T07:30:00.000Z", "nap": nap, "score_state": "SCORED" if scored else "PENDING_SCORE"}


def _workout(wid, day, hhmm="18:00"):
    return {"id": wid, "start": f"{day}T{hhmm}:00.000Z", "score_state": "SCORED"}


def test_induced_workout_gap_is_detected(monkeypatch):
    """Remove one stored workout sub-record from an otherwise-complete window and
    assert the reconciler flags EXACTLY that workout — the acceptance case."""
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    sleeps = [_sleep(today), _sleep(yesterday)]
    kept = _workout("w-present", yesterday, "18:00")
    dropped = _workout("w-missing", today, "12:00")  # the induced gap
    workouts = [kept, dropped]

    # Store has both days + the kept workout, but NOT the dropped one.
    stored_sks = {
        f"DATE#{today}",
        f"DATE#{yesterday}",
        f"DATE#{yesterday}#WORKOUT#w-present",
    }
    stored_starts = [datetime.fromisoformat(kept["start"].replace("Z", "+00:00"))]

    body, emitted = _run_reconcile(monkeypatch, sleeps, workouts, stored_sks, stored_starts)

    assert body["missing_count"] == 1
    assert emitted == 1
    miss = body["missing"]
    assert len(miss) == 1
    assert miss[0]["kind"] == "workout"
    assert miss[0]["id"] == "w-missing"
    assert miss[0]["date"] == today


def test_induced_dropped_night_is_detected(monkeypatch):
    """A scored main sleep with no stored DATE# record is a dropped-day gap."""
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    sleeps = [_sleep(today), _sleep(yesterday)]
    stored_sks = {f"DATE#{yesterday}"}  # today's night silently never landed

    body, _ = _run_reconcile(monkeypatch, sleeps, [], stored_sks, [])

    assert body["missing_count"] == 1
    assert body["missing"][0] == {"kind": "daily", "date": today, "sk": f"DATE#{today}"}


def test_clean_window_reports_no_gap(monkeypatch):
    """Every API record present in the store → missing_count 0, metric emits 0."""
    today = datetime.now(timezone.utc).date().isoformat()
    sleeps = [_sleep(today)]
    wk = _workout("w1", today, "18:00")
    stored_sks = {f"DATE#{today}", f"DATE#{today}#WORKOUT#w1"}

    body, emitted = _run_reconcile(monkeypatch, sleeps, [wk], stored_sks, [])

    assert body["missing_count"] == 0
    assert emitted == 0
    assert body["missing"] == []


def test_dedup_twin_workout_is_not_a_false_gap(monkeypatch):
    """A GPS-drop / double-log twin (two ids seconds apart) collapses to one — the
    store keeping only one representative must NOT flag the other as missing."""
    today = datetime.now(timezone.utc).date().isoformat()
    twin_a = _workout("twin-a", today, "18:00")
    twin_b = {"id": "twin-b", "start": f"{today}T18:00:30.000Z", "score_state": "SCORED"}  # +30s

    # Store kept only twin-a.
    stored_sks = {f"DATE#{today}", f"DATE#{today}#WORKOUT#twin-a"}
    stored_starts = [datetime.fromisoformat(twin_a["start"].replace("Z", "+00:00"))]

    body, _ = _run_reconcile(monkeypatch, [_sleep(today)], [twin_a, twin_b], stored_sks, stored_starts)

    assert body["missing_count"] == 0, body["missing"]


def test_unscored_and_nap_sleeps_do_not_anchor_a_day(monkeypatch):
    """Only a SCORED main sleep anchors an expected day — a nap or a pending night
    must not raise a false daily gap when no DATE# record exists yet."""
    today = datetime.now(timezone.utc).date().isoformat()
    sleeps = [_sleep(today, nap=True), _sleep(today, scored=False)]

    body, emitted = _run_reconcile(monkeypatch, sleeps, [], set(), [])

    assert body["missing_count"] == 0
    assert emitted == 0


def test_reconcile_is_read_only(monkeypatch):
    """The reconciler must never write to the store — assert no DDB write API is
    touched on the (mocked) table during a run with an induced gap."""
    today = datetime.now(timezone.utc).date().isoformat()
    writes = []

    class GuardTable:
        def __getattr__(self, name):
            if name in ("put_item", "update_item", "delete_item", "batch_writer"):
                writes.append(name)
            raise AttributeError(name)

    # _fetch_stored_records is mocked out, so the only table access is what
    # _reconcile itself does; guard proves it performs no writes.
    monkeypatch.setattr(whoop, "_table", GuardTable())

    sleeps = [_sleep(today)]
    body, _ = _run_reconcile(monkeypatch, sleeps, [_workout("w9", today)], {f"DATE#{today}"}, [])

    assert writes == []
    assert body["missing_count"] == 1  # the induced workout gap still detected
