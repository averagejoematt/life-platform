---
name: daily-debrief
description: "Run the nightly coaching debrief: review what training actually happened today, then author tomorrow's session as a Hevy routine. Use at end of day for training review, or when asked to plan tomorrow's workout."
user-invocable: true
argument-hint: "[review | author]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TodoWrite, mcp__life-platform__*
---

Run the nightly coaching debrief: review what training actually happened today, then (if
tomorrow is a training day) author tomorrow's session so it's ready before Matthew wakes,
drives to the gym, and has zero chance to adjust. Condensed from
`docs/coaching/COACH_SESSION.md` — that file stays the full source with the complete
persona, board-lens, and authoring-rubric detail; this command carries over its
load-bearing parts (§1 freshness paranoia, §2 thread-as-hypothesis, notes-completeness
cross-check) and adds the post-workout review emphasis this mode is for. See also
`docs/coaching/CHAT_MODES.md` for the route-the-takeaways contract this command uses.

## Arguments: $ARGUMENTS

Optional. `review` to run only the post-workout review half (skip authoring — e.g. a rest
day tomorrow). `author` to skip straight to authoring (e.g. reviewing was already done
earlier). Empty runs both, in order, as the standard nightly ritual.

## Instructions

### 0. Context first — every time, no shortcuts

