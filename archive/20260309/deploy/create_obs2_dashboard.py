#!/usr/bin/env python3
"""
create_obs2_dashboard.py — OBS-2: CloudWatch Operational Health Dashboard
Creates the 'life-platform-ops' dashboard with:
  - Top-level KPIs (DLQ depth, error count, invocations, API GW errors)
  - Alarm status grid (all platform alarms)
  - DLQ + error time series
  - Ingestion Lambda health (invocations + errors)
  - Email/compute Lambda health
  - MCP + DynamoDB throughput
  - AI token tracking placeholder (populated by COST-3)

Usage:
  python3 deploy/create_obs2_dashboard.py [--dry-run]

Requirements:
  AWS CLI configured, region us-west-2
"""

import json
import subprocess
import sys
import argparse

REGION = "us-west-2"
ACCOUNT = "205930651321"
DASHBOARD_NAME = "life-platform-ops"

# ── Lambda catalogue ───────────────────────────────────────────────────────────

INGESTION_LAMBDAS = [
    "whoop-data-ingestion",
    "eightsleep-data-ingestion",
    "garmin-data-ingestion",
    "strava-data-ingestion",
    "withings-data-ingestion",
    "habitify-data-ingestion",
    "macrofactor-data-ingestion",
    "notion-journal-ingestion",
    "todoist-data-ingestion",
    "weather-data-ingestion",
    "health-auto-export-webhook",
    "journal-enrichment",
    "activity-enrichment",
]

EMAIL_COMPUTE_LAMBDAS = [
    "daily-brief",
    "weekly-digest",
    "monthly-digest",
    "nutrition-review",
    "wednesday-chronicle",
    "weekly-plate",
    "monday-compass",
    "anomaly-detector",
    "character-sheet-compute",
    "adaptive-mode-compute",
    "daily-metrics-compute",
    "daily-insight-compute",
    "hypothesis-engine",
]

INFRA_LAMBDAS = [
    "life-platform-mcp",
    "dashboard-refresh",
    "life-platform-freshness-checker",
    "dropbox-poll",
    "life-platform-key-rotator",
    "life-platform-qa-smoke",
    "life-platform-data-export",
    "insight-email-parser",
]

ALL_LAMBDAS = INGESTION_LAMBDAS + EMAIL_COMPUTE_LAMBDAS + INFRA_LAMBDAS


# ── Alarm discovery ────────────────────────────────────────────────────────────

