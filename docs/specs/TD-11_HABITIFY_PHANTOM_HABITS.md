# TD-11 — Habitify phantom-failed habits

**Severity:** MED (correctness — distorts streak/scoring)
**Status:** Design — implementation pending Matthew approval
**Source handover:** `handovers/HANDOVER_v6.8.1.md` (TD-11)

---

## Problem

The Habitify ingestion writes the full habit registry of 65 to DDB daily. Habits not actively completed get written as `0.0`. This conflates two semantically different states:

- **Actively skipped** — the user marked the habit as skipped in Habitify (it's "off" today by intent)
- **Not yet attempted** — the day isn't over; the user hasn't gotten to it yet
- **Not tracked today** — the habit isn't part of today's plan (e.g. a workout on a non-workout day)

All three currently map to `0.0`. Streak calculation can't distinguish them. A habit that's "scheduled M-W-F" gets phantom `0.0` failures on Tu/Th/Sat/Sun. A morning habit at 9am hasn't been "failed" — it's been "not yet attempted." Mid-day score reads are systematically pessimistic.

---

## Why this is strategic, not a quick fix

This change touches three independent systems:

1. **Habitify ingestion Lambda** — the source of writes. Must change what it writes.
2. **Habitify completion-API contract** — the upstream API itself. We need to know what it actually tells us about the three states. (May or may not be enough information — TBD.)
3. **Scoring engine** — anything downstream that reads the daily habit data and computes streaks, completion rates, character-sheet scores. Must change how it reads.

A naive fix on (1) without (3) creates a worse bug: streaks misalign because the consumer assumes one schema and the producer ships another. A fix on (3) without (1) is a no-op.

---

## Step 1: What does the Habitify API actually tell us?

**Open question — must answer before designing the schema.** The Habitify API has at least these surface concepts:

- A habit has a `frequency` definition (daily / specific weekdays / X times per week)
- A habit has per-day `status` — likely some enum that includes at least "Completed", "Skipped", "Failed", "None" (terminology guess; verify)
- An "X times per week" habit doesn't have a fixed schedule per day — completion is week-aggregated

**Action:** before writing code, hit the Habitify API for a known day (yesterday, where state is final) and capture the raw response shape for:
- A daily habit completed
- A daily habit skipped
- A scheduled habit on a non-scheduled day
- An "X times per week" habit on different days
- A habit that's pending (mid-day, not yet attempted)

Save the raw response in `docs/audits/TD-11_HABITIFY_API_AUDIT.md`. The schema design (Step 2) depends on this.

---

## Step 2: New DDB schema

**Proposed shape** (depends on Step 1 findings; may need adjustment):

```python
# Per-habit per-day record (replaces current 0.0/1.0 binary)
{
    "habit_id": "weigh_in",
    "date": "2026-05-02",
    "status": "completed",          # enum: completed | skipped | not_scheduled | pending | failed
    "scheduled_today": True,         # was this day in the habit's schedule?
    "value": 1.0,                    # for habits with a numeric component (e.g. minutes)
    "completed_at": "2026-05-02T07:14:00Z",  # null if not completed
    "tier": 0,                       # from habit registry — non-negotiable / high / etc
}
```

States and their semantics:

| Status | Scheduled? | Value | Streak treatment |
|---|---|---|---|
| `completed` | Yes | 1.0 | Counts as success |
| `skipped` | Yes | 0.0 | Counts as missed (streak break) |
| `not_scheduled` | No | null | Doesn't affect streak (skip in calc) |
| `pending` | Yes | 0.0 | Doesn't count yet — streak calc must use "is it past the day's window" logic |
| `failed` | Yes | 0.0 | Counts as missed |

The critical change: `pending` and `not_scheduled` are NOT treated as failures. Today's data is `pending` until end-of-day or until the user marks the habit done/skipped explicitly.

---

## Step 3: Lambda change

`habitify-ingestion` Lambda (verify exact name in `ci/lambda_map.json`) — change the writer to:

1. For each habit in the registry, query the Habitify API for the day
2. Map API response → status enum (depends on Step 1 findings)
3. Determine `scheduled_today` from habit's `frequency` definition
4. Write the new schema

Backward compatibility note: existing data is in the old `0.0/1.0` binary schema. The new Lambda's writes will be a different shape. Either:

- **Option A: Hard cutover** — flip the Lambda, accept that historical data is in the old shape, treat it as "all `0.0` rows could be any of skipped/not_scheduled/pending/failed and we don't know which." Streak data from before the cutover is unreliable.
- **Option B: Soft migration** — Lambda writes BOTH shapes (old binary + new enum) for N days, scoring engine reads new shape, after N days drop old shape.
- **Option C: Backfill via Habitify API** — if the API exposes historical state per habit per day, write a one-off script to reconstruct the new schema for all historical data.

**Recommendation:** Option C if the API supports it; Option A otherwise. Option B is overkill for a personal platform with one user.

**Action:** in Step 1, also confirm whether the Habitify API supports historical state queries.

---

## Step 4: Scoring engine change

Wherever streaks and completion rates are computed (likely in `mcp/habits.py` or similar — verify), update the read path:

```python
# Before
completion_rate = sum(values) / len(values)  # treats 0.0 as failure regardless

# After
relevant = [r for r in records if r["status"] != "not_scheduled"]
completed = [r for r in relevant if r["status"] == "completed"]
pending = [r for r in relevant if r["status"] == "pending"]
final = [r for r in relevant if r["status"] not in ("pending", "not_scheduled")]
completion_rate = len(completed) / len(final) if final else None  # null if all pending
```

**Streak logic specifically:**
- Today's habit being `pending` does NOT break a streak (streak hasn't been decided yet)
- Yesterday's habit being `pending` is a data error (should have been finalized at midnight)
- A scheduled day with `failed` or `skipped` breaks the streak
- A `not_scheduled` day is invisible to streak calc — neither extends nor breaks

