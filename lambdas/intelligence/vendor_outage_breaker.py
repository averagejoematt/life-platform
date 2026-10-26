"""intelligence/vendor_outage_breaker.py — #5412: one analyzer run's Bedrock 5xx burst counts as ONE outage.

THE INCIDENT. `slo-ai-coaching-success` (Sum of `LifePlatform/AI` `AnthropicAPIFailure` over 24 h,
threshold 3) went ALARM on two Mondays running (2026-10-19, 2026-10-26) from one source: the
`ai-expert-analyzer` 14:00Z cron. Bedrock answered `ServiceUnavailableException` for about a minute;
every expert exhausted `bedrock_client.invoke_with_retry`'s 3 attempts (~20 s) and each exhausted
call emitted one failure metric (`common.retry_utils._emit_failure_metric`) — 6 in a minute. The
coaching SLO exists to protect the owner-facing brief and coach texts, which ran clean both days; the
alarm stayed red for 24 h on a weekly batch's bad minute.

THE CHOICE (#5412 option (a), pure-code variant). The analyzer does not walk eight experts into the
same dead vendor. Its calls go through `call_guarded`:

  1. the FIRST vendor-side failure of a run (a retryable Bedrock code that survived the 3-attempt
     transport retry) waits ONE bounded backoff — inside the Lambda timeout — and retries that call
     once: a blip heals and the run completes normally, having emitted a single failure metric;
  2. if the retry also fails, or a SECOND vendor failure arrives later in the run, the breaker
     TRIPS: every later call in the run is refused locally (`VendorOutageSkipped`, no send, no
     metric). The prior reader-facing records keep serving (the handler renews their TTL, #4703);
     next Monday's run produces the new ones.

So a run emits AT MOST `MAX_FAILURE_METRICS_PER_RUN` (2) failure metrics, whatever N experts the
roster holds — below the SLO threshold of 3 on its own, so the alarm still means what it says when
two runs' worth of real failures, or another Lambda's, add to it. Neither the alarm nor its
threshold is touched. A non-vendor error (validation, access, a refused budget stop) is not an
outage and passes through unchanged.

State is per Lambda invocation: `begin_run()` resets it (a warm container reuses the module).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

BACKOFF_SECONDS = 45  # one bounded wait; the function timeout is 600 s (cdk/stacks/compute_stack.py)
SAFETY_MARGIN_SECONDS = 150  # never sleep if it would leave less than this (+ the backoff) of the run
MAX_FAILURE_METRICS_PER_RUN = 2  # the first failure + at most one more (the post-backoff retry or a later call)


class VendorOutageSkipped(RuntimeError):
    """Raised instead of a send once the breaker has tripped — no call was made, no metric emitted."""


class _State:
    failures = 0  # vendor-side failures seen (each one already emitted its metric inside retry_utils)
    backed_off = False
    tripped = False
    skipped = 0
    remaining_ms: Optional[Callable[[], int]] = None


_state = _State()


def begin_run(context: Any = None) -> None:
    """Reset for a new invocation; remember how to read the remaining Lambda time (None in tests/CLI)."""
    s = _state
    s.failures, s.backed_off, s.tripped, s.skipped = 0, False, False, 0
    getter = getattr(context, "get_remaining_time_in_millis", None)
    s.remaining_ms = getter if callable(getter) else None


def tripped() -> bool:
    return _state.tripped


def is_vendor_outage(exc: BaseException) -> bool:
    """True for a retryable Bedrock service code (the ONE set, `bedrock_client.RETRYABLE_BEDROCK_CODES`)
    that survived the transport retry. Anything else is not an outage."""
    from ai.bedrock_client import RETRYABLE_BEDROCK_CODES

    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    return code in RETRYABLE_BEDROCK_CODES


def _room_to_back_off() -> bool:
    if _state.remaining_ms is None:
        return True
    try:
        return _state.remaining_ms() / 1000.0 > BACKOFF_SECONDS + SAFETY_MARGIN_SECONDS
    except Exception:  # noqa: BLE001 — a clock read must never break a call
        return True


def _send(req: Any, timeout: int) -> dict:
    # Looked up at call time so a patched `retry_utils.call_anthropic_raw` is what runs.
    from common import retry_utils

    return retry_utils.call_anthropic_raw(req, timeout=timeout)


def _note_failure(exc: BaseException) -> None:
    _state.failures += 1
    logger.warning("[outage-breaker] vendor failure %d this run: %s: %s", _state.failures, type(exc).__name__, exc)


def call_guarded(req: Any, timeout: int = 55) -> dict:
    """`retry_utils.call_anthropic_raw` under the run-level outage breaker (see module docstring)."""
    s = _state
    if s.tripped:
        s.skipped += 1
        raise VendorOutageSkipped("Bedrock vendor outage earlier in this run — call skipped, prior record keeps serving (#5412)")
    try:
        return _send(req, timeout)
    except Exception as first:
        if not is_vendor_outage(first):
            raise
        _note_failure(first)
        if s.backed_off or not _room_to_back_off():
            s.tripped = True
            logger.error("[outage-breaker] TRIPPED — remaining calls this run are skipped")
            raise
        s.backed_off = True
        logger.warning("[outage-breaker] backing off %ds once, then retrying this call", BACKOFF_SECONDS)
        time.sleep(BACKOFF_SECONDS)
        try:
            return _send(req, timeout)
        except Exception as second:
            if is_vendor_outage(second):
                _note_failure(second)
                s.tripped = True
                logger.error("[outage-breaker] TRIPPED after the backoff — remaining calls this run are skipped")
            raise


def summary() -> dict:
    return {"vendor_failures": _state.failures, "tripped": _state.tripped, "skipped_calls": _state.skipped}
