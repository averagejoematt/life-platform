# v4 Migration Map & Coverage Gate — FINAL

**Status:** Complete classification of all 89 existing pages · **Date:** 2026-06-01
**Purpose:** Every existing URL has a deliberate home in v4 (Cockpit / Story / Evidence / System) or goes to `/legacy`. Hard gate before the big-bang cutover. Zero orphans.

**Inventory:** 89 HTML pages enumerated from `site/**/*.html`. Counts by destination: **Cockpit 8 · Story 37 · Evidence 30 · System 5 · Legacy 9**.

---

## → Cockpit (8) — daily state, score, time-views
`character` · `observatory` · `live` · `week` · `weekly` · `recap` · `status`* · `achievements`*

## → Story (37) — narrative, journey, the cast, public face
`/` (root, the default door) · `chronicle/**` (index, archive, sample, posts: interview, issue-05, week-00…04, TEMPLATE) · `journal/**` (index, archive, sample, posts: week-minus-1, week-00…04, TEMPLATE) · `elena` · `story` · `mission` · `about` · `first-person` (Third Wall) · `field-notes`* · `discoveries` · `progress` · `start` · `start` · `builders` · `community`* · `accountability` · `ledger` · `board` · `coaches`

## → Evidence (30) — depth, protocols, data, credibility
`nutrition` · `sleep` · `training` · `physical` · `mind` · `supplements` (+`/protocol`) · `labs` · `biology` · `glucose` · `protocols` · `habits` · `experiments` (+`/detail`) · `challenges` (read-only) · `benchmarks` · `methodology` · `intelligence` · `predictions` · `stack` · `kitchen` · `results`* · `cost` · `explorer` · `data` · `tools` · `platform` (+`/data`, `/reviews`) · `ask`*

## → System (5) — functional, ported as-is
`404.html` · `privacy` · `subscribe` (+`/confirm`, `subscribe.html`)

## → /legacy (9) — already-archived v1, preserved not rehomed
`archive/v1/`: `board` (+`/product`, `/technical`) · `coaches` · `intelligence` · `recap` · `stack` · `supplements_protocol` · `weekly`

---

## My calls on the genuinely ambiguous (* above) — flip any in the script's RULES
- `status`* → **Cockpit** (a "where I stand now" page). If it's system/uptime/freshness instead → move to System.
- `achievements`* → **Cockpit** (gamified character score). Could surface in Story.
- `field-notes`* → **Story** (reflective AI lab notes). Could sit in Cockpit if it's a live panel.
- `community`* → **Story** (build-in-public corner). If it's a functional signup/forum → System.
- `results`* → **Evidence** (outcomes/data). Could anchor a Story beat.
- `ask`* → **Evidence/tools** (ask-the-data Q&A). Verify intent.

Everything unstarred is a confident assignment.

## Redirect & legacy policy
- 301 every old URL to its new door home, or to `/legacy/<path>` if archived. The **entire current site is preserved verbatim under `/legacy`** (rollback = one flip); the legacy tree is `noindex`.
- `scripts/v4_migration_inventory.py` emits a `redirects.map` skeleton (old → proposed new). Review before wiring to the edge.
- Keep `sitemap.xml`, `rss.xml`, `robots.txt` current for the new structure.

## Definition of done (gates cutover)
`v4_migration_inventory.py` reports **0 unmapped**, `redirects.map` covers every old URL, and a post-cutover crawl returns no unintended 404s.
