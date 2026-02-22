import json
import hmac
import hashlib
import time
import boto3
import urllib.request
import urllib.parse

SECRET_NAME = "life-platform/withings"
REGION = "us-west-2"
WITHINGS_SIG_URL = "https://wbsapi.withings.net/v2/signature"
WITHINGS_OAUTH_URL = "https://wbsapi.withings.net/v2/oauth2"
AUTH_CODE = "c530ce264e02d6b0d40957a5e7eb9fd6c26c0a52"
REDIRECT_URI = "http://localhost:3000/callback"


def get_secret():
    client = boto3.client("secretsmanager", region_name=REGION)
    resp = client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])


def hmac_sha256(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def post_form(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_nonce(client_id: str, client_secret: str) -> str:
    timestamp = int(time.time())
    # Signature: HMAC-SHA256 of comma-joined values sorted by param name
    # Params: action, client_id, timestamp — sorted alphabetically
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
    nonce = resp["body"]["nonce"]
    print(f"Got nonce: {nonce}")
    return nonce


def request_token(client_id: str, client_secret: str, nonce: str) -> dict:
    # Signature: HMAC-SHA256 of "action,client_id,nonce" (sorted alphabetically)
    sig_string = f"requesttoken,{client_id},{nonce}"
    signature = hmac_sha256(client_secret, sig_string)
    params = {
        "action": "requesttoken",
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": AUTH_CODE,
        "redirect_uri": REDIRECT_URI,
        "nonce": nonce,
        "signature": signature,
    }
    resp = post_form(WITHINGS_OAUTH_URL, params)
    if resp.get("status") != 0:
        raise RuntimeError(f"requesttoken failed: {resp}")
    return resp["body"]


def save_secret(existing: dict, token_body: dict):
    client = boto3.client("secretsmanager", region_name=REGION)
    updated = {
        "client_id": existing["client_id"],
        "client_secret": existing["client_secret"],
        "access_token": token_body["access_token"],
        "refresh_token": token_body["refresh_token"],
        "userid": token_body["userid"],
    }
    client.put_secret_value(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(updated),
    )
    return updated


def main():
    print("Reading credentials from Secrets Manager...")
    secret = get_secret()
    client_id = secret["client_id"]
    client_secret = secret["client_secret"]

    print("Fetching nonce...")
    nonce = get_nonce(client_id, client_secret)

    print("Exchanging authorization code for tokens...")
    token_body = request_token(client_id, client_secret, nonce)

    print("Saving tokens to Secrets Manager...")
    saved = save_secret(secret, token_body)

    print("\nSuccess! Saved to Secrets Manager:")
    print(f"  userid:        {saved['userid']}")
    print(f"  access_token:  {saved['access_token'][:20]}...")
    print(f"  refresh_token: {saved['refresh_token'][:20]}...")


if __name__ == "__main__":
    main()
