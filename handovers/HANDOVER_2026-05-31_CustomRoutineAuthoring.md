# HANDOVER — 2026-05-31 (Saturday night — Custom routine authoring, ADR-069)

**Previous handover:** `handovers/HANDOVER_2026-05-31_PerExerciseNotes.md` (per-exercise notes + final reset).
**This session covers:** ADR-069 — a `draft_custom` action so a hand-designed session can be pushed to Hevy from chat, plus a resolve-by-title fallback and three new catalog movements.
**HEAD on push:** `73f0daf` on branch **`adr-069-custom-hevy-routine`** (NOT yet merged to `main`). **Layer v70 published; MCP live on v70 with ADR-069 code; catalog synced to S3.**

> ⚠️ **Production runs ADR-069 but `main` does not yet.** The work is committed + pushed on `adr-069-custom-hevy-routine` only. Open/merge the PR to bring `main` in sync with production:
> https://github.com/averagejoematt/life-platform/pull/new/adr-069-custom-hevy-routine

---

## State at handover

| Surface | Status |
|---|---|
| Hevy write-loop (chat path) | **LIVE on v70 with ADR-069.** `manage_hevy_routine` now has 10 actions (added `draft_custom`). |
| `draft_custom` | **LIVE + smoke-verified in prod.** Authors an IR from an explicit exercise/set/weight list; flows through the existing `dry_run → commit` chain. |
| Hevy write-loop (cron) | DISABLED — EventBridge rule + SSM `/life-platform/hevy/cron_enabled=false`. Unchanged. |
| Add-load autoreg | OFF — SSM `/life-platform/hevy/autoreg_add_load_enabled=false`. Unchanged. |
| Shared layer | **AWS v70 published.** Only `life-platform-mcp` repointed to v70 (surgical). Other 35 layer-using Lambdas remain on v69 — intentional (see "Surgical deploy" below). `cdk/stacks/constants.py:SHARED_LAYER_VERSION = 70`. |
| Movement catalog | **S3 synced — 21 movements** (was 18; +barbell_bench_press, db_shoulder_press, reverse_pec_deck). |
| EXPERIMENT_START_DATE | 2026-06-01 — unchanged from prior session. |
| Branch / main | `main` does NOT have ADR-069 yet. Merge the PR. |

---

## What ADR-069 actually does

**Problem:** the only authoring action, `draft`, runs the deterministic volume-landmark programmer and never accepted an exercise list. A hand-designed session (e.g. 22-set push day ramping to 185 bench) could not be pushed from chat at all — the browser and manual routes both failed in practice.

**`draft_custom` action** (`mcp/tools_hevy_routine.py`): takes an explicit `exercises` list and builds a normal `RoutineSpec` IR with `source_action="draft_custom"`. Because it stops at the same IR, `dry_run` / `commit` work unchanged — **one write path preserved** (ADR-066 §1 intact).
- Each exercise: `movement_key` **or** human `title`/`name` (matched to catalog titles), `sets[{weight_lbs|weight_kg, reps|rep_range_start/end, type, count}]`, `rest_seconds`, `superset_id` (same int = superset/tri-set), per-exercise `notes`.
- `weight_lbs` → kg conversion (×0.45359237, 4dp). `count:N` repeats a set N times.
- **Loads are taken verbatim — the platform does not compute them.** ADR-068's "LLM never computes" governs the *deterministic* path only; `draft_custom` is the user authoring their own session.
- No silent caps: returns a `warnings[]` advisory if `total_sets` exceeds `session_set_ceiling` rather than truncating.

**Resolve-by-title fallback** (`_make_resolver()`): tries `hevy_template_cache.resolve_movement`, then falls back to `reconcile_custom` which searches the **live Hevy template list by exact title** and caches the real id. New catalog movements therefore ship their exact Hevy *title* and **no** `hevy_template_id_hint` — a hand-transcribed id could silently mis-map; a title miss instead fails **loudly** (`MovementUnmappable`). Used by both `dry_run` and `commit`.

**Catalog +3 movements** (`config/movement_catalog.json`): `barbell_bench_press` ("Bench Press (Barbell)"), `db_shoulder_press` ("Shoulder Press (Dumbbell)"), `reverse_pec_deck` ("Rear Delt Reverse Fly (Machine)") — title-only.

