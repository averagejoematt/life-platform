"""tests/test_wait_pr_green.py — #3103: the one blessed PR-check watcher must never lie.

The 2026-08-23/24 session hand-rolled ~12 ad-hoc PR-check watchers and hit every
failure mode this test file exists to structurally forbid:

  1. a short-sha `actions/runs?head_sha=` query silently returning EMPTY (exits
     instantly, reads as done) — `deploy/wait_pr_green.sh` never constructs that
     query at all; it delegates to `gh pr checks`, which gh itself scopes correctly,
     and independently resolves the PR's head via the full 40-char sha before
     comparing anything.
  2. "no checks reported" read as done — MUST be a failure, never a pass.
  3. an EXPECTED check that never attaches is invisible to a naive fail-filter —
     the mutation proof below: an absent expected check in the fixture exits
     nonzero even when every check that DID report is green.
  4. reading the verdict and merging in the same command — structurally impossible
     here, because this script contains no `gh pr merge` call at all (asserted
     below by a static sweep, not just by reading the code once).

Fixture mode (`--fixture FILE`) makes the evaluator testable with ZERO network and
ZERO `gh` calls — every test below runs the real script as a subprocess, under real
bash, against static JSON fixtures shaped exactly like `gh pr checks --json
name,state,bucket` output. Several tests additionally shadow `gh` with a PATH stub
that hard-fails if invoked, proving fixture mode never shells out.
"""

import json
import os
import stat
import subprocess
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO, "deploy", "wait_pr_green.sh")

_BASELINE = [
    "Collect + deploy-critical + format",
    # #3117: renamed off the `#`-comment-truncated wire name (`Full unit suite
    # (pre-merge,` — see the script's own BASELINE_CHECKS comment for the incident).
    "Full unit suite (pre-merge, issue 3025)",
    "API-before-frontend sequencing check (#2831)",
    "gitleaks (PR commit range only, not full history)",
    "CodeQL analysis (python)",
    "CodeQL analysis (javascript-typescript)",
]


def _check(name, state, bucket):
    return {"name": name, "state": state, "bucket": bucket}


def _all_green_checks(extra=None):
    checks = [_check(n, "SUCCESS", "pass") for n in _BASELINE]
    if extra:
        checks.extend(extra)
    return checks


def _write_fixture(checks):
    fd, path = tempfile.mkstemp(suffix=".json", dir=tempfile.gettempdir())
    with os.fdopen(fd, "w") as f:
        json.dump(checks, f)
    return path


def _no_gh_path():
    """A PATH with a `gh` stub that hard-fails loudly if ever invoked — proves
    fixture mode makes zero network/`gh` calls, not merely that the tests didn't
    happen to trigger one."""
    stub_dir = tempfile.mkdtemp()
    stub = os.path.join(stub_dir, "gh")
    with open(stub, "w") as f:
        f.write('#!/usr/bin/env bash\necho "GH_WAS_CALLED $*" >&2\nexit 97\n')
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # Keep real PATH for bash/jq/etc, just make our stub win for `gh`.
    return stub_dir + os.pathsep + os.environ.get("PATH", "")


