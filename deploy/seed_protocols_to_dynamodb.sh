#!/bin/bash
set -euo pipefail

# Seed DynamoDB with protocol data from site/config/protocols.json.
#
# #3621 box 5: the body moved to deploy/seed_protocols.py. This is now a thin delegate —
# the write goes through experiment.protocol_levers.build_protocol_item, which REFUSES
# any lever whose `spawned_by` is absent or unrecognised, and a refusal inside a quoted
# `python3 -c` heredoc is one nothing can unit-test.
#
# DRY-RUN BY DEFAULT (the heredoc had none); pass --apply to commit. Extra arguments are
# forwarded verbatim.

TABLE="life-platform"
REGION="us-west-2"
PK="USER#matthew#SOURCE#protocols"

cd "$(dirname "$0")/.."

echo "=== Seeding protocols to DynamoDB ==="
echo "Table: $TABLE | Region: $REGION"
python3 deploy/seed_protocols.py "$@"

echo ""
echo "Verify: aws dynamodb query --table-name $TABLE --key-condition-expression 'pk = :pk' --expression-attribute-values '{\":pk\":{\"S\":\"$PK\"}}' --query 'Items[].sk.S' --output text --region $REGION --no-cli-pager"
