"""tests/test_coach_weight_recency_1924.py — #1924: the OTHER coach generator's weigh-in date.

THE LIVE FAILURE (2026-08-01). `/api/coaching-dashboard` published, from Dr. Victor
Reyes:

    "The weight anchor I'm working from is 321.1 lbs at Day 1, and the latest
     reading is 316.3 lbs."

The cockpit served **317.0** (weigh-in 2026-08-01). `cross_surface:weight` (#1894)
caught the disagreement and, being a hard gate, blocked every deploy.

WHY 316.3 AND NOT A HALLUCINATION. The daily brief computes for *yesterday*, and its
weight window is `fetch_range("withings", ..., yesterday)` — it **ends at yesterday by
construction**. The cycle's weigh-ins are 07-27, 07-28 and 08-01, so on 08-01 the newest
reading inside that window is 07-28's 316.3. The number was correct for the brief's
frame and wrong for the surface it was rendered on, because it travelled without its
date. Not an invention — a frame mismatch.

WHY THE #1894 GUARD DIDN'T COVER IT. #1894 fixed `ai_expert_analyzer_lambda`, which
writes `SOURCE#coach_thread#...`. The dashboard reads `COACH#physical_coach / OUTPUT#`,
written by **daily_brief** via `ai_context._build_physical_data` — a second coach
generator that never got the treatment. The guard was applied to the instance that was
being looked at, not to the set.
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ai import ai_context  # noqa: E402
from intelligence import weight_recency  # noqa: E402


def _rec(day, lbs):
    return {"sk": f"DATE#{day}", "weight_lbs": lbs}


# Dates are derived relative to "today" so this can never become a frozen-fixture
# time bomb (the golden-tests/wall-clock trap).
_TODAY = date(2026, 8, 1)
_CYCLE = [_rec("2026-07-27", 321.1), _rec("2026-07-28", 316.3), _rec("2026-08-01", 317.0)]
_ENDS_YESTERDAY = _CYCLE[:2]  # what fetch_range(..., yesterday) actually returns on 08-01

# #2104: summarize_weight_readings became cycle-aware, so a fixture that replays a
# specific cycle has to NAME that cycle's genesis. These rows are cycle 11's (the
# incident's own dates); pinning it here is also what keeps this file from becoming
# a time bomb the next time EXPERIMENT_START_DATE moves past 2026-08-01.
_GENESIS = "2026-07-27"


def test_the_live_failure_reproduces_without_the_date():
    """The bare number the coach was handed really was 316.3 — the bug is real."""
    facts = weight_recency.summarize_weight_readings(_ENDS_YESTERDAY, _TODAY.isoformat(), genesis=_GENESIS)
    assert facts["current_weight_lb"] == 316.3
    # ...and it is knowably stale: 4 days old, past the 2-day tolerance.
    assert facts["current_weight_as_of"] == "2026-07-28"
    assert facts["current_weight_age_days"] == 4
    assert facts["current_weight_is_stale"] is True


def test_physical_coach_now_receives_the_reading_date_and_staleness():
    """The fix: the date travels with the number into the coach's fact set."""
    facts = weight_recency.summarize_weight_readings(_ENDS_YESTERDAY, _TODAY.isoformat(), genesis=_GENESIS)
    built = ai_context._build_physical_data({"latest_weight": 316.3, "weight_recency": facts})

    assert built["current_weight_lb"] == 316.3
    assert built["current_weight_as_of"] == "2026-07-28"
    assert built["current_weight_is_stale"] is True
    # and the prompt is explicitly told not to present it as current
    note = built["weight_recency_note"]
    assert "NOT" in note and "2026-07-28" in note
    assert "do NOT attach it to a day label" in note


def test_a_fresh_weigh_in_stays_silent():
    """No nagging on healthy data — the rider is empty when the reading is current."""
    facts = weight_recency.summarize_weight_readings(_CYCLE, _TODAY.isoformat(), genesis=_GENESIS)
    built = ai_context._build_physical_data({"latest_weight": 317.0, "weight_recency": facts})
    assert built["current_weight_lb"] == 317.0
    assert built["current_weight_is_stale"] is False
    assert built["weight_recency_note"] == ""


def test_absent_recency_block_degrades_cleanly():
    """A caller that has not been updated must not crash the coach build."""
    built = ai_context._build_physical_data({"latest_weight": 300.0})
    assert built["latest_weight"] == 300.0
    assert built.get("current_weight_as_of") is None
    assert built["weight_recency_note"] == ""


