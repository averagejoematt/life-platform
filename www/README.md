# `www/` — the v9 static build

> **Status:** Phase 0 (foundations) — a non-public preview shell. Plan: [`docs/design/v9/STAGE4_ENGINEERING_PLAN.md`](../docs/design/v9/STAGE4_ENGINEERING_PLAN.md) (owner-approved 2026-10-31). Story #5530, epic #5529. **Nothing here is deployed to the public root.**

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
| Fonts | `public/assets/fonts/v9/` | Archivo, Newsreader, IBM Plex Mono — Google's latin subsets, instanced to the axis ranges used (fontTools). 304 KB in all; the heaviest page loads ~262 KB. SIL OFL 1.1 (`docs/LICENSES.md` §3.1). |
| Fixtures | `content/fixtures/*.json` | Sample objects marked `sample: true`, including one `held` chapter, one `pending` week, one `held` insight and one `private` prediction whose sentinel strings the gates look for. |
| Phase 1 content | the exporter's `_chapter_body`, `_live_week_states`, episode `transcript` | A published chapter's body is the permalink's `.prose` block as published (scripts and inline handlers stripped, links made absolute), never rewritten; a program week with no chapter is a `held` / `skipped` / `pending` row with no title or body; an episode carries its transcript turns for the read-along. |

## Build

```bash
cd www && npm ci                                   # pinned toolchain, lockfile
python3 ../scripts/publish_snapshot.py --mode fixture --out content/snapshot   # or --mode live
npm run build:preview                              # WEB_BASE=/next/v9/ WEB_NOINDEX=1 → dist/
npm test                                           # node --test: the index and formatters
python3 ../tests/web_preview_gate.py --out /tmp/web-gate   # Playwright, 390 + 1280, axe; mutation control first
```

`npm run build` (base `/`, sitemap on) is the Phase 4 production target and is not run by any workflow yet.

## The gates (CI: `.github/workflows/web-gate.yml`, on every PR touching this tree)

1. **Reproducible:** two builds from the fixture snapshot, one tree hash.
2. **Schemas validate:** the build itself, plus `tests/test_web_publication_snapshot_5530.py`, which also pins that the Python `SCHEMA` and the zod schema declare the same fields.
3. **Visibility:** a snapshot with one object flipped to `held` MUST fail `astro build` (mutation, run every time); `dist` is scanned for the fixture sentinels.
4. **Relationships:** a snapshot with one dangling edge MUST fail `astro build` (mutation, run every time).
5. **Existing QA reaches the output:** `tests/web_preview_gate.py` — the same Playwright-and-axe harness family as `qa/pr_render_gate.py` and `tests/kit_page_gate.py` — with its own mutation control (a planted overflow, inline script and sentinel must red it before it grades anything).

`.github/workflows/web-preview-deploy.yml` runs only after a merge to `main`: live snapshot → build → `aws s3 sync` (no delete) into `s3://matthew-life-platform/site/next/v9/` → invalidate `/next/v9/*`. Same deploy role as the site deploy, no new grant, every page `noindex`.

## Rules carried from the plan and the owner's conditions

- The snapshot is the only source of a published statistic; a page never computes an official outcome, grade or correlation (requirement A). Phase 2's explorer draws precomputed numbers.
- Grading corrections keep history (requirement B) — a Phase 3 contract on the exporter: original grade, timestamps, corrected grade, reason, evaluator version, aggregate impact.
- Canonical tags, sitemap inclusion and the fate of superseded layouts are settled before the Phase 4 cut-over (requirement C); until then every preview page is `noindex` and self-canonical.
- One canonical object, many discovery paths; a new object type is a schema, a template and an edge type — never a navigation edit (requirement D).
- The age is never published; "British, in Seattle" stays (decision 7). Reflections are owner-only; the public sees aggregates through the ADR-155 stamp (decision 5).