def get_alarm_arns():
    """Fetch all CloudWatch alarms and return their ARNs."""
    result = subprocess.run(
        ["aws", "cloudwatch", "describe-alarms",
         "--region", REGION,
         "--query", "MetricAlarms[].AlarmArn",
         "--output", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"WARNING: Could not fetch alarms: {result.stderr.strip()}")
        return []
    try:
        arns = json.loads(result.stdout)
        print(f"  Found {len(arns)} CloudWatch alarms")
        return sorted(arns)
    except json.JSONDecodeError:
        print("WARNING: Could not parse alarm ARNs")
        return []


# ── Widget builders ────────────────────────────────────────────────────────────

def text_widget(markdown, x, y, w, h):
    return {
        "type": "text", "x": x, "y": y, "width": w, "height": h,
        "properties": {"markdown": markdown}
    }


def metric_widget(title, metrics, x, y, w, h,
                  view="timeSeries", stat="Sum",
                  period=86400, stacked=False):
    return {
        "type": "metric", "x": x, "y": y, "width": w, "height": h,
        "properties": {
            "title": title,
            "view": view,
            "stacked": stacked,
            "metrics": metrics,
            "period": period,
            "stat": stat,
            "region": REGION,
        }
    }


def single_value_widget(title, metrics, x, y, w=6, h=3, stat="Maximum", period=300):
    return metric_widget(title, metrics, x, y, w, h,
                         view="singleValue", stat=stat, period=period)


def alarm_widget(title, alarm_arns, x, y, w=24, h=6):
    return {
        "type": "alarm", "x": x, "y": y, "width": w, "height": h,
        "properties": {"title": title, "alarms": alarm_arns}
    }


def lambda_error_metrics(lambdas, color_start=0):
    colors = [
        "#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        "#aec7e8", "#ffbb78", "#98df8a",
    ]
    return [
        ["AWS/Lambda", "Errors", "FunctionName", fn,
         {"label": fn, "color": colors[(i + color_start) % len(colors)]}]
        for i, fn in enumerate(lambdas)
    ]


def lambda_invocation_metrics(lambdas):
    return [
        ["AWS/Lambda", "Invocations", "FunctionName", fn, {"label": fn}]
        for fn in lambdas
    ]


# ── Dashboard builder ──────────────────────────────────────────────────────────

def build_dashboard(alarm_arns):
    widgets = []
    y = 0

    # Header
    widgets.append(text_widget(
        "# 🏥 Life Platform — Operational Health\n"
        "**35 Lambdas · 144 MCP tools · 19 data sources**  "
        "| [Alarms](https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#alarmsV2:) "
        "| [DLQ](https://us-west-2.console.aws.amazon.com/sqs/v3/home?region=us-west-2#/queues) "
        "| [Logs](https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#logsV2:log-groups)",
        x=0, y=y, w=24, h=2,
    ))
    y += 2

    # KPI row
    widgets.append(single_value_widget(
        "DLQ Depth",
        [["AWS/SQS", "ApproximateNumberOfMessagesVisible",
          "QueueName", "life-platform-ingestion-dlq",
          {"label": "Messages", "color": "#d62728"}]],
        x=0, y=y, w=6, h=3, stat="Maximum", period=300,
    ))
    widgets.append(single_value_widget(
        "Lambda Errors (24h)",
        [["AWS/Lambda", "Errors", {"label": "All Errors", "color": "#d62728"}]],
        x=6, y=y, w=6, h=3, stat="Sum", period=86400,
    ))
    widgets.append(single_value_widget(
        "Lambda Invocations (24h)",
        [["AWS/Lambda", "Invocations", {"label": "Total"}]],
        x=12, y=y, w=6, h=3, stat="Sum", period=86400,
    ))
    widgets.append(single_value_widget(
        "API GW 5xx (24h)",
        [["AWS/ApiGateway", "5XXError", "ApiName", "health-auto-export-api",
          {"label": "5XX", "color": "#d62728"}]],
        x=18, y=y, w=6, h=3, stat="Sum", period=86400,
    ))
    y += 3

    # Alarm status
    if alarm_arns:
        widgets.append(alarm_widget("Platform Alarms", alarm_arns, x=0, y=y, w=24, h=7))
    else:
        widgets.append(text_widget(
            "⚠️ **No alarm ARNs found** — re-run after CloudWatch alarms are configured.",
            x=0, y=y, w=24, h=2,
        ))
    y += 7

    # DLQ + error time series
    widgets.append(metric_widget(
        "DLQ Depth — 7d",
        [["AWS/SQS", "ApproximateNumberOfMessagesVisible",
          "QueueName", "life-platform-ingestion-dlq", {"label": "Visible", "color": "#d62728"}],
         ["AWS/SQS", "ApproximateNumberOfMessagesNotVisible",
          "QueueName", "life-platform-ingestion-dlq", {"label": "In-flight", "color": "#ff7f0e"}]],
        x=0, y=y, w=12, h=6, stat="Maximum", period=3600,
    ))
    widgets.append(metric_widget(
        "Ingestion Errors — 7d",
        lambda_error_metrics(INGESTION_LAMBDAS),
        x=12, y=y, w=12, h=6, stat="Sum", period=3600,
    ))
    y += 6

    # Ingestion Lambda health
    widgets.append(text_widget(
        "## 📥 Ingestion (13 Lambdas)",
        x=0, y=y, w=24, h=1,
    ))
    y += 1
    widgets.append(metric_widget(
        "Ingestion — Invocations (7d)",
        lambda_invocation_metrics(INGESTION_LAMBDAS),
        x=0, y=y, w=12, h=6, stat="Sum", period=86400,
    ))
    widgets.append(metric_widget(
        "Ingestion — Errors (7d)",
        lambda_error_metrics(INGESTION_LAMBDAS),
        x=12, y=y, w=12, h=6, stat="Sum", period=86400,
    ))
    y += 6

    # Email / Compute Lambda health
    widgets.append(text_widget(
        "## 📬 Email & Compute (13 Lambdas)",
        x=0, y=y, w=24, h=1,
    ))
    y += 1
    widgets.append(metric_widget(
        "Email/Compute — Invocations (30d)",
        lambda_invocation_metrics(EMAIL_COMPUTE_LAMBDAS),
        x=0, y=y, w=12, h=6, stat="Sum", period=86400,
    ))
    widgets.append(metric_widget(
        "Email/Compute — Duration ms (30d)",
        [["AWS/Lambda", "Duration", "FunctionName", fn, {"label": fn}]
         for fn in ["daily-brief", "weekly-digest", "wednesday-chronicle",
                    "character-sheet-compute", "daily-metrics-compute",
                    "daily-insight-compute"]],
        x=12, y=y, w=12, h=6, stat="Average", period=86400,
    ))
    y += 6

    # Infrastructure — MCP + DDB
    widgets.append(text_widget("## ⚙️ Infrastructure", x=0, y=y, w=24, h=1))
    y += 1
    widgets.append(metric_widget(
        "MCP Lambda — Invocations (7d)",
        [["AWS/Lambda", "Invocations", "FunctionName", "life-platform-mcp", {"label": "Invocations"}],
         ["AWS/Lambda", "Errors", "FunctionName", "life-platform-mcp",
          {"label": "Errors", "color": "#d62728"}]],
        x=0, y=y, w=12, h=6, stat="Sum", period=3600,
    ))
    widgets.append(metric_widget(
        "DynamoDB Consumed Capacity (7d)",
        [["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", "life-platform",
          {"label": "Write CU", "color": "#1f77b4"}],
         ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", "life-platform",
          {"label": "Read CU", "color": "#ff7f0e"}]],
        x=12, y=y, w=12, h=6, stat="Sum", period=3600,
    ))
    y += 6

    # API Gateway + Throttles
    widgets.append(metric_widget(
        "API Gateway — Requests & Errors (7d)",
        [["AWS/ApiGateway", "Count", "ApiName", "health-auto-export-api", {"label": "Requests"}],
         ["AWS/ApiGateway", "5XXError", "ApiName", "health-auto-export-api",
          {"label": "5XX", "color": "#d62728"}],
         ["AWS/ApiGateway", "4XXError", "ApiName", "health-auto-export-api",
          {"label": "4XX", "color": "#ff7f0e"}]],
        x=0, y=y, w=12, h=6, stat="Sum", period=3600,
    ))
    widgets.append(metric_widget(
        "Lambda Throttles — Critical paths (7d)",
        [["AWS/Lambda", "Throttles", "FunctionName", fn, {"label": fn}]
         for fn in ["daily-brief", "life-platform-mcp", "health-auto-export-webhook",
                    "character-sheet-compute", "daily-metrics-compute"]],
        x=12, y=y, w=12, h=6, stat="Sum", period=3600,
    ))
    y += 6

    # AI token tracking placeholder
    widgets.append(text_widget(
        "## 🤖 AI Token Tracking\n"
        "**Placeholder — populated by COST-3.**\n\n"
        "Once COST-3 is deployed, this section shows daily Haiku + Sonnet token usage, "
        "estimated monthly AI cost, and the $15/month alarm threshold.  \n"
        "*Until then: monitor at [console.anthropic.com](https://console.anthropic.com)*",
        x=0, y=y, w=24, h=3,
    ))
    y += 3

    # Full error matrix
    widgets.append(text_widget("## 🔴 All Lambda Errors (24h)", x=0, y=y, w=24, h=1))
    y += 1
    mid = len(ALL_LAMBDAS) // 2
    widgets.append(metric_widget(
        "Lambda Errors — Ingestion + Email (24h)",
        lambda_error_metrics(ALL_LAMBDAS[:mid]),
        x=0, y=y, w=24, h=6, stat="Sum", period=86400,
    ))
    y += 6
    widgets.append(metric_widget(
        "Lambda Errors — Compute + Infrastructure (24h)",
        lambda_error_metrics(ALL_LAMBDAS[mid:], color_start=mid),
        x=0, y=y, w=24, h=6, stat="Sum", period=86400,
    ))

    return {"widgets": widgets}


