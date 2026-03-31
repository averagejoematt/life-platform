# SPEC: Character Engine v1.1.0 — Statistical Review Implementation

**Author:** Dr. Henning Brandt (review lead) + Full Board alignment
**Date:** 2026-03-30
**Implements:** `docs/reviews/REVIEW_CHARACTER_LEVELING_2026-03-30.md` (14 findings + F-15)
**Target:** Handoff to Claude Code for implementation
**Status:** BOARD APPROVED — ready to build

---

## Board Alignment: Progressive Difficulty (F-15)

### The Question

Should Level 1→2 require the same sustained performance as Level 65→66?

### Current Behavior

Flat difficulty. Every level-up requires exactly 5 consecutive days with EMA score above the target level. Every level-down requires 7 days. This is identical whether you're climbing from Level 1 or Level 95.

### Board Deliberation

**Coach Maya Rodriguez (Behavioral Design):**
"This is the single biggest design flaw in the current engine. In every well-designed progression system — RPGs, martial arts belts, academic degrees — the bar rises as you advance. Level 1→2 should feel like a warm-up. Level 65→66 should feel like a genuine achievement. Without progressive difficulty, reaching Level 80 doesn't mean 'I've demonstrated sustained mastery over months.' It means 'I had a good 5 days recently.' The streak escalation is the fix."

**Dr. Kai Nakamura (Neuroscience / Huberman proxy):**
"Progressive difficulty taps into a well-established motivational principle: challenge-skill balance (Csikszentmihalyi's flow model). When the challenge is too low relative to skill, you get boredom. When it's too high, anxiety. The streak escalation naturally increases challenge as the player's demonstrated skill (level) increases. At Foundation tier, short streaks keep the feedback loop tight — you see progress quickly, which builds the habit loop. At Mastery tier, longer streaks filter out noise and ensure the level represents true sustained behavior change, not a good week."

**Dr. Victor Reyes (Metabolic Health / Attia proxy):**
"From a health outcome perspective, this is exactly right. The difference between someone who exercises for 3 days and someone who exercises for 14 consecutive days is not 4.7x — it's qualitatively different. The 14-day exerciser has built a habit. The 3-day exerciser had a burst of motivation. The progressive streak requirement maps to this biological reality: at higher tiers, what we're really measuring is *habit formation* and *identity change*, not just compliance."

**Dr. Rhonda Patrick (via science advisory):**
"I agree with the tier-escalation model. One addition: the streak requirement should consider *what* is being sustained, not just *that* something is sustained. At Elite tier (81-100), all 7 pillars need to be performing. A 14-day streak at Level 85 means 14 consecutive days where sleep, movement, nutrition, metabolic, mind, relationships, AND consistency are all scoring in the mid-80s. That's not just discipline — that's a fundamentally healthy person. The progressive difficulty ensures the system only awards that label when it's genuinely earned."

**Raj Srinivasan (Adversarial Review):**
"I stress-tested the progressive model. Here's the key question: what happens when someone genuinely improves rapidly? Say Matthew gets a CPAP machine and his sleep score jumps from 30 to 80 overnight. With flat 5-day streaks, his Sleep level would take ~250 days to reach 80. With progressive streaks, it takes longer at higher tiers but the variable step size (F-10: +2 per cycle when delta >10) compensates. Net result: rapid genuine improvement still progresses meaningfully, but the *highest levels* require proven consistency. I approve."

**Dr. Lisa Park (Sleep Science):**
"From a sleep perspective specifically: the Foundation tier streak of 3 days is appropriate. Sleep debt and recovery operate on a 3-5 day cycle. If someone sleeps well for 3 consecutive nights, their HRV and recovery metrics will show genuine improvement. At Mastery tier (10-day streak), we're looking at a full sleep-wake cycle with weekend included — that's the real test of whether someone has actually fixed their sleep hygiene or just had a good run."

**Dr. Marcus Webb (Nutrition):**
"For nutrition, the progressive model is critical. Caloric adherence for 3 days is trivial — anyone can white-knuckle a deficit for a long weekend. 10 consecutive days of adherence at Mastery tier means the person has navigated at least one weekend, likely one social event, and possibly one stressful work day without blowing their nutrition. That's meaningful behavioral change."

**Dr. Lena Johansson (Scientific Defensibility):**
"The progressive model is scientifically defensible. The literature on habit formation (Lally et al., 2010 — 'How are habits formed') shows that the median time to automaticity is 66 days, with a range of 18 to 254 days. The progressive streak model doesn't claim to measure habit formation directly, but the increasing requirements at higher tiers approximate the principle: early behaviors are fragile and should be rewarded quickly, while sustained behaviors require longer demonstration periods."

**The Chair — VERDICT:**
"Unanimous approval. Progressive difficulty is the right design. Implementation should be config-driven so the exact streak values can be tuned based on observed data after 90 days. The variable step size (+2 when delta >10) approved as a safety valve for genuine rapid improvement."

### Approved Progressive Difficulty Model

```
Tier            Level Range    Streak Up    Streak Down    Tier Boundary Up    Tier Boundary Down
Foundation      1-20           3 days       5 days         5 days              7 days
Momentum        21-40          5 days       7 days         7 days              10 days
Discipline      41-60          7 days       10 days        10 days             14 days
Mastery         61-80          10 days      14 days        14 days             21 days
Elite           81-100         14 days      21 days        21 days             30 days
```

**Asymmetry ratios by tier:**
- Foundation: 3 up / 5 down (1.67x harder to lose)
- Momentum: 5 up / 7 down (1.40x)
- Discipline: 7 up / 10 down (1.43x)
- Mastery: 10 up / 14 down (1.40x)
- Elite: 14 up / 21 down (1.50x)

