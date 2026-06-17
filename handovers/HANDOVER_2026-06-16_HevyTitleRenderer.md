# HANDOVER — 2026-06-16 (PM) · Hevy title renderer (ADR-088) + AI cost telemetry (G1/G2)

> Two independent PRs this session, both **code-complete + tested, deploys pending**:
> **#142** AI cost telemetry/alarm (G1/G2), and the **Hevy `Phase - Type - N - Y`
> renderer** (ADR-088, this branch). Plus the cost one-pager `docs/COST_FORECAST_2026-06.md`.

---

## 0. Phase-0 finding (Hevy work order — the 3-line verdict)
1. **Shipped, but with a dry-run leak + wrong semantics.** The `Phase - Type - N - Y` convention
   *did* ship (`routine_title` + `hevy_compiler._resolve_title`, commit 2329aea3). But
   **`_action_dry_run` never passed `title_context`**, so its preview showed the raw `ir.title`
   placeholder (`Push — {date}`) — the "regression" the work order saw was a misleading dry_run.
   And the 2026-05-31 amendment had anchored N/Y to `EXPERIMENT_START_DATE` (N never resetting).
2. **Source of `Push — {date}`:** `routine_generator.py:331` + `tools_hevy_routine.py:571` set
   `ir.title` to the date placeholder; it leaks whenever `title_context` isn't applied.
3. **The work order's seed assumptions were off:** performed records carry **no archetype**
   (can't count performed-by-type without parsing titles — forbidden); the routine-index is noisy
   (dup drafts + future-dated pushes); and the first post-reset performed push is dated **2026-06-16**,
   not 06-15. Resolved below.

## 1. What shipped (ADR-088 — supersedes the 2026-05-31 amendment)
- **N** = PERFORMED workouts of this type since `current_started` (+1), resets per phase.
  **Y** = distinct PERFORMED workouts since `reset_epoch_date` (+1), deduped by `workout_uid`
  across Hevy + MacroFactor. Both honest — skipped/planned never inflate.
- **Type resolved without title-parsing:** stored `archetype` sticker → else nearest pushed routine
  by date (the index has `archetype`). Counting *performed* workouts (deduped) sidesteps the
  index noise entirely. `hevy_common.normalize_workout` now preserves Hevy's `routine_id` as
  `hevy_routine_id` for a future exact link.
- **dry_run fixed** to render the convention (truthful preview); dry_run + commit share
  `_resolve_title_inputs`. **`force_title` lockdown:** caller `title` ignored unless
  `force_title=true` (warns); tool description + schema say "don't pass a title."
- **config/training_phases.json:** added `reset_epoch_date`; `current_started` + `reset_epoch_date`
  = **2026-06-16** (the actual first post-reset performed push).
- **Seed outcome (correct, not a bug):** next push → `Foundation - Push - 2 - 2`,
  next pull → `Foundation - Pull - 1 - 2` (the June-16 push is already #1 by hand).

## 2. Tests
`tests/test_routine_title_counters.py` (13 — pure: resolve, seed Push-2-2/Pull-1-2,
skip-doesn't-inflate, dedup, contract regex) + rewritten `tests/test_routine_title.py`
(per-phase N reset, performed-derived). Full suite **1884 passed** (2 pre-existing live-AWS
integration failures unrelated: `test_i9_dlq_empty`, `test_i15_reserved_concurrency_guard`).

## 3. Deploy ledger — ⚠️ NOTHING DEPLOYED (author did not deploy, per work order)
| Change | Deploy | Status |
|---|---|---|
| ADR-088 — routine_title + hevy_common (layer) + registry + tools_hevy_routine (MCP) + config | **RUNBOOK §"Hevy Title Renderer — Deploy Steps (ADR-088)"** — S3 config upload → `build_layer.sh` → cdk Core+consumers → MCP special build | ⏳ PENDING |
| **#142** — G1 chokepoint cost telemetry + G2 daily-spend alarm | `bash deploy/build_layer.sh` + `cd cdk && npx cdk deploy --all` (layer + alarm) | ⏳ PENDING (separate branch/PR) |

**Verify after deploy:** draft_custom → dry_run → `wire_body.title` reads `Foundation - Push - 2 - 2`
(NOT `Push — <date>`); a title without `force_title` is ignored (warning in response).

## 4. Open micro-decision (flagged, default chosen — don't block)
N counts *performed* workouts, type resolved by nearest-date routine. If a deviated session ever
mis-tags, the durable fix is to populate the `archetype` sticker at ingestion from the now-preserved
`hevy_routine_id` (exact link). Deferred — the date heuristic suffices for one-type-per-day cadence.

## 5. Out of scope (untouched, as instructed)
Cron / autoreg gates, Character-Sheet training pillar, PR-celebration, streak art, chronicle hooks.
Phase advancement is config-only (flip `current` + bump `current_started`, re-upload to S3).

**Verified:** 2026-06-16 (PM).
