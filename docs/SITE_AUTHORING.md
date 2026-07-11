# Site Authoring — add or change a page on averagejoematt.com

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-10
> **Sources of truth:** `site/` tree, `scripts/v4_build_*.py`, `site/sw.js`, `.github/workflows/site-deploy.yml`

The end-to-end guide for changing the public site: where a page belongs, what a page is
made of, which pages are generator output, how the cache/hashing layer works, and how a
change ships. Design standards live in [DESIGN_SYSTEM_V5.md](DESIGN_SYSTEM_V5.md); the
change-method (render-sweep → fix → verify) lives in
[SITE_UPLEVEL_PLAYBOOK.md](SITE_UPLEVEL_PLAYBOOK.md) — this doc does not restate them.

---

## 1. The IA — where a new page belongs

The site (ADR-071, "The Measured Life") is a static S3 + CloudFront site (distribution
`E3S424OXQZ8NBE`), no framework, no build toolchain beyond the Python helper scripts.

Top nav = **Home + 5 doors** (DESIGN_SYSTEM_V5.md §2):

| Door | Route | What goes there |
|---|---|---|
| Home | `/` | The front door — teaches the loop, routes in |
| The Cockpit | `/now/` | Today's live slice (the daily instrument; noindex) |
| The Data | `/data/` | Every source, now & over time (was `/evidence/`) |
| The Coaching | `/coaching/` | The AI team — profiles, stances, board |
| The Protocols | `/protocols/` | Supplements · experiments · challenges · discoveries |
| The Story | `/story/` | Chronicle · journal · timeline · about |

**Footer-tier** (no top-nav door): `/method/` — the under-the-hood pages (methodology,
cost, pipeline, calibration, …), reachable from About + the global footer. `/legacy/` is
the frozen pre-v4 site — never edit it, never link it from the UI.

> You may still see "three doors" in older docs — that's the original v4 cut
> (`/now/ /story/ /evidence/`); the v5 split above is current.

**Before adding a page, read [SITE_MAP_AND_INTENT.md](SITE_MAP_AND_INTENT.md)** — the
intent registry for every existing page (what it must deliver, its endpoints, its
files). A new page gets an entry there; if the page's purpose doesn't fit any door,
that's a design conversation, not a new top-level directory.

Routing is directory-style: a page is `site/<path>/index.html`, served at `/<path>/`.

## 2. Anatomy of a page

The stack (all self-hosted, zero external requests):

- **`site/assets/css/tokens.css`** — the design-token system (colors, type triad,
  spacing, the shared kit incl. `.prose` — DESIGN_SYSTEM_V5.md §3). Every page loads
  `fonts.css` + `tokens.css` + one page/door stylesheet.
- **Self-hosted fonts** — `site/assets/fonts/`, preloaded `woff2` (CSP is
  `font-src 'self'`). Note fonts have a *separate* deploy step (§7).
- **Vanilla-JS ES modules** — `site/assets/js/*.js` (`cockpit.js`, `evidence.js`,
  `charts.js`, `theme.js`, `motion.js`, …). No framework, no npm, no bundler.
- **Inline-SVG charts** — rendered by `site/assets/js/charts.js` (and the
  `evidence_*.js` modules) into the page; no chart library. Icons come from the
  `site/assets/icons/icons.svg` sprite via `<use href="…#i-…">` (never emoji —
  DESIGN_SYSTEM_V5.md §8).
- **`.prose`** — the wrapper class for all injected/long-form HTML (DESIGN_SYSTEM_V5.md §3).

A real minimal skeleton — lifted from **`site/privacy/index.html`** (the simplest
hand-authored page; head trimmed, body classes verbatim):

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Privacy Policy — averagejoematt</title>
  <meta name="theme-color" media="(prefers-color-scheme: light)" content="#F4EFE4">
  <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0E0C08">
  <link rel="icon" href="/favicon.ico">
  <link rel="stylesheet" href="/assets/css/fonts.css">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  <link rel="canonical" href="https://averagejoematt.com/privacy/">
