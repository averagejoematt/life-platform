"""
Shared configuration: environment variables, AWS clients, constants.
"""
__version__ = "2.74.0"
import os
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Environment variables (with backwards-compatible defaults) ──
_REGION         = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME      = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET       = os.environ.get("S3_BUCKET", "matthew-life-platform")
USER_ID         = os.environ.get("USER_ID", "matthew")
API_SECRET_NAME = os.environ.get("API_SECRET_NAME", "life-platform/mcp-api-key")

# ── AWS clients ──
dynamodb  = boto3.resource("dynamodb", region_name=_REGION)
table     = dynamodb.Table(TABLE_NAME)
secrets   = boto3.client("secretsmanager", region_name=_REGION)
s3_client = boto3.client("s3", region_name=_REGION)

# ── Derived constants ──
USER_PREFIX     = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK      = f"USER#{USER_ID}"
PROFILE_SK      = "PROFILE#v1"
RAW_DAY_LIMIT   = 90
CACHE_PK        = f"CACHE#{USER_ID}"
CACHE_TTL_SECS  = 26 * 3600  # 26 hours
MEM_CACHE_TTL   = 600  # 10 minutes

# Fields stripped in lean queries
_LEAN_STRIP = {"activities", "sport_types", "pk", "sk", "ingested_at", "source"}

SOURCES = ["whoop", "withings", "strava", "todoist", "apple_health", "hevy", "eightsleep", "chronicling", "macrofactor", "garmin", "habitify", "notion", "labs", "dexa", "genome", "weather", "supplements", "state_of_mind", "habit_scores"]

# ── Source-of-truth domain ownership ──
_DEFAULT_SOURCE_OF_TRUTH = {
    "cardio":      "strava",
    "strength":    "hevy",
    "physiology":  "whoop",
    "nutrition":   "macrofactor",
    "sleep":       "whoop",
    "sleep_environment": "eightsleep",
    "journal":     "notion",
    "body":        "withings",
    "steps":       "apple_health",
    "tasks":       "todoist",
    "habits":      "habitify",
    "stress":      "garmin",
    "body_battery":"garmin",
    "gait":        "apple_health",
    "energy_expenditure": "apple_health",
    "cgm":         "apple_health",
    "water":        "apple_health",
    "caffeine":     "apple_health",
    "supplements":  "supplements",
    "weather":      "weather",
    "state_of_mind": "state_of_mind",
}

P40_GROUPS = ["Data", "Discipline", "Growth", "Hygiene", "Nutrition", "Performance", "Recovery", "Supplements", "Wellbeing"]

FIELD_ALIASES = {
    "strava": {
        "distance_miles":        "total_distance_miles",
        "elevation_gain_feet":   "total_elevation_gain_feet",
        "elevation_gain":        "total_elevation_gain_feet",
        "distance":              "total_distance_miles",
    }
}

# Partition keys for sub-features
INSIGHTS_PK     = f"USER#{USER_ID}#SOURCE#insights"
EXPERIMENTS_PK  = f"USER#{USER_ID}#SOURCE#experiments"
TRAVEL_PK       = f"USER#{USER_ID}#SOURCE#travel"
RUCK_PK         = f"USER#{USER_ID}#SOURCE#ruck_log"
LIFE_EVENTS_PK  = f"USER#{USER_ID}#SOURCE#life_events"
INTERACTIONS_PK = f"USER#{USER_ID}#SOURCE#interactions"
TEMPTATIONS_PK  = f"USER#{USER_ID}#SOURCE#temptations"
EXPOSURES_PK    = f"USER#{USER_ID}#SOURCE#exposures"
FOOD_RESPONSES_PK = f"USER#{USER_ID}#SOURCE#food_responses"