def _run(args, path_override=None):
    env = dict(os.environ)
    if path_override:
        env["PATH"] = path_override
    return subprocess.run(
        ["bash", _SCRIPT] + args,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


# ── the mutation proof (#3103's explicit acceptance criterion) ────────────────


def test_absent_expected_check_exits_nonzero_even_when_everything_seen_is_green():
    # Every check that DID report is green; one baseline name never showed up.
    checks = [_check(n, "SUCCESS", "pass") for n in _BASELINE if n != "CodeQL analysis (python)"]
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive"], path_override=_no_gh_path())
    assert p.returncode != 0, p.stdout + p.stderr
    assert "NONGREEN CodeQL analysis (python) ABSENT" in p.stdout, p.stdout
    assert "GH_WAS_CALLED" not in p.stderr, "fixture mode must never shell out to gh"


# ── the other three named failure modes ────────────────────────────────────────


def test_all_green_exits_zero():
    path = _write_fixture(_all_green_checks())
    p = _run(["--fixture", path, "--no-derive"], path_override=_no_gh_path())
    assert p.returncode == 0, p.stdout + p.stderr
    assert "VERDICT SUCCESS" in p.stdout


def test_empty_checks_array_is_a_failure_never_a_pass():
    path = _write_fixture([])
    p = _run(["--fixture", path, "--no-derive"], path_override=_no_gh_path())
    assert p.returncode != 0, "an empty check list must never read as done (the swallowed-push class)"
    assert "swallowed push" in (p.stdout + p.stderr).lower()


def test_a_single_failed_check_fails_the_whole_set():
    checks = _all_green_checks()
    checks[0]["state"] = "FAILURE"
    checks[0]["bucket"] = "fail"
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive"], path_override=_no_gh_path())
    assert p.returncode != 0
    assert "NONGREEN Collect + deploy-critical + format FAILURE" in p.stdout, p.stdout
    assert "VERDICT FAIL" in p.stdout


def test_waiting_check_reported_distinctly_not_green_not_plain_fail():
    checks = _all_green_checks(extra=[_check("Deploy", "WAITING", "pending")])
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive", "--expect", "Deploy"], path_override=_no_gh_path())
    assert p.returncode == 2, "a WAITING gate is its own exit code — a human disposes leases"
    assert "WAITING Deploy" in p.stdout
    assert "NONGREEN Deploy" not in p.stdout, "WAITING must not be reported as a plain failure"
    assert "VERDICT WAITING" in p.stdout


def test_pending_check_alone_is_nonzero_in_fixture_mode():
    # A fixture is a single static snapshot — there is no "poll again later" in
    # fixture mode, so a still-pending check must surface as nonzero too, not as a
    # silent pass.
    checks = _all_green_checks(extra=[])
    checks[1]["state"] = "IN_PROGRESS"
    checks[1]["bucket"] = "pending"
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive"], path_override=_no_gh_path())
    assert p.returncode != 0, p.stdout + p.stderr


# ── --expect is additive, and duplicates are deduped ───────────────────────────


def test_expect_flag_adds_to_the_baseline_set():
    checks = _all_green_checks(extra=[_check("Custom gate", "SUCCESS", "pass")])
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive", "--expect", "Custom gate"], path_override=_no_gh_path())
    assert p.returncode == 0, p.stdout + p.stderr
    assert "GREEN Custom gate" in p.stdout


def test_expect_flag_for_a_missing_custom_check_still_fails():
    path = _write_fixture(_all_green_checks())
    p = _run(["--fixture", path, "--no-derive", "--expect", "Custom gate that never ran"], path_override=_no_gh_path())
    assert p.returncode != 0
    assert "NONGREEN Custom gate that never ran ABSENT" in p.stdout


# ── path-derived defaults (grounded in the real workflow `paths:` filters) ─────


def _derive(files_newline):
    script = f"""
set -uo pipefail
source '{_SCRIPT}' --source-only
derive_expected_checks '{files_newline}'
"""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=15)


def test_deploy_only_change_gets_only_the_baseline():
    p = _derive("deploy/wait_pr_green.sh\\ntests/test_wait_pr_green.py")
    names = p.stdout.strip().split("\n")
    assert names == _BASELINE, p.stdout + p.stderr


def test_site_change_adds_the_v4_gate_checks():
    p = _derive("site/data/index.html")
    assert "Migration coverage + HTML well-formedness" in p.stdout
    assert "Render + accuracy gate (local render)" in p.stdout
    for n in _BASELINE:
        assert n in p.stdout


def test_lambdas_change_adds_wiki_drift_gates():
    p = _derive("lambdas/common/constants.py")
    assert "Wiki drift gates" in p.stdout


def test_claude_commands_change_adds_wiki_drift_gates():
    # .claude/commands/** is in docs-ci.yml's pull_request paths — this is exactly
    # the path this issue's own PR touches (reconcile-branch.md), so the derivation
    # must catch it.
    p = _derive(".claude/commands/reconcile-branch.md")
    assert "Wiki drift gates" in p.stdout


# ── structural guarantees: never merges, never truncates a sha ────────────────


def _non_comment_lines(path):
    """Lines of executable bash, with full-line `#` comments stripped — the header
    block deliberately NAMES the forbidden patterns in prose (documenting what NOT
    to do), so a plain substring search over the whole file would false-positive on
    its own warning comments. Inline trailing comments are left alone (none of the
    patterns under test appear as inline comments in this script)."""
    with open(path, encoding="utf-8") as f:
        return [line for line in f if not line.strip().startswith("#")]


def test_script_never_calls_gh_pr_merge():
    code = "".join(_non_comment_lines(_SCRIPT))
    assert "pr merge" not in code, "wait_pr_green.sh must never merge — the verdict is always a separate, deliberate command"


def test_script_never_hand_rolls_a_short_sha_actions_runs_query():
    code = "".join(_non_comment_lines(_SCRIPT))
    assert "actions/runs?head_sha=" not in code, "the short-sha query class this script exists to eliminate"


def test_script_rejects_a_non_full_sha_defensively():
    with open(_SCRIPT, encoding="utf-8") as f:
        content = f.read()
    assert "-ne 40" in content, "the full-sha assertion must be a literal length check, not a comment-only promise"


def test_missing_pr_number_and_missing_fixture_both_print_usage_and_exit_nonzero():
    # No network, no `gh` call — argument validation happens before either mode's
    # gh/fixture branch, so this must fail fast on argument shape alone.
    p = _run([], path_override=_no_gh_path())
    assert p.returncode != 0
    assert "usage:" in (p.stdout + p.stderr).lower()
    assert "GH_WAS_CALLED" not in p.stderr
