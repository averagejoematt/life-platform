# V2 Comprehensive Audit Prompt

> **Status: HISTORICAL.** The prompt used for the 2026-05-17 V2 audit (findings closed in ADR-057). Reusable as a template for a future audit cycle; not a live document.

> A second-round deep-dive planning prompt, refined from the v1 audit (2026-05-16/17, ~130 findings, ~70 shipped). v1 covered Phase 1-8 thoroughly but had ~10% wrong-premise findings (orphaned WAF that wasn't, "skeleton" coach evaluator that was 982 LOC built, board_ask caching that's no-op below threshold). This prompt encodes those lessons to produce a sharper v2.

---

## The prompt

```
/plan

I want a comprehensive second-round audit of the Life Platform — same
ambition as v1 but with the corrections from what v1 got wrong baked in.

Imagine a room of world-class architects, engineers, CTOs, security
specialists, AWS solution architects, AI engineers, data engineers, and
product designers — all with a 48-hour goal to pressure-test this entire
solution. The brief is:

  1. SURFACE EVERYTHING that's load-bearing but undocumented, fragile but
     unflagged, expensive but unnoticed, or architecturally wrong but
     working "well enough today."
  2. VERIFY before recommending. Don't accept the existing audit's framing
     at face value. v1 had ~10% wrong-premise findings (e.g., "orphaned WAF"
     was load-bearing; "build the coach evaluator" — it was already built).
     Read the actual code, query the actual AWS state, run the actual
     Lambdas before declaring something needs fixing.
  3. QUANTIFY ROI honestly. Not all hardening pays off for a single-user
     personal platform. v1's KMS-on-S3 migration broke the live site
     (ADR-053) because the hardening conflicted with the website-endpoint
     architecture. ROI must net the real risk of breaking production, the
     deploy effort, AND ongoing maintenance cost — not just the abstract
     security/quality benefit.
  4. CATEGORIZE findings into action types: (a) ship now / single session,
     (b) ship with explicit approval / blast radius warning, (c) defer with
     written rationale, (d) won't-do with rationale, (e) data-blocked /
     time-blocked / quota-blocked.

Specific things to look at:

  CODEBASE
  - All files in lambdas/, mcp/, cdk/, deploy/, site/, tests/, docs/.
  - Read whole files, not just headers. v1 missed that intelligence_common
    has only 1 importer (P4.3 ended up closed) because surface scans saw
    "1556 LOC monolith" without checking who imports it.
  - Look for: latent dead code, drift between layer versions (some Lambdas
    on v42, others on v50 today), inconsistent error handling, shared-state
    assumptions that break under concurrency, missing idempotency on
    side-effectful paths.
  - Specifically inspect: the 6 SIMP-2-exempt ingestion Lambdas (notion,
    macrofactor, apple_health, hae, dropbox_poll, food_delivery) for drift
    against the framework patterns.
  - daily_brief_lambda.py (2,283 LOC monolith) — should it stay as-is, or
    is a state-machine refactor worth the risk now?
  - site_api_lambda.py — already partially refactored via dispatch table
    (v7.7.0); is there a sharper split worth doing?

  AWS INFRASTRUCTURE
  - All Lambdas + their layer versions (currently uneven — see ADR-056
    follow-up). Are the older v42-v43 functions safe to run on stale
    shared code, or are there latent bugs?
  - DynamoDB single-table — single source of truth, no GSIs. Are any access
    patterns expensive scans that warrant a GSI now? (ADR-005 says no, but
    revisit with current item count + access patterns.)
  - S3 bucket structure (raw/, generated/, site/, archive/, deploys/,
    config/, uploads/). Are lifecycle policies sane? Are any prefixes
    accumulating unbounded? Phase 1.3 set lifecycle but verify it's working.
  - KMS keys: DDB CMK + S3 CMK. The S3 CMK is now retained-but-not-default
    (ADR-053). Are there any uses that explicitly invoke it that could
    break? Should it just be deleted, or kept indefinitely for the future
    REST+OAC migration (ADR-054)?
  - CloudFront 4 distributions (averagejoematt + dash + blog + buddy). Are
    any cache behaviors misconfigured? Any origins serving 5xx errors?
  - IAM: 37+ Lambda roles, each (claimed) least-privilege. Audit for
    actual least-privilege via IAM Access Analyzer; identify any role
    that's accumulated unused permissions over time.
  - Secrets Manager: 14 active. v1 deleted some (P1.4) — verify no new
    orphans accumulated. Verify rotation policy is actually followed.
  - CloudWatch: ~100 alarms (urgent + digest). Are the digest alarms
    actually being noisy in the digest, or are they all clean? If they're
    clean, can the digest be silenced for those entirely?
  - Cost Explorer: who/what is the next-biggest cost lever after v1's
    log retention + WAF + secrets cleanups? April baseline $35 → May $31.
    Where's the next $5-10/mo win?
  - Reserved concurrency: account quota is 10 (custom cap below AWS
    default 1000). v1 tried to set Whoop=1, got blocked. Is the manual
    Support ticket worth filing? Are there other concurrency-starvation
    risks worth fixing first?

  AI USAGE
  - Anthropic spend: only daily-brief + coach-state-updater currently emit
    token telemetry to CloudWatch (LifePlatform/AI namespace). Most other
    AI-calling Lambdas don't route through retry_utils.call_anthropic_raw,
    so their token usage is invisible. Roll out emission across all AI
    Lambdas. Then compute real per-Lambda + platform-wide spend.
  - Prompt caching: 12 Lambdas have cache_control, 7 more via retry_utils.
    Quantify cache hit rate from CloudWatch metrics (AnthropicCacheReadTokens
    vs AnthropicInputTokens) per Lambda. Identify uncached calls that could
    benefit (system prompt ≥1024 tokens).
  - Model selection: AI_MODEL_HAIKU vs AI_MODEL (Sonnet). Spot-check that
    each call site uses the cheapest model that delivers acceptable quality.
    The audit's ADR-049 documented model tiering but new call sites may
    have drifted.
  - Coach prediction loop (ADR-055): in 7-30 days, verify the chain is
    producing non-zero confirmed/refuted counts. If still 100% inconclusive,
    diagnose the metric-resolution gap deeper.
  - Coach quality gate: currently advisory only. Tie hit_rate_pct
    threshold (≥30%?) to a retry-with-stricter-prompt path once the
    track-record data exists.
  - Daily-brief AI call cost: 4 sequential Anthropic calls per day (BoD,
    training+nutrition, journal, TL;DR). Are the shared-preamble cache
    savings actually realized (verify via metrics)? Is there a way to
    parallelize without changing output quality?

  DATA FLOW + RELIABILITY
  - Pipeline timing: ADR-052 fixed the daily-brief race (P3.1). Verify
    every consumer/producer dependency has explicit ordering. Are there
    other implicit races (compute → email, ingestion → compute)?
  - Idempotency: P3.3 added run_id to compute Lambdas. Audit that the
    framework path covers all writes (PREDICTION#, LEARNING#, etc.) and
    that DDB writes can safely be replayed without doubling effects.
  - Backfill scripts in backfill/ — are any of them stale-unsafe (would
    corrupt current data if re-run)? Document hazards in
    backfill/README.md per-script.
  - Patches in patches/ (51 files) — same question. Some are already-
    irrelevant; identify and delete with a single ADR documenting the
    cleanup.

  WEBSITE
  - averagejoematt.com performance: Lighthouse scores, Core Web Vitals,
    JS bundle size. Site is mostly static HTML but has dynamic data
    fetches (vitals, labs, observatory). Audit p50/p95 load times.
  - SEO: JSON-LD shipped today (v7.20.0) for index + chronicle template.
    Crawl coverage check: search "averagejoematt.com" on Google and
    audit which pages are indexed vs. not.
  - Accessibility: keyboard nav, screen reader support, color contrast.
    Never audited in v1.
  - Subscriber path: subscribe.html → confirm → weekly digest. End-to-end
    test the flow.

  SECURITY (REVISITED)
  - Phase 2 hardening (rate limiting, validation, headers, CMK, CloudTrail,
    HMAC, cache-control, debug prints) was shipped. Verify each is still
    in place 1 month later — drift check.
  - WAF rules: what's actually in the active WebACL (the one v1 wrongly
    called orphaned)? Are rate-based rules tuned correctly?
  - Anthropic API key: still in life-platform/ai-keys. Rotation cadence?
    Has it been rotated since the audit started?
  - Lambda function URLs vs API Gateway: which Lambdas are exposed how?
    Any function URL with overly-permissive CORS or auth bypass?

  DEVELOPER EXPERIENCE
  - Time to deploy a single Lambda (deploy/deploy_lambda.sh). Currently
    ~10s. Are there friction points?
  - CDK deploy time per stack. Largest stacks?
  - Test suite: 1229 passing. Coverage? What's the longest unit test
    cycle? Slowest tests?
  - CI/CD GitHub Actions: any flaky steps? Lint/test cycle time?

  USER-FACING / PRODUCT
  - What's actually being USED in MCP/Claude conversations? Audit MCP tool
    invocation counts (CloudWatch metrics). Which of 127 tools have <5
    invocations in last 30 days — candidates for deletion?
  - Daily-brief email: when was the last time it was actually READ
    (SES open tracking)? If unread for >7 days, is it worth generating?
  - Weekly/monthly digests: same question.
  - Coach narratives: are any coaches generating identical-looking content
    week-over-week (low novelty)? That's a sign their state machine isn't
    progressing.

Output:

  For each finding, produce:
  - SEVERITY: CRITICAL / HIGH / MEDIUM / LOW
  - EVIDENCE: specific file:line or AWS resource ID + state snapshot
  - PROPOSED ACTION: concrete change, not "audit X" but "edit Y to do Z"
  - EFFORT: XS / S / M / L (hours to days)
  - ROI: dollar/month savings, reliability improvement, OR explicit
    "non-monetary justification" with the actual justification
  - RISK: what breaks if this goes wrong + recommended rollback
  - DEPENDENCIES: other findings or external actions blocking this

Then group findings into phases (similar to v1's Phase 1-8), but order
phases by NET ROI (savings + reliability gain - effort - risk), not by
topical area.

For items that v1 closed-as-rationale (ADR-057) — re-validate the
rationale only if there's new evidence. Otherwise honor the closure.

For items shipped in v1 — verify they're still working. Drift detection
is half the value of v2.

Deliverable: a single planning document with 50-100 findings (less is
fine; more should be aggressively triaged), grouped into 5-8 phases,
ordered by ROI, each finding actionable as a single PR or single deploy.
```

