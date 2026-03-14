# Life Platform Handover — v3.7.9
**Date:** 2026-03-13
**Session type:** TB7-25/26/27 — Rollback + WAF + tool tiering design

---

## What Was Done

### TB7-25: CI/CD Rollback Mechanism

**`deploy/deploy_lambda.sh`** — Added S3 artifact management step (Step 2.5):
- Before each deploy: copies `deploys/{func}/latest.zip` → `previous.zip` on S3
- After building the zip: uploads to `s3://matthew-life-platform/deploys/{func}/latest.zip`
- Works for all 40 Lambdas in lambda_map.json
- Zero-cost if bucket already exists; ~$0 S3 storage for 40 small zips

**`deploy/rollback_lambda.sh`** (new):
- Downloads `deploys/{func}/previous.zip` from S3
- Validates non-empty zip, shows contents before deploying
- `aws lambda update-function-code` + `wait function-updated`
- Accepts one or more function names: `bash deploy/rollback_lambda.sh daily-brief weekly-digest`
- Exits 1 if any rollback fails

**`.github/workflows/ci-cd.yml`** — Added `rollback-on-smoke-failure` job:
- Condition: `needs.smoke-test.result == 'failure' && needs.deploy.result == 'success'`
- Rolls back all functions in deploy matrix + MCP server (if deployed)
- Notes: layer rollback is MANUAL (not automated). Job renumbered to 7 for notify-failure.
- MCP Deploy step now also maintains S3 rollback artifacts for `life-platform-mcp`

**⚠️ First-deploy caveat:** Rollback requires at least TWO deploys of a function before `previous.zip` exists. On the first deploy after this change, `rollback_lambda.sh` will print "No previous artifact found" and exit 1. Expected.

### TB7-26: WAF on MCP Function URL

**`cdk/stacks/mcp_stack.py`** updated:
- `wafv2.CfnWebACL` — `life-platform-mcp-rate-limit` (REGIONAL scope, us-west-2)
- Rate rule: 1000 requests per 5-minute window per source IP → HTTP 429 on block
- `wafv2.CfnWebACLAssociation` targeting `arn:aws:lambda:us-west-2:205930651321:function:life-platform-mcp`
- New CloudWatch alarm: `mcp-waf-rate-limit-blocks` — fires if ≥10 blocks/hour → SNS
- New `CfnOutput`: `McpWafAclArn`

**Deploy required:** `cdk deploy LifePlatformMcp --require-approval never`
Run from `cdk/` after `source .venv/bin/activate`

**Cost:** ~$5/month (WAF WebACL $5/ACL + $1/rule + $0.60/million requests)

**Note:** Lambda Function URL WAF associations were added in 2023 and use the Lambda function ARN (not the URL string) as the `resource_arn`. If CDK deployment fails on the association, verify the WAF service-linked role exists in the account: `aws iam get-role --role-name AWSServiceRoleForWAFV2Logging`.

### TB7-27: MCP Tool Tiering Design

**`docs/MCP_TOOL_TIERING_DESIGN.md`** (new):
- 4-tier taxonomy: T1 Core (~25), T2 Domain (~40), T3 Specialty (~35), T4 Candidates (~44)
- 5-axis scoring criteria (frequency, unique capability, response utility, write side effect, platform dependency)
- Preliminary tier assignments for all 144 tools
- Option A implementation: `"tier": N` field in TOOLS dict, handler filters by `MCP_TIER_THRESHOLD` env var
- SIMP-1 instrumentation: CloudWatch EMF metric `LifePlatform/MCP / ToolInvocation / ToolName`
- Decision rules for SIMP-1: T4 with 0 invocations in 6 weeks → remove; T4 ≥10 invocations → promote to T3
- SIMP-1 session plan (~2026-04-08, ~4 hours)

---

## SNS Billing Confirmation

⚠️ **Still pending your action:** Check `awsdev@mattsusername.com` for SNS subscription confirmation (from TB7-15). The `life-platform-alerts` alarm won't notify until confirmed.

---

## Open Items / Next Up

1. **Deploy TB7-26 WAF** — run `cdk deploy LifePlatformMcp` + smoke test
2. **Google Calendar integration** — TB7-18, Board rank #2, ~6–8h. Next major feature.
3. **TB7-24** — Lambda handler integration tests (larger effort)
4. **SIMP-1 instrumentation** — Add CloudWatch EMF ToolInvocation metric to MCP handler now (so 6-week data window starts)
5. **TB7-28/29** — SIMP-1 + Architecture Review #8 (~2026-04-08)
6. **S3 lifecycle rule** — expire `deploys/*/` zips after 30 days to prevent accumulation (~$0 cost impact)
7. **Brittany weekly email** — still needs real email address

---

## Key Architecture Notes
- Platform: v3.7.9, 42 Lambdas, 19 data sources, 8 CDK stacks
- Shared layer: v9 (life-platform-shared-utils)
- Rollback: S3-backed (matthew-life-platform/deploys/{func}/latest.zip + previous.zip)
- WAF: CDK-managed, deploy pending
- MCP_TOOL_TIERING_DESIGN.md: T4 = ~44 candidates, SIMP-1 finalization ~2026-04-08
- Post-deploy rule: run `bash deploy/post_cdk_reconcile_smoke.sh` after every `cdk deploy`
