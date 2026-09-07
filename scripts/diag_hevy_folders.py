#!/usr/bin/env python3
"""Diagnostic: why does list_folders() 400?

Hypothesis: GET /v1/routine_folders rejects pageSize=50. Every other collection
endpoint in hevy_write_client uses 10 (templates is the exception at 100);
list_folders is the only one at 50, and the only one returning 400.

Evidence this is chasing (CloudWatch /aws/lambda/life-platform-mcp, 2026-09-07T04:01:52Z):
    [WARNING] list_folders failed; committing without folder: HTTP Error 400: Bad Request

Run from the repo root with AWS creds + network:
    python3 scripts/diag_hevy_folders.py

Read-only. Makes no writes, creates no folders.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

import boto3

API_BASE = "https://api.hevyapp.com"
SECRET = "life-platform/hevy-write"  # noqa: S105 — a Secrets Manager path, not a credential


def api_key() -> str:
    sm = boto3.client("secretsmanager", region_name="us-west-2")
    return json.loads(sm.get_secret_value(SecretId=SECRET)["SecretString"])["api_key"]


def get(key: str, path: str, **query):
    url = f"{API_BASE}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"api-key": key, "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode()[:300]


def main() -> None:
    key = api_key()

    print("=== A. pageSize sweep on /v1/routine_folders ===")
    print("    (production code uses pageSize=50)")
    for ps in (5, 10, 11, 20, 50, 100):
        status, payload = get(key, "/v1/routine_folders", page=1, pageSize=ps)
        marker = "  <-- PRODUCTION VALUE" if ps == 50 else ""
        detail = "" if status == 200 else f"  {payload}"
        print(f"    pageSize={ps:<4} -> {status}{marker}{detail}")

    print("\n=== B. control: same sweep on /v1/routines ===")
    print("    (isolates 'folders endpoint is broken' from 'pageSize cap')")
    for ps in (10, 50):
        status, _ = get(key, "/v1/routines", page=1, pageSize=ps)
        print(f"    pageSize={ps:<4} -> {status}")

    print("\n=== C. response shape at a working pageSize ===")
    print("    (does the line-101 parser in mcp/tools_hevy_routine.py match?)")
    status, payload = get(key, "/v1/routine_folders", page=1, pageSize=10)
    if status == 200 and isinstance(payload, dict):
        print(f"    top-level keys: {list(payload)}")
        print("    parser accepts 'routine_folders' or 'folders' -> ", end="")
        print("MATCH" if (payload.get("routine_folders") or payload.get("folders")) is not None else "MISS")
        for f in payload.get("routine_folders") or payload.get("folders") or []:
            print(f"      id={f.get('id')!r:<12} title={f.get('title')!r}")
    else:
        print(f"    {status} {payload}")

    print("\n=== D. is the day-1 push routine foldered? ===")
    status, payload = get(key, "/v1/routines/7f906e65-3362-4fef-bd86-52fbbf665eb3")
    if status == 200:
        r = payload.get("routine", payload)
        r = r[0] if isinstance(r, list) else r
        print(f"    title={r.get('title')!r}  folder_id={r.get('folder_id')!r}")
    else:
        print(f"    {status} {payload}")

    print("\nExpected if the hypothesis holds: A fails at 50 and passes at <=10,")
    print("B passes at both (or fails identically), C reports MATCH.")


if __name__ == "__main__":
    main()
