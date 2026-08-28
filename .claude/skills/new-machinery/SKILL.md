---
name: new-machinery
description: "Check anything durable being added carries all five charter primitives — registry, derivation guard, ratchet, contract test, dead-man — and name which one is missing. Use before landing a new gate, registry, scheduled job, generated artifact, or any producer/consumer pair that must agree."
user-invocable: true
argument-hint: "[what you are adding]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TodoWrite
---

`docs/CHARTER.md` states the architecture in five primitives, and the observation that
motivates them: **every A-grade area of this platform applies all five; every C-grade area
is where one was skipped.** The charter's own epic (#2842) admits the pattern is currently
practised as recurring incident response rather than enforced up front.

This is the up-front check. Read the charter first — it is the authority; this is a
checklist over it.

## The five

**1. Registry — one executable source of truth for the vocabulary.**
Not a list in prose, not a constant copied into three consumers. Exemplar:
`lambdas/ingestion/source_registry.py`.
*Ask:* if someone adds the 12th one tomorrow, what breaks if they forget to update this?

**2. Derivation guard — a test proving consumers derive rather than hand-copy.**
Exemplar: `tests/test_source_enumeration_drift.py`. **Guard the SET, not the instance** —
the most-repeated lesson in the corpus, 10+ recurrences.
*Ask:* does the guard enumerate from source, and is it mutation-proven in both directions?

**3. Ratchet — debt counted, exemptions dated, the count only moves down.**
Exemplars: `tests/test_module_size_guard.py`, `tests/test_coverage_floor_ratchet.py`.
A ceiling is paid by **extraction, fold, or re-read — never a baseline raise** (six
collisions, zero raises).
*Ask:* is every exemption dated, and does each carry a reason long enough to prove someone
actually looked?

**4. Contract test — every must-agree pair tested on the REAL wire shape.**
Exemplar: `tests/grounding_wiring.py`. §9a: *the fixture must be the wire.* A green
non-vacuous gate over a false payload assumption guards nothing (#1221).
*Ask:* which two things must agree here, and what happens the day they stop?

**5. Dead-man — an "it silently stopped" detector, at birth.**
**Absence must be louder than failure.** Exemplar: `tests/test_heartbeat_completeness.py`.
An error alarm is explicitly *not* an absence signal.
*Ask:* if this stops running entirely, what goes red — and has that been watched going red?

## The output

State which primitives are present and **which one is missing**, explicitly. "All five"
is a legitimate answer only when you can point at each. A missing primitive is a
legitimate answer too — recorded, with its cost, in `docs/PROPORTIONALITY.md` alongside
the subsystem's posture and demote trigger.

Per the charter's change bar: a PR that adds a vocabulary copy, an undated exemption, an
uncontracted agreement, or a scheduleless dead-man is **off-charter and must say so.**

## Two traps specific to new machinery

- **A derived artifact needs its LANE.** Generator, writer, guard — *and the guard running
  in a lane the artifact's INPUTS trigger*. "Is there a guard?" answered yes for two of
  three broken artifacts; the guard simply never ran when it mattered.
- **Arming a semantic gate needs a baseline.** An LLM gate armed over an un-baselined
  surface blocks the deploy path on standing debt. Ship the triaged ledger in the same
  change.
