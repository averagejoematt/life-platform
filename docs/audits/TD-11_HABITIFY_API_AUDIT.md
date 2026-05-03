# TD-11 — Habitify API audit (Step 1)

**Date:** 2026-05-03
**Source spec:** `docs/specs/TD-11_HABITIFY_PHANTOM_HABITS.md`
**Step:** 1 of 5 (audit only — Step 2 schema design gated on Matthew approval)

---

## Audit method

Hit `https://api.habitify.me/journal?target_date=…` for three days:
- 2026-05-01 (D-2, final state)
- 2026-05-02 (D-1, final state — yesterday per spec)
- 2026-05-03 (D, mid-day capture for "pending" state — actually 10:30 AM PT)

Plus `/habits` for the registry and `/areas` for grouping context. Auth via `life-platform/habitify` API key.

Raw responses captured at `/tmp/habitify_raw.json` (~5MB, not committed). Slim representative samples at `/tmp/habitify_audit_samples.json`.

---

## Headline finding — *the spec's assumed taxonomy is broader than Matthew's actual usage*

The spec assumed five distinguishable states: `completed`, `skipped`, `not_scheduled`, `pending`, `failed`. The Habitify API does provide enough state to distinguish all of these in principle. **But Matthew's current registry only exercises three:**

```
Status enum observed in 3-day capture:
  completed        — habit done, current_value >= target_value
  in_progress      — habit not yet completed (= "pending" if before deadline)
  failed           — habit not completed past its deadline
  skipped          — NOT OBSERVED (Matthew doesn't actively skip)
  none             — NOT OBSERVED (Habitify returns all habits, no "not scheduled" state)
```

The practical bug for Matthew is therefore **narrower than the spec's framing**:
- The conflation isn't between completed/skipped/not_scheduled/pending/failed
- It's between **`in_progress` (mid-day = "not yet attempted")** and **`failed` (deadline passed)** — both currently mapped to `0.0` by the live Lambda

This narrows the schema work in Step 2: a 3-state enum (`completed | pending | failed`) is sufficient for the current registry, plus an optional `skipped` slot for future-proofing.

---

## Status distribution snapshot (3-day capture)

| Day | Total habits | completed | in_progress | failed | skipped |
|---|---|---|---|---|---|
| 2026-05-01 (final) | 65 | 0 | 1 | 64 | 0 |
| 2026-05-02 (final) | 65 | 0 | 2 | 63 | 0 |
| 2026-05-03 (mid-day, ~10:30 AM PT) | 65 | 1 | 64 | 0 | 0 |

What this shows:
- **Mid-day** (today): nearly everything is `in_progress` (= the "pending" state the spec wanted to model). This is the data the live Lambda is currently misreading as "0/failure".
- **End-of-day** (D-1, D-2): nearly everything has flipped to `failed`. The 1–2 `in_progress` carry-overs at end-of-day are likely habits without a strict deadline (TBD).

---

## Frequency / scheduling pattern

| Pattern | Count | Implication |
|---|---|---|
| `RRULE:FREQ=DAILY` | 65 | All habits show up every day |
| `BYDAY` (specific weekdays only) | **0** | No M-W-F-only habits in current registry |
| `goal.periodicity = monthly` | 1 (Sauna) | Has monthly aggregation but daily appearance — needs special handling |
| `goal.periodicity = weekly` | 0 | No "X times per week" habits in current registry |

**Implication for the spec's "X times per week" question:** not currently relevant for Matthew. If he adds weekly habits later, the schema needs to accommodate them. The Sauna case (`periodicity=monthly` + `RRULE=DAILY`) is a less obvious aggregation case — see Sample C below.

---

## Sample raw entries (one per status)

### Sample A — `completed` (today, finished)

```json
{
  "id": "61252250-ED4F-4AE6-B6E4-C33993295C05",
  "name": "Weigh In",
  "is_archived": false,
  "time_of_day": ["afternoon"],
  "goal": {"unit_type": "rep", "value": 1, "periodicity": "daily"},
  "log_method": "manual",
  "recurrence": "DTSTART:20260223T185523Z\nRRULE:FREQ=DAILY",
  "remind": ["9:0"],
  "area": {"id": "C4BF713C-…", "name": "Data"},
  "status": "completed",
  "progress": {
    "current_value": 1,
    "target_value": 1,
    "unit_type": "rep",
    "periodicity": "daily",
    "reference_date": "2026-05-03T00:00:00.000Z"
  },
  "habit_type": 1
}
```

### Sample B — `in_progress` (today, not yet done = "pending")

```json
{
  "id": "59D681AF-67FF-4714-8AEC-D7970B9D4CEB",
  "name": "Out Of Bed Before 5am",
  "time_of_day": ["afternoon", "evening"],
  "goal": {"unit_type": "rep", "value": 1, "periodicity": "daily"},
  "recurrence": "DTSTART:20260223T185243Z\nRRULE:FREQ=DAILY",
  "area": {"name": "Discipline"},
  "status": "in_progress",
  "progress": {
    "current_value": 0,
    "target_value": 1,
    "periodicity": "daily",
    "reference_date": "2026-05-03T00:00:00.000Z"
  },
  "habit_type": 1
}
```

### Sample C — `failed` (yesterday, deadline passed)

```json
{
  "id": "59D681AF-67FF-4714-8AEC-D7970B9D4CEB",
  "name": "Out Of Bed Before 5am",
  "goal": {"unit_type": "rep", "value": 1, "periodicity": "daily"},
  "recurrence": "DTSTART:20260223T185243Z\nRRULE:FREQ=DAILY",
  "status": "failed",
  "progress": {
    "current_value": 0,
    "target_value": 1,
    "reference_date": "2026-05-02T00:00:00.000Z"
  }
}
```

