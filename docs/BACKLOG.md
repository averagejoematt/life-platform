# Life Platform — Open Backlog

**Last updated:** 2026-05-19 (v8.0.0)
**Source:** Synthesis of V1 audit (2026-05-17, ADR-057), V2 audit (2026-05-17, `docs/V2_AUDIT_PLAN.md`), and V2 follow-up sessions (2026-05-18/19).

> Single source of truth for everything **not done**. Items closed-with-rationale (ADR-057) and items shipped are not listed — see `docs/CHANGELOG.md` for what landed and `docs/DECISIONS.md` for what was formally closed.

---

## 📋 By status

| Bucket | Count | Action mode |
|---|---|---|
| **🔴 User-action blocked** | 3 | Waiting on you / AWS Support |
| **⏰ Data-blocked / time-windowed** | 5 | Re-evaluate at specific dates |
| **🟡 Long-tail low-value** | 11 | Optional cleanup — chip away when bored |
| **🛑 Defer-with-rationale (won't do)** | 9 | Documented `won't-do` unless trigger fires |
| **📦 New work surfaced (post-V2)** | 7 | Discovered during V2 follow-ups |
| **TOTAL OPEN** | **35** | |

---

## 🔴 User-action blocked

### B-01 — AWS Lambda concurrency quota raise
- **Filed:** AWS Support case 177921309700709 on 2026-05-19
- **Ask:** Account concurrent-execution limit 10 → 100
- **Cost:** Free
- **Unblocks:** Reserved concurrency rollout (pre-staged in CDK, commented out)
- **Action when approved:** Uncomment `reserved_concurrent_executions=` in `cdk/stacks/operational_stack.py` for 5 Lambdas (mcp, site-api, site-api-ai, daily-brief, hae-webhook); deploy via `cdk deploy LifePlatformOperational`.
- **ETA:** ~24h from filing

### B-02 — MCP tool bulk-delete decision window
- **V2 plan:** Recommended 60-day grace before bulk-pruning 124 unused MCP tools
- **Re-evaluate:** 2026-07-17 (60 days from V2 audit)
- **Data:** Per `LifePlatform/MCP ToolInvocations` metric, only 11 of 135 tools called in last 30d
- **First-pass candidates (already removable):** `tools_calendar.py` ✅ done, ~70 orphan `tool_*` functions in `mcp/tools_lifestyle.py` (3,400 LOC), `mcp/tools_correlation.py` (1,553 LOC), various `compare_*_periods` variants
- **Action:** When ready, run orphan-tool ratchet down from `AUDITED_AT=64` toward 0 in batches of 10-20

### B-03 — show_and_tell/screenshots/ local cleanup (169MB)
- **Source:** V2 P4.2 — `show_and_tell/` tracked files deleted but `screenshots/` subdir was untracked
- **Disk impact:** 169MB local-only
- **Action:** `rm -rf show_and_tell/screenshots/` (untracked, won't touch git)
- **Risk:** None — abandoned March content

---

## ⏰ Data-blocked / time-windowed

### D-01 — Cache hit-rate quantification (V2 P1.5)
- **Wait until:** ~2026-05-26 (7+ days post-emitter fix)
- **What changed:** V2 P0.6 fixed the `_emit_token_metrics` 2-arg bug; coach Lambdas now emit cache_creation/cache_read. Telemetry needs time to accumulate.
- **Query:** `aws cloudwatch get-metric-statistics --namespace LifePlatform/AI --metric-name AnthropicCacheReadTokens ...`
- **Action when data exists:** Compute cache hit ratio per Lambda; verify daily-brief's shared preamble cache is actually firing (was 0 datapoints pre-fix); quantify $/mo savings

### D-02 — Coach hit_rate threshold tuning (V2 P3.6)
- **Wait until:** ~2026-07-17 (60 days for confirmed/refuted verdicts to accumulate)
- **What changed:** V2 P1.1 (already-shipped) enforces `_normalize_metric_hint` whitelist; predictions with invalid hints become qualitative-only (correctly skipped by evaluator). New predictions from 2026-05-17+ should have measurable verdicts.
- **Action when data exists:** Read `coach_quality_gate.PASS_SCORE_THRESHOLD = 60`; tune based on actual hit_rate_pct distribution; promote advisory → blocking on score < 40

### D-03 — Per-Lambda AI spend ranking (V2 P1.4 followup)
- **Wait until:** ~2026-05-26 (7+ days post-rollout)
- **What changed:** V2 follow-up wired retry_utils/inline-telemetry on site_api + site_api_ai + partner + 5 coach Lambdas. ~9 of 22 AI-calling Lambdas now emit. Was 2.
- **Action when data exists:** Query `LifePlatform/AI AnthropicInputTokens` + `AnthropicOutputTokens` per `LambdaFunction` dimension; multiply by current Anthropic pricing; identify top 3 spenders + reduction levers

### D-04 — SES open-rate baseline (V2 P1.6 followup)
- **Wait until:** ~2026-05-26
- **What changed:** V2 P1.6 wired `life-platform-emails` configuration set to 4 email Lambdas. SES auto-injects open-tracking pixel.
- **Current state:** Send=8, Delivery=8, Open=0 over 24h (likely no recipient opens yet OR Apple Mail Privacy masking; SES tracking options may need `CustomRedirectDomain` for full visibility)
- **Action when data exists:** Compare Open / Delivery ratio across daily_brief vs weekly_digest vs partner; if Open=0 persistently, investigate `aws sesv2 put-configuration-set-tracking-options` with CNAME-validated redirect domain

### D-05 — Coach prediction loop validation (V2 ADR-055)
- **Wait until:** ~2026-06-17 (30 days post-loop closure)
- **What it tests:** Daily coach predictions get auto-evaluated against measured outcomes. Pre-V2 = 100% inconclusive (theatrical). Post-V2 should produce real confirmed/refuted verdicts.
- **Action when data exists:** Run `aws dynamodb query --table-name life-platform --key-condition-expression "begins_with(sk, 'PREDICTION#')" ...` and count by `verdict` field. Expect mix of confirmed/refuted (not 100% inconclusive).

---

## 🟡 Long-tail low-value (chip away when bored)

### L-01 — 4 multi-line prints in `anomaly_detector_lambda.py`
- V2 print-sweep skipped these (multi-line, harder to convert safely)
- Effort: 15 min careful editing
- Value: complete consistency

### L-02 — 5 redundant explicit imports in `mcp/registry.py`
- After V2 D AST-refactor, lines like `from mcp.tools_health import tool_get_autonomic_balance  # BS-MP1` are now redundant (the name is already in the explicit bulk import)
- Removing requires confirming each isn't critical-comment-anchored
- Effort: 10 min

### L-03 — Site_api partial extraction of `board_ask` + `/api/ask` handlers
- Source: V2 P6.6 — full router split deferred (too risky); partial extraction worth doing
- Move 2 large handlers (lines 2810-3000 + 7820-7870 of site_api_lambda.py) to new `lambdas/site_api_ai_handlers.py`
- Effort: 1-2h with regression test
- Value: smaller site_api_lambda.py file; easier follow-on AI work

### L-04 — Shared module adoption in exempt ingestion Lambdas (V2 P2.7)
- Notion/dropbox got `auth_breaker` ✅
- Still missing: `numeric` in dropbox_poll + food_delivery + hae; `http_retry` where applicable in macrofactor + food_delivery
- Effort: ~30 min per file
- Value: cleanup consistency

### L-05 — Migrate 47 explicit `print()` in `garmin_lambda.py`'s remaining multi-line cases
- The V2 sweep got 45 of 47; 2 multi-line remain
- Effort: 5 min

### L-06 — RSS feed: investigate `/feed.xml` alt-path 404
- Some RSS clients try `/feed.xml` not `/rss.xml`. Easy 301 redirect or duplicate file.
- Effort: 15 min

### L-07 — Refresh DEPENDENCY_GRAPH.md "Hottest Partitions" estimates
- Per V2 doc audit: estimates inherited from v4.5.0; need fresh DDB CloudWatch metrics
- Effort: 20 min query + edit

### L-08 — Verify SCHEMA.md per-source field tables exhaustively
- V2 doc audit flagged: per-source tables not line-by-line verified against current Lambda source
- Effort: 1h cross-reference

### L-09 — MCP_TOOL_CATALOG.md per-section tool tables
- V2 doc audit flagged: total count correct (127 cataloged vs 135 in registry), but per-section tables not line-by-line verified
- Effort: 1h

### L-10 — Stale `webhook-key` reference in `cdk/stacks/role_policies.py`
- Surfaced by V2 operations doc agent
- Effort: 5 min cleanup

### L-11 — DLQ depth: 66 messages remain in `life-platform-ingestion-dlq`
- These were stuck pre-Garmin-OAuth-refresh
- Will age out at 14d retention (post 2026-05-29 mostly)
- OR drain via `dlq_consumer` manual invoke
- Effort: 10 min triage + 5 min drain command
- Risk: ensure no real ingestion data was lost; if scheduled-event payloads, replay is no-op (gap detection handles)

---

## 🛑 Defer-with-rationale (won't do unless trigger fires)

These items are documented in ADR-057 or surfaced in V2 plan as won't-do. Do not re-open without new evidence.

### W-01 — Split `intelligence_common.py` (1,556 LOC)
- **Why won't-do:** Only 1 importer (`ai_expert_analyzer`); splitting multiplies imports without benefit
- **Reopen if:** A second major importer emerges

### W-02 — Multi-user / Cognito (V1 Phase 6, ~4 FTE-weeks)
- **Why won't-do:** No second user on horizon
- **Reopen if:** Real subscriber begins onboarding to their own dashboard

### W-03 — Cross-region DR (V1 P8.13)
- **Why won't-do:** Overkill for personal platform
- **Reopen if:** SLA pressure or regulatory requirement

### W-04 — Site_api full router split (V2 P6.6, 7,879 LOC monolith)
- **Why won't-do:** Touches public surface, risk > benefit
- **Reopen if:** A new endpoint requires touching the file substantially

### W-05 — HAE handler registry refactor (V1 P4.6)
- **Why won't-do:** Cleanup-only; current per-data-type code works
- **Reopen if:** 6th+ data type added

### W-06 — Lambda Power Tuning campaign (V1 P8.6)
- **Why won't-do:** Most Lambdas already at 256MB minimum; daily-brief unsafe to tune (sends real emails per invoke); realistic savings $1-3/mo
- **Reopen if:** Memory-related throttling becomes an issue

### W-07 — Batch API (V1 P5.9)
- **Why deferred:** Original plan said reconsider July 2026
- **Reopen on:** 2026-07-15 with 3 months of post-caching AI cost data

### W-08 — Inline JS extraction from `site/index.html` (V2 P6.2)
- **Why won't-do:** 22 KB across 15 inline scripts; touches many DOM IDs; risk of breaking dashboard hydration; cosmetic benefit
- **Reopen if:** CSP hardening (drop `'unsafe-inline'`) becomes priority

### W-09 — DLQ on 16 "async" Lambdas (V2 P6.5)
- **Why won't-do:** Operations stack explicitly sets `dlq=None` for scheduled health-check Lambdas; self-healing on next cron tick
- **Reopen if:** A specific Lambda's failure mode would benefit from manual replay

---

## 📦 New work surfaced (post-V2)

Items that came up during V2 follow-up sessions and aren't yet scheduled.

### N-01 — 5 long-standing alarms in ALARM state since May 3-4
- Surfaced by V2 doc-audit operations agent
- Alarms: `ingestion-error-whoop`, `life-platform-dlq-depth-warning`, `life-platform-garmin-data-ingestion-errors`, `life-platform-ingestion-dlq-messages`, `slo-source-freshness`
- Most will auto-clear after Garmin OAuth fix (today) + DLQ age-out (L-11)
- Verify clearance by 2026-05-26
- If stuck: re-tune threshold OR investigate root cause

### N-02 — Subscriber `confirm-token` lookup uses DDB scan
- Per V2 audit web/DX agent
- Currently fine (subscriber volume low)
- Re-evaluate when >2000 subscribers; switch to GSI-less pattern (item-per-token)
- Effort: 1h refactor + test
- Trigger: subscriber count

### N-03 — Email dark-mode CSS
- V2 plan: 30% of recipients use dark mode; emails currently assume light
- Add `@media (prefers-color-scheme: dark)` block in `html_builder.py`
- Effort: 3h design + test in real clients

### N-04 — Site `h1` semantic vs visual review
- V2 closed: hidden h1 is valid SEO pattern; left alone
- Possible follow-up: convert `.h-hero__title` from `div` to `h1` and remove the hidden one
- Skipped because of CSS cascade risk
- Effort: 2h careful refactor

### N-05 — V2 audit drift checks: re-verify all v1-shipped items are still working in 90 days
- Schedule a 2026-08-17 audit (per V2_AUDIT_PROMPT.md cadence)
- Use `docs/V2_AUDIT_PROMPT.md` for the v3 round
- Cost: ~1 session of focused agent work

### N-06 — Coach `quality_gate` threshold promotion
- Currently advisory (logs score, doesn't block); V2 wired it but kept it observational
- After 30 days of scores accumulating, decide: promote to retry-with-stricter-prompt on score <60? block on score <40?
- Re-evaluate: 2026-06-19

### N-07 — `compute_metadata` adoption gap-filling
- V2 P2.6 expanded to 5 more compute Lambdas; `acwr_compute` skipped (uses update_item)
- Future: if `acwr_compute` ever switches to put_item, add tag_record there
- No ETA — only if pattern changes

---

## How to add to this backlog

When you discover a new tech debt item:

1. Pick a category (User-action, Data-blocked, Long-tail, Won't-do, New-work-surfaced)
2. Assign an ID (next number in sequence within category)
3. Add a section like the ones above with: title, source/why-found, action, trigger/timing, effort estimate
4. Commit with `docs(backlog): add B-NN ...`

If you do an item, move it to `docs/CHANGELOG.md` and remove from here. If you decide an item won't ever be done, move it to `docs/DECISIONS.md` as an ADR with rationale.

---

**Verified:** 2026-05-19 — synthesized from V1 audit + V2 audit + V2 follow-ups
