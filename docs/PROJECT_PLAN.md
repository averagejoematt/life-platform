# Life Platform — Project Plan

> Living document. For completed work and version history, see CHANGELOG.md / CHANGELOG_ARCHIVE.md.
> Last update: 2026-03-14 (v3.7.20 — all actionable R8 items resolved, SIMP-1 Phase 1 complete)

---

## Active Priorities

### P0 — Completed (v3.7.15)
All P0 items from Architecture Review #8 are resolved:
- ✅ Webhook auth restored (CDK deploy LifePlatformIngestion)
- ✅ Secret state reconciled to 10 actual secrets
- ✅ IAM/secrets CI lint wired (`test_iam_secrets_consistency.py`)
- ✅ ARCHITECTURE.md secrets table updated to match reality
- ✅ CV_THRESHOLDS stale comments fixed
- ✅ SCHEMA.md added to `sync_doc_metadata.py`

---

## Backlog — Prioritized

Items are grouped by priority tier. Within each tier, items are ordered by ROI (impact ÷ effort).

### Tier 1 — Do Next (30 days)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R8-QS1 | **SIMP-1: MCP tool consolidation** — Phase 1 complete (116→86 tools via 13 dispatchers). Phase 2 (EMF-driven cuts to ≤80) gated on 30-day data. | R8 Finding-5, R8 Top-10 #5 | L | HIGH | ⏳ Phase 1 done (v3.7.17–19). Phase 2 ≤80 gated ~2026-04-13 |
| R8-QS2 | **Add integration test to qa-smoke Lambda** — write test record to `SOURCE#test`, invoke 2-3 MCP tools + validate response schema, verify cache ≥10 items, verify freshness of ≥1 source. | R8 Finding-4, R8 Top-10 #3 | M (2-3h) | HIGH — catches 80% of deployment-induced failures | ✅ Done (v3.7.16) |
| R8-QS3 | **Update COST_TRACKER model routing entry** — decision log says "Haiku ~$0.10/mo" but `ai_calls.py` uses Sonnet for coaching calls (~$3/mo actual). Entry is stale, not a cost problem. | R8 §8 stale docs | S (10min) | LOW — documentation hygiene | ✅ Done (v3.7.17) |
| R8-QS4 | **Archive completed deploy scripts** — reduce 120+ scripts in `deploy/` to active-only. Run `bash deploy/archive_onetime_scripts.sh`. | R8 Finding-3, R8-6 (pending from v3.7.14) | S (15min) | LOW — DevEx / cognitive load | ✅ Done (v3.7.16) |
| TB7-1 | **GitHub `production` Environment gate** — verify exists in repo settings for CI/CD manual approval. | TB7 (pre-R8) | S (5min) | LOW — CI/CD hygiene | ✅ Done |
| TB7-2 | **Update `BRITTANY_EMAIL` env var** to real address for accountability email. | TB7 (pre-R8) | S (5min) | LOW — feature enablement | ✅ Done |

