# Life Platform Handover — v3.7.10
**Date:** 2026-03-13
**Session type:** Housekeeping + incident response (SIMP-1 instrumentation, S3 lifecycle, Brittany email, alarm storm RCA)

---

## What Was Done

### SIMP-1 Instrumentation — Already Live ✅ (no work needed)
Confirmed `_emit_tool_metric()` already fully wired in `mcp/handler.py` — emits
`ToolInvocations`, `ToolDuration`, `ToolErrors` to `LifePlatform/MCP` via EMF.
6-week data window for SIMP-1 has been accumulating since v3.7.9 (today).

### S3 Lifecycle Rule — `deploy/apply_s3_lifecycle.sh` ✅
New script expires objects under `deploys/` prefix after 30 days.
**Not yet run** — Matthew needs to execute:
```bash
bash deploy/apply_s3_lifecycle.sh
```

### Brittany Weekly Email — Already Correct ✅
`email_stack.py` already had `brittany@mattsusername.com` as `BRITTANY_EMAIL`.
No CDK change needed.

**SES status:** Account is in **Sandbox mode**. Brittany's address must be verified
before she'll receive emails. Matthew needs to run:
```bash
aws sesv2 create-email-identity \
  --email-identity brittany@mattsusername.com \
  --region us-west-2
```
She'll receive a verification link — clicks once, permanent.

### Incident: Mar 12 Alarm Storm — RESOLVED ✅

**Root cause:** CDK drift on `LifePlatformIngestion-TodoistIngestionRole` —
missing `s3:PutObject` permission for `raw/todoist/*`. Policy existed in
`role_policies.py` but had not been applied to AWS (likely stale from COST-B
bundling refactor).

**Fix:** `npx cdk deploy LifePlatformIngestion` — synced role policies to AWS.
Post-deploy smoke: `todoist-data-ingestion` invoked successfully, `statusCode: 200`.

**Cascade that caused all the alarm emails:**
1. Todoist Lambda: `AccessDenied` on `s3:PutObject` → no S3 write → no DDB write
2. Freshness checker detected stale Todoist data → `slo-source-freshness` ALARM
3. `freshness-checker-errors` alarm fired (CW alarm on Lambda errors — the checker itself also alarmed)
4. Missing Todoist data → `daily-insight-compute` failed → ALARM
5. Missing Todoist data → `failure-pattern-compute` failed → ALARM
6. Missing Todoist data → `monday-compass` failed → ALARM
7. Failed invocations → DLQ → `life-platform-dlq-depth-warning` ALARM
8. All resolved via OK notifications once CDK deploy fixed the IAM role

DLQ depth at time of investigation: **0** (already drained via retries/expiry).

**Bug fix (separate):** `lambdas/freshness_checker_lambda.py` — duplicate
sick-day suppression block removed (copy-paste bug — second block was silently
resetting `_sick_suppress = False`, breaking suppression logic).
Needs deploy:
```bash
bash deploy/deploy_lambda.sh freshness-checker lambdas/freshness_checker_lambda.py
```

---

## SNS Billing Confirmation (still pending)
⚠️ Check `awsdev@mattsusername.com` for SNS subscription confirmation from TB7-15.
Alarms are silent until confirmed. Has been pending since v3.7.3.

---

## Outstanding Deploy Actions (do before next session)

| Action | Command |
|--------|---------|
| S3 lifecycle rule | `bash deploy/apply_s3_lifecycle.sh` |
| Freshness checker bug fix | `bash deploy/deploy_lambda.sh freshness-checker lambdas/freshness_checker_lambda.py` |
| Brittany SES verification | `aws sesv2 create-email-identity --email-identity brittany@mattsusername.com --region us-west-2` |

---

## Open Items / Next Up

1. **Google Calendar integration** — TB7-18, Board rank #2, ~6–8h. Next major feature.
2. **S3 lifecycle rule** — run `bash deploy/apply_s3_lifecycle.sh`
3. **Freshness checker deploy** — bug fix ready, needs deploy
4. **Brittany SES verification** — send verification email to Brittany
5. **SNS subscription confirmation** — check `awsdev@mattsusername.com`
6. **SIMP-1** — ~2026-04-08, ~4h. 6-week data window accumulating now.
7. **TB7-24** — Lambda handler integration tests (larger effort, future session).
8. **TB7-28/29** — Architecture Review #8 + SIMP-1 (~2026-04-08).

---

## Key Architecture Notes
- Platform: v3.7.10, 42 Lambdas, 19 data sources, 8 CDK stacks
- Shared layer: v9
- Rollback: S3-backed (`matthew-life-platform/deploys/{func}/latest.zip` + `previous.zip`)
- MCP tool tiering: T4 = ~44 candidates, data collection window started 2026-03-13
- All alarms: OK | DLQ: 0 | Todoist: confirmed healthy post-fix
- Post-deploy rule: `bash deploy/post_cdk_reconcile_smoke.sh` after every `cdk deploy`
