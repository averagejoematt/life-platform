#!/usr/bin/env python3
"""
Seed demo_mode_rules into the DynamoDB profile.
Run once. Rules can be updated anytime via DynamoDB or Claude.
"""

import boto3
from decimal import Decimal
import json

TABLE = "life-platform"

DEMO_RULES = {
    "redact_patterns": [
        "marijuana", "thc", "cannabis", "weed", "edible", "edibles",
        "alcohol", "bourbon", "whiskey", "wine", "beer", "drinks",
        "drunk", "hungover", "hangover"
    ],
    "replace_values": {
        "weight_lbs": "•••",
        "calories": "•,•••",
        "protein": "•••"
    },
    "hide_sections": [
        "journal_pulse",
        "journal_coach",
        "weight_phase"
    ],
    "subject_prefix": "[DEMO]"
}


def main():
    dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
    table = dynamodb.Table(TABLE)

    # Convert to Decimal-safe format
    rules_json = json.loads(json.dumps(DEMO_RULES), parse_float=Decimal)

    table.update_item(
        Key={"pk": "USER#matthew", "sk": "PROFILE#v1"},
        UpdateExpression="SET demo_mode_rules = :rules",
        ExpressionAttributeValues={":rules": rules_json},
    )

    # Verify
    result = table.get_item(
        Key={"pk": "USER#matthew", "sk": "PROFILE#v1"},
        ProjectionExpression="demo_mode_rules"
    ).get("Item", {})

    rules = result.get("demo_mode_rules", {})
    print("✅ demo_mode_rules seeded to profile:")
    print(f"  redact_patterns: {len(rules.get('redact_patterns', []))} words")
    print(f"  replace_values: {list(rules.get('replace_values', {}).keys())}")
    print(f"  hide_sections: {rules.get('hide_sections', [])}")
    print(f"  subject_prefix: {rules.get('subject_prefix', '')}")
    print()
    print("To update later, just modify the profile in DynamoDB — no deploy needed.")
    print("To trigger demo: aws lambda invoke --function-name daily-brief --payload '{\"demo_mode\": true}' ...")


if __name__ == "__main__":
    main()
