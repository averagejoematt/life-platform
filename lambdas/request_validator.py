"""
request_validator.py — Phase 2.2 (2026-05-16): centralized request envelope
validation for site-api Lambdas.

Catches broad threats without requiring per-endpoint schemas:
  - Oversized request bodies (DoS)
  - Oversized query string (DoS / log explosion)
  - Common injection patterns in unstructured query params
  - Path traversal attempts
  - Malformed user_id / date / source values

Usage:
    from request_validator import validate_envelope, ValidationError
    try:
        validate_envelope(event, path=path, method=method)
    except ValidationError as e:
        return {"statusCode": e.status, "headers": CORS_HEADERS,
                "body": json.dumps({"error": e.message})}

Design principle: fail loudly on obvious abuse, never on legit traffic.
All limits are intentionally generous; tighten per-endpoint as needed.
"""

from __future__ import annotations

import re

# ── Public exception ────────────────────────────────────────────────────────


class ValidationError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status
        super().__init__(message)


# ── Limits ──────────────────────────────────────────────────────────────────

MAX_BODY_BYTES = 100 * 1024  # 100KB for site-api endpoints (HAE webhook has its own)
MAX_QUERY_STRING_LENGTH = 2000  # Generous; longest legit ~200 chars
MAX_PARAM_VALUE_LENGTH = 500  # Single param value cap (longer = something is wrong)
MAX_PATH_LENGTH = 256  # AWS URL routing limit; should be far shorter


# ── Pattern allowlists ──────────────────────────────────────────────────────

# Known valid sources (extend as new ingestion sources are added).
KNOWN_SOURCES = frozenset(
    {
        "whoop",
        "withings",
        "strava",
        "garmin",
        "eightsleep",
        "macrofactor",
        "apple_health",
        "todoist",
        "notion",
        "habitify",
        "weather",
        "dropbox",
        "food_delivery",
        "measurements",
        "labs",
        "genome",
        "dexa",
        "supplements",
        "travel",
        "state_of_mind",
        "habit_scores",
        "character_sheet",
        "computed_metrics",
        "platform_memory",
        "insights",
        "decisions",
        "hypotheses",
        "chronicle",
        "field_notes",
        "experiments",
        "challenges",
    }
)

# Allowed user_id pattern. Single-user platform today; future-proofed for ids like "matthew", "user_123".
_USER_ID_RE = re.compile(r"^[a-z0-9_\-]{1,40}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_RE = re.compile(r"^[a-z0-9_]{1,32}$")

# Patterns that should NEVER appear in well-formed input. Catch obvious abuse.
# (We don't try to be a full WAF — just sanity checks.)
_SUSPICIOUS_PATTERNS = [
    re.compile(r"\.\./", re.IGNORECASE),  # path traversal
    re.compile(r"<script", re.IGNORECASE),  # XSS attempt
    re.compile(r"javascript:", re.IGNORECASE),  # XSS attempt
    re.compile(r"(?:^|\W)(?:union|select|drop|insert|update|delete)\s+(?:all\s+)?(?:from|into|table)", re.IGNORECASE),  # SQL injection
    re.compile(r"\x00"),  # null byte
]


# ── Validators ──────────────────────────────────────────────────────────────


def _check_suspicious(value: str, where: str) -> None:
    """Raise if a value contains obvious injection patterns."""
    for pat in _SUSPICIOUS_PATTERNS:
        if pat.search(value):
            raise ValidationError(
                f"Invalid characters in {where}",
                status=400,
            )


def validate_envelope(event: dict, path: str = None, method: str = None) -> None:
    """Validate the outer request envelope. Raise ValidationError on abuse."""
    # Path checks
    if path is None:
        path = event.get("rawPath") or event.get("path") or "/"
    if len(path) > MAX_PATH_LENGTH:
        raise ValidationError("Request path too long", status=414)
    _check_suspicious(path, "path")

    # Body size cap (POST/PUT only)
    body = event.get("body") or ""
    if body:
        # API Gateway base64-encodes binary bodies; estimate decoded size.
        body_bytes = len(body) if not event.get("isBase64Encoded") else (len(body) * 3) // 4
        if body_bytes > MAX_BODY_BYTES:
            raise ValidationError(
                f"Request body too large ({body_bytes} bytes; max {MAX_BODY_BYTES})",
                status=413,
            )

    # Query string sanity
    qs_raw = event.get("rawQueryString") or ""
    if len(qs_raw) > MAX_QUERY_STRING_LENGTH:
        raise ValidationError("Query string too long", status=414)

    qs = event.get("queryStringParameters") or {}
    if qs:
        for k, v in qs.items():
            if not isinstance(v, str):
                continue
            if len(v) > MAX_PARAM_VALUE_LENGTH:
                raise ValidationError(f"Query parameter '{k}' value too long", status=400)
            _check_suspicious(v, f"query parameter '{k}'")
            # Specific format checks for well-known param names
            if k == "user_id" and not _USER_ID_RE.match(v):
                raise ValidationError("Invalid user_id format", status=400)
            if k == "date" and not _DATE_RE.match(v):
                raise ValidationError("Invalid date format (expected YYYY-MM-DD)", status=400)
            if k == "source" and not _SOURCE_RE.match(v):
                raise ValidationError("Invalid source format", status=400)


def validate_user_id(user_id: str) -> str:
    """Validate + return a user_id. Raises ValidationError on bad input."""
    if not user_id or not _USER_ID_RE.match(user_id):
        raise ValidationError("Invalid user_id format", status=400)
    return user_id


def validate_date(date_str: str) -> str:
    """Validate + return an ISO date. Raises ValidationError on bad input."""
    if not date_str or not _DATE_RE.match(date_str):
        raise ValidationError("Invalid date format (expected YYYY-MM-DD)", status=400)
    return date_str


def validate_source(source: str, allow_unknown: bool = False) -> str:
    """Validate + return a source name."""
    if not source or not _SOURCE_RE.match(source):
        raise ValidationError("Invalid source format", status=400)
    if not allow_unknown and source not in KNOWN_SOURCES:
        raise ValidationError(f"Unknown source: {source}", status=400)
    return source


def validate_int_param(value: str, name: str, min_v: int = None, max_v: int = None) -> int:
    """Parse + range-check an integer query parameter."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Parameter '{name}' must be an integer", status=400)
    if min_v is not None and n < min_v:
        raise ValidationError(f"Parameter '{name}' must be >= {min_v}", status=400)
    if max_v is not None and n > max_v:
        raise ValidationError(f"Parameter '{name}' must be <= {max_v}", status=400)
    return n
