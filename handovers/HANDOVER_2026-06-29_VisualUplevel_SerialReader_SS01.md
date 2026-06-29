# HANDOVER — Visual uplevel + editorial imagery + 6-month foresight + serial reader + SS-01 — 2026-06-29

**One very long session.** Three big threads, all shipped live: (1) a **graphic-identity uplevel** of the website, (2) **free-license editorial imagery** on the Story surfaces, (3) a **"hands-off 6-month" foresight simulation** → a self-sustainability backlog, and the start of building it: a **serial "walk-backwards" reader** + **SS-01 (the chronicle can't go dark)**. Lots was deployed (Matthew authorized the deploys as we went). **`main` is at `b35c8c68` (#261 merged).** ⚠️ **PR housekeeping is the one thing left for Matthew** (close #262/#263, merge #264/#265) — see §6.

---

## 1. Visual identity uplevel — SHIPPED + LIVE (#260 + #261 merged; #262/#263 superseded)
Code-drawn SVG identity honoring the "earned glow / no gloss" rule. **Zero data-contract change.**
- **Icons** — `site/assets/icons/icons.svg` sprite + `site/assets/js/icons.js` (`icon()`, `domainIcon()`, `DOMAIN_ICON`): 8 domain + 5 door icons, currentColor, external `<use>`. Replaced the random emoji.
- **Coach sigils** — `site/assets/js/sigils.js` `sigil(coach)`: a deterministic geometric mark per persona (FNV-1a→mulberry32), vivid per-coach `--coach` colour. Wired into the board grid, coaching headers, team roster, popover, board-read digest.
- **Pillar/door identity** — domain icons on cockpit rows + `/data/` nav/title; door icons in the 5-door nav (all builders + home/now shells).
- **Constellation depth** — earned glow on "up" nodes.
- **Intensity pass** — icons muted-not-faint, ember page-title mark, ember on up-pillars, bigger/bolder sigils.
- **OG card** — `lambdas/og_image_lambda.mjs` reskinned to the v5 ember/ink palette + the `instrumentMark()` (same sigil vocabulary). The LIVE generator is the `.mjs` (Node), NOT the legacy `web/og_image_lambda.py`.
- **Standard** — `docs/DESIGN_SYSTEM_V5.md §8` codifies the whole system (reuse the modules; never reintroduce emoji). Memory: `project_visual_identity_system`.

## 2. Editorial imagery (Pexels) — SHIPPED + LIVE
Atmospheric free-license covers on **chronicle/podcast/blog ONLY** (never data/meal — truthfulness moat). Warm-duotone treatment.
- **`lambdas/editorial_image.py`** — fail-soft Pexels helper; kill-switch `EDITORIAL_IMAGES` (now **ON**). Constrained atmospheric query pool; stores to `generated/assets/images/editorial/`.
- **Two real fixes found live:** (a) **Cloudflare 403 "error 1010"** — Pexels behind Cloudflare bans the default urllib User-Agent; added a real UA on both the API + image fetch (403→200). (b) **Image dedup (Matthew's catch)** — chronicle Week N and podcast Week N shared a photo (same numeric seed); added a **per-kind seed offset** (`_KIND_SEED_OFFSET`), re-fetched the podcast covers, updated `episodes.json` credits. The offset is **deployed to the Lambda** so future posts decorrelate too.
- **Owner setup done:** Pexels secret `life-platform/pexels` created; `cdk deploy LifePlatformWeb` (editorial CloudFront behavior `/assets/images/editorial/*` + the new OG card) and `LifePlatformEmail` (editorial wiring + IAM); `EDITORIAL_IMAGES=on`; existing posts **backfilled** (covers render live in the chronicle/podcast readers).

## 3. 6-month "hands-off except data entry" foresight — RECORDED (#264, backlog PR open)
The engine self-sustains (~50 crons + the remediation agent), but several failures **go dark / decay silently**. Per-audience: QS/engineer best-served + improves; **friends & family worst-hit** (the public weekly story stops). Full report in plan `~/.claude/plans/soft-baking-toast.md`; recorded as the **SS-series** (11 items) in `docs/BACKLOG.md`.

## 4. Serial "walk-backwards" reader — SHIPPED + LIVE (#265 / `feat/serial-reader`)
Phase 1 of the evolving-serial vision (front-end, reads existing endpoints):
- **Interactive timeline** (`/story/timeline/`) — "the story so far" recap (Day N · Week N · lbs down + Jump-to-Day-1), month-grouped moments newest-first, ember dots on the up/milestones, **"Read Week N →"** into the chronicle that narrates each moment.
- **"Previously" rail** in the chronicle reader (the 2 prior installments).
- **Coach-evolution trail** — collapsible "how this read has evolved" rendering each coach's dated `recent_outputs`.
- **Podcast↔chronicle** cross-link.

## 5. SS-01 — the chronicle can't go dark — SHIPPED + LIVE + VERIFIED (in #265)
The #1 self-sustainability hole: `wednesday-chronicle` runs `PREVIEW_MODE=true`, so an un-clicked approval → the weekly story **never publishes**. Fix: a **daily EventBridge sweep** on `chronicle-approve` auto-publishes drafts unapproved past the review window, via the SAME publish path the approve click uses.
- **Safety window** `[CHRONICLE_AUTOPUBLISH_HOURS=48, CHRONICLE_AUTOPUBLISH_MAX_DAYS=10]` — catches a recently-unapproved draft ("forgot to click"), **never resurrects an abandoned one**. The dry-run caught a real 3-week-old pre-genesis draft (`2026-05-16`, week 7) — the window now correctly **skips** it.
- `chronicle_approve_lambda`: `_find_stale_drafts` + `_sweep_stale_drafts` + handler routes a scheduled (`source=aws.events`) invoke to the sweep (`dry_run` supported). CDK: daily `cron(0 18)` + the two env vars + `dynamodb:Query` on the approve role. 5 unit tests. **Verified live** (dry-run → `swept: []` after the window fix). `LifePlatformEmail` deployed (×3 this session).

---

## 6. ⚠️ OUTSTANDING — for the next session (nothing here is done)

### Matthew's PR housekeeping (only he can; the agent is blocked from merging its own PRs)
- **Close #262 and #263** — superseded by #261 (already on `main`); they only conflict because there's nothing new.
- **Merge #264** (SS-series backlog) and **#265 / `feat/serial-reader`** (serial reader Phase 1/1b + SS-01). `feat/serial-reader` is the session's work tip (has #261 content + the serial + SS-01 + these docs).
- After merging, `main` == live. (Branch-stack drift has been the recurring pain this session — squash-merges + parallel branches; the `--ours` reconcile pattern worked each time.)

### The self-sustainability program (SS-series, `docs/BACKLOG.md`)
- **SS-01 ✅ done** (this session). Remaining: **SS-02** podcast HOLD-aging escape · **SS-03** loud decay alarms (Garmin-staleness distinct from generic freshness, budget-tier≥2, podcast-HOLD-aging, Dependabot-PR-age) · **SS-04** Dependabot safe-auto-merge · **SS-05** experiment-continuity decision · **SS-06** enforce gradable predictions.

### The evolving-serial program (backend phases — each its own session + deploys)
- **Coach-opinion engine** — a longitudinal stance that evolves beyond the weight-ladder; **coaches review the site/challenges/habits** (feed `challenges`/`habits`/`experiments` into the coach generation brief — the hook is `coach_narrative_orchestrator`). The substrate that's ALREADY longitudinal: `PREDICTION#`/`LEARNING#` track record, `THREAD#` (ref_count), `OUTPUT#` per-day. The gap is the explicit opinion-of-Matthew model + the site-review loop.
- **Elena-written "previously on" recaps** + season/arc structure (chronicle lambda prompt).
- **Arbitrary historical-window APIs** ("jump to week 5's sleep") — `/api/character?date=` already time-travels; extend to data/waveform.
- **Remaining cross-links** (data→chronicle annotations).

### Smaller / known
- **Editorial-image guard (SS-11)** — the imagery is fully-automatic with no review; a quality/denylist or human-approve step is a worth-considering counterweight.
- **`ai_calls.py` nutrition guardrail** rides the next layer rebuild (pre-existing).
- A real **stale chronicle draft** (`2026-05-16`, week 7) sits in `status=draft` — SS-01 correctly ignores it (too old); if Matthew wants it published or deleted, that's a manual call.
- **Future-cover decorrelation** is deployed (helper offset live in the Lambda) — no action needed.

---

## Deploys done this session (Matthew authorized as we went)
`LifePlatformWeb` (OG card + editorial CloudFront behavior), `LifePlatformEmail` ×3 (editorial wiring → offset+SS-01 → SS-01 window-fix), multiple `sync_site_to_s3.sh` (visual identity, intensity, serial reader, image fixes), `EDITORIAL_IMAGES=on` on both generators, Pexels secret created, post backfill, CloudFront invalidations.

## Deploy-hygiene lessons (recurring)
- **Squash-merge drift:** after a PR squash-merges, parallel branches diverge by lineage (not content); `git merge origin/main` then `git checkout --ours <file>` resolves cleanly when your branch is a superset. The `sync_site_to_s3.sh` clobber-guard catches this before it reverts live work.
- **The live OG generator is the `.mjs`**, not the Python.
- **A 200 invoke isn't proof** — the editorial dry-run pattern (`{"sweep":true,"dry_run":true}`) is the right way to verify a scheduled lambda without side effects.
