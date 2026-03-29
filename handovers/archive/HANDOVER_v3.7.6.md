# Life Platform Handover — v3.7.6
**Date:** 2026-03-13
**Session type:** TB7 sprint completion + bug fixes

---

## What Was Done

Completed all 5 outstanding TB7 hardening items. Also discovered and fixed an MCP KMS
permission regression that was silently blocking all MCP write operations.
Sick days logged for 2026-03-12 and 2026-03-13.

---

## Items Completed

### TB7-4 — api-keys deletion ✅
Grep sweep of `lambdas/ mcp/ deploy/` confirmed zero live code references to
`life-platform/api-keys`. All hits were archived scripts or comment text.
Permanently deleted: `aws secretsmanager delete-secret --force-delete-without-recovery`.
Completed 4 days ahead of the 2026-03-17 deadline.

### TB7-1 — GitHub production environment ✅
Confirmed `production` environment exists in repo Settings → Environments with
1 protection rule active.

### TB7-2 — Brittany weekly email ✅
Two missing env vars identified: `EMAIL_SENDER` (required, no default) and
`BRITTANY_EMAIL` (was placeholder `awsdev@mattsusername.com`).
- Updated live Lambda with both vars
- Updated CDK source: `email_stack.py` `_brittany_env`
- Smoke test: HTTP 200, "Brittany email v1.1.0 sent: Matthew's Week · 2026-03-13"
Next scheduled run: Sunday 2026-03-15 at 09:30 PT (17:30 UTC).

### TB7-15 — AI cost billing alarm ✅
Fixed `create_ai_cost_alarm.sh`: billing CloudWatch alarms require SNS topic in
us-east-1 (cross-region not supported — original script used us-west-2 topic).
Created `life-platform-billing-alerts` SNS topic in us-east-1, subscribed
`awsdev@mattsusername.com` (pending email confirmation), created
`life-platform-ai-cost-soft-alarm` at $5 threshold.

### TB7-17 — DLQ alarm period verification ✅
Fixed `verify_dlq_alarm_periods.sh`: two bugs (JMESPath `lower()` not supported,
heredoc Python couldn't read shell variable). DLQ alarm period = 300s (5 min) ✅.
Note: DLQ alarm is currently in ALARM state — may have messages to investigate.

---

## Bug Fixed — MCP KMS Permission Regression

All MCP tool writes were failing with `AccessDeniedException: kms:Decrypt`.
Root cause: MCP Lambda role had lost the KMS inline policy (stale role state,
likely from a previous CDK deploy). CDK `role_policies.mcp_server()` already
has KMS correctly defined — this was a live/CDK drift issue, not a CDK bug.
Fix: applied `McpKmsDecrypt` inline policy directly to the MCP role.
Will self-heal on next `cdk deploy McpStack`.

---

## Pending / Carry Forward

1. **DLQ in ALARM** — `life-platform-dlq-depth-warning` is in ALARM state. Check for
   queued messages: `aws sqs get-queue-attributes --queue-url <dlq-url> --attribute-names All`

2. **Billing SNS confirmation** — Check `awsdev@mattsusername.com` for SNS subscription
   confirmation email and click the link. Alarm won't notify until confirmed.

3. **Google Calendar integration** — Next major feature (~6-8h).

4. **TB7-19 through TB7-23** — AI output validator, insights context filter, anomaly
   detector threshold correction, IC-19 window equalization, IC-3 model upgrade.
   Still pending from earlier sessions.

5. **MCP KMS** — Will self-heal on next `cdk deploy McpStack`. No urgency.

---

## Key Architecture Notes
- Platform: v3.7.6, 42 Lambdas, 19 data sources, 8 CDK stacks
- `life-platform/api-keys` secret: DELETED (2026-03-13)
- Billing alarm: `life-platform-ai-cost-soft-alarm` in us-east-1
- Brittany email: `brittany@mattsusername.com`, sender `awsdev@mattsusername.com`
- Post-deploy rule: run `bash deploy/post_cdk_reconcile_smoke.sh` after every `cdk deploy`
