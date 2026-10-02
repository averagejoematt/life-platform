"""tests/test_story_craft.py — the craft standard's gates (#4545), each fixtured on what the 2026-10-01 red
team actually flagged in the first rebuilt season, with a mutation control showing the passing case."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from content import story_craft as c  # noqa: E402


def test_the_red_team_tics_are_banned():
    for tic in [
        "The question is whether the structure holds.",
        "For a reader arriving here cold: Matthew is tracking a year-long attempt.",
        "Good to be here, Elena. And I'll say upfront — this is strange.",
        "That's my actual read.",
        "Wrong, and I want to be plain about it.",
    ]:
        assert c.banned(tic), tic
    assert c.banned("He walked eight miles on Sunday.") == []


def test_more_than_one_antithesis_is_a_finding():
    one = "The plan's note is no longer a reassurance — it is a deadline."
    two = one + " The miss is not a failure; it is the most honest signal of the week."
    assert not [x for x in c.banned(one) if "constructions" in x]
    assert [x for x in c.banned(two) if "constructions" in x]


def test_figure_density_ignores_the_calendar():
    assert c.figures("On September 25th, Day 20, at 5:12 in 2026") == 0
    assert c.figures("Recovery 80, 86, 99, 77 and 89; HRV 56.8") == 6


def test_opening_on_a_date_or_wearable_reading_is_flagged():
    body = "On the morning of September 25th — Day 20 — his WHOOP returned 99 percent.\n\nMore."
    assert any("opens on a date" in x for x in c.chronicle_findings(body, week=4))
    good = "Twenty-three days into the experiment, Day 24, Matthew had not taken a day off.\n\nMore."
    assert not any("opens on a date" in x for x in c.chronicle_findings(good, week=4))


def test_a_callback_must_match_the_week_it_recalls():
    prev = {1: "On Day 2 his recovery read 76 percent while he rated his mood 2 out of 10."}
    bad = "The gap that defined Week 1 — a 64 percent recovery score on a morning he reported 3 out of 10."
    good = "The gap that defined Week 1 — 76 percent recovery against a mood of 2 out of 10."
    assert c.callback_findings(bad, prev)
    assert c.callback_findings(good, prev) == []


def test_the_quote_gate_holds_quotes_to_the_stored_words():
    dossier = {
        "coaches_this_week": [
            {
                "latest_public_summary": "The vulnerability is structural: dinner carries roughly 85g of his daily total — nearly half the anchor — with no concrete backup plan if it gets disrupted.",
                "latest_key_recommendation": "",
            }
        ]
    }
    corpus = c.quote_corpus(dossier)
    exact = '> "The vulnerability is structural: dinner carries roughly 85g of his daily total — nearly half the anchor — with no concrete backup plan if it gets disrupted."'
    altered = '> "Dinner is carrying the majority of his daily protein total — nearly half the anchor — with no concrete backup plan."'
    trimmed = '> "The vulnerability is structural … with no concrete backup plan if it gets disrupted."'
    assert c.quote_findings(exact, corpus) == []
    assert c.quote_findings(trimmed, corpus) == []
    assert c.quote_findings(altered, corpus)


def test_tts_clean_removes_the_script_artifacts():
    assert c.tts_clean("September 15th, 2026 \\\n Day 10\t— of the experiment") == "September 15th, 2026 Day 10 — of the experiment"


def test_the_scoreboard_is_code_rendered():
    dossier = {
        "window": {"experiment_days": "Day 18 to Day 24"},
        "weight": {"first_weigh_in": {"lbs": 327.3}, "week_end": {"lbs": 312.3}, "total_change_lbs": -15.0},
        "training": {"consecutive_training_days_through_week_end": 23},
        "predictions": {
            "record_to_date_by_coach": {"Dr. Marcus Webb": {"right": 0, "wrong": 9}, "Dr. Nathan Reeves": {"right": 5, "wrong": 2}}
        },
    }
    ledger = {"bets": [{"result": "wrong"}, {"result": "right"}]}
    line = c.scoreboard_line(c.scoreboard(dossier, ledger))
    assert "Day 24" in line and "327.3 → 312.3 lb" in line and "23 straight training days" in line and "on-air bets 1–1" in line
