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

from ingestion.ingestion_framework import IngestionConfig, run_ingestion

try:
    from common.platform_logger import get_logger

    logger = get_logger("weather-ingestion")
except ImportError:
    import logging

    logger = logging.getLogger("weather-ingestion")

try:
    from common.http_retry import urlopen_with_retry
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    urlopen_with_retry = urllib.request.urlopen

# ── Seattle coordinates ──
LAT = float(os.environ.get("WEATHER_LAT", "47.6062"))
LON = float(os.environ.get("WEATHER_LON", "-122.3321"))

# ── Framework config ──
config = IngestionConfig(
    source_name="weather",
    secret_id=None,  # No auth needed — Open-Meteo is public
    s3_archive_prefix="raw/weather",
    schema_version=1,
    # #470: was enable_gap_detection=False ("runs yesterday+today by default")
    # — a multi-day outage (deploy break, Open-Meteo downtime) never backfilled,
    # it just silently skipped the missed days forever. Gap detection makes a
    # weather-pipe failure self-heal like every other SIMP-2 source once the
    # cron resumes. refresh_today=True preserves the old same-day-refresh
    # behavior (today's aggregates firm up between the two daily runs).
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
    refresh_today=True,
)

_OPEN_METEO_FIELDS = (
    "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
    "relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max,"
    "surface_pressure_mean,daylight_duration,uv_index_max,sunshine_duration,"
    # #2311: the brief's Conditions / Sunrise / Sunset cells had no writer.
    "weather_code,sunrise,sunset"
)

# ── WMO weather interpretation codes → the brief's condition string (#2311) ──
# Open-Meteo's daily `weather_code` is a WMO 4677-derived code. Unknown codes
# map to no condition at all (honest absence, ADR-104) — never a guess.
_WMO_CONDITIONS: dict[int, str] = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}


# ── Source callbacks ──────────────────────────────────────────────────────────


def authenticate(secret_data):
    """No authentication required for Open-Meteo."""
    return {}


def fetch_day(creds, date_str):
    """Fetch a single day from the Open-Meteo archive API.

    #501/X-11: on the shared retry policy (3 attempts, 2s/8s backoff on
    429/5xx and network errors) — was a bare, unretried urlopen."""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={LAT}&longitude={LON}"
        f"&start_date={date_str}&end_date={date_str}"
        f"&daily={_OPEN_METEO_FIELDS}"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&precipitation_unit=mm&timezone=America/Los_Angeles"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
    with urlopen_with_retry(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    # #2311 AQI decision: SOURCED, from Open-Meteo's air-quality product
    # (air-quality-api.open-meteo.com, hourly `us_aqi`) — same provider, no
    # auth, one extra call. Fail-soft: an AQI outage costs the aqi field for
    # the day (honest absence), never the weather record.
    try:
        data["air_quality"] = _fetch_air_quality(date_str)
    except Exception as e:
        logger.warning("air-quality fetch failed for %s — aqi omitted: %s", date_str, e)
    return data


def _fetch_air_quality(date_str):
    """Fetch hourly US AQI for one day from Open-Meteo's air-quality API (#2311)."""
    url = (
        f"https://air-quality-api.open-meteo.com/v1/air-quality?"
        f"latitude={LAT}&longitude={LON}"
        f"&start_date={date_str}&end_date={date_str}"
        f"&hourly=us_aqi&timezone=America/Los_Angeles"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
    with urlopen_with_retry(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _local_hhmm(iso_ts):
    """HH:MM from an Open-Meteo local ISO timestamp ('2026-07-01T05:16'), else None."""
    if isinstance(iso_ts, str) and "T" in iso_ts:
        return iso_ts.split("T", 1)[1][:5]
    return None


def _daily_aqi(raw):
    """Max hourly US AQI for the day, or None when nothing was measured (ADR-104)."""
    hourly = (raw.get("air_quality") or {}).get("hourly") or {}
    vals = [v for v in hourly.get("us_aqi") or [] if v is not None]
    return max(vals) if vals else None


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
        "source": "weather",
        "date": date_str,
        "temp_high_f": daily.get("temperature_2m_max", [None])[i],
        "temp_low_f": daily.get("temperature_2m_min", [None])[i],
        "temp_avg_f": daily.get("temperature_2m_mean", [None])[i],
        "humidity_pct": daily.get("relative_humidity_2m_mean", [None])[i],
        "precipitation_mm": daily.get("precipitation_sum", [None])[i],
        "wind_speed_max_mph": daily.get("wind_speed_10m_max", [None])[i],
        "pressure_hpa": daily.get("surface_pressure_mean", [None])[i],
        "daylight_hours": round(daylight_secs / 3600, 2),
        "sunshine_hours": round(sunshine_secs / 3600, 2),
        "uv_index_max": daily.get("uv_index_max", [None])[i],
        # #2311: the four field names html_builder's weather block already
        # reads. None values (old-style response, unknown code, AQI outage)
        # are stripped below — the brief omits the cell rather than fabricate.
        "condition": _WMO_CONDITIONS.get(daily.get("weather_code", [None])[i]),
        "sunrise_local": _local_hhmm(daily.get("sunrise", [None])[i]),
        "sunset_local": _local_hhmm(daily.get("sunset", [None])[i]),
        "aqi": _daily_aqi(raw),
    }

    # Strip None values (missing fields)
    return [{k: v for k, v in record.items() if v is not None}]


# ── Lambda entry point ────────────────────────────────────────────────────────


def lambda_handler(event, context):
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    try:
        """Entry point — delegates entirely to the ingestion framework."""
        return run_ingestion(config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
