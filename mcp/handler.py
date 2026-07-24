"""
Lambda handler and MCP protocol implementation.

Supports two transport modes:
1. Remote MCP (Streamable HTTP via Function URL) — for claude.ai, mobile, desktop
2. Local bridge (direct Lambda invoke via boto3) — legacy Claude Desktop bridge

The remote transport implements MCP Streamable HTTP (spec 2025-06-18):
- POST / — JSON-RPC request/response
- HEAD / — Protocol version discovery
- GET /  — 405 (no SSE support in Lambda)

OAuth: Minimal auto-approve flow to satisfy Claude's connector requirement.
Security is provided by the unguessable 40-char Lambda Function URL, not OAuth.
"""

import base64
import concurrent.futures
import hashlib
import hmac
import html
import json
import os
import time
import urllib.parse
import uuid
from typing import Any, cast

from mcp import audit as mcp_audit
from mcp.config import __version__, logger
from mcp.core import (
    SESSION_TOKEN_TTL_SECS,
    get_api_key,
    oauth_code_consume,
    oauth_code_store,
    session_token_issue,
    session_token_valid,
)
from mcp.registry import TOOLS
from mcp.utils import mcp_error, validate_date_range, validate_single_date
from mcp.warmer import nightly_cache_warmer

# ── MCP protocol constants ────────────────────────────────────────────────────
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_PROTOCOL_VERSION_LEGACY = "2024-11-05"

# Headers included in all remote MCP responses
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    "Cache-Control": "no-cache",
}


# ── MCP protocol handlers ─────────────────────────────────────────────────────
def handle_initialize(params):
    # Negotiate protocol version — support both current and legacy
    client_version = params.get("protocolVersion", MCP_PROTOCOL_VERSION_LEGACY)
    server_version = MCP_PROTOCOL_VERSION if client_version >= "2025" else MCP_PROTOCOL_VERSION_LEGACY

    return {
        "protocolVersion": server_version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "life-platform", "version": __version__},
    }


def handle_tools_list(_params):
    return {"tools": [t["schema"] for t in TOOLS.values()]}


def _audit_tool_call(name, arguments, status, duration_ms):
    """#753: record a mutating tool call to the mcp-audit/ S3 trail.

    Fail-open at BOTH layers — record_mutation never raises by contract, and
    this wrapper catches anyway so an audit bug can never fail or block the
    actual tool call. Runs AFTER the tool has executed, so the audit path adds
    zero latency before the mutation and cannot prevent it.
    """
    try:
        if mcp_audit.is_write_tool(name):
            mcp_audit.record_mutation(name, arguments, status, duration_ms)
    except Exception as e:  # noqa: BLE001 — fail-open is the contract (#753)
        logger.warning(f"[#753] audit hook failed for '{name}' (tool call unaffected): {e}")


def handle_tools_call(params):
    name = params.get("name")
    arguments = params.get("arguments", {})
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}")
    # SEC-3: Validate arguments before execution
    validation_error = _validate_tool_args(name, arguments)
    if validation_error:
        logger.warning(f"[SEC-3] Input validation failed for '{name}': {validation_error}")
        raise ValueError(f"Invalid arguments for tool '{name}': {validation_error}")
    logger.info(f"Calling tool '{name}' with args: {arguments}")
    # R13-F12: Rate limit write tools before execution
    rate_err = _check_write_rate_limit(name)
    if rate_err:
        return {"content": [{"type": "text", "text": json.dumps(mcp_error(message=rate_err, error_code="RATE_LIMIT"), default=str)}]}
    _t0 = time.time()
    # R6: per-tool soft timeout — returns a structured error instead of hanging
    # the Lambda until the 300s hard limit. 30s is the default; query-too-broad
    # errors guide Claude to try a narrower date range or use a summary tool.
    _TOOL_TIMEOUT_SECS = 30
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
            _future = _pool.submit(TOOLS[name]["fn"], arguments)
            try:
                result = _future.result(timeout=_TOOL_TIMEOUT_SECS)
            except concurrent.futures.TimeoutError:
                _emit_tool_metric(name, _TOOL_TIMEOUT_SECS * 1000, success=False)
                # #753: a timed-out write may or may not have landed — audit it.
                _audit_tool_call(name, arguments, "timeout", _TOOL_TIMEOUT_SECS * 1000)
                logger.warning(f"Tool '{name}' exceeded {_TOOL_TIMEOUT_SECS}s soft timeout")
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                mcp_error(
                                    message=(
                                        f"Tool '{name}' timed out after {_TOOL_TIMEOUT_SECS}s. "
                                        "The query is likely scanning too much data."
                                    ),
                                    error_code="QUERY_TOO_BROAD",
                                ),
                                default=str,
                            ),
                        }
                    ]
                }
        _emit_tool_metric(name, (time.time() - _t0) * 1000, success=True)
        _audit_tool_call(name, arguments, "success", (time.time() - _t0) * 1000)  # #753
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
    except Exception as e:
        _emit_tool_metric(name, (time.time() - _t0) * 1000, success=False)
        _audit_tool_call(name, arguments, "error", (time.time() - _t0) * 1000)  # #753
        # R31: Return structured error instead of propagating the exception.
        logger.error(f"Tool '{name}' raised an exception", exc_info=True)
        error_response = mcp_error(
            message=f"Tool '{name}' failed: {type(e).__name__}: {e}",
            error_code="INTERNAL",
            detail=str(e),
        )
        return {"content": [{"type": "text", "text": json.dumps(error_response, default=str)}]}


