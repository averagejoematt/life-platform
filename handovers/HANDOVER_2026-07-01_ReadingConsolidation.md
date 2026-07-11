# HANDOVER — Reading/Mind pillar: consolidated into the Data door + made content-rich — 2026-07-01

> **The reading pillar is now ONE coherent, content-rich experience inside the Data door, and `main == live` (0 open PRs).**
> Consolidated from two mismatched surfaces into `/data/reading`; every book shows its "why" (the coach's recommendation
> reason). Follows the audit session (below) — all of its PRs (#295/#296/#297/#298/#299) are merged; main is green.

## ⚠️ STATE
- **`main` == #299** (`20e8b15f`), **0 open PRs**, `main == live`. The audit PRs are all in.
- Reading lives entirely at **`/data/reading`** (Data door). The standalone **`/mind/` is retired** — it's a `noindex` redirect stub → `/data/reading` (bookmarks don't 404).

## WHAT & WHY
Matthew's feedback on the audit's PROD-01 fix (#298 had added `/data/reading` as a *thin* tile): it was too thin ("just the book I'm reading, not in the spirit of the data page") and clicking "open the full library" jumped to the standalone `/mind/` page, which "made the rest of the site look odd." **Root cause (2 Explore agents):** reading rendered **twice in two chromes** — thin `/data/reading` (evidence.css) + rich `/mind/` (cockpit.css+mind.css, no active-door highlight, truncated footer). **Owner call:** "I just want it to look like the same website" + "full depth" → consolidate into one Data-door surface, retire `/mind/`.

## BUILT (PR #299 — 3 phases, all live + verified)
- **P1 — consolidate + rich render:** `renderReading()` in `site/assets/js/evidence.js` is now the full async readout (reading-now, shelf, roundedness wheel, idea constellation), ported from `mind.js`, restyled `.rdg-*`/`wh-*`/`cst-` in `evidence.css`. **Retired `/mind/`:** repointed the 2 inbound links (`story.js:45` home constellation node; `/now/` cockpit reading line) to `/data/reading`; `site/mind/index.html` → `noindex` redirect stub; sitemap regenerated.
- **P2 — serve the reflections:** `lambdas/web/site_api_reading.py::_public_shelf_item` joins each book's **public** notes via `reading_visibility.project_public_list` (fail-closed — only `public:true` notes serve). Deployed via `deploy_site_api.sh`.
- **P3 — render the "why" + reflections + takeaways:** `readingNotes()` renders them as the loudest type — **"Why this book"** (intention) / "The takeaway" (synthesis) / "Reflections". The queue was generalized from bare spines to `readingBookList` so the why shows per book.

## ⚠️ THE KEY INSIGHT (drives the design)
Owner: *"I don't know what my intention is, I'm going off your recommendation."* → **the "why" belongs to the coach/recommender, NOT the reader** (the brief's anti-black-box reason-string rule). Forcing the reader to write an intention was backwards. So I **wrote 6 coach-authored recommendation reasons** (Dark Matter + the 5 queued books) as public `intention` notes via `reading_store.add_note` — the exact fn the MCP uses — with a **stable `noteId="coach-why"`** so they're idempotent + **editable in place** (rewrite the same sk to change framing; delete-item to remove). **No new field/tool/allowlist needed:** `intention` is just a public note type, `project_public` gates purely on the `public` flag (type-agnostic), and the capture path (`manage_reading add_note`) already existed.

## GOTCHAS
- **Local render QA hangs:** the `http.server` + Playwright harness times out on `goto` because the **service worker** stalls headless local loads. Verify reading-page renders against **live prod + a Playwright route-mock** instead (inject a sample note into `/api/reading_overview` to prove the populated render without fabricating owner content).
- **`/api/reading_*` is CDN-cached 300s** — after writing a note, `curl` with a `?cb=<ts>` buster (or `aws cloudfront create-invalidation --paths /api/reading_shelf /api/reading_overview`) to see it immediately.
- Reading write-tools (`manage_reading`) were **not exposed in this session's MCP** — wrote notes directly via `reading_store.add_note` (same schema/fn). `mind.js`/`mind.css` are now orphaned but harmless (left in place).

## OUTSTANDING (reading)
1. **Auto-recommender-reason path** (the clear next want): wire `reading_recommender`'s reason string to persist as a `RECOMMENDATION#` on `add_book` so every future book auto-gets a "why" — no manual note. Reconcile the `reason` vs allowlisted `reasonString` field-name mismatch; serve it on the shelf item.
2. Proper **`/mind/` CloudFront 301** (vs the current `noindex` stub) — add to `redirects.map` + republish the `v4-redirects` function (careful — it gates all viewer routing).
3. Rename the Data door's **"Mind & inner life"** tile → **"Mood & journal"** to fully de-collide with the reading pillar.
4. The 6 coach-why reasons are the owner's to edit — he may reframe any (e.g. picked Dark Matter for the idea, not the momentum).

## OUTSTANDING (from the audit session, still open)
- **DEVOPS-02** (OIDC trust tighten — dangerous, needs a dedicated session; plan in the audit handover below).
- **Doc-truth batch** — CQ-02 (ARCHITECTURE.md layer/ADR/module) + CQ-03 (CLAUDE.md counts) + PRIV-03 (DATA_GOVERNANCE + the stale Secrets Manager table).

---

# HANDOVER — Platform deep-dive audit + Tier-0/Tier-1 remediation — 2026-07-01

> **A full consulting-grade audit (80-agent workflow, token-only, $0 AWS/Bedrock) → 9 PRs, 5 stacks deployed + live-verified.
> Platform verdict: fundamentally healthy (0 P0, 0 P1). One Tier-1 item (DEVOPS-02 / OIDC) deliberately deferred.**

## ⚠️ IMMEDIATE STATE (read first)
- **`main` == #294.** **#295 (pexels registry) + #296 (REL-01 heartbeats) are OPEN.**
- **`main` is RED until #295 merges** — the audit's CI-integrity work unmasked two pre-existing red-mains (see cascade below). After #295, the full suite is green (verified locally: 2427 passed, black/ruff/mypy clean).
- **#296 (REL-01) is DEPLOYED but not on main** → a `cdk deploy LifePlatformMonitoring` from main would DROP the 4 new alarms (reverse-drift). **MERGE ORDER: #295 first, then #296.**
- Deploys done this session: **Compute, Email, MCP, Operational ×2 (COST-01 + SEC-01), Monitoring**, `deploy_site_api.sh`, `sync_site_to_s3.sh`. Each behind a `cdk diff` read (bundle re-hashes / +4 alarms / one IAM condition — zero destroys).

## THE AUDIT
`docs/reviews/PLATFORM_AUDIT_2026-06-30.md` (25KB). An 80-agent `Workflow`: 10 expert lenses (security · architecture · cost · reliability · correctness · code-quality · privacy · devops · product · frontend), each finding **adversarially verified** by a skeptic that reads the actual code (→ 23 confirmed, 45 refuted — the ~50% false-positive filter). **0 P0, 0 P1, 4 P2, 19 P3.** 7 systemic themes (worth more than any single finding): UTC-vs-Pacific date selection · silent-failure detectors that can themselves go silent · multiple-source-of-truth drift · doc-drift-behind-a-fresh-façade · IAM-known-but-not-applied · CI gate-coverage/masking · built-but-stranded surfaces.

## TIER 0 — deployed + live-verified (#289/#290/#291, MERGED)
- **BUG-01/02/03** (#289): `circadian-compliance` (7 PM PT) + `evening-nudge` (8 PM PT) + nutrition-MCP derived "today" from **UTC** while data is keyed by the **Pacific** day → their evening crons (02:00–03:00 UTC = *tomorrow* PT) scored an empty future day (published to `/now`) / cried "not logged". Fix: canonical `lambdas/pacific_time.pacific_today()` (bundled into Compute+Email → **no layer dance**) + MCP-single-source mirror `mcp.core.pacific_today`. **Live-proof:** at the real bug window (UTC 07-01 / PT 06-30) circadian wrote `DATE#2026-06-30`. Same class as the #133 DST fix, day-selection sibling.
- **FE-01** (#290): dead `role="button"` on the cockpit consistency band → removed (verified gone on live `/now`).
- **BUG-04** (#290): `/api/vitals` 30d trend on a `key=lambda _:0` no-op sort (correct only by DDB return-order luck) → explicit sort, **output unchanged**, + shuffled-input ordering-contract test.
- **COST-01/CQ-04** (#290): "hourly"→"every 8h" docstring; "advisory"→"ENFORCED" gate comments.
- **PRIV-01** (#291): the chronicle's only deterministic vice gate (`privacy_guard.VICE_KEYWORDS`) missed **"edible/edibles"** (already in `content_filter.json`) → added + a **superset drift-guard** test (the gate can never again be a subset of the configured filter). `privacy_guard` is a layer module but bundled into every asset → shipped via the Email bundle, **no layer dance**.

## TIER 1
- **DEVOPS-01 + CQ-01** (#292, MERGED): CI push-`paths` excluded `cdk/`, `ci/`, `config/`, workflows, tooling → those changes ran **NO pipeline** (IAM/alarm/layer-version un-gated) AND the auto-merge ALLOWLIST's premised on-main re-run never fired for its own files. Added the paths + fixed the automerge comment + unified `requirements-dev.txt` black/ruff/playwright to the CI pins + `tests/test_ci_pin_consistency.py`.
- **SEC-01** (#293, MERGED + DEPLOYED): public `site_api` role had **unconditioned PutItem/UpdateItem on the whole table** → scoped (`LeadingKeys`) to the 6 real interactive partitions (`VOTES#*`/`EXPERIMENT_FOLLOWS`/`CHALLENGE_FOLLOWS`/`RATE#*`/`…experiment_suggestions`/`…challenges`), enumerated exhaustively from `site_api_social.py` + `rate_limiter.py` (findings write to S3, not DDB) + a write-call-site canary test. **Verified via `aws iam simulate-principal-policy`** (zero data pollution): real partitions `allowed`, `…SOURCE#whoop`/`labs` now `implicitDeny`.
- **REL-01** (#296, OPEN + DEPLOYED): the 4 silent-failure detectors each had only a "≥1 problem" alarm with `treat_missing=NB` — blind to their OWN producer dying. Added a `_heartbeat_alarm` companion per detector = **BREACHING when the daily gauge is absent 2 consecutive days** (`SampleCount<1`, `evaluation=datapoints=2`; mirrors `panelcast-no-episode-7d`; 2 days dodges the in-progress-UTC-period false fire that's why the problem alarms can't just flip to BREACHING at eval=1). +4 digest alarms (52→56); problem alarms untouched. **All 4 live + `breaching`** (INSUFFICIENT_DATA until they accrue 2 days).
- **⚠️ DEVOPS-02 — DEFERRED (deliberate).** Tighten the OIDC trust subject `repo:org/repo:*` → `ref:refs/heads/main` / `environment:production`, and split the read-only-diff (plan/QA) role from the write (deploy) role. **Why held:** `deploy/setup_github_oidc.sh` rewrites the LIVE IAM trust policy that gates **all** CI/CD — a wrong condition locks GitHub Actions out of AWS entirely (no deploys, no CI rollback), and validating it means watching a real CI run assume the tightened role. Not a tail-of-session change. P3, `matthew-admin`-bounded today. **Plan:** dedicated session → edit the script's trust `StringLike`, apply, then push a trivial commit and confirm the CI/CD run still assumes the role before trusting it; keep the old policy handy for instant revert.

## THE CI-MASKING CASCADE (a real finding, not just process)
Merging the audit's CI-integrity work triggered fresh pipeline runs that exposed **two pre-existing red-mains** that had been masked for days (CI's Lint job runs gates sequentially — a red `black` skips everything downstream):
- **#294** (MERGED): `tests/test_editorial_image.py` unformatted since #280 (SS-11) → black red since then.
- **#295** (OPEN): once black was green, Unit Tests ran → `test_iam_secrets_consistency` + `test_secret_references` failed because **`life-platform/pexels`** (created 2026-06-29 for editorial imagery, referenced in IAM) was never in their `KNOWN_SECRETS`. Registered it (secret verified to exist in AWS) + bumped `test_s4` EXPECTED_COUNT 20→21.
- Ran the **full suite + all lint gates locally, creds-blanked** → after #295 there are no more layers; main goes green on merge. Lesson reinforced: after greening one gate, run the whole suite locally to surface the next masked layer at once.

## DEPLOY-FROM-BRANCH TRAP (new memory)
`cdk deploy` / `deploy/*.sh` package the **working tree**, not `origin/main`. I first ran Compute/Email while the worktree sat on the `priv01` feature branch → shipped only that PR's code, **missing** the pacific-date fixes. **The tell: `cdk diff LifePlatformMcp` showed 0 differences when I expected the nutrition change.** Recovered by `git checkout origin/main` + `grep`-verifying every fix present + redeploying. → memory `reference_deploy_from_main_not_worktree_branch`.

## OUTSTANDING
1. **Merge #295 (first) then #296** → main green + `main == live`.
2. **DEVOPS-02** (OIDC) — its own careful session (plan above).
3. **Doc-truth batch** (CQ-02 ARCHITECTURE.md layer/ADR/module + CQ-03 CLAUDE.md counts + PRIV-03 DATA_GOVERNANCE + the stale Secrets Manager table) — the deferred doc-drift-behind-a-fresh-façade theme, as one focused pass.
4. From the pre-audit backlog: SS-10 coach-grounding, PRE-13 data-publication decision, the gated reading Phase-E.

---

# HANDOVER — The Mind Pillar (Reading): cover-route fix + persona reconciliation (Dr. Cora Vance) — 2026-06-30

> **🎉 THE READING PILLAR IS NOW COHERENT END-TO-END AND `main == live`.** Two things shipped this
> session, both merged + deployed + verified; **0 open PRs, zero drift.** The reading pillar A–E work that
> was deployed-but-not-on-main last session is now reconciled (PR #286 merged), the broken book covers are
> fixed, and the placeholder reading-coach archetype is recast to a real named persona.
>
> **1. Broken book covers (real bug — FIXED + DEPLOYED + visually verified).** Matthew saw broken-image
> icons in his queue. Root cause: the `reading-cover-pipeline` writes real JPEGs to
> `generated/covers/<bookId>.jpg` and the `/mind/` front-end requests `/covers/<bookId>.jpg`, but **no
> CloudFront behavior routed `/covers/*` to `S3GeneratedOrigin`** — every cover fell through to the site
> origin and 404'd. Phase C shipped the page + pipeline but missed the one edge route. Fix: a `/covers/*`
> cache behavior in `cdk/stacks/web_stack.py` (mirrors `/assets/images/editorial/*`, 30-day TTL); the S3
> objects already existed. `cdk diff` clean (one behavior, no IAM/destroy) → `cdk deploy LifePlatformWeb`
> + invalidate `/covers/*`. **All 6 covers now serve `200 image/jpeg`**, confirmed by curl AND a Playwright
> `/mind/` screenshot (shelf renders Dark Matter + 5 queued covers crisp). **Durable lesson:** any new
> generated-content URL path needs its own CloudFront behavior (the ADR-046 prefix-stripping pattern) — a
> file in `generated/` is invisible at the edge until a behavior routes its viewer path. (PR #286.)
>
> **2. Persona reconciliation → Dr. Cora Vance (DONE + DEPLOYED).** The reading coach is now **Dr. Cora
> Vance** (`cora_vance`), recast from the placeholder "Lena Marsh". Registered in `config/personas.json` +
> `config/board_of_directors.json` as `type: board`, **`operational: false`**, **`active: false`**,
> **features-gated to nothing** → a defined-but-dormant persona that generates zero email/chronicle content
> until the reading-coaching surface ships (exactly how Elena Voss / Dr. Eli Marsh sit inert). All 13
> `tests/test_persona_registry.py` invariants stay green — incl. the gate that a non-operational persona
> gets **no `config/coaches/*.json` voice file** (that set matches operational coaches only). Counter-voices
> recast to the **real roster** (`READING_CALIBRATION.md` §9): Coach Maya Rodriguez (on-ramp), Dr. Amara
> Patel (longevity-vs-pleasure), Mara Chen (restraint gate). Orphan archetypes **Priya/Nadia/Crowe/Theo
> dropped** (only ever in the NOTE); Priya's pleasure-stance folded into Cora's own mandate.
>
> **⚠️ The rename touched LIVE code, not just docs** (my first `git grep` check missed it — a repo-wide
> plain `grep` caught it): the onboarding LLM **system prompt** ("You are Dr. Cora Vance",
> `reading_onboarding.py`), the `/mind/` empty-state string, the MCP **tool description** (`registry.py`),
> and track-record docstrings. Renamed + deployed: `cdk deploy LifePlatformMcp` (clean code re-hash — no
> IAM/layer; onboarding prompt + tool desc are bundled there) + `sync_site_to_s3.sh`. **NB — DO NOT TOUCH
> the separate, pre-existing Product-Board "Lena/Priya" personas** (in `docs/reviews/*`, product-board
> specs, `daily_insight`/`chronicle` lambdas, `challenges_catalog.json`): they're a different cast, and
> renaming the reading coach to Cora actually *disambiguates* from them. Dated build briefs
> (`BRIEF_2026-06-29…`, `CLAUDE_CODE_PROMPT_READING_MIND…`) keep their original names behind a
> reconciliation pointer (historical record). (PR #287.)
>
> **Process notes:** PR #286 was squash-merged mid-session → the post-squash drift guard (clobber guard in
> `sync_site_to_s3.sh`) correctly **blocked** the site sync because origin/main had a `site/` commit the
> branch lacked; reconciled by branching fresh off `main` and cherry-picking just the persona delta into
> #287 (the documented net-delta pattern). Also **deleted the stale `feat/site-polish-reading-layer`
> branch** — it had forked from main long ago (a merge would have reverted ~9,600 lines of coherence/SS/
> serial work) and its 2 commits were already shipped via PR #232; verified superseded, then removed.
>
> **Outstanding:** only the **gated Phase-E backlog** (journal-resonance embeddings, mind-body bridge,
> voice debrief, mnemonic medium, Third-Wall debrief render) — deliberately earned on real reading data
> (Matthew has 6 books, no finishes yet), so it waits. The reading pillar is otherwise complete: real
> covers, a real named coach, `main == live`. Prior session below.

---

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
`docs/coaching/READING_CALIBRATION.md`, `docs/specs/SPEC_READING_MIND_2026-06-29.md`,
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
