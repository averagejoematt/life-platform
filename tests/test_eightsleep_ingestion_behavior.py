#!/usr/bin/env python3
"""tests/test_eightsleep_ingestion_behavior.py — behavioral contracts of
`lambdas/ingestion/eightsleep_lambda.py`.

Part of #1658 tranche 2. Eight Sleep is the platform's source of truth for sleep
staging: `/data/sleep`, the chronicle, the character sheet's Sleep pillar, the
hypothesis engine and every AI narrative that mentions a night read the record
this Lambda writes. A normalization defect here corrupts a stored day
permanently and every downstream score with it.

Every number asserted below is derived BY HAND from the fixture payload (the
arithmetic is spelled out beside each constant) — never captured from what the
code happened to return. The contracts under test:

  * stage/duration normalization: seconds → hours, TIB, efficiency, WASO,
    stage percentages,
  * the platform's night-attribution convention (session ending on morning D+1
    is stored under DATE#(D+1)) and which calendar day a run picks — the
    TD-19 / 2026-07-10 "UTC double-stamp" class,
  * ADR-104: absence is never rendered as 0, and (the inverse) a measured zero
    is never rendered as absence,
  * Decimal-before-DynamoDB on every stored number,
  * auth / token-refresh failure paths degrading honestly (re-login, persist,
    non-401 propagation),
  * idempotency on re-ingest — a second run rewrites the same key, never a
    second row,
  * the S3 raw layout DERIVED from `source_registry`'s `raw_layout` facet,
  * the field names this module writes vs. the field names its readers query.

Time is frozen wherever `datetime.now` or the Pacific-day helpers are reachable,
so no fixture date is ever combined with the real clock (the DST-sensitive
`_tz_offset_hours` path is exercised on both sides of the transition).
"""

import copy
import importlib
import json
import os
import sys
import time as _time_mod
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
# The module reads S3_BUCKET with os.environ[...] at import time (no default).
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

_import_err = None
try:
    from common import auth_breaker as _auth_breaker, secret_cache as _secret_cache_mod
    from ingestion import eightsleep_lambda as es, ingestion_framework as fw
    from ingestion.ingestion_validator import validate_item
    from ingestion.source_registry import SOURCE_REGISTRY
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    es = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"eightsleep_lambda unavailable: {_import_err}")  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Frozen clocks
# ──────────────────────────────────────────────────────────────────────────────

# 2026-05-10 is inside US daylight saving time → America/Los_Angeles is UTC-7.
SUMMER_UTC = datetime(2026, 5, 11, 1, 0, 0, tzinfo=timezone.utc)  # = 2026-05-10 18:00 PDT
# 2026-01-15 is standard time → America/Los_Angeles is UTC-8.
WINTER_UTC = datetime(2026, 1, 15, 19, 0, 0, tzinfo=timezone.utc)

WAKE_DATE = "2026-05-10"
PT_NOW = SUMMER_UTC.astimezone(timezone(timedelta(hours=-7)))


def _frozen_datetime(pinned):
    """Build a `datetime` subclass with `now()`/`utcnow()` pinned to `pinned`.

    A subclass rather than a Mock keeps `strptime`, `fromisoformat` and
    arithmetic working — the module uses all three off the same name.
    """

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return pinned.astimezone(tz) if tz else pinned.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return pinned.replace(tzinfo=None)

    return _FrozenDatetime


@pytest.fixture
def summer_clock(monkeypatch):
    monkeypatch.setattr(es, "datetime", _frozen_datetime(SUMMER_UTC))
    return SUMMER_UTC


@pytest.fixture
def winter_clock(monkeypatch):
    monkeypatch.setattr(es, "datetime", _frozen_datetime(WINTER_UTC))
    return WINTER_UTC


@pytest.fixture(autouse=True)
def _reset_module_globals(monkeypatch):
    """Every warm-container cache this module keeps is process-global — reset
    them so test order can never leak a token, a secret or client creds."""
    monkeypatch.setattr(es, "_es_client_cache", None, raising=False)
    monkeypatch.setattr(es, "_secret_cache", {}, raising=False)
    monkeypatch.setattr(es, "_secret_cache_simp2", {"secret": None}, raising=False)
    _secret_cache_mod.invalidate()
    yield
    _secret_cache_mod.invalidate()


# ──────────────────────────────────────────────────────────────────────────────
# The canonical night — every expected number below is hand-derived from THIS
# payload. Seconds are chosen so the three stages sum exactly to sleepDuration.
# ──────────────────────────────────────────────────────────────────────────────

SLEEP_S = 25200  # 7.00 h asleep
DEEP_S = 5400  # 1.50 h
REM_S = 5040  # 1.40 h
LIGHT_S = 14760  # 4.10 h   (5400 + 5040 + 14760 == 25200)
PRESENCE_S = 27000  # 7.50 h in bed → awake = 27000 - 25200 = 1800 s = 0.50 h
LATENCY_S = 900  # 15.0 min


def canonical_day(day=WAKE_DATE, **overrides):
    d = {
        "day": day,
        "score": 84,
        "sleepDuration": SLEEP_S,
        "remDuration": REM_S,
        "lightDuration": LIGHT_S,
        "deepDuration": DEEP_S,
        "presenceDuration": PRESENCE_S,
        # 06:54Z → 23:54 PDT on 2026-05-09 (the evening before the wake date)
        "sleepStart": "2026-05-10T06:54:00.000Z",
        # 14:06Z → 07:06 PDT on 2026-05-10
        "sleepEnd": "2026-05-10T14:06:00.000Z",
        "tnt": 22,
        "sleepQualityScore": {
            "hrv": {"current": 42.7},
            "heartRate": {"current": 56},
            "respiratoryRate": {"current": 13.4},
        },
        "sleepRoutineScore": {"latencyAsleepSeconds": {"current": LATENCY_S}},
    }
    d.update(overrides)
    return d


def canonical_trends(*days):
    return {"days": list(days) if days else [canonical_day()]}


# Hand-derived expectations at tz_offset = -7 (PDT).
#   sleep_duration_hours = 25200/3600                     = 7.00
#   awake_hours          = (27000-25200)/3600             = 0.50
#   time_in_bed_hours    = 7.00 + 0.50                    = 7.50
#   sleep_efficiency_pct = 7.00/7.50*100 = 93.333…        → 93.3
#   waso_hours           = 0.50 - (15.0/60)               = 0.25
#   rem_pct              = 1.40/7.00*100                  = 20.0
#   deep_pct             = 1.50/7.00*100 = 21.4285…       → 21.4
#   light_pct            = 4.10/7.00*100 = 58.5714…       → 58.6
#   sleep_onset_hour     = (6 + 54/60) - 7 = -0.1 mod 24  = 23.9
#   wake_hour            = (14 + 6/60) - 7                = 7.1
#   sleep_midpoint_hour  = ((23.9 + 31.1)/2) mod 24       = 3.5
EXPECTED_PDT = {
    "sleep_score": 84.0,
    "sleep_start": "2026-05-10T06:54:00.000Z",
    "sleep_end": "2026-05-10T14:06:00.000Z",
    "sleep_duration_hours": 7.0,
    "time_to_sleep_min": 15.0,
    "awake_hours": 0.5,
    "light_hours": 4.1,
    "deep_hours": 1.5,
    "rem_hours": 1.4,
    "hr_avg": 56.0,
    "hrv_avg": 42.7,
    "respiratory_rate": 13.4,
    "toss_turn_count": 22.0,
    "bed_side": "left",
    "time_in_bed_hours": 7.5,
    "sleep_efficiency_pct": 93.3,
    "waso_hours": 0.25,
    "rem_pct": 20.0,
    "deep_pct": 21.4,
    "light_pct": 58.6,
    "sleep_onset_hour": 23.9,
    "wake_hour": 7.1,
    "sleep_midpoint_hour": 3.5,
}


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────────


