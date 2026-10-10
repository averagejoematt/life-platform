"""tests/test_editors_desk_4534.py — the editor's desk acceptance boxes (#4534).

Box 1: a schema-valid budget on a fixture week passes the desk end to end; a budget whose lead repeats
       the thread that led the previous two weeks is rejected — by the desk, not only by the ledger.
Box 2: a fixture week with good data and a journal gap does not lead on the gap. The rubric says so in
       prose; ``story_desk.absence_lead_findings`` is what holds the model to it in code.

Every rejection has a mutation control (the same fixture, the one fact changed, passes), and
``run_desk`` is driven with a fake ``invoke`` so the corrective retry is proven to fire.
"""

from __future__ import annotations

import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import pytest  # noqa: E402
from ai import structured_json  # noqa: E402
from content import story_desk, story_ledger  # noqa: E402

ROSTER = ("sleep_coach", "nutrition_coach", "mind_coach", "physical_coach")

# A good week: the scale down 2.2 lb, every programmed session done, protein over the floor, recovery up —
# and no journal entry in the window. The gap is the only "absence" in it.
GOOD_WEEK_WITH_JOURNAL_GAP = {
    "week": 3,
    "window": {"start": "2026-09-16", "end": "2026-09-22"},
    "roster": [{"coach_id": c} for c in ROSTER],
    "weight": {"start_lbs": 318.4, "end_lbs": 316.2, "change_lbs": -2.2, "plan_pace_lbs_per_week": -1.5},
    "training": {"sessions": 6, "programmed_sessions": 6, "matched_prescription": 6},
    "nutrition": {"protein_avg_g": 174, "protein_floor_g": 170, "not_yet_exported_dates": []},
    "recovery": {"avg": 71, "prior_week_avg": 64},
    "journal": {"entries_in_window": 0, "privacy": "journal content is off the record; only its presence is a fact here"},
    "export_watermarks": {"withings": {"kind": "daily", "last_covered_date": "2026-09-22", "not_yet_exported_dates": []}},
    "predictions": {"graded_this_week": []},
}


def _ledger_after_two_weeks_leading(thread_id: str) -> dict:
    led = story_ledger.empty_ledger()
    for w, coach in ((1, "physical_coach"), (2, "nutrition_coach")):
        led = story_ledger.apply_budget(
            led,
            {
                "lead": {"thread_id": thread_id, "angle": "", "why": "", "evidence": []},
                "thread_actions": [{"thread_id": thread_id, "action": "open" if w == 1 else "advance", "title": "t", "note": ""}],
                "bet_scored": {"result": "none", "note": ""},
                "bet": {"claim": "", "metric": "", "rule": "", "window_days": 7},
                "featured_coaches": [coach],
            },
            week=w,
            date=f"2026-09-0{w}",
            title="t",
        )
    return led


def _fixture_budget(ledger: dict, *, lead_thread="weight_trend", angle="the scale is ahead of the plan's pace", evidence=None) -> dict:
    """A full, schema-valid week-3 budget for the good week."""
    spine = ledger["spine"]["throughlines"][0]["id"]
    return {
        "lead": {
            "thread_id": lead_thread,
            "angle": angle,
            "why": "a change: the third straight week down, faster than plan",
            "evidence": evidence if evidence is not None else ["weight 318.4 to 316.2 lb (-2.2) against a -1.5 lb/week plan"],
        },
        "secondary": [
            {
                "thread_id": "programme_adherence",
                "angle": "every programmed session done",
                "why": "human interest",
                "evidence": ["6 of 6 sessions matched the prescription"],
            }
        ],
        "omitted": [{"item": "no journal entries this week", "why": "an absence with no consequence in the data"}],
        "tone": {"register": "encouraged", "why": "weight, training and recovery all moved the right way"},
        "featured_coaches": ["sleep_coach"],
        "coach_angle": "recovery up from 64 to 71",
        "thread_actions": [
            {"thread_id": "ramp_overshoot", "action": "hold", "title": "", "note": "nothing new this week"},
            {"thread_id": lead_thread, "action": "open", "title": "the weight trend", "note": ""},
        ],
        "bet_scored": {"result": "none", "note": ""},
        "bets_scored": [],
        "bet": {"claim": "recovery averages 70 or more next week", "metric": "recovery.avg", "rule": ">= 70", "window_days": 7},
        "beats_used": ["ahead of pace"],
        "arc_updates": [{"who": "sleep_coach", "line": "her recovery call is paying off"}],
        "title_ideas": ["Ahead of the plan"],
        "cold_reader_context": "A man is trying to lose weight over a year, in public.",
        "top_line": "He is down again this week. The question is whether the pace holds.",
        "throughline_advanced": spine,
        "cliffhanger": "Does recovery stay above 70 through Sunday?",
        "coach_asks": [],
        "asks_followed_up": [],
        "owner_lines_to_use": [],
        "data_caveats": [],
    }


def _reply(budget: dict) -> dict:
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(budget)}]}


# ── box 1: schema-valid budget on fixtures; a repeated two-week lead is rejected ─────────────────


