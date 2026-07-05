# HANDOVER — #589 the honest freshness pulse — 2026-07-05

> Solo session (no other Claude running in this worktree — a separate concurrent
> agent was mid-flight on #408 in the shared main working directory + its own
> worktree; untouched, left as its owner's in-progress state). Matthew had already
> authorized all edits/merges/deploys for the session. One issue, start to finish:
> implement → test → PR → merge → deploy → verify live.

## What shipped — #589 (PR #705)

A reusable freshness-pulse primitive: any element carrying `data-fresh-ts` (an ISO
instant) + `data-fresh-window` (seconds — the source's OWN registry-derived window,
never a guessed constant) gets a subtle ember pulse (`.fr-live`) **only** while
`now − ts` is inside that window. Past the window it falls through to the existing
motionless `.pv-stale`. Reduced-motion keeps the color/text state, drops the keyframe.

- **`tokens.css` §12c** — the CSS (`.fr-dot`, `[data-fresh-ts].fr-live`, `fr-pulse`
  keyframe, reduced-motion-gated).
- **`motion.js`** — `wireFreshness()` + `freshWindowOk()`, a NEW self-contained block
  kept beside (not merged into) the existing `data-cpts` chart-wiring, per the issue's
  explicit ask to stay merge-clean with the concurrent #590 branch. Re-checks on a
  60s interval + MutationObserver (SPA-injected markup, e.g. the cockpit sync line's
  own poll-driven re-render, gets picked up automatically).
- **Backend (site-api, additive only):** `/api/source_freshness` now also returns
  `last_update_ts` + `stale_hours` per source; `/api/last_sync` now also returns
  `stale_hours` per source. Both reuse the SAME `source_registry.py`-derived
  thresholds already used to compute `status` — no new source of truth invented.
- **Adopted on three surfaces:**
  1. **Cockpit sync line** — retired the flat `SYNC_FRESH_MIN = 45` (minutes) guess;
     each wearable now earns its glow from its OWN `stale_hours` window. Old
     `.sync-dot.is-fresh` / `syncPulse` CSS removed (superseded).
  2. **`/data/` (`/method/pipeline/`) source-freshness board** — each row's "last
     update" cell now renders through the primitive.
  3. **The `.provenance` design-system kit** (`DESIGN_SYSTEM_V5.md` — documented
     with example markup weeks ago, **never actually adopted anywhere**) — this is
     its first real use, on the pipeline board's per-row byline.

## Verification

- `python3 -m pytest tests/` — 3620 passed (updated `test_last_sync.py`'s
  `test_frontend_ticks_and_earns_the_glow` for the retired mechanism; added
  `tests/test_freshness_pulse_589.py`, 4 new test functions).
- **The unit test extracts and drives the ACTUAL shipped `freshWindowOk()`** out of
  `motion.js` (fenced by `// FRESH_WINDOW_OK_START/END` sentinel comments) via Node,
  rather than re-implementing the predicate in Python — a regression in the real
  file fails the test. Covers window edges, ±60s clock-skew grace, and fail-closed
  bad input (null/NaN/zero/negative window).
- `black` / `flake8` / `ruff` / `node --check --input-type=module` clean on every
  touched file.
- Local Playwright + route-mocked render QA (serve `site/` over `http.server`,
  `service_workers="block"`, catch-all `**/api/**` route first): verified `.fr-live`
  toggles correctly per real timestamp on both the cockpit sync line and the
  pipeline board, and that `reduced_motion="reduce"` keeps `animationName: none`
  while the ember color state (`rgb(163, 78, 19)`) still applies.
- Re-verified live post-deploy with a real browser against production data: 3
  cockpit sources pulsing (fresh), 1 (Withings, 9 days old vs its 7-day window)
  correctly motionless-stale; pipeline board rows the same pattern.

## Deploy record

- 1 site-api deploy (`deploy/deploy_site_api.sh /api/source_freshness`) — full
  `web/` package; layer already v114, **no re-attach needed**. Verified 200 +
  new fields live on both `/api/last_sync` and `/api/source_freshness`.
- 1 static-site deploy (`sync_site_to_s3.sh`) for the CSS/JS + the build-log beat.
  `version.json` build == HEAD each time. **Smoke 67/67** after both deploys.
- **No layer bump, no CDK, no MCP.**

## Gotchas

- **The `.provenance` kit had been fully speced in `DESIGN_SYSTEM_V5.md` for weeks
  with example markup, and a grep across the whole repo found zero live usages of
  it** — a documented design-system primitive is not the same as an adopted one.
  Worth periodically grepping the design doc's own component list against the
  actual site to catch this drift earlier next time.
- **Worktree merge surprise:** running `gh pr merge --squash --delete-branch` from
  inside a worktree that had the feature branch checked out switched THAT
  worktree's checkout to `main` (to safely delete the local feature branch) —
  which then blocked the PRIMARY repo directory from checking out `main` itself
  (`git checkout main` → "already used by worktree"). Turned out fine here because
  the worktree ended up sitting exactly at `origin/main` HEAD post-merge, so I
  deployed from there instead of the primary directory. General lesson: after
  `gh pr merge --delete-branch` run from a worktree, check `git worktree list`
  before assuming which checkout now owns `main`.
- **Discovered mid-session:** the primary shared working directory
  (`/Users/matthewwalker/Documents/Claude/life-platform`) was checked out on
  `feat/408-pr-render-accuracy-gate` with uncommitted changes — a concurrent
  agent's in-progress work on #408, not mine. Left completely untouched; did all
  #589 work in an isolated `.claude/worktrees/issue-589` worktree instead
  (removed after merge+deploy, after checking out the two harmless `site/feed.xml`
  / `site/rss.xml` regen-diffs that `sync_site_to_s3.sh` always leaves behind).

## State at close

- `main` == `origin/main`, #589 closed (PR #705 merged + deployed + live-verified).
- The primary repo directory still has #408's concurrent, uncommitted
  work-in-progress on `feat/408-pr-render-accuracy-gate` — **not resolved by this
  session, not mine to touch.** Whoever owns that session should find it as they
  left it.
- **GitHub Pages still enabled + public** (carried from prior sessions, unactioned).

## Next session

- **#590** (home cinematic — constellation v2 + waveform onto `data-cpts`) is still
  the next motion-epic item, deferred by Matthew's call in the prior session. See
  `handovers/HANDOVER_2026-07-05_MotionEpicWrap.md` for its full scope + the open
  data question (pillar-pair correlation edge-weight data isn't in `/api/character`
  today) — unchanged by this session.
- The `.provenance` kit now has one real adopter; if a future session wants to make
  good on "use it under every readout and chart" (DESIGN_SYSTEM_V5's own words),
  #589's pattern (byline + `data-fresh-ts`/`-window` when a real timestamp exists)
  is the template.
- Batch-#3 leftovers carried forward unchanged: **#408** (in progress concurrently,
  see above) · **#409** batch-price content AI (touches `bedrock_client`/`ai_calls`
  — layer bump + full consumer redeploy).
