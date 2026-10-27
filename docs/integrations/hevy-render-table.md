# Hevy render table: where every charter prescription field shows in the app

**Issue:** #5083, #5428 (epic #5050) · **Verified:** 2026-10-27 · **Machine twin:** `lambdas/training/hevy_render.py` (`RENDER_TABLE`), pinned to this table by `tests/test_hevy_render_5083.py`
**Status:** the table, the ordering rule and the `render_check` are built; the live proof (a committed routine opened in the app) is the owner's (§5)

A field can pass the Hevy API and still never reach the gym floor. #3938 is the precedent: `routine.notes` was accepted on every write and never read back. Hevy's routine wire has **no field** for a reason, an RPE, a bike level or a treadmill speed (RPE is logged on *performed* sets only). So those fields ride in the exercise's **Pinned Routine Note** (`routine.exercises[].notes`, `hevy_note_types.PINNED_ROUTINE_NOTE_FIELD`). Only warm-up sets, the rep range, rest and supersets have native homes. `lambdas/training/hevy_compiler.py` stays the only module that writes the wire.

## 1. The table

`home`: **native** = a Hevy field built for it · **note** = the Pinned Routine Note fallback · **not_shown** = carried in the IR only, by design · **deferred** = no producer yet.

| field | issue | producer | home | wire field | where the app shows it | fallback |
|---|---|---|---|---|---|---|
| `session_note` | #3938 #5069 | `routine_title.format_why_note` | note | `routine.exercises[0].notes (head)` | first exercise's Pinned Routine Note, first line | routine.notes never reads back (#3938), so the session line heads exercise 0's note; kept under the window |
| `progression_reason` | #5052 | `load_progression.next_prescription` | note | `routine.exercises[].notes` | that exercise's Pinned Routine Note, first line | no reason field on the routine wire; leads the exercise's own note |
| `stall_step` | #5057 | `load_progression.stall_step` | note | `routine.exercises[].notes` | that exercise's Pinned Routine Note, first line | no reason field on the routine wire; leads the exercise's own note (chat drafts: 'Step due:') |
| `rotation_note` | #5075 | `none yet (#5075 deferred)` | deferred | `routine.exercises[].notes (planned)` | that exercise's Pinned Routine Note (planned) | when built: leads the note after the progression reason |
| `cardio_level` | #5048 #5076 | `cardio_note.compose (line 1)` | note | `routine.exercises[].notes` | the cardio exercise's Pinned Routine Note, line 1 ('level N') | no level field on a routine set; line 1 of the note |
| `cardio_speed` | #5048 #5076 | `cardio_note.compose (line 1)` | note | `routine.exercises[].notes` | the cardio exercise's Pinned Routine Note, line 1 ('at S mph') | no speed field on a routine set; line 1 of the note |
| `cardio_rpe` | #5048 #5076 | `cardio_note.compose (line 1)` | note | `routine.exercises[].notes` | the cardio exercise's Pinned Routine Note, line 1 ('RPE a-b') | RPE is logged on performed sets only; line 1 of the note |
| `cardio_duration` | #5048 | `the cardio block's sets` | native | `routine.exercises[].sets[].duration_seconds` | the set row's time column (also 'N min' on note line 1) | - |
| `warmup_sets` | #5049 | `warmup_sets.attach_warmups` | native | `routine.exercises[].sets[].type = warmup` | set rows marked W, ahead of the working sets; 'Warm up:' clause in the note | - |
| `effort_ceiling` | #5058 | `effort_ceilings (via routine_title / program_structure cues)` | note | `routine.exercises[].notes` | 'RPE a-b' in the session line and the slot cue | no RPE field on the routine wire; the note |
| `rep_range` | #5052 | `the slot's rep scheme` | native | `routine.exercises[].sets[].rep_range` | the set row's reps column ('6-10') | - |
| `rest_seconds` | - | `the block's rest` | native | `routine.exercises[].rest_seconds` | the exercise's rest timer | - |
| `superset_id` | - | `the block's superset` | native | `routine.exercises[].superset_id` | the exercises grouped as a superset | - |
| `minimum_session` | #5088 | `disruption.to_routine` | note | `routine.exercises[0].notes (head) + routine.exercises[].notes` | the session line and each exercise's 'Minimum:' cue | the title is the convention's at commit (Phase - Type - N - Y); the label rides the session line |
| `charter_version` | #5068 #5085 | `training_charter.charter_version` | not_shown | `none (inputs_snapshot.charter_version + inputs_snapshot.nightly_predraft.charter_version)` | not shown in any Hevy note or footer; the IR and the pre-draft's draft mark carry it | - |

## 2. The ordering rule (so a reason line is never the part a cut lands on)

