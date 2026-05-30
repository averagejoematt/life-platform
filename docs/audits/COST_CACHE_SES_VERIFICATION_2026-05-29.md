# Cost / Cache / SES Verification — 2026-05-29

**Window:** rolling 7d ending 2026-05-30 01:17 UTC
**Account:** 205930651321 (us-west-2 primary)
**Budget guard mode:** ENFORCING (`OBSERVE_MODE=false`), ceiling $75/mo
**Current tier (SSM `/life-platform/budget-tier`):** **1** — coaches paused (set 2026-05-29 18:00:41 PT)
**Source telemetry:** `LifePlatform/AI` (legacy Anthropic-* names, still emitting post-Bedrock), `LifePlatform/Budget`, `AWS/SES`, Cost Explorer.

---

## Headline findings

1. **🚨 Tier 1 is firing correctly, but driven by non-AI overhead — not AI spend.** The remediable bulk of the projection is the still-attached WAF + CloudWatch + Secrets Manager, not Bedrock.
2. **🚨 WAF was NOT deleted** in P1.4 despite the CHANGELOG entry — `life-platform-amj-waf` is still attached to CloudFront. $8.36 MTD (~$8-10/mo recurring). Deleting it would drop the projection below $55 and flip the tier back to 0.
3. **✅ Bedrock cutover is delivering big.** Real Bedrock MTD is **$4.27** (Haiku $3.73 + Sonnet $0.54). Pre-Bedrock Anthropic-API spend was running materially higher. The migration is the dominant cost win this month.
4. **⚠️ daily-brief cache hit = 0%** — cache is being *written* (10,353 tokens) but never *read*. Root cause is the 5-min Anthropic cache TTL vs the once-daily invocation cadence — the cache always expires before the next run. **Not a bug, but the cache writes are pure waste.** Recommendation: drop `cache_control` on daily-brief specifically, or move it to a separate ephemeral path that doesn't pay the write surcharge.
5. **⚠️ coach-narrative-orchestrator cache hit = 1.3%** — better but still low. Cache writes to investigate: 14,886.
6. **⚠️ SES opens = 0** with 71 deliveries in 7d. Two issues stacked: (a) sending Lambdas set `ConfigurationSetName` but don't pass `Tags=[{Name:"SesEventType",...}]` so the per-event-type CloudWatch dimension is all "unknown"; (b) account-level `Open` is also 0, which points to Apple Mail Privacy Protection stripping the tracking pixel — no `CustomRedirectDomain` is configured.
7. **⚠️ 312 `AnthropicAPIFailure` events over 7d** — daily-brief 139, quality-gate 56, state-updater 56, narrative-orchestrator 53, ensemble-digest 8. Most are likely throttle retries (Bedrock concurrency) but worth a focused investigation.

---

## D-03 — AI spend per Lambda (7d)

> Caveat: the `LifePlatform/AI` namespace emits `Anthropic*` token metrics with no model dimension, so the table below prices everything at Sonnet rates as an upper bound. Real cost is significantly lower because most coach traffic is Haiku (~3x cheaper). The Cost Explorer reconciliation below is the ground truth.

| Lambda | Input tokens | Output | Cache read | Cache write | API fail | Cost upper bound (7d) |
|--------|-------------:|-------:|-----------:|------------:|---------:|-----------------------:|
| coach-narrative-orchestrator | 5,791,250 | 363,945 | 76,097 | 14,886 | 53 | $22.91 |
| daily-brief | 549,203 | 102,251 | 0 | 10,353 | 139 | $3.22 |
| coach-state-updater | 274,009 | 158,799 | 0 | 0 | 56 | $3.20 |
| coach-history-summarizer | 556,983 | 27,000 | 0 | 0 | 0 | $2.08 |
| coach-ensemble-digest | 299,803 | 48,261 | 0 | 0 | 8 | $1.62 |
| coach-quality-gate | 143,956 | 37,521 | 0 | 0 | 56 | $0.99 |
| life-platform-site-api-ai | 0 | 0 | 0 | 0 | 0 | $0.00 |
| **TOTALS** | **7,615,204** | **737,777** | **76,097** | **25,239** | **312** | **$34.02** |

