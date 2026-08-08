# The stack manifest — `stack.json`

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-08

**Fork the architecture, not the data.**

`https://averagejoematt.com/data/stack.json` is a machine-readable description of this
platform as an *instrument*: what it measures, how each source is ingested, what protocols
and supplements sit under measurement, and what it honestly costs to own. Its schema is
published next to it at `/data/stack.schema.json`.

It exists because "fork my setup" is a reasonable thing to want and a bad thing to answer
with a repo tour. The repo is public, but reading 101 Lambdas to find out *which wearables
feed this and what the bill is* is not a good use of anyone's evening. The manifest answers
that in one fetch.

**It is not a description of the subject.** No health metrics, no weights, no lab
readings, no per-day records, no identifiers. The line is enforced, not merely intended —
see *Privacy* below.

---

## Files

| Path | What it is |
|---|---|
| `site/data/stack.json` | The published manifest. **Generated — never hand-edit.** |
| `site/data/stack.schema.json` | The published JSON Schema (2020-12). Documents every field's meaning, not just its type. |
| `scripts/v4_build_stack_manifest.py` | The generator. Run from repo root; also runs inside `deploy/sync_site_to_s3.sh`. |
| `config/cost_of_ownership.json` | The *only* hand-maintained input — see *Cost* below. |
| `tests/test_stack_manifest_drift.py` | The guard suite. |

Regenerate with:

```bash
python3 scripts/v4_build_stack_manifest.py
```

---

## Where every field comes from

Nothing in the manifest is a hand-typed restatement of a list that lives elsewhere. That
pattern — a second copy of a list, slowly diverging from the first — is the failure this
repo has hit repeatedly, and a manifest is the most tempting possible place to repeat it.

| Section | Derived from |
|---|---|
| `sources[]` | `scripts/v4_build_data_sources.py::build()`, itself `lambdas/ingestion/source_registry.py::catalog_entries()` plus that generator's clinical/archive rows. **Same entry point as `/data/data_sources.json`**, so the manifest and the public data catalogue cannot disagree about which sources exist. |
| `sources[].behavioral` / `.paused` / `.raw_scheme` | The matching `SOURCE_REGISTRY` facets, read per source id. |
| `sources[].ingest_pattern` | Derived from the registry's `active_api` / `oauth` facets first, falling back to the `method` text. A closed vocabulary — see below. |
| `sources[].device` | `scripts/v4_build_gear.py::GEAR`, which already carries its own coverage assert against `catalog_entries()`. |
| `protocols[]` | `site/config/protocols.json` — the file the site itself serves. |
| `supplements[]` | `site/config/supplement_registry.json` — the **published** copy, deliberately (see *Privacy*). |
| `cost_of_ownership.aws.monthly_usd_typical` | `lambdas/web/site_api_common.py::PLATFORM_STATS["monthly_cost"]` — the same constant `/api/platform_stats` serves to `/method/cost/`. |
| `cost_of_ownership.aws.ceiling_usd` / `.surge_ceiling_usd` / `.surge_trigger_trailing_7d_uniques` | `lambdas/operational/cost_governor_lambda.py` constants (ADR-063/133). |
| `cost_of_ownership.supplements.*` | Summed from the manifest's own `supplements[]` rows. |
| `cost_of_ownership.time.recurring_manual_touchpoints` | Counted from the manifest's own `sources[]` rows. |
| `cost_of_ownership.aws.actuals` / `.composition` | `config/cost_of_ownership.json`, pinned to `docs/COST_TRACKER.md` by test. |

### The ingest-pattern vocabulary

A closed set, enumerated in the schema's `$defs.ingestPattern` and in the generator's
`INGEST_PATTERNS`. A source that matches none of the rules **fails the build** rather than
being quietly filed as `manual_entry` — a catch-all bucket is how a vocabulary stops
meaning anything.

| Pattern | Meaning |
|---|---|
| `scheduled_credentialed_pull` | Scheduled API pull behind a credential that can expire or be rotated. |
| `scheduled_keyless_pull` | Scheduled API pull with no credential to die. |
| `webhook_push` | The provider pushes; near-real-time. |
| `file_transport` | A file lands in cloud storage and a poller picks it up. |
| `habit_bridge` | Projected out of another source's habit records. |
| `manual_entry` | A human types it in. |
| `frozen_archive` | Historical import, no live writer. |

### The one idea worth copying

`sources[].behavioral`. A record from a *behavioral* source only exists because a human did
something — weighed in, trained, logged a meal. A gap there is a logging lapse, so it must
never page anyone. An *infrastructure* source's pipe runs unattended, so a gap means
something broke. The tie-breaker is the sync mechanics, not the vendor: a smart scale is
behavioral (it only writes when you step on it) while a 24/7 wearable is infrastructure.

Getting this backwards is how an operator is trained to ignore the one alarm class that
matters. It is one boolean, and it is the highest-leverage thing in the file.

---

## Privacy

Three layers, all enforced by `tests/test_stack_manifest_drift.py`:

