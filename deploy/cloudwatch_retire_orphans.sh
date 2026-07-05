#!/usr/bin/env bash
# cloudwatch_retire_orphans.sh — #411 / ADR-116 CloudWatch cost audit (2026-07)
#
# Deletes the orphan CloudWatch alarms that live outside CDK and are either
# provably redundant with an existing IaC alarm/digest, or are on a dead metric.
# Every deletion is justified in docs/reviews/CLOUDWATCH_AUDIT_2026-07.md §3.
#
# This is NOT auto-run. The orchestrator runs it deliberately, then deploys
# LifePlatformMonitoring so the 2 ADOPTED alarms are recreated under IaC names:
#
#     bash deploy/cloudwatch_retire_orphans.sh            # dry-run (default): prints, deletes nothing
#     bash deploy/cloudwatch_retire_orphans.sh --apply    # actually delete
#     cd cdk && npx cdk deploy LifePlatformMonitoring     # recreate the 2 adopted alarms (compute-pipeline-stale, hae-webhook-no-invocations-24h)
#
# Order does not matter for collisions (the adopted alarms use NEW names), but
# running this first avoids a brief double-bill on the 2 adopted alarms.
#
# `aws cloudwatch delete-alarms` is idempotent — deleting an absent alarm is a no-op.
set -euo pipefail

REGION="us-west-2"
APPLY="${1:-}"

# ── 3a. RETIRE forever: provably covered by an IaC alarm/digest, or dead metric ──
RETIRE=(
  # duplicates of a code alarm on the same function (code fires as fast or faster)
  "challenge-generator-errors"                          # dup ingestion-error-challenge-generator
  "og-image-generator-errors"                           # dup ingestion-error-og-image-generator
  "life-platform-subscriber-onboarding-errors"          # dup ingestion-error-subscriber-onboarding
  "life-platform-pipeline-health-check-errors"          # dup ingestion-error-pipeline-health-check
  "life-platform-life-platform-dlq-consumer-errors"     # double-prefixed dup of life-platform-dlq-consumer-errors
  "life-platform-daily-brief-duration-p95"              # covered by daily-brief-duration-high
  "life-platform-mcp-duration-p95"                       # covered by mcp-server-duration-high
  "life-platform-mcp-canary-failure-15min"              # dup of life-platform-canary-mcp-failure (same CanaryMCPFail)
  # dead metric — AskEndpointErrors emitted nowhere
  "life-platform-ask-endpoint-errors"
  # per-source ingest-error remnants — freshness/liveness digest covers (audit §4)
  "food-delivery-ingestion-errors"
  "life-platform-garmin-data-ingestion-errors"
  "life-platform-habitify-data-ingestion-errors"
  "life-platform-measurements-ingestion-errors"
  "life-platform-notion-journal-ingestion-errors"
  "life-platform-weather-data-ingestion-errors"
  "life-platform-dropbox-poll-errors"
  "withings-oauth-consecutive-errors"                   # superseded by ingest-consecutive-failures-withings
  "life-platform-insight-email-parser-errors"           # code intent: alerts_topic=None (no alarm)
)

# ── 3b. ADOPT: delete the manual alarm; CDK recreates it under an IaC-owned name ──
#   life-platform-compute-pipeline-stale     -> compute-pipeline-stale
#   health-auto-export-no-invocations-24h    -> hae-webhook-no-invocations-24h
ADOPT_OLD=(
  "life-platform-compute-pipeline-stale"
  "health-auto-export-no-invocations-24h"
)

ALL=("${RETIRE[@]}" "${ADOPT_OLD[@]}")

echo "life-platform CloudWatch orphan cleanup (#411 / ADR-116)"
echo "region=$REGION  mode=$([ "$APPLY" = "--apply" ] && echo APPLY || echo DRY-RUN)"
echo "retire-forever: ${#RETIRE[@]}   adopt-rename (delete old): ${#ADOPT_OLD[@]}   total: ${#ALL[@]}"
echo

if [ "$APPLY" = "--apply" ]; then
  # delete-alarms accepts up to 100 names per call; we have ~20.
  aws cloudwatch delete-alarms --region "$REGION" --alarm-names "${ALL[@]}"
  echo "Deleted ${#ALL[@]} orphan alarms."
  echo "NEXT: cd cdk && npx cdk deploy LifePlatformMonitoring  (recreates the 2 adopted alarms under IaC names)"
else
  printf '  would delete: %s\n' "${ALL[@]}"
  echo
  echo "Dry-run only. Re-run with --apply to delete."
fi
