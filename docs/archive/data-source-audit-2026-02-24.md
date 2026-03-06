# Project40 Data Source Audit — What We're Missing

**Date:** 2026-02-24  
**Purpose:** Comprehensive gap analysis across all 11 data sources — what fields are available via each API vs. what we currently ingest into DynamoDB.

---

## Summary

| Source | Fields Ingested | Available but Missing | Priority Gaps |
|--------|:-:|:-:|:-:|
| **Whoop** | 21 daily + per-workout | 3 | Journal (if API adds it) |
| **Garmin** | 20 | **12+** | 🔴 Sleep data, VO2max, activity detail |
| **Eight Sleep** | 22 | 2-3 | Bed temperature schedule |
| **Strava** | 30+ per activity | 5-6 | HR zones, splits, calories |
| **Withings** | 12 | 3-4 | Blood pressure (hardware dependent) |
| **Todoist** | 7 | 2 | Overdue tasks |
| **Habitify** | 8 | 1 | Habit streaks |
| **MacroFactor** | 53 nutrients + food log | 0 | ✅ Fully covered |
| **Apple Health** | 60+ | 0 | ✅ Fully covered |

**Biggest bang for the buck: Garmin has the most untapped data by far.**

---

## 🔴 HIGH PRIORITY GAPS

### 1. Garmin Sleep Data (Effort: 2h)
We call `get_sleep_data` but barely extract anything. Missing: sleep_score, deep/light/rem/awake durations, sleep start/end, sleep SpO2, restless moments. This makes Garmin a second complete sleep source (worn 24/7 vs Eight Sleep only in bed).

### 2. Garmin Activity Detail (Effort: 1h)
We call `get_activities_by_date` but only store type/name. Missing: duration, distance, avg/max HR, calories, elevation. These are the fields that make activity data actionable.

### 3. Garmin VO2max + Fitness Age (Effort: 30min)
We call `get_max_metrics` but don't extract. VO2max is the single best predictor of all-cause mortality. Fitness age is a great motivational metric.

### 4. Strava HR Zones per Activity (Effort: 3h)
`GET /activities/{id}/zones` — time in each HR zone. Critical for Zone 2 minute tracking. Requires second API call per activity (rate limit: 100/15min).

### 5. Strava DetailedActivity (Effort: 3h)
`GET /activities/{id}` — per-km splits (runs), suffer_score, calories, description. Can combine with zones call.

## 🟡 MEDIUM PRIORITY

6. Garmin hydration, race predictions
7. Whoop nap data + sleep timestamps
8. Todoist overdue task count
9. Habitify streaks

## ❌ NOT AVAILABLE
- **Whoop Journal** — Not in API. Most valuable missing data across the entire platform. Monitor for future availability.

---

## Implementation Plan

| Phase | Items | Effort | Impact |
|-------|-------|:-:|--------|
| **Phase 1** | Garmin sleep + activity detail + VO2max | 3-4h | Fills biggest gap; doubles sleep coverage |
| **Phase 2** | Strava zones + detailed activity | 4-5h | Unlocks Zone 2 tracking and run splits |
| **Phase 3** | Whoop nap + timing, Garmin hydration + race predictions | 2-3h | Incremental enrichment |
| **Phase 4** | Todoist overdue, Habitify streaks, Eight Sleep temps | 2-3h | Nice-to-haves |

**Phase 1 alone covers ~60% of the missing value.**
