# Handover — 2026-07-04 (second session) The Fable Next batch: #392 #387 #397 #396 #380

**All five open `model:fable` Next-milestone stories implemented, tested, and bundled as PR #453** (branch `feat/fable-next-392`, worktree `honesty-pair`, five commits — one per issue, each `Fixes #N`). Full suite **2,660 passed** (only the 5 known pre-existing failures: coaches_api ×4 + i16, identical on untouched main); black/ruff clean on CI scope; `cdk synth LifePlatformWeb` clean; content-policy scan PASS; 33 new tests. **⚠️ PR #453 is OPEN, NOT merged — the merge was permission-blocked as self-approval (the "implement the issues" ask didn't extend to merging my own unreviewed PR). Deploys are staged, not run (deploy-from-main).**

## What each story shipped

1. **#392 freshness split** — new canonical `lambdas/source_registry.py` (**new shared-layer module** → this PR's deploy includes a **layer bump to v97**). Behavioral-vs-infra classification + thresholds in one place; freshness_checker + `/api/source_freshness` + MCP `get_freshness_status` all derive from it (the MCP mirror still had food_delivery=90d, the pre-triage masking value). Withings/strava/macrofactor now behavioral → `slo-source-freshness` stops paging a quiet stretch; whoop-outage replay test proves real breakage still pages. `count_infra_stale()` extracted for testability.
2. **#387 ask grounding** — `_ask_fetch_computed_reads()` in `site_api_ai_lambda.py`: adaptive-mode verdict + factor reasons, momentum, improving/declining, canonical weight-rate + protein trio, what-changed 30d deltas, FDR correlations, presence — all fail-soft. Prompt: narrate-only (no arithmetic), what-drove answers from computed reads w/ correlative framing, never ask the reader for data; "19 data sources" now derived from the registry (11 live + 1 paused), coach preamble too.
3. **#397 ask loop** — CloudFront behavior `/board_answers/*` → S3GeneratedOrigin (was falling to site origin = the 404 that hid the whole payoff surface); `publish_board_answer.py` gains fail-closed `privacy_guard.assert_clean` on every published string; coaching qa tab shows honest feed state + kicker "you asked — the board answered". Private question queue stays non-public by design.
4. **#396 remediation agent** — report-first skeleton (file exists with all signals `untriaged` BEFORE the agent runs; prompt requires incremental bucket moves; emails render "Not triaged this run"); alarm-ack ledger `remediation-log/ack_ledger.json` (7d TTL, needs_human/stale conclusions carried forward); earn-or-shadow (28d auto window with 0 merged auto-fix-safe PRs → standing needs-human item with the exact SSM dial-back command; merged PR restarts the window). Safety invariant test untouched + green.
5. **#380 build log** — `/story/build/` section (Story app) fed by git-committed `site/story/build/beats.json`; session-end checklist `docs/content/BUILD_DISPATCH_CHECKLIST.md` wired into the CLAUDE.md wrap convention; format-enforced honesty (tests require honest_miss; privacy gate over every string; content-policy CI gate covers the feed). Seeded with the real ADR-104 beat. **Side catch:** the shell generator's nav was missing the #444 follow link — regen would have silently dropped it site-wide; template fixed (the stored-artifact-regen gotcha, again).

## Deploy sequence (STAGED — run from detached origin/main AFTER #453 merges)

1. `git checkout origin/main` (detached) + `rm -rf cdk/cdk.out`
2. **Layer dance → v97** (CONVENTIONS §1): `bash deploy/build_layer.sh` → `cd cdk && npx cdk deploy LifePlatformCore` → verify new version → bump `SHARED_LAYER_VERSION=97` in `cdk/stacks/constants.py` (tiny follow-up PR like #452) → deploy consumers: Compute, Email, Operational (ships freshness-checker + site-api-ai bundle), Mcp, Ingestion.
3. `npx cdk deploy LifePlatformWeb` — the `/board_answers/*` CloudFront behavior (distribution update, takes a few minutes).
4. `bash deploy/deploy_site_api.sh` — site_api_data (registry-derived freshness board).
5. `bash deploy/sync_site_to_s3.sh` — coaching.js, dispatches.js, story shells incl. `/story/build/`, beats.json.
6. Seed the empty feed: `printf '{"answers": []}' | aws s3 cp - s3://matthew-life-platform/generated/board_answers/answers.json --content-type application/json`
7. Verify: `slo-source-freshness` → OK within a day (next checker run emits StaleSourceCount=0); `curl https://averagejoematt.com/board_answers/answers.json` → 200; `/story/build/` renders the ADR-104 beat; `/api/ask` probe "what drove this morning's recovery?" cites computed reads; postflight 🟢.

## Gotchas / notes

- **source_registry.py is in the layer AND bundled** — CI layer-change detection covers it (ci/lambda_map.json updated; LV4 test green). Function-code copy shadows the layer copy harmlessly.
- The remediation changes are repo-side (merge = live at next scheduled run, no deploy); the ack ledger + earn marker are created lazily in S3 on first run.
- `remediation/` is NOT in CI's ruff/black scope (pre-existing unsorted imports on main) — don't chase style there.
- The `/api/board_ask` coaches now also see the derived source count; drivers were deliberately NOT added to board_ask (6 paid calls, scoped to #387's /api/ask).
- Prior session's outstanding item still stands: `python3 scripts/grounding_shadow_sweep.py --days 14` vs the 11/112 baseline after a few daily coach cycles.