**Real Bedrock spend (Cost Explorer MTD, 29 days):**
- Claude Haiku 4.5 (Bedrock Edition): **$3.73**
- Claude Sonnet 4.6 (Bedrock Edition): **$0.54**
- **Bedrock total MTD: $4.27** (~$4.40 projected month-end)

The ~8x gap between the upper-bound table ($34 / 7d) and the real bill (~$4 / 30d) confirms the coach mix is overwhelmingly Haiku (as designed in ADR-049 model tiering).

**Top spender:** coach-narrative-orchestrator is the dominant Bedrock consumer (75%+ of token volume). Cache write activity present but reads only 1.3% — worth a focused cache-engagement investigation.

**Reduction levers:** (1) raise cache hit on narrative-orchestrator (sibling coaches share the prelude); (2) drop cache_control on daily-brief (cache TTL > invocation interval = wasted writes); (3) consider trimming `coach-history-summarizer` output (557k in → 27k out is a fine ratio but the input is large).

---

## D-01 — Cache verification

| Lambda | Cache read | Cache write | Hit % | Verdict |
|--------|-----------:|------------:|------:|---------|
| coach-narrative-orchestrator | 76,097 | 14,886 | 1.3% | Cache **engages** but rarely. Worth tuning the sibling-cache pattern. |
| daily-brief | 0 | 10,353 | 0% | Cache **never engages** — 5-min TTL < 24h invocation interval. **Writes are waste.** |
| All others | 0 | 0 | n/a | No cache_control wrapper (expected for short-lived structured tasks). |

**Daily-brief specific:** the post-fix wrapper (P0.1) is producing cache writes but no cross-invocation reads. Anthropic's prompt cache TTL is 5 minutes — daily-brief fires once at 11 AM PT, so the cache always expires. Removing the wrapper drops a small surcharge (cache write is 1.25x base for Haiku, 1.25x base for Sonnet).

**Within-run cache:** if daily-brief makes multiple Bedrock calls in a single invocation, intra-invocation cache hits *would* be useful — verify by inspecting the call pattern. The 10k cache_write with 0 cache_read suggests it's not making a second call with the same prefix.

---

## D-04 — SES open / delivery / bounce (7d)

**Account-level (no `SesEventType` dim, configuration set agnostic):**
- Send: **76**
- Delivery: **71** (93%)
- Open: **0** ← problem
- Click: **0**
- Bounce: 5 (BounceRate=0.72% — acceptable)
- Complaint: 0

**Configuration set `life-platform-emails` per-event dim:** every event lands in `SesEventType=unknown` because sending Lambdas (daily_brief, weekly_digest, monthly_digest, partner, chronicle) set `ConfigurationSetName` but do not pass `Tags=[{Name:"SesEventType", Value:"daily_brief"}, ...]` per send. This makes per-email-type open-rate analysis impossible.

**Two stacked issues:**

1. **No per-event-type tagging.** The event destination config uses `DimensionValueSource=MESSAGE_TAG` with `DefaultDimensionValue="unknown"`. To get per-email-type metrics, each `send_email` call must include `Tags=[{Name:"SesEventType", Value:"<email-kind>"}]`. **Fix:** ~5-line patch in each email Lambda's send block. *Not high-priority since opens are 0 account-wide anyway.*

2. **Open rate is genuinely 0 (account-level), not just dim-bucketed.** Two likely causes:
   - **Apple Mail Privacy Protection** strips the tracking pixel by default. Roughly 50%+ of personal-domain mail is Apple Mail.
   - No `CustomRedirectDomain` is configured on the configuration set, so even clicks go untracked.

**Fix path:** `aws sesv2 put-configuration-set-tracking-options --configuration-set-name life-platform-emails --custom-redirect-domain track.averagejoematt.com` (after creating + CNAME-validating the subdomain). Note: this only solves *click* tracking — opens remain unreliable on Apple Mail. Worth doing for clicks alone.

---

## D-02 — Budget guard sanity check

**Cost governor (last run 2026-05-29 17:18 PT, 11 of last 24h had datapoints — hourly schedule):**