**WHY-note** (`lambdas/routine_title.py:format_why_note`): new `source_action == "draft_custom"` branch surfaces the user's own first note line instead of a generator-flavored rationale.

**Naming convention unchanged:** at `commit`, custom routines still render the ADR-067 title `<Phase> - <Type> - <N> - <Y>` with N/Y auto-incrementing — provided the caller passes `archetype` (e.g. `"push"`); default is `"custom"`. Verified: a push session with 2 prior Push routines + 7 performed workouts → `Foundation - Push - 3 - 8`.

---

## Surgical deploy (why MCP is on v70 and everything else is on v69)

`routine_title.py` is a **layer** module, so the WHY-note change needs a layer rebuild. Rather than `cdk deploy --all` (which would push unrelated stack drift — the I19 integration test already shows site-api is stale vs source), the layer was published directly and **only** the MCP function repointed:

1. `bash deploy/build_layer.sh` (verified it produces exactly the live v69 module set — no drops).
2. `aws lambda publish-layer-version … life-platform-shared-utils` → **v70**.
3. `cdk/stacks/constants.py:SHARED_LAYER_VERSION` 69 → 70.
4. `aws lambda update-function-configuration --function-name life-platform-mcp --layers …:70`.
5. MCP code redeploy (special build: `zip mcp_server.py mcp_bridge.py` + `zip -r mcp/`).
6. `aws s3 cp config/movement_catalog.json s3://matthew-life-platform/config/`.

**Safe because** `routine_title.py` is consumed only by `life-platform-mcp` and the parked/disabled `hevy-routine-cron`; the change is additive/backward-compatible. A future `cdk deploy --all` will move all functions to v70 harmlessly and is the way to reconcile the split.

**Backup:** previous S3 catalog saved to `/tmp/movement_catalog_prev.json` during deploy (18-movement version) — already superseded; no action needed.

---

## Verification (done)

- Offline: full suite **1424 passed** (4 new ADR-069 tests). 2 pre-existing failures are live-AWS integration tests (I17 character-sheet recency, I19 site-api `started_date` staleness) — unrelated to this change.
- Import smoke on v70: EventBridge invoke → cache warmer `COMPLETE`, function `Active`.
- **End-to-end in prod:** `draft_custom` (barbell_bench_press + cable_chest_fly) → `dry_run` resolved `barbell_bench_press` **by title against the live Hevy API → `79D0BB3A`**, `count:2` expanded to 2 sets. Smoke draft archived (never pushed to Hevy).

---

## Open items / follow-ups

1. **Merge the PR.** `main` is behind production until then.
2. **Optional: `cdk deploy --all`** to move the other 35 Lambdas from layer v69 → v70 (cosmetic; only matters if/when `routine_title.py` is consumed elsewhere). Watch for unrelated stack drift if you do.
3. **Title accuracy for the 3 new movements.** If Hevy's exact built-in name for DB shoulder press or reverse pec deck differs from the strings used, the first `dry_run` on that movement fails loudly (`MovementUnmappable`); fix the `title` in `config/movement_catalog.json` and re-sync to S3 — no code redeploy. (`barbell_bench_press` already confirmed = `79D0BB3A`.)
4. **The real "Push — Day 1" (2026-06-01)** was NOT committed to Hevy — left for the user to trigger `draft_custom → dry_run → commit` (commit creates the routine; Hevy has no delete, only archive).

---

## Files touched (commit `73f0daf`)

```
mcp/tools_hevy_routine.py        (draft_custom action + _make_resolver resolve-by-title)
mcp/registry.py                  (schema: draft_custom + exercises/archetype/title/notes params)
lambdas/routine_title.py         (format_why_note custom branch)   [LAYER module → v70]
config/movement_catalog.json     (+3 movements; synced to S3)
cdk/stacks/constants.py          (SHARED_LAYER_VERSION 69 -> 70)
tests/test_tools_hevy_routine.py (4 new tests)
docs/DECISIONS.md                (ADR-069)
CLAUDE.md                        (ADR range, layer version note)
handovers/HANDOVER_2026-05-31_CustomRoutineAuthoring.md  (this doc)
handovers/HANDOVER_LATEST.md     (re-pointed)
```
