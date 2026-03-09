#!/usr/bin/env python3
"""Test with token from file."""
import json, urllib.request, urllib.error

with open("/tmp/dbx_token.txt") as f:
    token = f.read().strip()

print(f"Token length: {len(token)} chars")

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

print("\n── Root ──")
result = api_call("https://api.dropboxapi.com/2/files/list_folder", {"path": "", "limit": 50})
for e in result.get("entries", []):
    print(f"  {e.get('path_display')}")

print("\n── /life-platform ──")
result = api_call("https://api.dropboxapi.com/2/files/list_folder", {"path": "/life-platform", "limit": 50})
if "ERROR" in result:
    print(f"  ERROR: {result}")
else:
    entries = result.get("entries", [])
    print(f"  {len(entries)} entries")
    for e in entries:
        print(f"  {e.get('name')} ({e.get('size', 0)} bytes)")
