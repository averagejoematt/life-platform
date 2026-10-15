"""tests/test_story_craft.py — the craft standard's gates (#4545), each fixtured on what the 2026-10-01 red
team actually flagged in the first rebuilt season, with a mutation control showing the passing case."""

from __future__ import annotations

import datetime as _dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from content import (
    story_craft as c,  # noqa: E402
    story_dossier,  # noqa: E402
)


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
        "training": {"consecutive_loaded_lifting_days_through_week_end": 4},
        "predictions": {
            "record_to_date_by_coach": {"Dr. Marcus Webb": {"right": 0, "wrong": 9}, "Dr. Nathan Reeves": {"right": 5, "wrong": 2}}
        },
    }
    ledger = {"bets": [{"result": "wrong"}, {"result": "right"}]}
    line = c.scoreboard_line(c.scoreboard(dossier, ledger))
    assert "Day 24" in line and "327.3 → 312.3 lb" in line and "4 straight lifting days" in line and "on-air bets 1–1" in line


# ── #4678: the story's streak is the loaded-lifting streak, never the any-Hevy-row count ──────────
#
# The dossier counted every day with ANY Hevy row — treadmill, bike and walking blocks included — and
# the scoreboard printed it as "N straight training days" beside a season throughline that asks about a
# rest day. Same class as #4067 (joints critic) and #4411 (routine notes), on a reader surface.

_WK_4678 = {"start": "2026-10-14", "end": "2026-10-20"}


def _hevy_row_4678(days_before_end: int, *, loaded: bool) -> dict:
    day = (_dt.date.fromisoformat(_WK_4678["end"]) - _dt.timedelta(days=days_before_end)).isoformat()
    lift = [{"name": "Squat (Barbell)", "sets": [{"type": "normal", "weight_kg": 80, "reps": 5}]}]
    cardio = [{"name": "Treadmill", "sets": [{"duration_sec": 3600}]}, {"name": "Stretching", "sets": [{"duration_sec": 900}]}]
    return {
        "sk": f"DATE#{day}#WORKOUT#w{days_before_end}",
        "date": day,
        "title": "Foundation Push" if loaded else "Engine",
        "start_time": f"{day}T15:00:00Z",
        "exercises": lift if loaded else cardio,
    }


def _training_4678(monkeypatch, hevy_rows):
    def _rows(table, source, start, end):  # the range reader, honoured: the week's sessions vs. the look-back trail
        return [r for r in hevy_rows if start <= r["date"] <= end] if source == "hevy" else []

    monkeypatch.setattr(story_dossier, "_rows", _rows)
    monkeypatch.setattr(story_dossier, "_days", lambda table, source, start, end: {})
    return story_dossier._training(None, _WK_4678)


def _fifteen_active_four_lifting():
    """15 consecutive days with a Hevy row through the week's end: the last 4 are loaded lifts, the 11 before are cardio."""
    return [_hevy_row_4678(n, loaded=n < 4) for n in range(15)]


def test_fifteen_active_days_with_four_lifting_days_is_not_fifteen_straight_training_days(monkeypatch):
    """The issue's fixture. Mutation control: restore the any-Hevy-row count in `story_dossier._training`
    (count every date with a row) — the line reads 15 and every assertion below reds."""
    t = _training_4678(monkeypatch, _fifteen_active_four_lifting())
    assert t["session_count"] == 7  # the week itself is seven Hevy sessions: the fixture really is an every-day week
    assert t["consecutive_loaded_lifting_days_through_week_end"] == 4
    assert "consecutive_training_days_through_week_end" not in t  # the ambiguous name is gone, not aliased
    line = c.scoreboard_line(c.scoreboard({"window": {"experiment_days": "Day 38 to Day 44"}, "training": t}, {}))
    assert "15 straight training days" not in line
    assert not re.search(r"\b15\b", line), line  # the active-day count reaches the reader under no label
    assert "4 straight lifting days" in line
    assert "training days" not in line


