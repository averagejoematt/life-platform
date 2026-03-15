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
import json
import logging
import base64
import uuid
import hmac
import hashlib
import time
import concurrent.futures
import urllib.parse

from mcp.config import logger, __version__
from mcp.core import get_api_key, decimal_to_float
from mcp.registry import TOOLS
from mcp.utils import validate_date_range, validate_single_date, mcp_error
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
    server_version = (MCP_PROTOCOL_VERSION
                      if client_version >= "2025"
                      else MCP_PROTOCOL_VERSION_LEGACY)

    return {
        "protocolVersion": server_version,
        "capabilities":    {"tools": {}},
        "serverInfo":      {"name": "life-platform", "version": __version__},
    }


def handle_tools_list(_params):
    return {"tools": [t["schema"] for t in TOOLS.values()]}


def handle_tools_call(params):
    name      = params.get("name")
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
        return {"content": [{"type": "text", "text": json.dumps(
            mcp_error(message=rate_err, error_code="RATE_LIMIT"),
            default=str
        )}]}
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
                logger.warning(f"Tool '{name}' exceeded {_TOOL_TIMEOUT_SECS}s soft timeout")
                return {"content": [{"type": "text", "text": json.dumps(
                    mcp_error(
                        message=(
                            f"Tool '{name}' timed out after {_TOOL_TIMEOUT_SECS}s. "
                            "The query is likely scanning too much data."
                        ),
                        error_code="QUERY_TOO_BROAD",
                    ), default=str)}]}
        _emit_tool_metric(name, (time.time() - _t0) * 1000, success=True)
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
    except Exception as e:
        _emit_tool_metric(name, (time.time() - _t0) * 1000, success=False)
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
    tool = TOOLS.get(name)
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
        "string":  str,
        "integer": int,
        "number":  (int, float),
        "boolean": bool,
        "array":   list,
        "object":  dict,
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
            return (
                f"Argument '{arg_name}' has wrong type: "
                f"expected {expected_type}, got {type(arg_val).__name__}"
            )

    # 3. Sanity check: reject suspiciously large string values (prompt injection guard)
    MAX_STRING_LEN = 2000
    for arg_name, arg_val in arguments.items():
        if isinstance(arg_val, str) and len(arg_val) > MAX_STRING_LEN:
            return (
                f"Argument '{arg_name}' exceeds maximum length "
                f"({len(arg_val)} > {MAX_STRING_LEN} chars)"
            )

    # 4. SEC-3 MEDIUM: Date range validation — prevents unbounded DDB range scans.
    # Automatically applied to any tool that accepts start_date + end_date args.
    # validate_date_range enforces YYYY-MM-DD format, calendar validity, ordering,
    # and a 365-day span cap (730-day hard max). See mcp/utils.py.
    if "start_date" in arguments and "end_date" in arguments:
        date_err = validate_date_range(
            arguments["start_date"], arguments["end_date"]
        )
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
                "CloudWatchMetrics": [{
                    "Namespace": "LifePlatform/MCP",
                    "Dimensions": [["ToolName"]],
                    "Metrics": [
                        {"Name": "ToolInvocations", "Unit": "Count"},
                        {"Name": "ToolDuration",    "Unit": "Milliseconds"},
                        {"Name": "ToolErrors",      "Unit": "Count"},
                    ],
                }],
            },
            "ToolName":        tool_name,
            "ToolInvocations": 1,
            "ToolDuration":    round(duration_ms, 1),
            "ToolErrors":      0 if success else 1,
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
                "CloudWatchMetrics": [{
                    "Namespace": "LifePlatform/MCP",
                    "Dimensions": [["EventType"]],
                    "Metrics": [
                        {"Name": "AuthFailures", "Unit": "Count"},
                    ],
                }],
            },
            "EventType":    "AuthFailure",
            "AuthFailures": 1,
        }
        print(json.dumps(emf))
    except Exception as e:
        logger.warning(f"[SEC] Failed to emit auth failure metric: {e}")


METHOD_HANDLERS = {
    "initialize":                handle_initialize,
    "tools/list":                handle_tools_list,
    "tools/call":                handle_tools_call,
    "notifications/initialized": lambda _: None,
    "ping":                      lambda _: {},
}


