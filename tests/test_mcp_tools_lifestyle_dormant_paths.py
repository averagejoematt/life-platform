"""#1658 tranche 4 — the dormant-but-live-capable helpers in mcp/tools_lifestyle.py.

tests/test_mcp_tools_lifestyle_behavior.py (tranche 3) established that
``_fetch_weather_range``, ``_load_bp_readings``, ``_is_traveling`` and
``_tz_offset`` are unreachable from any registered tool — ~150 lines of a
1,977-line module that nothing calls. That file pins the FACT of the dead
surface; this file pins what the surface would DO if it were ever wired up,
because "dead" is a decision that gets reversed and these carry the module's
only outbound HTTP call and its only DynamoDB write to the weather partition.

Writing that harness is what surfaced the S3-prefix defect below: the BP reader
would not work today even if a tool called it tomorrow.

Per the tranche contract, defects are REPORTED as xfail(strict=False), never
fixed here. That reported defect (#2278 — the BP reader read a prefix nothing
has ever written) has since been fixed, so its xfail is now a live assertion,
joined by one that pins the MECHANISM: the key comes from the registry's
raw_layout facet, not from a literal a future reader can retype wrong.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from common.pacific_time import pacific_today  # #2817: the frame the module reads
from fakes import FakeDdbTable  # noqa: E402

from mcp import tools_lifestyle as tl  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# Timezone table — the travel-aware offsets
# ══════════════════════════════════════════════════════════════════════════


def test_the_home_timezone_resolves_to_pacific_time():
    """The site and every daily boundary run on Pacific — the offset table's
    home entry has to agree with that or a trip would shift Matthew's day."""
    assert tl.HOME_TZ == "America/Los_Angeles"
    assert tl.HOME_OFFSET == tl._tz_offset(tl.HOME_TZ) == -8


def test_an_unknown_timezone_is_reported_as_unknown_not_silently_treated_as_utc():
    """Returning 0 for an unrecognized zone would silently mis-date every
    reading on a trip; None forces the caller to notice."""
    assert tl._tz_offset("Mars/Olympus_Mons") is None
    assert tl._tz_offset("") is None


@pytest.mark.parametrize("tz,offset", [("Europe/London", 0), ("Asia/Kolkata", 5.5), ("Pacific/Auckland", 12), ("America/Vancouver", -8)])
def test_known_travel_destinations_carry_their_real_utc_offset(tz, offset):
    assert tl._tz_offset(tz) == offset


# ══════════════════════════════════════════════════════════════════════════
# Trip detection — is Matthew away on this date?
# ══════════════════════════════════════════════════════════════════════════


def _trip(start, end=None, place="Lisbon"):
    item = {"pk": tl.TRAVEL_PK, "sk": f"TRIP#{start}", "start_date": start, "destination": place}
    if end is not None:
        item["end_date"] = end
    return item


def test_a_date_inside_a_trip_reports_the_trip(monkeypatch):
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[_trip("2026-07-01", "2026-07-10")]))
    trip = tl._is_traveling("2026-07-05")
    assert trip is not None
    assert trip["destination"] == "Lisbon"


@pytest.mark.parametrize("d", ["2026-07-01", "2026-07-10"])
def test_the_first_and_last_day_of_a_trip_count_as_travelling(monkeypatch, d):
    """Travel days are travel — an exclusive bound would mis-classify both
    ends of every trip."""
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[_trip("2026-07-01", "2026-07-10")]))
    assert tl._is_traveling(d) is not None


@pytest.mark.parametrize("d", ["2026-06-30", "2026-07-11"])
def test_a_date_outside_every_trip_reports_being_home(monkeypatch, d):
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[_trip("2026-07-01", "2026-07-10")]))
    assert tl._is_traveling(d) is None


