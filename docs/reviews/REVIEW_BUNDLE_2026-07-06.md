# Life Platform — Pre-Compiled Review Bundle
**Generated:** 2026-07-06
**Purpose:** Single-file input for architecture reviews. Contains all platform state needed for a Technical Board assessment.
**Usage:** Start a new session and say: "Read this review bundle file, then conduct Architecture Review #N using the Technical Board of Directors."

---

## 1. PLATFORM STATE SNAPSHOT

### Latest Handover

# HANDOVER — R21 Batch 1+2: 8 issues shipped, merged & deployed — 2026-07-06

> Instruction: "read memory and handover, put a plan to resolve efficiently as many
> issues as possible" → picked **Batch 1 (Now milestone) + Batch 2 (R21 perimeter
> quick-wins)** = 8 issues. Model decision: stayed on **Opus** as the driver +
> fanned the mechanical `model:sonnet` items to Sonnet worktree subagents. User then
> authorized "all merges and deploys, do everything, then memory + handover."
> **All 8 issues: code merged to `main` + deployed + live-verified. main green except
> ONE pre-existing drift red (freshness-checker, NOT this session — see below).**

## What shipped (8 issues, 5 PRs, all closed)

| # | Issue | PR | Deploy | Status |
|---|-------|----|--------|--------|
| #757 | ADR-128: no standing LLM Council | #774 | none (doc) | ✅ |
| #754 | ADR-129: remediation `auto`→`shadow` | #774 | SSM flip (live) | ✅ |
| #752 | ADR-130: GitHub Pages disabled | #774 | `gh api DELETE pages` (live) | ✅ |
| #756 | delete parked hevy-webhook FunctionURL | #775 | `cdk LifePlatformIngestion` | ✅ gone |
| #758 | gate PERMA/Seligman citations on n | #776 | `cdk LifePlatformMcp` | ✅ boots 401 |
| #727 | scientific-liveness heartbeat (grading stall) | #777 | `cdk Compute+Monitoring` | ✅ emits 999 |
| #729 | scorecard honest empty state | #778 | `sync_site_to_s3.sh` | ✅ live |
| #730 | static-render proof surfaces | #778 | `sync_site_to_s3.sh` | ✅ live |

**Live-verified in prod:**
- **#729/#730** — `curl https://averagejoematt.com/coaching/scorecard/ | grep` finds
  `Evaluator live since 2026-06-14 · 309 predictions pending · 0 graded yet · as of {date}`;
  `curl …/story/chronicle/ | grep` finds the dated 4-post list. version.json = `db889804`.
  Mechanism: `scripts/v4_proof.py` bakes `<noscript>` proof blocks at build time
  (live API + `scripts/proof_snapshot.json` fallback, never fabricates) — JS still
  renders the rich view. ADR-104 behavioral-absence + honest "as of" stamps.
- **#727** — invoked `coach-prediction-evaluator` → `liveness:{decided_count:0,
  gradable_count:127, days_since_last_decided:999}`. New `grading-stalled` alarm
  (DaysSinceLastDecided ≥ 14, 2 daily periods, BREACHING) is live and will fire on
  the current all-pending state (the point). alarm_count 109→110.
- **#758** — MCP redeployed via CDK (correct `reading/` staging, boots 401 healthy).
- **#756** — `hevy-webhook` Lambda ResourceNotFound (removed); ingestion lambdas boot
  clean on the reconciled **v118** layer (bonus: cleared the ingestion v115 drift).
- **#754/#752** — SSM `remediation-mode=shadow` verified; Pages returns 404.

## ⚠️ Pre-existing red on main (NOT this session) — decision for Matthew

Both post-merge CI/CD runs (#727, #729/#730) fail **only** on
`Post-deploy integration checks (I1/I2/I5)` → `test_i2_lambda_layer_version_current`:
**`life-platform-freshness-checker` is on layer v116 (current v118)**. This is
**pre-existing drift** (agent-756 flagged it independently; present before this
session) and does **not** trigger rollback (I2 is non-gating; auto-rollback skipped).
Every other job — Lint, Unit, Deploy-critical, **Deploy**, **Visual-QA**, **Smoke** —
passed on both runs.

`freshness-checker` lives in **`LifePlatformOperational`**, which the prior session
**deliberately held** at v115/v116 ("deploy held Operational→v118 on HAE reconcile —
lands `coherence_semantic` tier-1"). `cdk diff LifePlatformOperational` = layer
v115/116→v118 + the held `coherence_semantic` code bundle. **I did NOT deploy it**:
it's outside this session's authorized 8-issue scope AND overriding another session's
deliberate hold unilaterally isn't my call. **To green main:** `cd cdk && npx cdk
deploy LifePlatformOperational --require-approval never` — it's a low-risk layer
reconcile + an advisory-feature budget-gate, but confirm the hold rationale first.

## Notes / gotchas confirmed

- **CI DOES auto-deploy on merge** (the "Deploy" job succeeded on both runs) — my
  manual `cdk deploy`s were belt-and-suspenders/idempotent, not the only path.
- **doc-sync literal drift across concurrent PRs** is real: `test_count`/`alarms`/
  `lambda_count` in `site_api_common.py` conflict when two PRs branch off different
  mains. Fix: before merging each PR, `git merge origin/main` into its branch, resolve
  the literal conflicts by `git checkout --theirs` + re-run `sync_doc_metadata --apply`
  (authoritative from the merged tree), then merge. Did this for #727.
- **GitHub squash-merge rejects a branch with a merge commit** as CONFLICTING even
  when main is a full ancestor — linearize with `git reset --soft <main>` + one commit.
- **MCP deploy = `cdk deploy LifePlatformMcp`**, NOT `deploy_mcp_split.sh` (which omits
  the top-level `reading/` staging and re-breaks boot — deploy.md §MCP is authoritative).

## Untouched (remaining backlog, each its own session)
- **Next milestone:** #735 /verify/ page, #736 build-beat wrap-gate, #739 surge ceiling,
  #741 career artifact, #769 evening ritual, #740 essay, #734 audio, #409 batch-inference.
- **Later:** #395 MCP prune, #421/#422/#475 data depth, #552/#592/#594, #743/#744
  (honesty-layer receipts/retention), #746/#747/#748, #749/#750/#751/#753/#755 (infra/sec).
- Optional #380 build-beat dispatch for this batch (outward-facing content — not done).


---

## 2. RECENT CHANGELOG

## Site deploy — content-hash the full JS module graph (the "frozen page" fix) — 2026-07-03

One bug, **deployed live**. Many v5 pages loaded frozen — the static shell (header/title/footer) rendered but the JS-populated content stayed blank; a hard reload fixed it, and it reproduced after a browser restart. **Root cause:** `sync_site_to_s3.sh` content-hashed CSS/JS and served the hashed files immutable/1yr (ADR-039) but rewrote references **only in `*.html`** — the ES-module `import ... from "/assets/js/charts.js"` statements *inside* the modules kept pointing at the unhashed, mutable, 24h-cached URL. A deploy that changed an entry module **and** a dependency together (as #260 did) let a returning browser pair a fresh hashed entry module with a stale cached dependency; the ES module graph throws atomically on a mismatched import, so nothing executed and only the shell rendered. **Fix (ADR-098):** new `deploy/hash_site_assets.py` hashes the **whole module graph in dependency order (leaves first)** and rewrites every reference — HTML `<link>`/`<script>`, intra-module `import`s, and CSS — so every asset URL is content-hashed and immutable and version skew is structurally impossible. `/legacy` stays unhashed. **Verified:** 0 dangling refs, 0 unhashed HTML refs, headless render executes; live — `/data/` + `/coaching/` serve a fully-hashed, self-consistent, immutable module graph (shared `sigils` hash identical across pages), `version.json` == `sw.js` VERSION. Stuck visitors self-heal within ~5 min. See INCIDENT_LOG 2026-07-03 (P3), ADR-098. (PR #332.)

## The Mind Pillar (Reading) — cover-route fix + persona reconciliation (Dr. Cora Vance) — 2026-06-30

Two post-go-live items; both **deployed live**.
- **⚠️ Broken book covers (real bug, fixed)** — the `reading-cover-pipeline` writes real JPEGs to `generated/covers/<bookId>.jpg` and the `/mind/` front-end requests `/covers/<bookId>.jpg`, but **no CloudFront behavior routed `/covers/*` to `S3GeneratedOrigin`** — every cover fell through to the site origin and 404'd (broken-image icons). Added the missing `/covers/*` behavior (`web_stack.py`, 30-day TTL, mirrors the editorial-image route); `cdk deploy LifePlatformWeb` + invalidate. All 6 covers now serve `200 image/jpeg`, visually confirmed.
- **Persona reconciliation** — the reading coach is now **Dr. Cora Vance** (`cora_vance`), recast from the placeholder "Lena Marsh" archetype. She's a **defined, non-operational** persona (`config/personas.json` + `board_of_directors.json`, `type: board`, `active: false`, features-gated to nothing — generates no email/chronicle content, like Elena Voss / Eli Marsh sit inert) pending the reading-coaching surface. Counter-voices recast to the **real roster**: Coach Maya Rodriguez (on-ramp), Dr. Amara Patel (longevity-vs-pleasure), Mara Chen (restraint gate); the orphan "Priya/Nadia/Crowe/Theo" archetypes dropped (Priya's pleasure-stance folded into Cora's own mandate). Renamed in the reading code/page too — the onboarding LLM **system prompt** ("You are Dr. Cora Vance"), the `/mind/` empty-state string, the MCP tool description, and the track-record docstrings. The separate, pre-existing **Product-Board** Lena/Priya personas are unrelated and untouched. Docs: `READING_CALIBRATION.md` §9 (placeholder NOTE deleted), `BOARDS.md`, `SPEC_READING_MIND`; dated build briefs keep the original names with a reconciliation pointer. Tests: 51 reading + persona-registry green.

## The Mind Pillar (Reading) — go-live: discoverability, cover-on-add, Bedrock grant, first seed — 2026-06-29

Post-Phase-E follow-ups surfaced by real use; all **deployed live**.
- **cover-on-add** — `manage_reading add_book` now fire-and-forget invokes `reading-cover-pipeline` (scoped `lambda:InvokeFunction` on the MCP role); a new book gets a cover automatically. Fail-soft.
- **discoverability** — the home seven-pillar constellation's **Mind node now leads to `/mind/`** (was the old `/data/mind/`); the page had no normal-flow entry before. Mood/journal stays reachable via `/data/` + the `/mind/` foot.
- **⚠️ Bedrock grant (real gap)** — the reading LLM features (enrichment, onboarding taste synthesis, recall gist scoring, idea extraction) run **in the MCP lambda** but the MCP role lacked `bedrock:InvokeModel` — so they all silently **fail-soft to empty** (un-tagged books, no taste hypothesis). Found via live onboarding (`AccessDeniedException`). Added the standard budget-guarded grant (ADR-062); enrichment + synthesis now work (books come back genre-tagged).
- **First real seed** — Matthew's onboarding interview synthesized to a low-confidence taste profile; library seeded with Dark Matter (reading) + 5 queued spanning sci-fi/history/biography/memoir/fantasy/philosophy. `/mind/` is now populated.

## The Mind Pillar (Reading) — Phase E the signature (the Constellation) — 2026-06-29

Phase E: the gated signature. **Built + tested.** Per Mara's restraint rule it ships **dormant behind a beautiful honest-empty state** — a single lit point, "the constellation begins with the first idea you keep" — and fills only on real kept ideas (never fabricated).

- **The Constellation** (`lambdas/reading/reading_constellation.py`): a fail-soft LLM distills the DURABLE ideas he KEPT from a finished book's own takeaway/notes — **grounded only in his words, never invented** — into idea nodes + same-book edges. An idea-index (`READING#IDEA_INDEX`) makes the graph enumerable (DynamoDB can't `begins_with` a pk). The graph refuses to render below 4 nodes (brief §2: never a sparse sad graph). Ember = recent, muted ink = settled, never red.
- **MCP** `manage_reading map_ideas` (10th action): distil + persist ideas/edges from a debriefed book. `get_constellation` now enumerates the real graph when ready.
- **Public** `/api/constellation` (honest single-point empty state; public projection only) + the `/mind/` Constellation section: the lit-point seed empty state (reduced-motion respected) → a quiet code-drawn SVG graph once earned.
- **Gated backlog (per the spec, NOT built — earned on real data):** journal-resonance embeddings (the recommender already accepts the `journal_resonance` signal), the mind-body bridge (reading×sleep/HRV/mood via the existing correlation framework — `READING_SESSION#` already logs `moodSnapshot`), voice debrief, and the mnemonic medium. The Third-Wall debrief *render* (Lena hoped ↔ how it hit) is a frontend follow-up.
- **Tests:** `test_reading_constellation` (7). Full suite green except the 2 pre-existing pexels failures. Deploy: `cdk deploy LifePlatformMcp` + `deploy/deploy_site_api.sh /api/constellation` + `deploy/sync_site_to_s3.sh`.

## The Mind Pillar (Reading) — Phase D the loop (recall + debrief + retention) — 2026-06-29

Phase D: the two-clock loop. **Built + tested.** The debrief (immediate reaction → public takeaway) and the probes (spaced retention) are kept architecturally separate.

- **Spaced-retrieval core** (`lambdas/reading/reading_recall.py`, spec §7): expanding intervals `[3,7,16,35,90,180]` days, autoregulated (a strong gist ratchets the interval up, a weak one down — never to zero); a fail-soft LLM **gist scorer** (rewards reconstruct-the-argument / changed-prior, never verbatim); and the **n-gated PRIVATE `retentionScore`** (recency-weighted, no score until ≥3 scored probes — Henning's refuse-to-render).
- **The debrief starts the retention clock** (MCP `manage_reading debrief`): writes the public takeaway AND creates the first spaced probe (due in 3 days) — the two clocks never merged. `answer_recall` now scores the gist, advances the interval, and updates the private retentionScore on the READING#/STATE row (never public).
- **EventBridge sweep** (`reading-recall-sweep`, daily 16:00 UTC, DST-safe): queries the sparse GSI1 for due probes, writes an **owner-private** nudge snapshot (`READING#NUDGE`, never served publicly), emits `LifePlatform/Reading::RecallsDue`.
- **Tests:** `test_reading_recall` (7) + `test_reading_recall_sweep` (2) + 3 MCP-flow tests. Full suite green except the 2 pre-existing pexels failures. Deploy: `cdk deploy LifePlatformOperational` (the sweep lambda + rule + IAM).

## The Mind Pillar (Reading) — Phase C the /mind/ page + cockpit thread — 2026-06-29

Phase C: the public reading surface. **Built + tested.** A new `/mind/` page, public site-api endpoints (the first live surface for the `reading_visibility` chokepoint), a reading icon, and a cockpit reading line.

- **Public site-api** (`lambdas/web/site_api_reading.py`): `/api/reading_shelf` (currently-reading · queue · finished · the dignified "set down" shelf) + `/api/reading_overview` (roundedness wheel · input-streak · cockpit line). **Every record passes through `reading_visibility.project_public`** — retention/recall/mood/calibration internals are unreachable on the public surface BY CONSTRUCTION (a test populates private fields + asserts they never appear). Read-only.
- **The `/mind/` page** (`site/mind/index.html` + `site/assets/js/mind.js` + `site/assets/css/mind.css`): warm spines (cover if cached, else a designed text spine), the roundedness wheel, the habit line — **honest empty states everywhere** (day one is an invitation, not a failure). **No red on this surface** (a stalled/set-down book is muted ink). A reading icon added to `icons.svg`/`icons.js`.
- **Cockpit thread** (`/now/`): a `data-reading` tile + `renderReading()` — current book, read-today tick, input streak. Recall prompts/retention stay **owner-private** (MCP only) — never fetched on the public cockpit.
- **IAM:** the site-api role's DynamoDB read grant gains `/index/*` (the reading GSIs); deploy_site_api.sh + the CDK asset stage `lambdas/reading/`. Registered in visual_qa + the site-review bindings map.
- **Tests:** `test_site_api_reading` (5, incl. the privacy proof). Full suite green except the 2 pre-existing pexels failures. Deploy: `cdk deploy LifePlatformOperational` (IAM + code) → `deploy/sync_site_to_s3.sh`.

## The Mind Pillar (Reading) — Phase B engine + MCP tools — 2026-06-29

Phase B: the recommender + onboarding + the MCP tool surface, over the Phase A data layer. **Built + tested; MCP deploy run (no layer dance).** 8 new MCP tools (count 136→144).

- **Rules-based recommender v1** (`lambdas/reading/reading_recommender.py`, spec §4): the transparent objective function (capacity / difficulty-ratchet / breadth / momentum / journal-resonance / phase, minus whiplash / repeat / anti-Goggins penalties), weights shifting by curriculum phase. Every pick **decomposes to a reason string**; confidence is `f(n_finished,n_abandoned)` and below the n-gate it's **propose-and-dispose** (one pick). Never invents data.
- **Onboarding interview** (`reading_onboarding.py`, calibration §8): the taste-archaeology question bank + a fail-soft LLM synthesis → a low-confidence `tasteHypothesis`, **deliberately refusing to infer taste from the fitness goal** (anti-Goggins).
- **8 MCP tools** (`mcp/tools_reading.py`, spec §9): 7 reads (`get_reading_shelf` / `_recommendation` / `_profile` / `_history` / `get_due_recalls` / `get_reading_track_record` / `get_constellation`) + `manage_reading` — a **draft→dry_run→commit** write fat-tool (add_book / update_status / log_session / add_note / answer_recall / debrief / log_outcome / update_profile / onboard); previews by default, writes only on explicit `dry_run=false`. Honest empty states (constellation, recommendation, track record).
- **No layer dance** — the MCP bundle stages `lambdas/reading/` as a package (`mcp_stack.py`), so the reading code keeps its single source of truth and only the MCP stack redeploys (no fleet redeploy). No IAM change (the MCP role already has table + index/* CRUD).
- **Tests:** `test_reading_recommender` (10) + `test_reading_onboarding` (6) + `test_tools_reading` (14); `test_mcp_registry` ceiling bumped 141→150. Full suite green except the 2 pre-existing pexels failures. Deploy: `deploy/deploy_reading_mcp.sh`.

## The Mind Pillar (Reading) — Phase A data layer — 2026-06-29

The first phase of the reading/Mind pillar (`docs/SPEC_READING_MIND_2026-06-29.md`): the data layer only — no UI, no MCP tools (those are Phases B–E). **Built + tested; deploy scripts staged for the operator to run.** New SOT domain `reading` on the shared `life-platform` table.

- **Entities + access patterns** (`lambdas/reading/reading_store.py` + `reading_keys.py`): every reading entity per spec §1 (`BOOK#`, `READING#/STATE|SESSION|NOTE|RECALL`, `READING#REC`, `READING#PROFILE`, `READING#IDEA#`) with the seven access patterns from spec §2 (current/queue, history-by-date, notes, due-recalls, roundedness wheel, track record, Constellation node). Reading is `CROSS_PHASE` in `phase_taxonomy.py` (durable identity data — survives experiment resets; a coverage test asserts the new families classify).
- **Two GSIs — the first on `life-platform`** (`ADR-097`, amends ADR-005): **GSI1** sparse recall-due (only active prompts project → the daily sweep never scans), **GSI2** reading state/time (current-reading, queue, history). Added via `aws dynamodb update-table` (the table is not CDK-managed), additive/online-backfill.
- **Public/private chokepoint** (`reading_visibility.py`): an allowlist projection — the only sanctioned way to make a stored reading record public. Fail-closed (pk/sk, GSI attrs, and every private field — `retentionScore`, all `RECALL#`, session mood/location, recommendation `inputsSnapshot`, calibration internals — are dropped). A test populates every private field + an injected secret and proves none survive (spec §10 enforced server-side, not in the UI).
- **Cover pipeline** (`reading-cover-pipeline` Lambda): Open Library → Google Books → **designed placeholder** (Pillow, house palette). Always downloads + caches to `generated/covers/<bookId>.jpg` (ADR-046 prefix) — never hot-links. Fail-soft (a book always gets a cover).
- **LLM enrichment on add** (`reading_enrich.py`): Haiku tags `domainTags`/`themes`/`era`/difficulty subscores via the Bedrock chokepoint; fail-soft (a tagging failure still adds the book un-tagged).
- **Tests:** `test_reading_keys` / `test_reading_visibility` / `test_reading_store` / `test_reading_enrich` / `test_cover_pipeline` + reading families in `test_phase_taxonomy` (all green; full suite green except 2 pre-existing pexels secret-list failures unrelated to this change). **Deploy scripts** `deploy/deploy_reading_gsis.sh` + `deploy/deploy_reading_data.sh` (cdk diff first; operator runs). See `handovers/HANDOVER_LATEST.md`.

## The SS self-sustainability tail (SS-08/09/11) — 2026-06-30

The last documented backlog after the backend serial arc — counterweights to "fully automatic" content + a flat-day-still-shows-motion view. **Shipped + deployed live + verified.** 3 items, 2 PRs: SS-09 + SS-11 → #280; SS-08 → #281 — all merged + deployed.

- **SS-11 — editorial-image guardrail** (`editorial_image.py`): a fail-closed quality/denylist gate before an auto-picked Pexels cover ships. `_acceptable(photo)` requires a usable landscape AND an atmospheric description (rejects people/face/text/brand via a word-boundary denylist); `_search` ships the first candidate that clears the gate, or NO image if none qualify. Bundled (not the layer) → no layer dance.
- **SS-09 — podcast format rotation** (`coach_panel_podcast_lambda.py`): a deterministic per-week entry-point lens (`_episode_angle(week)`, 6 angles) injected into the writer prompt so the show doesn't feel formulaic by ep 26 — the bet/Split/scoreboard identity stays, only the lens rotates.
- **SS-08 — monthly "what changed"** (`weekly_correlation_compute_lambda.py` + `site_api_data.py` + `cockpit.js`): the `/now` "Month" scope button was a placeholder; SS-08 fills it so a flat day still shows monthly motion. Fill-in-the-blank — piggybacks the series + FDR correlations already computed weekly (zero new DDB queries, no new lambda, no layer dance). `compute_month_deltas` (trailing-30d vs prior-30d, n≥10 real days each half, never zero-filled) + `diff_newly_unlocked` (a first-seen ledger so a correlation is announced once, never re-announced) + `honest_null` → a calm "steady month" state (never fake motion). New `/api/what_changed`, `renderMonth()`, `what_changed` = EXPERIMENT_SCOPED.
- **Low-fabrication across all three** — only real FDR verdicts + real deltas + fail-closed image gating. Tests: `tests/test_ss_tail.py` (11) + `tests/test_what_changed.py` (11); all related green.

✅ **The full backlog is cleared:** backend serial arc (phases 1–4) + SS tail (SS-08/09/11). Only genuinely-deferred items remain (SS-10 coach-grounding "its own session", PRE-13). See `handovers/HANDOVER_LATEST.md`.

## Historical-window APIs — backend serial phase 4 (arc complete) — 2026-06-29

The **last** backend serial phase — the backend serial arc is now COMPLETE (all four phases live). Shipped + deployed live + verified (Matthew merged #278 and authorized the deploys). **1 feature PR: #278.** main == live, 0 open PRs.

- **The device:** let a reader arriving months in see the platform **AS OF a past date**, extending the `?date=` time-travel pattern `handle_character` already used to the data/waveform surfaces.
- **Two endpoints get `?date=`** (both already `DATE#`-keyed → zero new compute): `/api/observatory_week?domain=X&date=Y` (the 6-domain waveform) and `/api/vitals?date=Y` (the cockpit, with a new `site_api_common._latest_item_asof` for the latest weigh-in on-or-before the anchor).
- **As-of semantics mirror `handle_character` exactly:** most-recent-on-or-before, future clamps to today, pre-genesis honest-null 200 (never 503), `include_pilot=bool(date)` so prior-cycle history shows only when time-travelling, `time_travel` flag, immutable-past day cache. Read-only — stored records served verbatim, never interpolated.
- **Front-end (`cockpit.js`):** the date-scrubber time-travel mode no longer **hides** the vitals band (it did because no historical vitals endpoint existed) — it shows the **real readings from that date** via `/api/vitals?date=`, plus a chronicle cross-link. (The `evidence.js` silhouette scrubber is *weight*-keyed, not date-keyed, so it's correctly not wired.)
- **Deploy (site-api only, no layer dance, no CDK):** `deploy_site_api.sh` + `sync_site_to_s3.sh`. **Verified live:** historical-vs-current divergence proves real past records (weight 305 on 06-20 vs 301 now; recovery 60 vs 84); future clamps; pre-genesis 200. New tests: +10 in `tests/test_historical_window.py` (270 site-api tests green).

🎉 **The serial vision is complete:** phase 1 (coach stances) + phase 2 (coaches react to protocols) + phase 3 (Elena recaps) + phase 4 (historical windows). ⚠️ **Outstanding:** only the SS tail (SS-08/09/11). See `handovers/HANDOVER_LATEST.md`.

## Elena "previously on" recaps — backend serial phase 3 — 2026-06-29

The third backend serial phase, shipped + deployed live + verified end-to-end (Matthew merged #275 + #276 and authorized "you run the deploys"). **1 feature PR: #276 (merged + deployed).** main == live, 0 open PRs.

- **The device:** a serial-TV cold-open so a reader arriving months in catches up fast. **Elena Voss** (the embedded narrator who writes the weekly Chronicle — not the PI; that's Dr. Eli Marsh) produces a "previously on" recap grounded ONLY in **published** chronicle installments + the narrative arc — never raw vitals, never invented events.
- **Low-fabrication by construction:** generate-at-draft, commit-at-publish — the recap is written to `RECAP#latest` only when a week actually publishes, so it can never run ahead of the history it summarizes. **5 guards** in `build_recap()`, the strongest a **deterministic date cross-check** (any beat whose date isn't a real published-installment date is dropped — never trust an LLM-emitted date), plus raw-vitals strip/reject, a fail-closed privacy gate, and thin-history blanking. All fail-soft (a recap error never aborts the chronicle).
- **The loop:** `wednesday_chronicle_lambda.build_recap` (local `call_anthropic`, **not** the `ai_calls` layer → no layer rebuild) → `draft_recap_json` → `chronicle_approve._commit_recap` writes `RECAP#latest`+`RECAP#{date}` on both approve and the auto-publish sweep → `/api/recap` (`site_api_coach.handle_recap`, honest-null + stale-record withhold) → `dispatches.js` leads the `/story/timeline/` "story so far", falling back to the front-end stat aside when null.
- **Bootstrap:** a `{"recap_only": true}` invoke builds/regenerates the recap from existing published history without forcing a new installment.
- **Reset-safe:** `RECAP#` under `USER#…#SOURCE#chronicle` → already `EXPERIMENT_SCOPED` (zero taxonomy change, asserted).
- **Deploy (lighter than phase 2, no layer dance):** `LifePlatformEmail` + site-api (`deploy_site_api.sh /api/recap`) + `sync_site_to_s3.sh`. **Verified live:** first recap bootstrapped (`as_of 2026-06-20`, 3 beats); `/api/recap` serves it; all beat dates are real published dates; the story faithfully summarizes the published prologue. New tests: +14 in `tests/test_chronicle_recap.py` (14/14 pass; 368 related tests green).

⚠️ **Watch:** the raw-vitals guard is digit-based, so spelled-out numbers ("recovery score of *twelve*") pass through — grounded here, but the same gap the stance engine has. ⚠️ **Outstanding:** backend serial phase 4 (historical-window APIs); SS tail (SS-08/09/11). See `handovers/HANDOVER_LATEST.md`.

## Coaches-react-to-site-protocols — backend serial phase 2 — 2026-06-29

The second backend serial phase, shipped + deployed live + verified end-to-end (Matthew merged both PRs and authorized "do all the deploys"). **2 PRs, both merged + deployed: #273 (the feature) + #274 (the `SHARED_LAYER_VERSION` 91→92 bump).** main == live, fleet uniform on layer **v92**, 0 open PRs.

- **The loop:** coaches now react to the challenges/experiments Matthew has committed to on the site, instead of treating those protocol surfaces as separate from the coaching. Built on the **same `_gather_all_state` seam** phase 1 (the stance engine) laid — one new gather step.
- **`_gather_site_protocols(coach_id)`** (`coach_narrative_orchestrator`): reads active **challenges** (clean `domain` field) + **experiments** (routed by `tags`), filtered per-coach via a deterministic `COACH_DOMAINS` map (explorer = all; an experiment whose tags match no domain → explorer only, never mis-attributed). Reads go through `_query_begins_with` → **ADR-058 phase-filtered**, so the coach sees exactly the active set the site/MCP surface. Fail-soft; `_protocols_for_brief` caps ≤5/surface and drops nulls; **injected into the brief deterministically on every path** — the same seam `current_stance` uses.
- **`ai_calls.py`:** one ACTIVE PROTOCOLS steering line — acknowledge commitments by name, **never invent** progress/streak/adherence numbers (ground in real data or say it's not visible yet).
- **Scope held tight:** challenges + experiments only — **habits deferred** (ongoing behavior whose adherence already reaches coaches; re-surfacing risks number-fabrication); no persisted protocol-read record (phase 3/4).
- **Folded-in stance polish:** the labs_coach persistent `grounding_flag` — the stance no-numbers rule now explicitly covers **targets and gaps-to-target** ("short of the protein target", not "26% short of 190g"); takes effect on the next weekly summarizer run.
- **Deploy = the full layer dance** (`ai_calls.py` is a layer module): `build_layer.sh` → publish **v92** via `LifePlatformCore` → bump `SHARED_LAYER_VERSION` → redeploy **all 5 consumer stacks** for fleet uniformity (the v89 lesson). Every `cdk diff` read first — layer re-point + benign asset re-hash, zero destroys/IAM.
- **Verified live:** fleet **71/71 functions on v92**; live smoke invoke of `coach-narrative-orchestrator` → `200`, runs clean against the real partitions, correctly omits `site_protocols` when nothing is active (surfaces when Matthew activates a challenge), stance intact. New tests: +10 in `tests/test_coach_stance_engine.py` (30/30 pass; 198 coach tests green).

⚠️ **Outstanding:** backend serial phases 3–4 (Elena "previously on" recaps; historical-window APIs); SS tail (SS-08/09/11); watch labs_coach's `grounding_flag` across weekly runs. See `handovers/HANDOVER_LATEST.md`.

## Coach-opinion engine — an evolving, evidence-derived stance per coach — 2026-06-29

The first backend serial phase, shipped + deployed live + verified end-to-end (Matthew merged both PRs and authorized the deploys). **2 PRs, both merged + deployed: #270 (engine) + #271 (the compression bug it surfaced).**

- **The problem:** each coach's public "read of Matthew" was resolved from a hand-authored **weight-band ladder** — a *sleep* coach "graduated" Matthew foundation→architecture because he lost weight, not because his sleep changed. Board decision (4 lenses) = **"replace, enriched":** an evidence-derived stance becomes the single public read (carrying a domain-appropriate stage); the ladder is demoted to a **silent fallback**, never a parallel read.
- **Stance engine** (`coach_history_summarizer._generate_stance`, weekly): writes a grounded `STANCE#{date}` + `STANCE#latest` per coach, grounded ONLY in the coach's own validated artifacts (`LEARNING#`/`CONFIDENCE#` + `COMPRESSED` positions/corrections) — speaks to patterns, never raw vitals. A `_RAW_VITAL_RE` guard self-corrects once then sets an internal `grounding_flag`; an evolution claim survives only with a real signal (a logged correction or a stage shift); fail-soft.
- **Generation:** the orchestrator injects `current_stance` into the brief **deterministically** so it reaches the coach verbatim on every path; `ai_calls.py` lets the stance lead framing over the static goal block.
- **Render + front-end:** `_stance_block` prefers `STANCE#latest` in a normalized shape both the coach page and My Team consume (ladder mapped into the same keys as fallback); the stance now LEADS the coach page, and "how this read has evolved" reads the dated `STANCE#` trail.
- **⚠️ Pre-existing bug #271 surfaced bootstrapping:** compression was falling back for all 8 coaches — as `THREAD#`/`PREDICTION#` accrued, the compressed JSON outgrew `max_tokens=1500`, truncated before its closing ```json fence, and fell back to a stub (degrading the orchestrator's context for weeks). Fix: compression 1500→4000, stance 900→1400 (same class as the orchestrator's earlier 2000→6000 bump).
- **Verified live:** all 8 coaches serve `source=stance` with distinct evidence stages; 7/8 `grounding_flag=False`. Site-api shipped via `deploy/deploy_site_api.sh` (not `cdk deploy LifePlatformWeb`). New tests: `tests/test_coach_stance_engine.py` (20).

⚠️ **Outstanding:** backend serial phases 2–4 (coaches-review-the-site loop, Elena recaps, historical-window APIs); SS tail (SS-08/09/11); watch labs_coach's `grounding_flag`. See `handovers/HANDOVER_LATEST.md`.

## Self-Sustainability (SS) A-tier — built, deployed live, verified — 2026-06-29

The 6-month-hands-off foresight's highest-leverage backlog, shipped + deployed (Matthew authorized all deploys). 3 PRs — **#266 merged; #267 + #268 open + mergeable.**

- **SS-03 — budget hard-stop alarm** (#266, `LifePlatformMonitoring`): `budget-tier-hardstop` (`BudgetTier≥3` → **urgent** — all Bedrock off, the daily brief goes data-only). *Verified-down:* Garmin-staleness (`ingest-liveness-unhealthy`), podcast-HOLD (`panelcast-no-episode-7d`), and budget≥2 (`budget-tier-escalation` digest) already existed — only the tier-3 urgent escalation was the real gap.
- **SS-06 — gradable-predictions write-time metric** (#267, `LifePlatformCompute`): `coach_state_updater` emits `LifePlatform/Predictions::PredictionGradableShare` per run — a leading indicator of extraction drift ahead of the Sentinel's ≥8-closed check.
- **SS-05 — experiment continuity** (#267, `LifePlatformOperational`): decision = *runs continuously*; a Sentinel `check_experiment_continuity` invariant ALARMs only when a surfaced week disagrees with genesis (the ADR-077 stale-pre-reset leak).
- **SS-02 — podcast HOLD-aging escape** (#267, `LifePlatformEmail`): holds tagged `hold_class` (safety|quality); a Mon+Wed sweep re-generates a *quality* hold through every gate (never ships the flagged draft). **Safety/sensitivity holds never auto-release.**
- **SS-04 — Dependabot safe-auto-merge** (#267, merge-activated): a read-only `dependabot-validate` PR gate + a self-gated `dependabot-automerge` (on validate success) for the dev-tooling group only. No repo-settings change required.
- **Squash-drift caught + reconciled:** SS-01 (last session) was deployed-but-not-on-main; the Email deploy would have regressed it — caught by `cdk diff`. SS-01 source recovered into #267; this doc reconciliation (#268) lands the matching history. Reflex: `cdk diff` before every deploy.

## Website visual uplevel + editorial imagery + serial reader + SS-01 — 2026-06-29

A long, multi-thread session, all shipped + deployed live. **main `b35c8c68` (#260 + #261 merged).**

- **Graphic identity (#260/#261):** a code-drawn SVG identity — a line-icon set (`icons.svg`/`icons.js`: 8 domain + 5 door), deterministic generative **coach sigils** (`sigils.js`), pillar+door identity across cockpit/data/nav, constellation earned-glow, an intensity pass, and the OG share-card reskinned to the v5 palette + the sigil `instrumentMark()`. Codified as a standard in `DESIGN_SYSTEM_V5.md §8`. *(The live OG generator is the `.mjs`, not the legacy Python.)*
- **Editorial imagery (Pexels):** `lambdas/editorial_image.py` puts atmospheric, warm-duotone covers on chronicle/podcast/blog ONLY (never data/meal — truthfulness moat); fail-soft + kill-switch. Fixed the Cloudflare-403 (urllib User-Agent) and a chronicle/podcast image-dedup (per-kind seed offset). Pexels secret + `LifePlatformWeb`/`LifePlatformEmail` deploys + backfill; `EDITORIAL_IMAGES=on`.
- **Serial "walk-backwards" reader (#265):** `/story/timeline/` as a serial spine (recap + month-grouped + "Read Week N →"), a "previously" rail in the chronicle reader, a coach "how this read has evolved" trail, and the podcast↔chronicle cross-link.
- **SS-01 — the chronicle can't go dark (#265):** a daily bounded auto-publish sweep on `chronicle-approve` (publishes a draft unapproved past 48h, never resurrects one abandoned past 10d) via the same approve path. 5 unit tests; verified live.
- **6-month "hands-off" foresight (#264):** the **SS-series** self-sustainability backlog (11 items) recorded in `docs/BACKLOG.md`.

⚠️ **Outstanding:** close #262/#263 (superseded by #261), merge #264/#265; the rest of the SS-series + the backend serial phases (coach-opinion engine, coaches-review-site, Elena recaps, historical APIs). See `handovers/HANDOVER_LATEST.md`.

## Self-Management & Coherence Program (Phases 1–4) + content-bug fix + precision pass + asset guard — 2026-06-28/29

The thesis: the platform proved it's ALIVE (freshness, auth, render all green) but not RIGHT — every silent-incoherence bug (predictions inconclusive for weeks, recovery 30-vs-86, a coach serving RHR 53 vs the canonical 64) passed every existing liveness check because the producer/consumer contracts were implicit. The program makes coherence a first-class, monitored property. **9 PRs #250–258 (this wrap) on top of Phases 1–3 (#245–248); all deployed; main green.**

- **Phase 1 — Coherence Sentinel** (#245): `life-platform-coherence-sentinel` (daily 10:45 AM PT, read-only) runs 5 pure invariants (`lambdas/coherence_invariants.py`, each unit-tested by replaying a past outage — prediction-health, computed-coherence, canonical-facts agreement, endpoint non-degenerate shape, cross-surface count-agreement) → `LifePlatform/Coherence` → the `coherence-overall` digest alarm, plus a budget-gated Haiku semantic pass.
- **Phase 2 — shared contracts** (#246/#247): `measurable_metrics.py` (allowlist DERIVED from `METRIC_SOURCES`, un-driftable) + `canonical_facts.py` (one facts schema + units; producer-contract test). Both behavior-identical.
- **Phase 3 — deploy hygiene** (#248): clobber guard in `sync_site_to_s3.sh` (blocks a full-package sync when origin/main has site/ commits the checkout lacks) + `deploy/session_postflight.py` (layer + config-drift checks).
- **Phase 4 — self-healing eyes on content** (#250/#251/#252): the Sentinel persists findings to `s3://matthew-life-platform/coherence-log/{latest,<date>}.json` (the durable "WHAT failed") + grounds on `canonical_facts.build_canonical_facts`; `remediation/agent.py` reads the artifact as a `coherence` signal (no new IAM); `docs/REMEDIATION_TAXONOMY.md` "Content & coherence signals" routes every invariant to **Bucket B/C only, never auto-merge** — a test asserts no content path is on the auto-merge ALLOWLIST. New scoped IAM `s3:PutObject` on `coherence-log/*`.
- **Live validation → content-bug fix** (#254): the Sentinel's first live run caught coaches serving a hallucinated **RHR 53 vs the canonical 64** (Whoop's 7-day RHR is 55–64; 53 appears nowhere). Root cause: the Phase-3 grounding backstop only LOGGED and the layer validator's RHR regex misses the "RHR" abbreviation. Fix (self-contained in `ai_expert_analyzer`, no layer dance): `_hard_canonical_contradictions` (RHR/recovery/HRV) + the grounding backstop now self-corrects — regenerates the narrative once on a hard canonical contradiction, keeps it only if contradictions drop + a no-invent-trends prompt rule. Proven working (training recovery-73→fixed, glucose, sleep auto-corrected).
- **Precision pass + honest alarm** (#255/#256/#257): `facts_agreement` flags a metric only if a wrong value is cited AND the canonical is cited nowhere (`_mentions_value` — kills the historical/trend false-fire); email-subscriber CDK timeout 15s→30s (matches live; no deploy); the detector adopts the same grounded-anywhere logic + the format prompt stops saying "lead with the number" unconditionally; the Haiku semantic prompt tightened. **#257 (capstone): `coherence-overall` now fires on the DETERMINISTIC invariant verdict ONLY** — the Haiku semantic pass proved too unreliable to gate a daily-emailing alarm (it lists items it concludes are fine in `issues`, returns `coherent:false`), so it's advisory (digest + `semantic_incoherent` flag; supersedes #252's semantic-drives-alarm). Sentinel reports OVERALL OK.
- **Postflight asset-completeness guard** (#258): the new check found the Sentinel **broken again** — the CDK asset glitch is reproducible (CDK skips re-uploading an asset whose hash-key already exists in S3 → a corrupt zip poisons every lambda on that hash; `cdk deploy --force` won't fix it; a 200 invoke returning `errorMessage` not `body` is the tell). Fixed live via `aws lambda update-function-code`; `session_postflight.check_asset_completeness()` downloads each bundled-asset canary's zip and asserts its imported root modules are present.

**Recurring CI lesson:** #250/#251 main runs went red on the ENFORCED ruff I001 gate (pre-existing since Phase-2 #246) which masked Tests/Plan/Deploy; the local flake8 fail-loud subset doesn't run ruff's isort — run full `ruff check` before merge. Cleared in #252.

New tests: `test_coherence_invariants` · `test_coherence_sentinel` · `test_measurable_metrics` · `test_canonical_facts` · `test_prediction_gradability` · `test_remediation_agent` · `test_grounding_self_correction` · `test_session_postflight`.

---

## Data-integrity hardening (Whoop late-sync) + chronicle privacy fix — 2026-06-24 (continuation)

Follow-through on the CI-health/Strava session, same day.

- **#214 — Whoop late-sync hardening (deployed + live).** Generalized #209's Strava fix to the one other source with the same uncovered exposure: Whoop stores per-workout sub-records (`DATE#{date}#WORKOUT#{id}`), so a workout syncing from the band *after* that day's recovery record was stored would silently drop. `refresh_trailing_days=2`. A new `test_trailing_refresh_policy_per_source` pins the per-source policy — **and documents why the others are deliberately excluded**: Garmin (activities already flow to Strava; same-day-finalized wellness; 429-throttles aggressively so extra re-fetches would worsen it), eightsleep/withings/habitify (same-day finalized). Deployed via `cdk deploy LifePlatformIngestion`; whoop lambda updated + verified.
- **#215 — chronicle fallback privacy leak (merged; deploy staged).** The live Elena prompt builds Board interview descriptions from the S3 config (fictional personas), but the in-code `_FALLBACK_ELENA_PROMPT` (fires only on an S3 config-load failure) still hardcoded the **real public figures** the personas are modelled on (Attia/Huberman/Norton/Walker). Replaced with the fictional roster (Dr. Reyes/Nakamura/Webb/Park), personality-matched to `config/board_of_directors.json`. New `test_no_real_names_in_chronicle.py` bans the real names in the generator source (NOT bare "Walker" — the user's own surname) so the leak can't return. Needs a `LifePlatformEmail` deploy (low urgency — rare fallback path).
- **Verified-already-done:** the `get_freshness_status` MCP interior-gap parity (a stale CLAUDE.md follow-up) was in fact implemented in B3 (2026-06-21) — the tool returns `interior_gaps` + `interior_gap_count` per daily source, test green. No work needed; the follow-up note was stale.

## CI-health excavation + Strava late-sync fix + ai-tokens alarm recalibration — 2026-06-24

Inbox-noise triage that root-caused the "Run failed: CI/CD" email stream to **one red gate masking three more.** CI's Lint job runs its gates sequentially (flake8 → black → ruff → mypy) and `Unit Tests` `needs` Lint, so a single unformatted file stopped the pipeline before ruff/mypy/tests ever ran — and weeks of debt accumulated invisibly behind it. Fixing each layer exposed the next. `main` @ `317aa865`; **Lint + Unit Tests green; one deploy pending Matthew.**

**CI-health chain (4 PRs):**
- **#208** — removed 2 dead one-off scripts (`deploy/_publish_week1.py`, `_prologue_rewrite.py`, accidental #186 commits) that failed the **black** gate on every push = the entire email source.
- **#211** — 9 latent **test** failures unmasked once Unit Tests could run: `cost_governor` ×7 (test wasn't aware of the June-2026 tier headroom #169, auto-reverts Jul 1 → autouse fixture pins the normal thresholds); `coach_panel_podcast` sensitivity (refit #166-182 made the gate AI-adjudicate crisis-vs-backstory; test expected the pre-refit auto-hold AND called live Bedrock → rewritten to the new contract with the adjudication mocked); `hevy_common` (`BUCKET` binds `$S3_BUCKET` at import time, other modules set `test-bucket` → suite-order-dependent → pinned).
- **#212** — 14 **ruff** violations: 12 I001 import-sort (`ruff --fix`, sys.path/`# noqa: E402` guards preserved), F841 dead var, S324 `sha1` → `usedforsecurity=False` (grouping signature, not security).
- **#213** — 2 hevy `dry_run` tests hit `routine_title.build_title_context` → DynamoDB → `NoCredentialsError` in CI (passed locally on ambient creds; found by running the suite **creds-blanked**); stubbed `build_title_context`.

Full suite creds-blanked: **2045 passed, 0 failed**; live CI Lint + Unit Tests both **success**.

**Two real platform bugs (2 PRs):**
- **#209 — Strava late-sync drop.** The ADR-092 reconciler caught 5 afternoon walks (Jun 22-23) that never reached DDB — every stored activity those days was a morning workout. Gap detection (`ingestion_framework._find_missing_dates`) is **presence-based**; `refresh_today` only re-pulls today, so walks that **sync late** (after their local day rolled) land on an already-present date and are stranded. New `refresh_trailing_days=N` re-fetches the trailing window regardless of presence; `transform()` rebuilds the day from all API activities, so a re-fetch merges late arrivals and **auto-heals the 5 gaps on the next run.** Strava = 3. Distinct from the #180 tz-window fix.
- **#210 — ai-tokens alarm** 33333 → 150000. It fired daily because the threshold sat below the real autonomous baseline (~59k output tokens/day). Not a cost issue — the $75 budget guard and `ai-daily-spend-high` $ alarm are the real protection and untouched.

**⚠️ One deploy pending (Matthew's boundary):** merging #209 surfaced a pre-existing blocker — layer **v89** was published Jun 22 (hevy-commit-hardening) + `constants.py` bumped to 89, but the **15 consumer Lambdas were never redeployed to attach it** (on v87/v88). The `Plan deployments` layer-consistency gate (also masked) now fails → blocks #209's deploy and is the new "Run failed" email source. Fix: `cd cdk && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 npx cdk deploy --all` (`cdk diff` verified: layer v87/88→89 fleet-wide + #209 code + #210 threshold; **no IAM changes**) — NOT `build_layer.sh` (v89 already published). After deploy: Plan gate passes → CI fully green; `ingest-reconciliation-strava` clears + walks backfill; `ai-tokens` clears.

## Mind page redesign — Phase 0 (the layer the machine can't see); capture deferred — 2026-06-23

Reframed `/evidence/mind/` (the most sensitive page) on the spine **"the layer the machine can't see — awaiting its human."** Per `docs/SPEC_MIND_PAGE_REDESIGN_2026-06-21.md`; **Phase 0 only** (P0.1–P0.4, front-end); the Phase-1 capture mechanics are DEFERRED pending the invitation-not-obligation UX sign-off (its explicit STOP-AND-ASK) — tracked as MIND-01..05. Deployed + live-verified. Seventh page redesign.

**Fixed a live privacy leak:** the previous page rendered vice streaks by NAME ("No alcohol", "No sweets"…); Phase 0 renders them **unnamed** per the hard privacy rule — verified live (zero vice names on the page).

- **P0.1** vice restraint, reset-honest: leads with **cumulative days held** (resilience across resets, never erased) over a fragile streak; streaks **unnamed** (counts only); resets read muted as restarts — **zero red, no shame**.
- **P0.2** the inviting absence: empty mood/journal is a dignified invitation, never a hollow axis; a held one-tap affordance (mechanic is P1, gated).
- **P0.3** Mind pillar decomposed to its inputs (reflection/mood/restraint/depth), honestly "awaiting input" at week one.
- **P0.4** Third Wall centrepiece: the machine's weekly read + Matthew's **held last word** (invitingly empty, not absent).

**Sensitivity honored:** zero red anywhere (the site-wide reserved-red is explicitly excluded here — verified live), vices never named, relapse = muted reset/no shame, non-clinical self-compassionate tone, capture mechanics NOT built (deferred). Single ember; dark + light (new light capture). PR #207.

## Doors / cross-site IA redesign — one documentary, five doors (P0→P3) — 2026-06-23

Cross-site IA/editorial pass over the five doors (Home/Cockpit/Story/Coaching/Evidence). 5-door model + me-first LOCKED (untouched). Per `docs/SPEC_DOORS_EXPERIENCE_REDESIGN_2026-06-21.md`; 11 P-item commits; **front-end only, no server change.** Deployed + live-verified (all doors "Day 10 · Week 2", zero console errors).

**P0 — one genesis source of truth:** `genesisCount()` in `coach_popover.js` is now the single source; removed `story.js`'s duplicate day/week math (the drift that had Home on Week 1 vs Story/Coaching Week 2 — already live-fixed by WQA-07, this removes the risk).

**P1 — one artifact, one home:** Home no longer hosts the full chronicle reader (→ teaser + link to Story) or the full Third Wall (→ teaser + "the full exchange lives in Coaching"); reader ownership routed correctly (chronicle/journal/podcast → Story, lab notes → Coaching; Coaching keeps its own team+lab-notes reader, no dup).

**P2 — per-door uplevels:** Home pulls proof up to the promise (live weight-delta + genesis paired in the hero, the down-beat waveform now LEADS the arc — me-first + constellation intact) · Cockpit "sum of seven pillars" link wires the big level to its pillars (anti-black-box) + Month/Journey quieted as deeper scopes · Story promotes "In my own words" + the growing timeline to first-class cards · Coaching frames track record as "score unlocks as predictions resolve" + expands the cryptic disagreement lines into readable head-to-head arguments with the integrator's call (WQA-06 fields) · one-line descriptor per nav door across all 55 nav files.

**P3 — the moat:** the Third-Wall reply slot is now first-class held space (waiting, not absent; dashed-ember frame) — **the reply mechanic is intentionally NOT wired** (held per its STOP-AND-ASK + the no-fabricated-reply rule); track records auto-activate as predictions resolve. PR #206.

## Vitals page redesign (P0→P3 — glance-first landing page, three altitudes) — 2026-06-23

Reframed `/evidence/vitals/` — THE landing page — as a glance-first instrument panel that bleeds into the analysis: **"an instant, honest tell at the top; the full documentary as you scroll."** Per `docs/SPEC_VITALS_PAGE_REDESIGN_2026-06-21.md`; 7 P-item commits; **front-end only, no server change.** Deployed + live-verified (10 sections, zero console errors). Sixth Evidence page.

**Introduces a reserved alert RED** (`--alert`, restrained oxblood) — the first page to use red, scoped strictly to a genuine STATE (run-down / out-of-range), **never to encode a falling direction** (RHR-down / HRV-up / weight-down stay ember-positive). Zero red renders on a recovered day.

**Altitude 1 — the glance (P0.1–P0.4):** status word **synthesised from 4 component rings** (recovery/HRV/RHR/sleep — anti-black-box, never a lone grade; new `ring` primitive) · now/7d/30d ladder (30d "fills in" at week one) · earned glyph row that lights ember **only on a real daily signal** (habits "X of N today" honest fallback, no fabricated hourly baseline; cross-links Habits) · thin-data stamp ("10 days in — baseline forming") + dashed ring tracks.

**Altitude 2 — the synthesis (P1.1–P1.3):** two-voice autonomic narrative · autonomic hero (RHR + HRV in one frame, **RHR axis inverted so down reads ember-positive**, "the body downshifting" annotation; new `autonomicHero`) · readiness decomposed into HRV/RHR/sleep driver bars.

**Altitude 3 — the analysis (P2.1–P2.5):** autonomic 2×2 (recovery vs strain, today ember, **no trajectory arrows** at n≈8; new `autonomicQuadrant`) · small-multiples grid **replacing the 8 equal hero charts** · background-vitals honest empty (SpO₂/skin-temp/resp not captured — no fake "all in range") · hub links out to each domain page.

**Phase 3 (P3.1–P3.6, gated):** honest capture cards (BP cuff / hourly habits / walking HR / VO₂max / subjective mood); **cross-metric correlations WITHHELD until ≥2 weeks** (no coefficient at ~day 10; reuses the Sleep correlation board when the window opens). PR #205.

## WQA-06 — coach disagreements surfaced on the board — 2026-06-23

The board page showed eight parallel coach monologues but never the *argument* — the stated moat. Two fixes: (1) `_team_tensions` was reading the wrong field names (`coach_a_position`/`resolution_suggested`) so positions came back empty — the integrator digest actually stores `position_a`/`position_b`/`nakamura_call`; fixed the mapping. (2) `renderBoard` gained a "where the coaches disagree — the argument, not the consensus" section above the roster: each card shows the topic, the two coaches' positions **head-to-head**, and **the integrator's (Coach Nakamura's) call**. Live, two real disagreements surface — Nutrition vs Labs on protein/meal architecture, Training vs Mind on rest-day philosophy — each adjudicated. Ember on the coach labels + verdict, positions muted, never red. Deployed + live-verified. PR #204.

## RQA-05 — deficit-sustainability five-channel panel — 2026-06-23

Ported the MCP `get_deficit_sustainability` (BS-12) to a public compute endpoint `/api/deficit_sustainability` + a nutrition-page panel — the "is the cut costing you?" multi-signal read. Monitors 5 recovery channels over a trailing 14-day window (phase-filtered → post-genesis): HRV, sleep quality (efficiency + deep%), recovery, Tier-0 habit completion, training output; first-third vs last-third trend per channel; 3+ concurrent degradations = the deficit is costing too much. Port verified to match the MCP output exactly (intake 1542, deficit 2106/57.7% aggressive, 1/5 degraded → sustainable). Deficit context uses MacroFactor's TDEE (HB fallback as in the MCP), flagged estimated. Strain = ember (look here), holding = muted, too-few-days = faint — never red; honest empty state <7 logged days; correlative, n=1. One clarity fix over the MCP: the sleep channel surfaces the sub-signal (deep% vs efficiency) that triggered the strain. Deployed + live-verified. PR #203.

## RQA-04 — readiness score + component breakdown on the Cockpit — 2026-06-23

Surfaced a previously-hidden signal: `computed_metrics.readiness_score` + `component_scores` (written daily by daily-metrics-compute) are now read into `/api/snapshot.readiness` via a new read-only `_latest_readiness()` helper, and `/now/` renders the stored score, a worded band (primed / moderate / go easy — ember-toned, never alarm-red), and per-component ember bars (recovery / sleep / movement / habits) above the existing raw-vitals rows. Before, the Cockpit only showed a band re-derived from raw vitals; the actual computed score and its breakdown were never displayed. Cheap (no reimplementation, no new endpoint, no extra client roundtrip, no DDB change); deployed + live-verified (score 63 · moderate). PR #202.

## Physical page redesign (P0→P2 — weight cockpit + composition arc + transparent PhenoAge) — 2026-06-23

Reframed `/evidence/physical/` on the spine **"weight is the metronome; composition is the arc"** — a daily weight cockpit (Tier 1) over an episodic, countdown-driven composition arc (Tier 2). Per `docs/SPEC_PHYSICAL_PAGE_REDESIGN_2026-06-21.md`; 21 commits, one per P-item. **Deployed + live-verified (build `89c294fb` == HEAD); PR #201.** Fifth Evidence page (after Nutrition #193/#194 · Training #195 · Sleep #196 · Habits #197). Page renamed "Body composition" → "Weight & composition".

**Tier 1 — weight cockpit (P0.1–P0.7):** trend-weight hero (dual-layer raw dots + ember smoothed trend; **goal 185 is an annotation, never the axis anchor**; genesis marked; two-voice) · silhouette scrubber **linked to the trend marker in lockstep** · HappyScale stat cluster (high/latest/low · yesterday Δ · % complete) replacing DEXA % as the top figures · **milestone ladder** (the vertical measuring-rule signature, 315→185, rungs click ember when crossed, days-between annotated, live now-edge) · rate tempo strip (7d/30d/90d/since-genesis ember-intensity slope-gauges, 7d flagged "early = water") · **projection cone** (widening fast/mid/slow band, rung date-markers, the stated bet flagged early=water + gradeable) · BMI de-emphasized. New `charts.js` primitives `weightTrendChart` + `projectionCone`; `handle_journey` now surfaces profile `height_inches`.

**Tier 2 — composition arc (P1.1–P1.6):** next-DEXA countdown (cut-aware ~10wk-post-genesis target, honest not-yet-booked) · DEXA baseline as one dated lean-vs-fat stacked bar (pre-cut-labeled, snapshot-not-trend) · visceral fat callout + directional risk gauge (ember-intensity, never red, thresholds caveated) · lean/ALMI longevity context (demoted, sarcopenia-floor framing) · **transparent Levine PhenoAge** (new `/api/phenoage`) replacing the DEXA black-box bio-age · full-scan expander (dated) with the **+3.9 bone T-score suppressed+flagged as an artifact**, never shown as fact.

**PhenoAge privacy (Option A, owner decision):** chronological age is used ONLY to compute server-side and is **never returned** — no chronological number, no chrono−pheno gap — so the page can't be used to back out the owner's real age (verified live: zero chronological-leak terms in the payload). All 9 Levine markers shown transparently (lymphocyte % derived from absolute lymphocytes ÷ WBC, labeled); per-draw stamp; population-level + not-the-DNAm-clock caveats. Live phenotypic age computes to 28. **Residual flagged:** the 9 markers are public on the labs page, so a determined reader applying the Levine formula could approximate age from a precise published PhenoAge — harder banding is available if wanted (see `docs/BACKLOG.md` PHY-01).

**Phase 2 (P2.1–P2.5) — honestly gated:** a capture-backlog grid where every STOP-AND-ASK gate is honored by *not* building the gated thing — composition velocity awaits a 2nd valid scan + least-significant-change; progress photos private-by-default (no photo rendered); WHOOP Age not built (unofficial source); tape + scan-two scheduling pending. Follow-ups tracked as PHY-01…06 in `docs/BACKLOG.md`. 63 web/site-api tests pass.

## Habits evidence page redesign (P0→P2 — honest intelligence over Habitify) — 2026-06-23

Rebuilt `/evidence/habits/` from a flat tracker into an honest read of **which habits are load-bearing, where the effort is, and which one pulls the day up — as an early signal, not a law.** Per `docs/SPEC_HABITS_PAGE_REDESIGN_2026-06-21.md`; 17 commits, one per P-item. **Deployed live (build `cfbfaeaa` == HEAD); PR #197.** Completes the four-page Evidence redesign series (Nutrition #193/#194 · Training #195 · Sleep #196 · Habits #197).

**Phase 0 (surface):** honesty-rebuilt keystone hero (n-forward, **no bare Pearson**, coefficient withheld <2wk) · consistency RATE as north-star, single streak demoted (honest at 0) · 90-day ember heatmap with the cut-start (Jun 14) ringed — replaces the green/amber/red grid · group grades from real adherence **RATE** not correlation · state taxonomy tagging every habit on ONE ember+ink ramp incl. **backlog/never-started** (most apps hide it), no red · effort strip (not radar) · per-group small-multiples (floor muted) · goal linkage · data-anchored identity · tick spine + serif/mono two-voice; dark + light first-class.

**Phase 1 (inference):** **P1.1** auto-derived per-habit taxonomy (time-of-day / do·avoid·maintain / logical group) — deterministic name-only heuristic in `/api/habit_registry`, labeled "auto-derived, not fact"; the inferred *groupings* are NOT used to regroup the public surface (only the context tags ship). **P1.2** friction tag from real adherence (automatic / takes effort / high friction, ember→muted→dashed, no red). **P1.3** drivers view — friction real, trigger/reward honest-empty (the empty state IS the build; no fabricated causes). **P1.4** why-missed — real miss counts, reason honest-empty, no streak-shame. **P1.5** cross-page wiring — each group links to its evidence page; the reverse completion-feed is honest-pending.

**Phase 2 (calibration):** **P2.1** keystone coefficient + chip gated to ≥2wk overlap, rendered inside the sleep-board confidence-card DNA (n + overlap-weeks + confidence tier); a thin-but-sufficient n triggers a "likely noise" guard that suppresses the coefficient (verified n=21/r=.18). Stays N=1/correlative; genesis+8d at ship → renders **withheld** live, auto-surfaces at the window (~2026-06-28).

**Server:** `handle_habit_registry` emits a `taxonomy` per habit + `taxonomy_derived` flag (new `_derive_habit_taxonomy`); `handle_habits` gained `per_habit` adherence aggregation over 90 days of Habitify statuses. No DDB schema change. Open follow-ups tracked as EVR-01…06 in `docs/BACKLOG.md` (all genuine needs-data capture). 93 habit/site-api/web tests pass.

## Sleep evidence page redesign (P0→P2 + self-policing correlation board) — 2026-06-23

Flipped `/evidence/sleep/` retrospective → prospective: the circadian forecast LEADS as a "tonight's odds" hero (0→100 gauge + four anchors + the lever, two-voice, at-risk muted never red); last night demotes to evidence ("one night is noise"). Added dual-device stage agreement ("agreement, not truth"), regularity + social-jet-lag (empty until a weekend), stage composition (refuses <4), bed-temp-vs-deep environment overlay (observation-only), an autonomic-downshift state, a recovery cross-link, and the headline feature: a **self-policing cross-source correlation board** (new `/api/sleep_correlations`) where every card carries n + overlap-weeks + a confidence tag, shows direction-only under 2 weeks (no Pearson/chip), flags thin pairs "likely noise", and HARD-WITHHOLDS the sleep-vs-weight coefficient through the water-weight phase. Verified dark + mobile + the first light capture. 23 commits.

## Training evidence page redesign (P0→P2) — 2026-06-23

Rebuilt `/evidence/training/` on the twin spine "building the engine — and managing the load." Per `docs/SPEC_TRAINING_PAGE_REDESIGN_2026-06-21.md`; 20 commits, one per P-item. Built + locally verified; PR off `origin/main`.

**Phase 0:** Lift Index (load-trend sparklines, killed the 1RM "✓ goal met" table; <3-session tiles = fills-in) · session-volume ramp hero with a signed-off load-management caution · RHR-decline hero (RHR-down reads ember-POSITIVE — the Training inversion) · Zone-2 vs 150 now cross-source (Hevy bike/elliptical folded into Z2, server) · HR-of-the-engine (cardio HR; lifting HR an honest gap, never a 0 bar) · walking-as-engine + ember-intensity steps heatmap (low days muted, not hidden) · modality composition (ember ramp, mobility out of the cardio list) · Push/Pull/Legs balance · daily strain bar (replaced the naked avg-strain headline) · measuring-rule spine + two-voice signatures.

**Phase 1:** RPE per set (autoregulation) · session sRPE (internal load) · per-muscle volume vs MEV/MAV/MRV landmark bars (the `get_muscle_volume` core-mapping blocker was verified already fixed via #186) · anatomical body-map (stylized front+back, ember-intensity by volume — built per explicit sign-off) · HR-strap + rucking honest empty states.

**Phase 2:** strain-vs-recovery overlay (no Pearson, refuses <4) · ACWR placeholder (unlocks ~4 weeks) · present-vs-PROVEN_BLUEPRINT (private, server-gated `TRAINING_BLUEPRINT_PUBLIC`, OFF — never public).

**Server:** training_overview emits `muscle_volume` (compact in-package port of the MCP classifier + Israetel landmarks) and folds Hevy cardio minutes into Z2; strength_benchmarks emits per-lift `history`. New chart-kit primitives: targetSpine, heatStrip, stackedDayColumns, landmarkBars; dualLineChart gained showGap. No DDB schema change.

---

## Nutrition evidence page redesign (P0→P2 + CGM) — 2026-06-21

Rebuilt `/evidence/nutrition/` from a flat tile-board into one argued trajectory — "a deficit I can hold, hitting the protein to keep muscle, without quietly costing me anything." Per `docs/SPEC_NUTRITION_PAGE_REDESIGN_2026-06-21.md`; 20 commits, one per P-item. **Deployed live (build `8d342e15`); PR #193.**

### Phase 0 — fixes + the spine (front-end + one API readout)
§0 hero verdict (measuring-rule energy spine + two-voice) · lead with the 0% protein miss (ember-as-warning, never a "win" block) · kill the frozen protein-timing score · worst-first horizontal micronutrient **sufficiency bars** (value-labelled, no desktop/mobile clip, ember reserved for the worst offenders) · macro split recomputed on a **kcal basis** (fat ~30%, not 16% by mass) · honest empty states (no `Rest Day — Count 0` zero-rows) · per-day macro composition **stacked by energy** (refuses <4 pts) · the two signatures deployed (measuring-rule tick spine on both trend charts + a serif "what this means" annotation) · §1 loss-rate readout (target 3 lb/wk → required −1500 → actual → gap) with a deficit-intensity flag, rate + protein on one sightline.

### Phase 1 — new-capture unlocks (API fields first)
Per-meal timing+protein → §4 rhythm: eating-window ribbon (vs 16:8), protein time-of-day, avg protein/meal, and the **real** occasion-aware distribution score (revives the P0.3 placeholder) · sodium → §5 electrolyte honesty + the week-one "the drop is water" caveat (not a hydration ring) · daily hunger/energy not captured anywhere → honest "needs capture" empty state · Withings lean mass → the g/kg-lean muscle-retention protein floor in §2.

### Phase 2 — cross-source layer (honesty + privacy gated)
Standing self-grading weight prediction (bet + confidence band + verdict) · scale-vs-log **reconciliation** (projected-from-energy-balance vs actual Withings trend, two trajectories, gap annotated, **no Pearson**, gated ≥2 weeks overlap) · CGM × meals designed empty state. **Private-by-default, server-gated, flags OFF:** food-delivery off-protocol tell (`NUTRITION_DELIVERY_PUBLIC`, flip after confirm) + present-vs-PROVEN_BLUEPRINT (`NUTRITION_BLUEPRINT_PUBLIC`, never on — ADR-089). P2.4 deferred.

### Server / data
`lambdas/web/site_api_observatory.py::handle_nutrition_overview` emits the new computed objects (`loss_rate`, `meal_rhythm`, `electrolytes`, `lean_mass`, `projection`, `reconciliation`, `food_delivery`, `blueprint_benchmark`). **No DynamoDB schema change** — all derived from existing partitions. New chart-kit primitives in `site/assets/js/charts.js`. Verified via a local Playwright render harness (route-mocked API) before deploy.

---

## HAE ingestion path — deep review + P0 activity-undercount fix — 2026-06-19

Surgical review of the Health Auto Export path (`docs/reviews/HAE_PATH_REVIEW_2026-06-19.md`), triggered by Apple Health showing ~5,700 avg steps/wk vs ~2,960 stored.

### Root cause — HTTP 413 (data never arrives)
The 7-day step re-sync is rejected at the edge: HAE exports **raw per-sample** steps (`aggregateData=False`); the multi-day payload is **24.8 MB** and the Lambda Function URL caps bodies at **~6 MB** → **HTTP 413**. HAE logs the run `complete` right after the 413, so the phone shows success while nothing lands — the "successful on the app, issues downstream" mechanism. (Activity hits 413 too at 14.2 MB.) Historical undercount is a separate older cause: the Activity automation's `period=Today` + the Watch→iPhone sync lag froze partial iPhone-only counts. **Deferred to 2026-06-20:** aggregate the HAE step export OR a one-time file export/import for history.

### Fixed (P0, code — commit follows)
- **`health_auto_export_lambda.py`** additive activity metrics (`steps`, `distance_walk_run_miles`, `active_calories`, `basal_calories`, `flights_climbed`) now resolve via **MAX across per-source daily sums** instead of a single fixed-priority source — fixes the undercount (a partial iPhone count no longer discards the fuller Watch count) AND the double-count. `merge_day_to_dynamo` adds a **GREATEST(stored, new)** monotonic guard so a later partial export can't lower a day's total (`monotonic_guard=False` for authoritative backfills). The test that enshrined the bug is corrected. 16 HAE tests green. **Makes data correct once it arrives; orthogonal to the 413 unblock.**

### Surfaced (not fixed — see review)
- UTC-day partitioning of inherently-local activity metrics (won't match the app's local-day view); `active_calories` never exported by any `includeHealthMetrics=True` automation; the 413 is invisible to us (rejected pre-Lambda, no alarm); no ingestion completeness/plausibility gate.

Not deployed.

---

## Movement data integrity — DI-1.5 (ADR) + HAE step-undercount RCA — 2026-06-19 (WORKORDER_DI1)

### Added — ADR-091
- **ADR-091: source-state honesty guard as a cross-coach standard.** Generalizes the DI-1.3 guard + the readiness future-stamp guard into a standard: a coach must gate any deficiency verdict on its primary source's `source_state` and withhold ("not assessable + which source + why") when that source isn't `live`, with a deterministic write-time backstop (not prompt-only). `training_coach` is the reference; the other operational coaches adopt the gate incrementally. (Dr. Chen's corrective thread entry is written out-of-band by Matthew, not Claude Code.)

### Diagnosis — Apple Health step undercount (RCA, fix deferred)
- The Apple Health **app** shows ~6,500 / ~7,800 steps on 6/15 / 6/18; **DDB stored 402 / 444**. Root cause in `health_auto_export_lambda.py`: (1) `pick_source_or_all` keeps a **single** highest-priority source per day and discards the rest — the code comment (L324) admits the watch-without-phone loss; (2) **no MAX/accumulate guard on the steps write** (unlike water/caffeine's `_rd_` dedup map), so a partial export plain-overwrites. Possible third (config) cause: HAE may not export the Watch step stream — **same HAE export-config surface as the `active_calories`-entirely-None gap**, both folded into the DI-1.6 precondition note.
- **Recommended fix (separate item — ingestion change + historical backfill, Matthew's domain):** MAX across per-source daily sums + GREATEST(stored,new) on write for additive activity metrics; re-derive history from `raw/matthew/health_auto_export/`. This is why DI-1.4's "low step days" looked phone-only — partly an ingestion artifact.

---

## Movement data integrity — DI-1.4 — 2026-06-19 (WORKORDER_DI1: step gap + phantom 298 + precedence)

Apple-Health step-field completeness + the resolved step source-of-truth. Prerequisite for the DI-1.6 HAE failsafe (a backstop can't be trusted while its own feed has silent field-level gaps).

### Diagnosis — the "phantom 298", traced
The coach cited a **298** step avg that reconciled with nothing (~3,415 actual). Root cause: the training expert's step precedence preferred **Garmin steps first**, but Garmin is rate-limited (DI-1.1) and emits sparse partial readings — **Garmin 2026-06-15 = `298` steps** was being used as the step signal while Apple Health's ~3,415 was the truer figure. Fixed by state-aware precedence.

> **Fixture correction (verified against live DDB 2026-06-19):** the work order's "Apple steps blank 6/5–6/13" is **inaccurate** — steps are present every day in that window (low, 254–2487, phone-only days); the field that is *entirely* blank recently is **`active_calories`** (None on every day 6/3–6/19). The 298 was a Garmin reading, not a blank-Apple artifact. The completeness-flag logic below is validated against a constructed gap and handles genuinely-missing step fields whenever they occur.

### Fixed / Added
- **State-aware step precedence (coach, `gather_data_for_expert("training")`)** — Garmin (watch) steps are used **only when Garmin's source-state is `live`**; otherwise Apple Health. Kills the phantom 298 (a rate-limited Garmin's partial readings no longer masquerade as the step truth). Adds `step_source` + `step_completeness_pct` to the coach data.
- **Step-completeness flag (`get_daily_metrics(view="movement")`)** — per-day `step_data_complete` + summary `step_coverage_pct` / `step_incomplete_dates` / `step_incomplete_days`. The `apple_health` envelope can read "fresh" while the step field itself is missing for a day; that gap is now surfaced rather than silently read as zero movement.
- **DI-1.2 cross-check confirmed** — a blank/low Apple step day with a Hevy session is never `sedentary` (the Hevy-join already closes the path a missing step field could use to drive an under-training verdict).
- **Step source-of-truth documented** in `SCHEMA.md` (the live authoritative field reference; `DATA_DICTIONARY` is archived).

### Tests
- `tests/test_di1_movement_integrity.py::test_step_completeness_flag_surfaces_jun5_13_gap` (+ blank-Apple-steps-never-sedentary-with-Hevy). registry/wiring/coach/business green.

Correlational only; not deployed. DI-1.5 (governance/ADR) + DI-1.6 (HAE failsafe — needs Matthew to verify Garmin→Apple workout sync + HAE export config) remain.

---

## Movement data integrity — DI-1.1 source-state legibility — 2026-06-19 (WORKORDER_DI1)

Gives every ingest source a real, legible operational state — **`live` / `paused` / `rate_limited` / `stale`** — so a deliberately-off source (Strava, paused at the 402 paywall) or a chronically rate-limited one (Garmin's 429 refresh block) is never mistaken for silent breakage. Replaces DI-1.3's interim freshness-inference with the real field.

### Added
- **`lambdas/source_state.py`** (new shared-layer module) — `resolve_source_state(source, latest_date, today, *, rate_limited=…)`. **Freshness wins for `live`**: fresh data resolves to `live` even for a source still in `DECLARED_PAUSED_SOURCES`, so re-enabling Strava flips it `paused → live` the moment data flows again — no second edit. A rate-limit marker outranks the paused/stale labels; a declared-paused source with no fresh data is `paused`; everything else is `stale`. `has_rate_limit_marker()` reads Garmin's `REFRESH_RATELIMIT`. Added to `deploy/build_layer.sh`.

### Changed
- **`get_freshness_status` (MCP)** now returns `source_state` per source — the flip is visible on the freshness tool / status page.
- **Coach honesty guard (DI-1.3)** now reads `resolve_source_state` instead of inferring from freshness; the training expert's `movement_source_state` carries real `paused`/`rate_limited` labels (so the guard's note reads "strava: paused; garmin: rate-limited" exactly).
- **Liveness-pinger masking killed (`pipeline_health_check_lambda`)** — a `paused` source's healthcheck "ok" only proves the Lambda boots, masking that its cron is gone. Paused sources now **skip the boot-probe** and report as `paused` (a new bucket — neither healthy-green nor failed-red), and are **excluded from the `ingest-liveness-unhealthy` alarm** (a paused source has no cron to be "stopped", so attempt-staleness would false-fire). `health_check` record + body gain a `paused` count.

### Tests
- `tests/test_di1_movement_integrity.py` — `test_source_state_live_after_strava_reenable` (the visible flip), paused≠rate_limited≠stale matrix, resolver→guard end-to-end (paused withholds; live stops withholding), and the pipeline non-masking contract.

> **Re-enabling Strava (Matthew):** once the cron is restored and data re-ingests, `source_state` auto-flips to `live` (freshness wins) — **but remove `"strava"` from `DECLARED_PAUSED_SOURCES` in `source_state.py`** so a *future* real Strava outage labels as `stale` (not `paused`) and the health-check resumes probing it. Garmin re-enable work (GARM-1) is deferred.

Correlational only; not deployed. Ships in the same shared-layer rebuild as DI-1.3. Remaining DI-1.1 step is the Strava re-enable itself (CDK un-pause + rule recreate + backfill — Matthew). DI-1.4 next.

---

## Movement data integrity — DI-1.3 — 2026-06-19 (WORKORDER_DI1: coach Hevy-first pull + honesty guard)

The training coach (`training_coach` / Dr. Chen) assembled its data from **Strava + Garmin + Whoop + steps — no Hevy** — so with Strava paused and Garmin rate-limited it saw "0 sessions, all rest days" and wrote consecutive "you're under-training" verdicts that the thread's continuity loop kept re-confirming. DI-1.3 makes Hevy the primary training-stimulus signal in the coach and adds a deterministic honesty guard.

### Fixed
- **Hevy-first pull (`ai_expert_analyzer_lambda.gather_data_for_expert("training")`)** — now joins Hevy first; the training-day count, session/min totals, and modality breakdown derive from Hevy (lifts) **then** Strava (aerobic/NEAT), never from steps. A training day = any day with a logged workout from either source. New fields: `training_days`, `hevy_sessions/sets/active_min`, `strava_sessions/active_min`, `movement_source_state`, `hevy_summary`.
- **Honesty guard (`intelligence_common.movement_assessability` + `apply_movement_honesty_guard`)** — mirrors the readiness future-stamp guard (`tools_health.py:490–530`). Aerobic/NEAT volume is "assessable" iff **Strava is live** (§4a: Strava is authoritative for *what moved*; steps undercount, Garmin is chronically rate-limited). When it isn't, the guard withholds any under-training/sedentary verdict that slipped into `position_summary`, replaces it with an honest statement naming the unavailable sources + reason, and still reports the Hevy training that happened. Wired as both a **prompt constraint** (keeps the narrative honest) and a **deterministic write-time backstop** (the guarantee).
- Source states are freshness-derived for now (`live`/`stale`/`missing`); **DI-1.1 will inject precise `paused`/`rate_limited` labels** once Matthew's Strava call lands — the guard renders whatever label it's handed.

### Tests
- `tests/test_di1_movement_integrity.py::test_coach_guard_withholds_undertraining_when_strava_paused` (the regression that keeps Dr. Chen from relapsing) + pass-through-when-live and no-op-when-no-assertion guards. `test_coach_intelligence` / `test_persona_registry` still green.

Correlational only; no causal language. **Not deployed.** DI-1.4 (Apple step gap + phantom 298) + DI-1.5 (governance) next.

---

## Movement data integrity — DI-1.2 — 2026-06-19 (WORKORDER_DI1: Hevy join + Hevy-aware TSB)

The movement/sedentary read and the TSB training-stress signal were both **Strava-only**. With Strava deliberately paused (402 paywall — DI-1.1) and Garmin rate-limited, real Hevy training days (Push/Pull/Legs/Engine 6/16–6/19) were stamped `has_workout=false` and flagged `sedentary`, and TSB collapsed toward zero. DI-1.2 makes Hevy the primary "did he train" signal everywhere.


... [TRUNCATED — 4250 lines omitted, 4650 total]


---

## 3. ARCHITECTURE

# Life Platform — Architecture

Last updated: 2026-07-06 (v8.6.0 — 143 tools, 43-module MCP package, 20 data sources, 93 Lambdas, 9 secrets, 110 alarms, 8 CDK stacks deployed).

> **v4 "The Measured Life" front-end is live** (ADR-071) — `averagejoematt.com` is a static S3 + CloudFront site over the unchanged engine, with **three doors:** Cockpit (`/now/`, live data), Story (`/story/`, the writing hub), Evidence (`/evidence/`, the data archive); the pre-v4 site is preserved verbatim at `/legacy`. Shared-layer version: see the discovery command in [CONVENTIONS.md](CONVENTIONS.md#facts-that-drift-run-the-command-never-quote-a-number) (don't hand-write it — it drifts). **91 ADRs** (ADR-001 → ADR-103; newest: ADR-101 distribution-before-monetization, ADR-102 single-table-DynamoDB-kept-on-purpose, ADR-103 complexity-posture ledger). The count line above is auto-maintained by `deploy/sync_doc_metadata.py` (pre-commit hook) — edit `PLATFORM_FACTS` there, not by hand.

---

## Overview

The life platform is a personal health intelligence system built on AWS. It ingests data from twenty-six sources (thirteen scheduled + one webhook + three manual/periodic + two MCP-managed + one State of Mind via webhook), normalises everything into a single DynamoDB table, and surfaces it to Claude through a Lambda-backed MCP server. The design philosophy is: get data in automatically, store it cheaply, and make it queryable without a data engineering background.

---

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  INGEST LAYER                                               │
│  Scheduled Lambdas (EventBridge) + S3 Triggers + Webhooks   │
│  Whoop · Withings · Strava · Eight Sleep · MacroFactor      │
│  Garmin · Apple Health · Habitify · Notion Journal          │
│  Health Auto Export (webhook — CGM/BP/SoM) · Weather        │
│  Supplements (MCP write) · Labs · DEXA · Genome (seeds)     │
└────────────────────────┬────────────────────────────────────┘
                         │ normalised records
┌────────────────────────▼────────────────────────────────────┐
│  STORE LAYER                                                │
│  S3 (raw) + DynamoDB (normalised, single-table)             │
└────────────────────────┬────────────────────────────────────┘
                         │ DynamoDB queries
┌────────────────────────▼────────────────────────────────────┐
│  SERVE LAYER                                                │
│  MCP Server Lambda (133 tools, 768 MB) + Lambda Function URL │
│  ← Claude Desktop + claude.ai + Claude mobile via remote MCP│
│                                                             │
│  COMPUTE LAYER (IC intelligence features)                   │
│  character-sheet-compute · adaptive-mode-compute            │
│  daily-metrics-compute · daily-insight-compute (IC-8)       │
│  hypothesis-engine v1.2.0 (IC-18+IC-19, Sunday 12 PM PT)   │
│  compute → store → read pattern: runs before Daily Brief    │
│                                                             │
│  EMAIL LAYER                                                │
│  monday-compass (Mon 7am) · daily-brief (10am)              │
│  wednesday-chronicle (Wed 7am) · weekly-plate (Fri 6pm)     │
│  weekly-digest (Sun 8am) · monthly-digest (1st Mon 8am)     │
│  nutrition-review (Sat 9am) · anomaly-detector (8:05am)     │
│  freshness-checker (9:45am) · insight-email-parser (S3 trig)│
│                                                             │
│  WEB LAYER — v4 "The Measured Life" (ADR-071)              │
│  averagejoematt.com · CloudFront E3S424OXQZ8NBE → S3 /site  │
│  Three doors: / (landing) · /now/ (Cockpit) ·              │
│    /story/ (the writing) · /evidence/ (data archive)        │
│  Old site preserved at /legacy (private; 301s via the       │
│    v4-redirects CF function from redirects.map)             │
│  site-api Lambda (read-only): /api/ask · /api/board_ask ·   │
│    /api/pulse · /api/journey · /api/workouts · /api/labs …  │
└─────────────────────────────────────────────────────────────┘
```

---

## AWS Resources

**Account:** 205930651321
**Primary region:** us-west-2

| Resource | Type | Name / ARN |
|---|---|---|
| DynamoDB table | NoSQL database | `life-platform` (deletion protection + PITR enabled) |
| S3 bucket | Object storage + static website | `matthew-life-platform` (static hosting on `dashboard/*`) |
| SQS queue | Dead-letter queue | `life-platform-ingestion-dlq` |
| Lambda Function URL (remote MCP) | Remote MCP HTTPS endpoint | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/` (OAuth 2.1 auto-approve + HMAC Bearer) |
| API Gateway | HTTP endpoint | `health-auto-export-api` (a76xwxt2wa) — webhook ingest |
| Secrets Manager | Credential store | **9 active secrets** at $0.40/month each = **~$3.60/month**
| SNS topic | Alert routing | `life-platform-alerts` (urgent) + `life-platform-alerts-digest` (batched daily by `alert-digest-lambda` per ADR-050) |
| CloudFront (amj) | CDN (public) | `E3S424OXQZ8NBE` → site-api Lambda + S3 `/site`, alias `averagejoematt.com` |
| CloudFront (dash) | CDN + auth | `EM5NPX6NJN095` (`d14jnhrgfrte42.cloudfront.net`) → S3 `/dashboard`, Lambda@Edge auth, alias `dash.averagejoematt.com` |
| CloudFront (blog) | CDN (public) | `E1JOC1V6E6DDYI` (`d1aufb59hb2r1q.cloudfront.net`) → S3 `/blog`, alias `blog.averagejoematt.com` |
| CloudFront (buddy) | CDN (public) | `ETTJ44FT0Z4GO` (`d1empeau04e0eg.cloudfront.net`) → S3 `/buddy`, alias `buddy.averagejoematt.com` |
| ACM Certificate | TLS | us-east-1 — `averagejoematt.com` + all subdomains (DNS-validated via Route 53) |
| SES Receipt Rule Set | Inbound email routing | `life-platform-inbound` (active) — rule `insight-capture` routes `insight@aws.mattsusername.com` → S3 |
| SES Configuration Set | Outbound delivery telemetry | `life-platform-emails` wired to `daily-brief`, `weekly-digest`, `monthly-digest`, `partner-weekly-email` |
| CloudWatch | Alarms + logs | **~110 metric alarms** (12 redundant ingestion-error alarms consolidated 2026-05-29). |
| CDK | Infrastructure as Code | `cdk/` — 8 stacks deployed. CDK owns all Lambda IAM roles + ~50 EventBridge rules. Stacks: `core_stack`, `ingestion_stack`, `email_stack`, `compute_stack`, `mcp_stack`, `operational_stack`, `web_stack`, `monitoring_stack`. |
| CloudTrail | Audit logging | `life-platform-trail` → S3. Data events enabled for `s3://matthew-life-platform/raw/` and `s3://matthew-life-platform/uploads/`. |
| AWS Budget | Cost guardrail | **$75/mo all-in cap** (ADR-063), alerts at 50%/70%/85%/100%. Enforced via `cost_governor_lambda` (hourly) → SSM `/life-platform/budget-tier` → `budget_guard.py` gates AI features (1=coaches, 2=website AI, 3=hard cutoff in `bedrock_client.invoke()`). |
| Concurrency quota | Account-level | **10** (default; quota raise request filed 2026-05-19 — AWS Support case 177921309700709) |

---

## Ingest Layer

### Scheduled ingestion (EventBridge → Lambda)

Each source has its own dedicated Lambda and IAM role. EventBridge triggers fire hourly with a 10pm–4am PST maintenance window. All cron expressions use fixed UTC.

**Gap-aware backfill (v2.46.0):** All API-based ingestion Lambdas implement self-healing gap detection. On each run, the Lambda queries DynamoDB for the last N days (including today), identifies missing DATE# records, and fetches only those from the upstream API. Cost is ~$0/month — Lambdas short-circuit in <50ms when no new data exists.

**Schedule:** Hourly during active hours (4am–10pm PST) for most sources. Exceptions: Garmin at 4x daily (OAuth rate limits), Weather + Todoist at 2x daily (COST-OPT). Maintenance window: 10pm–4am PST (UTC 6–11 skipped).

**Shared Lambda Layer:** **v76** (mirrored in `cdk/stacks/constants.py:SHARED_LAYER_VERSION`). Includes `ai_calls.py` (god-module split 2026-06-08 → `ai_calls.py` (AI-call layer: `call_anthropic` + coaches + board) / `ai_context.py` (prompt-context + scoring builders) / `ai_summaries.py` (data-summary builders); `ai_calls` re-exports both for backward compat), `retry_utils.py`, **`bedrock_client.py`** (ADR-062 — all Claude calls funnel here, IAM auth via `bedrock:InvokeModel`), **`budget_guard.py`** (ADR-063 — `allow(feature)` gates AI by SSM tier), `board_loader.py`, `output_writers.py`, `scoring_engine.py`, `secret_cache.py`, `intelligence_common.py`, `ingestion_framework.py` (SIMP-2 per ADR-056), `auth_breaker.py`, `http_retry.py`, `rate_limiter.py`, `request_validator.py`, `compute_metadata.py`, `constants.py` (genesis date + baseline), `phase_filter.py` (default-deny by phase), `numeric.py`, `character_engine.py`, `html_builder.py`, `ai_output_validator.py`, `platform_logger.py`, `ingestion_validator.py`, `item_size_guard.py`, `digest_utils.py`, `sick_day_checker.py`, `site_writer.py`, `insight_writer.py`, `ai_context.py`, `ai_summaries.py`. **30 modules total**. Rebuild with `bash deploy/build_layer.sh`. Source of truth: `cdk/stacks/constants.py:SHARED_LAYER_VERSION` (test `lv6` enforces consistency with the latest AWS-published layer).

**Secret caching (COST-OPT-1):** 15-min in-memory TTL cache via `secret_cache.py` in shared layer. Reduces Secrets Manager API calls ~90% across 12 active Lambdas.

**Prompt caching (COST-OPT-2, ADR-049):** Both `ai_calls.py` and `retry_utils.py` auto-wrap system messages as cached content blocks (`anthropic-beta: prompt-caching-2024-07-31`). 90% discount on repeated system prompt tokens. CloudWatch metrics: `AnthropicCacheWriteTokens`, `AnthropicCacheReadTokens`. Model tiering: structured/templated tasks use Haiku (`AI_MODEL` env var), narrative content stays on Sonnet. All model assignments are env-var configurable for instant rollback.

| Source | Lambda | Schedule | Type |
|---|---|---|---|
| Whoop | `whoop-data-ingestion` | Hourly (active hours) | API pull |
| Garmin | `garmin-data-ingestion` | 4x daily (cron 0 0,6,14,22) | API pull |
| Eight Sleep | `eightsleep-data-ingestion` | Hourly (active hours) | API pull |
| Withings | `withings-data-ingestion` | Hourly (active hours) | API pull |
| Habitify | `habitify-data-ingestion` | Hourly (active hours) | API pull |
| Strava | `strava-data-ingestion` | Hourly (active hours) | API pull |
| Todoist | `todoist-data-ingestion` | 2x daily | API pull |
| Notion Journal | `notion-journal-ingestion` | Hourly (active hours) | API pull |
| Weather | `weather-data-ingestion` | 2x daily | API pull |
| MacroFactor | `macrofactor-data-ingestion` | S3 trigger (Dropbox CSV) | File upload |
| Dropbox Poll | `dropbox-poll` | `rate(30 minutes)` | File poll |
| Journal Enrichment | `journal-enrichment` | Hourly | Compute |
| Activity Enrichment | `activity-enrichment` | Hourly | Compute |
| Apple Health (CGM, water, BP, SOM) | `health-auto-export-webhook` | Near real-time (webhook) | HAE push |

> **SIMP-2 cohort (8 of 14 ingestion Lambdas, ADR-056):** `whoop`, `garmin`, `strava`, `withings`, `eightsleep`, `habitify`, `todoist`, `weather`. All `import from ingestion_framework`. The 6 pattern-exempt sources are: `notion`, `macrofactor`, `apple_health`, `dropbox_poll`, `food_delivery`, `health_auto_export` (now `measurements_ingestion`).
>
> **Lambda renames + deletions in V2 cleanup (2026-05-17/19):** `weather_handler.py` → `weather_lambda.py`. `tools_calendar.py` DELETED (ADR-030 retired, Google Calendar). `podcast_scanner_lambda.py` DELETED (no AWS counterpart). `email_framework.py` DELETED from shared layer.

### Compute + Email Lambdas

| Function | Lambda | Cron (UTC) | PT (PDT) |
|---|---|---|---|
| Daily Insight Compute (IC-8) | `daily-insight-compute` | `cron(20 17 * * ? *)` | 10:20 AM |
| Daily Metrics Compute | `daily-metrics-compute` | `cron(25 17 * * ? *)` | 10:25 AM |
| Adaptive Mode Compute | `adaptive-mode-compute` | `cron(30 17 * * ? *)` | 10:30 AM |
| Character Sheet Compute | `character-sheet-compute` | `cron(35 17 * * ? *)` | 10:35 AM |
| Anomaly Detector | `anomaly-detector` | `cron(5 15 * * ? *)` | 08:05 AM |
| Daily Brief | `daily-brief` | `cron(0 17 * * ? *)` | 10:00 AM |
| Monday Compass | `monday-compass` | `cron(0 15 ? * MON *)` | Mon 08:00 AM |
| Wednesday Chronicle | `wednesday-chronicle` | `cron(0 15 ? * WED *)` | Wed 08:00 AM |
| The Weekly Plate | `weekly-plate` | `cron(0 2 ? * SAT *)` | Fri 07:00 PM |
| Weekly Digest | `weekly-digest` | `cron(0 16 ? * SUN *)` | Sun 09:00 AM |
| Nutrition Review | `nutrition-review` | `cron(0 17 ? * SAT *)` | Sat 10:00 AM |
| Monthly Digest | `monthly-digest` | `cron(0 16 ? * 1#1 *)` | 1st Mon 9:00 AM |
| Hypothesis Engine (IC-18) | `hypothesis-engine` | `cron(0 19 ? * SUN *)` | Sun 12:00 PM |
| Weekly Correlation Compute | `weekly-correlation-compute` | `cron(30 18 ? * SUN *)` | Sun 11:30 AM |
| Weekly Signal (PB-06) | `weekly-signal` | `cron(30 16 ? * SUN *)` | Sun 09:30 AM |
| Hevy Routine Cron (ADR-066) | `hevy-routine-cron` | `cron(30 13 ? * SUN *)` *(rule starts disabled)* | Sun 06:30 AM |

### Hevy Routine Write-Loop (ADR-066, 2026-05-31)

Closes the **program → perform → adapt** loop with Hevy. One write path, two front doors:

```
coaching / generation logic
        │
        ▼
  routine-spec IR  ◄── system of record (ROUTINE# DDB partition)
        │
        ▼
   hevy_compiler   ◄── sole owner of Hevy wire format (one module)
        │
        ▼
 create_routine / update_routine_with_guard  →  Hevy
```

- **Front door 1 — chat:** `manage_hevy_routine` MCP fat tool (9 actions: draft / dry_run / commit / list / get / archive / floor / re_entry / adherence).
- **Front door 2 — cron:** `hevy-routine-cron` Lambda, EventBridge rule `enabled=False` at birth + SSM `/life-platform/hevy/cron_enabled=false` (belt-and-suspenders).
- **Shared modules (layer v64):** `routine_ir`, `hevy_compiler`, `hevy_write_client`, `hevy_template_cache`, `routine_repo`, `routine_generator`, `adherence_calc`.
- **Subtract-only autoregulation** until N≥30 readiness validation passes (PREREQS §C). Add-load SSM (`/life-platform/hevy/autoreg_add_load_enabled`) defaults `false`.
- **Conflict guard:** GET-before-PUT compares `updated_at`; refuses to clobber in-app edits.
- **Hevy API surprises:** no DELETE (archive = rename + folder-move), no webhooks (Phase 2 adherence polls `/v1/workouts/events`), no documented rate limits (client-side ≤1 req/s throttle).

### Reading / Mind Pillar data layer (ADR-097, Phase A)

A new source-of-truth domain (`reading`) on the shared table, using top-level pks (`BOOK#`, `READING#`) rather than the `USER#…#SOURCE#` convention. Data layer in `lambdas/reading/` (`reading_store`, `reading_keys`, `reading_visibility`, `reading_enrich`, `cover_placeholder` — bundled with the `lambdas/` asset, not the shared layer). Two **additive GSIs** (the first on `life-platform`, amending ADR-005): **GSI1** sparse recall-due, **GSI2** reading state/time. Public/private split enforced server-side via the `reading_visibility.project_public` allowlist. All reading records are `CROSS_PHASE` (survive experiment resets).

| Function | Lambda | Trigger |
|---|---|---|
| Cover pipeline | `reading-cover-pipeline` | on-demand (Open Library → Google Books → designed placeholder; caches to `generated/covers/`, never hot-links) |

Later phases (B–E): MCP tools + rules-based recommender, the `/mind/` page, the read→debrief→recall loop, and the Constellation (`docs/specs/CLAUDE_CODE_PROMPT_READING_MIND_v1.md`).

### File-triggered ingestion (S3 → Lambda)

| Source | Lambda | S3 Trigger Path |
|---|---|---|
| MacroFactor | `macrofactor-data-ingestion` | `uploads/macrofactor/*.csv` |
| Apple Health | `apple-health-ingestion` | `imports/apple_health/*.xml` |
| Insight Email | `insight-email-parser` | `raw/inbound_email/*` ObjectCreated |

### Webhook ingestion (API Gateway → Lambda)

| Source | Lambda | Endpoint |
|---|---|---|
| Health Auto Export | `health-auto-export-webhook` | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest` |

### Failure handling

DLQ coverage: all async Lambdas → `life-platform-ingestion-dlq`. CloudWatch: **~50 alarms** total. Alarm actions → SNS `life-platform-alerts`.

Additional safeguards: DLQ Consumer Lambda, Canary Lambda (synthetic health check every 30 min), item size guard.

---

## Store Layer

### DynamoDB — normalised data

Table: `life-platform` (us-west-2) | Single-table | On-demand | Deletion protection | PITR (35-day) | TTL on `ttl`

```
PK: USER#matthew#SOURCE#<source>
SK: DATE#YYYY-MM-DD
```

**Key partitions:** whoop · day_grade · habit_scores · character_sheet · computed_metrics · platform_memory · insights · hypotheses · PROFILE#v1 · CACHE#matthew (TTL 26h)

---

## Serve Layer

### MCP Server

**Lambda:** `life-platform-mcp` | **Tools:** 127 | **Memory:** 768 MB | **Runtime:** python3.12 | **Modules:** 26 (`mcp/tools_*.py` + helpers)
**Remote MCP:** `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/`
**Auth:** OAuth 2.1 auto-approve + HMAC Bearer (remote). Source of truth for tool count: AST parse of top-level `TOOLS` dict keys via `deploy/sync_doc_metadata.py::_auto_discover_tool_count` (see CLAUDE.md — `grep '"name":'` over-counts nested schema fields).

Cold start: ~700–800ms. Warm: 23–30ms. Cached tools: <100ms.

### IC Intelligence Features (16 of 31 live)

Compute → store → read pattern. Standalone Lambdas run before Daily Brief, store results to DynamoDB.

**Live:** IC-1 (anomaly), IC-2 (training load), IC-3 (nutrition), IC-6 (CGM correlation), IC-7 (cross-pillar), IC-8 (intent vs execution), IC-15 (insights persistence), IC-16 (progressive context), IC-17 (readiness synthesis), IC-18 (hypothesis engine), IC-19 (N=1 experiments + slow drift + sustained anomaly), IC-23 (Character Sheet), IC-24 (adaptive mode), IC-25 (decisions), IC-29 (metabolic adaptation / deficit sustainability — TDEE divergence tracking, deployed v3.7.67), IC-30 (autonomic balance score — HRV + RHR + RR + sleep quality → 4-quadrant nervous system state, deployed v3.7.67).

**Data-gated next:** IC-4 (failure patterns, ~Apr 18), IC-5 (momentum warning, ~Apr 18), IC-26 (temporal mining, ~May), IC-27 (multi-resolution handoff, ~May).

### Site API Lambda (us-west-2)

**Lambda:** `life-platform-site-api` | **Stack:** LifePlatformOperational | **Region:** us-west-2 (R17-09 migration)
**Function URL:** Routed through CloudFront (E3S424OXQZ8NBE). Lambda confirmed in us-west-2 (verified via AWS CLI 2026-03-30).
**IAM:** Primarily read-only — `dynamodb:GetItem, Query, PutItem` + `kms:Decrypt` + `s3:GetObject` on `site/config/*`. Limited writes for interactive features (votes, follows, checkins).

**Source layout** (P1.1 Phase B, 2026-05-26 — 85% reduction from original 7,949-line monolith):

| Module | Lines | Owns |
|---|---:|---|
| `lambdas/web/site_api_lambda.py` | 1,216 | `lambda_handler` entry point + `ROUTES`/`_SIMPLE_ROUTES` dispatch + 5 inline coach handlers |
| `lambdas/web/site_api_common.py` | 320 | Shared helpers: `_ok`, `_error`, `_query_source`, `_latest_item`, `_decimal_to_float`, `_load_s3_json`, CORS, request-id state |
| `lambdas/web/site_api_observatory.py` | 1,591 | 14 `/api/*_overview` + meal/strength/journal handlers |
| `lambdas/web/site_api_intelligence.py` | 1,057 | `/api/status` + `/api/pulse` |
| `lambdas/web/site_api_social.py` | 1,168 | 15 subscriber/experiment/challenge/nudge handlers + token-HMAC machinery |
| `lambdas/web/site_api_vitals.py` | 1,086 | 10 homepage/dashboard handlers (vitals, journey, character, achievements, snapshot) |
| `lambdas/web/site_api_data.py` | 1,619 | 19 domain-data handlers (glucose, sleep, habits, correlations, ledger, discoveries, etc.) |

All 7 modules ship together via the standard `Code.from_asset("../lambdas")` zip. `/api/ask` + `/api/board_ask` are served by the separate `life-platform-site-api-ai` Lambda (ADR-036).

**Routes served via CloudFront → site-api:**
- `GET /api/vitals` — weight, HRV, recovery (TTL 300s)
- `GET /api/journey` — weight trajectory, goal date (TTL 3600s)
- `GET /api/character` — pillar scores, level, per-pillar `score_delta`/`xp_earned` (Day-Grade Replay). Reads the **latest available** `character_sheet` `DATE#` record + its prior (compute writes the prior day at ~16:30 UTC, so the freshest record is routinely 1-2 days old; a today/yesterday-only window 503'd ~16h/day — fixed 2026-06-05). TTL 900s.
- `GET /api/source_freshness` — per-source pipeline status (fresh/stale/behavioral-stale/paused), feeds the `/evidence/pipeline/` topic (TTL 300s)
- `GET /api/timeline` — weight history + events
- `GET /api/correlations` — pre-computed correlation pairs
- `GET /api/weight_progress` — 180-day weight series
- `GET /api/experiments` — N=1 experiment list
- `GET /api/current_challenge` — weekly challenge ticker
- `POST /api/ask` — AI Q&A (Haiku 4.5), 3 anon / 20 subscriber q/hr
- `POST /api/board_ask` — 6-persona board AI (Haiku 4.5), 5/hr IP limit
- `GET /api/verify_subscriber?email=` — HMAC token for subscriber gate (24hr)
- `POST /api/subscribe` — email subscriber capture

**Rate limiting:** In-memory sliding window (module-level dicts `_ask_rate_store`, `_board_rate_store`). Vote/follow rate limits use DynamoDB atomic counters with TTL. Role is primarily read-only with limited writes for interactive features (votes, follows, checkins).

### Email / Intelligence cadence

| Lambda | Time (PDT) | Purpose |
|---|---|---|
| `anomaly-detector` | 9:05 AM daily | 15 metrics, CV-based Z thresholds |
| `daily-brief` | 11:00 AM daily | 18-section brief, 4 Haiku calls |
| `monday-compass` | Mon 8:00 AM | Forward-looking planning + Todoist |
| `wednesday-chronicle` | Wed 8:00 AM | Elena Voss narrative, blog + email |
| `weekly-plate` | Fri 7:00 PM | Food magazine column |
| `weekly-digest` | Sun 9:00 AM | 7-day summary, Board commentary |
| `nutrition-review` | Sat 10:00 AM | Deep Sonnet nutrition analysis |
| `hypothesis-engine` | Sun 12:00 PM | IC-18 hypothesis generation |

### Coach Intelligence Layer (v6.0.0)

Eight domain-specific AI coaches generate daily analyses through a multi-stage pipeline. Each coach has a persistent voice, relationship state, and confidence model stored in DynamoDB. The coach pipeline replaces the legacy `ai_expert_analyzer_lambda.py` (deprecated).

**Coaches (8):**

| Coach ID | Name | Domain |
|----------|------|--------|
| `sleep_coach` | Dr. Lisa Park | Sleep & circadian rhythm |
| `nutrition_coach` | Dr. Marcus Webb | Nutrition & metabolism |
| `training_coach` | Dr. Sarah Chen | Training & exercise |
| `mind_coach` | Dr. Nathan Reeves | Mental health & mindfulness |

... [TRUNCATED — 182 lines omitted, 482 total]


---

## 4. INFRASTRUCTURE REFERENCE

# Life Platform — Infrastructure Reference

> Quick-reference for all URLs, IDs, and configuration. No secrets stored here.
> Last updated: 2026-07-06 (v8.6.0 — 93 Lambdas, 9 active secrets, 143 MCP tools, ~110 alarms)

---

## AWS Account

| Field | Value |
|-------|-------|
| Account ID | `205930651321` |
| Region | `us-west-2` (Oregon); us-east-1 for Lambda@Edge + OG image + email-subscriber |
| Budget | $75/month all-in, **enforced** (ADR-063; alerts at 50/70/85/100%; cost-governor degrades AI by tier) |
| CloudTrail | `life-platform-trail` → S3 (data events enabled on `raw/` and `uploads/` S3 prefixes) |
| Account Lambda concurrency quota | **10** (default; raise request filed 2026-05-19, AWS Support case 177921309700709) |

---

## Domain & DNS

| Field | Value |
|-------|-------|
| Domain | `averagejoematt.com` |
| Registrar | *(check where you bought the domain — Namecheap, Google Domains, etc.)* |
| Hosted Zone ID | `Z063312432BPXQH9PVXAI` |
| Nameservers | `ns-214.awsdns-26.com` · `ns-1161.awsdns-17.org` · `ns-858.awsdns-43.net` · `ns-1678.awsdns-17.co.uk` |

### DNS Records

| Subdomain | Type | Target |
|-----------|------|--------|
| `dash.averagejoematt.com` | A (alias) | `d14jnhrgfrte42.cloudfront.net` |
| `blog.averagejoematt.com` | A (alias) | `d1aufb59hb2r1q.cloudfront.net` |
| `buddy.averagejoematt.com` | A (alias) | `d1empeau04e0eg.cloudfront.net` |

---

## Web Properties

| Property | URL | Auth | CloudFront ID |
|----------|-----|------|---------------|
| Public Site | `https://averagejoematt.com/` | None (public) | `E3S424OXQZ8NBE` |
| Dashboard | `https://dash.averagejoematt.com/` | Lambda@Edge password (`life-platform-cf-auth`) | `EM5NPX6NJN095` |
| Blog | `https://blog.averagejoematt.com/` | None (public) | `E1JOC1V6E6DDYI` |
| Buddy Page | `https://buddy.averagejoematt.com/` | None (public — Tom's accountability page, no PII) | `ETTJ44FT0Z4GO` |

Dashboard and Buddy passwords are stored in **Secrets Manager** (not here).

---

## MCP Server

| Field | Value |
|-------|-------|
| Lambda | `life-platform-mcp` (768 MB, python3.12) |
| Function URL (remote) | `https://c5hljblvma4u2xd6wf6oe4clk40unthu.lambda-url.us-west-2.on.aws/` |
| Auth (remote) | OAuth 2.1 auto-approve + HMAC Bearer via `life-platform/mcp-api-key` secret (auto-rotates every 90 days) |
| Auth (local) | `mcp_bridge.py` → `.config.json` → Function URL |
| Tools | **133** across **29** tool modules (`mcp/tools_*.py`) |
| Cache warmer | 14 warm-steps pre-computed nightly (warmer config) |

---

## API Gateway

| Field | Value |
|-------|-------|
| Name | `health-auto-export-api` |
| ID | `a76xwxt2wa` |
| Endpoint | `https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com` |
| Purpose | Webhook ingestion for Health Auto Export (Apple Health CGM, BP, State of Mind) |

---

## S3

| Field | Value |
|-------|-------|
| Bucket | `matthew-life-platform` |
| Default encryption | **AES256** (KMS CMK `5c50ca02-c187-4338-8704-5b27f1efafca` scheduled for deletion 2026-06-16 — bucket reverted to AES256 for CloudFront website-endpoint compatibility, ADR-053/054) |
| Key prefixes | `raw/` (source data) · `site/` (public website — ~72 pages) · `generated/` (Lambda-generated files — public_stats.json, character_stats.json, OG images, journal posts; ADR-046) · `dashboard/` (web dashboard) · `blog/` (Chronicle) · `buddy/` (accountability page) · `config/` (profile, board, character sheet, coaches) · `inbound-email/` (insight parser) · `uploads/` (MacroFactor CSVs) · `imports/` (Apple Health XML) · `avatar/` (pixel art sprites) |

---

## DynamoDB

| Field | Value |
|-------|-------|
| Table | `life-platform` |
| Key schema | PK: `USER#matthew#SOURCE#<source>` · SK: `DATE#YYYY-MM-DD` |
| Protection | Deletion protection ON · PITR enabled (35-day rolling) |
| Encryption | KMS CMK `alias/life-platform-dynamodb` (key `444438d1-a5e0-43b8-9391-3cd2d70dde4d`) · annual auto-rotation ON |
| Partitions (raw + derived) | whoop, eightsleep, garmin, strava, withings, habitify, macrofactor, macrofactor_workouts, apple_health, notion, todoist, weather, supplements, labs, genome, dexa, state_of_mind, food_delivery, measurements, travel · derived: day_grade, habit_scores, character_sheet, adaptive_mode, computed_metrics, platform_memory, insights, hypotheses, decisions, chronicle, coaching_insights, COACH#, ENSEMBLE#, NARRATIVE# |

---

## SES (Email)

| Field | Value |
|-------|-------|
| Sender / Recipient | `awsdev@mattsusername.com` |
| Inbound rule set | `life-platform-inbound` (active) |
| Inbound rule | `insight-capture` → routes `insight@aws.mattsusername.com` → S3 |
| Outbound configuration set | `life-platform-emails` — wired to `daily-brief`, `weekly-digest`, `monthly-digest`, `partner-weekly-email` |

---

## SNS

| Field | Value |
|-------|-------|
| Alert topic | `life-platform-alerts` → email to `awsdev@mattsusername.com` |
| CloudWatch alarms | **~104 metric alarms** (base + invocation-count + DDB item size + canary + duration + freshness + pipeline health) |

---

## SQS

| Field | Value |
|-------|-------|
| Dead-letter queue | `life-platform-ingestion-dlq` |
| DLQ coverage | All ingestion Lambdas (MCP + webhook excluded — request/response pattern) |

---

## ACM Certificates (us-east-1, required by CloudFront)

| Domain | Purpose |
|--------|---------|
| `dash.averagejoematt.com` | Dashboard CloudFront |
| `blog.averagejoematt.com` | Blog CloudFront |
| `buddy.averagejoematt.com` | Buddy CloudFront |

All DNS-validated via Route 53 CNAME records.

---

## Secrets Manager (9 active secrets)

All under prefix `life-platform/`. No values stored in this doc — access via AWS console or CLI.

| Secret | Type | Fields / Notes |
|--------|------|----------------|
| `whoop` | OAuth | Auto-refreshed by Lambda |
| `eightsleep` | OAuth | Auto-refreshed by Lambda |
| `eightsleep-client` | Client credential | Companion to `eightsleep`; required by Eight Sleep API |
| `strava` | OAuth | Auto-refreshed by Lambda |
| `withings` | OAuth | Auto-refreshed by Lambda |
| `garmin` | Session | garth OAuth tokens — auto-refreshed by Lambda |
| `ai-keys` | JSON bundle | `anthropic_api_key` + `mcp_api_key` (90-day auto-rotation) |
| `ingestion-keys` | JSON bundle | `notion_api_key` + `todoist_api_key` + `habitify_api_key` + `dropbox_app_key` + `health_auto_export_api_key`. COST-B pattern — single secret, per-service key fields. Now the **sole** source for Notion + Dropbox creds after the dedicated secrets were soft-deleted 2026-05-17. |
| `habitify` | API key | Dedicated Habitify API token. Also present in `ingestion-keys` — see ADR-014 for governing principle. |
| `todoist` | API key | Todoist API token used by MCP write tools (TD-23). |
| `mcp-api-key` | Rotation target | MCP server bearer token consumed by `ai-keys`. 90-day auto-rotation via `life-platform-key-rotator`. |
| `site-api-ai-key` | API key | Subscriber validation key for site-api-ai Lambda (ADR-041). |

**Soft-deleted (30-day recovery window):**
- `life-platform/notion` — deleted 2026-05-17 (consumer migrated to `ingestion-keys`)
- `life-platform/dropbox` — deleted 2026-05-17 (consumer migrated to `ingestion-keys`)
- `life-platform/anthropic-api-key` — deleted 2026-05-16 (orphan, no consumer)

**Hard-deleted (historical):** `api-keys` (2026-03-14), `webhook-key` (2026-03-14), `google-calendar` (2026-03-15, ADR-030).

---

## Lambdas (73 us-west-2 + 4 us-east-1 = 77 total)

CDK-managed in us-west-2 (73) plus 4 standalone in us-east-1 (Lambda@Edge + OG + email-subscriber).
Source of truth: `aws lambda list-functions --region us-west-2 --query 'length(Functions)'`.

### Ingestion (14)
`whoop-data-ingestion` · `eightsleep-data-ingestion` · `garmin-data-ingestion` · `strava-data-ingestion` · `withings-data-ingestion` · `habitify-data-ingestion` · `macrofactor-data-ingestion` · `notion-journal-ingestion` · `todoist-data-ingestion` · `weather-data-ingestion` · `health-auto-export-webhook` · `apple-health-ingestion` · `dropbox-poll` · `food-delivery-ingestion` · `measurements-ingestion`

> SIMP-2 cohort (8, ADR-056): whoop, garmin, strava, withings, eightsleep, habitify, todoist, weather. Pattern-exempt (6): notion, macrofactor, apple_health, dropbox_poll, food_delivery, measurements (HAE-fed).

### Enrichment / Compute (15)
`journal-enrichment` · `activity-enrichment` · `character-sheet-compute` · `adaptive-mode-compute` · `daily-metrics-compute` · `daily-insight-compute` · `hypothesis-engine` · `weekly-correlation-compute` · `acwr-compute` · `sleep-reconciler` · `circadian-compliance` · `failure-pattern-compute` · `journal-analyzer` · `field-notes-generate` · `weekly-signal`

### Coach Intelligence (8)
`coach-computation-engine` · `coach-narrative-orchestrator` · `coach-quality-gate` (BLOCKING N-06 #390) · `coach-state-updater` · `coach-ensemble-digest` · `coach-prediction-evaluator` · `coach-history-summarizer` · `coach-observatory-renderer` · plus legacy `ai-expert-analyzer` (deprecated, fallback only)

### Email / Digest (11)
`daily-brief` · `weekly-digest` · `monthly-digest` · `nutrition-review` · `wednesday-chronicle` (EventBridge ENABLED) · `chronicle-email-sender` (EventBridge ENABLED) · `weekly-plate` · `monday-compass` · `anomaly-detector` · `evening-nudge` · `partner-weekly-email`

### Infrastructure / Operational (~17)
`life-platform-mcp` · `life-platform-mcp-warmer` · `life-platform-site-api` · `life-platform-site-api-ai` · `site-stats-refresh` · `life-platform-freshness-checker` · `life-platform-key-rotator` · `dashboard-refresh` · `life-platform-data-export` · `life-platform-data-reconciliation` · `life-platform-delete-user-data` · `life-platform-dlq-consumer` · `life-platform-canary` · `life-platform-pip-audit` · `life-platform-qa-smoke` · `life-platform-alert-digest` · `insight-email-parser` · `challenge-generator` · `pipeline-health-check` · `chronicle-approve` · `subscriber-onboarding`

### us-east-1 functions (4)
- `life-platform-cf-auth` (Lambda@Edge) — attached to dashboard CloudFront (`EM5NPX6NJN095`), password-gates `dash.averagejoematt.com`
- `life-platform-buddy-auth` (Lambda@Edge) — function exists; buddy CloudFront currently runs **without auth** (intentionally public; see Web Properties table)
- `life-platform-og-image` — OG image generation (Pillow layer)
- `email-subscriber` — Subscribe form intake

### Layer version distribution (2026-05-19)
- v51: 1 Lambda (deployed during V2 follow-up)
- v50: 56 Lambdas
- None / N/A: 15 Lambdas (Edge functions, HAE webhook, freshness-checker, dlq-consumer, journal-analyzer, pipeline-health-check, data-reconciliation — intentionally no shared layer)
- v2 (Pillow): 1 Lambda (og-image-generator)


... [TRUNCATED — 64 lines omitted, 264 total]


---

## 5. ARCHITECTURE DECISIONS (ADRs)

## ADR Index

| # | Title | Status | Date |
|---|-------|--------|------|
| ADR-001 | Single-table DynamoDB design | ✅ Active | 2026-02-23 |
| ADR-002 | Lambda Function URL over API Gateway for MCP | ✅ Active | 2026-02-23 |
| ADR-003 | MCP over REST API for Claude integration | ✅ Active | 2026-02-24 |
| ADR-004 | Source-of-truth domain ownership model | ✅ Active | 2026-02-25 |
| ADR-005 | No GSI on DynamoDB table | ⚠️ Amended by ADR-097 | 2026-02-25 |
| ADR-006 | DynamoDB on-demand billing over provisioned | ✅ Active | 2026-02-25 |
| ADR-007 | Lambda memory 1024 MB over provisioned concurrency | ✅ Active | 2026-02-26 |
| ADR-008 | No VPC — public Lambda endpoints with auth | ✅ Active | 2026-02-27 |
| ADR-009 | CloudFront + S3 static site over server-rendered dashboard | ✅ Active | 2026-02-27 |
| ADR-010 | Reserved concurrency over WAF | ✅ Active | 2026-02-28 |
| ADR-011 | Whoop as sleep SOT over Eight Sleep | ✅ Active | 2026-03-01 |
| ADR-012 | Board of Directors as S3 config, not code | ✅ Active | 2026-03-01 |
| ADR-013 | Shared Lambda Layer for common modules | ✅ Active | 2026-03-05 |
| ADR-014 | Secrets Manager consolidation — dedicated vs. bundled principle | ✅ Active | 2026-03-05 |
| ADR-015 | Compute→Store→Read pattern for intelligence features | ✅ Active | 2026-03-06 |
| ADR-016 | platform_memory DDB partition over vector store | ✅ Active | 2026-03-07 |
| ADR-017 | No fine-tuning — prompt + context engineering instead | ✅ Active | 2026-03-07 |
| ADR-018 | CDK for IaC over Terraform | ✅ Active | 2026-03-09 |
| ADR-019 | SIMP-2 ingestion framework: adopt for new Lambdas, skip migration of existing | ✅ Active | 2026-03-09 |
| ADR-020 | MCP tool functions BEFORE TOOLS={} dict | ✅ Active | 2026-02-26 |
| ADR-021 | EventBridge rule naming convention (CDK) | ✅ Active | 2026-03-10 |
| ADR-022 | CoreStack scoping — shared infrastructure vs. per-stack resources | ✅ Active | 2026-03-10 |
| ADR-023 | Sick day checker as shared utility, not standalone Lambda | ✅ Active | 2026-03-10 |
| ADR-024 | DLQ consumer: schedule-triggered vs SQS event source mapping | ✅ Active | 2026-03-14 |
| ADR-025 | composite_scores vs computed_metrics: consolidate into computed_metrics | ✅ Active | 2026-03-14 |
| ADR-026 | Local MCP endpoint: AuthType NONE + in-Lambda API key check (accepted) | ✅ Active | 2026-03-14 |
| ADR-027 | MCP two-tier structure: stable core → Layer, volatile tools → Lambda zip | ✅ Active | 2026-03-14 |
| ADR-028 | Integration tests as quality gate: test-in-AWS after every deploy | ✅ Active | 2026-03-14 |
| ADR-029 | MCP monolith: retain single Lambda, revisit at 100+ calls/day | ✅ Active | 2026-03-15 |
| ADR-030 | Google Calendar integration: retired — no viable zero-touch data path | ✅ Active | 2026-03-15 |
| ADR-031 | MCP Lambda deploy: always use full zip build (guard in deploy_lambda.sh) | ✅ Active | 2026-03-15 |
| ADR-032 | S3 bucket policy: Deny DeleteObject on data prefixes for deploy user | ✅ Active | 2026-03-16 |
| ADR-033 | Safe S3 sync: wrapper function with dryrun gate and root-block | ✅ Active | 2026-03-16 |
| ADR-034 | Website content consistency architecture (component system + constants) | ✅ Active | 2026-03-24 |
| ADR-035 | SIMP-1 tool consolidation: view-dispatchers over standalone tools | ✅ Active | 2026-03-09 |
| ADR-036 | 3-layer status monitoring architecture | ✅ Active | 2026-03-29 |
... [SECTION TRUNCATED at 40 lines]

---

## 6. SLOs

# Life Platform — Service Level Objectives (SLOs)

> OBS-3: Formal SLO definitions for critical platform paths.
> Last updated: 2026-07-06 (v8.6.0)

---

## Overview

Four SLOs define the platform's reliability contract. Each SLO has a measurable Service Level Indicator (SLI), a target, and a CloudWatch alarm that fires on breach.

All SLO alarms publish to `life-platform-alerts` SNS topic. The operational dashboard (`life-platform-ops`) includes an SLO tracking widget section.

---

## SLO Definitions

### SLO-1: Daily Brief Delivery

| Field | Value |
|-------|-------|
| **SLI** | Daily Brief Lambda completes without error |
| **Target** | 99% (≤3 missed days per year) |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-daily-brief-delivery` — fires if Daily Brief Lambda errors ≥1 in a 24-hour period |
| **Metric** | `AWS/Lambda::Errors` for `daily-brief`, Sum, 24h period |
| **Recovery** | Check CloudWatch logs → fix code or data issue → re-invoke manually |

**Why 99% not 99.9%:** Single-user platform with no revenue SLA. 99% allows for the occasional bad deploy or upstream API outage without false-alarming. One missed day is annoying, not dangerous.

---

### SLO-2: Data Source Freshness

| Field | Value |
|-------|-------|
| **SLI** | Number of monitored data sources with data older than 48 hours |
| **Target** | 99% of checks show 0 stale sources |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-source-freshness` — fires if `StaleSourceCount > 0` for 2 consecutive checks |
| **Metric** | `LifePlatform/Freshness::StaleSourceCount`, custom metric emitted by `freshness_checker_lambda.py` |
| **Recovery** | Identify stale source → check ingestion Lambda logs → fix auth/API issue → manually invoke |

**Monitored sources (13):** Whoop, Withings, Strava, Todoist, Apple Health, Eight Sleep, MacroFactor, Garmin, Habitify, Notion Journal, Weather, Food Delivery (90-day threshold), Measurements.
**Note:** Labs, DEXA, and Genome are periodic/manual — not subject to 48h freshness SLO. Food Delivery uses a 90-day stale threshold instead of 48h.

**Why 48h threshold:** Many sources only sync once daily. A 24h threshold would false-alarm on normal timezone drift. 48h catches genuine failures while tolerating expected gaps (e.g., no MacroFactor data on a day Matthew doesn't log food).

---

### SLO-3: MCP Availability

| Field | Value |
|-------|-------|
| **SLI** | MCP Lambda invocations that complete without error |
| **Target** | 99.5% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-mcp-availability` — fires if MCP Lambda error rate exceeds 0.5% over 1 hour |
| **Metric** | `AWS/Lambda::Errors` / `AWS/Lambda::Invocations` for `life-platform-mcp` |
| **Recovery** | Check CloudWatch logs → redeploy from last-known-good code |

**Why 99.5%:** MCP is the interactive query layer — errors directly block Claude from answering questions. Higher bar than batch email Lambdas.

**Cold start note:** Cold starts (~700-800ms) are not errors. The SLI measures availability (error-free completion), not latency. A separate informational metric tracks p95 duration.

---

### SLO-4: AI Coaching Success

| Field | Value |
|-------|-------|
| **SLI** | Anthropic API calls that return a valid response |
| **Target** | 99% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-ai-coaching-success` — fires if `AnthropicAPIFailure` count exceeds 2 in a 24-hour period |
| **Metric** | `LifePlatform/AI::AnthropicAPIFailure` (already emitted by `ai_calls.py`) |
| **Recovery** | Check Anthropic status page → if upstream outage, wait. If code issue, fix prompt/parsing |

**Why count-based not rate-based:** The platform makes ~15-20 AI calls/day across all Lambdas. A rate-based alarm with so few datapoints would be noisy. A count threshold of 2 failures/day means something is systematically wrong (not just a transient 429).

---

## CloudWatch Dashboard Widgets

The `life-platform-ops` dashboard includes an "SLO Health" section with:

1. **SLO Status Panel** — 4 metric widgets showing current alarm states
2. **Daily Brief Success Rate** — 30-day graph of daily-brief errors
3. **Source Freshness Trend** — 30-day graph of stale source count
4. **MCP Error Rate** — 7-day graph of MCP error count
5. **AI Failure Trend** — 7-day graph of Anthropic API failures

---

## SLO Review Cadence

- **Weekly:** Glance at ops dashboard SLO section during Weekly Digest review
- **Monthly:** Review any SLO breaches in Monthly Digest (future integration)
- **Quarterly:** Review whether SLO targets need adjustment based on platform growth


... [TRUNCATED — 29 lines omitted, 129 total]


---

## 7. INCIDENT LOG

# Life Platform — Incident Log

Last updated: 2026-07-03 (added the "frozen page" — stale intra-module JS import from mutable-cached assets)

> Tracks operational incidents, outages, and bugs that affected data flow or system behavior.
> For full details on any incident, check the corresponding CHANGELOG entry or handover file.

---

## Severity Levels

| Level | Definition |
|-------|------------|
| **P1 — Critical** | System broken, no data flowing or MCP completely down |
| **P2 — High** | Major feature broken, data loss risk, or multi-day data gap |
| **P3 — Medium** | Single source affected, degraded but functional |
| **P4 — Low** | Cosmetic, minor data quality, or transient error |

---

## Incident History

| Date | Severity | Summary | Root Cause | TTD* | TTR* | Data Loss? |
|------|----------|---------|------------|------|------|------------|
| 2026-07-03 | **P3** | **"Frozen page" — many v5 pages loaded as a static shell only (JS-populated content blank); hard reload fixed it; reproducible after a browser restart.** Reported by the operator with a `/data/` screenshot: the header/title/footer rendered but the tabs, sidebar, and readout (all JS-populated) stayed empty. | `sync_site_to_s3.sh` content-hashed CSS/JS (immutable/1yr) but rewrote references **only in `*.html`** — the ES-module `import ... from "/assets/js/charts.js"` statements *inside* the modules kept pointing at the unhashed, mutable, `max-age=86400` URL. When a deploy changed an entry module AND a dependency together (#260), a returning browser paired a fresh hashed entry module with a stale cached dependency; the ES module graph throws atomically on a mismatched import → nothing executed → only the static shell rendered. Hard reload bypassed the HTTP cache; the stale copy survived a restart (≤24h TTL) so it reproduced. Same *class* as the 2026-03-10 CSS-cache issue ADR-039 addressed, but for the intra-module layer ADR-039's HTML-only rewrite never reached. | Operator report (interactive; freshness/QA checks are server-side and never saw it) | ~2 h — `deploy/hash_site_assets.py` now hashes the **full module graph** (leaves-first) and rewrites HTML + intra-module imports + CSS; deployed + live-verified (all imports hashed/immutable, 0 unhashed refs). ADR-098. | No — cosmetic/availability only; served data unaffected. Self-heals for stuck visitors within ~5 min (their cached HTML expires and points at the all-new hashed graph). |
| 2026-06-28 | **P3** | **coherence-sentinel silently broken — ran "green" off a stale artifact while throwing ImportModuleError.** A `cdk deploy` shipped the Sentinel a Lambda zip of only 2 entries (`operational/*`, **no root `lambdas/*.py`**), so it failed at cold start with `No module named 'coherence_invariants'`. The invoke still returned StatusCode 200 (handler re-raises → FunctionError payload with `errorMessage`, no `body`), and the last good `coherence-log/latest.json` made it look healthy. Detected when the new postflight asset-completeness check (#258) flagged it. **Reproducible** — recurred twice on routine redeploys this session. | CDK skips re-uploading an asset whose content-hash key already exists in the S3 assets bucket, so a corrupt `<hash>.zip` poisons every Lambda referencing that hash. `cdk deploy` reports "(no changes)" and `--force` won't re-upload; `rm -rf cdk.out` alone may resynthesize the same hash. Same *class* as the 2026-03-09 P2 (`Code.from_asset` subdir/ImportModuleError), different mechanism (S3 hash-skip caching). | Same-session (postflight check caught it; a 200 invoke had masked it) | ~5 min — pushed the correct asset via `aws lambda update-function-code --s3-bucket cdk-hnb659fds-assets-… --s3-key <hash>.zip` (a re-publish from another stack on the same hash had already overwritten the corrupt S3 object). | No — detection-only Lambda; the served data was unaffected, but coherence monitoring was blind for ~40 min. **Prevention:** `session_postflight.check_asset_completeness()` now downloads each bundled-asset canary's zip and asserts its imported root modules are present. See `reference_cdk_asset_staging_glitch`. |
| 2026-04-05 → 2026-05-19 | **P2** | **Garmin OAuth outage — ~44-day data gap.** Garmin OAuth1 token expired ~April 5 (pre-existing 30-day lifetime) during a platform-low-activity window; cron retries hit Garmin rate limits (429s) and the `auth_breaker` (added P2.4) tripped, halting attempts. Discovered during V2 audit when `life-platform-garmin-data-ingestion-errors` was found in ALARM. | OAuth1 expiry compounded by lack of pre-silence rule-disable. The auth_breaker correctly prevented log/quota spam during the outage, but no escalation surfaced the failure beyond CloudWatch ALARM. | ~44 days (alarm fired continuously, no inbox follow-through) | ~30 min (re-auth via `setup/setup_garmin_browser_auth.py` Playwright/Chromium flow; manual `clear_failure()` on auth_breaker DDB marker; first successful invocation 2026-05-19). Gap-fill will recover all DDB records over next 24h. | Data loss only during silence window; raw Garmin data not retained server-side beyond device sync history. Daily steps/sleep/HR for the gap may be partially recoverable from Garmin Connect UI export. |
| 2026-05-17 | **P2** | **V2 SES IAM regression — daily-brief delivery briefly failed AccessDenied.** During V2 P2 IAM tightening, `ses:SendEmail` was restricted to the identity ARN but the configuration-set ARN was dropped from the policy. SES requires permission on BOTH ARNs when emails are sent through a config set. Daily-brief delivery failed with `AccessDenied`. | Incomplete IAM resource list in `role_policies.py` for SES — single-ARN pattern doesn't suffice when a configuration set is involved (event tracking / dimension tagging requires the config-set resource grant). | Manual smoke check during V2 P2 verification (~minutes) | ~10 min (added config-set ARN to policy Resource list, redeployed EmailStack). Daily-brief resent successfully. | No — same-day fix; one delivery deferred. |
| 2026-03-16 | **P1** | **S3 bucket wipe — 35,188 objects deleted across all prefixes.** Deploy script `deploy_v3756_restore_signal_homepage.sh` ran `aws s3 sync --delete` from 17-file website dir to bucket root, deleting entire raw data archive (34,221 files, 2009–2026), config (24), deploys (25), dashboard (56), CloudTrail (753), exports (24), uploads/macrofactor (26), and 7 other prefixes. DynamoDB untouched. | One-off deploy script synced to `s3://$BUCKET/` (bucket root) instead of `s3://$BUCKET/site/`. The `--delete` flag treated all non-website objects as orphans. Canonical `sync_site_to_s3.sh` correctly uses `S3_PREFIX="site"` — the one-off script bypassed this. | Immediate (operator noticed deletions streaming in terminal) | ~2 hours. Full recovery via S3 versioning — delete markers removed with batch Python script. All 35,273 objects confirmed restored. | **No — full recovery.** S3 versioning was enabled pre-incident. All objects recovered by removing delete markers. Verified: `raw/` = 34,222, all other prefixes match forensic counts. |
| 2026-03-19 | **P2** | Eight Sleep data ingestion down for 10 days | `logger.set_date` crash — Lambda had stale bundled `platform_logger.py` missing `set_date()` method. Same class of bug as 2026-03-09 P2 incident but on a Lambda not redeployed in v3.3.8 batch fix. | 10 days (discovered during pipeline validation session) | ~30 min (hasattr guard + redeploy + re-auth after password change). 7 days backfilled. | No — backfill recovered missing data |
| 2026-03-19 | **P2** | Dropbox secret deleted — MacroFactor nutrition chain silently broken since Mar 10 | Secret `life-platform/ingestion-keys` scheduled for deletion (7-day recovery window expired). Dropbox poll Lambda couldn't read credentials → MacroFactor CSV never downloaded → nutrition data stopped. Undetected 9 days. | 9 days (discovered during pipeline validation session) | ~15 min (restored secret from deletion recovery) | No — MacroFactor data backfilled after restore |
| 2026-03-19 | **P3** | Notion secret deleted — journal ingestion silently broken | Same pattern as Dropbox: secret scheduled for deletion and not caught. Notion journal entries stopped ingesting. | Days (discovered during pipeline validation) | ~10 min (restored secret) | No — re-ingested after restore |
| 2026-03-19 | **P3** | Health Auto Export webhook Lambda crash | `logger.set_date` bug — same root cause as Eight Sleep. Lambda redeployed with stale platform_logger.py. | Days (discovered during pipeline validation) | ~15 min (redeploy with current code) | No — webhook data in S3, reprocessed |
| 2026-03-19 | **P3** | Garmin ingestion broken — missing modules + expired tokens | garth/garminconnect modules missing from Lambda package. OAuth tokens expired. | Days (discovered during pipeline validation) | Resolved 2026-04-05: garth-layer attached via CDK, re-authed, 4 days backfilled. Added OAuth resilience (proactive refresh, circuit breaker). | No — gap-fill recovered all data |
| 2026-03-12 | **P3** | Mar 12 alarm storm — 20+ ALARM/OK emails in 24h across todoist, daily-insight-compute, failure-pattern-compute, monday-compass, DLQ, freshness | CDK drift: `TodoistIngestionRole` missing `s3:PutObject` on `raw/todoist/*`. Policy correct in `role_policies.py` but never applied to AWS (likely stale from COST-B bundling refactor). Todoist Lambda threw `AccessDenied` on every invocation → cascading staleness alarms. | Alarm emails (real-time) | ~1 day (detected next session) — `cdk deploy LifePlatformIngestion` (54s) | No — Todoist data gap Mar 12 only. No backfill attempted (single day, non-critical). |
| 2026-03-12 | **P4** | `freshness_checker_lambda.py` duplicate sick-day suppression block silently breaking sick-day alert suppression | Copy-paste bug: sick-day block duplicated, second copy reset `_sick_suppress = False` after first set it `True`. Suppression never fired on sick days. | Code review during incident investigation | Fixed in v3.7.10 — awaiting deploy |
| 2026-02-28 | **P1** | 5 of 6 API ingestion Lambdas failing after engineering hardening (v2.43.0) | Handler mismatches (4 Lambdas had `lambda_function.py` but handlers pointed to `X_lambda.lambda_handler`), Garmin missing deps + IAM, Withings cascading OAuth expiry | ~hours (next scheduled run) | ~2 hr (sequential fixes) | No — gap-aware backfill self-healed all missing data. Full PIR: `docs/PIR-2026-02-28-ingestion-outage.md` |
| 2026-03-04 | P3 | character-sheet-compute failing with AccessDenied on S3 + DynamoDB | IAM role missing s3:GetObject on config bucket and dynamodb:PutItem permission. Lambda silently failing since deployment | ~1 day | 30 min | No (compute re-run via backfill) |
| 2026-02-25 | P4 | Day grade zero-score — journal and hydration dragging grades down | `score_journal` returned 0 instead of None when no entries; hydration noise <118ml scored | 1 day | 20 min | No (grades recalculated) |
| 2026-02-25 | P3 | Strava multi-device duplicate activities inflating movement score | WHOOP + Garmin recording same walk → duplicate in Strava | ~days | 30 min | No (dedup applied in brief; raw data retained) |
| 2026-03-10 | **P2** | All three web URLs (dash/blog/buddy) showing TLS cert error — `ERR_CERT_COMMON_NAME_INVALID` | `web_stack.py` had `CERT_ARN_* = None` placeholders — CDK deployed distributions without `viewer_certificate`, causing CloudFront to serve default `*.cloudfront.net` cert. Introduced during PROD-1 (v3.3.5). | Hours (noticed by user) | 15 min (v3.4.9) | No (data unaffected; all URLs inaccessible via HTTPS) |
| 2026-03-08 | **P3** | `todoist-data-ingestion` failing since 2026-03-06 | Stale `SECRET_NAME` env var (`life-platform/api-keys`) set on the Lambda — when api-keys was soft-deleted as part of secrets decomposition, the env var override started producing `ResourceNotFoundException`. Code default was correct but env var took precedence. DLQ consumer caught accumulated failures at 9:15 AM on 2026-03-08. | ~2 days | 15 min (env var removed + Lambda redeployed) | No — Todoist ingestion gap 2026-03-06 to 2026-03-08. Gap-aware backfill (7-day lookback) self-healed all missing task records on next run. |
| 2026-03-08 | **Info** | `data-reconciliation` first run reported RED: 17 gaps across 6 sources | Bootstrap noise, not real failures. First run has no prior reference point — all "gaps" were expected coldstart artifacts (MacroFactor real data only from 2026-02-22, habit gap 2025-11-10→2026-02-22, etc.). | First run | No action needed — monitor next 3 runs for convergence to GREEN | No |
| 2026-03-09 | **P2** | All 23 CDK-managed Lambdas broken after first CDK deploy (PROD-1, v3.3.5) | `Code.from_asset("..")` bundles files at `lambdas/X.py` inside a subdirectory, but Lambda expects `X.py` at zip root — causing `ImportModuleError` on every invocation. Affected: 7 Compute + 8 Email + 1 MCP + 7 Operational Lambdas. | Next scheduled run post-deploy | ~1 hr (`deploy/redeploy_all_cdk_lambdas.sh` redeployed all 23 via `deploy_lambda.sh`) | No — gap-aware backfill + DLQ drained. Permanent fix: update `lambda_helpers.py` to `Code.from_asset("../lambdas")` (tracked as TODO) |
| 2026-03-10 | **P1** | CDK IAM bulk migration — Lambda execution role gap during v3.4.0 deploy | CDK deleted 39 old IAM roles before confirming CDK-managed replacement roles were fully propagated and attached. Two email Lambdas (`wednesday-chronicle`, `nutrition-review`) had no execution role for ~5 min during the migration window, causing invocation failures on any warmup or invocation in that window. Root fix: `cdk deploy` sequencing — always verify role attachment before deleting old roles. *Identified retroactively during Architecture Review #4.* | Deploy logs (real-time) | ~15 min (CDK re-apply with `--force`) | No — no scheduled runs in migration window |
| 2026-03-10 | **P2** | CoreStack SQS DLQ ARN changed on CDK-managed recreation — DLQ send failures across all async Lambdas | CoreStack created a new CDK-managed DLQ (`life-platform-ingestion-dlq`) with a different ARN than the manually-created original. CDK-deployed Lambda env vars referenced the new ARN, but 3 Lambdas that had the old ARN cached in env var overrides (`SECRET_NAME`-style pattern) continued sending to the deleted queue. Result: DLQ send failures and silent dead-letter drop for ~30 min. *Identified retroactively during Architecture Review #4.* | CloudWatch errors (~30 min lag) | CDK update pushed correct ARN to all Lambda configs | Possible: some DLQ messages lost during gap window |
| 2026-03-10 | **P3** | EB rule recreation gap: 2 ingestion Lambdas missed scheduled morning runs during v3.4.0 migration | Old EventBridge rules deleted first; CDK replacements deployed after. 2 ingestion Lambdas (`withings-data-ingestion`, `eightsleep-data-ingestion`) missed their 7:15 AM / 8:00 AM PT windows during ~10 min gap between deletion and CDK rule creation. *Identified retroactively during Architecture Review #4.* | Freshness checker alert (10:45 AM) | Gap-aware backfill self-healed on next scheduled run | No — backfill recovered all missing data |
| 2026-03-10 | **P3** | Orphan Lambda adoption: `failure-pattern-compute` Sunday EB rule not included in CDK Compute stack definition | When 3 orphan Lambdas were adopted into CDK (v3.4.0), the `failure-pattern-compute` Sunday 9:50 AM EventBridge rule was omitted from the Compute stack definition. Lambda did not execute for ~1 week (one missed Sunday run). *Identified retroactively during Architecture Review #4.* | Architecture Review #4 inspection | EB rule added to CDK Compute stack | No — failure pattern memory records simply not generated for that week |
| 2026-03-10 | **P4** | Duplicate CloudWatch alarms after CDK Monitoring stack adoption of orphan Lambdas | CDK Monitoring stack created new alarms for 3 newly-adopted Lambdas (`failure-pattern-compute`, `partner-email`, `sick-day-checker`) that already had manually-created alarms — resulting in 9 duplicate alarms with overlapping SNS notifications and alert fatigue. *Identified retroactively during Architecture Review #4.* | Architecture Review #4 alarm audit | Manual alarms deleted; CDK alarms authoritative | No |
| 2026-03-09 | **P2** | All 13 ingestion Lambdas failing with `AttributeError: 'Logger' object has no attribute 'set_date'` | After `platform_logger.py` added `set_date()` to support OBS-1 structured logging, ingestion Lambdas had stale bundled copies of `platform_logger.py` missing the new method. 14 DLQ messages accumulated. Affected: whoop, eightsleep, withings, strava, todoist, macrofactor, garmin, habitify, notion, journal-enrichment, dropbox-poll, weather, activity-enrichment. | DLQ depth alarm + CloudWatch errors | ~30 min (`deploy/redeploy_ingestion_with_logger.sh` redeployed all 13 with `--extra-files lambdas/platform_logger.py`). DLQ purged in v3.3.8. | No — gap-aware backfill recovered all ingestion gaps. |
| 2026-02-25 | P4 | Daily brief IAM — day grade PutItem AccessDeniedException | `lambda-weekly-digest-role` missing `dynamodb:PutItem` | Since v2.20.0 | 10 min | Grades not persisted until fixed |
| 2026-02-24 | P2 | Apple Health data not flowing — 2+ day gap | Investigated wrong Lambda (`apple-health-ingestion` vs `health-auto-export-webhook`) + deployment timing | ~2 days | 4 hr investigation, 15 min actual fix | No (S3 archives preserved, backfill recovered) |
| 2026-02-24 | P3 | Garmin Lambda pydantic_core binary mismatch | Wrong platform binary in deployment package | 1 day | 30 min | No |
| 2026-02-24 | P3 | Garmin data gap (Jan 19 – Feb 23) | Garmin app sync issue (Battery Saver mode suspected) | ~5 weeks | Backfill script | Partial (gap backfilled from Feb 23 forward) |
| 2026-02-23 | P4 | Habitify alarm in ALARM state | Transient Lambda networking error ("Cannot assign requested address") | Hours | Manual alarm reset | No (re-invoked successfully) |
| 2026-02-23 | P4 | DynamoDB TTL field name mismatch | Cache using `ttl_epoch` but TTL configured on `ttl` attribute | ~1 day | 5 min | No (cache items never expired, just accumulated) |
| 2026-02-23 | P4 | Weight projection sign error in weekly digest | Delta calculation reversed (showing gain as loss) | 1 day | 5 min | No |
| 2026-02-23 | P4 | MacroFactor hit rate denominator off | Division denominator using wrong field | 1 day | 5 min | No |
| 2026-03-11 | **P2** | Partner email failing on all deploys since v3.5.1 | Two compounding bugs: (1) `deploy_obs1_ai3_apikeys.sh` used inline `zip` with path prefix — Lambda package contained `lambdas/partner_email_lambda.py` at a subdirectory rather than root, causing `ImportModuleError` on every invocation; (2) `EmailStack` in CDK had no layer reference — all 8 email Lambdas silently running on `life-platform-shared-utils:2` (missing `set_date` method added in v4). Root principle violation: deploy scripts must always delegate to `deploy_lambda.sh` (which strips path via temp dir); never inline zip logic. | Manual test during v3.5.4 session | ~30 min (v3.5.5): fixed zip via `deploy_lambda.sh` re-deploy; added `SHARED_LAYER_ARN` + layer reference to all 8 email Lambdas in `email_stack.py`; `npx cdk deploy LifePlatformEmail` to apply | No — no Partner emails sent since initial deploy; email content unaffected once fixed |
| 2026-03-11 | P3 | All 8 email Lambdas on stale layer v2 (missing `set_date`) since EmailStack CDK migration | EmailStack created in PROD-1 (v3.3.5) with no `layers=` parameter — all email Lambdas referenced zero layers and fell back to stale bundled copies of shared modules. `set_date()` method (added in platform_logger v2 for OBS-1 structured logging) was unavailable, causing silent `AttributeError` risk on any email Lambda that called it. No confirmed runtime failures because email Lambdas that bundled their own logger copy used the older API. Discovered during Partner email debug. | Discovered during v3.5.5 investigation | Fixed in v3.5.5 via EmailStack CDK layer patch | No confirmed impact — no `set_date` calls confirmed in email Lambdas prior to v3.5.5 fix |

*TTD = Time to Detect, TTR = Time to Resolve

---

## Patterns & Observations

**Most common root causes:**
1. **Deployment errors** (wrong function ordering, missing IAM, wrong binary, CDK packaging, inline zip path prefix, **S3 sync to wrong target**) — 9 incidents
2. **CDK drift** (IAM policies correct in code but not applied to AWS) — 3 incidents (Mar 12 Todoist, Mar 04 character-sheet, Mar 09 CDK packaging)
3. **Stale config / env var overrides** (SECRET_NAME env var pointing at deleted secret) — 3 incidents
4. **Silent secret deletion** — Secrets Manager 7-day deletion recovery window expired unnoticed. Two secrets (Dropbox/ingestion-keys, Notion) were scheduled for deletion and expired without any Lambda failing loudly. **Mitigation deployed:** `pipeline-health-check` Lambda (v4.4.0) probes all 11 secrets daily at 6 AM PT. — 2 incidents
5. **Stale Lambda module caches** — Lambda packages with bundled copies of shared modules (platform_logger.py) missing new methods. The v3.3.8 batch fix redeployed 13 ingestion Lambdas but missed Eight Sleep and Health Auto Export. Root fix: `hasattr(logger, 'set_date')` guard added to all 14 Lambdas. — 3 incidents (Mar 9, Mar 19 Eight Sleep, Mar 19 HAE)
6. **Wrong component investigated** (two Apple Health Lambdas, alarm dimension mismatch) — 3 incidents
7. **Missing infrastructure** (EventBridge rule never created, IAM missing permission, CDK stack missing layer reference) — 3 incidents
8. **Data quality / scoring logic** (zero-score defaults, dedup, sign errors) — 4 incidents
9. **One-off deploy scripts bypassing canonical tooling** — 2 incidents (Mar 11 Partner email inline zip, **Mar 16 S3 bucket wipe**)

**S3 sync --delete watch-out (ADR-032/033, v3.7.57):** `aws s3 sync --delete` to the bucket root will delete every object not in the source directory. This is the most destructive single command in the platform. **Hardening applied:**
1. S3 bucket policy denies `s3:DeleteObject` on `raw/`, `config/`, `uploads/`, `dashboard/`, `exports/`, `deploys/`, `cloudtrail/`, `imports/` for `matthew-admin` — deploy scripts physically cannot delete data files.
2. `deploy/lib/safe_sync.sh` wrapper blocks syncs to bucket root and aborts if dryrun shows >100 deletions.
3. S3 versioning enabled — delete markers are recoverable.
4. One-off deploy scripts are prohibited. All site deploys use `sync_site_to_s3.sh` with `S3_PREFIX="site"`.

**One-off deploy script watch-out (new pattern as of v3.7.57):** One-off scripts (`deploy_vXXXX_do_thing.sh`) bypass the safety patterns built into canonical tooling. Two separate P1/P2 incidents traced to one-off scripts that didn't use `deploy_lambda.sh` or `sync_site_to_s3.sh`. **Rule: no one-off deploy scripts.** Use canonical scripts with flags/arguments, or modify the canonical script temporarily.

**CDK drift watch-out (new pattern as of v3.7.10):** IAM policy changes in `role_policies.py` only take effect when the relevant stack is deployed. After any refactor touching role policies (secrets consolidation, prefix changes, etc.), always redeploy the affected stack immediately and verify with a smoke invoke. Do not assume CDK state matches AWS state without a deploy.

**MCP Lambda deploy watch-out (ADR-031, v3.7.47):** `deploy_lambda.sh life-platform-mcp` strips the `mcp/` package — the Lambda boots clean but routes everything through the bridge handler (401 on all requests). Always use the full zip build for MCP:
```bash
ZIP=/tmp/mcp_deploy.zip && rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```
`deploy_lambda.sh` now hard-rejects `life-platform-mcp` with a clear error. Symptom: `{"error": "Unauthorized"}` from OAuth endpoints; Lambda logs show clean START/END with no errors (misleading).

**CDK packaging watch-out:** `Code.from_asset("..")` bundles source files one directory deep in the zip — Lambda can't find the handler. Always use `Code.from_asset("../lambdas")` (points at the lambdas directory directly). When CDK-managing Lambdas for the first time, verify a sample function works before assuming all 23 are healthy. `deploy_lambda.sh` is immune to this bug.

**Stale lambda module caches:** When a shared module (like `platform_logger.py`) adds new methods, all Lambdas that bundle their own copy of that file need to be redeployed. CDK packaging re-bundles from source automatically; `deploy_lambda.sh --extra-files` is the manual equivalent for Lambdas not yet on CDK.

**Secrets consolidation watch-out:** When consolidating Secrets Manager entries, Lambdas with `SECRET_NAME` (or similar) set as explicit env vars will override code defaults and continue pointing at the deleted secret. Always audit Lambda env vars — not just code — when retiring secrets. Also verify key naming conventions match between old and new secret schemas.

**Key lesson (from RCA):** When data isn't flowing, check YOUR pipeline first (CloudWatch logs for the receiving Lambda), not the external dependency. Document the full request path so you investigate the right component.

---

## Open Monitoring Gaps

| Gap | Risk | Mitigation |
|-----|------|------------|
| No end-to-end data flow dashboard | Slow detection of silent failures | Freshness checker provides daily coverage |
| DLQ coverage: MCP + webhook excluded | Request/response pattern — DLQ not applicable | CloudWatch error alarms cover both |
| No webhook health check endpoint | Can't externally monitor webhook availability | CloudWatch alarm on zero invocations/24h |
| ~~No duration/throttle alarms~~ | ~~Timeouts without errors go undetected~~ | **Resolved v3.7.36** — duration alarms deployed for all Lambdas |
| ~~No CDK drift detection~~ | ~~IAM policy changes in code may not be applied to AWS~~ | **Resolved v3.7.36** — `cdk diff` step added to ci-cd.yml; post-refactor deploy + smoke verify documented in RUNBOOK.md |

**Resolved gaps (v2.75.0):** All 29 Lambdas now have CloudWatch error alarms. 10 log groups now have 30-day retention. Deployment zip filename bug eliminated by `deploy_lambda.sh` auto-reading handler config from AWS.

**Resolved gaps (v3.1.x):** DLQ consumer Lambda (`dlq-consumer`) now drains and logs failures from `life-platform-ingestion-dlq` on a schedule — silent DLQ accumulation is now caught proactively. Canary Lambda (`life-platform-canary`) runs synthetic DDB+S3+MCP round-trip every 30 min with 4 CloudWatch alarms — end-to-end health check is now automated. `item_size_guard.py` monitors 400KB DDB write limits before they cause failures.

**Open gap (V2 audit 2026-05-19):** Long-running ALARM-state alarms (e.g., Garmin errors for 44 days) need an escalation path beyond email — the inbox volume normalized the noise. V2 P6 follow-up: consider digest summary of alarms in continuous-ALARM state >7 days.

---

**Verified:** 2026-05-19 (V2 audit operational sweep)


---

## 8. INTELLIGENCE LAYER

[ERROR reading /Users/matthewwalker/Documents/Claude/life-platform/docs/INTELLIGENCE_LAYER.md: [Errno 2] No such file or directory: '/Users/matthewwalker/Documents/Claude/life-platform/docs/INTELLIGENCE_LAYER.md']


---

## 9. TIER 8 HARDENING STATUS

[Tier 8 section not found in PROJECT_PLAN.md]


---

## 10. CDK / IaC STATE

### cdk/app.py
```python

#!/usr/bin/env python3
"""
Life Platform CDK App — PROD-1: Infrastructure as Code

Stack architecture:
  core        → DynamoDB, S3, SQS DLQ, SNS alerts (imported existing resources)
  ingestion   → 13 ingestion Lambdas + EventBridge rules + IAM roles
  compute     → 5 compute Lambdas + EventBridge rules
  email       → 8 email/digest Lambdas + EventBridge rules
  operational → Operational Lambdas (anomaly, freshness, canary, dlq-consumer, etc.)
  mcp         → MCP Lambda + Function URLs (local + remote)
  web         → CloudFront (3 distributions) + ACM certificates
  monitoring  → CloudWatch alarms + ops dashboard + SLO alarms

Deployment:
  cdk bootstrap aws://205930651321/us-west-2
  cdk deploy LifePlatformCore
  cdk deploy LifePlatformIngestion
  cdk deploy LifePlatformCompute
  cdk deploy LifePlatformEmail
  cdk deploy LifePlatformOperational
  cdk deploy LifePlatformMcp
  cdk deploy LifePlatformWeb         # requires us-east-1 cert ARNs
  cdk deploy LifePlatformMonitoring

To import existing resources (first time only):
  cdk import LifePlatformCore
"""

import aws_cdk as cdk
from stacks.compute_stack import ComputeStack
from stacks.core_stack import CoreStack
from stacks.email_stack import EmailStack
from stacks.ingestion_stack import IngestionStack
from stacks.mcp_stack import McpStack
from stacks.monitoring_stack import MonitoringStack
from stacks.operational_stack import OperationalStack
from stacks.web_stack import WebStack

app = cdk.App()

# Read context values
account = app.node.try_get_context("account") or "205930651321"
region = app.node.try_get_context("region") or "us-west-2"

env = cdk.Environment(account=account, region=region)

# ── Cost-allocation / governance tags (applied to every taggable resource in
# every stack). Activate as cost-allocation tags in Billing console once to slice
# spend by Project/Env/Owner. (A-grade review: closes the "no resource tags" gap.)
cdk.Tags.of(app).add("Project", "life-platform")
cdk.Tags.of(app).add("Env", "prod")
cdk.Tags.of(app).add("Owner", "matthew")
cdk.Tags.of(app).add("ManagedBy", "cdk")

# ── Core infrastructure (DynamoDB, S3, SQS, SNS) ──
core = CoreStack(app, "LifePlatformCore", env=env)

# ── All 8 stacks wired ──
# Each stack receives core.table, core.bucket, core.dlq, core.alerts_topic
# as cross-stack references.
#
ingestion = IngestionStack(
    app,
    "LifePlatformIngestion",
    env=env,
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    digest_topic=core.digest_topic,
)
# ingestion stack wired ✅
#
compute = ComputeStack(
    app,
    "LifePlatformCompute",
    env=env,
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    digest_topic=core.digest_topic,
)
# compute stack wired ✅
#
email = EmailStack(
    app,
    "LifePlatformEmail",
    env=env,
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    digest_topic=core.digest_topic,
)
# email stack wired ✅
#
operational = OperationalStack(
    app,
    "LifePlatformOperational",
    env=env,
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    digest_topic=core.digest_topic,
)
# operational stack wired ✅
#
mcp = McpStack(app, "LifePlatformMcp", env=env, table=core.table, bucket=core.bucket)
# mcp stack wired ✅
#
web = WebStack(app, "LifePlatformWeb", env=cdk.Environment(account=account, region="us-east-1"))  # CloudFront requires us-east-1
# web stack wired ✅
#
monitoring = MonitoringStack(app, "LifePlatformMonitoring", env=env, alerts_topic=core.alerts_topic, digest_topic=core.digest_topic)
# monitoring stack wired ✅

app.synth()

```


### cdk/stacks/lambda_helpers.py (first 80 lines)
```python

"""
lambda_helpers.py — Shared Lambda construction patterns for CDK stacks.

Provides a helper function that creates a Lambda function with all the
standard Life Platform conventions:
  - Per-function IAM role with explicit least-privilege policies
  - DLQ configured
  - Environment variables (TABLE_NAME, S3_BUCKET, USER_ID)
  - CloudWatch error alarm
  - Handler auto-detection from source file
  - Shared Layer attachment (optional)

v2.0 (v3.4.0): Added custom_policies parameter to replace existing_role_arn.
  CDK now OWNS all IAM roles — no more from_role_arn references.
  Migration: existing_role_arn is DEPRECATED and will be removed in a future version.

Usage in a stack:
    from stacks.lambda_helpers import create_platform_lambda
    from stacks.role_policies import ingestion_policies

    fn = create_platform_lambda(
        self, "WhoopIngestion",
        function_name="whoop-data-ingestion",
        source_file="lambdas/ingestion/whoop_lambda.py",
        handler="ingestion.whoop_lambda.lambda_handler",
        table=core.table,
        bucket=core.bucket,
        dlq=core.dlq,
        custom_policies=ingestion_policies("whoop"),
        schedule="cron(0 14 * * ? *)",
        timeout_seconds=120,
    )
"""

from aws_cdk import (
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct


def create_platform_lambda(
    scope: Construct,
    id: str,
    function_name: str,
    source_file: str,
    handler: str,
    table: dynamodb.ITable,
    bucket: s3.IBucket,
    dlq: sqs.IQueue = None,
    alerts_topic: sns.ITopic = None,
    digest_topic: sns.ITopic = None,
    digest: bool = False,
    alarm_name: str = None,
    secrets: list[str] = None,
    schedule: str = None,
    timeout_seconds: int = 120,
    memory_mb: int = 256,
    environment: dict = None,
    shared_layer: _lambda.ILayerVersion = None,
    additional_layers: list = None,
    # ── Legacy parameter (DEPRECATED — use custom_policies instead) ──
    existing_role_arn: str = None,
    # ── Fine-grained IAM (v2.0) ──
    custom_policies: list[iam.PolicyStatement] = None,
    # ── Legacy broad-permission flags (used when neither existing_role_arn nor custom_policies) ──
    ddb_write: bool = True,
    s3_write: bool = True,
    needs_ses: bool = False,
    ses_domain: str = None,

... [TRUNCATED — 244 lines omitted, 324 total]

```


### cdk/stacks/role_policies.py (first 80 lines)
```python

"""
role_policies.py — Centralized IAM policy definitions for all Life Platform Lambdas.

Each function returns a list of iam.PolicyStatement objects that exactly
replicate the existing console-created per-function IAM roles from SEC-1.

Audit source: aws iam get-role-policy on all 37 lambda-* roles (2026-03-09).
Organized by CDK stack: ingestion, compute, email, operational, mcp.

Policy principle: least-privilege per Lambda. No shared roles.
"""

from aws_cdk import aws_iam as iam

from stacks.constants import ACCT, CF_DIST_ID, KMS_KEY_ID, REGION, S3_BUCKET, SES_DOMAIN, TABLE_NAME  # CONF-01, SEC-06, SEC-08

# ── Constants ──────────────────────────────────────────────────────────────
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCT}:table/{TABLE_NAME}"
BUCKET = S3_BUCKET
CF_DIST_ARN = f"arn:aws:cloudfront::{ACCT}:distribution/{CF_DIST_ID}"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
DLQ_ARN = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-ingestion-dlq"
KMS_KEY_ARN = f"arn:aws:kms:{REGION}:{ACCT}:key/{KMS_KEY_ID}"
# Phase 2.4 (2026-05-16): dedicated CMK for S3 default encryption.
# IMPORTANT: must reference by key ID ARN (not alias) — IAM does not resolve
# alias ARNs in resource policies. Key is created in CoreStack (`s3_kms_key`).
# Roles need encrypt/decrypt on it to write/read KMS-encrypted objects.
# S3_KMS_KEY_ARN removed 2026-05-24 — orphan reference; bucket uses AES256, key
# scheduled for deletion 2026-06-16. See BACKLOG.md follow-up.
SES_IDENTITY = f"arn:aws:ses:{REGION}:{ACCT}:identity/{SES_DOMAIN}"  # SEC-08: domain from constants
# V2 P1.6 follow-up (2026-05-19): SES requires send permission on BOTH the
# identity AND the configuration-set when SendEmail includes ConfigurationSetName.
# Missing this caused daily-brief AccessDeniedException for 2 days post-P1.6.
SES_CONFIG_SET_ARN = f"arn:aws:ses:{REGION}:{ACCT}:configuration-set/life-platform-emails"


def _secret_arn(name: str) -> str:
    """Secrets Manager ARN with wildcard suffix for version IDs."""
    return f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:{name}*"


def _s3(*prefixes: str) -> list[str]:
    """S3 object ARNs for the given key prefixes."""
    return [f"{BUCKET_ARN}/{p}" for p in prefixes]


def _bedrock_statement() -> iam.PolicyStatement:
    """ADR-062 (2026-05-27): bedrock:InvokeModel for Claude inference.

    Migration from direct Anthropic API → Bedrock. Granted to every AI-calling
    role (anywhere ai-keys was previously granted). Scoped to Anthropic Claude
    only — both the cross-region inference profiles (`us.anthropic.claude-*`,
    which on-demand 4.x models require) AND the underlying foundation-model
    ARNs the profiles fan out to (InvokeModel is authorized against both).
    Region wildcard because the us. profile routes across us-east-1/us-east-2/
    us-west-2.
    """
    return iam.PolicyStatement(
        sid="BedrockInvoke",
        actions=["bedrock:InvokeModel"],
        resources=[
            f"arn:aws:bedrock:*:{ACCT}:inference-profile/us.anthropic.claude-*",
            "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════
# INGESTION STACK — 15 Lambdas
# Pattern: DDB write, S3 raw/<source>/*, source-specific secret, DLQ
# ═══════════════════════════════════════════════════════════════════════════


def _ingestion_base(
    source: str,
    secret_name: str = None,
    s3_prefix: str = None,
    ddb_actions: list[str] = None,
    extra_secret_actions: list[str] = None,
    extra_s3_read: list[str] = None,

... [TRUNCATED — 2399 lines omitted, 2479 total]

```


### .github/workflows/ci-cd.yml (FULL — proof of pipeline implementation)
```yaml

# Life Platform CI/CD Pipeline
# MAINT-4: Automated lint → deploy → smoke test on push to main
#
# Architecture:
#   1. Lint (flake8 + py_compile syntax check) — runs on every push, no AWS access needed
#   2a. Deploy-critical tests — the FAST offline subset (marker: deploy_critical) that
#       GATES the chain (#416, ADR-117). `plan` depends on THIS, not the full suite.
#   2b. Unit Tests — the exhaustive suite; runs in parallel, still reds main, but no
#       longer skips deploy + the reader-facing visual-QA gate on an unrelated red test.
#   3. Plan — validates lambda_map.json, detects changed files, maps to Lambda functions
#   4. Deploy — requires manual approval (GitHub Environment: production)
#   5. Smoke test — invokes qa-smoke + canary, checks structured output
#   6. Auto-rollback — Lambda/MCP (smoke failure, TB7-25) + SITE (smoke OR visual-QA
#      failure, #418/ADR-117); shared-layer rollback surfaced as a runbook in the
#      failure notification.
#   7. Notify — posts to SNS on any failure
#
# AWS auth: OIDC federation (no long-lived keys)
# See deploy/setup_github_oidc.sh to create the IAM provider + role
#
# Changes from original (v3.5.8 → v3.6.0):
#   - Added py_compile syntax check step in Lint job
#   - Added lambda_map.json structural validation in Plan job
#   - Replaced sleep 10 with aws lambda wait function-updated (MCP + Lambda deploys)
#   - Added layer version verification after shared layer rebuild
#   - Fixed smoke test and canary to parse JSON output, not grep for "error"
#   - Added notify-failure job that posts to SNS life-platform-alerts on any failure
# Changes (v3.7.9):
#   - Added rollback-on-smoke-failure job (TB7-25): auto-rollback when smoke test fails
#     after a successful deploy. Calls deploy/rollback_lambda.sh for each deployed function.
#     Requires deploy_lambda.sh to have stored artifacts to s3://matthew-life-platform/deploys/

name: CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'lambdas/**'
      - 'mcp/**'
      - 'mcp_server.py'
      - 'tests/**'          # test-only changes must re-validate the suite (else CI red lingers)
      # DEVOPS-01 (AUDIT 2026-06-30): infra/config/tooling were EXCLUDED, so IAM, alarm,
      # and layer-version changes reached main with NO pipeline — and the auto-merge
      # ALLOWLIST (role_policies.py, monitoring_stack.py, ci/lambda_map.json) relies on
      # an on-main re-run that therefore never happened. These paths close that hole.
      - 'cdk/**'                 # IAM / alarms / layer version → must hit Lint + Plan
      - 'ci/**'                  # lambda_map.json / deploy-manifest drift
      - 'config/**'              # config that feeds Lambdas (content_filter, personas, goals)
      - '.github/workflows/**'   # workflow edits must re-validate
      - 'requirements*.txt'
      - 'pyproject.toml'
      - '.flake8'
  workflow_dispatch:
    inputs:
      deploy_all:
        description: 'Deploy ALL Lambdas (skip change detection)'
        required: false
        type: boolean
        default: false

# V2 P4.14 (2026-05-17): prevent concurrent deploys racing on the same branch.
# cancel-in-progress=false because a deploy mid-flight should complete.
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false

env:
  AWS_REGION: us-west-2
  AWS_ACCOUNT_ID: "205930651321"  # CONF-03: single place — override via GitHub env var for staging
  LAMBDA_MAP: ci/lambda_map.json
  SNS_TOPIC_ARN: arn:aws:sns:us-west-2:205930651321:life-platform-alerts-digest  # 2026-05-25: was life-platform-alerts (immediate-email). CI failure notifications now batch into the daily digest like all other alerts (per the inbox-noise mitigation sweep). CONF-03 follow-up: construct from AWS_ACCOUNT_ID.

permissions:
  id-token: write   # OIDC token for AWS
  contents: read    # Checkout code

jobs:
  # ════════════════════════════════════════════════════════════════
  # Job 1: Lint + Syntax Check
  # ════════════════════════════════════════════════════════════════
  lint:
    name: Lint + Syntax Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0

      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
        with:
          python-version: '3.12'
          cache: 'pip'  # V2 P4.14: speeds up CI by ~20s per job

      - name: Install flake8
        run: pip install flake8

      - name: Run flake8
        run: |
          echo "::group::Linting lambdas/"
          flake8 lambdas/ --count --show-source --statistics || true
          echo "::endgroup::"

          echo "::group::Linting mcp/"
          flake8 mcp/ --count --show-source --statistics || true
          echo "::endgroup::"

          # Fail on syntax errors and undefined names; pass on style warnings
          flake8 lambdas/ mcp/ --count --select=E9,F63,F7,F82 --show-source --statistics

      - name: Install black + ruff
        run: pip install black==25.9.0 ruff==0.14.0

      - name: Format gate (black — ENFORCED, config in pyproject.toml)
        run: black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/

      - name: Lint gate (ruff — ENFORCED; import-sort via ruff's isort rules)
        run: ruff check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/

      - name: Mypy gate (ENFORCED — clean-module set, ADR-080)
        run: |
          pip install mypy==2.1.0
          echo "::group::Mypy on the clean-module set (tier-1 core + split AI modules + tier-2 web/)"
          # Authoritative list: tests/test_mypy_clean_modules.py::MYPY_CLEAN_MODULES.
          # Tier-1 (budget/auth/inference): secret_cache, retry_utils, phase_filter,
          # constants, bedrock_client. Tier-2 (#419): the small, already-clean
          # slice of the public serving surface (web/*.py) — see that file's
          # comment for what's excluded and why. Blocking — a type regression
          # here fails CI.
          python -m mypy --config-file mypy.ini \
            lambdas/secret_cache.py lambdas/retry_utils.py lambdas/phase_filter.py \
            lambdas/constants.py lambdas/bedrock_client.py lambdas/scoring_engine.py \
            lambdas/character_engine.py lambdas/intelligence_common.py lambdas/ai_calls.py \
            lambdas/ai_context.py lambdas/ai_summaries.py \
            lambdas/web/site_api_common.py lambdas/web/site_api_coach.py \
            lambdas/web/site_api_intelligence.py lambdas/web/site_api_reading.py \
            lambdas/web/site_api_vitals.py lambdas/web/site_stats_refresh_lambda.py \
            lambdas/web/og_image_lambda.py lambdas/web/og_moments.py
          echo "::endgroup::"

      - name: Syntax check (py_compile)
        # Catches broken syntax that flake8 misses (e.g. invalid f-strings, truncated files)
        run: |
          echo "::group::Syntax checking lambdas/ and mcp/"
          FAILED=0
          while IFS= read -r -d '' f; do
            if python3 -m py_compile "$f" 2>&1; then
              echo "  ✅ $f"
            else
              echo "  ❌ SYNTAX ERROR: $f"
              FAILED=$((FAILED + 1))
            fi
          done < <(find lambdas/ mcp/ -name '*.py' -print0)
          echo "::endgroup::"
          if [ "$FAILED" -gt 0 ]; then
            echo "::error::$FAILED file(s) failed syntax check"
            exit 1
          fi
          echo "✅ All files pass syntax check"

      - name: Dependency Security Scan (advisory)
        # pip-audit for known CVEs. 2026-06-09 (Tier-1 hardening): broadened from
        # cdk-only to BOTH dependency manifests + a loud, actionable warning on any
        # finding (the platform's "advisory-but-visible" pattern). Stays NON-blocking
        # — Dependabot (.github/dependabot.yml) opens the fix PRs, so a sudden
        # unfixable transitive CVE never red-walls deploys. (Lambda runtime is
        # stdlib-only, so there is no lambdas/ requirements to scan.)
        run: |
          pip install pip-audit 2>/dev/null
          FOUND=0
          for req in requirements-dev.txt cdk/requirements.txt; do
            echo "::group::pip-audit $req"
            pip-audit -r "$req" --desc on 2>&1 || FOUND=1
            echo "::endgroup::"
          done
          if [ "$FOUND" = "1" ]; then
            echo "::warning title=Dependency vulnerability (advisory)::pip-audit flagged known CVEs — review the grouped logs; Dependabot will open a bump PR for the affected package."
          fi
          echo "Dependency scan complete — advisory (non-blocking); Dependabot drives remediation."

      - name: Check lambda_map coverage
        # R18-F03: Detect Lambda source files missing from ci/lambda_map.json.
        # 2026-05-28: the old `for f in lambdas/*_lambda.py` glob matched ZERO
        # files after the P3.1 subpackage restructure (everything moved under
        # lambdas/<domain>/), so this check silently passed and let unmapped
        # Lambdas slip through (the qa-smoke / lambda_map drift class). Now uses
        # a recursive find and FAILS the build — a Lambda source must be mapped.
        run: |
          MISSING=0
          while IFS= read -r f; do
            if ! grep -q "\"$f\"" ci/lambda_map.json; then
              echo "::error file=$f::Lambda source file not in ci/lambda_map.json — add it to the .lambdas section"
              MISSING=$((MISSING + 1))
            fi
          done < <(find lambdas -name '*_lambda.py' -o -name '*_handler.py')
          if [ $MISSING -gt 0 ]; then
            echo "::error::$MISSING Lambda source file(s) missing from lambda_map.json"
            exit 1
          else
            echo "✅ All Lambda source files present in lambda_map.json"
          fi

      - name: Content-policy scan (ENFORCED — #354)
        # Scans public-facing surfaces (site/, email lambdas, mcp/) for blocked terms
        # from seeds/content_filter.json — the same list the runtime filter enforces.
        # Catches personal-content leaks before they reach the public repo.
        run: python3 scripts/content_policy_scan.py

      - name: Doc-drift gate (ENFORCED — #389)
        # sync_doc_metadata.py --check asserts the literal counts quoted in CLAUDE.md
        # and docs/*.md (tool/Lambda/module/ADR/test counts, served PLATFORM_STATS)
        # against what AST/regex discovery finds in the source right now. Writes
        # nothing; a mismatch means a fact changed (new tool, new Lambda, new ADR,
        # new test) and nobody reran `sync_doc_metadata.py --apply` before merging.
        run: python3 deploy/sync_doc_metadata.py --check

  # ════════════════════════════════════════════════════════════════
  # Job 2a: Deploy-critical test lane (#416, ADR-117) — GATES the chain
  # ════════════════════════════════════════════════════════════════
  # The FAST, fully-offline subset that decides whether a deploy is SAFE:
  # the deploy contract (Lambda handler names/signatures, shared-layer
  # module presence + consumer wiring, MCP tool registration, IAM role
  # policies, secret-name references, DDB key patterns, CDK↔source
  # consistency) + the reader-facing AI-output honesty gate. `plan`
  # depends on THIS job, NOT the exhaustive `test` job below — so one
  # unrelated red unit test no longer skips deploy AND the reader-facing
  # visual-QA safety net (the "red main blacks out visual QA" failure).
  # The exhaustive suite still runs (job `test`, in parallel) and still
  # reds main + fires notify-failure; it just no longer gates the chain.
  # Inclusion criteria + the exact file list live in docs/CONVENTIONS.md
  # ("Deploy-critical test lane") and are enforced by the `deploy_critical`
  # pytest marker (pytest.ini). `not integration` keeps the one live-AWS
  # test in a marked file (test_lv6) out of this creds-free lane.
  test-critical:
    name: Deploy-critical tests
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0

      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install test dependencies
        run: pip install pytest boto3 botocore

      - name: Run deploy-critical test lane
        run: |
          echo "::group::Deploy-critical lane — pytest -m 'deploy_critical and not integration'"
          python3 -m pytest tests/ -m "deploy_critical and not integration" -v --tb=short
          echo "::endgroup::"

  # ════════════════════════════════════════════════════════════════
  # Job 2b: Unit Tests — the exhaustive offline suite
  # ════════════════════════════════════════════════════════════════
  # NON-GATING for deploy since #416/ADR-117: nothing downstream `needs`
  # this job except notify-failure, so a red here still flags main (and
  # emails a CI failure) but no longer skips plan → deploy → visual-QA.
  # The deploy-gating subset is job `test-critical` above.
  test:
    name: Unit Tests
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0

      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
        with:
          python-version: '3.12'
          cache: 'pip'  # V2 P4.14: speeds up CI by ~20s per job

      - name: Install test dependencies
        run: pip install pytest pytest-cov boto3 botocore  # Phase 8.2: pytest-cov for coverage report

      - name: Run unit tests
        run: |
          echo "::group::Running tests/test_shared_modules.py"
          python3 -m pytest tests/test_shared_modules.py -v --tb=short
          echo "::endgroup::"

      - name: IAM policy linter (test_role_policies.py)
        run: |
          echo "::group::IAM policy linter"
          python3 -m pytest tests/test_role_policies.py -v --tb=short
          echo "::endgroup::"

      - name: CDK handler consistency linter (test_cdk_handler_consistency.py)
        run: |
          echo "::group::CDK handler consistency linter"
          python3 -m pytest tests/test_cdk_handler_consistency.py -v --tb=short
          echo "::endgroup::"

      - name: CDK S3 path linter (test_cdk_s3_paths.py)
        run: |
          echo "::group::CDK S3 path linter"
          python3 -m pytest tests/test_cdk_s3_paths.py -v --tb=short
          echo "::endgroup::"

      - name: Safety module wiring linter (test_wiring_coverage.py)
        run: |

... [TRUNCATED — 1115 lines omitted, 1415 total]

```


### Test suite — all test files with function names

**test_adherence_calc.py** (3 tests): test_full_completion_is_100, test_partial_completion_reports_per_muscle, test_extra_exercises_listed


**test_ai_endpoint_hardening.py** (7 tests): test_both_handlers_check_budget_pause, test_paused_response_is_200_not_5xx, test_both_endpoints_rate_limited, test_per_request_token_caps_present, test_input_length_capped, test_ask_prompt_is_correlative_and_confidence_labelled, test_content_safety_filters_present


**test_ai_output_faithfulness.py** (3 tests): test_faithfulness_corpus, test_corpus_covers_all_failure_classes, test_reader_facing_paths_stay_gated


**test_ai_output_validator_units.py** (3 tests): test_hrv_in_bpm_warns, test_hrv_in_ms_is_clean, test_resting_hr_in_bpm_is_fine


**test_ai_quality_canary.py** (17 tests): test_status_ordering, test_probe_suite_has_the_three_regressions, test_clean_in_character_answer_is_ok, test_fourth_wall_vendor_leak_alarms, test_bare_ai_acknowledgement_is_not_a_leak, test_blocked_vice_term_alarms, test_empty_stub_response_alarms, test_grounded_numbers_pass_and_fabrication_alarms, test_grounded_check_ignores_reps_sets_and_years, test_grounded_check_degrades_when_no_facts, test_invalid_persona_400_is_ok_but_500_alarms, test_rate_limit_on_own_bucket_is_warn_not_alarm, test_transport_failure_alarms, test_advisory_judge_never_flips_the_status, test_handler_skips_when_budget_paused, test_handler_full_green_emits_ok, test_canary_uses_reserved_non_reader_source_ip


**test_ai_scrub_hardening.py** (8 tests): test_literal_term_still_removed, test_zero_width_obfuscation_stripped, test_spaced_long_term_drops_whole_answer, test_punctuated_long_term_drops_whole_answer, test_normal_answer_untouched, test_short_substring_does_not_nuke_answer, test_normalize_collapses_separators, test_history_turn_is_gated_and_scrubbed


**test_alert_digest.py** (7 tests): test_parse_raw_delivery_body, test_parse_envelope_fallback, test_parse_garbage_body, test_group_dedupes_by_alarm_name, test_format_email_includes_alarms, test_handler_empty_queue_sends_nothing, test_handler_non_empty_sends_one_email


**test_ask_grounding_depth.py** (8 tests): test_reads_block_renders_every_read, test_reads_block_empty_when_no_reads, test_prompt_includes_computed_reads_section, test_prompt_omits_section_when_reads_missing, test_prompt_rules_forbid_arithmetic_and_asking_reader, test_source_count_is_derived_not_hardcoded, test_coach_system_uses_derived_count, test_fetch_computed_reads_fail_soft


**test_auth_breaker.py** (9 tests): test_looks_like_auth_failure_recognizes_401, test_looks_like_auth_failure_recognizes_keywords, test_looks_like_auth_failure_recognizes_httperror_code, test_looks_like_auth_failure_ignores_5xx, test_check_auth_breaker_absent_returns_none, test_check_auth_breaker_fresh_returns_item, test_check_auth_breaker_expired_returns_none, test_mark_auth_failure_writes_item_with_ttl, test_clear_auth_failure_deletes_item


**test_auth_breaker_metrics.py** (6 tests): test_mark_failure_emits_zero, test_clear_failure_emits_one, test_check_breaker_fresh_emits_zero_and_returns_item, test_check_breaker_absent_emits_nothing, test_check_breaker_expired_emits_nothing, test_emit_never_raises


**test_autonomic_zone2_endpoints_414.py** (10 tests): test_autonomic_thin_data_is_honest_not_fabricated, test_autonomic_real_payload_places_current_state, test_autonomic_reads_real_efficiency_field, test_autonomic_handler_empty_state, test_autonomic_handler_real_payload, test_zone2_no_activity_is_honest, test_zone2_short_activity_below_floor_excluded, test_zone2_real_payload_against_150_reference, test_zone2_handler_real_payload, test_zone2_handler_empty_state


**test_bedrock_client.py** (7 tests): test_fable_and_opus48_map_to_us_profiles, test_unmapped_model_falls_back_to_haiku, test_profile_ids_and_arns_pass_through, test_invoke_scrubs_sampling_params_on_fable, test_invoke_drops_explicit_thinking_disabled_on_fable, test_invoke_keeps_adaptive_thinking_on_fable, test_invoke_leaves_sonnet_body_untouched


**test_bedrock_cost_telemetry.py** (13 tests): test_cost_haiku_in_out, test_cost_sonnet_in_out, test_cost_includes_cache_tokens, test_unknown_model_prices_as_most_expensive, test_zero_usage_is_zero_cost, test_emit_includes_dimensionless_cost_for_g2_alarm, test_emit_includes_dimensionless_output_tokens_for_platform_alarm, test_emit_omits_cache_metrics_when_absent, test_emit_includes_cache_metrics_when_present, test_emit_noop_on_zero_usage, test_emit_is_fail_open, test_invoke_meters_on_return_path, test_invoke_returns_even_if_telemetry_breaks


**test_bench_episode_model.py** (4 tests): test_episode_record_keying_and_types, test_episode_record_is_cross_phase, test_regain_episode_omits_loss_only_fields, test_training_reference_singleton_shape


**test_benchmark_views.py** (12 tests): test_pace_run_gate_false_above_240_and_forward_framed, test_pace_run_gate_true_under_240, test_pace_no_reference_yet, test_unknown_view_lists_valid, test_episodes_view_summary_and_asymmetry, test_maintenance_not_applicable_far_from_goal, test_maintenance_near_goal_forward_framed_no_failure_tally, test_proven_rate_at_clamps_above_curve_max, test_proven_rate_at_clamps_below_curve_min, test_pace_resolves_label_with_regression_rate, test_thin_window_rate_is_none_not_fabricated, test_pace_rate_queries_withings_cross_phase


**test_between_chronicle.py** (7 tests): test_zero_new_inference, test_empty_period_sends_nothing, test_unchanged_digest_sends_nothing, test_kill_switch_honored, test_email_numbers_match_the_record_and_no_tracking, test_dry_run_builds_without_sending, test_cdk_wiring_exists


**test_board_answers_feed.py** (6 tests): test_cloudfront_routes_board_answers_to_generated_origin, test_qa_tab_reads_the_feed_and_has_honest_empty_state, test_publish_gate_passes_clean_entry, test_publish_gate_blocks_vice_terms_fail_closed, test_publish_gate_blocks_banned_names_in_answers, test_publish_script_wires_the_gate_before_put


**test_board_ask_roster.py** (10 tests): test_roster_is_the_real_cast, test_legacy_ids_map_to_real_coaches_never_500, test_unknown_persona_is_400_before_model_spend, test_grounding_in_every_persona_turn, test_system_prompt_has_the_guardrails, test_meta_pressure_preamble_present, test_no_ai_vendor_named_in_prompt, test_no_retired_wire_ids_serve_anywhere, test_frontend_uses_the_same_cast, test_facts_block_formats_only_present_keys


**test_board_followup_sessions.py** (11 tests): test_create_session_returns_opaque_token_no_pii, test_ttl_is_set_within_one_hour, test_board_ask_response_carries_a_session_token, test_followup_routes_to_same_coach_with_prior_context, test_followup_cap_enforced_before_spend, test_expired_session_is_unresumable, test_followup_bound_to_originating_ip, test_malformed_token_rejected_before_any_read, test_followup_rate_limited, test_ungrounded_followup_is_refused_fail_closed, test_followup_through_board_ask_entrypoint


**test_budget_guard_ladder.py** (7 tests): test_tier0_everything_runs, test_tier1_internal_ai_pauses_first, test_tier2_reader_narrative_pauses_but_readers_still_answered, test_tier3_hard_stop_blocks_everything, test_band_ordering_is_strict_internal_lt_narrative_lt_reader, test_all_gated_features_are_classified, test_ask_endpoint_and_daily_brief_are_the_last_to_go


**test_budget_tier_alarms.py** (3 tests): test_hardstop_alarm_present_and_urgent, test_existing_escalation_digest_still_present, test_hardstop_is_strictly_above_escalation


**test_build_dispatches.py** (6 tests): test_feed_shape_and_three_part_format, test_beat_receipts_point_at_the_repo, test_beats_pass_the_privacy_gate, test_story_app_has_the_build_section, test_section_shell_emitted, test_checklist_carries_the_honesty_rules


**test_business_logic.py** (0 tests): 


**test_calibration_538.py** (0 tests): 


**test_canonical_facts.py** (0 tests): 


**test_card_engine.py** (7 tests): test_every_registered_card_type_renders_from_a_fixture, test_unknown_card_type_raises, test_og_image_lambda_delegates_primitives_to_the_engine, test_character_card_never_carries_chronological_age, test_uncertainty_helper_draws_ci_and_n, test_chronicle_sweep_writes_honest_stats_cards_from_posts_json, test_chronicle_sweep_is_fail_soft_without_posts_json


**test_cdk_handler_consistency.py** (5 tests): test_h1_handler_and_source_always_paired, test_h2_all_source_files_exist, test_h3_handler_module_matches_source_file, test_h4_all_source_files_define_lambda_handler, test_h5_no_generic_lambda_function_handler


**test_cdk_s3_paths.py** (4 tests): test_s1_all_s3_prefixes_are_convention_or_documented, test_s2_exception_evidence_in_lambda_source, test_s3_exceptions_dont_use_convention_prefix, test_s4_no_hardcoded_matthew_in_iam_comments


**test_character_config_endpoint.py** (4 tests): test_serves_mechanics, test_whitelist_excludes_private_fields, test_no_emoji_served, test_config_load_failure_is_honest_200


**test_character_engine.py** (43 tests): test_engine_version, test_weighted_pillar_score_full_data, test_weighted_pillar_score_sparse_data, test_weighted_pillar_score_no_data, test_xp_decays_on_mediocre_day, test_xp_floors_at_zero, test_xp_grows_on_good_day, test_body_comp_loss_sigmoid, test_body_comp_maintenance, test_body_comp_none_weight, test_lab_decay_full_value, test_lab_decay_expires, test_lab_decay_at_90_days, test_ema_empty_returns_50, test_vice_log_curve, test_vice_log_day_30, test_in_range_score_in_range, test_in_range_score_below, test_in_range_score_none, test_foundation_levels_up_in_3_days, test_foundation_no_levelup_at_2_days, test_mastery_requires_10_days, test_mastery_levels_up_at_10_days, test_equal_day_holds_streak, test_variable_step_when_delta_large, test_normal_step_when_delta_small, test_per_pillar_ema_lambda, test_xp_buffer_prevents_level_down, test_xp_buffer_depleted_allows_level_down, test_behavioral_absent_scores_zero, test_measured_absent_still_neutral_blended, test_fully_absent_behavioral_pillar_scores_low_not_neutral, test_low_coverage_day_cannot_level_up, test_low_coverage_day_cannot_level_down, test_good_coverage_day_levels_normally, test_no_coverage_arg_keeps_legacy_behavior, test_raw_gate_blocks_up_on_ema_momentum, test_raw_gate_allows_up_when_day_performed, test_step_bands_scale_with_gap, test_pillar_drivers_summary, test_state_of_mind_valence_reads_som_avg_valence, test_reported_scenario_mind_lags_and_movement_sinks, test_reported_scenario_down_levels_after_stop


**test_check_deploy_drift.py** (15 tests): test_stale_checkout_is_blocked_when_origin_gained_a_lambda_fix, test_docs_only_upstream_change_does_not_count_as_stale, test_up_to_date_checkout_is_fresh, test_offline_fetch_failure_is_unknown_not_a_crash, test_no_fetch_mode_uses_stale_local_knowledge_of_origin_main, test_live_code_drift_clean_when_in_sync, test_live_code_drift_flags_a_code_property_change, test_live_code_drift_config_only_does_not_hard_flag, test_live_code_drift_detection_failure_is_an_error_not_a_crash, test_live_code_drift_non_lambda_resources_are_ignored, test_main_blocks_on_stale_checkout, test_main_override_flag_unblocks_stale_checkout, test_main_override_env_var_unblocks_stale_checkout, test_main_blocks_on_live_code_drift_when_stacks_given, test_main_skip_live_check_flag


**test_chronicle_autopublish.py** (5 tests): test_find_stale_drafts_window, test_missing_or_old_timestamp_is_skipped, test_sweep_publishes_via_approve_path, test_sweep_dry_run_publishes_nothing, test_handler_routes_scheduled_event_to_sweep


**test_chronicle_email_portraits.py** (4 tests): test_portrait_img_when_manifest_has_coach, test_no_portrait_returns_empty_for_unknown_coach, test_byline_falls_back_to_emoji, test_manifest_load_is_failsoft


**test_chronicle_post_template.py** (7 tests): test_ac1_five_door_story_top_nav, test_ac1_legacy_chrome_removed, test_ac2_og_image_is_editorial_cover, test_ac2_og_image_falls_back_when_no_cover, test_ac3_canonical_and_structured_data_use_journal_path, test_ac4_subscribe_cta_present, test_post_key_is_sequential_week_path


**test_chronicle_recap.py** (14 tests): test_build_recap_returns_shape, test_date_cross_check_drops_unpublished_beat, test_raw_vitals_guard_drops_beat_and_rejects_story, test_thin_history_blanks_beats, test_no_published_history_returns_none, test_privacy_gate_drops_recap, test_build_recap_is_failsoft, test_parse_recap_json_handles_fence, test_commit_recap_writes_latest_and_dated, test_commit_recap_noop_without_draft, test_endpoint_honest_null_when_absent, test_endpoint_returns_recap, test_endpoint_withholds_stale_record, test_recap_is_experiment_scoped


**test_chronicle_share_kit.py** (6 tests): test_kit_carries_only_published_values_and_the_honest_stats_line, test_card_url_slug_matches_the_canonical_post_url, test_caption_is_paste_ready_with_stats_and_link_and_no_new_numbers, test_email_block_escapes_and_surfaces_the_kit, test_journal_post_ref_seq_matches_the_written_post_slug, test_empty_excerpt_source_still_produces_a_valid_kit


**test_ci_pin_consistency.py** (1 tests): test_dev_pins_match_ci_gate


**test_circadian_tz.py** (5 tests): test_pt_conversion_during_pdt_summer, test_pt_conversion_during_pst_winter, test_naive_iso_treated_as_utc, test_plain_hhmm_passthrough, test_empty_returns_none


**test_citation_gate_758.py** (0 tests): 


**test_classify_core.py** (3 tests): test_anti_rotation_and_carries_map_to_core, test_existing_core_still_core, test_big_three_patterns_untouched


**test_coach_commitments_532.py** (0 tests): 


**test_coach_daily_reflection.py** (3 tests): test_self_skips_at_tier_2, test_self_skips_at_tier_3, test_constants_sane


**test_coach_episode_cover.py** (3 tests): test_episode_cover_is_1500_square, test_unsigned_guest_rejected, test_cover_composites_two_portraits_when_host_present


**test_coach_history_windowing.py** (7 tests): test_failure_case_fits_the_input_budget, test_rollup_lines_keep_omitted_counts_honest, test_windows_do_not_fire_below_the_caps, test_budget_guard_shrinks_windows_deterministically, test_prediction_scan_is_bounded_and_newest_first, test_open_thread_window_is_recency_ranked, test_nothing_is_deleted_by_the_windowing


**test_coach_intelligence.py** (0 tests): 


**test_coach_interaction_memory_533.py** (9 tests): test_field_note_pushback_interaction_renders_distinctly, test_board_qa_interaction_still_renders_as_before, test_no_interactions_renders_none_section, test_gather_coach_state_reads_learning_records, test_prediction_outcomes_section_lists_confirmed_and_refuted, test_no_learning_outcomes_renders_none_section, test_compression_system_prompt_tells_haiku_to_reference_outcomes, test_mind_nutrition_training_briefs_see_a_real_interaction_when_one_exists, test_windowing_still_fits_the_input_budget_with_learning_added


**test_coach_memoir_lambda.py** (12 tests): test_self_skips_when_budget_tier_pauses_coach_narrative, test_runs_normally_below_the_pause_tier, test_already_generated_false_when_no_sentinel, test_already_generated_true_after_a_sentinel_is_written, test_gather_facts_is_none_with_no_learnings_this_quarter, test_gather_facts_only_counts_records_inside_the_quarter_window, test_gate_rejects_a_fabricated_number, test_gate_rejects_a_highlight_reel_when_a_miss_exists, test_gate_passes_grounded_text_that_cites_the_real_miss, test_generate_prompt_carries_only_real_facts_no_invented_numbers, test_generate_retries_once_then_drops_on_persistent_gate_failure, test_end_to_end_quarterly_gate_regenerates_only_on_a_new_quarter


**test_coach_panel_podcast.py** (19 tests): test_self_skips_at_tier_2, test_gate_turns_maps_speakers_and_drops_unsafe, test_pick_coach_fallback_is_operational, test_intro_gate_resolves_two_speakers_and_drops_unsafe, test_safety_gate_fails_closed_on_every_banned_class, test_sensitivity_routing_holds_only_on_current_crisis, test_weekly_gate_fails_closed_and_drops_unsafe, test_gemini_voice_map_distinct, test_intro_hallucination_guard_drops_daycero_violations, test_voice_routing_returns_chirp_voice, test_craft_check_passes_clean_dialogue, test_craft_check_allows_three_but_flags_four_in_a_row, test_craft_check_flags_monologue_but_exempts_hook, test_qa_review_fails_open_on_judge_error, test_feed_is_well_formed_and_podcast_standard, test_hms_formats_seconds, test_enclosure_mime_by_extension, test_reason_codes_cover_every_terminal_outcome, test_emit_outcome_is_fail_open_and_normalizes


**test_coach_quality_gate_390.py** (0 tests): 


**test_coach_stance.py** (9 tests): test_every_operational_coach_has_a_stance, test_every_stage_has_required_fields, test_bands_tile_the_metric, test_watches_reference_real_signals, test_resolver_picks_the_right_rung, test_nutrition_resolver_on_logging_consistency, test_nutrition_leads_with_logging, test_nutrition_has_no_aggressive_numeric_rate, test_nutrition_concern_watches_supportive_and_rate_deferred


**test_coach_stance_engine.py** (27 tests): test_summarize_track_record, test_summarize_track_record_empty, test_claims_change_detector, test_sanitize_drops_ungrounded_change, test_sanitize_keeps_change_grounded_by_correction, test_sanitize_keeps_change_grounded_by_stage_shift, test_generate_stance_first_run_blanks_change, test_generate_stance_self_corrects_leaked_vitals, test_generate_stance_flags_persistent_vitals, test_generate_stance_non_dict_returns_none, test_run_stance_skips_on_compression_fallback, test_run_stance_is_failsoft, test_stance_for_brief_trims_internal_fields, test_build_user_message_surfaces_stance, test_handler_injects_stance_into_brief, test_stance_block_prefers_stance, test_stance_block_falls_back_to_ladder, test_protocols_for_brief_trims_and_caps, test_gather_filters_by_domain, test_gather_only_active, test_experiment_routing_by_tags, test_untagged_experiment_routes_to_explorer_only, test_explorer_sees_all_domains, test_gather_is_failsoft, test_build_user_message_surfaces_protocols, test_handler_injects_protocols_into_brief, test_handler_omits_protocols_when_none


**test_coach_tuning_logged.py** (8 tests): test_tuning_log_is_shaped, test_every_entry_is_valid, test_entries_are_date_ordered, test_detector_flags_voice_change, test_detector_ignores_non_voice_change, test_new_entries_and_tip_logic, test_gate_fails_steady_state_when_voice_changed_but_log_untouched, test_voice_diffs_require_a_tuning_log_entry


**test_coaches_api.py** (8 tests): test_roster_returns_eight_coaches, test_roster_headline_is_honest_pre_data, test_coach_page_shape_and_stance_rung, test_coach_page_id_via_query_param, test_nutrition_coach_resolves_entry_rung_without_data, test_unknown_coach_404, test_team_view_shape, test_team_stage_mix_is_honest


**test_coherence_invariants.py** (1 tests): test_overall_status_takes_worst


**test_coherence_sentinel.py** (10 tests): test_run_checks_surfaces_known_bugs, test_digest_renders, test_facts_use_canonical_schema_closing_the_grounding_loop, test_build_record_is_serializable_and_complete, test_semantic_incoherence_is_advisory_not_alarm_driving, test_deterministic_alarm_still_drives_status, test_persist_writes_latest_and_dated_and_is_fail_soft, test_post_reset_empty_board_reports_ok, test_same_empty_board_alarms_once_past_the_grace_window, test_healthy_state_is_ok


**test_compute_surfacing.py** (6 tests): test_circadian_populated_shape, test_circadian_no_data, test_sleep_reconciliation_handler_is_retired, test_sleep_detail_night_of_date_sourced_live_not_from_unified, test_forecast_populated_shape, test_forecast_empty


**test_correlation_report_535.py** (5 tests): test_tiny_n_is_omitted, test_every_reported_correlation_carries_its_uncertainty, test_strong_but_thin_correlation_is_not_called_harmful, test_noise_is_neutral_not_inconclusive, test_per_tool_fdr_inflates_q_above_p


**test_correlations_serving.py** (5 tests): test_p_zero_served_as_zero_not_one, test_missing_p_served_as_none, test_ordinary_p_passes_through, test_strength_label_agrees_with_r, test_featured_filter_treats_p_zero_as_significant


**test_cost_governor.py** (13 tests): test_tier_thresholds, test_n08_regression_projection_overshoot_capped_to_tier1, test_early_month_projection_fully_ignored, test_genuine_runaway_unlocks_higher_tiers, test_actual_at_ceiling_is_tier3_regardless_of_projection, test_projection_below_actual_never_inflated_by_cap, test_post_pause_stuck_projection_de_escalates, test_all_quiet_is_tier0, test_projection_tracks_trailing_rate_not_lumpy_mtd, test_projection_nonai_lump_not_extrapolated, test_projection_zero_remaining_equals_mtd, test_projection_short_trailing_window_is_finite, test_non_ai_series_excludes_bedrock_edition_services


**test_cover_pipeline.py** (7 tests): test_open_library_hit, test_google_books_fallback, test_placeholder_when_all_miss, test_store_updates_book_cover_key, test_small_response_treated_as_miss, test_handler_batch_isolates_failures, test_buffer_import_kept


**test_daily_brief_golden.py** (1 tests): test_daily_brief_golden_snapshot


**test_daily_insight_changepoints.py** (0 tests): 


**test_data_truth_batch.py** (23 tests): test_hypothesis_rows_read_real_whoop_and_eightsleep_fields, test_hypothesis_rows_no_dead_field_names_remain, test_onset_consistency_ignores_workout_subrecords, test_onset_consistency_excludes_own_date_record, test_cgm_component_reads_written_field_name, test_metabolic_coverage_full_on_full_data_day, test_metabolic_config_weights_sum_to_one_without_body_fat, test_nutrition_review_cgm_extract_reads_written_names, test_withings_body_comp_delta_code_deleted, test_latest_weight_withings_backscan, test_latest_weight_apple_seven_day_backscan_beats_stale_withings, test_latest_weight_withings_wins_ties_and_converts_kg, test_latest_weight_empty_inputs, test_evidence_js_date_conditions_weight_labels, test_compute_readiness_returns_its_actual_inputs, test_latest_readiness_serves_stored_components_not_day_grade, test_latest_readiness_pre492_record_serves_no_components, test_device_agreement_never_silent_null, test_sleep_detail_mismatched_night_carries_attribution, test_sleep_detail_matched_night_has_null_attribution, test_sleep_page_captions_the_substitution, test_qa_smoke_strava_is_optional_not_paused, test_cockpit_zero_caption_no_longer_blames_quiet_day


**test_ddb_key_contracts.py** (1 tests): test_every_static_get_item_key_exists_in_table


**test_ddb_patterns.py** (4 tests): test_d1_pk_sk_format, test_d2_date_reserved_word_guarded, test_d3_schema_version_present, test_d4_put_item_guarded_by_validator


**test_delete_user_data.py** (6 tests): test_missing_user_id_returns_400, test_protected_user_refused, test_missing_confirm_or_dryrun_returns_400, test_dry_run_returns_plan_without_deleting, test_real_run_requires_explicit_confirm, test_real_run_invokes_batch_delete_and_audit


**test_di1_movement_integrity.py** (20 tests): test_has_workout_true_with_hevy_low_steps, test_no_sedentary_on_hevy_days_jun16_19, test_hevy_only_day_appears_when_no_apple_record, test_tsb_nonzero_from_hevy_when_strava_off, test_tsb_strava_and_hevy_are_additive_same_day, test_tsb_strava_weighttraining_echo_not_double_counted, test_coach_guard_withholds_undertraining_when_strava_paused, test_coach_guard_passes_through_when_strava_live, test_coach_guard_noop_when_no_undertraining_assertion, test_source_state_strava_unpaused_2026_07, test_source_state_distinguishes_paused_rate_limited_stale, test_guard_reads_resolved_paused_state_end_to_end, test_guard_stops_withholding_once_strava_live, test_pipeline_health_counts_strava_again, test_healthy_pipe_no_records_is_assessable_as_rest, test_unhealthy_pipe_no_records_stays_honest, test_live_records_beats_ingest_health_signal, test_ingest_health_omitted_is_backward_compatible, test_step_completeness_flag_surfaces_jun5_13_gap, test_missing_apple_steps_never_sedentary_with_hevy


**test_dlq_consumer.py** (11 tests): test_stable_id_is_stable_and_content_derived, test_record_failure_adds_receive_count_and_returns_cumulative, test_record_failure_fails_soft_on_ddb_error, test_transient_confirmed_retry_deletes_and_does_not_escalate, test_transient_unconfirmed_retry_is_left_on_queue, test_permanent_body_escalates, test_cumulative_threshold_escalates_a_transient, test_unretryable_message_escalates, test_empty_queue_no_alerts, test_drain_loops_until_empty, test_poisoned_message_pages_operator_end_to_end


**test_drift_sentinel.py** (12 tests): test_protect_prefixes_extracts_deny_resources, test_bucket_policy_clean_when_live_matches_source, test_bucket_policy_drift_when_a_prefix_is_dropped, test_bucket_policy_drift_when_statement_missing, test_bucket_policy_error_is_soft, test_orphan_allowlist_excludes_cdk_bootstrap, test_sweep_clean, test_sweep_drift_wins, test_sweep_degraded_when_error_no_drift, test_as_signal_only_on_real_drift, test_status_html_is_loud_for_every_state, test_read_latest_fail_soft


**test_editorial_image.py** (7 tests): test_killswitch_default_off, test_pick_query_is_constrained_and_deterministic, test_missing_key_is_failsoft, test_pexels_error_is_failsoft, test_happy_path_stores_to_editorial_prefix, test_tiny_image_rejected, test_slug_is_sanitised


**test_elena_state.py** (17 tests): test_no_prior_stance_means_no_evolution_claim, test_change_claim_without_receipts_is_dropped, test_change_claim_with_receipts_is_kept, test_vital_hits_flags_fabricated_numbers, test_callback_due_window_clamps, test_invented_slugs_are_noops, test_real_slugs_are_paid_and_resolved, test_motifs_merge_with_counts, test_stance_written_with_receipts_and_flag, test_updater_refuses_unpublished_installments, test_updater_requires_a_date, test_both_publish_paths_invoke_the_updater, test_chronicle_prompt_gains_the_notebook, test_chronicle_body_joins_the_grounding_gate, test_between_chronicle_reads_her_stance, test_podcast_host_reads_her_state, test_updater_writes_only_the_persona_partition


**test_email_render_goldens.py** (1 tests): test_email_render_golden


**test_engagement_coach.py** (8 tests): test_trimmer_omits_when_present, test_trimmer_surfaces_lull_without_cause, test_trimmer_surfaces_return_with_delta, test_trimmer_carries_planned_pause, test_handler_injects_engagement, test_handler_omits_engagement_when_present, test_handler_omits_engagement_when_absent, test_build_user_message_surfaces_engagement


**test_engagement_core.py** (12 tests): test_present_when_logging, test_lag_grace_yesterday_is_present, test_the_trigger_scenario_quiet, test_extended_silence_is_dark, test_no_data_in_window_is_dark, test_return_detection_and_weight_regain, test_short_gap_is_not_a_return, test_travel_suppresses_to_planned_pause, test_sick_suppresses_to_planned_pause, test_wearables_dark_when_not_flowing, test_passive_metrics_carried_verbatim, test_no_internal_keys_leak


**test_episode_detect_algorithm.py** (8 tests): test_turning_points_finds_peaks_and_troughs, test_detect_episodes_loss_and_regain, test_min_episode_threshold_filters_small_swings, test_classify_loss_outcome_held_vs_reversed, test_weekly_covariates_normalizes_per_week, test_classify_activity_mapping, test_smooth_weight_interpolates_daily, test_real_validation_reproduces_blueprint_values


**test_er03_gate.py** (8 tests): test_clean_correlative_text_passes, test_fabricated_number_fails, test_number_present_in_input_passes, test_causal_connective_fails, test_unhedged_small_n_fails, test_large_n_needs_no_hedge, test_matthew_prefix_fails, test_numbers_in_extractor


**test_evidence_catalog.py** (4 tests): test_blocked_vices_filtered_from_habit_names, test_habits_from_habitify_filters_and_groups, test_habits_from_habitify_empty_when_no_record, test_experiment_catalog_tags_origin_and_shelf


**test_exercise_history.py** (14 tests): test_history_facts_extracts_last_session_top_set_only, test_history_facts_empty_for_unknown_template, test_render_cue_default_format, test_render_cue_empty_for_no_history, test_render_cue_rounds_weight_to_half_kg, test_pick_note_one_best_line_prefers_history_when_no_ai, test_pick_note_one_best_line_prefers_ai_when_present, test_pick_note_show_both_concatenates, test_pick_note_off_returns_empty, test_load_recent_history_skips_legacy_aggregates, test_load_recent_history_orders_sessions_most_recent_first, test_load_recent_history_decimals_become_floats_for_arithmetic, test_anti_hallucination_render_quotes_only_source_numbers, test_anti_hallucination_pick_note_does_not_inject_numbers


**test_experiment_date_window.py** (5 tests): test_future_genesis_clamps_to_today, test_normal_genesis_unchanged, test_genesis_today_is_valid, test_clamp_today_helper, test_vacation_fund_query_range_guards_future_genesis


**test_experiment_design.py** (0 tests): 


**test_experiment_prereg_728.py** (4 tests): test_artifact_written_with_design, test_no_design_means_no_artifact, test_s3_failure_is_failsoft_and_honest, test_design_without_stopping_rule_rejected


**test_expert_presence_block.py** (6 tests): test_empty_when_present, test_lull_block_names_the_gap_not_the_cause, test_planned_pause_framed_as_break, test_return_block_supportive_with_delta, test_shared_prompt_includes_presence_when_quiet, test_shared_prompt_omits_presence_when_present


**test_explain_endpoint.py** (8 tests): test_unknown_surface_400s_before_any_spend, test_client_numbers_are_never_trusted, test_ungrounded_numbers_fail_closed, test_shrink_bounds_lists_not_midtoken, test_prompt_carries_the_honesty_rules, test_surface_allowlist_is_the_named_dense_surfaces, test_routing_exists_lambda_and_cloudfront, test_frontend_sends_only_the_surface_name


**test_failure_pattern_detectors.py** (12 tests): test_predictors_skip_drives_lift, test_predictors_filters_low_n, test_predictors_returns_top_3_only, test_predictors_handles_empty, test_cascade_poor_sleep_to_bad_day, test_cascade_no_pattern_when_baseline_high, test_cascade_handles_no_sleep_data, test_dow_clusters_flags_weekend_drop, test_dow_clusters_handles_empty, test_rebound_speed_basic, test_rebound_speed_no_episodes, test_rebound_speed_too_few_records


**test_field_note_interaction_writeback.py** (5 tests): test_write_field_note_interactions_broadcasts_to_every_operational_coach, test_field_note_interaction_sk_is_content_addressed_on_week, test_write_field_note_interactions_is_fail_soft_per_coach, test_log_field_note_response_writes_coach_interactions, test_log_field_note_response_still_succeeds_if_interaction_writeback_fails


**test_field_notes_gather.py** (5 tests): test_training_minutes_from_day_rollups, test_training_falls_back_to_activities_list, test_training_omitted_when_no_records, test_sleep_nights_count_day_records_only, test_day_record_filter_shape


**test_field_notes_grounding.py** (5 tests): test_contradiction_triggers_one_kept_rewrite, test_worse_rewrite_keeps_original, test_grounded_note_generates_once, test_spelled_out_numbers_are_caught, test_no_facts_record_serves_unchecked


**test_food_delivery_reimport_479.py** (8 tests): test_full_reimport_of_same_file_does_not_double_count, test_reordered_reimport_does_not_double_count, test_partial_then_full_yields_correct_total, test_full_then_partial_does_not_regress_total, test_day_level_fields_stay_correct_across_partial_then_full, test_exact_duplicate_rows_are_both_kept_and_reimport_is_idempotent, test_year_aggregate_reflects_canonical_month_totals_after_partial_then_full, test_lambda_handler_end_to_end_with_fake_s3_and_table


**test_forecast_engine.py** (0 tests): 


**test_freshness_board_mirror.py** (4 tests): test_active_sources_match_checker, test_paused_sources_not_double_listed, test_stale_thresholds_match_checker, test_behavioral_classification_identical


**test_freshness_interior_gaps.py** (7 tests): test_single_interior_gap_is_flagged, test_consecutive_interior_gap_run, test_contiguous_span_has_no_gaps, test_trailing_absence_is_not_an_interior_gap, test_leading_absence_is_not_an_interior_gap, test_fewer_than_two_present_dates_yields_no_interior, test_dates_outside_window_are_ignored


**test_freshness_interior_gaps_mcp.py** (7 tests): test_single_interior_gap_flagged, test_contiguous_has_no_gap, test_trailing_absence_is_recency_not_gap, test_leading_absence_is_not_gap, test_multi_day_interior_gap, test_single_present_date_no_interior, test_daily_sources_set_matches_lambda


**test_freshness_pulse_589.py** (4 tests): test_primitive_present_in_motion_js, test_css_primitive_present, test_fresh_window_ok_tied_to_real_timestamps, test_fresh_window_ok_fails_closed_on_bad_input


**test_function_url_origin_header_validation.py** (0 tests): 


**test_generation_cache_738.py** (15 tests): test_dict_key_order_does_not_change_fingerprint, test_bookkeeping_keys_are_ignored, test_underscore_and_volatile_stripped_at_any_depth, test_decimal_and_native_number_fingerprint_equal, test_changed_number_busts_fingerprint, test_staleness_day_count_ticking_busts_fingerprint, test_stance_edit_busts_fingerprint, test_new_list_item_busts_fingerprint, test_all_parts_participate_in_the_hash, test_store_then_reuse_on_matching_hash, test_no_reuse_on_hash_mismatch, test_no_reuse_when_absent, test_record_reuse_bumps_bookkeeping, test_helpers_are_fail_soft, test_store_shape_resets_unchanged_clock


**test_get_nutrition_args.py** (8 tests): test_nutrition_no_args, test_nutrition_summary_view, test_nutrition_macros_view, test_nutrition_meal_timing_view, test_nutrition_micronutrients_view, test_nutrition_with_dates, test_nutrition_macros_with_overrides, test_nutrition_invalid_view


**test_golden_brief_eval.py** (14 tests): test_deterministic_verdict_is_ok, test_covers_all_eight_coaches_and_enough_golden, test_every_golden_output_draws_zero_findings, test_every_canary_is_caught, test_canary_checks_span_all_three_deterministic_dimensions, test_contradiction_detector_is_wired_not_silently_disabled, test_fabricated_number_is_caught, test_vendor_fourth_wall_leak_is_an_anti_pattern, test_grounded_output_is_clean, test_distinctiveness_flags_converged_voices, test_real_golden_voices_are_distinct, test_verdict_computed_without_judge, test_judge_failure_is_soft, test_ops_line_marks_pass_and_fail


**test_grading_liveness_727.py** (0 tests): 


**test_grounded_generation.py** (16 tests): test_numbers_in_text_handles_thousands_separators, test_allowed_numbers_unions_strings_and_structures, test_fabricated_trend_endpoint_is_caught, test_grounded_numbers_pass, test_integer_restatement_of_input_float_is_grounded, test_benign_small_counts_and_durations_pass, test_plausible_invented_vital_is_not_benign, test_contradiction_finding_from_canonical_facts, test_fabricated_number_finding_with_allow_list, test_clean_text_yields_no_findings, test_facts_block_contains_exact_values_and_hard_rule, test_regen_once_keeps_the_improved_rewrite, test_regen_once_never_regresses, test_regen_once_no_findings_no_call, test_regen_once_survives_regen_exception, test_correction_prompt_names_canonical_value


**test_grounding_self_correction.py** (11 tests): test_catches_the_rhr_abbreviation_the_layer_validator_misses, test_catches_resting_heart_rate_spelled_out, test_catches_recovery_contradiction, test_catches_gross_hrv_contradiction, test_hrv_within_daily_swing_does_not_fire, test_correct_numbers_do_not_fire, test_rhr_within_tolerance_does_not_fire, test_weight_loss_delta_is_not_treated_as_rhr_or_weight, test_grounded_trend_does_not_self_correct, test_recovery_trend_citing_canonical_does_not_fire, test_missing_facts_are_safe


**test_habitify_status_resolution.py** (12 tests): test_completed_resolves_to_completed, test_in_progress_today_resolves_to_pending, test_in_progress_past_day_resolves_to_failed, test_failed_passes_through, test_skipped_resolves_to_skipped_not_failed, test_monthly_periodicity_preserved, test_unknown_status_passes_through_safely, test_legacy_habits_field_still_present_and_correct, test_scheduled_today_is_true_for_current_registry, test_completion_pct_excludes_pending_today, test_completion_pct_past_day_unchanged, test_completion_pct_all_pending_today_returns_zero_not_nan


**test_hae_activity_failsafe.py** (6 tests): test_healthy_no_alert, test_steps_stale_while_partition_fresh_alerts, test_no_steps_at_all_is_severe, test_sustained_low_activity_alerts, test_sick_day_suppresses_alert_but_still_flags_metric, test_empty_partition_is_quiet


**test_hae_datatype_liveness_468.py** (0 tests): 


**test_hae_validation_483.py** (13 tests): test_validate_fields_skips_whole_item_checks, test_validate_fields_flags_out_of_range_as_warning, test_validate_fields_critical_on_implausible_glucose, test_validate_fields_accepts_sane_bp, test_validate_fields_warns_on_absurd_bp, test_merge_gate_blocks_critical_and_passes_clean, test_cgm_partial_day_is_still_cgm_by_cadence, test_fingerstick_cadence_is_manual, test_cgm_too_few_readings_falls_back_to_count, test_water_ml_factor_by_unit, test_generic_metrics_respects_ml_water_unit, test_generic_metrics_defaults_floz_water, test_generic_metrics_converts_kg_weight


**test_handler_type_hints.py** (2 tests): test_untyped_handler_count_at_or_below_baseline, test_typed_count_grew_or_equal_to_phase412


**test_health_auto_export.py** (0 tests): 


**test_health_window_guards.py** (2 tests): test_future_genesis_no_validation_exception, test_explicit_dates_honored


**test_hevy_adherence_wiring.py** (11 tests): test_pacific_date_of_rolls_utc_evening_back_a_day, test_pacific_date_of_bad_input_is_none, test_exact_hevy_routine_id_match, test_ad_hoc_when_no_routine, test_date_single_fallback, test_date_fallback_uses_pacific_day_not_utc, test_ambiguous_when_no_overlap, test_overlap_picks_best_candidate, test_derive_failure_is_non_fatal, test_tmpl_prefixed_movement_key_resolves_directly, test_title_resolved_movement_uses_cache


**test_hevy_common.py** (9 tests): test_normalize_workout_kg_pk_sk, test_normalize_workout_kg_volume, test_normalize_workout_lbs_converts_to_kg, test_normalize_workout_duration, test_normalize_workout_raw_ref_points_at_s3, test_normalize_workout_missing_id_raises, test_normalize_workout_top_level_id_accepted, test_verify_signature_direct_match, test_verify_signature_hmac_match


**test_hevy_compiler.py** (19 tests): test_create_body_includes_folder_id_and_template, test_update_body_omits_folder_id, test_unmappable_movement_raises, test_from_hevy_response_extracts_diff_keys, test_title_context_overrides_default_title, test_why_note_overrides_default_notes, test_update_body_also_takes_title_context, test_drop_set_type_maps_to_dropset_on_wire, test_normalize_set_type, test_unmappable_set_type_coerces_to_normal_on_wire, test_hevy_set_types_constant, test_sanitize_note_strips_control_chars_preserves_emoji, test_sanitize_note_applied_to_exercise_and_routine_notes, test_no_branches_notes_unchanged_backward_compat, test_branches_render_into_notes, test_branches_render_in_update_body_too, test_render_branches_note_empty_when_no_branches, test_branch_menu_reflects_reordering, test_round_trip_response_to_diff


**test_hevy_compiler_isolation.py** (1 tests): test_exercise_template_id_only_in_allowed_files


**test_hevy_restamp.py** (17 tests): test_noop_when_paused, test_noop_when_disabled, test_noop_when_budget_tier_3, test_preference_safe_default_when_no_recovery, test_preference_green_reaches_for_harder, test_preference_red_steps_down, test_pick_label_only_uses_present_branches, test_restamp_red_recommends_easier, test_restamp_yellow_keeps_as_written, test_restamp_never_removes_a_branch, test_restamp_never_touches_set_content, test_restamp_empty_branches, test_noop_when_no_pushed_routine, test_fail_open_on_unexpected_exception, test_unchanged_recommendation_no_repush, test_applies_and_repushes_on_change, test_conflict_fails_open


**test_hevy_routine_cron.py** (5 tests): test_noop_when_paused, test_noop_when_cron_disabled, test_noop_when_budget_tier_3, test_force_overrides_all_gates, test_cron_pushes_branch_model_not_ideal_floor_pair


**test_hevy_strength_repoint.py** (9 tests): test_weekly_digest_ex_hevy_workouts_maps_real_hevy_shape, test_weekly_digest_ex_hevy_workouts_empty_returns_none, test_weekly_digest_ex_hevy_workouts_handles_two_a_day_same_date, test_weekly_digest_query_range_list_boundary_includes_end_date_suffix, test_weekly_digest_strength_section_renders_with_hevy_data, test_daily_brief_fetch_hevy_workouts_maps_real_hevy_shape, test_daily_brief_fetch_hevy_workouts_no_data_returns_none, test_daily_brief_fetch_hevy_workouts_query_failure_fails_soft, test_daily_brief_training_report_renders_with_hevy_data


**test_hevy_template_cache.py** (6 tests): test_resolve_movement_returns_hint_on_miss, test_resolve_movement_loud_fail_on_missing_key, test_resolve_movement_loud_fail_on_no_hint, test_reconcile_custom_picks_title_match, test_reconcile_custom_disambiguates_by_muscle, test_reconcile_custom_raises_on_no_match


**test_hevy_write_client.py** (12 tests): test_api_key_header_set, test_auth_error_on_401, test_retryable_on_429, test_update_with_guard_refuses_on_mismatch, test_update_with_guard_passes_through_on_match, test_create_routine_recovers_orphan, test_create_routine_no_orphan_match_reraises_400, test_throttle_holds_calls_apart, test_get_passes_no_max_attempts_override, test_post_and_put_disable_retry, test_post_does_not_retry_on_5xx_at_transport_level, test_get_still_retries_on_5xx_at_transport_level


**test_historical_window.py** (10 tests): test_observatory_week_dated_window_and_flags, test_observatory_week_dateless_is_live, test_observatory_week_bad_date, test_observatory_week_future_clamps_to_today, test_observatory_week_empty_is_honest_200, test_vitals_dated_window_anchors, test_vitals_dateless_unchanged, test_vitals_honest_null_when_absent, test_vitals_bad_date, test_latest_item_asof_queries_on_or_before


**test_home_fold.py** (4 tests): test_loop_teaser_sits_inside_the_hero_copy, test_teaser_names_all_four_doors_in_loop_order, test_full_loop_diagram_not_regressed, test_constellation_caption_carries_the_scale


**test_http_retry.py** (7 tests): test_first_attempt_success, test_503_then_success_retries, test_401_raises_immediately, test_three_503s_raises_after_attempts, test_network_error_retries, test_max_attempts_one_disables_retry, test_max_attempts_none_keeps_default_policy


**test_hypotheses_serving.py** (4 tests): test_private_hypotheses_never_serve, test_verdict_trail_served, test_verdict_trail_null_before_first_check, test_archived_still_served_for_the_expired_count


**test_hypothesis_engine_v2.py** (0 tests): 


**test_iam_secrets_consistency.py** (4 tests): test_s1_all_iam_secrets_are_known, test_s2_no_deleted_secrets_in_iam, test_s3_all_known_secrets_referenced, test_s4_known_secrets_count_matches_architecture


**test_ingest_health.py** (17 tests): test_classify_error, test_update_outcome_first_success_from_empty, test_update_outcome_failure_increments_and_records_class, test_update_outcome_streak_accumulates_then_resets, test_update_outcome_attempted_false_keeps_prior_attempt_ts, test_evaluate_unknown_when_no_sentinel, test_evaluate_ok_recent_success, test_evaluate_unfed_but_healthy_does_not_alert, test_evaluate_below_buffer_stays_silent, test_evaluate_failing_streak_alerts_critical_for_auth, test_evaluate_failing_streak_non_auth_is_warning, test_evaluate_stale_attempt_alerts_even_with_zero_failures, test_evaluate_recent_attempt_not_stale, test_acceptance_source_erroring_every_run_alerts_with_zero_new_data, test_acceptance_genuinely_unfed_source_does_not_alert, test_emf_metric_line_shape, test_ingest_health_sk


**test_ingest_liveness_standalone.py** (8 tests): test_clean_run_records_success_sentinel, test_fatal_api_error_records_failure_and_raises, test_per_event_error_records_parse_failure_but_returns_200, test_notion_success_and_failure_paths_record_sentinel, test_dropbox_healthy_skip_and_failure_record_sentinel, test_framework_breaker_delegates_to_auth_breaker, test_pipeline_health_check_lists_only_emitting_sources, test_record_ingest_health_writes_sentinel_and_streak


**test_ingestion_transforms.py** (23 tests): test_whoop_recovery_scored_maps_all_fields, test_whoop_recovery_empty_and_unscored_return_empty, test_whoop_sleep_duration_and_aliases, test_whoop_sleep_picks_main_over_nap_and_counts_naps, test_whoop_sleep_empty_and_unscored_return_empty, test_whoop_cycle_scored, test_whoop_workout_maps_known_and_unknown_sport, test_withings_weight_value_scaling_and_lbs, test_withings_most_recent_group_wins, test_withings_empty_and_unknown_type, test_strava_normalize_core_and_conversions, test_strava_none_distance_yields_none_miles, test_strava_merges_zone_and_hr_recovery, test_strava_fetch_day_captures_evening_pt_activity, test_strava_fetch_day_assigns_each_activity_to_one_local_date, test_garmin_transform_passthrough_and_empty, test_reconcile_flags_dropped_activity, test_reconcile_clean_when_all_present_by_id, test_reconcile_does_not_flag_deduped_gps_drop_twin, test_gapfill_trailing_days_refetch_even_when_present, test_gapfill_trailing_zero_keeps_today_only_when_all_present, test_gapfill_trailing_still_reports_genuine_older_gap, test_trailing_refresh_policy_per_source


**test_integration_aws.py** (22 tests): test_i1_lambda_handlers_match_expected, test_i2_lambda_layer_version_current, test_i3_spot_check_lambda_invocability, test_i4_dynamodb_table_healthy, test_i5_required_secrets_exist, test_i6_eventbridge_rules_exist_and_enabled, test_i7_cloudwatch_alarms_exist, test_i8_s3_bucket_and_config_files, test_i9_dlq_empty, test_i10_mcp_lambda_responds, test_i11_data_reconciliation_running, test_i12_mcp_tool_call_response_shape, test_i13_freshness_checker_returns_valid_data, test_i14_canary_mcp_check_passes, test_i15_reserved_concurrency_guard, test_i16_recent_ingest_records_exist, test_i17_character_sheet_recent_record, test_i18_daily_brief_recently_invoked, test_i19_site_api_journey_contract, test_i20_pre_genesis_records_are_phase_tagged, test_i21_ddb_profile_matches_constants, test_i22_site_version_sha_on_main


**test_inter_coach_dialogue.py** (0 tests): 


**test_journal_extraction_v2.py** (12 tests): test_defense_pass_is_gone, test_field_mapping_v2_shape, test_prompt_asks_for_the_trio_in_one_call, test_grounded_hint_survives, test_ungrounded_quote_is_dropped, test_grounding_normalizes_whitespace_and_case, test_malformed_hints_are_dropped, test_apply_enrichment_runs_the_gate, test_floors_are_the_same_20_words, test_enricher_scaffolding_gone, test_analyzer_key_fetch_gone, test_call_anthropic_raw_accepts_dict_and_legacy_request


**test_journal_mood_attunement_549.py** (6 tests): test_handler_injects_journal_mood_for_mind_coach, test_handler_omits_journal_mood_for_other_coaches, test_handler_omits_journal_mood_when_signal_thin, test_build_user_message_surfaces_for_mind_coach, test_build_user_message_hides_for_sleep_coach, test_mind_coach_json_has_low_sentiment_protocol


**test_journal_registries.py** (0 tests): 


**test_journal_signal_wiring.py** (9 tests): test_mind_data_signal_lands_from_journal_entries, test_mind_data_empty_journal_is_honest_absence, test_mind_data_tolerates_unenriched_entries, test_trajectory_reads_written_enrichment_names, test_unedited_enriched_entry_is_not_stale, test_entry_edited_after_enrichment_is_stale, test_missing_or_garbage_timestamps_fall_back_to_skip, test_preserve_enrichment_copies_enriched_and_defense_fields, test_preserve_enrichment_noop_when_no_existing_item


**test_js_parse_gate_377.py** (3 tests): test_sync_script_exists, test_parse_gate_present_and_module_mode, test_gate_runs_before_the_s3_upload


**test_lambda_handlers.py** (6 tests): test_i1_source_file_exists, test_i2_source_file_syntax_valid, test_i3_handler_signature, test_i4_handler_has_try_except, test_i5_no_orphaned_lambda_files, test_i6_mcp_server_handler


**test_lambda_map_regions.py** (3 tests): test_r1_region_field_is_known, test_r2_declared_region_matches_live, test_r3_no_silent_us_east_1_only


**test_lambda_size_gate.py** (2 tests): test_no_new_lambda_god_modules, test_grandfathered_set_does_not_rot


**test_lambda_sizing.py** (5 tests): test_ingestion_stack_memory_limits, test_compute_stack_memory_limits, test_web_stack_memory_limits, test_email_stack_memory_limits, test_no_3008mb_anywhere


**test_last_sync.py** (4 tests): test_last_sync_reads_real_write_stamps, test_missing_stamp_is_null_never_invented, test_sync_strip_sources_pinned, test_frontend_ticks_and_earns_the_glow


**test_layer_version_consistency.py** (7 tests): test_lv1_cdk_uses_layer_name_not_hardcoded_arn, test_lv2_all_consumers_referenced_in_cdk, test_lv3_all_layer_modules_exist_on_disk, test_lv4_layer_modules_match_build_script, test_lv5_layer_version_only_in_constants, test_lv4_consumer_count_sanity, test_lv6_cdk_constant_matches_latest_published_layer


**test_logger_discipline.py** (2 tests): test_print_count_baseline, test_no_print_in_new_lambdas


**test_macrofactor_unknown_csv.py** (2 tests): test_unknown_csv_archives_and_raises, test_empty_csv_still_skips_quietly


**test_margaret_editor_pass.py** (40 tests): test_extract_json_handles_raw_and_fenced, test_sanitize_critique_clamps_score_and_bounds_lists, test_sanitize_critique_rejects_non_dict, test_sanitize_critique_bad_score_defaults_safe, test_needs_revision_none_critique, test_needs_revision_high_score_clean_critique_skips, test_needs_revision_low_score_triggers, test_needs_revision_cut_findings_trigger_even_with_high_score, test_needs_revision_callback_debt_triggers, test_apply_revision_skips_when_not_needed, test_apply_revision_keeps_original_on_call_failure, test_apply_revision_keeps_original_on_empty_revision, test_apply_revision_rejects_degenerate_truncation, test_apply_revision_rejects_fabricated_numbers, test_apply_revision_rejects_privacy_violation, test_apply_revision_accepts_a_clean_tightened_revision, test_editors_note_eligible_no_prior_note, test_editors_note_eligible_respects_min_days, test_editors_note_eligible_bad_date_fails_open, test_extract_editors_note_requires_eligibility, test_extract_editors_note_empty_string_is_none, test_extract_editors_note_grounding_gate, test_extract_editors_note_privacy_gate, test_extract_editors_note_clean_note_passes, test_splice_editors_note_before_signature, test_splice_editors_note_appends_when_no_signature_found, test_splice_editors_note_noop_on_empty_note, test_run_pass_no_critique_is_untouched_and_makes_one_call, test_run_pass_clean_critique_skips_revision_makes_one_call, test_run_pass_low_score_triggers_exactly_two_calls_and_applies_revision, test_run_pass_due_callbacks_flow_into_critique_prompt, test_build_narrator_fallback_when_no_config, test_build_narrator_uses_board_config_when_present, test_critique_prompt_carries_privacy_rules, test_chronicle_invokes_margaret_pass_after_adr104_before_ai3, test_chronicle_margaret_pass_is_budget_gated, test_chronicle_uses_haiku_for_margaret_not_sonnet, test_has_board_detection_excludes_editors_note, test_layer_carries_the_new_module, test_budget_guard_pauses_chronicle_editor_at_tier_one


**test_mcp_orphan_tools.py** (3 tests): test_no_unexpected_orphans, test_known_orphans_still_orphans, test_orphan_count_doesnt_grow


**test_mcp_rate_limit.py** (4 tests): test_under_limit_allows, test_over_limit_blocks_then_window_slides, test_legit_multistep_flow_not_blocked, test_non_rate_limited_tool_never_blocks


**test_mcp_registry.py** (7 tests): test_r1_all_imports_resolve, test_r2_all_fn_references_exist, test_r3_schema_structure, test_r4_no_duplicate_tool_names, test_r5_tool_count_in_range, test_r6_registry_syntax_valid, test_r7_all_tool_modules_parseable


**test_meal_grouper.py** (10 tests): test_conservation_each_day, test_every_entry_assigned_exactly_once, test_0618_blob_splits_into_three, test_0616_tuna_lunch_uncategorized_and_snacks_peeled, test_0616_gap_split_tacos_dessert, test_0615_yogurt_and_katsu, test_determinism, test_no_mutation_of_raw, test_chicken_salmon_anchor_set_single_meal, test_low_confidence_is_uncategorized_not_mixed


**test_meal_projection.py** (5 tests): test_never_writes_raw_partition, test_items_stamped, test_idempotent_rewrite, test_prunes_stale_ordinals, test_dry_run_writes_nothing


**test_measurable_metrics.py** (4 tests): test_allowlist_is_derived_from_sources_cannot_drift, test_every_normalizer_target_is_measurable, test_normalize_basic_and_prose, test_both_coach_modules_share_the_single_source


**test_memoir_gate.py** (6 tests): test_no_refuted_learnings_needs_no_citation, test_pure_highlight_reel_fails_when_a_miss_exists, test_citing_the_specific_metric_passes, test_generic_honest_language_passes_without_naming_the_metric, test_refuted_markers_ignores_confirmed_records, test_empty_learnings_list_needs_no_citation


**test_methods_registry.py** (0 tests): 


**test_mirror_widget.py** (4 tests): test_widget_is_purely_client_side, test_reads_only_matthews_public_numbers, test_framing_is_n1_and_advice_free, test_honest_states


**test_model_versions.py** (2 tests): test_cdk_stacks_use_valid_model_ids, test_constants_model_default_is_valid


**test_muscle_volume_completeness.py** (5 tests): test_includes_latest_when_aggregation_reaches_high_water, test_stale_when_newer_in_window_session_missed, test_session_beyond_window_is_not_stale, test_rest_days_at_tail_are_not_stale, test_no_hevy_data_at_all


**test_mypy_clean_modules.py** (1 tests): test_mypy_clean_on_shared_modules


**test_no_real_names_in_chronicle.py** (2 tests): test_chronicle_source_names_no_real_public_figures, test_fallback_prompt_references_the_fictional_board


**test_notion_sync_476.py** (6 tests): test_build_sk_stable_for_multi_per_day, test_build_sk_single_per_day_unchanged, test_query_filter_includes_last_edited_time, test_reconcile_removes_orphans_keeps_written, test_archive_writes_per_page_s3_key, test_archive_best_effort_never_raises


**test_now_remainder_batch.py** (22 tests): test_habitify_refreshes_trailing_day, test_habitify_past_day_pending_resolves_failed, test_habitify_today_pending_stays_pending, test_supplement_bridge_preserves_same_day_manual_log, test_supplement_bridge_no_existing_record, test_validator_whoop_workout_subrecords_use_own_schema, test_validator_whoop_night_checks_written_name, test_validator_todoist_matches_written_shape, test_validator_supplements_matches_written_shape, test_validator_eightsleep_hr_avg_range_fires, test_eightsleep_401_relogin_persists_token, test_framework_writeback_failure_is_loud, test_phase_for_date_is_public_and_correct, test_all_standalone_writers_stamp_phase, test_measurements_multirow_csv_ingests_all_sessions, test_measurements_session_number_is_date_rank, test_measurements_records_stamp_phase, test_measurements_missing_required_row_reported_not_fatal, test_apple_health_xml_lambda_deleted, test_apple_health_backfill_hard_guarded, test_garmin_has_no_schedule, test_health_check_expected_secrets_are_real


**test_nudge_finding_rate_limit.py** (5 tests): test_nudge_uses_ddb_per_category_and_blocks, test_nudge_allowed_returns_200, test_submit_finding_uses_ddb_endpoint_and_limit, test_submit_finding_allowed_writes, test_nudge_in_memory_fallback_still_limits


**test_numeric.py** (9 tests): test_float_to_decimal, test_dict_recursion, test_list_recursion, test_bool_preserved, test_int_unchanged, test_string_unchanged, test_decimals_to_float, test_safe_float_default, test_shim_imports


**test_og_coach_cards.py** (6 tests): test_coach_card_is_1200x630, test_identity_resolves_from_board, test_identity_falls_back_without_board, test_build_all_only_signed_recipes, test_unsigned_recipe_excluded, test_load_signed_recipes_from_bundle


**test_og_moments.py** (7 tests): test_week_recap_moment_written_with_iso_week_permalink, test_empty_stats_mean_no_recap_moment, test_board_answer_moment_bakes_published_content_only, test_prediction_moment_key_matches_frontend_composite, test_prediction_sweep_only_mints_decided_calls, test_cloudfront_routes_moments_to_generated_origin, test_share_affordance_exists_on_the_three_surfaces


**test_pacific_date_selection.py** (7 tests): test_pacific_today_evening_returns_prior_utc_day, test_pacific_today_midday_agrees_with_utc, test_pacific_now_is_tz_aware_pacific, test_mcp_core_pacific_today_matches, test_circadian_handler_uses_pacific_today, test_evening_nudge_handler_uses_pacific_today, test_nutrition_latest_complete_day_is_pacific


**test_panelcast_hold_aging.py** (10 tests): test_hold_tags_class_and_inits_metadata, test_re_hold_preserves_first_held_and_bumps_retry, test_unknown_hold_class_defaults_to_safety, test_sweep_skips_safety_hold, test_sweep_skips_too_fresh, test_sweep_skips_abandoned, test_sweep_skips_retry_capped, test_sweep_cleans_already_published, test_sweep_retries_eligible_quality_hold, test_sweep_dry_run_does_not_regenerate


**test_panelcast_voice_gender.py** (1 tests): test_persona_voice_matches_gender


**test_permalink_unification_733.py** (7 tests): test_rss_items_link_per_post_permalink, test_sitemap_includes_published_post_urls, test_every_post_has_a_subscribe_cta, test_every_post_has_a_share_affordance, test_share_uses_the_crawlable_permalink, test_share_handler_is_wired_after_render, test_share_has_no_blocking_dialog_fallback


**test_persona_core.py** (13 tests): test_voice_block_renders_spec_fields, test_voice_block_handles_junk, test_voice_block_caps_hold, test_every_operational_coach_has_a_loadable_spec, test_unknown_coach_fails_soft, test_board_system_prompt_carries_the_voice_core, test_board_ask_loads_memory_and_episodic_recall, test_board_answer_written_back_after_grounding_gate, test_interaction_record_shape, test_expert_prompt_sources_the_persona_core, test_summarizer_meta_is_registry_derived, test_registry_meta_resolves_canonical_names, test_summarizer_gathers_and_folds_interactions


**test_persona_registry.py** (13 tests): test_registry_loads_and_is_shaped, test_every_persona_has_required_fields, test_operational_personas_have_coach_fields, test_operational_names_are_distinct, test_config_coaches_match_operational_personas, test_voice_spec_refs_exist_and_match, test_persona_registry_constant_matches_json, test_engine_and_evaluator_and_orchestrator_match_operational, test_intelligence_common_short_ids_match, test_board_persona_keys_resolve, test_accessors_resolve_known_coach, test_lead_persona_nonoperational_with_distinct_voice, test_podcast_voice_map_complete_and_unique


**test_personal_baselines.py** (1 tests): test_mcp_compute_ewa_delegates


**test_phase3_grounding.py** (8 tests): test_build_data_summary_prefers_primary_whoop, test_build_data_summary_falls_back_to_whoop, test_recovery_zero_is_honoured_not_skipped, test_sane_vitals_pass_clean, test_impossible_recovery_warns, test_impossible_rhr_warns, test_shared_prompt_carries_authoritative_facts, test_canonical_protein_target_not_hardcoded_190_path


**test_phase_filter_checkpoint.py** (12 tests): test_genesis_date_matches_constants, test_checkpoint_due_dates_derive_from_genesis, test_status_before_any_checkpoint_is_all_upcoming, test_status_on_due_date_is_due_with_diagnostic_snapshot, test_status_past_due_date_stays_due_until_recorded, test_record_before_due_date_is_rejected, test_record_on_due_date_succeeds_and_persists, test_recording_re_arms_the_next_checkpoint_not_lapse, test_double_record_without_force_is_rejected, test_double_record_with_force_overwrites, test_scan_include_pilot_bypasses_finds_known_site, test_diagnostic_snapshot_reports_scoped_sources


**test_phase_taxonomy.py** (8 tests): test_every_live_family_classifies, test_unknown_source_raises_not_defaults, test_unknown_pk_raises, test_source_decisions, test_email_log_family_is_system_state, test_platform_memory_split, test_pk_rules, test_helper_predicates


**test_platform_logger.py** (0 tests): 


**test_platform_stats_truth.py** (5 tests): test_mcp_tools_matches_registry, test_adr_count_matches_decisions_doc, test_test_count_matches_suite, test_lambda_count_matches_cdk, test_alarms_and_sources_share_the_maintained_fact


**test_podcast_v2.py** (0 tests): 


**test_portrait_raster.py** (7 tests): test_path_parser_handles_core_commands, test_cubic_bezier_flattens_to_polyline, test_relative_and_arc_commands_parse, test_render_mono_produces_transparent_ink_stamp, test_render_full_paints_palette_tones, test_render_is_deterministic, test_every_signed_recipe_renders


**test_portrait_recipes.py** (9 tests): test_placeholder_fixtures_validate, test_all_checked_in_recipes_validate, test_generated_bundle_never_drifts, test_unsigned_recipes_are_not_bundled, test_bundle_only_contains_signed_config_recipes, test_schema_rejects_the_named_failure_modes, test_tone_palette_contract, test_layer_registry_matches_the_runbook, test_fixtures_stay_out_of_config


**test_prediction_gradability.py** (0 tests): 


**test_prediction_metadata_stamp_725.py** (0 tests): 


**test_predictions_one_store_726.py** (0 tests): 


**test_presence_endpoint.py** (4 tests): test_projection_is_fail_closed, test_honest_null_before_first_compute, test_surfaces_return, test_read_error_is_shaped


**test_privacy_guard.py** (10 tests): test_clean_text_passes, test_real_full_name_blocked, test_real_surname_blocked, test_vice_blocked, test_subject_name_not_a_false_positive, test_common_words_not_false_positives, test_scrub_redacts_inline, test_stale_draft_detection, test_edible_blocked, test_vice_keywords_superset_of_content_filter


**test_protein_contract.py** (4 tests): test_producer_defines_both_protein_lines, test_serving_layer_reads_the_same_keys_and_defaults, test_no_hardcoded_protein_target_in_serving_layer, test_floor_served_as_its_own_field


**test_public_surface_pii_guard.py** (6 tests): test_live_site_is_clean, test_blocked_vice_keyword_is_caught, test_structural_pii_is_caught, test_allowlisted_email_passes, test_literal_denylist_arm_when_provided, test_denylist_is_not_committed_in_cleartext


**test_public_write_hardening.py** (7 tests): test_vote_rejects_unknown_catalog_id, test_vote_rejects_private_challenge, test_vote_503_when_catalog_unavailable, test_vote_accepts_known_catalog_id, test_checkin_dedups_same_date, test_checkin_keeps_distinct_dates, test_submit_finding_id_is_content_stable


**test_quarter_utils.py** (5 tests): test_quarter_key_maps_month_to_quarter, test_previous_quarter_key_within_year, test_previous_quarter_key_year_rollover, test_quarter_bounds_round_trip, test_quarter_bounds_exact_dates


**test_rate_limiter.py** (7 tests): test_bucket_truncates_to_window, test_first_request_allowed, test_at_limit_blocks_and_returns_retry, test_ddb_error_fails_open, test_ddb_error_fails_closed_when_requested, test_pk_starts_with_rate_prefix_for_iam_allowlist, test_ttl_set_only_on_first_write


**test_reader_engagement.py** (6 tests): test_predict_week_fails_closed_without_subject, test_predict_week_happy_path_increments_and_dedupes, test_predict_week_rejects_bad_inputs, test_predict_week_tally_inactive, test_board_question_happy_path, test_board_question_rejects_short_and_vice_and_ratelimit


**test_readiness_forward_dated.py** (1 tests): test_forward_dated_surfaces_real_data_date


**test_reading_auto_reason.py** (4 tests): test_recommendation_persists_open_rec_with_reason_string, test_status_reading_auto_writes_coach_why, test_hand_authored_coach_why_never_overwritten, test_no_rec_no_note_and_other_statuses_untouched


**test_reading_constellation.py** (6 tests): test_idea_id_is_stable, test_extract_grounded_and_failsoft, test_is_ready_gate, test_idea_index_and_enumeration, test_constellation_endpoint_honest_empty, test_constellation_endpoint_ready_when_enough


**test_reading_enrich.py** (6 tests): test_happy_path_tags_and_difficulty, test_fenced_json_parsed, test_subscores_clamped_and_capped, test_fail_soft_on_bad_json, test_fail_soft_on_exception, test_no_title_returns_empty


**test_reading_keys.py** (7 tests): test_book_id_is_stable_and_isbn_normalized, test_book_id_priority_isbn_over_title, test_olid_used_when_no_isbn, test_key_constructors, test_state_gsi_stamp, test_session_gsi_stamp, test_recall_due_gsi_is_sparse


**test_reading_onboarding.py** (6 tests): test_question_bank_present, test_synthesis_happy_path, test_accepts_list_of_qa, test_no_answers_is_empty, test_fail_soft_on_exception, test_fail_soft_on_bad_json


**test_reading_recall.py** (7 tests): test_next_due_uses_intervals, test_advance_ratchets_on_gist, test_retention_is_n_gated, test_retention_ignores_unscored_probes, test_score_gist_happy_and_failsoft, test_record_answer_advances_and_scores, test_first_probe


**test_reading_recall_sweep.py** (2 tests): test_sweep_writes_snapshot_and_metric, test_sweep_empty_is_clean


**test_reading_recommender.py** (10 tests): test_reason_string_is_decomposed_and_present, test_anti_goggins_penalizes_goal_domain, test_breadth_gain_prefers_thin_slice, test_red_week_subtracts_the_doorstop, test_low_n_forces_propose_and_dispose, test_high_n_shortlist_surfaces_multiple, test_empty_candidates_is_honest, test_whiplash_penalty_on_genre_lurch, test_phase1_weights_favor_capacity_completion, test_resonance_lifts_and_appears_in_reason


**test_reading_store.py** (14 tests): test_current_and_queue_by_status, test_history_by_date_range, test_notes_for_book, test_due_recalls_sparse_and_thresholded, test_clearing_next_due_drops_from_index, test_wheel_distribution_joins_domain_tags, test_track_record, test_idea_and_edges, test_add_book_writes_book_and_state, test_add_book_merges_enrichment, test_finish_and_abandon_transitions, test_abandon_requires_reason, test_invalid_status_rejected, test_update_cover_key


**test_reading_visibility.py** (8 tests): test_projection_drops_structural_and_injected, test_no_private_field_survives, test_recall_is_never_public, test_retention_score_never_public, test_note_private_unless_public_flag, test_profile_exposes_only_wheel, test_unknown_entity_type_denied, test_project_list_drops_private_members


**test_recovery_authoring.py** (15 tests): test_e3_stale_volume_blocks_authoring, test_gate_passes_on_complete_fresh_inputs, test_gate_flags_missing_recovery, test_gate_flags_stale_recovery, test_e1_e2_yellow_default_rendered, test_e4_red_branch_always_present, test_e5_lower_of_rule_and_feel_downgrade_only, test_e7_days_authored_independently, test_e8_late_week_caps_green_to_quality, test_deep_deficit_caps_green_to_quality, test_early_tissue_ramp_caps_green, test_e11_session_block_always_present, test_subtract_only_invariant, test_consecutive_days_counts_back_from_target, test_bands_match_whoop_thresholds


**test_recovery_deficit_overlay_388.py** (7 tests): test_no_coefficient_ever_in_the_payload, test_below_threshold_stays_purely_descriptive, test_missing_days_render_as_explicit_gaps_not_interpolated, test_recovery_paired_with_the_prior_days_deficit_not_the_same_day, test_strong_negative_relationship_yields_lower_after_heavier_language, test_no_relationship_yields_neutral_caption, test_empty_inputs_dont_crash


**test_relationship_state_536.py** (0 tests): 


**test_remediation_agent.py** (14 tests): test_coherence_ok_record_is_not_a_signal, test_coherence_alarm_surfaces_only_flagging_findings, test_coherence_missing_artifact_is_fail_soft, test_coherence_is_in_the_actionable_signal_set, test_automerge_allowlist_has_no_content_paths, test_automerge_denylist_blocks_bedrock_and_prompts, test_skeleton_report_lists_every_signal, test_annotate_acked_marks_unexpired_only, test_update_ack_ledger_acks_needs_human_and_stale, test_update_ack_ledger_expires_old_entries, test_earn_check_noop_outside_auto, test_earn_check_flags_dialback_after_window, test_earn_check_resets_window_when_earned, test_prompt_instructs_incremental_report_and_ack_skip


**test_render_portraits_parity.py** (4 tests): test_portrait_pngs_in_sync_with_recipes, test_manifest_covers_every_signed_recipe, test_recipe_hash_is_stable_and_changes_on_edit, test_all_png_files_exist


**test_request_validator.py** (18 tests): test_legit_get_passes, test_legit_post_passes, test_oversized_body_rejected, test_oversized_query_string_rejected, test_path_traversal_rejected, test_xss_in_query_rejected, test_sql_injection_pattern_rejected, test_null_byte_rejected, test_bad_user_id_format_rejected, test_bad_date_format_rejected, test_bad_source_format_rejected, test_validate_user_id_passes, test_validate_user_id_rejects_invalid, test_validate_date_passes, test_validate_date_rejects_invalid, test_validate_source_rejects_unknown, test_validate_source_allows_unknown_with_flag, test_validate_int_param_range


**test_retry_convergence_501.py** (7 tests): test_whoop_fetch_endpoint_retries_on_503, test_whoop_fetch_endpoint_raises_immediately_on_401, test_todoist_api_get_retries_on_503, test_todoist_api_get_now_retries_network_errors, test_weather_fetch_day_retries_on_503, test_withings_gap_fill_uses_one_range_call_for_multiple_dates, test_withings_authenticate_resets_range_cache


**test_role_policies.py** (7 tests): test_r1_ddb_read_requires_kms_decrypt, test_r2_ddb_write_requires_kms_generate, test_r3_kms_resource_is_scoped, test_r4_no_unexpected_wildcard_resources, test_r5_secrets_resources_are_scoped, test_r6_policy_is_non_empty, test_r7_no_duplicate_sids


**test_routine_generator.py** (15 tests): test_generates_ideal_plus_floor_for_lifting_day, test_re_entry_triggered_after_seven_days, test_subtract_only_invariant_red_recovery_shrinks_budget, test_add_load_flag_does_not_increase_budget_today, test_bounded_outputs_session_set_ceiling, test_catalog_has_skill_tier_1_for_each_landmark_muscle, test_floor_session_uses_skill_tier_1_only, test_inputs_snapshot_recorded, test_rest_day_returns_placeholder_only, test_exercise_notes_populated_from_history_index, test_exercise_notes_off_mode_yields_empty_notes, test_emit_branch_model_folds_variants_into_primary, test_emit_branch_model_includes_re_entry_when_present, test_emit_branch_model_none_on_empty, test_emit_branch_model_branch_carries_its_own_exercises


**test_routine_ir.py** (6 tests): test_round_trip_preserves_structure, test_serialize_emits_decimal_for_floats, test_deserialize_empty_raises, test_schema_version_pinned, test_branches_default_empty_backward_compat, test_branch_round_trip_preserves_nested_content


**test_routine_repo.py** (4 tests): test_put_versioned_writes_history_and_pointer, test_put_versioned_refuses_overwrite_on_conditional_failure, test_upsert_id_map_writes_both_directions, test_lookup_round_trip


**test_routine_title.py** (10 tests): test_format_title_renders_phase_type_n_y, test_format_title_truncates_at_limit, test_format_title_re_entry_is_gentle_no_counters, test_why_note_re_entry_is_kind, test_why_note_picks_red_recovery, test_why_note_picks_portfolio_guard, test_why_note_floor_variant_is_explicit, test_build_context_n_and_y_from_performed, test_build_context_first_of_type_is_n1_but_y_tracks_total, test_build_context_n_resets_on_phase_advance


**test_routine_title_counters.py** (16 tests): test_resolve_uses_stored_sticker_first, test_resolve_falls_back_to_nearest_preceding_routine, test_resolve_picks_latest_not_first, test_resolve_none_when_no_preceding_routine, test_resolve_exact_hevy_routine_link_beats_date, test_resolve_falls_back_to_date_when_link_unknown, test_resolve_no_hevy_id_uses_date, test_seed_next_push_counts_two, test_seed_next_pull_counts_one, test_planned_but_skipped_does_not_inflate_n, test_cross_source_duplicate_counts_once_in_n, test_y_counts_distinct_then_plus_one, test_y_skipped_session_not_counted, test_title_contract_shape, test_title_contract_for_pull_legs, test_re_entry_is_kind_no_counters


**test_scenario_explorer.py** (0 tests): 


**test_secret_references.py** (4 tests): test_sr1_all_secret_references_are_known, test_sr2_no_deleted_secret_references, test_sr3_secret_names_follow_convention, test_sr4_secret_references_found


**test_session_postflight.py** (3 tests): test_flags_the_lambda_whose_zip_is_missing_a_root_module, test_all_complete_returns_empty, test_download_error_is_fail_soft_not_a_false_alarm


**test_shared_modules.py** (66 tests): test_empty_blocked, test_none_blocked, test_too_short_blocked, test_truncated_blocked, test_good_text_passes, test_dangerous_training_red_recovery, test_aggressive_borderline_warns, test_low_cal_blocked, test_causation_warns, test_generic_phrases_warn, test_sanitized_text_fallback, test_sanitized_text_original, test_fallbacks_all_types, test_validate_json_none_blocked, test_validate_json_missing_key, test_validate_json_ok, test_get_logger_type, test_get_logger_singleton, test_set_date, test_set_correlation_id, test_info_json_output, test_positional_args, test_helpers_no_raise, test_check_sick_day_none, test_check_sick_day_found, test_check_sick_day_decimal, test_check_sick_day_ddb_error, test_get_sick_days_range_empty, test_get_sick_days_range_error, test_write_sick_day_fields, test_write_sick_day_no_reason, test_delete_sick_day, test_d2f_decimal, test_d2f_nested, test_avg_basic, test_avg_none_ignored, test_avg_empty, test_avg_all_none, test_fmt_value, test_fmt_none, test_fmt_with_unit, test_fmt_num, test_fmt_num_none, test_safe_float_present, test_safe_float_missing, test_safe_float_default, test_dedup_different_sports, test_dedup_removes_duplicate, test_dedup_empty, test_normalize_whoop_sleep, test_ex_whoop_from_list, test_ex_whoop_empty, test_ex_withings_latest, test_banister_zero_input, test_banister_with_training, test_validate_whoop_ok, test_validate_whoop_out_of_range, test_validate_empty_record, test_validation_result_structure, test_list_supported_sources, test_call_anthropic_has_output_type_param, test_ai_validator_importable, test_ai_output_type_importable, test_bod_caller_passes_output_type, test_journal_caller_passes_output_type, test_email_lambdas_dont_call_anthropic_directly


**test_silent_failure_heartbeats.py** (3 tests): test_heartbeat_helper_is_breaching_silence_detector, test_every_detector_has_both_a_problem_alarm_and_a_heartbeat, test_heartbeats_are_declared_via_the_helper


**test_site_a11y_landmarks.py** (9 tests): test_legacy_homepage_has_skip_link, test_legacy_homepage_has_main_landmark, test_legacy_homepage_gauges_marked_aria_hidden, test_subscribe_has_skip_link_and_main, test_legacy_text_muted_token_passes_contrast, test_legacy_email_cta_template_uses_h2_not_h3, test_v4_doors_have_skip_link_and_main, test_v4_tokens_define_reduced_motion_and_both_modes, test_v4_doors_link_tokens_first


**test_site_api_agents.py** (10 tests): test_empty_week_is_honest, test_week_boundaries_anchor_to_monday, test_coherence_alarm_surfaces, test_famous_case_grounding_catch, test_canary_budget_skip_is_info, test_remediation_raw_never_leaks, test_automerge_decision_renders, test_blocked_content_is_filtered, test_bad_week_param_defaults_gracefully, test_no_query_params_returns_current_week


**test_site_api_reading.py** (5 tests): test_empty_shelf_is_honest, test_shelf_joins_book_and_state_public_only, test_recall_and_retention_never_in_overview, test_overview_wheel_and_streak, test_overview_profile_exposes_only_wheel


**test_site_api_routes.py** (7 tests): test_routes_dict_parses, test_no_duplicate_paths, test_no_duplicate_handlers, test_all_handlers_defined, test_paths_well_formed, test_allowed_methods_use_valid_verbs, test_dispatch_call_exists_in_handler


**test_site_api_write_scope.py** (5 tests): test_leadingkeys_cover_every_site_api_write, test_write_call_site_canary, test_ai_leadingkeys_cover_every_ai_lambda_write, test_ai_write_call_site_canary, test_ai_interaction_write_is_putitem_only


**test_site_review_bindings.py** (0 tests): 


**test_source_enumeration_drift.py** (10 tests): test_pipeline_health_check_derives, test_qa_smoke_tiers_derive, test_data_reconciliation_derives, test_mcp_config_derives, test_data_export_derives_from_taxonomy, test_monitoring_stack_alarm_tuple_matches_registry, test_data_sources_json_is_generated, test_raw_layouts_document_the_three_generations, test_freshness_surfaces_unchanged_by_498, test_weather_joined_freshness_surfaces_470


**test_source_registry.py** (9 tests): test_quiet_stretch_does_not_page, test_all_behavioral_sources_stale_still_no_page, test_whoop_outage_still_pages, test_mixed_staleness_counts_only_infra, test_behavioral_classification_complete, test_passive_pipes_stay_infra, test_no_data_query_error_pages, test_registry_paused_never_monitored, test_registry_thresholds_have_rationale_values


**test_ss_tail.py** (2 tests): test_episode_angle_rotates_deterministically, test_episode_angle_handles_bad_input


**test_stance_event_refresh_534.py** (0 tests): 


**test_state_of_matthew_552.py** (0 tests): 


**test_stats_core.py** (0 tests): 


**test_stats_refresh_recovery.py** (4 tests): test_recovery_status_pairs_with_value, test_recovery_status_never_colors_a_missing_reading, test_get_latest_finalized_skips_unscored_today, test_get_latest_finalized_empty_when_none_scored


**test_strava_reconcile_window.py** (2 tests): test_window_edge_activity_is_not_a_false_positive, test_genuinely_missing_activity_still_reported


**test_subscriber_email_template.py** (5 tests): test_build_subscriber_email_basic, test_build_subscriber_email_no_signal_data, test_extract_chronicle_preview, test_extract_chronicle_preview_empty, test_bug_fix_subscriber_email_variable


**test_sync_doc_metadata_check.py** (4 tests): test_check_exits_nonzero_on_drift, test_check_exits_zero_when_current, test_check_and_apply_are_mutually_exclusive, test_check_is_clean_on_repo_head


**test_tdee_deficit_chain_484.py** (9 tests): test_resolves_canonical_expenditure_kcal, test_resolves_legacy_field_generations, test_scans_backward_to_most_recent_populated_record, test_prefers_newest_when_multiple_carry_expenditure, test_missing_zero_and_empty_yield_none, test_summary_ingest_writes_canonical_tdee_kcal, test_summary_ingest_omits_tdee_when_no_expenditure, test_mifflin_estimate_from_weight, test_mifflin_none_on_missing_weight


**test_timezone_discipline.py** (1 tests): test_no_fixed_offset_or_naive_mixed_pacific_math


**test_todoist_filters.py** (7 tests): test_get_filtered_tasks_uses_filter_endpoint_with_query_param, test_get_filtered_tasks_paginates, test_get_active_tasks_paginates_past_page_cap, test_mcp_list_all_tasks_routes_filter_to_filter_endpoint, test_large_active_backlog_does_not_fire_fatigue, test_high_pressing_load_plus_bad_habits_fires, test_high_pressing_load_but_good_habits_does_not_fire


**test_tools_hevy_routine.py** (17 tests): test_invalid_action_returns_error, test_commit_requires_routine_id, test_archive_requires_routine_id, test_dry_run_does_not_call_write_client, test_archive_calls_update_not_delete, test_commit_handles_orphan_created, test_draft_custom_requires_exercises, test_draft_custom_unknown_movement_errors_loudly, test_draft_custom_builds_ir_lb_to_kg_count_and_supersets, test_draft_custom_resolves_arbitrary_exercise_via_index, test_make_resolver_short_circuits_tmpl_keys, test_draft_custom_unknown_offers_index_suggestions, test_draft_custom_auto_creates_missing_exercise, test_draft_custom_does_not_create_from_bare_movement_key, test_infer_exercise_type_from_set_shape, test_dry_run_falls_back_to_reconcile_by_title, test_archive_local_only_when_never_pushed


**test_tools_reading.py** (18 tests): test_shelf_groups_by_status, test_recommendation_empty_queue_notes, test_recommendation_ranks_queue_with_reason, test_profile_absent_notes_onboarding, test_constellation_honest_empty, test_due_recalls_shape, test_invalid_action_errors, test_add_book_dry_run_then_commit, test_add_book_requires_title, test_add_book_triggers_cover_fetch, test_add_book_cover_failure_is_soft, test_update_status_abandon_requires_reason, test_log_session_commit, test_onboard_returns_questions_without_answers, test_dry_run_default_is_preview, test_debrief_starts_the_retention_clock, test_answer_recall_scores_and_advances, test_answer_recall_requires_answer


**test_traffic_digest.py** (4 tests): test_parse_filters_assets_api_bots_and_non200, test_aggregate_counts_and_returners, test_no_raw_ip_retained, test_empty_logs_safe


**test_training_load.py** (14 tests): test_kilojoules_convert_to_tss_points, test_walk_scores_by_moving_time, test_hr_backed_cardio_uses_intensity_squared, test_unknown_cardio_falls_back_to_default_rate, test_zero_duration_zero_load, test_rest_after_normal_block_reads_fresh_not_saturated, test_heavy_recent_block_reads_fatigued_within_band, test_walk_only_days_carry_load, test_walk_and_lift_same_day_are_additive, test_multi_device_duplicate_walk_not_double_counted, test_basis_note_flags_proxy_loads, test_basis_counts_and_shares, test_day_key_falls_back_to_sk, test_rest_tsb_scores_well_on_all_three_bands


**test_training_notes.py** (16 tests): test_cycling_progression_level_deterministic, test_standing_calf_equipment_and_form, test_seated_calf_new_machine, test_pallof_sentiment_positive_novel, test_farmers_limiter_and_logging_quirk, test_pain_net_fires_on_synthetic_with_llm_off, test_pain_net_does_not_fire_on_muscular_burn, test_pain_net_excludes_sore_and_tight, test_llm_pain_adds_flag, test_deterministic_pain_never_cleared_by_llm, test_merge_drops_off_taxonomy_classes, test_rpe_caveat_overlay_does_not_touch_raw, test_conservation_five_notes_five_records, test_empty_workout_zero_records, test_compute_deviation_set_delta_added_removed, test_writer_never_touches_raw_partition_and_is_idempotent


**test_training_notes_llm.py** (5 tests): test_parse_signals_defensive, test_parse_signals_garbage_returns_empty, test_cache_hit_skips_model, test_cap_raises_capexceeded, test_cap_breach_degrades_in_extractor


**test_training_trend_regression.py** (2 tests): test_lactate_threshold_regression_runs, test_exercise_efficiency_trend_regression_runs


**test_upstream_contracts.py** (4 tests): test_fixture_shape_contract, test_fixture_roundtrips_transform, test_fixtures_have_no_secrets, test_every_contract_has_a_committed_fixture


**test_v4_proof.py** (0 tests): 


**test_vacation_fund.py** (7 tests): test_genesis_empty_returns_zero_with_warning, test_strava_sum_and_per_sport_breakdown, test_additive_hevy_meters_to_miles, test_additive_macrofactor_yards_to_miles, test_rate_and_manual_adjustment_apply, test_sport_type_filter_restricts_and_skips_extras, test_start_end_override_beats_config_default


**test_vitals_frame.py** (4 tests): test_vitals_frame_and_night_of, test_vitals_trends_are_chronological_regardless_of_query_order, test_vitals_no_op_sort_is_gone, test_vitals_night_of_handles_missing_record


**test_voice_fidelity_545.py** (0 tests): 


**test_weekly_signal_data.py** (4 tests): test_build_weekly_signal_data_basic, test_build_weekly_signal_data_empty, test_board_rotation_deterministic, test_observatory_rotation


**test_weight_trend.py** (7 tests): test_regression_rate_not_total, test_projection_suppressed_while_provisional, test_projection_appears_once_span_is_enough, test_too_few_points_is_zero, test_rate_ci_present_and_ordered, test_goal_date_becomes_a_range, test_provisional_still_reports_rate_ci_but_no_projection


**test_what_changed.py** (11 tests): test_cumulative_delta_surfacing, test_delta_direction_respects_higher_is_better, test_delta_n_guard_omits_sparse_metric, test_flat_metric_omitted, test_newly_unlocked_present_not_prior, test_no_double_announce_outside_window, test_unlock_within_window_announced, test_dropout_then_recross_not_readded, test_non_significant_never_unlocked, test_honest_null_flat_month, test_what_changed_is_experiment_scoped


**test_whoop_reconcile.py** (6 tests): test_induced_workout_gap_is_detected, test_induced_dropped_night_is_detected, test_clean_window_reports_no_gap, test_dedup_twin_workout_is_not_a_false_gap, test_unscored_and_nap_sleeps_do_not_anchor_a_day, test_reconcile_is_read_only


**test_wiring_coverage.py** (4 tests): test_w1_platform_logger_imported, test_w2_ingestion_validator_wired, test_w3_ai_output_validator_wired, test_w4_no_causal_language_in_prompts


### CDK stack files: compute_stack.py, constants.py, core_stack.py, email_stack.py, ingestion_stack.py, lambda_helpers.py, mcp_stack.py, monitoring_stack.py, operational_stack.py, role_policies.py, web_stack.py


---

## 11. SOURCE CODE INVENTORY

### lambdas/ (80 .py files, 1 other files)

**Python files:** adherence_calc.py, ai_calls.py, ai_context.py, ai_output_validator.py, ai_summaries.py, auth_breaker.py, bedrock_client.py, board_loader.py, budget_guard.py, calibration_core.py, canonical_facts.py, character_engine.py, chronicle_share_kit.py, coach_stance.py, coherence_invariants.py, compute_metadata.py, constants.py, digest_utils.py, editorial_image.py, engagement_core.py, er03_gate.py, exercise_history.py, experiment_design.py, gemini_tts.py, generation_cache.py, genome_coaching.py, google_tts.py, grounded_generation.py, hevy_common.py, hevy_compiler.py, hevy_template_cache.py, hevy_write_client.py, html_builder.py, http_retry.py, ingest_health.py, ingestion_framework.py, ingestion_validator.py, insight_writer.py, intelligence_common.py, item_size_guard.py, labs_coaching.py, margaret_editor_pass.py, meal_grouper.py, meal_projection.py, meal_templates_seed.py, measurable_metrics.py, memoir_gate.py, methods_registry.py, numeric.py, output_writers.py, pacific_time.py, persona_core.py, persona_registry.py, personal_baselines.py, phase_filter.py, phase_taxonomy.py, platform_logger.py, privacy_guard.py, quarter_utils.py, rate_limiter.py, relationship_engine.py, request_validator.py, retry_utils.py, routine_generator.py, routine_ir.py, routine_repo.py, routine_title.py, scoring_engine.py, secret_cache.py, sick_day_checker.py, site_writer.py, source_registry.py, source_state.py, stats_core.py, training_load.py, training_notes.py, training_notes_llm.py, vacation_fund.py, voice_fidelity_core.py, weight_trend.py


**Other files (potential cleanup):** og_image_lambda.mjs


**Subdirectories:** __pycache__, cf-auth, coach, compute, dashboard, emails, fonts, ingestion, intelligence, operational, reading, requirements, web


### deploy/ (91 files)

**Files:** MANIFEST.md, OPERATIONAL_RUNBOOK.md, README.md, SMOKE_TEST_TEMPLATE.sh, V2_ROLLBACK.md, apply_s3_lifecycle.sh, archive_onetime_scripts.sh, audit_system_state.sh, backfill_eightsleep_hours.py, backfill_meals.py, backfill_training_notes.py, bucket_policy.json, build_layer.sh, build_mcp_stable_layer.sh, canary_policy.json, capture_baseline.sh, cdk_deploy.sh, check_deploy_drift.py, check_lambda_config_drift.py, cloudwatch_retire_orphans.sh, create_hevy_secret.sh, create_mcp_canary_15min.sh, current_challenge.sample.json, deploy_and_verify.sh, deploy_coach_intelligence.sh, deploy_lambda.sh, deploy_mcp_split.sh, deploy_meal_grouping.sh, deploy_reading_data.sh, deploy_reading_gsis.sh, deploy_reading_mcp.sh, deploy_site.sh, deploy_site_api.sh, deploy_web_stack.sh, download_barlow_condensed.sh, drift_sentinel.py, finish_waf_removal.sh, generate_review_bundle.py, generate_rss.py, hash_site_assets.py, hero_snippet_bs02.html, maintenance_mode.sh, phase_filter_checkpoint.py, pii_surface_guard.py, pipeline_health_check.sh, pitr_restore_drill.sh, point_route53_to_cloudfront.sh, post_cdk_reconcile_smoke.sh, post_cdk_smoke.sh, privacy_filter.json, purge_stale_chronicle_drafts.py, refresh_upstream_fixtures.py, request_amj_cert.sh, restart_character_rebuild.py, restart_chronicle_handler.py, restart_docs_update.py, restart_intelligence_wipe.py, restart_ledger_reset.py, restart_phase_tag.py, restart_pipeline.py, restart_pivot_when_ready.py, restart_rollback.py, restart_site_copy_sync.py, restart_verify.py, restart_verify_rendered.py, rollback_lambda.sh, rollback_site.sh, seed_protocols_to_dynamodb.sh, session_postflight.py, setup_email_subscriber.sh, setup_github_oidc.sh, setup_pipeline_health_check.sh, setup_r18_alarms.sh, setup_remediation_role.sh, setup_subscriber_onboarding.sh, setup_waf.sh, setup_waf_endpoint_rules.sh, setup_whoop_auth.py, smoke_test_cloudfront.sh, smoke_test_site.sh, stage_reserved_concurrency.sh, sync_constants_from_config.py, sync_doc_metadata.py, sync_site_to_s3.sh, test_subscribe.sh, tombstone_legacy_hevy_aggregates.py, v4_cutover.sh, validate_amj_cert.sh, verify_oidc_iam.py, void_legacy_predictions_726.py, warmup_lambdas.sh


### mcp/ (44 modules)

**Modules:** __init__.py, config.py, core.py, handler.py, helpers.py, labs_helpers.py, recovery_authoring.py, registry.py, strength_helpers.py, tools_adaptive.py, tools_benchmark.py, tools_board.py, tools_cgm.py, tools_challenges.py, tools_character.py, tools_coach_intelligence.py, tools_correlation.py, tools_data.py, tools_decisions.py, tools_food_delivery.py, tools_habits.py, tools_health.py, tools_hevy.py, tools_hevy_routine.py, tools_hypotheses.py, tools_journal.py, tools_labs.py, tools_lifestyle.py, tools_meals.py, tools_measurements.py, tools_memory.py, tools_nutrition.py, tools_protocols.py, tools_reading.py, tools_sick_days.py, tools_sleep.py, tools_social.py, tools_strength.py, tools_todoist.py, tools_training.py, tools_training_notes.py, tools_vacation.py, utils.py, warmer.py


---

## 12. KEY SOURCE CODE SAMPLES

### sick_day_checker.py — Sick day cross-cutting utility
```python

"""
Sick Day Checker — shared Lambda Layer utility.

Provides a lightweight DDB check so all Lambdas can test whether a given
date has been flagged as a sick/rest day without duplicating query logic.

DDB schema:
  pk  = USER#<user_id>#SOURCE#sick_days
  sk  = DATE#YYYY-MM-DD
  fields: date, reason (optional), logged_at, schema_version

Used by:
  character_sheet_lambda      — freeze EMA on sick days
  daily_metrics_compute_lambda — store grade="sick", preserve streaks
  anomaly_detector_lambda      — suppress alert emails
  freshness_checker_lambda     — suppress stale-source alerts
  daily_brief_lambda           — show recovery banner, skip coaching

v1.0.0 — 2026-03-09
"""

from datetime import datetime, timezone
from decimal import Decimal

SICK_DAYS_SOURCE = "sick_days"


def _d2f(obj):
    """Convert Decimal → float recursively."""
    if isinstance(obj, list):
        return [_d2f(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def check_sick_day(table, user_id, date_str):
    """Return sick day record dict for *date_str*, or None if not flagged.

    Safe to call from any Lambda — returns None on any error rather than raising.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    try:
        resp = table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        return _d2f(item) if item else None
    except Exception as e:
        print(f"[WARN] sick_day_checker.check_sick_day({date_str}): {e}")
        return None


def get_sick_days_range(table, user_id, start_date, end_date):
    """Return list of sick day record dicts within a date range (inclusive).

    Returns empty list on any error.
    """
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s": f"DATE#{start_date}",
                ":e": f"DATE#{end_date}",
            },
        )
        return [_d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        print(f"[WARN] sick_day_checker.get_sick_days_range({start_date}→{end_date}): {e}")
        return []


def write_sick_day(table, user_id, date_str, reason=None):
    """Write a sick day record. Idempotent — safe to call multiple times for the same date."""
    pk = f"USER#{user_id}#SOURCE#{SICK_DAYS_SOURCE}"
    sk = f"DATE#{date_str}"
    item = {

... [TRUNCATED — 17 lines omitted, 97 total]

```


### platform_logger.py — Structured logging module
```python

"""
platform_logger.py — OBS-1: Structured JSON logging for all Life Platform Lambdas.

Shared module. Drop-in replacement for the stdlib `logging` pattern used across
all 37 Lambdas. Every log line becomes a structured JSON object that CloudWatch
Logs Insights can query, filter, and alarm on.

USAGE (replaces `logger = logging.getLogger(); logger.setLevel(logging.INFO)`):

    from platform_logger import get_logger
    logger = get_logger("daily-brief")           # source name = lambda function name
    logger.info("Sending email", subject=subject, grade=grade)
    logger.warning("Stale data", source="whoop", age_hours=4.2)
    logger.error("AI call failed", attempt=3, error=str(e))

    # Structured log emitted to CloudWatch:
    {
      "timestamp": "2026-03-08T18:00:01.234Z",
      "level": "INFO",
      "source": "daily-brief",
      "correlation_id": "daily-brief#2026-03-08",
      "lambda": "daily-brief",
      "message": "Sending email",
      "subject": "Morning Brief | Sun Mar 8 ...",
      "grade": "B+"
    }

CORRELATION ID:
  Set once per Lambda execution via logger.set_date(date_str).
  Pattern: "{source}#{date}" — enables cross-Lambda log grouping in CWL Insights.
  Example query: `filter correlation_id like "2026-03-08"` shows ALL Lambda executions
  for that date.

MIGRATION PATTERN (for Lambdas not yet migrated):
  Old: `logger.info("Sending email: " + subject)`
  New: `logger.info("Sending email", subject=subject)`
  — keyword args become top-level JSON fields (searchable in CWL Insights)

BACKWARD COMPATIBILITY:
  PlatformLogger inherits logging.Logger so existing `logger.info(msg)` calls
  (positional only) continue to work unchanged. Migration can be incremental.

v1.0.0 — 2026-03-08 (OBS-1)
v1.0.1 — 2026-03-10 — *args %s compat for all log methods (Bug B fix)
v1.0.2 — 2026-05-02 — TD-20: normalize exc_info=True / BaseException to tuple before
                       passing to makeRecord. Previously every error log line emitted
                       a secondary TypeError in formatException because True was passed
                       where a (typ, val, tb) tuple was expected.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_LAMBDA_VERSION = os.environ.get("AWS_LAMBDA_FUNCTION_VERSION", "$LATEST")

# Map stdlib level names → integers (for external callers that pass strings)
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class StructuredFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Standard fields always present:
      timestamp, level, source, lambda, correlation_id, message

    Additional fields: any keyword arguments passed to the log call
    (stored in `record.extra_fields` by PlatformLogger).

... [TRUNCATED — 302 lines omitted, 382 total]

```


### ingestion_validator.py — Ingestion validation layer
```python

"""
ingestion_validator.py — DATA-2: Shared ingestion validation layer.

Validates incoming data items BEFORE writing to DynamoDB.
Invalid records are logged and written to S3 `validation-errors/` prefix
for audit. Critical validation failures skip DDB write entirely.

USAGE:

    from ingestion_validator import validate_item, validate_and_write

    result = validate_item("whoop", item, date_str="2026-03-08")
    if result.should_skip_ddb:
        logger.error("Skipping DDB write", errors=result.errors)
        result.archive_to_s3(s3_client, bucket)
        return
    if result.warnings:
        logger.warning("Validation warnings", warnings=result.warnings)

    table.put_item(Item=item)  # or safe_put_item()

VALIDATION RULES:

    Each source has:
      - required_fields: list of fields that MUST be present (critical if missing)
      - typed_fields: {field: type} — warns if value fails type check
      - range_checks: {field: (min, max)} — warns if value out of expected range
      - critical_range_checks: {field: (min, max)} — SKIPS write if out of range
      - at_least_one_of: list of fields — warns if ALL are absent

    Severity levels:
      CRITICAL — skip DDB write, archive to S3, log error
      WARNING  — write proceeds, issue logged and archived

SOURCES COVERED (20):
  whoop, garmin, apple_health, macrofactor, macrofactor_workouts, strava,
  eightsleep, withings, habitify, notion, todoist, weather, supplements,
  computed_metrics, character_sheet, day_grade, habit_scores,
  computed_insights, google_calendar, adaptive_mode
  (20 total: 13 ingestion + 6 compute + 1 calendar)

v1.0.0 — 2026-03-08 (DATA-2)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal as _Decimal

logger = logging.getLogger(__name__)
REGION = os.environ.get("AWS_REGION", "us-west-2")

# ── Validation result ──────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    source: str
    date_str: str
    errors: list[str] = field(default_factory=list)  # CRITICAL — skip write
    warnings: list[str] = field(default_factory=list)  # non-blocking

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def should_skip_ddb(self) -> bool:
        return len(self.errors) > 0

    def archive_to_s3(self, s3_client, bucket: str, item: dict):
        """Write the rejected item to S3 validation-errors/ prefix for audit."""
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            key = f"validation-errors/{self.source}/{self.date_str}/{ts}.json"
            payload = {
                "source": self.source,
                "date": self.date_str,

... [TRUNCATED — 567 lines omitted, 647 total]

```


### ai_output_validator.py — AI output safety layer
```python

"""
ai_output_validator.py — AI-3: Post-processing validation for AI coaching output.

Validates AI-generated coaching text AFTER generation, BEFORE delivery.
Catches dangerous recommendations, empty/truncated output, and advice that
conflicts with the user's known health context.

USAGE (in ai_calls.py or any Lambda after receiving AI output):

    from ai_output_validator import validate_ai_output, AIOutputType

    result = validate_ai_output(
        text=bod_insight,
        output_type=AIOutputType.BOD_COACHING,
        health_context={"recovery_score": 18, "tsb": -22},
    )

    if result.blocked:
        logger.error("AI output blocked", reason=result.block_reason)
        return result.safe_fallback   # use fallback text instead

    if result.warnings:
        logger.warning("AI output warnings", warnings=result.warnings)

    final_text = result.sanitized_text   # safe to use

VALIDATION TIERS:

    BLOCK  — output is replaced with safe_fallback. Used for:
             - Empty/None output (Lambda crash protection)
             - Dangerous exercise recs with red recovery (injury risk)
             - Severely dangerous caloric guidance (< 800 kcal)
             - Output clearly truncated mid-sentence

    WARN   — output used as-is, warning logged. Used for:
             - Aggressive training language with borderline recovery
             - High-calorie surplus recommendation (unusual for this user)
             - Generic phrases that suggest context was ignored
             - Correlation presented as causation with low-confidence signal

    PASS   — no issues detected

DISCLAIMER:
    All AI output validated by this module should still include the footer:
    "AI-generated analysis, not medical advice." (AI-1 requirement)
    This module validates logical safety, not medical accuracy.

v1.1.0 — 2026-03-13 (TB7-19: hallucinated data reference detection)
  - _METRIC_PATTERNS: 7 metric patterns (recovery, HRV, resting HR, sleep score, weight, TSB)
  - _check_hallucinated_metrics(): cross-refs text numbers against health_context ±25%
  - Check 12 in validate_ai_output(): WARN when claimed metrics deviate >25% from actual
v1.0.0 — 2026-03-08 (AI-3)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Output types ───────────────────────────────────────────────────────────────


class AIOutputType(str, Enum):
    BOD_COACHING = "bod_coaching"  # Board of Directors 2-3 sentence coaching
    TLDR = "tldr"  # TL;DR one-liner
    GUIDANCE = "guidance"  # Smart guidance bullet item
    TRAINING_COACH = "training_coach"  # Training coach section
    NUTRITION_COACH = "nutrition_coach"  # Nutrition coach section
    JOURNAL_COACH = "journal_coach"  # Journal reflection + tactical
    CHRONICLE = "chronicle"  # Weekly chronicle narrative
    WEEKLY_DIGEST = "weekly_digest"  # Weekly digest coaching
    MONTHLY_DIGEST = "monthly_digest"  # Monthly digest coaching
    GENERIC = "generic"  # Unknown — minimal checks only


# ── Validation result ──────────────────────────────────────────────────────────

... [TRUNCATED — 562 lines omitted, 642 total]

```


### digest_utils.py — Shared digest utilities
```python

"""
digest_utils.py — Shared utilities for digest Lambdas (v1.0.0)

Extracted from weekly_digest_lambda.py and monthly_digest_lambda.py to eliminate
duplication, fix bugs, and ensure consistent behaviour across all digest cadences.

Consumers:
  - weekly_digest_lambda.py
  - monthly_digest_lambda.py

Contents:
  - Pure scalar helpers: d2f, avg, fmt, fmt_num, safe_float
  - dedup_activities
  - _normalize_whoop_sleep
  - List-based extractors: ex_whoop_from_list, ex_whoop_sleep_from_list, ex_withings_from_list
  - Banister: compute_banister_from_list, compute_banister_from_dict
"""

from datetime import datetime, timezone
from decimal import Decimal

import training_load  # shared TSS-like load model + Banister core (layer module, #490)

# ══════════════════════════════════════════════════════════════════════════════
# PURE SCALAR HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def d2f(obj):
    """Recursively convert DynamoDB Decimal values to float."""
    if isinstance(obj, list):
        return [d2f(i) for i in obj]
    if isinstance(obj, dict):
        return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def avg(vals):
    """Mean of a list, ignoring None values. Returns None for empty input."""
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def fmt(val, unit="", dec=1):
    """Format a number with optional unit; returns em-dash for None."""
    return "\u2014" if val is None else f"{round(val, dec)}{unit}"


def fmt_num(val):
    """Format a number with thousands separator; returns em-dash for None."""
    if val is None:
        return "\u2014"
    return "{:,}".format(round(val))


def safe_float(rec, field, default=None):
    """Safely extract a float from a dict record."""
    if rec and field in rec:
        try:
            return float(rec[field])
        except Exception:
            return default
    return default


# ══════════════════════════════════════════════════════════════════════════════
# ACTIVITY DEDUP  (Strava/Garmin duplicate removal)
# ══════════════════════════════════════════════════════════════════════════════


def dedup_activities(activities):
    """Remove duplicate activities within a 15-minute window.

    Keeps the richer record (higher richness score). Records without a parseable
    start_date_local are kept unconditionally. Handles Garmin->Strava auto-sync
    duplicates where the same session appears twice with different metadata.
    """
    if not activities or len(activities) <= 1:

... [TRUNCATED — 296 lines omitted, 376 total]

```


### mcp/handler.py (first 60 lines)
```python

"""
Lambda handler and MCP protocol implementation.

Supports two transport modes:
1. Remote MCP (Streamable HTTP via Function URL) — for claude.ai, mobile, desktop
2. Local bridge (direct Lambda invoke via boto3) — legacy Claude Desktop bridge

The remote transport implements MCP Streamable HTTP (spec 2025-06-18):
- POST / — JSON-RPC request/response
- HEAD / — Protocol version discovery
- GET /  — 405 (no SSE support in Lambda)

OAuth: Minimal auto-approve flow to satisfy Claude's connector requirement.
Security is provided by the unguessable 40-char Lambda Function URL, not OAuth.
"""

import base64
import concurrent.futures
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import uuid

from mcp.config import __version__, logger
from mcp.core import decimal_to_float, get_api_key
from mcp.registry import TOOLS
from mcp.utils import mcp_error, validate_date_range, validate_single_date
from mcp.warmer import nightly_cache_warmer

# ── MCP protocol constants ────────────────────────────────────────────────────
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_PROTOCOL_VERSION_LEGACY = "2024-11-05"

# Headers included in all remote MCP responses
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    "Cache-Control": "no-cache",
}


# ── MCP protocol handlers ─────────────────────────────────────────────────────
def handle_initialize(params):
    # Negotiate protocol version — support both current and legacy
    client_version = params.get("protocolVersion", MCP_PROTOCOL_VERSION_LEGACY)
    server_version = MCP_PROTOCOL_VERSION if client_version >= "2025" else MCP_PROTOCOL_VERSION_LEGACY

    return {
        "protocolVersion": server_version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "life-platform", "version": __version__},
    }


def handle_tools_list(_params):
    return {"tools": [t["schema"] for t in TOOLS.values()]}


... [TRUNCATED — 577 lines omitted, 637 total]

```


---

## 13. PREVIOUS REVIEW GRADES


| Dimension | #1 (v2.91) | #2 (v3.1.3) | #3 (v3.3.10) | #4 (v3.4.1) | #13 (v3.7.29) |
|-----------|-----------|-----------|-------------|-------------|---------------|
| Architecture | B+ | B+ | A- | A | A |
| Security | C+ | B+ | B+ | A- | A- |
| Reliability | B- | B+ | B+ | B+ | A- |
| Operability | C+ | B- | B+ | B+ | B+ |
| Cost | A | A | A | A | A+ |
| Data Quality | B | B+ | B+ | A- | A |
| AI/Analytics | C+ | B- | B | B | B+ |
| Maintainability | C | B- | B | B+ | B+ |
| Production Readiness | D+ | C | B- | B | B+ |


**Last review source file: `REVIEW_PROMPT_R22_CONSULTANCY.md`**


### Last Review Findings (read this before flagging ANY new finding)

# R22 — The Consultancy Review (prompt + execution plan)

> **Status:** DRAFT — awaiting Matthew's green-light before execution.
> **What this is:** Part 1 is the *prompt* (the charter handed to the engagement). Part 2 is
> the *plan against that prompt* (how a Fable session executes it without burning the token
> budget before completion).
>
> **ER-05 caveat (mandatory, reproduce in every output):** every grade and persona verdict
> produced by this process is internal self-assessment by AI personas against a rubric the
> platform authored. It measures conformance to our own stated values — not external
> validation. The only trustworthy external arbiter remains one real senior engineer reading
> the review bundle cold (`deploy/generate_review_bundle.py`).

---

# PART 1 — THE PROMPT (the engagement charter)

You are **the Consultancy**: an engagement team of world-class technology leaders hired to do
a cold, comprehensive, adversarial deep-dive of the Life Platform (AWS ingest→store→serve
pipeline, ~93 Lambdas, 8 CDK stacks) and averagejoematt.com (the v4 "Measured Life" site),
including how the operator uses Claude itself to build and run it. You were hired because the
system has only ever been graded by the people who built it. Your job is to find what they
can no longer see.

## The bench

The engagement extends the standing 12-seat Technical Board (`docs/REVIEW_METHODOLOGY.md`)
with four engagement-specific seats:

| Seat | Standing question |
|---|---|
| **CIO** | "Is the operational risk posture, spend, vendor surface, and continuity story defensible? What happens if Matthew is hit by a bus — or just gets bored?" |
| **CTO** (chairs, with Priya/Marcus/Raj from the Board) | "Is the system shape right for the next 12 months, and where is complexity masquerading as capability?" |
| **CPO** (absorbs Sarah Chen's Product seat) | "Does every surface serve the causal loop and the 4 audiences (`docs/PLATFORM_NORTH_STAR.md`)? What would a reader pay attention with — and where do we lose them?" |
| **Head of AI Engineering** | "Is the *way Claude is used to build and run this* — CLAUDE.md, commands, skills, memory, missing `.claude/agents/`, hooks, the remediation agent, model tiering — itself well-engineered? Where does Fable-tier capability change what's possible?" |
| **Reader Panel** (4 voices, from the north star) | Reddit newcomer · Matthew-daily-return · friends/family · QS skeptic. Each browses the LIVE site and the AI-produced content (chronicle, coach commentary, briefs, podcasts) and reports where trust, interest, or returnability breaks. |

The **Red Team** (Yael Cohen chairing, plus a dedicated adversary) runs as a separate pass
with attacker mindset, not reviewer mindset.

## Scope — the ten dimensions

1. **Bugs & correctness** — live defects, silent failures, wrong numbers on public surfaces (ADR-104/105 are the honesty bar; any surface that could show a fabricated or stale number is a finding).
2. **Architecture** — coupling, failure domains, the single-table/no-GSI bet, the shared-layer version-drift treadmill (v115/116/118 drift is a *symptom* — diagnose the disease), stack boundaries, ADR-103 complexity posture vs. reality.
3. **Security (red team)** — IAM (one-role-per-Lambda claims vs. actual policies), site-api write paths (votes/follows/checkins/suggestions/findings), rate-limiter fail-open, Secrets Manager surface, CloudFront/S3 policy gaps, CI OIDC trust policy, the remediation agent's blast radius, MCP auth, prompt-injection paths into any Lambda that feeds LLM output to a public surface.
4. **Tech debt** — the honest register: what's rotting, what's held (Operational stack holds, `personal_baselines` not in build_layer.sh), what ADR-103 calls load-bearing vs. what usage data says (≈31 of ~143 MCP tools used in 30d).
5. **Modernization** — where 2023-era choices should be revisited *with evidence*: Python 3.12→3.13, CDK patterns, the no-deps rule's real cost, test architecture, observability (would OTel/X-Ray earn its keep at this scale?), batch inference (#409). Recommendation ≠ adoption; each needs a cost/benefit.
6. **Build/deploy/CI process** — the deploy gotcha register in `docs/CONVENTIONS.md` is long and growing; which gotchas should be *engineered away* rather than remembered? Squash-drift, doc-sync literal drift, asset-staging, layer sequence — each recurring gotcha is a missing automation.
7. **How we use Claude** — CLAUDE.md size/effectiveness, command quality, the empty `.claude/agents/`, no hooks, memory hygiene, skill gaps, permission-prompt friction, whether the session-handover pattern scales, remediation-agent model choice, ADR-049 tiering vs. today's model lineup.
8. **Content & reader experience** — the AI-produced content itself (chronicle, coach voices, briefs, podcast) reviewed as *editorial product*: voice, repetition, honesty-as-moat, returnability. The Reader Panel owns this.
9. **Fable-ecosystem opportunities** — specifically: what does Fable-tier capability unlock that the current setup doesn't exploit? Standing workflows, custom subagents, better /uplevel, self-improving eval loops, the golden-brief judge, cheaper-model delegation patterns. This dimension produces *proposals*, each with a token/cost estimate.
10. **Cost & FinOps** — the $75 ceiling's headroom, tier-band behavior in practice, CloudWatch/alarm spend (110 alarms), what growth (readers, sources) does to the curve.

## Rules of evidence (non-negotiable — from R1–R21 scar tissue)

1. **Read the resolved-findings inventory first** (review bundle §13b + `docs/DECISIONS.md` ADR-057/128–130). Re-issuing a resolved finding is a defect in *your* work.
2. **No finding from documentation alone.** Cite the file, the live URL, the AWS state, or the CI run that proves it. Historical false-positive rate for unverified findings is ~50%; every finding passes adversarial verification before it may be ranked (Part 2, Phase 3).
3. **Classify every finding:** NEW · REGRESSION (cite what broke it) · PERSISTING (carry the original ID) · CONFIRMED-RESOLVED (acknowledge, move on).
4. **Kill on sight:** causal claims from correlational data, findings that require exposing age/genome/vices, decorative-gloss suggestions, "add a GSI/framework/dependency" without an ADR-grade justification.
5. **Respect the holds:** the Operational-stack deploy hold, SHIPS-DISABLED features awaiting Matthew's decisions, and anything `parked-register` are *decisions*, not findings — unless you have new evidence the decision's premise changed.
6. **Every finding must state its outcome** — the sentence "if fixed, then X measurably improves for Y" — or it doesn't get filed.

## Output contract

Every surviving finding becomes a GitHub issue:

- **Title:** `[R22-<dim>-<n>] <one-line defect/opportunity>`
- **Body:** evidence (file:line / URL / AWS state) · failure scenario or opportunity · outcome-if-fixed · verification note (who confirmed, how) · effort S/M/L.
- **Labels:** `type:story`, one `area:*`, one `model:*` (assignment rubric in Part 2 §6), severity via title prefix in body (`Critical/High/Medium/Low` per REVIEW_METHODOLOGY).
- **Milestone:** Critical/High → **Now**; Medium → **Next**; Low/proposals → **Later**.
- **Epics:** one `type:epic` per dimension *that has ≥3 findings*, linking its stories.
- Plus one **closure record**: `docs/reviews/REVIEW_2026-07-XX_R22.md` (findings table, grades vs. R21, premise-corrections, ER-05 caveat) and an ADR if the review changes posture.

---

# PART 2 — THE PLAN (how a Fable session executes this)

**Posture:** read-only engagement. No deploys, no merges to feature code, no content
publishing. The only writes: GitHub issues/epics, the closure record, memory/handover.
Repo writes happen on a branch from a worktree (concurrent-session rule). Matthew
green-lights issue filing at the Phase 4 checkpoint before anything is created.

**Token discipline:** the whole engagement targets a bounded spend with two hard
checkpoints where the driver reports spend and can stop with partial-but-complete output.
Discovery agents are capped (max 10 findings each, evidence pointers not file dumps); the
review bundle is the shared context so agents don't re-read the repo; Sonnet does the
mechanical sweeps, Fable does judgment, red team, and synthesis.

## Phase 0 — Orient & bundle (driver, inline, ~1 agent-equivalent)

1. `git pull`; update §13b in `deploy/generate_review_bundle.py` if stale; run it → the R22 bundle.
2. Ground truth: `curl /version.json` vs HEAD · `gh issue list` (all 61 open, full JSON — this is the dedup corpus) · `gh pr list` · last 2 CI runs · `handovers/HANDOVER_LATEST.md` · Active Work memory.
3. Snapshot AWS reality where docs drift: layer versions across the fleet, alarm count, budget-tier value, remediation-mode.
4. Write the 5-line state summary. **Everything downstream cites the bundle + this snapshot, not re-derived state.**

## Phase 1 — Discovery fan-out (Workflow tool; ~14 agents, `pipeline()` into Phase 2)

| Lens | Agent persona | Model / effort | Primary inputs |
|---|---|---|---|
| Bugs/correctness sweep | Elena + Jin | sonnet / medium | bundle, lambdas/, web/, live API spot-checks |
| Architecture | CTO chair (Priya/Marcus/Raj) | fable / high | bundle, cdk/, ADR-103 ledger |
| Security recon (pre-red-team map) | Yael | sonnet / high | role_policies, web/*.py write paths, rate_limiter, ci-cd.yml |
| Tech debt register | Viktor | sonnet / medium | CONVENTIONS gotchas, holds, TODO/FIXME sweep, layer drift history |
| Modernization | Marcus | sonnet / medium | pinned versions, test arch, deps posture |
| Build/CI process | Jin | sonnet / medium | ci-cd.yml, deploy/, gotcha register → automation candidates |
| Claude-usage audit | Head of AI Eng | **fable / high** | CLAUDE.md, .claude/commands+skills, memory/, remediation workflow, ADR-049 |
| Fable-opportunities | Head of AI Eng | **fable / high** | same + Workflow/agent capabilities; produces costed proposals |
| Content editorial | CPO | opus / medium | live chronicle/coaches/briefs/podcast transcripts |
| Reader: Reddit newcomer | panel | haiku→sonnet / low | live site, cold |
| Reader: daily-return Matthew | panel | sonnet / low | live site, 7-day lens |
| Reader: friends/family | panel | haiku→sonnet / low | live site, cold |
| Reader: QS skeptic | panel | sonnet / medium | live site + evidence pages, rigor lens |
| Cost/FinOps | Dana | sonnet / medium | Cost Explorer snapshot, alarm/log config, budget-guard code |

Caps: ≤10 findings/lens, each `{summary, evidence_pointer, dimension, sev_guess, outcome}`
via structured schema. Reader panel browses via Playwright/WebFetch against the LIVE site.

## Phase 2 — Dedup barrier (driver, inline, cheap)

Flatten → dedup by (file/URL, defect) → **dedup against the 61 open issues + §13b resolved
inventory** (this is where re-flagging dies) → classify NEW/REGRESSION/PERSISTING. Expect
~140 raw → ~60–80 unique. *This is plain code + driver judgment, not agents.*

## Phase 3 — Adversarial verification (Workflow; the 50%-FP firewall)

Each unique finding → one verifier agent prompted to **refute** it against actual
code/live/AWS state (sonnet/medium for mechanical, fable for the 10 highest-severity).
Verdict: CONFIRMED (with strengthened evidence) or KILLED (with the wrong premise noted —
premise corrections go in the closure record). Severity ≥ High requires CONFIRMED by
evidence a cold reader could check.

**Red-team pass runs here as its own arm** (fable / xhigh, 3–4 agents): takes Yael's Phase-1
recon map and *attacks* — auth bypass on write endpoints, rate-limiter fail-open abuse, IAM
privilege escalation via the remediation role, prompt injection through user-submitted
content (board questions, findings, suggestions) into any LLM → public-surface path, CI
OIDC scope, S3/CloudFront policy gaps. Attacks are **described and evidenced, never
executed against prod** beyond read-only inspection and normal HTTP GETs.

**→ CHECKPOINT A:** driver reports confirmed-finding count, kill rate, spend so far.

## Phase 4 — Synthesis & outcome ranking (driver on Fable, inline)

Rank every confirmed finding: **Outcome value** (which north-star audience/loop station,
how hard) × **Risk retired** (security/data-loss/honesty) ÷ **Effort** (S/M/L), tempered by
ADR-103 posture (don't polish a retire-candidate). Produce the ranked board: Critical/High
→ Now, Medium → Next, Low + Fable-proposals → Later. Draft the epic structure and the
closure record.

**→ CHECKPOINT B (Matthew):** present the board — counts by severity/dimension, top 10 in
full, the epic list, and the proposed issue batch. **Filing ~60 issues is the one
irreversible-ish, outward-facing act; it waits for explicit go** (in-session authorization
per the standing convention).

## Phase 5 — File & close (driver + 2–3 sonnet agents for bulk `gh issue create`)

1. Epics first, then stories with `Part of #<epic>`; labels + milestones per the contract.
2. Write `docs/reviews/REVIEW_2026-07-XX_R22.md` (+ ADR if posture changed); update §13b
   with every R22 finding so R23 can't re-flag; PR the doc changes from the worktree branch.
3. Memory + handover; one-paragraph plan-of-attack ordering (which issues, which session
   type, which model) appended to the closure record.

## 6 — Model-assignment rubric (the `model:*` label on each filed issue)

- **model:sonnet** — mechanical, well-specified, verifiable by tests: single-file fixes, doc drift, gotcha-automation scripts, config/alarm changes.
- **model:opus** — multi-file features, front-end slices with render-QA, refactors with judgment but bounded blast radius.
- **model:fable** — architecture changes, security remediations, anything touching the honesty/rigor bar (ADR-104/105), agentic-tooling redesign, the Fable-proposals themselves, anything needing adversarial self-verification.

## 7 — Budget & contingency

Rough envelope: Phase 0 ~3% · Phase 1 ~40% · Phase 3 ~30% · Phase 4 ~7% · Phase 5 ~10% ·
reserve ~10%. If Checkpoint A shows >60% spent: skip fable-verification upgrades, verify
top-half by severity only, mark the rest `needs-review` label instead of dropping them.
If the session dies mid-flight: Workflow resume (`resumeFromRunId`) recovers Phase 1/3
agent results from the journal; Phases 4–5 can run as a separate cheap session from the
Checkpoint-A artifact. Natural two-session split if preferred: **Session 1 = Phases 0–3**
(discovery+verification, artifact = confirmed-findings file), **Session 2 = Phases 4–5**
(rank+file, cheap, mostly driver).


---

## 13b. RESOLVED FINDINGS INVENTORY


> **REVIEWER INSTRUCTION:** Before issuing ANY finding in this review, check this table.
> If the finding appears here as RESOLVED, do NOT re-issue it. Instead, verify the
> resolution is adequate and note it as confirmed-resolved in your output.
> Re-issuing resolved findings wastes review budget and creates noise.

### R13 Findings — All Resolved (as of 2026-03-15, v3.7.40)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R13-F01 | No CI/CD pipeline | ✅ RESOLVED | Already existed | `.github/workflows/ci-cd.yml` — 7 jobs: lint, test (9 linters), plan (cdk synth+diff), manual approval gate, deploy, smoke test, auto-rollback. OIDC auth. |
| R13-F02 | No integration tests for critical path | ✅ RESOLVED | v3.7.38 | `tests/test_integration_aws.py` I1–I13: Lambda handlers, layer versions, DDB health, secrets, EventBridge, S3, DLQ, alarms, MCP invocability, data-reconciliation, MCP tool response shape, freshness data. |
| R13-F03 | MCP monolith split assessment | N/A | — | Deferred: <100 calls/day. |
| R13-F04 | CI secret reference linter | ✅ RESOLVED | v3.7.35 | `tests/test_secret_references.py` SR1–SR4. Wired into `ci-cd.yml` test job. |
| R13-F05 | OAuth fail-open default | ✅ RESOLVED | v3.7.35 | `mcp/handler.py` `_get_bearer_token()` returns sentinel `"__NO_KEY_CONFIGURED__"`, `_validate_bearer()` fail-closed. |
| R13-F06 | Correlation n-gating missing | ✅ RESOLVED | v3.7.36 | `mcp/tools_training.py` `tool_get_cross_source_correlation`: n≥14 hard min, label downgrade, p-value, 95% CI via Fisher z. |
| R13-F07 | No PITR restore drill | ⏳ PENDING | — | First drill scheduled ~Apr 2026. Runbook written at v3.7.17. |
| R13-F08 | Layer version CI test | ✅ RESOLVED | v3.7.38 | `tests/test_layer_version_consistency.py` LV1–LV5. `cdk/stacks/constants.py` is single source of truth for layer version (LV1 caught real duplication bug). |
| R13-F08-dur | No duration alarms | ✅ RESOLVED | v3.7.36 | `deploy/create_duration_alarms.sh`: `life-platform-daily-brief-duration-p95` (>240s) + `life-platform-mcp-duration-p95` (>25s). |
| R13-F09 | No medical disclaimers in MCP health tools | ✅ RESOLVED | v3.7.35–36 | `_disclaimer` field in `tool_get_health()`, `tool_get_cgm()`, `tool_get_readiness_score()`, `tool_get_blood_pressure_dashboard()`, `tool_get_blood_pressure_correlation()`, `tool_get_hr_recovery_trend()`. |
| R13-F10 | `d2f()` duplicated across Lambdas | ✅ RESOLVED (annotated) | v3.7.37 | `weekly_correlation_compute_lambda.py` annotated; canonical copy in `digest_utils.py` (shared layer). Full dedup deferred to layer v12. |
| R13-F11 | DST timing in EventBridge | Documented, not mitigated | — | Low-impact; documented in ARCHITECTURE.md. |
| R13-F12 | No rate limiting on MCP write tools | ✅ RESOLVED | v3.7.35 | `mcp/handler.py` `_check_write_rate_limit()`: 10 calls/invocation on `create_todoist_task`, `delete_todoist_task`, `log_supplement`, `write_platform_memory`, `delete_platform_memory`. |
| R13-F14 | No MCP endpoint canary | ✅ RESOLVED | v3.7.40 | EventBridge rule `rate(15 minutes)` → canary. Alarms: `life-platform-mcp-canary-failure-15min`, `life-platform-mcp-canary-latency-15min`. |
| R13-F15 | Weekly correlation lacks FDR correction | ✅ RESOLVED | v3.7.37 | `weekly_correlation_compute_lambda.py` Benjamini-Hochberg FDR correction, `pearson_p_value()`, per-pair `p_value`/`p_value_fdr`/`fdr_significant`. |
| R13-XR | No X-Ray tracing on MCP | ✅ RESOLVED | v3.7.40 | `cdk/stacks/mcp_stack.py` `tracing=_lambda.Tracing.ACTIVE`. IAM: `xray:PutTraceSegments` etc. in `mcp_server()` policy. |


### R17 Findings (2026-03-20, v3.7.82)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R17-F01 | Public AI endpoints lack persistent rate limiting | ✅ RESOLVED | v4.3.0 | WAF WebACL deployed with SubscribeRateLimit (60/5min) and GlobalRateLimit (1000/5min) |
| R17-F02 | In-memory rate limiting resets on cold start | ✅ RESOLVED | v4.3.0 | WAF at CloudFront edge provides persistent rate limiting independent of Lambda lifecycle |
| R17-F03 | No WAF on public-facing CloudFront | ✅ RESOLVED | v4.3.0 | WAF WebACL attached to E3S424OXQZ8NBE |
| R17-F04 | Subscriber email verification has no rate limit | ✅ RESOLVED | v4.3.0 | WAF SubscribeRateLimit rule covers /api/subscribe* at 60/5min per IP |
| R17-F05 | Cross-region DynamoDB reads (site-api) | ✅ RESOLVED | v4.3.0 | Site-api confirmed in us-west-2 (AWS CLI verification 2026-03-30) |
| R17-F06 | No observability on public API endpoints | ⏳ PARTIAL | — | AskEndpointErrors alarm added. Structured route logging deployed v4.5.1. |
| R17-F07 | CORS headers not evidenced | ✅ RESOLVED | v4.3.1 | CORS_HEADERS dict + OPTIONS handler confirmed in site_api_lambda.py |
| R17-F08 | google_calendar in config.py SOURCES | ✅ RESOLVED | v4.3.1 | Retired file only, not in active SOURCES list |
| R17-F09 | MCP Lambda memory discrepancy in docs | ✅ RESOLVED | v4.3.1 | Doc headers reconciled to 118 tools (v4.5.0) |
| R17-F10 | Site API hardcoded model strings | ✅ RESOLVED | v4.3.1 | Using os.environ.get() pattern |
| R17-F11 | No privacy policy on public website | ✅ RESOLVED | v4.3.0 | /privacy/ directory exists |
| R17-F12 | PITR restore drill not executed | ✅ RESOLVED | v4.5.1 | Drill executed 2026-03-30 (Phase 3 of remediation plan) |
| R17-F13 | 95 MCP tools — context window pressure | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts 118 as operating state |

### R18 Findings (2026-03-28, v4.3.0)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R18-F01 | Severe documentation drift | ✅ RESOLVED | v4.5.1 | ARCHITECTURE.md body reconciled, INFRASTRUCTURE.md full update, INCIDENT_LOG updated |
| R18-F02 | CLI-created Lambdas outside CDK | ✅ RESOLVED | v4.5.1 | CDK adoption audit completed. Unmanaged Lambdas documented and adoption planned. |
| R18-F03 | lambda_map.json stale | ✅ RESOLVED | v4.3.1 | Updated with all new Lambdas. CI orphan-file lint added. |
| R18-F04 | New resources without monitoring | ✅ RESOLVED | v4.3.1 | Alarms added for og-image, food-delivery, challenge, email-subscriber. Pipeline health check covers rest. |
| R18-F05 | 47-page manual S3 deploy | ✅ RESOLVED | v4.3.1 | deploy/deploy_site.sh created |
| R18-F06 | WAF rules too broad | ✅ RESOLVED | v4.3.1 | Endpoint-specific rules: /api/ask (100/5min), /api/board_ask (100/5min) |
| R18-F07 | SIMP-1 regression (95→110) | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts 118 as operating state |
| R18-F08 | INTELLIGENCE_LAYER.md stale | ✅ RESOLVED | v4.5.2 | Full refresh — freeze label removed, all IC statuses updated |
| R18-F09 | Cross-region split on 13+ routes | ✅ RESOLVED | v4.3.0 | Site-api confirmed us-west-2 (AWS CLI 2026-03-30). No cross-region reads. |


### R19 Findings (2026-03-30, v4.5.0)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R19-F01 | INFRASTRUCTURE.md entirely stale (v4.2.1 state) | ✅ RESOLVED | v4.5.2 + v4.9.0 | Full update in v4.5.2 doc sprint. Second pass v4.9.0: Lambda categories reconciled (16+11+12+21+2=62), MCP 115, alarms ~66, missing Lambdas added. |
| R19-F02 | ARCHITECTURE.md internal contradictions (5+ conflicts) | ✅ RESOLVED | v4.5.2 + v4.9.0 | Body-section counts reconciled in v4.5.2. Second pass v4.9.0: local project structure updated (Lambda categories, us-west-2 site-api, shared modules, 35-module MCP). |
| R19-F03 | INCIDENT_LOG missing 5 v4.4.0 pipeline failures | ✅ RESOLVED | v4.5.2 | All 5 incidents added with P-levels, TTD, TTR. Patterns section updated with silent secret deletion class. |
| R19-F04 | SLOs reference stale data sources | ✅ RESOLVED | v4.9.0 | Google Calendar removed. Monitored sources expanded from 10 to 13 (added Weather, Food Delivery, Measurements). |
| R19-F05 | 118 MCP tools (4th consecutive review) | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts tool count as operating state. Current count: 115 (reduced from 118). |
| R19-F06 | Site-API region contradicts Function URL | ✅ RESOLVED | v4.3.0 | AWS CLI verification confirmed us-west-2. Docs updated. |
| R19-F07 | Section 13b not updated for R17/R18 | ✅ RESOLVED | v4.5.2 + v4.9.0 | R17, R18, R19 findings all added to generate_review_bundle.py Section 13b. |


---

## 14. SCHEMA SUMMARY

## Key Structure

| Attribute | Description |
|-----------|-------------|
| `pk` | Partition key — identifies the entity type and owner |
| `sk` | Sort key — enables range queries and versioning |



## Sources

Valid source identifiers: `whoop`, `withings`, `strava`, `todoist`, `apple_health`, `hevy`, `eightsleep`, `chronicling`, `macrofactor`, `macrofactor_workouts`, `macrofactor_export`, `garmin`, `habitify`, `notion`, `labs`, `dexa`, `genome`, `supplements`, `weather`, `travel`, `state_of_mind`, `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, `hypotheses`, `chronicle`, `measurements`, `food_delivery`, `weight_episodes`, `training_reference`, `macrofactor_meals`

Note: `chronicling` is a historical/archived source — not actively ingesting. `hevy` became the **primary** strength-training source on 2026-05-25 (see ADR-060) — actively ingesting via hourly `hevy-backfill` poll of the Hevy events API; older Hevy records exist as legacy daily aggregates that the MCP `_expand_legacy_aggregate` bridge surfaces as virtual per-workout views. `macrofactor_export` is the explicit source label for workouts arriving via the manual MacroFactor Dropbox CSV export path (Tier 2 — see ADR-061). `habit_scores`, `character_sheet`, `computed_metrics`, `platform_memory`, `insights`, `decisions`, `hypotheses`, `weight_episodes`, `training_reference`, and `macrofactor_meals` are derived/computed partitions, not raw ingested data (the last is a recomputable projection over the raw `macrofactor` food log — see below).

Ingestion methods: API polling (scheduled Lambda), S3 file triggers (manual export), **webhook** (Health Auto Export push — also handles BP and State of Mind), **MCP tool write** (supplements), **on-demand fetch + scheduled Lambda** (weather)

---


---

## 15. DOCUMENTATION INVENTORY

**Root docs (68 files):** A11Y_BASELINE.md, API.md, ARCHITECTURE.md, BACKLOG.md, BACKLOG_CC_SERIES_2026-06-13.md, BOARDS.md, CHANGELOG.md, CLAUDE_CODE_PROMPT_V4_PASTE_READY.md, CLAUDE_DESIGN_BRIEF_V4_2026_06_01.md, CONVENTIONS.md, COST_FORECAST_2026-06.md, COST_TRACKER.md, DATA_GOVERNANCE.md, DECISIONS.md, DEPENDENCY_GRAPH.md, DEPLOYMENT.md, DESIGN_SYSTEM_V4_THE_MEASURED_LIFE.md, DESIGN_SYSTEM_V5.md, DISASTER_RECOVERY.md, INCIDENT_LOG.md, INFRASTRUCTURE.md, LAUNCH_DAY_CHECKLIST.md, MANAGED_WHERE_LEDGER.md, MCP_TOOL_CATALOG.md, MIGRATION_MAP_V4_2026_06_01.md, MONITORING.md, ONBOARDING.md, OPERATOR_GUIDE.md, PHASE_TAXONOMY.md, PLATFORM_NORTH_STAR.md, QUICKSTART.md, README.md, REMEDIATION_TAXONOMY.md, REPO_STRUCTURE.md, RESERVED_CONCURRENCY.md, REVIEW_METHODOLOGY.md, RUNBOOK.md, RUNBOOK_REENTRY.md, SCHEMA.md, SECRETS_MAP.md, SECRETS_ROTATION.md, SECURITY.md, SITE_MAP_AND_INTENT.md, SITE_REVIEW_METHODOLOGY.md, SITE_UPLEVEL_PLAYBOOK.md, SLOs.md, SPEC_COACHES_AS_CHARACTERS_2026-06-13.md, SPEC_DOORS_EXPERIENCE_REDESIGN_2026-06-21.md, SPEC_HABITS_PAGE_REDESIGN_2026-06-21.md, SPEC_HEVY_NOTES_FEEDBACK_LOOP_2026-06-21.md, SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31.md, SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31_PREREQS.md, SPEC_MEAL_GROUPING_2026-06-19.md, SPEC_MIND_PAGE_REDESIGN_2026-06-21.md, SPEC_NUTRITION_PAGE_REDESIGN_2026-06-21.md, SPEC_PHYSICAL_PAGE_REDESIGN_2026-06-21.md, SPEC_READING_MIND_2026-06-29.md, SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md, SPEC_SLEEP_PAGE_REDESIGN_2026-06-21.md, SPEC_TRAINING_PAGE_REDESIGN_2026-06-21.md, SPEC_VITALS_PAGE_REDESIGN_2026-06-21.md, TAG_CODES.md, TESTING.md, V2_AUDIT_PLAN.md, V2_AUDIT_PROMPT.md, V4_DESIGN_CONSTITUTION_2026_06_01.md, files.zip, v4_art_direction_05_the_measured_life.html


**docs/archive/ (71 files):** AUDIT_PROD2_MULTI_USER.md, AVATAR_DESIGN_STRATEGY.md, A_GRADE_PHASE6_SUPPLEMENT.md, A_GRADE_REMEDIATION_PLAN.md, BOARD_DERIVED_METRICS_PLAN.md, CHANGELOG_ARCHIVE.md, CHANGELOG_v341.md, CLAUDE_CODE_BRIEF_2026-03-28.md, CLAUDE_CODE_DPR1_PROMPT.md, CLAUDE_CODE_REMEDIATION_PROMPT.md, CLAUDE_CODE_SPEC_OBSERVATORY_V2_REMAINING.md, DATA_DICTIONARY_archived_v3.7.32.md, DATA_FLOW_DIAGRAM.md, DERIVED_METRICS_PLAN.md, DESIGN_PROD1_CDK.md, DESIGN_SIMP2_INGESTION.md, DPR1_IMPLEMENTATION_BRIEF.md, DPR1_PHASE2_IMPLEMENTATION_BRIEF.md, FEATURES_archived_v3.7.32.md, FIELD_NOTES_SPEC.md, FIELD_NOTES_SPEC_ROOT.md, FOOD_DELIVERY_SPEC.md, FUNCTION_HEALTH_V2_HANDOFF_2026-05-02_tonight.md, HOME_EVOLUTION_SPEC.md, IMPL_SUBSCRIBER_EMAIL_REDESIGN.md, LAUNCH_DAY.md, LAUNCH_READINESS_IMPL_SPEC.md, LEDGER_SPEC_FINAL.md, MCP_TOOL_TIERING_DESIGN.md, MEASUREMENTS_IMPLEMENTATION_SPEC.md, NOTION_ENRICHMENT_SPEC.md, NOTION_JOURNAL_SPEC.md, OBSERVATORY_UPGRADE_SPEC.md, OBSERVATORY_V2_SPEC.md, OFFSITE_BUILD_PLAN.md, OFFSITE_BUILD_PLAN_2026-03-27.md, OFFSITE_BUILD_PLAN_PART3.md, OFFSITE_BUILD_PLAN_PART4.md, OFFSITE_FEATURE_LIST.md, OFFSITE_FEATURE_LIST_PART3.md, OFFSITE_FEATURE_LIST_PART4.md, OFFSITE_PART3_PROMPT.md, OFFSITE_PART4_PROMPT.md, OFFSITE_PRIORITY_SPEC.md, PULSE_REDESIGN_SPEC.md, R18_REMEDIATION_PROMPT.md, SCHEMA_LABS_ADDITION.md, SCOPING_LARGE_OPUS.md, SIMP1_PLAN.md, SPEC_CHARACTER_SHEET.md, SPRINT_PLAN.md, STATUS_PAGE_SPEC.md, STORY_ABOUT_REVIEW_SPEC.md, TD_BATCH_HAE_FIXES_2026-05-02.md, TD_QUICK_DECISIONS_2026-05-02.md, USABILITY_BRIEF_PROMPT.md, USER_GUIDE_archived_v3.7.32.md, V2_PAGE_DESIGN_BRIEFS.md, VISUAL_ASSET_BRIEF.md, VISUAL_DECISIONS.md, WEBSITE_REDESIGN_SPEC.md, WEBSITE_ROADMAP.md, WEBSITE_STRATEGY.md, avatar-design-strategy.md, data-source-audit-2026-02-24.md, joint-board-email-review-2026-03-29.md, reader-engagement-implementation-plan.md, sec3_input_validation_assessment.md, usability_implementation_brief.md, usability_study.md, wednesday-chronicle-design.md


**docs/audits/ (10 files):** AUDIT_2026-03-21_website.md, AUDIT_2026-03-30_alarm_coverage.md, AUDIT_2026-03-30_cdk_adoption.md, AUDIT_2026-03-30_pitr_drill.md, AUDIT_2026-03-30_security.md, COST_CACHE_SES_VERIFICATION_2026-05-29.md, IAM_AUDIT_2026-03-08.md, TD-11_HABITIFY_API_AUDIT.md, TD-19_DATE_PARTITION_AUDIT.md, VERIFY_SWEEP_2026-05-29.md


**docs/briefs/ (3 files):** BRIEF_2026-03-26_arena_lab_v2.md, BRIEF_2026-03-26_design_brief.md, BRIEF_2026-06-29_reading_mind.md


**docs/coaching/ (8 files):** COACH_SESSION.md, PROVEN_BLUEPRINT.md, READING_CALIBRATION.md, TRAINING_CALIBRATION.md, TRAINING_PROGRAM.md, WORKORDER_BENCH1_benchmarking.md, WORKORDER_DI1_movement_integrity.md, WORKORDER_HEVY_COMMIT_HARDENING.md


**docs/content/ (4 files):** BUILD_DISPATCH_CHECKLIST.md, ELENA_PREQUEL_BRIEF.md, ESSAY_ORG_CHART_OF_ONE.md, STORY_DRAFTS_v1.md


**docs/design/ (2 files):** MULTI_USER_ISOLATION.md, PORTRAIT_RUNBOOK.md


**docs/design-review/ (9 files):** README.md, body-composition.md, fitness.md, habits.md, mind-accountability.md, nutrition.md, sleep.md, the-doors.md, vitals.md


**docs/rca/ (3 files):** PIR-2026-02-28-ingestion-outage.md, RCA_2026-02-24_apple_health_pipeline.md, RCA_2026-06-13_ingestion_triage.md


**docs/restart/ (19 files):** RESTART_DISCOVERY_2026_05_18.md, _character_rebuild_report.txt, _chronicle_files.txt, _chronicle_report.txt, _docs_update_report.txt, _grep_307.txt, _grep_anchors.txt, _grep_dayn.txt, _grep_site_copy.txt, _grep_streaks.txt, _intelligence_wipe_report.txt, _phase_tag_report.txt, _pipeline_report.txt, _pivot_watchdog.log, _pivot_watchdog.stderr.log, _pivot_watchdog.stdout.log, _rollback_report.txt, _site_copy_report.txt, _verify_rendered_report.txt


**docs/reviews/ (59 files):** BACKLOG_MANIFEST_2026-07.json, BOARD_SPRINT_REVIEW_2026-03-16.md, BOARD_SUMMIT_2026-03-16.md, BOARD_SUMMIT_2_2026-03-17.md, BOARD_SUMMIT_2_2026-03-17_POINTER.md, CLOUDWATCH_AUDIT_2026-07.md, COACHING_SECTION_REVIEW_2026-06-28.md, DATA_SOURCE_HEALTH_REVIEW_2026-07.md, DATA_SOURCE_HEALTH_REVIEW_2026-07_findings.json, DEEP_PAGE_REVIEW_DPR1_PHASE2_RESULTS.md, DEEP_PAGE_REVIEW_DPR1_RESULTS.md, DEEP_PAGE_REVIEW_PROMPT_DPR1.md, DSR_BACKLOG_MANIFEST_2026-07.json, EDITORIAL_ACCURACY_REVIEW_2026-06-27.md, ELITE_REVIEW_2026-06-15.md, HAE_PATH_REVIEW_2026-06-19.md, IMPLEMENTATION_PLAN_WR4.md, PLATFORM_AUDIT_2026-06-30.md, PLATFORM_PRODUCT_REVIEW_2026-07.md, PLATFORM_PRODUCT_REVIEW_2026-07_findings.json, PRODUCT_REVIEW_PR1.md, PRODUCT_REVIEW_PR1_REVISED.md, PRODUCT_REVIEW_PROMPT_PR1.md, R21_BACKLOG.md, REVIEW_2026-03-08.md, REVIEW_2026-03-08_v2.md, REVIEW_2026-03-09.md, REVIEW_2026-03-09_full.md, REVIEW_2026-03-10.md, REVIEW_2026-03-10_full.md, REVIEW_2026-03-10_v6.md, REVIEW_2026-03-11_v7.md, REVIEW_2026-03-14_v13.md, REVIEW_2026-03-15_v14.md, REVIEW_2026-03-15_v15.md, REVIEW_2026-03-15_v16.md, REVIEW_2026-03-20_v17.md, REVIEW_2026-03-26_website_v4.md, REVIEW_2026-03-28_v18.md, REVIEW_2026-03-29_v19.md, REVIEW_2026-03-30_v19.md, REVIEW_2026-04-04_v20.md, REVIEW_BUNDLE_2026-03-10.md, REVIEW_BUNDLE_2026-03-14.md, REVIEW_BUNDLE_2026-03-15.md, REVIEW_BUNDLE_2026-03-29.md, REVIEW_BUNDLE_2026-03-30.md, REVIEW_BUNDLE_2026-04-04.md, REVIEW_CHARACTER_LEVELING_2026-03-30.md, REVIEW_HEVY_ROUTINE_WRITELOOP_2026_05_31.md, REVIEW_MEAL_GROUPING_2026-06-19.md, REVIEW_PROMPT_R20.md, REVIEW_PROMPT_R22_CONSULTANCY.md, SIMP1_PHASE2_PLAN.md, SUMMIT_2026-06-07_PRODUCT_GROWTH_REVIEW.md, WEBSITE_PANEL_REVIEW_2026-03-20.md, WHOOP_WEBHOOK_SPIKE_2026-07.md, mcp_architecture_review_2026-03-11.md, platform-review-2026-03-05.md


**docs/site-reviews/ (3 files):** README.md, SITE_REVIEW_2026-06-20.md, SITE_REVIEW_2026-06-21.md


**docs/specs/ (20 files):** CLAUDE_CODE_KICKOFF_2026-06-21.md, CLAUDE_CODE_PROMPT_DOORS_v1.md, CLAUDE_CODE_PROMPT_HABITS_PAGE_v1.md, CLAUDE_CODE_PROMPT_HEVY_NOTES_v1.md, CLAUDE_CODE_PROMPT_MEAL_GROUPING_v1.md, CLAUDE_CODE_PROMPT_MIND_PAGE_v1.md, CLAUDE_CODE_PROMPT_NUTRITION_PAGE_v1.md, CLAUDE_CODE_PROMPT_PHYSICAL_PAGE_v1.md, CLAUDE_CODE_PROMPT_READING_MIND_v1.md, CLAUDE_CODE_PROMPT_RECOVERY_ADAPTIVE_AUTHORING_v1.md, CLAUDE_CODE_PROMPT_SLEEP_PAGE_v1.md, CLAUDE_CODE_PROMPT_TRAINING_PAGE_v1.md, CLAUDE_CODE_PROMPT_VITALS_PAGE_v1.md, CLAUDE_CODE_PROMPT_v1.1.0.md, ER_EXTERNAL_REVIEW_RIGOR_2026-06-09.md, PG-14_ai_me_spike.md, PRODUCT_BOARD_SPRINT_HANDOVER.md, SPEC_CHARACTER_ENGINE_v1.1.0.md, TD-11_HABITIFY_PHANTOM_HABITS.md, TD-19_DATE_PARTITION_FIX.md


**docs/v2-audits/ (4 files):** 01_codebase.md, 02_aws.md, 03_ai_dataflow.md, 04_web_dx.md



---


*Bundle generated 2026-07-06 by deploy/generate_review_bundle.py*
