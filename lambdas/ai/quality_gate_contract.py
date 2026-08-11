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
from typing import Any, Optional

# The deployed function name the coach pipeline invokes synchronously (ADR-108/#390).
QUALITY_GATE_FUNCTION_NAME = "coach-quality-gate"


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
