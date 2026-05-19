# Life Platform — Project Plan Archive

> Completed work moved here to reduce session startup token cost.
> For active work, see PROJECT_PLAN.md.

---

## Completed Infrastructure
- DynamoDB table `life-platform` provisioned (us-west-2, account 205930651321) — deletion protection + PITR enabled
- MCP server Lambda `life-platform-mcp` deployed with API Gateway + secret key auth
- MCP bridge (`mcp_bridge.py`) configured for local Claude Desktop integration
- CloudWatch alarms for all ingestion Lambdas + composite DLQ alarm
- CloudWatch alarms for all email/digest Lambdas (v2.5.2)
- CloudWatch log retention 30 days on all 12 Lambda log groups (v2.5.2)
- CloudTrail audit logging — `life-platform-trail`, management events, us-west-2 (v2.5.2)
- AWS Budget alert ($5 / $10 / $20 thresholds)
- S3 lifecycle policy: raw/ → STANDARD_IA at 90 days, GLACIER at 1 year

## Completed Security
- All IAM roles least-privilege; ingestion roles scoped to specific Secrets Manager ARNs
- MCP role: GetItem + Query + PutItem only (Scan removed)
- SES scoped to specific verified identity ARN
- S3: all public access blocked, AES-256 encryption at rest

## Completed Data Sources
- **Whoop** — daily recovery, HRV, strain, sleep; Lambda + scheduler
- **Withings** — daily weight/body composition; Lambda + scheduler
- **Strava** — activities with full nested detail; backfill + live Lambda; enriched_name backfill complete (2,636 activities)
- **Todoist** — daily task completion; Lambda + scheduler
- **Apple Health** — steps, active calories, resting HR, HRV, sleep; backfill + Lambda
- **Hevy** — full exercise/set/rep history; backfill complete; 6 strength MCP tools
- **Eight Sleep** — sleep staging, HRV, efficiency, circadian metrics; 868 nights backfilled; Lambda + scheduler
- **MacroFactor** — S3-triggered Lambda; 6 nutrition MCP tools; real data live from 2026-02-22
- **Chronicling** — ARCHIVED (last record 2025-11-09; replaced by Habitify v2.7.0)
- **Habitify** — 65 habits across 9 P40 groups + mood (1-5); Lambda + scheduler (6:15 AM PT); $4.99/mo
- **Garmin** — 40+ fields; backfill complete (2022-04-25 → 2026-01-18, 1,356 records); Lambda + scheduler (9:30am PT)
- **Labs** — 7 blood draws (2019-2025), 2 Function Health + 5 GP; 8 MCP tools (v2.11.0)
- **DEXA** — 1 scan seeded (2025-05-10); semi-annual manual entry
- **Genome** — 110 SNPs, 14 categories; 8 MCP tools with cross-referencing (v2.11.0)

## MCP Server Version History

| Version | Key changes |
|---------|-------------|
| 1.0.0 | Initial release — core 5 tools |
| 1.2.0 | Added `search_activities` tool |
| 1.3.0 | Added `get_field_stats`; improved `find_days` + `search_activities` descriptions |
| 1.3.1 | `get_field_stats` top-5 highs/lows + trend; `search_activities` percentile rank + context flags |
| 2.0.0 | 6 strength tools |
| 2.1.0 | 8 habit/P40 tools |
| 2.2.0 | 3 core nutrition tools |
| 2.3.0 | 3 longevity nutrition tools |
| 2.3.1–2.3.3 | Bug fixes, source-of-truth architecture, ingestion schedule alignment |
| 2.4.0 | `get_readiness_score` (unified 0-100) |
| 2.5.0–2.5.2 | 3 insights tools, TTL fix, infrastructure hardening |
| 2.6.0 | Garmin integration (2 tools, readiness rebalanced to 5 components) |
| 2.7.0 | Habitify integration (SOT switch, Supplements group) |
| 2.8.0 | `get_caffeine_sleep_correlation` + unified OneDrive pipeline |
| 2.10.0 | GP physicals, DEXA, genome seeded; 14 data sources |
| 2.11.0 | 8 labs/DEXA/genome MCP tools (47→55) |
| 2.12.0 | `get_exercise_sleep_correlation` (55→56) |
| 2.13.0 | `get_zone2_breakdown` (56→57) |
| 2.14.0 | `get_alcohol_sleep_correlation` — first 3-source correlation (57→58) |

## Completed Backlog Items
- A. CloudTrail logging — DONE v2.5.2
- C. CloudWatch alarms for email Lambdas — DONE v2.5.2
- D. CloudWatch Logs retention policy — DONE v2.5.2
- F. Haiku API retry logic — DONE v2.5.2
- 1. Align ingestion schedules — DONE v2.3.3
- 2. Caffeine timing vs sleep quality tool — DONE v2.8.0
- 3. Exercise timing vs sleep quality tool — DONE v2.12.0
- 4. Zone 2 training identifier — DONE v2.13.0
- 5. Unified readiness score tool — DONE v2.4.0
- 7. Alcohol impact tool — DONE v2.14.0
- 8. Exist.io — SUPERSEDED by Habitify v2.7.0
- Labs Phase 2 (MCP tools) — DONE v2.11.0
- 16. Proactive daily morning brief — DONE v3.2.0
- Monthly Coach's Letter — DONE v3.2.0
- 19. Anomaly detection + root cause engine — DONE v3.3.0
- 21. Insight memory / coaching log (Phases 1+2a) — DONE v3.4.0/v3.5.0

## Completed Future Data Sources
- ~~Exist.io~~ — SUPERSEDED by Habitify v2.7.0
- ~~Function Health~~ — DONE v2.9.0/v2.10.0 (2 FH + 5 GP draws; 8 MCP tools v2.11.0)
- ~~DEXA scan~~ — DONE v2.10.0
- ~~Genome SNP report~~ — DONE v2.10.0 (110 SNPs, privacy-safe)
- ~~Garmin~~ — DONE v2.6.0 (backfill complete)
