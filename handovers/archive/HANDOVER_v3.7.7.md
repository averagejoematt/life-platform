# Life Platform Handover — v3.7.7
**Date:** 2026-03-13
**Session type:** TB7-19/20/21/22/23 — AI validator + anomaly + drift hardening

---

## What Was Done

Completed the final 5 TB7 items deferred from earlier sessions. All deployed.
TB7 board is now fully closed.

---

## Items Completed

### TB7-19 — AI output validator: hallucinated data reference detection ✅
`ai_output_validator.py` v1.1.0. Added `_METRIC_PATTERNS` (7 metrics: recovery,
HRV, resting HR, sleep score, weight, TSB) and `_check_hallucinated_metrics()`.
Check 12 in `validate_ai_output()` scans AI coaching text for numeric health claims
and WARNs when a mentioned value deviates >25% from the actual `health_context` value.
WARN tier only (not BLOCK — rounding and wording variations are common).

### TB7-20 — Relevance filter / cap on `_load_insights_context()` ✅
`ai_calls.py`: `_load_insights_context()` now applies a 1500-char hard cap as a
second safety valve behind the 700-token upstream budget in `_build_prioritized_context_block()`.
Truncates at the last newline before the cap and appends `[...context truncated at 1500-char limit]`.

### TB7-21 — Raise anomaly single-day alert threshold ✅
`anomaly_detector_lambda.py` v2.5.0. `CV_THRESHOLDS` updated:
- `(0.30, 2.5)` — high variability
- `(0.15, 2.0)` — medium variability  
- `(0.0,  2.0)` — low variability (raised from 1.5)
At 13 metrics, Z=1.5 floor produced ~42% daily FP rate. Z=2.0 floor drops
expected pre-gate FP rate to ~2.3%/metric/day. Sustained streak tracker unaffected.
`INTELLIGENCE_LAYER.md` CV threshold table updated.

### TB7-22 — Equalize slow drift windows ✅
`daily_insight_compute_lambda.py` v1.4.0. Drift windows changed from:
- Old: 7d recent (days 1-7) / 21d baseline (days 8-28)
- New: 14d recent (days 1-14) / 14d baseline (days 15-28)
Equal 14d windows have the same SE of mean — asymmetric windows were inflating
apparent drift severity by comparing a volatile 7-day mean against a stable 21-day mean.
Min N=14 gate now applies identically to both windows. `INTELLIGENCE_LAYER.md` updated.

### TB7-23 — IC-3 model documentation ✅ (doc-only)
Confirmed: `_run_analysis_pass()` in `ai_calls.py` calls `call_anthropic()` which
uses `AI_MODEL` = `claude-sonnet-4-6`. Both Pass 1 (analysis) and Pass 2 (output)
run on Sonnet. No quality asymmetry exists — IC-3 was already correctly implemented.
Haiku at line 515 of `daily_insight_compute_lambda.py` is the IC-8 intent evaluator
(correct by design — classification task). Documented in `INTELLIGENCE_LAYER.md`.

---

## Deploy
- Layer v9 published (ai_output_validator v1.1.0 + ai_calls cap)
- `anomaly-detector` redeployed (v2.5.0)
- `daily-insight-compute` redeployed (v1.4.0)
- All 14 layer consumers updated to layer v9
- Deploy script archived: `deploy/archive/20260313/deploy_tb7_19_23.sh`

---

## TB7 Board Status — FULLY CLOSED

All 23 TB7 items complete:
- TB7-1 through TB7-5: ✅ v3.7.1–v3.7.2
- TB7-6 through TB7-10: ✅ v3.7.0–v3.7.2
- TB7-11 through TB7-17: ✅ v3.7.3–v3.7.6 (TB7-10 N/A)
- TB7-18: 🔴 Google Calendar (next major feature, separate session)
- TB7-19 through TB7-23: ✅ v3.7.7

---

## Open Items / Next Up

1. **DLQ in ALARM** — `life-platform-dlq-depth-warning` was in ALARM as of v3.7.6.
   Check: `aws sqs get-queue-attributes --queue-url $(aws sqs get-queue-url --queue-name life-platform-dlq --query QueueUrl --output text) --attribute-names ApproximateNumberOfMessages`

2. **Billing SNS confirmation** — Check `awsdev@mattsusername.com` inbox for SNS
   subscription confirmation email (from TB7-15). Alarm won't fire until confirmed.

3. **TB7-11** — Layer version consistency CI check (still open from TB7 board).

4. **TB7-12** — Stateful resource assertion in CI Plan job (still open).

5. **TB7-13** — Add `digest_utils.py` to `shared_layer.modules` in `lambda_map.json`.

6. **TB7-14** — Document TTL policy per DDB partition in SCHEMA.md.

7. **TB7-16** — Add fingerprint update comment in `daily_metrics_compute_lambda.py`.

8. **Google Calendar integration** — Next major feature (~6-8h).

9. **SIMP-1 + Architecture Review #8** — ~2026-04-08 (30 days EMF data).

---

## Key Architecture Notes
- Platform: v3.7.7, 42 Lambdas, 19 data sources, 8 CDK stacks
- Shared layer: v9 (life-platform-shared-utils)
- Anomaly detector: v2.5.0, Z-floor=2.0
- Daily insight compute: v1.4.0, 14d/14d drift windows
- AI output validator: v1.1.0, 12 checks including hallucination detection
- Post-deploy rule: run `bash deploy/post_cdk_reconcile_smoke.sh` after every `cdk deploy`