class FakeTable:
    """DynamoDB Table stand-in keyed the way the framework keys the real table."""

    def __init__(self, existing_sks=()):
        self.items = {}
        self.puts = []
        self.deletes = []
        self.queries = []
        # What `_find_missing_dates` sees as already-present.
        self.query_items = [{"sk": sk} for sk in existing_sks]

    def put_item(self, Item=None, **kwargs):
        self.puts.append(copy.deepcopy(Item))
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    def get_item(self, Key=None, **kwargs):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def delete_item(self, Key=None, **kwargs):
        self.deletes.append(Key)
        self.items.pop((Key["pk"], Key["sk"]), None)
        return {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"Items": list(self.query_items)}

    def data_rows(self):
        return [i for (_pk, sk), i in self.items.items() if sk.startswith("DATE#")]


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket=None, Key=None, Body=None, **kwargs):
        self.objects[Key] = {"Bucket": Bucket, "Body": Body}
        return {}


class FakeSecrets:
    def __init__(self, payload):
        self.payload = dict(payload)
        self.gets = 0
        self.updates = []

    def get_secret_value(self, SecretId=None):
        self.gets += 1
        return {"SecretString": json.dumps(self.payload)}

    def update_secret(self, SecretId=None, SecretString=None):
        self.updates.append((SecretId, SecretString))
        self.payload = json.loads(SecretString)
        return {}


class FakeHTTPResponse:
    """urlopen context-manager stand-in — `read()` only, like the retry wrapper."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


BASE_SECRET = {
    "email": "matthew@example.test",
    "password": "hunter2",
    "user_id": "es-user-1",
    "access_token": "tok-current",
    "refresh_token": "refresh-current",
    "bed_side": "left",
    "timezone": "America/Los_Angeles",
}


def _http_error(code):
    return urllib.error.HTTPError(url="https://client-api.8slp.net/x", code=code, msg="boom", hdrs=None, fp=None)


def _flatten(obj, prefix=""):
    """Yield (path, value) for every scalar in a nested dict/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


# ══════════════════════════════════════════════════════════════════════════════
# 1. The S3 raw layout and the source identity come from the registry
# ══════════════════════════════════════════════════════════════════════════════

REG = SOURCE_REGISTRY["eightsleep"]
RAW_LAYOUT = REG["raw_layout"]


class TestRegistryDerivedLayout:
    def test_the_ingestion_config_archives_under_the_prefix_the_registry_publishes(self):
        assert es._config.s3_archive_prefix == RAW_LAYOUT["prefix"]

    def test_the_config_source_name_is_the_registry_key_so_the_partition_matches(self):
        assert es._config.source_name == "eightsleep"
        assert es._config.source_name in SOURCE_REGISTRY

    def test_the_archived_object_key_matches_the_registry_scheme_and_filename(self):
        s3 = FakeS3()
        assert fw._archive_raw(s3, es._config, WAKE_DATE, {"trends": {}}) is None
        (key,) = list(s3.objects)
        # scheme "date-tree" + filename "YYYY-MM-DD.json" → prefix/YYYY/MM/YYYY-MM-DD.json
        assert RAW_LAYOUT["scheme"] == "date-tree"
        assert RAW_LAYOUT["filename"] == "YYYY-MM-DD.json"
        expected = "{p}/{y}/{m}/{d}.json".format(p=RAW_LAYOUT["prefix"], y=WAKE_DATE[:4], m=WAKE_DATE[5:7], d=WAKE_DATE)
        assert key == expected

    def test_an_archive_failure_is_reported_to_the_caller_not_swallowed(self):
        class Boom:
            def put_object(self, **kwargs):
                raise RuntimeError("AccessDenied")

        err = fw._archive_raw(Boom(), es._config, WAKE_DATE, {"trends": {}})
        assert isinstance(err, RuntimeError)

    def test_gap_detection_and_today_refresh_are_both_enabled_for_a_nightly_source(self):
        # Eight Sleep re-scores a night for hours after wake; the registry calls it
        # an active hourly API pull, so the config must re-fetch today every run.
        assert REG["active_api"] is True
        assert es._config.enable_gap_detection is True
        assert es._config.refresh_today is True


# ══════════════════════════════════════════════════════════════════════════════
# 2. Local-hour extraction — hand-derived arithmetic
# ══════════════════════════════════════════════════════════════════════════════


class TestHourOfDay:
    @pytest.mark.parametrize(
        "iso,offset,expected",
        [
            # 06:54Z − 7h = 23:54 the previous evening → 23.9
            ("2026-05-10T06:54:00.000Z", -7, 23.9),
            # 06:54Z − 8h = 22:54 → 22.9 (the docstring's own worked example)
            ("2026-02-20T06:54:00.000Z", -8, 22.9),
            # 14:06Z − 7h = 07:06 → 7 + 6/60 = 7.1
            ("2026-05-10T14:06:00.000Z", -7, 7.1),
            # seconds contribute: 15:06:30 − 8h = 07:06:30 → 7 + 6/60 + 30/3600 = 7.11
            ("2026-02-21T15:06:30.000Z", -8, 7.11),
            # midnight UTC − 8h wraps to the previous day's 16:00
            ("2026-05-10T00:00:00.000Z", -8, 16.0),
            # exactly the offset → local midnight, expressed as 0.0 not 24.0
            ("2026-05-10T08:00:00.000Z", -8, 0.0),
            # a "+00:00" suffix is the same instant as a "Z" suffix
            ("2026-05-10T06:54:00+00:00", -7, 23.9),
            # half-hour zones are supported (offset is a float, not an int)
            ("2026-05-10T06:54:00.000Z", -3.5, 3.4),
        ],
    )
    def test_local_fractional_hour_is_utc_clock_time_plus_the_offset_modulo_24(self, iso, offset, expected):
        assert es._hour_of_day(iso, offset) == expected

    @pytest.mark.parametrize("bad", ["", "not-a-timestamp", "2026-13-45T99:99:99Z", None, 12345])
    def test_an_unparseable_timestamp_yields_absence_not_a_zero_hour(self, bad):
        # ADR-104: midnight (0.0) is a real sleep onset. A parse failure must be
        # indistinguishable from "we don't know", never from "onset at 00:00".
        assert es._hour_of_day(bad, -8) is None

    def test_the_default_offset_is_pacific_standard_time(self):
        assert es._hour_of_day("2026-05-10T08:00:00.000Z") == 0.0
        assert es._DEFAULT_TZ_OFFSET == -8


# ══════════════════════════════════════════════════════════════════════════════
# 3. Sleep midpoint — the circadian marker social jetlag is measured from
# ══════════════════════════════════════════════════════════════════════════════


class TestSleepMidpoint:
    @pytest.mark.parametrize(
        "onset,wake,expected",
        [
            (23.0, 7.0, 3.0),  # docstring's example: (23 + 31)/2 = 27 → 3.0
            (23.9, 7.1, 3.5),  # the canonical night
            (22.5, 6.5, 2.5),  # (22.5 + 30.5)/2 = 26.5 → 2.5
            (0.0, 8.0, 4.0),  # no midnight crossing
            (1.0, 9.0, 5.0),  # onset already after midnight
            (21.0, 23.0, 22.0),  # an evening nap that never crosses midnight
        ],
    )
    def test_the_midpoint_crosses_midnight_instead_of_averaging_into_the_afternoon(self, onset, wake, expected):
        assert es._sleep_midpoint(onset, wake) == expected

    def test_a_midpoint_is_never_reported_outside_the_24_hour_clock(self):
        for onset in (0.0, 6.0, 12.0, 18.0, 23.75):
            for wake in (0.0, 5.5, 11.0, 23.99):
                mid = es._sleep_midpoint(onset, wake)
                assert 0.0 <= mid < 24.0


