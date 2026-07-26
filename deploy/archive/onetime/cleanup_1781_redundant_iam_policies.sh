#!/bin/bash
# deploy/archive/onetime/cleanup_1781_redundant_iam_policies.sh
#
# #1781 follow-up: the weekly drift sentinel flagged AWS::IAM::Role MODIFIED across
# 7 stacks. Triage (see the #1781 PR description for the full evidence trail) found
# every flagged role's PropertyDifferences fell into one of three buckets:
#
#   1. GENUINELY SPURIOUS (CFN drift-detection false positives) — fixed in
#      deploy/drift_sentinel.py's `_known_cfn_noise_reason` allowlist. Not this script.
#   2. REAL + LOAD-BEARING — codified into cdk/stacks/role_policies.py (site_api's
#      ce:GetCostAndUsage / cloudwatch:DescribeAlarms / sqs:GetQueueAttributes) and
#      cdk/stacks/compute_stack.py (DashboardRefreshEveningRule description). Those
#      converge to IN_SYNC on the next `cdk deploy` — also not this script.
#   3. REAL BUT REDUNDANT OR STALE — an out-of-band inline policy that duplicates a
#      permission the role's CDK-managed DefaultPolicy already grants (verified
#      statement-by-statement against role_policies.py), or a permission the current
#      code no longer uses at all. THIS script's job: delete those, one
#      `aws iam delete-role-policy` per line below. CloudFormation does not retract
#      an out-of-band inline policy just because it isn't in the template (confirmed
#      by the McpKmsDecrypt case below, which was expected to "self-heal on next cdk
#      deploy" per handovers/archive/HANDOVER_v3.7.6.md and never did) — so this is a
#      one-time manual cleanup, not something a future deploy fixes on its own.
#
# Every policy below was verified against BOTH sides:
#   - cdk/stacks/role_policies.py already grants the equivalent permission via the
#     role's DefaultPolicy (so removing the duplicate changes nothing functionally), OR
#   - grep found zero call sites for the action anywhere the role's Lambda's code can
#     reach (so the permission is simply unused).
# None of these deletions narrow the DEFAULT policy CDK manages — only the redundant/
# stale STANDALONE inline policy goes away. Full audit trail: issue #1781.
#
# This is READ+WRITE (mutates live IAM) — deliberately NOT run by CI or by any agent.
# An operator with AWS creds runs it by hand, once, after the #1781 PR merges (no
# stack deploy required — this only touches inline role policies, not CFN state).
#
# Usage:
#   bash deploy/archive/onetime/cleanup_1781_redundant_iam_policies.sh            # dry-run: print only
#   bash deploy/archive/onetime/cleanup_1781_redundant_iam_policies.sh --apply    # actually delete

set -euo pipefail

APPLY=false
if [[ "${1:-}" == "--apply" ]]; then
    APPLY=true
fi

