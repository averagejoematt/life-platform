"""board_verdict_observer.py — #3414: the board's ADR-108 voice verdict, recovered
on an ASYNC channel, off the reader path.

WHAT THIS IS. One fire-and-forget Event invoke of the quality-gate Lambda
(`ai.quality_gate_contract.QUALITY_GATE_FUNCTION_NAME`), sent AFTER the board
answer is final and entering the reader's response. The event carries the #3414
`emit_verdict` opt-in, so the verdict is captured on the CALLEE side
(`coach_quality_gate._emit_async_verdict`: CloudWatch `BoardQualityGateVerdict`
/ `BoardQualityGateFired` + eval retention with the honest disposition
"observed"). Nothing is awaited, nothing is read back, and nothing here can
change, delay, or hold what the reader receives.

WHY THIS SHAPE. #968 ran this gate synchronously while a reader waited; the
client cap sat below the callee's own p50 and 7 days of live traffic produced
0 verdicts — so #3413 removed it from the reader path, which left the board's
voice-fidelity failure rate UNKNOWN. This module is the deferred half: the
measurement without the wait. The structural rules it lives under
(tests/test_board_quality_gate_968.py):

  • the ONLY invocation type here is "Event" — the synchronous kind is banned
    by needle on this module's source, with a mutation proof
  • the response payload is NEVER consumed (no read of the invoke result)
  • `observe()` never raises — a dead Lambda API costs a log line, not a reader

OBSERVE-ONLY BY DESIGN. There is no regenerate-or-hold on this channel and none
may be added: ADR-108's enforcement scope is the daily brief only (#3413
amendment). This channel measures; it never enforces.

COST (ADR-103): one async Lambda invocation + one Haiku judge call per grounded
board answer — the same per-answer gate cost the #968 sync path already paid
(and discarded), now minus the ~10s of reader latency. Board traffic measured
2026-09-01: ~8 gate-eligible answers per WEEK.
"""

import json
import logging
import os
from typing import Any, Optional

from ai.quality_gate_contract import QUALITY_GATE_FUNCTION_NAME, quality_gate_event

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_client: Optional[Any] = None


def _lambda_client() -> Any:
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    return _client


def observe(coach_id: str, output_text: str, surface: str = "board_ask") -> bool:
    """Fire-and-forget: queue one async gate evaluation of a served board answer.

    `output_text` is the text the reader ALREADY has — the verdict describes it,
    it can never amend it. Returns True if the invoke was queued, False on any
    failure (logged, never raised: telemetry is never load-bearing).
    """
    try:
        payload = json.dumps(quality_gate_event(coach_id, output_text, None, emit_verdict=surface)).encode()
        # The invoke result is deliberately discarded: an Event-type invoke's
        # response carries only a 202 acknowledgement, and consuming a payload
        # here is the banned shape (see the guard's needle set).
        _lambda_client().invoke(FunctionName=QUALITY_GATE_FUNCTION_NAME, InvocationType="Event", Payload=payload)
        return True
    except Exception as e:  # noqa: BLE001 — never a reader-facing failure
        logger.warning("[%s] async verdict observe failed for %s (non-fatal): %s", surface, coach_id, e)
        return False