def test_an_open_ended_trip_is_still_running_today(monkeypatch):
    """A trip logged without a return date must read as ongoing, not as a
    zero-length trip that already ended."""
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[_trip("2026-01-01", None)]))
    # #3222: `_is_traveling`'s day domain is Pacific end to end (its own default is
    # `pacific_today()`, #2817) — the sibling test below was fixed then and this one was
    # not, leaving one UTC day in a Pacific-framed file. Benign here only because the
    # trip is open-ended; the frame is still wrong, so it reads the handler's clock.
    today = pacific_today()
    assert tl._is_traveling(today) is not None


def test_travel_defaults_to_today_when_no_date_is_given(monkeypatch):
    # #2817: `_is_traveling()`'s default is the PACIFIC day. Deriving the fixture
    # from the UTC clock made this test red for the seven evening hours a day when
    # the two calendars disagree — the fixture has to name the same day the wire does.
    today = pacific_today()
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[_trip(today, today)]))
    assert tl._is_traveling() is not None


def test_the_right_partition_is_queried_for_trips(monkeypatch):
    tbl = FakeDdbTable(rows=[])
    monkeypatch.setattr(tl, "table", tbl)
    tl._is_traveling("2026-07-05")
    eav = tbl.query_calls[0]["ExpressionAttributeValues"]
    assert eav[":pk"] == tl.TRAVEL_PK
    assert eav[":prefix"] == "TRIP#"


def test_a_database_error_reads_as_home_rather_than_crashing_the_tool(monkeypatch):
    class _Boom:
        def query(self, **_k):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(tl, "table", _Boom())
    assert tl._is_traveling("2026-07-05") is None


# ══════════════════════════════════════════════════════════════════════════
# Metric extraction — the shape the experiment engine reads through
# ══════════════════════════════════════════════════════════════════════════


def test_a_plain_numeric_field_is_read_as_a_number():
    assert tl._extract_metric({"steps": "8412"}, "steps") == 8412.0
    assert tl._extract_metric({"steps": 8412}, "steps") == 8412.0


def test_a_nested_field_is_reachable_by_dotted_path():
    assert tl._extract_metric({"sleep": {"stages": {"rem_pct": 21.5}}}, "sleep.stages.rem_pct") == 21.5


def test_a_missing_metric_is_absent_not_zero():
    """ADR-104: a day with no reading must not become a factual 0 — that would
    drag every average the experiment engine computes."""
    assert tl._extract_metric({"steps": 100}, "flights") is None
    assert tl._extract_metric({"steps": None}, "steps") is None
    assert tl._extract_metric({}, "a.b.c") is None


def test_a_non_numeric_value_is_absent_rather_than_a_crash():
    assert tl._extract_metric({"steps": "lots"}, "steps") is None
    assert tl._extract_metric({"steps": {"nested": 1}}, "steps") is None


def test_descending_into_a_scalar_is_absent_not_an_exception():
    assert tl._extract_metric({"sleep": 7.5}, "sleep.stages.rem_pct") is None


# ══════════════════════════════════════════════════════════════════════════
# Individual blood-pressure readings (dormant reader)
# ══════════════════════════════════════════════════════════════════════════


class _FakeS3:
    """Minimal S3 double with the NoSuchKey exception surface boto3 exposes."""

    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self, objects=None, error=None):
        self.objects = objects or {}
        self.error = error
        self.requested: list = []

    def get_object(self, Bucket=None, Key=None):
        self.requested.append(Key)
        if self.error is not None:
            raise self.error
        if Key not in self.objects:
            raise _FakeS3.exceptions.NoSuchKey(Key)
        return {"Body": _Body(self.objects[Key])}


class _Body:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p


_BP_DAY = [
    {"time": "2026-07-05 08:12", "systolic": 128, "diastolic": 82, "pulse": 61},
    {"time": "2026-07-05 21:40", "systolic": 134, "diastolic": 86, "pulse": 66},
]

# The one key health_auto_export_lambda.save_bp_readings_to_s3 writes for that day.
_BP_KEY = "raw/matthew/blood_pressure/2026/07/05.json"


