#!/usr/bin/env python3
"""Quick Dropbox API debug — test folder listing."""
import json
import boto3
import base64
import urllib.request
import urllib.parse
import urllib.error

# Get credentials from Secrets Manager
secrets = boto3.client("secretsmanager", region_name="us-west-2")
resp = secrets.get_secret_value(SecretId="life-platform/dropbox")
creds = json.loads(resp["SecretString"])

# Get access token
credentials = base64.b64encode(f"{creds['app_key']}:{creds['app_secret']}".encode()).decode()
data = urllib.parse.urlencode({
    "grant_type": "refresh_token",
    "refresh_token": creds["refresh_token"],
}).encode()
req = urllib.request.Request("https://api.dropboxapi.com/oauth2/token", data=data, method="POST", headers={
    "Authorization": f"Basic {credentials}",
    "Content-Type": "application/x-www-form-urlencoded",
})
with urllib.request.urlopen(req) as r:
    token = json.loads(r.read())["access_token"]

print("✅ Got access token")

# List root
print("\n── Root listing ──")
req = urllib.request.Request(
    "https://api.dropboxapi.com/2/files/list_folder",
    data=json.dumps({"path": "", "limit": 50}).encode(),
    method="POST",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        for e in result["entries"]:
            print(f"  {e['.tag']:6s}  {e['path_display']}")
except urllib.error.HTTPError as e:
    print(f"  ERROR {e.code}: {e.read().decode()[:300]}")

# List /life-platform
print("\n── /life-platform listing ──")
req = urllib.request.Request(
    "https://api.dropboxapi.com/2/files/list_folder",
    data=json.dumps({"path": "/life-platform", "limit": 50}).encode(),
    method="POST",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        print(f"  Found {len(result['entries'])} entries:")
        for e in result["entries"]:
            print(f"    {e['.tag']:6s}  {e.get('name', '')}  ({e.get('size', 0)} bytes)")
except urllib.error.HTTPError as e:
    print(f"  ERROR {e.code}: {e.read().decode()[:300]}")

# Get current account info (check scopes)
print("\n── Account info ──")
req = urllib.request.Request(
    "https://api.dropboxapi.com/2/users/get_current_account",
    data=b"null",
    method="POST",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req) as r:
        acct = json.loads(r.read())
        print(f"  Name: {acct['name']['display_name']}")
        print(f"  Email: {acct['email']}")
        rt = acct.get("root_info", {})
        print(f"  Root type: {rt.get('.tag')}")
        print(f"  Root namespace: {rt.get('root_namespace_id')}")
        print(f"  Home namespace: {rt.get('home_namespace_id')}")
except urllib.error.HTTPError as e:
    print(f"  ERROR {e.code}: {e.read().decode()[:300]}")