def test_a_schema_valid_fixture_budget_passes_the_desk():
    led = _ledger_after_two_weeks_leading("ramp_overshoot")
    budget = _fixture_budget(led)
    assert structured_json.schema_findings(budget, story_desk.BUDGET_SCHEMA) == []
    assert story_desk.validate(budget, GOOD_WEEK_WITH_JOURNAL_GAP, led, week=3) == []
    calls = []

    def invoke(body, model):
        calls.append(body)
        return _reply(budget)

    assert story_desk.run_desk(GOOD_WEEK_WITH_JOURNAL_GAP, led, week=3, invoke=invoke, log=lambda m: None) == budget
    assert len(calls) == 1


def test_a_budget_whose_lead_repeats_a_two_week_lead_is_rejected_by_the_desk():
    led = _ledger_after_two_weeks_leading("ramp_overshoot")
    repeat = _fixture_budget(led, lead_thread="ramp_overshoot", angle="he trained past the ramp again")
    repeat["thread_actions"] = [{"thread_id": "ramp_overshoot", "action": "advance", "title": "", "note": ""}]
    assert structured_json.schema_findings(repeat, story_desk.BUDGET_SCHEMA) == []  # the schema cannot see it
    assert any("led 2 weeks running" in f for f in story_desk.validate(repeat, GOOD_WEEK_WITH_JOURNAL_GAP, led, week=3))
    # run_desk: the repeat is sent back once, the corrected budget is what comes out
    good = _fixture_budget(led)
    replies = [_reply(repeat), _reply(good)]
    calls = []

    def invoke(body, model):
        calls.append(copy.deepcopy(body))
        return replies.pop(0)

    assert story_desk.run_desk(GOOD_WEEK_WITH_JOURNAL_GAP, led, week=3, invoke=invoke, log=lambda m: None) == good
    assert "led 2 weeks running" in calls[1]["messages"][-1]["content"]
    # and twice running is a failure, never a published repeat
    with pytest.raises(RuntimeError, match="failed validation twice"):
        story_desk.run_desk(GOOD_WEEK_WITH_JOURNAL_GAP, led, week=3, invoke=lambda body, model: _reply(repeat), log=lambda m: None)


# ── box 2: a good week with a journal gap does not lead on the gap ───────────────────────────────


def test_a_good_week_with_a_journal_gap_does_not_lead_on_the_gap():
    led = _ledger_after_two_weeks_leading("ramp_overshoot")
    gap = _fixture_budget(
        led,
        lead_thread="journal_gap",
        angle="a week without a word in the journal",
        evidence=["0 journal entries in the window", "weight 318.4 to 316.2 lb"],
    )
    assert structured_json.schema_findings(gap, story_desk.BUDGET_SCHEMA) == []
    findings = story_desk.validate(gap, GOOD_WEEK_WITH_JOURNAL_GAP, led, week=3)
    assert any("journal" in f and "never a lead" in f for f in findings)
    # the desk sends it back and keeps the data lead
    good = _fixture_budget(led)
    replies = [_reply(gap), _reply(good)]
    out = story_desk.run_desk(GOOD_WEEK_WITH_JOURNAL_GAP, led, week=3, invoke=lambda body, model: replies.pop(0), log=lambda m: None)
    assert out["lead"]["thread_id"] == "weight_trend"
    # mutation control: the gap may still be mentioned in the lead's "why" and in "omitted" without a finding
    assert not story_desk.absence_lead_findings(_fixture_budget(led), GOOD_WEEK_WITH_JOURNAL_GAP)


def test_every_spelling_of_a_journal_lead_is_refused():
    missed = []
    for thread_id, angle in (("journaling", "he stopped writing"), ("silent_diary", ""), ("week_off", "nothing in his journal all week")):
        b = {"lead": {"thread_id": thread_id, "angle": angle, "why": "", "evidence": ["weight 318.4 to 316.2 lb"]}}
        if not story_desk.absence_lead_findings(b, GOOD_WEEK_WITH_JOURNAL_GAP):
            missed.append((thread_id, angle))
    assert missed == []


def test_an_absence_leads_only_with_a_grounded_data_consequence():
    absence = {"thread_id": "rest_days_skipped", "angle": "he skipped both rest days", "why": ""}
    # no consequence: evidence restates the absence, or cites a figure the dossier does not hold
    for ev in ([], ["0 rest days taken"], ["recovery fell to 52"]):
        assert story_desk.absence_lead_findings({"lead": {**absence, "evidence": ev}}, GOOD_WEEK_WITH_JOURNAL_GAP), ev
    # mutation control: a grounded consequence in the data lets it lead
    with_consequence = {"lead": {**absence, "evidence": ["recovery averaged 71 against 64 the week before"]}}
    assert not story_desk.absence_lead_findings(with_consequence, GOOD_WEEK_WITH_JOURNAL_GAP)


def test_an_absence_in_a_not_yet_exported_source_never_leads():
    lagging = copy.deepcopy(GOOD_WEEK_WITH_JOURNAL_GAP)
    lagging["nutrition"]["not_yet_exported_dates"] = ["2026-09-20", "2026-09-21"]
    lead = {"lead": {"thread_id": "food_log_gap", "angle": "the food log went quiet", "why": "", "evidence": ["protein 174 g"]}}
    assert any("not yet exported" in f for f in story_desk.absence_lead_findings(lead, lagging))
    # mutation control: the same lead against a fully exported window is judged on its consequence instead
    assert not story_desk.absence_lead_findings(lead, GOOD_WEEK_WITH_JOURNAL_GAP)
