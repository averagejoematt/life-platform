#!/bin/bash
# Deploy Data Completeness Alerting v2
# Upgrades freshness checker: per-source thresholds, SES HTML email, impact mapping
# Run: bash deploy_completeness_alerting.sh

set -e

FUNCTION_NAME="life-platform-freshness-checker"
ROLE_NAME="lambda-freshness-checker-role"
REGION="us-west-2"
ACCOUNT="205930651321"

echo "══════════════════════════════════════════════════════════════"
echo "  Data Completeness Alerting v2 — Deploy"
echo "══════════════════════════════════════════════════════════════"

# ── Step 1: Add SES permission to IAM role ───────────────────────────────────
echo ""
echo "Step 1: Updating IAM role with SES permission..."

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name freshness-checker-permissions \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DynamoDBRead",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": "arn:aws:dynamodb:us-west-2:'"$ACCOUNT"':table/life-platform"
            },
            {
                "Sid": "SNSPublish",
                "Effect": "Allow",
                "Action": ["sns:Publish"],
                "Resource": "arn:aws:sns:us-west-2:'"$ACCOUNT"':life-platform-alerts"
            },
            {
                "Sid": "SESEmail",
                "Effect": "Allow",
                "Action": ["ses:SendEmail"],
                "Resource": "arn:aws:ses:us-west-2:'"$ACCOUNT"':identity/mattsusername.com"
            },
            {
                "Sid": "Logs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": "arn:aws:logs:us-west-2:'"$ACCOUNT"':log-group:/aws/lambda/life-platform-freshness-checker:*"
            }
        ]
    }'

echo "  ✅ IAM role updated with SES permission"

# ── Step 2: Build Lambda package ─────────────────────────────────────────────
echo ""
echo "Step 2: Building Lambda package..."

rm -rf /tmp/freshness_build
mkdir -p /tmp/freshness_build

cat > /tmp/freshness_build/lambda_function.py << 'PYTHON'
"""
Data Completeness Alerting v2
Monitors all automated data sources for gaps that could corrupt trend analysis.

Improvements over v1:
- All 11 automated sources monitored (was 8)
- Per-source staleness thresholds (daily=48h, activity=72h, workout=96h)
- HTML email via SES with severity levels and impact assessment
- Impact mapping: shows which tools/analyses are degraded per gap
- SNS escalation when 3+ sources stale (likely infrastructure issue)
- Only emails when gaps detected (no daily noise)

Schedule: 8:15 AM PT daily (after all ingestion completes)
"""

import json
import boto3
import os
from datetime import datetime, timezone, timedelta

dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
ses = boto3.client('ses', region_name='us-west-2')
sns = boto3.client('sns', region_name='us-west-2')

TABLE = os.environ.get('TABLE_NAME', 'life-platform')
SNS_ARN = os.environ.get('SNS_ARN', 'arn:aws:sns:us-west-2:205930651321:life-platform-alerts')
SENDER = os.environ.get('SENDER', 'awsdev@mattsusername.com')
RECIPIENT = os.environ.get('RECIPIENT', 'awsdev@mattsusername.com')
USER = 'matthew'

