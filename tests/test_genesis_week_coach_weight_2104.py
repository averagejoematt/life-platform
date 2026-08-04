"""tests/test_genesis_week_coach_weight_2104.py — #2104: a pre-genesis body is not
this cycle's body, at any age.

THE LIVE FAILURE (cycle 12, genesis 2026-08-03). `/api/coaching-dashboard` published,
from Dr. Victor Reyes:

    "I have one weight reading: 317.0 lbs via Withings."

while `/api/vitals` served 322. The nightly `cross_surface:weight` pass (#1894) called
it correctly and `qa-smoke-failures` stayed red from genesis onward.

WHY THE #1894/#1924 GUARDS DID NOT COVER IT — and this is the whole point of the fix.
The Withings rows, in order, were 07-28, **08-01 (316.97)**, then **08-03 (321.6,
ingested 08-04T04:05Z)**. The physical coach ran at 08-03T17:38Z. So at generation time
the newest reading it could possibly see was 08-01, which was **exactly two days old** —
and `STALE_AFTER_DAYS = 2` tests `age > 2`. Not stale. No recency rider fired, the bare
number went into the prompt undated, and the coach narrated it as current. Every
existing guard was age-based, and age was never the problem: the reading was recent AND
belonged to a cycle that no longer existed.

THE FIX. `summarize_weight_readings` filters to the current cycle. When no reading in
the window is on-or-after genesis there is no `current_weight_lb` at all — the value is
withheld from the fact set, not merely annotated. That matters because it makes the rule
STRUCTURAL: `grounded_generation`'s allow-list gate treats a number absent from the facts
as a fabrication, so the existing regen-once harness corrects a coach that cites it
anyway. A prompt instruction alone could not have guaranteed that (the #1937 lesson).

These tests pin: the incident replay, the withholding, the rider, the second generator,
the reset-time verifier hook, and the static-shell span claims that made up the other
half of the same night's findings.
"""

import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ai import ai_context  # noqa: E402
from intelligence import weight_recency  # noqa: E402
from operational import weight_truth_qa as wq  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GENESIS = "2026-08-03"
GEN_DAY = date(2026, 8, 3)


def _rec(day, lbs):
    return {"sk": f"DATE#{day}", "weight_lbs": lbs}


# The real cycle-11 tail plus the cycle-12 Day-1 weigh-in, at the dates the platform
# actually holds them. `_AT_COACH_RUN` is what a 08-03T17:38Z query could return: the
# Day-1 row had not ingested yet.
_ALL = [_rec("2026-07-28", 316.31), _rec("2026-08-01", 316.97), _rec(GENESIS, 321.6)]
_AT_COACH_RUN = _ALL[:2]


# ── the incident, replayed ────────────────────────────────────────────────────


def test_the_pre_genesis_reading_was_not_stale_by_age():
    """Establish the premise before fixing it: age alone genuinely cleared this."""
    as_of = date(2026, 8, 1)
    assert (GEN_DAY - as_of).days == weight_recency.STALE_AFTER_DAYS
    assert not ((GEN_DAY - as_of).days > weight_recency.STALE_AFTER_DAYS), "age > 2 is False — the old guard passed it"


def test_no_current_weight_is_emitted_when_every_reading_predates_genesis():
    """The fix: withheld, not annotated. The number must not reach the fact set."""
    facts = weight_recency.summarize_weight_readings(_AT_COACH_RUN, GENESIS, genesis=GENESIS)

    assert facts["current_weight_lb"] is None, "316.97 must not be offered as a current weight"
    assert facts["current_weight_as_of"] is None
    assert facts["current_weight_is_stale"] is False, "absence is absence, not staleness"
    assert facts["current_weight_is_pre_genesis"] is True
    assert facts["cycle_weight_readings"] == 0
    assert facts["cycle_genesis"] == GENESIS
    # ...and the window is still described honestly: rows exist, none of them in-cycle.
    assert facts["weight_readings"] == 2


def test_the_withheld_value_appears_nowhere_in_the_fact_set():
    """Guard the mechanism, not the field name — a future refactor that reintroduces
    the number under any other key must fail here."""
    facts = weight_recency.summarize_weight_readings(_AT_COACH_RUN, GENESIS, genesis=GENESIS)
    assert 316.97 not in [v for v in facts.values() if isinstance(v, (int, float))]


