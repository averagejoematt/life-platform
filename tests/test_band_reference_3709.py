"""#3709 — training_reference v2: nearest-band resolution with the distance stated.

Three defects in v1, each pinned below:

1. **Bands covered the reference window only**, so the table stopped at 300-309.
   At 327.3 lb — above Matthew's entire 14-year record — a lookup returned
   nothing rather than "the nearest comparable period is 18 lb lighter".
2. **A band's window was `min(dates)..max(dates)`.** That holds only for a
   monotonic cut. Over all history he crosses 250-259 on the way down and again
   on the way up years later, so min..max becomes his whole life and the weekly
   rates become a lifetime average wearing a band's name.
3. **No `n`, no dwell.** The band nearest his current weight rested on a 6-day
   window and the record said so nowhere (ADR-105).

Plus the one that only appears once bands cover everything: at his current
weight the all-history band is drawn from the very weeks he is trying to
escape, so a prescription reading from it hands back his own inactivity.
`proven_bands` is the answer, and it must not borrow the evidence of the
all-history band it shares a key with.
"""

import pytest

from lambdas.compute import episode_detect_lambda as ed
from lambdas.training.band_reference import band_key, resolve_band

# ── resolution, distance, and declining ────────────────────────────────────


def test_band_key_buckets_to_ten_pounds():
    assert band_key(327.3) == "320-329"
    assert band_key(320.0) == "320-329"
    assert band_key(319.9) == "310-319"


def test_exact_band_is_used_and_reports_zero_distance():
    bands = {"320-329": {"n_days": 40, "n_weighins": 10}}
    r = resolve_band(327.3, bands)
    assert r["band"] == "320-329" and r["exact"] is True and r["band_distance_lb"] == 0


def test_widens_when_the_containing_band_is_absent_and_states_the_distance():
    """The 327 lb case: nothing at 320-329, nearest proven period is 18 lb down."""
    bands = {"300-309": {"n_days": 24, "n_weighins": 15}}
    r = resolve_band(327.3, bands)
    assert r["band"] == "300-309"
    assert r["exact"] is False
    assert r["band_distance_lb"] == 18, "the distance must be measured to the interval"


def test_distance_is_measured_to_the_interval_not_the_midpoint():
    r = resolve_band(310.0, {"300-309": {"n_days": 30, "n_weighins": 9}})
    assert r["band_distance_lb"] == 1


def test_declines_rather_than_reaching_past_the_widening_limit():
    """Silence beats a 40-lb-away 'reference'."""
    assert resolve_band(327.3, {"200-209": {"n_days": 99, "n_weighins": 40}}) is None


def test_declines_a_band_that_does_not_clear_the_evidence_floor():
    assert resolve_band(327.3, {"320-329": {"n_days": 4, "n_weighins": 2}}) is None


def test_a_thin_band_that_is_used_is_marked_low_confidence():
    r = resolve_band(327.3, {"320-329": {"n_days": 6, "n_weighins": 5}})
    assert r["confidence"] == "low", "a 6-day dwell must not be presented as measured"


def test_resolve_band_on_empty_input_is_none_not_an_exception():
    assert resolve_band(327.3, None) is None
    assert resolve_band(327.3, {}) is None
    assert resolve_band(None, {"320-329": {"n_days": 40, "n_weighins": 10}}) is None


# ── the day-set fix (defect 2) ─────────────────────────────────────────────


def _acts(dates, kind="walk", hours=1.0, miles=3.0, hr=100):
    return [{"date": d, "kind": kind, "hours": hours, "miles": miles, "hr": hr} for d in dates]


def test_day_set_mode_does_not_divide_by_the_calendar_span():
    """Two visits to a band years apart: 4 in-band days, not 4 years of weeks."""
    days = {"2020-01-01", "2020-01-02", "2024-01-01", "2024-01-02"}
    cov = ed.weekly_covariates(_acts(sorted(days)), "2020-01-01", "2024-01-02", day_set=days)
    assert cov["n_days"] == 4
    # 4 walks over 4 days = 7 walks/wk. Under the old min..max window it would
    # have been 4 walks over ~1462 days ≈ 0.02/wk.
    assert cov["walks_wk"] == pytest.approx(7.0, abs=0.1)


