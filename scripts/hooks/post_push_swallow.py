#!/usr/bin/env python3
"""scripts/hooks/post_push_swallow.py — PostToolUse: record a push, then check it late.

THE INCIDENT
  GitHub silently drops push events. Five in one night; one swallowed the WRAP commit
  itself, landing stale derived artifacts that nothing surfaced for ~7h. A guard wired on
  push cannot see a push that mints no runs — the only detection is asking, afterwards,
  whether any run exists at that sha.

WHY IT IS DEFERRED, NOT IMMEDIATE
  Runs take ~60-90s to appear, and a hook blocks the session while it runs. So this hook
  never waits: it RECORDS the sha, and on any later invocation checks the ones that are
  now old enough. The check drains itself, costs nothing when there is nothing pending,
  and reports at the next natural pause.

THE CONFOUND, HANDLED
  A `GITHUB_TOKEN` push (the reconcile bot) legitimately mints zero runs AND touches
  lambdas/**, so it looks identical to a swallow. Any zero-run detector without that
  discriminator pages after every merge and gets ignored. This one only records pushes
  made from an interactive session, and reports "unverified" rather than "swallowed" when
  it cannot tell — absence of proof is stated as such, never upgraded to proof of absence.
"""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import bash_command, emit, gh, git, ok, read_payload, state_path  # noqa: E402

_PUSH = re.compile(r"\bgit\s+push\b")
SETTLE_SECONDS = 90
STATE = "pending_pushes.json"


def _load() -> list[dict]:
    try:
        return json.loads(state_path(STATE).read_text())
    except Exception:
        return []


def _save(rows: list[dict]) -> None:
    try:
        state_path(STATE).write_text(json.dumps(rows))
    except Exception:
        pass


def main() -> int:
    now = time.time()
    rows = _load()

    if _PUSH.search(bash_command(read_payload())):
        code, sha = git("rev-parse", "HEAD")
        if code == 0 and len(sha) == 40 and not any(r.get("sha") == sha for r in rows):
            rows.append({"sha": sha, "at": now})

    due, pending, findings = [r for r in rows if now - r.get("at", 0) >= SETTLE_SECONDS], [], []
    pending = [r for r in rows if now - r.get("at", 0) < SETTLE_SECONDS]

    for r in due:
        sha = r["sha"]
        # The FULL 40-char sha: a short sha misses `pull_request` runs (#3103).
        code, out = gh("api", f"repos/averagejoematt/life-platform/actions/runs?head_sha={sha}", "--jq", ".total_count")
        if code != 0 or not out.isdigit():
            findings.append(f"{sha[:12]}: UNVERIFIED — could not query runs (absence of proof, not proof of absence)")
        elif int(out) == 0:
            findings.append(f"{sha[:12]}: ZERO runs {int(now - r['at'])}s after push — treat as SWALLOWED")
            findings.append("  recovery ladder: close/reopen the PR -> supersede-PR -> integration train")
        # A nonzero count is the healthy case and says nothing.

    _save(pending)
    if findings:
        return emit("push event check", findings)
    return ok()


if __name__ == "__main__":
    sys.exit(main())
