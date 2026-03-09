#!/bin/bash
# p1_migrate_eventbridge_scheduler.sh — P1.6: EventBridge Rules → EventBridge Scheduler
#
# WHY: EventBridge Rules use UTC-fixed crons — they drift 1 hour at DST transitions.
#      EventBridge Scheduler supports IANA timezone (America/Los_Angeles), so schedules
#      stay correct year-round automatically. No more deploy_dst_spring/fall scripts.
#
# SAFE: Old EventBridge rules are disabled, not deleted.
#       Rollback: aws events enable-rule --name <rule> --region us-west-2
#
# Usage: cd ~/Documents/Claude/life-platform && bash deploy/p1_migrate_eventbridge_scheduler.sh

set -euo pipefail
REGION="us-west-2"
ACCOUNT="205930651321"
TZ="America/Los_Angeles"
SCHEDULER_GROUP="life-platform"
LAMBDA_PREFIX="arn:aws:lambda:${REGION}:${ACCOUNT}:function"
SCHEDULER_ROLE="life-platform-scheduler-role"
SCHEDULER_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${SCHEDULER_ROLE}"
_SCHED_COUNT=0

# Write Python helper once — avoids heredoc-inside-function issues
cat > /tmp/make_target.py << 'PYEOF'
import json, sys
with open(sys.argv[3]) as f:
    payload_str = f.read().strip()
target = {"Arn": sys.argv[1], "RoleArn": sys.argv[2], "Input": payload_str}
print(json.dumps(target))
PYEOF

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  P1.6: EventBridge → Scheduler (IANA timezone, DST-safe)   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Ensure Scheduler IAM role exists (with correct trust policy) ─────
echo "── Step 1: Scheduler IAM role ──"

TRUST_POLICY=$(python3 - <<'PYEOF'
import json
print(json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "scheduler.amazonaws.com"},
        "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": "205930651321"}}
    }]
}))
PYEOF
)

INVOKE_POLICY=$(python3 - <<'PYEOF'
import json
print(json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "InvokeLambda",
        "Effect": "Allow",
        "Action": "lambda:InvokeFunction",
        "Resource": "arn:aws:lambda:us-west-2:205930651321:function:*"
    }]
}))
PYEOF
)

if aws iam get-role --role-name "$SCHEDULER_ROLE" --no-cli-pager > /dev/null 2>&1; then
    # Update trust policy to ensure SourceAccount condition is present
    aws iam update-assume-role-policy \
        --role-name "$SCHEDULER_ROLE" \
        --policy-document "$TRUST_POLICY" \
        --no-cli-pager
    echo "  ✅ Role exists — trust policy refreshed"
else
    aws iam create-role \
        --role-name "$SCHEDULER_ROLE" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "EventBridge Scheduler role for Life Platform Lambda invocations" \
        --no-cli-pager > /dev/null
    aws iam put-role-policy \
        --role-name "$SCHEDULER_ROLE" \
        --policy-name "invoke-lambda" \
        --policy-document "$INVOKE_POLICY" \
        --no-cli-pager
    echo "  ✅ Role created"
fi
echo ""

# ── Step 2: Create Scheduler group ───────────────────────────────────────────
echo "── Step 2: Scheduler group ──"
aws scheduler create-schedule-group \
    --name "$SCHEDULER_GROUP" \
    --region "$REGION" \
    --no-cli-pager > /dev/null 2>&1 \
    && echo "  ✅ Group created: $SCHEDULER_GROUP" \
    || echo "  ✅ Group already exists: $SCHEDULER_GROUP"
echo ""

# ── Helper: upsert a schedule ────────────────────────────────────────────────
# Uses Python to build the --target JSON so embedded payload JSON is safe.
make_schedule() {
    local name="$1"
    local cron="$2"
    local fn="$3"
    local payload="${4:-}"
    payload="${payload:-{}}"


    echo -n "  $name ($fn @ $cron) ... "

    # Build target JSON via Python — payload written to its own file first
    # to avoid ALL shell/JSON quoting interactions
    _SCHED_COUNT=$(( _SCHED_COUNT + 1 ))
    local payload_file="/tmp/payload-${_SCHED_COUNT}.txt"
    local tmpfile="/tmp/sched-${_SCHED_COUNT}.json"
    rm -f "$payload_file" "$tmpfile"
    printf '%s' "$payload" > "$payload_file"
    python3 /tmp/make_target.py "$LAMBDA_PREFIX:$fn" "$SCHEDULER_ROLE_ARN" "$payload_file" > "$tmpfile"
    rm -f "$payload_file"

    local exists=false
    aws scheduler get-schedule \
        --group-name "$SCHEDULER_GROUP" \
        --name "$name" \
        --region "$REGION" \
        --no-cli-pager > /dev/null 2>&1 && exists=true || true

    if $exists; then
        aws scheduler update-schedule \
            --group-name "$SCHEDULER_GROUP" \
            --name "$name" \
            --schedule-expression "cron($cron)" \
            --schedule-expression-timezone "$TZ" \
            --flexible-time-window '{"Mode":"OFF"}' \
            --target "file://$tmpfile" \
            --state "ENABLED" \
            --region "$REGION" \
            --no-cli-pager > /dev/null
        echo "updated ✅"
    else
        aws scheduler create-schedule \
            --group-name "$SCHEDULER_GROUP" \
            --name "$name" \
            --schedule-expression "cron($cron)" \
            --schedule-expression-timezone "$TZ" \
            --flexible-time-window '{"Mode":"OFF"}' \
            --target "file://$tmpfile" \
            --state "ENABLED" \
            --region "$REGION" \
            --no-cli-pager > /dev/null
        echo "created ✅"
    fi

    rm -f "$tmpfile"
}

