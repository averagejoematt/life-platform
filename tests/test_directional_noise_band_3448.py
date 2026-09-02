"""tests/test_directional_noise_band_3448.py — the ±2% directional band's
behavior under high- and low-variance regimes, made executable (#3448).

`DIRECTIONAL_NOISE_THRESHOLD = 0.02` is the de-facto null for the dominant live
scoring path (every machine spec re-routed to directional evaluation by the
#813 rescue). #3448's decision: the band stays a FIXED editorial choice carrying
the ADR-105 documented-exception stamp (the ±0.15 calibration_verdict form)
rather than being half-derived — deriving per-metric bands means deriving the
EWMA-slope statistic's null distribution per metric, a grading-semantics change
queued behind a real variance baseline (the September 2026 n≥30 read).

These tests make the stamped limitation EXECUTABLE, not merely prose:

  - a high-variance series with NO true trend can clear the band on noise
    (the band leaks noise as a "confirmed" direction);
  - a low-variance series with a REAL steady drift below 2% is absorbed as
    "flat" (the band eats true signal).

If either stops holding — e.g. the band is later derived per-metric — these
tests fail and the registry stamp must be rewritten with the new mechanism.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import coach_prediction_evaluator as ev  # noqa: E402


def _trend_for(values):
    """Run the REAL evaluator path over a synthetic daily series (newest last)
    via a pre-warmed data cache — no DDB, no network."""
    records = [{"date": f"2026-08-{i + 1:02d}", "hrv": v} for i, v in enumerate(values)]
    source = ev.METRIC_SOURCES["hrv"]
    cache = {f"{source}:30": records}
    return ev._get_ewma_trend("hrv", cache, "2026-08-30")


def test_the_evaluator_path_is_the_one_under_test():
    """Control: the pre-warmed cache really reaches _get_ewma_trend's own EWMA
    math (a broken cache key would return (None, None) and vacuously pass the
    regime tests below)."""
    direction, slope = _trend_for([50.0] * 20)
    assert direction == "flat" and abs(slope) < 1e-9


def test_high_variance_noise_clears_the_band():
    """No true trend: the series is the SAME zero-mean alternating ±20%
    oscillation throughout — only the phase differs between the two runs. A
    fixed 2% band reads the recency-weighted wobble as a confirmed direction
    in BOTH directions depending on nothing but the last swing's phase."""
    base = 50.0
    up_phase = [base * (1.2 if i % 2 else 0.8) for i in range(20)]  # ends on a high swing
    down_phase = [base * (0.8 if i % 2 else 1.2) for i in range(20)]  # ends on a low swing
    d_up, s_up = _trend_for(up_phase)
    d_down, s_down = _trend_for(down_phase)
    assert d_up == "up" and s_up > ev.DIRECTIONAL_NOISE_THRESHOLD
    assert d_down == "down" and s_down < -ev.DIRECTIONAL_NOISE_THRESHOLD
    # The same process, phase-flipped, "confirms" both directions — that is
    # noise clearing the band, the stamped high-variance failure mode.


def test_low_variance_real_signal_is_absorbed_as_flat():
    """A genuine, noise-free steady drift whose EWMA slope lands under 2% is
    labeled flat — the stamped low-variance failure mode."""
    values = [50.0 * (1 + 0.0008 * i) for i in range(20)]  # real +1.5% total drift
    direction, slope = _trend_for(values)
    assert 0 < slope < ev.DIRECTIONAL_NOISE_THRESHOLD
    assert direction == "flat"


def test_the_stamp_is_on_the_public_registry():
    from experiment import methods_registry as mr

    entry = mr.REGISTRY["directional_trend_verdict"]
    limitations = entry["limitations"]
    assert "documented exception" in limitations and "ADR-105" in limitations
    assert "#813" in limitations and "1,207" in limitations  # the reach, named
    assert "Re-derive trigger" in limitations
    assert entry["fingerprint"] == entry["recorded_fingerprint"]
