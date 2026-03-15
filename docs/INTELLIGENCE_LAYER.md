# Life Platform — Intelligence Layer

> Documents the Intelligence Compounding (IC) features: how the platform learns, remembers, and improves over time.
> For the IC roadmap and future phases, see PROJECT_PLAN.md (Tier 7).
> Last updated: 2026-03-15 (v3.7.48)

---

## Overview

The Intelligence Layer transforms the platform from a stateless data observer into a compounding intelligence engine. Rather than running the same analysis fresh each day and generating the same generic insight repeatedly, the IC system:

1. **Persists** insights and patterns to DynamoDB (`platform_memory`, `insights`, `decisions`, `hypotheses`, `weekly_correlations`)
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
│  SUNDAY 11:30 AM  weekly-correlation-compute                 │
│           ├─ 23 Pearson pairs (20 cross-sectional + 3 lagged)│
│           ├─ Benjamini-Hochberg FDR correction (v3.7.37)     │
│           └─ writes SOURCE#weekly_correlations | WEEK#<iso>  │
│                                                              │
│  SUNDAY 12:00 PM  hypothesis-engine v1.2.0                   │
│           ├─ reads weekly_correlations as context            │
│           ├─ cross-domain hypotheses → SOURCE#hypotheses DDB │
│           ├─ validation: fields + domains + numeric criteria  │
│           ├─ dedup against active hypotheses                 │
│           └─ 30-day hard expiry; 3 confirms → permanent      │
└─────────────────────────────────┬────────────────────────────┘
                                  │ reads pre-computed data
┌─────────────────────────────────▼────────────────────────────┐
│  AI CALL LAYER (all email/digest Lambdas)                    │
│                                                              │
│  IC-3: Chain-of-thought two-pass (BoD + TL;DR)               │
│    Pass 1: identify patterns + connections (JSON)            │
│    Pass 2: write coaching output using Pass 1 analysis       │
│                                                              │
│  IC-7: Cross-pillar trade-off reasoning instruction          │
│  IC-23: Attention-weighted prompt budgeting (surprise score) │
│  IC-24: Data quality scoring (flag incomplete sources)       │
│  IC-25: Diminishing returns detection (per-pillar)           │
│  IC-17: Red Team / Contrarian Skeptic pass (anti-confirmation│
│          bias, challenges correlation claims)                │
│                                                              │
│  W3: ai_output_validator wired to all 12 AI-output Lambdas  │
│      (validates shape, required fields, disclaimer presence) │
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
│  → SOURCE#hypotheses — weekly cross-domain hypotheses        │
│  → SOURCE#weekly_correlations — 23-pair FDR-corrected matrix │
└──────────────────────────────────────────────────────────────┘
```

---

## IC Features (as of v3.7.48)

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

**Validator:** `ingestion_validator.py` `computed_insights` schema wired since v3.7.25.

### IC-3: Chain-of-Thought Two-Pass
**Status:** Live (v2.86.0)
**What it does:** Board of Directors + TL;DR AI calls use two-pass reasoning. Pass 1 generates structured JSON identifying patterns and connections. Pass 2 writes coaching output using Pass 1 analysis. ~2× token cost but material quality improvement — model reasons before writing.

**Model routing (TB7-23, confirmed 2026-03-13):** Both Pass 1 (analysis) and Pass 2 (output) use `AI_MODEL` = `claude-sonnet-4-6` via `call_anthropic()` in `ai_calls.py`. There is **no quality asymmetry** between the two passes — both run on Sonnet. The Haiku reference at line 515 of `daily_insight_compute_lambda.py` is the IC-8 intent evaluator, which correctly uses Haiku (classification task, not coaching). IC-3 itself has no Haiku dependency.

### IC-4: Failure Pattern Recognition
**Status:** Data-gated skeleton (not yet live — data gate: `days_available >= 42` in `habit_scores`)
**Lambda:** `failure_pattern_compute_lambda.py` (CDK-wired and EventBridge-scheduled pending activation ~2026-05-01)
**What it does:** Identifies recurring failure patterns in habit execution — specifically, which antecedent conditions (high TSB, poor sleep, high Todoist load, travel) consistently precede multi-day habit streaks breaking. Writes failure pattern summaries to `MEMORY#failure_patterns` in `platform_memory`. Coaching AI uses these patterns to preemptively warn: "Last 3 times load exceeded 80 + sleep efficiency dropped below 78%, habits collapsed for 4+ days."

