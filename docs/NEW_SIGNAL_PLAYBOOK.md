# The New-Signal Playbook

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-16 (written from the live BodyScan 2 spike, #2782)
> **Sources of truth:** `lambdas/ingestion/withings_lambda.py` (`MEAS_TYPES`/`SEGMENT_POSITIONS` — the worked example's code half), `lambdas/ingestion/source_registry.py`, `docs/SCHEMA.md`

**When a new metric, device, or source starts emitting — what updates, where, in what order.**

Extracted from the Withings BodyScan 2 spike (#2782, 2026-08-16), the first time a new
device arrived after the platform was mature. The ordered checklist below is the
repeatable pattern; every step names the file that changes and the failure it prevents.
The worked example from #2782 is at the bottom.

Scope: a new *signal* — a new field from an existing source, a new device behind an
existing source, or an entirely new source. For a new source, every step applies; for a
new field, steps 1–8 still apply (the cheap mistake is assuming a "small" new field
skips the sweep).

---

## The ordered checklist

### 1. Capture raw, unfiltered, from the live API — before touching any code

- Pull the widest request the API supports (**unfiltered beats explicit**: in #2782 the
  unfiltered `getmeas` returned meastypes 197/198 that an explicit wide ID list did
  not).
- Capture to a local file, not the pipeline. Diff what arrived against what the
  ingestion code maps today.
- Record: every new field/ID, its **shape** (scalar vs. multi-valued — see step 4),
  its units (verify against a stored record, not memory), and which device/model
  emitted it.
- **Also list the already-mapped fields that have never fired.** A new device can light
  up dormant mappings with zero code change — in #2782, 19 of 21 mapped IDs fired for
  the first time, so the change surface was 31 fields, not 12. "What will start flowing
  on the next scheduled run?" is a capture-time question, not a deploy-time surprise.

### 2. Classify each new field: ingest or park (ADR-103/144 proportionality)

- **Ingest** only what a named consumer will actually read. "Interesting" is not a
  consumer.
- **Park** everything else *visibly*: the ID goes into the source's map file as a
  comment (e.g. `# 196: EDA feet — parked, no consumer (see #2782)`), so the next
  session finds the decision instead of re-deriving it.
- Multi-valued/structured fields (segmental body comp, waveforms) are their own
  follow-on story, never a naive map entry — see step 4.

### 3. Privacy tier BEFORE the first ingestion run

- Classify each new field against `docs/DATA_GOVERNANCE.md` **before** it lands in
  DynamoDB, because dormant mappings can start writing without a deploy (step 1).
- Age-class metrics (vascular age, metabolic age) are Tier-2 owner-only per the
  PhenoAge posture — never on a public surface, never in an AI narrative context.
- Event-class medical results (afib flags, ECG classifications) default owner-only.
- Verify no consumer dumps whole records to a public or AI surface (in #2782 all
  consumers picked fields explicitly — assert this, don't assume it).

### 4. Check the parser's shape contract

- Most flatteners assume **one value per field name**. Segmental/positional data
  (5 values with a `position` attribute) silently collapses to one arbitrary value
  under that contract. If the new field is multi-valued: park it and file a follow-on
  story for its own record shape.
- Check duplicate semantics: computed vs. measured variants of the same metric
  (Withings `attrib` classes) need an explicit keep-rule.

### 5. Source-of-truth ruling for every overlap

- If the new field overlaps an existing source's metric (heart rate → Whoop,
  temperature → Eight Sleep), write an explicit **primary / ancillary** ruling.
  **Never two writers to one truth surface.**
- The ruling lives in `docs/SCHEMA.md` next to the field definition, and in the spike
  issue.

### 6. The mechanical updates, in dependency order

1. Source map (`MEAS_TYPES` or equivalent) + normalizer — ingested fields only.
2. `lambdas/ingestion/source_registry.py` facets — desc/checker_label if the source's
   story changed (raw_layout only if the key scheme changed).
3. `docs/SCHEMA.md` — every new field, its units, its SoT ruling, its privacy tier.
4. Absence semantics (ADR-104): **a new metric defines what its absence means from
   day 1** — staleness threshold, and what a gap reads as (device not used? sync
   lag? true zero?). A field without absence semantics is not done.
5. The #2667 dated-metric contract: any field reaching an AI surface arrives already
   carrying as-of semantics (`as_of` entry in the context layer) — never bare.

### 7. The consumer sweep (the step that gets skipped)

For each **ingested** field, walk the full consumer list and name what changes (most
answers are "nothing yet" — write that down too):

| Consumer | File(s) |
|---|---|
| Source registry facets | `lambdas/ingestion/source_registry.py` |
| Schema reference | `docs/SCHEMA.md` |
| Character engine inputs | `lambdas/compute/` character sheet |
| Coach fact pack | `ai_expert_analyzer` + `lambdas/web/site_api_ai_context.py` |
| Site surfaces | `/data/` pages, cockpit vitals, `/api/vitals` |
| MCP tools | `mcp/tools_health.py` (+ registry wiring test) — **and `mcp/tools_data.py`'s generic row dumpers** (`_get_latest`, `_get_daily_summary`, `tool_get_date_range`, `_find_days_filter`): they return whatever fields a partition holds, so a new Tier-2 field lands in them with NO code change on their side — check whether it needs adding to `TIER2_STRIP_FIELDS` (#2809: the #2782 sweep checked `tools_health.py` and missed `tools_data.py`, so `vascular_age`/`metabolic_age`/`afib_result` reached conversation context through the generic path for 4 days) |
| Daily brief | `lambdas/emails/` |
| OG share cards | OG image lambda |

### 8. QA + verification

- If any *surface* changed: QA manifest / `api_deps`, and the render sweep per
  `docs/SITE_UPLEVEL_PLAYBOOK.md`.
- After the first scheduled ingestion run: read the actual DDB row and confirm the
  field list matches the classification decision — no more, no less.

---

## The worked example (#2782, BodyScan 2, 2026-08-16)

- **Capture:** unfiltered `getmeas` → 23 meastype IDs, 12 unmapped. Device
  self-identified as `BodyScan 2` (modelid 19), correcting the product-name guess.
- **First-fire surface:** 19 dormant mapped IDs lit up — including `vascular_age`
  (155), which forced the privacy-tier step before the next cron run.
- **Decision (owner, interactive): ingest ALL 12** — the park-by-default posture
  was presented with per-metric recommendations and Matthew chose full ingestion
  with the considerations on the record (age-class privacy, afib event
  semantics, the inferred segment mapping, the SpO2 zero guard — all four in
  the #2782 thread and `docs/SCHEMA.md`).
- **Shape contract honored (step 4):** segmental 173/174/175 got position-aware
  parsing (`SEGMENT_POSITIONS`) rather than a naive map entry; unknown positions
  skip loudly. The type-173 five-segment sum equals scalar `fat_free_mass_kg`,
  which is the internal proof that pins the semantics.
- **Absence semantics (step 6.4):** SpO2 zero is stored as ABSENT (the device
  transmits 0 on a failed measurement); afib 0 IS a reading (screening negative).
- **Privacy:** 155 + 227 + 130 Tier-2 owner-only; consumer sweep verified
  field-selective before the first cron fired.
- **SoT:** body-comp = Withings primary (now incl. segmental + water);
  heart_pulse/spo2 ancillary to Whoop; bmr_kcal cross-checks MacroFactor.

---

*Sanctioned by ADR-154 (`docs/DECISIONS.md`).*
