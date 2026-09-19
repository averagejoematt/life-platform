"""tests/test_recap_detail_3741.py — two cards a day, Day 0, and the filler for a missing piece.

THE BRIEF (owner, 2026-09-19, reviewing the first thirteen live cards)

  *"two graphics per day, maybe day 1 is the high level overview, highlights, insights,
  specifics, and the second image is a dual or three part split screen summarizing what i
  actually worked out that day, what i ate that day if available, and then any other sort
  of insights"* · *"a day zero card, maybe just showing the weight, and any other notables"*
  · *"plans for each daily card when certain ingestion wasnt available to us, i.e.
  placeholder things, maybe rotating visuals that show graphs, insights, coach points"*

WHAT THESE PIN

  - the second card draws only the bands the day HAS, fills an empty slot with a block that
    is true on any day and NAMES the absence, and refuses to exist below two blocks;
  - the two captions go through ONE gate call — the second card never gets its own verdict;
  - Day 0 is exactly the eve of genesis, draws none of the eve's names, and the lambda
    clears them before the gate (the first render was held on a cycle-16 habit row);
  - the Hevy title glyph fix: a ☀️ typed into the app became a notdef box on Day 5;
  - the weekly card's facts precede the coach line — the quote gives way, not the miss;
  - per-exercise detail never prints "0 lb" for a bodyweight movement.
"""

from __future__ import annotations

import pathlib
import sys
from decimal import Decimal

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from content.recap_data import DayFacts, ExerciseFact, WorkoutFact, _workout_facts  # noqa: E402

pytest.importorskip("PIL")

from web import recap_layouts as L  # noqa: E402

PORTRAIT = (1080, 1350)


def _full(**over) -> DayFacts:
    base = dict(
        date="2026-09-16",
        day_n=11,
        weight_lb=318.91,
        baseline_weight_lb=327.34,
        goal_weight_lb=185.0,
        grade_letter="B",
        component_scores={"movement": 57.0, "nutrition": 78.0},
        workouts=[
            WorkoutFact(
                "Foundation - Pull - 2 - 6",
                8,
                22,
                16710.0,
                "Lat Pulldown (Cable)",
                ["Lat Pulldown (Cable)", "Face Pull"],
                duration_min=144,
                detail=[
                    ExerciseFact("Lat Pulldown (Cable)", 4, 140, 10),
                    ExerciseFact("Face Pull", 4, 50, 12),
                    ExerciseFact("Stretching", 1),
                ],
            )
        ],
        walk_miles=0.7,
        calories=Decimal("1493"),
        cal_target=Decimal("1800"),
        protein_g=Decimal("200"),
        protein_target_g=Decimal("190"),
        carbs_g=Decimal("98"),
        fat_g=Decimal("46"),
        fiber_g=Decimal("27.8"),
        meals=Decimal("1"),
        snacks=Decimal("2"),
        sleep_hrs=Decimal("6.28"),
        sleep_score=Decimal("80"),
        recovery_pct=Decimal("92"),
        hrv_ms=Decimal("43.38"),
        steps=Decimal("940"),
        water_oz=Decimal("96.4"),
        water_target_oz=Decimal("100"),
        readiness=Decimal("70"),
        tier0_done=6,
        tier0_total=7,
        missed_tier0=["Walk 5k"],
        journal_templates=["evening"],
        coach_line="The Garmin pause has created a data blind spot.",
    )
    base.update(over)
    return DayFacts(**base)


WEIGHTS = [327.34, None, None, None, None, None, 319.68, None, None, 318.91, None]
GRADES = ["C", "B-", "B-", "B-", "C-", "C-", "C-", "B-", "C+", "B-", "B"]


# ── the second card ───────────────────────────────────────────────────────────
def test_a_full_day_draws_all_three_bands_and_no_filler():
    assert L.detail_bands(_full()) == ["trained", "ate", "rest"]
    assert L.detail_plan(_full(), WEIGHTS, GRADES) == [("trained", None), ("ate", None), ("rest", None)]


def test_the_detail_card_renders_at_portrait_from_dynamodb_decimals():
    # Every numeric field above is a Decimal on purpose — that is what the table returns.
    img = L.detail(_full(), date_label="Wed 16 Sep", weight_series=WEIGHTS, grade_series=GRADES)
    assert img.size == PORTRAIT


def test_an_empty_slot_takes_a_filler_that_names_the_absence():
    f = _full(workouts=[], walk_miles=0.0)
    plan = L.detail_plan(f, WEIGHTS, GRADES)
    assert plan[:2] == [("ate", None), ("rest", None)]
    block, note = plan[2]
    assert block in L.FILLERS
    assert note == "no training logged"
    assert L.detail(f, date_label="x", weight_series=WEIGHTS, grade_series=GRADES).size == PORTRAIT


