#!/usr/bin/env python3
"""
fix_brittany_user_id.py — Fix hardcoded USER#matthew in brittany_email_lambda.py (D1 compliance)

Run from project root:
    python3 deploy/fix_brittany_user_id.py
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent
TARGET = ROOT / "lambdas" / "brittany_email_lambda.py"

REPLACEMENTS = [
    # 1. Add USER_ID env var alongside existing constants
    (
        '_REGION    = os.environ.get("AWS_REGION", "us-west-2")\n'
        'TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")\n'
        'SENDER     = os.environ["EMAIL_SENDER"]',
        '_REGION    = os.environ.get("AWS_REGION", "us-west-2")\n'
        'TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")\n'
        'USER_ID    = os.environ.get("USER_ID", "matthew")\n'
        'SENDER     = os.environ["EMAIL_SENDER"]',
    ),
    # 2. query_range pk
    (
        '    pk = "USER#matthew#SOURCE#" + source',
        '    pk = f"USER#{USER_ID}#SOURCE#{source}"',
    ),
    # 3. query_journal_range pk
    (
        '        ":pk": "USER#matthew#SOURCE#notion",',
        '        ":pk": f"USER#{USER_ID}#SOURCE#notion",',
    ),
    # 4. fetch_profile pk
    (
        '        r = table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"})',
        '        r = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})',
    ),
]


def fix():
    src = TARGET.read_text(encoding="utf-8")
    changed = False

    if 'USER_ID    = os.environ.get("USER_ID"' in src and f'"USER#{USER_ID}' not in src:
        pass  # already has USER_ID but not yet applied — fall through

    for old, new in REPLACEMENTS:
        if old in src:
            src = src.replace(old, new, 1)
            print(f"[OK]   replaced: {old[:60].strip()!r}")
            changed = True
        elif new in src:
            print(f"[INFO] already fixed: {new[:60].strip()!r}")
        else:
            print(f"[WARN] anchor not found: {old[:60].strip()!r}")

    if changed:
        TARGET.write_text(src, encoding="utf-8")
        print("[OK]   brittany_email_lambda.py written")
    else:
        print("[INFO] No changes needed")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("D1 fix — brittany_email_lambda.py USER_ID")
    print("=" * 60)
    fix()
    print("\nRun: python3 -m pytest tests/ -x -q")
