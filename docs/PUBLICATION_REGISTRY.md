# One publication registry — design and migration plan

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-11-05 · epic #5607 — the agreed PLAN (owner ruling 2026-11-05); stage 1 not yet started

Owner ruling 2026-11-05 (item 7): "one authoritative publication registry ... source identity, field classification, derived-data inheritance, publication eligibility and explicit owner approvals ... Do not discard existing working guards prematurely. Migrate incrementally, preserve negative controls and prove equivalent or stronger protection before removing legacy mechanisms."

## Today: eight mechanisms, four vocabularies

| Mechanism | Decides | Vocabulary | Enforced |
|---|---|---|---|
| `privacy/field_tiers.py` | per-field / per-source tier (0 public · 1 internal · 2 owner-only · 3 owner-published, ADR-155) | tiers | build-time wiring test; MCP strip |
| `common/narrative_provenance.py` | AI text publishable iff its stamped source families are all public; fail closed | families | wire chokepoint `web/narrative_publication.py` |
| `common/activity_publication.py` | sources, habits (by Habitify id), habit-status and State-of-Mind fields; activity aggregates over public sources | families + ids | per-serializer calls |
| `common/prediction_publication.py` (+ registry) | coach calls by subject and grading metric; public totals over eligible calls (method 2) | sources + reviewed fingerprints | the public table handle every site-API read uses |
| `health/character_privacy.py` | owner-only/private-source components and pillars; held pillar shape | components | per-reader `public_sheet` |
| `common/journal_silence.py` | keyword scrub of "journal silence" wording | regex | wire guard (defence in depth) |
| `privacy/privacy_guard.py` + content-filter channel | banned names / vice vocabulary (off-repo) | keywords | render/publish gates |
| bucket policy + `public_archive_registry` | which storage paths are anonymously readable / archived | prefixes | drift job + registry tests |

They mostly agree, but only because each was patched after the last leak. The 11-03→11-05 incidents were all the same shape: a consumer computed a public value from an input that one module classified private and the consumer never asked (circadian, character receipts, relationships, ledger counts, storage origin).

## Target: one registry, one decision function

`lambdas/privacy/publication.py` (new), the only module a public producer or serializer asks:

1. **Source identity** — one table keyed by the source id the data plane uses (`SOURCE_REGISTRY` keys, engagement channels, habit ids, apple_health sub-streams such as State of Mind). Each entry: class (`public` / `private` / `owner_published`), the owner approval that made it public (date + ADR/ruling ref), and its family name. Absorbs `SOURCE_FAMILIES`, `SOURCE_TIERS`, `ACTIVITY_ONLY_SOURCES`, `HABIT_FAMILIES`/`PUBLIC_HABIT_IDS`.
2. **Field classification** — per source, per field (absorbs `FIELD_TIERS` and `HABIT_STATUS_FIELDS`); an unlisted field inherits nothing and is private.
3. **Derivation / inheritance** — a derived value (score component, pillar, composite, aggregate, prediction, narrative, generated file) declares its inputs; its class is the meet of its inputs: public only if every input is public. Components/pillars (absorbs `character_privacy`), predictions (subject + grading metric), and narratives (`provenance.families`) are all instances of the same rule.
4. **Publication eligibility** — `decide(subject) -> Decision(publishable: bool, reason)`, fail closed on unknown; `public_view(record, kind)` returns the omitted-never-marked public projection. No counts of what was withheld.
5. **Owner approvals** — an append-only approval log in the registry (ruling date, scope, text reference), so every public class traces to a recorded decision (ADR-155 pattern). Approval changes are code review, never runtime config.
6. **Storage and static surfaces** — the routed public path set is declared once and the bucket policy, CloudFront behaviours and the archive registry are checked against it (today three independently maintained lists).

## Migration (incremental; each stage proves equivalence before anything is removed)

| Stage | Change | Proof before moving on |
|---|---|---|
| 1 | `publication.py` as a FACADE over the existing modules (no behaviour change); new code asks only the facade | equivalence test: for every source/field/habit/component in every legacy table, facade decision == legacy decision; existing negative controls untouched |
| 2 | Move tables into the registry; legacy modules become thin re-exports reading it | same equivalence test + every legacy test green unchanged |
| 3 | Derivation inheritance for scores/predictions/narratives through one function; consumers migrate one by one (character, predictions, circadian, status, pulse, fulfillment, chronicle packet) | per consumer: the byte-identical private-input invariance test + mutation control already written in #5647–#5652 must pass against the facade path |
| 4 | Storage/static: generate the bucket-policy routed set and the archive registry check from the registry | drift job + `test_public_write_prefix_registry_3741` + anonymous-curl probe |
| 5 | Retire legacy *decision* code only where stage-3 coverage is proven stronger; keep `journal_silence` and the content-filter as defence-in-depth wire guards (they are cheap and catch prose the provenance missed) | a removal PR must show the guard's negative control still failing through the registry path |

Guards that stay permanently: the keyword wire guard (defence in depth), the content-filter vocabulary channel (names/vices, different class), the public-surface route walk and the anonymous storage probe.

## Not in scope of the registry

Coach-grading classification, nutrition scoring and stance refreshes (separate owner tracks).
