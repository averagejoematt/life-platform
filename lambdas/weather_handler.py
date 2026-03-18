"""
weather_handler.py — SIMP-2: Weather ingestion via shared ingestion framework.

Replaces weather_lambda.py (143 lines) with ~70 lines of source-specific logic.
The framework handles: AWS init, DATA-2 validation, schema versioning, S3 archival,
structured logging, Decimal conversion, and the ingest loop.

Source: Open-Meteo archive API (no auth required)
Location: Seattle, WA (47.6062, -122.3321)
Schedule: EventBridge, runs before Daily Brief (same schedule as weather_lambda)

SIMP-2 v1.0.0 — Proof of concept migration (2026-03-09)
"""
import json
import os
import urllib.request
from ingestion_framework import IngestionConfig, run_ingestion

try:
    from platform_logger import get_logger
    logger = get_logger("weather-ingestion")
except ImportError:
    import logging
    logger = logging.getLogger("weather-ingestion")

# ── Seattle coordinates ──
LAT = float(os.environ.get("WEATHER_LAT", "47.6062"))
LON = float(os.environ.get("WEATHER_LON", "-122.3321"))

# ── Framework config ──
config = IngestionConfig(
    source_name="weather",
    secret_id=None,               # No auth needed — Open-Meteo is public
    s3_archive_prefix="raw/weather",
    schema_version=1,
    enable_gap_detection=False,   # Weather runs yesterday+today by default
)

_OPEN_METEO_FIELDS = (
    "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
    "relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max,"
    "surface_pressure_mean,daylight_duration,uv_index_max,sunshine_duration"
)


# ── Source callbacks ──────────────────────────────────────────────────────────

def authenticate(secret_data):
    """No authentication required for Open-Meteo."""
    return {}


def fetch_day(creds, date_str):
    """Fetch a single day from the Open-Meteo archive API."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={LAT}&longitude={LON}"
        f"&start_date={date_str}&end_date={date_str}"
        f"&daily={_OPEN_METEO_FIELDS}"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&precipitation_unit=mm&timezone=America/Los_Angeles"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def transform(raw, date_str):
    """Map Open-Meteo daily response to platform DDB schema."""
    daily = raw.get("daily", {})
    dates = daily.get("time", [])

    if not dates or dates[0] != date_str:
        return []  # No data for this date

    i = 0  # Single-day fetch always index 0
    daylight_secs = daily.get("daylight_duration", [None])[i] or 0
    sunshine_secs = daily.get("sunshine_duration", [None])[i] or 0

    record = {
        "source":             "weather",
        "date":               date_str,
        "temp_high_f":        daily.get("temperature_2m_max",        [None])[i],
        "temp_low_f":         daily.get("temperature_2m_min",        [None])[i],
        "temp_avg_f":         daily.get("temperature_2m_mean",       [None])[i],
        "humidity_pct":       daily.get("relative_humidity_2m_mean", [None])[i],
        "precipitation_mm":   daily.get("precipitation_sum",         [None])[i],
        "wind_speed_max_mph": daily.get("wind_speed_10m_max",        [None])[i],
        "pressure_hpa":       daily.get("surface_pressure_mean",     [None])[i],
        "daylight_hours":     round(daylight_secs / 3600, 2),
        "sunshine_hours":     round(sunshine_secs / 3600, 2),
        "uv_index_max":       daily.get("uv_index_max",              [None])[i],
    }

    # Strip None values (missing fields)
    return [{k: v for k, v in record.items() if v is not None}]


# ── Lambda entry point ────────────────────────────────────────────────────────

def lambda_handler(event, context):
    try:
        """Entry point — delegates entirely to the ingestion framework."""
        return run_ingestion(config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
