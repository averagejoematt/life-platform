#!/usr/bin/env bash
# deploy/create_operational_dashboard.sh
#
# Creates the Life Platform CloudWatch operational dashboard.
# Single pane of glass: ingestion health, Lambda errors, DLQ, compute pipeline,
# freshness metrics, MCP latency, and alarm summary.
#
# USAGE:
#   bash deploy/create_operational_dashboard.sh
#
# After creation: view at
#   https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#dashboards/dashboard/life-platform-ops
#
# v1.0.0 — 2026-03-15 (item 10 of 11 unblocked tasks)

set -euo pipefail

REGION="us-west-2"
DASHBOARD_NAME="life-platform-ops"

echo "══════════════════════════════════════════════════════"
echo "  Creating CloudWatch Operational Dashboard"
echo "  Name: ${DASHBOARD_NAME}"
echo "  Region: ${REGION}"
echo "══════════════════════════════════════════════════════"
echo ""

DASHBOARD_BODY='{
  "widgets": [
    {
      "type": "text",
      "x": 0, "y": 0, "width": 24, "height": 1,
      "properties": {
        "markdown": "## Life Platform — Operational Dashboard | [Alarms](https://us-west-2.console.aws.amazon.com/cloudwatch/home#alarmsV2:) | [Logs](https://us-west-2.console.aws.amazon.com/cloudwatch/home#logsV2:log-groups)"
      }
    },

    {
      "type": "alarm",
      "x": 0, "y": 1, "width": 24, "height": 3,
      "properties": {
        "title": "Alarm Status — All Life Platform Alarms",
        "alarms": [
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:ingestion-error-whoop",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:ingestion-error-withings",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:ingestion-error-strava",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:ingestion-error-todoist",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:ingestion-error-eightsleep",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:ingestion-error-macrofactor",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:ingestion-error-apple-health",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:garmin-ingestion-errors",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:habitify-ingestion-errors",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:life-platform-daily-brief-errors",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:life-platform-mcp-errors",
          "arn:aws:cloudwatch:us-west-2:205930651321:alarm:life-platform-compute-pipeline-stale"
        ]
      }
    },

    {
      "type": "metric",
      "x": 0, "y": 4, "width": 8, "height": 6,
      "properties": {
        "title": "Ingestion Lambda Errors (24h)",
        "view": "timeSeries",
        "stacked": false,
        "period": 3600,
        "stat": "Sum",
        "region": "us-west-2",
        "metrics": [
          ["AWS/Lambda", "Errors", "FunctionName", "whoop-data-ingestion", {"label": "Whoop", "color": "#e84040"}],
          ["AWS/Lambda", "Errors", "FunctionName", "garmin-data-ingestion", {"label": "Garmin", "color": "#e84040"}],
          ["AWS/Lambda", "Errors", "FunctionName", "strava-data-ingestion", {"label": "Strava", "color": "#e88440"}],
          ["AWS/Lambda", "Errors", "FunctionName", "withings-data-ingestion", {"label": "Withings", "color": "#e88440"}],
          ["AWS/Lambda", "Errors", "FunctionName", "macrofactor-data-ingestion", {"label": "MacroFactor", "color": "#d4c020"}],
          ["AWS/Lambda", "Errors", "FunctionName", "eightsleep-data-ingestion", {"label": "8Sleep", "color": "#8040e8"}],
          ["AWS/Lambda", "Errors", "FunctionName", "todoist-data-ingestion", {"label": "Todoist", "color": "#4080e8"}],
          ["AWS/Lambda", "Errors", "FunctionName", "apple-health-ingestion", {"label": "AppleHealth", "color": "#40c840"}]
        ],
        "yAxis": {"left": {"min": 0}},
        "annotations": {"horizontal": [{"value": 1, "color": "#e84040", "label": "Error threshold"}]}
      }
    },

    {
      "type": "metric",
      "x": 8, "y": 4, "width": 8, "height": 6,
      "properties": {
        "title": "Compute + Email Lambda Errors (24h)",
        "view": "timeSeries",
        "stacked": false,
        "period": 3600,
        "stat": "Sum",
        "region": "us-west-2",
        "metrics": [
          ["AWS/Lambda", "Errors", "FunctionName", "daily-brief", {"label": "Daily Brief", "color": "#e84040"}],
          ["AWS/Lambda", "Errors", "FunctionName", "daily-metrics-compute", {"label": "Daily Metrics", "color": "#e88440"}],
          ["AWS/Lambda", "Errors", "FunctionName", "character-sheet-compute", {"label": "Character Sheet", "color": "#d4c020"}],
          ["AWS/Lambda", "Errors", "FunctionName", "daily-insight-compute", {"label": "Daily Insight", "color": "#8040e8"}],
          ["AWS/Lambda", "Errors", "FunctionName", "hypothesis-engine", {"label": "Hypothesis", "color": "#4080e8"}],
          ["AWS/Lambda", "Errors", "FunctionName", "weekly-digest", {"label": "Weekly Digest", "color": "#40c840"}]
        ],
        "yAxis": {"left": {"min": 0}}
      }
    },

    {
      "type": "metric",
      "x": 16, "y": 4, "width": 8, "height": 6,
      "properties": {
        "title": "MCP + Operational Lambda Errors (24h)",
        "view": "timeSeries",
        "stacked": false,
        "period": 3600,
        "stat": "Sum",
        "region": "us-west-2",
        "metrics": [
          ["AWS/Lambda", "Errors", "FunctionName", "life-platform-mcp", {"label": "MCP", "color": "#e84040"}],
          ["AWS/Lambda", "Errors", "FunctionName", "life-platform-freshness-checker", {"label": "Freshness", "color": "#e88440"}],
          ["AWS/Lambda", "Errors", "FunctionName", "life-platform-canary", {"label": "Canary", "color": "#d4c020"}],
          ["AWS/Lambda", "Errors", "FunctionName", "anomaly-detector", {"label": "Anomaly", "color": "#8040e8"}],
          ["AWS/Lambda", "Errors", "FunctionName", "dlq-consumer", {"label": "DLQ Consumer", "color": "#4080e8"}],
          ["AWS/Lambda", "Errors", "FunctionName", "dashboard-refresh", {"label": "Dash Refresh", "color": "#40c840"}]
        ],
        "yAxis": {"left": {"min": 0}}
      }
    },

    {
      "type": "metric",
      "x": 0, "y": 10, "width": 8, "height": 6,
      "properties": {
        "title": "SQS DLQ Depth",
        "view": "timeSeries",
        "stacked": false,
        "period": 300,
        "stat": "Maximum",
        "region": "us-west-2",
        "metrics": [
          ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", "life-platform-ingestion-dlq",
           {"label": "DLQ Visible", "color": "#e84040"}],
          ["AWS/SQS", "ApproximateNumberOfMessagesNotVisible", "QueueName", "life-platform-ingestion-dlq",
           {"label": "DLQ In-flight", "color": "#e88440"}]
        ],
        "yAxis": {"left": {"min": 0}},
        "annotations": {"horizontal": [{"value": 1, "color": "#e84040", "label": "Any message = failure"}]}
      }
    },

    {
      "type": "metric",
      "x": 8, "y": 10, "width": 8, "height": 6,
      "properties": {
        "title": "Data Freshness — Source Status",
        "view": "timeSeries",
        "stacked": false,
        "period": 3600,
        "stat": "Maximum",
        "region": "us-west-2",
        "metrics": [
          ["LifePlatform/Freshness", "StaleSourceCount", {"label": "Stale Sources", "color": "#e84040"}],
          ["LifePlatform/Freshness", "FreshSourceCount", {"label": "Fresh Sources", "color": "#40c840"}],
          ["LifePlatform/Freshness", "PartialCompletenessCount", {"label": "Partial Records", "color": "#e88440"}],
          ["LifePlatform/Freshness", "OAuthTokenStaleCount", {"label": "OAuth Stale", "color": "#d4c020"}]
        ],
        "yAxis": {"left": {"min": 0, "max": 12}}
      }
    },

    {
      "type": "metric",
      "x": 16, "y": 10, "width": 8, "height": 6,
      "properties": {
        "title": "Compute Pipeline Staleness",
        "view": "timeSeries",
        "stacked": false,
        "period": 3600,
        "stat": "Maximum",
        "region": "us-west-2",
        "metrics": [
          ["LifePlatform/DailyBrief", "ComputePipelineStaleness",
           {"label": "Pipeline Staleness (hours)", "color": "#e84040"}]
        ],
        "yAxis": {"left": {"min": 0}},
        "annotations": {"horizontal": [
          {"value": 4, "color": "#e88440", "label": "Warning (4h)"},
          {"value": 6, "color": "#e84040", "label": "Critical (6h)"}
        ]}
      }
    },

    {
      "type": "metric",
      "x": 0, "y": 16, "width": 12, "height": 6,
      "properties": {
        "title": "MCP Lambda — Duration + Invocations (24h)",
        "view": "timeSeries",
        "stacked": false,
        "period": 300,
        "stat": "p99",
        "region": "us-west-2",
        "metrics": [
          ["AWS/Lambda", "Duration", "FunctionName", "life-platform-mcp",
           {"label": "MCP p99 Duration (ms)", "color": "#4080e8", "stat": "p99"}],
          ["AWS/Lambda", "Duration", "FunctionName", "life-platform-mcp",
           {"label": "MCP p50 Duration (ms)", "color": "#8040e8", "stat": "p50"}]
        ],
        "yAxis": {"left": {"min": 0}},
        "annotations": {"horizontal": [{"value": 800, "color": "#d4c020", "label": "Cold start ceiling (800ms)"}]}
      }
    },

    {
      "type": "metric",
      "x": 12, "y": 16, "width": 12, "height": 6,
      "properties": {
        "title": "Lambda Invocations — Ingestion Layer (24h)",
        "view": "timeSeries",
        "stacked": true,
        "period": 3600,
        "stat": "Sum",
        "region": "us-west-2",
        "metrics": [
          ["AWS/Lambda", "Invocations", "FunctionName", "whoop-data-ingestion", {"label": "Whoop"}],
          ["AWS/Lambda", "Invocations", "FunctionName", "garmin-data-ingestion", {"label": "Garmin"}],
          ["AWS/Lambda", "Invocations", "FunctionName", "strava-data-ingestion", {"label": "Strava"}],
          ["AWS/Lambda", "Invocations", "FunctionName", "macrofactor-data-ingestion", {"label": "MacroFactor"}],
          ["AWS/Lambda", "Invocations", "FunctionName", "eightsleep-data-ingestion", {"label": "8Sleep"}],
          ["AWS/Lambda", "Invocations", "FunctionName", "habitify-data-ingestion", {"label": "Habitify"}],
          ["AWS/Lambda", "Invocations", "FunctionName", "todoist-data-ingestion", {"label": "Todoist"}],
          ["AWS/Lambda", "Invocations", "FunctionName", "life-platform-freshness-checker", {"label": "Freshness"}]
        ],
        "yAxis": {"left": {"min": 0}}
      }
    },

    {
      "type": "metric",
      "x": 0, "y": 22, "width": 12, "height": 6,
      "properties": {
        "title": "DynamoDB — Consumed RCU + WCU (24h)",
        "view": "timeSeries",
        "stacked": false,
        "period": 3600,
        "stat": "Sum",
        "region": "us-west-2",
        "metrics": [
          ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", "life-platform",
           {"label": "Read CU", "color": "#4080e8"}],
          ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", "life-platform",
           {"label": "Write CU", "color": "#e88440"}]
        ],
        "yAxis": {"left": {"min": 0}}
      }
    },

    {
      "type": "metric",
      "x": 12, "y": 22, "width": 12, "height": 6,
      "properties": {
        "title": "DynamoDB — Throttles + System Errors (24h)",
        "view": "timeSeries",
        "stacked": false,
        "period": 3600,
        "stat": "Sum",
        "region": "us-west-2",
        "metrics": [
          ["AWS/DynamoDB", "ReadThrottleEvents", "TableName", "life-platform",
           {"label": "Read Throttles", "color": "#e84040"}],
          ["AWS/DynamoDB", "WriteThrottleEvents", "TableName", "life-platform",
           {"label": "Write Throttles", "color": "#e88440"}],
          ["AWS/DynamoDB", "SystemErrors", "TableName", "life-platform",
           {"label": "System Errors", "color": "#8040e8"}]
        ],
        "yAxis": {"left": {"min": 0}},
        "annotations": {"horizontal": [{"value": 1, "color": "#e84040", "label": "Any throttle = concern"}]}
      }
    }
  ]
}'

echo "Uploading dashboard to CloudWatch..."
aws cloudwatch put-dashboard \
    --dashboard-name "$DASHBOARD_NAME" \
    --dashboard-body "$DASHBOARD_BODY" \
    --region "$REGION"

echo ""
echo "══════════════════════════════════════════════════════"
echo "  ✅ Dashboard created: ${DASHBOARD_NAME}"
echo ""
echo "  URL: https://${REGION}.console.aws.amazon.com/cloudwatch/home"
echo "       ?region=${REGION}#dashboards/dashboard/${DASHBOARD_NAME}"
echo ""
echo "  Widgets:"
echo "   Row 1: Alarm overview strip (12 key alarms)"
echo "   Row 2: Ingestion errors | Compute errors | MCP/Ops errors"
echo "   Row 3: DLQ depth | Freshness metrics | Pipeline staleness"
echo "   Row 4: MCP duration (p50/p99) | Invocations stacked"
echo "   Row 5: DynamoDB RCU/WCU | Throttles + system errors"
echo "══════════════════════════════════════════════════════"
