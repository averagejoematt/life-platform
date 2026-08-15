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
import re
from typing import Any, Dict, Optional, Tuple


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
