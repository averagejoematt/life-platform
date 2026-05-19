# Coach Intelligence Architecture — Claude Code Execution Prompt

## Context

You are implementing the Coach Intelligence Architecture for the Life Platform. The full design specification is at `docs/COACH_INTELLIGENCE_DESIGN_SPEC.md` — read it in full before starting.

This is a multi-phase project. This prompt covers **Phase 1 (Foundation) and Phase 2 (Single Coach Proof of Concept)**.

## Before You Begin

1. Read `handovers/HANDOVER_LATEST.md` for current platform state
2. Read `docs/COACH_INTELLIGENCE_DESIGN_SPEC.md` in full
3. Read `docs/ARCHITECTURE.md` for current infrastructure context
4. Read `docs/INTELLIGENCE_LAYER.md` for current IC feature documentation
5. Read `mcp/registry.py` to understand current tool count (SIMP-1 budget: ≤80 tools target)
6. Read `lambdas/` directory to understand current Lambda structure
7. Read the existing email generation Lambdas to understand the current coach prompt + data flow you'll be modifying

## Phase 1: Foundation

### 1A: DynamoDB Schema Additions

Add the following partition key schemes to the existing `life-platform` table. No new table — use existing table with new PK/SK patterns:

- `COACH#{coach_id}` — with SK patterns for `OUTPUT#`, `THREAD#`, `LEARNING#`, `PREDICTION#`, `VOICE#state`, `RELATIONSHIP#state`, `CONFIDENCE#{subdomain}`, `COMPRESSED#latest`
- `ENSEMBLE#digest` — with SK `CYCLE#{date}`
- `ENSEMBLE#influence_graph` — with SK `CONFIG#v1`
- `ENSEMBLE#disagreements` — with SK `ACTIVE#{topic_slug}`
- `NARRATIVE#arc` — with SK `STATE#current` and `HISTORY#{date}`

No CDK changes needed if no new GSIs are required — these are just new item patterns in the existing table. If a GSI is needed for cross-coach prediction queries, add it to the appropriate CDK stack.

### 1B: Deterministic Computation Engine

Create `lambdas/coach-computation-engine/handler.py`:

This Lambda does ALL math — the LLM never does math. Implement:

1. **EWMA trend detection** with domain-specific decay parameters:
   - Sleep: λ=0.85, HRV/recovery: λ=0.87, Training: λ=0.90, Nutrition/body comp: λ=0.95, Mood: λ=0.80
2. **Regression-to-mean detection** — flag when a change from an extreme value moves toward the baseline mean
3. **Seasonality flags** — compare trends against population-level seasonal adjustment table (use placeholder values from the spec, stored in S3 config)
4. **Autocorrelation warnings** — flag when a "trend" in a highly autocorrelated metric (HRV, sleep score) is likely noise
5. **Statistical guardrails** — tag every metric with data availability: <7 days = "observational only", <14 days = "preliminary", 14+ days = "established"
6. **Prediction evaluation** — for machine-evaluable predictions: check threshold, compare against null hypothesis, update Bayesian confidence (Beta distribution)

Store EWMA params in `config/computation/ewma_params.json` and seasonal adjustments in `config/computation/seasonal_adjustments.json` — upload both to S3 under `s3://matthew-life-platform/config/computation/`.

Output: a structured JSON computation results package consumed by the narrative orchestrator.

### 1C: Voice Specifications

Create voice specification JSON files for each coach in `config/coaches/{coach_id}.json`. Follow the schema from Section 5 of the design spec exactly. Each coach needs:

- `structural_voice_rules`: opening patterns (preferred + forbidden + rotation rule), sentence rhythm, uncertainty style, analogy domain, paragraph structure, humor style, relationship to other coaches, signature moves
- `decision_style`: default evidence threshold, comfort with bold claims, revision style
- `few_shot_examples`: 3-4 paragraphs of gold-standard output that anchor the voice regardless of model changes
- `anti_pattern_detection`: phrase blacklist, structural blacklist, staleness threshold

Write genuinely distinct voices. The fitness coach should not sound like the sleep coach with different vocabulary — they should have different *structures*, different rhythms, different ways of building arguments. Reference Marcus Adler's guidance in Section 5 of the spec.

Upload to `s3://matthew-life-platform/config/coaches/`.

### 1D: Cross-Coach Influence Graph

Create `config/coaches/influence_graph.json` with the weights from Section 6 of the spec. Upload to S3.

### 1E: Seed Initial State

Write a seed script (`seeds/seed_coach_state.py` or similar) that:

