# The training engine: how a session is chosen, progressed and kept recoverable (#5861)

> **Status:** describes the integrated engine of epic #5861 (lanes L1–L6). **Everything new runs only once the owner
> approves the exercise library** (`config/exercise_library.json` `"status": "approved"`). Until then today's drafts are
> served unchanged, byte for byte (`tests/test_no_live_change_5861_l6.py`, `tests/test_no_live_change_5861_l3.py`).
> **Written:** 2026-11-12, against charter 1.49.0, library 0.2.0 (`proposed`), the #5799 time model (99 s a set, measured).
> **Updated:** 2026-11-13 for the red-team programming fixes (`live_program`, §4–§7, §9): the generated weeks, not the
> architecture, were graded C+; every change below is LIVE-only and measured on the sample weeks. **Updated again** the same
> day for the SECOND red team's programming findings (`live_week`, the novelty budget, the load evidence rule; §3–§10),
> measured on the sample weeks and on the owner's private real-data run.
> No personal data: every example is a synthetic profile (`tests/fixtures/sample_week_profiles_5861.json`).

## The principle

**An exceptionally comprehensive library, an exceptionally selective engine.** The library rates 625 movements on five
objectives; the engine serves four to eight of them in a session — the right ones for the slot, his response, his equipment,
his recovery and the 75-minute ceiling — and holds them while they progress. More options is not more training: nothing is
ever added to fill a slot.

## The draft path

```
session sequence (next undone role)            program_structure.SESSION_TEMPLATES   (the week's design: 5 roles,
        │                                                                                anchors + accessory slots)
        ▼
variant_rotation.for_session ──► selection_engine.apply ──► selection_live (LIVE)     accessory slots: ranked from the
        │                         (shadow: the #5075 pools serve)                       library, like for like
        ▼
program_structure.session_prescription_for_role   anchors resolved, accessories placed, the #5799 time fit (estimate)
        ▼
live_session.for_live_draft (LIVE)                 equipment + pain on EVERY exposure, then live_program.plan (pain by
        │                                          joint, axial stacking, stall scheme, fatigue cost), then fatigue_model
        │                                          (one reducer, compounds first / deload shape), then the trunk floor
        ▼
full_body_session.full_body_routines               loads (load_ramp / load_progression, then the LIVE load guard),
        │                                          warm-ups, composed Hevy notes, the routine's own time fit (LIVE), rationale
        ▼
mcp.draft_standing_constraint.gate_draft           the session block, the cardio block (cardio_menu, then the LIVE cardio
        │                                          fit: live_program.cardio_fit / cardio_note)
        ▼
hevy_compiler.to_create_body                        the routine as written to Hevy
```

## 1. Classification — what a movement IS

