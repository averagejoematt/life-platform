# HANDOVER — 2026-06-19 · Readiness score data-integrity (date honesty + Garmin de-weight) + model convergence

> **MCP tool is DEPLOYED + verified live.** The precompute convergence (2 files) is still
> working-tree only, pending the deploy decision in §7. No PR opened yet.

---

## 0a. Deploy state
| Area | State | Notes |
|---|---|---|
| `life-platform-mcp` (`tool_get_readiness_score`) | ✅ **DEPLOYED 2026-06-19 16:22 UTC + verified** | full `mcp/` zip (not `deploy_lambda.sh` — its guard blocks single-file MCP); smoke-test below |
| `daily-metrics-compute` + daily-brief (sleep 30→25) | ⏳ **NOT deployed** | deliberate — see §4 (nudges stored colour). Deploy after QA. |
| `docs/coaching/TRAINING_CALIBRATION.md` (chat-instruction calibration) | ✅ committed `45d304aa` + pushed | §4a session-construction rules + §6 morning-of readiness gate (authored by chat session) |

**Live smoke-test** (forward-dated request `date=2026-06-25`): `date:2026-06-19` (real data date,
not the request), `requested_date:2026-06-25`, `is_forward_dated:true`, `staleness_warning` present,
`74.3 GREEN`, Garmin gated out, weights 40/25/20/10/5. The date-lie bug is dead in prod.

**Remaining cross-check split** (74 GREEN live vs 65 yellow precompute) is now *honestly labelled*
but not fully closed: ~small part is the undeployed sleep 30→25; the **larger** part is a separate,
untouched divergence — the two models use different colour thresholds (live GREEN ≥70 vs precompute
GREEN ≥80 / YELLOW ≥60). Threshold alignment is a deliberate decision item (see §7), not done.

---

## 0. What changed (4 files + 1 new test)

| File | Change |
|---|---|
| `mcp/tools_health.py` | `tool_get_readiness_score`: both data-integrity bugs fixed (date honesty + Garmin freshness gate / de-weight) |
| `lambdas/compute/daily_metrics_compute_lambda.py` | `compute_readiness`: sleep weight 30→25% (model convergence) |
| `lambdas/emails/daily_brief_lambda.py` | duplicate `compute_readiness`: sleep weight 30→25% (kept in sync) |
| `docs/MCP_TOOL_CATALOG.md` | line 54 readiness weights → 40/25/20/10/5 + staleness-flag note |
| `tests/test_readiness_forward_dated.py` | **new** — forward-dated path regression test |

## 1. Bug 1 — future-stamped stale data (live MCP tool)
Each component pulls a 7-day window and takes the newest available record, but the result dict
hardcoded `"date": end_date`. Asking for a date whose overnight hasn't happened yet returned
yesterday's components stamped with the requested date. Component `raw.date` fields were honest;
only the top-level `date` lied.

**Fix:** after `components` is built, compute `as_of_date = max(raw.date)` across the only three
components that carry a date (`whoop_recovery` / `sleep_quality` / `garmin_body_battery`, guarded
for missing). Then:
- top-level `"date"` → `as_of_date` (the real data date)
- added `"requested_date"`, `"is_forward_dated"` (= `as_of_date < end_date`)
- when forward-dated, added `"staleness_warning"` saying no data exists for the requested date yet,
  so the score is a current/trend signal, not the requested day's readiness.
All existing keys preserved (no caller breaks).

## 2. Bug 2 — Garmin Body Battery freshness gate + structural de-weight (live MCP tool)
Garmin ingestion is unreliable (datacenter-IP OAuth crackdown — see CLAUDE.md Garmin RCA); Body
Battery could be days stale and still enter the score at full 10% weight.

**Fix:**
- Freshness gate: skip `garmin_body_battery` entirely when `date_diff_days(garmin_date, whoop_date) > 1`
  (>1 day staler than newest Whoop). Existing weight re-normalisation redistributes onto Whoop.
- Base weights: Garmin Body Battery **0.10 → 0.05**, Whoop recovery **0.35 → 0.40** (Garmin structurally
  de-weighted even when fresh).
