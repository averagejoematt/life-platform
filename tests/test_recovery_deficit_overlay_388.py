"""tests/test_recovery_deficit_overlay_388.py — RQA-08 (#388) recovery vs prior-day
deficit overlay.

Exercises `_recovery_deficit_overlay` in lambdas/web/site_api_observatory.py — the
pure (no-DDB) alignment + confidence-gating function behind the new
`recovery_deficit_overlay` field on /api/nutrition_overview. Per the issue's
acceptance criteria: (1) each day's recovery is paired with the PRIOR day's
deficit, (2) days missing either series render as an explicit None gap — never
interpolated or dropped, (3) no correlation coefficient is ever present in the
returned payload, and (4) below the overlap-days threshold the caption stays
purely descriptive (no directional claim).
"""

import os
import random
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from web.site_api_observatory import _RDO_MIN_OVERLAP_DAYS, _recovery_deficit_overlay  # noqa: E402


def _dates(start, n):
    from datetime import datetime, timedelta

    d0 = datetime.strptime(start, "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def test_no_coefficient_ever_in_the_payload():
    """The spec is explicit: no correlation coefficient displayed at this sample
    size. Assert the field never leaks a raw r/p/CI, at any n."""
    days = _dates("2026-01-01", 45)
    rng = random.Random(11)
    deficit_by_date = {d: rng.uniform(300, 1800) for d in days}
    recovery_by_date = {d: 90 - 0.02 * deficit_by_date[days[i - 1]] + rng.gauss(0, 2) for i, d in enumerate(days) if i > 0}
    out = _recovery_deficit_overlay(deficit_by_date, recovery_by_date, days[1], days[-1])
    forbidden = {"r", "pearson_r", "coefficient", "p_value", "ci_low", "ci_high", "q_value"}
    assert forbidden.isdisjoint(out.keys())
    for row in out["days"]:
        assert forbidden.isdisjoint(row.keys())


def test_below_threshold_stays_purely_descriptive():
    """Fewer than _RDO_MIN_OVERLAP_DAYS overlapping days: ready=False and the
    caption only reports the count — no directional claim of any kind."""
    days = _dates("2026-01-01", 6)
    deficit_by_date = {d: 500 for d in days}
    recovery_by_date = {d: 70 for d in days[1:]}
    out = _recovery_deficit_overlay(deficit_by_date, recovery_by_date, days[1], days[-1])
    assert out["ready"] is False
    assert out["overlap_days"] < _RDO_MIN_OVERLAP_DAYS
    assert "overlapping day" in out["caption"]
    assert "moved together" not in out["caption"] and "tended to follow" not in out["caption"]


def test_missing_days_render_as_explicit_gaps_not_interpolated():
    """A day with no Whoop sync and a day with no MacroFactor upload must both
    come back as None in the aligned series — never filled or skipped."""
    days = _dates("2026-01-01", 10)
    deficit_by_date = {d: 600 for d in days}
    del deficit_by_date[days[3]]  # a MacroFactor gap on day 3
    recovery_by_date = {d: 65 for d in days}
    del recovery_by_date[days[7]]  # a Whoop gap on day 7
    out = _recovery_deficit_overlay(deficit_by_date, recovery_by_date, days[1], days[-1])
    by_date = {row["date"]: row for row in out["days"]}
    # day 4's PRIOR deficit (day 3) is missing -> gap, not zero/interpolated
    assert by_date[days[4]]["prior_deficit_kcal"] is None
    # day 7's own recovery is missing -> gap
    assert by_date[days[7]]["recovery"] is None
    # every requested calendar day is present (continuous walk, no dropped days)
    assert [row["date"] for row in out["days"]] == days[1:]


def test_recovery_paired_with_the_prior_days_deficit_not_the_same_day():
    """Lag alignment: recovery on day D must be paired with deficit on day D-1,
    never with day D's own (same-day) deficit."""
    days = _dates("2026-01-01", 6)
    deficit_by_date = {days[0]: 111, days[1]: 222, days[2]: 333, days[3]: 444, days[4]: 999}
    recovery_by_date = {days[1]: 51, days[2]: 52, days[3]: 53, days[4]: 54, days[5]: 55}
    out = _recovery_deficit_overlay(deficit_by_date, recovery_by_date, days[1], days[5])
    by_date = {row["date"]: row for row in out["days"]}
    assert by_date[days[1]]["prior_deficit_kcal"] == 111  # day0's deficit, not day1's own 222
    assert by_date[days[2]]["prior_deficit_kcal"] == 222  # day1's deficit, not day2's own 333
    assert by_date[days[4]]["prior_deficit_kcal"] == 444  # day3's deficit, not day4's own 999
    assert by_date[days[5]]["prior_deficit_kcal"] == 999  # day4's deficit, not "no deficit logged"


def test_strong_negative_relationship_yields_lower_after_heavier_language():
    """Enough overlapping days + a clean negative relationship (harder deficit ->
    lower next-morning recovery) should clear MEDIUM confidence and use the
    'lower ... heavier' correlative framing — with no number attached."""
    n = 45
    days = _dates("2026-01-01", n + 1)
    rng = random.Random(7)
    deficit_by_date = {d: rng.uniform(200, 2000) for d in days}
    recovery_by_date = {}
    for i in range(1, n + 1):
        prior_deficit = deficit_by_date[days[i - 1]]
        recovery_by_date[days[i]] = max(10.0, 95 - 0.03 * prior_deficit + rng.gauss(0, 1.5))
    out = _recovery_deficit_overlay(deficit_by_date, recovery_by_date, days[1], days[n])
    assert out["ready"] is True
    assert out["overlap_days"] == n
    assert out["confidence"] in ("MEDIUM", "HIGH")
    assert "lower" in out["caption"] and "heavier" in out["caption"]
    assert "causal" in out["caption"]  # the never-assert-causation guard rail


def test_no_relationship_yields_neutral_caption():
    """Independent series at a large-enough n: no directional claim, plain
    'no consistent relationship' language."""
    n = 40
    days = _dates("2026-01-01", n + 1)
    rng = random.Random(3)
    deficit_by_date = {d: rng.uniform(200, 2000) for d in days}
    recovery_by_date = {days[i]: rng.uniform(20, 95) for i in range(1, n + 1)}
    out = _recovery_deficit_overlay(deficit_by_date, recovery_by_date, days[1], days[n])
    if out["ready"] and out["confidence"] != "LOW":
        assert "No consistent relationship" in out["caption"]


def test_empty_inputs_dont_crash():
    out = _recovery_deficit_overlay({}, {}, "2026-01-01", "2026-01-10")
    assert out["overlap_days"] == 0
    assert out["ready"] is False
    assert len(out["days"]) == 10
    assert all(row["recovery"] is None and row["prior_deficit_kcal"] is None for row in out["days"])