Built offline by `deploy/build_exercise_library.py` from the Hevy history, the catalog and the curation modules; never
hand-edited (the committed JSON equals the builder's output; two builds are byte-identical).

| Field | What it says | Source |
|---|---|---|
| `target` (primary, secondary) | the muscles it trains | Hevy groups + 141 reviewed overrides (`exercise_library_targets.py`) |
| `pattern`, `job` | movement pattern (squat, hinge, vertical pull, shoulder rotation, hip abduction, …), compound/isolation | title rules (`exercise_library.movement_pattern`) + reviewed overrides |
| `category` | hypertrophy · strength · conditioning · athletic · mobility · rehab_control · carry | rule + reviewed overrides; an L2 addition's DECLARED category is kept |
| `trunk_function` | loaded flexion · anti-extension · anti-rotation · anti-lateral flexion · rotation · loaded stabilisation | rule; declared on additions |
| `length_bias`, `resistance_profile`, `stability`, `joint_stress`, `skill_complexity`, `equipment` | the inputs the rubrics read | rule + `ATTRIBUTE_OVERRIDES` (reviewed) |
| `canonical`, `variant` | the alias/dedupe layer: 44 families (e.g. 11 lat pulldowns are one family) | `CANONICAL_FAMILIES`; every pre-epic key and template id still resolves |
| `gates`, `not_for_you_now` | readiness: bodyweight, chain prerequisites, impact, skill, an identified need | curation + additions |
| `availability.home_gym` | available · unknown · unavailable, per movement and per equipment item | the 5-year rule (owner ruling 2026-11-11) |

The **movement catalog** (`config/movement_catalog.json`, built by `deploy/build_movement_catalog.py`) is what the generator
can WRITE to Hevy. A library movement with no catalog entry is never served. L6 adds the library movements with a Hevy
**built-in** template through the builder's `coach_added` path (`deploy/movement_catalog_additions.py`); movements that need a
custom template wait on the owner (L2's approval list).

## 2. Evaluation — per objective, each with its own rubric

`lambdas/training/quality_rubric.py` (rubric 3.0.0, PROPOSED). Every rating is `{tier S|A|B|C|D or null, basis[],
evidence_confidence}`. **`null` means not applicable, never "bad"**; nothing is forced into an objective; evidence
confidence is a separate field and moves a tier by at most one band (a direct trial), never into S past an unmet criterion.

| Objective | What it judges | S requires |
|---|---|---|
| hypertrophy (per target muscle) | stretch/length, stability to failure, resistance profile, progressability, joint cost; caps for a low overload ceiling or a limiter that is not the target | every S criterion: high ceiling, target is the limiter, stable, systemic fatigue not high, no high joint stress |
| strength | loading class, primary-lift status, self-stabilised, bilateral | a primary lift at maximal loading, self-stabilised, bilateral |
| functional | unilateral control, balance, carries, loaded locomotion, trunk stability, multiplanar, power, **joint capacity** (L6) | 3+ qualities, loadable, safe, AND a carry or single-leg work under travel/trunk load |
| conditioning | aerobic stimulus, intensity control, impact, recovery demand — `cardio_model` (L4) owns every modality | A-level stimulus and control, low impact, and his own sustained use (10+ sessions) |
| mobility / joint function | loaded > active/motor control > passive | only against a recorded N=1 limitation |

`joint_capacity` (L6): loaded work for a small stabiliser controlling a joint the big lifts load — rotator-cuff rotation,
lower-trap and serratus scapular control, tibialis and ankle, the adductor isometric. One quality: B when loadable, C
otherwise. It gives cuff and scapular work a functional verdict instead of a hypertrophy D, and can never reach S.

**What the tiers are NOT.** They are a categorical stimulus profile, not a measured effect size. 614 of 635 hypertrophy rows
carry `evidence_confidence: none_reviewed`; the rest cite verified trials (DOI/PMID) and move a tier by one band at most. The
conditioning, functional and mobility rubrics are practitioner consensus.

## 3. Selection — the live policy (`selection_engine` + `selection_live`)

The engine fills **accessory slots** (anchors are the program's). A slot is one template accessory: its muscle, its job
(movement patterns), its volume signature (so a swap never moves the week's set counts — the volume lock).

1. **Candidates**: same muscle AND pattern; the slot's objective rates it (a movement with `null` for that objective is never
   a candidate); for a trunk slot, the same **trunk function** (L6: a crunch slot is loaded flexion, so a torso-rotation
   machine is not a candidate even when its pattern word matches); available at home_gym; not pain-excluded;
   not `not_for_you_now`; every locking gate open by #5772's fresh evaluation (fail-closed); writable by the catalog; and, if
   new to him, a cue sheet (`selection_cue_sheets`) and the novel-again caps (RPE ≤ 7, ≤ 8 reps for exposures 1–3).
2. **Pool**: the top two non-empty bands (normally S∪A).
3. **Rank inside the pool**: repeated discomfort last, then his **N=1 fit** (the private overlay: progression, pain history,
   sentiment, swap-outs), then a categorical **fatigue cost** (compound, free weight, spinal load; heavier under axial
   stacking — machines and cables win at equal fit, his own response overrides), then slot variety, then tier.
4. **Hold while it progresses; rotate only for a named trigger** — stall/regression, pain, discomfort, equipment, no longer
   servable, a better band (servable this week, and only at a block's first phase — mid-block the upgrade waits, L6),
   adherence (swap-outs), fatigue (axial stacking), the owner's request, or a block-end review after 12+ weeks without
   progress. Never the calendar alone.
   **Novelty is budgeted** (L6; second red team): at most two movements NEW to the served week — a slot serving something it
   did not serve last phase and that he has not performed in the last 28 days — whatever the source: a live rotation, a
   never-logged pick, or the rotation LEDGER carrying a phase decision forward (the owner's real run served four, all from a
   shadow-era #5075 calendar rotation the ledger held, which `_live` serves whenever it is one of the pick's fallbacks).
   Forced changes (pain, equipment, no longer servable, fatigue, an owner request) keep their place and count; past the
   budget an optional change waits — a stall rotation keeps its place longest, a calendar rotation the live policy never
   asked for waits first — and the slot serves last phase's movement (`selection_live.enforce_novelty`, said so on the
   selection line). A held movement is never "new".
5. **A systemic slump is not a stall** (L6): when four or more judged lifts — and at least half of them — stall or regress
   together, the cause is sleep, recovery or the deficit; the movements hold and the fatigue model takes volume off instead.
6. **Within-week repetition when it helps**: a same-band peer is preferred over a duplicate; when the best band has no unserved
   member, a second weekly exposure of the best movement beats dropping a band (cap 2 a week, by canonical family).
7. **The rotation ledger** keeps a phase's first draft: a movement chosen mid-phase serves from the next phase, and the
   rationale says so ("THIS phase serves …").

## 4. The session fit (`live_session`, L6)

What the selection cannot see, because it ranks slots:

- **Equipment and pain on every exposure, anchors included.** An unavailable or pain-flagged anchor takes the next member of
  its pattern that is available, pain-free, servable (no locked gate) and at the anchor's skill ceiling; after a pain or
  repeated-discomfort flag the replacement must load the flagged movement's worst joint *less* (the library's joint-stress
  ratings). With none, the exposure is **skipped and said so** — never an impossible or painful prescription, never a filler.
- **One graded reducer.** A red readiness tier or a high ACWR no longer strips every accessory: both are HR-derived (Whoop),
  and HR is not effort evidence until a post-regime baseline exists, so they are ONE vote in the fatigue model beside sleep,
  hard cardio, weekly sets, strength trend and effort drift.
- **The 75-minute ceiling on the routine as written** — warm-ups included (a "find the load" set on every new movement).
  Accessories go last-listed first; anchors never.
- **One story**: the rationale keeps the selection's lines (pick, tier, hold or rotate and why), the swaps, the time trim and
  the fatigue decision; a lift that lost sets for recovery says so on its own Hevy note ("2 sets today: recovery.").

**The programming pass (`live_program`, red-team fixes, 2026-11-13).** Every rule is a labelled heuristic table in the module
(`LOAD_POLICY`, `DELOAD_SHAPE`, `PAIN_RULE`, `STACK_RULE`, `STALL_RULE`, `TRUNK_FLOOR`, `TRUNK_FALLBACK_ORDER`), owner-adjustable:

- **Pain by joint.** A pain flag (the classed overlay) or two discomfort notes on one movement reach EVERY movement that loads
  the same joint at moderate or more, every session while the flag stands. The pain-monitoring rule: a stated score at or under
  3/10 (and not "sharp") reduces — 10 % lighter, RPE ≤ 7 — on each joint-loading lift; above it, "sharp", or no number, the
  movements in the flagged PATTERN GROUP (pressing, pulling, hinge, squat) are avoided (swapped for a member under moderate
  stress on that joint, else skipped) and the rest are reduced.
- **Axial stacking avoided, not only detected.** Past two spinal-loading squat/hinge compounds in one session the lowest
  priority goes: an unpinned accessory first (a unilateral slot stays unilateral — a split squat becomes a reverse lunge);
  then an owner-pinned slot is KEPT but light — a technique dose at RPE ≤ 7, load held (`STACK_RULE pinned_light_rpe`); then
  a non-heavy anchor, squat before hinge — but never the session's ONLY squat or ONLY hinge. Second red team: the old order
  protected the pinned kettlebell hinge by swapping the lower-volume day's only squat for a leg press.
- **The kettlebell slot names its implement** (`live_week.kb_slot`, `KB_SLOT`). The KB deadlift logs under Hevy's "Sumo
  Deadlift" (template D20D7BBE, the owner-ruled stand-in — the template stays): its note reads "KB deadlift — logged as Sumo
  Deadlift.", its effort is capped at RPE 7–8 (an entry drill into the swing), and its rows carry the bell on file — its own
  last load, else the swing's — never "find the load" while his history names the bell. Its sets count toward glutes (and
  hamstrings at the secondary credit) through the library target; the catalog's `other` no longer hides them
  (`live_week.landmark_muscle`, also read by the surplus-first trim).
- **One cut per lift per week** (`live_program.mark_retreats`, `LOAD_POLICY one_retreat_per_week`). A lift whose earlier
  exposure this week (the last 6 days, read from the Hevy record — only a session actually done counts) took a guard cut or
  a stall reset holds at its next exposure: no second cut, no second reset (the owner run cut a row on its heavy day and
  stall-reset it on its volume day, the same week).
- **A new movement starts moderate** (`live_week.novel_start`, `NOVEL_START`). A movement swapped in that he has not done
  this block starts at 6–8 reps, RPE ≤ 7 (the novel-again caps, OD1) — never a 4–6 strength range with a load to find, and
  never so on a deload.
- **A vertical pull survives a garage** (`live_week.vertical_pull_fallback`, `VERTICAL_PULL_FALLBACK`). With no pulldown
  station the anchor takes the first servable key in order — a band-assisted pull-up (when the library carries one), a
  negative, the pull-up/chin-up (each only while its gates open: fail-closed), then the dumbbell pull-over.
- **Sets before exercises** (`live_week.trim_sets_for_time`). When the routine as written runs past the ceiling, working sets
  come off the accessories whose muscles sit over MAV, then over MEV (never taking the week under MEV; two sets, then one)
  before any accessory is dropped whole; pinned slots and live additions are never trimmed.
- **Stalled anchors change.** A stalled anchor (no new best e1RM over 3+ exposures at working effort; never a `step_due`)
  moves its rep range up 2 at 10 % less load ("Now aiming 6–8: stalled, lighter reset.").
- **Function in the week.** The shoulders+arms session carries one trunk-STABILITY drill (anti-extension / anti-rotation /
  anti-lateral flexion, never a carry; best functional tier, familiar first; skipped on a strained day, first to go on time).
  A trunk slot whose movement the gym can't serve and with no same-function member takes the nearest dynamic trunk job
  (`TRUNK_FALLBACK_ORDER`; a loaded or stable drill first; `bodyweight_weighted` accepted under live only).
- **The short week** (`short_week_roles`, library `programming_settings.short_week_rule`, live default `skip_shoulders_arms`):
  four mornings skip shoulders+arms, so both lower days keep 2x; the carry and the trunk floor move to the week's last
  session. Delts and arms sit at their floor that week. The cron's session sequence still slides (it credits by position):
  wiring the skip into `session_sequence` is an owner decision.

## 5. Progression

**The live load guard** (`live_program.guard_loads`, after the floor and the double progression, before the back-offs and
warm-ups): under live a load never steps UP on a regressing lift, a lift whose last top set was a grind (RPE 9+) at the bottom
of its range, a stalled lift, or on a strained/overreached day — it holds at the last top set (where that set reached the top
of the range at RPE ≤ 8.5, the session's own in-session step line stays: start where you were, step only if set 1 is easy).
It steps DOWN 10 % on a regression, 5 % on an anchor whose last top set overshot its band (RPE ≥ 9.5), 10 % under a joint
flag or a stall reset, rounded DOWN to the implement. **A regression cut needs effort evidence** on every lift (`LOAD_POLICY
evidence_rpe`, second red team): a lift cuts for a regression only when its last top set was RPE 9+ or under the rep range's
floor (or a joint flag stands); a trend alone HOLDS ("Same load: trend down, effort fine."). The e1RM trend is noisy on an
isolation lift (a dumbbell jump, a stack) and on a compound trained in two rep ranges (the heavy and the volume day). On the owner's real run a dumbbell lateral raise read "strength sliding" and dropped a dumbbell step after
a top set well inside its range at a moderate RPE — one session on the next dumbbell made the e1RM noisy; a cable pulldown
did the same on a stack. The guarded load is written onto the floor audit row the commit gate
reuses (`live_guard`, `floor_kg`), so a down-step is a recorded, sanctioned reduction — never a silent one. Shadow: untouched.

Otherwise unchanged by the epic and live today: `load_progression` (double progression — the top of the range on two same-type
exposures, then +2.5 % in 5-lb steps; RPE vetoes), `load_ramp` (the entry ramp to a share of band e1RM), the stall step
(#5057: the same load × reps three times at an easy RPE steps the load — `step_due` HOLDS the movement), effort ceilings.

The engine's **trend** (`fatigue_model.movement_signals`, read only under live): a movement PROGRESSES when its best e1RM in
the last 14 days beats its best before them; it STALLS when it does not over three or more exposures at working effort; it
REGRESSES when the latest two exposures are both more than 5 % under the best before them. L6 changed the first rule: the old
"latest exposure beats every earlier one" read every tie as a stall — and double progression repeats a load while the reps
climb, and a movement trained twice a week repeats it inside one week — so progressing movements were rotated out.

## 6. Fatigue and recovery (`fatigue_model`, live only)

Signals (each with a labelled threshold, all **heuristic**): readiness tier (+ ACWR, one vote), sleep < 6.5 h, hard cardio
minutes over the conditioning budget, weekly hard sets over MRV, strength regressing, effort drift; discomfort notes; axial
and hinge stacking; adherence. Walking from steps is counted (L4's `cardio_load(steps_by_day)`, read through the one
steps-truth resolver) and reported, but is not a strain vote — a high daily step count is this trainee's baseline.

| Strain signals | Action |
|---|---|
| 0–1 | maintain |
| 2 | reduce: 2 sets off, HIGH-FATIGUE WORK FIRST — compounds' back-offs (never below 2 sets, top set kept), then isolation surplus-first; no load steps up |
| 3+ (or a regressing compound on a red/short-sleep day) | a deload is RECOMMENDED (applies only on the owner's recorded word); meanwhile the DELOAD SHAPE: every compound to 2 sets at RPE ≤ 7 with its load held or stepped down, isolation KEPT (≤ 2 sets, RPE ≤ 8), hard cardio turned easy |
| low adherence over a fully covered fortnight | one step off ISOLATION only — a shorter session is easier to keep; never a recovery verdict, no load hold |

**Why compounds first** (red team, 2026-11-12): the earlier order held every heavy compound (and loaded it heavier) and cut
low-systemic-cost isolation — the wrong way round for "minimise unnecessary fatigue". The weekly SET count on the
high-fatigue profile is not lower than before (59 vs 54: isolation is kept), but the systemic cost is: compounds at 2 sets,
RPE 7, loads down 10 %, no intervals or tempo. Within isolation, the muscle furthest above its MEV gives first (L6).

## 7. Cardio (`cardio_model`, L4)

Its own model: modalities rated on stimulus, control, impact, leg interference and recovery cost; protocols as data (easy,
moderate continuous, tempo, structured intervals, progressive endurance, incline/resistance); steps counted before any added
cardio; progression by duration, then frequency, then intensity; no heart-rate targets. Hevy's "Cycling" and the account's
custom "Recumbent Bike" are one machine and one modality (`cardio_model.LIBRARY_MODALITY`). The PUBLIC conditioning tier caps
at A: S-for-him (A-level, low impact, 10+ of his own sessions) is returned on the model's `n1` field only, for the private
layer — one person's usage count is fit, not modality quality.

**Wired under live** (`live_program.cardio_fit`, over the charter menu's pick in `draft_standing_constraint.cardio_block`):

- a hard block (tempo, hills, intervals) turns easy under a recommended deload or when hard cardio is itself a strain signal,
  never sits on the heavy lower day or the session before it, and — with the shared cap — sits only on shoulders+arms;
- **steps first** (`cardio_model.aerobic_plan` over the steps the cron reads through the one steps resolver): an easy block is
  dropped when the week's steps already cover the aerobic volume — the walking IS the easy aerobic; unread steps never count;
- **`programming_settings.session_cap_includes_cardio`** (library setting, default `false` = today's 75-minute LIFTING cap
  with the cardio block apart): `true` makes the 75 minutes cover lifting + cardio — a block shrinks to what lifting leaves,
  under 10 minutes it is dropped — and hard conditioning lands on shoulders+arms;
- a conditioning note ends with a generic symptom line, `programming_settings.symptom_line` (default "Chest, breathing,
  dizzy? Stop, log it." — one phone line; no condition named, no heart-rate number; the wording is the owner's decision);
- **hard work turns easy on a bad day** (second red team): a strained state, or a red-readiness / short-sleep strain signal,
  turns tempo / hills / intervals easy — not only a recommended deload (a red, 5.6-h week kept its intervals);
- **the medical stop line is read** (`live_week.symptom_gate`). `owner_redlines.TRIPWIRES` `medical_stop_lines` is evaluated
  by its one reader, `health.tripwire_readers.medical_stop_lines` (report-only). The cron (live only) runs that reader over the
  whoop rows it already reads (one read widened to the RHR arm's 14 nights; nothing inside an HR-regime window) and hands the
  row to the draft: TRIPPED → no hard cardio, a review line on the rationale and on the conditioning note. Traced, not grepped:
  the palpitations and syncope arms are SELF-REPORT with no input on the platform — they read `unknown` (never clear, never
  tripped) until the check-in lane (#5819) supplies one; the labs arms read unknown here (no labs read); the RHR rise can trip;
- **week-to-week progression** (`live_week.cardio_progress`): the block's minutes follow `cardio_model.progress` over his
  performed blocks of the same kind — symptoms, recovery and LOGGED effort first (an unlogged RPE holds), then duration (+5
  min, within the menu's cap), then frequency, then intensity; a frequency or intensity step is named for the owner (the
  charter's placement owns frequency);
- **cardio room under the shared cap** (`live_week.make_cardio_room`, `CARDIO_ROOM`): on the conditioning host (and on any
  day the steps do not cover the easy volume) the charter's antagonist supersets pair first, then sets come off the muscles
  over MAV (they buy the whole block), then the largest surplus over MEV (it buys the 20-minute minimum) — the red team's
  shared-cap week served a 13-minute stub while the delts sat at 18 sets (MAV 16);
- the loss-rate band (`health.rate_policy.propose_band`) appears in the rationale as ADVISORY text only — nothing reads it back,
  no kcal or titration changes.

## 8. Heuristic vs evidence-backed

| Evidence-backed (verified citation, ±1 band) | Practitioner consensus (labelled) | Platform heuristic (labelled, owner-adjustable) |
|---|---|---|
| lengthened-position loading for some muscles; the glute stretch cap (Plotkin 2023); 14 direct-trial and 7 characteristic-trial hypertrophy rows | the functional, conditioning and mobility rubrics; joint-stress ratings; cue sheets; pain monitoring by a stated score | every fatigue threshold; the 14-day trend window; MAX_WEEKLY_EXPOSURES 2; MAX_HOLD_WEEKS 12; MAX_NEW_PER_WEEK 2 (new = not performed in RECENT_DAYS 28); upgrades at block start; the systemic-slump rule (4 lifts, half); fatigue cost; surplus-first trimming; the adherence step; `live_program` LOAD_POLICY (−10 % / −5 % / RPE 9.5 / RPE 9, evidence RPE 9, one retreat per 6 days), DELOAD_SHAPE, PAIN_RULE (3/10), STACK_RULE (2 per session, pinned light at RPE 7), STALL_RULE (+2 reps, −10 %), TRUNK_FLOOR, TRUNK_FALLBACK_ORDER, MIN_CARDIO_MINUTES 10; `live_week` KB_SLOT (RPE 7–8), CARDIO_ROOM (20-min block, 2-set floor), BEHIND_SCHEDULE (5 of 10 missed, ~45 min, 2 sets), NOVEL_START (6–8, RPE 7), VERTICAL_PULL_FALLBACK |

Volume landmarks (`config/training_landmarks.json`) are practitioner landmarks, not individual measurements.

## 9. What flipping `status: approved` turns on — the approval checklist

Flipping the status is the owner's act and the only switch. It turns on, at once:

1. accessory slots served from the library by the live policy (holds, named triggers, repetition rule, trunk function,
   systemic slump, the novelty budget, block-start upgrades), with gates read from #5772's evaluation;
2. the live session fit: equipment and pain on every exposure (anchors swapped or skipped), the routine's 75-minute fit;
3. the fatigue model's graded reduction in place of the red-day accessory drop, with ACWR mapped and steps counted;
4. the cron's real readiness, sleep, ACWR, 7-day sets and steps (instead of the hard-coded yellow/safe/empty);
5. fallback lines on the Hevy note, the free-weight floor as a BLOCK, the block design review's approved picks.

Before flipping, the owner should decide (each is listed on the epic's PRs):

- [ ] the heuristic thresholds (`fatigue_model.THRESHOLDS`, `selection_live` constants) — accept or adjust;
- [ ] home_gym equipment still `unknown` (hip abduction/adduction machines, belt and pendulum squat, sled, pullover and incline
      chest press machines, stair machine) — confirm, or they stay out;
- [ ] the 31 custom Hevy templates L2 lists (Copenhagen, tibialis raise, step-down, serratus punch, …) — approve or not;
- [ ] retiring ruling B and the 3-week forced rotation under live (holds replace them);
- [ ] the HR leftovers L4 lists (`critics_aerobic`, `DAY_SHAPE`, `recent_aerobic`'s HR flag, `_recovery_tier`'s window);
- [ ] the short-week rule (L5: skip shoulders + arms rather than slide the sequence) — built as a live option (default skip);
      wiring it into `session_sequence` (which credits by position) is a separate change;
- [ ] whether a fatigue-model reduction applies automatically (as built) — deloads stay his word either way;
- [ ] `programming_settings.session_cap_includes_cardio` — `false` (75-min lifting + a separate block; mornings up to ~95 min
      when a conditioning block lands) or `true` (75 minutes for everything; one hard block a week on shoulders+arms);
- [ ] `programming_settings.symptom_line` — the wording of the generic stop-and-log line on conditioning notes;
- [ ] the live heuristics in `live_program` (load down-steps, the deload shape, the 3/10 pain line, the stacking cap, the stall
      reset, the trunk floor) — accept or adjust;
- [ ] the week's third hinge exposure is the owner-pinned kettlebell slot — kept, but as a technique dose (RPE ≤ 7) when it is
      the session's third spinal-loading lift, so lower volume keeps its squat (strength would keep the squat and drop the KB
      hinge; recovery would accept a leg press — the panel disagrees, the default keeps both);
- [ ] `programming_settings.behind_schedule_week` (default `false`): after 5+ of the fortnight's 10 planned sessions are missed,
      a four-session "keep the anchors" week (anchors + one accessory per major muscle, two sets each, ~45 min) instead of
      trimming sets — wiring the four-session sequence into `session_sequence` is a separate change, as for the short week;
- [ ] `programming_settings.press_sets` (default `1`, the charter's `overhead_press_per_wk`, #5162): the shoulders+arms press at 2+
      sets, each taken from the face pull;
- [ ] the symptom-line wording — whether to add "heart racing or irregular" (the default is unchanged);
- [ ] the novelty budget's reach: on the flip, the current phase's ledger (written in shadow by the #5075 calendar) is served
      only within the budget — the rest of the shadow rotation waits;
- [ ] showing the loss-rate band as advisory text in the rationale (no nutrition change either way).

## 10. How it is validated

- `tests/test_acceptance_5861.py` — the brief's §11 acceptance gates over the integrated engine in live mode, each with a
  must-fail control.
- `scripts/sample_weeks_5861.py` — a full program week (five roles, cardio, Hevy notes as compiled) for six synthetic
  profiles, measured against the volume landmarks, the time model and axial stacking.
- `tests/test_no_live_change_5861_l6.py` — the proposed-mode drafts pinned against the base tree.
- The red-team outcome gates (2026-11-13), each with a must-fail control run: no load rises under overreach and compounds are
  cut before isolation (c4, c4b); pain reaches every joint-loading movement (c2c); a stalled anchor changes its scheme (c5);
  no session carries a third spinal-loading squat/hinge (d2b); the whole morning fits with the shared cap (d3b); abs reach
  MEV from direct trunk work, not carries, and the short week keeps every leg muscle at MEV (d1); a WEEK programs single-leg,
  carry, trunk-stability and aerobic work (b2); nothing is added without a landmark purpose (d5).
- The second red team's gates (2026-11-13): d1 now checks the DISTRIBUTION (no major muscle over MAV while another is under
  MEV); b2 needs a 20-minute aerobic block or the steps-dose rationale, not any block; d2b keeps a squat and a hinge in every
  lower session (its control replays the old precedence that swapped the squat out); d3b keeps a 20-minute block under the
  shared cap. `tests/test_programming_fix2_5861.py` reproduces each real-data failure of the owner run with a synthetic
  fixture SHAPED like it — a noisy isolation history (a dumbbell jump; the trend reads "regressing", the effort does not), a
  row cut on Monday and stall-reset on Thursday, a shadow-era ledger rotation carried into the phase — plus the KB slot,
  the stop line (and the cron's read), the cardio progression, the garage vertical pull, the new-movement rep range, the
  press option and the behind-schedule option, each with its control.
