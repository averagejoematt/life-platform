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
    assert c.tts_clean("September 15th, 2026 \\\n Day 10\t— of the experiment") == "September 15th, 2026 — Day 10 — of the experiment"


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


def test_a_mangled_dash_is_restored_not_dropped():
    assert c.tts_clean("Before we get into it \\ the open bet") == "Before we get into it — the open bet"


# ── #4545: every craft rule carries a red-team fixture and a mutation control ──────────────────────────────


def _of(findings, needle):
    return [f for f in findings if needle in f]


def test_a_day_by_day_series_paragraph_breaks_the_figure_cap():
    # the editor's flagged shape: a week told day by day in wearable readings
    series = "His recovery read 80, 86, 99, 77 and 89 across the week while his HRV held near 56.8."
    summary = "His recovery averaged 86 across the week, with one outlier at 99."
    assert _of(c.chronicle_findings(series, week=0), "figures (max 3)")
    assert not _of(c.chronicle_findings(summary, week=0), "figures (max 3)")


def test_the_chronicle_length_band():
    short = "He trained on Day 24 and the scale went down. " * 20  # ~200 words: the recap-only draft
    in_band = "He trained on Day 24 and the scale went down again. " * 95  # ~1,045 words
    assert _of(c.chronicle_findings(short, week=0), "the standard is 850-1300")
    assert not _of(c.chronicle_findings(in_band, week=0), "the standard is")


def test_the_opening_names_the_day():
    no_day = "Matthew had not taken a rest since the experiment began. The scale kept going down.\n\nMore."
    with_day = "On Day 24 Matthew had not taken a rest since the experiment began. The scale kept going down.\n\nMore."
    assert _of(c.chronicle_findings(no_day, week=4), "which day of the experiment")
    assert not _of(c.chronicle_findings(with_day, week=4), "which day of the experiment")


def test_the_opening_says_which_way_the_scale_went():
    # the red team's prologue complaint: a stranger got a recovery score before they learned how he is
    no_weight = "Day 24, and Matthew had trained twenty-three days straight. His recovery read high.\n\nMore."
    with_weight = "Day 24, and Matthew had trained twenty-three days straight. The scale was down fifteen pounds.\n\nMore."
    assert _of(c.chronicle_findings(no_weight, week=4, weight_known=True), "which way the scale went")
    assert not _of(c.chronicle_findings(with_weight, week=4, weight_known=True), "which way the scale went")
    # a week with no weigh-in cannot be held to it
    assert not _of(c.chronicle_findings(no_weight, week=4, weight_known=False), "which way the scale went")


def test_the_top_line_is_plain_english():
    jargon = "Day 24: his WHOOP recovery score hit 99 while HRV rose 12 ms and RHR fell 3 bpm against a 0.4 lb/day slope."
    plain = "Day 24, fifteen pounds down, and he has not taken a rest day. The coaches want one by Sunday."
    found = c.top_line_findings(jargon)
    assert _of(found, "'WHOOP'") and _of(found, "'HRV'") and _of(found, "'RHR'") and _of(found, "slope")
    assert _of(found, "figures (max 3)")
    assert c.top_line_findings(plain) == []
    long = "He trained again. " * 3 + "And again."
    assert _of(c.top_line_findings(long), "sentences (max 2)")


def test_the_spoken_figure_caps_per_turn_and_per_episode():
    # the producer's count: four to eight figures per spoken minute
    dense = [{"speaker": "coach", "line": "Recovery went 80, 86, 99, 77 and 89."}]
    sparse = [{"speaker": "coach", "line": "Recovery averaged about 86, with one morning at 99."}]
    assert _of(c.episode_findings(dense), "figures (max 3)")
    assert not _of(c.episode_findings(sparse), "figures (max 3)")
    many = [{"speaker": "coach", "line": "It was 81, 82 and 83."} for _ in range(11)]  # 33 figures, 3 per turn
    few = many[:9]  # 27 figures
    assert _of(c.episode_findings(many), "across the episode")
    assert not _of(c.episode_findings(few), "across the episode")