def test_a_day_with_no_reading_is_an_empty_list_not_an_error(monkeypatch):
    monkeypatch.setattr(tl, "s3_client", _FakeS3())
    assert tl._load_bp_readings("2026-07-05") == []


def test_an_s3_outage_degrades_to_no_readings_rather_than_failing_the_tool(monkeypatch):
    monkeypatch.setattr(tl, "s3_client", _FakeS3(error=RuntimeError("s3 unavailable")))
    assert tl._load_bp_readings("2026-07-05") == []


def test_a_malformed_date_does_not_raise(monkeypatch):
    monkeypatch.setattr(tl, "s3_client", _FakeS3())
    assert tl._load_bp_readings("not-a-date") == []


def test_every_reading_in_the_day_is_returned_when_the_object_is_found(monkeypatch):
    """When the key DOES resolve the reader must hand back each individual
    cuff reading — a daily average would hide a 134/86 evening spike.

    #2278: this used to retry against whatever key the reader happened to ask
    for, which made it pass no matter how wrong that key was. It now stocks the
    ONE key the writer writes, so a reader pointed anywhere else fails here.
    """
    fake = _FakeS3({_BP_KEY: _BP_DAY})
    monkeypatch.setattr(tl, "s3_client", fake)
    got = tl._load_bp_readings("2026-07-05")
    assert len(got) == 2
    assert got[1]["systolic"] == 134


def test_the_bp_reader_looks_where_the_ingestion_lambda_actually_writes():
    """Guard the reader/writer key agreement, not one hand-typed literal: the
    expected prefix is derived from the registry facet the writer follows.

    Fixed in #2278. The reader spent its whole life on
    `raw/blood_pressure/{YYYY}/{MM}/{DD}.json` — no user segment, a prefix
    nothing has ever written (verified against the live bucket: 10 objects under
    `raw/matthew/blood_pressure/`, zero under `raw/blood_pressure/`). Every read
    missed, raised NoSuchKey, and was swallowed into `return []`, so the first
    caller wired to it would have read a hypertension history as "never logged".
    """
    fake = _FakeS3()
    tl.s3_client, saved = fake, tl.s3_client
    try:
        tl._load_bp_readings("2026-07-05")
    finally:
        tl.s3_client = saved
    assert fake.requested == [_BP_KEY]
    assert fake.requested == ["raw/matthew/blood_pressure/2026/07/05.json"]


def test_the_bp_key_is_resolved_from_the_registry_not_hand_built():
    """The acceptance is the mechanism, not the literal: fixing the string alone
    leaves the next reader free to retype it wrong. The key the reader asks for
    must be exactly what the registry's raw_layout facet yields for the HAE
    blood-pressure sub-tree."""
    from ingestion.source_registry import raw_date_key, raw_layout_for

    layout = raw_layout_for("apple_health", sub="blood_pressure")
    assert layout["prefix"] == "raw/matthew/blood_pressure"
    assert layout["filename"] == "DD.json"  # HAE writes DD.json, not the SIMP-2 YYYY-MM-DD.json

    fake = _FakeS3()
    tl.s3_client, saved = fake, tl.s3_client
    try:
        tl._load_bp_readings("2026-07-05")
    finally:
        tl.s3_client = saved
    assert fake.requested == [raw_date_key("apple_health", "2026-07-05", sub="blood_pressure")]


