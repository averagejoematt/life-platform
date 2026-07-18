# HANDOVER — Next-milestone remediation slice 2: 10 /fullreview issues merged + DEPLOYED + verified live — 2026-07-18

> Instruction thread: continuing the /fullreview remediation backlog. Driver re-granted BOTH
> authorities in the fresh (post-/clear) context: "I approve — you do all the merges (squash +
> delete-branch)… you handle all deploys this session too — fleet/site-api/cdk/CloudFront as
> needed, verify each live. Do NOT blind-run live-DDB history backfills (#1266, #1265 are still
> mine)." Ran three disjoint-file `worktree-implementer` batches, verified every diff, merged
> 10 issues across 9 PRs, deployed everything, and verified each reader surface live.

## What shipped — 10 issues CLOSED across 9 PRs, all MERGED + DEPLOYED + VERIFIED LIVE

All via `worktree-implementer` agents in isolated worktrees; each carried a **non-vacuous**
regression guard (proven to fail without the fix), black/ruff clean, full offline suite green,
`Fixes #N`. I verified every diff against the issue before merge; all merges CLEAN (file-disjoint).

**Batch A (4 disjoint files):**
| PR | Issue | Fix |
|----|-------|-----|
| #1278 | #1211 | off-palette raw hex (`#0ea5e9` lead-coach, `#16a34a` vice-hold) → `var(--ember)`; new raw-hex gate in `check_css_tokens.py` (comment-strip + `hex-ok:` sanction) |
| #1280 | #1226 | `/api/coaching-dashboard` stamps `analysis_generated_at`; coaching.js renders an "as of Jul 17" kicker on the digest cards (completes #787); deterministic `check_vitals_freshness` in reader_truth_qa |
| #1281 | #1225 | hero weight row reconciles (round to 1 decimal everywhere → 315.6, delta from displayed values); trend copy gated on ≥2 weigh-ins ("since the start — one weigh-in so far"); "to goal"→"progress" + real U+2212 minus; qa_smoke `assess_hero_weight` |
| #1279 | #1229 | two CloudWatch alarms (alert-digest Errors + queue-age, both URGENT-routed) in monitoring_stack; AST guard `test_i23` + wired into ci-cd's post-deploy integration job |

**Batch B (3 disjoint):**
| PR | Issue | Fix |
|----|-------|-----|
| #1282 | #1204 | remediation `aged_alarm_escalations()` — deterministic backstop surfacing any alarm in ALARM >72h as a named needs-human line (fires even if the LLM turn-budget burns out) |
| #1283 | #1212 | css token gate → 7 consumer sheets (tokens.css stays the allowlist); §10.1 nine-number breakpoint invariant enforced; rogue `520px`→`600px`; mind.css `#1d1810`→`var(--shelf-spine-deep)` |
| #1284 | #1224 | new `text_utils.truncate_at_word` (word boundary + ellipsis, no cut when short); applied at the 3 generator sites (chronicle excerpt, coaching position_summary, thread fallback); mid-word reader-truth guard |

**Batch C (2 disjoint):**
| PR | Issue | Fix |
|----|-------|-----|
| #1285 | #1214+#1213 | home waveform: below-threshold spread now renders near-equal heights (no fake ~86% collapse) + `mid` muted tier (never the false `up` ember); pure `barHeight`/`barTier` extracted; node-run guards |
| #1286 | #1208 | grounding band-adjective class: maps `recovery_pct` to the Whoop band, flags a top-band superlative ("strong recovery") on a sub-green value within a proximity window; golden-surface fixture |

## Deploys — ALL DONE + verified live
| Deploy | Covers | Verified |
|--------|--------|----------|
| `deploy_site_api.sh` (batch A) | #1226 site_api_lambda, #1225 site_api_vitals | `/api/journey` 315.6 reconciles, weighin_count=1; `/api/coaching-dashboard` analysis_generated_at populated |
| `deploy_lambda.sh life-platform-qa-smoke` | #1225 nightly check | deployed |
| `cdk deploy LifePlatformMonitoring` | #1229 | both alarms CREATE_COMPLETE (Plan diff = +2 alarms, no IAM) |
| **`sync_site_to_s3.sh` ×2** | #1211/#1226/#1225 site JS+CSS (batch A), then #1212 CSS + #1285 waveform JS (batch B/C) | render-QA PASS both rounds; smoke 82/0 |
| `deploy_fleet.sh` ×2 (95/0/0 each) | #1224 new `text_utils` shared module (chronicle/intelligence/site-api), #1208 `grounded_generation` (ai-expert-analyzer) | fleet reports 95 updated 0 failed |
| CloudFront invalidations | `/api/*` + full-site ×2 | version.json rolled to each HEAD |