---

## What v2 should specifically NOT do

- Don't re-suggest the items in ADR-057 (formally closed). If new evidence emerges, fine — but cite the new evidence.
- Don't re-suggest P6 (multi-user) unless there's a real subscriber on the horizon.
- Don't re-suggest P8.13 (cross-region DR).
- Don't propose "audit X" as a finding — propose the actual fix or formally close the question.
- Don't estimate >$50/mo in savings without showing the AWS billing line that supports it. v1's $80-120/mo estimate landed at ~$4-5/mo realized; lesson is that the savings hide in many small places, not big headline items.

## What v2 should explicitly look for that v1 missed

- **Latent bugs from environmental drift** — e.g., the layer-version unevenness across Lambdas (v42-v50). Each older Lambda is running older `retry_utils`, missing token emission. v1 didn't catch this because it focused on greenfield work; v2 should snapshot the actual deployed state and compare to the source-of-truth code.
- **Failed-by-design paths** — e.g., the 100% inconclusive coach evaluations was a year-long silent failure mode. What other "running but not working" pipelines exist?
- **Cost concentrations from unused features** — MCP tools with low invocation counts, alarms that never fire, secrets that don't rotate. Things that cost a little but produce nothing.
- **Architectural decisions that contradict their own documentation** — e.g., ADR-005 says "no GSIs" but maybe an access pattern now warrants one. ADR-008 says "single user" but partial multi-user wiring exists. Find contradictions, propose either docs-update or arch-update.
- **Things that worked in v1's audit but are now BROKEN after the v1 work** — drift from the v1 changes themselves. e.g., the CloudFront/KMS incompatibility (ADR-053) was caused BY v1's Phase 2.4.

