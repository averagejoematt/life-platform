# HANDOVER — The Mind Pillar (Reading): A–E COMPLETE, LIVE + SEEDED — 2026-06-29

> **🎉 THE WHOLE MIND PILLAR IS LIVE, AND IN USE.** All five phases built + deployed + verified on
> production, the discoverability + LLM-permission gaps that real use surfaced are fixed, and the library
> is seeded with Matthew's actual onboarding + first 6 books. `averagejoematt.com/mind/` is populated.
>
> **What's live now:** `/mind/` (home → Mind pillar → `/mind/`), `/now/` reading line, `/api/reading_shelf
> · _overview · constellation`, 9 MCP `manage_reading`/`get_reading_*` tools, 2 lambdas
> (`reading-cover-pipeline`, `reading-recall-sweep`), 2 GSIs. Reading = `CROSS_PHASE` (survives resets).
>
> **Branch `feat/reading-phase-a-data-layer` (~10 commits) is pushed and deployed; it needs Matthew's
> MERGE** to reconcile `main` (I can't self-merge). Everything is already live in prod.
>
> **⚠️ Real-use fixes folded in after the A–E build (each deployed):**
> 1. **MCP role was missing `bedrock:InvokeModel`** — every reading LLM feature (enrichment / onboarding
>    synthesis / recall gist / idea extraction) runs IN the MCP lambda and was silently failing-soft to
>    empty (un-tagged books, blank taste hypothesis). Found live via `AccessDeniedException` on the first
>    onboarding. Added the budget-guarded grant (ADR-062). **Verify any new MCP AI feature has Bedrock.**
> 2. **cover-on-add** — `add_book` now invokes `reading-cover-pipeline` (scoped `lambda:InvokeFunction`).
> 3. **`/mind/` had no normal-flow entry** — pointed the home Mind pillar at it (`story.js`).
>
> **The first live loop, end-to-end (proven):** onboarding interview → low-confidence taste profile
> (sci-fi/fiction/history; "narrative momentum", "second chances") → 6 books added with auto-fetched
> covers + real genre tags (Dark Matter reading; Wager/Born a Crime/PHM/Ocean/Midnight Library queued,
> spanning fiction + non-fiction). The wheel fills as books are FINISHED; the Constellation as ideas are
> kept (`map_ideas` on a debriefed book).
>
> **⚠️ S3 note:** the `generated/` prefix is delete-protected (ADR-046), so test cover JPEGs can't be
> removed via CLI — harmless orphans unless the same bookId is re-added (which re-references them).
>
> **Outstanding (next sessions):** (a) **persona reconciliation** — Lena/Priya/Crowe/Nadia/Theo/Mara are
> archetypes; recast vs `docs/BOARDS.md` BEFORE they surface on the coaching page. (b) The **gated Phase-E
> backlog** (earned on real reading data): journal-resonance embeddings (recommender already takes the
> signal), mind-body bridge (`READING_SESSION#` logs `moodSnapshot`), voice debrief, mnemonic medium, the
> Third-Wall debrief render. (c) The **2 pre-existing pexels** secret-test failures (red on `main` before
> this work; unrelated). (d) Merge the branch.

---

# HANDOVER — The Mind Pillar (Reading): Phases A–E COMPLETE — 2026-06-29

