---
name: qbr
description: "Run the board-level review of the BUILD of averagejoematt.com — the numbers first, then the Technical and Product boards' candid read, grounded strictly on measured values. Use when asked how the platform is doing overall, what to steer, what's improving, or what the jury is out on."
user-invocable: true
argument-hint: "[lens: board | delivery | quality | incidents | cost | autonomy | grades | bets | jury]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, TodoWrite
---

The standing board-level read of **how the building is going** — as opposed to how the
experiment is going. Numbers first, judgement second, and the judgement is not allowed
to outrun the numbers.

## Arguments: $ARGUMENTS

`$ARGUMENTS` may name one lens (`board`, `delivery`, `quality`, `incidents`, `cost`,
`autonomy`, `grades`, `bets`, `jury`) to go deep on it. Default: the full review.

## Why this exists, and the failure it is designed against

The owner is moving from orchestrator to N=1 user and cannot see the forest. Every number
that would answer "how are we doing" already exists across eight homes; `/method/state/`
joins them. This skill adds the one thing a JSON cannot: a judgement about what the
numbers *mean* and what to do next.

That is also the dangerous part. This platform has ADR-104 (honest numbers) and ADR-105
(uncertainty + n on every claim; **deterministic computation before any LLM verdict**)
because confident, plausible, ungrounded prose has burned it repeatedly — on 2026-09-07 a
coach wrote *"Garmin isn't syncing"* about a **deliberately paused** source and a gate had
to block it from readers. A board persona inventing a trend would be that failure with a
bigger audience of one.

**So the rule is absolute: every sentence a persona says must cite a number that is in
`site/data/platform_state.json`.** No number, no sentence. "Momentum feels good" is not a
finding; "median cycle time 12.7h over 659 closed issues, with the audit-sourced cohort at
29.2h against 8.7h organic" is.

## Phase 1 — Get the numbers. Never skip, never summarise from memory.

```bash
python3 scripts/build_platform_state.py          # regenerate; ~30s, mostly gate_census
python3 -c "import json;print(json.dumps(json.load(open('site/data/platform_state.json')),indent=2))" | head -200
```

Read `degraded_sections` FIRST. Any section listed there could not be computed this run —
it is an absence, and you must say so rather than reaching for a previous value. A QBR
that quietly reuses last month's number is the thing this whole surface exists to prevent.

Then read the artifact properly. The sections are `board`, `delivery`, `quality`,
`incidents`, `cost`, `autonomy`, `grades`, `bets`, `jury_out`.

## Phase 2 — Lead with the decomposition

Open with the board cohorts, always, because the raw open count is the number that
misleads. State it in this shape:

> N open → A actionable. Of those, R arrived from commissioned audits, F touch anything a
> reader sees, and P are P1. The remainder is the platform maintaining its own tooling.

Then the trend that matters most: is `actionable` moving, and is `reader_facing` moving?
A rising actionable count driven entirely by a review fan-out is a *choice we made*, not a
decay. Say which it is.

## Phase 3 — Convene the boards (they already exist — do not invent personas)

`docs/BOARDS.md` defines them. Use those, by name:

- **Technical Board** — architecture, security, code quality, data models, AI
  trustworthiness, cost, operational reliability. Sub-boards: Architecture Review,
  Intelligence & Data, Productization.
- **Product Board** — UI/UX, customer journey, audience growth, features, monetization,
  vision, story, throughline, content strategy.

Give each board **at most three points**, each anchored to a section of the artifact:

| Board | Reads | Must answer |
|---|---|---|
| Technical | `quality`, `incidents`, `autonomy`, `cost` | Is the machine trustworthy, and is it getting cheaper or dearer per unit of work? |
| Product | `board`, `delivery`, `grades`, `bets` | Are we building the right things, and is the reader-facing surface improving? |

Real disagreement is welcome and should be recorded when it exists — a board that always
agrees is a board that is not reading. Record dissent in the same shape
`docs/reviews/fullreview_grades_*.json` already uses.

## Phase 4 — The four questions the owner actually asks

Answer these explicitly, each with its number:

1. **What should I worry about?** — usually `jury_out.n_p1` and anything in
   `degraded_sections`. If the honest answer is "nothing urgent", say that plainly; a QBR
   that manufactures a concern to look rigorous is the same dishonesty in the other
   direction.
2. **What are we betting on?** — `bets.epics` (standing) and `bets.roadmap_parked`
   (vision, deliberately outside the debt count, one promotion per cycle per ADR-099).
3. **What is improving vs not?** — `grades.lenses` prior→now, and
   `quality.proven_fraction_pct`. Name what moved DOWN as readily as what moved up.
4. **What is the jury out on?** — `jury_out.awaiting_live_proof`: merged and deployed, but
   not yet observed producing its named live output. This is the platform's most honest
   category and the easiest to skip. Do not skip it.

## Phase 5 — Write it down

Write `docs/reviews/QBR_<YYYY-MM-DD>.md`:

- The decomposition paragraph from Phase 2 (verbatim numbers)
- One table: the metric, its value, its direction since the previous QBR if one exists
- Each board's ≤3 points, each with its citation
- The four answers from Phase 4
- **A "what I could not measure" section.** Non-negotiable. It carries `degraded_sections`
  plus the known standing gaps — today that is MTTD/MTTR, because `TTD`/`TTR` in
  `docs/INCIDENT_LOG.md` are free prose (`"~7h"`, `"9 days"`, `"Open — filed as #3419"`)
  and only ~60-70% parse, so any mean would be a selection artefact rather than a fact.
- Stamp it with the artifact's `generated_at`, not with today's date.

## Phase 6 — Turn judgement into work, sparingly

At most **three** filings, and only where a board named a specific defect with a number
behind it. File per ADR-099 (`## Problem` / `## Set` / `## Outcome` / `## Acceptance` /
score line / epic). A QBR that files fifteen issues has recreated the exact problem the
owner asked this surface to solve — that is the fool's-errand treadmill, restarted.

If nothing warrants filing, file nothing and say so.

## Cadence

On demand. **Never on a cron.** A QBR is an act of judgement, and judgement on a timer
becomes a template — which is how a board readout stops being read. The numbers are always
live at `/method/state/`; this skill is for when you want an opinion about them.

## What this skill must not do

- Invent a metric that is not in the artifact.
- Report a number from memory or from a previous run.
- Fill a degraded section with an estimate.
- Grade a lens itself — that is `/review`'s job, and its output is an input here.
- Produce persona prose with no number attached.
