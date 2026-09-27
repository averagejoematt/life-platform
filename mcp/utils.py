"""
mcp/utils.py — SEC-3 MEDIUM: MCP input validation utilities.
                R31: Standardised error response builder.

Shared validation helpers for MCP tool arguments. Prevents invalid or
dangerous inputs from reaching DynamoDB queries.

Also provides mcp_error() — the canonical error response factory for all
MCP tool functions. Ensures every error Claude receives has the same shape:
  {"error": str, "error_code": str, "kind": str, "suggestions": list[str]}

Stable module — part of the Layer (ADR-027 stable core tier).

v1.0.0 — 2026-03-14 (SEC-3 MEDIUM)
v1.1.0 — 2026-03-15 (R31: mcp_error() + ERROR_CODES)
v1.2.0 — 2026-09-26 (#4172: every code carries a kind; a policy refusal is never told to retry)
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
#
# #4172: every code carries a KIND, declared once here beside the code — never at a call
# site — because the kind decides what a recovery can even be:
#
#   policy     a gate said no. The same call refuses identically forever; only changing
#              the thing the gate judged (the set, the floor, the critic, the routine, the
#              owner's own recorded words) changes the answer. Its suggestions name that
#              change and NEVER say "retry" — a caller that reads only `suggestions` would
#              otherwise loop on a refusal (the live REDTEAM_BINDING specimen, 2026-09-26).
#   argument   the call itself is wrong — a missing, malformed or unknown argument. Fix the
#              arguments and re-issue.
#   transport  the pipe, or the data at this instant — a timeout, an upstream 5xx, a
#              rolling rate window, a source not yet ingested. Time or an upstream may
#              change the answer; "retry" is honest advice here and only here.
KIND_POLICY = "policy"
KIND_ARGUMENT = "argument"
KIND_TRANSPORT = "transport"
ERROR_KINDS_VALID = frozenset({KIND_POLICY, KIND_ARGUMENT, KIND_TRANSPORT})

# code -> (kind, description). ERROR_CODES and ERROR_KINDS are DERIVED from this one table.
_ERROR_CODE_SPECS: dict[str, tuple[str, str]] = {
    # ── the pipe / the data at this instant ──────────────────────────────────
    "NO_DATA": (KIND_TRANSPORT, "No data found for the requested period."),
    "SOURCE_UNAVAIL": (KIND_TRANSPORT, "Data source is unavailable or not yet ingested."),
    "PARTIAL_DATA": (KIND_TRANSPORT, "Data returned but one or more fields are incomplete."),
    "INTERNAL": (KIND_TRANSPORT, "Internal processing error."),
    "RATE_LIMIT": (KIND_TRANSPORT, "Write tool called too many times in a short window."),
    "HEVY_RETRYABLE": (KIND_TRANSPORT, "Hevy was unreachable or answered 5xx through the retry budget; nothing was written."),
    "HEVY_AUTH": (KIND_TRANSPORT, "Hevy rejected the platform's write credential."),
    "HEVY_ORPHAN_CREATED": (KIND_TRANSPORT, "Hevy created the routine but answered with an error; the platform IR is now linked to it."),
    # ── the call is wrong ────────────────────────────────────────────────────
    "DATE_RANGE": (KIND_ARGUMENT, "Invalid or out-of-bound date range."),
    "MISSING_ARG": (KIND_ARGUMENT, "A required argument was not provided."),
    "INVALID_ARG": (KIND_ARGUMENT, "An argument carries a value the tool does not accept."),
    "INVALID_ACTION": (KIND_ARGUMENT, "The action is not one this tool offers."),
    "NOT_FOUND": (KIND_ARGUMENT, "No record carries the id the call named."),
    "QUERY_TOO_BROAD": (KIND_ARGUMENT, "Query spans too many days — use a narrower date range."),
    "MOVEMENT_UNMAPPABLE": (KIND_ARGUMENT, "An exercise in the draft names no movement the platform's index knows."),
    "UNRESOLVED_MOVEMENT": (KIND_ARGUMENT, "A movement in the routine could not be resolved to a Hevy exercise template."),
    "LINK_UNVERIFIED": (KIND_ARGUMENT, "The link given could not be verified as the page it claims to be."),
    "HEVY_PRECHECK_FAILED": (KIND_ARGUMENT, "The routine carries a field Hevy's schema rejects; nothing was sent."),
    "HEVY_BAD_REQUEST": (KIND_ARGUMENT, "Hevy rejected the routine body (4xx); its response names the field."),
    # ── a gate said no ───────────────────────────────────────────────────────
    "REDTEAM_BINDING": (KIND_POLICY, "Commit refused: the routine is not the one stage 2 red-teamed, unchanged since (#4066)."),
    "SUBTRACT_ONLY_VIOLATION": (KIND_POLICY, "Commit refused: a set under its floor or a conditional up-branch (#3927/#3971)."),
    "CRITIC_VETO": (KIND_POLICY, "Commit refused: a stage-2 critic's veto stands (#3752)."),
    "HEVY_ROUTINE_DELETED": (KIND_POLICY, "Commit refused: the routine's Hevy copy was deleted in the app (#4066)."),
    "HEVY_CONFLICT": (KIND_POLICY, "Write refused: Hevy's copy was edited in the app since the platform last saw it."),
    # #4190: a WRITE tool's arguments carried the calling client's own tool-call XML
    # envelope (`</decision>`, `<parameter name=…>`, `<invoke`, …). The call was
    # refused before anything was written; nothing was trimmed or rewritten.
    "TOOL_CALL_RESIDUE": (KIND_POLICY, "Write refused: an argument carries tool-call XML residue."),
}

ERROR_CODES: dict[str, str] = {code: desc for code, (_kind, desc) in _ERROR_CODE_SPECS.items()}
ERROR_KINDS: dict[str, str] = {code: kind for code, (kind, _desc) in _ERROR_CODE_SPECS.items()}

# A code nobody registered has no known recovery; it is NOT a transport error, so it is
# not told to retry (the pre-#4172 fallback "Retry or check system status." was exactly
# the advice that looped an agent on a policy refusal).
KIND_UNREGISTERED = "unregistered"


def error_kind(error_code: str) -> str:
    """policy | argument | transport for a registered code; 'unregistered' for any other."""
    return ERROR_KINDS.get(error_code, KIND_UNREGISTERED)


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
        dict with keys: error, error_code, kind, suggestions
        (and optionally: detail). `kind` is the code's registered kind (#4172):
        a `policy` refusal answers the same call identically — change what it
        judged; only `transport` is ever worth a retry.

    Examples:
        return mcp_error("No Whoop data found", "NO_DATA",
                         ["Try a shorter date range", "Check get_freshness_status"])

        return mcp_error("DynamoDB query failed", "INTERNAL", detail=str(e))
    """
    if suggestions is None:
        suggestions = _default_suggestions(error_code)

    response: dict[str, Any] = {
        "error": message,
        "error_code": error_code,
        "kind": error_kind(error_code),
        "suggestions": suggestions,
    }
    if detail is not None:
        response["detail"] = str(detail)
    return response


