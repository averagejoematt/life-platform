# Hevy changes since July 2026, and pinned exercise notes

**Issue:** #5010 (epic #4625), #5047 (epic #3742, §6) · **Verified:** 2026-10-18 · **Status:** research done; defensive code shipped; the three note types mapped and named in code (§6); the pinned-note write question is an owner decision
**Contract captures:** `tests/fixtures/hevy_openapi_5010/` (live 2026-10-18 + the Wayback 2026-08-17 baseline), pinned by `tests/test_hevy_pinned_notes_5010.py`

## The short answer

Hevy's **pinned exercise notes are not in the public API.** No schema in the live OpenAPI spec has a pinned, persistent or template-level note field. The live `GET /v1/exercise_templates/{id}` response carries the eight documented keys and no note. No operation can write a template note: templates have only `GET` and a `POST` that creates a custom template, and that body has no `notes`. In the app, a pinned exercise note belongs to one exercise in one user's account (Profile › Exercises › "How to"). From the API it is **neither readable nor writable**.

One question stays open: **does Hevy copy the pinned text into a saved workout's `exercises[].notes`?** The API can't answer that yet. Every live workout through 2026-10-16 had only Matthew's own session notes, and the keys were the documented set. That doesn't settle it, because no exercise had a pinned note at the time, as far as the data shows. The platform now has a marker rule (§4.1) so it stays correct whichever way this turns out. One test would settle it (§5).

## 1. What changed since the July 2026 community update

### App (consumer) side

| When | Version | Change | Source |
|---|---|---|---|
| ~2026-10-13 | iOS 3.2.0 | **"Notes, rebuilt."** You can pin a note to an exercise so it shows every time you train it, pin one to a routine, or add a one-off note for that day's workout. Also: share to Snapchat. | App Store "What's New" |
| Sep 3 – Oct 2 | iOS 3.1.12–3.1.16 | Send workouts to ChatGPT and Claude from the finish screen; 5 new languages | App Store version history |
| Aug 28 | iOS 3.1.11 | Gym tagging on workouts; choose a split (Full Body / Upper-Lower / PPL); female templates | App Store version history |
| Aug 20 | iOS 3.1.10 | Set-row UI redesign (RPE colour scale); Progressive Overload for reps-only exercises | App Store version history |
| Aug 6 – 14 | iOS 3.1.8–3.1.9 | Trainer "Program Variety"; Injury Management | App Store version history |
| Jul 24 – 30 | iOS 3.1.6–3.1.7 | Bug fixes | App Store version history |
| July 2026 | — | Latest community-update post: "Trainer, native redesign, faster app" | hevyapp.com/community-updates |

Hevy's feature page describes the note model as it now stands:

- **Pinned Exercise Notes** are exercise-specific. They "appear each time you add the movement to any workout or routine", including routines, live sessions and Trainer-generated workouts. The page's own example is machine settings: "seat at position 4, back support at position 6".
- **Pinned Routine Notes** are what a note added in a routine now defaults to. They show "only for the exercise in that routine". This is the same thing the API calls the routine's `exercises[].notes`, which the platform writes.
- **Workout notes** are per session and "saved with the workout". The API calls these the workout's `exercises[].notes`, and the note extractor reads them.

The page doesn't say whether a pinned exercise note is copied into the saved workout.

### API side (live spec diffed against Wayback captures; the repo held no copy of the 2026-08-27 contract)

The spec still has **22 operations**, the same set as 2026-08-17. Nothing was added or removed, and there is still no DELETE or PATCH. `info.version` is still the placeholder `0.0.1`. The changes between 2026-08-17 and 2026-10-18:

