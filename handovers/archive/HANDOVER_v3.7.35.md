# Life Platform Handover — v3.7.35
**Date:** 2026-03-15
**Session type:** Roadmap execution — TB7-4 deadline + R13 security hardening

## Platform Status
- **Version:** v3.7.35
- **MCP tools:** 89
- **Lambdas:** 43 (CDK) + 1 Lambda@Edge

## What Was Done This Session

### TB7-4 ✅ CLOSED (was DEADLINE 2026-03-17)
- Grep sweep confirmed: all `life-platform/api-keys` references were in `cdk/cdk.out/` (stale build artifacts), zero in live `lambdas/` or `mcp/` source
- Secret permanently deleted: `aws secretsmanager delete-secret --force-delete-without-recovery`
- ARN: `arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/api-keys-t2ADCR`

### R13-F05 ✅ MCP OAuth fail-closed
- `mcp/handler.py`: `_get_bearer_token()` now returns sentinel `"__NO_KEY_CONFIGURED__"` (not `None`) when no API key is set
- `_validate_bearer()`: removed `if expected is None: return True` accept-all bypass
- Was: no API key → accept all tokens. Now: no API key → reject all tokens

### R13-F12 ✅ Write tool rate limiting
- `mcp/handler.py`: `_check_write_rate_limit()` — 10 calls/invocation on 5 write tools
- `mcp/utils.py`: `RATE_LIMIT` error code + default suggestions

### R13-F09 ⚠️ Partial — medical disclaimers
- `mcp/tools_health.py`: `_disclaimer` via `tool_get_health()` dispatcher + `tool_get_readiness_score()` directly
- `mcp/tools_cgm.py`: `_disclaimer` via `tool_get_cgm()` dispatcher
- **Carry:** BP dashboard + HR recovery tools — not found in local `mcp/` source. Search showed they may be in `tools_lifestyle.py` or another module not yet located. Need a broader grep in next session to find and patch.

### R13-F04 ✅ CI secret reference linter
- `tests/test_secret_references.py` (new, SR1–SR4): scans `lambdas/`, `mcp/`, `mcp_server.py`
- Wired into `.github/workflows/ci-cd.yml` test job after IAM/secrets linter
- All 4 tests passing ✅

### Deployed
- `life-platform-mcp` ✅

## Remaining Roadmap Items (prioritised)

### Tier 1 — Still pending
| ID | Item | Effort | Notes |
|----|------|--------|-------|
| R13-F09 (tail) | BP + HR recovery tool disclaimers | XS | Find tools first: grep `tools_lifestyle.py` + others |
| R13-F08-dur | Duration alarms on Daily Brief + MCP | S (1h) | CloudWatch metric alarms |
| R13-F06 | n-gate on correlation tool + p-value | S (2h) | Tool name unclear — grep registry for "correlation" |

### Tier 2 — Near-term
| ID | Item | Effort |
|----|------|--------|
| R13-F01 | GitHub Actions CI pipeline audit/gaps | M (2–4h) |
| R13-F02 | Integration tests for critical path | M (5h) |
| R13-F15 | Bonferroni/FDR in weekly correlation compute | S (2h) |
| R13-F08 | CI layer version consistency pytest | S (1h) |
| R13-F10 | Consolidate `d2f()` into shared layer | S (30min) |
| CLEANUP-3 | Google Calendar OAuth activation | S (20min) |

### Tier 3 / Strategic
| ID | Item |
|----|------|
| R13-F14 | MCP endpoint canary (Function URL synthetic probe) |
| R13-XR | X-Ray tracing on MCP Lambda |

### Data-gated (≥ Apr 13)
SIMP-1 Phase 2, COST-2, IC-4/IC-5

## Next Session Recommended Start
1. Find BP/HR recovery tools: `grep -r "blood_pressure\|hr_recovery\|heart_rate_recovery" lambdas/ mcp/ --include="*.py" -l`
2. Patch disclaimers → close R13-F09
3. R13-F08-dur (duration alarms)
4. R13-F06 (correlation n-gate)
