# Life Platform — Project Plan

> Living document. For completed work and version history, see CHANGELOG.md / CHANGELOG_ARCHIVE.md.
> Last update: 2026-03-14 (v3.7.29 — Architecture Review #13 conducted, 15 findings tracked)

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
| R13-F05 | **Remove OAuth fail-open default** — `_get_bearer_token()` returns `None` (accept-all) when API key is missing. Change to reject-all. | R13 Finding-05 | S (30min) | MEDIUM — closes false security boundary | ✅ Done (v3.7.35) |
| R13-F06 | **n-gate on-demand correlation tool** — `get_cross_source_correlation` has no minimum sample size. Add n≥14 minimum, warn at n<30, include p-value/CI in response. | R13 Finding-06, R13 Top-10 #2 | S (2h) | MEDIUM — prevents spurious correlations from being presented as insights | ✅ Done (v3.7.36) |
| R13-F09 | **Medical disclaimer in MCP health tool responses** — Add `_disclaimer` field to all health-assessment tools (risk_profile, cgm dashboard, BP dashboard, HR recovery). | R13 Finding-09, R13 Top-10 #6 | S (1h) | MEDIUM — liability protection for any sharing/productization | ✅ Done (v3.7.36) |
| R13-F04 | **CI test: secret name references vs live secrets** — grep all Lambda source for secret names, validate referenced secrets exist. Prevents Todoist-style 2-day outage. | R13 Finding-04, R13 Top-10 #4 | S (1h) | MEDIUM — prevents class of deployment bug permanently | ✅ Done (v3.7.35) |
| R13-F12 | **Rate limiting on MCP write tools** — `create_todoist_task`, `log_supplement`, `write_platform_memory`, `delete_platform_memory`, `delete_todoist_task` have no per-session rate limiting. | R13 Finding-12 | S (1h) | MEDIUM — security hardening for write path | ✅ Done (v3.7.35) |
| R13-F08-dur | **Duration alarms on Daily Brief + MCP Lambdas** — timeout-without-error is currently undetected. Add p95 duration alarms. | R13 §Observability, R13 Top-10 #8 | S (1h) | MEDIUM — catches silent degradation | ✅ Done (v3.7.36) |
| R8-QS1 | **SIMP-1: MCP tool consolidation** — Phase 1 complete (116→86 tools via 13 dispatchers). Phase 2 (EMF-driven cuts to ≤80) gated on 30-day data. | R8 Finding-5, R8 Top-10 #5 | L | HIGH | ⏳ Phase 1 done (v3.7.17–19). Phase 2 ≤80 gated ~2026-04-13 |
| R8-QS2 | **Add integration test to qa-smoke Lambda** — write test record to `SOURCE#test`, invoke 2-3 MCP tools + validate response schema, verify cache ≥10 items, verify freshness of ≥1 source. | R8 Finding-4, R8 Top-10 #3 | M (2-3h) | HIGH — catches 80% of deployment-induced failures | ✅ Done (v3.7.16) |
| R8-QS3 | **Update COST_TRACKER model routing entry** — decision log says "Haiku ~$0.10/mo" but `ai_calls.py` uses Sonnet for coaching calls (~$3/mo actual). Entry is stale, not a cost problem. | R8 §8 stale docs | S (10min) | LOW — documentation hygiene | ✅ Done (v3.7.17) |
| R8-QS4 | **Archive completed deploy scripts** — reduce 120+ scripts in `deploy/` to active-only. Run `bash deploy/archive_onetime_scripts.sh`. | R8 Finding-3, R8-6 (pending from v3.7.14) | S (15min) | LOW — DevEx / cognitive load | ✅ Done (v3.7.16) |
| TB7-1 | **GitHub `production` Environment gate** — verify exists in repo settings for CI/CD manual approval. | TB7 (pre-R8) | S (5min) | LOW — CI/CD hygiene | ✅ Done |
| TB7-2 | **Update `BRITTANY_EMAIL` env var** to real address for accountability email. | TB7 (pre-R8) | S (5min) | LOW — feature enablement | ✅ Done |

### Tier 2 — Near-Term (60 days)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R13-F01 | **GitHub Actions CI pipeline** — pytest + cdk synth + cdk diff on push to main. Manual approval gate before cdk deploy. #1 highest-ROI improvement from R13. | R13 Finding-01, R13 Top-10 #1 | M (4h) | HIGH — prevents 80% of deployment incidents (8 in incident log) | Not started |
| R13-F02 | **Integration tests for critical path** — 3-5 tests against live AWS: (1) invoke ingestion Lambda with test data → verify DDB write, (2) invoke MCP tool → verify response shape, (3) verify freshness checker. Run post-deploy. | R13 Finding-02, R13 Top-10 #10 | M (5h) | HIGH — catches IAM gaps, schema mismatches, stale modules | Not started |
| R13-F08 | **CI test for layer version consistency** — verify shared layer version in CDK matches latest published layer. Catches "forgot to rebuild layer" bug (caused P2 incident). | R13 Finding-08, R13 Top-10 #5 | S (1h) | MEDIUM — prevents silent stale-layer failures | Not started |
| R13-F15 | **Bonferroni correction in weekly correlation compute** — 20 simultaneous tests at p=0.05 yields ~1 false positive per run. Add FDR or Bonferroni. | R13 Finding-15 | S (2h) | MEDIUM — statistical rigor for hypothesis generation | Not started |
| R13-F10 | **Consolidate d2f() into shared layer** — duplicated in digest_utils.py, sick_day_checker.py, mcp/core.py, and likely ingestion Lambdas. Move to shared utils. | R13 Finding-10, R13 Top-10 #9 | S (30min) | LOW — code hygiene | Not started (pair with ADR-027 next layer rebuild) |
| R13-F07 | **Quarterly PITR restore drill** — runbook written (R8-ST2) but never tested. Execute actual PITR restore to test table, verify data integrity. | R13 Finding-07, R13 Top-10 #7 | S (1h) | MEDIUM — validates backup strategy | Not started (first drill due ~Apr 2026) |
| R8-ST1 | **Google Calendar integration** — Lambda + 2 MCP tools deployed v3.7.21. OAuth still requires one-time setup: `python3 setup/setup_google_calendar_auth.py`. Tracked as CLEANUP-3. | Pre-R8, TB7-18 | S (20min remaining) | MEDIUM — code live, data flow pending OAuth | ⏳ Deployed (v3.7.21), OAuth pending (CLEANUP-3) |
| R8-ST2 | **Document and test DynamoDB restore procedure** — write runbook section, execute PITR restore to test table, verify data integrity across partitions. | R8 Finding-6, R8 Top-10 #6 | S (1h) | MEDIUM — critical insurance for core data asset | ✅ Done (v3.7.17) — runbook written. Drill (actual restore) tracked as R13-F07. |
| R8-ST3 | **Create "maintenance mode" Lambda profile** — config to disable non-essential Lambdas during vacation/absence. | R8 §6 R-5, R8 Top-10 #9 | S (30min) | MEDIUM — operational resilience during absence | ✅ Done (v3.7.17) — `deploy/maintenance_mode.sh enable\|disable\|status` |
| R8-ST4 | **Add OAuth token health monitoring** — alert if any OAuth refresh token hasn't been updated in >60 days. | R8 §6 R-2, R8 Top-10 | M (2h) | MEDIUM — prevents multi-source auth cascade failure | ✅ Done (v3.7.17) — freshness_checker extended, OAuthSecretDescribe IAM added |
| R8-ST5 | **Pre-compute composite scores** — Implemented v3.7.20, then superseded by ADR-025 (v3.7.25). All fields consolidated into `computed_metrics` partition. `write_composite_scores()` call removed from lambda_handler; dead code removal tracked as CLEANUP-1. | Pre-R8, SIMP-1 prereq | — | — | ✅ Done + deprecated (ADR-025) |
| R8-ST6 | **CDK diff IAM change → blocking gate** — make CI pipeline block (not just warn) when CDK diff detects IAM/policy changes. | R8 §10 CD-4 | S (30min) | MEDIUM — prevents future IAM drift | ✅ Done (v3.7.17) — ci-cd.yml warning → error + exit 1 |
| R8-ST7 | **Tighten HAE webhook S3 write scope** — tightened from `raw/matthew/*` to 5 explicit paths. | R8 §5 IAM | S (15min) | LOW — least-privilege refinement | ✅ Done (v3.7.17) — role_policies.py updated, CDK deploy pending |

### Tier 3 — Strategic (90 days)

| ID | Item | Source | Effort | Impact | Status |
|----|------|--------|--------|--------|--------|
| R13-F14 | **MCP endpoint canary** — synthetic probe of remote MCP Function URL every 15 min. Existing canary tests DDB+S3+MCP but may not exercise the remote Function URL path. | R13 Finding-14 | S (2h) | MEDIUM — catches remote MCP downtime | ✅ Done (v3.7.40) |
| R13-F03 | **MCP monolith split assessment** — if MCP usage increases 5-10x, split into read-light (cached, metadata) and read-heavy (correlation, longitudinal, search) Lambdas. | R13 Finding-03 | L | MEDIUM — scaling readiness | Not needed now. Revisit at productization or >100 MCP calls/day. |
| R13-XR | **X-Ray tracing on MCP Lambda** — enables per-DDB-query latency diagnosis. Currently diagnosis requires log parsing. | R13 §Observability | S (2h) | LOW — operational maturity | ✅ Done (v3.7.40) |
| R8-LT1 | **Architecture Review #14** — post-R13 validation. Targeting ~2026-05-15 (after R13 30-day items resolved). | R13 30-60-90 roadmap | L (1 session) | HIGH — validates R13 improvements | Gated on R13-F01 through F09 |
| R8-LT2 | **Evaluate IC-4/IC-5 readiness** — failure pattern recognition + momentum/early warning. Data maturity gate ~6-8 weeks behavioral data. | INTELLIGENCE_LAYER.md | S (assessment) | MEDIUM — next IC features | Gated on data (~May 2026) |
| R8-LT3 | **Unit tests for business logic** — pytest unit tests for scoring_engine, character_engine, day grade computation. | R8 §9 testability | M-L | MEDIUM | ✅ Done (v3.7.20) — 74/74 tests in `tests/test_business_logic.py` |
| R8-LT4 | **DynamoDB export to S3 for analytics isolation** — separate analytical workload from transactional. Export to Parquet via DDB export, query with Athena. | R8 §17 roadmap | L | LOW — premature until data volume warrants | Not started |
| R8-LT5 | **Review SLO targets** — evaluate whether 99%/99.5% targets are appropriate based on 90 days of operational data. | R8 §17 roadmap | S (assessment) | LOW — operational maturity | Gated on 90 days data |
| R8-LT6 | **Lambda@Edge auth — verify CDK management** | R8 Finding-6, R8 §4 S | S (15min) | LOW | ✅ Done (v3.7.19) — confirmed manually managed outside CDK, documented in ARCHITECTURE.md |
| R8-LT7 | **Add disclaimer to `get_hypotheses` MCP tool** — unconfirmed hypotheses require 3 observations before promotion. | R8 §12 AI-2 | S (5min) | LOW — analytical transparency | ✅ Done (v3.7.17) — registry description updated |
| Risk-7 | **Compute pipeline timing: staleness observability** — Daily Brief emits `ComputePipelineStaleness` metric. Alarm `life-platform-compute-pipeline-stale` deployed. | R8 Top-10 Risk 7 | — | MEDIUM | ✅ DONE v3.7.31 — alarm deployed `deploy/create_compute_staleness_alarm.sh` |
| R8-LT8 | **DLQ consumer: event-driven vs scheduled** | R8 §6 R-3 | S (30min) | LOW | ✅ Done (v3.7.19) — ADR-024 written, retain schedule model |
| R8-LT9 | **Pre-compute weekly correlation matrix** — `SOURCE#weekly_correlations` partition. | Pre-R8 | M (3h) | LOW | ✅ Done (v3.7.20) — `weekly-correlation-compute` Lambda, 20 pairs, Sunday 11:30 AM PT |

### Tier 2.5 — April 13 Cleanup (run before R14)

These are not architecture decisions — they're deferred deletions and one-time setups.

| ID | Item | Source | Effort | Status |
|----|------|--------|--------|--------|
| CLEANUP-1 | **Remove `write_composite_scores()` dead code** | ADR-025 + R12 Viktor | S | ✅ Done (v3.7.28) |
| CLEANUP-2 | **Lambda@Edge in `ci/lambda_map.json`** | R12 Yael | S | ✅ Done (v3.7.27) — `lambda_edge` section with cf-auth, region, CloudFront ID |
| CLEANUP-3 | **Google Calendar OAuth activation** — run `python3 setup/setup_google_calendar_auth.py`. Not an engineering task. Deferred since v3.7.21. | R9-R13 every review | S (20min) | ⏳ Still pending — carry to Apr 13 |
| CLEANUP-4 | **`ingestion_validator.py` Decimal import fix** — `_Decimal` was used in typed_fields loop with no import anywhere in the file (live NameError risk). `from decimal import Decimal as _Decimal` moved to module level. `weekly_correlation_compute_lambda.py` was already clean. | R12 Elena + Marcus | S | ✅ Done (v3.7.29) |
| SEC-3 MEDIUM | **`validate_date_range` in `mcp/utils.py`** — new stable module. Prevents unbounded DDB range scans from MCP tool date inputs. Auto-applied in `handler._validate_tool_args` step 4 to all tools with `start_date`/`end_date` or `date` args. `validate_single_date` also included. | R13 Yael / board | S | ✅ Done (v3.7.29) |
| ADR-027 EXEC | **Stable MCP core → Layer** — Layer v10 published with 6 stable mcp/ modules. Ingestion + Email stacks updated to `:10`. | ADR-027 | — | ✅ DONE v3.7.31 — `life-platform-shared-utils:10` live, CDK deployed |

---

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
| R13 | Architecture Review #13 conducted (B+/A-) — 15 findings, full report `docs/reviews/REVIEW_2026-03-14_v13.md` | v3.7.29 | 2026-03-14 |
| R8-P0a | Webhook auth restored (CDK IAM fix) | v3.7.15 | 2026-03-13 |
| R8-P0b | Secret state reconciled (10 actual secrets documented) | v3.7.15 | 2026-03-13 |
| R8-P0c | IAM/secrets CI lint (`test_iam_secrets_consistency.py` S1-S4) | v3.7.15 | 2026-03-13 |
| R8-P0d | ARCHITECTURE.md secrets table updated | v3.7.15 | 2026-03-13 |
| R8-P0e | CV_THRESHOLDS stale comments fixed | v3.7.15 | 2026-03-13 |
| R8-P0f | SCHEMA.md added to sync_doc_metadata.py | v3.7.15 | 2026-03-13 |
| R57 | Attia centenarian decathlon benchmarks MCP tool (`get_centenarian_benchmarks`) | v3.7.31 | 2026-03-15 |
| R6 | Per-tool 30s soft timeout in MCP handler | v3.7.31 | 2026-03-15 |
| R54 | Evening nudge Lambda (`evening-nudge`, 8 PM PT daily) | v3.7.31 | 2026-03-15 |
| R55 | Withings OAuth consecutive-error alarm | v3.7.30 | 2026-03-15 |
| R31 | MCP error standardisation (`mcp_error()`, `ERROR_CODES`) | v3.7.30 | 2026-03-15 |
| R49 | ONBOARDING.md, deploy/README.md, DATA_FLOW_DIAGRAM.md | v3.7.30 | 2026-03-15 |
| ADR-027 | Stable Layer v10 (mcp/ core modules) + CDK rollout | v3.7.31 | 2026-03-15 |
| Risk-7 | Compute pipeline staleness alarm deployed | v3.7.31 | 2026-03-15 |
| R8-P0g | Architecture Review #8 conducted (A-) | v3.7.15 | 2026-03-13 |
| TB7-* | All TB7 items closed | v3.7.8 | 2026-03-13 |
| PROD-1 | CDK migration (8 stacks) | v3.4.0 | 2026-03-10 |
| SEC-1 | Per-function IAM roles (43 dedicated) | v3.4.0 | 2026-03-10 |
| COST-A | CloudWatch alarm consolidation (87→47) | v3.4.0 | 2026-03-10 |

---

## Architecture Review History

| # | Date | Version | Grade | Key Findings |
|---|------|---------|-------|-------------|
| R13 | 2026-03-14 | v3.7.29 | B+/A- | Full external-style review. 15 findings: no CI/CD pipeline (#1 risk), no integration tests, OAuth fail-open, correlation n-gating gap, no PITR drill, layer version fragility, no medical disclaimers in MCP responses. 30-60-90 roadmap. Report: `docs/reviews/REVIEW_2026-03-14_v13.md` |
| R12 | 2026-03-15 | v3.7.25 | A- | Validator S3 bug, 4 partitions unwired, composite_scores stale. All 8 items resolved same session. |
| R11 | 2026-03-15 | v3.7.24 | A | Engineering strategy: deploy_and_verify.sh, integration tests I1-I10, auto-discover counters, checklists. All 9 items resolved. |
| R10 | 2026-03-15 | v3.7.23 | A | Double-warmer, Calendar pre-auth handler, health_context wired. All items resolved. |
| R9 | 2026-03-14 | v3.7.22 | A | tools_calendar cold-start, n-gated correlations, dedicated warmer Lambda, 9 dispatcher tests. All 21 items resolved. |
| R8 | 2026-03-13 | v3.7.15 | A- | COST-B secret drift, webhook auth broken, complexity limits. Full report: `docs/reviews/architecture_review_8_full.md` |
| R7 | 2026-03-11 | v3.5.x | — | TB7 hardening sprint (25 items) |
| R6 | 2026-03-10 | v3.4.x | — | CDK migration review |
| R1-R5 | 2026-02-28–03-09 | various | — | See `docs/reviews/` |

---

## Key Metrics

| Metric | Current | Target | Notes |
|--------|---------|--------|-------|
| MCP tools | 89 | ≤80 (SIMP-1 Phase 2) | Phase 1 complete (116→89). Phase 2 gated ~Apr 13 |
| Lambdas | 43 (CDK) + 1 Lambda@Edge | — | Lambda@Edge (`cf-auth`) in us-east-1, manually managed |
| CloudWatch alarms | 49 | — | +SLO-5 warmer alarm (v3.7.22) |
| Monthly cost | ~$10 | <$25 | Well under budget |
| Active secrets | 11 | — | +google-calendar (v3.7.21) |
| CI linters | 9 | — | H1-H5, S1-S4, IAM, registry, handler, wiring, DDB patterns |
| SLOs defined | 5 | — | SLO-1 through SLO-5 (warmer added v3.7.22) |
| IC features live | 14 of 30 | — | Next: IC-4/IC-5 (~May 2026) |
| Data sources | 20 | — | google_calendar deployed; OAuth pending (CLEANUP-3) |
| Architecture review grade | B+/A- | A | R13 comprehensive review. Top gap: CI/CD pipeline (F01). Path to A-: resolve F01-F09. |
| R13 open findings | 12 of 15 | 0 | 6 Tier 1 (30d), 6 Tier 2 (60d), 3 Tier 3 (90d). See `docs/reviews/REVIEW_2026-03-14_v13.md` |
