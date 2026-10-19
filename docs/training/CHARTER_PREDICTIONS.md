# Charter build pre-registered predictions (#5089)

Four owner-only, dated predictions, registered before W1 ships and graded by the six-week block retro (#5079).
Script: `scripts/register_charter_predictions.py` (dry-run default; `--apply` is run by the driver from main).

Store: `USER#matthew#SOURCE#diary_claims`, `PREDICTION#2026-10-18#<slug>` (private, evaluator-scanned; the public diary shelf
`site_api_diary._claims_by_entry` drops them: no `source_sk`, `visibility: private`). Rows are `status: observation` / `evaluation.type: qualitative`: the daily evaluator skips them and the retro grades
each from its `measurement` block, then sets confirmed/refuted. Evaluation date: 2026-12-06.

| Key | Prediction | Measured by |
|---|---|---|
| `anchor_e1rm_up` | every anchor lift's e1RM above its 2026-10-18 baseline | `coach_event_triggers.session_bests` |
| `zero_accessory_stalls` | no accessory stall over any 3 consecutive sessions, last 2 weeks | `stall_detector.assess_stall` |
| `steps_floor_90pct` | 12,000-step floor met on >= 90% of days | `metric_truth.steps_by_date` |
| `rate_in_band_4_of_6` | 7-day loss rate in 3.0-3.5 lb/wk on >= 4 of 6 weekly reads | `prescription_forecast.measured_week_rate` |

Ids are pasted on #5089 after `--apply`. Re-running is a no-op (`already_registered`).
