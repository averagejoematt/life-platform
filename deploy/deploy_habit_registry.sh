#!/bin/bash
# Deploy Habit Registry to DynamoDB PROFILE#v1
# Generated: 2026-02-28 Session 36
# 65 habits with full metadata (science, why_matthew, tier, synergy_group, etc.)
#
# Usage: bash deploy/deploy_habit_registry.sh
# Prereq: aws cli configured, python3 available

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Deploying Habit Registry (65 habits) ==="

# Generate DynamoDB JSON from Python source
echo "Generating DynamoDB-formatted JSON..."
python3 "$ROOT_DIR/deploy/generate_habit_registry.py"

TMPFILE="/tmp/habit_registry_values.json"
if [ ! -f "$TMPFILE" ]; then
    echo "ERROR: JSON file not generated"
    exit 1
fi

PAYLOAD_SIZE=$(wc -c < "$TMPFILE")
echo "Payload: $PAYLOAD_SIZE bytes"

# Single DynamoDB update
echo "Writing to DynamoDB..."
aws dynamodb update-item \
  --table-name life-platform \
  --key '{"pk":{"S":"USER#matthew"},"sk":{"S":"PROFILE#v1"}}' \
  --update-expression "SET habit_registry = :r" \
  --expression-attribute-values "file://$TMPFILE" \
  --return-values NONE \
  --region us-west-2

echo "✅ habit_registry written to PROFILE#v1"

# Verify
echo ""
echo "Verifying..."
RESULT=$(aws dynamodb get-item \
  --table-name life-platform \
  --key '{"pk":{"S":"USER#matthew"},"sk":{"S":"PROFILE#v1"}}' \
  --projection-expression "habit_registry" \
  --region us-west-2 \
  --query "Item.habit_registry.M | keys(@) | length(@)")

echo "Habits in registry: $RESULT"

# Cleanup
rm -f "$TMPFILE"
echo "✅ Deploy complete"
