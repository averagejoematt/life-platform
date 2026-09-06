"""tests/prereg_fixture_series.py — the offline stand-in for the pre-registration
seeder's trailing-series read (#3552).

`deploy/seed_genesis_preregistration.build_hypotheses` derives each hypothesis'
`min_effect` from the subject's OWN trailing variance at freeze time, which means a
DynamoDB query. Two test modules build a frozen-artifact fixture through that function
(`test_genesis_preregistration.py`, `test_prereg_hash_stamp.py`), and neither may make a
network call — a suite that reaches AWS is a suite that fails differently on every
machine. This module is the `series_reader` they inject.

The series are deliberately NOISY (real weigh-ins wander; real recovery scores swing 40
points), because a flat fixture would derive `min_effect` 0, which `prereg_effect`
rejects — and a fixture that cannot produce a valid threshold would make both suites red
for a reason that has nothing to do with what they test.
"""

from __future__ import annotations

SERIES = {
    ("withings", "weight_lbs"): [326.2, 325.0, 326.4, 324.1, 325.8, 323.9, 325.1, 322.8, 324.0, 322.1],
    ("whoop", "recovery_score"): [61, 44, 72, 38, 66, 51, 79, 42, 58, 70, 47, 63],
}


def fixture_series(source: str, attribute: str, window_days: int) -> list:
    """[(DATE# sk, value)] in the shape `seeder.trailing_series` returns."""
    values = SERIES[(source, attribute)]
    return [(f"DATE#2026-08-{i + 1:02d}", v) for i, v in enumerate(values)]
