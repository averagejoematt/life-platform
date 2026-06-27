# Life Platform — Cost Tracker

Last updated: 2026-06-27 (v8.6.0)

> Budget ceiling: **$75/month all-in** (raised from $25 with the Bedrock migration + automated guardrails, 2026-05-29). Design constraint: every feature must justify its cost.

---

## Production Run-Rate Sweep — 2026-06-08 (real Cost Explorer data)

Cross-functional sweep of the steady-state run-rate. **Real monthly bill (CE, unblended):**
Mar **$20.04** → Apr **$35.01** → May **$48.19** (peak) → Jun MTD ~**$18.60** (partial).

- **The bill is two things:** a **fixed floor (~$15–17/mo all-in, post-WAF)** — Secrets ~$6.45, CloudWatch alarms ~$4–5, **Cost-Explorer API ~$2–4**, KMS ~$1, Route 53 $0.50, Lambda/DDB/S3/CloudFront ~$0.50, +~10% tax — plus **variable Bedrock AI**, which is spiky and *development-driven* (marathon days $4–6, quiet days $0.80–1.10), not steady.
- **Expected steady-state production run-rate: ~$25–40/mo.** The May $48 peak was the Bedrock-cutover/v4-launch build phase, not the designed steady state. Hard-capped at $75 by the **enforcing** governor (above).
- **WAF deleted** (~−$8/mo; June shows $0). Confirmed banked alongside the earlier ingestion-alarm consolidation (−$4.60) and V2 sweep (−$3.65).

**Audit of reduction levers (what's left is small — the system is near its floor):**
- **CE-API polling (done 2026-06-08):** governor hourly → **every 4h**, ~−$2–3/mo. The AI estimate stays fresh from CloudWatch token metrics; only the slow non-AI bill is polled less.
- **Bedrock model tiering — already optimal:** structured passes (IC-3 analysis) run on **Haiku**; narrative (coaches, board, TL;DR, the 8-agent ensemble) run on **Sonnet** deliberately for prose quality (ADR-049). `call_anthropic(cache_system=True)` caches every system block by default — caching coverage is comprehensive. The only further "saving" would trade narrative quality; **not recommended** unless budget pressure rises.
- **CloudWatch alarms — already consolidated** (87 → ~25); no safe consolidation remains.
- **Secrets (~$6.45) — mostly irreducible** per-service OAuth isolation; the paused `strava` secret is intentionally retained.

**Net:** run-rate is excellent and hard-capped; ~$6–10/mo of micro-savings exist but the high-value wins were already banked.

> **BENCH-1 (2026-06-19, ADR-089):** the new `episode-detect` Lambda runs **weekly** (Sunday) and is **pure-Python (no Bedrock)** over a few thousand DDB rows — **pennies/mo** (Lambda + a handful of Query/PutItem calls). Dana: noted, negligible against the $75 ceiling.

---

## Current Monthly Cost Breakdown (actuals, 2026-05-29 — superseded by the 2026-06-08 sweep above)

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

   Auto-resumes at month rollover. **Status: ENFORCING** — `OBSERVE_MODE=false` on
   `life-platform-cost-governor` (since 2026-05-29). The governor sets the SSM tier and
   `budget_guard` gates AI accordingly; `bedrock_client` enforces the Tier-3 hard stop.
   AWS Budgets is the independent lagged backstop. **Cadence: every 4h** (was hourly, cut
   2026-06-08 to reduce Cost-Explorer self-cost — the AI half is priced from cheap
   CloudWatch token metrics, so only the slow non-AI half needs the CE call).

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
| Mar 2026 | **$20.04** (CE actual) | First full month. Fixed infra only (Secrets $5.12, CloudWatch $4.84, WAF $4.12, CE-API $2.50, Tax $1.88, KMS $0.75) — pre-Bedrock. The earlier "~$9-14 est" was wrong (under-counted). |
| Apr 2026 | **$35.01** (CE actual) | Infra grew: CloudWatch $9.56, WAF $9.04, Secrets $6.90, CE-API $4.25. AI still negligible. |
| May 2026 | **$48.19** (CE actual, peak) | + Bedrock **$14.29** (Sonnet $9.31 + Haiku $4.98) — Bedrock-cutover marathon + reset + v4 launch. The $75 ceiling held. |
| Jun 2026 (MTD ~8d) | **$18.60** (CE actual, partial) | WAF now $0 (deleted, ~−$8/mo). Bedrock $11.44 so far — inflated by this build week; steady-state expected lower. |

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

**Verified:** 2026-06-08 (production run-rate sweep — real CE data; governor enforcing; CE polling 4h)
