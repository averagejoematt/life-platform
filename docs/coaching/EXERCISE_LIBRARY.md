# Exercise library (v0.1, PROPOSED) — #5769

The coaching team's menu, chosen **before** drafting: what Matthew has done (his full Hevy history),
what he could do next (expansion candidates), what each movement trains, what it costs, what it needs,
what must be true before it is programmed, and what to swap to when the kit is missing.

**Status: `proposed`.** Nothing in the drafting path reads it (`tests/test_exercise_library_5769.py`
asserts no module under `lambdas/` or `mcp/` imports it). Gate evaluation is #5772; selection and
note rendering are #5771/#5773.

## Files

| Path | What |
|---|---|
| `config/exercise_library.json` | The PUBLIC library (built; committed). |
| `deploy/build_exercise_library.py` | Builder: read-only Hevy history Query + `config/movement_catalog.json` + curation. Preserves `version` / `change_log` / `status`. |
| `deploy/exercise_library_curation.py` | The hand-authored half: equipment vocabulary, verified citations, gates, per-template overrides, expansion candidates. |
| `lambdas/training/exercise_library.py` | Loader, schema check, gate rules, fallbacks, swap-note classifier, private-overlay join (fail-closed), private gate check. |
| `deploy/write_exercise_library_overlay.py` | Writer for the OWNER-PRIVATE overlay. Dry-run by default (counts only); `--out FILE`; `--apply` PUTs to S3. |
| `scripts/check_library_gates_private.py` | Private-side gate completeness check (prints ids + missing field names only). |
| `scripts/approve_exercise_library.py` | The only sanctioned `proposed -> approved` flip. |

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
`equipment` (ids from `equipment_vocabulary`) · `hypertrophy` (per target: tier, citations,
evidence_quality, last_reviewed) · `gates` · `not_for_you_now` · `availability.home_gym` ·
`fallbacks` (ranked). Attributes a rule cannot know are `unknown`.

**Hypertrophy tiers.** A or B only with a citation whose DOI/PMID was resolved (Crossref + PubMed) and
whose abstract was read. Everything else is C with `last_reviewed: "unreviewed"`.

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
- **KB swing (owner ruling 2026-11-11):** `chain_kb_swing` opens on exactly 2 logged KB-deadlift sessions.
- **Chain order:** a chain gate opens only when each prerequisite met its standard AND that prerequisite's own chain
  gates are open.
- **A clinical cue never locks** and is never an intensity gate; it rides the movement's `cues`.

It runs weekly as a fail-soft leg on the Monday panel-grade run (`mcp/exercise_gates_leg.py`), writing
`EXGATE#EVAL#<monday>` (docs/SCHEMA.md). A movement whose own gates open between two evaluations gets one
`EXGATE#ANNOUNCE#…` claim-once row — only while the library is `approved` — and `plan_next_session` stage 1 says it
once (`exercise_unlocks`). Logs carry gate ids, states and counts, never a bodyweight or a threshold.
