# Session Handover — 2026-03-01 — Feature #15: MCP API Key Rotation (v2.54.0)

## What Was Done

### MCP API Key 90-Day Auto-Rotation
Deployed automated key rotation for the MCP server's API key, closing Feature #15 from the roadmap.

**Rotator Lambda (`life-platform-key-rotator`):**
- Python 3.12, 128 MB, 30s timeout
- IAM role: `lambda-key-rotator-role` (scoped to `life-platform/mcp-api-key-*`)
- Standard Secrets Manager 4-step rotation protocol
- Generates URL-safe base64 keys (44 chars from 32 cryptographic random bytes)

**Rotation Configuration:**
- Secret `life-platform/mcp-api-key` — 90-day auto-rotation enabled
- Secrets Manager permission to invoke rotator Lambda
- First rotation triggered immediately on deployment

**Bearer Token Cache TTL (mcp/handler.py):**
- `_BEARER_TOKEN_CACHE` now expires after 5 minutes (was: never)
- Warm Lambda containers pick up new key within 5 min of rotation
- No MCP Lambda redeployment needed after key rotation
- Added `import time` to handler.py

**Helper Scripts:**
- `deploy/sync_bridge_key.sh` — pulls new key from Secrets Manager → updates `.config.json`
- `deploy/deploy_key_rotation.sh` — full 6-phase deployment script

## Current State

- **Version:** v2.54.0
- **99 MCP tools, 24 Lambdas, 19 data sources**
- **3 web properties:** dash/blog/buddy.averagejoematt.com
- Rotation verified: `RotationEnabled: true, AutomaticallyAfterDays: 90`

## Files Created/Modified

| File | Action |
|------|--------|
| `lambdas/key_rotator_lambda.py` | Created — rotator Lambda source |
| `deploy/deploy_key_rotation.sh` | Created — 6-phase deployment script |
| `deploy/sync_bridge_key.sh` | Created — post-rotation bridge key sync |
| `mcp/handler.py` | Modified — Bearer cache TTL (5 min) + `import time` |
| `docs/CHANGELOG.md` | Updated — v2.54.0 entry |
| `docs/PROJECT_PLAN.md` | Updated — version bump, Feature #15 struck, Lambda count 23→24 |

## Pending / Next Steps

1. **Verify bridge key still works** — The deploy triggered an immediate rotation. If `.config.json` was updated via `sync_bridge_key.sh`, Claude Desktop bridge should work. If not, run it.
2. **Chronicle v1.1 deploy** — `deploy/deploy_chronicle_v1.1.sh` still pending
3. **Prologue fix** — `deploy/fix_prologue.sh` still pending
4. **Nutrition Review feedback** — Matthew still has feedback pending
5. **Verify buddy data.json auto-generates** — Check after tomorrow's 10 AM Daily Brief

## Key Config

| Resource | Value |
|----------|-------|
| Rotator Lambda | `life-platform-key-rotator` |
| Rotator Role | `lambda-key-rotator-role` |
| Secret | `life-platform/mcp-api-key` (us-west-2) |
| Rotation | 90 days, automatic |
| Bearer cache TTL | 300s (5 min) |
| Manual rotation | `aws secretsmanager rotate-secret --secret-id life-platform/mcp-api-key --region us-west-2` |
| Bridge key sync | `./deploy/sync_bridge_key.sh` |
