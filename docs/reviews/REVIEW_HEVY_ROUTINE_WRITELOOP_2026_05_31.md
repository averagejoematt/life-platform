# Review — Hevy Routine Write-Loop

> **Destination in repo:** `docs/reviews/REVIEW_HEVY_ROUTINE_WRITELOOP_2026_05_31.md`
> **Date:** 2026-05-31
> **Status:** Approved to outline (all three boards consulted)
> **Boards convened:** Technical (Architecture Review, Intelligence & Data, Productization), Product (lane check), Personal (routine quality)
> **Related:** `SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31.md` (build outline), `docs/BOARDS.md`

---

## 1. Use case & requirements

Close the training loop with Hevy. Two front doors onto one system:

1. **Conversational authoring** — in a Claude session inside the life-platform project, deliberate with the coaching layer / boards and create, modify, or delete Hevy routines for the day or week ahead.
2. **Automated generation** — the platform generates routines on a schedule and writes them to Hevy.

Hevy API supports this: `create`/`update` routine, exercise-template fetch, folders, and webhook subscriptions. Requires a Hevy PRO subscription (already held — Hevy is an active logging source). Exact endpoint/field contract to be verified at build time.

## 2. Proposed approach (the spine — endorsed)

- **One write path, two front doors.** Both the cron and the chat path stop at a shared **routine-spec IR** and hand off to one **Hevy compiler** that owns the wire format.
- **Exercise-template-ID mapping** as a first-class cached layer (internal movement vocabulary → Hevy template ID), with a loud failure on unmappable movements.
- **Overwrite safety** modeled on the S3 `DeleteObject`/tombstone stance: stable routine identity, update-in-place, conflict detection so an in-app manual edit is never silently clobbered.
- **Pause-Mode gating** on the automated path (WR-47).

## 3. Technical Board

### Architecture Review (Priya, Marcus, Yael, Jin, Elena, Omar)
- **Priya Nakamura** — IR is the system of record: persisted and versioned in DynamoDB; Hevy is a downstream projection. Gives a replayable audit trail of proposed → pushed → performed.
- **Omar Khalil** — `ROUTINE#` partition, versioned, linked to workout records so "did I do what was programmed?" becomes queryable (programmed-vs-performed adherence).
- **Marcus Webb** — Cache the exercise-template list (S3/DynamoDB, TTL); don't re-fetch per generation. Write-capable Hevy key gets its own Secrets Manager secret (bundling principle: same creds + same Lambda set only).
- **Jin Park** — Idempotent, resumable generator; transactional id-mapping write; on Hevy outage at cron time → backoff + dead-letter + alert, never silently skip a week.
- **Elena Reyes** — Encapsulate all Hevy wire-format knowledge in one module so an API change touches one file.
- **Yael Cohen** — The chat path exposes a write-capable tool to an LLM. Mandatory commit gate + dry-run mode. If Hevy webhooks are used, validate signatures; treat inbound as untrusted.

### Intelligence & Data (Anika, Henning, Omar, Elena)
- **Anika Patel** — Log the *why* behind every generated routine (inputs used). Hard output caps so a bug cannot program absurd volume. Bounded, auditable.
- **Dr. Henning Brandt** *(dissent)* — Daily autoregulation assumes the readiness signal predicts training capacity; that is unvalidated for Matthew (N≥30). Ship deterministic, volume-landmark templates first; do not enable or publicize daily readiness-adaptation until validated. Correlative language only.

