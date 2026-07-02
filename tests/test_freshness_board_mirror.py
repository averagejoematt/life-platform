"""tests/test_freshness_board_mirror.py — the public pipeline board mirrors the checker.

Replays the 2026-07-01 live bug: commit 483ecb11 removed strava/macrofactor from the
site's paused list without re-adding them to the active registry, so the public
board showed a 9-source pipeline while /data/training rendered Strava walks + Hevy
sets and /data/nutrition rendered MacroFactor days (and the in-code comment claimed
both "now report live freshness", which was false). The site registry's own header
says KEEP IN SYNC with freshness_checker_lambda — this makes that mechanical.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import freshness_checker_lambda as checker  # noqa: E402
from web import site_api_data as sad  # noqa: E402


def test_active_sources_match_checker():
    """Every source the checker monitors appears on the public board, and vice versa."""
    assert set(sad._FRESHNESS_SOURCES) == set(checker.SOURCES)


def test_paused_sources_not_double_listed():
    assert not set(sad._FRESHNESS_PAUSED) & set(sad._FRESHNESS_SOURCES)
    # A paused source must not be silently monitored internally either.
    assert not set(sad._FRESHNESS_PAUSED) & set(checker.SOURCES)


def test_stale_thresholds_match_checker():
    """Shared per-source thresholds agree — the food_delivery 90d-vs-14d drift class."""
    for source, hours in checker.SOURCE_STALE_HOURS.items():
        assert (
            sad._FRESHNESS_STALE_HOURS.get(source, sad._FRESHNESS_DEFAULT_STALE_HOURS) == hours
        ), f"{source}: site board threshold != checker ({hours}h)"


def test_internal_behavioral_sources_marked_on_board():
    """A checker-behavioral source (manual logging) must read behavioral publicly too,
    so a lapse never renders as a broken pipeline. (The board may additionally mark
    manual-upload sources like macrofactor behavioral for honest wording.)"""
    board_behavioral = {k for k, v in sad._FRESHNESS_SOURCES.items() if v.get("behavioral")}
    assert checker.BEHAVIORAL_SOURCES <= board_behavioral
