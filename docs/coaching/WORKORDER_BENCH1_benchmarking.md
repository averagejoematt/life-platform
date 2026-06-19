# WORKORDER: BENCH-1 — Cut Benchmarking & Regain Firewall

> **Status:** OPEN — ready for Claude Code.
> **Author:** coaching session 2026-06-19 (derived from `PROVEN_BLUEPRINT.md` + cross-episode analysis).
> **Pairs with:** `docs/coaching/PROVEN_BLUEPRINT.md` (the finding this operationalizes),
> `TRAINING_CALIBRATION.md`, `TRAINING_PROGRAM.md`.
> **Boards consulted:** Technical (Omar/Priya/Anika/Henning/Viktor/Dana) + Personal (Victor/Maya/Nathan) + Product (brief).
> **Privacy tier:** PRIVATE. Nothing in BENCH-1 may surface to Elena Voss or any public surface.

---

## How Claude Code works this

Read first, in order: this file, `docs/coaching/PROVEN_BLUEPRINT.md`, `mcp/tools_health.py`
(`tool_get_readiness_score` — copy its `computed_metrics` read pattern verbatim), and the
`daily-metrics-compute` Lambda (copy its source-read + computed-record-write pattern).

Then build the five sub-items **in order**, committing each independently. Do **not** register any
MCP tool whose implementing function isn't in the same commit; run `pytest tests/test_mcp_registry.py`
before considering any MCP change done. Tool functions go **before** the `TOOLS = {}` dict.
**Do not deploy** — write code + tests, show diffs; Matthew runs all deploys.

**Hard scope guardrails (from the board — these are acceptance criteria, not suggestions):**
- **No predictor.** There is no "will-he-hold" model — `n_held = 0`, no positive class. Build only the
  *descriptive* divergence comparison (current vs proven). Any ML/classifier = out of scope, reject.
- **Correlational only (Henning standard).** Every numeric output carries a `confidence` field and an
  `n` field. No causal language anywhere in tool output strings. Small-n ⇒ `confidence: "low"`.
- **Forward framing (Nathan guardrail).** Output strings never tally failures. The brief/coach must
  never render "0 of 16 held" or a regain count as a recurring stat. Surface the *forward* signal
  ("walking is X vs the ~Y/wk that worked at this weight"). Add a unit test asserting the `maintenance`
  view output contains no failure-count string.
- **Cadence (Viktor).** Episode ledger refresh is **weekly + on-demand**, NOT on the nightly path.
  The live `pace` comparison is computed at tool-call time from precomputed reference + recent Withings.

---

## Data model (BENCH-1.1) — two new computed sources

Store both as computed records in the existing single table, read via `query_source(...)` exactly like
`computed_metrics`. **Match the existing partition/key convention — read `core.py` / how
`computed_metrics` is keyed; do not invent a new PK format.**

1. **`weight_episodes`** — one item per detected episode. Fields:
   ```
   episode_id            # e.g. "2024-09-05_loss"
   type                  # "loss" | "regain"
   start_date, end_date
   w_start, w_end, magnitude_lb, duration_wk, rate_lb_wk, peak_rate_lb_wk
   covariates_during     # {walks_wk, walk_hr_wk, runs_wk, lift_sessions_wk, lift_sets_wk}
   covariates_reliable   # bool — false when window predates dense Strava (~pre-2020)
   post_trough_8wk       # {walks_wk, walk_hr_wk}  (loss episodes only)
   regain_180d_lb        # max regain within 200d of trough (loss episodes only)
   outcome               # "held" | "reversed" | null
   confidence            # "low" while total episode n < 30
   ```
2. **`training_reference`** — singleton record, the proven by-band prescription + the 2024–25 proven
   trajectory curve:
   ```
   bands: { "300-309": {walks_wk, walk_hr_wk, runs_wk, lift_sessions_wk}, "290-299": {...}, ... }
   proven_curve: [ {weight, days_from_start, cum_lost, walks_wk}, ... ]   # the Sep24→Apr25 reference
   source_window: "2024-09-05..2025-04-30"
   derived_at, confidence: "low", n_episodes_with_covariates
   ```

Both are reference data: no TTL. Omar's note: these are thin derived views over `withings` / `strava`
/ `hevy` — do not duplicate raw activity rows.

---

## Compute (BENCH-1.2) — `episode-detect` Lambda

New Lambda (follow `daily-metrics-compute` for data access + CDK wiring). **EventBridge: weekly**
(e.g. Sun 10:00), plus manual-invoke support. Reads full `withings` history (+ `strava`/`hevy` for
co-variates), runs the reference algorithm below, writes `weight_episodes` + `training_reference`.

