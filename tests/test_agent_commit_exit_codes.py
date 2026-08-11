"""tests/test_agent_commit_exit_codes.py — pin agent_commit.sh's exit codes (#2464).

The incident: the script printed a refusal ("❌ black would reformat …") and the
caller's `&&` chain still proceeded — `git push` no-op'd and a `git worktree remove
--force` destroyed uncommitted work. A refused commit MUST be a nonzero exit, on
EVERY refusal path (guard the set, not the instance), and the success path must
stay exit 0 with the committed-count line, because concurrent implementer agents
compose on both.

Harness: each test runs the real script (the copy in this repo's deploy/) inside a
throwaway git repo, with stub `black`/`ruff` executables prepended to PATH whose
exit codes the test controls. The stubs make the suite deterministic (no dependency
on which black is installed) and mutation-prove the gate: the SAME harness produces
exit 0 when the tools pass and nonzero when they fail, so a refusal assertion cannot
pass vacuously. Every refusal test also asserts HEAD did not move — the behavioural
half of "refused".

#2570: the script no longer trusts a tool just because it is on PATH — it resolves
black/ruff through deploy/lib/pinned_formatters.sh, which accepts a binary only if
it reports the version requirements-dev.txt declares. So the scratch repo now also
carries the real resolver plus a requirements-dev.txt pinning the stubs' own
reported version. That is not a loosening: swap the pin and the stubs are refused
(tests/test_formatter_pin_resolution.py proves that half against the real pin).

Trap avoided deliberately: subprocess.run with capture_output, never a shell
pipeline — a pipe eats the exit code, which is this bug's whole genre.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "deploy" / "agent_commit.sh"
RESOLVER = REPO_ROOT / "deploy" / "lib" / "pinned_formatters.sh"

# The version the stubs report AND the version the scratch repo pins — they must
# match or the resolver refuses the stubs before their exit code is ever consulted.
STUB_VERSION = "0.0.0-stub"

STUB = """#!/bin/sh
# Test stub for {tool}: --version always succeeds; anything else exits ${{{var}:-0}}.
if [ "$1" = "--version" ]; then
  echo "{tool} {version}"
  exit 0
