# Life Platform — Intelligence Layer

> Documents the Intelligence Compounding (IC) features: how the platform learns, remembers, and improves over time.
> For the IC roadmap and future phases, see PROJECT_PLAN.md (Tier 7).
> Last updated: 2026-03-09 (v3.3.9)

---

## Overview

The Intelligence Layer transforms the platform from a stateless data observer into a compounding intelligence engine. Rather than running the same analysis fresh each day and generating the same generic insight repeatedly, the IC system:

1. **Persists** insights and patterns to DynamoDB (`platform_memory`, `insights`, `decisions`, `hypotheses`)
2. **Compounds** — each new analysis reads previous findings as context
3. **Learns** Matthew's specific biology, psychology, and failure patterns over time
4. **Self-improves** — coaching calibration evolves as evidence accumulates

The architecture decision (ADR-016) is explicit: no vector store, no embeddings, no fine-tuning. Pure DynamoDB key-value + structured context injection + prompt engineering.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PRE-COMPUTE PIPELINE (runs before Daily Brief)              │
│                                                              │
│  9:35 AM  character-sheet-compute                            │
│  9:40 AM  daily-metrics-compute → computed_metrics DDB       │
│  9:42 AM  daily-insight-compute → insight_data (JSON)        │
│           ├─ 7-day habit × outcome correlations              │
│           ├─ leading indicator flags                         │
│           ├─ platform_memory pull (relevant records)         │
│           └─ structured JSON handoff to Daily Brief          │
│                                                              │
│  SUNDAY   hypothesis-engine (11 AM PT)                       │
│           └─ cross-domain hypotheses → hypotheses DDB        │
└─────────────────────────────────┬────────────────────────────┘
                                  │ reads pre-computed data
┌─────────────────────────────────▼────────────────────────────┐
│  AI CALL LAYER (all email/digest Lambdas)                    │
│                                                              │
│  IC-3: Chain-of-thought two-pass (BoD + TL;DR)               │
│    Pass 1: identify patterns + causal chains (JSON)          │
│    Pass 2: write coaching output using Pass 1 analysis       │
│                                                              │
│  IC-7: Cross-pillar trade-off reasoning instruction          │
│  IC-23: Attention-weighted prompt budgeting (surprise score) │
│  IC-24: Data quality scoring (flag incomplete sources)       │
│  IC-25: Diminishing returns detection (per-pillar)           │
│  IC-17: Red Team / Contrarian Skeptic pass (anti-confirmation│
│          bias, challenges correlation claims)                │
└─────────────────────────────────┬────────────────────────────┘
                                  │ writes after generation
┌─────────────────────────────────▼────────────────────────────┐
│  MEMORY LAYER                                                │
│                                                              │
│  insight_writer.py (shared module in Lambda Layer)           │
│  → SOURCE#insights — universal write by all email Lambdas    │
│  → SOURCE#platform_memory — failure patterns, milestones,    │
│    intention tracking, what worked, coaching calibration      │
│  → SOURCE#decisions — platform decisions + outcomes          │
│  → SOURCE#hypotheses — weekly generated cross-domain hypotheses│
└──────────────────────────────────────────────────────────────┘
```

---

## Live IC Features (as of v3.3.9)

### IC-1: platform_memory Partition
**Status:** Live (v2.86.0)  
**What it does:** DDB partition `SOURCE#platform_memory`, SK `MEMORY#<category>#<date>`. The compounding substrate — structured memory written by compute Lambdas and digest Lambdas, read back into AI prompts as context. Enables "the last 4 weeks show X pattern" without re-querying raw data.

**Memory categories live:** `milestone_architecture`, `intention_tracking`  
**Memory categories coming:** `failure_patterns` (Month 2), `what_worked` (Month 3), `coaching_calibration` (Month 3), `personal_curves` (Month 4)

### IC-2: Daily Insight Compute Lambda
**Status:** Live (v2.86.0)  
**Lambda:** `daily-insight-compute` (9:42 AM PT)  
**What it does:** Pre-computes structured insight JSON before Daily Brief runs. Pulls 7 days of metrics, computes habit×outcome correlations, flags leading indicators, pulls relevant platform_memory records. Daily Brief receives curated intelligence rather than raw data.

**Key output fields in insight JSON:**
- `habit_outcome_correlations` — which habit completions correlate with better sleep/recovery
- `leading_indicators` — early warning signals (e.g., HRV declining 3 consecutive days)
- `memory_context` — relevant platform_memory records for today's conditions
- `data_quality` — per-source confidence scores (IC-24)
- `surprise_scores` — per-metric deviation from rolling baseline (IC-23)

