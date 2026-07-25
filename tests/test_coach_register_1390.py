"""tests/test_coach_register_1390.py — the tone dial's byte-identity guarantee (#1390).

AC#1: a register switch produces byte-identical deterministic payloads (numbers, verdicts,
citations) across all three registers — only the phrasing layer varies. These tests diff the
structured content across registers and prove it, and lock the structural properties that
make the guarantee hold (the deterministic builder takes no register; the phrasing is strictly
downstream of the payload block).
"""

import itertools
import os
import sys

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
sys.path.insert(0, _LAMBDAS)

import coach_register as cr  # noqa: E402

# A representative deterministic fact bundle — the kind of pre-computed content a coach
# surface would hand the phrasing layer.
_FACTS = {
    "metrics": [
        {"name": "hrv_7d_avg", "value": 48.0, "unit": "ms", "confidence": "moderate"},
        {"name": "sleep_debt", "value": 3.4, "unit": "h"},
        {"name": "protein_pct_target", "value": 82, "unit": "%"},
    ],
    "verdicts": [
        {"claim": "sleep_short_streak", "verdict": "3 nights under 6h", "n": 3},
        {"claim": "hrv_vs_baseline", "verdict": "below baseline", "n": 47, "p": 0.03},
    ],
    "citations": [
        {"source": "whoop", "ref": "recovery 2026-07-24"},
        {"source": "macrofactor", "ref": "log 2026-07-23"},
    ],
    "extra_context": {"week_num": 1},
}


def test_all_three_registers_exist():
    assert cr.registers() == ["clinical", "blunt", "warm"]
    for r in cr.registers():
        assert cr.REGISTERS[r]["phrasing"].strip(), r


def test_deterministic_payload_is_register_independent_by_signature():
    """Structural: the deterministic builder cannot vary by register because register is
    not one of its parameters."""
    import inspect

    params = inspect.signature(cr.build_deterministic_payload).parameters
    assert "register" not in params
    assert list(params) == ["facts"]


def test_payload_bytes_identical_across_registers():
    """AC#1 core: the serialized deterministic payload is byte-identical for every register."""
    serialized = {r: cr.serialize_payload(cr.build_deterministic_payload(_FACTS)) for r in cr.registers()}
    for a, b in itertools.combinations(cr.registers(), 2):
        assert serialized[a] == serialized[b], f"payload differs between {a} and {b}"


def test_composed_prompt_deterministic_slice_is_byte_identical():
    """AC#1 end-to-end: the region between the payload sentinels in the FULL composed prompt
    is byte-identical across registers — the numbers/verdicts/citations cannot move."""
    payload = cr.build_deterministic_payload(_FACTS)
    slices = {r: cr.extract_deterministic_slice(cr.compose_coach_prompt(payload, r)) for r in cr.registers()}
    ref = slices["clinical"]
    for r in cr.registers():
        assert slices[r] == ref, f"deterministic slice for {r} diverged from clinical"
    # And the slice actually carries the facts (non-vacuous).
    assert "hrv_7d_avg" in ref and "below baseline" in ref and "macrofactor" in ref


def test_phrasing_tails_actually_differ():
    """The whole point of a dial: the phrasing AFTER the payload differs per register."""
    payload = cr.build_deterministic_payload(_FACTS)
    tails = {}
    for r in cr.registers():
        prompt = cr.compose_coach_prompt(payload, r)
        tails[r] = prompt.split(cr.PAYLOAD_CLOSE, 1)[1]
    for a, b in itertools.combinations(cr.registers(), 2):
        assert tails[a] != tails[b], f"phrasing tails identical for {a} and {b} — the dial does nothing"
    assert "CLINICAL" in tails["clinical"]
    assert "BLUNT" in tails["blunt"]
    assert "WARM" in tails["warm"]


def test_numbers_verdicts_citations_all_present_and_stable():
    """The three deterministic categories the AC names are all serialized, and integral
    floats canonicalize stably (48.0 -> 48) so bytes don't wobble."""
    payload = cr.build_deterministic_payload(_FACTS)
    assert {m["name"] for m in payload["metrics"]} == {"hrv_7d_avg", "sleep_debt", "protein_pct_target"}
    hrv = next(m for m in payload["metrics"] if m["name"] == "hrv_7d_avg")
    assert hrv["value"] == 48 and isinstance(hrv["value"], int)  # 48.0 collapsed
    assert len(payload["verdicts"]) == 2 and len(payload["citations"]) == 2
    assert payload["extra"]["extra_context"] == {"week_num": 1}  # nothing silently dropped


def test_unknown_register_degrades_to_default_not_raise():
    payload = cr.build_deterministic_payload(_FACTS)
    prompt = cr.compose_coach_prompt(payload, "nonsense")
    # degraded to default (clinical) — same deterministic slice, clinical tail
    assert cr.extract_deterministic_slice(prompt) == cr.extract_deterministic_slice(cr.compose_coach_prompt(payload, "clinical"))
    assert "CLINICAL" in prompt
    assert cr.normalize_register(None) == cr.DEFAULT_REGISTER


def test_honest_absence_empty_facts_no_fabrication():
    """An empty fact bundle yields empty sections, never invented values (ADR-104)."""
    payload = cr.build_deterministic_payload({})
    assert payload["metrics"] == [] and payload["verdicts"] == [] and payload["citations"] == []
