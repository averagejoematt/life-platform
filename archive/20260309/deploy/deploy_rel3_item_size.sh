#!/usr/bin/env bash
# deploy_rel3_item_size.sh — REL-3: DynamoDB 400KB Item Size Monitoring
#
# Creates:
#   1. CloudWatch alarm: life-platform-ddb-item-size-warning
#      Fires when any source emits ItemSizeBytes >= 300KB
#   2. Patches strava + macrofactor Lambdas to use item_size_guard.safe_put_item()
#      (item_size_guard.py bundled as extra file in their zips)
#   3. Adds DDB item size widget to OBS-2 dashboard
#
# Usage: bash deploy/deploy_rel3_item_size.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
SNS_ARN="arn:aws:sns:${REGION}:${ACCOUNT}:life-platform-alerts"

info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

cd "$(dirname "$0")/.."  # project root

# ── 1. CloudWatch alarm on ItemSizeBytes ──────────────────────────────────────
info "Creating CloudWatch alarm: ddb-item-size-warning..."

aws cloudwatch put-metric-alarm \
    --alarm-name "life-platform-ddb-item-size-warning" \
    --alarm-description "DynamoDB item size >= 300KB — approaching 400KB limit. Check strava/macrofactor/apple_health sources." \
    --namespace "LifePlatform/DynamoDB" \
    --metric-name "ItemSizeBytes" \
    --statistic Maximum \
    --period 300 \
    --evaluation-periods 1 \
    --threshold 307200 \
    --comparison-operator GreaterThanOrEqualToThreshold \
    --treat-missing-data notBreaching \
    --alarm-actions "$SNS_ARN" \
    --region "$REGION" \
    --no-cli-pager

ok "Alarm: life-platform-ddb-item-size-warning (threshold: 300KB)"

# ── 2. Patch strava Lambda ────────────────────────────────────────────────────
info "Patching strava-data-ingestion with item_size_guard..."
bash deploy/deploy_lambda.sh strava-data-ingestion lambdas/strava_lambda.py \
    --extra-files lambdas/item_size_guard.py
ok "strava-data-ingestion redeployed with item_size_guard"

sleep 10

# ── 3. Patch macrofactor Lambda ───────────────────────────────────────────────
info "Patching macrofactor-data-ingestion with item_size_guard..."
bash deploy/deploy_lambda.sh macrofactor-data-ingestion lambdas/macrofactor_lambda.py \
    --extra-files lambdas/item_size_guard.py
ok "macrofactor-data-ingestion redeployed with item_size_guard"

sleep 10

# ── 4. Patch health-auto-export-webhook (large Apple Health payloads) ─────────
info "Patching health-auto-export-webhook with item_size_guard..."
bash deploy/deploy_lambda.sh health-auto-export-webhook lambdas/health_auto_export_lambda.py \
    --extra-files lambdas/item_size_guard.py
ok "health-auto-export-webhook redeployed with item_size_guard"

# ── 5. Add DDB item size widget to OBS-2 dashboard ───────────────────────────
info "Patching OBS-2 dashboard with DDB item size widget..."

python3 - <<'PYEOF'
import json, subprocess, sys

REGION = "us-west-2"
DASHBOARD_NAME = "life-platform-ops"

result = subprocess.run(
    ["aws", "cloudwatch", "get-dashboard",
     "--dashboard-name", DASHBOARD_NAME,
     "--region", REGION,
     "--query", "DashboardBody",
     "--output", "text"],
    capture_output=True, text=True,
)
if result.returncode != 0:
    print(f"  WARNING: Could not fetch dashboard: {result.stderr.strip()[:80]}")
    sys.exit(0)

try:
    dashboard = json.loads(result.stdout.strip())
except json.JSONDecodeError:
    print("  WARNING: Could not parse dashboard JSON")
    sys.exit(0)

widgets = dashboard.get("widgets", [])

# Find the last widget's Y position to append after
max_y = max((w["y"] + w["height"] for w in widgets), default=0)

# DDB item size section
new_widgets = [
    {
        "type": "text",
        "x": 0, "y": max_y, "width": 24, "height": 1,
        "properties": {"markdown": "## 📦 DynamoDB Item Size (REL-3)"}
    },
    {
        "type": "metric",
        "x": 0, "y": max_y + 1, "width": 12, "height": 6,
        "properties": {
            "title": "Item Size by Source — Max (7d)",
            "view": "timeSeries",
            "metrics": [
                ["LifePlatform/DynamoDB", "ItemSizeBytes", "Source", src,
                 {"label": src}]
                for src in ["strava", "macrofactor", "apple_health",
                            "health_auto_export", "strava_truncated",
                            "macrofactor_truncated"]
            ],
            "period": 3600,
            "stat": "Maximum",
            "region": REGION,
            "annotations": {
                "horizontal": [
                    {"label": "WARN 300KB", "value": 307200, "color": "#ff7f0e"},
                    {"label": "HARD 380KB", "value": 389120, "color": "#d62728"},
                ]
            }
        }
    },
    {
        "type": "alarm",
        "x": 12, "y": max_y + 1, "width": 12, "height": 6,
        "properties": {
            "title": "DDB Item Size Alarm",
            "alarms": [
                f"arn:aws:cloudwatch:{REGION}:205930651321:alarm:life-platform-ddb-item-size-warning"
            ]
        }
    },
]

dashboard["widgets"] = widgets + new_widgets
dashboard_json = json.dumps(dashboard)

patch = subprocess.run(
    ["aws", "cloudwatch", "put-dashboard",
     "--dashboard-name", DASHBOARD_NAME,
     "--dashboard-body", dashboard_json,
     "--region", REGION],
    capture_output=True, text=True,
)
if patch.returncode == 0:
    print("  ✅ OBS-2 dashboard patched with DDB item size widgets")
else:
    print(f"  WARNING: Dashboard patch failed: {patch.stderr.strip()[:80]}")
PYEOF

echo ""
echo "══════════════════════════════════════════════════"
echo "✅  REL-3 Item Size Monitoring deployed!"
echo ""
echo "  Alarm:     life-platform-ddb-item-size-warning (300KB threshold)"
echo "  Metric:    LifePlatform/DynamoDB / ItemSizeBytes (per source)"
echo "  Lambdas:   strava, macrofactor, health-auto-export-webhook patched"
echo ""
echo "  Behaviour at runtime:"
echo "    < 300KB  → normal put_item, no overhead"
echo "    300-380KB → put_item + CW warning metric + log warning"
echo "    >= 380KB → truncate largest list field + put_item + CW metric"
echo "══════════════════════════════════════════════════"
