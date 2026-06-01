# Build Outline — Hevy Routine Write-Loop

> **Destination in repo:** `docs/SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31.md`
> **Date:** 2026-05-31
> **Status:** Pre-build outline — approved to outline by all three boards
> **Review:** `docs/reviews/REVIEW_HEVY_ROUTINE_WRITELOOP_2026_05_31.md`

This is an outline, not an implementation spec. It captures architecture, phasing, and the constraints the boards baked in. A full spec follows once prerequisites (§10) clear.

---

## 1. Goal & scope

Close the **program → perform → adapt** loop with Hevy. Generate and author training routines informed by data Hevy doesn't have (recovery, volume landmarks, labs), write them to Hevy, then read back what was actually performed.

Non-goal (for now): replacing in-app routine editing. Hevy remains authoritative for what was performed.

## 2. Phasing (sequence is a gate)

- **Phase 1 — Conversational authoring.** Chat path only. IR + Hevy compiler + exercise-ID mapping + write client + commit gate + dry-run. Validates the hard parts under human supervision. *Ship and use for ~3 weeks before Phase 3.*
- **Phase 2 — Close the loop.** `ROUTINE#` partition; link IR to performed workouts; programmed-vs-performed adherence as a queryable metric.
- **Phase 3 — Automated generation (gated).** EventBridge cron. Only built if (a) real Phase-1 usage justifies it, (b) generated routines clear the "meaningfully better than hand-built" bar, (c) Pause-Mode gate in place. Daily readiness "add load" autoregulation only after signal validation.

## 3. Architecture — one write path, two front doors

```
coaching / generation logic
        │
        ▼
  routine-spec IR  ◄── system of record (persisted, versioned, ROUTINE#)
        │
        ▼
   Hevy compiler   ◄── sole owner of Hevy wire format (one module)
        │
        ▼
 create_routine / update_routine  →  Hevy
```

Both front doors (chat + cron) stop at the IR. The compiler is the only component that knows Hevy's schema.

**Components**
- Routine-spec IR (internal representation; format-agnostic)
- Hevy compiler module (encapsulated wire format)
- Exercise-template-ID mapping + cache
- Hevy write client (create/update routine, folders)
- Conflict detection (in-app edit protection)
- Pause-Mode gate (Phase 3)
- Adherence readback (Phase 2)

## 4. Data model

- **`ROUTINE#` partition** — versioned IR records; the audit trail of proposed → pushed.
- **ID mapping** — `platform_routine_id → hevy_routine_id`, written transactionally; never name-match for identity.
- **Workout link** — relate IR to performed-workout records so adherence-to-program is queryable.

## 5. Exercise-template-ID mapping (the load-bearing part)

- Cached mapping: internal movement vocabulary → Hevy template ID (S3/DynamoDB, TTL refresh).
- Policy for gaps: custom in-app exercises, and movements with no clean Hevy match.
- **Loud failure** on unmappable movements — error, never silently drop an exercise.

## 6. Programming-quality guardrails (Personal Board — baked into the generator)

- **Default near MEV**, progress slowly. Landmark-aware (`get_muscle_volume`).
- **Asymmetric autoregulation** — may only *subtract* load (deload on red recovery / high ACWR via `get_acwr_status`), never *add*, until readiness signal validated (N≥30).
- **Floor routine** — always produce a ≈20-min minimum-effective-dose session alongside the ideal plan.
- **Re-entry routine** — after a break: deliberately easy, no accumulated guilt-debt.
- **Portfolio awareness** — protect Zone 2 / mobility (`get_zone2_breakdown`); strength must not crowd out the aerobic base.
- **Joint-friendly bias** — favor machine/DB over high-skill barbell when programming unsupervised (until Sports Medicine seat filled).
- **Henning standard** — any claim about Matthew's optimum is a preliminary pattern, framed correlatively.

## 7. Safety & security

- **Commit gate** — chat path drafts → Matthew approves → write. No write on inferred intent.
- **Dry-run mode** — preview the compiled routine before any live write.
- **Own Secrets Manager secret** for the write-capable Hevy key (not bundled).
- **Bounded outputs** — hard caps (sets/volume/frequency) so a bug can't program absurd loads.
- **Webhooks** (if used) — validate signatures; treat inbound as untrusted.
- **Overwrite protection** — update-in-place via stable identity; conflict detection refuses to clobber a routine modified more recently in-app (same pattern as the publish-script conflict detection).

## 8. Operational requirements

- Idempotent + resumable generator (half-completed cron must not duplicate).
- Transactional id-mapping writes.
- Hevy outage handling: retry w/ backoff → dead-letter → alert. Never silently skip a week.
- Cache exercise templates; respect Hevy rate limits.

## 9. MCP surface

- Fold the write capability into **fewer fat tools** (e.g. one `manage_hevy_routine` with an action param) rather than 5 thin tools — respects SIMP-1 Phase 2 (≤80 tools).
- Tool function **before** `TOOLS={}`. Implementing function in the **same commit** as registration.
- `python3 -m pytest tests/test_mcp_registry.py -v` green before any MCP deploy.
- Deploy via `bash deploy/deploy_lambda.sh` (auto-reads handler config).

## 10. Open decisions / prerequisites before build

Prereq closures captured in `SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31_PREREQS.md` (2026-05-31).

- [x] Verify **Hevy API contract** — OpenAPI spec pulled; key surprises: no routine DELETE, no webhooks, no documented rate limits, `updated_at`-only conflict detection. Implications listed in PREREQS §A.11.
- [x] Decide **deterministic generation engine** design — pseudocode + test plan in PREREQS §B. Subtract-only autoregulation; MEV default; floor + re-entry variants; bounded outputs.
- [x] Define **readiness-signal validation** plan — pre-registered N≥30 design in PREREQS §C. Decision rule and public-site framing locked.
- [x] Fill or stand up interim **Sports Medicine / Movement Quality** Personal Board seat — Option 1 approved (2026-05-31); interim "Dr. Iris Tanaka — Sports Medicine (interim)" noted in `docs/BOARDS.md`. Live S3 board config update deferred to Phase 1 build commit. Phase 1 fully unblocked.

## 11. Doc-update implications (when this lands)

Per the doc trigger matrix: CHANGELOG + PROJECT_PLAN always; ARCHITECTURE + SCHEMA + DECISIONS (ROUTINE# partition, new write path); MCP_TOOL_CATALOG + RUNBOOK (new tools/ops); COST_TRACKER if any new service. Archive this outline to `docs/archive/` once the full spec supersedes it.