### IC-3: Chain-of-Thought Two-Pass
**Status:** Live (v2.86.0)  
**What it does:** Board of Directors + TL;DR AI calls use two-pass reasoning. Pass 1 generates structured JSON identifying patterns and causal chains. Pass 2 writes coaching output using Pass 1 analysis. ~2× token cost but material quality improvement — model reasons before writing.

### IC-6: Milestone Architecture
**Status:** Live (v2.86.0)  
**What it does:** 6 weight/health milestones with biological significance for Matthew stored in `platform_memory`. Surfaced in coaching when approaching each threshold. Example: "At 285 lbs: sleep apnea risk drops substantially (genome flag)." Converts abstract goal into biological waypoints.

**Current milestones:** 285 lbs (sleep apnea risk), 270 lbs (walking pace natural improvement), 250 lbs (Zone 2 accessible at real-workout pace), 225 lbs (FFMI crosses athletic range), 200 lbs (visceral fat normalization target), 185 lbs (goal weight).

### IC-7: Cross-Pillar Trade-off Reasoning
**Status:** Live (v2.89.0)  
**What it does:** Explicit instruction added to Board of Directors prompts to reason about trade-offs between pillars rather than analyzing each in isolation. Enables: "Movement is strong but Sleep is degrading — adding training volume at current TSB will compound sleep debt. Optimize sleep first."

### IC-8: Intent vs. Execution Gap
**Status:** Live (v2.90.0)  
**What it does:** Journal analysis pass comparing stated intentions ("going to meal prep Sunday") against next-day metrics. Builds personal intention-completion rate. Writes to `MEMORY#intention_tracking`. Coaching AI told when stated intentions have historically not been followed through.

### IC-15: Insight Ledger
**Status:** Live (v2.87.0)  
**What it does:** Universal write-on-generate — every email/digest Lambda appends a structured insight record to `SOURCE#insights` via `insight_writer.py` (shared Layer module). Accumulates the raw material for downstream IC features. Schema: pillar, data_sources, confidence, actionable flag, semantic tags, digest_type, generated_text hash (dedup).

### IC-16: Progressive Context — All Digests
**Status:** Live (v2.88.0)  
**What it does:** Weekly Digest, Monthly Digest, Chronicle, Nutrition Review, and Weekly Plate all retrieve recent high-value insights before generating. Weekly Digest gets 30-day window; Monthly gets quarterly; Chronicle gets narrative-relevant threads. Each digest reads as if written by someone who has followed Matthew for months. ~500-1,500 extra tokens per call.

### IC-17: Red Team / Contrarian Pass
**Status:** Live (v2.87.0)  
**What it does:** "The Skeptic" persona injected into Board of Directors calls. Explicitly tasked to challenge consensus — question whether correlations are causal, flag misleading data, identify when insights are obvious vs. genuinely novel. Counteracts single-model confirmation bias. Prompt-only change, zero cost.

### IC-18: Hypothesis Engine Lambda
**Status:** Live (v2.89.0)  
**Lambda:** `hypothesis-engine` (Sunday 11 AM PT)  
**What it does:** Weekly Lambda pulls 14 days of all-pillar data. Prompts Claude to identify non-obvious cross-domain correlations the existing 144 tools don't explicitly monitor. Writes hypothesis records to `SOURCE#hypotheses`. Subsequent insight compute + digest prompts told to watch for confirming/refuting evidence.

**Validation rules (v1.1.0):** Fields + domains + numeric criteria required. Dedup check against active hypotheses. 30-day hard expiry. Min 7 days sample. 3 confirming checks required for promotion to permanent check.

Access: `get_active_hypotheses`, `evaluate_hypothesis` MCP tools.

### IC-19: Decision Journal
**Status:** Live (v2.88.0)  
**What it does:** Tracks platform-guided decisions and their outcomes. `log_decision` MCP tool or inferred from journal + metrics. Builds trust-calibration dataset. Access via `log_decision`, `get_decision_journal`, `get_decision_effectiveness` MCP tools.

### IC-23: Attention-Weighted Prompt Budgeting
**Status:** Live (v2.88.0)  
**What it does:** Pre-processing step computes "surprise score" for every metric — deviation from personal rolling baseline. High-surprise metrics get expanded context in AI prompts; low-surprise ones compress to one line or are omitted. `_compute_surprise_scores(data, baselines)` returns metric → surprise_score (0-1). Information theory applied to prompt engineering.

### IC-24: Data Quality Scoring
**Status:** Live (v2.88.0)  
**What it does:** `_compute_data_quality(data)` runs before AI calls. Per-source confidence score based on completeness, recency, and consistency. Outputs compact quality block injected into prompts: "⚠️ Nutrition: 800 cal — likely incomplete (7d avg 1,750)". AI treats flagged sources with skepticism.

