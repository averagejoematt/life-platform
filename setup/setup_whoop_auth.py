#!/usr/bin/env python3
"""
setup_whoop_auth.py — re-authorize Whoop via the OAuth2 authorization-code flow.

Whoop refresh tokens rotate on every refresh; if a refresh response is ever
lost, the stored refresh_token becomes permanently invalid (the ingestion
Lambda then 400s every run — the 2026-06 outage). There is no fix but a fresh
browser authorization. This script walks that flow and updates the
`life-platform/whoop` secret in place (client_id/client_secret preserved).

Flow (mirrors setup/fix_withings_oauth.py):
  1. Reads client_id/client_secret from Secrets Manager
  2. Starts a local callback server on http://localhost:3000/callback
  3. Opens the browser to the Whoop authorization page
  4. Catches the redirect, exchanges the code for access + refresh tokens
  5. Verifies the new token against /developer/v2/recovery, then saves to
     Secrets Manager

Prerequisites:
  - AWS creds with secretsmanager read+write on life-platform/whoop
  - The redirect URI you pass MUST be registered on your Whoop app at
    https://developer.whoop.com — http://localhost:3000/callback is the
    registered default.

Usage:
  python3 setup/setup_whoop_auth.py               # callback server on :3000
  python3 setup/setup_whoop_auth.py --manual      # no server: paste the redirected URL back
  python3 setup/setup_whoop_auth.py --backfill    # also trigger ingestion after
  python3 setup/setup_whoop_auth.py --redirect-uri http://localhost:3000/callback

`--manual` exists for the headless/port-in-use case: the redirect page won't
load (nothing runs there) — just copy the full redirected URL off the address
bar and paste it back.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import boto3

REGION = "us-west-2"
SECRET_ID = "life-platform/whoop"  # noqa: S105 — secret name, not a secret value
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"  # noqa: S105 — OAuth endpoint URL, not a secret
API_BASE = "https://api.prod.whoop.com/developer/v2"
# Must include `offline` or Whoop returns no refresh_token (matches whoop_lambda).
SCOPES = "offline read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement"
DEFAULT_REDIRECT = "http://localhost:3000/callback"  # must match the Whoop app's registered Redirect URL (developer.whoop.com)
CALLBACK_PORT = 3000
STATE = "lifeplatform-reauth"


# ── Globals ────────────────────────────────────────────────────────────────
captured_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    """Captures the ?code= from the Whoop OAuth redirect."""

    def do_GET(self):
        global captured_code
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            captured_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Whoop authorized!</h2>" b"<p>You can close this tab. Tokens are being saved...</p>" b"</body></html>"
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code received")

    def log_message(self, format, *args):
        pass  # Suppress logs


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "WhoopAuthSetup/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_secret() -> dict:
    client = boto3.client("secretsmanager", region_name=REGION)
    return json.loads(client.get_secret_value(SecretId=SECRET_ID)["SecretString"])


def build_authorize_url(client_id: str, redirect_uri: str) -> str:
    return f"{AUTH_URL}?" + urllib.parse.urlencode(
        {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": SCOPES, "state": STATE}
    )


def extract_code(pasted: str) -> str:
    """Pull the authorization code out of a pasted redirect URL (or accept a bare code)."""
    pasted = pasted.strip()
    if "code=" in pasted:
        qs = urlparse(pasted).query
        return parse_qs(qs).get("code", [""])[0]
    return pasted


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    """Exchange the authorization code for tokens at the Whoop token endpoint."""
    return _post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
        },
    )


def verify_token(access_token: str) -> bool:
    """One authenticated GET against the API the ingestion Lambda uses."""
    req = urllib.request.Request(
        f"{API_BASE}/recovery?limit=1",
        method="GET",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "WhoopAuthSetup/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            json.loads(resp.read())
        return True
    except Exception as e:
        print(f"  ⚠ verification call failed: {e}")
        return False


def save_tokens(secret: dict, token_body: dict) -> dict:
    """Write access_token + refresh_token into the secret IN PLACE — every other
    field (client_id, client_secret, anything else present) is preserved, matching
    what whoop_lambda's refresh path expects to read back."""
    updated = dict(secret)
    updated["access_token"] = token_body["access_token"]
    updated["refresh_token"] = token_body["refresh_token"]
    client = boto3.client("secretsmanager", region_name=REGION)
    client.update_secret(SecretId=SECRET_ID, SecretString=json.dumps(updated))
    return updated


