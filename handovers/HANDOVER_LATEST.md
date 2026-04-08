# Handover — v6.7.0: Intelligence Layer V2 + V2.1 + V2.2 Complete

**Date:** 2026-04-07
**Session span:** 2026-04-06 → 2026-04-07 (extended multi-session)
**Scope:** Intelligence Layer V2 Session 1 — observatory persona consolidation, goals architecture, shared intelligence utilities (data inventory, data maturity, coach preamble), first-person voice enforcement.

## What Changed

### Coach Intelligence Architecture (Phases 1-5) — 8 NEW LAMBDAS

Built and deployed a multi-stage AI coach pipeline with 8 domain-specific coaches and 8 supporting Lambdas.

**Coaches (8):**

| Coach ID | Name | Domain |
|----------|------|--------|
| `sleep_coach` | Dr. Lisa Park | Sleep & circadian rhythm |
| `nutrition_coach` | Dr. Marcus Webb | Nutrition & metabolism |
| `training_coach` | Dr. Sarah Chen | Training & exercise |
| `mind_coach` | Dr. Nathan Reeves | Mental health & mindfulness |
| `physical_coach` | Dr. Victor Reyes | Physical health & body composition |
| `glucose_coach` | Dr. Amara Patel | Glucose regulation & CGM |
| `labs_coach` | Dr. James Okafor | Lab biomarkers & blood work |
| `explorer_coach` | Dr. Henning Brandt | Cross-domain patterns & experiments |

**Pipeline Lambdas (8):**

| Lambda | Purpose |
|--------|---------|
| `coach-computation-engine` | EWMA metrics, seasonal adjustments, anomaly detection per domain |
| `coach-narrative-orchestrator` | Generates coach prose with voice spec, thread continuity, epistemological framing |
| `coach-state-updater` | Updates relationship state, confidence scores, learning records |
| `coach-ensemble-digest` | Cross-coach synthesis, disagreement detection, influence graph |
| `coach-prediction-evaluator` | Scores past predictions, calibrates confidence |
| `coach-history-summarizer` | Compresses old threads into COMPRESSED#latest |
| `coach-quality-gate` | Validates output quality (hallucination, voice drift, repetition checks) |
| `coach-observatory-renderer` | Renders coach analysis for /api/coach_analysis endpoint |

**Pipeline flow:** Computation Engine -> Narrative Orchestrator -> Quality Gate -> State Updater -> (async) Ensemble Digest + Prediction Evaluator + History Summarizer.

### New DynamoDB Partitions

Seeded all new partitions for coach intelligence:

- **COACH#{coach_id}** — per-coach state with SK patterns: OUTPUT#, THREAD#{date}, LEARNING#{date}, PREDICTION#{date}, VOICE#state, RELATIONSHIP#state, CONFIDENCE#{subdomain}, COMPRESSED#latest
- **ENSEMBLE#digest / CYCLE#{date}** — cross-coach synthesis per generation cycle
- **ENSEMBLE#influence_graph / CONFIG#v1** — coach influence graph configuration
- **ENSEMBLE#disagreements / ACTIVE#{slug}** — tracked cross-coach disagreements
- **NARRATIVE#arc / STATE#current + HISTORY#{date}** — overarching narrative arc tracking
- **COACH#computation / RESULTS#{date}** — pre-computed EWMA metrics for all coaches

### S3 Configuration Files

- `config/coaches/*.json` — 8 voice specification files (one per coach)
- `config/coaches/influence_graph.json` — directed graph of coach-to-coach influence
- `config/computation/ewma_params.json` — EWMA smoothing parameters
- `config/computation/seasonal_adjustments.json` — seasonal adjustment factors
- `config/narrative/arc_definitions.json` — narrative arc definitions and phase transitions

### Observatory Integration

- `/api/coach_analysis` endpoint on site-api reads from COACH# DynamoDB partitions
- `observatory-v3.js` updated: tries `/api/coach_analysis?coach=<id>` first, falls back to legacy `/api/ai_analysis?expert=<key>`
- `ai_expert_analyzer_lambda.py` deprecated — replaced by `coach-observatory-renderer`

### Prompt Evolution Work