## Pre-flight checks before running v2

1. **Snapshot current state**: `git log --oneline -100`, `aws lambda list-functions`, `aws ce get-cost-and-usage --granularity DAILY` for last 14 days. v2 audit should be against the post-v1 state, not the pre-v1 state.
2. **Re-read ADR-053 through ADR-057**. These document the v1 decisions that v2 must respect (or explicitly override with new evidence).
3. **Check the v1 changelog**: v7.0.0 → v7.20.0 is the v1 work. v2 starts at v8.0.0.
4. **Verify the coach prediction loop validation timeline**: if v2 is run before 2026-06-15 (7-30 days post-v1), the coach hit_rate_pct will still be null and the loop is unverified. If after, the data is real.

## Suggested cadence

Run v2 in **August 2026** (~3 months post-v1). Reasons:
- Coach prediction loop will have 3 months of accumulated verdicts — enough to actually tune the quality gate threshold.
- Anthropic spend will have stabilized post-cache-rollout — easier to measure cache hit rate ROI.
- Any latent v1 regressions will have surfaced.
- AWS cost trend will be clear (April $35 → May $31 → expected steady state).
- New audit findings will accumulate from 3 months of real usage rather than 1 day of recent changes.

If running sooner (e.g., 2026-06-15 or 2026-07-01), expect 30-50 findings instead of 100+ — most of the v1 surface has been covered.
