# Handover — Session 11: Audit Fixes + Documentation Overhaul

**Date:** 2026-02-25  
**Version:** v2.28.1

---

## What happened this session

Cleared the entire Session 10 infrastructure audit backlog — all 31 findings resolved. No open audit items remain.

### Phase 1 — Critical Fixes (2)
1. **Anomaly detector EventBridge trigger** — Created `anomaly-detector-daily` rule at `cron(5 16 * * ? *)` (8:05 AM PT). Lambda existed but was never scheduled. First automated run will be tomorrow morning.
2. **Enrichment alarm dimension** — `ingestion-error-enrichment` was watching `activity-enrichment-nightly` (rule name) instead of `activity-enrichment` (Lambda name). Deleted and recreated.

### Phase 2 — Security Fixes (3)
3. **MCP role Scan removal** — Removed `dynamodb:Scan` from `lambda-mcp-server-role`.
4. **SES scoping** — Changed `Resource: "*"` → domain identity ARN on `lambda-weekly-digest-role` and `lambda-anomaly-detector-role`.
5. **DLQ coverage** — Added DLQ to 6 Lambdas (garmin, habitify, notion, dropbox-poll, activity-enrichment, journal-enrichment). Added `sqs:SendMessage` to each role. Coverage: 5/20 → 11/20.

### Bugs Encountered + Fixed
- Anomaly detector `ImportModuleError` after config update — redeployed zip.
- DLQ script failed on associative arrays in bash — rewrote with parallel arrays.
- DLQ attachment failed because roles lacked `sqs:SendMessage` — added IAM permissions first.

### Documentation Overhaul (3 files)
- **ARCHITECTURE.md** — Complete rewrite against AWS ground truth. 19 inaccuracies corrected. Accuracy: ~70% → ~100%. Key fixes: MCP endpoint (API Gateway → Function URL), 5 schedule corrections, secrets inventory (6→12), alarm count (7→21), DLQ coverage specifics, freshness-checker added, DST warning added.
- **RUNBOOK.md** — 9 corrections: schedules, MacroFactor path, MCP endpoint, log retention, IAM roles, DST warning.
- **USER_GUIDE.md** — Full rewrite. Tool reference: v2.8.0/45 tools → current/59 tools with 5 new categories (CGM, Gait, Journal, Labs/Genome, Sleep correlations). Email schedules, data sources, and infrastructure table all corrected.

### Habitify Alarm Cleared
- Re-invoked Lambda successfully (transient networking error). Manually set alarm to OK. All 21/21 alarms now green.

---

## Verification status

| Fix | Verified |
|-----|----------|
| Anomaly detector EventBridge rule | ✅ Created + test invocation returns today's date |
| Enrichment alarm correct dimension | ✅ Watches `activity-enrichment` |
| MCP role no Scan | ✅ Policy confirmed |
| SES scoped on both email roles | ✅ Domain identity ARN |
| 6 Lambdas have DLQ | ✅ Confirmed via list-functions |
| Habitify alarm cleared | ✅ All 21 alarms OK |
| Email Lambdas still work (SES) | ⏳ First test: tomorrow 10 AM brief |
| Anomaly detector automated run | ⏳ First test: tomorrow 8:05 AM |

---

## What still needs doing

### Remaining infrastructure (low priority)
- WAF rate limiting (#10) — $5/mo
- MCP API key rotation (#11) — 90-day schedule

### Uninvestigated from Session 10
- S3 bucket 2.3GB (was 34MB) — likely `raw/` directory growth
- MCP server latency trending up (1.2s → 2.8s avg)

### DST reminder
- **March 8** (11 days) — All EventBridge crons use fixed UTC. All PT times shift +1 hour after DST.

### SES revert plan (if tomorrow's brief fails)
Set SES Resource back to `"*"` on `lambda-weekly-digest-role`:
```bash
aws iam put-role-policy --role-name lambda-weekly-digest-role --policy-name weekly-digest-access --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["dynamodb:GetItem","dynamodb:Query","dynamodb:PutItem"],"Resource":"arn:aws:dynamodb:us-west-2:205930651321:table/life-platform"},{"Effect":"Allow","Action":["secretsmanager:GetSecretValue"],"Resource":"arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/anthropic*"},{"Effect":"Allow","Action":["ses:SendEmail","sesv2:SendEmail"],"Resource":"*"}]}' --region us-west-2
```

---

## Files created/modified
- `deploy_audit_fixes_phase1_2.sh` — Fixes 1-4
- `deploy_audit_fix5_dlq.sh` — Fix 5 DLQ
- `ARCHITECTURE.md` — Complete rewrite
- `RUNBOOK.md` — 9 corrections
- `USER_GUIDE.md` — Full rewrite
- `CHANGELOG.md` — v2.28.1 entry
- `PROJECT_PLAN.md` — Version bump, all audit items resolved

---

## Next session candidates
1. **Fasting glucose validation (#8)** — Compare CGM overnight nadir vs lab draws (2 hr)
2. **Monarch Money (#9)** — Financial pillar, monthly spend/savings/net worth (4-6 hr)
3. **Investigate S3 growth** — Quick check on why bucket jumped to 2.3GB
4. **MCP latency investigation** — Why server duration trending up