# ══════════════════════════════════════════════════════════════════════════════
# 4. Timezone offset — DST-aware, with the static map as a fallback only
# ══════════════════════════════════════════════════════════════════════════════


class TestTimezoneOffset:
    def test_a_summer_night_uses_the_daylight_offset(self, summer_clock):
        # The 2026-06-12 defect: the static map pinned standard time, so every
        # stored sleep hour landed 1h off from March to November.
        assert es._tz_offset_hours("America/Los_Angeles") == -7.0

    def test_a_winter_night_uses_the_standard_offset(self, winter_clock):
        assert es._tz_offset_hours("America/Los_Angeles") == -8.0

    def test_a_zone_without_dst_reports_the_same_offset_year_round(self, summer_clock):
        assert es._tz_offset_hours("Asia/Tokyo") == 9.0

    def test_an_unknown_zone_falls_back_to_the_pacific_default(self, summer_clock):
        assert es._tz_offset_hours("Mars/Olympus_Mons") == es._DEFAULT_TZ_OFFSET

    def test_every_entry_in_the_static_fallback_map_is_that_zones_standard_offset(self):
        """Guard the SET, not one instance: the fallback map is only honest if
        each hardcoded value equals the zone's non-DST offset — a southern-
        hemisphere zone (Sydney) is on DST in January, so a single-date check
        would silently pass a wrong number."""
        from zoneinfo import ZoneInfo

        assert es._TZ_OFFSETS, "the fallback map must not be empty"
        for zone, hardcoded in es._TZ_OFFSETS.items():
            tz = ZoneInfo(zone)
            standard = None
            for month in range(1, 13):
                probe = datetime(2026, month, 15, 12, 0, tzinfo=tz)
                if probe.dst() == timedelta(0):
                    standard = probe.utcoffset().total_seconds() / 3600
                    break
            assert standard is not None, f"{zone}: no standard-time month found"
            assert hardcoded == standard, f"{zone}: map says {hardcoded}, standard offset is {standard}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. _safe_float — the scalar coercion every raw field passes through
# ══════════════════════════════════════════════════════════════════════════════


class TestSafeFloat:
    @pytest.mark.parametrize(
        "value,divisor,expected",
        [
            (56, 1, 56.0),
            (42.7, 1, 42.7),
            (900, 60, 15.0),
            (Decimal("13.4"), 1, 13.4),
            ("18", 1, 18.0),
            (1.23456, 1, 1.23),  # rounds to 2dp
        ],
    )
    def test_numeric_values_are_divided_and_rounded_to_two_decimals(self, value, divisor, expected):
        assert es._safe_float(value, divisor) == expected

    @pytest.mark.parametrize("bad", [None, "n/a", object()])
    def test_an_unusable_value_becomes_absence_rather_than_a_number(self, bad):
        assert es._safe_float(bad) is None

    def test_a_measured_zero_survives_as_zero_and_is_not_confused_with_absence(self):
        # A tnt (toss-and-turn) count of 0 is a perfectly still night, not a
        # missing reading — ADR-104 cuts both ways.
        assert es._safe_float(0) == 0.0
        assert es._safe_float(0) is not None


# ══════════════════════════════════════════════════════════════════════════════
# 6. Parsing one night — the normalization that everything downstream inherits
# ══════════════════════════════════════════════════════════════════════════════


class TestParseTrendsForDate:
    def test_the_fixture_stages_sum_to_the_reported_sleep_duration(self):
        # Guards the hand-derived expectations below: if the fixture is
        # internally inconsistent, the percentage assertions prove nothing.
        assert DEEP_S + REM_S + LIGHT_S == SLEEP_S
        assert PRESENCE_S > SLEEP_S

    def test_a_full_night_normalizes_to_the_hand_derived_record(self):
        rec = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "left", tz_offset=-7)
        assert rec == EXPECTED_PDT

    @pytest.mark.parametrize(
        "field,expected",
        [
            ("sleep_duration_hours", 7.0),
            ("deep_hours", 1.5),
            ("rem_hours", 1.4),
            ("light_hours", 4.1),
            ("awake_hours", 0.5),
            ("time_to_sleep_min", 15.0),
        ],
    )
    def test_seconds_from_the_api_become_hours_or_minutes_at_two_decimals(self, field, expected):
        rec = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "left", tz_offset=-7)
        assert rec[field] == expected

    def test_awake_time_is_time_in_bed_minus_time_asleep(self):
        rec = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "left", tz_offset=-7)
        assert rec["awake_hours"] == round((PRESENCE_S - SLEEP_S) / 3600.0, 2)
        # The repo's canonical rule, in this source's units:
        # awake = (total_in_bed − total_asleep); TIB = asleep + awake.
        assert rec["time_in_bed_hours"] == round(PRESENCE_S / 3600.0, 2)

    def test_awake_time_can_never_go_negative_when_presence_undercounts_sleep(self):
        # Eight Sleep occasionally reports presenceDuration < sleepDuration after
        # a re-score; a negative "awake" would produce >100% efficiency.
        day = canonical_day(presenceDuration=SLEEP_S - 3600)
        rec = es.parse_trends_for_date({"days": [day]}, WAKE_DATE, "left", tz_offset=-7)
        assert "awake_hours" not in rec or rec["awake_hours"] >= 0.0
        assert rec.get("sleep_efficiency_pct", 100.0) <= 100.0

    def test_the_stored_session_boundaries_are_the_api_timestamps_verbatim(self):
        rec = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "left", tz_offset=-7)
        assert rec["sleep_start"] == "2026-05-10T06:54:00.000Z"
        assert rec["sleep_end"] == "2026-05-10T14:06:00.000Z"

    def test_the_night_is_attributed_to_the_wake_date_not_the_onset_date(self):
        # Platform convention: a session starting the evening of D and ending the
        # morning of D+1 is stored under DATE#(D+1). The onset timestamp is on
        # 2026-05-09 in local time; the record is still the 2026-05-10 night.
        rec = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "left", tz_offset=-7)
        assert rec["sleep_onset_hour"] > 12.0  # onset is the previous evening
        assert rec["wake_hour"] < 12.0  # wake is the morning of the wake date

    def test_the_matching_day_is_selected_out_of_a_multi_day_window(self):
        other = canonical_day(
            day="2026-05-09",
            sleepDuration=14400,
            presenceDuration=18000,
            deepDuration=3600,
            remDuration=3600,
            lightDuration=7200,
        )
        rec = es.parse_trends_for_date(canonical_trends(other, canonical_day()), WAKE_DATE, "left", tz_offset=-7)
        assert rec["sleep_duration_hours"] == 7.0  # the wake-date night, not 4.0

    def test_no_day_matching_the_requested_date_yields_no_record(self):
        payload = canonical_trends(canonical_day(day="2026-05-08"), canonical_day(day="2026-05-09"))
        assert es.parse_trends_for_date(payload, WAKE_DATE, "left", tz_offset=-7) is None

    @pytest.mark.parametrize("payload", [{}, {"days": []}, {"days": None}])
    def test_an_empty_trends_response_yields_no_record_rather_than_an_empty_night(self, payload):
        assert es.parse_trends_for_date(payload, WAKE_DATE, "left", tz_offset=-7) is None

    def test_the_bed_side_recorded_is_the_side_the_caller_configured(self):
        rec = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "right", tz_offset=-7)
        assert rec["bed_side"] == "right"

    def test_missing_biometric_blocks_leave_those_fields_absent_never_zero(self):
        day = canonical_day()
        day.pop("sleepQualityScore")
        day.pop("sleepRoutineScore")
        rec = es.parse_trends_for_date({"days": [day]}, WAKE_DATE, "left", tz_offset=-7)
        for field in ("hr_avg", "hrv_avg", "respiratory_rate", "time_to_sleep_min", "waso_hours"):
            assert field not in rec, f"{field} must be absent, not defaulted"
        # …while the fields that WERE measured still land.
        assert rec["sleep_duration_hours"] == 7.0

    def test_no_stored_field_ever_holds_a_none_value(self):
        day = canonical_day()
        day.pop("sleepQualityScore")
        rec = es.parse_trends_for_date({"days": [day]}, WAKE_DATE, "left", tz_offset=-7)
        assert all(v is not None for v in rec.values())

    def test_parsing_is_pure_so_a_re_ingest_of_the_same_payload_is_byte_identical(self):
        payload = canonical_trends()
        snapshot = copy.deepcopy(payload)
        first = es.parse_trends_for_date(payload, WAKE_DATE, "left", tz_offset=-7)
        second = es.parse_trends_for_date(payload, WAKE_DATE, "left", tz_offset=-7)
        assert first == second
        assert payload == snapshot, "the raw API payload must not be mutated in place"

    def test_the_timezone_offset_shifts_the_circadian_fields_and_nothing_else(self):
        pdt = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "left", tz_offset=-7)
        pst = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "left", tz_offset=-8)
        moved = {k for k in pdt if pdt[k] != pst.get(k)}
        assert moved == {"sleep_onset_hour", "wake_hour", "sleep_midpoint_hour"}
        assert pst["sleep_onset_hour"] == 22.9
        assert pst["wake_hour"] == 6.1

    def test_a_parsed_night_passes_the_platforms_own_eightsleep_validator(self):
        rec = es.parse_trends_for_date(canonical_trends(), WAKE_DATE, "left", tz_offset=-7)
        item = {
            "pk": "USER#matthew#SOURCE#eightsleep",
            "sk": f"DATE#{WAKE_DATE}",
            "date": WAKE_DATE,
            "schema_version": es._config.schema_version,
            **rec,
        }
        result = validate_item("eightsleep", item, WAKE_DATE)
        assert result.errors == []
        assert result.warnings == []