| Area | Change | Platform impact |
|---|---|---|
| Exercise template | `equipment_category` renamed to `equipment`; new `thumbnail_url` (nullable) | None. No code reads either field (`git grep`). |
| Workout / routine exercises | `supersets_id` renamed to `superset_id` (a doc fix; the live wire already used `superset_id`); `notes` marked nullable | None. The readers already use `ex.get("notes") or ""`. |
| Routine exercise | `rest_seconds` type changed from string to integer, now nullable; the read-side set `rpe` was dropped from the routine schema | None. The compiler sends integers and never reads routine RPE. |
| Routine POST/PUT response | Now documented as `{"routine": Routine}` instead of a bare `Routine` | Already handled: `from_hevy_response` and `verify_commit_landed` unwrap `routine`, and a list too. |
| Workout POST response | `{"workout": [Workout]}`, a single-element array | None. The platform never POSTs workouts. |
| Workout POST body | `title`, `start_time`, `end_time`, `exercises` now required; `is_private` defaults to false | None (not used). |
| Pagination | `pageSize` maximums documented: 10 for workouts, events, routines and folders; 100 for templates; 10 for body measurements | Already conforming. The callers use 10 and 100. |
| User info | New `username`, `weight_unit`, `distance_unit`, `is_pro` | None (not read). |
| Body measurements | POST now returns `201` with an empty body | None (not used). |
| Docs header | Title is now "Hevy Public API Docs". New advice: "if you update data from Hevy hourly or daily, please don't send your requests exactly at xx:00. Put some random minute instead." | **Applies to us.** `hevy-backfill` runs `cron(0 * * * ? *)`, on the hour (`cdk/stacks/ingestion_stack.py`). Proposed in §4.5. |

## 2. How pinned notes are exposed, with the evidence for each claim

| Question | Answer | Evidence |
|---|---|---|
| Exposed through the API at all? | **No.** | Live spec (`swaggerDoc` in `api.hevyapp.com/docs/swagger-ui-init.js`, 2026-10-18): the strings "pinned", "persistent", "sticky" and "exercise_note" appear nowhere. The only `notes` properties are on `Routine.exercises[]`, `Workout.exercises[]`, `Exercise`, and the routine and workout request bodies. `test_no_schema_declares_a_pinned_note` pins this. |
| Per exercise template or per user? | **In the app: per exercise, inside one user's account.** The API doesn't say. | hevyapp.com/features/exercise-notes ("exercise-specific"; added from Profile › Exercises › How to tab). `ExerciseTemplate` has no note property. The live GET for D8F7F851 (Cycling), 79D0BB3A (Bench) and a custom template returned `{id, title, type, primary_muscle_group, secondary_muscle_groups, equipment, is_custom, thumbnail_url}` and nothing else. |
| Readable? | **No.** | As above. No GET returns one. |
| Writable? | **No.** | The template operations are only `GET` list, `GET` by id, and `POST` create-custom. `CreateCustomExerciseRequestBody.exercise` has no `notes`. There is no template PUT, PATCH or DELETE. |
| Inside workout payloads, merged into or separate from `exercises[].notes`? | **Not separate:** there is no separate field. **Merged: can't be determined from the API yet.** | Live `GET /v1/workouts` (2026-10-14, 15 and 16) and the raw S3 payload `raw/hevy/e9f10998-….json` (2026-10-16): exercise keys are exactly `{exercise_template_id, index, notes, sets, superset_id, title}`, and the notes are Matthew's own session text ("Level 11 flat"). As far as the data shows, no pinned note existed yet, so these payloads can't show whether one would be copied. |

The r/Hevy "Pinned notes" thread couldn't be read. Reddit refuses automated fetches (`403` / "unable to fetch"). The Google Play listing returned no readable release notes. Neither is cited as evidence.

## 3. Impact

