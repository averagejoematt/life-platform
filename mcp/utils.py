"""
mcp/utils.py — SEC-3 MEDIUM: MCP input validation utilities.
                R31: Standardised error response builder.

Shared validation helpers for MCP tool arguments. Prevents invalid or
dangerous inputs from reaching DynamoDB queries.

Also provides mcp_error() — the canonical error response factory for all
MCP tool functions. Ensures every error Claude receives has the same shape:
  {"error": str, "error_code": str, "suggestions": list[str]}

Stable module — part of the Layer (ADR-027 stable core tier).

v1.0.0 — 2026-03-14 (SEC-3 MEDIUM)
v1.1.0 — 2026-03-15 (R31: mcp_error() + ERROR_CODES)
"""
import re
from datetime import datetime
from typing import Any

# ── Date validation ────────────────────────────────────────────────────────────

# Compiled once at module load — avoids re-compile on every MCP call.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Default max span for MCP date range queries.
# 365 days covers any annual summary; 730 is the hard cap for multi-year requests.
_DEFAULT_MAX_DAYS = 365
_HARD_MAX_DAYS = 730


def validate_date_range(
    start_date: str,
    end_date: str,
    max_days: int = _DEFAULT_MAX_DAYS,
) -> str | None:
    """Validate a date range for use in DynamoDB range queries.

    Prevents unbounded DDB scans by enforcing:
      1. YYYY-MM-DD format on both dates
      2. Calendar validity (no Feb 30 etc.)
      3. start_date <= end_date ordering
      4. Span <= max_days (default 365, hard cap 730)

    Returns:
        None if the date range is valid.
        An error message string if validation fails — callers should return
        this as a tool error rather than proceeding to DDB.

    Usage in tool functions:
        err = validate_date_range(args.get("start_date"), args.get("end_date"))
        if err:
            return {"error": err}
        # safe to query DynamoDB

    Usage in handler._validate_tool_args (automatic for all date-range tools):
        Date args named "start_date" and "end_date" are validated automatically
        before any tool function is called.
    """
    # ── 1. Presence check ────────────────────────────────────────────────────
    if start_date is None:
        return "start_date is required"
    if end_date is None:
        return "end_date is required"

    # ── 2. Format check (fast regex before expensive strptime) ───────────────
    for label, d in (("start_date", start_date), ("end_date", end_date)):
        if not isinstance(d, str):
            return f"{label} must be a string, got {type(d).__name__}"
        if not _DATE_RE.match(d):
            return f"{label} must be in YYYY-MM-DD format, got: {d!r}"

    # ── 3. Calendar validity ─────────────────────────────────────────────────
    for label, d in (("start_date", start_date), ("end_date", end_date)):
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            return f"{label} is not a valid calendar date: {d!r}"

    # ── 4. Ordering ─────────────────────────────────────────────────────────
    if start_date > end_date:
        return f"start_date ({start_date}) must be on or before end_date ({end_date})"

    # ── 5. Span cap ─────────────────────────────────────────────────────────
    cap = min(max_days, _HARD_MAX_DAYS)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    span_days = (end_dt - start_dt).days

    if span_days > cap:
        return (
            f"Date range span ({span_days} days) exceeds the {cap}-day limit. "
            f"Use a shorter window or call multiple times with smaller ranges."
        )

    return None  # valid


# ── R31: Standardised MCP error responses ─────────────────────────────────────

# Canonical error codes used across all MCP tools.
# Claude reads these to decide how to recover — keep them stable.
ERROR_CODES = {
    "NO_DATA":          "No data found for the requested period.",
    "DATE_RANGE":       "Invalid or out-of-bound date range.",
    "MISSING_ARG":      "A required argument was not provided.",
    "SOURCE_UNAVAIL":   "Data source is unavailable or not yet ingested.",
    "PARTIAL_DATA":     "Data returned but one or more fields are incomplete.",
    "QUERY_TOO_BROAD":  "Query spans too many days — use a narrower date range.",
    "INTERNAL":         "Internal processing error.",
}


def mcp_error(
    message: str,
    error_code: str = "INTERNAL",
    suggestions: list[str] = None,
    detail: Any = None,
) -> dict:
    """Build a standardised MCP tool error response.

    All MCP tool functions should return this instead of raising exceptions
    or returning ad-hoc dicts. Claude uses the error_code and suggestions
    fields to decide how to recover without re-prompting the user.

    Args:
        message:     Human-readable error description.
        error_code:  One of ERROR_CODES keys (default: "INTERNAL").
        suggestions: List of recovery actions for Claude to try.
                     If None, a default suggestion is generated from error_code.
        detail:      Optional extra context (e.g. caught exception str).
                     Included only in the response, not logged here.

    Returns:
        dict with keys: error, error_code, suggestions
        (and optionally: detail)

    Examples:
        return mcp_error("No Whoop data found", "NO_DATA",
                         ["Try a shorter date range", "Check get_data_freshness"])

        return mcp_error("DynamoDB query failed", "INTERNAL", detail=str(e))
    """
    if suggestions is None:
        suggestions = _default_suggestions(error_code)

    response: dict[str, Any] = {
        "error":      message,
        "error_code": error_code,
        "suggestions": suggestions,
    }
    if detail is not None:
        response["detail"] = str(detail)
    return response


def _default_suggestions(error_code: str) -> list[str]:
    """Return sensible default recovery suggestions for each error code."""
    _DEFAULTS = {
        "NO_DATA": [
            "Try a shorter or different date range.",
            "Call get_data_freshness to check when this source last updated.",
        ],
        "DATE_RANGE": [
            "Use YYYY-MM-DD format for both start_date and end_date.",
            "Ensure start_date is on or before end_date.",
            "Limit the range to 365 days or fewer.",
        ],
        "MISSING_ARG": [
            "Check the tool's required arguments and retry.",
        ],
        "SOURCE_UNAVAIL": [
            "Call get_data_freshness to see which sources are current.",
            "This source may not have data for the requested date.",
        ],
        "PARTIAL_DATA": [
            "Some fields may be missing — interpret available data with caution.",
            "Call get_data_freshness to see if the source is fully ingested.",
        ],
        "QUERY_TOO_BROAD": [
            "Split the request into smaller date windows (e.g. 90-day chunks).",
            "Use get_longitudinal_summary for multi-year overviews instead.",
        ],
        "INTERNAL": [
            "Retry the request — this may be a transient error.",
            "If the error persists, check CloudWatch logs for the MCP Lambda.",
        ],
    }
    return _DEFAULTS.get(error_code, ["Retry or check system status."])


def validate_single_date(date_str: str, label: str = "date") -> str | None:
    """Validate a single date string is in YYYY-MM-DD format and a valid calendar date.

    Returns None if valid, error message string if invalid.

    Usage:
        err = validate_single_date(args.get("date"))
        if err:
            return {"error": err}
    """
    if date_str is None:
        return f"{label} is required"
    if not isinstance(date_str, str):
        return f"{label} must be a string, got {type(date_str).__name__}"
    if not _DATE_RE.match(date_str):
        return f"{label} must be in YYYY-MM-DD format, got: {date_str!r}"
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return f"{label} is not a valid calendar date: {date_str!r}"
    return None