### Tier 2 — Near-Term (60 days)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R8-ST1 | **Google Calendar integration** — highest-priority unbuilt data source. OAuth token rotation pattern, ~6-8h. | Pre-R8, TB7-18 | L (6-8h) | MEDIUM — new data source for scheduling/planning intelligence | Not started |
| R8-ST2 | **Document and test DynamoDB restore procedure** — write runbook section, execute PITR restore to test table, verify data integrity across partitions. | R8 Finding-6, R8 Top-10 #6 | S (1h) | MEDIUM — critical insurance for core data asset | ✅ Done (v3.7.17) — runbook written. Drill (actual restore) still recommended. |
| R8-ST3 | **Create "maintenance mode" Lambda profile** — config to disable non-essential Lambdas during vacation/absence. | R8 §6 R-5, R8 Top-10 #9 | S (30min) | MEDIUM — operational resilience during absence | ✅ Done (v3.7.17) — `deploy/maintenance_mode.sh enable\|disable\|status` |
| R8-ST4 | **Add OAuth token health monitoring** — alert if any OAuth refresh token hasn't been updated in >60 days. | R8 §6 R-2, R8 Top-10 | M (2h) | MEDIUM — prevents multi-source auth cascade failure | ✅ Done (v3.7.17) — freshness_checker extended, OAuthSecretDescribe IAM added |
| R8-ST5 | **Pre-compute composite scores** — `SOURCE#composite_scores` DynamoDB partition written nightly. | Pre-R8, SIMP-1 prereq | M (3-4h) | HIGH | ✅ Done (v3.7.20) — `write_composite_scores()` in daily-metrics-compute |
| R8-ST6 | **CDK diff IAM change → blocking gate** — make CI pipeline block (not just warn) when CDK diff detects IAM/policy changes. | R8 §10 CD-4 | S (30min) | MEDIUM — prevents future IAM drift | ✅ Done (v3.7.17) — ci-cd.yml warning → error + exit 1 |
| R8-ST7 | **Tighten HAE webhook S3 write scope** — tightened from `raw/matthew/*` to 5 explicit paths. | R8 §5 IAM | S (15min) | LOW — least-privilege refinement | ✅ Done (v3.7.17) — role_policies.py updated, CDK deploy pending |

### Tier 3 — Strategic (90 days)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R8-LT1 | **Architecture Review #9** — post-SIMP-1 validation. Targeting ~2026-04-13 (after 30 days of EMF data). | R8 §17 | L (1 session) | HIGH — validates consolidation | Gated on SIMP-1 |
| R8-LT2 | **Evaluate IC-4/IC-5 readiness** — failure pattern recognition + momentum/early warning. Data maturity gate ~6-8 weeks behavioral data. | INTELLIGENCE_LAYER.md | S (assessment) | MEDIUM — next IC features | Gated on data (~May 2026) |
| R8-LT3 | **Unit tests for business logic** — pytest unit tests for scoring_engine, character_engine, day grade computation. | R8 §9 testability | M-L | MEDIUM | ✅ Done (v3.7.20) — 74/74 tests in `tests/test_business_logic.py` |
| R8-LT4 | **DynamoDB export to S3 for analytics isolation** — separate analytical workload from transactional. Export to Parquet via DDB export, query with Athena. | R8 §17 roadmap | L | LOW — premature until data volume warrants | Not started |
| R8-LT5 | **Review SLO targets** — evaluate whether 99%/99.5% targets are appropriate based on 90 days of operational data. | R8 §17 roadmap | S (assessment) | LOW — operational maturity | Gated on 90 days data |
| R8-LT6 | **Lambda@Edge auth — verify CDK management** | R8 Finding-6, R8 §4 S | S (15min) | LOW | ✅ Done (v3.7.19) — confirmed manually managed outside CDK, documented in ARCHITECTURE.md |
| R8-LT7 | **Add disclaimer to `get_hypotheses` MCP tool** — unconfirmed hypotheses require 3 observations before promotion. | R8 §12 AI-2 | S (5min) | LOW — analytical transparency | ✅ Done (v3.7.17) — registry description updated |
| Risk-7 | **Compute pipeline timing: staleness observability** — Daily Brief now emits `ComputePipelineStaleness` CloudWatch metric when `computed_metrics` is missing or >4h stale. Alarm `life-platform-compute-pipeline-stale` to be created via `deploy/create_compute_staleness_alarm.sh`. | R8 Top-10 Risk 7 | S (30min) | MEDIUM — makes silent timing failure visible | ✅ Code done (v3.7.17). Run alarm script to complete. |
| R8-LT8 | **DLQ consumer: event-driven vs scheduled** | R8 §6 R-3 | S (30min) | LOW | ✅ Done (v3.7.19) — ADR-024 written, retain schedule model |
| R8-LT9 | **Pre-compute weekly correlation matrix** — `SOURCE#weekly_correlations` partition. | Pre-R8 | M (3h) | LOW | ✅ Done (v3.7.20) — `weekly-correlation-compute` Lambda, 20 pairs, Sunday 11:30 AM PT |

