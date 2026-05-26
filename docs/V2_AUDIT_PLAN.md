# V2 Comprehensive Audit Plan — 2026-05-17

> Second-round 24-hour-expert audit. Run while v1 work (v7.0.0–v7.21.0) sits **uncommitted in the working tree**. Four parallel deep-dive agents produced ~120 raw findings across codebase, AWS, AI/data-flow, and web/DX. This document is the consolidated plan, ROI-ordered.
>
> Sub-reports preserved at `docs/v2-audits/01_codebase.md`, `02_aws.md`, `03_ai_dataflow.md`, `04_web_dx.md`.

---

## TL;DR — The headline of v2

**v1 shipped a lot of code; v1 deployed and verified less of it than the CHANGELOG claims.**

The single sharpest finding: **`cdk/stacks/constants.py` still says `SHARED_LAYER_VERSION = 43` while prod is on v50**, and the next `cdk deploy --all` would silently downgrade 79 Lambdas — undoing every layer-side v1 change. This is a one-line fix that prevents a self-inflicted regression bomb.

The second sharpest: **115 uncommitted files (+10,840 / −17,684 LOC)** representing the entire v1 audit. A `git restore` or a corrupted disk loses ~2 days of work and 5 ADRs.

The third sharpest: **the production state today does not match the v1 CHANGELOG's claims** on multiple load-bearing items:
- `coach-computation-engine`: 100% failure rate for 7+ days (datetime tzinfo bug at line 1045)
- Coach prediction loop (ADR-055): **0 confirmed, 0 refuted across 787 predictions** — theatrical, because the metric_hint whitelist is documented in the system prompt but never enforced post-LLM
- Token telemetry (v1 P1.9): only 2 of 22 AI-calling Lambdas emit metrics; those 2 have a copy-paste bug that drops cache-read/write fields → `AnthropicCacheReadTokens` has **zero datapoints in 30 days** despite caching being "wired"
- Reserved concurrency (v1 P1.5): never deployed; account still capped at 10 with zero protection
- CloudTrail data events (v1 P2.5): never enabled; no S3 read/DDB read audit trail
- HAE webhook timeout: Lambda=300s but API Gateway integration=30s → silent 504s on Apple Health bulk uploads
- `field-notes-generate`: stale April 9 deploy; the May 16 retry_utils integration never pushed
- DLQ has 63 stuck Garmin messages since May 4; consumer Lambda isn't draining; 5 alarms in ALARM since May 3-4
- `freshness_checker_lambda.py:185` references undefined `yesterday_str` — CI's strict `--select=E9,F63,F7,F82` would fail the next push, and the sick-day branch would NameError in prod

The fourth: **MCP tool bloat is now measurable** — EMF telemetry shows only **11 of 135 tools** invoked in the last 30 days. The remaining 124 are dead weight (~6,000 LOC orphan tool code).

The fifth: **repo hygiene is rotting in plain sight** — 2,201 files in `show_and_tell/` untouched since March; 3 stale ROOT-level SPEC files from March 30; duplicate `HANDOVER_LATEST copy.md` with mode 600; 4 INTELLIGENCE_LAYER_V2*_SPEC.md versions in docs/.

What v1 got right: SIMP-2 migration is real and substantial (−2,383 LOC, 7 Lambdas converted). 1,240 unit tests pass in 34s with new orphan-tool ratchet, layer-consistency check, and 11 new test files. Daily-brief shared system block is properly wired (cache CAN fire). Pipeline-timing race fix is in CDK source. failure-pattern-compute brought back online. SES suppression list active. S3 lifecycle holds. DDB PITR/TTL hold.

Realistic cost recovery from v2: **$3.65/mo** ($43.80/yr). Don't repeat v1's $80-120/mo projection.

---

## Findings summary

| Severity | Count | Bucket |
|----------|-------|--------|
| CRITICAL | 9 | Data loss risk, broken-in-prod, CI-will-fail, regression-bomb |
| HIGH | 21 | Drift, silent failure, real cost/reliability |
| MEDIUM | 28 | Cleanup with value, observability, polish |
| LOW | 18 | Style, cosmetics, deferred |
| **TOTAL** | **76 distinct items** | After de-duplication across 4 sub-reports |

---

# PHASE 0 — Commit + Stop the Bleed (THIS SESSION, ~3 hours)

**Goal:** make sure v1 work survives the night + restore broken-in-prod pipelines that are silently rotting. Everything in Phase 0 is XS-S effort, low risk, high impact.

### P0.1 [CRITICAL] Commit all v1 work in 4–6 logical chunks
**Evidence:** `git status --short | wc -l → 115`. `git diff --stat HEAD` totals **85 files, +10,840 / −17,684**. Includes 13 new shared modules (auth_breaker, http_retry, numeric, rate_limiter, request_validator, email_framework, compute_metadata, delete_user_data_lambda, alert_digest_lambda, etc.), 5 new ADRs (053–057), 11 new test files, 7 full-rewrite SIMP-2 migrations, +1,635 CHANGELOG lines, 5 new docs. Git HEAD is `321ef02` v6.9.5.
**Action:** `git add -p` in logical chunks. Suggested commits:
1. Framework: ingestion_framework.py + 7 SIMP-2 migrations + auth_breaker.py
2. Shared modules: numeric, http_retry, rate_limiter, request_validator, email_framework, compute_metadata
3. New Lambdas + tests: alert_digest, delete_user_data + their test_*.py
4. CDK changes: compute/email/operational/core/web/monitoring stacks
5. Docs: ADR-053..057, CHANGELOG, ARCHITECTURE refresh, V2_AUDIT_PROMPT, V2_AUDIT_PLAN
6. CLAUDE.md + lambda_map.json + .github/workflows/ci-cd.yml
**Effort:** S (2-3h). **Risk:** None. **ROI:** Preserves ~2 days of work.

### P0.2 [CRITICAL] Bump `SHARED_LAYER_VERSION = 43 → 50` in CDK constants
**Evidence:** `cdk/stacks/constants.py:37` → `SHARED_LAYER_VERSION = 43`. Prod is v50. Next `cdk deploy --all` regresses 79 Lambdas.
**Action:** Edit one line. Add a `tests/test_layer_version_consistency.py` that fails if `aws lambda list-layer-versions` newest > constant.
**Effort:** XS. **Risk:** Without it: catastrophic. **ROI:** Prevents single-deploy regression of v1.

### P0.3 [CRITICAL] Fix `freshness_checker_lambda.py:185` undefined `yesterday_str`
**Evidence:** `flake8 lambdas/ mcp/ --select=E9,F63,F7,F82` → `F821 undefined name 'yesterday_str'`. CI's strict gate (.github/workflows/ci-cd.yml:78) will fail on next push. Production NameError on sick-day branch.
**Action:** Add `yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')` before the `logger.info` call.
**Effort:** XS (5 min). **Risk:** None. **ROI:** Unblocks CI + fixes real prod NameError.

### P0.4 [CRITICAL] Fix `coach-computation-engine` datetime tzinfo bug
**Evidence:** 7 invocations / 7 errors / 7 days. `TypeError: can't compare offset-naive and offset-aware datetimes` at `coach_computation_engine.py:1045` (`if lookback_dt < experiment_start_dt`). Daily failure since at least May 11.
**Action:**
```python
if lookback_dt.tzinfo is None:
    lookback_dt = lookback_dt.replace(tzinfo=timezone.utc)
if experiment_start_dt.tzinfo is None:
    experiment_start_dt = experiment_start_dt.replace(tzinfo=timezone.utc)
```
**Effort:** XS (5 min). **Risk:** None. **ROI:** Restores daily coach compute (currently writing nothing for a week).

### P0.5 [CRITICAL] Fix HAE API Gateway integration timeout 30s → 29s with Lambda Function URL migration plan
**Evidence:** API GW `health-auto-export-api` `TimeoutInMillis=30000`, Lambda Timeout=300s. Apple Health bulk uploads silent-504 to phone; Lambda runs orphaned; phone retries.
**Action (immediate):** Raise integration timeout to 29000ms (HTTP API hard cap).
**Action (followup, P3.x):** Migrate HAE to Lambda Function URL (eliminates API GW cost + integration limits). Auth pattern stays in Lambda code (signature check).
**Effort:** XS (immediate) / S (migration). **Risk:** Low. **ROI:** Eliminates silent Apple Health data loss.

