"""tests/test_recap_templates_3745.py — a card is about the day, or there is no card.

THE BRIEF, VERBATIM
  *"so it's not just rinse and repeat… any sort of new, unique, interesting things that
  would captivate me would captivate my readers about the story."*

A fixed layout is a dashboard screenshot by day three, so each day draws the one or two
templates with the most SIGNAL. But variety is the second rule. The first is that a
template with nothing true to say draws nothing — this platform has shipped a card
asserting "Real CGM data. Updated daily." over a null endpoint (#3527), a card painting a
weight GAIN in success green under the caption "LOST" (#3285), and cards publishing
fabricated counts (#3261). Those were pages, correctable in minutes. A public Instagram
grid is not: a wrong frame survives in someone's screenshot.

WHAT IS PINNED HERE
  1. an empty day produces NO candidates (not a placeholder card)
  2. every template's own None conditions, each with its can-fire control
  3. the pick is DETERMINISTIC — same inputs, same choice, or "different every day" is a
     hope rather than a property
  4. direction words come from classify_delta, never from a re-derived sign
  5. a provisional rate is not publishable as fact (ADR-105)
  6. copy_for RAISES on a missing fact instead of drawing an em-dash — on the site "—"
     honestly says "not measured"; on a card it reads as a design flourish
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from content.recap_data import DayFacts, WorkoutFact  # noqa: E402
from web import recap_templates as rt  # noqa: E402


def _rich(**over) -> DayFacts:
    base = dict(
        date="2026-09-13",
        day_n=8,
        weight_lb=319.7,
        week_ago_weight_lb=322.0,
        weekly_rate_lb=-2.3,
        rate_ci=(-3.0, -1.5),
        rate_provisional=False,
        workouts=[WorkoutFact("Legs", 4, 18, 12000.0, "Squat (Barbell)")],
        tier0_done=8,
        tier0_total=8,
        tier0_pct=100.0,
        tier0_streak=4,
        protein_g=182,
        protein_target_g=180,
        calories=2100,
        journal_templates=["Evening"],
    )
    base.update(over)
    return DayFacts(**base)


# ── 1. An empty day draws nothing ─────────────────────────────────────────────
def test_a_day_with_no_data_produces_no_card():
    empty = DayFacts(date="2026-09-13", absent=["computed_metrics", "habit_scores", "hevy", "strava", "macrofactor", "notion"])
    assert rt.score_all(empty, []) == {name: None for name in rt.PRIORITY}
    assert rt.pick(empty, []) == [], "an empty day produced a card — this is the #3527 shape"


def test_a_rich_day_produces_a_card():
    """NEGATIVE CONTROL — a picker that never picks is not a picker."""
    assert rt.pick(_rich(), []) != []


# ── 2. Per-template None conditions, each with its control ────────────────────
def test_weight_declines_without_both_endpoints():
    assert rt._weight_signal(_rich(week_ago_weight_lb=None), []) is None
    assert rt._weight_signal(_rich(weight_lb=None), []) is None
    assert rt._weight_signal(_rich(), []) is not None


def test_weight_declines_while_the_rate_is_provisional():
    """ADR-105 — a projected number does not go on a public card as settled fact."""
    assert rt._weight_signal(_rich(rate_provisional=True), []) is None
    assert rt._weight_signal(_rich(rate_provisional=False), []) is not None


def test_weight_declines_when_the_direction_is_unknown():
    """classify_delta returns UNKNOWN for a non-finite or absent delta; that is a decline."""
    assert rt._weight_signal(_rich(weight_lb=float("nan")), []) is None


def test_workout_declines_with_no_sessions_and_fires_with_one():
    assert rt._workout_signal(_rich(workouts=[]), []) is None
    assert rt._workout_signal(_rich(), []) is not None


def test_workout_declines_on_a_session_with_zero_sets():
    """A logged-but-empty session is not a training story."""
    assert rt._workout_signal(_rich(workouts=[WorkoutFact("Legs", 0, 0, 0.0, None)]), []) is None


def test_habits_declines_without_a_denominator():
    assert rt._habits_signal(_rich(tier0_total=None), []) is None
    assert rt._habits_signal(_rich(tier0_total=0), []) is None
    assert rt._habits_signal(_rich(), []) is not None


def test_nutrition_declines_without_protein_and_scores_against_target():
    assert rt._nutrition_signal(_rich(protein_g=None), []) is None
    assert rt._nutrition_signal(_rich(protein_g=90, protein_target_g=180), []) == pytest.approx(0.5)
    assert rt._nutrition_signal(_rich(protein_g=90, protein_target_g=None), []) == 0.3


def test_journal_declines_with_no_entries():
    assert rt._journal_signal(_rich(journal_templates=[]), []) is None
    assert rt._journal_signal(_rich(), []) is not None


def test_comeback_needs_a_baseline_before_it_will_claim_one():
    """'First time in N days' is a claim about history; one day is not history."""
    assert rt._comeback_signal(_rich(), []) is None
    thin = [DayFacts(date="2026-09-12", tier0_pct=20.0)]
    assert rt._comeback_signal(_rich(), thin) is None


def test_comeback_ignores_todays_own_row_in_the_baseline():
    """Callers differ on whether the trailing window includes today. Comparing him against
    himself would silently never fire — the quietest kind of broken."""
    with_today = [
        DayFacts(date="2026-09-10", tier0_pct=95.0),
        DayFacts(date="2026-09-11", tier0_pct=90.0),
        DayFacts(date="2026-09-12", tier0_pct=20.0),
        DayFacts(date="2026-09-13", tier0_pct=100.0),  # today, again
    ]
    assert rt._comeback_signal(_rich(tier0_pct=100.0), with_today) == 0.9


def test_comeback_fires_on_a_bad_day_followed_by_a_good_one():
    trailing = [
        DayFacts(date="2026-09-10", tier0_pct=95.0),
        DayFacts(date="2026-09-11", tier0_pct=90.0),
        DayFacts(date="2026-09-12", tier0_pct=20.0),
    ]
    assert rt._comeback_signal(_rich(tier0_pct=100.0), trailing) == 0.9


def test_comeback_fires_on_a_streak_and_not_on_a_wobble():
    steady = [DayFacts(date=f"2026-09-{d}", tier0_pct=95.0) for d in (10, 11, 12)]
    assert rt._comeback_signal(_rich(tier0_pct=95.0), steady) is not None
    wobbly = [
        DayFacts(date="2026-09-10", tier0_pct=95.0),
        DayFacts(date="2026-09-11", tier0_pct=60.0),
        DayFacts(date="2026-09-12", tier0_pct=70.0),
    ]
    assert rt._comeback_signal(_rich(tier0_pct=72.0), wobbly) is None


# ── 3. Determinism and the second slot ────────────────────────────────────────
def test_the_pick_is_deterministic():
    facts, trailing = _rich(), []
    assert len({tuple(rt.pick(facts, trailing)) for _ in range(20)}) == 1


def test_ties_break_by_a_fixed_priority_not_by_dict_order():
    """weight_trend, habits and nutrition all score 1.0 on a good day. The winner must be
    the same one every time, and it must be the one that is more of a story."""
    facts = _rich()
    scores = rt.score_all(facts, [])
    assert scores["weight_trend"] == scores["habits"] == 1.0
    assert rt.pick(facts, [])[0] == "weight_trend"


def test_a_weak_second_candidate_does_not_earn_a_slot():
    """A protein number with no target scores 0.3 — real, but not a second card. (A journal
    tick at 0.45 DOES earn one, deliberately: the owner asked for days that are not all
    about the gym.)"""
    facts = _rich(workouts=[], tier0_done=None, tier0_total=None, tier0_pct=None, journal_templates=[], protein_target_g=None)
    picked = rt.pick(facts, [])
    assert picked[0] == "weight_trend"
    assert len(picked) == 1, f"a 0.3 nutrition signal took the second slot: {picked}"


def test_a_non_training_day_can_still_carry_a_second_card():
    """'It might not all be about exercise and fitness' — the owner, 2026-09-13."""
    facts = _rich(workouts=[], tier0_done=None, tier0_total=None, tier0_pct=None, protein_g=None)
    assert rt.pick(facts, []) == ["weight_trend", "journal"]


def test_a_strong_second_candidate_does_earn_one():
    """NEGATIVE CONTROL for the floor — it must be passable."""
    assert len(rt.pick(_rich(), [])) == 2


def test_exclusions_are_honoured_so_the_gate_can_force_a_repick():
    """#3746: a blocked item label drops its template and the picker chooses again."""
    picked = rt.pick(_rich(), [], exclude=["weight_trend"])
    assert "weight_trend" not in picked and picked