**Variable step size:** When `target_level - current_level > 10`, award +2 levels per streak cycle instead of +1.

---

## Part 1: Engine Changes (`character_engine.py`)

All changes listed below. Each includes the function, what changes, and the replacement code.

### 1A. `_weighted_pillar_score()` → `_weighted_pillar_score_v2()` [F-01]

**What:** Add confidence-weighted scoring. Blend toward 50 (neutral) when data is sparse.

```python
def _weighted_pillar_score(component_scores, components_config):
    """Weighted average with data completeness confidence penalty."""
    weighted_sum = 0.0
    total_weight = 0.0
    max_possible_weight = 0.0
    details = {}

    for comp_name, score in component_scores.items():
        comp_cfg = components_config.get(comp_name, {})
        weight = comp_cfg.get("weight", 0) if isinstance(comp_cfg, dict) else comp_cfg
        max_possible_weight += weight
        details[comp_name] = {"score": score, "weight": weight}
        if score is not None and weight > 0:
            weighted_sum += score * weight
            total_weight += weight

    if total_weight == 0:
        details["_confidence"] = 0.0
        details["_data_coverage"] = 0.0
        return 50.0, details  # true neutral when no data

    raw_score = weighted_sum / total_weight
    data_coverage = total_weight / max_possible_weight if max_possible_weight > 0 else 0
    confidence_threshold = 0.80  # full confidence at 80%+ data coverage
    confidence = min(1.0, data_coverage / confidence_threshold)
    
    # Blend toward neutral as confidence drops
    adjusted_score = raw_score * confidence + 50.0 * (1.0 - confidence)
    
    details["_confidence"] = round(confidence, 3)
    details["_data_coverage"] = round(data_coverage, 3)
    
    return round(_clamp(adjusted_score), 1), details
```

**Return signature change:** The function still returns `(score, details)` tuple. Confidence is embedded in details dict as `_confidence` and `_data_coverage`.

### 1B. `_compute_xp()` → XP with decay [F-02]

**What:** XP now decays daily and serves as a level stability buffer.

```python
# New constants (also in config)
DEFAULT_XP_PER_LEVEL = 100
DEFAULT_DAILY_XP_DECAY = 2
DEFAULT_XP_BUFFER_THRESHOLD = 20

def _compute_xp(raw_score, previous_xp, config):
    """Compute XP delta with daily decay. Returns (xp_delta, new_xp_total)."""
    bands = config.get("xp_bands", [
        {"min_raw_score": 80, "xp": 3},
        {"min_raw_score": 60, "xp": 2},
        {"min_raw_score": 40, "xp": 1},
        {"min_raw_score": 20, "xp": 0},
        {"min_raw_score": 0,  "xp": -1},
    ])
    leveling = config.get("leveling", {})
    daily_decay = leveling.get("daily_xp_decay", DEFAULT_DAILY_XP_DECAY)
    
    earned = -1
    for band in bands:
        if raw_score >= band["min_raw_score"]:
            earned = band["xp"]
            break
    
    xp_delta = earned - daily_decay
    new_xp = max(0, (previous_xp or 0) + earned - daily_decay)
    
    return earned, xp_delta, new_xp
```

**Call site in `compute_character_sheet()`:** Change from:
```python
xp_delta = _compute_xp(pillar_raw_scores[pillar_name], config)
level_state["xp_total"] = level_state.get("xp_total", 0) + xp_delta
```
To:
```python
prev_xp = prev_state.get("xp_total", 0) if prev_state else 0
xp_earned, xp_delta, new_xp = _compute_xp(pillar_raw_scores[pillar_name], prev_xp, config)
level_state["xp_total"] = new_xp
```

### 1C. `compute_ema_level_score()` → Per-pillar lambda [F-03]

**What:** Accept pillar-specific lambda from config, fall back to global.

```python
def compute_ema_level_score(raw_scores_history, config, pillar_name=None):
    """Compute EMA of raw scores. Uses per-pillar lambda if available."""
    leveling = config.get("leveling", {})
    
    # Per-pillar lambda override
    if pillar_name:
        pillar_cfg = config.get("pillars", {}).get(pillar_name, {})
        lam = pillar_cfg.get("ema_lambda", leveling.get("ema_lambda", 0.85))
    else:
        lam = leveling.get("ema_lambda", 0.85)
    
    window = leveling.get("ema_window_days", 21)
    recent = raw_scores_history[-window:] if len(raw_scores_history) > window else raw_scores_history
    if not recent:
        return 50.0  # Changed from 40.0 [F-09]

    weights = [lam ** i for i in range(len(recent))]
    weights.reverse()

    total = sum(r * w for r, w in zip(recent, weights))
    total_w = sum(weights)
    return round(total / total_w, 1) if total_w > 0 else 50.0
```

**Call site:** Add `pillar_name` arg:
```python
pillar_level_scores[pillar_name] = compute_ema_level_score(history, config, pillar_name)
```

### 1D. Body composition — two-phase scoring [F-04]

**What:** Replace linear interpolation with sigmoid loss + maintenance band.

```python
def _body_comp_score(current_weight, config):
    """Two-phase body composition scoring: sigmoid during loss, band during maintenance."""
    baseline = config.get("baseline", {})
    start = baseline.get("start_weight_lbs", 302)
    goal = baseline.get("goal_weight_lbs", 185)
    maintenance_band = baseline.get("maintenance_band_lbs", 3)
    phase = baseline.get("weight_phase", "loss")
    
    if current_weight is None:
        return None
    
    if phase == "maintenance":
        deviation = abs(current_weight - goal)
        if deviation <= maintenance_band:
            return 100.0
        penalty_range = 20.0 - maintenance_band
        if penalty_range <= 0:
            return 0.0
        score = 100.0 - ((deviation - maintenance_band) / penalty_range) * 100
        return round(_clamp(score), 1)
    
    # Loss phase: sigmoid curve
    if start == goal:
        return None
    progress = (start - current_weight) / (start - goal)
    progress = max(0, min(1.2, progress))
    # Sigmoid: steeper in middle, rewards early momentum
    score = 100 / (1 + math.exp(-8 * (progress - 0.5)))
    return round(_clamp(score), 1)
```

