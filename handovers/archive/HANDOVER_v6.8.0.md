# Handover — v6.8.0: COST-OPT-2 Prompt Caching + Model Tiering

**Date:** 2026-04-09
**Scope:** Anthropic API cost optimization — prompt caching across all 12 API call sites, model downgrades for 5 structured-output Lambdas, observatory AI_UNAVAILABLE fix.

## What Changed

### 1. Observatory [AI_UNAVAILABLE] Fix

**Problem:** Observatory pages showed literal `[AI_UNAVAILABLE]` text. The Anthropic API key (`life-platform/ai-keys`, ending `cQAA`) ran out of credits. `ai_calls.call_anthropic()` returns the sentinel `[AI_UNAVAILABLE]` on failure, which got written to DynamoDB and served raw to the frontend.

**Fix:** `site_api_lambda.py` — both `/api/coach_analysis` (line 7271) and `/api/ai_analysis` (line 7213) now nullify analysis text containing `[AI_UNAVAILABLE]`. The frontend's existing graceful fallback ("Analysis generates daily. Check back soon.") kicks in.

**Deployed:** `life-platform-site-api` ✅

### 2. Prompt Caching (COST-OPT-2, Phase 1)

Added Anthropic prompt caching to all API call paths. System messages are auto-wrapped as cached content blocks with 90% discount on cache hits.

**Shared utilities updated:**
- `retry_utils.py` — `call_anthropic_api()` gains `cache_system=True` param. String system prompts auto-wrapped as `[{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]`. Beta header added. New `_build_system_block()` helper.
- `ai_calls.py` — `call_anthropic()` gains `model` and `cache_system` params. Same auto-wrapping. New `_build_system_block()` helper.
- Both emit new CloudWatch metrics: `AnthropicCacheWriteTokens`, `AnthropicCacheReadTokens` per Lambda.

**Expert analyzer caching:**
- `ai_expert_analyzer_lambda.py` — new `_build_shared_system_prompt()` builds a ~2900-char system prompt (goals, inventory, targets, format instructions) once per invocation. Passed as cached system message to all 8 expert calls. First call pays 25% cache write premium; remaining 7 get 90% discount.

**Direct API callers updated (8 files):**
- `coach_narrative_orchestrator.py`, `coach_ensemble_digest.py`, `coach_state_updater.py`, `coach_quality_gate.py`, `coach_history_summarizer.py` — system block + beta header + cache metrics
- `journal_enrichment_lambda.py` — 2 call sites (main enrichment + defense)
- `hypothesis_engine_lambda.py` — 2 call sites (generation + check)
- `challenge_generator_lambda.py` — 1 call site

### 3. Model Downgrades (COST-OPT-2, Phase 2)

Switched structured/templated tasks from Sonnet to Haiku:

| Lambda | Change | Rationale |
|--------|--------|-----------|
| `ai-expert-analyzer` | Sonnet → Haiku | Templated observatory content (KEY RECOMMENDATION / ELENA QUOTE tags) |
| `ai_calls._run_analysis_pass()` | Sonnet → Haiku | 200-token JSON dict extraction |
| `hypothesis-engine` | Sonnet → Haiku | Structured JSON hypothesis generation |
| `challenge-generator` | Sonnet → Haiku | Structured JSON challenge output |
| `field-notes-generate` | Sonnet → Haiku | Weekly lab notes |

**NOT downgraded:** daily-brief main calls, wednesday-chronicle, weekly-plate, nutrition-review, monday-compass, weekly-digest, partner-email (narrative content where quality matters).

All model assignments use `AI_MODEL` env var — rollback via `aws lambda update-function-configuration` without code deploy.

### 4. Infrastructure

- **Shared layer v41** published (CDK LifePlatformCore deploy)
- **constants.py** updated: `SHARED_LAYER_VERSION = 41`
- **CDK LifePlatformEmail** deployed — all email Lambdas on layer v41
- **12 standalone Lambdas** deployed individually via `deploy_lambda.sh`

## Deployment Status

| Component | Status | Method |
|-----------|--------|--------|
| `life-platform-site-api` | ✅ Deployed | `deploy_lambda.sh` |
| `ai-expert-analyzer` | ✅ Deployed | `deploy_lambda.sh` |
| `hypothesis-engine` | ✅ Deployed | `deploy_lambda.sh` |
| `challenge-generator` | ✅ Deployed | `deploy_lambda.sh` |
| `field-notes-generate` | ✅ Deployed | `deploy_lambda.sh` |
| `coach-narrative-orchestrator` | ✅ Deployed | `deploy_lambda.sh` |
| `coach-ensemble-digest` | ✅ Deployed | `deploy_lambda.sh` |
| `coach-state-updater` | ✅ Deployed | `deploy_lambda.sh` |
| `coach-quality-gate` | ✅ Deployed | `deploy_lambda.sh` |
| `coach-history-summarizer` | ✅ Deployed | `deploy_lambda.sh` |
| `journal-enrichment` | ✅ Deployed | `deploy_lambda.sh` |
| Shared layer v41 | ✅ Published | CDK `LifePlatformCore` |
| Email stack (all Lambdas) | ✅ Updated | CDK `LifePlatformEmail` |

## Pending / Blocked

1. **Anthropic API credits exhausted.** The API key in `life-platform/ai-keys` (ending `cQAA`) has insufficient credits. All AI generation returns `[AI_UNAVAILABLE]` (now gracefully handled by site API). User must add credits at [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing).

2. **Observatory content stale.** Once credits are added, regenerate:
   ```bash
   aws lambda invoke --function-name ai-expert-analyzer --region us-west-2 \
     --cli-binary-format raw-in-base64-out --payload '{"expert": "all"}' \
     --cli-read-timeout 300 /tmp/expert-output.json
   ```

3. **Cache metrics unverified.** Cannot confirm `AnthropicCacheReadTokens > 0` until API credits are active. First successful expert analyzer run will validate.

4. **Haiku quality unverified.** Expert analyzer, hypothesis engine, challenge generator, and field notes are now on Haiku but haven't run successfully yet. Monitor first outputs for quality regression. Rollback: set `AI_MODEL=claude-sonnet-4-6` env var per Lambda.

## Docs Updated

- `docs/DECISIONS.md` — ADR-049 (COST-OPT-2: Prompt Caching + Model Tiering)
- `docs/ARCHITECTURE.md` — layer version, cost table, prompt caching description
- `docs/RUNBOOK.md` — Anthropic cost monitoring section, model assignment table, rollback instructions

## Tests

1114 tests pass. 3 pre-existing integration failures (stale layer versions on 7 Lambdas not in this session's scope, DLQ messages, data reconciliation staleness).
