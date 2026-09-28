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

#4260 — HEARD, NOT JUST PRINTED. Until #4260 every finding went to stderr on exit 0, which
the Claude Code hook contract routes to the debug log for PreToolUse/PostToolUse: the
model never read one. `assert_heard` below encodes the contract (code.claude.com/docs/en/
hooks, read 2026-09-27) and the session-boot test drives every handler registered in
`.claude/settings.json` exactly as the harness does — the real command string, the real
event payload on stdin — and asserts the output reaches the model. Its negative control
runs the pre-#4260 emit shape through the same assertion and requires it to FAIL.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOOKS = os.path.join(REPO, "scripts", "hooks")

GUARD = os.path.join(HOOKS, "guard_bash.py")
SWALLOW = os.path.join(HOOKS, "post_push_swallow.py")
PREFLIGHT = os.path.join(HOOKS, "session_preflight.py")
ALL_HOOKS = [GUARD, SWALLOW, PREFLIGHT]


def run(script, payload=None, mode="warn", raw=None, state=None):
    """`state`: the hook state dir. Always a tmp dir — a test must never write the real .git."""
    env = dict(os.environ, CLAUDE_HOOK_INERT="1", CLAUDE_HOOK_MODE=mode, CLAUDE_HOOK_STATE_DIR=state or tempfile.mkdtemp())
    stdin = raw if raw is not None else (json.dumps(payload) if payload is not None else "")
    return subprocess.run([sys.executable, script], input=stdin, capture_output=True, text=True, timeout=60, env=env, cwd=REPO)


def cmd(c, event="PreToolUse"):
    """The payload shape the harness sends a Bash tool hook (common fields + tool fields)."""
    return {
        "session_id": "test-4260",
        "transcript_path": "/tmp/test-4260.jsonl",
        "cwd": REPO,
        "permission_mode": "default",
        "hook_event_name": event,
        "tool_name": "Bash",
        "tool_input": {"command": c, "description": "test"},
        "tool_use_id": "toolu_test4260",
    }


def hook_json(r):
    """The harness parses stdout as JSON only when it starts with `{` and ends with `}`."""
    out = r.stdout.strip()
    if not (out.startswith("{") and out.endswith("}")):
        return None
    return json.loads(out)


def assert_heard(event, r, decision=None):
    """The contract for a FINDING to reach the model (#4260). Raises AssertionError if not.

    PreToolUse/PostToolUse: exit 0 + a JSON object whose hookSpecificOutput names the event
    and carries non-empty additionalContext (stderr on exit 0 is debug-log only).
    SessionStart: exit 0 + non-empty plain stdout (added to context as-is)."""
    assert r.returncode == 0, f"{event}: exit {r.returncode} — exit 2 blocks, other codes are a hook error"
    if event == "SessionStart":
        assert r.stdout.strip(), "SessionStart printed nothing on stdout — nothing reaches context"
        return None
    j = hook_json(r)
    assert j is not None, f"{event}: stdout is not a JSON object — the model hears nothing (stdout={r.stdout!r})"
    spec = j.get("hookSpecificOutput") or {}
    assert spec.get("hookEventName") == event, spec
    assert str(spec.get("additionalContext", "")).startswith("[claude-hook:"), spec
    assert spec.get("permissionDecision") == decision, f"expected decision {decision!r}, got {spec.get('permissionDecision')!r}"
    return spec


def assert_silent(r):
    assert r.returncode == 0 and r.stdout.strip() == "", f"false positive: {r.stdout!r} {r.stderr!r}"


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
        r = run(script, cmd(c), mode="warn")
        assert r.returncode == 0, f"{script} blocked in advisory mode on: {c}"
        spec = (hook_json(r) or {}).get("hookSpecificOutput") or {}
        assert "permissionDecision" not in spec, f"{script} asked/denied in advisory mode on: {c}"


# ── The detectors fire — and are HEARD ─────────────────────────────────────────
def test_merge_without_named_check_assertion_warns():
    r = run(GUARD, cmd("gh pr merge 3245 --squash"))
    spec = assert_heard("PreToolUse", r)
    assert "named-check assertion" in spec["additionalContext"]
    assert "named-check assertion" in json.loads(r.stdout)["systemMessage"], "the operator is told too"


