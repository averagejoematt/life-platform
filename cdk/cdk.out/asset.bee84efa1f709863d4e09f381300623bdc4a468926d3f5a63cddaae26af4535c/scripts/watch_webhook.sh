#!/bin/bash
# watch_webhook.sh — Poll for new Health Auto Export webhook payloads
# Run: bash watch_webhook.sh
# Stop: Ctrl+C

BUCKET="matthew-life-platform"
PREFIX="raw/health_auto_export/2026/02/"
REGION="us-west-2"
INTERVAL=300  # 5 minutes

echo "👀 Watching for new webhook payloads (every ${INTERVAL}s)..."
echo "   Ctrl+C to stop"
echo ""

LAST_COUNT=$(aws s3 ls "s3://$BUCKET/$PREFIX" --region "$REGION" 2>/dev/null | wc -l | tr -d ' ')
echo "$(date '+%I:%M %p') — Current payloads: $LAST_COUNT"
aws s3 ls "s3://$BUCKET/$PREFIX" --region "$REGION" 2>/dev/null
echo "---"

while true; do
    sleep "$INTERVAL"
    COUNT=$(aws s3 ls "s3://$BUCKET/$PREFIX" --region "$REGION" 2>/dev/null | wc -l | tr -d ' ')
    
    if [ "$COUNT" -gt "$LAST_COUNT" ]; then
        echo ""
        echo "🟢 $(date '+%I:%M %p') — NEW PAYLOAD DETECTED! ($LAST_COUNT → $COUNT)"
        aws s3 ls "s3://$BUCKET/$PREFIX" --region "$REGION" 2>/dev/null | tail -3
        
        # Show latest CloudWatch logs
        echo ""
        echo "Latest Lambda logs:"
        STREAM=$(aws logs describe-log-streams \
            --log-group-name /aws/lambda/health-auto-export-webhook \
            --order-by LastEventTime --descending --max-items 1 \
            --query "logStreams[0].logStreamName" --output text \
            --region "$REGION" 2>/dev/null)
        
        if [ "$STREAM" != "None" ] && [ -n "$STREAM" ]; then
            aws logs get-log-events \
                --log-group-name /aws/lambda/health-auto-export-webhook \
                --log-stream-name "$STREAM" \
                --limit 15 \
                --query "events[].message" --output text \
                --region "$REGION" 2>/dev/null | grep -E "Matched|Skipped|Source filter|Other metrics|Glucose|Result"
        fi
        echo "---"
        LAST_COUNT=$COUNT
    else
        echo "$(date '+%I:%M %p') — No change ($COUNT payloads)"
    fi
done
