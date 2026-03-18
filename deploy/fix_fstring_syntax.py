#!/usr/bin/env python3
"""
fix_fstring_syntax.py — Fix raw newlines inside f-strings in daily_insight_compute_lambda.py

The patch_deficit_ceiling.py script introduced two syntax errors:
  1. A literal newline inside an f-string expression (line ~1551)
  2. A raw newline inside a string used as str.join() separator (line ~1573)

This script uses bytes-level replacement to avoid any quoting issues.

Run from project root:
    python3 deploy/fix_fstring_syntax.py
"""
import ast
import sys
from pathlib import Path

ROOT   = Path(__file__).parent.parent
TARGET = ROOT / "lambdas" / "daily_insight_compute_lambda.py"

# Read as bytes to avoid encoding issues, then decode
raw = TARGET.read_bytes()

# Fix 1: the broken f-string body assignment.
# The patch wrote a literal newline between two adjacent f-string parts.
# Pattern (as bytes): f"  {channels_desc}\n"  (with real newline before closing quote)
# Replace with:       f"  {channels_desc}\n"  (with escaped backslash-n)
#
# The actual bytes on disk look like:
#   b'f"  {channels_desc}\n"\n                f"  Weight rate: {rate_str}"'
# where the \n between channels_desc and the closing " is a REAL newline (0x0a),
# not the two-char sequence backslash-n.
#
# We want: channels_desc}" + "\n" + "  Weight rate
# i.e. join the two strings explicitly rather than relying on adjacent f-string concatenation

OLD1 = (
    b'            body = (\n'
    b'                f"  {channels_desc}\n'
    b'"\n'
    b'                f"  Weight rate: {rate_str}"\n'
    b'            )'
)
NEW1 = (
    b'            body = (\n'
    b'                f"  {channels_desc}\\n"\n'
    b'                f"  Weight rate: {rate_str}"\n'
    b'            )'
)

# Fix 2: the broken alert_block join.
# The patch wrote: alert_block = "\n".join([...])
# where the "\n" contains a REAL newline (0x0a) instead of backslash-n.
# The bytes on disk look like: b'alert_block = "\n".join(['
OLD2 = b'        alert_block = "\n".join([headline, body, prescription, instruction, disclaimer])'
NEW2 = b'        alert_block = "\\n".join([headline, body, prescription, instruction, disclaimer])'

changes = 0

if OLD1 in raw:
    raw = raw.replace(OLD1, NEW1, 1)
    print("[OK]   Fix 1 applied: broken f-string body assignment")
    changes += 1
elif NEW1 in raw:
    print("[INFO] Fix 1 already applied")
else:
    print("[WARN] Fix 1 pattern not found — inspecting around line 1551...")
    lines = raw.split(b'\n')
    for i, line in enumerate(lines[1545:1560], start=1546):
        print(f"  line {i}: {line!r}")

if OLD2 in raw:
    raw = raw.replace(OLD2, NEW2, 1)
    print("[OK]   Fix 2 applied: broken alert_block join separator")
    changes += 1
elif NEW2 in raw:
    print("[INFO] Fix 2 already applied")
else:
    print("[WARN] Fix 2 pattern not found — inspecting around line 1573...")
    lines = raw.split(b'\n')
    for i, line in enumerate(lines[1568:1580], start=1569):
        print(f"  line {i}: {line!r}")

# Verify syntax
src = raw.decode("utf-8")
try:
    ast.parse(src)
    print("[OK]   File parses cleanly")
except SyntaxError as e:
    print(f"[ERROR] Still has SyntaxError at line {e.lineno}: {e.msg}")
    print("        Dumping lines around error:")
    lines = src.splitlines()
    for i in range(max(0, e.lineno-3), min(len(lines), e.lineno+3)):
        print(f"  {i+1}: {lines[i]!r}")
    sys.exit(1)

if changes > 0:
    TARGET.write_bytes(raw)
    print(f"[OK]   Wrote {TARGET.name} ({changes} fix(es) applied)")
else:
    print("[INFO] No changes needed")