### IC-25: Diminishing Returns Detector
**Status:** Live (v2.88.0)  
**What it does:** Weekly computation of each pillar's score trajectory vs. effort (habit completion rate, active habit count). When high effort + flat trajectory detected, coaching redirects to highest-leverage pillar. "Sleep optimization is mature at 82 — your biggest lever is movement consistency at 45%."

---

## Prompt Architecture Standards

All IC-era AI calls follow these structural standards:

### 1. Prompt Anatomy (all calls)
```
[1] PERSONA / ROLE — who is speaking (Board member, Elena Voss, etc.)
[2] JOURNEY CONTEXT — week number, stage label, stage-appropriate principles
[3] DATA QUALITY BLOCK — per-source confidence flags (IC-24)
[4] SURPRISE SCORES — which metrics are unusual today (IC-23)
[5] PLATFORM MEMORY — relevant memory records (IC-1)
[6] INSIGHT CONTEXT — recent high-value insights (IC-16, Progressive Context)
[7] TODAY'S DATA — actual metrics, weighted by surprise score (IC-23)
[8] INSTRUCTION — what to produce, including:
    - Cross-pillar trade-off reasoning (IC-7)
    - Correlative (not causal) framing (AI-2)
    - Red Team challenge (IC-17)
    - Health disclaimer footer (AI-1)
```

### 2. Chain-of-Thought Structure (BoD + TL;DR)
```python
# Pass 1 — analysis (JSON output)
{
  "key_patterns": [...],
  "surprising_findings": [...],
  "likely_connections": [...],      # not "causal chains" — AI-2 compliance
  "red_team_challenge": "...",      # IC-17
  "diminishing_returns_flag": ...,  # IC-25
  "highest_leverage_action": "..."
}

# Pass 2 — coaching output (uses Pass 1 JSON as context)
"Given this analysis: {pass_1_json}\n\nNow write the coaching message..."
```

### 3. Causal Language Standards (AI-2)
All prompts use correlative framing:
- ✅ "likely connection" / "appears to correlate" / "may be related to"
- ❌ "causes" / "directly leads to" / "because of" (when inferred, not measured)

### 4. Health Disclaimer (AI-1)
All AI-generated emails include footer: *"This platform provides personal health data aggregation and AI-generated insights for informational purposes only. Always consult a qualified healthcare provider for medical advice."*

---

## Shared Module: insight_writer.py

Location: `lambdas/insight_writer.py` (in shared Lambda Layer)

Called by all 5 email/digest Lambdas after generation. Writes structured records to `SOURCE#insights`.

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

## Data Maturity Roadmap

IC features are gated by how much data exists. Don't build IC features before their data maturity threshold:

| Feature | Data Requirement | Target Date |
|---------|-----------------|-------------|
| IC-4 Failure Pattern Recognition | 6-8 weeks behavioral data | ~May 2026 |
| IC-5 Momentum / Early Warning | 6-8 weeks | ~May 2026 |
| IC-9 Episodic Memory ("what worked") | Month 3 | ~June 2026 |
| IC-10 Personal Response Curves | Month 4 | ~July 2026 |
| IC-11 Coaching Calibration | Month 3 | ~June 2026 |
| IC-12 Coaching Effectiveness Feedback | Month 5 | ~Aug 2026 |
| IC-20 Titan Embeddings (Bedrock) | Month 3-4 insight corpus | ~July 2026 |
| IC-26 Temporal Pattern Mining | 8+ weeks | ~May 2026 |
| IC-28 Permanent Learnings Distillation | Quarterly | ~June 2026 |
| IC-30 Counterfactual Reasoning | Month 5 (after IC-10) | ~Aug 2026 |

---

## What NOT to Build (ADR-016, ADR-017)

These decisions are documented to prevent revisiting:

**Vector store / RAG:** Corpus too small (<150 journal entries), cost too high ($70-100/month vs $25 budget), `platform_memory` covers 80% of the use case. Revisit Month 4-5.

**Local / small LLM:** Quality delta vs. Claude Haiku/Sonnet is large on health coaching, behavioral synthesis, and narrative tasks. Only potential use: embedding generation (IC-20, Bedrock Titan) once corpus is large enough.

**Fine-tuning:** Addresses style/format consistency, not reasoning quality. The coaching quality gap is a reasoning + context problem. Fine-tuning on 2-week data would overfit to initial state.

---

*Last updated: 2026-03-09 (v3.3.9)*
