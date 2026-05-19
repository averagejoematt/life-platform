# Handover — v6.9.2: CI unblock + alarm noise reduction

**Date:** 2026-05-03 (very late evening, after v6.9.1 paydown sweep)
**Trigger:** User reported inbox flooded with alarm emails at 8:14pm PT, asked about open bugs/tech debt.
**Scope:** Two real bugs found and fixed; everything else properly tracked + intentionally deferred.

---

## What changed

### Fix 1: CI unblocked

**Symptom:** GitHub Actions CI/CD failure on commit `34aea27` (the parallel chronicle commit). Every push to main since b227b13 (the daily-brief 768MB bump earlier today) fails the `test_email_stack_memory_limits` assertion.

**Root cause:** `tests/test_lambda_sizing.py:82` asserted `mb <= 512` across all email-stack Lambdas. Daily-brief was bumped to 768MB legitimately (6-coach narrative pass needed headroom), but the test wasn't updated.

**Fix:** Added a 768MB exception for daily-brief specifically. Detection matches `daily-brief`, `daily_brief`, or `DailyBrief` in the parsed context (handles the underscore/hyphen/CamelCase variants because the regex captures both `function_name=` and `source_file=` neighborhoods). All 5 tests in the sizing suite now pass.

```python
ctx_lower = ctx.lower()
is_daily_brief = "daily-brief" in ctx_lower or "daily_brief" in ctx_lower or "DailyBrief" in ctx
cap = 768 if is_daily_brief else 512
```

### Fix 2: Alarm noise reduction (root cause of tonight's inbox flood)

**Symptom:** Inbox at 8:14pm PT showed dozens of `ALARM "ingestion-error-*"` emails firing repeatedly between 6:44pm and 7:57pm — even after my v6.9.1 manual `set-alarm-state OK` resets at ~6:35pm.

**Root cause:** `cdk/stacks/lambda_helpers.py:229` set `period=Duration.hours(24)` on every Lambda's error alarm. With a 24h evaluation window and single-datapoint threshold, a transient error stays in ALARM for 24h, and `set-alarm-state OK` is overridden on the next eval cycle (CloudWatch re-evaluates against the still-in-window historical datapoint). Result: cascade emails for 24h after a single blip.

**Fix:** `period=Duration.hours(1)`. A transient error now self-clears within an hour; sustained failures still re-fire as new errors come in (so we don't lose signal). Net: dramatically less inbox noise, same actionable visibility.

Single-line change in the shared helper → propagates to all ~30 `ingestion-error-*` alarms across all stacks via `cdk deploy --all`.

### Manual cleanup

After deploy, manually OK'd 8 in-flight ALARM-state alarms. With the new 1h window, historical errors from 16:00-17:00 UTC today are now outside the evaluation window, so the OK state sticks (no auto-revert). Confirmed: zero alarms in ALARM as of 8:30pm PT.

---

## Other findings from the audit (all properly tracked, intentionally deferred)

### Code TODOs whose data gate has now passed (10 functions)

`lambdas/failure_pattern_compute_lambda.py` (4 TODOs) and `lambdas/momentum_warning_compute_lambda.py` (6 TODOs) all marked "Implement when data gate met (~2026-05-01)". Today is 2026-05-03 — gate passed. These are stub functions returning placeholder data. Implementing them is real work (~2-4h) requiring fresh design. **Flag for next session.**

### Vestigial CDK alarm

`life-platform-compute-pipeline-stale` has no current emitter for the `LifePlatform/ComputePipelineStaleness` metric. Either wire up a heartbeat emitter or remove the alarm. Already noted in HANDOVER_v6.9.1.md. **Decide next session.**

### Open TDs (Matthew action / approval gated, no work tonight)

| Item | State |
|---|---|
| TD-11 step 2 (Habitify schema design) | Awaiting Matthew approval |
| TD-17 (HAE Tier-2 feeds) | iOS app config — Matthew action |
| TD-19 phase 3 (historical partition migration) | Awaiting Matthew approval |

### Open WRs (intentionally deferred)

| Item | State |
|---|---|
| WR-14, WR-15, WR-20 | Matthew-only content (story page, photos, video) |
| WR-17 (Lambda@Edge Function URL 403) | Partial — needs investigation |
| WR-47 phase 2 (server-side scoring suppression + public banner) | Phase 1 shipped v6.9.0; phase 2 needs design |
| WR-49 (one-click manual backfill UI) | Not specced |
| WR-50 (re-entry day template) | Gated on WR-47 phase 2 |

### Anthropic 4xx behavior

Logs confirm no NEW Lambda invocations since v6.9.1 deploy. The post-7pm alarm fires were re-evaluations of the morning's errors (now mitigated by the 1h period change). Tomorrow's natural runs (10am PT daily-brief, every-hour ingestions) will exercise the v6.9.1 max_tokens fixes. If 4xx persists, the response body is now captured in logs to diagnose.

---

## Deploy summary

```
# Fix 1: pure test change, no AWS deploy
python3 -m pytest tests/test_lambda_sizing.py -v   # 5/5 passed

# Fix 2:
cd cdk && npx cdk deploy --all --require-approval never
# → 8/8 stacks updated, ~30 alarms re-pointed to Period=3600
```

---

## State as of 8:30pm PT (v6.9.2 deploy complete)

| Metric | Value |
|---|---|
| Alarms in ALARM | **0** |
| CI status | Will be green on next push |
| Lambda layer | v43 (unchanged from v6.9.1) |
| 6 observatory pages | Cycle pause band live (per v6.9.0) |
| 5 Lambda fixes from v6.9.1 | Deployed, awaiting tomorrow's natural runs to verify |

## What's true tomorrow morning

✅ 10am PT daily-brief expected ~5min, ~14-16k tokens (under thresholds)
✅ Any single transient ingestion error self-clears within 1h instead of 24h
✅ Inbox quiet unless something genuinely sustained breaks
✅ Cycle pause band visible on observatory pages

---

**Previous:** `HANDOVER_v6.9.1.md` (Pre-Monday bug paydown sweep — 5 Lambda fixes + 2 alarm threshold bumps + layer v43)
