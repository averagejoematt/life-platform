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


def test_lines_already_heard_are_findings():
    prev = {3: "MAX: One good scan is one good scan, and fast is fine if the protein holds."}
    assert c.repeat_findings("MARCUS: Look, one good scan is one good scan, and fast is fine if it holds.", prev)
    assert c.repeat_findings("MARCUS: A single scan tells us little on its own.", prev) == []