fi
exit "${{{var}:-0}}"
"""


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def scratch(tmp_path):
    """A throwaway git repo containing the real script, plus a stub-tool bin dir."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], capture_output=True, text=True, check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")

    (repo / "deploy").mkdir()
    (repo / "deploy" / "agent_commit.sh").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "deploy" / "lib").mkdir()
    (repo / "deploy" / "lib" / "pinned_formatters.sh").write_text(RESOLVER.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "requirements-dev.txt").write_text(f"black=={STUB_VERSION}\nruff=={STUB_VERSION}\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "notes.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    for tool, var in (("black", "BLACK_STUB_EXIT"), ("ruff", "RUFF_STUB_EXIT")):
        stub = bin_dir / tool
        stub.write_text(STUB.format(tool=tool, var=var, version=STUB_VERSION), encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return repo, bin_dir


def run_script(scratch, args, black_exit=0, ruff_exit=0):
    repo, bin_dir = scratch
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["BLACK_STUB_EXIT"] = str(black_exit)
    env["RUFF_STUB_EXIT"] = str(ruff_exit)
    return subprocess.run(
        ["bash", "deploy/agent_commit.sh", *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
    )


# ── The success path: exit 0 + the committed-count line (interface pinned) ─────


def test_success_exits_zero_with_committed_line(scratch):
    repo, _ = scratch
    before = _head(repo)
    (repo / "scripts" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    r = run_script(scratch, ["feat: ok", "scripts/mod.py"])
    assert r.returncode == 0, r.stderr
    assert "✅ committed 1 path(s)" in r.stdout
    assert "REFUSED" not in r.stdout + r.stderr
    assert _head(repo) != before  # the commit actually landed


# ── The refusal set: every discard path is a nonzero exit + no commit ──────────


def _assert_refused(repo, before, r):
    assert r.returncode != 0, f"refusal exited 0 (#2464 regression)\nstdout:{r.stdout}\nstderr:{r.stderr}"
    assert "REFUSED" in r.stderr
    assert "✅ committed" not in r.stdout
    assert _head(repo) == before, "a refused commit moved HEAD"


def test_black_refusal_exits_nonzero(scratch):
    """The measured incident path: black rejects the staged Python."""
    repo, _ = scratch
    before = _head(repo)
    (repo / "scripts" / "mod.py").write_text("x = ( 1,2 )\n", encoding="utf-8")
    r = run_script(scratch, ["feat: bad", "scripts/mod.py"], black_exit=1)
    assert "black would reformat" in r.stderr
    _assert_refused(repo, before, r)


def test_ruff_refusal_exits_nonzero(scratch):
    repo, _ = scratch
    before = _head(repo)
    (repo / "scripts" / "mod.py").write_text("import os\n", encoding="utf-8")
    r = run_script(scratch, ["feat: bad", "scripts/mod.py"], ruff_exit=1)
    assert "ruff check failed" in r.stderr
    _assert_refused(repo, before, r)


def test_doc_literal_refusal_exits_nonzero(scratch):
    repo, _ = scratch
    (repo / "CLAUDE.md").write_text("literal\n", encoding="utf-8")
    before = _head(repo)
    r = run_script(scratch, ["docs: nope", "CLAUDE.md"])
    assert "doc-sync literal" in r.stderr
    _assert_refused(repo, before, r)


def test_unresolved_conflict_refusal_exits_nonzero(scratch):
    repo, _ = scratch
    _git(repo, "checkout", "-q", "-b", "other")
    (repo / "notes.txt").write_text("theirs\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "theirs")
    _git(repo, "checkout", "-q", "main")
    (repo / "notes.txt").write_text("ours\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "ours")
    merge = subprocess.run(["git", "-C", str(repo), "merge", "other"], capture_output=True, text=True)
    assert merge.returncode != 0  # a real UU conflict exists
    before = _head(repo)
    (repo / "scripts" / "mod.py").write_text("x = 3\n", encoding="utf-8")
    r = run_script(scratch, ["feat: mid-merge", "scripts/mod.py"])
    assert "unresolved merge conflict" in r.stderr
    _assert_refused(repo, before, r)


def test_missing_path_refusal_exits_nonzero(scratch):
    repo, _ = scratch
    before = _head(repo)
    r = run_script(scratch, ["feat: ghost", "scripts/does_not_exist.py"])
    assert "path does not exist" in r.stderr
    _assert_refused(repo, before, r)


def test_nothing_staged_refusal_exits_nonzero(scratch):
    repo, _ = scratch
    before = _head(repo)
    r = run_script(scratch, ["feat: noop", "scripts/mod.py"])  # unchanged vs HEAD
    assert "nothing staged" in r.stderr
    _assert_refused(repo, before, r)


def test_version_skew_refusal_exits_nonzero(scratch):
    """#2570: a formatter at the WRONG version is a refusal, not a fallback.

    Same harness, same passing stubs — only the declared pin moves. The script must
    refuse rather than run the tool it can see, because a gate running a different
    black than CI refuses correct code and blesses code CI will reject.
    """
    repo, _ = scratch
    skewed_pin = "9.9.9-not-the-stub"
    (repo / "requirements-dev.txt").write_text(f"black=={skewed_pin}\nruff=={skewed_pin}\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "skew the pin")
    before = _head(repo)
    (repo / "scripts" / "mod.py").write_text("x = 4\n", encoding="utf-8")
    r = run_script(scratch, ["feat: skewed toolchain", "scripts/mod.py"])
    assert "FAILED CLOSED" in r.stderr, r.stderr
    assert skewed_pin in r.stderr, r.stderr
    assert STUB_VERSION in r.stderr, "the refusal must name the version it rejected"
    _assert_refused(repo, before, r)


def test_usage_refusal_exits_nonzero(scratch):
    repo, _ = scratch
    before = _head(repo)
    r = run_script(scratch, ["message only, no paths"])
    assert "usage:" in r.stderr
    assert r.returncode == 2
    assert "REFUSED" in r.stderr
    assert _head(repo) == before