</head>
<body>
<header class="story-top">
  <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">privacy</span></a>
  <nav class="doors" aria-label="Doors">
      <a href="/now/" title="…">the cockpit</a>
      <a href="/data/" title="…">the data</a>
      <a href="/coaching/" title="…">the coaching</a>
      <a href="/protocols/" title="…">the protocols</a>
      <a href="/story/" title="…">the story</a>
    <a href="/subscribe/" class="nav-follow" aria-label="Follow the experiment">follow</a><button class="theme-toggle" type="button" aria-label="Toggle light and dark"><span class="theme-dot" aria-hidden="true"></span></button>
  </nav>
</header>
<main>
  <!-- page content -->
</main>
<footer class="dx-foot-bar"><span class="label">averagejoematt · privacy</span> <span class="label"><a href="/">← home</a></span></footer>
<script><!-- the inline no-flash theme + toggle snippet — copy it verbatim from site/privacy/index.html --></script>
</body>
```

(One caveat on that example: privacy's `<head>` also carries an "old-design token shim"
`<style>` block mapping pre-v4 token names — don't copy that into a new page; write new
pages against the current `tokens.css` names directly.)

For a richer page, crib from **`site/now/index.html`** (the hand-authored flagship): font
preloads, the no-flash theme script, the `.loop-ribbon` spine (whose one source of truth
for *generated* pages is `scripts/v4_kit.py`), skip-link, PWA meta, and an ES-module
entry (`<script type="module" src="/assets/js/cockpit.js">`).

## 3. Generated vs hand-authored

**The rule: if a page has a generator, change the generator and re-run it — never
hand-edit the output.** A hand edit renders fine today and silently reverts/drifts the
next time the generator runs (several run on *every* deploy — see the last column).
Generated files carry "GENERATED — never hand-edit" comments; the generators are:

| Generator (`scripts/`) | Output | Source data | Runs in every site sync? |
|---|---|---|---|
| `v4_build_evidence.py` | `/data/`, `/protocols/`, `/method/` app shells + per-slug shells (engine: `assets/js/evidence.js`, registry embedded as `window.__EVIDENCE_REGISTRY__`) | the PILLARS/REGISTRY in the script | No — run manually, commit output |
| `v4_build_methods.py` | `/method/registry/index.html` | `lambdas/methods_registry.py` (ADR-105) | Yes |
| `v4_build_coaching.py` | `/coaching/` + per-section shells (with the board's read baked into `<noscript>`) | section list in `assets/js/coaching.js`; live coaching read | Yes |
| `v4_build_dispatches.py` | `/story/` + per-section shells | section list in `assets/js/dispatches.js`; live chronicle state | Yes |
| `v4_build_gear.py` | `/gear/index.html` | `lambdas/source_registry.py::catalog_entries()` + the script's GEAR dict (coverage assert) | No — run manually, commit output |
| `v4_build_cockpit_proof.py` | the `<noscript>` proof block *inside* `site/now/index.html` (sentinel comments, idempotent injection — the page itself is hand-authored) | `/api/character` via `scripts/v4_proof.py` | Yes |
| `v4_build_data_sources.py` | `site/data/data_sources.json` | `lambdas/source_registry.py` (#498) | Yes |
| `v4_build_rss.py` | `site/rss.xml` | live published chronicle `posts.json` | Yes |
| `v4_build_sitemap.py` | `site/sitemap.xml` + a `<noscript>` post-link list injected into `/story/chronicle/index.html` | the real `site/` tree + live `posts.json` | Yes |
| `v4_build_portraits.py` | `site/assets/js/portrait_data.js` (only *signed* recipes bundle — ADR-106) | `config/portraits/*.json` | Yes — and a validation failure **blocks the sync** |
| `render_portraits.py` | `site/assets/portraits/*.png` | same recipes | Yes |
| `v4_migration_inventory.py` | `redirects.map` (§6) | the preserved `site/legacy/` tree | No |

("Yes" = wired into `deploy/sync_site_to_s3.sh` lines 56–89, so every deploy re-runs it;
your hand edit to those outputs dies at the next deploy. "No" = run it from repo root
after editing, commit the regenerated output in the same PR.)

**Hand-authored pages** (edit the HTML directly): `/` (`site/index.html`), `/now/`
(except the sentinel-marked proof block), `/privacy/`, `/subscribe/` (+ `subscribe.html`,
`/subscribe/confirm/`), `/journal/essays/*`, `404.html`, the redirect stub `/mind/`, and
all of `assets/css/` + `assets/js/` **except** the generated `assets/js/portrait_data.js`.
`/legacy/` is frozen verbatim — served with unhashed assets, never touched.

## 4. The module-graph hashing trap (why pages "freeze")

Read this before touching any `assets/js/` module. Full history:
`docs/INCIDENT_LOG.md` 2026-07-03 entry + ADR-098 in `docs/DECISIONS.md`.

**The mechanism.** `deploy/sync_site_to_s3.sh` content-hashes CSS/JS
(`base.css → base.a1b2c3d4.css`), serves hashed names immutable/1-year, HTML at
`max-age=300`. Pre-2026-07-03 it rewrote references **only in HTML** — the
`import … from "/assets/js/charts.js"` statements *inside* ES modules kept pointing at
the unhashed, 24h-cached URL. When a deploy changed an entry module and a dependency
together, a returning browser paired a fresh hashed entry with a stale cached
dependency; an ES module graph fails **atomically** on a mismatched import, so nothing
executed and only the static shell rendered — the "frozen page" (hard reload fixes it;
reproduces after a browser restart).

**The fix (ADR-098).** `deploy/hash_site_assets.py` hashes the **full module graph**
leaves-first and rewrites HTML refs, intra-module `import`s, and CSS — every asset URL
is content-hashed and immutable, so no version skew is possible. (`legacy/` is skipped.)

**What this means for you:**
- Never hardcode an asset URL anywhere the hasher doesn't rewrite (e.g. building an
  `import()` path from string concat at runtime) — that recreates the bug.
- If a frozen-page report ever comes in, the tell is a stale intra-module or dynamic
  `import()` path — check that before suspecting the service worker
  (SITE_UPLEVEL_PLAYBOOK.md, "Hard-won gotchas").

**The service worker (`site/sw.js`)** — actual strategy, from the file:
- `/api/*`, page navigations, and **all `*.json`** → network-first (falls back to cache,
  then the cached `/now/` shell when fully offline). JSON feeds are data, not immutable
  assets — cache-first here once hid a new chronicle post ("chronicle shows 2 not 3",
  2026-06-21, per the comment in `sw.js`).
- Hashed/static assets → cache-first (immutable filenames make that safe).
- Audio (`*.wav|mp3|m4a`) and cross-origin → never touched.
- **How a deploy rolls the cache:** `sw.js` ships with `const VERSION = "v1"`;
  `sync_site_to_s3.sh` rewrites `VERSION` to the build's short git SHA at deploy time,
  which renames both cache buckets — `activate` then deletes every cache not ending in
  the new VERSION. `sw.js` itself is served `max-age=300, must-revalidate` so browsers
  re-check it quickly.
- **The build fingerprint:** every deploy writes `/version.json` (`no-cache`) containing
  the merged short SHA + UTC time, and stamps `<meta name="build">` into every v4 page.
  `curl -s https://averagejoematt.com/version.json` == git HEAD is the "is my deploy
  live" check.

## 5. API contracts

- The front-end reads `/api/*` **read-only**. Endpoint inventory: [API.md](API.md)
  (two lambdas behind CloudFront: `life-platform-site-api` data + `site-api-ai`).
- **Shaped-empty 200 (ADR-073):** on sparse/genesis-week data, endpoints return `200`
  with the success contract's keys at empty/null values — never `503`. Front-end code
  must render an honest empty state for those shapes, not treat them as errors.
- **Never call engine writes from the front-end.** The only sanctioned POSTs are the
  existing interactive features (votes, follows, checkins, suggestions, subscribe, ask).
  A new page never adds a write path; if a feature seems to need one, that's a site-api
  design change (owner: `web/*.py`, see CLAUDE.md), not a `fetch(…, {method:"POST"})`.
- Changing an endpoint *and* the page that reads it has a deploy-ordering rule — §7.

## 6. Redirects (old URLs → v4)

Old-site URLs 301 at the edge via the CloudFront function **`v4-redirects`** (attached
viewer-request on the default behavior — `cdk/stacks/web_stack.py`, function ARN
`…function/v4-redirects`; it yields to the privacy-gate Lambda when `PRIVACY_MODE` is on).

The chain, when you move/rename a page:
1. `python3 scripts/v4_migration_inventory.py` — walks the preserved `site/legacy/` tree
   (plus the manual-301 list *inside the script* — add moved v4 URLs there, e.g. `/mind/`),
   classifies every old URL, writes **`redirects.map`** (tab-separated `old → new`);
   exits 1 on any unmapped URL, so it doubles as the coverage gate.
2. `deploy/v4_cutover.sh` step 2 generates
   **`deploy/generated/v4_redirects_function.js`** from `redirects.map`.
3. Apply: update + publish the `v4-redirects` CloudFront function with that artifact
   (SITE_UPLEVEL_PLAYBOOK.md "Deploy surface" #3 — this is a live-infra step; it is
   **not** part of the site sync, and deploys are Matthew's call).

## 7. Ship it

**The normal path is automatic (#750):** merge to `main` touching `site/**` →
`.github/workflows/site-deploy.yml` runs, with no approval gate:

1. **Superseded-run check** — skips cleanly if a newer `site/` merge already queued.
2. **Deploy** — `deploy/deploy_site.sh` → `deploy/sync_site_to_s3.sh`: clobber guard
   (refuses to sync a checkout missing origin/main `site/` commits), regenerates the
   §3 "Yes" artifacts, **PII surface guard (fail-closed)**, **JS parse gate** (every
   site module through `node --check --input-type=module` — a typo in `evidence.js`
   blocks the publish instead of breaking 40+ pages), full-graph hashing (§4), build
   stamp, per-type cache headers, CloudFront invalidation.
3. **Fonts** — explicit `aws s3 sync site/assets/fonts/` (the main sync deliberately
   excludes non-CSS/JS under `assets/`; the workflow automates the once-manual step).
4. **Gates** — `deploy/smoke_test_site.sh` (HTTP/content) ∥ visual + AI-vision QA
   (`tests/visual_qa.py --screenshot --ai-qa`) + accuracy audit
   (`tests/accuracy_audit.py --live`).
5. **Auto-rollback** — a red gate after a successful deploy runs
   `deploy/rollback_site.sh HEAD~1` (re-hash, re-stamp `version.json` to the prior
   build, re-invalidate) + SNS alert.

**Attended fallback** (when authorized — deploys are Matthew's call, and always from
`main`, never a worktree branch — `docs/CONVENTIONS.md` §2):
`bash deploy/sync_site_to_s3.sh` + the explicit fonts sync if fonts changed.

**Ordering rule — deploy the API before the front-end.** A change spanning
`lambdas/web/` + `site/` must get the site-api deployed **first**
(`bash deploy/deploy_site_api.sh` — full-tree bundle, never single-file; or the CI
production gate). Merging the pair at once means site-deploy.yml ships the page
immediately while the lambda waits on approval → visual-QA 404s on the new endpoint and
auto-rolls the site back (this happened on #750's first day).

**Before you merge — local render-QA.** `node --check` proves nothing about runtime;
render the page:
- `python3 tests/visual_qa.py --screenshot --ai-qa` (needs `playwright install chromium`)
  against live, or drive the changed page locally with Playwright + route-mocked
  `/api/*`. Route-mock gotchas: register the **catch-all route first**, **block service
  workers** (or the mocks are bypassed), and scroll the page before a full-page shot
  (scroll-reveals otherwise screenshot blank). The `render-qa` agent wraps this pattern.
- Check the pixel, not the diff — SITE_UPLEVEL_PLAYBOOK.md "The loop".

## 8. QA gates (ADR-076 — the 3 layers)

1. **`deploy/smoke_test_site.sh`** — HTTP/content smoke: v4 pages 200, legacy URLs 301,
   API freshness. Runs post-deploy in CI; cheap to run any time.
2. **`lambdas/operational/qa_smoke_lambda.py`** — data/output health (DDB freshness,
   score sanity), nightly against the live pipeline.
3. **`tests/visual_qa.py` (+ `visual_ai_qa.py`)** — Playwright browser sweep + Claude
   vision QA of each screenshot; **gating** in CI (deterministic FAIL or AI "high"
   verdict blocks/rolls back).

The `/qa` skill wraps all three for an attended sweep.
