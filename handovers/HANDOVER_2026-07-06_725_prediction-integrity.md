# HANDOVER — #725 code-stamp prediction metadata + layer-drift reconcile — 2026-07-06

> Matthew authorized **all deploys and merges** for this session ("do it" / "I authorize you
> to do all deploys and merges"). Single-threaded on `main` (no concurrent session, no worktree
> needed). Started from a question about the home constellation, pivoted into the R21 backlog's
> #1 move, shipped it end-to-end, and greened main.

## What shipped (merged + deployed + REAL-DATA-verified)

### #725 — code-stamp prediction metadata (epic #715, R21's single highest-leverage move)
PR **#761** → main `6b4457de`; layer-bump chore → main `79b3b4aa`. Layer **v116**.

**The defect (R21):** `intelligence_common.extract_thread_from_narrative` asked the LLM to emit
`prediction_id` + `target_date` verbatim (`:1537`). The live ledger held 2024/2025-dated,
duplicate, past-target predictions — **88 pending, 0 ever graded** — an ADR-106 ("only code
ships") violation at the exact point the platform's central claim depends on. The writer
(`ai-expert-analyzer`, cron 6am PT daily) was actively minting fresh corrupt records.

**The fix — `intelligence_common.stamp_thread_predictions()`:**
- Strips `prediction_id`/`target_date` from the LLM JSON schema + an explicit prompt rule. Model
  writes claim text / confidence / optional metric / optional natural timeframe only.
- Code stamps `prediction_id = pred_{today}_{semantic-slug}` (same slug regex as the canonical
  `coach_state_updater.py` COACH# path) + a **strictly-future** `target_date = today + window`
  (timeframe→days, default 14) → no metric-bearing record is ungradeable-by-construction.
- **Carry-forward dedup:** an open prior claim with the same `semantic_key` is updated in place
  (original id + fixed deadline preserved, `reaffirmed_on` stamped) instead of minting a fresh
  `pred_2025…` duplicate daily — the behavior behind the 88 inflation.
- Dropped the dated "I'll have more to say around {target_date}" promise from ORIENTATION_VOICE
  (`:187`) — an untracked date-claim; its code-derived plumbing removed.
- Tests: `tests/test_prediction_metadata_stamp_725.py` (9 cases). Full related sweep (85) green.

**THE VERIFICATION (the #412 "drive the real flow" lesson, applied):** unit tests + a healthy
deploy were NOT taken as proof. Invoked `ai-expert-analyzer` live on v116 with
`{"expert":"training"}` → the fresh `coach_thread#training#2026-07-06` record came out
**`pred_20260706_matthew_s_system_will_fracture_when_exte`, target_date `2026-07-20`,
`semantic_key` set** — vs the pre-fix garbage still visible in older entries
(`pred_20240621_nervous_system_fracture`, `pred_20250000_*`, null/past target dates,
`semantic_key=None`). The `{"expert":X}` payload runs one expert (~1 Bedrock call, cents).

### Layer-drift reconcile (the actual main-CI red — NOT #724)
`Plan deployments → Verify layer version consistency` was failing: **v115 was published
2026-07-06 (PR #711/#417) but never attached — all 15 consumers stranded on v114.** Shipping
#725 (a layer module) needed a fresh layer anyway → `build_layer.sh` → `cdk deploy
LifePlatformCore` (publish v116) → `cdk deploy LifePlatformCompute LifePlatformEmail` (attach).
**16/16 consumers now on v116.** Added `ai-expert-analyzer` (a REAL layer consumer that was
**missing** from `ci/lambda_map.json` — hence not tracked by the drift check) → now 16 in the map.

### #724 closed
Its ruff import-sort red was already fixed by #759. Closed with a note pointing at the real
(drift) cause so the CI-health thread isn't misled.

### Main CI is GREEN
Run `79b3b4aa`: Lint ✓ · Unit ✓ · Deploy-critical ✓ · **Plan (layer check) ✓**. Deploy is
skipped pending Matthew's prod approval (by design) — but the targeted layer+consumer deploy
already went out directly via CLI, so #725 is LIVE now.

## Side investigation (Matthew's opening question) — home constellation "no lines"
The `/` hero constellation showed circles, no edges. **Verdict: design is right, code is healthy,
it was transient.** The #590 design DOES specify co-movement edges (ember solid = rise/fall
together, dashed = trade-off, width=|r|, opacity=significance). `/api/pillar_coupling` returns
**15 real edges right now** (`honest_null:false`, n=54–60). `story.js` `drawConstellation`
renders them correctly (NODES keys match API pillar keys). The screenshot's all-dashed circles =
`.node.quiet` (uncoupled) style → drawConstellation got zero edges at that moment (transient
fetch hiccup / pre-threshold data). A reload shows the 15 lines. **Latent item (not filed):** a
transient `/api/pillar_coupling` fetch-fail renders identically to honest "no couplings yet" — a
small ADR-104 honesty gap worth a guard (distinguish fetch-fail from genuine empty).

## State at close
- `main` == origin (`79b3b4aa`); layer **v116**; 16/16 consumers current; main CI green.
- Untracked `docs/reviews/R21_BACKLOG.md` present (someone else's review record — left alone).
- Worktrees: `main` + `docs/uplevel-handover` (unchanged).
- Uncommitted `.claude/settings.local.json` (session tool-permission churn — not committed).

## Next (Session A remainder → Session B)
- **#726 — void the legacy prediction partition** (epic #715; depends on #725, now met). Sharper
  than the issue assumed: there are TWO prediction stores, and the newer `COACH#/PREDICTION#`
  one (written by `coach_state_updater.py:1137`, read by evaluator/site/track-record) is
  **already code-stamped correctly**. So #726 = tombstone the legacy `coach_thread#` corrupt
  predictions (cycle-stamp per ADR-077, don't delete), repoint MCP `get_predictions` → `COACH#`,
  assert MCP + `site_api_coach.py` read one store. **This mutates prod prediction data — confirm
  before writing tombstones.** Note the odd legacy key: pk=`USER#matthew`, source in the SK.
- Then **Session B = epic #716** proof-visible-to-the-skim: **#730** static-render the proof
  surfaces (scorecard/chronicle/key numbers into served HTML), **#733** permalink unification
  (one URL scheme, posts in sitemap, RSS→permalinks, subscribe CTA). Both `model:opus`, Now.
- Budget pair (Next): **#738** hash-and-reuse unchanged generation briefs (biggest recurring
  saving), **#737** re-order budget tiers (dev AI pauses before reader-facing).
- Hygiene surfaced: audit `ci/lambda_map.json` for OTHER missing layer consumers (a #342 item).

Refs: [[r21-prediction-integrity]] (memory), `docs/reviews/R21_BACKLOG.md` (review record),
`docs/CONVENTIONS.md` §1 (layer sequence).