# ── Source configuration ─────────────────────────────────────────────────────
# Each source has: display name, staleness threshold (hours), severity, impacted tools
SOURCES = {
    # Daily automated sources — 48h threshold
    'whoop': {
        'name': 'Whoop',
        'description': 'Recovery, HRV, strain, sleep',
        'stale_hours': 48,
        'impacts': [
            'get_readiness_score (recovery component)',
            'get_alcohol_sleep_correlation (next-day recovery)',
            'anomaly-detector (HRV, recovery metrics)',
            'daily brief (recovery signal)',
        ],
    },
    'withings': {
        'name': 'Withings',
        'description': 'Weight & body composition',
        'stale_hours': 48,
        'impacts': [
            'get_field_stats (weight trends)',
            'anomaly-detector (weight metric)',
            'daily brief (weight tracking)',
            'weekly/monthly digest (body metrics)',
        ],
    },
    'todoist': {
        'name': 'Todoist',
        'description': 'Task completion',
        'stale_hours': 48,
        'impacts': [
            'get_field_stats (productivity)',
            'daily brief (task summary)',
        ],
    },
    'apple_health': {
        'name': 'Apple Health',
        'description': 'Steps, calories, resting HR, HRV (manual export)',
        'stale_hours': 504,       # 21 days = WARNING (monthly manual export)
        'critical_hours': 720,    # 30 days = CRITICAL
        'impacts': [
            'get_field_stats (steps, active calories)',
            'anomaly-detector (resting HR)',
            'daily brief (step count)',
        ],
    },
    'eightsleep': {
        'name': 'Eight Sleep',
        'description': 'Sleep staging, HRV, efficiency',
        'stale_hours': 48,
        'impacts': [
            'get_sleep_analysis',
            'get_readiness_score (sleep component)',
            'get_exercise_sleep_correlation',
            'get_caffeine_sleep_correlation',
            'get_alcohol_sleep_correlation (same-night sleep)',
            'anomaly-detector (sleep metrics)',
            'daily brief (sleep signal)',
        ],
    },
    'habitify': {
        'name': 'Habitify',
        'description': 'P40 habits & mood',
        'stale_hours': 48,
        'impacts': [
            'get_habit_adherence',
            'get_habit_streaks',
            'get_keystone_habits',
            'get_habit_health_correlations',
            'get_habit_dashboard',
            'daily brief (habit completion)',
        ],
    },

    # Activity sources — 72h threshold (may skip days)
    'strava': {
        'name': 'Strava',
        'description': 'Activities (cardio, strength)',
        'stale_hours': 72,
        'impacts': [
            'search_activities',
            'get_exercise_sleep_correlation',
            'get_zone2_breakdown',
            'get_readiness_score (training load)',
            'anomaly-detector (training metrics)',
        ],
    },
    'garmin': {
        'name': 'Garmin',
        'description': 'Body Battery, HR zones, training effect',
        'stale_hours': 72,
        'impacts': [
            'get_garmin_summary',
            'get_device_agreement',
            'get_readiness_score (Body Battery component)',
        ],
    },

    # Hevy excluded — deprecated, historical backfill only (use MacroFactor workouts)

    # Manual upload sources — 72h threshold
    'macrofactor': {
        'name': 'MacroFactor',
        'description': 'Nutrition (calories, macros, food log)',
        'stale_hours': 72,
        'impacts': [
            'get_nutrition_summary',
            'get_macro_targets',
            'get_food_log',
            'get_micronutrient_report',
            'get_meal_timing',
            'get_caffeine_sleep_correlation',
            'get_alcohol_sleep_correlation (alcohol dose)',
            'daily brief (nutrition signal)',
        ],
    },
}

# Sources excluded from monitoring (periodic/manual, not daily):
# - labs: quarterly blood draws
# - genome: one-time seed
# - dexa: semi-annual
# - chronicling: archived

SNS_ESCALATION_THRESHOLD = 3  # 3+ stale sources triggers SNS (infrastructure concern)


