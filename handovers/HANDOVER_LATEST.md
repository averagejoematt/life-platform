# HANDOVER — Next-milestone pay-down: 8 issues shipped end-to-end, scorecard off 0-graded-ever, CI un-redded — 2026-07-07

> Instruction: "Look at open issues list and efficiently pay down as much as you can from
> the ready to work high valued items" → mid-session: "i authorize the merges and deploys -
> ship it all." Now milestone was empty; picks came from Next per the prior handover.
> Plan: 6 parallel worktree subagents (#804 opus, #803 sonnet, #808 opus, #813 fable,
> #735 sonnet, #769 sonnet) + driver-inline #736/#796.

## What shipped (8 issues, PRs #858–#865; all MERGED + DEPLOYED + LIVE-VERIFIED)

- **#813** (PR #864, fable) — **the scorecard graded for the first time ever.** Root
  cause was a *duplicate grader*: `coach_computation_engine` Component 6 ran 15 min
  before the real evaluator daily and terminally wrote `inconclusive` at the un-clamped
  window, so `coach_prediction_evaluator` never saw an elapsed prediction. Plus 4 more
  compounding defects (pre-C-3 `threshold=None` specs, `SUBDOMAIN_TO_DOMAIN` gaps
  silently tripling sleep windows, sleep metrics mapped to whoop instead of eightsleep,
  predictions emitted over dead sources — now write-time liveness-gated, and the
  extraction allowlist is derived from the registry so it can't drift). Post-deploy live
  run: **decided 17 (2 confirmed / 15 refuted), days_since_last_decided 999 → 0**, ~88
  genuinely decidable through late July; the baked scorecard proof now reads
  "17 graded · 12% hit-rate". Full triage table in the PR + #813 comment.
- **#804** (PR #860) — /coaching/ static-rendered via the #855 pattern: integrator
  weekly priority + each coach's `position_summary` from `/api/coaching-dashboard`
  baked into `<noscript>` on /coaching/ + /coaching/read/ (`v4_proof.load_coaching_read`,
  ADR-104 absent-coach omission, committed-snapshot offline fallback), regenerated
  every deploy by `sync_site_to_s3.sh` → `v4_build_coaching.py`.
- **#803** (PR #863) — chronicle: Week 2 was generated 06-24, sat unapproved
  (PREVIEW_MODE), then was deleted by the 06-27/28 privacy purge; current week blocked
  since 07-03 by the fail-closed privacy gate (Elena cited "paul conti" — no real-people
  rule existed). Fixes: REAL-PEOPLE prompt guardrail, `_set_chronicle_pending()` marker
  (mirrors the podcast pending fix), `_week_gap_note()` baked into the chronicle
  noscript ("Week 2 — no installment ran…" is LIVE). Watch the 07-08 Wednesday run.
- **#808** (PR #861) — `scripts/ai_spend_attribution.py` over the existing
  `LifePlatform/AI` EMF (prices imported from bedrock_client; reconciles vs AWS/Bedrock
  authoritative). Live June ranking confirms Haiku $24.47 > Sonnet $15.52 and the Haiku
  dollars hide INSIDE multi-model features — **#409 batch pricing should target the
  coach pipeline + daily-brief extraction passes**, not the tiny structured tools.
  Per-model EMF dimension deliberately NOT added (recurring cost — Matthew's call).
- **#769** (PR #862) — evening ritual C-floor (ADR-124): HMAC-signed one-tap links in
  `evening_nudge_lambda` (new `lambdas/ritual_link.py`, secret
  `life-platform/ritual-token-secret` — created live this session) → `/api/ritual_log`
  (last-tap-wins per metric, DDB-rate-limited) + aggregate-only `/api/fulfillment_ritual`
  (nulls for dark days). 33 tests.
- **#735** (PR #865) — `/method/verify/`: cross-device disagreement published via new
  `/api/device_agreement` (live: 1,193 overlapping nights, 54.1% RHR agreement — the
  imperfection IS the credibility), scrubbed raw samples, honest "not yet linked" device
  profiles (real URLs need Matthew — TODO(#735) markers in `evidence_meta.js`).
- **#736** (PR #858, driver) — build beat is now a wrap-GATE: beat or explicit
  `**Build beat:** none — <reason>` line in every handover; wrap.md + checklist + CLAUDE.md.
- **#796** (PR #859, driver) — `.claude/agents/`: worktree-implementer / finding-verifier
  / render-qa, with the recurring incident classes baked into the prompts.

## Repairs made en route (not from the issue list)

- **CI had been red since yesterday's #857**: unsorted imports in canary/qa_smoke
  lambdas failed the ruff gate, which MASKED a daily-brief golden failure behind it.
  Fixed imports; then defused the golden itself — `html_builder`'s BoD confidence badge
  computes `days_of_data` from wall-clock now, so the "frozen" golden flipped
  LOW→MEDIUM the day the real experiment crossed n=30. Fix: fixture
  `journey_start_date` pinned to 2024-06-08 (badge permanently HIGH → deterministic).
  **CI/CD on main is green again** (first full green since 07-07 ~17:00).
- **#803's gap note initially didn't ship**: `sync_site_to_s3.sh` never ran
  `v4_build_dispatches.py`. Wired it in (best-effort pattern like the other builders);
  live-verified after re-sync.

## Deploys (authorized in-session: "i authorize the merges and deploys - ship it all")

`cdk deploy --all` exit 0 (8/8 stacks; fleet code asset picks up shared
`measurable_metrics.py`) · `deploy_site_api.sh` (status 200) · `sync_site_to_s3.sh` ×2 ·
secret `life-platform/ritual-token-secret` created · one live
`coach-prediction-evaluator` invoke (17 decided). Verified: full suite locally **4011
passed** (4 pre-existing fails at merge time; the 2 golden ones then FIXED, remaining 2
are live-AWS-only: test_ddb_key_contracts, i16) · smoke **67/67** · visual QA **34/34,
0 failed, 5 warnings** · CI/CD green on main · version.json == deploy HEAD ·
live checks: /api/device_agreement 200 with real data, coach names in delivered
/coaching/ HTML, chronicle gap note live, /method/verify/ 200.

## Gotchas (this session)

- **The case-twin leak struck again** (#808's script appeared untracked in the MAIN
  tree): preserved to scratchpad, cleaned; the agent's PR carried the real copy.
- **A red lint gate masks unit-test failures for DAYS** (sequential CI gates): the
  golden drift was invisible until the ruff fix landed. After un-redding a gate, always
  re-check the next gate.
- **Golden tests must not depend on wall-clock now**: any fixture date used in a
  now-minus-date computation is a time bomb — pin it far past.
- **Worktree merge trains**: #860/#863 shared `v4_proof.py`; both-added-functions merge
  + `git reset --soft origin/main` linearize + force-push made the squash clean.
- **An agent wiring a builder into the BUILD script is not enough** — the deploy script
  must also RUN that builder (the #803 gap-note miss). Render-verify live after deploy.

## Build beat: 2026-07-08-scorecard-first-grades

## Next picks

- **Next milestone remainder:** #812 golden-harness generalization + harvest loop
  (fable, big) · #793 split site-api lambdas out of Operational (infra, attended) ·
  #740 essay (awaits Matthew's edit pass) · #734 audio debrief · #741 career artifact ·
  #739 surge-mode ceiling (needs Matthew to set $X) · #409 batch pricing — now
  correctly aimed by #861 at the coach pipeline + daily-brief extraction.
- **Watch:** 07-08 Wednesday chronicle run (privacy guardrail should clear the hold);
  evaluator daily runs (~71 more predictions decide through late July); first evening
  nudge with ritual links (needs `evening-nudge` env nothing — deployed).
- **Matthew:** /method/verify/ device-profile URLs (TODO markers) · per-model EMF
  dimension (recurring-cost decision) · #417 re-stamp timing/format · Ingestion/HAE
  deploy call · REVIEW_BUNDLE_2026-07-06.md untracked (commit or delete).

Prior session archived at `handovers/HANDOVER_2026-07-07_high-value-paydown.md`.
