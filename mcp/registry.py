"""
Tool registry: maps tool names to their functions and JSON schemas.
"""

from typing import Any, cast

from mcp.config import RAW_DAY_LIMIT, SOURCES

# BENCH-1: cut-benchmarking & regain firewall (PRIVATE, view-dispatched).
from mcp.tools_benchmark import GET_BENCHMARK_DESCRIPTION, tool_get_benchmark

# #1478: one-call session opener aggregating six pending-capture surfaces.
from mcp.tools_capture import tool_get_capture_queues
from mcp.tools_cgm import tool_get_cgm

# #915: ad-hoc coach check-in loop — coaches ask, Matthew answers verbatim.
from mcp.tools_coach_checkin import tool_get_coach_checkin_queue, tool_log_coach_calibration, tool_log_coach_checkin

# #1690 (epic #1687 S3): correct a weekly-review-pack item by number from chat.
from mcp.tools_coach_corrections import tool_log_coach_correction
from mcp.tools_coach_intelligence import (
    tool_audit_coach_dossier,
    tool_evaluate_prediction,
    tool_get_coach_thread,
    tool_get_coach_track_record,
    tool_get_predictions,
)
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

# #3692: the model-facing selection prose lives in a cohesive sibling so this file
# stays the wiring table it says it is. Two descriptions stayed inline below — see
# that module's docstring for which and why.
from mcp.tools_descriptions import (
    ARCHIVE_HORIZON_DESCRIPTION,
    AUDIT_COACH_DOSSIER_DESCRIPTION,
    CLOSE_TODOIST_TASK_DESCRIPTION,
    CREATE_EXPERIMENT_DESCRIPTION,
    CREATE_TODOIST_TASK_DESCRIPTION,
    CURATE_HORIZON_DESCRIPTION,
    DELETE_PLATFORM_MEMORY_DESCRIPTION,
    DESCRIBE_PLATFORM_SURFACES_DESCRIPTION,
    END_EXPERIMENT_DESCRIPTION,
    EVALUATE_PREDICTION_DESCRIPTION,
    FIND_DAYS_DESCRIPTION,
    GET_ACWR_STATUS_DESCRIPTION,
    GET_CAPTURE_QUEUES_DESCRIPTION,
    GET_CGM_DESCRIPTION,
    GET_COACH_CHECKIN_QUEUE_DESCRIPTION,
    GET_COACH_THREAD_DESCRIPTION,
    GET_COACH_TRACK_RECORD_DESCRIPTION,
    GET_CONSTELLATION_DESCRIPTION,
    GET_DAILY_METRICS_DESCRIPTION,
    GET_DAILY_SNAPSHOT_DESCRIPTION,
    GET_DECISIONS_DESCRIPTION,
    GET_DEFICIT_SUSTAINABILITY_DESCRIPTION,
    GET_DUE_RECALLS_DESCRIPTION,
    GET_EXERCISE_HISTORY_DESCRIPTION,
    GET_EXERCISE_NOTES_DESCRIPTION,
    GET_EXERCISE_NOTES_INPUT,
    GET_EXPERIMENT_CYCLE_DESCRIPTION,
    GET_EXPERIMENT_RESULTS_DESCRIPTION,
    GET_FIELD_NOTES_DESCRIPTION,
    GET_FLOURISHING_TREND_DESCRIPTION,
    GET_FRESHNESS_STATUS_DESCRIPTION,
    GET_HABIT_COMPLETION_DESCRIPTION,
    GET_HABIT_REFLECTION_QUEUE_DESCRIPTION,
    GET_HORIZONS_DESCRIPTION,
    GET_INSIGHTS_DESCRIPTION,
    GET_INTAKE_RESPONSE_DESCRIPTION,
    GET_INTELLIGENCE_QUALITY_DESCRIPTION,
    GET_LABS_DESCRIPTION,
    GET_MOOD_DESCRIPTION,
    GET_MUSCLE_VOLUME_DESCRIPTION,
    GET_NUTRITION_DESCRIPTION,
    GET_PLATFORM_COST_DESCRIPTION,
    GET_PLATFORM_STATE_DESCRIPTION,
    GET_PLATFORM_SURFACE_DESCRIPTION,
    GET_PREDICTIONS_DESCRIPTION,
    GET_READING_HISTORY_DESCRIPTION,
    GET_READING_PROFILE_DESCRIPTION,
    GET_READING_RECOMMENDATION_DESCRIPTION,
    GET_READING_SHELF_DESCRIPTION,
    GET_READING_TRACK_RECORD_DESCRIPTION,
    GET_SOCIAL_CONNECTION_TREND_DESCRIPTION,
    GET_SOCIAL_DASHBOARD_DESCRIPTION,
    GET_SOURCES_DESCRIPTION,
    GET_TODOIST_SNAPSHOT_DESCRIPTION,
    GET_TRAINING_DESCRIPTION,
    GET_WEIGHT_LOSS_PROGRESS_DESCRIPTION,
    GET_WORKOUT_DETAIL_DESCRIPTION,
    GET_WORKOUTS_DESCRIPTION,
    GET_ZONE2_BREAKDOWN_DESCRIPTION,
    LIST_AVAILABLE_TOOLS_DESCRIPTION,
    LIST_EXPERIMENTS_DESCRIPTION,
    LIST_MEMORY_CATEGORIES_DESCRIPTION,
    LOG_COACH_CALIBRATION_DESCRIPTION,
    LOG_COACH_CHECKIN_DESCRIPTION,
    LOG_COACH_CORRECTION_DESCRIPTION,
    LOG_DECISION_DESCRIPTION,
    LOG_EVENING_INTAKE_DESCRIPTION,
    LOG_FIELD_NOTE_RESPONSE_DESCRIPTION,
    LOG_HABIT_REFLECTION_DESCRIPTION,
    MANAGE_DIARY_CLAIMS_DESCRIPTION,
    MANAGE_HEVY_ROUTINE_DESCRIPTION,
    MANAGE_READING_DESCRIPTION,
    MANAGE_SICK_DAYS_DESCRIPTION,
    MARK_JOURNAL_QUOTE_DESCRIPTION,
    PLAN_NEXT_SESSION_DESCRIPTION,
    READ_PLATFORM_MEMORY_DESCRIPTION,
    SAVE_INSIGHT_DESCRIPTION,
    SEARCH_ACTIVITIES_DESCRIPTION,
    UPDATE_DECISION_OUTCOME_DESCRIPTION,
    UPDATE_INSIGHT_OUTCOME_DESCRIPTION,
    UPDATE_TODOIST_TASK_DESCRIPTION,
    WRITE_PLATFORM_MEMORY_DESCRIPTION,
)
from mcp.tools_habits import tool_get_habit_reflection_queue, tool_log_habit_reflection
from mcp.tools_health import tool_get_daily_metrics, tool_get_readiness_score, tool_get_weight_loss_progress

