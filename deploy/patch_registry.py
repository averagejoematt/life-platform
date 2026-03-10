#!/usr/bin/env python3
"""
patch_registry.py — restore registry.py from git and add sick day tools.

Run from project root:
  python3 deploy/patch_registry.py

Steps:
  1. git checkout HEAD -- mcp/registry.py  (restores to last committed version)
  2. Inserts 'from mcp.tools_sick_days import *' after the last import line
  3. Appends log_sick_day / get_sick_days / clear_sick_day tool entries before closing }
"""

import subprocess
import sys
import os

REGISTRY = os.path.join(os.path.dirname(__file__), "..", "mcp", "registry.py")
REGISTRY = os.path.normpath(REGISTRY)


def run(cmd, cwd=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        print(f"ERROR: {cmd!r} failed:\n{r.stderr}")
        sys.exit(1)
    return r.stdout.strip()


# ── Step 1: restore from git ──────────────────────────────────────────────────
proj_root = os.path.dirname(REGISTRY.rstrip("/").rsplit("/mcp", 1)[0])
# walk up to find project root (has .git)
check = REGISTRY
for _ in range(6):
    check = os.path.dirname(check)
    if os.path.isdir(os.path.join(check, ".git")):
        proj_root = check
        break

print(f"Project root: {proj_root}")
run("git checkout HEAD -- mcp/registry.py", cwd=proj_root)
print("✅ mcp/registry.py restored from git HEAD")


# ── Step 2: read content ──────────────────────────────────────────────────────
with open(REGISTRY, "r") as f:
    content = f.read()


# ── Step 3: insert import ─────────────────────────────────────────────────────
OLD_IMPORT = "from mcp.tools_hypotheses import *\n\nTOOLS = {"
NEW_IMPORT = "from mcp.tools_hypotheses import *\nfrom mcp.tools_sick_days import *\n\nTOOLS = {"

if "from mcp.tools_sick_days" in content:
    print("ℹ️  sick_days import already present — skipping import patch")
elif OLD_IMPORT in content:
    content = content.replace(OLD_IMPORT, NEW_IMPORT, 1)
    print("✅ Import added: from mcp.tools_sick_days import *")
else:
    print("WARNING: Could not find expected import anchor — adding import manually")
    content = content.replace("from mcp.tools_hypotheses import *",
                              "from mcp.tools_hypotheses import *\nfrom mcp.tools_sick_days import *", 1)


# ── Step 4: append tool entries ───────────────────────────────────────────────
SICK_TOOLS = '''
    "log_sick_day": {
        "fn": tool_log_sick_day,
        "schema": {
            "name": "log_sick_day",
            "description": (
                "Flag one or more dates as sick or rest days. When flagged: Character Sheet EMA is frozen "
                "(no gain or penalty), day grade is stored as 'sick', habit and streak timers are preserved "
                "from the previous day (not broken, not advanced), anomaly detector alerts are suppressed, "
                "freshness checker alerts are skipped, and the Daily Brief shows a recovery banner instead "
                "of normal habit/nutrition coaching. Use for illness, injury, travel recovery, or any day "
                "where normal tracking is intentionally paused."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date":   {"type": "string",
                               "description": "Single date to flag (YYYY-MM-DD). Use 'dates' for multiple."},
                    "dates":  {"type": "array", "items": {"type": "string"},
                               "description": "List of dates to flag (YYYY-MM-DD). Use when flagging multiple days."},
                    "reason": {"type": "string",
                               "description": "Optional reason (e.g. 'flu', 'food poisoning', 'migraine')."},
                },
                "required": [],
            },
        },
    },
    "get_sick_days": {
        "fn": tool_get_sick_days,
        "schema": {
            "name": "get_sick_days",
            "description": (
                "List all sick/rest days flagged within a date range. Shows date, reason, and when logged. "
                "Use for: 'how many sick days did I have?', 'when was I last sick?', 'sick day history'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default 90 days ago)."},
                    "end_date":   {"type": "string", "description": "End date YYYY-MM-DD (default today)."},
                },
                "required": [],
            },
        },
    },
    "clear_sick_day": {
        "fn": tool_clear_sick_day,
        "schema": {
            "name": "clear_sick_day",
            "description": (
                "Remove a sick day flag for a given date (use if logged in error). "
                "After clearing, re-run character-sheet-compute and daily-metrics-compute with "
                "force=true to recompute correct values."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date to un-flag (YYYY-MM-DD)."},
                },
                "required": ["date"],
            },
        },
    },
}
'''

if '"log_sick_day"' in content:
    print("ℹ️  Sick day tools already present in TOOLS dict — skipping tool patch")
else:
    # Insert before the final closing }
    content = content.rstrip()
    if content.endswith("\n}"):
        content = content[:-1] + SICK_TOOLS
    elif content.endswith("}"):
        content = content[:-1] + SICK_TOOLS
    else:
        print("ERROR: could not find TOOLS dict closing brace")
        sys.exit(1)
    print("✅ Added log_sick_day, get_sick_days, clear_sick_day to TOOLS dict")


# ── Step 5: write ─────────────────────────────────────────────────────────────
with open(REGISTRY, "w") as f:
    f.write(content)

print(f"✅ mcp/registry.py written ({len(content.splitlines())} lines)")
print()
print("Next: build the layer and deploy — run deploy/sick_days_deploy.sh")