def test_a_cardio_day_at_the_week_end_breaks_the_lifting_streak_and_the_scoreboard_says_nothing(monkeypatch):
    """Mutation control: count cardio-only rows as loaded (drop the `is_loaded_session` filter) — the streak reads 15."""
    rows = [_hevy_row_4678(0, loaded=False)] + [_hevy_row_4678(n, loaded=True) for n in range(1, 15)]
    t = _training_4678(monkeypatch, rows)
    assert t["consecutive_loaded_lifting_days_through_week_end"] == 0
    line = c.scoreboard_line(c.scoreboard({"window": {"experiment_days": "Day 9 to Day 15"}, "training": t}, {}))
    assert "straight" not in line and line == "Day 15"


def test_one_lifting_day_is_not_a_streak_on_the_scoreboard():
    """Mutation control: render at any truthy count — the line reads "1 straight lifting days"."""
    sb = c.scoreboard({"training": {"consecutive_loaded_lifting_days_through_week_end": 1}}, {})
    assert sb["loaded_lifting_streak_days"] == 1 and "straight" not in c.scoreboard_line(sb)
    assert "2 straight lifting days" in c.scoreboard_line({"loaded_lifting_streak_days": 2})


def test_a_tombstoned_hevy_row_is_not_a_lifting_day(monkeypatch):
    """Mutation control: drop the tombstone filter on the streak rows — the superseded row extends the streak to 3."""
    rows = [_hevy_row_4678(0, loaded=True), _hevy_row_4678(1, loaded=True), {**_hevy_row_4678(2, loaded=True), "tombstone": True}]
    assert _training_4678(monkeypatch, rows)["consecutive_loaded_lifting_days_through_week_end"] == 2


def test_every_session_says_whether_it_carried_load_and_the_streak_is_never_a_rest_signal(monkeypatch):
    """The writers read the whole dossier: each session is marked lift or not, and the streak carries its
    definition. Mutation control: drop `loaded` from the session rows, or the definition key."""
    t = _training_4678(monkeypatch, _fifteen_active_four_lifting())
    assert [s["loaded"] for s in t["sessions"]] == [False, False, False, True, True, True, True]
    note = t["lifting_streak_definition"]
    assert "not counted" in note and "not a fatigue" in note and "rest" in note


def test_no_story_prompt_or_renderer_names_the_any_hevy_row_streak():
    """The set, not the instance: nothing under lambdas/content/ reads or prints the retired field names.
    Mutation control: re-add `training_streak_days` to the scoreboard."""
    content = Path(story_dossier.__file__).parent
    offenders = [
        f"{p.name}: {name}"
        for p in sorted(content.glob("*.py"))
        for name in ("consecutive_training_days_through_week_end", "training_streak_days", "straight training days")
        if name in p.read_text()
    ]
    assert offenders == []


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
    # the plain word "weight" is the brief's own word for it, so it must satisfy the check (verifier #4746)
    for said in (
        "Day 24, and his weight fell again. He trained twenty-three days straight.\n\nMore.",
        "Day 24, and the weight came off again. He trained twenty-three days straight.\n\nMore.",
    ):
        assert not _of(c.chronicle_findings(said, week=4, weight_known=True), "which way the scale went")
    lifted = "Day 24, and he lifted weights again. He trained twenty-three days straight.\n\nMore."
    assert _of(c.chronicle_findings(lifted, week=4, weight_known=True), "which way the scale went")
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


def test_the_desk_hands_the_publish_path_only_storys_crafts_residual_verdict(monkeypatch):
    """#4545 box 3: craft_post/craft_episode/craft_dek are the sublists of post/episode/dek the hold is built on."""
    from content import story_pipeline, story_writers

    monkeypatch.setattr(story_writers, "fact_check", lambda *a, **k: [])
    g = story_pipeline._Gates(3, {"weight": {"available": True}}, {}, {})
    md = '"T"\n\nDay 24, and Matthew had trained twenty-three days straight. His recovery read high.\n\nMore.'
    assert _of(g.craft_post(md), "which way the scale went") and all(f in g.post(md, "end_turn") for f in g.craft_post(md))
    ep = {"turns": [{"speaker": "elena", "line": "Hello."}]}
    assert _of(g.craft_episode(ep), "never names the segment")
    assert g.craft_dek("Day 24: his HRV rose.") and all(
        f"dek: {f}" in g.dek("Day 24: his HRV rose.") for f in g.craft_dek("Day 24: his HRV rose.")
    )