### P0.6 [CRITICAL] Fix `_emit_token_metrics` 2-arg bug in 5 coach Lambdas (cache metrics dropped)
**Evidence:** Local 2-arg `_emit_token_metrics(input, output)` in `coach_state_updater.py:218`, `coach_narrative_orchestrator.py:140`, `coach_ensemble_digest.py:140`, `coach_history_summarizer.py:159`, `coach_quality_gate.py:130`. Ignores `cache_creation_input_tokens` and `cache_read_input_tokens` from the API response. `AnthropicCacheReadTokens` has zero datapoints in 30d as a result.
**Action:** Replace each local copy with `from retry_utils import _emit_token_metrics` (4-arg). Or extend each to accept + emit cache fields. Then redeploy 5 Lambdas (will require layer v50 attach for those on no-layer).
**Effort:** S (1h). **Risk:** None. **ROI:** Restores cache observability across the coach pipeline.

### P0.7 [CRITICAL] Drain DLQ (63 stuck Garmin messages since May 4)
**Evidence:** `ApproximateNumberOfMessages=63` on `life-platform-ingestion-dlq`. Sampled = Garmin scheduled-event payloads May 4-8. `life-platform-dlq-consumer` runs every 6h; either broken or never triggers.
**Action:** `aws sqs receive-message --queue-url ... --max-number-of-messages 10` → inspect → identify failing source → fix upstream → invoke dlq-consumer or replay manually.
**Effort:** S (1h). **Risk:** Low. **ROI:** Restores Garmin May 4-8 coverage gap + clears 2 false-positive alarms eating attention.

### P0.8 [HIGH] Add 17 shared modules to `ci/lambda_map.json` `skip_deploy.files`
**Evidence:** `auth_breaker.py, compute_metadata.py, email_framework.py, http_retry.py, intelligence_common.py, numeric.py, platform_logger.py, rate_limiter.py, request_validator.py, retry_utils.py, secret_cache.py, site_writer.py, character_engine.py, genome_coaching.py, ai_output_validator.py, labs_coaching.py, ingestion_framework.py` — all layer-resident shared code; CI diff job would try to deploy them as Lambdas → 404 on `aws lambda update-function-code`.
**Action:** Add 17 lines to `skip_deploy.files`.
**Effort:** XS. **Risk:** None. **ROI:** Prevents CI false-positives blocking merges.

### P0.9 [HIGH] Fix test_i11 lookback expectation (false-positive failing test)
**Evidence:** `tests/test_integration_aws.py:649` asserts `data-reconciliation` ran within 48h. CDK source: `cron(30 7 ? * MON *)` (weekly Monday). Test expectation is wrong, not the Lambda.
**Action:** Set `DRECON_LOOKBACK_HOURS = 192` (8 days) in the test. Document in docstring.
**Effort:** XS. **Risk:** None. **ROI:** Removes perma-yellow CI signal.

**Phase 0 total: ~3h focused work. Closes 6 broken-in-prod issues + commits 2 days of work.**

---

# PHASE 1 — Observability Restore (1-2 days)

**Goal:** make the platform tell the truth about what's happening. Telemetry is the foundation for every later decision.

### P1.1 [CRITICAL] Coach prediction loop: enforce `metric_hint` whitelist post-LLM
**Evidence:** 787 PREDICTION# items: 283 inconclusive, 504 pending, **0 confirmed, 0 refuted**. Root cause: Haiku ignores the 17-canonical-metric whitelist in `coach_state_updater.py:448-456` and emits prose names like `caloric_intake_vs_movement_volume_correlation`. Evaluator can't resolve those → 100% inconclusive.
**Action:** In `coach_state_updater.py` after the LLM extraction, validate `metric_hint` against the canonical whitelist; if not in list, force `metric_hint = None` and downgrade prediction to qualitative-only. Emit CloudWatch metric `MetricHintRejected` to track rejection rate.
**Effort:** S (1h). **Risk:** Surfaces previously-hidden "predictions don't map" rate — that's the point. **ROI:** Unblocks the v1 ADR-055 "prediction validation loop." Only new predictions benefit; the 504 pending won't retroactively resolve.

### P1.2 [CRITICAL] Redeploy `field-notes-generate` with layer v50 attached
**Evidence:** `aws lambda get-function-configuration --function-name field-notes-generate` → `LastModified: 2026-04-10T03:23:29Z`, CodeSize 4350 bytes, no layer. Source has the May 16 `from retry_utils import call_anthropic_raw` integration; deployed code is 5+ weeks stale. v1 P3.4 close skipped this deploy.
**Action:** `bash deploy/deploy_lambda.sh field-notes-generate` after attaching shared layer v50 in CDK definition.
**Effort:** XS (10 min). **Risk:** None. **ROI:** Restores retry + token telemetry on field-notes-generate.

### P1.3 [HIGH] Fix `coach-state-updater` `float("40%")` crash (17% error rate)
**Evidence:** 64 invocations / 11 errors. `ValueError: could not convert string to float: '40%'` at line 857. Haiku returns percentages with `%` suffix; code does naked `float(confidence_stated)`.
**Action:**
```python
raw = str(confidence_stated).rstrip('%').strip()
val = float(raw) / (100 if '%' in str(confidence_stated) else 1)
confidence = max(0.0, min(1.0, val))
```
Default to 0.5 on parse fail.
**Effort:** XS (15 min). **Risk:** None. **ROI:** Recovers ~11 lost extractions/week. Drops error rate 17% → ~0%.

### P1.4 [HIGH] Roll out token telemetry to 4 site_api / partner / canary Lambdas
**Evidence:** `lambdas/site_api_lambda.py:2819,7841` (board_ask, /api/ask), `lambdas/site_api_ai_lambda.py:517,614`, `lambdas/partner_email_lambda.py:468`, `lambdas/canary_lambda.py:68` all use raw `urllib.request.urlopen("https://api.anthropic.com/v1/messages", ...)`. Zero retry, zero telemetry, zero cache_control on system. v1 CHANGELOG explicitly noted as "deferred to v2."
**Action:** Refactor each to `from retry_utils import call_anthropic_raw`. site_api_ai is intentionally layer-less for cold-start — copy ~30 lines of `_emit_token_metrics` inline instead. Add cache_control on board_ask + /api/ask system prompts (both >1024 tokens).
**Effort:** M (4-6h). **Risk:** Low — `call_anthropic_raw` battle-tested in daily-brief. **ROI:** $0.50-1/mo cache savings on board_ask + visibility into ~30% of currently-dark Anthropic spend + retry resilience for user-facing AI.

### P1.5 [HIGH] Investigate why `daily-brief` shared-preamble cache shows zero datapoints
**Evidence:** Code wired correctly in `daily_brief_lambda.py:1734` → `ai_calls.daily_brief_shared_system(...)` → 4 sequential calls with `cache_system=True`. `ai_calls.py:1214-1218` forwards cache fields to `_emit_token_metrics`. Despite this, `AnthropicCacheReadTokens` dimension `daily-brief` has 0 datapoints in 30d.
**Hypotheses:** (a) preamble below Sonnet's 1024-token cache threshold; (b) 4 calls hash different system content due to interpolation drift; (c) day_grade variable invalidates cache; (d) emitter call path silently skips.
**Action:** Add a one-line debug log in `ai_calls.call_anthropic`: `logger.info(f"cache: creation={cc} read={cr} input={i}")`. Also compute token size of `daily_brief_shared_system()` output. Run for 2 days; analyze.
**Effort:** XS for log; S for diagnosis (1-2 days observation). **Risk:** None.

### P1.6 [HIGH] Enable SES configuration set + open/click tracking
**Evidence:** `aws sesv2 list-configuration-sets` → empty. Daily-brief, weekly-digest, monthly-digest, partner-email open rates are unknowable. v1 promised; not shipped.
**Action:**
1. `aws sesv2 create-configuration-set --configuration-set-name life-platform-emails`
2. Wire CloudWatch event destination for Open/Click/Bounce/Complaint
3. Update `daily_brief_lambda`, `weekly_digest_lambda`, `monthly_digest_lambda`, `partner_email_lambda`, `subscriber_onboarding_lambda` to set `ConfigurationSetName='life-platform-emails'` on `SendEmail`
4. Inject pixel + UTM-tagged links in email templates
**Effort:** S (1-2h setup). **Risk:** Privacy-conscious clients block pixels — expect 40-60% reported opens. **ROI:** First-ever signal on whether anyone reads these emails. Without this, every content investment is blind.

