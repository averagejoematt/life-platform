# V2 Audit — AI Usage + Data Flow + Reliability

**Auditor:** Claude (AI/Data-Flow leg)
**Date:** 2026-05-17
**Scope:** Anthropic API usage, prompt caching, model selection, coach intelligence pipeline, prediction loop, data flow, idempotency

---

## EXECUTIVE SUMMARY (≤500 words)

The v1 audit shipped real plumbing (retry_utils, shared layer, coach evaluator at 982 LOC, shared-preamble cache framework, run_id observability). But verification against the deployed state reveals **the plumbing is failing silently in production at almost every layer that matters**.

**The headline:** Of 22 AI-calling Lambdas, only 2 emit token telemetry to CloudWatch. Of those 2, both have a copy-paste bug that drops the cache-read/cache-write metrics on the floor — explaining why the entire `AnthropicCacheReadTokens` / `AnthropicCacheWriteTokens` metric series has **zero datapoints** in 30 days. The "caching is wired up" claim is unverifiable from telemetry because the emitter is broken. Worse: log inspection of coach-state-updater shows `cache_read: 0` on every single call. The system prompt (~700 tokens) is below Haiku's 2048-token cache threshold — caching cannot fire even if the wiring were correct.

**The coach prediction loop (v1 ADR-055) has produced 0 confirmed and 0 refuted verdicts across 787 predictions** (283 inconclusive, 504 pending). Root cause confirmed: extraction Haiku is ignoring the 17-canonical-metric whitelist and emitting prose metric names like `caloric_intake_vs_movement_volume_correlation` and `hormonal_markers_over_time`. The evaluator then can't find those metrics in DDB and writes `inconclusive` 100% of the time. The v1 "fix" exists in the system prompt but is being routinely violated.

**The coach-computation-engine has been 100% failing for at least a week** from a TypeError at line 1045 (offset-naive vs offset-aware datetime compare). It's invoked daily and writes nothing. **coach-quality-gate has 0 invocations in 7 days** — code exists, deployed, never wired to any caller. **coach-state-updater has a 17% error rate** from unparseable Haiku output (e.g. `float("40%")`). **field-notes-generate has a stale April 9 deployment** that doesn't contain the May 16 retry_utils integration — so its "P3.4 retry rollout" claim is unshipped.

**Observable AI spend: ~$7/month** (daily-brief $6.40 Sonnet + coach-state-updater $0.51 Haiku). Real total is likely 2-3x higher because 20 Lambdas don't emit telemetry. **Potential cache savings: $2-4/month** if (a) telemetry is fixed so we can measure, (b) coach Lambdas hit Haiku's 2048-token threshold or migrate to Sonnet, (c) the `_emit_token_metrics` bug is fixed.

**Layer drift:** 1 Lambda on v50, 6 on v49, 46 on v43, 3 on v25, 1 on v2 (garmin), 16 with no layer. The "v43 cohort" was the v1 May 16 build; everything older is running pre-token-emission retry_utils.

**Highest-leverage actions** (in order):
1. Fix `_emit_token_metrics` in 5 coach Lambdas (1-line change × 5 files, then 5 redeploys) → real visibility
2. Fix coach-computation-engine TypeError → restore daily coach compute
3. Add metric_hint whitelist validation in coach_state_updater post-LLM → unblock prediction loop verdicts
4. Promote field-notes-generate, brittany_email, site_api_ai to retry_utils and re-deploy with layer → token telemetry on 3 more Lambdas
5. Decide on the unused coach-quality-gate: wire it into the daily-brief flow OR delete

