#!/usr/bin/env bash
# TB7-9: CloudWatch alarm triage — reusable utility
set -euo pipefail
REGION="us-west-2"

echo "=== Alarms in ALARM state ==="
ALARMS_JSON=$(aws cloudwatch describe-alarms \
    --state-value ALARM --region "$REGION" \
    --query 'MetricAlarms[].{Name:AlarmName,Metric:MetricName,Namespace:Namespace,Reason:StateReason}' \
    --output json)

COUNT=$(echo "$ALARMS_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
echo "Total: $COUNT"
echo ""

echo "$ALARMS_JSON" | python3 -c "
import json, sys
alarms = json.load(sys.stdin)
cats = {'INGESTION': [], 'COMPUTE': [], 'EMAIL': [], 'INFRA': [], 'OTHER': []}
for a in alarms:
    n = a['Name']
    if 'ingestion-error' in n or any(x in n for x in ['whoop','garmin','strava','withings','habitify','todoist','eightsleep','macrofactor','dropbox','apple','weather','notion']):
        cats['INGESTION'].append(n)
    elif any(x in n for x in ['compute','character-sheet','daily-metrics','daily-insight','adaptive','hypothesis','dashboard']):
        cats['COMPUTE'].append(n)
    elif any(x in n for x in ['brief','digest','chronicle','plate','compass','nutrition','anomaly','freshness','brittany']):
        cats['EMAIL'].append(n)
    elif any(x in n for x in ['canary','dlq','slo','data-export','reconciliation','pip-audit','qa-smoke']):
        cats['INFRA'].append(n)
    else:
        cats['OTHER'].append(n)
for cat, items in cats.items():
    if items:
        print(f'--- {cat} ({len(items)}) ---')
        for n in sorted(items): print(f'  {n}')
        print()
"

echo "=== State reasons ==="
echo "$ALARMS_JSON" | python3 -c "
import json, sys
for a in sorted(json.load(sys.stdin), key=lambda x: x['Name']):
    print(f\"  {a['Name']}\")
    print(f\"    {a['Reason'][:100]}\")
"

echo ""
echo "# Delete: aws cloudwatch delete-alarms --alarm-names <name> --region $REGION"
