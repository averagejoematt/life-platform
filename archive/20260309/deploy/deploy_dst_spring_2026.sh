#!/bin/bash
# deploy_dst_spring_2026.sh — DST Spring Forward Cron Update
# Effective: March 8, 2026 (PDT begins)
#
# EventBridge crons are UTC. PST = UTC-8, PDT = UTC-7.
# To maintain the same local PT times, subtract 1 hour from each UTC cron.
#
# Run this on or after March 8 before the first 6:00 AM PDT ingestion cycle.
# To revert (November DST fall-back), add 1 hour back to each cron.
#
# Pre-flight: Run from ~/Documents/Claude/life-platform/

set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Life Platform — DST Spring Forward 2026"
echo "  Shifting 25 EventBridge crons: UTC -1 hour"
echo "═══════════════════════════════════════════════════"

REGION="us-west-2"
ERRORS=0

update_rule() {
    local name="$1"
    local old_cron="$2"
    local new_cron="$3"
    local pt_time="$4"

    echo -n "  $name: $old_cron → $new_cron ($pt_time PDT) ... "
    if aws events put-rule \
        --name "$name" \
        --schedule-expression "$new_cron" \
        --region "$REGION" 2>/dev/null; then
        echo "✅"
    else
        echo "❌"
        ERRORS=$((ERRORS + 1))
    fi
}

# ── 5:45 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 5:45 AM PT ingestion ──"
update_rule "weather-daily-ingestion"  "cron(45 13 * * ? *)" "cron(45 12 * * ? *)" "5:45 AM"

# ── 6:00 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 6:00 AM PT ingestion ──"
update_rule "whoop-daily-ingestion"    "cron(0 14 * * ? *)"  "cron(0 13 * * ? *)"  "6:00 AM"
update_rule "garmin-daily-ingestion"   "cron(0 14 * * ? *)"  "cron(0 13 * * ? *)"  "6:00 AM"
update_rule "notion-daily-ingest"      "cron(0 14 * * ? *)"  "cron(0 13 * * ? *)"  "6:00 AM"

# ── 6:15 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 6:15 AM PT ingestion ──"
update_rule "withings-daily-ingestion" "cron(15 14 * * ? *)" "cron(15 13 * * ? *)" "6:15 AM"
update_rule "habitify-daily-ingest"    "cron(15 14 * * ? *)" "cron(15 13 * * ? *)" "6:15 AM"

# ── 6:30 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 6:30 AM PT ingestion ──"
update_rule "strava-daily-ingestion"      "cron(30 14 * * ? *)" "cron(30 13 * * ? *)" "6:30 AM"
update_rule "journal-enrichment-daily"    "cron(30 14 * * ? *)" "cron(30 13 * * ? *)" "6:30 AM"

# ── 6:45 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 6:45 AM PT ingestion ──"
update_rule "todoist-daily-ingestion"  "cron(45 14 * * ? *)" "cron(45 13 * * ? *)" "6:45 AM"

# ── 7:00 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 7:00 AM PT ingestion ──"
update_rule "eightsleep-daily-ingestion" "cron(0 15 * * ? *)" "cron(0 14 * * ? *)" "7:00 AM"

# ── 7:30 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 7:30 AM PT enrichment ──"
update_rule "activity-enrichment-nightly" "cron(30 15 * * ? *)" "cron(30 14 * * ? *)" "7:30 AM"

# ── 8:00 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 8:00 AM PT ingestion ──"
update_rule "macrofactor-daily-ingestion" "cron(0 16 * * ? *)" "cron(0 15 * * ? *)" "8:00 AM"

# ── 8:05 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 8:05 AM PT alerting ──"
update_rule "anomaly-detector-daily" "cron(5 16 * * ? *)" "cron(5 15 * * ? *)" "8:05 AM"

# ── 9:00 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 9:00 AM PT cache ──"
update_rule "life-platform-nightly-warmer" "cron(0 17 * * ? *)" "cron(0 16 * * ? *)" "9:00 AM"