### Tier 4 — Deferred / Data-Gated

| ID | Item | Source | Target Date | Gate |
|----|------|--------|-------------|------|
| IC-4 | Failure pattern recognition | IC roadmap | ~May 2026 | 6-8 weeks behavioral data |
| IC-5 | Momentum / early warning | IC roadmap | ~May 2026 | 6-8 weeks behavioral data |
| IC-9 | Episodic memory ("what worked") | IC roadmap | ~June 2026 | Month 3 data |
| IC-10 | Personal response curves | IC roadmap | ~July 2026 | Month 4 data |
| IC-11 | Coaching calibration | IC roadmap | ~June 2026 | Month 3 data |
| IC-20 | Titan Embeddings (Bedrock) | IC roadmap | ~July 2026 | Month 3-4 insight corpus |
| IC-26 | Temporal pattern mining | IC roadmap | ~May 2026 | 8+ weeks data |
| IC-28 | Permanent learnings distillation | IC roadmap | ~June 2026 | Quarterly |
| COST-2 | CloudWatch EMF analysis → SIMP-1 | Pre-R8 | ~2026-04-13 | 30 days EMF data |

---

## Completed Items (Recent)

| ID | Item | Version | Date |
|----|------|---------|------|
| R8-P0a | Webhook auth restored (CDK IAM fix) | v3.7.15 | 2026-03-13 |
| R8-P0b | Secret state reconciled (10 actual secrets documented) | v3.7.15 | 2026-03-13 |
| R8-P0c | IAM/secrets CI lint (`test_iam_secrets_consistency.py` S1-S4) | v3.7.15 | 2026-03-13 |
| R8-P0d | ARCHITECTURE.md secrets table updated | v3.7.15 | 2026-03-13 |
| R8-P0e | CV_THRESHOLDS stale comments fixed | v3.7.15 | 2026-03-13 |
| R8-P0f | SCHEMA.md added to sync_doc_metadata.py | v3.7.15 | 2026-03-13 |
| R8-P0g | Architecture Review #8 conducted (A-) | v3.7.15 | 2026-03-13 |
| TB7-* | All TB7 items closed | v3.7.8 | 2026-03-13 |
| PROD-1 | CDK migration (8 stacks) | v3.4.0 | 2026-03-10 |
| SEC-1 | Per-function IAM roles (43 dedicated) | v3.4.0 | 2026-03-10 |
| COST-A | CloudWatch alarm consolidation (87→47) | v3.4.0 | 2026-03-10 |

---

## Architecture Review History

| # | Date | Version | Grade | Key Findings |
|---|------|---------|-------|-------------|
| R8 | 2026-03-13 | v3.7.15 | A- | COST-B secret drift, webhook auth broken, complexity limits. Full report: `docs/reviews/architecture_review_8_full.md` |
| R7 | 2026-03-11 | v3.5.x | — | TB7 hardening sprint (25 items) |
| R6 | 2026-03-10 | v3.4.x | — | CDK migration review |
| R1-R5 | 2026-02-28–03-09 | various | — | See `docs/reviews/` |

---

## Key Metrics

| Metric | Current | Target | Notes |
|--------|---------|--------|-------|
| MCP tools | 86 | ≤80 (SIMP-1 Phase 2) | Phase 1 complete. Phase 2 gated ~Apr 13 |
| Lambdas | 43 | — | +weekly-correlation-compute (v3.7.20) |
| CloudWatch alarms | 47 | — | Post-COST-A |
| Monthly cost | ~$10 | <$25 | Well under budget |
| Active secrets | 10 | — | Reconciled v3.7.15 |
| CI linters | 9 | — | Added IAM/secrets lint v3.7.15 |
| SLOs defined | 4 | 4 | SLO-1 through SLO-4 |
| IC features live | 14 of 30 | — | Next: IC-4/IC-5 (~May 2026) |
| Data sources | 19 | 20 (Google Cal) | Next integration |
| Architecture review grade | A- | A | Gap: SIMP-1 + integration tests |
