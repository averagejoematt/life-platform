# Root Cause Analysis: Apple Health Data Pipeline Failure

**Incident Date:** February 24, 2026  
**Duration:** ~4 hours (approx 10:30 AM – 2:50 PM PT)  
**Severity:** Low (data pipeline, no production service impact)  
**Author:** Claude (AI-assisted development session)  
**Status:** Resolved

---

## Executive Summary

Apple Health data stopped flowing into DynamoDB. Investigation consumed ~4 hours, with the majority spent troubleshooting the wrong component (the iOS app, Health Auto Export) when the root cause was a Lambda code deployment timing issue on our side. The app was working correctly the entire time.

---

## Timeline

| Time (PT) | Event |
|-----------|-------|
| ~10:30 AM | Matthew reports Stelo CGM glucose data not appearing in DynamoDB |
| 10:30–11:00 | Claude investigates DynamoDB, finds only steps + resting HR for recent days. Frames as "Health Auto Export not sending data" |
| 11:00–11:30 | Multiple manual syncs triggered in Health Auto Export (12:12, 13:08 timestamps on app). App shows green checkmarks. No new Lambda invocations observed in `apple-health-ingestion` Lambda logs |
| 11:30–12:00 | Claude drafts Discord support post blaming Health Auto Export app. Investigates native Apple Health export to verify data exists at source |
| 12:00–12:30 | Matthew performs native Apple Health export. 1GB XML confirms data IS in Apple Health (steps, HR, sleep, gait, audio — 12,000+ records in Feb alone). But zero glucose records → identifies Stelo permissions issue |
| 12:30–1:00 | Matthew fixes Stelo → Apple Health permissions. Claude continues drafting Discord support post |
| ~1:00 PM | **Claude identifies two separate Lambdas exist**: `apple-health-ingestion` (old, manual export path) and `health-auto-export-webhook` (new, webhook path via API Gateway). We had been checking logs for the WRONG Lambda the entire time |
| 1:00–1:05 PM | Check `health-auto-export-webhook` logs → **invocations from today found**. App WAS sending data successfully |
| 1:05 PM | Read webhook Lambda logs closely: 48 metrics received at 18:53 UTC (11:53 AM PT), but result shows `other_metric_days: 0`. Code was deployed at 19:37 UTC — **the payload hit the pre-update Lambda version that only processed glucose** |
| 1:10 PM | Later 4-metric sync at 19:21 UTC hit the updated code → successfully wrote steps, walking_speed, heart_rate_apple. **Pipeline confirmed working** |
| ~2:44 PM | Matthew triggers manual sync in foreground. Full 48-metric payload arrives, 14 metrics matched, 34 correctly skipped (SOT), 2 days updated with 14 fields each |
| 2:50 PM | DynamoDB verified: Feb 24 fully populated with steps, calories, gait, HR, SpO2, respiratory rate, headphone audio, flights climbed |

---

## Root Cause

**The iOS app was never broken.** Two compounding issues created the false appearance of an app-side failure:

### Primary: Wrong Lambda investigated
The platform has two Apple Health ingestion paths:

1. `apple-health-ingestion` — triggered by S3 upload of manual export.xml (legacy path)
2. `health-auto-export-webhook` — triggered by API Gateway from Health Auto Export app (current path)

When investigating, Claude checked CloudWatch logs for `apple-health-ingestion` (last invocation: Feb 22) and concluded the app wasn't sending data. In reality, the app was hitting `health-auto-export-webhook` via API Gateway (`a76xwxt2wa.execute-api...`) → the correct Lambda was receiving and processing requests the whole time.

### Secondary: Deployment timing
The `health-auto-export-webhook` Lambda was updated at 19:37 UTC to process all metric types (v1.1.0: three-tier source filtering). The app's large 48-metric sync arrived at 18:53 UTC — 44 minutes BEFORE the update deployed. The old code only processed blood glucose and silently dropped everything else. This made it look like the app was sending incomplete data.

### Tertiary: Intermittent iOS delivery
Some manual sync attempts genuinely didn't produce Lambda invocations (iOS background execution throttling). This reinforced the false narrative that the app was broken, when it was actually an orthogonal iOS platform issue.

---

## What Went Wrong (Process Failures)

### 1. Assumed external failure before checking internal pipeline
**What happened:** The initial hypothesis was "Health Auto Export app isn't sending data" rather than "our pipeline isn't processing data correctly."  
**Impact:** 2+ hours spent troubleshooting the app (screenshots, manual syncs, Discord post draft, native export analysis) when a 5-minute CloudWatch log check on the correct Lambda would have found the issue.

