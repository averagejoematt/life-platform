#!/bin/bash
# capture_baseline.sh — Capture Day 1 baseline snapshot
#
# Run on the morning of April 1, 2026 after waking data has synced.
# This records the official "intervention start" metrics that all
# future progress will be measured against.
#
# Usage: bash deploy/capture_baseline.sh

set -euo pipefail

REGION="us-west-2"
MCP_FUNCTION="life-platform-mcp"
DATE="2026-04-01"

echo "═══════════════════════════════════════════════════════"
echo "  CAPTURE BASELINE — Day 1 Snapshot"
echo "  Date: ${DATE}"
echo "═══════════════════════════════════════════════════════"
echo ""

# 1. Get Character Sheet (level, tier, all 7 pillar scores)
echo "[1/5] Fetching Character Sheet..."
CHARACTER=$(aws lambda invoke --function-name "${MCP_FUNCTION}" \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"tool\": \"get_character\", \"input\": {\"view\": \"sheet\"}}" \
  --region "${REGION}" /tmp/baseline_character.json --no-cli-pager 2>/dev/null && cat /tmp/baseline_character.json)
echo "  ✓ Character data captured"

# 2. Get latest daily snapshot (weight, BP, all sources)
echo "[2/5] Fetching latest daily snapshot..."
SNAPSHOT=$(aws lambda invoke --function-name "${MCP_FUNCTION}" \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"tool\": \"get_daily_snapshot\", \"input\": {\"view\": \"latest\"}}" \
  --region "${REGION}" /tmp/baseline_snapshot.json --no-cli-pager 2>/dev/null && cat /tmp/baseline_snapshot.json)
echo "  ✓ Daily snapshot captured"

# 3. Get habit data (T0 completion rate)
echo "[3/5] Fetching habit data..."
HABITS=$(aws lambda invoke --function-name "${MCP_FUNCTION}" \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"tool\": \"get_habits\", \"input\": {\"view\": \"summary\"}}" \
  --region "${REGION}" /tmp/baseline_habits.json --no-cli-pager 2>/dev/null && cat /tmp/baseline_habits.json)
echo "  ✓ Habit data captured"

# 4. Get vice streaks
echo "[4/5] Fetching vice streaks..."
VICES=$(aws lambda invoke --function-name "${MCP_FUNCTION}" \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"tool\": \"get_vice_streaks\", \"input\": {}}" \
  --region "${REGION}" /tmp/baseline_vices.json --no-cli-pager 2>/dev/null && cat /tmp/baseline_vices.json)
echo "  ✓ Vice streak data captured"

# 5. Write baseline as journey_milestone to platform_memory
echo "[5/5] Writing baseline to platform_memory..."
BASELINE_CONTENT=$(python3 -c "
import json, sys

def safe_load(path):
    try:
        with open(path) as f:
            data = json.load(f)
            # Handle MCP Lambda response format
            if isinstance(data, dict) and 'body' in data:
                return json.loads(data['body']) if isinstance(data['body'], str) else data['body']
            return data
    except:
        return {}

char = safe_load('/tmp/baseline_character.json')
snap = safe_load('/tmp/baseline_snapshot.json')
habits = safe_load('/tmp/baseline_habits.json')
vices = safe_load('/tmp/baseline_vices.json')

baseline = {
    'event': 'Day 1 Baseline Capture',
    'date': '${DATE}',
    'character_level': char.get('level', 'unknown'),
    'character_tier': char.get('tier', 'unknown'),
    'overall_score': char.get('overall_score', 'unknown'),
    'pillar_scores': char.get('pillars', {}),
    'raw_character': char,
    'raw_snapshot': snap,
    'raw_habits': habits,
    'raw_vices': vices,
    'note': 'Official intervention start. All prior data is baseline/washout period. Captured via deploy/capture_baseline.sh'
}

# Escape for shell
print(json.dumps(baseline).replace(\"'\", \"\\\\'\"))
")

aws lambda invoke --function-name "${MCP_FUNCTION}" \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"tool\": \"write_platform_memory\", \"input\": {\"category\": \"journey_milestone\", \"content\": ${BASELINE_CONTENT}, \"date\": \"${DATE}\"}}" \
  --region "${REGION}" /tmp/baseline_write.json --no-cli-pager 2>/dev/null

echo "  ✓ Baseline written to platform_memory"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ BASELINE CAPTURED"
echo ""
echo "  Raw data saved to:"
echo "    /tmp/baseline_character.json"
echo "    /tmp/baseline_snapshot.json"
echo "    /tmp/baseline_habits.json"
echo "    /tmp/baseline_vices.json"
echo ""
echo "  Milestone stored in DynamoDB:"
echo "    PK: SOURCE#platform_memory"
echo "    SK: journey_milestone#${DATE}"
echo ""
echo "  This is your Day 1. Every future measurement"
echo "  will be compared against these numbers."
echo "═══════════════════════════════════════════════════════"
