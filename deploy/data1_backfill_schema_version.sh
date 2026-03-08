#!/usr/bin/env bash
# DATA-1: Backfill schema_version=1 on all existing DynamoDB items that lack it.
#
# Scans all items under USER#matthew prefix and adds schema_version=1
# to any item that doesn't already have it.
#
# Safe to re-run (conditional update — only updates items missing the field).
# Runtime estimate: ~2-5 minutes depending on item count.
#
# Run from project root: bash deploy/data1_backfill_schema_version.sh

set -euo pipefail
REGION="us-west-2"
TABLE="life-platform"
USER_PREFIX="USER#matthew"

echo "=== DATA-1: Backfilling schema_version=1 on all DynamoDB items ==="
echo "Table: $TABLE | Region: $REGION"
echo ""

python3 << 'PYEOF'
import boto3
import sys
from boto3.dynamodb.conditions import Attr

REGION    = "us-west-2"
TABLE     = "life-platform"
USER_PREFIX = "USER#matthew"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE)

scanned = 0
updated = 0
skipped = 0
errors  = 0

print("Scanning for items missing schema_version...")

paginator = dynamodb.meta.client.get_paginator("scan")
pages = paginator.paginate(
    TableName=TABLE,
    FilterExpression="begins_with(pk, :prefix) AND attribute_not_exists(schema_version)",
    ExpressionAttributeValues={":prefix": {"S": USER_PREFIX}},
    ProjectionExpression="pk, sk",
)

items_to_update = []
for page in pages:
    for item in page.get("Items", []):
        items_to_update.append({
            "pk": item["pk"]["S"],
            "sk": item["sk"]["S"],
        })
    scanned += page.get("Count", 0)

print(f"  Found {len(items_to_update)} items to update (scanned {scanned} total)")
print()

for i, key in enumerate(items_to_update, 1):
    try:
        table.update_item(
            Key={"pk": key["pk"], "sk": key["sk"]},
            UpdateExpression="SET schema_version = :v",
            ConditionExpression=Attr("schema_version").not_exists(),
            ExpressionAttributeValues={":v": 1},
        )
        updated += 1
        if updated % 100 == 0:
            print(f"  ... updated {updated}/{len(items_to_update)}")
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        skipped += 1  # already has schema_version
    except Exception as e:
        errors += 1
        print(f"  ERROR on {key['pk']} / {key['sk']}: {e}")

print()
print(f"=== Done ===")
print(f"  Updated:  {updated}")
print(f"  Skipped:  {skipped} (already had schema_version)")
print(f"  Errors:   {errors}")
PYEOF
