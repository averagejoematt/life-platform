# CLAUDE CODE — Build averagejoematt.com v4 ("The Measured Life")

You are rebuilding the **front-end** of averagejoematt.com from the ground up. Four documents in `docs/` are the source of truth — read them before writing code: `V4_DESIGN_CONSTITUTION_2026_06_01.md`, `CLAUDE_DESIGN_BRIEF_V4_2026_06_01.md`, `DESIGN_SYSTEM_V4_THE_MEASURED_LIFE.md`, `MIGRATION_MAP_V4_2026_06_01.md`. This prompt is the execution plan; where it and a doc disagree, the doc wins.

## Mission
Re-express the existing static site (`site/`, **89 HTML pages**, served via CloudFront `E3S424OXQZ8NBE` from S3 in us-west-2) as **one engine, three doors** — Cockpit, Story, Evidence — in the locked **Direction 05 "The Measured Life"** design system. Single **big-bang** release; the current site is preserved verbatim at **`/legacy`** for one-flip rollback. North star (the tiebreaker): an honest living documentary of an ordinary life rebuilt with AI — the anti-Blueprint. The name enforces it.

## Do NOT touch the engine
No changes to data pipelines, ingest, the MCP server/tools, Lambda business logic, DynamoDB schema, or Secrets. Read the existing published data contracts only (`site/data/**`, `site/api/**`, renderer output). If a value isn't published yet, extend the renderer's output — never reach into the engine. The diff for this work is confined to `site/`, `assets/`, `scripts/`, `deploy/`, and the renderer's templates.

## Non-negotiables
- **Static / vanilla** front-end (no heavy SPA framework). Build `assets/css/tokens.css` from the design system. Use 2026-native tech: View Transitions API (in-place pillar disclosure + door changes), scroll-driven animations (Story), variable fonts, CSS Subgrid (bento), container queries, OKLCH + `color-mix()`.
- **Dark-mode-first** plus a real light mode.
- **No AI-template tells:** no Inter/Roboto/system fonts, no purple gradients, no stock shadcn/SaaS cards, no emoji headers. Do not echo WHOOP's dashboard look.
- **Deploy discipline:** write deploy scripts to `deploy/`; Matthew runs them in the terminal — never execute them yourself. S3 origin us-west-2; CloudFront invalidations in us-east-1; never `s3 sync --delete` at the bucket root.
- **Editorial guardrails (all public surfaces):** no employer/industry/role specifics; partner never named; the two designated vice categories never named; bereavement excluded unless opted in; chest-tightness paired with cardiovascular bloodwork framing only; escapism metaphorical.
- **Correlative framing** everywhere (never causal; N<30 = low confidence; <12 obs = "preliminary"). The LLM never computes — it interprets pre-computed numbers only.
- **Honesty vocabulary:** down weeks / pauses render in muted ink + plain language (and Matthew's human-voice reply where it fits) — never alarm-red, never hidden.
- **Accessibility AA**, full keyboard path, `prefers-reduced-motion` static fallback for all motion and scrollytelling.

## The three doors
| Door | URL | Job | Pattern |
|---|---|---|---|
| Cockpit | `/now` | "Am I winning + the one thing right now?" | Pattern A focus model; pillar detail opens **in place**; one global Today/Week/Month/Journey scope |
| Story | `/` (default for any visitor or shared link) | "The honest arc of this transformation" | Scrollytelling; the relational **constellation** as hero visual; Elena's chronicle + the Third Wall woven; honest down-beats |
| Evidence | `/evidence/**` | "What's the protocol, what's it built on, does it hold up?" | Archival index; supplements with what/why/what's-backed; experiments read-only |

The Cockpit stays a one-second read — the big editorial scale lives in the Story, not here.

## Design system — Direction 05 "The Measured Life"
Warm near-black instrument base (`#16130E`), bone ink (`#ECE3D2`), one ember live-signal accent (`#DD7A37`); a Daybook-informed light mode. Type triad: **Fraunces** (human voice) / **Instrument Sans** (interface) / **IBM Plex Mono** (machine voice & data, tabular). Two ownable signatures to build and protect: (1) the **measuring-rule spine**; (2) the **machine↔human two-voice dialogue** — the Third Wall rendered as the type system. Full values + per-door treatment: `DESIGN_SYSTEM_V4_THE_MEASURED_LIFE.md`; visual reference: `v4_art_direction_05_the_measured_life.html`.

## Migration — every page has a home (verified, 0 unmapped)
All 89 pages classified: **Cockpit 8 · Story 37 · Evidence 30 · System 5 · Legacy 9.** Full table: `MIGRATION_MAP_V4_2026_06_01.md`; rules: `scripts/v4_migration_inventory.py`.
- Run `python3 scripts/v4_migration_inventory.py` from the repo root — it must report **0 unmapped** and writes a `redirects.map` skeleton. Wire it into `ci-cd.yml` as a gate.
- 301 every old URL to its new door home, or to `/legacy/<path>` if archived. Preserve the entire current site verbatim under `/legacy` (`noindex`). Keep `sitemap.xml` / `rss.xml` / `robots.txt` current.
- **Six judgement calls to confirm with Matthew before cutover** (current defaults in RULES): `status`→Cockpit (→System if it's uptime/freshness), `achievements`→Cockpit, `field-notes`→Story, `community`→Story (→System if a functional signup), `results`→Evidence, `ask`→Evidence. `archive/v1/**` → Legacy.

## Build order (big-bang, gated)
1. Relocate the current site to `/legacy` (verbatim, kept served). Do not delete `site/`.
2. Build `assets/css/tokens.css` (both modes) from the design system.
3. Build the three doors over the existing data contracts.
4. Wire redirects from the reviewed `redirects.map`.
5. Validate as a whole: `tests/visual_qa.py` green across every door; inventory gate 0 unmapped; crawl shows no unintended 404s.
6. One cutover deploy script (you write to `deploy/`, Matthew runs); CloudFront invalidation (us-east-1); document rollback steps in the script header.

## Definition of done
Three doors live; all 89 old URLs 301'd; gate green; no engine/pipeline/schema diff; Cockpit passes the two-jobs test on mobile and opens pillar detail in place; Story scrollytelling has a reduced-motion fallback and the constellation renders; AA + guardrails + correlative framing enforced on all public copy; CHANGELOG / HANDOVER_LATEST / ARCHITECTURE updated and `sync_doc_metadata.py --apply` run.

## Start with
`assets/css/tokens.css`, then the `/legacy` relocation + redirect wiring, then the Cockpit — in that order.
