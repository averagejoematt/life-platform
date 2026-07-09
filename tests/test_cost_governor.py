"""tests/test_cost_governor.py — tier decision logic (N-08).

Pure unit tests of the projection→tier policy: the projection may escalate at
most ONE tier above what ACTUAL month-to-date spend justifies (none at all in
the early-month window). No AWS calls.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest


@pytest.fixture(scope="module")
def gov():
    return importlib.import_module("operational.cost_governor_lambda")


@pytest.fixture(autouse=True)
def _pin_normal_thresholds(gov, monkeypatch):
    """Pin the production tier boundaries regardless of any temporary, calendar-
    based headroom (e.g. the June-2026 override in _active_thresholds, #169) so
    these tests validate the boundary POLICY deterministically year-round — not
    whichever month the suite happens to run in. The override itself is config,
    exercised live; here we lock the mapping the assertions below are written for.
    Without this the whole module false-fails during the override window and
    silently passes again afterward — exactly the kind of date-flaky test the
    black gate was masking until 2026-06-24.
    """
    monkeypatch.setattr(gov, "_active_thresholds", lambda: gov._TIER_THRESHOLDS)


# ── _tier_for: threshold mapping ─────────────────────────────────────────────
# The dollar thresholds (55/65/73) are calibrated against the ORIGINAL $75
# reference ceiling (_THRESHOLD_REFERENCE_CEILING) and scale as fixed fractions
# (≈73%/87%/97%) of whatever ceiling is in effect. These boundary tests pin the
# reference mapping (explicit ceiling=75.0); the $85-base default (ADR-133
# amendment 2026-07-08) is pinned separately below.


@pytest.mark.parametrize(
    "projected,expected",
    [
        (0, 0),
        (54.99, 0),
        (55, 1),
        (64.99, 1),
        (65, 2),
        (72.99, 2),
        (73, 3),
        (500, 3),
    ],
)
def test_tier_thresholds_at_reference_ceiling(gov, projected, expected):
    assert gov._tier_for(projected, ceiling=75.0) == expected


@pytest.mark.parametrize(
    "projected,expected",
    [
        (0, 0),
        (62.0, 0),  # under 55 × 85/75 ≈ 62.33
        (62.34, 1),
        (73.0, 1),  # under 65 × 85/75 ≈ 73.67
        (73.67, 2),
        (82.0, 2),  # under 73 × 85/75 ≈ 82.73
        (82.74, 3),
        (500, 3),
    ],
)
def test_tier_thresholds_at_85_base_default(gov, projected, expected):
    """The current $85 base (ADR-133 amendment) is the DEFAULT ceiling — the
    bands re-derive proportionally: boundaries $62.33 / $73.67 / $82.73."""
    assert gov.MONTHLY_CEILING == 85.0
    assert gov._tier_for(projected) == expected


# ── _decide_tier: actual-spend cap ───────────────────────────────────────────
# The incident tests below document $75-era events, so they pin the POLICY at
# the ceiling they happened under (explicit ceiling=75.0); the policy itself
# is ceiling-independent.


def test_n08_regression_projection_overshoot_capped_to_tier1(gov):
    """The 2026-06-05/06 incident: $28.86 actual, $157 projected, day 6.
    Old behavior: tier 3 (all AI off). New: tier 1 (heaviest spender paused)."""
    assert gov._decide_tier(projected=157.0, mtd=28.86, elapsed_days=5.8, ceiling=75.0) == 1


def test_early_month_projection_fully_ignored(gov):
    """Day 2, front-loaded fixed charges: $15 actual → $233 projected.
    Inside EARLY_MONTH_DAYS the projection gets no benefit of the doubt."""
    assert gov._decide_tier(projected=233.0, mtd=15.56, elapsed_days=1.5, ceiling=75.0) == 0


def test_genuine_runaway_unlocks_higher_tiers(gov):
    """Real dollars unlock the harsh tiers: actual already past tier 2 ($65),
    projection past tier 3 → escalate the full way."""
    assert gov._decide_tier(projected=120.0, mtd=66.0, elapsed_days=20.0, ceiling=75.0) == 3


def test_actual_at_ceiling_is_tier3_regardless_of_projection(gov):
    assert gov._decide_tier(projected=74.0, mtd=74.0, elapsed_days=28.0, ceiling=75.0) == 3


def test_projection_below_actual_never_inflated_by_cap(gov):
    """min(), not max(): a calm projection with high-ish actual stays at the
    projection tier (late month, spend tapering)."""
    assert gov._decide_tier(projected=54.0, mtd=56.0, elapsed_days=29.0, ceiling=75.0) == 0


def test_post_pause_stuck_projection_de_escalates(gov):
    """Failure mode 2: AI paused, projection frozen high for weeks. Tier must
    track actual spend (+1), not the stale projection — so it recovers."""
    # mid-month, actual well under tier 1, projection still screaming tier 3
    assert gov._decide_tier(projected=150.0, mtd=40.0, elapsed_days=12.0, ceiling=75.0) == 1


def test_all_quiet_is_tier0(gov):
    assert gov._decide_tier(projected=30.0, mtd=10.0, elapsed_days=10.0) == 0


def test_2026_07_08_incident_still_tier1_at_85_base(gov):
    """The incident that motivated the $85 base raise (ADR-133 amendment):
    $79.27 projected from internal spend creep, low actual mtd, day 8. HONEST
    expectation: the raise does NOT clear tier 1 — $79.27 still exceeds the
    tier-2 boundary ($73.67 at $85), capped to 1 by actual spend. The bands
    degrade BEFORE the ceiling by design; the tier clears when the trailing
    burn rate decays, not when the ceiling moves."""
    assert gov._decide_tier(projected=79.27, mtd=25.0, elapsed_days=7.6) == 1
    # It would take a projection under $62.33 (73% of $85) to reach tier 0.
    assert gov._decide_tier(projected=62.0, mtd=25.0, elapsed_days=7.6) == 0


# ── _project_month_end: BOTH AI + non-AI run-rates use a TRAILING window ────────


def test_projection_tracks_trailing_rate_not_lumpy_mtd(gov):
    """2026-06-15 incident: early-month one-time AI (reset + podcast) inflated the
    MTD total, but the trailing-7d AI rate is low. The projection must track the
    recent rate — the old MTD active-day average produced ~$115 and a needless
    tier-2 website-AI pause against a real ~$60 run-rate."""
    # mtd $57, trailing 7d: non_ai $7.5 + ai $6.72 → ~$2.03/day.
    projected = gov._project_month_end(mtd=57.0, elapsed_days=15.0, days_in_month=30, non_ai_recent=7.5, ai_recent=6.72, trailing_days=7.0)
    # ~$2.03/day × 15 remaining → ~$87 (honest), not ~$115.
    assert 80 < projected < 95


def test_projection_nonai_lump_not_extrapolated(gov):
    """Day-1 monthly fixed charges (Secrets/Route53/KMS) inflate MTD non-AI but
    are already banked in mtd. The trailing window has cleared the lump, so the
    new projection must come in BELOW what the old MTD-linear non-AI method gave."""
    # Mid-month: mtd $40 (non-AI MTD $25, lump-inflated → $1.67/day; the real
    # variable rate is ~$0.8/day = $5.6 over 7d). AI ~$1/day ($7 over 7d).
    new = gov._project_month_end(mtd=40.0, elapsed_days=15.0, days_in_month=30, non_ai_recent=5.6, ai_recent=7.0, trailing_days=7.0)
    # Old method: non-AI extrapolated from the lump-inflated MTD average.
    old = 40.0 + (25.0 / 15.0 + 7.0 / 7.0) * 15.0  # ≈ $80
    assert new < old - 10  # ~$67 vs ~$80 — the lump no longer re-projects


def test_projection_zero_remaining_equals_mtd(gov):
    """Last day of the month: nothing remaining → projection == already-spent."""
    assert (
        gov._project_month_end(mtd=62.0, elapsed_days=30.0, days_in_month=30, non_ai_recent=4.0, ai_recent=7.0, trailing_days=7.0) == 62.0
    )


def test_projection_short_trailing_window_is_finite(gov):
    """Early month the trailing window is sub-7d; the 0.5d floor must prevent a
    divide-by-tiny blow-up."""
    p = gov._project_month_end(mtd=10.0, elapsed_days=1.5, days_in_month=30, non_ai_recent=8.0, ai_recent=2.0, trailing_days=1.5)
    assert 0 < p < 1000


# ── _non_ai_daily_series: Bedrock must NOT leak into the non-AI total ─────────
# Regression for the 2026-06-17 double-count: Bedrock is billed under per-model
# service names ("Claude Haiku 4.5 (Amazon Bedrock Edition)"), so the old
# Not==["Amazon Bedrock"] filter matched nothing and Bedrock got counted twice
# (once in non-AI from CE, once in the token-based AI estimate).


class _FakeCE:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def get_cost_and_usage(self, **kwargs):
        self.last_kwargs = kwargs
        return self._payload


def test_non_ai_series_excludes_bedrock_edition_services(gov, monkeypatch):
    payload = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-06-10", "End": "2026-06-11"},
                "Groups": [
                    {"Keys": ["Claude Haiku 4.5 (Amazon Bedrock Edition)"], "Metrics": {"UnblendedCost": {"Amount": "14.50"}}},
                    {"Keys": ["Claude Sonnet 4.6 (Amazon Bedrock Edition)"], "Metrics": {"UnblendedCost": {"Amount": "10.11"}}},
                    {"Keys": ["AmazonCloudWatch"], "Metrics": {"UnblendedCost": {"Amount": "5.68"}}},
                ],
            }
        ]
    }
    fake = _FakeCE(payload)
    monkeypatch.setattr(gov, "_ce", fake)
    series = gov._non_ai_daily_series(datetime(2026, 6, 1, tzinfo=timezone.utc), datetime(2026, 6, 18, tzinfo=timezone.utc))
    # Only the non-Bedrock service counts → 5.68, NOT 30.29 (which double-counts AI).
    assert series == [("2026-06-10", 5.68)]
    # No brittle exact-name CE filter anymore; we group by SERVICE and drop Bedrock in code.
    assert "Filter" not in fake.last_kwargs
    assert fake.last_kwargs.get("GroupBy")


# ── ADR-133 (#739): surge-mode ceiling — rule + isolation from spend creep ────
# The $85 base ceiling (ADR-133 amendment) floats to $100 when trailing 7-day
# unique visitors (traffic_digest_lambda's UniqueVisitors7d CloudWatch metric)
# cross SURGE_UNIQUES_THRESHOLD (900). Surge is a pure function of reader
# traffic — it must never be triggerable by spend alone.


@pytest.mark.parametrize(
    "recent_uniques,expected_ceiling,expected_surge",
    [
        (0, 85.0, False),
        (899, 85.0, False),  # boundary: one under the threshold
        (900, 100.0, True),  # boundary: exactly at the threshold — crosses
        (901, 100.0, True),
        (5000, 100.0, True),  # a genuine viral spike
        (None, 85.0, False),  # no signal yet (metric never emitted) → fails closed to the BASE
    ],
)
def test_effective_ceiling_rule(gov, recent_uniques, expected_ceiling, expected_surge):
    ceiling, surge_active = gov._effective_ceiling(recent_uniques)
    assert ceiling == expected_ceiling
    assert surge_active is expected_surge


def test_surge_engages_only_on_traffic_never_on_spend(gov):
    """Constraint #3 (#739 scope): the ceiling stays at the $85 base when
    uniques are below threshold REGARDLESS of projection. A heavy, over-budget
    spend projection with organic (sub-threshold) traffic must not float it."""
    ceiling, surge_active = gov._effective_ceiling(recent_uniques=288)  # real recent baseline
    assert ceiling == 85.0
    assert surge_active is False
    # Feed that ceiling into _decide_tier with a way-over-budget projection —
    # the tier still escalates (spend enforcement is untouched), but the
    # CEILING itself never moved off the base because of the projection.
    tier = gov._decide_tier(projected=500.0, mtd=200.0, elapsed_days=20.0, ceiling=ceiling)
    assert tier == 3  # spend enforcement still works — this isn't a bypass
    assert ceiling == 85.0  # the ceiling that produced it was never surged


def test_tier_for_scales_proportionally_with_surge_ceiling(gov):
    """The tier BANDS (≈73%/87%/97% of ceiling) stay proportionally identical
    under the surge ceiling — only the dollar amounts that trip them move.
    Thresholds scale from the $75 REFERENCE calibration, not from the base."""
    ratio = 100.0 / 75.0  # ceiling / _THRESHOLD_REFERENCE_CEILING
    assert gov._tier_for(55 * ratio - 0.01, ceiling=100.0) == 0
    assert gov._tier_for(55 * ratio, ceiling=100.0) == 1
    assert gov._tier_for(65 * ratio, ceiling=100.0) == 2
    assert gov._tier_for(73 * ratio, ceiling=100.0) == 3
    # A projection over the hard-stop line at the $85 base gets ROOM once surge
    # mode is active — this is the entire point of the story: reader-driven AI
    # spend that would have hard-stopped now degrades gently instead.
    assert gov._tier_for(83.0) == 3  # $85 base: $83 is past the $82.73 hard stop
    assert gov._tier_for(83.0, ceiling=100.0) == 1  # $100 surge: same $83 is tier 1


def test_decide_tier_default_ceiling_is_the_base(gov):
    """The runtime-resolved default (`ceiling=None` → MONTHLY_CEILING) makes
    every pre-existing 3-arg call site behave exactly like an explicit
    ceiling=$85 call."""
    assert gov._decide_tier(projected=157.0, mtd=28.86, elapsed_days=5.8) == gov._decide_tier(
        projected=157.0, mtd=28.86, elapsed_days=5.8, ceiling=85.0
    )


# ── _recent_unique_visitors: reads the traffic digest's CloudWatch metric ────


class _FakeCW:
    def __init__(self, datapoints):
        self._datapoints = datapoints

    def get_metric_statistics(self, **kwargs):
        assert kwargs["Namespace"] == "LifePlatform/Traffic"
        assert kwargs["MetricName"] == "UniqueVisitors7d"
        return {"Datapoints": self._datapoints}


def test_recent_unique_visitors_returns_latest_datapoint(gov, monkeypatch):
    points = [
        {"Timestamp": datetime(2026, 6, 29, tzinfo=timezone.utc), "Maximum": 165},
        {"Timestamp": datetime(2026, 7, 6, tzinfo=timezone.utc), "Maximum": 288},
    ]
    monkeypatch.setattr(gov, "_cw", _FakeCW(points))
    assert gov._recent_unique_visitors(datetime(2026, 7, 8, tzinfo=timezone.utc)) == 288


def test_recent_unique_visitors_no_datapoints_returns_none(gov, monkeypatch):
    monkeypatch.setattr(gov, "_cw", _FakeCW([]))
    assert gov._recent_unique_visitors(datetime(2026, 7, 8, tzinfo=timezone.utc)) is None


def test_recent_unique_visitors_read_failure_returns_none(gov, monkeypatch):
    class _BrokenCW:
        def get_metric_statistics(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(gov, "_cw", _BrokenCW())
    assert gov._recent_unique_visitors(datetime(2026, 7, 8, tzinfo=timezone.utc)) is None
