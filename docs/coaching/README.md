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

`COACH_SESSION.md`, `CHAT_MODES.md`, `READING_CALIBRATION.md`,
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
