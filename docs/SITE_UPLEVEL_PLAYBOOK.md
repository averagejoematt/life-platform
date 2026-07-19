# Site Uplevel Playbook

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-03

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
  Build the URL list from the registry (`scripts/v4_build_evidence.py` PILLARS/REGISTRY) + the static
  routes so nothing is missed (~56 pages).
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
- **The 3 narrative lambdas (chronicle/podcast/ai-expert) are CDK-asset-bundled** — they import
  non-layer siblings. A single-file `deploy_lambda.sh` strips them and breaks the function. Ship
  code-only changes by zipping `lambdas/` with `_ASSET_EXCLUDES` (from `cdk/stacks/lambda_helpers.py`)
  and `update-function-code` directly — avoids a drift-risky full `cdk deploy`.
- **Matthew runs prod deploys.** This is a standing boundary; explicit in-session authorization
  ("you run it this time") unblocks it. (Memory: `feedback_prod_deploy_authorization`.)
- **Work in a git worktree** — Matthew runs concurrent sessions on one repo (memory:
  `feedback_concurrent_session_worktree`).
- **Build scripts generate committed HTML.** `sync_site_to_s3.sh` re-runs the generator suite
  per deploy (8 `v4_build_*.py` scripts as of 2026-07-10 — see `docs/SITE_AUTHORING.md` §3 for the
  inventory). After editing a generator, run it and commit its output — never hand-edit generated pages.
- **The pre-commit hook auto-bumps doc dates** (`sync_doc_metadata.py`) — cosmetic, expect it.
- **Assets are hashed across the FULL module graph, not just HTML** (ADR-098). `deploy/hash_site_assets.py`
  hashes every CSS/JS file leaves-first and rewrites HTML refs, intra-module `import`s, and CSS. If you
  ever get a "frozen page" report (static shell renders, JS-populated content blank, hard-reload fixes it,
  reproduces after a browser restart), the tell is a **stale intra-module import / dynamic `import()` path** —
  an ES module graph fails atomically when one dependency is a cache-skewed version. Don't reach for the SW
  or an HTML ref first. (Memory: `reference_asset_hashing_full_graph`; INCIDENT_LOG 2026-07-03.)

## Verification checklist (per change)
- Python: `py_compile` + `black --check --line-length 140` (the format gate **reds main** otherwise) + `flake8`.
- JS: full-parse via `node scripts/import_site_js_graph.mjs` (#1432 — `node --check` alone can MISS a
  real SyntaxError buried in a function body, see the gotcha above) + the unit tests, `node --test`
  (#1431 — see "JS unit-test harness" below). CSS: brace-balance.
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
  is a poor unit-test target — that's what `tests/visual_qa.py` / `tests/pr_render_gate.py`
  (a real Playwright browser) already cover; don't reach for a DOM shim to force it into
  `node:test`. If a module mixes the two, consider splitting the pure logic out (as
  `evidence_router.js` did) rather than shimming a fake DOM.
- **CI gate:** `.github/workflows/v4-gate.yml`'s `site-gate` job runs `node --test` right after
  the #1432 import-graph gate, on every `site/**`-touching PR and push to main.

## Deploy surface (when authorized)
1. **Site** — `bash deploy/sync_site_to_s3.sh` (+ explicit `aws s3 sync site/assets/fonts/` if fonts changed). Content-hashes + invalidates + rolls the SW version.
2. **Site-API** — `bash deploy/deploy_site_api.sh [verify_path]` (ships the full `web/` package; never single-file).
3. **CloudFront redirects** — apply `deploy/generated/v4_redirects_function.js` to dist `E3S424OXQZ8NBE` (update-function → publish).
4. **Narrative lambdas** — the `lambdas/` asset zip method above.
5. Reconcile `main` — open a PR from the worktree branch so `main` matches what's live.

## Measurement pipeline — traffic digest (infra; Matthew runs the deploy)

The returnability instrument (`lambdas/operational/traffic_digest_lambda.py`): a weekly
email of page views / unique / returning visitors / top pages / referrers, parsed from
**CloudFront standard access logs**. Privacy-clean by construction — IPs are hashed in
memory for distinct/returning counts then discarded; output is aggregate only. The
privacy page documents this verbatim under "Cookies and tracking."

Two one-time infra steps (both require AWS perms beyond the site/API deploys — **hand to
Matthew**, do not run from the agent):

1. **CDK** — `cd cdk && npx cdk deploy LifePlatformOperational`. This creates:
   - the log bucket `matthew-life-platform-cf-logs` (BUCKET_OWNER_PREFERRED ACL so
     CloudFront can write; 90-day lifecycle; `RETAIN` on stack delete), and
   - the `life-platform-traffic-digest` Lambda on `cron(0 16 ? * MON *)` (9 AM PT Mondays),
     env `LOG_BUCKET`/`LOG_PREFIX=cf/`. No error alarm by design (a weekly digest
     failing is low-stakes — same as the other `alerts_topic=None` operational Lambdas).
   Run `npx cdk diff LifePlatformOperational` first — expect **no IAM changes to existing
   roles**, one new role + bucket + function.
2. **Enable CloudFront logging** — point dist `E3S424OXQZ8NBE`'s standard logging at the
   new bucket, prefix `cf/`:
   ```bash
   aws cloudfront get-distribution-config --id E3S424OXQZ8NBE > /tmp/cf.json   # capture ETag
   # set Logging: { Enabled:true, IncludeCookies:false,
   #   Bucket:"matthew-life-platform-cf-logs.s3.amazonaws.com", Prefix:"cf/" }
   aws cloudfront update-distribution --id E3S424OXQZ8NBE \
     --distribution-config file:///tmp/cf-config.json --if-match <ETag>
   ```
   Logs begin landing within ~an hour. The first digest fires the following Monday (it
   self-skips and sends nothing if the window is empty).

Verify after a few days of logs exist: `aws lambda invoke --function-name
life-platform-traffic-digest /tmp/out.json` → a digest email arrives (or a logged
"no traffic" no-op). Unit cores: `tests/test_traffic_digest.py`.