**Activation checklist:**
1. Verify `days_available >= 42` in `habit_scores` partition
2. Add to `cdk/stacks/compute_stack.py` with EventBridge rule
3. Update `ci/lambda_map.json` (remove `not_deployed` flag)
4. Deploy via CDK + run `post_cdk_reconcile_smoke.sh`

**Key output fields:**
- `antecedent_conditions` — conditions that preceded failure (list of {metric, threshold, direction})
- `failure_type` — e.g. `habit_streak_collapse`, `nutrition_drift`, `sleep_degradation`
- `recurrence_count` — how many times this pattern has been observed
- `recovery_days` — median days to recover after this pattern fires

---

### IC-5: Momentum Warning
**Status:** Data-gated skeleton (not yet live — data gate: `days_available >= 42` in `computed_metrics`)
**Lambda:** `momentum_warning_compute_lambda.py` (CDK-wired and EventBridge-scheduled pending activation ~2026-05-01)
**What it does:** Early-warning system that detects leading indicators of momentum loss — sustained low habit completion + declining pillar scores + rising TSB — before they manifest as a measurable setback. Writes momentum signals to `MEMORY#momentum_warnings`. Coaching AI surfaces these as forward-looking alerts rather than retrospective observations.

**Activation checklist:** Same as IC-4 — pair them in the same CDK deploy to share one activation pass.

**Key output fields:**
- `momentum_signal` — `warning` | `at_risk` | `stable` | `building`
- `leading_indicators` — list of metrics trending unfavorably with direction and days_trending
- `at_risk_pillars` — pillar names with current trajectory
- `suggested_intervention` — highest-leverage action to reverse momentum (e.g. `prioritize_sleep`, `reduce_training_load`)

---

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

### IC-18: Hypothesis Engine v1.2.0
**Status:** Live (v2.89.0 → v1.2.0 validation upgrade v3.7.x)
**Lambda:** `hypothesis-engine` (Sunday 12:00 PM PT — runs 30 min after weekly-correlation-compute to consume fresh correlation data)
**What it does:** Weekly Lambda pulls 14 days of all-pillar data plus the current week's correlation matrix. Prompts Claude to identify non-obvious cross-domain connections the existing 89 tools don't explicitly monitor. Writes hypothesis records to `SOURCE#hypotheses`. Subsequent insight compute + digest prompts told to watch for confirming/refuting evidence.

**Validation rules (v1.2.0):**
- Required fields + domains + numeric criteria must be present
- Dedup check against all active hypotheses before write
- 30-day hard expiry on all hypotheses
- Minimum 7 days sample data required
- 3 confirming checks required before promotion to permanent check
- Weekly correlations read as context to avoid re-hypothesising already-confirmed pairs

Access: `get_active_hypotheses`, `evaluate_hypothesis`, `get_hypotheses`, `update_hypothesis_outcome` MCP tools.

### IC-19: Decision Journal
**Status:** Live (v2.88.0)
**What it does:** Tracks platform-guided decisions and their outcomes. `log_decision` MCP tool or inferred from journal + metrics. Builds trust-calibration dataset. Access via `log_decision`, `get_decisions`, `update_decision_outcome` MCP tools.

### IC-23: Attention-Weighted Prompt Budgeting
**Status:** Live (v2.88.0)
**What it does:** Pre-processing step computes "surprise score" for every metric — deviation from personal rolling baseline. High-surprise metrics get expanded context in AI prompts; low-surprise ones compress to one line or are omitted. `_compute_surprise_scores(data, baselines)` returns metric → surprise_score (0-1). Information theory applied to prompt engineering.

