#!/usr/bin/env python3
"""Test with a console-generated access token to rule out scope issues."""
import json
import urllib.request
import urllib.error

token = input("Paste the generated access token: ").strip()

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

print("\n── Root listing ──")
result = api_call("https://api.dropboxapi.com/2/files/list_folder", {"path": "", "limit": 50})
if "ERROR" not in result:
    for e in result.get("entries", []):
        print(f"  {e['.tag']:6s}  {e.get('path_display')}")
else:
    print(f"  ERROR: {result}")

print("\n── /life-platform listing ──")
result = api_call("https://api.dropboxapi.com/2/files/list_folder", {"path": "/life-platform", "limit": 50})
if "ERROR" not in result:
    entries = result.get("entries", [])
    print(f"  Found {len(entries)} entries:")
    for e in entries:
        print(f"    {e['.tag']:6s}  {e.get('name')}  ({e.get('size', 0)} bytes)")
else:
    print(f"  ERROR: {result}")

print("\n── Recursive listing ──")
result = api_call("https://api.dropboxapi.com/2/files/list_folder", {"path": "", "recursive": True, "limit": 100})
if "ERROR" not in result:
    entries = result.get("entries", [])
    print(f"  Found {len(entries)} total entries:")
    for e in entries:
        print(f"    {e['.tag']:6s}  {e.get('path_display')}  ({e.get('size', '')})")
else:
    print(f"  ERROR: {result}")