# ── SEC-3: MCP input validation ─────────────────────────────────────────────
def _validate_tool_args(name: str, arguments: dict) -> str | None:
    """Validate tool arguments against the tool's JSON schema inputSchema.

    Returns an error message string if validation fails, None if valid.
    Only validates required fields and basic type checking — not deep schema
    validation (no jsonschema dep). Covers the main injection/crash vectors.
    """
    # cast: TOOLS' heterogeneous entries infer as `object`; each is a str-keyed
    # tool-spec dict (no runtime effect).
    tool = cast("dict[str, Any]", TOOLS.get(name))
    if not tool:
        return None  # unknown tool handled separately

    schema = tool.get("schema", {}).get("inputSchema", {})
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # 1. Check required fields are present
    for field in required:
        if field not in arguments:
            return f"Missing required argument: '{field}'"

    # 2. Check types of provided arguments against schema
    TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for arg_name, arg_val in arguments.items():
        if arg_name not in properties:
            continue  # allow extra args — don't break existing callers
        expected_type = properties[arg_name].get("type")
        if not expected_type:
            continue
        py_type = TYPE_MAP.get(expected_type)
        if py_type and not isinstance(arg_val, py_type):
            # Allow int where float expected (JSON numbers)
            if expected_type == "number" and isinstance(arg_val, int):
                continue
            return f"Argument '{arg_name}' has wrong type: " f"expected {expected_type}, got {type(arg_val).__name__}"

    # 3. Sanity check: reject suspiciously large string values (prompt injection guard)
    MAX_STRING_LEN = 2000
    for arg_name, arg_val in arguments.items():
        if isinstance(arg_val, str) and len(arg_val) > MAX_STRING_LEN:
            return f"Argument '{arg_name}' exceeds maximum length " f"({len(arg_val)} > {MAX_STRING_LEN} chars)"

    # 4. SEC-3 MEDIUM: Date range validation — prevents unbounded DDB range scans.
    # Automatically applied to any tool that accepts start_date + end_date args.
    # validate_date_range enforces YYYY-MM-DD format, calendar validity, ordering,
    # and a 365-day span cap (730-day hard max). See mcp/utils.py.
    if "start_date" in arguments and "end_date" in arguments:
        date_err = validate_date_range(arguments["start_date"], arguments["end_date"])
        if date_err:
            return f"Invalid date range: {date_err}"

    # Single-date tools (e.g. "date" argument only)
    elif "date" in arguments and isinstance(arguments["date"], str):
        date_err = validate_single_date(arguments["date"])
        if date_err:
            return f"Invalid date: {date_err}"

    return None