### IC-24: Data Quality Scoring
**Status:** Live (v2.88.0)
**What it does:** `_compute_data_quality(data)` runs before AI calls. Per-source confidence score based on completeness, recency, and consistency. Outputs compact quality block injected into prompts: "⚠️ Nutrition: 800 cal — likely incomplete (7d avg 1,750)". AI treats flagged sources with skepticism.

### IC-25: Diminishing Returns Detector
**Status:** Live (v2.88.0)
**What it does:** Weekly computation of each pillar's score trajectory vs. effort (habit completion rate, active habit count). When high effort + flat trajectory detected, coaching redirects to highest-leverage pillar. "Sleep optimization is mature at 82 — your biggest lever is movement consistency at 45%."

### Weekly Correlation Compute (R8-LT9)
**Status:** Live (v3.7.20)
**Lambda:** `weekly-correlation-compute` (Sunday 11:30 AM PT — runs before hypothesis engine)
**What it does:** Computes 23 Pearson correlation pairs weekly over a 90-day rolling window and writes results to `SOURCE#weekly_correlations | WEEK#<iso_week>`. Results feed directly into hypothesis engine context and are surfaced in `get_schedule_load` coaching notes.

**Correlation pairs (v3.7.25):**
- 20 cross-sectional pairs (sleep vs recovery, HRV vs performance, etc.)
- 3 lagged pairs: `hrv_predicts_next_day_load`, `recovery_predicts_next_day_load`, `load_predicts_next_day_recovery`
- Each pair includes: `correlation_type` (`cross_sectional` vs `lagged_Nd`), `lag_days`, Pearson r

**Statistical rigour (v3.7.37):** Benjamini-Hochberg FDR correction applied. With 23 simultaneous tests at α=0.05, naive thresholding produces ~1.15 expected false positives per run; BH controls the false discovery rate instead. Each pair now carries `p_value`, `p_value_fdr`, `fdr_significant` fields.

**N-gating (v3.7.22):** `interpret_r()` is n-gated — `moderate` requires n≥30, `strong` requires n≥50. Prevents spurious strong-labelled correlations during the first 3 months of data accumulation.

### W3: AI Output Validator
**Status:** Live (v3.7.x)
**What it does:** `ai_output_validator` wired into all 12 AI-output Lambdas. Validates response shape, required field presence, and health disclaimer footer before any AI-generated content is written to DDB or sent via email. Catches silent prompt failures (empty responses, malformed JSON, missing disclaimer) that would otherwise propagate undetected into the insight ledger.

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

Footer presence validated by W3 `ai_output_validator` before send.

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

## Known Statistical Limitations

> Authored in consultation with **Dr. Henning Brandt** (Statistician / Quantitative Methods Lead). Standing question: *"Are the conclusions actually valid?"*
>
> Purpose: every statistical method in this platform rests on assumptions. This section documents those assumptions, the conditions under which each method is valid, and the failure modes a new engineer must understand before modifying thresholds or interpreting outputs.

---

### 1. Exponential Moving Average (EMA) — Banister TSB Model

**Where used:** `daily_metrics_compute_lambda.py` → `compute_tsb()`
**Parameters:** ATL (Acute Training Load): τ = 7 days, λ = exp(−1/7) ≈ 0.867. CTL (Chronic Training Load): τ = 42 days, λ = exp(−1/42) ≈ 0.976.

**How to read λ and τ:** For any EMA with decay factor λ, the time constant τ = −1/ln(λ) is the *mean age of the data* — the average number of days back that a given observation contributes. A λ of 0.85, for instance, yields τ ≈ 6.2 days (−1/ln(0.85)). The ATL used here (λ ≈ 0.867, τ = 7 days) is slightly longer-memory. Concretely:

| Parameter | λ | τ (mean age) | Half-life | 95% of weight within |
|-----------|---|-------------|-----------|----------------------|
| ATL | ≈ 0.867 | 7 days | 4.85 days | last **21 days** |
| CTL | ≈ 0.976 | 42 days | 29 days | last **126 days** |