def _process_jsonrpc(body: dict) -> dict | None:
    """Process a single JSON-RPC message. Returns response dict or None for notifications."""
    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})
    logger.info(f"MCP request: method={method} id={rpc_id}")

    handler = METHOD_HANDLERS.get(method)
    if handler is None:
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}

    try:
        result = handler(params)
        if result is None:
            return None  # notification — no response
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    except ValueError as e:
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32602, "message": str(e)}}
    except Exception as e:
        logger.error(f"Tool error: {e}", exc_info=True)
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}


# ── Remote MCP transport (Streamable HTTP via Function URL) ───────────────────
def _remote_response(status_code, body="", extra_headers=None):
    """Build a Function URL response with standard MCP headers."""
    headers = {**_MCP_HEADERS}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": status_code, "headers": headers, "body": body}


def _get_base_url(event):
    """Extract base URL from Function URL event."""
    domain = (event.get("requestContext", {})
                   .get("domainName", ""))
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


# ── Minimal OAuth (auto-approve) ─────────────────────────────────────────────
# Claude's connector infrastructure requires OAuth discovery even for servers
# that don't need real auth. This implements a bare-minimum OAuth 2.1 flow
# that auto-approves everything. Token validation adds a second security layer
# beyond the unguessable Lambda Function URL.

_BEARER_TOKEN_CACHE = {}
_BEARER_CACHE_TTL = 300  # 5 min — ensures warm containers pick up new key after rotation

# R13-F12: Per-invocation write tool rate limiting.
# In-memory only — resets on each Lambda cold start / invocation context.
# Prevents accidental runaway loops from hammering write operations.
_WRITE_TOOL_CALLS: dict = {}
_WRITE_TOOL_RATE_LIMIT = 10  # max calls per write tool per Lambda invocation

_RATE_LIMITED_TOOLS = {
    "create_todoist_task",
    "delete_todoist_task",
    "log_supplement",
    "write_platform_memory",
    "delete_platform_memory",
}


def _check_write_rate_limit(tool_name: str):
    """R13-F12: Check if a write tool has exceeded its per-invocation rate limit.

    Returns an error message string if limit exceeded, None if OK.
    In-memory counter resets on every Lambda invocation — prevents runaway
    loops within a single session, not across sessions.
    """
    if tool_name not in _RATE_LIMITED_TOOLS:
        return None
    count = _WRITE_TOOL_CALLS.get(tool_name, 0)
    if count >= _WRITE_TOOL_RATE_LIMIT:
        logger.warning(
            f"[R13-F12] Write rate limit hit for '{tool_name}': "
            f"{count} calls this invocation (limit {_WRITE_TOOL_RATE_LIMIT})"
        )
        return (
            f"Tool '{tool_name}' has been called {count} times this invocation "
            f"(limit: {_WRITE_TOOL_RATE_LIMIT}). Rate limit prevents runaway write loops."
        )
    _WRITE_TOOL_CALLS[tool_name] = count + 1
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
    # _get_bearer_token() now returns a sentinel string when no key is configured,
    # so the hmac.compare_digest below will always fail in that case. No special
    # case needed — fail-closed is the default path.
    auth_header = (event.get("headers") or {}).get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return False
    provided = auth_header[7:].strip()
    return hmac.compare_digest(provided, expected)

def _handle_oauth_server_metadata(event):
    """GET /.well-known/oauth-authorization-server — RFC 8414"""
    base = _get_base_url(event)
    logger.info(f"[OAuth] Serving auth server metadata for {base}")
    return _remote_response(200, json.dumps({
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }))


def _handle_resource_metadata(event):
    """GET /.well-known/oauth-protected-resource — RFC 9728"""
    base = _get_base_url(event)
    logger.info(f"[OAuth] Serving resource metadata for {base}")
    return _remote_response(200, json.dumps({
        "resource": base,
        "authorization_servers": [base],
        "scopes_supported": [],
    }))


def _handle_register(event):
    """POST /register — Dynamic Client Registration (RFC 7591)"""
    body = _parse_body(event)
    client_id = f"lp-{uuid.uuid4().hex[:12]}"
    logger.info(f"[OAuth] Client registration: {body.get('client_name', 'unknown')} → {client_id}")
    return _remote_response(201, json.dumps({
        "client_id": client_id,
        "client_name": body.get("client_name", "claude"),
        "redirect_uris": body.get("redirect_uris", []),
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }))