- **Note extractor.** If Hevy copies a pinned note into `exercises[].notes`, the same setup text would land on every session of that exercise. Its numbers ("seat 5 / level 11") would parse as a progression level. The cycling cue's `structured_level` would see two levels and drop the ride as `multi_level_session`. The completeness count in `get_freshness_status` (`training_notes_health`) would then count every session as "noted". **Repeated text can't be used to detect this.** Matthew's real session notes repeat word for word ("Level 11 flat" on every ride from 2026-10-09 to 10-16), so a repeat detector would strip real data.
- **Routine writes.** `manage_hevy_routine` commit/update **cannot overwrite or clear a pinned exercise note**, because no request it sends can reach one. The PUT body is `{"routine": {"title", "exercises": [{exercise_template_id, superset_id, rest_seconds, notes, sets}]}}`, and every key is a declared `PutRoutinesRequest*` property. The client's write routes are only `POST /v1/routines`, `PUT /v1/routines/{id}`, `POST /v1/exercise_templates` and `POST /v1/routine_folders`. There's no DELETE anywhere. Both facts are pinned by tests. What the PUT *does* replace is the routine's exercise notes, which the app now calls Pinned Routine Notes. If Matthew edits one in the app, the routine's `updated_at` moves, and `update_routine_with_guard` refuses the next PUT (`HevyConflict`). It refuses only when the stored IR carries `hevy_updated_at`; with no value, the guard is skipped.
- **Where cues live (the rule).** Stable equipment setup (bench position, seat height, recumbent bike seat and level, pulldown thigh pad) goes in **pinned exercise notes. Those belong to Matthew and the platform never writes them.** Per-session coaching cues (the gate, RPE caps, red-team verdicts, the branch menu) stay in **routine exercise notes**, which the platform writes and regenerates on every draft. Setup text should never go in a routine note: the next draft would overwrite it.
- **Cycling calibration.** The cue reads prior session notes ("L9–10 is easy, 25 Jun"). Since pinned notes can't be read through the API, the bike level and seat **can't** come from them. History parsing stays the source.

## 4. Code changes

### Made (this PR)

1. **Owner-marked setup lines are tagged and kept out of session parsing** (`lambdas/training/pinned_setup.py`). A line that starts with `📌`, `Setup:` or `Pinned:` (case-insensitive) counts as setup text. Without a marker the rule does nothing: the note comes back unchanged, so no stored record changes.
   - `training_notes.extract_signals`: the deterministic pass and the Haiku tail see only the session text. A note that is only setup makes no model call and produces no signals. The **pain lexicon still reads the whole raw note**, so the safety floor is never narrowed (Invariant 5). `note_raw` stays verbatim. Records gain `setup_raw`/`setup_only` only when a marked line is present. `ALGO_VERSION` is deliberately left unchanged so the history doesn't re-version.
   - `training_notes_health` (→ `get_freshness_status`): setup-only notes are left out of `noted_exercise_sessions` and reported as `setup_only_notes_excluded`.
   - `exercise_history.load_history_indexes` (the cardio index that feeds the cycling cue): `note` is the session text, and the setup goes in `setup_note` when there is one.
2. **Contract captured and pinned.** The live spec and the 2026-08-17 Wayback capture are in `tests/fixtures/hevy_openapi_5010/`. These live under `tests/fixtures/`, not a new top-level `contracts/` directory: the root-clutter ratchet (`tests/test_root_clutter_guard.py`) would need an allowlisted reason, and a fixture does the job. Tests: the operation set, no pinned field, the PUT/POST request shape, and the client's write routes.

Fixtures are the live 2026-10-15 and 10-16 Hevy rows, `tests/fixtures/hevy_openapi_5010/hevy_rows_2026-10-15_16.json`. Each test names the mutation that breaks it. Five mutations were run and each one broke its test (see the PR).

### Proposed (not built)

