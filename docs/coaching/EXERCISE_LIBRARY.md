# Exercise library (v0.3, PROPOSED) — #5769, #5857, #5861

The coaching team's menu, chosen **before** drafting: what Matthew has done (his full Hevy history),
what he could do next (expansion candidates), what each movement trains, what it costs, what it needs,
what must be true before it is programmed, and what to swap to when the kit is missing.

**Status: `proposed`.** Only the selection engine reads it (#5773, `lambdas/training/selection_engine.py`;
`tests/test_exercise_library_5769.py` asserts no other module under `lambdas/` or `mcp/` does), and while the
status is `proposed` it runs in SHADOW: the selection is recorded on each draft as `inputs_snapshot.selection_shadow`
beside the #5075 pools, which still serve. It changes live drafts only once the status is `approved`. Every draft
records `inputs_snapshot.library_version`. Gate evaluation is #5772; note rendering is #5771.

## Files

| Path | What |
|---|---|
| `config/exercise_library.json` | The PUBLIC library (built; committed). |
| `deploy/build_exercise_library.py` | Builder: read-only Hevy history Query + `config/movement_catalog.json` + curation. Preserves `version` / `change_log` / `status`. |
| `deploy/exercise_library_curation.py` | The hand-authored half: equipment vocabulary, verified citations and each row's evidence, gates, per-template overrides, expansion candidates. |
| `deploy/exercise_library_targets.py` | The reviewed layer: the target-label audit (#5857), attribute fixes, and (#5861) pattern fixes, categories, strength lifts, objective-input overrides, secondary target rows, canonical families and the reviewed-movement set — one reason per row. |
| `deploy/exercise_library_objectives.py` | #5861: the rule half of the evaluation layer — category, trunk function, functions, objective inputs, the canonical layer. |
| `deploy/exercise_library_additions.py` | #5861 lane L2 (optional): new canonical movements, read through `build_exercise_library.library_additions()`. |
| `lambdas/training/quality_rubric.py` | The rubrics: hypertrophy (points + caps + S criteria, #5857/#5861), strength, functional, conditioning, mobility; `objective_tier()`. Pure. |
| `lambdas/training/exercise_library.py` | Loader, schema check, gate rules, fallbacks, swap-note classifier, private-overlay join (fail-closed), private gate check. |
| `deploy/write_exercise_library_overlay.py` | Writer for the OWNER-PRIVATE overlay. Dry-run by default (counts only); `--out FILE`; `--apply` PUTs to S3. |
| `scripts/check_library_gates_private.py` | Private-side gate completeness check (prints ids + missing field names only). |
| `scripts/approve_exercise_library.py` | The only sanctioned `proposed -> approved` flip. |
| `scripts/library_evidence_review.py` | Per-block evidence review: re-verifies citations, decides proposals from the allow-listed sources, opens the owner's PR (#5778). |
| `config/evidence_source_allowlist.json` | The allow-listed source set (channels, designs, named reviewers, denied hosts). |
| `deploy/exercise_library_reviews.json` (+ `.py`) | The accepted-review ledger the builder re-applies. |

## Public vs private

The repo is public. The library carries **no bodyweight, no loads, no body-composition number and
no note text**. The N=1 half lives in the owner-private overlay
`s3://matthew-life-platform/config/coaching/exercise_library.private.json` (the #3043 owner-private
prefix — `deploy/bucket_policy.json` grants public read only on `site/*` and named `generated/*` keys):

- best set per 10-lb bodyweight band (`training.band_reference.band_key`), computed from DynamoDB;
- coded signals from his Hevy notes (pain / joint discomfort + region, sentiment, swaps, form checks,
  equipment fit, availability) — tag counts, never text;
- availability learned from swap notes; the detail behind each `not_for_you_now`;
- every gate's private row, including bodyweight threshold **values** (owner-set; `null` = locked).

`exercise_library.n1_view()` joins it at selection time. Overlay missing or unreadable → the N=1 fit
is `unknown`; it never raises.

## Per-movement fields

`source` (history | expansion) · `template_id` (null + `template_note` when Hevy has none) ·
`history` {first_done, last_done, exposures} · `target` · `family` (hypertrophy | strength_anchor |
carry_conditioning | core_anti_movement | skill_athletic | corrective) · `length_bias` · `resistance_profile`
· `stability` · `joint_stress` {spinal_load, shear, wrist, elbow, shoulder} · `skill_complexity` ·
`equipment` (ids from `equipment_vocabulary`) · `hypertrophy` (per target: `tier` S-D, `rubric_tier`, `rubric_score`,
`evidence_confidence`, `evidence_adjustment` when a direct trial moved it, `citations`, `last_reviewed`) · `gates` ·
`not_for_you_now` · `availability.home_gym` · `fallbacks` (ranked). Attributes a rule cannot know are `unknown`.

#5861 adds: `category` (hypertrophy | strength | conditioning | athletic | mobility | rehab_control | carry) ·
`trunk_function` on trunk work (loaded_flexion | anti_extension | anti_rotation | anti_lateral_flexion | rotation |
loaded_stabilisation) · `functions` where present (hip_flexion | grip | wrist_flexion | wrist_extension |
forearm_rotation) · `canonical` (the family head's key) and `variant` ({axis: value}, or `{duplicate_of}` on an exact
duplicate) · `objective_inputs` (below) · `ratings` {hypertrophy, strength, functional, conditioning, mobility}, each
`{tier: S-D | null, basis: [...], evidence_confidence, provisional}` (hypertrophy also `target` and `by_target`; each
rated hypertrophy row also `provisional` and, when true, `provisional_why`). A hypertrophy row the
objective does not apply to carries `tier: null`, `applicable: false` and its reason. The top level carries
`canonical_families`.

## Quality tiers — the hypertrophy objective (#5857 rubric v2.0.0, owner ruling 2026-11-12; #5861 rubric v3.3.0, PROPOSED)

The tier grades **quality, not evidence**. The first tiers (A/B/C) graded evidence directness: A was a direct trial
of this exact movement, B a trial of a close one, C `none_reviewed` — 561 of 582 ratings were C, and most muscles' top
band had one member or none. Owner, 2026-11-12: *"if we are saying there is only one S tier tricep exercise in the
world, that sounds slightly off … there may be a best of the best, but there may be some in that same territory to
justify S-tier."* So each per-target row's `tier` is a band S/A/B/C/D that a written rubric derives from the attributes
the library records, and evidence strength is its own field beside it. Rubric v1 (stretch first, one set of terms for
every movement) was red-teamed by a board the owner convened; on 2026-11-12 he adopted all eight of its
recommendations, and v2 is the result (`lambdas/training/quality_rubric.py`; the library carries the same table as its
`quality_rubric` block).

**Scored against the job.** Each movement carries a `job` — `compound` or `isolation` — set by the builder from its
movement pattern (`exercise_library.movement_pattern`: presses, dips, push-ups, rows, pulldowns, squats, lunges, hinges,
carries and Olympic lifts are compound; a pullover, a straight-arm pull and a Pallof press are isolation), never from the
muscle's name. v1 scored every press as if it were a fly; v2 does not. Per (movement, target):

| Term | Field | Isolation | Compound |
|---|---|---|---|
| stretch | `length_bias` | lengthened 5 · mid 3 · shortened 1 · unknown 3 (neutral, 3.2.0) | the same |
| stability (the target is the limiter) | `stability` | high 3 · moderate 2 · low 1 | high 2 · moderate 2 · low 1 (stabiliser demand is part of the job) |
| resistance profile | `resistance_profile` | single-joint upper-body targets (chest, the delts, biceps, triceps, forearms): cable / selectorized machine 3 · plate-loaded machine / free weight 2 · band / bodyweight 1. Other targets: free weight / any machine 3 · cable 2 · band / bodyweight / sled 1 | free weight / any machine / cable 3 · band / bodyweight / sled 1 |
| progressability | `skill_complexity` + profile | skill low 2 · moderate 1 · high 0, +1 for small external load steps | the same |
| carryover | `resistance_profile` | — | +1 for a free-weight compound |
| joint stress (a penalty) | `joint_stress` | −2 per joint rated high, −1 once for any joint rated moderate **or unknown**; the total never below −2 | the same |

Maximum 14 for both jobs. **Bands:** S >= 12 · A >= 10 · B >= 8 · C >= 5 · D below. **Unknown is not poor (3.2.0):** a term
whose input is `unknown` scores its NEUTRAL value (`quality_rubric.NEUTRAL`, the middle of its range: stretch 3, stability 2,
resistance profile 2, progressability 2, joint stress −1, carryover 0), never less — a fully unknown movement lands at B — and an
unknown never helps reach S (the `inputs_known` S criterion). See "Second red team" below. **No stretch premium for the glutes** (`STRETCH_CAPS`:
their stretch term is capped at mid; Plotkin 2023 found the shortened hip thrust equal to the lengthened back squat).

**Evidence** is `evidence_confidence`: `rct_direct` (a randomized trial of this target with this movement or its
defining variable) · `rct_characteristic` (a trial of the movement's defining characteristic: training length, joint
angle) · `consensus` (a named evidence-based reviewer's peer-reviewed position) · `none_reviewed`. Anything above
`none_reviewed` cites a reference whose DOI/PMID resolved (Crossref + PubMed) and whose abstract was read. **Only a direct
trial may move a row, and only one band** from its rubric tier, recorded on the row as `evidence_adjustment {bands,
citation, why}`: +1 when the trial found this movement grew the target more than a compared movement or range, −1 when
less, and +1 for **equivalence** (`basis: equivalence`, `comparator`) when the movement it matched sits in a higher tier
for the same target (checked library-wide by `exercise_library.validate`); a move past S or D is capped. The shipped
adjustments: the overhead cable triceps extension +1 (Maeo 2023), the seated leg curl +1 and the lying leg curl −1
(Maeo 2021), the standing calf raises +1 (Kinoshita 2023). No equivalence row ships: the hip thrust's comparator (the back
squat, for the glutes) rates B, the hip thrust's own tier, so parity earns nothing. Citations the board named from
memory go through the evidence-review allowlist before they back any row.

**Derived, never authored.** The builder writes `job`, `pattern`, `rubric_score`, `rubric_tier` and `tier` last, from the
final attributes; `exercise_library.validate` re-derives every row, so a hand-edited tier is a schema error
(`tests/test_quality_tiers_5857.py`, with its must-fail control). A muscle whose programmable pool (S and A) holds fewer
than two selectable movements names why in `quality_rubric.TOP_BAND_SHORTFALL` (empty since #5861: the ab-wheel rollout
and the cable reverse fly, once their attributes were reviewed, reach A beside the cable crunch and the machine reverse fly).

**How selection reads it** (`selection_engine`): **S and A are both programmable.** A slot's pool is its top two
non-empty bands (`pool_tiers`); inside the pool it ranks his N=1 fit first, then slot variety (the movement this slot
served least recently first, then not served by any slot in the lookback), then the tier as a tie-break, then evidence.
A pick outside S∪A is served only with a recorded reason (`C_REASONS`: every earlier code kept, plus `pool_fit` for a
pick that ranked first inside its pool over a higher-tier peer).

**Rotation (owner ruling B on #5856, amended 2026-11-12).** Once the library is approved, the nippard `rotation`
commitment accepts a pick held at a phase boundary only when it is the single servable member of its slot's S∪A pool
(`selection_engine.top_band.sa_members`; when S∪A has no servable member that week, the slot's own pool stands in), and
the hold is recorded on the rotation row. Two or more members rotate.

**Weekly free-weight floor (owner ruling 2026-11-12).** Every program week serves at least one free-weight compound for
each of press, pull, squat and hinge; anchors count (`week_floors.free_weight_compounds`, stage-1 row
`free_weight_compounds`, the charter's `dan_john` ledger line). It warns while the library is proposed and blocks once
it is approved. Finding: today's program meets press, squat and hinge through its anchors but serves no free-weight
back pull (its rows and pulldown are machine/cable anchors), so approval would block every week until the owner rules.

**Attribute audit (owner ruling 2026-11-12, blocking before approval).** `deploy/exercise_library_targets.py` carries
the reviewed `ATTRIBUTE_OVERRIDES` (the weighted chest dip is a free-weight dip, not a selectorized machine; the dumbbell
lateral raise's stability re-checked as moderate) and `JOINT_RATINGS_BY_PATTERN`, which rates every joint still `unknown`
on a movement whose pattern it covers, one reason per row; a rated joint is never overwritten, and each fill is recorded
on the entry as `attribute_audit`. No S or A row carries an unknown joint (`tests/test_quality_tiers_5857.py`).

**v3.0.0 changes to the points (#5861, PROPOSED).** Three terms changed, each for a stated reason: (1) a bodyweight
*compound* scores 2, not 1, on resistance profile — body mass loads a pull-up's or a dip's working range well; its weak
point is progression, which progressability already scores; (2) a calisthenics progression ladder (assisted ->
bodyweight -> weighted, kneeling -> standing; `objective_inputs.ladder`) earns the load-step point; (3) the glute stretch
term is FIXED at mid for any known length, not only capped: the trial that removed the stretch premium (the shortened hip
thrust matched the lengthened squat) equally removes the shortened penalty. Then the points band is held under the
categorical caps below (Objectives).

## Standing principles (owner ruling 2026-11-12)

These bind every later library and tier decision.

1. **The tier answers one question:** how good is this movement's hypertrophy stimulus for this target, in this job. It
   is never a verdict on a program's anchors and never ranks across jobs (a press is not compared with a fly).
2. **Classify by what the movement does.** Compounds and isolations are scored on terms that fit each, by movement
   pattern, never by muscle name alone.
3. **Missing data never helps.** An unknown attribute scores no better than a known moderate one: positive terms score
   0, penalty terms count as moderate. A row with unknown joints can't hold S over a fully rated rival.
   *Proposed amendment (#5861 FIX2-DATA, rubric 3.2.0 — needs the owner's sign-off):* missing data never helps AND never
   hurts — an unknown term scores the middle of its range (neutral), the row is marked `provisional`, and it can never
   reach S. The second red team showed "scores 0" had turned unreviewed movements into C/D verdicts.
4. **No equipment class wins by construction.** Swapping equipment (machine, free weight, cable) on the same pattern may
   move a movement at most ±2 points, and for a compound the best achievable score is the same for each class before the
   free-weight carryover point (held by `test_no_equipment_class_wins_by_construction`). Each pattern's top two bands
   should hold both a machine/cable and a free-weight member where the library has one, or the doc names why.
5. **Evidence moves bands only through direct trials, by one band,** and equivalence counts. A stretch or stability
   weight is not applied to a muscle where a direct trial contradicts it (the glutes today). Every citation resolves and
   is read, as the evidence review requires.
6. **The person lives outside the tier.** Body mass, balance, pain, availability, a clinical history (as a cue, never a
   cap) and enjoyment belong in gates, cues, N=1 fit and selection, never in the quality score.
7. **The top two bands are programmable.** S is first among equals, not exclusive. A single-member S band is a reason to
   rotate through A, not to hold.
8. **Every weight change ships with its diff:** a before/after band table of every movement that moves, a version bump,
   and the owner's sign-off before anything serves.

## Objectives (#5861, rubric v3.1.0 — PROPOSED, not live)

**Verdict on the 14-point rubric.** It is fit for one job and was being used for five. As a *hypertrophy stimulus
profile* for a loadable movement it holds up: its terms (length bias, stability, resistance-curve fit, progressability,
joint stress), its job classing, "unknown never helps" and the one-band evidence rule are all kept. It was not fit as
a universal quality score, for four reasons: (1) it rated carries, sleds, cardio, core control and cuff work on muscle
growth, so they sat at C or D by construction; (2) it had no term for the overload ceiling, for what limits the set,
or for stimulus-to-fatigue, so balance-limited lunges outscored the barbell squat and an assisted pull-up outscored the
pull-up; (3) its inputs were mostly title-regex output; (4) a 14-point sum implies a precision the inputs do not have.
So the points stay, for hypertrophy only, as one input, held under categorical caps; the other four objectives get
their own small categorical rubrics. No objective is forced: `null` means "not applicable", never "bad".

**The model.** Each movement records reviewed categorical `objective_inputs`; each objective's rubric
(`training.quality_rubric`) turns them into a tier S-D or null and writes the `basis` it used. The builder writes
`ratings`; `exercise_library.validate` re-derives them, so a hand-edited rating is a schema error. The one accessor for
consumers is `quality_rubric.objective_tier(entry, objective, target=None)`. `hypertrophy[].tier` stays populated (it IS
the hypertrophy objective's tier per target), so the selection engine and every existing reader keep working.

| Input (`objective_inputs`) | Values | What it says |
|---|---|---|
| `ceiling` | high · moderate · low · unknown | can the TARGET be overloaded progressively, in small steps, to failure (the overload ceiling) |
| `limiter` | target · balance · grip · mobility · trunk · other_muscle · technique · cardio | what ends the set for the primary target (a secondary row carries its own) |
| `systemic_fatigue` | low · moderate · high | whole-body cost per hard set: the fatigue side of stimulus-to-fatigue |
| `resistance_class` | maximal · submaximal · bodyweight · light | absolute loading class, for strength |
| `strength_lift` | true / false | one of the primary strength lifts (`STRENGTH_LIFTS`) |
| `ladder` | true / false | a calisthenics progression ladder exists |
| `functional` | unilateral · balance · carry · locomotion · trunk_stability · multiplanar · power | the functional qualities it trains |
| `conditioning` | {aerobic, control, impact, recovery} or null | the conditioning profile of a modality |
| `mobility` | passive · active · loaded · motor_control or null | the mobility / joint-function type |
| `reviewed` | true / false | checked by hand in the #5861 pass (else rule-derived only) |

**A. Hypertrophy (per target muscle).** The v3 points band, then caps: a low or unknown ceiling, or a limiter that is
not the target, holds the row at B; any unmet **S criterion** holds it at A. S needs ALL of: the points band is S; the
ceiling is high; the target is the limiter; stability high or moderate (it can be taken near failure); systemic
fatigue not high; no joint rated high; the inputs were reviewed by hand (3.1.0). A direct trial still moves the capped tier at most one band, and never to S
unless every S criterion holds. Not applicable (null) to categories conditioning, mobility, rehab_control, carry and
athletic, to a `full_body` / `cardio` / `other` target, and to isometric trunk control (anti-rotation, anti-lateral
flexion, loaded stabilisation).

**B. Strength.** Applies to a loadable multi-joint strength pattern (squat, hinge, press, pull, carry). S = a primary
strength lift + maximal resistance class + self-stabilised (free weight or bodyweight) + bilateral. A = maximal class
(a plate-loaded machine, a non-primary barbell lift, a sled) or a bodyweight pull/dip ladder. B = submaximal (dumbbell,
kettlebell, landmine, cable, selectorized). C = other bodyweight. D = light. Fatigue is reported in the basis and weighed
by selection, never a demotion: the heavy lifts are costly and are still the strength lifts.

**C. Functional.** Applies when the movement trains at least one functional quality. S = three or more qualities,
loadable, not high-skill, no joint rated high, not joint-capacity work (3.1.0), AND a carry or single-leg work under
travel or trunk load. A = two or more
loadable (or three or more). B = two, or one loadable. C = one.

**D. Conditioning.** Applies to a conditioning modality (and to carries, sleds and athletic drills with a conditioning
profile). S = aerobic stimulus high + intensity control high + impact low + recovery demand low. A = aerobic high + low
impact, or aerobic moderate + low impact + low recovery demand. B = aerobic high, or moderate without high impact.
C otherwise. Never penalised for lacking hypertrophy traits. **One rule per movement:** every modality the cardio model
(`lambdas/training/cardio_model.py`, lane L4 — it owns cardio) rates is rated by it alone (`conditioning_rating`, with its
N=1 sustainability from `history.exposures`, summed over the canonical family as `family_sustainability` so one machine is
rated once, 3.1.0); the table above applies only to what it does not model (carries, athletic
drills, bodyweight circuits).

**E. Mobility / joint function.** Applies to mobility, rehab/control and loaded end-range movements. Loaded (strength
through an end range the movement takes the joint into: a cossack squat, a dead hang) A; active or motor control B;
passive C. S needs specificity to a RECORDED limitation, which is owner-private N=1 data, so the public library never
awards a mobility S. Cuff rotations, face pulls, band pull-aparts and prone W / UCV / scarecrow raises train no range: they
are joint capacity, rated on functional (3.2.0, by class).

**Evidence confidence** stays separate from every tier. Hypertrophy rows keep `rct_direct` / `rct_characteristic` /
`consensus` / `none_reviewed` with their citations. The other four objectives are practitioner-consensus heuristics:
their rating reads `consensus` when the movement's inputs were reviewed and `none_reviewed` otherwise; no trial is
claimed behind any single one of them.

**Categories, trunk function, functions.** `category` is the movement's primary type (a label; the verdicts are the
ratings). Trunk work also carries `trunk_function`, so a crunch (loaded flexion), an ab-wheel rollout (anti-extension), a
Pallof press (anti-rotation), a side plank or suitcase carry (anti-lateral flexion), a twist (rotation) and a carry
(loaded stabilisation) are told apart. Hip flexion and the forearm functions (grip, wrist flexion, wrist extension,
forearm rotation) are their own `functions`, distinct from the target muscle.

**The canonical layer.** `CANONICAL_FAMILIES` (`deploy/exercise_library_targets.py`) names a head per family, its exact
duplicates (aliases: the same movement under another Hevy template, e.g. the two farmer's walks) and its variants with
their axes (grip, stance, range, tempo, equipment, resistance, laterality: the eleven lat pulldowns, the six cable
crossovers, the pull-up and push-up ladders). Every existing key and Hevy template id keeps its own entry and history;
`exercise_library.canonical_of(lib, key_or_template_id)` resolves either to the head. An alias takes its head's reviewed
attributes, so the same movement can never score twice. `tests/test_objective_ratings_5861.py` holds every pre-#5861 key
and template id to resolve.

**Limits — the tiers are not universal truths.** They are categorical judgements over recorded attributes, most of them
practitioner consensus, a few backed by a direct trial. They rank movements *for an objective, for a typical trained
adult*, not for everyone: a movement can be S for one objective and C or null for another, and that is the point. The
bands carry no precision finer than their inputs; two movements in one band are not ranked against each other by the
tier. They say nothing about dose, frequency or how a movement fits a session — that is selection, the fatigue model
and the program.

**How individual response modifies rankings.** The tier is the prior; the person decides. Inside a slot's programmable
pool, the owner-private N=1 fit ranks first (progression on the movement, pain history, sentiment, swap-outs;
`selection_engine.n1_fit`); a `pain`-class note excludes a movement; equipment availability and the gates remove what
cannot be done; a mobility S exists only against a recorded limitation. A movement that keeps progressing for him
outranks a higher-tier one that does not, and a pain signal outranks any tier.

**The reviewed-attribute pass.** Fixed as data, each with a one-line reason in the reviewed layer: the walking lunge is
no longer cardio (the `walking` word); the crossover step-up is a step-up, not a chest fly; the cuff external rotations
are `shoulder_rotation`, not trunk flexion; the weighted push-up, pull-up and chin-up are free weight, like the weighted
dip; push-ups and step-ups have a length rule (mid); the Pallof press targets the abs everywhere; the dumbbell rear-delt
flies are dumbbells, the cable reverse fly is mid-length; the ab wheel is lengthened anti-extension; the linear leg press
and the inverted row are typed by what they are; the triceps kickbacks are triceps extensions; the rowing machine is
cardio; the military press is the barbell overhead press (an alias). `REVIEWED_KEYS` lists every movement checked by
hand; a hypertrophy S/A/B row, or an S/A on another objective, outside it is red.

**The owner's anomalies, worked through the framework** (before = rubric v2 hypertrophy tier; after = every objective,
H / St / F / C / M, "-" = not applicable):

| Anomaly | Movement | Before | After | Why |
|---|---|---|---|---|
| Weighted push-up D | push_up_weighted | D | H A · St B | free weight like the weighted dip; push-up length rule (mid); moderate ceiling holds it at A |
| Pull-ups below pulldowns | pull_up / pull_up_weighted / pull_up_assisted / lat_pulldown_cable | B / B / S / S | H A, St A / H S, St S / H A, St B / H S, St B | body mass loads a compound; the ladder earns the load step; an assisted machine is a regression (moderate ceiling); the weighted pull-up is a primary strength lift |
| DB lateral raise low | lateral_raise_dumbbell | B | H B | unchanged on purpose: its torque peaks at the shortened top; the cable (S) and machine (A) load the long range. N=1 fit ranks it inside the pool |
| Step-ups D | step_up / db_step_up | D / C | H C, F B / H B, F A | step-up length rule (mid); balance is the limiter (B cap); rated on functional |
| Walking lunge D | walking_lunge_dumbbell | D | H B · St B · F S | no longer cardio; balance limits the quads (B); single-leg work under travel is functional S |
| Farmer's carry C (and its duplicate D) | farmers_walk, farmers_walk_8d414b80 | C / D | H - · St B · F S · C C (both) | an alias pair, one rating; a carry is never judged on hypertrophy |
| Sled push / pull D | sled_push, sled_drag | D | H - · St A · F A · C B | category carry: loaded locomotion |
| Ab wheel D | ab_wheel | D | H A · F B | lengthened anti-extension with a kneeling-to-standing ladder |
| Bird dog / side plank / cuff D | bird_dog, side_plank, rotator_cuff_external_rotation | D / D / D | F C, M B / F B / F B, M - | rehab and control work, rated on functional, never on growth; cuff rotation is joint capacity, not mobility (3.1.0) |
| Cossack and unusual lunges S for quads | db_cossack_squats, 3_way_lunge, offset_lunges, drop_step_lunges, … | S | quads B (cossack: adductors A, M A; offset: F S) | balance or mobility, not the quads, ends the set; DB held lower-body work has a moderate ceiling. Squats, leg press and split squats now sit above them (A) |
| All cardio D | treadmill, cycling (= recumbent_bike), elliptical, rowing_machine, air_bike, walking, running | D | H - · C S / S / A / A / B / C / C | rated on conditioning only, by lane L4's cardio model (walking: hard to dose and progress; running: high impact) |
| No S glute | hip_thrust_machine, glute_kickback_machine, hip_thrust_barbell | A / A / B | A / A / A | glute length fixed at mid both ways (Plotkin 2023); the kickback stack's load ceiling is moderate (3.1.0: a single-leg lever stack caps the absolute load), so A; the barbell hip thrust's moderate skill and stability hold it at A, and (3.2.0, evidence ordering) the untested machine form ties it rather than outranking the movement the trial tested — so no glute S: the glute pool is the A band (owner decision noted below) |
| Weak adductors | db_cossack_squats, sumo squats, side lunges, squat_barbell | — | adductors A / A / B / A | reviewed secondary rows; adduction machines and Copenhagen work are lane L2's additions |
| Inconsistent rear delts | rear_delt_reverse_fly_machine / _cable / rear_delt_fly / face_pull | S / B / C / B | S / A / B / B (face pull F B) | the cable fly is mid-length like the machine; the dumbbell flies are dumbbells; the face pull's cuff work is joint capacity, rated on functional (3.2.0) |

**S census.** `_provenance.s_census` reports, per objective and muscle, how many movements are S and how many distinct
canonical families they are. No quota: every S already met every S criterion of its objective. `tests/test_objective_ratings_5861.py`
re-checks each S against its criteria.

## Red-team data fixes (#5861 FIX-DATA, rubric v3.1.0 — PROPOSED)

An independent red team graded the integrated engine C+ and named library DATA errors (the attributes, not the formula, were the
main source of wrong tiers). Each is fixed through a reviewed override with a one-line reason (`deploy/exercise_library_targets.py`,
`deploy/exercise_library_objectives.py`, the curation layer), then the SAME class was swept library-wide. Guards:
`tests/test_data_fixes_5861.py`.

| Error class | Specimen | Fix | Swept |
|---|---|---|---|
| a bent-knee calf raise credited to the gastrocnemius | `seated_calf_raise` | soleus only (the row is removed in the curation layer) | every calf movement: only the seated raise is bent-knee |
| a lateral side bend classed loaded flexion | `side_bend_dumbbell` | new trunk function `lateral_flexion`, pattern `core_lateral_flexion` | `saxon_side_bends`, `side_crunch_slow_cadence` |
| a hypertrophy row on a muscle that is not the primary | the three Pallof presses (row `shoulders`, primary `abs`) | the row follows the audited primary (`sync_primary_row`) | the sled push / pull, the Turkish get-up, `dead_hang`, `hang_high_pull` |
| a supported movement rated unstable | `spider_curl` (chest-supported), the bench-supported dumbbell flies, incline skull crusher | stability high / moderate | the whole `supported / incline / chest` title class |
| naturally short ROM penalised | the shrugs (C) | `STRETCH_NOT_ESTABLISHED`: the traps' stretch term reads mid (a heuristic, no trial) and a heavy shrug is grip-limited (B) | traps only |
| a lateral RAISE read as balance-limited | `bent_arm_lateral_raises`, `db_cheat_laterals` | the balance limiter never applies to an upper-body pattern | every `balance` limiter reviewed |
| the title regex missed the pattern (a hyphen, a missing word) | `knee_push_up`, `elbows_tucked_db_bench`, the glute-ham raises, `front_raise_dumbbell` | reviewed `PATTERN_OVERRIDES` | every movement left at pattern `other` with a tier |
| custom template with no equipment read as bodyweight | `shoulder_press`, `tricep_extension`, `overhead_tricep_extension`, `seated_bicep_curls`, `21s`, `one_arm_bench_press` | resistance `unknown` (a load is needed; the owner names it) | every bodyweight-resistance loaded-pattern movement |
| one machine, two rows, two tiers | `prone_leg_curl` = the lying leg-curl machine; `db_incline_curls` = the seated incline curl; `gorilla_row_kettlebell` ~ the dumbbell gorilla row; `cycling` = `recumbent_bike` | canonical families (ids and history preserved); equipment fixed | every same-title / same-core pair |
| the lunge family had no glute row | every loaded lunge / split squat / step-up | a glutes row (B: balance is the limiter, or target when stable) | `add_glute_row`, one rule |
| cuff rotation is not mobility | the three cuff external rotations | `mobility` n/a (joint capacity, rated functional B) | the cuff family |

**S is tightened, not quota-ed.** (1) S now also needs *reviewed* inputs (`reviewed_inputs`). (2) The glute kickback machine reached S
with a high load ceiling; a single-leg lever stack caps the absolute load far below the glutes' capacity (the hip thrust carries the
heavy loading), so its `ceiling` is moderate: A. (3) Copenhagen functional S: it carries the `joint_capacity` quality, which the rubric
always said never reaches S; the code now enforces that (functional A). S stays rare: see the S census in `_provenance`.

**One cardio rating per machine.** The recumbent bike and Hevy's "Cycling" are the same machine; they are one canonical family with one
`family_sustainability`, so the cardio model rates them once. *Cardio-model note (lane L4's file, not edited here):* the model still reads
the row's session count (N=1 sustainability) to award S; a public tier should not depend on one person's history, so the better fix is for
`cardio_model` to expose sustainability as a separate N=1 input (the private overlay) and cap the public tier at A.

## Second red team: unreviewed is not poor (#5861 FIX2-DATA, rubric v3.2.0 — PROPOSED)

The second red team cross-tabbed hypertrophy tier against `objective_inputs.reviewed`: every S/A/B row was reviewed and nearly
every C/D row was not, so "C/D" meant "nobody filled in the inputs", not "poor exercise" (Glute Ham Raise D, Shrug (Machine) D).
The owner's brief forbids that: evidence and input confidence are separate from exercise quality.

**1. Unknown scores neutral, and the row says it is provisional.** A term whose input is `unknown` scores `NEUTRAL` (the middle of
its range), never less, so an unreviewed movement is never pushed below what its class supports — a fully unknown movement is B,
the middle band. It never helps either: S needs `inputs_known`, and an unknown ceiling or limiter keeps the B cap. Every rating
that rests on title-rule (unreviewed) inputs — or, for a hypertrophy row, on an input still unknown — carries `provisional: true`
and `provisional_why`, shown beside the tier and `evidence_confidence`. A placeholder, not a verdict. (Heuristic, labelled.)

**2. The reviewed-input pass** (`deploy/exercise_library_input_review.py`, `REVIEW`: per movement the attributes and inputs a hand
review set, or confirmed, and one reason): every movement logged on 3+ days inside the library's 5-year window, every movement
in an S/A band on any objective, the red team's named rows, and every reviewed movement still carrying an unknown. A one-field
`INPUT_OVERRIDES` row no longer implies a full review (the machine hip thrust's limiter fix had marked all its inputs reviewed).
Fourteen logged custom templates that are not growth movements are typed by what they are (mobility drills, cuff and scapular
control, trunk endurance, a plyometric, a rope pull), so they leave the hypertrophy table instead of sitting in it at D.
Where the title does not identify the movement (`double_db_frog_press`, `hip_buck`, `nsfw`) or the equipment is unrecorded
(`21s`, `shoulder_press`, `overhead_tricep_extension`), the review leaves the unknown and the row stays provisional with the
reason: the owner can name them. Guards: `tests/test_unreviewed_not_poor_5861.py`.

| Hypertrophy rows (rated) | before: reviewed / title-rule | after: reviewed / title-rule / provisional |
|---|---|---|
| S | 50 / 0 | 49 / 0 / 0 |
| A | 108 / 0 | 121 / 0 / 2 |
| B | 146 / 0 | 166 / 52 / 61 |
| C | 13 / 84 | 19 / 44 / 47 |
| D | 1 / 63 | 0 / 0 / 0 |

Movements logged on 3+ days in the window: 230; inputs reviewed 152 before, 230 after; 6 still provisional (the six above).
Every S/A rating on every objective rests on reviewed inputs. The remaining title-rule rows are movements he has not used (B or
C, provisional): no S/A, so no programmable pool holds one.

**3. Evidence ordering.** An untested form of a trial-backed movement ties the tested form at best, never outranks it
(`EVIDENCE_FORMS` -> `evidence_ceiling` on the form's row, a cap in `hypertrophy_caps`). The barbell hip thrust carries the direct
trial (Plotkin 2023); the machine hip thrust scored S on heuristic points (pin-stack stability, a smaller load step) with no trial,
so it now ties the barbell at A. Evidence does not lift the barbell form: the trial's comparator (the back squat) rates B for the
glutes, so equivalence earns no band. A trial that ranked a movement LOWER (`bands: -1`) anchors nothing.

**4. The named rows.** Glute Ham Raise D -> A (bodyweight knee flexion from full extension, thighs pinned, a ladder; reviewed).
Shrug (Machine) D -> B (a guided shrug, grip-limited like every shrug). Face pull mobility A -> n/a, functional B: cuff, face-pull,
pull-apart and W / UCV / scarecrow work trains no range, so the class left loaded mobility. Pull-up A vs pulldown S, kept: the
bodyweight pull-up's load ceiling is the body (moderate) and S needs a high ceiling; its progression past bodyweight is the
weighted pull-up, which is S beside the pulldown — the criteria rank the forms, not the pattern.

**5. `programming_settings`** (top level): the programming lane's library-carried settings with their owner-pending defaults
(`session_cap_includes_cardio: false`, `symptom_line`, `short_week_rule: skip_shoulders_arms`, `behind_schedule_week: false`).
Written once by the builder; a value on disk (an owner's ruling) survives every rebuild.

## Third red team: the S quota and two class rules (#5861 FIX3, rubric v3.3.0 — PROPOSED)

The third red team (2026-11-13) graded the integrated engine B-. Its data findings, fixed in the generator (never by hand):

**1. One S per canonical family per objective** (`deploy/exercise_library_reviews.apply_s_quota`, read by
`quality_rubric.hypertrophy_caps` / `objective_ratings`). "S is not rare": every lat-pulldown grip was S (16 back S), five cable-fly
variants were S, the single-leg calf and leg extension shared their bilateral form's S. Now, per objective (per target muscle for
hypertrophy), ONE member of a canonical family holds S — the canonical movement itself when it earned S, else the variant he has
done most — and every other real variant that earned S carries `s_quota {holder, family}` and is capped at A with the line
`S quota: one S per canonical family (…) — … holds it; a variant`. An exact duplicate (another Hevy template of the same movement,
`variant.duplicate_of`) shares its canonical's rating: it is the same movement. A direct trial cannot re-open a capped S (3.3.0).
S counts, before -> after: **hypertrophy 49 -> 34** (= one per family-and-target, plus the exact duplicates), **strength 10 -> 10**
(the one second S is `military_press`, an exact duplicate of the barbell overhead press), **functional 10 -> 9**, conditioning and
mobility 0 -> 0. Guard: `tests/test_programming_fix3_5861.py::test_one_s_per_canonical_family_per_objective` (its control removes one
variant's quota and the family shows two S).

**2. Shoulder-provoking work loads the shoulder** (`deploy/exercise_library_input_review.SHOULDER_PROVOKING`, applied after the
canonical layer). Lateral raises, face pulls, reverse flies, rear-delt rows, upright rows, Y raises and cuff rotation work read shoulder
`low` ("light, no joint loaded hard"), so a 6/10 sharp shoulder note left them at RPE 9–10. Abduction toward 90 degrees, horizontal
abduction and loaded rotation are the classic painful-arc provocations: their shoulder rating is now at least `moderate` (23 rows), so
the live pain rule reaches them. It is a PAIN-MAP floor, not a joint cost for a healthy shoulder: the row records
`provocation_floor {shoulder: {from, rule}}` and the hypertrophy rubric's joint term reads the reviewed `from` rating — no tier moved
(the DB lateral raise stays B, the machine A, the single-arm cable S). Practitioner consensus, labelled; no trial is claimed.

**3. One spine-loading class** (`SPINE_AT_SIDES`). A split squat, lunge or step-up with dumbbells or a kettlebell at the sides read two
ways (the Bulgarian split squat and the dumbbell split squat `moderate`, every other lunge `low`), so the stacking rule "swapped" a
split squat for a reverse lunge that loads the spine the same — a label moved, not the fatigue. The whole class reads `low` (the
pattern table's own rating for it); barbell, front-rack, goblet and overhead forms keep their own. The engine counts spine-loading lifts
by ONE definition (`live_balance.spine_loading`), shared by the stacking rule, the acceptance gates and the sample-week generator.

**Not changed here (rating policy, not a data error):** the 14-point additive hypertrophy sum and its stretch weight, the DB lateral
raise at B, pull-up A vs pulldown S (the S quota now leaves one pulldown S), and per-row evidence labels for the strength and
functional rubrics (still the rule-level `consensus`). Each is named on the PR as open.

## Fourth red team: the knee/hip pain map and four input corrections (#5861 FIX4, library 0.3.2 — PROPOSED)

The fourth red team (2026-11-12) graded the engine B- (safety C). Its data findings, fixed in the generator (never by hand):

1. **Knee and hip in the joint-stress map** (`deploy/exercise_library_input_review.KNEE_HIP`, a class rule). A knee-pain note on
   the squat was routed as a spinal-load flag because the map had no knee. Every movement now carries `knee` and `hip`:
   knee-dominant squat, lunge, split-squat, step-up and knee-extension work is `high` for the knee; the regressions a physio uses
   (box, wall, Spanish squat) `moderate`; a pull off the floor, a leg curl and loaded locomotion `moderate`; the RDL family `low`.
   Hinges are `high` for the hip; loaded hip flexion and hip-dominant isolation `moderate`. Upper-body and trunk rows read `low`; a
   lower-body row no rule recognises stays `unknown` (never read as safe). An alias takes its head's rating. **This is a PAIN-MAP
   rating, practitioner consensus, not a trial** — the live pain rule reads it (`live_program.joint_flags`); the rubric's joint
   cost does NOT (`quality_rubric.RUBRIC_JOINTS`, the five original joints), so no tier moved on it. Adding the knee and hip to the
   joint cost would re-tier the lower body: a separate, reviewed change (owner decision).
2. **The band rung of the pull-up ladder.** Hevy's built-in "Pull Up (Band)" (template 56808FD2, `is_custom: false` in the
   template index) is now a library movement (`pull_up_band`, no gate: the band is the on-ramp) and a catalog `coach_added` entry of
   the vertical-pull family — a garage with a bar serves it instead of the dumbbell pull-over.
3. **Generous tiers, corrected at the input that was wrong** (`exercise_library_targets.INPUT_OVERRIDES`): the landmine press (both
   forms) and the trap pulldown read a `moderate` load ceiling (hypertrophy S -> A: the bar's arc and one bar end cap the press;
   the trap pulldown is a short-range scapular-depression pull); the sled push and pull are `submaximal` (strength A -> B: loaded
   locomotion is not a maximal-strength lift). Walking C vs the incline treadmill A was rechecked and KEPT: the incline is what
   gives the treadmill its high stimulus and fine control; outdoor walking is moderate stimulus, low control.
4. **Trunk drills are not strength lifts** (`CATEGORY_OVERRIDES`): the Pallof press family is `rehab_control` (anti-rotation, rated
   on functional) and the ab wheel `hypertrophy` (anti-extension for the abs).

## Target-label audit (#5857, owner-approved on PR #5858)

A movement's `target.primary` came through raw from Hevy's own muscle label, and the rubric grades a movement against that
muscle — so a straight-arm pulldown was rated as a shoulder exercise, a high cable row as chest, every lunge as hamstrings
and a squat-to-row as triceps. `deploy/exercise_library_targets.py` is the reviewed table (`TARGET_OVERRIDES`, library
key -> audited primary + a one-line reason). The builder applies it after the rule derivation and the curation and before
any tier is derived: the primary and region move, every hypertrophy row on the old primary moves with it (a sub-target
row such as `triceps_long_head` stays), and the entry records `target.audit {from, reason}`. A key not in the library is
a hard stop; `tests/test_target_audit_5857.py` holds the library to the table both ways and pins the table's size, so an
override cannot vanish silently.

Vocabulary beyond Hevy's muscles: `side_delts`, `rear_delts`, `front_delts` (a rotator-cuff or general shoulder drill stays
`shoulders`); `traps` (shrugs, trap raises); `adductors`; and `full_body` — a compound or conditioning movement (a
squat-to-row, a lunge-curl, a thruster, a carry), graded against no single muscle, so it never sits in a single-muscle
tier and never matches a muscle slot. **Vocabulary gap:** the charter's volume landmarks still group the side and rear
delts as one (`volume_priorities.sets_per_wk.side_rear_delts`, `block_model` maps it to `shoulders`) and have no front-delt
or traps landmark; the split lives in the library only.

**How selection reads it** (`selection_engine.rank_key`): quality tier first, then his N=1 fit, then variety (the
movement this slot served least recently first, then not served by any slot in the lookback), with evidence confidence
as a tie-break only. A C or D pick is served only with a recorded reason (`C_REASONS`, unchanged codes).

**Rotation (owner ruling B on #5856, 2026-11-12).** Once the library is approved, the nippard `rotation` commitment
accepts a pick held at a phase boundary only when it is the single servable member of its slot's best band
(`selection_engine.top_band`), and the hold is recorded on the rotation row. A band with two or more members still
rotates.

## Gates

Shape in `gate_schema`; kinds: `bodyweight_threshold` (value private), `chain_prerequisite`,
`performance_threshold`, `pain_flag_exclusion` (global), `charter_gate` (points at the training charter),
`owner_confirmation`, `equipment_available` (global), `clinical_cue` (a cue, never a lock). Unknown input
= locked. `exercise_library.requires_*` say which movements must carry which kind; the tests hold every
entry to them.

## Availability (`home_gym`; the gym is never named)

Owner ruling 2026-11-11: equipment used by a movement logged in the last 5 years is `available`;
equipment seen only in older history or only in expansion candidates is `unknown`. A "the gym doesn't
have X" note marks X `unavailable` (owner-confirmable); "X was taken" / "no bench free" is contention and
never changes a state. Seed: no preacher curl machine (owner note 2026-11-08).

## Fallbacks

Every movement carries up to three ranked substitutes (`exercise_library.fallback_candidates`):
same target + pattern (`same_stimulus`) first, then same target, then same family; ungated before gated;
equipment-disjoint from the primary first, so a missing item is a swap, not a hole.

## Rebuild

```bash
python3 deploy/build_exercise_library.py                  # dry-run summary
python3 deploy/build_exercise_library.py --write
python3 deploy/write_exercise_library_overlay.py --out /tmp/overlay.json   # dry-run + local file
```

## Evidence review (per block, #5778)

`scripts/library_evidence_review.py`, run from the training-review skill (§7) once per block — no schedule.
It PROPOSES; the owner accepts by merging the PR it opens; it never merges and never pushes main.

- **Re-verification.** Every registered citation is resolved live: DOI via Crossref, PMID via PubMed E-utilities,
  title + first author + year matched, the PMID's DOI cross-checked, a retraction / erratum / comment pubtype
  rejected. `not_found` or retracted on every citation behind a reviewed row proposes that row's evidence back to
  `none_reviewed` (its tier falls back to the rubric's); a
  `mismatch` is reported for a `correct_citation`; `unreachable` changes nothing. Exit 1 on a definitive failure.
- **Allow-listed sources only** — `config/evidence_source_allowlist.json` (hand-owned; a change to it is a reviewed
  PR): channels `pubmed`, `crossref`, `reviewer` (a named evidence-based reviewer's peer-reviewed paper, cited by its
  DOI/PMID). No social media, blogs or bare URLs (a denied host is rejected by name). Study designs and the evidence
  each may back (`may_back`, #5857): randomized trial `rct_direct` / `rct_characteristic`; controlled trial,
  meta-analysis, systematic review `rct_characteristic`; narrative review and position stand `consensus` at most, and
  only with a named reviewer among the authors.
- **Verification before evidence.** A proposed citation registers only if it resolves live with a DOI. It backs
  evidence only with a verified PMID, `abstract_read: true` and a design the allowlist permits for that confidence;
  otherwise the row stays `none_reviewed`. A proposal sets evidence (`set_evidence`, with an optional one-band `adjust`
  that only `rct_direct` may carry) — never the quality tier, which the rubric derives. Every proposed change carries its citation. Nothing is invented: the optional `--discover` PubMed search is
  a reading list built from the library's own targets, never a change, and no model is used.
- **Outputs.** Dry-run by default (prints the report + diff, writes nothing); `--out DIR` writes
  `proposal.json` + `library.diff`; `--open-pr --issue N` makes a locked lane off `origin/main`
  (`scripts/lane_worktree.py`), edits `config/exercise_library.json` (patch version bump + a `change_log` line) and
  appends one record to `deploy/exercise_library_reviews.json`, commits through `deploy/agent_commit.sh` (named paths only), pushes the lane branch and
  runs `gh pr create`.
- **Durable across rebuilds.** `deploy/build_exercise_library.py` re-applies the ledger
  (`deploy/exercise_library_reviews.py`): its citations beside the curation's, its candidates beside `EXPANSION`,
  its evidence changes over the derived rows; the quality tier is then re-derived.

## Approval (the owner's step)

1. The owner sets the bodyweight threshold values in the private overlay (`gates.<id>.value`) and the
   driver writes it (`deploy/write_exercise_library_overlay.py --apply`; a re-run keeps owner-set values).
2. Run the private check — it must pass:
   `python3 scripts/check_library_gates_private.py` (or `--overlay FILE`).
3. Approve — this re-runs the schema check and the private check and refuses on any failure:
   `python3 scripts/approve_exercise_library.py --by "owner ruling YYYY-MM-DD"`, then commit via a PR.

Never flip `status` by hand.

## Gate evaluation (#5772)

`lambdas/training/exercise_gates.py::evaluate_gates(library, overlay, measured)` is the one evaluator — pure, no reads,
no clock — and the selection engine (#5773) calls the same function. It returns, per gate id,
`{kind, state, input, reason, value_seen, unlock_condition}` (plus `by_movement` for the LOCKED carriers of a
per-movement kind); `movement_states` folds that into a per-movement `{state, locked_by, reasons, unlock_conditions,
cues}` — every "not for you now" carries its reason and its unlock condition.

- **States are `unlocked` and `locked` only.** An unknown input is `locked` with `input: "unknown"` and a reason
  naming what was not measured; there is no third state a consumer could mistake for a pass.
- **A null owner value** (the six owner-unset bodyweight thresholds) is `locked`, `input: "not_set"`, reason
  `threshold not set by owner`. An unread overlay is `unknown`, not `not_set`.
- **Measured inputs only:** the 7-day mean bodyweight (Withings, the phase evaluator's reading), the Hevy record over
  the last 12 weeks for chain and performance standards (an unlogged RPE or an unrecorded assistance/tempo is not
  evidence), the #5800 note class over 28 days (only a `pain` note locks; `discomfort` and `form_or_equipment` never do), the run gate as the May tracker reads it, and
  the charter's own numbers (power-clean revisit weight, lower-leg-prep carve-out) — read, never copied.
- **Template match:** a movement with no standard Hevy template can carry `template_match.title_all`; any logged exercise
  whose title carries every word counts (the KB deadlift, until #5810 picks its template).
- **Owner confirmation:** the overlay's `technique_confirmations` (movement id -> `{confirmed_on, source}`, seeded by
  `deploy/write_exercise_library_overlay.py::OWNER_TECHNIQUE_CONFIRMATIONS`, never dropped on a re-run) meets the
  `owner_confirmation` gate for that movement only — its chain and bodyweight gates still apply. Owner ruling 2026-11-11:
  `clean` and `hang_power_clean` confirmed.
- **Progression standards** (every chain and performance gate) are owner-approved as proposed (ruling 2026-11-11); the six
  owner-set bodyweight values stay null, so those gates stay locked and the library stays `proposed`.
- **KB swing (owner ruling 2026-11-11):** `chain_kb_swing` opens on exactly 2 logged KB-deadlift sessions.
- **Chain order:** a chain gate opens only when each prerequisite met its standard AND that prerequisite's own chain
  gates are open.
- **A clinical cue never locks** and is never an intensity gate; it rides the movement's `cues`.

It runs weekly as a fail-soft leg on the Monday panel-grade run (`mcp/exercise_gates_leg.py`), writing
`EXGATE#EVAL#<monday>` (docs/SCHEMA.md). A movement whose own gates open between two evaluations gets one
`EXGATE#ANNOUNCE#…` claim-once row — only while the library is `approved` — and `plan_next_session` stage 1 says it
once (`exercise_unlocks`). Logs carry gate ids, states and counts, never a bodyweight or a threshold.
