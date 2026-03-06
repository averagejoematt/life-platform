#!/usr/bin/env python3
"""
setup_garmin_auth.py — Interactive first-auth for Garmin Connect using garth directly.
"""

import json
import getpass
import sys
import boto3

SECRET_NAME = "life-platform/garmin"
REGION      = "us-west-2"

def main():
    print("=" * 60)
    print("Garmin Connect — First-time auth setup")
    print("=" * 60)
    print()

    try:
        import garth
    except ImportError:
        print("ERROR: Required libraries not installed.")
        print("Run: pip install garminconnect garth boto3")
        sys.exit(1)

    email    = input("Garmin Connect email: ").strip()
    password = getpass.getpass("Garmin Connect password: ")

    print()
    print("Logging in to Garmin Connect...")
    print("(If Garmin sends an MFA code, enter it when prompted)")
    print()

    try:
        garth.login(email, password)
        print("Login successful!")
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)

    # Capture tokens
    try:
        garth_tokens = garth.client.dumps()
        print(f"OAuth tokens captured ({len(garth_tokens)} bytes)")
    except Exception as e:
        print(f"Warning: could not capture tokens: {e}")
        garth_tokens = ""

    # Test a data call
    print()
    print("Testing data access...")
    try:
        profile = garth.client.connectapi("/userprofile-service/socialProfile")
        name = profile.get("displayName") or profile.get("fullName") or "unknown"
        print(f"Connected as: {name}")
    except Exception as e:
        print(f"Warning: profile fetch failed ({e}) — continuing anyway")

    # Store secret
    secret = {
        "email":        email,
        "password":     password,
        "garth_tokens": garth_tokens,
    }

    secrets_client = boto3.client("secretsmanager", region_name=REGION)

    try:
        secrets_client.update_secret(
            SecretId=SECRET_NAME,
            SecretString=json.dumps(secret),
        )
        print(f"\nSecret updated: {SECRET_NAME}")
    except secrets_client.exceptions.ResourceNotFoundException:
        secrets_client.create_secret(
            Name=SECRET_NAME,
            Description="Garmin Connect credentials and OAuth tokens for Life Platform",
            SecretString=json.dumps(secret),
        )
        print(f"\nSecret created: {SECRET_NAME}")

    print()
    print("=" * 60)
    print("Setup complete! Now run:")
    print()
    print("  aws lambda invoke \\")
    print("    --function-name garmin-data-ingestion \\")
    print("    --payload '{\"date\": \"2026-02-22\"}' \\")
    print("    --cli-binary-format raw-in-base64-out \\")
    print("    --region us-west-2 /tmp/garmin_test.json && cat /tmp/garmin_test.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
