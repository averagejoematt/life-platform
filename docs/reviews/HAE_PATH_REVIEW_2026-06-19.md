# HAE Ingestion Path — Surgical Deep Review (2026-06-19)

> Triggered by: Apple Health app shows ~5,700 avg steps/wk while DDB stored ~2,960; specific
> days badly undercounted (6/15 app ~6,500 vs DDB 402; 6/18 ~7,800 vs 444). User: "everything
> shows successful on the iPhone app but sometimes we see other issues."
> Scope: `lambdas/ingestion/health_auto_export_lambda.py` end-to-end + the HAE app automation/event logs.
> **Status:** root cause found + P0 code fix shipped (commit `9e98e093`); the unblock + history
> recovery are **deferred to 2026-06-20** (HAE aggregate-export change OR one-time file export).

---

## TL;DR — the headline: HTTP 413, the data never arrives

The 7-day step re-sync **never reaches us**. HAE exports **raw per-sample** step data
(`aggregateData=False`); over a multi-day window the payload is **24.8 MB**, and the Lambda
Function URL caps request bodies at **~6 MB** (API Gateway HTTP API at 10 MB) → **HTTP 413
Payload Too Large**, rejected at the edge before our Lambda runs. Confirmed in all three log sets:

| Automation | Max payload | Result |
|---|---|---|
| **Step counts** (7-day raw) | **24.8 MB** | **413** ❌ |
| **Activity** (raw, even `period=Today`) | **14.2 MB** | **413** ❌ (late-day runs) |
| Health Data | 1.4–5.0 MB | 200 ✓ |
| Water / Heart / Blood / Vitamins | < 0.3 MB | 200 ✓ |

**Why the phone shows success:** HAE logs `runAutomation_foreground → complete` *immediately
after* the 413 — "complete" means "ran and got an HTTP response," not "2xx accepted." A 413 reads
as a green checkmark. That is the exact "successful on the app but issues downstream" mechanism.

**Why the history is wrong (separate, older cause):** the **Activity** automation is
`period=Today` + the Apple **Watch→iPhone step-sync lag**. When the last hourly "Today" export
ran, the Watch hadn't synced its steps to the phone yet, so only the iPhone's partial count (e.g.
402) was in HealthKit — exported and accepted (small payload, 200). `period=Today` **never
re-sends past days**, so the wrong value is frozen. The dedicated "Step counts" feed was the right
instinct, but it's blocked by the 413.

---

## The fix — two paths (pick one tomorrow)

**A. Aggregate the step export (recommended, fixes 413 + dedup in one move).**
In the HAE **"Step counts"** automation, turn **`Aggregate Data` ON**. HAE then sends **one
Apple-deduplicated daily total per day** (= what the app shows) instead of thousands of raw
samples → payload **24.8 MB → a few KB**, no 413. Also remove `Step Count` from the **Activity**
automation so the aggregated feed owns it (no redundant 14 MB raw send). Same applies to any other
additive activity metric we want (distance, energy).

**B. One-time file export for history.** For the 7-day (or full-history) backfill, export from
Apple Health / HAE to a **file** (Dropbox/iCloud/S3) and use the existing import path — bulk
history does not belong in a 6 MB POST. Assets already present: `datadrops/apple_health_export/export.xml`
(full Apple Health export) and the `dropbox-poll` Lambda.

Once data arrives, the **P0 code fix** (below) makes it correct and durable.

---

## Findings by severity

### 🔴 P0 — additive-activity undercount in code — FIXED (commit `9e98e093`)
`pick_source_or_all` kept ONE priority source per day and **discarded the fuller device**; steps
were plain-**overwritten** so a later partial export could lower a fuller value. Affected
`steps, distance_walk_run_miles, active_calories, basal_calories, flights_climbed`.
**Fix:** `process_generic_metrics` now takes **MAX across per-source daily sums** for
`_ACTIVITY_MAX_FIELDS` (kills undercount AND double-count); `merge_day_to_dynamo` applies
**GREATEST(stored, new)** (monotonic — a partial re-export can't lower a day; backfill passes
`monotonic_guard=False`). Test that enshrined the bug updated (`..._iphone_wins` → `..._max_source_wins`). 16 tests green.

### 🟠 P1 — the 413 ingestion ceiling (config + infra)
Above. The 6 MB Function URL cap is a hard AWS limit. **Our Lambda never sees a 413** (rejected at
the edge → no log, no alarm, no DLQ) — a real observability blind spot. Mitigations: aggregate
exports (A), file-export for bulk (B), and a low-steps/stale-day anomaly guard on our side so a
silently-missing day is flagged (DI-1.4's `step_data_complete`/`step_coverage_pct` is a start).

### 🟠 P1 — UTC-day partitioning of inherently-local metrics
`parse_date_str` buckets every reading into its **UTC** day (TD-19, deliberate cross-source
consistency). For activity metrics this means our `DATE#YYYY-MM-DD` holds **PT 5pm→5pm**, so
evening (post-~5pm PT) activity bleeds into the next day's partition and our daily totals can
**never** match the Apple Health app (local-day). Decision needed: partition activity by local
(PT) day, or document that `apple_health` activity is UTC-windowed. Untouched (architectural).

### 🟠 P1 — `active_calories` never exported (config)
`Active Energy` is mapped correctly in code but **no `includeHealthMetrics=True` automation lists
it** (Activity's metric set omits it; Health Data has Basal Energy but not Active). Result:
`active_calories` is `None` every day → NEAT estimate, the `<200 active cal` sedentary clause, and
`total_calories_burned` (active+basal) all silently degrade. **Add `Active Energy` to the Activity
(or a dedicated) automation.**

### 🟡 P2 — no completeness/plausibility gate; silent drops
- Webhook returns `200 ok` whenever it doesn't crash — no validation that a day's data is complete
  or plausible (a 402-step day sails through).
- **Unmapped metrics are silently dropped** (logged "Unmatched", no alert).
- BP with missing diastolic writes `0` (not `None`).

### ✅ Sound
Raw payload archived every request (good for backfill/recovery); water/caffeine reading-level
timestamp dedup is correct; Tier-2 (HR/HRV/RHR) Apple-device filtering is right; workouts
deliberately not double-counted vs Strava; auth/base64/JSON-error paths return proper non-200s.

---

## Tomorrow's checklist
1. **Pick A or B** to get step history + ongoing steps flowing (A = aggregate "Step counts"; B = file export).
2. **Add `Active Energy`** to an `includeHealthMetrics=True` automation.
3. (Optional) remove `Step Count` from "Activity" to drop the redundant 14 MB raw send.
4. Once data lands, verify `get_daily_metrics(view="movement")` 6/13–6/19 matches the app; the P0 monotonic guard will let the corrected higher totals overwrite the stored 402/444.
5. **Then** run the DI-1 deploy batch (layer rebuild + `SHARED_LAYER_VERSION→87`, then the lambdas + MCP — see `HANDOVER_LATEST.md`).
6. Consider: our-side 413/low-steps anomaly guard (P1 observability); the UTC-vs-local partitioning decision (P1).

**Verified:** 2026-06-19. Logs analyzed: `datadrops/logs/{events.jsonl,events-prev.jsonl,automations.json}` (app v9.0.10). P0 fix committed + tested; not deployed.