# role_name policy_name reason
ENTRIES=(
    "LifePlatformIngestion-HabitifyIngestionRoleAE8D3697-6LFzioTebRnz|HabitifySecretAccess|dup of the role's own Secrets Sid (same secret, same action)"
    "LifePlatformCompute-CharacterSheetComputeRoleDAC7AB-MaRBMMFrhnzP|GeneratedS3Write|dup of needs_s3_write generated/* PutObject; GetObject unused (no read call in character_sheet_lambda.py/site_writer.py)"
    "LifePlatformCompute-CharacterSheetComputeRoleDAC7AB-MaRBMMFrhnzP|CharacterSheetKmsDecrypt|dup of the role's own KMS Sid"
    "LifePlatformCompute-CoachComputationEngineRole929C7-FKlmTydRtCF6|CloudWatchTokenMetrics|unused — coach_computation_engine.py never calls put_metric_data"
    "LifePlatformCompute-CoachEnsembleDigestRole85E5AD72-hwJGOI5w70bN|CloudWatchTokenMetrics|dup — compute_coach_orchestrator() already grants PutMetricData via needs_ai_keys=True's AICostMetrics Sid"
    "LifePlatformCompute-CoachHistorySummarizerRole0ADE1-d415N267av0s|CloudWatchTokenMetrics|dup — same AICostMetrics coverage as above"
    "LifePlatformCompute-CoachNarrativeOrchestratorRole0-5OjtcLje7ijp|CloudWatchTokenMetrics|dup — same AICostMetrics coverage as above"
    "LifePlatformCompute-CoachPredictionEvaluatorRole6C8-eEHMQKcg05Mp|CloudWatchTokenMetrics|dup — compute_coach_prediction_evaluator() already has an explicit CloudWatchMetrics Sid"
    "LifePlatformCompute-CoachQualityGateRoleD126A333-4MJnEA8eG245|CloudWatchTokenMetrics|dup — compute_coach_state_updater() already has an explicit CloudWatchMetrics Sid"
    "LifePlatformCompute-CoachStateUpdaterRole4A0E0878-V1fjz4VuCAeD|CloudWatchTokenMetrics|dup — compute_coach_state_updater() already has an explicit CloudWatchMetrics Sid"
    "LifePlatformEmail-DailyBriefRoleCE6CDC95-ksIxNOHNdRvg|SESConfigurationSetAccess|dup — _email_base's SES Sid already covers ses:SendEmail on this config set; ses:SendRawEmail is unused (no send_raw_email call anywhere in lambdas/)"
    "LifePlatformEmail-DailyBriefRoleCE6CDC95-ksIxNOHNdRvg|GeneratedS3Write|dup of needs_s3_write generated/* PutObject; GetObject unused"
    "LifePlatformEmail-MonthlyDigestRole8E849F79-5d4bzUTZxLnO|SESConfigurationSetAccess|dup — same as DailyBriefRole above"
    "LifePlatformEmail-WeeklyDigestRole64B61452-oyAW1JC0iShn|SESConfigurationSetAccess|dup — same as DailyBriefRole above"
    "LifePlatformOperational-CanaryRole4BD5F96A-Cz412T6DGTC4|McpSecretAccess|dup — operational_canary() already grants secretsmanager:GetSecretValue on this exact secret ARN"
    "LifePlatformOperational-DataReconciliationRole50569-W8J8IPZdUTxY|ReconciliationS3Fix|dup — operational_data_reconciliation()'s needs_s3_write=[\"reconciliation/*\"] already grants this"
    "LifePlatformOperational-QaSmokeRoleBDC805B8-CO0bpwGVPAVZ|QaSmokeKmsAccess|dup — operational_qa_smoke() already has its own KMS Sid"
    "LifePlatformOperational-SiteApiAiLambdaRoleA30FF994-JhJVvKT8F0gE|CloudWatchTokenMetrics|dup — site_api_ai() already has an explicit CloudWatchMetrics Sid"
    "LifePlatformOperational-SiteApiLambdaRoleD76A39BB-SmaRYSe02BJk|CloudWatchTokenMetrics|unused — site_api_lambda.py never imports board_quality_gate.py (only site_api_ai_lambda.py does) and calls put_metric_data nowhere else reachable"
    "LifePlatformOperational-SiteApiLambdaRoleD76A39BB-SmaRYSe02BJk|site-api-findings-write|stale — granted site/findings/* by deploy/archive/onetime/add_finding_s3_permission.sh BEFORE the ADR-046 migration; current code (site_api_social.py) writes generated/findings/* only. Keeping a write grant on site/* also cuts against ADR-046's site/-stays-lambda-write-free invariant"
    "LifePlatformMcp-McpServerRoleA1D35EE2-wJuRyjhOVioW|McpKmsDecrypt|dup — mcp_server() already has its own KMS Sid; documented in handovers/archive/HANDOVER_v3.7.6.md as a stopgap expected to self-heal on next deploy (it didn't — CFN doesn't retract undeclared inline policies)"
)

echo "=== #1781 redundant/stale IAM inline-policy cleanup ==="
echo "Mode: $([ "$APPLY" = true ] && echo APPLY || echo DRY-RUN)"
echo

for entry in "${ENTRIES[@]}"; do
    IFS='|' read -r role_name policy_name reason <<<"$entry"
    echo "role=$role_name policy=$policy_name"
    echo "  reason: $reason"
    if [[ "$APPLY" == true ]]; then
        aws iam delete-role-policy --role-name "$role_name" --policy-name "$policy_name" --no-cli-pager
        echo "  [deleted]"
    else
        echo "  [dry-run] aws iam delete-role-policy --role-name \"$role_name\" --policy-name \"$policy_name\""
    fi
    echo
done

echo "Done. Re-run 'python3 deploy/drift_sentinel.py --no-write' afterward to confirm"
echo "each role's cfn_drift entry clears (may need a few minutes for a fresh"
echo "detect_stack_drift to reflect the deletion)."
