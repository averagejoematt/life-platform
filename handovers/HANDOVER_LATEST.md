# HANDOVER — 2026-06-01 (v4 "The Measured Life" — one engine, three doors)

**Previous handover:** `handovers/HANDOVER_2026-06-01_VacationFund.md` (vacation fund + site-api deploy lesson).
**This session covers:** the front-end rebuild of averagejoematt.com into the locked **Direction 05 "The Measured Life"** design system — Cockpit / Story / Evidence over the unchanged engine, with the old site preserved verbatim under `/legacy`. Built per `docs/CLAUDE_CODE_PROMPT_V4_PASTE_READY.md` + the four source-of-truth docs (Constitution, Design Brief, Design System, Migration Map).
**State:** ✅ **DEPLOYED LIVE 2026-06-01 (after a same-day rollback + fix cycle).** Sequence: cut over → presented badly → rolled back to old site → fixed the 4 root causes → re-deployed → **browser-verified, now live and correct.** `main` carries everything (PR #10 + fix commits). Redirect Function `v4-redirects` associated on `E3S424OXQZ8NBE`. **Browser-verified (headless Chromium):** Story renders full with real data (−1.9 lbs, 42-day waveform, Third Wall field note) in Fraunces; Cockpit shows a clean honest empty-state (data not computed — see below); Evidence index + readouts render; **zero CSP errors, fonts load from 'self', no `[AI_UNAVAILABLE]`/`··`.** Smoke: doors 200, old URLs 301, `/legacy/*` 200. No engine/pipeline/schema/Lambda/MCP changes — ever.

### First-cutover failures + fixes (ALL RESOLVED — keep as lessons)
1. **CSP blocked Google Fonts.** CSP is `style-src 'self' 'unsafe-inline'; font-src 'self' data:` → the Google CDN type triad was blocked, whole site fell back to default fonts. **FIXED:** `scripts/v4_vendor_fonts.py` self-hosts Fraunces/Instrument Sans/IBM Plex Mono → `site/assets/fonts/v4/*.woff2` (18 files, 418KB) + `site/assets/css/fonts.css`; doors link the local sheet. ⚠️ `sync_site_to_s3.sh` does NOT upload `assets/**` woff2 (its catch-all excludes `assets/*`) → fonts need an explicit `aws s3 sync site/assets/fonts/ …` step (done at deploy).
2. **Scroll-reveal hid all below-hero content** (`.beat` started at `opacity:0`, revealed only on scroll → blank first glance). **FIXED:** reveal is now TRANSFORM-ONLY (opacity stays 1) in `story.css` — content is never invisible.
3. **Degraded live data surfaced raw** (`/api/weekly_priority` = `[AI_UNAVAILABLE]`, `/api/character` 503). **FIXED:** `cockpit.js` `isBad()` hides sentinel/empty values; missing character sheet → a calm "score hasn't computed yet — refreshes each morning" empty-state (force `display:none` on empty domains/band, not `[hidden]` which the author display rules override).
4. **PROCESS: cut over with NO real browser render.** **FIXED going forward:** headless Playwright visual QA is now part of verification (load each door, assert fonts load + no CSP errors + content visible + no raw tokens). Do this BEFORE re-cutover next time.

**DEPTH RESTORATION (2026-06-01, later same day):** A data-coverage audit found 45 of 60 legacy API endpoints had no v4 consumer. Rebuilt the Evidence door bound to the REAL nested shapes + regrouped into 4 browsable sections (The body · Mind & accountability · Protocol & experiments · Credibility & the machine): DEXA body-comp (`physical_overview`), workouts+strength (`training_overview`+`strength_benchmarks`+`weekly_physical_summary`), CGM×meals (`glucose`+`meal_glucose`+`meal_responses`), sleep_detail, mind/inner-life, vice streaks, ledger, discoveries, genome risk, challenges (26), and **The Board** (8 named AI experts via `coaching-dashboard`). Cockpit **Journey scope** now renders `journey_timeline` (level-ups/milestones) + `achievements` (34, earned/locked) — gamified layer, empty-but-ready. Old URLs rehomed: `board`/`coaches`→`/evidence/board`, `accountability`→`/evidence/vices`, `ledger`/`discoveries`→their pages. Renderers in `assets/js/evidence.js` (slug→renderer map, multi-endpoint, honest empty states). Whole-site headless QA: all clean (0 CSP/JS errors, no raw tokens). Empty domains (CGM, nutrition macros today) render "ready, no data yet" and auto-fill from the pipeline.

**⚠️ Remaining (ENGINE/data, off-limits to the front-end):** the Cockpit is intentionally empty because `character-sheet-compute` hasn't produced today's record (`/api/character` 503 — `test_i17`) and the AI budget tier has paused Bedrock (`/api/weekly_priority` = `[AI_UNAVAILABLE]`). The Story/Evidence use other live endpoints and are full. The Cockpit fills automatically once the compute runs / budget resets — investigate `/aws/lambda/character-sheet-compute` + the budget tier if they stay stale.

**ROLLBACK reference:** disassociate `v4-redirects` (FunctionAssociations Quantity=0, `update-distribution`); restore overwritten shared files (`index.html`, `assets/css/tokens.css`, `sitemap.xml`) from the pre-v4 commit `84e98e4` to S3; invalidate. Old per-page files were never deleted (additive sync) so they serve immediately once redirects are removed.

---

## What shipped (front-end only)

| Piece | Where |
|---|---|
| **Foundation** | `site/assets/css/tokens.css` — v4 token system. Locked hexes as primitives + OKLCH `color-mix()` tints; dark-first + real Daybook light mode (OS-aware, explicit choice wins); the type triad (Fraunces=human / Instrument Sans=interface / IBM Plex Mono=machine); both signatures tokenized (`--spine-*`, `--voice-*`); honesty vocabulary (muted ink, dashed marker, never red); motion + reduced-motion. |
| **Cockpit `/now`** | `site/now/index.html` + `assets/css/cockpit.css` + `assets/js/cockpit.js`. Focus/logbook (LOCKED). Rule-spine, big tabular-mono Level+tier+movement, honesty chip, two-voice dialogue (machine=Chair verdict, human reply optional/hidden — not faked), Body/Mind bento, Consistency band, global Today/Week/Month/Journey scope, theme toggle, in-place pillar disclosure via View Transitions. Binds `/api/snapshot` + `/api/weekly_priority`; lazy `/api/coach_analysis` per pillar. `noindex` (daily tool). |
| **Story `/`** | `site/index.html` + `assets/css/story.css` + `assets/js/story.js`. Scrollytelling default door. Relational **constellation** hero (SVG, 7 pillar nodes sized by score, relationship edges, ember=climbing). Numbers beat (`/api/journey`), honest 42-day waveform with green/amber/red/gray down-beats in muted ink (`/api/journey_waveform`), the **Third Wall** two-voice (`/api/field_notes` ai_present↔matthew_agreement, honest "hasn't replied" fallback), Elena chronicle spine (`/public_stats.json` → links to preserved `/legacy/chronicle`), reachable close + quiet subscribe. `animation-timeline` scroll reveal with `@supports`/reduced-motion fallback. |
| **Evidence `/evidence/**`** | `site/evidence/index.html` + 26 topic pages, generated by `scripts/v4_build_evidence.py` from a topic REGISTRY. Shared `assets/css/evidence.css` + `assets/js/evidence.js` (generic honest "readout" — renders ACTUAL published data, correlative framing, confidence labels n<12 preliminary / n<30 low). 12 live-readout topics (bind their `/api/*`), 14 archive topics (v4 intro + "deeper →" link to preserved `/legacy`). Archival-index treatment, rule-tick indexed cards. |

**Design fidelity:** the §10 open Cockpit decision (Mara focus vs Tyrell relational canvas) was already resolved by the later board-unanimous Design System — Cockpit = focus/logbook, Tyrell's canvas repurposed as the Story's constellation hero. Built to that; no prototyping needed. Anti-template guardrails honoured (no Inter/Roboto/system fonts, no purple gradients, no shadcn cards, no emoji headers). Editorial guardrails apply to public copy.

---

## /legacy relocation (reversible, no edge config)

`scripts/v4_relocate_legacy.py --apply` (idempotent; refuses if `site/legacy/` exists). Moved 54 page-trees + `assets/` into `site/legacy/` — **84 pages, all noindex**. Rewrote **552** `/assets/` refs → `/legacy/assets/` and internal nav → `/legacy/...`; **left untouched** all 11 `/api/*` (CloudFront→Lambda), `/config/`, `/data/*.json`, root statics. **System pages** (`privacy`, `subscribe`/`confirm`, `404`) stayed at root, ported as-is. Fully `git`-reversible.

---

## Validation + cutover

- **Migration gate:** `scripts/v4_migration_inventory.py` now scans the preserved `site/legacy/` tree → **cockpit 8 · story 37 · evidence 30 · legacy 9 · 0 unmapped** (matches the map exactly). Writes `redirects.map` (**83** 301s; all evidence targets verified to exist). Enforced by a dedicated, deploy-free workflow `.github/workflows/v4-gate.yml` (PRs to main + pushes to main; self-skips pre-relocation) — kept OUT of the Lambda deploy pipeline (`ci-cd.yml`) on purpose.
- **a11y tests:** `tests/test_site_a11y_landmarks.py` updated — original guarantees repointed to the preserved legacy pages; new tests pin skip-link + `<main>` + tokens (reduced-motion, light mode, ember) across the three doors. All site tests green.
- **visual_qa:** `tests/visual_qa.py` PAGES updated with the three doors (+ supplements readout). It runs against the **live authenticated site post-deploy** (Playwright + cf-auth) — so it's a post-cutover check, not local. ⚠️ its deep legacy-page entries still use old URLs; repoint them to `/legacy/<path>` (or drop as each is rebuilt).
- **Cutover:** `deploy/v4_cutover.sh` (Matthew runs; Claude does not). Pre-flight gates (inventory 0-unmapped, doors+tokens present, legacy ≥80 pages, HTML well-formed) → generates a CloudFront redirect Function from `redirects.map` → safe `site/` sync → invalidation → prints verify commands. **Rollback** documented in the header (git revert + re-deploy, or disassociate the CF function; S3 versioning retains prior objects).

### ⚠️ 6 judgement calls to CONFIRM before cutover (in `redirects.map`; flip in inventory RULES if wrong)
`status`→Cockpit · `achievements`→Cockpit · `field-notes`→Story · `community`→Story · `results`→Evidence · `ask`→Evidence · `archive/v1/**`→/legacy. Current defaults match the migration map.

---

## Remaining / follow-ups
- **Deploy:** run `deploy/v4_cutover.sh`, apply the generated CloudFront redirect Function, then `tests/visual_qa.py` (green across doors) + a crawl for stray 404s. Live render-verify the three doors (no browser in this build env).
- **Evidence depth:** 14 archive topics + interactive ones (ask/explorer/tools) link to preserved legacy until rebuilt bespoke; deepen as time allows.
- **Cockpit:** week/month/journey deeper series; human-voice daily reply source if/when published.
- **visual_qa:** repoint legacy-page entries to `/legacy/`.
- **Docs/CI:** migration gate runs via `.github/workflows/v4-gate.yml` (done); `python3 deploy/sync_doc_metadata.py --apply` run (pre-commit hook also does this).
- Source-of-truth docs: `docs/{V4_DESIGN_CONSTITUTION,CLAUDE_DESIGN_BRIEF_V4,DESIGN_SYSTEM_V4_THE_MEASURED_LIFE,MIGRATION_MAP_V4}_2026_06_01.md`.
