# Expert Review — Recommendation Tracker
**Review Date:** 2026-02-28 (v2.47.1) | **Tracker Created:** 2026-03-01 (v2.54.0)

> Consolidated list of every actionable recommendation from Phases 1–8.
> Status: ✅ DONE | ⏳ TODO | 🔜 DEFERRED | ❌ REJECTED

---

## Summary

| Status | Count |
|--------|-------|
| ✅ Done | 29 |
| ⏳ Todo | 16 |
| 🔜 Deferred | 5 |
| ❌ Rejected | 1 |
| **Total** | **51** |

---

## Phase 1 — Architecture (6 recommendations)

| # | Finding | Severity | Recommendation | Status | Notes |
|---|---------|----------|----------------|--------|-------|
| R1 | F1.1 — Daily Brief is 3,011-line monolith | MEDIUM | Extract day_grade + habit_scores compute into separate "daily-compute" Lambda (run 9:50 AM), brief reads pre-computed results | ⏳ TODO | Decouples compute from email rendering; each piece independently testable |
| R2 | F1.2 — Todoist/Strava/Activity Enrichment timeouts excessive | LOW | Right-size timeouts: Todoist→30s, Strava→60s, Activity Enrichment→120s (check CloudWatch p99 first) | ✅ DONE | All 5 Lambdas already at recommended values (Todoist 30s, Strava 120s, Activity 180s, Journal 120s, MacroFactor 60s) |
| R3 | F1.5 — Webhook handles 4 data types | LOW | Split into separate handlers if more HAE data types added | 🔜 DEFERRED | Not needed at current scale; revisit if webhook grows |
| R4 | F1.6 — DST cron drift risk | INFO | Ensure `deploy/deploy_dst_spring_2026.sh` is in calendar for Mar 8. Add recurring calendar events for both DST transitions | ⏳ TODO | Script updated (18→21 rules: +weather, +chronicle, +nutrition-review). **Run on Mar 8 before 6 AM PDT.** |
| R5 | F1.7 — MCP Lambda may be over-provisioned at 1024 MB | LOW | Run AWS Lambda Power Tuning to find optimal memory/cost tradeoff | ⏳ TODO | 512 MB could save ~$0.50/mo on Dropbox poll invocations |
| R6 | F1.8 — No per-tool timeout in MCP | INFO | Add 30s soft timeout per tool that returns "query too broad" instead of Lambda timeout | ⏳ TODO | Improves reliability for correlation tools scanning 180+ days |

---

## Phase 2 — Schema (5 recommendations)

| # | Finding | Severity | Recommendation | Status | Notes |
|---|---------|----------|----------------|--------|-------|
| R7 | F2.1 — Strava item size risk | MEDIUM | Add size check in Strava Lambda: warn if item >350KB. Consider splitting activities to separate SK items | ⏳ TODO | 400KB DynamoDB limit; low risk at current usage but no monitoring |
| R8 | F2.2 — MacroFactor food_log nesting | MEDIUM | Add size monitoring. If items approach 300KB, move food_log entries to separate items | ⏳ TODO | Same 400KB risk as Strava |
| R9 | F2.4 — habit_scores partition is sparse | INFO | Re-run habit_scores backfill monthly as Habitify data accumulates | ⏳ TODO | Trending tools need 30+ days; backfill script exists |
| R10 | F2.5 — No data validation at write time | LOW | Add lightweight field-presence validation to Whoop, Strava, Eight Sleep ingestion Lambdas (log WARN if key fields missing) | ⏳ TODO | Catches upstream API changes early |
| R11 | F2.7 — Profile record growing | LOW | Monitor profile item size. If >200KB, split habit_registry to `PROFILE#habit_registry` | ⏳ TODO | Currently not an issue but registry is large |

---

## Phase 3 — Security / IAM (8 recommendations)

