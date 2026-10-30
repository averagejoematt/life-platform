# Hevy routine notes: the standard

**Status:** adopted 2026-10-27 (#5428), with the owner's rulings of 2026-10-27 applied (§0). **Verified 2026-10-29.**

**The machine half:**
- `lambdas/training/hevy_note_grammar.py` — the words, line shapes and budgets every note producer builds from.
- `lambdas/training/hevy_note_lint.py` — the linter (rules L1–L13, §8), over the compiled wire body.

**The proof:** `tests/fixtures/hevy_notes_2026_10/a_grade.json` is the newest 10 of the 30 reviewed routines rewritten to this standard. `originals.json` is the same 10 as they were pushed (scrubbed for the public repo). `tests/test_hevy_note_lint_5428.py` holds that:
- every rewritten routine lints clean
- every original fails, with the named drift classes among its problems
- every rule has a mutation control that fires

The review that produced this standard graded the 30 routines published 2026-09-18 → 10-26 **C−** with a four-voice panel (strength coach, physical therapist, conditioning coach, plain-language editor). The same panel graded the rewritten corpus **A**.

**Scope:** every word the platform writes into a routine's **Pinned Routine Note** (`routine.exercises[].notes`, the clipboard-pin icon in the app). His Pinned Exercise Notes and Workout Notes (the plain-page icon) are his. The platform never writes them, and they render directly under ours (`hevy_note_types.py`).

## 0. Owner rulings (2026-10-27)

| # | Ruling | What it means here |
|---|---|---|
| R1 | "remove AF/ecg/and other references, i am no metorprolol" | No AF, ECG, Sinus, cardiology, beta-blocker or medication text on the wire. Cardio stays RPE- and talk-test-led (§3.7). The beta-blocker-era orthostatic cues ("sit up slowly") are retired. |
| R2 | Remove the daily gate | No pre-session check block. |
| R3 | Bigger in-session step | Two load steps (+10 lb, 2 pins) when top reps land at RPE ≤ 7; one step (+5 lb, 1 pin) at RPE 8; once per lift. The panel added two safeguards: **one step max under 40 lb**, since +10 on a 15 lb raise is +67 %; and the earlier RPE 8 / 7–8 caps **retire to the charter band 8–9**, so RPE 8 is never the top of a band. A capped first exposure (trap bar, crunch) opts out by name: `No jumps …`. The step is the charter's `progression.gain_rule.step_lb`, so the line moves with it. |
| R4 | Dumbbell warm-up: one row | One W row on the first dumbbell compound ≥ 50 lb per hand, at about 60 %, rounded to the rack, × 8 (× 5 on a 4–6 top set). Barbell warm-ups as ruled 10-23. |
| R5 | Bookkeeping off Hevy | Protein, rate, badges, streaks and critic verdicts are chat-only. `daily_brief_lambda.py` carries none of them today (verified), so they live in the coach chat until the brief is given them. |
| R6 | Pinned exercise notes are his setup only | The platform never repeats setup (seat, handles, his treadmill default) and never contradicts it silently (§1.5). |
| R7 | (~04:50Z) "yes add it back - also i think we can remove the whole chest pain, diziness and things like that line - i know this stuff" | **The safety line is removed.** No chest-pain / dizziness / 911 line anywhere on the wire. **The low-energy option is back** as one fixed line on exercise 1: `Low energy → first 2 lifts + easy cardio.` The session block is the session line, that line and the load rule (§3.1). |
| R8 | (~04:50Z) "when i meant warm up, i meant if it would recommend resistance band or body stretch before warm up, but if overkill skip" | **Warm-up text is at most one prep-movement cue per compound family**, from the existing #5049 table (`warmup_sets.WARMUP_MOVEMENT_CUES`): band pull-aparts before bench, hip hinges before a hinge, ankle and hip mobility before a squat. No general warm-up block. |
| — | Watch reminder (ruled 10-26) | `After: end watch cardio, restart Hevy.` on a cardio block that a Hevy block follows. |

## 1. Six principles

1. **Never restate the set rows.** Hevy shows, per row, the prescribed load × reps and the PREVIOUS column (e.g. "110lbs x 10 @ 8 rpe"). The note carries only what a row can't: the effort, a reason and a cue.
2. **Effort comes first.** Line 1 of every lift note is the RPE.
3. **One vocabulary.**
   - RPE for effort.
   - lb, with "per hand" on any dumbbell load the text has to name.
   - "min" on every clock time.
   - Fixed talk-test words per effort.
4. **Hevy is for the set; the chat is for the story.** Provenance, verdicts and bookkeeping are stored on the routine and never reach the wire.
5. **His notes sit under ours.** Ours never carries setup. When a prescribed dose departs from his usual, the note says `today`. It never contradicts him silently.
6. **Short is the budget.** Hevy shows notes in full, so every line is scroll. Exercise 1's set rows stay on the first phone screen. A note is never truncated to fit: if it's over budget, it fails the check and gets rewritten.

## 2. Where everything goes

| Content | Home |
|---|---|
| Sets, reps, load, W rows, rest, duration, superset | Native rows. Never repeated in the note |
| Last performance | Hevy's PREVIOUS column |
| Session line, low-energy line, load rule | Head of exercise 1's note, then a blank line, then its own note |
| Effort, one reason, one cue | That exercise's note |
| Cardio level, ride-clock rule, effort, watch step | The cardio note |
| Setup | His pinned exercise note |
| Verdicts, provenance, streak, bookkeeping | Stored routine, the dry-run and the coach chat. One plain clause goes on an exercise when a critic **changed** a row |

## 3. Note types

**Notation:**
- `‹›` marks a value.
- `·` separates fields.
- `→` means "then do".
- `–` marks ranges.

### 3.1 Session block (head of exercise 1)

```
‹Day› · RPE ‹a–b› on big lifts
Low energy → first 2 lifts + easy cardio.
Top reps at RPE 7 or less → +10 lb (2 pins) on later sets; at RPE 8 → +5 lb (1 pin). Under 40 lb: +5 max. Once per lift.
```

- **Line 1, the session line** (`hevy_note_grammar.session_line`):
  - `‹Day›` is one of Upper volume · Upper heavy · Lower volume · Lower heavy · Shoulders + arms · Full body · Minimum · Travel.
  - The RPE is the compounds' band.
  - ≤ 60 characters.
- **Line 2, the low-energy line (R7):** the one branch the note carries. Fixed text.
- **Line 3, the load rule (R3):** stated once (`hevy_note_grammar.load_rule_line`).
  - "Top reps" is the top of that row's rep range.
  - "Later sets" are the rest of that lift. On a top-set day, the back-offs move and the top set stays.
  - A dumbbell step is per hand.
- **No safety line (R7).** The block carries no medical or warning-sign text.
- **Who writes it:** `routine_title.format_why_note` returns the block for every program role, and for a chat draft whose first note line is a session line. The compiler places it, then a blank line, then exercise 1's own note.
- **Budget:** ≤ 7 phone lines (measured: 7, about 200 characters).

### 3.2 Lift (compound or isolation)

```
RPE ‹a–b›[, last set RPE ‹c–d›]        line 1, always
‹one reason›                            optional, only when it changes what he does
‹one cue›                               optional (§4), first exercise of a family only
```

**Reasons:**
- `Lighter: chase 12.`
- `Heavier: 15 reps was RPE 7.`
- `Heavier: 6 reps is a pass.`
- `Volume day: chase 12.`
- `Now aiming 10–12: 8s were RPE 8 three times.`
- `Set 1 over RPE 9 → sets 2–3 at 195 lb.` (the only place a load appears; a threshold follows its band)
- `No jumps today: 3rd trap-bar session.` / `No jumps: first time on it.` / `No jumps: first time in 19 weeks.` (a capped lift opts out of the load rule, and its line 1 is the cap's `RPE 7`)
- `New: replaces Calf Press (Machine).` (a rotated accessory, only when it is new to him: no PREVIOUS inside §3.3's 180 days)
- a critic clause (§3.8)

**Rules for reasons:**
- **A capped exposure** is OD1's: exposures 1–3 after a gap of more than 90 days in his own log (`layoff_tiers.exposure_caps`), on any lift, not only a ramped anchor. Its note is `RPE 7`, then its `No jumps` line; on stale history (§3.3) the pick-load W line follows.
- **Every working row more than one step from PREVIOUS gets a reason.** The engine derives the Heavier / Lighter / Volume-day word from PREVIOUS, his last performed load on that template (`hevy_note_grammar.delta_word`; the draft writes PREVIOUS to `inputs_snapshot["previous_loads"]`).
- A reason never repeats a number the rows already show.

### 3.3 Pick-load (no history, or stale history)

Used when there is no logged load, or the newest one is over 180 days old or from a bodyweight more than 20 lb away. The engine's start load goes on the working rows, after a no-load **feeler W row of 8**.

```
RPE ‹a–b›[, last set RPE ‹c–d›]
W set: up to 8 easy reps, find the load.
```

### 3.4 Warm-up

- W rows climb, are rounded to 5 lb, sit below the work, and are never restated in the note.
- **Text: at most one prep-movement cue (R8)**, on the first compound of its family, from the #5049 table:
  - bench: `Band pull-aparts first.`
  - hinge: `Hip hinges first.`
  - squat: `Ankles + hips first.`
- No general warm-up block, no "then the ramp sets".
- Barbell: as owner-ruled 10-23. Dumbbell: R4.

### 3.5 Carry

```
RPE ‹a–b› · pick the load per hand
Tall, ribs down, bells off your legs.
Steps go in the yards box.
```

- Hevy's `Farmers Walk`, with the step count in the distance box.
- Load per hand from 10-27 (#5373).

### 3.6 Mobility

Optional: one cue at most, ≤ 2 phone lines. The default is no note, because the row shows the minutes.

### 3.7 Cardio

```
‹Machine› · ‹levels› · [hard ]RPE ‹a[–b]› (‹talk words›)     line 1
⌚ ride clock: ‹rule›                                          tempo / hills / intervals
‹one why›                                                     optional, a route choice only
After: end watch cardio, restart Hevy.                        when a Hevy block follows
```

- **The ⌚ line** reads `⌚ ride clock:` on a bike, elliptical or rower, and `⌚ walk clock:` on the treadmill. It is the same watch clock.
- **No minutes** (the row shows them). **No speed on a bike, elliptical or rower** (an output under the iPad).
- **Talk words:**

  | Talk words | RPE |
  |---|---|
  | full sentences | 4–5 |
  | short phrases | 6–7 |
  | a few words | 8 |

  - RPE and the talk test lead.
  - **The RPE on line 1 sits inside its talk words' row.** A menu band that straddles two rows is clipped to the row its talk test names. Hills 5–7 with "short phrases on the climbs" print `RPE 6–7 (short phrases)`; the incline walk 4–6 with "full sentences" prints `RPE 4–5 (full sentences)`. Lint L3.
  - **No HR target** until his zones are re-baselined after the 10-10 episode and the medication change. The platform's 120 / 105 bpm walking numbers date from 2026-09-30, before both. Once re-baselined, an HR may appear as a **secondary** check, never the lead target.
- **The clock rule:**
  - Read off the ride's own clock from 0, in whole minutes.
  - `min` on every time.
  - ≤ 3 levels, counting every level a ladder climbs through (`L11 → L15` is five). A bike hill is steady + 2. A treadmill hill climbs grades, 1% a step, and grades are not levels.
  - The ⌚ line is ≤ 110 characters.
  - Examples:
    - tempo: `⌚ ride clock: at min 5 and 15, full sentences → one level up, a few words → one down`
    - intervals: `⌚ ride clock: L12 2 min at min 6, 10, 14, 18, 22; L10 between. Full sentences at min 8 → L14 from min 10.`
    - hills: `⌚ ride clock: 6% to min 6 · +1% every 2 min from min 6 to 14 · 10% to the end`
- **Levels come from his log:**
  - easy = his logged steady level (L11 today)
  - tempo = steady + 1
  - intervals: hard = steady + 1, with an escape upward
  - hills start no steeper than his steepest logged grade
- **Treadmill:** speed and grade are settings, so they are prescribed. The note says `today` when they differ from his usual (his own "3.3 / 1.5 incline"), e.g. `Treadmill · today 3.0 mph, 6% → 10% · RPE 4–5 (full sentences)`.

### 3.8 Critic changes, minimum / travel, tests

- **A critic that changed a row** gets one plain clause, e.g. `2 sets today: first incline in 5 weeks.` Its set count is checked against the rows. Unchanged verdicts never reach the wire.
  - **A layoff clause always carries its reason** (§6.3): the gap from the verdict, else from PREVIOUS's date, else `back after a break`. It is never a bare `3 sets today.`
  - **A set cap on a capped exposure** (a gap over 90 days, or unknown) takes the capped treatment: line 1 becomes `RPE 7`, and the clause is the lift's one `No jumps` line, `No jumps: 3 sets today, 19 weeks off.` (one phone line, so the W line and the cue still fit).
  - The clause takes the lift's one reason slot (§3.2): a computed reason already there (`New: replaces …`, `Heavier: …`) gives way and stays on the stored record. A `No jumps` line and an earlier critic clause keep their lines.
- **Minimum / travel:** the session line's `‹Day›`, then each lift as in §3.2.
- **Fitness test:** line 1 is `Test · ‹protocol›`.

## 4. Cue table (first exercise of each family per session)

| Family | Cue |
|---|---|
| Lying, seated or overhead press | `Breathe out on the press.` |
| Squat | `Brace each rep, breathe between reps.` |
| Hinge (RDL, trap bar) | `Brace; breathe out on the way up.` |
| Leg press / sled | `As deep as your hips stay on the pad.` |
| Calf press | `Full stretch at the bottom; knees soft.` |
| Row / pull | `Breathe out on the pull.` |
| Lying extension | `Elbows still.` |
| Crunch | `Breathe out on the crunch.` |
| Carry | `Tall, ribs down, bells off your legs.` |

Chat-era technique cues ("Elbows to hips, no lean-back", "Pause at the top for one count") count as the cue. A cue from the wrong family fails the check. The table is `hevy_note_grammar.FAMILY_CUES`.

## 5. Vocabulary, numbers and units

- **Effort:** `RPE ‹n›`, `RPE ‹a–b›`, `last set RPE ‹c–d›`. Never RIR, "in the tank" or "leave N".
- **Units:**
  - lb only.
  - `per hand` after any dumbbell or carry load the text names. A delta after Up/Down is not a load.
  - `@` only before a load.
- **Row rounding:**

  | Implement | Step |
  |---|---|
  | Barbell | 5 lb |
  | Dumbbell | 5 lb at ≥ 50, 2.5 lb below |
  | Plate machine | 5 lb |
  | Stack / cable | a value he has logged on that machine |

  Round to the nearest step; ties go down. That includes a load carried forward from his log: a floor raise to a logged 44 lb dumbbell is 45 (`load_progression.round_to_implement`, barbell and dumbbell only).
- **Banned on the wire** (linter L1, `hevy_note_grammar.BANNED`):
  - **Engine and process:** issue numbers, version ids, §, critic / red team / charter / engine / platform / tripwire.
  - **Load-model words:** floor, ramp, anchor, band, e1RM.
  - **Code and rule jargon:** code identifiers, "standing-constraint", "subtract-only", "never up", "is a bug".
  - **Effort and units:** RIR / "in the tank", kg.
  - **Tiers and verdicts:** tier emoji, Whoop tiers, APPROVE / FLAG / CHANGE: / applied:.
  - **Voice:** third person, "as written", "Optional if …", "…".
  - **Bookkeeping:** protein, lb/wk, calories, badges, weigh-ins.
  - **Medical and gate text (R1):** citations, AF / ECG / Sinus / cardiology / beta-blocker / metoprolol / retake.
- **Symbols:** `·`, `→`, `–`, `~`, and `⌚` on the clock line only.

## 6. Safety facts that must never be dropped

1. **The breathing / bracing cue (§4)** on the first exercise of each family present.
2. **RPE + talk words on every cardio line 1.** No HR as the lead target.
3. **A critic's safety change** (a set cap after a layoff, a swap for a joint flag) keeps its clause.
4. **A route chosen for an injury** keeps its one-line why (e.g. `Bike, not treadmill: rest the feet.`).

(The generic warning-sign line that stood first here was removed by R7.)

## 7. Length budgets (phone lines at a conservative 40 characters)

| Note | Budget | A-grade corpus | Originals |
|---|---|---|---|
| Session block | ≤ 7 lines | 7 lines (about 200 characters) | 1,395–2,219 characters with the critics' block |
| Exercise 1 total | ≤ 11 lines | ≤ 11 | 25–60 lines |
| Lift note | ≤ 4 lines | ≤ 4 | 64 / 532 characters (median / max, compounds) |
| Cardio note | ≤ 6 lines, ≤ 240 characters, line 1 ≤ 80, ⌚ ≤ 110, After ≤ 40 | ≤ 6 | 227 / 384 characters |
| Mobility | ≤ 2 lines | 0 | — |
| Any one line | ≤ 120 characters | | |
| Whole routine | ≤ 1,600 characters; the per-note caps bind first | 486–742 characters | 1,477 median / 5,027 max |

The 40 characters per line (`hevy_note_grammar.PHONE_CHARS`) is an inference. One screenshot of the next committed routine calibrates it. The test stays: exercise 1's first set row is visible without scrolling. The old 150-character "visible window" (#4070) is retired: Hevy shows a note in full (owner screenshots, 2026-10-26).

## 8. Validation rules (the linter's spec)

`lambdas/training/hevy_note_lint.py`. It runs:
- at every compile (`hevy_compiler.to_create_body` / `to_update_body`, the chokepoint the MCP tool, the nightly cron and the restamp share), in `HEVY_NOTE_LINT_MODE`. A problem logs a WARNING line; a clean lint logs one `hevy note lint (…): clean (…)` line;
- after the nightly predraft's stage 2, which compiles the drafted routine (compile only, no Hevy call) so the compiler's lint runs on it; the verdict is `note_lint` in `NIGHTLY_PREDRAFT_SUMMARY`;
- at `dry_run`, in `render_check.note_lint` (its problems also join `render_check.problems`, prefixed `note lint: `);
- in CI over the golden corpus and the archived originals.

**Modes:**
- `warn` (the default): log the problems; never change or block a write.
- `off`: skip.
- `enforce` (lane D2 of #5428, after lanes A–C): the commit gate refuses on L1–L8 and L12. The compiler itself only ever logs.

| ID | Rule |
|---|---|
| L1 | No banned token (§5). |
| L2 | No restated rows: `N × reps`, `Top 4–6 @`, `@ ‹n› lb`, `Last:` or `‹n› min ·` on cardio line 1. |
| L3 | Line-1 grammar by type: effort, carry, cardio or session. The session block is exactly its three lines. A cardio line 1's RPE sits inside its talk words' row (§3.7). |
| L4 | Text agrees with the rows: `‹n› sets today` (and the old `‹n› sets of`) = working rows; `W set: up to ‹n›` = W reps; a row more than one step from PREVIOUS carries a reason in the right direction (a stack or cable load has no fixed step, so it is not judged — the producer's rule too). PREVIOUS comes from `inputs_snapshot["previous_loads"]` (keyed by movement key: one load in lb, or one per working row), and the check reports itself "not checked" when that is absent. One load is his last session's TOP working load, so it is judged against the top row only (a top-set day's back-offs sit under it by design); a per-row list judges every row. Rep counts compare as numbers (a stored `8.0` is the text's `8`). |
| L5 | Loadable steps on every working and W row of a barbell or dumbbell. W rows ascend below the work. |
| L6 | One effort expression on a lift's line 1. |
| L7 | Budgets (§7). |
| L8 | Safety facts (§6): the first exercise of each family carries a cue and no cue comes from another family (the family comes from the catalog's anchor family, or a caller's classifier; an unknown family is reported "not checked"); a prep cue sits on its own family; no HR as the lead cardio target. |
| L9 | Clock lines: every number is a level, a grade or carries `min`; ≤ 3 levels, counting the levels a span or a ladder climbs through; a tempo, hill or interval ride has a clock line; intervals list their start minutes. |
| L10 | An `After:` line exactly when a Hevy block follows the cardio. |
| L11 | `per hand` on dumbbell and carry loads only; no mph off the treadmill. |
| L12 | Exercise 1 opens with the session block; nothing truncated (`…`). |
| L13 | R4: the first dumbbell compound ≥ 50 lb per hand has a W row. |

**Proof the rules can fail.** Every rule has at least one mutation control, each a one-line break of the golden corpus (`MUTATIONS` in `tests/test_hevy_note_lint_5428.py`):
- restated rows; a `Last:` line; minutes on cardio line 1
- a set count ≠ rows; W text ≠ W rows; a row two steps off PREVIOUS with no reason; a reason pointing the wrong way
- a DB load without per hand; per hand on a barbell; mph on a bike
- kg; an issue number; ECG text; cardiology text; `@` before RPE; a bookkeeping emoji; the RED TEAM block
- the retired safety line back in the session block; a lift or cardio line 1 off the grammar
- an unloadable 192.9 back-off; W rows that don't climb
- two efforts on line 1
- exercise 1 off the first screen; a lift note over 4 lines
- HR as the lead target; the first press without its cue; a cue from the wrong family; a prep cue on the wrong lift
- a clock number without `min`; four levels; a tempo ride with no clock line; intervals without start minutes
- a missing After line; an After line with nothing after
- no session block; a truncated note
- the first DB compound with no W row

## 9. What leaves Hevy

| Removed | Now |
|---|---|
| RED TEAM block, `applied:` | `inputs_snapshot["critics"]` and the dry-run; a plain clause when a row changed |
| "Last: 36.5kg …", "N sets of 8–12", restated loads | Hevy's rows and PREVIOUS |
| Load-model provenance | IR rationale and the dry-run |
| Subtract-only paragraph, "never up" | Session line 3 (the load rule) |
| Daily gate, ECG branches, "Optional if the ECG is not sinus", beta-blocker cues | Retired (R1, R2) |
| The generic warning-sign line | Retired (R7) |
| "Warm up: X, then the ramp sets." | One prep cue per compound family (R8) |
| Protein, rate, 🟢, "you went over", streak, `inputs_current_through` | Coach chat (R5) |
| "his calibration", rationale tails, bike mph | Gone |

## 10. Still open

1. **HR re-baseline.** When should HR return as a secondary cardio check? After about 2–3 weeks of watch data off the drug, the zones can be re-derived. Until then RPE and the talk test only.
2. **The stale-anchor threshold** for the pick-load form: 180 days, or a 20 lb bodyweight gap? The code applies the 180 days (`lift_note.STALE_AFTER_DAYS`, since the 2026-10-30 re-grade). The bodyweight test waits on PREVIOUS carrying the weigh-in at its date.
3. **Brief wiring (R5).** Should the critic flags get a home in the daily brief, or stay chat-only?

(The low-energy minimum session, open in the review, was answered by R7.)
