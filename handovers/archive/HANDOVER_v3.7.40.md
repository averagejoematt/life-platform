# Life Platform Handover — v3.7.40
**Date:** 2026-03-15
**Session type:** R13 roadmap execution — R13-F14 + R13-XR

## Platform Status
- **Version:** v3.7.40
- **MCP tools:** 89
- **Lambdas:** 43 (CDK) + 1 Lambda@Edge
- **CloudWatch alarms:** 53 (+2 MCP canary alarms this session)

## What Was Done This Session

### R13-F14 ✅ — MCP endpoint canary (15-min probe)
Three bugs in canary_lambda.py fixed (all caused by R13-F05 fail-closed auth change):
1. `MCP_SECRET` default was `ai-keys` → changed to `mcp-api-key`
2. Auth was `x-api-key` header → now HMAC-derived Bearer token via `derive_mcp_bearer_token()`
3. Tool count threshold was `< 100` → changed to `< 50` (we have 89; SIMP-1 headroom)

New `mcp_only` event flag: 15-min rule passes `{"mcp_only": true}` so it only runs the MCP check without the DDB/S3 round-trips (those still run on the 4-hourly full canary).

`deploy/create_mcp_canary_15min.sh` created and run:
- EventBridge rule `life-platform-mcp-canary-15min` (rate 15 min)
- Alarm `life-platform-mcp-canary-failure-15min` (any MCP fail → SNS)
- Alarm `life-platform-mcp-canary-latency-15min` (p95 >10s × 2 windows → SNS)

### R13-XR ✅ — X-Ray tracing on MCP Lambda
- `cdk/stacks/lambda_helpers.py`: `tracing` parameter added to `create_platform_lambda()`
- `cdk/stacks/mcp_stack.py`: `tracing=_lambda.Tracing.ACTIVE` on MCP server Lambda
- `cdk/stacks/role_policies.py`: XRay IAM statement added to `mcp_server()` policy
- CDK deployed `LifePlatformMcp` — MCP Lambda now emits X-Ray traces on every invocation
- Per-DDB-query latency now visible in X-Ray service map (no log parsing required)

## All R13 Findings Status

| Finding | Status |
|---------|--------|
| F01 CI/CD pipeline | ✅ (already existed) |
| F02 Integration tests | ✅ I12 + I13 |
| F03 MCP monolith split | N/A (not needed yet) |
| F04 CI secret linter | ✅ |
| F05 OAuth fail-closed | ✅ |
| F06 Correlation n-gate | ✅ |
| F07 PITR drill | ⏳ First drill due ~Apr 2026 |
| F08 Layer CI pytest | ✅ LV1-LV5 |
| F08-dur Duration alarms | ✅ |
| F09 Medical disclaimers | ✅ All 6 tools |
| F10 d2f consolidation | ✅ (annotated; defer to layer v12) |
| F11 DST timing | Documented, not mitigated |
| F12 Write rate limiting | ✅ |
| F14 MCP canary 15min | ✅ |
| F15 BH FDR correction | ✅ |
| XR X-Ray tracing | ✅ |

**R13 grade: A** (all actionable items done; F07 pending first drill; F11 low-impact)

## Remaining Work

| ID | Item | Effort | Notes |
|----|------|--------|-------|
| CLEANUP-3 | Google Calendar OAuth | S (20min) | `python3 setup/setup_google_calendar_auth.py` |
| R13-F07 | PITR restore drill | S (1h) | First drill due ~Apr 2026 |
| R8-LT1 / AR #14 | Architecture Review #14 | L | ~May 2026, after 30-day R13 window |
| SIMP-1 Phase 2 | MCP tool cuts to ≤80 | L | Data-gated Apr 13 |
| IC-4/IC-5 | Failure pattern + momentum | L | Data-gated ~May 2026 |

## Next Session
1. CLEANUP-3: `python3 setup/setup_google_calendar_auth.py` (20min, unlocks 20th data source)
2. R13-F07: PITR drill (1h, due Apr 2026 but may as well do it now)
3. Review SIMP-1 Phase 2 readiness (~Apr 13 data gate approaching)