# ── 9:30 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 9:30 AM PT refresh ──"
update_rule "whoop-recovery-refresh" "cron(30 17 * * ? *)" "cron(30 16 * * ? *)" "9:30 AM"

# ── 9:35 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 9:35 AM PT character sheet ──"
update_rule "character-sheet-compute" "cron(35 17 * * ? *)" "cron(35 16 * * ? *)" "9:35 AM"

# ── 9:45 AM PT ───────────────────────────────────────────────────────────
echo ""
echo "── 9:45 AM PT freshness ──"
update_rule "life-platform-freshness-check" "cron(45 17 * * ? *)" "cron(45 16 * * ? *)" "9:45 AM"

# ── 10:00 AM PT ──────────────────────────────────────────────────────────
echo ""
echo "── 10:00 AM PT daily brief ──"
update_rule "daily-brief-schedule" "cron(0 18 * * ? *)" "cron(0 17 * * ? *)" "10:00 AM"

# ── Weekly/Monthly/Special digests ───────────────────────────────────────
echo ""
echo "── Digest & special schedules ──"
update_rule "wednesday-chronicle-schedule" "cron(0 15 ? * WED *)" "cron(0 14 ? * WED *)" "7:00 AM Wed"
update_rule "weekly-digest-sunday"    "cron(0 16 ? * SUN *)"  "cron(0 15 ? * SUN *)"  "8:00 AM Sun"
update_rule "nutrition-review-schedule" "cron(0 17 ? * SAT *)" "cron(0 16 ? * SAT *)" "9:00 AM Sat"
update_rule "monthly-digest-schedule" "cron(0 16 ? * 1#1 *)"  "cron(0 15 ? * 1#1 *)"  "8:00 AM 1st Mon"

# ── 2:00 PM PT ────────────────────────────────────────────────────────────
echo ""
echo "── 2:00 PM PT dashboard refresh ──"
update_rule "dashboard-refresh-afternoon" "cron(0 22 * * ? *)" "cron(0 21 * * ? *)" "2:00 PM"

# ── 6:00 PM PT ────────────────────────────────────────────────────────────
echo ""
echo "── 6:00 PM PT dashboard refresh + weekly plate ──"
update_rule "dashboard-refresh-evening" "cron(0 2 * * ? *)" "cron(0 1 * * ? *)" "6:00 PM"
update_rule "weekly-plate-schedule" "cron(0 2 ? * SAT *)" "cron(0 1 ? * SAT *)" "6:00 PM Fri"

# ── Skipped ──────────────────────────────────────────────────────────────
echo ""
echo "── Skipped (rate-based, no DST impact) ──"
echo "  dropbox-poll-schedule: rate(30 minutes) — no change needed"

# ── Verify ───────────────────────────────────────────────────────────────
echo ""
echo "── Verification: Current schedules ──"
aws events list-rules \
    --region "$REGION" \
    --query "Rules[?State=='ENABLED'].[Name,ScheduleExpression]" \
    --output table

# ── Summary ──────────────────────────────────────────────────────────────
echo ""
if [ "$ERRORS" -eq 0 ]; then
    echo "═══════════════════════════════════════════════════"
    echo "  ✅ DST Spring Forward — 25/25 rules updated"
    echo ""
    echo "  All crons shifted UTC -1 hour."
    echo "  Local PT schedule unchanged."
    echo ""
    echo "  Effective: March 8, 2026 (PDT begins)"
    echo ""
    echo "  Revert (Nov 2 fall-back): add 1 hour back"
    echo "  or run deploy_dst_fall_2026.sh (create later)"
    echo "═══════════════════════════════════════════════════"
else
    echo "═══════════════════════════════════════════════════"
    echo "  ⚠️  $ERRORS rule(s) failed to update"
    echo "  Check output above and retry manually."
    echo "═══════════════════════════════════════════════════"
    exit 1
fi
