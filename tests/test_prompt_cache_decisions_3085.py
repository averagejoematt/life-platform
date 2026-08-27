"""#3085 — a `cache_control` block is not evidence of caching.

#2888 built the floor registry and the `PromptCacheNoOp` dead-man. What it did not
build is a place to record, per caller, what we DECIDED about that floor — so a
reader standing at a call site that carries `cache_control` still could not tell
"this caches" from "this was measured and deliberately left un-caching".

`prompt_cache.CACHING_DECISIONS` is that record and these tests are its ratchet.
The invariant is one line and it cuts BOTH ways:

    clears_floor(the real prompt, the real model)  ==  entry["engaged"]

  * A caller that CLAIMS caching whose prefix sits under the model's floor fails.
    That is the defect class #3085 exists to name — the claim without the caching.
  * A caller recorded as DECLINED whose prefix has since grown past the floor also
    fails, because the recorded rationale ("too small to cache") has silently
    stopped being true and the trade deserves re-deciding rather than inheriting.

The deterministic half lives here. The live half is `PromptCacheNoOp` (#2888),
emitted by `bedrock_client._note_cache_noop` when a request asked for caching and
the wire reported none — measured over the 30d window ending 2026-08-27T00:00Z
(the moment the ADR-125 budget tier escalated to 2 and coach narratives paused):
`coach-quality-gate` 435 calls / 0 cache-read / 0 cache-write, `coach-state-updater`
290 calls / 0 / 0, against `coach-narrative-orchestrator` on the SAME emit path and
the SAME model carrying 903,531 cache-read tokens. Same code, same Lambda role,
same namespace — so the two zeros are a true zero, not a dark instrument.
"""

import ast
from pathlib import Path

import pytest
from ai import prompt_cache

_LAMBDAS = Path(__file__).resolve().parents[1] / "lambdas"


def _const_eval(node, path: Path, name: str):
    """Fold a literal string expression — constants plus `+`/`*` between them.

    `ast.literal_eval` refuses `"a" * 3` and any Name reference, and raises a
    ValueError whose text says nothing about which prompt broke. These prompts are
    long literal concatenations that a future refactor could easily turn into
    something this cannot fold (`EXTRACTION_SYSTEM_PROMPT` already appends a module
    constant), so fail with an instruction instead of a traceback.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
        left = _const_eval(node.left, path, name)
        right = _const_eval(node.right, path, name)
        return left + right if isinstance(node.op, ast.Add) else left * right
    raise AssertionError(
        f"{path.name}::{name} is no longer a foldable string literal (found {type(node).__name__}). "
        "Give this test an import-based accessor for it, the way coach-state-updater has one — "
        "silently losing the prompt would turn the #3085 floor check into a check that cannot fail."
    )


def _literal(path: Path, name: str):
    """The value of a module-level string-literal assignment, without importing."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return _const_eval(node.value, path, name)
    raise AssertionError(f"{name} not found in {path.name}")


def _quality_gate_prompt():
    return _literal(_LAMBDAS / "coach" / "coach_quality_gate.py", "QUALITY_GATE_SYSTEM_PROMPT")


def _extraction_prompt():
    from coach.coach_extraction_prompt import EXTRACTION_SYSTEM_PROMPT

    return EXTRACTION_SYSTEM_PROMPT


_PROMPTS = {
    "coach-quality-gate": _quality_gate_prompt,
    "coach-state-updater": _extraction_prompt,
}


# ── 1. the register is well-formed ──────────────────────────────────────────


@pytest.mark.parametrize("fn", sorted(prompt_cache.CACHING_DECISIONS))
def test_every_decision_carries_a_dated_rationale(fn):
    """'Record why not' is only an outcome if the why and the when are both there."""
    entry = prompt_cache.CACHING_DECISIONS[fn]
    assert isinstance(entry["engaged"], bool)
    assert entry["model"], f"{fn}: a floor is meaningless without the model it belongs to"
    assert entry["prefix_tokens"] > 0, f"{fn}: prefix_tokens is a wire measurement, not a guess"
    assert len(entry["why"]) > 80, f"{fn}: the rationale must survive the next reader, not just satisfy a key"
    assert entry["decided"], f"{fn}: an undated decision cannot be re-litigated"
    assert entry["issue"], f"{fn}: the decision must be traceable to the issue that made it"


