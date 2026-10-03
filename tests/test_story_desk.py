"""tests/test_story_desk.py — the Story Desk's gates, ledger and calendar (#4531-#4538).

Fixtures are the real failures the 2026-10-01 continuity review found in published and
drafted installments (quoted verbatim where the text is ours to quote), so each gate is
proven against the defect it exists for — and each has a mutation control showing it can
fail.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import pytest  # noqa: E402
from content import story_checks, story_desk, story_dossier, story_ledger, story_writers  # noqa: E402

# ── completeness (#4535) ─────────────────────────────────────────────────────

WK4_DRAFT_TAIL = (
    "The scale has dropped 15 pounds in twenty-four days. It is a meaningful number, and it sits at the center of a week that is "
    "harder to read than the previous three. The body's physiological signals are the best they've been — the sleep architecture is genuinely"
)


def test_the_cut_off_wk4_draft_is_incomplete():
    f = story_checks.completeness(WK4_DRAFT_TAIL, stop_reason="end_turn", footer_pattern=story_writers.CHRONICLE_FOOTER)
    assert any("mid-sentence" in x for x in f)
    assert any("footer" in x for x in f)


def test_a_finished_installment_passes():
    body = "He walked home in the rain.\n\n---\n*Week 4 of The Measured Life*"
    assert story_checks.completeness(body, stop_reason="end_turn", footer_pattern=story_writers.CHRONICLE_FOOTER) == []


def test_stop_reason_max_tokens_is_incomplete_even_when_the_text_looks_finished():
    body = "He walked home in the rain.\n\n---\n*Week 4 of The Measured Life*"
    assert story_checks.completeness(body, stop_reason="max_tokens", footer_pattern=story_writers.CHRONICLE_FOOTER)


# ── the story door (#4538) ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "The Fifteenth Reset, or: What the Body Remembers",
        "He counted them himself. Fifteen, maybe sixteen resets.",
        "the whole argument for why this time might be different from the previous fifteen resets",
        "a man who has been waiting to start for fifteen attempts",
        "this is cycle 17 of the experiment",
        "for the sixteenth time",
    ],
)
def test_counts_are_blocked(text):
    assert story_checks.story_door(text), text


@pytest.mark.parametrize(
    "text", ["for the first time he cleared the floor", "a reset week for the nerves", "sleep cycles lengthened", "three sessions"]
)
def test_ordinary_language_passes(text):
    assert story_checks.story_door(text) == [], text


def test_backstage_words_are_blocked():
    assert story_checks.story_door("the desk flagged something worth putting on the table")


def test_absence_as_behaviour_only_when_the_window_is_not_exported():
    text = "Sunday, Monday, Tuesday: nothing. This is not a technical gap."
    assert story_checks.story_door(text, not_yet_exported=["macrofactor"])
    assert story_checks.story_door(text, not_yet_exported=[]) == []  # mutation control: a landed gap may be reported


# ── number grounding (ADR-104) ───────────────────────────────────────────────


def test_numbers_must_come_from_the_dossier():
    allowed = story_checks.allowed_numbers({"protein_g": 186, "hrv_ms": 56.82, "kcal": 1925})
    ok = "He ate 186 grams of protein on 1,925 calories; HRV touched 57 and nearly 56.8."
    assert story_checks.ungrounded_numbers(ok, allowed) == []
    # the published wk4 verdict measured 186 g against a 190 g floor the plan does not have
    assert story_checks.ungrounded_numbers("four grams short of the 190-gram floor", allowed)


def test_clock_times_and_small_counts_are_free():
    assert story_checks.ungrounded_numbers("at 5:12 AM, the third session in 7 days", set()) == []


# ── the spoken-word gate (mirrors the Panel renderer) ───────────────────────


def test_spoken_word_gate_catches_the_held_wk3_shapes():
    turns = [
        {"speaker": "elena", "line": "Welcome back."},
        {"speaker": "coach", "line": "It means the nervous system has caught up — the long weekend led to that 51."},
        {"speaker": "elena", "line": "He weighed 315 that morning. I'm Elena Voss. This has been The Measured Life."},
    ]
    f = story_writers.spoken_word_findings(turns, body_weights=[315.0])
    assert any("causal" in x for x in f)
    assert any("body-number" in x for x in f)


def test_a_clean_episode_passes():
    turns = [
        {"speaker": "elena", "line": "Recovery came in at 78 percent."},
        {"speaker": "elena", "line": "I'm Elena Voss. This has been The Measured Life."},
    ]
    assert story_writers.spoken_word_findings(turns, body_weights=[315.0]) == []


# ── the ledger (#4533) ───────────────────────────────────────────────────────


def _budget(lead="volume", actions=None, scored="none", bet_claim="", featured=("sleep_coach",)):
    return {
        "lead": {"thread_id": lead, "angle": "", "why": "", "evidence": []},
        "thread_actions": actions or [],
        "bet_scored": {"result": scored, "note": ""},
        "bet": {"claim": bet_claim, "metric": "recovery", "rule": ">=70 on 4 of 7", "window_days": 7},
        "featured_coaches": list(featured),
        "beats_used": [],
        "arc_updates": [],
    }


def test_a_thread_cannot_lead_a_third_week_running():
    led = story_ledger.empty_ledger()
    for w in (2, 3):
        led = story_ledger.apply_budget(
            led,
            _budget(actions=[{"thread_id": "volume", "action": "open" if w == 2 else "advance", "title": "", "note": ""}]),
            week=w,
            date=f"2026-09-{w}",
            title="t",
        )
    f = story_ledger.continuity_findings(led, _budget(actions=[{"thread_id": "volume", "action": "advance", "title": "", "note": ""}]), 4)
    assert any("led 2 weeks running" in x for x in f)
    # mutation control: leading elsewhere passes
    assert not [
        x
        for x in story_ledger.continuity_findings(
            led, _budget(lead="prereg", actions=[{"thread_id": "volume", "action": "advance", "title": "", "note": ""}]), 4
        )
        if "running" in x
    ]


def test_a_stale_thread_must_be_resolved_or_retired_by_name():
    led = story_ledger.apply_budget(
        story_ledger.empty_ledger(),
        _budget(lead="x", actions=[{"thread_id": "prereg_scoring", "action": "open", "title": "score the predictions", "note": ""}]),
        week=0,
        date="d0",
        title="t",
    )
    f = story_ledger.continuity_findings(
        led, _budget(lead="y", actions=[{"thread_id": "prereg_scoring", "action": "hold", "title": "", "note": ""}]), 3
    )
    assert any("stale thread" in x for x in f)
    assert not [
        x
        for x in story_ledger.continuity_findings(
            led, _budget(lead="y", actions=[{"thread_id": "prereg_scoring", "action": "resolve", "title": "", "note": ""}]), 3
        )
        if "stale" in x
    ]


def test_an_open_bet_must_be_scored():
    led = story_ledger.apply_budget(
        story_ledger.empty_ledger(), _budget(bet_claim="recovery >= 70 on 4 of 7 days"), week=1, date="d1", title="t"
    )
    assert any("bet" in x for x in story_ledger.continuity_findings(led, _budget(scored="none"), 2))
    assert not [x for x in story_ledger.continuity_findings(led, _budget(scored="right"), 2) if "bet" in x]


def test_apply_budget_never_mutates_the_previous_ledger():
    prev = story_ledger.empty_ledger()
    story_ledger.apply_budget(
        prev, _budget(actions=[{"thread_id": "a", "action": "open", "title": "", "note": ""}]), week=1, date="d", title="t"
    )
    assert prev["threads"] == []


def test_a_tombstoned_ledger_row_is_invisible():
    class _T:
        def __init__(self, items):
            self.items = items

        def query(self, **kw):
            return {"Items": self.items}

    import json

    row = {
        "pk": "p",
        "sk": "LEDGER#2026-07-07",
        "ledger_json": json.dumps({**story_ledger.empty_ledger(), "week": 4}),
        "tombstone": True,
        "phase": "pilot",
    }
    assert story_ledger.latest_visible(_T([row]), "p", "2026-09-29")["week"] is None
    live = {**row, "tombstone": False, "phase": "experiment"}
    live.pop("tombstone")
    assert story_ledger.latest_visible(_T([live]), "p", "2026-09-29")["week"] == 4  # mutation control


# ── the desk's code-side validation (#4534) ──────────────────────────────────


def test_the_desk_rejects_a_coach_off_the_roster_and_a_repeat_feature():
    dossier = {"roster": [{"coach_id": c} for c in ("sleep_coach", "nutrition_coach", "mind_coach", "physical_coach")]}
    led = story_ledger.apply_budget(story_ledger.empty_ledger(), _budget(featured=("sleep_coach",)), week=2, date="d", title="t")
    assert any(
        "not on the roster" in x for x in story_desk.validate(_budget(featured=("chen",)), dossier, story_ledger.empty_ledger(), week=3)
    )
    assert any("repeats" in x for x in story_desk.validate(_budget(featured=("sleep_coach",)), dossier, led, week=3))
    assert not [x for x in story_desk.validate(_budget(featured=("mind_coach",)), dossier, led, week=3) if "repeats" in x]


def test_the_budget_schema_is_closed():
    assert story_desk.BUDGET_SCHEMA["additionalProperties"] is False
    assert set(story_desk.BUDGET_SCHEMA["required"]) == set(story_desk.BUDGET_SCHEMA["properties"])


# ── the season calendar ──────────────────────────────────────────────────────


def test_the_season_calendar_matches_the_published_week_keys():
    weeks = story_dossier.season_weeks(through="2026-09-30")
    assert [(w["week"], w["start"], w["end"]) for w in weeks] == [
        (1, "2026-09-06", "2026-09-08"),
        (2, "2026-09-09", "2026-09-15"),
        (3, "2026-09-16", "2026-09-22"),
        (4, "2026-09-23", "2026-09-29"),
    ]
    assert weeks[3]["day_first"] == 18 and weeks[3]["day_last"] == 24


def test_an_ungradable_bet_whose_window_is_open_is_carried_not_dropped():
    led = story_ledger.apply_budget(
        story_ledger.empty_ledger(), _budget(bet_claim="weight on Day 7 below 326.2"), week=0, date="d0", title="t"
    )
    led = story_ledger.apply_budget(led, _budget(scored="not_gradable"), week=1, date="d1", title="t")
    assert story_ledger.last_open_bet(led)["claim"] == "weight on Day 7 below 326.2"  # still open, carried
    led = story_ledger.apply_budget(led, _budget(scored="right"), week=2, date="d2", title="t")
    assert led["bets"][0]["result"] == "right"


def test_the_desk_prefers_an_unmet_coach_with_a_graded_call():
    dossier = {
        "roster": [{"coach_id": c} for c in ("sleep_coach", "nutrition_coach", "mind_coach", "physical_coach")],
        "predictions": {"graded_this_week": [{"coach_id": "sleep_coach"}]},
    }
    led = story_ledger.apply_budget(story_ledger.empty_ledger(), _budget(featured=("physical_coach",)), week=1, date="d", title="t")
    led = story_ledger.apply_budget(led, _budget(featured=("mind_coach",)), week=2, date="d", title="t")
    led = story_ledger.apply_budget(led, _budget(featured=("nutrition_coach",)), week=3, date="d", title="t")
    assert any("never been featured" in x for x in story_desk.validate(_budget(featured=("physical_coach",)), dossier, led, week=4))
    assert not [x for x in story_desk.validate(_budget(featured=("sleep_coach",)), dossier, led, week=4) if "never been featured" in x]


def test_a_carried_bet_must_be_scored_once_its_window_closes():
    led = story_ledger.apply_budget(
        story_ledger.empty_ledger(), _budget(bet_claim="weight on Day 7 below 326.2"), week=0, date="d0", title="t"
    )
    led = story_ledger.apply_budget(led, _budget(scored="not_gradable", bet_claim="recovery Day 7 >= 70"), week=1, date="d1", title="t")
    b = _budget(scored="right")
    assert any("Week 0 bet" in x for x in story_ledger.continuity_findings(led, b, 2))
    b["bets_scored"] = [{"bet_week": 0, "result": "right", "winner": "Elena", "note": "319.7 on Day 7"}]
    assert not [x for x in story_ledger.continuity_findings(led, b, 2) if "Week 0 bet" in x]
    led = story_ledger.apply_budget(led, b, week=2, date="d2", title="t")
    assert led["bets"][0]["result"] == "right" and led["bets"][0]["winner"] == "Elena"


def _minimal_budget(schema=None):
    """A schema-conformant instance derived FROM BUDGET_SCHEMA (so the fixture cannot drift from the schema)."""
    from content import story_desk as d

    sc = d.BUDGET_SCHEMA if schema is None else schema
    if "enum" in sc:
        return sc["enum"][0]
    t = sc.get("type")
    if t == "object":
        return {k: _minimal_budget(v) for k, v in (sc.get("properties") or {}).items()}
    return {"array": [], "string": "", "integer": 0, "number": 0, "boolean": False}[t]


def test_a_grammar_refusal_falls_back_schema_less_and_the_shape_is_still_checked():
    """2026-10-02: Bedrock refused BUDGET_SCHEMA ('The compiled grammar is too large'), the desk raised, and the live
    chronicle fell back to the legacy writer. The desk now re-sends schema-less and checks the shape in code."""
    import json as _json

    from ai import structured_json
    from content import story_desk as d

    calls = []
    good = _json.loads(_json.dumps(_minimal_budget()))

    def invoke(body, model):
        calls.append(body)
        if "output_config" in body:
            raise RuntimeError(
                "An error occurred (ValidationException) when calling the InvokeModel operation: The compiled grammar is too large"
            )
        if len(calls) == 2:  # first schema-less reply: wrong shape → the corrective retry must name it
            return {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"lead": "a string"}'}]}
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": _json.dumps(good)}]}

    try:
        d.run_desk({"roster": []}, story_ledger.empty_ledger(), week=0, invoke=invoke, log=lambda m: None)
    except RuntimeError:
        pass  # the editorial checks may still reject a minimal budget; the seam is what is under test
    assert "output_config" in calls[0] and "output_config" not in calls[1]  # strict first, then schema-less
    assert "JSON Schema" in calls[1]["system"]
    retry_text = calls[2]["messages"][-1]["content"]
    assert "missing required" in retry_text  # the shape error reached the corrective retry, by name

    shape_errors = structured_json.schema_findings({"lead": "a string"}, d.BUDGET_SCHEMA)
    assert any("missing required" in f for f in shape_errors) and any("expected object" in f for f in shape_errors)
    assert not structured_json.schema_findings(good, d.BUDGET_SCHEMA)
    assert "output_config" not in d._schema_less({"system": "s", "output_config": {}})