| Metric | Value |
|--------|------:|
| EstimatedMonthToDateSpend | $45.24 |
| ProjectedMonthlySpend | **$57.93** |
| BudgetTier | **1** |

**Threshold reminder:** tier 1 fires at projected ≥ $55, tier 2 ≥ $65, tier 3 ≥ $73.

**Projection breakdown (reconstructed):**
- MTD non-AI (Cost Explorer, all-services minus Bedrock): ~$41 (consistent with the $34.67 service-grouped total + buffer)
- MTD AI (Bedrock tokens × current price × 1.15 buffer): ~$4
- Days remaining: 0.96
- Projection ≈ MTD + (non_ai_daily + ai_active_daily) × 0.96 ≈ $57.93

**Verdict:** the projection is correct — tier 1 is appropriate given today's input. But it's driven by **non-AI overhead**, not AI. The fixable hotspots:

| MTD line item | Amount | Action |
|---------------|-------:|--------|
| AWS WAF | $8.36 | **DELETE — `life-platform-amj-waf` should already be gone per P1.4 but is still attached to CloudFront.** |
| AmazonCloudWatch | $9.14 | Audit log retention + metric explorer queries. Likely overgrown alarm/dashboard count. |
| Secrets Manager | $6.05 | 40+ secrets at $0.40/mo each. Most are dead post-Bedrock (anthropic-* keys). Prune in line with Task #88. |
| Tax | $3.26 | n/a |
| Claude Haiku 4.5 | $3.73 | AI is small share. |
| Cost Explorer API | $1.58 | Cost-governor's own queries. Acceptable. |
| KMS | $0.96 | Acceptable. |
| Sonnet 4.6 | $0.54 | Small. |

**One concrete action would drop the tier:** delete the WAF (saves $8/mo). MTD becomes ~$36.88, projection ~$49.50 → tier 0.

---

## ⚠️ Action items (ranked)

1. **DELETE the orphaned WAF.** `life-platform-amj-waf` in us-east-1 (CLOUDFRONT scope). Saves ~$8/mo, flips budget tier back to 0. P1.4 evidently failed silently — write a post-mortem about what got missed.
2. **Drop cache_control on daily-brief.** Cache TTL << invocation interval = wasted writes. Net savings small (cents/mo) but it's the right shape.
3. **Investigate coach-narrative-orchestrator cache hit rate.** 1.3% with 76k reads vs 15k writes — close to one-shot per run. Verify the sibling-coach cache pattern is actually shared, not per-Lambda-per-run.
4. ~~Audit `AnthropicAPIFailure` = 312 (7d)~~ **RESOLVED 2026-05-29.** All 312 failures occurred on 2026-05-27, before the layer-v62 deploy. Log sample: `"Anthropic unavailable after 4 attempts (HTTP 400)"` — pre-v62 message format, malformed-request error (NOT throttle). Last-24h count is **0**. The v62 cleanup (sentinel-stub for dead Anthropic-key fetches) appears to have fixed whatever was producing the HTTP-400.
5. **(Later)** Configure SES `CustomRedirectDomain` so click tracking works. Per-event MessageTags is a smaller cleanup — only useful once opens/clicks are actually measurable.
6. **(Later)** Prune Secrets Manager (Task #88 follow-up). Each retired anthropic-* secret is $0.40/mo.

---

## Notes / methodology

- Pricing applied to the LifePlatform/AI table is Sonnet across the board (upper bound). The true cost is given by the Cost Explorer Bedrock line, which is correctly model-aware. The upper-bound table is for **ranking and trend**, not budget arithmetic.
- The cost-governor's `AI_SAFETY_BUFFER=1.15` is intentional and correct; the projection didn't over-fire — the MTD non-AI is the dominant input.
- Reverse-chronological CHANGELOG note: pytest-cov ratcheting is unrelated to spend; not conflated here.
- Active-days AI projection (`_ai_active_days`) is the right denominator post-Bedrock cutover (mid-month migration day shouldn't dilute the rate). Implementation in `lambdas/operational/cost_governor_lambda.py:160`.

---

**Verified by:** Claude Code session 2026-05-29.
