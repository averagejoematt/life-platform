# WORKORDER — Hevy commit hardening + notes-fetch gap

**Status:** OPEN · **Priority:** P1 (commit path silently blocks authored routines)
**Filed:** 2026-06-21 · **Owner:** Claude Code

## Context
Night-before authoring is the dominant use case (5am lift, no morning adjust).
On 2026-06-21 a well-formed custom Push routine 400'd on commit five times; it
only succeeded after stripping rep-ranges, the `drop` set type, and emoji from
notes. Separately, `get_workout_detail.notes` is empty for some workouts but
populated for others, disagreeing with the note-extractor's "noted sessions"
count. Both undermine trust in the coaching pipeline.

Reference: coaching log insight `2026-06-22T01:16:58`.

## Problem A — manage_hevy_routine commit returns HTTP 400 (P1)
Reproduced this session:
- routine `d49c0dc68cfa4289b78324ad44bee0d0` (rep_range + `drop` set + emoji notes) -> 400, twice.
- routine `f2e0a92d44a643f8b6c6fa3b16c98fd5` (same shape + auto-created exercise) -> 400, twice.
- routine `3a29ed7f42104fce9ef2cbdfbf872d1f` (fixed reps, no drop, plain-text notes) -> COMMITTED (hevy id 7ad52512-e1ad-4cff-bc49-d7aa76d17ddd).

So the offending element is one (or more) of: `rep_range` serialization, the
`drop` set type, or emoji/unicode in notes.

### Tasks
1. **Surface Hevy's real error.** The MCP Lambda currently returns a bare
   `HTTP Error 400: Bad Request`. Capture and log/return Hevy's response body so
   the rejected field is visible. (Without this we are guessing — as happened here.)
2. **Set-type enum mapping.** Map internal set types to Hevy's accepted enum on
   the commit path. Confirm Hevy's set: likely `normal | warmup | failure | dropset`
   (we sent `drop`). Translate, don't pass through.
3. **rep_range serialization.** Verify the routine POST shape for ranged reps vs a
   single `reps` target; fix or document the supported form.
4. **Note sanitisation.** Strip/transliterate unsupported unicode (emoji) from notes
   before POST, OR confirm Hevy accepts it and rule it out as the cause.
5. **Pre-commit validator.** dry_run should fail loudly naming the offending field,
   so a bad routine never reaches a silent 400 at commit.
6. **Newly-created custom exercise timing.** Confirm whether referencing a
   just-created custom exercise template in the same-session routine POST can 400
   (eventual consistency); if so, add a guard/retry.

### Acceptance
- A routine containing rep-ranges + a dropset + emoji notes either commits cleanly,
  or dry_run rejects it naming the exact offending field. No more opaque 400s.

## Problem B — get_workout_detail notes-fetch gap (P2)
- `hevy:ca3e7725-6df6-4c16-a332-da5e3dc45630` (06-16 Push): empty notes on all 8 exercises.
- `hevy:36bd9061-190b-43d4-acfd-515f5bb85dd0` (06-21 Legs): full notes + RPE present.
- `get_freshness_status` reports note-extractor healthy, 8 noted sessions.
These disagree.

### Tasks
1. **Phase 0 diagnostic (read-only, no schema change).** For the last ~14 Hevy
   workouts, trace the note field across the pipeline: raw S3 -> normalized DDB
   record -> `get_workout_detail` output -> extractor's noted-session count. Identify
   where notes drop.
2. Determine root cause: ingestion/normalization loss vs read-path divergence
   (extractor and get_workout_detail reading different fields/paths).
3. Report findings before proposing any fix.

### Acceptance
- A single source of truth on which workouts genuinely carry notes, and the precise
  drop point identified. Remediation scoped in a follow-up.

## Out of scope
- Schema changes (pending Problem B diagnostic).
- Coach-thread phantom-data handling — addressed via COACH_SESSION.md coaching
  guardrails, not code.