def _capture_code_via_server(authorize_url: str) -> str | None:
    """Serve localhost:3000/callback, open the browser, block until the redirect lands."""
    global captured_code
    captured_code = None
    server = HTTPServer(("localhost", CALLBACK_PORT), CallbackHandler)
    print(f"\n  Local callback server listening on port {CALLBACK_PORT}...")
    print("  Opening browser for Whoop authorization...")
    print("  If the browser doesn't open, visit:\n")
    print("  " + authorize_url + "\n")
    webbrowser.open(authorize_url)
    print("  Waiting for authorization callback (Ctrl-C to abort)...")
    try:
        while captured_code is None:
            server.handle_request()
    finally:
        server.server_close()
    return captured_code


def _capture_code_manually(authorize_url: str, redirect_uri: str) -> str:
    print("\n1) Open this URL in your browser and approve access:\n")
    print("   " + authorize_url + "\n")
    print(f"2) Whoop will redirect to {redirect_uri}?code=...&state=... (the page may 404 — that's fine).")
    pasted = input("3) Paste the FULL redirected URL (or just the code) here:\n   ")
    return extract_code(pasted)


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-authorize Whoop and update the life-platform/whoop secret.")
    ap.add_argument("--redirect-uri", default=DEFAULT_REDIRECT, help="must match a redirect registered on your Whoop app")
    ap.add_argument("--manual", action="store_true", help="skip the local callback server; paste the redirected URL back instead")
    ap.add_argument("--backfill", action="store_true", help="trigger whoop-data-ingestion after re-auth")
    args = ap.parse_args()

    print("=" * 60)
    print("  Whoop OAuth Re-Authorization")
    print("=" * 60)

    print("\n[1/5] Reading client credentials from Secrets Manager...")
    secret = get_secret()
    client_id, client_secret = secret.get("client_id"), secret.get("client_secret")
    if not client_id or not client_secret:
        print("ERROR: client_id/client_secret missing from the secret.")
        return 2
    print(f"  client_id: {client_id[:12]}...")

    authorize_url = build_authorize_url(client_id, args.redirect_uri)
    print("\n[2/5] Authorizing in the browser...")
    if args.manual or not args.redirect_uri.startswith(f"http://localhost:{CALLBACK_PORT}/"):
        code = _capture_code_manually(authorize_url, args.redirect_uri)
    else:
        code = _capture_code_via_server(authorize_url)
    if not code:
        print("ERROR: no authorization code received.")
        return 2
    print(f"  Authorization code received: {code[:12]}...")

    print("\n[3/5] Exchanging code for tokens...")
    try:
        tok = exchange_code(client_id, client_secret, code, args.redirect_uri)
    except urllib.error.HTTPError as e:
        print(f"ERROR: token exchange failed: HTTP {e.code} — {e.read().decode()[:300]}")
        print("(A 400 usually means the redirect_uri didn't match your Whoop app, or the code expired — re-run and be quick.)")
        return 2

    access, refresh = tok.get("access_token"), tok.get("refresh_token")
    if not access or not refresh:
        print(f"ERROR: response missing tokens (got keys: {sorted(tok)}). Ensure the `offline` scope is approved.")
        return 2

    print("\n[4/5] Verifying the new token against /recovery...")
    if not verify_token(access):
        print("ERROR: new access token did not validate against the Whoop API. Secret NOT updated.")
        return 2

    print("\n[5/5] Saving tokens to Secrets Manager...")
    save_tokens(secret, tok)
    print("\n✅ Whoop re-authorized — secret updated and verified against /recovery.")

    if args.backfill:
        print("[triggering whoop-data-ingestion to backfill the gap…]")
        lam = boto3.client("lambda", region_name=REGION)
        lam.invoke(FunctionName="whoop-data-ingestion", InvocationType="Event", Payload=b"{}")
        print("  ✓ invoked (async). Gap-aware backfill will fetch the missing days.")
    else:
        print("Next: the hourly cron will backfill automatically, or re-run with --backfill to do it now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