# ── 4. Direction comes from the one ruling ────────────────────────────────────
def test_a_gain_is_never_labelled_as_a_loss():
    """#3285, on a permanent surface: a static label over a signed value."""
    gained = _rich(weight_lb=323.0, week_ago_weight_lb=322.0, weekly_rate_lb=1.0)
    copy = rt.copy_for("weight_trend", gained)
    assert copy["direction"] == "up"
    assert copy["label"] == "UP THIS WEEK"
    assert "DOWN" not in copy["label"] and "LOST" not in copy["label"]


def test_a_loss_reads_as_a_loss_and_a_hold_as_a_hold():
    assert rt.copy_for("weight_trend", _rich())["label"] == "DOWN THIS WEEK"
    held = _rich(weight_lb=322.0, week_ago_weight_lb=322.0, weekly_rate_lb=0.0)
    assert rt.copy_for("weight_trend", held)["label"] == "HELD THIS WEEK"


def test_the_confidence_interval_travels_with_the_rate():
    """#551 — a projected number never ships as a bare point estimate."""
    assert "CI" in (rt.copy_for("weight_trend", _rich())["sub"] or "")


# ── 5. A missing fact raises rather than drawing a dash ───────────────────────
def test_copy_raises_rather_than_drawing_an_em_dash():
    for name in ("weight_trend", "workout", "habits", "nutrition", "journal", "consistency_comeback"):
        with pytest.raises(rt.RecapNullFact):
            rt.copy_for(name, DayFacts(date="2026-09-13"))


def test_no_rendered_string_contains_an_em_dash_placeholder():
    copies = [rt.copy_for(n, _rich()) for n in rt.pick(_rich(), [])]
    for s in rt.all_strings(copies, caption="Day 8 of the experiment"):
        assert s.strip() != "—", "a placeholder dash reached the card copy"


# ── The gate's input ──────────────────────────────────────────────────────────
def test_item_labels_expose_every_name_a_card_could_draw():
    """Whatever the gate does not see, it cannot screen."""
    labels = _rich().item_labels()
    assert ("workout", "Legs") in labels
    assert ("workout", "Squat (Barbell)") in labels


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
