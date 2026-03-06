#!/usr/bin/env python3
"""
Add Phase 2 expert panel fields to Notion journal database.

Adds: Gratitude, Social Connection, Deep Work Hours, One Thing I'm Avoiding

Usage:
    python3 patch_notion_db_phase2.py <API_KEY> <DATABASE_ID>
"""

import json
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def notion_request(method, endpoint, api_key, body=None):
    url = f"{NOTION_API}{endpoint}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        print(f"❌ Notion API error {e.code}: {e.read().decode()}")
        sys.exit(1)


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 patch_notion_db_phase2.py <API_KEY> <DATABASE_ID>")
        sys.exit(1)

    api_key = sys.argv[1]
    db_id = sys.argv[2].replace("-", "")
    if len(db_id) == 32:
        db_id = f"{db_id[:8]}-{db_id[8:12]}-{db_id[12:16]}-{db_id[16:20]}-{db_id[20:]}"

    # Check what exists
    db = notion_request("GET", f"/databases/{db_id}", api_key)
    existing = set(db.get("properties", {}).keys())

    new_fields = {
        "Gratitude": {"rich_text": {}},
        "Social Connection": {
            "select": {
                "options": [{"name": str(v)} for v in [1, 2, 3, 4, 5]]
            }
        },
        "Deep Work Hours": {
            "select": {
                "options": [{"name": v} for v in ["0", "1", "2", "3", "4+"]]
            }
        },
        "One Thing I'm Avoiding": {"rich_text": {}},
    }

    to_add = {k: v for k, v in new_fields.items() if k not in existing}

    if not to_add:
        print("✅ All Phase 2 fields already exist!")
        return

    print(f"Adding {len(to_add)} Phase 2 fields: {', '.join(to_add.keys())}")
    notion_request("PATCH", f"/databases/{db_id}", api_key, {"properties": to_add})
    print(f"✅ Added: {', '.join(to_add.keys())}")


if __name__ == "__main__":
    main()
