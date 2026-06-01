# Life Platform — Cost Tracker

Last updated: 2026-06-01 (v7.21.0)

> Budget ceiling: **$75/month all-in** (raised from $25 with the Bedrock migration + automated guardrails, 2026-05-29). Design constraint: every feature must justify its cost.

---

## Current Monthly Cost Breakdown (actuals, 2026-05-29)

Rewritten from Cost Explorer + the cost-governor estimator. The prior "~$10/mo"
figure was stale fiction (it predated Bedrock and three cost drivers the doc got
wrong). Real run-rate is **~$33-36/mo** — comfortably under the $75 ceiling.

| Service | Cost/Month | Notes |
|---------|-----------|-------|
| **CloudWatch** | ~$9.60 | **46 ingestion-error alarms + others (~112 total) × $0.10**. COST-A claimed ~40; regressed. Consolidation to metric-math is a tracked follow-up (~$4/mo). |
| **WAF** | ~$8.78 | `life-platform-amj-waf` (CLOUDFRONT, 4 rate rules) = $5/ACL + $1/rule. Slated for deletion once the Lambda concurrency quota lands (case 177921309700709). |
| **Secrets Manager** | ~$5.60 | 14 active secrets × $0.40. All currently referenced in code — pruning needs reference cleanup first (not a safe blind delete). |
| **Bedrock (AI)** | ~$5-7 | Claude inference, mostly Haiku 4.5 (coaches) + Sonnet 4.6 (daily brief), prompt-cached. Tracked near-real-time by the cost-governor; Cost Explorer lags 24-48h. |
| **Tax / Cost Explorer API** | ~$4 | CE GetCostAndUsage calls (governor, hourly) + tax. |
| **KMS** | ~$1.00 | DynamoDB CMK. |
| **Route 53** | ~$0.50 | 1 hosted zone — flat fee. |
| **Lambda / DynamoDB / S3 / CloudFront / SES** | ~$0.60 | All well-managed (on-demand DDB, 30-day log retention, S3 lifecycle). |
| **Total** | **~$33-36/month** | ~48% of the $75 ceiling. |

---

## Budget Guardrails (automated, 2026-05-29)

Three layers — see `lambdas/budget_guard.py`, `lambdas/operational/cost_governor_lambda.py`, ADR/plan for design:

1. **AWS Budget** (`life-platform-monthly-75`, CDK CoreStack): one $75 budget, email
   notifications at **50/70/85/100% (actual + 100% forecast)** → `awsdev@mattsusername.com`.
   Lagged backstop (Cost Explorer trails Bedrock 24-48h).
2. **cost-governor** (hourly): estimates near-real-time spend (Cost Explorer non-AI +
   Bedrock per-model token metrics × price, +15% buffer), projects month-end, writes a
   **tier** to SSM `/life-platform/budget-tier`. Alerts on tier change.
3. **budget_guard** (graceful degradation, protects the daily brief longest):

   | Tier | Projected month-end | Effect |
   |------|---------------------|--------|
   | 0 Normal | < $55 | everything runs |
   | 1 Caution | $55-65 | heavy coach AI paused (narrative/ensemble/chronicle) |
   | 2 Restrict | $65-73 | + public website AI paused (friendly "paused" message) |
   | 3 Hard stop | ≥ $73 | + ALL Bedrock paused (`bedrock_client` refuses); daily brief is data-only |

   Auto-resumes at month rollover. **Status: deployed observe-only** — the governor emits
   metrics + computes the tier but doesn't enforce yet; flip `OBSERVE_MODE=false` on
   `life-platform-cost-governor` to enable once the estimate is validated against the real bill.

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
| 2026-05-17 | **V2 audit cost optimization (P5)**: 5-item sweep totaling **$3.65/mo savings**. (1) deleted 5 power-tuning Lambdas left from earlier perf work; (2) deleted 5 orphan IAM roles (digest, og-image, measurements-ingestion, pipeline-health-check, subscriber-onboarding); (3) duplicate CloudWatch alarm pruning; (4) retired `api-keys`, `google-calendar`, `webhook-key` secret remnants; (5) scheduled `life-platform/notion`, `life-platform/dropbox`, `life-platform/anthropic-api-key` for deletion (orphans / migrated to bundle). | Saves $3.65/month total (full effect from June 2026 onward) |
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
| Apr 2026 | est ~$12-13 | Platform growth; Lambda count ~78 before V2 audit. |
| May 2026 MTD (through 2026-05-19) | $18.58 | Mid-month spend includes pre-V2 baseline; V2 P5 savings ($3.65/mo) land June. End-of-May expected ~$24-26 unadjusted. |

---

## Potential Cost Increases (Planned Features)

| Feature | Est. Monthly Cost | Status |
|---------|-------------------|--------|
| WAF rate limiting | ~$5/month | Tier 3 backlog — rejected in favor of reserved concurrency ($0) |
| Monarch Money integration | $0 (API polling, consolidate into `life-platform/api-keys`) | Tier 1 backlog |
| Google Calendar integration | $0 (OAuth, follows existing token rotation pattern) | Tier 1 backlog |
| Brittany accountability email | $0 (reuses existing SES + Daily Brief Lambda pattern) | Next planned feature |
| Provisioned concurrency (rejected) | $10.80/month | ❌ Rejected — caching solved the problem |
| Additional Secrets Manager secrets | $0.40/each | OAuth sources (new integrations) stay separate; static API keys merge into `life-platform/ingestion-keys` bundle (the new home, since `api-keys` was retired). |

---

**Verified:** 2026-05-19 (V2 audit operational sweep)
