# Life Platform — Cost Tracker

Last updated: 2026-03-14 (v3.7.21)

> Budget target: **$25/month**. Design constraint: every feature must justify its cost.

---

## Current Monthly Cost Breakdown (Estimated)

| Service | Cost/Month | Notes |
|---------|-----------|-------|
| **Secrets Manager** | $4.00 | 10 active secrets × $0.40/secret/month. `api-keys` permanently deleted 2026-03-14. |
| **Lambda** | ~$0.50 | ~2,500 invocations/month (13 ingestion + 35 Lambda schedule runs + MCP on-demand + Dropbox poll) |
| **DynamoDB** | ~$0.30 | On-demand pay-per-request, ~5,000 WCU + ~15,000 RCU/month |
| **S3** | ~$0.05 | ~2.5 GB stored (raw archives + dashboard + blog + buddy + avatar), minimal GET/PUT |
| **CloudWatch** | ~$3.20 | 42 alarms (40 CDK-managed + 2 intentional orphans: health-auto-export-no-invocations-24h, life-platform-recursive-loop). Down from 90 before COST-A. |
| **SES** | ~$0.01 | ~55 emails/month (daily brief + weekly + monthly + anomaly + freshness + nutrition review + chronicle + weekly plate + monday compass) |
| **API Gateway** | ~$0.01 | ~180 webhook invocations/month (Health Auto Export, ~4h × 30 days) |
| **SNS** | $0.00 | Free tier (alert topic, low volume) |
| **CloudTrail** | $0.00 | Management events free; S3 storage negligible |
| **Budgets** | $0.00 | First 2 budgets free |
| **PITR (DynamoDB)** | ~$0.10 | 35-day continuous backup on single table |
| **CloudFront** | ~$0.01 | CDN for `dash.averagejoematt.com`, `blog.averagejoematt.com`, `buddy.averagejoematt.com` (free tier) |
| **Route 53** | ~$0.50 | 1 hosted zone — flat monthly fee |
| **Total** | **~$10/month** | Well under $25 target. CloudWatch is the dominant variable — drops from ~$7.70 to ~$3.10 after COST-A alarm cleanup. |

---

## Budget Guardrails

| Mechanism | Threshold | Action |
|-----------|-----------|--------|
| AWS Budget alert | $5 (25%) | Email notification |
| AWS Budget alert | $10 (50%) | Email notification |
| AWS Budget alert | $20 (100%) | Email notification |
| Hard mental limit | $25/month | Feature must be deferred or redesigned |

Budget email: `awsdev@mattsusername.com`

---

## Cost Decisions Log

Decisions where cost was a factor in the design:

| Date | Decision | Cost Impact | Outcome |
|------|----------|-------------|---------|
| 2026-02-28 | Reserved concurrency (10) on MCP Lambda instead of WAF | Saved $5/month | 80% of WAF protection for $0 (expert review recommendation) |
| 2026-02-28 | CloudFront for web dashboard | +$0.01/month | HTTPS + CDN for `dash.averagejoematt.com` — negligible cost |
| 2026-02-26 | Rejected provisioned concurrency for MCP Lambda | Saved $10.80/month | Solved latency with memory bump ($1/mo) + caching instead |
| 2026-02-26 | Lambda memory 512→1024 MB | +~$1/month | 2x CPU allocation, halved heavy query execution time |
| 2026-02-25 | DynamoDB on-demand (not provisioned) | Saves ~$10-15/mo vs provisioned | Workload is spiky (morning ingestion burst, sparse MCP queries) |
| 2026-02-25 | Single DynamoDB table, no GSI | $0 extra | All access patterns served by PK+SK queries |
| 2026-03-10 | CloudWatch alarm consolidation (COST-A): 87 → ~41 alarms. Removed: 14 CDK duplicates (ingestion-error-daily-brief, life-platform-daily-brief-invocations, canary-any-failure, 11 per-Lambda AI token alarms) + ~32 pre-CDK orphans via delete_orphan_alarms.sh. AI token coverage: platform total + daily-brief only (was per-Lambda). | Saves ~$4.60/month ($7.70 → $3.10) |
| 2026-03-05 | Secrets Manager consolidation: 12 → 9 active secrets | Saves $1.20/month | Consolidated to dedicated per-service secrets. `ai-keys` bundles Anthropic API key + MCP API key (only bundle justified under ADR-014). `api-keys` fully deleted 2026-03-14. |
| 2026-02-25 | Single DynamoDB table, no GSI | $0 extra | All access patterns served by PK+SK queries |
| 2026-02-24 | 12 Secrets Manager secrets | $4.80/month → consolidated to $2.40/month | Isolation was right tradeoff initially; consolidated once pattern was proven |
| 2026-02-24 | CloudWatch 30-day log retention | Saves vs default infinite | Sufficient for debugging; older data in S3 raw archives |
| 2026-02-23 | MCP via Lambda Function URL (not API Gateway) | $0 vs ~$3.50/mo for REST API | AuthType NONE + in-Lambda API key check = free |
| 2026-02-23 | Haiku (not Sonnet/Opus) for AI calls in briefs/digests — **STALE: actual routing is Sonnet (see ai_calls.py)** | ~$3/mo actual (Sonnet) vs ~$0.10/mo if Haiku | Sonnet used for quality; Haiku entry was aspirational, never reflected production routing. Not a cost problem — still within budget. |

---

## Monthly Actuals

| Month | AWS Bill | Notes |
|-------|---------|-------|
| Feb 2026 | $1.92 | Platform built Feb 22, partial month. 22 Lambdas, 19 sources, CloudFront CDN |
| Mar 2026 | ~$13-14 est (pre-COST-A) | First full month. 41 Lambdas, 87 alarms (real run-rate). COST-A cleanup in progress — target ~$9-10/mo post-cleanup. |
| Mar 2026 (post-COST-A) | ~$9-10 est | 47 alarms, `api-keys` secret deleted 2026-03-14 (saves $0.40/mo from April onward). |

---

## Potential Cost Increases (Planned Features)

| Feature | Est. Monthly Cost | Status |
|---------|-------------------|--------|
| WAF rate limiting | ~$5/month | Tier 3 backlog — rejected in favor of reserved concurrency ($0) |
| Monarch Money integration | $0 (API polling, consolidate into `life-platform/api-keys`) | Tier 1 backlog |
| Google Calendar integration | $0 (OAuth, follows existing token rotation pattern) | Tier 1 backlog |
| Brittany accountability email | $0 (reuses existing SES + Daily Brief Lambda pattern) | Next planned feature |
| Provisioned concurrency (rejected) | $10.80/month | ❌ Rejected — caching solved the problem |
| Additional Secrets Manager secrets | $0.40/each | OAuth sources (new integrations) stay separate; static API keys merge into `life-platform/api-keys` |
