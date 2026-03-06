"""
Adaptive Mode MCP Tools — v1.0.0

Tools:
  get_adaptive_mode — view current/recent brief mode + engagement scores
"""

import json
import boto3
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

_REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID    = os.environ.get("USER_ID", "matthew")

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"


def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def get_adaptive_mode(days: int = 14) -> dict:
    """
    Retrieve recent adaptive brief mode history.

    Returns current mode, engagement score, contributing factors, and a
    day-by-day trend for the requested window.

    Args:
        days: Number of days of history to return (default 14, max 30)
    """
    days = min(max(int(days), 1), 30)
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()
    end   = (today - timedelta(days=1)).isoformat()

    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": USER_PREFIX + "adaptive_mode",
                ":s":  "DATE#" + start,
                ":e":  "DATE#" + end,
            },
            ScanIndexForward=False,
        )
        records = [d2f(item) for item in resp.get("Items", [])]
    except Exception as e:
        return {"error": str(e)}

    if not records:
        return {
            "message": "No adaptive mode records found. The adaptive-mode-compute Lambda may not yet be deployed.",
            "days_requested": days,
        }

    # Mode distribution
    mode_counts = {"flourishing": 0, "standard": 0, "struggling": 0}
    for r in records:
        m = r.get("brief_mode", "standard")
        mode_counts[m] = mode_counts.get(m, 0) + 1

    latest = records[0]
    avg_score = round(sum(r.get("engagement_score", 50) for r in records) / len(records), 1)

    # 7-day streak of current mode
    current_mode = latest.get("brief_mode", "standard")
    streak = 0
    for r in records:
        if r.get("brief_mode") == current_mode:
            streak += 1
        else:
            break

    # Build compact history
    history = []
    for r in sorted(records, key=lambda x: x.get("date", ""), reverse=False):
        history.append({
            "date":  r.get("date"),
            "mode":  r.get("brief_mode"),
            "score": r.get("engagement_score"),
            "factors": r.get("factors", {}),
        })

    return {
        "current": {
            "date":             latest.get("date"),
            "brief_mode":       latest.get("brief_mode"),
            "mode_label":       latest.get("mode_label"),
            "engagement_score": latest.get("engagement_score"),
            "factors":          latest.get("factors", {}),
            "component_scores": latest.get("component_scores", {}),
            "computed_at":      latest.get("computed_at"),
        },
        "summary": {
            "days_analysed":   len(records),
            "avg_score":       avg_score,
            "current_streak":  streak,
            "streak_mode":     current_mode,
            "mode_distribution": mode_counts,
        },
        "history": history,
        "interpretation": {
            "flourishing": "Score ≥ 70 — journal complete, high habit adherence, improving trend",
            "standard":    "Score 40-69 — on track, normal brief behaviour",
            "struggling":  "Score < 40 — brief shifts to gentler coaching and recovery focus",
        },
    }
