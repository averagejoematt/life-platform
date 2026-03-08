# Life Platform — Handover v2.99.0
**Date:** 2026-03-08
**Session:** P2 hardening complete + todoist DLQ incident fix

---

## Platform State
- **Version:** v2.99.0
- **Lambdas:** 37 (added: `life-platform-dlq-consumer`, `life-platform-canary`)
- **MCP Tools:** 144 | **Modules:** 30
- **Git:** pending commit

---

## This Session — P2 Complete ✅

All 6 P2 tasks shipped. Also fixed a live incident discovered via DLQ consumer.

| Task | What | Status |
|------|------|--------|
| OBS-2 | CloudWatch `life-platform-ops` dashboard — 23 widgets, 47 alarms, KPIs, error matrix, AI token section | ✅ |
| REL-2 | `life-platform-dlq-consumer` Lambda — every 6h, classifies/retries/archives/alerts | ✅ |
| COST-3 | 14 CloudWatch alarms on `LifePlatform/AI` token metrics, OBS-2 dashboard patched | ✅ |
| MAINT-1 | 18 `lambdas/requirements/*.txt` files, `pip-audit` clean | ✅ |
| REL-4 | `life-platform-canary` — DDB + S3 + MCP round-trip every 4h, 4 alarms | ✅ |
| REL-3 | `item_size_guard.py` + 300KB alarm, strava/macrofactor/hae bundled | ✅ |

### Incident: todoist DLQ failures (2026-03-06 → 2026-03-08)
- **Discovered by:** REL-2 DLQ consumer — drained 4 messages on first run
- **Root cause:** `SECRET_NAME` env var on `todoist-data-ingestion` pointed to a secret marked for deletion (remnant of P1 secrets consolidation)
- **Fix:** `deploy/fix_todoist_secret_name.sh` — removed stale override, Lambda now uses code default `life-platform/api-keys`
- **Sweep:** All other ingestion Lambdas checked — notion/dropbox (`ingestion-keys`), strava/whoop (OAuth secrets) all legitimate
- **Gap:** todoist records 2026-03-06, 2026-03-07 may be missing — gap-aware backfill will self-heal on next scheduled run

---

## New Infrastructure

### New Lambdas (2)
| Lambda | Schedule | Purpose |
|--------|----------|---------|
| `life-platform-dlq-consumer` | every 6h | Polls DLQ, classifies transient/permanent, retries, archives to `dead-letter-archive/`, SES alert |
| `life-platform-canary` | every 4h | Synthetic DDB + S3 + MCP round-trip, emits `LifePlatform/Canary` metrics |

### New CloudWatch Alarms (20+)
- `life-platform-dlq-depth-warning` — DLQ ≥ 1 message
- `ai-tokens-{fn}-daily` × 12 — per-Lambda daily output token budget
- `ai-tokens-platform-daily-total` — platform-wide 33K tokens/day ($15/mo equivalent)
- `ai-anthropic-api-failures` — 3+ Anthropic API failures/day
- `life-platform-canary-{ddb,s3,mcp,any}-failure` × 4
- `life-platform-ddb-item-size-warning` — item ≥ 300KB

### New CloudWatch Metrics Namespaces
- `LifePlatform/Canary` — CanaryDDBPass/Fail, CanaryS3Pass/Fail, CanaryMCPPass/Fail, latencies
- `LifePlatform/DynamoDB` — ItemSizeBytes per source (from item_size_guard.py)
- `LifePlatform/AI` — AnthropicInputTokens, AnthropicOutputTokens, AnthropicAPIFailure per Lambda (was already live from ai_calls.py; alarms now wired)

### New Files
- `lambdas/dlq_consumer_lambda.py` — DLQ consumer
- `lambdas/canary_lambda.py` — synthetic canary
- `lambdas/item_size_guard.py` — shared 300KB guard utility (safe_put_item)
- `lambdas/requirements/` — 18 requirements.txt files + README
- `deploy/create_obs2_dashboard.py`
- `deploy/deploy_rel2_dlq_consumer.sh`
- `deploy/deploy_cost3_token_alarm.py`
- `deploy/generate_maint1_requirements.py`
- `deploy/deploy_rel4_canary.sh`
- `deploy/deploy_rel3_item_size.sh`
- `deploy/fix_todoist_secret_name.sh`

---

## Architecture Review Grades (updated after P2)

| Dimension | After P1 | After P2 |
|-----------|----------|----------|
| Security | B- | B- |
| Reliability | B | B+ |
| Operability | C+ | B- |
| Cost | A | A |
| Data Quality | B+ | B+ |
| AI Rigor | B- | B- |
| Maintainability | C+ | B- |
| Production Readiness | C+ | B |

---

## Next: P3 Tasks

| Task | Priority | Effort | Description |
|------|----------|--------|-------------|
| OBS-1 | P3 | L (6-8hr) | Structured logging — shared JSON logging module across all Lambdas |
| DATA-2 | P3 | M (4-6hr) | Ingestion validation layer — required fields, type checks, range checks → DLQ on invalid |
| SEC-5 | P3 | S (1-2hr) | `pip-audit` monthly scheduled run (now trivial — only garmin.txt has real deps) |
| DATA-3 | P3 | M (3-4hr) | Weekly reconciliation job — check all sources have records for each day |
| AI-3 | P3 | M (4-6hr) | AI output validation — post-processing checks on coaching output |
| REL-3 follow-up | — | S | Wire `safe_put_item()` calls into strava/macrofactor source code (currently bundled but not called) |

After P3, **feature work** resumes. Board top-ranked unbuilt items:
- Light exposure tracking (#31, ~2hr)
- Grip strength tracking (#16, ~2hr)
- Google Calendar (#2, 6-8hr)
- Monarch Money (#1, 4-6hr)

---

## Key Deploy Notes
- `deploy_unified.sh` requires bash 4+ — use `bash deploy/deploy_unified.sh` or versioned scripts
- For garmin: `bash deploy/fix_garmin_deps.sh` (bypasses deploy_unified.sh entirely)
- New Lambdas (dlq-consumer, canary) deploy via their own scripts in `deploy/`
- todoist backfill: will self-heal via gap-aware lookback (LOOKBACK_DAYS=7) on next 7:45 AM PT run

