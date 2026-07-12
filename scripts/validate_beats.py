#!/usr/bin/env python3
"""Validate site/story/build/beats.json against the build-beat schema (#953).

Fast, stdlib-only pre-commit check for the /wrap build-beat step. Catches the
known failure class BEFORE it reds CI for every concurrent session: the wiki
session (2026-07-10) wrote string PRs (`"prs": ["#923", ...]`) where the schema
wants label/url objects, breaking tests/test_build_dispatches.py repo-wide.

Schema per beat (docs/content/BUILD_DISPATCH_CHECKLIST.md):
    id               non-empty string, unique across the feed
    date             YYYY-MM-DD
    title            non-empty string
    shipped          string, > 20 chars  (four-part honesty format, #1120)
    why_it_mattered  string, > 20 chars  (the narrative layer — stakes, not fabricated outcomes)
    gotcha           string, > 20 chars
    honest_miss      string, > 20 chars
    prs           optional list of {"label": "PR #831", "url": "https://github.com/averagejoematt/life-platform/pull/831"}

Usage: python3 scripts/validate_beats.py   (exit 0 = valid, 1 = errors listed)
"""

from __future__ import annotations

import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEATS_PATH = os.path.join(REPO, "site", "story", "build", "beats.json")
PR_URL_PREFIX = "https://github.com/averagejoematt/life-platform/pull/"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
PROSE_FIELDS = ("shipped", "why_it_mattered", "gotcha", "honest_miss")


def validate(data) -> list[str]:
    """Return a list of human-readable schema errors (empty = valid)."""
    errors: list[str] = []
    beats = data.get("beats") if isinstance(data, dict) else None
    if not isinstance(beats, list):
        return ['top level must be {"beats": [...]}']

    seen_ids: set[str] = set()
    for i, b in enumerate(beats):
        where = f"beats[{i}]"
        if not isinstance(b, dict):
            errors.append(f"{where}: beat must be an object, got {type(b).__name__}")
            continue
        bid = b.get("id")
        where = f"beats[{i}] ({bid})" if bid else where
        if not bid or not isinstance(bid, str):
            errors.append(f"{where}: missing/empty 'id'")
        elif bid in seen_ids:
            errors.append(f"{where}: duplicate id {bid!r}")
        else:
            seen_ids.add(bid)
        if not isinstance(b.get("date"), str) or not DATE_RE.fullmatch(b.get("date", "")):
            errors.append(f"{where}: 'date' must be YYYY-MM-DD, got {b.get('date')!r}")
        if not b.get("title") or not isinstance(b.get("title"), str):
            errors.append(f"{where}: missing/empty 'title'")
        for key in PROSE_FIELDS:
            val = b.get(key)
            if not isinstance(val, str) or len(val) <= 20:
                errors.append(f"{where}: '{key}' must be a string > 20 chars (the four-part format IS the honesty — #1120)")

        prs = b.get("prs", [])
        if not isinstance(prs, list):
            errors.append(f"{where}: 'prs' must be a list, got {type(prs).__name__}")
            continue
        for j, pr in enumerate(prs):
            if not isinstance(pr, dict):
                errors.append(
                    f"{where}: prs[{j}] must be an object {{'label': ..., 'url': ...}}, "
                    f"got {type(pr).__name__} ({pr!r}) — string PRs broke test_build_dispatches on 2026-07-10"
                )
                continue
            if not pr.get("label") or not isinstance(pr.get("label"), str):
                errors.append(f"{where}: prs[{j}] missing/empty 'label'")
            url = pr.get("url")
            if not isinstance(url, str) or not url.startswith(PR_URL_PREFIX):
                errors.append(f"{where}: prs[{j}] 'url' must start with {PR_URL_PREFIX}, got {url!r}")
    return errors


def main() -> int:
    try:
        with open(BEATS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"validate_beats: {BEATS_PATH} not found", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"validate_beats: beats.json is not valid JSON: {e}", file=sys.stderr)
        return 1

    errors = validate(data)
    if errors:
        print(f"validate_beats: {len(errors)} schema error(s) in {os.path.relpath(BEATS_PATH, REPO)}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"validate_beats: OK ({len(data['beats'])} beats)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