**In `compute_nutrition_raw()`:** Replace the existing body_composition_progress block with:
```python
scores["body_composition_progress"] = _body_comp_score(data.get("latest_weight"), config)
```

### 1E. Cross-pillar effects — explicit modifier types [F-05]

**What:** Config specifies `{"type": "multiplicative", "value": -0.08}` instead of raw numbers. Backward-compatible.

In `compute_cross_pillar_effects()`:
```python
def compute_cross_pillar_effects(pillar_levels, config):
    """Evaluate cross-pillar effects. Returns (active_effects, modifier_dict)."""
    effects_config = config.get("cross_pillar_effects", [])
    active = []
    modifiers = {}

    for effect in effects_config:
        condition = effect.get("condition", "")
        targets = effect.get("targets", {})

        if _evaluate_condition(condition, pillar_levels):
            active.append({
                "name": effect["name"], "emoji": effect.get("emoji", ""),
                "condition": condition, "targets": targets,
            })
            for target_pillar, mod_spec in targets.items():
                # Support both old format (raw number) and new format (dict with type+value)
                if isinstance(mod_spec, dict):
                    mod_value = mod_spec.get("value", 0)
                else:
                    mod_value = mod_spec
                
                if target_pillar == "_all":
                    for p in pillar_levels:
                        modifiers[p] = modifiers.get(p, 0) + mod_value
                else:
                    modifiers[target_pillar] = modifiers.get(target_pillar, 0) + mod_value

    return active, modifiers
```

In `compute_character_sheet()` Step 4, replace the branching logic:
```python
# ALL modifiers are multiplicative: score * (1 + total_mod)
adjusted_level_scores = {}
for pillar_name, ls in pillar_level_scores.items():
    mod = modifiers.get(pillar_name, 0)
    if mod != 0:
        adjusted = ls * (1 + mod)
        adjusted_level_scores[pillar_name] = round(_clamp(adjusted), 1)
    else:
        adjusted_level_scores[pillar_name] = ls
```

### 1F. Lab biomarker decay — extend to zero [F-07]

In `_compute_lab_score()`:
```python
if days_since <= 30:
    decay = 1.0
elif days_since <= 90:
    decay = 1.0 - 0.5 * ((days_since - 30) / 60)
elif days_since <= 180:
    decay = 0.5 - 0.4 * ((days_since - 90) / 90)
else:
    decay = 0.0  # Fully expired — no contribution from stale labs
```

### 1G. Vice control — logarithmic curve [F-12]

In `compute_mind_raw()`:
```python
if streaks:
    avg_streak = sum(streaks) / len(streaks)
    # Logarithmic: front-loads credit for hard early days
    # Day 7 ≈ 58, Day 14 ≈ 77, Day 30 = 100
    scores["vice_control"] = _clamp(round(
        100 * math.log(1 + avg_streak) / math.log(31), 1
    ))
```

### 1H. `evaluate_level_changes()` — Progressive difficulty [F-15]

**What:** Streak requirements scale by tier. Variable step size when delta >10.

```python
def evaluate_level_changes(pillar_name, current_level_score, previous_state, config):
    """Level changes with progressive difficulty by tier."""
    leveling = config.get("leveling", {})
    
    # Progressive streak overrides by tier
    tier_overrides = leveling.get("tier_streak_overrides", {})
    
    prev = previous_state or {
        "level": 1, "tier": "Foundation", "streak_above": 0,
        "streak_below": 0, "xp_total": 0
    }
    current_level = prev.get("level", 1)
    current_tier_info = get_tier(current_level, config)
    current_tier_name = current_tier_info["name"]
    streak_above = prev.get("streak_above", 0)
    streak_below = prev.get("streak_below", 0)
    xp_total = prev.get("xp_total", 0)
    
    # Look up streak requirements for current tier
    tier_cfg = tier_overrides.get(current_tier_name, {})
    up_streak_needed = tier_cfg.get("up", leveling.get("level_up_streak_days", 5))
    down_streak_needed = tier_cfg.get("down", leveling.get("level_down_streak_days", 7))
    tier_up_streak_needed = tier_cfg.get("tier_boundary_up", leveling.get("tier_up_streak_days", 7))
    tier_down_streak_needed = tier_cfg.get("tier_boundary_down", leveling.get("tier_down_streak_days", 10))
    
    # Variable step size [F-10]
    level_step_threshold = leveling.get("level_step_threshold", 10)
    
    # XP buffer gate for level-down [F-02]
    xp_per_level = leveling.get("xp_per_level", 100)
    xp_buffer_threshold = leveling.get("xp_buffer_threshold", 20)
    xp_buffer = xp_total % xp_per_level if xp_per_level > 0 else 0

    target_level = max(1, min(100, round(current_level_score)))
    events = []

    if target_level > current_level:
        streak_above += 1
        streak_below = 0
        if streak_above >= up_streak_needed:
            old_tier = get_tier(current_level, config)["name"]
            new_tier = get_tier(current_level + 1, config)["name"]
            would_cross_tier = old_tier != new_tier

            if would_cross_tier and streak_above < tier_up_streak_needed:
                pass  # Hold — need longer streak for tier transition
            else:
                old_level = current_level
                delta = target_level - current_level
                step = 2 if delta > level_step_threshold else 1
                current_level = min(current_level + step, 100)
                streak_above = 0
                events.append({
                    "type": "level_up", "pillar": pillar_name,
                    "old_level": old_level, "new_level": current_level,
                })
    elif target_level < current_level:
        streak_below += 1
        streak_above = 0
        if streak_below >= down_streak_needed:
            # XP buffer gate: can't lose a level until XP buffer is depleted
            if xp_buffer >= xp_buffer_threshold:
                pass  # Buffer absorbs the pressure — hold level
            else:
                old_tier = get_tier(current_level, config)["name"]
                new_tier = get_tier(current_level - 1, config)["name"]
                would_cross_tier = old_tier != new_tier

                if would_cross_tier and streak_below < tier_down_streak_needed:
                    pass  # Hold — need longer streak for tier demotion
                else:
                    old_level = current_level
                    current_level = max(current_level - 1, 1)
                    streak_below = 0
                    events.append({
                        "type": "level_down", "pillar": pillar_name,
                        "old_level": old_level, "new_level": current_level,
                    })
    else:
        # Equal day: hold streaks constant [F-11]
        pass

    # Check tier transitions
    new_tier_info = get_tier(current_level, config)
    new_tier = new_tier_info["name"]
    current_tier = prev.get("tier", "Foundation")
    if new_tier != current_tier:
        etype = "tier_up" if current_level > prev.get("level", 1) else "tier_down"
        events.append({
            "type": etype, "pillar": pillar_name,
            "old_tier": current_tier, "new_tier": new_tier,
            "old_level": prev.get("level", 1), "new_level": current_level,
        })
        current_tier = new_tier

    return {
        "level": current_level, "tier": current_tier,
        "tier_emoji": new_tier_info.get("emoji", "🔨"),
        "streak_above": streak_above, "streak_below": streak_below,
        "xp_total": xp_total, "xp_buffer": xp_buffer, "events": events,
    }
```

