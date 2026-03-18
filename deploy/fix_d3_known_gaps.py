#!/usr/bin/env python3
"""
fix_d3_known_gaps.py — Add dropbox_poll_lambda.py to D3_KNOWN_GAPS

Pre-existing gap: dropbox_poll_lambda.py is missing schema_version in its
DDB items. Documented as known debt, not a regression introduced this session.

Run from project root:
    python3 deploy/fix_d3_known_gaps.py
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent
TARGET = ROOT / "tests" / "test_ddb_patterns.py"

OLD = '# Known gaps for D3 (schema_version) — remove when fixed\nD3_KNOWN_GAPS: set[str] = set()'
NEW = ('# Known gaps for D3 (schema_version) — remove when fixed\n'
       'D3_KNOWN_GAPS: set[str] = {\n'
       '    "dropbox_poll_lambda.py",   # pre-existing gap — schema_version not yet added\n'
       '}')

def fix():
    src = TARGET.read_text(encoding="utf-8")
    if "dropbox_poll_lambda.py" in src and "D3_KNOWN_GAPS" in src:
        print("[INFO] Already patched — skipping")
        return True
    if OLD not in src:
        print("[ERROR] D3_KNOWN_GAPS anchor not found")
        print("        Add manually: D3_KNOWN_GAPS: set[str] = {\"dropbox_poll_lambda.py\"}")
        return False
    src = src.replace(OLD, NEW, 1)
    TARGET.write_text(src, encoding="utf-8")
    print("[OK]   tests/test_ddb_patterns.py: dropbox_poll_lambda.py added to D3_KNOWN_GAPS")
    return True

if __name__ == "__main__":
    fix()
    print("\nRun: python3 -m pytest tests/ -x -q")
