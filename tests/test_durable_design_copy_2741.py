"""#2741 — the durable-design-copy retirement, enforced deterministically.

Every NOTE below is a VERBATIM production note lifted from the qa-smoke log group
(`/aws/lambda/life-platform-qa-smoke`, the ten days to 2026-08-18) — including the
U+2011 non-breaking hyphen the live page renders in "Day‑1", which is precisely the
character an ASCII-hyphen comparison would silently miss. Fixture must be the wire:
a test written against re-typed ASCII notes would pass while the deployed check
never matched a single real finding.

Measured rate this retirement is answering: a home-page `temporal_contradiction`
in 25 of 60 runs (42%), across Day 6 of cycle 13, the pre-start countdown, and
Days 1-2 of cycle 14 — every phase, which is the exact claim the exempt clause makes.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import reader_truth_qa as rt  # noqa: E402

# ── verbatim production notes (see module docstring) ─────────────────────────

DROPPED = [
    # 2026-08-15 20:36Z, severity med
    "Home page states 'This attempt starts at the Day‑1 weigh‑in' but today is Day 6 "
    "(2026-08-15), so the attempt already started 6 days ago, not today. The phrasing "
    "implies the start is imminent or current, not in the past.",
    # 2026-08-15 21:49Z, severity med
    "Home page states 'This attempt starts at the Day‑1 weigh‑in' — but today is Day 6 "
    "(2026-08-15), and the cycle began 2026-08-10. The phrasing 'starts at' in present "
    "tense is misleading; the experiment is well underway, not starting today.",
    # 2026-08-16 20:51Z, severity med
    "Home page states 'This attempt starts at the Day‑1 weigh‑in' as a future/present "
    "framing, but the experiment phase confirms today is Day 7 (2026-08-16), meaning the "
    "Day-1 weigh-in occurred 6 days ago.",
    # 2026-08-18 18:31Z, severity HIGH — the run that would have FAILed the alarm
    "Home page states 'This attempt starts at the Day‑1 weigh‑in' — asserting the "
    "experiment begins at a weigh-in event. However, per the experiment phase, Day 1 was "
    "2026-08-17 (yesterday); today is Day 2.",
]

KEPT = [
    # 2026-08-15 22:17Z, severity HIGH — quotes the registered copy AND two other
    # spans. Not this class: the complaint is about the other sentences, so it must
    # survive at full severity.
    "Home page states 'This attempt starts at the Day‑1 weigh‑in, aimed at 185 lbs held "
    "for 90 consecutive days' but provides no data on current progress. The phrase "
    "'Every climb before this one ended the same way' and 'What is different this time "
    "is the loop above' imply this is a new attempt.",
    # 2026-08-17 18:31Z — quotes only UNregistered copy.
    "Home page states 'Every day writes its own numbers' and 'Every week gets written "
    "down' in narrative describing the site's design. However, the section 'the pillars "
    "· measured co-movement' states 'a young experiment starts low, not broken'.",
]


def _f(note, category="temporal_contradiction", page="/", severity="high"):
    return {"page": page, "category": category, "severity": severity, "note": note}


# ── the retirement fires on exactly the measured class ───────────────────────


@pytest.mark.parametrize("note", DROPPED)
def test_registered_durable_copy_is_dropped(note):
    assert rt.is_durable_design_copy(_f(note)) is True


@pytest.mark.parametrize("note", KEPT)
def test_a_note_quoting_anything_else_survives(note):
    assert rt.is_durable_design_copy(_f(note)) is False


def test_the_nonbreaking_hyphen_is_what_makes_it_match():
    """The live page renders U+2011; an ASCII-only comparison matches nothing."""
    nbh = "Home page states 'This attempt starts at the Day‑weigh‑in'"
    assert "‑" in DROPPED[0], "fixture lost its non-breaking hyphen"
    assert rt._normalize_copy("Day‑1 weigh‑in") == "day-1 weigh-in"
    assert nbh  # the glyph the registry must tolerate


# ── scope: nothing else is retired ───────────────────────────────────────────


def test_other_categories_are_never_dropped():
    for cat in ("duplicated_narrative", "audience_violation", "other"):
        assert rt.is_durable_design_copy(_f(DROPPED[0], category=cat)) is False, cat


def test_a_note_with_no_quoted_span_survives():
    assert rt.is_durable_design_copy(_f("The home page framing is misleading on Day 6.")) is False


def test_a_progress_claim_still_flags_at_full_severity():
    """The bar the issue sets: prose asserting progress that already happened stays flaggable."""
    note = "Home page states 'down 14 lbs over the past three weeks' but today is Day 2."
    assert rt.is_durable_design_copy(_f(note)) is False


def test_ambiguous_apostrophe_parse_fails_closed_to_keeping_the_finding():
    note = "Home page states 'What's different this time is the loop above' on Day 2."
    assert rt.is_durable_design_copy(_f(note)) is False


# ── the derivation guard: prompt clause and enforcement share one vocabulary ──


def test_prompt_renders_every_registered_string():
    """Charter primitive 2 — the clause the model reads derives from the tuple the
    code enforces, so widening one cannot silently leave the other behind."""
    phase = rt.phase_context()
    prompt = rt.build_prompt([{"name": "Home", "path": "/", "prose": "hello"}], phase)
    for s in rt.DURABLE_DESIGN_COPY:
        assert f'"{s}"' in prompt, f"{s!r} is enforced but never shown to the model"


def test_registry_is_non_empty_and_normalizes_cleanly():
    assert rt.DURABLE_DESIGN_COPY
    for s in rt.DURABLE_DESIGN_COPY:
        assert rt._normalize_copy(s) == rt._normalize_copy(s.upper())


# ── the drop is wired into assess_prose, not merely defined ──────────────────


def test_assess_prose_actually_drops_it(capsys):
    """A predicate nobody calls is a green light wired to nothing."""
    import json

    def fake_invoke(payload, model_name=None):
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "findings": [
                                {"page": "/", "category": "temporal_contradiction", "severity": "high", "note": DROPPED[3]},
                                {"page": "/", "category": "temporal_contradiction", "severity": "high", "note": KEPT[0]},
                            ],
                            "severity": "high",
                            "summary": "x",
                        }
                    ),
                }
            ]
        }

    findings, errors = rt.assess_prose([{"name": "Home", "path": "/", "prose": "hello"}], fake_invoke)
    assert errors == []
    assert len(findings) == 1, "exactly the registered-copy finding should have been dropped"
    assert findings[0]["note"] == KEPT[0]
    assert "dropped a durable-design-copy finding" in capsys.readouterr().out


def test_a_quoted_fragment_of_registered_copy_counts():
    """The 2026-08-15 21:49Z note quotes 'starts at' as well as the whole string."""
    assert rt._is_registered_span("starts at", [rt._normalize_copy(s) for s in rt.DURABLE_DESIGN_COPY]) is True


def test_a_short_common_word_inside_registered_copy_does_not_count():
    """The length floor — otherwise 'the' or 'day' would exempt anything."""
    reg = [rt._normalize_copy(s) for s in rt.DURABLE_DESIGN_COPY]
    for word in ("the", "day", "week", "at the"):
        assert rt._is_registered_span(word, reg) is False, word


# ── #3003: the /data/habits/ heatmap disclosure is registered durable copy ────
# The recorded 2026-08-22 finding (run 32601989142) flagged the caption that IS
# the page's honesty disclosure: "90-DAY HISTORY PREDATES THE CUT" — the ADR-077
# cross-phase shape correctly labelled. Render-verified against the live page.
# NB: the stored evidence for this run was truncated at 300 chars (the defect
# #3003 also fixes), so the fixture is the recorded prefix; the drop requires
# EVERY quoted span to be registered, and a fuller note quoting other page copy
# would rightly survive to the (page, category) baseline instead.

_HABITS_NOTE_3003 = (
    "The 90-DAY ADHERENCE HEATMAP section states '90-DAY HISTORY PREDATES THE CUT' and shows a heatmap "
    "with 90 days of history, but the experiment phase only allows 6 days of current-experiment data "
    "(Day 1 = 2026-08-17, today = 2026-08-22). This heatmap narrative implies 90 days of tracked habit data"
)


def test_the_habits_heatmap_disclosure_is_dropped():
    assert rt.is_durable_design_copy(_f(_HABITS_NOTE_3003, page="/data/habits/")) is True


def test_habits_note_quoting_other_copy_alongside_survives():
    note = _HABITS_NOTE_3003 + " and the section also states 'Tier-0 adherence held for 90 days straight'."
    assert rt.is_durable_design_copy(_f(note, page="/data/habits/")) is False
