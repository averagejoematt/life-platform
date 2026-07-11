"""
Tool registry: maps tool names to their functions and JSON schemas.
"""

from mcp.config import RAW_DAY_LIMIT, SOURCES

# BENCH-1: cut-benchmarking & regain firewall (PRIVATE, view-dispatched).
from mcp.tools_benchmark import tool_get_benchmark
from mcp.tools_cgm import tool_get_cgm

# #915: ad-hoc coach check-in loop — coaches ask, Matthew answers verbatim.
from mcp.tools_coach_checkin import tool_get_coach_checkin_queue, tool_log_coach_checkin
from mcp.tools_coach_intelligence import tool_evaluate_prediction, tool_get_coach_thread, tool_get_coach_track_record, tool_get_predictions
from mcp.tools_correlation import tool_get_zone2_breakdown
from mcp.tools_data import (
    tool_find_days,
    tool_get_daily_snapshot,
    tool_get_date_range,
    tool_get_intelligence_quality,
    tool_get_sources,
    tool_search_activities,
)
from mcp.tools_decisions import tool_get_decisions, tool_log_decision, tool_update_decision_outcome
from mcp.tools_habits import tool_get_habit_reflection_queue, tool_log_habit_reflection
from mcp.tools_health import tool_get_daily_metrics, tool_get_readiness_score, tool_get_weight_loss_progress

# SPEC_HEVY_AND_NUTRITION_BRIDGE §2.6 — source-agnostic workout query layer
from mcp.tools_hevy import tool_get_workout_detail, tool_get_workouts

# ADR-066 (2026-05-31): Hevy routine write-loop fat tool.
from mcp.tools_hevy_routine import tool_manage_hevy_routine
from mcp.tools_journal import tool_get_mood
from mcp.tools_labs import tool_get_freshness_status, tool_get_labs
from mcp.tools_lifestyle import (
    tool_create_experiment,
    tool_end_experiment,
    tool_get_experiment_results,
    tool_get_field_notes,
    tool_get_insights,
    tool_get_social_connection_trend,
    tool_list_experiments,
    tool_log_field_note_response,
    tool_save_insight,
    tool_update_insight_outcome,
)
from mcp.tools_memory import (
    tool_delete_platform_memory,
    tool_list_memory_categories,
    tool_read_platform_memory,
    tool_write_platform_memory,
)
from mcp.tools_nutrition import tool_get_deficit_sustainability, tool_get_nutrition
from mcp.tools_reading import (
    tool_get_constellation,
    tool_get_due_recalls,
    tool_get_reading_history,
    tool_get_reading_profile,
    tool_get_reading_recommendation,
    tool_get_reading_shelf,
    tool_get_reading_track_record,
    tool_manage_reading,
)
from mcp.tools_sick_days import tool_manage_sick_days
from mcp.tools_social import tool_get_social_dashboard

# tools_calendar retired v3.7.46 (ADR-030) — google_calendar import removed
from mcp.tools_strength import tool_get_muscle_volume
from mcp.tools_todoist import close_todoist_task, create_todoist_task, tool_get_todoist_snapshot, update_todoist_task
from mcp.tools_training import tool_get_acwr_status, tool_get_training
from mcp.tools_training_notes import tool_get_exercise_notes

# Vacation fund tracker ($1/workout-mile since experiment start).

