#!/usr/bin/env python3
"""
Targeted fix for store_installment signature in wednesday_chronicle_lambda.py.
Patches exactly lines 1497-1498 to add confidence kwargs.

Run from project root:
  python3 deploy/fix_store_installment_sig.py
"""

from pathlib import Path

TARGET = Path(__file__).parent.parent / "lambdas/wednesday_chronicle_lambda.py"
lines = TARGET.read_text().splitlines(keepends=True)

OLD_1 = "def store_installment(date_str, week_num, title, stats_line, raw_markdown,\n"
OLD_2 = "                      body_html, themes, has_board):\n"

# Already patched check
content = "".join(lines)
if 'confidence_level="MEDIUM"' in content:
    print("✅ store_installment signature already updated — skipping")
    raise SystemExit(0)

# Find the two-line signature
for i in range(len(lines) - 1):
    if lines[i] == OLD_1 and lines[i+1] == OLD_2:
        lines[i]   = "def store_installment(date_str, week_num, title, stats_line, raw_markdown,\n"
        lines[i+1] = ('                      body_html, themes, has_board,'
                      ' confidence_level="MEDIUM", confidence_badge_html=""):  # BS-05\n')
        TARGET.write_text("".join(lines))
        print(f"✅ store_installment signature updated at line {i+1}")
        print("   Deploy: bash deploy/deploy_lambda.sh wednesday-chronicle lambdas/wednesday_chronicle_lambda.py")
        raise SystemExit(0)

print("❌ Signature anchor not found — already patched or file changed")
print(f"   Check lines around 1497 in {TARGET}")
