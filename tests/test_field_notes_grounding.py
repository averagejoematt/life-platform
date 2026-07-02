"""tests/test_field_notes_grounding.py — SS-10 block-and-regen on the field note.

The field note is the public Third Wall and had NO post-generation numeric guard
(the last ungated served surface — analyzer and stance already regen; the recap
fails closed by dropping the beat). These lock the new behavior:
  * a canonical-facts contradiction triggers ONE corrective rewrite;
  * the rewrite is kept only if it strictly improves (never regress, never loop);
  * a worse/failed rewrite keeps the original;
  * no computed_metrics record → served unchecked (fail-soft, never blocks).
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))  # canonical_facts / coherence_invariants

import field_notes_lambda as fnl  # noqa: E402
import pytest  # noqa: E402

_FACTS_RECORD = {"date": "2026-07-01", "recovery_pct": 55, "hrv_ms": 38.7, "rhr_bpm": 64, "latest_weight": 301.0}


class _Table:
    """Double for the two table touches these paths make: the computed_metrics
    query (grounding) and the existing-note get_item / put_item (generate)."""

    def __init__(self, facts_record=_FACTS_RECORD):
        self._facts = facts_record
        self.put_items = []

    def query(self, **_kw):
        return {"Items": [dict(self._facts)]} if self._facts else {"Items": []}

    def get_item(self, **_kw):
        return {}

    def put_item(self, Item=None, **_kw):
        self.put_items.append(Item)


@pytest.fixture()
def wired(monkeypatch):
    t = _Table()
    monkeypatch.setattr(fnl, "table", t)
    monkeypatch.setattr(fnl, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(fnl, "gather_week_data", lambda s, e: {})
    monkeypatch.setattr(fnl, "get_prior_notes", lambda w: [])
    monkeypatch.setattr(fnl, "build_prompt", lambda w, d, p: "BASE PROMPT")
    return t


BAD = {"ai_present": "Resting heart rate held at 53 bpm all week.", "ai_tone": "mixed"}
GOOD = {"ai_present": "Resting heart rate held at 64 bpm all week.", "ai_tone": "mixed"}
STILL_BAD = {"ai_present": "Resting heart rate sat at 51 bpm.", "ai_tone": "mixed"}


def test_contradiction_triggers_one_kept_rewrite(wired, monkeypatch):
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return BAD if len(calls) == 1 else GOOD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    fnl.generate_field_notes("2026-W27")
    assert len(calls) == 2
    assert "CORRECTION REQUIRED" in calls[1]
    assert wired.put_items and "64 bpm" in wired.put_items[0]["ai_present"]


def test_worse_rewrite_keeps_original(wired, monkeypatch):
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return BAD if len(calls) == 1 else STILL_BAD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    fnl.generate_field_notes("2026-W27")
    assert len(calls) == 2
    # not improved (1 → 1) — the original ships, never a regression loop
    assert "53 bpm" in wired.put_items[0]["ai_present"]


def test_grounded_note_generates_once(wired, monkeypatch):
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return GOOD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    fnl.generate_field_notes("2026-W27")
    assert len(calls) == 1  # no contradiction → no second call


def test_spelled_out_numbers_are_caught():
    """The SS-10 named gap: every guard was digit-based, so "recovery of twelve"
    passed unchecked. The shared guard normalizes spelled numbers first — but
    "one"/"two" stay words (too ambiguous: "recovery is one of the pillars")."""
    sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
    from grounding_guard import hard_canonical_contradictions

    facts = {"rhr_bpm": 64.0, "recovery_pct": 30.0, "hrv_ms": 25.2}
    assert [h["metric"] for h in hard_canonical_contradictions("Recovery sat at twelve percent.", facts)] == ["Whoop recovery"]
    assert [h["metric"] for h in hard_canonical_contradictions("RHR held at fifty-three.", facts)] == ["resting HR"]
    assert hard_canonical_contradictions("Recovery is one of the pillars.", facts) == []
    assert hard_canonical_contradictions("RHR held at sixty-four all week.", facts) == []  # grounded, spelled


def test_no_facts_record_serves_unchecked(monkeypatch):
    t = _Table(facts_record=None)
    monkeypatch.setattr(fnl, "table", t)
    monkeypatch.setattr(fnl, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(fnl, "gather_week_data", lambda s, e: {})
    monkeypatch.setattr(fnl, "get_prior_notes", lambda w: [])
    monkeypatch.setattr(fnl, "build_prompt", lambda w, d, p: "BASE PROMPT")
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return BAD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    fnl.generate_field_notes("2026-W27")
    assert len(calls) == 1  # fail-soft: no facts → no regen, note still ships
