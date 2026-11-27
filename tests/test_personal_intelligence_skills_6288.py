#!/usr/bin/env python3
"""tests/test_personal_intelligence_skills_6288.py — the everyday entry point (#6288), the
reflective conversation (#6289), and review-before-save in the three older capture skills.

These are prose skills; nothing compiles them. Each assertion below is an owner ruling of
2026-11-26 that the skill text has to keep saying, because the failure it prevents is silent:
a record saved before he saw it, a model's reading stated as a finding, or a note shared
with the coaches because nobody asked.

Asserting on CONTENT, not presence (the `test_new_skills_contract.py` convention).
"""

import pytest
from skill_paths import require_skill


def body(name: str) -> str:
    return require_skill(name).read_text(encoding="utf-8").lower()


def flat(name: str) -> str:
    """The body with whitespace collapsed, so a re-wrapped sentence still matches."""
    return " ".join(body(name).split())


def test_both_skills_exist_under_the_one_registry():
    # The literal calls are what `scripts/skill_lint.py::has_contract_test` looks for.
    assert require_skill("ask").name == "SKILL.md"
    assert require_skill("reflect").name == "SKILL.md"


# ── ask — one entry point for an ordinary question ────────────────────────────
ASK = [
    ("get_decisions", "what he decided is read before answering"),
    ("log_coach_correction", "his open corrections outrank what a coach wrote earlier"),
    ("manage_coach_recommendation", "recommendations are read with his recorded answer"),
    ("read_platform_memory", "his approved context and constraints are read"),
    ("get_freshness_status", "a stale source is stated, never papered over"),
    ("never say he did something because the data looks like it", "no inferred compliance"),
    ("model-inferred", "a model's reading of his notes is never stated as a finding"),
    ("no invented coaches", "no manufactured coach memory or personality"),
    ("both positions are in the record", "a disagreement is shown only when the record holds both sides"),
    ("missing is unknown", "a gap is never described as decline"),
    ("manage_pending_writes", "nothing is kept outside the approval queue"),
    ("does not monitor him", "the platform never implies emergency monitoring"),
    ("plain words about saving", "first real use closed with 'to route, if you want' (2026-11-26)"),
]


@pytest.mark.parametrize("needle,why", ASK)
def test_ask_carries_its_rules(needle, why):
    assert needle in flat("ask"), f"ask must cover: {why}"


def test_ask_does_not_make_him_pick_a_coach_or_a_tool():
    b = flat("ask")
    assert "never has to choose a coach" in b
    assert "length follows the question" in b, "no fixed cap on every answer (owner, 2026-11-26)"


def test_ask_hands_off_instead_of_absorbing_other_skills():
    b = flat("ask")
    for other in ("coach-session", "daily-debrief", "reflect"):
        assert other in b, f"ask must hand off to {other} rather than imitate it"


# ── reflect — varied conversations, reviewed before anything is saved ─────────
REFLECT_MODES = [
    "life history and identity",
    "competing explanations",
    "relationships and belonging",
    "loss and change",
    "work and purpose",
    "confidence and coping",
    "values and meaning",
    "strengths and enjoyment",
    "data-informed reflection",
    "short journal",
    "something to try",
]


@pytest.mark.parametrize("mode", REFLECT_MODES)
def test_reflect_carries_every_mode_in_one_skill(mode):
    assert mode in flat("reflect"), f"reflect lost the '{mode}' mode"


REFLECT = [
    ("nothing is saved until he has seen it and said yes", "review before save"),
    ("never makes anything public", "no public path from this skill"),
    ("kept in his journal, never published", "owner ruling 2026-11-26: reflections go to the journal, coaches may see them"),
    ("never calls `mark_journal_quote`", "nothing from a reflection is nominated for the website"),
    ("parts 4 and 5 (your readings and your questions) are not written into the journal page", "the journal page holds only his words"),
    ("stay private by default", "structured platform items remain private unless he says otherwise"),
    ("one question at a time", "not a questionnaire"),
    ("light, medium or deep", "he sets the depth"),
    ("never opened by you", "loss is his to raise"),
    ("do not manufacture disagreement", "challenge only when real"),
    ("do not invent an insight", "no manufactured insight"),
    ("rival", "an interpretation carries a rival reading"),
    ("never load the whole journal", "earlier material by excerpt only"),
    ("he has excluded", "owner exclusions are honoured"),
    ("never call `write_platform_memory` directly", "platform records go through the queue"),
    ("rejected_interpretation", "a rejected reading is kept so it is not proposed again"),
    ("stop exploring", "distress stops the interview"),
    ("does not monitor him", "no implied emergency monitoring"),
    ("no reminders", "no follow-up schedule or rating form"),
    ("manage_personal_hypothesis", "open questions about him are read and written through the hypothesis record (#6292)"),
    ("never re-propose a question it shows as rejected", "a rejected hypothesis stays closed until he reopens it"),
    ("a confidence word, never a number", "no numeric confidence on a hypothesis"),
    ("open like a person, not a status report", "first real use opened with queue and sync status (2026-11-26)"),
]


@pytest.mark.parametrize("needle,why", REFLECT)
def test_reflect_carries_its_rules(needle, why):
    assert needle in flat("reflect"), f"reflect must cover: {why}"


def test_reflect_draft_keeps_five_kinds_of_content_apart():
    b = flat("reflect")
    for part in (
        "what you said",
        "events and dates you stated",
        "self-reports you chose to give",
        "possible readings (mine, not yours)",
        "questions for later",
    ):
        assert part in b, f"the reviewed draft lost its '{part}' part"
    assert "[confirmed]" in b and "[recollection]" in b


def test_reflect_names_no_clinical_labels_as_its_own_findings():
    b = flat("reflect")
    assert "do not name conditions, defence mechanisms or distortions" in b


# ── review-before-save in the older capture skills ────────────────────────────
def test_interview_shows_the_brief_before_storing_it():
    b = flat("interview")
    assert "review before anything is stored" in b
    assert b.index("review before anything is stored") < b.index("confirm the upload out loud"), "the review must come before the upload"
    assert "keeping the brief is not permission to share" in b
    assert "allude tier" not in b, "there is no 'allude' memory tier; a coach-context line goes through the queue"


def test_journal_interview_shows_the_entry_before_writing_the_page():
    b = flat("journal-interview")
    assert "show him the entry before it is written" in b
    assert b.index("show him the entry before it is written") < b.index("### 4. write the page")
    assert "read by the platform's enrichment" in b, "he is told a journal page reaches the enrichment and the journal coach"


def test_open_checkin_proposes_before_it_writes():
    b = flat("open-checkin")
    assert "nothing is written before he has seen the list and said yes" in b
    assert "manage_pending_writes" in b
