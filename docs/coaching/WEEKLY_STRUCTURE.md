# Weekly structure: is the five-day split the right default? (#5861 L5)

> **Status:** analysis and proposal. **Nothing here changes the live program.** `program_structure.SESSION_TEMPLATES`, the
> charter's `split` and the session sequence are untouched; every refinement below is an owner decision.
> **Written:** 2026-11-12, against charter 1.49.0 and the session-time model of #5799 (99 s per set, measured).
> **Part of:** epic #5861 (lane L5). Companion module: `lambdas/health/rate_policy.py` (the loss-rate interface, last section).

## The question

The owner's program runs five lifting mornings a week, served **in order** (the sequence advances on a logged session, not on
the calendar): upper heavy, lower heavy, shoulders and arms, upper volume, lower volume. The brief asks whether that should stay
the default, or give way to four main days and an optional fifth accessory or conditioning day, or something else. The aim is to
keep as much muscle and strength as possible during a long fat-loss phase, then improve aerobic fitness, with low unnecessary
fatigue and a routine that lasts. The 75-minute lifting ceiling stays.

## What the current week actually delivers

Every number in this section is computed from the live templates through `program_structure.session_prescription_for_role`
and the movement catalog. "Sets" are hard working sets counted to the movement's primary muscle, which is how the program's
own weekly view (`weekly_sets_by_muscle`) counts them. Indirect work from pressing and pulling comes on top.

| Session | Working sets | Lifting minutes (estimate, warm-ups included) |
|---|---|---|
| upper heavy | 17 | 74.7 |
| lower heavy | 14 | 71.7 |
| shoulders + arms | 13 | 52.4 |
| upper volume | 17 | 72.2 |
| lower volume | 14 | 61.7 |
| **week** | **75** | — |

| Muscle group | Sets per week | Sessions per week | Volume landmarks (MV / MEV, `config/training_landmarks.json`) |
|---|---|---|---|
| quads | 8 | 2 | 6 / 8 |
| hamstrings + glutes | 8 (5 + 3) | 2 | 4 / 6 each |
| chest | 8 | 2 | 6 / 8 |
| back | 10 | 2 | 8 / 10 |
| delts | 15 | 3 | 6 / 8 |
| biceps | 6 | 3 | 5 / 8 |
| triceps | 6 | 3 | 5 / 8 |
| calves | 8 | 2 | 4 / 8 |
| abs (direct) | 2 (+ carry and swing trunk work) | 1 | 0 / 4 |

**The finding that settles most of the question:** the current split is already four main days plus one accessory day in
everything but name. All of chest, back, quads, hamstrings and glutes are trained on the four upper/lower sessions. The
shoulders-and-arms session adds no major-muscle sets. It contributes 7 of the 15 delt sets, 2 of the 6 biceps and triceps sets,
and the carry. So "4 + 1" is not a new structure for this program. The real questions are what happens when a morning is missed,
where the hard conditioning goes, and whether the heavy lower day stacks too much fatigue.

## The alternatives, scored on the same model