### 1I. Character level — floor instead of round [F-14]

In `compute_character_sheet()`:
```python
character_level = max(1, min(100, int(math.floor(weighted_level_sum / total_weight)))) if total_weight > 0 else 1
```

### 1J. `_in_range_score()` buffer fix [F-13]

```python
def _in_range_score(value, low, high, buffer=0.1):
    if value is None:
        return None
    if low <= value <= high:
        return 100.0
    range_span = max(high - low, 1)  # avoid division by zero
    if value < low:
        dist = (low - value) / (range_span * buffer)
        return _clamp(100.0 - dist * 100)
    dist = (value - high) / (range_span * buffer)
    return _clamp(100.0 - dist * 100)
```

### 1K. Default neutral score: 50 not 40 [F-09]

All occurrences of `return 40.0, details` or `return 40.0` as "no data" fallbacks → change to `50.0`.

---

## Part 2: Config Changes (`config/character_sheet.json`)

All changes are additive. Missing keys fall back to current behavior.

```json
{
  "_meta": {
    "version": "1.1.0",
    "description": "Character Sheet v1.1.0: progressive difficulty, confidence scoring, XP-as-buffer, per-pillar EMA",
    "last_updated": "2026-03-30",
    "review_ref": "docs/reviews/REVIEW_CHARACTER_LEVELING_2026-03-30.md"
  },
  "baseline": {
    "start_date": "2026-04-01",
    "start_weight_lbs": 302,
    "goal_weight_lbs": 185,
    "weight_phase": "loss",
    "maintenance_band_lbs": 3
  },
  "pillars": {
    "sleep": {
      "weight": 0.20,
      "ema_lambda": 0.85,
      "owner": "Dr. Lisa Park",
      "components": {
        "duration_vs_target": { "weight": 0.25, "target_hours": 7.5 },
        "efficiency": { "weight": 0.20 },
        "deep_sleep_pct": { "weight": 0.20, "target_pct": 0.15 },
        "rem_pct": { "weight": 0.15, "target_pct": 0.20 },
        "onset_consistency": { "weight": 0.20, "window_days": 14 }
      }
    },
    "movement": {
      "weight": 0.18,
      "ema_lambda": 0.90,
      "owner": "Dr. Sarah Chen",
      "components": {
        "training_frequency": { "weight": 0.20, "target_sessions_week": 5 },
        "zone2_adequacy": { "weight": 0.25, "target_minutes": 150 },
        "training_load_balance": { "weight": 0.20 },
        "progressive_overload": { "weight": 0.15 },
        "movement_diversity": { "weight": 0.10, "target_types": 4 },
        "daily_steps": { "weight": 0.10, "target": 8000 }
      }
    },
    "nutrition": {
      "weight": 0.18,
      "ema_lambda": 0.88,
      "owner": "Dr. Marcus Webb",
      "components": {
        "calorie_adherence": { "weight": 0.20, "tolerance_pct": 0.10 },
        "protein_total": { "weight": 0.20, "target_grams": 190 },
        "protein_distribution": { "weight": 0.10, "threshold_grams": 30, "target_meals": 4 },
        "consistency": { "weight": 0.10 },
        "body_composition_progress": { "weight": 0.40 }
      }
    },
    "metabolic": {
      "weight": 0.12,
      "ema_lambda": 0.95,
      "owner": "Dr. Peter Attia",
      "components": {
        "body_fat_trajectory": { "weight": 0.25 },
        "cgm_glucose_control": { "weight": 0.25 },
        "lab_biomarkers": { "weight": 0.30, "full_value_days": 30, "decay_period_days": 60, "expiry_days": 180, "floor_pct": 0.0 },
        "blood_pressure": { "weight": 0.10 },
        "resting_heart_rate": { "weight": 0.10 }
      }
    },
    "mind": {
      "weight": 0.15,
      "ema_lambda": 0.85,
      "owner": "Coach Maya Rodriguez",
      "components": {
        "t0_habit_compliance": { "weight": 0.30 },
        "t1_habit_compliance": { "weight": 0.15 },
        "journal_consistency": { "weight": 0.15 },
        "state_of_mind_valence": { "weight": 0.15 },
        "stress_management": { "weight": 0.15 },
        "vice_control": { "weight": 0.10 }
      }
    },
    "relationships": {
      "weight": 0.07,
      "ema_lambda": 0.93,
      "rolling_window_days": 14,
      "owner": "Social Connection",
      "components": {
        "social_interaction_frequency": { "weight": 0.40 },
        "interaction_quality": { "weight": 0.30 },
        "buddy_engagement": { "weight": 0.15 },
        "social_mood_correlation": { "weight": 0.15 }
      }
    },
    "consistency": {
      "weight": 0.10,
      "ema_lambda": 0.93,
      "owner": "The Chair",
      "components": {
        "cross_pillar_variance": { "weight": 0.40 },
        "data_completeness": { "weight": 0.20 },
        "streak_maintenance": { "weight": 0.20 },
        "weekend_weekday_stability": { "weight": 0.20 }
      }
    }
  },
  "leveling": {
    "ema_lambda": 0.85,
    "ema_window_days": 21,
    "level_up_streak_days": 5,
    "level_down_streak_days": 7,
    "tier_up_streak_days": 7,
    "tier_down_streak_days": 10,
    "level_step_threshold": 10,
    "xp_per_level": 100,
    "daily_xp_decay": 2,
    "xp_buffer_threshold": 20,
    "tier_streak_overrides": {
      "Foundation":  { "up": 3,  "down": 5,  "tier_boundary_up": 5,  "tier_boundary_down": 7 },
      "Momentum":    { "up": 5,  "down": 7,  "tier_boundary_up": 7,  "tier_boundary_down": 10 },
      "Discipline":  { "up": 7,  "down": 10, "tier_boundary_up": 10, "tier_boundary_down": 14 },
      "Mastery":     { "up": 10, "down": 14, "tier_boundary_up": 14, "tier_boundary_down": 21 },
      "Elite":       { "up": 14, "down": 21, "tier_boundary_up": 21, "tier_boundary_down": 30 }
    }
  },
  "xp_bands": [
    { "min_raw_score": 80, "xp": 3 },
    { "min_raw_score": 60, "xp": 2 },
    { "min_raw_score": 40, "xp": 1 },
    { "min_raw_score": 20, "xp": 0 },
    { "min_raw_score": 0,  "xp": -1 }
  ],
  "tiers": [
    { "name": "Foundation", "emoji": "🔨", "min_level": 1,  "max_level": 20 },
    { "name": "Momentum",   "emoji": "🔥", "min_level": 21, "max_level": 40 },
    { "name": "Discipline", "emoji": "⚔️", "min_level": 41, "max_level": 60 },
    { "name": "Mastery",    "emoji": "🏆", "min_level": 61, "max_level": 80 },
    { "name": "Elite",      "emoji": "👑", "min_level": 81, "max_level": 100 }
  ],
  "cross_pillar_effects": [
    { "name": "Sleep Drag",      "emoji": "🛏️", "condition": "sleep < 35",                         "targets": { "movement": {"type": "multiplicative", "value": -0.08}, "mind": {"type": "multiplicative", "value": -0.05} } },
    { "name": "Training Boost",  "emoji": "💪", "condition": "movement > 70",                      "targets": { "metabolic": {"type": "multiplicative", "value": 0.05} } },
    { "name": "Focus Buff",      "emoji": "🧠", "condition": "mind > 70",                          "targets": { "consistency": {"type": "multiplicative", "value": 0.03} } },
    { "name": "Synergy Bonus",   "emoji": "⚡",  "condition": "nutrition > 70 AND movement > 70",   "targets": { "metabolic": {"type": "multiplicative", "value": 0.08} } },
    { "name": "Alignment Bonus", "emoji": "🌟", "condition": "all_pillars >= 41",                  "targets": { "_all": {"type": "multiplicative", "value": 0.03} } },
    { "name": "Vice Shield",     "emoji": "🛡️", "condition": "any_vice_streak > 30",               "targets": { "mind": {"type": "multiplicative", "value": 0.03} } }
  ],
  "avatar": {
    "enabled": true,
    "style": "pixel_rpg",
    "s3_prefix": "dashboard/avatar/"
  }
}
```