def lambda_handler(event, context):
    table = dynamodb.Table(TABLE)
    now = datetime.now(timezone.utc)

    results = []

    for source_key, config in SOURCES.items():
        pk = f'USER#{USER}#SOURCE#{source_key}'
        stale_threshold = now - timedelta(hours=config['stale_hours'])

        response = table.query(
            KeyConditionExpression='pk = :pk',
            ExpressionAttributeValues={':pk': pk},
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression='sk'
        )

        items = response.get('Items', [])

        if not items:
            results.append({
                'source': source_key,
                'config': config,
                'status': 'NO_DATA',
                'last_date': None,
                'gap_hours': None,
                'severity': 'CRITICAL',
            })
            continue

        sk = items[0]['sk']
        # Handle composite SKs like DATE#2026-02-24#journal#raw
        date_str = sk.replace('DATE#', '').split('#')[0]

        try:
            last_date = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            gap_hours = (now - last_date).total_seconds() / 3600

            if last_date < stale_threshold:
                # Severity: use per-source critical_hours if set, else 2x stale_hours
                critical_hours = config.get('critical_hours', config['stale_hours'] * 2)
                if gap_hours > critical_hours:
                    severity = 'CRITICAL'
                else:
                    severity = 'WARNING'

                results.append({
                    'source': source_key,
                    'config': config,
                    'status': 'STALE',
                    'last_date': date_str,
                    'gap_hours': gap_hours,
                    'severity': severity,
                })
            else:
                results.append({
                    'source': source_key,
                    'config': config,
                    'status': 'FRESH',
                    'last_date': date_str,
                    'gap_hours': gap_hours,
                    'severity': None,
                })
        except ValueError:
            results.append({
                'source': source_key,
                'config': config,
                'status': 'PARSE_ERROR',
                'last_date': date_str,
                'gap_hours': None,
                'severity': 'CRITICAL',
            })

    stale = [r for r in results if r['status'] in ('STALE', 'NO_DATA', 'PARSE_ERROR')]
    fresh = [r for r in results if r['status'] == 'FRESH']
    critical = [r for r in stale if r['severity'] == 'CRITICAL']

    # Log status
    for r in results:
        icon = '✅' if r['status'] == 'FRESH' else ('🔴' if r['severity'] == 'CRITICAL' else '⚠️')
        date_info = r['last_date'] or 'N/A'
        gap_info = f"{r['gap_hours']:.0f}h ago" if r['gap_hours'] else ''
        print(f"  {icon} {r['config']['name']}: {r['status']} — {date_info} {gap_info}")

    # Send alerts only if there are stale sources
    if stale:
        html = build_html_email(results, stale, fresh, critical, now)
        text = build_text_email(results, stale, now)

        try:
            ses.send_email(
                Source=SENDER,
                Destination={'ToAddresses': [RECIPIENT]},
                Message={
                    'Subject': {'Data': build_subject(stale, critical)},
                    'Body': {
                        'Html': {'Data': html},
                        'Text': {'Data': text},
                    },
                },
            )
            print(f"SES email sent: {len(stale)} stale source(s)")
        except Exception as e:
            print(f"SES send failed: {e}")

        # SNS escalation for 3+ stale (infrastructure concern)
        if len(stale) >= SNS_ESCALATION_THRESHOLD:
            try:
                sns.publish(
                    TopicArn=SNS_ARN,
                    Subject=f'🚨 Life Platform: {len(stale)} sources stale — possible infrastructure issue',
                    Message=text,
                )
                print(f"SNS escalation sent: {len(stale)} stale sources")
            except Exception as e:
                print(f"SNS publish failed: {e}")
    else:
        print(f"All {len(fresh)} sources fresh. No alert needed.")

    return {
        'statusCode': 200,
        'total_sources': len(results),
        'fresh_count': len(fresh),
        'stale_count': len(stale),
        'critical_count': len(critical),
        'stale_sources': [r['config']['name'] for r in stale],
        'checked_at': now.isoformat(),
    }


def build_subject(stale, critical):
    if critical:
        return f"🔴 Life Platform: {len(critical)} critical data gap(s)"
    return f"⚠️ Life Platform: {len(stale)} data source(s) stale"


