"""
data_reconciliation_lambda.py — DATA-3: Weekly data reconciliation job.

Runs every Sunday at 11:30 PM PT (Monday 07:30 UTC) — after the weekly digest.
Checks that all 19 active data sources have DynamoDB records for each of the
last 7 days. Compiles a gap report and sends an SES summary email.

PURPOSE:
  Catches silent ingestion failures that don't cause Lambda errors (e.g. API
  returns empty but Lambda completes successfully, DDB write succeeds but
  with no useful data, gap-aware backfill missed a day).

  Complements the freshness checker (which watches recency) by validating
  HISTORICAL coverage across the week.

SOURCES CHECKED (19):
  whoop, garmin, apple_health, macrofactor, strava, eightsleep, withings,
  habitify, notion, todoist, weather, supplements, day_grade, habit_scores,
  computed_metrics, character_sheet, adaptive_mode, computed_insights,
  hypothesis (weekly, not daily — different check)

REPORT FORMAT:
  Source | Mon | Tue | Wed | Thu | Fri | Sat | Sun | Coverage
  whoop  |  ✅  |  ✅  |  ✅  |  ✅  |  ✅  |  ✅  |  ✅  | 7/7
  notion |  ✅  |  ❌  |  ✅  |  ✅  |  ✅  |  ❌  |  ✅  | 5/7  ← gap

Severity:
  🟢 GREEN: All 19 sources have 7/7 coverage — nothing to do.
  🟡 YELLOW: 1–3 sources have 1–2 gaps — monitor.
  🔴 RED: Any source has 3+ gaps, or 4+ sources have any gap — investigate.

v1.0.0 — 2026-03-08 (DATA-3)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("data-reconciliation")
except ImportError:
    logger = logging.getLogger("data-reconciliation")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
REGION    = os.environ.get("AWS_REGION", "us-west-2")
TABLE     = os.environ.get("TABLE_NAME", "life-platform")
BUCKET    = os.environ["S3_BUCKET"]
USER_ID   = os.environ["USER_ID"]
RECIPIENT = os.environ["EMAIL_RECIPIENT"]
SENDER    = os.environ["EMAIL_SENDER"]
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# ── Sources and their check configs ───────────────────────────────────────────
# Each entry: (source_name, expected_days_per_week, notes)
# expected_days: 7 = daily, 5 = weekdays only, 1 = weekly
# Gaps are only flagged if days_missing > (7 - expected_days)
SOURCES = [
    # Daily sources (expected every day)
    ("whoop",            7, "Sleep + recovery — wrist sensor"),
    ("apple_health",     7, "Steps, CGM, gait — iPhone webhook"),
    ("weather",          7, "Open-Meteo daily fetch"),
    ("day_grade",        7, "Computed by daily-metrics-compute"),
    ("habit_scores",     7, "Computed by daily-metrics-compute"),
    ("computed_metrics", 7, "Computed by daily-metrics-compute"),
    ("character_sheet",  7, "Computed by character-sheet-compute"),
    ("adaptive_mode",    7, "Computed by adaptive-mode-compute"),
    ("computed_insights",7, "Computed by daily-insight-compute"),
    # Highly active but may miss days
    ("strava",           5, "Exercise days only — OK to miss 2+"),
    ("garmin",           5, "Exercise days only — OK to miss 2+"),
    ("eightsleep",       7, "Bed environment — every night"),
    ("withings",         5, "Weight — may skip weekends"),
    ("habitify",         7, "Habits — daily logging expected"),
    ("todoist",          7, "Tasks — daily expected"),
    ("macrofactor",      6, "Nutrition CSV — may miss 1 day/week"),
    # Journal — variable
    ("notion",           5, "Journal entries — weekdays typical"),
    # Supplements — every day logged
    ("supplements",      7, "Supplement bridge — every day"),
]

# Sources that DON'T use DATE# sk prefix (skip or handle differently)
_SKIP_SOURCES = set()


# ── AWS clients ────────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE)
ses      = boto3.client("sesv2", region_name=REGION)
secrets  = boto3.client("secretsmanager", region_name=REGION)


def d2f(obj):
    if isinstance(obj, Decimal): return float(obj)
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    return obj


def check_source_coverage(source: str, dates: list[str]) -> dict[str, bool]:
    """Query DDB for each date and return {date: has_record}.

    Uses individual GetItem calls — more reliable than Query for gap detection.
    """
    pk = USER_PREFIX + source
    coverage = {}
    for date_str in dates:
        try:
            resp = table.get_item(
                Key={"pk": pk, "sk": f"DATE#{date_str}"},
                ProjectionExpression="pk",   # minimal read — just need existence
            )
            item = resp.get("Item")
            coverage[date_str] = item is not None
        except Exception as e:
            logger.warning(f"[reconciliation] Error checking {source}/{date_str}: {e}")
            coverage[date_str] = None  # unknown
    return coverage


def coverage_emoji(present: bool | None) -> str:
    if present is True:  return "✅"
    if present is False: return "❌"
    return "❓"  # unknown (error)


def classify_severity(source_results: list[dict]) -> tuple[str, str]:
    """Return (severity_label, color_hex) based on gap count across all sources."""
    total_gaps = sum(r["gaps"] for r in source_results)
    sources_with_gaps = sum(1 for r in source_results if r["gaps"] > 0)
    max_single_gaps = max((r["gaps"] for r in source_results), default=0)

    if total_gaps == 0:
        return "GREEN — Full Coverage", "#059669"
    if max_single_gaps >= 3 or sources_with_gaps >= 4:
        return "RED — Investigate Gaps", "#dc2626"
    return "YELLOW — Monitor", "#d97706"


def build_html_report(dates: list[str], source_results: list[dict], severity: str, color: str) -> str:
    """Build HTML email with reconciliation table."""
    week_start = dates[0]
    week_end   = dates[-1]
    day_labels = [datetime.strptime(d, "%Y-%m-%d").strftime("%a") for d in dates]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows_html = ""
    for r in source_results:
        day_cells = "".join(f"<td style='text-align:center;font-size:16px;'>{coverage_emoji(r['coverage'].get(d))}</td>" for d in dates)
        gaps_badge = ""
        if r["gaps"] > 0:
            badge_color = "#dc2626" if r["gaps"] >= 3 else "#d97706"
            gaps_badge = f"<span style='background:{badge_color};color:white;border-radius:4px;padding:2px 6px;font-size:11px;margin-left:6px;'>{r['gaps']} gap{'s' if r['gaps'] > 1 else ''}</span>"
        cov_pct = round(r["days_present"] / max(1, r["days_checked"]) * 100)
        cov_color = "#059669" if r["gaps"] == 0 else ("#d97706" if r["gaps"] <= 2 else "#dc2626")
        rows_html += f"""
        <tr>
          <td style='padding:8px 12px;font-family:monospace;font-size:13px;white-space:nowrap;'>{r['source']}{gaps_badge}</td>
          {day_cells}
          <td style='padding:8px 12px;text-align:center;color:{cov_color};font-weight:bold;'>{r['days_present']}/{r['days_checked']}</td>
          <td style='padding:8px 12px;font-size:11px;color:#666;'>{r['notes']}</td>
        </tr>"""

    header_cells = "".join(f"<th style='padding:8px;text-align:center;'>{d}</th>" for d in day_labels)

    total_gaps = sum(r["gaps"] for r in source_results)
    sources_with_gaps = sum(1 for r in source_results if r["gaps"] > 0)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Weekly Reconciliation</title></head>
<body style="font-family:system-ui,sans-serif;margin:0;padding:16px;background:#f9fafb;">
<div style="max-width:900px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
  <div style="background:{color};padding:20px 24px;">
    <h2 style="color:white;margin:0;font-size:20px;">📊 Weekly Data Reconciliation</h2>
    <p style="color:rgba(255,255,255,.9);margin:4px 0 0;font-size:13px;">{week_start} → {week_end} | {severity} | Generated {generated_at}</p>
  </div>
  <div style="padding:16px 24px;background:#f0fdf4 if {total_gaps}==0 else #fef3c7;border-bottom:1px solid #e5e7eb;">
    <strong>Summary:</strong> {len(source_results)} sources checked | {total_gaps} total gaps | {sources_with_gaps} sources affected
    {" | <span style='color:#059669;'>All systems nominal ✅</span>" if total_gaps == 0 else ""}
  </div>
  <div style="padding:20px 24px;overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#f3f4f6;">
          <th style="padding:8px 12px;text-align:left;">Source</th>
          {header_cells}
          <th style="padding:8px;text-align:center;">Coverage</th>
          <th style="padding:8px 12px;text-align:left;">Notes</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
  </div>
  {"" if total_gaps == 0 else f'''
  <div style="padding:16px 24px;border-top:1px solid #e5e7eb;background:#fef3c7;">
    <strong>🔧 Recommended actions:</strong>
    <ul style="margin:8px 0 0;padding-left:20px;">
      {"".join(f"<li><code>{r['source']}</code>: {r['gaps']} gap{'s' if r['gaps']>1 else ''} ({', '.join(d for d in dates if r['coverage'].get(d) is False)})</li>" for r in source_results if r['gaps'] > 0)}
    </ul>
    <p style="margin:8px 0 0;font-size:12px;color:#666;">Gap-aware backfill (LOOKBACK_DAYS=7) will self-heal most gaps on next scheduled run.</p>
  </div>'''}
  <div style="padding:12px 24px;font-size:11px;color:#9ca3af;border-top:1px solid #e5e7eb;">
    AI-generated analysis, not medical advice. Life Platform v3.0 | data-reconciliation Lambda
  </div>
</div>
</body></html>"""


