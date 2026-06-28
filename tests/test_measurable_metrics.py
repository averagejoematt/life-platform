"""
tests/test_measurable_metrics.py — the consolidated metric registry can't drift.

MEASURABLE_METRICS (the extractor's allowlist) and METRIC_SOURCES (the evaluator's
source map) used to be hand-synced copies; drift dropped predictions to qualitative
and they never graded (the 504-inconclusive bug). They're now one DERIVED source.
These tests pin that, and that both coach modules import the SAME objects.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

import measurable_metrics as mm  # noqa: E402


def test_allowlist_is_derived_from_sources_cannot_drift():
    assert mm.MEASURABLE_METRICS == frozenset(mm.METRIC_SOURCES)


def test_every_normalizer_target_is_measurable():
    for _needle, target in mm._METRIC_HINT_NORMALIZERS:
        assert target in mm.MEASURABLE_METRICS, f"normalizer maps to non-measurable {target!r}"


def test_normalize_basic_and_prose():
    assert mm.normalize_metric_hint("hrv") == "hrv"
    assert mm.normalize_metric_hint("heart rate variability") == "hrv"
    assert mm.normalize_metric_hint("resting heart rate") == "resting_heart_rate"
    assert mm.normalize_metric_hint("hrv_7day_avg") == "hrv_7day_avg"  # direct allowlist hit
    assert mm.normalize_metric_hint("something unmappable") is None
    assert mm.normalize_metric_hint("") is None


def test_both_coach_modules_share_the_single_source():
    os.environ.setdefault("TABLE_NAME", "life-platform")
    os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    import coach_prediction_evaluator as evaluator
    import coach_state_updater as updater

    # Same registry object backing both — drift is structurally impossible.
    assert updater.MEASURABLE_METRICS is mm.MEASURABLE_METRICS
    assert evaluator.METRIC_SOURCES is mm.METRIC_SOURCES
    assert updater._normalize_metric_hint is mm.normalize_metric_hint