def test_merge_after_a_separate_watcher_is_silent():
    """The negative control (#4260): the watcher in its OWN earlier command, then the merge."""
    state = tempfile.mkdtemp()
    assert_silent(run(GUARD, cmd("python3 scripts/assert_pr_green.py 3245"), state=state))
    assert_silent(run(GUARD, cmd("gh pr merge 3245 --squash"), state=state))


def test_wait_pr_green_also_counts_as_an_assertion():
    state = tempfile.mkdtemp()
    assert_silent(run(GUARD, cmd("bash deploy/wait_pr_green.sh 3245"), state=state))
    assert_silent(run(GUARD, cmd("gh pr merge 3245 --squash"), state=state))


def test_a_watcher_for_a_different_pr_does_not_cover_the_merge():
    state = tempfile.mkdtemp()
    run(GUARD, cmd("bash deploy/wait_pr_green.sh 1111"), state=state)
    spec = assert_heard("PreToolUse", run(GUARD, cmd("gh pr merge 3245 --squash"), state=state))
    assert "PR 3245" in spec["additionalContext"]


def test_a_stale_watcher_does_not_cover_the_merge():
    state = tempfile.mkdtemp()
    with open(os.path.join(state, "watchers.json"), "w") as f:
        json.dump([{"pr": "3245", "at": time.time() - 2 * 3600}], f)
    assert_heard("PreToolUse", run(GUARD, cmd("gh pr merge 3245 --squash"), state=state))


def test_a_bare_gh_pr_checks_is_not_a_watcher():
    """`gh pr checks N` (the fail-filter idiom) must not arm the merge."""
    state = tempfile.mkdtemp()
    run(GUARD, cmd("gh pr checks 3245 | grep -c fail"), state=state)
    assert_heard("PreToolUse", run(GUARD, cmd("gh pr merge 3245 --squash"), state=state))


@pytest.mark.parametrize(
    "chained",
    [
        "python3 scripts/assert_pr_green.py 3245 && gh pr merge 3245 --squash",
        "bash deploy/wait_pr_green.sh 3245; gh pr merge 3245 --squash",
    ],
)
def test_the_chained_watcher_and_merge_is_a_finding(chained):
    """wait_pr_green.sh:20-23 — the chained form merged past an unread NONGREEN twice."""
    spec = assert_heard("PreToolUse", run(GUARD, cmd(chained)))
    assert "chained into the merge" in spec["additionalContext"]


def test_two_findings_in_one_command_are_one_json_object():
    """The harness parses ONE object — two prints would be plain text, i.e. unheard."""
    r = run(GUARD, cmd("gh pr merge 3245 --squash --body 'x'"))
    spec = assert_heard("PreToolUse", r)
    assert "named-check assertion" in spec["additionalContext"] and "no guard has validated" in spec["additionalContext"]


def test_push_check_is_heard_as_post_tool_use_context():
    state = tempfile.mkdtemp()
    with open(os.path.join(state, "pending_pushes.json"), "w") as f:
        json.dump([{"sha": "a" * 40, "at": time.time() - 600}], f)  # due; INERT -> gh cannot answer
    spec = assert_heard("PostToolUse", run(SWALLOW, cmd("git push origin HEAD", "PostToolUse"), state=state))
    assert "UNVERIFIED" in spec["additionalContext"]


def test_push_check_touches_no_state_on_a_non_push():
    """#4260 box 4: the state file is read only on a push — a due row must NOT drain on `ls`."""
    state = tempfile.mkdtemp()
    path = os.path.join(state, "pending_pushes.json")
    with open(path, "w") as f:
        json.dump([{"sha": "a" * 40, "at": time.time() - 600}], f)
    assert_silent(run(SWALLOW, cmd("ls -la", "PostToolUse"), state=state))
    assert json.load(open(path))[0]["sha"] == "a" * 40


# ── The arming switch is real ─────────────────────────────────────────────────
def test_block_mode_actually_blocks():
    """A switch nobody has watched flip is not a switch (#2578). #4260: a JSON "deny" — its
    reason is shown to the model, unlike stderr on exit 0."""
    r = run(GUARD, cmd("gh pr merge 3245 --squash"), mode="block")
    spec = assert_heard("PreToolUse", r, decision="deny")
    assert "named-check assertion" in spec["permissionDecisionReason"]


def test_ask_mode_asks():
    assert_heard("PreToolUse", run(GUARD, cmd("gh pr merge 3245 --squash"), mode="ask"), decision="ask")


