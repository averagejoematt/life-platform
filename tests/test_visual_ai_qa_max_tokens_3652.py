"""tests/test_visual_ai_qa_max_tokens_3652.py — #3652: the AI-vision verdict
budget is a DERIVED number with a pair-contract, not a bare literal.

WHAT WENT WRONG
---------------
`tests/visual_ai_qa.py::_assess_page` sent ``"max_tokens": 700`` — a literal with
nothing pinning it, unlike the coach-v2 cap that `test_ai_calls_coach_v2_max_tokens_3190.py`
guards. The `/coaching/` page's verdict outgrew it, and the consequence was not a
warning: #3540 (correctly) turns a reply cut off at ``max_tokens`` into an explicit
UNEVALUATED FAIL rather than a fabricated ``{"severity": "ok"}`` pass, and — before
#3652's classifier fix — `visual_qa_verdict.py` read that UNEVALUATED string as an
ordinary `site/**` rendering defect. So the site-deploy auto-rollback reverted EVERY
`site/**` merge (runs 34056404335 and 34057051481, 2026-09-06). One unpinned integer
took the whole reader-facing deploy path offline.

WHY A BIGGER BUDGET AND NOT A RETRY
------------------------------------
#2893 is the standing posture: a billed truncation is METERED, not retried
(`tests/test_billed_discarded_ai_2893.py`, and the rule restated at
`lambdas/ai/ai_transport.py` / `lambdas/common/retry_utils.py`). The repo's documented
cure for exactly this class is a budget raise sized against an observed ceiling — the
200 -> 600 -> 1500 walk at `lambdas/ai/ai_calls.py`, whose comment insists the number
comes from the measurement and "not the next round number".

THE MEASUREMENT (all three legs are live evidence, not estimates)
------------------------------------------------------------------
1. **The distribution.** CloudWatch
   ``LifePlatform/AI::AnthropicOutputTokens{LambdaFunction=visual-ai-qa}`` (us-west-2),
   2026-08-26 -> 09-06, the metric's full retained history: **n = 752 calls**,
   p50 158, p90 235, p95 434, p99 637, max 700. That max is CENSORED — 700 was the cap
   — and ``TruncatedResponses{visual-ai-qa}`` Sum = **6** over the same window (0.80%).

2. **The largest COMPLETE verdict + the chars/token ratio.** Run 34057051481
   (2026-09-06 20:32Z) produced a full `/coaching/` verdict at **615 output tokens**;
   the verdict recovered from that run's `report.json` artifact is **1,863 chars** of
   the indented JSON the model actually emits (the truncated reply's stored ``raw``
   confirms the indented+fenced shape) => **3.03 chars/token** for this exact
   model + prompt + page.

3. **What makes `/coaching/` the long one, and its bound.** The #2383 page rule asks
   for one ``undated_ai_band`` issue per AI-authored band. The complete verdict carried
   exactly **7** of them — one per coach in `coach.persona_registry.OPERATIONAL_COACH_IDS`
   — at 163-185 chars each (mean 175 ~= **58 tokens**), over a 641-char fixed scaffold
   (renders_ok / charts_populated / template_gloss / severity / summary) ~= **212 tokens**.
   The rule's own enumeration is broader than the coach cards: "each coach's read card,
   the 'where the board disagrees' tensions band (including 'the integrator's call')" =
   roster + 2 bands, and the generic rendering classes stack on top of the page-rule ones.

   ceiling = 212 + (7 + 2 + 3) * 58 = **908 tokens**

`_VERDICT_MAX_TOKENS = 1200` is that ceiling plus 32% margin, and ~2.0x the largest
complete verdict ever observed. It stays below the reader-truth judge's 1500, which
covers a 4-6 page BATCH rather than one page, so the two budgets stay ordered the way
their workloads are.

WHAT THIS TEST PROVES (and why each half is needed)
----------------------------------------------------
* the call site must reference the NAMED constant — a second bare literal is exactly how
  #3190's five-copy drift happened, and how this one was born;
* the constant must satisfy the inequality re-derived from the LIVE roster, so growing
  the coaching board without growing the budget reds a test instead of reverting a
  deploy (that is the pair-contract half, and it is the part that makes the number
  maintainable rather than merely correct today);
* the constant must clear the 700 that demonstrably truncated and the 615 that
  demonstrably fit — a floor no future "tidy-up" can quietly slide back under.

Mutation-proof (re-run locally 2026-09-06): setting `_VERDICT_MAX_TOKENS = 700` reds
both `test_verdict_budget_covers_the_derived_page_rule_ceiling` and
`test_verdict_budget_clears_the_two_measured_landmarks`; putting the literal back inline
in `_assess_page` reds `test_the_verdict_budget_is_a_named_constant_not_an_inline_literal`.
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_VISUAL_AI_QA_PATH = os.path.join(_HERE, "visual_ai_qa.py")

# ── the measured derivation, restated as numbers the inequality can use ──────
#
# Every one of these comes from evidence leg 2/3 in the docstring above; none is a
# guess. They are module-level so a future re-measure edits them here, in one place,
# next to the window they were measured over.
SCAFFOLD_TOKENS = 212  # 641 chars of non-issues[] verdict / 3.03 chars-per-token
TOKENS_PER_ISSUE = 58  # mean 175 chars per issue object / 3.03
NON_COACH_BANDS = 2  # the tensions band + "the integrator's call" (#2383's own wording)
GENERIC_ISSUE_HEADROOM = 3  # the generic rendering classes stack on top of the page rule

# The two landmarks the live runs established, both in output tokens.
TRUNCATED_AT = 700  # run 34056404335 — cut off, page went UNEVALUATED, deploy reverted
LARGEST_COMPLETE_VERDICT = 615  # run 34057051481 — the same page, 7 issues, complete

_MAX_TOKENS_LITERAL_RE = re.compile(r'"max_tokens":\s*(\d+)')
_ASSESS_PAGE_RE = re.compile(r"^def _assess_page\(", re.MULTILINE)
_NEXT_TOPLEVEL_DEF_RE = re.compile(r"\ndef [A-Za-z_]")


def _read_source():
    with open(_VISUAL_AI_QA_PATH, encoding="utf-8") as f:
        return f.read()


def _assess_page_body(source):
    """Slice `_assess_page`'s real body — the shipped source, never a fixture copy."""
    m = _ASSESS_PAGE_RE.search(source)
    assert m, "could not find `def _assess_page(` in tests/visual_ai_qa.py — has it moved or been renamed?"
    rest = source[m.start() :]
    end = _NEXT_TOPLEVEL_DEF_RE.search(rest[1:])
    assert end, "could not find the next top-level `def` after _assess_page — the slice would run to EOF"
    return rest[: end.start() + 1]