**Common misconception:** the ATL "7-day" label describes the *mean age*, not the window. Yesterdayʼs session carries ~13% of todayʼs ATL; a session 21 days ago still contributes ~5%. TSB is not a 7-day metric — it reaches back weeks.

**Validity conditions:**
- Load proxy is continuous and homogeneous. The model uses Strava kilojoule output only. Garmin-only runs, strength sessions, and HIIT are absent from the load signal. TSB underestimates total training stress proportionally to how much training is not recorded in Strava.
- The 60-day warm-up window is sufficient for ATL (3τ = 21 days needed for 95% stabilisation) but insufficient for CTL (3τ = 126 days). CTL values computed with fewer than ~90 days of consistent Strava history are systematically underestimated.
- The Banister model assumes load and fatigue accumulate and decay linearly. Non-linear effects (illness recovery, detraining after injury) are not captured.
- Kilojoule values of zero on rest days are meaningful and correctly handled (zero load); however, if Strava ingestion fails silently for a day, a rest day is assumed. Check ingestion freshness before interpreting a TSB spike.

**Known failure modes:** sparse Strava history (early platform days), mixed-device dedup removing legitimate load data, non-cardio training invisible to the model.

---

### 2. Z-Score Anomaly Detection — Adaptive Threshold

**Where used:** `anomaly_detector_lambda.py` → `check_anomalies()`
**Method:** For each of 13 metrics, compute a 30-day rolling mean (μ) and standard deviation (σ). Flag if z = (x − μ)/σ exceeds the CV-adaptive threshold in the anomalous direction.

**Adaptive thresholds:**

| CV (σ/μ) | Z threshold | One-tailed FP rate (normality assumed) |
|----------|-------------|----------------------------------------|
| ≥ 0.30 (high variability) | 2.5 | 0.62% per metric per day |
| 0.15–0.30 (medium) | 2.0 | 2.28% per metric per day |
| < 0.15 (low variability) | 2.0 | 2.28% per metric per day |

> **TB7-21 (2026-03-13):** Floor raised from Z=1.5/1.75 to Z=2.0 (`anomaly_detector_lambda.py` v2.5.0). At 13 metrics with Z=1.5 floor, expected daily FP count under independence was ~0.87 (single-metric) before the 2-source gate. Z=2.0 floor reduces this to ~0.30. Sustained streak tracker is unaffected (reads DDB anomaly history, not single-day Z-scores).

**Normality assumption:** Z-scores are only interpretable as probabilities under a Gaussian distribution. Most health metrics are *not* normally distributed:
- **HRV**: right-skewed and often lognormal. **Fixed in v2.4.0:** Z-scores for HRV are now computed on log(HRV) rather than raw HRV (see `LOG_TRANSFORM_METRICS` in `anomaly_detector_lambda.py`). Display values (ms) remain in original units; only the Z computation moves to log domain. This reduces false high-HRV flags and makes low-HRV detection more precise.
- **Steps**: bounded below at zero; heavy right tail on active days. DoW normalisation correctly splits both mean *and* σ by day type — weekday σ is computed on weekday-only values, weekend σ on weekend-only values. The remaining approximation is that the within-day-type distribution is still assumed Gaussian; the right tail on high-step days means the model is mildly under-sensitive on the high end.
- **Weight**: approximately Gaussian over short windows; the 1.5 lb minimum-absolute-change filter compensates well.
- **Recovery/sleep scores**: bounded 0–100, effectively truncated normals. Moderate distortion near extremes.

**Multiple comparisons:** At 13 metrics and Z=1.5, the expected number of spurious single-metric flags per day under independence and normality is approximately 13 × 0.0668 ≈ 0.87. The **2-source, 2-metric gate** before sending an alert provides a natural intersection filter that substantially reduces the per-day false alert rate. Do not remove this gate.

**Minimum baseline days (N = 7):** The code requires at least 7 historical data points to compute a baseline. At N=7, the standard error of σ̂ is σ/√(2(N−1)) ≈ 0.29σ — nearly 30% uncertainty. Z-scores derived from N=7–14 baselines should be treated as directional signals, not precise probability statements. After 30 days of data the baseline is reliable.

