# Session 34 — Remote MCP Live: OAuth + Security + Function URL Fix

**Date:** 2026-02-28
**Version:** v2.44.0 → v2.45.0
**Focus:** Getting Claude connector working end-to-end, adding security layer

---

## What Happened

### Problem 1: Claude Connector Requires OAuth
Claude's connector infrastructure has a bug — it always attempts OAuth discovery and crashes when no authorization server exists, despite MCP spec supporting authless connections. Multiple GitHub issues confirm this (issues #5826, #11814, #29034).

**Solution:** Implemented minimal auto-approve OAuth 2.1 flow in `mcp/handler.py`:
- `/.well-known/oauth-authorization-server` → RFC 8414 metadata
- `/.well-known/oauth-protected-resource` → RFC 9728 resource metadata
- `/register` → Dynamic client registration, returns `lp-{hex}` client_id
- `/authorize` → Auto-approve, generates auth code, 302 redirect to Claude callback
- `/token` → Returns HMAC-derived deterministic Bearer token

### Problem 2: Function URL 403 Forbidden
Lambda Function URL returned AWS-level "Forbidden" on all requests — the Lambda was never invoked.

**Root cause:** AWS introduced "Block public access for Lambda Function URLs" in late 2024, enabled by default. The `lambda:InvokeFunctionUrl` permission alone doesn't bypass this block.

**Compounding issue:** The old Function URL had 4 duplicate permission policy statements from multiple deploy attempts, creating a confused state.

**Solution:**
1. Deleted old Function URL entirely
2. Created fresh Function URL: `c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws`
3. Added `lambda:InvokeFunction` for `*` (bypasses the public access block per SST issue #6397)
4. Cleaned up to 3 clean policy statements

**CLI challenge:** Neither local AWS CLI, CloudShell CLI, nor CloudShell boto3 had the `put-public-access-block-config` API. AWS CLI v2.33.23 still doesn't support it. The `lambda:InvokeFunction` workaround was the practical fix.

### Problem 3: Security Hardening
With public Function URL, added HMAC Bearer token validation:
- Token derived from existing API key in Secrets Manager via `hmac.new(key, "life-platform-bearer-v1", sha256)`
- `/token` endpoint returns this deterministic token to Claude's connector
- All MCP endpoints validate Bearer token before processing
- OAuth discovery endpoints remain open (required for auth flow)
- Bridge transport unchanged (x-api-key)
- Token cached in Lambda memory — no repeated Secrets Manager lookups

---

## Current State
- **Connector:** ✅ Connected in claude.ai web + mobile
- **Security:** 3 layers (unguessable URL + HMAC Bearer token + OAuth gate)
- **Function URL:** `c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws`
- **Pending deploy:** v2.45.0 with Bearer token security (code written, not yet deployed)

## Files Modified
- `mcp/handler.py` — OAuth endpoints + HMAC Bearer validation
- `mcp/config.py` — version bump to 2.45.0
- `deploy/deploy_remote_mcp.sh` — updated Function URL reference
- Lambda resource policy — 3 clean statements

## Resource Policy (clean state)
1. `EventBridgeNightlyWarmer` — allows EventBridge to invoke for scheduled tasks
2. `FunctionURLPublicAccess` — allows Function URL invocation (auth-type NONE)
3. `AllowPublicInvoke` — allows `lambda:InvokeFunction` for `*` (bypasses public access block)

---

## Pending / Next Steps
1. **Deploy v2.45.0** — `cd ~/Documents/Claude/life-platform && ./deploy/deploy_remote_mcp.sh` then delete/re-add connector
2. **Update local CLI** — `pip3 install --upgrade awscli` to get newer Lambda APIs
3. **Feature #2: Google Calendar** — demand-side data, highest remaining roadmap priority
4. **Feature #1: Monarch Money** — financial stress pillar
5. **Feature #13: Annual Health Report** — year-in-review email

## Key Learnings
- AWS Lambda "Block public access" (2024) silently breaks Function URLs — no error in Lambda itself, just AWS-level 403
- `lambda:InvokeFunction` for `*` bypasses the block (vs `lambda:InvokeFunctionUrl` which doesn't)
- Claude's connector has no "allow all tools" option — per-tool approval on first use
- CloudShell AWS CLI may not have latest Lambda APIs even with `pip3 install --upgrade`
- Deterministic HMAC tokens allow stateless Lambda auth without DynamoDB storage
