#!/usr/bin/env python3
"""
Create the Life Platform Journal database in Notion with all 5 template types
and all properties pre-configured.

Usage:
    python3 create_notion_db.py <API_KEY> <PARENT_PAGE_ID>

The parent page must already exist and have the integration connected to it.
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
    """Build select options list."""
    return [{"name": str(v)} for v in values]


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 create_notion_db.py <API_KEY> <PARENT_PAGE_ID>")
        sys.exit(1)

    api_key = sys.argv[1]
    parent_page_id = sys.argv[2]

    # Clean up page ID (remove hyphens if pasted with them)
    parent_page_id = parent_page_id.replace("-", "")
    # Re-format as UUID
    if len(parent_page_id) == 32:
        parent_page_id = (
            f"{parent_page_id[:8]}-{parent_page_id[8:12]}-"
            f"{parent_page_id[12:16]}-{parent_page_id[16:20]}-"
            f"{parent_page_id[20:]}"
        )

    print("Creating Life Platform Journal database...")
    print(f"  Parent page: {parent_page_id}")
    print()

    # ── Build database schema ─────────────────────────────────────────────────
    #
    # Notion property ordering: properties are stored as a dict, but Notion
    # displays them in creation order. Title property comes first.

    scale_5 = select_options([1, 2, 3, 4, 5])
    scale_10 = select_options([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

    properties = {
        # Title property (required — every Notion DB has one)
        "Name": {
            "title": {}
        },

        # ── Shared fields (all templates) ─────────────────────────────────────
        "Date": {
            "date": {}
        },
        "Template": {
            "select": {
                "options": select_options([
                    "Morning", "Evening", "Stressor",
                    "Health Event", "Weekly Reflection"
                ])
            }
        },

        # ── Morning Check-In ☀️ ───────────────────────────────────────────────
        "Subjective Sleep Quality": {
            "select": {"options": scale_5}
        },
        "Morning Energy": {
            "select": {"options": scale_5}
        },
        "Morning Mood": {
            "select": {"options": scale_5}
        },
        "Physical State": {
            "multi_select": {
                "options": select_options([
                    "Fresh", "Sore", "Stiff", "Pain", "Fatigued", "Energized"
                ])
            }
        },
        "Body Region": {
            "multi_select": {
                "options": select_options([
                    "Lower Back", "Knees", "Shoulders", "Neck", "Hips", "General"
                ])
            }
        },
        "Today's Intention": {
            "rich_text": {}
        },

        # ── Evening Reflection 🌙 ────────────────────────────────────────────
        "Day Rating": {
            "select": {"options": scale_5}
        },
        "Stress Level": {
            "select": {"options": scale_5}
        },
        "Stress Source": {
            "multi_select": {
                "options": select_options([
                    "Work", "Family", "Health", "Financial", "Social", "None"
                ])
            }
        },
        "Energy End-of-Day": {
            "select": {"options": scale_5}
        },
        "Workout RPE": {
            "select": {"options": scale_10}
        },
        "Hunger/Cravings": {
            "multi_select": {
                "options": select_options([
                    "Controlled", "Hungry all day", "Sugar cravings",
                    "Late-night snacking", "Low appetite"
                ])
            }
        },
        "Win of the Day": {
            "rich_text": {}
        },
        "What Drained Me": {
            "rich_text": {}
        },
        "Notable Events": {
            "rich_text": {}
        },
        "Tomorrow Focus": {
            "rich_text": {}
        },

        # ── Stressor Deep-Dive 🔴 ────────────────────────────────────────────
        "Stress Intensity": {
            "select": {"options": scale_10}
        },
        "Category": {
            "select": {
                "options": select_options([
                    "Work", "Family", "Health", "Financial", "Social", "Existential"
                ])
            }
        },
        "What Happened": {
            "rich_text": {}
        },
        "Physical Response": {
            "multi_select": {
                "options": select_options([
                    "Heart racing", "Tension", "Shallow breathing",
                    "Stomach", "Headache", "None"
                ])
            }
        },
        "What I Did": {
            "rich_text": {}
        },
        "Resolution": {
            "select": {
                "options": select_options([
                    "Resolved", "Ongoing", "Escalated", "Accepted"
                ])
            }
        },

        # ── Health Event 🏥 ───────────────────────────────────────────────────
        "Type": {
            "select": {
                "options": select_options([
                    "Illness", "Injury", "Symptom",
                    "Medication Change", "Supplement Change"
                ])
            }
        },
        "Description": {
            "rich_text": {}
        },
        "Severity": {
            "select": {
                "options": select_options(["Mild", "Moderate", "Severe"])
            }
        },
        "Duration": {
            "select": {
                "options": select_options(["Hours", "Days", "Ongoing"])
            }
        },
        "Impact on Training": {
            "select": {
                "options": select_options([
                    "None", "Modified", "Skipped", "Full Rest"
                ])
            }
        },

        # ── Weekly Reflection 📝 ─────────────────────────────────────────────
        "Week Rating": {
            "select": {"options": scale_5}
        },
        "Biggest Win": {
            "rich_text": {}
        },
        "Biggest Challenge": {
            "rich_text": {}
        },
        "What Would I Change": {
            "rich_text": {}
        },
        "Emerging Pattern": {
            "rich_text": {}
        },
        "Next Week Priority": {
            "rich_text": {}
        },

        # ── Catch-all ─────────────────────────────────────────────────────────
        "Notes": {
            "rich_text": {}
        },
    }

    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "P40 Journal"}}],
        "icon": {"type": "emoji", "emoji": "📓"},
        "properties": properties,
    }

    result = notion_request("POST", "/databases", api_key, body)

    db_id = result["id"]
    db_url = result.get("url", "")

    print("✅ Database created!")
    print()
    print(f"  Database ID:  {db_id}")
    print(f"  URL:          {db_url}")
    print(f"  Properties:   {len(properties)}")
    print()
    print("  Templates:    Morning ☀️ | Evening 🌙 | Stressor 🔴 | Health Event 🏥 | Weekly Reflection 📝")
    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Save this Database ID for setup_notion.sh:")
    print(f"  {db_id}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    # ── Create template views (Notion API doesn't support views directly,
    #    but we can note this for manual setup) ────────────────────────────────
    print("  Optional: Set up filtered views in Notion for easier daily use:")
    print("    1. Morning View  → filter Template = Morning, sort Date desc")
    print("    2. Evening View  → filter Template = Evening, sort Date desc")
    print("    3. Timeline      → all entries, calendar view")
    print("    4. Stress Log    → filter Template = Stressor")
    print("    5. Health Events → filter Template = Health Event")
    print()


if __name__ == "__main__":
    main()
