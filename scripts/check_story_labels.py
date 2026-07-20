#!/usr/bin/env python3
"""scripts/check_story_labels.py — the /wrap label-completeness gate (#1349).

THE PROBLEM
  `.claude/agents/issue-filer.md`'s ADR-099 contract requires every filed issue
  to carry "exactly one model:*" label (model:sonnet/model:opus/model:fable) —
  it is how a session's label query (`gh issue list --label model:sonnet ...`)
  routes work to the right lane. Nothing checked that the rule held over time:
  the SDLC review 2026-07-18 found two open `type:story` issues (#1243, #1228)
  with no `model:*` label at all — invisible until someone happened to grep
  for it, and every session seeding from a `model:*` query silently skipped
  them.

THE FIX
  A one-line wrap check, same shape as the #1259 memory-orphan gate in
  `.claude/commands/wrap.md`: list every open `type:story` issue lacking a
  `model:*` label. Must print nothing.

USAGE
  python3 scripts/check_story_labels.py
    Calls `gh issue list --label type:story --state open --json
    number,title,labels` live (network + gh auth) and reports violators.

  python3 scripts/check_story_labels.py --issues-json FIXTURE.json
    Offline mode for tests/CI — reads the same JSON shape from a file instead
    of invoking gh, so the regression guard can pin a fixture and run without
    network access.

EXIT CODE: 1 if any open type:story issue lacks a model:* label, else 0.
Live-fetch failures (no network/auth) are fail-open (exit 0, advisory) — this
is a wrap-time reflex, not a CI gate; it must never block on missing creds.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = "averagejoematt/life-platform"


def unlabeled_stories(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Open type:story issues carrying no model:* label.

    Exposed as a plain function (not folded into main()) so the regression
    test can plant fixture issues and prove the rule bites, per the
    check_doc_facts.py "vacuous scan" house style (#1189).
    """
    hits = []
    for issue in issues:
        names = [lbl.get("name", "") if isinstance(lbl, dict) else str(lbl) for lbl in issue.get("labels", [])]
        if not any(name.startswith("model:") for name in names):
            hits.append(issue)
    return hits


def _fetch_live_issues() -> Optional[List[Dict[str, Any]]]:
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "-R",
                REPO,
                "--label",
                "type:story",
                "--state",
                "open",
                "--json",
                "number,title,labels",
                "--limit",
                "500",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"check_story_labels: gh issue list exited {result.returncode}: {result.stderr[:300]}; skipping (advisory).")
            return None
        return json.loads(result.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"check_story_labels: could not fetch live issues via gh ({e}); skipping (advisory).")
        return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Wrap gate: every open type:story issue must carry a model:* label.")
    parser.add_argument("--issues-json", help="Offline fixture path (gh issue list --json number,title,labels output).")
    args = parser.parse_args(argv)

    if args.issues_json:
        issues = json.loads(Path(args.issues_json).read_text(encoding="utf-8"))
    else:
        issues = _fetch_live_issues()
        if issues is None:
            return 0  # fail-open: no gh/network/auth available in this context

    hits = unlabeled_stories(issues)
    if hits:
        print(f"UNLABELED type:story issues ({len(hits)}) — add exactly one model:* label (issue-filer.md's ADR-099 contract):")
        for h in hits:
            print(f"  - #{h.get('number')}: {h.get('title', '')[:100]}")
        return 1
    print(f"OK — every open type:story issue ({len(issues)}) carries a model:* label.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
