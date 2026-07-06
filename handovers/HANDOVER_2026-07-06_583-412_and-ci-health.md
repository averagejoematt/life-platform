# HANDOVER — #583 chart contract + #412 training-truth + main-CI health — 2026-07-06

> Matthew authorized all edits/merges/deploys up front ("close out as much as we can
> efficiently without sacrificing quality"). A **concurrent session was live the whole
> time** (it shipped #415/#417); I isolated every change in a dedicated worktree off the
> latest origin/main — clean 3-way merges, zero shared-tree stomping. Matthew closed the
> other session near my wrap.

## What shipped (all merged + deployed + verified)

### 1. #583 — Chart interaction contract v2, batch 2 (cells + radials), 24/24
PR #709, main `9f9f2f30`. **Static-site only** (no layer/CDK/site-api). Completes the
`data-cpts` interaction contract — nothing on the site is dead to the touch.
- **`motion.js`**: `makeReadout()` + `wireGrammar()` factor the ONE focus-dot/tooltip +
  pointer/tap-linger/keyboard/Escape grammar. Batch-1's 1-D axis path is behavior-preserved.
- **Strategy 1 — radial/scatter** (`data-cpts` + `data-cpts-hit="xy"`, 2-D Euclidean nearest):
  `ring`, `pillarRing` (new `pillarRingCpts` geometry helper on the caller-owned `.ch-ringsvg`),
  `radarChart` (per-vertex), `autonomicQuadrant` (per-dot, replacing the native `<title>`).
  `--pillar-*` identity hues preserved.
- **Strategy 2 — reflowing DOM cells** (`data-cells`, nearest cell-CENTRE in live screen
  space, 2-D keyboard walk): `heatStrip`, `mealWindowRibbon`, `habitsEffortMap`; each cell `data-l`.
- `tokens.css`: `.vr-c` got `pointer-events:none` so the ring's center label never shadows its
  own readout.
- **Verified**: a Playwright harness rendered all 8 renderers + 2 batch-1 regression guards
  (lineChart x-axis, dumbbell y-axis) → pointer + keyboard both surface the tip, Escape
  dismisses, 0 console errors, both themes. Then LIVE on prod `/data/{character,vitals,habits,
  nutrition}/` (10 interactive elements, real data). Smoke 67/67. Deploy: `sync_site_to_s3.sh`.

### 2. #412 — Training-truth: pushed-vs-performed deviation loop
PR #712 (core) + PR #714 (fix), main `4ab48797`. **No layer bump.** Wired the already-tested
`adherence_calc.calculate_adherence` into Hevy ingestion.
- `adherence_calc.derive_adherence(raw_workout)` → match → compute → honest status, embedded in
  the workout DDB record BEFORE `write_normalized` (same idempotent put, self-heals on re-ingest),
  surfaced via `mcp/tools_hevy._slim_workout` → `get_workout_detail`.
- Match: exact-first via `hevy_routine_id` (id-map, immune to the UTC-date bug); Pacific-day
  fallback (`routine_repo.list_by_date_range`, new `pacific_time.pacific_date_of`); multi-sibling
  → template-id overlap; tie/zero → `ambiguous`; no plan → `ad_hoc`. ad_hoc/ambiguous omit all
  pct fields (ADR-104, no fabricated number).
- Movement→template resolution (`_ir_movement_to_template`, three tiers): **(0) `tmpl:<id>` keys
  carry the id in the suffix** (routines program some exercises by raw template — ADR-069 index),
  **(1) catalog hint**, **(2) resolved template cache** `config/hevy_template_cache.json` for the
  3 ADR-069 title-resolved movements (no hint on purpose — do NOT add hints).
- **IAM**: hevy backfill + webhook roles got `s3:GetObject` on `config/movement_catalog.json` +
  `config/hevy_template_cache.json`. Deploy: `cdk deploy LifePlatformIngestion LifePlatformMcp`
  (the #412 deploy also completed the concurrent session's pending ingestion layer 114→115 migration).
- **THE LESSON — drive the real flow, not just tests.** Unit tests (16) were green + deploy
  healthy, but re-ingesting the real 2026-06-25 workout showed **overall_pct=47.8% when he did
  the WHOLE workout** — 4 `tmpl:<id>` movements were mis-counted missing. The tier-0 fix (#714)
  restored it to **100.0** with the one un-planned stretch honestly listed as `extra`. Forced the
  real-data check by rewinding the `USER#system / INGESTION_STATE#hevy` `since_iso` cursor to
  before the workout, invoking `hevy-backfill` (idempotent upsert re-embeds adherence); the cursor
  auto-advances to now on success (verified back to normal at close).

### 3. Main-CI health — restored the gate to GREEN (first time since the pre-#408 era)
Main-push CI had been red at the **Lint gate**, which masks the Test gates. Fixed in two small
test/lint-only PRs (no deploy):
- **PR #759** (`610f787b`): `ruff --fix` the I001 import-sort in `lambdas/web/site_api_lambda.py`
  (concurrent session's code) + updated the stale `test_home_fold` assertion (my own #590
  constellation-v2 caption rewrite changed "not a broken one" → "a young experiment starts low,
  not broken").
- **PR #760** (`c67c5602`): greening Lint UNMASKED a latent Test-lane failure — 4 portrait/card
  tests (`test_portrait_raster`, `test_og_coach_cards`, `test_coach_episode_cover`,
  `test_render_portraits_parity`) imported PIL-dependent modules at module scope without a guard,
  so they failed at COLLECTION (CI test lanes install pytest+boto3 only — no Pillow, by design).
  Added `pytest.importorskip("PIL")` before the PIL import in each (the established
  `test_card_engine` convention). Verified: PIL-blocked → full suite collects 3714 tests, 0 errors.
- **Confirmed GREEN**: main CI run on `c67c5602` — Lint + Deploy-critical + Unit Tests all success
  (Deploy job waits for production approval, as designed).

## Worktree discipline (the win this session)
Every change was built in a throwaway worktree off the latest `origin/main`
(`git worktree add … -b <branch> origin/main` → edit → PR → merge → `worktree remove`), because
a concurrent session was actively merging into the shared tree and touching overlapping files
(`role_policies.py`). Stash-pop across the base change was clean each time. **No #590/#408-style
squash-stomp.** See [[feedback-concurrent-session-worktree]].

## State at close
- `main` == origin (`c67c5602` after the PIL-guard merge). Worktrees pruned to 2 (main +
  pre-existing `docs/uplevel-handover`); the two stale `.claude/worktrees/agent-*` copies remain
  (they belong to background-agent runs; prune before a full-suite-on-main if they trip
  `test_hevy_compiler_isolation`).
- Layer v115 (bumped by the concurrent #417 session). #412 needed no layer bump.
- Issues CLOSED: #583, #412 (+ its #714 fix). Main CI green.

## Carried forward (from the #415/#417 close — still Matthew's calls)
- **Re-stamp (#417) SHIPS DISABLED** — 2 decisions before enabling: (1) TIMING (rule 12:45 UTC vs
  Whoop recovery refresh 17:30 UTC → would re-stamp on stale recovery); (2) BRANCH PUSH FORMAT
  (base+menu-in-notes vs push the recommended branch's own exercises). Flip SSM
  `/life-platform/hevy/restamp_enabled` + the rule `enabled` after deciding.
- **Watch `ingest-reconciliation-whoop`** — #415's first live run caught a real dropped Whoop
  workout (`7a62677b…`, 2026-07-05); trailing-refresh should heal it — confirm it did.
- **GitHub Pages still enabled + public** (carried many sessions, unactioned).

## Next session
- **#409** batch-price content AI (LAYER bump, attended) · **#395** MCP prune (attended/destructive)
  · **#687** OIDC trust-tighten (watched live CI, risky IAM).
- Backlog data stories on epic #348: **#475** Hevy edit/delete lifecycle (adjacent to #412 — do
  aware), #421 vitals depth, #422 habit causality. #552 State-of-Matthew brief (site-ux, cross-stack).
- Optional: distill ONE build-in-public beat for #583/#412 per `docs/content/BUILD_DISPATCH_CHECKLIST.md`.
