"""#2575 — the coach cited a COMPLETE-DAY rollup while the cockpit served the latest reading.

The live failure, from the 2026-08-11 nightly qa-smoke:

    FAIL [content_truth] Reader Truth / cross_surface:vitals:
    coach-cited vitals disagree with the cockpit — Dr. Lisa Park cites recovery 53% vs cockpit 46%

Measured cause. The two surfaces have two DIFFERENT producers of "the current reading":

  * the cockpit resolves the latest FINALIZED whoop morning live, via the #1369 Truth
    Spine (`web.vitals_resolver`);
  * the coach reads the newest `USER#matthew#SOURCE#computed_metrics` row, which is a
    COMPLETE-DAY rollup: the row for day D carries `computed_at` the NEXT afternoon
    (live: `date=2026-08-10` / `computed_at=2026-08-11T16:40:18Z`). Newest-first it is
    therefore one morning behind the Spine whenever whoop has finalized today.

Not a stale row by any age rule, not a query-window difference, not a PT/UTC boundary:
two producers, one of which is a day-scoped aggregate that was never the right answer
to "what is the latest reading".

Verified end-to-end against the live table on 2026-08-11T19:0xZ, running the real
readers side by side:

    Truth Spine (cockpit) : recovery 54.0  hrv 41.07  rhr 56.0  as_of 2026-08-11
    canonical facts (coach): recovery 46.0  hrv 38.0   rhr 57.0  as_of 2026-08-10,
                             night_of 2026-08-09, latest_weight 320.4

Three of the four columns were past their cross-surface tolerance (recovery 8 pts vs
2.0; HRV 3.07 ms vs 1.5; weight 3.1 lb vs 1.5), and the coaching dashboard's live sleep
card opened "The night of 2026-08-09" while `/api/vitals` published
`night_of: 2026-08-10` — the same lag, visible in the prose.

The numbers below are that live pair. The reported 53-vs-46 is the same defect one day
earlier (whoop held 53 on 2026-08-09 and 46 on 2026-08-10); it is not reproduced
literally because 2026-08-09 precedes cycle 13's genesis, where #2113's withholding —
asserted separately below — is the rule that applies instead.

These tests are the mutation proof: `test_the_live_divergence_reappears_without_the_overlay`
reintroduces the divergence by skipping the overlay and asserts `cross_surface:vitals`
goes red on the measured numbers.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from experiment import canonical_facts as cf  # noqa: E402
from operational import weight_truth_qa as wq  # noqa: E402

GENESIS = "2026-08-10"

# The newest `computed_metrics` row, live — a complete-day rollup, one morning behind.
STALE_ROLLUP = {"sk": "DATE#2026-08-10", "recovery_pct": 46, "hrv_ms": 38.03, "rhr_bpm": 57, "latest_weight": 320.38}

# What the cockpit's resolvers served at the same moment (`/api/vitals`).
LIVE_READINGS = {
    "recovery_pct": 54.0,
    "hrv_ms": 41.07,
    "rhr_bpm": 56.0,
    "recovery_as_of": "2026-08-11",
    "latest_weight": 317.24,
    "weight_as_of": "2026-08-11",
}

COCKPIT_VITALS = {"recovery_pct": 54.0, "hrv_ms": 41.1, "rhr_bpm": 56.0, "sleep_hours": 8.9}


def _coach(facts):
    """A coach card that cites the facts it was grounded on, the way the live sleep card does."""
    return {
        "name": "Dr. Lisa Park",
        "position_summary": (
            f"Your recovery came in at {facts['recovery_pct']:g}% this morning, with HRV at "
            f"{facts['hrv_ms']:g} ms and a resting heart rate of {facts['rhr_bpm']:g} bpm."
        ),
    }


# ── the mutation proof ────────────────────────────────────────────────────────


def test_the_live_divergence_reappears_without_the_overlay():
    """Skip the overlay — the coach is grounded on the rollup again and the check reds.

    This is the pre-fix state, on the pair measured live: 46 vs 54, in the same shape
    the nightly published as 53 vs 46. If this test ever passes, the check has stopped
    being able to see the class and the fix below is unfalsifiable.
    """
    facts = cf.build_canonical_facts(STALE_ROLLUP, genesis=GENESIS)
    assert facts["recovery_pct"] == 46.0, "the rollup's own value, ungrounded by the cockpit"

    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_VITALS, [_coach(facts)])
    assert not ok
    assert "Dr. Lisa Park cites recovery 46% vs cockpit 54%" in msg
    assert "hrv 38 ms vs cockpit 41.1 ms" in msg


def test_the_overlay_makes_the_coach_agree_with_the_cockpit():
    facts = cf.overlay_latest_readings(cf.build_canonical_facts(STALE_ROLLUP, genesis=GENESIS), LIVE_READINGS, genesis=GENESIS)
    assert facts["recovery_pct"] == 54.0
    assert facts["hrv_ms"] == 41.1 and facts["rhr_bpm"] == 56.0

    ok, msg = wq.assess_cross_surface_vitals(COCKPIT_VITALS, [_coach(facts)])
    assert ok, msg


# ── the rules the overlay must keep ───────────────────────────────────────────


def test_provenance_travels_with_the_vitals_group():
    """as_of/night_of describe the wake-date-keyed vitals (#1923/#1968) — they must move.

    The live symptom was a coach narrating "The night of 2026-08-09" while the cockpit
    published `night_of: 2026-08-10`. A corrected number under an uncorrected night
    label is the same contradiction wearing a different hat.
    """
    facts = cf.overlay_latest_readings(cf.build_canonical_facts(STALE_ROLLUP, genesis=GENESIS), LIVE_READINGS, genesis=GENESIS)
    assert facts["as_of"] == "2026-08-11"
    assert facts["night_of"] == "2026-08-10"


def test_the_overlay_never_regresses_a_fact_to_an_older_reading():
    """A resolver behind the rollup is ignored — the overlay corrects a lag, never causes one."""
    fresh = {"sk": "DATE#2026-08-12", "recovery_pct": 61, "hrv_ms": 44.0, "rhr_bpm": 54}
    facts = cf.overlay_latest_readings(cf.build_canonical_facts(fresh, genesis=GENESIS), LIVE_READINGS, genesis=GENESIS)
    assert facts["recovery_pct"] == 61.0, "yesterday's reading must not overwrite today's rollup"
    assert facts["as_of"] == "2026-08-12"


def test_an_equal_dated_reading_is_a_no_op():
    """On the common day where the two already agree, turning the overlay on moves nothing."""
    same = {"sk": "DATE#2026-08-11", "recovery_pct": 54, "hrv_ms": 41.07, "rhr_bpm": 56}
    before = cf.build_canonical_facts(same, genesis=GENESIS)
    assert cf.overlay_latest_readings(dict(before), LIVE_READINGS, genesis=GENESIS) == before


def test_genesis_still_bites_on_a_live_reading():
    """#2113's rule survives: the Spine has no genesis clamp, the FACT SET does.

    The resolver happily returns a pre-genesis morning (that is its documented
    contract, #1369). If the overlay let it through, #2113's structural withholding
    would have been reopened by the fix for its sibling defect.
    """
    pre = dict(LIVE_READINGS, recovery_as_of="2026-08-09", weight_as_of="2026-08-09")  # cycle 13 genesis is 08-10
    facts = cf.overlay_latest_readings(cf.build_canonical_facts({"sk": "DATE#2026-08-08"}, genesis=GENESIS), pre, genesis=GENESIS)
    assert facts["recovery_pct"] is None and facts["hrv_ms"] is None and facts["rhr_bpm"] is None
    assert facts["latest_weight"] is None
    assert facts["facts_are_pre_genesis"] is True


def test_absent_or_unparseable_readings_are_a_clean_no_op():
    """ADR-104: absence is never a correction. A failed resolver leg leaves the rollup alone."""
    before = cf.build_canonical_facts(STALE_ROLLUP, genesis=GENESIS)
    for readings in ({}, None, {"recovery_as_of": ""}, {"recovery_as_of": "not-a-date", "recovery_pct": 1}):
        assert cf.overlay_latest_readings(dict(before), readings, genesis=GENESIS) == before


def test_the_weight_leg_closes_the_same_lag_on_the_weight_check():
    """Same defect, the column `cross_surface:weight` watches — live-verified, not hypothetical.

    While measuring #2575 the rollup held `latest_weight: 320.38` (DATE#2026-08-10)
    while `/api/vitals` served 317 as of 2026-08-11 — 3.1 lb apart, past the 1.5 lb
    `CROSS_SURFACE_WEIGHT_TOL_LBS`. It had not fired only because no coach happened to
    cite a weight that day. It is the same one-morning lag, so it takes the same fix.
    """
    rollup = {"sk": "DATE#2026-08-10", "latest_weight": 320.38}
    live = {"latest_weight": 317.24, "weight_as_of": "2026-08-11"}  # withings DATE#2026-08-11
    coach_before = {"name": "Dr. Marcus Webb", "position_summary": "You weighed in at 320.4 lb this morning."}
    ok, msg = wq.assess_cross_surface_weight({"weight_lbs": 317}, [coach_before])
    assert not ok and "320.4 lb vs cockpit 317" in msg

    facts = cf.overlay_latest_readings(cf.build_canonical_facts(rollup, genesis=GENESIS), live, genesis=GENESIS)
    assert facts["latest_weight"] == 317.2
    coach_after = {"name": "Dr. Marcus Webb", "position_summary": f"You weighed in at {facts['latest_weight']:g} lb this morning."}
    ok, msg = wq.assess_cross_surface_weight({"weight_lbs": 317}, [coach_after])
    assert ok, msg


def test_window_derived_facts_are_not_touched():
    """Only latest-reading figures move. Protein/rate stay with the rollup that computes them."""
    rollup = dict(STALE_ROLLUP, protein_g_avg=142.0, weekly_rate_lbs=-1.8, protein_g_target=190.0)
    facts = cf.overlay_latest_readings(cf.build_canonical_facts(rollup, genesis=GENESIS), LIVE_READINGS, genesis=GENESIS)
    assert facts["protein_g_avg"] == 142.0 and facts["weekly_rate_lbs"] == -1.8 and facts["protein_g_target"] == 190.0


def test_every_observed_field_is_either_overlaid_or_deliberately_window_derived():
    """Guard the SET, not the instance: a new OBSERVED fact cannot silently skip classification."""
    overlaid = {f for fields, _ in cf.LATEST_READING_GROUPS for f in fields}
    window_derived = {"protein_g_avg", "weekly_rate_lbs", "weekly_rate_ci_low", "weekly_rate_ci_high"}
    assert overlaid | window_derived == set(cf.OBSERVED_FIELDS), (
        "an OBSERVED field is neither derived from a live resolver nor declared window-derived — "
        "classify it in LATEST_READING_GROUPS or in this test's window_derived set"
    )
    assert not (overlaid & set(cf.CONFIGURED_FIELDS)), "configured targets are not readings"