### 2. Checked the wrong Lambda
**What happened:** The platform has two similarly-named Lambdas for Apple Health data. Claude checked `apple-health-ingestion` (the legacy S3-triggered path) instead of `health-auto-export-webhook` (the active webhook path).  
**Why:** No clear mapping documented between "Health Auto Export app sends data to endpoint X which triggers Lambda Y." The API Gateway → Lambda wiring was invisible without explicitly querying `apigatewayv2 get-integrations`.

### 3. No end-to-end observability
**What happened:** There was no dashboard, alarm, or log aggregation showing "webhook received → metrics parsed → DynamoDB written" as a single traceable flow. Each component had to be investigated independently.  
**Impact:** Debugging required manually querying CloudWatch log streams, API Gateway routes, and DynamoDB items in sequence.

### 4. Confirmation bias from intermittent iOS failures  
**What happened:** Some manual syncs genuinely failed to deliver (iOS background throttling). This reinforced the "app is broken" hypothesis and delayed investigation of the backend.

---

## What Went Right

1. **Native Apple Health export** correctly proved data existed at source, ruling out upstream issues
2. **Stelo → Apple Health permissions** issue was identified and fixed as a side benefit
3. **Three-tier SOT filtering** in the webhook Lambda worked perfectly once hit with updated code
4. **S3 raw archiving** preserved all payloads, enabling replay/backfill without re-syncing from the app
5. **`update_item` merge pattern** in the Lambda preserved existing data while adding new fields

---

## Corrective Actions

### Immediate (do now)

| # | Action | Status |
|---|--------|--------|
| 1 | ~~Verify pipeline working end-to-end with manual foreground sync~~ | ✅ Done |
| 2 | ~~Run historical backfill from native export.xml~~ | 🔄 In progress |
| 3 | Change Health Auto Export sync cadence from 4h to desired interval | 📋 Pending |
| 4 | Verify Stelo glucose data appears in Apple Health after re-auth (24-48h) | 📋 Pending |

### Short-term (next session)

| # | Action | Priority |
|---|--------|----------|
| 5 | **Add CloudWatch alarm** on `health-auto-export-webhook` for zero invocations in 24h | High |
| 6 | **Document API Gateway → Lambda mapping** in ARCHITECTURE.md (endpoint → route → integration → Lambda) | High |
| 7 | **Add structured logging** with request ID tracing: `{request_id, source, metrics_count, days_written, duration_ms}` | Medium |
| 8 | **Add CloudWatch dashboard** showing webhook invocations/day, metrics processed/day, error rate | Medium |
| 9 | **Fix auth header loss** on batch requests (some arrive without Bearer token → 401) | Medium |

### Long-term (backlog)

| # | Action | Priority |
|---|--------|----------|
| 10 | **Consolidate Apple Health Lambdas** — deprecate `apple-health-ingestion` (legacy S3 path) now that webhook is primary. One Lambda, one code path, less confusion | Medium |
| 11 | **Add data freshness check** to daily brief — flag if any source hasn't updated in 24h | Medium |
| 12 | **Webhook health check endpoint** — GET /health returns 200 so uptime monitoring can catch outages | Low |

---

## Lessons Learned

### For AI-assisted debugging sessions

1. **Start with YOUR pipeline, not the external dependency.** When data isn't flowing, the first 5 minutes should be: check CloudWatch logs for the receiving Lambda, check API Gateway access logs, check DynamoDB writes. Only investigate the sending app after confirming your receiver isn't the problem.

2. **Know your architecture.** Two Lambdas with overlapping names (`apple-health-ingestion` vs `health-auto-export-webhook`) and no clear documented mapping from endpoint → Lambda caused us to investigate the wrong component. Architecture docs should trace the full request path.

3. **Check deployment timing.** When code was recently updated, always ask: "did the payload arrive before or after the deploy?" This is especially relevant for webhook-driven systems where there's no retry on the sender's side.

4. **Don't draft external support requests before exhausting internal investigation.** We spent time composing a Discord post that would have been embarrassing to send — the app was working fine. Rule: confirm the issue is NOT on your side before asking for external help.

5. **Build observability upfront.** A single CloudWatch alarm ("zero webhook invocations in 24h") would have surfaced this issue in the morning brief, not during a 4-hour debugging session.

---

## Metrics

- **Time to detect:** ~2 days (last successful invocation was Feb 22; issue noticed Feb 24)
- **Time to diagnose:** ~3.5 hours (mostly spent on wrong hypothesis)
- **Time to resolve:** ~15 minutes (once correct Lambda identified)
- **Data loss:** None (S3 archives preserved all payloads; backfill recovers historical data)
- **Estimated wasted effort:** ~3 hours of human + AI time on wrong investigation path