**v1 drift:** P1.9 (token telemetry) is half-shipped. P3.4 (retry coverage) is partially shipped (field-notes not deployed). P3.8 (shared-preamble cache) is wired but unverifiable. P5.5 (quality gate retry) never started. P5.6 (COACH# write expansion) never started. ADR-055 (prediction evaluator) is running but 100% inconclusive.

---

## CRITICAL FINDINGS

### CRIT-AI-1: coach-computation-engine 100% failure rate for ≥7 days
**Evidence:** 7 invocations / 7 errors in last 7d (CloudWatch). Log shows `TypeError: can't compare offset-naive and offset-aware datetimes` at `coach_computation_engine.py:1045` (`if lookback_dt < experiment_start_dt:`). Errors observed 2026-05-11, 12, 13, and continuing — daily failure since at least May 11.
**Impact:** The coach computation engine — which feeds `COACH#computation/RESULTS#*` records consumed by narrative orchestrator — writes nothing. All coach narratives operate on stale/missing computed data. Probable contributor to the prediction-loop 100%-inconclusive rate.
**Action:** At `coach_computation_engine.py:1045`, ensure both datetimes have tzinfo. Either:
```python
if lookback_dt.tzinfo is None: lookback_dt = lookback_dt.replace(tzinfo=timezone.utc)
if experiment_start_dt.tzinfo is None: experiment_start_dt = experiment_start_dt.replace(tzinfo=timezone.utc)
```
**Effort:** XS (5 min). **Risk:** None (one branch). **$/mo:** non-monetary; restores coach intelligence value.

### CRIT-AI-2: Coach prediction loop produces 0 confirmed / 0 refuted across 787 predictions
**Evidence:** DDB scan of `PREDICTION#*` items: 283 inconclusive, 504 pending, 0 confirmed, 0 refuted. Outcome notes show `reason: "No data available for metric '<prose>'"`. Examples of extracted `metric_hint` from physical_coach 2026-05-17: `weight_trend_slope`, `caloric_intake_vs_movement_volume_correlation`, `hormonal_markers_over_time` — none in the 17-canonical-string whitelist defined at `coach_state_updater.py:448-456`.
**Impact:** v1 ADR-055 "prediction validation loop" produces no verdicts → coach hit_rate is permanently null → no track-record gate can fire → the entire learning loop is theatrical.
**Action:** In `coach_state_updater.py` after LLM extraction, validate `metric_hint` against the canonical whitelist; if not in list, force to `null` and downgrade prediction to qualitative. Add a CloudWatch metric `MetricHintRejected` to monitor rate.
**Effort:** S (1 hour). **Risk:** Will surface previously-hidden "predictions don't map" rate — but that's the point. Existing 504 pending records won't retroactively resolve; only new predictions benefit.

### CRIT-AI-3: Cache metrics dropped on floor in 5 coach Lambdas (`_emit_token_metrics` bug)
**Evidence:** Each of `coach_state_updater.py:218`, `coach_narrative_orchestrator.py:140`, `coach_ensemble_digest.py:140`, `coach_history_summarizer.py:159`, `coach_quality_gate.py:130` defines a local `_emit_token_metrics(input_tokens, output_tokens)` with a 2-arg signature that ignores `cache_creation_input_tokens` and `cache_read_input_tokens`. The Anthropic API IS returning them (log shows `cache_creation: 0, cache_read: 0`). The local emitter drops the cache fields even when non-zero. `LifePlatform/AI` namespace has zero datapoints for `AnthropicCacheReadTokens` / `AnthropicCacheWriteTokens` across all dimensions in 30d.
**Impact:** Cannot measure cache hit rate. Cannot quantify cache savings. Cannot detect when caching breaks. The v1 P1.9 telemetry rollout looks shipped but is functionally blind to cache.
**Action:** Replace local 2-arg `_emit_token_metrics` in those 5 files with the shared `retry_utils._emit_token_metrics` (4-arg). Or extend each local copy to accept and emit cache_creation/cache_read. Then redeploy.
**Effort:** S (1 hour for 5 files + 5 deploys). **Risk:** None — just adds metric datapoints.

### CRIT-AI-4: field-notes-generate stale deploy — v1 P3.4 retry_utils integration NOT actually shipped
**Evidence:** `aws lambda get-function-configuration --function-name field-notes-generate` → `LastModified: 2026-04-10T03:23:29Z`. CodeSize 4350 bytes. No layer attached. Yet `lambdas/field_notes_lambda.py:284` reads `from retry_utils import call_anthropic_raw` (added 2026-05-16 per comment). Deployed code is 5+ weeks stale; the May 16 P3.4 fix has never been pushed to this function. Lambda still runs successfully because the deployed code presumably uses the old urllib pattern without `retry_utils`.
**Impact:** No retry, no token telemetry, no failure metric for field-notes-generate. Worse — proves the "deploy all touched lambdas" step was skipped during v1 close.
**Action:** Run `bash deploy/deploy_lambda.sh field-notes-generate` after attaching the shared layer.
**Effort:** XS. **Risk:** None — strictly adds resilience.

---

## HIGH FINDINGS

### HIGH-AI-1: Only 2 of 22 AI-calling Lambdas emit ANY token metrics
**Evidence:** `aws cloudwatch list-metrics --namespace LifePlatform/AI` returns dimensions only for `daily-brief` and `coach-state-updater`. Checked 20 other lambdas: `nutrition-review`, `wednesday-chronicle`, `monday-compass`, `weekly-digest`, `monthly-digest`, `anomaly-detector`, `hypothesis-engine`, `ai-expert-analyzer`, `challenge-generator`, `brittany-weekly-email`, `weekly-plate`, `journal-enrichment`, `journal-analyzer`, `daily-insight-compute`, `coach-ensemble-digest`, `coach-history-summarizer`, `coach-narrative-orchestrator`, `coach-quality-gate`, `coach-prediction-evaluator`, `field-notes-generate` — all 0 metrics.
**Root causes:**
- Some don't actually call Anthropic (coach-quality-gate has 0 invocations this week, coach-prediction-evaluator doesn't call API).
- Some short-circuit before AI (anomaly-detector "Flagged metrics: 0" most runs; daily-insight-compute "IC-8: No intention data — skipping" 5/6 daily runs).
- Some have local `_emit_token_metrics` 2-arg bug (CRIT-AI-3).
- Several build their own urllib.Request and call `retry_utils.call_anthropic_raw` correctly (e.g. anomaly-detector at line 437) — but the metric isn't visible. Possibility: requests fail before usage emission.
**Action (in order):**
1. Audit each silent Lambda to confirm whether it invoked Anthropic in last 7d (check logs for `urlopen` or HTTP 200).
2. For lambdas that DO call, fix the emission path.
3. For lambdas that don't (anomaly-detector when no anomalies, daily-insight when no intentions), this is correct — but the v1 prompt should be updated to stop calling them "AI Lambdas".
**Effort:** M (4-6 hours). **Risk:** Surfaces real spend that was previously hidden — net positive but a "surprise me" moment when total AI spend doubles in the observability dashboard.

