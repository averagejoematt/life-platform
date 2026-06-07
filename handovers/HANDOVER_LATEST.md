# HANDOVER — 2026-06-06/07 (phase taxonomy + coherent restart tooling; Monday reset staged)

> A long two-day marathon. Closed the entire backlog burndown, then ran a full
> **schema-wide phase-taxonomy review** (census + 3-lens expert panel) and built
> **coherent experiment-restart tooling** from it — all dry-run-validated for a
> **Monday 2026-06-08 reset** the owner intends to execute. ~10 PRs.

> 🔴 **READ FIRST:**
> 1. **A platform RESET is scheduled for Monday 2026-06-08** (genesis re-anchor). All
>    tooling is landed + dry-run-validated. The runbook is in
>    `.claude/plans/quizzical-rolling-leaf.md` and memory `project_monday_reset.md`.
>    **The owner runs the `--apply`** (most destructive op in the system).
> 2. Everything is **committed + pushed**; `main` == `origin/main`; no open PRs; CI green.
> 3. Production behavior is **unchanged until Monday** — `phase_taxonomy.py` is imported
>    only by the local restart scripts, not by any Lambda.

**Previous handover:** `handovers/HANDOVER_2026-06-05_BacklogBurndownVisualQA.md`.

---

## The Monday 2026-06-08 reset (the headline)

**One command** (after the morning Withings weigh-in syncs — auto-anchors the genesis weight):
```
# dry-run first, review surface:
python3 deploy/restart_pipeline.py --genesis 2026-06-08 --keep-chronicle DATE#2026-02-28
# then apply (operator runs this):
python3 deploy/restart_pipeline.py --genesis 2026-06-08 --keep-chronicle DATE#2026-02-28 --apply
```
Pre-flight: confirm `DATE#2026-06-08` exists in the withings partition before running (else `--override-weight-lbs`). Post-reset: `aws ssm put-parameter --name /life-platform/experiment-cycle --value 3 --overwrite`.

**June-8 dry-run validated:** 7,525 records archived; coach_thread leak (279 threads) covered; ENSEMBLE/NARRATIVE/adaptive_mode/circadian/protocols covered; supplements/chronicling/labs/dexa un-hidden; ledger LIFETIME roll; "Before the Numbers" → visible pre-genesis lead-in; cycle=2 stamped. Coverage assertion green. Constants reverted cleanly after the preview.

---

## What shipped (by thread)

### 1. Phase taxonomy (ADR-077) — the big one
- **Full census** of the live table (27,083 items, 180 record families) + **3-lens expert panel** (physiologist / behavioral / data-product) classified every record type.
- **`lambdas/phase_taxonomy.py`** (PR #27): single registry → `cross_phase` / `raw_timeseries` / `experiment_scoped` / `system_state`. `classify(pk, sk)` raises on unknown sources (no silent default). `tests/test_phase_taxonomy.py` — 127 tests over all 180 families. `docs/PHASE_TAXONOMY.md` + ADR-077.
- **Caught a live bug:** 279 pre-genesis coach threads were leaking into live coach prompts (writer on a bare `USER#matthew` pk the tagger couldn't see; wipe aimed at a phantom partition name).
- **Owner decisions (A–G):** supplements → cross_phase (med safety); measurements/day_grade → raw_timeseries (genesis-anchor, not hide); chronicling → cross_phase (the "before" archive); email_log → system_state; ledger → keep LIFETIME aggregate (no hard-delete); vice_streaks → split current/longest-ever. **New: cycle/reset-generation stamping** (`cycle=N`) so the archive is navigable per run.

### 2. Coherent restart tooling (ADR-077, PR #28 + 046c36a)
- `restart_intelligence_wipe.py` + `restart_phase_tag.py` now **derive from the registry** with a **coverage assertion** (a new scoped partition can't silently survive a reset). Closes every census gap. cycle stamping. failure_pattern(s) drift fixed.
- `restart_ledger_reset.py` rolls a durable `LIFETIME#aggregate` + per-cycle row, tombstones (not deletes) txns.
- `restart_chronicle_handler.py` — kept issues re-dated to genesis−N as visible pre-genesis lead-ins (fixed a latent bug where "resurrected" articles stayed `phase=pilot`/hidden). `restart_pipeline.py --keep-chronicle` passthrough.

### 3. ADR-058 read-side phase-filter sweep (PR #23, layer v74)
All 268 query sites inventoried: 112 filtered, 22 cross-phase `include_pilot` annotations, 68 exempt. Public endpoints stopped serving 100% pilot-era data; labs preserved. Verified live (smoke 65/0, visual 20/0).

### 4. Backlog burndown (2026-06-06) — see CHANGELOG v8.3.1/8.3.2
- **N-08** cost-governor false tier-3 fixed (actual-spend cap; tier 3→1, AI restored). **D-01** daily-brief cache fix deployed (layer v72→73→74). **S-02** Evidence depth. **S-03** cockpit Week scope (real observatory_week sparklines). **S-05** visual-qa coverage. **D-03** orchestrator token reduction (~50% billed input). **L-04** http_retry in dropbox_poll. **L-07/L-08/L-09** doc verification passes (SCHEMA.md ~20 sections, MCP catalog +17 tools, DEPENDENCY_GRAPH SPOF). Several stale items closed (L-03, DRY_RUN gate, SiteAPI dashboard, S-04).
- Remediation-agent freshness fix merged (PR #16).

---

## ⚠️ Operator follow-ups
1. **Monday: run the reset** (above). Confirm weigh-in first; you run `--apply`.
2. **Post-reset:** bump SSM `/life-platform/experiment-cycle` to 3.

## Known / deferred (non-blocking, post-reset)
- Write-time `phase`/`cycle` stamping in the coach writers (so the NEXT reset's tagger-blind partitions self-describe).
- `NARRATIVE#arc` `phase → arc_phase` rename (latent attribute collision; harmless today).
- Read-side measurements genesis-anchor (currently phase-filtered; 1 record).
- The `baseline_snapshot` untag is **no longer a manual step** — the rewired tagger handles it automatically during the reset.

**Verify quickly:** `python3 -m pytest tests/test_phase_taxonomy.py -q` (127/0) · `python3 deploy/restart_intelligence_wipe.py` (dry-run, coverage assertion green) · `bash deploy/smoke_test_site.sh` (65/0).