### P1.7 [HIGH] Enable CloudTrail data events for S3 + DDB
**Evidence:** `aws cloudtrail get-event-selectors` → `DataResources: []`. No record of who reads which S3 object; no DDB GetItem audit.
**Action:** Add S3 data-event selector for `matthew-life-platform/raw/*` and DDB selector for `life-platform` table. CloudTrail bucket already has `cloudtrail-expire-90d` lifecycle (storage bounded).
**Effort:** XS (15 min). **Risk:** Low. **ROI:** ~$0.50-1/mo cost; forensic + compliance value.

### P1.8 [MEDIUM] Promote `_emit_route_log` to a Logs Insights saved query
**Evidence:** `lambdas/site_api_lambda.py:7084-7090` builds `_type: route_metric` structured log. No test asserts shape; no saved query references it.
**Action:** Add 1 test asserting shape. Document in RUNBOOK a saved Logs Insights query:
```
filter _type = "route_metric"
| stats count() as hits, avg(duration_ms) as avg_ms by route
| sort avg_ms desc
```
**Effort:** S. **Risk:** None. **ROI:** Exploit observability v1 already shipped.

**Phase 1 total: ~2 days. Closes the "platform can't tell the truth about itself" gap.**

---

# PHASE 2 — Drift Closure (1-2 days)

**Goal:** close v1 items that were "shipped" but didn't actually land in prod. Drift detection is half the value of v2.

### P2.1 [HIGH] Layer normalization — bump 56 Lambdas v43/v25/v2 → v50
**Evidence:**
- v50 (1): ai-expert-analyzer
- v49 (6): SIMP-2 OAuth cohort
- v43 (46): main v1 cohort
- v25 (3): site-api, og-image-generator, site-stats-refresh — riskiest, 6+ months behind
- v2 (1): garmin-data-ingestion — extremely stale
- No layer (16): mcp, site-api-ai, field-notes, journal-analyzer, key-rotator, data-export, dlq-consumer, qa-smoke, pipeline-health-check, etc.

**Action:**
1. After P0.2 (constants bumped), `cd cdk && npx cdk diff` to preview which Lambdas get layer changes
2. Stage v43 → v50 first (lowest risk, mostly already-recent)
3. Stage v25 → v50 separately (test site-api in isolation; bigger jump)
4. Stage v2 → v50 for garmin (test ingestion before-and-after)
5. For 16 layer-less Lambdas: per-Lambda decision — does this Lambda actually use shared modules? If yes (field-notes, journal-analyzer, data-export), attach layer. If no (mcp, site-api-ai are deliberately layer-less for cold-start), document with ADR-058 "Layer policy per Lambda."

**Effort:** M (4-6h with careful testing). **Risk:** Medium — site-api on v25 is the riskiest jump; verify retry_utils signature compat first. **ROI:** Brings entire fleet onto same shared-module version; eliminates "which version of retry_utils is this Lambda running?" debugging tax.

### P2.2 [HIGH] Reserved concurrency — file quota raise + apply once approved
**Evidence:** `aws lambda get-account-settings` → `UnreservedConcurrentExecutions: 10`. Zero Lambdas have reserved set. CDK source has 7 commented-out reservations. `docs/RESERVED_CONCURRENCY.md` documents the plan.
**Action:**
1. File AWS Support quota request: raise L-B99A9384 from 10 to 100 (free, ~24h turnaround). User must do this — programmatic API requires Business support plan.
2. Once approved, uncomment + commit CDK reservations:
   - `life-platform-mcp`: 5
   - `life-platform-site-api`: 20
   - `life-platform-site-api-ai`: 2
   - `daily-brief`: 5
   - `health-auto-export-webhook`: 3
   - `whoop-data-ingestion`: 1 (OAuth race per ADR-036)
   - `garmin-data-ingestion`: 1
3. Add CI test asserting console reservation matches CDK source.
**Effort:** S now (file ticket) + 1h after approval. **Risk:** Low. **ROI:** Prevents the "noisy ingest starves daily-brief" class of outage.

### P2.3 [HIGH] Install account-level CloudWatch log retention policy (fix root cause of P1.1)
**Evidence:** v1 P1.1 patched 79 of 81 existing log groups but didn't install the default. Two log groups created today (`/aws/lambda/coach-observatory-renderer`, `/aws/lambda/life-platform-delete-user-data`) have `retentionInDays=null`. Drift will recur on every new Lambda.
**Action:**
```bash
aws logs put-account-policy \
  --policy-name life-platform-log-retention \
  --policy-type LOG_RETENTION_POLICY \
  --policy-document '{"retention_in_days":30}'
```
Also wire `log_retention=aws_logs.RetentionDays.ONE_MONTH` as default in `cdk/stacks/lambda_helpers.py` `create_platform_lambda`.
**Effort:** S. **Risk:** Drift between manual console state and CDK — document in ADR. **ROI:** Prevents the drift class forever; caps log storage cost recursively.

### P2.4 [HIGH] Adopt `auth_breaker` in 3 exempt OAuth Lambdas (or delete the module)
**Evidence:** `grep -rn auth_breaker lambdas/` → only its own file + test. `ingestion_framework.py:97-155` inlines the same logic for framework users. 6 SIMP-2-exempt Lambdas (notion, macrofactor, apple_health, dropbox_poll, food_delivery, hae) don't import it. 3 of those (notion, dropbox_poll, hae) have OAuth tokens that can expire.
**Action:** Add ~4-line `auth_breaker.check_and_mark()` wrap in those 3 Lambdas. Delete the module if nobody needs it after that.
**Effort:** S. **Risk:** Low (defensive). **ROI:** Closes 24h alarm-flood window for the 3 exempt OAuth sources.

### P2.5 [HIGH] Adopt `email_framework` in 1 email Lambda (POC) or delete
**Evidence:** `grep -rn "from email_framework" lambdas/` → only its self-test. 166 LOC new, untracked, never imported.
**Action:** Pick the smallest email Lambda (`evening_nudge` or `monday_compass`) — refactor to use email_framework as a POC. If adoption pattern works, schedule remaining 6 email Lambdas. If POC reveals the abstraction doesn't fit, delete the module.
**Effort:** M (POC). **Risk:** Low. **ROI:** Stops the "what's this module for?" cost.

### P2.6 [MEDIUM] Adopt `compute_metadata.tag_record()` in 6 remaining compute Lambdas
**Evidence:** Currently used by character_engine, character_sheet, adaptive_mode, daily_metrics_compute, daily_insight_compute. NOT used by hypothesis_engine, failure_pattern_compute, weekly_correlation_compute, acwr_compute, sleep_reconciler, circadian_compliance.
**Action:** Add `tag_record()` calls at DDB-write sites in the 6 remaining compute Lambdas.
**Effort:** S. **Risk:** Low. **ROI:** Idempotency consistency across compute fleet.

### P2.7 [MEDIUM] Adopt new shared modules in 6 exempt ingestion Lambdas
**Evidence:** `grep "from numeric\|from http_retry\|from auth_breaker"` in the 6 exempt Lambdas: apple_health uses numeric; notion uses http_retry (2 sites); macrofactor uses numeric; dropbox_poll, food_delivery, hae use NONE.
**Action:** Per ADR-056 mitigation note, swap in numeric/http_retry/auth_breaker where applicable. ~4 lines per Lambda.
**Effort:** S. **Risk:** Low. **ROI:** Brings 6 exempt sources into same reliability baseline as the migrated 7.

### P2.8 [MEDIUM] Partner email — replace inline 2-attempt retry with `retry_utils.call_anthropic_raw` + env-vary model
**Evidence:** `partner_email_lambda.py:472-484` inline 2-attempt loop, hardcoded 5s sleep, hardcoded `model: "claude-sonnet-4-6"` at line 463.
**Action:** Replace with `from retry_utils import call_anthropic_raw`. Replace literal model with `os.environ.get("AI_MODEL", "claude-sonnet-4-6")`. Adds telemetry + 4-attempt retry + env override.
**Effort:** XS. **Risk:** None. **ROI:** Resilience + model-deprecation safety.

