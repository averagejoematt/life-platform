#!/usr/bin/env python3
"""
Patch whoop_lambda.py to add sleep onset consistency tracking.

New fields added to each Whoop daily record:
  - sleep_onset_minutes: minutes from midnight (UTC) of sleep_start
  - sleep_onset_consistency_7d: StdDev of last 7 days' sleep onset times (minutes)

Run this to apply the patch, then deploy via deploy_sleep_consistency.sh.
"""

import re

SOURCE = "whoop_lambda.py"

def apply():
    with open(SOURCE, "r") as f:
        code = f.read()

    # ── 1. Add import for statistics at the top ───────────────────────────────
    code = code.replace(
        "from decimal import Decimal",
        "from decimal import Decimal\nimport statistics",
    )

    # ── 2. Add helper functions before the Lambda entry point ─────────────────
    helper_block = '''

# ── Sleep onset consistency helpers ──────────────────────────────────────────

def _sleep_onset_minutes(iso_timestamp):
    """
    Convert an ISO sleep_start timestamp to minutes from midnight (UTC).
    Returns int or None if parsing fails.
    """
    if not iso_timestamp:
        return None
    try:
        # Handle both 'Z' suffix and '+00:00' formats
        ts = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        return dt.hour * 60 + dt.minute
    except (ValueError, AttributeError):
        return None


def _compute_sleep_consistency(table, date_str, current_onset_minutes, log=print):
    """
    Query last 6 Whoop records before date_str, combine with today's onset,
    compute 7-day StdDev of sleep onset times.
    
    Handles midnight wraparound: if range > 720 min, shift values crossing midnight
    so that e.g. 23:30 (1410) and 00:30 (30) are treated as 60 min apart.
    
    Returns StdDev in minutes (float) or None if <3 data points.
    """
    if current_onset_minutes is None:
        return None

    # Query previous 6 days of sleep_onset_minutes
    from boto3.dynamodb.conditions import Key
    resp = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#whoop")
            & Key("sk").lt(f"DATE#{date_str}"),
        ProjectionExpression="sleep_onset_minutes",
        ScanIndexForward=False,  # newest first
        Limit=6,
    )

    onsets = [current_onset_minutes]
    for item in resp.get("Items", []):
        val = item.get("sleep_onset_minutes")
        if val is not None:
            onsets.append(int(val))

    if len(onsets) < 3:
        log(f"[INFO] Sleep consistency: only {len(onsets)} data points, need ≥3")
        return None

    # Handle midnight wraparound using circular adjustment
    # If spread is >720 min, some values are on opposite sides of midnight
    min_val = min(onsets)
    max_val = max(onsets)
    if max_val - min_val > 720:
        # Shift values < 720 up by 1440 (treat early morning as "late night")
        onsets = [v + 1440 if v < 720 else v for v in onsets]

    sd = statistics.stdev(onsets)
    log(f"[INFO] Sleep consistency: {len(onsets)} points, StdDev={sd:.1f} min")
    return round(sd, 1)

'''

    # Insert before the Lambda entry point
    code = code.replace(
        "# ── Lambda entry point",
        helper_block + "# ── Lambda entry point",
    )

    # ── 3. Add sleep onset computation after normalization, before put_item ───
    enrichment_block = '''
    # ── Sleep onset consistency (derived metric A1) ────────────────────────────
    sleep_start_val = normalized.get("sleep_start")
    if sleep_start_val:
        onset_min = _sleep_onset_minutes(sleep_start_val)
        if onset_min is not None:
            normalized["sleep_onset_minutes"] = onset_min
            log(f"[INFO] sleep_onset_minutes: {onset_min}")
            consistency = _compute_sleep_consistency(table, date_str, onset_min, log)
            if consistency is not None:
                normalized["sleep_onset_consistency_7d"] = Decimal(str(consistency))
                log(f"[INFO] sleep_onset_consistency_7d: {consistency}")

'''

    code = code.replace(
        "    # ── DynamoDB: daily item ───────────────────────────────────────────────────",
        enrichment_block + "    # ── DynamoDB: daily item ───────────────────────────────────────────────────",
    )

    # ── 4. Add new fields to ALL_DAILY_FIELDS ─────────────────────────────────
    code = code.replace(
        '        # cycle\n        "strain", "kilojoule", "average_heart_rate", "max_heart_rate",',
        '        # cycle\n        "strain", "kilojoule", "average_heart_rate", "max_heart_rate",\n        # derived metrics\n        "sleep_onset_minutes", "sleep_onset_consistency_7d",',
    )

    # ── Write patched file ────────────────────────────────────────────────────
    with open(SOURCE, "w") as f:
        f.write(code)

    print("✅ whoop_lambda.py patched with sleep onset consistency")
    print("   New fields: sleep_onset_minutes, sleep_onset_consistency_7d")
    print("   Next: run deploy_sleep_consistency.sh")


if __name__ == "__main__":
    apply()