**Open question:** when does `pending` resolve to `failed`? Two reasonable rules:
- At end-of-day local time
- At end-of-day plus a grace window (some habits are "before sleep" which can extend past midnight)

Recommendation: end-of-day local time, with a "sleep" tier exception that uses 4am cutoff.

---

## Step 5: Migration

Per the option chosen in Step 3:

- **Option A:** no migration. Update `ARCHITECTURE.md` with a "data dating from before <cutover_date> is in legacy binary shape" note.
- **Option C:** write `backfill/backfill_habitify_v2_schema.py`. Dry-run first. Idempotent.

---

## Acceptance criteria

- [ ] `docs/audits/TD-11_HABITIFY_API_AUDIT.md` exists with verified API behavior for all four state cases
- [ ] Lambda writes new schema; verifiable by querying DDB after a daily run
- [ ] Streak calculation does not break for `pending` records on the current day
- [ ] Completion-rate calculation excludes `not_scheduled` days
- [ ] Existing site/observatory pages don't crash on the new schema
- [ ] Test suite passes — particularly streak tests if they exist (`tests/test_habits.py` or similar)

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Habitify API doesn't expose enough state to distinguish all four cases | HIGH | Step 1 audit confirms feasibility before writing code. Fall back: degrade gracefully — `pending` becomes inferred from "is the day still ongoing in user's TZ" |
| Scoring engine has implicit `0.0`-as-failure assumption in places we haven't found | MED | Grep for the schema before deploying; integration test on a known multi-day window |
| Character sheet scores recompute and look very different post-fix | MED | Expected behavior — it's the bug fix making them honest. Add a release note in CHANGELOG. |
| Habits with weekly aggregation ("X times/week") don't fit the per-day schema cleanly | MED | Solvable: store per-day record as `not_scheduled` or `flexible` with a separate weekly aggregate. Confirm in Step 1. |

---

## Open questions for Matthew

1. **Cutover strategy** — Option A (hard cutover, lose historical fidelity) or Option C (backfill if API supports)? Lean Option C if feasible.
2. **Pending → failed cutoff** — end-of-day local time? With sleep-tier exception at 4am?
3. **Weekly-aggregate habits** — do you have any of these in the 65-habit registry, and how do you currently think about their daily completion semantics?
4. **Order of operations** — TD-19 (date partition) and TD-11 interact. If we fix TD-11 first, the new schema lands on partitions that TD-19 will later migrate. If TD-19 first, TD-11 inherits the corrected partition. Recommendation: TD-19 first.

---

## Doc updates triggered by this work

- `SCHEMA.md` — new habit record shape
- `ARCHITECTURE.md` — Habitify ingestion behavior change
- `INTELLIGENCE_LAYER.md` — scoring engine semantics
- `DATA_DICTIONARY.md` — habit status enum reference
- `CHANGELOG.md` — always

---

## Estimated effort

- Step 1 audit: 1–2 hours
- Step 2 schema design + review: 1 hour
- Step 3 Lambda change + tests: 3–4 hours
- Step 4 scoring engine change + tests: 4–6 hours (depends on how many call sites)
- Step 5 migration (Option C): 2–3 hours

**Total:** ~12–16 hours of implementation, gated behind audit. Genuinely a multi-session feature, not a single-session fix.
