#!/usr/bin/env bash
# TB7-5: EventBridge Scheduler orphan check — reusable utility
set -euo pipefail
REGION="us-west-2"

echo "=== Schedule groups ==="
aws scheduler list-schedule-groups --region "$REGION" \
    --query 'ScheduleGroups[].Name' --output table

echo ""
echo "=== 'life-platform' group schedules ==="
aws scheduler list-schedules --group-name life-platform --region "$REGION" \
    --query 'Schedules[].[Name,State,Target.Arn]' --output table 2>/dev/null || \
    echo "  (group does not exist — good)"

echo ""
echo "=== Default group — life-platform targets only ==="
aws scheduler list-schedules --group-name default --region "$REGION" \
    --query 'Schedules[].[Name,State,Target.Arn]' --output table 2>/dev/null | \
    grep -i "life-platform\|whoop\|garmin\|strava\|withings\|habitify\|todoist\|eightsleep\|macrofactor\|dropbox\|weather\|journal\|enrichment" || \
    echo "  No life-platform targets found — clean"

echo ""
echo "=== CDK EventBridge Rules count ==="
aws events list-rules --region "$REGION" --query 'length(Rules)' --output text