# ── Deploy ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print dashboard JSON without deploying")
    args = parser.parse_args()

    print(f"OBS-2: Building CloudWatch dashboard '{DASHBOARD_NAME}'...")

    print("  Fetching alarm ARNs...")
    alarm_arns = get_alarm_arns()

    print("  Building dashboard widgets...")
    dashboard = build_dashboard(alarm_arns)
    dashboard_json = json.dumps(dashboard)

    print(f"  Dashboard: {len(dashboard['widgets'])} widgets, {len(dashboard_json):,} bytes")

    if args.dry_run:
        print("\n── Dashboard JSON preview (first 2000 chars) ──")
        print(json.dumps(dashboard, indent=2)[:2000])
        return

    print(f"  Deploying to CloudWatch...")
    result = subprocess.run(
        ["aws", "cloudwatch", "put-dashboard",
         "--region", REGION,
         "--dashboard-name", DASHBOARD_NAME,
         "--dashboard-body", dashboard_json],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        print(f"ERROR: {result.stderr.strip()}")
        sys.exit(1)

    print(f"\n✅  Dashboard '{DASHBOARD_NAME}' live!")
    print(f"\n    https://{REGION}.console.aws.amazon.com/cloudwatch/home?"
          f"region={REGION}#dashboards:name={DASHBOARD_NAME}")


if __name__ == "__main__":
    main()