> **🎉 ALL FIVE PHASES BUILT.** A (data layer) · B (recommender + 8 MCP tools) · C (the /mind/ page +
> public endpoints) · D (the recall/debrief/retention loop) — all **deployed live + verified**. E (the
> gated signature) — **built; ships dormant** behind a beautiful honest-empty state (Mara's rule).
>
> **Phase E (the Constellation):** `reading_constellation.py` distils the durable ideas he KEPT from a
> debriefed book (grounded, fail-soft, never invented) → idea nodes + same-book edges; an idea-index
> (`READING#IDEA_INDEX`) makes the graph enumerable. MCP `manage_reading map_ideas` (action #10);
> `get_constellation` enumerates when ready (≥4 nodes). Public `/api/constellation` (honest-empty;
> public projection) + the `/mind/` lit-point seed → code-drawn SVG graph once earned. Test:
> `test_reading_constellation` (7). **Deploy E:** `cdk deploy LifePlatformMcp` + `deploy/deploy_site_api.sh
> /api/constellation` + `deploy/sync_site_to_s3.sh`.
>
> **Gated backlog (per spec, intentionally NOT built — earned on real data):** journal-resonance
> embeddings (the recommender already takes a `journal_resonance` signal), the mind-body bridge
> (reading×sleep/HRV/mood — `READING_SESSION#` already logs `moodSnapshot`; use the existing correlation
> framework), voice debrief, mnemonic medium, and the Third-Wall debrief *render*. Persona reconciliation
> (Lena/Priya/etc. vs `docs/BOARDS.md`) is still owed before coaches surface on the coaching page.

---

# HANDOVER — The Mind Pillar (Reading): Phases A + B + C + D — 2026-06-29

> **Phase D (the loop) — BUILT + tested; deploy = `cdk deploy LifePlatformOperational`.** The two-clock
> retention model: `reading_recall.py` (expanding intervals, autoregulated; fail-soft LLM gist scorer;
> n-gated PRIVATE retentionScore — none until ≥3 probes). MCP `debrief` writes the public takeaway AND
> starts the first spaced probe (the clocks never merge); `answer_recall` scores gist → advances interval
> → updates private retentionScore on READING#/STATE (never public). New `reading-recall-sweep` lambda
> (daily 16:00 UTC, DST-safe) queries the sparse GSI1, writes an owner-private `READING#NUDGE` snapshot,
> emits `LifePlatform/Reading::RecallsDue`. Tests: `test_reading_recall` (7) + `_sweep` (2) + 3 MCP-flow.
> ⚠️ The MCP wiring (debrief/answer_recall) ships on the **next MCP deploy** (`cdk deploy LifePlatformMcp`)
> — Phase D's `cdk deploy LifePlatformOperational` only adds the sweep lambda. **Only Phase E remains**
> (the gated signature: Constellation + journal-resonance + mind-body bridge — build dormant/honest-empty
> per Mara's rule). The Third-Wall debrief *render* (Lena hoped ↔ how it hit) is a frontend follow-up.

---

# HANDOVER — The Mind Pillar (Reading): Phases A + B + C — 2026-06-29

> **Phase C (the /mind/ page + cockpit thread) — BUILT + tested; deploy pending (IAM + site sync).**
> Public site-api `lambdas/web/site_api_reading.py` → `/api/reading_shelf` + `/api/reading_overview`,
> both routed through `reading_visibility.project_public` (the public/private chokepoint's first LIVE
> surface — a test proves private fields never appear). New `/mind/` page (`site/mind/index.html` +
> `mind.js` + `mind.css`): warm spines, roundedness wheel, habit line, honest empty states, **no red**.
> Reading icon added (`icons.svg`/`icons.js`). Cockpit `/now/` gains a `data-reading` tile +
> `renderReading()` (current book · read-today · streak; recall stays owner-private). Registered in
> `visual_qa.py` PAGES + `site_review_bindings.py`. **⚠️ Deploy needs `cdk deploy LifePlatformOperational`**
> (the site-api role gains DynamoDB `/index/*` for the reading GSIs — an IAM change the site-api script
> can't do; the CDK asset also bundles `web/` + `reading/`) **then `deploy/sync_site_to_s3.sh`** for the
> page. The home Mind pillar already exists with the right edges (left untouched). Next: Phase D (the
> loop — recall EventBridge sweep + debrief + retention) and the gated Phase E (Constellation + resonance
> + mind-body). Test: `test_site_api_reading` (5). Suite green except the 2 pre-existing pexels failures.

---

# HANDOVER — The Mind Pillar (Reading): Phases A + B — 2026-06-29

> **Phase B (engine + MCP) — SHIPPED + DEPLOYED LIVE + verified.** The rules-based recommender
> (`reading_recommender.py`, spec §4 — decomposed reason strings, confidence n-gate → propose-and-
> dispose, anti-Goggins penalty, phase-shifting weights), the taste-archaeology onboarding
> (`reading_onboarding.py`, calibration §8), and **8 MCP tools** (`mcp/tools_reading.py`: 7 reads +
> `manage_reading` draft→dry_run→commit write fat-tool). Tool count 136→144 (`EXPECTED_MAX_TOOLS`
> 141→150). **No layer dance** — `mcp_stack.py` stages `lambdas/reading/` into the MCP bundle (the
> shared layer already provides `numeric`/`retry_utils` that reading needs), so only `LifePlatformMcp`
> redeployed; no fleet redeploy, no IAM change. **Deployed + verified live:** `cdk deploy
> LifePlatformMcp` clean (code-asset re-hash only); a direct MCP invoke of `get_reading_shelf`
> returned `200` with an empty shelf — proving the runtime `from reading import …` resolves AND a
> real GSI2 query ran against the now-ACTIVE index. Tests: `test_reading_recommender` (10) +
> `test_reading_onboarding` (6) + `test_tools_reading` (14). Deploy script: `deploy/deploy_reading_mcp.sh`.
> **Phase A GSIs are both ACTIVE in prod; the cover lambda is live.** Next: Phase C (the `/mind/` page +
> cockpit thread). Reconcile the panel personas vs `docs/BOARDS.md` before coaches surface (Phase C/D).

---

# HANDOVER — The Mind Pillar (Reading): Phase A data layer — 2026-06-29

Phase A of the reading/Mind pillar — **the data layer only** (no UI, no MCP tools; those are Phases
B–E). **Built + fully tested; deploy scripts staged for you to run** (per the canon norm, Claude does
not execute deploys). Canon read in full first: `docs/briefs/BRIEF_2026-06-29_reading_mind.md`,
`docs/coaching/READING_CALIBRATION.md`, `docs/SPEC_READING_MIND_2026-06-29.md`,
`docs/specs/CLAUDE_CODE_PROMPT_READING_MIND_v1.md`.

Branch: `feat/reading-phase-a-data-layer` (off `origin/main` = `50dbc196`, the live tip + your merged
#283). The four canon docs were authored by a claude.ai session on a *divergent* local `main`
(`15b00769`, never pushed); this branch carries them forward onto the live tip so the build lands on
current state, not stale main.

---

## 1. What's built

**Data layer — `lambdas/reading/`** (bundled with the `lambdas/` asset, NOT the shared layer → no
layer dance):
- `reading_keys.py` — pure key/id/GSI discipline. `book_id()` = stable 16-char hash of ISBN-13/OLID,
  else slug(title+author). Key constructors + GSI stamping (incl. the sparse GSI1 drop-out).
- `reading_store.py` — DynamoDB access for every entity (spec §1) + the **seven access patterns**
  (spec §2): current/queue + history (GSI2), notes + track-record (begins_with), due-recalls (sparse
  GSI1), roundedness wheel (finished × `BOOK#.domainTags`), Constellation node/edges. Reads are JSON-
  safe; writes cast Decimal. CROSS_PHASE → no phase filter, no phase stamp. State machine:
  `add_book` (enrich → `BOOK#` → `READING#/STATE`), `update_reading_status` (abandon REQUIRES a reason).
- `reading_visibility.py` — **the public/private chokepoint** (spec §10). An allowlist projection:
  the only sanctioned way to make a stored reading record public. Fail-closed — pk/sk, GSI attrs, and
  every private field (`retentionScore`, `lastProbeAt`, all `RECALL#`, session `moodSnapshot`/
  `location`, recommendation `inputsSnapshot`, profile calibration internals) are dropped. Notes
  project only when `public:true`; `RECALL#` is private in its entirety.
- `reading_enrich.py` — LLM book tagging (Haiku via the `retry_utils → bedrock_client` chokepoint;
  ADR-062). Tags `domainTags`/`themes`/`era` + difficulty subscores (length derived from pageCount;
  density/prose/structure clamped 1–5; composite). **Fail-soft** — any failure adds the book un-tagged.
- `cover_pipeline_lambda.py` + `cover_placeholder.py` — the **`reading-cover-pipeline`** Lambda:
  Open Library → Google Books → **designed placeholder** (Pillow, ink/ember house palette). ALWAYS
  downloads + caches to `generated/covers/<bookId>.jpg` (ADR-046 prefix; public URL `/covers/…` after
  the edge strips `generated/`) — **never hot-links** (spec §8). Real User-Agent on every fetch (the
  editorial_image Cloudflare lesson). Fail-soft + per-book isolation + a top-level handler guard.

**Two GSIs — the first ever on `life-platform`** (`ADR-097`, amends ADR-005):
- **GSI1** (sparse recall-due): `GSI1PK="RECALL_DUE"`, `GSI1SK=<nextDue>`. Only active prompts project
  → the daily sweep is `GSI1SK <= now`, never a scan. Answering removes the attrs (drops from index).
- **GSI2** (state/time): `GSI2PK="READING_STATUS#<status>" | "READING_SESSION"`, `GSI2SK=<iso>`.
- **Mechanism — CLI, not CDK.** The table is not CDK-managed (`core_stack.py` `from_table_name`
  lookup), so GSIs are added with `aws dynamodb update-table` (`deploy/deploy_reading_gsis.sh`),
  additive online backfill, one per UpdateTable. IAM already grants `…/index/*` (no role change).

**Taxonomy:** all reading pks (`BOOK#`, `READING#…`) → `CROSS_PHASE` in `phase_taxonomy.py` (durable
identity data, never wiped/phase-filtered; a coverage test asserts the new families classify).

**CDK:** one on-demand Lambda added to `LifePlatformOperational` (`ReadingCoverPipeline`, Pillow layer,
dedicated least-privilege role `operational_reading_cover_pipeline` — DDB read/update + S3 PutObject on
`generated/covers/*`, no Bedrock). `cdk synth LifePlatformOperational` is clean.

## 2. Tests (creds-blanked, `tests/reading_fakes.py` = an in-memory DDB query engine that really
evaluates the boto3 Key conditions, incl. sparse GSI semantics — no moto)

- `test_reading_keys.py` — bookId determinism + key/GSI stamping (incl. sparse drop-out).
- `test_reading_visibility.py` — **PROVES private fields are unreachable**: populates every private
  field + an injected secret, asserts none survive the projection (the §10 acceptance bar).
- `test_reading_store.py` — every spec §2 access pattern + the state machine (abandon-requires-reason).
- `test_reading_enrich.py` — parse (incl. fenced JSON), clamping, fail-soft.
- `test_cover_pipeline.py` — OL hit → Google fallback → placeholder; downloaded-not-hot-linked; cache
  key + coverS3Key update; batch isolation.
- `test_phase_taxonomy.py` — reading families added to the live-coverage fixture + a decision check.

**Full suite: green except 2 PRE-EXISTING failures unrelated to Phase A** — `test_s1`/`test_sr1`
(`life-platform/pexels` is referenced in `editorial_image.py` + IAM since SS-11 but was never added to
the tests' `KNOWN_SECRETS`). They fail identically on `origin/main`; left untouched to keep this PR
strictly Phase A (fixing them would mean editing the platform's secret-count invariant — out of scope).
`black` + `ruff` clean on all new/edited files.

## 3. Deploy scripts (YOU run these — Claude does not execute deploys)

Run in order. `deploy/deploy_reading_data.sh` orchestrates both and `cdk diff`s before applying:
```
bash deploy/deploy_reading_data.sh
```
…which does: (1) `deploy/deploy_reading_gsis.sh` — add GSI1 then GSI2 (additive, online backfill, waits
ACTIVE; idempotent); (2) `cdk diff LifePlatformOperational` (REVIEW — expect only the new
ReadingCoverPipeline Lambda + its role/policy/alarm/log-group and a benign shared-asset re-hash; NO
destroys, NO existing-IAM changes, NO table changes); (3) on your `y`, `cdk deploy
LifePlatformOperational`. Optional smoke invoke is printed at the end (writes one real cover).

No layer rebuild. No other stack changes. Re-running is safe (GSIs idempotent; CDK declarative).

## 4. ⚠️ Notes / honest watch-items

- **Spec §2.7 Constellation** — `PK begins_with READING#IDEA#` is not a valid DynamoDB query (you can't
  begins_with a partition key). The Constellation is Phase E (gated); Phase A stores/reads idea
  nodes+edges by exact key. Whole-graph enumeration is deferred to E (needs a small idea-index or a GSI).
- **Cover S3 prefix** — spec §8 says `covers/`; platform law (ADR-046) requires `generated/`. Honored
  both: key `generated/covers/<id>.jpg`, public path `/covers/<id>.jpg`.
- **2 pre-existing pexels secret-test failures** (§2) — a real SS-11 doc-drift gap, not introduced here;
  worth a 3-line fix in a *separate* housekeeping PR (add `life-platform/pexels` to both `KNOWN_SECRETS`
  + bump `test_s4` EXPECTED_COUNT 20→21).
- **Phases B–E remain** (`docs/specs/CLAUDE_CODE_PROMPT_READING_MIND_v1.md`): B = MCP tools +
  rules-based recommender + onboarding interview; C = `/mind/` page + cockpit thread; D = the
  debrief→recall loop (EventBridge sparse-GSI1 sweep); E = Constellation + journal-resonance + mind-body
  bridge. **Reconcile the panel personas (Lena/Priya/Crowe/Nadia/Theo/Mara) against `docs/BOARDS.md`
  before they surface on the coaching page** (flagged in the brief + calibration).

## 5. Docs updated (the session ritual)

ADR-097 (DECISIONS.md, amends ADR-005) · SCHEMA.md (Reading partition + pk table) · DATA_GOVERNANCE.md
(Tier 2 + PII + retention) · ARCHITECTURE.md (Reading subsection) · CHANGELOG.md (top entry) ·
phase_taxonomy registration · `sync_doc_metadata.py --apply` (Lambdas 83→84, auto). Counts: 84 Lambdas,
136 tools, 52 alarms, 9 secrets, 8 stacks.
