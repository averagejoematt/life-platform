# The training engine: how a session is chosen, progressed and kept recoverable (#5861)

> **Status:** describes the integrated engine of epic #5861. **Everything new runs only once the owner approves the exercise
> library** (`config/exercise_library.json` `"status": "approved"` AND a valid `"approved_on"` day — fix round 11, fail-closed:
> an approved library without its day behaves exactly as proposed). Until then today's drafts are served unchanged, byte for
> byte (`tests/test_no_live_change_5861_l6.py`, `tests/test_no_live_change_5861_l3.py`).
> **Current state (fix round 9, consolidation):** eight fix rounds stacked rules on rules; round 9 replaced them with one
> progression model (`live_load`, §5), one weekly volume plan and one time fit (`live_volume`, §4b) and one settings table
> (`live_settings`, generated below). This document describes the engine as it is, once; the history is in the PRs.
> No personal data: every example is a synthetic profile (`tests/fixtures/sample_week_profiles_5861.json`).
## The principle

**An exceptionally comprehensive library, an exceptionally selective engine.** The library rates 625 movements on five
objectives; the engine serves four to eight of them in a session — the right ones for the slot, his response, his equipment,
his recovery and the 75-minute ceiling — and holds them while they progress. More options is not more training: nothing is
ever added to fill a slot.

## The draft path