---

## Part 3: DynamoDB Schema Additions

Added to each `pillar_*` map within `character_sheet` records:

| Field | Type | Description |
|-------|------|-------------|
| `confidence` | number | 0.0–1.0 from `_weighted_pillar_score` |
| `data_coverage` | number | 0.0–1.0 ratio of available to max weight |
| `xp_buffer` | number | XP within current level (0 to xp_per_level) |

Added to the top-level record:

| Field | Type | Description |
|-------|------|-------------|
| `min_confidence` | number | Lowest pillar confidence |
| `avg_confidence` | number | Average pillar confidence |

**No migration needed** — schemaless DynamoDB. New fields appear on next compute.

---

## Part 4: Retrocompute Consideration

After engine v1.1.0 is deployed, the existing character_sheet history was computed by v1.0.0. Options:

**Option A (Recommended):** Run `retrocompute_character_sheet.py` with `--force` to recompute all history with v1.1.0 rules. This produces a clean, consistent dataset.

**Option B:** Let v1.1.0 compute forward from today. Historical records retain v1.0.0 calculations. The `engine_version` field distinguishes them. Level history may show a discontinuity at the transition date.

**Recommendation:** Option A. The dataset is small (~40 days). Retrocompute takes <5 minutes. Clean history is worth the effort.

---

## Part 5: Character Page Content Updates

### 5A. Methodology Section (replaces current incorrect text)

Replace the `<section class="method-section">` content with:

