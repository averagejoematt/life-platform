# Claude Code Build Prompt — Training Notes Feedback Loop (v1)

> **Destination in repo:** `docs/specs/CLAUDE_CODE_PROMPT_HEVY_NOTES_v1.md`
> **Pairs with design brief:** `docs/SPEC_HEVY_NOTES_FEEDBACK_LOOP_2026-06-21.md` (read it first — invariants, taxonomy, schema, board rationale).
> **Scope of this prompt:** Phase 0 (measure) + Phase 1 (deterministic+Haiku extractor, exercise-keyed projection, read tool, pain elevation). Phase 2 (loop-back into descriptions, pattern detection) is a separate prompt after Phase 1 is eyeballed privately.
> **Date:** 2026-06-21

---

## CONTEXT (do not re-derive)

Matthew writes freeform notes on individual Hevy exercises. They sync (per-exercise `notes`, per-workout `description`) but evaporate after one read — no structured, queryable, *progressive* view. Build a **derived note-signal layer**: a projection over the **untouched** raw Hevy notes, keyed by exercise so the per-exercise arc is one Query, with a deterministic safety floor for pain and a bounded Haiku pass for semantic signals.

This is the **same pattern as the meal-grouping layer** (`docs/SPEC_MEAL_GROUPING_2026-06-19.md` / `CLAUDE_CODE_PROMPT_MEAL_GROUPING_v1.md`) — derived projection, raw sovereign, deterministic-first, LLM tail bounded by cache + cap, frozen-as-data + correctable. Reuse its conventions and module shape.

### Hard invariants (tests must enforce)

1. **Raw untouched** — write ONLY to `SOURCE#training_notes`. A test asserts zero writes to the raw Hevy workout partitions.
2. **Inferred + labelled** — every signal carries `confidence` + `extracted_by`.
3. **Notes never overwrite numbers** — `rpe_caveat`/qualifiers are overlays the coach reads; raw logged RPE/load is never mutated.
4. **Conservation** — every non-empty raw note → exactly one signal record; on LLM failure keep `note_raw` + deterministic signals, set `degraded:true`; never drop a note.
5. **Pain never missed** — deterministic pain lexicon fires independently of the LLM and is authoritative for `pain_flag`; the LLM can add but never clear it.
6. **Private** — no public/website surface in this build.

---

## PHASE 0 — MEASURE (no production code; report findings, then stop for Matthew's lock)

1. **Sync fidelity.** Confirm the Hevy ingest reliably carries per-exercise `notes` and per-workout `description`. Pull 2026-06-20 workout `dc3e3b10-...` and confirm the 5 non-empty notes are present in raw.
2. **(Dropped 2026-06-21 per lock.)** No edit-resync / retroactive handling — this is real-time feedback; after-the-fact corrections go through chat. Trigger is **on-ingest, right after the session**. Skip this test.
3. **Taxonomy + deterministic patterns.** From the seed corpus (the 5 notes in §3 of the brief) draft: the frozen `signals` enum, the regex/keyword set for the deterministic classes (`progression` numeric `level`/`load`; `equipment_setup` keywords; `logging_quirk` keywords), and the **pain lexicon** (over-inclusive: sharp, twinge, tweak, pinch, niggle, "joint", knee/elbow/shoulder/wrist/hip/lower-back + pain/hurt). Red-team the pain lexicon for misses.
4. **Output:** findings + proposed frozen taxonomy + pain lexicon + the edit-resync answer. **Stop. Do not build Phase 1 until Matthew locks §13 of the brief.**

---

## PHASE 1 — BUILD (deterministic core first, against fixtures, before any I/O or model call)

Build order is a gate. Prove the pure core on fixtures before wiring storage or Haiku.

### 1. Pure extractor module — `mcp/` or `lambdas/` per existing layout (no I/O)

- `normalize_exercise_key(workout_exercise) -> template_id` (Hevy `template_id`, stable; carry `exercise_name` for display).
- `deterministic_pass(note_text) -> list[signal]` — numeric `level`/`load` extraction; `equipment_setup` + `logging_quirk` keywords. Pure, no model.
- `pain_lexicon_hit(note_text) -> bool` — the authoritative pain net. Pure.
- `note_hash(note_text) -> sha256`.
- `merge_signals(deterministic, llm) -> record` — dedupe by class; `pain_flag = pain_lexicon_hit OR any llm pain`; deterministic pain can never be cleared.

**Fixtures (must pass with ZERO I/O and ZERO model calls):** the 5 seed notes →
- Standing Calf Raise → `progression(rom:full, aid:platform)` + `form_technique(balance)` + `equipment_setup`.
- Seated Calf Raise → `rpe_caveat` (effective calf RPE < logged 9; raw RPE untouched) + `equipment_setup(new_machine)`.
- Pallof Press → `sentiment_adherence(positive, novel)`.
- Farmers Walk → `limiter(grip_before_strength)` + `logging_quirk(distance=steps)`.
- Cycling → `progression(level:10, character:flat)`.
- A synthetic pain note ("left knee felt sharp on the last set") → `pain_flag=true` via the **deterministic** net with the LLM stubbed off.
- Conservation: 5 non-empty notes → 5 records; 4 empty exercises → 0 records.

