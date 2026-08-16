"""#2756 — a narrated absence span must match the measured one.

Live case: /api/coach_analysis?domain=nutrition said "MacroFactor has been blank
for four days" while /api/character served days_dark: 52 one hop away. Two
halves, both pinned here:

  1. the fact pack: an empty 30-day nutrition window now carries the TRUE
     absence facts (from the partition's newest row, cross-cycle) instead of a
     None the model fills;
  2. the gate: a new `absence_span` grounding class — armed only when the caller
     hands in the measured truth — flags a stated span that disagrees with it
     (labelled positive: the exact live sentence).
"""

import os
import sys
from datetime import date

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence")):
    sys.path.insert(0, _p)

import ai_expert_analyzer_lambda as az  # noqa: E402
from ai import grounded_generation as gg  # noqa: E402
from health.pillar_absence import absence_gate_map, nutrition_absence_facts  # noqa: E402

# ── the gate class, labelled positive first ──────────────────────────────────

LIVE_SENTENCE = "MacroFactor has been blank for four days, so I can't see your meals."


def test_the_live_sentence_is_the_labelled_positive():
    found = gg.absence_span_findings(LIVE_SENTENCE, known_absence_days={"food": 52})
    assert len(found) == 1
    f = found[0]
    assert f["type"] == "absence_span" and f["claimed_days"] == 4 and f["true_days"] == 52


def test_digit_spans_are_flagged_too():
    found = gg.absence_span_findings("There's been no food log for 3 days now.", known_absence_days={"food": 52})
    assert found and found[0]["claimed_days"] == 3


def test_the_honest_span_passes():
    assert gg.absence_span_findings("MacroFactor has been dark for 52 days.", known_absence_days={"food": 52}) == []


def test_one_day_boundary_tolerance():
    assert gg.absence_span_findings("Nothing logged for 51 days.", known_absence_days={"food": 52}) == []


def test_day_spans_without_absence_vocabulary_are_untouched():
    text = "You trained hard for four days and slept 7 hours."
    assert gg.absence_span_findings(text, known_absence_days={"food": 52}) == []


def test_unarmed_gate_stays_silent():
    assert gg.absence_span_findings(LIVE_SENTENCE, known_absence_days=None) == []
    assert gg.absence_span_findings(LIVE_SENTENCE, known_absence_days={}) == []


def test_grounding_findings_wires_the_class():
    found = gg.grounding_findings(LIVE_SENTENCE, allowed={4.0, 52.0}, known_absence_days={"food": 52})
    assert any(f["type"] == "absence_span" for f in found)


# ── the fact pack ─────────────────────────────────────────────────────────────


def test_never_logged_this_cycle_names_the_true_span():
    row = {"sk": "DATE#2026-06-24", "total_calories_kcal": 1900}
    ab = nutrition_absence_facts(row, days_in_experiment=6, experiment_start="2026-08-10", today=date(2026, 8, 15))
    assert ab["absence_days_dark"] == 52
    assert ab["absence_transition"] == "never_logged_this_cycle"
    assert "52 days dark" in ab["note_absence"] and "never guess a smaller number" in ab["note_absence"]


def test_paused_within_cycle():
    ab = nutrition_absence_facts({"sk": "DATE#2026-08-12"}, 6, "2026-08-10", today=date(2026, 8, 15))
    assert ab["absence_transition"] == "paused" and ab["absence_days_dark"] == 3


def test_truly_never_logged():
    ab = nutrition_absence_facts(None, 6, "2026-08-10", today=date(2026, 8, 15))
    assert ab["absence_transition"] == "never_logged" and ab["absence_days_dark"] is None


def test_empty_window_fact_pack_carries_the_absence_fields(monkeypatch):
    monkeypatch.setattr(az, "_query_source", lambda s, a, b: [])
    monkeypatch.setattr(az, "_latest_item", lambda s: {"sk": "DATE#2026-06-24"})
    data = az.gather_data_for_expert("nutrition")
    assert data["absence_days_dark"] is not None and data["absence_days_dark"] >= 45
    assert data["days_since_last_food_log"] == data["absence_days_dark"]
    assert "days dark" in data["note"]


def test_gate_map_arms_only_on_absence():
    assert absence_gate_map({"absence_days_dark": 52}) == {"food": 52}
    assert absence_gate_map({"avg_calories": 1900}) is None
    assert absence_gate_map(None) is None