- Bug fixes in coach prompt generation
- Epistemological framing: coaches express appropriate uncertainty, distinguish observation from inference
- Fictitious coach names assigned (Dr. Park, Dr. Webb, Dr. Chen, etc.) for consistent voice identity
- Coach timestamp formatting: date/day/time prefix on coach analysis cards
- Timestamp placement refinement: moved under name/title, before prose content

## Files Changed

| File | Change |
|------|--------|
| `lambdas/coach_computation_engine/` | NEW — EWMA computation engine |
| `lambdas/coach_narrative_orchestrator/` | NEW — Voice-spec prose generation |
| `lambdas/coach_state_updater/` | NEW — State/confidence/learning updates |
| `lambdas/coach_ensemble_digest/` | NEW — Cross-coach synthesis |
| `lambdas/coach_prediction_evaluator/` | NEW — Prediction scoring |
| `lambdas/coach_history_summarizer/` | NEW — Thread compression |
| `lambdas/coach_quality_gate/` | NEW — Output validation |
| `lambdas/coach_observatory_renderer/` | NEW — Observatory API renderer |
| `lambdas/site_api_lambda.py` | Added /api/coach_analysis endpoint |
| `lambdas/ai_expert_analyzer_lambda.py` | DEPRECATED — replaced by coach-observatory-renderer |
| `site/assets/js/observatory-v3.js` | Coach analysis fallback chain |
| `cdk/stacks/compute_stack.py` | 8 new coach Lambda definitions |
| `cdk/stacks/role_policies.py` | 8 new IAM policies for coach Lambdas |
| `docs/ARCHITECTURE.md` | Lambda count 63->71, Coach Intelligence Layer section |
| `docs/SCHEMA.md` | Coach Intelligence Partitions section |
| `CLAUDE.md` | Lambda count 63->71 |

## What to Verify

### Smoke Tests
- [ ] `curl https://averagejoematt.com/api/coach_analysis?coach=sleep_coach` — returns coach analysis
- [ ] `curl https://averagejoematt.com/api/ai_analysis?expert=sleep` — legacy fallback still works
- [ ] Sleep observatory page — coach card renders from new endpoint
- [ ] All 8 coach DynamoDB partitions have seeded data

### CDK
- [ ] `cdk diff --all` shows no changes (compute stack deployed)

### Platform Quality Sweep (April 7)

**Critical fixes:**
- `coach_observatory_renderer.py` handler name mismatch (`handler` → `lambda_handler`)
- `_date_cls` undefined variable in `daily_brief_lambda.py` (ensemble digest invocation)
- Shared layer version drift — 7 Lambdas on stale layer versions, synced via full CDK deploy
- DLQ purged — 9 stale messages from `USER_ID` env var failures

**High-severity fixes:**
- MacroFactor field name bugs in `field_notes_lambda.py` and `site_api_lambda.py` (`calories` → `total_calories_kcal`)
- 302 → 307 weight fallbacks in 10+ files
- `os.environ["USER_ID"]` hard-crash pattern → `.get("USER_ID", "matthew")` in 41 Lambda files
- Experiment `days_in` off-by-one (`.days` → `.days + 1`)

**Deprecation cleanup:**
- `datetime.utcnow()` → `datetime.now(timezone.utc)` in 206 occurrences across 39 files (lambdas + mcp)
- Training "Coming Soon" placeholder hidden

**Website fixes:**
- Homepage ring label "lost" → "lbs lost"
- Mission page weight overwrite fix (start weight stays at 307)
- Pulse water glyph wired (was never rendered)
- Pulse Whoop query Limit 5 → 20 (workout sub-records flooding window)
- Homepage character data fallback chain (3 API layers)
- Observatory subtitle positioning (moved below status bar)
- Mobile scroll-through fix (overscrollBehavior + touchAction on menu)
- XP values rounded to 1 decimal place on character page
- "More" bottom nav button delegated click handler

**Documentation updated:**
- INTELLIGENCE_LAYER.md — full v6.0.0 rewrite
- ARCHITECTURE.md — 71 Lambdas, Coach Intelligence section
- SCHEMA.md — COACH#/ENSEMBLE#/NARRATIVE# partitions
- DECISIONS.md — ADR-047 (Coach Intelligence) + ADR-048 (Observatory Integration)
- CHANGELOG.md — v6.0.0 entry
- RUNBOOK.md — coach troubleshooting section
- ONBOARDING.md — coach mental model + glossary

