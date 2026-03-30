#!/usr/bin/env python3
"""
setup_garmin_browser_auth.py — Browser-based Garmin Connect auth.

Since March 2026, Garmin blocks all non-browser HTTP clients from their
SSO login endpoint (429 / Cloudflare TLS fingerprinting). This script
uses Playwright to open a real Chromium browser for login, captures the
SSO ticket, exchanges it for OAuth1 → OAuth2 tokens, and stores them
in AWS Secrets Manager for Lambda consumption.

Requires:
    pip install playwright requests-oauthlib boto3
    python -m playwright install chromium
"""

import base64
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs

try:
    import requests
    from requests_oauthlib import OAuth1Session
    from playwright.sync_api import sync_playwright
    import boto3
except ImportError as e:
    print(f"Missing dependency: {e.name}")
    print()
    print("Install requirements:")
    print("  pip3 install playwright requests-oauthlib boto3 --break-system-packages")
    print("  python3 -m playwright install chromium")
    sys.exit(1)


SECRET_NAME = "life-platform/garmin"
REGION = "us-west-2"
OAUTH_CONSUMER_URL = "https://thegarth.s3.amazonaws.com/oauth_consumer.json"
ANDROID_UA = "com.garmin.android.apps.connectmobile"


def get_oauth_consumer() -> dict:
    """Fetch the shared OAuth consumer key/secret from garth's S3 bucket."""
    resp = requests.get(OAUTH_CONSUMER_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_oauth1_token(ticket: str, consumer: dict) -> dict:
    """Exchange an SSO ticket for an OAuth1 token."""
    sess = OAuth1Session(
        consumer["consumer_key"],
        consumer["consumer_secret"],
    )
    url = (
        f"https://connectapi.garmin.com/oauth-service/oauth/"
        f"preauthorized?ticket={ticket}"
        f"&login-url=https://sso.garmin.com/sso/embed"
        f"&accepts-mfa-tokens=true"
    )
    resp = sess.get(url, headers={"User-Agent": ANDROID_UA}, timeout=15)
    resp.raise_for_status()
    parsed = parse_qs(resp.text)
    token = {k: v[0] for k, v in parsed.items()}
    token["domain"] = "garmin.com"
    return token


def exchange_oauth2(oauth1: dict, consumer: dict) -> dict:
    """Exchange OAuth1 token for OAuth2 token."""
    sess = OAuth1Session(
        consumer["consumer_key"],
        consumer["consumer_secret"],
        resource_owner_key=oauth1["oauth_token"],
        resource_owner_secret=oauth1["oauth_token_secret"],
    )
    url = "https://connectapi.garmin.com/oauth-service/oauth/exchange/user/2.0"
    data = {}
    if oauth1.get("mfa_token"):
        data["mfa_token"] = oauth1["mfa_token"]
    resp = sess.post(
        url,
        headers={
            "User-Agent": ANDROID_UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=data,
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()
    token["expires_at"] = int(time.time() + token["expires_in"])
    token["refresh_token_expires_at"] = int(
        time.time() + token["refresh_token_expires_in"]
    )
    return token


def browser_login() -> str:
    """Open a real browser, let user log in, capture the SSO ticket."""
    ticket = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        sso_url = (
            "https://sso.garmin.com/sso/embed"
            "?id=gauth-widget"
            "&embedWidget=true"
            "&gauthHost=https://sso.garmin.com/sso"
            "&clientId=GarminConnect"
            "&locale=en_US"
            "&redirectAfterAccountLoginUrl=https://sso.garmin.com/sso/embed"
            "&service=https://sso.garmin.com/sso/embed"
        )
        page.goto(sso_url)

        print()
        print("=" * 55)
        print("  A browser window has opened.")
        print("  Log in with your Garmin Connect credentials.")
        print("  The window will close automatically when done.")
        print("  (You have 5 minutes)")
        print("=" * 55)
        print()

        max_wait = 300
        start = time.time()
        while time.time() - start < max_wait:
            try:
                content = page.content()
                m = re.search(r"ticket=(ST-[A-Za-z0-9\-]+)", content)
                if m:
                    ticket = m.group(1)
                    print(f"  Got SSO ticket: {ticket[:30]}...")
                    break

                url = page.url
                if "ticket=" in url:
                    m = re.search(r"ticket=(ST-[A-Za-z0-9\-]+)", url)
                    if m:
                        ticket = m.group(1)
                        print(f"  Got SSO ticket from URL: {ticket[:30]}...")
                        break
            except Exception:
                pass

            page.wait_for_timeout(500)

        browser.close()

    if not ticket:
        print("ERROR: Timed out waiting for login (5 min).")
        sys.exit(1)

    return ticket


def verify_tokens(oauth2: dict) -> str:
    """Verify OAuth2 tokens work by fetching the user profile."""
    resp = requests.get(
        "https://connectapi.garmin.com/userprofile-service/socialProfile",
        headers={
            "User-Agent": "GCM-iOS-5.7.2.1",
            "Authorization": f"Bearer {oauth2['access_token']}",
        },
        timeout=15,
    )
    resp.raise_for_status()
    profile = resp.json()
    return profile.get("displayName") or profile.get("fullName") or "unknown"


def save_to_secrets_manager(oauth1: dict, oauth2: dict, display_name: str):
    """Store tokens in AWS Secrets Manager."""
    # Build a garth-compatible token bundle
    garth_tokens = json.dumps({"oauth1": oauth1, "oauth2": oauth2})

    secret = {
        "garth_tokens": garth_tokens,
        "display_name": display_name,
        "auth_method": "browser_playwright",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    client = boto3.client("secretsmanager", region_name=REGION)
    try:
        client.update_secret(
            SecretId=SECRET_NAME,
            SecretString=json.dumps(secret),
        )
        print(f"  Secret updated: {SECRET_NAME}")
    except client.exceptions.ResourceNotFoundException:
        client.create_secret(
            Name=SECRET_NAME,
            Description="Garmin Connect OAuth tokens for Life Platform",
            SecretString=json.dumps(secret),
        )
        print(f"  Secret created: {SECRET_NAME}")


def save_locally(oauth1: dict, oauth2: dict):
    """Save tokens to ~/.garth for local garth.resume() compatibility."""
    garth_dir = Path.home() / ".garth"
    garth_dir.mkdir(exist_ok=True)
    (garth_dir / "oauth1_token.json").write_text(json.dumps(oauth1, indent=2))
    (garth_dir / "oauth2_token.json").write_text(json.dumps(oauth2, indent=2))
    print(f"  Local tokens saved to {garth_dir}")


def main():
    print("=" * 55)
    print("  Garmin Connect — Browser Auth Setup")
    print("  (bypasses blocked SSO programmatic endpoint)")
    print("=" * 55)
    print()

    # Step 1: Fetch OAuth consumer credentials
    print("[1/6] Fetching OAuth consumer credentials...")
    consumer = get_oauth_consumer()
    print("  OK")

    # Step 2: Browser login
    print("[2/6] Launching browser for Garmin login...")
    ticket = browser_login()

    # Step 3: Exchange ticket → OAuth1
    print("[3/6] Exchanging SSO ticket for OAuth1 token...")
    oauth1 = get_oauth1_token(ticket, consumer)
    print(f"  OAuth1 token: {oauth1['oauth_token'][:20]}...")

    # Step 4: Exchange OAuth1 → OAuth2
    print("[4/6] Exchanging OAuth1 for OAuth2 token...")
    oauth2 = exchange_oauth2(oauth1, consumer)
    print(f"  Access token: {oauth2['access_token'][:20]}...")
    print(f"  Expires in: {oauth2['expires_in']}s")
    print(f"  Refresh expires in: {oauth2['refresh_token_expires_in']}s")

    # Step 5: Verify
    print("[5/6] Verifying tokens...")
    display_name = verify_tokens(oauth2)
    print(f"  Authenticated as: {display_name}")

    # Step 6: Save
    print("[6/6] Saving tokens...")
    save_to_secrets_manager(oauth1, oauth2, display_name)
    save_locally(oauth1, oauth2)

    print()
    print("=" * 55)
    print("  Setup complete!")
    print()
    print("  Tokens stored in:")
    print(f"    AWS: {SECRET_NAME}")
    print(f"    Local: ~/.garth/")
    print()
    print("  OAuth1 tokens last ~1 year.")
    print("  OAuth2 access tokens expire but can be refreshed.")
    print()
    print("  Test with:")
    print("    aws lambda invoke \\")
    print("      --function-name garmin-data-ingestion \\")
    print("      --payload '{\"date\": \"2026-03-30\"}' \\")
    print("      --cli-binary-format raw-in-base64-out \\")
    print("      --region us-west-2 /tmp/garmin_test.json && cat /tmp/garmin_test.json")
    print("=" * 55)


if __name__ == "__main__":
    main()
