# `www/` — the v9 static build

> **Status:** Phase 4 mechanics landed (#5534) — the build still ships to the `/next/v9/` preview only; the cut-over switch `live_at_root` in `owned_paths.json` is **false**. Plan: [`docs/design/v9/STAGE4_ENGINEERING_PLAN.md`](../docs/design/v9/STAGE4_ENGINEERING_PLAN.md) (owner-approved 2026-10-31). Stories #5530 (Phase 0) · #5534 (Phase 4), epic #5529. **Nothing here is deployed to the public root until the owner flips the switch** (§ The switch, below).

The Stage 3 design (Claude Design, 2026-10-31) as a static site: one typed content model, one build, one publication boundary, zero new AWS infrastructure. Astro 7 (static output) is a build-time toolchain only — the reader receives HTML, one stylesheet, self-hosted fonts and, from Phase 2, a few vanilla ES-module islands. No client framework.

## The pieces

| Piece | Where | What it is |
|---|---|---|
| The content model | `src/content.config.ts` | Eleven collections (chapter · episode · essay · metric · insight · experiment · prediction · disagreement · coach · source · method) plus the dated edition. Every entry carries the publication envelope: `id` · `type` · `visibility` (**literally `"public"` — anything else fails the build**) · `as_of` · `data_through` · `source` · `state` · `absent_text` · `approved` · `method_ids` · `edges` · `sample` · `title` · `summary`. Strict schemas: an unknown field fails the build. |
| The producer | `../scripts/publish_snapshot.py` | The ONE publication boundary. `--mode live` reads the public Site API over HTTPS with no credentials; `--mode fixture` reads `content/fixtures/` for deterministic CI builds. Writes only `visibility == "public"`; counts held/private in `manifest.json` and never serialises them. Refuses a dangling edge (exit 3) and a malformed object (exit 2). Byte-stable output. |
| The relationship index | `src/lib/edges.js` | Edges are stored once, on the object that knows them; the index inverts them at build. A dangling edge throws. `connected()` returns both directions, ordered story → machine, capped. |
| Canonical URLs | `src/lib/url.js` | One path per type, directory-style; every internal link goes through `href()` so the base path (`/` or `/next/v9/`) is never hard-coded. |
| Templates | `src/pages/` | One per object type; four destinations (Start · Story · Data · System), the appendix, privacy, 404. |
| The identity | `src/styles/tokens.css`, `fonts.css`, `base.css` | Frozen from the Stage 2 identity sheet. Light only (owner decision 6). Two AA corrections from the prototype: `--faint` 4.64:1, smallest type 12 px. |
| Fonts | `public/assets/fonts/v9/` | Archivo, Newsreader, IBM Plex Mono — Google's latin subsets, instanced to the axis ranges used (fontTools). 179 KB in all after the 2026-11-01 trim (Newsreader at one optical size, Archivo wdth 100–118), under the 250 KB budget; the heaviest page loads ~150 KB. SIL OFL 1.1 (`docs/LICENSES.md` §3.1). |
| Fixtures | `content/fixtures/*.json` | Sample objects marked `sample: true`, including one `held` chapter, one `pending` week, one `held` insight and one `private` prediction whose sentinel strings the gates look for. |
| Phase 1 content | the exporter's `_chapter_body`, `_live_week_states`, episode `transcript` | A published chapter's body is the permalink's `.prose` block as published (scripts and inline handlers stripped, links made absolute), never rewritten; a program week with no chapter is a `held` / `skipped` / `pending` row with no title or body; an episode carries its transcript turns for the read-along. |

## Build

```bash
cd www && npm ci                                   # pinned toolchain, lockfile
python3 ../scripts/publish_snapshot.py --mode fixture --out content/snapshot   # or --mode live
npm run build:preview                              # WEB_BASE=/next/v9/ WEB_NOINDEX=1 → dist/
npm run build                                      # WEB_BASE=/ (the production root; sitemap on) → dist/
npm test                                           # node --test: the index and formatters
python3 ../tests/web_preview_gate.py --out /tmp/web-gate   # Playwright, 390 + 1280, axe; mutation control first
```

Every build ends in `scripts/postbuild.mjs`, which emits two committed artifacts the Python side reads
(pytest cannot run `astro build`): **`owned_paths.json`** — every path the production build writes
(directory routes, `404.html`, the sitemap files, the `_astro/` and `assets/fonts/v9/` prefixes, plus the
static routes and route patterns read off `src/pages/`) and the cut-over switch `live_at_root`; and
**`reach.json`** — the front page's static reach (§ reach ratchet). Both are drift-checked against a fresh
build by `scripts/check_www_build.py` (the `owned-paths` check), so a route change that is not committed
reds the web gate. Rebuild and commit them together with any template change.

## The gates (CI: `.github/workflows/web-gate.yml`, on every PR touching this tree)

1. **Reproducible:** two builds from the fixture snapshot, one tree hash.
2. **Schemas validate:** the build itself, plus `tests/test_web_publication_snapshot_5530.py`, which also pins that the Python `SCHEMA` and the zod schema declare the same fields.
3. **Visibility:** a snapshot with one object flipped to `held` MUST fail `astro build` (mutation, run every time); `dist` is scanned for the fixture sentinels.
4. **Relationships:** a snapshot with one dangling edge MUST fail `astro build` (mutation, run every time).
5. **Existing QA reaches the output:** `tests/web_preview_gate.py` — the same Playwright-and-axe harness family as `qa/pr_render_gate.py` and `tests/kit_page_gate.py` — with its own mutation control (a planted overflow, inline script and sentinel must red it before it grades anything).

`.github/workflows/web-preview-deploy.yml` runs after a merge to `main` touching this tree: live snapshot → build → `aws s3 sync` (no delete) → invalidate. Same deploy role as the site deploy, no new grant. It has two targets and `deploy/www_deploy_target.py` picks one from the committed switch — see § Deploy below.

## Deploy — one owner per path (#5534)

Two deploy paths write `s3://matthew-life-platform/site/`: the `site/` tree (`deploy/sync_site_to_s3.sh`, on every merge touching `site/**`, and `deploy/rollback_site.sh` on a red sweep) and this build (`deploy/www_preview_sync.sh`). The rule: **every path in `owned_paths.json` is this build's, everything else is `site/`'s.** `sync_site_to_s3.sh` and `rollback_site.sh` `--exclude` exactly those paths (through `deploy/www_owned_paths.py`, fail-closed: no exclude set, no sync), so a `site/**` push or a site rollback can never re-publish the v8 front page over the launch. The exclusions are exact paths, never a prefix — `/story/chronicle/` stays `site/`'s even though `/story/*/` is a v9 route pattern.

| Target | Prefix · invalidation | Base | When |
|---|---|---|---|
| **preview** | `site/next/v9/` · `/next/v9/*` | `/next/v9/`, `noindex`, sitemap off | every `www/**` merge while the switch is off; `workflow_dispatch` with `target=preview` |
| **root** | `site/` · `/*` (waits for the invalidation, #1526) | `/`, self-canonical, sitemap on | every `www/**` merge once the switch is on; `workflow_dispatch` with `target=root` (REFUSED while the switch is off) |

A root run also: checks the **live** build's routes against the kept `site/` pages before syncing (`www_owned_paths.py --check-dist` — a v9 route landing on a kept page outside the declared replaced set `/`, `/story/`, `/data/`, `/privacy/` + `404.html`/`sitemap.xml` refuses the sync); runs the same two sweeps `site-deploy.yml` gates on (`deploy/smoke_test_site.sh`, `qa/visual_qa.py --screenshot --ai-qa --ai-qa-max-tier 1`); on green records the build at `s3://…/site/_v9_previous/`; on red rolls the v9 paths back from that prefix (`deploy/www_root_rollback.sh`, scope-checked like #3352/#3395) — S3 → S3, no delete, v9 keys only, **never from `site/`**. `qa/qa_manifest.py` derives the v9 rows (`owner: "www"`) from `owned_paths.json`'s static routes once the switch is on, so the sweeps know the pages.

### The switch

```bash
python3 scripts/www_cutover_switch.py --live     # sets live_at_root=true + flipped_on in owned_paths.json
# commit on a branch, open the PR, merge — the push to main deploys the root and every www/** merge after it.
gh workflow run web-preview-deploy.yml -f target=root     # a manual re-run of the root deploy, after the flip
```

The owner's go is that one-line merge (his five-reader bar on #5529 comes first; it is his, not the repo's). The flip is also what re-points the repo's description of `/`: the page registry, the sitemap writer and the reach ratchet all read the same bit. A dispatch with `target=root` before the flip exits 2 by design.

### Rollback — and what never rolls back

* **Automatic:** a red smoke or visual sweep after a root sync → `deploy/www_preview_sync.sh --target root --restore-previous` (the previous green v9 build over the root, `/*` invalidated, SNS). The first root deploy has no previous build: the step says so, writes nothing, and alerts.
* **By hand:** `bash deploy/www_preview_sync.sh --target root --restore-previous` (needs the deploy role). Rehearse any mode without credentials with `--print`.
* **Never automatic — the deliberate un-launch:** `python3 scripts/www_cutover_switch.py --preview` on a branch and merge it (the repo's half: the registry, sitemap writer and ratchet return to the v8 description), then `aws s3 cp` the four pages back from `git show <pre-flip-sha>:site/index.html` (and `story/`, `data/`, `privacy/`, `404.html`) and invalidate `/*`. Nothing in CI does this.

## Canonical and indexing at cut-over (requirement C)

* **v9 pages are self-canonical at `/`** (`src/layouts/Base.astro`): `<link rel="canonical" href="https://averagejoematt.com<path>">`, no `noindex`, and the build's sitemap lists them (`sitemap-index.xml` + `sitemap-0.xml`; `scripts/postbuild.mjs` copies the index to **`sitemap.xml`**, the URL the site has always advertised). On the preview base every page is `noindex` and the sitemap is off.
* **The kept `site/` pages are unchanged**: self-canonical, listed by `scripts/v4_build_sitemap.py` in **`sitemap-site.xml`** on every site deploy. Before the flip that generator also writes `sitemap.xml` (as it always has); after the flip it leaves `sitemap.xml` to the build — one writer per file at any time, arbitrated by the switch. `site/robots.txt` lists both `Sitemap:` lines.
* **Reference copies** of the superseded layouts (`scripts/v9_reference_copies.py --apply`; owner ruling 2026-10-18) live at `/reference/2026-11-01-{home,start,story,coaches}-v8/` and `/reference/2026-11-01-{data,privacy}-v5/`: `noindex,nofollow`, canonical → the v9 URL that replaces them (`/`, `/`, `/story/`, `/system/`, `/data/`, `/privacy/`), the last live sha in the head comment, asset links untouched, listed in the appendix under "Earlier front pages", never in a sitemap. `robots.txt` disallows `/reference/` and `/_v9_previous/`.
* **`/start/` and `/coaches/`** have no v9 twin: still served from `site/`, `noindex`, canonical → `/` and `/system/`. No URL moves, no 301s, nothing deleted.
* **The reach ratchet** (`tests/test_site_nav_reach_ratchet.py`): once the switch is on it reads `reach.json`'s `depth1_count` against `ledgers/site_vocabulary_residue.py::NAV_REACH_CEILING_V9` (10 on the fixture build after Phases 1–2, lowered from 18); the transitive closure is recorded, not ratcheted — on a content graph it is the number of published objects.

## Rules carried from the plan and the owner's conditions

- The snapshot is the only source of a published statistic; a page never computes an official outcome, grade or correlation (requirement A). Phase 2's explorer draws precomputed numbers.
- Grading corrections keep history (requirement B) — a Phase 3 contract on the exporter: original grade, timestamps, corrected grade, reason, evaluator version, aggregate impact.
- Canonical tags, sitemap inclusion and the fate of superseded layouts are settled before the Phase 4 cut-over (requirement C); until then every preview page is `noindex` and self-canonical.
- One canonical object, many discovery paths; a new object type is a schema, a template and an edge type — never a navigation edit (requirement D).
- The age is never published; "British, in Seattle" stays (decision 7). Reflections are owner-only; the public sees aggregates through the ADR-155 stamp (decision 5).

## Phase 2 — the data room (#5536)

- `scripts/publish_snapshot.py` maps the series catalogue (`/api/series`) to one Metric per publishable key and fetches each daily series for the experiment window into `content/snapshot/series/<metric>.json`; the platform's pair statistics (`/api/pairs`) land in `content/snapshot/pairs.json`. Both are data files beside the collections, hashed into the manifest and validated against the public Metric set (a series or a pairing naming a non-public metric fails the export). The chart marker is the reader-facing baseline-change date (`lambdas/web/baseline_change.py`), never the clinical module. The exporter's pure contract (schema mirror, envelope, validation, partition, writer) lives in `scripts/publish_snapshot_contract.py` and is re-exported.
- `src/lib/chart.js` draws the one line chart at build time AND in the island (a reader without JavaScript sees the same chart). Absence is drawn, not interpolated: a line never bridges a missing reading or a logging gap.
- `src/islands/explorer.js` is the progressive enhancement: range, 7-day mean, a second series, a lag of −2…+2 days. Every statistic it shows is READ from `pairs.json` via `src/lib/pairs.js`; nothing is computed in the browser (owner requirement A), and the word "significant" is never produced.
- `src/pages/data/series/[metric].json.ts` and `src/pages/data/pairs.json.ts` serve the snapshot's files beside the pages for the island (same origin; the CSP's `connect-src 'self'`).
- Node tests: `tests/chart.test.mjs`, `tests/pairs.test.mjs`.
