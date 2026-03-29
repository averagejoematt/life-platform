# Handover — 2026-03-07: Data-Aware Compute + CGM Fix
**Version:** v2.84.3  
**Previous handover:** 2026-03-07_secret_sweep_qa_infra.md

---

## Session Summary

Two things accomplished: fixed a structural design flaw in the compute pipeline, and confirmed real CGM data is now flowing.

---

## 1. Data-Aware Idempotency — daily-metrics-compute (v2.84.3)

### Problem
`daily-metrics-compute` used time-based idempotency — once computed for a date, it would skip on all subsequent runs regardless of whether source data had updated. Late-arriving HAE data (e.g. water landing at 7 PM after the 9:40 AM compute) produced stale scores with missing components visible in the daily brief.

### Solution
Replaced "skip if computed today" with "skip if inputs unchanged":

- **`get_source_fingerprints(date)`** — reads `webhook_ingested_at` from each source record (whoop, apple_health, macrofactor, strava, habitify, withings) for the target date
- **`fingerprints_changed(stored, current)`** — ISO string comparison; returns True if any source is newer
- **`store_computed_metrics()`** — now persists `source_fingerprints` map alongside scores
- **`lambda_handler`** — on each run: fetch current fingerprints → compare to stored → skip if unchanged, recompute with reason logged if changed

Behaviour on legacy records (no stored fingerprints): treated as stale, reruns once to populate fingerprints, then becomes data-aware going forward.

### EventBridge
New rule `daily-metrics-compute-catchup` — `rate(30 minutes)` — fires all day. No-op cost once inputs stabilise (~65ms skip). Lambda permission added for new rule ARN.

### Files changed
- `lambdas/daily_metrics_compute_lambda.py` — new functions + idempotency rewrite + fingerprint storage
- `deploy/deploy_metrics_compute.sh` — new deploy script (bundles scoring_engine.py alongside lambda_function.py)

### Verified in logs
```
Recomputing 2026-03-06 — no fingerprint stored (legacy record)
Source fingerprints: {'apple_health': '2026-03-07T19:08:06', 'macrofactor': '...', 'strava': '...'}
  hydration   100 ✅
  glucose     100 ✅
Done in 0.7s
```

---

## 2. CGM Data — Now Confirmed Real

### Problem
7-day DDB check showed `cgm_source: manual`, 1 reading/day — looked like manual fingerstick entries, not continuous Dexcom data.

### Investigation
- Weekly view in Health app showed daily averages as single dots (misleading)
- Day view confirmed real continuous Dexcom Stelo data was in HealthKit (~269–288 readings/day)
- Root cause: HAE was sending aggregated daily summary to webhook, not individual samples

### Fix
Matthew forced a 7-day HAE push with individual samples. Result:

| Date | Source | Readings | Avg | Std Dev |
|------|--------|----------|-----|---------|
| Mar 1 | dexcom_stelo | 269 | 88.7 | 9.1 |
| Mar 2 | dexcom_stelo | 280 | 91.9 | 7.1 |
| Mar 3 | dexcom_stelo | 284 | 88.4 | 7.7 |
| Mar 4 | dexcom_stelo | 275 | 89.8 | 6.1 |
| Mar 5 | dexcom_stelo | 288 | 86.4 | 7.0 |
| Mar 6 | dexcom_stelo | 109 | 83.3 | 5.8 |

Mar 6 partial (109 readings) consistent with ~36hr sensor gap. Mar 7 no data (mid-day, sensor off).

The data-aware compute will auto-recompute all 6 days on next catchup cycle since fingerprints changed.

**HAE note:** Whatever setting was changed to enable individual samples on the 7-day force push — keep that as the default going forward.

---

## Data Gap Assessment (Apple Health — 7-day)

| Metric | Status |
|--------|--------|
| Steps | ✅ All 7 days |
| Water | ✅ All 7 days (backfilled via manual JSON export earlier) |
| CGM | ✅ Mar 1–6 now real Dexcom data; Mar 7 partial (sensor gap) |
| SoM | ⚠️ Only Mar 5 has check-ins — Matthew noted not doing SoM regularly, expected |
| Gait/walking | ✅ Present most days |

---

## Pending Items

- **[NEXT]** Google Calendar integration — Board rank #2
- **[PENDING]** Brittany weekly accountability email — prerequisite: reward seeding  
- **[PENDING]** Reward seeding → Character Sheet Phase 4
- **[PENDING]** `deploy_lambda.sh` multi-module fix (daily-brief still needs manual deploy command)
- **[WATCH]** HAE individual samples setting — confirm it persists for ongoing syncs (not just the manual 7-day push)
- **[WATCH]** Notion data gap since v2.75.0 — journal entries may be missing; assess whether backfill needed

---

## Commands for Reference

**Force recompute a date:**
```bash
aws lambda invoke --function-name daily-metrics-compute --region us-west-2 \
  --payload '{"force": true, "date": "YYYY-MM-DD"}' /tmp/out.json
```

**Deploy metrics compute:**
```bash
cd /Users/matthewwalker/Documents/Claude/life-platform
bash deploy/deploy_metrics_compute.sh
```