1. **Unannounced sources can't leak.** The registry's `catalog: False` flag marks sources
   that are wired but that the owner has not chosen to advertise. Because the manifest
   derives its source set from the same generator the public catalogue uses, that gate
   applies here for free — and a test asserts the exclusion actually holds, because this
   is the door a leak would come through.
2. **Field allowlists, not denylists.** `sources[]`, `protocols[]` and `supplements[]` each
   have an exact permitted field set. Widening what is public therefore requires editing
   the allowlist in a diff, deliberately. The supplement projection is the exact column set
   `/protocols/supplements/` already renders — name, group, dose, timing, evidence grade,
   monthly cost, paused — and nothing else. The catalogue's narrative fields (the owner's
   reasoning, citations, board attributions) stay on his page, in his voice.
3. **A pattern sweep for identifiers and subject data.** Account ids, ARNs, bucket names,
   partition keys, secret paths, distribution ids, endpoint hostnames, body weights, lab
   readings. Note the deliberate distinction: a lab *threshold* is part of a protocol's
   definition and belongs here (`time-in-range (<140 mg/dL)` is what the instrument watches
   for); a lab *reading* is subject data and does not.

`protocols[]` also drops `key_finding`, `signal_note`, `signal_status`, `adherence_target`
and `start_date`. Those are results about a person. The manifest publishes what the
protocol *is*, never what it did to him.

The architecture block is vendor-neutral by design: generic service categories, no resource
names, no region, no function names. A fork should copy the shape, not the deployment.

---

## Cost of ownership

Per ADR-104 (honest numbers) and ADR-105 (uncertainty and *n* on every claim), every figure
in `cost_of_ownership` carries a `basis` — how it was derived — and a `confidence`.

**Consistency with the live cost page is structural, not editorial.** The run-rate is read
from the same constant `/method/cost/` renders, so the two cannot age apart. The ceilings
are read from the governor that enforces them. The supplement total is the sum of the rows
printed in the same file, so a reader can check the arithmetic.

**A null is a claim.** Device prices and human hours are `null`, each with a `basis` saying
why:

- **Devices** — every price is vendor-set, varies by region and plan, and changes without
  notice. This platform does not track what its own hardware costs. Any total here would be
  a guess wearing a decimal point, so the manifest publishes the device *set* instead
  (`sources[].device`) and lets a reader price the exact list at current rates.
- **Time** — nothing here instruments the owner's hours. The platform measures sleep,
  training and spend with real sensors; it has no sensor pointed at its own construction.
  What *can* be said is structural, and is derived instead:
  `time.recurring_manual_touchpoints` counts the two places recurring human action is
  actually required — re-authorising credentialed sources when a token dies, and the
  sources whose records only exist because someone typed them.

`config/cost_of_ownership.json` holds only what no code knows: the Cost Explorer actuals
series and the composition ranges (both restated from `docs/COST_TRACKER.md` and **pinned
to it by test** — each published month must appear with that exact figure in the Monthly
Actuals table), plus the two null blocks above. Anything with a code origin is injected by
the generator and must never be typed there.

The actuals series carries complete billed months only. A partial month is not a run-rate,
and a test asserts no published month is still marked MTD in the tracker.

---

## The guard suite

`tests/test_stack_manifest_drift.py`, in the order the guards would catch a real regression:

1. **Regeneration** — the file must equal the generator's output, modulo the date stamp.
   This is the one that fires when the registry gains a source and nobody re-ran the build.
   It names the fix command in its own failure message.
2. **Derivation** — the source id list must equal the public data catalogue's id list; the
   registry facets must be reflected, not restated; unannounced sources must be absent.
3. **Schema** — the manifest validates against the schema it publishes. (A small
   JSON-Schema subset checker lives in the test: a validator dependency for one file would
   cost more rent than it pays, per ADR-103.)
4. **Privacy** — the three layers above.
5. **Cost honesty** — each figure re-derived from its stated origin; nulls asserted to stay
   null and to explain themselves.

The build-failure path is proven rather than asserted: one test feeds `_ingest_pattern` a
source it cannot classify and requires it to raise.

---

## Adding a source, a protocol, or a supplement

Nothing to do here. Add it to its own source of truth
(`lambdas/ingestion/source_registry.py`, `site/config/protocols.json`,
`site/config/supplement_registry.json`), run the generator, commit the regenerated
`stack.json`. If you skip the regeneration, guard 1 fails and tells you so.

The only case that needs a code change is a source whose ingest method matches no existing
pattern — extend `INGEST_PATTERNS` and `_ingest_pattern` in the generator, and the `enum`
in `stack.schema.json`. A test asserts those two vocabularies stay identical.

---

## Related

- ADR-099 — the backlog contract this shipped under (story #1401, epic #1367)
- ADR-103/144 — the complexity posture this file's guard suite is sized against
- ADR-104/105 — honest numbers; uncertainty and *n* on every statistical claim
- ADR-063/133 — the spend ceiling the cost block reports
- `docs/COST_TRACKER.md` — the cost actuals this manifest pins to
- `lambdas/ingestion/source_registry.py` — the source of truth for every source facet
