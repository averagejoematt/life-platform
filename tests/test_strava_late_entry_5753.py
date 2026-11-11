"""tests/test_strava_late_entry_5753.py — #5753: a Strava activity entered late for an older day is stored.

Strava activity 20673635694, a manual walk dated 2026-10-06, was typed in about two weeks after
that day. The ingest re-fetched only the trailing 3 start days, gap-fill skips any day already
present, and the 14-day reconcile only REPORTS what the store lacks — so it was never stored.

Strava's list call cannot be filtered by upload time (`after=`/`before=` are START-time bounds),
so the ingest now lists a trailing window by start time, finds the vendor ids the store lacks,
and hands their start days to the framework (`IngestionConfig.extra_dates_fn`), which re-fetches
each through the ordinary fetch_day → transform → _store_item path — the same full replace, with
`carry_forward_enrichment`, that a `date_override` run makes.

The clock is frozen (the framework's `pacific_now`, and `late_entry_days`' own `today` argument),
so nothing here moves with the wall clock (#4848).
"""

import json
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

for _k, _v in {"S3_BUCKET": "t", "TABLE_NAME": "life-platform", "USER_ID": "matthew", "AWS_DEFAULT_REGION": "us-west-2"}.items():
    os.environ.setdefault(_k, _v)

from ingestion import (
    ingestion_framework as fw,  # noqa: E402
    strava_lambda as strava,  # noqa: E402
)

PK = "USER#matthew#SOURCE#strava"
TODAY = date(2026, 10, 20)  # the walk was entered "about two weeks" after 2026-10-06
LATE_ID = 20673635694
LATE_DAY = "2026-10-06"


def _api(id_, start_local, sport="Walk"):
    """A raw list-endpoint activity; Pacific (UTC-7 in October) local start."""
    local = datetime.strptime(start_local, "%Y-%m-%dT%H:%M:%S")
    utc = local.replace(tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc)
    return {
        "id": id_,
        "name": sport,
        "sport_type": sport,
        "type": sport,
        "start_date": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_date_local": start_local + "Z",
        "elapsed_time": 1800,
        "moving_time": 1800,
        "distance": 2000.0,
        "has_heartrate": False,
        "map": {"summary_polyline": ""},
    }


def _stored(api_activity, **extra):
    return {"strava_id": str(api_activity["id"]), "start_date": api_activity["start_date"], "name": api_activity["name"], **extra}


# The 2026-10-06 activity that WAS stored on time, and the late manual walk for the same day.
ON_TIME_1006 = _api(20500000001, "2026-10-06T07:00:00")
LATE_WALK = _api(LATE_ID, "2026-10-06T17:30:00")
# One activity for each recent day, so gap-fill finds nothing missing on its own.
RECENT = [_api(20700000000 + d, f"2026-10-{d:02d}T08:00:00") for d in range(12, 21)]


class _FakeTable:
    """The store: `query` returns every row (the callers bound the range themselves)."""

    def __init__(self, rows):
        self.rows = {r["sk"]: r for r in rows}
        self.put_items = []

    def query(self, **kwargs):
        return {"Items": [dict(r) for r in self.rows.values()]}

    def get_item(self, Key=None, **kwargs):
        row = self.rows.get((Key or {}).get("sk"))
        return {"Item": json.loads(json.dumps(row))} if row else {}

    def put_item(self, Item=None, **kwargs):
        self.put_items.append(Item)
        if str(Item.get("sk", "")).startswith("DATE#"):
            self.rows[Item["sk"]] = Item
        return {}


class _FakeS3:
    def put_object(self, **kwargs):
        return {}


class _FakeSecrets:
    def get_secret_value(self, SecretId=None):
        return {"SecretString": json.dumps(_SECRET)}

    def update_secret(self, **kwargs):  # pragma: no cover - credentials never change here
        raise AssertionError("no writeback expected")


_SECRET = {"access_token": "t", "refresh_token": "r", "expires_at": 4102444800, "client_id": "c", "client_secret": "s"}


