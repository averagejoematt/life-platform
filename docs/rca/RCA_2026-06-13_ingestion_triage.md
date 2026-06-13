# RCA — Ingestion & MCP Triage (pre-Monarch)

**Date:** 2026-06-13
**Trigger:** Phase 0 of the Monarch financial-integration eval cross-checked Monarch's transaction truth against native sources and found two "dead" behavioral feeds + two broken MCP query tools. Triage gates the Monarch build (`WORKORDER_ingestion_triage.md`).
**Scope:** 4 findings. Covers root cause, fix, and the systemic-vs-independent verdict.

---

## Finding 1 — `food_delivery` reported false "clean" for 77 days

**Symptom:** `get_food_delivery` returned `behavioral_state: "clean", this_month_order_count: 0`, while Monarch showed continuous DoorDash through 2026-06-10. Last import 2026-03-28 (77d).

**Root cause — two layers:**
1. `food_delivery` is a **manual CSV import** — S3-`ObjectCreated` trigger on `uploads/food_delivery/*.csv`. No CSV had been uploaded since 2026-03-28; the Lambda is healthy, the feed is simply unfed. **Not a broken pipeline — an abandoned manual feed.**
2. The dashboard's `_classify_state(index, streak_days)` maps `delivery_index == 0` to `"clean"` — and a *no-import* month produces `index == 0` identically to a *zero-orders* month. The platform asserted a clean streak it had no current data to back. The 90-day freshness threshold (set for "quarterly CSV") let the dead source read "fresh" for a full quarter, hiding it.

**Fix (shipped):**
- `mcp/tools_food_delivery.py`: staleness guard — derive `data_age_days` from the freshest known date; when > 35d, return `behavioral_state: "stale"`, `data_stale: true`, `data_age_days`, and an explicit note ("'clean' cannot be asserted without current data — cross-check Monarch"). Verified live: now reports `stale, 80 days`.
- `freshness_checker_lambda.py`: `food_delivery` threshold 90d → **14d** (the masking was itself a defect).

---

## Finding 2 — `macrofactor` unfed since 2026-04-11

**Symptom:** Freshness flagged `macrofactor` stale (last 2026-04-11, 63d).

**Root cause:** `macrofactor` is also a **manual CSV feed** (MacroFactor app export → Dropbox → `dropbox-poll` → `uploads/macrofactor/*.csv` → ingestion, ADR-061). The user stopped exporting on 2026-04-11. The freshness checker already carries the note **"dead since 2026-04-11 (Tier 1 torn down)"** — a deliberate decommission, not a silent failure. Pipeline healthy; feed abandoned.

**Fix:** None required to the pipeline. Resumption is a user/product decision (resume MacroFactor logging, or let an automated source replace nutrition tracking). Left as-is; the "Tier 1 torn down" annotation stands.

---

## Finding 3 — `get_weight_loss_progress` raised a ValidationException

**Symptom:** DynamoDB `BETWEEN` lower bound `DATE#2026-06-14` > upper `DATE#2026-06-13`; explicit `start_date`/`end_date` ignored.

**Root cause:** `effective_start = journey_start if journey_start else start_date` — the cycle-4 reset set `journey_start_date = 2026-06-14` (**tomorrow**), and `end_date` defaults to today (06-13), so the query got start > end. Separately, `journey_start` always overrode an explicit `start_date`. (The work order's "today+1 timezone" hypothesis was a near-miss — the real cause was a re-anchored genesis dated ahead of "now".)

**Fix (shipped, `mcp/tools_health.py`):**
- Honor an explicit `start_date` verbatim (the ADR-058 phase filter already prevents pre-genesis leakage, so the old genesis-clamp was redundant *and* harmful).
- Future/empty-window guard: when `effective_start > end_date`, return a graceful `pre_genesis` payload instead of letting `query_source` raise.
- Regression test: `tests/test_health_window_guards.py` (no-dates + future genesis → no start>end query; explicit dates → honored verbatim).

---

## Finding 4 — `get_body_composition_trend` returned "No Withings data"

**Symptom:** Returned no-data while freshness showed `withings` fresh (synced today).

**Root cause — source mismatch:** the handler queries `withings` for `body_fat_percentage`/`muscle_mass_lbs`, but the Withings scale here is **weight-only** — it has *never* carried body-composition fields (verified across cycles 1–3). Body composition lives in a separate **`dexa`** source (rich nested schema, last scan 2026-03-30). The freshness checker sees Withings weight (fresh); the body-comp query finds no comp fields → misleading "No Withings data." Compounded by the same window-bug class as F3 and, post-reset, the phase filter hiding all pre-genesis records.

**Fix (shipped, `mcp/tools_health.py`):**
- Same window guard + explicit-`start_date` honoring as F3 (regression-tested alongside).
- Honest messaging: "Body composition isn't available from the Withings scale (weight only). It comes from periodic DEXA scans — see the dexa source. A trend needs ≥2 scans." (was the misleading "Check Withings ingestor captures these fields.")

**Follow-up (not done — tracked):** repoint `get_body_composition_trend` to read the `dexa` source (nested-schema remap). Deferred because only **one** DEXA scan exists — a *trend* is impossible until ≥2, and the remap is a feature-sized change.

---

## VERDICT — independent failures, not a systemic ingestion problem

**The two dead feeds (`food_delivery`, `macrofactor`) are both abandoned MANUAL user-driven CSV/export feeds, not automated pipelines, and they share no broken scheduler, credential store, or freshness-checker silence window.** They died ~2 weeks apart because the user stopped doing the manual export — a *behavioral* common cause, not an infrastructure one. The automated API-pull sources are healthy with one unrelated exception (Whoop, down on its own OAuth refresh-token expiry — see `setup_whoop_auth.py`). The two MCP tool breakages (F3, F4) are independent code bugs surfaced/aggravated by the cycle-4 reset, now fixed.

**Gate decision: CLEARED for the Monarch build.** There is no systemic ingestion failure to fix first. Moreover, Monarch (automated, server-side API pull) is the *correct* architectural answer precisely because it removes the manual-export dependency that killed both `food_delivery` and `macrofactor` — and it becomes the delivery source of record (the Main-Board decision in the design brief), with `food_delivery` reconciled/retired.

**Threshold audit:** `food_delivery` was the egregious masker (90d → 14d, fixed). `measurements` at 60d is borderline (genuinely monthly body-tape cadence) — flagged for review, not changed. Other overrides (`withings` 7d, `todoist` 48h) are appropriately tight.
