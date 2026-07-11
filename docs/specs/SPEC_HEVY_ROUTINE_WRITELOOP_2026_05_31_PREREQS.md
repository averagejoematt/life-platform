# Prerequisites — Hevy Routine Write-Loop

> **Companion to:** `docs/specs/SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31.md` §10
> **Date:** 2026-05-31
> **Status:** §A, §B, §C, §D all closed (§D Option 1 approved 2026-05-31)

Closes (or stages) the four open items blocking Phase 1 build.

---

## A. Hevy API Contract (verified)

Pulled from the published OpenAPI 3.0 spec (mirrored at `chrisdoc/hevy-mcp/openapi-spec.json`, sourced from `api.hevyapp.com/docs/`). Verify against live spec at build time.

### A.1 Auth & transport
- **Base URL:** `https://api.hevyapp.com`
- **Auth:** `api-key` request header (UUID); required on every endpoint
- **Hevy PRO required.** Already held.

### A.2 Routine endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/routines` | Paginated list |
| POST | `/v1/routines` | Create |
| GET | `/v1/routines/{routineId}` | Get one |
| PUT | `/v1/routines/{routineId}` | Update (full document, not PATCH) |

**No DELETE.** Hevy does not expose routine deletion via API.

### A.3 Routine request schema (create)

```
workout (required)
├── title (string, required)
├── folder_id (number, nullable; null = "My Routines")
├── notes (string)
└── exercises (array, required)
    ├── exercise_template_id (string, required)
    ├── superset_id (int, nullable)
    ├── rest_seconds (int, nullable)
    ├── notes (string, nullable)
    └── sets (array)
        ├── type (enum: warmup|normal|failure|dropset)
        ├── weight_kg (number, nullable)
        ├── reps (int, nullable)
        ├── distance_meters (int, nullable)
        ├── duration_seconds (int, nullable)
        ├── custom_metric (number, nullable)
        └── rep_range (object, nullable; {start, end})
```

### A.4 Routine response schema (read)

Includes `id` (UUID string), `updated_at` (ISO 8601), `created_at` (ISO 8601), and per-exercise `index` ordering. `rpe` may be present on sets (read-only — not in request body).

### A.5 Update semantics & overwrite protection

- PUT requires the **full** routine body.
- **`folder_id` is absent from PUT body** → folder assignment is set-on-create only.
- **No etag, no version field.** Conflict detection uses `updated_at` only.
- **Pattern:** GET-before-PUT. Compare returned `updated_at` against the value the platform last persisted; refuse the PUT if remote moved (Hevy in-app edit detected). Same stance as the publish-script conflict guard.