def test_moving_the_registrys_bp_prefix_moves_the_reader(monkeypatch):
    """The distinguishing test. Asserting the reader asks for
    `raw/matthew/blood_pressure/...` cannot tell a registry lookup from a
    correctly-retyped literal — and a retyped literal is the exact thing that
    rotted here. So move the facet and require the reader to follow: only a
    reader that actually READS the registry can pass this.
    """
    from ingestion import source_registry as sr

    moved = dict(sr.SOURCE_REGISTRY["apple_health"]["raw_layout"])
    moved["sub_layouts"] = dict(moved["sub_layouts"])
    moved["sub_layouts"]["blood_pressure"] = {"prefix": "raw/elsewhere/bp", "scheme": "date-tree", "filename": "YYYY-MM-DD.json"}
    monkeypatch.setitem(sr.SOURCE_REGISTRY["apple_health"], "raw_layout", moved)

    fake = _FakeS3()
    monkeypatch.setattr(tl, "s3_client", fake)
    tl._load_bp_readings("2026-07-05")
    assert fake.requested == ["raw/elsewhere/bp/2026/07/2026-07-05.json"]


def test_the_bp_key_encodes_the_requested_day_not_todays_date(monkeypatch):
    fake = _FakeS3()
    monkeypatch.setattr(tl, "s3_client", fake)
    tl._load_bp_readings("2026-07-05")
    assert fake.requested[0].endswith("2026/07/05.json")


# ══════════════════════════════════════════════════════════════════════════
# Weather backfill — the module's only outbound HTTP + only weather DDB write
# ══════════════════════════════════════════════════════════════════════════


_OPEN_METEO_DAY = {
    "daily": {
        "time": ["2026-07-01", "2026-07-02"],
        "temperature_2m_max": [78.1, 81.0],
        "temperature_2m_min": [55.2, 57.0],
        "temperature_2m_mean": [66.4, 69.0],
        "relative_humidity_2m_mean": [61, 58],
        "precipitation_sum": [0.0, 1.2],
        "wind_speed_10m_max": [9.1, 11.0],
        "surface_pressure_mean": [1014.2, 1012.0],
        "daylight_duration": [57600.0, 57500.0],  # 16.0 h / 15.97 h
        "sunshine_duration": [36000.0, 18000.0],  # 10.0 h / 5.0 h
        "uv_index_max": [6.8, 7.1],
    }
}


class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _no_network(monkeypatch, payload=_OPEN_METEO_DAY, boom=False):
    import urllib.request

    seen: dict = {}

    def _open(req, timeout=None):
        seen["url"] = req.full_url if hasattr(req, "full_url") else str(req)
        if boom:
            raise RuntimeError("open-meteo unreachable")
        return _Resp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    return seen


def test_a_fully_cached_range_makes_no_outbound_call(monkeypatch):
    """The archive never changes — a cached day must never be refetched, or
    every query re-bills a third-party API."""
    cached = [{"date": "2026-07-01", "temp_high_f": 78.1}, {"date": "2026-07-02", "temp_high_f": 81.0}]
    monkeypatch.setattr(tl, "query_source", lambda *a, **k: list(cached))
    seen = _no_network(monkeypatch)
    out = tl._fetch_weather_range("2026-07-01", "2026-07-02")
    assert "url" not in seen, "a fully cached range must not hit Open-Meteo"
    assert len(out) == 2


def test_only_the_missing_days_are_fetched(monkeypatch):
    monkeypatch.setattr(tl, "query_source", lambda *a, **k: [{"date": "2026-07-01", "temp_high_f": 78.1}])
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[]))
    seen = _no_network(monkeypatch)
    tl._fetch_weather_range("2026-07-01", "2026-07-02")
    assert "start_date=2026-07-02" in seen["url"]
    assert "end_date=2026-07-02" in seen["url"]


def test_the_forecast_is_requested_for_seattle_in_matthews_own_units(monkeypatch):
    """Matthew reads Fahrenheit and mph; a metric fetch would silently halve
    every temperature correlation."""
    monkeypatch.setattr(tl, "query_source", lambda *a, **k: [])
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[]))
    seen = _no_network(monkeypatch)
    tl._fetch_weather_range("2026-07-01", "2026-07-02")
    assert "latitude=47.6062" in seen["url"] and "longitude=-122.3321" in seen["url"]
    assert "temperature_unit=fahrenheit" in seen["url"]
    assert "wind_speed_unit=mph" in seen["url"]
    assert "timezone=America%2FLos_Angeles" in seen["url"] or "timezone=America/Los_Angeles" in seen["url"]