**Reference algorithm (port verbatim; pure-Python, no scipy in the Lambda):**
```python
# 1. Smooth: daily-resample withings weight, linear-interpolate, 21-day centered rolling mean.
# 2. Turning points via swing/ZigZag detector (min_swing = 12.0 lb):
def turning_points(vals, idx, min_swing=12.0):
    tps=[]; ext_i=0; ext_v=vals[0]; direction=0
    for i in range(1,len(vals)):
        v=vals[i]
        if direction>=0 and v>ext_v: ext_v,ext_i=v,i
        elif direction<=0 and v<ext_v: ext_v,ext_i=v,i
        if direction>=0 and v<=ext_v-min_swing:
            tps.append((idx[ext_i],'P',ext_v)); direction=-1; ext_v,ext_i=v,i
        elif direction<=0 and v>=ext_v+min_swing:
            tps.append((idx[ext_i],'T',ext_v)); direction=1; ext_v,ext_i=v,i
    return tps
# 3. Loss episode = P -> next T with (w_start - w_end) >= 15 lb. Regain = T -> next P >= 15 lb.
# 4. Outcome (loss only): regain_180d = max(smoothed[trough .. trough+200d]) - w_end;
#    "held" if regain_180d < magnitude/3 else "reversed".
# 5. Co-variates per window: Strava Walk+Hike (walks_wk, walk_hr_wk via Moving Time/60/60),
#    Run (runs_wk), Weight Training (lift_sessions_wk); Hevy sets/wk where available.
#    Normalise per-week by window_days/7. Set covariates_reliable=False when window start < 2020-01-01.
# 6. post_trough_8wk: same co-variates over [trough, trough+56d].
```
Validated values this must reproduce on the current data (use as a fixture test): 16 loss episodes;
mean loss rate ≈ 3.0 lb/wk; mean regain rate ≈ 2.4 lb/wk; 2024-09-05→2025-04-30 episode = −118 lb /
~34 wk, covariates walks_wk ≈ 11.4, post_trough_8wk walks_wk ≈ 4.4; 0 episodes "held".

---

## MCP tool (BENCH-1.3 + 1.4) — one dispatcher `get_benchmark`

**One tool, view-dispatched** (Anika; matches `get_health` / `get_nutrition`; protects the ≤80-tool
SIMP-1 budget). Function before `TOOLS`; register in same commit; registry test green.

`get_benchmark(view=..., date=?)`:

- **`view="episodes"`** — returns `weight_episodes` ledger + summary (loss vs regain mean rate, the
  0.79× asymmetry). Read-only from the precomputed source. `confidence:"low"`, `n` surfaced.
- **`view="pace"`** *(BENCH-1.3, the daily-value view)* — computed live: current weight + current
  loss rate (reuse `tool_get_weight_loss_progress` / recent `withings`) vs (a) `training_reference`
  band for the current weight and (b) `proven_curve` at the matched weight. Returns e.g.
  `{current_weight, current_rate_lb_wk, proven_rate_at_weight, pace_vs_proven: "ahead|on|behind",
  walks_wk_current, walks_wk_proven, walk_gap, run_gate_ok: bool}`. Forward-framed strings only.
- **`view="maintenance"`** *(BENCH-1.4, the regain firewall)* — only meaningful post-trough / near
  goal. Compares current rolling walk volume to the proven floor and to the post-trough decay
  signature that preceded past regains; entry gated by `get_metabolic_adaptation` +
  `get_deficit_sustainability` (Victor). Output is support, never indictment (Nathan): no failure
  tally, forward signal only. Include the disclaimer used by the other health tools.

All three: descriptive, correlational, `confidence`/`n` on every numeric block, PRIVATE.

---

## Docs, tests, governance (BENCH-1.5)

- **ADR** — new partition + new tool + new Lambda + new cadence is an architecture decision. Write one
  (next ADR number), defer-nothing, record Viktor's weekly-not-nightly call and Henning's no-predictor
  constraint as the rationale.
- **Tests** — registry test green; a fixture test pinning the algorithm to the validated values above;
  the Nathan no-failure-tally string test on the `maintenance` view; a `pace` view test asserting
  forward-framed output and `run_gate_ok=False` above 240 lb.
- **Doc update matrix** (per house trigger rules): `CHANGELOG` + `PROJECT_PLAN` always;
  `DATA_DICTIONARY` (two new SOT domains: `weight_episodes`, `training_reference`);
  `MCP_TOOL_CATALOG` + `USER_GUIDE` + `FEATURES` (new `get_benchmark` tool);
  `ARCHITECTURE` + `SCHEMA` + `DECISIONS` (new partition + Lambda); `COST_TRACKER` (new Lambda —
  Dana: pennies/mo, note it). Run `python3 deploy/sync_doc_metadata.py --apply` if counts change
  (tool count +1).

## Deploy sequence (Matthew runs — reminders, do not execute)

1. CDK deploy the new `episode-detect` Lambda + weekly EventBridge rule.
2. Manually invoke `episode-detect` once to backfill `weight_episodes` + `training_reference`.
3. MCP package deploy (full `mcp/` dir — `deploy_lambda.sh` rejects `life-platform-mcp`; follow its
   printed build sequence). New script needs `chmod +x` or `bash deploy/<script>.sh`.
4. `pytest tests/test_mcp_registry.py` green before the MCP deploy.
5. Smoke-test: `get_benchmark(view="pace")` at current weight returns `behind` + a walk gap and
   `run_gate_ok=False` (you're at 305, above the 240 gate).

---

## Out of scope (explicit — do not build)

Any holding/regain *predictor* or classifier; any public surface; any separate analytical store;
nightly episode recompute; causal language; any rendering of the reversal count in a brief or digest.
These were rejected by the board on this workorder — re-propose separately if ever revisited.
