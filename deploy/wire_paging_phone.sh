#!/usr/bin/env bash
# ADR-143 (#1333): subscribe the paging phone to life-platform-paging (SMS).
#
# The number lives ONLY at SSM /life-platform/paging-phone (SecureString) —
# CloudFormation cannot resolve a SecureString into an SNS subscription
# endpoint, so this script wires it out-of-band. Idempotent: if any SMS
# subscription already exists on the topic, it does nothing (one phone is the
# posture; rotating the number = unsubscribe old, re-run this).
#
# Usage: bash deploy/wire_paging_phone.sh
set -euo pipefail

REGION="us-west-2"
ACCT="205930651321"
TOPIC_ARN="arn:aws:sns:${REGION}:${ACCT}:life-platform-paging"
PARAM="/life-platform/paging-phone"

existing=$(aws sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" --region "$REGION" \
  --query "Subscriptions[?Protocol=='sms'] | length(@)" --output text)

if [[ "$existing" != "0" ]]; then
  echo "✅ paging topic already has ${existing} SMS subscription(s) — nothing to do."
  echo "   (rotate: unsubscribe the old one, then re-run; verify with:"
  echo "    aws sns list-subscriptions-by-topic --topic-arn $TOPIC_ARN)"
  exit 0
fi

phone=$(aws ssm get-parameter --name "$PARAM" --with-decryption --region "$REGION" \
  --query Parameter.Value --output text)

if [[ -z "$phone" || "$phone" == "None" ]]; then
  echo "❌ $PARAM is empty/missing — provision the SecureString first." >&2
  exit 1
fi

aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol sms \
  --notification-endpoint "$phone" --region "$REGION" --output text >/dev/null
echo "✅ SMS subscription created on life-platform-paging (number redacted — from $PARAM)."
