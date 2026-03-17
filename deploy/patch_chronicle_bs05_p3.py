#!/usr/bin/env python3
"""
Patch 3 for wednesday_chronicle_lambda.py — BS-05
Adds _confidence_level + _confidence_badge_html to store_installment() signature and DDB item.

Run from project root:
  python3 deploy/patch_chronicle_bs05_p3.py

Idempotent — skips if already patched.
"""
import sys
from pathlib import Path

TARGET = Path(__file__).parent.parent / "lambdas/wednesday_chronicle_lambda.py"
content = TARGET.read_text()

if "_confidence_level" in content and '"author": "Elena Voss"' in content and "_confidence_badge_html" in content:
    # Check if confidence fields are already in store_installment's DDB item
    if '"_confidence_level": confidence_level' in content:
        print("✅ Patch 3 already applied — skipping")
        sys.exit(0)

# ── Step A: Update function signature ────────────────────────────────────────
OLD_SIG = 'def store_installment(date_str, week_num, title, stats_line, raw_markdown, content_html, tags, has_board):'
NEW_SIG = ('def store_installment(date_str, week_num, title, stats_line, raw_markdown, content_html, tags, has_board,\n'
           '                      confidence_level="MEDIUM", confidence_badge_html=""):\n'
           '    # BS-05: confidence_level + confidence_badge_html stored for chronicle-email-sender')

if OLD_SIG not in content:
    print(f"❌ Signature anchor not found. Check function definition manually.")
    print(f"   Expected: {OLD_SIG!r}")
    # Show what's in the file near 'def store_installment'
    idx = content.find('def store_installment')
    if idx >= 0:
        print(f"   Found: {content[idx:idx+120]!r}")
    sys.exit(1)

content = content.replace(OLD_SIG, NEW_SIG, 1)
print("✅ Patch 3a: store_installment() signature updated")

# ── Step B: Add confidence fields to DDB item (after "author" field) ─────────
OLD_AUTHOR = '"author": "Elena Voss",'
NEW_AUTHOR = ('"author": "Elena Voss",\n'
              '            "_confidence_level": confidence_level,\n'
              '            "_confidence_badge_html": confidence_badge_html,')

if OLD_AUTHOR not in content:
    print("❌ 'author' anchor not found in store_installment DDB item. Apply manually:")
    print('   Add after \'\"author\": \"Elena Voss\",\'')
    print('   "_confidence_level": confidence_level,')
    print('   "_confidence_badge_html": confidence_badge_html,')
    sys.exit(1)

content = content.replace(OLD_AUTHOR, NEW_AUTHOR, 1)
print("✅ Patch 3b: _confidence fields added to DDB item")

TARGET.write_text(content)
print(f"\n✅ Patch 3 complete — {TARGET}")
print("   Deploy: bash deploy/deploy_lambda.sh wednesday-chronicle lambdas/wednesday_chronicle_lambda.py")
