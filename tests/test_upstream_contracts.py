"""
tests/test_upstream_contracts.py — ER-02 upstream-API contract tests.

The transform() unit tests (tests/test_ingestion_transforms.py) pin OUR logic
against a fixed input: payload X → DDB shape Y. They do NOT notice when the VENDOR
changes payload X (a field rename, a renest, a retype). That drift corrupts data
silently and is only caught downstream, if ever — the literal mechanism of the next
44-day-class incident.

These contract tests assert the *shape contract* each transform depends on, against
committed, scrubbed fixtures under tests/fixtures/upstream/{source}/{endpoint}.json:

  1. test_fixture_shape_contract       — every key-path the transform reads is
                                          present and the right type (catches a
                                          vendor rename / renest / retype).
  2. test_fixture_roundtrips_transform — feeds the fixture through the REAL
                                          extractor and asserts the expected output
                                          fields appear. Ties the fixture to live
                                          code, so drift on EITHER side fails.
  3. test_fixtures_have_no_secrets     — guards the scrub invariant in-repo: no
                                          committed fixture may carry a token/PII.

Fully offline — asserts committed fixtures, makes zero live AWS/vendor calls, so CI
can gate on it. The LIVE refresh path (re-pull + scrub + diff) is
deploy/refresh_upstream_fixtures.py, which Matthew runs in his terminal with creds.

Priority sources per the ER-02 spec: Whoop, Withings, Apple Health/HAE.
"""

import json
import os
import re
import sys
from decimal import Decimal

import pytest

# Ingestion modules build an IngestionConfig at import time (reads env). Set dummies.
for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion.garmin_lambda import transform as garmin_transform  # noqa: E402
from ingestion.health_auto_export_lambda import process_blood_glucose  # noqa: E402
from ingestion.strava_lambda import _normalize as strava_normalize  # noqa: E402
from ingestion.whoop_lambda import (  # noqa: E402
    _extract_cycle,
    _extract_recovery,
    _extract_sleep,
    _extract_workout,
)
from ingestion.withings_lambda import _parse_measurements  # noqa: E402

# Shared scrubber/secret-scanner — single source of truth, also used by the
# live-refresh tool. (deploy/ is not on the default path; add it.)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
from refresh_upstream_fixtures import scan_for_secrets  # noqa: E402

FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "upstream")


# ── Path resolver: "records[0].score.recovery_score" ─────────────────────────
_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_MISSING = object()


def _resolve(obj, path):
    cur = obj
    for name, idx in _TOKEN.findall(path):
        if name:
            if not isinstance(cur, dict) or name not in cur:
                return _MISSING
            cur = cur[name]
        else:
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                return _MISSING
            cur = cur[i]
    return cur


def _type_ok(value, label):
    if label == "list":
        return isinstance(value, list)
    if label == "dict":
        return isinstance(value, dict)
    if label == "str":
        return isinstance(value, str)
    if label == "bool":
        return isinstance(value, bool)
    if label == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise AssertionError(f"unknown type label {label!r}")


def _num(v):
    return float(v) if isinstance(v, Decimal) else v


# ── Contract registry ─────────────────────────────────────────────────────────
# Each contract: required key-paths + types the transform reads, plus a roundtrip
# extractor (fixture dict → normalized field dict) and the fields it must produce.


class Contract:
    def __init__(self, source, endpoint, required, extractor, expect):
        self.source = source
        self.endpoint = endpoint
        self.required = required  # list[(path, type_label)]
        self.extractor = extractor  # fixture -> normalized dict (None = shape-only)
        self.expect = expect  # output keys that must be present
        self.id = f"{source}/{endpoint}"


def _hae_glucose_agg(fx):
    metric = fx["data"]["metrics"][0]
    daily_agg, _readings = process_blood_glucose(metric["data"], metric["units"])
    return next(iter(daily_agg.values()))  # first day's aggregate


