# Handover — v6.0.0: Coach Intelligence Architecture

**Date:** 2026-04-06
**Scope:** Coach Intelligence Architecture (Phases 1-5 + Observatory Integration) — 8 new Lambdas, 8 AI coaches, new DynamoDB partitions, Observatory wiring, prompt evolution, ai_expert_analyzer deprecated.

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

## Known Issues / Carry Forward

- **Phase 6 refinement** — coach output tuning, confidence calibration, ensemble weighting adjustments
- **/coaching/ dashboard page** — standalone coaching dashboard deferred (future sprint)
- **Coach scheduling** — pipeline trigger schedule not yet on EventBridge (manual invocation for now)
- **TDEE tracking** — blocked (MacroFactor doesn't export)
- **IC-4/IC-5** (failure pattern + momentum warning) — data gate ~May 1
- **PB-08 Intelligence Page Rebuild** — gated on SIMP-1 Phase 2
- **PRE-13 Data Publication Review** — deferred

## Current System State

| Metric | Value |
|--------|-------|
| MCP Tools | 115 |
| Lambdas | 71 |
| Site Pages | 72 |
| Lambda Layer | v26 |
| Architecture Grade | A- (R20) |
| CDK Stacks | 8 |
| AI Coaches | 8 |
| Coach DDB Partitions | 6 new partition families |
| Version | v6.0.0 |