### HIGH-AI-5: coach-state-updater 17% error rate from unparseable LLM output
**Evidence:** 64 invocations / 11 errors last 7d. Sample errors: `ValueError: could not convert string to float: '40%'` (line 857), `LLM extraction failed for explorer_coach: substring not found`. Haiku is returning percentages with `%` suffix and the code does naked `float(confidence_stated)`.
**Action:** At line 857, sanitize: `float(str(confidence_stated).rstrip('%').strip()) / (100 if '%' in str(confidence_stated) else 1)` then clamp [0,1]. Default to 0.5 on parse fail.
**Effort:** XS. **Risk:** None. **Side effect:** ~11 lost extractions/week become recovered.

### HIGH-AI-6: coach-history-summarizer 100% error + 120s timeout
**Evidence:** 3 invocations / 3 errors / 120,000ms duration each (= timeout) last 7d. Burning ~$0.005 of Lambda compute per failed run, plus presumably some Anthropic input tokens that were charged but threw away.
**Action:** Read recent error logs; either fix the actual bug or shorten the analyzer query window so it completes within 60s. If not load-bearing, disable the schedule.
**Effort:** S. **Risk:** Diagnosing requires looking at the actual exception (logs filter rejected my regex).

### HIGH-AI-7: coach-quality-gate built, deployed, never invoked (0 calls in 7d)
**Evidence:** 656 LOC, deployed 2026-05-16 on layer v43. `aws cloudwatch get-metric-statistics ... Invocations` = 0 last 7d. No caller in `lambdas/*` references it directly. Code reads voice spec, scores quality, returns advisory report — but nothing's calling it.
**Action:** Either (a) wire into daily-brief or coach_narrative_orchestrator post-generation, or (b) delete the file + CDK definition + IAM role. Don't leave dead infrastructure.
**Effort:** S to wire, XS to delete. **Risk:** Wiring adds a Haiku call per coach output (~$0.005 each).