Read `TRAINING_CALIBRATION.md`, `TRAINING_PROGRAM.md`, and `PROVEN_BLUEPRINT.md` from
the S3 owner prefix before reasoning about anything (owner-private since #3043 —
`aws s3 cp s3://matthew-life-platform/config/coaching/<name> -`). If authoring is in
scope, also read the matching `docs/coaching/routines/<type>/` spec for what was last
built and the progression currently in play — that index has been stale since 2026-09-19
(#4079), so for anything committed after that, also read
`config/coaching/routine_specs/<type>/<routine_id>.json` (same `aws s3 cp` pattern) for
the latest committed state; every routine 2026-09-21 onward was back-filled there by
`deploy/backfill_routine_specs.py`. Do not fall back to a generic routine or generic
coaching — these three docs are how Matthew is calibrated and what's actually being run.

Persona: training coach, peer-to-peer (Matthew has lifted for years — skip the basics).
Reason through the Personal Board's lenses and surface genuine disagreement rather than
blending to consensus: Sarah Chen (sports science/periodization), Victor Reyes
(metabolic/longevity), Marcus Webb (nutrition), Iris Tanaka (movement/joints), Maya
(adherence), Henning (rigor). Be science-led and willing to push back — never the generic
answer, never what Matthew wants to hear.

**The board is a lens, not the red team.** The red team is `plan_next_session` stage 2
(#3752): four critics that each hold a DIFFERENT evidence packet and each make a separate
model call — muscle-defense (anchor-lift trend + protein), joints/tendons (pain flags,
novelty, streak), rate-advocate (the owner's redlines and which tripwires are clear),
blueprint historian (the band reference + the #3717 attestation, labelled). One model
role-playing six personas cannot disagree with itself about data it was handed all at
once; the critics can, and each must name the number it argued from. Do not describe a
plan as red-teamed unless stage 2 ran on the routine you are committing.

### 0b. The packet — ONE call before any other data tool (#4082)

`get_coach_session_packet(target_date=<the session being coached>)` — tomorrow's date when
authoring. It returns, in one read, what a debrief used to re-verify over 10+ calls: working
sets per muscle (7d + 28d completed days), the last session of each type and each v0.3
session role with every set and note, MacroFactor kcal + protein over 7 days with the
protein-floor count, weekly walking hours (the one #4105 definition), the loss rate, the
active-day and loaded-lifting streaks, readiness + the readiness-floor streak, and the v0.3
block position. Every field is `measured` / `absent` / `read_failed` and names its canonical
source; nothing in it is a second computation.

- Quote it. Re-pull a field only when it is `absent`/`read_failed` or Matthew disputes it —
  a second tool over a different window is how one quantity reached him as two numbers
  (#4068).
- `read_failed` is never zero or empty: name the field and what it leaves unknown.
- It is the planner's INPUTS. Authoring still runs `plan_next_session` stage 1 → draft →
  stage 2 (below); the packet does not replace the constraint block.
- Today's session logged AFTER the packet was read is not in it — re-call the packet (not
  the individual tools) once the workout has synced.

### 1. FRESHNESS & COMPLETENESS FIRST (carries over verbatim from COACH_SESSION.md §1)

Before trusting any computed number: `get_freshness_status`, and verify completeness —
does today's session actually appear in the volume/recovery aggregations, not just the
latest record? A "green" status is a high-water-mark; it hides mid-window gaps. If a
number looks off or drives a big call (especially tomorrow's prescription), re-pull to
confirm before acting on it.

**Notes-completeness cross-check**: if `get_workout_detail` returns blank notes for
today's session while `get_freshness_status` reports the note-extractor healthy, that's a
fetch discrepancy — NOT a clean session. Flag it and re-pull; never report "no pain flags
/ clean" off empty notes. General rule: a tool's empty/green result is a HYPOTHESIS to
verify by direct read, not a fact to assert.

### 2. CONTINUITY (carries over from COACH_SESSION.md §2)

`get_coach_thread` (training domain) to pick up prior positions, what was said would be
tried, open predictions. Treat the thread's narrative flags as HYPOTHESES to verify
against `get_workouts`/Strava, not facts — stale data poisons it. Cross-check any
underload/overload story the thread implies against actual logged sessions before
accepting it.

### 3. POST-WORKOUT REVIEW — what was JUST done, not just what's next

This is the part `daily-debrief` adds beyond COACH_SESSION.md's night-before framing:
review today's actual session before looking ahead at all.

- `get_workout_detail` for today's session(s) — read the real exercise list and notes,
  not just the volume rollup (`get_muscle_volume` hides Pallof/carries under "Other" and
  can misreport core as 0 — don't trust it alone for what was actually trained).
- `get_exercise_notes` — the
  number says how hard; the note says why ("that RPE9 was shins not calves", "grip gave
  out first"). A note can correct a number's interpretation but never silently overwrites
  the logged number.
- `get_readiness_score`, `get_acwr_status` — how the session landed against readiness/
  training load, not just whether it happened.
- **Never call a stall or a plateau off the performed numbers alone (#3928).** At a fixed
  load × fixed reps, estimated 1RM is constant *by construction* — if the platform
  prescribed that load and those reps and he did exactly that, a "stall" is the platform
  re-reading its own prescription, not an observation about Matthew. Diff prescribed vs
  performed FIRST: `manage_hevy_routine(action="stall_check", movement_key=…)` pairs each
  of that movement's recent sessions with the routine IR that was pushed for it and
  returns `stall` / `progressing` / `regressing` / `unknown`. It returns **`unknown`,
  never `stall`**, on a window he performed as prescribed at a fixed load × reps, and it
  will not call one at all when no prescription is on file for those days. Report its
  `reason` — it names both numbers.
  - RPE is the only residual signal in such a window, and it is **self-reported**. Any
    verdict that leaned on it comes back with `basis: "self-reported RPE"`; say that out
    loud whenever you quote it. An RPE drift is his own rating of the set, not a
    measurement, and it does not license a stall verdict on its own.
  - `action="adherence"` is the session-level companion (set-count + RPE-ceiling
    dimensions, never averaged); `stall_check` is the across-sessions one for a single
    lift.
- Aerobic — count it from ALL sources: Strava walks/runs AND Z2 bike/elliptical blocks
  logged INSIDE Hevy (invisible to Strava). `search_activities` can undercount; don't
  call the aerobic base "starved" off one source.
- Say what actually happened, plainly: did the session hit the intent, where did it
  diverge, what does that change (if anything) about tomorrow.
- Close the loop on any open prediction from the coach thread (`get_coach_thread`) —
  did it hold up against what actually happened today?
- Route takeaways per the CHAT_MODES.md contract: a genuine pattern worth tracking →
  `save_insight`; a decision Matthew made against/with platform advice → `log_decision`
  (outcome later via `update_decision_outcome`); anything that belongs in the compounding
  substrate (a calibration correction, a failure pattern, what worked) →
  `write_platform_memory` with the matching category. **A standing training constraint he
  states (a gate, a toe flag, a back flag) → `write_platform_memory(category='training')`
  (#4077)** — its own narrow category, not `constraints_preferences`, so
  `plan_next_session` stage 1 reads it directly as `standing_constraints_from_chat`.
- **Matthew overrides a coach's read mid-session** — a flag he says is stale, a verdict
  he disagrees with — **log it: `log_coach_correction(signal=<the metric/flag id that
  was wrong>, correction=<his words, verbatim>, coach=<bare id>)` (#4083)**. No pack
  number is needed for this path — name the SIGNAL, not an item number. This is what
  feeds `get_intelligence_quality`'s false-positive-by-signal ranking; an override that
  isn't logged doesn't count toward it.

### 4. SYNTHESIZE current state (only as deep as authoring needs — don't fan out)

If authoring tomorrow's session (skip this if `$ARGUMENTS` is `review`):
- Energy/nutrition: `get_nutrition`, `get_deficit_sustainability` — on a deep cut,
  protein + enough fuel to defend muscle is the #1 lever; flag under-eating relative to
  targets.
- Weight-loss trajectory: `get_weight_loss_progress` — early-cut drops are water, don't
  read week-1 rate as tissue.
- **The weight-matched reference: `get_benchmark(view="prescription")` (#3710).** Cardio
  volume and target heart rate are prescribed FROM this, not from feel. It returns what
  Matthew was actually doing at a comparable bodyweight during a period he was LOSING —
  walk miles/hours, target walk bpm, sets, per-movement loads — plus the weight distance
  to that period and its evidence tier. Read it as follows, and do not improvise around it:
  - `proven_target` is the target. `current_typical` is the BASELINE and must never be
    quoted as a recommendation — at his current weight it is drawn from the very weeks he
    is trying to escape.
  - `volume_citable: false` means the nearest losing-phase period is below the evidence
    floor. Cite it as description ("the nearest comparable period ran X mi/wk, from N
    effective days — below the bar to set as a target"), never as a prescription.
  - `band_distance_lb > 0` must be said out loud. A reference 18 lb lighter is not a
    mirror, and presenting it as one is the failure this tool exists to prevent.
  - `applicable: false` with `reference_schema: 1` is a STALE REFERENCE — `episode-detect`
    needs redeploying. It is not a finding about his history; do not report it as one.
  - Intake is never comparable (no nutrition data before 2025-11-24). Say so whenever the
    comparison is used, per ADR-104.
- **The standing bet: `get_benchmark(view="forecast")` (#3712).** The week's prescription is
  registered as a graded forecast, so there is a number the plan already committed to and a
  record of whether it has been right. Read it as follows:
  - `open.prescribed_cardio_hr_wk` is the week's volume target and it OVERRIDES a freehand
    number. When `adjustment.basis` is `adherence_shortfall` or `model_over_predicted`, that
    target was DERIVED from last week's miss (`adjustment.derivation` shows the arithmetic) —
    quote the derivation, do not re-author the number.
  - `open.declined` means no forecast was issued and `declined_reason` says which floor failed.
    That is a result. Do not substitute a guess for it.
  - `track_record.answerable: false` means too few weeks have been graded to say whether the
    coaching is working. Say that, rather than quoting a coverage percentage at n=2.
  - Every figure here is descriptive of his own history and excludes intake (ADR-104).
- Mood/journal continuity: `get_mood` — mood continuity is a make-or-break signal for
  whether tomorrow's session should push or hold.
- Muscle volume vs MEV/MAV/MRV (`get_muscle_volume`) for the muscle groups in tomorrow's
  planned pattern, cross-checked against the actual exercise list per §3 (never trust
  the "Other" bucket at face value).

Give a curated read, not a template — every call visibly shaped by calories, recent
lifts, recovery, aerobic load, and notes. No reflexive "flush": name what each easy
session BUILDS; legs get a periodized progression slot, not perpetual recovery.

### 5. BUILD IT RIGHT FOR THE NIGHT BEFORE (carries over from COACH_SESSION.md §5)

Matthew authors at night and trains the next morning with zero chance to adjust. So:

- **Author tier-agnostic.** Never hard-stamp one night's recovery tier into the
  prescription. Write recovery BRANCHES into the cues (see
  `docs/specs/SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md`):
  🟢 GREEN (Whoop 67-100) = the authored ceiling (intervals / +1 RPE cap / optional work
  on); 🟡 YELLOW (34-66) = the baseline plan (the safe default with no signal); 🔴 RED
  (1-33) = subtract to the floor (Z2/mobility, cut top sets, or rest). Plus: use the
  LOWER of (wrist band, how Matthew feels) — feel only downgrades.
- **Autoregulation is subtract-only, and it has a FLOOR (#3927 — owner ruling
  2026-09-19, §7 of TRAINING_CALIBRATION.md).** Carried verbatim from
  `training.routine_generator.SUBTRACT_ONLY_RULE`, which is the same sentence the cron
  generator writes into the routine:
  > Autoregulation is subtract-only. The prescribed load IS the floor: take it down on
  > the day if you have to, never up, and never wait to be asked to progress. A load
  > below one already achieved at this bodyweight band, with no layoff, is a bug — not
  > conservatism.

  In practice, when you write a load into a cue:
  - Derive it, don't feel it. `prescription_floor(template_id, …)` in
    `lambdas/training/routine_generator.py` returns the best load that movement has
    actually carried at his CURRENT 10-lb bodyweight band, out of the Hevy partition.
    The number you prescribe is `>=` that floor. Full stop.
  - The ONLY sanctioned way below it is a layoff: `>=` the re-entry threshold
    (7d) since the last logged session, which applies the documented 10–15% detraining
    discount and says so in the cue. No layoff, no discount — a lower number with no
    layoff is the bug, not caution.
  - **Never write a conditional UP-branch.** Not "if set 1 is ≤7.5 go 80", not "GREEN
    only: a 2nd set at 185", not "climb toward 175 if set 1 is 4+ RIR". Progression is
    never his job to trigger mid-set at 5am — if the platform knows he hit 80, the
    prescription says 80. Down-branches are the sanctioned form ("drop to 40x10 if set 1
    exceeds the cap"). `recovery_authoring.find_conditional_up(text)` is the detector,
    and `audit_prescription(exercises, routine_notes, floors)` reds on both classes.
    **Since #3971 this is a GATE, not a reminder:** `dry_run` reports the audit in
    `prescription_audit`, and `commit` REFUSES with `SUBTRACT_ONLY_VIOLATION` on any
    conditional up-branch or any working set under its floor, naming the clause or the
    set and the floor's provenance. There is no chat-side override — fix the draft and
    re-`draft_custom`. `floor` / `re_entry` variants are exempt and say so in the result.
- Lower the GREEN ceiling / raise floors for week-position (consecutive training days),
  deep deficit, and novel-pattern tendons — green recovery does not clear a
  3-sessions-in tendon.
- Before programming any core/carry/finisher, read the ACTUAL exercise list of the last
  2-3 sessions via `get_workout_detail` (not `get_muscle_volume` — it hides
  Pallof/carries). Don't repeat the same anti-movement pattern on consecutive days.
- When Matthew's happy with the plan: `manage_hevy_routine` `draft_custom` →
  **`plan_next_session(routine_id=<the draft>)` — the red team (#3752)** → `dry_run`
  (show him the compiled preview, with an "inputs current through X" line so he can
  trust it) → `commit`. **Never pass a title** — it's auto-rendered from
  `Phase - Type - N - Y`.
  - Read every verdict in `critics.verdicts` and say which metric and number each critic
    pointed at. A **`veto`** blocks commit (`CRITIC_VETO`): redraft against the reason
    (substitute the flagged movement, drop the to-failure set, warm one axial pattern) and
    run stage 2 again. A **`change`** is already applied to the draft — `dry_run` shows
    the revised body; do not re-apply it by hand. `model: {paused: …}` on a verdict means
    the deterministic layer alone decided at this budget tier — say so; it is not an
    approval by a critic that ran.
  - Read `prescription_gate` on the commit result the same way. `SUBTRACT_ONLY_VIOLATION`
    (#3971) is the second named refusal on this path; unlike a critic veto it is purely
    deterministic, so "the model disagreed" is never the explanation.
  - The historian's packet carries the #3717 attestation with `OWNER-ATTESTED, NOT
    MEASURED` on it. Whenever you cite a band the attestation covers, say that the
    measured figure is a floor and the attested minutes are his statement, not a record.
  - A routine committed without stage 2 carries a `not red-teamed` warning in its
    result. That is the honest state — never describe such a plan as reviewed.
- After commit: log the decision to the training coach thread, save the routine spec to
  `docs/coaching/routines/<type>/` (README convention + annotation standard — see that
  README before creating a new file), and remind Matthew to `git commit` the spec.

Hard rule, carried over verbatim: never hand Matthew the standard routine. This is
programmed from his data, his progress, his goals, his weight-loss trajectory, and his
recovery — not a generic template.