- Updated docstring, `scoring_note`, and the (previously **stale/lying**) `_precomputed_cross_check` note.

## 3. The "second model" — important correction to the original premise
The task assumed the precompute weighted Body Battery at 15% (per the live tool's cross-check note).
**It doesn't.** Traced it: the live tool reads `readiness_score` from `computed_metrics`, written by
`daily_metrics_compute_lambda.compute_readiness` (an identical duplicate lives in
`daily_brief_lambda.compute_readiness`). **Both** were recovery 40 / sleep 30 / HRV 20 / TSB 10 — **no
Garmin/Body-Battery component at all, no sleep-debt term.** The "Body Battery 15% + sleep debt 5%"
claim existed **only in the stale cross-check note** (now corrected). Searched all of `lambdas/` for
`body_battery`/`readiness`/`compute_readiness`/`0.15`/`sleep debt` to confirm — only other Body-Battery
use is `hypothesis_engine_lambda.py` (a correlation row, not a readiness score).

**Decision (with user):** do NOT add Body Battery to the precompute — that would thread unreliable
Garmin into a second production path (day grades / emails / correlations) just to recover a 5% term.
Instead, the minimal safe convergence: precompute sleep **30 → 25%** in both copies. Result: both
become recovery 40 / sleep 25 / HRV 20 / TSB 10, identical to the live tool on the typical day
(Garmin stale → Body Battery gated and re-normalised out). The `_precomputed_cross_check` is now a
true drift detector instead of always showing structural noise.

## 4. ⚠️ Behavioral note for QA
The precompute sleep 30→25 change slightly shifts the stored `readiness_score` / `readiness_colour`
that feeds **day grades, the daily brief, and weekly correlations** — once
`life-platform-daily-metrics-compute` and the daily-brief lambda are deployed. Recovery (40%, the
dominant term) is unchanged; the shift is small but real. Nothing is deployed yet.

## 5. Verification done
- `pytest tests/test_mcp_registry.py` ✅ · `tests/test_readiness_forward_dated.py` ✅ ·
  `tests/test_health_window_guards.py` ✅ · `tests/test_daily_brief_golden.py` ✅ (fixture value, no golden drift)
- `black --line-length 140 --check` clean on all 3 edited files + the new test
- flake8 on `tools_health.py` shows only **pre-existing** F401/F841/E203 noise (none in edited regions)

## 6. Hevy sync (this session, on request)
Manually invoked `hevy-backfill` (the **primary** Hevy ingestion path — `hevy-webhook` is parked since
Hevy publishes no webhooks). Clean: `ingested:0 deleted:0 errors:0 pages:1`, `since` advanced to
2026-06-19T16:11 UTC. Up to date.

## 7. Follow-ups / deploy plan
- ✅ **DONE** — MCP tool deployed via full `mcp/` zip (NOT `deploy_lambda.sh` — its guard blocks
  single-file MCP packaging; use `zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/` then
  `aws lambda update-function-code --function-name life-platform-mcp`). **No layer rebuild needed.**
- ⏳ **After QA** — deploy precompute convergence: `life-platform-daily-metrics-compute` + the
  daily-brief lambda (sleep 30→25). Nudges stored readiness colour (§4) — deploy deliberately.
- 🔲 **Decision** — threshold alignment: live GREEN ≥70 vs precompute GREEN ≥80 / YELLOW ≥60 is the
  *larger* remaining source of the cross-check colour split. Not a bug; needs a call. Candidate for
  the page-by-page `/plan` batch.
- 🔲 Open a PR to bring `main` in sync (code + `docs/MCP_TOOL_CATALOG.md` still uncommitted). The
  calibration doc is already committed/pushed (`45d304aa`).
- Pre-existing uncommitted `docs/*` edits (COST_TRACKER, INFRASTRUCTURE, RUNBOOK, SCHEMA, SLOs) were
  already in the tree at session start — **not mine**, left untouched.

**Verified:** 2026-06-19. Tests green per §5. MCP tool deployed + smoke-tested live (§0a); precompute
convergence pending QA.
