#!/usr/bin/env python3
"""
PROD-2 Phase 1 — Remove hardcoded defaults & fix "matthew" hardcodes.

Changes applied:
  1. os.environ.get("USER_ID", "matthew")      → os.environ["USER_ID"]
  2. os.environ.get("S3_BUCKET", "matthew-life-platform") → os.environ["S3_BUCKET"]
  3. os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com") → os.environ["EMAIL_RECIPIENT"]
  4. os.environ.get("EMAIL_SENDER", ...)        → os.environ["EMAIL_SENDER"]
  5. monthly_digest hardcoded RECIPIENT/SENDER strings
  6. insight_writer.init(table, "matthew")      → insight_writer.init(table, USER_ID)
  7. weekly_digest: add USER_ID env var + fix all "USER#matthew" hardcodes

Run from project root:
  python3 deploy/prod2_phase1_fix.py
  git diff   # review before deploying
"""

import os
from pathlib import Path

ROOT        = Path(__file__).parent.parent
LAMBDAS_DIR = ROOT / "lambdas"
MCP_DIR     = ROOT / "mcp"

# ── Generic substitutions applied to every .py file ──
STRING_REPLACEMENTS = [
    ('os.environ.get("USER_ID", "matthew")',               'os.environ["USER_ID"]'),
    ('os.environ.get("S3_BUCKET", "matthew-life-platform")', 'os.environ["S3_BUCKET"]'),
    ('os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")', 'os.environ["EMAIL_RECIPIENT"]'),
    ('os.environ.get("EMAIL_SENDER",    "awsdev@mattsusername.com")', 'os.environ["EMAIL_SENDER"]'),
    ('os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")',    'os.environ["EMAIL_SENDER"]'),
    # monthly_digest uses bare string assignments (no os.environ.get)
    ('RECIPIENT         = "awsdev@mattsusername.com"', 'RECIPIENT         = os.environ["EMAIL_RECIPIENT"]'),
    ('SENDER            = "awsdev@mattsusername.com"', 'SENDER            = os.environ["EMAIL_SENDER"]'),
    # insight_writer.init hardcode
    ('insight_writer.init(table, "matthew")',  'insight_writer.init(table, USER_ID)'),
]

# ── weekly_digest-specific: run BEFORE generic substitutions ──
# (must run first because they match lines that generic subs would partially transform)
WEEKLY_DIGEST_PREFIXES = [
    # Inject USER_ID definition right after the SENDER env var line
    (
        'SENDER     = os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")',
        'SENDER     = os.environ["EMAIL_SENDER"]\nUSER_ID    = os.environ["USER_ID"]'
    ),
    # Fix all hardcoded DDB key patterns
    ('"pk": "USER#matthew"',         '"pk": f"USER#{USER_ID}"'),
    ('pk = f"USER#matthew#SOURCE#',  'pk = f"USER#{USER_ID}#SOURCE#'),
    ('":pk": "USER#matthew#SOURCE#', '":pk": f"USER#{USER_ID}#SOURCE#'),
]

def apply_list(text, pairs):
    changed = []
    for old, new in pairs:
        if old in text:
            text = text.replace(old, new)
            changed.append(old[:70])
    return text, changed

def process_file(path, prefix_replacements=None):
    original = path.read_text(encoding="utf-8")
    text = original
    changed = []

    if prefix_replacements:
        text, c = apply_list(text, prefix_replacements)
        changed += c

    text, c = apply_list(text, STRING_REPLACEMENTS)
    changed += c

    if text != original:
        path.write_text(text, encoding="utf-8")
        return changed
    return []

def main():
    total_files = total_changes = 0

    for py_file in sorted(LAMBDAS_DIR.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        prefix = WEEKLY_DIGEST_PREFIXES if py_file.name == "weekly_digest_lambda.py" else None
        changes = process_file(py_file, prefix)
        if changes:
            total_files += 1
            total_changes += len(changes)
            print(f"✅ {py_file.name}")
            for c in changes:
                print(f"   • {c!r}")

    mcp_config = MCP_DIR / "config.py"
    if mcp_config.exists():
        changes = process_file(mcp_config)
        if changes:
            total_files += 1
            total_changes += len(changes)
            print(f"✅ mcp/config.py")
            for c in changes:
                print(f"   • {c!r}")

    print(f"\n{'─'*60}")
    print(f"Done: {total_changes} replacements across {total_files} files.")
    print("Run `git diff` to review all changes before deploying.")

if __name__ == "__main__":
    os.chdir(ROOT)
    main()