class TestZeroValuedStages:
    """A stage the sensor measured as ZERO must be stored as 0, not dropped.

    `secs_to_hours()` returns None for a falsy second-count, so every genuinely
    zero measurement is stripped by the `v is not None` filter and reaches the
    reader as "no data".
    """

    def test_a_night_with_zero_deep_sleep_stores_zero_not_absence(self):
        day = canonical_day(deepDuration=0, lightDuration=LIGHT_S + DEEP_S)
        rec = es.parse_trends_for_date({"days": [day]}, WAKE_DATE, "left", tz_offset=-7)
        assert rec["deep_hours"] == 0.0
        assert rec["deep_pct"] == 0.0

    def test_falling_asleep_instantly_stores_a_zero_latency_and_still_yields_waso(self):
        day = canonical_day(sleepRoutineScore={"latencyAsleepSeconds": {"current": 0}})
        rec = es.parse_trends_for_date({"days": [day]}, WAKE_DATE, "left", tz_offset=-7)
        assert rec["time_to_sleep_min"] == 0.0
        assert rec["waso_hours"] == 0.5

    def test_a_perfect_night_reports_100_percent_efficiency_rather_than_no_efficiency(self):
        day = canonical_day(presenceDuration=SLEEP_S)
        rec = es.parse_trends_for_date({"days": [day]}, WAKE_DATE, "left", tz_offset=-7)
        assert rec["awake_hours"] == 0.0
        assert rec["time_in_bed_hours"] == 7.0
        assert rec["sleep_efficiency_pct"] == 100.0


class TestSingleDayFallbackMisattribution:
    def test_a_lone_non_matching_night_is_not_relabelled_as_the_requested_date(self):
        payload = {"days": [canonical_day(day="2026-05-09")]}
        assert es.parse_trends_for_date(payload, WAKE_DATE, "left", tz_offset=-7) is None


# ══════════════════════════════════════════════════════════════════════════════
# 7. Derived clinical fields — usable on a fresh parse AND a stored DDB item
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeDerivedFields:
    BASE = {
        "sleep_duration_hours": 7.0,
        "awake_hours": 0.5,
        "time_to_sleep_min": 15.0,
        "rem_hours": 1.4,
        "deep_hours": 1.5,
        "light_hours": 4.1,
        "sleep_start": "2026-05-10T06:54:00.000Z",
        "sleep_end": "2026-05-10T14:06:00.000Z",
    }

    def test_the_derived_block_is_exactly_the_documented_clinical_fields(self):
        derived = es.compute_derived_fields(dict(self.BASE), tz_offset=-7)
        assert set(derived) == {
            "time_in_bed_hours",
            "sleep_efficiency_pct",
            "waso_hours",
            "rem_pct",
            "deep_pct",
            "light_pct",
            "sleep_onset_hour",
            "wake_hour",
            "sleep_midpoint_hour",
        }

    def test_time_in_bed_is_sleep_plus_awake_and_efficiency_is_their_ratio(self):
        derived = es.compute_derived_fields(dict(self.BASE), tz_offset=-7)
        assert derived["time_in_bed_hours"] == 7.5
        assert derived["sleep_efficiency_pct"] == 93.3  # 7.0/7.5*100 = 93.333…

    def test_waso_is_total_awake_minus_onset_latency(self):
        derived = es.compute_derived_fields(dict(self.BASE), tz_offset=-7)
        assert derived["waso_hours"] == 0.25  # 0.50 h awake − 15 min latency

    def test_waso_clamps_at_zero_when_latency_alone_exceeds_the_awake_total(self):
        rec = dict(self.BASE, awake_hours=0.1, time_to_sleep_min=30.0)
        assert es.compute_derived_fields(rec, tz_offset=-7)["waso_hours"] == 0.0

    @pytest.mark.parametrize("field,expected", [("rem_pct", 20.0), ("deep_pct", 21.4), ("light_pct", 58.6)])
    def test_stage_percentages_are_the_stage_hours_over_total_sleep(self, field, expected):
        assert es.compute_derived_fields(dict(self.BASE), tz_offset=-7)[field] == expected

    def test_the_three_stage_percentages_sum_to_one_hundred_when_the_stages_do(self):
        derived = es.compute_derived_fields(dict(self.BASE), tz_offset=-7)
        total = derived["rem_pct"] + derived["deep_pct"] + derived["light_pct"]
        assert abs(total - 100.0) <= 0.1  # rounding slack only

    def test_a_record_read_back_from_dynamodb_as_decimals_derives_the_same_numbers(self):
        # The backfill script calls this directly on stored items, where every
        # number is a Decimal.
        stored = {k: (Decimal(str(v)) if isinstance(v, float) else v) for k, v in self.BASE.items()}
        assert es.compute_derived_fields(stored, tz_offset=-7) == es.compute_derived_fields(dict(self.BASE), tz_offset=-7)

    def test_missing_sleep_duration_omits_every_dependent_field_rather_than_zeroing_it(self):
        rec = dict(self.BASE)
        rec.pop("sleep_duration_hours")
        derived = es.compute_derived_fields(rec, tz_offset=-7)
        for absent in ("time_in_bed_hours", "sleep_efficiency_pct", "rem_pct", "deep_pct", "light_pct"):
            assert absent not in derived

    def test_missing_awake_hours_omits_efficiency_and_waso_rather_than_zeroing_them(self):
        rec = dict(self.BASE)
        rec.pop("awake_hours")
        derived = es.compute_derived_fields(rec, tz_offset=-7)
        assert "time_in_bed_hours" not in derived
        assert "sleep_efficiency_pct" not in derived
        assert "waso_hours" not in derived

    def test_a_night_with_no_sleep_at_all_does_not_divide_by_zero(self):
        rec = dict(self.BASE, sleep_duration_hours=0.0)
        derived = es.compute_derived_fields(rec, tz_offset=-7)
        assert "rem_pct" not in derived
        assert derived["sleep_efficiency_pct"] == 0.0  # in bed 0.5 h, slept none

    def test_a_session_with_only_an_onset_timestamp_reports_onset_but_no_midpoint(self):
        rec = dict(self.BASE)
        rec.pop("sleep_end")
        derived = es.compute_derived_fields(rec, tz_offset=-7)
        assert derived["sleep_onset_hour"] == 23.9
        assert "wake_hour" not in derived
        assert "sleep_midpoint_hour" not in derived

    def test_an_empty_record_derives_nothing_instead_of_a_row_of_zeroes(self):
        assert es.compute_derived_fields({}, tz_offset=-7) == {}

    def test_the_helper_returns_only_new_fields_and_never_echoes_its_input(self):
        derived = es.compute_derived_fields(dict(self.BASE), tz_offset=-7)
        assert not (set(derived) & set(self.BASE))


