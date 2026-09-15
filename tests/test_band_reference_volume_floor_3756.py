"""#3756 — `resolve_band` must not prefer a containing band that fails the
volume evidence floor over a neighbour that clears it.

Live shape pinned below (2026-09-13, `get_benchmark(view="prescription")`):
the containing band 310-319 had only 4.0 effective days (n_weighins=4, so it
passed the OLD `min_weighins` usability check and won outright) while the
adjacent 300-309 band carried 25.7 effective days — well past the 21-day
`VOLUME_FLOOR_DAYS` — and sat one band away. The old code never got that far:
having found a "usable" containing band, it stopped widening.
"""

from lambdas.training.band_reference import VOLUME_FLOOR_DAYS, resolve_band

# The live shape from the issue, reproduced exactly.
_LIVE_BANDS = {
    "300-309": {"n_days": 37.0, "n_eff": 25.7, "n_weighins": 37.0, "walk_mi_wk": 4.67, "window": "2019-12-30..2024-09-16"},
    "310-319": {"n_days": 4.0, "n_eff": 4.0, "n_weighins": 4.0, "walk_mi_wk": 0.0, "window": "2019-12-26..2019-12-29"},
}


def test_a_containing_band_that_fails_the_volume_floor_yields_to_a_neighbour_that_clears_it():
    """The must-fail test for #3756: pins the live shape above."""
    r = resolve_band(319.7, _LIVE_BANDS)
    assert r["band"] == "300-309", f"selected {r['band']} — the thin containing band won again"
    assert r["band_requested"] == "310-319"
    assert r["exact"] is False
    assert r["band_distance_lb"] > 0
    assert r["widened_reason"] == "volume_floor"
    assert r["evidence"]["n_effective"] >= VOLUME_FLOOR_DAYS


def test_exact_band_that_clears_the_floor_is_still_used_directly():
    bands = {"310-319": {"n_days": 30, "n_eff": 25.0, "n_weighins": 20, "walk_mi_wk": 5.0}}
    r = resolve_band(315.0, bands)
    assert r["band"] == "310-319" and r["exact"] is True
    assert r["widened_reason"] is None


def test_no_band_within_max_widening_clears_the_floor_returns_containing_band_as_before():
    """Acceptance box 2: the truly-empty case is unchanged — the containing
    band is returned, unciteable, rather than declining or reaching further."""
    bands = {"310-319": {"n_days": 4, "n_eff": 4.0, "n_weighins": 4, "walk_mi_wk": 0.0}}
    r = resolve_band(315.0, bands)
    assert r is not None
    assert r["band"] == "310-319"
    assert r["exact"] is True
    assert r["widened_reason"] is None
    assert r["evidence"]["volume_ok"] is False, "must stay unciteable — nothing anywhere clears the floor"


def test_widening_for_a_missing_containing_band_still_prefers_a_floor_clearing_neighbour():
    bands = {
        "300-309": {"n_days": 30, "n_eff": 25.0, "n_weighins": 20, "walk_mi_wk": 5.0},
        "320-329": {"n_days": 5, "n_eff": 5.0, "n_weighins": 4, "walk_mi_wk": 0.0},
    }
    r = resolve_band(315.0, bands)
    assert r["band"] == "300-309"
    assert r["widened_reason"] == "no_data"


def test_widening_for_an_insufficient_weighins_containing_band():
    bands = {
        "300-309": {"n_days": 30, "n_eff": 25.0, "n_weighins": 20, "walk_mi_wk": 5.0},
        "310-319": {"n_days": 30, "n_eff": 25.0, "n_weighins": 1, "walk_mi_wk": 0.0},  # below default min_weighins=3
    }
    r = resolve_band(315.0, bands)
    assert r["band"] == "300-309"
    assert r["widened_reason"] == "insufficient_weighins"


def test_declines_rather_than_reaching_past_the_widening_limit_still_holds():
    """Pre-existing behaviour (#3709) must survive the #3756 change: silence
    beats a reference more than `max_widening` bands away, floor or no floor."""
    bands = {"200-209": {"n_days": 99, "n_eff": 99.0, "n_weighins": 40, "walk_mi_wk": 6.0}}
    assert resolve_band(327.3, bands) is None