```
session sequence (next undone role; the week plan's skipped roles, live_sequence)   program_structure.SESSION_TEMPLATES
        │
        ▼
variant_rotation.for_session ──► selection_engine.apply ──► selection_live (LIVE)   accessory slots, ranked from the library
        ▼
program_structure.session_prescription_for_role                                     anchors resolved, accessories placed
        ▼
live_session.for_live_draft (LIVE)   the week's volume plan (live_volume) -> equipment + pain on every exposure ->
        │                            novelty (live_load) -> pain by joint, stacking, lead lift (live_program.plan) ->
        │                            systemic slump -> the fatigue model (one reducer) -> the session set ceiling
        ▼
full_body_session.full_body_routines   the engine's floor, then THE load model (live_load.set_loads), back-offs, warm-ups,
        │                              composed Hevy notes, THE time fit (live_volume.time_fit), rationale
        ▼
mcp.draft_standing_constraint.gate_draft   the cardio block (cardio_menu, then the LIVE cardio fit)
        ▼
hevy_compiler.to_create_body               the routine as written to Hevy
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
   new to him, a cue sheet (`selection_cue_sheets`); a new pattern's first exposure is capped by the load model (§5, rule 7).
2. **Pool**: the top two non-empty bands (normally S∪A).
3. **Rank inside the pool**: repeated discomfort last, then his **N=1 fit** (the private overlay: progression, pain history,
   sentiment, swap-outs), then a categorical **fatigue cost** (compound, free weight, spinal load; heavier under axial
   stacking — machines and cables win at equal fit, his own response overrides), then slot variety, then tier.
4. **Hold while it progresses; rotate only for a named trigger** — stall/regression, pain, discomfort, equipment, no longer
   servable, a better band (servable this week, and only at a block's first phase — mid-block the upgrade waits, L6),
   adherence (swap-outs), fatigue (axial stacking), the owner's request, or a block-end review after 12+ weeks without
   progress. Never the calendar alone.
   **Novelty is budgeted** (L6; second red team): at most two movements NEW to the served week — a slot serving something it
   did not serve last phase and that he has not performed in the last 28 days — and NONE on a declared short or adherence-dip
   week (fix round 10: that week rebuilds routine first).
   Forced changes (pain, equipment, no longer servable, fatigue, an owner request) keep their place and count; past the
   budget an optional change waits — a stall rotation keeps its place longest, a calendar rotation the live policy never
   asked for waits first — and the slot serves last phase's movement (`selection_live.enforce_novelty`, said so on the
   selection line). A held movement is never "new".
5. **A systemic slump is not a stall** (L6): when four or more judged lifts — and at least half of them — stall or regress
   together, the cause is sleep, recovery or the deficit; the movements hold and the fatigue model takes volume off instead.
6. **Within-week repetition when it helps**: a same-band peer is preferred over a duplicate; when the best band has no unserved
   member, a second weekly exposure of the best movement beats dropping a band (cap 2 a week, by canonical family).
7. **One authority** (fix round 10): under live the selection's pick serves; the rotation ledger records what served and never
   overrides it (the ninth red team's "selection X — THIS phase serves Y").

## 4. The session fit (`live_session`)

What the selection cannot see, because it ranks slots:

- **Equipment and pain on every exposure, anchors included.** An unavailable or pain-flagged anchor takes the next member of
  its pattern that is available, pain-free, servable (no locked gate) and at the anchor's skill ceiling; after a pain or
  repeated-discomfort flag the replacement must load the flagged movement's worst joint *less*. A vertical pull with no
  pulldown station takes the first servable vertical pull (`live_week.VERTICAL_PULL_FALLBACK`, gates fail-closed). With none,
  the exposure is **skipped and said so** — never an impossible or painful prescription, never a filler.
- **Pain by joint, one rule** (`live_program.joint_flags` / `apply_joint_rule`, `live_pain`, `live_safety`; fix round 10). A pain
  flag or two discomfort notes on one movement reach every lift that loads the same joint at moderate or more, whatever its
  pattern. Every lift reached HOLDS its load (no step up while a flag stands), runs at RPE <= `PAIN_RULE` pain_rpe with the in-set
  stop line. Above the mild line (`PAIN_RULE` mild_max) with a STATED score only the provoking lift is ROUTED (fix round 11, the
  tenth red team: a 4/10 hip flag on the split squat had removed every lower compound); a "sharp" note or one with no number
  also routes its pattern group and any lift loading the joint HIGH. A route is a pain-free same-family member, else a movement for the
  same muscle, each REVIEWED and LOW on the flagged joint (a defaulted, unreviewed row is never a route — ruling 16); with none
  the muscle is said to be zero this week by design. What the gym or the pain rule took goes back through the ONE spend step
  (`live_volume.spend_session`), from reviewed, low-stress movements only; a morning still under `min_session_minutes` says why. Discomfort at or under
  `PAIN_RULE` lift_only_max changes only that lift. The low back is the `spinal_load` case of the same rule. No symptom warning
  line on any session (owner ruling 10).
- **Axial stacking, a real limit** (`live_program.avoid_stacking`, `STACK_RULE`): past two spine-loading squat/hinge compounds in
  one session (`live_balance.spine_loading`, the one definition) an accessory is swapped for a member that is not spine-loading,
  else dropped; then a non-heavy anchor — never the session's only squat or only hinge.
- **The heavy lower day** (owner ruling 5): the deadlift is a top set + one back-off (`live_shape.deadlift_shape`); squat and
  deadlift are never both maximal — the squat always LEADS at the session's effort, the deadlift is capped at `deadlift_rpe`
  (`live_rulings.lead_lift`; fix round 11: the ISO-week alternation and the lead by state made a ratchet and are gone). On a
  full-body morning after a spine-loading day, a guest squat/hinge takes a low-spinal-load member (`live_program.axial_yesterday`).
  The squat comes before the hinge whenever both are in one session (`live_shape.order_lower_volume`).
- **One graded reducer** (`fatigue_model`, §6): readiness and ACWR are one vote among independent strain signals.
- **The session set ceiling** (`live_volume.fit_sets`) and **the 75-minute ceiling on the routine as written**, warm-ups
  included (`live_volume.time_fit`) — both by the ONE trim order of §4b.

## 4b. The weekly volume plan and the one time fit (`live_volume`)

**One weekly hard-set plan per muscle** (`week_plan`), computed from the five templates and the mornings declared this week —
the same for every morning of that week:

- **Targets** (`targets`): a priority muscle (`priority_muscles`, ruling 9) has a floor of MEV and an aim ABOVE it —
  `priority_aim_share` of the way to MAV, and on a full week at least one set over the busier arm (`ARMS`); every other muscle a floor of its maintenance volume
  (MV), an aim of MEV on a full week, and a cap of MAV; direct abs `abs_direct_sets_per_week`
  (ruling #8; halved on a 1-3 morning week; indirect trunk loading never counts); on a 4-morning week the
  shoulders, biceps and triceps are held at MEV (ruling 3). Each delt head is counted apart (ruling #9) with explicit credit by
  library pattern (`set_credit` delt: pressing -> front, overhead pressing -> half a side, rowing -> rear); the side and rear
  heads have their own aims (`delt_heads`).
- **Sizing — the ONE spend step** (`spend`, fix round 11): isolation surplus over the cap gives first (largest slot, never under
  2 sets, never a delt head under its aim); then, while a muscle sits under its aim, the one furthest under it (a share of its
  aim; under its floor first; on a tie the one trained longest ago — `last_trained`, the weekly memory that rotates short weeks)
  takes a set on the morning of its half of the body with the most free minutes (`plan_minutes` / `free_minutes`, the one time
  model; the conditioning host keeps `conditioning_reserve_minutes` for non-priority work): its isolation slot grows (never past
  3 sets), else a 2-set FILL movement joins (reviewed, served by the gym). Time or the owner's weekly set redline short, a muscle
  OVER its own aim gives the set — never under its aim, never a muscle's last isolation slot of the week. Nothing is cut to make
  a priority look bigger. Every template slot is served at the 3-set slot cap at most. The overhead press runs `press_sets` (ruling 6); its extra sets come off the lateral raises.
  `press_trade_alternative` reports the rear-delt alternative in numbers (not applied).
- **No kettlebell hinge slot** (owner rulings #2/#6/#7): the swing stays gated and optional and never fills a hinge slot.
- **Short weeks** (`SHORT_WEEKS`, owner ruling #5; 1-5 declared mornings): four mornings skip shoulders+arms; one to three are
  FULL-BODY mornings — the host role's anchors plus a partner role's named anchors, 4-6 movements at 2-3 working sets, never a
  1-set anchor, the anchors paired as antagonist / upper-lower sets (`FULL_BODY_PAIRS`) so the work fits the morning. Each
  priority muscle and each major pattern holds maintenance (MV x mornings / `short_week_floor`, at least 2 sets); a priority
  muscle aims at MEV pro rata; the rest aim at MV pro rata with no floor, so the few free slots rotate through the weekly memory. An adherence dip (5+ of the fortnight's 10 planned sessions missed, `live_sequence.DIP_MISSED`) is one 4-morning
  week, never two in a row for one gap (ruling 2).
- **The ONE hard-set counter** (`hard_sets`) over THE one set-credit table (`set_credit`): a working set prescribed at
  `hard_rpe`+ counts, primary 1.0, each secondary (library secondaries plus every other rated muscle) half a set unless `never`
  drops it (no indirect ab sets, no hip-thrust quadriceps, no leg-curl calves), delt heads direct or by pattern. The sample-week script and the deliverables read it.

**One time fit** (`next_cut`, `time_fit`, `fit_sets`): the 75-minute morning as written (warm-ups included) and the session set
ceiling, by ONE order — non-priority accessory back-offs, then non-priority anchor back-offs, then a whole 2-set accessory whose
muscle stays over its floor without it, then a priority (or floor-holding) muscle's back-offs, the one furthest over its floor
first; then a carry, any other whole non-priority accessory at 2 sets, then a priority one. Anchors never go under 2 sets and are
never dropped. Under the shared cap (ruling 1) the conditioning block takes only the minutes lifting leaves — no strength set is
cut for cardio — and the week's hard conditioning dose sits on the morning with the most free minutes
(`live_volume.conditioning_host`; never the heavy lower day or the morning before it).

## 5. Progression (`live_load`, the one model)

Keyed by SESSION ROLE (a heavy day and a volume day are two lifts, even on one Hevy template) and, on the heavy lower day, by
LEAD STATE (a lead progresses from its own lead days, never from the capped second-lift day before it):

1. **Double progression.** The load is the last same-role top load (an exposure in the last `history_days`). When every set at
   that load reached the top of the rep range at or under RPE 9 (or with effort unknown), it steps up one implement step;
   otherwise it holds and the reps climb. With no same-role exposure in the window the engine's own ramp load stands.
2. **Down, under the floor** (`below_floor`, fix round 10): the top set under the rep range's floor in the last
   `below_floor_exposures` same-role exposures — down at least `step_down_pct`, and as far as the last exposure says reaches the
   floor with three in reserve (`floor_load`). NOTHING blocks it: a slump, strain, pain or first-back hold stops only a step up.
   Every lift, the capped deadlift included, needs two exposures under the floor (fix round 11).
3. **Effort unknown** (`effort_unknown`): no RPE logged, or every logged set at `implausible_rpe`+ — the step up rides on reps
   alone; a load moves down only on reps under the floor, never on effort.
4. **Systemic slump — the ONE performance signal** (`slump`): `slump_anchors` or more anchors declining together (each read by
   `fatigue_model.declined`: the latest two same-role exposures both more than 5 % under the median of the earlier ones; in a
   deficit, half of them) — no load steps up, non-priority accessories lose about a third of their sets (`slump_accessory_cut`),
   and it is the fatigue model's one `strength` vote (no separate effort-drift vote); a lift under its floor still steps down.
5. **First session back** (owner ruling #10): `layoff_days`+ with no session — each lift's first session back runs at
   `first_back_rpe` at its last same-role load, no step; after `long_layoff_days`+ it starts `long_layoff_pct` under it.
6. **The capped deadlift** (ruling 5): an ordinary lift of this model — up at the top of its range at or under its cap.
7. **Novelty, three rules** (`mark_novelty`): a NEW pattern (none logged in `familiar_days`) runs one exposure at
   `new_pattern_rpe`; a FAMILIAR pattern (a biomechanically similar swap included) works at normal effort with no re-entry cap
   (the note composer's OD1 cap and layoff line are dropped for it under live); the layoff rule is rule 5.
8. **One bounded in-session step** (R3, pending the owner's confirmation; `r3_eligible`, `live_safety.r3_lines`): set 1 at RPE 7
   or easier on a straight-set lift the load model neither holds for a reason, steps down, caps at 7 nor treats as new -> one
   load step on the later sets; never down in-session.

Strain, a recommended deload, a slump, a first session back and a joint flag are each a HOLD through the same decision
(`decide`): they stop a step up, never a step down under the floor. Each lift's note carries ONE reason line, and only where
it changes what he reads (a hold for a reason always says it); the engine's in-session load-step lines are dropped
(`live_safety.no_step`) and only the bounded R3 line returns where rule 8 allows; each lift note fits four phone lines
(`live_safety.cap_lines`). The decision is written onto the floor audit row the commit
gate reuses (`live_load`), so a down-step is a recorded, sanctioned reduction. Shadow: untouched.

The engine's **trend** (`fatigue_model.movement_signals`, live only, read by selection and the fatigue model) is judged within
the latest exposure's session role: progressing (a new best e1RM in 14 days, or a heavier top load), stalled (none over three
exposures), regressing (`declined`: the latest two both more than 5 % under the median before them).
## 6. Fatigue and recovery (`fatigue_model`, live only)

Signals (each with a labelled threshold, all **heuristic**): readiness tier (+ ACWR, one vote), sleep < 6.5 h, hard cardio
minutes over the conditioning budget, weekly hard sets over MRV, the ONE performance vote (the systemic slump); discomfort notes; axial
and hinge stacking; adherence. Walking from steps is counted (L4's `cardio_load(steps_by_day)`, read through the one
steps-truth resolver) and reported, but is not a strain vote — a high daily step count is this trainee's baseline.

| Strain signals | Action |
|---|---|
| 0–1 | maintain |
| 2 | reduce: 2 sets off, HIGH-FATIGUE WORK FIRST — compounds' back-offs (never below 2 sets, top set kept), then isolation surplus-first; no load steps up |
| 3+ (or a regressing compound on a red/short-sleep day) | a deload is RECOMMENDED (applies only on the owner's recorded word); meanwhile the DELOAD SHAPE: every compound to 2 sets (an anchor's top set at RPE 8 until he confirms the deload, RPE ≤ 7 once he does) with its load held, isolation KEPT (≤ 2 sets, RPE ≤ 8), hard cardio turned easy |
| low adherence over a fully covered fortnight | one step off ISOLATION only — a shorter session is easier to keep; never a recovery verdict, no load hold |

**Why compounds first** (red team, 2026-11-12): the earlier order held every heavy compound (and loaded it heavier) and cut
low-systemic-cost isolation — the wrong way round for "minimise unnecessary fatigue". The weekly SET count on the
high-fatigue profile is not lower than before (59 vs 54: isolation is kept), but the systemic cost is: compounds at 2 sets
at RPE 7-8 with loads held, no intervals or tempo. Within isolation, the muscle furthest above its MEV gives first (L6).

## 7. Cardio (`cardio_model`, L4)

Its own model: modalities rated on stimulus, control, impact, leg interference and recovery cost; protocols as data; recorded
activity before any added cardio; progression by duration, then frequency, then intensity; no heart-rate targets.

**Wired under live** (`live_program.cardio_fit`, over the charter menu's pick):

- purposeful cardio only (ruling 4): a gym block exists for a named purpose — the week's conditioning dose
  (`hard_conditioning_doses`) on its host, or a week the record shows short of the aerobic floor;
- recorded activity first (ruling 12): outside-the-gym minutes with intensity evidence are credited; steps are reported, never
  credited; unknown intensity is reported, never a manufactured deficit; one optional walk prompt a week when the record shows
  a gap;
- a hard block turns easy under a recommended deload, strain or a short night, never sits on the heavy lower day or the session
  before it; a tripped medical stop line (including a self-reported symptom on a Hevy note) means no hard cardio;
- the shared cap (`session_cap_includes_cardio`, ruling 1): the block takes the minutes lifting leaves; under 10 it is dropped;
- the loss-rate ceiling (`rate_ceiling_pct_bw`, ruling 11) is one ADVISORY line a week — nothing about nutrition changes.

## 8. Heuristic vs evidence-backed

Evidence-backed (verified citation, moving a tier one band at most): lengthened-position loading for some muscles and the
direct-trial hypertrophy rows. Practitioner consensus (labelled): the functional, conditioning and mobility rubrics, joint-stress
ratings, cue sheets, pain monitoring by a stated score. Everything else the live engine decides with is a platform HEURISTIC —
labelled, owner-adjustable and listed once in the generated table below. Volume landmarks (`config/training_landmarks.json`)
are practitioner landmarks, not individual measurements.

## Settings and heuristics (generated)

Generated from `lambdas/training/live_settings.py` by `scripts/gen_live_settings_doc_5861.py` (`--check` fails on drift); the
library builder writes `programming_settings` from the same table.

<!-- GENERATED:live_settings BEGIN -->
| Setting | Default | Provenance | What it does |
|---|---|---|---|
| `session_cap_includes_cardio` | `True` | owner ruling 1 (2026-11-13) | lifting and gym cardio share the 75-minute cap; the conditioning dose takes only the minutes lifting leaves (no strength work is cut for cardio). False: the cap is lifting only and the cardio block sits apart |
| `press_sets` | `3` | owner ruling 6 (2026-11-13) | overhead-press working sets a week (2 or 3), taken from the side-delt (lateral raise) sets |
| `priority_muscles` | `['chest', 'quadriceps']` | owner ruling 9 (2026-11-13) | muscles aimed above MEV — a quarter of the way to MAV (`priority_aim_share`) — filled from low-fatigue isolation in the week's free minutes, never by cutting another muscle; trimmed last for time and by a slump |
| `abs_direct_sets_per_week` | `4` | owner ruling #8 (fix round 8) | challenging DIRECT ab sets a week, spread over the mornings; indirect trunk loading never counts; halved on a 1-3 morning week (a high-fatigue day's trim is the fatigue model's) |
| `hard_conditioning_doses` | `1` | owner follow-up ruling (2026-11-13) | hard conditioning blocks a week (the week's conditioning host takes the first; 2 adds `live_rulings.SECOND_HOST`) |
| `rate_ceiling_pct_bw` | `1.0` | owner ruling 11 (2026-11-13) | the ADVISORY upper planning reference for weekly loss, % of current bodyweight; never applied to a target |
| `sequence_rule_from` | `None` | owner ruling #4 (fix round 8) | the first Monday the week rules judge; None = the Monday after the library's approval; earlier history is kept, never re-sequenced |

| Heuristic | Value | Rule | Basis | Re-tuned on |
|---|---|---|---|---|
| `history_days` | `56` | progression | a same-role exposure in the last 8 weeks is a load reference; older, the engine's own ramp load stands | block retro: how often a lift returns after >8 weeks |
| `below_floor_exposures` | `2` | progression | fix round 10: the top set under the rep range's floor in two same-role exposures running steps the lift down (at least step_down_pct; as far as the last exposure says reaches the floor with 2 in reserve) — nothing blocks it (a slump, strain, pain or first-back hold stops only a step up); RPE plays no part, so missing or always-10 RPE never moves a load down on its own | block retro: exposures spent under the floor; step-downs followed by a new best within 3 weeks (too eager) |
| `step_down_pct` | `5` | progression | the smallest step-down: 5% under the last top load (one implement step on most lifts); a larger step only when the last exposure says 5% still leaves him under the floor | block retro: e1RM a month after each step-down |
| `implausible_rpe` | `9.5` | progression | RPE missing on every set, or >= 9.5 on every set, is EFFORT UNKNOWN: the step up rides on reps alone; a load moves down only on reps under the floor, never on effort | block retro: RPE calibration report (rpe_calibration) |
| `slump_anchors` | `4` | progression | four or more anchors declining together (or, in a deficit, at least half of them) is systemic — sleep, recovery or the deficit, not the lifts: no load steps UP and non-priority accessory volume comes down about a third (a lift under its floor still steps down) | block retro: anchor e1RM across the block vs sleep and loss rate |
| `slump_accessory_cut` | `0.34` | progression | the slump's volume answer: about a third of each accessory's working sets (never under 2); anchors keep theirs | block retro: recovery markers in the weeks after a slump hold |
| `deadlift_rpe` | `8` | progression | owner ruling 5 (fix round 11, the tenth red team's simpler rule): the squat always leads the heavy lower morning; the deadlift is a top set + one back-off capped at this RPE — never both maximal — and steps up after a top set at the top of its range at or under it, like every lift | block retro: squat and deadlift e1RM trend over the block |
| `familiar_days` | `56` | novelty | a movement pattern logged in the last ~8 weeks is familiar (a biomechanically similar swap included): normal effort, no re-entry cap | block retro: first-exposure RPE vs the cap |
| `new_pattern_rpe` | `7` | novelty | a NEW pattern runs one exposure at RPE <= 7 (technique, soreness); then normal effort | block retro: soreness / discomfort notes after a new pattern |
| `layoff_days` | `10` | novelty | owner ruling #10 (fix round 8): after 10+ days with no session, each lift's FIRST session back runs at RPE 8 at its last same-role load, no step; normal progression from the next exposure | block retro: second-session performance after a layoff |
| `first_back_rpe` | `8` | novelty | see layoff_days | see layoff_days |
| `long_layoff_days` | `21` | novelty | fix round 11 (the tenth red team: a 38-day layoff returned at the last load and ground under the floor): after this many days with no session the first session back starts long_layoff_pct under the last same-role load; 10-20 days stays the RPE-8 hold at the last load (owner ruling #10: no long deload either way) | block retro: first-back top-set reps vs the rep floor, by gap length |
| `long_layoff_pct` | `7.5` | novelty | see long_layoff_days: the middle of a 5-10% return dose (practitioner consensus for 3+ weeks of detraining), floored to the implement; normal progression from the next exposure | see long_layoff_days |
| `hard_rpe` | `8` | volume | a working set prescribed at RPE >= 8 (the top of its effort line) is a hard set; the ONE counter | block retro: logged RPE of prescribed hard sets |
| `set_credit` | `{'secondary': 0.5, 'delt': {'horizontal_press': {'front_delts': 0.5}, 'vertical_press': {'front_delts': 1.0, 'side_delts': 0.5}, 'horizontal_pull': {'rear_delts': 0.5}}, 'never': {'*': ['abs'], 'hip_extension': ['quadriceps'], 'leg_curl': ['calves']}}` | volume | THE one set-credit table (fix round 10): a working set credits its target's landmark muscle 1.0 and each secondary — the library's secondaries and every other muscle it is RATED for — `secondary` (half a set, the fatigue model's convention); each delt head direct 1.0, or by `delt` from the lift's pattern (pressing -> front and, overhead, half a side; rowing -> rear — practitioner consensus, explicit so it can be argued with); `never` drops a credit the anatomy does not support (indirect trunk loading is never an ab set, owner ruling #8; a hip thrust trains no quadriceps; a leg curl no calves) | none (convention) |
| `slot_max_sets` | `3` | volume | an accessory slot takes at most 3 working sets — a template slot written at 4 is served at 3 (fix round 10: the calf slots); 4+ in one slot is junk volume | none |
| `slot_min_sets` | `2` | volume | an accessory or anchor never runs one working set: drop, don't shave | none |
| `delt_heads` | `{'side_delts': 6, 'rear_delts': 4}` | volume | owner ruling #9: each delt head assessed apart, direct + indirect; the side delt (no compound trains it much) aims at 6 hard sets, the rear at 4 | block retro: lateral-raise and rear-delt progression |
| `priority_aim_share` | `0.25` | volume | fix round 11 (the tenth red team: 'priority' meant MEV + 1 while back and shoulders got 14-15): a priority muscle aims this share of the way from MEV to MAV (chest and quadriceps 8 -> 10 hard sets), filled from low-fatigue isolation in free minutes — never by cutting another muscle (practitioner consensus: priority = more stimulus) | block retro: priority muscles' performance and the time the plan spent on them |
| `conditioning_reserve_minutes` | `20` | volume | owner ruling 1: under the shared cap the week's conditioning dose takes only what lifting leaves — so the plan leaves this many minutes free on its host morning instead of filling them with isolation (a 1-2 morning week spends its few minutes on lifting first; the dose takes what is left) | block retro: the conditioning minutes delivered |
| `min_session_minutes` | `35` | volume | fix round 11 (the tenth red team's 16-minute pain morning): a morning under this many minutes is said plainly in the rationale with why (the pain rule took work and no reviewed low-stress option exists) — never a filler | block retro: short mornings and their reasons |
| `short_week_floor` | `3` | volume | a 1-3 morning week holds each priority muscle and each major pattern at maintenance: MV x mornings / this value hard sets (at least 2), a priority muscle aiming at MEV x mornings / this value; full-body mornings of 4-6 movements at 2-3 sets — never a 1-set anchor | block retro: anchor e1RM after a short week |

Time-fit order: accessory_backoff -> anchor_backoff -> spare_accessory -> priority_last_set.
<!-- GENERATED:live_settings END -->

## Block-retro hooks (ruling 18)

Every heuristic is re-tuned at a block retro (the `training-review` skill) on a named metric — never by a session's feel. The
consolidated rules' metrics are the generated table's last column (`live_settings.HEURISTICS`); the other labelled tables:

| Heuristic | Re-tune on |
|---|---|
| `live_settings.HEURISTICS` | each row's own "Re-tuned on" column above |
| `cardio_model.MODERATE_METS` | Apple workout intensity vs the session RPE he logged, per modality |
| `cardio_model.CADENCE_MODERATE_SPM` | his own walking cadence at a logged talk-test / RPE (the ~100 spm figure is a population heuristic) |
| `cardio_model.RPE_MODERATE` | logged cardio RPE vs the talk test he notes |
| `rate_policy.CEILING_TAPER` | 4-week loss rate vs anchor e1RM and lean-mass (DEXA) change at each block retro |
| `rate_policy.SUSTAINED_WEEKS` | weeks above the ceiling that preceded an anchor decline, across blocks |
| `rate_policy.SIGNAL_STEP_PCT` | loss rate in weeks with 1, 2, 3 slow signals vs strength the following week |
| `live_program.PAIN_RULE` | pain-note recurrence within 2 sessions of a hold / route, and the flagged muscle's hard sets |
| `live_program.DELOAD_SHAPE` | readiness and first-set reps the week after a deload |
| `live_program.STACK_RULE` | low-back discomfort notes and squat/hinge e1RM in weeks at the cap |
| `live_shape.WALK_PROMPT` | walks logged after a prompt |
| `fatigue_model.THRESHOLDS` | strain calls vs the next session's first-set reps / RPE |
| `quality_rubric.NEUTRAL` | how often a reviewed input moved a provisional row's tier |

## 9. What flipping `status: approved` turns on — the approval checklist

Flipping the status is the owner's act and the only switch — `scripts/approve_exercise_library.py` sets `status: approved` AND
`approved_on` (the day); live mode needs both (an approved library with no valid day runs exactly as proposed, and
`exercise_library.validate` / the builder refuse it). The sequence rules start the Monday after `approved_on` (ruling #4); earlier
weeks are never re-judged. Rolling back: set `status` back to `proposed` (or remove the stamp) — every draft is then the
shadow draft again, byte for byte. It turns on, at once: accessory slots served from the library by the
live policy; the session fit (equipment and pain on every exposure, the weekly volume plan, the time fit); the load model; the
fatigue model's graded reduction in place of the red-day accessory drop; the cron's real readiness, sleep, ACWR, sets and
steps; the week rule in the nightly sequence from `sequence_rule_from` (ruling #4).

Before flipping, the owner decides: the seven settings and every heuristic in the generated table (accept or adjust); ruling
6's press trade from the lateral raises vs the rear-delt alternative (`live_volume.press_trade_alternative`); home_gym equipment
still `unknown` (it stays out until confirmed); the bodyweight readiness gates (all locked); the short week's input (today the
charter's travel windows — a per-week declared count would be better).

## 10. How it is validated

- `tests/test_acceptance_5861.py` — the brief's acceptance gates over the integrated engine in live mode, each with a
  must-fail control.
- `scripts/sample_weeks_5861.py` — a full program week (cardio, Hevy notes as compiled) for the synthetic profiles and every
  stress fixture, under both cap settings, measured with the one hard-set counter against the landmarks and the time model.
- `scripts/progression_sim_5861.py` — multi-week synthetic athletes (steady, gaining, over-performing, one rep short, alternate
  weeks, RPE 10 always, no RPE, slow decline) fed back week to week: no load falls >10 % without step-down evidence, none
  oscillates.
- `tests/test_no_live_change_5861_l6.py` — the proposed-mode drafts pinned against the base tree.
- `tests/test_live_settings_doc_5861.py` — the generated table equals the code, and the library's settings equal the table.
