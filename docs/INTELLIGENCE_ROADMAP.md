# Intelligence Layer Roadmap

**Last updated:** 2026-04-07
**Current state:** V2 implemented, V2.1 and V2.2 queued

---

## Completed: V2 — Foundation

- [x] Consolidated observatory coaches into board_of_directors.json
- [x] Created user_goals.json schema (initially null targets)
- [x] Built shared utilities: build_data_inventory(), build_data_maturity(), load_goals_config(), build_coach_preamble()
- [x] Observatory Lambda reads from board config instead of hardcoded dict
- [x] Goals + data inventory + data maturity injected into all coach prompts
- [x] First-person voice directive for all coaches
- [x] Three-phase voice system (orientation/emerging/established) with per-coach thresholds
- [x] Intelligence validator (Mode A — post-generation alerting, 5 check types)
- [x] SOURCE#intelligence_quality DDB partition + get_intelligence_quality MCP tool
- [x] Dr. Kai Nakamura (Integrator) added to board config
- [x] Coach synthesis: second-pass generation after all coaches
- [x] "This Week's Priority" in weekly digest
- [x] "Cross-Domain Context" callout on observatory pages
- [x] Action completion loop: SOURCE#coach_actions partition, action write on generation, nightly auto-detection
- [x] MCP tools: list_actions, complete_action, get_action_history
- [x] Action history injected into coach prompt context
- [x] Maya Rodriguez expanded mandate: Builder's Paradox detection
- [x] Builder's Paradox score computation
- [x] Step count SOT: Garmin designated as primary
- [x] Character level display fix (was showing Lv 1, actual level 4)

**Spec:** `docs/INTELLIGENCE_LAYER_V2_SPEC.md`

---

## Queued: V2.1 — Coach Personality & Persistent Memory

- [ ] Coach Thread DDB partition (SOURCE#coach_thread#{coach_id})
- [ ] Thread write/read functions in intelligence_common.py
- [ ] Personality seeds added to board_of_directors.json for all 8 coaches
- [ ] Thread extraction: structured-output API call after each generation
- [ ] Thread injection into coach prompt preamble ("YOUR THREAD" block)
- [ ] Prediction tracking: predictions parsed from coach output, stored in thread
- [ ] Prediction evaluation logic in nightly warmer
- [ ] Disagreement detection during Nakamura's synthesis pass
- [ ] Coaching Dashboard page (/coaches/) — panel view, open actions, predictions, profiles
- [ ] Homepage widgets: Weekly Priority card + Open Actions strip
- [ ] Validator Mode B: inline correction (re-prompt on errors, max 1 pass)
- [ ] MCP tools: get_coach_thread, get_predictions, get_coach_disagreements, evaluate_prediction, get_coaching_summary

**Spec:** `docs/INTELLIGENCE_LAYER_V2_1_SPEC.md`
**Estimated:** 5 CC sessions

---

## Queued: V2.2 — Credibility, Public Intelligence, Hardening

- [ ] Public prediction tracker page (/predictions/) — scoreboard, timeline, notable predictions
- [ ] Coach learning timeline UI on /coaches/ profiles
- [ ] Chronicle integration: Elena Voss interviews use coach thread data
- [ ] Coach credibility scores (prediction accuracy + calibration)
- [ ] Credibility injected into coach prompts + Nakamura integrator
- [ ] Thread summarization at month boundaries (scalability)
- [ ] Intelligence pipeline monitoring: CloudWatch alarms, SNS alerts
- [ ] MCP tool: get_intelligence_costs
- [ ] Smoke test script update (15 stale HTML expectations)
- [ ] Coach Intelligence Lambda unit tests (8 files, ~300KB)
- [ ] Unused imports cleanup (464 F401 flake8)
- [ ] Observatory Lambda CDK migration
- [ ] ai_expert_analyzer deprecation marker cleanup

**Spec:** `docs/INTELLIGENCE_LAYER_V2_2_SPEC.md`
**Estimated:** 4 CC sessions

---

## Queued: Goals Config Update

- [ ] Upload populated user_goals.json to S3 (replacing null-target version)
- [ ] Regenerate observatory pages with full goals context
- [ ] Verify coaches reference goals correctly in next generation cycle

**Spec:** This file + `config/user_goals.json`
**Estimated:** 0.5 CC sessions (or single CC prompt)

---

## Data-Gated (waiting for time to pass)

| Item | Gate | Earliest Date | Notes |
|------|------|---------------|-------|
| IC-4: Failure pattern detection | 30 days of data | ~May 1, 2026 | Needs enough behavioral data to detect patterns |
| IC-5: Momentum warnings | 30 days of data | ~May 1, 2026 | Weight trend + habit data need baseline |
| Coach "rivalry" dynamics | 8+ weeks prediction history | ~June 2026 | Coaches explicitly referencing each other's track records. Needs enough predictions resolved. |
| Metabolic adaptation detection | TDEE tracking + 6 weeks deficit | ~May 15, 2026 | MacroFactor adaptive TDEE must have enough data to detect plateau |
| Validator calibration | 4+ weeks of validator running | ~May 2026 | Validator becomes more useful as coaches accumulate history and make evaluable predictions |
| Training phase auto-detection | Training log accumulation | Ongoing | Auto-detect Foundation→Build→Peak transitions from actual training data vs goals phases |
| DEXA recheck trigger | Weight milestone (250 lbs) | ~Month 4 | Auto-suggest DEXA when hitting 250 lbs milestone to verify composition trajectory |

---

## Future (V3+) — Not Designed Yet

| Item | Description | Dependency |
|------|-------------|------------|
| **Buddy site coaching** | Tom's buddy.averagejoematt.com is disconnected from intelligence layer. Multi-tenant coaching architecture. | V2.1+ stable |
| **Coach voice tuning from reader feedback** | If readers engage (share, comment), use engagement signals to tune which coach narratives resonate | Reader analytics |
| **Automated training program generation** | Dr. Chen generates weekly training programs based on phase, recovery, progressive overload | Training data + phase detection |
| **Nutrition plan suggestions** | Dr. Webb suggests meal plans optimized for protein at calorie target | MacroFactor meal history + goals |
| **Early warning Lambda** | Standalone Lambda that monitors failure_mode.early_warning_signals and fires alerts proactively (not waiting for weekly digest) | V2 action loop + behavioral data |
| **Crisis protocol** | When 3+ early warning signals fire simultaneously, Nakamura triggers a "crisis protocol" — simplified coaching (one action only), increased check-in frequency, Maya primary | Failure mode detection |
| **Weight cycling metabolic research** | Platform-specific literature review on metabolic impact of repeated gain/loss cycles, personalized to Matthew's history | Stable coaching foundation |
| **Public coaching API** | Allow other users to create their own coaching panels (far future, requires significant architecture) | Full V2.2 stable |

---

## Technical Debt Backlog

| Item | Severity | Notes |
|------|----------|-------|
| Coach Intelligence Lambdas — no unit tests | Medium | 8 files, ~300KB. Addressed in V2.2 |
| 464 unused imports (F401) | Low | Cosmetic. Addressed in V2.2 |
| Observatory Lambda not in CDK | Medium | Manually deployed. Addressed in V2.2 |
| Smoke test script stale | Medium | 15 expectations wrong. Addressed in V2.2 |
| ai_expert_analyzer marked deprecated but active | Low | Confusing. Addressed in V2.2 |
| Stale reference in RUNBOOK session-close checklist | Low | Archived sync script still referenced |
| SIMP-1 Phase 2 tool consolidation | Medium | Target ≤80 tools, currently 115. ~April 13 target |