def test_a_change_figure_never_straddles_the_reset():
    """Two pre-genesis readings are a pilot-cycle trend, not this experiment's."""
    facts = weight_recency.summarize_weight_readings(_AT_COACH_RUN, GENESIS, genesis=GENESIS)
    assert facts["weight_change_observed"] is None
    assert facts["weight_change_span_days"] is None


def test_the_day_one_weigh_in_restores_everything_once_it_lands():
    """The fix must not be a permanent mute — the next morning's ingest resolves it."""
    facts = weight_recency.summarize_weight_readings(_ALL, "2026-08-04", genesis=GENESIS)
    assert facts["current_weight_lb"] == 321.6
    assert facts["current_weight_as_of"] == GENESIS
    assert facts["current_weight_is_pre_genesis"] is False
    assert facts["cycle_weight_readings"] == 1


def test_an_ordinary_mid_cycle_window_is_untouched():
    """No behaviour change away from a reset boundary — the regression guard."""
    rows = [_rec("2026-08-10", 320.0), _rec("2026-08-17", 317.0)]
    facts = weight_recency.summarize_weight_readings(rows, "2026-08-17", genesis=GENESIS)
    assert facts["current_weight_lb"] == 317.0
    assert facts["current_weight_is_pre_genesis"] is False
    assert facts["weight_change_observed"] == -3.0
    assert facts["weight_change_span_days"] == 7


def test_genesis_defaults_to_the_live_constant_so_no_caller_can_forget():
    """The #1967 lesson: an all-optional anchor is how coverage drifts into
    convention. Both generators get the cycle filter without opting in."""
    from common.constants import EXPERIMENT_START_DATE

    facts = weight_recency.summarize_weight_readings(_AT_COACH_RUN, GENESIS)
    assert facts["cycle_genesis"] == EXPERIMENT_START_DATE


def test_no_readings_at_all_is_still_honest_absence_not_a_pre_genesis_claim():
    facts = weight_recency.summarize_weight_readings([], GENESIS, genesis=GENESIS)
    assert facts["current_weight_lb"] is None
    assert facts["weight_readings"] == 0
    assert facts["current_weight_is_pre_genesis"] is False, "an empty window predates nothing"


# ── the prompt rider ──────────────────────────────────────────────────────────


def test_the_rider_names_the_reset_and_forbids_the_exact_published_claim():
    facts = weight_recency.summarize_weight_readings(_AT_COACH_RUN, GENESIS, genesis=GENESIS)
    note = weight_recency.weight_recency_prompt_block(facts)

    assert "WEIGHT DATA RECENCY" in note
    assert GENESIS in note, "the rider must name the boundary it is enforcing"
    assert "latest reading" in note, "the published lie was phrased as a latest reading"
    assert "Day 1" in note
    assert "316.97" not in note and "317" not in note, "the rider must not smuggle the value back in"


def test_the_rider_does_not_assert_an_absolute_absence_it_cannot_know():
    """The brief's weight window ends at YESTERDAY while its `weight_lbs` fact can
    carry today's row — so a flat "you have no current weight" here would itself be
    a possible lie. The rider talks about the window and about inventing figures."""
    facts = weight_recency.summarize_weight_readings(_AT_COACH_RUN, GENESIS, genesis=GENESIS)
    note = weight_recency.weight_recency_prompt_block(facts)
    assert "in the facts" in note


def test_the_rider_is_silent_on_a_healthy_in_cycle_reading():
    facts = weight_recency.summarize_weight_readings(_ALL, GENESIS, genesis=GENESIS)
    assert weight_recency.weight_recency_prompt_block(facts) == ""


# ── the second generator (guard the SET, #1924's lesson) ─────────────────────


def test_the_brief_coach_generator_also_withholds_the_bare_latest_weight():
    """`latest_weight` is a separate bare number on the ai_context path. Dating it is
    not enough when the whole window predates the reset."""
    facts = weight_recency.summarize_weight_readings(_AT_COACH_RUN, GENESIS, genesis=GENESIS)
    built = ai_context._build_physical_data({"latest_weight": 316.97, "weight_recency": facts})

    assert built["latest_weight"] is None
    assert built["current_weight_lb"] is None
    assert "WEIGHT DATA RECENCY" in built["weight_recency_note"]


