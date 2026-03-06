#!/usr/bin/env python3
"""
find_garmin_earliest.py — Binary search to find the earliest date Garmin has data for you.

Uses ~20 API calls instead of scanning thousands of empty days.

Usage:
  source /tmp/garmin-venv/bin/activate
  python3 find_garmin_earliest.py
"""

import json
import time
import boto3
from datetime import datetime, date, timedelta

SECRET_NAME = "life-platform/garmin"
REGION      = "us-west-2"

def get_secret():
    client = boto3.client("secretsmanager", region_name=REGION)
    resp = client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])

def get_garmin_client(secret):
    import garth
    from garminconnect import Garmin
    if secret.get("garth_tokens"):
        garth.client.loads(secret["garth_tokens"])
    api = Garmin(email=secret["email"], password=secret["password"])
    api.garth = garth.client
    profile = garth.client.connectapi("/userprofile-service/socialProfile")
    api.display_name = profile.get("displayName") or profile.get("userName")
    return api

def has_data(api, date_str):
    """Return True if ANY Garmin endpoint returns data for this date."""
    # Try user summary first (most broadly available)
    try:
        data = api.get_user_summary(date_str)
        if data:
            steps = data.get("totalSteps")
            rhr   = data.get("restingHeartRate")
            if (steps and steps > 0) or (rhr and rhr > 0):
                return True
    except Exception:
        pass

    # Fallback: try stress data
    try:
        data = api.get_stress_data(date_str)
        if data and data.get("avgStressLevel", -1) >= 0:
            return True
    except Exception:
        pass

    return False

def binary_search_earliest(api, low: date, high: date) -> date | None:
    """
    Binary search between low and high to find the earliest date with data.
    Returns the earliest date found, or None if no data in range.
    """
    # First confirm there's data somewhere in the range
    print(f"  Checking if any data exists between {low} and {high}...")
    if not has_data(api, high.strftime("%Y-%m-%d")):
        print(f"  No data found at {high} — checking midpoint...")

    best_with_data = None

    while low <= high:
        mid = low + (high - low) // 2
        mid_str = mid.strftime("%Y-%m-%d")

        result = has_data(api, mid_str)
        status = "✓ DATA" if result else "· empty"
        print(f"  {mid_str}  {status}  (window: {low} → {high})")
        time.sleep(1.5)

        if result:
            best_with_data = mid
            high = mid - timedelta(days=1)  # search earlier
        else:
            low = mid + timedelta(days=1)   # search later

    return best_with_data

def main():
    print("=" * 60)
    print("Garmin earliest data finder")
    print("=" * 60)
    print()

    secret = get_secret()
    api    = get_garmin_client(secret)
    print(f"Connected as: {api.display_name}")
    print()

    # Binary search from 2004-01-01 to today
    low  = date(2004, 1, 1)
    high = date.today()

    print("Running binary search (~20 API calls)...")
    print()
    earliest = binary_search_earliest(api, low, high)

    print()
    print("=" * 60)
    if earliest:
        print(f"Earliest data found: {earliest}")
        print()
        print(f"Restart backfill from this date:")
        print(f"  python3 backfill_garmin.py --start {earliest}")
    else:
        print("No data found in entire range (2004–today).")
        print("Check that your Garmin account credentials are correct.")
    print("=" * 60)

if __name__ == "__main__":
    main()
