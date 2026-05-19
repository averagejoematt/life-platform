# Life Platform — Intelligence Layer

> Documents the Coach Intelligence Architecture and the legacy Intelligence Compounding (IC) features.
> For the IC roadmap and future phases, see PROJECT_PLAN.md (Tier 7).
> Last updated: 2026-04-06 (v6.0.0)
>
> **v6.0.0 (Coach Intelligence Architecture):** Full stateful coaching system — 8 domain coaches with persistent state, deterministic computation engine, narrative orchestration, ensemble consensus, prediction tracking with Bayesian evaluation, quality gate, weekly history compression, and observatory rendering. Supersedes the stateless prompt-template approach for daily coaching output.

---

## Overview

The Intelligence Layer has evolved through two distinct phases:

**Phase 1 (IC features, v2.86 - v5.3):** Stateless prompt templates with memory injection. Each AI call assembled context from DynamoDB, ran a two-pass chain-of-thought (IC-3), and produced coaching output with no memory of what it said yesterday. Anti-repetition was bolted on via `guidance_given` (v4.8.0), but the fundamental architecture was stateless: same data in, same coaching out, with no voice continuity, no prediction tracking, and no cross-coach coordination.

**Phase 2 (Coach Intelligence Architecture, v6.0):** Eight named coaches with persistent state, distinct analytical voices, a deterministic computation engine, narrative arc awareness, formal prediction tracking with Bayesian confidence updates, ensemble consensus, and quality assurance. The system remembers what it said, tracks whether its predictions were right, compresses its own history, and coordinates across domains.

