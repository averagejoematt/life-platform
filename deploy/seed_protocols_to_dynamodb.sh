#!/bin/bash
set -euo pipefail

# Seed DynamoDB with protocol data from site/config/protocols.json
# This eliminates the S3 fallback on every /api/protocols request.

TABLE="life-platform"
REGION="us-west-2"
PK="USER#matthew#SOURCE#protocols"
CONFIG="site/config/protocols.json"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: $CONFIG not found. Run from project root."
  exit 1
fi

echo "=== Seeding protocols to DynamoDB ==="
echo "Table: $TABLE | Region: $REGION"
echo "Source: $CONFIG"

python3 -c "
import json, boto3
from decimal import Decimal

with open('$CONFIG') as f:
    data = json.load(f)

dynamodb = boto3.resource('dynamodb', region_name='$REGION')
table = dynamodb.Table('$TABLE')

protocols = data.get('protocols', [])
print(f'Found {len(protocols)} protocols')

for p in protocols:
    pk = '$PK'
    sk = f'PROTOCOL#{p[\"id\"]}'

    # Convert floats to Decimal for DynamoDB
    item = json.loads(json.dumps(p), parse_float=Decimal)
    item['pk'] = pk
    item['sk'] = sk

    table.put_item(Item=item)
    print(f'  + {p[\"id\"]}: {p[\"name\"]}')

print(f'Done. {len(protocols)} protocols seeded.')
"

echo ""
echo "Verify: aws dynamodb query --table-name $TABLE --key-condition-expression 'pk = :pk' --expression-attribute-values '{\":pk\":{\"S\":\"$PK\"}}' --query 'Items[].sk.S' --output text --region $REGION --no-cli-pager"
