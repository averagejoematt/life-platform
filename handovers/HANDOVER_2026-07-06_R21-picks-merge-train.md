# HANDOVER — Matthew's three picks + the R21 merge train — 2026-07-06

> One instruction: **"yes do it all."** All three held decisions were made in-session,
> all five fable-batch PRs merged, layer v117 published + attached fleet-wide, the first
> pre-registered experiment registered LIVE through the real MCP endpoint, and the build
> beat published. Single-threaded on `main`. Main CI **green** (after one stale-race re-run).

## The three decisions (all Matthew's, recorded on the issues)

1. **Finish line (#732) = Option A** — *185 lbs held for 90 consecutive days, or the
   experiment failed.* **"Sixteen attempts" confirmed by Matthew** (repo-unverifiable;
   his word is the source). Live on `/` via PR #764.
2. **First experiment (#728) = Option B** — Matthew overrode the A (sleep-window)
   recommendation mid-train: **daily zone-2 floor (≥30 min) → recovery_score**,
   min_effect +5, baseline 14d / washout 3d / 28 days, stopping rule = full 28 days,
   abort only on ACWR > 1.3 × 3 consecutive days (recorded).
3. **Fulfillment channel (#745) = A primary + C floor**, posture confirmed as proposed —
   ADR-124 flipped **Accepted** (commit `d144881c` on the PR branch before merge).
   B (passive proxies) rejected as primary. The C one-tap two-scalar story filed as
   **#769** (epic #718, Next, model:sonnet).

## Merge train (order held: #765 → #763; #764 after the pick)

`8953a6a3` #765 prereg mechanism · `e4bde673` #763 /method/ trust doc · `81fe3065` #764
protagonist fold · `d3b80cf4` #762 ADR-124 (Accepted content; squash title still says
"Proposed" — the ADR text is the truth) · `97a3f614` #766 org-chart essay draft.
Then: `7493f495` layer v117 bump · `060bbcf3` docs-sync test_count · `d7071748` + `6455ed62`
rss/feed · `73893ab2` the build beat.

## Deploy (authorized: "do it all")

- **Layer v117** (`experiment_design.stopping_rule` + prereg artifact): build →
  `cdk deploy LifePlatformCore` → verified 117 live → **LifePlatformMcp + LifePlatformWeb**
  (MCP IAM prereg grant + CF `/experiments/prereg/*` behavior) → **LifePlatformCompute +
  LifePlatformEmail** (the 16 tracked consumers). **16/16 + mcp on v117.**
- **site-api**: `deploy/deploy_site_api.sh /api/experiments` — the script now
  **auto-attaches the layer itself** ("was: 116 → 117"); the manual-re-attach memory is
  softened (script handles it; watch for it on other paths).
- **MCP code ships via `cdk deploy LifePlatformMcp`** — no manual zip (the stack bundles
  mcp/ + stages reading/; confirmed again this session).
- Site synced twice (fold/method/evidence_discovery, then the beat). `/version.json`
  fresh on each sync.
- **The 29 Ingestion/Operational functions stay on v115 DELIBERATELY** (unchanged —
  still gated on Matthew for the HAE-staged Ingestion stack; reconcile WITH him).

## The experiment is LIVE (the session's flagship proof)

`create_experiment` driven through the deployed MCP FunctionURL (lp_-HMAC bearer) →
**`daily-zone-2-floor-30-min_2026-07-06`**, `pre_registered_at 2026-07-06T04:18:55`,
start **2026-07-06** (registered before day 1 — real before-the-results proof).
Frozen artifact live via CloudFront:
`https://averagejoematt.com/experiments/prereg/daily-zone-2-floor-30-min_2026-07-06.json`
`/api/experiments` carries the design + prereg URL; card renders "frozen artifact ↗".

## Gotchas this session

- **CI layer-check raced the deploy:** the v117 constant push fired Plan at 04:11, the
  Compute/Email attach landed ~04:15 → 16 stale ❌ on a correct in-flight deploy. Fix =
  `gh run rerun --failed` → green. A gate that reds on correct in-flight work trains
  people to ignore it (worth a story if it recurs).
- **`cdk diff` prints to stderr** — `2>/dev/null` eats the whole diff; filter with `2>&1`.
- **Pre-commit doc-sync mutates files it doesn't stage** (`site_api_common.py`
  test_count) — check `git status` after every commit or the next deploy ships a dirty tree.

## Issue state

#728 #732 #745 CLOSED (decision records on each) · #731 auto-closed · **#740 OPEN** —
draft merged, awaits **Matthew's edit pass** · **#769 NEW** (C one-tap path) ·
#748 still hard-gated on ≥4 lived weeks (clock starts when fulfillment data flows).

## Next

- **#727** liveness heartbeat (E1 remainder) · Session B epic #716 (#730/#733) ·
  budget pair #738/#737 · #740 edit pass (Matthew) · #769 one-tap path ·
  reconcile the 29 v115 functions WITH Matthew (HAE gate).
- Zone-2 experiment: day 1 is 2026-07-06 — the Whoop stream grades it passively;
  nothing to operate.
