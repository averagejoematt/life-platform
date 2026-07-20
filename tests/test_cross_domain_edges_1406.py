"""tests/test_cross_domain_edges_1406.py — the two #1406 cross-domain edges.

Covers: both edges are wired as lagged pairs; the daily-series assembly extracts
glucose %CV (with the mean/sd fallback), mood valence, and values-lived; and the
values_lived edge is stamped SDT-sensitive so coach consumption stays autonomy-
supportive. No AWS — the compute lambda constructs its boto3 handle lazily and we
drive the pure functions directly.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import weekly_correlation_compute_lambda as wc  # noqa: E402


def _labels():
    return [p[2] for p in wc.CORRELATION_PAIRS]


def test_both_edges_wired_as_lagged_pairs():
    by_label = {p[2]: p for p in wc.CORRELATION_PAIRS}
    values = by_label["values_lived_predicts_next_day_adherence"]
    glucose = by_label["glucose_variability_predicts_next_day_mood"]
    # (metric_a, metric_b, label, lag_days)
    assert values[0] == "values_lived_count" and values[1] == "habit_pct" and values[3] == 1
    assert glucose[0] == "glucose_cv" and glucose[1] == "mood_valence" and glucose[3] == 1


def test_expected_directions_registered():
    assert wc.EXPECTED_DIRECTIONS["values_lived_predicts_next_day_adherence"] == "positive"
    assert wc.EXPECTED_DIRECTIONS["glucose_variability_predicts_next_day_mood"] == "negative"


def test_values_lived_edge_is_sdt_sensitive():
    assert "values_lived_predicts_next_day_adherence" in wc.SDT_SENSITIVE_EDGES
    # The glucose→mood edge is NOT SDT-gated (it is a physiology observation).
    assert "glucose_variability_predicts_next_day_mood" not in wc.SDT_SENSITIVE_EDGES


def _linear_series(n, a_key, b_key, *, slope=1.0):
    """n consecutive days where b[D+1] = slope * a[D] — a clean lag-1 signal."""
    from datetime import date, timedelta

    d0 = date(2026, 5, 1)
    days = [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    series = {d: {} for d in days}
    for i, d in enumerate(days):
        series[d][a_key] = float(i % 5)  # varied condition value
    for i in range(len(days) - 1):
        # b on the NEXT day tracks a on THIS day (lag-1 predictive coupling)
        series[days[i + 1]][b_key] = slope * float(i % 5)
    return series


def test_sdt_stamp_lands_on_computed_result():
    # Build a 20-day series with a strong values_lived→next-day adherence signal.
    series = _linear_series(20, "values_lived_count", "habit_pct", slope=0.2)
    results = wc.compute_correlations(series)
    edge = results["values_lived_predicts_next_day_adherence"]
    assert edge["sdt_sensitive"] is True
    assert edge["coach_framing"] == "autonomy_supportive"
    assert "autonomy-supportive" in edge["framing_note"].lower()
    assert edge["correlation_type"] == "lagged_1d"
    # A non-SDT edge carries no framing stamp.
    other = results["hrv_vs_recovery"]
    assert "sdt_sensitive" not in other


def test_assemble_extracts_cross_domain_metrics(monkeypatch):
    # Stub the source fetch: apple_health carries mood valence + a CGM aggregate
    # WITHOUT a persisted blood_glucose_cv (historical day) so the mean/sd fallback
    # fires; flourishing carries the values-lived row.
    apple_row = {
        "date": "2026-05-02",
        "som_avg_valence": 0.4,
        "blood_glucose_avg": 110.0,
        "blood_glucose_std_dev": 22.0,  # CV = 100*22/110 = 20.0
        "blood_glucose_readings_count": 96,  # real CGM day — the n>=2 fallback guard requires it
    }
    flour_row = {"date": "2026-05-02", "values_lived_count": 3}

    def fake_fetch(source, start, end):
        if source == "apple_health":
            return [apple_row]
        if source == "flourishing":
            return [flour_row]
        return []

    monkeypatch.setattr(wc, "fetch_range", fake_fetch)
    series = wc.assemble_daily_series("2026-05-01", "2026-05-03")
    day = series["2026-05-02"]
    assert day["glucose_cv"] == 20.0  # derived from stored mean/sd (no persisted CV)
    assert day["mood_valence"] == 0.4
    assert day["values_lived_count"] == 3.0


def test_persisted_cv_preferred_over_fallback(monkeypatch):
    apple_row = {
        "date": "2026-05-02",
        "blood_glucose_avg": 110.0,
        "blood_glucose_std_dev": 22.0,  # fallback would give 20.0
        "blood_glucose_readings_count": 96,
        "blood_glucose_cv": 17.5,  # ingestion-persisted intraday CV wins
    }

    def fake_fetch(source, start, end):
        return [apple_row] if source == "apple_health" else []

    monkeypatch.setattr(wc, "fetch_range", fake_fetch)
    series = wc.assemble_daily_series("2026-05-01", "2026-05-03")
    assert series["2026-05-02"]["glucose_cv"] == 17.5


def test_null_edge_still_published_with_stats():
    # An edge with no overlapping data must still appear (null is a finding), with
    # its fdr_significant flag present rather than being dropped.
    series = _linear_series(20, "values_lived_count", "habit_pct", slope=0.2)
    results = wc.compute_correlations(series)
    glucose = results["glucose_variability_predicts_next_day_mood"]  # no glucose/mood data
    assert "fdr_significant" in glucose
    assert glucose["fdr_significant"] is False
    assert glucose["pearson_r"] is None  # honest: insufficient data, not fabricated


def test_single_reading_day_yields_no_fabricated_zero_cv(monkeypatch):
    """A one-reading day stores std_dev=0; the fallback must return None (measured
    absence), never a fabricated CV of 0.0 (ADR-104 — the #1565 review finding)."""
    apple_row = {
        "date": "2026-05-02",
        "blood_glucose_avg": 110.0,
        "blood_glucose_std_dev": 0,
        "blood_glucose_readings_count": 1,
    }

    def fake_fetch(source, start, end):
        return [apple_row] if source == "apple_health" else []

    monkeypatch.setattr(wc, "fetch_range", fake_fetch)
    series = wc.assemble_daily_series("2026-05-01", "2026-05-03")
    assert series["2026-05-02"]["glucose_cv"] is None