1. Queries existing coach outputs (emails generated to date — we're on day 6, so this is minimal)
2. Creates initial `COACH#` records for each coach: empty thread registries, Beta(1,1) confidence priors, relationship state set to `early`, voice state initialized
3. Creates initial `NARRATIVE#arc` `STATE#current` set to `early_baseline`
4. Creates initial `ENSEMBLE#influence_graph` `CONFIG#v1` from the JSON config
5. Run the seed

### 1F: Deploy Script

Create `deploy/deploy_coach_intelligence.sh` for the new Lambda(s). Follow existing deploy conventions — use `deploy/deploy_lambda.sh` for standard Lambdas.

## Phase 2: Single Coach Proof of Concept — Sleep Coach

The sleep coach (Dr. Matthew Walker persona) is the proof of concept because:
- Sleep has the highest cross-domain influence (outbound weight 0.9 to all)
- Sleep is downstream of everything — natural integrator role
- High data availability from Whoop + Eight Sleep from day 1

### 2A: Narrative Orchestrator

Create `lambdas/coach-narrative-orchestrator/handler.py`:

This is an LLM call (Haiku-class for cost efficiency) that:

1. Reads all coach compressed states from DynamoDB
2. Reads ensemble digest (will be empty initially — that's fine)
3. Reads computation results package from the computation engine
4. Reads narrative arc state
5. Produces a **generation brief** for the target coach (sleep coach for now)

Follow the generation brief schema from Section 4 of the spec exactly. The brief must include: open threads, cross-coach context (with influence weights applied), predictions to address, narrative beat, journey phase, voice guidance (anti-patterns to avoid, suggested opening type), decision class ceiling, evidence notes, computation outputs.

### 2B: Coach State Updater

Create `lambdas/coach-state-updater/handler.py`:

Post-generation LLM call (Haiku-class) that reads the coach's output and extracts:

1. Themes and structural fingerprint (opening type, paragraph count, analogy usage)
2. New threads opened (observations flagged, concerns raised)
3. Threads referenced or resolved
4. Predictions made (flag for formal schema creation — may need human review)
5. Anti-pattern violations (did the coach use a forbidden phrase?)
6. Decision classes used

Writes extracted data to the coach's state store partitions.

### 2C: Wire Into Email Pipeline

Modify the existing sleep coach email generation Lambda to:

1. **Before generation**: invoke computation engine → invoke narrative orchestrator → receive generation brief
2. **During generation**: replace current persona prompt + data approach with: voice spec (from S3) + few-shot examples + generation brief + domain data
3. **After generation**: invoke coach state updater with the output

Ensure the fallback works: if orchestrator fails, generate with current approach (voice spec + recent data + last outputs). Log degraded generation.

### 2D: Reasoning Traces

Store a reasoning trace record alongside each output:

```json
{
  "PK": "COACH#sleep_coach",
  "SK": "TRACE#2026-04-XX#weekly_email",
  "recommendations_made": [...],
  "primary_drivers": [...],
  "counterfactuals_considered": [...],
  "decision_classes_used": [...],
  "cross_coach_inputs_used": [...],
  "predictions_made": [...],
  "threads_status": [...]
}
```

## Important Rules

- **NEVER register a tool in TOOLS dict without the implementing function existing in the same commit.** Use stubs if implementing later.
- **Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy.**
- **Tool functions MUST go BEFORE the `TOOLS={}` dict.** Functions defined after cause `NameError` at import.
- **Use `deploy/deploy_lambda.sh` for all Lambda deploys** — it auto-reads handler config from AWS.
- **Wait 10s between sequential Lambda deploys.**
- **MCP Lambda requires full package**: `zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/` — never use `deploy_lambda.sh` for it.
- **NEVER use `aws s3 sync --delete`** against bucket root or `site/` prefix.
- **N<30 = low confidence; <12 observations = "preliminary pattern"** (Henning Brandt standard).
- Use correlational not causal language throughout.
- All new Lambdas need entries in `ci/lambda_map.json`.

## Completion Checklist

- [ ] Design spec read in full
- [ ] Computation engine Lambda created and tested
- [ ] Voice specs created for all coaches and uploaded to S3
- [ ] Influence graph config uploaded to S3
- [ ] EWMA params and seasonal adjustments uploaded to S3
- [ ] Initial coach state seeded in DynamoDB
- [ ] Narrative orchestrator Lambda created and tested
- [ ] Coach state updater Lambda created and tested
- [ ] Sleep coach email generation Lambda modified with new pipeline
- [ ] Fallback pipeline verified (orchestrator failure → graceful degradation)
- [ ] Reasoning traces stored on generation
- [ ] Deploy scripts created
- [ ] `ci/lambda_map.json` updated
- [ ] `PLATFORM_FACTS` in `deploy/sync_doc_metadata.py` updated if counts changed
- [ ] `python3 deploy/sync_doc_metadata.py --apply` run
- [ ] `CHANGELOG.md` updated
- [ ] Handover written + `HANDOVER_LATEST.md` updated
- [ ] `git add -A && git commit && git push`

## What NOT To Build Yet (Phase 3+)

- Ensemble digest writer (needs multiple coaches on new system first)
- Prediction evaluator scheduled Lambda (needs predictions to accumulate first)
- History summarizer / compression pipeline (not needed until output volume grows)
- Remaining coach migrations (wait for sleep coach proof of concept validation)
- MCP tool integration for coach state queries
- Narrative arc transition logic
- Quality gate Lambda
