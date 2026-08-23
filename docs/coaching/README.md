# `docs/coaching/` — what lives here, and what deliberately does not

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-23 (#3043, DIL-001)

This repo is **deliberately public** (since 2026-07-20). Owner-private coaching
material therefore does not live in this directory — or anywhere in the tree.

## Owner-private coaching material → the S3 owner prefix

The owner-private coaching corpus lives at
**`s3://matthew-life-platform/config/coaching/`** (the delete-protected `config/`
prefix, owner-credential access only). Relocated there 2026-08-23 (#3043):

- `PROVEN_BLUEPRINT.md` — the empirical anchor (owner's own history, mined)
- `TRAINING_CALIBRATION.md` — how the coach calibrates the owner
- `TRAINING_PROGRAM.md` — the current plan
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
orders, routine specs) without the owner-personal specifics that made the five
files above Tier-2. Anything Tier-2 that a public page could serve is governed by
`docs/DATA_GOVERNANCE.md`, not by this directory.