**Sustained streak detection (3+ days):** Valid as a pattern signal but does not correct for autocorrelation. Health metrics are serially correlated — a low HRV day predicts the next day's HRV. Consecutive flags therefore understate the novelty of the streak compared to what the naive flag-count implies.

---

### 3. Non-Overlapping Window Drift Detection

**Where used:** `daily_insight_compute_lambda.py` → `_compute_slow_drift()`
**Method:** Compare recent-window mean (days 1–14 before yesterday) against baseline-window mean (days 15–28 before yesterday). Express drift as (recent_mean − baseline_mean) / baseline_SD. Windows are explicitly non-overlapping by design (Henning gate).

> **TB7-22 (2026-03-13):** Windows equalized from 7d recent/8-28d baseline to 14d recent/15-28d baseline (`daily_insight_compute_lambda.py` v1.4.0). Rationale: asymmetric windows produced a volatile recent mean (N=7) vs stable baseline mean (N=21), inflating apparent drift severity. Equal 14d windows have the same standard error of the mean, making comparisons statistically equivalent.

**Why non-overlapping matters:** Overlapping windows share data points, creating artificial correlation between the two means and inflating the apparent precision of the drift estimate. The 1-day gap between windows (day 7 vs day 8) is the minimum necessary separation.

**Validity conditions:**
- **Minimum N = 14 in the baseline window.** This is enforced by code. At N=14 the standard error of σ̂ is ~19%; at N=21 it falls to ~15%. Both are acceptable for detecting large drifts but insufficient for borderline cases. Drift severity of "mild" (0.5–1.0 SD) at N=14 baseline should not trigger clinical concern.
- **Metric stationarity.** The drift test assumes the baseline window represents a stable reference state. If Matthew recently changed behaviour (started a new protocol, changed diet significantly), the baseline window may itself contain a trend, making the drift signal uninterpretable. In these cases, the N=1 experiment framework is a better analytical tool than the drift detector.
- **SD-based severity tiers are uncalibrated.** The thresholds (0.5, 1.0, 1.5 SD) were chosen by expert judgment, not by calibrating against a false positive rate target. A "significant" (1.0–1.5 SD) slow drift flag corresponds to roughly the 16th percentile of the baseline distribution under normality — meaningful, but not alarming in isolation.
- **No significance test.** The comparison is descriptive: it surfaces the magnitude of change but does not test whether the change exceeds sampling error. Two values are compared without confidence intervals. Treat slow drift flags as hypotheses to investigate, not confirmed findings.

**Weight plateau sub-method:** uses linear regression slope over ≥8 weight measurements (Attia gate). Regression slope is valid under this approach but the threshold of −0.2 lbs/week is clinically derived, not statistically calibrated. It will also fire during intentional diet breaks or refeeds. The mandatory recomposition caveat in the output is the correct response to this ambiguity.

---

### 4. Three-Day Consecutive Trend Signal

**Where used:** `daily_insight_compute_lambda.py` → `detect_metric_trends()`
**Method:** Detect if a metric has moved monotonically in one direction for 3 consecutive days.

**Statistical validity:** This is an ordinal test, not a parametric one. It makes no distributional assumption, which is a strength. The weakness is sensitivity:
- Under a random walk, the probability that any 3-day sequence is strictly monotone (either all up or all down) is 2 × (1/2)² = 50% when conditioned on the direction being consistent. For three distinct draws from a continuous distribution, P(x₁ < x₂ < x₃) = 1/6 ≈ 16.7%; P(strictly monotone in either direction) = 1/3 ≈ 33%.
- With 7 tracked metrics and 7-day windows, spurious 3-day monotone runs are expected roughly once per week under random variation. The signal is a *lead indicator*, not a confirmed trend.
- Serial correlation in health metrics (today predicts tomorrow) increases the probability of spurious streaks beyond the random walk baseline.

**Correct interpretation:** a 3-day declining signal should prompt inspection of the raw data, not immediate action. It is most meaningful when (a) the delta magnitude is large, (b) it aligns with an anomaly detector flag, or (c) an IC-5 early warning is also active.

