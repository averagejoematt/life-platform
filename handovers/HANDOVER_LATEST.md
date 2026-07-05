# HANDOVER — the model:opus batch, end to end: 11 issues → merged → layer v113 → deployed + verified — 2026-07-05 (opus session)

> **This session ran concurrently with the HAE/ingestion session** (which codified the HAE
> webhook edge into IaC and landed the #500 deploy — see
> `handovers/HANDOVER_2026-07-05_HAE_IaC_Deploy.md`) and after session 17's model:sonnet
> batch (`handovers/HANDOVER_2026-07-05_session17_SonnetBatch.md`). All three are now live on
> the same `main`. This handover covers the opus batch and is the consolidated close state —
> **all other sessions are closed.**

Matthew asked to "pay down as many `model:opus` issues as makes sense in one session,
prioritize value/outcome," while a parallel session worked HAE. Then: **"I authorize you to do
all deploys and merges this session and everything in auto mode is a yes."**

---

## Triage → 11 shipped, the rest deliberately held

Of 37 open `model:opus` issues, shipped 11 as a coherent slice; held the rest for reasons
below (all still open).

**Shipped (all merged + deployed + verified):**
- **Instrument-uplevel vertical slice (epic #575):** #581 evidence.js split (3,160→208-line
  router + 12 per-family `evidence_*.js` modules) · #582 chart interaction contract v2 (15/24
  charts answer to touch/hover/keyboard) · #551 uncertainty-first visual language (fan charts,
  CI bands, sample-size dots, confidence grammar — DESIGN_SYSTEM_V5 §7a; every band bound to a
  real interval, honest no-band fallback) · #584 provenance popovers (registry-fed from #544 so
  they can't drift; new `provenance_popover.js`, wired via the shared `fig()` helper).
- **Data honesty & intelligence:** #494 movement rest-vs-breakage (INGEST_HEALTH sentinel) ·
  #493 TSB honesty gate (ADR-109 — derived/proxy values covered by the scheduled scan, not the
  tight guard) · #542 changepoint detection (CUSUM, stdlib, `stats_core.detect_changepoints` →
  daily-insight) · #543 personal-variance thresholds + EWMA-ACWR (ADR-105; **floor-guarded —
  byte-identical to current constants until ~30 obs accumulate**) · #487 sleep reconciler
  **RETIRED** (ADR-113; dead merge reading nonexistent fields, mislabelled the public page) ·
  #414 autonomic quadrant + zone-2 read-only data-door endpoints.
- **Interactive:** #546 multi-turn board follow-up sessions (ADR-112; opaque-token, DDB TTL≤1h,
  atomic `followup_count < :cap AND ip_hash = :ip` condition, per-turn fail-closed grounding).

**Held out (still open, deliberate):**
- **Ingestion-adjacent** (the HAE session's territory): #507, #475, #478, #489, #415, #421,
  #422, #412, #417, #508.
- **Deploy-pipeline infra** (don't churn deploy tooling under a concurrent deployer): #416,
  #418, #401, #408, #411.
- **#395** MCP registry prune — destructive (removes tools), do attended.
- **Growth/build-in-public:** #420, #405, #399.
- **Downstream site-ux epic tail now UNBLOCKED** by this session's #581/#582/#551:
  #588 (motion v2), #590 (home cinematic), #591 (cockpit presence), #593 (portraits travel),
  #595 (share-card engine). #593 still needs your ADR-106 portrait sign-off.

## Deployed + live-verified (one coordinated sequence)

- **Shared layer v112 → v113** (build_layer → `cdk deploy LifePlatformCore` publishes → verify
  → bump `SHARED_LAYER_VERSION` constant → deploy consumers). **Also reconciled the session-17
  drift** where the constant said 111 but live was already 112.
- **CDK:** Compute (personal-baselines-compute ADDED w/ `cron(0 8 1 * ? *)`, sleep-reconciler
  REMOVED, daily-insight updated), Web (BOARDSESS IAM), Operational, Mcp, Email. **Not touched:
  LifePlatformIngestion** (HAE's) and Monitoring (no changes).
- **site-api** (`deploy_site_api.sh`, full `web/` dir) — `/api/autonomic_balance`,
  `/api/zone2`, `/api/methods` all 200; retired `/api/sleep_reconciliation` → 404.
- **Static site** synced + CloudFront invalidated. **Build hash == HEAD (4e84aba7), smoke
  67/67, visual QA 33/33** (3 benign warnings incl. the known glucose sparse-data state).
- **Bonus:** the Mcp redeploy re-bundled from `main` and **fixed a pre-existing prod crash** —
  the live MCP lambda had been throwing `No module named 'reading'` (integration tests i10/i12
  green again).

## Gotchas (durable ones saved to memory)

1. **Pre-reserving ADR numbers per parallel agent (109–113) prevented the session-17 ADR
   collision.** Each agent was told its number up front; no two wrote the same one.
2. **Stale agent worktrees break repo-tree-walk tests.** `test_hevy_compiler_isolation` passed
   on baseline but failed on merged main — offenders were all `.claude/worktrees/agent-*/`
   copies, not real source. Prune worktrees before the full-suite-on-main verify.
   (`reference_stale_worktrees_break_tree_walk_tests` in memory.)
3. **An agent (#581) ran out of window before committing** — its finished work sat uncommitted
   in the worktree; orchestrator landed it (PR #674), verified byte-identical. The agent later
   resumed and opened a duplicate PR #677 — closed as superseded (salvaged one doc fix).
4. **`test_count`/ADR-ledger/doc-counters conflict on nearly every stacked merge** — mechanical:
   take either side, `sync_doc_metadata.py --apply`, re-commit. The #389 `--check` gate makes a
   missed re-sync fail CI, so every busy-session merge needs it.
5. **cdk diff before deploy caught a layer-downgrade trap** — deploying consumers with the
   constant still at 111 would have downgraded live lambdas from 112→111. Bump the constant to
   the freshly-published version BEFORE deploying consumers.

## State at close (all sessions closed)

- `main` clean, build hash == HEAD (4e84aba7), all gates green (doc-drift, black, ruff, flake8,
  JS parse, hash graph). Full suite: 3532 passed; the only reds are pre-existing live-state
  integration tests **i3/i9/i14** (a message in the prod DLQ + canary checks — NOT this batch).
- All 11 issues CLOSED; zero dangling PRs.
- **Stale `git stash` entries cleared** this session (all were "RECOVERED: not mine" content
  already landed via merged PRs, plus old pre-2026-07 WIP — all sessions now closed, so safe).

## What's next

- **Site-ux epic tail** (#588/#590/#591/#593/#595) — unblocked by the split + chart contract;
  #593 portraits-travel needs your ADR-106 sign-off.
- **#582 follow-on:** 9 of 24 chart renderers still non-interactive (ring/radar/quadrant/heatStrip
  etc. — bespoke interaction, listed in PR #680).
- **#584 follow-on:** cockpit score/readiness tiles have no registry entry yet (honest = no
  popover until added to `methods_registry.py`); the weight-rate ±CI caption is a natural next
  provenance adopter.
- **#543:** personal-variance bands are live but floor-guarded — they won't change any verdict
  until ~30 observations accumulate post-reset; worth re-checking in a month.
- **Held-out opus queues** above remain for future sessions (ingestion-adjacent = coordinate
  with HAE; #395 MCP prune = attended; infra/growth).