### HIGH-AI-8: site_api_ai handles `/api/ask` and `/api/board_ask` WITHOUT retry_utils, telemetry, or caching for `/api/ask`
**Evidence:** `site_api_ai_lambda.py:516-528` uses raw `urllib.request.urlopen` with no retry, no token emission, no cache_control on system. board_ask DOES use cache_control (line 606-610, per-persona) but no retry. The lambda is intentionally layer-less for cold-start performance (per inline comment line 622-627). board_ask costs ~6 Haiku calls per public request.
**Impact:** Public AI endpoints have no token observability at all. Cannot bound spend if abused. Cannot detect 429s.
**Action:** Add minimal `_emit_token_metrics()` helper inside site_api_ai (don't add layer) — copy ~30 lines from retry_utils. Then both /api/ask and /api/board_ask emit per-endpoint metrics. Add cache_control to /api/ask system prompt (it's currently a string, not a content block).
**Effort:** S. **Risk:** XS extra latency (one extra put_metric_data call).

### HIGH-AI-9: Daily-brief shared-preamble cache savings unverifiable + likely not firing
**Evidence:** Code at `daily_brief_lambda.py:1734` calls `ai_calls.daily_brief_shared_system(...)` and passes to 4 sequential AI calls. `ai_calls.py:1214-1218` properly forwards cache_creation/cache_read to `_emit_token_metrics`. Despite this, **0 datapoints exist** for `AnthropicCacheReadTokens` dimension `daily-brief` in 30 days. Either (a) the preamble is below Sonnet's 1024-token cache threshold, (b) the 4 calls aren't hashing the same content (e.g. drift in shared_system across calls), (c) emitter call path silently skips, or (d) the assistant role injection or day_grade interpolation invalidates cache.
**Impact:** Can't confirm the ~$1.50-2/month savings claim from v1 P3.8.
**Action:** Add a log line in `ai_calls.call_anthropic` that prints `cache_creation/cache_read/input` per call so we can see in CloudWatch Logs Insights whether caching fires. Also count the token size of `daily_brief_shared_system()` output to verify it exceeds the cache threshold.
**Effort:** XS for log; S for diagnosis. **Risk:** None.

### HIGH-AI-10: Layer drift — 17 Lambdas (16 no layer + 1 v2 garmin) running stale or no shared utils
**Evidence:**
- v50 (1): ai-expert-analyzer
- v49 (6): eightsleep, habitify, strava, todoist, whoop, withings ingestion (SIMP-2 cohort)
- v43 (46): main v1 cohort, May 16 build
- v25 (3): life-platform-site-api, og-image-generator, site-stats-refresh
- v2 (1): garmin-data-ingestion
- No layer (16): email-subscriber, field-notes-generate, health-auto-export-webhook, insight-email-parser, journal-analyzer, life-platform-data-export, life-platform-data-reconciliation, life-platform-delete-user-data, life-platform-dlq-consumer, life-platform-key-rotator, life-platform-mcp, life-platform-mcp-warmer, life-platform-pip-audit, life-platform-qa-smoke, life-platform-site-api-ai, pipeline-health-check