### Observatory Intelligence Fixes (April 7 — continued session)

**P0 — Data Correctness:**
- **Character level carry-forward** — `load_previous_state()` now scans back 7 days instead of 1. Level restored to 4 (was dropping to 1 when compute skipped days).
- **Coach data blindness** — Added DEXA, measurements, labs to daily brief data dict (`_latest_item()` helper). Coaches now see body composition, lab results, and measurement data.
- **Step count SOT** — Garmin now primary for steps (wearable), Apple Health fallback. Was reversed.
- **Training interpretation** — `training_status: "no_training_logged"` explicitly signals no training vs missing data.
- **Data inventory injection** — Every coach prompt now receives a "DATA SOURCES AVAILABLE" block listing which sources have data and which don't. Coaches can no longer claim data is missing when it exists.

**P1 — Voice & Goals:**
- **First-person directive** — All coaches now instructed to write as "I" not "Dr. [Name]". Verified in regenerated outputs.
- **Goals injection** — System prompt now includes Matthew's goals (target weight, body comp, training philosophy, timeline, key priorities). Coaches no longer ask "what are your goals?"

**P2 — Rendering:**
- **Pulse FOUC fix** — Double `requestAnimationFrame` wrap before showing Pulse section to prevent unstyled flash on mobile.

**P3 — New Feature:**
- **Coach bio page** — `/coaches/` page with card layout for all 8 AI coaching personas. Shows name, title, voice description, domains, and link to latest observatory analysis.

## Known Issues / Carry Forward

- ~~Character level drop~~ **RESOLVED** — Level carry-forward now scans back 7 days.
- **Smoke test expectations stale** — `deploy/smoke_test_site.sh` has 15 failing checks for old V2/V3 HTML structures. Tests need updating, not the site.
- **/coaching/ dashboard page** — standalone coaching dashboard deferred (future sprint)
- **Coach Intelligence test coverage** — 8 new Lambda files (~300KB) have no unit tests
- **TDEE tracking** — blocked (MacroFactor doesn't export)
- **IC-4/IC-5** (failure pattern + momentum warning) — data gate ~May 1
- **PRE-13 Data Publication Review** — deferred
- **464 unused imports** — F401 flake8 warnings, cosmetic cleanup

## Current System State

| Metric | Value |
|--------|-------|
| MCP Tools | 115 |
| Lambdas | 71 |
| Site Pages | 72 |
| Lambda Layer | v32 |
| Architecture Grade | A- (R20) |
| CDK Stacks | 8 |
| AI Coaches | 8 |
| Coach DDB Partitions | 6 partition families |
| Test Results | 1103 passed, 1 infra-only failure |
| Site Pages | 73 (added /coaches/) |
| Shared Layer Modules | 18 (added intelligence_common.py) |
| Board Members | 18 (added amara_patel, victor_reyes, nathan_reeves, henning_brandt) |
| MCP Tools | 123 |
| Site Pages | 75 (added /predictions/, updated /coaches/) |
| Version | v6.7.0 |

## Intelligence Layer V2 — All Sessions Complete

| Session | Workstream | Status |
|---------|-----------|--------|
| S1 | W0 Persona Consolidation + W5 Goals | Complete — board v3.0, user_goals.json, intelligence_common.py |
| S2 | W2 Cold-Start Voice | Complete — 3-phase voice, thresholds refined |
| S3 | W4 Intelligence Validator | Complete — 5 checks, DDB partition, MCP tool |
| S4 | W1 Coach Synthesis | Complete — Dr. Nakamura, /api/weekly_priority, cross-domain notes |
| S5 | W3 Action Completion Loop | Complete — DDB tracking, auto-detection, MCP tools |
| S6 | W6 Builder's Paradox | Complete — score computation, Maya integration, journal prompt |

## What's Next
- Tune voice specs and thresholds as data accumulates (Phase 6 refinement)
- /coaching/ dashboard page (deferred — standalone design session)
- Inline correction mode for validator (Mode B — re-prompt on errors)
- Surface "Open Actions" widget on homepage Pulse section
