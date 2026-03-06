#!/usr/bin/env python3
"""
OneDrive OAuth2 Setup for Life Platform.

Uses Microsoft's device code flow (no redirect URI needed — works from terminal).
Stores refresh token in AWS Secrets Manager for Lambda use.

Prerequisites:
  1. Go to https://portal.azure.com → Azure Active Directory → App registrations
  2. Click "New registration"
     - Name: "Life Platform OneDrive"
     - Supported account types: "Personal Microsoft accounts only"
     - Redirect URI: leave blank (we use device code flow)
  3. Click "Register"
  4. Copy the "Application (client) ID" — you'll need it below
  5. Go to "API permissions" → Add permission → Microsoft Graph → Delegated:
     - Files.Read
     - offline_access
  6. Run this script with: python3 setup_onedrive_auth.py

The script will:
  - Prompt for your client_id
  - Start device code flow (you'll see a code to enter at microsoft.com/devicelogin)
  - Exchange the code for tokens
  - Store the refresh token in Secrets Manager (life-platform/onedrive)

Usage: python3 setup_onedrive_auth.py
"""

import json
import time
import urllib.request
import urllib.parse
import boto3

REGION = "us-west-2"
SECRET_NAME = "life-platform/onedrive"
ONEDRIVE_FOLDER = "life-platform"

# Microsoft identity platform endpoints for consumer accounts
AUTHORITY = "https://login.microsoftonline.com/consumers"
DEVICE_CODE_URL = f"{AUTHORITY}/oauth2/v2.0/devicecode"
TOKEN_URL = f"{AUTHORITY}/oauth2/v2.0/token"
SCOPE = "Files.Read offline_access"


def device_code_flow(client_id):
    """Initiate device code flow and return tokens."""

    # Step 1: Request device code
    print("\n📱 Requesting device code...")
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "scope": SCOPE,
    }).encode()
    req = urllib.request.Request(DEVICE_CODE_URL, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        dc = json.loads(resp.read())

    print(f"\n{'='*60}")
    print(f"  Open: {dc['verification_uri']}")
    print(f"  Enter code: {dc['user_code']}")
    print(f"{'='*60}")
    print(f"\nWaiting for you to authorize (expires in {dc['expires_in']}s)...")

    # Step 2: Poll for token
    interval = dc.get("interval", 5)
    device_code = dc["device_code"]

    while True:
        time.sleep(interval)
        token_data = urllib.parse.urlencode({
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant_type:device_code",
        }).encode()
        token_req = urllib.request.Request(TOKEN_URL, data=token_data, method="POST")
        try:
            with urllib.request.urlopen(token_req) as resp:
                tokens = json.loads(resp.read())
                return tokens
        except urllib.error.HTTPError as e:
            error_body = json.loads(e.read())
            error_code = error_body.get("error", "")
            if error_code == "authorization_pending":
                print("  ⏳ Waiting for authorization...")
                continue
            elif error_code == "slow_down":
                interval += 5
                continue
            elif error_code == "authorization_declined":
                print("  ❌ Authorization declined.")
                raise SystemExit(1)
            elif error_code == "expired_token":
                print("  ❌ Device code expired. Run the script again.")
                raise SystemExit(1)
            else:
                print(f"  ❌ Error: {error_body}")
                raise


def verify_access(access_token):
    """Verify we can list files in the target OneDrive folder."""
    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{ONEDRIVE_FOLDER}:/children?$top=5"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            files = data.get("value", [])
            print(f"\n✅ OneDrive access verified! Found {len(files)} items in /{ONEDRIVE_FOLDER}/:")
            for f in files:
                size = f.get("size", 0)
                name = f.get("name", "?")
                print(f"   {'📁' if 'folder' in f else '📄'} {name} ({size:,} bytes)")
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"\n⚠️  Folder /{ONEDRIVE_FOLDER}/ not found on OneDrive.")
            print(f"   Create it on OneDrive first, then re-run this script.")
            print(f"   (Or the Lambda will create-on-read — the folder just needs to exist.)")
            return True  # Auth works, folder just doesn't exist yet
        error_body = e.read().decode()
        print(f"\n❌ OneDrive access failed: HTTP {e.code}")
        print(f"   {error_body[:200]}")
        return False


def store_secret(client_id, refresh_token):
    """Store credentials in Secrets Manager."""
    secrets = boto3.client("secretsmanager", region_name=REGION)
    secret_value = json.dumps({
        "client_id": client_id,
        "refresh_token": refresh_token,
        "folder": ONEDRIVE_FOLDER,
    })

    try:
        secrets.describe_secret(SecretId=SECRET_NAME)
        secrets.update_secret(SecretId=SECRET_NAME, SecretString=secret_value)
        print(f"\n✅ Updated secret: {SECRET_NAME}")
    except secrets.exceptions.ResourceNotFoundException:
        secrets.create_secret(
            Name=SECRET_NAME,
            Description="OneDrive OAuth2 refresh token for MacroFactor CSV polling",
            SecretString=secret_value,
        )
        print(f"\n✅ Created secret: {SECRET_NAME}")


def main():
    print("=" * 60)
    print("  OneDrive OAuth2 Setup for Life Platform")
    print("=" * 60)
    print()
    print("Prerequisites:")
    print("  1. Register an app at https://portal.azure.com")
    print("     → Azure AD → App registrations → New registration")
    print("     → Personal Microsoft accounts only")
    print("  2. Add API permissions: Files.Read + offline_access")
    print()

    client_id = input("Enter your Application (client) ID: ").strip()
    if not client_id:
        print("❌ Client ID required.")
        return

    tokens = device_code_flow(client_id)

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    if not refresh_token:
        print("❌ No refresh token received. Ensure 'offline_access' scope is granted.")
        return

    print(f"\n✅ Tokens received!")
    print(f"   Access token: {access_token[:20]}...")
    print(f"   Refresh token: {refresh_token[:20]}...")

    # Verify
    verify_access(access_token)

    # Store
    store_secret(client_id, refresh_token)

    print()
    print("=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print()
    print(f"  Secret: {SECRET_NAME}")
    print(f"  Folder: OneDrive:/{ONEDRIVE_FOLDER}/")
    print(f"  Next: run deploy_onedrive_poll.sh")
    print()


if __name__ == "__main__":
    main()