def _vendor(acts):
    """`_fetch_activities_in_range` over a fixed vendor list, honouring the START-time window."""
    calls = []

    def fetch(secret, after_ts, before_ts):
        calls.append((after_ts, before_ts))
        out = []
        for a in acts:
            t = datetime.strptime(a["start_date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            if after_ts < t < before_ts:
                out.append(dict(a))
        return out, secret

    return fetch, calls


def _store_rows():
    rows = [{"pk": PK, "sk": f"DATE#{LATE_DAY}", "activities": [_stored(ON_TIME_1006, enriched_name="Morning loop")]}]
    for a in RECENT:
        rows.append({"pk": PK, "sk": "DATE#" + a["start_date_local"][:10], "activities": [_stored(a)]})
    return rows


# ── late_entry_days: the discovery ────────────────────────────────────────────


def test_a_late_entry_older_than_the_refetch_window_names_its_start_day(monkeypatch):
    fetch, _ = _vendor([ON_TIME_1006, LATE_WALK, *RECENT])
    monkeypatch.setattr(strava, "_fetch_activities_in_range", fetch)
    monkeypatch.setitem(strava._secret_cache, "secret", dict(_SECRET))
    assert strava.late_entry_days(_FakeTable(_store_rows()), TODAY) == [LATE_DAY]


def test_nothing_is_named_when_the_store_holds_every_vendor_id(monkeypatch):
    fetch, _ = _vendor([ON_TIME_1006, *RECENT])
    monkeypatch.setattr(strava, "_fetch_activities_in_range", fetch)
    monkeypatch.setitem(strava._secret_cache, "secret", dict(_SECRET))
    assert strava.late_entry_days(_FakeTable(_store_rows()), TODAY) == []


def test_the_list_window_is_by_start_time_and_reaches_the_whole_late_entry_window(monkeypatch):
    fetch, calls = _vendor([])
    monkeypatch.setattr(strava, "_fetch_activities_in_range", fetch)
    monkeypatch.setitem(strava._secret_cache, "secret", dict(_SECRET))
    strava.late_entry_days(_FakeTable([]), TODAY)
    after_ts, before_ts = calls[0]
    first = datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp()  # TODAY - 30 days
    assert after_ts <= first - 86400 + 1, "the UTC window must bracket the first local day"
    assert before_ts >= datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp(), "...and today's local day"
    assert len(calls) == 1, "one list call per run — the rate-limit budget"


def test_the_days_named_per_run_are_capped_oldest_first(monkeypatch):
    late = [_api(20680000000 + d, f"2026-10-{d:02d}T09:00:00") for d in range(1, 10)]
    fetch, _ = _vendor(late)
    monkeypatch.setattr(strava, "_fetch_activities_in_range", fetch)
    monkeypatch.setitem(strava._secret_cache, "secret", dict(_SECRET))
    monkeypatch.setattr(strava, "LATE_ENTRY_MAX_DAYS_PER_RUN", 3)
    assert strava.late_entry_days(_FakeTable([]), TODAY) == ["2026-10-01", "2026-10-02", "2026-10-03"]


def test_no_secret_means_no_discovery_and_no_vendor_call(monkeypatch):
    fetch, calls = _vendor([LATE_WALK])
    monkeypatch.setattr(strava, "_fetch_activities_in_range", fetch)
    monkeypatch.setitem(strava._secret_cache, "secret", None)
    assert strava.late_entry_days(_FakeTable([]), TODAY) == [] and calls == []


# ── end to end through the framework ─────────────────────────────────────────


def _run_ingest(monkeypatch, vendor_acts):
    table = _FakeTable(_store_rows())
    fetch, _ = _vendor(vendor_acts)
    monkeypatch.setattr(strava, "_fetch_activities_in_range", fetch)
    monkeypatch.setattr(strava, "_stored_enrichment", lambda d: {})
    monkeypatch.setitem(strava._secret_cache, "secret", None)
    monkeypatch.setattr(fw, "_init_aws", lambda config: (table, _FakeS3(), _FakeSecrets()))
    monkeypatch.setattr(fw, "record_ingest_health", lambda *a, **k: None)
    monkeypatch.setattr(fw, "_clear_auth_failure", lambda *a, **k: None)  # no CloudWatch call from a test
    monkeypatch.setattr(fw, "_mark_auth_failure", lambda *a, **k: None)
    monkeypatch.setattr(fw, "pacific_now", lambda: datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")))
    monkeypatch.setattr(fw, "pacific_today", lambda: "2026-10-20")
    monkeypatch.setattr(fw.time, "sleep", lambda s: None)
    from common import secret_cache

    monkeypatch.setattr(secret_cache, "get_secret_json", lambda sid, client: dict(_SECRET))
    resp = strava.lambda_handler({}, None)
    return resp, table


def test_the_late_walk_is_stored_on_its_start_day_with_enrichment_carried(monkeypatch):
    resp, table = _run_ingest(monkeypatch, [ON_TIME_1006, LATE_WALK, *RECENT])
    assert resp["statusCode"] == 200, resp
    assert LATE_DAY in json.loads(resp["body"])["results"]
    row = table.rows[f"DATE#{LATE_DAY}"]
    by_id = {a["strava_id"]: a for a in row["activities"]}
    assert set(by_id) == {str(ON_TIME_1006["id"]), str(LATE_ID)}, "the day is rebuilt from the vendor: both walks"
    assert row["activity_count"] == 2
    assert by_id[str(ON_TIME_1006["id"])]["enriched_name"] == "Morning loop", "carry_forward_enrichment ran on the replace"


def test_an_ordinary_run_does_not_touch_an_old_complete_day(monkeypatch):
    resp, table = _run_ingest(monkeypatch, [ON_TIME_1006, *RECENT])
    assert LATE_DAY not in json.loads(resp["body"])["results"]
    assert not [i for i in table.put_items if i.get("sk") == f"DATE#{LATE_DAY}"]


def test_a_failing_discovery_costs_the_run_nothing(monkeypatch):
    def boom(table, today):
        raise RuntimeError("strava 503")

    monkeypatch.setattr(strava._config, "extra_dates_fn", boom)
    resp, table = _run_ingest(monkeypatch, [ON_TIME_1006, LATE_WALK, *RECENT])
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200 and LATE_DAY not in body["results"]
    assert "2026-10-20" in body["results"], "the ordinary dates still ran"
