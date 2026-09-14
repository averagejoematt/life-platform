"""tests/test_recap_campaign_3741.py — the card as a serial, and the boundary that bit twice.

THE REWORK

The owner rejected the first seven cards — *"not posts i would be excited to post each
day… more creative, more data, more detail, more throughline, more nod to the experiment"*
— and then reframed the artefact entirely: *"its a social media campaign, and so this data
and story narrative is to be told through these daily posts."*

A recap answers "what happened yesterday". A campaign post has to earn the next one. These
tests hold the rework to the three things that follow from that, plus the two defect classes
that only appeared when real data was rendered.

THE BOUNDARY THAT BIT TWICE

An unclamped trailing window reaches into the PREVIOUS cycle:

  1. the first cards headlined "2.7 lb UP THIS WEEK" on Day 4, off a `week_ago_weight`
     belonging to a different attempt;
  2. the moment beat-selection read the same window, Day 1 chose the "new weigh-in" beat
     off a weight from before the cycle began.

Twice is a class. The clamp lives in `trailing()`, once, and this file pins it there.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from content.recap_data import DayFacts, WorkoutFact, trailing  # noqa: E402

# PIL is NOT in the deploy-critical lane's dependency set
# (tests/deploy_critical_lane_deps.py::LANE_THIRD_PARTY_DEPS). `web.recap_charts` and
# `web.recap_layouts` both reach `web.card_engine`, which imports PIL at module scope — so
# importing them at MODULE level here is a collection-time error in that lane, and a
# collection error takes the whole lane (exit 2), not one test. This file's tests are not
# deploy_critical-marked and were never selected there; pytest still has to IMPORT every
# module to discover markers, which is the part that failed.
#
# Shipped 2026-09-14 and redded main: locally PIL is installed, so collection succeeded and
# the full suite passed. The sibling tests/test_recap_render_3744.py had the guard in the
# right place from the start; this file put `importorskip` inside two test bodies, which
# runs far too late. Same class as the recurring PyYAML lane errors (2026-08-24, #3100/#3105
# and 2026-09-08, #3684/#3696) — a third-party import at collection time.
pytest.importorskip("PIL")

from web import (  # noqa: E402
    recap_charts as ch,
    recap_layouts as L,
)

GENESIS = "2026-09-06"


def _facts(date="2026-09-12", **over) -> DayFacts:
    base = dict(
        date=date,
        day_n=7,
        weight_lb=319.7,
        baseline_weight_lb=327.3,
        goal_weight_lb=185.0,
        grade_letter="C-",
        grade_score=56.0,
        component_scores={"movement": 57.0, "nutrition": 29.0, "hydration": 84.0},
        readiness=58.0,
        workouts=[WorkoutFact("Foundation - Pull - 2 - 6", 6, 27, 18910.0, "Lat Pulldown (Cable)", ["Lat Pulldown (Cable)", "Face Pull"])],
        missed_tier0=["Walk 5k"],
        vice_streaks={"No sweets": 7.0, "No alcohol": 7.0},
        tier0_done=5,
        tier0_total=7,
        tier0_pct=0.714,
    )
    base.update(over)
    return DayFacts(**base)


# ── The boundary ──────────────────────────────────────────────────────────────
class _CountingTable:
    """Records which dates were asked for. No data — the query shape is the assertion."""

    def __init__(self):
        self.dates: list[str] = []

    def get_item(self, Key=None, **_kw):
        sk = (Key or {}).get("sk", "")
        if sk.startswith("DATE#"):
            self.dates.append(sk[5:])
        return {}

    def query(self, **_kw):
        return {"Items": []}


def test_the_trailing_window_never_reaches_before_genesis():
    """The defect class, pinned. Day 1's window must not contain a single prior-cycle day."""
    t = _CountingTable()
    trailing(t, GENESIS, days=7, experiment_start=GENESIS)
    assert t.dates, "the window asked for nothing at all"
    assert min(t.dates) >= GENESIS, f"the window reached before genesis: {sorted(set(t.dates))[:3]}"


def test_the_window_is_full_once_the_cycle_is_old_enough():
    """NEGATIVE CONTROL — the clamp must not permanently shorten the window."""
    t = _CountingTable()
    trailing(t, "2026-10-01", days=7, experiment_start=GENESIS)
    assert len(set(t.dates)) == 7


def test_an_absent_genesis_does_not_clamp():
    t = _CountingTable()
    trailing(t, GENESIS, days=7, experiment_start=None)
    assert min(t.dates) < GENESIS, "without a genesis there is no boundary to enforce"


# ── Beat selection ────────────────────────────────────────────────────────────
def test_a_new_weigh_in_takes_the_trajectory_beat():
    prior = [_facts(date="2026-09-11", weight_lb=327.3)]
    beat, why = L.pick_beat(_facts(weight_lb=319.7), prior)
    assert beat == "trajectory" and "weigh-in" in why


def test_an_unchanged_weight_is_not_a_weigh_in():
    """computed_metrics carries the last weight forward; a repeat is not a measurement."""
    prior = [_facts(date="2026-09-11", weight_lb=319.7)]
    assert L.pick_beat(_facts(weight_lb=319.7), prior)[0] != "trajectory"


def test_a_heavy_session_takes_the_session_beat():
    f = _facts(weight_lb=None)
    assert L.pick_beat(f, [])[0] == "session"


def test_a_light_session_does_not():
    f = _facts(weight_lb=None, workouts=[WorkoutFact("Legs", 2, 4, 900.0, "Squat", ["Squat"])])
    assert L.pick_beat(f, [])[0] == "scorecard"


