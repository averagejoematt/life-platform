# The training engine: how a session is chosen, progressed and kept recoverable (#5861)

> **Status:** describes the integrated engine of epic #5861 (lanes L1–L6). **Everything new runs only once the owner
> approves the exercise library** (`config/exercise_library.json` `"status": "approved"`). Until then today's drafts are
> served unchanged, byte for byte (`tests/test_no_live_change_5861_l6.py`, `tests/test_no_live_change_5861_l3.py`).
> **Written:** 2026-11-12, against charter 1.49.0, library 0.2.0 (`proposed`), the #5799 time model (99 s a set, measured).
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
live_session.for_live_draft (LIVE)                 equipment + pain on EVERY exposure, then fatigue_model (one reducer)
        ▼
full_body_session.full_body_routines               loads (load_ramp / load_progression), warm-ups, composed Hevy notes,
        │                                          the routine's own time fit (LIVE), rationale
        ▼
mcp.draft_standing_constraint.gate_draft           the session block, the cardio block (cardio_menu)
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
   **Novelty is budgeted** (L6): at most two new-to-him movements enter in a week; past that a rotation takes the best
   familiar candidate. A held movement is never "new".
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

## 5. Progression

Unchanged by the epic and live today: `load_progression` (double progression — the top of the range on two same-type
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
| 2 | reduce: 2 accessory sets off, anchors and top sets held |
| 3+ (or a regressing compound on a red/short-sleep day) | a deload is RECOMMENDED (applies only on the owner's recorded word); 4–6 accessory sets off meanwhile |
| low adherence over a fully covered fortnight | one step off — a shorter session is easier to keep; never a recovery verdict |

**Where the sets come from** (L6): the accessory whose muscle the week loads furthest above its MEV landmark gives first
(the delts, near MAV), so a recovery trim does not take a muscle sitting at its minimum effective dose below it first.

## 7. Cardio (`cardio_model`, L4)

Its own model: modalities rated on stimulus, control, impact, leg interference and recovery cost; protocols as data (easy,
moderate continuous, tempo, structured intervals, progressive endurance, incline/resistance); steps counted before any added
cardio; progression by duration, then frequency, then intensity; no heart-rate targets. The live cardio block is still the
charter's menu (`cardio_menu`: two conditioning blocks a week, ≤ 30 min). Hevy's "Cycling" and the account's custom
"Recumbent Bike" are one machine and one modality (`cardio_model.LIBRARY_MODALITY`).

## 8. Heuristic vs evidence-backed

| Evidence-backed (verified citation, ±1 band) | Practitioner consensus (labelled) | Platform heuristic (labelled, owner-adjustable) |
|---|---|---|
| lengthened-position loading for some muscles; the glute stretch cap (Plotkin 2023); 14 direct-trial and 7 characteristic-trial hypertrophy rows | the functional, conditioning and mobility rubrics; joint-stress ratings; cue sheets | every fatigue threshold; the 14-day trend window; MAX_WEEKLY_EXPOSURES 2; MAX_HOLD_WEEKS 12; MAX_NEW_PER_WEEK 2; upgrades at block start; the systemic-slump rule (4 lifts, half); fatigue cost; surplus-first trimming; the adherence step |

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
- [ ] the short-week rule (L5: skip shoulders + arms rather than slide the sequence) — today a short week leaves legs at once;
- [ ] whether a fatigue-model reduction applies automatically (as built) — deloads stay his word either way.

## 10. How it is validated

- `tests/test_acceptance_5861.py` — the brief's §11 acceptance gates over the integrated engine in live mode, each with a
  must-fail control.
- `scripts/sample_weeks_5861.py` — a full program week (five roles, cardio, Hevy notes as compiled) for six synthetic
  profiles, measured against the volume landmarks, the time model and axial stacking.
- `tests/test_no_live_change_5861_l6.py` — the proposed-mode drafts pinned against the base tree.
