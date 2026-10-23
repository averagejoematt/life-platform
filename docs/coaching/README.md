# `docs/coaching/` — what lives here, and what deliberately does not

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-09-21 (#3753/#3755 v0.3 flip; #3043, DIL-001)

This repo is **deliberately public** (since 2026-07-20). Owner-private coaching
material therefore does not live in this directory — or anywhere in the tree.

## Owner-private coaching material → the S3 owner prefix

The owner-private coaching corpus lives at
**`s3://matthew-life-platform/config/coaching/`** (the delete-protected `config/`
prefix, owner-credential access only). Relocated there 2026-08-23 (#3043):

- `PROVEN_BLUEPRINT.md` — the empirical anchor (owner's own history, mined)
- `TRAINING_CALIBRATION.md` — how the coach calibrates the owner
- `TRAINING_PROGRAM_v0.3.md` — the current plan, in prose (**v0.3, owner-approved
  2026-09-21**, #3753/#3755; its red-team record is `TRAINING_PROGRAM_v0.3_redteam.md`;
  `TRAINING_PROGRAM.md` is the unapproved v0.2 and `TRAINING_PROGRAM_v0.1_2026-09-19.md` the
  original draft). **The machine-readable half is two bundled modules:**
  `lambdas/training/owner_redlines.py` (v3.0 — the §6 redlines and §7 tripwires, provenance
  on each; `landing()` is the §8 block) and `lambdas/training/program_structure.py` (v0.3 —
  three full-body sessions + an optional fourth, six anchor patterns 2x/wk, trap bar until
  275 lb, loads that hold, accessories fixed for the block, and the week grid as data the
  engine reads, plus the computed accessory-drift check that `plan_engine.constraint_block`
  reports). They ship in the Lambda bundle because `config/*.json` does not (#3675). Both
  readers of the week grid go through one seam, `training.program_seam.resolve_week_grid`,
  which serves the module's grid now that `program_structure.ACTIVE` is True (with the
  review date) and would fall back to the live `config/training_week.json` if it were
  flipped off. The owner's 2026-09-19 PPL ruling on #3755 is superseded by his 2026-09-21
  approval; `SPLIT_DECISION` records both dates.
- `TRAINING_CONTEXT.md` — standing injury + equipment constraints, each dated (#3715).
  **Not yet uploaded** (no AWS write access from this agent) — render it from the
  registry with `python3 scripts/render_training_context_md.py`, then pipe to
  `aws s3 cp - s3://matthew-life-platform/config/coaching/TRAINING_CONTEXT.md`.
  **UNCONFIRMED by the owner** (`gate:owner`, #3715) until he reviews the list in
  `lambdas/training/training_context_registry.py`'s `RECORDED_CONSTRAINTS` and flips
  `CONFIRMED_BY_OWNER` there — a coach must not treat it as cleared before that.
- `WORKORDER_BENCH1_benchmarking.md` — the BENCH-1 work order (ADR-089)
- `WORKORDER_DI1_movement_integrity.md` — the DI-1 work order (ADR-091)

Read them with owner credentials, e.g.:

```bash
aws s3 cp s3://matthew-life-platform/config/coaching/TRAINING_CALIBRATION.md -
```

The prefix name is not sensitive; the content is. A tracked file in a public repo
cannot be private — `tests/test_no_private_markers_3043.py` enforces that no
tracked file ever declares itself PRIVATE again.

## The files that remain here are deliberately public

`COACH_SESSION.md` (a pointer since #5086: the session protocol is `.claude/skills/coach-session/SKILL.md`), `CHAT_MODES.md`, `READING_CALIBRATION.md`,
`WORKORDER_HEVY_COMMIT_HARDENING.md`, and `routines/` were reviewed 2026-08-23
(#3043) and stay public on purpose: they document *how the coaching system works*
(session protocol, chat-mode registry, calibration philosophy, engineering work
orders, routine specs) without the owner-personal specifics that made the six
files above Tier-2. Anything Tier-2 that a public page could serve is governed by
`docs/DATA_GOVERNANCE.md`, not by this directory.

`PROGRESS_PHOTO_PROTOCOL.md` (#3761) joins that public list: it documents the
weekly-photo *capture procedure* (timing, lighting, distance, poses, clothing) —
none of it owner-personal content — while the photos themselves stay Tier-2
owner-only per `docs/DATA_GOVERNANCE.md`'s `progress_photos` entry. A working
copy also lives at `s3://matthew-life-platform/config/coaching/PROGRESS_PHOTO_PROTOCOL.md`
beside the rest of the owner-private corpus, for convenience — this repo copy is
the source of truth.

## Owner notes on the coach-nudge tick

Two deterministic, owner-only notes ride the hourly `coach-nudge` tick beside the coach's own
nudge, each on its own ledger row and each at most once a Pacific day: the lifting-day steps
note (#5056, `training.steps_nudge`) and the protein breakfast note (#5098,
`health.protein_engine.nudge_decide`). The protein note reads the charter's
`nutrition.protein` block — the range, four feedings at or above the feeding threshold, the
breakfast cut-off — and the same engine owns the one definition of a protein hit that the
scoring engine, the macros view, the critics and the `protein_floor_missed` tripwire share.

## The weekly calorie titration

The calorie target moves weekly by a rule the owner can read (#5096, `health.titration`): the
charter's `nutrition.titration` block — the shared 14-day trend against the charter rate band,
two consecutive weekly reads on the same side before a step, 14 days between steps, a step of
at most 150 kcal sized from the miss, feet before fork (below the band: the steps mean must be
at the floor, then a walking-first week, and food comes down only 14 days after it with the
trend still under the floor), complete logs counted against the redlines' dark-day line, and a
hold whenever the data or any rule value is unreadable. The steps-floor precondition on top of
the owner's walking-first rule is the panel interpretation, pending an owner ruling (#5091). The decision
is made Friday night for the coming week, carried by every calorie surface through
`health.calorie_target`, and shown with its reason in the Saturday nutrition-review email. The
weekly refit itself is built on the panel default, pending R1 (#5091).
