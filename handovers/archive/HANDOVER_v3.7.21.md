# Life Platform Handover — v3.7.21
**Date:** 2026-03-14
**Session type:** Google Calendar integration (R8-ST1)

---

## What Was Done

### Google Calendar Integration (R8-ST1) ✅

The last unblocked R8 item. All actionable R8 findings are now resolved.

**Architecture:** Same OAuth2 refresh_token pattern as Strava/Whoop. `client_id`, `client_secret`, `refresh_token` stored in Secrets Manager `life-platform/google-calendar`. Lambda auto-refreshes token on every invocation and writes back if updated.

**Files created:**
- `lambdas/google_calendar_lambda.py` — ingestion Lambda (v1.0.0)
- `mcp/tools_calendar.py` — 2 MCP tools
- `setup/setup_google_calendar_auth.py` — one-time OAuth setup script

**CDK:**
- `cdk/stacks/role_policies.py` — `ingestion_google_calendar()` added
- `cdk/stacks/ingestion_stack.py` — Lambda #16 wired at `cron(30 13 * * ? *)` (6:30 AM PT)

**MCP tools added (88 total):**
- `get_calendar_events(view: day|range|lookahead)` — events for a date, date range, or 14-day forward
- `get_schedule_load(days=, history_days=)` — meeting load analysis, DOW patterns, week assessment

**Data model:**
- `SOURCE#google_calendar | DATE#<date>` — per-day record: events[], event_count, meeting_minutes, focus_block_count, earliest/latest event
- `SOURCE#google_calendar | DATE#lookahead` — 14-day forward summary (overwritten daily)

**⚠️ ACTIVATION REQUIRED — calendar will not ingest until OAuth is set up:**
```bash
pip install google-auth-oauthlib google-api-python-client
python3 setup/setup_google_calendar_auth.py
```
Steps:
1. Create Google Cloud project at console.cloud.google.com
2. Enable Google Calendar API
3. Create OAuth 2.0 credentials (Desktop application type)
4. Download client_secret.json to ~/Downloads/
5. Run setup script — opens browser for authorization
6. Credentials stored to Secrets Manager `life-platform/google-calendar`
7. Lambda will run at 6:30 AM PT next day

---

## Platform Status
- Version: v3.7.21
- MCP tools: 88 (86 + get_calendar_events + get_schedule_load)
- Lambdas: 44 (43 + google-calendar-ingestion)
- Data sources: 19 active (Google Calendar = 20th, pending OAuth setup)
- All alarms: OK
- CI: 7/7, business logic: 74/74
- Smoke: 10/10
- DLQ: 0

---

## All R8 Items — Final Status

Every actionable R8 finding is now resolved. Only gated items remain.

| ID | Status |
|----|--------|
| R8-QS1 SIMP-1 Phase 1 | ✅ 116→86 tools |
| R8-QS2 Integration tests | ✅ |
| R8-QS3 COST_TRACKER | ✅ |
| R8-QS4 Archive scripts | ✅ |
| R8-ST1 Google Calendar | ✅ v3.7.21 |
| R8-ST2 DDB restore runbook | ✅ |
| R8-ST3 Maintenance mode | ✅ |
| R8-ST4 OAuth monitoring | ✅ |
| R8-ST5 Composite scores | ✅ v3.7.20 |
| R8-ST6 CDK IAM gate | ✅ |
| R8-ST7 HAE S3 scope | ✅ |
| R8-LT3 Unit tests | ✅ 74/74 |
| R8-LT6 Lambda@Edge verify | ✅ |
| R8-LT7 Hypothesis disclaimer | ✅ |
| R8-LT8 DLQ consumer model | ✅ ADR-024 |
| R8-LT9 Weekly correlations | ✅ v3.7.20 |

---

## Gated / Upcoming

| Item | Gate |
|------|------|
| SIMP-1 Phase 2 (≤80 tools) | ~2026-04-13 (30-day EMF data) |
| Architecture Review #9 | After Phase 2 |
| IC-4/IC-5 readiness eval | ~May 2026 (data maturity) |
| Google Calendar OAuth setup | Whenever Matthew sets up GCP project |

---

## Session Close Notes
- sync_doc_metadata.py PLATFORM_FACTS updated: v3.7.21, 44 Lambdas, 88 tools
- Run `python3 deploy/sync_doc_metadata.py --apply` before commit
