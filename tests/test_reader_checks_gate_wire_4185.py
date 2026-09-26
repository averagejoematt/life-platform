"""#4185 — the reader CHECK classes ride the coach quality gate's regenerate-or-hold path.

Proves the WIRE, through the real ``ai_calls._invoke_quality_gate_sync`` and
``_enforce_quality_gate`` with a fake coach-quality-gate client (the LLM judge PASSES
every draft, so any hold below is the deterministic checks' alone), plus the corpus seal.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import reader_checks_corpus as corpus

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import grounding_corpus_stamp  # noqa: E402
from ai import (
    ai_calls,  # noqa: E402
    grounded_generation,  # noqa: E402
)
from ai.quality_gate_contract import brief_with_grounding, report_findings  # noqa: E402
from coach import reader_checks  # noqa: E402

WEBB = next(fx for fx in corpus.FIXTURES if fx["id"] == "2026-09-26-nutrition-six-day-gap-on-20-of-20")


def _judge_that_passes_everything():
    client = MagicMock()

    def _invoke(**kwargs):
        body = MagicMock()
        body.read.return_value = json.dumps({"statusCode": 200, "passed": True, "score": 95}).encode()
        return {"Payload": body}

    client.invoke.side_effect = _invoke
    return client


def _brief(fx):
    facts = fx["served_facts"]
    brief = brief_with_grounding({"served_facts": facts}, None, grounded_generation.allowed_numbers(facts))
    if fx.get("slot"):
        brief["reader_slot"] = fx["slot"]
    return brief


def test_a_live_specimen_fails_the_gate_with_every_finding_named():
    report = ai_calls._invoke_quality_gate_sync(_judge_that_passes_everything(), "nutrition_coach", WEBB["text"], _brief(WEBB))
    assert report["passed"] is False
    named = {f["check"] for f in report[reader_checks.REPORT_KEY]}
    assert named == set(WEBB["expected_findings"])
    assert any("[absence_premise]" in s for s in report["suggestions"]), "the correction must reach the regeneration note"
    note = ai_calls._quality_gate_correction_note(report)
    assert "[absence_premise]" in note and "[banned_term]" in note
    assert {f["type"] for f in report_findings(report)} >= set(WEBB["expected_findings"]), "retention names each class"


def test_regenerate_then_hold_when_the_rewrite_still_fails():
    calls = []
    out, report = ai_calls._enforce_quality_gate(
        _judge_that_passes_everything(),
        "nutrition_coach",
        WEBB["text"],
        _brief(WEBB),
        regenerate_fn=lambda note: calls.append(note) or WEBB["text"],
    )
    assert out is None, "a draft still failing a reader check after the regeneration cap is HELD, never published"
    assert len(calls) == ai_calls._QUALITY_GATE_MAX_REGENERATIONS


def test_a_clean_rewrite_is_published():
    clean = "I've asked him to keep logging every meal through Friday, October 2."
    out, report = ai_calls._enforce_quality_gate(
        _judge_that_passes_everything(), "nutrition_coach", WEBB["text"], _brief(WEBB), regenerate_fn=lambda note: clean
    )
    assert out == clean and report["passed"] is True


def test_mutation_control_without_the_merge_the_specimen_passes(monkeypatch):
    monkeypatch.setattr(reader_checks, "merge_into_report", lambda payload, text, brief: [])
    report = ai_calls._invoke_quality_gate_sync(_judge_that_passes_everything(), "nutrition_coach", WEBB["text"], _brief(WEBB))
    assert report["passed"] is True and reader_checks.REPORT_KEY not in report


def test_an_empty_brief_arms_no_input_dependent_class():
    """No allow-list, no served facts: the input-dependent classes stay silent (honest absence)."""
    text = "Six days without logs; he hit 33 g below target."
    assert reader_checks.merge_into_report({}, text, {}) == []


def test_corpus_is_sealed():
    assert grounding_corpus_stamp.verify_corpus(Path(corpus.CORPUS_DIR)) == []


def test_every_positive_control_is_clean_on_every_narrative_class():
    for fx in (f for f in corpus.FIXTURES if f["kind"] == "control"):
        hits = [f for f in corpus.fired(fx, reader_checks.NARRATIVE_CHECK_NAMES + ("audience_violation", "ask_cardinality"))]
        assert hits == [], f"{fx['_file']}: {hits}"
