#!/bin/bash
# deploy_feature10_weather.sh — Feature #10: Weather & Seasonal Correlation
# 1 new MCP tool (fetch + cache + correlate). MCP-only, no new Lambda.
set -euo pipefail

echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #10: Weather & Seasonal Correlation"
echo "  1 MCP tool: get_weather_correlation"
echo "  Data source: Open-Meteo API (free, no auth)"
echo "═══════════════════════════════════════════════════════════════"

cd ~/Documents/Claude/life-platform

# ── Backup ──────────────────────────────────────────────────────────────────
cp mcp_server.py mcp_server.py.bak.f10
echo "✅ Backup: mcp_server.py.bak.f10"

# ── Patch ───────────────────────────────────────────────────────────────────
python3 << 'PYTHON_PATCH'
import sys

with open("mcp_server.py", "r") as f:
    content = f.read()

# ── Add urllib.request import if not present ──
if "import urllib.request" not in content:
    content = content.replace("import json\n", "import json\nimport urllib.request\n")
    print("Added urllib.request import")
else:
    print("urllib.request already imported")

# ── Insert tool function before TOOLS dict ──
tool_func = '''

# ══════════════════════════════════════════════════════════════════════════════
# Feature #10: Weather & Seasonal Correlation
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_weather_range(start_date, end_date):
    """
    Fetch weather data from Open-Meteo archive API for Seattle.
    Caches results in DynamoDB weather partition.
    Returns list of day records.
    """
    # Seattle coordinates
    LAT, LON = 47.6062, -122.3321

    # Check DynamoDB cache first
    cached = query_source("weather", start_date, end_date)
    cached_dates = {item.get("date") for item in cached if item.get("date")}

    # Find missing dates
    missing_dates = []
    d = datetime.strptime(start_date, "%Y-%m-%d")
    d_end = datetime.strptime(end_date, "%Y-%m-%d")
    while d <= d_end:
        ds = d.strftime("%Y-%m-%d")
        if ds not in cached_dates:
            missing_dates.append(ds)
        d += timedelta(days=1)

    # Fetch missing from Open-Meteo
    if missing_dates:
        fetch_start = min(missing_dates)
        fetch_end = max(missing_dates)
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={LAT}&longitude={LON}"
            f"&start_date={fetch_start}&end_date={fetch_end}"
            f"&daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
            f"relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max,"
            f"surface_pressure_mean,daylight_duration,uv_index_max,"
            f"sunshine_duration"
            f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
            f"&precipitation_unit=mm&timezone=America/Los_Angeles"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            daily = data.get("daily", {})
            dates = daily.get("time", [])
            table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")

            new_records = []
            for i, date_str in enumerate(dates):
                if date_str not in set(missing_dates):
                    continue
                daylight_hrs = round(float(daily["daylight_duration"][i] or 0) / 3600, 2)
                sunshine_hrs = round(float(daily["sunshine_duration"][i] or 0) / 3600, 2)
                record = {
                    "date": date_str,
                    "temp_high_f": daily["temperature_2m_max"][i],
                    "temp_low_f": daily["temperature_2m_min"][i],
                    "temp_avg_f": daily["temperature_2m_mean"][i],
                    "humidity_pct": daily["relative_humidity_2m_mean"][i],
                    "precipitation_mm": daily["precipitation_sum"][i],
                    "wind_speed_max_mph": daily["wind_speed_10m_max"][i],
                    "pressure_hpa": daily["surface_pressure_mean"][i],
                    "daylight_hours": daylight_hrs,
                    "sunshine_hours": sunshine_hrs,
                    "uv_index_max": daily["uv_index_max"][i],
                }
                new_records.append(record)

                # Cache in DynamoDB
                db_item = {
                    "pk": "USER#matthew#SOURCE#weather",
                    "sk": f"DATE#{date_str}",
                    "source": "weather",
                    **record,
                }
                try:
                    from decimal import Decimal
                    def _to_decimal(obj):
                        if isinstance(obj, float):
                            return Decimal(str(round(obj, 4)))
                        if isinstance(obj, dict):
                            return {k: _to_decimal(v) for k, v in obj.items()}
                        if isinstance(obj, list):
                            return [_to_decimal(v) for v in obj]
                        return obj
                    table.put_item(Item=_to_decimal(db_item))
                except Exception as e:
                    logger.warning(f"Weather cache write failed for {date_str}: {e}")

            print(f"Fetched and cached {len(new_records)} weather days from Open-Meteo")
            cached.extend(new_records)

        except Exception as e:
            logger.warning(f"Open-Meteo fetch failed: {e}")
            # Continue with whatever cached data we have

    return cached


def tool_get_weather_correlation(args):
    """
    Weather & seasonal correlation analysis. Fetches weather for Seattle from
    Open-Meteo (free API), caches in DynamoDB, and correlates with health metrics.

    Huberman: Light exposure (daylight hours) is the master circadian lever.
    Walker: Seasonal light changes drive mood, energy, and sleep timing shifts.
    Attia: Barometric pressure changes correlate with joint pain and headaches.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d"))

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    # Fetch weather data (cached + fresh from Open-Meteo)
    weather_items = _fetch_weather_range(start_date, end_date)
    if not weather_items:
        return {"error": "Could not fetch weather data.", "start_date": start_date, "end_date": end_date}

    weather_by_date = {w.get("date"): w for w in weather_items if w.get("date")}

    # Fetch health data
    health_sources = {}
    for src in ["whoop", "eightsleep", "garmin", "apple_health"]:
        try:
            health_sources[src] = {item.get("date"): item for item in query_source(src, start_date, end_date) if item.get("date")}
        except Exception:
            health_sources[src] = {}

    # Journal mood/energy
    journal_by_date = {}
    try:
        journal_items = query_source("notion", start_date, end_date)
        for item in journal_items:
            d = item.get("date")
            if d and not d in journal_by_date:
                journal_by_date[d] = {}
            for field in ["morning_mood", "morning_energy", "stress_level", "day_rating"]:
                v = _sf(item.get(field))
                if v is not None:
                    journal_by_date.setdefault(d, {})[field] = v
    except Exception:
        pass

    # Weather variables to correlate
    WEATHER_VARS = [
        ("temp_avg_f", "Temperature (°F)"),
        ("humidity_pct", "Humidity (%)"),
        ("precipitation_mm", "Precipitation (mm)"),
        ("daylight_hours", "Daylight Hours"),
        ("sunshine_hours", "Sunshine Hours"),
        ("pressure_hpa", "Barometric Pressure (hPa)"),
        ("uv_index_max", "UV Index"),
    ]

    # Health metrics to compare against
    HEALTH_METRICS = [
        ("whoop", "recovery_score", "Whoop Recovery"),
        ("whoop", "hrv", "HRV"),
        ("eightsleep", "sleep_score", "Sleep Score"),
        ("eightsleep", "sleep_efficiency_pct", "Sleep Efficiency"),
        ("eightsleep", "deep_pct", "Deep Sleep %"),
        ("garmin", "avg_stress", "Garmin Stress"),
        ("garmin", "body_battery_high", "Body Battery"),
    ]
    JOURNAL_METRICS = [
        ("morning_mood", "Morning Mood"),
        ("morning_energy", "Morning Energy"),
        ("stress_level", "Stress Level"),
        ("day_rating", "Day Rating"),
    ]

    # Compute correlations
    correlations = {}
    for wvar, wlabel in WEATHER_VARS:
        correlations[wvar] = {"label": wlabel, "health_correlations": {}, "journal_correlations": {}}

        for src, field, hlabel in HEALTH_METRICS:
            xs, ys = [], []
            for d, w in weather_by_date.items():
                wv = _sf(w.get(wvar))
                if wv is None: continue
                hv = _sf(health_sources.get(src, {}).get(d, {}).get(field))
                if hv is not None:
                    xs.append(wv); ys.append(hv)
            r = pearson_r(xs, ys) if len(xs) >= 10 else None
            if r is not None:
                correlations[wvar]["health_correlations"][field] = {"label": hlabel, "pearson_r": r, "n": len(xs)}

        for jfield, jlabel in JOURNAL_METRICS:
            xs, ys = [], []
            for d, w in weather_by_date.items():
                wv = _sf(w.get(wvar))
                if wv is None: continue
                jv = journal_by_date.get(d, {}).get(jfield)
                if jv is not None:
                    xs.append(wv); ys.append(jv)
            r = pearson_r(xs, ys) if len(xs) >= 10 else None
            if r is not None:
                correlations[wvar]["journal_correlations"][jfield] = {"label": jlabel, "pearson_r": r, "n": len(xs)}

    # Remove empty correlation groups
    for wvar in list(correlations.keys()):
        if not correlations[wvar]["health_correlations"] and not correlations[wvar]["journal_correlations"]:
            del correlations[wvar]

    # Weather summary
    weather_summary = {
        "avg_temp_f": _avg([_sf(w.get("temp_avg_f")) for w in weather_items]),
        "avg_humidity_pct": _avg([_sf(w.get("humidity_pct")) for w in weather_items]),
        "total_precip_mm": round(sum(_sf(w.get("precipitation_mm")) or 0 for w in weather_items), 1),
        "avg_daylight_hours": _avg([_sf(w.get("daylight_hours")) for w in weather_items]),
        "avg_sunshine_hours": _avg([_sf(w.get("sunshine_hours")) for w in weather_items]),
        "rainy_days": sum(1 for w in weather_items if (_sf(w.get("precipitation_mm")) or 0) > 0.5),
        "total_days": len(weather_items),
    }

    # Seasonal comparison (if enough data)
    seasonal = None
    if len(weather_items) >= 60:
        mid = len(weather_items) // 2
        first_half = weather_items[:mid]
        second_half = weather_items[mid:]
        seasonal = {
            "first_half_avg_daylight": _avg([_sf(w.get("daylight_hours")) for w in first_half]),
            "second_half_avg_daylight": _avg([_sf(w.get("daylight_hours")) for w in second_half]),
            "daylight_trend": "increasing" if (_avg([_sf(w.get("daylight_hours")) for w in second_half]) or 0) > (_avg([_sf(w.get("daylight_hours")) for w in first_half]) or 0) else "decreasing",
        }

    # Find strongest correlations
    notable = []
    for wvar, data in correlations.items():
        for field, corr in {**data.get("health_correlations", {}), **data.get("journal_correlations", {})}.items():
            r = corr.get("pearson_r", 0)
            if abs(r) >= 0.2:
                notable.append({"weather": data["label"], "health": corr["label"], "r": r, "n": corr["n"]})
    notable.sort(key=lambda x: abs(x["r"]), reverse=True)

    # Board of Directors
    bod = []
    daylight_mood = correlations.get("daylight_hours", {}).get("journal_correlations", {}).get("morning_mood", {})
    if daylight_mood and daylight_mood.get("pearson_r", 0) > 0.15:
        bod.append(f"Huberman: Daylight correlates with your mood (r={daylight_mood['pearson_r']}). Morning sunlight within 30 min of waking is the single highest-ROI circadian intervention.")
    
    sunshine_sleep = correlations.get("sunshine_hours", {}).get("health_correlations", {}).get("sleep_score", {})
    if sunshine_sleep and sunshine_sleep.get("pearson_r", 0) > 0.15:
        bod.append(f"Walker: More sunshine correlates with better sleep (r={sunshine_sleep['pearson_r']}). Light exposure during the day strengthens the circadian sleep drive.")

    pressure_corrs = correlations.get("pressure_hpa", {}).get("health_correlations", {})
    if any(abs(c.get("pearson_r", 0)) > 0.2 for c in pressure_corrs.values()):
        bod.append("Attia: Barometric pressure shows correlation with your health metrics. Low-pressure systems (storms) can affect joint inflammation, headaches, and autonomic function.")

    if weather_summary.get("rainy_days", 0) > weather_summary.get("total_days", 1) * 0.5:
        bod.append("Note: Seattle's rain prevalence means outdoor light exposure requires intentionality. Consider a 10,000 lux light therapy lamp for morning use during dark months.")

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "location": "Seattle, WA (47.61, -122.33)",
        "weather_summary": weather_summary,
        "correlations": correlations,
        "notable_correlations": notable[:10],
        "seasonal_analysis": seasonal,
        "board_of_directors": bod,
        "methodology": (
            "Weather data from Open-Meteo archive API (free, WMO-grade). Cached in DynamoDB after first fetch. "
            "Pearson correlations between daily weather variables and health metrics. "
            "Requires >= 10 overlapping data points per correlation pair. "
            "Huberman: daylight = master circadian lever. Walker: light drives sleep-wake timing."
        ),
        "source": "open-meteo + whoop + eightsleep + garmin + apple_health + notion",
    }

'''