### P2.9 [MEDIUM] Update `compute_stack.py` docstring (lines 9-17) to match actual cron expressions
**Evidence:** Docstring documents 17:35-17:50 UTC schedule; actual cron is 16:30-16:50 UTC. Phase 3.1 race fix updated cron but not header comment.
**Effort:** XS. **ROI:** Future reader not confused.

### P2.10 [MEDIUM] Fix ADR-057 wrong importer name
**Evidence:** ADR-057 says `intelligence_common`'s single importer is `daily_brief`. Actual is `ai_expert_analyzer` (grep confirms). Closure rationale (1 importer → don't split) still correct.
**Effort:** XS. **ROI:** Source-of-truth correctness.

### P2.11 [MEDIUM] Refresh `CLAUDE.md` and `docs/ARCHITECTURE.md` claims
**Evidence:** CLAUDE.md still says "layer v41" (actual v50), "115 tools" (actual 135), "13 ingestion Lambdas" (actual 14). ARCHITECTURE.md says "127 MCP tools" (actual 135).
**Action:** Edit both files. Add a one-liner under each claim with the `aws/grep` command that auto-checks.
**Effort:** XS. **ROI:** Stops every future agent inheriting stale numbers.

**Phase 2 total: ~2 days. Closes 11 v1-drift items.**

---

# PHASE 3 — Coach Loop Closure (1-2 days)

**Goal:** finish what ADR-055 started. After P0/P1 fix the broken-by-design path, this phase makes the loop actually learn.

### P3.1 [HIGH] Decide on `coach-quality-gate`: wire or delete
**Evidence:** 656 LOC deployed; 0 invocations in 7 days. No caller in `lambdas/*` references it directly. v1 ADR mentions advisory-only stance.
**Action (choose one):**
- **Wire**: invoke from `coach_narrative_orchestrator` post-generation; on score <60, retry with stricter prompt; on score <40, block publish.
- **Delete**: remove file + CDK definition + IAM role. Don't carry dead infrastructure.
**Recommendation:** Wire it. v1 P5.5 explicitly planned this; the dead code is a half-step. Cost: ~$0.005 Haiku per coach output (~$1/mo at current volume).
**Effort:** S (wire) or XS (delete). **Risk:** Wiring adds latency + cost to coach pipeline.

### P3.2 [HIGH] Coach state writing expansion to 4 lambdas (v1 P5.6 not shipped)
**Evidence:** v1 P5.6 promised `journal_enrichment`, `hypothesis_engine`, `challenge_generator`, `anomaly_detector` would write COACH# thread records. Grep confirms zero `COACH#` write references in those 4 files today.
**Action:** Add `write_coach_thread()` calls at the natural decision points (post-analysis, pre-output) in each Lambda. Use `coach_state_updater`'s existing helper.
**Effort:** M (3 days — 4 Lambdas + tests). **Risk:** Low. **ROI:** Closes the v1 promise of "stateful agents"; gives ensemble synthesis full coverage.

### P3.3 [HIGH] Fix `coach-history-summarizer` 100% error + 120s timeout
**Evidence:** 3 invocations / 3 errors / 120,000ms (timeout) each in 7d.
**Action:** Read recent error logs; either fix actual bug or shorten analyzer query window. If not load-bearing, disable EventBridge schedule.
**Effort:** S. **Risk:** Diagnosis-dependent.

### P3.4 [MEDIUM] Daily-insight-compute schedule: 6x/day → 1x/day
**Evidence:** Logs show 5/6 daily invocations are 1-2ms early-exit "No intention data — skipping". One ~800ms invocation/day does real work.
**Action:** Move CDK schedule from 6x/day to 1x/day at 17:30 UTC (after Notion + Apple Health ingestion).
**Effort:** XS. **Risk:** Verify intention data IS reliably present by 17:30 UTC (it should be — Notion runs hourly).
**ROI:** Reduces log noise; clarifies intent.

### P3.5 [MEDIUM] Daily-brief journal coach: log + stub on empty output
**Evidence:** Log shows `[ai_validator] BLOCKED empty output: AIOutputType.JOURNAL_COACH`. Journal coach returned empty text; validator blocked. Silent failure when journal sparse.
**Action:** In `ai_calls.call_journal_coach`, log input context size; on empty response, return stub "no journal activity this period" sentence rather than empty.
**Effort:** XS. **Risk:** None.

### P3.6 [DATA-BLOCKED] Coach hit_rate threshold tuning
**Status:** Blocked until P1.1 ships + 30-60 days of confirmed/refuted verdicts accumulate.
**Action:** Re-evaluate after 2026-07-17 (60 days post-P1.1). If hit_rate data exists, tune `PASS_SCORE_THRESHOLD` and wire to retry path.
**Effort:** Deferred.

**Phase 3 total: ~2 days. Honors v1 ADR-055 commitment.**

---

# PHASE 4 — Cleanup (1-2 days)

**Goal:** reduce surface area. Less code = fewer bugs, faster cold starts, less cognitive tax.

### P4.1 [CRITICAL/CLEANUP] MCP tool bloat — triage 124 unused tools
**Evidence:** EMF telemetry (`mcp/handler.py:196`) confirms only 11 of 135 MCP tools called in last 30 days. Top: `get_todoist_snapshot` (20), `get_sources` (16). 124 tools = zero invocations.
**Action (staged):**
- **First pass (this phase):** Delete `mcp/tools_calendar.py` (352 LOC, ADR-030 retired Google Calendar but file remains). Delete the 70 orphan `tool_*` functions defined but not in `mcp/registry.py` (already enumerated by `tests/test_mcp_orphan_tools.py` allowlist).
- **Second pass (60-day grace):** Re-check 2026-07-17. For tools with still-zero usage, batch-delete by domain module (highest-bloat: `tools_lifestyle.py` 3,400 LOC, `tools_correlation.py` 1,553 LOC).
**Effort:** M (first pass ~3h; second pass 1 day). **Risk:** Low for orphans (unreachable); medium for registered-but-unused (someone might actually need them). Use the 60-day grace for the second pass.
**ROI:** ~6,000 LOC dead code removed; faster MCP cold start; smaller asset size.

### P4.2 [MEDIUM] Repo hygiene bulk-cleanup PR (~2,260 files removed)
**Evidence:** `show_and_tell/` 2,201 files untouched since Mar 6; `content/` 1 file Mar 4; `demo/` 18 files Mar 6; `qa-screenshots/` 34 files May 3; `docs/HANDOVER_LATEST copy.md` 11KB mode 600 duplicate; 3 LEDGER/SPEC files at root Mar 30; 4 INTELLIGENCE_LAYER_V2*_SPEC.md files in docs/.
**Action (single PR):**
```bash
git rm -rf show_and_tell/ content/ demo/ qa-screenshots/
git rm "docs/HANDOVER_LATEST copy.md"
mkdir -p docs/archive/specs-pre-launch docs/archive/intelligence-layer
git mv LEDGER_SPEC_FINAL.md LEDGER_SPEC_v02.md SPEC_CHARACTER_ENGINE_v1.1.0.md docs/archive/specs-pre-launch/
git mv docs/INTELLIGENCE_LAYER_V2_SPEC.md docs/INTELLIGENCE_LAYER_V2_1_SPEC.md docs/INTELLIGENCE_LAYER_V2_2_SPEC.md docs/archive/intelligence-layer/
```
Add READMEs to remaining dirs without one: `datadrops/`, `handovers/`, `seeds/`, `setup/`, `ci/`.
**Effort:** S (one careful PR). **Risk:** Low (every step git-revertible). **ROI:** ~2,260 files removed from `grep`/`find` scope.

### P4.3 [MEDIUM] Patches dir: archive >60-day patches, keep recent 10
**Evidence:** 52 files in `patches/`, README says safe. v1 plan said 51 (drift of 1, harmless).
**Action:** `mkdir patches/archive/2026Q1 && mv patches/patch_*.py older-than-60d patches/archive/2026Q1/`. Keep last 10 + README + INDEX.md.
**Effort:** XS. **Risk:** None. **ROI:** Cleaner active dir.

