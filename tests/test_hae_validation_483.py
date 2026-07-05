"""tests/test_hae_validation_483.py — #483 (X-3, D-9, D-3, D-1; epic #459/#461).

The Health Auto Export webhook is the path that actually delivers CGM/BP/steps, yet it
merged everything unvalidated, ignored reported units for non-glucose metrics, classified
CGM by raw count (mislabeling UTC-truncated partial days 'manual'), and had a stray
`break` that read only the first metric in the separate-format BP loop.

These pin the four fixes:
  X-3  ingestion_validator.validate_fields() + the HAE merge gate
  D-9  unit-aware water/weight/distance conversion
  D-3  cgm_source by median inter-reading cadence
  D-1  the separate-format BP loop finds systolic even when it isn't metric[0]
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "lambdas", "ingestion")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("SECRET_NAME", "life-platform/ingestion-keys")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import health_auto_export_lambda as hae  # noqa: E402
from ingestion_validator import validate_fields  # noqa: E402

# ── X-3: validate_fields ──────────────────────────────────────────────────────


def test_validate_fields_skips_whole_item_checks():
    # A merge fragment lacks pk/sk/date — validate_fields must NOT emit required-field
    # errors (that's validate_item's job on full puts).
    r = validate_fields("apple_health", {"steps": 5000})
    assert r.errors == []
    assert not any("Required field" in w for w in r.warnings)


def test_validate_fields_flags_out_of_range_as_warning():
    r = validate_fields("apple_health", {"steps": 500_000})
    assert r.errors == []  # range = warning, not critical
    assert any("steps" in w for w in r.warnings)


def test_validate_fields_critical_on_implausible_glucose():
    r = validate_fields("apple_health", {"blood_glucose_avg": 1200})
    assert r.errors  # 1200 > 600 hard bound
    assert any("blood_glucose_avg" in e for e in r.errors)


def test_validate_fields_accepts_sane_bp():
    r = validate_fields("apple_health", {"bp_systolic": 120, "bp_diastolic": 78})
    assert r.errors == []
    assert r.warnings == []


def test_validate_fields_warns_on_absurd_bp():
    r = validate_fields("apple_health", {"bp_systolic": 400})
    assert any("bp_systolic" in w for w in r.warnings)


def test_merge_gate_blocks_critical_and_passes_clean():
    assert hae._merge_is_valid({"blood_glucose_avg": 110}, "2026-07-01") is True
    assert hae._merge_is_valid({"blood_glucose_avg": 1200}, "2026-07-01") is False
    assert hae._merge_is_valid({}, "2026-07-01") is True  # empty → no-op, allowed


# ── D-3: cgm_source by cadence ────────────────────────────────────────────────


def _readings(start_min_gap, count, start="2026-05-22 15:00:00 -0700"):
    from datetime import datetime, timedelta

    t0 = datetime.strptime(start, "%Y-%m-%d %H:%M:%S %z")
    out = []
    for i in range(count):
        t = t0 + timedelta(minutes=start_min_gap * i)
        out.append({"time": t.strftime("%Y-%m-%d %H:%M:%S %z"), "value": 100})
    return out


def test_cgm_partial_day_is_still_cgm_by_cadence():
    # 17 readings at 5-min cadence — the exact UTC-truncated case the count>=20 heuristic
    # mislabeled 'manual'.
    r = _readings(5, 17)
    assert hae._classify_cgm_source(r, len(r)) == "dexcom_stelo"


def test_fingerstick_cadence_is_manual():
    r = _readings(180, 4)  # readings 3h apart
    assert hae._classify_cgm_source(r, len(r)) == "manual"


def test_cgm_too_few_readings_falls_back_to_count():
    assert hae._classify_cgm_source([{"time": "2026-05-22 15:00:00 -0700", "value": 100}], 25) == "dexcom_stelo"
    assert hae._classify_cgm_source([], 3) == "manual"


# ── D-9: unit awareness ───────────────────────────────────────────────────────


def test_water_ml_factor_by_unit():
    assert hae._water_ml_factor("mL") == 1.0
    assert hae._water_ml_factor("L") == 1000.0
    assert hae._water_ml_factor("fl_oz_us") == 29.5735
    assert hae._water_ml_factor(None) == 29.5735  # historical default
    assert hae._water_ml_factor("qux") == 29.5735  # unknown → default + warn


def test_generic_metrics_respects_ml_water_unit():
    metrics = [
        {"name": "Dietary Water", "units": "mL", "data": [{"date": "2026-07-01 08:00:00 -0700", "qty": 500, "source": "waterminder"}]}
    ]
    daily, _, _ = hae.process_generic_metrics(metrics)
    # mL reported → stored as-is, NOT multiplied by 29.5735
    assert daily["2026-07-01"]["water_intake_ml"] == 500


def test_generic_metrics_defaults_floz_water():
    metrics = [
        {"name": "Dietary Water", "units": "fl_oz_us", "data": [{"date": "2026-07-01 08:00:00 -0700", "qty": 8, "source": "waterminder"}]}
    ]
    daily, _, _ = hae.process_generic_metrics(metrics)
    assert daily["2026-07-01"]["water_intake_ml"] == round(8 * 29.5735)


def test_generic_metrics_converts_kg_weight():
    metrics = [{"name": "Body Mass", "units": "kg", "data": [{"date": "2026-07-01 08:00:00 -0700", "qty": 90, "source": "withings"}]}]
    daily, _, _ = hae.process_generic_metrics(metrics)
    assert daily["2026-07-01"]["weight_lbs"] == round(90 * 2.20462, 2)