(Same habit ID as Sample B — same habit, same target — just different `reference_date` and resolved `status`. Confirms the API resolves status per (habit, date) tuple.)

### Sample D — Monthly periodicity (the Sauna edge case)

```json
{
  "name": "Sauna",
  "goal": {"unit_type": "rep", "value": 1, "periodicity": "monthly"},
  "recurrence": "DTSTART:20260223T185407Z\nRRULE:FREQ=DAILY",
  "status": "in_progress",
  "progress": {
    "current_value": 0,
    "target_value": 1,
    "periodicity": "monthly",
    "reference_date": "2026-05-02T00:00:00.000Z"
  }
}
```

`recurrence` is daily (so it shows up in the journal every day), but `goal.periodicity` is monthly (so the success target is per-month, not per-day). The current Lambda would mark every day as `0` until the one day per month it gets done. The schema needs to distinguish per-day appearance from per-period aggregation.

### Sample E — `skipped` and `none` — NOT OBSERVED

Matthew's behavior in the captured 3-day window does not include any actively-skipped or non-scheduled habits. Schema design should reserve slots for these states based on the spec, but verification samples will need to come from a session where Matthew explicitly skips a habit OR adds a BYDAY-scheduled habit.

---

## Backfill feasibility (gates schema choice in Step 3)

The spec asks: "Confirm whether the Habitify API supports historical state queries." 

**Answer: Yes.** The `/journal?target_date=YYYY-MM-DDT00:00:00+00:00` endpoint accepts arbitrary historical dates. Confirmed by the captured 2026-05-01 + 2026-05-02 + 2026-05-03 responses — each returned the habits' resolved status for that specific day.

**Implication:** Spec's **Option C (backfill via Habitify API)** is feasible. We can reconstruct the new schema for all historical data — no need for the lossy hard cutover (Option A).

The backfill cost is one API call per (date) pair. For ~70 days of history at 1s API latency, ~70s total. Cheap.

---

## Pending → failed cutoff timing

The API's status flip from `in_progress` → `failed` appears to happen at **end of UTC day** (the `reference_date` in `progress` is always `00:00:00.000Z`). At today's mid-day capture (2026-05-03 ~10:30 AM PT = 17:30 UTC), 64 habits are `in_progress`. Yesterday's same habits (2026-05-02 reference_date) are now `failed`.

**Relevance for spec's pending-vs-failed cutoff question:** Habitify's clock is the source of truth, not Matthew's local time. If the platform mirrors Habitify's status transitions, the Lambda inherits Habitify's UTC-end-of-day cutoff for free. No platform-side timezone math needed.

If Matthew wants the "sleep tier 4am-cutoff exception" the spec mentioned, that has to be added on the platform side because Habitify doesn't expose per-habit deadline customization in the API surface I observed.

---

## Schema implications (preview — Matthew confirms before Step 2)

Recommended state machine:

| Status | Scheduled? | Counts in streak? | Source field |
|---|---|---|---|
| `completed` | Always (current registry is all-daily) | ✅ success | `status: "completed"` from API |
| `pending` | Yes | doesn't count yet — exclude from rate calc until end-of-day | `status: "in_progress"` AND `reference_date == today UTC` |
| `failed` | Yes | counts as miss | `status: "failed"` OR (`status: "in_progress"` AND past UTC end-of-day) |
| `skipped` | Yes (when Matthew skips) | counts as miss | `status: "skipped"` from API — reserve slot, not yet observed |
| `not_scheduled` | No | invisible to streak | reserve slot for future BYDAY habits — not yet observed |

For the monthly-aggregation case (Sample D), recommend storing the per-day record as `pending` but adding a separate weekly/monthly aggregate at the partition level. Doesn't fit the per-day binary cleanly; needs explicit handling.

---

## Open questions for Matthew (gate Step 2 on these)

1. **Confirm Option C (backfill via API).** Feasibility verified. Lossy Option A would lose ~3 months of streak fidelity. Recommend C.
2. **Pending → failed cutoff** — adopt Habitify's UTC end-of-day (zero work) or add a platform-side override (e.g. 4am PT cutoff for sleep-tier habits)?
3. **Monthly habits (Sauna).** How should success be computed? Current registry has 1 such habit; need a per-period aggregate, not a per-day one. Recommend: store per-day record as a `progress` snapshot with `monthly_target / monthly_current_value`, compute success at the period boundary.
4. **Schema versioning.** Spec proposed Option A (hard cutover) vs Option C (backfill). With Option C feasible, recommend writing the new shape from the next ingestion run forward AND backfilling historical data with the same Lambda's logic. Avoids the "two schemas in the same partition" mess.
5. **TD-19 dependency** — Spec mentions TD-11 is gated on TD-19 (date partition convention) shipping first. Per PR 5 audit, TD-19 Phase 2 fix is straightforward for HAE/apple_health but doesn't directly affect the Habitify Lambda (which is already UTC-clean per PR 5 audit). So TD-11 can proceed independently of TD-19.

---

## Next step

This audit unblocks Step 2 (schema design). I am stopping here per the brief. Matthew approves Step 2 separately.

Step 2 scope (preview):
- Define the per-(habit, date) record shape — fields: `habit_id`, `date`, `status`, `scheduled_today`, `value`, `completed_at`, `tier`, `target_value`, `current_value`, `periodicity`, `aggregation_window_start` (for monthly habits).
- Define the streak-calc algorithm in `mcp/tools_habits.py` so it understands `pending` is not a streak break and `failed` is.
- Confirm the migration path (Option C feasible — see "Backfill feasibility" above).