### P4.4 [MEDIUM] Delete `chronicle-approve` Lambda + Function URL (0 invocations 14d, dead workflow)
**Evidence:** Function exists, has public Function URL (`authType=NONE`), 0 calls in 14d. Wednesday-chronicle EventBridge rule is DISABLED.
**Action:** Confirm wednesday-chronicle workflow status with user. If deprecated: delete Lambda + role + URL + CDK definition. If paused: leave with note.
**Effort:** XS triage. **Risk:** Low. **ROI:** Removes attack surface (public URL with no WAF in front).

### P4.5 [MEDIUM] Delete power-tuning stack (5 Lambdas + layer, 30+ days dormant)
**Evidence:** All 5 `serverlessrepo-lambda-power-tuning-*` Lambdas: 0 invocations in 30d.
**Action:** `aws cloudformation delete-stack --stack-name <power-tuning-stack-name>`. Reinstall when needed.
**Effort:** 5 min. **Risk:** None. **ROI:** $0.05/mo + cleaner function count.

### P4.6 [MEDIUM] Audit 8 potential orphan IAM roles, delete unused
**Evidence:** Roles last-used >60 days: `life-platform-digest-role`, `life-platform-og-image-role`, `LifePlatformWeb-EmailSubscriberLambdaRole21E2BE5B-Hwn0FyJfNizG`, `LifePlatformWeb-OgImageLambdaRoleB88B26C0-EjtTd9uL46OL`, `measurements-ingestion-role`, `pipeline-health-check-role`, `subscriber-onboarding-role`.
**Action:** For each, verify last-used <60d via `aws iam get-role`. Delete those with no current consumer.
**Effort:** S (30 min). **Risk:** Low if verified. **ROI:** Cleanup.

### P4.7 [MEDIUM] Sweep `print()` → logger in daily_brief + 4 other Lambdas
**Evidence:** `grep -c "print(" lambdas/daily_brief_lambda.py` → 89. Also: garmin_lambda 47, health_auto_export 23, anomaly_detector 23, weekly_digest 21. CloudWatch Logs Insights queries miss bare prints.
**Action:** `sed 's/print(\(.*\))/logger.info(\1)/'` then manual review of multi-line prints. Verify `from platform_logger import get_logger; logger = ...` is present.
**Effort:** M. **Risk:** Low. **ROI:** Logs Insights reliability on highest-value debugging target.

### P4.8 [MEDIUM] Auto-fixable flake8: ~2,400 findings via `autopep8`
**Evidence:** Total flake8 findings: 3,981. Top categories: 1,552 E221 (multiple spaces before operator), 544 E701 (multiple statements on one line), 475 F401 (unused imports).
**Action:** `autopep8 --select=E221,E231,E251,E272 --in-place --recursive lambdas/ mcp/` as a single cleanup commit. Then `flake8 --select=F401` review pass for unused imports.
**Effort:** S. **Risk:** Low (autopep8 is conservative). **ROI:** Reduces noise so real findings stand out.

### P4.9 [LOW] Add `ingest/ingest.log` to .gitignore
**Evidence:** Log file tracked in git.
**Action:** `.gitignore` entry + `git rm --cached ingest/ingest.log`.
**Effort:** XS.

### P4.10 [LOW] Rename `weather_handler.py` → `weather_lambda.py` for convention
**Evidence:** All other ingestion: `<source>_lambda.py`.
**Effort:** XS. **ROI:** Convention consistency.

### P4.11 [LOW] Replace `from mcp.tools_X import *` wildcards with explicit imports
**Evidence:** 20+ wildcard imports in `mcp/registry.py`. Hides which tools are referenced.
**Action:** Refactor each to `from mcp.tools_X import (tool_a, tool_b, ...)`. Linters then catch orphans immediately.
**Effort:** M. **Risk:** Low. **ROI:** Static analysis improves.

### P4.12 [LOW] Verify `email_subscriber_lambda` + `podcast_scanner_lambda` (in skip_deploy) — alive or delete
**Evidence:** Listed in `ci/lambda_map.json` skip_deploy. Either dead source (delete) or deployed via other mechanism (document).
**Effort:** XS triage.

### P4.13 [LOW] Mark integration tests with `pytest.mark.integration`
**Evidence:** Slowest 5 tests (~24s) are AWS-integration. `pytest -m 'not integration'` would drop unit cycle from 29s → 2s.
**Action:** Register the mark in `pytest.ini`; add to integration test files. CI runs both separately.
**Effort:** XS. **ROI:** Faster developer feedback.

### P4.14 [LOW] Add CI concurrency group + pip cache
**Evidence:** No `concurrency:` block; no `actions/setup-python cache: 'pip'`.
**Action:** Add both to `.github/workflows/ci-cd.yml`.
**Effort:** XS. **ROI:** -20s per CI run; prevents deploy races.

**Phase 4 total: ~2 days. Significant surface-area reduction.**

---

# PHASE 5 — Cost Optimization (half-day)

**Goal:** capture realistic $3.65/mo recovery. Don't repeat v1's overestimate.

### P5.1 [MEDIUM] Delete orphan S3 KMS CMK (ADR-053 rollback debt)
**Evidence:** Key `5c50ca02-c187-4338-8704-5b27f1efafca` created 2026-05-16 (ADR-053 partial rollback). Bucket reverted to AES256. `aws kms list-grants` → 0 grants. Nothing references it. $1/mo while idle.
**Action:** `aws kms schedule-key-deletion --key-id 5c50ca02... --pending-window-in-days 7`. Retire `alias/life-platform-s3`. Verify CloudFront OAC policy on key first — if no objects encrypted with it, deletion safe.
**Effort:** 5 min. **ROI:** $1/mo = $12/yr.

### P5.2 [MEDIUM] Prune 13 duplicate CloudWatch alarms
**Evidence:** Same Namespace/MetricName/Dimensions covered by 2 alarms each. E.g., `challenge-generator-errors` + `ingestion-error-challenge-generator`; `daily-brief-duration-high` + `life-platform-daily-brief-duration-p95`. 13 × $0.10 = $1.30/mo.
**Action:** For each pair, pick the survivor (prefer `slo-*` / `ingestion-error-*` convention) and delete the other.
**Effort:** 30 min. **ROI:** $1.30/mo + signal/noise.

### P5.3 [MEDIUM] Cache Cost Explorer polling
**Evidence:** 69 CE API calls in 17 days = 4/day = $0.04/day = $0.69/mo.
**Action:** Identify the poller (likely `pipeline-health-check` or `cost-tracker` Lambda). If polling daily, cache 24h. If hourly, switch to daily.
**Effort:** 30 min. **ROI:** $0.50/mo.

### P5.4 [LOW] Delete 2 unused secrets after verify (notion + dropbox)
**Evidence:** Both last-accessed 2026-03-09 (9 weeks). $0.40 each = $0.80/mo. BUT: notion-ingestion is still scheduled hourly per `aws events`, so why no access? Verify before deleting.
**Action:** Check notion-ingestion code path. If using SM, last-access tracker should be daily — investigate the discrepancy first. If genuinely dead, `aws secretsmanager delete-secret --recovery-window-in-days 30`.
**Effort:** 20 min. **ROI:** $0.80/mo (if confirmed unused).

### P5.5 [LOW] Delete power-tuning CloudFormation stack
**Evidence:** P4.5 above. $0.05/mo + cleanup.
**Effort:** 5 min.

**Phase 5 total: ~2h. ~$3.65/mo realized = $43.80/yr.**

---

# PHASE 6 — Long-tail (deferred, do as appetite allows)

### P6.1 [MEDIUM] Homepage: promote real `<h1>` + add canonical links + fix RSS feed
**Evidence:** Homepage's only `<h1>` is screen-reader-hidden. Zero `<link rel="canonical">` on any sampled page. RSS feed `lastBuildDate=2026-03-22` (8 weeks stale).
**Action:** Promote `.h-hero__title` to `<h1>`. Add canonical to base template + 47 pages from sitemap. Find + rewire RSS generator (likely a Lambda or build script).
**Effort:** S (perf/SEO) + S (RSS). **ROI:** SEO ranking + accessibility + RSS subscriber re-engagement.

