"""
Feature #8: Heart Rate Recovery Tracking
Two parts:
  A) Strava Lambda enhancement — fetch HR streams, compute recovery metrics
  B) MCP tool — get_hr_recovery_trend

Part A modifies strava_lambda.py
Part B adds a tool to mcp_server.py
"""

# ══════════════════════════════════════════════════════════════════════════════
# PART A — Add to strava_lambda.py (after fetch_activity_zones, ~line 143)
# ══════════════════════════════════════════════════════════════════════════════

STRAVA_HR_STREAM_CODE = '''

def fetch_activity_streams(strava_id: str, secret: dict) -> tuple:
    """
    Fetch HR + time streams for an activity.
    Returns (hr_recovery_dict, secret).
    
    Uses Strava API: GET /api/v3/activities/{id}/streams?keys=heartrate,time
    
    Computes:
      - hr_peak: Highest 30s rolling average HR
      - hr_peak_instant: Single highest HR reading
      - hr_end_60s: Average HR in last 60s of activity
      - hr_recovery_intra: peak - end_60s (intra-activity recovery proxy)
      - has_cooldown: True if end_60s < 85% of peak (activity includes cooldown)
      
    For activities with cooldown:
      - hr_at_peak_plus_60s: HR 60s after peak
      - hr_at_peak_plus_120s: HR 120s after peak  
      - hr_recovery_60s: peak - hr_at_peak_plus_60s
      - hr_recovery_120s: peak - hr_at_peak_plus_120s
    """
    try:
        url = f"https://www.strava.com/api/v3/activities/{strava_id}/streams?keys=heartrate,time&key_type=time"
        data, secret = strava_get(url, secret)
        
        # Parse streams
        hr_data = None
        time_data = None
        for stream in data:
            if stream.get("type") == "heartrate":
                hr_data = stream.get("data", [])
            elif stream.get("type") == "time":
                time_data = stream.get("data", [])
        
        if not hr_data or not time_data or len(hr_data) < 60:
            return {}, secret
        
        # Rolling 30s average for peak detection (reduces noise)
        window = 30
        rolling_avgs = []
        for i in range(len(hr_data)):
            # Find all points within 30s window
            start_idx = i
            while start_idx > 0 and time_data[i] - time_data[start_idx] < window:
                start_idx -= 1
            window_vals = hr_data[start_idx:i+1]
            if window_vals:
                rolling_avgs.append(sum(window_vals) / len(window_vals))
            else:
                rolling_avgs.append(hr_data[i])
        
        # Peak HR (30s rolling) and instant peak
        peak_rolling = max(rolling_avgs)
        peak_rolling_idx = rolling_avgs.index(peak_rolling)
        peak_instant = max(hr_data)
        peak_time = time_data[peak_rolling_idx]
        total_time = time_data[-1]
        
        # Last 60s average
        last_60s_vals = [hr_data[i] for i in range(len(time_data)) 
                         if time_data[-1] - time_data[i] <= 60]
        end_60s = sum(last_60s_vals) / len(last_60s_vals) if last_60s_vals else None
        
        # Intra-activity recovery
        recovery_intra = round(peak_rolling - end_60s, 1) if end_60s else None
        has_cooldown = end_60s is not None and end_60s < peak_rolling * 0.85
        
        result = {
            "hr_peak": round(peak_rolling, 1),
            "hr_peak_instant": round(peak_instant, 1),
            "hr_end_60s": round(end_60s, 1) if end_60s else None,
            "hr_recovery_intra": recovery_intra,
            "has_cooldown": has_cooldown,
            "stream_duration_s": total_time,
            "stream_samples": len(hr_data),
        }
        
        # Post-peak recovery (only meaningful if data exists after peak)
        remaining_time = total_time - peak_time
        if remaining_time >= 60:
            # Find HR at peak + 60s
            target_60 = peak_time + 60
            idx_60 = min(range(len(time_data)), key=lambda i: abs(time_data[i] - target_60))
            # Average a 10s window around the target
            window_vals = [hr_data[j] for j in range(max(0, idx_60-5), min(len(hr_data), idx_60+5))]
            hr_at_60 = sum(window_vals) / len(window_vals) if window_vals else None
            if hr_at_60:
                result["hr_at_peak_plus_60s"] = round(hr_at_60, 1)
                result["hr_recovery_60s"] = round(peak_rolling - hr_at_60, 1)
        
        if remaining_time >= 120:
            target_120 = peak_time + 120
            idx_120 = min(range(len(time_data)), key=lambda i: abs(time_data[i] - target_120))
            window_vals = [hr_data[j] for j in range(max(0, idx_120-5), min(len(hr_data), idx_120+5))]
            hr_at_120 = sum(window_vals) / len(window_vals) if window_vals else None
            if hr_at_120:
                result["hr_at_peak_plus_120s"] = round(hr_at_120, 1)
                result["hr_recovery_120s"] = round(peak_rolling - hr_at_120, 1)
        
        print(f"  HR recovery: peak={result['hr_peak']}, end_60s={result.get('hr_end_60s')}, "
              f"recovery_intra={result.get('hr_recovery_intra')}, cooldown={has_cooldown}")
        
        return result, secret
        
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  No stream data for activity {strava_id}")
        elif e.code == 429:
            print(f"  Rate limited on stream fetch for {strava_id}")
        else:
            print(f"  Stream fetch error for {strava_id}: {e.code}")
        return {}, secret
    except Exception as e:
        print(f"  Stream fetch exception for {strava_id}: {e}")
        return {}, secret
'''

