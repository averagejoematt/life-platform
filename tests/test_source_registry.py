"""tests/test_source_registry.py — behavioral silence must not page as breakage (#392).

Replays two real events against the canonical source registry:

1. The 2026-06-27→07-03 quiet stretch: Matthew stopped logging, so withings
   (no weigh-in), strava (no workouts), and macrofactor (no food-log upload)
   went stale while every passive device pipe stayed fresh. The slo-source-
   freshness alarm sat red for days — pure false positive; nothing was broken.

2. The Whoop token-rotation outage (project_whoop_reauth): an OAuth refresh
   broke ingestion on a passive source. That is exactly what the alarm exists
   to catch and must still page.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import freshness_checker_lambda as checker  # noqa: E402
import source_registry as reg  # noqa: E402


def _stale(*keys):
    """Build lambda_handler-shaped stale_sources entries for source keys."""
    return [(checker.SOURCES[k], "Last update: old") for k in keys]


def test_quiet_stretch_does_not_page():
    """Replay 2026-06-27→07-03: only logging-dependent sources stale → no page."""
    stale = _stale("withings", "strava", "macrofactor")
    assert checker.count_infra_stale(stale) == 0


def test_all_behavioral_sources_stale_still_no_page():
    """Even a full disengagement (every manual/logging source stale) is a
    presence story, not an outage — the paging metric must stay 0."""
    stale = _stale(*sorted(checker.BEHAVIORAL_SOURCES))
    assert checker.count_infra_stale(stale) == 0


def test_whoop_outage_still_pages():
    """Replay the Whoop token-rotation breakage: a passive pipe going stale is
    infrastructure failure and must count toward StaleSourceCount."""
    stale = _stale("whoop")
    assert checker.count_infra_stale(stale) == 1


def test_mixed_staleness_counts_only_infra():
    """A real outage during a quiet stretch must still page — behavioral noise
    can't mask it, and it can't inflate the count either."""
    stale = _stale("withings", "strava", "macrofactor", "whoop", "apple_health")
    assert checker.count_infra_stale(stale) == 2


def test_behavioral_classification_complete():
    """The three sources the earlier fix missed (withings, strava, macrofactor)
    are behavioral, alongside the original manual-log set."""
    assert reg.behavioral_source_keys() == {
        "withings",
        "strava",
        "macrofactor",
        "hevy",
        "measurements",
        "food_delivery",
    }


def test_passive_pipes_stay_infra():
    """Worn devices and scheduled API pulls must keep paging on staleness —
    this is the class that once hid a six-week outage."""
    infra = set(checker.SOURCES) - checker.BEHAVIORAL_SOURCES
    # #470: weather joined the freshness surfaces (was registry-resident for
    # facets only) — a scheduled API pull with no participation, so it pages.
    assert infra == {"whoop", "eightsleep", "apple_health", "todoist", "habitify", "weather"}


def test_no_data_query_error_pages():
    """lambda_handler appends non-source failures (query errors) under the
    source's label — those must page regardless of classification wording."""
    stale = [(checker.SOURCES["whoop"], "Query error: boom")]
    assert checker.count_infra_stale(stale) == 1


def test_registry_paused_never_monitored():
    """Paused sources are excluded from the checker set entirely (never stale)."""
    assert "garmin" not in checker.SOURCES
    assert "garmin" in reg.public_paused_sources()


def test_registry_thresholds_have_rationale_values():
    """Spot-check the thresholds that historically drifted between mirrors."""
    hours = reg.stale_hours_overrides()
    assert hours["food_delivery"] == 14 * 24  # was 90d in the MCP mirror — masking defect
    assert hours["withings"] == 7 * 24
    assert hours["hevy"] == 7 * 24
    # #471 (X-5): day-dated records + 1x-daily ingestion → max healthy age ~62h.
    # 48h false-staled request-time surfaces 14h/day; 72h is the tightest safe bound.
    assert hours["todoist"] == 72
