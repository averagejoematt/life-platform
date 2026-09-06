"""tests/test_raw_zone_drift_3570.py — #3570 (DA-8): the raw-zone drift check.

Pure-function tests for scripts/check_raw_zone_drift.py — never touches AWS (the
live-S3 leg is `list_common_prefixes`, exercised by hand per the PR body, not by
this suite). Covers:
  1. `expand_prefix` — brace-alternation and comma-separated-alternatives parsing.
  2. `prefix_root` — the raw/<x> vs raw/matthew/<x> namespace split.
  3. `known_prefix_roots` against the REAL registry — every root this PR added
     must actually be there (a positive control the registry additions are wired).
  4. `check_coverage` — the coverage decision itself, including a MUST-FAIL
     control: an uncovered live prefix is reported, not silently passed.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_raw_zone_drift as drift  # noqa: E402

# ── 1. expand_prefix ──────────────────────────────────────────────────────────


def test_expand_prefix_plain_passthrough():
    assert drift.expand_prefix("raw/matthew/withings") == ["raw/matthew/withings"]


def test_expand_prefix_brace_alternation():
    out = drift.expand_prefix("raw/whoop/{cycle,sleep,recovery,workout}")
    assert out == [
        "raw/whoop/cycle",
        "raw/whoop/sleep",
        "raw/whoop/recovery",
        "raw/whoop/workout",
    ]


def test_expand_prefix_comma_separated_alternatives():
    out = drift.expand_prefix("raw/apple_health, raw/matthew/apple_health")
    assert out == ["raw/apple_health", "raw/matthew/apple_health"]


def test_expand_prefix_comma_alternatives_plus_brace_together():
    # A realistic combined shape: two full alternatives, one of which has a brace group.
    out = drift.expand_prefix("raw/a, raw/b/{x,y}")
    assert out == ["raw/a", "raw/b/x", "raw/b/y"]


# ── 2. prefix_root ────────────────────────────────────────────────────────────


def test_prefix_root_top_level():
    assert drift.prefix_root("raw/garmin") == "raw/garmin"
    assert drift.prefix_root("raw/garmin/2026/03/08.json") == "raw/garmin"


def test_prefix_root_matthew_namespace():
    assert drift.prefix_root("raw/matthew/withings/measurements") == "raw/matthew/withings"
    assert drift.prefix_root("raw/matthew/matthew") == "raw/matthew/matthew"


# ── 3. known_prefix_roots against the REAL registry (positive control) ────────


def test_known_roots_include_every_root_this_pr_added():
    roots = drift.known_prefix_roots()
    # The four #3570 additions the PR body cites explicitly.
    for expected in (
        "raw/apple_health",
        "raw/matthew/apple_health",
        "raw/health_auto_export",
        "raw/matthew/labs",
        "raw/inbound_email",
        "raw/matthew/inbound_email",
        "raw/matthew/matthew",
        # the X-9 no-user-segment predecessor family found by the same drift check
        "raw/withings",
        "raw/strava",
        "raw/eightsleep",
        "raw/garmin",
        "raw/macrofactor",
        "raw/cgm_readings",
        "raw/state_of_mind",
        "raw/workouts",
    ):
        assert expected in roots, f"{expected!r} missing from known_prefix_roots() — a #3570 registry entry regressed"


# ── 4. check_coverage — the decision, including a MUST-FAIL control ───────────


def test_check_coverage_clean_when_every_live_prefix_is_known():
    known = {"raw/garmin", "raw/matthew/garmin"}
    uncovered = drift.check_coverage(live_top=["garmin"], live_matthew=["garmin"], known_roots=known)
    assert uncovered == []


def test_check_coverage_flags_an_uncovered_live_prefix():
    """MUST-FAIL control: a live prefix with no matching known root is reported,
    not silently absorbed — proves the guard isn't vacuous."""
    known = {"raw/garmin"}
    uncovered = drift.check_coverage(live_top=["a_brand_new_source_nobody_documented"], live_matthew=[], known_roots=known)
    assert uncovered == ["raw/a_brand_new_source_nobody_documented"]


def test_check_coverage_skips_the_matthew_namespace_marker_itself():
    # "matthew" as a live TOP-level name under raw/ is the namespace divider —
    # walked separately via live_matthew, never flagged as its own gap.
    uncovered = drift.check_coverage(live_top=["matthew"], live_matthew=[], known_roots=set())
    assert uncovered == []


def test_check_coverage_against_the_real_registry_is_clean_for_every_known_root():
    """Replays the real registry's own roots as the 'live' listing — every root the
    registry claims to cover must, tautologically, cover itself. Not a live-S3
    proof (that's the PR body's `check_raw_zone_drift.py` run), but proves the
    coverage LOGIC doesn't reject its own inputs."""
    known = drift.known_prefix_roots()
    top = sorted({r.split("/")[1] for r in known if r.startswith("raw/") and not r.startswith("raw/matthew/")})
    matthew = sorted({r.split("/")[2] for r in known if r.startswith("raw/matthew/")})
    uncovered = drift.check_coverage(live_top=top, live_matthew=matthew, known_roots=known)
    assert uncovered == []