---

### 5. IC-23 Surprise Scoring

**Where used:** `ai_calls.py` → `_compute_surprise_scores()`
**Method:** Compute percentage deviation of todayʼs metric from its 7-day mean. Map linearly to a 0–1 surprise score using metric-specific scaling factors (e.g. HRV: 40% deviation → surprise 1.0; glucose: 20% deviation → surprise 1.0).

**This is not a statistical test.** It is a heuristic attention-allocation mechanism. The scaling factors were chosen by judgment and are not tied to any distributional model. Specifically:
- The 7-day simple moving average baseline is noisier than the 30-day baseline used by the anomaly detector. A single outlier day in the last 7 days significantly shifts the mean, which can suppress surprise scores for genuinely anomalous events immediately following the outlier.
- Surprise scores do not account for the SD of the metric — a 20% deviation in a highly variable metric (e.g. steps) carries different information than a 20% deviation in a low-variability metric (e.g. resting heart rate). The anomaly detector handles this correctly via CV-adaptive thresholds; the surprise scorer does not.
- **Intended use:** prompt-length allocation and attention routing only. Do not use surprise scores as a proxy for statistical significance.

---

### 6. Weekly Correlation Compute — Pearson + BH FDR

**Where used:** `weekly_correlation_compute_lambda.py` → `compute_correlations()`
**Method:** Pearson r over 90-day rolling window, 23 pairs (20 cross-sectional + 3 lagged). Two-tailed p-value from t-distribution (df = n−2). Benjamini-Hochberg FDR correction applied across all 23 pairs simultaneously (v3.7.37).

**Pearson r validity conditions:**
- Assumes a linear relationship. Non-linear associations (e.g. U-shaped HRV vs training load curve) will produce r ≈ 0 even when a real relationship exists.
- Both variables must have variance. If one metric is near-constant for weeks (e.g. during illness), r is undefined and the pair is excluded.
- Assumes no extreme outliers dominate the correlation. A single anomalous data point can shift Pearson r by ±0.2 at n=30.

**N-gating (prevents spurious strong labels at low n):**
- `strong` (|r| ≥ 0.7) requires n ≥ 50
- `moderate` (|r| ≥ 0.4) requires n ≥ 30
- `weak` (|r| ≥ 0.2) requires n ≥ 14
- Below the threshold, the label is downgraded one tier (e.g. r=0.7 at n=35 → `moderate`, not `strong`)

**FDR correction (BH):** With 23 simultaneous tests, testing at α=0.05 without correction yields ~1.15 expected false discoveries. BH ranks p-values and adjusts the threshold: a pair is `fdr_significant` if its sorted p-value rank k satisfies p(k) ≤ (k/23) × 0.05. This controls the expected proportion of false discoveries among significant results, not the per-test false positive rate. At typical n=60-90 early in the platform's life, expect 3-7 FDR-significant pairs per week.

**Lagged pairs:** Three lagged correlations track temporal precedence:
- `hrv_predicts_next_day_load`: does today's HRV predict tomorrow's training load?
- `recovery_predicts_next_day_load`: does today's Whoop recovery predict tomorrow's effort?
- `load_predicts_next_day_recovery`: does today's training load predict tomorrow's recovery?
- Lag computed by shifting one series by 1 day and matching overlapping dates. Serial autocorrelation is not explicitly corrected — lagged correlations in autocorrelated series have inflated effective n. Treat as directional signals, not precise probability statements.

**On-demand correlation tool note (R14-F08):** `tool_get_cross_source_correlation` is a single-pair test with no multiple-comparison correction. When p < 0.05, the tool adds a `_note` field warning that the weekly report applies BH FDR correction across 23 pairs and is more conservative. Do not treat on-demand p-values as equivalent to the weekly report's `fdr_significant` flag.

---

### 7. Validity Precondition Summary