# Integration into main ingestion flow — add AFTER the zone fetch loop
# (after the `if a.get("has_heartrate") and a.get("id"):` block, ~line 384)
STRAVA_INTEGRATION_CODE = '''
            # Fetch HR streams for recovery metrics (only for activities with HR, >10 min)
            if a.get("has_heartrate") and a.get("id"):
                elapsed = a.get("elapsed_time") or a.get("elapsed_time_seconds") or 0
                if elapsed >= 600:  # Only for activities >= 10 min
                    hr_recovery, secret = fetch_activity_streams(str(a["id"]), secret)
                    if hr_recovery:
                        norm["hr_recovery"] = hr_recovery
'''


# ══════════════════════════════════════════════════════════════════════════════
# PART B — MCP tool: get_hr_recovery_trend
# Add to mcp_server.py BEFORE TOOLS dict
# ══════════════════════════════════════════════════════════════════════════════

HR_RECOVERY_MCP_CODE = '''
def tool_get_hr_recovery_trend(args):
    """
    Heart rate recovery tracker. Extracts HR recovery metrics from Strava activities
    (stored by enhanced ingestion), trends over time, classifies against clinical
    thresholds, and identifies fitness trajectory.
    
    HR Recovery is the strongest exercise-derived predictor of all-cause mortality
    (Cole et al., NEJM 1999; Jouven et al., NEJM 2005).
    
    Clinical thresholds (HRR at 1 minute post-peak):
      > 25 bpm = Excellent (elite autonomic function)
      18-25 bpm = Good
      12-18 bpm = Average
      < 12 bpm  = Below Average (abnormal — investigate)
      
    Since we measure intra-activity recovery (not strictly post-exercise),
    values are proxies. Activities with cooldown periods give the most
    reliable measurements. Activities without cooldown are flagged.
    """
    end_date = args.get("end_date", datetime.utcnow().strftime("%Y-%m-%d"))
    start_date = args.get("start_date", (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))
    sport_filter = (args.get("sport_type") or "").strip().lower()
    cooldown_only = args.get("cooldown_only", False)
    
    strava_items = query_source("strava", start_date, end_date)
    if not strava_items:
        return {"error": "No Strava data for range.", "start_date": start_date, "end_date": end_date}
    
    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None
    
    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None
    
    profile = get_profile()
    max_hr = float(profile.get("max_heart_rate", 190))
    
    # ── Extract HR recovery data from activities ─────────────────────────────
    records = []
    for item in strava_items:
        date = item.get("date")
        for act in (item.get("activities") or []):
            hr_rec = act.get("hr_recovery")
            if not hr_rec or not isinstance(hr_rec, dict):
                continue
            
            sport = (act.get("sport_type") or act.get("type") or "").lower()
            if sport_filter and sport_filter not in sport.lower().replace(" ", ""):
                continue
            
            has_cooldown = hr_rec.get("has_cooldown", False)
            if cooldown_only and not has_cooldown:
                continue
            
            peak = _sf(hr_rec.get("hr_peak"))
            recovery_intra = _sf(hr_rec.get("hr_recovery_intra"))
            recovery_60s = _sf(hr_rec.get("hr_recovery_60s"))
            recovery_120s = _sf(hr_rec.get("hr_recovery_120s"))
            
            # Use best available recovery metric
            best_recovery = recovery_60s or recovery_intra
            
            if peak is None or best_recovery is None:
                continue
            
            # Classify
            if best_recovery >= 25:
                classification = "excellent"
            elif best_recovery >= 18:
                classification = "good"
            elif best_recovery >= 12:
                classification = "average"
            else:
                classification = "below_average"
            
            records.append({
                "date": date,
                "sport_type": act.get("sport_type") or act.get("type"),
                "activity_name": act.get("name", ""),
                "duration_min": round((_sf(act.get("elapsed_time_seconds")) or 0) / 60, 1),
                "hr_peak": peak,
                "hr_peak_pct_max": round(peak / max_hr * 100, 1) if peak else None,
                "hr_end_60s": _sf(hr_rec.get("hr_end_60s")),
                "hr_recovery_intra": recovery_intra,
                "hr_recovery_60s": recovery_60s,
                "hr_recovery_120s": recovery_120s,
                "has_cooldown": has_cooldown,
                "best_recovery_bpm": best_recovery,
                "classification": classification,
            })
    
    if not records:
        return {
            "error": "No activities with HR recovery data found. HR recovery tracking requires the enhanced Strava ingestion (v2.35.0+).",
            "start_date": start_date, "end_date": end_date,
            "tip": "Activities need heart rate data and >= 10 min duration. Recovery metrics are computed from HR streams during ingestion.",
        }
    
    records.sort(key=lambda r: r["date"])
    
    # ── Trend analysis ───────────────────────────────────────────────────────
    # Split into first half vs second half
    mid = len(records) // 2
    first_half = records[:mid] if mid > 0 else records
    second_half = records[mid:] if mid > 0 else records
    
    first_avg = _avg([r["best_recovery_bpm"] for r in first_half])
    second_avg = _avg([r["best_recovery_bpm"] for r in second_half])
    
    trend_direction = None
    trend_delta = None
    if first_avg is not None and second_avg is not None:
        trend_delta = round(second_avg - first_avg, 1)
        if trend_delta > 2:
            trend_direction = "improving"
        elif trend_delta < -2:
            trend_direction = "declining"
        else:
            trend_direction = "stable"
    
    # Pearson correlation: date ordinal vs recovery
    date_ordinals = []
    recovery_vals = []
    base_date = datetime.strptime(records[0]["date"], "%Y-%m-%d")
    for r in records:
        d = (datetime.strptime(r["date"], "%Y-%m-%d") - base_date).days
        date_ordinals.append(d)
        recovery_vals.append(r["best_recovery_bpm"])
    
    r_val = pearson_r(date_ordinals, recovery_vals) if len(date_ordinals) >= 5 else None
    
    # ── Sport type breakdown ─────────────────────────────────────────────────
    by_sport = {}
    for r in records:
        s = r["sport_type"] or "Unknown"
        if s not in by_sport:
            by_sport[s] = {"activities": 0, "avg_recovery": [], "avg_peak_hr": []}
        by_sport[s]["activities"] += 1
        by_sport[s]["avg_recovery"].append(r["best_recovery_bpm"])
        by_sport[s]["avg_peak_hr"].append(r["hr_peak"])
    
    sport_summary = {}
    for s, data in by_sport.items():
        sport_summary[s] = {
            "activities": data["activities"],
            "avg_recovery_bpm": _avg(data["avg_recovery"]),
            "avg_peak_hr": _avg(data["avg_peak_hr"]),
        }
    
    # ── Classification distribution ──────────────────────────────────────────
    dist = {"excellent": 0, "good": 0, "average": 0, "below_average": 0}
    for r in records:
        dist[r["classification"]] += 1
    
    total = len(records)
    dist_pct = {k: round(v / total * 100, 1) for k, v in dist.items()}
    
    # ── Best and worst ───────────────────────────────────────────────────────
    sorted_by_recovery = sorted(records, key=lambda r: r["best_recovery_bpm"], reverse=True)
    best_5 = sorted_by_recovery[:5]
    worst_5 = sorted_by_recovery[-5:]
    
    # ── Cooldown analysis ────────────────────────────────────────────────────
    cooldown_records = [r for r in records if r["has_cooldown"]]
    no_cooldown = [r for r in records if not r["has_cooldown"]]
    
    # ── Clinical assessment ──────────────────────────────────────────────────
    overall_avg = _avg([r["best_recovery_bpm"] for r in records])
    
    if overall_avg and overall_avg >= 25:
        clinical = "Excellent autonomic function. Strong parasympathetic reactivation indicates high cardiovascular fitness."
    elif overall_avg and overall_avg >= 18:
        clinical = "Good HR recovery. Healthy autonomic balance. Continue current training approach."
    elif overall_avg and overall_avg >= 12:
        clinical = "Average HR recovery. Room for improvement — consistent Zone 2 training and stress management will enhance parasympathetic tone."
    elif overall_avg:
        clinical = "Below average HR recovery (<12 bpm). This is a clinical flag per Cole et al. (NEJM). Discuss with physician. May indicate autonomic dysfunction, deconditioning, or chronic stress."
    else:
        clinical = "Insufficient data for clinical assessment."
    
    # ── Board of Directors ───────────────────────────────────────────────────
    bod = []
    if trend_direction == "improving":
        bod.append(f"Attia: HR recovery improving by {trend_delta} bpm — cardiovascular fitness is trending in the right direction. This is one of the strongest longevity biomarkers.")
    elif trend_direction == "declining":
        bod.append(f"Huberman: HR recovery declining by {abs(trend_delta)} bpm — consider overtraining, sleep debt, or chronic stress as potential causes. Parasympathetic function reflects total allostatic load.")
    
    if cooldown_records and no_cooldown:
        bod.append(f"Galpin: {len(cooldown_records)} of {total} activities include cooldown. Adding a 5-min easy cooldown to every session improves recovery metrics AND gives more reliable HR recovery data.")
    
    if dist["below_average"] > 0 and dist["below_average"] / total > 0.3:
        bod.append("Attia: >30% of sessions show below-average recovery. This warrants attention — consider reducing training volume and prioritizing sleep.")
    
    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_activities_with_hr_recovery": total,
        "overall_avg_recovery_bpm": overall_avg,
        "clinical_assessment": clinical,
        "trend": {
            "direction": trend_direction,
            "delta_bpm": trend_delta,
            "first_half_avg": first_avg,
            "second_half_avg": second_avg,
            "pearson_r": r_val,
            "interpretation": (
                f"HR recovery {'improving' if trend_direction == 'improving' else 'declining' if trend_direction == 'declining' else 'stable'} "
                f"over the period ({'+' if (trend_delta or 0) > 0 else ''}{trend_delta} bpm)."
            ) if trend_delta is not None else None,
        },
        "classification_distribution": dist,
        "classification_distribution_pct": dist_pct,
        "by_sport_type": sport_summary,
        "cooldown_analysis": {
            "activities_with_cooldown": len(cooldown_records),
            "activities_without_cooldown": len(no_cooldown),
            "avg_recovery_with_cooldown": _avg([r["best_recovery_bpm"] for r in cooldown_records]),
            "avg_recovery_without_cooldown": _avg([r["best_recovery_bpm"] for r in no_cooldown]),
            "note": "Activities with cooldown give more reliable HR recovery measurements. Consider always including a 3-5 min cooldown.",
        },
        "best_recoveries": [{k: v for k, v in r.items() if k != "classification"} for r in best_5],
        "worst_recoveries": [{k: v for k, v in r.items() if k != "classification"} for r in worst_5],
        "board_of_directors": bod,
        "methodology": (
            "HR recovery computed from Strava HR streams during ingestion. "
            "Peak HR = 30s rolling average max. Recovery = peak minus HR at peak+60s (preferred) "
            "or peak minus last-60s average (fallback). Activities with end HR < 85% of peak "
            "are classified as having cooldown. Clinical thresholds per Cole et al. (NEJM 1999): "
            ">25 excellent, 18-25 good, 12-18 average, <12 below average (abnormal)."
        ),
        "source": "strava (HR streams)",
    }
'''

HR_RECOVERY_TOOLS_ENTRY = '''
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
                    "cooldown_only": {"type": "boolean", "description": "Only include activities with detected cooldown (more reliable measurements). Default: false."},
                },
                "required": [],
            },
        },
    },'''

print("Feature #8 patch ready.")
print(f"Strava Lambda stream code: {len(STRAVA_HR_STREAM_CODE.splitlines())} lines")
print(f"MCP tool code: {len(HR_RECOVERY_MCP_CODE.splitlines())} lines")
