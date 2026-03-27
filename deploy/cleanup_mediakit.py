#!/usr/bin/env python3
"""Remove orphaned media kit content from about/index.html"""
import os

path = os.path.join(os.path.dirname(__file__), '..', 'site', 'about', 'index.html')
path = os.path.abspath(path)

lines = open(path).readlines()
start = None
end = None
for i, line in enumerate(lines):
    if 'REMOVED_MEDIA_KIT_START' in line:
        start = i
    if 'REMOVED_MEDIA_KIT_END' in line:
        end = i
        break

if start is not None and end is not None:
    cleaned = lines[:start] + lines[end+1:]
    open(path, 'w').writelines(cleaned)
    removed = end - start + 1
    print(f"Removed {removed} lines ({start+1} to {end+1})")
    print(f"File now has {len(cleaned)} lines")
else:
    print("Markers not found - file may already be clean")