**Impact:** Each older layer version misses retry_utils improvements. journal-analyzer last deployed 2026-03-31 — predates v1 entirely. Cannot use shared modules without rebuilding their deployment.
**Action:** Phase: (1) bump v25/v43/v49 cohorts to v50 in one CDK deploy after verifying retry_utils backward compat. (2) For 16 layer-less Lambdas, decide each: do they need shared utils or not? If not (mcp, site-api), document with ADR; if yes (journal-analyzer, field-notes), attach v50 layer.
**Effort:** M-L. **Risk:** v43 → v50 might break older callers if retry_utils signature changed; verify before rolling.

### HIGH-AI-11: Anthropic 429 rate limits hitting daily-brief
**Evidence:** 6 events with "429" string in daily-brief logs last 7d. Not zero. retry_utils handles them, but they indicate we're brushing tier limits.
**Action:** No immediate action — backoff is working. But worth tracking: add `AnthropicAPIFailure` to a CloudWatch alarm (which currently has 0 datapoints because the metric is never emitted — see CRIT-AI-3).
**Effort:** XS once telemetry is fixed.

---

## MEDIUM FINDINGS

### MED-AI-1: daily-insight-compute fires 6x/day but does meaningful work ≤1x
**Evidence:** Logs show 5 of 6 daily invocations are 1-2ms (early-exit "No intention data — skipping"). One ~800ms invocation/day actually runs IC-8 evaluation.
**Impact:** Wastes 5 Lambda invocations/day (~$0.001/mo, trivial) but also means the schedule is misconfigured — should run once at the time intention data is reliably present.
**Action:** Move schedule from 6x/day to 1x/day at 17:30 UTC (after Notion + Apple Health ingestion completes). Reduces noise and clarifies intent.
**Effort:** XS (CDK schedule change).

### MED-AI-2: Hardcoded model strings + no AI_MODEL env vars on any Lambda
**Evidence:** None of daily-brief, weekly-digest, monday-compass, wednesday-chronicle, monthly-digest have AI_MODEL or AI_MODEL_HAIKU env vars set. All use code defaults (Sonnet 4.6 / Haiku 4.5). ADR-049 documents model tiering but operationally only the source default is used. Means model upgrades require a code change + redeploy, not an env-var flip.
**Action:** Add `AI_MODEL` and `AI_MODEL_HAIKU` as defaulted env vars in each Lambda's CDK definition. Enables "test new model on 1 Lambda by changing env var" workflows.
**Effort:** S (CDK + redeploy). **Risk:** None.

### MED-AI-3: brittany-weekly-email has custom 2-attempt retry — bypasses shared retry_utils
**Evidence:** `brittany_email_lambda.py:472-484` uses inline 2-attempt loop with hardcoded 5s sleep. Not using retry_utils (which has 4 attempts with 5/15/45s backoff). Hardcoded model `claude-sonnet-4-6` (line 463) — no AI_MODEL env override.
**Action:** Replace with `from retry_utils import call_anthropic_raw`. Also adds telemetry.
**Effort:** XS. **Risk:** None.

### MED-AI-4: Patches dir has 52 files — README says safe to delete but no action taken
**Evidence:** 52 files in `patches/`, mostly `patch_*.py` historical one-shots. `patches/README.md` says "Safe to delete if you accept losing the audit trail; nothing here is imported or scheduled." v1 claimed 51 — actually 52 (drift count, harmless).
**Action:** Move all `patches/patch_*.py` older than 60 days into `patches/archive/2026Q1/` and leave only the last 10. The git history preserves the audit trail.
**Effort:** XS (one mv command). **Risk:** None (no imports).

### MED-AI-5: site_api_lambda has 2 Anthropic call sites at lines 2819, 7841 with no retry / no telemetry
**Evidence:** `site_api_lambda.py:2819, 7841` use raw urlopen. Different from site_api_ai (which is a separate Lambda) — these are inside the main site_api lambda. Not behind rate limit at the lambda level.
**Action:** Migrate both to retry_utils. site_api is on layer v25 so needs layer bump to v50 first.
**Effort:** S. **Risk:** Layer bump may surface other compat issues; test in isolation.

