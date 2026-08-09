"""tests/test_pillar_absence.py — #2388: a dark source never licenses a trend verb.

The live defect (measured 2026-08-09, MacroFactor quiet 45 days per #2326): the home
family panel rendered "EATING eased off a little" and the cockpit rendered "Nutrition is
at 1 and slipping" over a cycle with ZERO food logs. This pins the server-side derivation
those surfaces now read.

What is deliberately NOT tested here: anything asserting `data_coverage != 1.0`. An
unlogged behavioral component scoring 0 at full weight IS ADR-104's documented design and
the ADR records it "so it isn't re-litigated". The defect was the translation, not the
engine, and a coverage assertion here would encode the opposite.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from health.pillar_absence import (  # noqa: E402
    PILLAR_LOG_CATEGORY,
    PILLAR_SOURCES,
    STATE_DARK,
    STATE_LOGGED,
    STATE_UNKNOWN,
    pillar_absence,
)

# The live shape: MacroFactor's newest DATE# write is 2026-06-25, the cycle-12 window
# opened 2026-08-03, today is 2026-08-09 — 45 days of silence, all of it before genesis.
LIVE_MACROFACTOR = {"macrofactor": {"last_date": "2026-06-25", "age_hours": 45 * 24, "stale_hours": 96}}
TODAY = "2026-08-09"
WINDOW = "2026-08-03"


def test_the_live_nutrition_case_is_dark_and_never_logged():
    a = pillar_absence("nutrition", source_state=LIVE_MACROFACTOR, reference_date=TODAY, window_start=WINDOW)
    assert a["state"] == STATE_DARK
    assert a["dark_sources"] == ["macrofactor"]
    # The last log predates the window, so this is never-logged-in-this-cycle — NOT a
    # "paused 45 days ago" transition. #2382: no day-count is attached to a never-logged
    # channel, and that is what stops "eased off a little" from ever being derivable.
    assert a["transition"] == "never_logged"
    assert a["days_since_last_log"] is None


def test_a_reporting_source_keeps_its_trend():
    fresh = {"macrofactor": {"last_date": "2026-08-08", "age_hours": 24, "stale_hours": 96}}
    a = pillar_absence("nutrition", source_state=fresh, reference_date=TODAY, window_start=WINDOW)
    assert a["state"] == STATE_LOGGED
    # A yesterday-dated log inside the window is a real (1-day) gap by the #2382
    # derivation, and that is fine: `state` is what silences a trend verb, and it says
    # the source is reporting. Only `dark` suppresses the trend.
    assert a["transition"] in ("logged", "paused")


def test_a_real_in_window_pause_carries_its_measured_gap():
    """Logged, then stopped — a transition that actually happened, with a real number."""
    paused = {"macrofactor": {"last_date": "2026-08-04", "age_hours": 5 * 24, "stale_hours": 96}}
    a = pillar_absence("nutrition", source_state=paused, reference_date=TODAY, window_start=WINDOW)
    assert a["state"] == STATE_DARK
    assert a["transition"] == "paused"
    assert a["days_since_last_log"] == 5


def test_dark_uses_each_sources_own_registry_window_not_a_flat_guess():
    """Hevy's window is 168h; a 6-day-old lift is FRESH where a 6-day-old food log is not."""
    strava_dark = {"strava": {"last_date": "2026-05-01", "age_hours": 100 * 24, "stale_hours": 48}}
    six_days = {"hevy": {"last_date": "2026-08-03", "age_hours": 6 * 24, "stale_hours": 168}, **strava_dark}
    assert pillar_absence("movement", source_state=six_days, reference_date=TODAY, window_start=WINDOW)["state"] == STATE_LOGGED
    tight = {"hevy": {"last_date": "2026-08-03", "age_hours": 6 * 24, "stale_hours": 96}, **strava_dark}
    a = pillar_absence("movement", source_state=tight, reference_date=TODAY, window_start=WINDOW)
    assert a["state"] == STATE_DARK
    assert sorted(a["dark_sources"]) == ["hevy", "strava"]
    # The day-count is measured off the FRESHEST dark source (the most recent log the
    # pillar has), never the oldest — "nothing logged for 100 days" would be false.
    assert a["days_dark"] == 6


def test_one_fresh_source_keeps_a_multi_source_pillar_logged():
    mixed = {
        "hevy": {"last_date": "2026-06-01", "age_hours": 69 * 24, "stale_hours": 168},
        "strava": {"last_date": "2026-08-09", "age_hours": 0, "stale_hours": 48},
    }
    assert pillar_absence("movement", source_state=mixed, reference_date=TODAY, window_start=WINDOW)["state"] == STATE_LOGGED


def test_an_unobserved_source_is_unknown_never_dark():
    """The #2056 semantics: absence of evidence is not evidence of absence. A failed
    lookup must not manufacture a 'nothing logged' claim on a reader surface."""
    partial = {"hevy": {"last_date": "2026-06-01", "age_hours": 69 * 24, "stale_hours": 168}}  # strava unobserved
    assert pillar_absence("movement", source_state=partial, reference_date=TODAY, window_start=WINDOW)["state"] == STATE_UNKNOWN
    assert pillar_absence("nutrition", source_state={}, reference_date=TODAY, window_start=WINDOW)["state"] == STATE_UNKNOWN


def test_a_source_that_has_written_nothing_at_all_is_dark_with_no_day_count():
    none_ever = {"macrofactor": {"last_date": None, "age_hours": None, "stale_hours": 96, "no_records": True}}
    a = pillar_absence("nutrition", source_state=none_ever, reference_date=TODAY, window_start=WINDOW)
    assert a["state"] == STATE_DARK
    assert a["transition"] == "never_logged"
    assert a["days_dark"] is None and a["days_since_last_log"] is None


def test_wearable_backed_pillars_are_unmapped_and_return_none():
    """sleep/metabolic/relationships keep their trend: a dark wearable is a broken pipe
    (disclosed by /api/source_freshness), not a behavioral absence."""
    for p in ("sleep", "metabolic", "relationships"):
        assert pillar_absence(p, source_state=LIVE_MACROFACTOR, reference_date=TODAY, window_start=WINDOW) is None


@pytest.mark.parametrize("bad", [None, "", "not_a_pillar", 7])
def test_garbage_input_is_total_and_silent(bad):
    assert pillar_absence(bad, source_state=LIVE_MACROFACTOR, reference_date=TODAY, window_start=WINDOW) is None


def test_absent_behaviors_ride_along_unchanged():
    a = pillar_absence(
        "nutrition",
        source_state=LIVE_MACROFACTOR,
        absent_behaviors=["protein_target", "calorie_adherence"],
        reference_date=TODAY,
        window_start=WINDOW,
    )
    assert a["absent_behaviors"] == ["protein_target", "calorie_adherence"]


def test_every_mapped_category_is_a_real_log_category():
    from ai.behavior_logs import LOG_CATEGORIES

    for pillar, cat in PILLAR_LOG_CATEGORY.items():
        assert pillar in PILLAR_SOURCES, f"{pillar} maps a log category but no source"
        assert cat in LOG_CATEGORIES, f"{cat} is outside the behavior_logs vocabulary"


def test_every_mapped_source_exists_in_the_ingestion_registry():
    """The whole point of deriving this server-side is that the window comes from the
    registry. A renamed source must fail here, not drift silently into a wrong claim."""
    from ingestion.source_registry import SOURCE_REGISTRY

    for pillar, sids in PILLAR_SOURCES.items():
        for sid in sids:
            assert sid in SOURCE_REGISTRY, f"{pillar} maps unknown source {sid}"
