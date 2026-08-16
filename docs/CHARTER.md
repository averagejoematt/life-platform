# The Platform Charter

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-16

**The five-primitive constitution** (#2843, epic #2842 "The Kernel"). This is the
session-boot architecture source: read this first, derive the rest. The 2026-08-16
elite review measured what this document declares — every A-grade subsystem in the
platform is built from the same five primitives, and every C-grade area is a place
one of them is missing. Until now the pattern was re-derived incident by incident
from prose docs and session memory. It is the architecture; here it is written down.

## The five primitives

Every durable subsystem here is the same five pieces. When grading, extending, or
debugging an area, ask which of the five it has — the missing one is where it will
fail silently.

1. **Registry** — one executable source of truth for each vocabulary (sources,
   coaches, pages, lambdas, channels, gates). Canonical exemplar:
   `lambdas/ingestion/source_registry.py` (cadence, paused state, raw layout,
   staleness — read the facet, never hand-state it). If a vocabulary appears in two
   places, one of them owns it and the other derives.

2. **Derivation guard** — the test proving consumers actually derive from the
   registry instead of hand-typing a copy. Canonical exemplar:
   `tests/test_source_enumeration_drift.py`. Guard the SET, not the instance: a
   guard on one copy of a list is a guard on nothing.

3. **Ratchet** — debt is counted, exemptions are dated, and the count only moves
   down. Canonical exemplars: `tests/test_module_size_guard.py`,
   `tests/test_coverage_floor_ratchet.py`. New debt needs a dated ledger entry;
   entries are only ever removed.

4. **Contract test** — every pair of things that must agree gets a test that fails
   when they diverge, written against the real wire shape (fixture must be the
   wire). Canonical exemplar: `tests/grounding_wiring.py`. The registry of which
   gate owns which defect class is `docs/CONVENTIONS.md` §9.

5. **Dead-man** — every scheduled thing has a detector for "it silently stopped
   running"; absence must be louder than failure. Canonical exemplar:
   `tests/test_heartbeat_completeness.py`.

## The paved roads

The ONLY sanctioned way to add each kind of thing. Off-road work is what the review
sweeps keep re-finding; if a road is missing, pave it before driving.

- **A signal** (metric, device, source): `docs/NEW_SIGNAL_PLAYBOOK.md` (ADR-154) —
  capture unfiltered → privacy tier BEFORE the first cron → absence semantics at
  birth → ingest-vs-park per consumer → SoT ruling per overlap → the consumer
  sweep. Registry: `source_registry.py`. The per-field × consumer-family wiring
  registry is epic #2797.
- **A lambda**: its ADR-146 domain package under `lambdas/`, registered in its CDK
  stack with its own least-privilege role, added to the mypy clean set
  (`tests/mypy_clean_set.py` globs are non-recursive), and — if scheduled — a
  heartbeat under `tests/test_heartbeat_completeness.py`. Enrollment-by-construction
  (all of that from one declaration) is being paved as #2846; until it lands the
  consumer sweep is manual and `tests/test_lambdas_packaging_guard.py` holds the
  packaging invariant.
- **A page**: `tests/qa_manifest.py` is THE page registry (#1426); visual QA and
  the smoke sweep derive from it (`tests/test_qa_manifest.py` gates the
  derivation). A page not in the manifest does not exist to QA.
- **A coach**: `config/personas.json` via `lambdas/coach/persona_registry.py`
  (CC-00); `tests/test_persona_registry.py` enforces no orphans across the three
  historically-divergent id-spaces.
- **A gate**: register it in `docs/CONVENTIONS.md` §9 (defect class → owning gate,
  #1349), name the defect class it owns, and prove it can fail (mutation evidence —
  a gate that cannot fail is a green light wired to nothing).

## The standing rules

1. **No hand-maintained enumeration** of registry vocabulary without a dated
   exemption. The fleet-wide enforcement is the #2844 conformance guard; until it
   lands, this is the review bar every PR is held to.
2. **Debt counts only ratchet down.**
3. **Every new "must agree" pair gets a contract test at birth**, on the real wire
   shape.
4. **Every scheduled thing gets a dead-man at birth**, and every metric states its
   absence semantics at birth (ADR-104 — honest numbers; ADR-105 — uncertainty and
   n on every statistical claim, deterministic computation before any LLM verdict).

Machinery added under these rules still pays rent: posture + rent + demote trigger
per subsystem in `docs/PROPORTIONALITY.md` (ADR-103/144) — consult it before adding
or removing anything.

## Using this

- **Session boot:** this charter (+ the system model, #2845, when it lands) is the
  architecture context; the prose docs are depth, not prerequisites.
- **Grading frame:** `/uplevel` and the review skills grade an area by asking which
  of the five primitives it is missing — that, not taste, is what separates the
  platform's A areas from its C areas.
- **Change bar:** a PR that adds a vocabulary copy, an undated exemption, an
  agreement without a contract test, or a schedule without a dead-man is
  off-charter and needs to say so explicitly.
