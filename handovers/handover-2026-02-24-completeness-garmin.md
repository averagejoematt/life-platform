# Life Platform — Session Handover: Completeness Alerting + Garmin Fix
**Date:** 2026-02-24  
**Version:** v2.14.1  
**Session focus:** Operational reliability — data gap detection + Garmin ingestion fix  
**Status:** Completeness alerting live; Garmin Lambda fixed; backfill in progress

---

## Session Summary

Two operational reliability improvements:

1. **Data Completeness Alerting v2** — upgraded `life-platform-freshness-checker` from basic 8-source stale/fresh check to a 10-source monitoring system with per-source thresholds, HTML email alerts via SES, impact mapping (which tools are degraded per gap), and SNS escalation for infrastructure-level failures.

2. **Garmin Lambda Fix** — diagnosed and fixed three issues that had silently broken Garmin ingestion since Jan 18: pydantic_core binary mismatch (Mac ARM vs Lambda x86_64), display_name=None causing 403 errors, and expired OAuth tokens. The completeness alerting immediately caught this on its first run.

---

## Data Completeness Alerting v2

### Source Configuration
| Source | Threshold | Severity Model |
|--------|-----------|----------------|
| Whoop, Withings, Todoist, Apple Health*, Eight Sleep, Habitify | 48h (daily) | WARNING → CRITICAL at 2× |
| Strava, Garmin, MacroFactor | 72h (activity) | WARNING → CRITICAL at 2× |
| *Apple Health override | 504h (21d) WARNING | 720h (30d) CRITICAL |

### Excluded Sources
- **Hevy** — deprecated, historical backfill only (use MacroFactor workouts)
- **Labs, Genome, DEXA** — periodic/manual, would always appear stale

### Alert Routing
- **SES HTML email** → fires when any source is stale (dashboard with impact assessment)
- **SNS push** → only when 3+ sources stale simultaneously (infrastructure concern)

### IAM
- Added `ses:SendEmail` to `lambda-freshness-checker-role` inline policy (scoped to mattsusername.com identity)

---

## Garmin Lambda Fix (v1.3.0)

### Root Cause
Three compounding issues:
1. `pip3 install garminconnect garth` on Mac installs ARM `.so` files → `ModuleNotFoundError: pydantic_core._pydantic_core` on Lambda (x86_64)
2. Our auth flow called `api.login()` which internally tries `garth.refresh_oauth2()` → fails with `AssertionError: OAuth1 token is required for OAuth2 refresh`
3. Without successful login, `api.display_name` stays None → URL paths like `/usersummary/daily/None` → 403 Forbidden

### Fix
- **Lambda packaging:** `pip install --platform manylinux2014_x86_64 --only-binary=:all:` in fix_garmin.sh
- **Auth flow:** removed `api.login()` entirely; load garth tokens, wire into Garmin object, resolve display_name directly via `/userprofile-service/socialProfile` API
- **Error messages:** clear instructions to re-run setup_garmin_auth.py if tokens expire
- Same fix applied to `backfill_garmin.py`

### Remaining Warnings (non-blocking)
- `training_readiness` — API now returns list instead of dict; needs minor extraction fix
- `get_training_load` — method removed in newer garminconnect library; needs replacement

---

## Files Created/Modified

| File | Action |
|------|--------|
| `deploy_completeness_alerting.sh` | Created — full deploy script for freshness checker v2 |
| `fix_garmin.sh` | Created — venv setup + re-auth + repackage + redeploy |
| `garmin_lambda.py` | Modified — v1.2.0 → v1.3.0 auth flow fix |
| `backfill_garmin.py` | Modified — matching auth flow fix |
| `CHANGELOG.md` | Updated — v2.14.1 entry |
| `handovers/handover-2026-02-24-completeness-garmin.md` | This file |

---

## Current Platform State

- **MCP Server:** v2.14.0, **58 tools**
- **Freshness Checker:** v2, 10 sources monitored, SES + SNS alerting
- **Garmin Lambda:** v1.3.0, fixed auth, daily schedule 9:30am PT
- **Garmin Backfill:** Jan 19 – Feb 23 in progress (~36 days)
- **Data Sources:** 14 (11 automated + 3 manual)
- **Cost:** Tracking under $25/month

---

## Backlog Status

### Completed This Session
- **#16 Data completeness alerting** — DONE v2.14.1
- **Garmin ingestion fix** — DONE v1.3.0

### Recommended Next
1. **DynamoDB TTL smoke test** (Item B) — single CLI command, 2 min
2. **Weekly Digest v2** (Item #6) — Zone 2, macro adherence, CTL/ATL/TSB, deltas
3. **Notion Journal integration** (Item #9) — closes the "why" gap
4. **Garmin minor fixes** — training_readiness list handling, get_training_load removal

---

## Verification After Backfill

Once backfill completes, re-run the freshness checker to confirm Garmin drops off alerts:
```
aws lambda invoke \
    --function-name life-platform-freshness-checker \
    --region us-west-2 /tmp/fresh.json && cat /tmp/fresh.json
```

Expected: Garmin shows ✅ FRESH, only Apple Health remains as a known gap (within 21d threshold).
