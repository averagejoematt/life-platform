#!/usr/bin/env python3
"""
PROD-2 Phase 1: Remove hardcoded defaults from os.environ.get() calls.

Replaces patterns that would silently allow Lambdas to run as "matthew" if
the USER_ID env var is missing — which masks misconfiguration.

Replacements performed:
  1. os.environ.get("USER_ID", "matthew")           → os.environ["USER_ID"]
  2. os.environ.get("S3_BUCKET", "matthew-life-platform") → os.environ["S3_BUCKET"]
  3. os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com") → os.environ["EMAIL_RECIPIENT"]
  4. os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")    → os.environ["EMAIL_SENDER"]
  5. insight_writer.init(table, "matthew")           → insight_writer.init(table, USER_ID)
  6. monthly_digest: hardcoded RECIPIENT/SENDER strings → env var reads
  7. weekly_digest/nutrition_review: fetch_profile hardcoded "USER#matthew" → USER_ID variable

Run from repo root:
  python3 deploy/prod2_phase1_remove_defaults.py [--dry-run]
"""

import os
import sys
import re
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv

REPO_ROOT = Path(__file__).resolve().parent.parent
LAMBDAS   = REPO_ROOT / "lambdas"
MCP_DIR   = REPO_ROOT / "mcp"

# ── Universal replacements (all .py files) ────────────────────────────────────
UNIVERSAL = [
    (
        'os.environ.get("USER_ID", "matthew")',
        'os.environ["USER_ID"]',
    ),
    (
        "os.environ.get('USER_ID', 'matthew')",
        "os.environ['USER_ID']",
    ),
    (
        'os.environ.get("S3_BUCKET", "matthew-life-platform")',
        'os.environ["S3_BUCKET"]',
    ),
    (
        "os.environ.get('S3_BUCKET', 'matthew-life-platform')",
        "os.environ['S3_BUCKET']",
    ),
    (
        'os.environ.get("EMAIL_RECIPIENT", "awsdev@mattsusername.com")',
        'os.environ["EMAIL_RECIPIENT"]',
    ),
    (
        'os.environ.get("EMAIL_SENDER", "awsdev@mattsusername.com")',
        'os.environ["EMAIL_SENDER"]',
    ),
    # insight_writer called with hardcoded user string
    (
        'insight_writer.init(table, "matthew")',
        'insight_writer.init(table, USER_ID)',
    ),
]

# ── File-specific replacements ────────────────────────────────────────────────
FILE_SPECIFIC = {
    "monthly_digest_lambda.py": [
        # Hardcoded (not even using env var) — convert to env var reads
        (
            'RECIPIENT         = "awsdev@mattsusername.com"',
            'RECIPIENT         = os.environ["EMAIL_RECIPIENT"]',
        ),
        (
            'SENDER            = "awsdev@mattsusername.com"',
            'SENDER            = os.environ["EMAIL_SENDER"]',
        ),
        # Profile fetch uses wrong SK
        (
            'p = table.get_item(Key={"pk":f"USER#{USER_ID}","sk":"PROFILE"}).get("Item",{})',
            'p = table.get_item(Key={"pk":f"USER#{USER_ID}","sk":"PROFILE#v1"}).get("Item",{})',
        ),
    ],
    "weekly_digest_lambda.py": [
        # fetch_profile() hardcodes "USER#matthew" instead of using USER_ID variable
        (
            '"pk": "USER#matthew"',
            '"pk": f"USER#{USER_ID}"',
        ),
    ],
    "nutrition_review_lambda.py": [
        (
            '"pk": "USER#matthew"',
            '"pk": f"USER#{USER_ID}"',
        ),
    ],
}

# ── Walk files ────────────────────────────────────────────────────────────────
def collect_files():
    files = list(LAMBDAS.glob("*.py"))
    files += list(MCP_DIR.glob("*.py"))
    return [f for f in files if "__pycache__" not in str(f)]


def apply_replacements(path: Path, replacements: list[tuple[str, str]]) -> int:
    """Apply list of (old, new) replacements to a file. Returns change count."""
    text = path.read_text(encoding="utf-8")
    original = text
    count = 0
    for old, new in replacements:
        occurrences = text.count(old)
        if occurrences:
            text = text.replace(old, new)
            count += occurrences
            print(f"  [{path.name}] {occurrences}× '{old[:60]}' → '{new[:60]}'")
    if count and not DRY_RUN:
        path.write_text(text, encoding="utf-8")
    elif count and DRY_RUN:
        print(f"  [DRY RUN] Would write {count} change(s) to {path.name}")
    return count


def main():
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    print(f"\n{'='*60}")
    print(f" PROD-2 Phase 1 — Remove hardcoded defaults ({mode})")
    print(f"{'='*60}\n")

    files = collect_files()
    total_changes = 0
    changed_files = []

    for path in sorted(files):
        replacements = list(UNIVERSAL)
        fname = path.name
        if fname in FILE_SPECIFIC:
            replacements += FILE_SPECIFIC[fname]

        n = apply_replacements(path, replacements)
        if n:
            total_changes += n
            changed_files.append(fname)

    print(f"\n{'='*60}")
    print(f" Summary: {total_changes} replacement(s) across {len(changed_files)} file(s)")
    if changed_files:
        print(" Changed files:")
        for f in changed_files:
            print(f"   - {f}")
    if DRY_RUN:
        print("\n ⚠️  DRY RUN — no files written. Remove --dry-run to apply.")
    else:
        print("\n ✅  Done. Verify with: git diff lambdas/ mcp/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
