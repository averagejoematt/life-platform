# Character Leveling System — Statistical & Mathematical Review

**Review Lead:** Dr. Henning Brandt, Biostatistician (Technical Board)
**Date:** 2026-03-30
**Engine Version Reviewed:** `character_engine.py` v1.0.0
**Config Version Reviewed:** `character_sheet.json` v1.0.0
**Status:** REVIEW COMPLETE — 14 findings, 7 critical

---

## Panel Composition

Dr. Henning Brandt convened the following review panel. Each member was selected for domain expertise directly relevant to the mathematical, statistical, or behavioral design challenges of turning multi-source health data into a single leveling system.

| Panelist | Role | Board | Why They're Here |
|----------|------|-------|-----------------|
| **Dr. Henning Brandt** | Review Lead — Statistical Validity | Technical | Cochrane-grade biostatistician. Owns every calculation, weighting decision, and statistical method in the engine. |
| **Dr. Anika Patel** | AI/LLM & Scoring Systems | Technical | Composite scoring is an ML-adjacent problem. Anika reviews whether the scoring functions produce sensible gradients and whether the EMA is the right smoothing choice. |
| **Omar Khalil** | Data Architecture & Completeness | Technical | The engine consumes data from 20+ sources. Omar reviews whether missing data, sparse partitions, and source outages distort scores in ways the math doesn't account for. |
| **Coach Maya Rodriguez** | Behavioral Design & Motivation | Personal | Maya designed the asymmetric leveling rules. She reviews whether the math actually produces the behavioral outcomes she specified (2–4 level-ups/month, no flip-flop, no punishment framing). |
| **Dr. Lena Johansson** | Scientific Defensibility | Product | If a reader asks "why is Sleep 20% and Relationships 7%?" — Lena needs the answer to be grounded in published evidence, not gut feel. |
| **Raj Srinivasan** | Founder Lens — Gaming & Edge Cases | Technical | Raj stress-tests systems. He looks for ways the scoring can be gamed, produce absurd results, or create perverse incentives. |
| **Dr. Lisa Park** | Sleep Science — Cross-Pillar Effects | Personal | Lisa designed the Sleep Drag mechanic. She validates whether the cross-pillar effect magnitudes match the clinical evidence for sleep deprivation's downstream impact. |
| **Dr. Marcus Webb** | Nutrition — Component Weighting | Personal | Marcus owns the Nutrition pillar. He reviews whether the 60/40 behavior-outcome split and body composition curve are mathematically sound. |

---

## 1. Executive Summary

**Overall Assessment: The engine is structurally sound but mathematically incomplete.**

The character leveling system implements a defensible high-level architecture: 7 weighted pillars → component scores → weighted aggregation → EMA smoothing → streak-gated level changes → XP accumulation. The anti-flip-flop design (asymmetric streaks, tier boundary gates) is well-conceived and implements Coach Maya's behavioral specification correctly.

However, this review identifies **14 findings across 5 severity levels** — 7 of which are critical and should be addressed before the system is considered "bulletproof" for public-facing use. The most consequential issues are:

1. **Missing data bias** — the engine doesn't distinguish between "no data available" and "bad performance," producing systematically inflated or deflated scores depending on which sources go offline.
2. **Pillar weight justification** — the current weights (Sleep 20%, Movement 18%, etc.) are defensible but not documented against evidence. A reader who asks "why?" gets no answer.
3. **XP is unbounded and monotonically accumulated** — creating a scenario where someone at Level 80 with massive XP can coast for months without meaningful consequences.
4. **The body composition component (40% of Nutrition)** is a one-directional progress curve that will break when Matthew reaches goal weight.
5. **Cross-pillar effects use additive vs. multiplicative modifiers inconsistently** — the code applies them as `ls * (1 + mod)` when `|mod| < 1` but `ls + mod` otherwise, which creates discontinuities.
6. **The Relationships pillar relies on sparse, subjective data** that produces unstable scores — yet it carries 7% of the overall character level.
7. **Consistency meta-pillar creates a circular dependency** — it scores the variance of the other 6 pillars, but itself contributes to the weighted average those pillars feed into.

None of these are unfixable. Several have straightforward mathematical solutions. The recommendations below are ordered by impact.

---

## 2. Pillar Weight Review

### Current Weights

| Pillar | Weight | Cumulative |
|--------|--------|------------|
| Sleep | 20% | 20% |
| Movement | 18% | 38% |
| Nutrition | 18% | 56% |
| Mind | 15% | 71% |
| Metabolic | 12% | 83% |
| Consistency | 10% | 93% |
| Relationships | 7% | 100% |

### Henning's Assessment

The weights produce a reasonable hierarchy but lack formal justification. Here is the evidence basis I would use to defend or adjust each:

