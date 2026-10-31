# Hevy routine notes: the standard

**Status:** adopted 2026-10-27 (#5428), with the owner's rulings of 2026-10-27 applied (§0). Amended 2026-10-31 after blind re-grade #2 (draft `40f2c0b5`, panel C+/B−): the load rule (§3.1), the low-energy line, `New` vs a stale PREVIOUS and the held-top reason (§3.2), the pick-load W line (§3.3), carry units (§3.5) and intervals (§3.7), each with a linter rule (§8). Amended again after re-grade #3 (B−): no load rule over a one-set exercise 1 and its effort printed once (§3.1), the held-top reason is the load rule's own step (§3.2), the carry's start load and adjust rule (§3.5), and the intervals' easy talk words and two-way escape (§3.7). Re-grade #4 (B/B+): the load rule reaches a one-set exercise 1's other lifts (§3.1), the held-top reason names its timeline (§3.2), the feeler W row is the start load and its line the result rule (§3.3), the carry's load is on its rows (§3.5), and the interval escape uses the talk words and never drops below the hard level (§3.7). **Verified 2026-10-31.**

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
| R3 | Bigger in-session step | Two load steps (+10 lb) when top reps land at RPE ≤ 7; one step (+5 lb) at RPE 7.5–8.5; once per lift. (Re-grade #2, 2026-10-31: the line said "at RPE 8", so 7.5 and 8.5 — the PREVIOUS on three lifts that day — fell in neither branch; and "pins" read wrong on a dumbbell, where the step is lb per hand, so the line names lb. Re-grade #3: the line is two if/then lines with a unit on every step; a stack's step is its next plate (§5: a stack has no fixed step, and +10 lb on a 50 lb rope is 20 %); the rule heads exercise 1 only when exercise 1 has a later set. Re-grade #4: over a one-set exercise 1 it is addressed to the other lifts, so the session never loses its in-session rule.) The panel added two safeguards: **one step max under 40 lb**, since +10 on a 15 lb raise is +67 %; and the earlier RPE 8 / 7–8 caps **retire to the charter band 8–9**, so RPE 8 is never the top of a band. A capped first exposure (trap bar, crunch) opts out by name: `No jumps …`. The step is the charter's `progression.gain_rule.step_lb`, so the line moves with it. |
| R4 | Dumbbell warm-up: one row | One W row on the first dumbbell compound ≥ 50 lb per hand, at about 60 %, rounded to the rack, × 8 (× 5 on a 4–6 top set). Barbell warm-ups as ruled 10-23. |
| R5 | Bookkeeping off Hevy | Protein, rate, badges, streaks and critic verdicts are chat-only. `daily_brief_lambda.py` carries none of them today (verified), so they live in the coach chat until the brief is given them. |
| R6 | Pinned exercise notes are his setup only | The platform never repeats setup (seat, handles, his treadmill default) and never contradicts it silently (§1.5). |
| R7 | (~04:50Z) "yes add it back - also i think we can remove the whole chest pain, diziness and things like that line - i know this stuff" | **The safety line is removed.** No chest-pain / dizziness / 911 line anywhere on the wire. **The low-energy option is back** as one line on exercise 1: `Low energy → first 2 lifts + easy cardio.` — or, when the session's only cardio is a hard kind (intervals, tempo, hills), `Low energy → first 2 lifts + cardio, no hard efforts.` (re-grade #2: the line promised easy cardio the session did not have). The session block is the session line, that line and the load rule (§3.1). |
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
Top reps at RPE 7 or less → +10 lb on later sets; 7.5–8.5 → +5 lb.     when exercise 1 has 2+ working sets
Under 40 lb: +5 lb max. Stack: next plate. Once per lift.
```

- **Line 1, the session line** (`hevy_note_grammar.session_line`):
  - `‹Day›` is one of Upper volume · Upper heavy · Lower volume · Lower heavy · Shoulders + arms · Full body · Minimum · Travel.
  - The RPE is the compounds' band.
  - ≤ 60 characters.
- **Line 2, the low-energy line (R7):** the one branch the note carries. `Low energy → first 2 lifts + easy cardio.`, or `Low energy → first 2 lifts + cardio, no hard efforts.` when every cardio block of the session is a hard kind (`hevy_note_grammar.low_energy_line`; lint L3).
- **Lines 3–4, the load rule (R3):** stated once (`hevy_note_grammar.load_rule_line`), two if/then lines, a unit on every step.
  - "Top reps" is the top of that row's rep range.
  - Every effort up to 8.5 sits in a branch: ≤ 7 two steps, 7.5–8.5 one step; RPE 9 holds.
  - "Later sets" are the rest of that lift. On a top-set day, the back-offs move and the top set stays.
  - **Who it addresses** (`hevy_note_grammar.rule_mode`). Exercise 1 with 2+ working sets: the rule as above. A one-set exercise 1 has no later set to step, so the rule opens `Other lifts: top reps at RPE 7 or less → +10 lb on later sets; 7.5–8.5 → +5 lb.` (re-grade #4: dropping it left the session's multi-set lifts with no in-session rule), and exercise 1's own note names the gain rule's next-session step: `One set: 10 reps at RPE 9 or less two sessions running → +5 lb per hand.` No rule at all only when no lift in the session has 2+ working sets (lint L3, L11).
  - A step adds to the row, and a dumbbell row is already per hand, so the rule says no "per hand". A stack has no fixed step (§5): its step is the next plate. No "pins" on a dumbbell (lint L11).
- **Exercise 1's effort is printed once.** When its own line 1 would repeat the session line's band (`RPE 8–9`), it is dropped; a different effort (a capped `RPE 7`, `last set RPE 9–10`) stays (lint L6).
- **No safety line (R7).** The block carries no medical or warning-sign text.
- **Who writes it:** `routine_title.format_why_note` returns the block for every program role, and for a chat draft whose first note line is a session line. The compiler places it, then a blank line, then exercise 1's own note.
- **Budget:** ≤ 7 phone lines (measured: 7 with the load rule). Exercise 1 total stays ≤ 11 (§7).

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
- `Same load: aim to leave one more rep.` (PREVIOUS ran to RPE 10 at this load and today's band is 8–9 — owner ruling 2026-10-30, #5428; `lift_note._same_load_after_a_grind`)
- `Set 1: 15 reps at RPE 8.5 or less → next plate on later sets.` (held at PREVIOUS, which reached the top of the range at RPE ≤ 8.5: the load rule applied to this lift's set 1, in its implement's step and in the rule's own timeline words, "on later sets" — today — `lift_note._held_at_top`, `hevy_note_grammar.held_top_line`; on a one-set lift `Same load: 15 reps again → +5 lb next session.`)
- `One set: 10 reps at RPE 9 or less two sessions running → +5 lb per hand.` (a one-set exercise 1, which carries no load rule: the gain rule's next-session step)
- `Lighter: first time in 2 years.` (a stale PREVIOUS, §3.3, more than one step from the row — re-grade #2)
- `Set 1 over RPE 9 → sets 2–3 at 195 lb.` (the only place a load appears; a threshold follows its band)
- `No jumps today: 3rd trap-bar session.` / `No jumps: first time on it.` / `No jumps: first time in 19 weeks.` (a capped lift opts out of the load rule, and its line 1 is the cap's `RPE 7`)
- `New: replaces Calf Press (Machine).` (a rotated accessory, only when it is new to him: NO PREVIOUS at all. Hevy shows any PREVIOUS beside the row, however old; re-grade #2 read `New` over a 2024 PREVIOUS of 65 lb × 10 and a 35 lb row.)
- a critic clause (§3.8)

**Rules for reasons:**
- **A capped exposure** is one something capped: a critic's layoff set cap (§3.8), a first-exposure gate (trap bar, crunch), or the ramp's OD1 exposure cap where the engine set one on a ramped lift (`layoff_tiers.exposure_caps`). **There is no blanket layoff cap** (owner ruling 2026-10-30): a lift back after a long layoff that nothing capped keeps the normal band, like the leg curl ~23 months off. A capped lift's note is `RPE 7`, then its `No jumps` line; on stale history (§3.3) the pick-load W line follows.
- **Every working row more than one step from PREVIOUS gets a reason.** The engine derives the Heavier / Lighter / Volume-day word from PREVIOUS, his last performed load on that template (`hevy_note_grammar.delta_word`; the draft writes PREVIOUS to `inputs_snapshot["previous_loads"]`).
- **A held load whose PREVIOUS reached the top of its range at RPE ≤ 8.5 gets a reason** (re-grade #2, 2026-10-31). Without it the row reads as "never progresses" (60 × 15 @ 8.5 held at 60). **One timeline** (re-grades #3 and #4): the reason is the load rule applied to this lift's set 1, saying "on later sets" (today) as the rule does, in its implement's step — a stack the next plate, under 40 lb one step, else `+10 lb` at RPE ≤ 7 and `+5 lb` at 7.5–8.5. `Same load: hit 15 again to move it up.` sat beside a load rule that already steps a 15 @ 8.5 today. A one-set lift has no later set, so its reason is the gain rule's next-session step. A reason over such a PREVIOUS that is not the step contradicts the load rule (lint L4).
- **A stale PREVIOUS still shows in Hevy.** A row more than one step from it gets `Lighter: first time in ‹gap›.` (or `Heavier: …`), never `New:`. Lint L4.
- **One exception inside a step (owner ruling 2026-10-30, #5428): the same load as a PREVIOUS that ran to RPE 10 gets `Same load: aim to leave one more rep.`** Two of the four 10-30 graders read a bare same-load row after a grind as a copy of the grind; the reason says the intent is a lower effort at the same load. A re-entry lift keeps its layoff clause instead (§6.3), and a lift back after a long layoff that no critic capped keeps the normal band (the owner declined a blanket layoff cap the same day).
- A reason never repeats a number the rows already show.

### 3.3 Pick-load (no history, or stale history)

Used when there is no logged load, or the newest one is over 180 days old or from a bodyweight more than 20 lb away. The engine's start load goes on the working rows, after a no-load **feeler W row of 8**.

```
RPE ‹a–b›[, last set RPE ‹c–d›]
[‹one reason›]                              a stale PREVIOUS more than a step away, or New (no PREVIOUS)
W set at RPE 5 or less → next plate.          the feeler W row is AT the start load; this is its result rule
```

- **The feeler W row is the start load** (8 reps at the working rows' load) and the W line is its result rule: `W set at RPE 5 or less → next plate.` (a fixed implement's one step, `+5 lb per hand` on a dumbbell). Re-grade #4: a "— lb" W row under "test the load." had nothing to act on. RPE 5 is the top of the talk table's full-sentences row: a start that easy is a step light. One phone line. `W set: up to 8 easy reps, find the load.` stays only where the rows carry no load (a chat draft). This is not an effort cap: the band and last-set target are unchanged (lint L4, L5).

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
RPE ‹a–b› · ‹n› lb per hand to start        his last carry load, also ON the rows (else: · pick the load per hand)
Tall, ribs down, bells off your legs.
Set 1 at RPE 7 or less: +10 lb per hand.
Steps go in the yards box.
```

- **The start is his last carry**, per hand, and it goes **on the rows** (re-grade #4: in the note alone, the logged set recorded no load and the next PREVIOUS came back empty). His 2026-10-25 Farmers Walk logged 120 lb as the total of both hands; the catalog's dated convention (#5373) makes every carry from 2026-10-27 per hand, so the row carries 60 — what he types now — and the note says "60 lb per hand". A carry has no reps, so the weighted history skips it; `exercise_history` keeps it under its own `carry:‹template›` key. **The adjust rule has one threshold on purpose:** the RPE ≤ 7 branch (two steps) for set 2; anything harder stays. A 7.5–8.5 branch would be a second line, and the note is at its 4-line budget (lint L4).

- Hevy's `Farmers Walk`, with the step count in the distance box.
- Load per hand from 10-27 (#5373).
- **The row is a step count, not metres** (re-grade #2). The routine writes the step count as the set's distance number, and his yards box shows that number as written: Hevy passes the number through unconverted (#5373). His own logged carries read back as whole numbers (50, 60, 60 on 2026-10-25); a yards-to-metres conversion would have stored 45.72. So a carry row is a whole number, every rendering of it says steps, and the note names no metres (lint L11).

### 3.6 Mobility

Optional: one cue at most, ≤ 2 phone lines. The default is no note, because the row shows the minutes.

### 3.7 Cardio

```
‹Machine› · ‹levels› · [hard ]RPE ‹a[–b]› (‹talk words›)     line 1
⌚ ride clock: ‹rule›                                          tempo / hills / intervals
As rep 1 ends: full sentences → L‹hard + 1›; can't talk → 1 min at L‹hard›.     intervals: the escape
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
    - intervals: `⌚ ride clock: L12 2 min at min 6, 10, 14, 18, 22; else L11 (full sentences).` then its own line `As rep 1 ends: full sentences → L13; can't talk → 1 min at L12.` Line 1 is `Recumbent · L11/L12 · hard RPE 8 (a few words)`. With the After line that is 7 phone lines, the interval budget (§7).
- **Intervals** (re-grade #2, 2026-10-31):
  - Every minute that is not a hard rep — the warm-up, the recoveries, the cool-down — is at his steady level (`else L11`), **with its talk words** (re-grade #3: they had none). The old example said `L10 between`, one under his steady L11, and named no level for min 0–6 or after min 24.
  - The talk check lands **as rep 1 ends**, not at a bare minute (min 8 was both the end of rep 1 and the start of the easy minutes).
  - **The escape uses the talk words** (re-grade #4). "A few words" is the target (line 1). Full sentences as rep 1 ends (too easy) → one level up. Can't talk (too hard) → the hard reps shorten to 1 min at the SAME level, never below it: the old `none → L11` used a word the table does not have and dropped the reps to the recovery level, cancelling the intervals.
  - The low-energy line on a session whose only cardio is intervals promises no easy cardio (§3.1).
  - Lint L9.
    - hills: `⌚ ride clock: 6% to min 6 · +1% every 2 min from min 6 to 14 · 10% to the end`
- **Levels come from his log:**
  - easy = his logged steady level (L11 today)
  - tempo = steady + 1
  - intervals: steady before, between and after the reps; hard = steady + 1; the escape one more
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
| Cardio note | ≤ 6 lines (an interval ride ≤ 7: its escape line, re-grade #4), ≤ 240 characters, line 1 ≤ 80, ⌚ ≤ 110, After ≤ 40 | ≤ 7 | 227 / 384 characters |
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
| L3 | Line-1 grammar by type: effort, carry, cardio or session. The session block is its session line, the low-energy line for the session's cardio and the load rule's two lines — addressed to the other lifts over a one-set exercise 1, absent only when no lift has 2+ working sets (§3.1). A cardio line 1's RPE sits inside its talk words' row (§3.7). |
| L4 | Text agrees with the rows: `‹n› sets today` (and the old `‹n› sets of`) = working rows; `W set: up to ‹n›` = W reps; a row more than one step from PREVIOUS carries a reason in the right direction (a stack or cable load has no fixed step, so it is not judged — the producer's rule too). PREVIOUS comes from `inputs_snapshot["previous_loads"]` (keyed by movement key: one load in lb, or one per working row), and the check reports itself "not checked" when that is absent. One load is his last session's TOP working load, so it is judged against the top row only (a top-set day's back-offs sit under it by design); a per-row list judges every row. Rep counts compare as numbers (a stored `8.0` is the text's `8`). Re-grade #2: the pick-load W line is not a reason; `New: replaces …` over any PREVIOUS fails; a load held at a PREVIOUS that reached the top of its range at RPE ≤ 8.5 needs a reason; `find the load.` over a loaded working row fails. Re-grade #3: a reason over a held top-of-range PREVIOUS must be the load rule's step (§3.2); a carry carries its adjust rule, and its start load when his last carry is on file (§3.5). Re-grade #4: the held-top reason states the step's timeline; a feeler W line over loaded rows carries its result rule; a carry's start load is on its rows. |
| L5 | Loadable steps on every working and W row of a barbell or dumbbell. W rows ascend below the work. |
| L6 | One effort expression on a lift's line 1; exercise 1 does not repeat the session line's. |
| L7 | Budgets (§7). |
| L8 | Safety facts (§6): the first exercise of each family carries a cue and no cue comes from another family (the family comes from the catalog's anchor family, or a caller's classifier; an unknown family is reported "not checked"); a prep cue sits on its own family; no HR as the lead cardio target. |
| L9 | Clock lines: every number is a level, a grade or carries `min`; ≤ 3 levels, counting the levels a span or a ladder climbs through and the escape line's; a tempo, hill or interval ride has a clock line; intervals list their start minutes, run every other minute at the hard level − 1 with its talk words, check the talk test as rep 1 ends (never `at min ‹n›`), go one level up on full sentences and, on can't talk, shorten the reps at the hard level — never below it. |
| L10 | An `After:` line exactly when a Hevy block follows the cardio. |
| L11 | `per hand` on dumbbell and carry loads only; no `pins` on a dumbbell lift; no `later sets` on a one-set lift; a carry row is a whole step count and its note names no metres (and says where the steps go); no mph off the treadmill. |
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
- re-grade #2 (`REGRADE_2_MUTATIONS`, each asserting its own message): `New` over a PREVIOUS; a drop past a step with only the W line; `find the load` over a loaded row; a held top-of-range PREVIOUS at 8.5 with no reason; pins on a dumbbell; `later sets` on a one-set lift; the load rule on a one-set exercise 1; exercise 1's effort twice; a hold reason against the load rule; a carry with no adjust rule; a carry with a last load and no start; easy interval minutes with no talk words; an escape that steps down to the recovery level; an escape with no too-hard branch; no load rule for a one-set exercise 1's other lifts; a feeler W line with no result rule; a carry's start load only in the note; the old load rule; metres on a carry; a carry row of 45.72 steps; easy cardio promised over intervals; between below steady; no warm-up / cool-down level; a talk check at a bare minute; a two-level escape
- no session block; a truncated note
- the first DB compound with no W row

## 9. What leaves Hevy

| Removed | Now |
|---|---|
| RED TEAM block, `applied:` | `inputs_snapshot["critics"]` and the dry-run; a plain clause when a row changed |
| "Last: 36.5kg …", "N sets of 8–12", restated loads | Hevy's rows and PREVIOUS |
| Load-model provenance | IR rationale and the dry-run |
| Subtract-only paragraph, "never up" | Session lines 3–4 (the load rule) |
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