def test_a_day_with_nothing_logged_still_gets_a_card_when_two_fillers_can_draw():
    bare = DayFacts(date="2026-09-17", day_n=12, baseline_weight_lb=327.34, goal_weight_lb=185.0, weight_lb=317.31)
    plan = L.detail_plan(bare, WEIGHTS, GRADES)
    assert len(plan) == L.DETAIL_SLOTS
    assert all(note for _b, note in plan), "every filler on a bare day names what it stands in for"
    assert L.detail(bare, date_label="x", weight_series=WEIGHTS, grade_series=GRADES).size == PORTRAIT


def test_below_two_blocks_there_is_no_second_card():
    # No weight, no series, no coach line: only the stakes can draw. One block is not a card.
    nothing = DayFacts(date="2026-09-17", day_n=12)
    assert L.detail_plan(nothing) == [("stakes", "no training logged")]
    with pytest.raises(ValueError):
        L.detail(nothing, date_label="x")


def test_fillers_rotate_by_day_so_consecutive_gaps_lead_differently():
    ctx = {"weight_series": WEIGHTS, "grade_series": GRADES}
    a = L.pick_fillers(_full(day_n=3), ctx, 1)
    b = L.pick_fillers(_full(day_n=4), ctx, 1)
    assert a and b and a != b
    assert L.pick_fillers(_full(day_n=3), ctx, 1) == a, "deterministic"


def test_a_filler_that_cannot_draw_today_is_not_a_candidate():
    ctx = {"weight_series": [], "grade_series": []}
    names = L.pick_fillers(_full(coach_line=None), ctx, 5)
    assert "arc" not in names and "graded" not in names and "coach" not in names
    assert "stakes" in names and "road" in names


def test_the_second_caption_is_assembled_from_the_card_and_capped():
    cap = L.detail_caption(_full(), day_label="Day 11")
    assert cap.startswith("Day 11 · attempt #17 · the detail")
    assert "Pull Day, 22 sets, 16,710 lb moved" in cap
    assert "1,493 kcal, 200 g protein" in cap
    assert "habits 6/7" in cap
    assert len(cap) <= L.CAPTION_MAX_CHARS


def test_both_captions_go_through_the_one_gate_call():
    strings = L.gate_strings(_full(), "first caption", extra=("second caption", ""))
    assert "first caption" in strings and "second caption" in strings
    assert "" not in strings


# ── the glyph fix ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw, clean",
    [
        ("Morning workout ☀️", "Morning workout"),
        ("Push 💪 Day", "Push Day"),
        ("Foundation - Pull - 2 - 6", "Foundation - Pull - 2 - 6"),
        ("Zone 2 · 45'", "Zone 2 · 45'"),
    ],
)
def test_symbols_the_fonts_cannot_draw_never_reach_a_title(raw, clean):
    assert L.clean_title(raw) == clean


def test_the_session_label_is_clean_before_it_is_split():
    assert L._session_label("Morning workout ☀️") == "Morning workout"
    assert L._session_label("Foundation - Pull - 2 - 6") == "Pull Day"


# ── exercise detail ───────────────────────────────────────────────────────────
def test_exercise_detail_is_top_weight_and_reps_at_it_and_never_zero_lb():
    rows = [
        {
            "title": "Pull",
            "duration_sec": 8619,
            "exercises": [
                {
                    "name": "Lat Pulldown (Cable)",
                    "sets": [{"weight_kg": 63.503, "reps": 10}, {"weight_kg": 63.503, "reps": 8}, {"weight_kg": 54.4, "reps": 12}],
                },
                {"name": "Stretching", "sets": [{"weight_kg": None, "reps": 1}, {"weight_kg": 0, "reps": 1}]},
            ],
        }
    ]
    (w,) = _workout_facts(rows)
    assert w.duration_min == 144
    lat, stretch = w.detail
    assert (lat.name, lat.n_sets, lat.top_weight_lb, lat.reps) == ("Lat Pulldown (Cable)", 3, 140, 10)
    assert (stretch.n_sets, stretch.top_weight_lb, stretch.reps) == (2, None, None), "bodyweight is absent, not 0 lb"


# ── Day 0 ─────────────────────────────────────────────────────────────────────
def test_day_zero_renders_from_the_baseline_and_goal_alone():
    eve = DayFacts(date="2026-09-05", day_n=0, baseline_weight_lb=327.34, goal_weight_lb=185.0)
    assert L.dayzero(eve, date_label="Sat 5 Sep").size == PORTRAIT
    cap = L.dayzero_caption(eve)
    assert cap.startswith("Day 0 · attempt #17") and "327.3 lb" in cap and "142 lb to lose" in cap


def test_day_zero_refuses_without_an_anchor():
    with pytest.raises(ValueError):
        L.dayzero(DayFacts(date="2026-09-05", day_n=0), date_label="x")


def test_the_serial_marker_says_day_0_not_a_dash():
    seen: list[str] = []

    class _Draw:
        def text(self, xy, text, **kw):
            seen.append(text)

    L._serial(_Draw(), DayFacts(date="2026-09-05", day_n=0), "Sat 5 Sep")
    assert any(t.startswith("DAY 0 ") for t in seen), seen


