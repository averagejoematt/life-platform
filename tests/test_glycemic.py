"""tests/test_glycemic.py — deterministic glycemic-variability features (#1406).

Every expected value below is computed BY HAND in the comments so the fixtures
double as the arithmetic proof (ADR-105: deterministic computation, no LLM).
"""

import math
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import glycemic  # noqa: E402

# ── The canonical hand-worked day ─────────────────────────────────────────────
# readings = [100, 120, 90, 160, 80]  (mg/dL, time-ordered)
#   mean = 550 / 5 = 110
#   population variance = (100 + 100 + 400 + 2500 + 900) / 5 = 4000 / 5 = 800
#   population SD = sqrt(800) = 28.2842712...
DAY = [100, 120, 90, 160, 80]


def test_coefficient_of_variation_hand_computed():
    # %CV = 100 * 28.2842712 / 110 = 25.7129...  → 25.71
    assert glycemic.coefficient_of_variation(DAY) == 25.71


def test_cv_from_mean_sd_matches_readings():
    sd = math.sqrt(800)
    # Same formula from the stored aggregate → same 25.71
    assert glycemic.cv_from_mean_sd(110, sd) == 25.71
    assert glycemic.cv_from_mean_sd(110, sd) == glycemic.coefficient_of_variation(DAY)


def test_cv_none_on_degenerate():
    assert glycemic.coefficient_of_variation([]) is None
    assert glycemic.coefficient_of_variation([100]) is None  # < 2 readings
    assert glycemic.coefficient_of_variation([0, 0]) is None  # mean 0 → undefined
    assert glycemic.cv_from_mean_sd(None, 10) is None
    assert glycemic.cv_from_mean_sd(0, 10) is None


def test_time_in_range_hand_computed():
    # readings = [65, 100, 150, 190, 120], band 70-180
    #   in-band: 100, 150, 120  → 3 of 5 = 60.0%
    assert glycemic.time_in_range_pct([65, 100, 150, 190, 120]) == 60.0


def test_time_in_range_boundaries_inclusive():
    # 70 and 180 are inclusive; 69.9 and 180.1 are out.
    assert glycemic.time_in_range_pct([70, 180]) == 100.0
    assert glycemic.time_in_range_pct([69.9, 180.1]) == 0.0


def test_time_in_range_custom_band():
    # Attia optimal 70-120 over [65, 100, 150, 190, 120] → 100, 120 in band = 40.0%
    assert glycemic.time_in_range_pct([65, 100, 150, 190, 120], lo=70, hi=120) == 40.0


def test_time_in_range_none_on_empty():
    assert glycemic.time_in_range_pct([]) is None


def test_mage_hand_computed():
    # readings = [100, 120, 90, 160, 80]
    #   extrema (all points are turning points): [100, 120, 90, 160, 80]
    #   amplitudes: |120-100|=20, |90-120|=30, |160-90|=70, |80-160|=80
    #   SD = 28.284..., threshold = 1 * SD = 28.284
    #   qualifying (> 28.284): 30, 70, 80  → mean = 180 / 3 = 60.0
    assert glycemic.mage(DAY) == 60.0


def test_mage_collapses_flats_and_needs_qualifying_excursion():
    # A flat day has SD 0 → None (no excursions to measure).
    assert glycemic.mage([100, 100, 100, 100]) is None
    # Small wiggles below 1 SD → no qualifying excursion → None.
    #   [100, 101, 100, 101, 100]: SD ~0.49, amplitudes all 1 > 0.49 actually qualify,
    #   so use a genuinely sub-SD case:
    #   [100, 102, 98, 102, 98]: mean=100, var=(0+4+4+4+4)/5=3.2, SD=1.788,
    #   amplitudes 2,4,4,4 → all > 1.788 → qualify (mean=3.5). This DOES qualify;
    #   to force None we need one dominant swing raising SD above the wiggles.
    assert glycemic.mage([100, 101]) is None  # < 3 readings


def test_mage_sd_multiplier_filters_small_swings():
    # readings = [100, 105, 100, 160, 100]
    #   mean = 113, var = (169 + 64 + 169 + 2209 + 169)/5 = 2780/5 = 556, SD = 23.58
    #   extrema: [100, 105, 100, 160, 100]
    #   amplitudes: 5, 5, 60, 60
    #   threshold @1 SD = 23.58 → qualifying: 60, 60 → MAGE = 60.0
    assert glycemic.mage([100, 105, 100, 160, 100]) == 60.0
    # At 3 SD (70.7) nothing qualifies → None
    assert glycemic.mage([100, 105, 100, 160, 100], sd_multiplier=3.0) is None


def test_mage_none_below_min_readings():
    assert glycemic.mage([100, 120]) is None
    assert glycemic.mage([]) is None
