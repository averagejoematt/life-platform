#!/usr/bin/env python3
"""
Dropbox OAuth2 Setup for Life Platform.

Prerequisites:
  1. Go to https://www.dropbox.com/developers/apps
  2. Create app → Scoped access → Full Dropbox → Name: "Life Platform Full"
  3. Permissions tab: enable files.metadata.read + files.content.read + files.content.write → Submit
  4. Copy App key and App secret from Settings tab
  5. Run: python3 setup_dropbox_auth.py

Usage: python3 setup_dropbox_auth.py
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import base64
import boto3

REGION = "us-west-2"
SECRET_NAME = "life-platform/dropbox"

AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


def get_auth_url(app_key):
    params = urllib.parse.urlencode({
        "client_id": app_key,
        "response_type": "code",
        "token_access_type": "offline",
        "scope": "account_info.read files.metadata.read files.metadata.write files.content.read files.content.write",
    })
    return f"{AUTH_URL}?{params}"


def exchange_code(app_key, app_secret, auth_code):
    data = urllib.parse.urlencode({
        "code": auth_code,
        "grant_type": "authorization_code",
    }).encode()
    credentials = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST", headers={
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def verify_access(access_token):
    """List Dropbox root to find available folders."""
    data = json.dumps({"path": "", "limit": 50}).encode()
    req = urllib.request.Request(
        "https://api.dropboxapi.com/2/files/list_folder",
        data=data, method="POST",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            entries = result.get("entries", [])
            print(f"\n✅ Dropbox access verified! Root folder contents:")
            for e in entries:
                tag = "📁" if e.get(".tag") == "folder" else "📄"
                print(f"   {tag} {e.get('name')} (path: {e.get('path_lower', '')})")
            if not entries:
                print("   (empty)")
            return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"\n❌ Dropbox access failed: HTTP {e.code}")
        print(f"   {error_body[:300]}")
        return False


def store_secret(app_key, app_secret, refresh_token):
    secrets = boto3.client("secretsmanager", region_name=REGION)
    secret_value = json.dumps({
        "app_key": app_key,
        "app_secret": app_secret,
        "refresh_token": refresh_token,
    })
    try:
        secrets.describe_secret(SecretId=SECRET_NAME)
        secrets.update_secret(SecretId=SECRET_NAME, SecretString=secret_value)
        print(f"\n✅ Updated secret: {SECRET_NAME}")
    except secrets.exceptions.ResourceNotFoundException:
        secrets.create_secret(
            Name=SECRET_NAME,
            Description="Dropbox OAuth2 credentials for MacroFactor CSV polling",
            SecretString=secret_value,
        )
        print(f"\n✅ Created secret: {SECRET_NAME}")


def main():
    print("=" * 60)
    print("  Dropbox OAuth2 Setup for Life Platform")
    print("=" * 60)
    print()

    app_key = input("Enter App key: ").strip()
    app_secret = input("Enter App secret: ").strip()
    if not app_key or not app_secret:
        print("❌ Both required.")
        return

    auth_url = get_auth_url(app_key)
    print(f"\n{'='*60}")
    print(f"  1. Open: {auth_url}")
    print(f"  2. Click 'Allow'")
    print(f"  3. Copy the authorization code")
    print(f"{'='*60}\n")

    auth_code = input("Paste the authorization code: ").strip()
    if not auth_code:
        print("❌ Code required.")
        return

    print("\n🔄 Exchanging code for tokens...")
    tokens = exchange_code(app_key, app_secret, auth_code)

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("❌ No refresh token. Ensure token_access_type=offline.")
        return

    print("✅ Tokens received!")
    verify_access(access_token)
    store_secret(app_key, app_secret, refresh_token)

    print()
    print("=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print()
    print(f"  Next: bash deploy_dropbox_poll.sh")
    print()


if __name__ == "__main__":
    main()
