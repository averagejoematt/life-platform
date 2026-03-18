#!/usr/bin/env python3
"""
deploy/fix_test_shared_modules.py — Replace test( → _run( in test_shared_modules.py.

Fixes: ERROR tests/test_shared_modules.py::test
Root cause: pytest collects def test(name, fn) as a test function and calls
it with no args, causing TypeError. Renaming to _run() hides it from collection.

This script replaces all test("...", ...) call sites with _run("...", ...).
The def test → def _run rename was already done by fix_i4_etc.py.

Usage: python3 deploy/fix_test_shared_modules.py
"""
import re, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
path = os.path.join(ROOT, "tests", "test_shared_modules.py")

with open(path, encoding="utf-8") as f:
    src = f.read()

# Replace all call sites: test("...", at start of line (with leading whitespace)
# Pattern: lines that start with `test("` — these are call sites, not the def
new_src = re.sub(r'^test\(', '_run(', src, flags=re.MULTILINE)

# Verify def is already renamed (from edit_file fix)
if 'def test(' in new_src:
    # fallback: rename def too
    new_src = new_src.replace('def test(', 'def _run(', 1)

changed = src.count('\ntest(') 
with open(path, "w", encoding="utf-8") as f:
    f.write(new_src)

print(f"✅ Replaced {new_src.count('_run(') - src.count('_run(')} test() calls with _run()")
print(f"   File: {path}")
