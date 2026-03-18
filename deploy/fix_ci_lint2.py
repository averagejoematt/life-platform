#!/usr/bin/env python3
"""
fix_ci_lint2.py — Fix the 5 remaining F821/F823 errors.

1. tools_lifestyle.py:387,1309 — add `from decimal import Decimal`
2. tools_nutrition.py:403,494,581 — remove `table = table` self-assignments

Run from project root:
  python3 deploy/fix_ci_lint2.py
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def write(path, content):
    (ROOT / path).write_text(content, encoding="utf-8")
    print(f"  ✅ Wrote {path}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. tools_lifestyle.py — add Decimal import
# ─────────────────────────────────────────────────────────────────────────────
content = read("mcp/tools_lifestyle.py")

if "from decimal import Decimal" not in content:
    content = content.replace(
        "from boto3.dynamodb.conditions import Key\n",
        "from boto3.dynamodb.conditions import Key\nfrom decimal import Decimal\n",
    )
    write("mcp/tools_lifestyle.py", content)
    print("  ✅ mcp/tools_lifestyle.py: added Decimal import")
else:
    print("  ℹ️  mcp/tools_lifestyle.py: Decimal already imported")


# ─────────────────────────────────────────────────────────────────────────────
# 2. tools_nutrition.py — remove `table = table` self-assignments
#    These were created by the previous fix replacing `get_table()` → `table`
#    in lines like `table = get_table()`. Since `table` is already imported
#    from mcp.config, just delete these lines.
# ─────────────────────────────────────────────────────────────────────────────
content = read("mcp/tools_nutrition.py")

# Count occurrences before
count_before = content.count("    table = table\n")
if count_before == 0:
    print("  ℹ️  mcp/tools_nutrition.py: no 'table = table' lines found — already clean")
else:
    # Remove all `    table = table` lines
    lines = content.splitlines(keepends=True)
    new_lines = [
        line for line in lines
        if line.rstrip() != "    table = table"
    ]
    new_content = "".join(new_lines)
    count_after = new_content.count("    table = table\n")
    write("mcp/tools_nutrition.py", new_content)
    print(f"  ✅ mcp/tools_nutrition.py: removed {count_before - count_after} 'table = table' self-assignment(s)")


print("\n✅ Done. Now run:")
print("  python3 -m flake8 lambdas/ mcp/ --count --select=E9,F63,F7,F82 --show-source --statistics")