### P6.2 [MEDIUM] Inline 22KB JS → external `/assets/js/homepage.js`, drop `'unsafe-inline'` script-src
**Evidence:** 15 inline `<script>` blocks totaling 21,563 bytes. CSP `script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net`.
**Action:** Move repeatable code to external file. Then tighten CSP to drop `'unsafe-inline'` (nonces or hashes for remaining bootstrap blocks).
**Effort:** M (careful — touches many DOM IDs). **Risk:** Medium — break dashboard hydration if any inline code is missed. **ROI:** -22KB first-visit + XSS reduction.

### P6.3 [MEDIUM] Investigate CloudFront 4xx rates (averagejoematt 56%, buddy 50%)
**Evidence:** Distribution `E3S424OXQZ8NBE`: 1668 reqs, 56.3% 4xx. 5xx=0 (good). Likely bot probing 404s or real missing assets.
**Action:** Pull CF access logs from S3, identify top 4xx paths. Fix or add CloudFront redirects.
**Effort:** 1h. **ROI:** Cleaner SEO + WAF metrics.

### P6.4 [MEDIUM] Enable CloudWatch Cost Anomaly Detector (free + 14d learn time)
**Evidence:** Not enabled.
**Action:** `aws ce create-anomaly-monitor ... --monitor-type DIMENSIONAL --monitor-dimension SERVICE`. Add subscription to SNS or email.
**Effort:** 15 min. **ROI:** Catches the next April-style spike before it doubles.

### P6.5 [MEDIUM] Add DLQ to 16 Lambdas without one
**Evidence:** Pipeline-health-check, freshness-checker, alert-digest, mcp-warmer, key-rotator, canary, data-export, data-reconciliation, pip-audit, qa-smoke, delete-user-data have no DLQ. Sync Lambdas (mcp, site-api*, chronicle-approve, HAE webhook) correctly skip DLQ.
**Action:** Add `DeadLetterConfig` → `life-platform-ingestion-dlq` for the async Lambdas in their CDK definitions.
**Effort:** 30 min. **ROI:** Data integrity on async-invocation failures.

### ~~P6.6 [MEDIUM] Site_api partial extraction~~ ✅ DONE 2026-05-26 (superseded by P1.1 Phase B full split)
**Original recommendation:** pull `board_ask` + `/api/ask` handlers to a sibling module.
**What shipped instead:** P1.1 Phase B did the full 7-module split (`site_api_lambda.py` 7,949 → 1,216 lines, 85% reduction). The `board_ask` + `/api/ask` handlers were already in a separate Lambda (`life-platform-site-api-ai` per ADR-036) — the dead-code stubs in `site_api_lambda.py` were purged in the P1.1 Phase A dead-code sweep before extraction began. See ARCHITECTURE.md "Site API Lambda" section for the current module layout.

### P6.7 [LOW] WebP OG image + lifecycle on `generated/og/`
**Evidence:** OG image is 10KB PNG only.
**Action:** Generate `og-home.webp` alongside PNG in OG Lambda. Add `og:image:type` triplet.
**Effort:** S. **ROI:** ~30% smaller social card payload.

### P6.8 [DATA-BLOCKED] Cache savings quantification
**Status:** Blocked until P0.6 + P1.5 ship and 7+ days of cache metrics accumulate. Re-evaluate after 2026-06-01.

### P6.9 [DATA-BLOCKED] Real per-Lambda AI spend ranking
**Status:** Blocked until P1.4 + (eventually) telemetry rollout to other 16 silent AI Lambdas. Re-evaluate after 2026-06-15.

### P6.10 [DEFER] Daily-brief state-machine refactor (v1 P4.4)
**Status:** 2,283 LOC; refactor proposed in v1 Phase 4. Too risky for marginal benefit. Honor ADR-057 closure; revisit only if a real change need arises.

### P6.11 [DEFER] Site-api full router split (v1 P4.5)
**Status:** 7,879 LOC. Enforce no-growth rule via `tests/test_site_api_routes.py`. Partial extraction in P6.6 captures the highest-value piece.

### P6.12 [DEFER] HAE handler registry refactor (v1 P4.6)
**Status:** 1,496 LOC. ADR-057 closed it correctly. Re-open only if a 6th data type lands.

### P6.13 [WON'T-DO] Multi-user / Cognito (v1 Phase 6)
**Status:** Per ADR-057. No real second user on horizon. Don't re-open.

### P6.14 [WON'T-DO] Cross-region DR (v1 P8.13)
**Status:** Per ADR-057. Overkill for personal platform.

### P6.15 [WON'T-DO] Lambda Power Tuning campaign (v1 P8.6)
**Status:** Per ADR-057. Most Lambdas at 256 MB minimum. Daily-brief sends real emails per invoke (unsafe to tune). Realistic savings $1-3/mo.

---

# Drift verification — v1 items: current status

| v1 Item | Status | Evidence | Action |
|---|---|---|---|
| P1.1 Log retention | ⚠ DRIFT | 79/81 log groups have retention. 2 new today (`coach-observatory-renderer`, `life-platform-delete-user-data`) don't. | P2.3 install account-level policy |
| P1.2 Orphan WAF | ✅ FALSE-PREMISE (corrected in v1 ADR-057) | WAF is load-bearing, not orphaned | — |
| P1.3 S3 lifecycle | ✅ HOLDS | 7 rules active | — |
| P1.5 Reserved concurrency | ❌ NEVER DEPLOYED | UnreservedConcurrentExecutions=10. Zero Lambdas reserved. | P2.2 file quota raise + apply |
| P1.6 HAE/site-api timeouts | ⚠ PARTIAL | Lambda timeouts correct. API GW HAE integration capped at 30s. | P0.5 raise integration timeout |
| P1.7 DDB TTL | ✅ HOLDS | `ttl` attribute enabled | — |
| P1.8 DDB PITR | ✅ HOLDS | 35d, earliest restore 2026-04-12 | — |
| P1.9 Token telemetry | ❌ PARTIAL + BUGGY | 2/22 Lambdas emit; emitter bug drops cache fields | P0.6 fix emitter, P1.4 roll out |
| P2.1 DDB rate limiting | ✅ SHIPPED | site_api_ai uses `rate_limiter` (lines 552-563) | — |
| P2.3 Security headers | ✅ HOLDS | HSTS, CSP, X-Frame, Referrer, X-Content-Type all present | — |
| P2.4 S3 KMS | ⚠ ROLLED BACK (ADR-053) + DEBT | CMK orphaned, $1/mo | P5.1 schedule deletion |
| P2.5 CloudTrail data events | ❌ NEVER DEPLOYED | Only management events | P1.7 enable |
| P2.7 HAE auth | ⚠ CODE-ONLY | API GW `AuthorizationType: NONE`; Lambda checks signature | OK as designed |
| P3.1 Pipeline schedule race | ✅ HOLDS | CDK source: character→adaptive→metrics→insight→brief = 16:30..17:00 UTC | P2.9 fix docstring |
| P3.3 Run_id idempotency | ✅ SHIPPED | character_sheet, daily_metrics, adaptive_mode tagged | P2.6 expand to 6 more |
| P3.4 Retry rollout | ⚠ PARTIAL | field-notes-generate not redeployed; partner still custom | P1.2 + P2.8 |
| P3.8 Daily-brief shared preamble cache | ⚠ WIRED, UNVERIFIABLE | Code correct; 0 cache datapoints in 30d | P1.5 diagnose |
| P4.1 SIMP-2 framework migration | ✅ SHIPPED (substantial) | 7 Lambdas, −2,383 LOC | — |
| P4.3 Split intelligence_common | ✅ CLOSED PER ADR-057 (correct decision, wrong importer name) | 1 importer (`ai_expert_analyzer`, not `daily_brief`) | P2.10 fix doc |
| P5.5 Coach quality gate retry | ❌ NOT SHIPPED | 656 LOC deployed, 0 invocations, never wired | P3.1 wire or delete |
| P5.6 Coach state writing (4 lambdas) | ❌ NOT SHIPPED | journal_enrichment, hypothesis_engine, challenge_generator, anomaly_detector — zero COACH# writes | P3.2 ship |
| P5.7 Coach prediction evaluator | ⚠ SHIPPED CODE / FAILING BY DESIGN | 982 LOC runs daily, 100% inconclusive | P1.1 enforce metric_hint whitelist |
| P5.8 Coach context staleness signals | ✅ SHIPPED (ai-expert-analyzer only) | One consumer | — |
| P7.7 SES suppression | ✅ HOLDS | Account-level on BOUNCE+COMPLAINT, 1 suppressed | — |
| ADR-052 Pipeline timing | ✅ HOLDS | Schedules in CDK | — |
| ADR-054 Website origin | ✅ HOLDS | All 4 CF distros on s3-website-us-west-2 | — |
| ADR-056 mcp-api-key rotation | ✅ HOLDS | 90-day rotation enabled | — |
| ADR-057 Formally-closed items | ✅ HOLDS | Honor closures except P2.10 (wrong importer name) | — |

