# Claude Code Kickoff — Training Feedback & Adaptive Authoring Workstream

> **Repo:** life-platform · **branch:** main · **Date:** 2026-06-21
> Paste this whole prompt into Claude Code to begin. It sequences the work and points to the detailed specs. Do the stages IN ORDER — later stages depend on earlier ones being trustworthy.

## Read first
- `docs/SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md` (+ its §10 data-integrity appendix)
- `docs/specs/CLAUDE_CODE_PROMPT_RECOVERY_ADAPTIVE_AUTHORING_v1.md`
- `docs/SPEC_HEVY_NOTES_FEEDBACK_LOOP_2026-06-21.md`
- `docs/specs/CLAUDE_CODE_PROMPT_HEVY_NOTES_v1.md`

## Working rules (all stages)
- Read the relevant spec before writing code. Deterministic core + tests BEFORE any I/O or model call.
- MCP: tool fn before `TOOLS={}`; implementing fn in the SAME commit as registration; `pytest tests/test_mcp_registry.py` green before any MCP deploy.
- Do NOT deploy — Matthew runs deploys in terminal (`bash deploy/deploy_lambda.sh`, `bash deploy/deploy_mcp_split.sh`). Tell him exactly what to run and which scripts need `chmod +x`.
- At every "STOP / report" gate below, stop and show findings — don't barrel into the next stage.

---

## STAGE 1 — Data integrity (do first; everything downstream trusts these reads)

The coaching engine was poisoned 2026-06-21 by reads that look "fresh" off a newest-record high-water-mark while hiding gaps behind it. Fix the shared instrument first. Detail: authoring brief §10 (B1–B3).

1. **B3 — `get_freshness_status` gap detection (shared root, highest leverage).** Make freshness detect *gaps behind the high-water mark*, not just recency: a missing mid-window day must surface, not read green. Update `freshness_checker_lambda.py` / `mcp/tools_labs.py`. Add a test: a source with the newest record present but an interior day missing → reports the gap.
2. **B2 — `get_muscle_volume` staleness + core-mapping.** (a) The aggregation must include the latest ingested sessions, or flag that it doesn't (the calf/core miscount). (b) Map anti-rotation/standing core (Pallof, carries) to **Core**, not `Other`, so `core_sets` is real. Tests for both.
3. **B1 — Strava walk ingestion gap (diagnose before fixing).** Run the diagnostic in authoring-brief §10/B1: pull Strava activity IDs Jun 14–20 from the API → diff vs the DDB Strava partition → read ingestion + enrichment Lambda logs for the missing IDs. **STOP and report** root cause (webhook-never-received vs dropped-in-enrichment) and whether `di1-movement-integrity` already fixes it. Do NOT backfill until Matthew approves the verdict.

**Gate:** report Stage 1 findings + fixes before Stage 2.

---

## STAGE 2 — Recovery-adaptive authoring (the thing that bit him; highest user value)

Per `CLAUDE_CODE_PROMPT_RECOVERY_ADAPTIVE_AUTHORING_v1.md`. Acceptance bar: **a routine authored the night before is correct on complete data and self-adapts at 5am off the Whoop wrist band with a safe default — no morning platform interaction.**

1. `authoring_freshness_gate(target_date)` — refuses to compile when volume/recovery/recent-workout inputs don't cover the latest ingested session (uses Stage 1's gap detection). Test: stale state → compile blocked.
2. `branches` structured field on routine-IR exercises → render the standard 🟢/🟡/🔴 block + "use the lower of band/feel" into Hevy notes. YELLOW always populated (the default).
3. `training_context(target_date)` → consecutive_days + deficit_state + tissue_ramp; authoring lowers the GREEN ceiling / raises floors accordingly.
4. Dry-run shows the branch block + `inputs_current_through: <date>`.
5. Tests = one per edge case in authoring-brief §5 (esp. E3 stale-block, E1/E2 default-to-yellow, subtract-only invariant).
6. Overnight re-stamp Lambda — **only if Matthew locks it on** (§8); else skip, self-selection is v1.

**Gate:** demo an authored adaptive routine + the gate blocking on stale data.

---

## STAGE 3 — Training feedback loop / notes (Phase 0 → Phase 1)

Per `CLAUDE_CODE_PROMPT_HEVY_NOTES_v1.md`. Source label `training_feedback_loop`. Real-time only (no edit-resync).

1. **Phase 0** — sync-fidelity check + freeze taxonomy/pain-lexicon from the 5-note seed corpus. **STOP and report.**
2. **Phase 1** — deterministic extractor (+ pain floor) → Haiku tail (hash-cache, cap, fail-safe) → exercise-keyed `training_feedback_loop` projection → `get_exercise_notes` read tool → pain elevation → freshness hook. Deterministic core green against the 5-note fixture (incl. pain-net with model stubbed, rpe_caveat-not-overwriting-raw, conservation) BEFORE any I/O or model call.
3. Additions (locked): `deviation` (pushed-vs-performed diff) + `rest_adherence` (prescribed-vs-actual rest, iff Hevy exposes it). Recovery-conditional descriptors are handled in Stage 2.
4. Do NOT build Phase 2 (loop-back, pattern detection) until Phase 1 is eyeballed privately.

**Gate:** Phase 0 report → (Matthew confirms taxonomy) → Phase 1 → private use.

---

## Doc hygiene (per the trigger matrix, when each stage lands)
CHANGELOG + PROJECT_PLAN always; SCHEMA + DECISIONS for new sources/projections/ADRs; MCP_TOOL_CATALOG + RUNBOOK for new tools; DATA_DICTIONARY for new derived domains; COST_TRACKER when the Haiku extractor runs at volume. Update `PLATFORM_FACTS` then `python3 deploy/sync_doc_metadata.py --apply`. Then Matthew commits.
