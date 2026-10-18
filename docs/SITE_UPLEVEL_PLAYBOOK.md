# Site Uplevel Playbook

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-18 (#4580 / #4588 — the front-page cut-over section carried onto main from the rehearsal's docs commit `2d749c6d4`, extended with the 2026-10-18 rulings: the Thursday 2026-10-22 go, the reference-copy step, the appendix-as-footnote reach rule and the static `og:image`. Prior verify 2026-10-17: the deploy surface and JS harness sections re-read against the tree.)

> **How to redesign or uplevel the site well** — the method and the hard-won lessons, so the
> next Claude inherits the playbook, not just the state. Start from
> [PLATFORM_NORTH_STAR.md](PLATFORM_NORTH_STAR.md) + [SITE_MAP_AND_INTENT.md](SITE_MAP_AND_INTENT.md);
> build to [DESIGN_SYSTEM_V5.md](DESIGN_SYSTEM_V5.md) — including its **§10 mobile / responsive
> layer** (breakpoint tokens, the `@layer` app-bar, touch grammar, the 44px tap floor, the table
> primitive), which a site PR must satisfy and the pre-merge render gate enforces at 390 + 360.

## The loop (run it every time)

**Understand → change one coherent slice → VERIFY against rendered screenshots → deploy → re-verify live.**
Never skip the render check. The single biggest lesson of the v5 work: *working blind produces
plausible-but-wrong results.* The home weight chart was rendering empty for days — caught the
moment someone actually looked at it.

### 1. Render-QA sweep (before AND after)
- Screenshot **every page at desktop (1280) + mobile (390)**, full-page, with Playwright (chromium).
  Build the URL list from the page registry (`python3 qa/qa_manifest.py --emit paths`, which derives
  from `scripts/v4_build_evidence.py` PILLARS/REGISTRY + the static routes) so nothing is missed.
- **Scroll each page through** before screenshotting so lazy/reveal content renders.
- Triage for **objective bugs only**: broken/empty/flat charts, text overflow/clipping (esp. mobile),
  literal `undefined`/`null`/`NaN`/`[object Object]`/`{placeholder}`/walls-of-"—"/stuck loaders,
  font inconsistency, layout breakage, sections blank that should have data. Fan out parallel
  subagents over screenshot batches to keep it cheap.
- Known non-bug: the fixed mobile door-bar overlaps content in *full-page* screenshots — that's a
  capture artifact of `position:fixed`, not a real overlap.

### 2. Fix, then re-screenshot the fixed page to confirm. Don't trust the edit — trust the pixel.

### 3. Elevate (taste) — but surface taste calls to Matthew
- Motion/interaction/depth are high-leverage. **The bolder-identity / "fascination" calls are
  taste** — present options with example screenshots and let Matthew choose; don't swing the visual
  identity unilaterally. Restraint is the credibility moat (see north star).

## Hard-won gotchas (these cost real time)

- **Stored AI artifacts don't change at deploy.** The chronicle, podcast, and board verdict are
  *generated* content saved to S3/DynamoDB. Fixing the *prompt* changes future generations, not the
  copy already published. To make a fix visible now: regenerate it (board = invoke
  `ai-expert-analyzer`; chronicle/podcast are approval-gated + publish publicly, so confirm with
  Matthew or surgically de-fabricate the published file).
- **CloudFront: invalidate the VIEWER path, not the S3 key.** `generated/journal/*` is served at
  `/journal/*` (the `generated/` prefix is stripped at the edge). Invalidating `/generated/...` does nothing.
- **The narrative lambdas (chronicle/podcast/ai-expert) ship in the ONE code bundle** — the whole
  `lambdas/` tree staged by `deploy/build_bundle.py` (`docs/CONVENTIONS.md` §1), so there is no
  single-file strip hazard any more. Ship code-only changes with `bash deploy/deploy_fleet.sh` (the
  one fleet path; `deploy_lambda.sh` is the laptop hot-fix path) — not a hand-zipped `_ASSET_EXCLUDES`
  upload (that list was retired from CDK; `build_bundle.py` carries the one copy).
- **Matthew runs prod deploys of Lambdas and infrastructure.** This is a standing boundary; explicit
  in-session authorization ("you run it this time") unblocks it. (Memory: `feedback_prod_deploy_authorization`.)
  **The site is the exception:** a merge to `main` touching `site/**` deploys it automatically
  (`.github/workflows/site-deploy.yml`, `docs/CONVENTIONS.md` §2), and a red site-deploy is silent — read
  the newest run's conclusion (the SessionStart pre-flight prints it) before and after a site merge.
- **Work in a git worktree** — Matthew runs concurrent sessions on one repo (memory:
  `feedback_concurrent_session_worktree`).
- **Build scripts generate committed HTML.** `sync_site_to_s3.sh` re-runs the generator suite
  per deploy (the set is the `run_site_generator` steps in that script — see `docs/SITE_AUTHORING.md` §3 for the
  inventory; a generator-only change does not trigger `site-deploy.yml`, so dispatch it). After editing a generator, run it and commit its output — never hand-edit generated pages.
- **The pre-commit hook auto-bumps doc dates** (`sync_doc_metadata.py`) — cosmetic, expect it.
- **Assets are hashed across the FULL module graph, not just HTML** (ADR-098). `deploy/hash_site_assets.py`
  hashes every CSS/JS file leaves-first and rewrites HTML refs, intra-module `import`s, and CSS. If you
  ever get a "frozen page" report (static shell renders, JS-populated content blank, hard-reload fixes it,
  reproduces after a browser restart), the tell is a **stale intra-module import / dynamic `import()` path** —
  an ES module graph fails atomically when one dependency is a cache-skewed version. Don't reach for the SW
  or an HTML ref first. (Memory: `reference_asset_hashing_full_graph`; INCIDENT_LOG 2026-07-03.)
  The hasher also counts an `/assets/...` path inside a **comment** as a dependency edge — a
  prose back-reference can hard-fail the deploy as a false import cycle; keep asset paths out
  of comments, or break them.
- **"The data is fixed" is not "the reader can see it" — check the renderer's filters.** 23
  withdrawn citations were live in `/api/supplements` and structurally invisible on the page,
  because a withdrawn source carries no `url` by design and `renderSupplements` filtered on
  `x.url`. Both halves were individually correct. After any data-level correction, render the
  surface (headless is enough) and `curl` the page for the correction's own words.
- **An `fs-ok: floored by svgtype.js` sanction is a claim the token guard cannot check.** The
  floor only engages when the selector is in `SVG_TYPE_FLOORS` (`site/assets/js/svgtype.js`)
  AND the CSS consumes its `--fs-*` cssVar AND the token's base is in `tokens.css`; a static
  `font-size: 11px` under that comment measured 5.1px effective at 390px. Verify with
  render-QA at 390px (computed size × `getScreenCTM().a` ≥ 11), and give floored SVGs a
  `min-width` inside an `overflow-x:auto` wrap so glyphs that grow scroll instead of clipping.
- **Verify generated PNGs, not just live pages.** Every OG/social card rendered `.notdef` tofu
  for months because the bundled card font was a subset with no basic-Latin glyphs — and
  visual-QA inspects pages, never the cards, which only surface when a link is shared. After
  touching `lambdas/web/card_engine.py` or a bundled font, open the generated PNGs.

## Verification checklist (per change)
- Python: `py_compile` + `black --check --line-length 140` (the format gate **reds main** otherwise) + `flake8`.
- JS: full-parse via `node scripts/import_site_js_graph.mjs` (#1432 — `node --check` alone can MISS a
  real SyntaxError buried in a function body, see the gotcha above) + the unit tests, `node --test`
  (#1431 — see "JS unit-test harness" below). CSS: brace-balance.
- CSS, additionally: `python3 -m pytest tests/test_css_tokens.py` on ANY `site/**/*.css` diff —
  the gating visual-QA passes a raw `font-size` (the pixels are fine) and then the Unit Tests
  job reds `main`. Use a `--fs-*` token or an inline `/* fs-ok: <reason> */` sanction.
- Render: screenshot the changed page (desktop + mobile); confirm no content stuck hidden, no overflow.
- Tests: the relevant subset **creds-blanked** (some pass locally on ambient creds but fail in CI on
  `NoCredentialsError`). Memory: `reference_ci_masking_and_creds`.
- Live: `bash deploy/smoke_test_site.sh`; `curl /version.json` == git HEAD.

## JS unit-test harness (#1431)

The site ships zero JS dependencies (CLAUDE.md "No framework/deps") — the test harness respects
that by staying **dev-only**: a `package.json` at repo root (never referenced by anything that
ships) names Node's **built-in `node:test` runner**, zero npm packages installed. Run the whole
suite with `node --test` from the repo root (auto-discovers everything under `tests/js/`), or
`npm run test:js`.

- **Where tests live:** `tests/js/<module>.test.mjs`, one file per `site/assets/js/*.js` module
  under test. `tests/js/support/loader.mjs` is a shared side-effect import that registers
  `scripts/site_js_loader.mjs` (the same module-resolution hook the #1432 import-graph gate uses)
  so a test file can `import` a site module by its real root-relative-import path, unmodified.
- **Static vs. dynamic import:** if the module under test has a top-level `import "/assets/js/…"`
  of its own (e.g. `charts.js` imports `svgtype.js`), import it **dynamically** —
  `const { fn } = await import("../../site/assets/js/foo.js");` — AFTER the static
  `import "./support/loader.mjs";` line. Node resolves an entire *static* import graph before
  evaluating any of it, so a static import of a module with its own root-relative import would try
  to resolve before the loader hook has registered. `tests/js/charts.test.mjs` has the worked
  example + the full comment.
- **What's covered so far (the first tranche, #1431):** `charts.js`'s pure chart functions
  (scales/paths/formatting, including the >=4-points-to-draw-a-trend honesty rule), the
  `evidence.js` router mapping (split into `site/assets/js/evidence_router.js` specifically so
  it's testable without triggering evidence.js's DOM-wiring side effects at import time — no
  behavior change, same pattern `evidence_shared.js` used at #581), and the shared formatters in
  `evidence_shared.js`.
- **Adding tests for the next module:** prefer testing a module's **pure functions** (data in,
  string/value out — most of `charts.js`, `evidence_shared.js`, and any future `evidence_*.js`
  renderer fit this). A module that's mostly DOM wiring (event listeners, `querySelector` chains)
  is a poor unit-test target — that's what `qa/visual_qa.py` / `qa/pr_render_gate.py`
  (a real Playwright browser) already cover; don't reach for a DOM shim to force it into
  `node:test`. If a module mixes the two, consider splitting the pure logic out (as
  `evidence_router.js` did) rather than shimming a fake DOM.
- **CI gate:** `.github/workflows/v4-gate.yml`'s `site-gate` job runs `node --test` right after
  the #1432 import-graph gate, on every `site/**`-touching PR and push to main.

## Deploy surface
1. **Site** — automatic on merge to `main` (`site-deploy.yml`: sync + explicit fonts sync + smoke ∥ visual/AI-QA, auto-rollback on a red; `docs/SITE_AUTHORING.md` §7). Attended fallback, when authorized and always from `main`: `bash deploy/sync_site_to_s3.sh` (+ explicit `aws s3 sync site/assets/fonts/` if fonts changed). Content-hashes + invalidates + rolls the SW version.
2. **Site-API** — `bash deploy/deploy_site_api.sh [verify_path]` (ships the full `web/` package; never single-file).
3. **CloudFront redirects** — apply `deploy/generated/v4_redirects_function.js` to dist `E3S424OXQZ8NBE` (update-function → publish).
4. **Narrative lambdas** — `bash deploy/deploy_fleet.sh` (the one-bundle path above).
5. Reconcile `main` — open a PR from the worktree branch so `main` matches what's live.

## The front-page cut-over (#4588, epic #4580)

The living front page goes live as **one commit**: the four kit pages of epic #4580 (front page,
Start here, Story, Coaches) copied from `/next/v8/` to `/`, `/start/`, `/story/` and `/coaches/`.
Their deep links stay on `/next/v8/` (`data-ck-base`); the other eight kit pages keep their
`/next/v8/` paths until a later cut-over (the door table is `SITE_MAP_AND_INTENT.md`). No page is
renamed, and no redirect is added. Every other page stays as it is. The rehearsal is the HELD draft
PR #4928 on #4588.

**When it merges — the Thursday rule and the freeze.** Only on the owner's go, recorded on #4588
(given 2026-10-18 for **Thursday 2026-10-22, morning PT**, provided five readers are recorded on
#4587 by Wednesday noon and the rebuilt rehearsal is green). A cut-over merges on a **Thursday**,
never inside the **Tuesday-evening to Wednesday-noon PT merge freeze** around the weekly chapter and
email: the chapter and podcast publish into that window, and a site deploy that auto-rolls back there
reverts the chapter's page with it. Thursday leaves the week's publish behind it and three weekdays
ahead to watch the live page. If a Thursday is missed, the next Thursday — never a Friday.

- **Every existing URL still resolves.** `tests/test_v4_redirects_function.py::test_every_existing_url_still_resolves_4588`
  checks this offline. Every site/ page, every sitemap URL and every old URL the edge 301s must end on a served
  file, and no page under site/ may sit behind a 301. `/start/` (301 to `/`) and `/coaches/` (301 to
  `/method/board/`) were 301 sources, so the cut-over drops those two 301s in
  `scripts/v4_migration_inventory.py::SCAN_SKIP_URLS`. It then regenerates `redirects.map` and
  `deploy/generated/v4_redirects_function.js`. Both URLs keep answering 200, now with the new page. The edge
  function is published by hand (Deploy surface, step 3). Until it is, the two new pages are unreachable and
  the two old 301s still answer.
- **The replaced layout is kept as a reference page (owner ruling 2026-10-18, standing for every
  cut-over).** Before the four files are overwritten, the cut-over commit copies each layout it
  replaces — the v5 home first — to a served, `noindex`, out-of-navigation reference page with the
  last live sha in its head comment (`<!-- reference copy of / at <sha>, replaced 2026-10-22 -->`),
  and adds it to the footnote appendix (`/next/v8/appendix/`). The path convention is
  `/reference/<date>-<slug>/` (`/reference/2026-10-22-home-v5/`), never under `/legacy/`, which is
  never linked from the UI. Nothing is deleted: the ~87 pages the kit does not replace stay served
  at their URLs and listed in the appendix.
- **The appendix is a footnote, not navigation (owner ruling 2026-10-18).** The kit footer links
  `/next/v8/appendix/`, which lists every off-path page, so a naive walk from `/` reaches ~87 pages.
  `tests/test_site_nav_reach_ratchet.py` counts with the appendix excluded; `NAV_REACH_CEILING`
  (`ledgers/site_vocabulary_residue.py`, 24 today) is lowered to what the rebuilt rehearsal
  measures, never raised. The pages the appendix lists carry no nav weight.
- **`og:image` is a static wordmark card** until the daily mark is ruled (#4586's `ck-mark`); the
  front page ships no data-driven unfurl image before then. A shared link must still unfurl — the
  rehearsal's "no `og:` tags" gap closes on the wordmark card, not on the mark.
- **The deploy builders leave a kit page alone.** `v4_build_home_proof.py` would otherwise exit 2
  (no proof anchor), and that blocks the sync. `v4_build_dispatches.py` would otherwise overwrite `/story/`
  with the v4 hub and silently undo the cut-over on its first deploy. Both now ask
  `v4_apply_chrome.is_kit_page()` first.
- **The rollback** reverts the one squash commit, deploys the site, then re-publishes the edge function:
  ```bash
  git fetch origin && git switch -c revert-4588-cutover origin/main
  git revert --no-edit <the cut-over's squash sha on main>   # restores every live file byte-identical
  git push -u origin revert-4588-cutover && gh pr create --fill   # merged by the driver; site-deploy runs on merge
  gh workflow run site-deploy.yml --ref main                   # or dispatch it by hand once the revert is on main
  # then re-publish deploy/generated/v4_redirects_function.js to E3S424OXQZ8NBE (Deploy surface, step 3)
  ```
  The quickest path to the old site is `bash deploy/rollback_site.sh <pre-cut-over sha>`. It restores
  site/ only. The revert above is the full rollback. Rehearsed 2026-10-15 on the lane: the revert of
  the cut-over commit left `git diff --stat` against the pre-cut-over tree empty.
- **If the AI visual check is paused by the budget tier, the cut-over waits.** `visual_ai_qa` sits in
  `budget_guard`'s operator-truth band (cutoff 3). It runs at tiers 0–2 and stops only at tier 3. There it
  prints SKIPPED-BY-BUDGET and the visual-QA job stays green on the Playwright sweep alone (CONVENTIONS
  §4b; the "cutoff tier 1" in §4b's budget bullet predates ADR-125's 2026-08-03 amendment). The cut-over
  does not ship on that Playwright-only gate, for three reasons:
  1. The four pages' Playwright checks in `qa/qa_manifest.py` are structural by construction. They assert
     elements in the static shell, so a green says nothing about whether the dated edition rendered.
  2. A tier-3 month is also when the edition's AI-written lines are paused. The front page would open in
     its degraded state.
  3. A missed Thursday costs one week, and the go on #4588 carries to the next Thursday.
  So read SSM `/life-platform/budget-tier` before the merge. At tier 3, hold to the next Thursday.
- **Live proof** (the box #4588 closes on, never the merge): on the Thursday,
  `curl -s https://averagejoematt.com/ | grep -c 'data-ck-page="front"'` → 1, and `/start/`, `/story/`
  and `/coaches/` each answering 200 with their kit page; `/reference/2026-10-22-home-v5/` answering
  200 with `noindex`; the site-deploy run green and not auto-rolled back.

## Measurement pipeline — traffic digest (infra; Matthew runs the deploy)

The returnability instrument (`lambdas/operational/traffic_digest_lambda.py`): a weekly
email of page views / unique / returning visitors / top pages / referrers, parsed from
**CloudFront standard access logs**. Privacy-clean by construction — IPs are hashed in
memory for distinct/returning counts then discarded; output is aggregate only. The
privacy page documents this verbatim under "Cookies and tracking."

One-time infra (step 2 below is already CDK-declared; both require AWS perms beyond the site/API deploys — **hand to
Matthew**, do not run from the agent). It is the weekly Monday ops-pack email (#2835): the same
digest also carries the folded data-reconciliation and pip-audit artifacts.

1. **CDK** — `bash deploy/cdk_deploy.sh LifePlatformOperational` (the drift-guarded path, `docs/CONVENTIONS.md` §6). This creates:
   - the log bucket `matthew-life-platform-cf-logs` (BUCKET_OWNER_PREFERRED ACL so
     CloudFront can write; 90-day lifecycle; `RETAIN` on stack delete), and
   - the `life-platform-traffic-digest` Lambda on `cron(0 16 ? * MON *)` (9 AM PT Mondays),
     env `LOG_BUCKET`/`LOG_PREFIX=cf/`. No error alarm by design (a weekly digest
     failing is low-stakes — same as the other `alerts_topic=None` operational Lambdas).
   Run `npx cdk diff LifePlatformOperational` first — expect **no IAM changes to existing
   roles**, one new role + bucket + function.
2. **CloudFront logging — done, now CDK-declared.** The standard-logging block (bucket
   `matthew-life-platform-cf-logs.s3.amazonaws.com`, prefix `cf/`, cookies off) is part of the
   distribution in `cdk/stacks/web_stack.py` (`LoggingProperty`, ADR-099 #349), so a redeploy preserves
   it; the old `get-distribution-config` / `update-distribution` hand step is retired. (Read-only check
   2026-10-17: dist `E3S424OXQZ8NBE` reports `Logging.Enabled: true`, prefix `cf/`.) The first digest
   fires the Monday after logs land; it self-skips and sends nothing if the window is empty.

Verify after a few days of logs exist: `aws lambda invoke --function-name
life-platform-traffic-digest /tmp/out.json` → a digest email arrives (or a logged
"no traffic" no-op). Unit cores: `tests/test_traffic_digest.py`.