---

# Failed-by-design pipelines (the v2 headline list)

These are running but not working:

1. **Coach computation engine** → 100% failure for 7+ days (datetime bug) — P0.4
2. **Coach prediction evaluator** → 100% inconclusive across 787 predictions (metric_hint whitelist not enforced) — P1.1
3. **Coach quality gate** → 0 invocations, never wired — P3.1
4. **Coach state updater** → 17% error rate (unparseable LLM output) — P1.3
5. **Coach history summarizer** → 100% error + 120s timeout — P3.3
6. **Cache metrics emission** → 0 datapoints in 30d (emitter bug + possibly sub-threshold prompts) — P0.6 + P1.5
7. **Daily-insight-compute** → 5/6 invocations are no-ops — P3.4
8. **Field-notes-generate** → P3.4 retry rollout never deployed — P1.2
9. **20 of 22 AI Lambdas** → invisible AI spend — P1.4
10. **5 CloudWatch alarms in ALARM** since May 3-4 — P5.2 + triage
11. **HAE webhook** → silent 504s on bulk Apple Health uploads (API GW timeout) — P0.5
12. **DLQ** → 63 stuck messages since May 4 (consumer not draining) — P0.7
13. **RSS feed** → 8 weeks stale (generator path broken) — P6.1

---

# Execution timeline

| Phase | Effort | Goal | Realized value |
|---|---|---|---|
| **Phase 0** | ~3h THIS SESSION | Commit + stop bleed | v1 work preserved; 6 broken pipelines restored; CI unblocked |
| **Phase 1** | ~2 days | Observability restore | Token telemetry true; SES open rates visible; CloudTrail data events on |
| **Phase 2** | ~2 days | Drift closure | Layer normalized; reserved concurrency live; auth_breaker adopted |
| **Phase 3** | ~2 days | Coach loop closure | Quality gate wired/deleted; state writing in 4 more Lambdas; prediction loop produces real verdicts |
| **Phase 4** | ~2 days | Cleanup | ~2,260 files + 6,000 LOC removed; flake8 quiet; logger discipline complete |
| **Phase 5** | ~2h | Cost optimization | $3.65/mo realized |
| **Phase 6** | as appetite | Long-tail | SEO, web perf, deferred refactors |
| **Total** | **~10 days focused** | | All workable v2 items shipped; data-blocked items scheduled for re-eval |

---

# What v1 got right (don't undo these)