def _handle_authorize(event):
    """GET /authorize — Auto-approve and redirect back with auth code."""
    qs = event.get("queryStringParameters") or {}
    redirect_uri = qs.get("redirect_uri", "")
    state = qs.get("state", "")
    code = uuid.uuid4().hex

    logger.info(f"[OAuth] Auto-approve → redirect_uri={redirect_uri} state={state[:20]}...")

    if not redirect_uri:
        return _remote_response(400, json.dumps({"error": "missing redirect_uri"}))

    # Build redirect back to Claude's callback
    params = urllib.parse.urlencode({"code": code, "state": state})
    sep = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{sep}{params}"

    return {
        "statusCode": 302,
        "headers": {
            "Location": location,
            "Cache-Control": "no-store",
        },
        "body": "",
    }


def _handle_token(event):
    """POST /token — Exchange auth code for deterministic access token."""
    body = _parse_body(event)
    logger.info(f"[OAuth] Token exchange: grant_type={body.get('grant_type', '?')}")
    token = _get_bearer_token() or f"lp_{uuid.uuid4().hex}"
    return _remote_response(200, json.dumps({
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 86400,
    }))


# ── Remote MCP request handler ────────────────────────────────────────────────
def handle_remote_mcp(event, method):
    """
    Handle MCP Streamable HTTP transport.
    Routes OAuth endpoints, then MCP JSON-RPC.
    """
    raw_path = (event.get("requestContext", {})
                     .get("http", {})
                     .get("path", "/"))

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
    if raw_path == "/token" and method == "POST":
        return _handle_token(event)

    # Return 404 for any other well-known paths
    if "/.well-known/" in raw_path:
        return _remote_response(404, json.dumps({"error": "Not found"}))

    # ── Bearer token validation for MCP endpoints ─────────────────────────
    if not _validate_bearer(event):
        logger.warning(f"[Remote] Rejected: invalid/missing Bearer token")
        _emit_auth_failure_metric()
        return _remote_response(401, json.dumps({"error": "Unauthorized: invalid Bearer token"}),
                                {"WWW-Authenticate": "Bearer"})

    # ── MCP protocol ──────────────────────────────────────────────────────
    # HEAD — protocol discovery
    if method == "HEAD":
        return _remote_response(200)

    # GET — SSE stream (not supported in Lambda BUFFERED mode)
    if method == "GET":
        return _remote_response(405, json.dumps({"error": "Method not allowed. Use POST."}),
                                {"Allow": "POST, HEAD"})

    # Only POST from here
    if method != "POST":
        return _remote_response(405, json.dumps({"error": "Method not allowed"}),
                                {"Allow": "POST, HEAD"})

    # Parse body (Function URL may base64-encode)
    try:
        raw_body = event.get("body", "")
        if event.get("isBase64Encoded") and raw_body:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        body = json.loads(raw_body) if raw_body else {}
    except (json.JSONDecodeError, Exception) as e:
        return _remote_response(
            400,
            json.dumps({"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32700, "message": f"Parse error: {str(e)}"}})
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
            return {"statusCode": 401, "body": json.dumps({"error": "Unauthorized"}),
                    "headers": {"Content-Type": "application/json"}}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON"}),
                "headers": {"Content-Type": "application/json"}}

    response_body = _process_jsonrpc(body)

    if response_body is None:
        return {"statusCode": 204, "body": ""}

    return {
        "statusCode": 200,
        "body":       json.dumps(response_body, default=str),
        "headers":    {"Content-Type": "application/json"},
    }


# ── Lambda handler (entry point) ─────────────────────────────────────────────
def lambda_handler(event, context):
    # 1. EventBridge scheduled rule — nightly cache warmer, no auth
    if event.get("source") == "aws.events" or event.get("detail-type") == "Scheduled Event":
        logger.info("[lambda_handler] EventBridge trigger — running nightly cache warmer")
        result = nightly_cache_warmer()
        return {"statusCode": 200, "body": json.dumps(result),
                "headers": {"Content-Type": "application/json"}}

    # 2. Detect transport: Function URL (has requestContext.http) vs Bridge
    http_method = (event.get("requestContext", {})
                        .get("http", {})
                        .get("method", "")
                        .upper())

    if http_method:
        logger.info(f"[lambda_handler] Remote MCP: {http_method}")
        return handle_remote_mcp(event, http_method)
    else:
        logger.info("[lambda_handler] Bridge invoke")
        return handle_bridge_invoke(event)