**Reader surfaces verified live by render-QA:** home hero ("up 1.6 lb since the start — one
weigh-in so far, Jul 13", "progress" caption + U+2212, 315.6); coaching cards ("AS OF JUL 17"
on all 5); home waveform (4 scored bars at 66% near-equal, all `bar mid`, zero `up`).

## TWO HARD OPERATIONAL TRAPS HIT THIS SESSION (both now memories)
1. **Site auto-deploy silently skipped** ([[reference_site_deploy_superseded_skip]] /
   `reference_site_deploy_superseded_skip.md`): after each site-PR merge, the reconcile-bot
   commit landed seconds later → `site-deploy.yml`'s "Superseded-run check" SKIPPED the deploy
   (all steps skipped, job still "success") → the reconcile commit touches no `site/**` so
   re-triggers nothing → **the site NEVER deployed**. render-QA caught it (`version.json` build
   predated the fix commits, hashed module names unchanged). **Fix reflex: after any site-PR
   batch, do a MANUAL `bash deploy/sync_site_to_s3.sh` — never trust a green "Site deploy" run
   when a reconcile commit followed.** Then `smoke_test_site.sh` (manual sync bypasses the gates).
2. **PLATFORM_FACTS maintained-literal drift** ([[reference_platform_facts_maintained_literal]]):
   #1229's alarm count 67→69 red `test_platform_stats_truth::test_alarms_and_sources_share_the_
   maintained_fact` in the Unit Tests lane — the hand-maintained `PLATFORM_FACTS["alarm_count"]`
   literal in `sync_doc_metadata.py` stayed 67 while the CDK discoverer + reconciled docs read 69.
   **Docs CI `--check` was GREEN** (docs==discovered) so it didn't catch it; only the unit test
   (static literal) did. Fixed by hand-bumping the literal (commit `0987a5d1`). **Reflex: any PR
   changing the CDK alarm/lambda COUNT must also bump `PLATFORM_FACTS` in sync_doc_metadata.py.**

## Verification / gotchas
- **Main health:** after fixing #1229's alarm-fact drift, the full offline suite is GREEN locally
  (5253 passed, was 1 failed). CI/CD `43c7711f` (batch-C merge, pre-fix) failed ONLY on that one
  truth test; **Plan deployments = SUCCESS** (R8-ST6 cleared — no new IAM this session, prior
  #1263 IAM already deployed). A CI/CD run on the fix commit `0987a5d1` was still queued at wrap
  (a Monitor is watching it) — expected green since the only failure is fixed. Confirm the
  `0987a5d1` CI/CD Unit Tests conclusion.
- **Reconcile bot raced me twice** — it committed `chore(reconcile) … [skip-reconcile]` after
  batch B and batch C before my manual reconcile push; I `reset --hard origin/main` to take the
  bot's version (no double-commit). Standard.
- **Stored-artifact fixes clean up on regen (not instantly):** #1224 coaching `position_summary`
  — the live serve-time fallback is already word-boundary (verified: "…architecture is…"); a
  stored mid-word `position_summary` would clean up on the next coach-opinion regen. #1208's band
  gate is deployed on ai-expert-analyzer; the live `/api/ai_analysis` "Strong recovery—44%" text
  persists until the next narrative regeneration (the gate catches it then). Neither forced (AI
  budget + narrative = editorial).

## Residual queue / next picks
- **Next milestone: 19 stories remain open.** The **check_doc_facts.py cluster MUST be SERIALIZED**
  — #1232 (monthly_cost ~$60 understates ~25%) + #1205 (ARCHITECTURE.md six false claims) both
  edit that file. Other candidates: #1207 (floats→Decimal consolidation — broad refactor, do solo/
  careful), #1221 (rate-limit IP spoofing — SECURITY, extra care), #1216/#1217 (supplement
  citations/claims — need factual judgment), #1215 (constellation touch/keyboard evidence),
  #1210 (svg type floor — touches check_css_tokens.py now that #1212 merged), #1218
  (/method/benchmarks empty page — may need product direction), #1219 (prologue Part I/II).
- **Left for Matthew (NOT deploys, unchanged):** #1266 DDB cycle re-stamp (history heal, needs a
  tested backfill), #1265 Elena held-draft regen (editorial + AI budget).

**Build beat:** `2026-07-18-the-week-in-honesty-fixes` (candidate) — this session's marquee is
the reader-honesty cluster (hero arithmetic that finally adds up, coaching cards dated, waveform
that stops dramatizing a 2.8% dip as an 86% collapse, band-false verdict gate). Distill ONE beat
per `docs/content/BUILD_DISPATCH_CHECKLIST.md` (merged+deployed only) OR write an explicit
`**Build beat:** none — <reason>` in the next wrap. Not yet written this session.

Prior session: `handovers/HANDOVER_2026-07-18_NextSlice1.md`.