1. **Bike level and seat from pinned notes:** not possible while pinned notes can't be read through the API. Revisit if a spec re-capture adds a field; the contract test will fail when it does.
2. **The remaining readers of the setup marker:** `site_api_training` (public workout notes), `muscle_volume`, `mcp/strength_helpers` (`note_raw`). Whether setup text should appear on the public site is a publication question, so it's left to the owner.
3. **The marker itself is an owner convention.** It only works if Matthew starts each pinned note with `📌` or `Setup:`. If Hevy turns out to copy pinned text and he doesn't use a marker, the old behaviour is unchanged: the text gets parsed.
4. **Move `hevy-backfill` off the top of the hour**, from `cron(0 * * * ? *)` to a fixed odd minute such as `cron(17 * * * ? *)`, per Hevy's new docs advice. This is a one-line CDK change plus an owner-attended `cdk deploy LifePlatformIngestion`.

## 5. Owner decision box (`gate:owner`, this one decision only)

- [ ] **The platform never writes pinned exercise notes** unless the API clearly supports it (today it doesn't: there's no field and no route) **and** Matthew approves.
- [ ] Adopt the marker: start each pinned setup note with `📌` (or `Setup:`).
- [ ] The one-session test that settles §2's open question: pin `📌 Setup: seat 7` on Cycling, log one ride with a session note, and the next session reads `raw/hevy/<id>.json`. If `exercises[].notes` holds the pinned text, Hevy merges them (and the marker rule is doing the work). If it doesn't, the two are separate and the marker is belt-and-braces.

## 6. The three note types, mapped to the API (#5047)