# SPEC_HEVY_AND_NUTRITION_BRIDGE §2.6 — source-agnostic workout query layer
from mcp.tools_hevy import tool_get_workout_detail, tool_get_workouts

# ADR-066 (2026-05-31): Hevy routine write-loop fat tool.
from mcp.tools_hevy_routine import tool_manage_hevy_routine
from mcp.tools_journal import tool_get_flourishing_trend, tool_get_mood, tool_manage_diary_claims, tool_mark_journal_quote
from mcp.tools_labs import tool_get_freshness_status, tool_get_labs
from mcp.tools_lifestyle import (
    tool_create_experiment,
    tool_end_experiment,
    tool_get_experiment_results,
    tool_get_field_notes,
    tool_get_insights,
    tool_get_intake_response,
    tool_list_experiments,
    tool_log_evening_intake,
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
from mcp.tools_meta import list_registered_tools  # #3668: the meta-tool body, lifted out of this table
from mcp.tools_nutrition import tool_get_deficit_sustainability, tool_get_nutrition
from mcp.tools_plan import tool_plan_next_session

# #3668: the three hot-path named tools (cycle / habits / cost) over the same waiter
# machinery the index uses — never a second copy of the rule declaration.
from mcp.tools_platform import tool_get_experiment_cycle, tool_get_habit_completion, tool_get_platform_cost

# #3692: the conversational half of /method/state/ (#3691) — the joined read of the
# BUILD, answered from chat against the same published artifact the page renders.
from mcp.tools_platform_state import tool_get_platform_state
from mcp.tools_reading import (
    tool_archive_horizon,
    tool_curate_horizon,
    tool_get_constellation,
    tool_get_due_recalls,
    tool_get_horizons,
    tool_get_reading_history,
    tool_get_reading_profile,
    tool_get_reading_recommendation,
    tool_get_reading_shelf,
    tool_get_reading_track_record,
    tool_manage_reading,
)
from mcp.tools_sick_days import tool_manage_sick_days
from mcp.tools_social import tool_get_social_dashboard
from mcp.tools_social_connection import tool_get_social_connection_trend  # lifted out of tools_lifestyle by #2221
from mcp.tools_strength import tool_get_exercise_history, tool_get_muscle_volume

# tools_calendar retired v3.7.46 (ADR-030) — google_calendar import removed
# #3668: the derived surface index + the waiter. Two tools, full coverage, and the
# MCP_TOOL_AUDIT tool-count discipline preserved (59 endpoints, not 59 new tools).
from mcp.tools_surfaces import tool_describe_platform_surfaces, tool_get_platform_surface
from mcp.tools_todoist import close_todoist_task, create_todoist_task, tool_get_todoist_snapshot, update_todoist_task
from mcp.tools_training import tool_get_acwr_status, tool_get_training
from mcp.tools_training_notes import tool_get_exercise_notes

# Vacation fund tracker ($1/workout-mile since experiment start).

TOOLS = {
    # #4036 pays this module's #1665 ceiling the way #3891 did — by extraction, never by
    # raising the ratchet: this tool's parameter table (which the issue extends with the
    # owner-dismissal action) lives in the cohesive sibling mcp/tools_descriptions.py. The
    # schema NAME stays here, which is what R3 reads.
    "get_exercise_notes": {
        "fn": tool_get_exercise_notes,
        "schema": {
            "name": "get_exercise_notes",
            "description": GET_EXERCISE_NOTES_DESCRIPTION,
            "inputSchema": GET_EXERCISE_NOTES_INPUT,
        },
    },
    "get_sources": {
        "fn": tool_get_sources,
        "schema": {
            "name": "get_sources",
            "description": GET_SOURCES_DESCRIPTION,
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    # get_calendar_events + get_schedule_load removed v3.7.46 (ADR-030)
    # Google Calendar integration retired — Smartsheet IT blocks all zero-touch options.
    "get_daily_snapshot": {
        "fn": tool_get_daily_snapshot,
        "schema": {
            "name": "get_daily_snapshot",
            "description": GET_DAILY_SNAPSHOT_DESCRIPTION,
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
            "description": FIND_DAYS_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD."},
                    "mode": {
                        "type": "string",
                        "enum": ["filter", "similar"],
                        "description": "Default 'filter' (threshold conditions). 'similar' = nearest-neighbour day retrieval around target_date.",
                    },
                    "target_date": {
                        "type": "string",
                        "description": "[similar] Anchor day YYYY-MM-DD to find analogs of (e.g. today). Required for mode='similar'.",
                    },
                    "features": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[similar] Numeric day-level fields forming the vector. Default for whoop: recovery_score, hrv, resting_heart_rate, strain, sleep_duration_hours. Required for other sources.",
                    },
                    "k": {"type": "number", "description": "[similar] Max matches to return (default 5, cap 20)."},
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
            "description": GET_INTELLIGENCE_QUALITY_DESCRIPTION,
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
            "description": GET_COACH_THREAD_DESCRIPTION,
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
            "description": GET_PREDICTIONS_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "confirmed", "refuted", "inconclusive", "expired", "declined"]},
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
            "description": GET_COACH_TRACK_RECORD_DESCRIPTION,
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
    "audit_coach_dossier": {
        "fn": tool_audit_coach_dossier,
        "schema": {
            "name": "audit_coach_dossier",
            "description": AUDIT_COACH_DOSSIER_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "coach_id": {
                        "type": "string",
                        "description": "Coach name: sleep, nutrition, training, mind, physical, glucose, labs, explorer (accepts _coach suffix too)",
                    },
                    "action": {"type": "string", "enum": ["view", "retract", "correct"], "description": "Default: view"},
                    "record_sk": {
                        "type": "string",
                        "description": "The exact sk of the memory record to retract/correct (e.g. 'COMMITMENT#commit_20260722_...'), from action=view",
                    },
                    "note": {
                        "type": "string",
                        "description": "Why it's retracted / what the correction is — logged verbatim to the corrections ledger",
                    },
                },
                "required": ["coach_id"],
            },
        },
    },
    "evaluate_prediction": {
        "fn": tool_evaluate_prediction,
        "schema": {
            "name": "evaluate_prediction",
            "description": EVALUATE_PREDICTION_DESCRIPTION,
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
            "description": SEARCH_ACTIVITIES_DESCRIPTION,
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
            "description": GET_TRAINING_DESCRIPTION,
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
            "description": GET_DAILY_METRICS_DESCRIPTION,
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
            "description": GET_BENCHMARK_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": (
                            "pace (default), episodes (the cut ledger), maintenance (the regain firewall), "
                            "or prescription (weight-matched training reference for authoring a session), "
                            "or campaign (this cut vs the one that worked, with the levers ranked)."
                        ),
                        "enum": ["pace", "episodes", "maintenance", "prescription", "campaign"],
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
            "description": GET_WEIGHT_LOSS_PROGRESS_DESCRIPTION,
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
    "plan_next_session": {
        "fn": tool_plan_next_session,
        "schema": {
            "name": "plan_next_session",
            "description": PLAN_NEXT_SESSION_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "description": "Session date YYYY-MM-DD. Defaults to today (Pacific)."},
                    "routine_id": {
                        "type": "string",
                        "description": "Stage 2 (#3752): a drafted routine_id to red-team. Runs the four critics over disjoint evidence, applies their changes to the draft, stores the verdicts on it; a veto then blocks commit.",
                    },
                    "veto_override": {
                        "type": "object",
                        "description": (
                            "#4076, stage 2 only: Matthew overrules ONE vetoing critic. {critic: muscle_defense|joints_tendons|"
                            "rate_advocate|blueprint_historian, owner_words: his words VERBATIM, error_class?: corrections-ledger class}. "
                            "Only that critic's veto is marked overridden (recorded on the routine, in the Hevy notes and in the "
                            "corrections ledger); every other critic's changes still apply and any other veto still blocks."
                        ),
                        "properties": {
                            "critic": {"type": "string"},
                            "owner_words": {"type": "string"},
                            "error_class": {"type": "string"},
                        },
                    },
                },
                "required": [],
            },
        },
    },
    "get_exercise_history": {
        "fn": tool_get_exercise_history,
        "schema": {
            "name": "get_exercise_history",
            "description": GET_EXERCISE_HISTORY_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "exercise_name": {
                        "type": "string",
                        "description": "Exercise name, case-insensitive substring match (e.g. 'bench press', 'leg extension').",
                    },
                    "template_id": {
                        "type": "string",
                        "description": "Exact Hevy exercise template id (hex or uuid). Preferred over a name — stable across renames.",
                    },
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to all time (2000-01-01)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today (Pacific)."},
                    "include_warmups": {"type": "boolean", "description": "Include warmup sets. Default false."},
                },
                "required": [],
            },
        },
    },
    "get_muscle_volume": {
        "fn": tool_get_muscle_volume,
        "schema": {
            "name": "get_muscle_volume",
            "description": GET_MUSCLE_VOLUME_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD."},
                    "period": {"type": "string", "enum": ["week", "month"], "description": "Aggregation period. Default 'week'."},
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
            "description": GET_NUTRITION_DESCRIPTION,
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
            "description": (GET_ZONE2_BREAKDOWN_DESCRIPTION),
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
            # Inline, unlike its 80 siblings: tests/test_data_truth_batch.py
            # ::test_device_agreement_never_silent_null asserts these weights appear in the
            # TEXT of this file, so the table can never advertise a blend the code dropped.
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
            "description": SAVE_INSIGHT_DESCRIPTION,
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
    "get_flourishing_trend": {
        "fn": tool_get_flourishing_trend,
        "schema": {
            "name": "get_flourishing_trend",
            "description": GET_FLOURISHING_TREND_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Trailing window in days (7-365, default 90)."},
                    "ema_span": {"type": "integer", "description": "EMA span in OBSERVATIONS not days (3-60, default 14); gaps carried."},
                },
                "required": [],
            },
        },
    },
    "log_evening_intake": {
        "fn": tool_log_evening_intake,
        "schema": {
            "name": "log_evening_intake",
            "description": LOG_EVENING_INTAKE_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Evening count, 0-4 (4 = four or more)."},
                    "date": {"type": "string", "description": "YYYY-MM-DD (default: tonight, the Pacific calendar day)."},
                },
                "required": ["count"],
            },
        },
    },
    "get_intake_response": {
        "fn": tool_get_intake_response,
        "schema": {
            "name": "get_intake_response",
            "description": GET_INTAKE_RESPONSE_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "window_days": {"type": "integer", "description": "Trailing window in days (30-730, default 180)."},
                },
                "required": [],
            },
        },
    },
    "get_insights": {
        "fn": tool_get_insights,
        "schema": {
            "name": "get_insights",
            "description": GET_INSIGHTS_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status_filter": {"type": "string", "description": "Filter by status: 'open', 'acted', or 'resolved'. Omit for all."},
                    "limit": {"type": "integer", "minimum": 1, "description": "Max results to return (default: 50)."},
                },
                "required": [],
            },
        },
    },
    "update_insight_outcome": {
        "fn": tool_update_insight_outcome,
        "schema": {
            "name": "update_insight_outcome",
            "description": UPDATE_INSIGHT_OUTCOME_DESCRIPTION,
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
            "description": GET_LABS_DESCRIPTION,
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
            "description": GET_FRESHNESS_STATUS_DESCRIPTION,
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
            "description": GET_CGM_DESCRIPTION,
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
            "description": GET_MOOD_DESCRIPTION,
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
            "description": CREATE_EXPERIMENT_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short name of the intervention (e.g. 'Creatine 5g daily', 'No screens after 9pm').",
                    },
                    "hypothesis": {"type": "string", "description": "What you expect to happen (e.g. 'Will improve deep sleep % by >5%')."},
                    "start_date": {
                        "type": "string",
                        "description": (
                            "Start date YYYY-MM-DD. Defaults to today. FORBIDDEN when design.randomized_start "
                            "is declared — the start is then drawn at random from the pre-declared window (#1413)."
                        ),
                    },
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
                    "why_now": {
                        "type": "string",
                        "description": (
                            "#1117: why THIS experiment NOW (max 600 chars). If omitted, it auto-derives from the "
                            "promotion trigger: a confirmed hypothesis (source_hypothesis_id) or the promoted "
                            "library entry (library_id — rationale + promoted_date). Absent trigger = honest-empty."
                        ),
                    },
                    "priority": {"type": "string", "description": "#1117: 'high', 'medium', or 'low'."},
                    "hoped_outcome": {"type": "string", "description": "#1117: the outcome hoped for, in plain words (max 600 chars)."},
                    "measurement": {
                        "type": "string",
                        "description": "#1117: the measurement plan — which instrument/metric adjudicates it (max 600 chars).",
                    },
                    "evidence_links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "http(s) link to the evidence."},
                                "title": {"type": "string", "description": "Short label for the link."},
                                "stance": {"type": "string", "description": "'for' or 'against' — dissent is kept, never filtered."},
                            },
                            "required": ["url"],
                        },
                        "description": (
                            "#1117: up to 8 evidence links motivating the experiment. If omitted and library_id is "
                            "set, the library entry's for/against citations are carried automatically."
                        ),
                    },
                    "source_hypothesis_id": {
                        "type": "string",
                        "description": (
                            "#1117: hypothesis_id of the CONFIRMED hypothesis-engine record this experiment was "
                            "promoted from — why_now then auto-derives from it (with the measured effect + CI)."
                        ),
                    },
                    "matthew_note": {
                        "type": "string",
                        "description": (
                            "#1569: OPTIONAL verbatim note in Matthew's own words — 'why I said yes to this one' "
                            "(max 500 chars). Rendered PUBLICLY on the experiment card, voice-tagged human, beside "
                            "the machine's read (the widened Third Wall). Opt-in; omit and the card shows nothing."
                        ),
                    },
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
                            "randomized_start": {
                                "type": "object",
                                "description": (
                                    "#1413 SCED: OPTIONAL randomized-start mode. Declare a FUTURE 7-14 day window; "
                                    "the actual start date is drawn uniformly at random from it at creation (do NOT "
                                    "pass start_date), the window+draw are frozen in the prereg artifact, and "
                                    "end_experiment additionally runs a start-point randomization (permutation) test — "
                                    "the observed pre/post difference ranked against every start the window could have "
                                    "produced. Defeats coincident-trend confounds; valid under autocorrelation. "
                                    "Example: {window_start: '2026-08-01', window_end: '2026-08-10'}."
                                ),
                                "properties": {
                                    "window_start": {
                                        "type": "string",
                                        "description": "First candidate start date, YYYY-MM-DD (must not predate creation).",
                                    },
                                    "window_end": {
                                        "type": "string",
                                        "description": "Last candidate start date, YYYY-MM-DD (window spans 7-14 days).",
                                    },
                                },
                                "required": ["window_start", "window_end"],
                            },
                            "counterfactual": {
                                "type": "object",
                                "description": (
                                    "#1410 the Ghost: OPTIONAL BSTS-lite synthetic-control counterfactual, frozen at "
                                    "pre-registration (no post-hoc spec shopping). Declares control metric slugs the "
                                    "intervention should NOT move (0-3, from the criterion metric list, never the "
                                    "criterion itself), the pre-fit window, and the pre-fit MAPE gate. At close, "
                                    "end_experiment fits the ghost on the pre-period and reports effect = observed − "
                                    "counterfactual with a widening 95% CI — or a stated refusal when the pre-fit MAPE "
                                    "exceeds the frozen gate. Example: {controls: ['resting_heart_rate'], pre_days: 28, "
                                    "mape_gate_pct: 15}."
                                ),
                                "properties": {
                                    "controls": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "0-3 control metric slugs (DESIGN_METRICS, ≠ the criterion metric).",
                                    },
                                    "pre_days": {
                                        "type": "integer",
                                        "description": "Pre-period window in days, 14-120 (default 28).",
                                    },
                                    "mape_gate_pct": {
                                        "type": "number",
                                        "description": "Pre-fit MAPE gate percent, 1-50 (default 15) — worse pre-fit ⇒ no ghost.",
                                    },
                                },
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
            "description": LIST_EXPERIMENTS_DESCRIPTION,
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
            "description": GET_EXPERIMENT_RESULTS_DESCRIPTION,
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
            "description": END_EXPERIMENT_DESCRIPTION,
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
                    "matthew_note": {
                        "type": "string",
                        "description": (
                            "#1569: OPTIONAL verbatim note in Matthew's own words at review time — 'here's how it "
                            "actually went, in his words' (max 500 chars). Public on the experiment card, voice-tagged "
                            "human. Opt-in; omit to leave any existing note untouched."
                        ),
                    },
                },
                "required": ["experiment_id"],
            },
        },
    },
    "get_social_connection_trend": {
        "fn": tool_get_social_connection_trend,
        "schema": {
            "name": "get_social_connection_trend",
            "description": GET_SOCIAL_CONNECTION_TREND_DESCRIPTION,
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
            "description": MANAGE_SICK_DAYS_DESCRIPTION,
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
            "description": GET_SOCIAL_DASHBOARD_DESCRIPTION,
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
            "description": GET_TODOIST_SNAPSHOT_DESCRIPTION,
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
            "description": UPDATE_TODOIST_TASK_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Todoist task id (from get_todoist_snapshot, or the id returned when the task was created).",
                    },
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
            "description": CREATE_TODOIST_TASK_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Task name."},
                    "project_id": {"type": "string", "description": "Todoist project id. Omit for Inbox."},
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
            "description": CLOSE_TODOIST_TASK_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Todoist task id (from get_todoist_snapshot, or the id returned when the task was created).",
                    },
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
            "description": WRITE_PLATFORM_MEMORY_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "Sanctioned memory category (e.g. 'life_context', 'constraints_preferences', "
                            "'failure_patterns', 'what_worked', 'coaching_calibration'). Aliases accepted: "
                            "'episodic_wins' → what_worked, 'failure_pattern' → failure_patterns."
                        ),
                    },
                    "content": {
                        "type": "object",
                        "description": (
                            'Key-value dict of data to store, with the readable core in "summary". '
                            'E.g. {"summary": "work trip Tue-Fri, hotel gym only", "detail": {...}}'
                        ),
                    },
                    "date": {"type": "string", "description": "Date for the record (YYYY-MM-DD). Defaults to today."},
                    "overwrite": {"type": "boolean", "description": "Overwrite if record exists (default true)."},
                    "privacy_tier": {
                        "type": "string",
                        "enum": ["public_ok", "coach_context", "private"],
                        "description": (
                            "Optional per-record privacy override — may only TIGHTEN the category default. "
                            "'private' never reaches any generation prompt."
                        ),
                    },
                    "domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional bare coach ids this memory is relevant to (sleep, training, nutrition, mind, "
                            "physical, glucose, labs, explorer). Default: the category's rule (usually all coaches)."
                        ),
                    },
                },
                "required": ["category", "content"],
            },
        },
    },
    "read_platform_memory": {
        "fn": tool_read_platform_memory,
        "schema": {
            "name": "read_platform_memory",
            "description": READ_PLATFORM_MEMORY_DESCRIPTION,
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
            "description": LIST_MEMORY_CATEGORIES_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "minimum": 1, "maximum": 365, "description": "Days back to scan (default 90)."},
                },
                "required": [],
            },
        },
    },
    "delete_platform_memory": {
        "fn": tool_delete_platform_memory,
        "schema": {
            "name": "delete_platform_memory",
            "description": DELETE_PLATFORM_MEMORY_DESCRIPTION,
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
            "description": LOG_DECISION_DESCRIPTION,
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
                    "note": {
                        "type": "string",
                        "description": (
                            "#1569: OPTIONAL verbatim note in Matthew's own words — 'his call, in his words' "
                            "(max 500 chars). This is what makes the decision PUBLISHABLE: only decisions carrying "
                            "a note render on the site (lab-notes / experiment archive), voice-tagged human, dated. "
                            "Opt-in; omit and the decision stays private (renders nothing)."
                        ),
                    },
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
    # ── #1568 (ADR-142): consent-per-line verbatim journal pull-quotes ────────────
    "mark_journal_quote": {
        "fn": tool_mark_journal_quote,
        "schema": {
            "name": "mark_journal_quote",
            "description": MARK_JOURNAL_QUOTE_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["mark", "unmark", "list"],
                        "description": "mark (default) = store an explicitly-approved line; unmark = revoke; list = show marked lines.",
                    },
                    "date": {"type": "string", "description": "The journal entry's day (YYYY-MM-DD). Required for mark/unmark."},
                    "quote": {
                        "type": "string",
                        "description": "The exact verbatim line (max 500 chars). Required for mark/unmark.",
                    },
                    "approved": {
                        "type": "boolean",
                        "description": "MUST be exactly true, and only after Matthew explicitly approved THIS line. Never inferred.",
                    },
                    "channel": {
                        "type": "string",
                        "enum": ["journal", "video_diary", "solo_recording"],
                        "coerce_outside_enum": True,  # #2664: the one sanctioned opt-out from boundary enum enforcement
                        "description": "Capture channel the line came from. Default journal; any other value coerces to journal server-side (#1806).",
                    },
                    "sk": {"type": "string", "description": "Exact record sk (from list) — alternative selector for unmark."},
                },
                "required": [],
            },
        },
    },
    # ── #1841: the on-tape claims ledger (diary → prediction machinery → diary) ──────
    "manage_diary_claims": {
        "fn": tool_manage_diary_claims,
        "schema": {
            "name": "manage_diary_claims",
            "description": MANAGE_DIARY_CLAIMS_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["due", "log", "list", "called_back"],
                        "description": "due (default) = claims past their stated deadline; log = register consented claims; "
                        "list = the whole ledger; called_back = mark one worked on tape.",
                    },
                    "date": {"type": "string", "description": "The session's day (YYYY-MM-DD). Required for log."},
                    "source_sk": {
                        "type": "string",
                        "description": "The video-diary entry's sk (DATE#<date>#journal#video_diary#<suffix>). Required for log — "
                        "the claim must point at the entry it came from, and the entry must already be ingested.",
                    },
                    "claims": {
                        "type": "array",
                        "description": "0-3 candidate claims. Each: {claim (his words), consent (MUST be exactly true, per claim), "
                        "metric, horizon_days (int, 14-365), and EITHER threshold+condition (gt|gte|lt|lte|eq) OR direction "
                        "(up|down); optional confidence (low|medium|high) and quote (the verbatim line he said it in).",
                        "items": {"type": "object"},
                    },
                    "status": {"type": "string", "description": "Optional status filter for action='list'."},
                    "sk": {"type": "string", "description": "The claim's sk (from action='due'). Required for called_back."},
                    "today": {"type": "string", "description": "Override today's date (YYYY-MM-DD) — testing only."},
                },
                "required": [],
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
            "description": GET_ACWR_STATUS_DESCRIPTION,
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
            "description": GET_DECISIONS_DESCRIPTION,
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
            "description": UPDATE_DECISION_OUTCOME_DESCRIPTION,
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
            "description": GET_DEFICIT_SUSTAINABILITY_DESCRIPTION,
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
            "description": GET_WORKOUTS_DESCRIPTION,
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
            "description": GET_WORKOUT_DETAIL_DESCRIPTION,
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
            "description": MANAGE_HEVY_ROUTINE_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "One of: draft, draft_custom, dry_run, commit, list, get, archive, floor, re_entry, adherence, stall_check.",
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
                            "If a title doesn't exist in Hevy the draft FAILS with suggestions "
                            "(create_missing defaults to false, #3718). To create it deliberately, "
                            "pass create_missing:true AND muscle_group on that item — an inferred "
                            "muscle group once guessed 'shoulders' for a calf press, which would "
                            "have corrupted muscle-volume aggregation permanently. "
                            "Loads are taken verbatim — the platform does not compute them."
                        ),
                        "items": {"type": "object"},
                    },
                    "create_missing": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "draft_custom only: when an exercise title isn't found in Hevy, create "
                            "it and report it under created_exercises. DEFAULTS TO FALSE (#3718) — "
                            "it previously defaulted to true and invented 'Calf Press on Leg Press "
                            "Machine' as a SHOULDERS exercise, which would have counted every calf "
                            "session toward shoulder volume for good. When enabling it, always pass "
                            "muscle_group explicitly rather than letting it be inferred. Only ever "
                            "creates from a human title, never a bare movement_key."
                        ),
                    },
                    "archetype": {
                        "type": "string",
                        "description": "draft_custom only: session type for the title (e.g. 'push', 'pull', 'upper'). Defaults to 'custom'.",
                    },
                    "title": {
                        "type": "string",
                        "description": (
                            "draft_custom only — DO NOT pass this. The compiler auto-renders 'Phase - Type - N - Y'. "
                            "Ignored unless force_title=true is set on the SAME draft_custom call; on 'commit' it does nothing."
                        ),
                    },
                    "force_title": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "draft_custom only — escape hatch (default false). When true, the literal `title` on the SAME "
                            "draft_custom call is used verbatim instead of the auto-rendered convention. It is stored on the "
                            "draft and re-read at commit, so passing it to 'commit' does nothing. Leave off for normal use."
                        ),
                    },
                    "notes": {"type": "string", "description": "draft_custom only: one-line session WHY-note shown in Hevy."},
                    "routine_id": {
                        "type": "string",
                        "description": "Platform routine_id. Required for dry_run, commit, get, archive, adherence.",
                    },
                    "movement_key": {"type": "string", "description": "stall_check: the movement to assess (e.g. 'lat_pulldown')."},
                    "template_id": {"type": "string", "description": "stall_check: exact Hevy template id, when movement_key misses."},
                    "sessions": {"type": "integer", "default": 6, "description": "stall_check: recent sessions to read (3-20)."},
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
            "description": GET_READING_SHELF_DESCRIPTION,
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_reading_recommendation": {
        "fn": tool_get_reading_recommendation,
        "schema": {
            "name": "get_reading_recommendation",
            "description": GET_READING_RECOMMENDATION_DESCRIPTION,
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
            "description": GET_READING_PROFILE_DESCRIPTION,
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_reading_history": {
        "fn": tool_get_reading_history,
        "schema": {
            "name": "get_reading_history",
            "description": GET_READING_HISTORY_DESCRIPTION,
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
            "description": GET_DUE_RECALLS_DESCRIPTION,
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_reading_track_record": {
        "fn": tool_get_reading_track_record,
        "schema": {
            "name": "get_reading_track_record",
            "description": GET_READING_TRACK_RECORD_DESCRIPTION,
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
            "description": GET_CONSTELLATION_DESCRIPTION,
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
            "description": MANAGE_READING_DESCRIPTION,
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
    # Horizons (#1705, epic #1686 S1): the weekly coach-curated media pick.
    "get_horizons": {
        "fn": tool_get_horizons,
        "schema": {
            "name": "get_horizons",
            "description": GET_HORIZONS_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Max picks to return, newest first (default 26)."}},
                "required": [],
            },
        },
    },
    "curate_horizon": {
        "fn": tool_curate_horizon,
        "schema": {
            "name": "curate_horizon",
            "description": CURATE_HORIZON_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The pick's link (fetched + verified before storage)."},
                    "title": {"type": "string", "description": "The pick's title."},
                    "format": {
                        "type": "string",
                        "enum": ["article", "podcast", "video", "paper", "news", "longform", "essay", "song"],
                        "description": "The media format.",
                    },
                    "rationale_tag": {
                        "type": "string",
                        "enum": ["topical", "experiment-relevant"],
                        "description": "Why this pick, this week.",
                    },
                    "pitch": {"type": "string", "description": "A short 'why I sent it' pitch."},
                    "source": {"type": "string", "description": "The outlet / source name (optional)."},
                    "week": {"type": "string", "description": "ISO week 'YYYY-Www' (default: current week)."},
                    "dry_run": {"type": "boolean", "description": "Preview + verify without writing (default true). Set false to commit."},
                    "follow_up_question": {
                        "type": "string",
                        "description": (
                            "Optional (#1706): a question about the pick to surface in the coach check-in queue. "
                            "Alone → asked under the Mind (curating) coach; with handoff_to_coach → the item that coach raises."
                        ),
                    },
                    "handoff_to_coach": {
                        "type": "string",
                        "description": (
                            "Optional (#1706): hand the follow-up to another coach (bare id, e.g. 'training') who raises "
                            "follow_up_question in their next brief/check-in. Requires follow_up_question."
                        ),
                    },
                },
                "required": ["url", "title", "format", "rationale_tag"],
            },
        },
    },
    "archive_horizon": {
        "fn": tool_archive_horizon,
        "schema": {
            "name": "archive_horizon",
            "description": ARCHIVE_HORIZON_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "week": {"type": "string", "description": "ISO week 'YYYY-Www' to archive (default: last week)."},
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview the retrospective without writing (default true). Set false to commit.",
                    },
                },
                "required": [],
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
            "description": GET_FIELD_NOTES_DESCRIPTION,
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
            "description": LOG_FIELD_NOTE_RESPONSE_DESCRIPTION,
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
            "description": LIST_AVAILABLE_TOOLS_DESCRIPTION,
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
                        "description": (
                            "Max results to return. Defaults to 100 — enough to cover the "
                            "whole registry (67 tools) unfiltered, so a no-arg call returns "
                            "everything rather than a partial, misleading slice. Max 100."
                        ),
                        "minimum": 1,
                        "maximum": 100,
                        "default": 100,
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
            "description": GET_HABIT_REFLECTION_QUEUE_DESCRIPTION,
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
            "description": LOG_HABIT_REFLECTION_DESCRIPTION,
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
            "description": GET_COACH_CHECKIN_QUEUE_DESCRIPTION,
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
            "description": LOG_COACH_CHECKIN_DESCRIPTION,
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
    # #1481: conversational self-calibration — the asking coach re-grades itself from the answer.
    "log_coach_calibration": {
        "fn": tool_log_coach_calibration,
        "schema": {
            "name": "log_coach_calibration",
            "description": LOG_COACH_CALIBRATION_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "checkin_id": {
                        "type": "string",
                        "description": "The ANSWERED check-in this calibration derives from (starts with 'CHECKIN#').",
                    },
                    "coach_id": {"type": "string", "description": "Optional: the asking coach's id — speeds up the lookup."},
                    "subdomain": {
                        "type": "string",
                        "description": "The subdomain being re-graded (reuse existing CONFIDENCE# vocabulary where it fits).",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "hold"],
                        "description": "up = the answer clarified/confirmed the coach's read; down = it revealed a blind spot; hold = record the learning without a confidence move.",
                    },
                    "takeaway": {
                        "type": "string",
                        "description": "What the coach learned, tightly paraphrasing the answer — no invented context (max 600 chars).",
                    },
                    "answer_excerpt": {
                        "type": "string",
                        "description": "Optional: the exact phrase of Matthew's answer this rests on — must appear verbatim in the stored answer.",
                    },
                    "weight": {
                        "type": "number",
                        "description": "Optional confidence-move weight 0.1-1.0 (default 0.5; 1.0 = as strong as one graded prediction, the hard cap).",
                    },
                },
                "required": ["checkin_id", "subdomain", "direction", "takeaway"],
            },
        },
    },
    # #1478: one-call session opener aggregating six pending-capture surfaces.
    "get_capture_queues": {
        "fn": tool_get_capture_queues,
        "schema": {
            "name": "get_capture_queues",
            "description": GET_CAPTURE_QUEUES_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "log_coach_correction": {
        "fn": tool_log_coach_correction,
        "schema": {
            "name": "log_coach_correction",
            "description": LOG_COACH_CORRECTION_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "item_number": {
                        "type": "integer",
                        "description": "The pack item number to correct (the #N from this week's review-pack email).",
                    },
                    "correction": {
                        "type": "string",
                        "description": "What was wrong and what it should say — Matthew's correction, stored verbatim.",
                    },
                    "error_class": {
                        "type": "string",
                        "description": (
                            "Optional error-class override. One of: stale-baseline, ungrounded-behavioral, "
                            "cross-coach-inconsistency, framing, checkable-metric, hedged-safe, defense-held, other. "
                            "Unrecognized values are stored as 'other' (original label preserved), never rejected."
                        ),
                    },
                },
                "required": ["item_number", "correction"],
            },
        },
    },
    # ── #3668: the surface index, the waiter, and the three hot-path named tools ──
    "describe_platform_surfaces": {
        "fn": tool_describe_platform_surfaces,
        "schema": {
            "name": "describe_platform_surfaces",
            "description": DESCRIBE_PLATFORM_SURFACES_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Substring filter over surface name / question / example phrasing."},
                    "include_excluded": {"type": "boolean", "description": "Also list reader-only surfaces + their exclusion reasons."},
                    "detail": {"type": "boolean", "description": "Include the derivation chain and phase-read counts behind each rule."},
                    "limit": {"type": "integer", "description": "Max surfaces to return (default 200, cap 300)."},
                },
                "required": [],
            },
        },
    },
    "get_platform_surface": {
        "fn": tool_get_platform_surface,
        "schema": {
            "name": "get_platform_surface",
            "description": GET_PLATFORM_SURFACE_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Surface name from describe_platform_surfaces ('/api/...' also accepted)."},
                    "params": {"type": "object", "description": "Query parameters for the surface (see its `params` in the index)."},
                    "question": {"type": "string", "description": "The question you are answering — recorded verbatim if this is a miss."},
                    "explain_against": {"type": "string", "description": "A second surface name; reconciles the two surfaces' rules."},
                },
                "required": ["name"],
            },
        },
    },
    "get_experiment_cycle": {
        "fn": tool_get_experiment_cycle,
        "schema": {
            "name": "get_experiment_cycle",
            "description": GET_EXPERIMENT_CYCLE_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD — which cycle a past date belonged to. Default: today (PT)."}
                },
                "required": [],
            },
        },
    },
    "get_habit_completion": {
        "fn": tool_get_habit_completion,
        "schema": {
            "name": "get_habit_completion",
            "description": GET_HABIT_COMPLETION_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {"include_registry": {"type": "boolean", "description": "Also return the full tracked-habit registry."}},
                "required": [],
            },
        },
    },
    "get_platform_cost": {
        "fn": tool_get_platform_cost,
        "schema": {
            "name": "get_platform_cost",
            "description": GET_PLATFORM_COST_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "skip_inference": {"type": "boolean", "description": "Return only the budget envelope, skip the AI receipt."}
                },
                "required": [],
            },
        },
    },
    "get_platform_state": {
        "fn": tool_get_platform_state,
        "schema": {
            "name": "get_platform_state",
            "description": GET_PLATFORM_STATE_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": (
                            "Which joined source to return: board, delivery, grades, jury_out, bets, incidents, quality, cost "
                            "or autonomy — or 'all' (the default) for every section. Not an enum on purpose: the set is "
                            "validated against the artifact's own keys at call time and echoed back as sections_available, so "
                            "a section the generator adds is selectable the day it ships."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
}


# Phase 4.9 (2026-05-16): list_available_tools — meta-tool implementation.
# #3668: the body moved to the cohesive sibling mcp/tools_meta.py (every other tool
# implementation already lives in a tools_* module; this table is the dispatch table).
# TOOLS is passed in rather than imported there, so there is no import cycle.
def tool_list_available_tools(args=None):
    """List MCP tools by domain or keyword — see mcp/tools_meta.list_registered_tools."""
    return list_registered_tools(TOOLS, args)


# Rebind the placeholder string in the TOOLS dict to the real function now
# that it's defined. The string was a marker for test_r2_all_fn_references_exist
# (which looks for tool_* names as fn-refs); rebinding here makes the dispatcher
# resolve to the callable at runtime.
cast("dict[str, Any]", TOOLS["list_available_tools"])["fn"] = tool_list_available_tools
