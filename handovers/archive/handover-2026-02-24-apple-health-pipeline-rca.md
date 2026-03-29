# Session Handover — 2026-02-24 (evening) — Apple Health Pipeline Fix + RCA

**MCP Server Version:** v2.16.1 (57 tools)
**Session focus:** Apple Health data pipeline debugging, historical backfill, RCA + corrective actions

---

## What Was Done

### 1. Diagnosed Apple Health Pipeline Failure
- **Symptom:** Apple Health data (steps, calories, gait, CGM) not appearing in DynamoDB
- **Root cause:** Two Lambdas exist for Apple Health (`apple-health-ingestion` legacy S3 path, `health-auto-export-webhook` active webhook path). We investigated the wrong one for ~3 hours. The webhook Lambda was receiving data but the 48-metric payload hit old code (pre v1.1.0 deploy) that only processed glucose
- **Resolution:** Confirmed pipeline working end-to-end with foreground manual sync. Full 48 metrics received, 14 matched, 34 correctly skipped (SOT filtering)

### 2. Fixed Stelo → Apple Health Permissions
- Dexcom Stelo CGM was not writing glucose to Apple Health (separate issue from webhook)
- Matthew re-authorized Apple Health write permissions in Stelo app
- Verification pending (24-48h for data to appear)

### 3. Historical Backfill (786 Days)
- Script: `backfill_apple_health_export.py`
- Source: native Apple Health export.xml (1.06 GB)
- Result: 786 days written (2024-01-01 → 2026-02-24), zero errors
- 37,011 CGM glucose readings saved to S3
- 21 fields per day: steps, active/basal calories, total_calories_burned, distance, flights, gait metrics (speed, step length, double support, asymmetry, steadiness), headphone audio, glucose aggregates
- SOT-aware: skipped nutrition (MacroFactor), sleep (Eight Sleep), body comp (Withings)
- Tier 2 fields (HR, HRV, RHR, SpO2, respiratory) not populated from export — Apple Watch source tags in XML don't match filter. These flow correctly via the webhook Lambda

### 4. RCA Document
- Full RCA saved: `RCA_2026-02-24_apple_health_pipeline.md`
- Timeline, root cause, process failures, corrective actions, lessons learned

### 5. Corrective Actions Implemented
- **CloudWatch alarm:** `health-auto-export-no-invocations-24h` → SNS alert on zero invocations in 24h
- **ARCHITECTURE.md:** Full request path documented (endpoint → API Gateway `a76xwxt2wa` → route `POST /ingest` → integration `mxskreu` → `health-auto-export-webhook` Lambda). Warning added about legacy `apple-health-ingestion` Lambda confusion
- **Structured logging (v1.2.0):** Deployed. JSON log on every completion: `event`, `request_id`, `metrics_count`, `matched_metrics`, `skipped_sot`, `duration_ms`, `payload_bytes`. Auth failures also logged with `request_id`
- **CHANGELOG:** v2.16.1 entry added

### 6. Pending User Action
- **Update Health Auto Export URLs** — append `?key=NduA...D5g` to both automation URLs in the app (fixes batch request auth header drops). Bearer token stays in header field too

---

## Current Pipeline State

**Health Auto Export → API Gateway → `health-auto-export-webhook` Lambda → DynamoDB + S3: ✅ WORKING**

Last successful full sync: Feb 24, 22:43 UTC (48 metrics, 14 matched, 2 days updated)

DynamoDB `apple_health` records: 786 days (2024-01-01 → 2026-02-24) with 21 fields per day + CGM glucose aggregates

### Two Apple Health Ingestion Paths
| Path | Lambda | Trigger | Status |
|------|--------|---------|--------|
| Webhook (primary) | `health-auto-export-webhook` | API Gateway POST | ✅ Active, 4h cadence |
| Manual export (legacy) | `apple-health-ingestion` | S3 PutObject | ⚠️ Legacy, not SOT-filtered |

---

## Files Created/Modified

| File | Action |
|------|--------|
| `RCA_2026-02-24_apple_health_pipeline.md` | Created — full root cause analysis |
| `backfill_apple_health_export.py` | Created — SOT-aware XML backfill script |
| `replay_s3_archive.py` | Created — replay S3-archived webhook payloads through Lambda |
| `health_auto_export_lambda.py` | Modified — v1.2.0 structured logging + auth tracking |
| `deploy_health_auto_export_webhook.sh` | Created — deploy script for webhook Lambda |
| `ARCHITECTURE.md` | Modified — full request path, alarm, legacy Lambda warning |
| `CHANGELOG.md` | Modified — v2.16.1 entry |

---

## Backlog (from RCA)

| # | Action | Priority |
|---|--------|----------|
| 10 | Consolidate `apple-health-ingestion` (legacy) into `health-auto-export-webhook` — one Lambda, one code path | Medium |
| 11 | Add data freshness check to daily brief — flag if any source hasn't updated in 24h | Medium |
| 12 | Webhook health check endpoint — GET /health returns 200 for uptime monitoring | Low |

---

## Key Lesson

**When data isn't flowing, start with YOUR pipeline (CloudWatch logs for the receiving Lambda), not the external dependency.** A 5-minute `apigatewayv2 get-integrations` check would have found the issue immediately instead of a 3.5-hour debugging session.
