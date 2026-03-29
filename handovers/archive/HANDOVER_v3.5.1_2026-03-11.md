# Life Platform — Handover v3.5.1
**Date:** 2026-03-11
**Version:** v3.5.1
**Previous:** v3.5.0

---

## What Was Done This Session

### ✅ Habitify secret restored
- `life-platform/habitify` was accidentally deleted during a secrets cleanup sweep (confused with the api-keys/todoist/notion/dropbox batch scheduled for deletion)
- Restored via: `aws secretsmanager restore-secret --secret-id life-platform/habitify`
- Verified: `DeletedDate: null`, `LastChangedDate: 2026-03-10T17:02:17`
- Habitify ingestion Lambda is operational again

### ✅ ADR-014 governing principle documented
- Added the dedicated-vs-bundled rule to `docs/DECISIONS.md`:
  - **Bundle only when the same credentials are consumed by the exact same set of Lambdas**
  - `life-platform/ai-keys` is the one justified bundle (all email/compute/MCP Lambdas)
  - Everything else (Habitify, Todoist, Notion, all OAuth secrets) is dedicated
  - Noted that `api-keys` bundle was an over-optimisation; migration away was correct
- Updated ADR-014 index title and current end-state (9 active secrets)

### ✅ ARCHITECTURE.md secrets section fixed
- Was stale: said "Habitify consolidated into api-keys" and listed 8 secrets
- Now correct: 9 secrets, `life-platform/habitify` listed as dedicated, ADR-014 cross-referenced
- OAuth token management paragraph updated
- Cost profile updated: Secrets Manager ~$3.60/month (was ~$2.40)

### ✅ Brittany email address confirmed + deployed
- Updated `cdk/stacks/email_stack.py`: `BRITTANY_EMAIL` placeholder → `awsdev@mattsusername.com`
- `brittany-weekly-email` Lambda verified live with correct env vars

### ✅ CDK deploy — LifePlatformCompute + LifePlatformEmail
- Both stacks deployed cleanly (43.68s total)
- All email Lambdas now have explicit `ANTHROPIC_SECRET=life-platform/ai-keys` env var
- api-keys migration debt fully resolved — Lambdas safe through ~2026-04-07 deletion

### ✅ CloudFront smoke test
- `bash deploy/smoke_test_cloudfront.sh` — 12/12 passed
- All 3 distributions: HTTPS reachable, TLS valid, CloudFront header present, HTTP→HTTPS redirect

### ✅ March 10 sick day logged
- DynamoDB record written to `USER#matthew#SOURCE#sick_days / DATE#2026-03-10`
- Effects: Character Sheet EMA frozen, day grade = sick, streaks preserved, anomaly alerts suppressed

---

## Alarm State at Session Close

12 alarms in ALARM — all expected, no new fires:
- **March 8-9 cluster** (whoop, strava, todoist, anomaly-detector, monday-compass, weekly-digest,
  enrichment, character-sheet-compute, daily-metrics-compute, slo-daily-brief-delivery,
  slo-source-freshness): pre-CDK migration turbulence — will self-clear as Lambdas run cleanly
  through 24hr evaluation windows post-deploy
- **freshness-checker-errors** (Mar 10): expected on sick day

---

## Upcoming Deadlines

| Item | When | Notes |
|------|------|-------|
| `life-platform/api-keys` deletion | ~2026-04-07 | All Lambdas already migrated. Safe to delete. |
| `life-platform/todoist/notion` deletion | ~2026-04-10 | Verify Lambdas reference dedicated secrets first |
| SIMP-1 MCP tool audit | ~2026-04-08 | Archive 0-invocation tools, rationalise pre-compute vs callable |
| Architecture Review #7 | ~2026-04-08 | Run `python3 deploy/generate_review_bundle.py` first |
| PROD-2 multi-user architecture audit | TBD | `docs/AUDIT_PROD2_MULTI_USER.md` |

---

## Next Session Priority Order
1. Monitor alarm self-clear over next 24-48hrs (no action needed — passive)
2. Optional: retroactive recompute for Mar 10 sick day if grades matter
   - `aws lambda invoke --function-name character-sheet-compute --payload '{"date":"2026-03-10"}' /tmp/out.json --region us-west-2`
   - `aws lambda invoke --function-name daily-metrics-compute --payload '{"date":"2026-03-10"}' /tmp/out.json --region us-west-2`
3. SIMP-1 MCP tool audit (~2026-04-08)
4. PROD-2 multi-user architecture audit

---

## Platform State

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Architecture | A | |
| Security | A | 13 dedicated IAM roles, secrets properly scoped + documented |
| Reliability | A- | DLQ, canary, item size guard |
| Observability | A- | OBS-1 complete for email Lambdas |
| Cost | A | ~$10/month |
| Data Quality | A | DATA-2 wired |
| AI/Analytics | B | ai_output_validator wired to all email Lambdas + anomaly_detector |
| Maintainability | A- | Layer v4, ADRs 001–023, unit tests |
| Productization | B+ | PROD-2 pending |

Next Architecture Review: ~2026-04-08