def test_guard_the_set_both_coach_generators_use_one_staleness_definition():
    """#1924's root cause was two generators and one guard.

    Assert both import the shared module rather than re-deriving staleness — a second
    local definition is how the two drifted apart in the first place.
    """
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
    generators = {
        "intelligence/ai_expert_analyzer_lambda.py": "the observatory generator (#1894)",
        "ai/ai_context.py": "the daily-brief coach generator (#1924)",
    }
    for rel, why in generators.items():
        with open(os.path.join(root, rel)) as fh:
            src = fh.read()
        assert "weight_recency" in src, f"{rel} ({why}) must use the shared staleness definition"
        assert "STALE_AFTER_DAYS" not in src, f"{rel} re-defines staleness locally instead of importing it"


def test_stale_threshold_is_the_shared_one():
    """Pin the contract both generators now share."""
    assert weight_recency.STALE_AFTER_DAYS == 2
    facts = weight_recency.summarize_weight_readings(
        [_rec((_TODAY - timedelta(days=2)).isoformat(), 300.0)],
        _TODAY.isoformat(),
        genesis=_GENESIS,
    )
    assert facts["current_weight_is_stale"] is False, "exactly at the threshold is still fresh"
    # #2104: and it is fresh because of the AGE rule, not because the cycle filter
    # silently emptied the window — without this the assertion above would pass for
    # entirely the wrong reason the next time the genesis constant moves.
    assert facts["current_weight_lb"] == 300.0
    assert facts["current_weight_is_pre_genesis"] is False


# ── the check side: a dated citation is not a contradiction ─────────────────


def test_the_live_prose_still_fails_on_the_undated_claim():
    """The REAL half of #1924 must keep failing — this is not a mute."""
    from operational import weight_truth_qa as wq

    prose = "The weight anchor I'm working from is 321.1 lbs at Day 1, and the latest reading is 316.3 lbs."
    cited = wq.weights_cited_in(prose)
    assert 316.3 in cited, "an undated 'latest reading' is still a present-tense claim"
    assert 321.1 not in cited, "a figure anchored 'at Day 1' is dated, not a claim about today"


def test_dating_the_citation_clears_the_check():
    """The cure for the real half must be ABLE to pass — otherwise the fix is unreachable.

    intelligence/weight_recency tells the coach to write "as of <date>"; if the check
    still flagged that, dating the claim would be pointless.
    """
    from operational import weight_truth_qa as wq

    ok, msg = wq.assess_cross_surface_weight(
        {"weight_lbs": 317.0},
        [
            {
                "name": "Dr. Victor Reyes",
                "position_summary": "The most recent weigh-in is 316.3 lbs as of 2026-07-28; he is at 317.0 lbs now.",
            }
        ],
    )
    assert ok, msg


def test_an_undated_out_of_tolerance_weight_still_blocks():
    """Negative test: removing the anchor must bring the failure straight back.

    Uses 321.1, not 316.3 — and that distinction is the whole story of the live
    incident. |316.3 - 317.0| = 0.7 lb, INSIDE the 1.5 lb tolerance, so the stale
    "latest reading" never tripped the gate. What actually failed was 321.1 vs
    317.0 — the correctly-labelled Day-1 anchor. The blocking failure was 100% the
    false positive; the staleness is a real honesty defect that the gate never
    caught. Two separate problems that looked like one line of output.
    """
    from operational import weight_truth_qa as wq

    ok, msg = wq.assess_cross_surface_weight(
        {"weight_lbs": 317.0},
        [{"name": "Dr. Victor Reyes", "position_summary": "He is at 321.1 lbs."}],
    )
    assert not ok
    assert "321.1" in msg


def test_the_exact_live_failure_now_passes():
    """Replay of the published prose against the live cockpit value."""
    from operational import weight_truth_qa as wq

    ok, msg = wq.assess_cross_surface_weight(
        {"weight_lbs": 317.0},
        [
            {
                "name": "Dr. Victor Reyes",
                "position_summary": "The weight anchor I'm working from is 321.1 lbs at Day 1, and the latest reading is 316.3 lbs.",
            }
        ],
    )
    assert ok, msg


def test_a_later_date_cannot_launder_an_undated_claim():
    """The anchor window is deliberately short — a date in the NEXT sentence is not a label."""
    from operational import weight_truth_qa as wq

    prose = "The latest reading is 316.3 lbs. That measurement was taken as of 2026-07-28."
    assert 316.3 in wq.weights_cited_in(prose)
