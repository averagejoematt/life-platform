# HANDOVER — Big-architecture paydown: cold-start armed (#1371), private intake ledger (#1405), flourishing daylighted (#1403), deploy README (#1322) — 2026-07-18 (evening)

> Instruction thread: continue the HIGH-VALUE backlog paydown, BIAS TOWARD THE BIG
> fable/opus architectural stories a fan-out can't half-do; fan out disjoint smalls;
> exclude gate:owner into ONE end-of-session decision menu. "Properly" = real fix +
> non-vacuous guard proven RED pre-fix, merged AND deployed + verified live. Matthew
> pre-authorized all merges and deploys ("i approve all merges and deploys etc. this
> session"). NOTE: a PARALLEL plan-only session (design partner pipeline,
> `HANDOVER_2026-07-18_DesignPartnerPlan.md`) ran tonight — no tree conflicts; its
> handover archived here, its backlog is #1460–#1475.

## Outcome — 4 issues closed properly (3 big solo + 1 fan-out), all live

**Standing ops first:** public_stats platform counts had NOT self-healed (still
121/26/62 at 15:52 PT — root cause: today's 17:06 UTC brief ran BEFORE the 21:50 UTC
deploy carried the #1369 writer). Healed the S3 block directly from PLATFORM_STATS
(64/20/94), invalidated `/public_stats.json`, verified live; tomorrow's brief writes
truth natively. `restart_verify.py` NOT run — still pre-genesis PT (Sunday+ item).

**Solo (each: guard red pre-fix in a pristine origin/main worktree, render/live verified):**
- **#1371 cold start as an armed instrument** (PR #1457): NEW `lambdas/experiment_gates.py`
  — the ONE registry of arming thresholds; correlation engine (`_INTERP_N_REQUIRED`,
  min-n), hypothesis engine (MIN_* family) and coupling floor import from it
  (identity-assert guard). `/api/correlations`+`/api/hypotheses` shaped-empty payloads
  carry gates + measured current_n (null when unmeasurable, never 0);
  `/api/source_freshness` stamps `carried`/`carried_from_cycle` + the experiment anchor;
  ai_context early-phase block gains the RESET-MANUFACTURED-GAPS no-scold clause (reaches
  every narrative surface via the one formatter); "warming up" hollow-mark grammar
  (`.warmup` tokens.css + `warmup()` evidence_shared.js) on correlations + discoveries
  zero-states; scorecard never promises a past date. 12 guards (7 red pre-fix);
  render-qa 4/4 surfaces at 1280+390 (its one finding — dashed border losing the
  cascade — fixed via `.rd-badge.wu-carried` compound selector). **Live-verified**:
  gates serve `0/10` (honest pre-genesis), carried chips + anchor live.
- **#1405 private intake ledger** (PR #1458): `intake_count` (0–4) joins the signed
  evening-nudge tap links, routed to `SOURCE#private_intake` — never the
  public-aggregated evening_ritual record. NEW `lambdas/intake_response.py`: evening-D
  count vs whoop D+1 (hrv/recovery/rem) — Pyper–Peterman n_eff, p on n_eff,
  zero-vs-nonzero block-bootstrap CI (all stats_core); dose bins arm at 15 nonzero
  evenings. MCP `log_evening_intake`+`get_intake_response`; quiet fail-soft daily-brief
  line (n+CI per ADR-105). `tests/test_intake_privacy_contract.py` pins the privacy
  boundary BOTH ways (presence red pre-fix; identifiers banned from site/, web reads,
  generated-artifact writers; response-level planted-field test). Tonight's 8 PM PT
  nudge carries the third tap row.
- **#1403 flourishing daylighted** (PR #1459): NEW `lambdas/flourishing.py` — daily
  provenance-stamped `SOURCE#flourishing` projection of the Haiku enrichment PERMA
  signals; enrichment writes rows every run + `{"flourishing_only": true}` zero-LLM
  backfill (**ran post-deploy: 18 rows from 47 enriched entries since Jan, verified in
  DDB with model stamps**). MCP `get_flourishing_trend` (EMA + provenance +
  anti-rumination framing). Pillar wiring: flourishing row = PRIMARY Relationships
  social input; Mind gains config-gated `values_alignment` (journaled-zero = real 20,
  no row = None); weights rebalanced sum-1.0, **S3 config uploaded + verified**
  (`config/matthew/character_sheet.json`). 13 guards (5 wiring guards red pre-fix).

**Fan-out (worktree-implementer, verified before merge):**
- **#1322 deploy README** (PR #1456): README + OPERATIONAL_RUNBOOK rewritten against
  the live scripts; the boot-broken ADR-031 manual MCP zip recipe tombstoned (4 patterns
  in `docs/_lint/tombstones.txt`, scanner covers live `deploy/*.md`); check_doc_index
  gains the blocking deploy-docs status-header+freshness gate. Guard proof: 5 tombstone
  hits + 4 headerless docs on pre-fix tree.

**Merge discipline:** /reconcile-branch per PR (merge main → `sync_doc_metadata --apply`
→ linearize → squash); mcp_tools literal 64→67, test_count 3948→~3990 across the queue.

## Un-red main mid-wrap (the session's own regression, caught + fixed)
The #1405 routing made the ritual write pk dynamic → the orphan-partition gate
(`test_site_partition_orphans`) saw `evening_ritual` as writerless and redded e1bcf766 +
4e886736 (my local full-suite ran `-x` and stopped at the OTHER failure — the stale
generated `/method/game/` page, which the reconcile bot fixed on main before my regen
push). Fix `28ee812a`: both write destinations INLINE as USER_PREFIX-joined literals in
the update_item call (the gate resolves web writers only inside put/update calls) +
line-level read-shape rule in the privacy contract. **28ee812a's CI/CD ran GREEN
end-to-end and fleet-deployed everything** (daily-brief/mcp/journal-enrichment/
evening-nudge all LastModified 01:13–01:15 UTC; deployed MCP bundle AST-verified: 67
tools incl. the three new).

## Gotchas hit (durable ones in memory)
- **Orphan gate needs inline write literals**: a hoisted/dynamic pk in a web put/update
  call makes the partition read as writerless — `reference_orphan_gate_inline_writer_literal`.
- **`pytest -x` masks the second failure** — the orphan red hid behind the game-page red
  locally; full suite without `-x` before pushing a multi-PR queue.
- **`config/character_sheet.json` feeds a GENERATED site page** (`/method/game/` via
  `scripts/v4_build_game_explained.py`) — config change ⇒ regenerate same-commit, else
  Unit Tests red one cycle later (the reconcile bot self-healed it this time).
- **Parallel-session handover collision**: the plan-only session's staged `git mv` of
  HANDOVER_LATEST rode into my un-red commit (shared index!) — harmless here, but check
  `git status` staged state before committing when a parallel session is live.
- CloudFront `/api/*` viewer-path invalidation before live-verifying (again held true).

## Residual / next picks

> **Reconciled 2026-07-19 under the #1340 residual-queue gate** — every bullet below now
> cites an issue number or carries an explicit `not-work —` tag; none were silently dropped.

- **Sunday+ (post-genesis, tomorrow)**: `python3 deploy/restart_verify.py`; verify the
  17:00 UTC brief writes 64/20/94 natively + the first intake brief line renders; re-seed
  prereg only if a pipeline re-run happened — **not-work — standing post-genesis
  verification routine, not a backlog item.** Cycle-8 prereg publish still awaits
  Matthew's OK (`handovers/prereg_dryrun_cycle8.txt`) — **not-work — pending Matthew
  decision, not a filed issue** (same item as the decision-menu bullet below).
- **site-api can't read SSM `/life-platform/experiment-cycle`** → freshness payload
  `experiment.cycle: null` and carried chips read "a previous attempt" (fail-soft,
  honest). IAM grant is user-NAMED → in the decision menu — **not-work — pending a
  Matthew-named IAM grant, not yet a filed issue** (same item as the decision-menu SSM
  IAM line below).
- Now remainder: #1409 felt-reality calibration (fable, W5 — n accrues weekly, time-
  sensitive), #1395 growth surface, #1376 career-vs-season, #1426 QA tier manifest
  (unlocks the qa-strategy epic), design pipeline #1462→#1464 (+pilot #1469); #1338 held
  on #1319. Epics #1194/#1195.
- Decision menu (Matthew): #1319 approval-gate posture, #1114 portrait pick,
  #1243/#748/#1187/#1029, gate:owner #1350/#1329, #741 — all filed issues. Prereg publish
  OK and the SSM cycle-param IAM line are **not-work — pending a Matthew decision/grant,
  not filed issues** (see the two bullets above).

**Main:** green (28ee812a) — its full CI/CD run concluded SUCCESS (fleet deploy included);
verified via `check_main_green.py` at wrap.
**Build beat:** `2026-07-19-cold-start-armed` (merged + deployed + verified only;
#1405 deliberately absent from the public beat — Matthew-private surface).
**Docs:** SCHEMA.md (flourishing + private_intake partitions), engines/CHARACTER doc
(values_alignment component) — see wrap commit; MCP catalog + counts via doc-sync;
tombstones/deploy-docs updates shipped inside #1322 itself.

Prior sessions (same day): `HANDOVER_2026-07-18_DesignPartnerPlan.md` (parallel,
plan-only), `HANDOVER_2026-07-18_QaStrategy.md`, `HANDOVER_2026-07-18_LaterDrainCycle8Reset.md`.
