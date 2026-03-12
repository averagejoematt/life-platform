#!/bin/bash
# TB7-17: Verify DLQ depth alarms have period ≤ 3600 seconds (1 hour)
#
# DLQ messages indicate silent Lambda failures. A period > 1 hour means
# a failed message can sit undetected for hours before the alarm fires.
# This script audits all DLQ-related CloudWatch alarms and fails if any
# have a period longer than 1 hour.
#
# Usage: bash deploy/verify_dlq_alarm_periods.sh

set -euo pipefail

AWS_REGION="us-west-2"
MAX_PERIOD=3600   # 1 hour in seconds

echo "Scanning CloudWatch alarms for DLQ depth metrics..."
echo ""

# Fetch all alarms that reference ApproximateNumberOfMessagesNotVisible (SQS DLQ depth)
# or have "dlq" / "dead" in their name.
ALARM_JSON=$(aws cloudwatch describe-alarms \
  --region "$AWS_REGION" \
  --query "MetricAlarms[?contains(MetricName, 'ApproximateNumberOfMessages') || contains(lower(AlarmName), 'dlq') || contains(lower(AlarmName), 'dead')]" \
  --output json)

COUNT=$(echo "$ALARM_JSON" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")

if [ "$COUNT" -eq 0 ]; then
  echo "⚠️  No DLQ alarms found. Consider creating an alarm on the DLQ queue depth."
  echo "   Queue: life-platform-dlq"
  echo "   Metric: ApproximateNumberOfMessagesNotVisible > 0 for 1 period"
  exit 1
fi

echo "Found $COUNT DLQ-related alarm(s):"
echo ""

FAILED=0
echo "$ALARM_JSON" | python3 << 'PYEOF'
import json, sys

alarms = json.load(sys.stdin)
max_period = 3600

for a in alarms:
    name    = a.get("AlarmName", "?")
    period  = a.get("Period", 0)
    evals   = a.get("EvaluationPeriods", 1)
    state   = a.get("StateValue", "?")
    total   = period * evals

    ok = period <= max_period
    status = "✅" if ok else "❌"
    print(f"  {status} {name}")
    print(f"     Period: {period}s ({period // 60} min)  x {evals} eval(s) = {total}s total window")
    print(f"     State:  {state}")
    if not ok:
        print(f"     ⚠️  VIOLATION: period {period}s exceeds limit of {max_period}s (1 hour)")
    print()

violations = [a for a in alarms if a.get("Period", 0) > max_period]
if violations:
    print(f"❌ {len(violations)} alarm(s) exceed the 1-hour period limit.")
    print("   Fix: reduce Period in the CloudWatch alarm or CDK construct.")
    sys.exit(1)
else:
    print(f"✅ All {len(alarms)} DLQ alarm(s) have period ≤ {max_period}s (1 hour).")
PYEOF
