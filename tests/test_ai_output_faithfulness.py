"""ER-03 Layer 1 — AI-output faithfulness harness (offline, GATING).

`visual_ai_qa.py` verifies pages *render*; this verifies the coach/insight AI
*content* obeys the standard the platform sells: correlative-only (never causal),
confidence-labelled at small N, no number that wasn't in the input (anti-
fabrication / no LLM arithmetic), and no "Matthew"-prefixed opening.

Two parts, both offline (no AWS, no inference) so CI can gate on them:
  1. A labelled corpus (tests/fixtures/ai_inputs/faithfulness_cases.json) of
     (input -> output) pairs — good outputs must pass, planted-bad outputs must
     fail with the expected reason. Seeding a fabricated number, a causal claim,
     or an unlabelled small-N finding makes the gate (and this test) fail.
  2. A wiring-coverage guard: the reader-facing AI paths that are SUPPOSED to be
     gated must still route through er03_gate — so a future refactor can't
     silently drop the truthfulness gate from a publish path.

The deterministic engine is lambdas/er03_gate.py (the same gate the coach
daily-reflection batch and The Panel already enforce at publish time). This
harness is held to the standard it enforces: it asserts behaviour, it does not
fake confidence. Layer 2 (a budget-gated Haiku judge vs an in-repo rubric) is
intentionally deferred — see docs/specs/ER_EXTERNAL_REVIEW_RIGOR_2026-06-09.md.
"""

import json
import os

# er03_gate lives in lambdas/ (shipped in the layer). The test runner puts lambdas/
# on sys.path via conftest; import directly.
import er03_gate
import pytest

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ai_inputs", "faithfulness_cases.json")
_LAMBDAS = os.path.join(os.path.dirname(__file__), os.pardir, "lambdas")


def _load_cases():
    with open(_FIXTURE) as f:
        return json.load(f)["cases"]


_CASES = _load_cases()


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_faithfulness_corpus(case):
    """Each labelled (input -> output) pair gets the verdict ER-03 promises."""
    ok, reasons = er03_gate.er03_check(
        case["output"],
        allowed_numbers=case.get("input_numbers") or [],
        n=case.get("n"),
    )
    if case["expect_ok"]:
        assert ok, f"{case['id']}: expected PASS but gate held it — {reasons}"
    else:
        assert not ok, f"{case['id']}: expected the gate to HOLD this output, but it passed"
        want = case.get("expect_reason")
        if want:
            joined = " | ".join(reasons).lower()
            assert want.lower() in joined, f"{case['id']}: expected reason ~{want!r}, got {reasons}"


def test_corpus_covers_all_failure_classes():
    """The corpus must keep exercising every failure class — guard against a
    future edit that quietly deletes the planted-bad cases to make CI green."""
    reasons = " ".join(
        " ".join(er03_gate.er03_check(c["output"], c.get("input_numbers") or [], c.get("n"))[1]) for c in _CASES if not c["expect_ok"]
    ).lower()
    assert "fabricated number" in reasons, "no fabricated-number case in corpus"
    assert "causal connective" in reasons, "no causal-connective case in corpus"
    assert "unhedged claim" in reasons, "no unhedged-small-N case in corpus"
    assert "matthew" in reasons, "no 'Matthew'-opener case in corpus"
    assert any(c["expect_ok"] for c in _CASES), "corpus must include good cases that PASS"


# Reader-facing AI paths that publish to a human surface and MUST stay gated.
# A path here that stops referencing er03_gate has silently lost its truthfulness
# gate — the exact regression this guard exists to catch.
_GATED_PATHS = [
    os.path.join("compute", "coach_daily_reflection_lambda.py"),
    os.path.join("emails", "coach_panel_podcast_lambda.py"),
]


@pytest.mark.parametrize("rel", _GATED_PATHS)
def test_reader_facing_paths_stay_gated(rel):
    path = os.path.join(_LAMBDAS, rel)
    assert os.path.exists(path), f"gated path moved/removed: {rel} — update _GATED_PATHS"
    with open(path) as f:
        src = f.read()
    assert "er03_gate" in src, f"{rel} no longer routes output through er03_gate (truthfulness gate dropped)"
