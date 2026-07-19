"""Experiment instrument gates — the ONE registry of arming thresholds (#1371).

Every "not enough data yet" decision an engine makes (correlation interpretation
floors, hypothesis-generation minimums, coupling floors) is defined HERE, and the
engines import their gates from this module. The site API serves the same values
inside its shaped-empty payloads, so a cold-start zero-state can render the real
trigger ("first correlations at n≥10 — currently 3/10") and can structurally
never drift from the engine that enforces it (ADR-104: computed, never authored).

Adding a threshold to an engine? Define it here and import it there — a test
(tests/test_experiment_gates.py) asserts the engines' module attributes are THIS
module's objects, so a re-hardcoded literal reds CI.
"""

# ── Correlation engine (weekly_correlation_compute_lambda) ────────────────────
# Below this many overlapping days a pair has no r at all (stats_core min_n).
CORRELATION_MIN_N = 10
# Interpretation floors (Henning, R9): r on small n is noisy — a label must be
# backed by sample size, or it downgrades.
CORRELATION_INTERP_N = {
    "strong": 50,  # |r| >= 0.6 AND n >= 50
    "moderate": 30,  # |r| >= 0.4 AND n >= 30
    "weak": 10,  # |r| >= 0.2 AND n >= 10
}

# ── Hypothesis engine (hypothesis_engine_lambda, AI-4/#530) ───────────────────
HYPOTHESIS_MIN_DATA_DAYS = 10  # >= this many complete days before generating
HYPOTHESIS_MIN_METRICS_PER_DAY = 5  # a "complete" day has >= 5 non-null metrics
HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK = 7  # data days since creation before evaluating
HYPOTHESIS_MIN_DAYS_PER_ARM = 5  # each arm needs 5+ days (stats_core bootstrap floor)

# ── Pillar-coupling matrix (site_api_intelligence) ────────────────────────────
COUPLING_MIN_N = 6  # a pair needs >= this many co-present days or it is omitted


def correlation_gates(current_n=None):
    """The correlation zero-state payload block: real thresholds + honest progress.

    current_n is the caller-measured count of complete data days this cycle
    (None when the caller can't measure it — the block still carries the gates).
    """
    return {
        "min_n": CORRELATION_MIN_N,
        "interp_n": dict(CORRELATION_INTERP_N),
        "current_n": current_n,
    }


def hypothesis_gates(current_n=None):
    """The hypothesis zero-state payload block (same shape as correlation_gates)."""
    return {
        "min_data_days": HYPOTHESIS_MIN_DATA_DAYS,
        "min_metrics_per_day": HYPOTHESIS_MIN_METRICS_PER_DAY,
        "min_sample_days_for_check": HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK,
        "current_n": current_n,
    }


# ── Felt-reality calibration (site_api_data.handle_character_calibration, #1409) ─
# Below this many probe-week pairs a pillar has no r at all — the card renders
# the honest "uncalibrated (n=X)" state with the arming trigger instead. The
# floor follows stats_core.pearson_r's noise argument: Fisher CI needs n-3 > 0
# and r on fewer than 5 weekly pairs is coin-flip territory.
FELT_CALIBRATION_MIN_WEEKS = 5
# Below this the CONFIDENCE GRAMMAR downgrades: r renders as a point estimate
# only — never a fabricated band (ADR-105 rule 1).
FELT_CALIBRATION_CI_MIN_WEEKS = 8


def felt_calibration_gates(current_n=None):
    """The calibration-card zero-state payload block (same shape as the others)."""
    return {
        "min_weeks": FELT_CALIBRATION_MIN_WEEKS,
        "ci_min_weeks": FELT_CALIBRATION_CI_MIN_WEEKS,
        "current_n": current_n,
    }