### MED-AI-6: 5 long-standing CloudWatch alarms in ALARM state since May 3-4 (2 weeks)
**Evidence:** `ingestion-error-whoop`, `life-platform-dlq-depth-warning`, `life-platform-garmin-data-ingestion-errors`, `og-image-generator-errors`, `slo-source-freshness` — all ALARM since 2026-05-03/04. Either the underlying issue is unaddressed or these alarms are noise that should be re-tuned.
**Action:** Triage each: fix underlying issue or raise threshold / extend evaluation period. Don't leave alarms in ALARM state indefinitely.
**Effort:** S each.

### MED-AI-7: Compute Lambda docstring drift in compute_stack.py
**Evidence:** `cdk/stacks/compute_stack.py:9-17` documents the schedules as "17:35-17:50 UTC" but actual schedules (lines 89-133) are "16:30-16:50 UTC" — the Phase 3.1 race fix updated cron but not the header comment. Future reader will be confused.
**Action:** Update the docstring at lines 9-17 to match actual cron expressions.
**Effort:** XS.

### MED-AI-8: Daily-brief journal coach BLOCKED for empty output
**Evidence:** Daily-brief 2026-05-17 log: `[ai_validator] BLOCKED empty output: AIOutputType.JOURNAL_COACH`. The journal coach call returned empty text. AI-3 validator blocked it. Not a regression but indicates the journal coach is failing silently at the AI layer when journal entries are sparse.
**Action:** In `ai_calls.call_journal_coach`, log the input context size and raise a warning when the response is empty so we can debug; consider returning a stub "no journal activity" sentence instead of empty.
**Effort:** XS.

---

## LOW FINDINGS

### LOW-AI-1: 16 layer-less Lambdas may or may not need the shared layer — undocumented
**Action:** Add a column to `cdk/` indicating each Lambda's layer policy.

### LOW-AI-2: Backfill dir is well-managed with README
**Evidence:** 8 scripts in `backfill/`, README clearly says "Never delete after run." Headers in each script are explicit. No action needed.

### LOW-AI-3: Cost benchmarking — daily-brief is top spender at ~$6.40/mo
**Evidence:** From observed CloudWatch token totals × Sonnet pricing.
- daily-brief: $6.40/mo (4 Sonnet calls × 365)
- coach-state-updater: $0.51/mo (Haiku, many small calls)
- Other 20 lambdas: unknown but estimated $5-15/mo combined based on invocation counts
**Top 3 spenders (best estimates):**
1. daily-brief ($6.40/mo Sonnet)
2. coach-narrative-orchestrator (56 invocations × ~3-5 Haiku calls each, ~$2-3/mo)
3. weekly-digest + monthly-digest + monday-compass + wednesday-chronicle (Sonnet weekly, ~$2-4/mo combined)

**Reduction levers per top 3:**
- daily-brief: fix shared-preamble cache properly (~$2/mo if 75% hit rate on system tokens)
- coach-narrative-orchestrator: it's Haiku already; trim brief prompt size if possible
- digests: switch monday-compass/wednesday-chronicle to Haiku for narrative tightening pass; Sonnet only for the lead

---

## DRIFT CHECK: v1 items VERIFIED