def test_block_mode_still_lets_clean_commands_through():
    assert_silent(run(GUARD, cmd("ls -la"), mode="block"))


# ── The session-boot test: every registered handler, driven as the harness drives it ──
_TRIGGERS = {
    # event -> a command that must produce a finding under INERT (no git/gh), per `if` rule
    "PreToolUse": "gh pr merge 4260 --squash",
    "PostToolUse": {"Bash(git push *)": "git push origin HEAD", "Bash(git -C *)": "git -C . push origin HEAD"},
}


def _handlers():
    with open(os.path.join(REPO, ".claude", "settings.json"), encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    for event, groups in hooks.items():
        for g in groups:
            for h in g["hooks"]:
                yield event, g.get("matcher"), h


def _drive(event, handler, payload, state):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=REPO, CLAUDE_HOOK_INERT="1", CLAUDE_HOOK_STATE_DIR=state)
    env.pop("CLAUDE_HOOK_MODE", None)  # the shipped default, exactly as a session gets it
    # The harness hands the command string to a shell ($CLAUDE_PROJECT_DIR expands there).
    return subprocess.run(
        ["/bin/sh", "-c", handler["command"]],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=handler.get("timeout", 60),
        env=env,
        cwd=REPO,
    )


def _if_matches(rule, command):
    """A local model of the `if` rule for the triggers above: `Bash(<prefix> *)`."""
    m = re.fullmatch(r"Bash\((.+?)(?: \*)?\)", rule)
    return bool(m) and (command == m.group(1) or command.startswith(m.group(1) + " "))


@pytest.mark.parametrize("event,matcher,handler", list(_handlers()), ids=lambda v: v if isinstance(v, str) else None)
def test_session_boot_every_registered_hook_is_heard(event, matcher, handler):
    state = tempfile.mkdtemp()
    if event == "SessionStart":
        payload = {
            "session_id": "boot-4260",
            "transcript_path": "/tmp/boot.jsonl",
            "cwd": REPO,
            "hook_event_name": "SessionStart",
            "source": "startup",
            "model": "test",
        }
        assert_heard("SessionStart", _drive(event, handler, payload, state))
        return
    assert matcher == "Bash", f"{event} handler with matcher {matcher!r} — the triggers below only model Bash"
    trig = _TRIGGERS[event]
    command = trig[handler["if"]] if isinstance(trig, dict) else trig
    if "if" in handler:
        assert _if_matches(handler["if"], command), f"trigger {command!r} does not satisfy the handler's own if {handler['if']!r}"
    if event == "PostToolUse":  # a due row, so the push check has something to report
        with open(os.path.join(state, "pending_pushes.json"), "w") as f:
            json.dump([{"sha": "b" * 40, "at": time.time() - 600}], f)
    payload = cmd(command, event)
    if event == "PostToolUse":
        payload["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False, "isImage": False}
    assert_heard(event, _drive(event, handler, payload, state))


def test_session_boot_negative_control_the_pre_4260_shape_is_unheard(tmp_path):
    """Mutation control for `assert_heard` itself: the old emit (stderr + exit 0) and the old
    block (stderr + exit 2) must both FAIL the contract, or the boot test proves nothing."""
    legacy = tmp_path / "legacy_hook.py"
    legacy.write_text(
        "import os, sys\n"
        "print('[claude-hook: merge without a named-check assertion] (advisory)', file=sys.stderr)\n"
        "sys.exit(2 if os.environ.get('CLAUDE_HOOK_MODE') == 'block' else 0)\n"
    )
    for mode in ("warn", "block"):
        env = dict(os.environ, CLAUDE_HOOK_MODE=mode)
        r = subprocess.run([sys.executable, str(legacy)], input=json.dumps(cmd("gh pr merge 1")), capture_output=True, text=True, env=env)
        with pytest.raises(AssertionError):
            assert_heard("PreToolUse", r, decision="deny" if mode == "block" else None)


def test_post_push_swallow_is_narrowed_to_git_push_in_settings():
    """#4260 box 4: the push hook must not spawn on every Bash call."""
    handlers = [h for e, _m, h in _handlers() if "post_push_swallow" in h["command"]]
    assert handlers and all(h.get("if", "").startswith("Bash(git ") for h in handlers), handlers


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
