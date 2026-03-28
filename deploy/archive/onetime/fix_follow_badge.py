#!/usr/bin/env python3
"""Fix nav.js BADGE_MAP: Follow key /chronicle/ → /subscribe/."""
import os

FPATH = os.path.expanduser("~/Documents/Claude/life-platform/site/assets/js/nav.js")

with open(FPATH, "r") as f:
    content = f.read()

# Fix BADGE_MAP key for Follow section
OLD = "'/chronicle/': ['/chronicle/', '/chronicle/archive/', '/weekly/'],"
NEW = "'/subscribe/': ['/chronicle/', '/chronicle/archive/', '/weekly/', '/subscribe/'],"

if OLD in content:
    content = content.replace(OLD, NEW)
    with open(FPATH, "w") as f:
        f.write(content)
    print("DONE: nav.js BADGE_MAP Follow key → /subscribe/")
elif "'/subscribe/': ['/chronicle/" in content:
    print("SKIP: Already fixed")
else:
    print("WARN: Could not find old pattern — manual fix needed")
