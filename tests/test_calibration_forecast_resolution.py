"""tests/test_calibration_forecast_resolution.py — #1246 regression guard.

The calibration scoreboard queries the shared CALIB# ledger, which holds BOTH
hypothesis-resolution rows (an `outcome` word) and forecast-engine
`forecast_resolution` rows (a `covered` bool + `confidence` float — the 80%
interval's graded binary). Before #1246, `pairs_from_calibration_rows` dropped
every row lacking `outcome`, so all the graded forecast resolutions were
silently invisible and the platform reported n=0 while /api/forecast reported
real coverage over the exact same rows.

This guard is deliberately NON-VACUOUS: against the pre-fix calibration_core it
FAILS (there is no `pairs_from_forecast_resolution_rows`, and the forecast rows
score to n=0); against the fixed module it PASSES. It uses only the pure,
I/O-free calibration_core so no Lambda-layer-only dependency is imported at
collection time.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import calibration_core as cc  # noqa: E402


def _forecast_resolution_row(resolved_date, metric, horizon, covered, confidence=0.80):
    """A real forecast_resolution CALIB# row shape (per
    forecast_engine_lambda.build_forecast_calibration_item): NO `outcome` field —
    the grade signal is `covered` + `confidence`."""
    return {
        "pk": "USER#matthew#SOURCE#calibration",
        "sk": f"CALIB#{resolved_date}#forecast-{metric}-h{horizon}-{resolved_date}",
        "record_type": "forecast_resolution",
        "metric": metric,
        "horizon_days": horizon,
        "confidence": confidence,
        "covered": covered,
        "resolved_at": resolved_date,
        # note: intentionally no "outcome" and no "stated_confidence"
    }


def _graded_ledger(n_covered=19, n_missed=4):
    """23 graded forecast resolutions — the exact live count from the issue
    (coverage 82.6% ≈ 19/23), none carrying an `outcome` field."""
    rows = []
    for i in range(n_covered):
        rows.append(_forecast_resolution_row(f"2026-07-{6 + (i % 11):02d}", f"m{i}", 1, True))
    for i in range(n_missed):
        rows.append(_forecast_resolution_row(f"2026-07-{6 + (i % 11):02d}", f"n{i}", 3, False))
    return rows


class TestForecastResolutionSurfaces:
    def test_old_path_drops_them_this_is_the_bug(self):
        # Documents the root cause: the hypothesis extractor drops every
        # forecast_resolution row because none carry `outcome`.
        rows = _graded_ledger()
        assert cc.pairs_from_calibration_rows(rows) == []

    def test_forecast_rows_are_counted(self):
        # THE FIX: the 23 graded resolutions must surface, not vanish.
        rows = _graded_ledger()
        pairs = cc.pairs_from_forecast_resolution_rows(rows)
        assert len(pairs) == 23
        summary = cc.score_pairs(pairs)
        assert summary["n"] == 23
        assert summary["confirmed"] == 19  # covered → 1
        assert summary["refuted"] == 4  # missed → 0
        assert summary["accuracy_pct"] == 82.6  # matches /api/forecast coverage

    def test_covered_maps_to_binary(self):
        covered = cc.pairs_from_forecast_resolution_rows([_forecast_resolution_row("2026-07-10", "hr", 1, True)])
        missed = cc.pairs_from_forecast_resolution_rows([_forecast_resolution_row("2026-07-10", "hr", 1, False)])
        assert covered == [(0.8, 1)]
        assert missed == [(0.8, 0)]

    def test_stated_confidence_is_the_interval_nominal(self):
        # A 50% interval that covered scores as (0.5, 1), not the 80% default.
        pairs = cc.pairs_from_forecast_resolution_rows([_forecast_resolution_row("2026-07-10", "wt", 7, True, confidence=0.50)])
        assert pairs == [(0.5, 1)]

    def test_unresolved_row_is_not_fabricated(self):
        # A forecast_resolution row still awaiting its actual (no `covered`) must
        # NOT be counted — no invented outcomes.
        pending = _forecast_resolution_row("2026-07-10", "hr", 1, None)
        pending.pop("covered")
        assert cc.pairs_from_forecast_resolution_rows([pending]) == []

    def test_platform_aggregate_folds_both_streams(self):
        # Mirror handle_calibration's aggregation: hypothesis outcome rows + forecast
        # covered rows both fold into the platform total — n must be their sum, and
        # the two extractors never double-count a row.
        hyp_rows = [
            {"record_type": "hypothesis_resolution", "outcome": "confirmed", "stated_confidence": "high"},
            {"record_type": "hypothesis_resolution", "outcome": "refuted", "stated_confidence": "low"},
        ]
        forecast_rows = _graded_ledger()
        ledger = hyp_rows + forecast_rows  # the single CALIB# query returns both

        hyp_pairs = cc.pairs_from_calibration_rows(ledger)
        forecast_pairs = cc.pairs_from_forecast_resolution_rows(ledger)
        assert len(hyp_pairs) == 2  # forecast rows excluded from the hypothesis extractor
        assert len(forecast_pairs) == 23  # hypothesis rows excluded from the forecast extractor

        platform = cc.score_pairs(hyp_pairs + forecast_pairs)
        assert platform["n"] == 25  # 2 hypotheses + 23 forecasts, no longer n=0
