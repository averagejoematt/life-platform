"""tests/test_grounding_number_tolerance_2290.py — #2290: the gate's numeric match window.

`fabricated_numbers` accepted any output number within **0.01** of an allowed one. That
window exists for a good reason — a narrative surface that legitimately rounds should not
be refused — but a corruption that lands inside it passes the gate *regardless of what is
on the allow-list*. #2276 narrowed the allow-list (intersecting it with the source payload
so a prompt truncation can't enlarge the gate's vocabulary) and deliberately left the
tolerance alone; the two are independent.

**A correction to #2290's own framing, measured here.** The issue illustrates the hole with
74.61 → 74.62. That example does **not** reproduce: the comparison is a strict `<`, and in
binary floating point `abs(74.62 - 74.61)` evaluates to 0.010000000000005116 — a hair ABOVE
the window — so 74.62 is already flagged today. The defect is real but needs one more digit
of precision than the issue suggests. Measured exploitable band against an allowed 74.61:
74.6101 through 74.6199 pass; 74.62 and 74.60 do not. The tests below use **74.618**, which
is inside the window by construction rather than by luck.

The decision recorded here, per surface:

* **Narrative surfaces keep `NUMBER_TOLERANCE_TOLERANT` (0.01)** — the default, so every
  existing caller's behaviour is byte-identical. Their gate is an internal quality check,
  and refusing an honest rounding costs more than the near-miss class buys.
* **`/api/explain` gets `NUMBER_TOLERANCE_EXACT`** — there the gate IS the honesty claim
  being made to a reader (ADR-104). The endpoint's own refusal copy says *"I'd rather not
  narrate numbers I can't ground in this page's data."* That sentence is only true to two
  decimal places under the tolerant window.

EXACT is not punitive: rounding is handled by a separate rule (`_is_restatement`), which
generalises the old integer-restatement branch ("64 for 64.2") to every precision. So
`/api/explain` may still say "74.6" for 74.61. What it may not do is say "74.62".
"""

import pytest
from ai.grounded_generation import (
    NUMBER_TOLERANCE_EXACT,
    NUMBER_TOLERANCE_TOLERANT,
    fabricated_numbers,
    grounding_findings,
)

# 74.61 is deliberately not near any benign number and has a meaningful third digit.
_ALLOWED = {74.61, 218.4, 1523.0}


# ── The defect ────────────────────────────────────────────────────────────────
def test_a_corrupted_trailing_decimal_passes_the_tolerant_window():
    """The behaviour #2290 exists to characterise — pinned so the trade-off is visible
    rather than implied. 74.618 is not in the allow-list and is not a rounding of 74.61;
    it is grounded ONLY because it sits inside the 0.01 window."""
    assert fabricated_numbers("Body fat read 74.618 percent.", _ALLOWED, tolerance=NUMBER_TOLERANCE_TOLERANT) == []


def test_exact_mode_refuses_the_same_corrupted_trailing_decimal():
    assert fabricated_numbers("Body fat read 74.618 percent.", _ALLOWED, tolerance=NUMBER_TOLERANCE_EXACT) == [74.618]


# ── EXACT is not punitive: real roundings still pass ──────────────────────────
@pytest.mark.parametrize(
    "restatement",
    [
        "74.61",  # verbatim
        "74.6",  # one decimal
        "75",  # integer — the old integer-restatement branch
        "218.4",  # verbatim, one already at 1dp
        "218",  # its integer form
    ],
)
def test_exact_mode_still_accepts_a_genuine_rounding(restatement):
    """If EXACT refused these, /api/explain would serve its refusal copy constantly and the
    tightening would be a usability regression rather than an honesty win."""
    assert fabricated_numbers(f"The figure was {restatement}.", _ALLOWED, tolerance=NUMBER_TOLERANCE_EXACT) == []


def test_exact_mode_still_refuses_an_outright_fabrication():
    assert fabricated_numbers("Recovery sat at 88.7 percent.", _ALLOWED, tolerance=NUMBER_TOLERANCE_EXACT) == [88.7]


# ── The default is unchanged, which is what protects every other caller ───────
def test_the_default_tolerance_is_the_historical_one():
    """Acceptance 4: existing narrative callers' behaviour is unchanged. If this flips,
    every surface silently tightens at once — the thing #2290 said not to do."""
    assert NUMBER_TOLERANCE_TOLERANT == 0.01
    assert fabricated_numbers("Body fat read 74.618 percent.", _ALLOWED) == []


def test_grounding_findings_threads_the_parameter():
    """The gate entrypoint most callers use must be able to select the mode, or the
    parameter is unreachable from where it matters."""
    tolerant = grounding_findings("Body fat read 74.618 percent.", allowed=_ALLOWED)
    exact = grounding_findings("Body fat read 74.618 percent.", allowed=_ALLOWED, number_tolerance=NUMBER_TOLERANCE_EXACT)
    assert tolerant == []
    assert [f["type"] for f in exact] == ["fabricated_number"]
    assert exact[0]["claimed"] == 74.618


# ── The call site, asserted structurally (acceptance 3) ───────────────────────
# A behavioural test of /api/explain would need a live Bedrock call. What is checkable
# offline — and what actually regresses — is whether the endpoint still ASKS for the exact
# window. The anchor is the CONSTANT, not one kwarg spelling: the call site passes it via a
# small dict so `**cycle_gate_params()` stays literally visible at the call, which
# tests/test_grounding_wiring_1967.py requires in order to see the freshness class armed.
# Anchoring on the spelling would break on that refactor while the behaviour was intact.
def test_api_explain_asks_for_the_exact_window():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "lambdas" / "web" / "site_api_ai_lambda.py").read_text(encoding="utf-8")
    handler = src[src.index("def _handle_explain") :]
    handler = handler[: handler.index("\ndef ", 10)]
    assert "_gg.NUMBER_TOLERANCE_EXACT" in handler, (
        "/api/explain no longer requests the exact numeric window (#2290). Its refusal copy "
        "claims it will not narrate numbers it cannot ground in the page's data; under the "
        "tolerant window that claim is only true to two decimal places."
    )


def test_no_other_caller_was_tightened_by_accident():
    """Acceptance 4, derived: exactly one call site opts in. A blanket tightening is the
    outcome #2290 explicitly ruled out, and it would be easy to do by editing the default."""
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    out = subprocess.run(
        ["git", "grep", "-l", "NUMBER_TOLERANCE_EXACT", "--", "lambdas", "mcp"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert sorted(out) == [
        "lambdas/ai/grounded_generation.py",  # where it is defined
        "lambdas/web/site_api_ai_lambda.py",  # /api/explain, the one opted-in surface
    ], f"the exact window spread beyond /api/explain without a recorded decision: {sorted(out)}"


def test_the_issues_own_example_was_already_caught():
    """Recorded because it changed what this PR had to test, not as trivia.

    #2290 illustrates the hole with 74.61 -> 74.62. Under a strict `<` comparison and
    binary floating point that difference is 0.010000000000005116 — just ABOVE the window
    — so the example is already refused. Exploiting the gap needs a third decimal. If a
    future edit makes the comparison `<=`, this test reds and the illustrative example
    starts passing for real.
    """
    assert fabricated_numbers("Body fat read 74.62 percent.", {74.61}) == [74.62]
    assert fabricated_numbers("Body fat read 74.60 percent.", {74.61}) == []  # a rounding, not a near-miss
