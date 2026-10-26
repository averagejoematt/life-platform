# Gym workflow after the Apple Watch: one visit, counted once

**Issue:** #5370 (epic #4967), with #5371 (the Strava half: [strava-best-practices-2026-10.md](strava-best-practices-2026-10.md)) · **Verified:** 2026-10-26 against integration/session-ch-w2 @ 4907f0a5a (main + #5369, PR #5383); row 1's SH and WW cells re-read 2026-10-26 for #5390 against main @ 8e9223903
**Shared fixture:** `tests/test_gym_visit_one_source_5369.py`, the 2026-10-25 wire's structure with synthetic numbers (one Hevy session holding a lift, a 60-minute Cycling block and a Stretching block; three HealthKit workouts of three origins; four Strava activities; the matching Whoop rows)
**Status:** the protocol is ruled (§1); the table (§4) covers every reader found; the cells that count twice or never count each have an issue (§5)

One gym visit reaches the platform up to ten times. Hevy logs it once, as the routine source. Then the watch, the pliability app, Hevy's own watch app, HealthKit, Strava and Whoop each hold their own copy of some of the same minutes. This page says which copy each reader counts, which it folds into another, and which it ignores. Each cell names the test that proves it. Where no test does, the cell says so.

## 1. The recording protocol (owner ruling, 2026-10-26)

The owner's choice, verbatim, was "Hevy + watch overlays". One recording per block type:

| Block | The record of the block | The heart-rate recorder |
|---|---|---|
| **Lift** | the Hevy session | Hevy's own watch app |
| **Cardio** | the Hevy block (the plan of record) | the watch's Workout app |
| **Mobility** | the Hevy block | the pliability app, as he uses it today |

