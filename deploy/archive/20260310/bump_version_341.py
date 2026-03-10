#!/usr/bin/env python3
"""
bump_version_341.py — Update PROJECT_PLAN.md + prepend CHANGELOG entry.
Run from project root: python3 deploy/bump_version_341.py
"""
import os
import subprocess

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1. Fix CHANGELOG (restore from git + prepend new entry)
print("1. Restoring CHANGELOG.md from git...")
subprocess.run(["git", "checkout", "HEAD", "--", "docs/CHANGELOG.md"], cwd=PROJ, check=True)

prepend_path = os.path.join(PROJ, "docs", "CHANGELOG_PREPEND.md")
if os.path.exists(prepend_path):
    with open(prepend_path) as f:
        prepend = f.read()
    changelog_path = os.path.join(PROJ, "docs", "CHANGELOG.md")
    with open(changelog_path) as f:
        existing = f.read()
    if "v3.4.1" not in existing:
        with open(changelog_path, "w") as f:
            f.write(prepend + existing)
        print("   ✅ v3.4.1 prepended to CHANGELOG.md")
    else:
        print("   ℹ️  v3.4.1 already in CHANGELOG.md")
    os.remove(prepend_path)
else:
    print("   ⚠️  CHANGELOG_PREPEND.md not found — CHANGELOG not updated")

# 2. Bump PROJECT_PLAN.md version references
print("2. Bumping PROJECT_PLAN.md to v3.4.1...")
pp_path = os.path.join(PROJ, "docs", "PROJECT_PLAN.md")
with open(pp_path) as f:
    pp = f.read()

replacements = [
    ("v3.4.0 — 144 MCP tools, 41 Lambdas, 30 modules",
     "v3.4.1 — 147 MCP tools, 41 Lambdas, 31 modules"),
    ("**Platform version:** v3.4.0",
     "**Platform version:** v3.4.1"),
    ("144 tools across 30-module package",
     "147 tools across 31-module package"),
]

changed = 0
for old, new in replacements:
    if old in pp:
        pp = pp.replace(old, new, 1)
        changed += 1

if changed:
    with open(pp_path, "w") as f:
        f.write(pp)
    print(f"   ✅ {changed} replacements applied to PROJECT_PLAN.md")
else:
    print("   ℹ️  PROJECT_PLAN.md already up to date")

print("\n✅ Version bump complete.")
print("\nNext: git add -A && git commit -m 'v3.4.1: sick day system' && git push")
