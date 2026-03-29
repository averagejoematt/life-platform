# Handover — 2026-02-25 — Dropbox MacroFactor Pipeline

## Session Goal
Eliminate laptop dependency from MacroFactor CSV ingestion by adding a Dropbox polling Lambda.

## What Was Done

### 1. Dropbox Poll Lambda (`dropbox-poll`)
New Lambda that polls Dropbox `/life-platform/` folder every 30 minutes for MacroFactor CSVs.

**Flow:** Phone → MacroFactor export → Share to Dropbox → Save to `/life-platform/` → Lambda picks up within 30 min → S3 → existing macrofactor-data-ingestion pipeline → DynamoDB

**Key implementation details:**
- OAuth2 refresh token flow with explicit scope parameter in authorization URL
- Credentials stored in Secrets Manager (`life-platform/dropbox`)
- Content-hash dedup (SHA256, first 16 chars) tracked in DynamoDB (`USER#matthew#SOURCE#dropbox_tracker`)
- Processed files moved to `/life-platform/processed/` subfolder (rolling 7-day window)
- CSV header validation: accepts files containing "Food Name", "Calories", "Protein", "Carbs", "Fat", or "Date"
- Download uses `Content-Type: application/octet-stream` header (required by Dropbox content API)

### 2. MacroFactor Ingestion v1.1.0
Updated `macrofactor-data-ingestion` Lambda to auto-detect CSV type:
- "Food Name" header → nutrition diary path (existing)
- "Exercise" + "Set Type" headers → workout path (new, merged from `backfill_macrofactor_workouts.py`)
- Unknown formats logged and skipped

Workout data stored under `USER#matthew#SOURCE#macrofactor_workouts` with full exercise/set/rep/weight detail.

### 3. Water Intake (Apple Health v1.3.0)
- `dietary_water` added to Apple Health webhook metric map
- Converts fl_oz_us → mL, stores both units
- 16th SOT domain: `water` → `apple_health`

### 4. Notion Journal Phase 4 (v2.17.0)
- Daily Brief: Journal Pulse section (mood/energy/stress gauges, themes, quote)
- Weekly Digest: Journal & Mood section with W-o-W deltas

## Debugging Journey — Dropbox API

The Dropbox integration required significant debugging:

1. **OneDrive abandoned** — Microsoft tenant restrictions require M365 Developer Program for personal accounts
2. **App Folder vs Full Dropbox** — First Dropbox app used "App folder" access type which creates a sandboxed `/Apps/Life Platform/` folder invisible in iOS share sheet. Switched to "Full Dropbox" access type.
3. **Phone sync issue** — Files visible on phone but not on browser or API. Caused by phone Dropbox app having stale session. Logging out and back in on phone fixed it.
4. **Scoped token with no file access** — For scoped Dropbox apps, the OAuth authorization URL MUST include an explicit `scope` parameter listing requested permissions. Without it, the token is issued with essentially no file access (can list folders but not see files). Fix: added `scope=account_info.read files.metadata.read files.metadata.write files.content.read files.content.write` to auth URL.
5. **Refresh token only on first auth** — Dropbox only issues a refresh token on the FIRST authorization. Re-authorizing returns only an access token. Must disconnect app from Settings → Connected Apps before re-authorizing to get a new refresh token.
6. **Download 400 error** — Initial download function sent `data=b""` which caused urllib to add an unwanted Content-Type header. Fixed by setting `Content-Type: application/octet-stream` explicitly and using `req.data = b""`.

## Files Created/Modified

| File | Status |
|------|--------|
| `dropbox_poll_lambda.py` | NEW — Dropbox polling Lambda |
| `deploy_dropbox_poll.sh` | NEW — Full deploy (IAM, Lambda, EventBridge, alarm) |
| `setup_dropbox_auth.py` | MODIFIED — Added explicit scope parameter |
| `macrofactor_lambda.py` | MODIFIED — v1.1.0, workout CSV support |
| `health_auto_export_lambda.py` | MODIFIED — v1.3.0, water intake |
| `deploy_water_intake.sh` | NEW — Deploy for water intake |
| `test_dropbox*.py` | NEW — Debug scripts (4 files, can be deleted) |

## Platform State After Session

| Metric | Value |
|--------|-------|
| Version | v2.18.0 |
| MCP tools | 57 |
| Data sources | 16 |
| Lambdas | 16 |
| SOT domains | 16 |
| Monthly cost | Under $25 |