def build_html_email(results, stale, fresh, critical, now):
    # Sort stale by severity (critical first), then by gap hours
    stale_sorted = sorted(stale, key=lambda r: (0 if r['severity'] == 'CRITICAL' else 1, -(r['gap_hours'] or 9999)))

    stale_rows = ''
    for r in stale_sorted:
        severity_color = '#dc2626' if r['severity'] == 'CRITICAL' else '#f59e0b'
        severity_icon = '🔴' if r['severity'] == 'CRITICAL' else '⚠️'
        gap_text = format_gap(r['gap_hours']) if r['gap_hours'] else 'No data'
        threshold_text = f"{r['config']['stale_hours']}h"
        impacts_html = ''.join(f'<li style="margin:2px 0;font-size:13px;color:#6b7280;">{imp}</li>' for imp in r['config']['impacts'])

        stale_rows += f'''
        <tr>
            <td style="padding:12px 16px;border-bottom:1px solid #f3f4f6;">
                <span style="font-size:16px;">{severity_icon}</span>
                <strong style="color:{severity_color};">{r['config']['name']}</strong>
                <div style="font-size:12px;color:#9ca3af;margin-top:2px;">{r['config']['description']}</div>
            </td>
            <td style="padding:12px 16px;border-bottom:1px solid #f3f4f6;text-align:center;">
                <span style="color:{severity_color};font-weight:600;">{gap_text}</span>
                <div style="font-size:11px;color:#9ca3af;">threshold: {threshold_text}</div>
            </td>
            <td style="padding:12px 16px;border-bottom:1px solid #f3f4f6;font-size:12px;color:#9ca3af;">
                {r['last_date'] or 'Never'}
            </td>
        </tr>
        <tr>
            <td colspan="3" style="padding:4px 16px 12px 44px;border-bottom:1px solid #e5e7eb;">
                <div style="font-size:12px;color:#9ca3af;font-weight:600;margin-bottom:2px;">Degraded tools:</div>
                <ul style="margin:0;padding-left:16px;">{impacts_html}</ul>
            </td>
        </tr>'''

    fresh_rows = ''
    for r in sorted(fresh, key=lambda r: r['gap_hours'] or 0):
        gap_text = format_gap(r['gap_hours']) if r['gap_hours'] else ''
        fresh_rows += f'''
        <tr>
            <td style="padding:6px 16px;border-bottom:1px solid #f3f4f6;">
                <span style="font-size:14px;">✅</span> {r['config']['name']}
            </td>
            <td style="padding:6px 16px;border-bottom:1px solid #f3f4f6;text-align:center;color:#6b7280;font-size:13px;">
                {r['last_date']}
            </td>
            <td style="padding:6px 16px;border-bottom:1px solid #f3f4f6;text-align:center;color:#6b7280;font-size:13px;">
                {gap_text}
            </td>
        </tr>'''

    summary_color = '#dc2626' if critical else '#f59e0b'
    summary_text = f"{len(critical)} critical, {len(stale) - len(critical)} warning" if critical else f"{len(stale)} warning"

    pt_time = now - timedelta(hours=8)
    checked_str = pt_time.strftime('%b %d, %Y at %I:%M %p PT')

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:24px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,{summary_color},{'#991b1b' if critical else '#d97706'});border-radius:12px;padding:24px;margin-bottom:24px;">
        <h1 style="margin:0;color:white;font-size:20px;font-weight:600;">
            {'🔴' if critical else '⚠️'} Data Completeness Alert
        </h1>
        <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">
            {summary_text} — {len(fresh)}/{len(results)} sources healthy
        </p>
    </div>

    <!-- Stale Sources -->
    <div style="background:white;border-radius:12px;overflow:hidden;margin-bottom:24px;border:1px solid #e5e7eb;">
        <div style="padding:16px;border-bottom:1px solid #e5e7eb;background:#fef2f2;">
            <h2 style="margin:0;font-size:15px;color:#991b1b;">Sources Needing Attention</h2>
        </div>
        <table style="width:100%;border-collapse:collapse;">
            <tr style="background:#f9fafb;">
                <th style="padding:8px 16px;text-align:left;font-size:12px;color:#6b7280;font-weight:600;">Source</th>
                <th style="padding:8px 16px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">Gap</th>
                <th style="padding:8px 16px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">Last Data</th>
            </tr>
            {stale_rows}
        </table>
    </div>

    <!-- Healthy Sources -->
    <div style="background:white;border-radius:12px;overflow:hidden;margin-bottom:24px;border:1px solid #e5e7eb;">
        <div style="padding:16px;border-bottom:1px solid #e5e7eb;background:#f0fdf4;">
            <h2 style="margin:0;font-size:15px;color:#166534;">Healthy Sources ({len(fresh)}/{len(results)})</h2>
        </div>
        <table style="width:100%;border-collapse:collapse;">
            <tr style="background:#f9fafb;">
                <th style="padding:8px 16px;text-align:left;font-size:12px;color:#6b7280;font-weight:600;">Source</th>
                <th style="padding:8px 16px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">Last Data</th>
                <th style="padding:8px 16px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">Age</th>
            </tr>
            {fresh_rows}
        </table>
    </div>

    <!-- Footer -->
    <div style="text-align:center;color:#9ca3af;font-size:12px;padding:16px;">
        Checked {checked_str}<br>
        Life Platform Data Completeness Monitor
    </div>

