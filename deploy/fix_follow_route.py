#!/usr/bin/env python3
"""Fix bottom nav Follow route: /chronicle/ → /subscribe/ with mail icon."""
import os

FPATH = os.path.expanduser("~/Documents/Claude/life-platform/site/assets/js/components.js")

with open(FPATH, "r") as f:
    content = f.read()

OLD = "{ href: '/chronicle/', label: 'Follow',  icon: '<path d=\"M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z\"/><path d=\"M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z\"/>' }"
NEW = "{ href: '/subscribe/', label: 'Follow',  icon: '<path d=\"M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z\"/><polyline points=\"22,6 12,13 2,6\"/>' }"

if OLD in content:
    content = content.replace(OLD, NEW)
    with open(FPATH, "w") as f:
        f.write(content)
    print("DONE: Bottom nav Follow → /subscribe/ with mail icon")
elif "/subscribe/', label: 'Follow'" in content:
    print("SKIP: Already fixed")
else:
    print("WARN: Could not find old pattern — manual fix needed")
