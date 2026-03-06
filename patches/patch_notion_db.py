#!/usr/bin/env python3
"""
Inspect an existing Notion database and add missing P40 Journal properties.

Usage:
    python3 patch_notion_db.py <API_KEY> <DATABASE_ID>

Will show existing properties, then offer to add any missing ones.
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
        error_body = e.read().decode() if e.fp else ""
        print(f"❌ Notion API error {e.code}: {error_body}")
        sys.exit(1)


def select_options(values):
    return [{"name": str(v)} for v in values]


# ── Target schema ─────────────────────────────────────────────────────────────
REQUIRED_PROPERTIES = {
    "Date": {"date": {}},
    "Template": {
        "select": {
            "options": select_options([
                "Morning", "Evening", "Stressor",
                "Health Event", "Weekly Reflection"
            ])
        }
    },
    "Subjective Sleep Quality": {"select": {"options": select_options([1, 2, 3, 4, 5])}},
    "Morning Energy": {"select": {"options": select_options([1, 2, 3, 4, 5])}},
    "Morning Mood": {"select": {"options": select_options([1, 2, 3, 4, 5])}},
    "Physical State": {
        "multi_select": {
            "options": select_options(["Fresh", "Sore", "Stiff", "Pain", "Fatigued", "Energized"])
        }
    },
    "Body Region": {
        "multi_select": {
            "options": select_options(["Lower Back", "Knees", "Shoulders", "Neck", "Hips", "General"])
        }
    },
    "Today's Intention": {"rich_text": {}},
    "Day Rating": {"select": {"options": select_options([1, 2, 3, 4, 5])}},
    "Stress Level": {"select": {"options": select_options([1, 2, 3, 4, 5])}},
    "Stress Source": {
        "multi_select": {
            "options": select_options(["Work", "Family", "Health", "Financial", "Social", "None"])
        }
    },
    "Energy End-of-Day": {"select": {"options": select_options([1, 2, 3, 4, 5])}},
    "Workout RPE": {"select": {"options": select_options([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])}},
    "Hunger/Cravings": {
        "multi_select": {
            "options": select_options([
                "Controlled", "Hungry all day", "Sugar cravings",
                "Late-night snacking", "Low appetite"
            ])
        }
    },
    "Win of the Day": {"rich_text": {}},
    "What Drained Me": {"rich_text": {}},
    "Notable Events": {"rich_text": {}},
    "Tomorrow Focus": {"rich_text": {}},
    "Stress Intensity": {"select": {"options": select_options([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])}},
    "Category": {
        "select": {
            "options": select_options(["Work", "Family", "Health", "Financial", "Social", "Existential"])
        }
    },
    "What Happened": {"rich_text": {}},
    "Physical Response": {
        "multi_select": {
            "options": select_options(["Heart racing", "Tension", "Shallow breathing", "Stomach", "Headache", "None"])
        }
    },
    "What I Did": {"rich_text": {}},
    "Resolution": {
        "select": {"options": select_options(["Resolved", "Ongoing", "Escalated", "Accepted"])}
    },
    "Type": {
        "select": {
            "options": select_options(["Illness", "Injury", "Symptom", "Medication Change", "Supplement Change"])
        }
    },
    "Description": {"rich_text": {}},
    "Severity": {"select": {"options": select_options(["Mild", "Moderate", "Severe"])}},
    "Duration": {"select": {"options": select_options(["Hours", "Days", "Ongoing"])}},
    "Impact on Training": {
        "select": {"options": select_options(["None", "Modified", "Skipped", "Full Rest"])}
    },
    "Week Rating": {"select": {"options": select_options([1, 2, 3, 4, 5])}},
    "Biggest Win": {"rich_text": {}},
    "Biggest Challenge": {"rich_text": {}},
    "What Would I Change": {"rich_text": {}},
    "Emerging Pattern": {"rich_text": {}},
    "Next Week Priority": {"rich_text": {}},
    "Notes": {"rich_text": {}},
}


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 patch_notion_db.py <API_KEY> <DATABASE_ID>")
        sys.exit(1)

    api_key = sys.argv[1]
    database_id = sys.argv[2].replace("-", "")
    if len(database_id) == 32:
        database_id = (
            f"{database_id[:8]}-{database_id[8:12]}-"
            f"{database_id[12:16]}-{database_id[16:20]}-"
            f"{database_id[20:]}"
        )

    # ── Fetch existing schema ─────────────────────────────────────────────────
    print("Fetching existing database schema...")
    print()

    db = notion_request("GET", f"/databases/{database_id}", api_key)

    title_parts = db.get("title", [])
    title = "".join(t.get("plain_text", "") for t in title_parts)
    print(f"  Database: {title}")
    print(f"  ID:       {db['id']}")
    print()

    existing = db.get("properties", {})
    existing_names = set(existing.keys())

    print(f"  Existing properties ({len(existing_names)}):")
    for name, prop in sorted(existing.items()):
        ptype = prop.get("type", "unknown")
        print(f"    • {name} ({ptype})")

    # ── Diff ──────────────────────────────────────────────────────────────────
    print()
    required_names = set(REQUIRED_PROPERTIES.keys())
    already_have = required_names & existing_names
    missing = required_names - existing_names
    extra = existing_names - required_names

    print(f"  ✓ Already have: {len(already_have)} of {len(required_names)} required properties")

    if extra:
        print(f"  ℹ Extra properties (will keep): {', '.join(sorted(extra))}")

    if not missing:
        print()
        print("  ✅ Database already has all required properties!")
        print(f"  Database ID for setup_notion.sh: {db['id']}")
        return

    print(f"  ✗ Missing {len(missing)} properties:")
    for name in sorted(missing):
        prop_def = REQUIRED_PROPERTIES[name]
        ptype = list(prop_def.keys())[0]
        print(f"    + {name} ({ptype})")

    # ── Confirm and patch ─────────────────────────────────────────────────────
    print()
    response = input(f"Add {len(missing)} missing properties? (y/N): ")
    if response.lower() != "y":
        print("Aborted.")
        return

    # Build patch payload (only missing properties)
    patch_props = {name: REQUIRED_PROPERTIES[name] for name in missing}

    print()
    print(f"Adding {len(patch_props)} properties...")

    notion_request("PATCH", f"/databases/{database_id}", api_key, {
        "properties": patch_props
    })

    print()
    print(f"  ✅ Added {len(patch_props)} properties!")
    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Database ID for setup_notion.sh:")
    print(f"  {db['id']}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()


if __name__ == "__main__":
    main()
