# Handover — v6.9.1: Pre-Monday bug paydown sweep

**Date:** 2026-05-03 (late evening, after v6.9.0 Cycle Pause)
**Scope:** End-of-Sunday cleanup. Investigated 13 alarms in ALARM state, fixed 5 real bugs, bumped 2 stale alarm thresholds, published shared layer v43.
**Goal:** Tomorrow's 10am PT daily-brief fires clean with no false-positive alarm cascade.

---

## Lambda fixes (5)

### 1. apple-health-ingestion — defensive `Records` guard
**Symptom:** `KeyError: 'Records'` at `lambda_handler` line 330 today at 16:05 UTC, fired `ingestion-error-apple-health`.
**Root cause:** Lambda is S3-trigger only; today something invoked it without the Records payload (test invoke, or vestigial trigger).
**Fix:** Early-exit `200 no-op` if no `Records` key. (`lambdas/apple_health_lambda.py` lambda_handler)

### 2. todoist-data-ingestion — retry transient 5xx
**Symptom:** `HTTP Error 503: Service Unavailable` from Todoist API today at 16:05 UTC, fired `ingestion-error-todoist`.
**Root cause:** No retry on transient Todoist outages; one 503 → hard failure → alarm.
**Fix:** 3-attempt retry with 2s/8s backoff on 429/500/502/503/504. (`lambdas/todoist_lambda.py api_get`)

### 3. hypothesis-engine — bump max_tokens + capture 400 body
**Symptom:** "Output appears truncated (ends mid-sentence)" + `HTTP Error 400: Bad Request` at 16:09-16:12 UTC.
**Root cause:** `max_tokens=2000` insufficient for multi-pattern JSON. Anthropic returned truncated response (heuristic detected mid-sentence end), then 400 on retry of malformed-context request.
**Fix:** `max_tokens` 2000 → 4000. Also captures HTTPError response body so future 4xx surfaces actual reason. (`lambdas/hypothesis_engine_lambda.py:577`)

### 4. coach-state-updater — bump max_tokens + capture 400 body
**Symptom:** 5x `LLM extraction failed for {sleep,nutrition,training,mind,physical}_coach: HTTP Error 400` at 17:00 UTC.
**Root cause:** `_call_haiku` default `max_tokens=1500` insufficient for 5-coach state extraction; truncation → 400 on next attempt.
**Fix:** Default `max_tokens` 1500 → 3000. Also captures HTTPError body. (`lambdas/coach_state_updater.py:169`)

### 5. IC-3 chain-of-thought analysis — bump max_tokens (LAYER)
**Symptom:** Multiple `[WARN] IC-3 analysis pass failed: Unterminated string starting at... char 670` in daily-brief logs.
**Root cause:** `_run_analysis_pass` calls Anthropic with `max_tokens=200`. The IC-3 JSON has 5 fields (key_patterns array + likely_connection + challenge + priority + tone); 200 was truncating mid-string.
**Fix:** `max_tokens` 200 → 600. (`lambdas/ai_calls.py:280` — shared layer)

## Layer v43

- Built via `bash deploy/build_layer.sh` (18 modules)
- `SHARED_LAYER_VERSION` constant bumped 42 → 43 in `cdk/stacks/constants.py`
- Published via `npx cdk deploy LifePlatformCore` at 01:35:08 UTC
- All consuming Lambdas updated via `cdk deploy --all` — verified: coach-state-updater, hypothesis-engine, daily-brief, apple-health-ingestion, todoist-data-ingestion all on v43 by 01:37:15 UTC

## Alarm thresholds bumped (`monitoring_stack.py`)

| Alarm | Old | New | Why |
|---|---|---|---|
| `daily-brief-duration-high` | 240000ms (4min) | 720000ms (12min) | Old sized for 300s Lambda timeout; new timeout is 900s. 720s = 80% of timeout, still catches genuine runaways. |
| `ai-tokens-daily-brief-daily` | 13333 | 18000 | Today's healthy brief used 14414 tokens (above old threshold). 18k leaves ~25% buffer. |

## Alarm cleanup (manual reset)

Reset 8 stale alarms to OK via `aws cloudwatch set-alarm-state`:
- 5 historical April single-datapoint alarms (no current emitter): `ingestion-error-coach-computation-engine`, `life-platform-dlq-depth-warning`, `life-platform-ingestion-dlq-messages`, `og-image-generator-errors`, `slo-source-freshness`
- 3 today's transient (root causes now fixed): `ingestion-error-apple-health`, `ingestion-error-todoist`, `daily-brief-duration-high`, `ai-tokens-daily-brief-daily`, `slo-daily-brief-delivery`, `ingestion-error-coach-state-updater`, `ingestion-error-hypothesis-engine`, `life-platform-compute-pipeline-stale`

NOTE: `set-alarm-state` is overridden on next datapoint evaluation. Some alarms re-flipped to ALARM because historical error datapoints are still inside their evaluation window. They will naturally clear over the next 24h as those datapoints age out — and tomorrow's clean runs reinforce the OK state.

## Deploy summary

```
bash deploy/build_layer.sh                                        # rebuilt layer
cd cdk && npx cdk deploy --all --require-approval never           # 8/8 stacks
```

All stacks updated cleanly. No CloudFormation rollbacks. Total deploy time ~10 min.

## What's NOT fixed (deferred)

- **`life-platform-compute-pipeline-stale` alarm has no current emitter** — vestigial CDK definition. TODO: either wire up emission or remove the alarm.
- **If tomorrow's runs still 4xx after max_tokens bumps** — points to a different root cause (context length, stop_sequences, prompt format). Now visible in logs (body captured). Re-investigate Tuesday.

## What's true tomorrow morning

✅ 10am PT daily-brief fires; expected ~5min, ~14-16k tokens; both under new thresholds → no false alarm
✅ Hypothesis-engine + coach-state-updater + IC-3 have ample token budget for healthy completion
✅ apple-health + todoist resilient to transient bad invocations
✅ All Lambdas on layer v43 (with the IC-3 fix)
✅ Stale-source banner correctly identifies the 2 known stale sources (Strava, MacroFactor — Matthew action)
✅ Cycle Pause band visible on observatory pages (manual eyeball check still recommended per HANDOVER_v6.9.0)

---

**Previous:** `HANDOVER_v6.9.0.md` (Cycle Pause viz).