| Option | Major muscles: sets and frequency | Session time | Fatigue placement | Aerobic compatibility | Missed-morning consequence |
|---|---|---|---|---|---|
| **A. Current five roles** | Every major muscle at its floor band, 2x/wk; delts 15 sets at 3x/wk | All five within 75 min; shoulders + arms is 52 min | Heavy squat and heavy conventional deadlift share lower heavy, the week's costliest session. The two lower sessions are at least two sessions apart in the sequence | Conditioning is appended to lifting days; the shortest day has room | The sequence slides. If the slide pushes lower volume into next week, quads and hamstrings drop to 5 sets at 1x that week (computed) |
| **B. Four main days + optional fifth (accessory/conditioning)** | Same as A on the four main days (the main days ARE A's four upper/lower sessions) | Same | Same | The optional day is the natural home for a full conditioning block | Skip the optional day: every major muscle keeps 2x/wk and its sets. Delts fall to 8 (at MEV), biceps and triceps to 4 direct (computed) |
| **C. Upper/lower x2 + an optional full-body fifth day** | Adds a third squat or hinge exposure | Fits | Three axial-loading days a week during a deficit | Less room for conditioning on the lower-fatigue day | As B, but the fifth day costs more recovery than it returns while every major muscle already sits at its floor |
| **D. Full body x3 + two optional days** | With the 99 s per set model and warm-ups for three compound anchors, a heavy full-body session estimates 90.5 min. Trimming it to 75 cuts every accessory. A synthetic three-day version holds 39 sets a week, with chest 6 and delts 9 (computed) | Over the ceiling before trimming | Squat or hinge on every lifting day | Two optional days for conditioning | Missing one of three days removes a third of every major muscle's work |
| **E. Four days only (no fifth)** | As B on a short week, every week | Fits | Lowest | Most room | Drops the delt and arm emphasis the owner ruled in, and the fifth morning of the habit |

A push/pull/legs rotation over five mornings trains each muscle less than twice a week, so it was not modelled further.

### What the evidence can and cannot say here

The citations below are **named from memory. They have not been checked through the repo's DOI/PMID verification** (the
library's evidence script). They are context for the reasoning, not evidence ratings.

- **Frequency.** Once weekly volume is equal, meta-analyses find little or no hypertrophy difference between training a muscle
  2x and 3x or more a week (Schoenfeld, Grgic and Krieger 2019, J Sports Sci). An earlier analysis favoured at least 2x over 1x
  (Schoenfeld, Ogborn and Krieger 2016, Sports Med). Strength results are similar once volume is accounted for (Grgic and
  colleagues 2018, Sports Med). Practical reading: 2x a week for each major muscle is enough, and a split earns nothing by
  raising frequency without raising volume.
- **Maintenance needs less than building.** In a detraining-and-maintenance study (Bickel, Cross and Bamman 2011, Med Sci Sports
  Exerc), a fraction of the building dose kept the gains in younger adults, while older adults needed more. Muscle in a deficit
  is not the same condition, so treat this as direction, not a dose. The point is that holding intensity (the heavy top sets)
  probably matters more than adding sets.
- **Deficit.** A meta-regression (Murphy and Koehler 2022, Scand J Med Sci Sports) found an energy deficit blunts lean-mass gain
  more than strength gain. That supports keeping heavy exposures for retention and not expecting growth from extra volume while
  losing.
- **Interference.** A concurrent-training meta-analysis (Wilson and colleagues 2012, J Strength Cond Res) linked the interference
  effect to running more than cycling, and to the frequency and duration of the endurance work. Spacing and modality are the
  levers. Practitioner consensus is to keep hard leg-dominant conditioning away from the session before a heavy lower day.

**Uncertain:** no study tests this exact person, deficit or split. Every "enough" above means "consistent with group averages".
Individual response is read from the owner's own anchor trend, which is what the strength tripwire and the rate policy watch.

## Recommendation: keep the current split as the default, read as four main days plus one flex day

**The current five-role split should stay.** It already puts every major muscle on four upper/lower sessions at 2x a week, inside
the 75-minute ceiling. The fifth session is the accessory day the brief describes. No alternative improves muscle or strength
retention on the program's own numbers. Full body x3 fails the time model, and adding a third axial day costs recovery for no
frequency the evidence says is needed. Five mornings is the owner's habit, and the fifth session is the cheapest one to keep or to
drop.

Three refinements are worth an owner decision. **None is built here.** Each would touch a live module owned elsewhere.

1. **A short-week rule (session sequence).** When a week can hold only four lifting mornings, skip shoulders + arms rather than
   letting the sequence slide. Computed consequence: every major muscle keeps 2x a week and its sets. Delts and arms fall to their
   MEV for that week. Today's slide can instead leave legs at 1x for a week. This is the single change that most protects
   priority 1 when life intervenes.
2. **Conditioning placement (cardio menu, lane L4).** Put the two weekly conditioning blocks on shoulders + arms (52 minutes
   of lifting, so its morning has the most room) and upper volume. Never put one on the session before lower heavy. Prefer a
   non-impact modality for the block the morning after lower heavy. Spacing is a practitioner heuristic consistent with the
   interference literature. No heart-rate gating is implied.
3. **Watch the heavy lower day (no change now).** Lower heavy stacks a heavy squat and a heavy conventional deadlift (owner ruling,
   #5694). Keep it. If the anchor strength tripwire trips on the squat or the hinge, the first lever (heuristic) is to cut that
   day's deadlift to a top set plus one back-off before trimming volume anywhere else. Weekly hinge work is still the deadlift,
   the Romanian deadlift and the kettlebell swing.

**Built since (#5861 fix round 9, live only).** Refinement 1 is the live week rule (`live_sequence`, `live_volume.SHORT_WEEKS`: four
mornings skip shoulders + arms with the delts and arms held at MEV; one to three are full-body mornings); refinement 2 is the
shared-cap conditioning host (`hard_conditioning_doses`); refinement 3 is the heavy day's top set + one back-off with one lift
leading (owner ruling 5). The defaults the live engine reads are generated from the code below — this document states none of its
own (`rate_policy`'s `body_fat_tier` is a function input, not a library setting).

<!-- GENERATED:live_settings BEGIN -->
| Setting | Default | Provenance | What it does |
|---|---|---|---|
| `session_cap_includes_cardio` | `True` | owner ruling 1 (2026-11-13) | lifting and gym cardio share the 75-minute cap; the conditioning dose takes only the minutes lifting leaves (no strength work is cut for cardio). False: the cap is lifting only and the cardio block sits apart |
| `press_sets` | `3` | owner ruling 6 (2026-11-13) | overhead-press working sets a week (2 or 3), taken from the side-delt (lateral raise) sets |
| `priority_muscles` | `['chest', 'quadriceps']` | owner ruling 9 (2026-11-13) | muscles planned at MEV at least and never under the non-priority arm and calf muscles' weekly hard sets (the plan pays them from those isolation slots); trimmed last for time and by a slump |
| `abs_direct_sets_per_week` | `4` | owner ruling #8 (fix round 8) | challenging DIRECT ab sets a week, spread over the mornings; indirect trunk loading never counts; halved on a short or high-fatigue week |
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
| `decline_pct` | `0.02` | progression | an anchor is DECLINING when its same-role e1RM fell 2%+ across its latest same-role exposures (newest vs two back) with no recovery between (a level under an old best is not a decline: the one-rep-short lifter holds steady) | block retro: slump calls vs the next block's anchor e1RM |
| `slump_accessory_cut` | `0.34` | progression | the slump's volume answer: about a third of each accessory's working sets (never under 2); anchors keep theirs | block retro: recovery markers in the weeks after a slump hold |
| `second_lift_band` | `[7, 8]` | progression | owner ruling 5: squat and deadlift never both maximal in one session; the lift that does not lead runs one band lower, loaded from its own same-role e1RM at that band | block retro: both lifts' e1RM trend under alternation |
| `familiar_days` | `56` | novelty | a movement pattern logged in the last ~8 weeks is familiar (a biomechanically similar swap included): normal effort, no re-entry cap | block retro: first-exposure RPE vs the cap |
| `new_pattern_rpe` | `7` | novelty | a NEW pattern runs one exposure at RPE <= 7 (technique, soreness); then normal effort | block retro: soreness / discomfort notes after a new pattern |
| `layoff_days` | `10` | novelty | owner ruling #10 (fix round 8): after 10+ days with no session, each lift's FIRST session back runs at RPE 8 at its last same-role load, no step; normal progression from the next exposure | block retro: second-session performance after a layoff |
| `first_back_rpe` | `8` | novelty | see layoff_days | see layoff_days |
| `hard_rpe` | `8` | volume | a working set prescribed at RPE >= 8 (the top of its effort line) is a hard set; the ONE counter | block retro: logged RPE of prescribed hard sets |
| `set_credit` | `{'secondary': 0.5, 'delt': {'horizontal_press': {'front_delts': 0.5}, 'vertical_press': {'front_delts': 1.0, 'side_delts': 0.5}, 'horizontal_pull': {'rear_delts': 0.5}}, 'never': {'*': ['abs'], 'hip_extension': ['quadriceps'], 'leg_curl': ['calves']}}` | volume | THE one set-credit table (fix round 10): a working set credits its target's landmark muscle 1.0 and each secondary — the library's secondaries and every other muscle it is RATED for — `secondary` (half a set, the fatigue model's convention); each delt head direct 1.0, or by `delt` from the lift's pattern (pressing -> front and, overhead, half a side; rowing -> rear — practitioner consensus, explicit so it can be argued with); `never` drops a credit the anatomy does not support (indirect trunk loading is never an ab set, owner ruling #8; a hip thrust trains no quadriceps; a leg curl no calves) | none (convention) |
| `slot_max_sets` | `3` | volume | an accessory slot takes at most 3 working sets — a template slot written at 4 is served at 3 (fix round 10: the calf slots); 4+ in one slot is junk volume | none |
| `slot_min_sets` | `2` | volume | an accessory or anchor never runs one working set: drop, don't shave | none |
| `delt_heads` | `{'side_delts': 6, 'rear_delts': 4}` | volume | owner ruling #9: each delt head assessed apart, direct + indirect; the side delt (no compound trains it much) aims at 6 hard sets, the rear at 4 | block retro: lateral-raise and rear-delt progression |
| `short_week_floor` | `3` | volume | a 1-3 morning week holds each priority muscle and each major pattern at maintenance: MV x mornings / 3 hard sets (at least 2-3), full-body mornings of 4-6 movements at 2-3 sets — never a 1-set anchor | block retro: anchor e1RM after a short week |
| `time_cap_minutes` | `75` | time | the owner's 75-minute morning, warm-ups included (#5799 time model, 99 s a set measured) | the #5799 measured set time |

Time-fit order: accessory_backoff -> anchor_backoff -> spare_accessory -> priority_last_set.
<!-- GENERATED:live_settings END -->

A data-only alternative template set was **not** added. The recommended default is the existing templates, so no option needs to
exist in code. Building option B would mean flagging shoulders + arms as the flex role, which is the short-week rule above. That
rule belongs in `session_sequence`, behind an owner ruling.

## Rate policy interface (brief §10)

**#5861 FIX6 — the owner's ruling 11 (2026-11-13): the ADVISORY ceiling.** `rate_policy.advisory_ceiling(weights_by_day, ...)`
states ~1 % of the CURRENT 7-day mean weight a week as the upper planning reference — not a rule, never applied. The absolute
ceiling falls with the weight (1 % of a lighter body), a quarter of a point per slow signal (strength, fatigue, recovery,
adherence; floor 0.5 %, `SIGNAL_STEP_PCT`, `CEILING_FLOOR_PCT`, heuristic). Past weeks are judged against the base reference, never
today's signals. One unusually fast week is reported as such and is NOT a muscle-loss call: that needs the rate over the
reference in `SUSTAINED_WEEKS` (3) of the last 4 weeks AND a sliding strength signal. The live draft prints it as one line a week
(`live_rulings.rate_line`, the upper-heavy morning); the cron reads 35 days of weigh-ins for it (live only). `calorie_target`,
titration and the live rate band are untouched. `propose_band` below is unchanged.

`lambdas/health/rate_policy.py` proposes a target loss-rate **band in percent of bodyweight per week**. It reports the signal
that drove the band and the reason. It is pure and deterministic, and no live module imports it (a test sweeps `lambdas/` and
`mcp/` for any reader). The calorie target, the kcal floors, titration and the live rate band are unchanged.

**Inputs** (all optional; an unknown never speeds the band):

| Input | Platform source it is meant to come from |
|---|---|
| `body_fat_tier` | `training.redline_rate.body_fat_tier` (tiers in `owner_redlines` rate_protein_gate) |
| `observed_pct_bw_per_wk` | the rolling weight trend (`health.titration` trend / weight), reported only |
| `anchor_e1rm_change_pct` | the core-anchor e1RM trend behind the `anchor_lift_strength_drop` tripwire |
| `fatigue_level` | lane L3's fatigue model, injected (`low`/`normal`/`elevated`/`high`) |
| `recovery_low` | the sleep or `readiness_floor` tripwire state. The HR-regime caution applies: HR-derived readiness is not effort evidence |
| `protein_floor_days_missed_7d` | `training.redline_rate.protein_days_missed` |
| `intake_adherence_pct` | share of logged days inside the prescribed band (MacroFactor logs) |
| `hunger_high_days_7d` | the check-in hunger answer, where one exists |

**Rules** (labels as in the code):

| Rule | Value | Label |
|---|---|---|
| Start rung by body-fat tier | highest tier 0.75–1.25; middle and unknown 0.5–1.0; lowest 0.5–0.75 %BW/wk | practitioner heuristic (tier boundaries are the existing owner_redlines tiers) |
| Each slow signal | one rung down, floor 0.25–0.5 %BW/wk | heuristic |
| Nothing moves a band up | the start rung is the ceiling; max 1.25 %BW/wk | heuristic |
| Strength slow | 2+ anchors at or below −threshold, or one at or below −2x threshold | threshold read from `owner_redlines` (5 % today) |
| Adherence slow | protein floor missed on threshold days in 7, or intake in band on < 60 % of logged days | protein: owner_redlines; 60 %: heuristic |
| Hunger slow | high hunger on 4+ of 7 check-ins | heuristic |
| Fatigue slow | injected level `high` (`elevated` is a watch) | L3's model |
| Three or more slow signals | an `owner_decision` line (maintenance phase or diet break is the owner's call) | never proposed or applied here |
| Driver | strength > fatigue > recovery > adherence > hunger | the owner's priority order |

The ranges echo common practitioner guidance for losing fat while keeping lean mass, roughly 0.5–1 % of bodyweight a week. That
guidance is associated with Helms, Aragon and Fitschen 2014 (JISSN). Garthe and colleagues 2011 (IJSNEM) report a slower arm
keeping more lean mass than a faster one in athletes. Both are **named from memory and unverified**. Neither validates a rung for
this person.

**Where the nutrition side would read it (not wired).** The one seam is `health.titration.band_for(weight, guidance_cap)`,
which today returns the charter band or the landing-schedule step. If the owner adopts the policy, the seam would intersect the
proposal with that band: the proposal's %BW multiplied by weight, then the lower of the two ceilings and the guidance cap. So the
policy can only slow the target, never speed it past the charter. `health.calorie_target.resolve` would still clamp every day to
the owner's kcal floors (#5794). A slower band that titration meets by eating more is always allowed. A faster one can never
push intake under a floor. Try it with `python3 scripts/rate_policy_dry_run.py`, which runs synthetic profiles only.

**Rent and demotion (docs/PROPORTIONALITY.md).** No rent while unwired: one pure module, one script, one test file. Delete all
three if the owner declines the interface, or if L3's fatigue model and the existing tripwires end up feeding titration directly.