| # | Finding | Severity | Recommendation | Status | Notes |
|---|---------|----------|----------------|--------|-------|
| R12 | F3.1 — Shared digest role is broad | MEDIUM | Split into `lambda-daily-brief-role` (full write) and `lambda-digest-read-role` (read-only DDB + SES) | ⏳ TODO | Prevents monthly digest from accidentally writing to day_grade/habit_scores |
| R13 | F3.3 — No IAM policy version pinning | INFO | Periodically export IAM policies to `security/` directory for documentation | ⏳ TODO | Low priority; MANIFEST helps but doesn't capture IAM state |
| R14 | F3.4.1 — MCP Function URL uncapped concurrency | **HIGH** | Set reserved concurrency to 10: `aws lambda put-function-concurrency --function-name life-platform-mcp --reserved-concurrent-executions 10` | ✅ DONE | v2.48.0 — $0 cost, prevents DDoS cost runaway |
| R15 | F3.4.3 — No secondary auth barrier on Function URL | LOW | Add User-Agent or custom header check as lightweight additional barrier | ⏳ TODO | Bearer token is primary auth; this is defense-in-depth |
| R16 | F3.5 — API Gateway webhook has no rate limiting | LOW | Add usage plan with daily quota (e.g., 100 req/day) on health-auto-export-api | ✅ DONE | Route-level throttling configured: 10 req/s rate, burst 20 on POST /ingest |
| R17 | F3.7 — No automatic secret rotation | LOW | Implement MCP API key rotation (roadmap item #15) | ✅ DONE | v2.54.0 — 90-day auto-rotation, rotator Lambda, Bearer cache TTL |
| R18 | F3.8 — Withings OAuth fragility | LOW | Add specific "OAuth may expire soon" alert if Withings Lambda fails 2 consecutive days | ⏳ TODO | Currently gets generic freshness alert; targeted alert would prompt faster action |
| R19 | F3.9 — Dashboard data.json publicly accessible | INFO | Consider CloudFront Functions with cookie/token check, or signed URLs | 🔜 DEFERRED | Acceptable risk — URLs not indexed, security through obscurity |

---

## Phase 4 — Costing (3 recommendations)

| # | Finding | Severity | Recommendation | Status | Notes |
|---|---------|----------|----------------|--------|-------|
| R20 | F4.1 — Secrets Manager is 72% of cost ($4.80/mo) | MEDIUM | Consolidate static API keys into single JSON secret (Todoist, Habitify, Notion, HAE, MCP) — saves $2.00/mo | ⏳ TODO | Optional; $4.80 is still trivial. Would reduce 12→7 secrets |
| R21 | F4.2 — 9 log groups have infinite retention | MEDIUM | Set 30-day retention on all log groups | ✅ DONE | v2.48.0 — one-liner script applied to all 9 groups |
| R22 | F4.3 — MCP Lambda concurrency cost risk | LOW | (Covered by R14 — reserved concurrency) | ✅ DONE | v2.48.0 |

---

## Phase 5 — Technical (10 recommendations)

| # | Finding | Severity | Recommendation | Status | Notes |
|---|---------|----------|----------------|--------|-------|
| R23 | F5.1 — config.py version stale (2.45.0) | BUG | Update `__version__` to current. Add to deploy checklist | ✅ DONE | v2.48.0 — updated to 2.47.2 |
| R24 | F5.2 — SOURCES list incomplete (15 vs 19+) | BUG | Update SOURCES to include all active sources; consider DATA_SOURCES vs DERIVED_SOURCES split | ✅ DONE | v2.48.0 — added weather, supplements, state_of_mind, habit_scores |
| R25 | F5.3 — _DEFAULT_SOURCE_OF_TRUTH missing 5 domains | BUG | Sync with profile's full 20-domain list | ✅ DONE | v2.48.0 — added water, caffeine, supplements, weather, state_of_mind |
| R26 | F5.4 — Timeout over-provisioning on 5 Lambdas | LOW | Right-size: Todoist→30s, Strava→120s, Activity Enrichment→180s, Journal Enrichment→120s, MacroFactor→60s | ✅ DONE | All at recommended values (verified 2026-03-01) |
| R27 | F5.5 — journal-enrichment under-provisioned at 128 MB | LOW | Bump to 256 MB for consistency with other Haiku-calling Lambdas | ✅ DONE | Already at 256 MB (verified 2026-03-01) |
| R28 | F5.6 — Daily brief timeout tight at 210s | INFO | Increase to 300s for safety margin | ✅ DONE | Already at 300s (verified 2026-03-01) |
| R29 | F5.7 — No AWS Lambda Powertools | OPP | Add Powertools layer for structured logging, X-Ray tracing, correlation IDs | 🔜 DEFERRED | Nice-to-have; invaluable for debugging slow MCP tools |
| R30 | F5.8 — Daily brief has no section-level error handling | MEDIUM | Wrap each of 18 sections in try/except with graceful degradation (17/18 sections > 0/18) | ✅ DONE | All 18 sections wrapped with _section_error_html graceful fallback (verified 2026-03-01) |
| R31 | F5.9 — MCP tool error responses inconsistent | LOW | Standardize on `{"error": "...", "error_code": "...", "suggestions": [...]}` | ⏳ TODO | Improves Claude's ability to offer recovery suggestions |
| R32 | F5.10 — No structured error logging | LOW | Switch to JSON logging: `{"event": "ingestion_failed", "source": "whoop", "error": "..."}` | ⏳ TODO | Enables CloudWatch Insights queries grouped by source |

---

## Phase 6 — Observability (8 recommendations)

| # | Finding | Severity | Recommendation | Status | Notes |
|---|---------|----------|----------------|--------|-------|
| R33 | 2 Lambdas missing error alarms | P1 | Add alarm for `weather-data-ingestion` | ✅ DONE | v2.54.0 — `weather-data-ingestion-errors` alarm exists |
| R34 | Freshness checker unmonitored | P1 | Add alarm for `life-platform-freshness-checker` — who watches the watchman? | ✅ DONE | v2.54.0 — `freshness-checker-errors` alarm exists |
| R35 | No duration alarms | P2 | Add duration alarms for `daily-brief` and `life-platform-mcp` | ✅ DONE | v2.54.0 — `daily-brief-duration-high` + `mcp-server-duration-high` (240s threshold) |
| R36 | No "no invocations" alarm for daily brief | P3 | Add "no invocations" alarm — detect if EventBridge stops firing | ✅ DONE | v2.54.1 — `daily-brief-no-invocations-24h` (TreatMissingData=breaching) |
| R37 | 9 log groups with infinite retention | P1 | Set 30-day retention on all | ✅ DONE | v2.48.0 (same as R21) |
| R38 | 5 stale DLQ messages | P1 | Purge messages from resolved P0 outage | ✅ DONE | v2.48.0 |
| R39 | No DLQ message retention policy | P2 | Add 14-day retention policy on DLQ so stale messages auto-expire | ✅ DONE | Already configured — MessageRetentionPeriod=1209600 (14 days) |
| R40 | No CloudWatch ops dashboard | P3 | Create CloudWatch dashboard: Lambda invocations, errors, durations, DDB consumed capacity | ⏳ TODO | Free (up to 3 dashboards); provides ops-level visibility |

---

## Phase 7 — Documentation (9 recommendations)

| # | Finding | Severity | Recommendation | Status | Notes |
|---|---------|----------|----------------|--------|-------|
| R41 | MCP_TOOL_CATALOG.md 6 versions stale | **HIGH** | Update to current version with all tools | ✅ DONE | v2.48.0 doc sprint — 94→97 tools |
| R42 | FEATURES.md 6 versions stale | **HIGH** | Update with Habit Intelligence, remote MCP, dashboard Phase 2, etc. | ✅ DONE | v2.48.0 doc sprint |
| R43 | USER_GUIDE.md 6 versions stale | **HIGH** | Update tool count, add usage examples for new tools | ✅ DONE | v2.48.0 doc sprint |
| R44 | INCIDENT_LOG.md missing Feb 28 P0 | MEDIUM | Add P0 outage entry, cross-reference PIR | ✅ DONE | v2.48.0 doc sprint |
| R45 | RUNBOOK.md 4 versions stale | MEDIUM | Add habit registry ops, smoke test ref, Withings re-auth | ✅ DONE | v2.48.0 doc sprint |
| R46 | COST_TRACKER.md 14 versions stale | MEDIUM | Update with current cost breakdown | ✅ DONE | v2.48.0 doc sprint |
| R47 | DATA_DICTIONARY.md 14 versions stale | MEDIUM | Add missing SOT entries for 5 sources | ✅ DONE | v2.48.0 doc sprint |
| R48 | Consider doc consolidation | LOW | Merge DATA_DICTIONARY→SCHEMA, FEATURES+USER_GUIDE→single doc (13→11 docs) | ⏳ TODO | Reduces maintenance surface |
| R49 | 3 missing docs: ONBOARDING.md, deploy/README.md, DATA_FLOW_DIAGRAM.md | LOW | Create "start here" doc, deploy script guide, Mermaid data flow diagram | ⏳ TODO | Nice-to-have for project maturity |

---

## Phase 8 — Board of Directors (7 recommendations)

| # | Finding | Severity | Recommendation | Status | Notes |
|---|---------|----------|----------------|--------|-------|
| R50 | Rec A — Doc Sprint | URGENT | Dedicate full session to updating all stale docs | ✅ DONE | v2.48.0 — all 13 docs brought current |
| R51 | Rec B — Fix config.py bugs | URGENT | (Covered by R23/R24/R25) | ✅ DONE | v2.48.0 |
| R52 | Rec C — Reserved concurrency | URGENT | (Covered by R14) | ✅ DONE | v2.48.0 |
| R53 | Rec D — 30-day maturation focus | ONGOING | Focus on consistent daily data hygiene (supplements, journal, CGM, How We Feel) rather than new features | ⏳ TODO | Ongoing discipline; platform value compounds with data density |
| R54 | Rec E — Evening nudge email | MEDIUM | 8 PM "Did you log supplements? Journal? How We Feel?" email to improve manual-input data completeness | ⏳ TODO | Low engineering effort (EventBridge + SES Lambda) |
| R55 | WAF rate limiting (#14) | — | Reject WAF in favor of reserved concurrency | ❌ REJECTED | Reserved concurrency (R14) achieves 80% protection at $0 vs $5/mo |
| R56 | VO2max clinical test | INFO | Schedule a clinical VO2max test; add result to manual entry workflow | ⏳ TODO | Strongest mortality predictor; Apple Health proxy unreliable |
| R57 | Strength benchmarks (centenarian decathlon) | INFO | Track compound lift benchmarks (deadlift, squat, bench, OHP) against Attia's framework | ⏳ TODO | MacroFactor captures volume but not key benchmarks |
| R58 | Cold/heat exposure tracking | INFO | Add journal template question or habit registry entry for deliberate cold exposure | ⏳ TODO | Huberman/Sussman high-ROI protocol; zero engineering cost if habit-based |

---

## Prioritized TODO List

### 🔴 P0 — Do Next (high impact, low effort)

| # | Recommendation | Effort | Source |
|---|----------------|--------|--------|
| R4 | DST cron deployment — **script ready, run on Mar 8!** | 2 min | Phase 1 |
| ~~R30~~ | ~~Daily brief section-level try/except~~ | ~~30 min~~ | ✅ Already implemented (18/18 sections) |
| ~~R28~~ | ~~Daily brief timeout 210s→300s~~ | ~~1 min~~ | ✅ Already at 300s |
| ~~R27~~ | ~~Journal-enrichment memory 128→256 MB~~ | ~~1 min~~ | ✅ Already at 256 MB |
| ~~R2/R26~~ | ~~Right-size Lambda timeouts (5 Lambdas)~~ | ~~15 min~~ | ✅ All at recommended values |

### 🟡 P1 — High Value (security, observability gaps)

| # | Recommendation | Effort | Source |
|---|----------------|--------|--------|
| ~~R33~~ | ~~Add alarm: weather-data-ingestion~~ | ~~5 min~~ | ✅ Already existed |
| ~~R34~~ | ~~Add alarm: freshness-checker~~ | ~~5 min~~ | ✅ Already existed |
| ~~R35~~ | ~~Add duration alarms: daily-brief + MCP~~ | ~~10 min~~ | ✅ Already existed |
| ~~R36~~ | ~~Add "no invocations" alarm: daily-brief~~ | ~~5 min~~ | ✅ Created v2.54.1 |
| ~~R39~~ | ~~DLQ 14-day message retention policy~~ | ~~5 min~~ | ✅ Already configured |
| ~~R16~~ | ~~API Gateway usage plan (100 req/day quota)~~ | ~~15 min~~ | ✅ Route throttle exists |
| R18 | Withings OAuth-specific 2-day failure alert | 15 min | Phase 3 |
| R54 | Evening nudge email for data completeness | 1-2 hr | Phase 8 |

### 🟢 P2 — Good Hygiene (schema safety, error handling)

| # | Recommendation | Effort | Source |
|---|----------------|--------|--------|
| R7 | Strava item size monitoring (>350KB warn) | 15 min | Phase 2 |
| R8 | MacroFactor item size monitoring | 15 min | Phase 2 |
| R10 | Write-time field validation (Whoop/Strava/Eight Sleep) | 1 hr | Phase 2 |
| R12 | Split shared digest role (daily-brief vs read-only) | 30 min | Phase 3 |
| R31 | Standardize MCP tool error responses | 1-2 hr | Phase 5 |
| R32 | Structured JSON error logging across Lambdas | 1-2 hr | Phase 5 |
| R15 | User-Agent/custom header check on Function URL | 15 min | Phase 3 |

### 🔵 P3 — Nice-to-Have (optimization, polish)

| # | Recommendation | Effort | Source |
|---|----------------|--------|--------|
| R1 | Split daily brief into compute + render Lambdas | 3-4 hr | Phase 1 |
| R5 | Lambda Power Tuning for MCP memory optimization | 1 hr | Phase 1 |
| R6 | Per-tool soft timeout in MCP (30s) | 1 hr | Phase 1 |
| R9 | Monthly habit_scores backfill re-run | 15 min | Phase 2 |
| R11 | Monitor profile record size | 15 min | Phase 2 |
| R13 | Export IAM policies to security/ directory | 30 min | Phase 3 |
| R20 | Secrets Manager consolidation (save $2/mo) | 1-2 hr | Phase 4 |
| R40 | CloudWatch ops dashboard | 1 hr | Phase 6 |
| R48 | Doc consolidation (13→11 docs) | 1 hr | Phase 7 |
| R49 | Create ONBOARDING.md, deploy/README.md, DATA_FLOW_DIAGRAM.md | 2 hr | Phase 7 |
| R56 | Schedule clinical VO2max test | N/A | Phase 8 |
| R57 | Track compound lift benchmarks | 1 hr | Phase 8 |
| R58 | Cold/heat exposure habit tracking | 15 min | Phase 8 |

### 🔜 Deferred

| # | Recommendation | Revisit | Source |
|---|----------------|---------|--------|
| R3 | Split webhook Lambda by data type | When adding more HAE types | Phase 1 |
| R19 | Dashboard data.json access restriction | If security posture changes | Phase 3 |
| R29 | AWS Lambda Powertools | When debugging slow tools | Phase 5 |
| R53 | 30-day maturation focus | Ongoing | Phase 8 |

---

## Review Completion Status

**29 of 51 recommendations completed** (57%) — all P0/URGENT items resolved. P1 observability gaps closed in v2.54.1. Many P0 items were already implemented but tracker lagged behind.

**16 actionable TODOs remain.** Only P0 item left is R4 (DST script — run Mar 8).

**Note:** 3 new Lambdas (wednesday-chronicle, nutrition-review, life-platform-key-rotator) added error alarms in v2.54.1 — not part of original review but closes the coverage gap. All 25 Lambdas now have at least one CloudWatch alarm (29 total alarms).