The architecture decision (ADR-016) remains: no vector store, no embeddings, no fine-tuning. Pure DynamoDB key-value + structured context injection + S3 config + prompt engineering + deterministic statistical computation.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  COACH INTELLIGENCE PIPELINE (daily, sequential)                 │
│                                                                  │
│  Step 1: COMPUTATION ENGINE (deterministic, no LLM)              │
│    coach-computation-engine Lambda                               │
│    ├─ EWMA trends (domain-specific decay from S3 config)         │
│    ├─ Regression-to-mean detection (z > 1.5 + mean reversion)    │
│    ├─ Seasonality flags (population baselines from S3 config)    │
│    ├─ Autocorrelation warnings (HRV/sleep/recovery < 5 pts)     │
│    ├─ Statistical guardrails (<7d observational, <14d prelim)    │
│    ├─ Prediction evaluation (Bayesian Beta distribution)         │
│    └─ Narrative arc transition detection                         │
│    Writes → COACH#computation | RESULTS#{date}                   │
│                                                                  │
│  Step 2: NARRATIVE ORCHESTRATOR (Haiku "showrunner")             │
│    coach-narrative-orchestrator Lambda                            │
│    ├─ Reads: all COMPRESSED#latest + ENSEMBLE#digest +           │
│    │         computation results + NARRATIVE#arc +                │
│    │         open threads + active predictions                   │
│    └─ Produces: per-coach generation brief                       │
│    Writes → COACH#{id} | BRIEF#{date}                            │
│                                                                  │
│  Step 3: COACH GENERATION (Sonnet, per coach)                    │
│    Each coach generates output using:                            │
│    ├─ S3 voice spec (structural rules, decision style, examples) │
│    ├─ Generation brief from orchestrator                         │
│    ├─ Domain-specific data from DynamoDB                         │
│    ├─ Own compressed history (COMPRESSED#latest)                 │
│    └─ Active threads and predictions                             │
│                                                                  │
│  Step 4: STATE UPDATER (Haiku, async post-generation)            │
│    coach-state-updater Lambda                                    │
│    ├─ Extracts: themes, structural fingerprint, threads          │
│    ├─ Creates: formal PREDICTION# records                        │
│    ├─ Writes: OUTPUT# with observatory_summary                   │
│    ├─ Updates: VOICE#state                                       │
│    └─ Writes: TRACE#{date}#{type} reasoning traces               │
│                                                                  │
│  Step 5: ENSEMBLE DIGEST (Haiku, async)                          │
│    coach-ensemble-digest Lambda                                  │
│    ├─ Reads all coach outputs for the cycle                      │
│    ├─ Identifies disagreements between coaches                   │
│    ├─ Flags unanimous agreement (S-10 threshold)                 │
│    └─ Writes: ENSEMBLE#digest | CYCLE#{date}                     │
│                                                                  │
│  Daily: PREDICTION EVALUATOR (deterministic, no LLM)             │
│    coach-prediction-evaluator Lambda                             │
│    ├─ Evaluates: machine/directional/conditional predictions     │
│    ├─ Null hypothesis comparison                                 │
│    ├─ Bayesian confidence updates (Beta distribution)            │
│    └─ Learning log entries                                       │
│                                                                  │
│  Weekly: HISTORY SUMMARIZER (Haiku)                              │
│    coach-history-summarizer Lambda                               │
│    ├─ Compresses each coach's full history                       │
│    └─ Writes: 500-token COMPRESSED#latest per coach              │
│                                                                  │
│  Advisory: QUALITY GATE (Haiku)                                  │
│    coach-quality-gate Lambda                                     │
│    ├─ Anti-pattern detection                                     │
│    ├─ Decision class compliance check                            │
│    ├─ Voice distinctiveness scoring                              │
│    └─ Cross-coach similarity detection                           │
│                                                                  │
│  Renderer: OBSERVATORY RENDERER (no LLM)                         │
│    coach-observatory-renderer Lambda                             │
│    ├─ Reads COACH# state from DynamoDB                           │
│    └─ Assembles JSON payloads for observatory page cards          │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  LEGACY PRE-COMPUTE PIPELINE (runs alongside coach system)       │
│                                                                  │
│  9:35 AM  character-sheet-compute                                │
│  9:40 AM  daily-metrics-compute → computed_metrics DDB           │
│  9:42 AM  daily-insight-compute → insight_data (JSON)            │
│                                                                  │
│  SUNDAY 11:30 AM  weekly-correlation-compute                     │
│  SUNDAY 12:00 PM  hypothesis-engine v1.2.0                       │
│                                                                  │
│  These continue to feed the Daily Brief email pipeline.          │
│  The coach system reads their DynamoDB outputs as data sources.  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  OBSERVATORY INTEGRATION                                         │
│                                                                  │
│  /api/coach_analysis?domain={domain}                             │
│    ├─ Reads from COACH# state store via observatory renderer     │
│    ├─ Falls back to /api/ai_analysis (legacy) if no coach data   │
│    └─ Cards show continuity markers:                             │
│         thread_reference, revision_signal, cross_coach_reference │
│                                                                  │
│  data_availability constraints:                                  │
│    observational_only → hides recommendations                    │
│    preliminary → adds confidence qualifier                       │
│    established → full coaching output                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## The Eight Coaches

Each coach has a named persona, a domain specialty, a voice specification stored in S3, and persistent state in DynamoDB. All coaches share the same pipeline infrastructure but produce distinct analytical perspectives.

| Coach ID | Persona | Domain | Specialty |
|----------|---------|--------|-----------|
| `sleep_coach` | Dr. Lisa Park | Sleep | sleep_science |
| `nutrition_coach` | Dr. Marcus Webb | Nutrition | nutrition |
| `training_coach` | Dr. Sarah Chen | Training | exercise_physiology |
| `mind_coach` | Dr. Nathan Reeves | Mind | psychiatry |
| `physical_coach` | Dr. Victor Reyes | Physical | body_composition |
| `glucose_coach` | Dr. Amara Patel | Glucose | metabolic_health |
| `labs_coach` | Dr. James Okafor | Labs | clinical_pathology |
| `explorer_coach` | Dr. Henning Brandt | Explorer | biostatistics |

### Voice Specifications (S3 Config)

Each coach's voice spec at `s3://matthew-life-platform/config/coaches/{coach_id}.json` contains:

- **structural_voice_rules** — sentence structure, hedging patterns, citation style, characteristic phrasings
- **decision_style** — how the coach approaches ambiguous data (conservative vs. exploratory, data-first vs. intuition-augmented)
- **few_shot_examples** — 2-3 exemplar outputs that anchor the voice during generation
- **anti_pattern_detection** — patterns the quality gate watches for (e.g., Dr. Brandt should never make causal claims without statistical backing; Dr. Reeves should never reduce mental health to biomarkers)

### Influence Graph

`s3://matthew-life-platform/config/coaches/influence_graph.json` defines 56 directed weights across all 8 coaches, controlling how much each coach's output influences others. The graph is read by the narrative orchestrator to shape generation briefs. Stored in DynamoDB as `ENSEMBLE#influence_graph | CONFIG#v1`.

---

## Coach Pipeline Lambdas (8)

### 1. coach-computation-engine

**Type:** Deterministic (no LLM)

Runs all statistical computation before any AI generation begins. Separates math from narrative to ensure reproducibility.

**Computations performed:**
- **EWMA trends** — domain-specific exponential decay parameters loaded from `s3://matthew-life-platform/config/computation/ewma_params.json`. Each domain (sleep, training, nutrition, etc.) has its own decay factor calibrated to the biological time constants of that domain.
- **Regression-to-mean detection** — flags metrics where z > 1.5 AND the current trajectory is moving toward the personal mean. Prevents coaches from attributing normal statistical reversion to interventions.
- **Seasonality flags** — compares current values against population-level seasonal baselines from `s3://matthew-life-platform/config/computation/seasonal_adjustments.json`. Prevents false attribution of seasonal patterns to behavioral changes.
- **Autocorrelation warnings** — for HRV, sleep, and recovery metrics with fewer than 5 data points, warns that serial correlation makes trend detection unreliable.
- **Statistical guardrails** — enforces data maturity tiers:
  - < 7 days of data: `observational_only` (no directional claims permitted)
  - < 14 days: `preliminary` (qualified claims only)
  - 14+ days: `established` (full coaching output)
- **Prediction evaluation** — evaluates outstanding predictions using Bayesian Beta distribution for confidence updates.
- **Narrative arc transition detection** — reads arc definitions from `s3://matthew-life-platform/config/narrative/arc_definitions.json` (8 phases) and detects when data patterns suggest a phase transition.

**DynamoDB output:** `COACH#computation | RESULTS#{date}`

### 2. coach-narrative-orchestrator

**Type:** LLM (Haiku) — "showrunner" role

The orchestrator is the creative director of the coaching system. It reads the full state of every coach and produces a generation brief that tells each coach what to focus on, which threads to continue, which to drop, and what narrative arc to follow.

**Inputs:**
- All 8 coaches' `COMPRESSED#latest` state
- Current `ENSEMBLE#digest` (latest cycle)
- Computation results from step 1
- Current `NARRATIVE#arc | STATE#current`
- All open `THREAD#` records across coaches
- All active `PREDICTION#` records

**Output:** One generation brief per coach, written to `COACH#{id} | BRIEF#{date}`. Each brief contains:
- Focus areas for this cycle
- Threads to continue or resolve
- Cross-coach references to make
- Narrative arc context and phase-appropriate tone
- Predictions to revisit or update

### 3. coach-state-updater

**Type:** LLM (Haiku) — post-generation extraction

Runs asynchronously after each coach generates output. Performs structured extraction from the generated text to maintain the state graph.

**Extractions:**
- **Themes** — semantic tags for the current output
- **Structural fingerprint** — statistical signature of the output's structure (used by quality gate for voice drift detection)
- **Threads opened/referenced** — which analytical threads the coach started or continued
- **Predictions made** — extracted and formalized as `PREDICTION#` records with testable criteria

**DynamoDB writes:**
- `COACH#{id} | OUTPUT#` — full output with `observatory_summary` field
- `COACH#{id} | VOICE#state` — updated voice state
- `COACH#{id} | PREDICTION#{id}` — formal prediction records
- `COACH#{id} | THREAD#{id}` — thread state updates
- `COACH#{id} | TRACE#{date}#{type}` — reasoning traces for debugging

### 4. coach-ensemble-digest

**Type:** LLM (Haiku) — cross-coach synthesis

Reads all coach outputs for the current cycle and produces a meta-analysis of the coaching panel.

**Key functions:**
- **Disagreement detection** — identifies where coaches reach different conclusions from the same data (e.g., training coach says increase volume while sleep coach says reduce load). Writes to `ENSEMBLE#disagreements | ACTIVE#{slug}`.
- **Unanimous agreement flagging** — when all relevant coaches agree on a signal (S-10 threshold), flags it as high-confidence consensus.
- **Cross-domain insight synthesis** — identifies patterns that no single coach can see in isolation.

**DynamoDB output:** `ENSEMBLE#digest | CYCLE#{date}`

### 5. coach-prediction-evaluator

**Type:** Deterministic (no LLM) — runs daily

Evaluates all outstanding predictions from all coaches against incoming data.

**Prediction types evaluated:**
- **Machine predictions** — specific numerical forecasts (e.g., "HRV will exceed 45ms within 3 days")
- **Directional predictions** — trend forecasts (e.g., "sleep efficiency will improve this week")
- **Conditional predictions** — if-then forecasts (e.g., "if training load drops below X, recovery will rebound within 48 hours")

**Evaluation method:**
- Bayesian Beta distribution for confidence updates — each prediction outcome updates the coach's domain-specific confidence prior
- Null hypothesis comparison — was the prediction better than a naive baseline (e.g., "tomorrow will be like today")?
- Learning log entries written to `COACH#{id} | LEARNING#` for coaches that consistently over- or under-predict

### 6. coach-history-summarizer

**Type:** LLM (Haiku) — runs weekly

Compresses each coach's full output history into a 500-token state summary. This is the mechanism that gives coaches long-term memory without unbounded context growth.

**Output:** `COACH#{id} | COMPRESSED#latest` — replaces the previous compressed state. The full history remains in `OUTPUT#` records; the compressed state is the working memory that feeds into the orchestrator.

### 7. coach-quality-gate

**Type:** LLM (Haiku) — advisory role

Quality assurance Lambda that checks coach outputs for structural and analytical integrity.

**Checks performed:**
- **Anti-pattern detection** — per-coach anti-patterns defined in voice specs (e.g., making causal claims from correlational data, reducing complex phenomena to single biomarkers)
- **Decision class compliance** — verifies that coaches respect the statistical guardrails from the computation engine (observational_only coaches should not be making recommendations)
- **Voice distinctiveness scoring** — measures how distinct each coach's output is from the others. Flags convergence where coaches start sounding alike.
- **Cross-coach similarity detection** — identifies when multiple coaches are saying the same thing in different words, which wastes the user's attention budget

### 8. coach-observatory-renderer

**Type:** Pure DynamoDB reader (no LLM)

Assembles JSON payloads for the observatory page cards from `COACH#` state in DynamoDB. No AI generation — purely reads and formats existing state for the frontend.

**Output:** JSON payloads consumed by `/api/coach_analysis?domain={domain}` endpoint.

**Card features:**
- `thread_reference` — shows which analytical thread this card continues
- `revision_signal` — indicates when the coach has changed its mind about a previous assessment
- `cross_coach_reference` — shows when the coach is responding to or building on another coach's analysis
- `data_availability` — controls card rendering (observational_only hides recommendation sections)

---

## DynamoDB Schema

All coach data lives in the existing `life-platform` single-table. No new tables or GSIs.

### Coach State Partitions

| PK | SK Pattern | Contents |
|----|-----------|----------|
| `COACH#{coach_id}` | `OUTPUT#` | Latest coach output with observatory_summary |
| `COACH#{coach_id}` | `THREAD#{thread_id}` | Analytical thread state (open/resolved/dormant) |
| `COACH#{coach_id}` | `LEARNING#{entry_id}` | Prediction evaluation learning log entries |
| `COACH#{coach_id}` | `PREDICTION#{prediction_id}` | Formal prediction records with testable criteria |
| `COACH#{coach_id}` | `VOICE#state` | Current voice state (structural fingerprint, theme history) |
| `COACH#{coach_id}` | `RELATIONSHIP#state` | Inter-coach relationship state |
| `COACH#{coach_id}` | `CONFIDENCE#{subdomain}` | Bayesian confidence priors per subdomain |
| `COACH#{coach_id}` | `COMPRESSED#latest` | 500-token compressed history (weekly update) |
| `COACH#{coach_id}` | `BRIEF#{date}` | Generation brief from narrative orchestrator |
| `COACH#{coach_id}` | `TRACE#{date}#{type}` | Reasoning traces for debugging |

### Ensemble and Narrative Partitions

| PK | SK Pattern | Contents |
|----|-----------|----------|
| `ENSEMBLE#digest` | `CYCLE#{date}` | Cross-coach synthesis for a generation cycle |
| `ENSEMBLE#influence_graph` | `CONFIG#v1` | 56 directed weights across 8 coaches |
| `ENSEMBLE#disagreements` | `ACTIVE#{slug}` | Currently unresolved inter-coach disagreements |
| `NARRATIVE#arc` | `STATE#current` | Current narrative arc phase |
| `NARRATIVE#arc` | `HISTORY#{date}` | Narrative arc transition history |
| `COACH#computation` | `RESULTS#{date}` | Deterministic computation results per day |

---

## S3 Configuration

All coach configuration lives in `s3://matthew-life-platform/config/`:

| Path | Contents |
|------|----------|
| `coaches/{coach_id}.json` | Voice spec: structural_voice_rules, decision_style, few_shot_examples, anti_pattern_detection |
| `coaches/influence_graph.json` | 56 directed weights across 8 coaches |
| `computation/ewma_params.json` | Domain-specific EWMA decay parameters |
| `computation/seasonal_adjustments.json` | Population-level seasonal baselines |
| `narrative/arc_definitions.json` | 8 narrative arc phase definitions |

---

## Generation Pipeline Flow

The daily generation pipeline runs in strict sequential order:

```
1. coach-computation-engine          (deterministic math)
              │
              ▼
2. coach-narrative-orchestrator      (Haiku → per-coach briefs)
              │
              ▼
3. Each coach generates output       (Sonnet × 8 coaches)
              │
              ▼
4. coach-state-updater               (Haiku, async post-generation)
   coach-ensemble-digest             (Haiku, async cross-coach)
              │
              ▼
5. coach-prediction-evaluator        (deterministic, runs daily)
   coach-quality-gate                (Haiku, advisory)
   coach-observatory-renderer        (pure reader, assembles cards)
```

**Weekly:** `coach-history-summarizer` compresses each coach's full history into 500-token `COMPRESSED#latest` state.

**Model routing:**
- Computation engine, prediction evaluator, observatory renderer: no LLM (deterministic)
- Narrative orchestrator, state updater, ensemble digest, quality gate, history summarizer: Haiku (structured extraction / classification / compression)
- Coach generation (step 3): Sonnet (coaching output quality)

---

## Statistical Guardrails

> Authored in consultation with the Science Board. These guardrails are enforced by the computation engine and respected by all coaches via the generation brief.

### Data Maturity Tiers

| Days of Data | Classification | Permitted Coaching |
|-------------|---------------|-------------------|
| < 7 days | `observational_only` | Describe what the data shows. No directional claims. No recommendations. |
| 7 - 13 days | `preliminary` | Qualified directional observations. "Early data suggests..." framing required. |
| 14+ days | `established` | Full coaching output with recommendations. |

### Decision Class Ceiling

Coaches operate under a three-level decision class hierarchy that constrains what kind of guidance they can offer:

1. **Observational** — "Your HRV has been X over the past Y days." (always permitted)
2. **Directional** — "This trend suggests Z may happen." (requires `preliminary` or `established`)
3. **Interventional** — "Consider doing W." (requires `established` only)

A coach in `observational_only` mode cannot issue directional or interventional guidance, regardless of how confident the AI is.

### Regression-to-Mean Flagging

When a metric has z > 1.5 AND is currently moving back toward the personal mean, the computation engine flags it as likely regression-to-mean. Coaches are instructed not to attribute this movement to any intervention. This prevents false attribution of normal statistical reversion.

### Autocorrelation Warnings

For serially correlated metrics (HRV, sleep efficiency, recovery score), trend claims with fewer than 5 independent data points are flagged. Health metrics on consecutive days are not independent observations — today's HRV strongly predicts tomorrow's HRV. The effective sample size for trend detection is smaller than the raw day count.

### Seasonality Adjustment

The computation engine compares current metric values against population-level seasonal baselines. A 10% HRV increase in spring may be seasonal rather than behavioral. Coaches receive seasonality flags and are instructed to factor them into their analysis.

### Public Page Constraints

- No numerical confidence scores on public observatory pages
- Correlational language only ("appears to correlate," not "causes")
- N=1 constraint always noted
- Health disclaimer footer on all AI-generated content

---

## Observatory Integration

The observatory (averagejoematt.com) displays coach analysis cards via a new endpoint with legacy fallback:

1. **Primary:** `/api/coach_analysis?domain={domain}` reads from `COACH#` state store via the observatory renderer
2. **Fallback:** `/api/ai_analysis` (legacy V3 prompt-template analysis) when no coach data exists for a domain

### Card Continuity Markers

Coach cards display three continuity signals that show the observatory reader this is not a stateless daily regeneration:

- **thread_reference** — "Continuing the sleep architecture thread from April 3..."
- **revision_signal** — "Revising my earlier assessment on recovery trajectory..."
- **cross_coach_reference** — "Building on Dr. Chen's training load observation..."

### Data Availability Rendering

The `data_availability` field from the computation engine controls card rendering:

- `observational_only` — hides recommendation sections entirely
- `preliminary` — shows recommendations with qualification badge
- `established` — full card rendering

---

## IC Features Status (v6.0.0)

The coach system subsumes several IC features that previously ran as standalone prompt-template logic. Others continue to run independently alongside the coach pipeline.

### Subsumed by Coach System

These features are now handled by the computation engine and/or narrative orchestrator. Their logic is no longer needed as separate prompt-template injections for coach-generated output. They continue to run for the legacy Daily Brief email pipeline.

| Feature | What It Did | Now Handled By |
|---------|-------------|---------------|
| IC-3: Chain-of-thought two-pass | Two-pass analysis→coaching pattern | Orchestrator brief → Sonnet generation (richer: context includes compressed history, threads, predictions, arc) |
| IC-7: Cross-pillar trade-off | Prompt instruction for cross-pillar reasoning | Ensemble digest + orchestrator briefs explicitly coordinate cross-domain |
| IC-23: Attention weighting | Surprise score → prompt budget allocation | Computation engine EWMA trends + orchestrator focus allocation |
| IC-24: Data quality scoring | Per-source confidence flags | Computation engine statistical guardrails (more granular: per-domain maturity tiers) |
| IC-25: Diminishing returns | Effort vs trajectory per pillar | Computation engine trend analysis + regression-to-mean detection |
| v4.8 Anti-repetition | 3-day guidance_given dedup | State updater tracks all threads + compressed history provides full continuity |
| v4.8 Weekly correlation injection | Top 3 FDR pairs into coaching context | Computation engine reads correlations; orchestrator routes to relevant coaches |

### Running Independently (alongside coach system)

| Feature | Status | Why Independent |
|---------|--------|----------------|
| IC-1: platform_memory | Live | General-purpose memory substrate used by many systems beyond coaching |
| IC-2: daily-insight-compute | Live | Feeds Daily Brief email pipeline (separate from coach pipeline) |
| IC-6: Milestone Architecture | Live | Weight milestones surfaced in coaching when approaching thresholds |
| IC-8: Intent vs Execution Gap | Live | Journal analysis writes to platform_memory; read by coaches as data |
| IC-15: Insight Ledger | Live | Universal insight accumulator for all systems |
| IC-16: Progressive Context | Live | Digest-specific context windowing (Weekly, Monthly, Chronicle) |
| IC-17: Red Team / Contrarian | Live | Skeptic persona in Board of Directors calls (separate from coach panel) |
| IC-18: Hypothesis Engine v1.2.0 | Live | Weekly cross-domain hypothesis generation (independent pipeline) |
| IC-19: Decision Journal | Live | Decision tracking and calibration dataset |
| Weekly Correlation Compute | Live | Sunday correlation matrix; results consumed by computation engine |
| W3: AI Output Validator | Live | Validation gate on all AI-output Lambdas |
| IC-29: Deficit Sustainability | Live | MCP tools for deficit early warning (standalone) |
| IC-30: Autonomic Balance | Live | MCP tool for ANS state quadrant mapping (standalone) |

### Data-Gated (not yet live)

| Feature | Data Requirement | Target Date |
|---------|-----------------|-------------|
| IC-4: Failure Pattern Recognition | 6-8 weeks behavioral data | ~May 2026 |
| IC-5: Momentum / Early Warning | 6-8 weeks | ~May 2026 |
| IC-10: Personal Response Curves | Month 4 | ~July 2026 |
| IC-11: Coaching Calibration | Month 3 | ~June 2026 |
| IC-12: Coaching Effectiveness Feedback | Month 5 | ~Aug 2026 |
| IC-20: Titan Embeddings (Bedrock) | Month 3-4 insight corpus | ~July 2026 |
| IC-26: Temporal Pattern Mining | 8+ weeks | ~May 2026 |
| IC-28: Permanent Learnings Distillation | Quarterly | ~June 2026 |
| IC-31: Meal-Level CGM Response Scorer | 90 days CGM + MacroFactor overlap | ~July 2026 |

### Board Summit Planned Features

| Feature | Status | Summary |
|---------|--------|---------|
| IC-27: AI Confidence Scoring (BS-05) | Planned | 3-level confidence badge on every AI insight |
| IC-28: Habit Cascade Detector (BS-06) | Planned | P(fail Y \| failed X within 48h) conditional probability matrix |
| Unified Sleep Record (BS-08) | Planned | Reconcile Whoop + Eight Sleep + Apple Health into canonical sleep record |
| ACWR Training Load Model (BS-09) | Planned | Acute:chronic workload ratio with injury risk alerts |
| Decision Journal Analytics (BS-T2-6) | Planned | Calibration scoring and regret analysis for IC-19 |
| Biomarker Trajectory Engine (BS-T2-2) | Planned | Linear regression with 95% CI for lab biomarkers |

---

## v4.8.0 AI Insight Engine Overhaul (2026-04-01)

> This section documents the pre-coach overhaul that remains active in the Daily Brief email pipeline. The coach system builds on these foundations but replaces the prompt-template approach for observatory-facing output.

### Phase 1: Anti-Repetition via `guidance_given`

Three-layer anti-repetition system:

1. **`daily_insight_compute_lambda.py`** (step 5j): Reads prior 3 days of `guidance_given` from `computed_insights` records. Builds an "AVOID REPEATING" list (up to 8 items) injected into `ai_context_block`.

2. **`daily_brief_lambda.py`**: After TL;DR generation, writes current day's coaching points back to `computed_insights` as `guidance_given`.

3. **`ai_expert_analyzer_lambda.py`**: Reads its own prior analysis for the same expert before generating a new one.

**DynamoDB path:** `SOURCE#computed_insights | DATE#<YYYY-MM-DD>` -> `guidance_given` field (list of strings).

### Phase 2: 6 Unused Data Sources Wired into Coaching

| Data Source | Wired Into | Fields Used |
|-------------|-----------|-------------|
| **Journal enrichment** (16 fields) | Journal coach prompt | Defense patterns, cognitive patterns, growth signals, avoidance flags, social quality, locus of control, stress sources |
| **Character sheet** | Coaching tone adaptation | Conscientiousness, resilience, growth mindset scores |
| **Adaptive mode** | Email tone/verbosity | Flourishing/struggling classification |
| **State of Mind** (Apple Health) | Emotional context priority | Low mood valence triggers nervous-system-reset priority |
| **Supplements** | Nutrition coach prompt | Active supplement list |
| **Weather** | Training prescription | Daylight hours, barometric pressure, temperature |

### Phase 3: Memory -- `what_worked` + Weekly Correlation Injection

**`what_worked` pattern** (step 5k): When weekly grade average >= 85, records current conditions to `MEMORY#what_worked#<date>`. Coaching reads most recent 2 records as "WHAT HAS WORKED" context.

**Weekly correlation injection** (step 5l): Reads most recent `weekly_correlations` record (top 3 significant Pearson r pairs by absolute value). Injected as "WEEKLY CORRELATIONS (statistically significant)" into `ai_context_block`.

### Phase 4: Labs + Genome Personalization Modules

**`lambdas/labs_coaching.py`** — 8 biomarker coaching rules with threshold-based triggers (ferritin, vitamin D, hs-CRP, HbA1c, fasting insulin, ApoB, testosterone, TSH). Generates coaching deltas injected as `labs_coaching_ctx`.

**`lambdas/genome_coaching.py`** — 7 gene mappings (CYP1A2, MTHFR, FTO, BDNF, FADS1/FADS2, VKORC1, MTNR1B) with weekly rotation to prevent repetition. Generates coaching deltas injected as `genome_coaching_ctx`.

---

## Prompt Architecture Standards

All IC-era AI calls and coach generation follow these structural standards:

### 1. Prompt Anatomy (legacy Daily Brief calls)
```
[1]  PERSONA / ROLE
[2]  JOURNEY CONTEXT — week number, stage label, stage-appropriate principles
[3]  DATA QUALITY BLOCK — per-source confidence flags (IC-24)
[4]  SURPRISE SCORES — which metrics are unusual today (IC-23)
[5]  PLATFORM MEMORY — relevant memory records, what_worked
[6]  INSIGHT CONTEXT — recent high-value insights (IC-16)
[7]  ANTI-REPETITION — "AVOID REPEATING" list from prior 3 days
[8]  WEEKLY CORRELATIONS — top 3 FDR-significant Pearson pairs
[9]  LABS/GENOME CONTEXT — biomarker coaching deltas + genome SNP guidance
[10] TODAY'S DATA — actual metrics, enriched with journal, character,
     adaptive mode, State of Mind, supplements, weather
[11] INSTRUCTION — output format, cross-pillar trade-offs, correlative
     framing, Red Team challenge, health disclaimer
```

### 2. Coach Generation Prompt Anatomy (new)
```
[1]  VOICE SPEC — structural rules, decision style, few-shot examples
[2]  GENERATION BRIEF — from narrative orchestrator (focus areas, threads,
     arc phase, cross-coach references to make)
[3]  COMPUTATION RESULTS — EWMA trends, guardrail classifications,
     regression-to-mean flags, seasonality adjustments
[4]  COMPRESSED HISTORY — 500-token compressed state (own prior outputs)
[5]  ACTIVE THREADS — open analytical threads to continue or resolve
[6]  ACTIVE PREDICTIONS — outstanding predictions to revisit
[7]  DOMAIN DATA — domain-specific metrics from DynamoDB
[8]  ENSEMBLE CONTEXT — latest digest, active disagreements
```

### 3. Causal Language Standards (AI-2)
All prompts use correlative framing:
- "likely connection" / "appears to correlate" / "may be related to"
- Never "causes" / "directly leads to" / "because of" (when inferred, not measured)

### 4. Health Disclaimer (AI-1)
All AI-generated emails include footer: *"This platform provides personal health data aggregation and AI-generated insights for informational purposes only. Always consult a qualified healthcare provider for medical advice."*

Footer presence validated by W3 `ai_output_validator` before send.

---

## Shared Module: insight_writer.py

Location: `lambdas/insight_writer.py` (in shared Lambda Layer)

Called by all email/digest Lambdas after generation. Writes structured records to `SOURCE#insights`.

```python
from insight_writer import write_insight

write_insight(
    table=table,
    user_id=USER_ID,
    text="Sleep efficiency dropped below 80% for 3 consecutive nights...",
    digest_type="daily_brief",
    pillars=["sleep", "recovery"],
    data_sources=["whoop", "eightsleep"],
    confidence="medium",
    actionable=True,
    semantic_tags=["sleep_efficiency", "hrv", "recovery"]
)
```

---

## Known Statistical Limitations

> Authored in consultation with **Dr. Henning Brandt** (Statistician / Quantitative Methods Lead). Standing question: *"Are the conclusions actually valid?"*
>
> Purpose: every statistical method in this platform rests on assumptions. This section documents those assumptions, the conditions under which each method is valid, and the failure modes a new engineer must understand before modifying thresholds or interpreting outputs.

---

### 1. Exponential Moving Average (EMA) -- Banister TSB Model

**Where used:** `daily_metrics_compute_lambda.py` -> `compute_tsb()`
**Parameters:** ATL (Acute Training Load): tau = 7 days, lambda = exp(-1/7) ~ 0.867. CTL (Chronic Training Load): tau = 42 days, lambda = exp(-1/42) ~ 0.976.

**How to read lambda and tau:** For any EMA with decay factor lambda, the time constant tau = -1/ln(lambda) is the *mean age of the data*. A lambda of 0.85 yields tau ~ 6.2 days. Concretely:

| Parameter | lambda | tau (mean age) | Half-life | 95% of weight within |
|-----------|--------|---------------|-----------|----------------------|
| ATL | ~0.867 | 7 days | 4.85 days | last **21 days** |
| CTL | ~0.976 | 42 days | 29 days | last **126 days** |

**Common misconception:** the ATL "7-day" label describes the *mean age*, not the window. Yesterday's session carries ~13% of today's ATL; a session 21 days ago still contributes ~5%.

**Validity conditions:**
- Load proxy is continuous and homogeneous. The model uses Strava kilojoule output only. Garmin-only runs, strength sessions, and HIIT are absent.
- The 60-day warm-up window is sufficient for ATL (3tau = 21 days) but insufficient for CTL (3tau = 126 days).
- The Banister model assumes linear load accumulation and decay.
- Zero-load rest days are correctly handled; silent ingestion failures are not (they masquerade as rest days).

**Known failure modes:** sparse Strava history, mixed-device dedup removing legitimate load data, non-cardio training invisible to the model.

**Coach system integration:** The computation engine uses domain-specific EWMA parameters from `ewma_params.json` rather than the fixed Banister constants. Each domain has decay factors calibrated to its biological time constants.

---

### 2. Z-Score Anomaly Detection -- Adaptive Threshold

**Where used:** `anomaly_detector_lambda.py` -> `check_anomalies()`
**Method:** For each of 13 metrics, compute a 30-day rolling mean and standard deviation. Flag if z = (x - mu) / sigma exceeds the CV-adaptive threshold.

**Adaptive thresholds:**

| CV (sigma/mu) | Z threshold | One-tailed FP rate (normality assumed) |
|---------------|-------------|----------------------------------------|
| >= 0.30 (high variability) | 2.5 | 0.62% per metric per day |
| 0.15-0.30 (medium) | 2.0 | 2.28% per metric per day |
| < 0.15 (low variability) | 2.0 | 2.28% per metric per day |

> **TB7-21 (2026-03-13):** Floor raised from Z=1.5/1.75 to Z=2.0. At 13 metrics, expected daily FP count reduced from ~0.87 to ~0.30.

**Normality assumption:** Z-scores assume Gaussian distribution. Most health metrics are not normally distributed:
- **HRV**: right-skewed, often lognormal. **Fixed in v2.4.0:** Z-scores computed on log(HRV).
- **Steps**: bounded below at zero; heavy right tail. DoW normalization splits mean and sigma by day type.
- **Weight**: approximately Gaussian over short windows; 1.5 lb minimum-absolute-change filter compensates.
- **Recovery/sleep scores**: bounded 0-100, truncated normals. Moderate distortion near extremes.

**Multiple comparisons:** The **2-source, 2-metric gate** before sending an alert provides a natural intersection filter. Do not remove this gate.

**Minimum baseline days (N = 7):** At N=7, the standard error of sigma-hat is ~29%. Z-scores at N=7-14 are directional signals, not precise probability statements.

---

### 3. Non-Overlapping Window Drift Detection

**Where used:** `daily_insight_compute_lambda.py` -> `_compute_slow_drift()`
**Method:** Compare 14-day recent window mean against 14-day baseline window mean (non-overlapping). Express drift as (recent_mean - baseline_mean) / baseline_SD.

> **TB7-22 (2026-03-13):** Windows equalized from 7d/21d to 14d/14d. Equal windows have the same standard error of the mean.

**Validity conditions:**
- Minimum N = 14 in baseline window (code-enforced)
- Assumes baseline window represents a stable reference state
- SD-based severity tiers (0.5, 1.0, 1.5 SD) are expert-judged, not calibrated to FP rate
- No significance test — purely descriptive

**Weight plateau sub-method:** Linear regression slope over >= 8 weight measurements. Threshold of -0.2 lbs/week is clinically derived.

---

### 4. Three-Day Consecutive Trend Signal

**Where used:** `daily_insight_compute_lambda.py` -> `detect_metric_trends()`
**Method:** Detect 3 consecutive days of monotonic movement.

**Statistical validity:** Ordinal test with no distributional assumption. P(strictly monotone in either direction) = 1/3 ~ 33% under random draws. With 7 metrics and 7-day windows, spurious 3-day runs are expected ~once per week. The signal is a lead indicator, not a confirmed trend.

---

### 5. IC-23 Surprise Scoring

**Where used:** `ai_calls.py` -> `_compute_surprise_scores()`
**Method:** Percentage deviation from 7-day mean, mapped to 0-1 via metric-specific scaling factors.

**This is not a statistical test.** It is a heuristic attention-allocation mechanism. The 7-day SMA baseline is noisier than the anomaly detector's 30-day baseline. Intended use: prompt-length allocation and attention routing only.

---

### 6. Weekly Correlation Compute -- Pearson + BH FDR

**Where used:** `weekly_correlation_compute_lambda.py` -> `compute_correlations()`
**Method:** Pearson r over 90-day rolling window, 23 pairs (20 cross-sectional + 3 lagged). BH FDR correction across all 23 pairs.

**N-gating:**
- `strong` (|r| >= 0.7) requires n >= 50
- `moderate` (|r| >= 0.4) requires n >= 30
- `weak` (|r| >= 0.2) requires n >= 14
- Below threshold: label downgraded one tier

**FDR correction (BH):** Controls expected proportion of false discoveries among significant results. At typical n=60-90, expect 3-7 FDR-significant pairs per week.

**Lagged pairs:** Serial autocorrelation is not explicitly corrected; lagged correlations in autocorrelated series have inflated effective n. Treat as directional signals.

**On-demand correlation note (R14-F08):** `tool_get_cross_source_correlation` is a single-pair test with no multiple-comparison correction. Do not treat on-demand p-values as equivalent to the weekly report's `fdr_significant` flag.

---

### 7. Coach Computation Engine -- EWMA Trends

**Where used:** `coach_computation_engine.py`
**Method:** Domain-specific EWMA with decay parameters from `s3://matthew-life-platform/config/computation/ewma_params.json`. Unlike the fixed Banister model (tau = 7/42), each domain uses decay factors calibrated to biological time constants (e.g., sleep metrics have shorter decay than body composition metrics).

**Regression-to-mean detection:** Flags when z > 1.5 AND the metric is moving toward its personal mean. The threshold of 1.5 SD was chosen to balance sensitivity (catching genuine reversion) against specificity (not flagging every fluctuation). Serial correlation in health metrics means some flagged movements will be genuine trends, not reversion.

**Seasonality adjustment:** Population-level baselines. Individual seasonal patterns may differ from population patterns. The adjustment is directional — it shifts the prior expectation — but does not replace individual assessment.

---

### 8. Prediction Evaluation -- Bayesian Beta Distribution

**Where used:** `coach_prediction_evaluator.py`
**Method:** Each coach-domain pair maintains a Beta(alpha, beta) prior for prediction accuracy. Successful predictions increment alpha; failures increment beta. The posterior mean alpha/(alpha+beta) gives the running accuracy estimate.

**Validity conditions:**
- Assumes predictions are independent Bernoulli trials. In practice, consecutive predictions about the same metric are correlated.
- The prior (Beta(1,1) = uniform) is weakly informative. After 20+ evaluated predictions, the prior's influence is negligible.
- Directional and conditional predictions are evaluated as binary outcomes (correct/incorrect). Partial credit is not modeled.

---

### 9. Validity Precondition Summary

| Method | File | Minimum data for valid output | Key assumption | Known failure mode |
|--------|------|------------------------------|----------------|--------------------|
| EMA / ATL (tau=7) | `daily_metrics_compute_lambda.py` | ~21 days Strava | Linear load accumulation | Non-Strava training invisible |
| EMA / CTL (tau=42) | `daily_metrics_compute_lambda.py` | ~90 days Strava | Same as ATL | CTL underestimated until ~126 days |
| Z-score anomaly | `anomaly_detector_lambda.py` | 7 days (reliable at 30) | Approximate normality | HRV/steps non-Gaussian |
| Non-overlapping drift | `daily_insight_compute_lambda.py` | 14 days baseline | Baseline stationarity | Breaks during protocol changes |
| 3-day trend | `daily_insight_compute_lambda.py` | 3 days (ordinal) | None | High FP under serial correlation |
| Surprise scoring | `ai_calls.py` | 7 days | None (heuristic) | 7-day mean distorted by outliers |
| Weekly Pearson (cross) | `weekly_correlation_compute_lambda.py` | 30 days (n-gated) | Linear relationship | Non-linear invisible; low n inflates r |
| Weekly Pearson (lagged) | `weekly_correlation_compute_lambda.py` | 30 days + 1 day | Same as cross-sectional | Autocorrelation inflates effective n |
| Coach EWMA trends | `coach_computation_engine.py` | Domain-specific | Domain-calibrated decay | Miscalibrated decay parameters |
| Coach stat guardrails | `coach_computation_engine.py` | 7 days minimum | Day count = data quality | Missing days counted as available |
| Prediction evaluation | `coach_prediction_evaluator.py` | 20+ predictions | Independent Bernoulli | Correlated predictions bias estimate |

---

### 10. What a New Engineer Must Not Do

1. **Do not lower Z-score thresholds without recomputing the expected FP rate.** Z=1.0 at 13 metrics produces ~2.6 expected false alerts per day.

2. **Do not interpret TSB as a pure 7-day metric.** Today's TSB reflects 60 days of training history with exponentially decaying weight.

3. **Do not run the drift detector without the N=14 gate.** A drift "signal" at N<14 has SE large enough to make the severity tier meaningless.

4. **Do not add new metrics to the anomaly detector without checking their distribution.** Consider log-transform or percentile-rank for bounded/skewed metrics.

5. **Surprise scores are prompt engineering, not statistics.** Do not persist them as evidence or use them to gate downstream logic.

6. **Do not treat on-demand correlation p-values as equivalent to the weekly report.** Single-pair tests have no multiple-comparison correction.

7. **Do not remove the W3 ai_output_validator gate.** It is the last defence against silent prompt failures propagating into the insight ledger.

8. **Do not bypass the computation engine's statistical guardrails.** If a coach is classified as `observational_only`, do not override this in the prompt or the rendering. The guardrails exist to prevent false confidence from small samples.

9. **Do not modify voice specifications without running the quality gate.** Voice spec changes can cause cross-coach convergence or anti-pattern violations that are not visible from a single coach's output.

10. **Do not remove the orchestrator step.** Without orchestrated briefs, coaches will independently focus on the same obvious signals and produce redundant output. The orchestrator's attention allocation is what makes 8 coaches more valuable than 1 coach repeated 8 times.

---

## What NOT to Build (ADR-016, ADR-017, ADR-025)

These decisions are documented to prevent revisiting:

**Vector store / RAG:** Corpus too small, cost too high ($70-100/month vs $25 budget), `platform_memory` + coach compressed state covers the use case. Revisit Month 4-5.

**Local / small LLM:** Quality delta vs. Claude Haiku/Sonnet is large on health coaching. Only potential use: embedding generation (IC-20, Bedrock Titan) once corpus is large enough.

**Fine-tuning:** Addresses style/format consistency, not reasoning quality. The coach voice specifications + quality gate handle style consistency without fine-tuning.

**composite_scores DDB partition (ADR-025):** Removed from active pipeline (v3.7.25). Dead code deleted v3.7.28. Do not reintroduce.

---

*Last updated: 2026-04-06 (v6.0.0 -- Coach Intelligence Architecture: 8 named coaches, deterministic computation engine, narrative orchestration, ensemble consensus, Bayesian prediction tracking, quality gate, weekly compression, observatory rendering. 8 new Lambdas, 10 new DynamoDB partition patterns, 5 S3 config files. 115 MCP tools, 71 Lambdas.)*
