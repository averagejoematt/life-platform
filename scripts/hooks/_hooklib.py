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

THE POSTURE: ADVISORY FIRST — BUT HEARD (#4260)
  Every hook here WARNS by default. Nothing refuses a tool call until an operator sets
  `CLAUDE_HOOK_MODE`, the same arming discipline this repo uses for its CI gates
  (#390/ADR-108: measure on real traffic first, then flip). A hook that blocks on day one
  is a hook that wedges a session at the worst moment and gets deleted.

  "Warn" has to mean the MODEL reads it. Until #4260 `emit()` printed to stderr and exited
  0 — and under the Claude Code hook contract stderr on exit 0 from PreToolUse/PostToolUse
  goes to the debug log only, so every finding this layer ever produced was advisory to
  nobody. The contract (code.claude.com/docs/en/hooks, read 2026-09-27, CLI 2.1.283):
    * exit 0 + a JSON object on stdout is parsed; `hookSpecificOutput.additionalContext`
      is wrapped in a system reminder next to the tool result — the model reads it;
    * top-level `systemMessage` is a warning shown to the USER;
    * PreToolUse `permissionDecision` "ask" prompts the user (reason shown to the user,
      not the model); "deny" refuses the call (reason shown to the model);
    * SessionStart plain stdout on exit 0 is already added to the model's context.
  So `emit()` now prints one JSON object on stdout, per event, and exits 0 in every mode:

    CLAUDE_HOOK_MODE  PreToolUse                                 PostToolUse
    warn (default)    additionalContext + systemMessage          additionalContext + systemMessage
    ask               permissionDecision "ask" + the above        (same as warn — nothing to ask)
    block             permissionDecision "deny" + reason          decision "block" + reason

  "ask" is deliberately NOT the default: a hook "ask" forces a permission prompt even in
  auto mode, and an unattended lane parked on a prompt has frozen this repo's sessions for
  6-9 hours (reference_a_parent_turn_can_stall_while_its_children_finish). Warn keeps the
  advisory posture and makes it audible; ask/block are the operator's arming steps.

FAIL OPEN, ALWAYS
  Any exception, any unparseable payload, any missing tool — exit 0 silently. A hook runs
  on EVERY matching tool call; one that can crash is one that can halt a session. The
  cost of a missed warning is a warning. The cost of a false block is the session.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

#: "warn" (default), "ask" or "block". Only an operator flips this, never a code path.
HOOK_MODE = os.environ.get("CLAUDE_HOOK_MODE", "warn")

#: Set by the test suite so hooks never shell out to git/gh during pytest.
INERT = os.environ.get("CLAUDE_HOOK_INERT") == "1"

#: The directory the tool call runs in: the payload's `cwd` (set by `read_payload`), else
#: the hook process's own cwd. NOT `ROOT` — `ROOT` is the checkout the hook SCRIPT lives
#: in (the session's project dir), and a lane's push/deploy runs in its worktree (#4260).
CWD: Path | None = None


def read_payload() -> dict:
    """The hook's stdin JSON, or {} for anything unparseable. Never raises. Records the
    payload's `cwd` so `git()` runs where the tool call runs."""
    global CWD
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return {}
    except Exception:
        return {}
    try:
        c = payload.get("cwd")
        if isinstance(c, str) and c and Path(c).is_dir():
            CWD = Path(c)
    except Exception:
        pass
    return payload


def bash_command(payload: dict) -> str:
    try:
        return str(payload.get("tool_input", {}).get("command", "") or "")
    except Exception:
        return ""


_CD = re.compile(r"(?:^|[;&|(]\s*|\s&&\s*)cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|)]+)")
_GIT_C = re.compile(r"\bgit\s+-C\s+(\"[^\"]+\"|'[^']+'|[^\s;&|)]+)")


def command_cwd(cmd: str, upto: int | None = None, git_c: bool = True) -> Path | None:
    """Where the part of `cmd` before offset `upto` runs: the last `cd <dir>` (or `git -C
    <dir>`) ahead of it, resolved against the payload cwd. None = no override, use CWD.

    Sessions reset cwd between Bash calls, so a lane pushes/deploys with `cd <worktree> &&
    ...` or `git -C <worktree> ...` — the payload cwd alone names the session's checkout,
    not the lane's (#4260)."""
    head = cmd if upto is None else cmd[:upto]
    hits = [(m.start(), m.group(1)) for m in _CD.finditer(head)]
    if git_c:  # `git -C` scopes only that git call — right for a push, wrong for a deploy script
        hits += [(m.start(), m.group(1)) for m in _GIT_C.finditer(head)]
    if not hits:
        return None
    raw = max(hits)[1].strip("\"'")
    try:
        p = Path(os.path.expanduser(raw))
        if not p.is_absolute():
            p = (CWD or Path.cwd()) / p
        return p if p.is_dir() else None
    except Exception:
        return None


def git(*args: str, cwd: Path | None = None, timeout: int = 15) -> tuple[int, str]:
    """Runs in `cwd`, else the payload's cwd, else the process cwd — never ROOT by default."""
    if INERT:
        return 1, ""
    try:
        r = subprocess.run(["git", *args], cwd=cwd or CWD or None, capture_output=True, text=True, timeout=timeout)
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
    never needs to create a new top-level path. State is keyed to ROOT (the session's
    checkout), deliberately NOT the payload cwd: it must survive the session's `cd`s.
    """
    code, gitdir = git("rev-parse", "--git-dir", cwd=ROOT)
    if code == 0 and gitdir:
        p = Path(gitdir)
        return p if p.is_absolute() else ROOT / p
    # INERT (pytest) or git unavailable: same default the code always used.
    return ROOT / ".git"


_STATE_DIR: Path | None = None


def state_dir() -> Path:
    """Resolved lazily, once per process — a hook with nothing to record never pays the
    `git rev-parse` (it used to run at import, on every Bash call, #4260)."""
    global _STATE_DIR
    if _STATE_DIR is None:
        override = os.environ.get("CLAUDE_HOOK_STATE_DIR")  # tests only: a tmp dir, never the real .git
        _STATE_DIR = Path(override) if override else _git_state_root() / "claude-hooks"
    return _STATE_DIR


def state_path(name: str) -> Path:
    """Raises on failure — callers that must not crash a hook catch this themselves and
    report it (see `post_push_swallow._load`/`_save`) rather than have it swallowed here."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def render(title: str, lines: list[str]) -> str:
    body = "\n".join(f"  {ln}" for ln in lines)
    return f"[claude-hook: {title}] ({HOOK_MODE if HOOK_MODE in ('ask', 'block') else 'advisory'})\n{body}"


def output(event: str, text: str, mode: str | None = None) -> dict:
    """The JSON object the harness reads for `event` in `mode` — see the table above."""
    mode = mode or HOOK_MODE
    spec: dict = {"hookEventName": event, "additionalContext": text}
    out: dict = {"systemMessage": text, "hookSpecificOutput": spec}
    if event == "PreToolUse" and mode == "block":
        spec["permissionDecision"] = "deny"
        spec["permissionDecisionReason"] = text
    elif event == "PreToolUse" and mode == "ask":
        spec["permissionDecision"] = "ask"
        spec["permissionDecisionReason"] = text
    elif event == "PostToolUse" and mode == "block":
        out["decision"] = "block"
        out["reason"] = text
    return out


def emit(title: str, lines: list[str], event: str = "PreToolUse") -> int:
    """Report a finding where the MODEL reads it: one JSON object on stdout, exit 0.

    The mode only changes whether the call is asked about or refused (see the table in the
    module docstring). A copy also goes to stderr for anyone running the hook by hand."""
    text = render(title, lines)
    print(json.dumps(output(event, text)))
    print(text, file=sys.stderr)
    return 0


def ok() -> int:
    return 0
