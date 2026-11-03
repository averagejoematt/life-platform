"""tests/test_ledger_corrections_export_5610.py — the snapshot exporter's half of #5610 (owner decision D).

``/api/ledger_export`` serves every stored grade correction in one shape (``lambdas/web/correction_history``).
The exporter copies the contract's keys as served (``_correction_entry``) and ``validate_correction`` holds
them strictly, so:

  * a correction whose rule has no reader words (``explanation`` null — an unknown rule id on the API side)
    FAILS the export: no page prints engineering text in place of an explanation;
  * a pre-#5610 entry (the bare #5533 nine keys) fails the export by name rather than rendering a
    half-empty correction — the www merge waits for the Site API deploy;
  * dates are a day or null; ``published_on`` is never filled by the exporter.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "scripts", "publish_snapshot.py")


def _load():
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    spec = importlib.util.spec_from_file_location("publish_snapshot_5610", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ps = _load()

SERVED = {
    "source": "verdict_correction",
    "kind": "regrade",
    "rules": [{"id": "#4618:regrade", "version": None}],
    "explanation": "The sentence named its own day. It was graded again on the reading for the day it named.",
    "said_on": "2026-09-14",
    "original_status": "confirmed",
    "original_outcome_date": "2026-09-28",
    "original_outcome_notes": '{"reason": "recovery_score=64.00 on 2026-09-28"}',
    "corrected_status": "refuted",
    "corrected_outcome_date": None,
    "corrected_outcome_notes": None,
    "target_before": "2026-09-28",
    "target_after": "2026-09-15",
    "corrected_at": "2026-10-11T02:48:10.102408+00:00",
    "published_on": None,
    "reason": "#4618: the sentence names its own day; graded again on the reading for the day it named.",
    "evaluator_version": None,
}


def test_a_served_correction_maps_and_validates():
    c = ps._correction_entry(SERVED)
    ps.validate_correction(c, "t")
    assert c["published_on"] is None and c["corrected_outcome_date"] is None and c["aggregate_impact"] is None
    assert {k: c[k] for k in SERVED} == SERVED, "every served key copied as served"


def test_a_correction_with_no_reader_words_fails_the_export():
    c = ps._correction_entry({**SERVED, "explanation": None, "rules": [{"id": "unknown:grader v2", "version": None}]})
    with pytest.raises(ps.SchemaError, match=r"unknown:grader v2.*no reader explanation"):
        ps.validate_correction(c, "t")


def test_a_pre_5610_entry_fails_by_name():
    old = {
        k: SERVED[k]
        for k in ("original_status", "original_outcome_date", "corrected_status", "corrected_at", "reason", "evaluator_version")
    }
    with pytest.raises(ps.SchemaError):
        ps.validate_correction(ps._correction_entry(old), "t")


def test_malformed_corrections_are_refused():
    bad_cases = {
        "grading-day-is-a-day": {"original_outcome_date": "2026-09-28T17:00:00Z"},
        "published-is-a-day": {"published_on": "1 November 2026"},
        "kind-enum": {"kind": "rewrite"},
        "rules-non-empty": {"rules": []},
        "rule-id-non-empty": {"rules": [{"id": "", "version": None}]},
    }
    passed = []
    for name, bad in bad_cases.items():
        try:
            ps.validate_correction(ps._correction_entry({**SERVED, **bad}), "t")
            passed.append(name)
        except ps.SchemaError:
            pass
    assert not passed, f"accepted: {passed}"


def test_an_extra_key_is_refused_by_the_validator():
    with pytest.raises(ps.SchemaError, match="unknown"):
        ps.validate_correction({**ps._correction_entry(SERVED), "original_timestamp": None}, "t")
