#!/usr/bin/env python3
"""
Fix wednesday_chronicle_lambda.py BS-05 issues:
  1. Remove duplicate confidence block (patch_chronicle_bs05.py ran twice)
  2. Update store_installment() signature to accept confidence kwargs
  3. Add _confidence_level + _confidence_badge_html to DDB item

Run from project root:
  python3 deploy/fix_chronicle_bs05.py

Idempotent.
"""

import sys
import re
from pathlib import Path

TARGET = Path(__file__).parent.parent / "lambdas/wednesday_chronicle_lambda.py"
content = TARGET.read_text()
original = content

FIXES_APPLIED = []

# ─────────────────────────────────────────────────────────────────────────────
# FIX 1: Remove duplicate confidence block
# The block starts with "    # BS-05: Compute confidence badge" and ends at the
# closing except block. Find if there are 2 occurrences and remove the second.
# ─────────────────────────────────────────────────────────────────────────────

BLOCK_START = "    # BS-05: Compute confidence badge based on total journey data depth."
occurrences = [i for i in range(len(content)) if content[i:i+len(BLOCK_START)] == BLOCK_START]

if len(occurrences) >= 2:
    # Find the second occurrence and remove it
    second_start = occurrences[1]
    # Find the end of the second block: look for the next non-blank, non-indented-conf line
    # The block ends at `logger.info(f"Title: \"{title}\"")` which immediately follows
    # Actually find the next logger.info line after the second block
    BLOCK_END_MARKER = '    logger.info(f"Title: \\"'
    end_idx = content.find(BLOCK_END_MARKER, second_start)
    if end_idx == -1:
        # Try alternate
        BLOCK_END_MARKER2 = "    logger.info(f'Title:"
        end_idx = content.find(BLOCK_END_MARKER2, second_start)
    
    if end_idx != -1:
        # Remove from second_start to end_idx (keep the logger.info line)
        content = content[:second_start] + content[end_idx:]
        FIXES_APPLIED.append("FIX 1: Duplicate confidence block removed")
    else:
        print("⚠️  FIX 1: Could not find end marker for second confidence block — skipping")
elif len(occurrences) == 1:
    print("ℹ️  FIX 1: Only one confidence block found — no duplicate to remove")
    FIXES_APPLIED.append("FIX 1: Already clean (no duplicate)")
else:
    print("⚠️  FIX 1: No confidence block found at all")


# ─────────────────────────────────────────────────────────────────────────────
# FIX 2: Update store_installment() signature
# ─────────────────────────────────────────────────────────────────────────────

OLD_SIG = 'def store_installment(date_str, week_num, title, stats_line, raw_markdown, content_html, tags, has_board):'
NEW_SIG = 'def store_installment(date_str, week_num, title, stats_line, raw_markdown, content_html, tags, has_board,\n                      confidence_level="MEDIUM", confidence_badge_html=""):  # BS-05'

if 'confidence_level="MEDIUM"' in content and 'def store_installment' in content:
    print("ℹ️  FIX 2: store_installment signature already updated")
    FIXES_APPLIED.append("FIX 2: Already updated")
elif OLD_SIG in content:
    content = content.replace(OLD_SIG, NEW_SIG, 1)
    FIXES_APPLIED.append("FIX 2: store_installment signature updated")
else:
    print("⚠️  FIX 2: store_installment signature anchor not found — check manually")
    print(f'   Looking for: {OLD_SIG!r}')


# ─────────────────────────────────────────────────────────────────────────────
# FIX 3: Add confidence fields to DDB item in store_installment
# Find '"author": "Elena Voss",' and insert confidence fields after it
# ─────────────────────────────────────────────────────────────────────────────

AUTHOR_ANCHOR = '"author": "Elena Voss",'
ALREADY_PATCHED = '"_confidence_level": confidence_level'

if ALREADY_PATCHED in content:
    print("ℹ️  FIX 3: confidence fields already in DDB item")
    FIXES_APPLIED.append("FIX 3: Already updated")
elif AUTHOR_ANCHOR in content:
    NEW_AUTHOR = (
        '"author": "Elena Voss",\n'
        '            "_confidence_level": confidence_level,       # BS-05\n'
        '            "_confidence_badge_html": confidence_badge_html,  # BS-05 — used by chronicle-email-sender'
    )
    content = content.replace(AUTHOR_ANCHOR, NEW_AUTHOR, 1)
    FIXES_APPLIED.append("FIX 3: Confidence fields added to DDB item")
else:
    print("⚠️  FIX 3: 'author' anchor not found in store_installment item — check manually")
    print("   Add manually: '_confidence_level': confidence_level, '_confidence_badge_html': confidence_badge_html")


# ─────────────────────────────────────────────────────────────────────────────
# Write file if changes were made
# ─────────────────────────────────────────────────────────────────────────────

if content != original:
    TARGET.write_text(content)
    print(f"\n✅ {len(FIXES_APPLIED)} fix(es) applied to {TARGET.name}:")
    for f in FIXES_APPLIED:
        print(f"   {f}")
    print("\n   Deploy: bash deploy/deploy_lambda.sh wednesday-chronicle lambdas/wednesday_chronicle_lambda.py")
else:
    print(f"\nℹ️  No changes needed — file already correct")
    for f in FIXES_APPLIED:
        print(f"   {f}")
