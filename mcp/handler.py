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
import urllib.parse

from mcp.config import logger, __version__
from mcp.core import get_api_key, decimal_to_float
from mcp.registry import TOOLS
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
    logger.info(f"Calling tool '{name}' with args: {arguments}")
    result = TOOLS[name]["fn"](arguments)
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}


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

def _get_bearer_token():
    """Derive a deterministic Bearer token from the API key using HMAC.
    Cached with 5-min TTL to support key rotation without redeployment."""
    now = time.time()
    if "token" in _BEARER_TOKEN_CACHE and now - _BEARER_TOKEN_CACHE.get("ts", 0) < _BEARER_CACHE_TTL:
        return _BEARER_TOKEN_CACHE["token"]

    api_key = get_api_key()
    if not api_key:
        # Fallback: accept any token if no API key configured
        _BEARER_TOKEN_CACHE["token"] = None
        _BEARER_TOKEN_CACHE["ts"] = now
        return None
    sig = hmac.new(api_key.encode(), b"life-platform-bearer-v1", hashlib.sha256).hexdigest()
    _BEARER_TOKEN_CACHE["token"] = f"lp_{sig}"
    _BEARER_TOKEN_CACHE["ts"] = now
    return _BEARER_TOKEN_CACHE["token"]


def _validate_bearer(event):
    """Validate Bearer token from Authorization header. Returns True if valid."""
    expected = _get_bearer_token()
    if expected is None:
        return True  # No API key configured — skip validation
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