# The default recovery per code, when the call site derives nothing more specific.
# `tests/test_mcp_suggestion_tool_names_2666.py` holds every `policy` code's entry to the
# no-retry rule and every tool name here to the registry.
_DEFAULT_SUGGESTIONS: dict[str, list[str]] = {
    "NO_DATA": [
        "Try a shorter or different date range.",
        "Call get_freshness_status to check when this source last updated.",
    ],
    "DATE_RANGE": [
        "Use YYYY-MM-DD format for both start_date and end_date.",
        "Ensure start_date is on or before end_date.",
        "Limit the range to 365 days or fewer.",
    ],
    "MISSING_ARG": [
        "Check the tool's required arguments and retry.",
    ],
    "INVALID_ARG": [
        "The error names the argument and what it accepts — re-issue the call with an accepted value.",
    ],
    "INVALID_ACTION": [
        "Use one of the actions the error lists; the action name is exact.",
    ],
    "NOT_FOUND": [
        "The id is an exact string, not a prefix or a title — read it back from the tool's listing action and re-issue the call.",
    ],
    "MOVEMENT_UNMAPPABLE": [
        "Use one of the movement keys the error offers under 'Did you mean', or give the exercise's exact Hevy title.",
    ],
    "UNRESOLVED_MOVEMENT": [
        "Re-draft the routine (draft_custom) with a movement key or exact Hevy title the platform's exercise index resolves.",
    ],
    "LINK_UNVERIFIED": [
        "Give the canonical URL of the page itself (not a search result or a redirect), or omit the link and give the title and author.",
    ],
    "HEVY_PRECHECK_FAILED": [
        "Fix the named fields in a new draft (draft_custom) — this is Hevy's schema, not a transient — then commit that routine_id.",
    ],
    "HEVY_BAD_REQUEST": [
        "Hevy's response body in `error` names the rejected field — fix it in a new draft (draft_custom) and commit that routine_id.",
    ],
    "TOOL_CALL_RESIDUE": [
        "Re-issue the call with the plain text of each argument — no `</…>` closers, no `<parameter name=…>`, no `<invoke` markup.",
        "The residue is your own tool-call envelope echoed into a string argument; check the argument that FOLLOWED the residue too, it was probably swallowed (the live specimen lost `followed=true`).",
    ],
    "SOURCE_UNAVAIL": [
        "Call get_freshness_status to see which sources are current.",
        "This source may not have data for the requested date.",
    ],
    "PARTIAL_DATA": [
        "Some fields may be missing — interpret available data with caution.",
        "Call get_freshness_status to see if the source is fully ingested.",
    ],
    "QUERY_TOO_BROAD": [
        "Split the request into smaller date windows (e.g. 90-day chunks).",
        "Use find_days to locate the specific days that matter, instead of scanning the whole span.",
    ],
    "INTERNAL": [
        "Retry the request — this may be a transient error.",
        "If the error persists, check CloudWatch logs for the MCP Lambda.",
    ],
    "RATE_LIMIT": [
        "This write tool was called many times in a short window (runaway guard).",
        "Wait a few seconds and retry — the limit clears automatically as the rolling window slides. No new conversation needed.",
    ],
    "HEVY_RETRYABLE": [
        "Hevy was unreachable or answered 5xx through the retry budget; nothing was written — retry in a minute.",
    ],
    "HEVY_AUTH": [
        "Rotate the life-platform/hevy-write secret; the Lambda's cached copy refreshes within 15 minutes, then retry.",
    ],
    "HEVY_ORPHAN_CREATED": [
        "Inspect the created routine in the Hevy app; the platform IR is linked to it, so the next commit of this routine_id UPDATES it rather than creating another.",
    ],
    # ── policy refusals: what would change the answer, never 'retry' (#4172) ──
    "REDTEAM_BINDING": [
        "Run plan_next_session with this routine_id (stage 2) and commit what it verdicts — the commit is bound to the routine the red team saw, unchanged since.",
        "Or commit the routine the error names as already red-teamed for this date, if that is the one meant.",
        "Or pass owner_override_redteam=true with override_reason in the owner's own words — the override is stamped into the stored routine and reported as a warning.",
    ],
    "SUBTRACT_ONLY_VIOLATION": [
        "Raise each named set to at least its floor (the error names the set, the floor and where the floor came from), or remove the conditional up-branch clause, in a new draft (draft_custom) — then run stage 2 and commit that routine_id.",
        "There is no chat override for this gate: a set under its floor is refused until the draft clears it.",
    ],
    "CRITIC_VETO": [
        "Address the vetoing critic's finding (the error names the critic and its reason) in a new draft (draft_custom), then run plan_next_session with that routine_id (stage 2) and commit what it verdicts.",
        "Or overrule THAT critic in the owner's own words: plan_next_session with veto_override={critic, owner_words} on this routine_id — the words are stored verbatim on the verdict.",
    ],
    "HEVY_ROUTINE_DELETED": [
        "Draft a new routine (draft_custom), red-team it (plan_next_session with routine_id), then commit that new routine_id.",
        "The stored routine still points at a Hevy id the app deleted — committing the same routine_id refuses the same way.",
    ],
    "HEVY_CONFLICT": [
        "Read the routine back (action=get) — Hevy's copy was edited in the app after the platform last wrote it, and the platform will not overwrite an in-app edit.",
        "Either keep the in-app edit and leave the platform copy as is, or draft from the current Hevy state (draft_custom) and commit that new routine_id.",
    ],
}


def _default_suggestions(error_code: str) -> list[str]:
    """Return sensible default recovery suggestions for each error code."""
    return list(
        _DEFAULT_SUGGESTIONS.get(
            error_code,
            [f"Unregistered error code {error_code!r}: no default recovery is known — read `error` and `detail`."],
        )
    )


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