### A.6 Exercise templates

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/exercise_templates` | Paginated (pageSize ≤ 100) |
| POST | `/v1/exercise_templates` | Create custom |
| GET | `/v1/exercise_templates/{exerciseTemplateId}` | Get one |

- **ID format:** 8-char uppercase hex string (e.g. `D04AC939`).
- **Quirk:** custom-create response returns `{id: integer}`, not the string form. Mapping module must reconcile by listing/searching post-create.
- Template fields: `title`, `type`, `primary_muscle_group`, `secondary_muscle_groups[]`, `is_custom`.

### A.7 Routine folders

GET list, GET by id, POST create. **No update, no delete.** Folders are append-only.

### A.8 Webhooks
**Not present in spec.** Confirms the existing `hevy-webhook` Lambda stays parked (CLAUDE.md). Change tracking uses polling via `GET /v1/workouts/events` (returns events with `type: created|updated|deleted` and `deleted_at`).

### A.9 Rate limits
**Not documented.** Client must throttle defensively. Recommended:
- ≤ 1 req/sec sustained
- Token bucket in the write client; back off + DLQ on `429` or `5xx`
- Cache the exercise-template list (S3, 24h TTL) to avoid full re-fetch per generation

### A.10 Pagination
Offset-based: `page` (≥1), `pageSize`. Response carries `page` + `page_count`.

### A.11 Implications for SPEC

| Spec section | Change |
|---|---|
| §1 (scope) | "create, modify, **delete**" → "create, modify, **archive** (rename + folder-move; Hevy has no DELETE)" |
| §3 (architecture) | Compiler emits PUT full-document; Hevy client owns GET-before-PUT conflict check |
| §5 (template mapping) | Cache full template list; mapping is `internal_name → 8-char uppercase hex`; custom-create requires post-create reconcile |
| §7 (safety) | Overwrite protection = `updated_at` compare (named explicitly); webhooks-untrusted-input clause becomes moot |
| §8 (ops) | Polling cadence for `/workouts/events` defined (Phase 2 adherence); client-side throttle replaces any rate-limit assumption |

---

## B. Deterministic Generation Engine — design sketch

Decision: **deterministic core, no per-day LLM.** LLM only assists conversational authoring (Phase 1 chat path), never the cron generator (Phase 3). Rationale: Dana (cost recurring), Henning (auditability), Anika (bounded outputs).

### B.1 Inputs

All from existing MCP/data layer — no new ingestion required:

| Input | Source | Used for |
|---|---|---|
| Muscle-group volume landmarks (MV, MEV, MAV, MRV) | `config/training_landmarks.json` (new — small static config) | Per-muscle weekly set targets |
| Trailing 7-day completed sets per muscle | `get_muscle_volume` | Distance from landmarks |
| ACWR + recovery tier | `get_acwr_status`, Whoop recovery | Deload trigger (subtract-only) |
| Zone 2 minutes (7d) | `get_zone2_breakdown` | Portfolio guard (block strength volume bumps if aerobic base shrinking) |
| Last-completed-date per movement | `get_exercise_history` | Frequency / recency rotation |
| Movement vocabulary | `config/movement_catalog.json` (new) | Internal name → Hevy template ID + joint-friendliness tag + skill tier |
| Schedule shape | `config/training_week.json` (new) | Day-of-week slot → session archetype (upper/lower/full/aerobic/mobility) |

### B.2 Algorithm (pseudocode, not implementation)

```
def generate_routine(date, archetype, state):
    landmarks = load_landmarks()
    volume_7d = mcp.get_muscle_volume(7)
    acwr = mcp.get_acwr_status()
    recovery_tier = whoop_recovery_tier(date)
    z2_7d = mcp.get_zone2_breakdown(7).minutes

    # 1. Volume budget per muscle for THIS session
    budget = {}
    for muscle in archetype.target_muscles:
        weekly_target = landmarks[muscle].MEV   # default at MEV, not MAV
        remaining = max(0, weekly_target - volume_7d[muscle])
        session_share = remaining / sessions_left_this_week(archetype, muscle)
        budget[muscle] = clamp(session_share,
                               min=landmarks[muscle].MIN_PER_SESSION,
                               max=landmarks[muscle].MAX_PER_SESSION)

    # 2. ASYMMETRIC AUTOREGULATION — subtract only
    if recovery_tier == "red" or acwr.flag in ("high", "very_high"):
        budget = {m: v * 0.6 for m, v in budget.items()}     # deload
    # NEVER increase budget from a "green" recovery signal — readiness not validated

    # 3. Portfolio guard
    if z2_7d < state.z2_floor_minutes:
        # aerobic base eroding — don't crowd it; keep strength flat, don't expand
        budget = cap_at_prior_week(budget)

    # 4. Exercise selection — joint-friendly bias, skill-tier filter
    exercises = []
    for muscle, set_count in budget.items():
        candidates = catalog.movements_for(muscle)
        candidates = [m for m in candidates if m.skill_tier <= state.skill_ceiling]
        candidates = sorted(candidates,
                            key=lambda m: (m.joint_friendly_score,
                                           recency(m, state.history)),
                            reverse=True)
        chosen = pick_with_rotation(candidates, exercises)
        exercises.append(make_block(chosen, set_count, rep_range=chosen.default_range))

    # 5. Hard caps (bounded outputs)
    assert total_sets(exercises) <= state.session_set_ceiling   # default 25
    assert session_duration_estimate(exercises) <= state.session_minutes_ceiling   # default 75

    return RoutineSpec(date=date, archetype=archetype, exercises=exercises,
                       rationale=log_inputs_used())
```

### B.3 Two outputs per generation

Per Coach Maya's "floor routine" requirement, every generation produces **two** IR records:

1. **Ideal** — full session at the budgeted volume.
2. **Floor** — ≈20 min minimum-effective-dose variant (1 set per major muscle, ~5 movements, machine/DB only).

User picks at session time. Both written to the `ROUTINE#` partition; only one pushed to Hevy at a time (or both as separate routines in the same folder — TBD at implementation).

### B.4 Re-entry mode

Triggered automatically when `days_since_last_workout(state.history) ≥ 7`. Re-entry routine:
- Halves the budget vs. normal.
- Uses only joint-friendly machine/DB variants (skill tier 1).
- Tags rationale as "re-entry — no guilt-debt."
- Does **not** try to make up missed weekly volume. Pause-Mode principle.

### B.5 What stays out of the deterministic core

- Narrative coaching copy
- Cross-day periodization "reasoning"
- Anything that requires natural-language synthesis

Those live in the Phase 1 chat path, which uses the same IR but is authored by Matthew in conversation.

### B.6 Tests required before merge

- Golden tests: fixed inputs → fixed RoutineSpec (regression guard on landmark math)
- Property tests: no recovery signal can increase budget vs. baseline ("subtract only" invariant)
- Cap tests: bounded outputs hold against adversarial inputs
- Catalog tests: every muscle has ≥1 skill-tier-1 movement available

---

## C. Readiness-Signal Validation Plan

Honors Henning's dissent: until the readiness signal is shown to predict training capacity for Matthew specifically, the generator may only **subtract** load on it, never **add**.

