#!/usr/bin/env python3
"""
setup_whoop_auth.py — re-authorize Whoop via the OAuth2 authorization-code flow.

Whoop refresh tokens rotate on every refresh; if a refresh response is ever
lost, the stored refresh_token becomes permanently invalid (the ingestion
Lambda then 400s every run — the 2026-06 outage). There is no fix but a fresh
browser authorization. This script walks that flow and updates the
`life-platform/whoop` secret in place (client_id/client_secret preserved).

Prerequisites:
  - AWS creds with secretsmanager read+write on life-platform/whoop
  - The redirect URI you pass MUST be registered on your Whoop app at
    https://developer.whoop.com (any value works as long as it matches; a
    localhost URL is fine — you only need to read the ?code= off the address
    bar, the page itself need not exist).

Usage:
  python3 deploy/setup_whoop_auth.py
  python3 deploy/setup_whoop_auth.py --redirect-uri http://localhost:8080/callback
  python3 deploy/setup_whoop_auth.py --backfill      # also trigger ingestion after

Flow: prints an authorize URL → you open it, approve → Whoop redirects to your
redirect URI with ?code=... → paste that full URL (or just the code) back here.
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request

import boto3

REGION = "us-west-2"
SECRET_ID = "life-platform/whoop"  # noqa: S105 — secret name, not a secret value
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"  # noqa: S105 — OAuth endpoint URL, not a secret
API_BASE = "https://api.prod.whoop.com/developer/v2"
# Must include `offline` or Whoop returns no refresh_token (matches whoop_lambda).
SCOPES = "offline read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement"
DEFAULT_REDIRECT = "http://localhost:8080/callback"


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "WhoopAuthSetup/1.0"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _verify(access_token: str) -> bool:
    req = urllib.request.Request(
        f"{API_BASE}/recovery?limit=1",
        method="GET",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "WhoopAuthSetup/1.0"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            json.loads(resp.read())
        return True
    except Exception as e:
        print(f"  ⚠ verification call failed: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redirect-uri", default=DEFAULT_REDIRECT, help="must match a redirect registered on your Whoop app")
    ap.add_argument("--backfill", action="store_true", help="trigger whoop-data-ingestion after re-auth")
    args = ap.parse_args()

    sm = boto3.client("secretsmanager", region_name=REGION)
    secret = json.loads(sm.get_secret_value(SecretId=SECRET_ID)["SecretString"])
    client_id, client_secret = secret.get("client_id"), secret.get("client_secret")
    if not client_id or not client_secret:
        print("ERROR: client_id/client_secret missing from the secret.")
        return 2

    state = "lifeplatform-reauth"
    authorize = f"{AUTH_URL}?" + urllib.parse.urlencode(
        {"response_type": "code", "client_id": client_id, "redirect_uri": args.redirect_uri, "scope": SCOPES, "state": state}
    )
    print("\n1) Open this URL in your browser and approve access:\n")
    print("   " + authorize + "\n")
    print(f"2) Whoop will redirect to {args.redirect_uri}?code=...&state=... (the page may 404 — that's fine).")
    pasted = input("3) Paste the FULL redirected URL (or just the code) here:\n   ").strip()

    code = pasted
    if "code=" in pasted:
        qs = urllib.parse.urlparse(pasted).query
        code = urllib.parse.parse_qs(qs).get("code", [""])[0]
    if not code:
        print("ERROR: no authorization code found in your input.")
        return 2

    print("\n[exchanging code for tokens…]")
    try:
        tok = _post_form(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": args.redirect_uri,
                "scope": SCOPES,
            },
        )
    except urllib.error.HTTPError as e:
        print(f"ERROR: token exchange failed: HTTP {e.code} — {e.read().decode()[:300]}")
        print("(A 400 usually means the redirect_uri didn't match your Whoop app, or the code expired — re-run and be quick.)")
        return 2

    access, refresh = tok.get("access_token"), tok.get("refresh_token")
    if not access or not refresh:
        print(f"ERROR: response missing tokens (got keys: {sorted(tok)}). Ensure the `offline` scope is approved.")
        return 2

    if not _verify(access):
        print("ERROR: new access token did not validate against the Whoop API. Secret NOT updated.")
        return 2

    secret["access_token"], secret["refresh_token"] = access, refresh
    sm.update_secret(SecretId=SECRET_ID, SecretString=json.dumps(secret))
    print("\n✅ Whoop re-authorized — secret updated and verified against /recovery.")

    if args.backfill:
        print("[triggering whoop-data-ingestion to backfill the gap…]")
        lam = boto3.client("lambda", region_name=REGION)
        lam.invoke(FunctionName="whoop-data-ingestion", InvocationType="Event", Payload=b"{}")
        print("  ✓ invoked (async). Gap-aware backfill will fetch the missing days.")
    else:
        print("Next: the 4x-daily cron will backfill automatically, or re-run with --backfill to do it now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