def test_the_decision_register_is_not_empty():
    """A register nothing is enrolled in is a check that cannot fail (the platform's
    most-repeated defect). Both #3085 callers must be present."""
    assert {"coach-quality-gate", "coach-state-updater"} <= set(prompt_cache.CACHING_DECISIONS)


# ── 2. THE invariant, both directions ───────────────────────────────────────


@pytest.mark.parametrize("fn", sorted(prompt_cache.CACHING_DECISIONS))
def test_engaged_flag_matches_what_the_floor_actually_permits(fn):
    """Claimed caching must clear the floor; declined caching must still be under it.

    This is the check #3085's outcome statement asks for, in the form CI can run
    offline: a nonzero cache read is only POSSIBLE above the floor, so asserting
    the claim against the floor is asserting the claim against the wire.
    """
    entry = prompt_cache.CACHING_DECISIONS[fn]
    prompt = _PROMPTS[fn]()
    floor = prompt_cache.cache_floor(entry["model"])
    est = prompt_cache.estimate_tokens(prompt)
    clears = prompt_cache.clears_floor(prompt, entry["model"])
    assert clears is entry["engaged"], (
        f"{fn}: recorded engaged={entry['engaged']} but its system prompt is ~{est} tok "
        f"against a {floor} tok floor for {entry['model']}. "
        + (
            "A caller cannot claim caching below the floor — the marker is silently ignored and "
            "`cache_read_input_tokens` stays 0 forever (#3085)."
            if entry["engaged"]
            else "The prompt has grown past the floor, so the recorded 'too small to cache' rationale "
            f"({entry['decided']}, #{entry['issue']}) is no longer true — re-decide it rather than inherit it."
        )
    )


@pytest.mark.parametrize("fn", sorted(prompt_cache.CACHING_DECISIONS))
def test_recorded_measurement_still_matches_the_live_prompt(fn):
    """The recorded wire count must stay in the same ballpark as the real prompt.

    `prefix_tokens` was measured by Bedrock CountTokens; `estimate_tokens` is
    chars/3.6 and runs ~5-10% high on these two. A 35% band therefore passes normal
    prompt edits and fails a prompt that has materially changed size without anyone
    re-measuring — which is how a stale decision survives its own rationale.
    """
    entry = prompt_cache.CACHING_DECISIONS[fn]
    est = prompt_cache.estimate_tokens(_PROMPTS[fn]())
    lo, hi = entry["prefix_tokens"] * 0.65, entry["prefix_tokens"] * 1.35
    assert lo <= est <= hi, (
        f"{fn}: recorded prefix_tokens={entry['prefix_tokens']} (wire, {entry['decided']}) but the "
        f"prompt now estimates ~{est} tok — re-measure with Bedrock CountTokens and update the register"
    )


# ── 3. the call sites still say so where the reader will look ───────────────


@pytest.mark.parametrize(
    "relpath,fn",
    [("coach/coach_quality_gate.py", "coach-quality-gate"), ("coach/coach_state_updater.py", "coach-state-updater")],
)
def test_the_no_op_call_sites_are_annotated_as_deliberate(relpath, fn):
    """The whole failure mode is a marker that reads as working code. Both sites keep
    `cache_control` (an ignored marker costs nothing and engages free if the prompt
    later grows) — so the annotation is the only thing standing between the next
    reader and the same wrong conclusion."""
    src = (_LAMBDAS / relpath).read_text()
    assert "cache_control" in src
    assert "#3085" in src, f"{relpath}: the measured no-op decision must be stated at the call site"
    assert "CACHING_DECISIONS" in src, f"{relpath}: point the reader at the register that holds the numbers"


def test_haiku_floor_is_what_makes_these_two_uncacheable():
    """The load-bearing number, asserted rather than narrated: the issue assumed a
    ~2,048 floor; Haiku 4.5's is 4,096, which is why both prompts are further from
    caching than #3085 was filed believing."""
    assert prompt_cache.cache_floor("us.anthropic.claude-haiku-4-5-20251001-v1:0") == 4096
    for fn in ("coach-quality-gate", "coach-state-updater"):
        assert prompt_cache.CACHING_DECISIONS[fn]["prefix_tokens"] < 2048, (
            f"{fn} was under even the 2,048 figure the issue assumed — if that is no longer true "
            "the arithmetic in the register needs redoing"
        )