### C.1 What we are testing
**Hypothesis:** Whoop recovery score (the proposed readiness signal) predicts within-session training capacity (top-set load × reps) on the same calendar day.

**Null:** recovery score is uncorrelated (Spearman ρ < 0.2 or 95% CI crosses zero) with same-day top-set capacity after controlling for the prior-week volume.

### C.2 Sample size & cadence
- **N ≥ 30 paired observations.** One observation = (morning recovery score, that day's top set on a recurring lift).
- Recurring lifts = the 4–6 movements that recur weekly in the deterministic catalog (e.g., goblet squat, DB bench, machine row).
- **Estimated time-to-N:** ~10–12 weeks at 3–4 strength sessions/week.

### C.3 Capacity outcome — definition
For each observation:
- **Primary:** estimated 1RM from top working set (Epley, weight × (1 + reps/30)), expressed as %-deviation from the trailing 4-session per-lift mean.
- **Secondary:** RPE on top set (if available; Hevy doesn't store this on request body, so logged separately).

### C.4 Confounders to control
- Prior-week volume (trailing 7d sets for that muscle from `get_muscle_volume`)
- Sleep duration prior night
- Days since last hit of that movement
- ACWR at session start

Model: partial correlation of recovery vs. capacity, holding the four above fixed. Pre-register the model before running.

### C.5 Decision rule (pre-registered)
- **Pass** → ρ ≥ 0.3 AND 95% CI lower bound ≥ 0.15 → "add load" autoregulation may be enabled.
- **Fail** → ρ < 0.2 OR CI crosses zero → keep subtract-only indefinitely; do not re-test for ≥ 6 months.
- **Inconclusive** → 0.2 ≤ ρ < 0.3 → continue collecting to N = 60 before deciding.

### C.6 What "passing" unlocks
Even on pass, "add load" is limited to **+10% volume on green recovery with low ACWR**, capped at MAV (never MRV). No "max effort" prescription from a single-day signal.

### C.7 What "failing" preserves
Failing is not a setback — it is the planned default. The generator ships with subtract-only autoregulation regardless of outcome; the validation only determines whether the symmetric ("also add") path is ever enabled.

### C.8 Public-site implications
Per Lena: averagejoematt.com may not describe the system as "autoregulated" while the signal is unvalidated. Current correct framing: "deterministic volume-landmark programming with red-day deload guard."

---

## D. Interim Sports Medicine / Movement Quality Seat — placeholder

**Status:** drafted for Matthew's review; not appointed.

The Personal Board has an open seat on Sports Medicine / Movement Quality. Phase 1 unsupervised programming benefits from one voice in the generator's exercise-selection guardrails. Two options:

### D.1 Option 1 — interim composite persona (recommended for Phase 1 only)

**Name (placeholder):** "Dr. Iris Tanaka — Sports Medicine (interim)"
**Mandate:**
- Veto rights on exercise catalog entries flagged as high-skill or high-injury-risk for an unsupervised lifter in late-30s, returning from break, multi-year inconsistency history.
- Joint-friendliness scoring rubric for catalog entries (0–3 scale, machine ≥ cable ≥ DB ≥ barbell as default tiebreak).
- Re-entry routine sign-off (the easy/no-guilt-debt variant).
- **Does not** opine on hypertrophy programming, periodization, or sports-specific work — explicitly scoped to "don't get hurt."

**Rationale:** a placeholder voice is better than no voice while unsupervised programming ships. Composite persona is honest about the gap (named "interim" in BOARDS.md) and easy to retire.

### D.2 Option 2 — leave seat empty, lean on existing personas

Coach Maya (concurrent training) and Dr. Nathan (re-entry / dropout) already cover overlapping ground. Generator hard-codes the joint-friendly bias rule from §B.2 without a persona attached. Risk: no human-voice veto in board reviews of future programming changes.

### D.3 Recommendation
**Option 1 for Phase 1 only**, with explicit sunset trigger: retire interim persona when a named Sports Med voice fills the real seat. Captured in `docs/BOARDS.md` change log if approved.

### D.4 Decision (2026-05-31)
**Approved: Option 1.** Interim "Dr. Iris Tanaka — Sports Medicine (interim)" placeholder noted in `docs/BOARDS.md`. Live S3 board config (`board_of_directors.json`) update deferred to Hevy write-loop Phase 1 build commit — keeps the BOARDS.md table accurate to the live config until the generator code actually invokes the persona.

---

## Status against SPEC §10

- [x] **A. Hevy API contract** — verified from OpenAPI spec; SPEC implications listed in §A.11
- [x] **B. Deterministic generation engine design** — pseudocode + tests defined
- [x] **C. Readiness-signal validation plan** — pre-registered design
- [x] **D. Sports Med seat** — Option 1 approved (2026-05-31); interim "Dr. Iris Tanaka — Sports Medicine (interim)" noted in `docs/BOARDS.md`; live S3 board config update deferred to Phase 1 build commit

Phase 1 build is fully unblocked. All four prereqs closed.
