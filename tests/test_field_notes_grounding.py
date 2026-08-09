"""tests/test_field_notes_grounding.py — the field note on the STANDARD grounding gate.

#2426 upgraded the note's gate from the single-row hard_canonical_contradictions count
(fail-soft to "served unchecked") to the full ``grounding_findings`` chokepoint:
  * allow-list = the generation PROMPT (the week's computed data + prior-note
    excerpts) — a number or calendar date the inputs never contained cannot ship;
  * the canonical-facts contradiction check is kept (note_contradiction_hits, the
    #812 harness path), best-effort;
  * one corrective rewrite, kept only if it strictly improves — and if the best
    draft STILL carries findings the note is HELD (no WEEK# row is written), so
    /api/field_notes never serves failed text (regenerate-once-then-hold);
  * a missing computed_metrics record no longer waves the note through — the
    allow-list classes still gate.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))  # canonical_facts / ai.grounded_generation

import field_notes_lambda as fnl  # noqa: E402
import pytest  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

_FACTS_RECORD = {"date": "2026-07-01", "recovery_pct": 55, "hrv_ms": 38.7, "rhr_bpm": 64, "latest_weight": 301.0}

# The prompt IS the allow-list now — it carries the week's real numbers, exactly as
# build_prompt embeds the gathered data section.
_PROMPT = "BASE PROMPT — this week: resting heart rate 64 bpm, recovery 55 percent."


def _Table(facts_record=_FACTS_RECORD):
    """Double for the table touches these paths make: the computed_metrics query
    (grounding facts) and the existing-note get_item / put_item (generate).
    `seed_store=False` keeps the facts row query()-only — get_item (existing
    note lookup) stays unconditionally empty, as the original stub was."""
    return FakeDdbTable(rows=[dict(facts_record)] if facts_record else [], seed_store=False)


def _stub_side_writers(monkeypatch):
    """Keep the fail-soft side writers (eval retention, QA archive) off AWS —
    a local run with real credentials must never write EVALRET#/qa_archive rows."""
    import common.qa_archive as qa_archive
    import experiment.eval_retention as eval_retention

    monkeypatch.setattr(eval_retention, "retain", lambda *a, **k: True)
    monkeypatch.setattr(qa_archive, "archive_text", lambda *a, **k: None)


@pytest.fixture()
def wired(monkeypatch):
    t = _Table()
    monkeypatch.setattr(fnl, "table", t)
    monkeypatch.setattr(fnl, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(fnl, "gather_week_data", lambda s, e: {})
    monkeypatch.setattr(fnl, "get_prior_notes", lambda w: [])
    monkeypatch.setattr(fnl, "build_prompt", lambda w, d, p: _PROMPT)
    _stub_side_writers(monkeypatch)
    return t


BAD = {"ai_present": "Resting heart rate held at 53 bpm all week.", "ai_tone": "mixed"}
GOOD = {"ai_present": "Resting heart rate held at 64 bpm all week.", "ai_tone": "mixed"}
STILL_BAD = {"ai_present": "Resting heart rate sat at 51 bpm.", "ai_tone": "mixed"}


def test_findings_trigger_one_kept_rewrite(wired, monkeypatch):
    """53 is both a fabricated number (not in the prompt) and a canonical
    contradiction (facts say 64) — one rewrite, and the clean draft publishes."""
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return BAD if len(calls) == 1 else GOOD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    result = fnl.generate_field_notes("2026-W27")
    assert len(calls) == 2
    assert "CORRECTION REQUIRED" in calls[1]
    assert result["status"] == "ok"
    assert wired.puts and "64 bpm" in wired.puts[0]["ai_present"]


def test_unimproved_rewrite_holds_the_note(wired, monkeypatch):
    """Regenerate-once-then-HOLD (#2426): a rewrite that does not improve no longer
    ships the original — nothing is written, so the reader surface serves nothing."""
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return BAD if len(calls) == 1 else STILL_BAD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    result = fnl.generate_field_notes("2026-W27")
    assert len(calls) == 2
    assert result["status"] == "held"
    assert wired.puts == [], "a held note must never reach the WEEK# row /api/field_notes serves"


def test_grounded_note_generates_once(wired, monkeypatch):
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return GOOD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    result = fnl.generate_field_notes("2026-W27")
    assert len(calls) == 1  # no findings → no second call
    assert result["status"] == "ok"
    assert wired.puts and wired.puts[0]["ai_present"] == GOOD["ai_present"]


def test_fabricated_number_without_contradiction_is_caught(wired, monkeypatch):
    """The #2390 class the old gate could not see: a figure the inputs never
    contained but which contradicts no canonical fact (HRV 133 vs facts 38.7 is a
    contradiction; a random '17 workouts' contradicts nothing — it is just invented)."""
    fabricated = {"ai_present": "You logged 17 workouts this week, a personal record.", "ai_tone": "affirming"}
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return fabricated

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    result = fnl.generate_field_notes("2026-W27")
    assert len(calls) == 2  # flagged → one rewrite (same fabrication) → held
    assert result["status"] == "held"
    assert wired.puts == []


def test_no_facts_record_still_gates_on_the_allowlist(monkeypatch):
    """The old gate went fail-soft to 'served unchecked' when the computed_metrics
    row was absent — the exact weakness #2426 names. The allow-list classes gate
    regardless of the facts row."""
    t = _Table(facts_record=None)
    monkeypatch.setattr(fnl, "table", t)
    monkeypatch.setattr(fnl, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(fnl, "gather_week_data", lambda s, e: {})
    monkeypatch.setattr(fnl, "get_prior_notes", lambda w: [])
    monkeypatch.setattr(fnl, "build_prompt", lambda w, d, p: "BASE PROMPT")  # no numbers at all
    _stub_side_writers(monkeypatch)
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return BAD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    result = fnl.generate_field_notes("2026-W27")
    assert len(calls) == 2  # fabricated 53 → rewrite → still fabricated → held
    assert result["status"] == "held"
    assert t.puts == []


def test_broken_gate_holds_never_waves_through(wired, monkeypatch):
    """Fail-closed: if the gate machinery itself dies, the note is held — the
    horizons posture, replacing the old fail-soft 'served unchecked'."""

    def boom(analysis, prompt):
        return [{"type": "gate_error", "detail": "synthetic gate failure"}]

    monkeypatch.setattr(fnl, "_note_grounding_findings", boom)
    calls = []

    def model(prompt, key):
        calls.append(prompt)
        return GOOD

    monkeypatch.setattr(fnl, "_call_notes_model", model)
    result = fnl.generate_field_notes("2026-W27")
    assert result["status"] == "held"
    assert wired.puts == []


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


def test_surface_is_registered_with_the_standard_classes():
    """#2426 acceptance: the module is IN the SURFACES registry (so the wiring guard
    polices it — removing the gate call reds test_grounding_wiring_1967's stale-entry
    direction) with the three armable classes required."""
    from grounding_wiring import SURFACES

    key = "lambdas/intelligence/field_notes_lambda.py::_note_grounding_findings"
    assert key in SURFACES
    assert SURFACES[key]["required"] == frozenset({"numbers", "dates", "freshness"})
    assert set(SURFACES[key]["exempt"]) == {"behavioral", "night"}
