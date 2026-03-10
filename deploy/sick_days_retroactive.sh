#!/bin/bash
# sick_days_retroactive.sh — Retroactively flag March 8-9 as sick days in DDB
# Run from project root: bash deploy/sick_days_retroactive.sh
set -euo pipefail

REGION="us-west-2"
TABLE="life-platform"
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "Flagging 2026-03-08 as sick day..."
aws dynamodb put-item --region $REGION --table-name $TABLE --item \
    "{\"pk\": {\"S\": \"USER#matthew#SOURCE#sick_days\"}, \"sk\": {\"S\": \"DATE#2026-03-08\"}, \"date\": {\"S\": \"2026-03-08\"}, \"reason\": {\"S\": \"sick - flu/illness\"}, \"logged_at\": {\"S\": \"$NOW\"}, \"schema_version\": {\"N\": \"1\"}}"

echo "Flagging 2026-03-09 as sick day..."
aws dynamodb put-item --region $REGION --table-name $TABLE --item \
    "{\"pk\": {\"S\": \"USER#matthew#SOURCE#sick_days\"}, \"sk\": {\"S\": \"DATE#2026-03-09\"}, \"date\": {\"S\": \"2026-03-09\"}, \"reason\": {\"S\": \"sick - flu/illness\"}, \"logged_at\": {\"S\": \"$NOW\"}, \"schema_version\": {\"N\": \"1\"}}"

echo ""
echo "✅ Sick days flagged: 2026-03-08, 2026-03-09"
echo ""
echo "Now recompute character sheet + daily metrics for both dates:"
echo ""
echo "aws lambda invoke --function-name character-sheet-compute \\"
echo "    --payload '{\"date\": \"2026-03-08\", \"force\": true}' \\"
echo "    --cli-binary-format raw-in-base64-out /tmp/cs_08.json && cat /tmp/cs_08.json"
echo ""
echo "aws lambda invoke --function-name character-sheet-compute \\"
echo "    --payload '{\"date\": \"2026-03-09\", \"force\": true}' \\"
echo "    --cli-binary-format raw-in-base64-out /tmp/cs_09.json && cat /tmp/cs_09.json"
echo ""
echo "aws lambda invoke --function-name daily-metrics-compute \\"
echo "    --payload '{\"date\": \"2026-03-08\", \"force\": true}' \\"
echo "    --cli-binary-format raw-in-base64-out /tmp/dm_08.json && cat /tmp/dm_08.json"
echo ""
echo "aws lambda invoke --function-name daily-metrics-compute \\"
echo "    --payload '{\"date\": \"2026-03-09\", \"force\": true}' \\"
echo "    --cli-binary-format raw-in-base64-out /tmp/dm_09.json && cat /tmp/dm_09.json"