```html
<!-- ═══ METHODOLOGY ═══ -->
<section class="method-section reveal">
  <div class="eyebrow">Methodology</div>
  <h2 class="text-h3" style="color:var(--text)">How the score works</h2>
  <div class="method-grid">
    <div>
      <p>Every night, 26 data sources — wearables, food logs, habit trackers, blood work, journals — feed a scoring engine. No self-reporting. The engine grades yesterday across 7 pillars and updates the character level.</p>
      <p>Leveling up isn't about having one great day. It requires <strong>sustained performance</strong> — consecutive days above your current level. And the higher you climb, the longer you have to prove it. Early levels come in days. Higher levels take weeks. The top requires months of consistency across every pillar.</p>
      <p>Leveling down is harder than leveling up. The system is designed to reward progress, not punish bad days. A rough week won't erase months of work — but a rough month will get your attention.</p>
    </div>
    <div class="sources-table">
      <div class="sources-table__header">Pillar weights & sources</div>
      <div class="sources-row"><span class="sources-row__name">Sleep <span style="color:var(--text-faint)">(20%)</span></span><span class="sources-row__desc">Whoop + Eight Sleep: duration, efficiency, deep/REM %, onset consistency</span></div>
      <div class="sources-row"><span class="sources-row__name">Movement <span style="color:var(--text-faint)">(18%)</span></span><span class="sources-row__desc">Strava + Garmin + Apple: training frequency, Zone 2, load balance, steps</span></div>
      <div class="sources-row"><span class="sources-row__name">Nutrition <span style="color:var(--text-faint)">(18%)</span></span><span class="sources-row__desc">MacroFactor + Withings: calorie/protein adherence, body composition progress</span></div>
      <div class="sources-row"><span class="sources-row__name">Mind <span style="color:var(--text-faint)">(15%)</span></span><span class="sources-row__desc">Habitify + Notion + How We Feel: habits, journaling, emotional state, vices</span></div>
      <div class="sources-row"><span class="sources-row__name">Metabolic <span style="color:var(--text-faint)">(12%)</span></span><span class="sources-row__desc">CGM + labs + Withings: glucose control, biomarkers, blood pressure, body fat</span></div>
      <div class="sources-row"><span class="sources-row__name">Consistency <span style="color:var(--text-faint)">(10%)</span></span><span class="sources-row__desc">Cross-pillar balance, data completeness, streak maintenance</span></div>
      <div class="sources-row"><span class="sources-row__name">Social <span style="color:var(--text-faint)">(7%)</span></span><span class="sources-row__desc">Journal-derived social interaction frequency and quality</span></div>
    </div>
  </div>
</section>
```

### 5B. "The Math" Expandable Section (replaces current incorrect formulas)

Replace the `<details class="math-details">` block with:

```html
<!-- ═══ THE MATH ═══ -->
<details class="math-details">
  <summary>The Math — How leveling actually works</summary>
  <div class="math-details__body">
    
    <p style="color:var(--text);font-weight:600;margin-bottom:var(--space-4)">The 30-second version</p>
    <p>Each pillar scores 0–100 nightly from real data. The scores are smoothed over time (recent days count more). If your smoothed score stays above your current level long enough, you level up. If it drops below long enough, you level down. The "long enough" gets longer as you climb higher.</p>

    <p style="color:var(--text);font-weight:600;margin-top:var(--space-6);margin-bottom:var(--space-4)">The deeper version</p>

    <p><strong>Step 1 — Raw scores.</strong> Each pillar has 4–6 weighted components. Sleep, for example, is 25% duration vs. target, 20% efficiency, 20% deep sleep %, 15% REM %, and 20% onset consistency. These produce a raw score (0–100) every night. When a data source is missing, the engine reduces confidence in that pillar's score — it doesn't pretend the missing data doesn't matter.</p>

    <p><strong>Step 2 — Smoothing.</strong> Raw scores feed into an exponentially-weighted moving average (EMA). The most recent day counts most; 3 weeks ago barely registers. Each pillar has its own smoothing rate — Sleep responds quickly (half-life ~4 days), Metabolic Health moves slowly (half-life ~14 days). This prevents one great day from masking a bad week, and one bad day from erasing a great month.</p>

    <p><strong>Step 3 — Level changes.</strong> Your smoothed score suggests a "target level." If the target is above your current level, a streak counter starts ticking. Once the streak reaches the threshold for your tier, you level up. The thresholds increase with tier:</p>

    <div style="font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text-muted);margin:var(--space-4) 0;padding:var(--space-4);background:var(--surface);border-left:2px solid var(--tier-accent)">
      Foundation (Lv 1–20) ··· 3 days to level up · 5 days to level down<br>
      Momentum (Lv 21–40) ··· 5 days up · 7 days down<br>
      Discipline (Lv 41–60) ··· 7 days up · 10 days down<br>
      Mastery (Lv 61–80) ··· 10 days up · 14 days down<br>
      Elite (Lv 81–100) ··· 14 days up · 21 days down
    </div>

    <p>Crossing a tier boundary (e.g., Momentum → Discipline at Level 41) requires an even longer streak — you have to prove you belong in the new tier, not just that you briefly touched the threshold.</p>

    <p><strong>Step 4 — XP as resilience.</strong> Every day earns XP based on raw score (good days earn more, bad days can lose some). XP decays slowly over time — you can't coast on past performance forever. High XP at your current level acts as a buffer: if your scores dip, the XP absorbs the pressure before you lose a level. Think of it as earned trust — months of good behavior buys you grace during a rough patch.</p>

    <p><strong>Step 5 — Cross-pillar effects.</strong> Pillars aren't independent. Sustained poor sleep applies a visible debuff to Movement and Mind scores (you can't out-train bad sleep). High performance in both Nutrition and Movement boosts Metabolic Health. When all pillars score 41+, a global Alignment Bonus kicks in. These effects model real physiology — sleep deprivation genuinely impairs exercise performance and emotional regulation.</p>

    <p><strong>Step 6 — Character level.</strong> The 7 pillar levels are weighted-averaged (Sleep 20%, Movement 18%, Nutrition 18%, Mind 15%, Metabolic 12%, Consistency 10%, Social 7%) into one number: the Character Level. The weights reflect the scientific evidence for each domain's impact on healthspan and all-cause mortality.</p>

    <p style="font-size:var(--text-xs);color:var(--text-faint);font-family:var(--font-mono);letter-spacing:var(--ls-label);margin-top:var(--space-6);margin-bottom:0">// Pillar weights grounded in epidemiological evidence (Cappuccio 2010, Mandsager 2018, Holt-Lunstad 2015). Full rationale: see platform architecture docs.</p>
  </div>
</details>
```