TOOLS = {
    "get_exercise_notes": {
        "fn": tool_get_exercise_notes,
        "schema": {
            "name": "get_exercise_notes",
            "description": (
                "The per-exercise TRAINING-NOTE timeline (the arc Matthew wrote on a lift across sessions), "
                "derived from his freeform Hevy notes — progression/form/equipment/limiter/sentiment signals + "
                "a prominent pain_flag. Use for: 'what did I note on calf raises lately?', 'how's the cycling "
                "progression going?', 'any pain flags on squats?', and as a standard pre-flight pull alongside "
                "get_exercise_history. Pass a human exercise name OR a Hevy template_id. Signals are inferred + "
                "confidence-tagged; raw notes are sovereign. pain_flag is over-inclusive by design — confirm or "
                "dismiss before loading that movement."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "exercise": {
                        "type": "string",
                        "description": "Exercise name (e.g. 'calf raise', 'cycling') — resolved to its Hevy template via recent workouts.",
                    },
                    "template_id": {"type": "string", "description": "Hevy exercise template id (hex or uuid). Alternative to 'exercise'."},
                    "lookback_days": {"type": "integer", "description": "Days of history to include (default 180)."},
                },
                "required": [],
            },
        },
    },
    "get_sources": {
        "fn": tool_get_sources,
        "schema": {
            "name": "get_sources",
            "description": "List all available data sources and their date ranges in the life platform.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    # get_calendar_events + get_schedule_load removed v3.7.46 (ADR-030)
    # Google Calendar integration retired — Smartsheet IT blocks all zero-touch options.
    "get_daily_snapshot": {
        "fn": tool_get_daily_snapshot,
        "schema": {
            "name": "get_daily_snapshot",
            "description": (
                "Unified daily data access. "
                "'summary' (default) = all available data across every source for a specific date. Best for 'how was my day/yesterday?' questions. Requires date=. "
                "'latest' = most recent record for each source — useful for current status checks. "
                "Use for: 'how was yesterday?', 'what's my latest data?', 'show me today's readings', 'all data for 2026-03-10'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "'summary' (default) for a specific date, 'latest' for most recent per source.",
                        "enum": ["summary", "latest"],
                    },
                    "date": {"type": "string", "description": "[summary] Date YYYY-MM-DD (required for summary view)."},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": f"[latest] List of sources to fetch. Defaults to all. Valid: {SOURCES}",
                    },
                },
                "required": [],
            },
        },
    },
    "get_date_range": {
        "fn": tool_get_date_range,
        "schema": {
            "name": "get_date_range",
            "description": f"Get time-series records for a single source. Returns raw daily data for windows up to {RAW_DAY_LIMIT} days, monthly aggregates beyond that.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (inclusive)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (inclusive)."},
                },
                "required": ["source", "start_date", "end_date"],
            },
        },
    },
    "find_days": {
        "fn": tool_find_days,
        "schema": {
            "name": "find_days",
            "description": "Find days within a date range where numeric fields meet filter conditions. For Strava, use field names: 'total_distance_miles', 'total_elevation_gain_feet'. For Whoop: 'hrv', 'recovery_score', 'strain'. Great for correlations. IMPORTANT: This tool operates on day-level aggregates only — it cannot search inside individual activity names or sport types. For any query involving specific activity names, first/longest/highest achievements, named events, or sport-type filtering, you MUST use search_activities instead.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD."},
                    "filters": {
                        "type": "array",
                        "description": "List of field filter conditions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "op": {"type": "string", "enum": [">", ">=", "<", "<=", "="]},
                                "value": {"type": "number"},
                            },
                            "required": ["field", "op", "value"],
                        },
                    },
                },
                "required": ["source", "start_date", "end_date"],
            },
        },
    },
    "get_intelligence_quality": {
        "fn": tool_get_intelligence_quality,
        "schema": {
            "name": "get_intelligence_quality",
            "description": "Query intelligence quality validation results from the post-generation validator. Shows flags where coaches made claims contradicted by actual data, used overconfident language for early-stage data, or cited wrong source-of-truth values. Use for: 'are the coaches accurate?', 'any quality issues?', 'intelligence validation results'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "number", "description": "Days to look back (default: 7)."},
                    "severity": {
                        "type": "string",
                        "description": "Filter by severity: 'error' or 'warning'. Default: all.",
                        "enum": ["error", "warning"],
                    },
                    "coach": {"type": "string", "description": "Filter by coach ID (e.g., 'glucose', 'physical')."},
                },
                "required": [],
            },
        },
    },
    "get_coach_thread": {
        "fn": tool_get_coach_thread,
        "schema": {
            "name": "get_coach_thread",
            "description": "Read a coach's persistent thread — their running memory of positions, predictions, surprises, and emotional investment. Use for: 'what has Dr. Park been saying?', 'show me the glucose coach's predictions', 'how invested is the training coach?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "coach_id": {
                        "type": "string",
                        "description": "Coach domain: sleep, nutrition, training, mind, physical, glucose, labs, explorer",
                    },
                    "limit": {"type": "number", "description": "Number of thread entries (default 4)"},
                },
                "required": ["coach_id"],
            },
        },
    },
    "get_predictions": {
        "fn": tool_get_predictions,
        "schema": {
            "name": "get_predictions",
            "description": "Cross-coach prediction ledger — all predictions from all coaches with statuses. Use for: 'what predictions are pending?', 'which coach is most accurate?', 'prediction scorecard'. #726: reads the canonical COACH#/PREDICTION# store (evaluator-graded, code-stamped IDs per #725 — the SAME store the public site serves); the legacy SOURCE#coach_thread# embedded predictions were tombstoned. For hit-rate + calibration analysis, use get_coach_track_record.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "confirmed", "refuted", "inconclusive", "expired"]},
                    "coach_id": {"type": "string"},
                    "limit": {"type": "number"},
                },
                "required": [],
            },
        },
    },
    "get_coach_track_record": {
        "fn": tool_get_coach_track_record,
        "schema": {
            "name": "get_coach_track_record",
            "description": "Hit-rate track record for a single coach over a configurable window — reads the COACH#{coach_id}/LEARNING# audit trail written daily by the prediction evaluator. Returns by_outcome counts (confirmed/refuted/inconclusive/expired), hit_rate_pct (confirmed / decided), per-subdomain and per-metric breakdowns, and 10 most-recent evaluations. Use for: 'how accurate has the glucose coach been?', 'which subdomain does the sleep coach get right most often?', 'show me recent verdicts on metabolic predictions'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "coach_id": {
                        "type": "string",
                        "description": "Coach name: sleep, nutrition, training, mind, physical, glucose, labs, explorer (accepts _coach suffix too)",
                    },
                    "days": {"type": "number", "description": "Lookback window in days (default 30)"},
                    "subdomain": {"type": "string", "description": "Optional subdomain filter (e.g. 'sleep_quality', 'caloric_intake')"},
                },
                "required": ["coach_id"],
            },
        },
    },
    "evaluate_prediction": {
        "fn": tool_evaluate_prediction,
        "schema": {
            "name": "evaluate_prediction",
            "description": "Manually resolve a coach prediction — mark as confirmed or refuted with an outcome note.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prediction_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["confirmed", "refuted"]},
                    "outcome_note": {"type": "string"},
                },
                "required": ["prediction_id", "status"],
            },
        },
    },
    "search_activities": {
        "fn": tool_search_activities,
        "schema": {
            "name": "search_activities",
            "description": "Search Strava activities by name keyword, sport type, minimum distance, or minimum elevation gain. ALWAYS use this tool (not find_days) for: named activities ('first century', 'mailbox peak', 'machu picchu'), achievement queries (longest run, biggest hike, first 100-mile ride), or sorting by distance/elevation to find top efforts. CRITICAL: Do NOT filter by sport_type when looking for longest/biggest/most impressive efforts — long walks and hikes count equally to runs and should be included. Only pass sport_type if the user explicitly asks for a specific type (e.g. 'my longest run' vs 'my longest activity'). Results include an all-time percentile rank and a context flag for exceptional values so you can narrate how remarkable the effort was.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "name_contains": {
                        "type": "string",
                        "description": "Keyword to search in activity name (case-insensitive). E.g. 'machu', 'half marathon', 'trail'.",
                    },
                    "sport_type": {
                        "type": "string",
                        "description": "Filter by sport type (case-insensitive). Common values: 'Run', 'Walk', 'Hike', 'Ride', 'VirtualRide', 'WeightTraining'.",
                    },
                    "min_distance_miles": {"type": "number", "description": "Only return activities with distance >= this value in miles."},
                    "min_elevation_gain_feet": {
                        "type": "number",
                        "description": "Only return activities with elevation gain >= this value in feet.",
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Field to sort results by descending. Options: 'distance_miles', 'total_elevation_gain_feet', 'moving_time_seconds', 'kilojoules'. Default: 'distance_miles'.",
                    },
                    "limit": {"type": "number", "description": "Max results to return. Default 100."},
                },
                "required": [],
            },
        },
    },
    "get_training": {
        "fn": tool_get_training,
        "schema": {
            "name": "get_training",
            "description": (
                "Unified training intelligence. Use 'view' to select the analysis: "
                "'load' (default) = Banister CTL/ATL/TSB fitness-fatigue model + ACWR injury risk. Warmed nightly. "
                "'periodization' = mesocycle detection (Base/Build/Peak/Deload), 80/20 polarization analysis, progressive overload tracking. Warmed nightly. "
                "'recommendation' = readiness-based workout suggestion synthesising Whoop, Eight Sleep, Garmin, training load. Board of Directors rationale. Warmed nightly. "
                "Use for: 'how fit am I?', 'am I overtraining?', 'training load', 'CTL', 'TSB', 'form', "
                "'am I in a deload?', 'periodization', 'what should I do today?', 'training recommendation', 'ready to train?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "load (default), periodization, or recommendation.",
                        "enum": ["load", "periodization", "recommendation"],
                    },
                    "start_date": {"type": "string", "description": "[load/periodization] Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "[load/periodization] End date YYYY-MM-DD (default: today)."},
                    "date": {"type": "string", "description": "[recommendation] Target date YYYY-MM-DD (default: today)."},
                    "weeks": {"type": "number", "description": "[periodization] Number of weeks to analyse (default: 12)."},
                },
                "required": [],
            },
        },
    },
    "get_daily_metrics": {
        "fn": tool_get_daily_metrics,
        "schema": {
            "name": "get_daily_metrics",
            "description": (
                "Unified daily activity metrics. "
                "'movement' (default) = NEAT analysis, movement score 0-100, step target tracking, sedentary day flags. "
                "'energy' = calorie expenditure vs intake balance — TDEE breakdown, activity energy, deficit/surplus trend. "
                "'hydration' = daily water intake adequacy scored against bodyweight-adjusted target (35ml/kg). "
                "Use for: 'am I moving enough?', 'NEAT', 'steps', 'sedentary days', "
                "'energy balance', 'calorie burn', 'am I in a deficit?', 'hydration score', 'water intake'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "movement (default), energy, or hydration.",
                        "enum": ["movement", "energy", "hydration"],
                    },
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30d ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "step_target": {"type": "integer", "description": "[movement] Daily step target (default: 8000)."},
                },
                "required": [],
            },
        },
    },
    "get_benchmark": {
        "fn": tool_get_benchmark,
        "schema": {
            "name": "get_benchmark",
            "description": (
                "PRIVATE cut-benchmarking vs Matthew's own proven weight-loss history (descriptive, "
                "correlational, n=1 — never causal). Use 'view' to select: "
                "'pace' (default) = live pace vs the proven trajectory at the current weight — current "
                "weight/rate + recent walking volume vs the by-band proven volumes, walk gap, and the "
                "~240 lb run gate. "
                "'episodes' = the detected loss/regain ledger + loss-vs-regain rate asymmetry. "
                "'maintenance' = the regain firewall (near goal): rolling walk volume vs the proven floor "
                "and the post-trough decay signature. "
                "All views forward-framed (what works next), never a failure tally. "
                "Use for: 'how does my pace compare to last time?', 'am I walking enough?', 'can I run yet?', "
                "'show my cut history', 'am I holding the loss?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "pace (default), episodes (the cut ledger), or maintenance (the regain firewall).",
                        "enum": ["pace", "episodes", "maintenance"],
                    },
                    "date": {
                        "type": "string",
                        "description": "Optional YYYY-MM-DD as-of date (default today).",
                    },
                },
                "required": [],
            },
        },
    },
    "get_weight_loss_progress": {
        "fn": tool_get_weight_loss_progress,
        "schema": {
            "name": "get_weight_loss_progress",
            "description": "The core weight-loss coaching report. Returns: weekly rate of loss with fast/slow flags, full BMI series with clinical milestone flags (Obese III→II→I→Overweight→Normal), projected goal date at current pace, plateau detection (14+ days of minimal movement), and % complete toward goal. Use for: 'how is my weight loss going?', 'when will I reach my goal?', 'am I losing too fast?', 'am I in a plateau?', 'what BMI am I at?'. Requires journey_start_date, goal_weight_lbs in profile.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Override start date YYYY-MM-DD. Defaults to journey_start_date from profile.",
                    },
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_muscle_volume": {
        "fn": tool_get_muscle_volume,
        "schema": {
            "name": "get_muscle_volume",
            "description": "Weekly sets per muscle group vs MEV/MAV/MRV volume landmarks (Renaissance Periodization). Shows if training volume is below maintenance, optimal, or exceeding recovery capacity. Also analyses push/pull/legs balance. Use for: 'am I training enough chest?', 'what is my weekly volume?', 'am I overtraining?', 'is my push/pull ratio balanced?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD."},
                    "period": {"type": "string", "description": "Aggregation period: 'week' (default) or 'month'."},
                },
                "required": [],
            },
        },
    },
    # ── MacroFactor longevity nutrition tools ─────────────────────────────────
    # ── MacroFactor / Nutrition tools ─────────────────────────────────────────
    "get_nutrition": {
        "fn": tool_get_nutrition,
        "schema": {
            "name": "get_nutrition",
            "description": (
                "Unified nutrition intelligence from MacroFactor. Use 'view' to select the analysis: "
                "'summary' (default) = daily macro breakdown and rolling averages: calories, protein, carbs, fat, fiber, sodium, omega-3, vitamin D, gap vs targets. "
                "'macros' = calorie and protein adherence vs TDEE estimate. Day-by-day hit rates. Supports calorie_target= and protein_target= overrides. "
                "'meal_timing' = eating window analysis (TRF/Satchin Panda): first/last bite, window duration, circadian consistency, gap to sleep onset. "
                "'micronutrients' = score ~25 micronutrients against RDA + longevity targets (Attia, Patrick, Blueprint). Flags deficiencies, omega-6:3 ratio, vitamin D risk. "
                "Use for: 'how is my nutrition?', 'average macros', 'am I hitting protein?', 'am I in a deficit?', "
                "'eating window', 'am I eating too late?', 'TRF', 'micronutrient deficiencies', 'omega-3 intake', 'vitamin D'. Requires MacroFactor data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "summary (default), macros, meal_timing, or micronutrients.",
                        "enum": ["summary", "macros", "meal_timing", "micronutrients"],
                    },
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "days": {
                        "type": "number",
                        "description": "[macros] Rolling window in days (default: 30). Ignored if start_date provided.",
                    },
                    "calorie_target": {
                        "type": "number",
                        "description": "[macros] Override daily calorie target (kcal). Defaults to TDEE estimate.",
                    },
                    "protein_target": {"type": "number", "description": "[macros] Override daily protein target (g). Default: 180g."},
                },
                "required": [],
            },
        },
    },
    "get_zone2_breakdown": {
        "fn": tool_get_zone2_breakdown,
        "schema": {
            "name": "get_zone2_breakdown",
            "description": (
                "Zone 2 training tracker and weekly breakdown. Classifies Strava activities into 5 HR zones "
                "based on average heartrate as a percentage of max HR (from profile). Aggregates weekly Zone 2 "
                "minutes and compares to the 150 min/week target (Attia, Huberman, WHO moderate-intensity guidelines). "
                "Shows full 5-zone training distribution, sport type breakdown for Zone 2, weekly trend analysis, "
                "and training polarization alerts (Zone 3 'no man's land' warning per Seiler). "
                "Zone 2 (60-70% max HR) is the highest-evidence longevity training modality — builds mitochondrial "
                "density, fat oxidation capacity, and cardiovascular base. "
                "Use for: 'how much Zone 2 am I doing?', 'am I hitting my Zone 2 target?', "
                "'show my training zone distribution', 'weekly Zone 2 minutes', 'zone 2 trend', "
                "'am I doing enough easy cardio?', 'training polarization check'. Requires Strava data with HR."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "weekly_target_minutes": {
                        "type": "integer",
                        "description": "Weekly Zone 2 target in minutes (default: 150, per Attia/WHO guidelines).",
                    },
                    "min_duration_minutes": {
                        "type": "integer",
                        "description": "Minimum activity duration in minutes to include (default: 10).",
                    },
                },
                "required": [],
            },
        },
    },
    # ── Habits / P40 tools ────────────────────────────────────────────────────
    # compare_habit_periods retained as standalone — requires 4 required params, not suited to view= dispatch
    "get_readiness_score": {
        "fn": tool_get_readiness_score,
        "schema": {
            "name": "get_readiness_score",
            "description": (
                "Unified readiness score (0-100) synthesising Whoop recovery (40%), Whoop sleep quality (25%), "
                "HRV 7-day trend vs 30-day baseline (20%), TSB training form (10%), and "
                "Garmin Body Battery (5%) into a single GREEN / YELLOW / RED signal with a 1-line "
                "actionable recommendation. Also includes a device_agreement section showing Whoop vs "
                "Garmin HRV/RHR delta as a confidence signal — flag status means lower score reliability; "
                "when the cross-check can't run it returns status=unavailable with a reason instead of null. "
                "Reduces cognitive load: one number instead of 5 separate metrics tells you "
                "'train hard today' vs 'go easy' vs 'rest day'. Missing components are excluded and "
                "remaining weights re-normalised. "
                "Use for: 'should I train hard today?', 'what is my readiness score?', "
                "'am I ready for a key session?', 'how am I feeling today?', 'morning readiness check-in'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "save_insight": {
        "fn": tool_save_insight,
        "schema": {
            "name": "save_insight",
            "description": (
                "Save a new insight to the personal coaching log. "
                "Use whenever Claude or Matthew identifies something worth tracking and following up on — "
                "a hypothesis, a behavioural change to try, a pattern noticed, or a recommendation to act on. "
                "Returns the insight_id needed for update_insight_outcome. "
                "Use for: 'save this insight', 'track this idea', 'add this to the coaching log', "
                "'remember to follow up on this'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The insight text to save. Be specific and actionable."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of tags (e.g. ['sleep', 'hrv', 'caffeine']).",
                    },
                    "source": {"type": "string", "description": "Origin of the insight: 'chat' (default) or 'email'."},
                },
                "required": ["text"],
            },
        },
    },
    "get_insights": {
        "fn": tool_get_insights,
        "schema": {
            "name": "get_insights",
            "description": (
                "List insights from the personal coaching log. "
                "Returns all insights newest-first with days_open calculated. "
                "Stale flag is set for open insights older than 14 days. "
                "Use for: 'what insights are open?', 'show my coaching log', "
                "'what have I been meaning to act on?', 'any stale insights?', "
                "'show me resolved insights'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status_filter": {"type": "string", "description": "Filter by status: 'open', 'acted', or 'resolved'. Omit for all."},
                    "limit": {"type": "integer", "description": "Max results to return (default: 50)."},
                },
                "required": [],
            },
        },
    },
    "update_insight_outcome": {
        "fn": tool_update_insight_outcome,
        "schema": {
            "name": "update_insight_outcome",
            "description": (
                "Close the loop on a saved insight — record what happened when you acted on it. "
                "Updates the insight's status and adds outcome notes. "
                "Use for: 'I tried the caffeine cutoff — it worked', 'mark this insight as resolved', "
                "'update the outcome for insight X', 'close out this coaching log item'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "insight_id": {"type": "string", "description": "The insight_id returned by save_insight (e.g. 2026-02-22T09:15:00)."},
                    "outcome_notes": {"type": "string", "description": "What happened — did it work? What did you learn?"},
                    "status": {
                        "type": "string",
                        "description": "New status: 'acted' (tried it) or 'resolved' (fully closed). Default: 'acted'.",
                    },
                },
                "required": ["insight_id"],
            },
        },
    },
    "get_labs": {
        "fn": tool_get_labs,
        "schema": {
            "name": "get_labs",
            "description": (
                "Unified lab intelligence. Use 'view' to select the analysis: "
                "'results' (default) = latest blood work values across all 7 draws with reference ranges and trend direction. "
                "'trends' = biomarker trajectory over time — slope, direction, clinical threshold crossings. "
                "'out_of_range' = all historically out-of-range biomarkers with persistence classification (chronic/recurring/occasional). "
                "Use for: 'show my blood work', 'lab results', 'biomarker trends', 'what's out of range?', "
                "'cholesterol history', 'which labs are chronic issues?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "results (default), trends, or out_of_range.",
                        "enum": ["results", "trends", "out_of_range"],
                    },
                    "biomarker": {"type": "string", "description": "[results/trends] Filter by biomarker name (partial match)."},
                    "category": {"type": "string", "description": "[results] Filter by category (e.g. 'lipids', 'metabolic', 'hormones')."},
                    "start_date": {"type": "string", "description": "[trends] Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "[trends] End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    "get_freshness_status": {
        "fn": tool_get_freshness_status,
        "schema": {
            "name": "get_freshness_status",
            "description": (
                "Per-source data freshness summary (WR-48 Enhancement 4). "
                "Returns overall status (green / yellow / orange / red) plus "
                "per-source last-date / age-days / threshold. Use for: "
                "'are we OK?', 'what sources are stale?', 'data status check', "
                "'why isn't my dashboard updating?'. "
                "Independent of freshness-checker Lambda — reads DDB directly so it "
                "works even if the Lambda's silently failing (which is what happened "
                "during the Apr–May 2026 silence)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of source keys to restrict to (whoop, withings, strava, garmin, eightsleep, habitify, todoist, apple_health, macrofactor, notion, food_delivery, measurements). Default: all.",
                    },
                },
                "required": [],
            },
        },
    },
    "get_cgm": {
        "fn": tool_get_cgm,
        "schema": {
            "name": "get_cgm",
            "description": (
                "Unified CGM (continuous glucose monitor) intelligence. "
                "'dashboard' (default) = time-in-range (target >90%), variability (SD target <20), mean glucose, time above 140, fasting proxy, clinical flags, trend. Warmed nightly. "
                "'fasting' = overnight nadir-based fasting glucose validation — avoids dawn phenomenon by using 2-5 AM nadir. Cross-validates CGM accuracy. "
                "Use for: 'glucose overview', 'blood sugar', 'time in range', 'CGM dashboard', "
                "'am I pre-diabetic?', 'fasting glucose', 'glucose variability', 'metabolic health'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "dashboard (default) or fasting.",
                        "enum": ["dashboard", "fasting"],
                    },
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "days": {"type": "number", "description": "[dashboard] Days to analyse (default: 30)."},
                },
                "required": [],
            },
        },
    },
    # ── Journal tools (v2.16.0) ────────────────────────────────────────────────
    "get_mood": {
        "fn": tool_get_mood,
        "schema": {
            "name": "get_mood",
            "description": (
                "Unified mood and state-of-mind intelligence. "
                "'trend' (default) = journal-derived mood, energy, and stress scores with 7-day rolling averages, trend direction. "
                "'state_of_mind' = Apple Health How We Feel (HWF) valence data — objective emotional state tracking. "
                "Use for: 'how has my mood been?', 'mood trend', 'energy levels', 'stress trend', "
                "'state of mind', 'emotional wellbeing', 'How We Feel data', 'mood vs training'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "trend (default) or state_of_mind.",
                        "enum": ["trend", "state_of_mind"],
                    },
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "days": {"type": "number", "description": "[trend] Rolling window in days (default: 30)."},
                },
                "required": [],
            },
        },
    },
    "create_experiment": {
        "fn": tool_create_experiment,
        "schema": {
            "name": "create_experiment",
            "description": (
                "Start tracking a new N=1 experiment. An experiment is a specific protocol change "
                "(supplement, diet shift, sleep hygiene tweak, training adjustment) with a hypothesis "
                "and start date. The system will automatically compare before/after metrics when you "
                "call get_experiment_results. Board rules: one variable at a time, minimum 14 days, "
                "define success criteria upfront. "
                "Use for: 'I'm starting creatine today', 'track my no-caffeine-after-10am experiment', "
                "'create experiment for cold plunge protocol', 'I want to test if X improves Y'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short name of the intervention (e.g. 'Creatine 5g daily', 'No screens after 9pm').",
                    },
                    "hypothesis": {"type": "string", "description": "What you expect to happen (e.g. 'Will improve deep sleep % by >5%')."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to today."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags (e.g. ['sleep', 'supplement', 'caffeine']).",
                    },
                    "notes": {"type": "string", "description": "Additional context or protocol details."},
                    "library_id": {"type": "string", "description": "ID from experiment_library.json to link this run to a library entry."},
                    "duration_tier": {"type": "string", "description": "'7-day sprint', '30-day trial', or '60-day deep dive'."},
                    "experiment_type": {
                        "type": "string",
                        "description": "'measurable' (has biomarker endpoint) or 'behavioral' (compliance tracking).",
                    },
                    "planned_duration_days": {"type": "integer", "description": "Target duration in days."},
                    "design": {
                        "type": "object",
                        "description": (
                            "#539: OPTIONAL but strongly preferred — the n-of-1 pre-registration design, "
                            "validated at creation and FROZEN (immutable, publicly stamped 'pre-registered on DATE'). "
                            "With a design, end_experiment runs the paired analysis automatically "
                            "(baseline vs washout-trimmed window, block-bootstrap 95% CI, deterministic verdict). "
                            "Example: {baseline_days: 14, washout_days: 3, stopping_rule: 'run the full 21 days regardless "
                            "of interim trend; abort only if recovery < 40% for 3 consecutive days', criterion: "
                            "{metric: 'deep_pct', direction: 'higher', min_effect: 2}}. "
                            "#728: the registration is also frozen to a PUBLIC timestamped artifact "
                            "(/experiments/prereg/{id}.json) at creation — before-the-results proof."
                        ),
                        "properties": {
                            "baseline_days": {"type": "integer", "description": "Baseline window: days before start (7-56)."},
                            "washout_days": {
                                "type": "integer",
                                "description": "Days after start excluded from analysis while the intervention takes effect (0-14).",
                            },
                            "stopping_rule": {
                                "type": "string",
                                "description": (
                                    "#728 REQUIRED: plain-language rule (20-500 chars) declaring when the experiment "
                                    "ends or aborts — stated before any data exists so an early stop is checkable "
                                    "against what was promised."
                                ),
                            },
                            "criterion": {
                                "type": "object",
                                "description": "The frozen success criterion.",
                                "properties": {
                                    "metric": {
                                        "type": "string",
                                        "description": (
                                            "One of: sleep_score, sleep_efficiency_pct, deep_pct, rem_pct, sleep_duration_hours, "
                                            "sleep_onset_latency_min, recovery_score, hrv_rmssd, resting_heart_rate, garmin_stress, "
                                            "body_battery_high, weight_lbs, calories, protein_g, steps, cgm_mean_glucose, "
                                            "cgm_time_in_range_pct."
                                        ),
                                    },
                                    "direction": {"type": "string", "description": "'higher' or 'lower' — the predicted change."},
                                    "min_effect": {
                                        "type": "number",
                                        "description": "Minimum absolute effect (metric units) that would count as success.",
                                    },
                                },
                                "required": ["metric", "direction", "min_effect"],
                            },
                        },
                        "required": ["baseline_days", "criterion", "stopping_rule"],
                    },
                },
                "required": ["name", "hypothesis"],
            },
        },
    },
    "list_experiments": {
        "fn": tool_list_experiments,
        "schema": {
            "name": "list_experiments",
            "description": (
                "List all N=1 experiments with their status, duration, and whether minimum "
                "data threshold (14 days) has been met. Filter by status. "
                "Use for: 'what experiments am I running?', 'show active experiments', "
                "'list completed experiments', 'any experiments ready to evaluate?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter: 'active', 'completed', 'abandoned'. Omit for all."},
                },
                "required": [],
            },
        },
    },
    "get_experiment_results": {
        "fn": tool_get_experiment_results,
        "schema": {
            "name": "get_experiment_results",
            "description": (
                "Auto-compare before vs during metrics for an N=1 experiment. "
                "Automatically queries sleep, recovery, stress, body composition, nutrition, "
                "movement, and glucose metrics for both the pre-experiment baseline period "
                "and the experiment period. Reports deltas, % changes, and direction "
                "(improved/worsened). Board of Directors evaluates results against hypothesis. "
                "Use for: 'how is my creatine experiment going?', 'did cutting caffeine help my sleep?', "
                "'show experiment results', 'evaluate my N=1', 'did this actually work?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string", "description": "The experiment_id from create_experiment or list_experiments."},
                },
                "required": ["experiment_id"],
            },
        },
    },
    "end_experiment": {
        "fn": tool_end_experiment,
        "schema": {
            "name": "end_experiment",
            "description": (
                "End an active N=1 experiment and record the outcome. "
                "Run get_experiment_results first to review the data. "
                "Status can be 'completed' (ran full course) or 'abandoned' (stopped early). "
                "Use for: 'end my creatine experiment', 'I'm stopping the no-caffeine experiment', "
                "'mark experiment as completed', 'abandon experiment X'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string", "description": "The experiment_id to end."},
                    "outcome": {"type": "string", "description": "What happened — did it work? What did you learn?"},
                    "status": {"type": "string", "description": "'completed' (default) or 'abandoned'."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "grade": {
                        "type": "string",
                        "description": "'completed', 'partial' (>50% done), or 'failed'. Auto-inferred if omitted.",
                    },
                    "compliance_pct": {"type": "integer", "description": "0-100, percentage of days the intervention was performed."},
                    "reflection": {"type": "string", "description": "What I'd do differently next time."},
                },
                "required": ["experiment_id"],
            },
        },
    },
    "get_social_connection_trend": {
        "fn": tool_get_social_connection_trend,
        "schema": {
            "name": "get_social_connection_trend",
            "description": (
                "Social connection quality trend from journal entries. Tracks enriched_social_quality "
                "(alone/surface/meaningful/deep) over time with rolling averages, streaks, and PERMA "
                "wellbeing model context. Correlates social quality with recovery, HRV, sleep, stress. "
                "Seligman: Relationships are the #1 predictor of sustained wellbeing. "
                "Use for: 'social connection trend', 'meaningful connections', 'PERMA score'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    # ── Travel & Jet Lag (v2.40.0) ────────────────────────────────────────────
    # ── Habit Registry tools (v2.47.0) ──────────────────────────────────────────
    # ── BS-BH1: Vice Streak Amplifier ──
    # ── Board of Directors Management ──
    # ── Character Sheet tools (v2.58.0) ──
    # ── Character Sheet Phase 4 tools (v2.71.0) ──
    # ── Life Event Tagging (#40) ──
    "manage_sick_days": {
        "fn": tool_manage_sick_days,
        "schema": {
            "name": "manage_sick_days",
            "description": (
                "Manage sick and rest day flags. Sick day flags suppress streak breaks, habit alerts, and anomaly noise. "
                "'list' (default) = show all logged sick/rest days in a date range. "
                "'log' = flag a date as sick/rest day (requires date=). Accepts dates= list for multiple days. "
                "'clear' = remove a sick day flag logged in error (requires date=). "
                "Use for: 'log a sick day', 'I'm sick today', 'show my sick days', 'remove sick day flag', 'rest day'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "list (default), log, or clear.",
                        "enum": ["list", "log", "clear"],
                    },
                    "date": {"type": "string", "description": "[log/clear] Date YYYY-MM-DD."},
                    "dates": {"type": "array", "items": {"type": "string"}, "description": "[log] List of dates to flag at once."},
                    "reason": {"type": "string", "description": "[log] Optional reason (e.g. 'flu', 'rest day', 'travel')."},
                    "start_date": {"type": "string", "description": "[list] Start of range (default: 30 days ago)."},
                    "end_date": {"type": "string", "description": "[list] End of range (default: today)."},
                },
                "required": [],
            },
        },
    },
    # ── Contact Frequency Tracking (#42) ──
    "get_social_dashboard": {
        "fn": tool_get_social_dashboard,
        "schema": {
            "name": "get_social_dashboard",
            "description": (
                "Social connection dashboard: contact frequency, depth distribution, connection diversity, "
                "weekly trends, stale contacts, and Murthy-threshold assessment. Pillar 7 data source. "
                "Use for: 'social connection status', 'how often do I talk to people', "
                "'who haven't I contacted recently', 'social health dashboard', 'am I isolated', "
                "'relationship pillar data', 'connection quality trends'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    # ── Temptation Logging (#35) ──
    # DISC-7: Discovery annotations (behavioral response to findings)
    # get_defense_patterns removed — function never implemented (v3.7.0)
    # ── Lactate Threshold Estimation (#27) ──
    # ── Exercise Efficiency Trending (#39) ──
    # ── Hydration Tracking Enhancement (#30) ──
    # ── Todoist Integration ──
    "get_todoist_snapshot": {
        "fn": tool_get_todoist_snapshot,
        "schema": {
            "name": "get_todoist_snapshot",
            "description": (
                "Unified Todoist snapshot. "
                "'load' (default) = current task load: active count, overdue, due-today, priority breakdown, cognitive load signal (LOW/MODERATE/ELEVATED/HIGH). "
                "'today' = full Todoist day summary for a specific date — completed tasks, project breakdown, counts. "
                "Use for: 'how many tasks do I have?', 'task load', 'am I overloaded?', 'decision fatigue', "
                "'overdue tasks', 'Todoist summary', 'what tasks did I complete yesterday?', 'task backlog'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "load (default) or today.",
                        "enum": ["load", "today"],
                    },
                    "date": {"type": "string", "description": "[today] Date YYYY-MM-DD (default: yesterday)."},
                    "days": {"type": "integer", "description": "[load] Days of completion history to include (default: 7)."},
                },
                "required": [],
            },
        },
    },
    # ── Todoist write tools ──
    "update_todoist_task": {
        "fn": update_todoist_task,
        "schema": {
            "name": "update_todoist_task",
            "description": (
                "Update an existing Todoist task — reschedule, change recurrence, rename, change priority or project. "
                "IMPORTANT: Always use 'every!' (with exclamation mark) for recurring due_string to reschedule from "
                "completion date, not original due date. This prevents pile-up when tasks are missed. "
                "Examples: due_string='every! week', 'every! month', 'every! 3 months', 'every! year'. "
                "To set first-fire date AND recurrence: set due_string='every! month' AND due_date='2026-04-01'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID from list_todoist_tasks."},
                    "due_string": {"type": "string", "description": "Recurrence e.g. 'every! week', 'every! month'. Use every! not every."},
                    "due_date": {"type": "string", "description": "First-fire date YYYY-MM-DD."},
                    "content": {"type": "string", "description": "New task name."},
                    "description": {"type": "string", "description": "Task description/notes."},
                    "priority": {"type": "integer", "description": "1=urgent 2=high 3=medium 4=normal."},
                    "project_id": {"type": "string", "description": "Move to project ID."},
                },
                "required": ["task_id"],
            },
        },
    },
    "create_todoist_task": {
        "fn": create_todoist_task,
        "schema": {
            "name": "create_todoist_task",
            "description": (
                "Create a new Todoist task with optional recurrence and due date. "
                "Always use 'every!' for recurring tasks. Get project_id from get_todoist_projects first."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Task name."},
                    "project_id": {"type": "string", "description": "Project ID from get_todoist_projects."},
                    "due_string": {"type": "string", "description": "e.g. 'every! Sunday', 'every! month'. Use every! for recurring."},
                    "due_date": {"type": "string", "description": "YYYY-MM-DD for one-time or first-fire date."},
                    "priority": {"type": "integer", "description": "1=urgent 2=high 3=medium 4=normal."},
                    "description": {"type": "string", "description": "Task description."},
                },
                "required": ["content"],
            },
        },
    },
    "close_todoist_task": {
        "fn": close_todoist_task,
        "schema": {
            "name": "close_todoist_task",
            "description": "Mark a Todoist task as complete. For recurring tasks, advances to next occurrence. For one-time tasks, removes from active list.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID from list_todoist_tasks."},
                },
                "required": ["task_id"],
            },
        },
    },
    # ── IC-1: Platform Memory (tools 136–139) ──────────────────────────────────
    "write_platform_memory": {
        "fn": tool_write_platform_memory,
        "schema": {
            "name": "write_platform_memory",
            "description": (
                "Store a structured memory record in the platform_memory partition. "
                "The compounding intelligence substrate — use to record failure patterns, "
                "what worked, coaching calibrations, journey milestones, and episodic wins. "
                "Valid categories: weekly_plate, failure_pattern, what_worked, "
                "coaching_calibration, personal_curves, journey_milestone, insight, experiment_result."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Memory category (e.g. 'failure_pattern', 'what_worked', 'journey_milestone').",
                    },
                    "content": {
                        "type": "object",
                        "description": 'Key-value dict of data to store. E.g. {"pattern": "high-stress Tuesdays correlate with missed nutrition", "conditions": [...]}',
                    },
                    "date": {"type": "string", "description": "Date for the record (YYYY-MM-DD). Defaults to today."},
                    "overwrite": {"type": "boolean", "description": "Overwrite if record exists (default true)."},
                },
                "required": ["category", "content"],
            },
        },
    },
    "read_platform_memory": {
        "fn": tool_read_platform_memory,
        "schema": {
            "name": "read_platform_memory",
            "description": (
                "Retrieve recent memory records for a given category from the platform_memory partition. "
                "Use to pull coaching calibration, failure patterns, or episodic wins into context."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Memory category to retrieve."},
                    "days": {"type": "integer", "description": "How many days back to look (default 30, max 365)."},
                    "limit": {"type": "integer", "description": "Max records to return (default 10, max 50)."},
                },
                "required": ["category"],
            },
        },
    },
    "list_memory_categories": {
        "fn": tool_list_memory_categories,
        "schema": {
            "name": "list_memory_categories",
            "description": (
                "List all platform_memory categories that have records, with record counts and date ranges. "
                "Use to understand what intelligence the platform has accumulated so far."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How many days back to scan (default 90)."},
                },
                "required": [],
            },
        },
    },
    "delete_platform_memory": {
        "fn": tool_delete_platform_memory,
        "schema": {
            "name": "delete_platform_memory",
            "description": "Delete a specific platform_memory record by category + date. Use to correct bad memories or remove stale records.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Memory category."},
                    "date": {"type": "string", "description": "Date of the record to delete (YYYY-MM-DD)."},
                },
                "required": ["category", "date"],
            },
        },
    },
    # ── IC-19: Decision Journal ────────────────────────────────────────────────
    "log_decision": {
        "fn": tool_log_decision,
        "schema": {
            "name": "log_decision",
            "description": (
                "IC-19: Log a platform-guided decision for trust calibration. Record what the platform recommended, "
                "whether Matthew followed or overrode the advice, and why. Outcome recorded later via update_decision_outcome. "
                "Use for: 'the brief said rest day but I trained', 'followed protein advice', 'platform recommended X and I did Y'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "description": "What the platform recommended (e.g. 'Take a rest day', 'Front-load protein').",
                    },
                    "followed": {
                        "type": "boolean",
                        "description": "True if Matthew followed the advice, False if overridden. Omit if not yet decided.",
                    },
                    "override_reason": {"type": "string", "description": "Why Matthew chose differently (if overridden). Optional."},
                    "source": {
                        "type": "string",
                        "description": "Which digest/email made the recommendation. Default: daily_brief.",
                        "enum": ["daily_brief", "weekly_digest", "monthly_digest", "nutrition_review", "chronicle", "mcp"],
                    },
                    "pillars": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Pillars this decision touches (e.g. ['sleep', 'movement']).",
                    },
                    "date": {"type": "string", "description": "Date of the decision (YYYY-MM-DD). Defaults to today."},
                },
                "required": ["decision"],
            },
        },
    },
    # ── BS-01: Essential Seven Protocol ─────────────────────────────────────────────
    # ── Garmin biometrics + device agreement ─────────────────────────────────────────
    # ── BS-09: ACWR Training Load ────────────────────────────────────────────────────
    "get_acwr_status": {
        "fn": tool_get_acwr_status,
        "schema": {
            "name": "get_acwr_status",
            "description": (
                "BS-09: Acute:Chronic Workload Ratio status from Whoop strain data. "
                "Reads pre-computed ACWR from computed_metrics partition (written nightly by acwr-compute Lambda). "
                "Safe zone: 0.8–1.3. Above 1.3 = injury risk, below 0.8 = detraining. "
                "Gabbett et al. thresholds. Proxy note: Whoop strain is cardiac-based; use as directional signal, not precise injury predictor. "
                "Use for: 'what is my ACWR?', 'am I overtraining?', 'is my training load safe?', 'injury risk assessment'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "End date for status query (YYYY-MM-DD). Defaults to yesterday."},
                    "days_back": {"type": "integer", "description": "Days of history to return (default 14)."},
                },
                "required": [],
            },
        },
    },
    "get_decisions": {
        "fn": tool_get_decisions,
        "schema": {
            "name": "get_decisions",
            "description": (
                "IC-19: Retrieve recent platform-guided decisions with outcomes and trust calibration. "
                "Shows follow vs override patterns and which approach produces better outcomes. "
                "Use for: 'how often do I follow platform advice?', 'should I trust the system?', "
                "'decision journal', 'when do my overrides work?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Look back N days (default 30)."},
                    "pillar": {"type": "string", "description": "Filter by pillar (e.g. 'sleep', 'nutrition')."},
                    "outcome_only": {"type": "boolean", "description": "If true, only return decisions with recorded outcomes."},
                },
                "required": [],
            },
        },
    },
    "update_decision_outcome": {
        "fn": tool_update_decision_outcome,
        "schema": {
            "name": "update_decision_outcome",
            "description": (
                "IC-19: Record the outcome of a past decision. Call 1-3 days after logging a decision "
                "to capture what actually happened. Over time builds trust calibration: when to follow "
                "vs override platform advice. Use for: 'that rest day advice worked', 'I ignored the protein tip and felt fine'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sk": {"type": "string", "description": "Sort key of the decision to update (from get_decisions)."},
                    "outcome_metric": {
                        "type": "string",
                        "description": "Which metric was affected (e.g. 'HRV', 'sleep_score', 'protein_g').",
                    },
                    "outcome_delta": {"type": "number", "description": "Change in the metric (positive = improved, negative = worsened)."},
                    "outcome_notes": {"type": "string", "description": "Free-text notes on what happened."},
                    "effectiveness": {"type": "integer", "description": "1-5 rating: 1=bad outcome, 3=neutral, 5=great outcome."},
                },
                "required": ["sk"],
            },
        },
    },
    # ── IC-18: Cross-Domain Hypothesis Engine ───────────────────────────────────────────
    # ── BS-12: Deficit Sustainability Tracker ──
    "get_deficit_sustainability": {
        "fn": tool_get_deficit_sustainability,
        "schema": {
            "name": "get_deficit_sustainability",
            "description": (
                "BS-12: Multi-signal early warning for unsustainable caloric deficit. "
                "Monitors 5 channels simultaneously: HRV trend, sleep quality, recovery, "
                "Tier 0 habit completion, and training output. When 3+ degrade concurrently "
                "during an active deficit → flags with severity and calorie increase recommendation. "
                "Attia / Huberman: aggressive deficits destroy adherence, sleep, and muscle. "
                "Use for: 'is my deficit sustainable?', 'am I cutting too hard?', "
                "'deficit health check', 'should I eat more?', 'deficit sustainability'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "days": {"type": "integer", "description": "Rolling window in days (default: 14)."},
                },
                "required": [],
            },
        },
    },
    # ── IC-29: Metabolic Adaptation Intelligence ──
    # ── BS-SL1: Sleep Environment Optimizer — RETIRED (ADR-118, #489). The tool
    #    was entirely a bed-temperature optimizer; the Eight Sleep temperature
    #    pipeline is dead (dead /v2/intervals endpoint, no temp field 4+ months),
    #    so the tool could only ever return "Need ≥14 nights of paired data". ──
    # ── BS-MP1: Autonomic Balance Score ──
    # ── BS-MP2: Journal Sentiment Trajectory ──
    # ── Challenge tools ──────────────────────────────────────────────────────
    # ── Protocols ────────────────────────────────────────────────────────
    # ── BL-04: Field Notes ──────────────────────────────────────
    # ── BL-03: The Ledger / Snake Fund ──────────────────────────
    # SPEC_HEVY_AND_NUTRITION_BRIDGE §2.6 — source-agnostic workout tools.
    # Read the new per-workout schema (sk=DATE#yyyy-mm-dd#WORKOUT#<id>).
    # Coexists with the legacy tool_get_workout_frequency / tool_get_strength
    # tools that read the old daily-aggregate shape.
    "get_workouts": {
        "fn": tool_get_workouts,
        "schema": {
            "name": "get_workouts",
            "description": (
                "List normalized workouts across all logging sources (Hevy + MacroFactor) "
                "in a date range. Returns per-workout records with title, duration, "
                "set count, total volume in kg, and source attribution. Use for: "
                "'what workouts did I do this week?', 'show recent training', "
                "'compare workouts across apps'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "ISO yyyy-mm-dd. Default: 30 days ago."},
                    "end_date": {"type": "string", "description": "ISO yyyy-mm-dd. Default: today."},
                    "source": {
                        "type": "string",
                        "enum": ["hevy", "macrofactor_export"],
                        "description": "Optional source filter. Omit for all.",
                    },
                    "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500, "description": "Max workouts to return."},
                },
                "required": [],
            },
        },
    },
    "get_workout_detail": {
        "fn": tool_get_workout_detail,
        "schema": {
            "name": "get_workout_detail",
            "description": (
                "Return full per-set detail for one workout (exercises, weights, reps, RPE, "
                "notes). Looked up by workout_uid in the form '<source>:<source_workout_id>' "
                "(e.g. 'hevy:abc-123'). Use after get_workouts to drill into a specific session."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workout_uid": {"type": "string", "description": "Stable workout uid, '<source>:<id>'."},
                },
                "required": ["workout_uid"],
            },
        },
    },
    # ADR-066 (2026-05-31): Hevy routine write-loop. Single fat tool with action
    # dispatcher; respects SPEC §9 "fewer fat tools" guidance. Cron + add-load
    # both ship gated off (SSM defaults false). See docs/specs/SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31.md.
    "manage_hevy_routine": {
        "fn": tool_manage_hevy_routine,
        "schema": {
            "name": "manage_hevy_routine",
            "description": (
                "Author, preview, push, list, fetch, archive, or score adherence on Hevy "
                "training routines. One tool, action-dispatched. Actions: 'draft' (the "
                "deterministic programmer builds its OWN routine from your state — does NOT "
                "take an exercise list), 'draft_custom' (author a routine from an explicit "
                "exercise/set/weight list you supply — use this to push a hand-designed "
                "session), 'dry_run' (compile a draft into the Hevy POST body for preview), "
                "'commit' (push to Hevy — requires explicit routine_id), 'list' (date range), "
                "'get' (one IR by routine_id), 'archive' (rename + folder-move; Hevy has no "
                "DELETE), 'floor' (≈20-min variant), 're_entry' (deliberately easy after a "
                "break), 'adherence' (programmed-vs-performed). Typical custom flow: "
                "draft_custom → dry_run → commit. Subtract-only autoregulation on the 'draft' "
                "path. TITLES ARE AUTO-RENDERED: the compiler names every routine "
                "'Phase - Type - N - Y' (e.g. 'Foundation - Push - 2 - 2') from config + "
                "performed history — DO NOT pass a title; leave it to the compiler. (A title "
                "you pass is ignored unless you also set force_title=true.) Honest framing: "
                "'deterministic volume-landmark programming with red-day deload guard' — never "
                "describe as 'autoregulated' publicly until the readiness signal is validated."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "One of: draft, draft_custom, dry_run, commit, list, get, archive, floor, re_entry, adherence.",
                    },
                    "exercises": {
                        "type": "array",
                        "description": (
                            "draft_custom only: ordered exercise list. Each item: "
                            "{movement_key OR title/name (ANY built-in or custom Hevy exercise "
                            "resolves by its exact Hevy title — e.g. 'Cycling', 'Burpee', "
                            "'Kettlebell Swing'; no catalog edit needed), "
                            "sets:[{weight_lbs OR weight_kg, reps OR rep_range_start+rep_range_end, "
                            "type?, count? (repeat the set N times), duration_seconds? (cardio), "
                            "distance_meters?}], "
                            "rest_seconds?, superset_id? (same int = superset/circuit/tri-set), notes?}. "
                            "If a title doesn't exist in Hevy yet it is auto-created (see "
                            "create_missing); to control the new exercise pass muscle_group, "
                            "exercise_type, and/or equipment_category on that item (else inferred). "
                            "Loads are taken verbatim — the platform does not compute them."
                        ),
                        "items": {"type": "object"},
                    },
                    "create_missing": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "draft_custom only: when an exercise title isn't found in Hevy, "
                            "create it (so the draft never gets stuck) and report it under "
                            "created_exercises. Set false to instead fail loudly with "
                            "suggestions. Only creates from a human title, never a bare movement_key."
                        ),
                    },
                    "archetype": {
                        "type": "string",
                        "description": "draft_custom only: session type for the title (e.g. 'push', 'pull', 'upper'). Defaults to 'custom'.",
                    },
                    "title": {
                        "type": "string",
                        "description": (
                            "DO NOT pass this. The compiler auto-renders 'Phase - Type - N - Y'. "
                            "Any title here is IGNORED unless force_title=true is also set."
                        ),
                    },
                    "force_title": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Escape hatch (default false). When true, the literal `title` you pass "
                            "is used verbatim instead of the auto-rendered convention; a warning is "
                            "logged. Leave off for normal use."
                        ),
                    },
                    "notes": {"type": "string", "description": "draft_custom only: one-line session WHY-note shown in Hevy."},
                    "routine_id": {
                        "type": "string",
                        "description": "Platform routine_id. Required for dry_run, commit, get, archive, adherence.",
                    },
                    "target_date": {"type": "string", "description": "ISO YYYY-MM-DD. Defaults to today (UTC)."},
                    "start_date": {"type": "string", "description": "List action: range start (YYYY-MM-DD)."},
                    "end_date": {"type": "string", "description": "List action: range end (YYYY-MM-DD)."},
                    "limit": {"type": "integer", "default": 50, "description": "Max items returned by list."},
                    "recovery_tier": {
                        "type": "string",
                        "description": "green | yellow | red — overrides default yellow for draft/floor/re_entry.",
                    },
                    "acwr_flag": {"type": "string", "description": "safe | caution | high | very_high."},
                    "volume_7d": {"type": "object", "description": "Optional map of muscle->sets completed in last 7d."},
                    "z2_minutes_7d": {"type": "number"},
                    "days_since_last_workout": {"type": "integer"},
                },
                "required": ["action"],
            },
        },
    },
    "get_reading_shelf": {
        "fn": tool_get_reading_shelf,
        "schema": {
            "name": "get_reading_shelf",
            "description": (
                "The reading shelf (Mind pillar): currently-reading, the queue, finished books, and the "
                "'set down' (abandoned) shelf. Use for: 'what am I reading', 'my bookshelf', 'reading list'."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_reading_recommendation": {
        "fn": tool_get_reading_recommendation,
        "schema": {
            "name": "get_reading_recommendation",
            "description": (
                "A curated next-read pick from the queue, each with a DECOMPOSED reason string + confidence "
                "label. Below the data n-gate it is propose-and-dispose (one pick, stated as a hypothesis). "
                "Use for: 'what should I read next', 'recommend a book'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Max picks to surface (default 3; capped to 1 at low n)."}},
                "required": [],
            },
        },
    },
    "get_reading_profile": {
        "fn": tool_get_reading_profile,
        "schema": {
            "name": "get_reading_profile",
            "description": "The reading calibration profile: taste hypothesis, curriculum phase, difficulty ratchet, roundedness wheel, trust mode.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_reading_history": {
        "fn": tool_get_reading_history,
        "schema": {
            "name": "get_reading_history",
            "description": "Reading-session history over a date range + the current input streak (consecutive days read). Defaults to the trailing 90 days.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default 90 days ago)."},
                    "end_date": {"type": "string", "description": "End YYYY-MM-DD (default today)."},
                },
                "required": [],
            },
        },
    },
    "get_due_recalls": {
        "fn": tool_get_due_recalls,
        "schema": {
            "name": "get_due_recalls",
            "description": "Spaced-retrieval recall prompts that are due now (private). The sparse-index sweep that powers the cockpit's recall nudge.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_reading_track_record": {
        "fn": tool_get_reading_track_record,
        "schema": {
            "name": "get_reading_track_record",
            "description": "Cora's reading-recommendation track record + auditable hit rate (low-confidence until enough recommendations resolve).",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Max records (default 50)."}},
                "required": [],
            },
        },
    },
    "get_constellation": {
        "fn": tool_get_constellation,
        "schema": {
            "name": "get_constellation",
            "description": (
                "The Constellation idea-graph (Mind pillar signature). Honest empty state below the node threshold; "
                "pass idea_id to fetch one node + its edges. Whole-graph enumeration ships in Phase E."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"idea_id": {"type": "string", "description": "Optional — fetch a single idea node + its edges."}},
                "required": [],
            },
        },
    },
    "manage_reading": {
        "fn": tool_manage_reading,
        "schema": {
            "name": "manage_reading",
            "description": (
                "Write fat-tool for the reading library (draft -> dry_run -> commit). Every mutating action PREVIEWS by "
                "default (dry_run=true) and writes only on an explicit dry_run=false. Actions: add_book, update_status "
                "(abandon requires abandon_reason), log_session, add_note, answer_recall, debrief, log_outcome, "
                "update_profile, onboard (taste-archaeology interview)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "add_book",
                            "update_status",
                            "log_session",
                            "add_note",
                            "answer_recall",
                            "debrief",
                            "log_outcome",
                            "update_profile",
                            "onboard",
                            "map_ideas",
                        ],
                        "description": "Which write to perform.",
                    },
                    "dry_run": {"type": "boolean", "description": "Preview without writing (default true). Set false to commit."},
                    "bookId": {"type": "string", "description": "Target book id (most actions)."},
                    "title": {"type": "string", "description": "[add_book] Book title."},
                    "author": {"type": "string", "description": "[add_book] Author."},
                    "isbn13": {"type": "string", "description": "[add_book] ISBN-13 (improves cover + id)."},
                    "olid": {"type": "string", "description": "[add_book] Open Library id."},
                    "pageCount": {"type": "integer", "description": "[add_book] Page count."},
                    "status": {"type": "string", "description": "[add_book/update_status] want|reading|finished|abandoned."},
                    "abandon_reason": {"type": "string", "description": "[update_status=abandoned] wrong-time|wrong-book|stalled|other."},
                    "minutes": {"type": "number", "description": "[log_session] Minutes read."},
                    "pages": {"type": "integer", "description": "[log_session] Pages read."},
                    "date": {"type": "string", "description": "[log_session] Date YYYY-MM-DD."},
                    "type": {"type": "string", "description": "[add_note] highlight|reflection|synthesis."},
                    "text": {"type": "string", "description": "[add_note] Note text."},
                    "public": {"type": "boolean", "description": "[add_note/debrief] Whether the note may be shown publicly."},
                    "takeaway": {"type": "string", "description": "[debrief] The one public takeaway."},
                    "prompt_id": {"type": "string", "description": "[answer_recall] Recall prompt id."},
                    "answer": {
                        "type": "string",
                        "description": "[answer_recall] The reader's recall answer (gist-scored; advances the interval).",
                    },
                    "next_due": {"type": "string", "description": "[answer_recall] (reserved) explicit next-due ISO override."},
                    "ts": {"type": "string", "description": "[log_outcome] Recommendation timestamp id."},
                    "resolved_outcome": {"type": "string", "description": "[log_outcome] right|surprised|unexpected|miss."},
                    "answers": {
                        "type": "object",
                        "description": "[onboard] {question: answer} from the taste interview (omit to get the questions).",
                    },
                },
                "required": ["action"],
            },
        },
    },
    # Phase 4.9 (2026-05-16): meta-tool for tool discoverability across the
    # 116+ registered tools. Function defined just below the dict, referenced
    # here via _list_tools_proxy which forwards to the real impl at call time.
    "get_field_notes": {
        "fn": tool_get_field_notes,
        "schema": {
            "name": "get_field_notes",
            "description": (
                "Retrieve the weekly Field Notes entry — AI Lab Notes (present/lookback/focus paragraphs) "
                "and any existing Matthew response. Defaults to current week if no week specified. "
                "Use for: 'show me this week's field notes', 'what did the AI say this week', "
                "'read field notes for week 14', 'get my lab notebook'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "week": {"type": "string", "description": "ISO week e.g. '2026-W14'. Defaults to current week."},
                },
                "required": [],
            },
        },
    },
    "log_field_note_response": {
        "fn": tool_log_field_note_response,
        "schema": {
            "name": "log_field_note_response",
            "description": (
                "Write Matthew's response to the right page of a Field Notes entry. "
                "The AI Lab Notes must already exist for that week. Uses update_item to never overwrite AI fields. "
                "Use for: 'respond to field notes', 'write my side of the lab notebook', "
                "'I disagree with the AI notes this week', 'add my response to week 14'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "week": {"type": "string", "description": "ISO week e.g. '2026-W14'. Required."},
                    "notes": {"type": "string", "description": "Matthew's prose response. No length limit."},
                    "agreement": {
                        "type": "string",
                        "enum": ["agree", "disagree", "mixed"],
                        "description": "Matthew's overall take on the AI notes.",
                    },
                    "disputed": {"type": "array", "items": {"type": "string"}, "description": "Specific AI claims Matthew pushes back on."},
                    "added": {"type": "string", "description": "What Matthew noticed that the AI missed."},
                },
                "required": ["week", "notes"],
            },
        },
    },
    "list_available_tools": {
        "fn": "tool_list_available_tools",  # placeholder; rebound below
        "schema": {
            "name": "list_available_tools",
            "description": (
                "Discover MCP tools by domain or keyword. Use when you're unsure "
                "which specific tool matches a question. Returns tool names, "
                "domains, and short descriptions. "
                "Filter by domain (e.g. 'health', 'training', 'nutrition', 'sleep', "
                "'journal', 'cgm', 'labs', 'habits', 'lifestyle', 'board', "
                "'character', 'social', 'memory', 'measurements', 'strength', "
                "'coach_intelligence', 'decisions', 'hypotheses', 'challenges') "
                "or keyword (matches tool name + description substring)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Optional domain filter (short module name)."},
                    "keyword": {
                        "type": "string",
                        "description": "Optional case-insensitive substring " "match against name + description.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 30, max 100).",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 30,
                    },
                },
                "required": [],
            },
        },
    },
    # ── #422 EVR-01/02: habit causality reflection loop (secondary capture channel) ──
    "get_habit_reflection_queue": {
        "fn": tool_get_habit_reflection_queue,
        "schema": {
            "name": "get_habit_reflection_queue",
            "description": (
                "#422: Recent habit-days still missing causality context — what to ask Matthew about. "
                "Deterministically returns missed days with no recorded 'why' and completed days with no "
                "trigger/reward, scoped to the last N days. Use this OPTIONALLY when Matthew is already "
                "reflecting on his day/week: pick a couple, ask about them conversationally, then call "
                "log_habit_reflection with his answer. Never nag or schedule — it only makes the ask possible. "
                "Use for: 'ask me about my habits', 'what habit context am I missing?', end-of-day/week reflection."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Look back N days (default 7, max 31). Use 7 for a weekly view."},
                },
                "required": [],
            },
        },
    },
    "log_habit_reflection": {
        "fn": tool_log_habit_reflection,
        "schema": {
            "name": "log_habit_reflection",
            "description": (
                "#422: Log Matthew's reflection about a habit on a date — the richer, Claude-sourced context "
                "layer that complements in-app Habitify notes. Record any of trigger (what cued it), reward "
                "(what it paid back), why_missed (why a missed day slipped), or free-text context. Stored "
                "verbatim, keyed to habit+date, tagged channel=claude_reflection so it coexists with (never "
                "overwrites) Habitify-sourced notes. Renders on the habits page. "
                "Use for: 'I missed meditation because I was traveling', 'the walk is triggered by my morning coffee'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "habit": {"type": "string", "description": "Habit name as it appears in the tracker (e.g. 'Meditate')."},
                    "date": {"type": "string", "description": "Date the reflection is about (YYYY-MM-DD). Defaults to today."},
                    "trigger": {"type": "string", "description": "What cued the habit (for completed days). Optional."},
                    "reward": {"type": "string", "description": "What the habit paid back / how it felt. Optional."},
                    "why_missed": {"type": "string", "description": "Why a missed day slipped (travel, illness, low day…). Optional."},
                    "context": {
                        "type": "string",
                        "description": "Any free-text reflection. An explicit 'trigger:'/'reward:' prefix is lifted.",
                    },
                },
                "required": ["habit"],
            },
        },
    },
    # ── #915: ad-hoc coach check-in loop (coaches ask, Matthew answers verbatim) ──
    "get_coach_checkin_queue": {
        "fn": tool_get_coach_checkin_queue,
        "schema": {
            "name": "get_coach_checkin_queue",
            "description": (
                "#915: Up to 3 open check-in questions FROM Matthew's AI coaches — qualitative questions whose "
                "verbatim answers pair with (or explain the absence of) the quantitative data. Open questions "
                "persist: re-calls return the SAME queue; fresh questions are generated (Bedrock, in the asking "
                "coach's persona, grounded in live presence/adaptive-mode/manual-source context) only when the "
                "queue is empty. Ask conversationally, one at a time, then call log_coach_checkin. Skipping is "
                "always valid with zero penalty — never nag. "
                "Use for: 'what do my coaches want to know?', 'coach check-in', periodic qualitative catch-ups."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "coach_id": {
                        "type": "string",
                        "description": (
                            "Optional: have a specific coach ask (sleep, nutrition, training, mind, physical, "
                            "glucose, labs, explorer). Default: auto-picked from the most informative signal."
                        ),
                    },
                    "count": {"type": "integer", "description": "Questions to generate when the queue is empty (1-3, default 3)."},
                },
                "required": [],
            },
        },
    },
    "log_coach_checkin": {
        "fn": tool_log_coach_checkin,
        "schema": {
            "name": "log_coach_checkin",
            "description": (
                "#915: Record Matthew's answer to a coach check-in question VERBATIM (his words, never a "
                "paraphrase — ADR-104), or an explicit skip (always valid, zero penalty). The answer becomes "
                "durable qualitative context stored with the coach's records. "
                "Use after get_coach_checkin_queue, once Matthew has responded (or declined)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "checkin_id": {
                        "type": "string",
                        "description": "The question's checkin_id from get_coach_checkin_queue (starts with 'CHECKIN#').",
                    },
                    "coach_id": {"type": "string", "description": "Optional: the asking coach's id — speeds up the lookup."},
                    "answer": {"type": "string", "description": "Matthew's answer, verbatim. Omit when skip=true."},
                    "skip": {"type": "boolean", "description": "true = Matthew declines this question (zero penalty)."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional topic tags (max 5)."},
                },
                "required": ["checkin_id"],
            },
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4.9 (2026-05-16): list_available_tools — meta-tool implementation
# ═══════════════════════════════════════════════════════════════════════════


def tool_list_available_tools(domain: str = None, keyword: str = None, limit: int = 30):
    """List MCP tools, optionally filtered by domain (module short-name) or
    keyword (substring of tool name or description). Returns at most `limit`
    items, ordered alphabetically.
    """
    if limit is None or limit < 1:
        limit = 30
    if limit > 100:
        limit = 100
    matches = []
    kw_lower = (keyword or "").lower().strip()
    for tool_name, entry in TOOLS.items():
        fn = entry.get("fn")
        schema = entry.get("schema", {})
        description = schema.get("description") or ""
        module = getattr(fn, "__module__", "") if fn else ""
        short_module = module.rsplit(".tools_", 1)[-1] if ".tools_" in module else module

        if domain and short_module != domain:
            continue
        if kw_lower:
            haystack = (tool_name + " " + description).lower()
            if kw_lower not in haystack:
                continue
        matches.append(
            {
                "name": tool_name,
                "domain": short_module,
                "description": description[:200] + ("…" if len(description) > 200 else ""),
            }
        )

    matches.sort(key=lambda m: m["name"])
    return {
        "total_matching": len(matches),
        "total_registered": len(TOOLS),
        "tools": matches[:limit],
        "filter": {"domain": domain, "keyword": keyword, "limit": limit},
    }


# Rebind the placeholder string in the TOOLS dict to the real function now
# that it's defined. The string was a marker for test_r2_all_fn_references_exist
# (which looks for tool_* names as fn-refs); rebinding here makes the dispatcher
# resolve to the callable at runtime.
TOOLS["list_available_tools"]["fn"] = tool_list_available_tools
