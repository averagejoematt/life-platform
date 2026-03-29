"""MCP tools for body tape measurements (periodic, every 4-8 weeks)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mcp.core import query_source, get_table, get_user_id


def _float(val):
    """Convert Decimal/None to float."""
    if val is None:
        return None
    return float(val)


def _get_sessions(start_date=None, end_date=None, latest_only=False):
    """Fetch measurement sessions from DynamoDB."""
    if latest_only:
        table = get_table()
        import boto3.dynamodb.conditions as cond
        resp = table.query(
            KeyConditionExpression=cond.Key("pk").eq(f"USER#{get_user_id()}#SOURCE#measurements"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
    else:
        if not start_date:
            start_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        items = query_source("measurements", start_date, end_date)

    sessions = []
    for item in items:
        raw = {}
        derived = {}
        for k, v in item.items():
            if k in ("pk", "sk", "ingested_at", "source_file", "unit", "measured_by", "date", "session_number"):
                continue
            if k in ("waist_height_ratio", "bilateral_symmetry_bicep_in", "bilateral_symmetry_thigh_in",
                      "trunk_sum_in", "limb_avg_in"):
                derived[k] = _float(v)
            elif k.endswith("_in"):
                raw[k] = _float(v)

        sessions.append({
            "date": item.get("date", item.get("sk", "").replace("DATE#", "")),
            "session_number": int(item.get("session_number", 0)),
            "measurements": raw,
            "derived": {
                **derived,
                "waist_height_ratio_target": 0.5,
            },
        })

    return sessions


def tool_get_measurements(args):
    """Returns all measurement sessions in a date range with raw and derived fields."""
    latest_only = args.get("latest_only", False)
    start_date = args.get("start_date")
    end_date = args.get("end_date")

    sessions = _get_sessions(start_date, end_date, latest_only)

    # Board note
    board_note = ""
    if sessions:
        latest = sessions[-1] if not latest_only else sessions[0]
        whr = latest["derived"].get("waist_height_ratio", 0)
        bicep_sym = latest["derived"].get("bilateral_symmetry_bicep_in", 0)

        if whr and whr > 0.6:
            board_note = f"Dr. Peter Attia: Current waist-to-height ratio is {whr:.3f} — target is <0.500. " \
                         f"Ratio above 0.5 is associated with increased visceral fat and metabolic risk."
        if bicep_sym and bicep_sym > 1.0:
            board_note += f" Dr. Layne Norton: Bicep asymmetry of {bicep_sym:.1f}\" detected — " \
                          f"consider unilateral training to address imbalance."

    return {
        "sessions": sessions,
        "session_count": len(sessions),
        "date_range": {"start": start_date or "12mo ago", "end": end_date or "today"},
        "board_note": board_note,
    }


def tool_get_measurement_trends(args):
    """Cross-session analysis — deltas, rate of change, recomposition score, projection."""
    include_projection = args.get("include_projection", True)

    sessions = _get_sessions()
    sessions.sort(key=lambda s: s["date"])

    if not sessions:
        return {"error": "No measurement sessions found. First session needed."}

    if len(sessions) == 1:
        return {
            "baseline": sessions[0],
            "latest": sessions[0],
            "sessions_count": 1,
            "note": "Trend analysis available after session 2. This is the baseline.",
        }

    baseline = sessions[0]
    latest = sessions[-1]

    # Weeks elapsed
    try:
        d0 = datetime.strptime(baseline["date"], "%Y-%m-%d")
        d1 = datetime.strptime(latest["date"], "%Y-%m-%d")
        weeks_elapsed = max(1, (d1 - d0).days / 7)
    except Exception:
        weeks_elapsed = 4

    # Deltas from baseline
    deltas = {}
    all_keys = set(list(baseline["measurements"].keys()) + list(baseline["derived"].keys()))
    for k in all_keys:
        bv = baseline["measurements"].get(k) or baseline["derived"].get(k)
        lv = latest["measurements"].get(k) or latest["derived"].get(k)
        if bv is not None and lv is not None:
            deltas[k] = round(lv - bv, 3)

    # Rate of change per 4 weeks
    rate_4w = {}
    for k, delta in deltas.items():
        if k in ("waist_navel_in", "waist_narrowest_in", "waist_height_ratio"):
            rate_4w[k] = round(delta / weeks_elapsed * 4, 3)

    # Recomposition score
    recomp_sessions = []
    for i in range(1, len(sessions)):
        prev = sessions[i - 1]
        curr = sessions[i]
        trunk_shrinking = (
            (curr["measurements"].get("waist_navel_in", 999) or 999) <
            (prev["measurements"].get("waist_navel_in", 0) or 0)
        )
        limb_holding = True
        for limb in ["bicep_relaxed_left_in", "bicep_relaxed_right_in", "thigh_left_in", "thigh_right_in"]:
            cv = curr["measurements"].get(limb) or 0
            pv = prev["measurements"].get(limb) or 0
            if pv > 0 and cv < pv - 0.25:
                limb_holding = False
        recomp = trunk_shrinking and limb_holding
        recomp_sessions.append({"date": curr["date"], "recomposition": recomp})

    recomp_rate = sum(1 for r in recomp_sessions if r["recomposition"]) / max(1, len(recomp_sessions))

    result = {
        "baseline": baseline,
        "latest": latest,
        "sessions_count": len(sessions),
        "weeks_elapsed": round(weeks_elapsed, 1),
        "deltas_from_baseline": deltas,
        "rate_of_change_per_4_weeks": rate_4w,
        "recomposition_score": {
            "sessions": recomp_sessions,
            "recomposition_rate": round(recomp_rate, 2),
            "verdict": "Strong — trunk reducing while limbs hold" if recomp_rate >= 0.7
                       else "Mixed — some sessions show trunk reduction without limb preservation"
                       if recomp_rate >= 0.3 else "Early — insufficient recomposition signal",
        },
    }

    # Projection
    if include_projection and len(sessions) >= 2:
        whr = latest["derived"].get("waist_height_ratio", 0)
        whr_rate = rate_4w.get("waist_height_ratio", 0)
        if whr and whr_rate and whr_rate < 0:
            remaining = whr - 0.5
            weeks_to_target = remaining / abs(whr_rate) * 4
            projected_date = (datetime.now(timezone.utc) + timedelta(weeks=weeks_to_target)).strftime("%Y-%m-%d")
            result["projection"] = {
                "waist_height_ratio_current": whr,
                "waist_height_ratio_target": 0.5,
                "ratio_remaining": round(remaining, 4),
                "rate_per_week": round(whr_rate / 4, 4),
                "weeks_to_target": round(weeks_to_target),
                "projected_date": projected_date,
                "confidence": "low" if len(sessions) < 4 else "moderate" if len(sessions) < 8 else "high",
                "note": f"Based on {len(sessions)} sessions. {'≥4 sessions needed for reliable confidence.' if len(sessions) < 4 else ''}",
            }

    return result
