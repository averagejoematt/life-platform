# HANDOVER — the rigor chain: ADR-105 → stats_core → hypothesis engine v2 — 2026-07-04 (session 10)

The full epic-#525 opening sequence is **MERGED + DEPLOYED + LIVE-VERIFIED** in one
session: **ADR-105** (PR #567, docs), **#529 stats_core** (PR #568, layer **v105**),
**#530 hypothesis engine v2** (PR #570 — supersedes #569, see gotcha 1). Issues
#554/#529/#530 auto-closed. The last fable **Next** story is done; remaining open
fable stories are all **Later**: #550/#547/#541/#540/#539/#506/#498.

---

## What shipped

### ADR-105 — the rigor bar (PR #567)
Four standing rules recorded once so E-A PRs cite instead of re-litigate:
(1) every user-facing statistical claim carries uncertainty + n or "descriptive
only"; (2) every forecast enters the calibration ledger and is graded; (3) an LLM
verdict about data is always preceded by a deterministic computation it narrates;
(4) new thresholds derive from personal variance or document why not. Plus the
ADR-103 ledger row: stats/forecast machinery = **load-bearing**.

### #529 — stats_core (PR #568, layer v105)
- **`lambdas/stats_core.py`** (shared layer, stdlib-only, pure): one `pearson_r`,
  one erf-based `pearson_p_value` (accepts **fractional n**), AR(1)/Bartlett
  `effective_sample_size` (Pyper-Peterman for pairs; clamped to [2, n] — only ever
  corrects toward conservatism), seeded moving-block-bootstrap CIs (paired /
  single-series / `bootstrap_mean_diff_ci`), Fisher-z CI, `cohens_d`, `bh_fdr`.
- **Migrations, duplicates deleted**: weekly-correlation (p on n_eff, per-pair
  `n_eff` + `ci95_low/high`), tools_training cross-source correlation (~50 inline
  lines → 5, output gains `effective_n`), mcp/helpers.pearson_r (delegates,
  min-3/round-3 contract kept), digest_utils.compute_confidence (`n_eff` param).
- 35 tests incl. the acceptance fixture: AR(1)-driven pairs — raw-n p significant,
  corrected p >1.5× weaker.

### #530 — hypothesis engine v2 (PR #570)
- **Creation = pre-registration**: generation must emit a machine-checkable
  `test_spec` `{condition_metric, condition_op (>=|<=|median_split),
  condition_threshold, outcome_metric, direction, min_effect, lag_days}` from the
  `build_data_narrative` vocabulary (listed in the prompt; `SPEC_METRICS` must stay
  in sync with the narrative builder). `validate_test_spec` gates storage; the spec
  is frozen at write (`pre_registered_at`, `engine_version: 2`).
- **Check = pure Python** (`evaluate_test_spec`): arm split per frozen spec
  (lag-paired), effect size + block-bootstrap 95% CI + d via stats_core.
  supported = CI excludes 0 predicted-side AND ≥ min_effect; contradicted =
  CI excludes 0 wrong-side → refuted; confirmed = supported + full window
  observed; window expiry undecided → archived `expired_undecided`.
- **The Haiku data-verdict is deleted** (`validate_check_verdict`,
  `load_active_experiments`, the per-hypothesis weekly calls). Haiku only narrates
  resolutions, fail-soft to the deterministic evidence sentence. Net AI-cost cut.
- **Calibration ledger**: every resolution → `SOURCE#calibration /
  CALIB#<date>#<id>` (stated_confidence vs outcome + final stats + frozen spec).
  Registered **CROSS_PHASE** in phase_taxonomy — the scoreboard measures the
  platform, not a cycle; it must survive resets.
- **Surfaces**: HYPOTHESIS# records carry effect/ci95/n/deterministic_verdict;
  MCP `get_hypotheses` + `/api/hypotheses` serve spec + stats + pre_registered_at;
  evidence.js cards render "frozen test" + "measured" lines + "pre-registered
  <date>"; digest context cites measured effect + CI on confirmed lines.
- Engine pulls 30 days now (checks need the full window); generation still sees 14.

### Live verification (all on prod, 2026-07-04)
- Layer **v105** published + verified; Compute/Mcp/Email/Ingestion/Operational all
  redeployed; site-api via `deploy_site_api.sh` (200); site synced (evidence.js).
- **hypothesis-engine invoked live**: 200 — 3 new v2 hypotheses stored with frozen
  specs, **2 rejected by the spec gate** (the stricter contract working), 5 legacy
  v1 pendings correctly skipped (never LLM-checked again), 0 resolutions yet.
  `/api/hypotheses` serves `test_spec` + `pre_registered_at` live.
- **weekly-correlation force-recomputed**: per-pair n_eff + ci95 live. The
  headline: `habit_pct_vs_day_grade` r=0.88 n=20 → **n_eff 7.1**, still
  FDR-significant (p_fdr=0.002); `tier0_streak_vs_day_grade` n=20 → n_eff 17.1,
  **no longer significant**. 1/23 pairs FDR-significant — the honest count.
- Main CI green through Deploy + I1/I2/I5 + smoke (run 28718898507).

## Gotchas (this session's tuition)

1. **`gh pr merge --delete-branch` on a stacked base CLOSES the child PR** — and a
   closed PR whose base branch is gone can be neither retargeted nor reopened
   (GraphQL refuses both). Recovery: rebase the child onto main
   (`git rebase --onto origin/main <old-base-sha>`), open a FRESH PR (#569→#570).
   Next time: retarget the child to main BEFORE merging the base, or don't stack.
2. **Full CI gates do NOT run at PR level** in this repo — PRs only get "Dependabot
   Validate". The local FAKE-creds full-suite run (CONVENTIONS §4) is the real
   pre-merge gate; main's push-triggered CI is the confirmation, not the test.
3. **New layer modules need a `ci/lambda_map.json` entry as `lambdas/<name>.py`**
   (repo-relative) — LV4 fails on a missing entry, LV3 fails on a bare filename.
4. **`test_hevy_compiler_isolation` reds locally** from stale `.claude/worktrees/`
   copies (not in git — CI-clean). Ignore or clean the worktrees.
5. **Weekly-correlation's nested-map Decimal conversion only handles top-level
   values** — new per-pair fields must be FLAT keys (`ci95_low`, not
   `ci95: {low…}`) or boto3 rejects the floats.
6. `aws dynamodb query` piped through `--query`/JMESPath on nested maps is
   miserable — use boto3 in a heredoc for DDB verification.

## Watch
- **Sunday 07-06, hypothesis engine cron**: first scheduled v2 run — expect v1
  legacy skips in the logs, no resolutions before ~07-11 (7-day check floor).
  First calibration rows land when something resolves (~2-3 weeks).
- **Sunday 07-06 weekly-correlation cron**: FDR-significant count will sit lower
  than historical weeks — that's the effective-n correction, not a regression.
  (`tsb_vs_recovery` also still straddles the #490 kJ→TSS discontinuity ~2 wks.)
- Wed 07-09 chronicle (session-9 watch: grounded hints + Elena's promises due).
- `slo-source-freshness` 7-day window from 07-04.

## Next
- **#535** (rank 7, Next): uncertainty everywhere it's claimed — weight-projection
  CIs, SE-based drift, corrected correlation *tools* (tools_correlation's HARMFUL
  labels at n=5 still have no correction — deliberately left for #535).
- **#538 calibration scoreboard** consumes the new ledger once rows exist.
- Fable Later flagships: #541 forecast engine (builds directly on stats_core +
  the calibration ledger), #540 inter-coach dialogue, #506 journal Phase 2,
  #539 N-of-1 engine, #547 podcast v2, #550 scenario explorer, #498 registry enums.
