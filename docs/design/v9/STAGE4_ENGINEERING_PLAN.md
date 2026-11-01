# Stage 4 — Engineering architecture and implementation plan for the Stage 3 prototype

> **Status:** approved by the owner on 2026-10-31 with twelve decisions and four additional requirements (recorded on epic #5529); **Phase 0 authorised and built as the PR for #5530** — a non-public preview shell in `web/`, nothing deployed to `/`, nothing migrated. · **Written:** 2026-10-31 (Fable 5.1) · ADR-166 records the toolchain decision; `web/README.md` is the tree's guide.
> **Design source of truth:** the Stage 3 functional prototype (`https://claude.ai/artifact/7jvmahzD8fLQvux2qgoWhK`, version `1793493829-9b55`, 912 lines, read in full) and the Stage 1–2 canvas (`https://claude.ai/artifact/1SBbKGGAZjuWkjXFyA5SRk`, identity sheet `S2-Identity.dc.html`).
> **Companions:** `docs/PLATFORM_NORTH_STAR.md` (the why, unchanged) · `docs/SITE_MAP_AND_INTENT.md` (today's doors) · `docs/design/v8/README.md` (the kit this would supersede) · `docs/SITE_UPLEVEL_PLAYBOOK.md` (the gotchas still apply).

The governing principle the plan is built to: **simple on arrival, deep on demand.** The engineering translation: one typed content model, one static build, one publication boundary, zero new AWS infrastructure.

---

## A. Existing-state assessment

Everything below was measured on the working tree and the live site on 2026-10-31. Counts are the audit's, not the docs'.

### What is there

| Layer | State today | Verdict |
|---|---|---|
| **Ingest + store** | 107 Lambdas, 29 registered sources, DynamoDB single table (`USER#matthew#SOURCE#{src}` / `DATE#`), raw JSON in S3, source registry as the one vocabulary | **Retain untouched.** The site is a consumer of this. |
| **Compute** | Daily: evaluator 09:00Z, character sheet 09:30Z, metrics 09:40Z, insights 09:45Z, brief 10:00Z; weekly: correlations (Sun), hypothesis engine (Sun). All deterministic in Python; the model narrates only (`grounded_generation.py`, AST-guarded) | **Retain.** The rigor machinery (`stats_core.py`: effective n, Fisher CI, block bootstrap, BH-FDR; `calibration_core.py`: Brier, skill, Wilson) is better than what the prototype draws. |
| **Serving API** | One Lambda, 137 routes, 44,715 lines in `lambdas/web/`; CloudFront edge cache 300 s default; `/api/edition` is rebuilt per request from ~20 upstream handlers (87 KB), `/api/calls` 148 KB, `/api/predictions` 80 KB; no ETag, no precomputed edition | **Refactor at the edges, keep the core.** Add a handful of list/export routes for the build; do not re-platform. |
| **Edge + hosting** | S3 website origins (`/site`, `/generated`) + CloudFront `E3S424OXQZ8NBE`, 23 behaviours, CSP `script-src 'self'`, HSTS, no WAF, no custom error pages | **Retain.** Static output drops straight in. |
| **Frontend** | 117 served `index.html` outside `/legacy` (+82 legacy): 99 v5 pages (`tokens.css` 160 KB), 17 v8 kit pages (`clean.css`), 9 dead v7 previews; 105 JS modules / 2.09 MB; 19 stylesheets / 524 KB; 31 generators, 16 re-run on every deploy; kit pages hand-authored with no generator | **Replace the presentation layer.** Three design systems coexist; this is the maintenance problem the owner named. |
| **Content pipeline** | Chronicle: Story Desk → grounded-generation gate → privacy guard → preview email → approve Lambda → `generated/journal/*`; Panel podcast triggered by approval; essays via skill + PR; quotes via `mark_journal_quote` (approved=true required); owner words via filter only | **Retain the gates, add one missing stamp** (per-object visibility in the publication snapshot). |
| **Prediction ledger** | `COACH#{id}` / `PREDICTION#{pred_id}`; 468 rows, 214 decided (88 confirmed · 126 refuted), 20 pending, 10 expired, 224 observational; simple-guess baseline scored per call; sign test; K-of-N floors; dispute docket; sealed pre-registration with a published hash | **Retain; it is the site's strongest asset.** Fix the four grading defects in §F before they are rendered at scale. |
| **Privacy** | Four tiers in `field_tiers.py` (69 owner-only fields, 25 owner-only sources, ADR-155 stamp rule); content filter off-repo, fail-closed; PII surface guard in the deploy | **Retain.** The boundary stays exactly where it is: nothing public leaves the platform except through the Site API or an approval Lambda. |
| **CI/CD + QA** | 37 workflows; `site-deploy.yml` on merge with smoke + visual QA + AI vision + accuracy gate + scoped auto-rollback; `qa_manifest.py` (95 entries) as the page registry; 82 `node:test` files; Playwright render gates at 390/1280; axe on kit pages | **Retain and re-point** at the new build output. |
| **Monitoring** | 141 alarms; site alarms on errors/5xx/p95 ≥ 5 s/throttles/content-filter fallback; no CloudFront 5xx alarm on the main distribution; no SLO covers the public site | **Retain; add one SLO and one alarm** (see §G). |

### Retain / replace / refactor / retire

**Retain (reuse as is):** ingest, store, compute, the Site API core and its privacy gates, the edge, the deploy workflow and gates, the page-registry pattern, the methods registry (25 entries), the prereg seal, the subscribe flow, the podcast and chronicle pipelines, `stats_core` and `calibration_core`.

**Replace:** the presentation layer — the v5 shells and the `evidence_*`/`coaching`/`dispatches` module families as *navigation*, the hand-authored v8 kit pages, the 31 `v4_build_*` generators as the page-production method, the service worker (registered on 12 pages, pre-caches `/cockpit/`), and the hash-routed prototype itself (it is a reference for experience, not code).

**Refactor:** the Site API's list surfaces (`/api/calls` and `/api/predictions` serve windows of 63 and 49 rows; the build needs the full ledger, paginated); `/api/edition` from a per-request assembly into a nightly publication snapshot; the data-quality flags the prototype computes in the browser into fields the grader emits.

**Retire (kept served, per the owner's standing rulings):** the 9 v7 preview pages and their 20 CSS/JS files stop deploying and move under `/reference/`; the four live v8 pages become `/reference/2026-MM-DD-<slug>-v8/` at cut-over (ruling 2026-10-18); the ~88 v5 pages keep their URLs, leave navigation, and are listed on an appendix page (rulings 2026-10-04 and 2026-10-18). Nothing is deleted; nothing redirects.

### Technical debt that must not be carried forward

1. **Pages produced three ways** (hand-authored kit, generator shells, generated-at-deploy noscript proofs). One build, one way.
2. **Hand-maintained navigation and "connected" links.** `SITE_MAP_AND_INTENT.md` mirrors `v4_wayfinding.py` which mirrors the chrome; a kit page's deep links are hard-coded `data-ck-base` paths.
3. **Counts in literals.** `PLATFORM_STATS` and the doc-sync literals (`site_pages`, `review_count`) are pinned at deploy; the prototype hard-codes `LEDGER_TOTALS`. One producer per number (ADR-104).
4. **Methods tagged on ~5 of 113 figures.** The registry exists; the wiring does not. Every number on the new site resolves to a Method object or is labelled descriptive.
5. **Per-request assembly of the front page** (20 upstream calls, 4 threads, 8 s deadlines, "unavailable" fallbacks). A nightly snapshot removes the whole failure class.
6. **No `--delete` ever.** S3 holds every page and hashed asset ever published. Acceptable for history, but the new build must write to a prefix it owns so it can be reasoned about.
7. **Two sheets, three fonts stacks.** Fraunces/Instrument Sans/Plex Mono (v5), Geist (v8), now Archivo/Newsreader/Plex Mono (Stage 3). One identity, frozen as tokens.

---

## B. Proposed architecture

### B1. Shape

```
                 nightly (after compute, ~10:30Z) · on merge · on chapter approval
                                   │
  Life-Platform  ──public API──▶  publish_snapshot.py  ──▶  web/content/snapshot/*.json
  (DDB, S3,          (HTTPS,           (Python; the ONE          (typed, validated,
   compute)           no creds)         publication boundary)      visibility-stamped)
                                                                      │
                                                     Astro static build (web/) ──▶ dist/
                                                       content collections + schemas
                                                       one template per object type
                                                       "Connected" rail derived from edges
                                                                      │
                                   existing site-deploy.yml: sync → S3 site/ → CloudFront
                                   smoke · visual QA · axe · accuracy gate · rollback
```

- **Frontend: a static site generated by Astro (static output, zero client JavaScript by default), with vanilla-JS islands only where the prototype is interactive** (the data room, the ledger filters, the audio player). Pages are real URLs, not hash routes. Each object type has one template. The "Connected" block is computed at build from a relationship index, never hand-listed.
- **Backend/API: the existing Site API Lambda, unchanged in architecture,** plus three code-only additions: a paginated full-ledger export, a per-metric daily-series export for the data room, and a `visibility`/`as_of`/`source` envelope on any record the snapshot consumes (the `/api/edition` block contract already has exactly these five keys: `state`, `as_of`, `source`, `absent_text`, `data`).
- **Data access: a publication snapshot.** `scripts/publish_snapshot.py` (Python, in the repo, run in CI) reads only public HTTPS endpoints on averagejoematt.com and writes typed JSON into the Astro content directory. It never holds AWS credentials. The privacy boundary therefore does not move: what the Site API will not serve, the site cannot render.
- **Content model:** §D below. JSON files per collection, validated by schema at build; the build fails on an unknown field, a dangling reference, or a `held`/`private` object reaching a template.
- **Hosting and deployment:** the same bucket, distribution, workflow and gates. `dist/` syncs to `s3://matthew-life-platform/site/` through the existing `sync_site_to_s3.sh` path with its generator stage replaced by the Astro build. Astro content-hashes its own assets, so `hash_site_assets.py` applies only to the retained v5 tree.
- **No new AWS infrastructure.** No new Lambda, table, bucket, distribution or schedule in AWS. The one new schedule is a GitHub Actions cron (the nightly build), which under the charter needs a dead-man: the existing `check_deploy_deadman.py` pattern, pointed at the site-build workflow.

### B2. Why Astro, and the alternatives considered

| Option | What it is | Cost | Why / why not |
|---|---|---|---|
| **A. Astro static (recommended)** | Established static-site framework; content collections with schema validation and typed cross-references; one component per object; islands for interactivity; sitemap/RSS/OG built in; zero runtime JS unless an island asks for it | A Node build toolchain in CI (Node 26 and npm are already used for `node:test` and the CDK CLI); one lockfile to pin and Dependabot to watch | The content model *is* the site. Astro's collections give the registry primitive (schema), the derivation guard (dangling `reference()` fails the build) and the template-per-type for free. It is the mainstream answer for exactly this class of site in 2026. Output is plain HTML/CSS to S3 — vendor-neutral. |
| **B. Python SSG (Jinja2 + pydantic)** | A small in-repo generator, like the 31 `v4_build_*.py` scripts but unified | No new toolchain; pytest covers it | Honest option. But it means writing our own collection loader, schema validation, routing, relationship resolution, image handling and asset pipeline — a bespoke framework, which is what the owner asked to avoid, and it is what produced the current 31 generators. |
| **C. Extend the v8 kit by hand** | Keep hand-authoring HTML on `clean.css` with `ck_*.js` binding | Nothing new | Does not scale to hundreds of objects (no templates, no index); it is the architecture that stalled. Rejected. |
| **D. A dynamic app (Next/SSR, API-driven)** | Server-rendered pages per request | New compute, new failure modes, new cost | The data changes nightly. Rendering at request time buys nothing and reintroduces the per-request assembly problem. Rejected. |

The rule `CLAUDE.md` states for the site ("vanilla-JS ES modules, no framework/deps") is about what ships to the reader. Astro's static output honours it: the reader receives HTML, CSS, self-hosted fonts and a few vanilla modules. The rule should be restated as "no client-side framework; a build-time toolchain is permitted", and the docs that say "no npm, no bundler" (`SITE_AUTHORING.md:17,62`) updated. **This is decision 1 in §H.**

### B3. Freshness model

The data arrives nightly; the site rebuilds nightly after the compute chain (≈10:30Z) and on every merge. A chapter approval should also trigger a build — the cleanest route is the approve Lambda calling the GitHub `repository_dispatch` API with a scoped token; that is a new secret and a Lambda code change, so it lands in Phase 3, and until then an approved chapter appears at the next nightly build (the current site already shows chapters only after a CloudFront invalidation, so this is not a regression).

Two blocks are allowed a progressive-enhancement client fetch against the existing `/api/edition`: today's weight tile and the open-predictions count. Everything else is baked, dated, and says "data through <date>". This is what makes "updates nightly" true rather than aspirational.

### B4. Interactivity budget

Islands, each a vanilla ES module with a `node:test` file, each loading only on its page:
1. **Data room** — chart drawing, range/compare/lag controls, tooltip. Series arrive as prebuilt JSON per metric; statistics arrive **precomputed** (see §F).
2. **Ledger filters** — filter a prebuilt JSON index (status × coach × quality) client-side; every prediction also has its own static page.
3. **Audio player** — native `<audio>` over the existing MP3s with chapter markers from the transcript.
4. **Theme / reduced-motion** — the existing `boot_theme.js` pattern.

No client router, no state library, no third-party script.

---

## C. Design-to-production mapping

Hash routes become directory URLs. Existing URLs are not reused for new objects so nothing already published changes meaning.

| Prototype route | Production URL | Template / data | Notes and necessary UX changes |
|---|---|---|---|
| `#start` | `/` | `Start.astro`: premise, portrait tiles (6 dimensions), this week's chapter, "What's alive", three doors, coaches-this-week, follow | **UX change 1:** remove "Thirty-seven" from the hero copy — chronological age is never published (Option A, PhenoAge ruling 2026-06-23). **UX change 2:** the coaches' number renders as "K of N right, beside a simple guess that would have scored M" — never a bare percentage (ADR-157, #4580 rule 3); "67/157" becomes the live K-of-N from one producer. **UX change 3:** add the one-line disclosure that the coaches are software built with Claude, not people (standing ruling). Photo frame stays a frame until a dated approval stamp exists. |
| `#story` | `/story/` | `StoryIndex.astro` over the Chapter collection | **UX change 4:** chapters are listed by the chronicle's own `week` field with explicit `held` and `skipped` states (Week 7 skipped, Week 8 held today — #5520), not an unbroken 01–08 run. Prologue and plan posts (2026-08-31, 09-05) appear as chapters 00a/00b. |
| `#chapter-NN` | `/story/week-NN/` | `Chapter.astro`: lead, player, article, figures, Connected rail, prev/next | Body comes from the published chronicle (`content_markdown`), not re-written. Figures are Metric embeds with a "data through" stamp and a link into the data room with the window pre-set. Audio is real (5 episodes exist with MP3 + transcript). Journal lines render only with a `mark_journal_quote` approval. |
| `#data` (+ `data-explore` params) | `/data/` and `/data/<metric>/` | `DataRoom.astro` + island; `Metric.astro` per metric | **UX change 5 (statistical):** the compare/lag panel prints the precomputed Spearman/Pearson with effective n, a block-bootstrap CI and the family-wise (BH-FDR) threshold for all lags offered; the lag range is −2…+2 (not ±7); the word "significant" never appears; the regime boundary on 2026-10-10 is drawn on HRV and resting-HR charts and baselines split at it. Each metric's "How this is measured" is the Methods Registry entry, not prose typed into the page. |
| `#insight-<slug>` | `/data/insights/<id>/` | `Insight.astro` | Evidence panel from the grader's record; "surfaces in" from the edge index. |
| `#experiment-NN` | `/data/experiments/<id>/` | `Experiment.astro` | From `SOURCE#experiments` + the prereg seal; a proposed-not-registered experiment renders as the prototype's empty panel. |
| `#reflect` | **none on the public site** | — | **UX change 6:** the reflection form is the owner's instrument, not the reader's. Capture moves to the owner's channel (the 20-second evening check-in already in Now, #5106, plus `log_evening_intake`), stored owner-only; the public Mind tile shows counts, and averages only once n ≥ 7, through a `TIER_OWNER_PUBLISHED` aggregate stamp. Readers never see a form. **Decision 5 in §H.** |
| `#system` | `/system/` | `System.astro`: depth 1 plain English, depth 2 headline three ways + calibration table, depth 3 under the hood | Depth 2's "clean rate" and flags are read from grader fields, not computed in the page. Depth 3's pseudo-code is rendered from the Methods Registry entries (`directional_window_verdict`, `calibration_verdict`), so it cannot drift from the code — the prototype's text already disagrees with the evaluator (expiry is "past 2× the window", not "fewer than 4 readings after 28 days"). |
| `#ledger` | `/system/ledger/` (+ `/system/ledger/<status>/`) | `Ledger.astro` + filter island over a JSON index | **UX change 7 (mobile):** rows collapse to a two-line card at ≤ 760 px; the three `<select>`s become a sticky filter strip; the five-up `.facts` grid becomes a 2 × 3. |
| `#prediction-<id>` | `/system/ledger/<prediction_id>/` | `Prediction.astro` | One page per prediction (468 today). "How it was graded" = the record's `outcome_notes` + the method entry. Flags (`gap`, `weak`, `proxy`) come from the grader (§F). "Beats the simple guess" is the existing `simple_guess` block. |
| `#coach-<id>` | `/system/coaches/<persona_id>/` | `Coach.astro` | Eight operational coaches plus the lead (`eli_marsh`, missing from the prototype); a retired coach (Sarah Chen) says "retired" with the date, not "no checked call yet"; an absent instrument renders "no sensor since <date>" (the existing `instrument_presence` contract). |
| System › sources table | `/system/sources/` and `/system/sources/<source_id>/` | `Source.astro` from `source_registry` + `/api/source_freshness` | live / stale / paused from the registry's `stale_hours` and `paused` facets. |
| footer "Verified · Sample" chips | build-time `provenance` on every figure | `<Figure>` component | A figure renders a chip only from its record's `state`/`as_of`; no hand-placed chips. |
| (absent) | `/system/everything-else/` | `Appendix.astro` | **UX change 8:** the footnote appendix of the ~88 kept pages (owner rulings 10-04 and 10-18); linked from the footer, excluded from the reach ratchet. |
| (absent) | `/privacy/`, `/subscribe/`, `/404.html` | restyled utility pages | Required by the subscribe flow and the policy. |

**Identity, carried as tokens (from the Stage 2 sheet, frozen):** paper `#F4F4F0`, ink `#121212`, cobalt `#1B3FD6` (measured, confirmed, primary series, links), vermillion `#D9341C` (refuted, flagged, what broke — meaning, never direction), ochre `#B97A12` (compared series), hollow dashed (pending, missing, sample). Archivo for structure and numerals (expanded for figures, tabular always), Newsreader for Matthew's voice only, IBM Plex Mono for the machine's voice. Four destinations: Start · Story · Data · System; a four-tab bottom bar at ≤ 760 px.

**Three more necessary changes the prototype could not make:**
- **UX change 9 (fonts):** Google Fonts → self-hosted subsets (CSP is `font-src 'self'`). Budget ≤ 250 KB for all three families; Archivo's width axis is used, so keep the variable file but subset it to Latin and the axis ranges actually used.
- **UX change 10 (accessibility):** `--faint #B9B9B3` on paper measures ≈1.9:1 and the 10 px uppercase mono labels fall below the 11 px floor; raise the faint token to ≥ 4.5:1 for any text use and set labels/chips at 11–12 px (the same correction the v8 kit made to `--ck-faint`). Chart tooltips get a keyboard path (focusable series points with `aria-describedby`); pill groups become real radio groups.
- **UX change 11 (states):** the prototype's 650 ms fake skeleton goes; static pages have no loading state. Islands render their static fallback first (the baked numbers) and enhance.

**Dark mode:** the prototype is light-only. The current site treats both themes as first-class. Designing dark tokens unilaterally would be a redesign, so the recommendation is light-only at launch with `prefers-color-scheme` respected only for the browser chrome, and a dark pass as a later owner-reviewed screen. **Decision 6 in §H.**

---

## D. Privacy and publication model

### D1. The boundary

Private source data becomes public content through exactly one of three doors, all of which exist today:

1. **The Site API** (Lambda, CloudFront) — per-endpoint gates (`_strip_genetic_biomarkers`, `reading_visibility.project_public`, `food_names` allowlist, the content filter fail-closed) over the `field_tiers` declarations.
2. **An approval Lambda or tool with a human stamp** — chronicle approve (per-draft token), `mark_journal_quote` (`approved=true`), the essay PR, progress-photo viewer (owner-only link).
3. **A build-time scan over the output** — `pii_surface_guard.py` and `content_policy_scan.py` already run in the deploy.

The plan adds no fourth door. The snapshot exporter reads door 1 over public HTTPS; the build re-runs door 3 over `dist/`. If a field must become public that is not today, it goes through the ADR-155 stamp (`TIER_OWNER_PUBLISHED` in `field_tiers.py`), which `tests/test_privacy_tier_wiring_2803.py` and `test_data_governance_tier_guard_3045.py` already police.

### D2. Per-object publication record

Every object in the snapshot carries:

```json
{ "id": "...", "type": "prediction", "visibility": "public" | "held" | "private",
  "as_of": "2026-10-31", "data_through": "2026-10-30",
  "source": ["/api/calls"], "state": "ok" | "stale" | "absent",
  "approved": { "by": "owner", "at": "2026-10-28T19:02Z", "via": "chronicle-approve" } | null,
  "method_ids": ["directional_window_verdict"], "edges": [{"type":"coach","id":"sleep_coach"}] }
```

Rules the build enforces (as tests, not conventions): a `held` or `private` object never reaches a template; a Chapter, Essay, Quote or Photo without an `approved` stamp is `held`; a figure with no `method_ids` renders the label "descriptive only" (ADR-105); `state: stale` renders its `absent_text` in the prototype's hollow style.

### D3. Specific categories

| Category | Rule | Mechanism today |
|---|---|---|
| Journal text | Never, unless a specific line is marked approved | `mark_journal_quote`; `SOURCE#notion` owner-only |
| Reflections (happiness, connection, purpose) | Counts public; averages after n ≥ 7; notes never | Owner-only capture (#5106 channel); aggregate stamped ADR-155 |
| Medical (AF diagnosis, ECGs, medication) | Never on a reader surface; the HR regime change appears only as an unexplained dated boundary | #4972 owner-only channel; `hr_regime.py` |
| Chronological age, genome identifiers, substances, employer, partner | Never | PhenoAge Option A; `test_public_genetic_privacy_absolute`; content filter; `DATA_GOVERNANCE.md` editorial guardrails |
| Photos | Only with a dated approval stamp, GPS EXIF stripped, never shirtless | Rulings 2026-10-02 and 2026-10-03 |
| Training loads | Public (ruling 2026-09-26) | `/api/session`, `/api/workouts` |
| Coach text | Served verbatim, never rewritten; glossed; marked where the engine disagrees | `claim_sourcing.py`; `check_served_coach_facts.py` |

### D4. What this fixes that is open today

- `generated/*` and `site/*` are anonymously readable at the S3 origin (#3559/#3741 guards exist; the broad grant remains). The new build writes only public output, so the risk class is unchanged; the plan does **not** touch the bucket policy (infrastructure).
- Owner words reach `/api/owner_words` with no human step (filter only). Unchanged by this plan; flagged in §H as a product question, not a build task.

---

## E. Content scalability strategy

### E1. The model

Seven object types from the brief, four added, two deferred.

| Type | Stable id (exists today) | Canonical URL | Record source | Relationships stored on it |
|---|---|---|---|---|
| **Chapter** | chronicle `DATE#<week-ending>` → published `week` | `/story/week-NN/` | `generated/journal/posts.json` + the row's `content_markdown` | episode, featured coach, bets, metrics in figures (declared in the chronicle's `LEDGER#`) |
| **Episode** (added) | `wk<N>` | `/story/week-NN/#listen` (no separate page) | `generated/panelcast/episodes.json` | chapter |
| **Essay** (added — "in my own words") | slug | `/story/essays/<slug>/` | `site/journal/blog.json` + body | none required |
| **Metric** | field name (`weight_lbs`, `hrv`, `deep_pct`) | `/data/<metric>/` | `measurable_metrics.METRIC_SOURCES` + `metric_truth` + new series export | source (winner), method(s), coach (reader) |
| **Insight** | `INSIGHT#<date>#<type>#<slug>` | `/data/insights/<id>/` | `SOURCE#insights`, `SOURCE#hypotheses` | predictions, metric, chapter |
| **Experiment** | `<slug>_<start_date>` | `/data/experiments/<id>/` | `SOURCE#experiments` + prereg seal | hypothesis, metric, predictions, chapter |
| **Prediction** | `pred_<YYYYMMDD>_<slug>` / `bet-…` / `<coach>-<date>-<hash>` | `/system/ledger/<id>/` | `COACH#<id>` / `PREDICTION#` via the new paginated export | coach, metric, experiment, insight, disagreement |
| **Disagreement** (added — the dispute docket) | `docket-<ref>-<date>` | `/system/ledger/disagreements/<id>/` | `ENSEMBLE#docket` via `/api/coach_docket` | two coaches, metric, predictions |
| **Coach** | `persona_id` | `/system/coaches/<id>/` | `config/personas.json` + `/api/coaches` + records | predictions, sources (`instrument_for`), disagreements |
| **Source** | registry key | `/system/sources/<id>/` | `source_registry.py` via `/api/source_freshness` | metrics, coach |
| **Method** (added) | registry id | `/system/methods/<id>/` | `methods_registry.py` via `/api/methods` | figures that cite it |
| Event / milestone | — | — | — | **Deferred**: the prototype's "Upcoming" list is derived (next chapter date, next grading date, next milestone) rather than a stored type |
| Technical doc | ADR-NNN | GitHub link from System depth 3 | `docs/DECISIONS.md` | **Deferred**: linking is enough at launch |

**Identifier gap to close first:** the chronicle is keyed by date in the database and by a `week-NN` counter on the site, and the two have already drifted (a skipped week). The Chapter collection keys on the database date and derives the public label from the row's `week` field; the counter is never incremented by the site.

### E2. Relationships without a graph database

Edges are stored once, on the object that *knows* them (a prediction knows its coach and metric; a chapter declares what it touches). At build, `scripts/publish_snapshot.py` emits `edges.json`; the Astro build inverts it into an index (`by_target[type][id] → [sources]`). The "Connected" rail on any page is `edges_out ∪ edges_in`, sorted by type then date, capped at seven with a "see all". Astro's `reference()` makes a dangling edge a build failure. This is a JSON index of a few thousand rows, rebuilt nightly in milliseconds; a graph database would be machinery with no rent to pay (`docs/PROPORTIONALITY.md`).

### E3. Discovery paths (the same object from many contexts, one copy)

1. **The four destinations** — Start/Story/Data/System, each a surface of ≤ 4 screens with "see all" into an index.
2. **Indexes per type** — paginated list pages with facets (status, coach, metric, week), built statically; the ledger's client filter is a convenience over the same index.
3. **Connected rails** — every object page.
4. **Time** — a `/story/week-NN/` is also the hub for that week's predictions, insights and figures (the week is the unit of the experiment).
5. **Search** (Phase 5) — Pagefind, a static search index built at build time, zero infrastructure, loads only when the reader opens search.
6. **Feeds and machines** — RSS for chapters (exists), the podcast feed (exists), `sitemap.xml` from the route manifest, JSON-LD (`Article`, `PodcastEpisode`, `Dataset` for metrics), per-object OG images via the existing `/og` Lambda.

### E4. Staying small at hundreds of objects

- A new object type is a schema file, a template and an edge type; no navigation edits.
- The reach ratchet (`NAV_REACH_CEILING`, 18 today) is kept and measured on the new tree; the appendix is excluded by ruling.
- `qa_manifest.py` stops being a hand list: the Astro build emits a route manifest and the manifest derives from it (type → tier, content class, api deps), with the existing `tests/test_qa_manifest.py` re-pointed.
- Doc-sync count literals (`site_pages`) read the route manifest.

---

## F. Phased implementation roadmap

Each phase ends with something a reader can use on the preview path (`/next/v9/`, `noindex`, the existing preview convention) and one owner review of real screens on a phone. Durations assume Claude-driven sessions at the recent cadence; they are estimates, not commitments.

### Phase 0 — Foundations (≈1 week) · no reader-visible change
- Decisions in §H recorded on the epic.
- `web/` scaffold: Astro static, `astro.config` with `inlineStylesheets: 'never'` and no inline scripts (CSP `script-src 'self'`), the identity as CSS custom properties, the three families self-hosted and subset, the four-destination shell, the Figure/Provenance/Connected components, the appendix and privacy pages.
- Content schemas for the eleven collections; `scripts/publish_snapshot.py` reading the public API; the `held/private` build gate as tests.
- `site-deploy.yml` gains a `web` job building to `/next/v9/`; the v4 render gate, axe and `node:test` run against it. Record the nightly cron's dead-man.
- **Exit:** an empty-shell preview builds in CI and passes the gates.

### Phase 1 — Start, Story, Chapter (≈2 weeks) · first usable preview
- Chapter collection from the 8 published posts (+ held/skipped states), Episode collection from the 5 MP3s with real audio and transcript markers, Start page with the portrait tiles from the existing `/api/edition` blocks, Connected rails.
- Site API addition 1: a `week` and `held/skipped` field on `posts.json` (code-only; #5520 is the same defect).
- **Exit:** a reader can land, understand the experiment, read and listen to every published chapter, and reach a coach or prediction from a chapter — on a phone, at 390 px, A on the render gate.

### Phase 2 — Data room (≈2 weeks)
- Site API addition 2: `/api/series/<metric>?from&to` (daily values with a per-day presence flag; logging gaps distinguished from missing readings) and a nightly precomputed pair-statistics table (`stats_core`: Pearson and Spearman, effective n, block-bootstrap CI, BH-FDR across the offered pairs × lags −2…+2) — delivered as extensions of `weekly_correlation_compute`, not a new Lambda.
- Metric pages from the Methods Registry; the explorer island draws only. The HR regime boundary is drawn and baselines split.
- **Exit:** every figure on the site cites a method or says "descriptive only"; no correlation claim without n, effective n and an interval.

### Phase 3 — System, ledger, coaches, sources (≈2 weeks)
- Site API addition 3: paginated full-ledger export with the grader's data-quality flags.
- Grader fixes that the ledger pages would otherwise expose at scale (all engine-side, each its own PR): (a) emit `quality_flags` (`logging_gap`, `low_power`, `proxy_metric`) on every graded row from the record itself; (b) grade retired coaches' sealed bets (`COACH_IDS` excludes `training_coach`, #5518); (c) treat zero-entry food days as missing, not 15 g (the #5519 class); (d) make the point grader respect `after_day` for `_7day_avg`; (e) read `hr_regime.py` in the evaluator's and `coach_baseline`'s windows.
- Coach pages (lead + staff + retired), source pages, method pages, disagreement pages; the "clean rate" computed in Python from the flags.
- The approve Lambda triggers a build (`repository_dispatch`, one scoped token in Secrets Manager — a code change plus one secret; the IAM diff, if any, is owner-required).
- **Exit:** every one of the 468 predictions has a page whose grading text is the record's own; the headline is one producer's K of N beside the simple guess.

### Phase 4 — Cut-over (≈1 week, on a Thursday morning PT, as before)
- Reference copies of the four v8 pages under `/reference/`; the v7 preview tree retired to `/reference/`; the appendix lists everything kept.
- `qa_manifest` derives from the route manifest; `NAV_REACH_CEILING` re-measured and lowered; sitemap/RSS/robots from the build; `og:image` per object.
- Rehearsal with rollback (`rollback_site.sh`), five real readers on a phone recorded (the #4580 bar), smoke + visual QA green, then `/next/v9/` → `/`.
- **Exit:** every existing URL still returns 200; the kept pages are unchanged and out of navigation; a red deploy rolls back by itself.

### Phase 5 — Depth (ongoing, one object type per session)
Search (Pagefind); essays; insights and experiments as they are created; the reflection aggregate once the owner-only capture has seven entries; historical snapshots (`generated/publication/<date>.json`, needs one additive S3 grant — owner-required); the dark theme as an owner-reviewed screen; the character sheet and badges re-homed from the appendix (the owner keeps them, ruling 2026-10-04).

---

## G. Risks and trade-offs

| Risk | Why it is real | Mitigation |
|---|---|---|
| **A third design system during the transition** | 99 v5 + 17 v8 pages are live; a v9 preview adds a third | Freeze v5 and v8 (no further changes), cut over as one event, move the predecessors to `/reference/` the same morning. |
| **Chapters are the spine and the pipeline is held** | The Story Desk hold (since 10-18), Week 7 skipped, Week 8 waiting on approval; the owner parked site and desk work the week of 10-26 | The Chapter collection renders `held` and `skipped` honestly (the state is content, not a bug). The site never depends on a chapter existing to be useful: Start and Data stand alone. |
| **The lag explorer invites false findings** | n ≈ 56 daily points, autocorrelated; a slider over 15 lags × 6 metrics is a multiple-comparison machine | Precomputed stats with effective n and FDR across the family; lags −2…+2; language fixed by template; the three pre-declared questions are the default entry. |
| **Rendering 468 prediction pages exposes grading defects** | Four known defects (§F Phase 3) | Fix the grader before the pages ship; the pages make the defects visible to readers otherwise. |
| **Node toolchain in a Python repo** | A second ecosystem for sessions to carry; supply chain | Lockfile, pinned Astro, Dependabot (as for `cdk/`), a `node:test` suite that already exists, a one-command local build. The alternative (Option B) carries a different cost: a bespoke framework. |
| **Nightly build is a schedule** | Charter: every schedule gets a dead-man | Reuse `check_deploy_deadman.py` logic for the build workflow; alarm if no successful build in 36 h. |
| **Owner review bandwidth** | Every screen needs a yes; prior cut-overs stalled here | One screen per review, one question ("what's wrong with this screen?"), no taste questions (the #4580 rule). |
| **Snapshot over the public API reaches only served windows** | `/api/calls` 63, `/api/predictions` 49 rows | Phase 3's paginated export; until then the ledger is honest about "N of M loaded", as the prototype is. |
| **Fonts and weight** | Three families, one variable with two axes | Subset, preload two, `font-display: swap`, measure against the existing LCP 2.5 s gate. |
| **No site SLO** | Nothing says what "up" means for readers | Add one SLO (availability from the smoke probe, p95 from the existing metric) and a CloudFront 5xx alarm on the main distribution (CDK, additive — owner-required, Phase 4). |

**Alternatives rejected and why:** a dynamic SSR app (no benefit at nightly cadence); a headless CMS (adds a vendor between the owner and his own data; the platform *is* the CMS); a graph database (a JSON index does the job); a big-bang rewrite including the 88 v5 pages (the rulings keep them served; re-homing is Phase 5, one type at a time).

---

## H. Decisions requiring your approval

1. **Toolchain.** Astro static build in `web/` (recommended) vs. a Python/Jinja generator. Approving Astro also approves restating the "no framework/deps" rule as "no client-side framework".
2. **Supersession.** The Stage 3 direction replaces the v8 kit as the approved look (your 2026-10-03 and 10-18 rulings named the kit "the approved direction"). The four live v8 pages move to `/reference/` at cut-over under your 10-18 keep-the-old-layout rule. Confirm.
3. **Freshness.** Nightly rebuild (a GitHub Actions cron with a dead-man) plus two progressive-enhancement fetches, vs. client-side fetching everywhere. Recommended: nightly.
4. **Publication snapshot source.** Read the public API over HTTPS with no credentials (recommended), vs. a read-only IAM role in CI reading DynamoDB directly (faster, but a second privacy boundary to guard).
5. **The reflection instrument.** Owner-only capture through the evening check-in channel, public aggregates only (recommended), vs. the prototype's reader-facing form (which would store strangers' entries or nothing).
6. **Dark mode.** Light-only at launch, dark as a later reviewed screen (recommended), vs. designing dark tokens now.
7. **Hero copy.** Removing the age; keeping "British, in Seattle" (nationality and city have appeared in published chapters). Confirm or strike.
8. **Grader fixes before the ledger ships** (Phase 3 a–e). These change graded outcomes for a small number of rows (zero-entry food days; retired coach's sealed bets). Confirm they are in scope.
9. **Infrastructure asks, all deferred and each owner-required when they come:** a scoped GitHub token in Secrets Manager for approve-triggers-build (Phase 3); an additive S3 grant for `generated/publication/` history (Phase 5); a CloudFront 5xx alarm (Phase 4). None is needed for Phases 0–2.
10. **Owner words with no human step.** Today `/api/owner_words` publishes any note that passes the filter. Not a build task, but the new Start page will show it more prominently; decide whether a stamp is wanted.
11. **Cost.** No new AWS spend; CI minutes for a nightly build (~2–3 min). Confirm acceptable.
12. **Scope of chapters 00–06 migration.** Render the published chronicle text as-is (recommended, it is approved content) vs. re-edit in your voice (a Story Desk task, held).

---

## Appendix — what was audited

Read in full: the Stage 3 prototype (912 lines) and the Stage 2 identity sheet and canvas; `docs/CHARTER.md`, `PLATFORM_NORTH_STAR.md`, `SITE_MAP_AND_INTENT.md`, `SITE_TRANSFORMATION_V6/V7.md`, `design/v8/README.md`, `DESIGN_PARTNER_BRIEF.md`, `SITE_UPLEVEL_PLAYBOOK.md`, `SITE_AUTHORING.md`, `PROPORTIONALITY.md`, ADR-157, `handovers/HANDOVER_LATEST.md`, the open backlog (51 issues), the owner's site rulings in memory. Five read-only audits by subagents over: the frontend tree and build; the Site API and edge; the content and publication pipeline; the prediction ledger, grading and statistics; privacy, security, CI and monitoring. Live, read-only GETs against `/api/receipts`, `/api/edition`, `/api/predictions`, `/api/calls`, `/api/coaches`, `/api/platform_stats`, `/api/source_freshness`, `/journal/posts.json`, `/panelcast/episodes.json` and `/`.

Not done, by instruction: no deploy, no production change, no data migration, no deletion, no AWS provisioning, no implementation. The one file written is this document (uncommitted).