# ── the weekly card's order ───────────────────────────────────────────────────
def test_on_the_weekly_card_the_facts_come_before_the_quote(monkeypatch):
    order: list[str] = []
    real_row, real_coach = L._fact_row, L._coach_line

    def _row(draw, label, value, **kw):
        order.append(f"row:{label}")
        return real_row(draw, label, value, **kw)

    def _coach(draw, facts, **kw):
        order.append("coach")
        return real_coach(draw, facts, **kw)

    monkeypatch.setattr(L, "_fact_row", _row)
    monkeypatch.setattr(L, "_coach_line", _coach)
    L.reckoning(
        _full(),
        week_n=1,
        date_label="week 1",
        grade_series=GRADES[:7],
        totals={"sessions": 6, "sets": 117, "misses": "recovery — 24/100 at its worst"},
    )
    assert "coach" in order and "row:biggest miss" in order
    assert order.index("row:biggest miss") < order.index("coach")


# ── the lambda: two puts, two deliveries, one record ──────────────────────────
@pytest.fixture
def lambda_harness(monkeypatch):
    from content import recap_data, recap_deliver, recap_gate
    from web import recap_card_lambda as C

    puts: dict[str, bytes] = {}
    records: dict[str, dict] = {}
    sends: list[tuple[str, str]] = []

    monkeypatch.setattr(C._s3, "put_object", lambda Bucket, Key, Body, **kw: puts.__setitem__(Key, Body))
    monkeypatch.setattr(C, "_record", lambda sk, payload: records.__setitem__(sk, payload))
    monkeypatch.setattr(C, "_existing", lambda sk: None)
    monkeypatch.setattr(C.boto3, "client", lambda *a, **k: None)
    monkeypatch.setattr(C, "EXPERIMENT_START_DATE", "2026-09-06")
    monkeypatch.setattr(recap_data, "trailing", lambda *a, **k: [])
    monkeypatch.setattr(recap_data, "cycle_series", lambda *a, **k: (WEIGHTS, GRADES))
    monkeypatch.setattr(recap_data, "coach_line", lambda *a, **k: ("The Garmin pause has created a data blind spot.", "OUTPUT#x", "ok"))
    monkeypatch.setattr(recap_gate, "gate", lambda strings, **k: recap_gate.GateResult(recap_gate.VERDICT_CLEARED))
    monkeypatch.setattr(
        recap_deliver,
        "deliver",
        lambda png, caption, **k: sends.append((k["filename"], caption)) or {"telegram": "dry_run", "email": "dry_run"},
    )
    return C, recap_data, puts, records, sends


def test_a_full_day_stores_two_cards_and_delivers_both(lambda_harness, monkeypatch):
    C, recap_data, puts, records, sends = lambda_harness
    monkeypatch.setattr(recap_data, "day_facts", lambda *a, **k: _full())
    out = C.render_for_date("2026-09-16", deliver=True, force=True, dry_run=True)
    assert set(puts) == {"recap/2026-09-16.png", "recap/2026-09-16-detail.png"}
    assert out["detail_s3_key"] == "recap/2026-09-16-detail.png"
    assert out["detail_caption"].startswith("Day 11 · attempt #17 · the detail")
    assert [f for f, _c in sends] == ["recap-2026-09-16.png", "recap-2026-09-16-detail.png"]
    assert records["DATE#2026-09-16"]["delivered_detail"] == {"telegram": "dry_run", "email": "dry_run"}


def test_day_zero_is_exactly_the_eve_and_carries_none_of_the_eves_names(lambda_harness, monkeypatch):
    C, recap_data, puts, records, sends = lambda_harness
    # The eve holds the PREVIOUS cycle's row: a workout, a missed-habit list with a name the
    # gate would hold on, a streak dict. None of it is the starting line's.
    eve = _full(date="2026-09-05", day_n=None, missed_tier0=["Walk 5k", "No placeholder"], vice_streaks={"No placeholder": 3})
    monkeypatch.setattr(recap_data, "day_facts", lambda *a, **k: eve)
    screened: list[list[str]] = []
    from content import recap_gate

    monkeypatch.setattr(
        recap_gate, "gate", lambda strings, **k: screened.append(list(strings)) or recap_gate.GateResult(recap_gate.VERDICT_CLEARED)
    )
    out = C.render_for_date("2026-09-05", deliver=True, force=True, dry_run=True)
    assert out["beat"] == "dayzero" and out["day_n"] == 0
    assert set(puts) == {"recap/2026-09-05.png"}, "no detail card on the eve"
    assert out["coach_line_status"] == "skipped"
    assert not any("placeholder" in s.lower() or "Walk 5k" in s for s in screened[0]), screened[0]
    assert len(sends) == 1
    assert C._genesis_eve() == "2026-09-05"


def test_a_random_pre_genesis_date_is_not_day_zero(lambda_harness, monkeypatch):
    C, recap_data, puts, records, sends = lambda_harness
    monkeypatch.setattr(recap_data, "day_facts", lambda *a, **k: _full(date="2026-08-20", day_n=None))
    out = C.render_for_date("2026-08-20", deliver=False, force=True, dry_run=True)
    assert out["beat"] != "dayzero"
