#!/usr/bin/env python3
"""
setup_eightsleep_auth.py — One-time Eight Sleep authentication setup.

Run this ONCE from your local machine before deploying the Lambda.
It logs in, captures the token + user_id, and saves everything to
Secrets Manager as life-platform/eightsleep.

Usage:
    python3 setup_eightsleep_auth.py
"""

import getpass
import json
import urllib.request

import boto3

SECRET_NAME         = "life-platform/eightsleep"
REGION              = "us-west-2"
CLIENT_API          = "https://client-api.8slp.net"
AUTH_API            = "https://auth-api.8slp.net"
KNOWN_CLIENT_ID     = "0894c7f33bb94800a03f1f4df13a4f38"
KNOWN_CLIENT_SECRET = "f0954a3ed5763ba3d06834c73731a32f15f168f47d4f164751275def86db0c76"


def login(email, password):
    payload = json.dumps({
        "client_id":     KNOWN_CLIENT_ID,
        "client_secret": KNOWN_CLIENT_SECRET,
        "grant_type":    "password",
        "username":      email,
        "password":      password,
    }).encode()
    req = urllib.request.Request(
        f"{AUTH_API}/v1/tokens",
        data=payload,
        headers={
            "Content-Type":    "application/json",
            "Accept":          "application/json",
            "Accept-Encoding": "gzip",
            "user-agent":      "okhttp/4.9.3",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_user_id(access_token):
    req = urllib.request.Request(
        f"{CLIENT_API}/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["user"]["userId"]


def main():
    print("Eight Sleep Authentication Setup")
    print("=" * 50)
    print(f"Saves credentials to Secrets Manager: {SECRET_NAME}  ({REGION})")
    print()

    email    = input("Eight Sleep email: ").strip()
    password = getpass.getpass("Eight Sleep password: ")
    bed_side = input("Your bed side [left/right] (default: left): ").strip().lower() or "left"
    tz       = input("Your timezone (default: America/Los_Angeles): ").strip() or "America/Los_Angeles"

    if bed_side not in ("left", "right"):
        print("Invalid bed side — defaulting to 'left'")
        bed_side = "left"

    print()
    print("Logging in to Eight Sleep...", flush=True)

    try:
        token_data = login(email, password)
    except Exception as e:
        print(f"[ERROR] Login failed: {e}")
        print("\nCommon causes:")
        print("  • Wrong email or password")
        print("  • API rate limiting (wait a few minutes and try again)")
        return

    access_token  = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    user_id       = token_data.get("userId", "")

    if not user_id:
        print("Resolving user_id from /v1/users/me ...", flush=True)
        try:
            user_id = get_user_id(access_token)
        except Exception as e:
            print(f"[WARNING] Could not resolve user_id: {e}")
            print("The Lambda will resolve it automatically on first run.")

    print(f"✓ Login successful")
    print(f"  user_id  : {user_id or '(will be resolved on first run)'}")
    print(f"  token    : {access_token[:20]}...")
    print(f"  bed_side : {bed_side}")
    print(f"  timezone : {tz}")
    print()

    secret_value = {
        "email":         email,
        "password":      password,
        "user_id":       user_id,
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "bed_side":      bed_side,
        "timezone":      tz,
    }

    secrets_client = boto3.client("secretsmanager", region_name=REGION)

    try:
        secrets_client.get_secret_value(SecretId=SECRET_NAME)
        print(f"Updating existing secret: {SECRET_NAME}")
        secrets_client.update_secret(
            SecretId=SECRET_NAME,
            SecretString=json.dumps(secret_value),
        )
    except secrets_client.exceptions.ResourceNotFoundException:
        print(f"Creating new secret: {SECRET_NAME}")
        secrets_client.create_secret(
            Name=SECRET_NAME,
            SecretString=json.dumps(secret_value),
        )

    print(f"✓ Secret saved to {SECRET_NAME}")
    print()
    print("Next steps:")
    print("  1. Test one night:  python3 -c \"")
    print("       from eightsleep_lambda import get_secret, ingest_day")
    print("       import json")
    print("       s = get_secret()")
    print("       print(json.dumps(ingest_day('2025-02-21', s), indent=2, default=str))\"")
    print("  2. Deploy Lambda:   bash deploy_eightsleep.sh")
    print("  3. Run backfill:    python3 backfill_eightsleep.py")


if __name__ == "__main__":
    main()
