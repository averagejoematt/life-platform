"""lambdas/web/site_api_ai_request.py — request-body parsing for the AI doors (#2688).

Split out of ``site_api_ai_lambda.py`` rather than grown inside it: that module is
at its recorded size ceiling (`tests/test_module_size_guard.py`), and the guard's
rule is to pay for new lines out of an extracted sibling instead of raising the
number.

Deliberately PURE — no imports from the lambda module, so there is no import
cycle and these are testable on their own. Each function returns data plus an
error *message*; turning that into an HTTP envelope stays the caller's job.

Why this exists at all: `json.loads` returns a str/list/int for a well-formed but
non-object body, so the very next ``body.get(...)`` raised AttributeError. On
``/api/explain`` and ``/api/board_ask`` that call sat outside the try, so the
error escaped the handler and the reader got ``502 Internal Server Error`` — a
Lambda invocation failure — for a malformed request.
"""

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger()


def json_object_body(raw_body: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse a request body that MUST be a JSON object.

    Returns ``(body, error_message)``; ``error_message`` is None on success.
    """
    try:
        parsed = json.loads(raw_body or "{}")
    except Exception:  # noqa: BLE001 — any parse failure is a client error
        return None, "Invalid JSON"
    if not isinstance(parsed, dict):
        return None, "Request body must be a JSON object"
    return parsed, None


def text_field(body: Dict[str, Any], key: str, cap: int = 500) -> str:
    """One reader-supplied free-text field: type-guarded, HTML-stripped, capped.

    Mirrors ``web/site_api_social._sanitise_text`` so the AI doors and the capture
    doors treat a mistyped field identically. A non-text value yields "" — the
    door's own length/enum check then answers 400 — never an AttributeError.
    ``bool`` is excluded explicitly because it is a subclass of ``int``.
    """
    raw = body.get(key)
    if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
        return ""
    return re.sub(r"<[^>]+>", "", str(raw)).strip()[:cap]


def hazard_gate(
    question: str,
    endpoint: str,
    response_key: str,
    cors_headers: Dict[str, str],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """#3050 (DIL-031-lite): the clinical-lite hazard check, shared by every free-text
    AI door. Returns None when the question is safe; otherwise the COMPLETE HTTP
    response to serve — and the caller MUST return it without calling any model.
    That short-circuit is the safety property: the platform cannot hallucinate advice
    it never generated.

    Lives here (not in the lambda module) for the same reason this file exists at
    all — site_api_ai_lambda.py sits at its module-size ceiling, and the guard's rule
    is to pay for new lines out of a sibling. ONE deliberate ordering rule for
    callers, pinned by tests/test_safety_contract_3050.py: this gate runs BEFORE the
    WR-40 privacy filter (a question can be both a hazard and a privacy hit — the
    hazard response must win), BEFORE the rate limit (a person describing an
    emergency must not be rate-limited into silence) and BEFORE the budget pause
    (tier 3 must not answer "the AI is paused" to someone describing chest pain).
    All three are safe to defer because this path is $0: a pure, offline regex
    classification that makes no model call and no AWS call.

    #3560: for eight weeks that sentence was true only of /api/ask. `board_ask`
    charged its DDB rate token and every door served the tier-3 pause AHEAD of this
    gate, and the ordering test compared the gate only against the privacy filter —
    so a hazard question that was the reader's 6th of the hour got a 429, and at
    tier 3 every door served the pause copy. The order is now asserted against the
    pause and the limiter too (`test_the_hazard_check_precedes_every_spend_gate`),
    against a synthetic wrong-ordered door as the checker's own positive control.

    ``response_key`` matches each door's existing payload shape ("answer" for
    /api/ask, "response" for the board doors); ``extra`` carries door-specific
    fields (e.g. the follow-up's persona echo).
    """
    from ai import safety_contract

    safe, copy, hazard = safety_contract.check(question)
    if safe:
        return None
    logger.warning(f"[{endpoint}] safety contract fired — class={hazard} (no model call made)")
    payload: Dict[str, Any] = {response_key: copy, "filtered": True, "safety": hazard}
    if extra:
        payload.update(extra)
    return {
        "statusCode": 200,
        "headers": {**cors_headers, "Cache-Control": "no-store"},
        "body": json.dumps(payload),
    }