**Sleep (20%) — DEFENSIBLE.** Meta-analyses (Cappuccio et al., 2010; Itani et al., 2017) consistently show sleep duration and quality as independent predictors of all-cause mortality with hazard ratios of 1.12–1.30 for short sleep. The 20% weight is appropriate. If anything, given the cross-pillar effects (Sleep Drag), sleep's *effective* contribution exceeds 20%.

**Movement (18%) — DEFENSIBLE but should note VO2max gap.** Physical activity is the single strongest modifiable predictor of longevity (Mandsager et al., 2018 — elite fitness = 5x mortality reduction vs. low fitness). The 18% weight undersells this slightly, but the cross-pillar Training Boost partially compensates.

**Nutrition (18%) — REQUIRES SCRUTINY.** The 40% body composition sub-weight is the largest single component in the entire system. Dr. Webb's reasoning (60% behavior + 40% outcome) is sound *during weight loss*, but the mathematical curve is a pure linear interpolation that breaks at goal weight. See Finding F-04.

**Mind (15%) — DEFENSIBLE but heterogeneous.** This pillar conflates habit compliance, journaling, emotional valence, stress, and vice control — six quite different constructs. Consider splitting into Discipline (behavioral) and Wellbeing (outcome) in v2.

**Metabolic (12%) — DEFENSIBLE with lab decay caveat.** See Finding F-07.

**Consistency (10%) — CIRCULAR DEPENDENCY ISSUE.** See Finding F-06.

**Relationships (7%) — DATA QUALITY CONCERN.** See Finding F-08.

---

## 3. Findings

### F-01: Missing Data Produces Systematic Bias (CRITICAL)

**Severity:** Critical
**Owner:** Henning + Omar
**Components Affected:** All pillars, `_weighted_pillar_score()`

**Current behavior:** When a component score is `None` (no data), `_weighted_pillar_score()` excludes it from both numerator and denominator — effectively redistributing its weight to the remaining components.

**The problem:** This creates two failure modes:

**Mode A — Inflation.** If the hardest-to-score components go missing (e.g., no CGM data, no lab results, no journal), the pillar score is computed from only the easy/high-scoring components.

**Mode B — Volatility.** When a source comes back online after an outage, the denominator suddenly increases and the score can jump or drop dramatically.

**Recommendation — Implement Confidence-Weighted Scoring:**

```python
def _weighted_pillar_score_v2(component_scores, components_config):
    weighted_sum = 0.0
    total_weight = 0.0
    available_weight = 0.0
    max_possible_weight = 0.0
    details = {}

    for comp_name, score in component_scores.items():
        weight = components_config.get(comp_name, {}).get("weight", 0)
        max_possible_weight += weight
        details[comp_name] = {"score": score, "weight": weight}
        if score is not None and weight > 0:
            weighted_sum += score * weight
            total_weight += weight
            available_weight += weight

    if total_weight == 0:
        return 50.0, details, 0.0  # neutral + zero confidence

    raw_score = weighted_sum / total_weight
    data_coverage = available_weight / max_possible_weight if max_possible_weight > 0 else 0
    confidence = min(1.0, data_coverage / 0.80)
    adjusted_score = raw_score * confidence + 50.0 * (1.0 - confidence)
    
    details["_confidence"] = round(confidence, 3)
    details["_data_coverage"] = round(data_coverage, 3)
    
    return round(_clamp(adjusted_score), 1), details, confidence
```

---

### F-02: XP Accumulation is Unbounded and Non-Decaying (CRITICAL)

**Severity:** Critical
**Owner:** Henning + Maya

**Current behavior:** XP accumulates monotonically. The -1 penalty at <20 raw score is negligible compared to daily +1/+2/+3 gains. After 6 months, XP is in the thousands with no function.

**Recommendation — XP as Level Stability Buffer:**

```
XP_PER_LEVEL = 100
DAILY_XP_DECAY = 2

Per pillar per day:
  xp_earned = xp_band_lookup(raw_score)
  xp_total = max(0, previous_xp + xp_earned - DAILY_XP_DECAY)
  level_xp_buffer = xp_total % XP_PER_LEVEL
  can_level_down = (streak_below >= threshold) AND (level_xp_buffer < 20)
```

This makes XP functional: high XP = earned resilience, low XP = fragile hold on current level.

---

### F-03: EMA Smoothing — Per-Pillar Lambda (HIGH)

**Severity:** High
**Owner:** Henning + Anika

**Current:** λ=0.85 globally (half-life ~4.3 days).

**Recommendation:** Per-pillar EMA lambda in config:

| Pillar | λ | Half-Life | Reasoning |
|--------|---|-----------|-----------|
| Sleep | 0.85 | ~4 days | Sleep debt recovers within a week |
| Movement | 0.90 | ~7 days | Training adaptations over weeks |
| Nutrition | 0.88 | ~5 days | Weekly caloric balance |
| Metabolic | 0.95 | ~14 days | Biomarkers change slowly |
| Mind | 0.85 | ~4 days | Emotional state highly variable |
| Relationships | 0.93 | ~10 days | Social connection is stable |
| Consistency | 0.93 | ~10 days | Measured over longer windows |