def test_todays_own_row_is_still_served_when_it_exists():
    """`weight_lbs` is today's row and is in-cycle by construction — suppressing it
    would hide the true current weight, which is the opposite defect."""
    facts = weight_recency.summarize_weight_readings(_AT_COACH_RUN, GENESIS, genesis=GENESIS)
    built = ai_context._build_physical_data({"withings": {"weight_lbs": 321.6}, "latest_weight": 316.97, "weight_recency": facts})
    assert built["weight_lbs"] == 321.6


def test_a_mid_cycle_latest_weight_is_untouched():
    facts = weight_recency.summarize_weight_readings(_ALL, "2026-08-04", genesis=GENESIS)
    built = ai_context._build_physical_data({"latest_weight": 321.6, "weight_recency": facts})
    assert built["latest_weight"] == 321.6


# ── the check side: the published prose, and what clears it ──────────────────


def test_the_published_prose_still_fails_the_cross_surface_check():
    """This is not a mute. The exact card that was live must still be a failure."""
    ok, msg = wq.assess_cross_surface_weight(
        {"weight_lbs": 322},
        [{"name": "Dr. Victor Reyes", "position_summary": "I have one weight reading: 317.0 lbs via Withings."}],
    )
    assert ok is False
    assert "317.0" in msg and "322" in msg


def test_the_honest_absence_prose_clears_the_check():
    """The cure has to be reachable, or the gate is unpassable (the #1924 lesson)."""
    ok, msg = wq.assess_cross_surface_weight(
        {"weight_lbs": 322},
        [
            {
                "name": "Dr. Victor Reyes",
                "position_summary": "No weigh-in has landed in this cycle yet, so I have no bodyweight to read from.",
            }
        ],
    )
    assert ok, msg


def test_a_dated_pre_cycle_citation_would_also_clear_the_check():
    """The rider's sanctioned escape hatch and the check's exemption are one seam."""
    ok, msg = wq.assess_cross_surface_weight(
        {"weight_lbs": 322},
        [{"name": "Dr. Victor Reyes", "position_summary": "The last reading was 316.97 lbs as of 2026-08-01, before this cycle began."}],
    )
    assert ok, msg


# ── the reset-time hook (acceptance: cycle 13 cannot reproduce it) ───────────


def test_restart_verify_checks_the_coaching_door_and_reuses_the_nightly_assessor():
    src = open(os.path.join(REPO, "deploy", "restart_verify.py")).read()
    assert "assess_cross_surface_weight" in src, "the post-reset verifier must look at the coaching door"
    assert "weight_truth_qa" in src, "it must import the nightly's assessor, not re-derive the rule"
    assert "CROSS_SURFACE_WEIGHT_TOL" not in src, "a local tolerance literal is a second copy free to drift"


# ── the static shell's span claims (the reader_truth half of the same night) ──

# Words that assert a span the shipped HTML cannot know has elapsed. cockpit.js has
# spoken in the filling-in voice since the #1094 drill; the static default did not, so
# a fresh genesis served "seven days, by instrument" to crawlers, no-JS readers and the
# nightly reader-truth pass. Derived from the SECTIONS, not from the two captions that
# happened to be wrong — a caption added later is covered without anyone remembering.
_SPAN_CLAIMS = re.compile(r"seven days|this month|this week|past 30 days|last 30 days|the last week", re.IGNORECASE)


def _reader_facing(markup: str) -> str:
    """Everything a reader (or an assistive tech, or the tag-stripping truth pass) can
    reach: visible text AND attribute values such as aria-label. Only HTML comments —
    which reach nobody — are dropped, so a span claim cannot hide in an accessible name."""
    return re.sub(r"<!--.*?-->", " ", markup, flags=re.S)


def test_cockpit_scope_sections_ship_no_unearned_span_claim():
    html = open(os.path.join(REPO, "site", "cockpit", "index.html")).read()
    for marker in ("data-weekview", "data-monthview"):
        at = html.find(marker)
        assert at != -1, f"could not locate the {marker} section"
        start = html.rfind("<section", 0, at)  # this section's own open tag, not a neighbour's
        end = html.find("</section>", at)
        hit = _SPAN_CLAIMS.search(_reader_facing(html[start:end]))
        assert not hit, f"{marker} ships the static claim {hit.group(0)!r} — a fresh cycle has not lived it yet"


def test_the_javascript_still_promotes_to_the_earned_copy():
    """The other end of the seam: honest defaults must not cost the mature reader
    the real caption once the window exists."""
    js = open(os.path.join(REPO, "site", "assets", "js", "cockpit.js")).read()
    assert '"seven days, by instrument"' in js
    assert '"what changed this month"' in js
