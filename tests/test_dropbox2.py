#!/usr/bin/env python3
"""Deep Dropbox debug — try multiple API approaches."""
import json
import boto3
import base64
import urllib.request
import urllib.parse
import urllib.error

# Get credentials
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
    token_resp = json.loads(r.read())
    token = token_resp["access_token"]
    print(f"✅ Token scopes: {token_resp.get('scope', 'NOT RETURNED')}")
    print(f"   Token type: {token_resp.get('token_type')}")
    print(f"   Expires in: {token_resp.get('expires_in')}s")

def api_call(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"ERROR": e.code, "body": e.read().decode()[:500]}

# Test 1: list_folder with path variations
print("\n── Test 1: Path variations ──")
for path in ["/life-platform", "/Life-Platform", "/life-platform/", ""]:
    result = api_call("https://api.dropboxapi.com/2/files/list_folder", {"path": path, "limit": 50})
    if "ERROR" in result:
        print(f"  '{path}' → ERROR {result['ERROR']}: {result['body'][:200]}")
    else:
        entries = result.get("entries", [])
        print(f"  '{path}' → {len(entries)} entries")
        for e in entries[:5]:
            print(f"      {e['.tag']:6s}  {e.get('path_display', e.get('name', '?'))}")

# Test 2: get_metadata on specific file
print("\n── Test 2: Get metadata on known file ──")
result = api_call("https://api.dropboxapi.com/2/files/get_metadata", {"path": "/life-platform/MacroFactor-20260224170733.csv"})
print(f"  Result: {json.dumps(result, indent=2)[:500]}")

# Test 3: search for MacroFactor
print("\n── Test 3: Search for 'MacroFactor' ──")
result = api_call("https://api.dropboxapi.com/2/files/search_v2", {
    "query": "MacroFactor",
    "options": {"path": "/life-platform", "max_results": 10}
})
if "ERROR" in result:
    print(f"  ERROR {result['ERROR']}: {result['body'][:300]}")
else:
    matches = result.get("matches", [])
    print(f"  Found {len(matches)} matches:")
    for m in matches[:5]:
        meta = m.get("metadata", {}).get("metadata", {})
        print(f"    {meta.get('name', '?')} — {meta.get('path_display', '?')}")

# Test 4: list_folder recursive from root
print("\n── Test 4: Recursive root listing ──")
result = api_call("https://api.dropboxapi.com/2/files/list_folder", {"path": "", "recursive": True, "limit": 50})
if "ERROR" in result:
    print(f"  ERROR {result['ERROR']}: {result['body'][:300]}")
else:
    entries = result.get("entries", [])
    print(f"  Found {len(entries)} entries (recursive):")
    for e in entries[:20]:
        print(f"    {e['.tag']:6s}  {e.get('path_display', '?')}  ({e.get('size', '')})")
