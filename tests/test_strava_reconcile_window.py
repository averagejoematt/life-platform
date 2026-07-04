"""tests/test_strava_reconcile_window.py — #472 (C-1, epic #459).

The reconciler fetches API activities by a UTC epoch window but the store is
partitioned by LOCAL (Pacific) date, so a window-edge activity — the live-alarm
case: an evening-PT walk whose UTC start falls just inside the window start —
is stored under a local DATE# one day OUTSIDE [start, today] and was reported
as a false 'missing'. The fix brackets the stored-side fetch by ±1 day; these
tests replay that exact case through _reconcile.
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

from ingestion import strava_lambda as strava  # noqa: E402


def _run_reconcile(monkeypatch, api_activities, stored_by_local_date):
    """Drive _reconcile with a store keyed by local date, honoring the range asked for."""
    requested = {}

    def fake_stored(table, start_date, end_date):
        requested["range"] = (start_date, end_date)
        return [a for d, acts in stored_by_local_date.items() if start_date <= d <= end_date for a in acts]

    fake_boto3 = types.SimpleNamespace(
        resource=lambda *a, **k: types.SimpleNamespace(Table=lambda name: None),
        client=lambda *a, **k: types.SimpleNamespace(),
    )
    monkeypatch.setattr(strava, "boto3", fake_boto3)
    monkeypatch.setattr(strava, "authenticate", lambda sd: sd)

    import secret_cache

    monkeypatch.setattr(secret_cache, "get_secret_json", lambda sid, client: {"access_token": "t"})
    monkeypatch.setattr(strava, "_fetch_stored_activities", fake_stored)
    monkeypatch.setattr(strava, "_fetch_activities_in_range", lambda secret, after, before: (api_activities, secret))
    monkeypatch.setattr(strava, "_emit_reconciliation_metric", lambda n: None)

    out = strava._reconcile({}, None)
    return json.loads(out["body"]), requested["range"]


def test_window_edge_activity_is_not_a_false_positive(monkeypatch):
    """Evening-PT walk at the window start: UTC start inside the API window, but
    stored under the PREVIOUS local date — outside the naive stored-side range."""
    today = datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=strava.RECONCILE_WINDOW_DAYS)
    # 05:30 UTC on the window-start day == 21:30 PT the local day BEFORE it.
    utc_start = datetime(window_start.year, window_start.month, window_start.day, 5, 30, tzinfo=timezone.utc)
    local_date = (window_start - timedelta(days=1)).isoformat()

    walk = {"id": 987654, "type": "Walk", "start_date": utc_start.strftime("%Y-%m-%dT%H:%M:%SZ")}
    stored_walk = {"strava_id": "987654", "start_date": walk["start_date"]}

    body, (fetch_start, fetch_end) = _run_reconcile(monkeypatch, [walk], {local_date: [stored_walk]})

    assert fetch_start == local_date  # the ±1-day bracket reaches the local partition
    assert fetch_end == (today + timedelta(days=1)).isoformat()
    assert body["missing_count"] == 0
    assert body["missing_ids"] == []


def test_genuinely_missing_activity_still_reported(monkeypatch):
    """The widened bracket must not mask a real gap."""
    today = datetime.now(timezone.utc).date()
    run = {"id": 111, "type": "Run", "start_date": f"{today.isoformat()}T15:00:00Z"}

    body, _ = _run_reconcile(monkeypatch, [run], {})

    assert body["missing_count"] == 1
    assert body["missing_ids"] == ["111"]
