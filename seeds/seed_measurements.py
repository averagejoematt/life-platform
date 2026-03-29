"""Seed Day 1 body measurements to DynamoDB. Validates schema and derived fields."""
import boto3
from decimal import Decimal
from datetime import datetime, timezone

TABLE = "life-platform"
REGION = "us-west-2"
PK = "USER#matthew#SOURCE#measurements"

ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)

# Fetch height from profile
profile = table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"}).get("Item", {})
height_in = int(profile.get("height_inches", 69))
print(f"Height from profile: {height_in} inches")

# Day 1 measurements (2026-03-29, captured by Brittany)
date_str = "2026-03-29"
raw = {
    "neck_in": Decimal("17.0"),
    "chest_in": Decimal("49.0"),
    "waist_narrowest_in": Decimal("49.5"),
    "waist_navel_in": Decimal("52.0"),
    "hips_in": Decimal("55.5"),
    "bicep_relaxed_left_in": Decimal("16.0"),
    "bicep_relaxed_right_in": Decimal("17.0"),
    "bicep_flexed_left_in": Decimal("17.5"),
    "bicep_flexed_right_in": Decimal("18.0"),
    "calf_left_in": Decimal("19.0"),
    "calf_right_in": Decimal("19.0"),
    "thigh_left_in": Decimal("30.5"),
    "thigh_right_in": Decimal("30.0"),
}

# Derived fields
waist_height_ratio = round(Decimal(str(float(raw["waist_navel_in"]) / height_in)), 4)
bilateral_bicep = abs(raw["bicep_relaxed_right_in"] - raw["bicep_relaxed_left_in"])
bilateral_thigh = abs(raw["thigh_right_in"] - raw["thigh_left_in"])
limb_avg = round((raw["bicep_relaxed_left_in"] + raw["bicep_relaxed_right_in"] +
                   raw["thigh_left_in"] + raw["thigh_right_in"]) / 4, 3)
trunk_sum = raw["waist_navel_in"] + raw["waist_narrowest_in"]

# Count existing sessions for session_number
resp = table.query(
    KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(PK),
    Select="COUNT",
)
session_number = resp.get("Count", 0) + 1

item = {
    "pk": PK,
    "sk": f"DATE#{date_str}",
    "date": date_str,
    "unit": "in",
    "session_number": session_number,
    "measured_by": "brittany",
    **raw,
    "waist_height_ratio": waist_height_ratio,
    "bilateral_symmetry_bicep_in": bilateral_bicep,
    "bilateral_symmetry_thigh_in": bilateral_thigh,
    "limb_avg_in": limb_avg,
    "trunk_sum_in": trunk_sum,
    "ingested_at": datetime.now(timezone.utc).isoformat(),
    "source_file": "seed_measurements.py (Day 1 baseline)",
}

table.put_item(Item=item)

print(f"\nSession {session_number} written: DATE#{date_str}")
print(f"  waist_height_ratio: {waist_height_ratio} (target <0.500)")
print(f"  bilateral_symmetry_bicep: {bilateral_bicep} in")
print(f"  bilateral_symmetry_thigh: {bilateral_thigh} in")
print(f"  trunk_sum: {trunk_sum} in")
print(f"  limb_avg: {limb_avg} in")
