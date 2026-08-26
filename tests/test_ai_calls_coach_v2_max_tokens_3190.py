"""tests/test_ai_calls_coach_v2_max_tokens_3190.py — #3190: pair-contract guard
tying the coach-v2 generation prompt's word budget to the `max_tokens` cap at
all five `_run_coach_v2_pipeline` call sites in `lambdas/ai/ai_calls.py`.

THE BUG THIS GUARDS AGAINST
----------------------------
Every coach-v2 generation shares ONE `system_prompt` and ONE `user_message_full`
across five `call_anthropic(..., system=system_prompt)` sites in
`_run_coach_v2_pipeline`: the initial generation, the grounding-gate correction
arm, the ADR-108 quality-gate regenerate arm, the presence-ack regenerate arm,
and the self-graded-verdict regenerate arm. All five used to hardcode
`max_tokens=600`. The prompt had NO explicit length instruction ("Write 2-4
paragraphs..." with no word count), so nothing bounded how long a generation
tried to be — measured 2026-08-24/08-25: 14 and 13 truncation WARNs
(`output_tokens=600` exactly, i.e. `stop_reason` was the token cap, not a
natural stop), and `nutrition_coach` held for three consecutive cycles
(ADR-108 quality-gate scores 62 -> 58 -> 28) because the REGENERATE arm the
gate calls to fix a bad draft was capped at the same 600 tokens and truncated
identically. A fix that only raised the initial call's cap would have left the
regen arms — the ones the quality gate actually depends on to self-correct —
truncating exactly when invoked.

THE ARITHMETIC (full derivation in PR #3190's body)
-----------------------------------------------------
`_run_coach_v2_pipeline`'s system prompt now instructs "target 300-450 words,
and do not exceed 500 words." 500 words was chosen from real production data,
not guessed: a query of 240 gate-passed OUTPUT# rows across all 8 coach-v2
domains (pre-regression) measured word_count p95=472, p99=492, max=500 — 500
is the real historical ceiling this coach has already written to, not an
arbitrary number invented for this issue. At the task's stated ~1.4
tokens/word for prose, 500 words ~= 700 tokens; cross-checked against the
production truncation evidence itself (max_tokens=600 output consistently cut
at output_tokens=600 with text_length 1901-1952 chars, i.e. ~3.2 chars/token
for this model+content), a 500-word/~2950-char ceiling projects to ~920
tokens. Both independent estimates land in the 700-925 token range;
`max_tokens=1000` was chosen as a cap with ~8-30% margin above both.

WHAT THIS TEST ACTUALLY PROVES
-------------------------------
A test that just imports a shared constant and checks it once would not catch
a regression where one of the five call sites drifts back to a hardcoded
literal (exactly how this bug was introduced by the original 600 in five
places). So this test parses the REAL SOURCE of `_run_coach_v2_pipeline` in
`lambdas/ai/ai_calls.py` — the file that actually ships — and asserts, from
the source text itself:

  1. There are exactly five `call_anthropic(..., system=system_prompt)` call
     sites inside `_run_coach_v2_pipeline` (a count regression — someone
     adding or removing a call site without noticing — is itself a finding).
  2. Every one of those five sites carries the SAME `max_tokens=<N>` integer
     literal — no site may drift from its siblings.
  3. The prompt text (the same source slice) states a "do not exceed <W>
     words" ceiling — the pair's other half must exist at all.
  4. N >= W * TOKENS_PER_WORD_ESTIMATE (the pair-contract inequality) — if a
     future change raises the word budget without raising the token cap to
     match, or lowers the cap without lowering the word budget, this fails.

Mutation-proof (reported in PR #3190's body): temporarily hand-editing ONE
call site's `max_tokens=1000` down to a different literal (breaking check #2)
reds this test; reverting turns it green again. Same for lowering the shared
cap below the word-budget floor (breaking check #4).
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_AI_CALLS_PATH = os.path.join(_REPO, "lambdas", "ai", "ai_calls.py")

# The task's own prose-token heuristic (~1.4 tokens/word for English narrative
# text) — see the docstring above and the PR body for the cross-check against
# the measured production chars-per-token ratio.
TOKENS_PER_WORD_ESTIMATE = 1.4

_PIPELINE_START_RE = re.compile(r"^def _run_coach_v2_pipeline\(", re.MULTILINE)
_NEXT_TOPLEVEL_DEF_RE = re.compile(r"\ndef [A-Za-z_]")
_WORD_BUDGET_RE = re.compile(r"do not exceed (\d+) words")
_CALL_SITE_RE = re.compile(r"call_anthropic\(")
_MAX_TOKENS_RE = re.compile(r"max_tokens=(\d+)")
_SYSTEM_PROMPT_RE = re.compile(r"system=system_prompt")


def _read_source():
    with open(_AI_CALLS_PATH, encoding="utf-8") as f:
        return f.read()


def _pipeline_body(source):
    """Slice out `_run_coach_v2_pipeline`'s full body: from its `def` line to
    the next top-level `def` (i.e. `call_sleep_coach_v2`, the first of the
    thin per-domain wrappers). This is the ONE function all five coach-v2
    generation call sites live in — sliced so the test only ever inspects the
    real shipped source, never a hand-copied fixture that could drift from it.
    """
    m = _PIPELINE_START_RE.search(source)
    assert m, "could not find `def _run_coach_v2_pipeline(` in lambdas/ai/ai_calls.py — has it moved or been renamed?"
    rest = source[m.start() :]
    end_m = _NEXT_TOPLEVEL_DEF_RE.search(rest[1:])
    assert end_m, "could not find the next top-level `def` after _run_coach_v2_pipeline — slice would run to EOF"
    return rest[: end_m.start() + 1]


def _call_site_windows(body):
    """One text window per `call_anthropic(` occurrence, each running to just
    before the NEXT occurrence (or end of body). None of these calls nest a
    second `call_anthropic(` inside their own arguments, so a window this
    wide safely contains the whole call (including multi-line calls, and the
    one call site whose args contain an unrelated inner function call) without
    needing a real paren-balancing parser.
    """
    starts = [m.start() for m in _CALL_SITE_RE.finditer(body)]
    assert starts, "found zero `call_anthropic(` call sites inside _run_coach_v2_pipeline"
    windows = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        windows.append(body[start:end])
    return windows


def test_five_coach_v2_generation_call_sites_share_one_max_tokens():
    """The five `call_anthropic(..., system=system_prompt)` sites in
    `_run_coach_v2_pipeline` (initial generation, grounding correction, N-06
    quality-gate regen, presence-ack regen, self-graded-verdict regen) must
    all carry the identical `max_tokens` literal. A partial fix that raises
    only the initial call — the #3190 acceptance bar states this explicitly —
    leaves the regenerate arms truncating exactly when the ADR-108 quality
    gate asks for a retry, which is the bug this issue fixes.
    """
    body = _pipeline_body(_read_source())
    windows = [w for w in _call_site_windows(body) if _SYSTEM_PROMPT_RE.search(w)]

    assert len(windows) == 5, (
        f"expected exactly 5 call_anthropic(..., system=system_prompt) sites in "
        f"_run_coach_v2_pipeline, found {len(windows)} — a call site was added, "
        f"removed, or no longer threads system_prompt; update this test's count "
        f"deliberately if that's an intentional change, and audit whether the "
        f"new/changed site(s) need the same max_tokens treatment"
    )

    max_tokens_values = []
    for w in windows:
        m = _MAX_TOKENS_RE.search(w)
        assert m, f"a coach-v2 call_anthropic(..., system=system_prompt) site has no max_tokens= kwarg:\n{w[:200]}"
        max_tokens_values.append(int(m.group(1)))

    assert len(set(max_tokens_values)) == 1, (
        f"the five coach-v2 generation call sites have DRIFTED apart: {max_tokens_values} "
        f"— all five must move together (this is exactly how #3190 was introduced: "
        f"max_tokens=600 hardcoded independently at all five sites)"
    )


def test_max_tokens_covers_the_prompts_own_word_budget():
    """Pair-contract: `_run_coach_v2_pipeline`'s system prompt states a
    "do not exceed <W> words" ceiling, and the shared `max_tokens` at all five
    call sites must be large enough to actually deliver W words of prose
    without truncating (at the task's ~1.4 tokens/word estimate). This is the
    guard that makes the two sides of the pair (prompt instruction, code cap)
    unable to silently drift apart from each other again: raise the word
    budget without raising the cap, or lower the cap below the budget, and
    this reds.
    """
    body = _pipeline_body(_read_source())

    budget_m = _WORD_BUDGET_RE.search(body)
    assert budget_m, (
        "_run_coach_v2_pipeline's system prompt no longer states an explicit "
        "'do not exceed N words' ceiling — #3190 added this because the prompt "
        "previously had NO length instruction at all, which is part of why "
        "generation truncated unpredictably. If the wording changed, update "
        "this test's regex deliberately, but a coach-v2 generation prompt "
        "must always carry an explicit word ceiling."
    )
    word_budget = int(budget_m.group(1))

    windows = [w for w in _call_site_windows(body) if _SYSTEM_PROMPT_RE.search(w)]
    max_tokens_values = {int(_MAX_TOKENS_RE.search(w).group(1)) for w in windows if _MAX_TOKENS_RE.search(w)}
    assert len(max_tokens_values) == 1, f"call sites disagree on max_tokens: {max_tokens_values} (see the sibling test for this)"
    max_tokens = next(iter(max_tokens_values))

    required_minimum = word_budget * TOKENS_PER_WORD_ESTIMATE
    assert max_tokens >= required_minimum, (
        f"max_tokens={max_tokens} cannot deliver the prompt's own {word_budget}-word "
        f"ceiling without truncating: at {TOKENS_PER_WORD_ESTIMATE} tokens/word that "
        f"needs >= {required_minimum:.0f} tokens. Either the word budget grew without "
        f"the cap growing with it, or the cap was lowered below what the prompt "
        f"itself asks for — both sides of this pair must move together (#3190)."
    )
