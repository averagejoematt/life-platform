#!/usr/bin/env python3
"""scripts/hooks/_hooklib.py — shared plumbing for the Claude Code hook layer.

WHY A HOOK LAYER AT ALL
  Until 2026-08-27 `.claude/settings.json` had no `hooks` key. Every piece of enforcement
  in this repo lived in git hooks, which run at COMMIT time — so the whole family of
  incidents that bite before a commit exists had nothing watching:

    * a push that mints zero runs (5 in one night; one reached a wrap commit and landed
      stale derived artifacts nobody saw for ~7h);
    * merging past a check that had not ATTACHED yet — `gh pr checks` returning an empty
      rollup passes a naive fail-filter, which merged a PR with a red pre-merge lane;
    * a production deploy lease left waiting (found EVERY session: 16.4h, 15.5h, 7.5h —
      and in three of them approving it would have rolled back live-deployed fixes);
    * deploying from a worktree branch, whose tell is a deceptive 0-diff.

THE POSTURE: ADVISORY FIRST
  Every hook here WARNS and exits 0. Nothing refuses a tool call until an operator flips
  `HOOK_MODE` to "block", the same arming discipline this repo uses for its CI gates
  (#390/ADR-108: measure on real traffic first, then flip). A hook that blocks on day one
  is a hook that wedges a session at the worst moment and gets deleted.

FAIL OPEN, ALWAYS
  Any exception, any unparseable payload, any missing tool — exit 0 silently. A hook runs
  on EVERY matching tool call; one that can crash is one that can halt a session. The
  cost of a missed warning is a warning. The cost of a false block is the session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

#: "warn" (default) or "block". Only an operator flips this, never a code path.
HOOK_MODE = os.environ.get("CLAUDE_HOOK_MODE", "warn")

#: Set by the test suite so hooks never shell out to git/gh during pytest.
INERT = os.environ.get("CLAUDE_HOOK_INERT") == "1"


def read_payload() -> dict:
    """The hook's stdin JSON, or {} for anything unparseable. Never raises."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def bash_command(payload: dict) -> str:
    try:
        return str(payload.get("tool_input", {}).get("command", "") or "")
    except Exception:
        return ""


def git(*args: str, cwd: Path | None = None, timeout: int = 15) -> tuple[int, str]:
    if INERT:
        return 1, ""
    try:
        r = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except Exception:
        return 1, ""


def gh(*args: str, timeout: int = 25) -> tuple[int, str]:
    if INERT:
        return 1, ""
    try:
        r = subprocess.run(["gh", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except Exception:
        return 1, ""


def _git_state_root() -> Path:
    """The real, already-existing git directory to nest hook state under.

    `ROOT / ".git"` is a git FILE (a `gitdir:` pointer), not a directory, inside a
    worktree — `mkdir` on it raises `NotADirectoryError` (measured, #3262). `git
    rev-parse --git-dir` resolves to the directory that actually exists in both cases:
    `.git` in the main checkout, `<main>/.git/worktrees/<name>` inside a worktree — git
    creates that directory itself when the worktree is added, so nesting state under it
    never needs to create a new top-level path.
    """
    code, gitdir = git("rev-parse", "--git-dir")
    if code == 0 and gitdir:
        p = Path(gitdir)
        return p if p.is_absolute() else ROOT / p
    # INERT (pytest) or git unavailable: same default the code always used.
    return ROOT / ".git"


#: Resolved once per process. Worktree-aware (see `_git_state_root`).
STATE_DIR = _git_state_root() / "claude-hooks"


def state_path(name: str) -> Path:
    """Raises on failure — callers that must not crash a hook catch this themselves and
    report it (see `post_push_swallow._load`/`_save`) rather than have it swallowed here."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / name


def emit(title: str, lines: list[str]) -> int:
    """Report a finding. Exit 2 blocks the call; exit 0 is advisory.

    The message goes to stderr in BOTH modes so the session always sees it — the
    difference is only whether the tool call proceeds.
    """
    body = "\n".join(f"  {ln}" for ln in lines)
    mode = "BLOCKED" if HOOK_MODE == "block" else "advisory"
    print(f"[claude-hook: {title}] ({mode})\n{body}", file=sys.stderr)
    return 2 if HOOK_MODE == "block" else 0


def ok() -> int:
    return 0
