"""tests/test_voice_register_guard_1987.py — #1987 coach voice-register guard.

The summarizer's extraction/summary prompts sometimes drift into third-person
"meta" narration ("The coach pivots from data to ownership…", "the glucose
coach is in calibration mode…") instead of the coach's own first person, and
raw markdown emphasis asterisks ("*word*") leak straight through to the
rendered page. Prompt rules alone can't guarantee structure (ADR-105) — this
guard is the deterministic (zero-AI-cost) backstop wired at both write paths:
`coach_state_updater._write_output_record` (observatory_summary, item 8) and
`intelligence_common.extract_thread_from_narrative` (position_summary).

These fixtures are drawn from the issue's own cited live examples. Each
third-person / markdown fixture demonstrates the pre-fix bug: run against the
raw guard functions and the write-path wiring, they prove the check actually
FIRES (rejects / cleans) rather than a prompt hope that silently drifts.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

from coach import persona_registry  # noqa: E402
from coach.voice_register_guard import (  # noqa: E402
    is_third_person,
    sanitize_summary,
    strip_markdown_emphasis,
)

# ══════════════════════════════════════════════════════════════════════════════
# Fixtures — verbatim (or near-verbatim) from the issue's cited live examples.
# ══════════════════════════════════════════════════════════════════════════════

THIRD_PERSON_GENERIC = "The coach pivots from data to ownership… the coach refuses to interpret it…"
THIRD_PERSON_DOMAIN_GLUCOSE = "The glucose coach is in calibration mode, waiting on another week of readings."
THIRD_PERSON_DOMAIN_SLEEP = "the sleep coach encountered a data paradox this week."
MARKDOWN_ASTERISK = "Do your targets feel like *your* future, or someone else's checklist?"
CLEAN_FIRST_PERSON = "I'm noticing your HRV trending up this week — keep the wind-down consistent and I'll reassess Friday."


class TestThirdPersonDetection:
    """The regex reject: 'the coach' / 'the {domain} coach', case-insensitive."""

    def test_generic_the_coach_fires(self):
        assert is_third_person(THIRD_PERSON_GENERIC) is True

    def test_domain_prefixed_glucose_fires(self):
        assert is_third_person(THIRD_PERSON_DOMAIN_GLUCOSE) is True

    def test_domain_prefixed_sleep_fires(self):
        assert is_third_person(THIRD_PERSON_DOMAIN_SLEEP) is True

    def test_case_insensitive(self):
        assert is_third_person("THE COACH IS RIGHT.") is True
        assert is_third_person("the Glucose Coach is calibrating.") is True

    def test_clean_first_person_does_not_fire(self):
        assert is_third_person(CLEAN_FIRST_PERSON) is False

    def test_markdown_only_sample_does_not_fire(self):
        # Markdown leakage and third-person register are independent defects —
        # a clean first-person sentence with a stray asterisk isn't third-person.
        assert is_third_person(MARKDOWN_ASTERISK) is False

    def test_empty_and_none_do_not_fire(self):
        assert is_third_person("") is False
        assert is_third_person(None) is False

    def test_domain_words_are_derived_not_hand_listed(self):
        """Every OPERATIONAL_SHORT_IDS persona is covered with no per-coach test edit needed —
        proves the pattern is built FROM the registry, not a hardcoded name list here."""
        for short_id in persona_registry.OPERATIONAL_SHORT_IDS:
            sample = f"the {short_id} coach is still calibrating."
            assert is_third_person(sample) is True, f"domain pattern missed derived short_id={short_id!r}"

    def test_unrelated_use_of_word_coach_does_not_fire(self):
        # "coach" alone, or "my coach"/"your coach", isn't the third-person-meta defect class.
        assert is_third_person("Your coach's take: keep pushing.") is False
        assert is_third_person("I coach myself through this every week.") is False


class TestMarkdownEmphasisStrip:
    def test_single_asterisk_emphasis_stripped(self):
        assert strip_markdown_emphasis(MARKDOWN_ASTERISK) == "Do your targets feel like your future, or someone else's checklist?"

    def test_bold_double_asterisk_stripped(self):
        assert strip_markdown_emphasis("This is **important** context.") == "This is important context."

    def test_no_markdown_is_unchanged(self):
        assert strip_markdown_emphasis(CLEAN_FIRST_PERSON) == CLEAN_FIRST_PERSON

    def test_inline_multiplication_is_left_alone(self):
        # Not markdown — a bare "3 * 4" shouldn't get mangled by the emphasis regex.
        assert strip_markdown_emphasis("Volume is roughly 3 * 4 sets.") == "Volume is roughly 3 * 4 sets."

    def test_empty_and_none(self):
        assert strip_markdown_emphasis("") == ""
        assert strip_markdown_emphasis(None) is None


class TestSanitizeSummary:
    """The combined write-time check both callers use."""

    def test_third_person_is_rejected(self):
        cleaned, rejected = sanitize_summary(THIRD_PERSON_GENERIC)
        assert rejected is True
        assert cleaned is None

    def test_domain_third_person_is_rejected(self):
        cleaned, rejected = sanitize_summary(THIRD_PERSON_DOMAIN_GLUCOSE)
        assert rejected is True
        assert cleaned is None

    def test_markdown_only_is_cleaned_not_rejected(self):
        cleaned, rejected = sanitize_summary(MARKDOWN_ASTERISK)
        assert rejected is False
        assert "*" not in cleaned
        assert cleaned == "Do your targets feel like your future, or someone else's checklist?"

    def test_clean_first_person_passes_through(self):
        cleaned, rejected = sanitize_summary(CLEAN_FIRST_PERSON)
        assert rejected is False
        assert cleaned == CLEAN_FIRST_PERSON

    def test_falsy_input_passes_through_not_rejected(self):
        assert sanitize_summary(None) == (None, False)
        assert sanitize_summary("") == ("", False)

    def test_third_person_AND_markdown_together_is_rejected(self):
        # The mixed-register noscript example from the issue: markdown gets stripped
        # first, but the surviving third-person register still rejects the value.
        mixed = "The *sleep* coach encountered a data paradox this week."
        cleaned, rejected = sanitize_summary(mixed)
        assert rejected is True
        assert cleaned is None


# ══════════════════════════════════════════════════════════════════════════════
# Write-path wiring — item 8 (observatory_summary) in coach_state_updater.py.
# ══════════════════════════════════════════════════════════════════════════════

import coach_state_updater as su  # noqa: E402


class TestObservatorySummaryWriteWiring:
    """`_write_output_record` must reject third-person and clean markdown BEFORE
    the OUTPUT# record is written — this is the actual write path the issue's
    live examples leaked through (served preferentially at site_api_coach.py:1682)."""

    def _write_and_capture(self, monkeypatch, observatory_summary):
        written = []
        monkeypatch.setattr(su, "_put_item", lambda item: written.append(item) or True)
        su._write_output_record(
            "mind_coach",
            "2026-08-02",
            "weekly_email",
            "the full first-person coach narrative goes here",
            {"observatory_summary": observatory_summary},
        )
        return written[0]

    def test_third_person_observatory_summary_is_rejected_to_none(self, monkeypatch):
        item = self._write_and_capture(monkeypatch, THIRD_PERSON_GENERIC)
        # None (not the raw third-person text) — site_api_coach.py's existing
        # `observatory_summary or content` fallback then serves the real content.
        assert item["observatory_summary"] is None

    def test_markdown_observatory_summary_is_cleaned_in_place(self, monkeypatch):
        item = self._write_and_capture(monkeypatch, MARKDOWN_ASTERISK)
        assert item["observatory_summary"] == "Do your targets feel like your future, or someone else's checklist?"

    def test_clean_first_person_observatory_summary_is_unchanged(self, monkeypatch):
        item = self._write_and_capture(monkeypatch, CLEAN_FIRST_PERSON)
        assert item["observatory_summary"] == CLEAN_FIRST_PERSON


# ══════════════════════════════════════════════════════════════════════════════
# Write-path wiring — position_summary parser in intelligence_common.py.
# ══════════════════════════════════════════════════════════════════════════════

from intelligence import intelligence_common as ic  # noqa: E402


class TestPositionSummaryWriteWiring:
    """`extract_thread_from_narrative` must reject third-person and clean markdown
    on the parsed `position_summary` before returning it to the caller."""

    def _extract_with_mocked_llm(self, monkeypatch, position_summary):
        def fake_call_anthropic_raw(req, timeout=30):
            import json as _json

            body = _json.dumps(
                {
                    "position_summary": position_summary,
                    "predictions": [],
                    "surprises": [],
                    "emotional_investment": "observing",
                    "open_questions": [],
                }
            )
            return {"content": [{"type": "text", "text": body}]}

        monkeypatch.setattr("common.retry_utils.call_anthropic_raw", fake_call_anthropic_raw)
        return ic.extract_thread_from_narrative("mind_coach", "the full narrative text", "fake-api-key")

    def test_third_person_position_summary_falls_back_to_truncated_narrative(self, monkeypatch):
        result = self._extract_with_mocked_llm(monkeypatch, THIRD_PERSON_DOMAIN_SLEEP)
        assert result["position_summary"] == "the full narrative text"
        assert "the sleep coach" not in result["position_summary"].lower()

    def test_markdown_position_summary_is_cleaned_in_place(self, monkeypatch):
        result = self._extract_with_mocked_llm(monkeypatch, MARKDOWN_ASTERISK)
        assert result["position_summary"] == "Do your targets feel like your future, or someone else's checklist?"

    def test_clean_first_person_position_summary_is_unchanged(self, monkeypatch):
        result = self._extract_with_mocked_llm(monkeypatch, CLEAN_FIRST_PERSON)
        assert result["position_summary"] == CLEAN_FIRST_PERSON
