#!/usr/bin/env bash
# rotate_ai_keys.sh — one-command rotation prep for life-platform/ai-keys (#1329).
#
# The rotation ACT itself is human-only (gate:owner, #1329 acceptance criteria) —
# generating a new key at https://console.anthropic.com/settings/keys and revoking
# the old one there cannot be automated. This script is the PREP that collapses
# everything AROUND that human act into one command, so once Matthew has the new
# key copied, landing it is `bash deploy/rotate_ai_keys.sh <new-key>` instead of the
# multi-step manual procedure in docs/SECRETS_ROTATION.md.
#
# Consumers of this secret (verified 2026-07-19, #1329 — see docs/SECRETS_ROTATION.md
# "Who actually reads this secret"): most Claude inference migrated to Bedrock/IAM auth
# (ADR-062) and never touches this secret at all. A handful of lambdas still call the
# Anthropic API directly and read `{"anthropic_api_key": "..."}` off this secret,
# cached per-container for the container's lifetime: field_notes_lambda.py,
# ai_expert_analyzer_lambda.py, daily_insight_compute_lambda.py, partner_email_lambda.py,
# monday_compass_lambda.py, data_reconciliation_lambda.py, pipeline_health_check_lambda.py.
# A rotation reaches a warm container only at its next cold start; force a redeploy of
# the affected function(s) if you need it live sooner.
#
# What this script does:
#   1. Reads the CURRENT secret value (preserves any other JSON fields untouched)
#   2. Merges in the new anthropic_api_key (same jq expression as the manual
#      procedure this replaces — docs/SECRETS_ROTATION.md)
#   3. `secretsmanager put-secret-value`s the merged JSON
#   4. Re-reads the secret and parses it the SAME way the consumer lambdas do
#      (`_get_api_key()` in field_notes_lambda.py / ai_expert_analyzer_lambda.py /
#      daily_insight_compute_lambda.py: JSON-parse, `.get("anthropic_api_key", secret)`)
#      to confirm a consumer can actually read the new value back out — this is the
#      verification step, not a live Anthropic API call (no network egress to
#      api.anthropic.com from this script; that only happens inside the lambdas).
#   5. Prints the post-rotation checklist (the two steps this script does NOT do)
#
# Does NOT: generate the key (console, human), revoke the old key (console, human,
# irreversible), or call the live Anthropic API. Never rotates anything by itself if
# invoked with --dry-run.
#
# Usage:
#   bash deploy/rotate_ai_keys.sh                 # prompts for the new key (hidden input)
#   bash deploy/rotate_ai_keys.sh sk-ant-...       # or pass it as an argument
#   bash deploy/rotate_ai_keys.sh --dry-run [key]  # print the plan; no AWS calls at all
#   SECRET_ID=life-platform/site-api-ai-key bash deploy/rotate_ai_keys.sh sk-ant-...
#     # reusable for the isolated site-api key (same JSON shape, R17-04)

set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
SECRET_ID="${SECRET_ID:-life-platform/ai-keys}"

DRY_RUN=0
NEW_KEY=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --help|-h)
      sed -n '2,40p' "$0"
      exit 0
      ;;
    *) NEW_KEY="$arg" ;;
  esac
done

if [ -z "$NEW_KEY" ]; then
  if [ -t 0 ]; then
    read -r -s -p "New Anthropic API key for ${SECRET_ID} (input hidden): " NEW_KEY
    echo
  else
    echo "ERROR: no key given and stdin is not a TTY (can't prompt). Pass it as an argument." >&2
    exit 1
  fi
fi

if [ -z "$NEW_KEY" ]; then
  echo "ERROR: empty key — aborting." >&2
  exit 1
fi

# Sanity check only (not exhaustive) — Anthropic keys are sk-ant-... . A near-miss
# here (pasted the wrong thing) is a much cheaper mistake to catch than an outage.
case "$NEW_KEY" in
  sk-ant-*) ;;
  *)
    echo "WARNING: key does not start with 'sk-ant-' — this doesn't look like an Anthropic API key." >&2
    if [ "$DRY_RUN" -eq 0 ]; then
      read -r -p "Continue anyway? [y/N] " _confirm
      [ "$_confirm" = "y" ] || [ "$_confirm" = "Y" ] || { echo "Aborted."; exit 1; }
    fi
    ;;
