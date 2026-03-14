# Life Platform Handover — v3.7.9
**Date:** 2026-03-13
**Session type:** TB7-25/26/27 — Rollback + WAF (N/A) + tool tiering design

---

## What Was Done

### TB7-25: CI/CD Rollback Mechanism ✅

**`deploy/deploy_lambda.sh`** — Added S3 artifact management (Step 2.5):
- Before each deploy: copies `deploys/{func}/latest.zip` → `previous.zip`
- After build: uploads new zip to `deploys/{func}/latest.zip`
- Works for all 40 Lambdas + MCP server

**`deploy/rollback_lambda.sh`** (new):
- Downloads `previous.zip` from S3, validates, redeploys, waits for active
- `bash deploy/rollback_lambda.sh daily-brief` or multiple names at once
- ⚠️ Requires at least 2 prior deploys before `previous.zip` exists

**`.github/workflows/ci-cd.yml`** — `rollback-on-smoke-failure` job (Job 6):
- Condition: smoke-test fails AND deploy succeeded
- Rolls back all matrix functions + MCP if deployed
- Layer rollback remains manual

### TB7-26: WAF on MCP Function URL — N/A ✅

**Finding:** `aws wafv2 associate-web-acl` does not support Lambda Function URLs.
Supported resource types: ALB, API Gateway, AppSync, Cognito, App Runner,
Verified Access. Both `CfnWebACLAssociation` (CDK) and CLI `associate-web-acl`
returned `WAFInvalidParameterException`.

**Rationale for N/A close:** MCP Function URL requires valid HMAC Bearer token.
Unauthenticated requests fail immediately at the handler. Account-level concurrency
(10 reserved) acts as a natural rate brake. `slo-mcp-availability` alarm (≥3
errors/hour → SNS) covers runaway behavior. No meaningful unmitigated attack surface.

**Stack state:** `mcp_stack.py` reverted to pre-WAF baseline. LifePlatformMcp
deployed clean, smoke 10/10. No orphaned WAF resources (CloudFormation rollback
cleaned them up automatically).

### TB7-27: MCP Tool Tiering Design ✅

**`docs/MCP_TOOL_TIERING_DESIGN.md`** (new, ~300 lines):
- T1 Core (~25): always active, backbone tools
- T2 Domain (~40): always active, domain-specific
- T3 Specialty (~35): always active, narrow deep-dive
- T4 Candidates (~44): SIMP-1 removal targets
- Option A: `"tier": N` in TOOLS dict, handler filters by `MCP_TIER_THRESHOLD` env var
- SIMP-1 instrumentation: CloudWatch EMF `LifePlatform/MCP / ToolInvocation`
- Decision rules: T4 with 0 invocations in 6 weeks → remove; ≥10 → promote T3
- SIMP-1 session plan: ~2026-04-08, ~4 hours

---

## SNS Billing Confirmation

⚠️ **Still pending:** Check `awsdev@mattsusername.com` for SNS subscription
confirmation from TB7-15. Alarms are silent until confirmed.

---

## Open Items / Next Up

1. **Google Calendar integration** — TB7-18, Board rank #2, ~6–8h. Next major feature.
2. **SIMP-1 instrumentation** — Add CloudWatch EMF ToolInvocation metric to MCP
   handler now to start the 6-week data window before SIMP-1 (~2026-04-08).
3. **S3 lifecycle rule** — expire `deploys/*/` zips after 30 days.
4. **TB7-24** — Lambda handler integration tests (larger effort, future session).
5. **TB7-28/29** — SIMP-1 + Architecture Review #8 (~2026-04-08).
6. **Brittany weekly email** — needs real email address.

---

## Key Architecture Notes
- Platform: v3.7.9, 42 Lambdas, 19 data sources, 8 CDK stacks
- Shared layer: v9
- Rollback: S3-backed (`matthew-life-platform/deploys/{func}/latest.zip` + `previous.zip`)
- WAF: N/A for Lambda Function URLs — documented and closed
- MCP tool tiering: T4 = ~44 candidates, data collection window starts now
- All alarms: OK | DLQ: clear | Smoke: 10/10
- Post-deploy rule: `bash deploy/post_cdk_reconcile_smoke.sh` after every `cdk deploy`