# ══════════════════════════════════════════════════════════════════════════════
# 8. transform() — the framework-facing contract
# ══════════════════════════════════════════════════════════════════════════════


class TestTransform:
    def _raw(self, tz="America/Los_Angeles", days=None):
        return {"trends": {"days": days or [canonical_day()]}, "bed_side": "left", "tz": tz}

    def test_one_night_becomes_exactly_one_record_stamped_with_source_and_date(self, summer_clock):
        items = es.transform(self._raw(), WAKE_DATE)
        assert len(items) == 1
        assert items[0]["source"] == "eightsleep"
        assert items[0]["date"] == WAKE_DATE

    def test_the_record_carries_no_key_attributes_because_the_framework_owns_them(self, summer_clock):
        item = es.transform(self._raw(), WAKE_DATE)[0]
        assert "pk" not in item and "sk" not in item and "sk_suffix" not in item

    def test_the_stored_date_is_the_requested_wake_date_not_the_api_day_label(self, summer_clock):
        # Defends the day-attribution contract at the transform boundary.
        raw = self._raw(days=[canonical_day(day=WAKE_DATE), canonical_day(day="2026-05-09")])
        assert es.transform(raw, WAKE_DATE)[0]["date"] == WAKE_DATE

    @pytest.mark.parametrize("raw", [None, {}])
    def test_an_absent_upstream_response_produces_no_records(self, raw, summer_clock):
        assert es.transform(raw, WAKE_DATE) == []

    def test_a_response_with_no_matching_night_produces_no_records(self, summer_clock):
        raw = self._raw(days=[canonical_day(day="2026-05-07"), canonical_day(day="2026-05-08")])
        assert es.transform(raw, WAKE_DATE) == []

    def test_the_secrets_timezone_drives_the_circadian_fields_through_dst(self, summer_clock, monkeypatch):
        summer = es.transform(self._raw(), WAKE_DATE)[0]
        assert summer["sleep_onset_hour"] == 23.9  # PDT, UTC-7
        monkeypatch.setattr(es, "datetime", _frozen_datetime(WINTER_UTC))
        winter = es.transform(self._raw(), WAKE_DATE)[0]
        assert winter["sleep_onset_hour"] == 22.9  # PST, UTC-8

    def test_every_stored_number_survives_the_decimal_conversion_dynamodb_requires(self, summer_clock):
        item = es.transform(self._raw(), WAKE_DATE)[0]
        converted = fw.floats_to_decimal(item)
        floats = [p for p, v in _flatten(converted) if isinstance(v, float)]
        assert floats == [], f"boto3 rejects native floats; still present at {floats}"
        assert converted["sleep_duration_hours"] == Decimal("7.0")
        assert converted["sleep_efficiency_pct"] == Decimal("93.3")


# ══════════════════════════════════════════════════════════════════════════════
# 9. Secrets + auth
# ══════════════════════════════════════════════════════════════════════════════


class TestSecretHandling:
    def test_a_warm_container_reuses_a_cached_secret_instead_of_re_reading_it(self, monkeypatch):
        client = FakeSecrets(BASE_SECRET)
        monkeypatch.setattr(es, "secrets_client", client)
        assert es.get_secret()["access_token"] == "tok-current"
        assert es.get_secret()["access_token"] == "tok-current"
        assert client.gets == 1

    def test_a_cached_secret_is_re_read_once_the_fifteen_minute_ttl_expires(self, monkeypatch):
        client = FakeSecrets(BASE_SECRET)
        monkeypatch.setattr(es, "secrets_client", client)
        now = [1_000_000.0]
        monkeypatch.setattr(_time_mod, "time", lambda: now[0])
        es.get_secret()
        now[0] += 901
        es.get_secret()
        assert client.gets == 2

    def test_persisting_a_rotated_token_invalidates_the_cache_so_the_next_read_is_fresh(self, monkeypatch):
        client = FakeSecrets(BASE_SECRET)
        monkeypatch.setattr(es, "secrets_client", client)
        es.get_secret()
        es.save_secret({**BASE_SECRET, "access_token": "tok-rotated"})
        assert json.loads(client.updates[0][1])["access_token"] == "tok-rotated"
        assert es.get_secret()["access_token"] == "tok-rotated"
        assert client.gets == 2

    def test_the_secret_is_written_back_under_the_platforms_canonical_secret_id(self, monkeypatch):
        client = FakeSecrets(BASE_SECRET)
        monkeypatch.setattr(es, "secrets_client", client)
        es.save_secret(dict(BASE_SECRET))
        assert client.updates[0][0] == es.SECRET_NAME == es._config.secret_id
        assert es.SECRET_NAME.startswith("life-platform/")


