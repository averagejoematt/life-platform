# HANDOVER — Coherence Program (Phases 1–3 done) + Coaching + Nutrition — 2026-06-28

**Next up:** Phase 4 of the Self-Management & Coherence Program (self-healing eyes on content). This handover is written to start Phase 4 cleanly after a compaction.

---

## What shipped this session (12 PRs merged to `main`, #237–248)

### Coaching (#237–243) — all merged + deployed
- `/coaching/` recut **commentary-first** (The Read · By Coach · Scorecard · Team · lab-notes · Reader Q&A).
- **C-1** experiment arc — `generate_experiment_arc()` in `ai_expert_analyzer_lambda.py` → `/api/experiment_synthesis`.
- **C-2** cardio-vs-lifts + per-muscle balance on the training coach (front-end off `/api/training_overview`).
- **C-3** gradable predictions + `/coaching/scorecard/`. Root cause: 248/248 machine preds had `threshold=None`. Fix: metric+direction → directional/EWMA evaluator (`coach_state_updater._build_prediction_eval_spec` + `_infer_direction`); `handle_predictions` reads real `PREDICTION#`. **Did NOT** backfill the 296 legacy dead preds (unsafe + would freeze natural expiry — see `project_coaching_redesign`).

### Nutrition 24h-lag (#244) — merged + deployed + live
MacroFactor is a manual end-of-day upload → **always ~24h behind by design**. Every surface now treats the latest COMPLETE day as live, never "not logged today". See `project_nutrition_24h_lag`. ⚠️ The `ai_calls.py` coach guardrail is a **layer module** — merged but **NOT live until the next layer rebuild** (low urgency; the brief coach is already "yesterday"-framed).

### Coherence Program Phases 1–3 — built + merged (Phase 1 deployed + LIVE)
**Thesis:** the platform proves it's ALIVE but not RIGHT. Every silent-incoherence bug (predictions 100%-inconclusive-for-weeks, 30-vs-86, arc 7-vs-3, `handle_predictions` all-zero) is *incoherent-but-green* from implicit producer/consumer contracts.

- **Phase 1 — Coherence Sentinel (#245, DEPLOYED + LIVE).** `lambdas/operational/coherence_sentinel_lambda.py` (function `life-platform-coherence-sentinel`, daily 10:45 AM PT, read-only). Runs 5 pure invariants in `lambdas/coherence_invariants.py` (each unit-tested by replaying a real past outage) → emits `LifePlatform/Coherence` metrics → the `coherence-overall` DIGEST alarm (`monitoring_stack.py`), plus a budget-gated Haiku semantic pass. **It found real bugs on its first live run** (coaches inventing weight-loss numbers; protein 140/170/190 still in narratives). Deterministic facts check hardened for precision over 3 live iterations. `prediction_health` now counts only **gradable** predictions → currently GREEN.
- **Phase 2 — shared contracts (#246/#247).** `lambdas/measurable_metrics.py` (MEASURABLE_METRICS derived from METRIC_SOURCES — un-driftable) + `lambdas/canonical_facts.py` (one facts schema + units + a producer-contract test). Both behavior-identical.
- **Phase 3 — deploy hygiene (#248).** Clobber guard in `deploy/sync_site_to_s3.sh` + `deploy/session_postflight.py` (layer uniformity + config drift).

**All three new shared modules are bundled with the `lambdas/` asset (NOT the layer) — no layer dance to deploy.**

---

## State of `main`
- All 12 PRs merged. `main` contains everything. Phase 1 is **deployed live** (`LifePlatformOperational` + `LifePlatformMonitoring` deployed; the sentinel function + alarm exist). Phases 2–3 are merged but **behavior-identical / not behaviorally deployed yet** (no urgency — they only remove drift surface; pick up on the next relevant deploy).
- The Coherence Sentinel currently reads **GREEN** when invoked (`aws lambda invoke --function-name life-platform-coherence-sentinel ... '{}'`).

---

## Open follow-ups (small, do early in Phase 4 or alongside)
1. **Sentinel adopts `canonical_facts`** — `coherence_sentinel_lambda._gather_facts_and_narratives` still builds its facts dict inline; both it and `canonical_facts.py` are now on main, so swap it to `build_canonical_facts(...)`. Closes the grounding↔detection loop (the coach is grounded on, and the Sentinel checks against, the *same* extraction). Redeploy the sentinel single-fn (`deploy/deploy_lambda.sh life-platform-coherence-sentinel lambdas/operational/coherence_sentinel_lambda.py --extra-files lambdas/coherence_invariants.py`).
2. **email-subscriber config drift** — `session_postflight.py` found CDK=15s vs live=30s. Decide: align the CDK value or `cdk deploy LifePlatformOperational`.
3. **`ai_calls.py` nutrition guardrail** rides the next layer rebuild (build_layer → bump SHARED_LAYER_VERSION → cdk deploy LifePlatformCore → redeploy consumers).

---

## Phase 4 — self-healing eyes on content (the next task)
**Goal:** the remediation agent gains awareness of *content/correctness* failures (today it only triages infra: CloudWatch alarms, failed CI, DLQ).

**Key files:** `remediation/agent.py` (triage loop — gathers signals, invokes Claude on Bedrock, opens PRs), `remediation/automerge.py` (deterministic auto-merge gate — ALLOWLIST/DENYLIST, ≤60 lines, daily cap 3), `docs/REMEDIATION_TAXONOMY.md`, `.github/workflows/remediation-agent.yml`. Kill-switch: SSM `/life-platform/remediation-mode` (off|shadow|auto).

**Approach (scoped, SAFE-FIRST — this touches the auto-merge/kill-switch machinery):**
1. **Check first** whether the agent already ingests the `coherence-overall` alarm — it pulls CloudWatch alarms in ALARM state, and `coherence-overall` is now a real alarm, so item 1 may be largely free. Verify in `remediation/agent.py` how it lists alarms.
2. Add Coherence Sentinel findings as a triage signal source if not already covered by the alarm.
3. Add **content-remediation classes** to `docs/REMEDIATION_TAXONOMY.md` (e.g. "re-run a stuck compute", "re-trigger prediction extraction") — start as **open-PR / needs-human, NOT auto-merge** (content stays OFF the deterministic allowlist until proven).
4. Optionally: a scheduled monthly deep **semantic audit** via the `Workflow` harness (multi-agent `/accuracy-review` pattern).

**DO NOT** widen the auto-merge allowlist to content without explicit sign-off — the whole safety model is that the agent (read-only role) only opens PRs and a deterministic gate merges a narrow allowlist.

---

## Verification / commands
- Sentinel live: `aws lambda invoke --function-name life-platform-coherence-sentinel --region us-west-2 --cli-read-timeout 0 --payload '{}' /tmp/s.json && python3 -c "import json;print(json.loads(json.load(open('/tmp/s.json'))['body'])['digest'])"`
- Postflight: `python3 deploy/session_postflight.py`
- Tests: `python3 -m pytest tests/ -k "coherence or measurable or canonical or gradability" -q`
- Deploy authority: Matthew authorized deploys this session; the "I run deploys" boundary is per-change for new IAM (the cdk deploy of the sentinel needed explicit sign-off, which he gave).

## Memories updated
`project_coaching_redesign`, `project_reader_engagement_loop`, `project_nutrition_24h_lag` (new), the Self-Management & Coherence Program pointer in `MEMORY.md`.