1. **Exercise 1's note opens with the session block** (`routine_title.format_why_note`; #5428, `docs/coaching/HEVY_NOTE_STANDARD.md` §3.1): the session line "Upper heavy · RPE 8–9 on big lifts", the low-energy line and the load rule, then a blank line. A minimum or travel session's label rides here, because the title is the `Phase - Type - N - Y` convention at commit.
2. **Each exercise's own note opens with its prescription line:**
   - the progression or stall-step reason (`routine_generator._progress_block` and `draft_custom_session.attach_step_due` put it first), for example "+5 lb to 184.9 lb: 2 top sets at the top of 6-10, RPE <= 9, 10-14 and 10-16; reps back to 6."
   - the cardio dose line (`cardio_note` line 1), for example "Treadmill · 30 min · incline 8% at 2.5 mph walk · RPE 4–6, full sentences"
   - the minimum-session cue (`disruption._cue`)
3. **Everything else comes after:** the history cue, the warm-up clause ("Warm up: band pull-aparts, then the ramp sets."), the wake-recovery session block (`hevy_render.place_after_prescription`, called by `tools_hevy_routine._apply_recovery_adaptation` on the daily draft path, puts it after exercise 1's prescription line), the branch menu (`hevy_compiler._place_routine_note` puts it after exercise 1's own note), and the critics' block (`tools_plan._place_block_on_first_exercise` appends it).

On exercise 1 the result is: the session line, then exercise 1's prescription line, then the recovery block, then the menus. A cut lands on a menu, never on a reason. `tests/test_hevy_render_5083.py` runs the daily path's own pass (`_apply_recovery_adaptation`) over the fixture, so the test reads the real wire.

One path keeps its block ahead of the reason on purpose: the standing-constraint gate (`draft_standing_constraint.apply_gate`, #5000) still heads exercise 1's note, because it is the check made before the first set. When that path runs, `render_check` reports the reason as `not_leading`. That is the honest result, not a false alarm.

## 3. The visible window (retired by #5428)

`VISIBLE_NOTE_CHARS = 150` was the #4070 observation (`mcp/tools_plan.HEVY_NOTE_OBSERVED_VISIBLE_CHARS`; the test still holds the two equal until both go together). The owner's in-app screenshots of 2026-10-26 settled it: **Hevy renders an exercise note in full**, and each set row already shows the load × reps and PREVIOUS. So length costs scroll, not visibility. `render_check` raises no window problem any more (`beyond_window` is retired). Length is the note linter's phone-line budget instead (rule L7 of `docs/coaching/HEVY_NOTE_STANDARD.md` §8), and what a note may say is that standard: effort, one reason, one cue. The rows and PREVIOUS carry the rest.

## 4. The check: `manage_hevy_routine action=dry_run` → `render_check`

`hevy_render.render_check(body, session_note=why, ir=ir)` reads the compiled body and returns one row per field. A reason is searched for anywhere in the note (by its producer's grammar), not only at the start, so a reason buried behind another block is reported, never read as `absent`. The IR names the reasons that must be on the wire (`expected_reasons`: every generator progression that changed a set, from `inputs_snapshot.load_floors`, and every chat-draft step authored below the stall step, from `inputs_snapshot.step_due`).

- `status`: `lands`, `not_leading` (in the note but not first), `missing` (the IR records it, the wire lacks it), `absent` (not in this routine), `deferred` or `not_shown`
- `found`: where each hit sits (for example "exercise 2 note, line 1" or "exercise 1 set rows (3 W)"), its offset and whether it leads its note
- `session_note` with its length, and `expected_reasons`
- `note_lint` (#5428): the note linter's result over the body — its mode (`HEVY_NOTE_LINT_MODE`, `warn` today), its problems by rule (L1–L13) and the rules it could not check
- `problems`: one line for every `not_leading` or `missing` row, a session block not heading exercise 1, a warm-up set after a working set, and every note-lint problem (prefixed `note lint: `). In warn mode none of them refuses a commit.

## 5. The live proof (owner or driver; never from a lane)

1. Draft a routine that carries a progression step, a cardio block and warm-up sets. The generator's Upper-heavy day qualifies if its bench has two top sets at the top of the range on file. Otherwise use `draft_custom` with a bench block, plus a `cycling` or `treadmill` block.
2. Run `manage_hevy_routine action=dry_run` and keep `render_check`. `problems` should be `[]`, `progression_reason` should be `lands` (the bench step is in `expected_reasons`), and no row should be `not_leading` or `missing`.
3. Run `manage_hevy_routine action=commit`, open the routine in the Hevy app, and take one screenshot per item:
   - exercise 1's note shows the session line first
   - the bench note shows the progression reason ("+5 lb to …") first
   - the bench set rows show the W warm-up sets ahead of the working sets
   - the cardio note's line 1 shows the level or incline, the speed and "RPE a–b"
   - the cardio set row shows the minutes
4. Record whether the app cuts the note at about 150 characters, and if so where (§3).
5. Post the screenshots and the `render_check` JSON on #5083, then close it.
