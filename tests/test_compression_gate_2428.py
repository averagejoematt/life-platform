"""tests/test_compression_gate_2428.py — #2428: the compression path onto the module's own gate.

THE SEAM (#2390 census, 2026-08-09)
-----------------------------------
coach_history_summarizer's stance path was gated and registered (#534/#2195) while the
COMPRESSED#latest compression — written by the same module, from the same Haiku seam —
was not. The compressed state replays into board-answer prompt assembly
(site_api_ai_lambda._coach_memory_bits): an internal input laundered into a reader
surface. A fabricated figure in the compression became silent context for every
subsequent board answer.

WHAT #2428 SHIPPED, AND WHAT THIS FILE PINS
-------------------------------------------
* `_apply_compression_gate` — the module's own gate idiom, reused: allow-list from the
  compression's OWN inputs, one corrective regen via the shared `regen_once` harness,
  registered in tests/grounding_wiring.SURFACES with the same arms as the stance surface.
* HOLD semantics: surviving findings keep the prior COMPRESSED#latest (the handler skips
  the write) or, with no prior, the deterministic structural fallback stands in. A
  compression that still cites an untraceable number is never written.
* Reader-side exclusion: `_coach_memory_bits` serves only rows the gate stamped
  (`grounding_gated`) — ungated legacy state is excluded until regenerated.

THE MUTATION PROOF
------------------
`test_compress_coach_routes_through_the_gate` is the census-side tripwire: remove the
gate call from `_compress_coach` and it reds (the wiring registry alone cannot see a
dropped CALL SITE while the gate function still exists). The behavioral half is
`test_fabricated_number_never_reaches_compressed_latest`: the REAL gate, a REAL
fabricated number, and the write path observed end-to-end through `lambda_handler`.
"""

import ast
import inspect
import json
import os
import sys
import textwrap

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import coach_history_summarizer as chs  # noqa: E402

MODULE = "lambdas/coach/coach_history_summarizer.py"


def _state():
    """A minimal real coach state — one output, no threads/predictions."""
    return {
        "outputs": [{"sk": "OUTPUT#2026-08-01#brief", "summary": "Sleep consistency improving without regressions.", "themes": []}],
        "open_threads": [],
        "active_predictions": [],
        "confidence_records": [],
        "relationship_state": None,
        "voice_state": None,
        "interactions": [],
        "learning_outcomes": [],
    }


FABRICATED = {
    # 43 bpm / 17.4 appear nowhere in the compression message — the exact laundering
    # class from the census: model-introduced figures entering coach memory.
    "summary": "Matthew's resting heart rate hit 43 bpm this week, a 17.4 percent improvement he never logged.",
    "key_concerns": [],
}

CLEAN = {
    "summary": "Sleep consistency remains the focus; the coach sees steady adherence and no open disputes.",
    "key_concerns": ["evening wind-down drift"],
}


def _wire_haiku(monkeypatch, payload):
    calls = []

    def fake_haiku(system, user_message, max_tokens=1500, temperature=0.2):
        calls.append(user_message)
        return dict(payload)

    monkeypatch.setattr(chs, "_call_haiku", fake_haiku)
    return calls


def test_fabricated_number_never_reaches_compressed_latest(monkeypatch):
    """A compression citing an untraceable number is held — the prior row survives."""
    calls = _wire_haiku(monkeypatch, FABRICATED)
    prior = {"summary": "prior clean summary", "grounding_gated": True, "compressed_at": "2026-08-02T14:00:00+00:00"}
    monkeypatch.setattr(chs, "_get_item", lambda pk, sk: dict(prior) if sk == "COMPRESSED#latest" else None)

    result = chs._compress_coach("sleep_coach", _state())

    assert result.get("_held") is True
    assert result["summary"] == "prior clean summary"
    assert "43" not in json.dumps(result)
    # the gate spent its ONE corrective regen before holding
    assert len(calls) == 2
    assert "43" not in calls[0], "the fabricated figure must come from the model, not the prompt"


def test_hold_without_prior_falls_back_to_the_deterministic_state(monkeypatch):
    """No prior to hold to => the structural fallback stands in, never the fabrication."""
    _wire_haiku(monkeypatch, FABRICATED)
    monkeypatch.setattr(chs, "_get_item", lambda pk, sk: None)

    result = chs._compress_coach("sleep_coach", _state())

    assert result.get("_fallback") is True
    assert result.get("grounding_gated") is True  # deterministic-by-construction
    blob = json.dumps(result)
    assert "43" not in blob and "17.4" not in blob