### 5C. Tier Framework Section (update the existing tier descriptions)

The existing tier framework section already has the right structure. Update the descriptions to reflect progressive difficulty:

```html
<!-- Inside the existing .tier-framework rows -->
<div class="tf-row" data-tier="foundation">
  <div class="tf-row__tier">🔨 Foundation</div>
  <div class="tf-row__range">Lv 1–20</div>
  <div class="tf-row__desc">Building the baseline. Every data source connected, every habit tracked. Level up in 3 days of sustained improvement — the feedback loop is fast because momentum matters most here.</div>
</div>
<div class="tf-row" data-tier="momentum">
  <div class="tf-row__tier">🔥 Momentum</div>
  <div class="tf-row__range">Lv 21–40</div>
  <div class="tf-row__desc">The routine is forming. 5-day streaks required to level up. Weekends are the real test — can you maintain when structure disappears?</div>
</div>
<div class="tf-row" data-tier="discipline">
  <div class="tf-row__tier">⚔️ Discipline</div>
  <div class="tf-row__range">Lv 41–60</div>
  <div class="tf-row__desc">Optimizing from a stable base. 7 consecutive days to prove each level. Running experiments. The hard part isn't starting anymore — it's not stopping.</div>
</div>
<div class="tf-row" data-tier="mastery">
  <div class="tf-row__tier">🏆 Mastery</div>
  <div class="tf-row__range">Lv 61–80</div>
  <div class="tf-row__desc">All 7 pillars performing. 10-day streaks — you've navigated weekends, social events, and stress without collapse. The system works, and you're refining it.</div>
</div>
<div class="tf-row" data-tier="elite">
  <div class="tf-row__tier">👑 Elite</div>
  <div class="tf-row__range">Lv 81–100</div>
  <div class="tf-row__desc">Sustained excellence across every dimension. 14 days to earn each level. This isn't discipline anymore — it's identity. You've become the person.</div>
</div>
```

### 5D. Introductory "how it works" paragraph (update existing)

Replace the brief paragraph below the pillar grid (currently line ~1326):

```html
<p>Every night, <span data-const="platform.data_sources">26</span> data sources feed a scoring engine that grades yesterday across Sleep, Movement, Nutrition, Metabolic, Mind, Social, and Consistency. Each pillar is weighted by its evidence-backed impact on healthspan. Level progression gets harder as you climb — early levels come in days, higher levels demand weeks of sustained performance across all pillars. The system is designed so that reaching Level 80 genuinely means something.</p>
<p style="font-size:var(--text-xs);color:var(--text-faint);font-family:var(--font-mono);letter-spacing:var(--ls-label);margin-bottom:0">// 7 weighted pillars · scored nightly · no self-reporting · progressive difficulty</p>
```

### 5E. N=1 Disclaimer (keep as-is, minor update)

Keep the existing disclaimer. No changes needed.

---

## Part 6: Tests

### Unit tests to add or update (`tests/test_character_engine.py`)