def test_the_episode_length_band_cold_open_and_elena_turns():
    cold_open = {"speaker": "elena", "line": "He walked into the gym again. " * 15}  # 90 words
    tight_open = {"speaker": "elena", "line": "He walked into the gym again on a morning he could have rested."}
    filler = {"speaker": "coach", "line": "That is a fair read of the week and I stand by it. " * 10}  # 130 words
    assert _of(c.episode_findings([cold_open]), "cold open runs past 70 words")
    long_elena = {"speaker": "elena", "line": "That is a fair read of the week and I stand by it. " * 10}  # 130 words
    assert _of(c.episode_findings([tight_open, long_elena]), "Elena's turn 1 runs 130 words")
    assert not _of(c.episode_findings([tight_open, filler]), "Elena's turn")  # the guest is not held to Elena's cap
    assert not _of(c.episode_findings([tight_open]), "cold open")
    assert _of(c.episode_findings([tight_open]), "the standard is 1150-1550")
    assert not _of(c.episode_findings([tight_open] + [filler] * 11), "the standard is")


def test_the_podcast_names_its_recurring_segments_in_order():
    lead = {"speaker": "elena", "line": "Marcus, the protein story first."}
    wrong = {"speaker": "elena", "line": "Time for the call I got wrong. Marcus, yours."}
    unknown = {"speaker": "elena", "line": "And what we don’t know yet: whether he rests by Sunday."}
    assert c.episode_findings([lead, wrong, unknown], segments=True) == [
        f for f in c.episode_findings([lead, wrong, unknown]) if "segment" not in f
    ]
    assert not _of(c.episode_findings([lead, wrong, unknown], segments=True), "segment")
    assert _of(c.episode_findings([lead, unknown], segments=True), "never names the segment 'the call I got wrong'")
    assert _of(c.episode_findings([lead, wrong], segments=True), 'never names the segment "what we don\'t know yet"')
    assert _of(c.episode_findings([lead, unknown, wrong], segments=True), "runs before")
    # the prologue (week 0) carries no segments
    assert not _of(c.episode_findings([lead], segments=False), "segment")


def test_the_scoreboard_is_the_dossiers_numbers_not_the_models():
    dossier = {
        "window": {"experiment_days": "Day 1 to Day 3"},
        "weight": {"first_weigh_in": {"lbs": 327.3}, "week_end": {"lbs": 327.3}},
        "predictions": {
            "record_to_date_by_coach": {
                "Dr. Marcus Webb": {"right": 0, "wrong": 9},
                "Dr. Nathan Reeves": {"right": 5, "wrong": 2},
                "Dr. Nobody": {"right": 0, "wrong": 0},
            }
        },
    }
    sb = c.scoreboard(dossier, {"bets": [{"result": "open"}]})
    line = c.scoreboard_line(sb)
    assert "Day 3" in line and "327.3 lb at the first weigh-in" in line and "→" not in line
    assert "on-air bets" not in line  # an open bet is not a record
    assert [x["coach"] for x in sb["coach_board"]] == ["Nathan Reeves", "Marcus Webb"]  # best record first; no-call coaches dropped
    assert "Reeves 5–2, Webb 0–9" in line


def test_the_desk_must_advance_a_named_season_throughline():
    from content import story_desk

    ledger = {"spine": c.season_spine()}
    base = {"featured_coaches": ["c1"], "cliffhanger": "Will he rest by Sunday?"}
    dossier = {"roster": [{"coach_id": "c1"}]}
    off_spine = story_desk.validate({**base, "throughline_advanced": "a_new_idea"}, dossier, ledger, week=2)
    on_spine = story_desk.validate({**base, "throughline_advanced": "the_streak"}, dossier, ledger, week=2)
    assert _of(off_spine, "throughline_advanced")
    assert not _of(on_spine, "throughline_advanced")
    assert {t["id"] for t in c.season_spine()["throughlines"]} >= {"the_streak"}


def test_the_desk_pipeline_runs_the_new_craft_gates(monkeypatch):
    from content import story_pipeline, story_writers

    monkeypatch.setattr(story_writers, "fact_check", lambda *a, **k: [])
    dossier = {"weight": {"available": True}}
    g = story_pipeline._Gates(3, dossier, {}, {})
    assert g.weight_known is True
    assert _of(g.dek("Day 24: his HRV rose."), "jargon")
    assert _of(g.episode({"turns": [{"speaker": "elena", "line": "Hello."}]}, "end_turn"), "never names the segment")
    md = '"T"\n\nDay 24, and Matthew had trained twenty-three days straight. His recovery read high.\n\nMore.'
    assert _of(g.post(md, "end_turn"), "which way the scale went")


def test_lines_already_heard_are_findings():
    prev = {3: "MAX: One good scan is one good scan, and fast is fine if the protein holds."}
    assert c.repeat_findings("MARCUS: Look, one good scan is one good scan, and fast is fine if it holds.", prev)
    assert c.repeat_findings("MARCUS: A single scan tells us little on its own.", prev) == []