Hevy 3.2.0 shows three notes on an exercise (the owner's screenshot, 2026-10-18). Each has one
owner and one platform behaviour, declared once in `lambdas/training/hevy_note_types.py`
(`NOTE_TYPES`) and pinned by `tests/test_hevy_note_types_5047.py`.

| App note type | App description | API field | Readable | Writable | In a workout payload | Owner | Platform behaviour |
|---|---|---|---|---|---|---|---|
| **Pinned Exercise Note** | "appears every time you log this exercise; hidden from workout posts" | **none** (`PINNED_EXERCISE_NOTE_FIELD = None`) | No | No | No separate field. Copied into `exercises[].notes`? **Unsettled** (no pinned note exists yet, below) | Matthew | **Never touches.** Setup text he marks `📌`/`Setup:` is split out at ingest if it ever appears (#5024) |
| **Pinned Routine Note** | "appears every time you log this routine; hidden from workout posts" | routine `exercises[].notes` (`PINNED_ROUTINE_NOTE_FIELD`) | Yes (`GET /v1/routines/{id}`) | Yes (`POST`/`PUT /v1/routines`) | **Not copied** into the workout (below) | the platform | **Writes coaching cues** (`hevy_compiler._exercise_to_wire`); session-level cues on the first exercise |
| **Workout Note** | "appears only in this workout; visible to friends and followers" | workout `exercises[].notes` (`WORKOUT_NOTE_FIELD`) | Yes (`GET /v1/workouts`, the events feed, the webhook fetch) | Only by creating a workout (`POST /v1/workouts`), which the platform never calls | Is the payload's `exercises[].notes` | Matthew | **Reads as his feedback**: parsed for RPE / pain / context (`training_notes`), stored as `owner_session_note` |

Two free-text fields sit outside the three: the routine-level `routine.notes` (below) and the
workout-level `description`, which the record already stores verbatim as `description`. The
platform writes neither.

**Evidence (read-only `GET`s, 2026-10-18).** The 30 most recent workouts (2026-09-11 →
2026-10-18; 29 performed from a routine) and each routine they name, read side by side:

- Every routine object's keys are `{created_at, exercises, folder_id, id, title, updated_at}`.
  None carries a routine-level `notes`.
- 215 exercise rows had a readable routine exercise beside them; 165 of those routine
  exercises carried a pinned routine note (up to 1,395 characters: the gate block on the first
  exercise). In 137 of the 165 the workout's `exercises[].notes` was **empty**; the other 28
  held Matthew's own text, none equal to or containing the routine note. **Hevy does not copy
  the pinned routine note into the saved workout.** So the ingest needs no routine-text match:
  a workout note is his text, plus a pinned exercise note if Hevy copies those.
- No workout note in the 30 starts with a setup marker, and none repeats a pinned-exercise-style
  setup line, so §5's one-session test **has not been run** (no pinned exercise note existed yet,
  as far as the data shows). The marker split stays the guard; the routine-note result says
  nothing about pinned exercise notes, which are a different app object.
- All 30 `description` fields were empty.

**Why the session-level cues stay on the first exercise.** The spec declares `routine.notes`
on `PostRoutinesRequestBody` and `PutRoutinesRequestBody` ("Additional notes for the
routine") but not on the `Routine` read schema, and no routine GET has ever returned it
(#3938: 12 of 12 September routines; all 28 above). A write that can't be read back can't be
verified, and #3938 found the text never reached the app. So the gate line (ECG + feel),
the stop list and the day's one-line plan stay at the top of the **first exercise's pinned
routine note** (`hevy_compiler._place_routine_note`, the `session_block` in
`mcp/tools_hevy_routine.py`). Testing whether the app now shows `routine.notes` would take a
routine write, which this lane may not make. If a re-capture of the spec adds `notes` to
`Routine`, `test_the_map_matches_the_live_spec` reds, and that's the signal to try a test
routine.

**What the code now says by name.**
- Write: the compiler fills exactly `PINNED_ROUTINE_NOTE_FIELD` per exercise and never sends
  `routine.notes` (`test_compiler_writes_exactly_the_pinned_routine_note_and_never_routine_notes`).
- Read: `normalize_workout` adds `owner_session_note` to every Hevy session record: one line
  per noted exercise, `"<exercise>: <text>"`, with `📌`/`Setup:`/`Pinned:` lines removed. `""`
  when the session has no note. The raw `exercises[].notes` stays verbatim, and the
  training-notes extractor still parses each raw note (pain over the whole note, the session
  parsers over the session text, as #5024 left it). Records gain the field on their next
  ingest; no backfill is needed for any reader today, because nothing reads it yet.
- Request shape: a full `manage_hevy_routine` commit, create branch and update branch,
  drives the client's one transport (`hevy_write_client._request`). It sends only `GET`/`POST`
  `/v1/routines`, `GET`/`PUT /v1/routines/{id}` and the routine-folder calls. It never reaches
  a workout endpoint (any method) or a template write, and every body key is a property the
  spec declares for that request. So the tool **cannot overwrite or clear a pinned exercise
  note or a workout note**.

**Owner decision (the #5047 `gate:owner` box, his):** whether the platform may ever write a
pinned exercise note once the API allows it. Today it cannot. Recommended answer: no, setup
notes stay his.

## Sources

- https://www.hevyapp.com/community-updates/ (latest post: July 2026)
- https://www.hevyapp.com/features/exercise-notes/ and https://www.hevyapp.com/features/track-workouts/
- https://apps.apple.com/us/app/hevy-workout-tracker-gym-log/id1458862350 (3.2.0 notes and version history)
- https://play.google.com/store/apps/details?id=com.hevy (fetched, but no readable release notes came back)
- r/Hevy "Pinned notes" thread: not reachable (Reddit blocks automated fetches)
- https://api.hevyapp.com/docs/swagger-ui-init.js (the embedded `swaggerDoc`, 2026-10-18); Wayback captures `20260428075209`, `20260817182101`, `20261010114847`
- Live read-only `GET`s, 2026-10-18: `/v1/exercise_templates/{D8F7F851,79D0BB3A,cb2d3813-…}`, `/v1/exercise_templates?pageSize=100`, `/v1/routines`, `/v1/workouts?pageSize=3`; for §6, `/v1/workouts?page=1..3&pageSize=10` and `/v1/routines/{id}` for each routine they name; the DynamoDB `SOURCE#hevy` rows for 2026-09-20 to 10-16; S3 `raw/hevy/e9f10998-….json`