def test_the_default_beat_is_the_graded_day_not_a_fallback():
    f = _facts(weight_lb=None, workouts=[])
    beat, why = L.pick_beat(f, [])
    assert beat == "scorecard" and "graded" in why


def test_beat_selection_is_deterministic():
    f, prior = _facts(), [_facts(date="2026-09-11", weight_lb=327.3)]
    assert len({L.pick_beat(f, prior) for _ in range(20)}) == 1


# ── Privacy: what the card may name ───────────────────────────────────────────
def test_vice_streaks_are_a_count_and_never_a_name():
    """The north star's rule is broader than the blocked-category vocabulary:
    *never name substances/vices (… alcohol, etc.)*. The first render of the scorecard
    printed "7d no alcohol" and the vocabulary did not catch it, correctly — that list
    covers one category. So no card names a vice at all."""
    summary = L._vice_summary(_facts())
    assert summary is not None
    for name in ("alcohol", "sweets", "marijuana"):
        assert name not in summary.lower(), f"the vice summary named {name!r}"
    assert "2 of 2 holding" in summary


def test_the_text_screen_covers_every_name_a_layout_can_draw():
    strings = L.gate_strings(_facts(), caption="Day 7 · attempt #17")
    assert "Foundation - Pull - 2 - 6" in strings  # workout title
    assert "Lat Pulldown (Cable)" in strings  # exercise
    assert "Walk 5k" in strings  # missed habit
    assert "Day 7 · attempt #17" in strings  # the caption is screened with the card


def test_the_text_screen_excludes_only_what_no_layout_draws():
    """Vice names are in `item_labels` (the risk registry) and out of the TEXT screen,
    because no layout prints them. Including them held all seven cards over a name none of
    them was going to render — and the per-ITEM screen still sees them."""
    strings = L.gate_strings(_facts())
    assert not any("alcohol" in s.lower() for s in strings)
    assert ("streaks", "No alcohol") in _facts().item_labels(), "the risk registry lost a name it must still track"
    assert L.NEVER_DRAWN_BY_NAME == {"streaks"}, "a class was added to the never-drawn set without review"


# ── The serial, on every card ─────────────────────────────────────────────────
@pytest.mark.parametrize("layout", ["scorecard", "trajectory", "session"])
def test_every_daily_layout_renders_at_portrait(layout):
    pytest.importorskip("PIL")
    img = L.render_beat(layout, _facts(), date_label="Sat 12 Sep", weight_series=[327.3, None, None, None, None, None, 319.7])
    assert img.size == (1080, 1350)


def test_the_weekly_card_renders():
    pytest.importorskip("PIL")
    img = L.reckoning(
        _facts(),
        week_n=1,
        date_label="week 1",
        weight_series=[327.3, None, None, None, None, None, 319.7],
        grade_series=["C", "B-", "B-", "B-", "C-", "C-", "C-"],
        totals={"weight_delta": -7.7, "sessions": 6, "sets": 117},
    )
    assert img.size == (1080, 1350)


def test_the_session_layout_refuses_a_day_with_no_session():
    """A layout that cannot be drawn honestly raises; the handler falls back."""
    with pytest.raises(ValueError):
        L.session(_facts(workouts=[]), date_label="Sun 6 Sep")


# ── The throughline ───────────────────────────────────────────────────────────
def test_cumulative_loss_is_the_number_the_first_cards_missed():
    f = _facts()
    assert f.total_lost_lb == pytest.approx(7.6, abs=0.05)
    assert f.lb_to_goal == pytest.approx(134.7, abs=0.05)
    assert 0 < f.pct_to_goal < 0.1


def test_the_throughline_is_absent_not_zero_when_the_weight_is():
    f = _facts(weight_lb=None)
    assert f.total_lost_lb is None and f.pct_to_goal is None and f.lb_to_goal is None


# ── Charts tell the truth about sparse data ───────────────────────────────────
class _Rec:
    """Records the marks a chart draws, so 'it drew something honest' is assertable."""

    def __init__(self):
        self.lines = 0
        self.dots = 0

    def line(self, pts, **_kw):
        self.lines += 1

    def ellipse(self, *_a, **_kw):
        self.dots += 1

    def text(self, *_a, **_kw):
        pass

    def textlength(self, *_a, **_kw):
        return 40

    def rectangle(self, *_a, **_kw):
        pass

    def rounded_rectangle(self, *_a, **_kw):
        pass


def test_a_gap_is_never_connected():
    """One weigh-in a week: connecting Day 1 to Day 7 would draw a smooth descent through
    five days that were never measured — the prettiest possible lie."""
    rec = _Rec()
    ch.draw_sparkline(rec, [327.3, None, None, None, None, None, 319.7], x=0, y=0, w=900, h=100)
    assert rec.lines == 1, "a data line was drawn across a gap (the baseline is the only line expected)"
    assert rec.dots >= 2, "isolated measurements were not plotted at all"


def test_adjacent_days_do_get_a_line():
    """NEGATIVE CONTROL — the gap rule must not suppress a genuine series."""
    rec = _Rec()
    ch.draw_sparkline(rec, [327.0, 326.0, 325.0, 324.0], x=0, y=0, w=900, h=100)
    assert rec.lines >= 2


def test_a_single_measurement_draws_no_chart():
    rec = _Rec()
    assert ch.draw_sparkline(rec, [None, None, 319.7], x=0, y=0, w=900, h=100) is False
    assert rec.lines == 0


def test_component_bars_skip_absent_scores():
    rec = _Rec()
    end = ch.draw_component_bars(rec, [("nutrition", 29.0), ("sleep", None)], x=0, y=0, w=900)
    assert end == 46, "an absent score drew a bar — a zero-height bar is still a claim"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