# ── Step 3: Create all schedules ─────────────────────────────────────────────
echo "── Step 3: Creating schedules (America/Los_Angeles) ──"
echo ""

echo "  [Ingestion — daily]"
make_schedule "whoop-ingestion"           "0 6 * * ? *"   "whoop-data-ingestion"
make_schedule "garmin-ingestion"          "0 6 * * ? *"   "garmin-data-ingestion"
make_schedule "notion-journal-ingestion"  "0 6 * * ? *"   "notion-journal-ingestion"
make_schedule "withings-ingestion"        "15 6 * * ? *"  "withings-data-ingestion"
make_schedule "habitify-ingestion"        "15 6 * * ? *"  "habitify-data-ingestion"
make_schedule "strava-ingestion"          "30 6 * * ? *"  "strava-data-ingestion"
make_schedule "journal-enrichment"        "30 6 * * ? *"  "journal-enrichment"
make_schedule "todoist-ingestion"         "45 6 * * ? *"  "todoist-data-ingestion"
make_schedule "eightsleep-ingestion"      "0 7 * * ? *"   "eightsleep-data-ingestion"
make_schedule "activity-enrichment"       "30 7 * * ? *"  "activity-enrichment"
make_schedule "macrofactor-ingestion"     "0 8 * * ? *"   "macrofactor-data-ingestion"
make_schedule "anomaly-detector"          "5 8 * * ? *"   "anomaly-detector"
make_schedule "mcp-cache-warmer"          "0 9 * * ? *"   "life-platform-mcp" \
    '{"action":"warm_cache"}'
make_schedule "whoop-recovery-refresh"    "30 9 * * ? *"  "whoop-data-ingestion" \
    '{"date_override":"today"}'
make_schedule "character-sheet-compute"   "35 9 * * ? *"  "character-sheet-compute"
make_schedule "freshness-checker"         "45 9 * * ? *"  "life-platform-freshness-checker"
make_schedule "daily-brief"              "0 10 * * ? *"  "daily-brief"
echo ""

echo "  [Dashboard refresh]"
make_schedule "dashboard-refresh-afternoon" "0 14 * * ? *" "dashboard-refresh"
make_schedule "dashboard-refresh-evening"   "0 18 * * ? *" "dashboard-refresh"
echo ""

echo "  [Weekly emails]"
make_schedule "monday-compass"      "0 8 ? * MON *"  "monday-compass"
make_schedule "wednesday-chronicle" "0 7 ? * WED *"  "wednesday-chronicle"
make_schedule "weekly-plate"        "0 19 ? * FRI *" "weekly-plate"
make_schedule "nutrition-review"    "0 9 ? * SAT *"  "nutrition-review"
make_schedule "weekly-digest"       "0 8 ? * SUN *"  "weekly-digest"
echo ""

echo "  [Monthly digest — 1st of month, Lambda guards for Monday]"
make_schedule "monthly-digest" "0 9 1 * ? *" "monthly-digest"
echo ""

echo "  [Dropbox poll — every 30 min]"
make_schedule "dropbox-poll" "0/30 * * * ? *" "dropbox-poll"
echo ""

# ── Step 4: Disable old EventBridge rules ────────────────────────────────────
echo "── Step 4: Disabling old EventBridge rules (not deleting) ──"

RULES=$(aws events list-rules --region "$REGION" --no-cli-pager \
    --query "Rules[*].Name" --output text 2>/dev/null || echo "")

if [ -z "$RULES" ]; then
    echo "  No rules found"
else
    for rule in $RULES; do
        TARGET_ARN=$(aws events list-targets-by-rule \
            --rule "$rule" --region "$REGION" --no-cli-pager \
            --query "Targets[0].Arn" --output text 2>/dev/null || echo "")
        if echo "$TARGET_ARN" | grep -q "arn:aws:lambda:${REGION}:${ACCOUNT}:function:"; then
            echo -n "  Disabling $rule ... "
            aws events disable-rule --name "$rule" --region "$REGION" --no-cli-pager
            echo "✅"
        fi
    done
fi
echo ""

# ── Step 5: Verify ────────────────────────────────────────────────────────────
echo "── Step 5: Verification ──"
SCHEDULE_COUNT=$(aws scheduler list-schedules \
    --group-name "$SCHEDULER_GROUP" \
    --region "$REGION" \
    --no-cli-pager \
    --query "length(Schedules)" --output text)
echo "  Schedules in group '$SCHEDULER_GROUP': $SCHEDULE_COUNT"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ P1.6 EventBridge → Scheduler Migration Complete         ║"
echo "║                                                              ║"
echo "║  All schedules now run on America/Los_Angeles timezone       ║"
echo "║  DST transitions handled automatically — no manual scripts  ║"
echo "║                                                              ║"
echo "║  Rollback: aws events enable-rule --name <rule>             ║"
echo "║  Then:     aws scheduler delete-schedule --group-name       ║"
echo "║            life-platform --name <name>                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