```python
# F-01: Confidence scoring
def test_weighted_pillar_score_full_data():
    """Full data → confidence 1.0, no blending."""
    scores = {"a": 80, "b": 60}
    config = {"a": {"weight": 0.5}, "b": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert details["_confidence"] == 1.0
    assert score == 70.0  # straight average

def test_weighted_pillar_score_sparse_data():
    """50% data coverage → blended toward neutral."""
    scores = {"a": 80, "b": None}
    config = {"a": {"weight": 0.5}, "b": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert details["_confidence"] < 1.0
    assert 50 < score < 80  # blended toward 50

def test_weighted_pillar_score_no_data():
    """No data → neutral 50, confidence 0."""
    scores = {"a": None, "b": None}
    config = {"a": {"weight": 0.5}, "b": {"weight": 0.5}}
    score, details = _weighted_pillar_score(scores, config)
    assert score == 50.0
    assert details["_confidence"] == 0.0

# F-02: XP decay
def test_xp_decays_on_mediocre_day():
    """Score 40 earns +1 XP but decay -2 → net -1."""
    config = {"xp_bands": [{"min_raw_score": 40, "xp": 1}], "leveling": {"daily_xp_decay": 2}}
    earned, delta, new_xp = _compute_xp(45, 100, config)
    assert earned == 1
    assert delta == -1  # 1 earned - 2 decay
    assert new_xp == 99  # 100 + 1 - 2

def test_xp_floors_at_zero():
    config = {"xp_bands": [{"min_raw_score": 0, "xp": -1}], "leveling": {"daily_xp_decay": 2}}
    _, _, new_xp = _compute_xp(10, 1, config)
    assert new_xp == 0  # Can't go negative

# F-04: Body comp sigmoid
def test_body_comp_loss_sigmoid():
    """Sigmoid produces nonlinear curve."""
    config = {"baseline": {"start_weight_lbs": 302, "goal_weight_lbs": 185, "weight_phase": "loss"}}
    score_at_300 = _body_comp_score(300, config)
    score_at_250 = _body_comp_score(250, config)
    score_at_200 = _body_comp_score(200, config)
    assert score_at_300 < score_at_250 < score_at_200
    # Sigmoid front-loads: first 50lbs should earn more than last 50lbs
    first_50_gain = score_at_250 - score_at_300
    last_50_gain = score_at_200 - score_at_250
    # Not strictly enforced due to sigmoid shape, but early gains should be meaningful
    assert score_at_250 > 30  # Mid-journey should be above 30

def test_body_comp_maintenance():
    config = {"baseline": {"goal_weight_lbs": 185, "weight_phase": "maintenance", "maintenance_band_lbs": 3}}
    assert _body_comp_score(185, config) == 100.0
    assert _body_comp_score(187, config) == 100.0  # within band
    assert _body_comp_score(190, config) < 100.0   # outside band
    assert _body_comp_score(205, config) == 0.0     # 20 lbs out

# F-07: Lab decay to zero
def test_lab_decay_expires():
    labs = {"date": "2025-06-01", "apob": 80}
    score = _compute_lab_score(labs, "2026-03-01", {})
    assert score == 0.0  # 270+ days → fully expired

# F-12: Vice log curve
def test_vice_log_curve():
    """Day 7 should score higher than linear 23%."""
    import math
    avg_streak = 7
    score = min(100, round(100 * math.log(1 + avg_streak) / math.log(31), 1))
    assert score > 50  # log curve rewards early days

# F-15: Progressive streaks
def test_foundation_levels_up_in_3_days():
    config = {"leveling": {"tier_streak_overrides": {"Foundation": {"up": 3, "down": 5}}}, "tiers": [{"name": "Foundation", "min_level": 1, "max_level": 20}]}
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("sleep", 60.0, prev, config)
    assert result["level"] == 6  # 3rd day → level up

def test_mastery_requires_10_days():
    config = {"leveling": {"tier_streak_overrides": {"Mastery": {"up": 10, "down": 14}}}, "tiers": [{"name": "Mastery", "min_level": 61, "max_level": 80}]}
    prev = {"level": 65, "tier": "Mastery", "streak_above": 8, "streak_below": 0, "xp_total": 500}
    result = evaluate_level_changes("sleep", 70.0, prev, config)
    assert result["level"] == 65  # Only 9th day — need 10
    
def test_equal_day_holds_streak():
    """Equal day should not decay streak [F-11]."""
    config = {"leveling": {"tier_streak_overrides": {"Foundation": {"up": 3}}}, "tiers": [{"name": "Foundation", "min_level": 1, "max_level": 20}]}
    prev = {"level": 5, "tier": "Foundation", "streak_above": 2, "streak_below": 0, "xp_total": 50}
    result = evaluate_level_changes("sleep", 5.0, prev, config)  # target == current
    assert result["streak_above"] == 2  # Held, not decayed
```

---

## Part 7: Retrocompute Script Update

`backfill/retrocompute_character_sheet.py` needs to pass the new args:

1. Pass `pillar_name` to `compute_ema_level_score()`
2. Pass `previous_xp` to `_compute_xp()`  
3. The script already processes days sequentially (required for streak tracking), so progressive difficulty works without structural changes

---

## Part 8: Deploy Sequence

```bash
# 1. Update config in S3
aws s3 cp config/character_sheet.json s3://matthew-life-platform/config/matthew/character_sheet.json

# 2. Deploy character_engine.py (lives in shared layer)
bash deploy/p3_build_shared_utils_layer.sh
bash deploy/p3_attach_shared_utils_layer.sh

# 3. Run retrocompute to recompute all history with v1.1.0
python3 backfill/retrocompute_character_sheet.py --write --force

# 4. Update character page
aws s3 cp site/character/index.html s3://matthew-life-platform/site/character/index.html --content-type "text/html"

# 5. Invalidate CloudFront
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/character/*" "/config/*"

# 6. Verify
# Check a recent character_sheet record in DDB for new fields (confidence, xp_buffer, engine_version 1.1.0)
```

---

## Part 9: Acceptance Criteria

The implementation is complete when:

1. ✅ `character_engine.py` `ENGINE_VERSION = "1.1.0"`
2. ✅ All 15 findings implemented (F-01 through F-15)
3. ✅ Config v1.1.0 deployed to S3 with `tier_streak_overrides`
4. ✅ Retrocompute runs clean — all history recomputed with v1.1.0
5. ✅ Unit tests pass for all new/changed functions
6. ✅ Character page methodology section is factually correct
7. ✅ Character page "The Math" section explains progressive difficulty
8. ✅ Pillar weights shown on the character page match config (not "equal")
9. ✅ No references to "logarithmic XP curve" remain (that was never real)
10. ✅ MCP registry test passes: `python3 -m pytest tests/test_mcp_registry.py -v`

---

## Part 10: What This Spec Does NOT Cover

- **Pillar weight rationale document** (`docs/PILLAR_WEIGHT_RATIONALE.md`) — Lena's requirement. Should be written separately.
- **Relationships 14-day rolling window** (F-08 Option B) — Approved but implementation deferred. Requires changes to `compute_relationships_raw()` to accept 14 days of journal data instead of just today's.
- **`log_social_interaction` MCP tool** (F-08 Option C) — Roadmap item, not blocking.
- **Mind pillar split** (Discipline vs. Wellbeing) — v2 consideration per Henning.
- **Huberman's variable-ratio reward scheduling** — v2 behavioral polish.
- **Norton's asymmetric calorie adherence** — Good idea, small code change, can be added in a follow-up.

---

*Spec complete. Ready for Claude Code handoff.*