def _declared_budget(source):
    m = re.search(r"^_VERDICT_MAX_TOKENS = (\d+)$", source, re.MULTILINE)
    assert m, (
        "tests/visual_ai_qa.py no longer declares `_VERDICT_MAX_TOKENS = <int>` at module level. "
        "#3652 named this budget precisely so its derivation could live beside it and be re-checked; "
        "if it moved, move this guard with it deliberately."
    )
    return int(m.group(1))


def test_the_verdict_budget_is_a_named_constant_not_an_inline_literal():
    """The bug was born as a bare `"max_tokens": 700` in the request body. A named
    constant is not cosmetics here: it is what gives the number somewhere to carry its
    derivation, and what stops a second call site growing its own copy (the #3190
    five-literal shape, one level down)."""
    source = _read_source()
    body = _assess_page_body(source)

    assert "_VERDICT_MAX_TOKENS" in body, "_assess_page must send the named budget, not an inline number"
    inline = _MAX_TOKENS_LITERAL_RE.findall(body)
    assert not inline, f"_assess_page still hardcodes max_tokens={inline} — route it through _VERDICT_MAX_TOKENS (#3652)"

    # ...and the constant must not be shadowed by a second literal anywhere else in the
    # module's request-building code.
    everywhere = _MAX_TOKENS_LITERAL_RE.findall(source)
    assert (
        not everywhere
    ), f"tests/visual_ai_qa.py carries bare max_tokens literal(s) {everywhere} — every budget must be a named, derived constant"


def test_verdict_budget_covers_the_derived_page_rule_ceiling():
    """The pair contract. The #2383 `/coaching/` rule asks for one issue per AI-authored
    band, so the verdict's length is a FUNCTION OF THE ROSTER — which is why this reads
    the roster live instead of hardcoding 7. Add a coach without raising the budget and
    this reds; that is the whole point, because the alternative feedback channel is a
    reverted production deploy."""
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    roster = len(OPERATIONAL_COACH_IDS)
    assert roster >= 1, "the operational coach roster came back empty — this guard would be measuring nothing"

    bands = roster + NON_COACH_BANDS
    required = SCAFFOLD_TOKENS + (bands + GENERIC_ISSUE_HEADROOM) * TOKENS_PER_ISSUE
    budget = _declared_budget(_read_source())

    assert budget >= required, (
        f"_VERDICT_MAX_TOKENS={budget} cannot carry the verdict the /coaching/ page rule asks for: "
        f"{roster} operational coach read card(s) + {NON_COACH_BANDS} non-coach band(s) + "
        f"{GENERIC_ISSUE_HEADROOM} generic rendering issue(s) = {SCAFFOLD_TOKENS} scaffold + "
        f"{bands + GENERIC_ISSUE_HEADROOM} x {TOKENS_PER_ISSUE} tok = {required} tokens. "
        f"Either the board grew without the budget growing with it, or the budget was lowered "
        f"below what the prompt itself asks for — both sides move together (#3652)."
    )


def test_verdict_budget_clears_the_two_measured_landmarks():
    """A floor from the live runs themselves, independent of the arithmetic above: the
    budget must sit clear of the value that demonstrably truncated (700) and well clear
    of the largest verdict that demonstrably fit (615). Margin is stated, not implied."""
    budget = _declared_budget(_read_source())
    assert (
        budget > TRUNCATED_AT
    ), f"_VERDICT_MAX_TOKENS={budget} is at or below the {TRUNCATED_AT} that truncated /coaching/ in run 34056404335"
    assert budget >= 1.5 * LARGEST_COMPLETE_VERDICT, (
        f"_VERDICT_MAX_TOKENS={budget} leaves under 50% headroom over the largest COMPLETE verdict "
        f"measured ({LARGEST_COMPLETE_VERDICT} output tokens, run 34057051481) — a judge one issue "
        f"longer than that run would truncate again, and a truncation here reverts a live deploy."
    )
