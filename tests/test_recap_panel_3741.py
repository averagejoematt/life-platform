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


def test_no_card_counts_attempts_or_prior_episodes():
    """Owner ruling 2026-09-19: no "attempt #17", no "16 lost · 0 kept" — the first true experiment."""
    f = _facts(weighed_today=True, weight_lb=319.7)
    for img in (
        L.scorecard(f, date_label="x"),
        L.trajectory(f, date_label="x", weight_series=[327.3, None, 319.7]),
        L.dayzero(f, date_label="x"),
    ):
        for t in _strings(img):
            low = t.lower()
            assert "attempt" not in low and "16 lost" not in low and "stayed off" not in low, t
    for cap in (L.caption_for_beat("scorecard", f, day_label="Day 5", date_label="x"), L.dayzero_caption(f), L.HASHTAGS):
        assert "attempt" not in cap.lower() and "sixteen" not in cap.lower(), cap
    assert any("THE EXPERIMENT" in t for t in _strings(L.scorecard(f, date_label="x")))


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
    assert C._milestone(f, [], 32195.0, prior_sessions=4) == "most moved so far"
    assert C._milestone(f, [], 60000.0, prior_sessions=4) is None


def test_a_milestone_picks_the_beat_that_carries_it():
    f = _facts(weighed_today=True, weight_lb=317.31, milestone="first 10 lb")
    assert L.pick_beat(f, [])[0] == "trajectory"
    g = _facts(workouts=[WorkoutFact("Legs", 6, 12, 49400.0, None, [], 150, [], 12)], milestone="most moved so far")
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


# ── #4362: "Not checked in: Walk 5k" beside "walked 5.2 mi" ─────────────────────────
# The live 2026-09-26 rows, read-only from DynamoDB 2026-09-27, cut to the fields the card
# reads (no names, notes, polylines or ids). habit_scores is the row AS STORED before the
# scorer fix: it still lists the renamed "Walk 5k" as missed.
ROWS_0926 = {
    "computed_metrics": {"component_details": {"hydration": {"water_oz": 26.1, "target_oz": 100}}},
    "habit_scores": {"tier0_done": 5, "tier0_total": 7, "missed_tier0": ["Walk 5k", "Morning Sunlight / Luminette Glasses"]},
    "strava": {
        "activities": [
            {
                "type": "WeightTraining",
                "trainer": True,
                "start_date": "2026-09-26T17:59:23Z",
                "elapsed_time_seconds": 3937,
                "device_name": "Hevy",
            },
            {
                "type": "WeightTraining",
                "trainer": True,
                "start_date": "2026-09-26T18:28:00Z",
                "elapsed_time_seconds": 1019,
                "device_name": "WHOOP",
            },
            {
                "type": "Walk",
                "trainer": False,
                "distance_miles": 5.16,
                "start_date": "2026-09-26T20:09:22Z",
                "elapsed_time_seconds": 6175,
                "device_name": "Garmin epix (Gen2)",
            },
        ]
    },
}
HEVY_0926 = [
    {
        "start_time": "2026-09-26T17:59:23+00:00",
        "end_time": "2026-09-26T19:05:00+00:00",
        "exercises": [
            {"name": "Suitcase Carry", "sets": [{"reps": 10, "weight_lbs": 50}]},
            {"name": "Stretching", "sets": [{"duration_sec": 900}]},
        ],
    }
]


def _facts_0926(monkeypatch, rows=None, hevy=None):
    rows = ROWS_0926 if rows is None else rows
    monkeypatch.setattr(recap_data, "_get_day", lambda _t, source, _d: rows.get(source))
    monkeypatch.setattr(
        recap_data, "_query_prefix", lambda _t, source, _p: (HEVY_0926 if hevy is None else hevy) if source == "hevy" else []
    )
    return recap_data.day_facts(None, "2026-09-26")


def test_the_0926_card_credits_the_walk_it_measured_instead_of_listing_it_missed(monkeypatch):
    f = _facts_0926(monkeypatch)
    assert f.walk_miles == 5.16 and f.longest_outdoor_walk_mi == 5.16
    assert f.met_by_measurement == ["Walk 5k"]
    assert f.missed_tier0 == ["Morning Sunlight / Luminette Glasses"]
    caption = L.caption_for_beat("scorecard", f, day_label="Day 21", date_label="Sat 26 Sep")
    drawn = " | ".join(_strings(L.scorecard(f, date_label="x")))
    assert "Walk 5k" not in caption and "Walk 5k" not in drawn
    assert "Morning Sunlight" in caption and "Morning Sunlight" in drawn


def test_a_measured_twin_is_credited_only_when_the_habits_own_definition_is_met(monkeypatch):
    """The SET: every tier-0 habit a card measurement could stand in for, and the ones it cannot."""
    f = _facts_0926(monkeypatch)
    f.water_oz = 102.0
    assert recap_data.measured_twin_met("Walk Outdoor >2mi", f)
    assert recap_data.measured_twin_met("Walk 5k", f)  # 5 km = 3.11 mi <= 5.16
    assert recap_data.measured_twin_met("Hydrate 3L", f)  # 3 L = 101.4 oz
    f.water_oz = 26.1  # the real 09-26 channel: 26 oz on a day "Hydrate 3L" was checked in
    assert not recap_data.measured_twin_met("Hydrate 3L", f)  # a partial channel never credits
    for no_quantity in ("Primary Exercise", "Calorie Goal", "Morning Sunlight / Luminette Glasses", "No alcohol"):
        assert not recap_data.measured_twin_met(no_quantity, f), no_quantity
    f.longest_outdoor_walk_mi = 1.9
    assert not recap_data.measured_twin_met("Walk Outdoor >2mi", f)
    f.longest_outdoor_walk_mi = None
    assert not recap_data.measured_twin_met("Walk Outdoor >2mi", f)


def test_a_treadmill_walk_is_not_an_outdoor_walk(monkeypatch):
    """#4068: WHOOP posts the treadmill block inside a Hevy session as its own Strava Walk."""
    whoop = {
        "type": "Walk",
        "distance_miles": 3.4,
        "start_date": "2026-09-26T18:10:00Z",
        "elapsed_time_seconds": 3000,
        "device_name": "WHOOP",
    }
    treadmill = [{**HEVY_0926[0], "exercises": [{"name": "Treadmill", "sets": [{"duration_sec": 3000}]}]}]
    rows = {**ROWS_0926, "strava": {"activities": [whoop]}}
    f = _facts_0926(monkeypatch, rows=rows, hevy=treadmill)
    assert f.longest_outdoor_walk_mi is None and f.missed_tier0 == ["Walk 5k", "Morning Sunlight / Luminette Glasses"]
    rows = {**ROWS_0926, "strava": {"activities": [{**whoop, "trainer": True, "start_date": "2026-09-26T22:00:00Z"}]}}
    assert _facts_0926(monkeypatch, rows=rows, hevy=[]).longest_outdoor_walk_mi is None
