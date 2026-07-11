# Claude Code Build Prompt — Recovery-Adaptive Night-Before Authoring (v1)

> **Destination in repo:** `docs/specs/CLAUDE_CODE_PROMPT_RECOVERY_ADAPTIVE_AUTHORING_v1.md`
> **Pairs with brief:** `docs/specs/SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md` (read first — principles, rubric, edge-case table).
> **Date:** 2026-06-21

---

## CONTEXT (do not re-derive)

Routines are authored the night before; Matthew trains the next morning (wake → car → gym) with **zero platform interaction possible**. Two failures on 2026-06-21: (1) authored on **stale/incomplete** volume data (`get_muscle_volume` hadn't aggregated the latest sessions → wrong baseline); (2) hard-stamped one night's `recovery_tier` so the routine couldn't adapt to a GREEN morning. Fix both structurally. The routine must be **self-adapting at 5am off a wrist-visible Whoop band, with a safe default, authored only on complete data.**

### Hard invariants (tests enforce)

1. **Freshness/completeness gate** — authoring refuses to compile if volume/recovery/recent-workout inputs don't cover the latest *ingested* sessions. Completeness, not max-date recency.
2. **Tier-agnostic authoring** — no single `recovery_tier` drives the prescription; the routine carries GREEN/YELLOW/RED branches.
3. **Safe default** — absent/ambiguous morning signal resolves to YELLOW.
4. **Subtract-only** — GREEN is the authored ceiling; YELLOW/RED are defined subtractions; nothing authored lets the athlete exceed the GREEN ceiling on the day.
5. **Fail-open** — any optional automation (re-stamp) degrades to the always-present branches; no morning hard dependency.

---

## PREREQUISITE (land first or in parallel)

The `get_muscle_volume` **staleness + core-mapping** bug (notes brief §14.4). Authoring consumes volume; if volume is wrong, branches are wrong. Either fix it first or have the freshness gate (below) treat an incomplete volume read as a hard block.

---

## BUILD — Part B (platform hardening)

### 1. Freshness/completeness gate — `authoring_freshness_gate(target_date) -> {ok, gaps[]}`

- Confirm, for the athlete: latest **Hevy workout**, **Whoop recovery**, and **muscle-volume aggregation** all include every session ingested up to authoring time. Compare the volume/aggregation's newest counted session against the newest ingested workout — if the aggregation lags, that's a gap (the exact §14.4 failure).
- Return structured `gaps` (which input, how stale). `manage_hevy_routine` **draft path refuses to compile** when `!ok`, returning the gaps so Claude can refresh/flag rather than silently author on stale data.
- Test: a synthetic state where volume omits the most recent session → gate returns `ok:false` with the gap; draft is blocked.

### 2. Conditional branches as structured data — `branches` on each exercise

- Extend the routine IR exercise schema with an optional `branches` object:
  ```
  branches: {
    green:  { cue, sets?, load_pct?, rpe_cap?, cardio_mode? },
    yellow: { cue, ... },   # the baseline = the default
    red:    { cue, ... }
  }
  ```
- The compiler renders the three-line block (per brief §3) into the Hevy exercise `notes` consistently — e.g. `🟢 … · 🟡 … · 🔴 … · use the lower of band/feel`. YELLOW is the default and must always be populated when `branches` is present.
- Only branch the **levers that should move** (cardio character, top-set RPE cap, optional set/exercise on/off). Non-branched exercises render as today.
- Test: an exercise with `branches` renders all three lines, YELLOW present; the GREEN spec never prescribes above-ceiling load relative to YELLOW+defined-add (subtract-only invariant check).

### 3. Week-position helper — `training_context(target_date) -> {consecutive_days, deficit_state, tissue_ramp}`

- `consecutive_days`: streak length from recent-workout history (freshness-gated).
- `deficit_state`: from `get_deficit_sustainability` / recent nutrition (deep/moderate/maintenance).
- `tissue_ramp`: sessions-into-block for novel patterns (drives the GREEN tendon cap, Iris).
- The authoring path consumes this to **lower the GREEN ceiling and raise floors** late-week / deep-deficit / early-ramp (brief §4).
- Test: day-6 streak + deep deficit → GREEN branch caps quality (no load PR), RED triggers earlier.

### 4. (Optional, gated) overnight re-stamp Lambda — `routine_restamp`

- Post-Whoop-sync cron. **Only if** morning recovery lands before a configurable cutoff, update the day's routine to **pre-highlight** the matching branch (and optionally re-title with the band). 
- **Guardrails (enforced by test):** never deletes the other branches; idempotent; **no-op if recovery is late or missing**; logs the action taken. Anything depending on it must still work if it never runs.
- Do NOT build this in v1 unless Matthew locks it on (brief §8). Self-selection is the v1 solution.

### 5. Authoring protocol encoding (Part A as reusable config)

- Encode the §3 rubric + the "lower of band/feel" rule + the band thresholds (67/34) as a single config/constant the authoring path and the rendered cue both reference — so the format is consistent and changes in one place.
- Surface in the dry-run preview: the branch block per exercise **and** an `inputs_current_through: <date/session>` line (the preflight Matthew eyeballs in 30s).

---

## TESTS (one per edge case in brief §5)

- E1/E2 absent/late recovery → YELLOW default rendered.
- E3 stale volume → gate blocks compile (the headline test).
- E4 RED → floor branch present (no improvisation needed).
- E5 conflicting → rubric line present; feel-downgrades-only documented in cue.
- E7 weekly → each day's routine compiles independently with no dependency on prior-day actuals.
- E8 late-week → floors raised via `training_context`.
- E11 re-stamp late/missing → branches intact, session still valid.
- Subtract-only invariant → GREEN never exceeds the authored ceiling.

---

## DEPLOY (Matthew runs in terminal — never via MCP)

- `manage_hevy_routine` lives in the MCP package → `bash deploy/deploy_mcp_split.sh` (full `mcp/` dir); `pytest tests/test_mcp_registry.py` green first; tool fns before `TOOLS={}`.
- New helper Lambdas (`routine_restamp`, if built) → `bash deploy/deploy_lambda.sh`; new scripts to `deploy/`, `chmod +x` or `bash deploy/<script>.sh` (tell Matthew which).
- Wait 10s between sequential deploys.

## OUTPUT OF THIS BUILD

Freshness gate enforced in the authoring path (E3 structural) → `branches` structured field + consistent rubric rendering → `training_context` ceiling/floor modulation → dry-run preflight line. Re-stamp only if locked on. Every brief §5 edge case has a test. **The acceptance bar: a routine authored the night before is correct on complete data and self-adapts at 5am off the wrist band with a safe default — no morning platform interaction, no improvised audible.**
