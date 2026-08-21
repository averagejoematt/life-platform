"""tests/test_eightsleep_stage_pct_reconcile_2921.py — no impossible stage percentage.

THE LIVE DEFECT. On 2026-08-21 `/api/sleep_detail` served this row to the public site:

    2026-08-20   deep 11.1 + rem 31.1 + light 106.7  =  148.9%

`light_pct: 106.7` is not a rounding artifact — it is a percentage of a denominator that
was never the right one. The stored Eight Sleep row for that night:

    deep_hours 0.15 + rem_hours 0.42 + light_hours 1.44 = 2.01h
    sleep_duration_hours (TST)                          = 1.35h
    awake_hours                                         = 0.61h

The stages carried the awake time; TST excluded it. `compute_derived_fields` divided
anyway, because it asserted the reconciliation instead of checking it.

WHY THE CONDITION IS "IMPOSSIBLE", NOT "DOES NOT RECONCILE". Measured across all 991
stored rows: 45 have stage hours exceeding TST (mostly 105-124% — a systematic vendor
skew), and only ONE of those 45 ever published a percentage over 100. Omitting on the
reconciliation test would strip 44 nights of plausible figures to fix one live defect.
The guard fires on the thing that cannot be true, not on a proxy for it.

WHY ALL THREE ARE OMITTED, NOT JUST LIGHT. Every percentage came off the same bad
denominator, so `deep_pct` 11.1 was equally wrong — the real figure against the stage
total is 7.5%. It escaped notice only by landing inside a plausible range. A guard that
fixed `light_pct` alone would leave two wrong numbers published and read as a fix.

WHY OMIT RATHER THAN CLAMP. Clamping to 100 fabricates a figure and destroys the evidence
that anything was wrong — the exact opposite of ADR-104, which says the honest output for
"cannot compute" is absence. `stage_pct_omitted_reason` carries the numbers so a consumer
can distinguish "not measured" from "measured and dropped" (#2819's lesson: a field that
vanishes silently is its own defect).

Related: #2921 owns this endpoint's other half — the API interleaves Eight Sleep and Whoop
figures in one object, which is why the served row's `hours`/`deep_sleep_hours` do not
match the stored Eight Sleep row above at all.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "ingestion")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Same import-time env contract tests/test_eightsleep_ingestion_behavior.py declares:
# the module reads S3_BUCKET with os.environ[...] at import (no default), so omitting
# these turns a test failure into a COLLECTION error that aborts the whole job (#1297).
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import pytest  # noqa: E402
from ingestion.eightsleep_lambda import compute_derived_fields  # noqa: E402

_PCTS = ("rem_pct", "deep_pct", "light_pct")

# The real 2026-08-20 row, verbatim from DynamoDB — the fixture IS the wire (#1221's rule).
THE_2026_08_20_ROW = {
    "date": "2026-08-20",
    "sleep_duration_hours": 1.35,
    "awake_hours": 0.61,
    "time_to_sleep_min": 0,
    "deep_hours": 0.15,
    "rem_hours": 0.42,
    "light_hours": 1.44,
}

# A night that reconciles normally — stages sum to TST within rounding.
A_HEALTHY_NIGHT = {
    "date": "2026-08-21",
    "sleep_duration_hours": 6.80,
    "awake_hours": 0.40,
    "time_to_sleep_min": 6,
    "deep_hours": 0.95,
    "rem_hours": 1.78,
    "light_hours": 4.09,
}


def test_the_real_regression_row_publishes_no_impossible_percentage():
    """THE defect, pinned to the row that actually shipped."""
    derived = compute_derived_fields(THE_2026_08_20_ROW)
    for key in _PCTS:
        assert (
            key not in derived
        ), f"{key} was published for a night whose stages do not reconcile with TST — it cannot be a true percent-of-TST"
    assert "stage_pct_omitted_reason" in derived, "the percentages vanished with no stated reason — a silent drop is its own defect (#2819)"
    reason = derived["stage_pct_omitted_reason"]
    assert "2.01" in reason and "1.35" in reason, f"the reason must carry the numbers that produced it, got: {reason!r}"


def test_a_reconciling_night_still_gets_its_percentages():
    """The control. A guard that omits on every night would 'fix' the impossible value
    by deleting the feature — passing this file while removing what it protects."""
    derived = compute_derived_fields(A_HEALTHY_NIGHT)
    for key in _PCTS:
        assert key in derived, f"{key} is missing on a night that reconciles fine — the guard is over-firing"
    assert "stage_pct_omitted_reason" not in derived
    total = sum(derived[k] for k in _PCTS)
    assert 98.0 <= total <= 102.0, f"stage percentages sum to {total}, not ~100 — the denominator is wrong on a night that should reconcile"


@pytest.mark.parametrize("row", [THE_2026_08_20_ROW, A_HEALTHY_NIGHT])
def test_no_published_percentage_ever_exceeds_100(row):
    """The invariant, stated independently of the mechanism: whatever this function
    decides to publish, a percentage over 100 is never a legitimate output."""
    derived = compute_derived_fields(row)
    for key in _PCTS:
        if key in derived:
            assert 0 <= derived[key] <= 100, f"{key}={derived[key]} is not a possible percentage"


def test_stage_sum_just_inside_tolerance_still_publishes():
    """Vendor rounding must not trip the guard. Three stages rounded to 2dp can drift a
    few hundredths; that is not a reconciliation failure."""
    row = dict(A_HEALTHY_NIGHT, deep_hours=0.96, rem_hours=1.79, light_hours=4.10)  # sum 6.85 vs TST 6.80
    derived = compute_derived_fields(row)
    assert all(k in derived for k in _PCTS), "rounding drift was treated as a mismatch — the tolerance is too tight"


def test_a_skewed_but_possible_night_KEEPS_its_percentages():
    """THE SCOPE DECISION, pinned — the guard must not over-fire.

    Measured across all 991 stored Eight Sleep rows: **45 have stage hours exceeding
    TST** (mostly 105-124%, a systematic vendor skew where brief wake epochs land inside
    a stage), and **only one of the 45** ever produced a percentage over 100. The obvious
    guard — "omit whenever the stages fail to reconcile with TST" — would therefore strip
    44 nights of individually-plausible figures to fix one live defect: a real regression
    traded for a cosmetic one, and a mass mutation of the archive nobody reviewed.

    So the condition is the thing that genuinely cannot be true (a percentage outside
    [0,100]), not a proxy for it. This row is 8% skewed and every percentage is possible;
    it must keep them."""
    row = dict(A_HEALTHY_NIGHT, deep_hours=1.10, rem_hours=1.90, light_hours=4.35)  # 7.35h vs TST 6.80 = 108%
    derived = compute_derived_fields(row)
    assert all(
        k in derived for k in _PCTS
    ), "a merely-skewed night lost its percentages — the guard is firing on the proxy, not the invariant"
    assert "stage_pct_omitted_reason" not in derived
    assert all(0 <= derived[k] <= 100 for k in _PCTS)


def test_the_guard_is_not_vacuous():
    """Mutation proof: a night whose stages exceed TST by a wide margin MUST be caught.
    Built from the healthy night so the only thing that changed is the reconciliation."""
    broken = dict(A_HEALTHY_NIGHT, light_hours=9.0)  # stages 11.73h vs TST 6.80h
    derived = compute_derived_fields(broken)
    assert not any(k in derived for k in _PCTS), "a wildly unreconciled night still published percentages — the guard does not fire"
    assert "stage_pct_omitted_reason" in derived


def test_missing_stage_data_is_not_treated_as_a_mismatch():
    """A night with no stage breakdown at all must simply produce no percentages — not a
    spurious omission reason claiming a reconciliation failure that never happened."""
    derived = compute_derived_fields({"date": "2026-08-22", "sleep_duration_hours": 7.0, "awake_hours": 0.5, "time_to_sleep_min": 5})
    assert not any(k in derived for k in _PCTS)
    assert "stage_pct_omitted_reason" not in derived, "absent stage data was reported as a reconciliation failure"