def test_clean_compression_is_stamped_gated_and_written(monkeypatch):
    """The passing path: gated stamp on, no hold, and the handler writes it."""
    _wire_haiku(monkeypatch, CLEAN)
    monkeypatch.setattr(chs, "_get_item", lambda pk, sk: None)

    result = chs._compress_coach("sleep_coach", _state())

    assert result.get("_held") is None and result.get("_fallback") is None
    assert result.get("grounding_gated") is True
    assert result["summary"] == CLEAN["summary"]


def test_handler_skips_the_write_on_a_held_compression(monkeypatch):
    """held => the prior COMPRESSED#latest row stays; this run writes nothing."""
    monkeypatch.setattr(chs, "_gather_coach_state", lambda cid: _state())
    monkeypatch.setattr(chs, "_presence_signal", lambda: None)
    monkeypatch.setattr(chs, "_run_stance", lambda *a, **k: {"written": False, "reason": "test"})
    monkeypatch.setattr(chs, "_compress_coach", lambda cid, state, presence_signal=None: {"summary": "prior clean summary", "_held": True})
    writes = []
    monkeypatch.setattr(chs, "_write_compressed_state", lambda cid, compressed: writes.append((cid, compressed)) or True)

    out = chs.lambda_handler({"coach_ids": ["sleep_coach"]}, None)

    assert writes == []
    assert out["results"]["sleep_coach"]["status"] == "held_kept_prior"


def test_handler_writes_a_gated_compression(monkeypatch):
    monkeypatch.setattr(chs, "_gather_coach_state", lambda cid: _state())
    monkeypatch.setattr(chs, "_presence_signal", lambda: None)
    monkeypatch.setattr(chs, "_run_stance", lambda *a, **k: {"written": False, "reason": "test"})
    monkeypatch.setattr(chs, "_compress_coach", lambda cid, state, presence_signal=None: {"summary": "ok", "grounding_gated": True})
    writes = []
    monkeypatch.setattr(chs, "_write_compressed_state", lambda cid, compressed: writes.append((cid, compressed)) or True)

    out = chs.lambda_handler({"coach_ids": ["sleep_coach"]}, None)

    assert len(writes) == 1
    assert writes[0][1].get("grounding_gated") is True
    assert out["results"]["sleep_coach"]["status"] == "success"


def test_compress_coach_routes_through_the_gate():
    """The census tripwire: dropping the gate CALL from the compression path reds here.

    The wiring registry (tests/grounding_wiring.py) guards the gate FUNCTION's arms;
    it cannot see a removed call site while the function still exists. This assertion
    closes that seam — together they make 'the compression call passes the gate' a
    guarded property, not a convention.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(chs._compress_coach)))
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_apply_compression_gate" in calls


def test_surface_registered_and_census_defect_closed():
    """#2428's acceptance in the two registries: SURFACES gained the compression
    writer; the census no longer tracks the module as a known-ungated reader path."""
    from grounding_wiring import SURFACES
    from test_invoke_site_census_2390 import DECLARED_OVERLAPS, UNGATED_READER_KNOWN

    assert f"{MODULE}::_apply_compression_gate" in SURFACES
    assert MODULE not in UNGATED_READER_KNOWN
    assert MODULE not in DECLARED_OVERLAPS


class _FakeTable:
    def __init__(self, row):
        self.row = row

    def get_item(self, Key):
        return {"Item": self.row} if self.row is not None else {}


def test_board_prompt_serves_only_gated_compressed_state(monkeypatch):
    """site_api_ai_lambda._coach_memory_bits: an ungated legacy row is excluded;
    a gated row serves exactly as before."""
    from web import site_api_ai_lambda as ai

    legacy = {"summary": "legacy ungated memory", "key_concerns": []}
    gated = {"summary": "gated memory", "key_concerns": ["one concern"], "grounding_gated": True}

    monkeypatch.setattr(ai, "table", _FakeTable(legacy))
    assert ai._coach_memory_bits("sleep_coach") == ""

    monkeypatch.setattr(ai, "table", _FakeTable(gated))
    bits = ai._coach_memory_bits("sleep_coach")
    assert "gated memory" in bits and "one concern" in bits