class TestAuthenticate:
    def test_an_existing_access_token_is_reused_so_the_password_grant_is_not_burned(self, monkeypatch):
        calls = []
        monkeypatch.setattr(es, "login", lambda *a, **k: calls.append(a) or {})
        creds = es.authenticate(dict(BASE_SECRET))
        assert calls == [], "a valid cached token must not trigger a re-login"
        assert creds["access_token"] == "tok-current"

    def test_a_missing_access_token_forces_a_fresh_password_grant(self, monkeypatch):
        secret = {k: v for k, v in BASE_SECRET.items() if k != "access_token"}
        seen = {}

        def fake_login(email, password, *a, **k):
            seen["email"] = email
            return {"access_token": "tok-new", "refresh_token": "refresh-new", "user_id": "es-user-1"}

        monkeypatch.setattr(es, "login", fake_login)
        creds = es.authenticate(secret)
        assert creds["access_token"] == "tok-new"
        assert seen["email"] == BASE_SECRET["email"]

    def test_authentication_does_not_mutate_the_secret_dict_it_was_handed(self, monkeypatch):
        monkeypatch.setattr(es, "login", lambda *a, **k: {"access_token": "x", "refresh_token": "y", "user_id": "z"})
        original = dict(BASE_SECRET)
        es.authenticate(original)
        assert original == BASE_SECRET

    def test_the_authenticated_secret_is_handed_to_the_fetch_stage_through_the_module_cache(self):
        creds = es.authenticate(dict(BASE_SECRET))
        assert es._secret_cache_simp2["secret"] == creds

    def test_a_known_user_id_is_reused_without_a_users_me_round_trip(self, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("ensure_user_id must not call the API when the id is cached")

        monkeypatch.setattr(es.urllib.request, "Request", explode)
        assert es.ensure_user_id(dict(BASE_SECRET))["user_id"] == "es-user-1"

    def test_an_unknown_user_id_is_resolved_once_and_cached_into_the_secret(self, monkeypatch):
        secret = {k: v for k, v in BASE_SECRET.items() if k != "user_id"}
        body = json.dumps({"user": {"userId": "es-resolved"}}).encode()
        import common.http_retry as http_retry

        monkeypatch.setattr(http_retry, "urlopen_with_retry", lambda req, timeout=30: FakeHTTPResponse(body))
        assert es.ensure_user_id(secret)["user_id"] == "es-resolved"


class TestLogin:
    def _capture(self, monkeypatch, body):
        captured = {}

        class _Req:
            def __init__(self, url, data=None, headers=None, method=None):
                captured["url"] = url
                captured["payload"] = json.loads(data) if data else None
                captured["method"] = method

        import common.http_retry as http_retry

        monkeypatch.setattr(es.urllib.request, "Request", _Req)
        monkeypatch.setattr(http_retry, "urlopen_with_retry", lambda req, timeout=30: FakeHTTPResponse(body))
        return captured

    def test_a_login_posts_a_password_grant_to_the_auth_api(self, monkeypatch):
        body = json.dumps({"access_token": "a", "refresh_token": "r", "userId": "u"}).encode()
        captured = self._capture(monkeypatch, body)
        result = es.login("me@example.test", "pw", client_id="cid", client_secret="csec")
        assert captured["method"] == "POST"
        assert captured["url"].startswith(es.AUTH_API)
        assert captured["payload"]["grant_type"] == "password"
        assert captured["payload"]["username"] == "me@example.test"
        assert result == {"access_token": "a", "refresh_token": "r", "user_id": "u"}

    def test_a_login_response_without_a_token_fails_loudly_instead_of_returning_a_blank_one(self, monkeypatch):
        # Silently returning access_token="" would turn one bad response into a
        # 24h ADR-052 breaker trip with no diagnosable cause.
        self._capture(monkeypatch, json.dumps({"userId": "u"}).encode())
        with pytest.raises(KeyError):
            es.login("me@example.test", "pw", client_id="cid", client_secret="csec")

    def test_a_re_login_replaces_both_tokens_on_the_secret_it_is_given(self, monkeypatch):
        monkeypatch.setattr(es, "login", lambda e, p: {"access_token": "tok-2", "refresh_token": "refresh-2", "user_id": "u"})
        secret = es.refresh_token(dict(BASE_SECRET))
        assert secret["access_token"] == "tok-2"
        assert secret["refresh_token"] == "refresh-2"


class TestClientCredentialCache:
    def test_client_credentials_are_read_once_and_reused_within_a_warm_container(self, monkeypatch):
        client = FakeSecrets({"client_id": "cid", "client_secret": "csec"})
        monkeypatch.setattr(es, "secrets_client", client)
        assert es._get_es_client_creds()["client_id"] == "cid"
        assert es._get_es_client_creds()["client_id"] == "cid"
        assert client.gets == 1

    def test_a_transient_secrets_manager_failure_does_not_latch_empty_client_credentials(self, monkeypatch):
        state = {"fail": True}

        class Flaky:
            gets = 0

            def get_secret_value(self, SecretId=None):
                if state["fail"]:
                    raise RuntimeError("ThrottlingException")
                return {"SecretString": json.dumps({"client_id": "cid", "client_secret": "csec"})}

        monkeypatch.setattr(es, "secrets_client", Flaky())
        assert es._get_es_client_creds() == {}
        state["fail"] = False
        assert es._get_es_client_creds()["client_id"] == "cid"


# ══════════════════════════════════════════════════════════════════════════════
# 10. fetch_day — the 401 re-login path
# ══════════════════════════════════════════════════════════════════════════════


class TestFetchDay:
    def test_the_trends_window_spans_the_night_before_the_wake_date(self, monkeypatch):
        seen = {}

        def fake_api_get(path, token, params=None):
            seen.update(path=path, token=token, params=params)
            return canonical_trends()

        monkeypatch.setattr(es, "api_get", fake_api_get)
        raw = es.fetch_day(dict(BASE_SECRET), WAKE_DATE)
        assert seen["path"] == "/v1/users/es-user-1/trends"
        assert seen["params"] == {"from": "2026-05-09", "to": WAKE_DATE, "tz": "America/Los_Angeles"}
        assert seen["token"] == "tok-current"
        assert raw["bed_side"] == "left"
        assert raw["tz"] == "America/Los_Angeles"

    def test_the_window_start_is_always_the_calendar_day_before_the_requested_date(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(es, "api_get", lambda p, t, params=None: seen.update(params=params) or canonical_trends())
        es.fetch_day(dict(BASE_SECRET), "2026-03-01")  # crosses a month boundary
        assert seen["params"]["from"] == "2026-02-28"

    def test_an_expired_token_triggers_one_re_login_and_the_retry_uses_the_new_token(self, monkeypatch):
        tokens = []

        def fake_api_get(path, token, params=None):
            tokens.append(token)
            if len(tokens) == 1:
                raise _http_error(401)
            return canonical_trends()

        monkeypatch.setattr(es, "api_get", fake_api_get)
        monkeypatch.setattr(es, "login", lambda e, p: {"access_token": "tok-fresh", "refresh_token": "r2", "user_id": "u"})
        monkeypatch.setattr(es, "save_secret", lambda s: None)
        raw = es.fetch_day(dict(BASE_SECRET), WAKE_DATE)
        assert tokens == ["tok-current", "tok-fresh"]
        assert raw["trends"] == canonical_trends()

    def test_the_token_minted_on_the_401_path_is_persisted_so_the_next_run_starts_valid(self, monkeypatch):
        # #481/A-1: without this persist, every scheduled run burned a password
        # grant against an unofficial API (126/week).
        persisted = []
        attempts = {"n": 0}

        def fake_api_get(path, token, params=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise _http_error(401)
            return canonical_trends()

        monkeypatch.setattr(es, "api_get", fake_api_get)
        monkeypatch.setattr(es, "login", lambda e, p: {"access_token": "tok-fresh", "refresh_token": "r2", "user_id": "u"})
        monkeypatch.setattr(es, "save_secret", lambda s: persisted.append(s))
        es.fetch_day(dict(BASE_SECRET), WAKE_DATE)
        assert len(persisted) == 1
        assert persisted[0]["access_token"] == "tok-fresh"

    def test_a_failed_token_persist_still_lets_the_nights_data_land(self, monkeypatch):
        seq = {"n": 0}

        def fake_api_get(path, token, params=None):
            seq["n"] += 1
            if seq["n"] == 1:
                raise _http_error(401)
            return canonical_trends()

        monkeypatch.setattr(es, "api_get", fake_api_get)
        monkeypatch.setattr(es, "login", lambda e, p: {"access_token": "tok-fresh", "refresh_token": "r2", "user_id": "u"})

        def boom(_s):
            raise RuntimeError("AccessDenied on UpdateSecret")

        monkeypatch.setattr(es, "save_secret", boom)
        assert es.fetch_day(dict(BASE_SECRET), WAKE_DATE)["trends"] == canonical_trends()

    @pytest.mark.parametrize("code", [403, 429, 500, 503])
    def test_a_non_401_http_failure_propagates_instead_of_being_retried_as_auth(self, code, monkeypatch):
        monkeypatch.setattr(es, "api_get", lambda p, t, params=None: _raise(_http_error(code)))
        monkeypatch.setattr(es, "login", lambda e, p: pytest.fail("a non-401 must not trigger a re-login"))
        with pytest.raises(urllib.error.HTTPError):
            es.fetch_day(dict(BASE_SECRET), WAKE_DATE)

    def test_the_freshly_authenticated_secret_wins_over_a_stale_credentials_argument(self, monkeypatch):
        es.authenticate({**BASE_SECRET, "access_token": "tok-authenticated"})
        seen = {}
        monkeypatch.setattr(es, "api_get", lambda p, t, params=None: seen.update(token=t) or canonical_trends())
        es.fetch_day({**BASE_SECRET, "access_token": "tok-stale"}, WAKE_DATE)
        assert seen["token"] == "tok-authenticated"


def _raise(exc):
    raise exc


class TestApiGet:
    def test_a_gzipped_response_is_decompressed_by_magic_bytes_not_by_header(self, monkeypatch):
        # http_retry hides response headers, so Content-Encoding is unavailable.
        import gzip

        import common.http_retry as http_retry

        payload = json.dumps({"days": []}).encode()
        monkeypatch.setattr(es.urllib.request, "Request", lambda *a, **k: None)
        monkeypatch.setattr(http_retry, "urlopen_with_retry", lambda req, timeout=30: FakeHTTPResponse(gzip.compress(payload)))
        assert es.api_get("/v1/x", "tok") == {"days": []}

    def test_an_uncompressed_response_is_parsed_unchanged(self, monkeypatch):
        import common.http_retry as http_retry

        monkeypatch.setattr(es.urllib.request, "Request", lambda *a, **k: None)
        monkeypatch.setattr(http_retry, "urlopen_with_retry", lambda req, timeout=30: FakeHTTPResponse(b'{"days": [1]}'))
        assert es.api_get("/v1/x", "tok") == {"days": [1]}

    def test_query_parameters_are_url_encoded_onto_the_client_api_base(self, monkeypatch):
        seen = {}
        import common.http_retry as http_retry

        monkeypatch.setattr(es.urllib.request, "Request", lambda url, headers=None: seen.update(url=url, headers=headers))
        monkeypatch.setattr(http_retry, "urlopen_with_retry", lambda req, timeout=30: FakeHTTPResponse(b"{}"))
        es.api_get("/v1/users/u/trends", "tok-abc", params={"from": "2026-05-09", "tz": "America/Los_Angeles"})
        assert seen["url"].startswith(es.CLIENT_API + "/v1/users/u/trends?")
        assert "tz=America%2FLos_Angeles" in seen["url"]
        assert seen["headers"]["Authorization"] == "Bearer tok-abc"


# ══════════════════════════════════════════════════════════════════════════════
# 11. End-to-end through the SIMP-2 framework
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def wired(monkeypatch):
    """Wire the Lambda to fakes at the framework's own seams — no AWS, no HTTP."""
    table = FakeTable(existing_sks=[f"DATE#2026-05-0{d}" for d in range(3, 10)])
    s3 = FakeS3()
    secrets = FakeSecrets(BASE_SECRET)

    monkeypatch.setattr(fw, "_init_aws", lambda config: (table, s3, secrets))
    monkeypatch.setattr(fw, "pacific_now", lambda: PT_NOW)
    monkeypatch.setattr(fw, "pacific_today", lambda: WAKE_DATE)
    monkeypatch.setattr(fw, "time", type("T", (), {"sleep": staticmethod(lambda s: None)})())
    monkeypatch.setattr(_auth_breaker, "_emit_auth_health", lambda *a, **k: None)
    monkeypatch.setattr(es, "datetime", _frozen_datetime(SUMMER_UTC))

    calls = []

    def fake_api_get(path, token, params=None):
        calls.append({"path": path, "token": token, "params": params})
        # Label the night with the wake date actually requested — the vendor keys
        # `day` off its own local wake date, and a fixture that always answers
        # 2026-05-10 would let a day-attribution defect read as correct.
        return canonical_trends(canonical_day(day=(params or {}).get("to", WAKE_DATE)))

    monkeypatch.setattr(es, "api_get", fake_api_get)
    return {"table": table, "s3": s3, "secrets": secrets, "calls": calls}


class TestEndToEndIngestion:
    def test_a_run_at_six_pm_pacific_ingests_the_pacific_day_not_the_already_rolled_utc_day(self, wired):
        # The 2026-07-10 truth audit: at 18:00 PT the UTC calendar already reads
        # 2026-05-11, and the pre-fix framework wrote the same night under two
        # DATE# keys. Frozen instant here IS 2026-05-11T01:00Z.
        assert SUMMER_UTC.strftime("%Y-%m-%d") == "2026-05-11"
        es.lambda_handler({}, None)
        assert [c["params"]["to"] for c in wired["calls"]] == [WAKE_DATE]
        assert [i["sk"] for i in wired["table"].data_rows()] == [f"DATE#{WAKE_DATE}"]

    def test_the_night_lands_on_the_single_table_key_the_platform_reads_it_from(self, wired):
        es.lambda_handler({}, None)
        (item,) = wired["table"].data_rows()
        assert item["pk"] == f"USER#{es._config.user_id}#SOURCE#eightsleep"
        assert item["sk"] == f"DATE#{WAKE_DATE}"
        assert item["source"] == "eightsleep"
        assert item["date"] == WAKE_DATE

    def test_every_number_written_to_dynamodb_is_a_decimal(self, wired):
        es.lambda_handler({}, None)
        (item,) = wired["table"].data_rows()
        offenders = [p for p, v in _flatten(item) if isinstance(v, float)]
        assert offenders == [], f"boto3 rejects native floats; found at {offenders}"

    def test_the_stored_night_carries_the_hand_derived_clinical_values(self, wired):
        es.lambda_handler({}, None)
        (item,) = wired["table"].data_rows()
        for field, expected in EXPECTED_PDT.items():
            stored = item[field]
            if isinstance(expected, str):
                assert stored == expected, field
            else:
                assert float(stored) == pytest.approx(expected), field

    def test_the_record_is_phase_stamped_so_the_read_path_filter_can_place_it(self, wired):
        es.lambda_handler({}, None)
        (item,) = wired["table"].data_rows()
        assert item["phase"] == fw.phase_for_date(WAKE_DATE)

    def test_the_raw_response_is_archived_under_the_registrys_layout(self, wired):
        es.lambda_handler({}, None)
        expected = "{p}/{y}/{m}/{d}.json".format(p=RAW_LAYOUT["prefix"], y=WAKE_DATE[:4], m=WAKE_DATE[5:7], d=WAKE_DATE)
        assert expected in wired["s3"].objects
        archived = json.loads(wired["s3"].objects[expected]["Body"])
        assert archived["raw"]["trends"]["days"][0]["day"] == WAKE_DATE

    def test_re_ingesting_the_same_night_overwrites_one_row_rather_than_adding_a_second(self, wired):
        es.lambda_handler({}, None)
        first = copy.deepcopy(wired["table"].data_rows()[0])
        es.lambda_handler({}, None)
        rows = wired["table"].data_rows()
        assert len(rows) == 1
        volatile = {"ingested_at"}
        assert {k: v for k, v in rows[0].items() if k not in volatile} == {k: v for k, v in first.items() if k not in volatile}

    def test_an_explicit_date_override_ingests_exactly_that_night(self, wired):
        es.lambda_handler({"date_override": "2026-04-02"}, None)
        assert [c["params"]["to"] for c in wired["calls"]] == ["2026-04-02"]
        assert [i["sk"] for i in wired["table"].data_rows()] == ["DATE#2026-04-02"]

    def test_a_healthcheck_returns_ok_without_touching_aws_or_the_vendor_api(self, wired):
        assert es.lambda_handler({"healthcheck": True}, None) == {"statusCode": 200, "body": "ok"}
        assert wired["calls"] == []
        assert wired["table"].puts == []

    def test_a_run_with_nothing_missing_reports_no_gaps_and_makes_no_api_call(self, wired, monkeypatch):
        monkeypatch.setattr(es._config, "refresh_today", False, raising=False)
        wired["table"].query_items.append({"sk": f"DATE#{WAKE_DATE}"})
        resp = es.lambda_handler({}, None)
        assert json.loads(resp["body"])["message"] == "No gaps to fill"
        assert wired["calls"] == []

    def test_a_tripped_auth_breaker_suppresses_the_vendor_call_and_says_so_honestly(self, wired):
        marked = datetime.now(timezone.utc).isoformat()
        wired["table"].items[(f"USER#{es._config.user_id}#SOURCE#eightsleep", "AUTH_FAILURE")] = {
            "pk": f"USER#{es._config.user_id}#SOURCE#eightsleep",
            "sk": "AUTH_FAILURE",
            "marked_at": marked,
            "error": "401 Unauthorized",
        }
        resp = es.lambda_handler({}, None)
        assert json.loads(resp["body"])["skipped"] == "auth_failure_circuit_breaker"
        assert wired["calls"] == [], "a tripped breaker must not reach the vendor API"
        assert wired["table"].data_rows() == []

    def test_a_persistent_401_trips_the_breaker_instead_of_alarming_every_run(self, wired, monkeypatch):
        monkeypatch.setattr(es, "api_get", lambda p, t, params=None: _raise(_http_error(401)))
        monkeypatch.setattr(es, "login", lambda e, p: _raise(_http_error(401)))
        es.lambda_handler({}, None)
        markers = [i for (_pk, sk), i in wired["table"].items.items() if sk == "AUTH_FAILURE"]
        assert len(markers) == 1
        assert "401" in markers[0]["error"]

    def test_a_successful_run_clears_a_stale_breaker_marker(self, wired):
        key = (f"USER#{es._config.user_id}#SOURCE#eightsleep", "AUTH_FAILURE")
        wired["table"].items[key] = {"pk": key[0], "sk": "AUTH_FAILURE", "marked_at": "2020-01-01T00:00:00+00:00"}
        es.lambda_handler({}, None)
        assert key not in wired["table"].items

    def test_the_run_summary_reports_what_was_written_for_the_liveness_surfaces(self, wired):
        body = json.loads(es.lambda_handler({}, None)["body"])
        assert body["source"] == "eightsleep"
        assert body["records_written"] == 1
        assert body["errors"] == 0
        assert body["archive_failures"] == 0

    def test_a_vendor_response_with_no_matching_night_writes_nothing_and_leaves_the_gap(self, wired, monkeypatch):
        monkeypatch.setattr(
            es, "api_get", lambda p, t, params=None: canonical_trends(canonical_day(day="2026-05-08"), canonical_day(day="2026-05-09"))
        )
        body = json.loads(es.lambda_handler({}, None)["body"])
        assert body["records_written"] == 0
        assert wired["table"].data_rows() == []

    def test_an_unexpected_failure_is_re_raised_so_the_invocation_is_visibly_red(self, wired, monkeypatch):
        # Patch where the name is LOOKED UP: the handler imported run_ingestion
        # into its own namespace, so patching the framework module is a no-op.
        monkeypatch.setattr(es, "run_ingestion", lambda *a, **k: _raise(RuntimeError("table gone")))
        with pytest.raises(RuntimeError, match="table gone"):
            es.lambda_handler({}, None)


# ══════════════════════════════════════════════════════════════════════════════
# 12. Writer/reader field-name contract
# ══════════════════════════════════════════════════════════════════════════════


def _written_field_names():
    """The complete set of attribute names this Lambda stores on an Eight Sleep
    DATE# record — derived from a real transform, never hand-listed."""
    raw = {"trends": canonical_trends(), "bed_side": "left", "tz": "America/Los_Angeles"}
    item = es.transform(raw, WAKE_DATE)[0]
    return set(item) | {"pk", "sk", "schema_version", "ingested_at", "phase"}


class TestWriterReaderFieldNames:
    def test_the_documented_field_list_matches_what_the_module_actually_writes(self, summer_clock):
        written = _written_field_names()
        doc = es.__doc__ or ""
        documented = {
            "sleep_score",
            "sleep_start",
            "sleep_end",
            "sleep_duration_hours",
            "time_to_sleep_min",
            "awake_hours",
            "light_hours",
            "deep_hours",
            "rem_hours",
            "hr_avg",
            "hrv_avg",
            "respiratory_rate",
            "toss_turn_count",
            "bed_side",
            "time_in_bed_hours",
            "sleep_efficiency_pct",
            "waso_hours",
            "rem_pct",
            "deep_pct",
            "light_pct",
            "sleep_onset_hour",
            "wake_hour",
            "sleep_midpoint_hour",
        }
        assert documented <= written, f"module docstring promises fields it never writes: {documented - written}"
        for name in documented:
            assert name in doc

    def test_the_freshness_checkers_liveness_fields_are_fields_this_lambda_writes(self, summer_clock):
        from emails.freshness_checker_lambda import FIELD_COMPLETENESS_CHECKS

        written = _written_field_names()
        missing = [f for f in FIELD_COMPLETENESS_CHECKS["eightsleep"] if f not in written]
        assert missing == [], f"freshness would read the partition as dead: {missing}"

    def test_the_hypothesis_engine_reads_the_onset_latency_field_the_writer_stores(self, summer_clock):
        # hypothesis_engine_lambda maps sleep_onset_min <- time_to_sleep_min.
        assert "time_to_sleep_min" in _written_field_names()

    def test_every_eightsleep_field_the_experiment_metric_registries_query_is_actually_written(self, summer_clock):
        """FIXED (#2221). Both registries used to query the eightsleep partition for
        'sleep_onset_latency_min', which this Lambda has never written — the stored
        name is 'time_to_sleep_min'. Sleep Onset Latency is the ONLY Eight-Sleep-
        exclusive criterion metric, so any pre-registered experiment choosing it
        extracted None for every day and closed with an empty series. The DESIGN_METRICS
        KEY (the frozen pre-registration slug) is unchanged; only the field it reads is."""
        from experiment.experiment_design import DESIGN_METRICS

        written = _written_field_names()
        wanted = {field for (source, field, _label) in DESIGN_METRICS.values() if source == "eightsleep"}
        assert wanted, "the guard is only meaningful while an eightsleep criterion metric exists"
        assert wanted <= written, f"experiment metrics read fields the writer never stores: {sorted(wanted - written)}"


class TestLatentTimestampFormatSensitivity:
    def test_an_offset_bearing_timestamp_is_not_silently_read_as_utc(self):
        # 23:54 local on a -07:00 offset IS 23.9 in that local frame.
        assert es._hour_of_day("2026-05-09T23:54:00-07:00", -7) == 23.9


# ══════════════════════════════════════════════════════════════════════════════
# 13. Module import surface
# ══════════════════════════════════════════════════════════════════════════════


class TestModuleSurface:
    def test_the_module_imports_from_the_packaged_bundle_path_it_ships_under(self):
        # ADR-146: handlers live under lambdas/ingestion/, shared code under common/.
        mod = importlib.import_module("ingestion.eightsleep_lambda")
        assert mod is es
        assert mod.__file__.endswith(os.path.join("lambdas", "ingestion", "eightsleep_lambda.py"))

    def test_the_lambda_uses_stdlib_urllib_rather_than_a_third_party_http_client(self):
        source = open(os.path.join(LAMBDAS, "ingestion", "eightsleep_lambda.py"), encoding="utf-8").read()
        for banned in ("import requests", "import httpx", "from requests", "from httpx"):
            assert banned not in source
        assert "import urllib.request" in source