Every Hevy-origin or pliability-origin echo, whether in HealthKit or Strava, folds into its source **in code** (#5369). The protocol itself needs no app setting changes. The Strava uploader settings are a separate decision, made the same evening on #5371 (§3 of the Strava page). WHOOP's share-to-Strava is off, Hevy's push is kept, and the watch uploads through Strava's Health connection.

The coach-session skill carries the same protocol in one line (`.claude/skills/coach-session/SKILL.md`, "Constraints to carry").

## 2. The record types

| Key | Record type | Where it lands | How a reader tells it apart |
|---|---|---|---|
| **H** | Hevy session (the lift) | `hevy` `DATE#d#WORKOUT#<id>` | the routine source |
| **HC** | Hevy cardio block (Cycling, Treadmill, Walking, …) | an exercise inside that row | a timed set with a counted cardio name (`walking_volume.HEVY_COUNTED_NAMES`) |
| **HM** | Hevy pliability/mobility block (Stretching) | an exercise inside that row | `workout_identity._HEVY_EXTRA_NAMES` → `mobility` |
| **AW** | watch workout | `apple_health` day row, `apple_workouts` map (owner-only) | HealthKit origin = the watch → source `apple_health` |
| **AP** | pliability-app workout (Flexibility) | the same map | origin `com.romwodllc.romwod` → `apple_health/pliability` |
| **AH** | Hevy-to-HealthKit echo (Traditional Strength Training) | the same map | origin `com.hevyapp.hevy` → `apple_health/hevy` |
| **SW** | watch-to-Strava push | `strava` day row `activities[]` | `device_name` "Apple Watch Ultra 4" (from 2026-10-26 through Strava's Health "Automatic uploads") |
| **SH** | Hevy-to-Strava push | the same list | `device_name` "Hevy" (`common.activity_overlap.HEVY_DEVICE`), WeightTraining or Workout, spanning the whole session |
| **WW** | Whoop workout | `whoop` `DATE#d#WORKOUT#<id>` sub-rows | Whoop's own API, auto-detected pieces |
| **SX** | WHOOP-to-Strava push (history only) | `strava` `activities[]` | `device_name` "WHOOP". Off from 2026-10-26, but every stored day before then carries them |

The origin tag (`training.walking_volume.apple_workout_source`) is read everywhere `apple_workouts` is read. On this tree `git grep -ln apple_workouts -- lambdas mcp` returns 6 files. The 3 readers (`training/workout_identity.py`, `training/zone2_minutes.py`, `training/walking_volume.py`) all key on that one function. The other 3 are the HAE writer pair and the privacy tier (`privacy/field_tiers.py` keeps `apple_workouts` Tier-2 owner-only; `tests/test_privacy_tier_wiring_2803.py` pins it).

## 3. The readers

The floor is the issue's grep: `git grep -ln "apple_workouts\|hevy_cardio\|counted_sessions\|workout_identity\|covered_intervals\|dedup_strava\|Hevy-echo\|hevy_echo" -- lambdas mcp`. Re-run on this tree it still returns **22 files**. They map onto the rows of §4:

| File (the 22) | Row | Role |
|---|---|---|
| `training/zone2_minutes.py`, `web/site_api_autonomic.py`, `web/site_api_training.py` (Zone 2 half), `mcp/tools_training.py`, `mcp/tools_correlation.py`, `web/window_registry.py` | 1 | THE Zone 2 computation and its four served callers. The registry declares `hevy_cardio_minutes_30d` |
| `compute/watch_hypotheses.py` | 2 | the hypothesis engine's trailing volumes |
| `training/training_load.py`, `health/training_output_channel.py` | 3 | TSB/ACWR load. The deficit tracker's channel 5 reads it |
| `health/tdee.py` | 4 | exercise energy |
| `training/walking_volume.py`, `mcp/shared_quantities.py`, `mcp/tools_coach_packet.py` | 5 | walking/cycling hours |
| `training/recent_aerobic.py` | 6 | the plan's per-activity aerobic rows |
| `mcp/coach_packet_today.py` | 7 | the session packet's "today so far" listing |
| `content/recap_data.py` | 8 | the daily recap card |
| `training/workout_identity.py`, `common/activity_overlap.py`, `common/strava_read_seam.py` | — | the shared rules the rows call: the cross-source resolver, the HR-covered interval and Hevy-echo test, and the Strava partition's same-sport fold |
| `ingestion/health_auto_export_lambda.py`, `ingestion/health_auto_export_workouts.py`, `privacy/field_tiers.py` | — | the `apple_workouts` writer and its tier. These are not readers |

The grep misses steps, conditioning, muscle volume and every reader that counts Strava activities directly. Those were added by reading. Rows 9 to 11 come from `training/steps_resolver.py`, `training/block_retro.py` and `training/panel_rubric.py`, and `training/muscle_volume.py`. Row 12 is the 15 Strava-activity counters enumerated on #5387. Row 13 is `health/character_engine.py`.

## 4. The table

`C` counted · `F` folded into another record of the same minutes · `I` ignored (not read, or dropped by rule) · **`2×`** counted twice · **`0`** never counted (a defect, not a rule). The bracket is the proof. Its key is listed below the table. `(code)` means read from the code, with no test pinning it.

| # | Reader (served as) | H | HC | HM | AW | AP | AH | SW | SH | WW | SX |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Zone 2, sessions, exercise minutes**: `zone2_minutes.counted_sessions` (`/api/zone2`, `/api/training_overview` Zone 2, MCP `get_zone2_breakdown`, the correlation tool) | C the lift part [G1 G2] | C once, as the ride's duration; also the separate `hevy_cardio_minutes` bucket, never summed [G2 G3 N1] | C the mobility part [G1 G2] | F into the ride, zones the ride [G1 G7] | F into mobility [G9] | F into the lift [G8] | F into the ride [G7] | F into the lift as its heart-rate member when it carries its own heart rate (every push from 2026-10-18) and the session holds a lift: no part, no minute, zone time claimed once against the ride and the mobility block inside its span (#5390). I dropped as the echo when it carries none, or the session holds no lift [G4 H1 H2 H3] | F, its zones win unless another recording measured materially more (over the lift, the push does) [G6 H4] | F: lift pieces fold into SH by the seam, or join the lift as chunks; the ride joins the ride [G4 G5] |
| 2 | **Hypothesis-engine trailing volumes**: `watch_hypotheses._trailing_volumes` (`cardio_7d_min`, `zone2_7d_min`) | I (Hevy not fetched) | I (Hevy not fetched) | I | C as the ride inside SH's span: **2×** in `cardio_7d_min` [P1] **#5388** | C as mobility inside SH's span: **2×** [P1] **#5388** | F into SH [P1] | F into the ride [P1] | C stands for the whole visit [P1] | F [P1] | F (seam) [G4, its no-Hevy half] |
| 3 | **Training load** (TSB/ACWR): `training_load.daily_training_load` (computed TSB, MCP `get_training_load`, the deficit tracker's channel 5) | C worked-set time [L2] | C only on the share no heart-rate record covers [L2 L3] | I, 0 by definition [L4] | I (reaches load only as SW) (code) | I (code) | I (code) | C by heart rate, covers HC [L2] | I echo-skipped when Hevy has the day [L1] | I (code) | lift pieces I (echo) [L5]; walks and rides C, cover HC [L3] |
| 3a | its `basis["sessions"]` ledger | C | — | — | — | — | — | C as a second session: **2×** [P1] **#5387** | I | — | walks and rides inside the visit **2×** [P1] **#5387** |
| 4 | **Exercise energy**: `tdee.exercise_energy` (the energy budget and calorie targets) | C worked-set lifting energy [E2] | C only on the uncovered share [E1] | C as a timed hold at the lifting rate, where row 3 charges it 0 [P1] (code) | I (code) | I (code) | I (code) | C by modality MET, covers HC [E1 E2] | F: its time moves to the lifting bucket, priced by H [E2] | I (code) | lift pieces → lifting bucket (F); walks and rides C, cover HC [E1] |
| 5 | **Walking/cycling hours**: `walking_volume.build` via `shared_quantities.walking_layer` (the plan's floor, the coach packet) | I (claims its span only when it holds a counted cardio block) [G10] | C, claims first [W2 W3] | I (code) | C last, unclaimed time only [G10] | I (origin filter) [G11] | I (origin filter) [G11] | C after Hevy's claim, once with AW [G10] | I (not a counted type) [W2] | I (code) | C outside Hevy's claim only [W1] |
| 6 | **Recent aerobic rows**: `recent_aerobic.build` (`plan_next_session`, the nightly pre-draft) | gym window for standalone walks (code) | C a row [G13] | I (code) | C a row without its heart rate [G13] | I (the same origin filter) [G11] | I (the same origin filter) [G11] | C, one row with AW [G13] | I (code) | I (code) | C outside Hevy's claim [W1] |
| 7 | **"Today so far" listing**: `coach_packet_today.activities_on_day` | C listed, claims its span [K1] | C inside the session's `cardio_blocks` (code) | C as an exercise of the session (code) | I (code) | I (code) | I (code) | F when inside a Hevy session [K2] | F inside its own session [K1] | I (code) | F inside a Hevy session [K2] |
| 8 | **Daily recap card**: `recap_data.day_facts` (workouts, walked miles, longest outdoor walk) | C the workout [R1] | C as an exercise, not a session [R1] | C as an exercise (code) | I (code) | I (code) | I (code) | C in walked miles; an indoor walk is never the longest outdoor walk [R2] | I (not a walk) (code) | I (code) | walks carry no distance, so I (code) |
| 9 | **Steps**: `steps_resolver` → `metric_truth.resolve_steps` | I | I (a derived estimate only, never merged) [S1] | I | I (the watch slot is `not_stored`) [S2] | I | I | I (derived estimate only) [S1] | I | I | I [S1] |
| 10 | **Conditioning count**: `block_retro` `cardio.conditioning_sessions`, `panel_rubric` (draft routines) | I | C (logged or planned Hevy blocks) (code) | I | I | I | I | I | I | I | I |
| 11 | **Muscle volume, lifting history, streaks**: `muscle_volume`, `exercise_history`, `training_streaks` | C | I (not working sets) (code) | I | I | I | I | I | I | I | I |
| 12 | **Strava-activity counters** (the 15 members on #5387: `/api/training_overview` workouts, minutes and modalities; the character sheet's training frequency; the weekly and monthly digests; the partner email; the daily brief; the milestone ledger; …) | I | I | I | I | I | I | C, and SH spans it: **2×** [P1] **#5387** | C stands for the whole visit [P1] | I | lift pieces F (seam); walks and rides inside the visit **2×** [P1] **#5387** |
| 13 | **Character sheet Zone 2**: `character_engine` `zone2_adequacy` | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0** | **0**. Reads `zone2_minutes`, which no writer stores [P2] **#5389** |

**Proof key.** Every `G` is a test in `tests/test_gym_visit_one_source_5369.py`, the shared fixture:

- **G1** `test_the_wire_is_one_lift_one_ride_one_mobility_block`
- **G2** `test_minutes_are_counted_once_and_the_parts_sum_to_the_visit`
- **G3** `test_hevy_cardio_stays_its_own_bucket_beside_zone2`
- **G4** `test_the_seam_folds_the_whoop_pieces_into_hevys_push_and_an_hr_less_push_drops_as_its_echo`
- **G5** `test_without_hevys_push_the_two_whoop_pieces_are_chunks_of_one_lift`
- **G6** `test_the_full_wire_with_whoop_rows_is_still_three_parts_with_whoops_own_zones`
- **G7** `test_readers_work_without_whoops_strava_copies`
- **G8** `test_a_hevy_origin_lift_folds_into_the_hevy_lift_never_a_second_watch_session` + `test_the_hevy_origin_fold_can_fail`
- **G9** `test_a_pliability_session_folds_into_the_hevy_mobility_block`
- **G10** `test_a_walk_only_the_watch_recorded_is_counted`, `test_a_walk_in_strava_and_apple_is_counted_once_with_or_without_whoops_copy`, `test_a_hevy_treadmill_block_claims_the_watch_walk_inside_it`
- **G11** `test_the_watch_backstop_reads_only_the_watchs_own_workouts`
- **G13** `test_recent_aerobic_carries_the_watch_walk_as_a_row_without_its_heart_rate`

The **H** proofs are `tests/test_hevy_push_lift_hr_5390.py` (#5390, the same shared fixture):

- **H1** `test_a_push_carrying_its_own_heart_rate_is_the_lifts_heart_rate_member_on_both_wires` + `test_the_kept_push_is_counted_once_identities_and_minutes_unchanged` + `test_the_session_count_is_one_visit_and_the_push_is_no_parts_activity`
- **H2** `test_zone2_reads_the_lifts_heart_rate_from_the_push_and_claims_time_once` + its mutation control `test_mutation_control_dropping_the_push_is_the_under_read`
- **H3** `test_a_push_with_no_heart_rate_of_its_own_is_still_an_echo`, `test_a_push_over_a_session_holding_no_lift_is_still_an_echo`, `test_a_push_whose_sport_is_not_a_lifts_is_still_an_echo`, `test_mutation_control_keying_the_push_as_plain_strava_splits_the_lift`
- **H4** `test_whoops_own_lift_pieces_do_not_outrank_a_push_that_measured_the_whole_lift`

The other proofs:

- **N1** `tests/test_hevy_cardio_never_summed_5369.py`, the AST guard over the set
- **L1** `tests/test_training_load.py::test_hevy_pushed_workout_echo_is_not_double_counted`
- **L2** `tests/test_training_load_worked_set_4075.py::test_hr_governs_a_cardio_block_it_overlaps_and_the_lift_stays_on_worked_set_time`
- **L3** `…::test_partial_hr_cover_charges_only_the_uncovered_share`
- **L4** `…::test_a_timed_hold_is_its_measured_duration_and_mobility_is_zero`
- **L5** `…::test_an_hr_less_or_echo_activity_never_counts_as_hr_cover`
- **E1** `tests/test_worked_set_duration_field_4158.py::test_exercise_energy_does_not_double_count_an_hr_covered_hevy_cardio_block` + its mutation control
- **E2** `…::test_strava_activities_classify_by_the_shared_pace_predicate_and_the_lifting_proxy_stays_for_lifting`
- **W1** `tests/test_shared_quantities_4068.py::test_whoop_walks_inside_hevy_treadmill_sessions_are_counted_once`
- **W2** `tests/test_walking_volume_3930.py::test_a_mirrored_hevy_session_arriving_in_strava_is_not_counted_twice`
- **W3** `…::test_a_hevy_cycling_block_counts_and_lands_under_its_own_modality`
- **K1** `tests/test_coach_session_packet_4082.py::test_today_lists_the_flex_session_and_the_garmin_walk_as_separate_items` (the Hevy session listed; Hevy's push and WHOOP's copy named as duplicates inside it)
- **K2** `…::test_today_keeps_the_six_whoop_in_hevy_walks_de_duplicated`
- **R1** `tests/test_recap_panel_3741.py::test_walking_and_stretching_entries_are_not_working_sets`
- **R2** `…::test_a_treadmill_walk_is_not_an_outdoor_walk`
- **S1** `tests/test_steps_resolver_5081.py::test_strava_walk_outside_a_session_is_a_derived_estimate_never_merged` + `…::test_walk_inside_a_hevy_session_and_two_devices_on_one_walk_count_once`
- **S2** `…::test_watch_slot_reported_and_still_true`
- **P1** the audit's probe (§6): each reader run over the shared fixture, pre- and post-2026-10-26 wire. It is not a test; #5387 and #5388 each make their row a test. Done in Session CI (2026-10-26): rows 3a and 12 are pinned by `tests/test_strava_session_count_set_5387.py` (every member on both wires reads 1 visit / 160 min) and the AST guard `tests/test_strava_counters_read_the_one_count_5387.py`; row 2 by `tests/test_hypothesis_hevy_input_5388.py`; row 13 by `tests/test_character_engine.py` (#5389).
- **P2** a code read: `git grep` finds no writer of `zone2_minutes` on a Strava row. The live `/api/character` lists `zone2_adequacy` among the movement pillar's dragging drivers (read 2026-10-26T05:00Z).

## 5. What counts twice, or never: the issues

| Cell | What happens on one gym visit | Issue |
|---|---|---|
| Row 2, AW/AP against SH | the engine never fetches Hevy, so Hevy's push stands for the whole visit and the ride and the mobility session are counted again. `cardio_7d_min` reads 240 for a 160-minute visit; with Hevy rows it reads 160 | **#5388** |
| Rows 3a and 12, SW/SX against SH | 15 readers count Strava activities directly: Hevy's push of the whole session plus the ride (or, before 2026-10-26, WHOOP's ride or walk) inside it. Two sessions and 220 minutes for one 160-minute visit. Since 2026-10-18 Hevy's push also carries its own zones, so a day's summed `zone2_seconds` can hold the ride's minutes twice | **#5387** |
| Row 13, every column | the character sheet's Zone 2 reads a key no writer stores, so it is 0 every day | **#5389** |
| Row 1, SH (an under-read, not a double count) | the resolver dropped Hevy's push as an echo. Since 2026-10-18 the push is the one record with heart rate over the whole lift; the Hevy-origin HealthKit workout spans only part of it. Decided in code on #5390: a push carrying its own heart rate is the lift's heart-rate member (row 1, SH) | **#5390** (rule decided; the 2026-10-26-protocol read is `scripts/gym_day_hr_coverage.py --date <day>`) |

Already fixed and cited, not re-filed: the zone-2 over-merge of a whole visit into one session (#5369, G1), the Hevy-origin and pliability-origin HealthKit fold (#5369, G8 G9), the HealthKit-origin read in the walking layer (#5369, G11), Hevy cardio minutes summed with wearable minutes (#5369, N1), the WHOOP treadmill walk inside a Hevy session (#4068, W1), and the Hevy cardio block charged twice for energy and load (#4158 E1, #4075 L2).

Two gaps that under-read rather than double-count, stated here and not filed. The day grade's walking half (`scoring_engine` → `walking_minutes_for_day`) and the "today so far" listing do not wire the watch backstop. So a walk the watch records but does not upload to Strava is missing from those two reads only. With Strava's automatic uploads on, the watch uploads its walks, so both reads see them through SW. The energy model charges the Hevy mobility block as lifting work (row 4) while the load model charges it 0 (row 3). That is a rate question, not a duplicate.

## 6. How the table was read (reproducible, read-only)

The probe imports the shared fixture module and hands each reader the same synthetic visit. The rows go in through `common.strava_read_seam`, as every reader receives them. It runs each reader twice: once on the 2026-10-25 wire (four Strava activities, WHOOP's included) and once on the post-2026-10-26 wire (Hevy's push plus a watch Ride). For rows 3 and 4 it calls `training_load.daily_training_load` / `hevy_session_load` and `tdee.exercise_energy` / `worked_set_seconds`. For row 2 it calls `watch_hypotheses._trailing_volumes` with and without `data["hevy"]`. For row 12 it calls `site_api_training._dedup_whoop(_flatten_day_activities(...))`, and for 3a it reads the load ledger. No AWS call, no clock read. The live reads behind the issues are read-only too: raw Strava day files and the raw HAE workouts export in S3 (spans and device names only), and the public `/api/character` payload.
