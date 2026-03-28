#!/usr/bin/env python3
"""Bump version in sync_doc_metadata.py from v3.9.34 → v3.9.35"""
import os

f = os.path.expanduser("~/Documents/Claude/life-platform/deploy/sync_doc_metadata.py")
with open(f) as fh:
    content = fh.read()

content = content.replace('"v3.9.34"', '"v3.9.35"')
content = content.replace('"2026-03-26"', '"2026-03-26"')  # date stays same (same day)

with open(f, "w") as fh:
    fh.write(content)

print("✓ Version bumped to v3.9.35")