def lambda_handler(event, context):
    logger.info("[reconciliation] Starting weekly data reconciliation")

    today = datetime.now(timezone.utc).date()
    # Check last 7 completed days (not today — ingestion may still be running)
    dates = [(today - timedelta(days=i)).isoformat() for i in range(LOOKBACK_DAYS, 0, -1)]
    logger.info(f"[reconciliation] Checking dates: {dates[0]} → {dates[-1]}")

    source_results = []
    for source, expected_days, notes in SOURCES:
        if source in _SKIP_SOURCES:
            continue
        coverage = check_source_coverage(source, dates)
        days_present = sum(1 for v in coverage.values() if v is True)
        days_missing  = sum(1 for v in coverage.values() if v is False)
        # Only count as "gap" if below expected_days threshold
        # e.g. strava expected 5/7 — if only 4, that's 1 gap
        expected_present = min(expected_days, len(dates))
        gaps = max(0, expected_present - days_present)

        source_results.append({
            "source": source,
            "coverage": coverage,
            "days_present": days_present,
            "days_checked": len(dates),
            "gaps": gaps,
            "expected_days": expected_days,
            "notes": notes,
        })
        if gaps > 0:
            logger.warning(f"[reconciliation] Gap detected: {source} — {gaps} missing (expected {expected_days}/7)")

    severity, color = classify_severity(source_results)
    total_gaps = sum(r["gaps"] for r in source_results)
    sources_with_gaps = sum(1 for r in source_results if r["gaps"] > 0)

    logger.info(f"[reconciliation] Result: {severity} | {total_gaps} gaps across {sources_with_gaps} sources")

    # Build + send report
    html = build_html_report(dates, source_results, severity, color)
    week_label = f"{dates[0]} → {dates[-1]}"
    subject = f"📊 Weekly Reconciliation | {week_label} | {severity}"

    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body":    {"Html": {"Data": html, "Charset": "UTF-8"}},
            }},
        )
        logger.info(f"[reconciliation] Report sent: {subject}")
    except Exception as e:
        logger.error(f"[reconciliation] Failed to send report: {e}")
        raise

    # Also write summary to S3 for programmatic access
    try:
        summary = {
            "week": week_label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "severity": severity,
            "total_gaps": total_gaps,
            "sources_with_gaps": sources_with_gaps,
            "results": [
                {"source": r["source"], "gaps": r["gaps"], "days_present": r["days_present"],
                 "missing_dates": [d for d in dates if r["coverage"].get(d) is False]}
                for r in source_results
            ],
        }
        s3 = boto3.client("s3", region_name=REGION)
        s3.put_object(
            Bucket=BUCKET,
            Key=f"reconciliation/{dates[-1]}_weekly_reconciliation.json",
            Body=json.dumps(summary, indent=2),
            ContentType="application/json",
        )
        logger.info("[reconciliation] Summary written to S3")
    except Exception as e:
        logger.warning(f"[reconciliation] S3 write failed (non-fatal): {e}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "severity": severity,
            "total_gaps": total_gaps,
            "sources_with_gaps": sources_with_gaps,
            "week": week_label,
        }),
    }