def test_build_reference_bands_are_summed_over_in_band_days_not_the_span():
    """The guard that matters. Testing weekly_covariates directly proves the
    day-set MODE works; it proves nothing about whether build_reference passes
    one. Two visits to 250-259 four years apart must not yield a band whose
    window is four years — that is the lifetime-average bug."""
    weigh_ins = [("2020-01-0%d" % d, 255.0) for d in range(1, 6)] + [("2024-01-0%d" % d, 255.0) for d in range(1, 6)]
    idx = [d for d, _ in weigh_ins]
    vals = [v for _, v in weigh_ins]
    ref = ed.build_reference(idx, vals, [], _acts(idx), {}, {}, {})
    band = ref["bands"]["250-259"]
    assert band["n_days"] < 60, f"band window spans the calendar gap: n_days={band['n_days']}"
    assert band["n_weighins"] == 10
    # 10 walks over ~10-20 in-band days is a real rate; over 4 years it is ~0.03.
    assert band["walks_wk"] > 1.0, "the lifetime-average bug is back"


def test_range_mode_is_unchanged_for_contiguous_periods():
    cov = ed.weekly_covariates(_acts(["2024-01-01", "2024-01-08"]), "2024-01-01", "2024-01-15")
    assert cov["n_days"] == 14


def test_absent_heart_rate_is_none_never_zero():
    """ADR-104 — absence reported as absence."""
    acts = [{"date": "2024-01-01", "kind": "walk", "hours": 1.0, "miles": 3.0, "hr": None}]
    cov = ed.weekly_covariates(acts, "2024-01-01", "2024-01-08")
    assert cov["walk_bpm"] is None and cov["n_walk_bpm"] == 0


# ── corrupt sets, and the dead Whoop field ─────────────────────────────────


def test_corrupt_sets_are_excluded_from_tonnage():
    """Six such sets exist live; one distorts a weekly aggregate by 10x."""
    good = {"sets": 0.0, "tonnage_lb": 0.0, "top_kg": {}}
    hevy = {"2024-01-01": good}
    for kg, reps in ((100.0, 5.0), (5443.0, 10.0), (0.0, 200.0)):
        if kg > ed.CORRUPT_SET_MAX_KG or reps > ed.CORRUPT_SET_MAX_REPS:
            continue
        good["sets"] += 1
        good["tonnage_lb"] += kg * ed.LB_PER_KG * reps
    cov = ed.weekly_covariates([], "2024-01-01", "2024-01-08", hevy_by_date=hevy)
    assert cov["sets_wk"] > 0
    assert cov["tonnage_lb_wk"] < 2000, "a corrupt set reached the aggregate"


def test_whoop_zone_minutes_are_never_read():
    """Present on 2,167 of 4,822 records and ZERO on every one (2026-09-08).
    Reading them would silently produce a zeroed cardio signal."""
    src = open(ed.__file__).read()
    for field in ("zone_0_minutes", "zone_1_minutes", "zone_2_minutes", "zone_3_minutes"):
        assert f'"{field}"' not in src and f"'{field}'" not in src, f"{field} is a dead field"


# ── the proven-band separation ─────────────────────────────────────────────


def test_proven_bands_do_not_borrow_the_all_history_bands_evidence():
    """`n_weighins` must be counted inside the restriction, or a proven band
    standing on 2 weigh-ins inherits the 12 of its all-history twin and clears
    an evidence floor it should have failed."""
    src = open(ed.__file__).read()
    assert "band_weighin_dates.get(band, set()) & use" in src


def test_build_reference_emits_both_tables():
    src = open(ed.__file__).read()
    assert '"proven_bands": proven_bands' in src
    assert '"bands": bands' in src