</div>
</body>
</html>'''


def build_text_email(results, stale, now):
    lines = ['Life Platform — Data Completeness Alert', '=' * 50, '']

    lines.append('STALE SOURCES:')
    for r in stale:
        gap_text = format_gap(r['gap_hours']) if r['gap_hours'] else 'No data'
        icon = '🔴 CRITICAL' if r['severity'] == 'CRITICAL' else '⚠️  WARNING'
        lines.append(f"  {icon}: {r['config']['name']} — {gap_text} (last: {r['last_date'] or 'never'})")
        lines.append(f"    Threshold: {r['config']['stale_hours']}h")
        lines.append(f"    Degraded: {', '.join(r['config']['impacts'][:3])}")
        lines.append('')

    fresh = [r for r in results if r['status'] == 'FRESH']
    lines.append(f'HEALTHY SOURCES ({len(fresh)}/{len(results)}):')
    for r in fresh:
        gap_text = format_gap(r['gap_hours']) if r['gap_hours'] else ''
        lines.append(f"  ✅ {r['config']['name']}: {r['last_date']} ({gap_text})")

    pt_time = now - timedelta(hours=8)
    lines.append('')
    lines.append(f"Checked: {pt_time.strftime('%Y-%m-%d %I:%M %p PT')}")

    return '\n'.join(lines)


def format_gap(hours):
    if hours is None:
        return 'N/A'
    if hours < 24:
        return f"{hours:.0f}h"
    days = hours / 24
    if days < 2:
        return f"1 day, {(hours % 24):.0f}h"
    return f"{days:.1f} days"


PYTHON

cd /tmp/freshness_build
zip -r /tmp/freshness_checker.zip .
echo "  ✅ Lambda package built"

# ── Step 3: Deploy Lambda code ───────────────────────────────────────────────
echo ""
echo "Step 3: Deploying Lambda code..."

aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb:///tmp/freshness_checker.zip \
    --region "$REGION" \
    --query "[FunctionName,CodeSize,LastModified]"

echo "  ✅ Lambda code deployed"

echo "  Waiting for Lambda update to propagate..."
aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"

# ── Step 4: Update environment variables ─────────────────────────────────────
echo ""
echo "Step 4: Updating environment variables..."

aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --timeout 30 \
    --environment 'Variables={TABLE_NAME=life-platform,SNS_ARN=arn:aws:sns:us-west-2:'"$ACCOUNT"':life-platform-alerts,SENDER=awsdev@mattsusername.com,RECIPIENT=awsdev@mattsusername.com}' \
    --region "$REGION" \
    --query "[FunctionName,Timeout,Environment.Variables]"

echo "  ✅ Environment updated"

# ── Step 5: Test invoke ──────────────────────────────────────────────────────
echo ""
echo "Step 5: Testing..."
sleep 5

aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --log-type Tail \
    /tmp/freshness_response.json \
    --query "LogResult" \
    --output text | base64 -d | tail -30

echo ""
echo "Response:"
cat /tmp/freshness_response.json | python3 -m json.tool

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  ✅ Data Completeness Alerting v2 deployed!"
echo "══════════════════════════════════════════════════════════════"
echo ""
echo "What changed:"
echo "  • 10 sources monitored (was 8) — added habitify, garmin; removed hevy (deprecated)"
echo "  • Per-source thresholds: daily=48h, activity=72h, apple_health=21d/30d"
echo "  • HTML email via SES with impact assessment"
echo "  • SNS escalation only for 3+ stale sources"
echo "  • Only emails when gaps detected (no daily noise)"
echo ""
echo "Schedule: runs daily at 8:15 AM PT (unchanged)"
