# HANDOVER — v8.0.0

**Date:** 2026-05-19
**Prior:** All v6.x and v7.x handovers archived to `handovers/archive/`. Last committed git version stamp was v6.9.5; v7.0.0–v7.21.0 was the v1 audit (uncommitted at the time of v2 audit); v8.x is V2 audit + follow-ups.

---

## Quick orientation

**What this is:** Personal health platform. AWS-native (us-west-2). Single user (matthew). ~73 Lambdas, 1 DynamoDB table, public site at `averagejoematt.com`, MCP server for Claude Desktop / claude.ai integration.

**Where to start as a new operator:**
1. `docs/QUICKSTART.md` — 30-min action sequence (auth → test → deploy → verify)
2. `docs/ONBOARDING.md` — mental model
3. `docs/RUNBOOK.md` — daily ops
4. `docs/BACKLOG.md` — what's open

**Tonight if you do nothing:** the platform continues running. Daily-brief sends at 10 AM PT, chronicles resume Wed 8 AM PT, MCP serves Claude Desktop tools, site-api serves averagejoematt.com. Garmin is finally back online (was 44 days dark).

---

## Last 48 hours summary

**V2 audit + follow-up shipped (~50 commits, ~$3.65/mo cost recovery):**

### Critical fixes
- coach-computation-engine restored after 7-day datetime tzinfo crash
- HAE webhook integration timeout 30s → 29s (was silently truncating bulk Apple Health uploads)
- daily-brief SES IAM regression fixed (2-day delivery gap; ses:SendEmail needed on configuration-set ARN as well as identity)
- freshness_checker NameError on sick-day branch fixed (would have failed CI)
- 5 coach Lambdas: `_emit_token_metrics` 2-arg bug → 4-arg with cache fields; CloudWatch IAM grants added
- coach-history-summarizer timeout 120s → 300s + IAM grant + JSON-fence parse defensive (`text.find` not `text.index`)
- Garmin OAuth refreshed via Playwright browser-auth setup script; 15 days backfilled to DDB + S3
- coach prediction loop `_normalize_metric_hint` whitelist enforced (verified-already-shipped, source code)

### Production state changes
- **Layer normalized:** 55–57 Lambdas now on shared-utils v51 (was 1 v50, 6 v49, 46 v43, 3 v25, 1 v2)
- **CDK constant fixed:** `SHARED_LAYER_VERSION = 51` (was 43; would have regressed everything on next `cdk deploy --all`)
- **New CI guard:** `test_lv6_cdk_constant_matches_latest_published_layer` — fails if constant drifts from AWS
- **SES open tracking** wired (configuration set `life-platform-emails` → CloudWatch event destination → 4 email Lambdas)
- **CloudTrail data events** enabled for `s3://matthew-life-platform/raw/*` and `uploads/*`
- **DLQ status:** 64 stuck Garmin messages will age out at 14d retention (no active fill)
- **coach-quality-gate** now WIRED (was 0 invocations; async-invoked from `ai_calls.call_coach_brief_v2`)
- **Chronicle workflow re-enabled** — first chronicle in 8 weeks tomorrow 8 AM PT
- **MCP wildcard imports** replaced with explicit imports via AST analysis (registry.py)
- **Site_api / site_api_ai:** 4 dark Anthropic call sites now emit token metrics dimensioned by Endpoint