### 2. Haiku pass — `claude-haiku-4-5`, bounded (one swappable module)

- Input: single note text + the frozen taxonomy enum. Constrained JSON out (`[{class, summary, value?, confidence}]`), `max_tokens` tight (~64), minimal system prompt.
- **Hash-cache**: key on `note_hash`; reuse the cached extraction across re-imports; re-extract only on hash change.
- **Fail-safe**: on exception or monthly-cap breach → `degraded:true`, keep `note_raw` + deterministic signals, do NOT drop (Invariant 4). Monthly call cap (default 300) + CloudWatch alarm.
- Encapsulate the endpoint so the future Bedrock swap touches one file (match the meal-namer module pattern).

### 3. Projection writer (single-table, no GSI — ADR-005)

- Source label **`training_feedback_loop`** (locked).
- `pk = USER#matthew#SOURCE#training_notes#EXERCISE#<template_id>`, `sk = DATE#YYYY-MM-DD#WORKOUT#<workout_id>`.
- Record fields per brief §5. Idempotent upsert by the stable `sk`. Correction overlay at `sk = …#WORKOUT#<id>#CORRECTION`, wins on read, survives recompute.
- Test: re-running extraction over the same workout produces no duplicates; a correction overlay survives a recompute.

### 4. Read tool — `get_exercise_notes`

- Signature: `get_exercise_notes(exercise OR template_id, lookback_days?=180)`.
- Returns the date-sorted per-exercise timeline: `[{date, workout_uid, note_raw, signals, pain_flag, sentiment, degraded}]`, plus a `latest_progression` convenience field (most recent `progression.value`) for the Phase-2 description generator to consume.
- Resolve a human exercise name → `template_id` via the same normalize fn (so "calf raise" works, not just the hex id).
- **MCP registration discipline:** tool fn defined BEFORE `TOOLS={}`; implementing fn in the SAME commit as registration; `pytest tests/test_mcp_registry.py` green before any MCP deploy.

### 5. Pain elevation (§7 of the brief)

On `pain_flag`: (a) `save_insight` tags `["training","pain",<exercise>]`; (b) annotate the training coach thread; (c) ensure `get_exercise_notes` surfaces `pain_flag` prominently. No confidence floor on pain. A correction-overlay dismissal of a false positive persists.

### 6. Freshness / silent-failure hook

Surface `degraded` rate + an alert if N consecutive recent sessions with non-empty notes produce only degraded records (extractor dark) — hook into `get_freshness_status` (`mcp/tools_labs.py`), mirroring the meal-layer `daily_summary` drift guard.

### 7. Backfill

One-time resumable batch over existing workouts with non-empty notes (trivial now — ~1 session — but write it resumable for growth). Use the Batch API path if volume ever warrants; not needed at current scale.

---

## ADDITIONS (locked 2026-06-21)

8. **`deviation`** — pure diff of **pushed routine vs performed Hevy workout** (`get_workout_detail`): added/removed/swapped exercises, set/load deltas. No LLM. Emit per-session under the same exercise-keyed projection. Strong long-term preference/capacity signal.
9. **`rest_adherence`** — prescribed vs actual rest per exercise, **iff Phase 0 confirms Hevy exposes per-set rest/timestamps**; else defer to the qualitative notes path. Bidirectional (coach may prescribe rest discipline as the focus).
10. **Recovery-conditional descriptors** (programming, not extraction) — routine builders write recovery-branched cues into exercise notes ('YELLOW → level 10; GREEN → intervals 6↔8') so a night-before routine adapts to the morning reading; bike levels source from the `progression` timeline.
11. **Out of scope / separate ticket** — the `get_muscle_volume` staleness + core-mapping bug (brief §14.4) is a coaching-engine defect fixed independently of this build.

## DEPLOY (Matthew runs in terminal — never via MCP)

- Lambda(s): `bash deploy/deploy_lambda.sh` (auto-reads handler config; never hardcode zip names; 10s between sequential deploys; tool fns BEFORE `TOOLS={}`).
- MCP changes: `bash deploy/deploy_mcp_split.sh` (packages full `mcp/` dir).
- Run `pytest tests/test_mcp_registry.py` green before any MCP deploy.
- New deploy scripts → `deploy/`, `chmod +x` or invoke `bash deploy/<script>.sh`; tell Matthew which.

## OUTPUT OF THIS BUILD

Phase 0 findings + (after lock) Phase 1: pure extractor + fixtures green → Haiku module + cache + cap → projection writer → `get_exercise_notes` → pain elevation → freshness hook → backfill. Deterministic core proven against the 5-note fixture (incl. the pain net with the model stubbed, the `rpe_caveat` not-overwriting-raw test, and the conservation test) BEFORE any I/O or model call. Do NOT build Phase 2 (loop-back, pattern detection) in this pass — show Phase 1 working privately first.
