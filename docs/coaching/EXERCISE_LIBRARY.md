# Exercise library (v0.1, PROPOSED) — #5769

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
| `deploy/exercise_library_curation.py` | The hand-authored half: equipment vocabulary, verified citations, gates, per-template overrides, expansion candidates. |
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

## Evidence review (per block, #5778)

`scripts/library_evidence_review.py`, run from the training-review skill (§6) once per block — no schedule.
It PROPOSES; the owner accepts by merging the PR it opens; it never merges and never pushes main.

- **Re-verification.** Every registered citation is resolved live: DOI via Crossref, PMID via PubMed E-utilities,
  title + first author + year matched, the PMID's DOI cross-checked, a retraction / erratum / comment pubtype
  rejected. `not_found` or retracted on every citation behind an A/B row proposes that row's downgrade to C; a
  `mismatch` is reported for a `correct_citation`; `unreachable` changes nothing. Exit 1 on a definitive failure.
- **Allow-listed sources only** — `config/evidence_source_allowlist.json` (hand-owned; a change to it is a reviewed
  PR): channels `pubmed`, `crossref`, `reviewer` (a named evidence-based reviewer's peer-reviewed paper, cited by its
  DOI/PMID). No social media, blogs or bare URLs (a denied host is rejected by name). Study designs and the tiers
  each may back: randomized trial A/B; controlled trial, meta-analysis, systematic review B; narrative review and
  position stand context only, and only with a named reviewer among the authors.
- **Verification before tier.** A proposed citation registers only if it resolves live with a DOI. It backs a
  tier only with a verified PMID, `abstract_read: true` and a design the allowlist permits; otherwise the row stays
  C. Every proposed change carries its citation. Nothing is invented: the optional `--discover` PubMed search is
  a reading list built from the library's own targets, never a change, and no model is used.
- **Outputs.** Dry-run by default (prints the report + diff, writes nothing); `--out DIR` writes
  `proposal.json` + `library.diff`; `--open-pr --issue N` makes a locked lane off `origin/main`
  (`scripts/lane_worktree.py`), edits `config/exercise_library.json` (patch version bump + a `change_log` line) and
  appends one record to `deploy/exercise_library_reviews.json`, commits through `deploy/agent_commit.sh` (named paths only), pushes the lane branch and
  runs `gh pr create`.
- **Durable across rebuilds.** `deploy/build_exercise_library.py` re-applies the ledger
  (`deploy/exercise_library_reviews.py`): its citations beside the curation's, its candidates beside `EXPANSION`,
  its tier changes over the derived rows.

## Approval (the owner's step)

1. The owner sets the bodyweight threshold values in the private overlay (`gates.<id>.value`) and the
   driver writes it (`deploy/write_exercise_library_overlay.py --apply`; a re-run keeps owner-set values).
2. Run the private check — it must pass:
   `python3 scripts/check_library_gates_private.py` (or `--overlay FILE`).
3. Approve — this re-runs the schema check and the private check and refuses on any failure:
   `python3 scripts/approve_exercise_library.py --by "owner ruling YYYY-MM-DD"`, then commit via a PR.

Never flip `status` by hand.
