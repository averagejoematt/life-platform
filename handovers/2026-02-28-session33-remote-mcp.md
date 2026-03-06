# Life Platform — Session Handover
# Session: Remote MCP Connector (Claude Mobile + Web)
# Date: 2026-02-28
# Version: v2.44.0

## What happened this session

### Remote MCP Streamable HTTP Transport
Added MCP Streamable HTTP transport (spec 2025-06-18) to the Lambda handler, enabling the Life Platform MCP server to be used as a custom connector in claude.ai and the Claude iOS/Android apps.

**How it works:**
The Lambda handler now detects three transport modes from the incoming event:
1. **Remote MCP** — Function URL HTTP requests (has `requestContext.http.method`)
   - HEAD / → 200 with MCP-Protocol-Version header (connector discovery)
   - POST / → JSON-RPC processing (tools/list, tools/call, initialize, ping)
   - GET / → 405 (no SSE support in Lambda BUFFERED mode)
   - Authless — Function URL is unguessable 40-char token
2. **Bridge** — boto3 lambda.invoke() from mcp_bridge.py (no requestContext)
   - Requires x-api-key auth (unchanged)
3. **EventBridge** — nightly cache warmer (source=aws.events)

**Key design decisions:**
- Refactored `_process_jsonrpc()` as shared processor for both transports
- Protocol version negotiation: returns 2025-06-18 for modern clients, 2024-11-05 for legacy
- Added `ping` method handler (connection keepalive)
- Notifications return 202 Accepted (Streamable HTTP spec) for remote, 204 for bridge
- No SSE — Lambda BUFFERED mode returns complete JSON responses
- No session ID — Lambda is stateless; each request is independent

### AWS Changes
- Function URL CORS expanded: POST, HEAD, GET, OPTIONS methods
- CORS headers: added accept, mcp-session-id, mcp-protocol-version
- CORS expose headers: mcp-session-id, mcp-protocol-version
- MaxAge: 86400 (1 day cache for preflight)

## Files modified
- `mcp/handler.py` — refactored into dual-transport handler
- `mcp/config.py` — version 2.44.0
- `deploy/deploy_remote_mcp.sh` — new deploy script
- `docs/CHANGELOG.md` — v2.44.0 entry
- `docs/PROJECT_PLAN.md` — version bump

## Validation needed
After deploying (`chmod +x deploy/deploy_remote_mcp.sh && ./deploy/deploy_remote_mcp.sh`):

1. **Verify HEAD works:** `curl -I https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/`
   - Should return 200 with `MCP-Protocol-Version: 2025-06-18`
2. **Verify POST initialize:** `curl -X POST -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/`
   - Should return protocolVersion: 2025-06-18, serverInfo with version 2.44.0
3. **Verify bridge still works:** Use Claude Desktop as normal
4. **Register connector:** claude.ai → Settings → Connectors → Add Custom Connector → paste Function URL
5. **Test on iPhone:** Open Claude app → should see Life Platform connector available

## Current state
- Version: v2.44.0
- 94 MCP tools accessible via claude.ai, Claude mobile, AND Claude Desktop
- Three transport modes in single Lambda handler
- Backwards compatible with existing bridge

## Next steps
- Test all 94 tools via claude.ai web interface
- Feature #2 (Google Calendar) or #1 (Monarch Money)
- Feature #13 (Annual Health Report)
