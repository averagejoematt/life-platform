"""The one source: Open-Meteo's historical weather archive.

Chosen because it needs no API key, no account, and no consent to publish — so a
stranger can run the whole pipeline on the first try. The real platform reads it
the same way (standard library `urllib`, no HTTP dependency).
"""

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "starter-slice/1.0 (+https://averagejoematt.com)"


def window(days: int, lag_days: int, today: date | None = None) -> tuple[str, str]:
    """The last `days` settled days, ending `lag_days` before today."""
    today = today or date.today()
    end = today - timedelta(days=lag_days)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def fetch(lat: float, lon: float, start: str, end: str, timeout: int = 20) -> dict:
    """Fetch a date range of daily temperatures. Returns the response verbatim."""
    query = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start,
            "end_date": end,
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": "celsius",
            "timezone": "UTC",
        }
    )
    req = urllib.request.Request(f"{ARCHIVE_URL}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https host
        return json.loads(resp.read().decode("utf-8"))


def normalize(raw: dict) -> list[dict]:
    """Raw API response -> one flat record per day.

    A day whose reading is missing is DROPPED, never zero-filled. An invented zero
    is indistinguishable from a real one once it is in the database.
    """
    daily = (raw or {}).get("daily") or {}
    dates = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    records = []
    for i, day in enumerate(dates):
        high = highs[i] if i < len(highs) else None
        low = lows[i] if i < len(lows) else None
        if high is None:
            continue
        records.append({"date": day, "temp_max_c": float(high), "temp_min_c": None if low is None else float(low)})
    return records