| Method | File | Minimum data for valid output | Key assumption | Known failure mode |
|--------|------|------------------------------|----------------|--------------------|
| EMA / ATL (τ=7) | `daily_metrics_compute_lambda.py` | ~21 days of Strava history | Linear load accumulation; Strava = complete load signal | Non-Strava training invisible |
| EMA / CTL (τ=42) | `daily_metrics_compute_lambda.py` | ~90 days of Strava history | Same as ATL | CTL underestimated until ~126-day warm-up |
| Z-score anomaly | `anomaly_detector_lambda.py` | 7 days (reliable at 30) | Approximate normality of metric distribution | HRV/steps are non-Gaussian; Z scores are approximate |
| Non-overlapping drift | `daily_insight_compute_lambda.py` | 14 days baseline (hardcoded gate) | Stationarity of baseline window | Breaks during intentional protocol changes |
| 3-day trend | `daily_insight_compute_lambda.py` | 3 days (pure ordinal) | None (distribution-free) | High FP rate under serial correlation |
| Surprise scoring | `ai_calls.py` | 7 days | None (heuristic) | 7-day mean distorted by recent outliers |
| Weekly Pearson (cross-sectional) | `weekly_correlation_compute_lambda.py` | 30 days (n-gated; weak at 14) | Linear relationship; no extreme outliers | Non-linear relationships invisible; low n inflates r |
| Weekly Pearson (lagged) | `weekly_correlation_compute_lambda.py` | 30 days + 1 day lag | Same as cross-sectional | Autocorrelation inflates effective n on lagged pairs |

---

### 8. What a New Engineer Must Not Do

1. **Do not lower Z-score thresholds without recomputing the expected FP rate.** Z=1.0 at 13 metrics produces ~2.6 expected false alerts per day. The 2-source gate will not save you — it shifts the problem to correlated metrics (e.g. HRV and recovery score move together).

2. **Do not interpret TSB as a pure 7-day metric.** Todayʼs TSB reflects 60 days of training history with exponentially decaying weight. A sudden change in TSB after a single hard session is expected.

3. **Do not run the drift detector without the N=14 gate.** The gate is in code; do not bypass it when backfilling or running one-off analyses. A drift "signal" at N<14 has an SE of SD large enough to make the severity tier meaningless.

4. **Do not add new metrics to the anomaly detector without checking their distribution.** If the metric is bounded, multimodal, or heavily right-skewed, consider a log-transform or a percentile-rank approach instead of raw Z-scores.

5. **Surprise scores are prompt engineering, not statistics.** They should not be persisted to DynamoDB as evidence of anomalous events or used to gate any downstream logic.

6. **Do not treat on-demand correlation p-values as equivalent to the weekly report.** The weekly report corrects for 23 simultaneous tests via BH FDR. An on-demand single-pair p=0.04 has not been corrected; the same pair in the weekly report may not be `fdr_significant`.

7. **Do not remove the W3 ai_output_validator gate.** It is the last line of defence against silent prompt failures (empty responses, missing disclaimers) propagating into the insight ledger and downstream coaching.

---

## What NOT to Build (ADR-016, ADR-017, ADR-025)

These decisions are documented to prevent revisiting:

**Vector store / RAG:** Corpus too small (<150 journal entries), cost too high ($70-100/month vs $25 budget), `platform_memory` covers 80% of the use case. Revisit Month 4-5.

**Local / small LLM:** Quality delta vs. Claude Haiku/Sonnet is large on health coaching, behavioral synthesis, and narrative tasks. Only potential use: embedding generation (IC-20, Bedrock Titan) once corpus is large enough.

**Fine-tuning:** Addresses style/format consistency, not reasoning quality. The coaching quality gap is a reasoning + context problem. Fine-tuning on 2-week data would overfit to initial state.

**composite_scores DDB partition (ADR-025):** `write_composite_scores()` removed from active compute pipeline (v3.7.25). The `computed_metrics` partition covers the same use case with less DDB write overhead. Dead code fully deleted v3.7.28. Do not reintroduce.

---

*Last updated: 2026-03-15 (v3.7.48 — IC-4/IC-5 skeleton descriptions added (R14-F02))*