---

### F-04: Body Composition Curve Breaks at Goal Weight (CRITICAL)

**Severity:** Critical
**Owner:** Henning + Marcus

**Current:** Linear interpolation `(start - current) / (start - goal) * 100`. No maintenance phase implemented.

**Recommendation — Two-Phase with Sigmoid:**

Loss phase: Sigmoid curve that front-loads credit for early momentum.
Maintenance phase: Score 100 within ±3lb band, linear drop outside.

```python
def _body_comp_score(current_weight, config):
    phase = config.get("baseline", {}).get("weight_phase", "loss")
    if phase == "loss":
        progress = (start - current) / (start - goal)
        score = 100 / (1 + math.exp(-8 * (progress - 0.5)))
    elif phase == "maintenance":
        deviation = abs(current - goal)
        if deviation <= band: return 100.0
        score = 100 - ((deviation - band) / (20 - band)) * 100
    return _clamp(score)
```

Add `weight_phase` and `maintenance_band_lbs` to config.

---

### F-05: Cross-Pillar Effects — Inconsistent Modifier Application (HIGH)

**Severity:** High

**Current code:** `adjusted = ls * (1 + mod) if abs(mod) < 1 else ls + mod` — creates a discontinuity at mod=1.

**Recommendation:** Add explicit `type` field to effect targets:

```json
{ "type": "multiplicative", "value": -0.08 }
```

Convert the Alignment Bonus from additive +2 to multiplicative +3%.

---

### F-06: Consistency Pillar — Circular Dependency (MEDIUM)

**Severity:** Medium

Consistency scores the variance of the other 6 pillars but contributes to the average. At 10% weight (4% effective via the variance component), the mathematical impact is bounded to ±4 points. Acceptable for v1. Document the known circularity.

---

### F-07: Lab Biomarker Decay Function (MEDIUM)

**Severity:** Medium

**Current:** Floor at 0.5 after 90 days (forever).

**Recommendation:** Continue decay to 0.0 at 180 days. Six-month-old labs should not contribute to metabolic health scoring.

---

### F-08: Relationships Pillar — Sparse Data (MEDIUM)

**Severity:** Medium

All 4 components rely on Notion journal entries. No journal = all None = score 40.0 (default). Creates massive day-to-day volatility.

**Recommendation:** Use 14-day rolling window for Relationships scoring (Option B). Add `log_social_interaction` MCP tool on roadmap (Option C).

---

### F-09: Neutral Default 40 Skews Low (LOW)

Change default from 40.0 to 50.0. Combined with F-01's confidence weighting, no-data pillars should score neutral, not sub-par.

---

### F-10: Level-Up ±1 Per Day Cap (LOW)

Allow +2 per streak cycle when delta between target and current level exceeds 10. Prevents 250-day catch-up lag on rapid genuine improvement.

---

### F-11: Streak Decay on Equal Days (LOW)

When target equals current level, hold streaks constant instead of decrementing by 1.

---

### F-12: Vice Control — Linear Should Be Logarithmic (LOW)

Current linear (day 7 = 23 points). Replace with log curve (day 7 = 58 points). Front-loads credit for the hardest early days.

---

### F-13: `_in_range_score()` Buffer at Zero (LOW)

Use `(high - low) * buffer` as universal fallback divisor instead of hardcoded 10.

---

### F-14: Banker's Rounding at Level Boundaries (TRIVIAL)

Replace `round()` with `math.floor()` for level calculations.

---

## 4. Implementation Priority

| Priority | Finding | Effort |
|----------|---------|--------|
| **P0** | F-01 (Missing data bias) | Medium |
| **P0** | F-04 (Body comp curve) | Low |
| **P0** | F-05 (Modifier types) | Low |
| **P1** | F-02 (XP as buffer) | High |
| **P1** | F-03 (Per-pillar EMA) | Low |
| **P1** | F-07 (Lab decay) | Low |
| **P1** | F-12 (Vice log curve) | Low |
| **P2** | F-08 (Relationships window) | Low |
| **P2** | F-09 (Neutral 50) | Low |
| **P2** | F-11 (Streak hold) | Low |
| **P2** | F-10 (Variable step) | Low |
| **P3** | F-06, F-13, F-14 | Trivial |

---

## 5. Panel Sign-Off

All 8 panelists approved. Blockers: F-01 (Omar), F-04 (Marcus). Highest-value upgrades: F-02 (Maya), F-12 (Maya). Documentation requirement: Pillar weight rationale (Lena).

---

*Review conducted 2026-03-30. Next review after P0 implementation.*
*Engine version: 1.0.0 → Target: 1.1.0*