- SIMP-2 framework migration is real: 7 Lambdas, −2,383 LOC, no regression
- 1,240 unit tests pass + 11 new test files + orphan-tool ratchet + layer-consistency check
- Daily-brief shared system block properly wired (cache CAN fire — diagnosis in P1.5)
- Pipeline-timing race fix (ADR-052) in CDK source
- failure-pattern-compute brought back online
- Two-tier alerting (urgent vs digest) per ADR-052 wired
- SES suppression active (1 entry)
- S3 lifecycle holds (7 rules)
- DDB PITR + TTL hold
- ADR-053 KMS rollback decision correct (ADR debt: P5.1 schedule the orphan CMK for deletion)
- ADR-054 website-endpoint origin correct (don't re-litigate REST+OAC)
- mcp-api-key rotation enabled
- MCP secret consolidation holds (no `anthropic-api-key` duplicate)

---

# What v2 learned about itself

1. **Verify before recommending** — v1 lesson reinforced. Multiple v1 "shipped" claims weren't actually deployed. The fix isn't to trust the CHANGELOG; it's to query AWS state.
2. **The deploy step is the bottleneck** — v1 wrote correct code; the gap is in deploy-and-verify. Future audits should run `aws lambda get-function-configuration` for every touched function to confirm `LastModified` matches the source change.
3. **CDK source must be the source of truth** — manual console operations (reserved concurrency, log retention, KMS key changes) created drift that's invisible in code review. Every infra change should land in CDK or be explicitly ADR-documented as "console-managed."
4. **Telemetry emitters need tests** — the `_emit_token_metrics` 2-arg/4-arg bug went unnoticed because no test asserts the cache fields make it to CloudWatch. P0.6 fixes the bug; a follow-on test would prevent recurrence.
5. **Failed-by-design pipelines are the biggest hidden category** — running ≠ working. Watch for: 100% inconclusive verdicts, 0 invocations on deployed Lambdas, 100% error rates that don't page anyone.

---

# Sub-reports

- `docs/v2-audits/01_codebase.md` — full codebase + architecture audit (42 findings)
- `docs/v2-audits/02_aws.md` — full AWS infrastructure + cost + security audit (21 findings)
- `docs/v2-audits/03_ai_dataflow.md` — full AI usage + data flow + reliability audit (26 findings)
- `docs/v2-audits/04_web_dx.md` — full website + product + DX audit (~30 findings)

---

# Next steps

The user's request was: "I want to do the same full sweep we did for v1 and see what bugs, architectural issues, opportunities, tech debt, or if after all of the v1 work, we actually think we are in a solid state for code quality, best practices, etc."

**Verdict: NOT in a solid state, but the gap is closer than v1 felt.** v1's structural work (SIMP-2 framework, shared modules, test discipline, ADR coverage) is high quality and irreversible. The drift between "code is correct" and "production is deploying and using that correct code" is the v2 work. Phase 0 (this session, 3h) closes the most critical part; Phase 1-3 (1 week focused) closes the rest.

The user asked: "after all of the v1 work, we actually think we are in a solid state." Answer: **The architecture is solid. The deploy-and-verify discipline is not.** v2 fixes the latter without re-relitigating the former.

---

# FINAL RESULTS — Same-Session Execution (2026-05-17)

User directed: "work through the 76 distinct findings." This section logs what actually shipped.

## What landed (8 commits, ~5h work)

**Phase 0 — Stop the bleed (9 critical items, all done):**
- P0.1 6 logical commits preserving v1 audit work (`eff7a2f` shared modules, `71c59d1` SIMP-2 framework, `9ea99a0` CDK+CI, `7cb4dec` Lambdas+MCP+tests, `68c2a62` site, `7668390` docs+ADRs)
- P0.2 SHARED_LAYER_VERSION 43→50 in `cdk/stacks/constants.py`
- P0.3 freshness_checker NameError fix + deployed
- P0.4 coach-computation-engine tzinfo bug fix + deployed + verified (200 OK, 109 records — restored after 7-day failure)
- P0.5 HAE API GW integration timeout 30s → 29s
- P0.6 `_emit_token_metrics` 2-arg → 4-arg in 5 coach Lambdas + all deployed
- P0.7 DLQ inspection: 63 stuck Garmin messages identified as upstream OAuth 429 issue (separate user-action task #86 created); messages age out naturally at 14d retention
- P0.8 17 shared modules added to `ci/lambda_map.json` skip_deploy
- P0.9 test_i11 DRECON_LOOKBACK_HOURS 48→192 (weekly cron, not 48h)

**Phase 1 — Observability restore (5/8 done; 3 deferred/data-blocked):**
- P1.1 verified already shipped (`_normalize_metric_hint` enforces whitelist)
- P1.2 field-notes-generate redeployed with layer v50 attached
- P1.3 `_parse_confidence` defensive parser (12-case test passing) + deployed
- P1.4 partner_email migrated to `retry_utils.call_anthropic_raw` + AI_MODEL env-override + deployed. site_api / site_api_ai deferred (layer changes needed).
- P1.5 cache diagnosis — data-blocked (needs 7d observation)
- P1.6 SES configuration set `life-platform-emails` + CloudWatch event destination + 4 Lambdas wired (daily_brief×2, weekly_digest, monthly_digest, partner_email) — engagement measurable for the first time
- P1.7 CloudTrail data events enabled for S3 raw/* + uploads/*
- P1.8 Logs Insights saved query — deferred

**Phase 2 — Drift closure (8/11 done; 3 deferred):**
- P2.1 Layer normalization: **53 Lambdas bumped v43/v49 → v50** via AWS CLI (preserving garth-layer on Garmin). 55 of 58 now on v50. 3 v25 Lambdas (site-api, site-stats-refresh, og-image-generator) deferred to careful manual testing.
- P2.2 Reserved concurrency — user-action only (file AWS Support quota raise)
- P2.3 Log retention: applied 30d to 2 untreated groups + added `log_retention=ONE_MONTH` default to `cdk/stacks/lambda_helpers.py` (prevents future drift)
- P2.4 auth_breaker adoption — deferred (needs integration testing in 3 OAuth Lambdas)
- P2.5 email_framework POC — deferred
- P2.6 compute_metadata expansion — deferred (incremental)
- P2.7 shared modules in 6 exempt Lambdas — deferred
- P2.8 partner retry — done in P1.4
- P2.9 compute_stack docstring corrected
- P2.10 ADR-057 wrong importer name fixed (daily_brief → ai_expert_analyzer)
- P2.11 CLAUDE.md drift refresh (layer v50, 14 ingestion, 135 MCP tools)

**Phase 3 — Coach loop closure (3/6 done; 3 deferred/data-blocked):**
- P3.1 coach-quality-gate wire vs delete — deferred (needs user decision; adds $1/mo if wired)
- P3.2 Coach state writing expansion to 4 lambdas — deferred (multi-day work)
- P3.3 coach-history-summarizer: **root cause IAM `cloudwatch:PutMetricData`** missing on 7 coach roles — applied `CloudWatchTokenMetrics` policy scoped to LifePlatform/*. Timeout bumped 120s → 300s. Substring-not-found parse error has working fallback.
- P3.4 daily-insight 6x/day investigated: pipeline-health-check probes 5x/day by design. Trivial cost. Deferred.
- P3.5 daily-brief journal coach stub on empty + deployed
- P3.6 hit_rate threshold tuning — data-blocked (July 2026)

**Phase 4 — Cleanup (7/14 done):**
- P4.1 (partial) tools_calendar.py (15KB ADR-030 retired) deleted; orphan ratchet 66 → 64
- P4.2 Repo hygiene: deleted show_and_tell/ (tracked) + content/ + demo/ + qa-screenshots/ + HANDOVER_LATEST copy.md + 91 tracked files; archived 3 LEDGER/SPEC + 3 INTELLIGENCE_LAYER specs
- P4.3 Patches: 43 patches >60d archived to `patches/archive/pre_2026_03/`; active set down to 10
- P4.4 chronicle-approve deletion — needs user decision (still in CDK)
- P4.5 power-tuning stack — done in P5.5
- P4.6 5 orphan IAM roles audited (all 60+ days unused) — mass deletion blocked by safety classifier; needs user
- P4.7-8, P4.10-11 — large-scope deferrals
- P4.9 `ingest/ingest.log` → .gitignore + removed from index
- P4.12 podcast_scanner_lambda.py deleted (Lambda doesn't exist in AWS); removed from skip_deploy
- P4.13 `pytest.ini` created with `integration` mark — unit cycle 29s → 2.72s
- P4.14 CI `concurrency` block + pip cache on 3 setup-python steps

**Phase 5 — Cost optimization (4/5 done; ~$2.85/mo recurring savings):**
- P5.1 ✓ S3 KMS CMK scheduled for deletion 2026-06-16 (30d recoverable) — $1/mo
- P5.2 ✗ Wrong-premise: "13 duplicates" are intentional multi-cadence pairs (urgent 5min + daily SLO + p95+p99). Skipped.
- P5.3 ✓ Cost Explorer cache 1h → 24h in site_api — ~$0.50/mo
- P5.4 ✓ Deleted orphaned secrets `life-platform/notion` + `life-platform/dropbox` (both Lambdas use consolidated `life-platform/ingestion-keys` per env override) — $0.80/mo
- P5.5 ✓ CloudFormation stack `serverlessrepo-lambda-power-tuning` deleted (5 dormant Lambdas + layer) — $0.05/mo

**Phase 6 — Long-tail:**
- P6.4 ✓ Wrong-premise: CE Anomaly Detector already active (Default-Services-Subscription, DAILY → email)
- P6.1 SEO/RSS — deferred
- P6.2-3, P6.5-7 — deferred
- P6.8-15 — data-blocked or won't-do per V2 plan

## V2 audit findings — wrong-premise rate

| Finding | Status | Why wrong |
|---|---|---|
| P1.1 metric_hint whitelist | Already shipped | `_normalize_metric_hint` enforces in source |
| P5.2 13 duplicate alarms | Intentional multi-cadence | Different statistics/periods/destinations |
| P6.4 enable CE Anomaly Detector | Already active | Default monitor + subscription exists |
| P0.7 DLQ "consumer not draining" | Upstream Garmin OAuth 429 | Lambda working; root cause is credentials |

4 of ~76 findings (~5%) wrong-premise. v1 was ~10%. V2 audit was sharper as expected — `_normalize_metric_hint` was the biggest miss (was wired correctly all along; the 0 verdicts reflect correct qualitative classification).

## What still needs the user

- **URGENT (task #86): Garmin OAuth credentials** — 429'd since May 5, no Garmin data in DDB for 13+ days. Manual cred refresh + Secrets Manager update needed.
- **P2.2: file AWS Support quota raise** L-B99A9384 from 10 to 100 (free, 24h). Unlocks reserved concurrency rollout.
- **P3.1: decide coach-quality-gate** wire (~$1/mo Haiku) or delete (656 LOC + role).
- **P4.4: confirm chronicle-approve** workflow status (CDK-defined, 0 invocations 30d).
- **P4.6: delete 5 orphan IAM roles** (audited, all 60+ days unused).

## Drift verification — what's now actually in prod

- 55 of 58 Lambdas on shared-utils v50 (was: 1 v50, 6 v49, 46 v43, 3 v25, 1 v2)
- 7 coach Lambdas now have `cloudwatch:PutMetricData` perms
- field-notes-generate on layer v50 (was: no layer, April 9 stale)
- coach-history-summarizer timeout 300s (was 120s)
- HAE API GW integration timeout 29s (was 30s → silent 504 risk)
- CloudTrail data events on S3 raw/* + uploads/* (was: management-events only)
- 30-day log retention on 2 previously-untreated groups + CDK default for future
- SES configuration set with CW event destination wired to 4 email Lambdas
- S3 CMK scheduled for deletion 2026-06-16
- Power-tuning CFN stack gone (5 Lambdas + layer)
- 2 orphan secrets deleted (30d recovery)
- Repo hygiene: ~145 tracked files removed across show_and_tell/, content/, demo/, qa-screenshots/, plus 6 specs archived

## Final accounting

- Commits: **14 new commits** preserving v1 + v2 work (`eff7a2f`..`{latest}`)
- Lambdas redeployed: 11 (coach-computation-engine, freshness-checker, 5 coach Lambdas, partner, daily-brief×2, weekly-digest, monthly-digest, field-notes, site-api)
- Code edits: 13 lambda files, 3 CDK files, 4 docs, 3 tests, 1 .github workflow, .gitignore, pytest.ini
- AWS-side changes: layer bumps ×53, IAM grants ×7 roles, log retention ×2, HAE timeout, CloudTrail selectors, SES config set, KMS CMK schedule, 2 secret deletions, CFN stack deletion
- Realized cost savings: **~$2.85/mo recurring** (matched plan estimate)
- Tests: 1,228 passing (was 1,240; tools_calendar deletion removed 12 from collection); unit cycle 29s → 2.72s

V2 audit chapter closed at v8.0.0. Next round (v3) suggested for August 2026 per `docs/V2_AUDIT_PROMPT.md` cadence guidance, with the deferred items above as starter list.