### Cleanup shipped
- **Deleted:** `email_framework.py` (zero importers), `tools_calendar.py` (ADR-030 retired), `podcast_scanner_lambda.py` (Lambda doesn't exist)
- **Renamed:** `weather_handler.py` → `weather_lambda.py`
- **Archived:** ~145 tracked files (show_and_tell/, content/, demo/, qa-screenshots/, HANDOVER_LATEST copy.md, LEDGER specs, INTELLIGENCE_LAYER specs)
- **autopep8:** 2,055 style findings → 0 across lambdas/ and mcp/
- **5 orphan IAM roles deleted** (life-platform-digest-role, og-image-role, measurements-ingestion-role, pipeline-health-check-role, subscriber-onboarding-role)
- **2 orphan secrets deleted** (notion, dropbox — both Lambdas use consolidated `life-platform/ingestion-keys`)
- **S3 KMS CMK** scheduled for deletion 2026-06-16 (bucket on AES256 per ADR-053)
- **CloudFront favicon/apple-touch-icon 404s fixed**

### Cost
- **April baseline:** $35/mo
- **May MTD (as of 5/19):** $18.58
- **V2 recovery:** $3.65/mo recurring
- **Forecast:** ~$30/mo steady state (within $20 stretch budget after Anthropic API spend stable)

---

## What's running where

### Active Lambdas (73 prod + 4 us-east-1)
See `docs/ARCHITECTURE.md` § Lambda inventory. All on layer v51 except 3 v25 (deferred: site-api currently on v51, site-stats-refresh on v51, og-image-generator on v51 — all bumped today). Garmin Lambda uses its own `garth-layer:2`.

### Scheduled timing (UTC)
| Time | What |
|---|---|
| 14:00, 02:00 | Weather ingestion (cron) |
| 14:30 | Activity enrichment |
| 15:00 + 15:10 (Wed) | Wednesday Chronicle + email send |
| 15:30 | Anomaly detector |
| 16:00 (Sun) | Weekly digest |
| 16:30 | Character sheet compute (ADR-052) |
| 16:35 | Adaptive mode compute |
| 16:40 | Daily metrics compute |
| 16:45 | Daily insight compute |
| 17:00 | Daily brief send (10 AM PT) |
| 17:30 | Whoop recovery |
| 18:00 (Sun) | Weekly correlation compute |
| 19:00 (Sun) | Hypothesis engine |
| 19:30 | OG image generator |
| Every 4h | Canary, MCP-warmer |
| Every 15min | MCP canary |
| Every 30min | Dropbox poll |
| 22:00 (Sun) | Challenge generator |
| 07:30 (Mon) | Data reconciliation |

---

## What you (Matthew) need to do

### 🔴 Urgent / today-ish
- [ ] **Watch for AWS Support response** on case 177921309700709 (concurrency quota raise 10→100). Free, ~24h turnaround. When approved, ping the agent — there's a one-line CDK uncomment + deploy.

### ⏰ Monitor this week
- [ ] Wednesday 8 AM PT (tomorrow 2026-05-20): verify chronicle email lands
- [ ] Daily brief tomorrow morning: verify SES open tracking starts recording (Apple Mail Privacy may mask; check `LifePlatform/AI Open` metric)
- [ ] Coach prediction loop: 7-day window starts now — first verdicts should be confirmed/refuted by next Sunday
- [ ] Cache hit-rate metrics: 7+ days of `AnthropicCacheReadTokens` data should accumulate

### 📅 Scheduled re-evaluations
- **2026-05-26:** Cache savings + per-Lambda AI spend + SES open rate (7-day data)
- **2026-06-17:** Coach prediction validation (30 days post-loop closure)
- **2026-06-19:** Coach quality_gate threshold promotion decision
- **2026-07-17:** MCP tool bulk delete (60-day grace expires)
- **2026-08-19:** v3 audit (per `docs/V2_AUDIT_PROMPT.md` cadence)

---

## What can wait

See `docs/BACKLOG.md` for the full enumerated open list (35 items across 5 categories).

**Top 3 long-tail items if you want to chip away:**
1. **Site_api partial extraction** of `board_ask` + `/api/ask` handlers (~1-2h, smaller monolith)
2. **`anomaly_detector_lambda.py` 4 multi-line prints** (15 min, completes logger discipline)
3. **DEPENDENCY_GRAPH.md "Hottest Partitions"** refresh (20 min, accuracy)

---

## Where docs live

```
docs/
├── ONBOARDING.md          ← start here as new operator
├── QUICKSTART.md          ← first commands
├── ARCHITECTURE.md        ← system design
├── SCHEMA.md              ← DDB fields
├── INFRASTRUCTURE.md      ← AWS resources
├── DEPENDENCY_GRAPH.md    ← Lambda-to-Lambda
├── MCP_TOOL_CATALOG.md    ← MCP tools
├── RUNBOOK.md             ← daily ops
├── OPERATOR_GUIDE.md      ← Day 1 ops walkthrough
├── DEPLOYMENT.md          ← how to deploy + rollback (new)
├── DISASTER_RECOVERY.md   ← DR playbook (new)
├── SECURITY.md            ← threat model + defenses (new)
├── API.md                 ← public API reference (new)
├── TESTING.md             ← test strategy (new)
├── INCIDENT_LOG.md        ← past incidents
├── SLOs.md                ← service level objectives
├── COST_TRACKER.md        ← cost tracking
├── SECRETS_MAP.md         ← secret inventory
├── SECRETS_ROTATION.md    ← rotation procedures
├── RESERVED_CONCURRENCY.md ← Lambda concurrency plan
├── RUNBOOK_REENTRY.md     ← protocol for >7-day gaps
├── DECISIONS.md           ← ADRs (001-057)
├── DATA_GOVERNANCE.md     ← PII + retention
├── BOARDS.md              ← AI persona panels
├── REVIEW_METHODOLOGY.md  ← how to audit
├── CHANGELOG.md           ← what shipped when
├── BACKLOG.md             ← open work (new — synthesized)
├── V2_AUDIT_PLAN.md       ← V2 audit findings
├── V2_AUDIT_PROMPT.md     ← v3 audit planning prompt
└── archive/               ← historical specs (not active)

handovers/
├── HANDOVER_LATEST.md     ← this file
└── archive/               ← all prior handovers
```

---

## Where things you might worry about live

| Concern | Doc / location |
|---|---|
| "Is anything on fire?" | `aws cloudwatch describe-alarms --state-value ALARM` |
| "How much am I spending?" | `docs/COST_TRACKER.md` + AWS Cost Explorer |
| "When did X happen?" | `docs/CHANGELOG.md` + `docs/INCIDENT_LOG.md` |
| "Why did we decide X?" | `docs/DECISIONS.md` (ADRs) |
| "What's open?" | `docs/BACKLOG.md` |
| "How do I deploy?" | `docs/DEPLOYMENT.md` |
| "Disaster scenario X" | `docs/DISASTER_RECOVERY.md` |

---

## Repo state at handover

- **Branch:** `main`
- **Last commit:** see `git log -1 --oneline`
- **Pushed:** yes (all work in this session pushed to GitHub)
- **Untracked:** `archive/051726_downloadsfolder_backup/` (your personal backup, intentionally not tracked)
- **Tests:** 1,217 passing, 0 failing (unit), 1-3 failing (integration — Garmin alarms still in ALARM state, will self-clear)

---

## Contact / context

- **AWS account:** 205930651321 (us-west-2 primary)
- **AWS Support case open:** 177921309700709 (concurrency quota raise)
- **Anthropic billing:** ~$8-12/mo (managed by Matthew)
- **Domain registrar:** averagejoematt.com via Route53
- **SES domain:** mattsusername.com (sender verified)

---

**Verified:** 2026-05-19 (v8.0.0)