esac

_mask() {
  # Print only the first 10 + last 4 chars — enough to eyeball-verify, never the full key.
  local k="$1"
  if [ "${#k}" -le 18 ]; then printf '%s\n' "***"; else printf '%s...%s\n' "${k:0:10}" "${k: -4}"; fi
}

echo "Secret:  ${SECRET_ID}"
echo "Region:  ${REGION}"
echo "New key: $(_mask "$NEW_KEY")"

if [ "$DRY_RUN" -eq 1 ]; then
  echo
  echo "[--dry-run] Would run:"
  echo "  1. aws secretsmanager get-secret-value --secret-id ${SECRET_ID} --region ${REGION}"
  echo "  2. jq --arg k '<new-key>' '. + {anthropic_api_key: \$k}'"
  echo "  3. aws secretsmanager put-secret-value --secret-id ${SECRET_ID} --region ${REGION} --secret-string <merged JSON>"
  echo "  4. aws secretsmanager get-secret-value --secret-id ${SECRET_ID} --region ${REGION}   (verify)"
  echo "No AWS calls made."
  exit 0
fi

command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required (brew install jq)." >&2; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "ERROR: aws CLI is required." >&2; exit 1; }

echo
echo "1/3 Reading current secret..."
CURRENT_JSON=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --region "$REGION" --query SecretString --output text)

# Same merge the manual procedure in docs/SECRETS_ROTATION.md uses — preserves any
# other fields in the blob untouched. If the current value isn't valid JSON (a bare
# string secret), fall back to a fresh single-field object rather than failing closed.
if echo "$CURRENT_JSON" | jq -e . >/dev/null 2>&1; then
  MERGED_JSON=$(echo "$CURRENT_JSON" | jq --arg k "$NEW_KEY" '. + {anthropic_api_key: $k}')
else
  echo "  (current secret is not JSON — writing a fresh {\"anthropic_api_key\": ...} object)"
  MERGED_JSON=$(jq -n --arg k "$NEW_KEY" '{anthropic_api_key: $k}')
fi

echo "2/3 Writing new secret value..."
aws secretsmanager put-secret-value --secret-id "$SECRET_ID" --region "$REGION" --secret-string "$MERGED_JSON" >/dev/null

echo "3/3 Verifying — reading it back the way consumer lambdas parse it..."
READBACK=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --region "$REGION" --query SecretString --output text)
READBACK_KEY=$(echo "$READBACK" | jq -r '.anthropic_api_key // empty')

if [ -z "$READBACK_KEY" ]; then
  echo "ERROR: readback did not find an anthropic_api_key field — verification FAILED." >&2
  exit 1
fi
if [ "$READBACK_KEY" != "$NEW_KEY" ]; then
  echo "ERROR: readback key does not match what was written — verification FAILED." >&2
  exit 1
fi
echo "  OK — a consumer reading this secret now gets: $(_mask "$READBACK_KEY")"

cat <<EOF

Done. ${SECRET_ID} is rotated. Remaining human steps (docs/SECRETS_ROTATION.md):
  - Revoke the OLD key at https://console.anthropic.com/settings/keys (irreversible —
    do this only after confirming the new key works, e.g. next daily-brief run or
    CloudWatch metric LifePlatform/AI AnthropicAPISuccess).
  - Warm containers on the direct-API consumer lambdas (field_notes_lambda,
    ai_expert_analyzer_lambda, daily_insight_compute_lambda, partner_email_lambda,
    monday_compass_lambda, data_reconciliation_lambda, pipeline_health_check_lambda)
    keep the OLD key cached until their next cold start. Force one if you need the
    new key live immediately:
      aws lambda update-function-configuration --function-name <fn> \\
        --environment "Variables={ROTATE_BUST=\$(date +%s)}" --region ${REGION}
  - The freshness-checker / remediation-agent staleness reminder (#1329) clears once
    this secret's LastChangedDate has advanced past MANUAL_ROTATION_STALE_DAYS ago —
    i.e. immediately after this run.
EOF
