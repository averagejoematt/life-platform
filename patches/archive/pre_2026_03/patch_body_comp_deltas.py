#!/usr/bin/env python3
"""
Patch withings_lambda.py to add body composition delta tracking.

New fields added to each Withings daily record:
  - lean_mass_delta_14d: change in lean mass vs 14 days ago (lbs)
  - fat_mass_delta_14d: change in fat mass vs 14 days ago (lbs)

Run this to apply the patch, then deploy via deploy_body_comp_deltas.sh.
"""

SOURCE = "withings_lambda.py"

def apply():
    with open(SOURCE, "r") as f:
        code = f.read()

    # ── 1. Add delta computation function before save_to_dynamo ───────────────
    delta_func = '''
# ── Body composition delta helpers (derived metric A2) ─────────────────────

def compute_body_comp_deltas(date_str, measurements):
    """
    Query the Withings record from ~14 days ago and compute lean/fat mass deltas.
    Uses nearest record within a 7-day search window (days 11-17 before today).
    Returns dict with delta fields to merge into measurements.
    """
    from boto3.dynamodb.conditions import Key

    deltas = {}
    current_lean = measurements.get("fat_free_mass_lbs")  # Withings calls lean mass "fat_free_mass"
    current_fat = measurements.get("fat_mass_lbs")

    if current_lean is None and current_fat is None:
        return deltas

    # Search window: 11-17 days ago (centered on 14)
    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    search_start = (target_dt - timedelta(days=17)).strftime("%Y-%m-%d")
    search_end = (target_dt - timedelta(days=11)).strftime("%Y-%m-%d")

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(DYNAMO_PK)
            & Key("sk").between(f"DATE#{search_start}", f"DATE#{search_end}"),
        ProjectionExpression="fat_free_mass_lbs, fat_mass_lbs, #d",
        ExpressionAttributeNames={"#d": "date"},
        ScanIndexForward=False,  # newest first (closest to 14 days ago)
        Limit=1,
    )

    items = resp.get("Items", [])
    if not items:
        print(f"  No Withings record found in {search_start} to {search_end} for delta")
        return deltas

    prev = items[0]
    prev_date = prev.get("date", "?")

    if current_lean is not None and prev.get("fat_free_mass_lbs") is not None:
        delta = round(float(current_lean) - float(prev["fat_free_mass_lbs"]), 2)
        deltas["lean_mass_delta_14d"] = delta
        print(f"  lean_mass_delta_14d: {delta:+.2f} lbs (vs {prev_date})")

    if current_fat is not None and prev.get("fat_mass_lbs") is not None:
        delta = round(float(current_fat) - float(prev["fat_mass_lbs"]), 2)
        deltas["fat_mass_delta_14d"] = delta
        print(f"  fat_mass_delta_14d: {delta:+.2f} lbs (vs {prev_date})")

    return deltas


'''

    # Insert before save_to_dynamo function
    code = code.replace(
        "def save_to_dynamo(date_str: str, measurements: dict):",
        delta_func + "def save_to_dynamo(date_str: str, measurements: dict):",
    )

    # ── 2. Add delta computation call in lambda_handler before save_to_dynamo ─
    code = code.replace(
        '        save_to_dynamo(date_str, measurements)',
        '''        # Compute body composition deltas (derived metric A2)
        deltas = compute_body_comp_deltas(date_str, measurements)
        measurements.update(deltas)

        save_to_dynamo(date_str, measurements)''',
    )

    # ── Write patched file ────────────────────────────────────────────────────
    with open(SOURCE, "w") as f:
        f.write(code)

    print("✅ withings_lambda.py patched with body composition deltas")
    print("   New fields: lean_mass_delta_14d, fat_mass_delta_14d")
    print("   Next: run deploy_body_comp_deltas.sh")


if __name__ == "__main__":
    apply()
