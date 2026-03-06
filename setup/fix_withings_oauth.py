#!/usr/bin/env python3
"""
fix_withings_oauth.py — Re-authorize Withings OAuth2 (refresh_token expired)

Flow:
  1. Opens browser to Withings authorization page
  2. Catches the callback on localhost:3000
  3. Exchanges auth code for new access_token + refresh_token
  4. Saves to Secrets Manager
  5. Tests the Lambda invocation

Run: python3 setup/fix_withings_oauth.py
"""

import json
import hmac
import hashlib
import time
import webbrowser
import subprocess
import boto3
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

SECRET_NAME = "life-platform/withings"
REGION = "us-west-2"
REDIRECT_URI = "http://localhost:3000/callback"
WITHINGS_AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_SIG_URL = "https://wbsapi.withings.net/v2/signature"
WITHINGS_OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"


# ── Globals ────────────────────────────────────────────────────────────────
captured_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    """Captures the ?code= from Withings OAuth redirect."""

    def do_GET(self):
        global captured_code
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            captured_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Withings authorized!</h2>"
                b"<p>You can close this tab. Tokens are being saved...</p>"
                b"</body></html>"
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code received")

    def log_message(self, format, *args):
        pass  # Suppress logs


def hmac_sha256(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def post_form(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_secret():
    client = boto3.client("secretsmanager", region_name=REGION)
    resp = client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])


def get_nonce(client_id: str, client_secret: str) -> str:
    timestamp = int(time.time())
    sig_string = f"getnonce,{client_id},{timestamp}"
    signature = hmac_sha256(client_secret, sig_string)
    params = {
        "action": "getnonce",
        "client_id": client_id,
        "timestamp": timestamp,
        "signature": signature,
    }
    resp = post_form(WITHINGS_SIG_URL, params)
    if resp.get("status") != 0:
        raise RuntimeError(f"getnonce failed: {resp}")
    return resp["body"]["nonce"]


def exchange_code(client_id, client_secret, code) -> dict:
    nonce = get_nonce(client_id, client_secret)
    sig_string = f"requesttoken,{client_id},{nonce}"
    signature = hmac_sha256(client_secret, sig_string)
    params = {
        "action": "requesttoken",
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "nonce": nonce,
        "signature": signature,
    }
    resp = post_form(WITHINGS_OAUTH_URL, params)
    if resp.get("status") != 0:
        raise RuntimeError(f"Token exchange failed: {resp}")
    return resp["body"]


def save_tokens(secret, token_body):
    client = boto3.client("secretsmanager", region_name=REGION)
    updated = {
        "client_id": secret["client_id"],
        "client_secret": secret["client_secret"],
        "access_token": token_body["access_token"],
        "refresh_token": token_body["refresh_token"],
        "userid": str(token_body["userid"]),
    }
    client.put_secret_value(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(updated),
    )
    return updated


def main():
    global captured_code

    print("=" * 60)
    print("  Withings OAuth Re-Authorization")
    print("=" * 60)

    # Step 1: Get client_id from Secrets Manager
    print("\n[1/5] Reading client credentials from Secrets Manager...")
    secret = get_secret()
    client_id = secret["client_id"]
    print(f"  client_id: {client_id[:12]}...")

    # Step 2: Start local server
    print("\n[2/5] Starting local callback server on port 3000...")
    server = HTTPServer(("localhost", 3000), CallbackHandler)

    # Step 3: Open browser
    auth_url = (
        f"{WITHINGS_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope=user.metrics"
        f"&state=life-platform"
    )
    print(f"\n[3/5] Opening browser for Withings authorization...")
    print(f"  If browser doesn't open, visit:")
    print(f"  {auth_url}")
    webbrowser.open(auth_url)

    # Step 4: Wait for callback
    print("\n  Waiting for authorization callback...")
    while captured_code is None:
        server.handle_request()
    server.server_close()
    print(f"  Authorization code received: {captured_code[:12]}...")

    # Step 5: Exchange code for tokens
    print("\n[4/5] Exchanging code for tokens...")
    token_body = exchange_code(client_id, secret["client_secret"], captured_code)
    print(f"  access_token:  {token_body['access_token'][:16]}...")
    print(f"  refresh_token: {token_body['refresh_token'][:16]}...")
    print(f"  userid:        {token_body['userid']}")

    # Step 6: Save to Secrets Manager
    print("\n[5/5] Saving tokens to Secrets Manager...")
    saved = save_tokens(secret, token_body)
    print("  Saved!")

    # Step 7: Test Lambda
    print("\n" + "=" * 60)
    print("  Testing Lambda invocation...")
    print("=" * 60)
    try:
        result = subprocess.run(
            [
                "aws", "lambda", "invoke",
                "--function-name", "withings-data-ingestion",
                "--region", "us-west-2",
                "--log-type", "Tail",
                "/tmp/withings_test.json",
                "--query", "LogResult",
                "--output", "text",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        import base64
        if result.stdout.strip():
            logs = base64.b64decode(result.stdout.strip()).decode()
            print(logs)
            if "ERROR" in logs:
                print("\n⚠️  Lambda ran but had errors — check logs above")
            elif "GAP-FILL" in logs:
                print("\n✅ Withings Lambda is working! Gap-fill ran successfully.")
        else:
            print(f"  stdout: {result.stdout}")
            print(f"  stderr: {result.stderr}")
    except Exception as e:
        print(f"  Lambda test failed: {e}")
        print("  Run manually: aws lambda invoke --function-name withings-data-ingestion --region us-west-2 /tmp/test.json --log-type Tail")


if __name__ == "__main__":
    main()
