# Handover — Sleep SOT Redesign (v2.55.0)
## Date: 2026-03-01

## What Changed
Sleep Source-of-Truth (SOT) split from Eight Sleep → Whoop for duration/staging/score/efficiency. Eight Sleep remains SOT for bed environment (temperature, toss & turns). This is an architecture-level change driven by the couch-sleep scenario: Eight Sleep truncates sleep that starts outside the pod, while Whoop captures all sleep via wrist sensor.

## Files Modified

### ✅ Completed (Phase 1)

1. **`mcp/helpers.py`** — Added `normalize_whoop_sleep()` shared normalizer function. Maps Whoop DynamoDB fields to common schema: `sleep_quality_score` → `sleep_score`, `sleep_efficiency_percentage` → `sleep_efficiency_pct`, hours → pct for deep/rem/light, `time_awake_hours` → `waso_hours`, `sleep_start`/`sleep_end` → `sleep_onset_hour`/`wake_hour`/`sleep_midpoint_hour`.

2. **`mcp/tools_sleep.py`** — `tool_get_sleep_analysis()` now queries `whoop` and normalizes via shared helper. Inline normalizer replaced with thin wrapper. Docstring, source tag, clinical note updated. `tool_get_sleep_environment_analysis()` stays on Eight Sleep (correct — environment is Eight Sleep SOT).

3. **`mcp/tools_correlation.py`** — All three sleep correlation tools updated:
   - `tool_get_caffeine_sleep_correlation()` → Whoop + normalize
   - `tool_get_exercise_sleep_correlation()` → Whoop + normalize  
   - `tool_get_alcohol_sleep_correlation()` → Whoop + normalize
   Import added for `normalize_whoop_sleep`.

4. **`mcp/tools_health.py`** — Two data query changes:
   - `tool_get_readiness_score()`: Sleep component now queries Whoop, normalizes, component key renamed `eight_sleep` → `sleep_quality`. Weight table and all_keys set updated.
   - `tool_get_health_trajectory()`: Recovery section now uses single Whoop query with normalization instead of separate Whoop + Eight Sleep queries.
   All docstrings, methodology strings, and messages updated.

5. **`docs/DATA_DICTIONARY.md`** — SOT domain table split: Sleep Duration & Staging → Whoop, Sleep Environment → Eight Sleep. Metric Overlap Map updated. Sleep metric reference table rewritten with full field mapping. Tier 3 note added.

### ⏳ Remaining (Phase 2 — tools_lifestyle.py)

25 `eightsleep` references across 8 functions in `tools_lifestyle.py`:

| Function | Lines | What Needs Changing |
|----------|-------|-------------------|
| `_EXPERIMENT_METRICS` | 78-82 | Change sleep metrics source from eightsleep to whoop with normalized field names |
| `tool_get_supplement_correlation` | 547, 559-563 | Query whoop instead of eightsleep for sleep metrics, normalize |
| `tool_get_weather_correlation` | 682, 718-720 | Query whoop for sleep metrics in HEALTH_METRICS |
| `tool_get_social_connection_trend` | 918 | Change eightsleep sleep_score reference to whoop |
| `tool_get_social_isolation_risk` | 1044, 1055 | Query whoop instead of eightsleep |
| `tool_get_meditation_correlation` | 1135, 1144-1145 | Query whoop for sleep metrics |
| `tool_get_jet_lag_recovery` | 1441-1442 | Change recovery_metrics eightsleep references |
| `tool_get_blood_pressure_correlation` | 1900 | Query whoop instead of eightsleep |

**Impact of NOT doing Phase 2 yet:** These tools still work — they use Eight Sleep sleep data for secondary correlations. On split-sleep nights the correlations will use truncated data, but for typical nights the data is similar. Not urgent.

### ⏳ Remaining (Phase 3 — Lambdas)

- `daily_brief_lambda.py` — Sleep component still queries Eight Sleep
- `weekly_digest_lambda.py` — Unknown, needs audit
- `monthly_digest_lambda.py` — Unknown, needs audit  
- `anomaly_detector_lambda.py` — Unknown, needs audit
- `dashboard_lambda.py` — Unknown, needs audit
- `buddy_page_lambda.py` — Unknown, needs audit
- `clinical_summary_lambda.py` — Unknown, needs audit

### ⏳ Remaining (Phase 4 — Architecture docs)

- `docs/ARCHITECTURE.md` — SOT domain table needs same update as DATA_DICTIONARY

## Normalizer Field Mapping

| Whoop DynamoDB Field | Normalised Alias | Notes |
|---------------------|-----------------|-------|
| `sleep_quality_score` | `sleep_score` | 0-100 |
| `sleep_efficiency_percentage` | `sleep_efficiency_pct` | % |
| `slow_wave_sleep_hours` | `deep_pct` | Computed: hours / duration * 100 |
| `rem_sleep_hours` | `rem_pct` | Computed: hours / duration * 100 |
| `light_sleep_hours` | `light_pct` | Computed: hours / duration * 100 |
| `time_awake_hours` | `waso_hours` | Direct map |
| `hrv` | `hrv_avg` | Direct map |
| `disturbance_count` | `toss_and_turns` | Direct map |
| `sleep_start` | `sleep_onset_hour` | Computed: ISO → decimal hour (PST) |
| `sleep_end` | `wake_hour` | Computed: ISO → decimal hour (PST) |
| (derived) | `sleep_midpoint_hour` | Computed: midpoint of onset/wake |

## Key Design Decisions

1. **Normalizer in helpers.py** — Single shared function, imported by all consumers. Idempotent (won't overwrite existing fields). All Whoop fields preserved alongside normalized aliases.

2. **No DynamoDB changes** — Both sources already store data separately. The normalizer operates at query time, not at ingest.

3. **Readiness score component renamed** — `eight_sleep` → `sleep_quality` (breaking change for any code referencing this key by name).

4. **Sleep onset latency unavailable from Whoop** — Whoop doesn't report time-to-fall-asleep. The sleep environment tool still uses Eight Sleep for this metric.

5. **Timezone hardcoded to PST (-8)** — The `_hour_from_iso` helper uses a fixed offset. Should eventually pull from user profile timezone.

## Deploy Steps

No Lambda deploys needed for Phase 1 — these are MCP server changes only. After editing on disk, restart the MCP server to pick up the changes.

## Platform State
- Version: v2.55.0 (after this change)
- 99 MCP tools, 24 Lambdas, 19 sources