# ── COST-2: EMF tool usage metrics ───────────────────────────────────────────
# Emits per-tool CloudWatch metrics via Embedded Metrics Format (EMF).
# EMF is printed to stdout — Lambda auto-ingests it with zero IAM changes.
# Namespace: LifePlatform/MCP  |  Dimensions: ToolName
# After 30 days of data: use SIMP-1 audit to identify 0-invocation tools.
def _emit_tool_metric(tool_name: str, duration_ms: float, success: bool) -> None:
    """Emit EMF metric for a single tool invocation."""
    try:
        ts = int(time.time() * 1000)
        emf = {
            "_aws": {
                "Timestamp": ts,
                "CloudWatchMetrics": [
                    {
                        "Namespace": "LifePlatform/MCP",
                        "Dimensions": [["ToolName"]],
                        "Metrics": [
                            {"Name": "ToolInvocations", "Unit": "Count"},
                            {"Name": "ToolDuration", "Unit": "Milliseconds"},
                            {"Name": "ToolErrors", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "ToolName": tool_name,
            "ToolInvocations": 1,
            "ToolDuration": round(duration_ms, 1),
            "ToolErrors": 0 if success else 1,
        }
        print(json.dumps(emf))
    except Exception as e:
        logger.warning(f"[COST-2] Failed to emit EMF metric for '{tool_name}': {e}")


# ── SEC: Auth failure EMF metric ────────────────────────────────────────────
# Emits a CloudWatch metric on every rejected Bearer token attempt.
# Namespace: LifePlatform/MCP  |  Dimension: EventType=AuthFailure
# Alarm on AuthFailures >= 5 in 5 min to detect credential probing.
def _emit_auth_failure_metric() -> None:
    """Emit EMF metric for a rejected Bearer token."""
    try:
        ts = int(time.time() * 1000)
        emf = {
            "_aws": {
                "Timestamp": ts,
                "CloudWatchMetrics": [
                    {
                        "Namespace": "LifePlatform/MCP",
                        "Dimensions": [["EventType"]],
                        "Metrics": [
                            {"Name": "AuthFailures", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "EventType": "AuthFailure",
            "AuthFailures": 1,
        }
        print(json.dumps(emf))
    except Exception as e:
        logger.warning(f"[SEC] Failed to emit auth failure metric: {e}")


METHOD_HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "notifications/initialized": lambda _: None,
    "ping": lambda _: {},
}


def _process_jsonrpc(body: dict) -> dict | None:
    """Process a single JSON-RPC message. Returns response dict or None for notifications."""
    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})
    logger.info(f"MCP request: method={method} id={rpc_id}")

    handler = METHOD_HANDLERS.get(method)
    if handler is None:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    try:
        result = handler(params)
        if result is None:
            return None  # notification — no response
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    except ValueError as e:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": str(e)}}
    except Exception as e:
        logger.error(f"Tool error: {e}", exc_info=True)
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}


# ── Remote MCP transport (Streamable HTTP via Function URL) ───────────────────
def _remote_response(status_code, body="", extra_headers=None):
    """Build a Function URL response with standard MCP headers."""
    headers = {**_MCP_HEADERS}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": status_code, "headers": headers, "body": body}


def _get_base_url(event):
    """Extract base URL from Function URL event."""
    domain = event.get("requestContext", {}).get("domainName", "")
    return f"https://{domain}" if domain else ""


def _parse_body(event):
    """Parse request body, handling base64 encoding and both JSON and form-encoded."""
    raw = event.get("body", "") or ""
    if event.get("isBase64Encoded") and raw:
        raw = base64.b64decode(raw).decode("utf-8")
    if not raw:
        return {}
    # Try JSON first, fall back to form-encoded
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return dict(urllib.parse.parse_qsl(raw))


# ── OAuth 2.1 flow (PKCE + passcode consent) ─────────────────────────────────
# Claude's connector infrastructure requires OAuth discovery. /authorize is NO
# LONGER auto-approve (#893-B): it gates on a passcode (or a remembered-browser
# cookie), so knowing the Function URL alone cannot mint a code. /token then
# exchanges the PKCE-bound code for a short-lived, revocable session bearer
# (#893-A) rather than the permanent key-derived Desktop bearer.

_BEARER_TOKEN_CACHE: dict[str, Any] = {}
_BEARER_CACHE_TTL = 300  # 5 min — ensures warm containers pick up new key after rotation

# R13-F12: Per-invocation write tool rate limiting.
# Rolling-window rate limit (in-memory, per warm container).
#
# HISTORY: this was a per-tool lifetime counter that the docstring claimed
# "resets every invocation" — but the dict is module-level, so it actually
# accumulated across every request a warm container served (i.e. across the
# whole conversation AND unrelated prior sessions) and only cleared on a cold
# start. Result: legitimate multi-step flows (draft -> dry_run -> commit, with a
# couple of retries) intermittently tripped RATE_LIMIT and the only "fix" was
# forcing a cold start. Since one Lambda invocation handles exactly one tool
# call (see _process_jsonrpc), a true per-invocation reset would also be wrong —
# it could never exceed 1, defeating the runaway-loop guard entirely.
#
# FIX: a rolling time window. At most _WRITE_TOOL_RATE_LIMIT calls to a given
# write tool within _WRITE_TOOL_RATE_WINDOW_SECS. A runaway loop (many calls/sec)
# trips within ~a second; a human-paced multi-step flow never does; and it
# self-heals as the window slides — no cold start required. Lambda serializes
# invocations within a container, so no lock is needed.
_WRITE_TOOL_CALLS: dict[str, list] = {}  # tool -> recent call epoch timestamps
_WRITE_TOOL_RATE_LIMIT = 20  # max calls per tool within the window
_WRITE_TOOL_RATE_WINDOW_SECS = 60  # rolling window

_RATE_LIMITED_TOOLS = {
    "create_todoist_task",
    "write_platform_memory",
    "delete_platform_memory",
    # ADR-066: fat tool — cap covers worst-case write loop (commit/archive).
    # Read actions (list/get/dry_run) also count toward the window; trade-off
    # accepted to keep one tool surface rather than splitting.
    "manage_hevy_routine",
    # ADR-097 (Phase B): reading library write fat-tool (add_book/log_session/etc.).
    "manage_reading",
}


def _check_write_rate_limit(tool_name: str):
    """R13-F12: rolling-window write-tool rate limit.

    Returns an error message string if the limit is exceeded within the window,
    else None (and records the call). Stops runaway loops without penalizing a
    normal human-paced sequence of writes.
    """
    if tool_name not in _RATE_LIMITED_TOOLS:
        return None
    now = time.time()
    cutoff = now - _WRITE_TOOL_RATE_WINDOW_SECS
    recent = [t for t in _WRITE_TOOL_CALLS.get(tool_name, []) if t >= cutoff]
    if len(recent) >= _WRITE_TOOL_RATE_LIMIT:
        _WRITE_TOOL_CALLS[tool_name] = recent  # keep pruned list
        logger.warning(
            f"[R13-F12] Write rate limit hit for '{tool_name}': "
            f"{len(recent)} calls in {_WRITE_TOOL_RATE_WINDOW_SECS}s "
            f"(limit {_WRITE_TOOL_RATE_LIMIT})"
        )
        return (
            f"Tool '{tool_name}' exceeded {_WRITE_TOOL_RATE_LIMIT} calls in "
            f"{_WRITE_TOOL_RATE_WINDOW_SECS}s. Pause a few seconds and retry — "
            f"the limit clears as the window slides (no new conversation needed)."
        )
    recent.append(now)
    _WRITE_TOOL_CALLS[tool_name] = recent
    return None


def _get_bearer_token():
    """Derive a deterministic Bearer token from the API key using HMAC.
    Cached with 5-min TTL to support key rotation without redeployment."""
    now = time.time()
    if "token" in _BEARER_TOKEN_CACHE and now - _BEARER_TOKEN_CACHE.get("ts", 0) < _BEARER_CACHE_TTL:
        return _BEARER_TOKEN_CACHE["token"]

    api_key = get_api_key()
    if not api_key:
        # R13-F05: fail-closed — no API key means all requests are rejected.
        # Return a non-None sentinel so _validate_bearer performs a real
        # (always-failing) comparison rather than bypassing auth entirely.
        _BEARER_TOKEN_CACHE["token"] = "__NO_KEY_CONFIGURED__"
        _BEARER_TOKEN_CACHE["ts"] = now
        logger.warning("[SEC] API key not configured — MCP auth is fail-closed (all tokens rejected)")
        return "__NO_KEY_CONFIGURED__"
    sig = hmac.new(api_key.encode(), b"life-platform-bearer-v1", hashlib.sha256).hexdigest()
    _BEARER_TOKEN_CACHE["token"] = f"lp_{sig}"
    _BEARER_TOKEN_CACHE["ts"] = now
    return _BEARER_TOKEN_CACHE["token"]


def _validate_bearer(event):
    """Validate Bearer token from Authorization header. Returns True if valid.

    R13-F05: fail-closed — when no API key is configured, all requests are
    rejected rather than accepted. Previously returned True (accept-all) when
    expected was None, creating a false security boundary.
    """
    expected = _get_bearer_token()
    auth_header = (event.get("headers") or {}).get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return False
    provided = auth_header[7:].strip()
    # Fail-closed: when no API key is configured, _get_bearer_token() returns a sentinel
    # — reject everything, including any live session token (the whole boundary is off).
    if expected == "__NO_KEY_CONFIGURED__":
        return False
    # Static Desktop bearer (constant-time compare) OR a live remote session bearer
    # (#893). Desktop tokens are "lp_…" and never reach the "lps_…" session lookup, so
    # the Desktop path takes no extra DynamoDB read.
    if hmac.compare_digest(provided, expected):
        return True
    return session_token_valid(provided)


# ── /authorize consent gate (#893 option B) ───────────────────────────────────
# #893-A stopped /token from minting a permanent bearer, but /authorize still
# auto-approved anyone who knew the URL. Option B gates /authorize behind an access
# code so URL possession alone yields nothing. The code is derived from the API key
# on a distinct HMAC domain (so it can be shown/entered without exposing the key);
# a signed, expiring "remembered browser" cookie lets an already-approved browser
# refresh tokens without re-entering it. The static Desktop bearer path is untouched.
_AUTHORIZE_PASSCODE_DOMAIN = b"life-platform-authorize-v1"
_APPROVAL_COOKIE_NAME = "lp_approval"
_APPROVAL_COOKIE_TTL_SECS = 90 * 24 * 3600  # #916: 90 days between passcode prompts per browser
# (raised 30→90d to cut re-entry friction). This is the *passcode-bypass* window on an
# already-approved browser, NOT live API access — that stays the separate 24h `lps_`
# session bearer, deliberately left short for a tight revocation window. The cookie is
# HMAC-bound to the API key (forging needs the key) and fail-closed with no key.
_APPROVAL_COOKIE_DOMAIN = "lp-authorize-cookie-v1"


def _get_authorize_passcode():
    """The /authorize access code. Sentinel when no API key is configured — fail-closed,
    so the consent form can never be satisfied and the flow cannot mint a code."""
    api_key = get_api_key()
    if not api_key:
        return "__NO_KEY_CONFIGURED__"
    return hmac.new(api_key.encode(), _AUTHORIZE_PASSCODE_DOMAIN, hashlib.sha256).hexdigest()


def _issue_approval_cookie():
    """Signed, expiring 'remembered browser' cookie string (for the response `cookies`
    array). HMAC-bound to the API key; forging it requires the key. None if no key."""
    api_key = get_api_key()
    if not api_key:
        return None
    exp = int(time.time()) + _APPROVAL_COOKIE_TTL_SECS
    sig = hmac.new(api_key.encode(), f"{_APPROVAL_COOKIE_DOMAIN}:{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{_APPROVAL_COOKIE_NAME}={exp}.{sig}; Max-Age={_APPROVAL_COOKIE_TTL_SECS}; Path=/; HttpOnly; Secure; SameSite=Lax"


def _approval_cookie_valid(event):
    """True iff the request carries a valid, unexpired, HMAC-verified approval cookie.
    Reads both the payload-2.0 `cookies` array and a `Cookie` header (case-insensitive)."""
    api_key = get_api_key()
    if not api_key:
        return False
    raw = []
    if isinstance(event.get("cookies"), list):
        raw.extend(event["cookies"])
    headers = event.get("headers") or {}
    cookie_hdr = headers.get("cookie") or headers.get("Cookie") or ""
    if cookie_hdr:
        raw.extend(cookie_hdr.split(";"))
    for part in raw:
        part = part.strip()
        if not part.startswith(_APPROVAL_COOKIE_NAME + "="):
            continue
        val = part[len(_APPROVAL_COOKIE_NAME) + 1 :]
        exp_s, sep, sig = val.rpartition(".")
        if not sep:
            return False
        try:
            exp = int(exp_s)
        except ValueError:
            return False
        if exp < time.time():
            return False
        expected = hmac.new(api_key.encode(), f"{_APPROVAL_COOKIE_DOMAIN}:{exp}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    return False


def _authorize_form_html(redirect_uri, state, code_challenge, code_challenge_method, error=""):
    """The consent page: a passcode field + hidden OAuth params. All reflected values are
    HTML-escaped (the redirect_uri is already allowlisted before this renders)."""
    e = html.escape
    err = f'<p class="err">{e(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Authorize access</title><style>
 body{{font-family:-apple-system,system-ui,sans-serif;background:#0b0d10;color:#e7e9ec;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
 form{{background:#14181d;padding:2rem;border-radius:12px;max-width:22rem;width:90%;box-shadow:0 8px 40px rgba(0,0,0,.4)}}
 h1{{font-size:1.05rem;margin:0 0 .25rem}} p{{color:#9aa4af;font-size:.85rem;margin:.25rem 0 1rem}} .err{{color:#ff6b6b}}
 input[type=password]{{width:100%;box-sizing:border-box;padding:.6rem;border-radius:8px;border:1px solid #2a323b;background:#0b0d10;color:#e7e9ec;font-size:1rem}}
 button{{margin-top:1rem;width:100%;padding:.65rem;border:0;border-radius:8px;background:#4f8cff;color:#fff;font-size:1rem;cursor:pointer}}
</style></head><body><form method="post" autocomplete="off">
 <h1>Authorize this connection</h1>
 <p>Enter the access code to connect this client to the Life&nbsp;Platform MCP server.</p>
 {err}
 <input type="password" name="passcode" placeholder="Access code" autofocus required>
 <input type="hidden" name="redirect_uri" value="{e(redirect_uri)}">
 <input type="hidden" name="state" value="{e(state)}">
 <input type="hidden" name="code_challenge" value="{e(code_challenge)}">
 <input type="hidden" name="code_challenge_method" value="{e(code_challenge_method)}">
 <button type="submit">Authorize</button>
</form></body></html>"""


def _issue_code_and_redirect(redirect_uri, state, code_challenge, code_challenge_method, set_cookie=None):
    """Mint a single-use PKCE-bound code, store it, and 302 back to the (already
    allowlisted) redirect_uri. Optionally set the remembered-browser cookie."""
    code = uuid.uuid4().hex + uuid.uuid4().hex  # 256-bit opaque code
    if not oauth_code_store(code, code_challenge, code_challenge_method, redirect_uri):
        return _remote_response(500, json.dumps({"error": "server_error", "error_description": "could not issue code"}))
    logger.info(f"[OAuth] Issued code → host={urllib.parse.urlparse(redirect_uri).hostname} pkce={'y' if code_challenge else 'n'}")
    params = urllib.parse.urlencode({"code": code, "state": state})
    sep = "&" if "?" in redirect_uri else "?"
    resp = {"statusCode": 302, "headers": {"Location": f"{redirect_uri}{sep}{params}", "Cache-Control": "no-store"}, "body": ""}
    if set_cookie:
        resp["cookies"] = [set_cookie]  # payload 2.0 sets cookies via the top-level array
    return resp


def _handle_oauth_server_metadata(event):
    """GET /.well-known/oauth-authorization-server — RFC 8414"""
    base = _get_base_url(event)
    logger.info(f"[OAuth] Serving auth server metadata for {base}")
    return _remote_response(
        200,
        json.dumps(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/authorize",
                "token_endpoint": f"{base}/token",
                "registration_endpoint": f"{base}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
            }
        ),
    )


def _handle_resource_metadata(event):
    """GET /.well-known/oauth-protected-resource — RFC 9728"""
    base = _get_base_url(event)
    logger.info(f"[OAuth] Serving resource metadata for {base}")
    return _remote_response(
        200,
        json.dumps(
            {
                "resource": base,
                "authorization_servers": [base],
                "scopes_supported": [],
            }
        ),
    )


def _handle_register(event):
    """POST /register — Dynamic Client Registration (RFC 7591)"""
    body = _parse_body(event)
    client_id = f"lp-{uuid.uuid4().hex[:12]}"
    logger.info(f"[OAuth] Client registration: {body.get('client_name', 'unknown')} → {client_id}")
    return _remote_response(
        201,
        json.dumps(
            {
                "client_id": client_id,
                "client_name": body.get("client_name", "claude"),
                "redirect_uris": body.get("redirect_uris", []),
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }
        ),
    )


# ── OAuth redirect_uri allowlist (SEC-01 / #779) ──
# /authorize must not act as an open redirect. Only hand a code back to a callback
# whose host we trust. The default set covers the first-party MCP clients (claude.ai /
# claude.com / anthropic.com and their subdomains) plus loopback for desktop/CLI clients.
# Override with OAUTH_REDIRECT_HOSTS (comma-separated hostnames) without a code change.
_DEFAULT_REDIRECT_HOSTS = ("claude.ai", "claude.com", "anthropic.com")
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def _redirect_uri_allowed(redirect_uri: str) -> bool:
    """True if redirect_uri is an https callback on an allowlisted host (or loopback)."""
    if not redirect_uri:
        return False
    try:
        parsed = urllib.parse.urlparse(redirect_uri)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in _LOOPBACK_HOSTS:
        return True  # native/desktop clients use http://127.0.0.1:<port>/callback
    if parsed.scheme != "https":
        return False
    extra = [h.strip().lower() for h in os.environ.get("OAUTH_REDIRECT_HOSTS", "").split(",") if h.strip()]
    allowed = set(_DEFAULT_REDIRECT_HOSTS) | set(extra)
    # Exact host or a subdomain of an allowed apex (foo.claude.ai), never a suffix trick.
    return any(host == a or host.endswith("." + a) for a in allowed)


def _verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    """RFC 7636 PKCE verification. S256 is required; 'plain' accepted only if the
    client explicitly registered it (Claude uses S256)."""
    if not code_challenge:
        return False
    if method == "S256":
        if not code_verifier:
            return False
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(computed, code_challenge)
    if method == "plain":
        return bool(code_verifier) and hmac.compare_digest(code_verifier, code_challenge)
    return False


def _handle_authorize(event):
    """GET /authorize — consent gate, then a single-use PKCE-bound code + redirect back.

    SEC-01 (#779): the code is stored server-side (DDB, 10-min TTL) with its PKCE
    challenge and redirect_uri so /token can only exchange a code this server minted; the
    redirect target is allowlisted so /authorize can't be turned into an open redirect.
    SEC (#893-B): the auto-approve is gone — a request must either carry a valid
    remembered-browser cookie or complete the passcode consent form (POST /authorize),
    so knowing the URL alone can no longer mint a code.
    """
    qs = event.get("queryStringParameters") or {}
    redirect_uri = qs.get("redirect_uri", "")
    state = qs.get("state", "")
    code_challenge = qs.get("code_challenge", "")
    code_challenge_method = (qs.get("code_challenge_method") or "S256").upper()

    if not redirect_uri:
        return _remote_response(400, json.dumps({"error": "invalid_request", "error_description": "missing redirect_uri"}))
    if not _redirect_uri_allowed(redirect_uri):
        logger.warning(f"[OAuth] Rejected disallowed redirect_uri host: {urllib.parse.urlparse(redirect_uri).hostname!r}")
        return _remote_response(400, json.dumps({"error": "invalid_request", "error_description": "redirect_uri not allowed"}))

    # Already-approved browser → refresh without re-prompting; otherwise show the form.
    if _approval_cookie_valid(event):
        return _issue_code_and_redirect(redirect_uri, state, code_challenge, code_challenge_method)
    return _remote_response(
        200,
        _authorize_form_html(redirect_uri, state, code_challenge, code_challenge_method),
        {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
    )


def _handle_authorize_submit(event):
    """POST /authorize — the consent form target. Validates the passcode, then issues the
    code + sets the remembered-browser cookie. redirect_uri is re-validated (never trust a
    form field), and passcode is checked in constant time. Fail-closed with no API key."""
    body = _parse_body(event)
    redirect_uri = body.get("redirect_uri", "")
    state = body.get("state", "")
    code_challenge = body.get("code_challenge", "")
    code_challenge_method = (body.get("code_challenge_method") or "S256").upper()
    passcode = (body.get("passcode") or "").strip()

    if not redirect_uri or not _redirect_uri_allowed(redirect_uri):
        return _remote_response(400, json.dumps({"error": "invalid_request", "error_description": "redirect_uri not allowed"}))

    expected = _get_authorize_passcode()
    if expected == "__NO_KEY_CONFIGURED__":
        return _remote_response(500, json.dumps({"error": "server_error"}))
    if not passcode or not hmac.compare_digest(passcode, expected):
        logger.warning("[OAuth] /authorize passcode rejected")
        _emit_auth_failure_metric()
        return _remote_response(
            401,
            _authorize_form_html(redirect_uri, state, code_challenge, code_challenge_method, error="Incorrect access code."),
            {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
        )

    return _issue_code_and_redirect(redirect_uri, state, code_challenge, code_challenge_method, set_cookie=_issue_approval_cookie())


def _handle_token(event):
    """POST /token — exchange a server-issued, single-use, PKCE-verified code for the bearer.

    SEC-01: previously returned the real bearer for ANY POST (fully unauthenticated). Now the
    request must present a code /authorize issued; the code is consumed atomically (single-use),
    the PKCE code_verifier is checked against the stored challenge, and redirect_uri must match.
    """
    body = _parse_body(event)
    grant_type = body.get("grant_type", "")
    code = (body.get("code") or "").strip()
    code_verifier = body.get("code_verifier") or ""
    redirect_uri = body.get("redirect_uri") or ""

    if grant_type != "authorization_code":
        return _remote_response(400, json.dumps({"error": "unsupported_grant_type"}))

    binding = oauth_code_consume(code)
    if binding is None:
        logger.warning("[OAuth] Token exchange rejected: unknown/expired/replayed code")
        return _remote_response(400, json.dumps({"error": "invalid_grant", "error_description": "invalid or expired code"}))

    # redirect_uri, when the client sends one, must match what it authorized with.
    if redirect_uri and binding["redirect_uri"] and not hmac.compare_digest(redirect_uri, binding["redirect_uri"]):
        logger.warning("[OAuth] Token exchange rejected: redirect_uri mismatch")
        return _remote_response(400, json.dumps({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}))

    # PKCE: if the code was issued with a challenge (Claude always sends S256), it must verify.
    if binding["code_challenge"] and not _verify_pkce(code_verifier, binding["code_challenge"], binding["code_challenge_method"]):
        logger.warning("[OAuth] Token exchange rejected: PKCE verification failed")
        return _remote_response(400, json.dumps({"error": "invalid_grant", "error_description": "PKCE verification failed"}))

    # SEC (#893): fail closed if no API key is configured at all (the auth boundary is
    # otherwise off). Then mint a random, short-lived, revocable SESSION bearer rather
    # than returning the permanent key-derived Desktop bearer — so completing the
    # (auto-approving) OAuth flow no longer yields a credential that never expires.
    if _get_bearer_token() == "__NO_KEY_CONFIGURED__":
        return _remote_response(500, json.dumps({"error": "server_error"}))
    session_token = session_token_issue()
    if not session_token:
        return _remote_response(500, json.dumps({"error": "server_error"}))

    logger.info("[OAuth] Token exchange OK — session bearer issued")
    return _remote_response(
        200,
        json.dumps({"access_token": session_token, "token_type": "Bearer", "expires_in": SESSION_TOKEN_TTL_SECS}),
    )


# ── Remote MCP request handler ────────────────────────────────────────────────
def handle_remote_mcp(event, method):
    """
    Handle MCP Streamable HTTP transport.
    Routes OAuth endpoints, then MCP JSON-RPC.
    """
    raw_path = event.get("requestContext", {}).get("http", {}).get("path", "/")

    logger.info(f"[Remote] {method} {raw_path}")

    # ── OAuth endpoints ───────────────────────────────────────────────────
    # Strip trailing path segments some clients append (e.g. /.well-known/oauth-authorization-server/mcp)
    if "/.well-known/oauth-authorization-server" in raw_path:
        return _handle_oauth_server_metadata(event)
    if "/.well-known/oauth-protected-resource" in raw_path:
        return _handle_resource_metadata(event)
    if raw_path == "/register" and method == "POST":
        return _handle_register(event)
    if raw_path == "/authorize" and method == "GET":
        return _handle_authorize(event)
    if raw_path == "/authorize" and method == "POST":
        return _handle_authorize_submit(event)
    if raw_path == "/token" and method == "POST":
        return _handle_token(event)

    # Return 404 for any other well-known paths
    if "/.well-known/" in raw_path:
        return _remote_response(404, json.dumps({"error": "Not found"}))

    # ── Bearer token validation for MCP endpoints ─────────────────────────
    if not _validate_bearer(event):
        logger.warning("[Remote] Rejected: invalid/missing Bearer token")
        _emit_auth_failure_metric()
        return _remote_response(401, json.dumps({"error": "Unauthorized: invalid Bearer token"}), {"WWW-Authenticate": "Bearer"})

    # ── MCP protocol ──────────────────────────────────────────────────────
    # HEAD — protocol discovery
    if method == "HEAD":
        return _remote_response(200)

    # GET — SSE stream (not supported in Lambda BUFFERED mode)
    if method == "GET":
        return _remote_response(405, json.dumps({"error": "Method not allowed. Use POST."}), {"Allow": "POST, HEAD"})

    # Only POST from here
    if method != "POST":
        return _remote_response(405, json.dumps({"error": "Method not allowed"}), {"Allow": "POST, HEAD"})

    # Parse body (Function URL may base64-encode)
    try:
        raw_body = event.get("body", "")
        if event.get("isBase64Encoded") and raw_body:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        body = json.loads(raw_body) if raw_body else {}
    except (json.JSONDecodeError, Exception) as e:
        return _remote_response(
            400, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {str(e)}"}})
        )

    # Process JSON-RPC
    response_body = _process_jsonrpc(body)

    # Notifications get 202 Accepted (no body) per Streamable HTTP spec
    if response_body is None:
        return _remote_response(202)

    return _remote_response(200, json.dumps(response_body, default=str))


# ── Bridge transport (direct Lambda invoke via boto3) ─────────────────────────
def handle_bridge_invoke(event):
    """Handle local bridge invocations (mcp_bridge.py via boto3 lambda.invoke)."""
    expected_key = get_api_key()
    if expected_key:
        provided_key = (event.get("headers") or {}).get("x-api-key", "")
        if provided_key != expected_key:
            return {"statusCode": 401, "body": json.dumps({"error": "Unauthorized"}), "headers": {"Content-Type": "application/json"}}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"}), "headers": {"Content-Type": "application/json"}}

    response_body = _process_jsonrpc(body)

    if response_body is None:
        return {"statusCode": 204, "body": ""}

    return {
        "statusCode": 200,
        "body": json.dumps(response_body, default=str),
        "headers": {"Content-Type": "application/json"},
    }


# ── Lambda handler (entry point) ─────────────────────────────────────────────
def lambda_handler(event, context):
    # 1. EventBridge scheduled rule — nightly cache warmer, no auth
    if event.get("source") == "aws.events" or event.get("detail-type") == "Scheduled Event":
        logger.info("[lambda_handler] EventBridge trigger — running nightly cache warmer")
        result = nightly_cache_warmer()
        return {"statusCode": 200, "body": json.dumps(result), "headers": {"Content-Type": "application/json"}}

    # 2. Detect transport: Function URL (has requestContext.http) vs Bridge
    http_method = event.get("requestContext", {}).get("http", {}).get("method", "").upper()

    if http_method:
        logger.info(f"[lambda_handler] Remote MCP: {http_method}")
        return handle_remote_mcp(event, http_method)
    else:
        logger.info("[lambda_handler] Bridge invoke")
        return handle_bridge_invoke(event)
