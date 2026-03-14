# Life Platform — Changelog

## v3.7.9 — 2026-03-13: TB7-25/26/27 — Rollback + WAF + tool tiering design

### Summary
TB7-25: Alias-based CI/CD rollback implemented using S3 artifact strategy.
`deploy_lambda.sh` now maintains `latest.zip`/`previous.zip` per function in
S3. New `rollback_lambda.sh` enables one-command rollback. CI/CD gets
`rollback-on-smoke-failure` job that auto-fires when smoke test fails after
a successful deploy. TB7-26: WAF WebACL (REGIONAL, rate-limit 1000 req/5min
per IP) added to McpStack CDK with `CfnWebACLAssociation` targeting MCP Lambda
ARN. CloudWatch alarm on blocked requests. TB7-27: MCP tool tiering design doc
created — 4-tier taxonomy, criteria, preliminary assignments for all 144 tools,
SIMP-1 instrumentation requirements.

### Changes
- **TB7-25** — `deploy/deploy_lambda.sh`: adds S3 artifact management step —
  shifts `deploys/{func}/latest.zip` → `previous.zip` before each deploy,
  uploads new zip as `latest.zip`. Works for all 40 Lambdas.
- **TB7-25** — `deploy/rollback_lambda.sh` (new): downloads `previous.zip`
  from S3, redeploys, waits for active. Accepts one or more function names.
- **TB7-25** — `.github/workflows/ci-cd.yml`: added `rollback-on-smoke-failure`
  job (Job 6). Fires when `smoke-test` fails AND `deploy` succeeded. Rolls back
  all deployed Lambdas and MCP server. Notes layer rollback is manual.
  Notify-failure job renumbered to Job 7.
- **TB7-25** — `ci-cd.yml` Deploy job: MCP deploy step now also maintains
  `deploys/life-platform-mcp/latest.zip` and `previous.zip` on S3.
- **TB7-26** — `cdk/stacks/mcp_stack.py`: added WAF WebACL
  `life-platform-mcp-rate-limit` (REGIONAL, 1000 req/5min per IP, returns 429
  on block). `CfnWebACLAssociation` targets MCP Lambda function ARN.
  CloudWatch alarm `mcp-waf-rate-limit-blocks` (threshold 10 blocks/hour) → SNS.
  Cost: ~$5/month.
- **TB7-27** — `docs/MCP_TOOL_TIERING_DESIGN.md` (new): 4-tier taxonomy,
  tiering criteria, preliminary assignments for all 144 tools, Option A
  implementation (tier field in TOOLS dict), SIMP-1 data collection plan,
  6-week instrumentation requirements, SIMP-1 session plan.

### Files Changed
- `deploy/deploy_lambda.sh` (S3 artifact management)
- `deploy/rollback_lambda.sh` (new)
- `.github/workflows/ci-cd.yml` (rollback job + MCP S3 artifact)
- `cdk/stacks/mcp_stack.py` (WAF WebACL + alarm)
- `docs/MCP_TOOL_TIERING_DESIGN.md` (new)
- `docs/CHANGELOG.md` (this file)
- `handovers/HANDOVER_v3.7.9.md` (new)

### Deploy required
- `bash deploy/rollback_lambda.sh` — no deploy, script is local only
- `cdk deploy LifePlatformMcp` — deploys WAF WebACL + association + new alarm
  Run from `cdk/`: `source .venv/bin/activate && npx cdk deploy LifePlatformMcp --require-approval never`
- `bash deploy/post_cdk_reconcile_smoke.sh` after CDK deploy

### AWS cost delta
- WAF: ~$5/month (1 WebACL + 1 rule + request processing)
- S3: ~$0 (rollback zips are small; lifecycle rule recommended: expire after 30 days)

---

## v3.7.8 — 2026-03-13: TB7 fully closed + DLQ cleared + smoke test fix

### Summary
TB7-11/12/13 confirmed already done. TB7-14 and TB7-16 completed (SCHEMA TTL
documentation + fingerprint comment). DLQ investigated and cleared (5 stale
Habitify retry messages from pre-layer-v9 deploy). Smoke test fixed
(--cli-binary-format regression + handler regressions for key-rotator and
insight-email-parser). All TB7 items now closed.

### Changes
- **TB7-14 CLOSED** — `SCHEMA.md` TTL section replaced with full per-partition
  table: DDB TTL vs app-level expiry vs indefinite, with rationale for each.
  Documents hypotheses (30d app-level), platform_memory (~90d policy),
  insights (~180d policy), decisions/anomalies/ingestion (indefinite).
- **TB7-16 CLOSED** — Comment added to `get_source_fingerprints()` in
  `daily_metrics_compute_lambda.py` warning that new data sources must be
  added to the fingerprint list to trigger recomputes.
- **TB7-11/12/13 CLOSED** — Confirmed already implemented: layer version
  consistency CI check, stateful resource assertions, and digest_utils.py in
  shared_layer.modules all present in existing `ci-cd.yml` and `lambda_map.json`.
- **DLQ CLEARED** — 5 stale Habitify retry messages from 2026-03-13 14:15 UTC
  (pre-layer-v9 deploy). All identical EventBridge events. Purged + alarm reset
  to OK. Habitify confirmed healthy.
- **SMOKE TEST FIXED** — Removed `--cli-binary-format raw-in-base64-out` from
  `post_cdk_reconcile_smoke.sh` (AWS CLI v2 regression). Fixed dry_run payload
  for todoist invocation check.
- **HANDLER FIXES** — `life-platform-key-rotator` and `insight-email-parser`
  restored to correct handlers (CDK reconcile regression).

### Files Changed
- `lambdas/daily_metrics_compute_lambda.py` (TB7-16 fingerprint comment)
- `docs/SCHEMA.md` (TB7-14 TTL per-partition table)
- `docs/PROJECT_PLAN.md` (TB7-11–17 all marked complete)
- `deploy/post_cdk_reconcile_smoke.sh` (CLI flag fix + dry_run fix)

---

## v3.7.7 — 2026-03-13: TB7-19/20/21/22/23 — AI validator + anomaly + drift hardening
