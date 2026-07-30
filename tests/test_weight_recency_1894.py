"""tests/test_weight_recency_1894.py — #1894: a stale weigh-in must not be narrated
as today's.

The live failure (Day 1 of cycle 11): Dr. Victor Reyes' card on the coaching door
opened **"Day 1 weight is 317.61 lbs"** — the pre-genesis 2026-07-22 weigh-in —
while home and /api/vitals served 321.09. A cold reader crossing home → coaching
hit a 3.5 lb contradiction on the experiment's single most important number.

Root cause (`gather_data_for_expert`, the `physical` branch):

    weights = [float(w["weight_lbs"]) for w in weight_items if w.get("weight_lbs")]
    current_weight = weights[-1] if weights else None

The newest reading in a 30-day window, handed to the prompt as `current_weight_lb`
with **no date and no recency check**. On Day 1 the real weigh-in had not ingested
yet (03:05Z the following morning), so the analyzer was handed the Jul-22 value and
the coach narrated it as the Day-1 figure.

Why the existing backstop could not catch it: the Phase-3 grounding pass grounds the
narrative against THIS SAME fact set, so a stale fact is a "grounded" fact. Freshness
has to be established where the fact is assembled, not where the prose is checked.

The fix carries the reading's own date and age alongside the value, marks it stale,
and — via `build_prompt` — instructs the coach not to attach a day label to it.
These tests pin all three: the data shape, the staleness flag, and the prompt rule.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from intelligence import ai_expert_analyzer_lambda as ana  # noqa: E402


def _ago(days: int) -> str:
    """A date N days before the analyzer's own 'today'.

    Deliberately RELATIVE. gather_data_for_expert reads
    datetime.now(timezone.utc) directly, so a hardcoded fixture date would make
    every age assertion drift by one each midnight — the golden-test wall-clock
    time bomb. Deriving from the same clock keeps these tests true on any day.
    """
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


TODAY = _ago(0)


def _rows(*pairs):
    """(date, lbs) -> the DDB row shape gather_data_for_expert sees."""
    return [{"sk": f"DATE#{d}", "weight_lbs": w} for d, w in pairs]


def _physical(monkeypatch, rows):
    """Run the physical branch against canned withings rows."""
    monkeypatch.setattr(ana, "_query_source", lambda source, start, end: rows if source == "withings" else [])
    monkeypatch.setattr(ana, "_latest_item", lambda source: None)
    return ana.gather_data_for_expert("physical")


# ── the data shape ────────────────────────────────────────────────────────────


def test_current_weight_carries_its_reading_date(monkeypatch):
    """The value alone is not enough — the date must travel with it."""
    d = _physical(monkeypatch, _rows((_ago(7), 320.0), (_ago(5), 317.61)))
    assert d["current_weight_lb"] == pytest.approx(317.61)
    assert d["current_weight_as_of"] == _ago(5), "the reading date must reach the prompt"


def test_the_live_1894_shape_is_flagged_stale(monkeypatch):
    """Exactly the incident shape: the newest reading is 5 days old when the analyzer runs."""
    d = _physical(monkeypatch, _rows((_ago(7), 320.0), (_ago(5), 317.61)))
    assert d["current_weight_is_stale"] is True
    assert d["current_weight_age_days"] == 5


def test_a_todays_reading_is_not_stale(monkeypatch):
    """The guard must not cry wolf on fresh data."""
    d = _physical(monkeypatch, _rows((_ago(2), 320.0), (TODAY, 321.09)))
    assert d["current_weight_is_stale"] is False
    assert d["current_weight_age_days"] == 0
    assert d["current_weight_lb"] == pytest.approx(321.09)


def test_newest_reading_wins_regardless_of_row_order(monkeypatch):
    """weights[-1] assumed the query returned sorted rows. Sort explicitly."""
    d = _physical(monkeypatch, _rows((TODAY, 321.09), (_ago(7), 320.0), (_ago(5), 317.61)))
    assert d["current_weight_lb"] == pytest.approx(321.09)
    assert d["current_weight_as_of"] == TODAY


def test_delta_reports_its_real_span_not_an_assumed_four_weeks(monkeypatch):
    """The old field was named weight_change_4wk while spanning whatever existed —
    with two readings two days apart it still called itself a 4-week change."""
    d = _physical(monkeypatch, _rows((_ago(2), 322.0), (TODAY, 321.0)))
    assert d["weight_change_observed"] == pytest.approx(-1.0)
    assert d["weight_change_span_days"] == 2
    assert "weight_change_4wk" not in d, "the misleading fixed-window name must be gone"


def test_no_readings_is_honest_absence(monkeypatch):
    d = _physical(monkeypatch, [])
    assert d["current_weight_lb"] is None
    assert d["current_weight_as_of"] is None
    assert d["current_weight_is_stale"] is False
    assert d["weight_readings"] == 0


# ── the prompt actually uses the flag ─────────────────────────────────────────


def test_prompt_forbids_day_labelling_a_stale_weight():
    """Data alone changes nothing if the prompt ignores it."""
    data = {
        "expert_key": "physical",
        "current_weight_lb": 317.61,
        "current_weight_as_of": "2026-07-22",
        "current_weight_age_days": 5,
        "current_weight_is_stale": True,
        "weight_change_span_days": 2,
    }
    prompt = ana.build_prompt("physical", dict(data), days_in_experiment=1, week_number=1)
    assert "WEIGHT DATA RECENCY" in prompt
    assert "2026-07-22" in prompt
    assert "Day 1 weight" in prompt, "the prompt must name the exact phrasing it is forbidding"


def test_prompt_stays_quiet_when_the_weight_is_fresh():
    """No nagging block on healthy data — the same discipline as the movement guard."""
    data = {
        "expert_key": "physical",
        "current_weight_lb": 321.09,
        "current_weight_as_of": TODAY,
        "current_weight_age_days": 0,
        "current_weight_is_stale": False,
    }
    prompt = ana.build_prompt("physical", dict(data), days_in_experiment=1, week_number=1)
    assert "WEIGHT DATA RECENCY" not in prompt


# ── the cross-surface guard (acceptance criterion 4) ─────────────────────────
# No single surface was internally wrong in the live incident — each was
# self-consistent. Only comparing home/cockpit against the coaching door reveals
# it, which is exactly why every per-surface guard already in place passed.


def _assess():
    # weight_truth_qa is a pure LEAF module — no AWS, no network, no clock, and no
    # import-time env vars. That is the point of the split: qa_smoke_lambda resolves
    # S3_BUCKET/EMAIL_* at import and would otherwise drag a bare KeyError into
    # collection here (the import-time-frozen-globals trap).
    from operational.weight_truth_qa import assess_cross_surface_weight

    return assess_cross_surface_weight


def test_cross_surface_catches_the_live_1894_contradiction():
    ok, msg = _assess()(
        {"weight_lbs": 321.09},
        [{"name": "Dr. Victor Reyes", "position_summary": "Day 1 weight is 317.61 lbs, and the deficit is holding."}],
    )
    assert ok is False
    assert "317.61" in msg and "321.09" in msg, f"the message must name both figures: {msg}"


def test_cross_surface_passes_when_surfaces_agree():
    ok, msg = _assess()({"weight_lbs": 316.0}, [{"name": "Dr. Victor Reyes", "position_summary": "He is at 316.3 lbs this week."}])
    assert ok is True, msg


def test_cross_surface_ignores_non_bodyweight_figures():
    """A '10 lbs' dumbbell reference is not a claim about his bodyweight."""
    ok, msg = _assess()(
        {"weight_lbs": 316.0}, [{"name": "Dr. Sarah Chen", "position_summary": "Add 10 lbs to the bar and hold 45 lbs dumbbells."}]
    )
    assert ok is True, msg


def test_cross_surface_absence_is_a_clean_pass():
    """Pre-start / no weigh-in has nothing to contradict (ADR-104)."""
    assert _assess()({"weight_lbs": None}, [{"position_summary": "anything"}])[0] is True
    assert _assess()({}, [])[0] is True
    assert _assess()({"weight_lbs": 316.0}, [])[0] is True


def test_cross_surface_tolerates_rounding_but_not_a_stale_cycle_figure():
    a = _assess()
    assert a({"weight_lbs": 316.0}, [{"position_summary": "316.4 lbs"}])[0] is True, "rounding must not fire"
    assert a({"weight_lbs": 316.0}, [{"position_summary": "321.1 lbs"}])[0] is False, "a 5 lb gap must fire"