CONTRACTS = [
    Contract(
        "whoop",
        "recovery",
        [
            ("records", "list"),
            ("records[0].score_state", "str"),
            ("records[0].score", "dict"),
            ("records[0].score.recovery_score", "number"),
            ("records[0].score.resting_heart_rate", "number"),
            ("records[0].score.hrv_rmssd_milli", "number"),
        ],
        _extract_recovery,
        ["recovery_score", "resting_heart_rate", "hrv", "spo2_percentage", "skin_temp_celsius"],
    ),
    Contract(
        "whoop",
        "sleep",
        [
            ("records", "list"),
            ("records[0].nap", "bool"),
            ("records[0].score_state", "str"),
            ("records[0].start", "str"),
            ("records[0].end", "str"),
            ("records[0].score.stage_summary", "dict"),
            ("records[0].score.stage_summary.total_in_bed_time_milli", "number"),
            ("records[0].score.stage_summary.total_awake_time_milli", "number"),
            ("records[0].score.sleep_performance_percentage", "number"),
        ],
        _extract_sleep,
        ["sleep_duration_hours", "rem_sleep_hours", "slow_wave_sleep_hours", "sleep_performance_percentage", "nap_count"],
    ),
    Contract(
        "whoop",
        "cycle",
        [
            ("records[0].score_state", "str"),
            ("records[0].score.strain", "number"),
            ("records[0].score.kilojoule", "number"),
            ("records[0].score.average_heart_rate", "number"),
            ("records[0].score.max_heart_rate", "number"),
        ],
        _extract_cycle,
        ["strain", "kilojoule", "average_heart_rate", "max_heart_rate"],
    ),
    Contract(
        "whoop",
        "workout",
        [
            ("records[0].sport_id", "number"),
            ("records[0].score_state", "str"),
            ("records[0].start", "str"),
            ("records[0].end", "str"),
            ("records[0].score.strain", "number"),
        ],
        lambda fx: _extract_workout(fx["records"][0]),
        ["sport_id", "sport_name", "strain", "average_heart_rate", "max_heart_rate"],
    ),
    Contract(
        "withings",
        "measures",
        [
            ("measuregrps", "list"),
            ("measuregrps[0].date", "number"),
            ("measuregrps[0].measures", "list"),
            ("measuregrps[0].measures[0].type", "number"),
            ("measuregrps[0].measures[0].value", "number"),
            ("measuregrps[0].measures[0].unit", "number"),
        ],
        _parse_measurements,
        ["weight_kg", "weight_lbs", "fat_free_mass_kg", "fat_mass_kg", "fat_ratio_pct", "measurement_timestamp"],
    ),
    Contract(
        "hae",
        "blood_glucose",
        [
            ("data.metrics", "list"),
            ("data.metrics[0].name", "str"),
            ("data.metrics[0].units", "str"),
            ("data.metrics[0].data", "list"),
            ("data.metrics[0].data[0].date", "str"),
            ("data.metrics[0].data[0].qty", "number"),
        ],
        _hae_glucose_agg,
        ["blood_glucose_avg", "blood_glucose_min", "blood_glucose_max", "blood_glucose_readings_count", "cgm_source"],
    ),
    Contract(
        "hae",
        "blood_pressure",
        [
            ("data.metrics", "list"),
            ("data.metrics[0].name", "str"),
            ("data.metrics[0].data", "list"),
            ("data.metrics[0].data[0].date", "str"),
            ("data.metrics[0].data[0].systolic", "number"),
            ("data.metrics[0].data[0].diastolic", "number"),
        ],
        None,  # BP processing is inline in the handler — shape-only contract
        [],
    ),
    Contract(
        "strava",
        "activity",
        [
            ("id", "number"),
            ("name", "str"),
            ("type", "str"),
            ("distance", "number"),
            ("total_elevation_gain", "number"),
            ("average_heartrate", "number"),
            ("has_heartrate", "bool"),
            ("map.summary_polyline", "str"),
        ],
        strava_normalize,
        ["strava_id", "name", "distance_miles", "total_elevation_gain_feet", "average_heartrate", "summary_polyline"],
    ),
    Contract(
        "garmin",
        "daily",
        [
            ("steps", "number"),
            ("resting_heart_rate", "number"),
            ("body_battery_high", "number"),
        ],
        lambda fx: garmin_transform(fx, "2026-06-08")[0],
        ["steps", "resting_heart_rate", "body_battery_high"],
    ),
]

_IDS = [c.id for c in CONTRACTS]


def _load(contract):
    with open(os.path.join(FIXTURE_ROOT, contract.source, f"{contract.endpoint}.json")) as fh:
        return json.load(fh)


@pytest.mark.parametrize("contract", CONTRACTS, ids=_IDS)
def test_fixture_shape_contract(contract):
    """Every key-path the transform reads is present and the right type."""
    fx = _load(contract)
    for path, label in contract.required:
        value = _resolve(fx, path)
        assert value is not _MISSING, f"{contract.id}: vendor drift — missing key-path '{path}'"
        assert _type_ok(value, label), f"{contract.id}: '{path}' should be {label}, got {type(value).__name__}"


@pytest.mark.parametrize("contract", [c for c in CONTRACTS if c.extractor], ids=[c.id for c in CONTRACTS if c.extractor])
def test_fixture_roundtrips_transform(contract):
    """The real extractor, run on the fixture, produces every expected field."""
    out = contract.extractor(_load(contract))
    assert isinstance(out, dict) and out, f"{contract.id}: extractor returned empty — fixture no longer satisfies the transform"
    for key in contract.expect:
        assert key in out, f"{contract.id}: extractor dropped '{key}' — fixture drifted from what the transform reads"
        assert out[key] is not None, f"{contract.id}: '{key}' came back None"


def test_fixtures_have_no_secrets():
    """No committed fixture may carry a token / bearer / JWT / email (scrub guarantee)."""
    scanned = 0
    for source in sorted(os.listdir(FIXTURE_ROOT)):
        sdir = os.path.join(FIXTURE_ROOT, source)
        if not os.path.isdir(sdir):
            continue
        for fname in sorted(os.listdir(sdir)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(sdir, fname)) as fh:
                payload = json.load(fh)
            leaks = scan_for_secrets(payload)
            assert leaks == [], f"{source}/{fname}: fixture carries secrets/PII: {leaks}"
            scanned += 1
    assert scanned >= len(CONTRACTS), f"expected ≥{len(CONTRACTS)} fixtures scanned, saw {scanned}"


def test_every_contract_has_a_committed_fixture():
    """Each active source/endpoint in the registry has a fixture file on disk."""
    for c in CONTRACTS:
        p = os.path.join(FIXTURE_ROOT, c.source, f"{c.endpoint}.json")
        assert os.path.exists(p), f"missing fixture for {c.id} at {p}"
