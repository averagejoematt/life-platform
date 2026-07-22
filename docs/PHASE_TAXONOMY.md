# Phase Taxonomy — experiment-restart data semantics

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11

**Authoritative classification of every DynamoDB record type for experiment restarts.**
Machine-readable source of truth: `lambdas/phase_taxonomy.py` (bundled `lambdas/` tree). Both
restart tools and the read paths derive from it. See ADR-077 for the decision record.

**Owner invariants (locked):**
1. **Nothing is ever deleted.** "Reset" = hidden from current-experiment views (tombstone), never destruction.
2. **A restart re-anchors progress to genesis.** Restart Monday → site weight starts from Monday's weigh-in, habits from Monday, etc. (genesis-anchored date clamps).
3. **Clinical truths are date-independent everywhere** (labs, DEXA, genome, medication log).

## The four classes

| Class | Restart behavior | Read behavior | Examples |
|---|---|---|---|
| **cross_phase** | Never tagged, never wiped | Always fully visible (`include_pilot`) | labs, dexa, genome, **supplements/meds**, **`chronicling`** (frozen pre-platform archive), subscribers, profile, durable platform memories, **`calibration`** (prediction-resolution ledger, #530), **`VOICEFIDELITY#*`** (blind voice-fidelity scoreboard, #545), **`benchmarks`** (cut-benchmarking history, BENCH-1/ADR-089 — #918), **`coach_corrections`** (class-tagged corrections ledger, #1689/epic #1687) |
| **raw_timeseries** | Never wiped (facts kept) | Current views **genesis-anchored** (date-clamped to `EXPERIMENT_START`) | whoop, withings, strava, garmin, apple_health, eightsleep, habitify, macrofactor, hevy, notion/journal, food_delivery, sick_days, **measurements**, **day_grade**, state_of_mind, travel, interactions, exposures, temptations |
| **experiment_scoped** | **Tagged + wiped** (tombstone + `phase=pilot` + `cycle=N`) | **Phase-filtered** (pilot hidden) | insights, hypotheses, experiments, challenges, protocols, field_notes, discovery_annotations, **chronicle** (Wednesday narrative), habit_scores, character_sheet, computed_metrics/insights, adaptive_mode, circadian, anomalies, weekly_correlations, centenarian_progress, nutrition_review, ledger TOTALS, ai_analysis, **all COACH#\***, **ENSEMBLE#digest/disagreements/dispute** (dispute threads wired into the wipe by #918), **NARRATIVE#arc**, **coach_thread**, learning-category platform memories |
| **system_state** | Ignored entirely | Ignored (some GA on read) | journal_analysis (TTL cache), health_check, dropbox_tracker, hevy_id_map, routine_index, **email_log**, ENSEMBLE#influence_graph, PULSE, CACHE#, SUBSCRIBE#rate_limit, VOTES#, CHALLENGE_FOLLOWS (#918), intelligence_quality, ROUTINE#, USER#system, dead partitions (composite_scores, google_calendar) |

## Cycle / reset-generation stamping

`phase=pilot` answers "hidden from the current run?"; **`cycle=N` answers "which run did this belong to?"** — turning the archive into a navigable sequence of past experiments whose cycle-over-cycle diffs are themselves data.

- Current cycle integer lives at SSM `/life-platform/experiment-cycle` (seed **2**, matching the `CYCLE#2#reentry` marker).
- At restart, the wipe stamps `cycle=<closing run>` on every experiment_scoped record it archives, then increments the counter for the new run.
- The tagger-blind intelligence output writers stamp their own provenance at write time via `phase_taxonomy.experiment_stamp()` (#1233), so records self-describe without relying solely on the reset-time wipe: COACH#* (OUTPUT#/TRACE#/VOICE#/COMMITMENT#/STANCE#/…), ENSEMBLE#* and COACH#computation RESULTS# carry `phase=experiment` + `cycle=<current>`; **NARRATIVE#arc carries `cycle=<current>` only** — its `phase` attribute is the narrative-arc STATE, not the taxonomy phase, so it's left intact. Other experiment_scoped writers (e.g. daily INSIGHT#, bare `USER#matthew` coach_thread rows) still lean on the wipe/tagger for provenance. The stamp is read-safe: `phase=experiment` matches the `with_phase_filter` current-phase clause, so a stamped row stays visible exactly as an unstamped one did.

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
9. **Reset-protocol clean sweep (#918, 2026-07-10)** — three registry gaps closed ahead of the cycle-5 reset: `benchmarks` classified **cross_phase** (proven cut-benchmarking history must survive resets), `CHALLENGE_FOLLOWS` classified **system_state**, and `ENSEMBLE#dispute` threads wired into the wipe surface.
10. **Registry made total (#930/#951, 2026-07-11)** — every live DDB family now classifies. SOURCE additions: `weight_episodes`/`training_reference` **cross_phase** (BENCH-1 14-year reference, per the writer's contract), `macrofactor_meals`/`training_notes` **raw_timeseries** (derived projections of raw facts — they follow their parent partitions), `coach_gen_cache`/`ingest_liveness`/`personal_baselines`/`experiment_suggestions`/`email_digest`/`deletion_log` **system_state**, plus writer-backed `food_responses`/`life_events`/`ruck_log` **raw_timeseries**. Ops pk rules: `EVALUATOR#*`/`RATE#*`/`BOARDSESS#*`/`CANARY#*`/`SYSTEM#*`/`OAUTH#*` **system_state**; `PERSONA#*` (Elena/Margaret narrator state) **cross_phase** — deliberately spans cycles; wiping personas at a reset would be a new decision needing its own wipe wiring. Same PR: the resurrect path (`restart_chronicle_handler.untombstone_and_redate`) now re-stamps `cycle=<current>` so a carried-forward chronicle can't keep its wipe-era cycle stamp, and `restart_ledger_reset` receives the **closing** cycle explicitly from the pipeline (the SSM bump precedes it, so an SSM read there mislabeled CYCLE_TOTALS# with the new cycle).
11. **`coach_corrections` registered (#1689, 2026-07-22)** — the new class-tagged corrections ledger (`USER#matthew#SOURCE#coach_corrections` / `CORRECTION#<date>#<id8>`, `lambdas/coach_corrections.py`) classified **cross_phase**: same rationale as `calibration`/`EVALRET#*` — a correction is a statement about the coaching machinery's error, not a property of the current run, so it must survive resets for the prompt-memory/gate/pattern-extraction downstream stages (#1690/#1691/S5/S6) to keep the same error class from recurring. Foundation story only — no writer wired yet.

## Pending classification (#917)

The coach check-in records (`pk COACH#<id>_coach` / `sk CHECKIN#<date>#<uuid8>`, shipped 2026-07-10) currently **inherit the COACH#\* default (experiment_scoped)**. The recommended class is **cross_phase** — qualitative Q&A history is exactly what ought to survive an experiment reset (see the #917 PR body). The one-line registry addition in `lambdas/phase_taxonomy.py` is a deliberate follow-up; until it lands, a reset will tombstone CHECKIN# rows along with the rest of the coach tier.

---

**Behavioral verification (#1559):** the taxonomy decides what a reset wipes/keeps;
`deploy/restart_integration_check.py` proves the platform still FLOWS afterwards (ingestion,
compute Day-0 shapes, serving surface, ops legs) — see `docs/RUNBOOK.md` "Experiment restart"
for when each leg runs. State verification stays with the `restart_verify*.py` family.

**Verified:** 2026-06-07 — `tests/test_phase_taxonomy.py` covers all 180 live record families (census of 27,083 items).
