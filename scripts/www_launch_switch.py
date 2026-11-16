#!/usr/bin/env python3
"""scripts/www_launch_switch.py — the Python reader of the v9 build's split go-live switches (2026-11-09).

The Laboratory (L1) and the Human Story (HS1) were built dark behind env switches (WEB_LAB=1, WEB_STORY=1) that give
a private, never-deployed build. Each now also has ONE committed go-live constant, in the JS helper every gated piece
already reads:

    www/src/lib/lab.js          export const LAB_LIVE = false;
    www/src/lib/story_dark.js   export const STORY_LIVE = false;

The owner's go for either is the one-line PR that sets its constant to `true`. The Python side (the snapshot
producer's twins in publish_snapshot_lab.py / publish_snapshot_story.py, and scripts/check_www_build.py's deploy scan)
reads the same line as text, so there is one switch per feature, never two that could disagree.

FAIL CLOSED: a constant that cannot be read — the file missing, the line absent, duplicated or not a literal
`true`/`false` — reads as DARK (False). tests/test_www_launch_switch.py pins that each line is found exactly once, so
a refactor that breaks the reader reds CI instead of silently darkening (or lighting) a feature.

  python3 scripts/www_launch_switch.py            # prints both switches
"""

from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAB_JS = os.path.join(REPO, "www", "src", "lib", "lab.js")
STORY_JS = os.path.join(REPO, "www", "src", "lib", "story_dark.js")


def read_flag(path: str, name: str) -> bool | None:
    """The committed value of `export const <name> = true|false;` in `path`, or None when it cannot be read exactly."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    hits = re.findall(rf"^export const {re.escape(name)} = (true|false);[ \t]*$", text, flags=re.MULTILINE)
    if len(hits) != 1:
        return None
    return hits[0] == "true"


def lab_live(path: str = LAB_JS) -> bool:
    """Is the Laboratory committed live? (www/src/lib/lab.js LAB_LIVE; unreadable = dark.)"""
    return read_flag(path, "LAB_LIVE") is True


def story_live(path: str = STORY_JS) -> bool:
    """Is the Human Story committed live? (www/src/lib/story_dark.js STORY_LIVE; unreadable = dark.)"""
    return read_flag(path, "STORY_LIVE") is True


if __name__ == "__main__":
    print(f"LAB_LIVE={lab_live()} STORY_LIVE={story_live()}")
    sys.exit(0)
