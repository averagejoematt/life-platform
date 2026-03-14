"""
Tool registry: maps tool names to their functions and JSON schemas.
"""
from mcp.config import SOURCES, RAW_DAY_LIMIT, P40_GROUPS
from mcp.tools_data import *
from mcp.tools_strength import *
from mcp.tools_training import *
from mcp.tools_health import *
from mcp.tools_sleep import *
from mcp.tools_nutrition import *
from mcp.tools_correlation import *
from mcp.tools_habits import *
from mcp.tools_labs import *
from mcp.tools_cgm import *
from mcp.tools_journal import *
from mcp.tools_lifestyle import *
from mcp.tools_board import *
from mcp.tools_character import *
from mcp.tools_social import *
from mcp.tools_adaptive import *
from mcp.tools_todoist import *
from mcp.tools_memory import *
from mcp.tools_decisions import *
from mcp.tools_hypotheses import *
from mcp.tools_sick_days import *

TOOLS = {
    "get_sources": {
        "fn": tool_get_sources,
        "schema": {
            "name": "get_sources",
            "description": "List all available data sources and their date ranges in the life platform.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_daily_snapshot": {
        "fn": tool_get_daily_snapshot,
        "schema": {
            "name": "get_daily_snapshot",
            "description": (
                "Unified daily data access. "
                "'summary' (default) = all available data across every source for a specific date. Best for 'how was my day/yesterday?' questions. Requires date=. "
                "'latest' = most recent record for each source — useful for current status checks. "
                "Use for: 'how was yesterday?', 'what\'s my latest data?', 'show me today\'s readings', 'all data for 2026-03-10'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "'summary' (default) for a specific date, 'latest' for most recent per source.",
                        "enum": ["summary", "latest"],
                    },
                    "date":    {"type": "string", "description": "[summary] Date YYYY-MM-DD (required for summary view)."},
                    "sources": {"type": "array", "items": {"type": "string"},
                                "description": f"[latest] List of sources to fetch. Defaults to all. Valid: {SOURCES}"},
                },
                "required": [],
            },
        },
    },
    "get_date_range": {
        "fn": tool_get_date_range,
        "schema": {
            "name": "get_date_range",
            "description": f"Get time-series records for a single source. Returns raw daily data for windows up to {RAW_DAY_LIMIT} days, monthly aggregates beyond that. Use get_aggregated_summary for multi-year trends.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (inclusive)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (inclusive)."},
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
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                    "filters": {
                        "type": "array",
                        "description": "List of field filter conditions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "op":    {"type": "string", "enum": [">", ">=", "<", "<=", "="]},
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
    "get_longitudinal_summary": {
        "fn": tool_get_longitudinal_summary,
        "schema": {
            "name": "get_longitudinal_summary",
            "description": (
                "Unified long-horizon data intelligence. Use 'view' to select the analysis: "
                "'aggregate' (default) = monthly or yearly averages across any date range. For 'how has my weight trended over the years?', 'summarize my health history'. Supports source=, period=month|year. "
                "'seasonal' = month-by-month averages aggregated across ALL years, revealing annual cycles. For 'do I always gain weight in winter?', 'when is my HRV historically highest?'. "
                "'records' = all-time personal records across every measurable dimension. For 'what are my PRs?', 'when was I fittest?', 'have I ever run further than X miles?'. "
                "Use for: 'summarize my history', 'seasonal patterns', 'all-time bests', 'yearly trends', 'my PRs', 'when should I plan my peak event?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "Which analysis: aggregate (default), seasonal, records.",
                        "enum": ["aggregate", "seasonal", "records"],
                    },
                    "source":     {"type": "string", "description": f"[aggregate/seasonal] Optional source filter. Valid: {SOURCES}"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "period":     {"type": "string", "enum": ["month", "year"],
                                   "description": "[aggregate] Use 'year' for multi-year history, 'month' for 1-3 year windows."},
                },
                "required": [],
            },
        },
    },
    "get_field_stats": {
        "fn": tool_get_field_stats,
        "schema": {
            "name": "get_field_stats",
            "description": "Get rich stats for a numeric field: min/max/avg/count, dates of the all-time peak and trough, top-5 highest and top-5 lowest readings with dates, and a trend direction. Use this to find actual historical peaks rather than guessing AND to build a narrative arc. Examples: 'what was my heaviest weight ever?' (source=withings, field=weight_lbs), 'best HRV day' (source=whoop, field=hrv), 'lowest resting heart rate' (source=whoop, field=resting_heart_rate). Always prefer this over get_aggregated_summary when the user asks about a specific extreme value or record. For full narrative context, follow up with get_aggregated_summary (period=year) to show the trend between the peaks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source":     {"type": "string", "description": f"Data source. Valid: {SOURCES}"},
                    "field":      {"type": "string", "description": "The numeric field name to analyze. E.g. 'weight_lbs', 'hrv', 'recovery_score', 'resting_heart_rate', 'total_distance_miles'."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01 (all-time)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["source", "field"],
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
                    "start_date":              {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2010-01-01."},
                    "end_date":                {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "name_contains":           {"type": "string", "description": "Keyword to search in activity name (case-insensitive). E.g. 'machu', 'half marathon', 'trail'."},
                    "sport_type":              {"type": "string", "description": "Filter by sport type (case-insensitive). Common values: 'Run', 'Walk', 'Hike', 'Ride', 'VirtualRide', 'WeightTraining'."},
                    "min_distance_miles":      {"type": "number", "description": "Only return activities with distance >= this value in miles."},
                    "min_elevation_gain_feet": {"type": "number", "description": "Only return activities with elevation gain >= this value in feet."},
                    "sort_by":                 {"type": "string", "description": "Field to sort results by descending. Options: 'distance_miles', 'total_elevation_gain_feet', 'moving_time_seconds', 'kilojoules'. Default: 'distance_miles'."},
                    "limit":                   {"type": "number", "description": "Max results to return. Default 100."},
                },
                "required": [],
            },
        },
    },
    "compare_periods": {
        "fn": tool_compare_periods,
        "schema": {
            "name": "compare_periods",
            "description": "Side-by-side comparison of two date ranges across one or all sources. Returns per-field averages for both periods plus delta and % change. Use for benchmarking questions: 'how does my fitness now compare to my 2022 peak?', 'was I more active this year vs last year?', 'did my HRV improve after I started running more?'. Label your periods meaningfully (e.g. 'Peak 2022', 'Current').",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "period_a_start": {"type": "string", "description": "Start date of period A (YYYY-MM-DD)."},
                    "period_a_end":   {"type": "string", "description": "End date of period A (YYYY-MM-DD)."},
                    "period_b_start": {"type": "string", "description": "Start date of period B (YYYY-MM-DD)."},
                    "period_b_end":   {"type": "string", "description": "End date of period B (YYYY-MM-DD)."},
                    "period_a_label": {"type": "string", "description": "Human-readable label for period A. E.g. 'Peak 2022', 'Pre-injury', 'Last year'."},
                    "period_b_label": {"type": "string", "description": "Human-readable label for period B. E.g. 'Current', 'Post-injury', 'This year'."},
                    "source":         {"type": "string", "description": f"Optional. Limit to one source. Valid: {SOURCES}. Omit to compare all sources."},
                },
                "required": ["period_a_start", "period_a_end", "period_b_start", "period_b_end"],
            },
        },
    },
    "get_weekly_summary": {
        "fn": tool_get_weekly_summary,
        "schema": {
            "name": "get_weekly_summary",
            "description": "Group Strava activities into ISO calendar weeks and return per-week totals (distance, elevation, time, activity count, sport type breakdown). Use for training load questions: 'what was my biggest training week ever?', 'show my weekly mileage this year', 'what were my top 10 highest mileage weeks?'. Sort by distance (default), elevation, or time. Chronological order available via sort_ascending=true for trend analysis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":     {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2000-01-01 (all-time)."},
                    "end_date":       {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "sort_by":        {"type": "string", "description": "Field to sort weeks by. Options: 'total_distance_miles' (default), 'total_elevation_gain_feet', 'total_moving_time_seconds', 'activity_count'."},
                    "limit":          {"type": "number", "description": "Max weeks to return. Default 52."},
                    "sort_ascending": {"type": "boolean", "description": "Set true for chronological order (trend view). Default false (best weeks first)."},
                },
                "required": [],
            },
        },
    },
    "get_training_load": {
        "fn": tool_get_training_load,
        "schema": {
            "name": "get_training_load",
            "description": "Compute the Banister fitness-fatigue model: CTL (42-day fitness), ATL (7-day fatigue), TSB (form = CTL-ATL), and ACWR (injury risk ratio). Use for: 'how fit am I right now?', 'am I overtraining?', 'am I ready for a race?', 'when was my peak fitness?', 'what is my injury risk?'. ACWR > 1.3 = caution, > 1.5 = danger. TSB positive = fresh, negative = fatigued. Returns a full time series plus current state summary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 6 months ago."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_cross_source_correlation": {
        "fn": tool_get_cross_source_correlation,
        "schema": {
            "name": "get_cross_source_correlation",
            "description": "Pearson correlation between any two numeric metrics, with optional day lag. The coaching superpower — reveals hidden relationships in your data. Examples: 'does HRV predict next-day training output?' (source_a=whoop, field_a=hrv, source_b=strava, field_b=total_distance_miles, lag_days=1), 'does work stress suppress recovery?' (source_a=todoist, field_a=tasks_completed, source_b=whoop, field_b=recovery_score), 'does weight track with training volume?' (source_a=withings, field_a=weight_lbs, source_b=strava, field_b=total_distance_miles). r > 0.4 is practically meaningful.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_a":   {"type": "string", "description": f"First data source. Valid: {SOURCES}"},
                    "field_a":    {"type": "string", "description": "Field from source_a (e.g. 'hrv', 'recovery_score', 'weight_lbs')"},
                    "source_b":   {"type": "string", "description": f"Second data source. Valid: {SOURCES}"},
                    "field_b":    {"type": "string", "description": "Field from source_b (e.g. 'total_distance_miles', 'recovery_score')"},
                    "lag_days":   {"type": "number", "description": "Shift source_b forward N days. Use lag=1 to ask 'does A today predict B tomorrow?'. Default 0."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2019-01-01."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["source_a", "field_a", "source_b", "field_b"],
            },
        },
    },
    "get_health": {
        "fn": tool_get_health,
        "schema": {
            "name": "get_health",
            "description": (
                "Unified health intelligence. Use 'view' to select the analysis: "
                "'dashboard' (default) = current-state morning briefing: readiness (recovery, HRV, RHR, sleep), training load (CTL/ATL/TSB/ACWR), 7d/30d summaries, biomarker trends, alerts. "
                "'risk_profile' = health risk synthesis: cardiovascular, metabolic, longevity. Combines 7 lab draws, 110 genome SNPs, DEXA, wearable HRV. Supports domain= filter. Warmed nightly. "
                "'trajectory' = forward-looking projections: weight goal date, biomarker trend slopes, Zone 2 trend, HRV trend, glucose trend, Board of Directors longevity assessment. Supports domain= filter. Warmed nightly. "
                "Use for: 'how am I doing?', 'morning check-in', 'health briefing', 'am I overtrained?', "
                "'health risk profile', 'CV risk', 'metabolic health', 'longevity assessment', "
                "'where am I headed?', 'health trajectory', 'projected goal date', 'am I on track?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "dashboard (default), risk_profile, or trajectory.",
                        "enum": ["dashboard", "risk_profile", "trajectory"],
                    },
                    "domain": {"type": "string",
                               "description": "[risk_profile] 'cardiovascular', 'metabolic', 'longevity'. Omit for all. [trajectory] 'all', 'weight', 'biomarkers', 'fitness', 'recovery', 'metabolic'."},
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
                    "start_date": {"type": "string", "description": "Override start date YYYY-MM-DD. Defaults to journey_start_date from profile."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_body_composition_trend": {
        "fn": tool_get_body_composition_trend,
        "schema": {
            "name": "get_body_composition_trend",
            "description": "Tracks fat mass vs lean/muscle mass over time from Withings data — the question the scale alone cannot answer: are you losing fat or muscle? Returns fat mass, lean mass, body fat %, FFMI series, and flags significant lean mass loss events. Use for: 'am I losing fat or muscle?', 'how is my body composition changing?', 'am I protecting my lean mass?', 'what is my body fat percentage trend?'. Requires Withings body composition sync.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to journey_start_date from profile."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_energy_expenditure": {
        "fn": tool_get_energy_expenditure,
        "schema": {
            "name": "get_energy_expenditure",
            "description": "Estimates Total Daily Energy Expenditure (TDEE) = BMR + exercise calories. BMR computed via Mifflin-St Jeor (most validated for people with obesity). Exercise calories from Strava kilojoules or TRIMP estimate. Returns implied daily calorie target at a given deficit, and shows how BMR has changed since start weight (metabolic adaptation). Use for: 'how many calories should I eat?', 'what is my TDEE?', 'how much am I burning?', 'how has my metabolism changed as I lose weight?'. Requires height_inches, date_of_birth, biological_sex in profile.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_deficit_kcal": {"type": "number", "description": "Daily calorie deficit target. Default 500 (≈1 lb/week). Use 750 for 1.5 lbs/week, 1000 for 2 lbs/week."},
                    "end_date":            {"type": "string",  "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": [],
            },
        },
    },
    "get_exercise_history": {
        "fn": tool_get_exercise_history,
        "schema": {
            "name": "get_exercise_history",
            "description": "Deep dive on a single exercise: all sessions, per-set detail, PR chronology, and estimated 1RM trend. Use for: 'show me all my bench press sessions', 'when did I hit a bench PR?', 'how has my squat progressed?'. Fuzzy matches exercise name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "exercise_name":   {"type": "string", "description": "Exercise name to search (case-insensitive, fuzzy match). E.g. 'bench press', 'squat', 'deadlift'."},
                    "start_date":      {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to 2000-01-01."},
                    "end_date":        {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "include_warmups": {"type": "boolean", "description": "Include warmup sets. Default false."},
                },
                "required": ["exercise_name"],
            },
        },
    },
    "get_strength_prs": {
        "fn": tool_get_strength_prs,
        "schema": {
            "name": "get_strength_prs",
            "description": "All-exercise PR leaderboard ranked by estimated 1RM (Epley formula). Shows best weight, best reps, and estimated 1-rep max for every exercise with sufficient data. Use for: 'what are my strength PRs?', 'what's my best bench press?', 'show me my top lifts by muscle group'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":           {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":             {"type": "string", "description": "End date YYYY-MM-DD."},
                    "muscle_group_filter":  {"type": "string", "description": "Optional filter by muscle group. E.g. 'chest', 'back', 'legs'."},
                    "min_sessions":         {"type": "number", "description": "Minimum sessions required for exercise to appear. Default 3."},
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
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                    "period":     {"type": "string", "description": "Aggregation period: 'week' (default) or 'month'."},
                },
                "required": [],
            },
        },
    },
    "get_strength_progress": {
        "fn": tool_get_strength_progress,
        "schema": {
            "name": "get_strength_progress",
            "description": "Longitudinal 1RM trend, rate of gain, and plateau detection for a single exercise. Splits history into thirds for periodization analysis. Use for: 'am I still getting stronger at bench?', 'how fast is my squat progressing?', 'am I in a plateau?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "exercise_name":          {"type": "string", "description": "Exercise name (fuzzy match)."},
                    "start_date":             {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":               {"type": "string", "description": "End date YYYY-MM-DD."},
                    "plateau_threshold_days": {"type": "number", "description": "Days without PR to flag plateau. Default 90."},
                },
                "required": ["exercise_name"],
            },
        },
    },
    "get_workout_frequency": {
        "fn": tool_get_workout_frequency,
        "schema": {
            "name": "get_workout_frequency",
            "description": "Adherence metrics: total workouts, avg per week/month, longest streak, longest gap, month-by-month breakdown, and top 15 most-trained exercises. Use for: 'how consistent am I?', 'what is my workout streak?', 'how many days per week do I train?', 'what exercises do I do most?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD."},
                },
                "required": [],
            },
        },
    },
    "get_strength_standards": {
        "fn": tool_get_strength_standards,
        "schema": {
            "name": "get_strength_standards",
            "description": "Bodyweight-relative strength vs Untrained/Novice/Intermediate/Advanced/Elite norms for bench press, squat, deadlift, and overhead press. Uses current bodyweight from Withings. Use for: 'how strong am I?', 'what level is my bench press?', 'how far am I from an advanced deadlift?', 'what are my strength standards?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "end_date":           {"type": "string", "description": "Only use data up to this date. Defaults to today."},
                    "bodyweight_source":  {"type": "string", "description": "'withings' (default) or 'profile'."},
                    "bodyweight_lbs":     {"type": "number", "description": "Override bodyweight in lbs if no Withings data."},
                },
                "required": [],
            },
        },
    },
    "get_sleep_analysis": {
        "fn": tool_get_sleep_analysis,
        "schema": {
            "name": "get_sleep_analysis",
            "description": (
                "Clinical sleep analysis from Eight Sleep data. Goes beyond raw hours to surface the metrics a "
                "sleep physician uses: sleep architecture percentages (REM/deep/light as % of TST with clinical "
                "norms), sleep efficiency (sleep/TIB ×100, target ≥85%, CBT-I flag <80%), WASO (true "
                "wake-after-sleep-onset), circadian timing (avg onset/wake/midpoint in local time), sleep "
                "regularity (SD of onset and wake hours), social jetlag (weekday vs weekend midpoint delta, "
                "threshold 1h), sleep debt (rolling 7d and 30d vs target), and respiratory rate screening. "
                "All alerts reference evidence-based clinical thresholds. "
                "Use for: 'how is my sleep quality?', 'do I have enough REM?', 'is my sleep consistent?', "
                "'what is my sleep efficiency?', 'do I have social jetlag?', 'how much sleep debt do I have?', "
                "'is my respiratory rate normal?'. Requires Eight Sleep data in life-platform."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":          {"type": "string", "description": "Start date YYYY-MM-DD. Overrides 'days' if provided."},
                    "end_date":            {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                    "days":                {"type": "number", "description": "Rolling window in days from end_date (default: 90). Ignored if start_date provided."},
                    "target_sleep_hours":  {"type": "number", "description": "Nightly sleep target for debt calculation (default: 7.5h)."},
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
                    "start_date":     {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":       {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "days":           {"type": "number", "description": "[macros] Rolling window in days (default: 30). Ignored if start_date provided."},
                    "calorie_target": {"type": "number", "description": "[macros] Override daily calorie target (kcal). Defaults to TDEE estimate."},
                    "protein_target": {"type": "number", "description": "[macros] Override daily protein target (g). Default: 180g."},
                },
                "required": [],
            },
        },
    },
    "get_food_log": {
        "fn": tool_get_food_log,
        "schema": {
            "name": "get_food_log",
            "description": (
                "Return individual food entries logged on a specific date, with per-item macros and daily totals. "
                "Use for: 'what did I eat yesterday?', 'show me my food diary for Monday', "
                "'what was in my food log on Feb 21?'. Requires MacroFactor data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: yesterday)."},
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
                "and training polarization alerts (Zone 3 'no man\'s land' warning per Seiler). "
                "Zone 2 (60-70% max HR) is the highest-evidence longevity training modality — builds mitochondrial "
                "density, fat oxidation capacity, and cardiovascular base. "
                "Use for: 'how much Zone 2 am I doing?', 'am I hitting my Zone 2 target?', "
                "'show my training zone distribution', 'weekly Zone 2 minutes', 'zone 2 trend', "
                "'am I doing enough easy cardio?', 'training polarization check'. Requires Strava data with HR."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":             {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":               {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "weekly_target_minutes":   {"type": "integer", "description": "Weekly Zone 2 target in minutes (default: 150, per Attia/WHO guidelines)."},
                    "min_duration_minutes":    {"type": "integer", "description": "Minimum activity duration in minutes to include (default: 10)."},
                },
                "required": [],
            },
        },
    },
    # ── Habits / P40 tools ────────────────────────────────────────────────────
    "get_habits": {
        "fn": tool_get_habits,
        "schema": {
            "name": "get_habits",
            "description": (
                "Unified P40 habit intelligence. Use the 'view' parameter to select the analysis: "
                "'dashboard' (default) = current-state briefing: latest day, 7d rolling vs 30d baseline, best/worst groups, top streaks, alerts. "
                "'adherence' = per-habit and per-group completion rates ranked worst-to-best. Supports group= filter. "
                "'streaks' = current streak, longest streak, days since last completion per habit. Supports habit_name= filter. "
                "'tiers' = Tier 0 perfect-day rate, T1 adherence, vice adherence, most-missed T0 habits, synergy groups. "
                "'stacks' = co-occurrence analysis: which habits cluster together (lift metric), natural morning routines. "
                "'keystones' = Pearson correlation of each habit vs overall P40 score — the behavioral levers. "
                "Use for: 'how are my habits?', 'P40 check-in', 'habit adherence this month', 'active streaks', "
                "'are my non-negotiables consistent?', 'which habits do I always do together?', 'keystone habits', "
                "'which P40 group is weakest?', 'habit tier report', 'natural routines'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "Which analysis to run. One of: dashboard (default), adherence, streaks, tiers, stacks, keystones.",
                        "enum": ["dashboard", "adherence", "streaks", "tiers", "stacks", "keystones"],
                    },
                    "start_date":      {"type": "string",  "description": "Start date YYYY-MM-DD."},
                    "end_date":        {"type": "string",  "description": "End date YYYY-MM-DD (default: today)."},
                    "group":           {"type": "string",  "description": f"[adherence] Filter by P40 group. Valid: {P40_GROUPS}"},
                    "habit_name":      {"type": "string",  "description": "[streaks] Optional habit name filter (fuzzy match)."},
                    "top_n":           {"type": "number",  "description": "[keystones/stacks] Number of top results to return (default: 15/20)."},
                    "min_pct":         {"type": "number",  "description": "[stacks] Minimum base rate to include a habit (default: 0.1)."},
                },
                "required": [],
            },
        },
    },
    # compare_habit_periods retained as standalone — requires 4 required params, not suited to view= dispatch
    "compare_habit_periods": {
        "fn": tool_compare_habit_periods,
        "schema": {
            "name": "compare_habit_periods",
            "description": (
                "Side-by-side P40 adherence comparison of two date ranges. Returns per-habit and per-group delta. "
                "Use for: 'how did my habits change after I started running more?', "
                "'compare this month to last month', 'was I more consistent pre-injury vs now?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "period_a_start": {"type": "string", "description": "Start of period A (YYYY-MM-DD)."},
                    "period_a_end":   {"type": "string", "description": "End of period A (YYYY-MM-DD)."},
                    "period_b_start": {"type": "string", "description": "Start of period B (YYYY-MM-DD)."},
                    "period_b_end":   {"type": "string", "description": "End of period B (YYYY-MM-DD)."},
                    "period_a_label": {"type": "string", "description": "Label for period A (e.g. 'Last month')."},
                    "period_b_label": {"type": "string", "description": "Label for period B (e.g. 'This month')."},
                },
                "required": ["period_a_start", "period_a_end", "period_b_start", "period_b_end"],
            },
        },
    },
    "get_readiness_score": {
        "fn": tool_get_readiness_score,
        "schema": {
            "name": "get_readiness_score",
            "description": (
                "Unified readiness score (0-100) synthesising Whoop recovery (35%), Eight Sleep score (25%), "
                "HRV 7-day trend vs 30-day baseline (20%), TSB training form (10%), and "
                "Garmin Body Battery (10%) into a single GREEN / YELLOW / RED signal with a 1-line "
                "actionable recommendation. Also includes a device_agreement section showing Whoop vs "
                "Garmin HRV/RHR delta as a confidence signal — flag status means lower score reliability. "
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
                    "text":   {"type": "string",  "description": "The insight text to save. Be specific and actionable."},
                    "tags":   {"type": "array",   "items": {"type": "string"},
                               "description": "Optional list of tags (e.g. ['sleep', 'hrv', 'caffeine'])."},
                    "source": {"type": "string",  "description": "Origin of the insight: 'chat' (default) or 'email'."},
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
                    "status_filter": {"type": "string",
                                      "description": "Filter by status: 'open', 'acted', or 'resolved'. Omit for all."},
                    "limit":         {"type": "integer", "description": "Max results to return (default: 50)."},
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
                    "insight_id":    {"type": "string", "description": "The insight_id returned by save_insight (e.g. 2026-02-22T09:15:00)."},
                    "outcome_notes": {"type": "string", "description": "What happened — did it work? What did you learn?"},
                    "status":        {"type": "string", "description": "New status: 'acted' (tried it) or 'resolved' (fully closed). Default: 'acted'."},
                },
                "required": ["insight_id"],
            },
        },
    },
    "get_lab_results": {
        "fn": tool_get_lab_results,
        "schema": {
            "name": "get_lab_results",
            "description": (
                "Get blood work results. Without a date, returns summary of all 7 draws (2019-2025). "
                "With a date, returns full biomarkers with genome cross-reference annotations. "
                "Filter by category: lipids, cbc, metabolic, thyroid, liver, kidney, etc. "
                "Use for: 'show my latest blood work', 'lipids in 2024', 'all lab draws'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "draw_date": {"type": "string", "description": "Draw date YYYY-MM-DD. Omit to list all."},
                    "category":  {"type": "string", "description": "Filter: lipids, cbc, metabolic, thyroid, liver, kidney, electrolytes, minerals, diabetes, hormones, etc."},
                },
                "required": [],
            },
        },
    },
    "get_lab_trends": {
        "fn": tool_get_lab_trends,
        "schema": {
            "name": "get_lab_trends",
            "description": (
                "Track biomarker trajectory across all 7 draws (2019-2025). Slope per year, 1-year projection, "
                "derived ratios (TG/HDL, non-HDL, TC/HDL). Genome flags for genetic drivers. "
                "Use for: 'LDL trend', 'cholesterol trajectory', 'is glucose rising', 'TG/HDL ratio over time'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "biomarker":  {"type": "string", "description": "Single key: 'ldl_c', 'hba1c', 'glucose'. Use search_biomarker to find names."},
                    "biomarkers": {"type": "array", "items": {"type": "string"}, "description": "Multiple keys."},
                    "include_derived_ratios": {"type": "boolean", "description": "Include TG/HDL, non-HDL, TC/HDL. Default true."},
                },
                "required": [],
            },
        },
    },
    "get_out_of_range_history": {
        "fn": tool_get_out_of_range_history,
        "schema": {
            "name": "get_out_of_range_history",
            "description": (
                "All out-of-range biomarkers across draws with persistence (chronic/recurring/occasional) "
                "and genome-driven explanations. Use for: 'flagged biomarkers', 'persistent issues', 'genetic vs lifestyle flags'."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "search_biomarker": {
        "fn": tool_search_biomarker,
        "schema": {
            "name": "search_biomarker",
            "description": (
                "Free-text biomarker search across all draws. Values over time + trend. "
                "Use when you don't know the exact key. 'find cholesterol', 'search thyroid', 'iron markers'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term: 'cholesterol', 'thyroid', 'liver', 'iron'."},
                },
                "required": ["query"],
            },
        },
    },
    "get_genome_insights": {
        "fn": tool_get_genome_insights,
        "schema": {
            "name": "get_genome_insights",
            "description": (
                "Query 110 genome SNPs by category/risk/gene. Cross-reference with labs or nutrition. "
                "Categories: metabolism, cardiovascular, nutrients, methylation, inflammation, longevity, etc. "
                "Risks: unfavorable, mixed, neutral, favorable. "
                "Use for: 'genome metabolism', 'unfavorable SNPs', 'FTO variants', 'genome + labs cross-ref'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category":        {"type": "string", "description": "SNP category filter."},
                    "risk_level":      {"type": "string", "description": "unfavorable, mixed, neutral, favorable."},
                    "gene":            {"type": "string", "description": "Gene name: FTO, MTHFR, ABCG8."},
                    "cross_reference": {"type": "string", "description": "'labs' or 'nutrition' for cross-ref data."},
                },
                "required": [],
            },
        },
    },
    "get_movement_score": {
        "fn": tool_get_movement_score,
        "schema": {
            "name": "get_movement_score",
            "description": (
                "Daily movement & NEAT analysis. NEAT = energy burned outside exercise (larger than workouts "
                "for most people). Movement score 0-100, step target tracking, sedentary day flags. "
                "Use for: 'am I moving enough?', 'NEAT analysis', 'sedentary days', 'step trend', "
                "'non-exercise activity'. Requires Apple Health webhook. Strava enhances NEAT calc."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date":  {"type": "string", "description": "Start YYYY-MM-DD (default: 30d ago)."},
                "end_date":    {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                "step_target": {"type": "integer", "description": "Daily step target (default: 8000)."},
            }, "required": []},
        },
    },
    "get_cgm_dashboard": {
        "fn": tool_get_cgm_dashboard,
        "schema": {
            "name": "get_cgm_dashboard",
            "description": (
                "CGM blood glucose dashboard. Time in range (target >90%), variability (SD target <20), "
                "mean glucose (target <100), time above 140, fasting proxy. Clinical flags, trend analysis. "
                "Glucose management is a top-3 longevity lever (Attia, Huberman). "
                "Use for: 'glucose overview', 'CGM dashboard', 'blood sugar', 'time in range', "
                "'metabolic health', 'am I pre-diabetic?'. Requires Apple Health CGM webhook."
            ),
            "inputSchema": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30d ago)."},
                "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
            }, "required": []},
        },
    },
    "get_glucose_meal_response": {
        "fn": tool_get_glucose_meal_response,
        "schema": {
            "name": "get_glucose_meal_response",
            "description": (
                "Levels-style postprandial glucose response analysis. For each meal logged in MacroFactor, "
                "matches 5-minute CGM readings to compute: pre-meal baseline, peak glucose, spike magnitude, "
                "time-to-peak, AUC, and a letter grade (A-F). Aggregates best/worst meals, per-food scores "
                "across days, and macro correlations (carbs/fiber/protein/sugar vs spike). "
                "Based on Attia, Huberman, Lustig: spikes >30 mg/dL drive insulin resistance and inflammation. "
                "Use for: 'which foods spike my glucose?', 'meal glucose response', 'food scoring', "
                "'postprandial analysis', 'best and worst meals for blood sugar', 'does fiber help my glucose?'. "
                "Requires MacroFactor food log + CGM data (Dexcom Stelo via Apple Health webhook)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":        {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":          {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "meal_gap_minutes":  {"type": "integer", "description": "Minutes gap to consider separate meals (default: 30)."},
                },
                "required": [],
            },
        },
    },
    "get_fasting_glucose_validation": {
        "fn": tool_get_fasting_glucose_validation,
        "schema": {
            "name": "get_fasting_glucose_validation",
            "description": "Validate CGM fasting glucose accuracy against venous lab draws. Computes proper overnight nadir (midnight-6AM) from raw CGM readings, builds distribution, and compares against 6 historical blood draws. Two modes: direct same-day validation when overlap exists, and statistical validation (z-scores, percentiles) when not. Shows bias analysis, confidence level, and Board of Directors interpretation. Use for: 'how accurate is my CGM fasting glucose?', 'validate CGM against labs', 'compare overnight nadir to blood work', 'is my fasting proxy trustworthy?'",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "nadir_start_hour": {"type": "number", "description": "Start of overnight window (decimal hours). Default 0 (midnight)."},
                    "nadir_end_hour": {"type": "number", "description": "End of overnight window (decimal hours). Default 6 (6 AM)."},
                    "deep_nadir_start_hour": {"type": "number", "description": "Start of deep nadir window. Default 2 (2 AM). Avoids late digestion."},
                    "deep_nadir_end_hour": {"type": "number", "description": "End of deep nadir window. Default 5 (5 AM). Avoids dawn phenomenon."},
                    "min_overnight_readings": {"type": "number", "description": "Minimum CGM readings in overnight window. Default 6 (~30 min coverage)."},
                },
                "required": [],
            },
        },
    },
    # ── Journal tools (v2.16.0) ────────────────────────────────────────────────
    "get_journal_entries": {
        "fn": tool_get_journal_entries,
        "schema": {
            "name": "get_journal_entries",
            "description": (
                "Retrieve journal entries for a date range with optional template filter. "
                "Returns structured fields + Haiku-enriched signals (mood, energy, stress, "
                "themes, emotions, cognitive patterns, values, etc). "
                "Use for: 'show my journal from last week', 'what did I write this morning?', "
                "'evening entries from January', 'my weekly reflections'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 7 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "template":   {"type": "string", "description": "Filter by template: morning, evening, stressor, health_event, weekly. Optional."},
                    "include_enriched": {"type": "boolean", "description": "Include Haiku-enriched fields (default: true)."},
                },
                "required": [],
            },
        },
    },
    "search_journal": {
        "fn": tool_search_journal,
        "schema": {
            "name": "search_journal",
            "description": (
                "Full-text search across all journal entries — searches raw text, themes, "
                "emotions, avoidance flags, pain mentions, quotes, and all enriched fields. "
                "Use for: 'when did I mention back pain?', 'find entries about work stress', "
                "'search for entries where I felt lonely', 'find journal mentions of alcohol'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query":      {"type": "string", "description": "Search keywords (all must match)."},
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: all time)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                },
                "required": ["query"],
            },
        },
    },
    "get_mood_trend": {
        "fn": tool_get_mood_trend,
        "schema": {
            "name": "get_mood_trend",
            "description": (
                "Mood, energy, and stress scores over time with 7-day rolling averages, "
                "trend direction, and recurring themes at peaks/valleys. Combines structured "
                "Notion scores with Haiku-enriched signals for the most accurate longitudinal view. "
                "Use for: 'how has my mood been this month?', 'stress trend over 30 days', "
                "'am I getting better?', 'energy trend', 'mood and stress together'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
                    "metric":     {"type": "string", "description": "mood, energy, stress, or all (default: all)."},
                },
                "required": [],
            },
        },
    },
    "get_journal_insights": {
        "fn": tool_get_journal_insights,
        "schema": {
            "name": "get_journal_insights",
            "description": (
                "Cross-entry pattern analysis — the 'so what?' tool. Surfaces recurring themes, "
                "dominant emotions, cognitive pattern frequency (CBT: catastrophizing, rumination, "
                "reframing, growth mindset), avoidance flags, ownership trend (locus of control), "
                "values alignment, social connection quality, flow state frequency, and gratitude patterns. "
                "Based on Seligman (PERMA), Beck (CBT), Ferriss (fear-setting), Jocko (ownership), "
                "Huberman (stress), Csikszentmihalyi (flow). "
                "Use for: 'what patterns do you see in my journal?', 'what am I consistently avoiding?', "
                "'how is my ownership trending?', 'cognitive pattern analysis', 'journal insights'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default: today)."},
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
                    "name":       {"type": "string", "description": "Short name of the intervention (e.g. 'Creatine 5g daily', 'No screens after 9pm')."},
                    "hypothesis": {"type": "string", "description": "What you expect to happen (e.g. 'Will improve deep sleep % by >5%')."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD. Defaults to today."},
                    "tags":       {"type": "array", "items": {"type": "string"},
                                   "description": "Optional tags (e.g. ['sleep', 'supplement', 'caffeine'])."},
                    "notes":      {"type": "string", "description": "Additional context or protocol details."},
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
                    "outcome":       {"type": "string", "description": "What happened — did it work? What did you learn?"},
                    "status":        {"type": "string", "description": "'completed' (default) or 'abandoned'."},
                    "end_date":      {"type": "string", "description": "End date YYYY-MM-DD. Defaults to today."},
                },
                "required": ["experiment_id"],
            },
        },
    },

    "get_hr_recovery_trend": {
        "fn": tool_get_hr_recovery_trend,
        "schema": {
            "name": "get_hr_recovery_trend",
            "description": (
                "Heart rate recovery tracker — the strongest exercise-derived mortality predictor (Cole et al., NEJM). "
                "Extracts post-peak HR recovery from Strava activity streams, trends over time, classifies against "
                "clinical thresholds (>25 excellent, 18-25 good, 12-18 average, <12 abnormal). Shows sport-type "
                "breakdown, cooldown vs no-cooldown comparison, best/worst sessions, and fitness trajectory. "
                "Board of Directors provides longevity assessment. "
                "Use for: 'HR recovery trend', 'heart rate recovery', 'am I getting fitter?', "
                "'cardiovascular fitness trajectory', 'autonomic function', 'post-exercise HR drop'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 180 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "sport_type": {"type": "string", "description": "Filter by sport type (e.g. 'Run', 'Ride'). Case-insensitive."},
                    "cooldown_only": {"type": "boolean", "description": "Only include activities with detected cooldown. Default: false."},
                },
                "required": [],
            },
        },
    },
    "log_supplement": {
        "fn": tool_log_supplement,
        "schema": {
            "name": "log_supplement",
            "description": (
                "Log a supplement or medication. Writes to the supplements partition in DynamoDB. "
                "Supports name, dose, unit, timing (morning, with_meal, before_bed, post_workout), "
                "category (supplement, medication, vitamin, mineral), and notes. Multiple entries per day. "
                "Use for: 'log 500mg magnesium before bed', 'track my creatine', 'I took vitamin D this morning', "
                "'log my medication', 'supplement log entry'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Supplement or medication name (required)."},
                    "dose": {"type": "number", "description": "Dosage amount (e.g. 500 for 500mg)."},
                    "unit": {"type": "string", "description": "Unit: mg, mcg, g, IU, ml, capsule, tablet."},
                    "timing": {"type": "string", "description": "When taken: morning, with_meal, before_bed, post_workout, evening, afternoon."},
                    "category": {"type": "string", "description": "Category: supplement, medication, vitamin, mineral. Default: supplement."},
                    "notes": {"type": "string", "description": "Optional notes."},
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                },
                "required": ["name"],
            },
        },
    },
    "get_supplement_log": {
        "fn": tool_get_supplement_log,
        "schema": {
            "name": "get_supplement_log",
            "description": (
                "Retrieve supplement/medication log. Shows what was taken, dosage, timing, adherence patterns, "
                "and per-supplement summary with adherence percentage. Filter by supplement name. "
                "Use for: 'show my supplement log', 'what supplements am I taking?', 'supplement adherence', "
                "'am I consistent with creatine?', 'medication history'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "name": {"type": "string", "description": "Filter by supplement name (partial match, case-insensitive)."},
                },
                "required": [],
            },
        },
    },
    "get_training_periodization": {
        "fn": tool_get_training_periodization,
        "schema": {
            "name": "get_training_periodization",
            "description": (
                "Training periodization planner. Analyzes weekly training patterns to detect mesocycle phases "
                "(base/build/peak/deload), deload needs (Galpin 3:1 or 4:1 ratio), progressive overload "
                "tracking (strength volume trends), training polarization (Seiler 80/20 model), Zone 2 "
                "target adherence (Attia 150 min/week), and training consistency. "
                "Use for: 'do I need a deload?', 'training periodization', 'am I overtraining?', "
                "'progressive overload trend', 'training polarization check', 'weekly training summary', "
                "'mesocycle analysis', 'should I take a rest week?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 12 weeks ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "weeks": {"type": "integer", "description": "Number of weeks to analyze (default: 12). Ignored if start_date provided."},
                },
                "required": [],
            },
        },
    },
    "get_training_recommendation": {
        "fn": tool_get_training_recommendation,
        "schema": {
            "name": "get_training_recommendation",
            "description": (
                "Readiness-based training recommendation. Synthesizes Whoop recovery, Eight Sleep quality, "
                "Garmin Body Battery, training load (CTL/ATL/TSB), recent activity history, and muscle group "
                "recency into a specific workout suggestion: type (Zone 2, intervals, strength upper/lower, "
                "active recovery, rest), intensity, duration, HR targets, and muscle groups to target. "
                "Board of Directors provides rationale. Warns about injury risk (ACWR), consecutive training days, "
                "and sleep debt. Use for: 'what should I do today?', 'workout recommendation', 'should I train today?', "
                "'am I recovered enough for a hard workout?', 'readiness-based training', 'what workout today?'."
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
    "log_travel": {
        "fn": tool_log_travel,
        "schema": {
            "name": "log_travel",
            "description": (
                "Log a trip start or end. Tracks destination, timezone offset, and travel direction. "
                "On trip start: computes timezone difference, provides Huberman jet lag protocol "
                "(light exposure, meal timing, melatonin window, exercise). On trip end: closes the active trip. "
                "Travel records are used by anomaly detector (suppresses false positives during travel) "
                "and daily brief (travel mode banner). "
                "Use for: 'I'm traveling to London', 'log a trip to Tokyo', 'I'm back home', 'end my trip'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "'start' (default) or 'end'."},
                    "destination_city": {"type": "string", "description": "City name (required for start)."},
                    "destination_country": {"type": "string", "description": "Country name."},
                    "destination_timezone": {"type": "string", "description": "IANA timezone (e.g. 'Europe/London', 'Asia/Tokyo'). Enables jet lag protocol."},
                    "start_date": {"type": "string", "description": "Trip start YYYY-MM-DD (default: today)."},
                    "end_date": {"type": "string", "description": "Trip end YYYY-MM-DD (for action='end', default: today)."},
                    "purpose": {"type": "string", "description": "personal, work, family, vacation."},
                    "trip_id": {"type": "string", "description": "Trip ID to end (for action='end'). If omitted, ends most recent active trip."},
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": [],
            },
        },
    },
    "get_travel_log": {
        "fn": tool_get_travel_log,
        "schema": {
            "name": "get_travel_log",
            "description": (
                "List all trips with status, timezone offsets, and duration. Shows currently active trip if any. "
                "Filter by status (active/completed). "
                "Use for: 'show my trips', 'am I traveling?', 'travel history', 'list completed trips'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter: 'active', 'completed'. Omit for all."},
                },
                "required": [],
            },
        },
    },
    "get_jet_lag_recovery": {
        "fn": tool_get_jet_lag_recovery,
        "schema": {
            "name": "get_jet_lag_recovery",
            "description": (
                "Post-trip recovery analysis. Compares 7-day pre-trip baseline to post-return recovery curve "
                "across 8 metrics (HRV, recovery, sleep, stress, Body Battery, steps). Shows days-to-baseline "
                "for each metric, overall recovery summary, and Board coaching. "
                "Huberman: ~1 day recovery per timezone crossed, eastbound harder. "
                "Use for: 'how did I recover from my trip?', 'jet lag recovery', 'post-travel analysis', "
                "'did travel affect my sleep?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string", "description": "Trip ID from get_travel_log. Omit for most recent completed trip."},
                    "recovery_window_days": {"type": "integer", "description": "Days after return to analyze (default: 14)."},
                },
                "required": [],
            },
        },
    },
    "get_blood_pressure_dashboard": {
        "fn": tool_get_blood_pressure_dashboard,
        "schema": {
            "name": "get_blood_pressure_dashboard",
            "description": (
                "Blood pressure dashboard. Current status, AHA classification (normal/elevated/stage1/stage2/crisis), "
                "30-day trend, morning vs evening patterns from individual readings, variability analysis (SD). "
                "SD >12 mmHg systolic is an independent cardiovascular risk factor. "
                "Use for: 'blood pressure status', 'BP trend', 'am I hypertensive?', "
                "'morning vs evening BP', 'blood pressure variability'. "
                "Requires BP cuff syncing to Apple Health."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    # ── Habit Registry tools (v2.47.0) ──────────────────────────────────────────
    "get_habit_registry": {
        "fn": tool_get_habit_registry,
        "schema": {
            "name": "get_habit_registry",
            "description": (
                "Inspect the 65-habit registry with full metadata: tier (0=non-negotiable, 1=high priority, "
                "2=aspirational), category, science rationale, why_matthew personal context, synergy_group, "
                "scoring_weight, applicable_days, evidence_strength, friction_level, and graduation_criteria. "
                "Filter by tier, category, vice_only, or synergy_group. "
                "Use for: 'show my habit registry', 'what are my Tier 0 habits?', 'which habits are vices?', "
                "'what synergy groups exist?', 'why do I track cold showers?', 'habits in the sleep category'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tier": {"type": "number", "description": "Filter by tier: 0, 1, or 2."},
                    "category": {"type": "string", "description": "Filter by category (e.g. 'sleep', 'nutrition', 'recovery', 'mindset')."},
                    "vice_only": {"type": "boolean", "description": "If true, only show vice habits (default: false)."},
                    "synergy_group": {"type": "string", "description": "Filter by synergy group (e.g. 'morning_stack', 'recovery_stack')."},
                },
                "required": [],
            },
        },
    },
    "get_vice_streak_history": {
        "fn": tool_get_vice_streak_history,
        "schema": {
            "name": "get_vice_streak_history",
            "description": (
                "Vice streak trends over time. Shows each vice's streak trajectory, longest historical streaks, "
                "relapse dates and context, and trend direction. Identity-based habit tracking. "
                "Use for: 'show my vice streaks over time', 'No Alcohol streak history', "
                "'when did I last relapse on late-night screens?', 'vice trend analysis', "
                "'which vices am I strongest at?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "vice_name": {"type": "string", "description": "Filter by vice name (partial match, case-insensitive)."},
                },
                "required": [],
            },
        },
    },
    "get_state_of_mind_trend": {
        "fn": tool_get_state_of_mind_trend,
        "schema": {
            "name": "get_state_of_mind_trend",
            "description": (
                "State of Mind valence trend from How We Feel / Apple Health. Tracks mood check-ins "
                "(momentary emotions + daily moods) with valence (-1 to +1), emotion labels (Happy, Stressed, "
                "Calm, Anxious, etc.), and life area associations (Work, Family, Health, Fitness, Money, etc.). "
                "Shows overall valence trend, 7-day rolling average, time-of-day patterns, best/worst days, "
                "top emotion labels, valence by life area (which domains drive best/worst mood), and "
                "valence classification distribution. Huberman: mood is circadian — cortisol, dopamine, serotonin "
                "fluctuate throughout day. Walker: evening mood valence predicts sleep onset latency. "
                "Seligman: momentary mood sampling is clinically validated experience sampling method (ESM). "
                "Use for: 'how has my mood been?', 'state of mind trend', 'valence trend', 'mood check-ins', "
                "'what makes me feel best?', 'mood by time of day', 'How We Feel data', "
                "'emotional patterns', 'which life areas affect my mood?'. "
                "Requires How We Feel (or Apple State of Mind) + Health Auto Export State of Mind automation."
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
    # ── Board of Directors Management ──
    "get_board_of_directors": {
        "fn": tool_get_board_of_directors,
        "schema": {
            "name": "get_board_of_directors",
            "description": (
                "View the Board of Directors expert panel. Returns all members with their personas, "
                "domains, voice profiles, and feature assignments. Filter by member_id for one member, "
                "or by type (fictional_advisor/real_expert/narrator/meta_role), feature (weekly_digest/"
                "monthly_digest/daily_brief/nutrition_review/chronicle), or active_only. "
                "Use for: 'show the board', 'who are my experts?', 'which experts cover sleep?', "
                "'show Elena Voss profile', 'board members for chronicle'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "member_id": {"type": "string", "description": "Specific member ID (e.g. 'sarah_chen', 'elena_voss'). Omit for all."},
                    "type": {"type": "string", "description": "Filter by type: fictional_advisor, real_expert, narrator, meta_role."},
                    "feature": {"type": "string", "description": "Filter by feature: weekly_digest, monthly_digest, daily_brief, nutrition_review, chronicle."},
                    "active_only": {"type": "boolean", "description": "Only show active members. Default: true."},
                },
                "required": [],
            },
        },
    },
    # ── Character Sheet tools (v2.58.0) ──
    "get_character_sheet": {
        "fn": tool_get_character_sheet,
        "schema": {
            "name": "get_character_sheet",
            "description": (
                "Get the current character sheet — overall Character Level (1-100), all 7 pillar levels "
                "and tiers, active cross-pillar effects, XP totals, and recent level events. "
                "Includes 14-day sparklines per pillar. "
                "Use for: 'show my character sheet', 'what level am I', 'how am I doing overall', "
                "'character status', 'my game stats'."
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
    "get_pillar_detail": {
        "fn": tool_get_pillar_detail,
        "schema": {
            "name": "get_pillar_detail",
            "description": (
                "Deep dive into a single pillar: component breakdown with individual scores, "
                "daily raw_scores over time, level history, XP curve, and contributing metrics. "
                "Valid pillars: sleep, movement, nutrition, metabolic, mind, relationships, consistency. "
                "Use for: 'how is my sleep pillar', 'break down my nutrition score', "
                "'movement pillar detail', 'why is my mind score low'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pillar": {"type": "string", "description": "Pillar name: sleep, movement, nutrition, metabolic, mind, relationships, consistency."},
                    "days": {"type": "integer", "description": "Days of history to analyze (default: 30, max: 180)."},
                    "date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": ["pillar"],
            },
        },
    },
    "get_level_history": {
        "fn": tool_get_level_history,
        "schema": {
            "name": "get_level_history",
            "description": (
                "Timeline of all level and tier change events across all pillars or a specific one. "
                "Shows level ups, level downs, tier transitions, and milestone achievements. "
                "Use for: 'show my level history', 'when did I level up', 'tier transitions', "
                "'character progress timeline', 'have I hit any milestones'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days of history (default: 90, max: 365)."},
                    "pillar": {"type": "string", "description": "Optional: filter to specific pillar."},
                    "date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                },
                "required": [],
            },
        },
    },
    # ── Character Sheet Phase 4 tools (v2.71.0) ──
    "set_reward": {
        "fn": tool_set_reward,
        "schema": {
            "name": "set_reward",
            "description": (
                "Create or update a user-defined reward milestone tied to Character Sheet progress. "
                "Rewards trigger automatically when their condition is met during daily character sheet computation. "
                "Examples: 'When Sleep hits Mastery \u2192 buy new pillow', 'When Character Level reaches 60 \u2192 dinner at Canlis'. "
                "Use for: 'set a reward', 'create a milestone', 'when I reach level X do Y', "
                "'reward myself for hitting Mastery in movement'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short reward title (e.g., 'Dinner at Canlis', 'Buy new running shoes')."},
                    "condition_type": {"type": "string", "description": "Trigger type: pillar_tier, pillar_level, character_level, character_tier."},
                    "pillar": {"type": "string", "description": "Pillar name (required for pillar_tier/pillar_level): sleep, movement, nutrition, metabolic, mind, relationships, consistency."},
                    "tier": {"type": "string", "description": "Target tier (for pillar_tier/character_tier): Foundation, Momentum, Discipline, Mastery, Elite."},
                    "level": {"type": "integer", "description": "Target level 1-100 (for pillar_level/character_level)."},
                    "description": {"type": "string", "description": "Optional notes about the reward."},
                    "reward_id": {"type": "string", "description": "Optional: specify ID to update existing reward."},
                },
                "required": ["title", "condition_type"],
            },
        },
    },
    "get_rewards": {
        "fn": tool_get_rewards,
        "schema": {
            "name": "get_rewards",
            "description": (
                "View all user-defined reward milestones with their status (active, triggered, claimed). "
                "Shows reward title, condition, and trigger status. "
                "Use for: 'show my rewards', 'what rewards have I earned', 'list milestones', "
                "'check reward status', 'any rewards triggered'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status: active, triggered, claimed. Leave empty for all."},
                },
                "required": [],
            },
        },
    },
    "update_character_config": {
        "fn": tool_update_character_config,
        "schema": {
            "name": "update_character_config",
            "description": (
                "View or update the Character Sheet configuration (pillar weights, component targets, leveling parameters). "
                "Changes are written to S3 and take effect on next character sheet computation. "
                "Use for: 'show character config', 'change sleep pillar weight', 'adjust protein target', "
                "'update leveling parameters', 'tune character sheet settings'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action: view, update_weight, update_target, update_leveling."},
                    "pillar": {"type": "string", "description": "Pillar name (for update_weight, update_target)."},
                    "weight": {"type": "number", "description": "New weight 0-1 (for update_weight, e.g. 0.20 for 20%)."},
                    "component": {"type": "string", "description": "Component name (for update_target, e.g. 'duration_vs_target')."},
                    "target_field": {"type": "string", "description": "Target field name (for update_target, e.g. 'target_hours')."},
                    "value": {"type": "number", "description": "New value (for update_target, update_leveling)."},
                    "field": {"type": "string", "description": "Leveling field (for update_leveling: ema_lambda, ema_window_days, level_up_streak_days, etc.)."},
                },
                "required": ["action"],
            },
        },
    },
    # ── Life Event Tagging (#40) ──
    "log_life_event": {
        "fn": tool_log_life_event,
        "schema": {
            "name": "log_life_event",
            "description": (
                "Log a structured life event (birthday, anniversary, work milestone, social event, "
                "conflict, loss, health milestone, achievement, setback). Creates narrative architecture "
                "for Chronicle and connects data anomalies to actual life context. "
                "Use for: 'log a life event', 'my mum's birthday is March 15', 'had a conflict at work', "
                "'record that I hit a weight milestone', 'mark Tom's visit'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title of the event."},
                    "type": {"type": "string", "description": "Event type: birthday, anniversary, work_milestone, social, conflict, loss, health_milestone, travel, relationship, financial, achievement, setback, other."},
                    "date": {"type": "string", "description": "Event date YYYY-MM-DD (default: today)."},
                    "description": {"type": "string", "description": "Optional longer description."},
                    "people": {"type": "array", "items": {"type": "string"}, "description": "People involved (names)."},
                    "emotional_weight": {"type": "integer", "description": "1-5 emotional significance (5 = life-altering)."},
                    "recurring": {"type": "string", "description": "If recurring: 'annual', 'monthly', etc."},
                },
                "required": ["title"],
            },
        },
    },
    "get_life_events": {
        "fn": tool_get_life_events,
        "schema": {
            "name": "get_life_events",
            "description": (
                "Retrieve life events with optional filters by type, person, or date range. "
                "Returns events, type breakdown, and people mentioned. "
                "Use for: 'show my life events', 'what events happened in March', "
                "'events involving Tom', 'all losses this year', 'upcoming birthdays'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 1 year ago)."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "type": {"type": "string", "description": "Filter by event type."},
                    "person": {"type": "string", "description": "Filter by person name."},
                },
                "required": [],
            },
        },
    },
    # ── Contact Frequency Tracking (#42) ──
    "log_interaction": {
        "fn": tool_log_interaction,
        "schema": {
            "name": "log_interaction",
            "description": (
                "Log a meaningful social interaction with a specific person. Tracks contact frequency, "
                "depth (surface/meaningful/deep), and channel diversity for Pillar 7 (Relationships). "
                "Murthy: 3-5 close relationships is the threshold for wellbeing. "
                "Use for: 'I called Tom today', 'had coffee with Sarah', 'texted Brittany', "
                "'log a deep conversation with my therapist', 'had lunch with a coworker'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "person": {"type": "string", "description": "Name of the person."},
                    "type": {"type": "string", "description": "Interaction type: call, text, in_person, video, email, social_media, other."},
                    "depth": {"type": "string", "description": "Depth level: surface, meaningful, deep. Default: meaningful."},
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                    "duration_min": {"type": "integer", "description": "Duration in minutes (optional)."},
                    "notes": {"type": "string", "description": "Optional notes about the interaction."},
                    "initiated_by": {"type": "string", "description": "Who initiated: 'me' or 'them' (optional)."},
                },
                "required": ["person"],
            },
        },
    },
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
    "log_temptation": {
        "fn": tool_log_temptation,
        "schema": {
            "name": "log_temptation",
            "description": (
                "Log a temptation moment — whether resisted or succumbed. Captures the exact point "
                "where the knowing-doing gap lives. Categories: food, alcohol, sleep_sabotage, "
                "skip_workout, screen_time, social_avoidance, impulse_purchase, other. "
                "Rodriguez: this is the only metric that measures willpower directly. "
                "Use for: 'I resisted junk food', 'I gave in to late night snacking', "
                "'tempted to skip workout but went anyway', 'stayed up too late scrolling'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Category: food, alcohol, sleep_sabotage, skip_workout, screen_time, social_avoidance, impulse_purchase, other."},
                    "resisted": {"type": "boolean", "description": "true if resisted, false if succumbed."},
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)."},
                    "trigger": {"type": "string", "description": "What triggered the temptation (e.g. 'stress', 'boredom', 'social pressure')."},
                    "intensity": {"type": "integer", "description": "1-5 intensity of the urge."},
                    "time_of_day": {"type": "string", "description": "When it happened: morning, afternoon, evening, night."},
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["category", "resisted"],
            },
        },
    },
    "get_temptation_trend": {
        "fn": tool_get_temptation_trend,
        "schema": {
            "name": "get_temptation_trend",
            "description": (
                "Temptation trend analysis: overall resist rate, category breakdown, trigger patterns, "
                "intensity analysis (do you succumb more to intense urges?), weekly trends. "
                "A leading indicator of behavioral change that no wearable can capture. "
                "Use for: 'how's my willpower', 'temptation trend', 'resist rate', "
                "'what tempts me most', 'am I getting better at resisting', 'behavioral change progress'."
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
    "get_adaptive_mode": {
        "fn": get_adaptive_mode,
        "schema": {
            "name": "get_adaptive_mode",
            "description": (
                "Retrieve adaptive brief mode history and current engagement score. "
                "Shows whether today's brief is in 'flourishing', 'standard', or 'struggling' mode, "
                "plus the 4-factor engagement score (journal completion, T0/T1 habit adherence, grade trend). "
                "Flourishing (≥70): brief is celebratory, BoD is reinforcing. "
                "Struggling (<40): brief shifts to warm coaching, gentle BoD, recovery focus. "
                "Use for: 'what mode is my brief in', 'am I flourishing or struggling', "
                "'engagement score history', 'brief mode trend', 'adaptive email mode'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days of mode history to return (default 14, max 30)."},
                },
                "required": [],
            },
        },
    },
    # get_defense_patterns removed — function never implemented (v3.7.0)
    # ── Lactate Threshold Estimation (#27) ──
    "get_lactate_threshold_estimate": {
        "fn": tool_get_lactate_threshold_estimate,
        "schema": {
            "name": "get_lactate_threshold_estimate",
            "description": (
                "Estimates aerobic threshold development using cardiac efficiency analysis of Zone 2 sessions. "
                "Tracks pace-per-HR (cardiac drift proxy) across steady-state efforts over time. "
                "As aerobic base builds, HR drops for same effort (or pace improves at same HR). "
                "Linear regression reveals direction and rate of change. Weekly trend summary. "
                "Chen: proxy lactate curve from HR drift over repeated efforts without a blood draw. "
                "Use for: 'am I building aerobic base?', 'lactate threshold estimate', 'cardiac drift', "
                "'Zone 2 efficiency trend', 'aerobic base progress', 'is my Zone 2 improving?'"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":       {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":         {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "zone2_hr_low":     {"type": "number", "description": "Lower HR bound for Zone 2 sessions (default: 110)."},
                    "zone2_hr_high":    {"type": "number", "description": "Upper HR bound for Zone 2 sessions (default: 139)."},
                    "min_duration_min": {"type": "number", "description": "Minimum session duration in minutes (default: 20)."},
                    "sport_type":       {"type": "string", "description": "Filter by sport type e.g. 'run', 'ride' (default: all)."},
                },
                "required": [],
            },
        },
    },
    # ── Exercise Efficiency Trending (#39) ──
    "get_exercise_efficiency_trend": {
        "fn": tool_get_exercise_efficiency_trend,
        "schema": {
            "name": "get_exercise_efficiency_trend",
            "description": (
                "Tracks pace-at-HR (cardiac efficiency) over time for repeated workout types. "
                "Same workout + lower HR over time = improving cardiovascular fitness. "
                "Groups by sport type, computes efficiency metric, detects trend via linear regression. "
                "Shows which sports are improving, stable, or declining. "
                "Attia: pace-at-HR over time is the purest fitness signal available from consumer data. "
                "Use for: 'am I getting fitter?', 'exercise efficiency trend', 'pace at heart rate', "
                "'cardiovascular fitness progress', 'running efficiency', 'cycling fitness', "
                "'is my heart rate dropping for same effort?', 'fitness signal'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date":       {"type": "string", "description": "Start date YYYY-MM-DD (default: 90 days ago)."},
                    "end_date":         {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "sport_type":       {"type": "string", "description": "Filter by sport type e.g. 'run', 'ride' (default: all)."},
                    "min_hr":           {"type": "number", "description": "Minimum avg HR to include (default: 100)."},
                    "min_duration_min": {"type": "number", "description": "Minimum duration in minutes (default: 10)."},
                },
                "required": [],
            },
        },
    },
    # ── Hydration Tracking Enhancement (#30) ──
    "get_hydration_score": {
        "fn": tool_get_hydration_score,
        "schema": {
            "name": "get_hydration_score",
            "description": (
                "Hydration adequacy scoring with bodyweight-adjusted daily target (35ml/kg per Webb). "
                "Shows daily water intake vs target, adequacy rate, deficit days, current streak, "
                "and correlation with exercise intensity. Source: Apple Health water_intake_ml. "
                "Webb: hydration adequacy is correlated with energy, headaches, and exercise performance. "
                "Use for: 'am I drinking enough water?', 'hydration score', 'water intake trend', "
                "'hydration target', 'deficit days', 'water and exercise', 'daily water', 'hydration adequacy'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default: 30 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default: today)."},
                    "target_ml":  {"type": "number", "description": "Override daily target in ml (default: 35ml/kg bodyweight)."},
                },
                "required": [],
            },
        },
    },
    # ── Todoist Integration ──
    "get_task_completion_trend": {
        "fn": get_task_completion_trend,
        "schema": {
            "name": "get_task_completion_trend",
            "description": (
                "Task completion trend over the last N days with 7-day rolling average and summary stats. "
                "Shows daily completed count, zero-completion days, current streak, and peak day. "
                "Use for: 'how productive have I been in Todoist?', 'task completion trend', "
                "'how many tasks am I completing per day?', 'productivity streak', 'Todoist stats'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to analyze (default: 30, max: 90)."},
                },
                "required": [],
            },
        },
    },
    "get_task_load_summary": {
        "fn": get_task_load_summary,
        "schema": {
            "name": "get_task_load_summary",
            "description": (
                "Current task load snapshot: active count, overdue count, due-today count, priority breakdown. "
                "Includes cognitive load signal (LOW/MODERATE/ELEVATED/HIGH) based on overdue backlog. "
                "The decision fatigue indicator — high active + high overdue = cognitive overhead that suppresses habits. "
                "Use for: 'how many tasks do I have?', 'task load', 'overdue tasks', 'due today', "
                "'how overwhelmed am I?', 'decision fatigue', 'task backlog', 'Todoist load'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days of recent completion history to include (default: 7)."},
                },
                "required": [],
            },
        },
    },
    "get_project_activity": {
        "fn": get_project_activity,
        "schema": {
            "name": "get_project_activity",
            "description": (
                "Completion breakdown by Todoist project over the last N days. "
                "Shows which life domains (Health, Finance, Growth, Relationships, Home) are getting attention "
                "and which are being neglected. Includes percentage of total and average per day. "
                "Use for: 'which projects am I completing tasks in?', 'project activity', 'life domain attention', "
                "'which areas am I neglecting?', 'Todoist project breakdown', 'where am I spending effort?'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to analyze (default: 30, max: 90)."},
                },
                "required": [],
            },
        },
    },
    "get_decision_fatigue_signal": {
        "fn": get_decision_fatigue_signal,
        "schema": {
            "name": "get_decision_fatigue_signal",
            "description": (
                "Correlates Todoist task load (active + overdue) with Habitify T0 habit completion rate. "
                "Identifies the overdue-task threshold above which habit compliance drops — the knowing-doing gap made quantifiable. "
                "Returns Pearson r correlation, load threshold analysis, and daily breakdown. "
                "Roadmap item #34. Requires both Todoist and Habitify data in the same date range. "
                "Use for: 'does task overload hurt my habits?', 'decision fatigue', 'knowing-doing gap', "
                "'does having too many tasks affect my habits?', 'task load vs habit completion'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days to analyze (default: 30, min: 14, max: 60)."},
                },
                "required": [],
            },
        },
    },
    "get_todoist_day": {
        "fn": get_todoist_day,
        "schema": {
            "name": "get_todoist_day",
            "description": (
                "Full Todoist snapshot for a specific date (default: yesterday). "
                "Returns completed tasks list with project names, overdue/active/due-today counts, "
                "priority breakdown, and completions by project. "
                "Use for: 'what tasks did I complete yesterday?', 'Todoist day summary', "
                "'what was my task load on [date]?', 'show me my completed tasks'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD (default: yesterday)."},
                },
                "required": [],
            },
        },
    },
    # ── Todoist write tools ──
    "get_todoist_projects": {
        "fn": get_todoist_projects,
        "schema": {
            "name": "get_todoist_projects",
            "description": "List all Todoist projects with IDs and names. Call this first before creating or moving tasks to get valid project_id values.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "list_todoist_tasks": {
        "fn": list_todoist_tasks,
        "schema": {
            "name": "list_todoist_tasks",
            "description": (
                "List active Todoist tasks with IDs, due dates, and recurrence strings. "
                "Supports Todoist filter syntax: 'overdue', 'today', 'no date', 'p1', '#Health & Body'. "
                "Use before updating tasks to get task IDs and inspect current due/recurrence settings."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "filter_str": {"type": "string", "description": "Todoist filter string e.g. 'overdue', '#Health & Body', 'no date'."},
                    "limit": {"type": "integer", "description": "Max tasks to return (default: 200)."},
                },
                "required": [],
            },
        },
    },
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
                    "task_id":     {"type": "string", "description": "Task ID from list_todoist_tasks."},
                    "due_string":  {"type": "string", "description": "Recurrence e.g. 'every! week', 'every! month'. Use every! not every."},
                    "due_date":    {"type": "string", "description": "First-fire date YYYY-MM-DD."},
                    "content":     {"type": "string", "description": "New task name."},
                    "description": {"type": "string", "description": "Task description/notes."},
                    "priority":    {"type": "integer", "description": "1=urgent 2=high 3=medium 4=normal."},
                    "project_id":  {"type": "string", "description": "Move to project ID."},
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
                    "content":     {"type": "string", "description": "Task name."},
                    "project_id":  {"type": "string", "description": "Project ID from get_todoist_projects."},
                    "due_string":  {"type": "string", "description": "e.g. 'every! Sunday', 'every! month'. Use every! for recurring."},
                    "due_date":    {"type": "string", "description": "YYYY-MM-DD for one-time or first-fire date."},
                    "priority":    {"type": "integer", "description": "1=urgent 2=high 3=medium 4=normal."},
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
    "delete_todoist_task": {
        "fn": delete_todoist_task,
        "schema": {
            "name": "delete_todoist_task",
            "description": "Permanently delete a Todoist task. Cannot be undone. Use only for duplicates or stale tasks, not for completing.",
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
                    "category": {"type": "string", "description": "Memory category (e.g. 'failure_pattern', 'what_worked', 'journey_milestone')."},
                    "content":  {"type": "object", "description": "Key-value dict of data to store. E.g. {\"pattern\": \"high-stress Tuesdays correlate with missed nutrition\", \"conditions\": [...]}"},
                    "date":     {"type": "string", "description": "Date for the record (YYYY-MM-DD). Defaults to today."},
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
                    "days":     {"type": "integer", "description": "How many days back to look (default 30, max 365)."},
                    "limit":    {"type": "integer", "description": "Max records to return (default 10, max 50)."},
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
                    "date":     {"type": "string", "description": "Date of the record to delete (YYYY-MM-DD)."},
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
                    "decision":        {"type": "string", "description": "What the platform recommended (e.g. 'Take a rest day', 'Front-load protein')."},
                    "followed":        {"type": "boolean", "description": "True if Matthew followed the advice, False if overridden. Omit if not yet decided."},
                    "override_reason": {"type": "string", "description": "Why Matthew chose differently (if overridden). Optional."},
                    "source":          {"type": "string", "description": "Which digest/email made the recommendation. Default: daily_brief.",
                                        "enum": ["daily_brief", "weekly_digest", "monthly_digest", "nutrition_review", "chronicle", "mcp"]},
                    "pillars":         {"type": "array", "items": {"type": "string"},
                                        "description": "Pillars this decision touches (e.g. ['sleep', 'movement'])."},
                    "date":            {"type": "string", "description": "Date of the decision (YYYY-MM-DD). Defaults to today."},
                },
                "required": ["decision"],
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
                    "days":         {"type": "integer", "description": "Look back N days (default 30)."},
                    "pillar":       {"type": "string", "description": "Filter by pillar (e.g. 'sleep', 'nutrition')."},
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
                    "sk":             {"type": "string", "description": "Sort key of the decision to update (from get_decisions)."},
                    "outcome_metric": {"type": "string", "description": "Which metric was affected (e.g. 'HRV', 'sleep_score', 'protein_g')."},
                    "outcome_delta":  {"type": "number", "description": "Change in the metric (positive = improved, negative = worsened)."},
                    "outcome_notes":  {"type": "string", "description": "Free-text notes on what happened."},
                    "effectiveness":  {"type": "integer", "description": "1-5 rating: 1=bad outcome, 3=neutral, 5=great outcome."},
                },
                "required": ["sk"],
            },
        },
    },
    # ── IC-18: Cross-Domain Hypothesis Engine ───────────────────────────────────────────
    "get_hypotheses": {
        "fn": tool_get_hypotheses,
        "schema": {
            "name": "get_hypotheses",
            "description": (
                "IC-18: List cross-domain health hypotheses generated by the weekly Hypothesis Engine. "
                "Shows non-obvious correlations between pillars being monitored for confirmation or refutation. "
                "Lifecycle: pending -> confirming -> confirmed (incorporated into AI coaching) or refuted. "
                "IMPORTANT: Active hypotheses are unconfirmed — they require 3 confirming observations before promotion. "
                "Treat pending/confirming hypotheses as working theories only, not established patterns. "
                "Use for: 'what hypotheses is the platform watching?', 'confirmed patterns', "
                "'what cross-domain correlations have been found?', 'scientific method on my data'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status":           {"type": "string",
                                         "description": "Filter by lifecycle status.",
                                         "enum": ["pending", "confirming", "confirmed", "refuted", "archived"]},
                    "domain":           {"type": "string",
                                         "description": "Filter by domain (e.g. 'sleep', 'nutrition', 'movement', 'mind', 'metabolic')."},
                    "days":             {"type": "integer", "description": "How many days back to search (default 90)."},
                    "include_archived": {"type": "boolean", "description": "Include archived hypotheses (default false)."},
                },
                "required": [],
            },
        },
    },
    "update_hypothesis_outcome": {
        "fn": tool_update_hypothesis_outcome,
        "schema": {
            "name": "update_hypothesis_outcome",
            "description": (
                "IC-18: Record a confirming or refuting observation for a pending hypothesis. "
                "After 3 confirming checks the hypothesis is promoted to 'confirmed' and flows into AI coaching. "
                "Use when you notice evidence in your data or experience that bears on a pending hypothesis. "
                "Use for: 'carb-sleep pattern held again tonight', 'stress-HRV connection wasn’t there this week'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sk":            {"type": "string",
                                      "description": "Sort key from get_hypotheses (starts with 'HYPOTHESIS#')."},
                    "verdict":       {"type": "string",
                                      "description": "Your assessment of the evidence.",
                                      "enum": ["confirming", "confirmed", "refuted", "insufficient", "archived"]},
                    "evidence_note": {"type": "string",
                                      "description": "What you observed (free text)."},
                    "effectiveness": {"type": "integer",
                                      "description": "Optional 1-5 strength of evidence (5=very strong confirmation)."},
                },
                "required": ["sk", "verdict"],
            },
        },
    },

    "log_sick_day": {
        "fn": tool_log_sick_day,
        "schema": {
            "name": "log_sick_day",
            "description": (
                "Flag one or more dates as sick or rest days. When flagged: Character Sheet EMA frozen, "
                "day grade = 'sick', habit/streak timers preserved (not broken), anomaly alerts suppressed, "
                "freshness alerts skipped, Daily Brief shows recovery banner."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date":   {"type": "string", "description": "Single date YYYY-MM-DD."},
                    "dates":  {"type": "array", "items": {"type": "string"},
                               "description": "Multiple dates YYYY-MM-DD."},
                    "reason": {"type": "string", "description": "Optional reason (flu, injury, etc)."},
                },
                "required": [],
            },
        },
    },
    "get_sick_days": {
        "fn": tool_get_sick_days,
        "schema": {
            "name": "get_sick_days",
            "description": "List sick/rest days within a date range. Shows date, reason, when logged.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start YYYY-MM-DD (default 90d ago)."},
                    "end_date":   {"type": "string", "description": "End YYYY-MM-DD (default today)."},
                },
                "required": [],
            },
        },
    },
    "clear_sick_day": {
        "fn": tool_clear_sick_day,
        "schema": {
            "name": "clear_sick_day",
            "description": "Remove a sick day flag (use if logged in error).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date to un-flag YYYY-MM-DD."},
                },
                "required": ["date"],
            },
        },
    },
}
