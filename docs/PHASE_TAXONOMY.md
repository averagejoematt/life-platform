# Phase Taxonomy — experiment-restart data semantics

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-06-07

**Authoritative classification of every DynamoDB record type for experiment restarts.**
Machine-readable source of truth: `lambdas/phase_taxonomy.py` (shared layer). Both
restart tools and the read paths derive from it. See ADR-077 for the decision record.

**Owner invariants (locked):**
1. **Nothing is ever deleted.** "Reset" = hidden from current-experiment views (tombstone), never destruction.
2. **A restart re-anchors progress to genesis.** Restart Monday → site weight starts from Monday's weigh-in, habits from Monday, etc. (genesis-anchored date clamps).
3. **Clinical truths are date-independent everywhere** (labs, DEXA, genome, medication log).

## The four classes

| Class | Restart behavior | Read behavior | Examples |
|---|---|---|---|
| **cross_phase** | Never tagged, never wiped | Always fully visible (`include_pilot`) | labs, dexa, genome, **supplements/meds**, **`chronicling`** (frozen pre-platform archive), subscribers, profile, durable platform memories, **`calibration`** (prediction-resolution ledger, #530), **`VOICEFIDELITY#*`** (blind voice-fidelity scoreboard, #545) |
| **raw_timeseries** | Never wiped (facts kept) | Current views **genesis-anchored** (date-clamped to `EXPERIMENT_START`) | whoop, withings, strava, garmin, apple_health, eightsleep, habitify, macrofactor, hevy, notion/journal, food_delivery, sick_days, **measurements**, **day_grade**, state_of_mind, travel, interactions, exposures, temptations |
| **experiment_scoped** | **Tagged + wiped** (tombstone + `phase=pilot` + `cycle=N`) | **Phase-filtered** (pilot hidden) | insights, hypotheses, experiments, challenges, protocols, field_notes, discovery_annotations, **chronicle** (Wednesday narrative), habit_scores, character_sheet, computed_metrics/insights, adaptive_mode, circadian, anomalies, weekly_correlations, centenarian_progress, nutrition_review, ledger TOTALS, ai_analysis, **all COACH#\***, **ENSEMBLE#digest/disagreements**, **NARRATIVE#arc**, **coach_thread**, learning-category platform memories |
| **system_state** | Ignored entirely | Ignored (some GA on read) | journal_analysis (TTL cache), health_check, dropbox_tracker, hevy_id_map, routine_index, **email_log**, ENSEMBLE#influence_graph, PULSE, CACHE#, SUBSCRIBE#rate_limit, VOTES#, intelligence_quality, ROUTINE#, USER#system, dead partitions (composite_scores, google_calendar) |

## Cycle / reset-generation stamping

`phase=pilot` answers "hidden from the current run?"; **`cycle=N` answers "which run did this belong to?"** — turning the archive into a navigable sequence of past experiments whose cycle-over-cycle diffs are themselves data.

- Current cycle integer lives at SSM `/life-platform/experiment-cycle` (seed **2**, matching the `CYCLE#2#reentry` marker).
- At restart, the wipe stamps `cycle=<closing run>` on every experiment_scoped record it archives, then increments the counter for the new run.
- Going forward, experiment_scoped writers stamp `phase=experiment` + `cycle=<current>` at write time, so records self-describe even on partitions the tagger can't reach (COACH#, ENSEMBLE#, bare `USER#matthew`, NARRATIVE#arc).

## Decisions where the panel diverged or corrected the prior behavior (ADR-077)

| # | Record | Was | Now | Why |
|---|---|---|---|---|
| A | supplements/meds | hidden at restart | **cross_phase** | Medication history must stay continuously visible (interactions, washout) — clinical safety. |
| B | body tape measurements | hidden | **raw_timeseries** (genesis-anchor) | Waist is a body fact like weight; only "inches since baseline" is progress (already handled by the date clamp). |
| C | day_grade (back to 2023) | filtered | **raw_timeseries** (genesis-anchor) | Fresh cockpit via the clamp; keep the 1,045-day series for Day-Grade Replay. |
| D | `chronicling` (pre-platform archive) | hidden | **cross_phase** | The frozen "before" baseline that makes progress legible — never hide it. |
| E | email_log | hidden | **system_state** (GA read) | Immutable sent-mail archive; stop phase-hiding. |
| F | ledger | hard-DELETE txns | **tombstone + LIFETIME# aggregate**, reset TOTALS only | "Nothing is ever deleted"; lifetime-donated-dollars is the key accountability anchor. |
| G | vice_streaks | wiped inside habit_scores | **split**: current streak resets, all-time max/relapse promoted to a durable record | Mirrors food_delivery's preserved longest-ever streak. |

## Chronicle carry-forward (curated)

The Wednesday Chronicle (`SOURCE#chronicle`, written installments) is experiment_scoped, but the owner can **keep** selected issues across a restart: kept articles are re-dated to `genesis − N days` (staggered, preserving order), set `phase=experiment` + visible; the rest are tombstoned (`phase=pilot` + `cycle`). Repeatable via `restart_pipeline.py --keep-chronicle DATE#…[,DATE#…]`.

**Cycle-2 carry-forward (the 2026-06-07 decision):** keep `DATE#2026-02-28` *"Before the Numbers"*; archive the other 11.

## Known mechanism fixes folded into this work (ADR-077)

1. **coach_thread leak** — 279 April threads under a bare `USER#matthew` pk (tagger-blind) leaked into live coach prompts; the wipe targeted a phantom `SOURCE#coach_threads`. Fixed: write-time stamping + backfill + real wipe target.
2. **NARRATIVE#arc `phase="plateau"` collision** — the arc reused the reserved `phase` attribute → renamed to `arc_phase`.
3. **USER#matthew#MEMORY pk mismatch** — durable carve-outs aimed at the wrong pk; protection made explicit in the registry.
4. **`failure_pattern` vs `failure_patterns`** — the wipe missed the plural; registry covers both.
5. **Write-time stamping** — experiment_scoped writers stamp `phase`/`cycle` so the wipe can reach tagger-blind partitions at the next restart.
6. **Shared registry** — the tagger and wipe import `phase_taxonomy.py` instead of divergent hand-rolled lists (the root cause).
7. **Dead partitions** — composite_scores (ADR-025) + google_calendar (no writer) classified system_state and excluded.
8. **Standalone-writer stamping closed (#482/X-6, 2026-07-04)** — phase tagging was framework+hevy only; the six standalone writers depended on the manual reset sweep, so an untagged backfill could surface pre-genesis data as current (`phase_filter` passes `attribute_not_exists`). Now every standalone DDB-writing ingestion path stamps `phase` via the public `ingestion_framework.phase_for_date()`: HAE (`if_not_exists` in the merge update), notion, macrofactor, food_delivery (DATE#-keyed records), measurements. The apple_health XML writer was retired the same day (#474) rather than stamped. Pinned by `tests/test_now_remainder_batch.py`.

---

**Verified:** 2026-06-07 — `tests/test_phase_taxonomy.py` covers all 180 live record families (census of 27,083 items).
