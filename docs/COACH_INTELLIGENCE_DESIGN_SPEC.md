# Coach Intelligence Architecture — Design Specification

**Version:** 1.0
**Date:** April 6, 2026
**Status:** Approved — All Boards
**Author:** Product Board, Technical Board, Science Board, ML/Stats Expert Panel

---

## Executive Summary

The Life Platform's intelligence layer is evolving from **intelligence as calculation** (data pipelines surfacing trends for human interpretation) to **intelligence as character** (persistent, evolving AI coaches with memory, voice, narrative arc, and ensemble awareness). This spec defines the architecture for that transition.

The system transforms stateless prompt templates into persistent agents with episodic memory, reflective intelligence, relational memory, and cross-coach communication — creating an interdisciplinary coaching team that deepens over a 12-month experiment.

---

## Table of Contents

1. [Current State & Gap Analysis](#1-current-state--gap-analysis)
2. [Architecture Overview](#2-architecture-overview)
3. [Subsystem 1: Coach State Store](#3-subsystem-1-coach-state-store)
4. [Subsystem 2: Narrative Orchestration Layer](#4-subsystem-2-narrative-orchestration-layer)
5. [Subsystem 3: Voice Engine](#5-subsystem-3-voice-engine)
6. [Subsystem 4: Cross-Coach Ensemble Layer](#6-subsystem-4-cross-coach-ensemble-layer)
7. [Subsystem 5: Deterministic Computation Layer](#7-subsystem-5-deterministic-computation-layer)
8. [Prediction Tracking System](#8-prediction-tracking-system)
9. [Statistical Guardrails](#9-statistical-guardrails)
10. [Generation Pipeline (Before/After)](#10-generation-pipeline-beforeafter)
11. [Context Window Budget](#11-context-window-budget)
12. [DynamoDB Schema](#12-dynamodb-schema)
13. [New Lambda Functions](#13-new-lambda-functions)
14. [Configuration Artifacts](#14-configuration-artifacts)
15. [Science Board Requirements](#15-science-board-requirements)
16. [Cost & Performance Impact](#16-cost--performance-impact)
17. [Rollout Plan](#17-rollout-plan)
18. [Open Questions](#18-open-questions)
19. [Appendices](#19-appendices)

---

## 1. Current State & Gap Analysis

### Current Architecture

```
Data fetch → Persona prompt + recent data snapshot → LLM → Output
```

Coaches are stateless prompt templates. Each generation cycle operates independently with no memory of prior outputs, no awareness of other coaches' perspectives, and no narrative planning.

### Identified Gaps

| Gap | Description | Impact |
|-----|-------------|--------|
| **No episodic memory** | Coaches don't know what they've said before (beyond a shallow recent window) | Repetition, inconsistency, no callbacks |
| **No reflective intelligence** | Coaches can't update their own thinking or acknowledge being wrong | Loss of credibility, no intellectual growth |
| **No narrative orchestration** | No "showrunner" coordinating threads, arcs, or callbacks across coaches and over time | Content feels like weekly templates, not a series |
| **No structural voice differentiation** | Coaches sound different at the word level but identical at the structural level | "What strikes me most is not X" from multiple coaches |
| **No relational memory** | Coaches don't deepen their relationship with the subject over time | Month 9 reads like month 1 |
| **No inter-coach awareness** | Coaches don't reference, build on, or disagree with each other's opinions | Parallel monologues instead of a coaching team |
| **No decision framework** | All recommendations treated equally regardless of evidence strength | Observations presented with same weight as interventions |
| **No prediction accountability** | Coaches make implicit claims with no tracking or evaluation | No calibration, no learning |
| **No statistical rigor in coaching** | Trend detection left to LLM judgment; no autocorrelation, seasonality, or regression-to-mean awareness | False signals, premature conclusions |

---

## 2. Architecture Overview

The system comprises five subsystems layered on top of the existing IC data pipeline:

```
┌─────────────────────────────────────────────────────────────┐
│                   GENERATION PIPELINE                        │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │ Deterministic │    │  Narrative    │    │    Voice     │   │
│  │ Computation   │───▶│ Orchestrator  │───▶│   Engine     │   │
│  │    Layer      │    │ (Showrunner)  │    │              │   │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘   │
│         │                   │                    │            │
│         ▼                   ▼                    ▼            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              LLM Generation (per coach)               │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                             │                                │
│                             ▼                                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           Post-Generation State Update                │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌──────────────┐    ┌──────────────────┐
│ Coach State  │    │ Ensemble State   │
│   Store      │    │ (Cross-Coach)    │
│ (per coach)  │    │                  │
└──────────────┘    └──────────────────┘
```

### Core Architectural Principle

**Computation/LLM separation.** All math, trend detection, prediction evaluation, confidence updates, and statistical analysis happens in deterministic Python code. The LLM receives the *results* of those computations and writes about them in character. The LLM never does math. (Source: Karpathy, Expert Panel)

---

## 3. Subsystem 1: Coach State Store

Persistent, per-coach state in DynamoDB within the existing `life-platform` table.

### State Components

#### 3.1 Output Archive
Every piece of content the coach has generated, with extracted metadata.

```json
{
  "PK": "COACH#dr_johansson",
  "SK": "OUTPUT#2026-04-06#weekly_email",
  "content": "Full text of generated output",
  "themes": ["sleep_debt", "hrv_recovery", "training_load"],
  "structural_fingerprint": {
    "opening_type": "data_lead",
    "paragraph_count": 4,
    "uses_analogy": true,
    "analogy_domain": "systems_biology"
  },
  "predictions_made": ["pred_042"],
  "threads_referenced": ["thread_sleep_debt_concern"],
  "threads_opened": ["thread_hrv_inflection_watch"],
  "decision_classes": ["observational", "directional"],
  "word_count": 387,
  "created_at": "2026-04-06T08:00:00Z"
}
```

#### 3.2 Thread Registry
Open observations, flagged concerns, and unresolved positions.

```json
{
  "PK": "COACH#dr_johansson",
  "SK": "THREAD#2026-04-03#sleep_debt_concern",
  "status": "open",
  "type": "observation",
  "summary": "Sleep debt accumulating despite consistent bedtime. Watching for impact on HRV.",
  "opened_date": "2026-04-03",
  "last_referenced": "2026-04-06",
  "reference_count": 2,
  "related_predictions": ["pred_041"],
  "expected_resolution": "Data-dependent — need 14+ days",
  "tags": ["sleep", "hrv", "recovery"]
}
```

Thread types: `observation` (watching something), `prediction` (testable claim), `concern` (flagged risk), `recommendation_pending` (waiting for data to advise), `callback` (resolved thread available for narrative reference).

#### 3.3 Learning Log
Positions taken, mental model updates, and revised thinking.

```json
{
  "PK": "COACH#dr_johansson",
  "SK": "LEARNING#2026-04-06#revised_hrv_position",
  "type": "position_revision",
  "previous_position": "Expected HRV to recover within 2 weeks of deficit easing",
  "revised_position": "HRV recovery appears slower than expected — may be compounded by training load",
  "evidence": "HRV 7-day avg remained below 50ms despite 5 days of reduced deficit",
  "confidence_before": 0.7,
  "confidence_after": 0.5,
  "subdomain": "sleep_recovery",
  "surfaced_in_output": false
}
```

#### 3.4 Voice State
Structural patterns tracked to prevent repetition and reinforce signature elements.

```json
{
  "PK": "COACH#dr_johansson",
  "SK": "VOICE#state",
  "recent_openings": ["data_lead", "data_lead", "thread_callback", "data_lead", "prediction_reference"],
  "overused_patterns": ["opening_with_data_lead"],
  "signature_patterns_to_reinforce": ["confidence_levels", "systems_biology_analogies"],
  "anti_patterns": ["What strikes me most", "If there's one thing", "The data tells a clear story"],
  "last_updated": "2026-04-06T08:00:00Z"
}
```

#### 3.5 Relationship State
How the coach relates to Matthew specifically, evolving over time.

```json
{
  "PK": "COACH#dr_johansson",
  "SK": "RELATIONSHIP#state",
  "rapport_level": "early",
  "known_responsiveness": {
    "engages_with": ["data-driven insights", "specific actionable steps"],
    "resistant_to": ["vague encouragement", "overly cautious hedging"],
    "motivational_profile": "responds to direct honesty over diplomacy"
  },
  "topics_covered_depth": {
    "sleep_architecture": "deep",
    "hrv_interpretation": "moderate",
    "circadian_rhythm": "surface"
  },
  "inside_references": [],
  "journey_phase": "early_baseline",
  "last_updated": "2026-04-06T08:00:00Z"
}
```

---

## 4. Subsystem 2: Narrative Orchestration Layer

The "showrunner" — an LLM planning step that runs before any coach generates content.

### Inputs

- All coach compressed states
- Ensemble digest (cross-coach opinions and concerns)
- Current data changes across all domains
- Open predictions registry with evaluation status
- Narrative arc position
- Journey phase / periodization state
- Deterministic computation outputs (trends, alerts, seasonal flags)

### Output: Generation Brief (per coach)

```json
{
  "coach_id": "fitness_coach",
  "generation_brief": {
    "open_threads": [
      {"thread_id": "thread_progressive_overload", "status": "active", "data_update": "Squat 1RM improved 5% this week"},
      {"thread_id": "thread_hip_mobility_watch", "status": "monitoring", "data_update": "No change — 3 weeks flat"}
    ],
    "cross_coach_context": [
      {"source_coach": "mind_coach", "signal": "emotional_fatigue_flagged", "confidence": 0.6, "influence_weight": 0.8, "summary": "Mind coach concerned about depressive indicators from journal analysis. Recommends reducing cognitive load. Based on 4 days of journal data — preliminary."},
      {"source_coach": "nutrition_coach", "signal": "deficit_aggressive", "confidence": 0.75, "influence_weight": 0.7, "summary": "Nutrition coach believes current deficit is too aggressive for training goals. Recommends increasing intake by 200kcal on training days."}
    ],
    "predictions_to_address": [
      {"pred_id": "pred_038", "status": "failed", "claim": "Expected bench press plateau to break by April 5", "note": "Plateau persists — coach should own this and revise thinking"}
    ],
    "narrative_beat": "cautious_recalibration",
    "journey_phase": "early_baseline",
    "periodization_note": "Month 1 — building base. Conservative loading appropriate.",
    "voice_guidance": {
      "avoid_openings": ["What strikes me most", "data_lead (overused 3/5 recent)"],
      "suggested_opening": "thread_callback or cross_coach_response",
      "structural_note": "Reference mind coach's concern explicitly — show team awareness"
    },
    "decision_class_ceiling": "directional",
    "evidence_note": "Most metrics have <14 days of data. Use 'preliminary' framing per statistical guardrails.",
    "seasonal_flags": [],
    "computation_outputs": {
      "trends": {"squat_1rm": {"direction": "up", "ewma_slope": 0.03, "confidence": "low_n"}},
      "regression_to_mean_warnings": ["sleep_score recovery after bad week — likely noise, not signal"]
    }
  }
}
```

### Narrative Arc Definitions

The orchestrator maintains awareness of the macro narrative arc:

| Arc Phase | Description | Coaching Tone | Risk Tolerance |
|-----------|-------------|---------------|----------------|
| `early_baseline` | Establishing norms, building data | Observational, curious, low-intervention | Low — watch and learn |
| `building_momentum` | Trends emerging, habits forming | Encouraging, directional | Moderate |
| `plateau` | Progress stalls | Patient, analytical, thread-deepening | Low — avoid overreacting |
| `breakthrough` | Clear improvement on key metrics | Celebratory but grounded | Moderate |
| `setback` | Regression or negative event | Supportive, recalibrating | Low — pull back recommendations |
| `inflection` | Major data shift or life event | High-alert, cross-coach coordination | Variable by domain |
| `deep_adaptation` | Months 6+ — long-term patterns visible | Strategic, periodization-aware | Higher — earned trust |
| `culmination` | Final months — pulling threads together | Reflective, synthesizing the arc | Moderate |

### Periodization Awareness (Science Board Requirement)

The orchestrator tracks journey phase (month 1 vs month 10) and adjusts coaching context accordingly. Early months emphasize observation and baseline building. Middle months emphasize intervention and experimentation. Late months emphasize synthesis and optimization.

---

## 5. Subsystem 3: Voice Engine

### Voice Specification (per coach, stored in S3)

```json
{
  "coach_id": "dr_johansson",
  "display_name": "Dr. Lena Johansson",
  "domain": "sleep_science",

  "structural_voice_rules": {
    "opening_patterns": {
      "preferred": ["lead_with_data", "reference_open_thread", "callback_to_prediction", "cross_coach_response"],
      "forbidden": ["What strikes me most", "If there's one thing", "The data tells a clear story"],
      "rotation_rule": "Never use the same opening type more than 2 consecutive times"
    },
    "sentence_rhythm": "Long analytical sentences punctuated by short declarative conclusions",
    "uncertainty_style": "Explicit confidence levels — 'I'm moderately confident that...' or 'The data is too early to say, but my instinct is...'",
    "analogy_domain": "Systems biology, feedback loops, homeostasis",
    "paragraph_structure": "Data observation → interpretation → implication → recommendation (when warranted)",
    "humor_style": "Dry, understated, rare",
    "relationship_to_others": "Collegial but independent. Will reference other coaches' takes and respectfully disagree when warranted.",
    "signature_moves": [
      "Naming confidence levels explicitly",
      "Distinguishing correlation from causation",
      "Referencing her own prior predictions and whether they held"
    ]
  },

  "decision_style": {
    "default_evidence_threshold": "moderate",
    "comfort_with_bold_claims": "low — prefers hedged directional statements",
    "revision_style": "Transparent — 'I need to update my thinking here because...'"
  },

  "few_shot_examples": [
    "Your HRV data this week tells a more nuanced story than last week's simple decline suggested. The 7-day average has stabilized at 48ms — still below your emerging baseline of 53ms, but the downward trajectory I flagged on March 30 has flattened. I'd put my confidence at moderate that we're seeing the floor rather than continued decline. What I'm watching now is whether the rebound follows the 3-5 day pattern I'd expect from sleep debt recovery, or whether something structural — training load, perhaps — is holding it down. I've read the fitness coach's note on your increased squat volume and I think that's a plausible contributor, though I'd want another week of data before I'd point the finger there.",
    "I owe you a correction. Two weeks ago I predicted your sleep onset latency would normalize once the caffeine cutoff moved to 1pm. It hasn't. Your average onset is still 23 minutes, essentially unchanged. My working model was that caffeine was the primary driver, but at this point I'm less confident in that hypothesis — maybe 40% — and I'm increasingly looking at your evening screen exposure patterns as a co-factor. The nutrition coach's caffeine call may have been directionally right but insufficient as a standalone intervention."
  ],

  "anti_pattern_detection": {
    "phrase_blacklist": ["What strikes me most is not", "The real story here", "Let me be direct"],
    "structural_blacklist": ["Opening with a rhetorical question", "Ending with a generic motivational statement"],
    "staleness_threshold": "Flag if any phrase or structural pattern appears in 3+ of last 5 outputs"
  }
}
```

### Voice Anchoring Against Model Drift

The few-shot examples serve as **voice calibration anchors**. When the underlying model changes (version bumps, provider changes), these examples maintain voice consistency. Recommendation: 3-4 gold-standard paragraphs per coach, reviewed quarterly. (Source: Karpathy, Expert Panel)

---

## 6. Subsystem 4: Cross-Coach Ensemble Layer

### Ensemble State Record

After each generation cycle, a shared ensemble digest is written:

```json
{
  "PK": "ENSEMBLE#digest",
  "SK": "CYCLE#2026-04-06",
  "coach_summaries": [
    {
      "coach_id": "mind_coach",
      "key_concerns": ["Emotional fatigue indicators from journal — moderate confidence"],
      "key_recommendations": ["Reduce cognitive load this week"],
      "predictions_active": ["pred_045: mood score will improve within 5 days if training reduced"],
      "confidence_state": {"emotional_assessment": 0.6, "journal_pattern_recognition": 0.55},
      "wants_team_input_on": ["Whether training reduction alone is sufficient or if nutrition is a factor"]
    },
    {
      "coach_id": "nutrition_coach",
      "key_concerns": ["Caloric deficit may be too aggressive for current training volume"],
      "key_recommendations": ["Increase intake by 200kcal on training days"],
      "predictions_active": ["pred_046: body weight will stabilize within 10 days at new intake"],
      "confidence_state": {"deficit_assessment": 0.75, "protein_adequacy": 0.8},
      "disagrees_with": {"fitness_coach": "Disagrees that current volume is sustainable at this deficit"}
    }
  ],
  "active_disagreements": [
    {
      "topic": "Training volume vs. caloric deficit",
      "coaches": ["nutrition_coach", "fitness_coach"],
      "nutrition_position": "Deficit too aggressive — reduce volume or increase intake",
      "fitness_position": "Volume is appropriate for progressive overload goals — maintain and monitor",
      "status": "unresolved",
      "data_needed_to_resolve": "2 more weeks of body composition + performance data"
    }
  ],
  "created_at": "2026-04-06T08:30:00Z"
}
```

### Cross-Coach Influence Graph

Directed weighted graph defining how much one coach's concerns influence another's generation brief. Weights set from domain knowledge, reviewed quarterly. Not learned from data (insufficient N). (Source: Tao & Jordan, Expert Panel)

```json
{
  "PK": "ENSEMBLE#influence_graph",
  "SK": "CONFIG#v1",
  "weights": {
    "sleep → fitness": 0.9,
    "sleep → nutrition": 0.7,
    "sleep → mind": 0.8,
    "mind → fitness": 0.8,
    "mind → nutrition": 0.6,
    "mind → sleep": 0.5,
    "fitness → sleep": 0.7,
    "fitness → mind": 0.4,
    "fitness → nutrition": 0.6,
    "nutrition → fitness": 0.7,
    "nutrition → sleep": 0.6,
    "nutrition → mind": 0.5
  },
  "notes": "Sleep and mind coaches have highest outbound influence. Set from science board domain expertise. Review quarterly.",
  "last_reviewed": "2026-04-06"
}
```

### Productive Disagreement (Science Board Requirement)

The ensemble layer explicitly supports and surfaces disagreement between coaches. Disagreements are:

- Logged in the ensemble digest with both positions stated
- Surfaced in generation briefs for involved coaches
- Tracked for resolution as data accumulates
- Never smoothed over by the orchestrator — tension is signal, not noise

The system should allow coaches to make bold, domain-biased calls and be challenged by other coaches. A fitness coach who says "push through" while the mind coach says "pull back" creates a meaningful dialogue for the reader. (Source: Huberman, Science Board)

---

## 7. Subsystem 5: Deterministic Computation Layer

**All math and statistical analysis happens here — never in the LLM.** The LLM receives results and writes about them in character. (Source: Karpathy, Expert Panel)

### Components

#### 7.1 Trend Detection (EWMA)

Exponentially weighted moving averages with domain-specific decay parameters:

| Domain | λ (decay) | Rationale |
|--------|-----------|-----------|
| Sleep metrics | 0.85 | Recent nights matter most |
| HRV / recovery | 0.87 | Moderate recency bias |
| Training performance | 0.90 | Adaptations take weeks |
| Nutrition / body comp | 0.95 | Changes are gradual |
| Mood / mental state | 0.80 | High day-to-day variability |

```python
# EWMA computation
def ewma(values: list[float], decay: float) -> float:
    """Exponentially weighted moving average. Most recent value last."""
    weights = [(1 - decay) * (decay ** i) for i in range(len(values) - 1, -1, -1)]
    weight_sum = sum(weights)
    return sum(w * v for w, v in zip(weights, values)) / weight_sum
```

(Source: Tao, Expert Panel)

#### 7.2 Bayesian Coach Confidence

Each coach maintains a per-subdomain confidence score as a Beta distribution, updated on prediction outcomes:

```python
# Bayesian confidence update
from dataclasses import dataclass

@dataclass
class SubdomainConfidence:
    alpha: float = 1.0  # successes + 1 (uninformed prior)
    beta: float = 1.0   # failures + 1
    
    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)
    
    @property
    def sample_size(self) -> int:
        return int(self.alpha + self.beta - 2)  # subtract prior
    
    def update(self, success: bool):
        if success:
            self.alpha += 1
        else:
            self.beta += 1

# Example: After 4 successes, 1 failure
# Beta(5, 2) → mean confidence = 0.71
```

Confidence scores are included in generation briefs: "Your nutrition-to-body-comp prediction accuracy is 71% (5 predictions) — moderate confidence. Frame recommendations accordingly." (Source: Tao, Expert Panel)

#### 7.3 Regression-to-Mean Detection

Before any "improvement" or "decline" is flagged to a coach, check whether the change is more likely regression to the mean than a genuine signal:

```python
def is_likely_regression_to_mean(
    current_value: float,
    prior_value: float,
    baseline_mean: float,
    baseline_std: float
) -> bool:
    """Flag if prior was extreme and current moved toward mean."""
    prior_z = abs(prior_value - baseline_mean) / baseline_std
    moved_toward_mean = abs(current_value - baseline_mean) < abs(prior_value - baseline_mean)
    return prior_z > 1.5 and moved_toward_mean
```

When flagged, the generation brief includes: "Regression-to-mean warning: sleep score improvement likely reflects natural reversion from an unusually bad week, not intervention effect." (Source: Witten, Expert Panel)

#### 7.4 Seasonality Adjustment

For key metrics, provide coaches with deseasonalized views alongside raw data. Until a full year of individual data exists (month 12+), use population-level seasonal adjustments:

```python
# Population-level seasonal adjustments (placeholder — calibrate from literature)
SEASONAL_ADJUSTMENTS = {
    "sleep_duration": {1: -15, 2: -10, 3: -5, 4: 0, 5: 5, 6: 10, 7: 10, 8: 5, 9: 0, 10: -5, 11: -10, 12: -15},
    # minutes relative to annual mean
    "mood_score": {1: -0.3, 2: -0.2, 3: 0.0, 4: 0.1, 5: 0.2, 6: 0.2, 7: 0.1, 8: 0.1, 9: 0.0, 10: -0.1, 11: -0.2, 12: -0.3},
    # points relative to annual mean
}
```

Flag to coaches when an apparent trend may be seasonal: "Note: sleep duration increase aligns with seasonal pattern (longer daylight hours in April). Deseasonalized trend is flat." (Source: Witten, Expert Panel)

#### 7.5 Autocorrelation Awareness

Sequential health measurements are not independent. The computation layer flags when a "trend" is simply autocorrelation:

- 3 consecutive days of decline in a highly autocorrelated metric (e.g., HRV) is **not** a meaningful trend
- Predictions about *inflection points* (changes in direction) are valuable; predictions about *continuation* of existing trends are expected by autocorrelation and should not count as meaningful confirmations

(Source: Jordan, Expert Panel)

---

## 8. Prediction Tracking System

### Formal Prediction Schema

```json
{
  "PK": "COACH#dr_johansson",
  "SK": "PREDICTION#pred_042",
  "prediction_id": "pred_042",
  "coach_id": "dr_johansson",
  "created_date": "2026-04-06",
  "claim_natural": "HRV 7-day average will exceed 55ms within 3 weeks",
  "evaluation": {
    "type": "machine",
    "metric": "hrv_7day_avg",
    "condition": "gt",
    "threshold": 55,
    "evaluation_window_days": 21,
    "null_hypothesis": "HRV continues current EWMA trajectory without intervention — would reach 52ms in 3 weeks",
    "beats_null_if": "Exceeds 55ms (null predicts 52ms)"
  },
  "confidence": 0.7,
  "subdomain": "sleep_recovery",
  "confounders_noted": ["training_load_change", "travel_schedule", "seasonal_daylight"],
  "status": "pending",
  "outcome": null,
  "outcome_date": null,
  "outcome_notes": null,
  "decision_class": "directional",
  "surfaced_to_subject": true
}
```

### Prediction Types

| Type | Evaluation Method | Example |
|------|-------------------|---------|
| **Machine-evaluable** | Metric crosses threshold within window | "HRV will exceed 55ms in 3 weeks" |
| **Qualitative** | LLM evaluation against criteria | "Sleep quality will subjectively improve" |
| **Directional** | Metric moves in predicted direction | "Body fat % will trend downward over 6 weeks" |
| **Conditional** | If X then Y | "If caffeine cutoff moves to 1pm, sleep onset will improve" |

### Domain-Appropriate Evaluation Windows (Science Board Requirement)

| Domain | Minimum Evaluation Window | Rationale |
|--------|---------------------------|-----------|
| Sleep | 7-14 days | High night-to-night variability |
| HRV / Recovery | 14-21 days | Autonomic adaptation is gradual |
| Training performance | 21-42 days | Neuromuscular adaptations take weeks |
| Body composition | 28-56 days | Tissue changes are slow |
| Biomarkers (blood) | 60-90 days | Aligned with blood draw cadence |
| Mood / mental state | 7-14 days | Responsive but noisy |

### Null Hypothesis Requirement (Expert Panel Requirement)

Every prediction must include a null hypothesis — what would we expect to happen without intervention? Predictions that merely match the null (regression to mean, continuation of existing trend) do not count as meaningful confirmations. Only predictions that *beat* the null update the Bayesian confidence score. (Source: Witten, Expert Panel)

### Prediction Evaluation Lambda

Runs on schedule (daily or weekly depending on domain). For machine-evaluable predictions:

1. Check if evaluation window has elapsed
2. Fetch current metric value
3. Evaluate against threshold and condition
4. Compare against null hypothesis
5. Update prediction status (confirmed / refuted / inconclusive / beats_null / matches_null)
6. Update coach's Bayesian confidence for relevant subdomain
7. Add to coach's learning log for generation brief inclusion

---

## 9. Statistical Guardrails

Enforced by the deterministic computation layer and injected into generation briefs. (Sources: Henning/Brandt standard + Jordan + Witten, Expert Panel)

| Rule | Threshold | Implementation |
|------|-----------|----------------|
| **Low-N warning** | <14 days of data | Generation brief flags: "Use 'preliminary' framing" |
| **Very low-N warning** | <7 days of data | Generation brief flags: "Observational only — no directional claims" |
| **Autocorrelation flag** | Trend in highly autocorrelated metric | Brief includes: "Likely autocorrelation, not independent signal" |
| **Regression-to-mean flag** | Extreme → mean movement | Brief includes: "Likely regression to mean — do not claim intervention effect" |
| **Seasonality flag** | Trend aligns with seasonal pattern | Brief includes: "Aligns with seasonal pattern — deseasonalized trend is [X]" |
| **Multiple comparisons awareness** | 8 coaches × dozens of metrics | Orchestrator-level: expect ~1 false signal per cycle by chance alone |
| **N=1 constraint** | Always | Never claim population-level inference. "Unusual for you" only, not "unusual." |
| **Correlational language** | Always | Use "associated with," "coincided with," never "caused," "led to" |

### Decision Type Evidence Thresholds (Expert Panel Requirement)

| Decision Class | Minimum Evidence | Language |
|----------------|-----------------|----------|
| **Observational** | Any data point | "I'm noticing..." / "Something caught my attention..." |
| **Directional** | 14+ days trend OR established pattern | "I'd suggest considering..." / "My recommendation would be..." |
| **Interventional** | 21+ days strong signal AND beats null hypothesis | "I think it's time to change..." / "I'd strongly recommend..." |

Coaches should never exceed the evidence ceiling for their decision class. The orchestrator enforces this via the `decision_class_ceiling` field in the generation brief.

---

## 10. Generation Pipeline (Before/After)

### Before (Current)

```
1. Fetch recent data for coach's domain
2. Load persona prompt (static template)
3. Append recent data snapshot
4. Optionally append last 1-3 outputs for continuity
5. Send to LLM → Generate output
6. Publish
```

### After (Proposed)

```
Phase 1: Deterministic Computation (Python Lambda)
  1. Fetch all current data across domains
  2. Run EWMA trend detection per metric (domain-specific λ)
  3. Run regression-to-mean checks on notable changes
  4. Check seasonality flags
  5. Evaluate pending predictions (machine-evaluable)
  6. Update Bayesian confidence scores
  7. Compile computation results package

Phase 2: Narrative Orchestration (LLM — Haiku-class)
  8. Read all coach compressed states
  9. Read ensemble digest (cross-coach opinions)
  10. Read computation results package
  11. Read narrative arc state + journey phase
  12. Produce generation brief per coach

Phase 3: Coach Generation (LLM — Sonnet-class, per coach)
  13. Load voice specification + few-shot examples
  14. Load generation brief
  15. Load relevant domain data
  16. Generate output

Phase 4: Post-Generation (Python Lambda)
  17. Extract themes, structural fingerprint from output
  18. Identify new threads opened, threads referenced
  19. Identify predictions made (flag for schema creation)
  20. Detect anti-pattern violations
  21. Update coach state store (output archive, thread registry, voice state)
  22. Update ensemble digest for cross-coach consumption
  23. Store reasoning trace metadata

Phase 5: Quality Gate (Optional — LLM — Haiku-class)
  24. Check output against voice spec anti-patterns
  25. Verify decision class doesn't exceed evidence ceiling
  26. Flag if coach sounds too similar to another coach's recent output
```

### Fallback (SRE Requirement)

If the orchestrator (Phase 2) fails, fall back to simplified generation:
- Use most recent generation brief if available (cached)
- If no cached brief, generate with: voice spec + recent data + last 3 outputs (current approach)
- Log degraded generation for review

---

## 11. Context Window Budget

Explicit token allocation for the orchestrator call. (Source: Karpathy, Expert Panel)

| Component | Estimated Tokens | Notes |
|-----------|-----------------|-------|
| System prompt + orchestration instructions | ~2,000 | Static |
| Per-coach compressed state (8 coaches × 500) | ~4,000 | Compression quality is critical path |
| Ensemble digest | ~1,000 | Cross-coach opinions + disagreements |
| Current data snapshot (all domains) | ~2,000 | Structured, not raw |
| Open predictions registry | ~500 | Active predictions only |
| Computation results package | ~800 | Trends, flags, confidence scores |
| Narrative arc state | ~300 | Current phase + recent arc history |
| **Total input** | **~10,600** | Well within context limits |
| **Output (all generation briefs)** | **~3,000-4,000** | One brief per coach |

### Coach Generation Call Budget

| Component | Estimated Tokens |
|-----------|-----------------|
| System prompt + voice spec | ~1,500 |
| Few-shot voice examples (3-4) | ~1,200 |
| Generation brief | ~500 |
| Domain data snapshot | ~1,500 |
| **Total input** | **~4,700** |
| **Output** | **~400-800** |

### Compression Quality Testing

The summarization pipeline that produces 500-token compressed coach states is **critical path**. Test criterion: "Can a coach reading only their compressed state produce output that's consistent with everything they've ever said?" If not, the compression is too lossy. (Source: Karpathy, Expert Panel)

---

## 12. DynamoDB Schema

All records in existing `life-platform` table.

### Partition Key Scheme

| PK | SK Pattern | Description |
|----|------------|-------------|
| `COACH#{coach_id}` | `OUTPUT#{date}#{type}` | Generated content archive |
| `COACH#{coach_id}` | `THREAD#{date}#{slug}` | Open/resolved threads |
| `COACH#{coach_id}` | `LEARNING#{date}#{slug}` | Position revisions, mental model updates |
| `COACH#{coach_id}` | `PREDICTION#{pred_id}` | Formal predictions |
| `COACH#{coach_id}` | `VOICE#state` | Voice pattern tracking |
| `COACH#{coach_id}` | `RELATIONSHIP#state` | Relationship with subject |
| `COACH#{coach_id}` | `CONFIDENCE#{subdomain}` | Bayesian confidence (alpha, beta) |
| `COACH#{coach_id}` | `COMPRESSED#latest` | Most recent compressed state for orchestrator |
| `ENSEMBLE#digest` | `CYCLE#{date}` | Cross-coach digest per generation cycle |
| `ENSEMBLE#influence_graph` | `CONFIG#v{n}` | Influence weights |
| `ENSEMBLE#disagreements` | `ACTIVE#{topic_slug}` | Tracked disagreements |
| `NARRATIVE#arc` | `STATE#current` | Current narrative arc + phase |
| `NARRATIVE#arc` | `HISTORY#{date}` | Arc transitions over time |

### GSI Considerations

- **GSI-1**: `SK` as partition key for querying all predictions across coaches (`PREDICTION#*`)
- Existing GSIs should be evaluated for compatibility

---

## 13. New Lambda Functions

| Lambda | Trigger | Purpose | Estimated Complexity |
|--------|---------|---------|---------------------|
| `coach-narrative-orchestrator` | Pre-generation (invoked by email pipeline) | Reads all state, produces generation briefs | High — core LLM planning |
| `coach-state-updater` | Post-generation (invoked after each coach output) | Extracts themes, threads, predictions; writes to state store | Medium — LLM extraction + DDB writes |
| `coach-ensemble-digest` | Post-cycle (after all coaches generate) | Writes cross-coach summary digest | Medium — LLM summarization |
| `coach-prediction-evaluator` | Scheduled (daily) | Evaluates pending predictions, updates confidence scores | Medium — deterministic + DDB |
| `coach-history-summarizer` | Scheduled (weekly) | Compresses full output history into 500-token state | Medium — LLM summarization, quality-critical |
| `coach-computation-engine` | Pre-orchestrator (invoked by email pipeline) | All deterministic math: EWMA, regression-to-mean, seasonality, autocorrelation | Medium — pure Python, no LLM |

### Modified Lambdas

All existing email/content generation Lambdas receive the generation brief as input, replacing the current simple persona + data approach. The voice specification and few-shot examples are loaded from S3 at generation time.

### Day 6 Seed (Not a Full Backfill)

Since the experiment is only 6 days old, the bootstrap is minimal:
- Seed each coach's output archive with any content generated to date
- Initialize thread registries as empty
- Initialize confidence priors as Beta(1,1) — uninformed
- Set relationship state to `early`
- Set narrative arc to `early_baseline`
- No historical extraction needed — the system starts accumulating forward

---

## 14. Configuration Artifacts

### S3 Locations

| Path | Content |
|------|---------|
| `config/coaches/{coach_id}.json` | Voice specification per coach |
| `config/coaches/influence_graph.json` | Cross-coach influence weights |
| `config/narrative/arc_definitions.json` | Narrative arc phase definitions |
| `config/narrative/periodization.json` | 12-month periodization plan |
| `config/computation/ewma_params.json` | Domain-specific decay parameters |
| `config/computation/seasonal_adjustments.json` | Population-level seasonal baselines |

---

## 15. Science Board Requirements

Consolidated from the Science Board session (Huberman, Attia, Patrick, Galpin, Walker, Lyon, Starrett):

| # | Requirement | Implementation |
|---|-------------|----------------|
| S-1 | Cross-coach communication must carry confidence levels, not just conclusions | Ensemble digest includes per-signal confidence |
| S-2 | Productive disagreement — coaches should respectfully disagree, not smooth over | Ensemble layer tracks and surfaces active disagreements |
| S-3 | Domain-appropriate prediction evaluation windows | Prediction schema enforces minimum windows per domain |
| S-4 | Periodization and journey-phase awareness | Orchestrator includes phase in every brief |
| S-5 | Revision as credibility — coaches should own being wrong | Learning log + prediction failures surfaced in briefs |
| S-6 | Observational patience — "I'm watching this" is a valid coaching stance | Thread type `observation` with no pressure to resolve |
| S-7 | Sleep coach as cross-domain integrator | Highest inbound influence weights from all domains |
| S-8 | Bidirectional influence modeling, not one-way deference | Influence graph is directed with varying weights in both directions |
| S-9 | Increased persuasion requires increased rigor | Decision class evidence thresholds + statistical guardrails |
| S-10 | Ensemble should have built-in disagreement — all coaches agreeing is a red flag | Orchestrator flags unanimous agreement as unusual |

---

## 16. Cost & Performance Impact

### Token Cost Estimate (Per Generation Cycle)

| Component | Calls | Model | Est. Input Tokens | Est. Output Tokens |
|-----------|-------|-------|-------------------|-------------------|
| Computation engine | 1 | None (Python) | — | — |
| Narrative orchestrator | 1 | Haiku | ~10,600 | ~3,500 |
| Coach generation | 8 | Sonnet | ~4,700 each | ~600 each |
| Post-generation extraction | 8 | Haiku | ~1,500 each | ~500 each |
| Ensemble digest | 1 | Haiku | ~5,000 | ~1,000 |
| **Total per cycle** | **19** | | **~69,000 input** | **~12,500 output** |

Estimated cost increase: **~2-2.5x current generation costs**. At current scale, approximately **$3-5/month additional API cost**.

### Latency Impact

- Computation engine: <1s (Python)
- Orchestrator: ~5-10s (Haiku, planning)
- Coach generation: ~10-15s each, parallelizable
- Post-generation: ~3-5s each, parallelizable
- Ensemble digest: ~5s

**Total wall clock (parallel execution):** ~30-40s per cycle, up from ~15-20s currently.

### DynamoDB Cost

Negligible. Kilobytes per coach per week. Well within existing provisioned capacity.

---

## 17. Rollout Plan

### Phase 1: Foundation (Session 1-2)
- Create DynamoDB schema additions
- Build `coach-computation-engine` Lambda (deterministic math)
- Build voice specifications for all coaches (S3 configs)
- Seed initial state (day 6 outputs + empty registries)

### Phase 2: Single Coach Proof of Concept (Session 2-3)
- Pick one coach (recommendation: sleep coach — highest cross-domain influence)
- Build `coach-narrative-orchestrator` for single coach
- Build `coach-state-updater` for single coach
- Wire into existing email generation pipeline
- Run A/B comparison: new system vs. current template

### Phase 3: Ensemble Layer (Session 3-4)
- Build `coach-ensemble-digest`
- Build cross-coach influence graph config
- Extend orchestrator to read ensemble state
- Wire second and third coaches into new system
- Test cross-coach references and disagreement

### Phase 4: Prediction & Intelligence (Session 4-5)
- Build `coach-prediction-evaluator`
- Implement Bayesian confidence tracking
- Wire prediction schema into post-generation extraction
- Enable null hypothesis checks

### Phase 5: Full Rollout (Session 5-6)
- Migrate remaining coaches to new system
- Build `coach-history-summarizer` (weekly compression)
- Activate narrative arc tracking
- Build fallback pipeline for SRE resilience
- Full quality gate activation

### Phase 6: Refinement (Ongoing)
- Tune compression quality (critical path testing)
- Refine voice specifications based on output quality
- Quarterly influence graph review
- Quarterly voice calibration example refresh

**Estimated total: 4-6 focused sessions** for core system, then incremental.

---

## 18. Open Questions

| # | Question | Owner | Notes |
|---|----------|-------|-------|
| OQ-1 | Should the orchestrator be a single LLM call producing all briefs, or one call per coach? | Technical Board | Single call is cheaper; per-coach allows more focused context |
| OQ-2 | How do we surface reasoning traces to Matthew? Metadata sidebar? On-demand MCP query? | Product Board | Rudin (Expert Panel) recommends stored + optionally surfaceable |
| OQ-3 | Should coaches reference each other by name in prose, or indirectly? | Content / Product | "The sleep team" vs. "Dr. Walker" — affects immersion |
| OQ-4 | How does this interact with MCP-based coaching queries? | Technical Board | MCP queries should read the same coach state for consistency |
| OQ-5 | Do we need a "showrunner" persona that occasionally speaks directly? | Product Board | Could provide meta-commentary on the coaching ensemble |
| OQ-6 | Prompt evolution — should the system prompt itself change over months? | AI/LLM | Relationship state changes could modify prompt structure |
| OQ-7 | What triggers a narrative arc transition? | Orchestrator design | Data-driven? Time-driven? Manually flagged? |

---

## 19. Appendices

### Appendix A: Board Approvals

| Board | Date | Vote | Conditions |
|-------|------|------|------------|
| Product Board | 2026-04-06 | Approved | Recommended single-coach proof of concept first |
| Technical Board | 2026-04-06 | Unanimous (8-0) | Fallback pipeline required (Jin/SRE) |
| Science Board | 2026-04-06 | Approved | Statistical rigor must scale with coaching sophistication |
| Expert Panel | 2026-04-06 | Approved | Computation/LLM separation is non-negotiable |

### Appendix B: Expert Panel Participants

| Expert | Domain | Key Contribution |
|--------|--------|------------------|
| Dr. Andrej Karpathy | AI/Neural Nets | Context budget, voice anchoring, computation/LLM separation |
| Dr. Cassie Kozyrkov | Decision Science | Decision type taxonomy, counterfactual prompting |
| Dr. Chris Re | ML Systems | Formal prediction schema, confounders |
| Dr. Cynthia Rudin | Interpretable ML | Reasoning traces, transparency |
| Dr. Terence Tao | Mathematics | Bayesian confidence, EWMA, influence graph |
| Dr. Michael Jordan | Statistics/ML | N=1 constraints, autocorrelation, multiple comparisons |
| Dr. Daniela Witten | Biostatistics | Seasonality, regression to mean, null hypothesis |

### Appendix C: Related Platform Documents

- `docs/INTELLIGENCE_LAYER.md` — Current IC feature documentation
- `docs/ARCHITECTURE.md` — Platform architecture
- `docs/BOARDS.md` — Board frameworks and personas
- `s3://matthew-life-platform/config/board_of_directors.json` — Board member configurations