insert_point = content.find("\nTOOLS = {")
if insert_point == -1:
    print("ERROR: Could not find TOOLS dict")
    sys.exit(1)
content = content[:insert_point] + tool_func + content[insert_point:]
print("Inserted weather tool function")

# ── Add TOOLS entry ──
tools_entry = '''
    "get_weather_correlation": {
        "fn": tool_get_weather_correlation,
        "schema": {
            "name": "get_weather_correlation",
            "description": (
                "Weather & seasonal correlation analysis. Fetches Seattle weather from Open-Meteo "
                "(free API), caches in DynamoDB, and correlates temperature, humidity, precipitation, "
                "daylight hours, sunshine, barometric pressure, and UV index with health metrics "
                "(recovery, HRV, sleep, stress, Body Battery) and journal signals (mood, energy, stress). "
                "Huberman: daylight is the master circadian lever. Walker: seasonal light drives sleep. "
                "Attia: barometric pressure affects inflammation and autonomic function. "
                "Use for: 'does weather affect my sleep?', 'daylight and mood correlation', "
                "'seasonal patterns in my health', 'weather impact on recovery', "
                "'does rain affect my energy?', 'sunshine and sleep quality'."
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
    },'''

# Find last TOOLS entry
for marker in ['"get_supplement_correlation":', '"get_sleep_environment_analysis":', '"get_hr_recovery_trend":', '"get_health_trajectory":']:
    idx = content.find(marker)
    if idx != -1:
        break
