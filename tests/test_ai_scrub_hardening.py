"""tests/test_ai_scrub_hardening.py — elite review (2026-06-15) batch 4.

Behavioral coverage for the public-AI content scrub hardening:
  * zero-width characters can't smuggle a blocked term past the literal pass
  * obfuscated (spaced / punctuated) LONG terms trip the whole-answer-drop
    fail-safe instead of slipping through
  * normal answers (incl. ones merely containing short-term substrings) are not
    nuked by the fail-safe

(The history-replay gating — scrub + safety-gate the replayed assistant turn —
is asserted structurally in test_ai_endpoint_hardening.py's grep suite plus the
import-level check here.)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_ai_lambda as ai  # noqa: E402

_FILTER = {
    "blocked_vices": ["No porn", "No marijuana"],
    "blocked_vice_keywords": ["porn", "pornography", "marijuana", "cannabis", "weed", "thc"],
}


def _set_filter(monkeypatch):
    monkeypatch.setattr(ai, "_content_filter_cache", dict(_FILTER))


def test_literal_term_still_removed(monkeypatch):
    _set_filter(monkeypatch)
    out = ai._scrub_blocked_terms("He asked about marijuana use.")
    assert "marijuana" not in out.lower()


def test_zero_width_obfuscation_stripped(monkeypatch):
    _set_filter(monkeypatch)
    # zero-width space inside the word → must not survive
    out = ai._scrub_blocked_terms("about mari​juana today")
    assert "marijuana" not in ai._normalize_for_detection(out)


def test_spaced_long_term_drops_whole_answer(monkeypatch):
    _set_filter(monkeypatch)
    out = ai._scrub_blocked_terms("the answer is m a r i j u a n a for sure")
    assert out == "I can't share that."


def test_punctuated_long_term_drops_whole_answer(monkeypatch):
    _set_filter(monkeypatch)
    out = ai._scrub_blocked_terms("c-a-n-n-a-b-i-s is the topic")
    assert out == "I can't share that."


def test_normal_answer_untouched(monkeypatch):
    _set_filter(monkeypatch)
    txt = "Your recovery improved 8% this week and HRV is trending up."
    assert ai._scrub_blocked_terms(txt) == txt


def test_short_substring_does_not_nuke_answer(monkeypatch):
    # "weed" (<7 normalized) must NOT trigger the whole-answer-drop fail-safe on
    # legit text — only the literal pass touches short terms.
    _set_filter(monkeypatch)
    out = ai._scrub_blocked_terms("We discussed your sleep at length.")
    assert out != "I can't share that."
    assert "sleep" in out


def test_normalize_collapses_separators(monkeypatch):
    assert ai._normalize_for_detection("m a r i.j-u_a n a") == "marijuana"
    assert ai._normalize_for_detection("CANNABIS") == "cannabis"


def test_history_turn_is_gated_and_scrubbed():
    # Structural: the replayed assistant answer must be both safety-gated and
    # scrubbed (not passed through raw). Guards against silent regression.
    src = open(ai.__file__, encoding="utf-8").read()
    assert "_ask_question_safe(a)[0]" in src, "replayed answer must be safety-gated"
    assert "_scrub_blocked_terms(a)" in src, "replayed answer must be scrubbed"
