"""tests/test_recap_panel_3741.py — what the elite panel review changed, pinned (2026-09-19).

Seven seats (editorial designer, growth marketer, mobile UX, content PM, a quantified-self
follower, a regainer follower, the honesty seat) graded the first live set C+ to B-. The
convergent findings became rules, and each rule has a must-fail here:

  - a coach line is a COMPLETE sentence that fits, with no date, instrument or ops word —
    else no line (the Day 8 quote contradicted Day 8's own detail card);
  - a scorecard day without a weigh-in never headlines the carried-forward weight;
  - a milestone is detected from the platform's series and picks the beat;
  - trajectory cannot run three days straight on a barely-moved arc;
  - working sets exclude walking/stretching entries; "0 lb moved" is never drawn;
  - no red anywhere in the chart palette;
  - every daily card ends with the anchored goal bar and a NEXT line.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from content import recap_data  # noqa: E402
from content.recap_data import DayFacts, ExerciseFact, WorkoutFact  # noqa: E402

pytest.importorskip("PIL")

from web import (  # noqa: E402
    recap_card_lambda as C,  # noqa: E402
    recap_charts as ch,
    recap_layouts as L,
    recap_qa,
)


# ── the coach line ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text",
    [
        "On the night of 2026-09-08, his Whoop recorded 64% recovery. He trained through it anyway.",
        "On September 10th his food log went silent. He trained through it anyway.",
        "His HRV of 37 ms is physiologically normal. He trained through it anyway.",
        "The Garmin pause has created a data blind spot. He trained through it anyway.",
        "His journal reported 3/10 mood. He trained through it anyway.",
        "I'm establishing his waist-to-height ratio of 0.754 as the north star metric — it predicts cardiometabolic risk over twenty years and beyond. He trained through it anyway.",
    ],
)
def test_the_first_sentence_is_skipped_when_it_cannot_go_on_a_card(text):
    assert recap_data.card_sentence(text) == "He trained through it anyway."


@pytest.mark.parametrize(
    "opener",
    [
        "That gap is the most interesting signal I have.",
        "It's the difference between a signal and a report.",
        "Strip that meal and the total collapses.",
    ],
)
def test_a_sentence_that_points_back_at_the_one_before_is_not_a_line(opener):
    assert recap_data.card_sentence(opener + " He trained through it anyway.") == "He trained through it anyway."


def test_a_line_is_a_verbatim_sentence_of_the_input_or_nothing():
    text = "Here is the line the card wants, and it fits. Then more."
    out = recap_data.card_sentence(text)
    assert out and out in text and out.endswith(".")
    assert recap_data.card_sentence("On 2026-09-08 his HRV was 37 ms.") == ""
    assert recap_data.card_sentence("") == ""


def test_no_sentence_is_ever_cut_with_an_ellipsis():
    long = "word " * 60 + "end."
    assert recap_data.card_sentence(long) == ""


# ── the stale weight ──────────────────────────────────────────────────────────
def _strings(img):
    return [r.text for r in img.info["recap_strings"]]


def _facts(**over):
    base = dict(
        date="2026-09-10",
        day_n=5,
        weight_lb=327.34,
        weighed_today=False,
        last_weigh_label="Day 1",
        baseline_weight_lb=327.34,
        goal_weight_lb=185.0,
        grade_letter="C-",
        component_scores={"hydration": 34.0, "nutrition": 39.0, "sleep_quality": 89.0},
    )
    base.update(over)
    return DayFacts(**base)


def test_a_scorecard_without_a_weigh_in_does_not_headline_the_carried_weight():
    drawn = _strings(L.scorecard(_facts(), date_label="Thu 10 Sep"))
    assert "327.3" not in drawn, "the carried-forward weight was drawn as today's hero"
    assert "hydration" in drawn, "the day's weakest mark is the hero instead"
    assert any("last weighed Day 1" in t for t in drawn)


def test_a_scorecard_with_a_weigh_in_still_headlines_it():
    drawn = _strings(L.scorecard(_facts(weighed_today=True, weight_lb=319.7), date_label="x"))
    assert "319.7" in drawn


def test_zero_percent_is_never_claimed_before_the_arc_moves():
    drawn = _strings(L.scorecard(_facts(), date_label="x"))
    assert not any("0.0%" in t for t in drawn)
    assert any("142 lb to go" in t for t in drawn)


# ── the anchored bottom and the forward hook ──────────────────────────────────
@pytest.mark.parametrize("layout", ["scorecard", "trajectory", "session"])
def test_every_daily_card_ends_with_the_bar_and_a_next_line(layout):
    f = _facts(
        weighed_today=True,
        weight_lb=319.7,
        workouts=[WorkoutFact("Push", 3, 22, 13000.0, None, ["a", "b"], 90, [ExerciseFact("Bench", 4, 185, 5)], 22)],
    )
    img = getattr(L, layout)(f, date_label="x")
    recs = img.info["recap_strings"]
    nxt = [r for r in recs if r.text.startswith("Day 6 tomorrow")]
    assert nxt and nxt[0].bbox[1] >= L.NEXT_Y - 10
    assert any(r.text == "NEXT" for r in recs)
    assert recap_qa.audit_image(img, margin=L.M).may_store


def test_the_next_line_counts_to_the_week_close():
    assert L.next_line(DayFacts(date="x", day_n=13)) == "Day 14 tomorrow  ·  week 2 closes tomorrow"
    assert L.next_line(DayFacts(date="x", day_n=8)) == "Day 9 tomorrow  ·  week 2 closes in 6 days"
    assert L.next_line(DayFacts(date="x", day_n=14)) == "Day 15 tomorrow  ·  week 3 closes in 7 days"
    assert L.next_line(DayFacts(date="x", day_n=None)) is None


def test_the_footer_carries_the_stakes_on_every_card():
    drawn = _strings(L.scorecard(_facts(), date_label="x"))
    assert any("16 lost · 0 kept" in t for t in drawn)


# ── milestones ────────────────────────────────────────────────────────────────
def test_the_first_10_lb_is_a_milestone_once():
    f = _facts(weighed_today=True, weight_lb=317.31, day_n=12)
    assert C._milestone(f, [327.34, None, 319.68, None, 318.91, None, 317.31], 0.0) == "first 10 lb"
    # The next weigh-in past 10 lb is not "first" any more.
    g = _facts(weighed_today=True, weight_lb=315.13, day_n=13)
    assert C._milestone(g, [327.34, None, 319.68, None, 318.91, None, 317.31, 315.13], 0.0) is None


def test_a_volume_best_needs_prior_sessions_to_mean_anything():
    f = _facts(workouts=[WorkoutFact("Legs", 6, 27, 49400.0, None, [], 150, [], 27)])
    assert C._milestone(f, [], 32195.0, prior_sessions=2) is None
    assert C._milestone(f, [], 32195.0, prior_sessions=4) == "most moved this attempt"
    assert C._milestone(f, [], 60000.0, prior_sessions=4) is None


def test_a_milestone_picks_the_beat_that_carries_it():
    f = _facts(weighed_today=True, weight_lb=317.31, milestone="first 10 lb")
    assert L.pick_beat(f, [])[0] == "trajectory"
    g = _facts(workouts=[WorkoutFact("Legs", 6, 12, 49400.0, None, [], 150, [], 12)], milestone="most moved this attempt")
    assert L.pick_beat(g, [])[0] == "session"


def test_a_milestone_draws_its_stripe():
    f = _facts(weighed_today=True, weight_lb=317.31, milestone="first 10 lb")
    drawn = _strings(L.trajectory(f, date_label="x", weight_series=[327.34, None, 317.31]))
    assert any("MILESTONE" in t and "FIRST 10 LB" in t for t in drawn)


# ── anti-repeat ───────────────────────────────────────────────────────────────
def _day(date, w):
    return DayFacts(date=date, weight_lb=w)


def test_trajectory_does_not_run_three_days_on_a_barely_moved_arc():
    trailing = [_day("2026-09-16", 318.9), _day("2026-09-17", 318.7), _day("2026-09-18", 318.5)]
    today = _facts(date="2026-09-18", day_n=13, weighed_today=True, weight_lb=318.5)
    recent = [("2026-09-16", "trajectory"), ("2026-09-17", "trajectory")]
    assert L.pick_beat(today, trailing, recent_beats=recent)[0] != "trajectory"


def test_trajectory_does_run_a_third_day_when_the_arc_really_moved():
    trailing = [_day("2026-09-16", 320.0), _day("2026-09-17", 319.5), _day("2026-09-18", 317.0)]
    today = _facts(date="2026-09-18", day_n=13, weighed_today=True, weight_lb=317.0)
    recent = [("2026-09-16", "trajectory"), ("2026-09-17", "trajectory")]
    assert L.pick_beat(today, trailing, recent_beats=recent)[0] == "trajectory"


# ── sets, zeros, red ──────────────────────────────────────────────────────────
def test_walking_and_stretching_entries_are_not_working_sets():
    rows = [
        {
            "title": "Morning",
            "exercises": [
                {"name": "Treadmill", "sets": [{"duration_sec": 600}, {"duration_sec": 600}]},
                {"name": "Bench", "sets": [{"weight_kg": 60, "reps": 8}]},
            ],
        }
    ]
    (w,) = recap_data._workout_facts(rows)
    assert (w.n_sets, w.n_working_sets) == (3, 1)


def test_a_session_that_moved_no_load_never_says_zero_lb():
    w = WorkoutFact("Morning workout", 2, 4, 0.0, None, ["Treadmill", "Cycling"], 117, [], 0)
    assert "0 lb" not in L._session_line(w) and "1h 57m" in L._session_line(w)
    assert L._sets_word(1) == "1 set"
    drawn = _strings(L.session(_facts(workouts=[w]), date_label="x"))
    assert "1h 57m" in drawn and not any("0 lb" in t for t in drawn)


def test_no_red_anywhere_in_the_chart_palette():
    for letter in "ABCDF":
        r, g, b = ch.grade_colour(letter)
        assert not (r > 180 and g < 100 and b < 100), f"grade {letter} is red"
    assert ch.AMBER_DEEP != (196, 78, 62)
    for src in (L, ch):
        text = pathlib.Path(src.__file__).read_text()
        assert "(196, 78, 62)" not in text


def test_the_missed_row_says_what_it_measures():
    drawn = _strings(L.scorecard(_facts(missed_tier0=["Walk 5k"]), date_label="x"))
    assert "NOT CHECKED IN" in drawn and "MISSED" not in drawn


def test_the_vice_denominator_is_the_tracked_count():
    f = _facts(vice_streaks={"a": 7, "b": 7}, vices_total=8)
    assert L._vice_summary(f).startswith("2 of 8")
