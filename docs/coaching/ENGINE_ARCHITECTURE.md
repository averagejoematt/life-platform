# The training engine: how a session is chosen, progressed and kept recoverable (#5861)

> **Status:** describes the integrated engine of epic #5861 (lanes L1–L6). **Everything new runs only once the owner
> approves the exercise library** (`config/exercise_library.json` `"status": "approved"`). Until then today's drafts are
> served unchanged, byte for byte (`tests/test_no_live_change_5861_l6.py`, `tests/test_no_live_change_5861_l3.py`).
> **Written:** 2026-11-12, against charter 1.49.0, library 0.2.0 (`proposed`), the #5799 time model (99 s a set, measured).
> **Updated:** 2026-11-13 for the red-team programming fixes (`live_program`, §4–§7, §9): the generated weeks, not the
> architecture, were graded C+; every change below is LIVE-only and measured on the sample weeks. **Updated again** the same
> day for the SECOND red team's programming findings (`live_week`, the novelty budget, the load evidence rule; §3–§10),
> measured on the sample weeks and on the owner's private real-data run. **Updated a third time** (2026-11-13) for the THIRD
> red team (graded B-): `live_balance` (volume by priority, one spine-loading definition and the kettlebell slot's placement,
> pain persistence, the adherence dip, the library fallback, one effort target per lift, cardio host and machine) and the
> library's S quota and two class rules (rubric 3.3.0) — §1–§10 and the new §4b, measured the same two ways. **Updated a fourth
> time** (2026-11-13) for the FOURTH red team (graded B-, safety C): `live_safety` and `live_shape` (the pain site from the note,
> knee and hip, mild pain kept lighter, no load step on a held lift, one effort across the session, the weekly redline, at-MAV
> donors and the quadriceps slot, drop-don't-shave, squat before the hinge, the aerobic gap's walk, the stop line's wording) and
> library 0.3.2 — the new §4c, measured on the sample weeks, three stress profiles and the owner's private run.
> **Updated a fifth time** (2026-11-13) for the FIFTH red team (graded B-, "do not approve yet"): `live_rules` and `live_sequence`
> (the session set cap, full-body short weeks, the pattern off above the mild line, nothing added on a bad day, the KB deadlift as
> filler, light discomfort, the self-reported stop lines, the week rule wired into the cron's sequence) and library 0.3.2's elbow
> pain map, KB-deadlift ceiling and preacher family — the new §4d.
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
- **Axial stacking avoided, not only detected — a real limit.** ONE spine-loading definition (`live_balance.spine_loading`: a
  squat/hinge compound at moderate+ spinal load) is read by the rule, the acceptance gates and the sample-week generator (third red
  team: the generator counted free-weight compounds, so a dumbbell lunge read "axial" there and "low" here). Past two in one session:
  an unpinned accessory is swapped for a member that is NOT spine-loading (a unilateral slot stays unilateral), else dropped; an
  owner-pinned slot is never swapped — it is the movable one (below) and, if still third, dropped; then a non-heavy anchor, squat
  before hinge — but never the session's ONLY squat or ONLY hinge. Second red team: the old order swapped the lower-volume day's only
  squat; third red team: the pin "kept light" was not a limit (three spine-loading lifts every Friday), and the split-squat ->
  reverse-lunge swap moved a label, not the fatigue (the data now rates the dumbbell-at-the-sides class low as one,
  `EXERCISE_LIBRARY.md` third red team §3 — the swap no longer happens).
- **The kettlebell slot's placement** (`live_balance.kb_placement` / `place_kb`). Its home is `programming_settings.kb_slot_role`
  (default `lower_volume`, the owner's pin). When the home's template already holds two spine-loading lifts (RDL + back squat), the
  slot MOVES (`kb_slot_when_stacked` default `move`) to the first of `kb_slot_move_to` (default shoulders+arms, then upper volume)
  that is drafted this week, has room, and is not the shared cap's conditioning host; `drop` drops it for the week. Either way the
  rationale says so on both sessions. The movement follows `kb_entry` (the KB deadlift until two are logged, then the swing).
- **The kettlebell slot names its implement** (`live_week.kb_slot`, `KB_SLOT`). The KB deadlift logs under Hevy's "Sumo
  Deadlift" (template D20D7BBE, the owner-ruled stand-in — the template stays) unless the owner sets
  `programming_settings.kb_deadlift_template_id` to a custom "Kettlebell Deadlift" template (third red team: the KB pulls land in his
  barbell Sumo Deadlift history and e1RM): then the compiler's resolver writes the slot under that id
  (`live_balance.template_resolver`, approved library only — wired in the nightly cron, the MCP resolver and the sample weeks), the
  bell and the entry count read it first, and the note says "KB deadlift — one kettlebell." No template is created by the engine. Its
  note reads "KB deadlift — logged as Sumo Deadlift.", its effort is capped at RPE 7–8 (an entry drill into the swing), and its rows carry the bell on file — its own
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

## 4b. The third red team's week (`live_balance`, 2026-11-13)

- **Volume by priority** (`allocation_plan`, `allocate`, `ALLOCATION`). The template's delt spread (lateral raise 3+3, rear delt
  2+3, face pull 3) put shoulders at 18 (MAV 16) beside chest at exactly its MEV. Before drafting, the week is allocated: every
  muscle over its MAV gives isolation sets (the largest slot first, never under two sets, never a pinned slot) until it sits at MAV;
  the freed sets go first to the priority muscles (`programming_settings.priority_muscles`, default chest, back, quadriceps,
  hamstrings — retention first) at or under MEV + 1, one per accessory slot; the rest is time back. Sample week (a): shoulders 18 ->
  16, chest 8 -> 9 (the face pull on shoulders+arms and on upper volume 3 -> 2, the cable fly 2 -> 3). `live_week.week_sets` (the
  cardio room and the time trim) reads the allocated week. Whether the delts become a priority muscle is the owner's call (his split).
- **Pain that persists** (`pain_assess`, `programming_settings.pain_assess_line`, default on: "Still hurts 2 sessions? Get it
  assessed."). While a pain flag stands, every session's first joint-flagged lift carries that one neutral line and the rationale says
  how many sessions logged the note. No diagnosis, no number; "" turns it off. The shoulder pain map itself is data (abduction,
  rear-delt and rotation work rated at least moderate for the shoulder), so a sharp shoulder flag now caps lateral raises, face pulls
  and reverse flies at RPE 7, 10 % lighter.
- **The adherence dip** (`adherence_response`, `lighter_week`, `ADHERENCE_DIP`). Five of fourteen sessions done used to mean a full
  five-day week minus two isolation sets. The DEFAULT response (`programming_settings.adherence_response` `short_week`; `trim_sets` =
  the old answer) is now fewer, shorter sessions focused on the anchors: four mornings (shoulders+arms skipped, as in the short
  week), each fitted to ~60 min, every anchor whole, every accessory at two sets, the trunk floor waiting. The dip is judged once a
  week, as of its Monday, so every morning of the week gives the same answer. The stricter keep-the-anchors week (one accessory per
  major muscle, ~45 min) stays behind `behind_schedule_week` (default off).
- **The library fallback** (`library_fallbacks`). An accessory whose slot's ranked fallbacks are all unservable now searches the
  library's same-pattern, same-muscle members (best tier for that muscle, familiar first; equipment, pain, gates and joint limits
  judged as for any swap): the garage week keeps hamstring knee flexion with a banded lying curl instead of dropping it.
- **One effort target per lift** (`one_effort`, `why_effort`, `effort_targets`). Exercise 1's session line said "RPE 8–9 on big
  lifts" above the same lift's "RPE 6–7". When exercise 1's own effort differs, the session line is restated at it (the note
  standard's grammar kept) and the lift's own line printed once. `effort_targets` is the guard the sample weeks and
  `tests/test_programming_fix3_5861.py` run over every generated note.
- **Cardio: the host and the machine** (`conditioning_host`, `cardio_machine`, `machine_label`). Under the shared cap the conditioning
  host is shoulders+arms, or — in a week that skips it (short, dip) — the session after the heavy lower day (the owner's 2026-10-25
  placement), which the cardio room then trims for; the short week used to have no conditioning at all. A menu machine the gym lacks
  is swapped for one it has that runs the kind; a `cycling` note names "Bike", not "Recumbent", where the gym has no recumbent.
- **The cardio room trims harder before the block is cut**: after the over-MAV and over-MEV passes at two sets, a second pass to one
  set, then whole isolation accessories (largest week surplus over MEV first, never under MEV, never pinned) — so the shared-cap
  morning keeps a 20-minute block.

## 4c. The fourth red team's week (`live_safety`, `live_shape`, 2026-11-13)

Every rule is a labelled heuristic table (`live_safety.STOP_LINE`, `live_shape.VOLUME`, `QUAD_SLOT`, `WALK_PROMPT`); every owner
decision is a library setting with today's default.

- **The pain site comes from the note** (`live_safety.note_site`, `flag_joints`). The joint a pain or discomfort flag reaches is
  the one the note NAMES (knee, hip, low back, shoulder, elbow, wrist — the earliest named wins); the flagged movement's worst
  joint is the fallback only when none is named. The joint model gains the knee and the hip (library 0.3.2, a pain-map rating,
  never the rubric's joint cost). A knee flag's pattern group is the knee-dominant group (squat, lunge, split squat, step-up,
  leg extension) whatever lift the note was on. Above the mild line a high-stress movement with no low-stress member takes a
  MODERATE one, reduced (10 % lighter, RPE <= 7); a regression the session fit already chose (a box squat for the squat) is kept,
  reduced. Stress case (g), knee pain 5/10 on the squat in a garage: no high-knee movement served all week, every knee-loading
  lift at RPE <= 7 (it served a Bulgarian split squat at RPE 8–9 and two more lunge patterns before).
- **Mild pain keeps the lift** (`mild`, `mild_pain_tids`): a stated score at or under PAIN_RULE's 3/10, not sharp, keeps the
  movement — in the session fit (`live_session._blocked`) AND the selection (`selection_live.build_policy` `mild_pain`, read by
  `selection_engine._exclusion` under the live policy only) — and the pain rule reduces it. Every lift the pain rule touched
  carries an in-set stop line: "Pain past N/10 or sharp → stop this lift." (N = 3, or the stated score when lower).
- **No load step on a held lift** (`no_step`, `block_rule`). The session block's "Top reps at RPE 7 or less → +10 lb on later
  sets" no longer heads a lift the engine held, cut, stall-reset or flagged: a held exercise 1 turns the rule to "Other lifts: …"
  (or drops it when nothing else may step); any other held lift says "No load step today."; its own "Set 1: … on later sets"
  line goes; a hold day (strain, overreach, a recommended deload) drops the rule and exercise 1 says "Loads stay as written
  today." The rule is fitted on exercise 1's block or on the compiler's WHY line (`live_balance.why_effort` -> `fix_block`).
- **One effort across the session** (`coherent_effort`, `coherent_head`, `big_lift_conflicts`). The session line states the band
  every big lift (anchor) shares, or the day alone when they differ (each big lift then states its own target). The guard reads
  the whole session, and the sample weeks report it (`session_effort_conflicts`).
- **Volume** (`live_shape.reallocate`, `week_ceiling`, `add_slots`; inside `live_balance.allocation_plan`). Muscles AT their MAV give
  isolation sets too (up to two a week, never a slot under two sets), and the priority muscles at or under MEV + 2 take them; the
  quadriceps take a two-set isolation slot on the lower-volume day (leg extension first, else a leg press) when they sit there,
  his history shows the movement (catalog sessions >= 3) and the gym has it; the week's planned working sets (templates +
  allocation + added slots + the trunk floor) are held to the owner's redline (`owner_redlines` total_hard_sets_wk, 75) — one
  isolation set at a time from the largest surplus over MEV, a slot at its floor going whole. A short week counts only the
  roles it drafts. The press option's sets count in the week's allocation (a trade, not extra).
- **Drop, don't shave** (`no_single_sets`, `next_drop`). The time fit and the cardio room never trim an accessory to one set: the
  sets pass stops at two, then whole accessories go — the one whose muscle keeps the most surplus over MEV first (else the last
  listed); a reduce trim never takes isolation under two sets; any one-set accessory left is dropped and its superset unpaired.
  Under the shared cap, as the last resort before the minimum aerobic block is cut, a NON-priority isolation accessory may go
  under its MEV (the shared cap is the owner's choice of conditioning).
- **Order and the heavy pull** (`order_lower_volume`, `deadlift_shape`). On the lower-volume day the squat comes before the RDL. The
  heavy-day squat + deadlift pairing stays (owner ruling #5694); `programming_settings.heavy_day_deadlift_shape` `as_today`
  (default: top set + two back-offs) | `top_plus_backoff` (top set + one back-off — the fourth red team's recommendation).
- **The aerobic gap** (`walk_covers`, `walk_prompt`, `walk_note`). On the conditioning host's morning, when the week's aerobic gap
  (the guideline floor less the walking credit, every block done this week and today's block) is at least 15 minutes, ONE
  optional walk is prescribed on exercise 1's note ("Optional today: brisk walk N min, any time.", N <= 40) — never a silent
  shortfall, never a lifting cut. Under the default cap an easy ride is no longer added when one walk covers what is left
  (<= 40 min). The walking credit itself stays a labelled heuristic (`cardio_model.STEPS_CREDIT_SHARE`, a quarter of the steps
  over 5,000): cadence minutes from the watch would replace it where a source records them.
- **The stop line** (`symptom_text`, `lifting_day_symptom`). `programming_settings.symptom_line` keeps its default wording; the
  preset `extended` reads "Chest, breathing, dizzy, heart racing or irregular? Stop." / "Doesn't settle → get medical help.", and
  `symptom_line_on_lifting_days` (default false) prints it on exercise 1 of every lifting morning. A test reads it on the routine
  as compiled for Hevy (`hevy_compiler.to_create_body`, the nightly and MCP write path's payload builder).
- **The kettlebell slot under strain** (`kb_under_strain`): `programming_settings.kb_slot_under_strain` `as_today` (default: the slot
  follows its placement) | `drop`. **The fourth red team recommends `drop`**: a strained, overreached or deload-recommended week
  drops the kettlebell hinge rather than relocating it.
- **Fidelity.** The sample-week generator compiles with the nightly job's own template lookup (`hevy_template_cache.resolve_movement`
  behind the KB template setting, offline: `scripts/sample_weeks_5861.cron_resolver`) — a title-only catalog entry no longer reaches
  the wire as its catalog key. The no-live-change digests keep the base tree's harness lookup (`RESOLVER` `legacy`), the
  harness their pins were computed with.

## 4d. The fifth red team's week (`live_rules`, `live_sequence`, 2026-11-13)

Every rule is a labelled heuristic table (`live_rules.SET_CAP`, `FULL_BODY`, `JOINT_ISOLATION`, `KB_FILLER`, `SELF_REPORT`,
`live_sequence.SHORT_WEEK_PLANS`); every owner decision keeps today's default.

- **The session set cap** (`fit_set_cap`). A 3-day week crashed the draft (`total_sets 23 > cap 20`): the short week's host took the
  carry, the trunk floor and the kettlebell slot with no guard. Every live session is held to the week grid's
  `session_set_ceiling`: live additions go first, then accessory sets to two, then whole accessories, then an anchor's back-offs —
  never an anchor's top set. Fuzzed 1–5 mornings x both cap settings x every stress profile (`tests/test_programming_fix5_5861.py`).
- **Short weeks are planned, not truncated** (`live_sequence.SHORT_WEEK_PLANS`). 4 mornings: shoulders+arms skipped. 3 mornings:
  upper heavy, lower heavy, and a FULL-BODY lower volume (+ the upper-volume anchors at two sets) — legs and upper body each twice.
  2 mornings: two full-body days (upper heavy + the lower-volume anchors; lower heavy + the upper-volume anchors), never an upper
  half and a lower half. 1 morning: one full-body session. The line no longer claims "legs keep 2x" where it is false.
- **The week rule is the cron's** (`live_sequence.week_plan`, `sequence_skip`, `serve`). The short-week and adherence-dip role
  choices lived only in the sample generator. Now `routine_generator._schedule_entry_for_date` passes the live plan's skipped roles
  to `session_sequence.next_session(skip=...)` (`ledger` / `classify_sessions` step over them, so the credit check reads the role
  the plan served), and the entry carries `live_week` (host, full-body partner) into the draft. The generator reads the same plan.
  Live only: with the library `proposed` the sequence is today's (`tests/test_no_live_change_5861_l6.py`). The dip is judged on
  the record BEFORE the week's Monday. The short week's production input is the charter's dated travel windows
  (`days_available`); `sequence_rule_from` (default: from the block start) is the first Monday the rule judges.
- **Above the mild line the pattern is off** (`live_program.apply_joint_rule`). A stated score over 3/10, "sharp" or no number:
  every member of the flag's pattern group that loads the joint at moderate or more is dropped for the session, and so is the
  session fit's pain swap for the flagged movement — no moderate-stress substitute (FIX4 served a decline machine press at sharp
  6/10 and 7/10 shoulder pain). **Same-joint isolation** (`isolation_joint_cap`, `JOINT_ISOLATION`): under any flag, every isolation
  lift working the joint is capped at RPE 7 with the stop line, whatever the joint data says.
- **The elbow pain map** (library, `exercise_library_input_review.ELBOW_PROVOKING`): every loaded triceps extension and curl reads
  the elbow at least moderate (50 rows; wrist / forearm / bridge rows excluded) — a pain-map floor the rubric's joint cost does not
  read (`provocation_floor`), so no tier moved. **New movements at RPE <= 7, isolation too** (`live_program._novel_cap`,
  `live_week.novel_start`): a lift with no load on file ("find the load") starts at the novel-again cap.
- **Nothing added on a bad day** (`no_added_work`, `bad_day`). On a strained, overreached or deload-recommended day the quadriceps
  slot, the trunk floor and a RELOCATED kettlebell slot wait. `kb_slot_under_strain` (default `as_today`) still governs the slot in
  its home session; today's templates never keep it there (lower volume already holds two spine-loading lifts), so the default week
  serves no KB hinge on a bad day either way. **The fourth and fifth red teams both recommend `drop`.**
- **The KB deadlift as filler** (`kb_choice`, `kb_filler`, `KB_FILLER`). For a lifter whose record holds a loaded barbell or
  trap-bar deadlift, the KB deadlift (one bell) is filler: the swing serves when servable (equipment, pain, its gates), else the
  slot is dropped. The swing's own chain gate (`chain_kb_swing`, the owner's #5774 entry: two KB deadlifts first) stays the
  owner's: while it is locked, a deadlifter's slot is dropped. The library rates the KB deadlift's glute hypertrophy B (load
  ceiling low: one bell — the rubric's cap), not A.
- **"Sore" is discomfort** (`note_class`, `LIGHT`). A joint-located sore / achy / tight / cranky note at or under the mild line,
  which the note layer leaves as nothing (#5800, unchanged), is light discomfort for the engine: two in a fortnight reach the joint
  rule's reduce tier (10 % lighter, RPE <= 7, the stop line) — the lift is kept, never swapped.
- **Thresholds that read** (`fatigue_model`): `readiness_strain` is the table's tier; the axial and hinge windows are the table's
  hours; `axial_stacking` reads the ONE spine-loading definition (`live_balance.spine_loading`).
- **The self-reported stop lines** (`self_report`, `SELF_REPORT`). The symptom line says "Stop, log it." A Hevy note in the last
  fortnight naming a racing or irregular heartbeat, or fainting / near-fainting / dizziness, trips the draft's symptom gate (no hard
  cardio, a review line). The platform tripwire's own palpitations and syncope arms (`health.tripwire_readers`) still read
  `unknown`: their canonical input is the check-in lane's (#5819).

## 4e. The owner's rulings of 2026-11-13 (`live_rulings`, FIX6)

Configuration, not activation: the library stays `proposed`. Each ruling is a library-carried setting
(`deploy/build_exercise_library.py` `OWNER_RULED_SETTINGS`, written over any earlier on-disk default by every rebuild) with the
same code default, read only under `mode() == "live"`. `tests/test_owner_rulings_5861.py` holds one outcome + one control per
ruling.

- **Shared 75-minute cap ON** (ruling 1, `session_cap_includes_cardio: true`). The host's cardio room comes from the charter's
  supersets and from sets OVER a muscle's MAV only (`cardio_room_takes: over_mav_only`): no strength work a muscle needs is cut
  for a cardio block. Consequence: on the synthetic normal week the conditioning block is ~18 min; on the 4-day week the host has
  no room and the week's aerobic answer is the walk on the host's note (a tradeoff, stated, not hidden).
- **The 4-session week after missed sessions** (ruling 2, `adherence_response: short_week`) and **the 4-day week drops
  shoulders+arms** (ruling 3) with a COUNTED floor: shoulders, biceps and triceps (direct 1.0 + indirect 0.5) are held at MEV over
  the sessions left (`short_week_floor`, `ARMS_FLOOR`); a time trim never reads a skipped day's sets as surplus
  (`live_week.week_sets(rx=...)`).
- **Purposeful cardio only** (ruling 4, `cardio_purpose_only: true`). A gym block exists only for the week's conditioning dose on
  the conditioning host; no easy block fills a slot or a gap. Easy aerobic is the walking outside the gym, tracked apart.
- **Top set + one back-off, one lead lift** (ruling 5, `heavy_day_deadlift_shape: top_plus_backoff`, `lead_lift_rule:
  alternate_weekly`). The squat and the deadlift keep their pairing (#5694) but are never both maximal: one leads at the
  session's RPE 8-9 and the other is capped at RPE 7-8 (`LEAD_LIFT`); the lead alternates by ISO week (even: squat, odd:
  deadlift), so each lift gets a top-effort exposure every other week — its strength trend stays readable — and the second lift's
  fatigue falls on the week it does not lead. A deadlift swapped out (a hip thrust under discomfort) is not a second maximal lift.
- **Overhead press 3 sets** (ruling 6, `press_sets: 3`). The extra sets come off the LATERAL raises first (`press_trade`, never
  under two sets), not the rear delts; the press progresses by double progression in 6-10 with the session's one-load-change rule,
  and a strained / deload week takes a set off like any other lift.
- **No KB hinge under strain** (ruling 7, `kb_slot_under_strain: drop`): the slot's sets leave the week, nothing makes them up.
- **Priority by stimulus and performance** (ruling 9, `priority_muscles: [chest, quadriceps]`, `priority_add_rule:
  stimulus_and_performance`). A priority muscle the week already holds at or over MEV whose anchor is PROGRESSING takes no extra
  sets and no added slot (`stimulus_gate`, `PRIORITY_ADD`); under MEV, or with a stalled / regressing / unread anchor, the
  allocation stands and the quadriceps take the low-fatigue isolation slot first. A week whose squat is the SECOND lift (RPE
  7-8 under the lead-lift rule) never holds the quadriceps: less stimulus from the squat, so their added work stands.
- **No symptom warning line** (ruling 10): `symptom_line` defaults to "" and `symptom_line_on_lifting_days` to false; the
  `extended` preset stays available. The self-report gate (FIX5) still turns hard cardio easy, with one neutral reason line.
- **The advisory loss-rate ceiling** (ruling 11, `rate_ceiling_pct_bw: 1.0`): `health.rate_policy.advisory_ceiling` — ~1 % of
  the CURRENT 7-day mean weight a week (the absolute ceiling tapers as weight falls), a quarter-point lower per slow signal
  (strength, fatigue, recovery, adherence; floor 0.5 %), past weeks judged against the base reference, and the single-fast-week
  guard: muscle-loss risk only when the rate sat over the reference for 3 of the last 4 weeks AND strength is sliding. One line a
  week on the upper-heavy draft; never applied (`calorie_target` is untouched).
- **Aerobic credit from recorded sessions** (ruling 12). The 25 %-of-steps-over-5k credit is GONE. `cardio_model.recorded_aerobic`
  resolves Apple workouts, Strava and the Hevy record into ONE workout identity each (`training.workout_identity`); an identity
  holding a Hevy member is the gym's and is never credited again; an Apple member's METs (>= 3) or mean cadence (>= ~100 spm, a
  population heuristic) classifies it, else a recorded walk's moving speed through the walking metabolic equation on the flat
  (valid 0.83-1.67 m/s; terrain ignored, so a floor). Heart rate is never effort evidence; anything else is reported as
  "intensity unknown", not credited. Steps are reported as their own activity metric, never credited.
- **Unconfirmed equipment is never served** (ruling 13): `selection_engine.availability` reads an `unknown` movement or item as
  unavailable on every live path (anchors, selection, slots, cardio machines) — tested over every drafted week.
- **Evidence and completeness visible** (ruling 16): one `evidence (live)` line per session — each served movement's tier on its
  slot's objective, evidence confidence and data completeness (`quality_rubric.completeness`); a provisional rating never reaches
  S on any objective and ranks outside the S/A pool.
- **The glute S standard** (ruling 17, rubric 3.4.0): see docs/coaching/EXERCISE_LIBRARY.md "Owner rulings 2026-11-13".

## Block-retro hooks (ruling 18)

Every heuristic the live engine reads is labelled `heuristic` in its table and is re-tuned at a block retro (the
`training-review` skill) on the metric below — never by a session's feel. `live_rulings.HEURISTIC_HOOKS` is the registry; a test
holds each key to a labelled table and to this list.

| Heuristic | Re-tune on |
|---|---|
| `live_rulings.LEAD_LIFT.second_band` | the non-lead lift's e1RM trend over the block (held = right; sliding = raise the cap a half band) |
| `live_rulings.ARMS_FLOOR.add_per_slot` | short-week arm/shoulder e1RM and the next normal week's first-set reps |
| `live_rulings.PRIORITY_ADD.progressing` | quadriceps anchor e1RM slope in weeks with vs without the added slot |
| `cardio_model.MODERATE_METS` | Apple workout intensity vs the session RPE he logged, per modality |
| `cardio_model.CADENCE_MODERATE_SPM` | his own walking cadence at a logged talk-test / RPE (the ~100 spm figure is a population heuristic) |
| `cardio_model.RPE_MODERATE` | logged cardio RPE vs the talk test he notes |
| `rate_policy.CEILING_TAPER` | 4-week loss rate vs anchor e1RM and lean-mass (DEXA) change at each block retro |
| `rate_policy.SUSTAINED_WEEKS` | weeks above the ceiling that preceded an anchor decline, across blocks |
| `rate_policy.SIGNAL_STEP_PCT` | loss rate in weeks with 1, 2, 3 slow signals vs strength the following week |
| `live_program.LOAD_POLICY` | e1RM trend after a hold / step down vs after a step up |
| `live_program.STALL_RULE` | e1RM over the 3 exposures after a stall reset |
| `live_program.PAIN_RULE` | pain-note recurrence within 2 sessions of a reduce / avoid |
| `live_program.DELOAD_SHAPE` | readiness and first-set reps the week after a deload |
| `live_program.TRUNK_FLOOR` | trunk-drill progression and back-discomfort notes |
| `live_balance.ALLOCATION` | weekly sets per muscle vs that muscle's e1RM / rep PRs |
| `live_balance.ADHERENCE_DIP` | sessions completed in the 2 weeks after a short-week response |
| `live_shape.VOLUME` | priority-muscle sets vs their anchor trend |
| `live_shape.QUAD_SLOT` | quadriceps anchor trend with the slot served |
| `live_shape.WALK_PROMPT` | walks logged after a prompt |
| `live_week.CARDIO_ROOM` | conditioning-block minutes delivered vs lifting minutes lost |
| `live_week.NOVEL_START` | RPE logged on a new movement's first 3 exposures |
| `fatigue_model.THRESHOLDS` | strain calls vs the next session's first-set reps / RPE |
| `quality_rubric.NEUTRAL` | how often a reviewed input moved a provisional row's tier |
| `fatigue_model.THRESHOLDS.deficit_hold_pct` | anchor e1RM 3 and 6 weeks after a 'holding' read in a deficit vs after a reset (held = right; sliding = tighten the band) |
| `fatigue_model.THRESHOLDS.post_reset_min_exposures` | e1RM over the exposures after each reset; resets per lift per block |
| `fatigue_model.THRESHOLDS.reset_detect_pct` | resets the record shows vs the resets the engine prescribed (false reads = a volume day called a reset) |
| `live_pain.PAIN_SCOPE` | pain-note recurrence within 2 sessions of a lift-only / pattern / pain-free-route answer, and the flagged muscle's hard sets |
| `live_stimulus.FAST_CUT` | anchor e1RM in the 2 weeks after a fast-cut volume answer vs after a load cut |
| `live_stimulus.WEEK_FLOOR` | weekly HARD sets per muscle vs MEV, and the floor muscles' e1RM / rep PRs |
| `live_stimulus.DELOAD_TOP_SET` | readiness and first-set reps the week after an unconfirmed-deload week |
| `live_stimulus.PARITY` | priority-muscle sets vs the donors' and both muscles' rep PRs |
| `live_week.FAMILIAR_SWAP` | RPE logged on a familiar swap's first 2 exposures (over target = restore the novelty cap) |

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
- **recorded activity first** (`cardio_model.aerobic_plan`): #5861 FIX6 (owner ruling 12) REMOVED the steps credit (a quarter of
  the steps over 5,000). The credit is recorded outside-the-gym minutes with intensity evidence (`cardio_model.recorded_aerobic`,
  read by the cron as `aerobic_record`), then cadence-qualified minutes where a source records them; steps are reported, never
  credited, and a day with only steps reads "intensity unknown". Under `cardio_purpose_only` (ruling 4) no easy block is served;
- **`programming_settings.session_cap_includes_cardio`** (library setting, default `false` = today's 75-minute LIFTING cap
  with the cardio block apart): `true` makes the 75 minutes cover lifting + cardio — a block shrinks to what lifting leaves,
  under 10 minutes it is dropped — and hard conditioning lands on shoulders+arms;
- a conditioning note MAY end with a symptom line, `programming_settings.symptom_line` — #5861 FIX6 (owner ruling 10): the
  default is "" (no warning line on any session); the `extended` preset and the owner's own wording print when set;
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
- **cardio room under the shared cap** (`live_week.make_cardio_room`, `CARDIO_ROOM`): on the conditioning host only (third red
  team: with the conservative steps credit an uncovered week is common, and trimming every morning for an easy block gutted the
  lifting — an easy block now takes only the room left, and only while the week's aerobic gap needs it, `live_balance.easy_gap`)
  the charter's antagonist supersets pair first, then sets come off the muscles
  over MAV (they buy the whole block), then the largest surplus over MEV (it buys the 20-minute minimum) — the red team's
  shared-cap week served a 13-minute stub while the delts sat at 18 sets (MAV 16);
- the loss-rate band (`health.rate_policy.propose_band`) appears in the rationale as ADVISORY text only — nothing reads it back,
  no kcal or titration changes.

## 8. Heuristic vs evidence-backed

| Evidence-backed (verified citation, ±1 band) | Practitioner consensus (labelled) | Platform heuristic (labelled, owner-adjustable) |
|---|---|---|
| lengthened-position loading for some muscles; the glute stretch cap (Plotkin 2023); 14 direct-trial and 7 characteristic-trial hypertrophy rows | the functional, conditioning and mobility rubrics; joint-stress ratings; cue sheets; pain monitoring by a stated score | every fatigue threshold; the 14-day trend window; #5861 FIX4: `live_safety` SITE_WORDS, STOP_LINE, the moderate-member fallback; `live_shape` VOLUME (priority_margin 2, at_mav_give 2), QUAD_SLOT, WALK_PROMPT (15–40 min), the knee/hip pain map (library); MAX_WEEKLY_EXPOSURES 2; MAX_HOLD_WEEKS 12; MAX_NEW_PER_WEEK 2 (new = not performed in RECENT_DAYS 28); upgrades at block start; the systemic-slump rule (4 lifts, half); fatigue cost; surplus-first trimming; the adherence step; `live_program` LOAD_POLICY (−10 % / −5 % / RPE 9.5 / RPE 9, evidence RPE 9, one retreat per 6 days), DELOAD_SHAPE, PAIN_RULE (3/10), STACK_RULE (2 per session, pinned light at RPE 7), STALL_RULE (+2 reps, −10 %), TRUNK_FLOOR, TRUNK_FALLBACK_ORDER, MIN_CARDIO_MINUTES 10; `live_week` KB_SLOT (RPE 7–8), CARDIO_ROOM (20-min block, 2-set floor), BEHIND_SCHEDULE (5 of 10 missed, ~45 min, 2 sets), NOVEL_START (6–8, RPE 7), VERTICAL_PULL_FALLBACK |

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
- [ ] the symptom-line wording — whether to add "heart racing or irregular" (the default is unchanged; the longer wording is
      exercised and prints on every conditioning note);
- [ ] third red team settings, each at today's default and each alternative exercised in `tests/test_programming_fix3_5861.py`:
      `kb_slot_role` (lower_volume) / `kb_slot_when_stacked` (move | drop) / `kb_slot_move_to`; `kb_deadlift_template_id` (none: the
      Sumo Deadlift stand-in — set it once a custom "Kettlebell Deadlift" template exists); `pain_assess_line` (on); `priority_muscles`
      (chest, back, quadriceps, hamstrings — add the delts if they stay a priority); `adherence_response` (short_week | trim_sets);
      `body_fat_tier` (unknown) and `rate_band_mode` (advisory | structured — structured records the band on the draft; nothing
      reads it back: wiring it into nutrition is a separate, owner-approved change);
- [ ] the S quota and the shoulder pain-map floor (library rubric 3.3.0) and the conservative steps credit (a quarter of the steps
      over 5,000) — accept or adjust;
- [ ] the novelty budget's reach: on the flip, the current phase's ledger (written in shadow by the #5075 calendar) is served
      only within the budget — the rest of the shadow rotation waits;
- [ ] showing the loss-rate band as advisory text in the rationale (no nutrition change either way).
- [ ] fourth red team settings, each at today's default and each alternative exercised in `tests/test_programming_fix4_5861.py`:
      `heavy_day_deadlift_shape` (as_today | top_plus_backoff — recommended), `kb_slot_under_strain` (as_today | drop —
      recommended), `symptom_line` (today's wording | `extended`, with racing/irregular heartbeat and a seek-care step),
      `symptom_line_on_lifting_days` (false | true);
- [ ] fifth red team (each exercised in `tests/test_programming_fix5_5861.py`): `sequence_rule_from` — set it to the approval's
      Monday so weeks served before the flip keep their credited positions (unset = the week rule judges every week since the block
      start); the short week's input (today: the charter's travel windows — a per-week declared count would be better); the
      `SHORT_WEEK_PLANS`; the pattern-off rule above 3/10; `kb_slot_under_strain` (both red teams: `drop`); the KB swing's chain gate
      for a lifter who deadlifts (locked = no kettlebell slot); readers that still show the positional sequence (the site, the coach
      packet, fitness tests) — the cron and the MCP draft serve the live one;
- [ ] the knee/hip pain map (library 0.3.2, a class rule, not in the rubric's joint cost) and the fourth red team's heuristics:
      the note-site words, the moderate-member fallback above the mild line, the stop line at 3/10, at-MAV donors (2 sets) and
      the MEV + 2 priority margin, the quadriceps slot (history >= 3 sessions), the weekly redline from `owner_redlines`, the walk
      prompt (15–40 min, on the conditioning host), drop-don't-shave.

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
- The third red team's gates (2026-11-13) test OUTCOMES, not the engine's own words: d1 fails any muscle over MAV while a
  priority muscle sits at or under MEV + 1 with sets that could move (the 18/8 week fails; its control replays it); d2b counts
  spine-loading lifts by the one definition with no "kept light" exemption, holds the dumbbell-at-the-sides class to one rating, and
  proves the rule, the gate and the generator share the definition; d3 checks lifting minutes under the default cap and the whole
  morning under the shared cap, and the morning is always reported; b2's aerobic check is a 20-minute block or the steps dose
  COMPUTED by the cardio model (the engine's sentence no longer passes — a control proves it); b3 checks the cardio block's machine
  and its note's machine name; c2c names abduction / rear-delt / rotation work by pattern, independent of the joint data (its
  control puts the old data back and the lateral raise goes uncapped); d5 fails a muscle over MAV however the sets got there.
  `tests/test_programming_fix3_5861.py` holds the rest, each with a control: the shoulder class rule, the persistence line, the
  allocation, the KB placement and template settings, the S quota, one effort target on every generated note, the adherence dip on a
  realistic irregular history, the steps credit, the garage leg curl, the short week's conditioning host, the machine and its name,
  and the owner settings.
- The fourth red team's gates (2026-11-13), `tests/test_programming_fix4_5861.py`, over the six profiles AND three stress profiles
  (`tests/fixtures/sample_week_stress_profiles_5861.json`: knee pain in a garage, a heavy walker, mild low-back pain) under both
  cap settings, each with a control: no high-knee movement and no knee-loading lift above RPE 7 under a knee flag (control: the
  note's site ignored); mild pain keeps the deadlift lighter with a stop line (control: the old exclusion); every pain-touched lift
  carries a stop line; no "+N on later sets" reaches a held lift or a hold day (control: the rule fitted to nothing); no session
  line contradicts a big lift (control: the per-lift guard only); the week never passes the 75-set redline (control: 76 fails, and
  the ceiling off); no one-set accessory; squat before the hinge; the deadlift shape and the KB-under-strain settings both ways;
  one optional walk under the shared cap (control: a silent shortfall); fewer bolt-on rides under the default cap; the stop line on
  the Hevy payload, the extended wording and the lifting-day switch; the band pull-up; the corrected tiers; the deload's compound
  RPE cap (the third red team's surviving M3 mutation, now red); the cron's template lookup on the sample wire. Acceptance c4 reads
  the note text too ("loads never rise" includes the in-session step).
- The second red team's gates (2026-11-13): d1 now checks the DISTRIBUTION (no major muscle over MAV while another is under
  MEV); b2 needs a 20-minute aerobic block or the steps-dose rationale, not any block; d2b keeps a squat and a hinge in every
  lower session (its control replays the old precedence that swapped the squat out); d3b keeps a 20-minute block under the
  shared cap. `tests/test_programming_fix2_5861.py` reproduces each real-data failure of the owner run with a synthetic
  fixture SHAPED like it — a noisy isolation history (a dumbbell jump; the trend reads "regressing", the effort does not), a
  row cut on Monday and stall-reset on Thursday, a shadow-era ledger rotation carried into the phase — plus the KB slot,
  the stop line (and the cron's read), the cardio progression, the garage vertical pull, the new-movement rep range, the
  press option and the behind-schedule option, each with its control.
