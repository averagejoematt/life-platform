#!/usr/bin/env python3
"""tests/test_claude_hooks.py — the Claude Code hook layer's safety contract.

`.claude/settings.json` had no `hooks` key at all until 2026-08-27, so every incident
class that bites BEFORE a commit exists had nothing watching it: the push that mints zero
runs, the merge past a check that had not attached, the stranded deploy lease, the deploy
from a worktree.

The tests that matter here are not "does it detect" — they are **does it stay out of the
way**. A hook runs on every matching tool call; one that can crash, hang, or wrongly
refuse is one that halts a session at the worst possible moment. So:

  * every hook exits 0 on garbage, on empty stdin, and on an unrelated command;
  * advisory mode NEVER returns 2, and block mode DOES — proving the arming switch is
    real rather than decorative (an unproven switch is the #2578 class);
  * the detectors are shown firing AND staying silent, because a detector that always
    fires is not a detector.

Subprocess-driven, with CLAUDE_HOOK_INERT=1 so nothing shells out to git or gh.
"""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOOKS = os.path.join(REPO, "scripts", "hooks")

GUARD = os.path.join(HOOKS, "guard_bash.py")
SWALLOW = os.path.join(HOOKS, "post_push_swallow.py")
PREFLIGHT = os.path.join(HOOKS, "session_preflight.py")
ALL_HOOKS = [GUARD, SWALLOW, PREFLIGHT]


def run(script, payload=None, mode="warn", raw=None):
    env = dict(os.environ, CLAUDE_HOOK_INERT="1", CLAUDE_HOOK_MODE=mode)
    stdin = raw if raw is not None else (json.dumps(payload) if payload is not None else "")
    return subprocess.run([sys.executable, script], input=stdin, capture_output=True, text=True, timeout=60, env=env, cwd=REPO)


def cmd(c):
    return {"tool_name": "Bash", "tool_input": {"command": c}}


# ── Fail open, always ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("script", ALL_HOOKS)
def test_hook_exits_zero_on_garbage_stdin(script):
    assert run(script, raw="this is not json {{{").returncode == 0


@pytest.mark.parametrize("script", ALL_HOOKS)
def test_hook_exits_zero_on_empty_stdin(script):
    assert run(script, raw="").returncode == 0


@pytest.mark.parametrize("script", ALL_HOOKS)
def test_hook_exits_zero_on_an_unrelated_command(script):
    assert run(script, cmd("ls -la")).returncode == 0


@pytest.mark.parametrize("script", ALL_HOOKS)
def test_hook_never_blocks_in_advisory_mode(script):
    """Advisory is the default posture. Nothing here may return 2 until armed."""
    for c in ("gh pr merge 1 --squash", "git push --force origin main", "bash deploy/deploy_lambda.sh x y"):
        assert run(script, cmd(c), mode="warn").returncode == 0, f"{script} blocked in advisory mode on: {c}"


# ── The detectors fire ────────────────────────────────────────────────────────
def test_merge_without_named_check_assertion_warns():
    r = run(GUARD, cmd("gh pr merge 3245 --squash"))
    assert r.returncode == 0 and "named-check assertion" in r.stderr


def test_merge_with_an_assertion_is_silent():
    """The negative control: assert_pr_green in the same command is the sanctioned path."""
    r = run(GUARD, cmd("python3 scripts/assert_pr_green.py 3245 && gh pr merge 3245 --squash"))
    assert r.returncode == 0 and r.stderr.strip() == "", f"false positive: {r.stderr}"


def test_wait_pr_green_also_counts_as_an_assertion():
    r = run(GUARD, cmd("bash deploy/wait_pr_green.sh 3245 && gh pr merge 3245 --squash"))
    assert r.stderr.strip() == ""


# ── The arming switch is real ─────────────────────────────────────────────────
def test_block_mode_actually_blocks():
    """A switch nobody has watched flip is not a switch (#2578)."""
    r = run(GUARD, cmd("gh pr merge 3245 --squash"), mode="block")
    assert r.returncode == 2, "block mode must return 2, or the advisory->blocking promotion is a no-op"


def test_block_mode_still_lets_clean_commands_through():
    assert run(GUARD, cmd("ls -la"), mode="block").returncode == 0


# ── Settings wiring ───────────────────────────────────────────────────────────
def test_settings_registers_every_hook_script_that_exists():
    """Guard the SET: a hook script on disk that no event references is dead code, and a
    registration pointing at a missing script is a hook that silently never runs."""
    with open(os.path.join(REPO, ".claude", "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    assert "hooks" in settings, "the hooks block is gone — the whole layer is dark"
    registered = json.dumps(settings["hooks"])
    on_disk = {f for f in os.listdir(HOOKS) if f.endswith(".py") and not f.startswith("_")}
    for script in on_disk:
        assert script in registered, f"scripts/hooks/{script} is registered nowhere — it never runs"
    for name in ("SessionStart", "PreToolUse", "PostToolUse"):
        assert name in settings["hooks"], f"{name} hook missing"


def test_settings_permissions_survived_the_hooks_edit():
    with open(os.path.join(REPO, ".claude", "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    assert len(settings["permissions"]["ask"]) > 80, "the ask-list was truncated by the hooks edit"
    assert len(settings["permissions"]["allow"]) > 80, "the allow-list was truncated by the hooks edit"