def test_fetched_days_are_returned_with_durations_converted_to_hours(monkeypatch):
    """Open-Meteo answers in seconds; a reader comparing 'sunshine hours' to
    mood needs hours, not 36000."""
    monkeypatch.setattr(tl, "query_source", lambda *a, **k: [])
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[]))
    _no_network(monkeypatch)
    out = tl._fetch_weather_range("2026-07-01", "2026-07-02")
    by_date = {r["date"]: r for r in out}
    assert by_date["2026-07-01"]["daylight_hours"] == 16.0  # 57600 / 3600
    assert by_date["2026-07-01"]["sunshine_hours"] == 10.0  # 36000 / 3600
    assert by_date["2026-07-02"]["sunshine_hours"] == 5.0  # 18000 / 3600
    assert by_date["2026-07-02"]["precipitation_mm"] == 1.2


def test_a_fetched_day_is_cached_into_the_weather_partition(monkeypatch):
    monkeypatch.setattr(tl, "query_source", lambda *a, **k: [])
    tbl = FakeDdbTable(rows=[])
    monkeypatch.setattr(tl, "table", tbl)
    _no_network(monkeypatch)
    tl._fetch_weather_range("2026-07-01", "2026-07-02")
    assert len(tbl.puts) == 2
    item = tbl.puts[0]
    assert item["pk"] == tl.USER_PREFIX + "weather"
    assert item["sk"] == "DATE#2026-07-01"
    assert item["source"] == "weather"


def test_cached_weather_is_written_as_decimal_because_dynamodb_rejects_floats(monkeypatch):
    from decimal import Decimal

    monkeypatch.setattr(tl, "query_source", lambda *a, **k: [])
    tbl = FakeDdbTable(rows=[])
    monkeypatch.setattr(tl, "table", tbl)
    _no_network(monkeypatch)
    tl._fetch_weather_range("2026-07-01", "2026-07-02")
    assert isinstance(tbl.puts[0]["temp_high_f"], Decimal)


def test_an_open_meteo_outage_still_returns_the_cached_days(monkeypatch):
    """A third-party outage must degrade to partial history, never blank the
    whole correlation."""
    monkeypatch.setattr(tl, "query_source", lambda *a, **k: [{"date": "2026-07-01", "temp_high_f": 78.1}])
    monkeypatch.setattr(tl, "table", FakeDdbTable(rows=[]))
    _no_network(monkeypatch, boom=True)
    out = tl._fetch_weather_range("2026-07-01", "2026-07-05")
    assert [r["date"] for r in out] == ["2026-07-01"]


def test_a_failed_cache_write_never_loses_the_day_the_caller_asked_for(monkeypatch):
    monkeypatch.setattr(tl, "query_source", lambda *a, **k: [])

    class _Boom:
        def put_item(self, **_k):
            raise RuntimeError("ddb throttled")

    monkeypatch.setattr(tl, "table", _Boom())
    _no_network(monkeypatch)
    out = tl._fetch_weather_range("2026-07-01", "2026-07-02")
    assert len(out) == 2, "a cache-write failure must not drop the fetched data"


def test_a_day_outside_the_requested_range_is_ignored(monkeypatch):
    """Open-Meteo can answer with a wider window than asked; only the days the
    caller is missing should be adopted."""
    payload = json.loads(json.dumps(_OPEN_METEO_DAY))
    payload["daily"]["time"] = ["2026-06-30", "2026-07-01"]
    monkeypatch.setattr(tl, "query_source", lambda *a, **k: [])
    tbl = FakeDdbTable(rows=[])
    monkeypatch.setattr(tl, "table", tbl)
    _no_network(monkeypatch, payload=payload)
    out = tl._fetch_weather_range("2026-07-01", "2026-07-01")
    assert [r["date"] for r in out] == ["2026-07-01"]
