# HANDOVER — the fable batch + authorized carry-overs (#726 + the #725 beat) — 2026-07-06

> TWO halves. **First half** (fable batch): "all model:fable issues, efficiently without
> sacrificing quality" — no deploy/merge authorization, so 5 PRs opened and held (below).
> **Second half**: Matthew said "take care of that" for the two carry-overs — **#726 shipped,
> merged, deployed, prod-migrated, LIVE-verified** and the **#725 build beat is published**.
> Single-threaded on `main`; branches per story.

## SECOND HALF — shipped under explicit authorization

### #726 — one prediction store (PR #767 → main `7474cf90`, deployed + migrated + live-verified)
- `get_predictions` repointed: legacy `SOURCE#coach_thread#` embedded arrays → canonical
  `COACH#{coach}_coach/PREDICTION#` (the store the evaluator grades and `/api/predictions`
  serves); track-record-style id normalization; registry docstring corrected; status enum
  +inconclusive/expired. Tests `tests/test_predictions_one_store_726.py` (7) incl. AST-level
  one-store assertions on BOTH readers.
- **Prod migration executed:** `deploy/void_legacy_predictions_726.py --apply` → **712 corrupt
  embedded predictions voided across 345 thread records** (705 pending; hallucinated
  `pred_2024/2025` IDs, past/null targets — the FULL corruption; R21's "88" was just the old
  tool's visible slice). ADR-077 tombstone: `predictions_voided_726` + voided_at/by/`cycle=4`;
  clean #725-stamped records untouched (spot-checked `training#2026-07-06`); idempotent
  (re-run: 0 new / 345 already).
- **Live verification (the real flow):** drove the deployed MCP FunctionURL with the
  `lp_`-prefixed HMAC bearer (`mcp/handler.py:388` — the `lp_` prefix is the gotcha) →
  `get_predictions` returned **357 canonical records (302 pending / 55 inconclusive — the
  evaluator IS grading)**, all code-stamped 2026 IDs. Deploy: `cdk deploy LifePlatformMcp`
  (diff was exactly code-hash + layer 115→116; the raw-zip path is NOT needed — the stack
  bundles mcp/ + stages reading/).

### #725 build beat — published (PR #768 → main `2f634e03`, site synced, verified live)
"The AI no longer writes its own report card" on `/story/build/` — shipped/gotcha/honest-miss
per the #380 checklist, content-policy scan PASS, `/version.json == 2f634e03`.

### Layer-truth discovered while deploying (the "16/16 on v116" was wrong)
The live sweep found **three tiers**: (1) `life-platform-mcp` + `life-platform-site-api` were
still on **v115** (the two special-path consumers the drift check can't see) — **both fixed**
(MCP via the #726 stack deploy; site-api via manual re-attach per the standing runbook memory);
(2) `life-platform-freshness-checker` v115 — caught by the post-deploy I1/I2/I5 integration
check (redded the run), **fixed + job re-run**; (3) **29 functions across the Ingestion +
Operational stacks remain on v115** — functionally harmless (v116 only changed
`intelligence_common`, which none of them import) and **deliberately NOT fixed**: the clean fix
is a stack deploy, but `LifePlatformIngestion` carries the staged HAE change that is
**explicitly gated on Matthew's call** (session-17 memory). → Next session: the
`ci/lambda_map.json` consumer audit (#342-adjacent), then reconcile the 29 with Matthew.

---

## FIRST HALF — the fable batch (5 PRs open, held on the batched ask)

## What was built (5 open PRs, 0 merged)

| Story | PR | State | What it is |
|---|---|---|---|
| #745 channel decision | **#762** | ready (Refs) | **ADR-124 (Proposed)** in DECISIONS.md — 3 capture channels graded friction/honesty/privacy; recommends A (StateOfMind→HAE, build≈0) + C floor (two-scalar evening ritual); B rejected as primary. **Bad-week publication posture proposed BEFORE data flows** (aggregate always publishes; labels never; dark = honest absence; no retro-deletion). |
| #731 /method/ trust doc | **#763** | ready (**Fixes #731**) | The static trust contract — ten sections of `.prose` HTML rendered before the evidence.js explorer (new `.trust-doc` in tokens.css): number-gate (+ the published 11/112 baseline), blocking quality gate, code-stamped predictions, pre-registration w/ stopping rules, falsification conditions, no-cherry-picking, **the #725 incident disclosed in full**, N=1 limits, never-published list, the $75 ceiling. Playwright-verified JS-off (6.2k chars static), JS-on explorer intact, 390px overflow 0. **Merge with/after #765** — its pre-registration section describes #728's mechanism. |
| #732 protagonist fold | **#764** | **HOLD** (Refs) | `.hero-who` + `.hero-finish` static in the hero: Matthew named, the sixteen-attempts arc, 315→185 stakes, and the provisional finish line ("185 lbs held 90 consecutive days — or this experiment failed", linking /method/survival/). **Two Matthew confirmations before merge:** finish-line option (A maintenance / B date / C two-stage) and the "sixteen" count (R21-sourced, NOT verifiable in repo — fallback phrasing ready). |
| #728 pre-registration | **#765** | ready (Refs) | The mechanism: `stopping_rule` REQUIRED in `experiment_design.validate_design` (**layer module → v117 bump on deploy**); `create_experiment` freezes a public timestamped artifact to `generated/experiments/prereg/{id}.json` (fail-soft + honest warning); CF behavior `/experiments/prereg/*`→S3GeneratedOrigin (no clash with the exact-path `/experiments/` redirect); `mcp_server()` PutObject on that prefix only; `/api/experiments` passes `pre_registration_url`; card renders "frozen artifact ↗" + stopping rule. Tests: 4 new + stopping-rule cases; sweep 106 green; synth clean, **both changes verified in synthesized templates**. 3 candidate designs commented on the issue (A = fixed sleep window 23:00–07:00, `sleep_duration_hours` higher ≥0.5h, 14d baseline/2d washout/21d, full-run stopping rule — recommended; passive, survives quiet logging weeks). |
| #740 org-chart essay | **#766** | ready (Refs) | `docs/content/ESSAY_ORG_CHART_OF_ONE.md` — full draft + talk outline + ranked venue shortlist (own site → HN → AI Engineer CFP → podcasts → LeadDev). Failures ARE the spine (#408 squash-stomp, #725 constitution violation, 47.8% green-tests-lied, lead-list rule). Receipt index appended; 2 `[CONFIRM]` flags (the "~50 stories/3d" self-report). NB: the "case-insensitive macOS" worktree framing was NOT verifiable in-repo; the essay uses the documented squash-inheritance mechanism. |
| #748 fulfillment story | — | **blocked** | Commented gate status: needs the #745 decision, then ≥4 flowing weeks incl. ≥1 rough patch. Earliest start ≈ pick + 4–5 weeks. |

## The batched ask (Matthew — one numbered list)
1. **#732 finish line:** A (185 held 90d — drafted/recommended) / B (target+date) / C (two-stage)? And confirm **"sixteen"** or take the count-free phrasing.
2. **#728 first experiment:** A sleep-window (recommended) / B zone-2→recovery / C protein (not recommended first)? One `create_experiment` call registers it live post-deploy.
3. **#745 channel:** A / A+C (recommended) / other — and confirm the bad-week posture in ADR-124 (it flips Proposed→Accepted).
4. **Merges + deploys** (all held): merge order #765 → #763 (+#764 after decision 1; #762/#766 anytime). Deploy: layer v117 rebuild→publish→attach (CONVENTIONS §1; `rm -rf cdk.out` first), `cdk deploy LifePlatformWeb LifePlatformMcp`, MCP zip (stage `lambdas/reading/`!), `deploy_site_api.sh`, `sync_site_to_s3.sh`.

## State at close
- `main` == origin == **live** (`/version.json` = `2f634e03`); #726 + the beat merged; PRs #762–#766 still open, checks green, held on the ask above.
- Layer: constants v116; **53 functions on v116** (incl. mcp, site-api, freshness-checker — all reconciled this session); **29 Ingestion/Operational functions on v115, deliberately left** (see second-half notes — LifePlatformIngestion deploy is gated on Matthew's staged-HAE call).
- Legacy prediction partition: **voided (712/345, cycle-stamped)**; canonical store serving 357 records via MCP + site. #726 CLOSED by the merge; **E1 remainder = #727** (liveness heartbeat).
- Pre-existing `stash@{0} "On main: session-local"` + untracked `docs/reviews/R21_BACKLOG.md` — left alone.
- Next session: whatever subset of the ask Matthew approves (merge order #765→#763; #764 after the finish-line pick) · #727 · Session B epic #716 (#730 static proof render / #733 permalinks) · the `ci/lambda_map.json` consumer audit + the 29-straggler reconcile.
