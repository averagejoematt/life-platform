"""quality_gate_contract.py — the wire contract between the coach pipeline and
the `coach-quality-gate` Lambda (#1374).

One tiny module with one job: own the EXACT event payload production sends to the
quality gate, so that everything which needs to reproduce that call — the caller
(`ai_calls._invoke_quality_gate_sync`) and the judge-calibration harness
(`tests/judge_calibration.py`) — reads it from the same place.

Why it is its own module rather than a helper inside `ai_calls`: `ai_calls` is a
baselined god-module under the #1665 size ratchet, and this is exactly the
"cohesive helper module beside it" that ratchet asks for. It is also genuinely
separable — a call contract, not generation logic — and importing it costs nothing
(stdlib `date` only, no boto3, no clients), which is what lets a test harness pull
the production payload shape without dragging the generation stack in behind it.

The drift this prevents is specific and has bitten before: a harness that
hand-rebuilds a production call slowly diverges from it and then manufactures
findings about an instrument nothing actually uses.
"""

from datetime import date
from typing import Any, Iterable, Optional

# The deployed function name the coach pipeline invokes synchronously (ADR-108/#390).
QUALITY_GATE_FUNCTION_NAME = "coach-quality-gate"

# ── #2573: the deterministic grounding context, carried INSIDE generation_brief ──
# The gate's rubric was blind to fabricated numbers (all three canaries scored
# 92/92/82 and passed). The fix consumes the ADR-104 deterministic verdict rather
# than asking the LLM to re-decide it in prose (ADR-105: deterministic computation
# before any LLM verdict) — but the gate Lambda cannot recompute that verdict on
# its own, because the allow-list is derived from the ASSEMBLED GENERATION PROMPT,
# which never crosses the wire. So the caller ships the already-computed allow-list.
#
# Why nested in `generation_brief` rather than as new top-level event keys: the
# top-level payload shape is diffed key-by-key against the live call site by
# `tests/test_judge_calibration_1374.py`, and the brief is already the "everything
# the generation had" channel. Nesting keeps the wire contract's top-level keys
# byte-identical and costs the size-ratcheted `ai_calls` no new call-site lines.
GROUNDING_ALLOWLIST_KEY = "grounding_allowlist"
AUTHORITATIVE_FACTS_KEY = "authoritative_facts"


def quality_gate_event(
    coach_id: str,
    output_text: str,
    generation_brief: Any,
    generation_date: Optional[str] = None,
) -> dict[str, Any]:
    """The EXACT event payload production sends to `coach-quality-gate`.

    `tests/test_judge_calibration_1374.py` diffs the real wire payload against
    this function key-by-key, so the caller and this builder cannot separate.

    Note what is deliberately ABSENT, because it matters to any replay: no
    `voice_spec` (the gate loads it from S3), no `other_coach_outputs` (the gate
    queries DynamoDB), no `skip_cross_coach`. A hermetic replay has to substitute
    for those two AWS reads and must say so rather than quietly measuring a
    different prompt — see `judge_calibration.FIDELITY_GAPS`.
    """
    return {
        "coach_id": coach_id,
        "output_text": output_text,
        "generation_brief": generation_brief if isinstance(generation_brief, dict) else None,
        "generation_date": generation_date or date.today().isoformat(),
    }


def brief_with_grounding(
    generation_brief: Any,
    canonical_facts: Optional[dict] = None,
    allowed_numbers: Optional[Iterable[float]] = None,
) -> Any:
    """Attach the caller's DETERMINISTIC grounding context to the brief (#2573).

    `allowed_numbers` is `grounded_generation.allowed_numbers(prompt, data, facts)`
    as the generation path already computed it — every number the model was given.
    `canonical_facts` is the same dict the ADR-104 grounding gate uses for the
    RHR/recovery/HRV contradiction check.

    THE PRESENCE OF THE ALLOW-LIST KEY IS THE SIGNAL. The gate treats a missing
    `grounding_allowlist` as "this caller supplied no grounding context" and its
    number check reports honest absence rather than a green verdict — never a
    silent pass. An allow-list of `None` (the generation path's grounding gate did
    not run, e.g. `grounded_generation` failed to import) is therefore NOT attached;
    an EMPTY allow-list is a real, if unusual, statement and IS attached.

    Pure: returns a new dict, never mutates the caller's brief.
    """
    if not isinstance(generation_brief, dict):
        return generation_brief
    out = dict(generation_brief)
    out[AUTHORITATIVE_FACTS_KEY] = dict(canonical_facts or {})
    if allowed_numbers is not None:
        out[GROUNDING_ALLOWLIST_KEY] = sorted(float(n) for n in allowed_numbers)
    return out