if idx == -1:
    print("ERROR: Could not find TOOLS entry to insert after")
    sys.exit(1)

depth = 0; found_first = False; end_idx = idx
for i in range(idx, len(content)):
    if content[i] == '{': depth += 1; found_first = True
    elif content[i] == '}':
        depth -= 1
        if found_first and depth == 0: end_idx = i + 1; break

if content[end_idx:end_idx+1] == ',':
    insert_at = end_idx + 1
else:
    content = content[:end_idx] + ',' + content[end_idx:]
    insert_at = end_idx + 1

content = content[:insert_at] + tools_entry + content[insert_at:]
print("Inserted TOOLS entry for get_weather_correlation")

with open("mcp_server.py", "w") as f:
    f.write(content)
print("mcp_server.py patched successfully")
PYTHON_PATCH

echo "✅ MCP server patched"

# ── Package and deploy ──────────────────────────────────────────────────────
cp mcp_server.py lambdas/mcp_server.py
cd lambdas && rm -f mcp_server.zip && zip mcp_server.zip mcp_server.py && cd ..

aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb://lambdas/mcp_server.zip \
  --region us-west-2

# ── Verify ──────────────────────────────────────────────────────────────────
TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Feature #10 deployed! Tool: get_weather_correlation"
echo "  MCP tool count: $TOOL_COUNT"
echo "  Data: Open-Meteo API → DynamoDB cache (SOURCE#weather)"
echo "  No new Lambda — weather fetched on-demand + cached"
echo "  Try: 'How does weather affect my sleep and mood?'"
echo "═══════════════════════════════════════════════════════════════"