| v1 Item | Status | Notes |
|---|---|---|
| Coach prediction evaluator (ADR-055, 982 LOC) | SHIPPED CODE / FAILING BY DESIGN | Runs daily, 100% inconclusive verdicts because metric_hint not enforced |
| Token telemetry (P1.9, all AI Lambdas) | PARTIAL | 2 of ~22 Lambdas emit; cache metrics dropped via `_emit_token_metrics` bug |
| Prompt caching (12 + 7 Lambdas) | UNVERIFIABLE | Cache metrics absent from CloudWatch; logs show coach-state-updater always cache_read=0 |
| SIMP-2 ingestion framework (8 Lambdas) | SHIPPED | All 6 SIMP-2 cohort Lambdas on layer v49 (newer than main cohort) |
| Shared preamble cache (P3.8 daily-brief) | WIRED, UNVERIFIED | Code calls correctly; no telemetry confirms cache hits |
| Retry rollout via retry_utils (P3.4) | PARTIAL | field-notes-generate not redeployed; brittany-email still custom 2-attempt |
| run_id idempotency observability (P3.3) | SHIPPED | character_sheet, daily_metrics, adaptive_mode all tagged via compute_metadata.tag_record |
| Coach state writing expansion (P5.6) | NOT SHIPPED | journal_enrichment, hypothesis_engine, challenge_generator, anomaly_detector all have 0 `COACH#` write references |
| Coach quality gate retry (P5.5) | NOT SHIPPED | Still advisory-only per `coach_quality_gate.py` — and not even invoked |
| DDB rate limiting (P2.1) | SHIPPED | site_api_ai uses `rate_limiter` module with DDB-backed check (line 552-563) |

---

## FAILED-BY-DESIGN PIPELINES (explicit list)

1. **Coach prediction evaluator → 100% inconclusive** — metric_hint not in canonical whitelist (CRIT-AI-2)
2. **Coach computation engine → 100% error** — TypeError datetime compare crashes every daily run (CRIT-AI-1)
3. **Coach quality gate → 0 invocations** — never wired to a caller (HIGH-AI-7)
4. **Coach state updater → 17% error rate** — unparseable LLM output (HIGH-AI-5)
5. **Coach history summarizer → 100% error + 120s timeout** (HIGH-AI-6)
6. **Cache metrics → 0 datapoints** — emitter bug + possibly sub-threshold prompts (CRIT-AI-3)
7. **Daily-insight-compute → 5/6 invocations are heartbeat-only no-ops** (MED-AI-1)
8. **Field-notes-generate → P3.4 fix never deployed** — stale April 9 lambda (CRIT-AI-4)
9. **20 of 22 AI Lambdas → invisible AI spend** — no telemetry (HIGH-AI-1)
10. **5 CloudWatch alarms in ALARM since 2 weeks** — chronic, unaddressed (MED-AI-6)

---

## DATA-BLOCKED / TIME-BLOCKED ITEMS

- **Coach hit_rate threshold tuning** (v1 next step): blocked until CRIT-AI-2 ships and 30-60 days of confirmed/refuted verdicts accumulate. As of 2026-05-17, hit_rate = null for all coaches because verdict counts are zero.
- **Cache savings quantification**: blocked until CRIT-AI-3 fixed and 7 days of cache metrics accumulate.
- **Real per-Lambda AI spend ranking**: blocked until HIGH-AI-1 fixed for at least 6 silent Lambdas.

---

## PROPOSED EXECUTION ORDER (top-leverage first)

1. **CRIT-AI-1** (5 min) — Fix coach-computation-engine datetime bug. Restores daily coach compute.
2. **CRIT-AI-3** (1 hr) — Fix `_emit_token_metrics` in 5 coach files. Restores cache observability.
3. **CRIT-AI-4** (10 min) — Redeploy field-notes-generate with layer.
4. **HIGH-AI-5** (15 min) — Fix coach-state-updater `float('40%')` crash. Reduces error rate from 17% to ~0.
5. **CRIT-AI-2** (1 hr) — Whitelist enforcement for metric_hint in coach_state_updater. Unblocks prediction loop.
6. **HIGH-AI-1** (4 hrs) — Roll out telemetry to silent Lambdas. Quantifies real spend.
7. **HIGH-AI-7** (30 min) — Decide on coach-quality-gate: wire or delete.
8. **HIGH-AI-9 / HIGH-AI-10 / HIGH-AI-11** — caching deep-dive + layer normalization + 429 alerting (longer-tail work).
9. **MED-AI-X** — schedule normalization, model env vars, alarm cleanup.

Total estimated effort for top 5: **~3 hours**. Yields restored coach compute, restored prediction verdicts, restored cache observability, restored field-notes telemetry — i.e., most of what v1 claimed but didn't actually achieve.