### Productization (Raj S, Sarah C, Viktor, Dana, Priya)
- **Viktor Sorokin** *(Principal of No)* — Hevy builds routines in ~2 min. The write-path + overwrite machinery is only justified if generated routines are *meaningfully better* by using data Hevy lacks (recovery, volume landmarks, labs). If it just transcribes routines you'd build anyway, don't build it.
- **Raj Srinivasan** — The wedge is the conversational path, not the cron. Risk: an engine used twice. Build the manual path; observe real usage; then automate.
- **Sarah Chen** *(Tech Board PM — distinct from Personal Board's Dr. Sarah Chen)* — The real problem is "close the program → perform → adapt loop." Pushing routines is one third; without adherence-readback and adaptation it's a fancy exporter.
- **Dana Torres** — Cost negligible (Hevy free w/ PRO). Decide deterministic-vs-LLM generation core now; per-day inference recurs, deterministic is near-free and satisfies auditability.

## 4. Product Board (lane check)

Mostly out of lane — internal tooling, not a user-facing surface (**Mara Chen**). Genuine contributions:
- **Ava Moreau** — The closed loop is a chronicle story beat ("content that runs without Matthew"), under Elena's editorial guardrails and correlative framing.
- **Dr. Lena Johansson** — If averagejoematt.com showcases "autoregulated programming," it must be defensible or it damages credibility. Don't publicize until validated (echoes Henning).
- **Raj Mehta** — Tie success to adherence-to-program, not "routines generated."

## 5. Personal Board (routine quality)

- **Dr. Sarah Chen** (sports scientist) — Goal stack is longevity/functional strength, not hypertrophy max. Generator must default conservative — start near **MEV**, progress slowly. Conservative, landmark-aware programming *is* the answer to Viktor's "meaningfully better" bar.
- **Dr. Victor Reyes** (metabolic/longevity) — Portfolio awareness: don't let strength sessions crowd out Zone 2 / mobility. Program the whole decathlon.
- **Dr. Henning Brandt** — Autoregulation is asymmetric: **may only subtract load** (deload on red recovery / high ACWR), **never add**, until the readiness signal is validated (N≥30). Safe to ship day one and honest.
- **Coach Maya Rodriguez** — Produce a **floor routine** (≈20-min minimum-effective-dose) for low days alongside the ideal plan. Program for the version of Matthew who shows up tired.
- **Dr. Nathan Reeves** — Re-entry after a break is the highest-injury, highest-dropout moment. Return routines must be deliberately easy and carry **no accumulated guilt-debt**. Pause-Mode principle applied to programming.
- **Empty seat** — Strongest argument yet to fill the backlogged **Sports Medicine / Movement Quality** seat. Until filled, generator hard-biases to joint-friendly machine/DB variants over high-skill barbell lifts when programming unsupervised.

## 6. Consolidated verdict & change list

Approach approved to outline. The spine survives intact and reinforced. Changes/additions/edits vs. the initial sketch:

1. **Demote autoregulation** from headline to unvalidated hypothesis; ship deterministic volume-landmark templates first (Henning/Lena).
2. **Add the missing third of the loop** — programmed-vs-performed adherence readback; `ROUTINE#` partition linked to workouts (Omar/Sarah C).
3. **IR is the system of record**, persisted/versioned; Hevy is a projection (Priya).
4. **Sequence is a gate, not a preference** — conversational path only first; build cron only after real usage + Viktor's "meaningfully better" bar + readiness validation (Raj S/Viktor).
5. **Chat-write safety** — mandatory commit gate + dry-run; own Secrets Manager secret (Yael).
6. **Operational hardening** — idempotent/resumable, transactional id-map, backoff/DLQ/alert, bounded outputs, logged rationale (Jin/Anika).
7. **Deterministic generation core**, not per-day LLM (Dana/Henning).
8. **Programming-quality guardrails** — MEV default, asymmetric autoregulation, floor session, easy guilt-free re-entry, portfolio awareness, joint-friendly bias (Personal Board).

## 7. Open items / prerequisites before build

- [ ] Fill (or stand up an interim) **Sports Medicine / Movement Quality** Personal Board seat.
- [ ] Verify exact **Hevy API contract** (endpoints, routine JSON schema, rate limits, template ID format).
- [ ] Confirm **deterministic generation engine** design (no per-day LLM in the core).
- [ ] Define the **readiness-signal validation** plan before any "add load" autoregulation.
