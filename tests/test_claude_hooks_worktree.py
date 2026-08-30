#!/usr/bin/env python3
"""tests/test_claude_hooks_worktree.py — the hook layer in a REAL worktree (#3262).

`tests/test_claude_hooks.py` runs every hook with `CLAUDE_HOOK_INERT=1`, which makes
`_hooklib.git()` short-circuit to `(1, "")` before it ever shells out — so neither of
the two worktree-specific defects this issue fixes could ever have been exercised by
that suite, INERT or not:

  C1 — `guard_bash.py`'s deploy-from-a-worktree detector compared `--git-common-dir`
       (which resolves to the MAIN checkout's `.git` even when run FROM a worktree) to
       `.../.git`, so the condition was false everywhere. Fix: compare `--git-dir`
       instead, which is the one that actually differs.
  C2 — `_hooklib.state_path()` nested state under `ROOT / ".git"`. Inside a worktree
       `<root>/.git` is a FILE (a `gitdir:` pointer), not a directory, so `mkdir` raised
       `NotADirectoryError` — caught and swallowed by `post_push_swallow.py`'s `_load`/
       `_save`, so the deferred swallow-check silently never ran. Fix: nest state under
       `git rev-parse --git-dir` instead, which is a real, already-existing directory in
       both the main checkout and a worktree.

These tests synthesize a REAL worktree with `git worktree add` (a temp repo fixture,
per the issue) and run the hook scripts as real subprocesses with `CLAUDE_HOOK_INERT`
UNSET, so git is actually shelled out to — the exact condition that hid both defects.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOOKS = os.path.join(REPO, "scripts", "hooks")
HOOK_FILES = ["_hooklib.py", "guard_bash.py", "post_push_swallow.py"]

_GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="hook-test",
    GIT_AUTHOR_EMAIL="hook-test@example.com",
    GIT_COMMITTER_NAME="hook-test",
    GIT_COMMITTER_EMAIL="hook-test@example.com",
)


def _git(*args: str, cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30, env=_GIT_ENV)
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout.strip()


def _make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A synthetic repo with a real `git worktree add` layout — the exact shape #3262
    measured, reproduced from scratch rather than mocked."""
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=main, check=True, env=_GIT_ENV)

    hooks_dir = main / "scripts" / "hooks"
    hooks_dir.mkdir(parents=True)
    for f in HOOK_FILES:
        shutil.copy(os.path.join(HOOKS, f), hooks_dir / f)

    subprocess.run(["git", "add", "-A"], cwd=main, check=True, env=_GIT_ENV)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=main, check=True, env=_GIT_ENV)

    worktree = tmp_path / "worktree"
    subprocess.run(["git", "worktree", "add", "-q", str(worktree), "-b", "lane", "main"], cwd=main, check=True, env=_GIT_ENV)
    return main, worktree


def _run(script: str, payload: dict, cwd: Path, mode: str = "warn") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("CLAUDE_HOOK_INERT", None)  # the whole point: git must actually run
    env["CLAUDE_HOOK_MODE"] = mode
    return subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
        env=env,
    )


def _real_gitdir(cwd: Path) -> Path:
    gitdir = _git("rev-parse", "--git-dir", cwd=cwd)
    p = Path(gitdir)
    return p if p.is_absolute() else cwd / p


# ── Negative control: the fixture actually reproduces the defect shape ─────────────
def test_fixture_worktree_git_is_a_file_not_a_directory(tmp_path):
    """If this fails, the fixture below is not exercising the #3262 shape at all —
    `<root>/.git` must be a FILE inside the worktree, which is what broke `mkdir`."""
    _main, worktree = _make_fixture(tmp_path)
    assert (worktree / ".git").is_file()
    assert not (worktree / ".git").is_dir()


# ── C1: guard_bash's deploy detector must fire from inside a real worktree ─────────
def test_guard_bash_deploy_detector_fires_in_a_real_worktree(tmp_path):
    _main, worktree = _make_fixture(tmp_path)
    script = str(worktree / "scripts" / "hooks" / "guard_bash.py")
    r = _run(script, {"tool_name": "Bash", "tool_input": {"command": "bash deploy/deploy_lambda.sh x y"}}, cwd=worktree)
    assert r.returncode == 0, r.stderr  # advisory mode never blocks
    assert "deploy from a worktree" in r.stderr, f"detector did not fire; stderr={r.stderr!r}"


def test_guard_bash_deploy_detector_silent_in_the_main_checkout(tmp_path):
    """Positive control for the detector itself: the main checkout is not a worktree."""
    main, _worktree = _make_fixture(tmp_path)
    script = str(main / "scripts" / "hooks" / "guard_bash.py")
    r = _run(script, {"tool_name": "Bash", "tool_input": {"command": "bash deploy/deploy_lambda.sh x y"}}, cwd=main)
    assert r.returncode == 0, r.stderr
    assert "deploy from a worktree" not in r.stderr, f"false positive in the main checkout: {r.stderr!r}"


# ── C2: hook state must resolve, write, and read back inside a real worktree ───────
def test_post_push_swallow_records_and_reads_back_a_push_in_a_real_worktree(tmp_path):
    _main, worktree = _make_fixture(tmp_path)
    script = str(worktree / "scripts" / "hooks" / "post_push_swallow.py")
    sha = _git("rev-parse", "HEAD", cwd=worktree)

    r = _run(script, {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD"}}, cwd=worktree)
    assert r.returncode == 0, r.stderr
    assert "UNVERIFIED" not in r.stderr, f"state write failed where it should have succeeded: {r.stderr!r}"

    state_file = _real_gitdir(worktree) / "claude-hooks" / "pending_pushes.json"
    assert state_file.exists(), "hook state was never written — state_path() failed silently (the #3262 bug)"
    rows = json.loads(state_file.read_text())
    assert any(row.get("sha") == sha for row in rows), rows

    # Read-back: a second invocation must load the existing file without erroring, and
    # the recorded row must survive the load+save round trip.
    r2 = _run(script, {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}, cwd=worktree)
    assert r2.returncode == 0, r2.stderr
    assert "UNVERIFIED" not in r2.stderr, f"read-back failed: {r2.stderr!r}"
    rows2 = json.loads(state_file.read_text())
    assert any(row.get("sha") == sha for row in rows2), "recorded push did not survive a load+save round trip"


# ── The module's own contract: an unwritable state dir reports, never swallows ─────
def test_post_push_swallow_reports_unverified_when_state_dir_is_unwritable(tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("running as root: directory permissions do not block writes")

    _main, worktree = _make_fixture(tmp_path)
    script = str(worktree / "scripts" / "hooks" / "post_push_swallow.py")
    gitdir = _real_gitdir(worktree)
    gitdir.chmod(0o500)  # r-x: mkdir of a new child ("claude-hooks") must fail
    try:
        r = _run(script, {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD"}}, cwd=worktree)
        assert r.returncode == 0, r.stderr  # advisory mode: fail open, never blocks
        assert "UNVERIFIED" in r.stderr, f"a write failure was swallowed into silence: {r.stderr!r}"
        assert "could not write hook state" in r.stderr, r.stderr
    finally:
        gitdir.chmod(0o700)
